"""
ProductPerceptionPipeline - Main orchestrator for hybrid vision+HTML extraction.

Combines HTML extraction (for URLs) with Vision extraction (for product data)
to create a robust, universal product extraction system.
"""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING, Tuple, Any, Union, Dict
from urllib.parse import urlparse

import httpx

from .models import FusedProduct, ExtractionResult, HTMLCandidate
from .config import get_config, PerceptionConfig
from .html_extractor import HTMLExtractor
from .vision_extractor import VisionExtractor
from .fusion import ProductFusion, match_html_only
from .resolver import URLResolver
from .pdp_extractor import PDPExtractor
from .product_verifier import ProductVerifier, VerifiedProduct

# Candidate prioritization for smart PDP verification
from apps.services.tool_server.candidate_prioritizer import prioritize_candidates, should_continue_verification

# Schema-based extraction components
from apps.services.tool_server.shared_state.site_schema_registry import (
    SiteSchema,
    get_schema_registry
)
# Using PageIntelligence adapter for backwards compatibility
from apps.services.tool_server.page_intelligence.legacy_adapter import get_smart_calibrator, ExtractionSchema
from apps.services.tool_server.shared_state.site_health_tracker import get_health_tracker

if TYPE_CHECKING:
    from playwright.async_api import Page

from apps.services.tool_server.shared.llm_utils import load_prompt_via_recipe as _load_prompt_via_recipe

logger = logging.getLogger(__name__)


