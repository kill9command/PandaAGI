"""
orchestrator/purchasing_mcp.py

High-level purchasing helper that bundles together commerce-related lookups.
Exposes a single `lookup` helper so Gateway/Coordinator can call one MCP tool
and receive normalized offers along with a best-offer suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from apps.services.tool_server import commerce_mcp
from apps.services.tool_server.species_taxonomy import validate_species_match  # Available if needed


@dataclass
class PurchasingResult:
    query: str
    extra_query: str
    offers: List[Dict[str, Any]]
    best_offer: Optional[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "extra_query": self.extra_query,
            "offers": self.offers,
            "best_offer": self.best_offer,
            "total": len(self.offers),
        }


def lookup(
    query: str,
    *,
    max_results: int = 6,
    extra_query: str = "",
    country: str = "us",
    language: str = "en",
    pause: float = 0.6,
    user_id: str | None = None,
) -> Dict[str, Any]:
    """
    Run a commerce lookup (SerpAPI shopping) and return normalized offers.

    If the first pass with extra_query returns nothing, retry once without the
    extra query so we still return whatever is available for the base subject.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")

    primary = commerce_mcp.search_offers(
        query.strip(),
        user_id=user_id,
        max_results=max_results,
        extra_query=extra_query or "",
        country=country or "us",
        language=language or "en",
        pause=pause,
    )
    offers = primary[: max(1, max_results)]

    if not offers and extra_query:
        fallback = commerce_mcp.search_offers(
            query.strip(),
            user_id=user_id,
            max_results=max_results,
            extra_query="",
            country=country or "us",
            language=language or "en",
            pause=pause,
        )
        offers = fallback[: max(1, max_results)]

    best = commerce_mcp.best_offer(offers) if offers else None
    return PurchasingResult(
        query=query.strip(),
        extra_query=extra_query or "",
        offers=offers,
        best_offer=best,
    ).to_dict()
