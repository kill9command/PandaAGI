"""
orchestrator/retailer_selector.py

Dynamic retailer selection for Phase 2 shopping queries.
Uses Phase 1 intelligence to discover relevant retailers - NO HARDCODING.

Integrates with VendorRegistry to:
- Filter out vendors that are blocked (block us)
- Prioritize vendors with proven success rates
- Learn from experience which vendors work

Created: 2025-11-24
Updated: 2025-11-26 - Removed hardcoded retailers, now intelligence-driven
Updated: 2025-12-01 - Integrated with VendorRegistry for dynamic vendor learning
"""

import logging
from typing import List, Dict, Any, Optional

from apps.services.tool_server.shared_state.vendor_registry import get_vendor_registry

logger = logging.getLogger(__name__)


async def select_retailers_for_query(
    query: str,
    intelligence: Dict[str, Any] = None,
    max_retailers: int = 3
) -> List[str]:
    """
    Select retailers to visit based on Phase 1 intelligence.

    INTELLIGENCE-DRIVEN APPROACH:
    1. Primary: Use retailers discovered in Phase 1 intelligence
    2. Fallback: If no retailers found, return empty list (caller should
       use generic search instead of visiting specific retailers)

    Args:
        query: Shopping query
        intelligence: Phase 1 intelligence (should contain retailers_mentioned)
        max_retailers: Maximum number of retailers to visit

    Returns:
        List of retailer domains discovered from intelligence, or empty list
    """
    intelligence = intelligence or {}

    # Extract retailers from Phase 1 intelligence
    retailers_mentioned = intelligence.get("retailers_mentioned", [])

    # Also check alternative field names the LLM might use
    if not retailers_mentioned:
        retailers_mentioned = intelligence.get("recommended_retailers", [])
    if not retailers_mentioned:
        retailers_mentioned = intelligence.get("stores", [])
    if not retailers_mentioned:
        retailers_mentioned = intelligence.get("vendors", [])

    if retailers_mentioned:
        logger.info(f"[RetailerSelect] Intelligence discovered {len(retailers_mentioned)} retailers: {retailers_mentioned}")

        # Get vendor registry to filter blocked vendors
        registry = get_vendor_registry()

        # Normalize, deduplicate, and filter blocked vendors
        selected = []
        blocked_skipped = []
        for retailer in retailers_mentioned:
            domain = _normalize_retailer_to_domain(retailer)
            if domain and domain not in selected:
                # Check if vendor is blocked
                if registry.is_blocked(domain):
                    blocked_skipped.append(domain)
                    logger.info(f"[RetailerSelect] Skipping blocked vendor: {domain}")
                    continue

                # Register this vendor (learned from Phase 1 intelligence)
                registry.add_or_update(
                    domain=domain,
                    discovered_via="phase1_intelligence",
                    discovery_query=query
                )

                selected.append(domain)
                if len(selected) >= max_retailers:
                    break

        if blocked_skipped:
            logger.info(f"[RetailerSelect] Skipped {len(blocked_skipped)} blocked vendors: {blocked_skipped}")

        logger.info(f"[RetailerSelect] Selected {len(selected)} retailers from intelligence: {selected}")
        return selected
    else:
        # No retailers discovered in Phase 1
        # Return empty list - caller should fall back to Google search
        # which dynamically discovers vendor pages
        logger.warning(
            f"[RetailerSelect] No retailers discovered in Phase 1 intelligence. "
            f"Phase 2 will use Google search to discover vendors dynamically."
        )
        return []


def _normalize_retailer_to_domain(retailer_name: str) -> Optional[str]:
    """
    Normalize retailer name to domain format.

    Handles various formats:
        "Best Buy" → "bestbuy.com"
        "amazon" → "amazon.com"
        "Newegg.com" → "newegg.com"
        "https://www.chewy.com/path" → "chewy.com"
        "petco.com" → "petco.com"
    """
    from urllib.parse import urlparse

    if not retailer_name:
        return None

    name = retailer_name.strip()

    # If it looks like a URL, extract the domain
    if name.startswith("http://") or name.startswith("https://") or "://" in name:
        try:
            parsed = urlparse(name)
            domain = parsed.netloc.lower()
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            if domain:
                logger.debug(f"[RetailerSelect] Extracted domain from URL: '{retailer_name}' → '{domain}'")
                return domain
        except Exception:
            pass

    # If it already looks like a domain (contains dot)
    if "." in name and " " not in name:
        domain = name.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        logger.debug(f"[RetailerSelect] Already a domain: '{retailer_name}' → '{domain}'")
        return domain

    # Clean the name: lowercase, remove spaces
    name_clean = name.lower().replace(" ", "").replace("-", "").replace("'", "")

    # Common retailer name mappings (for brand names that don't match domain)
    known_mappings = {
        "bestbuy": "bestbuy.com",
        "homedepot": "homedepot.com",
        "thd": "homedepot.com",  # Common abbreviation
        "microcenter": "microcenter.com",
        "bhphoto": "bhphotovideo.com",
        "bh": "bhphotovideo.com",
    }

    if name_clean in known_mappings:
        domain = known_mappings[name_clean]
        logger.debug(f"[RetailerSelect] Known mapping: '{retailer_name}' → '{domain}'")
        return domain

    # Default: assume retailer name is the domain without .com
    # This handles: "amazon" → "amazon.com", "chewy" → "chewy.com", etc.
    domain = f"{name_clean}.com"
    logger.debug(f"[RetailerSelect] Inferred domain: '{retailer_name}' → '{domain}'")
    return domain
