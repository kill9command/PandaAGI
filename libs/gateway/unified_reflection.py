"""
Unified Reflection Gate

Simplified reflection gate with only 2 decisions: PROCEED or CLARIFY.

Features:
- Query type detection (RETRY, ACTION, RECALL, INFORMATIONAL, CLARIFICATION)
- Pronoun resolution from context
- Confidence scoring (0.0-1.0)
- Document-driven (context.md §2)
- Strategy hints from turn history patterns
- Statistics tracking

ARCHITECTURAL DECISION (2025-12-30):
Simplified from 5 decisions to 2 per architecture docs:
- PROCEED: Continue to Planner (confidence >= 0.4)
- CLARIFY: Ask user for clarification (confidence < 0.4)

Removed decisions (handled elsewhere):
- GATHER_MORE: Context Gatherer runs once; Planner handles gaps via memory tools
- NEED_INFO: Planner handles via memory.search tool
- CACHED: Response cache handled at gateway level before reflection
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from libs.gateway.recipe_loader import load_recipe, RecipeNotFoundError

logger = logging.getLogger(__name__)


class ReflectionDecision(Enum):
    """
    Unified reflection decisions - simplified to 2 options.

    ARCHITECTURAL DECISION (2025-12-30):
    Reduced from 5 to 2 decisions for cleaner flow:
    - PROCEED: Continue to Planner (handles all execution paths)
    - CLARIFY: Ask user for clarification (only when truly ambiguous)

    Removed decisions (now handled elsewhere):
    - GATHER_MORE: Planner handles gaps via memory tools
    - NEED_INFO: Planner handles via memory.search tool
    - CACHED: Response cache checked at gateway level before reflection
    """
    PROCEED = "PROCEED"              # Continue to Planner
    CLARIFY = "CLARIFY"              # Ask user for clarification


class QueryType(Enum):
    """Query type classification"""
    RETRY = "RETRY"                  # User wants fresh execution
    ACTION = "ACTION"                # User wants new results
    RECALL = "RECALL"                # User wants previous results
    INFORMATIONAL = "INFORMATIONAL"  # User wants knowledge
    CLARIFICATION = "CLARIFICATION"  # User wants elaboration


@dataclass
class InfoRequest:
    """Request for additional system information"""
    type: str       # "memory", "quick_search", "claims"
    query: str      # What to search for
    reason: str     # Why needed
    priority: int = 1  # 1=high, 2=medium, 3=low


@dataclass
class StrategyHint:
    """Strategy hint for query processing (from turn history patterns)"""
    strategy: str                    # retrieval_first, direct, iterative, conservative
    lesson_id: Optional[str] = None  # Deprecated - was from lesson_store
    requirements: List[str] = field(default_factory=list)
    validation_strictness: str = "MEDIUM"  # LOW, MEDIUM, HIGH


@dataclass
class UnifiedReflectionResult:
    """Result from unified reflection gate"""
    decision: ReflectionDecision
    confidence: float
    reasoning: str
    query_type: Optional[QueryType] = None
    action_verbs: List[str] = field(default_factory=list)
    is_followup: bool = False  # Whether this query references prior context

    # Conditional fields based on decision
    clarification_question: Optional[str] = None  # For CLARIFY
    strategy_hint: Optional[StrategyHint] = None

    # DEPRECATED fields (kept for backwards compatibility during migration)
    # These decisions have been removed - see ReflectionDecision docstring
    refined_query: Optional[str] = None         # DEPRECATED: GATHER_MORE removed
    info_requests: List[InfoRequest] = field(default_factory=list)  # DEPRECATED: NEED_INFO removed
    cache_key: Optional[str] = None             # DEPRECATED: CACHED removed

    # Metadata
    timestamp: float = field(default_factory=time.time)
    token_cost: int = 300  # Standard budget

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        result = {
            "_type": "REFLECTION_UNIFIED",
            "decision": self.decision.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "query_type": self.query_type.value if self.query_type else None,
            "action_verbs": self.action_verbs,
            "is_followup": self.is_followup,
            "refined_query": self.refined_query,
            "info_requests": [
                {"type": r.type, "query": r.query, "reason": r.reason, "priority": r.priority}
                for r in self.info_requests
            ] if self.info_requests else None,
            "clarification_question": self.clarification_question,
            "cache_key": self.cache_key,
            "strategy_hint": {
                "strategy": self.strategy_hint.strategy,
                "lesson_id": self.strategy_hint.lesson_id,
                "requirements": self.strategy_hint.requirements,
                "validation_strictness": self.strategy_hint.validation_strictness
            } if self.strategy_hint else None,
            "timestamp": self.timestamp,
            "token_cost": self.token_cost
        }
        return result

    # Compatibility properties for V4 code
    @property
    def can_proceed(self) -> bool:
        return self.decision == ReflectionDecision.PROCEED

    @property
    def needs_clarification(self) -> bool:
        return self.decision == ReflectionDecision.CLARIFY

    @property
    def needs_info(self) -> bool:
        """DEPRECATED: NEED_INFO decision removed. Always returns False."""
        return False

    @property
    def action(self):
        """Compatibility with V4 MetaAction"""
        from apps.services.orchestrator.meta_reflection import MetaAction
        mapping = {
            ReflectionDecision.PROCEED: MetaAction.PROCEED,
            ReflectionDecision.CLARIFY: MetaAction.REQUEST_CLARIFICATION,
        }
        return mapping.get(self.decision, MetaAction.PROCEED)


class UnifiedReflectionGate:
    """
    Unified reflection gate with simplified 2-decision model.

    Document-driven, recipe-based implementation with:
    - Query type detection (RETRY, ACTION, RECALL, INFORMATIONAL, CLARIFICATION)
    - Pronoun resolution from context
    - Strategy hints from turn history patterns
    - Statistics tracking

    Outputs only 2 decisions:
    - PROCEED: Continue to Planner (handles all execution paths)
    - CLARIFY: Ask user for clarification (only when truly ambiguous)
    """

    def __init__(
        self,
        llm_client: Any = None,
        recipe_name: str = "reflection/unified",
        accept_threshold: float = 0.8,
        reject_threshold: float = 0.4
    ):
        """
        Initialize unified reflection gate.

        Args:
            llm_client: LLM client for calling the model
            recipe_name: Recipe name (e.g., "reflection/unified")
            accept_threshold: Confidence >= this → PROCEED
            reject_threshold: Confidence < this → CLARIFY
        """
        self.llm_client = llm_client
        self.recipe_name = recipe_name
        self.accept_threshold = accept_threshold
        self.reject_threshold = reject_threshold

        # Cache for loaded recipe and prompt
        self._recipe_cache = None
        self._prompt_cache: Optional[str] = None

        # Statistics tracking (from V4)
        self.stats = {
            "total_calls": 0,
            "by_decision": {d.value: 0 for d in ReflectionDecision},
            "by_query_type": {q.value: 0 for q in QueryType},
            "total_tokens": 0,
            "avg_confidence": 0.0
        }

    @property
    def recipe(self):
        """
        Load the reflection recipe with caching.
        """
        if self._recipe_cache is not None:
            return self._recipe_cache

        try:
            self._recipe_cache = load_recipe(self.recipe_name)
            logger.debug(f"[UnifiedReflection] Loaded recipe: {self.recipe_name}")
            return self._recipe_cache
        except RecipeNotFoundError as e:
            logger.warning(f"[UnifiedReflection] Recipe not found: {e}")
            return None

    @property
    def prompt_template(self) -> str:
        """
        Load the reflection prompt template via recipe system with caching.
        """
        if self._prompt_cache is not None:
            return self._prompt_cache

        # Try to load via recipe
        recipe = self.recipe
        if recipe:
            try:
                self._prompt_cache = recipe.get_prompt()
                logger.debug(f"[UnifiedReflection] Loaded prompt via recipe: {self.recipe_name}")
                return self._prompt_cache
            except Exception as e:
                logger.warning(f"[UnifiedReflection] Failed to load prompt from recipe: {e}")

        # Fallback to minimal prompt
        logger.warning(f"[UnifiedReflection] Could not load prompt from recipe {self.recipe_name}, using minimal prompt")
        self._prompt_cache = "Analyze the query and context, then decide: PROCEED or CLARIFY."
        return self._prompt_cache

    async def reflect(
        self,
        context_doc: 'ContextDocument',
        max_gather_iterations: int = 1,  # DEPRECATED: No longer used
        iteration: int = 0  # DEPRECATED: No longer used
    ) -> Tuple['ContextDocument', UnifiedReflectionResult]:
        """
        Perform unified reflection on the context document.

        Analyzes the query and gathered context, outputting PROCEED or CLARIFY.

        Args:
            context_doc: Context document with §0 (query) and §1 (gathered context)
            max_gather_iterations: DEPRECATED - kept for API compatibility
            iteration: DEPRECATED - kept for API compatibility

        Returns:
            Tuple of (updated context_doc, reflection result)
        """
        start_time = time.time()
        self.stats["total_calls"] += 1

        logger.info(f"[UnifiedReflection] Starting reflection (iteration {iteration + 1})")

        try:
            # Build prompt with context
            prompt = self._build_prompt(context_doc)

            # Call LLM
            if self.llm_client:
                result = await self._call_llm(prompt)
            else:
                # Fallback to heuristics
                result = self._heuristic_reflection(context_doc)

            # Update statistics
            self._update_stats(result)

            # Append §2 to context document (only first time)
            if not context_doc.has_section(2):
                section_content = self._format_section2(result)
                context_doc.append_section(2, "Reflection Decision", section_content)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[UnifiedReflection] Result: {result.decision.value}, "
                f"confidence={result.confidence:.2f}, query_type={result.query_type.value if result.query_type else 'unknown'}, "
                f"elapsed={elapsed_ms:.0f}ms"
            )

            return context_doc, result

        except Exception as e:
            logger.error(f"[UnifiedReflection] Error: {e}")
            # Fallback: proceed with caution
            result = UnifiedReflectionResult(
                decision=ReflectionDecision.PROCEED,
                confidence=0.6,
                reasoning=f"Reflection error, proceeding with caution: {str(e)}",
                query_type=QueryType.ACTION
            )
            return context_doc, result

    def _build_prompt(self, context_doc: 'ContextDocument') -> str:
        """Build the reflection prompt with context"""
        # Get context.md content (§0 and §1)
        context_content = context_doc.get_markdown_up_to(1)

        prompt = f"""{self.prompt_template}

