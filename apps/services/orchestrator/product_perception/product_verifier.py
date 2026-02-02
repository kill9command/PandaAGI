"""
Product Verifier - Click-to-Verify as PRIMARY flow.

This module implements the core product verification strategy:
1. For each product identified on listing page
2. Click to navigate to its Product Detail Page (PDP)
3. Extract verified data: URL, price, stock, specs
4. Navigate back, repeat for next product

This is the PRIMARY extraction method - all products get verified
on their actual PDP for accurate pricing and availability.
"""

import asyncio
import logging
import re
from typing import List, Optional, Dict, Any, Union, TYPE_CHECKING
from dataclasses import dataclass
from urllib.parse import urlparse

from .models import (
    FusedProduct, HTMLCandidate, VisualProduct,
    PDPData, BoundingBox
)
from .config import get_config

# Import captcha intervention system
try:
    from apps.services.orchestrator.captcha_intervention import detect_blocker, request_intervention
    CAPTCHA_INTERVENTION_AVAILABLE = True
except ImportError:
    CAPTCHA_INTERVENTION_AVAILABLE = False

if TYPE_CHECKING:
    from playwright.async_api import Page
    from .pdp_extractor import PDPExtractor

logger = logging.getLogger(__name__)


@dataclass
class VerifiedProduct:
    """A product with verified data from its PDP."""
    # Core verified data
    title: str
    price: Optional[float]
    url: str
    vendor: str

    # Stock and availability
    in_stock: bool = True
    stock_status: str = "unknown"

    # Additional verified data
    original_price: Optional[float] = None  # Sale price strikethrough
    specs: Dict[str, str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    condition: str = "new"
    image_url: Optional[str] = None

    # Extraction metadata
    extraction_confidence: float = 0.0
    extraction_source: str = ""  # "json_ld", "html_selector", "vision"
    verification_method: str = ""  # "pdp_navigation", "direct_url", "fallback"

    # Original candidate data (for debugging)
    original_title: Optional[str] = None
    original_price: Optional[float] = None
    bbox: Optional[BoundingBox] = None

    def __post_init__(self):
        if self.specs is None:
            self.specs = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "price": self.price,
            "url": self.url,
            "vendor": self.vendor,
            "in_stock": self.in_stock,
            "stock_status": self.stock_status,
            "original_price": self.original_price,
            "specs": self.specs,
            "rating": self.rating,
            "review_count": self.review_count,
            "condition": self.condition,
            "image_url": self.image_url,
            "extraction_confidence": self.extraction_confidence,
            "extraction_source": self.extraction_source,
            "verification_method": self.verification_method,
        }