class ProductPerceptionPipeline:
    """
    Hybrid product extraction using HTML + Vision.

    Strategy:
    1. Capture HTML + Screenshot in parallel
    2. Extract from both in parallel (HTML for URLs, Vision for products)
    3. Fuse results (match vision products to HTML URLs)
    4. Click-resolve any products without URLs (fallback)

    This approach is:
    - More reliable than HTML-only (vision works on any layout)
    - Faster than vision-only (HTML provides URLs directly)
    - Universal (no retailer-specific selectors needed)

    Special handling:
    - PDP (Product Detail Page) detection: When on a single product page,
      uses PDPExtractor to get product data instead of searching for product links.
    """

    # URL patterns that indicate a Product Detail Page (PDP)
    PDP_URL_PATTERNS = [
        r'/dp/[A-Z0-9]{10}',           # Amazon ASIN
        r'/gp/product/[A-Z0-9]+',      # Amazon alt
        r'/product/[\w-]+',            # Best Buy /product/... style
        r'/site/[^/]+/\d+\.p',         # Best Buy old style /site/xxx/12345.p
        r'/ip/[\d]+',                  # Walmart /ip/123456
        r'/products/[\w-]+\.html',     # Generic /products/slug.html
        r'/pd/[\w-]+',                 # Target /pd/...
        r'/p/[\w-]+/[\w-]+',           # Newegg /p/xxx/yyy
        r'/item/[\w-]+/[\d]+',         # Newegg /item/N82E/123456
        # HP product pages
        r'/shop/custom/[\w-]+-[\w-]+', # HP /shop/custom/product-name-variant
        r'/shop/pdp/[\w-]+',           # HP /shop/pdp/product-name
        r'/shop/slp/[\w-]+',           # HP laptop landing pages with product
        # Generic product-specific indicators
        r'\?catEntryId=\d+',           # IBM/HP WebSphere Commerce product IDs
        r'/sku/\d+',                   # SKU-based product pages
    ]

    # URL patterns that indicate search/listing pages (NOT PDPs)
    SEARCH_URL_PATTERNS = [
        r'/search',
        r'/s\?',                       # Amazon search
        r'/browse/',
        r'/category/',
        r'/c/',
        r'/shop/$',                    # Only /shop/ at end (not /shop/custom/product)
        r'/shop/browse',               # HP category browsing
        r'/shop/sitemap',              # HP sitemap
        r'/results',
        r'[?&]q=',                     # Query parameter
        r'[?&]keyword=',
        r'[?&]search=',
    ]

    def __init__(
        self,
        llm_url: str = None,
        llm_model: str = None,
        llm_api_key: str = None,
        config: PerceptionConfig = None,
        ocr_engine=None,
    ):
        """
        Initialize the perception pipeline.

        Args:
            llm_url: LLM service URL (default from env)
            llm_model: LLM model ID (default from env)
            llm_api_key: LLM API key (default from env)
            config: Pipeline configuration (default from env)
            ocr_engine: Pre-initialized PaddleOCR engine (optional)
        """
        self.config = config or get_config()

        # LLM settings (with env fallbacks)
        # Note: VisionExtractor expects base URL (without /v1/chat/completions suffix)
        solver_url = llm_url or os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        # Strip the endpoint path if present - VisionExtractor adds it internally
        if solver_url.endswith("/v1/chat/completions"):
            self.llm_url = solver_url.rsplit("/v1/chat/completions", 1)[0]
        else:
            self.llm_url = solver_url
        self.llm_model = llm_model or os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        self.llm_api_key = llm_api_key or os.getenv("SOLVER_API_KEY", "qwen-local")

        # Initialize components
        self.html_extractor = HTMLExtractor()
        self.vision_extractor = VisionExtractor(
            llm_url=self.llm_url,
            llm_model=self.llm_model,
            llm_api_key=self.llm_api_key,
            ocr_engine=ocr_engine
        )
        self.fusion = ProductFusion()

        # Initialize PDP extractor for price verification
        self.pdp_extractor = PDPExtractor() if self.config.enable_pdp_verification else None

        # Initialize resolver with PDP extractor for inline verification
        self.resolver = URLResolver(
            pdp_extractor=self.pdp_extractor
        ) if self.config.enable_click_resolve else None

        # Compile PDP detection patterns
        self._pdp_patterns = [re.compile(p, re.IGNORECASE) for p in self.PDP_URL_PATTERNS]
        self._search_patterns = [re.compile(p, re.IGNORECASE) for p in self.SEARCH_URL_PATTERNS]

    def _is_pdp_by_url(self, url: str) -> Optional[bool]:
        """
        Quick URL-based PDP detection. Returns None if inconclusive.

        Args:
            url: Page URL to check

        Returns:
            True if definitely PDP, False if definitely search, None if unknown
        """
        # Check PDP URL patterns FIRST (they're more specific)
        for pattern in self._pdp_patterns:
            if pattern.search(url):
                logger.debug(f"[Pipeline] URL pattern matches PDP: {url[:60]}...")
                return True

        # Then check for search page indicators
        for pattern in self._search_patterns:
            if pattern.search(url):
                logger.debug(f"[Pipeline] URL pattern matches search: {url[:60]}...")
                return False

        return None  # Inconclusive

    async def _classify_page_with_vision(self, page: 'Page', url: str) -> bool:
        """
        Use page analysis to classify as PDP or listing.

        This is the universal fallback when URL patterns don't match.
        Works on any retailer without needing specific URL patterns.

        Strategy:
        1. Check HTML for PDP indicators (Add to Cart, single product structure)
        2. Use OCR to count distinct product price patterns
        3. Single price with Add to Cart = PDP, multiple prices in grid = listing

        Args:
            page: Playwright page object
            url: Current URL (for logging)

        Returns:
            True if page appears to be a PDP (single product)
        """
        try:
            # Get page HTML for analysis
            html = await page.content()
            html_lower = html.lower()

            # PDP indicators in HTML
            pdp_signals = 0
            listing_signals = 0

            # Check for Add to Cart / Buy Now buttons (strong PDP signal)
            add_to_cart_patterns = [
                'add to cart', 'add-to-cart', 'addtocart',
                'buy now', 'buy-now', 'buynow',
                'add to bag', 'add-to-bag',
                'add to basket',
            ]
            for pattern in add_to_cart_patterns:
                if pattern in html_lower:
                    pdp_signals += 2
                    break

            # Check for product detail structures
            if 'itemprop="product"' in html_lower or 'itemtype="http://schema.org/product"' in html_lower:
                pdp_signals += 2
            if 'product-detail' in html_lower or 'pdp-' in html_lower or 'product-page' in html_lower:
                pdp_signals += 1

            # Check for listing/search page structures
            if 'search-results' in html_lower or 'product-grid' in html_lower or 'product-list' in html_lower:
                listing_signals += 2
            if 'filter' in html_lower and ('price' in html_lower or 'brand' in html_lower):
                listing_signals += 1
            if 'pagination' in html_lower or 'load more' in html_lower or 'page=' in html_lower:
                listing_signals += 1

            # Count price patterns in visible text (multiple = listing)
            price_pattern = re.compile(r'\$[\d,]+\.?\d{0,2}')
            # Get just the body text, not all HTML
            body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
            if body_match:
                body_text = re.sub(r'<[^>]+>', ' ', body_match.group(1))  # Strip HTML tags
                prices = price_pattern.findall(body_text)
                unique_prices = len(set(prices))

                if unique_prices == 1:
                    pdp_signals += 2  # Single price = likely PDP
                elif unique_prices > 3:
                    listing_signals += 2  # Many prices = likely listing

            # Decision
            is_pdp = pdp_signals > listing_signals

            logger.info(
                f"[Pipeline] Page analysis: PDP signals={pdp_signals}, "
                f"listing signals={listing_signals} → {'PDP' if is_pdp else 'LISTING'}: {url[:60]}..."
            )
            return is_pdp

        except Exception as e:
            logger.warning(f"[Pipeline] Page classification error: {e}")

        # Default to listing page (safer - will try to click-verify)
        return False

    async def _is_pdp(self, url: str, page: 'Page' = None) -> bool:
        """
        Detect if page is a Product Detail Page (PDP) vs a search/listing page.

        Uses a two-tier approach:
        1. Quick URL pattern matching (instant, no cost)
        2. Vision-based classification if URL inconclusive (universal, works on any site)

        Args:
            url: Page URL to check
            page: Playwright page for vision classification (optional)

        Returns:
            True if URL appears to be a PDP
        """
        # Tier 1: Quick URL pattern check
        url_result = self._is_pdp_by_url(url)
        if url_result is not None:
            logger.info(f"[Pipeline] URL pattern detected {'PDP' if url_result else 'listing'}: {url[:60]}...")
            return url_result

        # Tier 2: Vision-based classification (when URL patterns inconclusive)
        if page is not None:
            logger.info(f"[Pipeline] URL inconclusive, using vision to classify: {url[:60]}...")
            return await self._classify_page_with_vision(page, url)

        # No page available, assume listing (safer)
        logger.debug(f"[Pipeline] URL inconclusive, no page for vision, assuming listing: {url[:60]}...")
        return False

    async def _extract_from_pdp(
        self,
        page: 'Page',
        url: str,
        query: str
    ) -> ExtractionResult:
        """
        Extract product data when on a PDP (Product Detail Page).

        Uses PDPExtractor to get the main product's info instead of
        searching for product links (which would return navigation).

        Args:
            page: Playwright page object
            url: PDP URL
            query: User's search query

        Returns:
            ExtractionResult with single product
        """
        start_time = time.time()
        errors = []

        logger.info(f"[Pipeline] PDP extraction from {url[:60]}...")

        # Ensure we have a PDP extractor
        if not self.pdp_extractor:
            self.pdp_extractor = PDPExtractor()

        try:
            # Extract product data from PDP
            pdp_data = await self.pdp_extractor.extract(page, url)

            if pdp_data and pdp_data.price is not None:
                # Get vendor from URL
                vendor = urlparse(url).netloc
                if vendor.startswith("www."):
                    vendor = vendor[4:]

                # Create FusedProduct from PDP data
                product = FusedProduct(
                    title=pdp_data.title or "Unknown Product",
                    price=pdp_data.price,
                    price_str=f"${pdp_data.price:.2f}" if pdp_data.price else "",
                    url=url,
                    vendor=vendor,
                    confidence=pdp_data.extraction_confidence or 0.9,
                    extraction_method="pdp_direct",
                    vision_verified=False,
                    url_source="pdp",
                    bbox=None,
                    match_score=1.0,
                    pdp_verified=True,
                    original_price=pdp_data.original_price,
                )

                logger.info(
                    f"[Pipeline] PDP extraction successful: {product.title[:50]}... "
                    f"${product.price} via {pdp_data.extraction_source}"
                )

                return ExtractionResult(
                    products=[product],
                    html_candidates_count=0,
                    vision_products_count=0,
                    fusion_matches=0,
                    click_resolved=0,
                    pdp_verified=1,
                    price_discrepancies=0,
                    extraction_time_ms=(time.time() - start_time) * 1000,
                    errors=[]
                )
            else:
                logger.warning(f"[Pipeline] PDP extraction failed to get price from {url[:60]}...")
                errors.append("PDP extraction failed to get price")

        except Exception as e:
            logger.error(f"[Pipeline] PDP extraction error: {e}")
            errors.append(f"PDP extraction error: {str(e)}")

        # If PDP extraction failed, return empty result
        # (falling back to HTML would give navigation links which is wrong)
        return ExtractionResult(
            products=[],
            html_candidates_count=0,
            vision_products_count=0,
            fusion_matches=0,
            click_resolved=0,
            extraction_time_ms=(time.time() - start_time) * 1000,
            errors=errors
        )

    async def extract(
        self,
        page: 'Page',
        url: str,
        query: str,
    ) -> List[FusedProduct]:
        """
        Main entry point - extracts products from retailer page.

        Args:
            page: Playwright page object (already navigated to retailer)
            url: Current page URL
            query: User's search query (for context)

        Returns:
            List of FusedProduct with verified URLs
        """
        result = await self.extract_with_stats(page, url, query)
        return result.products

    async def extract_with_stats(
        self,
        page: 'Page',
        url: str,
        query: str,
    ) -> ExtractionResult:
        """
        Extract products with full statistics.

        Args:
            page: Playwright page object
            url: Current page URL
            query: User's search query

        Returns:
            ExtractionResult with products and extraction stats
        """
        start_time = time.time()
        errors = []

        logger.info(f"[Pipeline] Starting extraction from {url}")

        # Step 0: Detect if this is a PDP (Product Detail Page)
        # PDPs need different extraction strategy - get the single product's data
        # instead of searching for product links (which would return navigation)
        # Uses URL patterns first, falls back to vision classification if needed
        if await self._is_pdp(url, page):
            return await self._extract_from_pdp(page, url, query)

        logger.info(f"[Pipeline] Using hybrid extraction (search/listing page)")

        screenshot_path = None
        try:
            # Step 1: Parallel capture (HTML + Screenshot) with smart wait
            html, screenshot_path = await self._capture(page, url)

            if not html:
                errors.append("Failed to capture HTML")
                return ExtractionResult(
                    products=[],
                    html_candidates_count=0,
                    vision_products_count=0,
                    fusion_matches=0,
                    click_resolved=0,
                    extraction_time_ms=(time.time() - start_time) * 1000,
                    errors=errors
                )

            # Step 2: Parallel extraction
            html_candidates, vision_products = await self._extract_parallel(
                html, screenshot_path, url, query
            )

            logger.info(
                f"[Pipeline] Extraction complete: "
                f"{len(html_candidates)} HTML candidates, "
                f"{len(vision_products)} vision products"
            )

            # Step 3: Decide extraction strategy
            if vision_products:
                # Full hybrid: fuse vision with HTML
                fused = self.fusion.match(vision_products, html_candidates, url)
                fusion_matches = sum(1 for p in fused if p.url_source != "fallback")
            elif html_candidates:
                # Vision failed, fall back to HTML-only
                logger.warning("[Pipeline] Vision extraction failed, using HTML-only")
                fused = match_html_only(html_candidates, url)
                fusion_matches = 0
            else:
                # Both failed
                logger.error("[Pipeline] Both HTML and vision extraction failed")
                fused = []
                fusion_matches = 0

            # Step 4: Click-resolve unmatched products (if enabled)
            # This also performs PDP verification to get accurate prices
            click_resolved = 0
            if self.resolver and fused:
                unresolved = [p for p in fused if p.url_source == "fallback"]
                if unresolved:
                    click_resolved = await self.resolver.resolve(page, fused)

            # Count PDP verifications and price discrepancies
            pdp_verified = sum(1 for p in fused if p.pdp_verified)
            price_discrepancies = sum(
                1 for p in fused
                if p.price_discrepancy is not None and p.price_discrepancy > 0.01
            )

            extraction_time = (time.time() - start_time) * 1000

            logger.info(
                f"[Pipeline] Complete: {len(fused)} products, "
                f"{fusion_matches} fused, {click_resolved} click-resolved, "
                f"{pdp_verified} PDP-verified, {price_discrepancies} price-discrepancies, "
                f"{extraction_time:.0f}ms"
            )

            return ExtractionResult(
                products=fused,
                html_candidates_count=len(html_candidates),
                vision_products_count=len(vision_products),
                fusion_matches=fusion_matches,
                click_resolved=click_resolved,
                pdp_verified=pdp_verified,
                price_discrepancies=price_discrepancies,
                extraction_time_ms=extraction_time,
                errors=errors
            )

        except Exception as e:
            logger.error(f"[Pipeline] Extraction failed: {e}")
            errors.append(str(e))

            # Try HTML-only fallback
            if self.config.fallback_to_html_only:
                try:
                    logger.info("[Pipeline] Attempting HTML-only fallback")
                    html = await page.content()
                    html_candidates = await self.html_extractor.extract(html, url)
                    fused = match_html_only(html_candidates, url)

                    return ExtractionResult(
                        products=fused,
                        html_candidates_count=len(html_candidates),
                        vision_products_count=0,
                        fusion_matches=0,
                        click_resolved=0,
                        extraction_time_ms=(time.time() - start_time) * 1000,
                        errors=errors + ["Fallback to HTML-only"]
                    )
                except Exception as e2:
                    errors.append(f"HTML fallback failed: {e2}")

            return ExtractionResult(
                products=[],
                html_candidates_count=0,
                vision_products_count=0,
                fusion_matches=0,
                click_resolved=0,
                extraction_time_ms=(time.time() - start_time) * 1000,
                errors=errors
            )

        finally:
            # Always cleanup temp screenshot file
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    os.remove(screenshot_path)
                except OSError as e:
                    logger.warning(f"[Pipeline] Failed to cleanup temp file {screenshot_path}: {e}")

    async def _wait_for_listing_content(self, page: 'Page', url: str, timeout: float = 10.0) -> bool:
        """
        Wait for product listing content to appear on the page.

        Similar to _wait_for_price_content in PDPExtractor and _wait_for_google_results
        in research_orchestrator, but optimized for product listing pages.

        Waits for common product card/grid selectors, then verifies at least 2 products
        are visible before continuing.

        Returns True if listing content found, False if timeout.
        """
        import time
        start = time.time()

        # Common product listing selectors across retailers
        listing_selectors = [
            # Generic product containers
            '[data-sku]',                          # SKU-based (BestBuy, Newegg)
            '[data-product-id]',                   # Product ID based
            '[data-item-id]',                      # Item ID (eBay, Walmart)
            '.product-card',                       # Common class
            '.product-item',                       # Common class
            '.sku-item',                           # BestBuy
            '.item-cell',                          # Newegg
            '.s-result-item',                      # Amazon
            'li[data-asin]',                       # Amazon ASIN
            '.srp-results .s-item',                # eBay search results
            '[class*="ProductCard"]',              # React-style naming
            '[class*="product-tile"]',             # Tile layouts
            'article[data-component-type="s-search-result"]',  # Amazon modern
            # Grid containers with items
            '.products-grid > *',                  # Grid layout children
            '.product-grid > *',                   # Alt grid naming
            '.search-results > *',                 # Search result items
        ]

        logger.info(f"[Pipeline] Waiting for listing content to load...")

        # Try each selector with short timeout
        for selector in listing_selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                if count >= 2:  # Need at least 2 products for a valid listing
                    # Verify elements are visible AND have actual content
                    try:
                        await locator.first.wait_for(state='visible', timeout=2000)

                        # CRITICAL: Check for actual text content (not just empty containers)
                        # This catches lazy-loaded pages where elements exist but content hasn't loaded
                        items_with_content = 0
                        for i in range(min(count, 5)):  # Check first 5 items
                            try:
                                item = locator.nth(i)
                                text = await item.text_content()
                                # Valid product card should have substantial text (title, price, etc.)
                                if text and len(text.strip()) > 20:
                                    items_with_content += 1
                            except Exception:
                                continue

                        if items_with_content >= 2:
                            logger.info(f"[Pipeline] ✓ Listing content found: {selector} ({count} items, {items_with_content} with content)")
                            # Brief wait for render stabilization
                            await asyncio.sleep(0.5)
                            return True
                        else:
                            logger.debug(f"[Pipeline] {selector}: {count} items but only {items_with_content} have content (lazy loading?)")
                            # Continue checking - content may still be loading
                    except Exception:
                        pass  # Elements exist but not visible, try next
            except Exception:
                continue

            # Check timeout
            if time.time() - start > timeout:
                break

        # Fallback: look for multiple price patterns in page text
        try:
            body_text = await page.locator('body').text_content()
            if body_text:
                body_lower = body_text.lower()

                # FIRST: Check for explicit "no results" messages
                # This catches pages that legitimately have 0 products
                no_results_phrases = [
                    'we found 0 items',
                    'found 0 items',
                    '0 items found',
                    '0 results',
                    'no items found',
                    'no results found',
                    'no products found',
                    'no matching products',
                    'sorry, no results',
                    'nothing matched your search',
                    'did not match any products',
                    'no items match',
                    'we couldn\'t find',
                    'we have found 0 items',
                ]
                for phrase in no_results_phrases:
                    if phrase in body_lower:
                        logger.warning(f"[Pipeline] Detected 'no results' page: '{phrase}'")
                        # Return False but store metadata about why
                        return False

                # Count $ signs as proxy for products
                price_count = body_text.count('$')
                if price_count >= 3:  # At least 3 prices suggests multiple products
                    logger.info(f"[Pipeline] Found {price_count} price patterns, continuing...")
                    await asyncio.sleep(0.5)
                    return True
        except Exception:
            pass

        # Last resort: wait remaining time for JS render
        remaining = timeout - (time.time() - start)
        if remaining > 0:
            logger.info(f"[Pipeline] No listing selector found, waiting {remaining:.1f}s for render...")
            await asyncio.sleep(min(remaining, 3.0))

        return False

    async def _capture(self, page: 'Page', url: str = None) -> tuple:
        """
        Capture HTML and screenshot in parallel.

        Args:
            page: Playwright page object
            url: Optional URL for smart wait (enables listing content wait)

        Returns:
            Tuple of (html_content, screenshot_path)
        """
        # Generate temp path for screenshot
        screenshot_path = f"/tmp/product_perception_{uuid.uuid4().hex[:8]}.png"

        try:
            # Scroll to top to ensure consistent viewport coordinates
            await page.evaluate("window.scrollTo(0, 0)")

            # Smart wait for listing content if URL provided
            if url:
                await self._wait_for_listing_content(page, url, timeout=10.0)
            else:
                await asyncio.sleep(0.3)  # Fallback for legacy calls

            # Parallel capture
            # full_page=True captures entire scrollable page, not just viewport
            # This ensures OCR can see all products, not just those above the fold
            html, screenshot_bytes = await asyncio.gather(
                page.content(),
                page.screenshot(type='png', full_page=True),
                return_exceptions=True
            )

            # Handle exceptions
            if isinstance(html, Exception):
                logger.error(f"[Pipeline] HTML capture failed: {html}")
                html = None

            if isinstance(screenshot_bytes, Exception):
                logger.error(f"[Pipeline] Screenshot capture failed: {screenshot_bytes}")
                screenshot_path = None
            else:
                # Save screenshot to temp file
                with open(screenshot_path, 'wb') as f:
                    f.write(screenshot_bytes)

                # Debug: save copy if enabled
                if self.config.save_debug_screenshots:
                    debug_dir = self.config.debug_output_dir
                    os.makedirs(debug_dir, exist_ok=True)
                    debug_path = os.path.join(debug_dir, f"capture_{int(time.time())}.png")
                    with open(debug_path, 'wb') as f:
                        f.write(screenshot_bytes)

            return html, screenshot_path

        except Exception as e:
            logger.error(f"[Pipeline] Capture failed: {e}")
            return None, None

    async def _extract_parallel(
        self,
        html: str,
        screenshot_path: Optional[str],
        url: str,
        query: str
    ) -> tuple:
        """
        Run HTML and vision extraction in parallel.

        Returns:
            Tuple of (html_candidates, vision_products)
        """
        tasks = [
            self.html_extractor.extract(html, url)
        ]

        # Only run vision if we have a screenshot
        if screenshot_path and os.path.exists(screenshot_path):
            tasks.append(self.vision_extractor.extract(screenshot_path, query))
        else:
            # Return empty list for vision
            async def empty_vision():
                return []
            tasks.append(empty_vision())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions
        html_candidates = results[0] if not isinstance(results[0], Exception) else []
        vision_products = results[1] if not isinstance(results[1], Exception) else []

        if isinstance(results[0], Exception):
            logger.error(f"[Pipeline] HTML extraction failed: {results[0]}")

        if isinstance(results[1], Exception):
            logger.error(f"[Pipeline] Vision extraction failed: {results[1]}")

        return html_candidates, vision_products

    async def extract_and_verify(
        self,
        page: 'Page',
        url: str,
        query: str,
        max_products: int = 5,
        max_price: float = None,
        requirements: Dict[str, Any] = None,
        target_viable_products: int = 4
    ) -> List[VerifiedProduct]:
        """
        NEW PRIMARY API: Extract and verify products via PDP navigation.

        This is the recommended method for commerce queries. It:
        1. Extracts product candidates (HTML + Vision hybrid)
        2. SMART PRIORITIZATION: Scores candidates by likelihood of matching requirements
        3. SAFE REJECTION: Skips products that are DEFINITELY wrong (Chromebooks for NVIDIA query)
        4. Pre-filters by max_price if provided
        5. Clicks each product to navigate to its PDP (in priority order)
        6. Extracts verified data: actual URL, price, stock, specs
        7. EARLY STOPPING: Stops when enough viable products found

        Unlike the basic extract() method which relies on SERP data,
        this method verifies every product on its actual PDP for
        accurate pricing and availability.

        Args:
            page: Playwright page object (already on listing page)
            url: Listing page URL
            query: User's search query
            max_products: Maximum products to verify (default 5)
            max_price: Maximum price filter - skip candidates with listing price > max_price
            requirements: User requirements from Phase 1 intelligence (for smart prioritization)
            target_viable_products: Stop early when this many viable products found (default 4)

        Returns:
            List of VerifiedProduct with accurate PDP data
        """
        start_time = time.time()

        logger.info(f"[Pipeline] extract_and_verify: Starting on {url[:60]}...")

        # Step 0: Handle PDP URLs (single product pages)
        # Uses URL patterns first, falls back to vision classification if needed
        if await self._is_pdp(url, page):
            logger.info("[Pipeline] Page is PDP, extracting single product")
            result = await self._extract_from_pdp(page, url, query)
            if result.products:
                # Convert FusedProduct to VerifiedProduct
                fp = result.products[0]
                return [VerifiedProduct(
                    title=fp.title,
                    price=fp.price,
                    url=fp.url,
                    vendor=fp.vendor,
                    in_stock=fp.in_stock,
                    stock_status=fp.stock_status,
                    original_price=fp.original_price,
                    specs=fp.specs,  # Include extracted specs
                    extraction_confidence=fp.confidence,
                    extraction_source="pdp_direct",
                    verification_method="direct_pdp"
                )]
            return []

        # Step 1: Extract candidates from listing page
        logger.info("[Pipeline] Step 1: Extracting candidates from listing page")
        candidates = await self._extract_candidates_for_verification(page, url, query)

        if not candidates:
            logger.warning("[Pipeline] No candidates extracted from listing page")
            return []

        logger.info(f"[Pipeline] Found {len(candidates)} candidates to verify")

        # Step 1.4: GOAL-AWARE FILTERING
        # Filter candidates to only include products that match the user's goal
        # This prevents visiting hamster cage pages when searching for live hamsters
        candidates = await self._filter_candidates_for_goal(candidates, query)

        if not candidates:
            logger.warning("[Pipeline] No candidates matched user's goal after filtering")
            return []

        # Step 1.5: SMART PRIORITIZATION (NEW)
        # Score candidates by likelihood of matching requirements
        # Safe-reject products that are DEFINITELY wrong (Chromebooks for NVIDIA query)
        # Sort remaining by score (high-probability first)
        if requirements:
            # Convert candidates to dicts for prioritizer
            candidate_dicts = []
            for c in candidates:
                if hasattr(c, 'to_dict'):
                    candidate_dicts.append(c.to_dict())
                elif isinstance(c, dict):
                    candidate_dicts.append(c)
                else:
                    # HTMLCandidate or similar - extract key fields
                    candidate_dicts.append({
                        "name": getattr(c, 'link_text', '') or getattr(c, 'title', ''),
                        "url": getattr(c, 'url', ''),
                        "price": getattr(c, 'price', None) or getattr(c, 'context_text', ''),
                    })

            prioritization = prioritize_candidates(
                candidates=candidate_dicts,
                requirements=requirements,
                query=query,
                max_to_verify=max_products * 2  # Get more than we need for early stopping
            )

            # Log prioritization results
            if prioritization.rejected:
                logger.info(
                    f"[Pipeline] Prioritization: {len(prioritization.rejected)} candidates SAFE-REJECTED "
                    f"(definitely wrong category)"
                )
                for r in prioritization.rejected[:3]:  # Log first 3
                    logger.info(f"[Pipeline]   ✗ {r.get('name', 'Unknown')[:40]}: {r.get('_rejection_reason', 'N/A')}")

            # Rebuild candidate list from prioritized dicts
            # Match back to original objects by URL
            url_to_original = {getattr(c, 'url', ''): c for c in candidates}
            prioritized_candidates = []
            for p_dict in prioritization.prioritized:
                original = url_to_original.get(p_dict.get('url', ''))
                if original:
                    prioritized_candidates.append(original)

            if prioritized_candidates:
                candidates = prioritized_candidates
                logger.info(
                    f"[Pipeline] Prioritization: {len(candidates)} candidates prioritized for verification "
                    f"(high={prioritization.stats.get('high_priority', 0)}, "
                    f"medium={prioritization.stats.get('medium_priority', 0)}, "
                    f"low={prioritization.stats.get('low_priority', 0)})"
                )
            else:
                logger.warning("[Pipeline] Prioritization returned empty, using original order")

        # Step 1.6: Pre-filter by price if max_price is set
        # This saves expensive PDP verification for products clearly over budget
        if max_price is not None:
            original_count = len(candidates)
            filtered_candidates = []

            for candidate in candidates:
                # Get price from candidate (could be HTMLCandidate or other types)
                candidate_price = None
                if hasattr(candidate, 'price') and candidate.price:
                    candidate_price = candidate.price
                elif hasattr(candidate, 'price_numeric') and candidate.price_numeric:
                    candidate_price = candidate.price_numeric
                elif isinstance(candidate, dict):
                    candidate_price = candidate.get('price') or candidate.get('price_numeric')

                # Ensure price is numeric (could be string like "$35" or "35")
                if candidate_price is not None and isinstance(candidate_price, str):
                    try:
                        # Remove $ and commas, convert to float
                        candidate_price = float(candidate_price.replace('$', '').replace(',', ''))
                    except (ValueError, AttributeError):
                        candidate_price = None

                # If we can't determine price, include the candidate (verify to be safe)
                if candidate_price is None:
                    filtered_candidates.append(candidate)
                elif candidate_price <= max_price:
                    filtered_candidates.append(candidate)
                else:
                    # Skip this candidate - price exceeds budget
                    title = getattr(candidate, 'title', str(candidate)[:50])
                    logger.info(
                        f"[Pipeline] Pre-filter: Skipping '{title[:40]}...' "
                        f"(listing price ${candidate_price:.2f} > max ${max_price:.2f})"
                    )

            candidates = filtered_candidates
            skipped = original_count - len(candidates)
            if skipped > 0:
                logger.info(
                    f"[Pipeline] Pre-filter: {skipped} candidates skipped "
                    f"(over budget ${max_price:.2f}), {len(candidates)} remaining"
                )

            if not candidates:
                logger.warning(
                    f"[Pipeline] All {original_count} candidates exceeded max price ${max_price:.2f}"
                )
                return []

        # Step 2: Verify each product via PDP navigation with early stopping
        logger.info("[Pipeline] Step 2: Verifying products via PDP navigation (with early stopping)")

        # Get vendor from URL
        vendor = urlparse(url).netloc
        if vendor.startswith("www."):
            vendor = vendor[4:]

        # Initialize verifier with early stopping support
        verifier = ProductVerifier(
            pdp_extractor=self.pdp_extractor,
            max_products=max_products
        )

        # Scroll to top to match the state when screenshot was taken
        # (bbox coordinates are viewport-relative from scroll position 0)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.3)

        # Verify products with early stopping
        # When requirements are provided, we can stop early once we have enough viable products
        verified = await verifier.verify_products_with_early_stop(
            page=page,
            candidates=candidates,
            original_url=url,
            vendor=vendor,
            target_viable=target_viable_products,
            requirements=requirements,
            query=query
        )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[Pipeline] extract_and_verify complete: "
            f"{len(verified)}/{len(candidates)} products verified in {elapsed_ms:.0f}ms"
        )

        return verified

    async def _extract_candidates_for_verification(
        self,
        page: 'Page',
        url: str,
        query: str
    ) -> List:
        """
        Extract candidates for verification using tiered extraction.

        Tiered approach:
        - Tier 1: Schema-driven DOM extraction (fastest, if schema exists)
        - Tier 2: HTML pattern extraction (current html_extractor)
        - Tier 3: Vision/OCR extraction (current vision_extractor)

        Returns a mix of HTMLCandidate and VisualProduct objects
        that can be passed to ProductVerifier.
        """
        # Get domain for schema lookup
        domain = self._extract_domain(url)
        schema_registry = get_schema_registry()
        health_tracker = get_health_tracker()

        extraction_method = None
        screenshot_path = None

        try:
            # ═══════════════════════════════════════════════════════════════
            # TIER 0: Universal JS extraction
            # Simple, fast extraction using universal JS patterns
            # ═══════════════════════════════════════════════════════════════
            logger.info(f"[Pipeline] Tier 0: Universal JS extraction for {domain}")

            js_candidates = await self._extract_universal_js(page, url)
            if js_candidates and len(js_candidates) >= 3:
                logger.info(f"[Pipeline] Tier 0 SUCCESS: Universal JS extracted {len(js_candidates)} candidates")
                schema_registry.record_extraction(domain, "listing", success=True, method="universal_js")
                return js_candidates

            # ═══════════════════════════════════════════════════════════════
            # PROACTIVE SCHEMA BUILD MODE (only if Tier 0 didn't work)
            # Ensure schema exists BEFORE extraction (not after)
            # ═══════════════════════════════════════════════════════════════
            schema = await self._ensure_schema(page, url, domain, "listing")

            # ═══════════════════════════════════════════════════════════════
            # TIER 1: Schema-driven extraction
            # The calibrator now handles internal retries with validation feedback,
            # so we only need one attempt here - calibrate() returns a validated schema.
            # ═══════════════════════════════════════════════════════════════
            if schema and schema.product_card_selector:
                logger.info(f"[Pipeline] Tier 1: Schema extraction for {domain} (selector: {schema.product_card_selector})")

                schema_candidates = await self._extract_with_schema(page, schema, url)

                if schema_candidates:
                    logger.info(f"[Pipeline] Tier 1 SUCCESS: Schema extracted {len(schema_candidates)} candidates")
                    schema_registry.record_extraction(domain, "listing", success=True, method="schema")
                    return schema_candidates
                else:
                    logger.warning(f"[Pipeline] Tier 1 FAILED: Schema selector found elements but extraction returned 0 candidates")
                    schema_registry.record_extraction(domain, "listing", success=False, method="schema")
                    # Don't retry here - calibrator already did internal retries with validation
                    # Fall through to Tier 2-3
            else:
                logger.info(f"[Pipeline] No valid schema for {domain}, skipping Tier 1")

            # ═══════════════════════════════════════════════════════════════
            # TIER 2-3: HTML + Vision extraction (existing flow)
            # ═══════════════════════════════════════════════════════════════
            logger.info(f"[Pipeline] Tier 2-3: HTML + Vision extraction for {domain}")

            # Capture HTML and screenshot with smart wait
            html, screenshot_path = await self._capture(page, url)

            if not html:
                logger.warning("[Pipeline] Failed to capture HTML")
                return []

            # Extract from both
            html_candidates, vision_products = await self._extract_parallel(
                html, screenshot_path, url, query
            )

            logger.info(
                f"[Pipeline] Candidates extracted: "
                f"{len(html_candidates)} from HTML, {len(vision_products)} from Vision"
            )

            # Prioritize candidates:
            # 1. Fused products (have both URL and visual confirmation)
            # 2. HTML candidates with URLs
            # 3. Vision products (need click-to-verify)

            candidates = []

            if vision_products and html_candidates:
                # Full fusion: match vision to HTML
                fused = self.fusion.match(vision_products, html_candidates, url)
                candidates.extend(fused)
                extraction_method = "fusion"
            elif html_candidates:
                # HTML-only: convert to candidates
                fused = match_html_only(html_candidates, url)
                candidates.extend(fused)
                extraction_method = "html"
            elif vision_products:
                # Vision-only: add directly (will need click-to-verify)
                candidates.extend(vision_products)
                extraction_method = "vision"

            # ═══════════════════════════════════════════════════════════════
            # REACTIVE CALIBRATION: Only if proactive mode is disabled
            # (With proactive mode, schema is already built before extraction)
            # ═══════════════════════════════════════════════════════════════
            if not self.config.enable_proactive_calibration:
                if candidates and (not schema or schema.needs_recalibration):
                    # Trigger background calibration (legacy reactive mode)
                    asyncio.create_task(self._trigger_calibration(page, url, domain))

            # Record extraction result
            if candidates:
                schema_registry.record_extraction(
                    domain, "listing", success=True, method=extraction_method or "unknown"
                )
            else:
                schema_registry.record_extraction(
                    domain, "listing", success=False, method=extraction_method or "unknown"
                )

            return candidates

        except Exception as e:
            logger.error(f"[Pipeline] Candidate extraction failed: {e}")
            schema_registry.record_extraction(domain, "listing", success=False, method="error")
            return []

        finally:
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    os.remove(screenshot_path)
                except OSError:
                    pass

    async def _extract_with_schema(
        self,
        page: 'Page',
        schema: SiteSchema,
        url: str
    ) -> List:
        """
        Extract products using learned schema selectors.

        This is Tier 1 extraction - fastest and most reliable when schema exists.
        """
        candidates = []

        try:
            if not schema.product_card_selector:
                return []

            # Find all product cards
            cards = await page.query_selector_all(schema.product_card_selector)

            if not cards:
                logger.debug(f"[Pipeline] Schema selector '{schema.product_card_selector}' found 0 cards")
                return []

            logger.info(f"[Pipeline] Schema found {len(cards)} product cards")

            for i, card in enumerate(cards[:20]):  # Limit to 20 products
                try:
                    # Get product link
                    link_el = None
                    href = None
                    title = ""

                    if schema.product_link_selector:
                        link_el = await card.query_selector(schema.product_link_selector)

                    if not link_el:
                        # Fallback: find any link in the card
                        link_el = await card.query_selector("a[href]")

                    if link_el:
                        href = await link_el.get_attribute("href")
                        title = await link_el.text_content() or ""
                        title = title.strip()

                    if not href:
                        continue

                    # Get price
                    price_text = ""
                    if schema.price_selector:
                        price_el = await card.query_selector(schema.price_selector)
                        if price_el:
                            price_text = await price_el.text_content() or ""

                    # Get title from dedicated selector if available
                    if schema.title_selector and not title:
                        title_el = await card.query_selector(schema.title_selector)
                        if title_el:
                            title = await title_el.text_content() or ""
                            title = title.strip()

                    # Build absolute URL
                    if href and not href.startswith("http"):
                        from urllib.parse import urljoin
                        href = urljoin(url, href)

                    # Skip filter/navigation URLs
                    if self._is_filter_url(href, schema):
                        continue

                    # Create candidate
                    from .models import HTMLCandidate
                    candidate = HTMLCandidate(
                        url=href,
                        link_text=title[:200],
                        context_text=price_text[:100],
                        source="schema_driven",
                        confidence=0.95
                    )
                    candidates.append(candidate)

                except Exception as e:
                    logger.debug(f"[Pipeline] Error extracting card {i}: {e}")
                    continue

            return candidates

        except Exception as e:
            logger.error(f"[Pipeline] Schema extraction error: {e}")
            return []

    async def _extract_universal_js(self, page: 'Page', url: str) -> List:
        """
        Universal JS extraction using "inside-out" approach.

        Instead of finding product cards and extracting from them,
        we find prices first and walk UP the DOM to find product containers.

        This works on ANY site without calibration because:
        1. Prices ($XX.XX) are universal and easy to find
        2. Walking UP from price to container is reliable
        3. Product cards always contain title + link + price together

        Returns list of HTMLCandidate objects.
        """
        try:
            # JavaScript to find products by price-first approach
            result_data = await page.evaluate('''() => {
                const results = [];
                const seen = new Set();

                // Price pattern: $X, $XX, $XXX, $X,XXX, $XX.XX, etc.
                const pricePattern = /\\$[\\d,]+\\.?\\d{0,2}/;

                // Strategy 1: Find all text nodes with prices
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    {
                        acceptNode: function(node) {
                            const text = node.textContent.trim();
                            if (pricePattern.test(text) && text.length < 20) {
                                return NodeFilter.FILTER_ACCEPT;
                            }
                            return NodeFilter.FILTER_SKIP;
                        }
                    }
                );

                const priceNodes = [];
                while (walker.nextNode()) {
                    priceNodes.push(walker.currentNode);
                }

                // For each price, walk UP to find product container
                for (const priceNode of priceNodes) {
                    let element = priceNode.parentElement;
                    let card = null;
                    let attempts = 0;

                    // Walk up max 10 levels to find a container with both link and title
                    while (element && attempts < 10) {
                        const links = element.querySelectorAll('a[href]');
                        const hasProductLink = Array.from(links).some(a => {
                            const href = a.href || '';
                            return href.includes('/product') || href.includes('/p/') ||
                                   href.includes('/dp/') || href.includes('/ip/') ||
                                   href.includes('/item') || href.includes('/pd/') ||
                                   (href.startsWith('http') && !href.includes('/search') &&
                                    !href.includes('/category') && !href.includes('javascript:'));
                        });

                        const hasTitle = element.querySelector('h1, h2, h3, h4, [class*="title"], [class*="name"], [class*="product"]');

                        if (hasProductLink && hasTitle) {
                            card = element;
                            break;
                        }

                        element = element.parentElement;
                        attempts++;
                    }

                    if (!card) continue;

                    // Extract data from found card
                    const priceText = priceNode.textContent.trim();
                    const priceMatch = priceText.match(/\\$[\\d,]+\\.?\\d{0,2}/);
                    const price = priceMatch ? priceMatch[0] : '';

                    // Find product link (prefer product URLs over generic links)
                    let productUrl = '';
                    let title = '';
                    const cardLinks = card.querySelectorAll('a[href]');

                    for (const link of cardLinks) {
                        const href = link.href || '';
                        if (!href || href.includes('javascript:') || href === '#') continue;

                        // Prefer product-like URLs
                        const isProductUrl = href.includes('/product') || href.includes('/p/') ||
                                           href.includes('/dp/') || href.includes('/ip/') ||
                                           href.includes('/item') || href.includes('/pd/') ||
                                           href.includes('/shop/');

                        if (isProductUrl || !productUrl) {
                            productUrl = href;
                            // Get title from link or nearby heading
                            title = link.textContent?.trim() || '';
                            if (title.length < 10) {
                                const heading = card.querySelector('h1, h2, h3, h4, [class*="title"], [class*="name"]');
                                if (heading) title = heading.textContent?.trim() || '';
                            }
                            if (isProductUrl) break;
                        }
                    }

                    // Skip if no valid URL or already seen
                    if (!productUrl || seen.has(productUrl)) continue;
                    if (productUrl.includes('/search') || productUrl.includes('/category')) continue;

                    // Filter out non-product titles
                    const titleLower = title.toLowerCase();
                    const navWords = ['your list', 'quick view', 'leave feedback',
                                     'any category', 'sign in', 'my cart', 'wishlist', 'compare',
                                     'filter by', 'sort by', 'refine by', 'see all deals', 'view all',
                                     'ad feedback', 'shop all', 'browse all'];
                    const isNavTitle = navWords.some(w => titleLower.includes(w));

                    // Skip if title is too short or is pure navigation (but keep "more options" since Newegg uses it)
                    if (title.length < 12 || isNavTitle) continue;

                    // Skip if URL doesn't look like a product page (relaxed for Newegg /N82E format)
                    const urlLower = productUrl.toLowerCase();
                    const isProductPage = urlLower.includes('/dp/') || urlLower.includes('/product') ||
                                         urlLower.includes('/p/') || urlLower.includes('/ip/') ||
                                         urlLower.includes('/item') || urlLower.includes('/pd/') ||
                                         urlLower.includes('/gp/product') || urlLower.includes('ref=') ||
                                         urlLower.includes('/n82e');  // Newegg product IDs
                    if (!isProductPage) continue;

                    seen.add(productUrl);

                    results.push({
                        url: productUrl,
                        title: title.substring(0, 200),
                        price: price,
                        source: 'universal_js'
                    });

                    // Limit to 20 products
                    if (results.length >= 20) break;
                }

                // Strategy 2: If no results, try finding product cards by common patterns
                if (results.length < 3) {
                    const cardSelectors = [
                        '[data-testid*="product"]',
                        '[data-component*="product"]',
                        '[class*="product-card"]',
                        '[class*="product-item"]',
                        '[class*="sku-item"]',
                        'article[class*="product"]',
                        'li[class*="product"]'
                    ];

                    for (const selector of cardSelectors) {
                        const cards = document.querySelectorAll(selector);
                        if (cards.length < 3) continue;

                        for (const card of cards) {
                            const link = card.querySelector('a[href]');
                            const priceEl = card.querySelector('[class*="price"]');
                            const titleEl = card.querySelector('h1, h2, h3, h4, [class*="title"], [class*="name"]');

                            if (!link) continue;

                            const href = link.href || '';
                            if (!href || seen.has(href)) continue;
                            if (href.includes('/search') || href.includes('/category')) continue;

                            const title = (titleEl?.textContent || link.textContent || '').trim();

                            // Apply same filtering as Strategy 1
                            const titleLower = title.toLowerCase();
                            const navWords = ['your list', 'quick view', 'leave feedback',
                                             'any category', 'sign in', 'my cart', 'wishlist', 'compare'];
                            if (title.length < 12 || navWords.some(w => titleLower.includes(w))) continue;

                            seen.add(href);

                            results.push({
                                url: href,
                                title: title.substring(0, 200),
                                price: priceEl?.textContent?.match(/\\$[\\d,]+\\.?\\d{0,2}/)?.[0] || '',
                                source: 'universal_js_fallback'
                            });

                            if (results.length >= 20) break;
                        }

                        if (results.length >= 3) break;
                    }
                }

                return results;
            }''')

            if not result_data:
                return []

            # Convert to HTMLCandidate objects
            from .models import HTMLCandidate
            candidates = []

            for item in result_data:
                href = item.get("url", "")
                if not href:
                    continue

                # Build absolute URL
                if not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)

                candidate = HTMLCandidate(
                    url=href,
                    link_text=item.get("title", "")[:200],
                    context_text=item.get("price", "")[:50],
                    source=item.get("source", "universal_js"),
                    confidence=0.85
                )
                candidates.append(candidate)

            logger.info(f"[Pipeline] Universal JS found {len(candidates)} products")
            return candidates

        except Exception as e:
            logger.warning(f"[Pipeline] Universal JS extraction error: {e}")
            return []

    def _is_filter_url(self, url: str, schema: SiteSchema) -> bool:
        """Check if URL is a filter/navigation link or ad redirect to avoid."""
        if not url:
            return True

        url_lower = url.lower()

        # Reject Amazon sponsored/ad redirect URLs
        # These URLs redirect to random promoted products, not search-relevant results
        # Pattern: aax-us-east-retail-direct.amazon.com or similar ad domains
        from urllib.parse import urlparse
        try:
            hostname = urlparse(url_lower).netloc
            if hostname and ('aax-us-east' in hostname or hostname.startswith('aax-')):
                logger.debug(f"[Pipeline] Filtering Amazon ad URL: {url[:60]}...")
                return True
        except Exception:
            pass

        # Check against schema's filter selectors patterns
        filter_patterns = [
            "searchpage.jsp",
            "_facet",
            "modelfamily_facet",
            "qp=",
            "/browse/",
            "/category/",
        ]

        return any(p in url_lower for p in filter_patterns)

    async def _trigger_calibration(self, page: 'Page', url: str, domain: str) -> None:
        """Trigger background calibration to learn schema."""
        try:
            # Validate page is still valid and on the expected URL
            # (page may have navigated away if this is called as background task)
            if page.is_closed():
                logger.warning(f"[Pipeline] Calibration skipped - page is closed")
                return

            current_url = page.url
            if domain not in current_url:
                logger.warning(f"[Pipeline] Calibration skipped - page navigated away from {domain} to {current_url}")
                return

            calibrator = get_smart_calibrator()
            logger.info(f"[Pipeline] Triggering calibration for {domain}")
            await calibrator.calibrate(page, url, force=False)
        except Exception as e:
            logger.warning(f"[Pipeline] Calibration failed for {domain}: {e}")

    async def _ensure_schema(
        self,
        page: 'Page',
        url: str,
        domain: str,
        page_type: str = "listing"
    ) -> Optional[Any]:
        """
        Ensure a valid schema exists for this domain/page_type.

        PROACTIVE Schema Build Mode:
        - If no schema exists, calibrate NOW before extraction
        - If schema needs recalibration, recalibrate NOW
        - This replaces the reactive approach where we only calibrated after success

        Args:
            page: Playwright page object
            url: Current page URL
            domain: Extracted domain
            page_type: Type of page (listing, pdp, search_results)

        Returns:
            SiteSchema or ExtractionSchema if found/created, None if calibration failed/disabled
        """
        if not self.config.enable_proactive_calibration:
            # Proactive calibration disabled, fall back to reactive
            schema_registry = get_schema_registry()
            return schema_registry.get(domain, page_type)

        schema_registry = get_schema_registry()

        # Check if we have a valid, non-stale schema
        existing = schema_registry.get(domain, page_type)
        if existing and not existing.needs_recalibration:
            # Use success_rate as proxy for confidence (SiteSchema doesn't have confidence attr)
            logger.info(f"[Pipeline] Using cached schema for {domain} (success_rate: {existing.success_rate:.0%})")
            return existing

        # Need to build/rebuild schema proactively
        reason = "no schema exists" if not existing else "schema needs recalibration"
        logger.info(f"[Pipeline] Proactive calibration for {domain} ({reason})")

        try:
            calibrator = get_smart_calibrator()

            # Use timeout from config
            timeout_sec = self.config.calibration_timeout_ms / 1000.0
            schema = await asyncio.wait_for(
                calibrator.calibrate(page, url, force=True),
                timeout=timeout_sec
            )

            if schema:
                # Check if schema has key selectors (proxy for confidence)
                has_selectors = bool(schema.product_card_selector or schema.product_link_selector)
                if has_selectors:
                    logger.info(
                        f"[Pipeline] Proactive calibration SUCCESS for {domain} "
                        f"(selectors: card={schema.product_card_selector is not None}, "
                        f"link={schema.product_link_selector is not None})"
                    )
                    return schema
                else:
                    logger.warning(
                        f"[Pipeline] Proactive calibration no selectors for {domain}, "
                        f"will use vision fallback"
                    )
                    return None
            else:
                logger.warning(f"[Pipeline] Proactive calibration returned None for {domain}")
                return None

        except asyncio.TimeoutError:
            logger.warning(
                f"[Pipeline] Proactive calibration timeout for {domain} "
                f"(>{self.config.calibration_timeout_ms}ms)"
            )
            return None
        except Exception as e:
            logger.warning(f"[Pipeline] Proactive calibration failed for {domain}: {e}")
            return None

    async def _filter_candidates_for_goal(
        self,
        candidates: List,
        goal: str,
        max_candidates: int = 10
    ) -> List:
        """
        Filter candidates to only include products matching the user's goal.

        This is CRITICAL for intelligent navigation - it prevents clicking on
        hamster cages when searching for live hamsters, or laptop bags when
        searching for laptops.

        Uses LLM to understand the user's intent and filter accordingly.

        Args:
            candidates: List of product candidates (HTMLCandidate, FusedProduct, etc.)
            goal: User's original search query/goal
            max_candidates: Maximum candidates to evaluate (for token efficiency)

        Returns:
            Filtered list of candidates that match the user's goal
        """
        if not candidates:
            return []

        # Limit candidates for LLM evaluation
        to_evaluate = candidates[:max_candidates]

        # Build candidate list for prompt
        candidate_lines = []
        for i, c in enumerate(to_evaluate, 1):
            title = ""
            if hasattr(c, 'title'):
                title = c.title or ""
            elif hasattr(c, 'link_text'):
                title = c.link_text or ""
            elif isinstance(c, dict):
                title = c.get('title') or c.get('link_text') or ""

            if title:
                candidate_lines.append(f"{i}. {title[:100]}")

        if not candidate_lines:
            # No titles to filter, return all
            return candidates

        # Load prompt via recipe system
        base_prompt = _load_prompt_via_recipe("search_result_filter", "tools")
        if not base_prompt:
            logger.warning("Search result filter prompt not found via recipe")
            base_prompt = "Filter search results to match user's goal. Respond with JSON: {keep: [indices], reason: 'explanation'}"

        # Build full prompt with dynamic data
        prompt = f"""{base_prompt}

## Current Task

USER'S GOAL: {goal}

CANDIDATE ITEMS:
{chr(10).join(candidate_lines)}

Identify which items are RELEVANT PRODUCTS that match what the user wants."""

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.llm_url}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.llm_api_key}"},
                    json={
                        "model": self.llm_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.4,
                        "max_tokens": 300,
                        "top_p": 0.8,
                        "stop": ["<|im_end|>", "<|endoftext|>"],
                        "repetition_penalty": 1.05
                    }
                )

                if response.status_code != 200:
                    logger.warning(f"[Pipeline] Goal filter LLM returned {response.status_code}, keeping all")
                    return candidates

                result = response.json()
                content = result.get('choices', [{}])[0].get('message', {}).get('content', '')

                # Parse JSON response
                # Handle markdown code blocks
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                filter_result = json.loads(content)
                keep_indices = set(filter_result.get("keep", []))
                reason = filter_result.get("reason", "").lower()

                # CONSISTENCY CHECK: If reason says "no matching" but keep is not empty,
                # trust the reason over the keep list (LLM instruction-following issue)
                no_match_phrases = [
                    "no matching products",
                    "no matching items",
                    "none match",
                    "no items match",
                    "no products match",
                    "only cages",
                    "only accessories",
                    "only supplies",
                    "not the actual",
                    "not actual",
                ]
                if keep_indices and any(phrase in reason for phrase in no_match_phrases):
                    logger.warning(
                        f"[Pipeline] Goal filter INCONSISTENCY: LLM returned {len(keep_indices)} items "
                        f"but reason says '{reason[:60]}...'. Trusting reason - rejecting all."
                    )
                    keep_indices = set()  # Override to empty - trust the reason

                # Build filtered list
                filtered = []
                for i, c in enumerate(to_evaluate, 1):
                    if i in keep_indices:
                        filtered.append(c)

                # Add any candidates beyond max_candidates (weren't evaluated)
                if len(candidates) > max_candidates:
                    filtered.extend(candidates[max_candidates:])

                rejected = len(to_evaluate) - len([c for c in to_evaluate if to_evaluate.index(c) + 1 in keep_indices])

                logger.info(
                    f"[Pipeline] Goal filter: {len(filtered)}/{len(to_evaluate)} candidates match goal '{goal[:40]}...' "
                    f"({rejected} rejected: {reason})"
                )

                return filtered

        except json.JSONDecodeError as e:
            logger.warning(f"[Pipeline] Goal filter JSON parse failed: {e}, keeping all")
            return candidates
        except Exception as e:
            logger.warning(f"[Pipeline] Goal filter error: {e}, keeping all")
            return candidates

    def _extract_domain(self, url: str) -> str:
        """Extract normalized domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or ""
            if domain.startswith("www."):
                domain = domain[4:]
            return domain.lower()
        except Exception:
            return ""


# Convenience function for simple usage
async def extract_products(
    page: 'Page',
    url: str,
    query: str,
    **kwargs
) -> List[FusedProduct]:
    """
    Extract products from a retailer page using hybrid vision+HTML extraction.

    Args:
        page: Playwright page object (already navigated)
        url: Current page URL
        query: User's search query
        **kwargs: Additional arguments passed to ProductPerceptionPipeline

    Returns:
        List of FusedProduct
    """
    pipeline = ProductPerceptionPipeline(**kwargs)
    return await pipeline.extract(page, url, query)
