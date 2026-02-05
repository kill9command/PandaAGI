"""
apps/services/tool_server/candidate_prioritizer.py

Smart candidate prioritization for PDP verification.

Instead of verifying ALL extracted candidates (expensive), this module:
1. Scores candidates by likelihood of matching requirements
2. Safely rejects candidates that are DEFINITELY wrong category
3. Returns prioritized list for verification with early stopping

This optimization can reduce PDP verification time by 50-80% by:
- Verifying high-probability candidates first
- Stopping early when enough viable products found
- Skipping obviously wrong products (Chromebooks when looking for NVIDIA GPU)

Created: 2025-12-16
"""

import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class ScoredCandidate:
    """A candidate with priority score and categorization."""
    product: Dict[str, Any]
    score: float
    category: str  # "high", "medium", "low", "reject"
    signals: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None


@dataclass
class PrioritizationResult:
    """Result of candidate prioritization."""
    prioritized: List[Dict[str, Any]]  # Sorted by score, rejects removed
    rejected: List[Dict[str, Any]]  # Safe rejects with reasons
    stats: Dict[str, int]


# ============================================================================
# REJECTION RULES - Products that are DEFINITELY wrong
# These are safe to skip without PDP verification
# ============================================================================

# Products that NEVER have dedicated NVIDIA/AMD GPUs
SAFE_REJECT_CATEGORIES = {
    # Chromebooks - always integrated graphics
    "chromebook": "Chromebooks only have integrated graphics",
    "chrome os": "Chrome OS devices only have integrated graphics",

    # Apple products - no NVIDIA option since 2016
    "macbook": "MacBooks don't have NVIDIA GPUs (Apple silicon or AMD only)",
    "imac": "iMacs don't have NVIDIA GPUs",
    "mac mini": "Mac Minis don't have NVIDIA GPUs",
    "mac studio": "Mac Studios don't have NVIDIA GPUs",

    # Tablets and mobile devices
    "ipad": "iPads are tablets, not laptops with dedicated GPUs",
    "surface go": "Surface Go has integrated graphics only",
    "tablet": "Tablets don't have dedicated GPUs",

    # Budget/office categories that never have dGPU
    "chromebook plus": "Chromebook Plus still only has integrated graphics",
}

# Explicit integrated graphics mentions - safe to reject for dGPU queries
INTEGRATED_GRAPHICS_KEYWORDS = [
    "intel uhd",
    "intel iris",
    "intel hd graphics",
    "integrated graphics",
    "intel graphics",
    "amd radeon graphics",  # This is the integrated Radeon in Ryzen APUs
    "radeon graphics",      # Without a model number, this is integrated
]

# Keywords that indicate dedicated NVIDIA GPU
NVIDIA_POSITIVE_KEYWORDS = [
    "rtx",
    "geforce",
    "nvidia",
    "gtx",
    "quadro",
    "rtx 4050",
    "rtx 4060",
    "rtx 4070",
    "rtx 4080",
    "rtx 4090",
    "rtx 3050",
    "rtx 3060",
    "rtx 3070",
    "rtx 3080",
]

# Keywords that indicate dedicated AMD GPU (not integrated)
AMD_DGPU_KEYWORDS = [
    "radeon rx",
    "rx 6600",
    "rx 6700",
    "rx 7600",
    "rx 7700",
    "rx 7800",
    "rx 7900",
]

# Gaming keywords - products more likely to have dGPU
GAMING_KEYWORDS = [
    "gaming",
    "gamer",
    "rog",          # ASUS Republic of Gamers
    "tuf gaming",   # ASUS TUF
    "predator",     # Acer Predator
    "nitro",        # Acer Nitro
    "legion",       # Lenovo Legion
    "omen",         # HP Omen
    "alienware",    # Dell Alienware
    "razer blade",  # Razer
    "zephyrus",     # ASUS ROG Zephyrus
    "strix",        # ASUS ROG Strix
]


