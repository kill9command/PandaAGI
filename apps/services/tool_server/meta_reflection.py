"""
Meta-Reflection System - Core Infrastructure

Implements fractal meta-reflection pattern where each role asks:
"Can I proceed with confidence, or do I need help?"

This is the PRIMARY gate at every level (Guide, Coordinator, Context Manager).
"""

import logging
import re
import time
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from apps.services.tool_server.shared import call_llm_text
from libs.gateway.llm.recipe_loader import load_recipe, RecipeNotFoundError

logger = logging.getLogger(__name__)

# Recipe cache for reflection prompts
_recipe_cache: Dict[str, Any] = {}


def _load_reflection_prompt(prompt_name: str) -> str:
    """
    Load a reflection prompt via the recipe system.

    Uses caching to avoid repeated recipe loads.

    Args:
        prompt_name: Prompt name without extension (e.g., "guide_reflection")

    Returns:
        Prompt content as string, or empty string if not found
    """
    if prompt_name in _recipe_cache:
        return _recipe_cache[prompt_name]

    try:
        recipe = load_recipe(f"reflection/{prompt_name}")
        prompt_content = recipe.get_prompt()
        _recipe_cache[prompt_name] = prompt_content
        logger.debug(f"[MetaReflection] Loaded prompt via recipe: reflection/{prompt_name}")
        return prompt_content
    except RecipeNotFoundError:
        logger.warning(f"[MetaReflection] Recipe not found: reflection/{prompt_name}")
        return ""
    except Exception as e:
        logger.warning(f"[MetaReflection] Failed to load prompt from recipe: {e}")
        return ""


class MetaAction(Enum):
    """Actions resulting from meta-reflection"""
    PROCEED = "proceed"  # Confidence high enough, continue
    REQUEST_CLARIFICATION = "request_clarification"  # Can't proceed, need user input
    NEEDS_ANALYSIS = "needs_analysis"  # Unsure, escalate to deeper check
    NEED_INFO = "need_info"  # Need additional information from system (memory/search/etc)


@dataclass
class InfoRequest:
    """Request for additional information from system"""
    type: str  # "memory", "quick_search", "claims", etc.
    query: str  # Search query or memory lookup term
    reason: str  # Why this info is needed
    priority: int = 1  # 1=high, 2=medium, 3=low


