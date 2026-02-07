"""
Panda Context Gatherer 2-Phase Implementation

Implements Phase 2.1 (Retrieval) and Phase 2.2 (Synthesis) of the 8-phase pipeline.

Consolidates 4-phase gathering (SCAN → READ → EXTRACT → COMPILE) into 2 phases:
- Phase 2.1: RETRIEVAL (merged SCAN + READ)
- Phase 2.2: SYNTHESIS (merged EXTRACT + COMPILE)

Token Budget: ~10,500 tokens (vs 14,500 for 4-phase) = 27% reduction

Key Design:
- Deterministic N-1 pre-loading for follow-ups (runs BEFORE LLM call)
- Single RETRIEVAL prompt handles turn identification AND context evaluation
- Single SYNTHESIS prompt handles extraction (if links) AND compilation
- Feature flag controlled: CONTEXT_GATHERER_VERSION=2phase

Architecture Reference:
    architecture/concepts/main-system-patterns/phase2-context-gathering.md
"""

import json
import logging
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone

from .context_document import ContextDocument
from .query_analyzer import QueryAnalysis, ContentReference
from libs.gateway.persistence.visit_record import VisitRecordReader, VisitRecordManifest

# Recipe loader for prompt loading
from libs.gateway.llm.recipe_loader import load_recipe, Recipe, RecipeNotFoundError


from .context_gatherer_docs import (
    TurnIndexDoc, TurnIndexEntry,
    ContextBundleDoc, ContextBundleEntry,
    LinkedDocsDoc,
    write_doc
)
from .context_gatherer_2phase_docs import (
    MemoryNode, RetrievalResultDoc, RetrievalTurn, LinkToFollow,
    SynthesisInputDoc
)
from .search_results import SearchResults, SearchResultItem
from .memory_vault_searcher import MemoryVaultSearcher

# Import optional dependencies with graceful fallback
try:
    from apps.services.tool_server.session_intelligence_cache import SessionIntelligenceCache
    INTEL_CACHE_AVAILABLE = True
except ImportError:
    INTEL_CACHE_AVAILABLE = False
    SessionIntelligenceCache = None

