"""
Product search configuration: Query templates, defaults, and category mappings.

Part of the intelligence-driven multi-phase product search system.
"""

import os
from typing import Dict, List, Optional
from dataclasses import dataclass


# Phase 1 query templates for intelligence gathering
PHASE1_QUERY_TEMPLATES = [
    "{product}",                                      # Base query
    "where to buy {product}",                         # Direct intent
    "{product} forum reddit recommendations",         # Community wisdom
    "best place to buy {product}",                   # Quality focus
    "{product} {category_specific}",                 # e.g., "breeder" for animals
]

# TODO(LLM-FIRST): Category-specific query additions should be LLM-generated.
# INSTEAD OF: Hardcoded mappings like "pet" -> "breeder"
# SHOULD BE: Let the LLM generate query variations based on:
#   1. The original query (e.g., "buy hamster" suggests live animal, "hamster cage" suggests product)
#   2. Context from Phase 1 intelligence
#   3. User history and preferences
#
# The current mapping is too coarse - "pet" doesn't distinguish between
# live animals (breeder) vs pet supplies (retailer).
#
# See: panda_system_docs/architecture/LLM-ROLES/CONTEXT_DISCIPLINE.md
CATEGORY_QUERY_ADDITIONS = {
    "pet": "breeder",
    "animal": "breeder",
    "electronics": "vendor supplier",
    "computer": "vendor supplier",
    "clothing": "online store",
    "food": "where to buy",
    "home": "retailer",
    "general": "vendor"
}

# TODO(LLM-FIRST): DEPRECATED - Hardcoded vendor lists violate LLM-first design.
# The system now uses VendorRegistry which learns vendors dynamically from:
# - Phase 1 intelligence gathering
# - Google search results
# - User queries
#
# This list is kept ONLY as initial seed data for the registry
# and should eventually be removed entirely.
#
# The LLM-first approach:
# - Let Google search discover vendors naturally
# - Let LLM evaluate which results look like legitimate vendors
# - Build vendor knowledge from actual research, not hardcoded lists
#
# See: orchestrator/shared_state/vendor_registry.py
# See: panda_system_docs/architecture/LLM-ROLES/CONTEXT_DISCIPLINE.md
_SEED_VENDORS = {
    "pet": [
        {"name": "PetSmart", "url": "petsmart.com", "type": "pet_store_chain"},
        {"name": "Petco", "url": "petco.com", "type": "pet_store_chain"},
        {"name": "Chewy", "url": "chewy.com", "type": "online_retailer"},
    ],
    "electronics": [
        {"name": "Best Buy", "url": "bestbuy.com", "type": "electronics_store"},
        {"name": "Newegg", "url": "newegg.com", "type": "online_retailer"},
        {"name": "B&H Photo", "url": "bhphotovideo.com", "type": "specialty_retailer"},
    ],
    "general": [
        {"name": "Amazon", "url": "amazon.com", "type": "marketplace"},
        {"name": "eBay", "url": "ebay.com", "type": "marketplace"},
    ]
}

# For backwards compatibility - use get_default_vendors() which now uses registry
DEFAULT_VENDORS = _SEED_VENDORS


def seed_vendor_registry() -> int:
    """
    Seed the VendorRegistry with initial vendors if empty.

    This is called once on startup to give the system initial knowledge.
    After that, the system learns and adapts from experience.

    Returns:
        Number of vendors seeded
    """
    try:
        if os.getenv("SEED_VENDOR_ENABLE", "true").lower() != "true":
            return 0
        from apps.services.tool_server.shared_state.vendor_registry import get_vendor_registry
        registry = get_vendor_registry()

        # Only seed if registry is empty
        if registry.get_all():
            return 0

        count = 0
        for category, vendors in _SEED_VENDORS.items():
            for vendor in vendors:
                registry.add_or_update(
                    domain=vendor["url"],
                    name=vendor["name"],
                    categories=[category],
                    vendor_type=vendor.get("type", ""),
                    discovered_via="seed_data"
                )
                count += 1

        return count
    except Exception:
        return 0


