"""
Context Gatherer 2-Phase Implementation

Consolidates 4-phase gathering (SCAN → READ → EXTRACT → COMPILE) into 2 phases:
- Phase 1: RETRIEVAL (merged SCAN + READ)
- Phase 2: SYNTHESIS (merged EXTRACT + COMPILE)

Token Budget: ~10,500 tokens (vs 14,500 for 4-phase) = 27% reduction

Key Design:
- Deterministic N-1 pre-loading for follow-ups (runs BEFORE LLM call)
- Single RETRIEVAL prompt handles turn identification AND context evaluation
- Single SYNTHESIS prompt handles extraction (if links) AND compilation
- Feature flag controlled: CONTEXT_GATHERER_VERSION=2phase

See panda_system_docs/architecture/CONTEXT_GATHERER_2PHASE_PLAN.md for full design.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone

from .context_document import ContextDocument
from .query_analyzer import QueryAnalysis, ContentReference
from .visit_record import VisitRecordReader, VisitRecordManifest

# Recipe loader for prompt loading
from libs.gateway.recipe_loader import load_recipe, RecipeNotFoundError


from .context_gatherer_docs import (
    TurnIndexDoc, TurnIndexEntry,
    ContextBundleDoc, ContextBundleEntry,
    LinkedDocsDoc,
    write_doc
)
from .context_gatherer_2phase_docs import (
    RetrievalResultDoc, RetrievalTurn, LinkToFollow,
    SynthesisInputDoc
)

# Import optional dependencies with graceful fallback
try:
    from apps.services.orchestrator.session_intelligence_cache import SessionIntelligenceCache
    INTEL_CACHE_AVAILABLE = True
except ImportError:
    INTEL_CACHE_AVAILABLE = False
    SessionIntelligenceCache = None

try:
    from libs.gateway.research_index_db import get_research_index_db
    RESEARCH_INDEX_AVAILABLE = True
except ImportError:
    RESEARCH_INDEX_AVAILABLE = False
    get_research_index_db = None

# ARCHITECTURAL DECISION (2025-12-30): Removed lesson_store import
# Learning now happens implicitly via turn indexing
LESSON_STORE_AVAILABLE = False

# Import forever memory (obsidian_memory) with graceful fallback
try:
    from apps.tools.memory import search_memory, get_user_preferences, MemoryResult
    FOREVER_MEMORY_AVAILABLE = True
except ImportError:
    FOREVER_MEMORY_AVAILABLE = False
    search_memory = None
    get_user_preferences = None
    MemoryResult = None

# Import memory context builder for intelligent summarization
try:
    from libs.gateway.memory_context_builder import MemoryContextBuilder, get_memory_context_builder
    from libs.gateway.token_budget_allocator import TokenBudgetAllocator, get_allocator
    MEMORY_CONTEXT_BUILDER_AVAILABLE = True
except ImportError:
    MEMORY_CONTEXT_BUILDER_AVAILABLE = False
    MemoryContextBuilder = None
    get_memory_context_builder = None
    TokenBudgetAllocator = None
    get_allocator = None

# TTL Configuration
PRICE_CLAIM_TTL_HOURS = int(os.getenv("PRICE_CLAIM_TTL_HOURS", "24"))
RETRY_PRICE_TTL_HOURS = int(os.getenv("RETRY_PRICE_TTL_HOURS", "1"))

# Link-Following Limits (#43 from IMPLEMENTATION_ROADMAP.md)
# Level 0: context.md, Level 1: research.md, Level 2: claim sources
MAX_LINK_DEPTH = int(os.getenv("MAX_LINK_DEPTH", "2"))
TOKEN_BUDGET_LINKING = int(os.getenv("TOKEN_BUDGET_LINKING", "8000"))  # Stop at 80% consumed

# User Feedback Detection Patterns
# These patterns detect when a user is correcting or rejecting the previous response
CORRECTION_PATTERNS = {
    "explicit_correction": [
        r"^no[,.]?\s",           # "No, that's not what I meant"
        r"^not what i (asked|meant|wanted)",
        r"^that'?s (wrong|incorrect|not right)",
        r"^actually[,.]?\s",     # "Actually, I wanted..."
        r"^i (meant|wanted|asked)",
        r"^wrong[,.]?\s",
    ],
    "abandonment_retry": [
        r"let me (rephrase|try again|ask differently)",
        r"never ?mind",
        r"forget (that|it)",
        r"start over",
        r"let'?s try",
        r"ignore (that|my|the)",
    ],
    "disappointment": [
        r"^that'?s not (helpful|what|useful)",
        r"^this (doesn'?t|isn'?t) (help|answer|what)",
        r"^(you'?re|that'?s) not (understanding|getting)",
        r"^i (already|don'?t) (know|said|told)",
    ],
    "repetition_request": [
        r"^(can you )?(try|search|look) again",
        r"^(find|show|get) (me )?(something|other|different)",
        r"^(any|are there|what about) other",
    ],
}

# Compile patterns for efficiency
_COMPILED_CORRECTION_PATTERNS = {
    category: [re.compile(p, re.IGNORECASE) for p in patterns]
    for category, patterns in CORRECTION_PATTERNS.items()
}

logger = logging.getLogger(__name__)


class ContextGatherer2Phase:
    """
    2-Phase Context Gatherer with Document IO.

    Phase 1 (RETRIEVAL): Single LLM call that:
    - Identifies relevant turns from index (was SCAN)
    - Evaluates loaded contexts (was READ)
    - Decides direct_info vs links_to_follow

    Phase 2 (SYNTHESIS): Single LLM call that:
    - Extracts from linked docs if present (was EXTRACT)
    - Compiles final context.md §1 (was COMPILE)
    """

    def __init__(
        self,
        session_id: str,
        llm_client: Any,
        turns_dir: Path = None,
        sessions_dir: Path = None,
        index_limit: int = 20,
        mode: str = "chat",
        repo: str = None,
        user_id: str = None
    ):
        self.session_id = session_id
        self.llm_client = llm_client
        self.user_id = user_id or "default"
        # Use new consolidated path structure under obsidian_memory/Users/
        self.turns_dir = turns_dir or Path(f"panda_system_docs/obsidian_memory/Users/{self.user_id}/turns")
        self.sessions_dir = sessions_dir or Path(f"panda_system_docs/obsidian_memory/Users/{self.user_id}/sessions")
        self.index_limit = index_limit
        self.mode = mode  # "chat" or "code"
        self.repo = repo  # Repository path for code mode

        # Retry context
        self.retry_context: Optional[Dict[str, Any]] = None
        self.failed_urls: set = set()

        # Link-following tracking (#43: prevent circular references and enforce depth limits)
        self._visited_paths: set = set()
        self._link_tokens_consumed: int = 0

        # Supplementary sources
        self.cached_intelligence: Optional[Dict[str, Any]] = None
        self.intel_cache_metadata: Optional[Dict[str, Any]] = None
        self.research_index_results: List[Dict[str, Any]] = []
        self.forever_memory_results: List[Any] = []  # Obsidian memory search results
        self.user_preferences_memory: Optional[Any] = None  # User preferences from memory
        self.formatted_memory_context: str = ""  # Pre-built memory context from MemoryContextBuilder
        self.matching_lessons: List[Any] = []
        self.session_memory: Dict[str, str] = {}
        self.query_topic_path: Optional[str] = None
        self.repo_context: Optional[str] = None  # Repository context for code mode
        self.user_feedback: Dict[str, Any] = {}  # User feedback on previous response

        # Memory context builder for intelligent summarization
        self.memory_context_builder = (
            get_memory_context_builder() if MEMORY_CONTEXT_BUILDER_AVAILABLE else None
        )
        self.budget_allocator = (
            get_allocator() if MEMORY_CONTEXT_BUILDER_AVAILABLE else None
        )

        # Load recipes
        self.recipes = self._load_recipes()

    def _load_recipes(self) -> Dict[str, Dict]:
        """Load recipe configs for each phase using the recipe loader."""
        recipes = {}

        for phase in ["retrieval", "synthesis"]:
            recipe_name = f"pipeline/phase1_context_gatherer_{phase}"
            try:
                recipe = load_recipe(recipe_name)
                # Extract system_prompt from raw spec
                recipes[phase] = recipe._raw_spec
                logger.debug(f"[ContextGatherer2Phase] Loaded recipe: {recipe_name}")
            except RecipeNotFoundError:
                logger.debug(f"[ContextGatherer2Phase] Recipe not found: {recipe_name}")
                recipes[phase] = {"system_prompt": f"Default {phase} prompt"}

        return recipes

    def _detect_user_feedback(
        self,
        current_query: str,
        previous_response: Optional[str] = None,
        previous_query: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Detect if the current query indicates user feedback on the previous response.

        Detects patterns like:
        - Explicit correction: "No, that's not what I meant"
        - Abandonment: "Never mind, let me rephrase"
        - Disappointment: "That's not helpful"
        - Repetition request: "Can you try again?"

        Args:
            current_query: The current user query
            previous_response: The previous assistant response (optional)
            previous_query: The previous user query (optional)

        Returns:
            Dict with:
                - detected: bool - whether feedback was detected
                - feedback_type: str - category of feedback (explicit_correction, abandonment_retry, etc.)
                - confidence: float - confidence in the detection (0.0-1.0)
                - patterns_matched: List[str] - which patterns matched
        """
        result = {
            "detected": False,
            "feedback_type": "",
            "confidence": 0.0,
            "patterns_matched": []
        }

        if not current_query:
            return result

        query_lower = current_query.strip().lower()

        # Check compiled patterns
        for category, patterns in _COMPILED_CORRECTION_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(query_lower):
                    result["patterns_matched"].append(f"{category}:{pattern.pattern}")
                    if not result["detected"]:
                        result["detected"] = True
                        result["feedback_type"] = category

        # Calculate confidence based on number of matched patterns and category
        if result["detected"]:
            num_matches = len(result["patterns_matched"])

            # Base confidence by category
            category_confidence = {
                "explicit_correction": 0.85,
                "abandonment_retry": 0.75,
                "disappointment": 0.80,
                "repetition_request": 0.70,
            }
            base_conf = category_confidence.get(result["feedback_type"], 0.60)

            # Boost for multiple matches
            result["confidence"] = min(0.95, base_conf + (num_matches - 1) * 0.05)

            logger.info(
                f"[ContextGatherer2Phase] User feedback detected: {result['feedback_type']} "
                f"(confidence: {result['confidence']:.2f}, patterns: {result['patterns_matched']})"
            )

        return result

    def _update_previous_turn_feedback(
        self,
        current_turn: int,
        feedback: Dict[str, Any]
    ):
        """
        Update the previous turn's index entry with feedback status.

        Args:
            current_turn: Current turn number (previous is current - 1)
            feedback: Feedback detection result
        """
        if current_turn <= 1:
            return

        previous_turn = current_turn - 1

        try:
            from .turn_index_db import TurnIndexDB
            turn_index = TurnIndexDB()

            # Map feedback type to status
            feedback_status = "rejected" if feedback.get("detected") else "neutral"

            turn_index.update_feedback_status(
                turn_number=previous_turn,
                feedback_status=feedback_status,
                confidence=feedback.get("confidence", 0.0)
            )

            logger.info(
                f"[ContextGatherer2Phase] Updated turn {previous_turn} feedback: "
                f"{feedback_status} (confidence: {feedback.get('confidence', 0):.2f})"
            )
        except Exception as e:
            logger.warning(f"[ContextGatherer2Phase] Failed to update feedback status: {e}")

    async def gather(self, query: str, turn_number: int) -> ContextDocument:
        """
        Execute 2-phase gathering loop.

        Phase 1 (RETRIEVAL): Identify turns + evaluate contexts in single LLM call
        Phase 2 (SYNTHESIS): Extract from links (if any) + compile context.md §1
        """
        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        turn_dir.mkdir(parents=True, exist_ok=True)

        # Reset link-following tracking for this gather operation (#43)
        self._visited_paths.clear()
        self._link_tokens_consumed = 0

        # Load query analysis from Phase 0 (if available)
        self.query_analysis: Optional[QueryAnalysis] = QueryAnalysis.load(turn_dir)
        if self.query_analysis:
            logger.info(f"[ContextGatherer2Phase] Loaded query_analysis.json: resolved={self.query_analysis.was_resolved}, action={self.query_analysis.action_needed}")
            # Use resolved query for gathering (has references made explicit)
            effective_query = self.query_analysis.resolved_query
            if self.query_analysis.content_reference:
                logger.info(f"[ContextGatherer2Phase] Content reference: '{self.query_analysis.content_reference.title[:50]}...' (turn {self.query_analysis.content_reference.source_turn})")
        else:
            logger.debug("[ContextGatherer2Phase] No query_analysis.json found, using original query")
            effective_query = query

        # Load retry context if this is a validation retry
        self._load_retry_context(turn_dir)

        # Check supplementary sources (using effective_query with resolved references)
        self._check_intelligence_cache(effective_query)
        _, inherited_topic = self._detect_followup(effective_query, turn_number)
        self._check_research_index(effective_query, intent=None, inherited_topic=inherited_topic)

        # Get action_needed from query analysis for memory budget allocation
        memory_intent = "informational"  # Default (legacy value for compatibility)
        if self.query_analysis:
            # Map action_needed + data_requirements to legacy intent for memory budget
            data_reqs = self.query_analysis.data_requirements or {}
            if data_reqs.get("needs_current_prices"):
                memory_intent = "commerce"
            elif self.query_analysis.action_needed == "recall_memory":
                memory_intent = "recall"
            elif self.query_analysis.action_needed == "navigate_to_site":
                memory_intent = "navigation"

        await self._check_forever_memory(effective_query, intent=memory_intent)  # Check obsidian_memory for relevant knowledge
        self._check_matching_lessons(effective_query)
        self._load_session_memory()
        self._gather_repo_context()  # Gather repo context for code mode

        # Detect user feedback on previous response
        self.user_feedback = self._detect_user_feedback(effective_query)
        if self.user_feedback.get("detected"):
            # Update turn index DB with feedback status if we can identify the previous turn
            self._update_previous_turn_feedback(turn_number, self.user_feedback)

        logger.info(f"[ContextGatherer2Phase] Starting 2-phase gather for turn {turn_number}")

        # ==================================================================
        # FAST PATH 1: Navigation intent - skip heavy context gathering
        # ==================================================================
        # For "go to X and do Y" queries, prior context is irrelevant.
        # Skip turn search and just include user preferences.
        if self.query_analysis and self.query_analysis.action_needed == "navigate_to_site":
            logger.info("[ContextGatherer2Phase] Navigation action - using minimal context fast path")
            return self._create_navigation_context(query, turn_number, turn_dir)

        # ==================================================================
        # FAST PATH 2: Check visit_records before LLM retrieval (Plan-Act-Review)
        # ==================================================================
        # If we have a content_reference with has_visit_record=True, check if
        # the cached data can answer the question directly (skips LLM call)
        fast_path_result = await self._try_visit_record_fast_path(
            effective_query, query, turn_number, turn_dir
        )
        if fast_path_result:
            logger.info("[ContextGatherer2Phase] Fast path succeeded - returning cached context")
            return fast_path_result

        # Write query document (include both original and resolved if different)
        if self.query_analysis and self.query_analysis.was_resolved:
            query_doc = f"# Query\n\n**Resolved:** {effective_query}\n\n**Original:** {query}\n"
        else:
            query_doc = f"# Query\n\n{query}\n"
        write_doc(turn_dir / "query.md", query_doc)

        # ==================================================================
        # PHASE 1: RETRIEVAL (merged SCAN + READ)
        # ==================================================================
        logger.info("[ContextGatherer2Phase] Phase 1: RETRIEVAL")

        # If we have a content_reference with source_turn, ensure that turn is prioritized
        priority_turn = None
        if self.query_analysis and self.query_analysis.content_reference:
            priority_turn = self.query_analysis.content_reference.source_turn
            if priority_turn:
                logger.info(f"[ContextGatherer2Phase] Prioritizing turn {priority_turn} from content_reference")

        retrieval_result = await self._phase_retrieval(
            effective_query, turn_number, inherited_topic, priority_turn=priority_turn
        )
        write_doc(turn_dir / "retrieval_result.md", retrieval_result.to_markdown())

        # Check for no-context cases
        if not retrieval_result.relevant_turns:
            if self.cached_intelligence or self.research_index_results:
                logger.info("[ContextGatherer2Phase] No turns but have cached intel/research")
                return self._create_context_from_cache(effective_query, turn_number, turn_dir)
            logger.info("[ContextGatherer2Phase] No relevant turns, minimal context")
            return self._create_minimal_context(effective_query, turn_number, turn_dir)

        # ==================================================================
        # PHASE 2: SYNTHESIS (merged EXTRACT + COMPILE)
        # ==================================================================
        logger.info("[ContextGatherer2Phase] Phase 2: SYNTHESIS")

        context_doc = await self._phase_synthesis(
            effective_query, turn_number, retrieval_result, turn_dir
        )
        write_doc(turn_dir / "context.md", context_doc.get_markdown())

        logger.info(f"[ContextGatherer2Phase] Gather complete for turn {turn_number}")
        return context_doc

    # ==================================================================
    # PHASE 1: RETRIEVAL
    # ==================================================================

    async def _phase_retrieval(
        self,
        query: str,
        turn_number: int,
        inherited_topic: Optional[str],
        priority_turn: Optional[int] = None
    ) -> RetrievalResultDoc:
        """
        Phase 1: Single LLM call for turn identification + context evaluation.

        Key innovation: N-1 pre-loading for follow-ups happens BEFORE the LLM call,
        ensuring the context is always available (deterministic, not LLM-dependent).

        Args:
            query: The query to gather context for (should be resolved_query from Phase 0)
            turn_number: Current turn number
            inherited_topic: Topic inherited from previous turn (if followup)
            priority_turn: Turn number to prioritize loading (from content_reference.source_turn)
        """
        # Build turn index
        turn_index = self._build_turn_index(turn_number)

        # Determine which turn to preload:
        # 1. If priority_turn specified (from content_reference), use that
        # 2. Otherwise fall back to N-1 for follow-ups
        preload_turn = None
        is_followup = False

        if priority_turn is not None:
            preload_turn = priority_turn
            logger.info(f"[ContextGatherer2Phase] Preloading priority turn {priority_turn} from content_reference")
        else:
            # Fall back to N-1 pre-loading for follow-ups
            is_followup, _ = self._preload_for_followup(
                query, turn_number, turn_index
            )
            if is_followup:
                preload_turn = turn_number - 1

        # Load contexts for recent turns (top 3-5)
        context_bundle = self._build_context_bundle_for_retrieval(
            query, turn_index, preloaded_turn=preload_turn
        )

        # Build RETRIEVAL prompt from recipe
        recipe = self.recipes.get("retrieval", {})
        system_prompt = recipe.get("system_prompt", self._default_retrieval_prompt())

        # Build user prompt with context data
        user_prompt = f"""TURN INDEX:
{turn_index.to_markdown()}

LOADED CONTEXTS (top {len(context_bundle.entries)} turns):
{context_bundle.to_markdown()}

{self._format_followup_hint(is_followup, inherited_topic)}

---

CURRENT QUERY: {query}

===== YOUR TASK =====

1. IDENTIFY which turns from the index are relevant to the CURRENT QUERY
2. EVALUATE the loaded contexts - what info can be used directly?
3. DECIDE if any links need to be followed for more detail

CRITICAL: usable_info MUST come from the turn's content shown in LOADED CONTEXTS above.
Do NOT attribute information from the CURRENT QUERY to prior turns.

Output JSON with this structure:
{{
  "turns": [
    {{
      "turn": <turn_number>,
      "relevance": "critical|high|medium|low",
      "reason": "why this turn is relevant",
      "usable_info": "specific info from this turn that can be used directly (from LOADED CONTEXTS, not current query)"
    }}
  ],
  "links_to_follow": [
    {{
      "turn": <turn_number>,
      "path": "path/to/research.md or research.json",
      "reason": "why we need more detail from this doc",
      "extract": ["products", "prices", "recommendations"]
    }}
  ],
  "sufficient": true/false,
  "missing_info": "what info is still needed (if any)",
  "reasoning": "your reasoning process"
}}"""

        try:
            full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

            response_text = await self.llm_client.call(
                prompt=full_prompt,
                role="context_gatherer",
                max_tokens=600,
                temperature=0.1
            )

            json_data = self._extract_json(response_text)

            # Create result with followup metadata
            result = RetrievalResultDoc.from_llm_response(
                query=query,
                response=json_data,
                is_followup=is_followup,
                inherited_topic=inherited_topic
            )

            # SAFETY: Ensure N-1 is included for follow-ups (double-check LLM output)
            if is_followup:
                # Get the preloaded context entry (first entry in bundle if available)
                preloaded_entry = context_bundle.entries[0] if context_bundle.entries else None
                result = self._ensure_n1_in_result(result, turn_index, preloaded_entry)

            return result

        except Exception as e:
            logger.error(f"[ContextGatherer2Phase] RETRIEVAL phase failed: {e}")
            return RetrievalResultDoc(
                query=query,
                timestamp=datetime.utcnow().isoformat() + "Z",
                relevant_turns=[],
                direct_info={},
                links_to_follow=[],
                sufficient=True,
                missing_info=f"RETRIEVAL failed: {e}",
                reasoning="Error during retrieval phase",
                is_followup=is_followup,
                inherited_topic=inherited_topic
            )

    def _preload_for_followup(
        self,
        query: str,
        turn_number: int,
        turn_index: TurnIndexDoc
    ) -> tuple:
        """
        Always pre-load N-1 context for the Context Gatherer.

        ARCHITECTURAL FIX (2026-01-04): Removed hardcoded pattern matching.
        Always load N-1 and let the LLM decide if it's relevant to the current query.
        This fixes cases like "the thread" which need N-1 context but didn't match
        the old pronoun/signal patterns.

        Returns:
            (n1_available: bool, preloaded_context: Optional[ContextBundleEntry])
        """
        if turn_number <= 1 or not turn_index.entries:
            return False, None

        # Always load N-1 context
        n1_turn = turn_index.entries[0].turn_number
        n1_dir = self.turns_dir / f"turn_{n1_turn:06d}"
        context_path = n1_dir / "context.md"

        if not context_path.exists():
            logger.warning(f"[ContextGatherer2Phase] N-1 context not found at {context_path}")
            return False, None

        try:
            content = context_path.read_text()
            entry = self._parse_context_for_bundle(content, n1_turn, n1_dir)
            if entry:
                logger.info(
                    f"[ContextGatherer2Phase] PRE-LOADED N-1 (Turn {n1_turn}, topic={entry.topic})"
                )
                return True, entry
        except Exception as e:
            logger.warning(f"[ContextGatherer2Phase] Failed to pre-load N-1: {e}")

        return False, None

    def _ensure_n1_in_result(
        self,
        result: RetrievalResultDoc,
        turn_index: TurnIndexDoc,
        preloaded: Optional[ContextBundleEntry]
    ) -> RetrievalResultDoc:
        """
        Safety check: Ensure N-1 is in results for follow-up queries.

        Even with strong prompting, LLMs may miss N-1. This is the backup.
        """
        if not turn_index.entries or not preloaded:
            return result

        n1_turn = turn_index.entries[0].turn_number
        existing_turns = {t.turn_number for t in result.relevant_turns}

        if n1_turn in existing_turns:
            return result

        # N-1 missing - add it
        logger.warning(
            f"[ContextGatherer2Phase] SAFETY: Adding N-1 (Turn {n1_turn}) that LLM missed"
        )

        n1_entry = RetrievalTurn(
            turn_number=n1_turn,
            relevance="critical",
            reason=f"N-1 turn (immediately preceding). Follow-up query refers to topic: {preloaded.topic}",
            usable_info=preloaded.summary[:500] if preloaded.summary else "",
            expected_info=f"Context for pronouns referring to {preloaded.topic}",
            load_priority=0
        )

        result.relevant_turns.insert(0, n1_entry)
        if preloaded.summary:
            result.direct_info[str(n1_turn)] = preloaded.summary[:500]

        result.reasoning += f"\n\n[SAFETY] Force-added N-1 (Turn {n1_turn}) for follow-up handling."

        return result

    def _format_followup_hint(
        self,
        is_followup: bool,
        inherited_topic: Optional[str]
    ) -> str:
        """Format follow-up hint for the prompt."""
        if not is_followup:
            return ""

        return f"""
**FOLLOW-UP DETECTED**: This query appears to be a follow-up.
{f'**Inherited Topic:** {inherited_topic}' if inherited_topic else ''}

IMPORTANT: For follow-up queries, the N-1 turn (immediately preceding) is CRITICAL.
It contains the subject that pronouns like "some", "it", "that" refer to.
"""

    # ==================================================================
    # PHASE 2: SYNTHESIS
    # ==================================================================

    async def _phase_synthesis(
        self,
        query: str,
        turn_number: int,
        retrieval_result: RetrievalResultDoc,
        turn_dir: Path
    ) -> ContextDocument:
        """
        Phase 2: Single LLM call for extraction (if links) + compilation.

        If links_to_follow is non-empty, includes linked docs and extraction instructions.
        Otherwise, just compiles from direct_info.
        """
        # Load linked documents if needed
        linked_docs = {}
        if retrieval_result.has_links_to_follow():
            linked_docs = self._load_linked_docs(retrieval_result)
            write_doc(turn_dir / "linked_docs.md", LinkedDocsDoc(query, linked_docs).to_markdown())

        # Build SYNTHESIS prompt from recipe
        recipe = self.recipes.get("synthesis", {})
        system_prompt = recipe.get("system_prompt", self._default_synthesis_prompt())

        # Build input sections
        direct_info_section = self._format_direct_info(retrieval_result)
        linked_docs_section = self._format_linked_docs(linked_docs, retrieval_result) if linked_docs else ""
        supplementary_section = self._format_supplementary_sources()

        # Build follow-up context section if this is a follow-up query
        followup_section = ""
        if retrieval_result.is_followup and retrieval_result.inherited_topic:
            followup_section = f"""
===== FOLLOW-UP QUERY CONTEXT =====
**This is a follow-up to the previous turn.**
**Inherited Topic:** {retrieval_result.inherited_topic}

CRITICAL: For follow-up queries like "search for more", "find more", "what else":
- INHERIT the topic from the previous turn (shown above)
- Do NOT pick a different topic from User Preferences or Forever Memory
- The Topic Classification should be: {retrieval_result.inherited_topic}
"""

        # Build user prompt with context data
        user_prompt = f"""CURRENT QUERY: {query}
TURN NUMBER: {turn_number}
{followup_section}
===== DIRECT INFORMATION =====
{direct_info_section}

{linked_docs_section}

{supplementary_section}

===== YOUR TASK =====

{"TASK 1 - EXTRACT: Extract relevant information from the linked documents." if linked_docs else ""}
{"Focus on: " + ", ".join(set(s for link in retrieval_result.links_to_follow for s in link.sections_to_extract)) if linked_docs else ""}

{"TASK 2 - " if linked_docs else ""}COMPILE: Create the section 1 Gathered Context section for context.md.

Structure your output as MARKDOWN with these sections (ONLY include sections with RELEVANT content):
- ### Repository Context (if code mode with repo - INCLUDE FIRST if present)
- ### Topic Classification (Topic + Intent)
- ### Prior Turn Context (what we learned from relevant turns)
- ### User Preferences (ONLY if preferences relate to current query topic)
- ### Forever Memory Knowledge (ONLY if knowledge documents relate to current query topic)
- ### Prior Research Intelligence (if research index matches AND relates to query)
- ### Cached Intelligence (if intelligence cache hit AND relates to query)
- ### Relevant Strategy Lessons (if lessons matched AND relate to query)

CRITICAL - RELEVANCE FILTERING:
**OMIT sections entirely if their content is NOT relevant to the current query.**
Example: Query about "Russian troll farms" → OMIT User Preferences about hamsters (irrelevant)
Example: Query about "Syrian hamsters" → OMIT Forever Memory about troll farms (irrelevant)

CRITICAL - FOLLOW-UP TOPIC INHERITANCE:
**For follow-up queries (e.g., "search for more", "find more"), INHERIT the topic from the previous turn.**
- If "FOLLOW-UP QUERY CONTEXT" section exists above, USE that inherited topic
- Do NOT pick a different topic from User Preferences just because it's mentioned
- Example: Previous turn was about laptops → "search for more" = search for more LAPTOPS (not hamsters)

IMPORTANT: If supplementary sources contain "### Repository Context", include it FIRST.
IMPORTANT: When forever memory includes **Sources:** blocks, COPY THEM VERBATIM.
IMPORTANT: Do NOT add a "Memory Status" section - this will be added programmatically.
CRITICAL: When "Follow-up Detected" appears, include N-1 turn's content in Prior Turn Context even if query terms don't appear directly.

Output MARKDOWN only (no JSON wrapper)."""

        try:
            full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

            response_text = await self.llm_client.call(
                prompt=full_prompt,
                role="context_gatherer",
                max_tokens=1200,
                temperature=0.2
            )

            # Create context document
            context_doc = ContextDocument(
                turn_number=turn_number,
                session_id=self.session_id,
                query=query
            )
            # Preserve mode and repo for tool execution
            context_doc.mode = self.mode
            context_doc.repo = self.repo

            # CRITICAL: Pass user_purpose through to downstream phases
            # Without this, get_action_needed() returns "unclear" by default,
            # which prevents proper routing decisions.
            if self.query_analysis:
                # Set the full query_analysis dict for get_action_needed() to use
                context_doc.set_section_0(self.query_analysis.to_dict())

            # Clean response and add as §1
            gathered_context = self._clean_markdown(response_text)

            # Add user feedback section if rejection was detected
            feedback_section = self._format_feedback_section()
            if feedback_section:
                gathered_context = feedback_section + "\n\n" + gathered_context

            # Add research section if available
            # Pass whether prior turn context was extracted so Memory Status is accurate
            has_prior_context = bool(retrieval_result.direct_info)
            research_section = self._format_research_section(has_prior_turn_context=has_prior_context)
            if research_section:
                gathered_context += "\n\n" + research_section

            # Add lessons section if available
            lessons_section = self._format_lessons_section()
            if lessons_section:
                gathered_context += "\n\n" + lessons_section

            context_doc.append_section(1, "Gathered Context", gathered_context)

            # Add source references
            for turn_str in retrieval_result.direct_info.keys():
                try:
                    t = int(turn_str)
                    context_doc.add_source_reference(
                        path=f"panda_system_docs/turns/turn_{t:06d}/context.md",
                        summary=f"Turn {t} context",
                        relevance=0.8
                    )
                except (ValueError, AttributeError):
                    pass

            for link in retrieval_result.links_to_follow:
                context_doc.add_source_reference(
                    path=link.path,
                    summary=link.reason[:50],
                    relevance=0.9
                )

            # Add source references from forever memory
            for mem_result in self.forever_memory_results:
                context_doc.add_source_reference(
                    path=f"panda_system_docs/{mem_result.path}",
                    summary=f"Forever memory: {mem_result.topic or mem_result.artifact_type}",
                    relevance=mem_result.relevance
                )

            return context_doc

        except Exception as e:
            logger.error(f"[ContextGatherer2Phase] SYNTHESIS phase failed: {e}")
            return self._create_minimal_context(query, turn_number, turn_dir)

    def _format_direct_info(self, retrieval_result: RetrievalResultDoc) -> str:
        """Format direct info section for synthesis prompt."""
        if not retrieval_result.direct_info:
            return "*No direct information from prior turns.*"

        lines = []
        for turn, info in retrieval_result.direct_info.items():
            lines.append(f"### From Turn {turn}")
            lines.append(info)
            lines.append("")

        return "\n".join(lines)

    def _format_linked_docs(
        self,
        linked_docs: Dict[str, str],
        retrieval_result: RetrievalResultDoc
    ) -> str:
        """Format linked documents section for synthesis prompt."""
        lines = [
            "===== LINKED DOCUMENTS (EXTRACT FROM THESE) =====",
            ""
        ]

        for path, content in linked_docs.items():
            lines.append(f"### Document: {path}")
            lines.append(content[:3000])
            if len(content) > 3000:
                lines.append("*[Content truncated...]*")
            lines.append("")

        return "\n".join(lines)

    def _format_supplementary_sources(self) -> str:
        """Format supplementary sources (cache, lessons, session memory, repo context)."""
        sections = []

        # Repository context (code mode)
        if self.repo_context:
            sections.append(self.repo_context)

        # Session memory
        if self.session_memory.get("preferences"):
            sections.append(f"""===== SESSION MEMORY - USER PREFERENCES =====
{self.session_memory['preferences']}
""")

        # Cached intelligence
        if self.cached_intelligence:
            retailers = self.cached_intelligence.get("retailers", {})
            if isinstance(retailers, dict):
                retailer_names = list(retailers.keys())[:5]
            elif isinstance(retailers, list):
                retailer_names = retailers[:5]
            else:
                retailer_names = []

            age = self.intel_cache_metadata.get("age_hours", 0) if self.intel_cache_metadata else 0

            sections.append(f"""===== CACHED INTELLIGENCE (Phase 1) =====
- Age: {age:.1f}h
- Retailers: {', '.join(retailer_names)}
- Recommendations: {len(self.cached_intelligence.get('forum_recommendations', []))}
- Requirements: {len(self.cached_intelligence.get('hard_requirements', []))}
""")

        # Forever memory (obsidian_memory) - persistent knowledge
        # Uses pre-built context from MemoryContextBuilder with intelligent summarization
        if self.formatted_memory_context:
            # Use the intelligently summarized context (includes full docs, sources, links)
            sections.append(f"===== FOREVER MEMORY (Persistent Knowledge) =====\n\n{self.formatted_memory_context}")
        elif self.forever_memory_results:
            # Fallback to simple formatting if MemoryContextBuilder not available
            memory_lines = ["===== FOREVER MEMORY (Persistent Knowledge) =====", ""]
            for result in self.forever_memory_results[:5]:
                expired_note = " *[may be outdated]*" if result.expired else ""
                memory_lines.append(f"### {result.topic or result.path}{expired_note}")
                memory_lines.append(f"Type: {result.artifact_type} | Relevance: {result.relevance:.2f} | Confidence: {result.confidence:.2f}")
                if result.tags:
                    memory_lines.append(f"Tags: {', '.join(result.tags[:5])}")
                memory_lines.append("")
                memory_lines.append(result.summary[:500] if result.summary else "")
                memory_lines.append("")
            sections.append("\n".join(memory_lines))

        # Stored user preferences (from persistent storage - distinct from session preferences)
        if self.user_preferences_memory:
            pref_lines = ["===== STORED USER PREFERENCES =====", ""]
            pref_lines.append(self.user_preferences_memory.summary[:1000] if self.user_preferences_memory.summary else "*No preferences recorded*")
            pref_lines.append("")
            sections.append("\n".join(pref_lines))

        return "\n".join(sections)

    def _load_linked_docs(
        self,
        retrieval_result: RetrievalResultDoc,
        depth: int = 1
    ) -> Dict[str, str]:
        """
        Load content from links that need to be followed.

        Implements depth limiting (#43 from IMPLEMENTATION_ROADMAP.md):
        - MAX_LINK_DEPTH=2 (context.md → research.md → claim sources)
        - TOKEN_BUDGET_LINKING=8000 (stop when 80% consumed)
        - Circular reference prevention via visited_paths set

        Args:
            retrieval_result: The retrieval result containing links to follow
            depth: Current depth level (1 = research.md, 2 = claim sources)

        Returns:
            Dict mapping paths to content
        """
        documents = {}

        # Check depth limit
        if depth > MAX_LINK_DEPTH:
            logger.debug(f"[ContextGatherer2Phase] Depth limit ({MAX_LINK_DEPTH}) reached, skipping links")
            return documents

        # Check token budget (stop at 80% consumed)
        budget_threshold = int(TOKEN_BUDGET_LINKING * 0.8)
        if self._link_tokens_consumed >= budget_threshold:
            logger.debug(f"[ContextGatherer2Phase] Token budget ({TOKEN_BUDGET_LINKING}) exhausted at {self._link_tokens_consumed}")
            return documents

        for link in retrieval_result.links_to_follow:
            # Circular reference prevention
            path_str = str(link.path)
            if path_str in self._visited_paths:
                logger.debug(f"[ContextGatherer2Phase] Skipping already visited: {path_str}")
                continue

            # Check remaining budget
            remaining_budget = TOKEN_BUDGET_LINKING - self._link_tokens_consumed
            if remaining_budget < 500:  # Minimum useful chunk
                logger.debug(f"[ContextGatherer2Phase] Insufficient budget remaining: {remaining_budget}")
                break

            self._visited_paths.add(path_str)

            # Resolve path - relative paths like "../turn_001353/toolresults.md"
            # need to be resolved relative to turns_dir
            path = Path(link.path)
            if not path.is_absolute():
                # Relative path - resolve from turns_dir
                resolved_path = (self.turns_dir / link.path).resolve()
            else:
                resolved_path = path

            if resolved_path.exists():
                try:
                    content = resolved_path.read_text()
                    # Truncate based on remaining budget (rough 4 chars per token)
                    max_chars = min(4000, remaining_budget * 4)
                    truncated = content[:max_chars]
                    documents[link.path] = truncated

                    # Update token count (rough estimate)
                    self._link_tokens_consumed += len(truncated) // 4
                    logger.debug(f"[ContextGatherer2Phase] Loaded {link.path} (depth={depth}, tokens~{len(truncated)//4})")

                except Exception as e:
                    logger.debug(f"[ContextGatherer2Phase] Failed to load {link.path}: {e}")
                    documents[link.path] = f"[Failed to load: {e}]"

        return documents

    # ==================================================================
    # INDEX AND BUNDLE BUILDING
    # ==================================================================

    def _build_turn_index(self, current_turn: int) -> TurnIndexDoc:
        """Build index of recent turns.

        Respects quality_score from the Freshness Degradation System:
        - Skips turns with quality < 0.2 (essentially unusable data)
        - Includes quality_score in entries so LLM can see outdated warnings
        """
        entries = []

        for turn_num in range(current_turn - 1, max(0, current_turn - self.index_limit - 1), -1):
            turn_dir = self.turns_dir / f"turn_{turn_num:06d}"
            if not turn_dir.exists():
                continue

            entry = self._parse_turn_for_index(turn_dir, turn_num)
            if entry:
                # Skip turns with very low quality (essentially unusable)
                # These were degraded by the Freshness Analyzer due to outdated info
                if entry.quality_score < 0.2:
                    logger.debug(
                        f"[ContextGatherer2Phase] Skipping turn {turn_num} - "
                        f"quality too low ({entry.quality_score:.2f})"
                    )
                    continue
                entries.append(entry)

        oldest = entries[-1].turn_number if entries else current_turn
        newest = entries[0].turn_number if entries else current_turn

        return TurnIndexDoc(
            session_id=self.session_id,
            generated_at=datetime.utcnow().isoformat() + "Z",
            entries=entries,
            oldest_turn=oldest,
            newest_turn=newest
        )

    def _parse_turn_for_index(self, turn_dir: Path, turn_num: int) -> Optional[TurnIndexEntry]:
        """Parse a turn directory into an index entry."""
        context_path = turn_dir / "context.md"
        if not context_path.exists():
            return None

        try:
            content = context_path.read_text()

            # Extract query summary
            query_summary = ""
            if "## 0. User Query" in content:
                query_section = content.split("## 0. User Query")[1]
                if "---" in query_section:
                    query_section = query_section.split("---")[0]
                query_summary = query_section.strip()[:100]

            # Extract topic
            topic = "unknown"
            if "**Topic:**" in content:
                topic_match = re.search(r'\*\*Topic:\*\*\s*([^\n]+)', content)
                if topic_match:
                    topic = topic_match.group(1).strip()

            # Check research.json for topic if not found
            if topic == "unknown":
                research_path = turn_dir / "research.json"
                if research_path.exists():
                    try:
                        with open(research_path) as f:
                            research_data = json.load(f)
                        topic_data = research_data.get("topic", {})
                        if isinstance(topic_data, dict):
                            topic = topic_data.get("primary_topic", topic)
                        elif topic_data:
                            topic = str(topic_data)
                    except Exception:
                        pass

            # Extract entities
            entities = []
            if "electronics" in topic.lower() or topic == "unknown":
                gpu_matches = re.findall(r'RTX\s*(\d{4})', content, re.IGNORECASE)
                entities.extend([f"RTX {m}" for m in gpu_matches[:3]])

            price_matches = re.findall(r'\$[\d,]+\.?\d*', content)
            if price_matches:
                entities.append(f"prices: {len(price_matches)}")

            has_research = (turn_dir / "research.md").exists() or (turn_dir / "research.json").exists()
            has_products = "| Product |" in content or "Product Findings" in content

            # Get response preview for searchability
            response_preview = self._get_response_preview(turn_dir)

            # Load quality_score from metadata.json
            # Degraded turns (from Freshness Analyzer) have lower quality scores
            quality_score = 1.0
            metadata_path = turn_dir / "metadata.json"
            if metadata_path.exists():
                try:
                    with open(metadata_path) as f:
                        metadata = json.load(f)
                    quality_score = metadata.get("quality_score", 1.0)
                except Exception:
                    pass

            return TurnIndexEntry(
                turn_number=turn_num,
                query_summary=query_summary,
                topic=topic,
                key_entities=entities[:5],
                has_research=has_research,
                has_products=has_products,
                response_preview=response_preview,
                quality_score=quality_score
            )

        except Exception as e:
            logger.debug(f"[ContextGatherer2Phase] Failed to parse turn {turn_num}: {e}")
            return None

    def _get_response_preview(self, turn_dir: Path, max_len: int = 200) -> str:
        """Get response preview for turn index searchability.

        Extracts bold topic names (e.g. **Topic Name**) since these are
        the key searchable items in list-style responses.
        """
        response_path = turn_dir / "response.md"
        if not response_path.exists():
            return ""

        try:
            content = response_path.read_text()

            # Extract bold items (topic names) - these are most searchable
            bold_items = re.findall(r'\*\*([^*]+)\*\*', content)
            if bold_items:
                # Join topic names, limit total length
                preview = ", ".join(bold_items[:8])
                if len(preview) > max_len:
                    preview = preview[:max_len] + "..."
                return preview

            # Fallback: first content lines
            lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("#")]
            preview = " ".join(lines)[:max_len]
            if len(preview) == max_len:
                preview += "..."
            return preview
        except Exception:
            return ""

    def _build_context_bundle_for_retrieval(
        self,
        query: str,
        turn_index: TurnIndexDoc,
        preloaded_turn: Optional[int] = None
    ) -> ContextBundleDoc:
        """Build context bundle for RETRIEVAL phase.

        Loads top N turns from index, ensuring preloaded_turn is included.
        """
        entries = []
        loaded_turns = set()

        # Load top 5 turns from index
        for entry in turn_index.entries[:5]:
            turn_dir = self.turns_dir / f"turn_{entry.turn_number:06d}"
            context_path = turn_dir / "context.md"

            if not context_path.exists():
                continue

            include_prices = not self._is_price_expired(turn_dir)

            try:
                content = context_path.read_text()
                bundle_entry = self._parse_context_for_bundle(
                    content, entry.turn_number, turn_dir, include_prices
                )
                if bundle_entry:
                    entries.append(bundle_entry)
                    loaded_turns.add(entry.turn_number)
            except Exception as e:
                logger.debug(f"[ContextGatherer2Phase] Failed to load turn {entry.turn_number}: {e}")

        return ContextBundleDoc(query=query, entries=entries)

    def _parse_context_for_bundle(
        self,
        content: str,
        turn_num: int,
        turn_dir: Path,
        include_prices: bool = True
    ) -> Optional[ContextBundleEntry]:
        """Parse context.md into a bundle entry."""
        # Extract query
        original_query = ""
        if "## 0. User Query" in content:
            query_section = content.split("## 0. User Query")[1]
            if "---" in query_section:
                query_section = query_section.split("---")[0]
            original_query = query_section.strip()[:200]

        # Extract topic and intent
        topic = "unknown"
        intent = "unknown"
        if "**Topic:**" in content:
            topic_match = re.search(r'\*\*Topic:\*\*\s*([^\n]+)', content)
            if topic_match:
                topic = topic_match.group(1).strip()
        if "**Intent:**" in content:
            intent_match = re.search(r'\*\*Intent:\*\*\s*([^\n]+)', content)
            if intent_match:
                intent = intent_match.group(1).strip()

        # Extract summary - PRIORITIZE Section 1 (Gathered Context) over Section 5 (Response)
        # Section 1 contains rich context that may be valuable even if the response failed
        summary = ""

        # First, try to get rich context from Section 1
        section1_context = ""
        if "## 1. Gathered Context" in content:
            section1 = content.split("## 1. Gathered Context")[1]
            if "## 2." in section1:
                section1 = section1.split("## 2.")[0]
            # Extract Prior Turn Context only - NOT Topic Classification
            # Topic Classification is query-specific metadata that must be generated fresh
            # for each new query, never inherited from prior turns (fixes context pollution)
            if "### Prior Turn Context" in section1:
                ptc = section1.split("### Prior Turn Context")[1]
                if "###" in ptc:
                    ptc = ptc.split("###")[0]
                section1_context += ptc.strip()[:500]

        # Then get Section 5 response
        section5_response = ""
        if "## 5. Synthesis" in content:
            synthesis = content.split("## 5. Synthesis")[1]
            if "## 6." in synthesis:
                synthesis = synthesis.split("## 6.")[0]
            if "**Draft Response:**" in synthesis:
                draft = synthesis.split("**Draft Response:**")[1].strip()
                section5_response = draft[:500]
            else:
                section5_response = synthesis.strip()[:500]

        # Combine: prefer Section 1 context + Section 5 response
        # This ensures we don't lose context even when response says "couldn't find info"
        if section1_context and section5_response:
            summary = f"{section1_context}\n\n[Response]: {section5_response[:300]}"
        elif section1_context:
            summary = section1_context
        elif section5_response:
            summary = section5_response
        elif "### Prior Research Intelligence" in content:
            pri = content.split("### Prior Research Intelligence")[1]
            if "---" in pri:
                pri = pri.split("---")[0]
            summary = pri.strip()[:500]

        # Strip price info if expired
        if not include_prices and summary:
            summary = re.sub(r'\$[\d,]+(?:\.\d{2})?', '[price expired]', summary)

        # Extract product findings
        products = []
        if include_prices:
            if "## 4. Tool Execution" in content:
                section4 = content.split("## 4. Tool Execution")[1]
                if "## 5." in section4:
                    section4 = section4.split("## 5.")[0]
                for line in section4.split("\n"):
                    if line.startswith("|") and "$" in line and "Claim" not in line:
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) >= 2:
                            products.append({
                                "name": parts[0][:50],
                                "price": next((p for p in parts if "$" in p), ""),
                                "vendor": parts[-1] if len(parts) > 2 else ""
                            })

        # Extract source references
        source_refs = []
        if "### Source References" in content:
            ref_section = content.split("### Source References")[1]
            if "##" in ref_section:
                ref_section = ref_section.split("##")[0]
            for line in ref_section.split("\n"):
                if line.strip().startswith("- ["):
                    url_match = re.search(r'\((https?://[^\)]+)\)', line)
                    if url_match and self._should_skip_url(url_match.group(1)):
                        continue
                    source_refs.append(line.strip())

        return ContextBundleEntry(
            turn_number=turn_num,
            original_query=original_query,
            topic=topic,
            intent=intent,
            summary=summary,
            product_findings=products[:5],
            source_references=source_refs[:5]
        )

    # ==================================================================
    # SUPPLEMENTARY SOURCES (reused from v2)
    # ==================================================================

    def _check_intelligence_cache(self, query: str) -> None:
        """Check for cached Phase 1 intelligence."""
        self.cached_intelligence = None
        self.intel_cache_metadata = None

        if not INTEL_CACHE_AVAILABLE:
            return

        try:
            cache = SessionIntelligenceCache(self.session_id)
            intelligence = cache.load_intelligence(query)

            if intelligence:
                cache_data = cache._load_cache()
                query_hash = cache._hash_query(query)

                for entry in cache_data.get("entries", []):
                    if entry.get("query_hash") == query_hash:
                        created_at = datetime.fromisoformat(entry["created_at"].replace("Z", "+00:00"))
                        expires_at = datetime.fromisoformat(entry["expires_at"].replace("Z", "+00:00"))
                        now = datetime.now(timezone.utc)

                        self.intel_cache_metadata = {
                            "query_hash": query_hash,
                            "original_query": entry.get("original_query", query),
                            "age_hours": (now - created_at).total_seconds() / 3600,
                            "ttl_remaining_hours": max(0, (expires_at - now).total_seconds() / 3600),
                        }
                        break

                self.cached_intelligence = intelligence
                logger.info(f"[ContextGatherer2Phase] INTEL CACHE HIT")

        except Exception as e:
            logger.warning(f"[ContextGatherer2Phase] Failed to check intelligence cache: {e}")

    def _detect_followup(self, query: str, turn_number: int) -> tuple:
        """
        Always check N-1 for inherited topic context.

        ARCHITECTURAL FIX (2026-01-04): Removed hardcoded pattern matching.
        Always check N-1 for topic inheritance - the research index can use
        the previous topic to find related research even if the query doesn't
        explicitly look like a follow-up.

        Returns:
            (has_n1: bool, inherited_topic: Optional[str])
        """
        if turn_number <= 1:
            return False, None

        # Always check N-1 for topic
        prev_dir = self.turns_dir / f"turn_{turn_number - 1:06d}"
        context_path = prev_dir / "context.md"

        if context_path.exists():
            try:
                content = context_path.read_text()
                topic_match = re.search(
                    r'### Topic Classification.*?\*\*Topic:\*\*\s*([^\n]+)',
                    content, re.DOTALL
                )
                if topic_match:
                    return True, topic_match.group(1).strip().replace(' ', '_')
            except Exception:
                pass

        return True, None  # N-1 exists but no topic extracted

    def _check_research_index(
        self,
        query: str,
        intent: Optional[str] = None,
        inherited_topic: Optional[str] = None
    ) -> None:
        """Check ResearchIndexDB for relevant documents."""
        self.research_index_results = []
        self.query_topic_path = None

        if not RESEARCH_INDEX_AVAILABLE:
            return

        try:
            index_db = get_research_index_db()

            if inherited_topic:
                topic_path = inherited_topic
            else:
                from libs.gateway.research_doc_writers import normalize_topic
                topic = normalize_topic(query) or "general"
                topic_path = f"commerce.{topic.replace(' ', '_')}"

            self.query_topic_path = topic_path

            results = index_db.search(
                topic=topic_path,
                intent=intent,
                session_id=self.session_id,
                min_quality=0.5,
                include_expired=False,
                limit=5
            )

            if results:
                for result in results:
                    entry = result.entry
                    self.research_index_results.append({
                        "topic": entry.primary_topic,
                        "keywords": entry.keywords,
                        "quality_score": entry.overall_quality,
                        "age_hours": entry.age_hours,
                        "match_score": result.score,
                        "doc_path": entry.doc_path
                    })
                logger.info(f"[ContextGatherer2Phase] RESEARCH INDEX HIT: {len(results)} docs")

        except Exception as e:
            logger.warning(f"[ContextGatherer2Phase] Failed to check research index: {e}")

    async def _check_forever_memory(self, query: str, intent: str = "informational") -> None:
        """
        Check obsidian_memory (forever memory) for relevant knowledge.

        Per architecture/services/OBSIDIAN_MEMORY.md:
        - Searches Knowledge/ (Research, Products, Facts, Concepts)
        - Searches Beliefs/ (Active, Hypotheses, Contested)
        - Searches Users/{user_id}/ for user-specific data
        - Uses topic/tag/content matching with recency weighting

        Uses config.searchable_paths by default (no hardcoded folders).
        Uses MemoryContextBuilder for intelligent summarization with dynamic
        token budget based on query type.
        """
        self.forever_memory_results = []
        self.user_preferences_memory = None
        self.formatted_memory_context = ""

        if not FOREVER_MEMORY_AVAILABLE:
            return

        try:
            # Search for relevant knowledge - uses config.searchable_paths
            # which includes Knowledge/, Beliefs/, Users/, Maps/
            raw_memory_results = await search_memory(
                query=query,
                # No folders param = uses config.searchable_paths defaults
                limit=7,  # Quality over quantity - fewer but more relevant results
            )
            # Filter to only include results with meaningful relevance (>= 0.6)
            # This prevents irrelevant notes from consuming context budget
            MIN_CONTEXT_RELEVANCE = 0.6
            self.forever_memory_results = [
                r for r in raw_memory_results
                if r.relevance >= MIN_CONTEXT_RELEVANCE
            ]
            if len(raw_memory_results) != len(self.forever_memory_results):
                logger.info(
                    f"[ContextGatherer2Phase] Filtered memory results: "
                    f"{len(raw_memory_results)} -> {len(self.forever_memory_results)} "
                    f"(min relevance: {MIN_CONTEXT_RELEVANCE})"
                )
            self.user_preferences_memory = await get_user_preferences(user_id=self.user_id)

            if self.forever_memory_results:
                logger.info(f"[ContextGatherer2Phase] FOREVER MEMORY HIT: {len(self.forever_memory_results)} results")
                for result in self.forever_memory_results[:3]:
                    logger.debug(f"  - {result.topic} ({result.artifact_type}, relevance={result.relevance:.2f})")

                # Build formatted memory context using intelligent summarization
                if self.memory_context_builder and self.budget_allocator:
                    # Calculate average relevance to help determine query profile
                    avg_relevance = sum(r.relevance for r in self.forever_memory_results) / len(self.forever_memory_results)

                    # Detect query profile for optimal token budget allocation
                    query_type = self.budget_allocator.detect_query_profile(
                        intent=intent,
                        has_memory_hits=True,
                        memory_relevance=avg_relevance,
                        is_follow_up=False,  # Will be updated if detected
                        mode=self.mode
                    )

                    logger.info(
                        f"[ContextGatherer2Phase] Using query profile '{query_type}' "
                        f"(avg_relevance={avg_relevance:.2f}, mode={self.mode})"
                    )

                    # Build context with dynamic budget
                    # For now, assume tool results may be present (conservative)
                    # This will be refined based on planner output
                    self.formatted_memory_context = await self.memory_context_builder.build(
                        memory_results=self.forever_memory_results,
                        query_type=query_type,
                        has_tool_results=(intent == "transactional"),
                        load_full_content=True
                    )

                    logger.info(
                        f"[ContextGatherer2Phase] Built memory context: "
                        f"{len(self.formatted_memory_context)} chars"
                    )

            if self.user_preferences_memory:
                logger.info("[ContextGatherer2Phase] User preferences loaded from forever memory")

        except Exception as e:
            logger.warning(f"[ContextGatherer2Phase] Failed to check forever memory: {e}")

    def _check_matching_lessons(self, query: str) -> None:
        """Check for matching strategy lessons.

        ARCHITECTURAL DECISION (2025-12-30):
        Lesson system removed - learning now happens implicitly via turn indexing.
        This method is kept as a no-op for backwards compatibility.
        """
        self.matching_lessons = []
        # No-op: lesson_store has been removed from the codebase

    def _load_session_memory(self) -> None:
        """Load session memory files."""
        self.session_memory = {"preferences": "", "live_context": "", "history": ""}

        session_dir = self.sessions_dir / self.session_id
        if not session_dir.exists():
            return

        for name in ["preferences.md", "live_context.md", "history_compressed.md"]:
            path = session_dir / name
            if path.exists():
                try:
                    content = path.read_text().strip()
                    key = name.replace(".md", "").replace("_compressed", "")
                    self.session_memory[key] = content[:2000]  # Limit
                except Exception:
                    pass

    def _gather_repo_context(self) -> None:
        """
        Gather repository context for code mode.

        Collects:
        - Repository path
        - Git status (branch, modified files count)
        - Top-level structure with file counts by type
        - Key files (entry points, configs, build files, docs)
        - README excerpt (first 300 chars)
        - Primary language from file extensions
        """
        import subprocess

        if self.mode != "code" or not self.repo:
            return

        repo_path = Path(self.repo)
        if not repo_path.exists():
            logger.warning(f"[ContextGatherer2Phase] Repo path does not exist: {self.repo}")
            return

        lines = ["### Repository Context", ""]
        lines.append(f"**Path:** {self.repo}")

        # Git status
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain", "--branch"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                git_lines = result.stdout.strip().split('\n')
                branch_line = git_lines[0] if git_lines else ""
                # Parse branch info (e.g., "## main...origin/main")
                if branch_line.startswith("## "):
                    branch_info = branch_line[3:].split("...")[0]
                    lines.append(f"**Git Branch:** {branch_info}")
                # Count modified files
                modified_count = len([l for l in git_lines[1:] if l.strip()])
                if modified_count > 0:
                    lines.append(f"**Uncommitted Changes:** {modified_count} files")
        except Exception as e:
            logger.debug(f"[ContextGatherer2Phase] Git status failed: {e}")

        lines.append("")

        # Top-level structure with counts
        lines.append("**Directory Structure:**")
        try:
            entries = list(repo_path.iterdir())
            dirs = sorted([e for e in entries if e.is_dir() and not e.name.startswith('.')])
            files = sorted([e for e in entries if e.is_file() and not e.name.startswith('.')])

            # Count files by extension in each directory
            for d in dirs[:15]:  # Limit to 15 dirs
                try:
                    dir_files = list(d.rglob("*"))
                    file_count = len([f for f in dir_files if f.is_file()])
                    lines.append(f"- {d.name}/          ({file_count} files)")
                except Exception:
                    lines.append(f"- {d.name}/")

            # Top-level files
            top_files = [f.name for f in files[:10]]
            if top_files:
                lines.append(f"- (root files): {', '.join(top_files)}")
        except Exception as e:
            logger.debug(f"[ContextGatherer2Phase] Directory listing failed: {e}")

        lines.append("")

        # Key files detection and language detection in SINGLE PASS (performance optimization)
        key_files = {"entry_points": [], "config": [], "build": [], "docs": []}
        ext_counts = {}

        entry_point_patterns = {
            "main.py", "app.py", "index.py", "__main__.py",
            "index.js", "index.ts", "main.js", "app.js",
            "main.go", "main.rs", "manage.py", "wsgi.py", "asgi.py"
        }
        config_patterns = {
            ".env", ".env.example", "config.yaml", "config.json", "config.yml",
            "settings.py", "constants.py", "tsconfig.json", "webpack.config.js"
        }
        build_patterns = {
            "Makefile", "CMakeLists.txt", "setup.py", "pyproject.toml",
            "requirements.txt", "package.json", "Cargo.toml", "go.mod", "pom.xml"
        }
        doc_patterns = {
            "README.md", "README.rst", "README.txt", "CONTRIBUTING.md", "CHANGELOG.md"
        }
        skip_dirs = {'node_modules', 'venv', '__pycache__', '.git', '.venv', 'dist', 'build'}

        try:
            file_count = 0
            max_files = 10000  # Limit to prevent unbounded iteration on massive repos
            for f in repo_path.rglob("*"):
                if not f.is_file():
                    continue

                file_count += 1
                if file_count > max_files:
                    logger.warning(f"[ContextGatherer2Phase] Repo scan limited to {max_files} files")
                    break

                name = f.name
                rel_path = str(f.relative_to(repo_path))

                # Skip hidden and vendor dirs
                path_parts = rel_path.split('/')
                if any(part.startswith('.') or part in skip_dirs for part in path_parts):
                    continue

                # Language detection (count extensions)
                if f.suffix:
                    ext = f.suffix.lower()
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1

                # Key files detection
                if name in entry_point_patterns:
                    key_files["entry_points"].append(rel_path)
                elif name in config_patterns:
                    key_files["config"].append(rel_path)
                elif name in build_patterns:
                    key_files["build"].append(rel_path)
                elif name in doc_patterns:
                    key_files["docs"].append(rel_path)
        except Exception as e:
            logger.debug(f"[ContextGatherer2Phase] Repo scan failed: {e}")

        if any(key_files.values()):
            lines.append("**Key Files Detected:**")
            if key_files["entry_points"]:
                lines.append(f"- Entry points: {', '.join(key_files['entry_points'][:5])}")
            if key_files["config"]:
                lines.append(f"- Config: {', '.join(key_files['config'][:5])}")
            if key_files["build"]:
                lines.append(f"- Build: {', '.join(key_files['build'][:5])}")
            if key_files["docs"]:
                lines.append(f"- Docs: {', '.join(key_files['docs'][:5])}")
            lines.append("")

        if ext_counts:
            total = sum(ext_counts.values())
            sorted_exts = sorted(ext_counts.items(), key=lambda x: -x[1])[:3]
            lang_parts = [f"{ext} ({count/total*100:.0f}%)" for ext, count in sorted_exts]
            lines.append(f"**Primary Languages:** {', '.join(lang_parts)}")
            lines.append("")

        # README excerpt
        readme_path = None
        for name in ["README.md", "README.rst", "README.txt", "readme.md"]:
            candidate = repo_path / name
            if candidate.exists():
                readme_path = candidate
                break

        if readme_path:
            try:
                readme_content = readme_path.read_text()[:500]
                # Get first paragraph or 300 chars
                first_para = readme_content.split('\n\n')[0][:300]
                if first_para:
                    lines.append(f"**README Excerpt:** {first_para.strip()}")
                    lines.append("")
            except Exception:
                pass

        self.repo_context = "\n".join(lines)
        logger.info(f"[ContextGatherer2Phase] Gathered repo context ({len(self.repo_context)} chars)")

    def _load_research_findings(self, doc_path: str, max_listings: int = 5) -> Dict[str, Any]:
        """
        Load and extract key findings from a research.md file.

        Returns:
            Dict with 'listings' (list of product summaries) and 'sources' (list of vendors)
        """
        findings = {"listings": [], "sources": [], "raw_excerpt": ""}

        if not doc_path:
            return findings

        # Construct full path
        full_path = self.turns_dir.parent / doc_path
        if not full_path.exists():
            # Try alternate path constructions
            alt_path = Path(doc_path)
            if alt_path.exists():
                full_path = alt_path
            else:
                logger.debug(f"[ContextGatherer2Phase] Research doc not found: {doc_path}")
                return findings

        try:
            content = full_path.read_text()

            # Extract Current Listings table
            # Look for the markdown table after "### Current Listings"
            listings_match = re.search(
                r'### Current Listings\s*\n\n\|[^\n]+\|\s*\n\|[-| ]+\|\s*\n((?:\|[^\n]+\|\s*\n)+)',
                content,
                re.MULTILINE
            )

            if listings_match:
                table_rows = listings_match.group(1).strip().split('\n')
                for row in table_rows[:max_listings]:
                    # Parse table row: | Product | Price | Vendor | In Stock | Confidence |
                    cols = [c.strip() for c in row.split('|')[1:-1]]  # Remove empty first/last
                    if len(cols) >= 3:
                        product = cols[0][:60] + "..." if len(cols[0]) > 60 else cols[0]
                        findings["listings"].append({
                            "product": product,
                            "price": cols[1] if len(cols) > 1 else "N/A",
                            "vendor": cols[2] if len(cols) > 2 else "unknown"
                        })
                        if cols[2] and cols[2] not in findings["sources"]:
                            findings["sources"].append(cols[2])

            # Extract URLs from Listing Details section (always, to enrich table data)
            detail_matches = re.findall(
                r'####\s+\d+\.\s+([^\n]+)\n- \*\*Price:\*\*\s+(\$[\d,.]+)\n- \*\*Vendor:\*\*\s+([^\n]+)\n(?:- \*\*URL:\*\*\s+([^\n]+))?',
                content
            )

            # Build URL lookup by product name
            url_lookup = {}
            for match in detail_matches:
                product_name = match[0].strip()
                if len(match) > 3 and match[3]:
                    url_lookup[product_name] = match[3].strip()

            # If we found listings from table, enrich with URLs from Listing Details
            if findings["listings"]:
                for listing in findings["listings"]:
                    # Try to match product name to get URL
                    for detail_name, url in url_lookup.items():
                        # Match if product name starts with detail name or vice versa
                        if (listing["product"].startswith(detail_name[:40]) or
                            detail_name.startswith(listing["product"][:40])):
                            listing["url"] = url
                            break
            else:
                # No table found, use Listing Details as primary source
                for match in detail_matches[:max_listings]:
                    product = match[0][:60] + "..." if len(match[0]) > 60 else match[0]
                    listing = {
                        "product": product,
                        "price": match[1],
                        "vendor": match[2]
                    }
                    # Add URL if captured (group 4)
                    if len(match) > 3 and match[3]:
                        listing["url"] = match[3].strip()
                    findings["listings"].append(listing)
                    if match[2] and match[2] not in findings["sources"]:
                        findings["sources"].append(match[2])

            # Extract evergreen knowledge excerpt if available
            evergreen_match = re.search(
                r'## Evergreen Knowledge\s*\n(.*?)(?=\n---|\n## |$)',
                content,
                re.DOTALL
            )
            if evergreen_match:
                excerpt = evergreen_match.group(1).strip()[:500]
                findings["raw_excerpt"] = excerpt

            # Extract links from the "Extracted Links" section
            # Format: | Title | URL |
            links_match = re.search(
                r'### Extracted Links\s*\n\n\*[^\n]*\*\s*\n\n\|[^\n]+\|\s*\n\|[-| ]+\|\s*\n((?:\|[^\n]+\|\s*\n)+)',
                content,
                re.MULTILINE
            )
            if links_match:
                findings["extracted_links"] = []
                table_rows = links_match.group(1).strip().split('\n')
                for row in table_rows[:30]:  # Limit to 30 links
                    # Parse table row: | Title | URL |
                    cols = [c.strip() for c in row.split('|')[1:-1]]  # Remove empty first/last
                    if len(cols) >= 2 and cols[1].startswith('http'):
                        findings["extracted_links"].append({
                            "title": cols[0][:100],  # Limit title length
                            "url": cols[1]
                        })
                if findings["extracted_links"]:
                    logger.debug(f"[ContextGatherer2Phase] Extracted {len(findings['extracted_links'])} links from {doc_path}")

        except Exception as e:
            logger.warning(f"[ContextGatherer2Phase] Failed to load research findings from {doc_path}: {e}")

        return findings

    def _format_feedback_section(self) -> str:
        """Format user feedback warning as markdown section."""
        if not self.user_feedback.get("detected"):
            return ""

        feedback_type = self.user_feedback.get("feedback_type", "unknown")
        confidence = self.user_feedback.get("confidence", 0.0)

        # Map feedback type to user-friendly descriptions
        type_descriptions = {
            "explicit_correction": "explicitly corrected the previous response",
            "abandonment_retry": "abandoned the previous request to try differently",
            "disappointment": "expressed dissatisfaction with the previous response",
            "repetition_request": "requested a retry or alternative options",
        }

        description = type_descriptions.get(feedback_type, "provided feedback on previous response")

        lines = [
            "### ⚠️ Previous Response Feedback",
            "",
            f"**Status:** User {description}",
            f"**Feedback Type:** {feedback_type}",
            f"**Confidence:** {confidence:.0%}",
            "",
            "**Guidance:** Consider what went wrong in the previous turn and adjust your approach. "
            "The user may be looking for different results, clearer explanations, or a change in direction.",
            ""
        ]

        return "\n".join(lines)

    def _format_research_section(self, has_prior_turn_context: bool = False, intent: str = None) -> str:
        """Format research index results as markdown section with key findings and Memory Status.

        Args:
            has_prior_turn_context: Whether the LLM extracted useful info from prior turns.
                                   This affects Memory Status generation.
            intent: Legacy intent parameter (deprecated) - kept for compatibility.
        """
        # Determine if this is a query that needs fresh data based on data_requirements
        needs_fresh_data = False
        if self.query_analysis:
            data_reqs = self.query_analysis.data_requirements or {}
            needs_fresh_data = data_reqs.get("needs_live_data", False) or data_reqs.get("needs_current_prices", False)
            if self.query_analysis.action_needed == "navigate_to_site":
                needs_fresh_data = True

        # Track ALL knowledge sources for accurate Memory Status
        knowledge_sources = []

        if has_prior_turn_context:
            knowledge_sources.append("prior turn context")
        if self.cached_intelligence:
            knowledge_sources.append("cached intelligence")
        if self.forever_memory_results:
            knowledge_sources.append("forever memory")
        if self.session_memory and self.session_memory.get("preferences"):
            knowledge_sources.append("user preferences")

        if not self.research_index_results:
            # No research index results, but check OTHER sources
            if knowledge_sources:
                if needs_fresh_data:
                    guidance = "For fresh data on products/prices, internet.research may still be needed."
                else:
                    guidance = "This context may be sufficient for an informational response."
                return (
                    "### Memory Status\n\n"
                    f"Prior turn context and cached knowledge available ({', '.join(knowledge_sources)}). "
                    f"{guidance}"
                )
            else:
                # Truly nothing found
                return (
                    "### Memory Status\n\n"
                    "No prior research found in memory for this topic. "
                    "Internet research will be needed to gather information."
                )

        lines = ["### Prior Research Intelligence", ""]
        included_count = 0
        has_fresh_intelligence = False
        total_searched = len(self.research_index_results)

        for doc in self.research_index_results[:3]:
            if not self._is_topic_relevant(doc.get("topic", "")):
                continue

            quality = doc.get('quality_score', 0)
            age_hours = doc.get('age_hours', 0)

            lines.append(f"**Topic:** {doc.get('topic', 'unknown')}")
            lines.append(f"**Quality:** {quality:.2f}, **Age:** {age_hours:.1f} hours")

            # Check if this qualifies as fresh intelligence
            if quality >= 0.6 and age_hours < 24:
                has_fresh_intelligence = True

            # Load and include key findings from the research.md file
            doc_path = doc.get("doc_path")
            if doc_path:
                findings = self._load_research_findings(doc_path)

                if findings["listings"]:
                    lines.append("")
                    lines.append("**Key Findings:**")
                    for listing in findings["listings"][:5]:
                        if listing.get('url'):
                            lines.append(f"- {listing['product']} @ {listing['price']} ({listing['vendor']}) - {listing['url']}")
                        else:
                            lines.append(f"- {listing['product']} @ {listing['price']} ({listing['vendor']})")

                    if findings["sources"]:
                        lines.append(f"")
                        lines.append(f"*Sources: {', '.join(findings['sources'][:3])}*")

                # Include extracted links for navigation (forum threads, articles, etc.)
                # Show these even if no listings (e.g., forum thread lists)
                extracted_links = findings.get("extracted_links", [])
                if extracted_links:
                    lines.append("")
                    lines.append("**Available Links:**")
                    for link in extracted_links[:10]:  # Limit to 10 links in context
                        lines.append(f"- [{link['title'][:60]}]({link['url']})")

                # Also show raw excerpt if available (for forum/article content)
                if not findings["listings"] and findings.get("raw_excerpt"):
                    lines.append("")
                    lines.append("**Content Summary:**")
                    lines.append(findings["raw_excerpt"][:300])

                lines.append(f"")
                lines.append(f"[Full research: {doc_path}]")

            lines.append("")
            included_count += 1

        # If all research was filtered out as irrelevant, check other sources
        if included_count == 0:
            if knowledge_sources:
                if needs_fresh_data:
                    guidance = "For current products/prices, internet.research is recommended."
                else:
                    guidance = "This context may be sufficient for an informational response."
                return (
                    "### Memory Status\n\n"
                    f"No research index matches, but other context available ({', '.join(knowledge_sources)}). "
                    f"{guidance}"
                )
            else:
                return (
                    "### Memory Status\n\n"
                    "No relevant prior research found for this topic. "
                    "Internet research will be needed to gather information."
                )

        # Add natural language Memory Status for Planner decision-making
        lines.append("### Memory Status")
        lines.append("")

        filtered_out = total_searched - included_count

        if has_fresh_intelligence:
            if included_count >= 3:
                lines.append(
                    f"Found {included_count} relevant research documents with fresh data (< 24h, quality ≥ 0.6). "
                    f"This appears comprehensive for the topic. No additional memory search needed."
                )
            else:
                lines.append(
                    f"Found {included_count} relevant research document(s) with fresh data. "
                    f"This covers the core topic. Additional memory search unlikely to find more."
                )
        else:
            # Found something but not fresh
            freshest = min(doc.get("age_hours", 999) for doc in self.research_index_results[:included_count])
            avg_quality = sum(doc.get("quality_score", 0) for doc in self.research_index_results[:included_count]) / max(included_count, 1)
            lines.append(
                f"Found {included_count} relevant research document(s), but data is older ({freshest:.0f}+ hours) "
                f"or lower quality ({avg_quality:.2f}). Consider refreshing with internet.research."
            )

        # Note if topic appears to have shifted
        if filtered_out > 0:
            lines.append(
                f"Note: {filtered_out} other research document(s) exist but are for different topics."
            )

        # Add note about other knowledge sources available
        if knowledge_sources:
            other_sources = [s for s in knowledge_sources if s != "prior turn context"]
            if other_sources:
                lines.append(
                    f"Additional context from: {', '.join(other_sources)}."
                )

        return "\n".join(lines)

    def _format_lessons_section(self) -> str:
        """Format matching lessons as markdown section."""
        if not self.matching_lessons:
            return ""

        lines = ["### Relevant Strategy Lessons", ""]
        lines.append("| Lesson | Strategy | Success Rate |")
        lines.append("|--------|----------|--------------|")

        for lesson in self.matching_lessons[:3]:
            lines.append(
                f"| {lesson.lesson_id} | {lesson.strategy_profile} | "
                f"{lesson.success_rate:.0%} |"
            )

        return "\n".join(lines)

    def _is_topic_relevant(self, doc_topic: str) -> bool:
        """Check if document topic is relevant to query."""
        if not self.query_topic_path or not doc_topic:
            return False

        query_kw = set(self.query_topic_path.lower().replace("_", ".").split("."))
        doc_kw = set(doc_topic.lower().replace("_", ".").split("."))

        generic = {'commerce', 'general', 'other', 'misc', 'unknown'}
        query_meaningful = query_kw - generic
        doc_meaningful = doc_kw - generic

        if query_meaningful and doc_meaningful:
            return bool(query_meaningful & doc_meaningful)

        return len(query_kw & doc_kw) >= 2

    # ==================================================================
    # HELPERS
    # ==================================================================

    def _load_retry_context(self, turn_dir: Path) -> None:
        """Load retry context for validation loop-back."""
        retry_path = turn_dir / "retry_context.json"
        if not retry_path.exists():
            self.retry_context = None
            self.failed_urls = set()
            return

        try:
            with open(retry_path) as f:
                self.retry_context = json.load(f)

            if self.retry_context.get("session_id") != self.session_id:
                self.retry_context = None
                self.failed_urls = set()
                return

            self.failed_urls = set(self.retry_context.get("failed_urls", []))
            logger.info(f"[ContextGatherer2Phase] RETRY MODE: {len(self.failed_urls)} failed URLs")

        except Exception as e:
            logger.error(f"[ContextGatherer2Phase] Failed to load retry context: {e}")
            self.retry_context = None
            self.failed_urls = set()

    def _is_price_expired(self, turn_dir: Path) -> bool:
        """Check if turn's price data is expired."""
        if self.retry_context and self.retry_context.get("reason") in ("PRICE_STALE", "SPEC_MISMATCH"):
            return True

        context_path = turn_dir / "context.md"
        if not context_path.exists():
            return True

        try:
            mtime = context_path.stat().st_mtime
            age = datetime.now() - datetime.fromtimestamp(mtime)
            ttl = RETRY_PRICE_TTL_HOURS if self.retry_context else PRICE_CLAIM_TTL_HOURS
            return age > timedelta(hours=ttl)
        except Exception:
            return True

    def _should_skip_url(self, url: str) -> bool:
        """Check if URL should be skipped (failed validation)."""
        if not self.failed_urls:
            return False
        return any(failed in url or url in failed for failed in self.failed_urls)

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Extract JSON from LLM response."""
        # Try code block
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try whole response
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try finding JSON object
        brace_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning("[ContextGatherer2Phase] Could not extract JSON")
        return {}

    def _clean_markdown(self, text: str) -> str:
        """Clean markdown response."""
        text = re.sub(r'^```(?:markdown)?\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
        return text.strip()

    def _create_context_from_cache(
        self,
        query: str,
        turn_number: int,
        turn_dir: Path
    ) -> ContextDocument:
        """Create context from cached intelligence when no turns found."""
        context_doc = ContextDocument(
            turn_number=turn_number,
            session_id=self.session_id,
            query=query
        )
        # Preserve mode and repo for tool execution
        context_doc.mode = self.mode
        context_doc.repo = self.repo

        # CRITICAL: Pass user_purpose through to downstream phases
        if self.query_analysis:
            context_doc.set_section_0(self.query_analysis.to_dict())

        content_parts = []

        # Include Repository Context FIRST for code mode
        if self.repo_context:
            content_parts.append(self.repo_context)

        # Session memory
        if self.session_memory.get("preferences"):
            content_parts.append(f"""### User Preferences

