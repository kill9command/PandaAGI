"""
orchestrator/research_orchestrator.py

DEPRECATED (2025-11-29): Use web_mcp.py instead.

This module is kept for backward compatibility with research_role.py.
New code should use:
    from orchestrator.web_mcp import web_research

The unified web_mcp.py provides:
- Single entry point for ALL web operations
- Proactive schema learning
- Unified SmartPageWaiter

Migration:
    OLD: gather_intelligence(query, ...), research(query, ...)
    NEW: await web_research(query, max_sources=5)

Created: 2025-11-15
Deprecated: 2025-11-29 (replaced by web_mcp.py)
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

# NEW: Two-phase research system imports
from orchestrator.query_planner import optimize_query_for_phase, construct_vendor_search_url, simplify_query_for_retailers, simplify_query_for_retailers_async, detect_price_priority
from orchestrator.llm_candidate_filter import filter_candidates_for_intelligence
from orchestrator.shared_state.source_reliability import get_tracker
from orchestrator.retailer_selector import select_retailers_for_query
from orchestrator.product_comparison_tracker import ProductComparisonTracker

# Goal-directed navigation for intelligent extraction
from orchestrator.navigator_integration import extract_with_navigation, UnifiedClaim
from orchestrator.product_requirements import ProductRequirements

# Universal Web Agent - simple See→Think→Act loop
from orchestrator.universal_agent import UniversalWebAgent
from orchestrator.site_knowledge_cache import SiteKnowledgeCache

# Global site knowledge cache (shared across extractions)
_site_knowledge_cache = None

def get_site_knowledge_cache() -> SiteKnowledgeCache:
    """Get or create the global site knowledge cache."""
    global _site_knowledge_cache
    if _site_knowledge_cache is None:
        _site_knowledge_cache = SiteKnowledgeCache()
    return _site_knowledge_cache

# Site schema registry for persistent selector learning
from orchestrator.shared_state.site_schema_registry import (
    get_schema_registry,
    SiteSchema
)
from orchestrator.shared_state.site_health_tracker import get_health_tracker
from orchestrator.shared_state.vendor_registry import get_vendor_registry
from orchestrator.search_rate_limiter import get_search_rate_limiter

logger = logging.getLogger(__name__)


# ==================== SOURCE QUALITY TRACKING ====================

def _fallback_source_type(url: str) -> str:
    """Lightweight fallback when LLM scoring is unavailable."""
    url_lower = url.lower()
    if any(token in url_lower for token in ["/forum", "/thread", "/discussion"]):
        return "forum"
    if any(token in url_lower for token in ["/video", "/watch", "/player"]):
        return "video"
    return "unknown"


async def _goal_directed_browse(
    url: str,
    goal: str,
    session_id: str,
    max_steps: int = 10
) -> Optional[Dict[str, Any]]:
    """
    Use UniversalWebAgent for goal-directed browsing.

    This replaces hardcoded navigation logic with LLM-driven decisions.
    The agent can navigate pagination, click specific links, and achieve
    complex goals like "go to the last page" or "find the pricing section".

    Args:
        url: Starting URL
        goal: What to achieve (e.g., "read the last page of this thread")
        session_id: Browser session ID
        max_steps: Maximum navigation steps

    Returns:
        {
            "url": "final_url",
            "text_content": "extracted content",
            "pages_visited": [...],
            "goal_achieved": True/False,
            "summary": "..."
        }
    """
    from orchestrator import web_vision_mcp

    try:
        # Get page object from web vision session
        page = await web_vision_mcp.get_page(session_id)
        if not page:
            logger.warning(f"[GoalBrowse] Could not get page for session {session_id}")
            return None

        # Create agent with site knowledge
        agent = UniversalWebAgent(
            page=page,
            knowledge_cache=get_site_knowledge_cache(),
            llm_url=os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions"),
            llm_model=os.getenv("SOLVER_MODEL_ID", "qwen3-coder"),
            llm_api_key=os.getenv("SOLVER_API_KEY", "qwen-local"),
            session_id=session_id
        )

        # Use goal-directed browsing
        result = await agent.browse(
            url=url,
            goal=goal,
            max_steps=max_steps
        )

        logger.info(
            f"[GoalBrowse] Complete: {len(result.get('pages_visited', []))} pages, "
            f"goal_achieved={result.get('goal_achieved', False)}"
        )

        return result

    except Exception as e:
        logger.error(f"[GoalBrowse] Failed: {e}")
        return None


def _build_navigation_context(
    intelligence: Dict[str, Any],
    query: str
) -> Dict[str, Any]:
    """
    Build navigation context for UniversalWebAgent from Phase 1 intelligence.

    This context helps the agent make better decisions about which links to click.
    For example, if searching for live hamsters, it should navigate to "Animals"
    not "Supplies" on pet store sites.

    Note: Site type detection is NOT done here - the LLM determines site type
    from actual page content per CONTEXT_DISCIPLINE.md.

    Args:
        intelligence: Phase 1 intelligence dict with specs, retailers, etc.
        query: User's search query

    Returns:
        Dict with navigation hints for the agent
    """
    context = {}

    # Infer product type from query
    query_lower = query.lower()

    # Detect if searching for live animals
    live_animal_patterns = [
        "hamster", "gerbil", "guinea pig", "rabbit", "bunny",
        "puppy", "kitten", "bird", "fish", "reptile", "snake",
        "lizard", "turtle", "ferret", "chinchilla", "mouse", "rat"
    ]
    if any(animal in query_lower for animal in live_animal_patterns):
        context["product_type"] = "live_animal"
        context["accept_patterns"] = [
            "Animals", "Live Animals", "Pets", "Available",
            "Litters", "Our Hamsters", "Adopt", "For Sale"
        ]
        context["reject_patterns"] = [
            "Supplies", "Accessories", "Cages", "Food", "Bedding",
            "Toys", "Habitat", "Equipment"
        ]

    # NOTE: Site type detection removed per CONTEXT_DISCIPLINE.md
    # The LLM determines site type from actual page content, not domain patterns.
    # Hardcoded domain lists (petco, petsmart, craigslist, etc.) violated the principle:
    # "If the LLM is making bad decisions, the fix is better context/prompts, NOT hardcoded workarounds."

    # Extract key topics from intelligence
    if intelligence:
        # Get key topics
        key_topics = intelligence.get("key_topics", [])
        if key_topics:
            context["key_topics"] = key_topics[:3]

        # Get discovered retailers
        retailers = intelligence.get("retailers_discovered", [])
        if not retailers:
            # Try alternative keys
            retailers = intelligence.get("credible_sources", [])
        if retailers:
            context["retailers_discovered"] = retailers[:5]

        # Get specs/requirements
        specs = intelligence.get("specs_discovered", {})
        if specs:
            context["requirements"] = {k: str(v) for k, v in list(specs.items())[:3]}

        # Get price range
        price_range = intelligence.get("price_range", {})
        if isinstance(price_range, dict) and price_range:
            context["requirements"] = context.get("requirements", {})
            if price_range.get("max"):
                context["requirements"]["max_price"] = f"${price_range['max']}"

    # Detect price priority from query for navigation decisions
    # This tells the agent to prioritize sorting by price
    price_priority = detect_price_priority(query)
    if price_priority:
        context["price_priority"] = price_priority
        if price_priority == "low":
            context["navigation_goal"] = "Sort results by price low-to-high to show cheapest first"
        elif price_priority == "high":
            context["navigation_goal"] = "Sort results by price high-to-low to show premium options first"

    return context


def _extract_key_requirements_from_query(query: str) -> List[str]:
    """
    Extract key requirements/constraints from query for intelligent source filtering.

    This extracts explicit constraints mentioned in the query to help the LLM
    filter sources more effectively. The LLM uses its own knowledge to interpret
    what these requirements mean.

    Args:
        query: The user's search query

    Returns:
        List of key requirements/constraints extracted from query
    """
    query_lower = query.lower()
    requirements = []

    # Budget/price intent (universal - applies to any product)
    budget_words = ["cheap", "cheapest", "budget", "affordable", "inexpensive", "low cost", "under $", "below $", "less than $"]
    if any(word in query_lower for word in budget_words):
        requirements.append("budget/affordable")

    premium_words = ["premium", "high-end", "luxury", "best", "top of the line", "professional"]
    if any(word in query_lower for word in premium_words):
        requirements.append("premium/high-end")

    # Purchase intent
    if any(word in query_lower for word in ["for sale", "buy", "purchase", "where to get"]):
        requirements.append("for purchase")

    # Location constraints
    if any(word in query_lower for word in ["near me", "local", "in my area"]):
        requirements.append("local availability")

    # The main product/item is in the query itself - LLM will understand it
    # We don't need to extract "laptop" or "hamster" - the query contains it

    return requirements


# ==================== RECOVERY STRATEGIES ====================

async def _try_recovery_strategy(
    domain: str,
    url: str,
    strategy: str,
    session_id: str = None
) -> bool:
    """
    Execute a recovery strategy for a failing vendor.

    The system tries to fix problems before giving up on vendors.
    Returns True if recovery was successful.

    Strategies:
    - recalibrate_selectors: Clear cached selectors, force re-calibration
    - increase_wait_time: Add delays for slow-loading sites
    - use_stealth_mode: Enable anti-detection measures
    - try_different_url_pattern: Try alternative URL formats
    - use_mobile_viewport: Try mobile user-agent
    """
    logger.info(f"[Recovery] Attempting {strategy} for {domain}")

    try:
        if strategy == "recalibrate_selectors":
            # Clear cached selectors for this domain, forcing LLM recalibration
            from orchestrator.shared_state.site_schema_registry import get_schema_registry
            registry = get_schema_registry()
            if registry.delete_schema(domain):
                logger.info(f"[Recovery] Cleared cached selectors for {domain} - will recalibrate on next visit")
                return True
            # Also clear unified calibration cache
            # Using PageIntelligence adapter for backwards compatibility
            from orchestrator.page_intelligence.legacy_adapter import get_calibrator
            calibrator = get_calibrator()
            if hasattr(calibrator, 'delete_calibration') and calibrator.delete_calibration(domain):
                logger.info(f"[Recovery] Cleared UnifiedCalibrator cache for {domain}")
                return True
            return False

        elif strategy == "increase_wait_time":
            # Set a flag that extraction should use longer waits
            # This is stored in site_health_tracker for the extraction code to check
            from orchestrator.shared_state.site_health_tracker import get_health_tracker
            ht = get_health_tracker()
            ht.set_site_config(domain, "wait_multiplier", 2.0)
            logger.info(f"[Recovery] Set wait_multiplier=2.0 for {domain}")
            return True

        elif strategy == "use_stealth_mode":
            # Enable stealth browser options for this domain
            from orchestrator.shared_state.site_health_tracker import get_health_tracker
            ht = get_health_tracker()
            ht.set_site_config(domain, "use_stealth", True)
            logger.info(f"[Recovery] Enabled stealth mode for {domain}")
            return True

        elif strategy == "try_different_url_pattern":
            # Mark that we should try alternative URL patterns (e.g., /search vs /s)
            from orchestrator.shared_state.site_health_tracker import get_health_tracker
            ht = get_health_tracker()
            ht.set_site_config(domain, "try_alt_urls", True)
            logger.info(f"[Recovery] Enabled alternative URL patterns for {domain}")
            return True

        elif strategy == "use_mobile_viewport":
            # Try mobile viewport/user-agent
            from orchestrator.shared_state.site_health_tracker import get_health_tracker
            ht = get_health_tracker()
            ht.set_site_config(domain, "use_mobile", True)
            logger.info(f"[Recovery] Enabled mobile viewport for {domain}")
            return True

        else:
            logger.warning(f"[Recovery] Unknown strategy: {strategy}")
            return False

    except Exception as e:
        logger.error(f"[Recovery] Strategy {strategy} failed for {domain}: {e}")
        return False


def _normalize_price_range(intelligence: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize price_range in intelligence to handle edge cases.

    Common issues:
    - LLM sets min=max when "under $X" is specified (should be min=0, max=X)
    - LLM sets min > max (swap them)
    - LLM sets unrealistic values

    Args:
        intelligence: Intelligence dict with potential price_range

    Returns:
        Intelligence dict with normalized price_range
    """
    if not intelligence or "price_range" not in intelligence:
        return intelligence

    pr = intelligence.get("price_range", {})
    if not isinstance(pr, dict):
        return intelligence

    min_val = pr.get("min", 0)
    max_val = pr.get("max", 0)

    # Ensure numeric
    try:
        min_val = float(min_val) if min_val else 0
        max_val = float(max_val) if max_val else 0
    except (ValueError, TypeError):
        min_val = 0
        max_val = 0

    # Fix: If min == max, likely "under $X" - set min to 0
    if min_val == max_val and max_val > 0:
        logger.info(f"[PriceRange] Normalized min==max={max_val} to min=0, max={max_val}")
        min_val = 0

    # Fix: If min > max, swap them
    if min_val > max_val and max_val > 0:
        logger.info(f"[PriceRange] Swapped inverted range: min={min_val}, max={max_val}")
        min_val, max_val = max_val, min_val

    # Fix: If min is unreasonably high (>80% of max), assume "under $X" intent
    if max_val > 0 and min_val > max_val * 0.8:
        logger.info(f"[PriceRange] min={min_val} seems too high (>80% of max), setting min=0")
        min_val = 0

    intelligence["price_range"] = {"min": min_val, "max": max_val}
    return intelligence


def _parse_budget_intent_from_query(query: str) -> Dict[str, Any]:
    """
    Parse budget intent directly from the user's query.

    This extracts budget constraints BEFORE intelligence gathering,
    so we know what price tier to filter specs for.

    Returns:
        {
            "budget_tier": "budget" | "mid" | "premium" | "any",
            "max_budget": float | None,
            "min_budget": float | None,
            "budget_words_found": ["cheapest", ...],
            "user_specified_specs": ["RTX 4060", ...],  # specs user explicitly asked for
            "detected_category": "electronics" | "pets" | "furniture" | ...
        }
    """
    import re

    query_lower = query.lower()
    result = {
        "budget_tier": "any",
        "max_budget": None,
        "min_budget": None,
        "budget_words_found": [],
        "user_specified_specs": [],
        "detected_category": "general"
    }

    # Budget tier words
    budget_words = ["cheapest", "cheap", "budget", "affordable", "inexpensive", "low cost", "lowest price", "best value"]
    premium_words = ["best", "premium", "high-end", "top of the line", "flagship", "professional", "luxury"]

    # Check for budget intent
    for word in budget_words:
        if word in query_lower:
            result["budget_tier"] = "budget"
            result["budget_words_found"].append(word)

    # Check for premium intent (only if no budget words found)
    if result["budget_tier"] == "any":
        for word in premium_words:
            if word in query_lower:
                result["budget_tier"] = "premium"
                result["budget_words_found"].append(word)
                break

    # Extract explicit price constraints
    # Patterns: "under $800", "below $1000", "less than $500", "$400-$800", "around $600"
    under_pattern = r'(?:under|below|less than|max|maximum|up to)\s*\$?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)'
    over_pattern = r'(?:over|above|more than|min|minimum|at least)\s*\$?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)'
    range_pattern = r'\$?\s*(\d+(?:,\d{3})*)\s*[-–to]+\s*\$?\s*(\d+(?:,\d{3})*)'
    around_pattern = r'(?:around|about|approximately|~)\s*\$?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)'

    # Check for range first
    range_match = re.search(range_pattern, query_lower)
    if range_match:
        result["min_budget"] = float(range_match.group(1).replace(",", ""))
        result["max_budget"] = float(range_match.group(2).replace(",", ""))
    else:
        # Check for under/max
        under_match = re.search(under_pattern, query_lower)
        if under_match:
            result["max_budget"] = float(under_match.group(1).replace(",", ""))

        # Check for over/min
        over_match = re.search(over_pattern, query_lower)
        if over_match:
            result["min_budget"] = float(over_match.group(1).replace(",", ""))

        # Check for around (sets both min and max as range)
        if not under_match and not over_match:
            around_match = re.search(around_pattern, query_lower)
            if around_match:
                target = float(around_match.group(1).replace(",", ""))
                result["min_budget"] = target * 0.8
                result["max_budget"] = target * 1.2

    # Category detection and default budgets for "cheapest X" queries
    # Maps: (keywords, category_name, default_budget_for_cheapest)
    category_budgets = [
        # Electronics
        (["laptop", "notebook", "chromebook"], "electronics", 800),
        (["gpu", "graphics card", "video card"], "electronics", 400),
        (["phone", "smartphone", "iphone", "android phone"], "electronics", 500),
        (["tv", "television", "smart tv"], "electronics", 400),
        (["monitor", "display"], "electronics", 250),
        (["headphone", "earbuds", "airpods"], "electronics", 80),
        (["camera", "dslr", "mirrorless"], "electronics", 500),
        (["tablet", "ipad"], "electronics", 300),
        (["smartwatch", "watch"], "electronics", 150),
        (["speaker", "soundbar"], "electronics", 100),
        (["keyboard", "mechanical keyboard"], "electronics", 50),
        (["mouse", "gaming mouse"], "electronics", 30),
        (["router", "wifi"], "electronics", 60),
        (["drone"], "electronics", 200),

        # Pets & Animals
        (["hamster", "gerbil"], "pets", 25),
        (["guinea pig", "cavy"], "pets", 40),
        (["rabbit", "bunny"], "pets", 50),
        (["dog", "puppy"], "pets", 500),
        (["cat", "kitten"], "pets", 200),
        (["bird", "parrot", "parakeet", "cockatiel"], "pets", 100),
        (["fish", "aquarium fish", "goldfish", "betta"], "pets", 20),
        (["reptile", "snake", "lizard", "gecko", "turtle", "tortoise"], "pets", 100),
        (["ferret"], "pets", 150),
        (["chinchilla"], "pets", 200),

        # Furniture & Home
        (["sofa", "couch", "sectional"], "furniture", 500),
        (["mattress", "bed"], "furniture", 400),
        (["desk", "standing desk"], "furniture", 150),
        (["chair", "office chair", "gaming chair"], "furniture", 100),
        (["table", "dining table", "coffee table"], "furniture", 150),
        (["dresser", "drawer"], "furniture", 200),
        (["bookshelf", "shelf"], "furniture", 80),
        (["rug", "carpet"], "furniture", 100),

        # Appliances
        (["refrigerator", "fridge"], "appliances", 600),
        (["washer", "washing machine"], "appliances", 400),
        (["dryer"], "appliances", 400),
        (["dishwasher"], "appliances", 400),
        (["microwave"], "appliances", 80),
        (["vacuum", "roomba"], "appliances", 150),
        (["air conditioner", "ac unit"], "appliances", 300),
        (["air purifier"], "appliances", 100),
        (["blender", "mixer"], "appliances", 50),
        (["coffee maker", "espresso"], "appliances", 80),
        (["toaster", "toaster oven"], "appliances", 40),
        (["instant pot", "pressure cooker"], "appliances", 80),

        # Sports & Outdoors
        (["bicycle", "bike", "mountain bike", "road bike"], "sports", 300),
        (["treadmill", "elliptical"], "sports", 400),
        (["weights", "dumbbells", "kettlebell"], "sports", 50),
        (["tent", "camping tent"], "sports", 100),
        (["kayak", "canoe"], "sports", 300),
        (["golf clubs", "golf set"], "sports", 300),
        (["skateboard", "longboard"], "sports", 60),
        (["scooter", "electric scooter"], "sports", 200),

        # Clothing & Accessories
        (["shoes", "sneakers", "boots"], "clothing", 60),
        (["jacket", "coat"], "clothing", 80),
        (["backpack", "bag"], "clothing", 40),
        (["sunglasses"], "clothing", 30),

        # Tools & Garden
        (["lawn mower", "mower"], "tools", 200),
        (["drill", "power drill"], "tools", 50),
        (["chainsaw"], "tools", 150),
        (["pressure washer"], "tools", 150),

        # Musical Instruments
        (["guitar", "electric guitar", "acoustic guitar"], "music", 200),
        (["piano", "keyboard", "digital piano"], "music", 300),
        (["drum", "drum set"], "music", 300),
        (["violin"], "music", 150),
        (["ukulele"], "music", 40),

        # Baby & Kids
        (["stroller", "baby stroller"], "baby", 150),
        (["car seat", "baby car seat"], "baby", 100),
        (["crib", "baby crib"], "baby", 150),
        (["high chair"], "baby", 80),

        # Vehicles (accessories/parts)
        (["car battery"], "automotive", 100),
        (["tire", "tires"], "automotive", 100),
        (["dash cam", "dashcam"], "automotive", 50),
    ]

    # Detect category and set default budget
    detected_category = "general"
    default_budget = 200  # Generic default

    for keywords, category, budget in category_budgets:
        if any(kw in query_lower for kw in keywords):
            detected_category = category
            default_budget = budget
            break

    result["detected_category"] = detected_category

    # NOTE: We intentionally do NOT infer a hard budget when user says "cheapest"
    # without an explicit price. "Cheapest" means sort by price, not reject over $X.
    # Hard budget limits only come from explicit user input like "under $800".

    # Extract user-specified specs that should NOT be filtered
    # GPU models
    gpu_patterns = [
        r'rtx\s*\d{4}(?:\s*ti)?(?:\s*super)?',
        r'gtx\s*\d{4}(?:\s*ti)?(?:\s*super)?',
        r'rx\s*\d{4}(?:\s*xt)?',
        r'arc\s*[ab]\d{3}',
    ]
    for pattern in gpu_patterns:
        matches = re.findall(pattern, query_lower)
        for match in matches:
            result["user_specified_specs"].append(match.upper().replace(" ", " "))

    # Pet breeds (user specifying a breed means they want that breed)
    pet_breed_patterns = [
        # Dogs
        r'golden retriever', r'labrador', r'german shepherd', r'bulldog', r'poodle',
        r'beagle', r'rottweiler', r'husky', r'corgi', r'shiba inu', r'french bulldog',
        r'dachshund', r'boxer', r'great dane', r'doberman', r'pitbull', r'chihuahua',
        # Cats
        r'persian', r'siamese', r'maine coon', r'ragdoll', r'bengal', r'british shorthair',
        r'scottish fold', r'sphynx', r'russian blue', r'abyssinian',
        # Hamsters
        r'syrian', r'dwarf', r'roborovski', r'campbell', r'chinese hamster', r'winter white',
        # Birds
        r'african grey', r'cockatoo', r'macaw', r'budgie', r'conure',
    ]
    for pattern in pet_breed_patterns:
        if pattern in query_lower:
            result["user_specified_specs"].append(pattern.title())

    # Brand names that indicate user preference (electronics)
    brand_patterns = [
        r'\bapple\b', r'\bsamsung\b', r'\bsony\b', r'\blg\b', r'\bdell\b', r'\bhp\b',
        r'\blenovo\b', r'\basus\b', r'\bacer\b', r'\bmsi\b', r'\brazer\b', r'\bbose\b',
        r'\bjbl\b', r'\bcanon\b', r'\bnikon\b', r'\bdyson\b', r'\bkitchenaid\b',
    ]
    for pattern in brand_patterns:
        if re.search(pattern, query_lower):
            brand = re.search(pattern, query_lower).group().title()
            result["user_specified_specs"].append(brand)

    if result["budget_words_found"] or result["max_budget"]:
        logger.info(
            f"[BudgetParser] Query: '{query[:50]}...' → "
            f"tier={result['budget_tier']}, max=${result['max_budget']}, "
            f"category={result['detected_category']}, specs={result['user_specified_specs']}"
        )

    return result