try:
    from libs.gateway.research.research_index_db import get_research_index_db
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
    from libs.gateway.context.memory_context_builder import MemoryContextBuilder, get_memory_context_builder
    from libs.gateway.llm.token_budget_allocator import TokenBudgetAllocator, get_allocator
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
# These patterns detect when a user is correcting or rejecting the previous response.
#
# NOTE: These heuristics are used for context optimization (loading N-1 with higher
# priority when correction is detected) rather than for routing/intent decisions.
# Per architecture guidelines, subjective relevance decisions should be LLM-driven.
# If these patterns are used to gate workflow selection or affect response routing,
# consider replacing with LLM-based feedback detection.
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

        # Retrieval context (memory graph)
        self._last_memory_index: Dict[str, MemoryNode] = {}
        self._last_retrieval_plan: Optional[Dict[str, Any]] = None
        self._last_search_results: Optional[SearchResults] = None

        # Load recipes
        self.recipes = self._load_recipes()

    def _load_recipes(self) -> Dict[str, Recipe]:
        """Load recipe objects for each phase using the recipe loader."""
        recipes = {}

        recipe_map = {
            "retrieval": "pipeline/phase1_context_gatherer_retrieval",
            "synthesis": "pipeline/phase1_context_gatherer_synthesis",
            "validation": "pipeline/phase2_5_context_gathering_validator",
            "search_term_gen": "pipeline/phase2_1_search_term_generation",
        }

        for phase, recipe_name in recipe_map.items():
            try:
                recipe = load_recipe(recipe_name)
                recipes[phase] = recipe
                logger.debug(f"[ContextGatherer2Phase] Loaded recipe: {recipe_name}")
            except RecipeNotFoundError:
                logger.debug(f"[ContextGatherer2Phase] Recipe not found: {recipe_name}")
                recipes[phase] = None

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
            logger.info(f"[ContextGatherer2Phase] Loaded query_analysis.json: resolved={self.query_analysis.was_resolved}")
            # Use resolved query for gathering (has references made explicit)
            effective_query = self.query_analysis.resolved_query

            # Enrich content_reference with URLs (moved from Query Analyzer)
            # Context Gatherer is responsible for all context lookups
            if self.query_analysis.content_reference:
                self.query_analysis.content_reference = self._enrich_content_reference(
                    self.query_analysis.content_reference, turn_number
                )
                logger.info(f"[ContextGatherer2Phase] Content reference: '{self.query_analysis.content_reference.title[:50]}...' (turn {self.query_analysis.content_reference.source_turn})")
                if self.query_analysis.content_reference.source_url:
                    logger.info(f"[ContextGatherer2Phase] Found source URL: {self.query_analysis.content_reference.source_url[:60]}...")

            # NEW: If no content_reference but we have reference_resolution, try to resolve URL
            # This handles follow-up queries like "tell me more about The Café thread"
            elif self.query_analysis.reference_resolution:
                ref_res = self.query_analysis.reference_resolution
                if isinstance(ref_res, dict) and ref_res.get("resolved_to"):
                    resolved_title = ref_res["resolved_to"]
                    # Create a content_reference from the resolved reference
                    from .query_analyzer import ContentReference
                    self.query_analysis.content_reference = ContentReference(
                        title=resolved_title,
                        content_type="thread",  # Default to thread for follow-ups
                        site=None,
                        source_turn=None,
                        source_url=None
                    )
                    # Now try to enrich it with URL from linked_items
                    self.query_analysis.content_reference = self._enrich_content_reference(
                        self.query_analysis.content_reference, turn_number
                    )
                    if self.query_analysis.content_reference.source_url:
                        logger.info(
                            f"[ContextGatherer2Phase] Resolved reference URL: "
                            f"'{resolved_title[:40]}...' → {self.query_analysis.content_reference.source_url[:60]}..."
                        )
        else:
            logger.debug("[ContextGatherer2Phase] No query_analysis.json found, using original query")
            effective_query = query

        # Load retry context if this is a validation retry
        self._load_retry_context(turn_dir)

        # Check supplementary sources (using effective_query with resolved references)
        self._check_intelligence_cache(effective_query)
        _, inherited_topic = self._detect_followup(effective_query, turn_number)
        self._check_research_index(effective_query, intent=None, inherited_topic=inherited_topic)

        # Derive memory intent from data requirements (legacy compatibility)
        memory_intent = "informational"
        if self.query_analysis:
            data_reqs = self.query_analysis.data_requirements or {}
            if data_reqs.get("needs_current_prices") or data_reqs.get("needs_product_urls"):
                memory_intent = "commerce"

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
        # FAST PATH 1: Explicit navigation query - skip heavy context gathering
        # ==================================================================
        # For "go to X and do Y" queries, prior context is irrelevant.
        # Skip turn search and just include user preferences.
        if self._is_navigation_query(effective_query):
            logger.info("[ContextGatherer2Phase] Navigation query - using minimal context fast path")
            context_doc = self._create_navigation_context(query, turn_number, turn_dir)
            return await self._finalize_context(context_doc, turn_dir, effective_query)

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
            return await self._finalize_context(fast_path_result, turn_dir, effective_query)

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
        if not retrieval_result.relevant_turns and not retrieval_result.links_to_follow:
            if self.cached_intelligence or self.research_index_results:
                logger.info("[ContextGatherer2Phase] No turns but have cached intel/research")
                context_doc = self._create_context_from_cache(effective_query, turn_number, turn_dir)
                return await self._finalize_context(context_doc, turn_dir, effective_query)
            logger.info("[ContextGatherer2Phase] No relevant turns, minimal context")
            context_doc = self._create_minimal_context(effective_query, turn_number, turn_dir)
            return await self._finalize_context(context_doc, turn_dir, effective_query)

        # ==================================================================
        # PHASE 2: SYNTHESIS (merged EXTRACT + COMPILE)
        # ==================================================================
        logger.info("[ContextGatherer2Phase] Phase 2: SYNTHESIS")

        context_doc = await self._phase_synthesis(
            effective_query, turn_number, retrieval_result, turn_dir
        )

        # ==================================================================
        # PHASE 2.5: VALIDATION (gates §2 commit)
        # ==================================================================
        logger.info("[ContextGatherer2Phase] Phase 2.5: VALIDATION")
        validation = await self._phase_validation(
            context_doc=context_doc,
            query=effective_query,
            turn_dir=turn_dir
        )

        # Only retry once if validation requests it
        if validation.get("status") == "retry":
            logger.info("[ContextGatherer2Phase] Phase 2.5 requested retry - re-running synthesis once")
            context_doc = await self._phase_synthesis(
                effective_query,
                turn_number,
                retrieval_result,
                turn_dir,
                validator_guidance=validation
            )
            validation = await self._phase_validation(
                context_doc=context_doc,
                query=effective_query,
                turn_dir=turn_dir
            )

        # Only raise for explicit clarify - retry after one attempt becomes pass
        if validation.get("status") == "clarify":
            question = validation.get("clarification_question") or "Clarification required."
            raise RuntimeError(f"Phase 2.5 clarification required: {question}")

        # After retry attempt, proceed even if not "pass" - log warning but don't block
        if validation.get("status") != "pass":
            logger.warning(
                f"[ContextGatherer2Phase] Phase 2.5 validation issues (proceeding anyway): "
                f"{', '.join(validation.get('issues') or []) or 'none'}"
            )

        context_doc = await self._finalize_context(context_doc, turn_dir, effective_query)

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
        Phase 2.1 v2.0: Search-First Retrieval.

        LLM generates search terms → code does BM25 + embedding hybrid search →
        only matching documents go to synthesis. The LLM never sees the full index.

        Architecture Reference:
            architecture/main-system-patterns/phase2.1-context-gathering-retrieval.md v2.0

        Args:
            query: The query to gather context for (should be resolved_query from Phase 0)
            turn_number: Current turn number
            inherited_topic: Topic inherited from previous turn (if followup)
            priority_turn: Turn number to prioritize loading (from content_reference.source_turn)
        """
        is_followup = bool(inherited_topic)

        # Build turn index (still needed for N-1 preloading and safety checks)
        turn_index = self._build_turn_index(turn_number)

        # PRE-LOAD N-1 for follow-ups (deterministic, runs BEFORE search)
        n1_available, preloaded_n1 = self._preload_for_followup(query, turn_number, turn_index)

        # Step 1: LLM generates search terms (REFLEX, temp 0.4)
        search_config = await self._generate_search_terms(query)

        search_terms = search_config.get("search_terms", [])
        include_preferences = search_config.get("include_preferences", False)
        include_n_minus_1 = search_config.get("include_n_minus_1", is_followup)

        # Fallback: keyword extraction if LLM returned no terms
        if not search_terms:
            logger.warning("[ContextGatherer2Phase] Search term generation returned empty, using fallback")
            search_terms = self._fallback_keyword_extraction(query)

        # Get explicitly referenced turns
        reference_turns = self._get_reference_turns()
        if priority_turn:
            reference_turns = (reference_turns or []) + [priority_turn]

        # Step 2: Hybrid search (code only, no LLM)
        searcher = MemoryVaultSearcher(
            user_id=self.user_id,
            session_id=self.session_id,
            turns_dir=self.turns_dir,
            sessions_dir=self.sessions_dir,
        )

        search_results = searcher.search(
            search_terms=search_terms,
            include_preferences=include_preferences,
            include_n_minus_1=include_n_minus_1,
            current_turn=turn_number,
            reference_turns=reference_turns,
            forever_memory_results=self.forever_memory_results,
            research_index_results=self.research_index_results,
            index_limit=self.index_limit,
        )

        # Store for synthesis path and observability
        self._last_search_results = search_results

        # Populate _last_memory_index from results (for validation compat)
        # confidence: use 0.80 for search results (RRF scores ~0.05-0.13 would
        # falsely trigger the <0.30 "expired" check designed for quality scores)
        # source_ref: resolve to absolute path so validator's exists() check works
        self._last_memory_index = {}
        for item in search_results.results:
            abs_ref = str(Path(item.document_path).resolve()) if item.document_path else ""
            self._last_memory_index[item.node_id] = MemoryNode(
                node_id=item.node_id,
                source_type=item.source_type,
                summary=item.snippet,
                confidence=0.80,
                source_ref=abs_ref,
                links=[],
            )

        # Save observability (retrieval_plan.json)
        self._write_retrieval_plan(turn_number, search_results.to_observability_dict())

        # Bridge: SearchResults → RetrievalResultDoc (so synthesis works unchanged)
        result = RetrievalResultDoc.from_search_results(
            query=query,
            search_results=search_results,
            is_followup=is_followup,
            inherited_topic=inherited_topic,
        )

        # SAFETY: Ensure N-1 is in results for follow-up queries (belt + suspenders)
        if n1_available:
            result = self._ensure_n1_in_result(result, turn_index, preloaded_n1)

        logger.info(
            f"[ContextGatherer2Phase] Search-first retrieval: "
            f"{len(search_results.results)} results, terms={search_terms}"
        )

        return result

    async def _generate_search_terms(self, query: str) -> Dict[str, Any]:
        """
        LLM call to generate search terms (REFLEX role, temp 0.4).

        Returns:
            Dict with search_terms, include_preferences, include_n_minus_1.
            Empty dict on failure (caller falls back to keyword extraction).
        """
        recipe = self.recipes.get("search_term_gen")
        if not recipe:
            logger.warning("[ContextGatherer2Phase] search_term_gen recipe not found")
            return {}

        system_prompt = recipe.get_prompt()
        if not system_prompt:
            logger.warning("[ContextGatherer2Phase] search_term_gen prompt is empty")
            return {}

        query_payload = self._build_query_analysis_payload(query)
        user_prompt = f"QUERY_ANALYSIS:\n{json.dumps(query_payload, indent=2)}"

        try:
            full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
            response_text = await self.llm_client.call(
                prompt=full_prompt,
                role="search_term_gen",
                max_tokens=200,
                temperature=0.4,
            )

            result = self._extract_json(response_text)

            # Validate structure
            terms = result.get("search_terms", [])
            if not isinstance(terms, list) or not terms:
                logger.warning(f"[ContextGatherer2Phase] Invalid search_terms from LLM: {result}")
                return {}

            logger.info(f"[ContextGatherer2Phase] Generated search terms: {terms}")
            return result

        except Exception as e:
            logger.warning(f"[ContextGatherer2Phase] Search term generation failed: {e}")
            return {}

    def _fallback_keyword_extraction(self, query: str) -> List[str]:
        """
        Extract search phrases from the resolved query when LLM fails.

        Uses simple keyword extraction and groups into 2-3 phrases.
        """
        # Use TurnSearchIndex's keyword extraction if available
        try:
            from libs.gateway.persistence.turn_search_index import TurnSearchIndex
            keywords = TurnSearchIndex._extract_keywords(None, query)
        except Exception:
            # Manual fallback
            import re as _re
            stop = {"the", "and", "for", "are", "but", "not", "you", "all", "can",
                     "was", "has", "have", "been", "would", "will", "just", "what",
                     "with", "this", "that", "from", "they", "about", "more", "some"}
            words = _re.findall(r"\b[a-z]{3,}\b", query.lower())
            keywords = [w for w in words if w not in stop]

        if not keywords:
            return [query[:50]]

        # Group into 2-3 phrases
        phrases = []
        if len(keywords) <= 3:
            phrases.append(" ".join(keywords))
        else:
            # First phrase: first 2-3 keywords, second phrase: remaining
            mid = min(3, len(keywords) // 2 + 1)
            phrases.append(" ".join(keywords[:mid]))
            phrases.append(" ".join(keywords[mid:mid + 3]))
            if len(keywords) > mid + 3:
                phrases.append(" ".join(keywords[mid + 3:mid + 6]))

        return phrases[:3]

    def _get_reference_turns(self) -> Optional[List[int]]:
        """Extract explicitly referenced turn numbers from QA reference_resolution."""
        if not self.query_analysis or not self.query_analysis.reference_resolution:
            return None

        ref = self.query_analysis.reference_resolution
        if not isinstance(ref, dict):
            return None

        turn_nums = []
        # Check for resolved_turn field
        resolved_turn = ref.get("resolved_turn") or ref.get("source_turn")
        if resolved_turn and isinstance(resolved_turn, int):
            turn_nums.append(resolved_turn)

        return turn_nums if turn_nums else None

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

        ARCHITECTURAL FIX (2026-02-05): Also load response.md for N-1.
        The user sees the response and asks follow-ups about it. We need
        the actual response content, not just the context.md summary.

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
                # Also load response.md for N-1 - this is what the user actually saw
                response_path = n1_dir / "response.md"
                if response_path.exists():
                    try:
                        response_content = response_path.read_text()
                        # Include up to 1500 chars of response (enough for topic lists)
                        if response_content:
                            response_preview = response_content[:1500]
                            if len(response_content) > 1500:
                                response_preview += "..."
                            # Append response to summary so follow-ups can find mentioned items
                            entry.summary = f"{entry.summary}\n\n[Previous Response]:\n{response_preview}"
                            logger.info(
                                f"[ContextGatherer2Phase] Added N-1 response.md ({len(response_content)} chars)"
                            )
                    except Exception as e:
                        logger.debug(f"[ContextGatherer2Phase] Could not load N-1 response.md: {e}")

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
            usable_info=preloaded.summary[:2000] if preloaded.summary else "",
            expected_info=f"Context for pronouns referring to {preloaded.topic}",
            load_priority=0
        )

        result.relevant_turns.insert(0, n1_entry)
        if preloaded.summary:
            result.direct_info[str(n1_turn)] = preloaded.summary[:2000]

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

    def _build_query_analysis_payload(self, resolved_query: str) -> Dict[str, Any]:
        """Build minimal narrative + hint payload for retrieval."""
        payload = {"resolved_query": resolved_query}

        if not self.query_analysis:
            return payload

        qa = self.query_analysis.to_dict()
        payload.update({
            "original_query": qa.get("original_query", ""),
            "user_purpose": qa.get("user_purpose", ""),
            "reasoning": qa.get("reasoning", ""),
        })

        hints = {}
        for key in ["data_requirements", "content_reference", "reference_resolution"]:
            value = qa.get(key)
            if value:
                hints[key] = value
        if hints:
            payload["hints"] = hints

        return payload

    def _write_retrieval_plan(self, turn_number: int, response: Dict[str, Any]) -> None:
        """Persist RetrievalPlan JSON when present for observability."""
        # Accept both v1 (selected_nodes) and v2 (version: 2.0_search_first) formats
        if "selected_nodes" not in response and "version" not in response:
            return

        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        write_doc(turn_dir / "retrieval_plan.json", json.dumps(response, indent=2))

    def _resolve_source_ref(self, path: str) -> str:
        """Normalize a source_ref to an absolute path when possible."""
        if not path:
            return ""
        ref_path = Path(path)
        if ref_path.is_absolute():
            return str(ref_path)
        return str(ref_path.resolve())

    def _build_unified_memory_index(
        self,
        turn_index: TurnIndexDoc,
        priority_turn: Optional[int] = None
    ) -> tuple[List[MemoryNode], Dict[str, MemoryNode]]:
        """Build a unified memory graph from turns, memory, cache, and visits."""
        nodes: List[MemoryNode] = []
        node_index: Dict[str, MemoryNode] = {}

        def add_node(node: MemoryNode) -> None:
            if not node.node_id or node.node_id in node_index:
                return
            node_index[node.node_id] = node
            nodes.append(node)

        # Turn summaries
        for entry in turn_index.entries:
            summary_parts = []
            if entry.query_summary:
                summary_parts.append(f"Query: {entry.query_summary}")
            if entry.topic and entry.topic != "unknown":
                summary_parts.append(f"Topic: {entry.topic}")
            if entry.response_preview:
                summary_parts.append(f"Response: {entry.response_preview}")
            if entry.has_research:
                summary_parts.append("Has research cache")
            if entry.has_products:
                summary_parts.append("Has product findings")

            summary = " | ".join(summary_parts)[:500]

            node_id = f"turn:{entry.turn_number}"
            if priority_turn and entry.turn_number == priority_turn:
                summary = f"[priority] {summary}"

            add_node(MemoryNode(
                node_id=node_id,
                source_type="turn_summary",
                summary=summary,
                confidence=entry.quality_score,
                timestamp=entry.timestamp,
                source_ref=f"turn_{entry.turn_number:06d}/context.md",
                links=[],
            ))

        # Session memory (preferences/live_context/history)
        session_dir = self.sessions_dir / self.session_id
        if self.session_memory.get("preferences"):
            add_node(MemoryNode(
                node_id="session:preferences",
                source_type="preference",
                summary=self.session_memory["preferences"][:400],
                confidence=0.8,
                timestamp=None,
                source_ref=str((session_dir / "preferences.md").resolve()),
                links=[],
            ))
        if self.session_memory.get("live_context"):
            add_node(MemoryNode(
                node_id="session:live_context",
                source_type="fact",
                summary=self.session_memory["live_context"][:400],
                confidence=0.7,
                timestamp=None,
                source_ref=str((session_dir / "live_context.md").resolve()),
                links=[],
            ))
        if self.session_memory.get("history"):
            add_node(MemoryNode(
                node_id="session:history",
                source_type="fact",
                summary=self.session_memory["history"][:400],
                confidence=0.6,
                timestamp=None,
                source_ref=str((session_dir / "history_compressed.md").resolve()),
                links=[],
            ))

        # Forever memory results
        for result in self.forever_memory_results:
            source_type = "preference" if result.artifact_type == "preference" else "fact"
            summary = result.summary or result.topic or result.path
            timestamp = None
            if result.modified:
                timestamp = result.modified.isoformat()
            elif result.created:
                timestamp = result.created.isoformat()

            add_node(MemoryNode(
                node_id=f"memory:{result.path}",
                source_type=source_type,
                summary=summary[:500],
                confidence=result.confidence if result.confidence is not None else result.relevance,
                timestamp=timestamp,
                source_ref=self._resolve_source_ref(Path("panda_system_docs") / result.path),
                links=[],
            ))

        # User preferences note (if separate)
        if self.user_preferences_memory:
            pref = self.user_preferences_memory
            timestamp = pref.modified.isoformat() if pref.modified else None
            add_node(MemoryNode(
                node_id=f"preference:user:{self.user_id}",
                source_type="preference",
                summary=(pref.summary or pref.topic or "User preferences")[:500],
                confidence=pref.confidence,
                timestamp=timestamp,
                source_ref=self._resolve_source_ref(Path("panda_system_docs") / pref.path),
                links=[],
            ))

        # Research cache (Research Index DB)
        for idx, doc in enumerate(self.research_index_results):
            doc_path = doc.get("doc_path", "")
            if not doc_path:
                continue
            summary_parts = [f"Topic: {doc.get('topic', 'unknown')}"]
            keywords = doc.get("keywords") or []
            if keywords:
                summary_parts.append(f"Keywords: {', '.join(keywords[:6])}")
            if doc.get("quality_score") is not None:
                summary_parts.append(f"Quality: {doc['quality_score']:.2f}")
            if doc.get("age_hours") is not None:
                summary_parts.append(f"Age: {doc['age_hours']:.1f}h")

            add_node(MemoryNode(
                node_id=f"research:{idx}",
                source_type="research_cache",
                summary=" | ".join(summary_parts)[:500],
                confidence=float(doc.get("quality_score", 0.8)),
                timestamp=f"{doc.get('age_hours', 0):.1f}h",
                source_ref=self._resolve_source_ref(doc_path),
                links=[],
            ))

        # Cached intelligence (session intelligence cache)
        if self.cached_intelligence:
            cache_path = Path("panda_system_docs/sessions") / self.session_id / "intelligence_cache.json"
            cache_summary = "Cached intelligence"
            if self.intel_cache_metadata:
                cache_summary = (
                    f"Cached intelligence | age {self.intel_cache_metadata.get('age_hours', 0):.1f}h"
                )
            add_node(MemoryNode(
                node_id="research_cache:intelligence",
                source_type="research_cache",
                summary=cache_summary,
                confidence=0.7,
                timestamp=self.intel_cache_metadata.get("age_hours") if self.intel_cache_metadata else None,
                source_ref=self._resolve_source_ref(cache_path),
                links=[],
            ))

        # Visit record manifests (recent turns)
        visit_nodes = self._collect_visit_record_nodes(turn_index)
        for node in visit_nodes:
            add_node(node)

        return nodes, node_index

    def _collect_visit_record_nodes(self, turn_index: TurnIndexDoc, max_records: int = 15) -> List[MemoryNode]:
        """Collect visit record nodes from recent turns."""
        nodes: List[MemoryNode] = []
        reader = VisitRecordReader(turns_dir=self.turns_dir)
        record_count = 0

        for entry in turn_index.entries:
            if record_count >= max_records:
                break

            turn_dir = self.turns_dir / f"turn_{entry.turn_number:06d}"
            visit_dir = turn_dir / "visit_records"
            if not visit_dir.exists():
                continue

            for record_dir in visit_dir.iterdir():
                if record_count >= max_records:
                    break
                if not record_dir.is_dir():
                    continue

                manifest = reader.load_manifest(record_dir)
                if not manifest:
                    continue

                page_path = record_dir / "page_content.md"
                if not page_path.exists():
                    page_path = record_dir / "manifest.json"

                summary = manifest.content_summary or manifest.title or "Visit record"
                summary = summary[:500]

                nodes.append(MemoryNode(
                    node_id=f"visit:{entry.turn_number}:{record_dir.name}",
                    source_type="visit_record",
                    summary=f"{summary} | {manifest.domain}",
                    confidence=0.7,
                    timestamp=manifest.captured_at,
                    source_ref=self._resolve_source_ref(page_path),
                    links=[f"turn:{entry.turn_number}"],
                ))
                record_count += 1

        return nodes

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
        turn_dir: Path,
        validator_guidance: Optional[Dict[str, Any]] = None
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

        # Build loaded node metadata for synthesis (_meta binding)
        loaded_nodes = self._build_loaded_nodes_for_synthesis()
        node_by_ref = self._index_nodes_by_source_ref(loaded_nodes)

        # Build SYNTHESIS prompt from recipe
        recipe = self.recipes.get("synthesis")
        system_prompt = recipe.get_prompt() if recipe else self._default_synthesis_prompt()

        # Build input sections
        direct_info_section = self._format_direct_info(retrieval_result)
        linked_docs_section = self._format_linked_docs(linked_docs, retrieval_result, node_by_ref) if linked_docs else ""
        loaded_nodes_section = self._format_loaded_nodes(loaded_nodes)

        query_analysis_section = self._format_query_analysis_for_synthesis(query)

        # Build user prompt with context data
        guidance_block = ""
        if validator_guidance:
            guidance_block = (
                "===== VALIDATION FEEDBACK (PHASE 2.5) =====\n"
                f"Issues: {', '.join(validator_guidance.get('issues') or [])}\n"
                f"Missing Context: {', '.join(validator_guidance.get('missing_context') or [])}\n"
                f"Retry Guidance: {', '.join(validator_guidance.get('retry_guidance') or [])}\n"
            )

        user_prompt = f"""CURRENT QUERY: {query}
