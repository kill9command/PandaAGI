"""
apps/services/tool_server/intelligence_retriever.py

Unified Knowledge Retriever - Searches ALL cached knowledge sources.

DEPRECATION NOTICE (2024-12-02):
================================
This module is being replaced by lib/gateway/context_pipeline.py which provides:
- Single unified context gathering path
- Validation phase (TTL, confidence, deduplication)
- Multi-factor relevance scoring
- Budget-aware selection
- Conflict detection and resolution

To enable the new pipeline, set USE_CONTEXT_PIPELINE=true in environment.
This module will be removed in a future version.

Legacy behavior:
This runs during Phase 1 (Context Gathering) BEFORE the Planner decides what tools to call.
It writes cached_knowledge.md so the Planner can make informed decisions about
whether research is needed.

Searches:
1. Session Intelligence Cache - products, retailers, specs from previous research
2. Tool Cache - raw research results (cross-session)
3. Claims Registry - verified facts with evidence and TTL

Created: 2024-11-30
Deprecated: 2024-12-02
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field

from apps.services.tool_server.session_intelligence_cache import SessionIntelligenceCache, CACHE_DIR, _parse_datetime_aware
from apps.services.tool_server.shared_state.embedding_service import EMBEDDING_SERVICE

logger = logging.getLogger(__name__)


@dataclass
class RetrievedProduct:
    """A product found in cached intelligence."""
    name: str
    price: Optional[float]
    price_str: str
    retailer: str
    url: Optional[str]
    specs: Dict[str, Any] = field(default_factory=dict)
    source_query: str = ""
    age_hours: float = 0.0


@dataclass
class RetrievedClaim:
    """A verified claim from the claims registry."""
    claim_id: str
    statement: str
    confidence: str  # "high", "medium", "low"
    evidence: List[str]
    age_hours: float
    expires_in_hours: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievedKnowledge:
    """Unified knowledge from all cache sources."""
    # Products from intelligence cache
    products: List[RetrievedProduct] = field(default_factory=list)
    retailers: List[str] = field(default_factory=list)
    price_range: Dict[str, float] = field(default_factory=dict)
    specs_found: Dict[str, Any] = field(default_factory=dict)

    # Claims from claims registry
    claims: List[RetrievedClaim] = field(default_factory=list)

    # Metadata
    sources_searched: int = 0
    freshest_data_hours: float = 999.0
    oldest_data_hours: float = 0.0
    query_coverage: float = 0.0  # 0-1, how well cached data matches query

    def has_sufficient_products(self, min_count: int = 5) -> bool:
        """Check if we have enough products to potentially answer."""
        return len(self.products) >= min_count

    def has_fresh_prices(self, max_age_hours: float = 6.0) -> bool:
        """Check if price data is fresh enough for transactional queries."""
        return self.freshest_data_hours <= max_age_hours

    def has_relevant_claims(self, min_count: int = 2) -> bool:
        """Check if we have relevant verified claims."""
        return len(self.claims) >= min_count

    def get_matching_products(self, budget: Optional[float] = None) -> List[RetrievedProduct]:
        """Filter products by budget constraint."""
        if budget is None:
            return self.products
        return [p for p in self.products if p.price and p.price <= budget]

    def get_high_confidence_claims(self) -> List[RetrievedClaim]:
        """Get claims with high confidence."""
        return [c for c in self.claims if c.confidence == "high"]


# Backward compatibility alias
RetrievedIntelligence = RetrievedKnowledge


class KnowledgeRetriever:
    """
    Unified Knowledge Retriever - searches ALL cached knowledge sources.

    This is called during Phase 1 context gathering to:
    1. Search session intelligence cache (products, retailers, specs)
    2. Search tool cache for previous research results
    3. Search claims registry for verified facts
    4. Aggregate and score relevance to current query
    5. Provide data for cached_knowledge.md document
    """

    def __init__(self, claim_registry=None):
        self.cache_dir = CACHE_DIR
        self.claim_registry = claim_registry

    def set_claim_registry(self, claim_registry):
        """Set the claim registry (for lazy initialization)."""
        self.claim_registry = claim_registry

    async def retrieve(
        self,
        query: str,
        session_id: str,
        intent: str,
        user_constraints: Optional[Dict] = None,
        min_similarity: float = 0.65
    ) -> RetrievedKnowledge:
        """
        Search ALL knowledge sources for relevant cached data.

        Args:
            query: Current user query
            session_id: Session ID for session-scoped caches
            intent: Query intent (transactional, informational, etc.)
            user_constraints: User preferences (budget, etc.)
            min_similarity: Minimum semantic similarity threshold

        Returns:
            RetrievedKnowledge with aggregated products, claims, and metadata
        """
        # DEPRECATION WARNING: This module is being replaced by ContextPipeline
        # Set USE_CONTEXT_PIPELINE=true to use the new unified pipeline
        import warnings
        warnings.warn(
            "IntelligenceRetriever is deprecated. Use lib/gateway/context_pipeline.py instead. "
            "Set USE_CONTEXT_PIPELINE=true to enable the new pipeline.",
            DeprecationWarning,
            stacklevel=2
        )

        result = RetrievedKnowledge()
        user_constraints = user_constraints or {}

        logger.info(f"[KnowledgeRetriever] Searching all cached knowledge for: {query[:60]}...")

        # Step 1: Search session intelligence cache
        session_intel = await self._search_session_intelligence(
            query, session_id, min_similarity
        )

        # Step 2: Search tool cache for research results
        tool_intel = await self._search_tool_cache(
            query, intent, min_similarity
        )

        # Step 3: Search claims registry
        claims = await self._search_claims(
            query, session_id
        )
        result.claims = claims

        # Step 4: Aggregate results
        all_products = []
        all_retailers = set()
        min_age = 999.0
        max_age = 0.0

        # Process session intelligence
        for entry in session_intel:
            age_hours = entry.get("age_hours", 0)
            min_age = min(min_age, age_hours)
            max_age = max(max_age, age_hours)
            result.sources_searched += 1

            intel = entry.get("intelligence", {})

            # Extract retailers
            retailers = intel.get("retailers", {})
            all_retailers.update(retailers.keys())

            # Extract products from various fields
            products = self._extract_products_from_intelligence(intel, entry)
            all_products.extend(products)

            # Extract price range
            if "price_range" in intel:
                pr = intel["price_range"]
                if pr.get("min"):
                    result.price_range["min"] = min(
                        result.price_range.get("min", float("inf")),
                        pr["min"]
                    )
                if pr.get("max"):
                    result.price_range["max"] = max(
                        result.price_range.get("max", 0),
                        pr["max"]
                    )

            # Extract specs
            if "specs_discovered" in intel:
                result.specs_found.update(intel["specs_discovered"])

        # Process tool cache results
        for entry in tool_intel:
            age_hours = entry.get("age_hours", 0)
            min_age = min(min_age, age_hours)
            max_age = max(max_age, age_hours)
            result.sources_searched += 1

            # Tool cache has raw research results
            research_result = entry.get("result", {})
            products = self._extract_products_from_research(research_result, entry)
            all_products.extend(products)

        # Deduplicate products by name similarity
        result.products = self._deduplicate_products(all_products)
        result.retailers = list(all_retailers)
        result.freshest_data_hours = min_age if min_age < 999 else 0
        result.oldest_data_hours = max_age

        # Calculate query coverage score
        result.query_coverage = await self._calculate_coverage(
            query, result, user_constraints
        )

        logger.info(
            f"[KnowledgeRetriever] Found {len(result.products)} products, {len(result.claims)} claims "
            f"from {result.sources_searched} sources (freshest: {result.freshest_data_hours:.1f}h)"
        )

        return result

    async def _search_claims(
        self,
        query: str,
        session_id: str,
        min_similarity: float = 0.5
    ) -> List[RetrievedClaim]:
        """
        Search claims registry for relevant verified facts.

        Uses semantic similarity to filter claims to those relevant to the query.
        """
        claims = []

        if not self.claim_registry:
            logger.debug(f"[KnowledgeRetriever] No claim registry available")
            return claims

        try:
            # Get active claims for this session
            active_claims = list(self.claim_registry.list_active_claims(session_id=session_id))

            now = datetime.now(timezone.utc)

            # Get query embedding for semantic filtering
            query_embedding = None
            if EMBEDDING_SERVICE.is_available():
                query_embedding = EMBEDDING_SERVICE.embed(query)

            for claim in active_claims:
                try:
                    # Check if expired
                    expires_at = _parse_datetime_aware(claim.expires_at)
                    if expires_at < now:
                        continue

                    # Semantic relevance filtering
                    if query_embedding is not None:
                        claim_embedding = EMBEDDING_SERVICE.embed(claim.statement)
                        if claim_embedding is not None:
                            similarity = self._cosine_similarity(query_embedding, claim_embedding)
                            if similarity < min_similarity:
                                continue  # Skip irrelevant claims

                    # Calculate age and time remaining
                    created_at = _parse_datetime_aware(claim.last_verified)
                    age_hours = (now - created_at).total_seconds() / 3600
                    expires_in_hours = (expires_at - now).total_seconds() / 3600

                    claims.append(RetrievedClaim(
                        claim_id=claim.claim_id,
                        statement=claim.statement,
                        confidence=claim.confidence,
                        evidence=list(claim.evidence)[:3],  # Limit evidence
                        age_hours=age_hours,
                        expires_in_hours=expires_in_hours,
                        metadata=dict(claim.metadata) if claim.metadata else {}
                    ))
                except Exception as e:
                    logger.debug(f"[KnowledgeRetriever] Skipping malformed claim: {e}")
                    continue

            logger.debug(f"[KnowledgeRetriever] Found {len(claims)} relevant claims (filtered from {len(active_claims)})")

        except Exception as e:
            logger.warning(f"[KnowledgeRetriever] Claims search failed: {e}")

        return claims

    async def _search_session_intelligence(
        self,
        query: str,
        session_id: str,
        min_similarity: float
    ) -> List[Dict]:
        """Search session-scoped intelligence cache."""
        results = []

        try:
            cache = SessionIntelligenceCache(session_id)
            entries = cache.get_all_entries(include_expired=False)

            if not entries:
                logger.debug(f"[IntelRetriever] No cached entries for session {session_id}")
                return results

            # Get query embedding for semantic search
            query_embedding = None
            if EMBEDDING_SERVICE.is_available():
                query_embedding = EMBEDDING_SERVICE.embed(query)

            now = datetime.now(timezone.utc)

            for entry in entries:
                # Note: get_all_entries(include_expired=False) already filters expired entries

                # Calculate age
                try:
                    created_at = _parse_datetime_aware(entry["created_at"])
                    age_hours = (now - created_at).total_seconds() / 3600
                except (KeyError, ValueError):
                    age_hours = 24  # Assume old if unknown

                # Semantic similarity check
                similarity = 1.0  # Default if no embedding
                if query_embedding is not None:
                    original_query = entry.get("original_query", "")
                    if original_query:
                        cached_embedding = EMBEDDING_SERVICE.embed(original_query)
                        if cached_embedding is not None:
                            similarity = self._cosine_similarity(query_embedding, cached_embedding)

                if similarity >= min_similarity:
                    results.append({
                        **entry,
                        "age_hours": age_hours,
                        "similarity": similarity
                    })

            # Sort by relevance (similarity) and freshness
            results.sort(key=lambda x: (-x["similarity"], x["age_hours"]))

            logger.debug(f"[IntelRetriever] Session cache: {len(results)} relevant entries")

        except Exception as e:
            logger.warning(f"[IntelRetriever] Session cache search failed: {e}")

        return results

    async def _search_tool_cache(
        self,
        query: str,
        intent: str,
        min_similarity: float
    ) -> List[Dict]:
        """Search tool cache for previous research results."""
        results = []

        try:
            from apps.services.tool_server.shared_state.tool_cache import TOOL_CACHE

            # Try semantic search on tool cache
            cached = await TOOL_CACHE.get("internet.research", {
                "query": query,
                "intent": intent
            })

            if cached:
                results.append({
                    "result": cached["result"],
                    "age_hours": cached.get("age_hours", 0),
                    "similarity": 1.0  # Exact or semantic match
                })
                logger.debug(f"[IntelRetriever] Tool cache hit: age={cached.get('age_hours', 0):.1f}h")

        except Exception as e:
            logger.warning(f"[IntelRetriever] Tool cache search failed: {e}")

        return results

    def _extract_products_from_intelligence(
        self,
        intel: Dict,
        entry: Dict
    ) -> List[RetrievedProduct]:
        """Extract products from intelligence dict."""
        products = []
        age_hours = entry.get("age_hours", 0)
        source_query = entry.get("original_query", "")

        # Products might be in various places
        # Check forum_recommendations
        forum_recs = intel.get("forum_recommendations", [])
        for rec in forum_recs:
            if isinstance(rec, dict) and rec.get("name"):
                products.append(RetrievedProduct(
                    name=rec.get("name", ""),
                    price=rec.get("price"),
                    price_str=rec.get("price_str", ""),
                    retailer=rec.get("retailer", "unknown"),
                    url=rec.get("url"),
                    specs=rec.get("specs", {}),
                    source_query=source_query,
                    age_hours=age_hours
                ))

        # Check recommended_brands (less specific)
        brands = intel.get("recommended_brands", [])
        # Don't create products from just brands - they're not specific enough

        return products

    def _extract_products_from_research(
        self,
        research_result: Dict,
        entry: Dict
    ) -> List[RetrievedProduct]:
        """Extract products from research tool result."""
        products = []
        age_hours = entry.get("age_hours", 0)

        # Research results have synthesis.products or vendor_data
        synthesis = research_result.get("synthesis", {})

        # Check top_products in synthesis
        top_products = synthesis.get("top_products", [])
        for prod in top_products:
            if isinstance(prod, dict):
                price = prod.get("price")
                if isinstance(price, str):
                    # Try to parse price string
                    try:
                        price = float(price.replace("$", "").replace(",", ""))
                    except (ValueError, AttributeError):
                        price = None

                products.append(RetrievedProduct(
                    name=prod.get("name", prod.get("title", "")),
                    price=price,
                    price_str=prod.get("price_str", str(prod.get("price", ""))),
                    retailer=prod.get("retailer", prod.get("vendor", "unknown")),
                    url=prod.get("url", prod.get("link")),
                    specs=prod.get("specs", {}),
                    source_query=research_result.get("query", ""),
                    age_hours=age_hours
                ))

        # Check vendor_data for more products
        vendor_data = research_result.get("vendor_data", {})
        for vendor, data in vendor_data.items():
            vendor_products = data.get("products", [])
            for prod in vendor_products:
                if isinstance(prod, dict):
                    price = prod.get("price")
                    if isinstance(price, str):
                        try:
                            price = float(price.replace("$", "").replace(",", ""))
                        except (ValueError, AttributeError):
                            price = None

                    products.append(RetrievedProduct(
                        name=prod.get("name", prod.get("title", "")),
                        price=price,
                        price_str=prod.get("price_str", str(prod.get("price", ""))),
                        retailer=vendor,
                        url=prod.get("url"),
                        specs=prod.get("specs", {}),
                        source_query=research_result.get("query", ""),
                        age_hours=age_hours
                    ))

        return products

    def _deduplicate_products(
        self,
        products: List[RetrievedProduct]
    ) -> List[RetrievedProduct]:
        """Deduplicate products, keeping freshest version."""
        seen = {}  # name_key -> product

        for prod in products:
            # Normalize name for comparison
            name_key = prod.name.lower().strip()[:50]

            if name_key not in seen or prod.age_hours < seen[name_key].age_hours:
                seen[name_key] = prod

        # Sort by price (cheapest first) if prices available
        result = list(seen.values())
        result.sort(key=lambda p: (p.price if p.price else float("inf")))

        return result

    async def _calculate_coverage(
        self,
        query: str,
        result: RetrievedKnowledge,
        user_constraints: Dict
    ) -> float:
        """
        Calculate how well cached data covers the query needs.

        Returns 0-1 score:
        - 1.0 = Fully covered, can answer without research
        - 0.5 = Partially covered, might need targeted research
        - 0.0 = Not covered, need full research
        """
        score = 0.0

        # Factor 1: Product count (up to 0.3)
        product_count = len(result.products)
        if product_count >= 10:
            score += 0.3
        elif product_count >= 5:
            score += 0.25
        elif product_count >= 3:
            score += 0.15
        elif product_count >= 1:
            score += 0.1

        # Factor 2: Data freshness (up to 0.25)
        if result.freshest_data_hours <= 1:
            score += 0.25
        elif result.freshest_data_hours <= 6:
            score += 0.2
        elif result.freshest_data_hours <= 12:
            score += 0.1

        # Factor 3: Budget match (up to 0.15)
        budget = user_constraints.get("budget") or user_constraints.get("max_price")
        if budget:
            try:
                # Handle currency symbols and commas (e.g., "$1,500" -> 1500.0)
                budget_val = float(str(budget).replace("$", "").replace(",", "").strip())
                matching = result.get_matching_products(budget_val)
                if len(matching) >= 3:
                    score += 0.15
                elif len(matching) >= 1:
                    score += 0.1
            except (ValueError, AttributeError):
                # Invalid budget format, skip budget matching
                score += 0.1
        else:
            score += 0.1  # No budget constraint

        # Factor 4: Retailer diversity (up to 0.1)
        if len(result.retailers) >= 3:
            score += 0.1
        elif len(result.retailers) >= 2:
            score += 0.05

        # Factor 5: Verified claims (up to 0.2)
        claim_count = len(result.claims)
        high_conf_claims = len(result.get_high_confidence_claims())
        if high_conf_claims >= 3:
            score += 0.2
        elif claim_count >= 5:
            score += 0.15
        elif claim_count >= 2:
            score += 0.1
        elif claim_count >= 1:
            score += 0.05

        return min(score, 1.0)

    def _cosine_similarity(self, vec1, vec2) -> float:
        """Calculate cosine similarity between two vectors."""
        import numpy as np

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))


# Global instance
KNOWLEDGE_RETRIEVER = KnowledgeRetriever()

# Backward compatibility alias
IntelligenceRetriever = KnowledgeRetriever
INTELLIGENCE_RETRIEVER = KNOWLEDGE_RETRIEVER


def get_knowledge_retriever() -> KnowledgeRetriever:
    """Get the global knowledge retriever instance."""
    return KNOWLEDGE_RETRIEVER


def get_intelligence_retriever() -> KnowledgeRetriever:
    """Backward compatibility alias for get_knowledge_retriever."""
    return KNOWLEDGE_RETRIEVER