def extract_specs_from_text(text: str) -> Dict[str, Any]:
    """
    Extract specifications from product name/URL text.

    Returns dict with detected specs like:
    {"gpu": "RTX 4060", "ram": "16GB", "integrated_graphics": True}
    """
    if not text:
        return {}

    text_lower = text.lower()
    specs = {}

    # Check for NVIDIA GPU
    for kw in NVIDIA_POSITIVE_KEYWORDS:
        if kw in text_lower:
            # Try to extract model number
            pattern = rf'({kw})\s*(\d{{4}})\s*(ti|super)?'
            match = re.search(pattern, text_lower)
            if match:
                model = f"{match.group(1).upper()} {match.group(2)}"
                if match.group(3):
                    model += f" {match.group(3).upper()}"
                specs["gpu"] = model
            else:
                specs["gpu"] = kw.upper()
            specs["has_nvidia"] = True
            break

    # Check for AMD dedicated GPU
    for kw in AMD_DGPU_KEYWORDS:
        if kw in text_lower:
            specs["gpu"] = kw.upper()
            specs["has_amd_dgpu"] = True
            break

    # Check for integrated graphics
    for kw in INTEGRATED_GRAPHICS_KEYWORDS:
        if kw in text_lower:
            specs["integrated_graphics"] = True
            specs["integrated_type"] = kw
            break

    # Check for gaming indicators
    for kw in GAMING_KEYWORDS:
        if kw in text_lower:
            specs["is_gaming"] = True
            specs["gaming_brand"] = kw
            break

    # Extract RAM if mentioned
    ram_match = re.search(r'(\d+)\s*gb\s*(ram|ddr|memory)?', text_lower)
    if ram_match:
        specs["ram_gb"] = int(ram_match.group(1))

    # Extract price if in text
    price_match = re.search(r'\$[\d,]+(?:\.\d{2})?', text)
    if price_match:
        try:
            specs["price"] = float(price_match.group().replace('$', '').replace(',', ''))
        except ValueError:
            pass

    return specs


def parse_price(price_value: Any) -> Optional[float]:
    """Parse price from various formats."""
    if price_value is None:
        return None

    if isinstance(price_value, (int, float)):
        return float(price_value)

    if isinstance(price_value, str):
        # Remove currency symbols and commas
        cleaned = re.sub(r'[^\d.]', '', price_value)
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    return None


def score_candidate(
    product: Dict[str, Any],
    requirements: Dict[str, Any],
    query: str = ""
) -> ScoredCandidate:
    """
    Score a candidate product for verification priority.

    Args:
        product: Extracted product with name, price, url
        requirements: User requirements from Phase 1 intelligence
        query: Original user query

    Returns:
        ScoredCandidate with score, category, and signals
    """
    score = 0.0
    signals = []
    rejection_reason = None

    # Extract text to analyze
    name = (product.get("name") or product.get("title") or "").lower()
    url = (product.get("url") or "").lower()
    desc = (product.get("description") or "").lower()

    # Combine all text for analysis
    all_text = f"{name} {url} {desc}"

    # Parse price
    price = parse_price(product.get("price"))

    # Extract specs from name and URL
    name_specs = extract_specs_from_text(name)
    url_specs = extract_specs_from_text(url)

    # Determine what user is looking for
    query_lower = query.lower()
    wants_nvidia = any(kw in query_lower for kw in ["nvidia", "rtx", "geforce", "gtx"])
    wants_gaming = any(kw in query_lower for kw in ["gaming", "game", "gamer"])
    wants_dgpu = wants_nvidia or "dedicated gpu" in query_lower or "discrete gpu" in query_lower

    # Also check requirements
    req_gpu = str(requirements.get("gpu", "")).lower()
    if any(kw in req_gpu for kw in ["nvidia", "rtx", "geforce"]):
        wants_nvidia = True
        wants_dgpu = True

    # ========================================================================
    # SAFE REJECTION CHECKS - Products that are DEFINITELY wrong
    # ========================================================================

    if wants_nvidia or wants_dgpu:
        # Check for categories that NEVER have dedicated NVIDIA GPUs
        for reject_kw, reason in SAFE_REJECT_CATEGORIES.items():
            if reject_kw in name:
                return ScoredCandidate(
                    product=product,
                    score=-999,
                    category="reject",
                    signals=[f"REJECT: {reject_kw} detected"],
                    rejection_reason=reason
                )

        # Check for explicit integrated graphics mentions
        if name_specs.get("integrated_graphics") and not name_specs.get("has_nvidia"):
            return ScoredCandidate(
                product=product,
                score=-999,
                category="reject",
                signals=[f"REJECT: Explicitly states integrated graphics: {name_specs.get('integrated_type')}"],
                rejection_reason=f"Product explicitly has {name_specs.get('integrated_type')} (integrated, not dedicated)"
            )

    # ========================================================================
    # POSITIVE SCORING - Higher score = verify first
    # ========================================================================

    # Strong positive: GPU explicitly mentioned in name
    if name_specs.get("has_nvidia"):
        score += 1.5
        signals.append(f"+1.5: NVIDIA GPU in name ({name_specs.get('gpu', 'detected')})")

    # Medium positive: GPU in URL (many retailers encode specs in URL)
    if url_specs.get("has_nvidia") and not name_specs.get("has_nvidia"):
        score += 1.0
        signals.append(f"+1.0: NVIDIA GPU in URL ({url_specs.get('gpu', 'detected')})")

    # Positive: Gaming keywords (these products usually have dGPU)
    if name_specs.get("is_gaming"):
        score += 0.5
        signals.append(f"+0.5: Gaming product ({name_specs.get('gaming_brand')})")
    elif url_specs.get("is_gaming"):
        score += 0.3
        signals.append(f"+0.3: Gaming keyword in URL")

    # Positive: Price range typical for gaming laptops with dGPU
    if price:
        if wants_dgpu and 900 <= price <= 3000:
            score += 0.3
            signals.append(f"+0.3: Price ${price:.0f} in typical dGPU range")
        elif wants_dgpu and price < 600:
            score -= 0.3
            signals.append(f"-0.3: Price ${price:.0f} too low for dGPU laptop")

    # Positive: RAM suggests higher-end machine
    ram = name_specs.get("ram_gb") or url_specs.get("ram_gb")
    if ram and ram >= 16:
        score += 0.2
        signals.append(f"+0.2: {ram}GB RAM suggests higher-end")

    # ========================================================================
    # NEGATIVE SCORING - Lower priority but still verify
    # ========================================================================

    # Slight negative: Budget keywords (less likely to have dGPU but possible)
    budget_keywords = ["budget", "affordable", "basic", "everyday", "home", "office"]
    if any(kw in name for kw in budget_keywords):
        score -= 0.2
        signals.append("-0.2: Budget/office keywords (less likely to have dGPU)")

    # Slight negative: Very low RAM suggests budget machine
    if ram and ram <= 8:
        score -= 0.1
        signals.append(f"-0.1: Only {ram}GB RAM suggests budget tier")

    # ========================================================================
    # CATEGORIZE
    # ========================================================================

    if score >= 1.0:
        category = "high"
    elif score >= 0.3:
        category = "medium"
    elif score >= 0:
        category = "low"
    else:
        category = "low"  # Negative but not rejected - still verify if needed

    return ScoredCandidate(
        product=product,
        score=score,
        category=category,
        signals=signals,
        rejection_reason=rejection_reason
    )