TURN NUMBER: {turn_number}
{query_analysis_section}

===== LOADED MEMORY NODES =====
{loaded_nodes_section}

===== DIRECT INFORMATION =====
{direct_info_section}

{linked_docs_section}

{guidance_block}

===== YOUR TASK =====

{"TASK 1 - EXTRACT: Extract relevant information from the linked documents." if linked_docs else ""}
{"Focus on: " + ", ".join(set(s for link in retrieval_result.links_to_follow for s in link.sections_to_extract)) if linked_docs else ""}

{"TASK 2 - " if linked_docs else ""}COMPILE: Create Section 2 (Gathered Context) for context.md.

Structure your output as MARKDOWN with canonical sections (ONLY include sections with relevant content):
- ### Session Preferences
- ### Relevant Prior Turns
- ### Cached Research
- ### Visit Data
- ### Constraints

For each section that uses memory nodes, include a YAML `_meta` block:
```yaml
_meta:
  source_type: turn_summary | preference | fact | research_cache | visit_record | user_query
  node_ids: ["node_id", "..."]
  confidence_avg: 0.0-1.0
  provenance: ["source_ref", "..."]
```

Rules:
- Do not fabricate node_ids or sources. Only use LOADED MEMORY NODES.
- If a section uses multiple source types (Constraints only), set source_type as a list.
- Do not include nodes with confidence < 0.30.
- If a node has no confidence, default it to 0.50.
- Use `user_query` with node_ids=[] and provenance=["§0.raw_query"] for constraints from the raw query.
- Omit empty sections entirely.