{self.session_memory['preferences']}
""")

        # Research index (no prior turn context in cache fallback path)
        research_section = self._format_research_section(has_prior_turn_context=False)
        if research_section:
            content_parts.append(research_section)

        # Cached intelligence
        if self.cached_intelligence:
            retailers = self.cached_intelligence.get("retailers", {})
            if isinstance(retailers, dict):
                retailer_names = list(retailers.keys())[:5]
            else:
                retailer_names = retailers[:5] if retailers else []

            age = self.intel_cache_metadata.get("age_hours", 0) if self.intel_cache_metadata else 0

            content_parts.append(f"""### Cached Intelligence (Phase 1)

**Source:** intelligence_cache.json ({age:.1f}h old)
**Retailers:** {', '.join(retailer_names)}
**Recommendations:** {len(self.cached_intelligence.get('forum_recommendations', []))}
""")

        content_parts.append("""### Prior Turn Context

*No relevant prior turns found for this query.*
""")

        context_doc.append_section(1, "Gathered Context", "\n\n".join(content_parts))
        return context_doc

    async def _try_visit_record_fast_path(
        self,
        resolved_query: str,
        original_query: str,
        turn_number: int,
        turn_dir: Path
    ) -> Optional[ContextDocument]:
        """
        Plan-Act-Review: Try to answer from cached visit_records.

        This is the "fast path" that avoids LLM calls when we have cached
        page data that can answer the question directly.

        Plan: Check if query_analysis has a content_reference with has_visit_record=True
        Act: Load the cached data and check if it answers the question
        Review: If it answers the question, build context; otherwise return None

        Returns:
            ContextDocument if fast path succeeds, None otherwise
        """
        # PLAN: Check if we have a visit record to check
        if not self.query_analysis or not self.query_analysis.content_reference:
            return None

        content_ref = self.query_analysis.content_reference
        if not content_ref.has_visit_record or not content_ref.visit_record_path:
            logger.debug("[FastPath] No visit record available, falling back to LLM retrieval")
            return None

        logger.info(
            f"[FastPath] Checking visit record at {content_ref.visit_record_path} "
            f"for question: '{resolved_query[:50]}...'"
        )

        # ACT: Load the cached data
        try:
            # Construct full path to visit record
            # visit_record_path is relative to turns_dir parent (panda_system_docs)
            record_path = self.turns_dir.parent / content_ref.visit_record_path
            if not record_path.exists():
                logger.warning(f"[FastPath] Visit record path does not exist: {record_path}")
                return None

            reader = VisitRecordReader(turns_dir=self.turns_dir)
            manifest = reader.load_manifest(record_path)

            if not manifest:
                logger.warning(f"[FastPath] Could not load manifest from {record_path}")
                return None

            # REVIEW: Check if the question can be answered from this data
            question_type = self._classify_question_type(resolved_query)
            logger.info(f"[FastPath] Question type: {question_type}")

            if question_type == "real_time":
                # Questions about current state need fresh data
                logger.info("[FastPath] Real-time question - need fresh data, falling back to LLM")
                return None

            # Check if manifest can answer the question
            if not reader.can_answer_question(resolved_query, manifest):
                logger.info("[FastPath] Manifest cannot answer this question, falling back to LLM")
                return None

            # Load the page content
            page_content = reader.load_page_content(record_path)
            if not page_content:
                logger.warning("[FastPath] Could not load page content")
                return None

            # Extract answer from cached data
            answer = self._extract_answer_from_cache(
                resolved_query, manifest, page_content
            )

            if not answer:
                logger.info("[FastPath] Could not extract answer from cache, falling back to LLM")
                return None

            # SUCCESS: Build context from cached data
            logger.info(f"[FastPath] Successfully answered from cache: '{answer[:100]}...'")

            context_doc = ContextDocument(
                turn_number=turn_number,
                session_id=self.session_id,
                query=original_query
            )
            context_doc.mode = self.mode
            context_doc.repo = self.repo

            # CRITICAL: Pass user_purpose through to downstream phases
            if self.query_analysis:
                context_doc.set_section_0(self.query_analysis.to_dict())

            # Build §1 with the cached answer
            content = f"""### Answer from Cached Page Data