def prioritize_candidates(
    candidates: List[Dict[str, Any]],
    requirements: Dict[str, Any],
    query: str = "",
    max_to_verify: int = 10
) -> PrioritizationResult:
    """
    Prioritize candidates for PDP verification.

    Args:
        candidates: List of extracted product candidates
        requirements: User requirements from Phase 1
        query: Original user query
        max_to_verify: Maximum candidates to return for verification

    Returns:
        PrioritizationResult with prioritized list and rejection stats
    """
    if not candidates:
        return PrioritizationResult(
            prioritized=[],
            rejected=[],
            stats={"total": 0, "prioritized": 0, "rejected": 0}
        )

    scored = []
    rejected = []

    for candidate in candidates:
        result = score_candidate(candidate, requirements, query)

        if result.category == "reject":
            # Safe to skip - add rejection info to product
            rejected_product = candidate.copy()
            rejected_product["_rejection_reason"] = result.rejection_reason
            rejected_product["_rejection_signals"] = result.signals
            rejected.append(rejected_product)

            logger.info(
                f"[Prioritizer] REJECT: {candidate.get('name', 'Unknown')[:40]} - "
                f"{result.rejection_reason}"
            )
        else:
            scored.append(result)

            if result.signals:
                logger.debug(
                    f"[Prioritizer] Score {result.score:.1f} ({result.category}): "
                    f"{candidate.get('name', 'Unknown')[:40]} - {result.signals}"
                )

    # Sort by score (highest first)
    scored.sort(key=lambda x: x.score, reverse=True)

    # Take top candidates for verification
    prioritized = [s.product for s in scored[:max_to_verify]]

    # Log summary
    high_count = sum(1 for s in scored if s.category == "high")
    medium_count = sum(1 for s in scored if s.category == "medium")
    low_count = sum(1 for s in scored if s.category == "low")

    logger.info(
        f"[Prioritizer] Prioritized {len(prioritized)}/{len(candidates)} candidates: "
        f"{high_count} high, {medium_count} medium, {low_count} low priority, "
        f"{len(rejected)} rejected"
    )

    return PrioritizationResult(
        prioritized=prioritized,
        rejected=rejected,
        stats={
            "total": len(candidates),
            "prioritized": len(prioritized),
            "rejected": len(rejected),
            "high_priority": high_count,
            "medium_priority": medium_count,
            "low_priority": low_count
        }
    )