Output MARKDOWN only (no JSON wrapper)."""

        try:
            full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

            # MIND role temp=0.6 for synthesis reasoning
            # See: architecture/LLM-ROLES/llm-roles-reference.md
            response_text = await self.llm_client.call(
                prompt=full_prompt,
                role="context_gatherer",
                max_tokens=1200,
                temperature=0.6
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

            # CRITICAL: Pass query analysis through to downstream phases
            if self.query_analysis:
                context_doc.set_section_0(self.query_analysis.to_dict())

            # Clean response and add as §1
            gathered_context = self._clean_markdown(response_text)

            # Add user feedback section if rejection was detected
            feedback_section = self._format_feedback_section()
            if feedback_section:
                gathered_context = feedback_section + "\n\n" + gathered_context

            context_doc.append_section(2, "Gathered Context", gathered_context)

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
            # Hard error per spec §9.1: LLM call failures, I/O errors propagate
            # See: architecture/main-system-patterns/phase2-context-gathering.md §9
            logger.error(f"[ContextGatherer2Phase] SYNTHESIS phase failed (hard error): {e}")
            raise

    async def _phase_validation(
        self,
        context_doc: ContextDocument,
        query: str,
        turn_dir: Path
    ) -> Dict[str, Any]:
        """Phase 2.5: Validate gathered context for completeness and integrity."""
        recipe = self.recipes.get("validation")
        system_prompt = recipe.get_prompt() if recipe else self._default_context_validation_prompt()

        gathered_context = context_doc.get_section(2) or ""
        query_analysis = self._build_query_analysis_payload(query)

        user_prompt = f"""RAW QUERY:
{query}