**Source:** [{manifest.title}]({manifest.source_url})
**Page Type:** {manifest.content_type}
**Cached At:** {manifest.captured_at}

{answer}

---

*This answer was retrieved from cached page data (fast path).*
*Original page summary: {manifest.content_summary}*"""

            context_doc.append_section(1, "Gathered Context", content)

            # Save the context
            from .context_gatherer_docs import write_doc
            write_doc(turn_dir / "context.md", context_doc.get_markdown())

            return context_doc

        except Exception as e:
            logger.warning(f"[FastPath] Error during fast path check: {e}")
            return None

    def _classify_question_type(self, question: str) -> str:
        """
        Classify if a question needs real-time data or can use cache.

        Returns:
            "factual" - Can use cached data
            "real_time" - Needs fresh data (prices, stock status)
        """
        question_lower = question.lower()

        # Real-time indicators (need fresh data)
        real_time_patterns = [
            "right now", "currently", "today",
            "in stock", "available now", "still available",
            "current price", "latest price",
            "is it open", "are they open"
        ]

        for pattern in real_time_patterns:
            if pattern in question_lower:
                return "real_time"

        # Factual questions about page structure can use cache
        factual_patterns = [
            "how many pages", "how many replies", "how many comments",
            "what is the title", "what is it about",
            "page count", "number of",
            "when was it posted", "who posted"
        ]

        for pattern in factual_patterns:
            if pattern in question_lower:
                return "factual"

        # Default to factual for most questions
        return "factual"

    def _extract_answer_from_cache(
        self,
        question: str,
        manifest: VisitRecordManifest,
        page_content: str
    ) -> Optional[str]:
        """
        Extract an answer to the question from cached data.

        This uses simple pattern matching for common questions.
        Complex questions fall back to LLM retrieval.
        """
        question_lower = question.lower()

        # Page count questions
        if "how many pages" in question_lower:
            if manifest.page_info:
                return f"The {manifest.content_type} has {manifest.page_info}."

            # Try to extract from content
            import re
            page_match = re.search(r'page\s+\d+\s+of\s+(\d+)', page_content.lower())
            if page_match:
                return f"The {manifest.content_type} has {page_match.group(1)} pages."

            return None

        # Reply/comment count questions
        if any(w in question_lower for w in ["how many replies", "how many comments", "how many posts"]):
            if manifest.page_info and any(w in manifest.page_info.lower() for w in ["comment", "repl", "post"]):
                return f"The {manifest.content_type} has {manifest.page_info}."

            # Try to extract from content
            import re
            count_match = re.search(r'(\d+)\s+(comments?|replies?|posts?)', page_content.lower())
            if count_match:
                return f"The {manifest.content_type} has {count_match.group(1)} {count_match.group(2)}."

            return None

        # What is it about questions
        if "what is it about" in question_lower or "what is the" in question_lower:
            return f"""**{manifest.title}**