---

## Current Input

{context_content}

---

Now analyze this query and context, then produce the JSON output.
"""
        return prompt

    async def _call_llm(self, prompt: str) -> UnifiedReflectionResult:
        """Call LLM and parse response"""
        try:
            response = await self.llm_client.call(
                prompt=prompt,
                role="reflection",
                max_tokens=300,
                temperature=0.1  # Low for consistent decisions
            )

            return self._parse_llm_response(response)

        except Exception as e:
            logger.warning(f"[UnifiedReflection] LLM call failed: {e}")
            raise

    def _parse_llm_response(self, response: str) -> UnifiedReflectionResult:
        """Parse LLM response into UnifiedReflectionResult"""

        # Try to extract JSON from response using balanced brace approach
        json_str = self._extract_json_object(response)

        if json_str:
            try:
                data = json.loads(json_str)
                return self._dict_to_result(data)
            except json.JSONDecodeError as e:
                logger.warning(f"[UnifiedReflection] Could not parse JSON: {e}")

        # Fallback: parse key fields from text
        return self._parse_text_response(response)

    def _extract_json_object(self, text: str) -> Optional[str]:
        """
        Extract a JSON object from text using balanced brace counting.

        Handles nested objects (strategy_hint, info_requests) correctly
        by tracking brace depth rather than using greedy regex.

        Args:
            text: Text potentially containing JSON

        Returns:
            JSON string if found, None otherwise
        """
        # Find the first opening brace
        start = text.find('{')
        if start == -1:
            return None

        # Track brace depth to find matching close
        depth = 0
        in_string = False
        escape_next = False

        for i, char in enumerate(text[start:], start):
            if escape_next:
                escape_next = False
                continue

            if char == '\\' and in_string:
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    # Found matching closing brace
                    json_str = text[start:i + 1]
                    # Validate it looks like our expected output
                    if '"_type"' in json_str or '"decision"' in json_str:
                        return json_str
                    # If this JSON doesn't have expected fields, keep looking
                    # for another JSON object in the text
                    next_start = text.find('{', i + 1)
                    if next_start != -1:
                        return self._extract_json_object(text[next_start:])
                    return json_str

        # No balanced JSON found
        return None

    def _dict_to_result(self, data: Dict[str, Any]) -> UnifiedReflectionResult:
        """Convert parsed JSON dict to UnifiedReflectionResult"""

        # Parse decision - map legacy values to simplified 2-decision model
        decision_str = data.get("decision", "PROCEED").upper()

        # Map legacy decisions to current ones
        legacy_to_current = {
            "PROCEED": ReflectionDecision.PROCEED,
            "CLARIFY": ReflectionDecision.CLARIFY,
            # Legacy decisions - map to PROCEED (Planner handles these now)
            "GATHER_MORE": ReflectionDecision.PROCEED,
            "NEED_INFO": ReflectionDecision.PROCEED,
            "CACHED": ReflectionDecision.PROCEED,
        }

        decision = legacy_to_current.get(decision_str, ReflectionDecision.PROCEED)

        # Parse query type
        query_type_str = data.get("query_type", "ACTION")
        try:
            query_type = QueryType(query_type_str.upper()) if query_type_str else None
        except ValueError:
            query_type = QueryType.ACTION

        # Parse info requests
        info_requests = []
        if data.get("info_requests"):
            for req in data["info_requests"]:
                info_requests.append(InfoRequest(
                    type=req.get("type", "memory"),
                    query=req.get("query", ""),
                    reason=req.get("reason", ""),
                    priority=req.get("priority", 1)
                ))

        # Parse strategy hint
        strategy_hint = None
        if data.get("strategy_hint"):
            sh = data["strategy_hint"]
            strategy_hint = StrategyHint(
                strategy=sh.get("strategy", "direct"),
                lesson_id=sh.get("lesson_id"),
                requirements=sh.get("requirements", []),
                validation_strictness=sh.get("validation_strictness", "MEDIUM")
            )

        return UnifiedReflectionResult(
            decision=decision,
            confidence=float(data.get("confidence", 0.8)),
            reasoning=data.get("reasoning", ""),
            query_type=query_type,
            action_verbs=data.get("action_verbs", []),
            is_followup=bool(data.get("is_followup", False)),
            refined_query=data.get("refined_query"),
            info_requests=info_requests,
            clarification_question=data.get("clarification_question"),
            cache_key=data.get("cache_key"),
            strategy_hint=strategy_hint
        )

    def _parse_text_response(self, response: str) -> UnifiedReflectionResult:
        """Fallback parser for non-JSON responses"""

        # Extract decision
        decision = ReflectionDecision.PROCEED
        for d in ReflectionDecision:
            if d.value in response.upper():
                decision = d
                break

        # Extract confidence
        conf_match = re.search(r'confidence["\s:]+(\d+\.?\d*)', response, re.IGNORECASE)
        confidence = float(conf_match.group(1)) if conf_match else 0.7

        # Extract query type
        query_type = QueryType.ACTION
        for qt in QueryType:
            if qt.value in response.upper():
                query_type = qt
                break

        # Extract reasoning
        reason_match = re.search(r'reasoning["\s:]+["\']?([^"\'}\n]+)', response, re.IGNORECASE)
        reasoning = reason_match.group(1).strip() if reason_match else "Parsed from text response"

        return UnifiedReflectionResult(
            decision=decision,
            confidence=confidence,
            reasoning=reasoning,
            query_type=query_type
        )

    def _heuristic_reflection(self, context_doc: 'ContextDocument') -> UnifiedReflectionResult:
        """
        Simplified heuristic fallback when LLM is unavailable.

        DESIGN PRINCIPLE: Complex query classification should be done by the LLM prompt,
        not Python pattern matching. This fallback just defaults to PROCEED and lets
        downstream components (Planner, Coordinator) handle the query appropriately.
        """
        gathered = context_doc.get_section(1) or ""

        # Check for strategy hints in context (still useful even in fallback)
        strategy_hint = None
        if "### Relevant Strategy Lessons" in gathered:
            strategy_hint = self._extract_strategy_hint(gathered)

        # Simple fallback: default to PROCEED with ACTION type
        # The Planner and Coordinator are better equipped to handle query classification
        return UnifiedReflectionResult(
            decision=ReflectionDecision.PROCEED,
            confidence=0.7,
            reasoning="LLM unavailable - defaulting to PROCEED and letting Planner decide",
            query_type=QueryType.ACTION,
            action_verbs=[],
            is_followup=False,
            strategy_hint=strategy_hint
        )

    def _extract_strategy_hint(self, gathered: str) -> Optional[StrategyHint]:
        """Extract strategy hint from gathered context"""
        if "### Relevant Strategy Lessons" not in gathered:
            return None

        # Simple extraction - look for key fields
        strategy_match = re.search(r'Strategy:\s*(\w+)', gathered)
        lesson_match = re.search(r'lesson_id:\s*(\S+)', gathered)
        strictness_match = re.search(r'Validation Strictness:\s*(\w+)', gathered)

        if strategy_match:
            return StrategyHint(
                strategy=strategy_match.group(1).lower(),
                lesson_id=lesson_match.group(1) if lesson_match else None,
                requirements=[],  # Would need more complex parsing
                validation_strictness=strictness_match.group(1).upper() if strictness_match else "MEDIUM"
            )

        return None

    def _format_section2(self, result: UnifiedReflectionResult) -> str:
        """Format §2 content for context.md"""
        lines = [
            f"**Decision:** {result.decision.value}",
            f"**Confidence:** {result.confidence:.2f}",
            f"**Reasoning:** {result.reasoning}",
        ]

        if result.query_type:
            lines.append(f"**Query Type:** {result.query_type.value}")

        if result.action_verbs:
            lines.append(f"**Action Verbs:** {', '.join(result.action_verbs)}")

        if result.refined_query:
            lines.append(f"**Refined Query:** {result.refined_query}")

        if result.info_requests:
            lines.append("**Info Requests:**")
            for req in result.info_requests:
                lines.append(f"  - {req.type}: {req.query} ({req.reason})")

        if result.clarification_question:
            lines.append(f"**Clarification:** {result.clarification_question}")

        if result.strategy_hint:
            lines.append(f"**Strategy Hint:** {result.strategy_hint.strategy}")
            if result.strategy_hint.lesson_id:
                lines.append(f"  - Lesson: {result.strategy_hint.lesson_id}")

        # Route hint for downstream phases (simplified to 2 routes)
        route = "planner" if result.decision == ReflectionDecision.PROCEED else "user"
        lines.append(f"**Route:** {route}")

        return "\n".join(lines)

    def _update_stats(self, result: UnifiedReflectionResult):
        """Update statistics"""
        self.stats["by_decision"][result.decision.value] += 1
        if result.query_type:
            self.stats["by_query_type"][result.query_type.value] += 1
        self.stats["total_tokens"] += result.token_cost

        # Update rolling average confidence
        n = self.stats["total_calls"]
        old_avg = self.stats["avg_confidence"]
        self.stats["avg_confidence"] = old_avg + (result.confidence - old_avg) / n

    def get_stats(self) -> Dict[str, Any]:
        """Get reflection statistics"""
        total = max(1, self.stats["total_calls"])
        return {
            "total_calls": self.stats["total_calls"],
            "decision_rates": {
                k: v / total for k, v in self.stats["by_decision"].items()
            },
            "query_type_rates": {
                k: v / total for k, v in self.stats["by_query_type"].items()
            },
            "total_tokens": self.stats["total_tokens"],
            "avg_tokens_per_call": self.stats["total_tokens"] / total,
            "avg_confidence": self.stats["avg_confidence"]
        }