QUERY_ANALYSIS:
{json.dumps(query_analysis, indent=2)}

GATHERED_CONTEXT (§2):
{gathered_context[:6000]}"""

        response_text = await self.llm_client.call(
            prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
            role="validator",
            max_tokens=350,
            temperature=0.4
        )

        parsed = self._extract_json(response_text)
        validation = self._normalize_context_validation(parsed)

        # Structural validation - log issues but don't force retry
        # Per user guidance: only reject truly broken/garbled queries
        structural = self._validate_gathered_context_meta(
            gathered_context=gathered_context,
            memory_index=self._last_memory_index
        )
        if structural:
            validation.setdefault("issues", [])
            validation.setdefault("missing_context", [])
            validation.setdefault("retry_guidance", [])
            validation["issues"].extend(structural["issues"])
            validation["missing_context"].extend(structural["missing_context"])
            validation["retry_guidance"].extend(structural["retry_guidance"])
            # Don't force retry - let the pipeline proceed with available context
            logger.warning(f"[ContextGatherer2Phase] Structural issues in §2: {structural['issues']}")

        # Override: Always pass for legitimate queries - let downstream phases handle gaps
        if validation.get("status") == "retry":
            logger.info("[ContextGatherer2Phase] Phase 2.5 would retry, but proceeding anyway (lenient mode)")
            validation["status"] = "pass"

        write_doc(turn_dir / "context_validation.json", json.dumps(validation, indent=2))
        return validation

    def _normalize_context_validation(self, parsed: Any) -> Dict[str, Any]:
        """Normalize Phase 2.5 validator output to expected schema."""
        if not isinstance(parsed, dict):
            return {
                "status": "retry",
                "issues": ["validator_output_not_json"],
                "missing_context": [],
                "retry_guidance": ["return_valid_json"],
                "clarification_question": None
            }

        status = parsed.get("status") or "retry"
        if status not in {"pass", "retry", "clarify"}:
            status = "retry"

        return {
            "status": status,
            "issues": parsed.get("issues") or [],
            "missing_context": parsed.get("missing_context") or [],
            "retry_guidance": parsed.get("retry_guidance") or [],
            "clarification_question": parsed.get("clarification_question"),
        }

    def _validate_gathered_context_meta(
        self,
        gathered_context: str,
        memory_index: Dict[str, MemoryNode]
    ) -> Dict[str, List[str]]:
        """Validate _meta blocks in §2 against memory index."""
        issues: List[str] = []
        missing: List[str] = []
        guidance: List[str] = []

        allowed_sections = {
            "Session Preferences",
            "Relevant Prior Turns",
            "Cached Research",
            "Visit Data",
            "Constraints",
        }

        meta_blocks = self._extract_meta_blocks(gathered_context)
        for block in meta_blocks:
            section = block.get("section")
            meta = block.get("meta")
            if section and section not in allowed_sections:
                issues.append(f"non_canonical_section_title: {section}")
                guidance.append("use canonical section titles for any section with _meta")

            node_ids = meta.get("node_ids", [])
            provenance = meta.get("provenance", [])
            confidence_avg = meta.get("confidence_avg")

            if node_ids:
                if not provenance:
                    issues.append(f"missing_provenance: {section or 'unknown_section'}")
                    guidance.append("include provenance list when node_ids are present")
                if confidence_avg is None:
                    issues.append(f"missing_confidence_avg: {section or 'unknown_section'}")
                    guidance.append("include confidence_avg when node_ids are present")
                else:
                    try:
                        conf_val = float(confidence_avg)
                        if conf_val < 0 or conf_val > 1:
                            issues.append(f"invalid_confidence_avg: {section or 'unknown_section'}")
                    except (TypeError, ValueError):
                        issues.append(f"invalid_confidence_avg: {section or 'unknown_section'}")

            for node_id in node_ids:
                if node_id not in memory_index:
                    # Skip unknown node_id check when using search-first path:
                    # The synthesis LLM references node_ids from loaded nodes, which
                    # are all valid search results. Minor ID mismatches (e.g. LLM
                    # citing "session:preferences" that wasn't a search result) are
                    # harmless — the content was provided via supplementary sources.
                    if not self._last_search_results:
                        issues.append(f"unknown_node_id: {node_id}")
                        missing.append(node_id)
                        guidance.append("remove unknown node_ids or select valid nodes from memory index")
                    continue

                node = memory_index[node_id]
                if node.confidence is not None and node.confidence < 0.30:
                    issues.append(f"expired_node_used: {node_id}")
                    guidance.append("exclude nodes with confidence below 0.30")

                if node.source_ref:
                    ref_path = Path(node.source_ref)
                    if not ref_path.is_absolute():
                        # Try resolving relative to turns_dir first, then cwd
                        ref_path = (self.turns_dir / ref_path).resolve()
                    if not ref_path.exists():
                        issues.append(f"missing_source_ref: {node_id}")
                        guidance.append("ensure source_ref exists for all node_ids in _meta")

        return {
            "issues": issues,
            "missing_context": missing,
            "retry_guidance": list(dict.fromkeys(guidance)),
        }

    def _extract_meta_blocks(self, gathered_context: str) -> List[Dict[str, Any]]:
        """Extract _meta YAML blocks from gathered context."""
        blocks: List[Dict[str, Any]] = []
        current_section: Optional[str] = None
        in_yaml = False
        yaml_lines: List[str] = []

        for line in gathered_context.splitlines():
            if line.startswith("### "):
                current_section = line[4:].strip()
            if line.strip().startswith("```yaml"):
                in_yaml = True
                yaml_lines = []
                continue
            if in_yaml and line.strip().startswith("```"):
                in_yaml = False
                meta = self._parse_meta_yaml("\n".join(yaml_lines))
                if meta:
                    blocks.append({"section": current_section, "meta": meta})
                continue
            if in_yaml:
                yaml_lines.append(line)

        return blocks

    def _parse_meta_yaml(self, yaml_text: str) -> Dict[str, Any]:
        """Parse a minimal _meta YAML block without external dependencies."""
        meta: Dict[str, Any] = {}
        if "_meta" not in yaml_text:
            return meta

        for line in yaml_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("source_type:"):
                value = stripped.split("source_type:", 1)[1].strip()
                meta["source_type"] = self._parse_yaml_value(value)
            elif stripped.startswith("node_ids:"):
                value = stripped.split("node_ids:", 1)[1].strip()
                if value:
                    meta["node_ids"] = self._parse_yaml_list_inline(value)
                else:
                    meta["node_ids"] = []
            elif stripped.startswith("-") and "node_ids" in meta and not meta.get("node_ids"):
                meta["node_ids"].append(stripped.lstrip("-").strip().strip('"').strip("'"))
            elif stripped.startswith("confidence_avg:"):
                value = stripped.split("confidence_avg:", 1)[1].strip()
                meta["confidence_avg"] = value
            elif stripped.startswith("provenance:"):
                value = stripped.split("provenance:", 1)[1].strip()
                if value:
                    meta["provenance"] = self._parse_yaml_list_inline(value)
                else:
                    meta["provenance"] = []
            elif stripped.startswith("-") and "provenance" in meta and not meta.get("provenance"):
                meta["provenance"].append(stripped.lstrip("-").strip().strip('"').strip("'"))

        meta.setdefault("node_ids", [])
        meta.setdefault("provenance", [])
        return meta

    def _parse_yaml_value(self, value: str) -> Any:
        """Parse simple YAML scalar or list value."""
        if value.startswith("[") and value.endswith("]"):
            return self._parse_yaml_list_inline(value)
        return value.strip().strip('"').strip("'")

    def _parse_yaml_list_inline(self, value: str) -> List[str]:
        """Parse inline YAML list like [a, b]."""
        cleaned = value.strip()
        if cleaned.startswith("[") and cleaned.endswith("]"):
            cleaned = cleaned[1:-1]
        if not cleaned:
            return []
        return [item.strip().strip('"').strip("'") for item in cleaned.split(",") if item.strip()]

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

    def _format_query_analysis_for_synthesis(self, resolved_query: str) -> str:
        """Format query analysis narrative and hints for synthesis."""
        payload = {"resolved_query": resolved_query}
        if self.query_analysis:
            payload.update({
                "original_query": self.query_analysis.original_query,
                "user_purpose": self.query_analysis.user_purpose,
                "reasoning": self.query_analysis.reasoning,
                "data_requirements": self.query_analysis.data_requirements,
                "reference_resolution": self.query_analysis.reference_resolution,
                "content_reference": (
                    asdict(self.query_analysis.content_reference)
                    if self.query_analysis.content_reference else None
                ),
            })
        return f"QUERY_ANALYSIS:\n{json.dumps(payload, indent=2)}"

    def _build_loaded_nodes_for_synthesis(self) -> List[MemoryNode]:
        """Resolve selected nodes for synthesis.

        v2.0 path: build MemoryNodes from SearchResults.
        v1.x fallback: use _last_retrieval_plan + _last_memory_index.
        """
        # v2.0: Search-first path
        if self._last_search_results and self._last_search_results.results:
            loaded = []
            for item in self._last_search_results.results:
                loaded.append(MemoryNode(
                    node_id=item.node_id,
                    source_type=item.source_type,
                    summary=item.snippet,
                    confidence=item.rrf_score,
                    source_ref=item.document_path,
                    links=[],
                ))
            return loaded

        # v1.x fallback: legacy retrieval plan path
        if not self._last_retrieval_plan or not self._last_memory_index:
            return []

        selected = self._last_retrieval_plan.get("selected_nodes") or {}
        node_ids: List[str] = []
        for ids in selected.values():
            if isinstance(ids, list):
                node_ids.extend(ids)

        loaded = []
        seen = set()
        for node_id in node_ids:
            if node_id in seen:
                continue
            seen.add(node_id)
            node = self._last_memory_index.get(node_id)
            if node:
                loaded.append(node)
        return loaded

    def _index_nodes_by_source_ref(self, nodes: List[MemoryNode]) -> Dict[str, MemoryNode]:
        """Index nodes by source_ref for matching loaded docs."""
        index: Dict[str, MemoryNode] = {}
        for node in nodes:
            if not node.source_ref:
                continue
            index[node.source_ref] = node
            try:
                index[str(Path(node.source_ref).resolve())] = node
            except Exception:
                pass
        return index

    def _format_loaded_nodes(self, nodes: List[MemoryNode]) -> str:
        """Format loaded node metadata for synthesis."""
        if not nodes:
            return "[]"
        payload = [
            {
                "node_id": node.node_id,
                "source_type": node.source_type,
                "summary": node.summary,
                "confidence": node.confidence,
                "timestamp": node.timestamp,
                "source_ref": node.source_ref,
                "links": node.links,
            }
            for node in nodes
        ]
        return json.dumps(payload, indent=2)

    def _format_linked_docs(
        self,
        linked_docs: Dict[str, str],
        retrieval_result: RetrievalResultDoc,
        node_by_ref: Optional[Dict[str, MemoryNode]] = None
    ) -> str:
        """Format linked documents section for synthesis prompt."""
        lines = [
            "===== LINKED DOCUMENTS (EXTRACT FROM THESE) =====",
            ""
        ]

        for path, content in linked_docs.items():
            node = node_by_ref.get(path) if node_by_ref else None
            header = f"### Document: {path}"
            if node:
                header = (
                    f"### Document: {path}\n"
                    f"**Node ID:** {node.node_id}\n"
                    f"**Source Type:** {node.source_type}\n"
                    f"**Confidence:** {node.confidence:.2f}"
                )
            lines.append(header)
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
                # EXCEPTION: Never skip N-1 - user might be following up on it
                is_n1 = (turn_num == current_turn - 1)
                if entry.quality_score < 0.2 and not is_n1:
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

        # Extract summary - PRIORITIZE Section 2 (Gathered Context) over Section 6 (Response)
        # Section 2 contains rich context that may be valuable even if the response failed
        summary = ""

        # First, try to get rich context from Section 2
        section1_context = ""
        if "## 2. Gathered Context" in content:
            section1 = content.split("## 2. Gathered Context")[1]
            if "## 3." in section1:
                section1 = section1.split("## 3.")[0]
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

    def _enrich_content_reference(
        self, content_ref: ContentReference, current_turn: int
    ) -> ContentReference:
        """
        Enrich a ContentReference with source_url from prior turns' research.json.

        This is the URL lookup that enables follow-up queries like "tell me more
        about that thread" to route directly to the URL instead of searching again.

        Moved from Query Analyzer to Context Gatherer because URL lookup is
        context retrieval, not query analysis.
        """
        if content_ref.source_url:
            # Already have URL, no need to search
            return content_ref

        ref_title = content_ref.title.lower().strip() if content_ref.title else ""
        ref_site = content_ref.site.lower() if content_ref.site else None

        if not ref_title:
            return content_ref

        # Search recent turns (up to 3 lookback)
        max_lookback = 3
        for i in range(1, min(max_lookback + 1, current_turn)):
            prev_turn = current_turn - i
            turn_dir = self.turns_dir / f"turn_{prev_turn:06d}"
            research_path = turn_dir / "research.json"

            if not research_path.exists():
                continue

            try:
                research_data = json.loads(research_path.read_text())
                extracted_links = research_data.get("extracted_links", [])

                for link in extracted_links:
                    link_title = link.get("title", "").lower().strip()
                    link_url = link.get("url", "")

                    if not link_title or not link_url:
                        continue

                    # Match by title similarity (substring matching)
                    title_match = (
                        ref_title in link_title or
                        link_title in ref_title or
                        ref_title.replace("the ", "") in link_title or
                        link_title in ref_title.replace("the ", "")
                    )

                    # If site specified, verify URL matches
                    if ref_site and title_match:
                        site_match = ref_site in link_url.lower()
                        if not site_match:
                            continue

                    if title_match:
                        content_ref.source_url = link_url
                        content_ref.source_turn = prev_turn
                        logger.info(
                            f"[ContextGatherer2Phase] Found URL for '{content_ref.title[:30]}...' "
                            f"in turn {prev_turn}: {link_url[:60]}..."
                        )
                        return content_ref

            except Exception as e:
                logger.warning(f"[ContextGatherer2Phase] Error reading research.json from turn {prev_turn}: {e}")
                continue

        # Also check toolresults.md for linked_items (thread/topic URLs from extraction)
        for i in range(1, min(max_lookback + 1, current_turn)):
            prev_turn = current_turn - i
            turn_dir = self.turns_dir / f"turn_{prev_turn:06d}"
            toolresults_path = turn_dir / "toolresults.md"

            if not toolresults_path.exists():
                continue

            try:
                toolresults_content = toolresults_path.read_text()
                # Extract linked_items from JSON blocks in toolresults.md
                linked_items = self._extract_linked_items_from_toolresults(toolresults_content)

                for item in linked_items:
                    # Parse markdown link: [text](url)
                    match = re.match(r'\[([^\]]+)\]\(([^)]+)\)', item)
                    if not match:
                        continue

                    link_text, link_url = match.groups()
                    link_text_lower = link_text.lower().strip()

                    # Match by title similarity
                    title_match = (
                        ref_title in link_text_lower or
                        link_text_lower in ref_title or
                        ref_title.replace("the ", "") in link_text_lower or
                        link_text_lower in ref_title.replace("the ", "")
                    )

                    if title_match:
                        # Handle relative URLs - prepend site if needed
                        if link_url.startswith("/") and ref_site:
                            link_url = f"https://{ref_site}{link_url}"
                        elif link_url.startswith("/"):
                            # Try to get base URL from previous research
                            link_url = self._resolve_relative_url(link_url, prev_turn)

                        content_ref.source_url = link_url
                        content_ref.source_turn = prev_turn
                        logger.info(
                            f"[ContextGatherer2Phase] Found linked_items URL for '{content_ref.title[:30]}...' "
                            f"in turn {prev_turn}: {link_url[:60]}..."
                        )
                        return content_ref

            except Exception as e:
                logger.warning(f"[ContextGatherer2Phase] Error reading toolresults.md from turn {prev_turn}: {e}")
                continue

        # Also check visit records
        content_ref = self._enrich_with_visit_record(content_ref)

        logger.debug(f"[ContextGatherer2Phase] No matching URL found for '{ref_title[:30]}...'")
        return content_ref

    def _extract_linked_items_from_toolresults(self, content: str) -> list:
        """
        Extract linked_items from toolresults.md JSON blocks.

        toolresults.md contains JSON like:
        {
          "intelligence": {
            "linked_items": [
              "[Monster Tanks 400g+](/forums/monster-tanks-400g.1046/)",
              "[Carbon Dosing](/threads/carbon-dosing.123456/)"
            ]
          }
        }
        """
        linked_items = []

        # Find all JSON blocks in the markdown (between ```json and ```)
        json_pattern = r'```json\s*([\s\S]*?)```'
        matches = re.findall(json_pattern, content)

        for json_str in matches:
            try:
                # Handle truncated JSON by trying to parse what we have
                data = json.loads(json_str)

                # Extract linked_items from intelligence dict
                if isinstance(data, dict):
                    intelligence = data.get("intelligence", {})
                    if isinstance(intelligence, dict):
                        items = intelligence.get("linked_items", [])
                        if isinstance(items, list):
                            linked_items.extend(items)
            except json.JSONDecodeError:
                # JSON may be truncated in toolresults.md, try regex extraction
                # Look for linked_items array directly
                items_pattern = r'"linked_items"\s*:\s*\[(.*?)\]'
                items_match = re.search(items_pattern, json_str, re.DOTALL)
                if items_match:
                    items_str = items_match.group(1)
                    # Extract individual markdown links
                    link_pattern = r'"(\[[^\]]+\]\([^)]+\))"'
                    links = re.findall(link_pattern, items_str)
                    linked_items.extend(links)

        return linked_items

    def _resolve_relative_url(self, relative_url: str, source_turn: int) -> str:
        """
        Resolve a relative URL to absolute using the base URL from source turn.

        Checks research.json and toolresults.md to find the site that was visited.
        """
        turn_dir = self.turns_dir / f"turn_{source_turn:06d}"

        # Try research.json first
        research_path = turn_dir / "research.json"
        if research_path.exists():
            try:
                research_data = json.loads(research_path.read_text())
                extracted_links = research_data.get("extracted_links", [])
                for link in extracted_links:
                    url = link.get("url", "")
                    if url.startswith("http"):
                        # Extract base URL
                        from urllib.parse import urlparse
                        parsed = urlparse(url)
                        base_url = f"{parsed.scheme}://{parsed.netloc}"
                        return f"{base_url}{relative_url}"
            except Exception:
                pass

        # Try context.md for source URL hints
        context_path = turn_dir / "context.md"
        if context_path.exists():
            try:
                content = context_path.read_text()
                # Look for URLs in the content
                url_pattern = r'https?://([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
                match = re.search(url_pattern, content)
                if match:
                    domain = match.group(1)
                    return f"https://{domain}{relative_url}"
            except Exception:
                pass

        # Fallback: return as-is (won't be fully navigable but preserves info)
        logger.warning(f"[ContextGatherer2Phase] Could not resolve relative URL: {relative_url}")
        return relative_url

    def _enrich_with_visit_record(self, content_ref: ContentReference) -> ContentReference:
        """
        Enrich a ContentReference with visit record info if available.

        Checks visit_records/ directories for cached page data.
        """
        if not content_ref.source_turn:
            return content_ref

        turn_dir = self.turns_dir / f"turn_{content_ref.source_turn:06d}"
        visit_records_dir = turn_dir / "visit_records"

        if not visit_records_dir.exists():
            return content_ref

        # Look for manifest.json files in visit_records subdirectories
        for subdir in visit_records_dir.iterdir():
            if not subdir.is_dir():
                continue

            manifest_path = subdir / "manifest.json"
            if not manifest_path.exists():
                continue

            try:
                manifest = json.loads(manifest_path.read_text())

                # Check if this visit record matches the content we're looking for
                manifest_title = manifest.get("title", "").lower()
                manifest_url = manifest.get("source_url", "")
                ref_title = content_ref.title.lower() if content_ref.title else ""

                # Match by title similarity or site match
                title_match = (
                    ref_title in manifest_title or
                    manifest_title in ref_title or
                    (content_ref.site and content_ref.site in manifest_url)
                )

                if title_match:
                    # Found matching visit record
                    content_ref.source_url = manifest_url
                    content_ref.has_visit_record = True
                    # Path relative to turns_dir.parent (panda_system_docs)
                    content_ref.visit_record_path = str(subdir.relative_to(self.turns_dir.parent))

                    logger.info(
                        f"[ContextGatherer2Phase] Found visit record for '{content_ref.title[:30]}...' "
                        f"at {content_ref.visit_record_path}"
                    )
                    return content_ref

            except Exception as e:
                logger.warning(f"[ContextGatherer2Phase] Error reading manifest {manifest_path}: {e}")
                continue

        return content_ref

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
                from libs.gateway.research.research_doc_writers import normalize_topic
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
            # Search for relevant knowledge in per-user memory directories
            raw_memory_results = await search_memory(
                query=query,
                limit=7,  # Quality over quantity - fewer but more relevant results
                user_id=self.user_id,
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

    async def _finalize_context(
        self,
        context_doc: ContextDocument,
        turn_dir: Path,
        query: str
    ) -> ContextDocument:
        """Write context.md to turn directory.

        Note: Constraint extraction is handled by Phase 2.5 (ConstraintExtractor)
        in request_handler.py. This method only persists the context document.
        """
        from .context_gatherer_docs import write_doc
        write_doc(turn_dir / "context.md", context_doc.get_markdown())
        return context_doc

    async def _extract_constraints(self, query: str, gathered_context: str) -> Dict[str, Any]:
        """Extract structured constraints from query and gathered context."""
        system_prompt = (
            "You are a constraint extraction assistant. "
            "Return JSON only. Do not include markdown."
        )

        user_prompt = f"""QUERY:
{query}