{manifest.content_summary}

**Key Topics:** {', '.join(manifest.key_entities[:5]) if manifest.key_entities else 'Not specified'}"""

        # For other questions, return the content summary as context
        # (this is a soft answer - not definitive but helpful)
        if manifest.content_summary and len(manifest.content_summary) > 50:
            return f"""Based on the cached page data:

**Title:** {manifest.title}
**Type:** {manifest.content_type}
{f'**Page Info:** {manifest.page_info}' if manifest.page_info else ''}

**Summary:** {manifest.content_summary}

*Note: For more specific details, you may need to visit the page directly.*"""

        return None

    def _create_navigation_context(
        self,
        query: str,
        turn_number: int,
        turn_dir: Path
    ) -> ContextDocument:
        """
        Create minimal context for navigation intent.

        For "go to X and do Y" queries, we skip heavy context gathering
        because prior conversation is irrelevant. We just need:
        - User preferences (if any)
        - Navigation metadata (target URL, goal)
        """
        context_doc = ContextDocument(
            turn_number=turn_number,
            session_id=self.session_id,
            query=query
        )
        context_doc.mode = self.mode
        context_doc.repo = self.repo

        # Pass user_purpose through to downstream phases
        if self.query_analysis:
            context_doc.set_section_0(self.query_analysis.to_dict())

        content_parts = []

        # Include User Preferences (still relevant for navigation)
        if self.session_memory.get("preferences"):
            content_parts.append(f"""### User Preferences

