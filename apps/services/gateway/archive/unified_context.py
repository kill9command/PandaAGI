"""
Unified Context Manager for Pandora Gateway

Consolidates scattered context gathering/injection into a single, LLM-assisted system.
Serves both meta-reflection (lightweight) and Guide (comprehensive) with role-specific views.

Author: Implementation based on INJECTED_CONTEXT_REDESIGN_PLAN.md
Date: 2025-11-12
"""

import asyncio
import hashlib
import json
import logging
import os
import pathlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

# Import dependencies for context loading
from scripts import memory_schema
from apps.services.tool_server.shared_state.claims import ClaimRegistry

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ContextItem:
    """Single item of context from a source"""
    source: str          # "living_context", "long_term_memory", "claim", "baseline_memory"
    content: str         # The actual text
    relevance: float     # 0.0-1.0 (from LLM or rule-based)
    confidence: float    # 0.0-1.0 (for claims, 1.0 for others)
    timestamp: str       # ISO8601
    metadata: Dict[str, Any] = field(default_factory=dict)
    priority: int = 5    # 1=highest, 5=lowest (for truncation)

    def content_hash(self) -> str:
        """Generate hash for deduplication"""
        return hashlib.md5(self.content.encode()).hexdigest()


@dataclass
class UnifiedContext:
    """All gathered context before curation"""
    living_context: Optional[ContextItem]
    long_term_memories: List[ContextItem]
    recent_claims: List[ContextItem]
    baseline_memories: List[ContextItem]
    discovered_facts: List[ContextItem]  # NEW (2025-11-13): Reuse stored facts
    total_items: int
    total_estimated_tokens: int
    gather_time_ms: float = 0.0


@dataclass
class CuratedContext:
    """Curated context after selection"""
    selected_items: List[ContextItem]
    total_tokens: int
    curation_method: str  # "rule_based", "llm", "bootstrap"
    curation_reasoning: str
    curate_time_ms: float = 0.0
    cache_hit: bool = False


@dataclass
class ContextMetrics:
    """Metrics for monitoring context operations"""
    gather_start: float
    gather_duration_ms: float
    curate_start: float
    curate_duration_ms: float
    source_counts: Dict[str, int] = field(default_factory=dict)
    source_tokens: Dict[str, int] = field(default_factory=dict)
    dedup_removed: int = 0
    truncated_items: int = 0
    cache_hit: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gather_ms": self.gather_duration_ms,
            "curate_ms": self.curate_duration_ms,
            "source_counts": self.source_counts,
            "source_tokens": self.source_tokens,
            "dedup_removed": self.dedup_removed,
            "truncated": self.truncated_items,
            "cache_hit": self.cache_hit
        }


# ============================================================================
# Unified Context Manager
# ============================================================================

