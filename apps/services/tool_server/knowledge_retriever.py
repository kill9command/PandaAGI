"""
Knowledge Retriever - Unified knowledge access for research queries.

Retrieves relevant knowledge from session topics and claims to:
1. Inform Phase 1/2 skip decisions
2. Inject context into research execution
3. Provide knowledge context to planning and coordination

Created: 2025-12-02
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from apps.services.tool_server.shared_state.claims import ClaimRegistry, ClaimRow
from apps.services.tool_server.shared_state.topic_index import TopicIndex, Topic, TopicMatch, get_topic_index
from apps.services.tool_server.shared_state.claim_types import ClaimType, PHASE1_CLAIM_TYPES, REUSABLE_CLAIM_TYPES

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path("panda_system_docs/shared_state/claims.db")


@dataclass
class KnowledgeContext:
    """Aggregated knowledge relevant to a query."""

    # Matched topics
    matched_topics: List[TopicMatch] = field(default_factory=list)
    best_match_similarity: float = 0.0
    best_match_topic_name: str = ""

    # Aggregated knowledge
    retailers: List[str] = field(default_factory=list)
    price_expectations: Dict[str, float] = field(default_factory=dict)
    buying_tips: List[str] = field(default_factory=list)
    key_specs: List[str] = field(default_factory=list)

    # Raw claims by type
    claims_by_type: Dict[str, List[ClaimRow]] = field(default_factory=dict)
    total_claims: int = 0

    # Freshness metrics
    oldest_claim_age_hours: float = 0.0
    average_confidence: float = 0.0

    # Phase decision
    phase1_skip_recommended: bool = False
    phase1_skip_reason: str = ""
    knowledge_completeness: float = 0.0  # 0.0 - 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "matched_topics": [
                {
                    "topic_name": tm.topic.topic_name,
                    "topic_slug": tm.topic.topic_slug,
                    "similarity": tm.similarity,
                    "claim_count": tm.claim_count,
                }
                for tm in self.matched_topics
            ],
            "best_match_similarity": self.best_match_similarity,
            "best_match_topic_name": self.best_match_topic_name,
            "retailers": self.retailers,
            "price_expectations": self.price_expectations,
            "buying_tips": self.buying_tips[:5],  # Limit for serialization
            "key_specs": self.key_specs[:10],
            "total_claims": self.total_claims,
            "knowledge_completeness": self.knowledge_completeness,
            "phase1_skip_recommended": self.phase1_skip_recommended,
            "phase1_skip_reason": self.phase1_skip_reason,
        }


@dataclass
class Phase1Recommendation:
    """Recommendation for Phase 1 execution."""
    skip: bool
    reason: str
    confidence: float  # How confident we are in this recommendation
    missing_knowledge: List[str] = field(default_factory=list)


class KnowledgeRetriever:
    """
    Retrieves and aggregates knowledge for research queries.

    Usage:
        retriever = KnowledgeRetriever(session_id)
        context = await retriever.retrieve_for_query("laptop with rtx 4070")

        if context.phase1_skip_recommended:
            # Skip Phase 1, use context.retailers for Phase 2
            pass
    """

    # Thresholds (LOWERED for common categories - see _recommend_phase1)
    MIN_SIMILARITY_THRESHOLD = 0.70  # Minimum topic match similarity (was 0.75)
    KNOWLEDGE_COMPLETE_THRESHOLD = 0.5  # When to skip Phase 1 (was 0.7)
    FRESHNESS_WEIGHT = 0.3  # How much freshness affects completeness

    # Common product categories that don't need extensive Phase 1 research
    COMMON_CATEGORIES = ["laptop", "monitor", "keyboard", "mouse", "phone", "tablet", "tv", "camera", "headphones"]

    def __init__(self, session_id: str, db_path: Optional[Path] = None):
        """
        Initialize KnowledgeRetriever for a session.

        Args:
            session_id: Session to retrieve knowledge for
            db_path: Optional database path (defaults to claims.db)
        """
        self.session_id = session_id
        self.db_path = db_path or DEFAULT_DB_PATH

        self._topic_index: Optional[TopicIndex] = None
        self._claim_registry: Optional[ClaimRegistry] = None
        self._embedding_service = None
        self._retailer_tokens: Optional[List[str]] = None

    @property
    def topic_index(self) -> TopicIndex:
        """Lazy-load topic index."""
        if self._topic_index is None:
            self._topic_index = get_topic_index(self.db_path)
        return self._topic_index

    @property
    def claim_registry(self) -> ClaimRegistry:
        """Lazy-load claim registry."""
        if self._claim_registry is None:
            from apps.services.tool_server.shared_state.claims import get_claim_registry
            self._claim_registry = get_claim_registry()
        return self._claim_registry

    def _get_retailer_tokens(self) -> List[str]:
        """Build retailer tokens from VendorRegistry (learned, not hardcoded)."""
        if self._retailer_tokens is not None:
            return self._retailer_tokens

        tokens = set()
        try:
            from apps.services.tool_server.shared_state.vendor_registry import get_vendor_registry
            registry = get_vendor_registry()
            for vendor in registry.get_all():
                if vendor.domain:
                    base = vendor.domain.split(".")[0].lower()
                    if base:
                        tokens.add(base)
                if vendor.name:
                    name = vendor.name.lower().strip()
                    if name:
                        tokens.add(name)
                        tokens.add(name.replace(" ", ""))
        except Exception:
            pass

        self._retailer_tokens = sorted(tokens)
        return self._retailer_tokens

    def _extract_domains_from_text(self, text: str) -> List[str]:
        """Extract domain-like tokens from text."""
        domains = []
        for match in re.findall(r"(?:https?://)?([a-z0-9.-]+\.[a-z]{2,})", text.lower()):
            domain = match.strip(".")
            if domain.startswith("www."):
                domain = domain[4:]
            domains.append(domain)
        return domains

    @property
    def embedding_service(self):
        """Lazy-load embedding service."""
        if self._embedding_service is None:
            from apps.services.tool_server.shared_state.embedding_service import EmbeddingService
            self._embedding_service = EmbeddingService()
        return self._embedding_service

    async def retrieve_for_query(
        self,
        query: str,
        min_similarity: float = None,
        include_ancestors: bool = True,
        max_topics: int = 5
    ) -> KnowledgeContext:
        """
        Retrieve all relevant knowledge for a query.

        Args:
            query: User's research query
            min_similarity: Minimum topic similarity (default: 0.70)
            include_ancestors: Whether to include parent topic knowledge
            max_topics: Maximum number of topics to retrieve

        Returns:
            KnowledgeContext with aggregated knowledge and Phase 1 recommendation
        """
        min_similarity = min_similarity or self.MIN_SIMILARITY_THRESHOLD

        logger.info(f"[KnowledgeRetriever] Retrieving knowledge for: {query[:60]}...")

        # Step 1: Find matching topics via semantic search
        matched_topics = self.topic_index.search_by_query(
            query=query,
            session_id=self.session_id,
            min_similarity=min_similarity,
            limit=max_topics,
        )

        logger.info(f"[KnowledgeRetriever] Found {len(matched_topics)} matching topics")

        if not matched_topics:
            return KnowledgeContext(
                phase1_skip_recommended=False,
                phase1_skip_reason="No relevant topics found in session knowledge"
            )

        # Step 2: Collect all relevant topic IDs (including ancestors)
        all_topic_ids: Set[str] = set()
        for topic_match in matched_topics:
            all_topic_ids.add(topic_match.topic.topic_id)
            if include_ancestors:
                ancestor_ids = self.topic_index.get_ancestor_ids(topic_match.topic.topic_id)
                all_topic_ids.update(ancestor_ids)

        # Step 3: Retrieve claims for all topics
        claims = self.claim_registry.get_claims_for_topics(
            topic_ids=list(all_topic_ids),
            session_id=self.session_id,
            exclude_expired=True,
        )

        logger.info(f"[KnowledgeRetriever] Retrieved {len(claims)} claims from {len(all_topic_ids)} topics")

        # Step 4: Aggregate knowledge
        context = self._aggregate_knowledge(matched_topics, claims)

        # Step 5: Determine Phase 1 recommendation
        recommendation = self._recommend_phase1(context)
        context.phase1_skip_recommended = recommendation.skip
        context.phase1_skip_reason = recommendation.reason

        logger.info(
            f"[KnowledgeRetriever] Phase 1 recommendation: "
            f"{'SKIP' if recommendation.skip else 'RUN'} - {recommendation.reason}"
        )

        return context

    def _aggregate_knowledge(
        self,
        topics: List[TopicMatch],
        claims: List[ClaimRow]
    ) -> KnowledgeContext:
        """Aggregate claims into knowledge context."""

        context = KnowledgeContext(
            matched_topics=topics,
            best_match_similarity=topics[0].similarity if topics else 0.0,
            best_match_topic_name=topics[0].topic.topic_name if topics else "",
            total_claims=len(claims),
        )

        # Group claims by type
        claims_by_type: Dict[str, List[ClaimRow]] = {}
        retailers: Set[str] = set()
        tips: List[str] = []
        specs: Set[str] = set()
        prices: List[str] = []
        confidences: List[float] = []

        for claim in claims:
            claim_type = claim.metadata.get("claim_type") or "general"

            if claim_type not in claims_by_type:
                claims_by_type[claim_type] = []
            claims_by_type[claim_type].append(claim)

            confidences.append(self._confidence_to_float(claim.confidence))

            # Extract specific knowledge based on type
            if claim_type == ClaimType.RETAILER.value:
                retailers.update(self._extract_retailers(claim.statement))
            elif claim_type == ClaimType.BUYING_TIP.value:
                tips.append(claim.statement)
            elif claim_type == ClaimType.SPEC_INFO.value:
                specs.add(claim.statement)
            elif claim_type in (ClaimType.PRICE.value, ClaimType.MARKET_INFO.value):
                prices.append(claim.statement)

        # Also get retailers from topic summaries
        for topic_match in topics:
            retailers.update(topic_match.topic.retailers)
            specs.update(topic_match.topic.key_specs)

            # Get inherited knowledge
            if topic_match.inherited_knowledge:
                retailers.update(topic_match.inherited_knowledge.get("retailers", []))
                specs.update(topic_match.inherited_knowledge.get("key_specs", []))

        context.claims_by_type = claims_by_type
        context.retailers = list(retailers)
        context.buying_tips = tips[:10]  # Limit tips
        context.key_specs = list(specs)[:20]
        context.average_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # Extract price expectations
        context.price_expectations = self._extract_price_range(prices, topics)

        # Calculate completeness
        context.knowledge_completeness = self._calculate_completeness(context)

        return context

    def _recommend_phase1(self, context: KnowledgeContext) -> Phase1Recommendation:
        """Determine whether to skip Phase 1 based on knowledge completeness."""

        missing: List[str] = []

        # Check essential knowledge
        has_retailers = len(context.retailers) >= 2
        has_market_context = bool(context.price_expectations) or len(context.key_specs) >= 2
        has_sufficient_claims = context.total_claims >= 3

        if not has_retailers:
            missing.append("retailer knowledge")
        if not has_market_context:
            missing.append("market context (prices/specs)")

        # Calculate skip confidence
        completeness = context.knowledge_completeness
        similarity = context.best_match_similarity

        # NEW: Check if this is a common category (more aggressive skip)
        topic_name_lower = context.best_match_topic_name.lower()
        is_common_category = any(cat in topic_name_lower for cat in self.COMMON_CATEGORIES)

        # Decision matrix (lowered thresholds, especially for common categories)
        if is_common_category and similarity >= 0.70:
            # Common categories: Skip Phase 1 with lower threshold
            return Phase1Recommendation(
                skip=True,
                reason=f"Common category '{topic_name_lower}' with topic match ({similarity:.0%}) - skipping Phase 1",
                confidence=0.85
            )
        elif completeness >= self.KNOWLEDGE_COMPLETE_THRESHOLD and similarity >= 0.80:
            # Good match with decent completeness (lowered from 0.85)
            return Phase1Recommendation(
                skip=True,
                reason=f"Strong topic match ({similarity:.0%}) with knowledge ({completeness:.0%})",
                confidence=0.9
            )
        elif completeness >= 0.4 and similarity >= 0.75 and has_retailers:
            # Lower threshold when we have retailers (lowered from 0.5/0.80)
            return Phase1Recommendation(
                skip=True,
                reason=f"Good topic match ({similarity:.0%}) with retailer knowledge available",
                confidence=0.75
            )
        elif has_retailers and has_sufficient_claims:
            return Phase1Recommendation(
                skip=True,
                reason="Sufficient accumulated knowledge from related queries",
                confidence=0.6,
                missing_knowledge=missing
            )
        else:
            reason = f"Insufficient knowledge"
            if missing:
                reason += f": missing {', '.join(missing)}"
            else:
                reason += ": low topic coverage"
            return Phase1Recommendation(
                skip=False,
                reason=reason,
                confidence=0.8,
                missing_knowledge=missing
            )

    def _calculate_completeness(self, context: KnowledgeContext) -> float:
        """Calculate knowledge completeness score (0.0 - 1.0)."""

        scores: List[float] = []

        # Retailer coverage (0-0.3)
        retailer_score = min(len(context.retailers) / 3, 1.0) * 0.3
        scores.append(retailer_score)

        # Market context (0-0.3)
        has_prices = bool(context.price_expectations)
        has_specs = len(context.key_specs) >= 2
        market_score = (0.15 if has_prices else 0) + (0.15 if has_specs else 0)
        scores.append(market_score)

        # Claim volume (0-0.2)
        claim_score = min(context.total_claims / 10, 1.0) * 0.2
        scores.append(claim_score)

        # Confidence (0-0.2)
        confidence_score = context.average_confidence * 0.2
        scores.append(confidence_score)

        return sum(scores)

    def _confidence_to_float(self, confidence: str) -> float:
        """Convert confidence string to float."""
        if isinstance(confidence, (int, float)):
            return float(confidence)
        mapping = {"HIGH": 0.9, "MEDIUM": 0.7, "LOW": 0.5}
        return mapping.get(confidence.upper(), 0.6) if isinstance(confidence, str) else 0.6

    def _extract_retailers(self, statement: str) -> List[str]:
        """Extract retailer names from a statement."""
        found: List[str] = []
        statement_lower = statement.lower()

        for retailer in self._get_retailer_tokens():
            if retailer in statement_lower:
                normalized = retailer.replace(" ", "").replace("&", "and")
                if normalized not in found:
                    found.append(normalized)

        for domain in self._extract_domains_from_text(statement_lower):
            base = domain.split(".")[0]
            normalized = base.replace(" ", "").replace("&", "and")
            if normalized and normalized not in found:
                found.append(normalized)

        return found

    def _extract_price_range(
        self,
        price_statements: List[str],
        topics: List[TopicMatch]
    ) -> Dict[str, float]:
        """Extract price range from statements and topics."""
        prices: List[float] = []

        # Extract from statements
        for stmt in price_statements:
            matches = re.findall(r'\$[\d,]+(?:\.\d{2})?', stmt)
            for match in matches:
                try:
                    price = float(match.replace('$', '').replace(',', ''))
                    if price > 0:
                        prices.append(price)
                except ValueError:
                    pass

        # Extract from topic summaries
        for topic_match in topics:
            pr = topic_match.topic.price_range
            if pr:
                if 'min' in pr and pr['min'] > 0:
                    prices.append(pr['min'])
                if 'max' in pr and pr['max'] > 0:
                    prices.append(pr['max'])

            # Also from inherited knowledge
            inherited_pr = topic_match.inherited_knowledge.get("price_range", {})
            if inherited_pr:
                if 'min' in inherited_pr and inherited_pr['min'] > 0:
                    prices.append(inherited_pr['min'])
                if 'max' in inherited_pr and inherited_pr['max'] > 0:
                    prices.append(inherited_pr['max'])

        if not prices:
            return {}

        return {
            "min": min(prices),
            "max": max(prices),
            "typical": sum(prices) / len(prices)
        }


# Module-level singleton cache
_retriever_cache: Dict[str, KnowledgeRetriever] = {}


def get_knowledge_retriever(session_id: str, db_path: Optional[Path] = None) -> KnowledgeRetriever:
    """
    Get or create knowledge retriever for session.

    Args:
        session_id: Session identifier
        db_path: Optional database path

    Returns:
        KnowledgeRetriever instance
    """
    cache_key = f"{session_id}:{db_path or 'default'}"

    if cache_key not in _retriever_cache:
        _retriever_cache[cache_key] = KnowledgeRetriever(session_id, db_path)

    return _retriever_cache[cache_key]


def clear_retriever_cache() -> None:
    """Clear the retriever cache (useful for testing)."""
    _retriever_cache.clear()