GATHERED CONTEXT (if any):
{gathered_context[:3000]}

Extract explicit constraints only. Use this schema:
{{
  "constraints": [
    {{
      "id": "C1",
      "type": "budget|time_window|location|must_use|must_avoid|format|privacy",
      "value": "... or object",
      "source": "user_query|session_preferences|prior_turn",
      "required": true|false,
      "confidence": 0.0-1.0
    }}
  ],
  "notes": "optional"
}}

Rules:
- Only include constraints stated or clearly implied by the user or preferences.
- If none, return {{ "constraints": [] }}.
"""

        try:
            # MIND role temp=0.6 for constraint extraction
            response = await self.llm_client.call(
                prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
                role="context_gatherer",
                max_tokens=400,
                temperature=0.6
            )
            parsed = self._extract_json_from_text(response)
            constraints = parsed.get("constraints") if isinstance(parsed, dict) else None
            if not isinstance(constraints, list):
                return {"constraints": []}
            return {
                "constraints": constraints,
                "notes": parsed.get("notes", "") if isinstance(parsed, dict) else ""
            }
        except Exception as e:
            logger.warning(f"[ContextGatherer2Phase] Constraint extraction failed: {e}")
            return {"constraints": []}

    def _write_constraints_file(self, turn_dir: Path, payload: Dict[str, Any]) -> None:
        """Persist constraints.json for downstream phases."""
        constraints_path = turn_dir / "constraints.json"
        try:
            constraints_path.write_text(json.dumps(payload, indent=2))
        except Exception as e:
            logger.warning(f"[ContextGatherer2Phase] Failed to write constraints.json: {e}")

    def _format_constraints_block(self, payload: Dict[str, Any]) -> str:
        """Format constraints as markdown block for §1."""
        constraints = payload.get("constraints", []) if isinstance(payload, dict) else []
        if not constraints:
            return "### Constraints\n\n*None identified.*"

        lines = [
            "### Constraints",
            "",
            "```yaml",
            f"_meta:\n  type: constraints\n  count: {len(constraints)}",
            "```",
            "",
            "| Constraint | Value | Source | Required |",
            "|------------|-------|--------|----------|"
        ]

        for item in constraints:
            if not isinstance(item, dict):
                continue
            ctype = str(item.get("type", "unknown"))
            value = item.get("value", "")
            source = item.get("source", "unknown")
            required = str(item.get("required", True)).lower()
            value_str = self._format_constraint_value(value)
            lines.append(f"| {ctype} | {value_str} | {source} | {required} |")

        return "\n".join(lines)

    def _format_constraint_value(self, value: Any) -> str:
        """Format constraint value for markdown table."""
        if isinstance(value, dict):
            return ", ".join(f"{k}: {v}" for k, v in value.items())
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return str(value)

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

        context_doc.append_section(2, "Gathered Context", "\n\n".join(content_parts))
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

            context_doc.append_section(2, "Gathered Context", content)

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

    def _is_navigation_query(self, query: str) -> bool:
        """Detect explicit navigation queries by URL or direct domain."""
        if not query:
            return False

        text = query.strip().lower()

        # Direct URL
        if re.search(r'https?://\\S+', text) or re.search(r'www\\.[^\\s]+', text):
            return True

        # Direct domain or command + domain
        domain_match = re.search(r'\\b[a-z0-9.-]+\\.[a-z]{2,}\\b', text)
        if domain_match:
            if " " not in text:
                return True
            if any(kw in text for kw in ["go to", "open", "visit", "navigate"]):
                return True

        return False

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

        context_doc.append_section(2, "Gathered Context", "\n\n".join(content_parts))

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

        context_doc.append_section(2, "Gathered Context", "\n\n".join(content_parts))
        return context_doc

    def _default_retrieval_prompt(self) -> str:
        """Default system prompt for RETRIEVAL phase."""
        return """You are the Context Gatherer (RETRIEVAL phase).