class ProductVerifier:
    """
    Verifies products by navigating to their PDPs.

    This is the PRIMARY extraction method - all products should
    be verified via PDP navigation for accurate data.
    """

    def __init__(self, pdp_extractor: 'PDPExtractor' = None, max_products: int = 5):
        self.config = get_config()
        self.pdp_extractor = pdp_extractor
        self.max_products = max_products

    async def _check_and_handle_captcha(
        self,
        page: 'Page',
        url: str,
        session_id: str = "product_verifier"
    ) -> bool:
        """
        Check if current page is a captcha/blocker and request intervention if needed.

        Args:
            page: Playwright page object
            url: Current page URL
            session_id: Session ID for intervention tracking

        Returns:
            True if page is OK (no captcha or captcha resolved)
            False if captcha detected and not resolved
        """
        if not CAPTCHA_INTERVENTION_AVAILABLE:
            logger.debug("[Verifier] Captcha intervention not available")
            return True

        try:
            # Get page content for detection
            html_content = await page.content()
            current_url = page.url

            # Use the captcha intervention detection
            blocker = detect_blocker({
                "url": current_url,
                "content": html_content,
                "status": 200
            })

            if not blocker or blocker.get("confidence", 0) < 0.7:
                return True  # No blocker detected

            logger.warning(f"[Verifier] Captcha/blocker detected on PDP: {blocker.get('type')} at {current_url[:60]}...")

            # Take screenshot for intervention
            import tempfile
            import os
            screenshot_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    screenshot_bytes = await page.screenshot(type='png', full_page=False)
                    f.write(screenshot_bytes)
                    screenshot_path = f.name
            except Exception as e:
                logger.warning(f"[Verifier] Screenshot failed: {e}")

            # Get noVNC URL - use vnc_lite.html which auto-connects (no connect button needed)
            novnc_url = os.getenv("NOVNC_URL", "http://localhost:6080/vnc_lite.html?host=localhost&port=6080&scale=true")

            # Request intervention
            logger.info(f"[Verifier] Requesting intervention for captcha on {current_url[:60]}...")
            intervention = await request_intervention(
                blocker_type=blocker.get("type", "captcha"),
                url=current_url,
                screenshot_path=screenshot_path,
                session_id=session_id,
                blocker_details=blocker,
                cdp_url=novnc_url
            )

            # Wait for resolution
            resolved = await intervention.wait_for_resolution(timeout=120)

            if resolved:
                logger.info(f"[Verifier] Captcha resolved, waiting 5 seconds for page to settle...")
                # Wait for page to fully load after CAPTCHA resolution
                # This prevents re-triggering Cloudflare on rapid navigation (matching research_orchestrator.py)
                await asyncio.sleep(5.0)
                return True
            else:
                logger.warning(f"[Verifier] Captcha not resolved within timeout")
                return False

        except Exception as e:
            logger.error(f"[Verifier] Error in captcha check: {e}")
            return True  # Continue anyway on error

    async def verify_products(
        self,
        page: 'Page',
        candidates: List[Union[HTMLCandidate, VisualProduct, FusedProduct]],
        original_url: str,
        vendor: str
    ) -> List[VerifiedProduct]:
        """
        Verify multiple products via PDP navigation.

        For each candidate:
        1. Navigate to product page (click or direct URL)
        2. Extract verified data from PDP
        3. Navigate back
        4. Return verified product

        Args:
            page: Playwright page object
            candidates: Products to verify (from HTML, Vision, or Fusion)
            original_url: Listing page URL to return to
            vendor: Retailer domain

        Returns:
            List of verified products
        """
        if not candidates:
            return []

        verified = []
        to_verify = candidates[:self.max_products]

        logger.info(f"[Verifier] Starting verification of {len(to_verify)} products on {vendor}")

        for i, candidate in enumerate(to_verify):
            try:
                logger.info(f"[Verifier] Verifying product {i+1}/{len(to_verify)}: {self._get_title(candidate)[:50]}...")

                product = await self._verify_single(page, candidate, original_url, vendor)

                if product:
                    verified.append(product)
                    price_str = f"${product.price:.2f}" if product.price else "contact"
                    logger.info(f"[Verifier] Product {i+1} verified: {price_str} - {product.title[:40]}...")
                else:
                    # Verification failed - create unverified product with listing URL
                    logger.warning(f"[Verifier] Product {i+1} verification failed, returning unverified")
                    unverified = self._create_unverified_product(candidate, original_url, vendor)
                    if unverified:
                        verified.append(unverified)
                        logger.info(f"[Verifier] Product {i+1} returned as unverified: {unverified.title[:40]}...")

                # Delay between products to avoid bot detection (especially Cloudflare)
                if i < len(to_verify) - 1:
                    await asyncio.sleep(3.0)

            except Exception as e:
                logger.error(f"[Verifier] Error verifying product {i+1}: {e}")
                # Create unverified product even on error
                unverified = self._create_unverified_product(candidate, original_url, vendor)
                if unverified:
                    verified.append(unverified)
                # Try to recover page state
                await self._ensure_on_listing(page, original_url)

        logger.info(f"[Verifier] Verification complete: {len(verified)}/{len(to_verify)} products verified")
        return verified

    async def verify_products_with_early_stop(
        self,
        page: 'Page',
        candidates: List[Union[HTMLCandidate, VisualProduct, FusedProduct]],
        original_url: str,
        vendor: str,
        target_viable: int = 4,
        requirements: Dict[str, Any] = None,
        query: str = ""
    ) -> List[VerifiedProduct]:
        """
        Verify products with early stopping when enough viable products found.

        This is an optimized version of verify_products that:
        1. Verifies products in priority order (caller should pre-sort)
        2. Checks viability after each verification
        3. STOPS EARLY when target_viable products are found

        This can save 50-80% of verification time by not verifying
        low-priority candidates once we have enough good products.

        Args:
            page: Playwright page object
            candidates: Products to verify (should be pre-sorted by priority)
            original_url: Listing page URL to return to
            vendor: Retailer domain
            target_viable: Stop when this many viable products found (default 4)
            requirements: User requirements for viability checking
            query: User's original query

        Returns:
            List of verified products (may be fewer than max_products if early stopped)
        """
        if not candidates:
            return []

        # If no requirements provided, fall back to regular verification
        if not requirements:
            logger.info("[Verifier] No requirements provided, using standard verification")
            return await self.verify_products(page, candidates, original_url, vendor)

        verified = []
        viable_count = 0
        to_verify = candidates[:self.max_products * 2]  # Allow more candidates for early stop filtering

        logger.info(
            f"[Verifier] Starting verification with early stop: "
            f"{len(to_verify)} candidates, target {target_viable} viable products"
        )

        for i, candidate in enumerate(to_verify):
            # Check if we should continue
            remaining = len(to_verify) - i - 1
            from apps.services.orchestrator.candidate_prioritizer import should_continue_verification
            should_continue, reason = should_continue_verification(
                viable_count=viable_count,
                verified_count=len(verified),
                remaining_count=remaining,
                target_per_vendor=target_viable
            )

            if not should_continue:
                logger.info(f"[Verifier] EARLY STOP: {reason}")
                break

            try:
                logger.info(
                    f"[Verifier] Verifying product {i+1}/{len(to_verify)} "
                    f"(viable: {viable_count}/{target_viable}): {self._get_title(candidate)[:50]}..."
                )

                product = await self._verify_single(page, candidate, original_url, vendor, goal=query)

                if product:
                    verified.append(product)
                    price_str = f"${product.price:.2f}" if product.price else "contact"
                    logger.info(f"[Verifier] Product {i+1} verified: {price_str} - {product.title[:40]}...")

                    # Quick viability check on verified product
                    is_viable = self._quick_viability_check(product, requirements, query)
                    if is_viable:
                        viable_count += 1
                        logger.info(f"[Verifier] Product {i+1} is VIABLE ({viable_count}/{target_viable})")
                    else:
                        logger.info(f"[Verifier] Product {i+1} verified but NOT VIABLE for requirements")

                else:
                    # Verification failed - create unverified product
                    logger.warning(f"[Verifier] Product {i+1} verification failed, returning unverified")
                    unverified = self._create_unverified_product(candidate, original_url, vendor)
                    if unverified:
                        verified.append(unverified)
                        # Unverified products get lower confidence in viability
                        logger.info(f"[Verifier] Product {i+1} returned as unverified")

                # Delay between products to avoid bot detection
                if i < len(to_verify) - 1:
                    await asyncio.sleep(3.0)

            except Exception as e:
                logger.error(f"[Verifier] Error verifying product {i+1}: {e}")
                unverified = self._create_unverified_product(candidate, original_url, vendor)
                if unverified:
                    verified.append(unverified)
                await self._ensure_on_listing(page, original_url)

        skipped = len(to_verify) - len(verified) - (len(to_verify) - i - 1 if 'i' in dir() else 0)
        logger.info(
            f"[Verifier] Verification complete: {len(verified)} verified, "
            f"{viable_count} viable, {len(to_verify) - len(verified)} skipped (early stop)"
        )
        return verified

    def _quick_viability_check(
        self,
        product: 'VerifiedProduct',
        requirements: Dict[str, Any],
        query: str
    ) -> bool:
        """
        Quick viability check on a verified product.

        This is a lightweight check to determine if a product likely matches
        requirements, used for early stopping decisions. The full viability
        filter runs later with LLM reasoning.

        Args:
            product: Verified product with title, price, specs
            requirements: User requirements
            query: User's query

        Returns:
            True if product appears viable, False otherwise
        """
        title = (product.title or "").lower()
        specs = product.specs or {}
        price = product.price

        query_lower = query.lower()

        # Check for NVIDIA GPU requirement
        wants_nvidia = any(kw in query_lower for kw in ["nvidia", "rtx", "geforce", "gtx"])
        if not wants_nvidia:
            req_gpu = str(requirements.get("gpu", "")).lower()
            wants_nvidia = any(kw in req_gpu for kw in ["nvidia", "rtx", "geforce"])

        if wants_nvidia:
            # Check if product has NVIDIA GPU
            has_nvidia = any(kw in title for kw in ["rtx", "geforce", "nvidia", "gtx"])
            if not has_nvidia:
                # Check specs
                gpu_spec = str(specs.get("gpu", "")).lower()
                has_nvidia = any(kw in gpu_spec for kw in ["rtx", "geforce", "nvidia", "gtx"])

            if not has_nvidia:
                # Check for integrated graphics (definite fail)
                has_integrated = any(kw in title for kw in ["intel uhd", "intel iris", "integrated"])
                if has_integrated:
                    return False

                # Unknown GPU - might be viable (let LLM decide later)
                # Don't reject unless we're confident it's wrong

        # Check price range
        price_range = requirements.get("price_range", {})
        if isinstance(price_range, dict):
            max_price = price_range.get("max")
            if max_price and price and price > max_price * 1.1:  # 10% tolerance
                return False

        # Check for wrong category keywords
        wrong_categories = ["chromebook", "macbook", "ipad", "tablet"]
        if any(cat in title for cat in wrong_categories):
            if wants_nvidia:
                return False

        # Default: assume viable (let full viability check decide)
        return True

    async def _verify_single(
        self,
        page: 'Page',
        candidate: Union[HTMLCandidate, VisualProduct, FusedProduct],
        original_url: str,
        vendor: str,
        goal: str = None
    ) -> Optional[VerifiedProduct]:
        """
        Verify a single product by navigating to its PDP.

        Strategy:
        1. If candidate has direct URL (HTMLCandidate), navigate directly
        2. If candidate has bbox (VisualProduct), click to navigate
        3. Extract data from PDP (with goal for targeted specs extraction)
        4. Navigate back
        """
        try:
            # Determine navigation strategy
            direct_url = self._get_url(candidate)
            has_bbox = self._get_bbox(candidate) is not None
            title = self._get_title(candidate)

            pdp_url = None
            verification_method = "unknown"

            # Strategy 1: Direct URL navigation (most reliable)
            if direct_url and self._is_valid_product_url(direct_url):
                logger.info(f"[Verifier] Using direct URL: {direct_url[:60]}...")
                await page.goto(direct_url, wait_until='domcontentloaded', timeout=10000)
                pdp_url = page.url
                verification_method = "direct_url"

            # Strategy 2: Click navigation (for Vision products)
            elif has_bbox or title:
                logger.info(f"[Verifier] Using click navigation for: {title[:40]}...")
                pdp_url = await self._click_to_pdp(page, candidate, original_url)
                if pdp_url:
                    verification_method = "pdp_navigation"

            if not pdp_url:
                logger.warning(f"[Verifier] Could not navigate to PDP for: {title[:40]}...")
                return None

            # Verify we're on a PDP (not homepage/search)
            if not self._is_valid_product_url(pdp_url):
                logger.warning(f"[Verifier] Navigation resulted in non-PDP URL: {pdp_url[:60]}...")
                await self._go_back(page, original_url)
                return None

            # Check for captcha/blocker and request intervention if needed
            captcha_ok = await self._check_and_handle_captcha(page, pdp_url)
            if not captcha_ok:
                logger.warning(f"[Verifier] Captcha blocked extraction for: {pdp_url[:60]}...")
                await self._go_back(page, original_url)
                return None

            # Extract verified data from PDP
            logger.info(f"[Verifier] Extracting data from PDP: {pdp_url[:60]}...")

            # Note: PDPExtractor handles smart waiting internally
            # Pass goal for targeted specs extraction (e.g., GPU specs for laptop queries)
            pdp_data = await self._extract_pdp_data(page, pdp_url, goal=goal)

            if not pdp_data:
                logger.warning(f"[Verifier] Failed to extract PDP data from: {pdp_url[:60]}...")
                await self._go_back(page, original_url)
                return None

            # Build verified product
            verified = VerifiedProduct(
                title=pdp_data.title or title,
                price=pdp_data.price,
                url=pdp_url,
                vendor=vendor,
                in_stock=pdp_data.in_stock,
                stock_status=pdp_data.stock_status,
                original_price=pdp_data.original_price,
                specs=pdp_data.specs,
                rating=pdp_data.rating,
                review_count=pdp_data.review_count,
                condition=pdp_data.condition,
                image_url=pdp_data.image_url,
                extraction_confidence=pdp_data.extraction_confidence,
                extraction_source=pdp_data.extraction_source,
                verification_method=verification_method,
                original_title=title,
                bbox=self._get_bbox(candidate)
            )

            # Navigate back to listing
            await self._go_back(page, original_url)

            return verified

        except Exception as e:
            logger.error(f"[Verifier] Error in _verify_single: {e}")
            await self._ensure_on_listing(page, original_url)
            return None

    async def _click_to_pdp(
        self,
        page: 'Page',
        candidate: Union[HTMLCandidate, VisualProduct, FusedProduct],
        original_url: str
    ) -> Optional[str]:
        """
        Click on a product to navigate to its PDP.

        Tries multiple strategies:
        1. Find and click link containing product title (multiple patterns)
        2. Click at bounding box coordinates
        """
        title = self._get_title(candidate)
        bbox = self._get_bbox(candidate)
        timeout_ms = self.config.click_resolve_timeout_ms

        context = page.context
        pages_before = len(context.pages)

        # Generate multiple search patterns from title
        search_patterns = self._generate_search_patterns(title)

        # Strategy 1: Find link by text (try multiple patterns)
        for pattern_idx, search_text in enumerate(search_patterns):
            try:
                logger.info(f"[Verifier] Search pattern {pattern_idx+1}/{len(search_patterns)}: '{search_text}'")
                link_locator = page.get_by_role("link").filter(
                    has_text=re.compile(re.escape(search_text), re.IGNORECASE)
                )
                link_count = await link_locator.count()
                logger.info(f"[Verifier] Link search result: {link_count} matches")

                if link_count > 0:
                    logger.info(f"[Verifier] Found {link_count} links with text '{search_text}'")

                    # Find a valid product link
                    for i in range(min(link_count, 5)):
                        try:
                            link = link_locator.nth(i)
                            href = await link.get_attribute('href')
                            link_text = await link.text_content() or ""

                            if href and self._is_valid_product_url(href):
                                logger.info(f"[Verifier] Clicking link: {href[:60]}...")
                                logger.debug(f"[Verifier] Link text: '{link_text[:60]}...'")
                                await link.click(timeout=timeout_ms)
                                return await self._wait_for_navigation(page, original_url, pages_before)
                        except Exception as e:
                            logger.debug(f"[Verifier] Link {i} click failed: {e}")
                            continue
            except Exception as e:
                logger.debug(f"[Verifier] Link search pattern {pattern_idx+1} failed: {e}")

        # Strategy 2: Coordinate click (if we have bbox)
        if bbox:
            try:
                center = bbox.center
                logger.info(f"[Verifier] Trying coordinate click at ({center[0]}, {center[1]})")

                # Scroll to make element visible
                page_y = center[1]
                scroll_y = max(0, page_y - 400)
                viewport_y = page_y - scroll_y

                if scroll_y > 0:
                    await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                    await asyncio.sleep(0.3)

                await page.mouse.click(center[0], viewport_y)
                return await self._wait_for_navigation(page, original_url, pages_before)

            except Exception as e:
                logger.debug(f"[Verifier] Coordinate click failed: {e}")

        return None

    async def _wait_for_navigation(
        self,
        page: 'Page',
        original_url: str,
        pages_before: int
    ) -> Optional[str]:
        """Wait for navigation and return new URL."""
        context = page.context

        # Brief wait for navigation
        await asyncio.sleep(0.5)

        # Check for new tab
        pages_after = context.pages
        if len(pages_after) > pages_before:
            new_page = pages_after[-1]
            await new_page.wait_for_load_state('domcontentloaded', timeout=5000)
            new_url = new_page.url
            await new_page.close()
            return new_url

        # Poll for URL change in same tab
        for attempt in range(6):
            await asyncio.sleep(0.5)
            current_url = page.url
            if current_url != original_url and not self._is_same_page(current_url, original_url):
                logger.info(f"[Verifier] URL changed after {(attempt+1)*0.5}s")
                return current_url

        return None

    async def _extract_pdp_data(self, page: 'Page', url: str, goal: str = None) -> Optional[PDPData]:
        """Extract product data from PDP."""
        if self.pdp_extractor:
            try:
                return await self.pdp_extractor.extract(page, url, goal=goal)
            except Exception as e:
                logger.error(f"[Verifier] PDP extraction failed: {e}")

        # Fallback: basic extraction
        return await self._basic_pdp_extraction(page, url)

    async def _basic_pdp_extraction(self, page: 'Page', url: str) -> Optional[PDPData]:
        """Basic PDP extraction when PDPExtractor not available."""
        try:
            # Try to find price
            price = None
            price_selectors = [
                '[data-testid="price"]',
                '.price',
                '[itemprop="price"]',
                '.product-price',
                '#price',
            ]

            for selector in price_selectors:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        text = await el.text_content()
                        if text:
                            price = self._parse_price(text)
                            if price:
                                break
                except Exception:
                    continue

            # Try to find title
            title = None
            title_selectors = ['h1', '[data-testid="product-title"]', '.product-title']

            for selector in title_selectors:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        title = await el.text_content()
                        if title:
                            title = title.strip()
                            break
                except Exception:
                    continue

            return PDPData(
                price=price,
                title=title,
                extraction_source="basic_selector",
                extraction_confidence=0.6
            )

        except Exception as e:
            logger.error(f"[Verifier] Basic PDP extraction failed: {e}")
            return None

    async def _go_back(self, page: 'Page', original_url: str) -> None:
        """Navigate back to listing page."""
        try:
            await page.go_back(timeout=5000)
            await page.wait_for_load_state('domcontentloaded', timeout=3000)
        except Exception:
            try:
                await page.goto(original_url, timeout=5000)
                await page.wait_for_load_state('domcontentloaded', timeout=3000)
            except Exception as e:
                logger.warning(f"[Verifier] Failed to return to listing: {e}")

    async def _ensure_on_listing(self, page: 'Page', original_url: str) -> None:
        """Ensure we're on the listing page."""
        try:
            if page.url != original_url:
                await page.goto(original_url, timeout=5000)
                await page.wait_for_load_state('domcontentloaded', timeout=3000)
        except Exception as e:
            logger.warning(f"[Verifier] Could not ensure on listing: {e}")

    def _create_unverified_product(
        self,
        candidate: Union[HTMLCandidate, VisualProduct, FusedProduct],
        listing_url: str,
        vendor: str
    ) -> Optional[VerifiedProduct]:
        """
        Create an unverified product when PDP verification fails.

        Returns a product with:
        - Title from the candidate
        - Listing page URL (not individual product URL)
        - Low confidence score
        - 'unverified' extraction source

        This ensures we return something useful even when verification fails.
        """
        try:
            title = self._get_title(candidate)
            if not title or len(title) < 3:
                return None

            # Get numeric price from candidate if available
            # Prefer price_numeric (always a float) over price (may be string like "$29.99")
            price = None
            if hasattr(candidate, 'price_numeric') and candidate.price_numeric:
                price = candidate.price_numeric
            elif hasattr(candidate, 'price') and candidate.price:
                # Try to extract numeric value if price is a string
                raw_price = candidate.price
                if isinstance(raw_price, (int, float)):
                    price = float(raw_price)
                elif isinstance(raw_price, str):
                    # Try to parse "$29.99" or "29.99" format
                    match = re.search(r'[\d,]+\.?\d*', raw_price)
                    if match:
                        try:
                            price = float(match.group().replace(',', ''))
                        except ValueError:
                            price = None

            return VerifiedProduct(
                title=title,
                price=price,
                url=listing_url,  # Use listing page URL since we couldn't get PDP URL
                vendor=vendor,
                in_stock=True,  # Assume in stock (we saw it on the listing)
                stock_status="unverified",
                extraction_confidence=0.5,  # Lower confidence since unverified
                extraction_source="listing_fallback",
                verification_method="unverified",
                original_title=title,
                bbox=self._get_bbox(candidate)
            )

        except Exception as e:
            logger.error(f"[Verifier] Error creating unverified product: {e}")
            return None

    # Helper methods

    def _generate_search_patterns(self, title: str) -> List[str]:
        """
        Generate multiple search patterns from a product title.

        Tries progressively shorter patterns to find a match.
        Example: "Acer Nitro V 16S Gaming Laptop RTX 4060 16GB"
        Returns: ["Acer Nitro V 16S", "Acer Nitro V", "Acer Nitro", "Nitro"]
        """
        if not title:
            return []

        # Clean title - remove punctuation that might break search
        clean_title = re.sub(r'["\'\(\)\[\]{}]', '', title)
        words = clean_title.split()

        if not words:
            return []

        patterns = []

        # Known laptop/hardware brands for smarter extraction
        brands = {
            'acer', 'asus', 'dell', 'hp', 'lenovo', 'msi', 'razer',
            'alienware', 'samsung', 'lg', 'gigabyte', 'microsoft',
            'apple', 'toshiba', 'huawei', 'xiaomi'
        }

        # Find brand position (usually first word)
        brand = None
        brand_idx = -1
        for i, word in enumerate(words[:3]):  # Brand usually in first 3 words
            if word.lower() in brands:
                brand = word
                brand_idx = i
                break

        # Pattern 1: First 4-5 words (most specific)
        if len(words) >= 4:
            patterns.append(' '.join(words[:5]))
            patterns.append(' '.join(words[:4]))

        # Pattern 2: First 3 words
        if len(words) >= 3:
            patterns.append(' '.join(words[:3]))

        # Pattern 3: Brand + next word (model line)
        if brand and brand_idx >= 0 and brand_idx + 1 < len(words):
            brand_model = f"{brand} {words[brand_idx + 1]}"
            if brand_model not in patterns:
                patterns.append(brand_model)

        # Pattern 4: First 2 words
        if len(words) >= 2:
            two_words = ' '.join(words[:2])
            if two_words not in patterns:
                patterns.append(two_words)

        # Pattern 5: Just brand name (last resort)
        if brand and brand not in patterns:
            patterns.append(brand)

        # Remove duplicates while preserving order
        seen = set()
        unique_patterns = []
        for p in patterns:
            p_lower = p.lower()
            if p_lower not in seen and len(p) >= 3:
                seen.add(p_lower)
                unique_patterns.append(p)

        logger.debug(f"[Verifier] Generated {len(unique_patterns)} search patterns from '{title[:40]}...': {unique_patterns}")
        return unique_patterns[:6]  # Limit to 6 patterns max

    def _get_title(self, candidate: Union[HTMLCandidate, VisualProduct, FusedProduct]) -> str:
        """Get title from any candidate type."""
        if isinstance(candidate, HTMLCandidate):
            return candidate.link_text or ""
        elif isinstance(candidate, VisualProduct):
            return candidate.title or ""
        elif isinstance(candidate, FusedProduct):
            return candidate.title or ""
        return ""

    def _get_url(self, candidate: Union[HTMLCandidate, VisualProduct, FusedProduct]) -> Optional[str]:
        """Get URL from candidate if available."""
        if isinstance(candidate, HTMLCandidate):
            return candidate.url
        elif isinstance(candidate, FusedProduct):
            return candidate.url if candidate.url else None
        return None

    def _get_bbox(self, candidate: Union[HTMLCandidate, VisualProduct, FusedProduct]) -> Optional[BoundingBox]:
        """Get bounding box from candidate if available."""
        if isinstance(candidate, VisualProduct):
            return candidate.bbox
        elif isinstance(candidate, FusedProduct):
            return candidate.bbox
        return None

    def _is_valid_product_url(self, url: str) -> bool:
        """Check if URL looks like a valid product page."""
        if not url:
            return False

        url_lower = url.lower()
        parsed = urlparse(url_lower)
        path = parsed.path.rstrip('/')
        hostname = parsed.netloc

        # Reject obvious non-product patterns
        reject_patterns = ['', '/', '/home', '/index', '/search', '/category', '/browse']
        if path in reject_patterns:
            return False

        # Reject navigation URLs
        if 'ref=nav_' in url_lower or 'ref=logo' in url_lower:
            return False

        # Reject Amazon sponsored/ad redirect URLs
        # These redirect to random promoted products, not search-relevant products
        if 'aax-us-east' in hostname or 'aax-' in hostname:
            logger.debug(f"[Verifier] Rejecting Amazon ad URL: {url[:60]}...")
            return False

        # Reject filter/search/category URLs (Best Buy specific and generic)
        reject_substrings = [
            'searchpage.jsp',   # Best Buy search/filter pages
            '_facet',           # Filter facets (brand, price, etc.)
            'modelfamily_facet',
            '/browse/',
            '/category/',
            'qp=',              # Query parameters for filters
        ]
        if any(s in url_lower for s in reject_substrings):
            return False

        # Reject captcha/blocker URLs (redirect to these means we're blocked)
        captcha_patterns = [
            '/splashui/captcha',  # eBay captcha
            '/blocked',           # Walmart, generic block pages
            '/captcha',           # Generic captcha
            '/challenge',         # Generic challenge pages
            '/verify',            # Generic verification
            '/sorry/',            # Google captcha
            'blocked?url=',       # Walmart with redirect
        ]
        if any(p in url_lower for p in captcha_patterns):
            logger.warning(f"[Verifier] Rejecting captcha/blocker URL: {url[:60]}...")
            return False

        # Check for product URL patterns
        # Note: removed '/site/' - too generic, matches Best Buy filter pages
        product_patterns = ['/dp/', '/product/', '/p/', '/ip/', '/pd/', '/sku/', '/item/']
        if any(p in path for p in product_patterns):
            return True

        # Check for PHP-style product URLs (common on smaller retailers)
        # e.g., index.php?main_page=product_info&products_id=123
        php_product_patterns = ['product_info', 'products_id=', 'product_id=', 'pid=', 'item_id=']
        if any(p in url_lower for p in php_product_patterns):
            return True

        # Accept if path has meaningful length and looks like a product slug
        return len(path) > 15

    def _is_same_page(self, url1: str, url2: str) -> bool:
        """Check if two URLs represent the same page."""
        p1 = urlparse(url1)
        p2 = urlparse(url2)
        return p1.netloc == p2.netloc and p1.path == p2.path

    def _parse_price(self, text: str) -> Optional[float]:
        """Parse price from text."""
        if not text:
            return None
        cleaned = re.sub(r'[^\d.]', '', text)
        try:
            price = float(cleaned)
            if 0 < price < 100000:  # Sanity check
                return price
        except (ValueError, TypeError):
            pass
        return None


# Convenience function
async def verify_products(
    page: 'Page',
    candidates: List[Union[HTMLCandidate, VisualProduct, FusedProduct]],
    original_url: str,
    vendor: str,
    pdp_extractor: 'PDPExtractor' = None,
    max_products: int = 5
) -> List[VerifiedProduct]:
    """
    Convenience function to verify products.

    Args:
        page: Playwright page
        candidates: Products to verify
        original_url: Listing page URL
        vendor: Retailer domain
        pdp_extractor: Optional PDPExtractor instance
        max_products: Maximum products to verify

    Returns:
        List of verified products
    """
    verifier = ProductVerifier(pdp_extractor=pdp_extractor, max_products=max_products)
    return await verifier.verify_products(page, candidates, original_url, vendor)