@dataclass
class MetaReflectionResult:
    """Result of meta-reflection gate"""
    confidence: float  # 0.0-1.0 confidence score
    can_proceed: bool
    needs_clarification: bool
    needs_analysis: bool
    reason: str
    action: MetaAction
    role: str  # Which role performed reflection (guide/coordinator/context_manager)
    needs_info: bool = False  # NEW: Need additional information
    info_requests: List[InfoRequest] = field(default_factory=list)  # NEW: Info requests
    query_type: Optional[str] = None  # NEW: Query type (action/recall/informational/clarification)
    action_verbs: List[str] = field(default_factory=list)  # NEW: Detected action verbs
    timestamp: float = field(default_factory=time.time)

    @property
    def token_cost(self) -> int:
        """Meta-reflection costs ~100-120 tokens (with query type classification)"""
        return 120 if self.query_type else 100

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/monitoring"""
        return {
            "confidence": self.confidence,
            "can_proceed": self.can_proceed,
            "needs_clarification": self.needs_clarification,
            "needs_analysis": self.needs_analysis,
            "needs_info": self.needs_info,
            "reason": self.reason,
            "action": self.action.value,
            "role": self.role,
            "query_type": self.query_type,
            "action_verbs": self.action_verbs,
            "info_requests": [
                {"type": req.type, "query": req.query, "reason": req.reason, "priority": req.priority}
                for req in self.info_requests
            ],
            "timestamp": self.timestamp,
            "token_cost": self.token_cost
        }


@dataclass
class ProcessContext:
    """Context information for meta-reflection"""
    current_confidence: float
    evidence: List[Any]
    task_domain: str
    available_tools: Optional[List[str]] = None
    original_query: Optional[str] = None
    execution_history: List[Any] = field(default_factory=list)


class MetaReflectionGate:
    """
    Universal meta-reflection gate used at every level.

    Core question: "Can I proceed with confidence, or do I need help?"

    This is the PRIMARY gate at each boundary, implementing fractal reflection
    where every role asks itself the same fundamental question at its abstraction level.
    """

    def __init__(
        self,
        llm_url: str,
        llm_model: str,
        llm_api_key: str,
        accept_threshold: float = 0.8,
        reject_threshold: float = 0.4,
        max_tokens: int = 80,
        timeout: float = 10.0
    ):
        """
        Initialize meta-reflection gate.

        Args:
            llm_url: LLM endpoint URL
            llm_model: Model identifier
            llm_api_key: API key for authentication
            accept_threshold: Confidence >= this → PROCEED
            reject_threshold: Confidence < this → REQUEST_CLARIFICATION
            max_tokens: Max tokens for meta-reflection response
            timeout: Timeout for LLM call
        """
        self.llm_url = llm_url
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self.accept_threshold = accept_threshold
        self.reject_threshold = reject_threshold
        self.max_tokens = max_tokens
        self.timeout = timeout

        # Statistics tracking
        self.stats = {
            "total_calls": 0,
            "proceed_count": 0,
            "clarification_count": 0,
            "analysis_count": 0,
            "need_info_count": 0,
            "total_tokens": 0,
            "by_role": {}
        }

    async def can_i_proceed(
        self,
        role: Literal["guide", "coordinator", "context_manager"],
        input_data: Dict[str, Any],
        context: Optional[ProcessContext] = None
    ) -> MetaReflectionResult:
        """
        Primary gate: LLM asks itself if it can proceed.

        This is the FIRST check at every boundary, before any other analysis.

        Args:
            role: Which role is asking (guide/coordinator/context_manager)
            input_data: Role-specific input (query for guide, ticket for coordinator, etc.)
            context: Additional process context

        Returns:
            MetaReflectionResult with decision and reasoning
        """
        start_time = time.time()

        # Update statistics
        self.stats["total_calls"] += 1
        if role not in self.stats["by_role"]:
            self.stats["by_role"][role] = {"calls": 0, "proceed": 0, "clarify": 0, "analyze": 0, "need_info": 0}
        self.stats["by_role"][role]["calls"] += 1

        logger.info(f"[MetaReflect-{role.upper()}] Asking: Can I proceed?")

        try:
            # Build role-specific prompt
            prompt = self._build_meta_prompt(role, input_data, context)

            # VERBOSE: Log prompt for debugging (truncate to 500 chars)
            logger.debug(f"[MetaReflect-{role.upper()}] Prompt preview (first 500 chars):\n{prompt[:500]}")

            # Call LLM using centralized utility
            # REFLEX role (temp=0.4) for meta-reflection gate decisions
            response = await call_llm_text(
                prompt=prompt,
                llm_url=self.llm_url,
                llm_model=self.llm_model,
                llm_api_key=self.llm_api_key,
                max_tokens=self.max_tokens,
                temperature=0.4
            )

            # Parse response
            result = self._parse_meta_response(response, role)

            # Update statistics
            self.stats["total_tokens"] += result.token_cost
            if result.can_proceed:
                self.stats["proceed_count"] += 1
                self.stats["by_role"][role]["proceed"] += 1
            elif result.needs_clarification:
                self.stats["clarification_count"] += 1
                self.stats["by_role"][role]["clarify"] += 1
            elif result.needs_info:
                self.stats["need_info_count"] += 1
                self.stats["by_role"][role]["need_info"] += 1
            else:
                self.stats["analysis_count"] += 1
                self.stats["by_role"][role]["analyze"] += 1

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[MetaReflect-{role.upper()}] Result: {result.action.value}, "
                f"confidence={result.confidence:.2f}, elapsed={elapsed_ms:.0f}ms"
            )
            logger.info(f"[MetaReflect-{role.upper()}] Reason: {result.reason}")

            return result

        except Exception as e:
            logger.error(f"[MetaReflect-{role.upper()}] Error: {e}")
            # Fallback: if meta-reflection fails, proceed with caution
            return MetaReflectionResult(
                confidence=0.6,
                can_proceed=True,
                needs_clarification=False,
                needs_analysis=False,
                reason=f"Meta-reflection error, proceeding with caution: {str(e)}",
                action=MetaAction.PROCEED,
                role=role
            )

    def _build_meta_prompt(
        self,
        role: str,
        input_data: Dict[str, Any],
        context: Optional[ProcessContext]
    ) -> str:
        """Build role-specific meta-reflection prompt"""

        if role == "guide":
            query = input_data.get("query", "")

            # NEW: Use live session context if available
            live_context = input_data.get("live_context", "")
            turn_number = input_data.get("turn_number", 0)
            reflection_round = input_data.get("round", 1)
            available_info = input_data.get("available_info", "")
            has_memory_context = input_data.get("has_memory_context", False)

            # VERBOSE: Check if Recent Conversation is present
            if "Recent Conversation:" in live_context:
                logger.info(f"[MetaPrompt-GUIDE] ✓ Recent Conversation found in live_context ({len(live_context)} chars)")
            else:
                logger.warning(f"[MetaPrompt-GUIDE] ✗ Recent Conversation NOT found in live_context ({len(live_context)} chars)")

            # Fallback to old history-based context if live context not provided
            if not live_context:
                history = input_data.get("history", [])
                if history and len(history) >= 2:
                    recent_msgs = history[-2:]
                    live_context = "Recent conversation:\n" + "\n".join([
                        f"- {msg.get('role', 'user')}: {msg.get('content', '')[:100]}"
                        for msg in recent_msgs
                    ])
                else:
                    live_context = "(no context - first turn)"

            info_context_section = ""
            if available_info:
                info_context_section = f"\n\nInformation Available from Previous Rounds:\n{available_info}"

            # Load base prompt from file
            base_prompt = _load_reflection_prompt("guide_reflection")
            if not base_prompt:
                # Fallback inline prompt if file not found
                base_prompt = """You are the Guide. Classify the query type (RETRY/ACTION/RECALL/INFORMATIONAL/CLARIFICATION) and evaluate confidence.