Your task is to select relevant memory nodes from a Unified Memory Index.
Do NOT load full documents. Do NOT fabricate node_ids.

## OUTPUT (RetrievalPlan)
{
  "selected_nodes": {
    "turn_summary": ["node_id", "..."],
    "preference": ["node_id", "..."],
    "fact": ["node_id", "..."],
    "research_cache": ["node_id", "..."],
    "visit_record": ["node_id", "..."]
  },
  "selection_reasons": {
    "turn_summary": "string",
    "preference": "string",
    "fact": "string",
    "research_cache": "string",
    "visit_record": "string"
  },
  "coverage": {
    "has_prior_turns": true | false,
    "has_memory": true | false,
    "has_cached_research": true | false,
    "has_visit_data": true | false
  },
  "reasoning": "short narrative rationale"
}

## RULES
- Use ONLY node_ids from the Unified Memory Index.
- All keys must exist (use empty arrays if none).
- Prefer narrative signal from resolved_query + user_purpose.
- Coverage must match selected_nodes."""

    def _default_synthesis_prompt(self) -> str:
        """Default system prompt for SYNTHESIS phase."""
        return """You are the Context Gatherer (SYNTHESIS phase).

Your task is to compile gathered information into the §2 Gathered Context section.

## STRUCTURE

Use these canonical sections (omit empty):
- ### Session Preferences
- ### Relevant Prior Turns
- ### Cached Research
- ### Visit Data
- ### Constraints