def _filter_specs_by_budget(
    intelligence: Dict[str, Any],
    budget_intent: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Post-processing filter to remove specs incompatible with user's budget.

    Only filters forum-recommended specs, NOT user-specified specs.
    Works across all product categories.

    Args:
        intelligence: Intelligence dict with specs_discovered
        budget_intent: Output from _parse_budget_intent_from_query

    Returns:
        Intelligence dict with filtered specs_discovered
    """
    if not intelligence:
        return intelligence

    specs = intelligence.get("specs_discovered", {})
    if not specs:
        return intelligence

    max_budget = budget_intent.get("max_budget")
    budget_tier = budget_intent.get("budget_tier", "any")
    user_specs = [s.lower() for s in budget_intent.get("user_specified_specs", [])]
    detected_category = budget_intent.get("detected_category", "general")

    # If no budget constraint, don't filter
    if budget_tier == "any" and not max_budget:
        return intelligence

    def is_user_specified(value: str) -> bool:
        """Check if a value was explicitly specified by user."""
        value_lower = value.lower()
        return any(user_spec in value_lower for user_spec in user_specs)

    def get_spec_value(spec_entry) -> str:
        """Extract string value from spec (handles dict or string format)."""
        if isinstance(spec_entry, dict):
            return spec_entry.get("value", "").lower()
        elif isinstance(spec_entry, str):
            return spec_entry.lower()
        return ""

    def filter_spec(spec_key: str, premium_items: Dict[str, int], budget_threshold: int = 1000):
        """Generic filter for a spec by premium item pricing."""
        if spec_key not in specs:
            return

        spec_value = get_spec_value(specs[spec_key])
        if not spec_value or is_user_specified(spec_value):
            return

        for item_name, min_price in premium_items.items():
            if item_name in spec_value:
                if max_budget and min_price > max_budget:
                    logger.info(
                        f"[SpecFilter] Removing {spec_key} '{spec_value}' - requires ${min_price}+ "
                        f"but budget is ${max_budget}"
                    )
                    del specs[spec_key]
                elif budget_tier == "budget" and min_price > budget_threshold:
                    logger.info(
                        f"[SpecFilter] Removing {spec_key} '{spec_value}' - premium item "
                        f"(${min_price}+) incompatible with 'budget' intent"
                    )
                    del specs[spec_key]
                return

    # ==========================================================================
    # GPU Filtering (Electronics)
    # ==========================================================================
    gpu_min_prices = {
        # RTX 50 series (2024-2025)
        "rtx 5090": 4500, "rtx 5080": 3000, "rtx 5070 ti": 2000,
        "rtx 5070": 1500, "rtx 5060 ti": 1200, "rtx 5060": 1000,
        # RTX 40 series
        "rtx 4090": 2500, "rtx 4080": 2000, "rtx 4070 ti": 1500,
        "rtx 4070": 1200, "rtx 4060 ti": 1000, "rtx 4060": 800,
        "rtx 4050": 700,
        # RTX 30 series
        "rtx 3090": 1800, "rtx 3080": 1500, "rtx 3070 ti": 1200,
        "rtx 3070": 1000, "rtx 3060 ti": 900, "rtx 3060": 700,
        "rtx 3050": 600,
        # GTX series (budget friendly)
        "gtx 1660 ti": 600, "gtx 1660": 550, "gtx 1650": 450,
        "gtx 1050 ti": 400, "gtx 1050": 350,
    }
    filter_spec("gpu", gpu_min_prices, budget_threshold=1000)

    # ==========================================================================
    # Phone Model Filtering (Electronics)
    # ==========================================================================
    phone_min_prices = {
        # iPhones
        "iphone 16 pro max": 1200, "iphone 16 pro": 1000, "iphone 16 plus": 900,
        "iphone 15 pro max": 1100, "iphone 15 pro": 900, "iphone 15 plus": 800,
        "iphone 14 pro max": 900, "iphone 14 pro": 800,
        # Samsung Galaxy
        "galaxy s24 ultra": 1300, "galaxy s24+": 1000, "galaxy s24": 800,
        "galaxy s23 ultra": 1100, "galaxy s23+": 900,
        "galaxy z fold": 1800, "galaxy z flip": 1000,
        "galaxy note": 900,
        # Google Pixel
        "pixel 9 pro xl": 1100, "pixel 9 pro": 1000, "pixel 9": 800,
        "pixel 8 pro": 900, "pixel 8a": 500, "pixel 8": 700,
        # OnePlus
        "oneplus 12": 800, "oneplus 11": 700,
    }
    filter_spec("phone", phone_min_prices, budget_threshold=600)
    filter_spec("model", phone_min_prices, budget_threshold=600)

    # ==========================================================================
    # Pet Breed Filtering (Pets)
    # ==========================================================================
    if detected_category == "pets":
        # Premium dog breeds (purebred from breeder prices)
        dog_breed_prices = {
            # Very expensive breeds
            "tibetan mastiff": 3000, "samoyed": 2500, "french bulldog": 2500,
            "english bulldog": 2500, "chow chow": 2000, "akita": 2000,
            "rottweiler": 1500, "german shepherd": 1500, "golden retriever": 1500,
            "labrador": 1200, "bernese mountain": 1500, "cavalier": 2000,
            "portuguese water": 2500, "irish wolfhound": 2000, "great dane": 1500,
            # Moderately expensive
            "husky": 1000, "corgi": 1000, "shiba inu": 1200, "beagle": 800,
            "poodle": 1200, "maltese": 1000, "yorkshire": 1200, "pomeranian": 1000,
            "boston terrier": 900, "cocker spaniel": 1000, "border collie": 1000,
            "australian shepherd": 1000, "doberman": 1200, "boxer": 1000,
            "dachshund": 800, "pug": 1000, "chihuahua": 600, "shih tzu": 800,
            # Budget friendly (shelter/rescue prices)
            "mixed breed": 150, "mutt": 150, "rescue": 200,
        }
        filter_spec("breed", dog_breed_prices, budget_threshold=500)
        filter_spec("dog_breed", dog_breed_prices, budget_threshold=500)

        # Premium cat breeds
        cat_breed_prices = {
            "savannah": 5000, "bengal": 2000, "persian": 1500, "maine coon": 1500,
            "ragdoll": 1200, "british shorthair": 1500, "scottish fold": 1500,
            "sphynx": 2000, "russian blue": 1000, "siamese": 800, "abyssinian": 1000,
            "burmese": 800, "birman": 700, "himalayan": 1000, "exotic shorthair": 1200,
            "devon rex": 1500, "norwegian forest": 1000, "siberian": 1200,
            # Budget friendly
            "domestic shorthair": 100, "mixed": 100, "rescue": 150,
        }
        filter_spec("cat_breed", cat_breed_prices, budget_threshold=400)

        # Small pet pricing (hamsters, guinea pigs, etc.)
        small_pet_prices = {
            # Hamsters - most are affordable
            "syrian hamster": 20, "golden hamster": 20, "teddy bear hamster": 25,
            "dwarf hamster": 15, "roborovski": 20, "winter white": 20,
            "chinese hamster": 20, "campbell": 15,
            # Guinea pigs
            "guinea pig": 40, "skinny pig": 100, "teddy guinea": 50,
            # Rabbits
            "holland lop": 75, "netherland dwarf": 50, "mini rex": 50,
            "lionhead": 75, "flemish giant": 100,
        }
        # Don't filter small pets for budget - they're all affordable
        # But do filter if max_budget is very low
        if max_budget and max_budget < 30:
            filter_spec("breed", small_pet_prices, budget_threshold=30)

    # ==========================================================================
    # Furniture Material Filtering
    # ==========================================================================
    if detected_category == "furniture":
        premium_materials = {
            "solid wood": 800, "hardwood": 700, "walnut": 1000, "mahogany": 1200,
            "teak": 1000, "oak": 600, "cherry wood": 800, "maple": 600,
            "leather": 800, "genuine leather": 1000, "top grain leather": 1200,
            "full grain leather": 1500, "italian leather": 1500,
            "marble": 1000, "granite": 800, "quartz": 700,
            "handmade": 600, "artisan": 700, "custom": 800,
        }
        filter_spec("material", premium_materials, budget_threshold=500)
        filter_spec("upholstery", premium_materials, budget_threshold=500)

    # ==========================================================================
    # Premium Brand Filtering (Generic)
    # ==========================================================================
    # Brands that command premium prices - filter if on tight budget
    premium_brand_prices = {
        # Electronics
        "apple": 800, "sony": 500, "bose": 300, "bang & olufsen": 1000,
        "dyson": 400, "miele": 600, "thermador": 2000, "sub-zero": 5000,
        # Furniture
        "herman miller": 1000, "steelcase": 800, "restoration hardware": 1500,
        "pottery barn": 500, "west elm": 400, "crate & barrel": 400,
        "arhaus": 1500, "ethan allen": 1200, "room & board": 800,
        # Fashion/Accessories
        "gucci": 1000, "louis vuitton": 1500, "prada": 1000, "burberry": 600,
        "canada goose": 800, "moncler": 1200, "north face": 200,
        # Sports
        "peloton": 1500, "nordictrack": 1000, "bowflex": 600,
        "trek": 800, "specialized": 1000, "giant": 500,
        # Musical Instruments
        "gibson": 1500, "fender american": 1200, "martin": 1500, "taylor": 1200,
        "steinway": 50000, "yamaha grand": 5000, "roland": 500,
    }
    if budget_tier == "budget":
        filter_spec("brand", premium_brand_prices, budget_threshold=300)

    # ==========================================================================
    # Appliance Tier Filtering
    # ==========================================================================
    if detected_category == "appliances":
        premium_appliances = {
            # Refrigerators
            "sub-zero": 8000, "thermador": 4000, "viking": 4000,
            "kitchenaid": 2000, "samsung family hub": 3000, "lg instaview": 2500,
            # Washers/Dryers
            "miele": 2500, "speed queen": 1500, "electrolux": 1200,
            # Vacuums
            "dyson v15": 700, "dyson v12": 550, "miele": 1000, "rainbow": 2000,
            # Kitchen
            "wolf": 5000, "thermador": 3000, "viking": 3000, "la cornue": 15000,
            "vitamix": 500, "breville": 300,
        }
        filter_spec("model", premium_appliances, budget_threshold=500)
        filter_spec("brand", premium_appliances, budget_threshold=500)

    intelligence["specs_discovered"] = specs
    return intelligence


def validate_extraction_against_requirements(
    products: List[Dict[str, Any]],
    requirements: Dict[str, Any],
    vendor_domain: str
) -> Dict[str, Any]:
    """
    Post-extraction validation: Check if extracted products match ALL hard requirements.

    This validates against:
    1. Budget constraints (budget_max, budget_min)
    2. Hard user requirements (must-have features from query)
    3. Hard discovered requirements (from intelligence/specs)

    Detects cases where:
    - URL had filters but products don't match
    - Navigation lost important filters
    - Site's filters didn't work as expected

    Args:
        products: List of extracted products
        requirements: Dict with budget, hard_requirements, specs, etc.
        vendor_domain: Vendor name for logging

    Returns:
        {
            "valid": bool,
            "passing_count": int,
            "failing_count": int,
            "failure_ratio": float,
            "failures_by_reason": Dict[str, int],
            "warnings": List[str],
            "filtered_products": List[Dict]  # Only products meeting requirements
        }
    """
    if not products:
        return {
            "valid": True,
            "passing_count": 0,
            "failing_count": 0,
            "failure_ratio": 0.0,
            "failures_by_reason": {},
            "warnings": [],
            "filtered_products": []
        }

    if not requirements:
        return {
            "valid": True,
            "passing_count": len(products),
            "failing_count": 0,
            "failure_ratio": 0.0,
            "failures_by_reason": {},
            "warnings": [],
            "filtered_products": products
        }

    # Extract requirement constraints
    budget_max = requirements.get("budget_max") or requirements.get("price_max")
    budget_min = requirements.get("budget_min") or requirements.get("price_min")
    hard_requirements = requirements.get("hard_requirements", [])
    required_specs = requirements.get("required_specs", {})
    excluded_terms = requirements.get("excluded_terms", [])

    # Also check for requirements in nested structures
    if not hard_requirements and "user_requirements" in requirements:
        user_reqs = requirements["user_requirements"]
        if isinstance(user_reqs, dict):
            hard_requirements = user_reqs.get("must_have", [])
            excluded_terms = user_reqs.get("must_not_have", excluded_terms)

    passing = []
    failing = []
    failures_by_reason = {}

    def record_failure(reason: str):
        failures_by_reason[reason] = failures_by_reason.get(reason, 0) + 1

    def extract_price(product: Dict) -> Optional[float]:
        """Extract numeric price from product."""
        price_val = product.get("price")
        if isinstance(price_val, (int, float)):
            return float(price_val)
        elif isinstance(price_val, str):
            match = re.search(r'[\$]?([\d,]+(?:\.\d{2})?)', price_val)
            if match:
                return float(match.group(1).replace(",", ""))
        return None

    def product_text(product: Dict) -> str:
        """Get searchable text from product."""
        parts = [
            str(product.get("name", "")),
            str(product.get("title", "")),
            str(product.get("description", "")),
        ]
        # Include specs if present
        specs = product.get("specs", {})
        if isinstance(specs, dict):
            parts.extend(str(v) for v in specs.values())

        # Include URL - many retailers encode key attributes in SEO-friendly URLs
        # E.g., newegg.com URLs contain "geforce-rtx-5080" even if product name doesn't
        url = product.get("url", "")
        if url:
            # Extract path component and normalize hyphens to spaces
            from urllib.parse import urlparse
            path = urlparse(url).path
            # Convert URL path to searchable text (e.g., "geforce-rtx-5080" -> "geforce rtx 5080")
            url_text = path.replace("-", " ").replace("/", " ").replace("_", " ")
            parts.append(url_text)

        return " ".join(parts).lower()

    for product in products:
        product_passed = True
        text = product_text(product)

        # Check 1: Budget max
        if budget_max:
            price = extract_price(product)
            if price is not None and price > budget_max:
                product_passed = False
                record_failure(f"over_budget_${budget_max:.0f}")

        # Check 2: Budget min (for quality floors)
        if budget_min and product_passed:
            price = extract_price(product)
            if price is not None and price < budget_min:
                product_passed = False
                record_failure(f"under_minimum_${budget_min:.0f}")

        # Check 3: Hard requirements - REMOVED
        # Keyword-based requirement matching is brittle and causes false rejections.
        # The LLM viability filter (downstream) handles semantic matching much better.
        # It can understand that "Gaming Laptop" on an NVIDIA-filtered page is an NVIDIA laptop,
        # even if the product name doesn't literally contain "NVIDIA GPU".

        # Check 4: Required specs
        if required_specs and product_passed:
            product_specs = product.get("specs", {})
            for spec_key, spec_value in required_specs.items():
                if spec_key not in product_specs:
                    # Extract actual value - spec_value may be a dict like {"value": "RTX 4060", ...}
                    if isinstance(spec_value, dict):
                        actual_value = spec_value.get("value", "")
                    else:
                        actual_value = str(spec_value)

                    # Check if spec mentioned in product text
                    if actual_value.lower() not in text:
                        product_passed = False
                        record_failure(f"missing_spec_{spec_key}")
                        break

        # Check 5: Excluded terms (must NOT have)
        if excluded_terms and product_passed:
            for excluded in excluded_terms:
                if excluded.lower() in text:
                    product_passed = False
                    record_failure(f"has_excluded_{excluded}")
                    break

        if product_passed:
            passing.append(product)
        else:
            failing.append(product)

    total = len(products)
    failure_ratio = len(failing) / total if total > 0 else 0

    warnings = []
    if failure_ratio > 0.7:
        # More than 70% failing - something went wrong with filters
        top_reasons = sorted(failures_by_reason.items(), key=lambda x: -x[1])[:3]
        reasons_str = ", ".join(f"{r}: {c}" for r, c in top_reasons)
        warning = (
            f"[Validation] {vendor_domain}: {len(failing)}/{total} products "
            f"({failure_ratio:.0%}) failed requirements. Top reasons: {reasons_str}"
        )
        warnings.append(warning)
        logger.warning(warning)
    elif failure_ratio > 0.3:
        logger.info(
            f"[Validation] {vendor_domain}: {len(failing)}/{total} products "
            f"failed requirements, {len(passing)} passed"
        )

    return {
        "valid": failure_ratio < 0.7,
        "passing_count": len(passing),
        "failing_count": len(failing),
        "failure_ratio": failure_ratio,
        "failures_by_reason": failures_by_reason,
        "warnings": warnings,
        "filtered_products": passing
    }


def _get_requirement_variations(requirement: str) -> List[str]:
    """
    Get common variations of a requirement term for flexible matching.

    E.g., "nvidia" -> ["nvidia", "geforce", "rtx", "gtx"]
    """
    # Known tech term variations (kept for backwards compatibility)
    tech_variations = {
        "nvidia": ["nvidia", "geforce", "rtx", "gtx", "quadro"],
        "amd": ["amd", "radeon", "ryzen", "threadripper"],
        "intel": ["intel", "core i", "xeon", "celeron", "pentium"],
        "ssd": ["ssd", "solid state", "nvme", "m.2"],
        "hdd": ["hdd", "hard drive", "hard disk"],
        "ram": ["ram", "memory", "ddr4", "ddr5"],
        "wifi": ["wifi", "wi-fi", "wireless", "802.11"],
        "bluetooth": ["bluetooth", "bt "],
        "usb-c": ["usb-c", "usb type-c", "type-c", "thunderbolt"],
        "touchscreen": ["touchscreen", "touch screen", "touch display"],
        "backlit": ["backlit", "back-lit", "keyboard light", "rgb keyboard"],
    }

    # Check known tech variations first
    for key, vars in tech_variations.items():
        if key in requirement or requirement in key:
            return vars

    # GENERIC APPROACH: Generate variations dynamically
    variations = [requirement]

    # 1. Add singular/plural forms
    req_lower = requirement.lower()
    if req_lower.endswith('s') and len(req_lower) > 3:
        variations.append(req_lower[:-1])  # Remove trailing 's'
    elif not req_lower.endswith('s'):
        variations.append(req_lower + 's')  # Add trailing 's'

    # 2. Add individual words for multi-word requirements
    words = req_lower.split()
    if len(words) > 1:
        # Add each significant word (skip common words)
        skip_words = {'for', 'the', 'a', 'an', 'to', 'of', 'and', 'or', 'in', 'on', 'at', 'by'}
        for word in words:
            if word not in skip_words and len(word) > 2:
                variations.append(word)
                # Also add singular/plural of each word
                if word.endswith('s') and len(word) > 3:
                    variations.append(word[:-1])
                elif not word.endswith('s'):
                    variations.append(word + 's')

    # 3. Handle common purchase/availability phrases generically
    purchase_terms = ['available', 'in stock', 'buy', 'purchase', 'for sale',
                      'add to cart', 'shop', 'order', 'get it']
    if any(term in req_lower for term in ['purchase', 'sale', 'buy', 'available']):
        variations.extend(purchase_terms)

    return list(set(variations))  # Deduplicate


# ============================================================================
# Search Provider Configuration
# ============================================================================

# Search provider: "google" or "duckduckgo"
SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "google")

logger.info(f"[ResearchOrchestrator] Search provider: {SEARCH_PROVIDER}")

# Import document manager for snapshot compression
try:
    from orchestrator.document_tools import get_document_manager
except ImportError:
    logger.warning("Document tools not available, snapshot compression disabled")
    get_document_manager = None

# Import browser agent for multi-page browsing
try:
    from orchestrator.browser_agent import deep_browse, detect_navigation_opportunities
except ImportError:
    logger.warning("Browser agent not available, multi-page browsing disabled")
    deep_browse = None
    detect_navigation_opportunities = None


# ============================================================================
# PUBLIC API - Reusable Phase Functions for Adaptive Research
# ============================================================================

async def gather_intelligence(
    query: str,
    research_goal: str,
    max_sources: int = 10,
    session_id: str = "default",
    web_vision_session_id: str = None,  # NEW: Web Vision session ID
    event_emitter: Optional[Any] = None,
    human_assist_allowed: bool = True,  # Default: enabled
    enable_deep_browse: bool = True,  # Enable multi-page browsing
    mode: str = "standard",  # Research mode: "standard" or "deep"
    query_type: str = "product",  # Query type for planning: "product", "information", etc.
    research_context: Dict[str, Any] = None  # NEW: Context from Planner with pre-planned queries
) -> Dict[str, Any]:
    """
    Phase 1: Gather intelligence from forums, reviews, communities.

    This is the CONTEXT GATHERING phase. It learns:
    - What matters to people (key topics)
    - Who is credible (reputable sources)
    - What to look for (quality criteria)
    - What to avoid (red flags)

    Args:
        query: Original search query
        research_goal: What we're trying to learn
        max_sources: Max sources to gather from (default: 10)
        session_id: Session ID for browser context (enables CAPTCHA intervention)
        event_emitter: Optional progress events

    Returns:
        {
            "intelligence": {
                "key_topics": [...],
                "credible_sources": [...],
                "important_criteria": [...],
                "things_to_avoid": [...],
                "price_ranges": {...}
            },
            "sources": [...],
            "stats": {...}
        }
    """
    from orchestrator import web_vision_mcp
    from orchestrator.llm_candidate_filter import llm_filter_candidates

    # Create Web Vision session ID if not provided
    if web_vision_session_id is None:
        web_vision_session_id = f"{session_id}_intelligence"

    logger.info(f"[Phase1] Gathering intelligence for: {query} (session={web_vision_session_id})")

    if event_emitter:
        await event_emitter.emit_phase_started("phase1", "intelligence_gathering")

    # Generate context-gathering queries using LLM planner
    # Focus on high-quality intelligence sources: forums, buying guides
    from orchestrator.query_planner import plan_phase1_queries

    research_context = research_context or {}
    user_query = research_context.get("user_query")
    entities = research_context.get("entities", [])
    research_type = research_context.get("research_type", "general")

    # NEW: Extract deep_read mode for multi-page reading
    deep_read_mode = research_context.get("deep_read", False)
    deep_read_max_pages = research_context.get("max_pages", 5)
    if deep_read_mode:
        logger.info(f"[Phase1] Deep read mode enabled: max_pages={deep_read_max_pages}")

    # NEW: Extract intent for query planning
    intent = research_context.get("intent", "commerce")
    intent_metadata = research_context.get("intent_metadata", {})
    logger.info(f"[Phase1] Intent: {intent}, metadata: {intent_metadata}")

    # NAVIGATION/SITE_SEARCH with target: Skip query planning, use direct navigation
    if intent == "navigation" and intent_metadata.get("target_url"):
        # Navigation with target_url - will use direct navigation path below
        context_queries = []
        logger.info(f"[Phase1] Navigation intent with target_url - skipping query planning")
    elif intent == "site_search" and intent_metadata.get("site_name"):
        # Site search - will use direct navigation path below
        context_queries = []
        logger.info(f"[Phase1] Site search intent - skipping query planning")
    elif "site:" in query:
        # Pre-built site-specific query (e.g., for content_reference lookup)
        # Use directly without LLM planning
        context_queries = [query]
        logger.info(f"[Phase1] Using pre-built site-specific query directly: {query[:80]}...")
    else:
        # Normal path - use LLM query planner
        query_for_planning = query
        logger.info(f"[Phase1] Planning search query for: '{query_for_planning}'")

        context_queries = await plan_phase1_queries(
            user_query=query_for_planning,
            intent=intent,
            intent_metadata=intent_metadata,
            solver_url=os.environ.get("SOLVER_URL", "http://127.0.0.1:8000"),
            solver_model_id=os.environ.get("SOLVER_MODEL_ID", "qwen3-coder"),
            solver_api_key=os.environ.get("SOLVER_API_KEY", "qwen-local")
        )
        logger.info(f"[Phase1] Generated search query: {context_queries}")

    # Use planned queries (optimized for intelligence, not product listings)
    queries_to_use = context_queries

    # Gather context from multiple angles using Web Vision search
    context_findings = []
    reliability_tracker = get_tracker()

    # NAVIGATION INTENT: Direct URL navigation when no queries (skip Google search)
    if intent == "navigation" and not queries_to_use:
        target_url = intent_metadata.get("target_url", "")
        goal = intent_metadata.get("goal", query)
        if target_url:
            logger.info(f"[Phase1] NAVIGATION: Direct navigation to {target_url} (goal: {goal[:50]}...)")
            try:
                # Navigate directly to target URL and extract content
                result = await _web_vision_visit_and_read(
                    url=target_url,
                    reading_goal=goal,
                    session_id=web_vision_session_id
                )
                if result:
                    context_findings.append({
                        "url": target_url,
                        "title": result.get("title", ""),
                        "summary": result.get("summary", ""),
                        "key_points": result.get("key_points", []),
                        "claims": result.get("claims", []),
                        "source_type": "direct_navigation",
                        "extracted_links": result.get("extracted_links", [])  # Include links for navigation
                    })
                    link_count = len(result.get("extracted_links", []))
                    logger.info(f"[Phase1] NAVIGATION: Extracted content from {target_url} ({link_count} links)")
                else:
                    logger.warning(f"[Phase1] NAVIGATION: Failed to extract content from {target_url}")
            except Exception as e:
                logger.error(f"[Phase1] NAVIGATION: Error navigating to {target_url}: {e}")
        else:
            logger.warning(f"[Phase1] NAVIGATION: No target_url provided in intent_metadata")

    # SITE_SEARCH INTENT: Direct URL navigation when no queries
    elif intent == "site_search" and not queries_to_use:
        site_name = intent_metadata.get("site_name", "")
        search_term = intent_metadata.get("search_term", query)
        if site_name:
            # Build URL - assume .com if not specified
            domain = site_name.lower().strip()
            if not domain.startswith("http"):
                if "." not in domain:
                    domain = f"{domain}.com"
                target_url = f"https://{domain}"
            else:
                target_url = domain
            logger.info(f"[Phase1] SITE_SEARCH: Direct navigation to {target_url} (search: {search_term[:50]}...)")
            try:
                result = await _web_vision_visit_and_read(
                    url=target_url,
                    reading_goal=search_term,
                    session_id=web_vision_session_id
                )
                if result:
                    extracted_links = result.get("extracted_links", [])
                    link_count = len(extracted_links)
                    logger.info(f"[Phase1] SITE_SEARCH: Extracted {link_count} links from {target_url}")

                    # Try to find a matching link and click through to it
                    matching_link = None
                    search_lower = search_term.lower()
                    for link in extracted_links:
                        title_lower = link.get("title", "").lower()
                        # Check if search term words appear in link title
                        search_words = [w for w in search_lower.split() if len(w) > 3]
                        matches = sum(1 for w in search_words if w in title_lower)
                        if matches >= len(search_words) * 0.6:  # 60% of words match
                            matching_link = link
                            logger.info(f"[Phase1] SITE_SEARCH: Found matching link: {link.get('title', '')[:60]}")
                            break

                    if matching_link:
                        # Navigate to the matching link
                        thread_url = matching_link.get("url", "")
                        logger.info(f"[Phase1] SITE_SEARCH: Clicking through to {thread_url}")
                        thread_result = await _web_vision_visit_and_read(
                            url=thread_url,
                            reading_goal=search_term,
                            session_id=web_vision_session_id
                        )
                        if thread_result:
                            context_findings.append({
                                "url": thread_url,
                                "title": thread_result.get("title", matching_link.get("title", "")),
                                "summary": thread_result.get("summary", ""),
                                "text_content": thread_result.get("text_content", ""),
                                "key_points": thread_result.get("key_points", []),
                                "claims": thread_result.get("claims", []),
                                "source_type": "thread_content",
                                "extracted_links": thread_result.get("extracted_links", [])
                            })
                            logger.info(f"[Phase1] SITE_SEARCH: Successfully extracted thread content")
                        else:
                            # Fall back to homepage content if thread visit failed
                            logger.warning(f"[Phase1] SITE_SEARCH: Thread visit failed, using homepage content")
                            context_findings.append({
                                "url": target_url,
                                "title": result.get("title", ""),
                                "summary": result.get("summary", ""),
                                "key_points": result.get("key_points", []),
                                "claims": result.get("claims", []),
                                "source_type": "direct_navigation",
                                "extracted_links": extracted_links
                            })
                    else:
                        # No matching link found, return homepage content with links
                        logger.info(f"[Phase1] SITE_SEARCH: No matching link found, returning homepage content")
                        context_findings.append({
                            "url": target_url,
                            "title": result.get("title", ""),
                            "summary": result.get("summary", ""),
                            "key_points": result.get("key_points", []),
                            "claims": result.get("claims", []),
                            "source_type": "direct_navigation",
                            "extracted_links": extracted_links
                        })
                else:
                    logger.warning(f"[Phase1] SITE_SEARCH: Failed to extract content from {target_url}")
            except Exception as e:
                logger.error(f"[Phase1] SITE_SEARCH: Error navigating to {target_url}: {e}")
        else:
            logger.warning(f"[Phase1] SITE_SEARCH: No site_name provided in intent_metadata")

    # Standard flow: Google search with queries
    for ctx_query in queries_to_use:
        # Perform Web Vision search
        raw_candidates = await _web_vision_search(
            query=ctx_query,
            max_results=10,
            session_id=web_vision_session_id,
            event_emitter=event_emitter
        )

        # Use intelligence-specific filtering for Phase 1
        # Phase C: Request 6 candidates (pool) to ensure 3 good sources after retries
        logger.info(f"[Phase1] Filtering {len(raw_candidates)} candidates for: {ctx_query}")

        # Extract key requirements from query for smarter filtering
        key_requirements = _extract_key_requirements_from_query(query)
        if key_requirements:
            logger.info(f"[Phase1] Key requirements for filtering: {key_requirements}")

        candidates = await filter_candidates_for_intelligence(
            raw_candidates,
            query=ctx_query,
            max_candidates=6,  # Request 6 to have backup candidates
            intent=intent,
            key_requirements=key_requirements
        )
        logger.info(f"[Phase1] Intelligence filtering complete: {len(candidates)} candidates in pool")

        # Phase C: Retry logic - try up to 4 candidates to get 2 good sources
        target_good_sources = 2  # Reduced from 3 to speed up Phase 1
        good_sources_this_query = 0
        failed_urls = []

        for candidate in candidates:
            # Stop if we've reached overall max OR enough good sources for this query
            if len(context_findings) >= max_sources:
                logger.info(f"[Phase1] Reached max_sources limit ({max_sources}), stopping")
                break
            if good_sources_this_query >= target_good_sources:
                logger.info(f"[Phase1] Got {target_good_sources} good sources for this query, moving on")
                break

            candidate_url = candidate.get("url", "unknown")
            logger.info(f"[Phase1] Trying source ({good_sources_this_query + 1}/target:{target_good_sources}): {candidate_url[:60]}...")

            try:
                # Visit page using Web Vision MCP
                result = await _web_vision_visit_and_read(
                    url=candidate["url"],
                    reading_goal=f"Learn what matters when researching: {query}",
                    session_id=web_vision_session_id
                )

                # Check if visit failed (returns None for 404, timeout, etc.)
                if result is None:
                    failed_urls.append(candidate_url)
                    logger.warning(f"[Phase1] Source failed (404/error), trying next... Failed: {len(failed_urls)}")
                    continue

                # Check if page redirected to significantly different content
                final_url = result.get("url", candidate_url)
                if final_url != candidate_url:
                    # Extract path from both URLs to compare
                    from urllib.parse import urlparse
                    original_path = urlparse(candidate_url).path.rstrip('/').lower()
                    final_path = urlparse(final_url).path.rstrip('/').lower()

                    # Check if redirect is to different content:
                    # - Paths must be equal, OR
                    # - Final must be a subdirectory (e.g., /eggnog → /eggnog/recipe is OK)
                    # - But /eggnog → /eggnog-dip is NOT OK (different page, not subdirectory)
                    is_subdirectory = final_path.startswith(original_path + '/')
                    paths_match = original_path == final_path

                    if not paths_match and not is_subdirectory:
                        logger.warning(
                            f"[Phase1] URL redirected to different content: {original_path} → {final_path}, "
                            f"trying next... Failed: {len(failed_urls) + 1}"
                        )
                        failed_urls.append(candidate_url)
                        continue

                # NEW: Goal-directed navigation for informational queries
                # Instead of hardcoded click-through, use LLM agent to navigate
                # The agent can handle complex goals like "go to last page" or "find specific thread"
                extracted_links = result.get("extracted_links", [])
                if extracted_links and intent in ("informational", "site_search", "navigation"):
                    # Determine if we should use goal-directed navigation
                    # Use the original user query as the goal for the agent
                    user_goal = research_context.get("user_query", query)

                    # Check if this looks like a list/index page that needs navigation
                    page_has_navigation = len(extracted_links) > 3
                    content_is_sparse = len(result.get("text_content", "")) < 500

                    if page_has_navigation and content_is_sparse:
                        logger.info(f"[Phase1] GOAL-BROWSE: List page detected, using LLM agent for navigation")
                        logger.info(f"[Phase1] GOAL-BROWSE: Goal='{user_goal[:80]}...'")

                        try:
                            browse_result = await _goal_directed_browse(
                                url=candidate_url,
                                goal=user_goal,
                                session_id=web_vision_session_id,
                                max_steps=10
                            )

                            if browse_result and browse_result.get("text_content"):
                                # Replace result with agent's findings
                                result = {
                                    "url": browse_result.get("url", candidate_url),
                                    "text_content": browse_result.get("text_content", ""),
                                    "summary": browse_result.get("summary", ""),
                                    "source_type": "goal_directed_browse",
                                    "pages_visited": browse_result.get("pages_visited", []),
                                    "goal_achieved": browse_result.get("goal_achieved", False),
                                    "extracted_links": extracted_links  # Keep original links
                                }
                                logger.info(
                                    f"[Phase1] GOAL-BROWSE: Success - visited {len(browse_result.get('pages_visited', []))} pages, "
                                    f"goal_achieved={browse_result.get('goal_achieved', False)}"
                                )
                            else:
                                logger.warning(f"[Phase1] GOAL-BROWSE: Agent returned no content, using original result")
                        except Exception as browse_err:
                            logger.warning(f"[Phase1] GOAL-BROWSE: Agent navigation failed: {browse_err}, using original result")

                # NEW: Check if multi-page browsing needed (e.g., forum threads)
                # Enable deep browse for:
                # 1. Commerce/transactional queries (product listings)
                # 2. Deep read mode (user explicitly requested full thread reading)
                should_attempt_deep_browse = (
                    result and
                    enable_deep_browse and
                    deep_browse and
                    detect_navigation_opportunities and
                    (intent in ["commerce", "transactional"] or deep_read_mode)  # Commerce OR deep_read mode
                )

                if not should_attempt_deep_browse and enable_deep_browse and not deep_read_mode and intent not in ["commerce", "transactional"]:
                    logger.info(f"[Phase1] Skipping deep browse check - intent={intent} (only commerce/deep_read triggers deep browse)")

                if should_attempt_deep_browse:
                    try:
                        # Get sanitized text content from result
                        text_content = result.get("text_content", "")
                        if text_content:
                            # Check for multi-page opportunities
                            nav_check = await detect_navigation_opportunities(
                                page_content=text_content,
                                url=candidate["url"],
                                browsing_goal=f"Learn what matters when researching: {query}"
                            )

                            # If multi-page thread/discussion detected, do deep browse
                            if nav_check.get("has_more_pages") and nav_check.get("navigation_type") in ["thread", "pagination"]:
                                logger.info(
                                    f"[Phase1] Multi-page {nav_check['navigation_type']} detected, "
                                    f"enabling deep browse for {candidate['url'][:60]}"
                                )

                                # Deep browse to get all pages (using Web Vision session)
                                # Pass LLM config so should_continue_browsing() can evaluate
                                # Use deep_read_max_pages if in deep read mode, otherwise 5 for standard
                                browse_max_pages = deep_read_max_pages if deep_read_mode else 5
                                deep_result = await deep_browse(
                                    url=candidate["url"],
                                    browsing_goal=f"Learn what matters when researching: {query}",
                                    max_pages=browse_max_pages,  # Use deep_read setting or default 5
                                    session_id=web_vision_session_id,  # Pass Web Vision session
                                    llm_url=os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions"),
                                    llm_model=os.getenv("SOLVER_MODEL_ID", "qwen3-coder"),
                                    llm_api_key=os.getenv("SOLVER_API_KEY", "qwen-local")
                                )

                                if deep_result:
                                    result = deep_result  # Replace single-page with multi-page result
                                    logger.info(
                                        f"[Phase1] Deep browse complete: "
                                        f"{deep_result.get('pages_visited', 1)} pages aggregated"
                                    )
                    except Exception as deep_error:
                        logger.warning(f"[Phase1] Deep browse failed, using single-page result: {deep_error}")
                        # Continue with single-page result

                # Success - tag with source classification for confidence tracking
                source_type = candidate.get("source_type") or _fallback_source_type(candidate_url)
                quality_score = candidate.get("quality_score")
                reliability_score = candidate.get("reliability_score")
                if quality_score is None:
                    reliability_score = reliability_tracker.get_reliability(candidate_url)
                    quality_score = reliability_score

                result["source_url"] = candidate_url
                result["source_type"] = source_type
                result["source_reliability"] = quality_score
                result["source_quality"] = quality_score
                result["source_reliability_db"] = reliability_score
                result["source_quality_confidence"] = candidate.get("quality_confidence")

                reliability_tracker.log_extraction(
                    url=candidate_url,
                    extraction_type="intelligence",
                    success=True,
                    confidence=float(quality_score) if quality_score is not None else 0.5,
                    metadata={"source_type": source_type},
                )

                # Add to findings
                context_findings.append(result)
                good_sources_this_query += 1
                logger.info(
                    f"[Phase1] ✓ Good source {good_sources_this_query}/{target_good_sources} "
                    f"({source_type}, score={quality_score:.2f}): {candidate_url[:60]}"
                )

            except Exception as e:
                failed_urls.append(candidate_url)
                logger.error(f"[Phase1] Error visiting {candidate_url}: {e}")
                reliability_tracker.log_extraction(
                    url=candidate_url,
                    extraction_type="intelligence",
                    success=False,
                    confidence=0.0,
                    error_type=type(e).__name__,
                )
                continue  # Try next candidate

        # Log summary for this query
        if failed_urls:
            logger.info(f"[Phase1] Query complete. Good: {good_sources_this_query}, Failed: {len(failed_urls)} ({failed_urls})")

        if len(context_findings) >= max_sources:
            break

    # Parse budget intent from user query BEFORE intelligence extraction
    # This ensures we filter specs appropriately based on user's stated constraints
    budget_intent = _parse_budget_intent_from_query(query)

    # Extract meta-intelligence (now budget-aware)
    intelligence = await _extract_intelligence_from_findings(context_findings, query, budget_intent)

    # Normalize price_range to handle edge cases (min==max, inverted ranges, etc.)
    intelligence = _normalize_price_range(intelligence)

    # Post-processing: Filter specs that are incompatible with user's budget
    # This catches any specs the LLM missed filtering
    intelligence = _filter_specs_by_budget(intelligence, budget_intent)

    stats = {
        "sources_checked": len(context_findings),
        "queries_used": len(queries_to_use),
        "intelligence_extracted": bool(intelligence)
    }

    logger.info(f"[Phase1] Complete: {stats['sources_checked']} sources analyzed")

    if event_emitter:
        await event_emitter.emit_phase_complete("phase1", intelligence)

    return {
        "intelligence": intelligence,
        "sources": context_findings,
        "stats": stats
    }


async def search_products_with_comparison(
    query: str,
    intelligence: Dict[str, Any],
    max_retailers: int = 3,
    max_products: int = 4,
    session_id: str = "default",
    web_vision_session_id: str = None,
    event_emitter: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Phase 2: Visit retailers, extract products, compare deals.
    Uses retailer selection and comparison tracking.

    Args:
        query: Original user query
        intelligence: Phase 1 intelligence with specs, price range, etc.
        max_retailers: Max retailers to visit (default: 3)
        max_products: Max products to track (default: 4)
        session_id: Session ID for browser context
        web_vision_session_id: Web Vision session ID
        event_emitter: Optional progress events

    Returns:
        {
            "findings": [...],  # Top products
            "synthesis": {...},  # Summary stats
            "stats": {...}
        }
    """
    from orchestrator import web_vision_mcp

    # Create Web Vision session ID if not provided
    if web_vision_session_id is None:
        web_vision_session_id = f"{session_id}_shopping"

    logger.info(f"[Phase2-Comparison] Starting retailer comparison for: {query}")

    if event_emitter:
        await event_emitter.emit_phase_started("phase2", "shopping_comparison")

    # Step 1: Optimize query for shopping
    shopping_query = await optimize_query_for_phase(
        user_query=query,
        phase="shopping",
        context={"intelligence": intelligence}
    )

    # Step 1.5: Simplify query for retailer compatibility (LLM-based)
    shopping_query = await simplify_query_for_retailers_async(shopping_query)

    logger.info(f"[Phase2-Comparison] Shopping query: '{query}' → '{shopping_query}'")

    # Extract budget max from intelligence for pre-filtering
    budget_max = None
    if intelligence:
        price_range = intelligence.get("price_range", {})
        if isinstance(price_range, dict):
            budget_max = price_range.get("budget_max") or price_range.get("max")
        elif isinstance(price_range, str):
            # Parse "under $800" style strings
            import re
            match = re.search(r'\$?(\d+(?:,\d{3})*(?:\.\d{2})?)', price_range)
            if match:
                budget_max = float(match.group(1).replace(",", ""))

    if budget_max:
        logger.info(f"[Phase2-Comparison] Budget max: ${budget_max:.2f} (will pre-filter candidates)")

    # Step 2: Select retailers from Phase 1 intelligence
    retailers = await select_retailers_for_query(
        query=shopping_query,
        intelligence=intelligence,
        max_retailers=max_retailers
    )

    # Track whether we need to supplement with generic search
    supplement_with_generic_search = False
    min_retailers_for_good_coverage = 2

    if not retailers:
        # No retailers discovered - use only generic search
        logger.warning(
            f"[Phase2-Comparison] No retailers discovered in Phase 1 intelligence. "
            f"Using generic product search only."
        )
        return await search_products(
            query=query,
            research_goal=f"Find products matching: {query}",
            intelligence=intelligence,
            max_sources=max_retailers * 3,
            session_id=session_id,
            web_vision_session_id=web_vision_session_id,
            event_emitter=event_emitter
        )
    elif len(retailers) < min_retailers_for_good_coverage:
        # Few retailers discovered - visit them AND supplement with generic search
        logger.info(
            f"[Phase2-Comparison] Only {len(retailers)} retailer(s) discovered. "
            f"Will supplement with generic search for better coverage."
        )
        supplement_with_generic_search = True

    logger.info(f"[Phase2-Comparison] Selected {len(retailers)} retailers from intelligence: {retailers}")

    # Step 3: Initialize comparison tracker
    tracker = ProductComparisonTracker(max_products=max_products)

    # Step 4: Visit each retailer
    all_findings = []

    # Detect price priority from original query for URL sorting
    # CONTEXT DISCIPLINE: Use original query to understand user's price preference
    price_sort = detect_price_priority(query)
    if price_sort:
        logger.info(f"[Phase2-Comparison] Detected price priority: sort by {price_sort}")

    # Initialize hybrid perception pipeline for universal product extraction
    use_hybrid_extraction = os.getenv("PERCEPTION_ENABLE_HYBRID", "true").lower() == "true"

    if use_hybrid_extraction:
        from orchestrator.product_perception import ProductPerceptionPipeline, VerifiedProduct
        perception_pipeline = ProductPerceptionPipeline()
        logger.info("[Phase2-Comparison] Using click-to-verify extraction pipeline")
    else:
        logger.info("[Phase2-Comparison] Using legacy HTML-only extraction")

    for retailer in retailers:
        logger.info(f"[Phase2-Comparison] Visiting retailer: {retailer}")

        # Use constructed URL for now - the intelligent search path handles Google-based URL discovery
        # This path is for quick comparison shopping, not deep product search
        # CONTEXT DISCIPLINE: Pass price_sort from original query to sort results appropriately
        retailer_url = construct_vendor_search_url(retailer, shopping_query, sort_by_price=price_sort)

        # Visit and extract products
        try:
            # Use web vision to navigate
            from orchestrator import web_vision_mcp

            # Navigate to retailer search page
            nav_result = await web_vision_mcp.navigate(
                session_id=web_vision_session_id,
                url=retailer_url,
                wait_for="networkidle"
            )

            if not nav_result.get("success"):
                logger.warning(f"[Phase2-Comparison] Failed to navigate to {retailer}: {nav_result.get('message')}")
                continue

            # Choose extraction method
            if use_hybrid_extraction:
                # NEW: Hybrid vision+HTML extraction
                try:
                    page = await web_vision_mcp.get_page(web_vision_session_id)
                except Exception as e:
                    logger.error(f"[Phase2-Comparison] Exception getting page for {retailer}: {e}")
                    continue

                if not page:
                    logger.warning(f"[Phase2-Comparison] Failed to get page object for {retailer}")
                    continue

                logger.info(f"[Phase2-Comparison] Running click-to-verify extraction on {retailer}")

                # Build requirements from intelligence for smart prioritization
                comparison_requirements = {
                    "key_requirements": intelligence.get("key_requirements", []) if intelligence else [],
                    "price_range": intelligence.get("price_range", {}) if intelligence else {},
                    "hard_requirements": intelligence.get("key_requirements", []) if intelligence else [],
                    "specs_discovered": intelligence.get("specs_discovered", {}) if intelligence else {},
                } if intelligence else None

                # Run click-to-verify extraction (PRIMARY flow)
                # This clicks each product to navigate to PDP and extract verified data
                # Pass budget_max to pre-filter candidates before expensive PDP verification
                # Pass requirements for smart prioritization + early stopping
                verified_products = await perception_pipeline.extract_and_verify(
                    page=page,
                    url=retailer_url,
                    query=shopping_query,
                    max_products=max_products,
                    max_price=budget_max,
                    requirements=comparison_requirements,  # Smart prioritization + early stopping
                    target_viable_products=max_products
                )

                # Convert VerifiedProduct to dict format
                # All products are already PDP-verified with accurate prices
                products = []
                for vp in verified_products:
                    product = {
                        "name": vp.title,
                        "price": f"${vp.price:.2f}" if vp.price else "N/A",
                        "url": vp.url,
                        "description": "",  # Description from specs
                        "confidence": vp.extraction_confidence,
                        "vendor": retailer,
                        "extraction_method": vp.extraction_source,
                        "url_source": vp.verification_method,
                        # PDP verification metadata (all are verified)
                        "pdp_verified": True,
                        "in_stock": vp.in_stock,
                        "stock_status": vp.stock_status,
                        "rating": vp.rating,
                        "review_count": vp.review_count,
                    }

                    # Add specs to description
                    if vp.specs:
                        spec_text = ", ".join(f"{k}: {v}" for k, v in vp.specs.items() if v)
                        product["description"] = spec_text

                    # Add original/sale price info if available
                    if vp.original_price and vp.price and vp.original_price > vp.price:
                        product["original_price"] = f"${vp.original_price:.2f}"
                        product["on_sale"] = True

                    products.append(product)

                    # Log verified product
                    price_str = f"${vp.price:.2f}" if vp.price else "N/A"
                    logger.info(
                        f"[Phase2-Comparison] ✓ Verified '{vp.title[:40]}' "
                        f"price={price_str} in_stock={vp.in_stock} "
                        f"via={vp.verification_method} url={vp.url[:60]}..."
                    )

            else:
                # LEGACY: HTML-only extraction
                from orchestrator.product_extractor import extract_products_from_html

                # Capture HTML content
                content_result = await web_vision_mcp.capture_content(
                    session_id=web_vision_session_id,
                    format="html"
                )

                if not content_result.get("success"):
                    logger.warning(f"[Phase2-Comparison] Failed to capture content from {retailer}")
                    continue

                html_content = content_result.get("content", "")
                logger.info(f"[Phase2-Comparison] Extracting products from {retailer} (HTML: {len(html_content)} chars)")

                # Get LLM config
                llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
                llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
                llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

                # Extract products
                product_claims = await extract_products_from_html(
                    html=html_content,
                    url=retailer_url,
                    query=shopping_query,
                    llm_url=llm_url,
                    llm_model=llm_model,
                    llm_api_key=llm_api_key
                )

                # Convert to dict format
                products = []
                for claim in product_claims:
                    product = {
                        "name": claim.title,
                        "price": f"${claim.price:.2f}" if claim.price else "N/A",
                        "url": claim.url,
                        "description": claim.description or "",
                        "confidence": claim.confidence,
                        "vendor": retailer
                    }
                    products.append(product)

            logger.info(f"[Phase2-Comparison] {retailer}: Found {len(products)} products")

            # Add each product to tracker
            for product in products:
                # Ensure vendor field is set
                if "vendor" not in product:
                    product["vendor"] = retailer

                added = tracker.add_product(product)

                if added:
                    # Convert to finding format for backward compatibility
                    finding = {
                        "name": product.get("name", "Unknown Product"),
                        "price": product.get("price", "N/A"),
                        "vendor": retailer,
                        "url": product.get("url", ""),
                        "description": product.get("description", ""),
                        "confidence": product.get("confidence", 0.8)
                    }
                    all_findings.append(finding)

            # Log comparison status after each retailer
            logger.info(f"[Phase2-Comparison] After {retailer}:\n{tracker.get_summary()}")

            # Record extraction success/failure for schema tracking AND vendor registry
            if products:
                try:
                    ht = get_health_tracker()
                    ht.record_extraction(url=retailer_url, page_type="listing", success=True, method="phase2_comparison")
                    # Update vendor registry with success
                    vr = get_vendor_registry()
                    vr.record_visit(domain=retailer, success=True)
                except Exception as e:
                    logger.warning(f"[Phase2-Comparison] Failed to record extraction success for {retailer}: {e}")
            else:
                try:
                    ht = get_health_tracker()
                    ht.record_extraction(url=retailer_url, page_type="listing", success=False, method="phase2_comparison")
                    # Update vendor registry with failure - may suggest recovery
                    vr = get_vendor_registry()
                    recovery_strategy = vr.record_visit(domain=retailer, success=False)

                    # If registry suggests recovery, try it
                    if recovery_strategy:
                        logger.info(f"[Phase2-Recovery] {retailer} extraction failed. Trying recovery: {recovery_strategy}")
                        recovery_success = await _try_recovery_strategy(
                            retailer, retailer_url, recovery_strategy, web_vision_session_id
                        )
                        vr.record_recovery_attempt(retailer, recovery_strategy, recovery_success)
                except Exception as e:
                    logger.warning(f"[Phase2-Comparison] Failed to record extraction failure or attempt recovery for {retailer}: {e}")

        except Exception as e:
            logger.error(f"[Phase2-Comparison] Failed to visit {retailer}: {e}", exc_info=True)

            # Record extraction failure
            try:
                ht = get_health_tracker()
                ht.record_extraction(url=retailer_url, page_type="listing", success=False, method="phase2_exception")
                # Update vendor registry - check if it looks like a block
                vr = get_vendor_registry()
                error_str = str(e).lower()
                if any(block_signal in error_str for block_signal in [
                    "blocked", "captcha", "403", "access denied", "bot", "cloudflare"
                ]):
                    recovery_strategy = vr.record_visit(domain=retailer, success=False, blocked=True, block_type="exception_detected")
                else:
                    recovery_strategy = vr.record_visit(domain=retailer, success=False)

                # If recovery suggested, try it
                if recovery_strategy:
                    logger.info(f"[Phase2-Recovery] {retailer} failed with exception. Trying recovery: {recovery_strategy}")
                    recovery_success = await _try_recovery_strategy(
                        retailer, retailer_url, recovery_strategy, web_vision_session_id
                    )
                    vr.record_recovery_attempt(retailer, recovery_strategy, recovery_success)
            except Exception as recovery_err:
                logger.warning(f"[Phase2-Recovery] Failed to record failure or attempt recovery for {retailer}: {recovery_err}")

    # Step 5: Supplement with generic search if we had few retailers
    if supplement_with_generic_search:
        logger.info(f"[Phase2-Comparison] Supplementing with generic Google search...")
        try:
            generic_results = await search_products(
                query=query,
                research_goal=f"Find additional products matching: {query}",
                intelligence=intelligence,
                max_sources=5,  # Limit generic search to avoid too much overlap
                session_id=session_id,
                web_vision_session_id=f"{web_vision_session_id}_supplement",
                event_emitter=None  # Don't emit duplicate events
            )

            # Add generic findings to tracker (will deduplicate by URL)
            generic_findings = generic_results.get("findings", [])
            for finding in generic_findings:
                if isinstance(finding, dict) and "name" in finding:
                    tracker.add_product(finding)

            logger.info(f"[Phase2-Comparison] Added {len(generic_findings)} products from generic search")
        except Exception as e:
            logger.warning(f"[Phase2-Comparison] Supplementary search failed: {e}")

    # Step 6: Get final top products
    top_products = tracker.get_top_products()

    logger.info(f"[Phase2-Comparison] Complete: {len(top_products)} final recommendations")

    if event_emitter:
        await event_emitter.emit_phase_complete("phase2", {"products": len(top_products)})

    # Build final response
    return {
        "findings": [
            {
                "name": p.get("name", "Unknown Product"),
                "price": p.get("price", "N/A"),
                "vendor": p.get("vendor", "Unknown"),
                "url": p.get("url", ""),
                "description": p.get("description", ""),
                "confidence": p.get("confidence", 0.8)
            }
            for p in top_products
        ],
        "synthesis": {
            "total_sources": len(retailers),
            "products_considered": tracker.get_stats()["total_considered"],
            "final_recommendations": len(top_products),
            "retailers_visited": retailers,
            "supplemented_with_generic": supplement_with_generic_search
        },
        "stats": tracker.get_stats()
    }


# ==================== VENDOR CATALOG DETECTION ====================

# ARCHITECTURE: No hardcoded vendor domain lists. Use URL patterns only.
# See CLAUDE.md: "NEVER hardcode blocklists/allowlists of domains"
# The system detects catalog pages via URL patterns, not domain names.

# URL patterns that indicate product catalogs (e.g., /shop/, /laptops/, /products/)
CATALOG_URL_PATTERNS = [
    "/shop/", "/store/", "/products/", "/laptops/", "/desktops/",
    "/catalog/", "/category/", "/browse/", "/search?", "/s?k=",
    "/rtx-laptops", "/gaming-laptops", "/nvidia-", "/ai-laptops",
]


def _is_vendor_catalog_url(url: str) -> bool:
    """
    Detect if a URL is likely a vendor catalog page that needs hybrid extraction.

    ARCHITECTURE: Uses URL patterns only, no hardcoded domain lists.
    See CLAUDE.md: "NEVER hardcode blocklists/allowlists of domains"

    Args:
        url: The URL to check

    Returns:
        True if this looks like a vendor catalog page
    """
    from urllib.parse import urlparse

    if not url:
        return False

    try:
        parsed = urlparse(url.lower())

        # Check for catalog URL patterns in path (no domain checks)
        path = parsed.path.lower()
        for pattern in CATALOG_URL_PATTERNS:
            if pattern in path or pattern in url.lower():
                return True

        return False

    except Exception:
        return False


def _extract_domain(url: str) -> str:
    """Extract clean domain from URL."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return "unknown"


def _is_likely_hallucinated_product(product: Dict[str, Any], source_url: str) -> bool:
    """
    Detect likely hallucinated products from LLM extraction.

    Checks for common hallucination indicators:
    1. Unrealistic prices (e.g., $84 laptop)
    2. Generic/vague product names
    3. URL is homepage with no product path
    4. Missing critical fields

    Args:
        product: Extracted product dict
        source_url: URL the product was extracted from

    Returns:
        True if product is likely hallucinated, False if plausible
    """
    from urllib.parse import urlparse
    import re

    name = product.get("name", "").strip()
    price_str = product.get("price", "")
    product_url = product.get("url", "")

    # Check 1: Generic/vague product names (LLM hallucination signature)
    generic_names = [
        "gaming laptop",
        "laptop with nvidia gpu",
        "laptop",
        "computer",
        "product",
        "item",
    ]
    if name.lower() in generic_names:
        logger.debug(f"[HallucinationCheck] Generic name detected: {name}")
        return True

    # Check 2: Unrealistic prices by category
    try:
        # Parse price - handle various formats
        price_match = re.search(r'[\$£€]?\s*([\d,]+\.?\d*)', str(price_str))
        if price_match:
            price = float(price_match.group(1).replace(",", ""))

            # Laptops under $100 are almost certainly hallucinated
            name_lower = name.lower()
            if any(kw in name_lower for kw in ["laptop", "notebook", "computer"]):
                if price < 100:
                    logger.debug(f"[HallucinationCheck] Unrealistic laptop price: ${price}")
                    return True

            # GPUs under $50 are suspicious
            if any(kw in name_lower for kw in ["gpu", "graphics", "rtx", "geforce"]):
                if price < 50:
                    logger.debug(f"[HallucinationCheck] Unrealistic GPU price: ${price}")
                    return True
    except (ValueError, AttributeError) as e:
        logger.debug(f"[HallucinationCheck] Price parsing failed for '{name}': {e}")

    # Check 3: URL is homepage (no product path) - only reject if ALSO missing details
    # Many small businesses legitimately sell from their homepage
    try:
        parsed_source = urlparse(source_url)
        source_path = parsed_source.path.strip("/")

        # If source URL is homepage or minimal path
        if not source_path or source_path in ["index.html", "index.php", "home"]:
            # And product URL is same as source or missing
            if not product_url or product_url == source_url:
                # Homepage extraction is suspicious, but only reject if ALSO:
                # - No specific price (must have $ followed by digits)
                # - Generic name (less than 2 words)
                has_specific_price = price_str and re.search(r'\$\d+', price_str)
                has_specific_name = name and len(name.split()) >= 2
                if not has_specific_price and not has_specific_name:
                    logger.debug(f"[HallucinationCheck] Homepage + no specific price/name: {name}")
                    return True
                # Otherwise allow - small businesses often sell from homepage
                logger.debug(f"[HallucinationCheck] Homepage but has details, allowing: {name} @ {price_str}")
    except Exception as e:
        logger.debug(f"[HallucinationCheck] URL parsing failed for source_url '{source_url}': {e}")

    # Check 4: Missing both name AND price (completely empty)
    if not name and not price_str:
        logger.debug(f"[HallucinationCheck] Missing name and price")
        return True

    return False


# REMOVED: _get_fallback_vendors_for_category()
# Hardcoded vendor lists bypass LLM reasoning. Vendors should come from:
# 1. Phase 1 intelligence (forums/Reddit mention vendors)
# 2. Google search results (LLM selects appropriate vendors)


def _extract_vendors_from_intelligence(intelligence: Dict[str, Any], max_vendors: int = 5, query: str = None) -> List[Dict[str, Any]]:
    """
    Extract vendor URLs from Phase 1 intelligence as fallback.

    This is used when Google search fails (CAPTCHA, rate limiting, etc.)
    to provide alternative vendor candidates from the gathered intelligence.

    Sources of vendor URLs:
    1. retailers_mentioned - Retailer names from guides/forums (constructs URLs)
    2. recommended_vendors - Vendors recommended in research
    3. top_sources - URLs from Phase 1 source visits (if available)

    Args:
        intelligence: Phase 1 intelligence dict
        max_vendors: Maximum vendors to extract
        query: Search query to use when building retailer search URLs

    Returns:
        List of vendor candidate dicts: [{"url": "...", "title": "...", "snippet": "..."}]
    """
    if not intelligence:
        return []

    candidates = []
    seen_domains = set()

    # NOTE: No hardcoded RETAILER_URLS dictionary - removed per architecture principle
    # (see CLAUDE.md: "NEVER hardcode site-specific URL templates")
    # The web agent navigates from homepage and uses each site's search UI dynamically

    # Source 1: retailers_mentioned (highest priority)
    retailers = intelligence.get("retailers_mentioned", [])
    for retailer in retailers:
        if isinstance(retailer, dict):
            url = retailer.get("url", "")
            name = retailer.get("name", "Unknown")
        elif isinstance(retailer, str):
            name = retailer.lower().strip()
            # Construct homepage URL - web agent navigates from there
            # No hardcoded search URL patterns (see CLAUDE.md architecture principle)
            clean_name = name.replace(" ", "").replace("&", "")  # "best buy" -> "bestbuy", "b&h" -> "bh"
            if clean_name == "bh" or clean_name == "bhphoto":
                url = "https://www.bhphotovideo.com/"
            else:
                url = f"https://www.{clean_name}.com/"
        else:
            continue

        if url:
            domain = _extract_domain(url)
            if domain and domain not in seen_domains:
                seen_domains.add(domain)
                candidates.append({
                    "url": url,
                    "title": name.title() if isinstance(name, str) else name,
                    "snippet": f"Retailer mentioned in Phase 1 research",
                    "domain": domain,
                    "_source": "retailers_mentioned"
                })

    # Source 2: recommended_vendors
    vendors = intelligence.get("recommended_vendors", []) or intelligence.get("vendors", [])
    for vendor in vendors:
        if isinstance(vendor, dict):
            url = vendor.get("url", "")
            name = vendor.get("name", vendor.get("domain", "Unknown"))
        elif isinstance(vendor, str):
            name = vendor.lower().strip()
            # Construct homepage URL - web agent navigates from there
            # No hardcoded search URL patterns (see CLAUDE.md architecture principle)
            clean_name = name.replace(" ", "").replace("&", "")
            if clean_name == "bh" or clean_name == "bhphoto":
                url = "https://www.bhphotovideo.com/"
            else:
                url = f"https://www.{clean_name}.com/"
        else:
            continue

        if url:
            domain = _extract_domain(url)
            if domain and domain not in seen_domains:
                seen_domains.add(domain)
                candidates.append({
                    "url": url,
                    "title": name.title() if isinstance(name, str) else name,
                    "snippet": f"Vendor discovered in Phase 1 research",
                    "domain": domain,
                    "_source": "recommended_vendors"
                })

    # Source 3: top_sources from Phase 1 (check VendorRegistry for known commerce sites)
    # ARCHITECTURE PRINCIPLE: No hardcoded blocklists/allowlists. Use VendorRegistry
    # which learns commerce domains through experience. See CLAUDE.md.
    sources = intelligence.get("top_sources", []) or intelligence.get("sources", [])
    registry = get_vendor_registry()

    for source in sources:
        if isinstance(source, dict):
            url = source.get("url", "")
            title = source.get("title", source.get("name", "Unknown"))
        elif isinstance(source, str):
            url = source
            title = "Source"
        else:
            continue

        if url:
            domain = _extract_domain(url)
            # Check VendorRegistry for known commerce domains (learned, not hardcoded)
            # Unknown domains are also included - they came from Phase 1 intelligence
            # and the LLM already selected them as relevant sources
            vendor_record = registry.get(domain) if domain else None
            is_known_commerce = vendor_record is not None and vendor_record.vendor_type in ("retailer", "marketplace", "")
            # Include if: known commerce vendor OR came from Phase 1 (already LLM-vetted)
            if domain and domain not in seen_domains and (is_known_commerce or vendor_record is None):
                seen_domains.add(domain)
                candidates.append({
                    "url": url,
                    "title": title,
                    "snippet": f"Commerce source from Phase 1 research",
                    "domain": domain,
                    "_source": "top_sources"
                })

    # NO HARDCODED FALLBACK - removed per architecture doc
    # Vendors must come from Phase 1 intelligence or Google search, not hardcoded lists
    # If no vendors found, caller should create intervention for human investigation
    if not candidates:
        logger.warning("[IntelligenceFallback] No vendors found in intelligence - hardcoded fallbacks removed per architecture")

    logger.info(f"[IntelligenceFallback] Extracted {len(candidates)} vendor candidates from intelligence")
    for i, c in enumerate(candidates[:max_vendors]):
        logger.info(f"[IntelligenceFallback] {i+1}. {c.get('domain')} ({c.get('_source')})")

    return candidates[:max_vendors]


# ==================== INTELLIGENT VENDOR SEARCH ====================

async def intelligent_vendor_search(
    query: str,
    intelligence: Dict[str, Any],
    max_vendors: int = 5,  # Visit up to 5 vendors for comparison shopping
    min_vendors: int = 3,  # MUST visit at least 3 vendors before stopping
    products_per_vendor: int = 8,  # Extract 5-10 products per vendor
    session_id: str = "default",
    web_vision_session_id: str = None,
    event_emitter: Optional[Any] = None,
    research_context: Dict[str, Any] = None,  # Context from Planner
    requirements_reasoning: Dict[str, Any] = None,  # LLM-generated reasoning for viability filter
    original_query: str = None  # CONTEXT DISCIPLINE: Original user query with priority signals
) -> Dict[str, Any]:
    """
    Intelligent multi-vendor product search with LLM-driven decisions.

    This is the main entry point for commerce queries. It:
    1. Builds a smart search query using Phase 1 intelligence
    2. Searches Google for product pages
    3. LLM selects best vendor candidates from results
    4. Visits each vendor, extracts products with hybrid vision
    5. Filters products for viability using LLM reasoning (NEW)
    6. Tracks and ranks products across vendors
    7. Returns final ranked recommendations

    Args:
        query: User's search query
        intelligence: Phase 1 intelligence with requirements, specs, etc.
        max_vendors: Maximum number of vendors to visit (default 5)
        min_vendors: Minimum vendors to visit before stopping (default 3)
        products_per_vendor: Maximum products to keep per vendor
        session_id: Session ID for browser context
        web_vision_session_id: Web Vision session ID
        event_emitter: Optional progress event emitter
        research_context: Context from Planner with:
            - entities: List of specific product names
            - subtasks: Pre-planned search queries
            - research_type: Type of research (technical_specs, etc.)
        requirements_reasoning: NEW - LLM-generated reasoning about validity criteria:
            - reasoning_document: Full YAML reasoning text
            - parsed: Structured dict with validity_criteria, disqualifiers, etc.
            - optimized_query: Search query optimized by LLM

    Returns:
        {
            "findings": [...],  # Final ranked products
            "synthesis": {...},  # Search summary
            "stats": {...}  # Execution statistics
        }
    """
    from orchestrator import web_vision_mcp
    from orchestrator.llm_candidate_filter import select_vendor_candidates
    from orchestrator.product_viability import filter_viable_products, filter_viable_products_with_reasoning
    from orchestrator.product_comparison_tracker import ProductComparisonTracker

    # Initialize Web Vision session
    if web_vision_session_id is None:
        web_vision_session_id = f"{session_id}_intelligent"

    logger.info(f"[IntelligentSearch] Starting multi-vendor search: {query[:60]}")

    # Defensive check for None intelligence
    intelligence = intelligence or {}

    # Extract budget max from intelligence for pre-filtering candidates
    budget_max = None
    if intelligence:
        price_range = intelligence.get("price_range", {})
        if isinstance(price_range, dict):
            budget_max = price_range.get("budget_max") or price_range.get("max")
        elif isinstance(price_range, str):
            # Parse "under $800" style strings
            import re
            match = re.search(r'\$?(\d+(?:,\d{3})*(?:\.\d{2})?)', price_range)
            if match:
                budget_max = float(match.group(1).replace(",", ""))

    if budget_max:
        logger.info(f"[IntelligentSearch] Budget max: ${budget_max:.2f} (will pre-filter candidates)")

    # CONTEXT DISCIPLINE: Detect price priority from original query
    # Use original_query if provided, fall back to query (which may be sanitized)
    price_sort_query = original_query or query
    price_sort = detect_price_priority(price_sort_query)
    if price_sort:
        logger.info(f"[IntelligentSearch] Detected price priority from '{price_sort_query[:40]}...': sort by {price_sort}")

    if event_emitter and hasattr(event_emitter, 'emit_phase_started'):
        await event_emitter.emit_phase_started("intelligent_search", "vendor_discovery")

    # Create ProductRequirements from Phase 1 intelligence for recipe-based validation
    product_requirements = None
    if intelligence:
        try:
            product_requirements = ProductRequirements.from_phase1_intelligence(intelligence, query)
            logger.info(f"[IntelligentSearch] Created ProductRequirements: category={product_requirements.category}, "
                       f"deal_breakers={len(product_requirements.deal_breakers)}, "
                       f"acceptable_alternatives={len(product_requirements.acceptable_alternatives)}")
        except Exception as req_err:
            logger.warning(f"[IntelligentSearch] Could not create ProductRequirements: {req_err}")

    # Initialize hybrid perception pipeline
    use_hybrid_extraction = os.getenv("PERCEPTION_ENABLE_HYBRID", "true").lower() == "true"
    perception_pipeline = None
    if use_hybrid_extraction:
        try:
            from orchestrator.product_perception import ProductPerceptionPipeline, VerifiedProduct
            perception_pipeline = ProductPerceptionPipeline()
            logger.info("[IntelligentSearch] Click-to-verify extraction enabled")
        except ImportError as e:
            logger.warning(f"[IntelligentSearch] Could not load ProductPerceptionPipeline: {e}")
            use_hybrid_extraction = False

    # Initialize comparison tracker
    tracker = ProductComparisonTracker(max_products=max_vendors * products_per_vendor)

    # ==================== STEP 1: Build Smart Shopping Queries ====================
    # Priority for query selection:
    # 1. Original user query (from research_context) - let _build_smart_shopping_queries optimize it
    # 2. Entity-based query for specific research types
    # 3. LLM-optimized query via _build_smart_shopping_queries
    #
    # DO NOT use subtask.q - it may have been poorly reformulated by the Planner
    research_context = research_context or {}
    user_query = research_context.get("user_query")
    entities = research_context.get("entities", [])
    research_type = research_context.get("research_type", "general")
    topic = research_context.get("topic")  # e.g., "Pets.Hamsters"
    user_preferences = research_context.get("user_preferences")  # e.g., "Favorite Hamster: Syrian"
    prior_vendors_from_context = research_context.get("prior_vendors", [])  # Vendors from previous turns (§1)

    if prior_vendors_from_context:
        logger.info(f"[IntelligentSearch] Prior vendors from context: {prior_vendors_from_context}")

    # If query is vague (just "vendors", "products", etc.), enhance with topic context
    # This fixes the "vendor for sale" problem when user says "search again for vendors"
    vague_terms = ["vendor", "vendors", "seller", "sellers", "product", "products", "option", "options", "more", "others"]
    query_lower = (user_query or query).lower()
    is_vague = any(term in query_lower.split() for term in vague_terms) and len(query_lower.split()) < 8

    if is_vague and topic:
        # Extract meaningful subject from topic (e.g., "Pets.Hamsters" -> "hamster")
        topic_subject = topic.split(".")[-1].rstrip("s")  # "Hamsters" -> "Hamster"
        # Check user preferences for more specific info
        specific_type = ""
        if user_preferences and "syrian" in user_preferences.lower():
            specific_type = "Syrian "
        # Enhance the query with topic context
        enhanced_query = f"{specific_type}{topic_subject} {user_query or query}"
        logger.info(f"[IntelligentSearch] Enhanced vague query with topic: '{user_query or query}' -> '{enhanced_query}'")
        user_query = enhanced_query

    if user_query:
        # Use original user query - let _build_smart_shopping_queries craft optimal search query
        logger.info(f"[IntelligentSearch] Using original user query: '{user_query}'")
        smart_queries = await _build_smart_shopping_queries(user_query, intelligence)
        shopping_query = smart_queries.get("primary", f"{user_query} for sale")
        site_specific_queries = smart_queries.get("site_specific", {})
        logger.info(f"[IntelligentSearch] LLM-optimized query: '{shopping_query}'")
    elif entities and research_type in ["technical_specs", "pricing", "availability"]:
        # Build entity-specific query
        entity = entities[0]
        if research_type == "technical_specs":
            shopping_query = f"{entity} specifications specs maximum upgrade"
        elif research_type == "pricing":
            shopping_query = f"{entity} price buy for sale"
        elif research_type == "availability":
            shopping_query = f"{entity} in stock where to buy"
        else:
            shopping_query = f"{entity} specifications"
        logger.info(f"[IntelligentSearch] Entity-aware query (type={research_type}): '{shopping_query}'")
        site_specific_queries = {}
    else:
        # Standard flow: build smart queries from intelligence
        smart_queries = await _build_smart_shopping_queries(query, intelligence)
        shopping_query = smart_queries.get("primary", f"{query} for sale")
        site_specific_queries = smart_queries.get("site_specific", {})
        logger.info(f"[IntelligentSearch] Smart query: '{shopping_query}'")
    if site_specific_queries:
        logger.info(f"[IntelligentSearch] Site-specific queries for: {list(site_specific_queries.keys())}")

    # ==================== STEP 2: Build Vendor List (Phase 1 + Google) ====================
    # Use VendorRegistry for dynamic vendor management (NO hardcoded lists)
    # The registry learns which vendors work through experience
    from orchestrator.query_planner import construct_vendor_search_url
    registry = get_vendor_registry()
    price_range = intelligence.get("price_range", {}) if intelligence else {}

    # PHASE 1 VENDORS: Extract from intelligence (forums/reviews mentioned these)
    # Collect vendor info now, but find URLs later (just before visiting) for natural delays
    phase1_vendors = []
    retailers_from_intel = intelligence.get("retailers", {}) if intelligence else {}

    # FALLBACK: Check retailers_mentioned (list format) if retailers (dict format) is empty
    # This handles cached intelligence where retailers are stored as a simple list
    if not retailers_from_intel and intelligence:
        retailers_mentioned = intelligence.get("retailers_mentioned", [])
        if retailers_mentioned:
            logger.info(f"[IntelligentSearch] Converting retailers_mentioned list to retailers dict: {retailers_mentioned}")
            # Convert list to dict format with default relevance scores
            retailers_from_intel = {
                name.lower(): {
                    "relevance_score": 0.7,  # Default relevance for cached retailers
                    "context": "From cached intelligence",
                    "mentioned_for": [],
                    "include_in_search": True
                }
                for name in retailers_mentioned
                if isinstance(name, str) and name.strip()
            }

    if retailers_from_intel:
        logger.info(f"[IntelligentSearch] Step 2a: Collecting Phase 1 vendors (URLs found during visit)")

        # Sort by relevance score (highest first)
        sorted_retailers = sorted(
            retailers_from_intel.items(),
            key=lambda x: x[1].get("relevance_score", 0) if isinstance(x[1], dict) else 0,
            reverse=True
        )

        for domain, info in sorted_retailers:
            # Normalize domain
            if not domain.endswith(".com") and "." not in domain:
                domain = f"{domain}.com"
            domain = domain.lower().replace("www.", "")

            # Extract info
            relevance = info.get("relevance_score", 0.5) if isinstance(info, dict) else 0.5
            context = info.get("context", "") if isinstance(info, dict) else ""
            categories = info.get("mentioned_for", []) if isinstance(info, dict) else []

            # Register this vendor in the living registry (learns from Phase 1 intelligence)
            registry.add_or_update(
                domain=domain,
                categories=categories if isinstance(categories, list) else [],
                discovered_via="phase1_intelligence",
                discovery_query=query
            )

            # Check if vendor is usable (not blocked, reasonable success rate)
            if not registry.is_usable(domain):
                logger.info(f"[IntelligentSearch] Phase 1 vendor {domain} not usable (blocked/low success rate)")
                continue

            # DON'T find URL yet - we'll do Google search just before visiting
            # This creates natural delays between searches (browsing activity)
            phase1_vendors.append({
                "domain": domain,
                "url": None,  # Will be found via Google just before visit
                "source": "phase1_intelligence",
                "relevance_score": relevance,
                "context": context,
                "needs_url_discovery": True  # Flag to find URL during visit
            })
            logger.info(f"[IntelligentSearch] Phase 1 vendor queued: {domain} (relevance={relevance:.2f})")

        logger.info(f"[IntelligentSearch] Collected {len(phase1_vendors)} Phase 1 vendors (URLs to be found during visit)")

    # PRIOR VENDORS: Add vendors from previous turns (Context Gatherer found in §1)
    # These are vendors that worked before - give them priority
    prior_turn_vendors = []
    phase1_domains = {v["domain"].lower() for v in phase1_vendors}

    for vendor_name in prior_vendors_from_context:
        # Normalize domain
        domain = vendor_name.lower().replace("www.", "").strip()
        if not domain:
            continue
        if not any(c in domain for c in "."):
            domain = f"{domain}.com"

        # Skip if already in Phase 1 vendors
        if domain in phase1_domains:
            logger.debug(f"[IntelligentSearch] Prior vendor {domain} already in Phase 1")
            continue

        # Check if usable
        if not registry.is_usable(domain):
            logger.info(f"[IntelligentSearch] Prior vendor {domain} not usable")
            continue

        prior_turn_vendors.append({
            "domain": domain,
            "url": None,  # Will be found via Google just before visit
            "source": "prior_turn",
            "relevance_score": 0.8,  # High priority - worked before
            "context": "From previous conversation turns",
            "needs_url_discovery": True
        })
        phase1_domains.add(domain)  # Track to avoid duplicates
        logger.info(f"[IntelligentSearch] Prior turn vendor queued: {domain}")

    if prior_turn_vendors:
        logger.info(f"[IntelligentSearch] Added {len(prior_turn_vendors)} vendors from prior turns")

    # GOOGLE SEARCH: Fill remaining slots with additional vendors
    backup_count = int(os.getenv("VENDOR_BACKUP_COUNT", "6"))
    max_total_vendors = max_vendors + backup_count
    remaining_slots = max(0, max_total_vendors - len(phase1_vendors) - len(prior_turn_vendors))
    google_vendors = []

    if remaining_slots > 0:
        logger.info(f"[IntelligentSearch] Step 2b: Searching for {remaining_slots} more vendors (provider: {SEARCH_PROVIDER})")

        search_results = await _web_vision_search(
            query=shopping_query,
            max_results=15,
            session_id=web_vision_session_id,
            event_emitter=event_emitter
        )

        if search_results:
            # Use LLM to identify which search results are actual vendors
            vendor_candidates_raw = await select_vendor_candidates(
                search_results=search_results,
                query=query,
                intelligence=intelligence,
                max_vendors=remaining_slots,
                original_query=original_query  # CONTEXT DISCIPLINE: LLM reads priorities from this
            )

            # Extract domains we already have from Phase 1
            phase1_domains = {v["domain"] for v in phase1_vendors}

            for vendor in (vendor_candidates_raw or []):
                domain = vendor.get("domain", "").lower().replace("www.", "")

                # Skip if we already have this vendor from Phase 1
                if domain in phase1_domains:
                    logger.debug(f"[IntelligentSearch] Skipping {domain} - already from Phase 1")
                    continue

                # Register in VendorRegistry (learns from Google search discoveries)
                registry.add_or_update(
                    domain=domain,
                    discovered_via="google_search",
                    discovery_query=query
                )

                # Check if usable (not blocked, reasonable success rate)
                if not registry.is_usable(domain):
                    logger.info(f"[IntelligentSearch] Google vendor {domain} not usable, skipping")
                    continue

                # URL selection strategy:
                # - If user wants price sorting (cheapest/budget), PREFER constructed URL with sort params
                #   because Google often returns product pages, not search results
                # - Otherwise use Google's URL (may be a specific product page Google found relevant)
                google_url = vendor.get("url")

                # ARCHITECTURE: Apply price-sort to ALL vendors, not just "major retailers"
                # The web agent navigates from homepage and finds sort controls dynamically
                # See CLAUDE.md: "NEVER hardcode site-specific conditional logic"
                if price_sort:
                    # For price-priority queries: construct URL with sort params for ANY vendor
                    # Web agent will navigate and find the sort control
                    vendor_url = construct_vendor_search_url(domain, shopping_query, price_range, sort_by_price=price_sort)
                    logger.info(f"[IntelligentSearch] Google vendor: {domain} (constructed URL with price sort={price_sort})")
                elif google_url:
                    # Use Google's URL for other cases
                    vendor_url = google_url
                    logger.info(f"[IntelligentSearch] Google vendor: {domain} (using search result URL: {vendor_url[:80]})")
                else:
                    # Fallback to constructed URL only if Google didn't return one
                    vendor_url = construct_vendor_search_url(domain, shopping_query, price_range, sort_by_price=price_sort)
                    logger.info(f"[IntelligentSearch] Google vendor: {domain} (constructed URL, sort={price_sort})")

                google_vendors.append({
                    "domain": domain,
                    "url": vendor_url,
                    "source": "google_search",
                    "vendor_type": vendor.get("vendor_type", "unknown"),
                    "reasoning": vendor.get("reasoning", "")
                })

                if len(google_vendors) >= remaining_slots:
                    break
        else:
            logger.warning("[IntelligentSearch] Google search returned no results")

    # COMBINE: Phase 1 vendors, prior turn vendors, then Google vendors
    # Prior turn vendors are included as high-priority since they worked before
    # Vendor selection is driven by LLM reasoning in source_selector, not hardcoded lists
    vendor_candidates = phase1_vendors + prior_turn_vendors + google_vendors

    if not vendor_candidates:
        logger.warning("[IntelligentSearch] No vendors found from Phase 1, prior turns, or Google")
        return {
            "findings": [],
            "synthesis": {"total_sources": 0, "error": "No vendors found"},
            "stats": {"vendors_visited": 0, "products_found": 0}
        }

    logger.info(
        f"[IntelligentSearch] Total vendors: {len(vendor_candidates)} "
        f"({len(phase1_vendors)} from Phase 1, {len(prior_turn_vendors)} from prior turns, {len(google_vendors)} from Google)"
    )

    # ==================== STEP 4: Visit Vendors & Extract Products ====================
    logger.info("[IntelligentSearch] Step 4: Visiting vendors and extracting products")

    all_viable_products = []
    all_rejected_products = []  # Track ALL rejected products with rejection_reason for context
    rejected_for_relaxation = []  # Track rejected products for potential re-evaluation
    vendors_visited = []
    vendors_failed = []
    vendors_with_products = 0  # Track successful vendors (those that yielded products)

    # Extract requirements for viability filtering and post-extraction validation
    price_range = intelligence.get("price_range", {})
    requirements = {
        "key_requirements": intelligence.get("key_requirements", []),
        "price_range": price_range,
        "specs_discovered": intelligence.get("specs_discovered", {}),
        "recommended_brands": intelligence.get("recommended_brands", []),
        # Flatten budget for validation function
        "budget_max": budget_max or (price_range.get("max") if isinstance(price_range, dict) else None),
        "budget_min": price_range.get("min") if isinstance(price_range, dict) else None,
        # Map key_requirements to hard_requirements for validation
        "hard_requirements": intelligence.get("key_requirements", []),
        # NOTE: specs_discovered are forum recommendations, NOT hard requirements
        # They should inform ranking/scoring, not cause rejection
        # "required_specs" is intentionally left empty - use key_requirements instead
        "required_specs": {},
    }

    # Iterate through all candidates
    # CRITICAL: Must visit at least min_vendors before stopping, then can stop at max_vendors
    for vendor in vendor_candidates:
        # Check stopping conditions:
        # 1. MUST reach min_vendors first (no early stopping!)
        # 2. THEN can stop when max_vendors reached
        if vendors_with_products >= min_vendors and vendors_with_products >= max_vendors:
            logger.info(f"[IntelligentSearch] Reached max of {max_vendors} successful vendors, stopping")
            break

        # Log progress toward minimum
        if vendors_with_products < min_vendors:
            logger.info(f"[IntelligentSearch] Progress: {vendors_with_products}/{min_vendors} minimum vendors")

        vendor_domain = vendor.get("domain", "unknown")
        vendor_source = vendor.get("source", "unknown")

        # For Phase 1 vendors: Find URL via Google search NOW (just before visiting)
        # This creates natural delays - we browse the vendor site between Google searches
        if vendor.get("needs_url_discovery"):
            logger.info(f"[IntelligentSearch] Finding URL for Phase 1 vendor: {vendor_domain} via Google")

            # ARCHITECTURE: For price-priority queries, use constructed URL for ALL vendors
            # Web agent navigates from homepage and finds sort controls dynamically
            # See CLAUDE.md: "NEVER hardcode site-specific conditional logic"
            if price_sort:
                vendor_url = construct_vendor_search_url(vendor_domain, shopping_query, price_range, sort_by_price=price_sort)
                logger.info(f"[IntelligentSearch] {vendor_domain}: Constructed URL with price sort={price_sort}")
            else:
                vendor_url = await _find_vendor_url_via_google(
                    query=shopping_query,
                    vendor_domain=vendor_domain,
                    session_id=web_vision_session_id,
                    event_emitter=event_emitter
                )

                if not vendor_url:
                    # Fallback to constructed search URL if Google doesn't find anything
                    # CONTEXT DISCIPLINE: Include price_sort from original query
                    vendor_url = construct_vendor_search_url(vendor_domain, shopping_query, price_range, sort_by_price=price_sort)
                    logger.info(f"[IntelligentSearch] {vendor_domain}: Fallback to constructed URL (sort={price_sort})")
                else:
                    logger.info(f"[IntelligentSearch] {vendor_domain}: Google found {vendor_url[:80]}")
        else:
            # Google vendors already have URLs from the general search
            vendor_url = vendor.get("url")

        if not vendor_url:
            logger.warning(f"[IntelligentSearch] No URL for {vendor_domain}, skipping")
            continue

        logger.info(f"[IntelligentSearch] Visiting vendor: {vendor_domain} (source={vendor_source}, successful: {vendors_with_products}/{min_vendors} min, {max_vendors} max)")
        logger.info(f"[IntelligentSearch] URL: {vendor_url[:100]}...")

        if event_emitter and hasattr(event_emitter, 'emit_vendor_visit'):
            await event_emitter.emit_vendor_visit(vendor_domain)

        try:
            # Navigate to vendor URL
            nav_result = await web_vision_mcp.navigate(
                session_id=web_vision_session_id,
                url=vendor_url,
                wait_for="networkidle"
            )

            if not nav_result.get("success"):
                logger.warning(f"[IntelligentSearch] Failed to navigate to {vendor_domain}: {nav_result.get('message')}")
                vendors_failed.append(vendor_domain)
                continue

            # Extract products using Universal Web Agent (PRIMARY)
            # Simple See→Think→Act loop with OCR - no CSS selectors
            raw_products = []

            if use_hybrid_extraction:
                try:
                    page = await web_vision_mcp.get_page(web_vision_session_id)
                    if page:
                        # Use Universal Web Agent for intelligent extraction
                        logger.info(f"[IntelligentSearch] Using UniversalWebAgent for {vendor_domain}")

                        # Get LLM settings
                        llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
                        llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
                        llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

                        # Create agent with site knowledge cache
                        agent = UniversalWebAgent(
                            page=page,
                            knowledge_cache=get_site_knowledge_cache(),
                            llm_url=llm_url,
                            llm_model=llm_model,
                            llm_api_key=llm_api_key,
                            session_id=web_vision_session_id
                        )

                        # Build research context for UniversalWebAgent navigation
                        # This helps the agent make better decisions about which links to click
                        # CONTEXT DISCIPLINE: Use original_query so price priority is detected
                        # Note: vendor_domain not passed - site type detection is done by LLM from page content
                        navigation_context = _build_navigation_context(
                            intelligence=intelligence,
                            query=original_query or query
                        )

                        # Extract products using See→Think→Act loop
                        # Per-vendor timeout - needs to cover: navigation + search + extraction + PDP verification
                        # PDP verification alone: 8 products × ~7s each = ~56s
                        VENDOR_TIMEOUT = 90
                        try:
                            # CONTEXT DISCIPLINE: Pass original_query so agent sees user priorities
                            # like "cheapest", "best", "budget" - these drive navigation decisions
                            agent_query = original_query or query
                            products = await asyncio.wait_for(
                                agent.extract(
                                    url=vendor_url,
                                    query=agent_query,  # THE GOAL drives navigation and extraction
                                    research_context=navigation_context  # Phase 1 intelligence for navigation
                                ),
                                timeout=VENDOR_TIMEOUT
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"[IntelligentSearch] UniversalAgent timed out after {VENDOR_TIMEOUT}s for {vendor_domain}")
                            # Retrieve partial results instead of discarding all work
                            products = agent.partial_results if hasattr(agent, 'partial_results') else []
                            if products:
                                logger.info(f"[IntelligentSearch] Recovered {len(products)} partial results from timeout")

                        # Convert Product objects to dict format
                        for product in products:
                            raw_products.append({
                                "name": product.name,
                                "price": product.price if product.price else "N/A",
                                "url": product.url,
                                "description": product.description,
                                "vendor": product.vendor or vendor_domain,
                                "specs": {},
                                "pdp_verified": False,  # OCR-based extraction
                                "in_stock": True,  # Assume in stock if visible
                                "extraction_method": "universal_agent_ocr",
                                "price_status": "priced" if product.price else "unknown",
                                "contact_email": "",
                                "contact_phone": "",
                                "contact_note": "",
                                "location": "",
                                "source_type": "product",
                                "confidence": 0.8  # OCR confidence
                            })

                        logger.info(f"[IntelligentSearch] ✓ UniversalAgent extracted {len(raw_products)} products from {vendor_domain}")

                        # Record extraction success to schema registry
                        try:
                            ht = get_health_tracker()
                            ht.record_extraction(
                                url=vendor_url,
                                page_type="listing",
                                success=True,
                                method="universal_agent"
                            )
                        except Exception as e:
                            logger.warning(f"[IntelligentSearch] Failed to record extraction success for {vendor_domain}: {e}")
                except Exception as extract_err:
                    logger.warning(f"[IntelligentSearch] UniversalAgent extraction failed for {vendor_domain}: {extract_err}")

                    # Fallback to direct pipeline if navigator fails
                    if perception_pipeline:
                        try:
                            page = await web_vision_mcp.get_page(web_vision_session_id)
                            if page:
                                logger.info(f"[IntelligentSearch] Falling back to direct pipeline for {vendor_domain}")
                                verified_products = await perception_pipeline.extract_and_verify(
                                    page=page,
                                    url=vendor_url,
                                    query=query,
                                    max_products=products_per_vendor,
                                    max_price=budget_max,
                                    requirements=requirements,  # Smart prioritization + early stopping
                                    target_viable_products=products_per_vendor
                                )

                                for vp in verified_products:
                                    desc = ""
                                    if vp.specs:
                                        spec_text = ", ".join(f"{k}: {v}" for k, v in vp.specs.items() if v)
                                        if spec_text:
                                            desc = f"Specs: {spec_text}"

                                    raw_products.append({
                                        "name": vp.title,
                                        "price": f"${vp.price:.2f}" if vp.price else "N/A",
                                        "url": vp.url,
                                        "description": desc,
                                        "vendor": vendor_domain,
                                        "specs": vp.specs or {},
                                        "pdp_verified": True,
                                        "in_stock": vp.in_stock,
                                        "extraction_method": "click_to_verify_fallback"
                                    })

                                logger.info(f"[IntelligentSearch] ✓ Fallback verified {len(raw_products)} products from {vendor_domain}")
                        except Exception as fallback_err:
                            logger.warning(f"[IntelligentSearch] Fallback also failed for {vendor_domain}: {fallback_err}")

                    # Record extraction failure to schema registry for recalibration
                    try:
                        ht = get_health_tracker()
                        ht.record_extraction(
                            url=vendor_url,
                            page_type="listing",
                            success=False,
                            method="universal_agent"
                        )
                    except Exception as e:
                        logger.warning(f"[IntelligentSearch] Failed to record extraction failure for {vendor_domain}: {e}")

            # Check if we got category names instead of products (common issue)
            if raw_products:
                # Detect if all products are category names (no prices, generic names)
                category_indicators = ['laptops', 'computers', 'gaming', 'windows', 'deals', 'category']
                looks_like_categories = all(
                    any(ind in p.get("name", "").lower() for ind in category_indicators)
                    and len(p.get("name", "").split()) <= 4  # Short generic names
                    for p in raw_products
                )
                if looks_like_categories:
                    logger.warning(f"[IntelligentSearch] Products from {vendor_domain} look like category names, trying site search")
                    raw_products = []  # Clear and retry

            # If no products, try using the vendor's search functionality
            if not raw_products and use_hybrid_extraction:
                logger.info(f"[IntelligentSearch] Trying site search on {vendor_domain}")
                search_products = await _try_vendor_site_search(
                    web_vision_session_id, vendor_domain, query, intelligence, perception_pipeline
                )
                if search_products:
                    raw_products = search_products

            # Fallback to basic extraction if hybrid failed or not available
            if not raw_products:
                logger.info(f"[IntelligentSearch] Using basic extraction for {vendor_domain}")
                basic_result = await _web_vision_visit_and_read(
                    url=vendor_url,
                    reading_goal=f"Find products matching: {query}",
                    session_id=web_vision_session_id
                )
                if basic_result:
                    extracted = basic_result.get("extracted_info", {}).get("products", [])
                    for idx, p in enumerate(extracted):
                        if isinstance(p, dict):
                            # VALIDATION: Check for hallucinated products from homepages
                            # Reject products with suspicious indicators
                            if _is_likely_hallucinated_product(p, vendor_url):
                                logger.warning(
                                    f"[IntelligentSearch] Rejecting likely hallucinated product from {vendor_domain}: "
                                    f"{p.get('name', 'unknown')[:50]} @ {p.get('price', 'N/A')}"
                                )
                                continue

                            p["vendor"] = vendor_domain
                            p["extraction_method"] = "basic_llm"
                            # Set URL to vendor homepage if not extracted (real URL, not fake fragment)
                            if not p.get("url"):
                                p["url"] = vendor_url
                            raw_products.append(p)

            if not raw_products:
                logger.warning(f"[IntelligentSearch] No products extracted from {vendor_domain}, trying next vendor")
                vendors_failed.append(vendor_domain)

                # Record failure for schema recalibration
                try:
                    from orchestrator.shared_state.site_health_tracker import get_health_tracker
                    ht = get_health_tracker()
                    ht.record_extraction(
                        url=vendor_url,
                        page_type="listing",
                        success=False,
                        method="all_methods_failed"
                    )
                except Exception as e:
                    logger.warning(f"[IntelligentSearch] Failed to record all_methods_failed for {vendor_domain}: {e}")

                # VendorRegistry: Record failure and attempt recovery
                try:
                    vr = get_vendor_registry()
                    recovery_strategy = vr.record_visit(domain=vendor_domain, success=False)

                    if recovery_strategy:
                        logger.info(f"[IntelligentSearch-Recovery] {vendor_domain} extraction failed. Attempting recovery: {recovery_strategy}")
                        recovery_success = await _try_recovery_strategy(
                            vendor_domain, vendor_url, recovery_strategy, web_vision_session_id
                        )
                        vr.record_recovery_attempt(vendor_domain, recovery_strategy, recovery_success)

                        if recovery_success:
                            # Retry extraction after recovery
                            logger.info(f"[IntelligentSearch-Recovery] Recovery applied, retrying {vendor_domain}...")
                            # Re-run extract_and_verify after recovery
                            retry_result = await extract_and_verify(
                                vendor_url,
                                session_id=web_vision_session_id,
                                query=query,
                                max_products=products_per_vendor,
                                requirements=requirements
                            )
                            if retry_result and retry_result.get("verified_products"):
                                raw_products = retry_result["verified_products"]
                                logger.info(f"[IntelligentSearch-Recovery] Recovery successful! Got {len(raw_products)} products from {vendor_domain}")
                                # Remove from failed list since we recovered
                                if vendor_domain in vendors_failed:
                                    vendors_failed.remove(vendor_domain)
                            else:
                                logger.warning(f"[IntelligentSearch-Recovery] Recovery applied but still no products from {vendor_domain}")
                except Exception as e:
                    logger.debug(f"[IntelligentSearch-Recovery] VendorRegistry error: {e}")

                # EXTRACTION FAILED: Register intervention so it appears in chat UI
                if not raw_products:
                    try:
                        from orchestrator.captcha_intervention import request_intervention

                        novnc_url = "http://localhost:6080/vnc_lite.html?host=localhost&port=6080&scale=true"

                        # Register intervention - will appear in chat UI like captchas
                        intervention = await request_intervention(
                            blocker_type="extraction_failed",
                            url=vendor_url,
                            screenshot_path=None,
                            session_id=web_vision_session_id,
                            blocker_details={
                                "vendor": vendor_domain,
                                "query": query,
                            },
                            cdp_url=novnc_url
                        )

                        logger.warning(
                            f"[IntelligentSearch] ❌ Extraction failed for {vendor_domain}. "
                            f"Waiting for user (intervention: {intervention.intervention_id})"
                        )

                        # Wait for user to view and dismiss (or timeout after 2 min)
                        resolved = await intervention.wait_for_resolution(timeout=120)

                        if resolved:
                            logger.info(f"[IntelligentSearch] User resolved intervention for {vendor_domain}")
                        else:
                            logger.info(f"[IntelligentSearch] Intervention timeout/skipped for {vendor_domain}, continuing...")

                    except Exception as intervention_err:
                        logger.debug(f"[IntelligentSearch] Intervention registration failed: {intervention_err}")

                if not raw_products:
                    continue  # Continue to next vendor (may be a backup)

            # ==================== STEP 4.5: Post-Extraction Requirements Validation ====================
            # Check if extracted products match ALL hard requirements (budget, specs, features)
            # This detects cases where site filters didn't work or navigation lost the filter
            if raw_products and requirements:
                validation = validate_extraction_against_requirements(
                    products=raw_products,
                    requirements=requirements,
                    vendor_domain=vendor_domain
                )

                if not validation["valid"]:
                    # Most products failing requirements - site filter may not be working
                    reasons = validation.get("failures_by_reason", {})
                    top_reasons = sorted(reasons.items(), key=lambda x: -x[1])[:3]
                    reasons_str = ", ".join(f"{r}: {c}" for r, c in top_reasons) if top_reasons else "unknown"
                    logger.warning(
                        f"[IntelligentSearch] {vendor_domain}: Extraction validation FAILED - "
                        f"{validation['failing_count']}/{len(raw_products)} products failed requirements. "
                        f"Top failures: {reasons_str}"
                    )
                    # Use only passing products to avoid wasting viability check time
                    if validation["filtered_products"]:
                        raw_products = validation["filtered_products"]
                        logger.info(
                            f"[IntelligentSearch] {vendor_domain}: Using {len(raw_products)} products that pass requirements"
                        )
                    else:
                        logger.warning(
                            f"[IntelligentSearch] {vendor_domain}: No products pass requirements after filtering"
                        )
                        continue

            # ==================== STEP 5: Filter Viable Products ====================
            # Use LLM reasoning-based filter if available, otherwise fall back to structured filter
            if requirements_reasoning and requirements_reasoning.get("reasoning_document"):
                # NEW: LLM-driven viability filter - reasons about each product
                viability_result = await filter_viable_products_with_reasoning(
                    products=raw_products,
                    requirements_reasoning=requirements_reasoning["reasoning_document"],
                    query=query,
                    max_products=products_per_vendor
                )
                logger.info(f"[IntelligentSearch] {vendor_domain}: Using LLM reasoning-based viability filter")
            else:
                # FALLBACK: Structured filter (old behavior)
                viability_result = await filter_viable_products(
                    products=raw_products,
                    requirements=requirements,
                    query=query,
                    max_products=products_per_vendor
                )

            viable = viability_result.get("viable_products", [])
            rejected = viability_result.get("rejected", [])
            logger.info(
                f"[IntelligentSearch] {vendor_domain}: {len(viable)}/{len(raw_products)} products viable"
            )

            # Track ALL rejected products for context awareness (with rejection_reason)
            if rejected:
                logger.info(f"[IntelligentSearch] {vendor_domain}: Adding {len(rejected)} rejected products to all_rejected_products")
                for rej_prod in rejected:
                    rej_prod["vendor"] = vendor_domain
                    all_rejected_products.append(rej_prod)
                    logger.debug(f"[IntelligentSearch] Rejected: {rej_prod.get('name', 'Unknown')[:40]} - {rej_prod.get('rejection_reason', 'No reason')[:50]}")

            # Track rejected products for potential re-evaluation after relaxation
            # Store the rejected items directly (they have rejection_reason for filtering)
            if rejected and product_requirements and product_requirements.can_relax():
                for rej_prod in rejected:
                    rej_prod["_vendor"] = vendor_domain  # Track source vendor
                    rejected_for_relaxation.append(rej_prod)

            # ==================== STEP 6: Add to Tracker ====================
            if viable:
                for product in viable:
                    # Ensure vendor is set
                    product["vendor"] = vendor_domain
                    # Map viability_score to confidence for tracker scoring
                    product["confidence"] = product.get("viability_score", 0.7)

                    # Add to comparison tracker
                    tracker.add_product(product)

                all_viable_products.extend(viable)
                vendors_visited.append(vendor_domain)
                vendors_with_products += 1  # This vendor was successful

                # VendorRegistry: Record success
                try:
                    vr = get_vendor_registry()
                    vr.record_visit(domain=vendor_domain, success=True)
                except Exception as e:
                    logger.warning(f"[IntelligentSearch] Failed to record vendor success for {vendor_domain}: {e}")

                if event_emitter and hasattr(event_emitter, 'emit_vendor_complete'):
                    await event_emitter.emit_vendor_complete(vendor_domain, len(viable))

                # ==================== Early Stopping Check ====================
                # If we have enough matching products AND met minimum vendors, stop searching
                # CRITICAL: Must meet min_vendors FIRST before checking product count
                if product_requirements:
                    target_qty = product_requirements.target_quantity
                    current_count = len(all_viable_products)
                    # Only early stop if we've met the minimum vendor requirement
                    if vendors_with_products >= min_vendors and current_count >= target_qty:
                        logger.info(
                            f"[IntelligentSearch] EARLY STOP: Met min_vendors ({vendors_with_products}/{min_vendors}) "
                            f"and target products ({current_count}/{target_qty}), stopping vendor search"
                        )
                        break
                    elif current_count >= target_qty:
                        # Have enough products but not enough vendors - keep going
                        logger.info(
                            f"[IntelligentSearch] Have {current_count} products but only {vendors_with_products}/{min_vendors} vendors, continuing..."
                        )
            else:
                # Vendor was visited but yielded no viable products
                logger.warning(f"[IntelligentSearch] {vendor_domain} yielded 0 viable products, trying next vendor")
                vendors_failed.append(vendor_domain)
                # Don't increment vendors_with_products - continue to backup vendors

        except Exception as vendor_err:
            logger.error(f"[IntelligentSearch] Error processing vendor {vendor_domain}: {vendor_err}")
            vendors_failed.append(vendor_domain)
            continue

    # ==================== STEP 5.5: Requirements Relaxation Check ====================
    # If we have some products but not enough, relax requirements and re-evaluate rejected products
    if product_requirements and len(all_viable_products) < product_requirements.target_quantity:
        current_tier = product_requirements.current_relaxation_tier

        while (product_requirements.can_relax() and
               len(all_viable_products) < product_requirements.target_quantity and
               rejected_for_relaxation):
            relaxed_specs = product_requirements.relax()
            if not relaxed_specs:
                logger.info(
                    f"[IntelligentSearch] Requirements relaxed but no specs changed (tier {product_requirements.current_relaxation_tier})"
                )
                continue

            logger.info(
                f"[IntelligentSearch] RELAXATION: Not enough products ({len(all_viable_products)}/{product_requirements.target_quantity}). "
                f"Relaxed requirements tier {current_tier} → {product_requirements.current_relaxation_tier}: {relaxed_specs}"
            )
            current_tier = product_requirements.current_relaxation_tier

            # Re-evaluate rejected products with relaxed requirements
            newly_viable = []
            still_rejected = []

            # Rejection reasons that indicate fundamental category mismatch - NEVER relax these
            FATAL_REJECTION_PATTERNS = [
                "toy", "not a live", "accessory", "food", "treat",
                "cage", "habitat", "enclosure", "bedding", "supplies",
                "carrier", "wheel", "bottle", "bowl"
            ]

            for prod in rejected_for_relaxation:
                specs = prod.get("specs", {})
                title = prod.get("name", "")

                # Check if this product has a fatal rejection reason - NEVER relax these
                rejection_reason = prod.get("rejection_reason", "").lower()
                if any(pattern in rejection_reason for pattern in FATAL_REJECTION_PATTERNS):
                    still_rejected.append(prod)
                    logger.debug(
                        f"[IntelligentSearch] SKIP RELAXATION: {title[:50]} - "
                        f"fatal rejection: {rejection_reason[:60]}"
                    )
                    continue

                # Use quick_title_check with relaxed requirements
                worth_checking, reason = product_requirements.quick_title_check(title)

                if worth_checking:
                    # Passed relaxed title check - add to viable
                    prod["vendor"] = prod.pop("_vendor", prod.get("vendor", "unknown"))
                    prod["relaxation_tier"] = product_requirements.current_relaxation_tier
                    prod["confidence"] = prod.get("viability_score", 0.6)  # Lower confidence for relaxed matches
                    newly_viable.append(prod)
                    tracker.add_product(prod)
                    logger.debug(f"[IntelligentSearch] RELAXED: {title[:50]} now viable ({reason})")
                else:
                    still_rejected.append(prod)

            if newly_viable:
                logger.info(
                    f"[IntelligentSearch] RELAXATION RECOVERY: {len(newly_viable)} products "
                    f"now viable after tier {product_requirements.current_relaxation_tier} relaxation"
                )
                all_viable_products.extend(newly_viable)

            # Update rejected list for next iteration
            rejected_for_relaxation = still_rejected

        if not product_requirements.can_relax() and len(all_viable_products) < product_requirements.target_quantity:
            logger.info(
                f"[IntelligentSearch] Cannot relax further - at maximum tier ({product_requirements.current_relaxation_tier}). "
                f"Have {len(all_viable_products)} products, target was {product_requirements.target_quantity}"
            )

    # ==================== STEP 6: Fallback if ALL vendors failed ====================
    if vendors_with_products == 0 and len(all_viable_products) == 0:
        logger.warning("[IntelligentSearch] All vendor visits failed! Trying intelligence fallback retailers...")

        # Get fallback retailers from Phase 1 intelligence
        # Pass the query so fallback retailers use the actual search term
        fallback_vendors = _extract_vendors_from_intelligence(intelligence, max_vendors=2, query=query)

        # Filter out vendors we already tried
        already_tried_domains = set(vendors_failed)
        fallback_vendors = [v for v in fallback_vendors if v.get("domain") not in already_tried_domains]

        if fallback_vendors:
            logger.info(f"[IntelligentSearch] Trying {len(fallback_vendors)} fallback retailers from intelligence")

            for vendor in fallback_vendors:
                # In fallback mode, still respect min_vendors constraint
                if vendors_with_products >= min_vendors and vendors_with_products >= max_vendors:
                    break

                vendor_url = vendor.get("url")
                vendor_domain = vendor.get("domain", "unknown")

                logger.info(f"[IntelligentSearch] FALLBACK: Visiting {vendor_domain}")

                try:
                    # Navigate to vendor URL (direct search URL)
                    nav_result = await web_vision_mcp.navigate(
                        session_id=web_vision_session_id,
                        url=vendor_url,
                        wait_for="networkidle"
                    )

                    if not nav_result.get("success"):
                        logger.warning(f"[IntelligentSearch] FALLBACK: Failed to navigate to {vendor_domain}")
                        vendors_failed.append(vendor_domain)
                        continue

                    # Try click-to-verify extraction
                    raw_products = []

                    if use_hybrid_extraction and perception_pipeline:
                        try:
                            page = await web_vision_mcp.get_page(web_vision_session_id)
                            if page:
                                verified_products = await perception_pipeline.extract_and_verify(
                                    page=page,
                                    url=vendor_url,
                                    query=query,
                                    max_products=products_per_vendor,
                                    max_price=budget_max,
                                    requirements=requirements,  # Smart prioritization + early stopping
                                    target_viable_products=products_per_vendor
                                )

                                for vp in verified_products:
                                    desc = ""
                                    if vp.specs:
                                        spec_text = ", ".join(f"{k}: {v}" for k, v in vp.specs.items() if v)
                                        if spec_text:
                                            desc = f"Specs: {spec_text}"

                                    raw_products.append({
                                        "name": vp.title,
                                        "price": f"${vp.price:.2f}" if vp.price else "N/A",
                                        "url": vp.url,
                                        "description": desc,
                                        "vendor": vendor_domain,
                                        "specs": vp.specs or {},
                                        "pdp_verified": True,
                                        "in_stock": vp.in_stock,
                                        "extraction_method": "fallback_click_to_verify"
                                    })

                                logger.info(f"[IntelligentSearch] FALLBACK: Verified {len(raw_products)} products from {vendor_domain}")

                                # Record success
                                try:
                                    from orchestrator.shared_state.site_health_tracker import get_health_tracker
                                    ht = get_health_tracker()
                                    ht.record_extraction(url=vendor_url, page_type="listing", success=True, method="fallback_click_to_verify")
                                except Exception as e:
                                    logger.warning(f"[IntelligentSearch] FALLBACK: Failed to record extraction success for {vendor_domain}: {e}")
                        except Exception as extract_err:
                            logger.warning(f"[IntelligentSearch] FALLBACK: Extraction failed for {vendor_domain}: {extract_err}")

                            # Record failure
                            try:
                                from orchestrator.shared_state.site_health_tracker import get_health_tracker
                                ht = get_health_tracker()
                                ht.record_extraction(url=vendor_url, page_type="listing", success=False, method="fallback_extraction_error")
                            except Exception as e:
                                logger.warning(f"[IntelligentSearch] FALLBACK: Failed to record extraction failure for {vendor_domain}: {e}")

                    # Fallback to basic extraction if no products
                    if not raw_products:
                        logger.info(f"[IntelligentSearch] FALLBACK: Using basic extraction for {vendor_domain}")
                        basic_result = await _web_vision_visit_and_read(
                            url=vendor_url,
                            reading_goal=f"Find products matching: {query}",
                            session_id=web_vision_session_id
                        )
                        if basic_result:
                            extracted = basic_result.get("extracted_info", {}).get("products", [])
                            for idx, p in enumerate(extracted):
                                if isinstance(p, dict):
                                    p["vendor"] = vendor_domain
                                    p["extraction_method"] = "fallback_basic_llm"
                                    # Set URL to vendor homepage if not extracted (real URL, not fake fragment)
                                    if not p.get("url"):
                                        p["url"] = vendor_url
                                    raw_products.append(p)

                    if raw_products:
                        # Filter viable products - use reasoning-based filter if available
                        if requirements_reasoning and requirements_reasoning.get("reasoning_document"):
                            viability_result = await filter_viable_products_with_reasoning(
                                products=raw_products,
                                requirements_reasoning=requirements_reasoning["reasoning_document"],
                                query=query,
                                max_products=products_per_vendor
                            )
                        else:
                            viability_result = await filter_viable_products(
                                products=raw_products,
                                requirements=requirements,
                                query=query,
                                max_products=products_per_vendor
                            )

                        viable = viability_result.get("viable_products", [])
                        logger.info(f"[IntelligentSearch] FALLBACK: {vendor_domain}: {len(viable)}/{len(raw_products)} products viable")

                        if viable:
                            for product in viable:
                                product["vendor"] = vendor_domain
                                product["confidence"] = product.get("viability_score", 0.7)
                                tracker.add_product(product)

                            all_viable_products.extend(viable)
                            vendors_visited.append(vendor_domain)
                            vendors_with_products += 1
                        else:
                            vendors_failed.append(vendor_domain)
                    else:
                        vendors_failed.append(vendor_domain)

                except Exception as fallback_err:
                    logger.error(f"[IntelligentSearch] FALLBACK: Error with {vendor_domain}: {fallback_err}")
                    vendors_failed.append(vendor_domain)
                    continue
        else:
            logger.warning("[IntelligentSearch] No fallback retailers available from intelligence")

    # ==================== STEP 7: Get Final Rankings ====================
    logger.info("[IntelligentSearch] Step 7: Finalizing rankings")

    top_products = tracker.get_top_products()

    # Check if we met minimum vendor requirement
    min_vendors_met = vendors_with_products >= min_vendors

    # Log summary with backup vendor info
    backup_used = len(vendors_failed) > 0
    logger.info(
        f"[IntelligentSearch] Complete: {vendors_with_products}/{min_vendors} minimum vendors, "
        f"{len(vendors_failed)} failed/skipped, {len(top_products)} final products"
    )

    # Log warning if we didn't meet minimum vendors
    if not min_vendors_met:
        logger.warning(
            f"[IntelligentSearch] ⚠️ MINIMUM VENDORS NOT MET: "
            f"Only {vendors_with_products}/{min_vendors} vendors yielded products. "
            f"Results may not represent full market comparison."
        )
        # Log intervention for debugging
        try:
            from orchestrator.intervention_manager import log_extraction_failed
            log_extraction_failed(
                session_id=session_id,
                vendor="multi_vendor_search",
                query=query,
                error=f"Only {vendors_with_products}/{min_vendors} vendors yielded products",
                url=None,
                page_summary=f"Tried {len(vendor_candidates)} vendors, {len(vendors_failed)} failed"
            )
        except Exception as e:
            logger.warning(f"[IntelligentSearch] Failed to record insufficient vendors intervention: {e}")

    if backup_used:
        logger.info(f"[IntelligentSearch] Failed/skipped vendors: {', '.join(vendors_failed)}")
    logger.info(tracker.get_summary())

    # Build findings in expected format
    findings = []
    reliability_tracker = get_tracker()
    for product in top_products:
        findings.append({
            "name": product.get("name", "Unknown"),
            "price": product.get("price", "N/A"),
            "vendor": product.get("vendor", "unknown"),
            "url": product.get("url", ""),
            "description": product.get("description", ""),
            "confidence": product.get("viability_score", product.get("confidence", 0.7)),
            "extraction_method": product.get("extraction_method", "unknown"),
            "viability_score": product.get("viability_score", 0.7),
            "strengths": product.get("strengths", []),
            "weaknesses": product.get("weaknesses", [])
        })

    # Build rejected list in expected format (for context awareness)
    logger.info(f"[IntelligentSearch] Building rejected output from {len(all_rejected_products)} rejected products")
    rejected_output = []
    for product in all_rejected_products:
        rejected_output.append({
            "name": product.get("name", "Unknown"),
            "price": product.get("price", "N/A"),
            "vendor": product.get("vendor", "unknown"),
            "url": product.get("url", ""),
            "rejection_reason": product.get("rejection_reason", "Unknown reason"),
        })
    logger.info(f"[IntelligentSearch] Final rejected_output count: {len(rejected_output)}")

    return {
        "findings": findings,
        "rejected": rejected_output,  # For context.md and research.json
        "synthesis": {
            "total_sources": len(vendors_visited),
            "vendors_visited": vendors_visited,
            "vendors_failed": vendors_failed,
            "vendors_successful": vendors_with_products,
            "min_vendors_required": min_vendors,
            "min_vendors_met": min_vendors_met,  # Flag for Synthesizer to inform user
            "products_considered": tracker.get_stats()["total_considered"],
            "products_rejected": len(rejected_output),
            "final_recommendations": len(findings),
            "search_query_used": shopping_query
        },
        "stats": tracker.get_stats()
    }


async def _build_smart_shopping_queries(
    query: str,
    intelligence: Dict[str, Any],
    target_vendors: List[str] = None
) -> Dict[str, Any]:
    """
    Build optimized shopping queries using LLM.

    Returns:
        {
            "primary": "RTX 4060 laptop 16GB RAM for sale",
            "site_specific": {
                "bestbuy.com": "site:bestbuy.com RTX 4060 laptop gaming",
                "newegg.com": "RTX 4060 laptop newegg",
                ...
            }
        }
    """
    import os
    from orchestrator.shared import call_llm_json

    # Extract relevant intelligence
    specs = intelligence.get("specs_discovered", {}) if intelligence else {}
    hard_reqs = intelligence.get("hard_requirements", []) if intelligence else []
    price_range = intelligence.get("price_range", {}) if intelligence else {}
    retailers = intelligence.get("retailers", {}) if intelligence else {}

    # Get high-relevance retailers for site-specific queries (hybrid strategy)
    high_relevance_retailers = []
    if retailers:
        for name, info in retailers.items():
            if isinstance(info, dict):
                score = info.get("relevance_score", 0.5)
                include = info.get("include_in_search", True)
                if include and score >= 0.8:
                    high_relevance_retailers.append(name)

    # Also include target_vendors if provided
    vendors_for_queries = list(set(high_relevance_retailers + (target_vendors or [])))[:5]

    # Build price hint
    price_hint = ""
    max_price = price_range.get("max")
    if max_price and isinstance(max_price, (int, float)) and max_price < 3000:
        price_hint = f"Budget: under ${int(max_price)}"

    # Get current year for context
    from datetime import datetime
    current_year = datetime.now().year

    # Load prompt from recipe file
    prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "research" / "shopping_query_generator.md"
    if prompt_path.exists():
        base_prompt = prompt_path.read_text()
    else:
        logger.warning(f"[SmartQuery] Prompt file not found: {prompt_path}")
        base_prompt = "Generate optimized shopping search queries. Return JSON with 'primary' (ending with 'for sale') and 'site_specific' keys."

    # Build full prompt with dynamic data
    prompt = f"""{base_prompt}

---

## Current Task

USER QUERY: {query}

DISCOVERED SPECS FROM RESEARCH: {json.dumps(specs) if specs else "None"}
HARD REQUIREMENTS: {hard_reqs if hard_reqs else "None"}
{price_hint}
CURRENT YEAR: {current_year}
TARGET VENDORS FOR SITE-SPECIFIC QUERIES: {vendors_for_queries if vendors_for_queries else "None (general search only)"}

Generate the optimized queries now. Return JSON ONLY:"""

    llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
    llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    try:
        result = await call_llm_json(prompt=prompt, llm_url=llm_url, llm_model=llm_model, llm_api_key=llm_api_key, max_tokens=500)

        if result and isinstance(result, dict):
            # Ensure required fields exist
            primary = result.get("primary", f"{query} for sale")
            site_specific = result.get("site_specific", {})

            # Apply rejection-based refinements to site-specific queries
            try:
                from orchestrator.rejection_tracker import get_rejection_tracker
                tracker = get_rejection_tracker()

                for vendor in list(site_specific.keys()):
                    refinements = tracker.get_query_refinements(vendor, query)
                    if refinements:
                        # Add refinements to site-specific query
                        current_query = site_specific[vendor]
                        site_specific[vendor] = f"{current_query} {' '.join(refinements)}"
                        logger.info(f"[SmartQuery] Applied rejection refinements to {vendor}: {refinements}")
            except Exception as ref_err:
                logger.debug(f"[SmartQuery] Could not apply rejection refinements: {ref_err}")

            return {"primary": primary, "site_specific": site_specific}
    except Exception as e:
        logger.warning(f"[SmartQuery] LLM query generation failed: {e}")

    # Fallback: Build simple query without LLM
    base_query = query.lower().strip()
    for term in ["for sale", "buy", "price", "shop", "store", "find", "looking for"]:
        base_query = base_query.replace(term, "").strip()

    # Add top 2 specs (using helper for backwards compatibility with both formats)
    from orchestrator.shared.spec_utils import get_spec_value
    spec_parts = []
    if specs:
        for key in list(specs.keys())[:2]:
            value = get_spec_value(specs, key)
            if value and str(value).strip():
                spec_parts.append(str(value))

    if spec_parts:
        primary = f"{base_query} {' '.join(spec_parts)} for sale"
    else:
        primary = f"{base_query} for sale"

    return {"primary": " ".join(primary.split()), "site_specific": {}}


async def _try_vendor_site_search(
    session_id: str,
    vendor_domain: str,
    query: str,
    intelligence: Dict[str, Any],
    perception_pipeline
) -> List[Dict[str, Any]]:
    """
    Try to use a vendor's site search to find products.

    Used when the initial page is a category overview without actual products.
    Navigates to vendor's search URL and extracts products from results.
    """
    from orchestrator import web_vision_mcp

    # Extract budget max from intelligence for pre-filtering
    budget_max = None
    if intelligence:
        price_range = intelligence.get("price_range", {})
        if isinstance(price_range, dict):
            budget_max = price_range.get("budget_max") or price_range.get("max")
        elif isinstance(price_range, str):
            import re
            match = re.search(r'\$?(\d+(?:,\d{3})*(?:\.\d{2})?)', price_range)
            if match:
                budget_max = float(match.group(1).replace(",", ""))

    # Map vendor domains to their search URL patterns
    vendor_search_patterns = {
        "bestbuy.com": "https://www.bestbuy.com/site/searchpage.jsp?st={query}",
        "newegg.com": "https://www.newegg.com/p/pl?d={query}",
        "amazon.com": "https://www.amazon.com/s?k={query}",
        "dell.com": "https://www.dell.com/en-us/search/{query}",
        "lenovo.com": "https://www.lenovo.com/us/en/search?text={query}",
        "hp.com": "https://www.hp.com/us-en/search.html?q={query}",
        "walmart.com": "https://www.walmart.com/search?q={query}",
        "microcenter.com": "https://www.microcenter.com/search/search_results.aspx?Ntt={query}",
    }

    # Find matching domain
    search_pattern = None
    for domain, pattern in vendor_search_patterns.items():
        if domain in vendor_domain.lower():
            search_pattern = pattern
            break

    if not search_pattern:
        logger.info(f"[IntelligentSearch] No search pattern for {vendor_domain}")
        return []

    # Build search query from user query and intelligence
    # IMPORTANT: Simplify query for retailer site search (removes natural language)
    from orchestrator.query_planner import simplify_query_for_retailers_async
    search_terms = await simplify_query_for_retailers_async(query)

    if intelligence:
        # Add key specs for more targeted search (use helper for backwards compatibility)
        from orchestrator.shared.spec_utils import get_spec_value
        specs = intelligence.get("specs_discovered", {})
        if specs:
            # Get first spec key and extract its value (handles both old and new formats)
            first_key = next(iter(specs.keys()), None)
            if first_key:
                top_spec = get_spec_value(specs, first_key, "")
                if top_spec and str(top_spec).strip():
                    search_terms = f"{search_terms} {top_spec}"

    logger.info(f"[IntelligentSearch] Simplified query for site search: '{query}' → '{search_terms}'")

    # URL encode the search query
    from urllib.parse import quote
    search_url = search_pattern.format(query=quote(search_terms))

    logger.info(f"[IntelligentSearch] Navigating to site search: {search_url[:80]}...")

    try:
        # Navigate to search results
        nav_result = await web_vision_mcp.navigate(
            session_id=session_id,
            url=search_url,
            wait_for="networkidle"
        )

        if not nav_result.get("success"):
            logger.warning(f"[IntelligentSearch] Site search navigation failed for {vendor_domain}")
            return []

        # Extract products from search results using click-to-verify
        page = await web_vision_mcp.get_page(session_id)
        if not page or not perception_pipeline:
            return []

        # Build requirements from intelligence for smart prioritization
        site_search_requirements = {
            "key_requirements": intelligence.get("key_requirements", []) if intelligence else [],
            "price_range": intelligence.get("price_range", {}) if intelligence else {},
            "hard_requirements": intelligence.get("key_requirements", []) if intelligence else [],
        }

        # Use click-to-verify as PRIMARY extraction method
        verified_products = await perception_pipeline.extract_and_verify(
            page=page,
            url=search_url,
            query=query,
            max_products=5,
            max_price=budget_max,
            requirements=site_search_requirements,  # Smart prioritization + early stopping
            target_viable_products=4
        )

        # Convert VerifiedProduct to dict format
        raw_products = []
        for vp in verified_products:
            desc = ""
            if vp.specs:
                spec_text = ", ".join(f"{k}: {v}" for k, v in vp.specs.items() if v)
                if spec_text:
                    desc = f"Specs: {spec_text}"

            raw_products.append({
                "name": vp.title,
                "price": f"${vp.price:.2f}" if vp.price else "N/A",
                "url": vp.url,
                "description": desc,
                "vendor": vendor_domain,
                "specs": vp.specs or {},
                "pdp_verified": True,  # All verified via PDP
                "in_stock": vp.in_stock,
                "extraction_method": "click_to_verify_site_search"
            })

        logger.info(f"[IntelligentSearch] ✓ Site search verified {len(raw_products)} products from {vendor_domain}")

        # Record success to schema registry
        if raw_products:
            try:
                from orchestrator.shared_state.site_health_tracker import get_health_tracker
                ht = get_health_tracker()
                ht.record_extraction(
                    url=search_url,
                    page_type="listing",
                    success=True,
                    method="site_search"
                )
            except Exception as e:
                logger.warning(f"[IntelligentSearch] Failed to record site_search success for {vendor_domain}: {e}")
        else:
            # No products found - record failure
            try:
                from orchestrator.shared_state.site_health_tracker import get_health_tracker
                ht = get_health_tracker()
                ht.record_extraction(
                    url=search_url,
                    page_type="listing",
                    success=False,
                    method="site_search"
                )
            except Exception as e:
                logger.warning(f"[IntelligentSearch] Failed to record site_search failure for {vendor_domain}: {e}")

        return raw_products

    except Exception as e:
        logger.warning(f"[IntelligentSearch] Site search failed for {vendor_domain}: {e}")

        # Record failure for schema recalibration
        try:
            from orchestrator.shared_state.site_health_tracker import get_health_tracker
            ht = get_health_tracker()
            ht.record_extraction(
                url=search_url if 'search_url' in dir() else f"https://{vendor_domain}/search",
                page_type="listing",
                success=False,
                method="site_search_error"
            )
        except Exception as tracker_err:
            logger.warning(f"[IntelligentSearch] Failed to record site_search_error for {vendor_domain}: {tracker_err}")

        return []


def _fallback_vendor_selection(
    search_results: List[Dict[str, Any]],
    max_vendors: int = 2
) -> List[Dict[str, Any]]:
    """
    Fallback vendor selection when LLM selection fails.
    Uses VendorRegistry to identify and filter vendor URLs dynamically.

    The registry learns which vendors work over time - NO hardcoded lists.
    """
    logger.info("[IntelligentSearch] Using fallback vendor selection")

    # Get vendor registry for dynamic vendor knowledge
    registry = get_vendor_registry()

    # Skip patterns - review/info sites (not shopping vendors)
    # These are NOT vendors, just content sites
    skip_info_sites = [
        "reddit.com", "youtube.com", "wikipedia.org", "cnet.com", "techradar.com",
        "tomshardware.com", "tomsguide.com", "pcmag.com", "theverge.com",
        "howtogeek.com", "arstechnica.com", "zdnet.com", "forbes.com", "medium.com"
    ]

    vendors = []
    seen_domains = set()

    for result in search_results:
        if len(vendors) >= max_vendors:
            break

        url = result.get("url", "")
        domain = _extract_domain(url)

        if domain in seen_domains:
            continue

        # Skip info/review sites (not vendors)
        if any(skip in domain for skip in skip_info_sites):
            continue

        # Check if vendor is blocked in registry
        if registry.is_blocked(domain):
            logger.info(f"[FallbackVendor] Skipping blocked vendor: {domain}")
            continue

        # Check if vendor is usable (not blocked, reasonable success rate)
        if not registry.is_usable(domain):
            logger.info(f"[FallbackVendor] Skipping unusable vendor: {domain}")
            continue

        # Check if URL looks like a product/shopping page
        url_lower = url.lower()
        is_shopping_url = any(signal in url_lower for signal in [
            "/shop", "/product", "/buy", "/store", "/item",
            "/laptops", "/computers", "/electronics", "/pets", "/search"
        ])

        # Check if domain is in registry as a known vendor
        known_vendor = registry.get(domain)
        is_known = known_vendor is not None

        if is_shopping_url or is_known:
            seen_domains.add(domain)

            # Register/update vendor discovery
            registry.add_or_update(
                domain=domain,
                discovered_via="google_search_fallback",
                discovery_query=""
            )

            vendors.append({
                "url": url,
                "domain": domain,
                "title": result.get("title", ""),
                "rank": len(vendors) + 1,
                "vendor_type": known_vendor.vendor_type if known_vendor else "unknown",
                "reasoning": "Dynamic fallback selection (VendorRegistry)"
            })

    logger.info(f"[FallbackVendor] Selected {len(vendors)} vendors from search results")
    return vendors


async def search_products(
    query: str,
    research_goal: str,
    intelligence: Optional[Dict] = None,
    max_sources: int = 12,
    session_id: str = "default",
    web_vision_session_id: str = None,  # NEW: Web Vision session ID
    event_emitter: Optional[Any] = None,
    human_assist_allowed: bool = True,  # Default: enabled
    token_budget: int = 10800,
    use_snapshots: bool = True,
    enable_deep_browse: bool = True,  # Enable multi-page browsing
    mode: str = "standard"  # Research mode: "standard" or "deep"
) -> Dict[str, Any]:
    """
    Phase 2: Search for products/listings/information.

    If intelligence provided: Uses smart queries based on credible sources and keywords
    If intelligence=None: Uses generic queries

    Args:
        query: Search query
        research_goal: What we're trying to find
        intelligence: Optional Phase 1 intelligence to guide search
        max_sources: Max sources to check
        session_id: Session ID for browser context (enables CAPTCHA intervention)
        event_emitter: Optional progress events
        token_budget: Token limit for results
        use_snapshots: Enable snapshot compression

    Returns:
        {
            "findings": [...],
            "synthesis": {...},
            "stats": {...}
        }
    """
    from orchestrator import web_vision_mcp
    from orchestrator.llm_candidate_filter import llm_filter_candidates

    # Initialize reliability tracker for source quality scoring
    reliability_tracker = get_tracker()

    # Create Web Vision session ID if not provided
    if web_vision_session_id is None:
        web_vision_session_id = f"{session_id}_products"

    logger.info(f"[Phase2] Searching for: {query} (intelligence: {intelligence is not None}, session={web_vision_session_id})")

    # Extract budget max from intelligence for pre-filtering candidates
    budget_max = None
    if intelligence:
        price_range = intelligence.get("price_range", {})
        if isinstance(price_range, dict):
            budget_max = price_range.get("budget_max") or price_range.get("max")
        elif isinstance(price_range, str):
            import re
            match = re.search(r'\$?(\d+(?:,\d{3})*(?:\.\d{2})?)', price_range)
            if match:
                budget_max = float(match.group(1).replace(",", ""))

    if budget_max:
        logger.info(f"[Phase2] Budget max: ${budget_max:.2f} (will pre-filter candidates)")

    # Initialize hybrid perception pipeline for vendor catalog extraction
    # This enables vision+HTML extraction for JS-heavy vendor pages (Dell, ASUS, etc.)
    use_hybrid_extraction = os.getenv("PERCEPTION_ENABLE_HYBRID", "true").lower() == "true"
    perception_pipeline = None
    if use_hybrid_extraction:
        try:
            from orchestrator.product_perception import ProductPerceptionPipeline, VerifiedProduct
            perception_pipeline = ProductPerceptionPipeline()
            logger.info("[Phase2] Click-to-verify extraction enabled for vendor catalogs")
        except ImportError as e:
            logger.warning(f"[Phase2] Could not load ProductPerceptionPipeline: {e}")
            use_hybrid_extraction = False

    if event_emitter:
        await event_emitter.emit_phase_started("phase2", "product_search")

    # Generate search queries
    if intelligence:
        # Smart queries based on intelligence
        queries = await _generate_targeted_queries(query, intelligence, mode)
        logger.info(f"[Phase2] Using {len(queries)} intelligence-guided queries (mode={mode})")
    else:
        # Generic queries - optimize for shopping to help Google return product pages
        # Try multiple query variations to increase chance of finding products
        base_query = query.lower().strip()

        # Remove existing shopping terms to avoid duplication
        for term in ["for sale", "buy", "price", "shop", "store"]:
            base_query = base_query.replace(term, "").strip()

        queries = [
            f"{base_query} buy",           # Shopping intent
            f"{base_query} price",         # Price comparison pages
            f"{base_query} for sale",      # Marketplace listings
        ]
        logger.info(f"[Phase2] Using {len(queries)} shopping-optimized queries (no intelligence)")

    # Search and visit using Web Vision
    findings = []
    for search_query in queries:
        if len(findings) >= max_sources:
            break

        # Perform Web Vision search
        raw_candidates = await _web_vision_search(
            query=search_query,
            max_results=max_sources * 2,
            session_id=web_vision_session_id,
            event_emitter=event_emitter
        )

        # LLM filter
        logger.info(f"[Phase2] Filtering {len(raw_candidates)} candidates for: {search_query}")
        candidates = await llm_filter_candidates(
            raw_candidates,
            query=search_query,
            research_goal=research_goal,
            max_candidates=min(5, max_sources - len(findings))
        )

        # Visit candidates
        for candidate in candidates:
            if len(findings) >= max_sources:
                break

            try:
                candidate_url = candidate["url"]

                # Check if this is a vendor catalog URL that needs hybrid extraction
                is_vendor_catalog = _is_vendor_catalog_url(candidate_url)

                if is_vendor_catalog and use_hybrid_extraction and perception_pipeline:
                    # Use click-to-verify extraction for vendor catalogs
                    logger.info(f"[Phase2] Using click-to-verify extraction for vendor catalog: {candidate_url[:60]}")

                    try:
                        # Navigate to the page
                        nav_result = await web_vision_mcp.navigate(
                            session_id=web_vision_session_id,
                            url=candidate_url,
                            wait_for="networkidle"
                        )

                        if not nav_result.get("success"):
                            logger.warning(f"[Phase2] Failed to navigate to {candidate_url[:60]}: {nav_result.get('message')}")
                            continue

                        # Get page object for hybrid extraction
                        page = await web_vision_mcp.get_page(web_vision_session_id)
                        if not page:
                            logger.warning(f"[Phase2] Failed to get page object for {candidate_url[:60]}")
                            # Fall back to basic extraction
                            result = await _web_vision_visit_and_read(
                                url=candidate_url,
                                reading_goal=research_goal,
                                session_id=web_vision_session_id
                            )
                        else:
                            # Build requirements from intelligence for smart prioritization
                            phase2_requirements = {
                                "key_requirements": intelligence.get("key_requirements", []) if intelligence else [],
                                "price_range": intelligence.get("price_range", {}) if intelligence else {},
                                "hard_requirements": intelligence.get("key_requirements", []) if intelligence else [],
                            } if intelligence else None

                            # Run click-to-verify extraction (PRIMARY flow)
                            verified_products = await perception_pipeline.extract_and_verify(
                                page=page,
                                url=candidate_url,
                                query=query,
                                max_products=5,
                                max_price=budget_max,
                                requirements=phase2_requirements,  # Smart prioritization + early stopping
                                target_viable_products=4
                            )

                            # Convert VerifiedProduct list to findings format
                            # All products are now PDP-verified with accurate prices
                            products = []
                            for vp in verified_products:
                                # Build description from specs
                                desc = ""
                                if vp.specs:
                                    spec_text = ", ".join(f"{k}: {v}" for k, v in vp.specs.items() if v)
                                    if spec_text:
                                        desc = f"Specs: {spec_text}"

                                product = {
                                    "name": vp.title,
                                    "price": f"${vp.price:.2f}" if vp.price else "N/A",
                                    "url": vp.url,
                                    "description": desc,
                                    "confidence": 0.90,  # High confidence - all PDP verified
                                    "vendor": _extract_domain(candidate_url),
                                    "extraction_method": vp.extraction_source,
                                    "pdp_verified": True,
                                    "in_stock": vp.in_stock,
                                }
                                products.append(product)

                            if products:
                                logger.info(f"[Phase2] ✓ Verified {len(products)} products from {candidate_url[:60]}")
                                # Record success
                                try:
                                    from orchestrator.shared_state.site_health_tracker import get_health_tracker
                                    ht = get_health_tracker()
                                    ht.record_extraction(url=candidate_url, page_type="listing", success=True, method="phase2_click_to_verify")
                                except Exception as e:
                                    logger.warning(f"[Phase2] Failed to record click_to_verify success: {e}")
                            else:
                                logger.warning(f"[Phase2] Click-to-verify found 0 products from {candidate_url[:60]}")
                                # Record failure
                                try:
                                    from orchestrator.shared_state.site_health_tracker import get_health_tracker
                                    ht = get_health_tracker()
                                    ht.record_extraction(url=candidate_url, page_type="listing", success=False, method="phase2_no_products")
                                except Exception as e:
                                    logger.warning(f"[Phase2] Failed to record no_products failure: {e}")

                            # Build result in expected format
                            result = {
                                "url": candidate_url,
                                "title": candidate.get("title", ""),
                                "extracted_info": {
                                    "products": products,
                                    "page_type": "vendor_catalog"
                                },
                                "text_content": "",  # Not needed for click-to-verify extraction
                                "extraction_method": "click_to_verify"
                            }
                    except Exception as hybrid_err:
                        logger.warning(f"[Phase2] Click-to-verify extraction failed for {candidate_url[:60]}: {hybrid_err}")

                        # Record failure for schema recalibration
                        try:
                            from orchestrator.shared_state.site_health_tracker import get_health_tracker
                            ht = get_health_tracker()
                            ht.record_extraction(url=candidate_url, page_type="listing", success=False, method="phase2_exception")
                        except Exception as e:
                            logger.warning(f"[Phase2] Failed to record phase2_exception: {e}")

                        # Fall back to basic extraction
                        result = await _web_vision_visit_and_read(
                            url=candidate_url,
                            reading_goal=research_goal,
                            session_id=web_vision_session_id
                        )
                else:
                    # Standard extraction for non-vendor pages
                    result = await _web_vision_visit_and_read(
                        url=candidate_url,
                        reading_goal=research_goal,
                        session_id=web_vision_session_id
                    )

                # NEW: Check if multi-page browsing needed (e.g., vendor catalogs)
                if result and enable_deep_browse and deep_browse and detect_navigation_opportunities:
                    try:
                        # Get sanitized text content from result
                        text_content = result.get("text_content", "")
                        if text_content:
                            # Check for multi-page opportunities
                            nav_check = await detect_navigation_opportunities(
                                page_content=text_content,
                                url=candidate["url"],
                                browsing_goal=research_goal
                            )

                            # Check if this is a catalog page worth deep browsing
                            should_deep_browse = False
                            nav_type = nav_check.get("navigation_type", "")

                            # Pagination detected - likely vendor catalog
                            if nav_check.get("has_more_pages") and nav_type == "pagination":
                                should_deep_browse = True

                            # Categories detected - explore all categories
                            if nav_check.get("categories") and len(nav_check["categories"]) > 0:
                                should_deep_browse = True

                            # Multiple products on first page - likely has more pages
                            products = result.get("extracted_info", {}).get("products", [])
                            if isinstance(products, list) and len(products) >= 2:
                                should_deep_browse = True

                            if should_deep_browse:
                                logger.info(
                                    f"[Phase2] Catalog page detected (type={nav_type}, "
                                    f"products={len(products) if isinstance(products, list) else 0}, "
                                    f"categories={len(nav_check.get('categories', []))}), "
                                    f"enabling deep browse for {candidate['url'][:60]}"
                                )

                                # Deep browse to get all pages (using Web Vision session)
                                # Pass LLM config so should_continue_browsing() can evaluate
                                deep_result = await deep_browse(
                                    url=candidate["url"],
                                    browsing_goal=research_goal,
                                    max_pages=10,  # More pages for Phase 2 (product search)
                                    session_id=web_vision_session_id,  # Pass Web Vision session
                                    llm_url=os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions"),
                                    llm_model=os.getenv("SOLVER_MODEL_ID", "qwen3-coder"),
                                    llm_api_key=os.getenv("SOLVER_API_KEY", "qwen-local")
                                )

                                if deep_result:
                                    result = deep_result  # Replace single-page with multi-page result
                                    logger.info(
                                        f"[Phase2] Deep browse complete: "
                                        f"{deep_result.get('pages_visited', 1)} pages, "
                                        f"{len(deep_result.get('extracted_info', {}).get('products', []))} products aggregated"
                                    )
                    except Exception as deep_error:
                        logger.warning(f"[Phase2] Deep browse failed, using single-page result: {deep_error}")
                        # Continue with single-page result

                if result:
                    candidate_url = candidate.get("url", "")
                    extracted_products = result.get("extracted_info", {}).get("products", [])
                    if extracted_products:
                        logger.info(f"[Phase2] Page {candidate_url[:60]} has {len(extracted_products)} products")

                    source_type = candidate.get("source_type") or _fallback_source_type(candidate_url)
                    quality_score = candidate.get("quality_score")
                    reliability_score = candidate.get("reliability_score")
                    if quality_score is None:
                        reliability_score = reliability_tracker.get_reliability(candidate_url)
                        quality_score = reliability_score

                    result["source_url"] = candidate_url
                    result["source_type"] = source_type
                    result["source_reliability"] = quality_score
                    result["source_quality"] = quality_score
                    result["source_reliability_db"] = reliability_score

                    reliability_tracker.log_extraction(
                        url=candidate_url,
                        extraction_type="products",
                        success=bool(extracted_products),
                        confidence=float(quality_score) if quality_score is not None else 0.5,
                        metadata={"source_type": source_type},
                    )

                    findings.append(result)
            except Exception as e:
                logger.error(f"[Phase2] Error visiting {candidate.get('url')}: {e}")
                reliability_tracker.log_extraction(
                    url=candidate.get("url", ""),
                    extraction_type="products",
                    success=False,
                    confidence=0.0,
                    error_type=type(e).__name__,
                )

    # Synthesize results
    synthesis = await _synthesize_findings(findings, query, research_goal)

    stats = {
        "sources_checked": len(findings),
        "intelligence_used": intelligence is not None,
        "avg_quality": synthesis.get("confidence", 0.0)
    }

    logger.info(f"[Phase2] Complete: {stats['sources_checked']} sources, confidence: {stats['avg_quality']:.2f}")

    if event_emitter:
        await event_emitter.emit_phase_complete("phase2", {"findings": findings})

    return {
        "findings": findings,
        "synthesis": synthesis,
        "stats": stats
    }


async def research(
    query: str,
    research_goal: str = None,
    mode: str = "standard",
    max_sources: int = 15,
    session_id: str = "default",
    human_assist_allowed: bool = False,
    event_emitter: Optional[Any] = None,
    token_budget: int = 10800,
    use_snapshots: bool = True
) -> Dict[str, Any]:
    """
    DEPRECATED: Use adaptive_research() from internet_research_mcp.py instead.

    This function now redirects to the canonical entry point to ensure:
    - Consistent Browser Agent integration
    - Unified session intelligence caching
    - Proper event emission
    - Intervention registration

    Args:
        query: Search query
        research_goal: Optional - What we're trying to learn
        mode: "standard" or "deep"
        max_sources: Maximum sources to check
        session_id: Session ID for browser context persistence
        human_assist_allowed: Allow human intervention for CAPTCHAs
        event_emitter: Optional event emitter for progress tracking
        token_budget: Token budget for research
        use_snapshots: Enable snapshot compression

    Returns:
        Research results (same format as adaptive_research)
    """
    logger.warning(
        "[DEPRECATED] research_orchestrator.research() is deprecated. "
        "Use adaptive_research() from internet_research_mcp.py for full feature support "
        "(Browser Agent, session intelligence, unified events)."
    )

    # Redirect to canonical entry point
    from orchestrator.internet_research_mcp import adaptive_research

    # Validate and pass mode directly (unified vocabulary)
    if mode not in ["standard", "deep"]:
        mode = "standard"

    return await adaptive_research(
        query=query,
        research_goal=research_goal,
        session_id=session_id,
        human_assist_allowed=human_assist_allowed,
        event_emitter=event_emitter,
        mode=mode,  # Unified vocabulary: pass mode directly
        remaining_token_budget=token_budget,
        query_type="general_research",  # Default type
        force_refresh=False
    )


async def _synthesize_findings(
    findings: List[Dict],
    query: str,
    research_goal: str
) -> Dict[str, Any]:
    """
    Synthesize findings into coherent answer.

    Works for ANY research type - just intelligent synthesis.
    """
    import os
    from urllib.parse import urlparse

    if not findings:
        return {
            "answer": "No information found",
            "confidence": 0.0,
            "key_findings": [],
            "recommendations": []
        }

    # Collect all extracted info (handle snapshot mode where findings only have metadata)
    all_info = [f.get("extracted_info", {}) for f in findings]
    all_summaries = [f.get("summary", "") for f in findings]
    page_types = [f.get("page_type", "unknown") for f in findings]

    # ==================== CATALOG DETECTION ====================
    # Detect if any findings appear to be vendor catalogs with multiple items
    catalog_hints = _detect_vendor_catalogs(findings)

    # Load prompt from recipe file
    prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "research" / "research_synthesizer.md"
    if prompt_path.exists():
        base_prompt = prompt_path.read_text()
    else:
        logger.warning(f"[Synthesizer] Prompt file not found: {prompt_path}")
        base_prompt = "Synthesize research findings into a coherent answer. Return JSON with answer, key_findings, recommendations, confidence, contradictions, and sources_used."

    # Build summaries string
    summaries_text = chr(10).join(f"{i+1}. {s}" for i, s in enumerate(all_summaries))

    # Build full prompt with dynamic data
    prompt = f"""{base_prompt}

---

## Current Task

RESEARCH QUERY: {query}
RESEARCH GOAL: {research_goal}

FINDINGS FROM {len(findings)} SOURCES:
Page types encountered: {', '.join(set(page_types))}

SUMMARIES:
{summaries_text}

DETAILED INFORMATION:
{json.dumps(all_info[:5], indent=2)}

Synthesize now. Return JSON ONLY:"""

    # Call LLM for synthesis
    from orchestrator.shared import call_llm_json

    llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
    llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    result = await call_llm_json(prompt=prompt, llm_url=llm_url, llm_model=llm_model, llm_api_key=llm_api_key, max_tokens=3000)

    # Add catalog hints to synthesis
    if catalog_hints:
        result["catalog_hints"] = catalog_hints
        logger.info(f"[Research] Detected {len(catalog_hints)} vendor catalogs for potential deep-crawling")

    return result


async def _extract_intelligence_from_findings(
    findings: List[Dict],
    query: str,
    budget_intent: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Extract meta-intelligence from Phase 1 findings.

    Like: "What do people care about? Who's credible? What should I look for?"

    Args:
        findings: List of source findings from Phase 1
        query: Original user query
        budget_intent: Budget constraints parsed from query (from _parse_budget_intent_from_query)
    """
    import os

    if not findings:
        return {"key_topics": [], "credible_sources": [], "important_criteria": []}

    budget_intent = budget_intent or {}

    # Build summaries with source classification for confidence tracking
    summaries_with_sources = []
    for i, f in enumerate(findings, 1):
        summary = f.get("summary", f.get("description", "No summary"))
        source_type = f.get("source_type", "general")
        reliability = f.get("source_reliability", 0.5)
        source_url = f.get("source_url", f.get("url", "unknown"))
        summaries_with_sources.append(
            f"{i}. [{source_type}, r={reliability:.2f}] {summary[:200]}"
        )

    # Handle both old format (extracted_info) and new format (direct fields)
    extracted_data = []
    for f in findings:
        if "extracted_info" in f:
            extracted_data.append(f["extracted_info"])
        else:
            # New format: use direct fields
            extracted_data.append({
                "name": f.get("name", ""),
                "price": f.get("price", ""),
                "vendor": f.get("vendor", ""),
                "url": f.get("url", ""),
                "description": f.get("description", ""),
                "source_type": f.get("source_type", "general"),
                "source_reliability": f.get("source_reliability", 0.5)
            })

    # Build budget context for the prompt
    budget_context = ""
    if budget_intent:
        budget_tier = budget_intent.get("budget_tier", "any")
        max_budget = budget_intent.get("max_budget")
        user_specs = budget_intent.get("user_specified_specs", [])
        budget_words = budget_intent.get("budget_words_found", [])

        if budget_tier != "any" or max_budget:
            budget_lines = ["USER BUDGET CONSTRAINTS (from query parsing):"]
            if budget_tier == "budget":
                budget_lines.append(f"  - Budget intent: USER WANTS CHEAPEST/BUDGET OPTION")
            elif budget_tier == "premium":
                budget_lines.append(f"  - Budget intent: User wants premium/high-end")
            if max_budget:
                budget_lines.append(f"  - Maximum budget: ${max_budget}")
            if user_specs:
                budget_lines.append(f"  - User-specified specs (DO NOT FILTER): {user_specs}")
            if budget_words:
                budget_lines.append(f"  - Budget keywords found: {budget_words}")
            budget_context = "\n".join(budget_lines) + "\n\n"

    # Load prompt from recipe (apps/prompts/intelligence_synthesizer/core.md)
    # This follows the architectural pattern: prompts live in files, not code
    prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "intelligence_synthesizer" / "core.md"
    if prompt_path.exists():
        base_prompt = prompt_path.read_text()
    else:
        logger.warning(f"[Intelligence] Prompt file not found: {prompt_path}, using minimal fallback")
        base_prompt = "Extract structured intelligence from the research findings. Return JSON with: retailers, hard_requirements, nice_to_haves, price_range, recommended_brands, user_insights, confidence."

    # Build the full prompt with dynamic data injection
    prompt = f"""{base_prompt}

---

## Current Task

**QUERY:** {query}

{budget_context}**FINDINGS** (with source reliability - use for confidence weighting):
{chr(10).join(summaries_with_sources)}

**EXTRACTED DATA:**
{json.dumps(extracted_data[:3], indent=2)}

---

Return ONLY the JSON block from the "Structured Data" section. Do not include markdown formatting or explanation text."""

    from orchestrator.shared import call_llm_json

    llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
    llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    # Token budget from recipe (intelligence_synthesizer.yaml): output=1000
    # Timeout increased to 60s for complex synthesis tasks
    result = await call_llm_json(
        prompt=prompt,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        max_tokens=1000,  # From recipe token_budget.output
        timeout=60.0  # Increased from 30s for synthesis tasks
    )

    # Validate and provide defaults for required fields
    if not isinstance(result, dict):
        logger.warning(f"[Intelligence] LLM returned non-dict response: {type(result)}")
        result = {}

    # Ensure required fields exist with sensible defaults
    result.setdefault("retailers", {})
    result.setdefault("retailers_mentioned", [])
    result.setdefault("specs_discovered", {})
    result.setdefault("price_range", {})
    result.setdefault("hard_requirements", [])
    result.setdefault("nice_to_haves", [])
    result.setdefault("key_requirements", [])
    result.setdefault("user_explicit_requirements", [])
    result.setdefault("forum_recommendations", [])
    result.setdefault("recommended_brands", [])
    result.setdefault("user_insights", [])
    result.setdefault("confidence", 0.5)
    # New fields for LLM-integrated navigation
    result.setdefault("acceptable_alternatives", {})
    result.setdefault("deal_breakers", [])
    result.setdefault("relaxation_tiers", [])

    # Validate retailers dict structure and normalize names (remove underscores)
    if result["retailers"] and isinstance(result["retailers"], dict):
        normalized_retailers = {}
        for name, info in list(result["retailers"].items()):
            # CRITICAL: Remove underscores from retailer names - they break domain lookup
            # "example_petstore" → "example-petstore"
            normalized_name = name.replace("_", "").replace(" ", "").lower()
            if normalized_name != name:
                logger.debug(f"[Intelligence] Normalized retailer name: '{name}' → '{normalized_name}'")

            if not isinstance(info, dict):
                # Convert simple value to expected format
                normalized_retailers[normalized_name] = {
                    "mentioned_for": [],
                    "context": str(info) if info else "",
                    "relevance_score": 0.5,
                    "include_in_search": True
                }
            else:
                # Ensure required fields in each retailer entry
                info.setdefault("mentioned_for", [])
                info.setdefault("context", "")
                info.setdefault("relevance_score", 0.5)
                info.setdefault("include_in_search", True)
                normalized_retailers[normalized_name] = info

        result["retailers"] = normalized_retailers

    # Sync retailers_mentioned with retailers keys for backwards compatibility
    if result["retailers"] and not result["retailers_mentioned"]:
        result["retailers_mentioned"] = list(result["retailers"].keys())
    elif result["retailers_mentioned"]:
        # Also normalize retailers_mentioned list
        result["retailers_mentioned"] = [
            name.replace("_", "").replace(" ", "").lower()
            for name in result["retailers_mentioned"]
        ]

    # VALIDATION: Check for unrealistic price_range based on product category
    # If user said "cheapest" without explicit price AND the LLM still guessed a low max, clear it
    price_range = result.get("price_range", {})
    if isinstance(price_range, dict) and price_range.get("max"):
        max_price = price_range.get("max", 0)
        query_lower = query.lower()

        # Define minimum realistic prices for product categories
        category_minimums = {
            "laptop": 300,  # Basic laptop
            "nvidia": 600,  # Laptop with nvidia GPU
            "rtx 4060": 900,
            "rtx 4070": 1200,
            "rtx 4080": 1800,
            "rtx 4090": 2500,
            "gaming laptop": 700,
            "macbook": 900,
            "desktop": 400,
            "gaming desktop": 800,
        }

        # Find applicable minimum
        applicable_min = 0
        for keyword, min_price in category_minimums.items():
            if keyword in query_lower:
                applicable_min = max(applicable_min, min_price)

        # Check if budget intent was "cheapest" without explicit price
        budget_words = ["cheapest", "cheap", "budget", "affordable", "lowest price"]
        has_budget_word = any(word in query_lower for word in budget_words)
        has_explicit_price = bool(re.search(r'\$\d+|\d+\s*dollars?', query_lower))

        # If max price is below realistic minimum and user didn't specify explicit price, clear it
        if max_price < applicable_min and has_budget_word and not has_explicit_price:
            logger.warning(
                f"[Intelligence] Clearing unrealistic price_range: max ${max_price} < "
                f"realistic min ${applicable_min} for query '{query[:50]}...'"
            )
            result["price_range"] = {}  # Clear the hallucinated budget
        elif max_price < applicable_min:
            logger.info(
                f"[Intelligence] Note: price_range max ${max_price} is below "
                f"realistic min ${applicable_min} for this product category"
            )

    return result


async def _generate_targeted_queries(
    query: str,
    intelligence: Dict[str, Any],
    mode: str = "standard"
) -> List[str]:
    """
    Generate targeted Phase 2 queries using LLM planner.

    The LLM chooses strategy based on Phase 1 intelligence:
    1. vendor_direct: Search specific vendor (e.g., "query petco")
    2. criteria_targeted: Use key criteria (e.g., "syrian hamsters friendly docile for sale")
    3. generic_optimized: Clean query with commerce keywords (e.g., "syrian hamsters for sale")
    """
    from orchestrator.query_planner import plan_phase2_queries

    try:
        queries = await plan_phase2_queries(
            user_query=query,
            intelligence=intelligence,
            mode=mode,  # LLM decides query count based on mode
            solver_url=os.environ.get("SOLVER_URL", "http://127.0.0.1:8000"),
            solver_model_id=os.environ.get("SOLVER_MODEL_ID", "qwen3-coder"),
            solver_api_key=os.environ.get("SOLVER_API_KEY", "qwen-local")
        )
        logger.info(f"[Phase2] LLM-planned queries (mode={mode}): {queries}")
        return queries
    except Exception as e:
        logger.error(f"[Phase2] Query planning failed: {e}", exc_info=True)
        # Fallback: Use intelligence if available, otherwise generic
        if intelligence and intelligence.get("credible_sources"):
            fallback = [f"{query} {intelligence['credible_sources'][0]}"]
        else:
            fallback = [f"{query} for sale"]
        logger.warning(f"[Phase2] Using fallback queries: {fallback}")
        return fallback


async def _synthesize_deep_findings(
    query: str,
    research_goal: str,
    intelligence: Dict[str, Any],
    findings: List[Dict]
) -> Dict[str, Any]:
    """
    Synthesize deep research with both Phase 1 intelligence and Phase 2 findings.
    """
    import os

    # Build enriched context
    context = f"""Phase 1 Intelligence:
- Key topics: {', '.join(intelligence.get('key_topics', []))}
- Credible sources: {', '.join(intelligence.get('credible_sources', []))}
- Important criteria: {', '.join(intelligence.get('important_criteria', []))}

Phase 2 Findings: {len(findings)} sources"""

    # Use standard synthesis with enriched context
    synthesis = await _synthesize_findings(findings, query, research_goal)

    # Add intelligence context
    synthesis["phase1_intelligence"] = intelligence

    return synthesis


def _generate_summary(extracted_info: Dict[str, Any]) -> str:
    """
    Generate concise summary from extracted information.

    In production, this would use an LLM to create high-quality summaries.
    For now, we create simple bullet-point summaries from the extraction.
    """
    summary_parts = []

    # Add main points
    if "main_content" in extracted_info:
        content = extracted_info["main_content"]
        # Take first 200 chars as summary
        if isinstance(content, str):
            summary_parts.append(content[:200].strip())

    # Add product info if present
    if "products" in extracted_info and extracted_info["products"]:
        products = extracted_info["products"][:3]  # Top 3
        for product in products:
            if isinstance(product, dict):
                name = product.get("name", "")
                price = product.get("price", "")
                if name:
                    summary_parts.append(f"- {name}" + (f" ({price})" if price else ""))

    # Add vendor info if present
    if "vendor" in extracted_info:
        vendor = extracted_info["vendor"]
        if isinstance(vendor, dict):
            name = vendor.get("name", "")
            if name:
                summary_parts.append(f"Vendor: {name}")

    # Join all parts
    summary = "\n".join(summary_parts) if summary_parts else "No specific details extracted"

    # Limit to ~100 words (roughly 100 tokens)
    words = summary.split()
    if len(words) > 100:
        summary = " ".join(words[:100]) + "..."

    return summary


def _count_page_types(findings: List[Dict]) -> Dict[str, int]:
    """Count how many of each page type we found"""
    counts = {}
    for finding in findings:
        page_type = finding.get("page_type", "unknown")
        counts[page_type] = counts.get(page_type, 0) + 1
    return counts


def _detect_vendor_catalogs(findings: List[Dict]) -> List[Dict[str, Any]]:
    """
    Detect vendor catalog pages that could benefit from deep-crawling.

    A catalog page is identified by:
    - Multiple products/items from same domain
    - Pagination indicators (page=, /page/, next, more)
    - Category structure (/category/, /available/, /retired/)
    - Product listings page (vs individual product detail)

    Returns list of catalog hints:
    [
        {
            "vendor_url": "https://example-shop.com/available",
            "vendor_name": "Example Pet Shop",
            "detected_items": 5,
            "has_pagination": True,
            "categories": ["available", "upcoming"],
            "reason": "Multiple items with pagination detected"
        }
    ]
    """
    from urllib.parse import urlparse
    import re

    # Group findings by domain
    domain_groups = {}
    for finding in findings:
        url = finding.get("url", "")
        if not url:
            continue

        parsed = urlparse(url)
        domain = parsed.netloc

        if domain not in domain_groups:
            domain_groups[domain] = []
        domain_groups[domain].append(finding)

    # Analyze each domain for catalog patterns
    catalog_hints = []

    for domain, domain_findings in domain_groups.items():
        # Skip if only one finding from this domain
        if len(domain_findings) < 1:
            continue

        # Check each finding for catalog indicators
        for finding in domain_findings:
            url = finding.get("url", "")
            extracted = finding.get("extracted_info", {})
            html = finding.get("html", "")

            # Count products in this page
            products = extracted.get("products", []) if isinstance(extracted.get("products"), list) else []
            num_products = len(products)

            # Detect pagination indicators
            has_pagination = False
            pagination_indicators = [
                r'\bpage=\d+',  # ?page=2
                r'/page/\d+',  # /page/2/
                r'\bnext\b',   # "next" link
                r'\bmore\b',   # "load more"
                r'\bprev\b',   # "previous"
                r'pagination'   # pagination class
            ]
            for pattern in pagination_indicators:
                if re.search(pattern, url.lower()) or re.search(pattern, html.lower()):
                    has_pagination = True
                    break

            # Detect category structure
            categories = []
            category_patterns = [
                r'/available',
                r'/retired',
                r'/upcoming',
                r'/sold',
                r'/category/',
                r'/catalog',
                r'/inventory',
                r'/listings'
            ]
            for pattern in category_patterns:
                if re.search(pattern, url.lower()):
                    # Extract category name
                    match = re.search(r'/(available|retired|upcoming|sold|category|catalog|inventory|listings)', url.lower())
                    if match:
                        categories.append(match.group(1))

            # Determine if this looks like a catalog page
            is_catalog = False
            reason_parts = []

            if num_products >= 3:
                is_catalog = True
                reason_parts.append(f"{num_products} items")

            if has_pagination:
                is_catalog = True
                reason_parts.append("pagination detected")

            if categories:
                is_catalog = True
                reason_parts.append(f"categories: {', '.join(categories)}")

            # Only add if we detected catalog patterns
            if is_catalog:
                # Extract vendor name from domain or page title
                vendor_name = domain.replace("www.", "").replace(".com", "").replace(".org", "").title()
                if extracted.get("title"):
                    # Try to extract vendor name from title
                    title = extracted["title"]
                    # Remove common suffixes
                    for suffix in [" - Available", " - Hamsters", " | Available"]:
                        if suffix in title:
                            vendor_name = title.split(suffix)[0].strip()
                            break

                catalog_hints.append({
                    "vendor_url": url,
                    "vendor_name": vendor_name,
                    "detected_items": num_products,
                    "has_pagination": has_pagination,
                    "categories": categories if categories else ["all"],
                    "reason": " with ".join(reason_parts)
                })

    return catalog_hints


# ============================================================================
# Web Vision MCP Helper Functions
# ============================================================================

async def _web_vision_search(
    query: str,
    max_results: int = 10,
    session_id: str = "default",
    event_emitter: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """
    Perform search using Web Vision MCP (LLM-guided browser navigation).

    Routes to appropriate search provider based on SEARCH_PROVIDER config.

    Args:
        query: Search query
        max_results: Maximum results to extract
        session_id: Web Vision session ID
        event_emitter: Optional event emitter for progress updates

    Returns:
        List of search result candidates:
        [
            {"url": "...", "title": "...", "snippet": "..."},
            ...
        ]
    """
    if SEARCH_PROVIDER == "google":
        return await _web_vision_search_google(query, max_results, session_id, event_emitter)
    else:
        return await _web_vision_search_duckduckgo(query, max_results, session_id)


async def _web_vision_search_duckduckgo(
    query: str,
    max_results: int = 10,
    session_id: str = "default",
    zone_preference: List[str] = None
) -> List[Dict[str, Any]]:
    """
    Perform search using DuckDuckGo.

    Args:
        query: Search query
        max_results: Maximum results to extract
        session_id: Web Vision session ID
        zone_preference: Which zones to extract from. Options:
            - ["organic_results"] (default) - Real search result links
            - ["instant_answer"] - DDG's curated/AI content
            - ["organic_results", "instant_answer"] - Both

    Returns:
        List of search result candidates
    """
    from orchestrator import web_vision_mcp
    from orchestrator.content_sanitizer import ContentSanitizer

    # Default to organic results only (skip DDG curation)
    if zone_preference is None:
        zone_preference = ["organic_results", "list_content", "content_prose", "product_grid"]

    try:
        logger.info(f"[WebVisionSearch] Starting DuckDuckGo search for: {query} (session={session_id})")
        logger.info(f"[WebVisionSearch] Zone preference: {zone_preference}")

        # 1. Navigate to DuckDuckGo
        logger.info(f"[WebVisionSearch] Step 1: Navigating to DuckDuckGo...")
        nav_result = await web_vision_mcp.navigate(
            session_id=session_id,
            url="https://duckduckgo.com",
            wait_for="networkidle"
        )
        logger.info(f"[WebVisionSearch] Navigation result: {nav_result.get('success', False)}")

        # 2. Click search box
        logger.info(f"[WebVisionSearch] Step 2: Clicking search box...")
        click_result = await web_vision_mcp.click(
            session_id=session_id,
            goal="search box"
        )
        logger.info(f"[WebVisionSearch] Click result: {click_result.get('success', False)}")

        # 3. Type query
        logger.info(f"[WebVisionSearch] Step 3: Typing query: '{query}'...")
        type_result = await web_vision_mcp.type_text(
            session_id=session_id,
            text=query
        )
        logger.info(f"[WebVisionSearch] Type result: {type_result.get('success', False)}")

        # 4. Press Enter to search
        logger.info(f"[WebVisionSearch] Step 4: Pressing Enter...")
        key_result = await web_vision_mcp.press_key(
            session_id=session_id,
            key="Enter"
        )
        logger.info(f"[WebVisionSearch] Key press result: {key_result.get('success', False)}")

        # 5. Wait for results to load (wait for actual elements, not just time)
        logger.info(f"[WebVisionSearch] Step 5: Waiting for results to load...")
        import asyncio

        # Get the page object to wait for specific selectors
        page = await web_vision_mcp.get_page(session_id)
        if page:
            # DDG stable selectors - these are data-testid attributes that don't change
            DDG_RESULT_SELECTORS = [
                '[data-testid="result"]',           # Individual result items
                '[data-testid="mainline"] article', # Result articles in mainline
                'article[data-testid]',             # Any article with data-testid
                '.react-results--main article',     # React-rendered results
            ]

            results_loaded = False
            for selector in DDG_RESULT_SELECTORS:
                try:
                    await page.wait_for_selector(selector, timeout=8000)
                    logger.info(f"[WebVisionSearch] Results loaded (found: {selector})")
                    results_loaded = True
                    break
                except Exception:
                    continue

            if not results_loaded:
                # Fallback: wait a bit and hope for the best
                logger.warning(f"[WebVisionSearch] No result selectors found, using fallback wait")
                await asyncio.sleep(3)
        else:
            await asyncio.sleep(5)  # No page object, fallback to sleep

        # 6. Use PageIntelligence to identify zones and extract organic results
        logger.info(f"[WebVisionSearch] Step 6: Using PageIntelligence to identify search result zones...")

        from orchestrator.page_intelligence.service import PageIntelligenceService
        from bs4 import BeautifulSoup

        organic_text = ""

        if not page:
            logger.error("[WebVisionSearch] No page available for extraction")
            return []

        # Use PageIntelligence to understand the page structure
        pi_service = PageIntelligenceService()
        understanding = await pi_service.understand_page(
            page=page,
            extraction_goal="search_results"
        )

        logger.info(f"[WebVisionSearch] PageIntelligence identified zones: {[z.zone_type for z in understanding.zones]}")
        logger.info(f"[WebVisionSearch] Page type: {understanding.page_type}")

        # Find zones matching the caller's preference
        selected_zone = None
        for zone in understanding.zones:
            zone_type_value = zone.zone_type.value if hasattr(zone.zone_type, 'value') else str(zone.zone_type).lower()
            logger.info(f"[WebVisionSearch] Checking zone: {zone_type_value}")
            if zone_type_value in zone_preference:
                selected_zone = zone
                break

        if not selected_zone:
            logger.error(f"[WebVisionSearch] No matching zone found for preference: {zone_preference}")
            return []

        logger.info(f"[WebVisionSearch] Extracting from zone: {selected_zone.zone_type}")
        logger.info(f"[WebVisionSearch] Zone dom_anchors: {selected_zone.dom_anchors}")

        if not selected_zone.dom_anchors:
            logger.error(f"[WebVisionSearch] Zone has no dom_anchors")
            return []

        # Extract content from zone anchors
        # Use select() to get ALL matching elements (for selectors like [data-testid="result"])
        html_content = await page.content()
        soup = BeautifulSoup(html_content, 'html.parser')

        for anchor in selected_zone.dom_anchors:
            if anchor.startswith('.') or anchor.startswith('#') or anchor.startswith('['):
                # CSS selector - get ALL matching elements
                elems = soup.select(anchor)
                if elems:
                    for elem in elems[:20]:  # Limit to 20 results
                        text = elem.get_text(separator='\n', strip=True)
                        if text:
                            organic_text += text + '\n\n---\n\n'
                    logger.info(f"[WebVisionSearch] Extracted {len(organic_text)} chars from {len(elems)} elements using {anchor}")
                    break  # Found good selector, don't try others
            else:
                # Class or ID name
                elem = soup.find(class_=anchor) or soup.find(id=anchor)
                if elem:
                    organic_text += elem.get_text(separator='\n', strip=True) + '\n\n'

        if len(organic_text) < 100:
            logger.error(f"[WebVisionSearch] Extraction insufficient: {len(organic_text)} chars. Zone anchors may be wrong.")

        logger.info(f"[WebVisionSearch] Final organic content: {len(organic_text)} chars")

        # 7. Extract URLs and titles from organic results
        logger.info(f"[WebVisionSearch] Step 7: Extracting search results...")
        candidates = await _extract_search_results_from_content(
            content=organic_text,
            max_results=max_results
        )

        logger.info(f"[WebVisionSearch] ✓ Complete: Found {len(candidates)} candidates for query: {query}")
        return candidates

    except Exception as e:
        logger.error(f"[WebVisionSearch] ✗ Search failed: {e}", exc_info=True)
        return []


async def _web_vision_search_google(
    query: str,
    max_results: int = 10,
    session_id: str = "default",
    event_emitter: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """
    Perform autonomous Google search with SERP extraction.

    This implements the full Google search flow:
    1. Navigate to Google
    2. Handle consent dialog if present
    3. Type query and submit
    4. Extract results using LLM SERP parsing
    5. Click "Next" for pagination if needed
    6. Handle CAPTCHA/blockers with human intervention

    Args:
        query: Search query
        max_results: Maximum results to extract
        session_id: Web Vision session ID

    Returns:
        List of search result candidates:
        [
            {"url": "...", "title": "...", "snippet": "..."},
            ...
        ]
    """
    from orchestrator import web_vision_mcp
    from orchestrator.captcha_intervention import detect_blocker, request_intervention

    try:
        logger.info(f"[GoogleSearch] Starting autonomous Google search for: {query}")

        # 0. Apply rate limiting - wait if needed to avoid captcha
        rate_limiter = get_search_rate_limiter()
        await rate_limiter.acquire(query, "Google")
        logger.info(f"[GoogleSearch] Rate limiter cleared, proceeding with search")

        # 1. Navigate to Google
        logger.info("[GoogleSearch] Step 1: Navigating to Google...")
        await web_vision_mcp.navigate(
            session_id=session_id,
            url="https://www.google.com",
            wait_for="domcontentloaded"
        )

        # 2. Handle consent dialog if present (first-time visitors)
        logger.info("[GoogleSearch] Step 2: Handling consent dialog (if present)...")
        await _maybe_accept_google_consent(session_id)

        # 3. Type query and submit
        logger.info(f"[GoogleSearch] Step 3: Searching for '{query}'...")
        await _google_type_query(session_id, query)

        # Smart wait for results to load - wait for actual SERP elements
        await _wait_for_google_results(session_id)

        # 4. Collect SERP results (with pagination if needed)
        logger.info(f"[GoogleSearch] Step 4: Extracting up to {max_results} results...")
        results = []
        pages_visited = 0
        max_pages = 3  # Don't paginate beyond 3 pages

        while len(results) < max_results and pages_visited < max_pages:
            # Get page object first for URL check and blocker detection
            from orchestrator.web_vision_mcp import _get_or_create_page
            page = await _get_or_create_page(session_id)
            current_url = page.url
            logger.info(f"[GoogleSearch] >>> Current URL: {current_url}")

            # Check if browser restarted and we're no longer on Google
            # This can happen when page limit triggers deferred restart
            if current_url in ("about:blank", "chrome://newtab/", "") or "google.com" not in current_url:
                logger.warning(f"[GoogleSearch] Browser restart detected (URL: {current_url}), re-navigating to Google and re-searching...")
                await web_vision_mcp.navigate(
                    session_id=session_id,
                    url="https://www.google.com",
                    wait_for="domcontentloaded"
                )
                await _maybe_accept_google_consent(session_id)
                await _google_type_query(session_id, query)
                await _wait_for_google_results(session_id)
                page = await _get_or_create_page(session_id)
                current_url = page.url
                logger.info(f"[GoogleSearch] Re-navigation complete, now at: {current_url}")

            # Check for CAPTCHA or other blockers using RAW HTML (not markdown)
            # detect_blocker() looks for HTML patterns like class="g-recaptcha", "i'm not a robot"
            # These patterns are stripped out when converting to markdown
            logger.info(f"[GoogleSearch] >>> Checking for blockers (using raw HTML)...")
            raw_html = await page.content()
            logger.info(f"[GoogleSearch] >>> Raw HTML length: {len(raw_html)} chars")
            blocker = detect_blocker({
                "url": current_url,
                "content": raw_html,  # Use raw HTML for detection, not markdown
                "status": 200  # Playwright doesn't expose response status easily
            })

            if blocker:
                # Report rate limit to increase delays for future searches
                rate_limiter.report_rate_limit("Google")
                logger.info(f"[GoogleSearch] Reported rate limit to rate limiter - backoff increased")

                # PROOF OF EXECUTION - create a file
                import os
                with open("/tmp/blocker_detected.txt", "a") as f:
                    f.write(f"Blocker detected at {asyncio.get_event_loop().time()}\n")

                logger.info(f"[GoogleSearch] >>> Blocker found! Type: {blocker['type'].value}, Confidence: {blocker['confidence']:.0%}")
                logger.warning(
                    f"[GoogleSearch] Blocker detected: {blocker['type'].value} "
                    f"(confidence={blocker['confidence']:.0%})"
                )
                logger.info(f"[GoogleSearch] Indicators: {', '.join(blocker['indicators'])}")

                # Take screenshot for human reference
                import os
                screenshot_dir = "panda_system_docs/research_screenshots"
                os.makedirs(screenshot_dir, exist_ok=True)
                screenshot_filename = f"google_blocker_{session_id}_{int(asyncio.get_event_loop().time())}.png"
                screenshot_path = os.path.join(screenshot_dir, screenshot_filename)

                await page.screenshot(path=screenshot_path, full_page=False)
                logger.info(f"[GoogleSearch] Screenshot saved: {screenshot_path}")

                # Get noVNC URL for live browser access
                # The browser is running on DISPLAY=:99 which is accessible via noVNC on port 6080
                # Use vnc_lite.html which auto-connects (no connect button needed)
                novnc_url = "http://localhost:6080/vnc_lite.html?host=localhost&port=6080&scale=true"
                logger.info(f"[GoogleSearch] noVNC URL available: {novnc_url}")

                # Request human intervention
                intervention = await request_intervention(
                    blocker_type=blocker["type"],
                    url=current_url,
                    screenshot_path=screenshot_path,
                    session_id=session_id,
                    blocker_details=blocker,
                    cdp_url=novnc_url  # Pass noVNC URL in cdp_url field
                )

                # Emit intervention_needed event for WebSocket notification
                if event_emitter:
                    await event_emitter.emit_intervention_needed(
                        intervention_id=intervention.intervention_id,
                        url=current_url,
                        blocker_type=blocker["type"],
                        screenshot_path=screenshot_path,
                        cdp_url=intervention.cdp_url
                    )
                    logger.info(
                        f"[GoogleSearch] Emitted intervention_needed event "
                        f"(ID: {intervention.intervention_id})"
                    )

                logger.info(
                    f"[GoogleSearch] Waiting for human to resolve intervention "
                    f"(ID: {intervention.intervention_id}, timeout: 180s)"
                )

                # Wait for user to solve CAPTCHA (90 second timeout)
                logger.info(f"[GoogleSearch] >>> Starting wait_for_resolution (timeout=180s)...")
                success = await intervention.wait_for_resolution(timeout=180)
                logger.info(f"[GoogleSearch] >>> wait_for_resolution returned: {success}")

                if not success:
                    logger.error(
                        f"[GoogleSearch] Intervention timeout/skipped "
                        f"(ID: {intervention.intervention_id})"
                    )
                    return []  # Return empty results, research will try other sources

                # User solved it! Re-capture content
                logger.info(
                    f"[GoogleSearch] ✓ Intervention resolved successfully! "
                    f"(ID: {intervention.intervention_id})"
                )

                # Emit intervention_resolved event to clear UI message
                if event_emitter:
                    await event_emitter.emit_intervention_resolved(
                        intervention_id=intervention.intervention_id,
                        action="user_solved",
                        success=True
                    )

                # Get page state before waiting
                try:
                    current_url_before = page.url
                    logger.info(f"[GoogleSearch] >>> Current URL before wait: {current_url_before}")
                except Exception as e:
                    logger.warning(f"[GoogleSearch] >>> Could not get URL before wait: {e}")

                # Wait for results to load after CAPTCHA resolution
                logger.info("[GoogleSearch] >>> Waiting 5 seconds for results to load after CAPTCHA...")
                await asyncio.sleep(5)  # Give page time to fully load and avoid re-triggering blocker detection
                logger.info("[GoogleSearch] >>> 3-second wait complete")

                # Get page state after waiting
                try:
                    current_url_after = page.url
                    page_title = await page.title()
                    logger.info(f"[GoogleSearch] >>> Current URL after wait: {current_url_after}")
                    logger.info(f"[GoogleSearch] >>> Page title after wait: {page_title}")
                except Exception as e:
                    logger.warning(f"[GoogleSearch] >>> Could not get page state after wait: {e}")

                # Take a post-resolution screenshot to verify page state
                post_screenshot_path = f"panda_system_docs/research_screenshots/google_post_captcha_{session_id}_{int(asyncio.get_event_loop().time())}.png"
                try:
                    await page.screenshot(path=post_screenshot_path, full_page=False)
                    logger.info(f"[GoogleSearch] >>> Post-resolution screenshot saved: {post_screenshot_path}")
                except Exception as e:
                    logger.warning(f"[GoogleSearch] >>> Could not take post-resolution screenshot: {e}")

                # Capture page content
                logger.info("[GoogleSearch] >>> Calling capture_content...")
                content_result = await web_vision_mcp.capture_content(
                    session_id=session_id,
                    format="markdown"
                )

                # Log content details
                content_str = content_result.get("content", "")
                logger.info(f"[GoogleSearch] >>> Captured content length: {len(content_str)} chars")
                logger.info(f"[GoogleSearch] >>> Content preview (first 500 chars): {content_str[:500]}")
                logger.info(f"[GoogleSearch] >>> Content result keys: {list(content_result.keys())}")
            else:
                # No blocker detected - capture markdown content for extraction
                logger.info("[GoogleSearch] >>> No blocker detected, capturing markdown content...")
                content_result = await web_vision_mcp.capture_content(
                    session_id=session_id,
                    format="markdown"
                )
                content_str = content_result.get("content", "")
                logger.info(f"[GoogleSearch] >>> Markdown content: {len(content_str)} chars")
                logger.info(f"[GoogleSearch] >>> Content preview (first 500 chars): {content_str[:500]}")

            # Extract results from this page using DOM parsing with recalibration retry
            # This will try up to 3 times, recalibrating schema between attempts
            logger.info("[GoogleSearch] >>> Calling DOM extraction with recalibration retry...")
            page_results = await _extract_with_recalibration_retry(
                session_id=session_id,
                domain="google.com",
                page_type="search_results",
                extract_func=_extract_google_results_from_dom,
                max_retries=3,
                max_results=max_results - len(results)
            )

            logger.info(f"[GoogleSearch] >>> DOM extraction returned {len(page_results)} results")

            # Fallback: Screenshot+OCR extraction if DOM fails after all retry attempts
            if not page_results:
                logger.warning("[GoogleSearch] >>> DOM extraction failed after 3 recalibration attempts, trying screenshot+OCR fallback...")

                # Record final failure
                try:
                    health_tracker.record_extraction(
                        url="https://www.google.com/search",
                        page_type="search_results",
                        success=False,
                        method="schema_all_retries_failed"
                    )
                except Exception as e:
                    logger.warning(f"[GoogleSearch] Failed to record schema_all_retries_failed: {e}")

                page_results = await _extract_google_results_from_screenshot(
                    session_id=session_id,
                    max_results=max_results - len(results)
                )
                logger.info(f"[GoogleSearch] >>> Screenshot+OCR extraction returned {len(page_results)} results")

            # Fallback 2: LLM content extraction (last resort - validate against page URLs)
            if not page_results:
                logger.warning("[GoogleSearch] >>> Screenshot+OCR failed, falling back to LLM content extraction with URL validation...")
                # Get actual URLs from page for validation (anti-hallucination)
                try:
                    page_urls_for_validation = await page.evaluate('''() => {
                        return Array.from(document.querySelectorAll('a[href^="http"]'))
                            .map(a => a.href)
                            .filter(url => !url.includes('google.com/search'))
                            .slice(0, 50);
                    }''')
                except Exception as eval_err:
                    logger.warning(f"[GoogleSearch] >>> Could not get page URLs for validation: {eval_err}")
                    page_urls_for_validation = None

                page_results = await _extract_google_results_from_content(
                    content=content_result.get("content", ""),
                    max_results=max_results - len(results),
                    valid_urls=page_urls_for_validation
                )
                logger.info(f"[GoogleSearch] >>> LLM content extraction returned {len(page_results)} results")
            if page_results:
                logger.info(f"[GoogleSearch] >>> First result: {page_results[0]}")
            else:
                logger.warning("[GoogleSearch] >>> WARNING: Extraction returned ZERO results!")

            logger.info(f"[GoogleSearch] Page {pages_visited + 1}: Found {len(page_results)} results")

            for r in page_results:
                if len(results) >= max_results:
                    break
                # Deduplicate by URL
                if not any(existing["url"] == r["url"] for existing in results):
                    results.append(r)

            pages_visited += 1

            # Try to get more results if needed
            if len(results) < max_results and pages_visited < max_pages:
                logger.info(f"[GoogleSearch] Need more results, trying to click 'Next'...")
                if not await _click_google_next(session_id):
                    logger.info("[GoogleSearch] No 'Next' button found or click failed, stopping pagination")
                    break

                # Wait for next page to load
                await asyncio.sleep(4)  # Longer wait for pagination to avoid blocker detection

        logger.info(f"[GoogleSearch] ✓ Complete: Found {len(results)} results across {pages_visited} page(s)")

        # Report success to rate limiter - reduces backoff
        if results:
            rate_limiter.report_success()
            logger.info(f"[GoogleSearch] Reported success to rate limiter")

        return results

    except Exception as e:
        logger.error(f"[GoogleSearch] ✗ Search failed: {e}", exc_info=True)
        return []


async def _find_vendor_url_via_google(
    query: str,
    vendor_domain: str,
    session_id: str = "default",
    event_emitter: Optional[Any] = None
) -> Optional[str]:
    """
    Find the best vendor URL for a product query by searching Google.

    Instead of constructing a search URL (which may not work for all retailers),
    this searches Google for "{query} site:{vendor}" and returns the best
    matching URL from that vendor.

    This works better for retailers whose internal search is poor (e.g., Petco's
    search returns supplies instead of live animals).

    Natural delays are provided by browsing activity between searches
    (visit vendor → extract products → then search for next vendor).

    Args:
        query: Product search query (e.g., "Syrian hamster")
        vendor_domain: Vendor domain (e.g., "petco.com")
        session_id: Web Vision session ID
        event_emitter: Optional event emitter for notifications

    Returns:
        Best matching URL from the vendor, or None if not found
    """
    # Clean the vendor domain
    vendor_domain = vendor_domain.lower().replace("www.", "")

    # Extract topic from query (remove "for sale" if present - vendor queries don't need it)
    topic = query.replace(" for sale", "").replace("for sale ", "").strip()

    # Build search query: {vendor} {topic} {year}
    from datetime import datetime
    current_year = datetime.now().year
    search_query = f"{vendor_domain} {topic} {current_year}"

    logger.info(f"[VendorURLDiscovery] Searching ({SEARCH_PROVIDER}): '{search_query}'")

    # No artificial delay needed - natural browsing activity between searches
    # (visiting vendor pages, extracting products) provides human-like timing

    try:
        # Use search router (respects SEARCH_PROVIDER setting)
        results = await _web_vision_search(
            query=search_query,
            max_results=5,  # Only need a few results
            session_id=session_id,
            event_emitter=event_emitter
        )

        if not results:
            logger.warning(f"[VendorURLDiscovery] No results for '{search_query}'")
            return None

        # Find the first result from the vendor domain
        for result in results:
            url = result.get("url", "")
            title = result.get("title", "")

            # Check if URL is from the target vendor
            if vendor_domain in url.lower():
                logger.info(f"[VendorURLDiscovery] Found vendor URL: {url} ({title})")
                return url

        # If no exact domain match, check for www variant
        for result in results:
            url = result.get("url", "")
            title = result.get("title", "")

            if f"www.{vendor_domain}" in url.lower():
                logger.info(f"[VendorURLDiscovery] Found vendor URL (www): {url} ({title})")
                return url

        logger.warning(f"[VendorURLDiscovery] No results matched vendor domain {vendor_domain}")
        return None

    except Exception as e:
        logger.error(f"[VendorURLDiscovery] Failed to find URL via Google: {e}")
        return None


async def _maybe_accept_google_consent(session_id: str):
    """
    Handle Google consent dialog if present.

    First checks if a consent dialog exists via DOM, then clicks if found.
    This avoids unnecessary click attempts when no dialog is present.

    Args:
        session_id: Web Vision session ID
    """
    from orchestrator.web_vision_mcp import _get_or_create_page

    try:
        page = await _get_or_create_page(session_id)

        # First, check if consent dialog is present via DOM
        # Google consent dialogs typically have these characteristics
        consent_selectors = [
            "button:has-text('Accept all')",
            "button:has-text('Reject all')",
            "button:has-text('I agree')",
            "[aria-label='Accept all']",
            "[aria-label='Reject all']",
            "form[action*='consent'] button",
        ]

        consent_button = None
        for selector in consent_selectors:
            try:
                element = page.locator(selector).first
                if await element.count() > 0:
                    consent_button = element
                    logger.info(f"[GoogleConsent] Found consent button via: {selector}")
                    break
            except Exception:
                continue

        if not consent_button:
            logger.debug("[GoogleConsent] No consent dialog found (already accepted or not shown)")
            return

        # Click the consent button
        try:
            await consent_button.click(timeout=5000)
            logger.info("[GoogleConsent] Clicked consent button successfully")
            await asyncio.sleep(1)  # Wait for dialog to disappear
        except Exception as e:
            logger.warning(f"[GoogleConsent] Failed to click consent button: {e}")

    except Exception as e:
        logger.debug(f"[GoogleConsent] No consent handling needed: {e}")


async def _wait_for_google_results(session_id: str, timeout: float = 15.0):
    """
    Smart wait for Google search results to load.

    Waits for actual SERP elements to appear instead of arbitrary sleep.
    Tries multiple selectors to handle different Google layouts:
    - Organic results (div.g, div.MjjYud)
    - Shopping results (div.sh-dgr__content)
    - Knowledge panels
    - Featured snippets

    Args:
        session_id: Web Vision session ID
        timeout: Maximum wait time in seconds
    """
    from orchestrator.web_vision_mcp import _get_or_create_page

    # Selectors that indicate search results have loaded
    result_selectors = [
        'div.g',                     # Classic organic results
        'div.MjjYud',                # Modern organic wrapper
        'div[data-hveid]',           # Results with tracking ID
        'div.sh-dgr__content',       # Shopping results
        'div.commercial-unit-desktop-top',  # Shopping carousel
        'div[data-attrid]',          # Knowledge panel
        'div.xpdopen',               # Featured snippet
        'h3.LC20lb',                 # Result titles
        'div.yuRUbf',                # Result URL container
        '#search',                   # Main search container
    ]

    try:
        page = await _get_or_create_page(session_id)
        if not page:
            logger.warning("[GoogleWait] No page found, falling back to sleep")
            await asyncio.sleep(5)
            return

        logger.info("[GoogleWait] Waiting for search results to load...")

        # Wait for URL to change to search results page first
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            if '/search?' in page.url or 'q=' in page.url:
                break
            await asyncio.sleep(0.3)

        # Now wait for actual result elements
        for selector in result_selectors:
            try:
                # Try to wait for this selector with short timeout
                await page.wait_for_selector(selector, timeout=3000)
                logger.info(f"[GoogleWait] ✓ Results loaded (found '{selector}')")

                # Extra wait for dynamic content to finish rendering
                await asyncio.sleep(1.5)
                return

            except Exception:
                continue  # Try next selector

        # If no selector worked, check if we have any h3 elements (universal)
        try:
            h3_count = await page.evaluate('document.querySelectorAll("h3").length')
            if h3_count >= 3:
                logger.info(f"[GoogleWait] ✓ Results loaded (found {h3_count} h3 elements)")
                await asyncio.sleep(1.5)
                return
        except Exception as e:
            logger.debug(f"[GoogleWait] h3 count check failed: {e}")

        # Fallback: just wait a bit longer
        logger.warning("[GoogleWait] No result selectors found, using fallback wait")
        elapsed = asyncio.get_event_loop().time() - start_time
        remaining = max(0, timeout - elapsed)
        if remaining > 0:
            await asyncio.sleep(min(remaining, 5))

    except Exception as e:
        logger.warning(f"[GoogleWait] Smart wait failed: {e}, using fallback")
        await asyncio.sleep(5)


async def _google_type_query(session_id: str, query: str):
    """
    Type query into Google search box and submit.

    Args:
        session_id: Web Vision session ID
        query: Search query to type
    """
    from orchestrator import web_vision_mcp
    from orchestrator.human_behavior_simulator import HumanBehaviorSimulator

    try:
        # Get page for human behavior simulation
        from orchestrator.web_vision_mcp import _get_or_create_page
        page = await _get_or_create_page(session_id)

        # Use human behavior simulator for realistic typing
        simulator = HumanBehaviorSimulator(page, seed=session_id)

        # Find and click search box (Google uses textarea)
        search_box = await page.query_selector('textarea[name="q"]')
        if not search_box:
            search_box = await page.query_selector('input[name="q"]')

        if search_box:
            # Click with human-like behavior
            await simulator.click_like_human(search_box, move_mouse=True, pause_before_click_ms=150)

            # Type with human-like behavior
            await simulator.type_like_human(
                text=query,
                min_delay_ms=60,
                max_delay_ms=180,
                mistake_probability=0.01  # 1% chance of typo
            )

            # Pause before submitting (humans don't immediately press Enter)
            await simulator.random_pause(0.3, 0.8, reason="reviewing query")

            # Press Enter
            await page.keyboard.press("Enter")

            logger.info(f"[GoogleQuery] Typed and submitted query: '{query}'")
        else:
            logger.warning("[GoogleQuery] Could not find search box, using fallback method")
            # Fallback: use web_vision_mcp click/type
            await web_vision_mcp.click(session_id=session_id, goal="search box")
            await web_vision_mcp.type_text(session_id=session_id, text=query)
            await web_vision_mcp.press_key(session_id=session_id, key="Enter")

    except Exception as e:
        logger.error(f"[GoogleQuery] Query typing failed: {e}", exc_info=True)
        # Fallback to basic method
        await web_vision_mcp.type_text(session_id=session_id, text=query)
        await web_vision_mcp.press_key(session_id=session_id, key="Enter")


# Cache the last working selector to avoid re-testing
_last_working_google_selector = None


async def _extract_with_recalibration_retry(
    session_id: str,
    domain: str,
    page_type: str,
    extract_func,
    max_retries: int = 3,
    **extract_kwargs
) -> List[Dict[str, Any]]:
    """
    Wrapper that retries extraction with immediate recalibration on failure.

    Instead of waiting for 3 failures across sessions, this immediately
    recalibrates and retries when extraction returns 0 results.

    Args:
        session_id: Browser session ID
        domain: Domain for schema lookup (e.g., "google.com")
        page_type: Page type for schema (e.g., "search_results")
        extract_func: Async extraction function to call
        max_retries: Max recalibration attempts before giving up
        **extract_kwargs: Arguments to pass to extract_func

    Returns:
        Extraction results, or empty list if all retries fail
    """
    from orchestrator.shared_state.site_schema_registry import get_schema_registry
    from orchestrator.site_calibrator import get_calibrator
    from orchestrator.web_vision_mcp import _get_or_create_page

    schema_registry = get_schema_registry()

    for attempt in range(max_retries):
        # Try extraction
        results = await extract_func(session_id=session_id, **extract_kwargs)

        if results:
            # Success! Record it and return
            logger.info(f"[RecalibrationRetry] Extraction succeeded on attempt {attempt + 1}")
            return results

        # Extraction failed - try recalibration
        if attempt < max_retries - 1:  # Don't recalibrate on last attempt
            logger.warning(
                f"[RecalibrationRetry] Attempt {attempt + 1}/{max_retries} failed for {domain}/{page_type}, "
                f"triggering immediate recalibration..."
            )

            try:
                # Mark schema as needing recalibration
                schema_registry.mark_stale(domain, page_type)
                logger.info(f"[RecalibrationRetry] Marked {domain}/{page_type} schema as stale")

                # Get page and run calibration
                page = await _get_or_create_page(session_id)
                if page:
                    calibrator = get_calibrator()
                    url = page.url

                    # Force recalibration
                    new_schema = await calibrator.calibrate(
                        page=page,
                        url=url,
                        page_type=page_type,
                        force=True
                    )

                    if new_schema and new_schema.product_card_selector:
                        logger.info(
                            f"[RecalibrationRetry] ✓ New schema built: "
                            f"selector='{new_schema.product_card_selector}'"
                        )
                    else:
                        logger.warning(f"[RecalibrationRetry] Calibration returned no valid selectors")

            except Exception as cal_err:
                logger.error(f"[RecalibrationRetry] Recalibration failed: {cal_err}")

        else:
            logger.warning(
                f"[RecalibrationRetry] All {max_retries} attempts failed for {domain}/{page_type}"
            )

    return []


async def _extract_google_results_from_dom(
    session_id: str,
    max_results: int = 10
) -> List[Dict[str, Any]]:
    """
    Extract search results from Google SERP using DOM parsing (NOT LLM).

    This bypasses LLM hallucination by extracting actual URLs from <a> tags.
    Uses Playwright DOM queries to get real href attributes.

    Args:
        session_id: Web Vision session ID (must have Google results loaded)
        max_results: Maximum results to extract

    Returns:
        List of result dicts: [{"url": "...", "title": "...", "snippet": "..."}, ...]
    """
    from orchestrator.web_vision_mcp import _get_or_create_page
    global _last_working_google_selector

    # Schema registry for persistent selector learning
    schema_registry = get_schema_registry()
    health_tracker = get_health_tracker()

    try:
        # Get Playwright page object
        page = await _get_or_create_page(session_id)
        if not page:
            logger.warning(f"[ExtractGoogleDOM] No page found for session: {session_id}")
            return []

        # ═══════════════════════════════════════════════════════════════
        # TIER 0: Unified Web Extractor
        # Single system that works for any webpage including search results
        # ═══════════════════════════════════════════════════════════════
        try:
            from orchestrator.unified_web_extractor import get_unified_extractor, SiteType
            unified = get_unified_extractor()
            current_url = page.url

            unified_results = await unified.extract(page, current_url, max_items=max_results, site_type=SiteType.SEARCH)

            if unified_results and len(unified_results) >= 3:
                logger.info(f"[ExtractGoogleDOM] Unified extractor found {len(unified_results)} results")
                return [
                    {
                        "url": r.url,
                        "title": r.title,
                        "snippet": r.snippet or "",
                        "_url_source": "unified"
                    }
                    for r in unified_results[:max_results]
                ]
        except Exception as ue:
            logger.warning(f"[ExtractGoogleDOM] Unified extractor error: {ue}, falling back to legacy")

        # ═══════════════════════════════════════════════════════════════
        # LEGACY: Universal JS extraction (inside-out approach)
        # Fallback if unified extractor fails
        # ═══════════════════════════════════════════════════════════════
        logger.info(f"[ExtractGoogleDOM] Using legacy JS extraction (h3 → anchor approach)...")

        try:
            result_data = await page.evaluate('''() => {
                const results = [];
                const seen = new Set();

                // Find all h3 elements (these are result titles)
                const h3s = document.querySelectorAll('h3');

                for (const h3 of h3s) {
                    // Walk UP to find the anchor tag
                    let anchor = h3.closest('a');
                    if (!anchor) {
                        // Try parent's anchor
                        anchor = h3.parentElement?.closest('a');
                    }
                    if (!anchor) {
                        // Try sibling or nearby anchor
                        const parent = h3.parentElement;
                        if (parent) {
                            anchor = parent.querySelector('a[href]');
                        }
                    }

                    if (!anchor || !anchor.href) continue;

                    const url = anchor.href;

                    // Skip internal Google URLs and duplicates
                    if (seen.has(url)) continue;
                    if (url.includes('google.com/search') ||
                        url.includes('google.com/url') ||
                        url.includes('accounts.google') ||
                        url.includes('support.google') ||
                        url.startsWith('javascript:')) {
                        continue;
                    }

                    seen.add(url);

                    // Get title
                    const title = h3.innerText || h3.textContent || '';

                    // Try to get snippet from nearby elements
                    let snippet = '';
                    const resultContainer = h3.closest('[data-hveid]') ||
                                          h3.closest('.g') ||
                                          h3.closest('[data-sokoban-container]') ||
                                          h3.parentElement?.parentElement?.parentElement;

                    if (resultContainer) {
                        // Look for snippet in common containers
                        const snippetEl = resultContainer.querySelector('.VwiC3b') ||
                                        resultContainer.querySelector('[data-sncf]') ||
                                        resultContainer.querySelector('.IsZvec') ||
                                        resultContainer.querySelector('span.aCOpRe');
                        if (snippetEl) {
                            snippet = snippetEl.innerText || '';
                        }
                    }

                    results.push({
                        url: url,
                        title: title.trim(),
                        snippet: snippet.substring(0, 300).trim()
                    });

                    if (results.length >= 15) break;
                }

                return results;
            }''')

            if result_data and len(result_data) >= 3:
                logger.info(f"[ExtractGoogleDOM] JS extraction found {len(result_data)} results")
                results = [
                    {
                        "url": r["url"],
                        "title": r["title"],
                        "snippet": r.get("snippet", ""),
                        "position": i + 1,
                        "_url_source": "dom_js_primary"
                    }
                    for i, r in enumerate(result_data)
                    if r.get("url") and r.get("title")
                ]

                if results:
                    logger.info(f"[ExtractGoogleDOM] Returning {len(results)} results from JS extraction")
                    return results[:max_results]

        except Exception as js_err:
            logger.warning(f"[ExtractGoogleDOM] JS extraction failed: {js_err}")

        # ═══════════════════════════════════════════════════════════════
        # FALLBACK: CSS selector approach (only if JS didn't work)
        # ═══════════════════════════════════════════════════════════════
        logger.info(f"[ExtractGoogleDOM] JS extraction insufficient, trying CSS selectors...")

        # Selectors to try (ordered by likelihood - updated Nov 2025)
        selectors_to_try = [
            'div.g',                     # Classic organic results
            'div.MjjYud',                # Modern organic results wrapper
            'div.N54PNb',                # 2024+ result container
            'div.yuRUbf',                # Title/link container (inner)
            'div.tF2Cxc',                # Another common wrapper
            'div.Gx5Zad',                # Result item (mobile/some layouts)
        ]

        result_elements = []
        working_selector = None

        for selector in selectors_to_try:
            elements = await page.query_selector_all(selector)
            # Only use if we get a reasonable number (not too many, not too few)
            if 3 <= len(elements) <= 50:
                logger.info(f"[ExtractGoogleDOM] Selector '{selector}' found {len(elements)} elements")
                result_elements = elements
                working_selector = selector
                break
            else:
                logger.debug(f"[ExtractGoogleDOM] Selector '{selector}' found {len(elements)} elements (outside 3-50 range)")

        if not working_selector:
            logger.warning(f"[ExtractGoogleDOM] No working selector found, trying universal link+h3 pattern")
            # Last resort: Find all anchors that have h3 children (universal Google pattern)
            try:
                # JavaScript to find all result-like structures
                result_data = await page.evaluate('''() => {
                    const results = [];
                    // Find all h3 elements (result titles)
                    const h3s = document.querySelectorAll('h3');
                    for (const h3 of h3s) {
                        // Find parent anchor or sibling anchor
                        let anchor = h3.closest('a');
                        if (!anchor) {
                            anchor = h3.parentElement?.querySelector('a');
                        }
                        if (!anchor) {
                            anchor = h3.parentElement?.parentElement?.querySelector('a');
                        }
                        if (anchor && anchor.href && anchor.href.startsWith('http') && !anchor.href.includes('google.com/search')) {
                            // Find snippet nearby
                            let snippet = '';
                            const parent = h3.closest('div');
                            if (parent) {
                                const snippetEl = parent.querySelector('div[data-sncf], .VwiC3b, .IsZvec, span.aCOpRe');
                                if (snippetEl) snippet = snippetEl.innerText || '';
                            }
                            results.push({
                                url: anchor.href,
                                title: h3.innerText || '',
                                snippet: snippet.substring(0, 300)
                            });
                        }
                    }
                    // Deduplicate by URL
                    const seen = new Set();
                    return results.filter(r => {
                        if (seen.has(r.url)) return false;
                        seen.add(r.url);
                        return true;
                    }).slice(0, 15);
                }''')

                if result_data and len(result_data) > 0:
                    logger.info(f"[ExtractGoogleDOM] Universal pattern found {len(result_data)} results via JS evaluation")
                    return [
                        {
                            "url": r["url"],
                            "title": r["title"],
                            "snippet": r.get("snippet", ""),
                            "position": i + 1,
                            "_url_source": "dom_js"
                        }
                        for i, r in enumerate(result_data)
                        if r.get("url") and r.get("title")
                    ]
            except Exception as js_err:
                logger.warning(f"[ExtractGoogleDOM] JS evaluation failed: {js_err}")

            logger.warning(f"[ExtractGoogleDOM] All DOM extraction methods failed")
            return []

        logger.info(f"[ExtractGoogleDOM] Using selector '{working_selector}' with {len(result_elements)} result elements")

        results = []
        for i, elem in enumerate(result_elements[:max_results]):
            try:
                # Try different extraction patterns based on Google SERP structure
                url = None
                title = None
                snippet = None

                # Pattern 1: Classic organic result (div.g)
                if working_selector == 'div.g':
                    link_elem = await elem.query_selector('a')
                    url = await link_elem.get_attribute("href") if link_elem else ""
                    title_elem = await elem.query_selector('h3')
                    title = await title_elem.inner_text() if title_elem else ""
                    snippet_elem = await elem.query_selector('div[data-sncf]')
                    if not snippet_elem:
                        snippet_elem = await elem.query_selector('div.VwiC3b')
                    snippet = await snippet_elem.inner_text() if snippet_elem else ""

                # Pattern 2: Modern organic result (div.MjjYud)
                elif working_selector == 'div.MjjYud':
                    link_elem = await elem.query_selector('a')
                    url = await link_elem.get_attribute("href") if link_elem else ""
                    title_elem = await elem.query_selector('h3')
                    title = await title_elem.inner_text() if title_elem else ""
                    snippet_elem = await elem.query_selector('div.VwiC3b')
                    if not snippet_elem:
                        snippet_elem = await elem.query_selector('span')
                    snippet = await snippet_elem.inner_text() if snippet_elem else ""

                # Pattern 3: Title/link container (div.yuRUbf) - need to traverse up for snippet
                elif working_selector == 'div.yuRUbf':
                    link_elem = await elem.query_selector('a')
                    url = await link_elem.get_attribute("href") if link_elem else ""
                    title_elem = await elem.query_selector('h3')
                    title = await title_elem.inner_text() if title_elem else ""
                    # Snippet is in sibling element - safely traverse to parent
                    try:
                        parent = await elem.evaluate_handle('el => el.parentElement || el')
                        if parent:
                            snippet_elem = await parent.query_selector('div.VwiC3b')
                            snippet = await snippet_elem.inner_text() if snippet_elem else ""
                        else:
                            snippet = ""
                    except Exception as e:
                        logger.debug(f"[ExtractGoogleDOM] Failed to extract snippet from parent: {e}")
                        snippet = ""

                # Generic fallback - try multiple patterns
                else:
                    # Try to find link with h3 (most reliable pattern)
                    link_elem = await elem.query_selector('a[href^="http"]')
                    if not link_elem:
                        link_elem = await elem.query_selector('a')
                    url = await link_elem.get_attribute("href") if link_elem else ""

                    # Try multiple title selectors
                    title_elem = await elem.query_selector('h3')
                    if not title_elem:
                        title_elem = await elem.query_selector('h3.LC20lb')
                    if not title_elem:
                        title_elem = await elem.query_selector('[role="heading"]')
                    title = await title_elem.inner_text() if title_elem else ""

                    # Try multiple snippet selectors
                    snippet_elem = await elem.query_selector('div.VwiC3b')
                    if not snippet_elem:
                        snippet_elem = await elem.query_selector('span.aCOpRe')
                    if not snippet_elem:
                        snippet_elem = await elem.query_selector('div[data-sncf]')
                    if not snippet_elem:
                        snippet_elem = await elem.query_selector('.IsZvec')
                    snippet = await snippet_elem.inner_text() if snippet_elem else ""

                # Clean up extracted data
                title = title.strip() if title else ""
                snippet = snippet.strip() if snippet else ""

                # Validate and add result
                if url and title and url.startswith("http"):
                    # Additional validation: skip Google internal URLs (but allow cache/translate)
                    if "google.com" in url:
                        # Skip internal Google pages, but allow useful services
                        if any(x in url for x in ["/search?", "/url?", "accounts.google", "support.google"]):
                            logger.debug(f"[ExtractGoogleDOM] Skipping Google internal URL: {url[:60]}")
                            continue
                        # Allow Google cache, translate, and other useful services

                    results.append({
                        "url": url,
                        "title": title,
                        "snippet": snippet,
                        "position": i + 1,
                        "_url_source": "dom"  # Mark as DOM-extracted (not hallucinated)
                    })
                    logger.info(f"[ExtractGoogleDOM]   {i+1}. {title[:60]}... ({url[:60]}...)")
            except Exception as e:
                logger.warning(f"[ExtractGoogleDOM] Error extracting result {i+1}: {e}")
                continue

        logger.info(f"[ExtractGoogleDOM] Successfully extracted {len(results)} results from DOM")

        # FALLBACK: If selector matched elements but extracted 0 results, try universal JS pattern
        if not results and result_elements and len(result_elements) > 0:
            logger.warning(f"[ExtractGoogleDOM] Selector '{working_selector}' found {len(result_elements)} elements but extracted 0 results - trying JS fallback")
            try:
                result_data = await page.evaluate('''() => {
                    const results = [];
                    const h3s = document.querySelectorAll('h3');
                    for (const h3 of h3s) {
                        let anchor = h3.closest('a');
                        if (!anchor) {
                            anchor = h3.parentElement?.querySelector('a');
                        }
                        if (!anchor) {
                            anchor = h3.parentElement?.parentElement?.querySelector('a');
                        }
                        if (anchor && anchor.href && anchor.href.startsWith('http') && !anchor.href.includes('google.com/search')) {
                            let snippet = '';
                            const parent = h3.closest('div');
                            if (parent) {
                                const snippetEl = parent.querySelector('div[data-sncf], .VwiC3b, .IsZvec, span.aCOpRe');
                                if (snippetEl) snippet = snippetEl.innerText || '';
                            }
                            results.push({
                                url: anchor.href,
                                title: h3.innerText || '',
                                snippet: snippet.substring(0, 300)
                            });
                        }
                    }
                    const seen = new Set();
                    return results.filter(r => {
                        if (seen.has(r.url)) return false;
                        seen.add(r.url);
                        return true;
                    }).slice(0, 15);
                }''')

                if result_data and len(result_data) > 0:
                    logger.info(f"[ExtractGoogleDOM] JS fallback found {len(result_data)} results")
                    results = [
                        {
                            "url": r["url"],
                            "title": r["title"],
                            "snippet": r.get("snippet", ""),
                            "position": i + 1,
                            "_url_source": "dom_js_fallback"
                        }
                        for i, r in enumerate(result_data)
                        if r.get("url") and r.get("title")
                    ]
            except Exception as js_err:
                logger.warning(f"[ExtractGoogleDOM] JS fallback failed: {js_err}")

        # Update schema registry with working selector (if new or different)
        # IMPORTANT: Only save if selector actually extracted results, NOT if JS fallback was used
        results_from_dom = results and results[0].get("_url_source") == "dom"
        if results_from_dom and working_selector:
            try:
                existing_schema = schema_registry.get("google.com", "search_results")
                if not existing_schema or existing_schema.product_card_selector != working_selector:
                    # Create or update schema with working selector
                    new_schema = SiteSchema(
                        domain="google.com",
                        page_type="search_results",
                        product_card_selector=working_selector,
                        title_selector="h3",
                        product_link_selector="a",
                        version=existing_schema.version + 1 if existing_schema else 1
                    )
                    schema_registry.save(new_schema)
                    logger.info(f"[ExtractGoogleDOM] Saved working selector '{working_selector}' to schema registry")

                # Record success
                health_tracker.record_extraction(
                    url="https://www.google.com/search",
                    page_type="search_results",
                    success=True,
                    method="dom_schema" if schema and schema.product_card_selector == working_selector else "dom_discovery"
                )
            except Exception as schema_err:
                logger.warning(f"[ExtractGoogleDOM] Failed to update schema: {schema_err}")
        elif results and not results_from_dom:
            # JS fallback was used - don't save the broken selector
            logger.info(f"[ExtractGoogleDOM] JS fallback used - NOT saving selector '{working_selector}' (it failed extraction)")

        return results

    except Exception as e:
        logger.error(f"[ExtractGoogleDOM] DOM extraction failed: {e}")
        # Record failure
        try:
            health_tracker.record_extraction(
                url="https://www.google.com/search",
                page_type="search_results",
                success=False,
                method="dom"
            )
        except Exception as e:
            logger.warning(f"[ExtractGoogleDOM] Failed to record dom extraction failure: {e}")
        return []


async def _extract_google_results_from_screenshot(
    session_id: str,
    max_results: int = 10
) -> List[Dict[str, Any]]:
    """
    Extract search results from Google SERP using screenshot + OCR.

    This is the reliable fallback when DOM extraction fails.
    Takes a screenshot, runs OCR, and uses LLM to structure the results.

    Args:
        session_id: Web Vision session ID (must have Google results loaded)
        max_results: Maximum results to extract

    Returns:
        List of result dicts: [{"url": "...", "title": "...", "snippet": "..."}, ...]
    """
    import httpx
    import tempfile
    import re

    logger.info(f"[ExtractGoogleOCR] Starting screenshot+OCR extraction...")

    try:
        # Get page object
        from orchestrator.web_vision_mcp import _get_or_create_page
        page = await _get_or_create_page(session_id)
        if not page:
            logger.warning(f"[ExtractGoogleOCR] No page found for session: {session_id}")
            return []

        # Take screenshot (full_page=True to capture all results, not just viewport)
        screenshot_bytes = await page.screenshot(full_page=True)
        logger.info(f"[ExtractGoogleOCR] Screenshot captured: {len(screenshot_bytes)} bytes")

        # Save to temp file for OCR
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(screenshot_bytes)
            screenshot_path = f.name

        # Run OCR using EasyOCR
        try:
            import easyocr
            reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            ocr_results = reader.readtext(screenshot_path)
            logger.info(f"[ExtractGoogleOCR] OCR found {len(ocr_results)} text regions")
        except ImportError:
            logger.warning("[ExtractGoogleOCR] EasyOCR not available, trying alternative...")
            # Fallback: extract URLs from raw page content
            content = await page.content()
            urls = re.findall(r'href="(https?://[^"]+)"', content)
            titles = re.findall(r'<h3[^>]*>([^<]+)</h3>', content)

            results = []
            for i, (url, title) in enumerate(zip(urls[:max_results], titles[:max_results])):
                if 'google.com' not in url:
                    results.append({
                        "url": url,
                        "title": title,
                        "snippet": "",
                        "position": i + 1,
                        "_url_source": "regex_fallback"
                    })
            logger.info(f"[ExtractGoogleOCR] Regex fallback found {len(results)} results")
            return results

        # Extract text from OCR results, preserving bounding boxes for DOM mapping
        ocr_text_lines = []
        ocr_items = []  # Preserved with bounding boxes
        for (bbox, text, confidence) in ocr_results:
            if confidence > 0.5:
                ocr_text_lines.append(text)
                # Preserve bounding box for OCR-DOM mapping
                ocr_items.append({
                    "text": text,
                    "x": min(p[0] for p in bbox),
                    "y": min(p[1] for p in bbox),
                    "width": max(p[0] for p in bbox) - min(p[0] for p in bbox),
                    "height": max(p[1] for p in bbox) - min(p[1] for p in bbox),
                    "confidence": confidence
                })

        ocr_text = "\n".join(ocr_text_lines)
        logger.info(f"[ExtractGoogleOCR] OCR text length: {len(ocr_text)} chars")

        # Also get any URLs from the page (for validation)
        page_urls = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a[href^="http"]'))
                .map(a => a.href)
                .filter(url => !url.includes('google.com/search'))
                .slice(0, 50);
        }''')
        logger.info(f"[ExtractGoogleOCR] Found {len(page_urls)} URLs in page for validation")

        # Skip LLM call if there's no content to analyze (e.g., about:blank page)
        if not ocr_text.strip() and not page_urls:
            logger.warning(f"[ExtractGoogleOCR] No OCR text and no URLs found, skipping LLM (likely blank page)")
            return []

        # Use LLM to structure the OCR output into search results
        model_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        model_id = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

        # Load prompt from recipe file
        prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "research" / "ocr_serp_analyzer.md"
        if prompt_path.exists():
            base_prompt = prompt_path.read_text()
        else:
            logger.warning(f"[ExtractGoogleOCR] Prompt file not found: {prompt_path}")
            base_prompt = "Analyze OCR text from Google search results and match with URLs. Return JSON array."

        prompt = f"""{base_prompt}

---

## Current Task

OCR TEXT FROM SCREENSHOT:
{ocr_text[:6000]}

ACTUAL URLs FOUND IN PAGE (use these for URL field):
{chr(10).join(page_urls[:20])}

Maximum results to extract: {max_results}

JSON OUTPUT:"""

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                model_url,
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2000
                },
                headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            result = response.json()

        llm_output = result["choices"][0]["message"]["content"].strip()
        logger.info(f"[ExtractGoogleOCR] LLM response length: {len(llm_output)} chars")

        # Parse JSON
        if "```json" in llm_output:
            llm_output = llm_output.split("```json")[1].split("```")[0].strip()
        elif "```" in llm_output:
            llm_output = llm_output.split("```")[1].split("```")[0].strip()

        import json
        try:
            results_raw = json.loads(llm_output)
        except json.JSONDecodeError as e:
            logger.warning(f"[ExtractGoogleOCR] JSON parse failed: {e}")
            return []

        # Validate results - only keep URLs that were in the page
        page_urls_set = set(page_urls)
        validated_results = []
        for i, r in enumerate(results_raw):
            url = r.get("url", "")
            title = r.get("title", "")

            # Check if URL was actually in the page
            if url in page_urls_set or any(url in pu or pu in url for pu in page_urls):
                validated_results.append({
                    "url": url,
                    "title": title,
                    "snippet": r.get("snippet", ""),
                    "position": i + 1,
                    "_url_source": "ocr_validated"
                })
            else:
                logger.debug(f"[ExtractGoogleOCR] Rejected URL not in page: {url[:60]}")

        logger.info(f"[ExtractGoogleOCR] Validated {len(validated_results)}/{len(results_raw)} results")

        # Clean up temp file
        import os as os_module
        try:
            os_module.unlink(screenshot_path)
        except Exception as e:
            logger.debug(f"[ExtractGoogleOCR] Failed to clean up temp file {screenshot_path}: {e}")

        # Track OCR extraction success
        if validated_results:
            try:
                health_tracker = get_health_tracker()
                health_tracker.record_extraction(
                    url="https://www.google.com/search",
                    page_type="search_results",
                    success=True,
                    method="ocr"
                )
            except Exception as track_err:
                logger.debug(f"[ExtractGoogleOCR] Health tracking failed: {track_err}")

        return validated_results

    except Exception as e:
        logger.error(f"[ExtractGoogleOCR] Screenshot+OCR extraction failed: {e}", exc_info=True)
        # Track OCR failure
        try:
            health_tracker = get_health_tracker()
            health_tracker.record_extraction(
                url="https://www.google.com/search",
                page_type="search_results",
                success=False,
                method="ocr"
            )
        except Exception as track_err:
            logger.warning(f"[ExtractGoogleOCR] Failed to record OCR extraction failure: {track_err}")
        return []


async def _extract_google_results_from_content(
    content: str,
    max_results: int = 10,
    valid_urls: List[str] = None
) -> List[Dict[str, Any]]:
    """
    Extract search results from Google SERP using LLM.

    Uses LLM to parse the Google search results page and extract:
    - Title
    - URL
    - Snippet

    Filters out ads, top stories, knowledge panels, etc.

    Args:
        content: Captured page content (markdown or text)
        max_results: Maximum results to extract
        valid_urls: Optional list of URLs to validate against (anti-hallucination)

    Returns:
        List of result dicts: [{"url": "...", "title": "...", "snippet": "..."}, ...]
    """
    import httpx

    # Get model config from env
    model_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    model_id = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
    api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    logger.info(f"[ExtractGoogleResults] >>> Starting extraction (content_length={len(content)}, max_results={max_results})")

    if not content or len(content) < 50:
        logger.warning(f"[ExtractGoogleResults] >>> Content too short or empty! Length: {len(content)}")
        logger.warning(f"[ExtractGoogleResults] >>> Content: '{content}'")
        return []

    try:
        # Load prompt from recipe file
        prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "research" / "serp_analyzer.md"
        if prompt_path.exists():
            base_prompt = prompt_path.read_text()
        else:
            logger.warning(f"[ExtractGoogleResults] Prompt file not found: {prompt_path}")
            base_prompt = "Extract organic search results. Return JSON array with title, url, snippet."

        prompt = f"""{base_prompt}

---

## Current Task

CONTENT TO ANALYZE:
{content[:8000]}

Maximum results to extract: {max_results}

JSON OUTPUT:"""

        logger.info(f"[ExtractGoogleResults] >>> Sending {len(prompt)} chars to LLM...")
        logger.info(f"[ExtractGoogleResults] >>> Content sent to LLM (first 800 chars): {content[:800]}")

        # Call LLM via httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                model_url,
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2000
                },
                headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            result = response.json()

        logger.info(f"[ExtractGoogleResults] >>> LLM responded with status {response.status_code}")

        llm_output = result["choices"][0]["message"]["content"].strip()
        logger.info(f"[ExtractGoogleResults] >>> LLM output length: {len(llm_output)} chars")
        logger.info(f"[ExtractGoogleResults] >>> LLM output preview: {llm_output[:500]}")

        # Parse JSON output
        # Remove markdown code blocks if present
        if "```json" in llm_output:
            llm_output = llm_output.split("```json")[1].split("```")[0].strip()
            logger.info("[ExtractGoogleResults] >>> Removed ```json markdown wrapper")
        elif "```" in llm_output:
            llm_output = llm_output.split("```")[1].split("```")[0].strip()
            logger.info("[ExtractGoogleResults] >>> Removed ``` markdown wrapper")

        logger.info(f"[ExtractGoogleResults] >>> Parsing JSON (length: {len(llm_output)})")

        # Try parsing JSON with repair fallback
        try:
            results = json.loads(llm_output)
            logger.info(f"[ExtractGoogleResults] >>> Parsed {len(results)} raw results from JSON")
        except json.JSONDecodeError as e:
            # Try JSON repair for common issues (unterminated strings, literal newlines)
            logger.warning(f"[ExtractGoogleResults] >>> JSON parse failed: {e}, attempting repair...")
            import re

            def escape_newlines_in_strings(match):
                """Escape literal newlines within JSON string values"""
                return match.group(0).replace('\n', '\\n').replace('\r', '')

            try:
                # Fix literal newlines in string values
                fixed_content = re.sub(r'"[^"]*"', escape_newlines_in_strings, llm_output, flags=re.DOTALL)
                results = json.loads(fixed_content)
                logger.info(f"[ExtractGoogleResults] >>> JSON repair successful! Parsed {len(results)} raw results")
            except Exception as repair_error:
                logger.warning(f"[ExtractGoogleResults] >>> Newline fix failed: {repair_error}, trying truncation repair...")

                # Strategy 2: Handle truncated JSON (common with max_tokens limit)
                if "Unterminated string" in str(e) or "Expecting" in str(e):
                    # Try simple closing strategies for truncated arrays
                    repair_attempts = [
                        llm_output + '"}]',    # Close string and array
                        llm_output + '}]',     # Close object and array
                        llm_output + '"]',     # Close string array
                        llm_output + ']',      # Just close array
                    ]

                    for attempt in repair_attempts:
                        try:
                            results = json.loads(attempt)
                            logger.info(f"[ExtractGoogleResults] >>> Truncation repair successful! Parsed {len(results)} raw results")
                            break
                        except json.JSONDecodeError:
                            continue
                    else:
                        # All repairs failed
                        logger.error(f"[ExtractGoogleResults] >>> All JSON repairs failed")
                        raise e  # Re-raise original error
                else:
                    logger.error(f"[ExtractGoogleResults] >>> JSON repair also failed: {repair_error}")
                    raise e  # Re-raise original error

        # Validate results and fix truncated URLs
        validated = []
        valid_urls_set = set(valid_urls) if valid_urls else None

        for r in results:
            if isinstance(r, dict) and "url" in r and "title" in r:
                # Filter out invalid URLs
                url = r["url"]

                # Fix truncated URLs (e.g., "https://www.petco.com/...")
                if "..." in url:
                    # Extract base domain and discard truncated path
                    logger.warning(f"[ExtractGoogleResults] >>> Truncated URL detected: {url}")
                    # Get just the domain
                    parts = url.split("/")
                    if len(parts) >= 3:
                        # Reconstruct as https://domain.com/
                        fixed_url = "/".join(parts[:3]) + "/"
                        logger.info(f"[ExtractGoogleResults] >>> Fixed to: {fixed_url}")
                        url = fixed_url

                if url.startswith("http") and "google.com" not in url:
                    # URL validation against known page URLs (anti-hallucination)
                    if valid_urls_set:
                        # Check if URL or its domain was in the page
                        url_domain = url.split("/")[2] if len(url.split("/")) > 2 else ""
                        is_valid = (
                            url in valid_urls_set or
                            any(url in vu or vu in url for vu in valid_urls_set) or
                            any(url_domain in vu for vu in valid_urls_set)
                        )
                        if not is_valid:
                            logger.warning(f"[ExtractGoogleResults] >>> Rejected hallucinated URL: {url[:60]}")
                            continue

                    validated.append({
                        "url": url,
                        "title": r.get("title", ""),
                        "snippet": r.get("snippet", ""),
                        "_url_source": "llm_validated" if valid_urls_set else "llm_unvalidated"
                    })
                else:
                    logger.debug(f"[ExtractGoogleResults] >>> Filtered out URL: {url}")
            else:
                logger.debug(f"[ExtractGoogleResults] >>> Invalid result format: {r}")

        logger.info(f"[ExtractGoogleResults] >>> Validated {len(validated)} results (filtered from {len(results)} raw)")
        logger.info(f"[GoogleSERP] Extracted {len(validated)} valid results from LLM")
        return validated[:max_results]

    except Exception as e:
        logger.error(f"[GoogleSERP] LLM extraction failed: {e}", exc_info=True)
        # Fallback: use regex-based extraction
        return await _extract_search_results_from_content(content, max_results)


async def _click_google_next(session_id: str) -> bool:
    """
    Click "Next" button on Google SERP for pagination.

    Args:
        session_id: Web Vision session ID

    Returns:
        True if Next button was found and clicked, False otherwise
    """
    from orchestrator import web_vision_mcp

    try:
        # Try to click "Next" button (Google uses various formats)
        result = await web_vision_mcp.click(
            session_id=session_id,
            goal="Next",
            max_attempts=2
        )

        if result.get("success"):
            logger.info("[GooglePagination] Clicked 'Next' button")
            return True
        else:
            logger.debug("[GooglePagination] Could not find or click 'Next' button")
            return False

    except Exception as e:
        logger.debug(f"[GooglePagination] Next button click failed: {e}")
        return False


async def _summarize_page_content(
    content: str,
    reading_goal: str,
    max_input_chars: int = 4000,
    max_output_tokens: int = 400
) -> str:
    """
    Use LLM to summarize page content for intelligence gathering.

    Condenses verbose page content into key facts relevant to the reading goal.

    Preserves:
    - Specific product recommendations (names, models)
    - Price ranges and specifications
    - Key facts and comparisons
    - Expert opinions and user experiences

    Removes:
    - Navigation, ads, boilerplate
    - Redundant information
    - Off-topic content

    Args:
        content: Raw page content (can be verbose)
        reading_goal: What we're trying to learn from this page
        max_input_chars: Maximum input content to process
        max_output_tokens: Maximum tokens for summary output

    Returns:
        Condensed summary string (~500-800 chars)
    """
    import httpx

    # Skip if content is already short
    if len(content) < 1000:
        logger.debug(f"[ContentSummarizer] Content already short ({len(content)} chars), skipping summarization")
        return content

    # Truncate input if too long
    input_content = content[:max_input_chars]

    model_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    model_id = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
    api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    # Detect if goal is asking for a list (topics, threads, items, titles, etc.)
    list_keywords = ["topic", "thread", "title", "post", "discussion", "article", "item", "list", "name", "what are the"]
    goal_lower = reading_goal.lower()
    is_list_goal = any(kw in goal_lower for kw in list_keywords)

    if is_list_goal:
        # Goal wants specific items - preserve exact titles/names
        # Load prompt from recipe file
        prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "research" / "item_lister.md"
        if prompt_path.exists():
            base_prompt = prompt_path.read_text()
        else:
            logger.warning(f"[ContentSummarizer] Prompt file not found: {prompt_path}")
            base_prompt = "Extract and list specific items from the page. Preserve exact titles."

        prompt = f"""{base_prompt}

---

## Current Task

RESEARCH GOAL: {reading_goal}

PAGE CONTENT:
{input_content}

EXTRACTED ITEMS:"""
    else:
        # Standard summarization for product/informational research
        # Load prompt from recipe file
        prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "research" / "page_summarizer.md"
        if prompt_path.exists():
            base_prompt = prompt_path.read_text()
        else:
            logger.warning(f"[ContentSummarizer] Prompt file not found: {prompt_path}")
            base_prompt = "Summarize page content for research. Extract relevant facts and details."

        prompt = f"""{base_prompt}

---

## Current Task

RESEARCH GOAL: {reading_goal}

PAGE CONTENT:
{input_content}

SUMMARY:"""

    # Use higher token limit for list extraction (need more space for multiple items)
    effective_max_tokens = max_output_tokens * 2 if is_list_goal else max_output_tokens
    extraction_mode = "LIST_EXTRACTION" if is_list_goal else "SUMMARIZATION"
    logger.info(f"[ContentSummarizer] Mode: {extraction_mode}, max_tokens={effective_max_tokens}")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                model_url,
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": effective_max_tokens
                },
                headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            result = response.json()

        summary = result["choices"][0]["message"]["content"].strip()
        logger.info(f"[ContentSummarizer] {extraction_mode}: {len(content)} → {len(summary)} chars for goal: {reading_goal[:50]}...")
        return summary

    except Exception as e:
        logger.warning(f"[ContentSummarizer] Summarization failed: {e}, using truncated original")
        # Fallback: return truncated original content
        return content[:1500] + "..." if len(content) > 1500 else content


async def _extract_with_page_intelligence(
    page,
    url: str,
    reading_goal: str
) -> Optional[Dict[str, Any]]:
    """
    Use PageIntelligenceService to understand and extract content from a page.

    Extraction goal is determined from reading_goal:
    - "Find products..." → products extraction (Phase 2)
    - "Learn what matters..." → information extraction (Phase 1)

    This is the UNIVERSAL extraction system that:
    1. Identifies page zones (thread_list, popular_topics, product_grid, etc.)
    2. Generates CSS selectors for each zone (cached per domain)
    3. Extracts content using goal-aware extraction
    4. Caches understanding for future visits

    Args:
        page: Playwright page object (already navigated)
        url: Current URL
        reading_goal: What we want to extract - determines extraction mode automatically

    Returns:
        Dict with extracted content, or None if extraction failed
    """
    try:
        from orchestrator.page_intelligence import get_page_intelligence_service
        from orchestrator.page_intelligence.models import ZoneType, PageType

        service = get_page_intelligence_service()

        # Determine extraction goal based on reading_goal context
        # - Phase 1 uses "Learn what matters..." → extract information
        # - Phase 2 uses "Find products..." → extract products
        goal_lower = reading_goal.lower()

        if "find products" in goal_lower or "products matching" in goal_lower:
            # Phase 2: Product extraction mode
            extraction_goal = "products"
            logger.info(f"[PageIntelligence] Extraction goal: products (Phase 2 product extraction)")
        else:
            # Phase 1: Intelligence gathering - always extract information, not products
            extraction_goal = "information"

            # Refine based on content type hints (forum vs article)
            if any(kw in goal_lower for kw in ["topic", "thread", "discussion", "forum", "post"]):
                extraction_goal = "topics"
            elif any(kw in goal_lower for kw in ["article", "news", "story", "headline"]):
                extraction_goal = "news"

            logger.info(f"[PageIntelligence] Extraction goal: {extraction_goal} (Phase 1 intelligence gathering)")

        # Phase 1-3: Understand page structure (uses cache if available)
        understanding = await service.understand_page(
            page, url,
            extraction_goal=extraction_goal
        )

        if not understanding.zones:
            logger.warning(f"[PageIntelligence] No zones identified for {url}")
            return None

        # Log what we found
        zone_types = [z.zone_type.value if hasattr(z.zone_type, 'value') else z.zone_type for z in understanding.zones]
        logger.info(f"[PageIntelligence] Identified zones: {zone_types}, page_type: {understanding.page_type}")

        # Determine primary zone for extraction based on goal
        target_zone = None
        list_zones = [ZoneType.POPULAR_TOPICS, ZoneType.THREAD_LIST, ZoneType.POST_LIST,
                      ZoneType.ARTICLE_LIST, ZoneType.NEWS_FEED, ZoneType.LIST_CONTENT]

        use_prose_extraction = False
        content_zone = None  # The actual zone object for prose extraction

        if extraction_goal in ("topics", "threads", "list_items", "news"):
            # Look for list-type zones
            for zone in understanding.zones:
                if zone.zone_type in list_zones:
                    target_zone = zone.zone_type.value if hasattr(zone.zone_type, 'value') else zone.zone_type
                    content_zone = zone
                    break
            # Fallback to content_prose - but use ProseExtractor directly for this case
            if not target_zone:
                for zone in understanding.zones:
                    if zone.zone_type == ZoneType.CONTENT_PROSE:
                        target_zone = "content_prose"
                        content_zone = zone  # Capture zone for prose extraction
                        use_prose_extraction = True  # Force ProseExtractor for prose zones with topic goals
                        break
        elif extraction_goal == "products":
            # Look for product zones
            for zone in understanding.zones:
                if zone.zone_type in [ZoneType.PRODUCT_GRID, ZoneType.PRODUCT_DETAILS]:
                    target_zone = zone.zone_type.value if hasattr(zone.zone_type, 'value') else zone.zone_type
                    content_zone = zone
                    break

        # Phase 4: Extract using understanding
        extracted_links = []  # Links from page for navigation (forum threads, articles, etc.)

        if target_zone and not use_prose_extraction:
            # Use selector-based extraction for structured zones
            logger.info(f"[PageIntelligence] Extracting from zone: {target_zone} (selector mode)")
            items = await service.extract(page, understanding, zone_type=target_zone)
        else:
            # Use prose extraction for unstructured content or prose zones
            logger.info(f"[PageIntelligence] Using prose extraction for goal: {extraction_goal}")
            from orchestrator.page_intelligence.extractors.prose_extractor import ProseExtractor
            from orchestrator.page_intelligence.llm_client import get_llm_client

            prose_extractor = ProseExtractor(llm_client=get_llm_client())
            # Pass the zone and reading_goal for proper extraction
            extraction_result = await prose_extractor.extract(
                page,
                zone=content_zone,  # Pass zone for link filtering
                extraction_goal=extraction_goal,
                query_context=reading_goal
            )
            # Normalize response - generic prompt may return different keys
            # Try multiple keys the LLM might use for list data
            items = (
                extraction_result.get("items") or
                extraction_result.get("entries") or
                extraction_result.get("results") or
                extraction_result.get("data") or
                []
            )
            # Preserve extracted links from prose extraction (for forum threads, article lists, etc.)
            extracted_links = extraction_result.get("extracted_links", [])
            # If LLM returned answer-style response, wrap it as an item
            if not items and extraction_result.get("answer"):
                items = [{
                    "title": "Summary",
                    "content": extraction_result.get("answer"),
                    "details": extraction_result.get("details", "")
                }]

        if not items:
            logger.warning(f"[PageIntelligence] No items extracted")
            return None

        # Format results
        logger.info(f"[PageIntelligence] Extracted {len(items)} items")

        # Build summary from extracted items
        item_summaries = []
        for item in items[:30]:  # Limit to 30 items
            if isinstance(item, dict):
                title = item.get("title", "")
                if title:
                    item_summaries.append(f"- {title}")
            elif hasattr(item, "title"):
                item_summaries.append(f"- {item.title}")

        summary_text = "\n".join(item_summaries) if item_summaries else "No items extracted"

        return {
            "success": True,
            "extraction_method": "page_intelligence",
            "page_type": understanding.page_type.value if hasattr(understanding.page_type, 'value') else str(understanding.page_type),
            "zones_identified": zone_types,
            "target_zone": target_zone,
            "extraction_goal": extraction_goal,
            "items": items,
            "extracted_links": extracted_links,  # Navigable links from page (forum threads, articles)
            "summary": summary_text,
            "has_list_content": understanding.has_list_content,
            "cached": True  # Understanding was cached
        }

    except ImportError as e:
        logger.warning(f"[PageIntelligence] Import error (page_intelligence not available): {e}")
        return None
    except Exception as e:
        logger.warning(f"[PageIntelligence] Extraction failed: {e}")
        import traceback
        logger.debug(f"[PageIntelligence] Traceback: {traceback.format_exc()}")
        return None


async def _web_vision_visit_and_read(
    url: str,
    reading_goal: str,
    session_id: str = "default",
    human_assist_allowed: bool = True,  # Enable captcha intervention by default
    event_emitter: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    """
    Visit a page and read content using Web Vision MCP.

    Replaces: human_web_navigator.visit_and_read()

    Args:
        url: URL to visit
        reading_goal: What we're trying to learn from this page (also determines extraction mode)
        session_id: Web Vision session ID
        human_assist_allowed: If True, request human intervention for CAPTCHAs
        event_emitter: Optional event emitter for WebSocket notifications

    Returns:
        {
            "url": "...",
            "text_content": "...",
            "extracted_info": {...},
            "summary": "...",
            "page_type": "...",
            "metadata": {...}
        }
    """
    from orchestrator import web_vision_mcp
    from orchestrator.content_sanitizer import ContentSanitizer
    from orchestrator.captcha_intervention import detect_blocker, request_intervention

    try:
        # 1. Navigate to URL with retry logic
        nav_result = await web_vision_mcp.navigate(
            session_id=session_id,
            url=url,
            wait_for="networkidle"
        )

        # If navigation failed, log and return None
        if not nav_result.get("success"):
            logger.warning(f"[WebVisionVisit] Navigation failed: {nav_result.get('message', 'unknown error')}")
            return None

        # Get actual URL after redirects (may have been redirected to block page)
        final_url = nav_result.get("url", url)

        # 2a. First capture HTML to extract product links (before markdown conversion loses them)
        html_result = await web_vision_mcp.capture_content(
            session_id=session_id,
            format="html"
        )

        # Extract product URLs from HTML using existing utility
        from orchestrator.product_extractor import _extract_product_links
        product_url_map = _extract_product_links(html_result.get("content", ""), final_url)
        if product_url_map:
            logger.info(f"[WebVisionVisit] Extracted {len(product_url_map)} product URLs from HTML")

        # 2b. Capture markdown for text content
        content_result = await web_vision_mcp.capture_content(
            session_id=session_id,
            format="markdown"
        )

        # 3. Check for blockers (CAPTCHA, rate limit, etc.)
        page_content = content_result.get("content", "")
        blocker = detect_blocker({
            "url": final_url,
            "content": page_content,
            "status": 200  # Playwright doesn't expose response status easily
        })

        if blocker and blocker["confidence"] >= 0.7 and human_assist_allowed:
            logger.warning(
                f"[WebVisionVisit] Blocker detected on {final_url}: "
                f"{blocker['type'].value} (confidence={blocker['confidence']:.0%})"
            )
            logger.info(f"[WebVisionVisit] Indicators: {', '.join(blocker['indicators'])}")

            # Take screenshot for human reference
            import os
            screenshot_dir = "panda_system_docs/research_screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_filename = f"blocker_{session_id}_{int(asyncio.get_event_loop().time())}.png"
            screenshot_path = os.path.join(screenshot_dir, screenshot_filename)

            # Get page object for screenshot
            from orchestrator.web_vision_mcp import _get_or_create_page
            page = await _get_or_create_page(session_id)
            await page.screenshot(path=screenshot_path, full_page=False)
            logger.info(f"[WebVisionVisit] Screenshot saved: {screenshot_path}")

            # noVNC URL for live browser access
            novnc_url = "http://localhost:6080/vnc_lite.html?host=localhost&port=6080&scale=true"

            # Request human intervention
            intervention = await request_intervention(
                blocker_type=blocker["type"],
                url=final_url,
                screenshot_path=screenshot_path,
                session_id=session_id,
                blocker_details=blocker,
                cdp_url=novnc_url
            )

            # Emit intervention_needed event for WebSocket notification
            if event_emitter:
                await event_emitter.emit_intervention_needed(
                    intervention_id=intervention.intervention_id,
                    url=final_url,
                    blocker_type=blocker["type"],
                    screenshot_path=screenshot_path,
                    cdp_url=intervention.cdp_url
                )

            logger.info(
                f"[WebVisionVisit] Waiting for human to resolve intervention "
                f"(ID: {intervention.intervention_id}, timeout: 120s)"
            )

            # Wait for user to solve CAPTCHA (120 second timeout)
            resolved = await intervention.wait_for_resolution(timeout=120)

            if resolved:
                logger.info(f"[WebVisionVisit] Intervention resolved, re-capturing content")
                # Re-capture content after intervention
                content_result = await web_vision_mcp.capture_content(
                    session_id=session_id,
                    format="markdown"
                )
            else:
                logger.warning(f"[WebVisionVisit] Intervention timed out, continuing with blocked content")

        elif blocker and blocker["confidence"] >= 0.7:
            # Blocked but human_assist not allowed
            logger.warning(
                f"[WebVisionVisit] Blocker detected but human_assist disabled: "
                f"{blocker['type'].value} on {final_url}"
            )
            return None

        # 4. TRY PAGE INTELLIGENCE EXTRACTION FIRST (universal extraction with caching)
        # This uses the PageIntelligenceService to:
        # - Identify page zones (thread_list, popular_topics, product_grid, etc.)
        # - Generate and cache CSS selectors per domain
        # - Extract using goal-aware extractors
        from orchestrator.web_vision_mcp import _get_or_create_page
        page = await _get_or_create_page(session_id)

        page_intel_result = await _extract_with_page_intelligence(
            page=page,
            url=final_url,
            reading_goal=reading_goal
        )

        if page_intel_result and page_intel_result.get("success"):
            # Page Intelligence extraction succeeded!
            logger.info(f"[WebVisionVisit] PageIntelligence extraction successful: {len(page_intel_result.get('items', []))} items")

            # Format result using page intelligence output
            pi_summary = page_intel_result.get("summary", "")
            pi_items = page_intel_result.get("items", [])
            extraction_goal = page_intel_result.get("extraction_goal", "")

            # Convert items to expected format based on extraction goal
            # For products, IntelligentSearch expects: {"name": "...", "price": "$X", "url": "..."}
            formatted_products = []
            if extraction_goal == "products":
                for item in pi_items:
                    if isinstance(item, dict):
                        # Convert title->name, ensure price is string, add url
                        formatted_product = {
                            "name": item.get("title") or item.get("name", "Unknown"),
                            "price": str(item.get("price", "")) if item.get("price") else item.get("price_note", "Price not listed"),
                            "url": item.get("url", final_url),  # Use vendor URL if no product URL
                            "description": item.get("description", ""),
                            "availability": item.get("availability", "")
                        }
                        formatted_products.append(formatted_product)

            # Get extracted links from page (for forum threads, articles, etc.)
            pi_extracted_links = page_intel_result.get("extracted_links", [])

            result = {
                "url": final_url,  # Use final URL after redirects
                "text_content": pi_summary,
                "text_content_full": None,  # Items are in structured form
                "extracted_info": {
                    "page_type": page_intel_result.get("page_type", "unknown"),
                    "extraction_method": "page_intelligence",
                    "zones_identified": page_intel_result.get("zones_identified", []),
                    "target_zone": page_intel_result.get("target_zone"),
                    "items": pi_items,
                    # IMPORTANT: Also include as "products" for IntelligentSearch compatibility
                    "products": formatted_products if extraction_goal == "products" else [],
                    # Links from page for follow-up navigation (forum threads, articles)
                    "extracted_links": pi_extracted_links
                },
                "summary": pi_summary,
                "page_type": page_intel_result.get("page_type", "unknown"),
                "key_points": [item.get("title") or item.get("name", str(item)) if isinstance(item, dict) else str(item) for item in pi_items[:15]],
                "claims": [],  # Page intelligence doesn't generate claims (yet)
                "extracted_links": pi_extracted_links,  # Top-level for easy access
                "metadata": {
                    "extraction_method": "page_intelligence",
                    "extraction_goal": extraction_goal,
                    "zones_identified": page_intel_result.get("zones_identified", []),
                    "has_list_content": page_intel_result.get("has_list_content", False),
                    "item_count": len(pi_items),
                    "extracted_link_count": len(pi_extracted_links),
                    "capture_method": "web_vision_mcp"
                }
            }

            logger.info(f"[WebVisionVisit] PageIntelligence: {url[:60]}... ({len(pi_items)} items, {len(formatted_products)} products)")
            return result

        # 5. FALLBACK: Traditional markdown extraction if PageIntelligence failed
        logger.info(f"[WebVisionVisit] PageIntelligence unavailable, using traditional extraction")

        # 5a. Sanitize content
        sanitizer = ContentSanitizer()
        sanitized = sanitizer.sanitize(content_result["content"], url)

        # 5b. Reconstruct clean_text from chunks
        if "chunks" in sanitized and sanitized["chunks"]:
            clean_text = "\n\n".join(chunk["text"] for chunk in sanitized["chunks"])
        else:
            # Fallback: use raw content if sanitizer failed
            clean_text = content_result["content"]
            logger.warning(f"[WebVisionVisit] No chunks from sanitizer, using raw content ({len(clean_text)} chars)")

        # 6. Extract information using LLM (pass product URLs extracted from HTML)
        extracted_info = await _extract_information_llm(
            text_content=clean_text,
            url=url,
            reading_goal=reading_goal,
            product_url_map=product_url_map
        )

        # 7. Summarize content for cleaner LLM context (Phase B: Website Content Cleaning)
        # This condenses verbose page content into key facts relevant to reading_goal
        if len(clean_text) > 1000:
            summarized_content = await _summarize_page_content(
                content=clean_text,
                reading_goal=reading_goal,
                max_input_chars=4000,
                max_output_tokens=400
            )
            logger.info(f"[WebVisionVisit] Summarized content: {len(clean_text)} -> {len(summarized_content)} chars")
        else:
            # Short content doesn't need summarization
            summarized_content = clean_text

        # 8. Create result (traditional extraction fallback)
        result = {
            "url": final_url,  # Use final URL after redirects
            "text_content": summarized_content,  # Use summarized content for cleaner LLM context
            "text_content_full": clean_text if len(clean_text) > 1000 else None,  # Keep full text for debugging
            "extracted_info": extracted_info,
            "summary": summarized_content[:500] + "..." if len(summarized_content) > 500 else summarized_content,
            "page_type": extracted_info.get("page_type", "unknown"),
            "metadata": {
                "extraction_method": "traditional_markdown",  # Fallback method
                "sanitization": sanitized.get("metadata", {}),
                "structured_data": sanitized.get("structured_data", {}),
                "total_chunks": sanitized.get("total_chunks", 0),
                "capture_method": "web_vision_mcp",
                "original_length": len(clean_text),
                "summarized_length": len(summarized_content)
            }
        }

        logger.info(f"[WebVisionVisit] Successfully read {url[:60]}... ({len(summarized_content)} chars summary, {sanitized.get('total_chunks', 0)} chunks)")
        return result

    except Exception as e:
        logger.error(f"[WebVisionVisit] Failed to read {url}: {e}")
        return None


async def _extract_search_results_from_content(
    content: str,
    max_results: int = 10
) -> List[Dict[str, Any]]:
    """
    Extract search result URLs and titles from captured page content.

    Args:
        content: Markdown content from search results page
        max_results: Maximum results to extract

    Returns:
        List of candidates with url, title, snippet
    """
    import os
    from orchestrator.shared import call_llm_json

    # Load prompt from recipe file
    prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "research" / "organic_results_extractor.md"
    if prompt_path.exists():
        base_prompt = prompt_path.read_text()
    else:
        logger.warning(f"[ExtractSearchResults] Prompt file not found: {prompt_path}")
        base_prompt = "Extract organic search results (fallback mode). Return JSON array."

    # Content should already be filtered to organic results only (by caller)
    # Use first 4000 chars for extraction
    content_for_extraction = content[:4000]
    logger.info(f"[ExtractSearchResults] Using {len(content_for_extraction)} chars for extraction")
    # Debug: Log first 500 chars to see what we're sending
    logger.debug(f"[ExtractSearchResults] Content preview: {content_for_extraction[:500]}")

    prompt = f"""{base_prompt}

---

## Current Task

CONTENT:
{content_for_extraction}

Maximum results to extract: {max_results}

JSON OUTPUT:"""

    llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
    llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    try:
        result = await call_llm_json(prompt=prompt, llm_url=llm_url, llm_model=llm_model, llm_api_key=llm_api_key, max_tokens=1500)

        # Debug: Log the raw LLM response
        logger.info(f"[ExtractSearchResults] LLM response type: {type(result)}, content: {str(result)[:300]}")

        # Handle both direct array and wrapped response
        if isinstance(result, list):
            candidates = result[:max_results]
        elif isinstance(result, dict) and "results" in result:
            candidates = result["results"][:max_results]
        else:
            logger.warning(f"[ExtractSearchResults] Unexpected LLM response format: {type(result)}, full: {result}")
            candidates = []

        # Log extracted URLs for debugging
        for i, c in enumerate(candidates):
            url = c.get('url', 'N/A')
            title = c.get('title', 'N/A')[:50]
            logger.info(f"[ExtractSearchResults] Result {i+1}: {title} -> {url}")

        return candidates

    except Exception as e:
        logger.error(f"[ExtractSearchResults] LLM extraction failed: {e}")
        return []


async def _extract_information_llm(
    text_content: str,
    url: str,
    reading_goal: str,
    product_url_map: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Extract structured information from page content using LLM.

    Args:
        text_content: Clean text content from page
        url: Source URL
        reading_goal: What we're trying to learn
        product_url_map: Optional dict mapping product text to actual URLs (extracted from HTML)

    Returns:
        Extracted information (products, facts, opinions, etc.)
    """
    import os
    from orchestrator.shared import call_llm_json

    # Truncate to first 4000 chars to stay within token limits
    content_snippet = text_content[:4000]

    # Load prompt from recipe file
    prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "research" / "webpage_reader.md"
    if prompt_path.exists():
        base_prompt = prompt_path.read_text()
    else:
        logger.warning(f"[ExtractInfo] Prompt file not found: {prompt_path}")
        base_prompt = "Extract information from webpage. Return JSON with page_type, main_content, products, facts, opinions."

    prompt = f"""{base_prompt}

---

## Current Task

URL: {url}
READING GOAL: {reading_goal}

CONTENT:
{content_snippet}

JSON OUTPUT:"""

    llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
    llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    try:
        result = await call_llm_json(prompt=prompt, llm_url=llm_url, llm_model=llm_model, llm_api_key=llm_api_key, max_tokens=1000)

        # Post-process: match LLM-extracted products to real URLs from HTML
        if product_url_map and result.get("products"):
            matched_count = 0
            for product in result["products"]:
                product_name = product.get("name", "").lower().strip()
                if not product_name:
                    continue

                # Try to find matching URL from the HTML-extracted URL map
                best_match_url = None
                best_match_score = 0

                for link_text, link_url in product_url_map.items():
                    link_text_lower = link_text.lower()
                    # Score based on word overlap
                    product_words = set(product_name.split())
                    link_words = set(link_text_lower.split())
                    overlap = len(product_words & link_words)
                    # Also check if product name is contained in link text or vice versa
                    if product_name in link_text_lower or link_text_lower in product_name:
                        overlap += 3  # Bonus for substring match

                    if overlap > best_match_score:
                        best_match_score = overlap
                        best_match_url = link_url

                # Assign URL based on match quality
                current_url = product.get("url", "")
                is_fake_url = not current_url or "#product-" in current_url or current_url == url

                if best_match_url and best_match_score >= 2 and is_fake_url:
                    product["url"] = best_match_url
                    matched_count += 1
                    logger.debug(f"[ExtractInfo] Matched product '{product_name[:30]}' to URL: {best_match_url[:60]}")
                elif is_fake_url:
                    # No good match found - use vendor homepage instead of fake URL
                    product["url"] = url
                    logger.debug(f"[ExtractInfo] No URL match for '{product_name[:30]}', using homepage")

            if matched_count > 0:
                logger.info(f"[ExtractInfo] Matched {matched_count}/{len(result['products'])} products to real URLs")

        # Log extraction results for debugging
        if result.get("products"):
            logger.info(f"[ExtractInfo] Extracted {len(result.get('products', []))} products from {url[:60]}")
        else:
            logger.info(f"[ExtractInfo] No products extracted from {url[:60]} (page_type: {result.get('page_type', 'unknown')})")

        return result

    except Exception as e:
        logger.error(f"[ExtractInfo] LLM extraction failed: {e}")
        return {
            "page_type": "unknown",
            "main_content": text_content[:200]
        }