{self.session_memory['preferences']}""")

        # Navigation metadata
        if self.query_analysis and self.query_analysis.content_reference:
            target_url = self.query_analysis.content_reference.source_url or ""
            goal = self.query_analysis.user_purpose or "explore the page"
            content_parts.append(f"""### Navigation Intent

**Target:** {target_url}
**Goal:** {goal}

*Prior context skipped - navigation queries need fresh data from the target site.*""")
        else:
            content_parts.append("""### Navigation Intent

*Direct navigation query - proceed to target site.*""")

        # Topic classification
        content_parts.append("""### Topic Classification
- **Intent:** navigation
- **Query Type:** direct action""")

        context_doc.append_section(1, "Gathered Context", "\n\n".join(content_parts))

        # Write the context document
        from .context_gatherer_docs import write_doc
        write_doc(turn_dir / "context.md", context_doc.get_markdown())

        logger.info(f"[ContextGatherer2Phase] Navigation fast path - minimal context created")
        return context_doc

    def _create_minimal_context(
        self,
        query: str,
        turn_number: int,
        turn_dir: Path
    ) -> ContextDocument:
        """Create minimal context when nothing found."""
        context_doc = ContextDocument(
            turn_number=turn_number,
            session_id=self.session_id,
            query=query
        )
        # Preserve mode and repo for tool execution
        context_doc.mode = self.mode
        context_doc.repo = self.repo

        # CRITICAL: Pass user_purpose through to downstream phases
        if self.query_analysis:
            context_doc.set_section_0(self.query_analysis.to_dict())

        content_parts = []

        # Include Repository Context FIRST for code mode
        if self.repo_context:
            content_parts.append(self.repo_context)

        # Include User Preferences
        if self.session_memory.get("preferences"):
            content_parts.append(f"""### User Preferences