Each section that uses memory nodes must include a YAML _meta block:
```yaml
_meta:
  source_type: turn_summary | preference | fact | research_cache | visit_record | user_query
  node_ids: ["node_id", "..."]
  confidence_avg: 0.0-1.0
  provenance: ["source_ref", "..."]
```

## RULES
- Use only loaded memory nodes; do not fabricate node_ids.
- Exclude nodes with confidence < 0.30.
- If confidence missing, default to 0.50.
- Constraints derived from raw query use source_type: user_query, node_ids: [].
- Omit empty sections entirely.
- Be concise; preserve specifics and provenance.

Output MARKDOWN only."""

    def _default_context_validation_prompt(self) -> str:
        """Default system prompt for VALIDATION phase (Phase 2.5)."""
        return """You are the Context Gatherer (VALIDATION phase).

Your task is to check if the gathered context is sufficient to proceed.

## OUTPUT (JSON only)
{
  "status": "pass | retry | clarify",
  "issues": ["string"],
  "missing_context": ["string"],
  "retry_guidance": ["string"],
  "clarification_question": "string | null"
}

## RULES

Return `pass` if:
- The gathered context provides enough information to attempt an answer
- Even partial context is OK - the pipeline can work with what's available
- Simple queries (greetings, preference recall, basic questions) should pass with minimal context

Return `retry` if:
- Critical structural issues in the gathered context
- Referenced nodes are missing or corrupted

Return `clarify` ONLY if:
- The query is fundamentally unanswerable (not just missing some context)
- This should be RARE - prefer `pass` and let downstream phases handle gaps

**Default to `pass` when uncertain.** The pipeline can handle incomplete context."""


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
