"""
orchestrator/unified_calibrator.py

DEPRECATED: This module is deprecated in favor of PageIntelligenceService.

Use the new page intelligence system instead:
    from apps.services.tool_server.page_intelligence import get_page_intelligence_service

    service = get_page_intelligence_service()
    understanding = await service.understand_page(page, url)
    items = await service.extract(page, understanding)

The new system provides:
- 3-phase pipeline (zone identification, selector generation, strategy selection)
- Multiple extraction strategies (selector, vision, hybrid, prose)
- Async-locked caching with LRU eviction
- Better error handling and debugging support

This module remains for backwards compatibility but will be removed in a future version.

---

ORIGINAL DOCUMENTATION (deprecated):

Unified Site Calibrator - Main Entry Point

LLM-driven calibration system that learns how to interact with ANY website.

The LLM:
1. Analyzes page structure and decides what elements matter
2. Creates its own extraction schema (selectors for products, prices, etc.)
3. Tests the schema and self-corrects if wrong
4. Loops until success (max 3 iterations)

This is a "programming by instruction" approach - the LLM figures out the
website and writes its own instruction manual for future use.

Usage:
    from apps.services.tool_server.unified_calibrator import UnifiedCalibrator

    calibrator = UnifiedCalibrator()

    # Get profile (from cache or by learning)
    profile = await calibrator.get_profile(page, "https://amazon.com/s?k=laptop")

    # Use learned patterns
    search_url = profile.build_search_url(query="laptop", max_price=800)
    url_context = profile.get_url_context(current_url)
"""
import warnings

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Dict, Any
from urllib.parse import urlparse

from apps.services.tool_server.calibrator.llm_calibrator import LLMCalibrator

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger("calibrator")