@dataclass
class SearchConfig:
    """Configuration for multi-phase product search"""

    # Phase 1: Intelligence gathering
    max_vendors_phase1: int = 10
    max_urls_per_query_phase1: int = 10
    num_query_variations_phase1: int = 4

    # Phase 2: Product search
    max_products_phase2: int = 20
    max_urls_per_vendor_phase2: int = 5

    # Performance
    parallel_fetch_limit: int = 3
    fetch_timeout_sec: int = 30

    # Caching
    vendor_cache_ttl_days: int = 7
    intelligence_cache_ttl_days: int = 7

    # Quality thresholds
    min_vendor_confidence: float = 0.6
    min_product_quality_score: float = 0.4
    min_spec_compliance: float = 0.5


def get_phase1_queries(product: str, category: str = "general") -> List[str]:
    """
    Generate Phase 1 discovery queries.

    Args:
        product: Product name (e.g., "Syrian hamster")
        category: Product category (e.g., "pet", "electronics")

    Returns:
        List of search queries for intelligence gathering
    """
    category_addition = CATEGORY_QUERY_ADDITIONS.get(category, "vendor")

    queries = []
    for template in PHASE1_QUERY_TEMPLATES:
        query = template.format(
            product=product,
            category_specific=category_addition
        )
        queries.append(query)

    return queries


def get_default_vendors(category: str = "general") -> List[Dict]:
    """
    Get vendor list for a category from the VendorRegistry.

    This now uses the living VendorRegistry which learns from experience.
    Falls back to seed vendors only if registry is empty.

    Args:
        category: Product category

    Returns:
        List of vendor dicts with name, url, type
    """
    try:
        from apps.services.tool_server.shared_state.vendor_registry import get_vendor_registry
        registry = get_vendor_registry()

        # Get usable vendors from registry for this category
        usable = registry.get_usable_vendors(category=category, limit=5, min_success_rate=0.3)

        if usable:
            # Convert VendorRecord to dict format expected by callers
            return [
                {
                    "name": v.name or v.domain.split('.')[0].title(),
                    "url": v.domain,
                    "type": v.vendor_type or "unknown"
                }
                for v in usable
            ]
    except Exception:
        pass

    # Fall back to seed vendors if registry is empty or failed
    return _SEED_VENDORS.get(category, _SEED_VENDORS.get("general", []))


def infer_category(product: str) -> str:
    """
    Infer product category from product name.

    Args:
        product: Product name

    Returns:
        Category string
    """
    product_lower = product.lower()

    # Pet/animal keywords
    pet_keywords = ["hamster", "dog", "cat", "bird", "fish", "rabbit", "pet",
                    "puppy", "kitten", "animal", "reptile", "guinea pig"]
    if any(keyword in product_lower for keyword in pet_keywords):
        return "pet"

    # Electronics keywords
    electronics_keywords = ["laptop", "computer", "phone", "tablet", "monitor",
                           "keyboard", "mouse", "headphones", "camera", "tv",
                           "electronics", "gaming", "console"]
    if any(keyword in product_lower for keyword in electronics_keywords):
        return "electronics"

    # Clothing keywords
    clothing_keywords = ["shirt", "pants", "shoes", "dress", "jacket", "coat",
                        "clothing", "apparel", "boots", "sneakers", "jeans"]
    if any(keyword in product_lower for keyword in clothing_keywords):
        return "clothing"

    # Home keywords
    home_keywords = ["furniture", "couch", "chair", "table", "bed", "lamp",
                    "decor", "rug", "curtain", "shelf", "home"]
    if any(keyword in product_lower for keyword in home_keywords):
        return "home"

    return "general"


# Phase 2 query templates
def get_phase2_queries(
    product: str,
    vendor_name: str,
    vendor_url: str
) -> List[str]:
    """
    Generate Phase 2 product search queries for a specific vendor.

    Args:
        product: Product name
        vendor_name: Vendor name
        vendor_url: Vendor domain

    Returns:
        List of vendor-specific search queries
    """
    return [
        f"{product} site:{vendor_url}",
        f"{product} buy site:{vendor_url}",
        f"{product} {vendor_name}"
    ]


def get_phase2_generic_queries(product: str) -> List[str]:
    """
    Generate generic Phase 2 queries (when no Phase 1 vendors available).

    Args:
        product: Product name

    Returns:
        List of generic product search queries
    """
    return [
        f"{product} buy",
        f"{product} for sale",
        f"{product} online",
        f"where to buy {product}"
    ]