def should_continue_verification(
    viable_count: int,
    verified_count: int,
    remaining_count: int,
    target_per_vendor: int = 4,
    min_viable_ratio: float = 0.3
) -> Tuple[bool, str]:
    """
    Determine if we should continue verifying more candidates.

    Implements early stopping logic:
    - Stop if we have enough viable products
    - Stop if yield rate is too low (wasting time)
    - Continue if we haven't found enough yet

    Args:
        viable_count: Number of viable products found so far
        verified_count: Number of products verified so far
        remaining_count: Number of candidates remaining
        target_per_vendor: Target viable products per vendor
        min_viable_ratio: Minimum ratio to continue (stop if too many rejects)

    Returns:
        Tuple of (should_continue: bool, reason: str)
    """
    # Success: We have enough viable products
    if viable_count >= target_per_vendor:
        return False, f"Found {viable_count} viable products (target: {target_per_vendor})"

    # No more candidates to verify
    if remaining_count == 0:
        return False, f"No more candidates to verify ({viable_count} viable found)"

    # Check yield rate after minimum sample
    if verified_count >= 3:
        yield_rate = viable_count / verified_count if verified_count > 0 else 0

        # If yield is very low and we've tried several, might want to stop
        # But only if we have at least some products
        if yield_rate < min_viable_ratio and viable_count >= 2:
            return False, f"Low yield rate ({yield_rate:.0%}), stopping with {viable_count} products"

    # Continue verifying
    return True, f"Need more products ({viable_count}/{target_per_vendor})"


# ============================================================================
# Convenience function for integration
# ============================================================================

def prioritize_and_filter(
    candidates: List[Dict[str, Any]],
    requirements: Dict[str, Any],
    query: str = "",
    max_to_verify: int = 10
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Convenience function: prioritize candidates and return (to_verify, rejected).

    Args:
        candidates: Extracted product candidates
        requirements: User requirements
        query: User query
        max_to_verify: Max candidates to verify

    Returns:
        Tuple of (candidates_to_verify, rejected_candidates)
    """
    result = prioritize_candidates(candidates, requirements, query, max_to_verify)
    return result.prioritized, result.rejected


# ============================================================================
# Test
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test candidates
    test_candidates = [
        {"name": "ASUS TUF Gaming F15 RTX 4060", "price": "$1,099", "url": "/asus-tuf-rtx-4060"},
        {"name": "Dell G15 Gaming Laptop", "price": "$1,199", "url": "/dell-g15-gaming"},
        {"name": "HP Chromebook 14", "price": "$299", "url": "/hp-chromebook"},
        {"name": "Lenovo IdeaPad 3 Intel UHD Graphics", "price": "$499", "url": "/lenovo-ideapad"},
        {"name": "Acer Nitro V", "price": "$899", "url": "/acer-nitro-v-rtx-4050"},
        {"name": "MacBook Air M2", "price": "$1,099", "url": "/macbook-air-m2"},
        {"name": "MSI Thin 15", "price": "$1,049", "url": "/msi-thin-15"},
        {"name": "Razer Blade 15", "price": "$2,499", "url": "/razer-blade-15-rtx-4070"},
    ]

    requirements = {
        "gpu": "NVIDIA RTX",
        "key_requirements": ["NVIDIA GPU", "16GB RAM"]
    }

    query = "gaming laptop with nvidia gpu under $2000"

    print("=" * 60)
    print("PRIORITIZATION TEST")
    print("=" * 60)
    print(f"Query: {query}")
    print(f"Candidates: {len(test_candidates)}")
    print()

    result = prioritize_candidates(test_candidates, requirements, query)

    print("\nPRIORITIZED (will verify in this order):")
    for i, p in enumerate(result.prioritized, 1):
        print(f"  {i}. {p['name']} - {p['price']}")

    print("\nREJECTED (safe to skip):")
    for p in result.rejected:
        print(f"  ✗ {p['name']} - {p.get('_rejection_reason', 'N/A')}")

    print(f"\nSTATS: {result.stats}")