class UnifiedCalibrator:
    """
    DEPRECATED: Use PageIntelligenceService instead.

    LLM-Driven Site Calibrator (legacy)

    The LLM analyzes the website, creates its own extraction schema,
    tests it, and self-corrects until it works. This "instruction manual"
    is saved for future use.
    """

    def __init__(
        self,
        llm_url: str = None,
        llm_model: str = None,
        storage_path: str = None,
        max_profile_age_days: int = 7,
    ):
        """
        Initialize the calibrator.

        Args:
            llm_url: URL for LLM API
            llm_model: Model name
            storage_path: Where to store profiles (defaults to site_profiles/)
            max_profile_age_days: Profiles older than this are re-learned
        """
        warnings.warn(
            "UnifiedCalibrator is deprecated. Use PageIntelligenceService instead:\n"
            "  from apps.services.tool_server.page_intelligence import get_page_intelligence_service\n"
            "  service = get_page_intelligence_service()\n"
            "  understanding = await service.understand_page(page, url)\n"
            "  items = await service.extract(page, understanding)",
            DeprecationWarning,
            stacklevel=2
        )
        self.llm_calibrator = LLMCalibrator(llm_url=llm_url, llm_model=llm_model)
        self.storage_path = Path(storage_path) if storage_path else Path("site_profiles")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.max_profile_age_days = max_profile_age_days

    async def get_profile(
        self,
        page: 'Page',
        url: str,
        force_recalibrate: bool = False
    ) -> Dict[str, Any]:
        """
        Get site profile - from cache or by LLM learning.

        This is the main entry point. Call this before extracting from any site.

        Args:
            page: Playwright page (already navigated to the site)
            url: Current URL on the site
            force_recalibrate: If True, ignore cache and re-learn

        Returns:
            Dict with extraction schema and URL patterns
        """
        domain = self._get_domain(url)

        # Check cache first (unless force recalibrate)
        if not force_recalibrate:
            cached = self._load_schema(domain)
            if cached and self._is_valid(cached):
                logger.info(f"[Calibrator] Using cached schema for {domain}")
                return cached

            if cached:
                logger.info(f"[Calibrator] Cached schema expired for {domain}, re-learning")

        # Learn the site using LLM
        logger.info(f"[Calibrator] Learning new site: {domain}")
        schema = await self.llm_calibrator.calibrate(page, url)

        # Save if validated
        if schema.get("validated"):
            logger.info(f"[Calibrator] Saving validated schema for {domain}")
            self._save_schema(domain, schema)
        else:
            logger.warning(f"[Calibrator] Schema not validated, but saving for reference")
            self._save_schema(domain, schema)

        return schema

    def _load_schema(self, domain: str) -> Optional[Dict]:
        """Load cached schema from file."""
        path = self.storage_path / f"{domain}.json"
        if path.exists():
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[Calibrator] Failed to load schema: {e}")
        return None

    def _save_schema(self, domain: str, schema: Dict):
        """Save schema to file."""
        path = self.storage_path / f"{domain}.json"
        try:
            with open(path, 'w') as f:
                json.dump(schema, f, indent=2, default=str)
            logger.info(f"[Calibrator] Schema saved to {path}")
        except Exception as e:
            logger.error(f"[Calibrator] Failed to save schema: {e}")

    def _is_valid(self, schema: Dict) -> bool:
        """Check if cached schema is still valid."""
        learned_at = schema.get("learned_at")
        if not learned_at:
            return False

        try:
            # Parse ISO format date
            learned = datetime.fromisoformat(learned_at.replace('Z', '+00:00'))
            age_days = (datetime.now() - learned.replace(tzinfo=None)).days
            return age_days < self.max_profile_age_days
        except:
            return False

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        return domain

    def get_url_context(self, url: str) -> dict:
        """
        Get URL context using cached schema.

        Falls back to basic parsing if no schema exists.
        """
        domain = self._get_domain(url)

        # Try to load cached schema
        schema = self._load_schema(domain)
        if schema and schema.get("url_patterns"):
            patterns = schema["url_patterns"]
            from urllib.parse import parse_qs, unquote

            parsed = urlparse(url)
            params = parse_qs(parsed.query)

            context = {
                "is_filtered": False,
                "search_query": None,
                "price_filter": None,
                "source": "learned_schema"
            }

            # Use learned search param
            search_param = patterns.get("search_param")
            if search_param and search_param in params:
                context["search_query"] = unquote(params[search_param][0])

            # Use learned price param
            price_param = patterns.get("price_param")
            if price_param and price_param in params:
                try:
                    context["price_filter"] = {"raw": params[price_param][0]}
                    context["is_filtered"] = True
                except:
                    pass

            return context

        # Fallback: basic URL parsing
        return self._basic_url_context(url)

    def _basic_url_context(self, url: str) -> dict:
        """Basic URL parsing without learned patterns."""
        from urllib.parse import parse_qs, unquote

        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        context = {
            "is_filtered": False,
            "search_query": None,
            "price_filter": None,
            "page": None,
            "source": "basic_parsing"
        }

        # Common search params
        for param in ['q', 'k', 'query', 'search', 'keyword']:
            if param in params:
                context["search_query"] = unquote(params[param][0])
                break

        # Common price params
        price_params = ['price_max', 'maxPrice', 'max_price', 'price']
        for param in price_params:
            if param in params:
                try:
                    context["price_filter"] = {"max": float(params[param][0])}
                    context["is_filtered"] = True
                except ValueError:
                    pass
                break

        return context

    def delete_calibration(self, domain: str) -> bool:
        """
        Delete cached calibration for a domain.

        Used by recovery systems to force recalibration on next visit.

        Args:
            domain: Domain to delete calibration for (e.g., "amazon.com")

        Returns:
            True if deleted, False if not found
        """
        # Normalize domain
        domain = domain.lower().strip()
        if domain.startswith('www.'):
            domain = domain[4:]

        path = self.storage_path / f"{domain}.json"
        if path.exists():
            try:
                path.unlink()
                logger.info(f"[Calibrator] Deleted calibration for {domain}")
                return True
            except Exception as e:
                logger.error(f"[Calibrator] Failed to delete calibration: {e}")
        return False


# Global instance
_calibrator: Optional[UnifiedCalibrator] = None


def get_calibrator(
    llm_url: str = None,
    llm_model: str = None,
    storage_path: str = None
) -> UnifiedCalibrator:
    """Get or create the global calibrator instance."""
    global _calibrator
    if _calibrator is None:
        _calibrator = UnifiedCalibrator(
            llm_url=llm_url,
            llm_model=llm_model,
            storage_path=storage_path
        )
    return _calibrator


# Convenience function for quick URL context
def get_url_context(url: str) -> dict:
    """
    Get URL context for a URL.

    If we have a cached schema, uses learned patterns.
    Otherwise, does basic URL parsing.
    """
    calibrator = get_calibrator()
    return calibrator.get_url_context(url)
