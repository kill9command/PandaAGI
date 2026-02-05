"""
lib/gateway/context_pipeline.py

LEGACY MODULE - See ContextGatherer2Phase for the current implementation.

This module implements an older unified context pipeline. The current Panda
architecture uses ContextGatherer2Phase (context_gatherer_2phase.py) which
implements the two-phase retrieval + synthesis pattern aligned with Phase 2.1/2.2.

Key differences from current architecture:
- Uses intent-domain mapping (INTENT_DOMAINS) which conflicts with the
  "no hardcoding for subjective decisions" principle
- Doesn't implement the two-phase (retrieval + synthesis) pattern
- Scoring heuristics are embedded in code rather than LLM-driven

This module is retained for backward compatibility only. New code should use
ContextGatherer2Phase from libs.gateway.context.

---

Original docstring:

Unified Context Pipeline - Consolidates all context gathering, validation, and scoring.

This replaces the scattered context gathering in:
- UnifiedContextManager.gather_context()
- IntelligenceRetriever.retrieve()

Key features:
1. Single source for all context (claims, memories, facts, cache)
2. Validation phase (TTL, confidence, deduplication)
3. Multi-factor relevance scoring
4. Budget-aware selection
5. Optional LLM consolidation for conflicts

Created: 2024-12-02
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ContextItem:
    """
    Unified context item from any source.

    All context (claims, memories, facts, cache) is normalized to this format
    for consistent validation, scoring, and selection.
    """
    # Identity
    item_id: str                    # Unique ID (hash of content + source)
    source: str                     # "claim_registry", "session_intel", "memory", "discovered_fact"
    source_id: Optional[str] = None # Original ID (claim_id, memory_id, etc.)

    # Content
    content: str = ""               # The actual text
    content_type: str = "general"   # "product_claim", "fact", "preference", "memory"

    # Scoring inputs
    confidence: float = 0.7         # 0.0-1.0 from source
    freshness_hours: float = 0.0    # Age in hours
    source_priority: int = 5        # 1=session state, 2=memory, 3=claims, 4=cache, 5=baseline

    # Computed scores (set during scoring phase)
    semantic_similarity: float = 0.0  # To current query
    relevance_score: float = 0.0      # Final weighted score

    # Validation results (set during validation phase)
    is_valid: bool = True
    is_stale: bool = False          # Past soft TTL but not expired
    is_expired: bool = False        # Past hard TTL, should not be used
    conflicts_with: List[str] = field(default_factory=list)  # IDs of conflicting items
    duplicate_of: Optional[str] = None  # ID of primary if this is a duplicate

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    ttl_hours: float = 168.0        # Default 7 days

    def content_hash(self) -> str:
        """Generate hash for deduplication."""
        return hashlib.md5(self.content.encode()).hexdigest()[:12]


@dataclass
class ContextResult:
    """Result from context pipeline."""
    # Selected items (within budget)
    items: List[ContextItem] = field(default_factory=list)

    # Categorized items for easy access
    session_state: Optional[ContextItem] = None
    claims: List[ContextItem] = field(default_factory=list)
    memories: List[ContextItem] = field(default_factory=list)
    facts: List[ContextItem] = field(default_factory=list)

    # Metadata
    total_gathered: int = 0
    total_valid: int = 0
    total_selected: int = 0
    total_tokens: int = 0
    gather_time_ms: float = 0.0

    # Diagnostics
    conflicts_detected: List[Tuple[str, str]] = field(default_factory=list)
    duplicates_removed: int = 0
    expired_removed: int = 0

    # For downstream phases
    has_product_claims: bool = False
    has_sufficient_data: bool = False
    freshest_claim_hours: float = 999.0


@dataclass
class ValidationConfig:
    """Configuration for validation phase."""
    min_confidence: float = 0.3
    max_age_hours: float = 168.0  # 7 days default
    transactional_max_age_hours: float = 24.0  # Stricter for prices
    enable_dedup: bool = True
    enable_conflict_detection: bool = True


@dataclass
class ScoringConfig:
    """Configuration for scoring phase."""
    # Weights for relevance scoring (must sum to 1.0)
    semantic_weight: float = 0.35
    priority_weight: float = 0.20
    freshness_weight: float = 0.20
    confidence_weight: float = 0.15
    intent_weight: float = 0.10

    # Semantic similarity thresholds
    transactional_min_similarity: float = 0.35  # Lower for product searches
    informational_min_similarity: float = 0.50  # Standard


# ============================================================================
# Context Pipeline
# ============================================================================

class ContextPipeline:
    """
    Unified context gathering, validation, and consolidation.

    Replaces scattered context gathering with a single, consistent pipeline.
    """

    # Intent to domain mapping
    INTENT_DOMAINS = {
        "transactional": ["commerce", "shopping", "product"],
        "commerce_search": ["commerce", "shopping", "product"],
        "comparison": ["commerce", "shopping", "product"],
        "informational": ["general", "knowledge"],
        "navigational": ["general", "location"],
        "local_service": ["local", "service"],
        "recall": ["general"],
        "retry": ["commerce", "shopping", "general"],
    }

    def __init__(
        self,
        claim_registry: Any = None,
        session_context_manager: Any = None,
        embedding_service: Any = None,
        validation_config: Optional[ValidationConfig] = None,
        scoring_config: Optional[ScoringConfig] = None
    ):
        """
        Initialize the context pipeline.

        Args:
            claim_registry: ClaimRegistry for verified claims
            session_context_manager: SessionContextManager for live context
            embedding_service: EmbeddingService for semantic similarity
            validation_config: Configuration for validation phase
            scoring_config: Configuration for scoring phase
        """
        self.claim_registry = claim_registry
        self.session_mgr = session_context_manager
        self.embedding_service = embedding_service
        self.validation_config = validation_config or ValidationConfig()
        self.scoring_config = scoring_config or ScoringConfig()

        # Cache for embeddings
        self._embedding_cache: Dict[str, List[float]] = {}

    async def build_context(
        self,
        session_id: str,
        user_query: str,
        intent: str,
        live_ctx: Any = None,
        budget_tokens: int = 2000,
        profile_id: Optional[str] = None
    ) -> ContextResult:
        """
        Main entry point. Returns validated, scored, selected context.

        Args:
            session_id: Session ID for session-scoped data
            user_query: Current user query
            intent: Query intent (transactional, informational, etc.)
            live_ctx: Live session context (preferences, topic, etc.)
            budget_tokens: Maximum tokens for output
            profile_id: Profile ID for long-term memories

        Returns:
            ContextResult with selected items and metadata
        """
        start_time = time.time()

        logger.info(f"[ContextPipeline] Building context for session {session_id}, intent={intent}")

        # Phase 0: Gather raw items from all sources
        raw_items = await self._gather_all_sources(
            session_id=session_id,
            user_query=user_query,
            intent=intent,
            live_ctx=live_ctx,
            profile_id=profile_id
        )

        logger.info(f"[ContextPipeline] Gathered {len(raw_items)} raw items")

        # Phase 1: Validate items
        valid_items, validation_stats = self._validate_items(
            items=raw_items,
            intent=intent
        )

        logger.info(
            f"[ContextPipeline] Validated: {len(valid_items)} valid, "
            f"{validation_stats['expired']} expired, {validation_stats['duplicates']} duplicates"
        )

        # Phase 2: Score and rank items
        scored_items = await self._score_items(
            items=valid_items,
            user_query=user_query,
            intent=intent
        )

        # Phase 3: Select within budget
        selected_items, total_tokens = self._select_within_budget(
            items=scored_items,
            budget_tokens=budget_tokens
        )

        logger.info(
            f"[ContextPipeline] Selected {len(selected_items)} items, "
            f"{total_tokens} tokens (budget: {budget_tokens})"
        )

        # Phase 4: Check for conflicts and consolidate if needed
        conflicts = self._detect_conflicts(selected_items)
        if conflicts:
            logger.info(f"[ContextPipeline] Detected {len(conflicts)} conflicts, resolving...")
            selected_items = await self._resolve_conflicts(
                items=selected_items,
                conflicts=conflicts,
                user_query=user_query
            )

        # Build result
        gather_time_ms = (time.time() - start_time) * 1000

        result = self._build_result(
            selected_items=selected_items,
            raw_count=len(raw_items),
            valid_count=len(valid_items),
            total_tokens=total_tokens,
            gather_time_ms=gather_time_ms,
            validation_stats=validation_stats,
            conflicts=conflicts
        )

        logger.info(
            f"[ContextPipeline] Complete: {result.total_selected} items, "
            f"{result.total_tokens} tokens in {gather_time_ms:.1f}ms"
        )

        return result

    # ========================================================================
    # Phase 0: Gathering
    # ========================================================================

    async def _gather_all_sources(
        self,
        session_id: str,
        user_query: str,
        intent: str,
        live_ctx: Any,
        profile_id: Optional[str]
    ) -> List[ContextItem]:
        """Gather context items from all sources."""
        items = []

        # Source 1: Session state (highest priority)
        if live_ctx:
            session_item = self._gather_session_state(live_ctx)
            if session_item:
                items.append(session_item)

        # Source 2: Claims from registry
        claim_items = await self._gather_claims(
            session_id=session_id,
            user_query=user_query,
            intent=intent
        )
        items.extend(claim_items)

        # Source 3: Discovered facts from session
        if live_ctx:
            fact_items = self._gather_discovered_facts(live_ctx, intent)
            items.extend(fact_items)

        # Source 4: Long-term memories
        if profile_id:
            memory_items = await self._gather_memories(
                profile_id=profile_id,
                user_query=user_query
            )
            items.extend(memory_items)

        # Source 5: Session intelligence cache
        intel_items = await self._gather_session_intelligence(
            session_id=session_id,
            user_query=user_query,
            intent=intent
        )
        items.extend(intel_items)

        return items

    def _gather_session_state(self, live_ctx: Any) -> Optional[ContextItem]:
        """Gather session state as highest-priority context item."""
        if not live_ctx:
            return None

        try:
            # Build session state text
            parts = []

            if hasattr(live_ctx, 'preferences') and live_ctx.preferences:
                prefs_str = ", ".join(f"{k}: {v}" for k, v in live_ctx.preferences.items())
                parts.append(f"User preferences: {prefs_str}")

            if hasattr(live_ctx, 'current_topic') and live_ctx.current_topic:
                parts.append(f"Current topic: {live_ctx.current_topic}")

            if hasattr(live_ctx, 'turn_count'):
                parts.append(f"Turn: {live_ctx.turn_count}")

            # Add previous turn summary for follow-up question context
            if hasattr(live_ctx, 'last_turn_summary') and live_ctx.last_turn_summary:
                summary = live_ctx.last_turn_summary
                prev_parts = []
                if summary.get('short_summary'):
                    prev_parts.append(f"Previous turn: {summary['short_summary']}")
                if summary.get('key_findings'):
                    findings = "; ".join(summary['key_findings'][:2])
                    prev_parts.append(f"Key findings: {findings}")
                if prev_parts:
                    parts.extend(prev_parts)
                    logger.info(f"[ContextPipeline] Added previous_turn context: {summary.get('short_summary', '')[:50]}...")

            if not parts:
                return None

            content = "; ".join(parts)

            return ContextItem(
                item_id=f"session_{hashlib.md5(content.encode()).hexdigest()[:8]}",
                source="session_state",
                content=content,
                content_type="session",
                confidence=1.0,
                freshness_hours=0.0,
                source_priority=1,  # Highest priority
                is_valid=True,
                metadata={
                    "preferences": live_ctx.preferences if hasattr(live_ctx, 'preferences') else {},
                    "topic": live_ctx.current_topic if hasattr(live_ctx, 'current_topic') else None
                },
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        except Exception as e:
            logger.warning(f"[ContextPipeline] Failed to gather session state: {e}")
            return None

    async def _gather_claims(
        self,
        session_id: str,
        user_query: str,
        intent: str
    ) -> List[ContextItem]:
        """Gather claims from claim registry."""
        items = []

        if not self.claim_registry:
            return items

        try:
            # Get relevant domains for this intent
            relevant_domains = self.INTENT_DOMAINS.get(intent, ["general"])

            # Get active claims for this session
            active_claims = list(self.claim_registry.list_active_claims(session_id=session_id))

            now = datetime.now(timezone.utc)

            for claim in active_claims[:50]:  # Limit to 50 for performance
                try:
                    # Check domain relevance
                    claim_domain = claim.metadata.get("domain", "general") if claim.metadata else "general"
                    if claim_domain not in relevant_domains and "general" not in relevant_domains:
                        continue

                    # Calculate age
                    created_at = self._parse_datetime(claim.last_verified)
                    if created_at:
                        age_hours = (now - created_at).total_seconds() / 3600
                    else:
                        age_hours = 24.0  # Default if unknown

                    # Determine content type
                    content_type = "product_claim" if claim_domain in ["commerce", "shopping", "product"] else "fact"

                    # Map confidence string to float
                    confidence_map = {"low": 0.4, "medium": 0.7, "high": 0.9}
                    confidence = confidence_map.get(
                        claim.confidence.lower() if isinstance(claim.confidence, str) else "medium",
                        0.7
                    )

                    # Preserve full metadata
                    full_metadata = dict(claim.metadata) if claim.metadata else {}
                    full_metadata["claim_id"] = claim.claim_id
                    full_metadata["domain"] = claim_domain

                    items.append(ContextItem(
                        item_id=f"claim_{claim.claim_id}",
                        source="claim_registry",
                        source_id=claim.claim_id,
                        content=claim.statement,
                        content_type=content_type,
                        confidence=confidence,
                        freshness_hours=age_hours,
                        source_priority=3,
                        metadata=full_metadata,
                        timestamp=str(claim.created_at),
                        ttl_hours=self._get_ttl_for_content_type(content_type)
                    ))

                except Exception as e:
                    logger.debug(f"[ContextPipeline] Skipping malformed claim: {e}")
                    continue

            logger.debug(f"[ContextPipeline] Gathered {len(items)} claims from registry")

        except Exception as e:
            logger.warning(f"[ContextPipeline] Failed to gather claims: {e}")

        return items

    def _gather_discovered_facts(
        self,
        live_ctx: Any,
        intent: str
    ) -> List[ContextItem]:
        """Gather discovered facts from session context."""
        items = []

        if not hasattr(live_ctx, 'discovered_facts') or not live_ctx.discovered_facts:
            return items

        try:
            relevant_domains = self.INTENT_DOMAINS.get(intent, ["general"])

            for i, fact in enumerate(live_ctx.discovered_facts[:20]):  # Limit to 20
                # Handle both dict and string facts
                if isinstance(fact, dict):
                    content = fact.get("content", str(fact))
                    fact_domain = fact.get("domain", "general")
                    confidence = fact.get("confidence", 0.7)
                else:
                    content = str(fact)
                    fact_domain = "general"
                    confidence = 0.7

                # Domain filter
                if fact_domain not in relevant_domains and "general" not in relevant_domains:
                    continue

                items.append(ContextItem(
                    item_id=f"fact_{hashlib.md5(content.encode()).hexdigest()[:8]}",
                    source="discovered_fact",
                    content=content,
                    content_type="fact",
                    confidence=confidence,
                    freshness_hours=0.0,  # Session facts are fresh
                    source_priority=3,
                    metadata={"domain": fact_domain},
                    timestamp=datetime.now(timezone.utc).isoformat()
                ))

            logger.debug(f"[ContextPipeline] Gathered {len(items)} discovered facts")

        except Exception as e:
            logger.warning(f"[ContextPipeline] Failed to gather discovered facts: {e}")

        return items

    async def _gather_memories(
        self,
        profile_id: str,
        user_query: str
    ) -> List[ContextItem]:
        """Gather long-term memories for profile."""
        items = []

        # TODO: Implement memory retrieval when memory system is ready
        # For now, return empty list

        return items

    async def _gather_session_intelligence(
        self,
        session_id: str,
        user_query: str,
        intent: str
    ) -> List[ContextItem]:
        """Gather cached intelligence from session intelligence cache."""
        items = []

        try:
            from apps.services.tool_server.session_intelligence_cache import SessionIntelligenceCache

            cache = SessionIntelligenceCache(session_id)
            entries = cache.get_all_entries(include_expired=False)

            if not entries:
                return items

            now = datetime.now(timezone.utc)

            for entry in entries[:20]:  # Limit to 20 entries
                try:
                    # Calculate age
                    created_at = self._parse_datetime(entry.get("created_at"))
                    if created_at:
                        age_hours = (now - created_at).total_seconds() / 3600
                    else:
                        age_hours = 24.0

                    intel = entry.get("intelligence", {})

                    # Extract products from intelligence
                    products = intel.get("products", [])
                    for product in products[:10]:
                        name = product.get("name", "")
                        price = product.get("price", "")
                        vendor = product.get("retailer", product.get("vendor", ""))
                        url = product.get("url", "")

                        if not name:
                            continue

                        # Build claim-like content
                        content_parts = [name]
                        if vendor:
                            content_parts.append(f"at {vendor}")
                        if price:
                            content_parts.append(f"for {price}")
                        if url:
                            content_parts.append(f"- {url}")

                        content = " ".join(content_parts)

                        items.append(ContextItem(
                            item_id=f"intel_{hashlib.md5(content.encode()).hexdigest()[:8]}",
                            source="session_intel",
                            content=content,
                            content_type="product_claim",
                            confidence=0.8,
                            freshness_hours=age_hours,
                            source_priority=4,
                            metadata={
                                "product_name": name,
                                "price": price,
                                "vendor": vendor,
                                "url": url,
                                "source_query": entry.get("original_query", "")
                            },
                            timestamp=entry.get("created_at", "")
                        ))

                except Exception as e:
                    logger.debug(f"[ContextPipeline] Skipping malformed intel entry: {e}")
                    continue

            logger.debug(f"[ContextPipeline] Gathered {len(items)} items from session intelligence")

        except ImportError:
            logger.debug("[ContextPipeline] Session intelligence cache not available")
        except Exception as e:
            logger.warning(f"[ContextPipeline] Failed to gather session intelligence: {e}")

        return items

    # ========================================================================
    # Phase 1: Validation
    # ========================================================================

    def _validate_items(
        self,
        items: List[ContextItem],
        intent: str
    ) -> Tuple[List[ContextItem], Dict[str, int]]:
        """
        Validate context items.

        Checks:
        - TTL (expired items removed)
        - Confidence threshold
        - Deduplication
        """
        valid_items = []
        stats = {"expired": 0, "low_confidence": 0, "duplicates": 0}

        # Track content hashes for deduplication
        seen_hashes: Dict[str, str] = {}  # hash -> item_id

        # Determine max age based on intent
        is_transactional = intent in ["transactional", "commerce_search", "comparison", "retry"]
        max_age = (
            self.validation_config.transactional_max_age_hours
            if is_transactional
            else self.validation_config.max_age_hours
        )

        for item in items:
            # Skip session state validation (always valid)
            if item.source == "session_state":
                valid_items.append(item)
                continue

            # Check expiration
            if item.freshness_hours > max_age:
                item.is_expired = True
                stats["expired"] += 1
                continue

            # Mark stale (past soft TTL but not expired)
            soft_ttl = max_age * 0.7
            if item.freshness_hours > soft_ttl:
                item.is_stale = True

            # Check confidence
            if item.confidence < self.validation_config.min_confidence:
                stats["low_confidence"] += 1
                continue

            # Deduplication
            if self.validation_config.enable_dedup:
                content_hash = item.content_hash()
                if content_hash in seen_hashes:
                    item.duplicate_of = seen_hashes[content_hash]
                    stats["duplicates"] += 1
                    continue
                seen_hashes[content_hash] = item.item_id

            valid_items.append(item)

        return valid_items, stats

    # ========================================================================
    # Phase 2: Scoring
    # ========================================================================

    async def _score_items(
        self,
        items: List[ContextItem],
        user_query: str,
        intent: str
    ) -> List[ContextItem]:
        """
        Score and rank context items.

        Scoring formula:
        relevance = semantic_sim * 0.35 + priority * 0.20 + freshness * 0.20
                  + confidence * 0.15 + intent_alignment * 0.10
        """
        # Get query embedding
        query_embedding = None
        if self.embedding_service and hasattr(self.embedding_service, 'embed'):
            try:
                query_embedding = self.embedding_service.embed(user_query)
            except Exception as e:
                logger.debug(f"[ContextPipeline] Failed to get query embedding: {e}")

        # Determine semantic threshold based on intent
        is_transactional = intent in ["transactional", "commerce_search", "comparison", "retry"]
        min_similarity = (
            self.scoring_config.transactional_min_similarity
            if is_transactional
            else self.scoring_config.informational_min_similarity
        )

        scored_items = []

        for item in items:
            # Session state always gets max score
            if item.source == "session_state":
                item.relevance_score = 1.0
                scored_items.append(item)
                continue

            # Calculate semantic similarity
            if query_embedding is not None:
                item.semantic_similarity = await self._calculate_similarity(
                    item.content, query_embedding
                )

                # Filter by minimum similarity (except high-priority items)
                if item.semantic_similarity < min_similarity and item.source_priority > 2:
                    continue
            else:
                # Default similarity if no embedding service
                item.semantic_similarity = 0.5

            # Calculate component scores (0-1)
            semantic_score = item.semantic_similarity
            priority_score = 1.0 - (item.source_priority - 1) / 5  # Priority 1=1.0, 5=0.2
            freshness_score = max(0, 1.0 - item.freshness_hours / 168)  # 0 at 7 days
            confidence_score = item.confidence

            # Intent alignment score
            intent_domains = self.INTENT_DOMAINS.get(intent, ["general"])
            item_domain = item.metadata.get("domain", "general")
            intent_score = 1.0 if item_domain in intent_domains else 0.5

            # Calculate weighted relevance score
            item.relevance_score = (
                semantic_score * self.scoring_config.semantic_weight +
                priority_score * self.scoring_config.priority_weight +
                freshness_score * self.scoring_config.freshness_weight +
                confidence_score * self.scoring_config.confidence_weight +
                intent_score * self.scoring_config.intent_weight
            )

            scored_items.append(item)

        # Sort by relevance score (descending)
        scored_items.sort(key=lambda x: x.relevance_score, reverse=True)

        return scored_items

    async def _calculate_similarity(
        self,
        content: str,
        query_embedding: List[float]
    ) -> float:
        """Calculate semantic similarity between content and query."""
        try:
            # Check cache
            content_hash = hashlib.md5(content.encode()).hexdigest()
            if content_hash in self._embedding_cache:
                content_embedding = self._embedding_cache[content_hash]
            else:
                content_embedding = self.embedding_service.embed(content)
                if content_embedding:
                    self._embedding_cache[content_hash] = content_embedding

            if content_embedding is None:
                return 0.5

            # Cosine similarity
            dot_product = sum(a * b for a, b in zip(query_embedding, content_embedding))
            norm_a = sum(a * a for a in query_embedding) ** 0.5
            norm_b = sum(b * b for b in content_embedding) ** 0.5

            if norm_a == 0 or norm_b == 0:
                return 0.0

            return dot_product / (norm_a * norm_b)

        except Exception as e:
            logger.debug(f"[ContextPipeline] Similarity calculation failed: {e}")
            return 0.5

    # ========================================================================
    # Phase 3: Selection
    # ========================================================================

    def _select_within_budget(
        self,
        items: List[ContextItem],
        budget_tokens: int
    ) -> Tuple[List[ContextItem], int]:
        """
        Select items within token budget.

        Uses greedy selection: highest-scored items first until budget exhausted.
        Session state is always included.
        """
        selected = []
        total_tokens = 0

        for item in items:
            item_tokens = self._estimate_tokens(item.content)

            # Always include session state
            if item.source == "session_state":
                selected.append(item)
                total_tokens += item_tokens
                continue

            # Check if fits in budget
            if total_tokens + item_tokens <= budget_tokens:
                selected.append(item)
                total_tokens += item_tokens
            else:
                # Budget exhausted
                break

        return selected, total_tokens

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        # Simple estimate: ~4 chars per token
        return len(text) // 4 + 1

    # ========================================================================
    # Phase 4: Conflict Resolution
    # ========================================================================

    def _detect_conflicts(
        self,
        items: List[ContextItem]
    ) -> List[Tuple[str, str]]:
        """
        Detect conflicting claims.

        Conflicts: Same product/subject with different prices or contradictory info.
        """
        if not self.validation_config.enable_conflict_detection:
            return []

        conflicts = []

        # Group product claims by product name
        product_claims: Dict[str, List[ContextItem]] = {}

        for item in items:
            if item.content_type == "product_claim":
                product_name = item.metadata.get("product_name", "")
                if product_name:
                    # Normalize product name for comparison
                    normalized = product_name.lower().strip()[:50]
                    if normalized not in product_claims:
                        product_claims[normalized] = []
                    product_claims[normalized].append(item)

        # Check for price conflicts
        for product, claims in product_claims.items():
            if len(claims) < 2:
                continue

            prices = []
            for claim in claims:
                price_str = claim.metadata.get("price", "")
                price = self._parse_price(price_str)
                if price:
                    prices.append((claim.item_id, price))

            # If prices differ by more than 20%, flag as conflict
            if len(prices) >= 2:
                min_price = min(p[1] for p in prices)
                max_price = max(p[1] for p in prices)
                if min_price > 0 and (max_price - min_price) / min_price > 0.2:
                    # Find the two most different
                    min_item = next(p[0] for p in prices if p[1] == min_price)
                    max_item = next(p[0] for p in prices if p[1] == max_price)
                    conflicts.append((min_item, max_item))

        return conflicts

    async def _resolve_conflicts(
        self,
        items: List[ContextItem],
        conflicts: List[Tuple[str, str]],
        user_query: str
    ) -> List[ContextItem]:
        """
        Resolve conflicts using LLM to decide which claim is better.

        For each conflict, keeps the more reliable/recent claim.
        """
        if not conflicts:
            return items

        # Build conflict resolution map
        items_by_id = {item.item_id: item for item in items}
        items_to_remove = set()

        for item1_id, item2_id in conflicts:
            item1 = items_by_id.get(item1_id)
            item2 = items_by_id.get(item2_id)

            if not item1 or not item2:
                continue

            # Heuristic resolution (prefer fresher, higher confidence)
            # In future: could use LLM for more sophisticated resolution
            score1 = item1.confidence * (1 - item1.freshness_hours / 168)
            score2 = item2.confidence * (1 - item2.freshness_hours / 168)

            loser_id = item2_id if score1 >= score2 else item1_id
            items_to_remove.add(loser_id)

            # Mark the conflict
            winner = items_by_id[item1_id if loser_id == item2_id else item2_id]
            winner.conflicts_with.append(loser_id)

            logger.debug(
                f"[ContextPipeline] Resolved conflict: keeping {winner.item_id}, "
                f"removing {loser_id}"
            )

        # Filter out removed items
        return [item for item in items if item.item_id not in items_to_remove]

    # ========================================================================
    # Result Building
    # ========================================================================

    def _build_result(
        self,
        selected_items: List[ContextItem],
        raw_count: int,
        valid_count: int,
        total_tokens: int,
        gather_time_ms: float,
        validation_stats: Dict[str, int],
        conflicts: List[Tuple[str, str]]
    ) -> ContextResult:
        """Build the final ContextResult."""
        result = ContextResult(
            items=selected_items,
            total_gathered=raw_count,
            total_valid=valid_count,
            total_selected=len(selected_items),
            total_tokens=total_tokens,
            gather_time_ms=gather_time_ms,
            duplicates_removed=validation_stats.get("duplicates", 0),
            expired_removed=validation_stats.get("expired", 0),
            conflicts_detected=conflicts
        )

        # Categorize items
        for item in selected_items:
            if item.source == "session_state":
                result.session_state = item
            elif item.source == "claim_registry":
                result.claims.append(item)
            elif item.source in ["memory", "long_term_memory"]:
                result.memories.append(item)
            elif item.source == "discovered_fact":
                result.facts.append(item)
            elif item.source == "session_intel":
                result.claims.append(item)  # Treat as claims

        # Set flags
        result.has_product_claims = any(
            item.content_type == "product_claim" for item in selected_items
        )
        result.has_sufficient_data = len(result.claims) >= 3 or result.session_state is not None

        # Find freshest claim
        claim_ages = [item.freshness_hours for item in result.claims if item.freshness_hours < 999]
        if claim_ages:
            result.freshest_claim_hours = min(claim_ages)

        return result

    # ========================================================================
    # Helpers
    # ========================================================================

    def _parse_datetime(self, dt_str: Any) -> Optional[datetime]:
        """Parse datetime string to timezone-aware datetime."""
        if not dt_str:
            return None

        if isinstance(dt_str, datetime):
            if dt_str.tzinfo is None:
                return dt_str.replace(tzinfo=timezone.utc)
            return dt_str

        try:
            # Try ISO format
            dt = datetime.fromisoformat(str(dt_str).replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def _parse_price(self, price_str: str) -> Optional[float]:
        """Parse price string to float."""
        if not price_str:
            return None

        try:
            import re
            # Extract numeric value
            match = re.search(r'[\d,]+(?:\.\d{2})?', str(price_str).replace(",", ""))
            if match:
                return float(match.group().replace(",", ""))
        except (ValueError, TypeError):
            pass

        return None

    def _get_ttl_for_content_type(self, content_type: str) -> float:
        """Get TTL in hours for content type."""
        ttl_map = {
            "product_claim": 72,    # 3 days for prices
            "fact": 168,            # 7 days for facts
            "preference": 720,      # 30 days for preferences
            "memory": 2160,         # 90 days for memories
            "session": 24,          # 1 day for session data
        }
        return ttl_map.get(content_type, 168)


# ============================================================================
# Factory Function
# ============================================================================

def get_context_pipeline(
    claim_registry: Any = None,
    session_context_manager: Any = None
) -> ContextPipeline:
    """
    Factory function to create a ContextPipeline with default configuration.

    Args:
        claim_registry: ClaimRegistry instance
        session_context_manager: SessionContextManager instance

    Returns:
        Configured ContextPipeline instance
    """
    # Try to get embedding service
    embedding_service = None
    try:
        from apps.services.tool_server.shared_state.embedding_service import EMBEDDING_SERVICE
        if EMBEDDING_SERVICE.is_available():
            embedding_service = EMBEDDING_SERVICE
    except ImportError:
        pass

    return ContextPipeline(
        claim_registry=claim_registry,
        session_context_manager=session_context_manager,
        embedding_service=embedding_service
    )
