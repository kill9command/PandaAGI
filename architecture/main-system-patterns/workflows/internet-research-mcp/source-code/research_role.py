"""
orchestrator/research_role.py

Research Role orchestrator - 4th reflection cycle in Pandora's architecture.

Responsibilities:
- Analyze session context and prior research
- Select optimal Phase 1/2 execution strategy
- Execute Standard (1-pass) or Deep (multi-pass) research
- Evaluate satisfaction criteria for Deep mode
- Generate refined queries for iterative passes

Created: 2025-11-17
"""
import asyncio
import json
import logging
import os
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Import dependencies
from orchestrator import research_orchestrator
from orchestrator.session_intelligence_cache import get_intelligence_cache
from orchestrator.research_evaluator import evaluate_research_satisfaction
from orchestrator.research_strategy_selector import analyze_and_select_strategy


class ResearchRole:
    """
    Research Role - Strategic research orchestration with adaptive strategy selection.
    """

    DEFAULT_REQUIRED_INFO_BY_TYPE = {
        "commerce_search": ["name", "location", "price", "credibility"],
        "informational": ["key_topics", "expert_opinions", "recommendations"],
        "comparison": ["pros", "cons", "best_use_cases"]
    }

    def __init__(self):
        # Safety cap to prevent infinite loops (not a hard iteration limit)
        # Deep mode relies on satisfaction criteria, not predetermined pass count
        self.max_passes = 10

    def _extract_sources_count(self, phase2_result: Dict) -> int:
        """
        Extract total sources count from a phase2 result.

        Handles different result structures:
        - intelligent_vendor_search returns: synthesis.total_sources, synthesis.vendors_visited
        - gather_intelligence returns: stats.sources_checked

        Args:
            phase2_result: Result dict from Phase 2 execution

        Returns:
            Number of sources visited/checked
        """
        if not phase2_result:
            return 0

        # Try synthesis.total_sources first (from intelligent_vendor_search)
        synthesis = phase2_result.get("synthesis", {})
        if synthesis.get("total_sources"):
            return synthesis["total_sources"]

        # Try vendors_visited list (from intelligent_vendor_search)
        vendors_visited = synthesis.get("vendors_visited", [])
        if vendors_visited:
            return len(vendors_visited)

        # Try stats.sources_checked (from gather_intelligence)
        stats = phase2_result.get("stats", {})
        if stats.get("sources_checked"):
            return stats["sources_checked"]

        return 0

    async def orchestrate(
        self,
        query: str,
        research_goal: str,
        mode: str,  # "standard" or "deep"
        session_id: str,
        query_type: str = "commerce_search",  # DEPRECATED: Ignored, use research_context.intent
        user_constraints: Dict[str, Any] = None,
        event_emitter: Optional[Any] = None,
        remaining_token_budget: int = 10000,
        force_refresh: bool = False,
        research_context: Dict[str, Any] = None,  # Context from Planner (contains intent)
        turn_number: int = 0  # For research document indexing
    ) -> Dict[str, Any]:
        """
        Main orchestration entry point for Research Role.

        Args:
            query: User's search query
            research_goal: What we're trying to accomplish
            mode: "standard" (1-pass) or "deep" (multi-pass)
            session_id: Session ID for cache and context
            query_type: DEPRECATED - Ignored. Use research_context["intent"] instead.
            user_constraints: User preferences (budget, location, etc.)
            event_emitter: Optional progress event emitter
            remaining_token_budget: Token budget available for research
            force_refresh: If True, bypass cache and force fresh research
            research_context: Context from Planner containing:
                - intent: Intent (navigation, site_search, commerce, informational)
                - entities, subtasks, research_type, phase_hint

        Note: Intent-based routing is the single source of truth.
        See: panda_system_docs/architecture/LLM-ROLES/CONTEXT_DISCIPLINE.md

        Returns:
            {
                "query": str,
                "mode": str,
                "strategy_used": str,
                "passes": int,
                "results": {...},
                "intelligence_cached": bool,
                "satisfaction_evaluations": [...],
                "stats": {...}
            }
        """
        logger.info(f"[ResearchRole] Orchestrating {mode.upper()} mode research: {query[:60]}...")

        user_constraints = user_constraints or {}
        research_context = research_context or {}

        # NEW: Log and process research context from Planner
        entities = research_context.get("entities", [])
        subtasks = research_context.get("subtasks", [])
        research_type = research_context.get("research_type", "general")
        phase_hint = research_context.get("phase_hint", None)

        # NEW: Extract intent for strategy routing
        intent = research_context.get("intent", "informational")
        intent_metadata = research_context.get("intent_metadata", {})

        logger.info(f"[ResearchRole] Intent: {intent}, metadata: {intent_metadata}")

        # INTENT-BASED QUERY MODIFICATION: Use site: modifier for site-specific searches
        # NOTE: We NO LONGER use forced_vendors - Google search handles site-specific filtering
        # ALL web navigation uses GoalDirectedNavigator via intelligent_vendor_search

        if intent == "navigation":
            target_url = intent_metadata.get("target_url")
            goal = intent_metadata.get("goal", "")
            if target_url:
                # Navigation with target_url: DON'T build a search query
                # Let research_orchestrator handle direct navigation to the URL
                logger.info(f"[ResearchRole] Navigation intent with target_url - will use direct navigation")
                logger.info(f"[ResearchRole] Target: {target_url}, Goal: {goal[:50] if goal else 'none'}")
                # Keep query empty so research_orchestrator uses direct navigation path
                query = ""

        if intent == "site_search":
            site_name = intent_metadata.get("site_name")
            search_term = intent_metadata.get("search_term")
            if site_name and search_term:
                # VALIDATION: Check if metadata makes sense for the query
                # If site_name or search_term don't appear in original query, metadata may be stale
                query_lower = query.lower()
                site_lower = site_name.lower()
                term_lower = search_term.lower()

                # Check if the site is mentioned in the query OR if any word from search_term appears
                term_words = [w for w in term_lower.split() if len(w) > 3]
                site_relevant = site_lower in query_lower or any(w in query_lower for w in site_lower.split())
                term_relevant = any(w in query_lower for w in term_words) if term_words else False

                if not site_relevant and not term_relevant:
                    # Metadata doesn't match query - likely stale, fall back to commerce
                    logger.warning(
                        f"[ResearchRole] site_search metadata appears stale: "
                        f"site='{site_name}', term='{search_term}' not found in query='{query[:60]}'. "
                        f"Falling back to commerce intent."
                    )
                    intent = "commerce"
                else:
                    # Normalize site name to domain
                    site_normalized = site_name.lower().strip()
                    if not site_normalized.endswith(".com") and not site_normalized.endswith(".org"):
                        site_normalized = f"{site_normalized}.com"
                    logger.info(f"[ResearchRole] Site search intent - using site:{site_normalized} (term: {search_term[:50]})")
                    # Build query with site constraint
                    query = f"{search_term} site:{site_normalized}"
                    logger.info(f"[ResearchRole] Modified query for site search: {query[:60]}...")

        # CONTENT REFERENCE HANDLING: When we have site + title but no URL
        # Use site-specific search to find the specific content
        content_reference = research_context.get("content_reference")
        if content_reference:
            site = content_reference.get("site")
            title = content_reference.get("title")
            source_url = content_reference.get("source_url")

            logger.info(
                f"[ResearchRole] Content reference detected: "
                f"title='{title[:50] if title else 'none'}...', site={site}, has_url={source_url is not None}"
            )

            # If we have site + title but no URL, build a site-specific search
            if site and title and not source_url:
                # Normalize site to domain format
                site_normalized = site.lower().strip()
                if not site_normalized.startswith("www."):
                    site_normalized = site_normalized.replace("www.", "")

                # Build query: use quoted title for exact match + site constraint
                # This should find the specific thread/article on the site
                query = f'"{title}" site:{site_normalized}'
                logger.info(f"[ResearchRole] Using content_reference for site-specific search: {query[:80]}...")

        if entities or subtasks or research_type != "general":
            logger.info(
                f"[ResearchRole] Research context from Planner: "
                f"entities={len(entities)}, subtasks={len(subtasks)}, "
                f"research_type={research_type}, phase_hint={phase_hint}"
            )
            if entities:
                logger.info(f"[ResearchRole] Entities: {entities[:3]}{'...' if len(entities) > 3 else ''}")

        # Step 1: Retrieve session knowledge (NEW: Knowledge System)
        # Check if caching is disabled via environment variable
        caching_disabled = os.getenv("DISABLE_CACHING", "").lower() in ("true", "1", "yes")
        knowledge_context = None
        has_cached_intel = False

        if caching_disabled:
            logger.info(f"[ResearchRole] CACHING DISABLED - skipping all cache lookups")
        elif not force_refresh:
            try:
                from orchestrator.knowledge_retriever import get_knowledge_retriever
                retriever = get_knowledge_retriever(session_id)
                knowledge_context = await retriever.retrieve_for_query(query)

                if knowledge_context and knowledge_context.phase1_skip_recommended:
                    has_cached_intel = True
                    logger.info(
                        f"[ResearchRole] Knowledge context: {knowledge_context.total_claims} claims, "
                        f"{len(knowledge_context.retailers)} retailers, "
                        f"completeness={knowledge_context.knowledge_completeness:.0%}, "
                        f"skip_phase1={knowledge_context.phase1_skip_recommended}"
                    )
                else:
                    logger.info(f"[ResearchRole] No sufficient knowledge found for query")
            except Exception as e:
                logger.warning(f"[ResearchRole] Knowledge retrieval failed (falling back): {e}")
                # Fall back to old cache system
                cache = get_intelligence_cache(session_id)
                has_cached_intel = cache.has_intelligence(query)
        else:
            logger.info(f"[ResearchRole] FORCE REFRESH - bypassing knowledge cache")

        logger.info(f"[ResearchRole] Session knowledge available: {has_cached_intel}")

        # Step 2: Select execution strategy (Phase 1/2 decision) using LLM Research Planner
        # NEW: Check if Planner provided phase hints or specific entities
        force_skip_phase1 = False
        force_phase1_only = False
        force_phase1_then_phase2 = False

        # Handle phase_hint from Planner (new unified format)
        if phase_hint == "phase2_only":
            force_skip_phase1 = True
            logger.info("[ResearchRole] Phase hint from Planner: PHASE 2 ONLY (skip intelligence gathering)")
        elif phase_hint == "phase1_only":
            force_phase1_only = True
            logger.info("[ResearchRole] Phase hint from Planner: PHASE 1 ONLY (intelligence research)")
        elif phase_hint == "phase1_then_phase2":
            force_phase1_then_phase2 = True
            logger.info("[ResearchRole] Phase hint from Planner: PHASE 1 THEN PHASE 2 (full research)")
        # Legacy hints (backward compatibility)
        elif phase_hint == "skip_phase1":
            force_skip_phase1 = True
            logger.info("[ResearchRole] Phase hint from Planner (legacy): SKIP Phase 1")
        elif phase_hint == "phase1":
            force_phase1_only = True
            logger.info("[ResearchRole] Phase hint from Planner (legacy): PHASE 1 ONLY")
        # Auto-detection based on research_type (fallback if no hint)
        elif not phase_hint:
            if research_type in ["pricing", "availability"] and entities and has_cached_intel:
                # Pricing/availability queries with entities AND cached intel can skip forum discovery
                force_skip_phase1 = True
                logger.info(
                    f"[ResearchRole] Auto-skip Phase 1: research_type={research_type} with {len(entities)} entities + cached intel"
                )
            elif research_type == "technical_specs" and entities:
                # Technical specs NEED Phase 1 (forums, spec sites), NOT vendor search
                force_phase1_only = True
                logger.info(
                    f"[ResearchRole] Force Phase 1 only: research_type={research_type} with {len(entities)} entities"
                )

        strategy = await self._select_strategy(
            query=query,
            mode=mode,
            has_cached_intel=has_cached_intel or force_skip_phase1,  # Treat entities as "intel"
            intent=intent,  # Use intent instead of legacy query_type
            token_budget=remaining_token_budget,
            session_id=session_id
        )

        # Override strategy based on Planner hints
        if force_skip_phase1 and not strategy.get("skip_phase1"):
            logger.info("[ResearchRole] Overriding strategy: forcing skip_phase1=True (phase2_only)")
            strategy["skip_phase1"] = True
            strategy["execute_phase2"] = True
            strategy["phase1_skip_reason"] = f"Planner hint: {phase_hint}"

        if force_phase1_only:
            logger.info("[ResearchRole] Overriding strategy: forcing Phase 1 only (no product search)")
            strategy["skip_phase1"] = False
            strategy["execute_phase2"] = False
            strategy["phase1_only"] = True
            strategy["phase1_only_reason"] = f"Planner hint: {phase_hint or research_type}"

        if force_phase1_then_phase2:
            # Check if LLM selected PHASE1_ONLY with high confidence
            # If so, respect that decision - the LLM determined this is an informational query
            # that doesn't need commerce/product search
            llm_confidence = strategy.get("llm_confidence", 0.0)
            llm_selected_phase1_only = (
                strategy.get("execution") == "phase1_only" and
                not strategy.get("execute_phase2", True)
            )

            if llm_selected_phase1_only and llm_confidence >= 0.8:
                logger.info(
                    f"[ResearchRole] Respecting LLM PHASE1_ONLY decision (confidence={llm_confidence:.2f}) "
                    f"- informational query does not need commerce search"
                )
                # Don't override - keep the LLM's PHASE1_ONLY decision
            else:
                logger.info("[ResearchRole] Overriding strategy: forcing Phase 1 then Phase 2 (full research)")
                strategy["skip_phase1"] = False
                strategy["execute_phase2"] = True
                strategy["phase1_then_phase2_reason"] = f"Planner hint: {phase_hint} - no prior intelligence"
                # CRITICAL: Also update max_sources_phase1 - was 0 for phase2_only strategy
                if strategy.get("max_sources_phase1", 0) == 0:
                    strategy["max_sources_phase1"] = 10
                    logger.info("[ResearchRole] Updated max_sources_phase1 to 10 for override")

        # ARCHITECTURAL RULE: Intent-based Phase 2 decision (UNIFIED - no legacy query_type)
        #
        # Intent values (from _classify_research_intent in unified_flow.py):
        # - "navigation": Go to specific URL, extract content -> Phase 1 only (direct nav)
        # - "site_search": Search within a specific site -> Phase 1 only (direct nav)
        # - "informational": Learn about topic -> Phase 1 only (forum/article research)
        # - "commerce": Buy/find products across vendors -> Phase 1 + Phase 2 (multi-vendor search)
        #
        # Only "commerce" intent triggers Phase 2 (multi-vendor product search).
        # All other intents use Phase 1 only for direct navigation or information gathering.
        #
        # NOTE: The legacy query_type parameter is DEPRECATED and ignored.
        # Intent is the single source of truth for routing decisions.
        # See: panda_system_docs/architecture/LLM-ROLES/CONTEXT_DISCIPLINE.md

        is_commerce = intent == "commerce"

        if is_commerce:
            if not strategy.get("execute_phase2", False):
                logger.info(
                    f"[ResearchRole] Forcing Phase 2 for commerce intent - product search needs fresh results"
                )
                strategy["execute_phase2"] = True
                if strategy.get("max_sources_phase2", 0) == 0:
                    strategy["max_sources_phase2"] = 10
                # Update execution type if needed
                if strategy.get("execution") == "phase1_only":
                    if strategy.get("skip_phase1"):
                        strategy["execution"] = "phase2_only"
                    else:
                        strategy["execution"] = "phase1_then_phase2"
        else:
            # Non-commerce intents: navigation, site_search, informational
            # Force Phase 1 only - no multi-vendor product search
            if strategy.get("execute_phase2", False):
                logger.info(
                    f"[ResearchRole] Disabling Phase 2 for non-commerce intent '{intent}' - using Phase 1 only"
                )
                strategy["execute_phase2"] = False
                strategy["execution"] = "phase1_only"
                strategy["max_sources_phase2"] = 0

        # Inject knowledge context into strategy for downstream use
        if knowledge_context:
            strategy["knowledge_context"] = knowledge_context.to_dict()
            strategy["known_retailers"] = knowledge_context.retailers
            strategy["price_expectations"] = knowledge_context.price_expectations

        # NEW: Inject research_context for query generation
        # ALWAYS include research_context (for intent), entities/subtasks may be empty
        strategy["research_context"] = research_context
        strategy["entities"] = entities
        strategy["subtasks"] = subtasks
        strategy["research_type"] = research_type

        logger.info(
            f"[ResearchRole] Selected strategy: {strategy['execution']} "
            f"(Phase 1: {not strategy['skip_phase1']}, Phase 2: {strategy['execute_phase2']})"
        )

        # Step 3: Execute research based on mode
        # Note: intent is available via strategy["research_context"]["intent"]
        if mode == "standard":
            result = await self._execute_standard(
                query=query,
                research_goal=research_goal,
                strategy=strategy,
                session_id=session_id,
                event_emitter=event_emitter,
                user_constraints=user_constraints,
                turn_number=turn_number
            )
        elif mode == "deep":
            result = await self._execute_deep(
                query=query,
                research_goal=research_goal,
                strategy=strategy,
                session_id=session_id,
                user_constraints=user_constraints,
                event_emitter=event_emitter
            )
        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'standard' or 'deep'")

        logger.info(
            f"[ResearchRole] Complete: {mode.upper()} mode, {result['passes']} pass(es), "
            f"{result['stats'].get('total_sources', 0)} sources"
        )

        # Step 4: Store knowledge from research results (NEW: Knowledge System)
        try:
            from orchestrator.knowledge_extractor import get_knowledge_extractor
            extractor = get_knowledge_extractor(session_id)
            topic = await extractor.process_research_completion(
                query=query,
                research_result=result.get("results", result),
            )
            if topic:
                result["knowledge_topic"] = topic.topic_name
                result["knowledge_topic_id"] = topic.topic_id
                logger.info(f"[ResearchRole] Stored knowledge under topic: {topic.topic_name}")
        except Exception as e:
            logger.warning(f"[ResearchRole] Knowledge extraction failed: {e}")

        return result

    async def _select_strategy(
        self,
        query: str,
        mode: str,
        has_cached_intel: bool,
        intent: str,  # UNIFIED: Use intent instead of legacy query_type
        token_budget: int,
        session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        Select which research phases to execute using LLM Phase Selector.

        IMPORTANT: Mode vs Phases distinction:
        - `mode` parameter (from Gateway): Controls PASS COUNT
          - "standard" = single pass (run phases once)
          - "deep" = multi-pass (iterate until goals complete)

        - `phases` (from LLM): Controls WHICH PHASES to run
          - "phase1_only" = just gather intelligence (informational/navigation queries)
          - "phase2_only" = skip Phase 1, run Phase 2 (use cached intel)
          - "phase1_and_phase2" = run both phases (commerce queries)

        Args:
            intent: Intent from _classify_research_intent (navigation, site_search, commerce, informational)

        Returns:
            {
                "execution": "phase1_only" | "phase2_only" | "phase1_then_phase2",
                "skip_phase1": bool,
                "execute_phase2": bool,
                "reason": str,
                "max_sources_phase1": int,
                "max_sources_phase2": int,
                "phases": str
            }
        """
        logger.info(f"[ResearchRole] LLM Phase Selector deciding phases for: '{query[:50]}...' (intent={intent})")

        try:
            # Use LLM-powered phase selector
            llm_decision = await analyze_and_select_strategy(
                query=query,
                session_id=session_id,
                cached_intelligence_available=has_cached_intel,
                user_preferences={"intent": intent}  # Pass intent instead of query_type
            )

            phases = llm_decision.get("phases", "phase1_and_phase2")
            config = llm_decision.get("config", {})
            reason = llm_decision.get("reason", "LLM phase selection")

            logger.info(
                f"[ResearchRole] LLM selected phases: {phases.upper()} "
                f"(confidence: {llm_decision.get('confidence', 0.0):.2f}) - {reason}"
            )

            # Build execution config from phases
            if phases == "phase1_only":
                return {
                    "execution": "phase1_only",
                    "skip_phase1": False,
                    "execute_phase2": False,
                    "reason": reason,
                    "max_sources_phase1": config.get("max_sources_phase1", 10),
                    "max_sources_phase2": 0,
                    "phases": phases,
                    "llm_confidence": llm_decision.get("confidence", 0.0)
                }
            elif phases == "phase2_only":
                return {
                    "execution": "phase2_only",
                    "skip_phase1": True,
                    "execute_phase2": True,
                    "reason": reason,
                    "max_sources_phase1": 0,
                    "max_sources_phase2": config.get("max_sources_phase2", 10),
                    "phases": phases,
                    "llm_confidence": llm_decision.get("confidence", 0.0)
                }
            else:  # phase1_and_phase2
                return {
                    "execution": "phase1_then_phase2",
                    "skip_phase1": False,
                    "execute_phase2": True,
                    "reason": reason,
                    "max_sources_phase1": config.get("max_sources_phase1", 10),
                    "max_sources_phase2": config.get("max_sources_phase2", 12),
                    "phases": phases,
                    "llm_confidence": llm_decision.get("confidence", 0.0)
                }

        except Exception as e:
            logger.warning(f"[ResearchRole] LLM phase selection failed: {e}, using fallback")
            return self._fallback_strategy_selection(query, mode, has_cached_intel, intent)

    def _fallback_strategy_selection(
        self,
        query: str,
        mode: str,
        has_cached_intel: bool,
        intent: str  # UNIFIED: Use intent instead of legacy query_type
    ) -> Dict[str, Any]:
        """
        Rule-based fallback if LLM phase selection fails.

        Logic (based on intent):
        - navigation/site_search/informational → phase1_only (no multi-vendor search)
        - commerce + cached intel → phase2_only
        - commerce + no cached intel → phase1_and_phase2
        """
        # Non-commerce intents only need Phase 1 (direct navigation/info gathering)
        if intent in ("navigation", "site_search", "informational"):
            return {
                "execution": "phase1_only",
                "skip_phase1": False,
                "execute_phase2": False,
                "reason": f"Non-commerce intent '{intent}' - Phase 1 only (fallback rule)",
                "max_sources_phase1": 10,
                "max_sources_phase2": 0,
                "phases": "phase1_only",
                "llm_confidence": 0.0
            }
        elif has_cached_intel:
            # Have cached intel → skip Phase 1
            return {
                "execution": "phase2_only",
                "skip_phase1": True,
                "execute_phase2": True,
                "reason": "Cached intelligence available (fallback rule)",
                "max_sources_phase1": 0,
                "max_sources_phase2": 10,
                "phases": "phase2_only",
                "llm_confidence": 0.0
            }
        else:
            # No cached intel → need both phases
            return {
                "execution": "phase1_then_phase2",
                "skip_phase1": False,
                "execute_phase2": True,
                "reason": "No cached intelligence (fallback rule)",
                "max_sources_phase1": 10,
                "max_sources_phase2": 12,
                "phases": "phase1_and_phase2",
                "llm_confidence": 0.0
            }

    async def _execute_standard(
        self,
        query: str,
        research_goal: str,
        strategy: Dict,
        session_id: str,
        event_emitter: Optional[Any],
        user_constraints: Dict,
        turn_number: int = 0
    ) -> Dict[str, Any]:
        """Execute Standard mode (1-pass) research.

        Note: Intent is retrieved from strategy["research_context"]["intent"].
        The legacy query_type parameter has been removed.
        """
        # Get intent from research_context (already stored in strategy by orchestrate())
        research_context = strategy.get("research_context", {})
        intent = research_context.get("intent", "informational")
        logger.info(f"[ResearchRole:STANDARD] Starting single-pass research")

        intelligence = None
        intelligence_cached_this_pass = False
        phase1_sources = []  # Raw sources for document generation

        # Create Web Vision session ID for this research session
        web_vision_session_id = f"{session_id}_research"

        # Phase 1: Gather intelligence (if needed)
        if not strategy["skip_phase1"]:
            logger.info(f"[ResearchRole:STANDARD] Phase 1: Gathering intelligence")
            # NEW: Pass research_context for pre-planned queries
            research_context = strategy.get("research_context")
            phase1_result = await research_orchestrator.gather_intelligence(
                query=query,
                research_goal=research_goal,
                max_sources=strategy["max_sources_phase1"],
                session_id=session_id,
                web_vision_session_id=web_vision_session_id,  # Pass Web Vision session
                event_emitter=event_emitter,
                research_context=research_context  # Pass Planner context with subtasks
            )
            intelligence = phase1_result["intelligence"]
            phase1_sources = phase1_result.get("sources", [])  # Capture raw sources

            # Cache intelligence for future queries (skip if caching disabled)
            caching_disabled = os.getenv("DISABLE_CACHING", "").lower() in ("true", "1", "yes")
            if not caching_disabled:
                cache = get_intelligence_cache(session_id)
                cache.save_intelligence(
                    query=query,
                    intelligence=intelligence,
                    sources=phase1_sources,
                    stats=phase1_result.get("stats", {})
                )
                intelligence_cached_this_pass = True
                logger.info(f"[ResearchRole:STANDARD] Phase 1 complete, intelligence cached ({len(phase1_sources)} sources)")

                # NEW: Index research in ResearchIndexDB for context gatherer retrieval
                await self._index_phase1_research(
                    query=query,
                    intelligence=intelligence,
                    sources=phase1_sources,
                    stats=phase1_result.get("stats", {}),
                    session_id=session_id,
                    turn_number=turn_number,
                    intent=intent  # Use intent instead of legacy query_type
                )
            else:
                logger.info(f"[ResearchRole:STANDARD] Phase 1 complete, caching DISABLED ({len(phase1_sources)} sources)")
        else:
            # Load cached intelligence (skip if caching disabled)
            caching_disabled = os.getenv("DISABLE_CACHING", "").lower() in ("true", "1", "yes")
            if not caching_disabled:
                cache = get_intelligence_cache(session_id)
                intelligence = cache.load_intelligence(query) or {}
                logger.info(f"[ResearchRole:STANDARD] Using cached intelligence")
            else:
                intelligence = {}
                logger.info(f"[ResearchRole:STANDARD] Skipping cached intelligence (caching DISABLED)")

        # Inject knowledge-based retailers into intelligence (NEW: Knowledge System)
        if strategy.get("known_retailers"):
            if not intelligence:
                intelligence = {}
            knowledge_retailers = strategy["known_retailers"]

            # Inject into retailers_mentioned (list format - backwards compatible)
            existing_retailers = intelligence.get("retailers_mentioned", [])
            merged_retailers = list(set(existing_retailers + knowledge_retailers))
            intelligence["retailers_mentioned"] = merged_retailers

            # ALSO inject into retailers (dict format - used by intelligent_vendor_search)
            existing_retailers_dict = intelligence.get("retailers", {})
            for retailer in knowledge_retailers:
                retailer_key = retailer.lower().strip()
                if retailer_key and retailer_key not in existing_retailers_dict:
                    existing_retailers_dict[retailer_key] = {
                        "relevance_score": 0.8,  # Good relevance for known retailers
                        "context": "From knowledge system / cached intelligence",
                        "mentioned_for": [],
                        "include_in_search": True
                    }
            intelligence["retailers"] = existing_retailers_dict

            logger.info(f"[ResearchRole:STANDARD] Injected {len(knowledge_retailers)} retailers from knowledge: {knowledge_retailers}")

        # ════════════════════════════════════════════════════════════════════════
        # NEW: Generate requirements reasoning (LLM-driven product filtering)
        #
        # This step uses an LLM to reason about what the user actually needs
        # based on the query and Phase 1 intelligence. It replaces hardcoded
        # ProductRequirements logic with flexible LLM reasoning.
        #
        # Flow:
        #   1. Input: query + intelligence (from Phase 1 or cache)
        #   2. LLM reasons about: validity criteria, disqualifiers, search optimization
        #   3. Output: reasoning_document + optimized_query
        #   4. Phase 2 uses optimized_query for better search results
        #   5. Viability filter uses reasoning_document to reject wrong products
        # ════════════════════════════════════════════════════════════════════════
        requirements_reasoning = None
        optimized_query = query  # Default to original query

        # Only generate reasoning if Phase 2 will run AND it's a commerce intent
        # (no point reasoning about product filtering for informational/navigation queries)
        is_commerce = intent == "commerce"

        if strategy["execute_phase2"] and is_commerce:
            logger.info(f"[ResearchRole:STANDARD] Generating requirements reasoning (LLM-driven)")
            try:
                requirements_reasoning = await self._generate_requirements_reasoning(
                    query=query,
                    intelligence=intelligence or {},
                    user_constraints=user_constraints,
                    session_id=session_id
                )
                optimized_query = requirements_reasoning.get("optimized_query", query)
                logger.info(f"[ResearchRole:STANDARD] Requirements reasoning complete")
                logger.info(f"[ResearchRole:STANDARD] Optimized query: '{optimized_query}'")

                # Log key disqualifiers for debugging
                parsed = requirements_reasoning.get("parsed", {})
                disqualifiers = parsed.get("disqualifiers", {})
                if disqualifiers.get("wrong_category"):
                    logger.info(f"[ResearchRole:STANDARD] Will reject: {disqualifiers['wrong_category']}")
            except Exception as e:
                logger.warning(f"[ResearchRole:STANDARD] Requirements reasoning failed: {e}, using original query")
                requirements_reasoning = None
                optimized_query = query

        # Phase 2: Search products/info (if needed)
        phase2_result = None
        if strategy["execute_phase2"]:
            logger.info(f"[ResearchRole:STANDARD] Phase 2: Searching products")

            # is_commerce is defined above (before requirements reasoning) based on intent
            # Intent values (from _classify_research_intent):
            # - "commerce" = transactional (buy, find products) -> use intelligent vendor search
            # - "navigation/site_search/informational" = non-commerce -> use standard search

            if is_commerce:
                logger.info(f"[ResearchRole:STANDARD] Using intelligent vendor search (commerce query detected)")
                # Use intelligent multi-vendor search:
                # 1. Google search for shopping query (uses optimized_query from reasoning)
                # 2. LLM selects vendors from search results (informed by Phase 1 intelligence)
                # 3. Visits vendor URLs directly
                # 4. Extracts products with hybrid vision pipeline
                # 5. Filters for viability using requirements_reasoning (LLM-driven)
                #
                # Domain hallucination fix applied in llm_candidate_filter.py:
                # - Always uses actual URL domain, not LLM's claimed domain
                min_vendors = int(os.getenv("MIN_SUCCESSFUL_VENDORS", "3"))

                # Extract research_context from strategy for entity-aware queries
                research_context = strategy.get("research_context")

                phase2_result = await research_orchestrator.intelligent_vendor_search(
                    query=optimized_query,  # Use optimized query from requirements reasoning (includes site: modifier if applicable)
                    intelligence=intelligence or {},
                    max_vendors=min_vendors,
                    products_per_vendor=4,
                    session_id=session_id,
                    web_vision_session_id=web_vision_session_id,
                    event_emitter=event_emitter,
                    research_context=research_context,
                    requirements_reasoning=requirements_reasoning,  # LLM reasoning for viability filter
                    original_query=query  # CONTEXT DISCIPLINE: LLM reads user priorities from this
                )
            else:
                # FALLBACK: Use standard Phase 2 for non-commerce queries
                logger.info(f"[ResearchRole:STANDARD] Using standard Phase 2 (non-commerce query)")
                phase2_result = await research_orchestrator.search_products(
                    query=query,
                    research_goal=research_goal,
                    intelligence=intelligence,
                    max_sources=strategy["max_sources_phase2"],
                    session_id=session_id,
                    web_vision_session_id=web_vision_session_id,
                    event_emitter=event_emitter
                )

            logger.info(f"[ResearchRole:STANDARD] Phase 2 complete")

        # Build results using helper to extract sources count
        # Include Phase 1 sources when Phase 2 is skipped
        if phase2_result:
            total_sources = self._extract_sources_count(phase2_result)
        else:
            total_sources = len(phase1_sources)

        # When Phase 2 is skipped (phase1_only), build findings from Phase 1 intelligence AND sources
        results = phase2_result
        if not results and (intelligence or phase1_sources):
            # Extract findings from Phase 1 intelligence AND raw sources for downstream use
            phase1_findings = []

            # FIRST: Extract from raw sources (these have the actual forum content)
            # Sources have "summary" and "text_content" with real spec info
            for source in phase1_sources[:5]:
                summary = source.get("summary", "") or source.get("text_content", "")
                if summary and len(summary) > 50:
                    # Use higher limit for list content (topics, threads, items)
                    # to avoid truncating the last few items
                    max_statement_len = 1500
                    finding = {
                        "type": "source_summary",
                        "statement": summary[:max_statement_len] + "..." if len(summary) > max_statement_len else summary,
                        "confidence": source.get("source_reliability", 0.80),
                        "source": source.get("url", "phase1_source"),
                        "source_type": source.get("source_type", "forum")
                    }
                    # Include extracted links from page (for forum threads, articles, etc.)
                    if source.get("extracted_links"):
                        finding["extracted_links"] = source.get("extracted_links")
                    phase1_findings.append(finding)

            # SECOND: Extract from synthesized intelligence (shopping-focused fields)
            if isinstance(intelligence, dict):
                # Intelligence synthesis returns shopping-focused fields
                # Also try answer/key_findings for synthesis-based research
                answer = intelligence.get("answer", "")
                key_findings_list = intelligence.get("key_findings", [])

                # Add answer if present
                if answer and answer != "No information found":
                    phase1_findings.append({
                        "type": "intelligence_summary",
                        "statement": answer,
                        "confidence": 0.85,
                        "source": "phase1_intelligence"
                    })

                # Add key findings
                for finding in key_findings_list[:5]:
                    if isinstance(finding, str) and finding.strip():
                        phase1_findings.append({
                            "type": "fact",
                            "statement": finding,
                            "confidence": 0.80,
                            "source": "phase1_intelligence"
                        })

                # Also extract user_insights (often contains spec info)
                for insight in intelligence.get("user_insights", [])[:3]:
                    if isinstance(insight, str) and insight.strip():
                        phase1_findings.append({
                            "type": "user_insight",
                            "statement": insight,
                            "confidence": 0.75,
                            "source": "phase1_intelligence"
                        })

                # Extract specs_discovered if present
                specs = intelligence.get("specs_discovered", {})
                for spec_name, spec_data in specs.items():
                    if isinstance(spec_data, dict):
                        value = spec_data.get("value", "")
                        conf = spec_data.get("confidence", 0.7)
                        if value:
                            phase1_findings.append({
                                "type": "spec",
                                "statement": f"{spec_name}: {value}",
                                "confidence": conf,
                                "source": "phase1_intelligence"
                            })

            results = {
                "intelligence": intelligence,
                "findings": phase1_findings,
                "sources_visited": len(phase1_sources),
                "phase1_only": True
            }

            logger.info(f"[ResearchRole:STANDARD] Built {len(phase1_findings)} findings from Phase 1 ({len(phase1_sources)} sources)")

        return {
            "query": query,
            "research_goal": research_goal,
            "mode": "standard",
            "strategy_used": strategy["execution"],
            "passes": 1,
            "results": results or {"intelligence": intelligence},
            "intelligence": intelligence,  # Include for document generation
            "phase1_sources": phase1_sources,  # Raw sources for document generation
            "intelligence_cached": intelligence_cached_this_pass,
            "satisfaction_evaluations": [],  # None for Standard mode
            "stats": {
                "strategy": strategy["execution"],
                "passes_executed": 1,
                "total_sources": total_sources,
                "intelligence_used": intelligence is not None,
                "phase1_only": not strategy.get("execute_phase2", True)
            }
        }

    async def _generate_requirements_reasoning(
        self,
        query: str,
        intelligence: Dict[str, Any],
        user_constraints: Dict[str, Any],
        session_id: str
    ) -> Dict[str, Any]:
        """
        Generate LLM-reasoned requirements from query and Phase 1 intelligence.

        This replaces hardcoded ProductRequirements logic with LLM reasoning.
        The LLM determines:
        - What the user actually wants (validity criteria)
        - What would disqualify a product (disqualifiers)
        - Optimized search query (search_optimization)

        Args:
            query: User's search query
            intelligence: Phase 1 intelligence (may be empty if skipped/cache miss)
            user_constraints: User preferences (budget, etc.)
            session_id: Session ID for context

        Returns:
            {
                "reasoning_document": str,  # Full LLM response
                "parsed": dict,  # Parsed YAML structure
                "optimized_query": str  # Query optimized for product search
            }
        """
        import httpx
        import yaml

        logger.info(f"[ResearchRole] Generating requirements reasoning for: {query[:60]}...")

        # Load prompt template
        prompt_path = Path("apps/prompts/phase1_intelligence/requirements_reasoning.md")
        try:
            prompt_template = prompt_path.read_text()
        except FileNotFoundError:
            logger.error(f"[ResearchRole] Requirements reasoning prompt not found: {prompt_path}")
            return {
                "reasoning_document": "",
                "parsed": {},
                "optimized_query": query
            }

        # Build research summary from Phase 1 intelligence
        research_summary = self._format_intelligence_for_reasoning(intelligence)

        # Build user context
        context = self._format_user_context(user_constraints, session_id)

        # Fill template placeholders
        prompt = prompt_template.replace("{{query}}", query)
        prompt = prompt.replace("{{context}}", context)
        prompt = prompt.replace("{{research_summary}}", research_summary)

        # Call LLM with retry logic
        import asyncio

        solver_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        solver_model_id = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        solver_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

        max_retries = 2
        last_error = None

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        solver_url,
                        json={
                            "model": solver_model_id,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 1200,  # Increased to match recipe budget
                            "temperature": 0.2
                        },
                        headers={"Authorization": f"Bearer {solver_api_key}"}
                    )
                    response.raise_for_status()

                    reasoning_document = response.json()["choices"][0]["message"]["content"]

                    # Parse YAML from response
                    parsed = self._parse_reasoning_yaml(reasoning_document)

                    # Extract optimized query
                    optimized_query = parsed.get("search_optimization", {}).get("primary_query", query)

                    logger.info(f"[ResearchRole] Requirements reasoning complete. Optimized query: {optimized_query[:60]}...")

                    return {
                        "reasoning_document": reasoning_document,
                        "parsed": parsed,
                        "optimized_query": optimized_query
                    }

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # 2s, 4s backoff
                    logger.warning(f"[ResearchRole] Requirements reasoning timeout, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"[ResearchRole] Requirements reasoning failed after {max_retries} attempts: {e}")

            except Exception as e:
                last_error = e
                logger.error(f"[ResearchRole] Requirements reasoning LLM failed: {e}")
                break  # Don't retry on non-timeout errors

        # Return fallback - use original query, no reasoning
        return {
            "reasoning_document": "",
            "parsed": {},
            "optimized_query": query
        }

    def _format_intelligence_for_reasoning(self, intelligence: Dict[str, Any]) -> str:
        """Format Phase 1 intelligence for the requirements reasoning prompt."""
        if not intelligence or not any(intelligence.values()):
            return """No research findings available.

Reason based on the query alone. Use your knowledge to determine:
- What type of product the user likely wants
- Common disqualifiers for this product category
- Reasonable price expectations
- Appropriate search terms"""

        lines = []

        # Add source quality summary if available
        sources = intelligence.get("sources", [])
        if sources:
            lines.append("**Sources consulted:**")
            for src in sources[:5]:
                url = src.get("url", src.get("source_url", "unknown"))
                source_type = src.get("source_type", "general")
                reliability = src.get("source_reliability", 0.5)
                # Truncate URL for readability
                url_short = url[:60] + "..." if len(url) > 60 else url
                lines.append(f"- [{source_type}, reliability={reliability:.2f}] {url_short}")
            lines.append("")
            lines.append("**Note:** Evaluate this intelligence critically. Some sources may be outdated or discuss products that don't match the query requirements.")
            lines.append("")

        if intelligence.get("specs_discovered"):
            lines.append("**Specs discovered:**")
            for k, v in intelligence["specs_discovered"].items():
                if isinstance(v, dict):
                    lines.append(f"- {k}: {v.get('value', v)}")
                else:
                    lines.append(f"- {k}: {v}")

        if intelligence.get("price_range"):
            pr = intelligence["price_range"]
            min_price = pr.get('min', '?')
            max_price = pr.get('max', '?')
            lines.append(f"**Price range:** ${min_price} - ${max_price}")

        if intelligence.get("key_findings"):
            lines.append("**Key findings:**")
            for finding in intelligence["key_findings"][:5]:
                if isinstance(finding, str):
                    lines.append(f"- {finding}")
                elif isinstance(finding, dict):
                    lines.append(f"- {finding.get('statement', finding.get('content', str(finding)))}")

        if intelligence.get("forum_recommendations"):
            lines.append("**Community recommendations:**")
            for rec in intelligence["forum_recommendations"][:5]:
                if isinstance(rec, dict):
                    content = rec.get('content', rec.get('recommendation', ''))
                    lines.append(f"- {content[:200]}")
                elif isinstance(rec, str):
                    lines.append(f"- {rec[:200]}")

        if intelligence.get("retailers") or intelligence.get("retailers_mentioned"):
            # Handle both rich retailer info and simple list
            retailers_data = intelligence.get("retailers", {})
            if retailers_data and isinstance(retailers_data, dict):
                lines.append("**Retailers mentioned:**")
                for name, info in list(retailers_data.items())[:5]:
                    if isinstance(info, dict):
                        score = info.get("relevance_score", 0.5)
                        reasons = info.get("mentioned_for", [])
                        reason_str = f" ({', '.join(reasons[:2])})" if reasons else ""
                        lines.append(f"- {name}: relevance={score:.2f}{reason_str}")
                    else:
                        lines.append(f"- {name}")
            else:
                # Fall back to simple list
                retailers = intelligence.get("retailers_mentioned", [])[:5]
                if retailers:
                    lines.append(f"**Retailers mentioned:** {', '.join(retailers)}")

        if intelligence.get("user_insights"):
            lines.append("**User tips/warnings:**")
            for tip in intelligence["user_insights"][:3]:
                lines.append(f"- {tip}")

        return "\n".join(lines) if lines else "No specific research findings."

    def _format_user_context(self, user_constraints: Dict[str, Any], session_id: str) -> str:
        """Format user context for the requirements reasoning prompt."""
        lines = []

        if user_constraints:
            if user_constraints.get("budget"):
                budget = user_constraints["budget"]
                if isinstance(budget, dict):
                    lines.append(f"- Budget: ${budget.get('min', 0)} - ${budget.get('max', '?')}")
                else:
                    lines.append(f"- Budget: {budget}")

            if user_constraints.get("location"):
                lines.append(f"- Location: {user_constraints['location']}")

            if user_constraints.get("preferences"):
                for key, value in user_constraints["preferences"].items():
                    lines.append(f"- {key}: {value}")

        if not lines:
            lines.append("No specific user constraints provided.")

        return "\n".join(lines)

    def _parse_reasoning_yaml(self, response: str) -> Dict[str, Any]:
        """Parse YAML from LLM response, handling code blocks and errors."""
        import yaml

        # Extract YAML from markdown code block if present
        content = response
        if "```yaml" in content:
            content = content.split("```yaml")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        try:
            return yaml.safe_load(content) or {}
        except yaml.YAMLError as e:
            logger.warning(f"[ResearchRole] YAML parse error: {e}")
            # Try to extract key fields manually
            parsed = {}

            # Look for primary_query
            import re
            query_match = re.search(r'primary_query:\s*["\']?([^"\'\n]+)', response)
            if query_match:
                parsed["search_optimization"] = {"primary_query": query_match.group(1).strip()}

            # Look for must_be
            must_be_match = re.search(r'must_be:\s*["\']?([^"\'\n]+)', response)
            if must_be_match:
                parsed["validity_criteria"] = {"must_be": must_be_match.group(1).strip()}

            return parsed

    async def _execute_deep(
        self,
        query: str,
        research_goal: str,
        strategy: Dict,
        session_id: str,
        user_constraints: Dict,
        event_emitter: Optional[Any]
    ) -> Dict[str, Any]:
        """Execute Deep mode (multi-pass) research with satisfaction evaluation.

        Note: Intent is retrieved from strategy["research_context"]["intent"].
        The legacy query_type parameter has been removed.
        """
        # Get intent from research_context
        research_context = strategy.get("research_context", {})
        intent = research_context.get("intent", "informational")

        logger.info(
            f"[ResearchRole:DEEP] Starting multi-pass research "
            f"(unlimited iterations until satisfied, safety cap: {self.max_passes})"
        )

        passes_results = []
        satisfaction_evaluations = []
        intelligence = None
        intelligence_cached_this_pass = False

        for pass_num in range(1, self.max_passes + 1):
            logger.info(f"[ResearchRole:DEEP] === PASS {pass_num}/{self.max_passes} ===")

            # Execute pass
            pass_result = await self._execute_pass(
                pass_num=pass_num,
                query=query,
                research_goal=research_goal,
                strategy=strategy,
                session_id=session_id,
                intent=intent,  # Use intent instead of legacy query_type
                event_emitter=event_emitter,
                intelligence=intelligence,  # Carry forward from Pass 1
                previous_evaluation=satisfaction_evaluations[-1] if satisfaction_evaluations else None
            )

            passes_results.append(pass_result)

            # Cache intelligence from Pass 1
            if pass_num == 1 and not strategy["skip_phase1"]:
                intelligence = pass_result.get("phase1_results", {}).get("intelligence")
                if intelligence:
                    cache = get_intelligence_cache(session_id)
                    cache.save_intelligence(query, intelligence, [], {})
                    intelligence_cached_this_pass = True
                    logger.info(f"[ResearchRole:DEEP] Pass 1 intelligence cached")

            # Evaluate satisfaction
            # Map intent to required info type for satisfaction evaluation
            intent_to_info_type = {
                "commerce": "commerce_search",
                "navigation": "informational",
                "site_search": "informational",
                "informational": "informational"
            }
            info_type = intent_to_info_type.get(intent, "informational")
            required_info = self.DEFAULT_REQUIRED_INFO_BY_TYPE.get(info_type, ["name", "info"])
            evaluation = await evaluate_research_satisfaction(
                pass_number=pass_num,
                pass_results=pass_result,
                required_info=required_info,
                intent=intent  # Use intent instead of legacy query_type
            )
            satisfaction_evaluations.append(evaluation)

            logger.info(
                f"[ResearchRole:DEEP] Pass {pass_num} Evaluation: {evaluation['decision']} "
                f"(Coverage: {evaluation['criteria']['coverage']['met']}, "
                f"Quality: {evaluation['criteria']['quality']['met']}, "
                f"Completeness: {evaluation['criteria']['completeness']['met']}, "
                f"Contradictions: {evaluation['criteria']['contradictions']['met']})"
            )

            # Check if we should continue
            if evaluation["decision"] == "COMPLETE":
                logger.info(f"[ResearchRole:DEEP] Research complete after {pass_num} pass(es)")
                break

            # Check if we've hit safety limit
            if pass_num >= self.max_passes:
                logger.warning(
                    f"[ResearchRole:DEEP] Reached safety cap ({self.max_passes} passes) - "
                    f"stopping despite incomplete criteria"
                )
                break

            # Generate refined queries for next pass using LLM Research Planner
            logger.info(f"[ResearchRole:DEEP] LLM generating refined research goals for Pass {pass_num + 1}")
            strategy = await self._refine_strategy(
                strategy=strategy,
                evaluation=evaluation,
                query=query,
                session_id=session_id
            )

        # Aggregate results
        final_pass = passes_results[-1]
        final_evaluation = satisfaction_evaluations[-1]

        return {
            "query": query,
            "research_goal": research_goal,
            "mode": "deep",
            "strategy_used": strategy["execution"],
            "passes": len(passes_results),
            "results": final_pass.get("phase2_results", {}),
            "intelligence_cached": intelligence_cached_this_pass,
            "satisfaction_evaluations": satisfaction_evaluations,
            "passes_results": passes_results,
            "final_decision": final_evaluation["decision"],
            "stats": {
                "strategy": strategy["execution"],
                "passes_executed": len(passes_results),
                "total_sources": sum(
                    self._extract_sources_count(p.get("phase2_results", {}))
                    for p in passes_results
                ),
                "intelligence_used": intelligence is not None,
                "all_criteria_met": final_evaluation["all_met"]
            }
        }

    async def _execute_pass(
        self,
        pass_num: int,
        query: str,
        research_goal: str,
        strategy: Dict,
        session_id: str,
        intent: str,  # Use intent instead of legacy query_type
        event_emitter: Optional[Any],
        intelligence: Optional[Dict],
        previous_evaluation: Optional[Dict]
    ) -> Dict[str, Any]:
        """Execute a single research pass.

        Note: Uses intent instead of legacy query_type for routing decisions.
        """
        # Create Web Vision session ID for this research pass
        web_vision_session_id = f"{session_id}_research_pass{pass_num}"

        pass_result = {
            "pass_number": pass_num,
            "phase1_results": {},
            "phase2_results": {},
            "stats": {}
        }

        # Phase 1 (only on first pass unless strategy changes)
        if pass_num == 1 and not strategy["skip_phase1"]:
            phase1_result = await research_orchestrator.gather_intelligence(
                query=query,
                research_goal=research_goal,
                max_sources=strategy["max_sources_phase1"],
                session_id=session_id,
                web_vision_session_id=web_vision_session_id,  # Pass Web Vision session
                event_emitter=event_emitter
            )
            pass_result["phase1_results"] = phase1_result
            intelligence = phase1_result["intelligence"]

        # Phase 2
        if strategy["execute_phase2"]:
            # Only commerce intent triggers retailer comparison search
            is_commerce = intent == "commerce"

            if is_commerce:
                logger.info(f"[ResearchRole:DEEP] Phase 2 Pass {pass_num}: Using retailer comparison search")
                phase2_result = await research_orchestrator.search_products_with_comparison(
                    query=query,
                    intelligence=intelligence or {},
                    max_retailers=3,
                    max_products=6,
                    session_id=session_id,
                    web_vision_session_id=web_vision_session_id,
                    event_emitter=event_emitter
                )
            else:
                # Non-commerce: Use standard search for informational queries
                logger.info(f"[ResearchRole:DEEP] Phase 2 Pass {pass_num}: Using standard search (non-commerce)")
                phase2_result = await research_orchestrator.search_products(
                    query=query,
                    research_goal=research_goal,
                    intelligence=intelligence,
                    max_sources=strategy["max_sources_phase2"],
                    session_id=session_id,
                    web_vision_session_id=web_vision_session_id,
                    event_emitter=event_emitter
                )

            pass_result["phase2_results"] = phase2_result

        return pass_result

    async def _refine_strategy(
        self,
        strategy: Dict,
        evaluation: Dict,
        query: str,
        session_id: str
    ) -> Dict:
        """
        LLM-driven strategy refinement for deep search.

        Generates a research to-do list with specific goals based on what's missing.
        This is the key improvement over simple source count increases.
        """
        logger.info("[ResearchRole] LLM generating refined research goals...")

        try:
            # Generate research goals using LLM
            research_goals = await self._generate_research_goals(
                query=query,
                evaluation=evaluation,
                strategy=strategy,
                session_id=session_id
            )

            # Update strategy with LLM-generated goals
            strategy["research_goals"] = research_goals
            strategy["refined_queries"] = research_goals.get("queries", [])

            # Adjust source counts based on gap analysis
            if not evaluation["criteria"]["coverage"]["met"]:
                strategy["max_sources_phase2"] = min(strategy["max_sources_phase2"] + 3, 20)

            logger.info(
                f"[ResearchRole] Generated {len(research_goals.get('goals', []))} research goals: "
                f"{[g.get('goal', 'unknown') for g in research_goals.get('goals', [])]}"
            )

            return strategy

        except Exception as e:
            logger.warning(f"[ResearchRole] LLM goal generation failed: {e}, using simple refinement")
            # Fallback to simple increase
            if not evaluation["criteria"]["coverage"]["met"]:
                strategy["max_sources_phase2"] = min(strategy["max_sources_phase2"] + 3, 20)
            return strategy

    async def _generate_research_goals(
        self,
        query: str,
        evaluation: Dict,
        strategy: Dict,
        session_id: str
    ) -> Dict[str, Any]:
        """
        LLM generates specific research goals (to-do list) for deep search continuation.

        This is the "research to-do list" that drives iterative deep search.
        """
        import httpx

        # Build context from evaluation
        missing_info = evaluation.get("missing", [])
        next_actions = evaluation.get("next_actions", [])
        criteria = evaluation.get("criteria", {})

        # Load prompt from recipe file
        prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "research" / "goal_generator.md"
        if prompt_path.exists():
            base_prompt = prompt_path.read_text()
        else:
            logger.warning(f"[ResearchRole] Prompt file not found: {prompt_path}")
            base_prompt = "Generate 1-3 specific research goals. Return JSON with goals array (goal, reason, query, target_sources, priority), queries array, and expected_improvement."

        # Build full prompt with dynamic data
        prompt = f"""{base_prompt}

---

## Current Task

ORIGINAL QUERY: "{query}"

CURRENT EVALUATION:
- Decision: {evaluation.get('decision', 'CONTINUE')}
- Missing info: {', '.join(missing_info) if missing_info else 'None identified'}
- Suggested actions: {', '.join(next_actions) if next_actions else 'None'}

UNMET CRITERIA:
- Coverage: {'NOT MET' if not criteria.get('coverage', {}).get('met') else 'MET'} - {criteria.get('coverage', {}).get('notes', '')}
- Quality: {'NOT MET' if not criteria.get('quality', {}).get('met') else 'MET'} - {criteria.get('quality', {}).get('notes', '')}
- Completeness: {'NOT MET' if not criteria.get('completeness', {}).get('met') else 'MET'} - {criteria.get('completeness', {}).get('notes', '')}

Generate goals now. Return ONLY JSON:"""

        try:
            solver_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
            solver_model_id = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
            solver_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    solver_url,
                    json={
                        "model": solver_model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 500,
                        "temperature": 0.3
                    },
                    headers={"Authorization": f"Bearer {solver_api_key}"}
                )
                response.raise_for_status()

                content = response.json()["choices"][0]["message"]["content"]

                # Parse JSON from response
                start_idx = content.find('{')
                end_idx = content.rfind('}') + 1
                if start_idx != -1 and end_idx > 0:
                    return json.loads(content[start_idx:end_idx])
                else:
                    raise ValueError("No JSON found in response")

        except Exception as e:
            logger.error(f"[ResearchRole] Goal generation LLM failed: {e}")
            # Return simple fallback goals
            return {
                "goals": [
                    {
                        "goal": "Find more sources",
                        "reason": "Coverage criterion not met",
                        "query": query,
                        "target_sources": 5,
                        "priority": 1
                    }
                ],
                "queries": [query],
                "expected_improvement": "Increase source coverage"
            }

    # NOTE: _execute_navigation_strategy and _execute_site_search_strategy were removed
    # as they bypassed GoalDirectedNavigator. All research now goes through intelligent_vendor_search.
    # See PIPELINE_FIX_PLAN.md for details.

    async def _summarize_page_for_goal(
        self,
        content: str,
        goal: str,
        url: str,
        title: str = ""
    ) -> str:
        """Use LLM to summarize page content based on the user's goal."""
        import httpx

        # Truncate content to avoid token limits
        content_truncated = content[:12000] if len(content) > 12000 else content

        # Load prompt from recipe file
        prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "research" / "page_summarizer.md"
        if prompt_path.exists():
            base_prompt = prompt_path.read_text()
        else:
            logger.warning(f"[ResearchRole] Prompt file not found: {prompt_path}")
            base_prompt = "Summarize webpage content to answer the user's goal. Be concise (200-400 words), include specific details."

        # Build full prompt with dynamic data
        prompt = f"""{base_prompt}

---

## Current Task

USER'S GOAL: {goal}

PAGE URL: {url}
PAGE TITLE: {title}

PAGE CONTENT:
{content_truncated}

Provide your summary:"""

        try:
            solver_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
            solver_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
            solver_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

            # SOLVER_URL already includes /v1/chat/completions, use it directly
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    solver_url,
                    headers={
                        "Authorization": f"Bearer {solver_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": solver_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 800
                    }
                )
                response.raise_for_status()
                result = response.json()
                summary = result["choices"][0]["message"]["content"]
                logger.info(f"[ResearchRole] Page summary generated ({len(summary)} chars)")
                return summary

        except Exception as e:
            logger.error(f"[ResearchRole] Failed to generate summary: {e}")
            # Fallback: return truncated content
            return f"Page content from {url}:\n\n{content[:1000]}..."

    async def _index_phase1_research(
        self,
        query: str,
        intelligence: Dict[str, Any],
        sources: List[Dict],
        stats: Dict[str, Any],
        session_id: str,
        turn_number: int,
        intent: str  # Use intent directly instead of legacy query_type
    ) -> None:
        """
        Index Phase 1 intelligence in ResearchIndexDB for context gatherer retrieval.

        This enables subsequent queries to find this research via topic-based search,
        avoiding redundant Phase 1 execution.

        Args:
            intent: Intent from _classify_research_intent (navigation, site_search, commerce, informational)
        """
        try:
            from lib.gateway.research_index_db import get_research_index_db
            from lib.gateway.research_doc_writers import normalize_topic, generate_topic_hash
            import hashlib

            # Build topic from query
            topic_normalized = normalize_topic(query)
            if not topic_normalized:
                topic_normalized = "general"

            # Generate unique ID
            research_id = f"phase1_{session_id}_{turn_number}_{generate_topic_hash(topic_normalized)}"

            # Extract keywords from intelligence
            keywords = []
            if intelligence:
                # Extract retailer names as keywords
                retailers = intelligence.get("retailers_mentioned", [])
                if isinstance(retailers, list):
                    keywords.extend(retailers[:5])

                # Extract key terms from recommendations
                recommendations = intelligence.get("forum_recommendations", [])
                for rec in recommendations[:3]:
                    if isinstance(rec, dict):
                        text = rec.get("recommendation", rec.get("text", ""))
                    else:
                        text = str(rec)
                    # Extract noun-like words as keywords
                    words = [w.lower() for w in text.split() if len(w) > 3 and w.isalpha()]
                    keywords.extend(words[:2])

            keywords = list(set(keywords))[:10]  # Dedupe and limit

            # Determine content types based on intelligence
            content_types = ["purchase_info"]  # Default for Phase 1 commerce research
            if intelligence:
                if intelligence.get("retailers_mentioned"):
                    content_types.append("vendor_info")
                if intelligence.get("forum_recommendations"):
                    content_types.append("community_recommendations")
                if intelligence.get("hard_requirements"):
                    content_types.append("requirements_info")

            # Calculate quality score
            source_count = len(sources) if sources else 0
            source_quality = min(1.0, source_count / 5.0)  # Max out at 5 sources
            completeness = 0.5  # Phase 1 is foundational, not complete
            if intelligence:
                if intelligence.get("retailers_mentioned"):
                    completeness += 0.2
                if intelligence.get("forum_recommendations"):
                    completeness += 0.2
                if intelligence.get("hard_requirements"):
                    completeness += 0.1
            overall_quality = (source_quality * 0.4 + completeness * 0.6)

            # Intent is now passed directly (no longer mapped from query_type)
            # Map to legacy intent value for index compatibility if needed
            indexed_intent = "transactional" if intent == "commerce" else "informational"

            # Build doc path for reference
            doc_path = f"panda_system_docs/sessions/{session_id}/intelligence_cache.json"

            # Get current timestamp
            now = datetime.now(timezone.utc).timestamp()
            expires_at = now + (24 * 3600)  # 24 hour TTL

            # Index in database
            index_db = get_research_index_db()
            index_db.index_research(
                id=research_id,
                turn_number=turn_number,
                session_id=session_id,
                primary_topic=f"commerce.{topic_normalized.replace(' ', '_')}",
                keywords=keywords,
                intent=indexed_intent,  # Use mapped intent for index compatibility
                completeness=completeness,
                source_quality=source_quality,
                overall_quality=overall_quality,
                confidence_initial=0.85,
                decay_rate=0.02,
                created_at=now,
                expires_at=expires_at,
                scope="new",
                doc_path=doc_path,
                content_types=content_types
            )

            logger.info(
                f"[ResearchRole] Indexed Phase 1 research: id={research_id}, "
                f"topic=commerce.{topic_normalized}, quality={overall_quality:.2f}, "
                f"content_types={content_types}"
            )

        except Exception as e:
            # Don't fail research if indexing fails
            logger.warning(f"[ResearchRole] Failed to index Phase 1 research: {e}")