class UnifiedContextManager:
    """
    Centralized context management for Guide injections.

    Architecture:
    1. Gather context from all sources (living, long-term, claims, baseline)
    2. Curate with role-specific budgets (meta: 300, guide: 2500)
    3. Format for injection (compact vs comprehensive)

    Features:
    - Domain filtering for claims (prevent cache pollution)
    - Deduplication (hash-based)
    - Token truncation (priority-based)
    - LLM-assisted curation (Phase 2, with fallback)
    - Metrics collection
    - Aggressive caching
    """

    # Token budgets (adjusted per quality-agent recommendations)
    META_REFLECTION_BUDGET = 300  # Lightweight for strategy
    GUIDE_CONTEXT_BUDGET = 2500   # Comprehensive for synthesis

    # Domain mapping for intent-based filtering
    DOMAIN_MAP = {
        "transactional": ["pricing", "purchasing", "commerce", "shopping", "research", "search_quality"],
        "informational": ["care", "research", "facts", "general", "search_quality"],
        "navigational": ["location", "directory", "breeder", "store", "research"],
        "code": ["file", "git", "repository", "code"]
    }

    def __init__(
        self,
        llm_url: str = "http://localhost:8000/v1/chat/completions",
        enable_llm_curation: bool = False,  # Start with False (Phase 1)
        enable_metrics: bool = True,
        claim_registry: Optional[ClaimRegistry] = None,
        mem_index_path: Optional[pathlib.Path] = None,
        mem_json_dir: Optional[pathlib.Path] = None
    ):
        self.llm_url = llm_url
        self.enable_llm_curation = enable_llm_curation
        self.enable_metrics = enable_metrics

        # Memory and claim dependencies
        self.claim_registry = claim_registry
        self.mem_index_path = mem_index_path or pathlib.Path(
            os.getenv("LONG_TERM_MEMORY_INDEX", "panda_system_docs/memory/long_term/index.json")
        )
        self.mem_json_dir = mem_json_dir or pathlib.Path(
            os.getenv("LONG_TERM_MEMORY_DIR", "panda_system_docs/memory/long_term/json")
        )
        self.profile_memory_max = int(os.getenv("PROFILE_MEMORY_MAX", "5"))

        # Caching for curated context (per session)
        self._curate_cache: Dict[str, CuratedContext] = {}
        self._cache_ttl = 300  # 5 minutes

        # Metrics
        self._metrics_history: List[ContextMetrics] = []

        logger.info(f"[UnifiedContext] Initialized (LLM curation: {enable_llm_curation})")

    # ========================================================================
    # Main Public API
    # ========================================================================

    async def gather_context(
        self,
        session_id: str,
        profile_id: str,
        user_query: str,
        live_ctx: Any,  # LiveSessionContext
        turn_count: int,
        query_intent: str = "informational"
    ) -> UnifiedContext:
        """
        Gather context from all sources.

        Sources (in priority order):
        1. Living session context (turn history, preferences, facts)
        2. Long-term memories (profile-specific saved memories)
        3. Recent claims (from claim registry, domain-filtered)
        4. Baseline memories (semantic search on query)
        """
        start_time = time.time()

        logger.info(f"[UnifiedContext] Gathering context for session {session_id}, turn {turn_count}")

        source_counts = {}
        source_tokens = {}

        # Source 1: Living session context (highest priority)
        living_item = None
        if turn_count > 0:
            living_text = live_ctx.to_context_block(max_tokens=400)
            living_item = ContextItem(
                source="living_context",
                content=living_text,
                relevance=1.0,
                confidence=1.0,
                timestamp=datetime.utcnow().isoformat(),
                metadata={"turn": turn_count, "topic": live_ctx.current_topic},
                priority=1  # Highest priority (always keep)
            )
            source_counts["living_context"] = 1
            source_tokens["living_context"] = self._estimate_tokens(living_text)

        # Source 2: Long-term memories (profile-specific)
        ltm_items = await self._gather_long_term_memories(profile_id, user_query)
        source_counts["long_term_memories"] = len(ltm_items)
        source_tokens["long_term_memories"] = sum(self._estimate_tokens(item.content) for item in ltm_items)

        # Source 3: Recent claims (domain-filtered)
        claim_items = await self._gather_recent_claims(session_id, user_query, query_intent)
        source_counts["recent_claims"] = len(claim_items)
        source_tokens["recent_claims"] = sum(self._estimate_tokens(item.content) for item in claim_items)

        # Source 3.5: Discovered facts (NEW: 2025-11-13 - reuse stored session facts)
        fact_items = self._gather_discovered_facts(live_ctx, query_intent)
        source_counts["discovered_facts"] = len(fact_items)
        source_tokens["discovered_facts"] = sum(self._estimate_tokens(item.content) for item in fact_items)
        logger.info(f"[UnifiedContext] Extracted {len(fact_items)} facts from session context")

        # Source 4: Baseline memories (semantic search)
        baseline_items = await self._gather_baseline_memories(profile_id, user_query)
        source_counts["baseline_memories"] = len(baseline_items)
        source_tokens["baseline_memories"] = sum(self._estimate_tokens(item.content) for item in baseline_items)

        total_items = len(ltm_items) + len(claim_items) + len(fact_items) + len(baseline_items) + (1 if living_item else 0)
        total_tokens = sum(source_tokens.values())

        gather_time_ms = (time.time() - start_time) * 1000

        logger.info(f"[UnifiedContext] Gathered {total_items} items, {total_tokens} tokens in {gather_time_ms:.1f}ms")

        return UnifiedContext(
            living_context=living_item,
            long_term_memories=ltm_items,
            recent_claims=claim_items,
            baseline_memories=baseline_items,
            discovered_facts=fact_items,
            total_items=total_items,
            total_estimated_tokens=total_tokens,
            gather_time_ms=gather_time_ms
        )

    async def curate(
        self,
        unified_context: UnifiedContext,
        user_query: str,
        query_intent: str,
        role: str,  # "meta_reflection" or "guide"
        session_id: str
    ) -> CuratedContext:
        """
        Curate context for specific role.

        Meta-reflection needs:
        - Lightweight (300 tokens)
        - High-level session state
        - Quick decision-making

        Guide needs:
        - Comprehensive (2500 tokens)
        - Detailed context
        - Full answer synthesis
        """
        start_time = time.time()

        # Check cache
        cache_key = self._build_cache_key(session_id, user_query, role)
        if cache_key in self._curate_cache:
            cached = self._curate_cache[cache_key]
            cached.cache_hit = True
            logger.info(f"[UnifiedContext] Cache hit for {role} in session {session_id}")
            return cached

        # Route to role-specific curation
        if role == "meta_reflection":
            budget = self.META_REFLECTION_BUDGET
            curated = await self._curate_for_meta_reflection(
                unified_context, user_query, query_intent, budget
            )
        elif role == "guide":
            budget = self.GUIDE_CONTEXT_BUDGET
            curated = await self._curate_for_guide(
                unified_context, user_query, query_intent, budget, session_id
            )
        else:
            raise ValueError(f"Unknown role: {role}")

        curated.curate_time_ms = (time.time() - start_time) * 1000

        # Cache result
        self._curate_cache[cache_key] = curated

        logger.info(
            f"[UnifiedContext] Curated {len(curated.selected_items)} items "
            f"({curated.total_tokens}/{budget} tokens) for {role} in {curated.curate_time_ms:.1f}ms"
        )

        return curated

    def format_for_reflection(self, curated_context: CuratedContext) -> str:
        """
        Format for meta-reflection input (compact).

        Target: ~100-150 tokens, binary indicators.
        """
        sections = []

        # Living context (if present)
        living = [item for item in curated_context.selected_items if item.source == "living_context"]
        if living:
            # Extract key info only
            content = living[0].content
            lines = content.split("\n")

            # Compact format
            sections.append("**Reflection Context:**")
            for line in lines[:5]:  # First 5 lines only
                if line.strip():
                    sections.append(line.strip())

        # Preferences (if any)
        preferences = [item for item in curated_context.selected_items
                      if "preference" in item.metadata.get("tags", [])]
        if preferences:
            sections.append("\n**Key Preferences:**")
            for pref in preferences[:2]:  # Top 2 only
                sections.append(f"- {pref.content[:50]}...")  # Truncate

        return "\n".join(sections)

    def format_for_guide(self, curated_context: CuratedContext, turn_count: int) -> str:
        """
        Format for Guide injection (comprehensive).

        Target: Full context with all sources organized.
        """
        sections = []

        # Group items by source
        living = [item for item in curated_context.selected_items if item.source == "living_context"]
        memories = [item for item in curated_context.selected_items if "memory" in item.source]
        claims = [item for item in curated_context.selected_items if item.source == "claim"]
        facts = [item for item in curated_context.selected_items if item.source == "discovered_facts"]

        # Format living context
        if living:
            sections.append(f"**Session Context (Turn {turn_count}):**")
            sections.append(living[0].content)

        # Format discovered facts (NEW: 2025-11-13)
        if facts:
            sections.append("\n**Known Facts (from previous searches):**")
            # Group facts by category for better organization
            facts_by_category = {}
            for item in facts:
                category = item.metadata.get("category", "general")
                if category not in facts_by_category:
                    facts_by_category[category] = []
                facts_by_category[category].append(item.content)

            for category, fact_list in facts_by_category.items():
                sections.append(f"\n*{category.capitalize()}:*")
                for fact in fact_list:
                    sections.append(f"  - {fact}")

        # Format memories
        if memories:
            sections.append("\n**Relevant Memories:**")
            for item in memories:
                sections.append(f"- {item.content}")

        # Format claims
        if claims:
            sections.append("\n**Recent Discoveries:**")
            for item in claims:
                sections.append(f"- {item.content} (confidence: {item.confidence:.2f})")

        # Add metadata footer
        sections.append(
            f"\n[Context: {len(curated_context.selected_items)} items, "
            f"{curated_context.total_tokens} tokens, "
            f"method: {curated_context.curation_method}]"
        )

        return "\n".join(sections)

    # ========================================================================
    # Role-Specific Curation
    # ========================================================================

    async def _curate_for_meta_reflection(
        self,
        unified_context: UnifiedContext,
        user_query: str,
        query_intent: str,
        token_budget: int = 300
    ) -> CuratedContext:
        """
        Lightweight curation for strategy planning.

        Includes:
        - Living context (always)
        - Top 2 preferences (if relevant)
        - Query intent classification

        Excludes:
        - Detailed claims
        - Long-term memories
        - Baseline memories
        """
        selected = []

        # Always include living context (compact version)
        if unified_context.living_context:
            # Keep as-is, already prioritized
            selected.append(unified_context.living_context)

        # Add top preferences if relevant
        preferences = [item for item in unified_context.long_term_memories
                      if "preference" in item.metadata.get("tags", [])]
        for pref in preferences[:2]:  # Top 2 only
            selected.append(pref)

        # Calculate tokens
        total_tokens = sum(self._estimate_tokens(item.content) for item in selected)

        # Truncate if over budget
        if total_tokens > token_budget:
            selected, total_tokens = self._truncate_to_budget(selected, token_budget)

        return CuratedContext(
            selected_items=selected,
            total_tokens=total_tokens,
            curation_method="rule_based_meta_reflection",
            curation_reasoning="Lightweight for strategy: living context + top preferences"
        )

    async def _curate_for_guide(
        self,
        unified_context: UnifiedContext,
        user_query: str,
        query_intent: str,
        token_budget: int = 2500,
        session_id: str = None
    ) -> CuratedContext:
        """
        Comprehensive curation for answer synthesis.

        Includes:
        - Living context (full version)
        - All high-confidence claims (>0.7)
        - Relevant long-term memories
        - Relevant baseline memories

        Phase 1: Rule-based prioritization
        Phase 2: LLM-assisted selection (with fallback)
        Phase 3: Intent-weighted scoring (with fallback)
        """

        # Phase 3: Try intent-weighted scoring if enabled (NEW)
        if os.getenv("ENABLE_INTENT_WEIGHTED_SCORING", "1") == "1":
            try:
                return self._curate_with_intent_weights(
                    unified_context, user_query, query_intent, token_budget
                )
            except Exception as e:
                logger.warning(f"[UnifiedContext] Intent-weighted scoring failed: {e}, falling back to LLM/rules")

        # Phase 2: Try LLM curation if enabled
        if self.enable_llm_curation:
            try:
                return await self._curate_with_llm(
                    unified_context, user_query, query_intent, token_budget, session_id
                )
            except Exception as e:
                logger.warning(f"[UnifiedContext] LLM curation failed: {e}, falling back to rules")

        # Phase 1: Rule-based curation (final fallback)
        return self._curate_rule_based(unified_context, token_budget)

    def _curate_rule_based(
        self,
        unified_context: UnifiedContext,
        token_budget: int
    ) -> CuratedContext:
        """
        Rule-based curation (Phase 1, fallback for Phase 2).

        Priority: living > discovered_facts > claims (by confidence) > memories (by recency)
        """
        all_items = []

        # Collect all items
        if unified_context.living_context:
            all_items.append(unified_context.living_context)

        all_items.extend(unified_context.discovered_facts)  # NEW (2025-11-13): Include session facts
        all_items.extend(unified_context.recent_claims)
        all_items.extend(unified_context.long_term_memories)
        all_items.extend(unified_context.baseline_memories)

        # Deduplicate
        all_items, dedup_count = self._deduplicate(all_items)

        # Sort by priority + relevance + confidence
        all_items.sort(
            key=lambda item: (
                item.priority,              # Lower number = higher priority
                -item.relevance,            # Higher relevance first
                -item.confidence            # Higher confidence first
            )
        )

        # Select items within budget
        selected = []
        total_tokens = 0

        for item in all_items:
            item_tokens = self._estimate_tokens(item.content)
            if total_tokens + item_tokens <= token_budget:
                selected.append(item)
                total_tokens += item_tokens
            else:
                # Try to fit by truncating (for non-priority items)
                if item.priority > 1:
                    break  # Stop adding

        # If over budget, truncate
        truncated_count = 0
        if total_tokens > token_budget:
            selected, total_tokens = self._truncate_to_budget(selected, token_budget)
            truncated_count = len(all_items) - len(selected)

        return CuratedContext(
            selected_items=selected,
            total_tokens=total_tokens,
            curation_method="rule_based",
            curation_reasoning=f"Prioritized by: living > confidence > recency (dedup: {dedup_count}, truncated: {truncated_count})"
        )

    def _curate_with_intent_weights(
        self,
        unified_context: UnifiedContext,
        user_query: str,
        query_intent: str,
        token_budget: int
    ) -> CuratedContext:
        """
        Intent-weighted curation using CONTEXT_SCORER (Phase 3).

        Uses semantic similarity + source confidence + intent-based weighting
        to dynamically allocate context budget based on query type.

        RECALL queries: More memory, less RAG
        INFORMATIONAL queries: More RAG, less memory
        """
        from apps.services.gateway.context_scorer import CONTEXT_SCORER
        from apps.services.gateway.intent_weights import (
            MINIMUM_ALLOCATIONS,
            MAXIMUM_ALLOCATIONS
        )

        # Convert UnifiedContext items to scorer format
        scorer_items = []

        if unified_context.living_context:
            scorer_items.append({
                "content": unified_context.living_context.content,
                "source": "living_context",
                "metadata": unified_context.living_context.metadata,
                "similarity": unified_context.living_context.relevance
            })

        for mem in unified_context.long_term_memories:
            scorer_items.append({
                "content": mem.content,
                "source": "long_term_memory",
                "metadata": mem.metadata,
                "similarity": mem.relevance
            })

        for claim in unified_context.recent_claims:
            scorer_items.append({
                "content": claim.content,
                "source": "recent_claims",
                "metadata": {"confidence": claim.confidence, **claim.metadata},
                "similarity": claim.relevance
            })

        for baseline in unified_context.baseline_memories:
            scorer_items.append({
                "content": baseline.content,
                "source": "baseline_memory",
                "metadata": baseline.metadata,
                "similarity": baseline.relevance
            })

        for fact in unified_context.discovered_facts:
            scorer_items.append({
                "content": fact.content,
                "source": "discovered_facts",
                "metadata": fact.metadata,
                "similarity": fact.relevance
            })

        # Score and select with intent-based weighting
        scored = CONTEXT_SCORER.score_batch(scorer_items, user_query, query_intent)
        selected_scored = CONTEXT_SCORER.select_within_budget(
            scored, token_budget, MINIMUM_ALLOCATIONS, MAXIMUM_ALLOCATIONS
        )

        # Convert back to ContextItem format
        selected_items = []
        for scored_item in selected_scored:
            selected_items.append(ContextItem(
                source=scored_item.source,
                content=scored_item.content,
                relevance=scored_item.base_relevance,
                confidence=scored_item.source_confidence,
                timestamp=scored_item.metadata.get("timestamp", datetime.utcnow().isoformat()),
                metadata=scored_item.metadata,
                priority=1  # All selected items are priority
            ))

        total_tokens = sum(item.tokens for item in selected_scored)

        # Calculate source breakdown for reasoning
        source_tokens = {}
        for item in selected_scored:
            source_tokens[item.source] = source_tokens.get(item.source, 0) + item.tokens

        reasoning = f"Intent={query_intent}, dynamic allocation: " + ", ".join(
            f"{src}={tokens}t" for src, tokens in sorted(source_tokens.items())
        )

        logger.info(f"[UnifiedContext] Intent-weighted curation: {reasoning}")

        return CuratedContext(
            selected_items=selected_items,
            total_tokens=total_tokens,
            curation_method="intent_weighted_scoring",
            curation_reasoning=reasoning
        )

    async def _curate_with_llm(
        self,
        unified_context: UnifiedContext,
        user_query: str,
        query_intent: str,
        token_budget: int,
        session_id: str
    ) -> CuratedContext:
        """
        Use LLM to intelligently select context (Phase 2).

        Timeout: 500ms (automatic fallback to rule-based)
        Model: Use fast model (haiku or local 7B)
        """
        try:
            # Build curation prompt
            prompt = self._build_curation_prompt(
                unified_context, user_query, query_intent, token_budget
            )

            # Call LLM with timeout
            async with httpx.AsyncClient() as client:
                response = await asyncio.wait_for(
                    client.post(
                        self.llm_url,
                        json={
                            "model": "claude-3-haiku",  # Fast model
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 500,
                            "temperature": 0.3
                        },
                        timeout=0.5  # 500ms timeout
                    ),
                    timeout=0.5
                )

            # Parse response
            curated = self._parse_curation_response(response.json(), unified_context)
            curated.curation_method = "llm"

            return curated

        except Exception as e:
            logger.warning(f"[UnifiedContext] LLM curation failed: {e}, using rule-based")
            return self._curate_rule_based(unified_context, token_budget)

    # ========================================================================
    # Context Source Gathering (Helpers)
    # ========================================================================

    async def _gather_long_term_memories(
        self,
        profile_id: str,
        query: str
    ) -> List[ContextItem]:
        """
        Gather long-term memories from persistent storage.

        Loads saved preferences, profile info, and general memories
        from the long-term memory index.
        """
        items = []

        try:
            # Load memory index
            idx = memory_schema.load_index(self.mem_index_path)
        except Exception as e:
            logger.warning(f"[UnifiedContext] Failed to load memory index: {e}")
            return []

        tags = idx.get("tags") or {}
        candidate_entries = []

        # Collect entries from preference, profile, memory, all tags
        for tag in ("preference", "profile", "memory", "all"):
            for entry in tags.get(tag, []):
                candidate_entries.append(entry)

        # Sort by most recent first
        candidate_entries.sort(key=lambda meta: meta.get("created_at", ""), reverse=True)

        seen_ids: set[str] = set()
        for meta in candidate_entries[:self.profile_memory_max * 2]:  # Load 2x for dedup
            entry_id = meta.get("id")
            if not entry_id or entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)

            record_path = self.mem_json_dir / f"{entry_id}.json"
            if not record_path.exists():
                continue

            try:
                data = json.loads(record_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[UnifiedContext] Failed to read memory {entry_id}: {e}")
                continue

            metadata = data.get("metadata") or {}
            mem_profile = metadata.get("profile")

            # Filter by profile
            if mem_profile and mem_profile != profile_id:
                continue

            # Extract content from memory structure
            # Priority: summary > title > body_md
            value = data.get("summary") or data.get("title") or data.get("body_md", "")
            if not value or not value.strip():
                continue

            # For preference memories, extract key from title if available
            title = data.get("title", "")
            if "preference" in title.lower() or "favorite" in title.lower():
                key = "preference"
            else:
                key = "memory"

            # Create ContextItem
            content = f"{title}: {value}" if value != title else value
            items.append(ContextItem(
                source="long_term_memory",
                content=content,
                relevance=0.8,  # High relevance for stored memories
                confidence=1.0,
                timestamp=data.get("created_at", datetime.utcnow().isoformat()),
                metadata={"key": key, "memory_id": entry_id, "title": title},
                priority=2  # High priority (after living context)
            ))

            if len(items) >= self.profile_memory_max:
                break

        logger.info(f"[UnifiedContext] Loaded {len(items)} long-term memories for profile {profile_id}")
        return items

    async def _gather_recent_claims(
        self,
        session_id: str,
        query: str,
        query_intent: str
    ) -> List[ContextItem]:
        """
        Gather recent claims from claim registry.

        Domain filtering applied based on query intent.
        """
        items = []

        if not self.claim_registry:
            logger.debug("[UnifiedContext] No claim registry available")
            return []

        # Map intent to relevant domains
        relevant_domains = self.DOMAIN_MAP.get(query_intent, ["general"])

        try:
            # Get active claims for this session
            active_claims = list(self.claim_registry.list_active_claims(session_id=session_id))

            for claim in active_claims[:10]:  # Limit to 10 most recent
                # Extract domain from metadata
                claim_domain = claim.metadata.get("domain", "general")
                if claim_domain not in relevant_domains and "general" not in relevant_domains:
                    logger.debug(f"[UnifiedContext] Skipping claim from domain {claim_domain} (not in {relevant_domains})")
                    continue

                # Convert confidence string to float
                confidence_map = {"low": 0.3, "medium": 0.6, "high": 0.9}
                confidence_value = confidence_map.get(claim.confidence.lower(), 0.6)

                # Only include high-confidence claims
                if confidence_value < 0.5:
                    continue

                # Extract relevance from metadata (intent_alignment or quality_score)
                relevance = claim.metadata.get("intent_alignment") or claim.metadata.get("quality_score", 0.7)

                # Create ContextItem from claim
                # Preserve full claim metadata (includes product_name, price, vendor, url)
                full_metadata = dict(claim.metadata) if claim.metadata else {}
                full_metadata.update({
                    "claim_id": claim.claim_id,
                    "domain": claim_domain,
                })

                items.append(ContextItem(
                    source="claim",
                    content=claim.statement,  # ClaimRow uses 'statement', not 'claim_text'
                    relevance=relevance,
                    confidence=confidence_value,
                    timestamp=str(claim.created_at),
                    metadata=full_metadata,
                    priority=3  # Medium priority (after memories)
                ))

            logger.info(f"[UnifiedContext] Loaded {len(items)} recent claims for session {session_id}")

        except Exception as e:
            logger.warning(f"[UnifiedContext] Failed to load claims: {e}")

        return items

    async def _gather_baseline_memories(
        self,
        profile_id: str,
        query: str
    ) -> List[ContextItem]:
        """
        Gather baseline memories via semantic search.

        For now, returns empty list. Future implementation will use
        embedding-based semantic search across all memories.
        """
        # TODO: Implement semantic search when embedding service is available
        # For Phase 1, we rely on long-term memories and claims
        return []

    def _gather_discovered_facts(
        self,
        live_ctx: Any,  # LiveSessionContext
        query_intent: str
    ) -> List[ContextItem]:
        """
        Gather discovered facts from session context (NEW: 2025-11-13).

        This reuses facts stored in previous turns, eliminating duplicate searches.
        Facts are domain-filtered based on query intent.

        Args:
            live_ctx: LiveSessionContext with discovered_facts
            query_intent: Query intent for domain filtering

        Returns:
            List of ContextItems with facts
        """
        items = []

        if not hasattr(live_ctx, 'discovered_facts') or not live_ctx.discovered_facts:
            logger.debug("[UnifiedContext] No discovered facts in session context")
            return []

        # Map intent to relevant domains
        relevant_domains = self.DOMAIN_MAP.get(query_intent, ["general"])

        # Extract facts from each category
        for category, facts_list in live_ctx.discovered_facts.items():
            # Domain filtering: only include facts from relevant domains
            if category not in relevant_domains and "general" not in relevant_domains:
                logger.debug(f"[UnifiedContext] Skipping facts from category '{category}' (not in {relevant_domains})")
                continue

            # Convert each fact to a ContextItem
            for fact in facts_list:
                if not fact or not isinstance(fact, str):
                    continue

                items.append(ContextItem(
                    source="discovered_facts",
                    content=fact,
                    relevance=1.0,  # High relevance - already stored from previous turn
                    confidence=0.8,  # High confidence - extracted from tools
                    timestamp=datetime.utcnow().isoformat(),
                    metadata={
                        "category": category,
                        "session_reuse": True
                    },
                    priority=2  # High priority (after living context, before claims)
                ))

        logger.info(f"[UnifiedContext] Extracted {len(items)} discovered facts from session context")

        return items

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _deduplicate(self, items: List[ContextItem]) -> tuple[List[ContextItem], int]:
        """
        Remove duplicate content across sources.

        Returns: (deduplicated_items, count_removed)
        """
        seen_hashes = set()
        deduped = []
        removed = 0

        for item in items:
            content_hash = item.content_hash()
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                deduped.append(item)
            else:
                removed += 1

        return deduped, removed

    def _truncate_to_budget(
        self,
        items: List[ContextItem],
        budget: int
    ) -> tuple[List[ContextItem], int]:
        """
        Truncate items to fit within budget.

        Priority-based: Remove lowest priority items first.

        Returns: (truncated_items, total_tokens)
        """
        # Sort by priority (keep highest priority)
        sorted_items = sorted(items, key=lambda x: x.priority)

        selected = []
        total_tokens = 0

        for item in sorted_items:
            item_tokens = self._estimate_tokens(item.content)
            if total_tokens + item_tokens <= budget:
                selected.append(item)
                total_tokens += item_tokens
            else:
                # Budget exceeded, stop
                break

        return selected, total_tokens

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (words * 1.3)"""
        return int(len(text.split()) * 1.3)

    def _build_cache_key(self, session_id: str, query: str, role: str) -> str:
        """Build cache key for curated context"""
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        return f"{session_id}_{role}_{query_hash}"

    def _build_curation_prompt(
        self,
        unified_context: UnifiedContext,
        user_query: str,
        query_intent: str,
        token_budget: int
    ) -> str:
        """
        Build prompt for LLM curator (Phase 2).

        TODO: Implement actual prompt
        """
        return f"""You are a context curator. Select the most relevant context items.

Query: {user_query}
Intent: {query_intent}
Budget: {token_budget} tokens

Available context: {unified_context.total_items} items

Select the most relevant items and return JSON."""

    def _parse_curation_response(
        self,
        response: dict,
        unified_context: UnifiedContext
    ) -> CuratedContext:
        """
        Parse LLM curation response (Phase 2).

        TODO: Implement actual parsing
        """
        # Placeholder: fallback to rule-based
        return self._curate_rule_based(unified_context, self.GUIDE_CONTEXT_BUDGET)

    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        if not self._metrics_history:
            return {}

        recent = self._metrics_history[-10:]  # Last 10

        return {
            "total_curations": len(self._metrics_history),
            "avg_gather_ms": sum(m.gather_duration_ms for m in recent) / len(recent),
            "avg_curate_ms": sum(m.curate_duration_ms for m in recent) / len(recent),
            "cache_hit_rate": sum(1 for m in recent if m.cache_hit) / len(recent),
            "avg_dedup_removed": sum(m.dedup_removed for m in recent) / len(recent)
        }

    def write_document(self, unified_context: UnifiedContext, turn_dir: 'TurnDirectory') -> pathlib.Path:
        """
        Write unified_context.md to turn directory (v4.0 document-driven).

        Args:
            unified_context: Gathered context
            turn_dir: TurnDirectory instance

        Returns:
            Path to written file
        """
        from libs.gateway.context.doc_writers import write_unified_context_md
        return write_unified_context_md(turn_dir, unified_context)


# ============================================================================
# Singleton Instance (created in gateway/app.py)
# ============================================================================

# This will be instantiated in gateway/app.py:
# UNIFIED_CONTEXT_MGR = UnifiedContextManager(
#     llm_url=SOLVER_URL,
#     enable_llm_curation=os.getenv("ENABLE_LLM_CURATION", "false").lower() == "true"
# )
