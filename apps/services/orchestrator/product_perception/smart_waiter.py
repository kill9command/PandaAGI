"""
orchestrator/product_perception/smart_waiter.py

Unified SmartPageWaiter - Wait for page content to load before extraction.

Consolidates wait logic from:
- research_orchestrator._wait_for_google_results() (15s, 9 selectors)
- pdp_extractor._wait_for_price_content() (10s, 12 selectors)
- pipeline._wait_for_listing_content() (10s, 16 selectors)

Key improvement: Uses schema.wait_selector when available (learned from calibration).
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from apps.services.orchestrator.shared_state.site_schema_registry import SiteSchema

logger = logging.getLogger(__name__)


class PageType(Enum):
    """Page types for smart wait configuration."""
    LISTING = "listing"
    PDP = "pdp"
    SEARCH_RESULTS = "search_results"
    ARTICLE = "article"
    GENERIC = "generic"


@dataclass
class WaitConfig:
    """Configuration for page wait behavior."""
    timeout_ms: int = 10000        # Max wait time
    poll_interval_ms: int = 300    # How often to check selectors
    min_wait_ms: int = 500         # Minimum wait after detection
    min_elements: int = 1          # Minimum elements to find


@dataclass
class WaitResult:
    """Result of a wait operation."""
    success: bool
    selector_used: Optional[str] = None
    elements_found: int = 0
    wait_time_ms: float = 0
    method: str = "unknown"  # "schema", "page_type", "fallback", "timeout"


class SmartPageWaiter:
    """
    Unified smart wait for any page type.

    Uses tiered approach:
    1. Schema wait_selector (if available) - learned from calibration
    2. Page-type specific selectors - known patterns for each page type
    3. Universal fallbacks - count elements, check body text
    """

    # Page-type specific selectors (fallback when no schema)
    PAGE_TYPE_SELECTORS = {
        PageType.LISTING: [
            # Generic product containers
            '[data-sku]',
            '[data-product-id]',
            '[data-item-id]',
            '.product-card',
            '.product-item',
            '.sku-item',
            '.item-cell',
            '.s-result-item',
            'li[data-asin]',
            '.srp-results .s-item',
            '[class*="ProductCard"]',
            '[class*="product-tile"]',
            'article[data-component-type="s-search-result"]',
        ],
        PageType.PDP: [
            '[data-testid*="price"]',
            '[class*="price"]',
            '[class*="Price"]',
            '[itemprop="price"]',
            '.priceView-hero-price',
            '.price-characteristic',
            '#priceblock_ourprice',
            '.a-price-whole',
            '.product-price',
            '[data-price]',
        ],
        PageType.SEARCH_RESULTS: [
            'div.g',
            'div.MjjYud',
            'div[data-hveid]',
            'div.sh-dgr__content',
            'div.commercial-unit-desktop-top',
            'div[data-attrid]',
            'div.xpdopen',
            'h3.LC20lb',
            'div.yuRUbf',
            '#search',
        ],
        PageType.ARTICLE: [
            'article',
            '.article-content',
            '.post-content',
            '[role="article"]',
            'main',
        ],
        PageType.GENERIC: [
            'main',
            '#content',
            '.content',
            'article',
            '[role="main"]',
        ],
    }

    # Default wait configs by page type
    DEFAULT_CONFIGS = {
        PageType.LISTING: WaitConfig(timeout_ms=10000, min_elements=2),
        PageType.PDP: WaitConfig(timeout_ms=10000, min_elements=1),
        PageType.SEARCH_RESULTS: WaitConfig(timeout_ms=15000, min_elements=3),
        PageType.ARTICLE: WaitConfig(timeout_ms=5000, min_elements=1),
        PageType.GENERIC: WaitConfig(timeout_ms=5000, min_elements=1),
    }

    async def wait_for_content(
        self,
        page: 'Page',
        page_type: PageType,
        schema: Optional['SiteSchema'] = None,
        config: Optional[WaitConfig] = None
    ) -> WaitResult:
        """
        Wait for page content to load.

        Args:
            page: Playwright page object
            page_type: Type of page we're waiting for
            schema: Optional SiteSchema with learned wait_selector
            config: Optional custom wait configuration

        Returns:
            WaitResult with success status and details
        """
        cfg = config or self.DEFAULT_CONFIGS.get(page_type, WaitConfig())
        start_time = time.time()

        # Strategy 1: Use schema wait_selector if available (fastest, learned)
        if schema and hasattr(schema, 'wait_selector') and schema.wait_selector:
            result = await self._wait_for_selector(
                page,
                schema.wait_selector,
                cfg,
                min_elements=getattr(schema, 'wait_min_count', cfg.min_elements)
            )
            if result.success:
                result.method = "schema"
                result.wait_time_ms = (time.time() - start_time) * 1000
                return result

        # Strategy 2: Try page-type specific selectors
        selectors = self.PAGE_TYPE_SELECTORS.get(page_type, [])
        for selector in selectors:
            # Check timeout
            elapsed = (time.time() - start_time) * 1000
            if elapsed >= cfg.timeout_ms:
                break

            remaining_timeout = cfg.timeout_ms - elapsed
            temp_cfg = WaitConfig(
                timeout_ms=min(2000, remaining_timeout),  # 2s per selector
                min_elements=cfg.min_elements
            )

            result = await self._wait_for_selector(page, selector, temp_cfg)
            if result.success:
                result.method = "page_type"
                result.wait_time_ms = (time.time() - start_time) * 1000
                logger.info(f"[SmartWait] ✓ Content found: {selector} ({result.elements_found} elements)")
                return result

        # Strategy 3: Universal fallbacks
        result = await self._universal_fallback(page, page_type, cfg)
        result.wait_time_ms = (time.time() - start_time) * 1000
        if result.success:
            result.method = "fallback"
            return result

        # Timeout fallback
        remaining = cfg.timeout_ms - (time.time() - start_time) * 1000
        if remaining > 0:
            logger.warning(f"[SmartWait] No selectors matched, waiting {min(remaining, 3000):.0f}ms")
            await asyncio.sleep(min(remaining, 3000) / 1000.0)

        return WaitResult(
            success=False,
            wait_time_ms=(time.time() - start_time) * 1000,
            method="timeout"
        )

    async def _wait_for_selector(
        self,
        page: 'Page',
        selector: str,
        config: WaitConfig,
        min_elements: int = None
    ) -> WaitResult:
        """Wait for a specific selector to appear."""
        min_els = min_elements or config.min_elements
        try:
            locator = page.locator(selector)
            count = await locator.count()

            if count >= min_els:
                # Elements exist, verify visibility
                try:
                    await locator.first.wait_for(state='visible', timeout=config.timeout_ms)
                    await asyncio.sleep(config.min_wait_ms / 1000.0)
                    return WaitResult(
                        success=True,
                        selector_used=selector,
                        elements_found=count
                    )
                except Exception:
                    pass  # Not visible yet
        except Exception:
            pass

        return WaitResult(success=False, selector_used=selector)

    async def _universal_fallback(
        self,
        page: 'Page',
        page_type: PageType,
        config: WaitConfig
    ) -> WaitResult:
        """Universal fallback when no specific selectors match."""
        try:
            if page_type == PageType.SEARCH_RESULTS:
                # Check for h3 elements (universal for search results)
                h3_count = await page.evaluate('document.querySelectorAll("h3").length')
                if h3_count >= 3:
                    logger.info(f"[SmartWait] ✓ Fallback: Found {h3_count} h3 elements")
                    await asyncio.sleep(config.min_wait_ms / 1000.0)
                    return WaitResult(success=True, elements_found=h3_count)

            elif page_type == PageType.LISTING:
                # Check for multiple price patterns
                body_text = await page.locator('body').text_content()
                if body_text:
                    price_count = body_text.count('$')
                    if price_count >= 3:
                        logger.info(f"[SmartWait] ✓ Fallback: Found {price_count} price patterns")
                        await asyncio.sleep(config.min_wait_ms / 1000.0)
                        return WaitResult(success=True, elements_found=price_count)

            elif page_type == PageType.PDP:
                # Check for $ in body text + h1/h2 (price + title)
                body_text = await page.locator('body').text_content()
                has_price = body_text and '$' in body_text
                h1_count = await page.evaluate('document.querySelectorAll("h1, h2").length')
                if has_price and h1_count > 0:
                    logger.info(f"[SmartWait] ✓ Fallback: Found price + {h1_count} headings")
                    await asyncio.sleep(config.min_wait_ms / 1000.0)
                    return WaitResult(success=True, elements_found=1)

        except Exception as e:
            logger.debug(f"[SmartWait] Fallback check failed: {e}")

        return WaitResult(success=False)


# Global instance
_smart_waiter: SmartPageWaiter = None


def get_smart_waiter() -> SmartPageWaiter:
    """Get global SmartPageWaiter instance."""
    global _smart_waiter
    if _smart_waiter is None:
        _smart_waiter = SmartPageWaiter()
    return _smart_waiter