Format:
QUERY_TYPE: [type]
ACTION_VERBS: [verbs or none]
CONFIDENCE: [0.0-1.0]
REASON: [explanation]
DECISION: [PROCEED or NEED_INFO or CLARIFY]"""

            return f"""{base_prompt}

---

**Query:** "{query}"

**Living Session Context (Turn {turn_number}, Reflection Round {reflection_round}):**
{live_context}{info_context_section}

Now classify and respond:"""

        elif role == "coordinator":
            goal = input_data.get("goal", "")
            ticket_context = input_data.get("context", "")
            subtasks = input_data.get("subtasks", [])

            available_tools = []
            if context and context.available_tools:
                available_tools = context.available_tools[:10]  # Limit to 10 for token efficiency

            # Load base prompt from file
            base_prompt = _load_reflection_prompt("coordinator_reflection")
            if not base_prompt:
                # Fallback inline prompt if file not found
                base_prompt = """You are the Coordinator. Evaluate planning confidence (0.0-1.0).

Respond ONLY in this format:
CONFIDENCE: [0.0-1.0]
REASON: [one sentence]
CAN_PROCEED: [YES/NO/UNSURE]"""

            return f"""{base_prompt}

---

**Task Ticket:**
Goal: {goal}
Context: {ticket_context}
Subtasks: {len(subtasks)} items
Available tools: {', '.join(available_tools) if available_tools else 'unknown'}

Now evaluate and respond:"""

        elif role == "context_manager":
            claims = input_data.get("claims", [])
            sources = input_data.get("sources", [])

            original_query = context.original_query if context else "unknown"

            # Load base prompt from file
            base_prompt = _load_reflection_prompt("context_manager_reflection")
            if not base_prompt:
                # Fallback inline prompt if file not found
                base_prompt = """You are the Context Manager. Evaluate evidence quality (0.0-1.0).

Respond ONLY in this format:
CONFIDENCE: [0.0-1.0]
REASON: [one sentence]
CAN_PROCEED: [YES/NO/UNSURE]"""

            return f"""{base_prompt}

---

**Evidence Summary:**
Original query: {original_query}
Evidence collected: {len(claims)} claims
Sources: {len(set(sources))} unique sources