# Convenience function
async def research_orchestrate(
    query: str,
    research_goal: str,
    mode: str,
    session_id: str,
    query_type: str = "commerce_search",  # DEPRECATED: Ignored, use research_context.intent
    user_constraints: Dict[str, Any] = None,
    event_emitter: Optional[Any] = None,
    remaining_token_budget: int = 10000,
    force_refresh: bool = False,
    research_context: Dict[str, Any] = None,  # Context from Planner (contains intent)
    turn_number: int = 0  # For research document indexing
) -> Dict[str, Any]:
    """
    Orchestrate research (standalone function).

    This is the main entry point for Research Role from Gateway.

    Args:
        query_type: DEPRECATED - Ignored. Use research_context["intent"] instead.
        research_context: Context from Planner with:
            - intent: Intent from _classify_research_intent (navigation, site_search, commerce, informational)
            - entities: List of specific product/item names from context
            - subtasks: Pre-planned search queries with rationale
            - research_type: Type of research (technical_specs, comparison, etc.)
            - phase_hint: Whether to skip Phase 1 (e.g., "skip_phase1")
        turn_number: Turn number for research document indexing

    Note: Intent-based routing is the single source of truth.
    See: panda_system_docs/architecture/LLM-ROLES/CONTEXT_DISCIPLINE.md
    """
    role = ResearchRole()
    return await role.orchestrate(
        query=query,
        research_goal=research_goal,
        mode=mode,
        session_id=session_id,
        query_type=query_type,  # Passed but ignored - kept for backward compatibility
        user_constraints=user_constraints,
        event_emitter=event_emitter,
        remaining_token_budget=remaining_token_budget,
        force_refresh=force_refresh,
        research_context=research_context,
        turn_number=turn_number
    )