{self.session_memory['preferences']}""")

        # Standard minimal context
        content_parts.append("""### Session Context

*No relevant prior context found for this query.*

### Topic Classification
- **Topic:** unknown
- **Intent:** unknown""")

        context_doc.append_section(1, "Gathered Context", "\n\n".join(content_parts))
        return context_doc

    def _default_retrieval_prompt(self) -> str:
        """Default system prompt for RETRIEVAL phase."""
        return """You are the Context Gatherer (RETRIEVAL phase).

Your task is to identify relevant prior turns AND evaluate their content in a single pass.

## CRITICAL RULES

**RULE ZERO (FOLLOW-UPS):**
For follow-up queries (containing "it", "that", "some", "again", "more"), the N-1 turn
(immediately preceding) is ALWAYS CRITICAL. It contains the subject being referenced.

**RULE ONE (TOPIC RELEVANCE):**
Only mark turns as relevant if their topic matches the current query.
A laptop query should not pull in hamster turns, and vice versa.

**RULE TWO (RECENCY):**
More recent turns are generally more relevant than older ones.

**RULE THREE (DIRECT INFO):**
Extract usable information directly - don't just note that information exists.

## OUTPUT

Return JSON with identified turns, their usable info, and any links to follow."""

    def _default_synthesis_prompt(self) -> str:
        """Default system prompt for SYNTHESIS phase."""
        return """You are the Context Gatherer (SYNTHESIS phase).

Your task is to compile gathered information into the §1 Gathered Context section.

## STRUCTURE

Your output should include:
- ### Topic Classification (Topic + Intent)
- ### Prior Turn Context (summarize relevant prior turn info)
- ### User Preferences (if provided)
- ### Prior Research Intelligence (if available)
- ### Cached Intelligence (if available)

## RULES

1. PRESERVE SPECIFICS - Keep vendor names, prices, product names
2. COMPRESS VERBOSITY - Remove redundant information
3. MAINTAIN STRUCTURE - Follow the section format above
4. BE CONCISE - Target ~500-800 words for the entire section

Output MARKDOWN only."""


# Convenience function
async def gather_context_2phase(
    query: str,
    turn_number: int,
    session_id: str,
    llm_client: Any,
    **kwargs
) -> ContextDocument:
    """Convenience function for 2-phase context gathering."""
    gatherer = ContextGatherer2Phase(
        session_id=session_id,
        llm_client=llm_client,
        **kwargs
    )
    return await gatherer.gather(query=query, turn_number=turn_number)
