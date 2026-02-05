"""
Claim Type Categories for Session Knowledge System.

Categorizes claims by their reusability and TTL characteristics.
Used for intelligent Phase 1 skip decisions and knowledge filtering.

Created: 2025-12-02
"""

from enum import Enum
from typing import Set


class ClaimType(str, Enum):
    """
    Categories of knowledge claims with associated TTLs.

    Phase 1 Intelligence (long TTL, high reuse):
    - RETAILER: Which stores sell this product category
    - MARKET_INFO: Price ranges, trends, general market knowledge
    - BUYING_TIP: Advice, warnings, recommendations
    - SPEC_INFO: Technical specifications, compatibility

    Phase 2 Findings (short TTL, query-specific):
    - PRODUCT: Specific product found
    - PRICE: Current price observation
    - AVAILABILITY: Stock status

    User Context (session-scoped):
    - PREFERENCE: Learned user preferences
    - CONSTRAINT: User-specified requirements
    """

    # Phase 1 - Reusable intelligence
    RETAILER = "retailer"
    MARKET_INFO = "market_info"
    BUYING_TIP = "buying_tip"
    SPEC_INFO = "spec_info"

    # Phase 2 - Query-specific findings
    PRODUCT = "product"
    PRICE = "price"
    AVAILABILITY = "availability"

    # User context
    PREFERENCE = "preference"
    CONSTRAINT = "constraint"

    # Fallback
    GENERAL = "general"

    @property
    def default_ttl_hours(self) -> int:
        """Default TTL in hours for this claim type."""
        ttl_map = {
            ClaimType.RETAILER: 168,       # 1 week - retailers don't change often
            ClaimType.MARKET_INFO: 72,     # 3 days - market trends
            ClaimType.BUYING_TIP: 336,     # 2 weeks - tips stay relevant
            ClaimType.SPEC_INFO: 720,      # 1 month - specs are stable
            ClaimType.PRODUCT: 24,         # 1 day - specific products
            ClaimType.PRICE: 4,            # 4 hours - prices change fast
            ClaimType.AVAILABILITY: 2,     # 2 hours - stock changes fast
            ClaimType.PREFERENCE: 720,     # 1 month - preferences persist
            ClaimType.CONSTRAINT: 24,      # 1 day - per-session usually
            ClaimType.GENERAL: 24,         # 1 day default
        }
        return ttl_map.get(self, 24)

    @property
    def default_ttl_seconds(self) -> int:
        """Default TTL in seconds for this claim type."""
        return self.default_ttl_hours * 3600

    @property
    def is_reusable(self) -> bool:
        """Whether this claim type is reusable across queries."""
        return self in REUSABLE_CLAIM_TYPES

    @property
    def is_phase1_knowledge(self) -> bool:
        """Whether this is Phase 1 intelligence (vs Phase 2 findings)."""
        return self in PHASE1_CLAIM_TYPES

    @classmethod
    def from_statement(cls, statement: str) -> "ClaimType":
        """
        Infer claim type from statement text.

        Used for categorizing claims from Phase 1/2 results.
        """
        statement_lower = statement.lower()

        # Retailer patterns
        retailer_patterns = [
            "sells", "carries", "available at", "shop at", "retailer",
            "store", "vendor", "merchant", "buy from", "purchase from"
        ]
        if any(pattern in statement_lower for pattern in retailer_patterns):
            return cls.RETAILER

        # Price patterns - check for ranges vs specific prices
        if any(word in statement_lower for word in ["$", "price", "cost", "costs", "priced"]):
            if any(word in statement_lower for word in ["range", "between", "typically", "usually", "average"]):
                return cls.MARKET_INFO
            return cls.PRICE

        # Tip/recommendation patterns
        tip_patterns = [
            "tip", "recommend", "avoid", "warning", "best to", "should",
            "consider", "advice", "suggestion", "don't forget", "make sure",
            "check for", "look for", "deals", "discount", "coupon", "save"
        ]
        if any(pattern in statement_lower for pattern in tip_patterns):
            return cls.BUYING_TIP

        # Constraint patterns (check BEFORE spec patterns)
        constraint_patterns = [
            "must have", "require", "need", "constraint", "limit",
            "maximum", "minimum", "at least", "at most", "no more than",
            "under $", "over $", "less than", "more than"
        ]
        if any(pattern in statement_lower for pattern in constraint_patterns):
            return cls.CONSTRAINT

        # Spec patterns
        spec_patterns = [
            "spec", "ram", "cpu", "gpu", "processor", "storage", "display",
            "battery", "weight", "dimension", "resolution", "memory",
            "core", "ghz", "mhz", "inch", "watt"
        ]
        if any(pattern in statement_lower for pattern in spec_patterns):
            return cls.SPEC_INFO

        # Stock/availability patterns
        availability_patterns = [
            "in stock", "out of stock", "available", "unavailable",
            "sold out", "back in stock", "limited stock", "backordered"
        ]
        if any(pattern in statement_lower for pattern in availability_patterns):
            return cls.AVAILABILITY

        # Product patterns (specific product mentions)
        product_patterns = ["model", "sku", "product", "item", "unit"]
        if any(pattern in statement_lower for pattern in product_patterns):
            return cls.PRODUCT

        # Preference patterns
        preference_patterns = [
            "prefers", "preference", "likes", "wants", "looking for",
            "interested in", "budget", "priority"
        ]
        if any(pattern in statement_lower for pattern in preference_patterns):
            return cls.PREFERENCE

        return cls.GENERAL


# Sets for fast membership testing
REUSABLE_CLAIM_TYPES: Set[ClaimType] = {
    ClaimType.RETAILER,
    ClaimType.MARKET_INFO,
    ClaimType.BUYING_TIP,
    ClaimType.SPEC_INFO,
    ClaimType.PREFERENCE,
}

PHASE1_CLAIM_TYPES: Set[ClaimType] = {
    ClaimType.RETAILER,
    ClaimType.MARKET_INFO,
    ClaimType.BUYING_TIP,
    ClaimType.SPEC_INFO,
}

PHASE2_CLAIM_TYPES: Set[ClaimType] = {
    ClaimType.PRODUCT,
    ClaimType.PRICE,
    ClaimType.AVAILABILITY,
}

USER_CONTEXT_CLAIM_TYPES: Set[ClaimType] = {
    ClaimType.PREFERENCE,
    ClaimType.CONSTRAINT,
}