Now evaluate and respond:"""

        else:
            raise ValueError(f"Unknown role: {role}")

    def _parse_meta_response(self, response: str, role: str) -> MetaReflectionResult:
        """Parse LLM meta-reflection response"""

        # Extract confidence score
        confidence_match = re.search(r'CONFIDENCE:\s*(0\.\d+|1\.0|0|1)', response, re.IGNORECASE)
        if confidence_match:
            confidence = float(confidence_match.group(1))
        else:
            logger.warning(f"Could not parse confidence from response: {response[:100]}")
            confidence = 0.5  # Default to uncertain

        # Try new DECISION format first (supports NEED_INFO)
        decision_match = re.search(r'DECISION:\s*(PROCEED|NEED_INFO|CLARIFY|YES|NO|UNSURE)', response, re.IGNORECASE)
        if decision_match:
            decision_str = decision_match.group(1).upper()
        else:
            # Fallback to old CAN_PROCEED format
            can_proceed_match = re.search(r'CAN_PROCEED:\s*(YES|NO|UNSURE)', response, re.IGNORECASE)
            if can_proceed_match:
                decision_str = can_proceed_match.group(1).upper()
            else:
                logger.warning(f"Could not parse DECISION from response: {response[:100]}")
                decision_str = "UNSURE"

        # Extract reason
        reason_match = re.search(r'REASON:\s*(.+?)(?:\n|$)', response)
        if reason_match:
            reason = reason_match.group(1).strip()
        else:
            reason = "No reason provided"

        # Extract QUERY_TYPE (NEW)
        query_type = None
        query_type_match = re.search(
            r'QUERY_TYPE:\s*(RETRY|ACTION|RECALL|INFORMATIONAL|CLARIFICATION|METADATA)',
            response,
            re.IGNORECASE
        )
        if query_type_match:
            query_type = query_type_match.group(1).lower()

        # Extract ACTION_VERBS (NEW)
        action_verbs = []
        action_verbs_match = re.search(r'ACTION_VERBS:\s*(.+?)(?:\n|$)', response, re.IGNORECASE)
        if action_verbs_match:
            verbs_str = action_verbs_match.group(1).strip()
            if verbs_str.lower() != "none":
                # Split by commas and clean up
                action_verbs = [v.strip() for v in verbs_str.split(',') if v.strip()]

        # Parse INFO_REQUESTS if present
        info_requests = []
        if "INFO_REQUESTS:" in response:
            info_section = response[response.find("INFO_REQUESTS:"):]
            # Parse each request (simple line-by-line parsing)
            current_request = {}
            for line in info_section.split('\n')[1:]:  # Skip "INFO_REQUESTS:" header
                line = line.strip()
                if not line or line.startswith('Example'):
                    break
                if line.startswith('- type:'):
                    if current_request:
                        # Save previous request
                        info_requests.append(InfoRequest(**current_request))
                    current_request = {'type': line.split(':', 1)[1].strip(), 'priority': 1}
                elif line.startswith('query:'):
                    current_request['query'] = line.split(':', 1)[1].strip()
                elif line.startswith('reason:'):
                    current_request['reason'] = line.split(':', 1)[1].strip()
                elif line.startswith('priority:'):
                    current_request['priority'] = int(line.split(':', 1)[1].strip())
            # Add last request
            if current_request and 'query' in current_request and 'reason' in current_request:
                info_requests.append(InfoRequest(**current_request))

        # Determine action based on decision string
        if decision_str in ("PROCEED", "YES") and confidence >= self.accept_threshold:
            action = MetaAction.PROCEED
            can_proceed = True
            needs_clarification = False
            needs_analysis = False
            needs_info = False
        elif decision_str == "NEED_INFO":
            action = MetaAction.NEED_INFO
            can_proceed = False
            needs_clarification = False
            needs_analysis = False
            needs_info = True
        elif decision_str in ("CLARIFY", "NO") or confidence < self.reject_threshold:
            action = MetaAction.REQUEST_CLARIFICATION
            can_proceed = False
            needs_clarification = True
            needs_analysis = False
            needs_info = False
        else:  # UNSURE or borderline confidence
            action = MetaAction.NEEDS_ANALYSIS
            can_proceed = False
            needs_clarification = False
            needs_analysis = True
            needs_info = False

        return MetaReflectionResult(
            confidence=confidence,
            can_proceed=can_proceed,
            needs_clarification=needs_clarification,
            needs_analysis=needs_analysis,
            needs_info=needs_info,
            reason=reason,
            action=action,
            role=role,
            query_type=query_type,
            action_verbs=action_verbs,
            info_requests=info_requests
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get meta-reflection statistics"""
        return {
            "total_calls": self.stats["total_calls"],
            "proceed_rate": self.stats["proceed_count"] / max(1, self.stats["total_calls"]),
            "clarification_rate": self.stats["clarification_count"] / max(1, self.stats["total_calls"]),
            "analysis_rate": self.stats["analysis_count"] / max(1, self.stats["total_calls"]),
            "need_info_rate": self.stats["need_info_count"] / max(1, self.stats["total_calls"]),
            "total_tokens": self.stats["total_tokens"],
            "avg_tokens_per_call": self.stats["total_tokens"] / max(1, self.stats["total_calls"]),
            "by_role": self.stats["by_role"]
        }

    def write_document(self, result: MetaReflectionResult, turn_dir: 'TurnDirectory') -> 'pathlib.Path':
        """
        Write meta_reflection.md to turn directory (v4.0 document-driven).

        Args:
            result: Meta-reflection result
            turn_dir: TurnDirectory instance

        Returns:
            Path to written file
        """
        import pathlib
        from libs.gateway.context.doc_writers import write_meta_reflection_md
        return write_meta_reflection_md(turn_dir, result)
