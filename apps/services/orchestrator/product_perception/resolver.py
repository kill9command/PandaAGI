"""
URL Resolver - Click on products to capture their actual URLs.

Used as fallback when HTML fusion doesn't find a matching URL.
Also performs PDP (Product Detail Page) verification to get accurate prices.
"""

import asyncio
import logging
import re
from typing import List, Tuple, Optional, TYPE_CHECKING

from .models import FusedProduct, PDPData
from .config import get_config

if TYPE_CHECKING:
    from playwright.async_api import Page
    from .pdp_extractor import PDPExtractor

logger = logging.getLogger(__name__)


class URLResolver:
    """
    Resolves product URLs by clicking on them in the browser.

    Used as fallback when fusion fails to match a vision product
    to an HTML URL candidate.

    Also performs PDP verification to extract accurate prices.
    """

    def __init__(self, max_resolves: int = None, pdp_extractor: 'PDPExtractor' = None):
        self.config = get_config()
        self.max_resolves = max_resolves or self.config.max_click_resolves
        self.pdp_extractor = pdp_extractor
        self._pdp_verify_count = 0  # Track verifications per session

    async def resolve(self, page: 'Page', products: List[FusedProduct]) -> int:
        """
        Click on products to capture their URLs.

        Modifies products in-place, setting url and url_source.

        Args:
            page: Playwright page object
            products: List of products to resolve (filters to those needing resolution)

        Returns:
            Number of successfully resolved products
        """
        # Filter to products that need resolution
        needs_resolution = [
            p for p in products
            if p.url_source == "fallback" and p.bbox is not None
        ]

        if not needs_resolution:
            return 0

        # Limit number of clicks
        to_resolve = needs_resolution[:self.max_resolves]

        logger.info(f"[Resolver] Attempting to resolve {len(to_resolve)} product URLs via click")

        resolved_count = 0
        original_url = page.url

        for i, product in enumerate(to_resolve):
            success = await self._resolve_single(page, product, original_url)
            if success:
                resolved_count += 1

            # Rate limiting: delay between clicks to avoid bot detection
            if i < len(to_resolve) - 1:  # Don't delay after last item
                await asyncio.sleep(0.5)

        logger.info(f"[Resolver] Successfully resolved {resolved_count}/{len(to_resolve)} URLs")
        return resolved_count

    async def _resolve_single(
        self,
        page: 'Page',
        product: FusedProduct,
        original_url: str
    ) -> bool:
        """
        Resolve a single product's URL by clicking on it.

        Args:
            page: Playwright page
            product: Product to resolve
            original_url: URL to return to after clicking

        Returns:
            True if resolution successful
        """
        if not product.bbox:
            logger.warning(f"[Resolver] Product '{product.title[:30]}...' has no bbox, skipping")
            return False

        try:
            center = product.bbox.center
            timeout_ms = self.config.click_resolve_timeout_ms

            logger.info(f"[Resolver] Clicking '{product.title[:30]}...' at ({center[0]}, {center[1]}) [bbox: {product.bbox.x},{product.bbox.y} {product.bbox.width}x{product.bbox.height}]")

            # Strategy 1: Try to find and click a link containing the product title text
            # This is more reliable than clicking by coordinates
            # Clean title: remove special chars that break selectors
            clean_title = re.sub(r'["\'\(\)\[\]]', '', product.title)  # Remove quotes, parens, brackets
            title_words = clean_title.split()[:4]  # First 4 words
            search_text = ' '.join(title_words)
            short_text = ' '.join(title_words[:2])  # Define early for use in all strategies

            clicked = False
            found_href = None  # Store href in case click fails
            context = page.context
            pages_before = len(context.pages)

            try:
                # Look for a link containing the product title using get_by_text (more robust)
                logger.info(f"[Resolver] Searching for link with text: '{search_text}'")

                # Use get_by_text with substring matching - more robust than CSS selector
                link_locator = page.get_by_role("link").filter(has_text=re.compile(re.escape(search_text), re.IGNORECASE))
                link_count = await link_locator.count()
                logger.info(f"[Resolver] Found {link_count} links containing '{search_text}'")

                # Filter to find a product link (not search/filter links)
                if link_count > 0:
                    product_link, product_href = await self._find_product_link(link_locator, link_count, original_url)
                    if product_link and product_href:
                        found_href = product_href  # Save href in case click fails
                        logger.info(f"[Resolver] Found product link, clicking it")
                        await product_link.click(timeout=timeout_ms)
                        clicked = True

                if not clicked:
                    # Fallback: try broader search with first 2 words
                    logger.info(f"[Resolver] No exact link found, trying shorter text")
                    short_locator = page.get_by_role("link").filter(has_text=re.compile(re.escape(short_text), re.IGNORECASE))
                    short_count = await short_locator.count()
                    logger.info(f"[Resolver] Found {short_count} links with shorter text '{short_text}'")

                    if short_count > 0:
                        product_link, product_href = await self._find_product_link(short_locator, short_count, original_url)
                        if product_link and product_href:
                            found_href = product_href  # Save href in case click fails
                            logger.info(f"[Resolver] Found product link with shorter text, clicking it")
                            await product_link.click(timeout=timeout_ms)
                            clicked = True

                if not clicked:
                    # Strategy 3: Find element with product text, then find nearby link
                    logger.info(f"[Resolver] Trying container-based search for '{short_text}'")
                    # Product URL patterns for different retailers
                    product_url_selectors = [
                        'a[href*="/product/"]',   # Best Buy, generic
                        'a[href*="/dp/"]',        # Amazon
                        'a[href*="/p/"]',         # Newegg, generic
                        'a[href*="/ip/"]',        # Walmart
                        'a[href*="/pd/"]',        # Target
                        'a[href*="/site/"]',      # Best Buy old style
                    ]
                    try:
                        # Find any element containing the product text
                        text_element = page.get_by_text(re.compile(re.escape(short_text), re.IGNORECASE)).first
                        text_count = await text_element.count()
                        logger.info(f"[Resolver] Container search: found {text_count} text elements for '{short_text}'")

                        if text_count > 0:
                            # Look for a product link in the same container (parent elements)
                            # Go up to 5 levels to find a container with a product link
                            for level in range(5):
                                try:
                                    # XPath to find ancestor and then product link within
                                    container = text_element.locator(f"xpath=ancestor::*[{level + 1}]")
                                    container_count = await container.count()
                                    if container_count == 0:
                                        continue

                                    # Try each product URL pattern
                                    for selector in product_url_selectors:
                                        links = container.locator(selector)
                                        link_count = await links.count()

                                        if link_count > 0:
                                            # Check each link for relevance - don't just take the first!
                                            best_link = None
                                            best_href = None
                                            for link_idx in range(min(link_count, 5)):
                                                try:
                                                    link = links.nth(link_idx)
                                                    href = await link.get_attribute('href')
                                                    if not href:
                                                        continue

                                                    # Skip accessory/warranty links (common false positives)
                                                    if self._is_accessory_link(href):
                                                        logger.info(f"[Resolver] Skipping accessory/warranty link: {href[:60]}...")
                                                        continue

                                                    # Check if link matches the product we're looking for
                                                    link_text = await link.text_content() or ""
                                                    if self._link_matches_product(href, link_text, short_text):
                                                        best_link = link
                                                        best_href = href
                                                        logger.info(f"[Resolver] Found matching product link: {href[:60]}...")
                                                        break
                                                    elif best_link is None:
                                                        # Keep first non-accessory link as fallback
                                                        best_link = link
                                                        best_href = href
                                                except Exception as e:
                                                    logger.debug(f"[Resolver] Error checking link {link_idx}: {e}")
                                                    continue

                                            if best_href:
                                                logger.info(f"[Resolver] Container level {level+1}: using link {best_href[:60]}...")
                                                found_href = best_href
                                                logger.info(f"[Resolver] Found product link in container (level {level+1}): {best_href[:60]}...")
                                                await best_link.click(timeout=timeout_ms)
                                                clicked = True
                                                break

                                    if clicked:
                                        break
                                except Exception as e:
                                    logger.debug(f"[Resolver] Container level {level} search failed: {e}")
                                    continue

                            if not clicked:
                                logger.info(f"[Resolver] Container search: no product links found in any parent level")
                    except Exception as e:
                        logger.info(f"[Resolver] Container-based search failed: {e}")

                if not clicked:
                    # Last resort: coordinate click with scroll to ensure visibility
                    # bbox coordinates are in page coordinates, need to scroll and convert to viewport
                    page_y = center[1]
                    scroll_y = max(0, page_y - 400)  # Scroll so element is ~400px from top
                    viewport_y = page_y - scroll_y

                    logger.info(f"[Resolver] No product link found, trying coordinate click at page({center[0]}, {page_y}) -> viewport({center[0]}, {viewport_y})")

                    if scroll_y > 0:
                        await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                        await asyncio.sleep(0.3)

                    await page.mouse.click(center[0], viewport_y)

            except Exception as link_err:
                logger.info(f"[Resolver] Link search failed: {link_err}, trying coordinate click")
                # Use same scroll+viewport logic as the normal coordinate click
                page_y = center[1]
                scroll_y = max(0, page_y - 400)
                viewport_y = page_y - scroll_y
                if scroll_y > 0:
                    try:
                        await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                        await asyncio.sleep(0.3)
                    except Exception:
                        pass
                await page.mouse.click(center[0], viewport_y)

            # Wait for navigation or new tab with better detection
            new_url = None
            new_page = None

            try:
                # Check if a new tab was opened (target="_blank" links)
                await asyncio.sleep(0.3)  # Brief wait for new tab

                pages_after = context.pages
                if len(pages_after) > pages_before:
                    # New tab opened - get URL from new tab
                    new_page = pages_after[-1]
                    await new_page.wait_for_load_state('domcontentloaded', timeout=timeout_ms)
                    new_url = new_page.url
                    logger.info(f"[Resolver] New tab opened: {new_url[:60]}...")

                    # Close the new tab
                    await new_page.close()
                else:
                    # No new tab - poll for URL change (handles SPA/React routing)
                    # Best Buy uses client-side routing which may take time
                    for attempt in range(6):  # Up to 3 seconds total
                        await asyncio.sleep(0.5)
                        current_url = page.url
                        if current_url != original_url and not self._is_same_page(current_url, original_url):
                            new_url = current_url
                            logger.info(f"[Resolver] URL changed after {(attempt+1)*0.5}s")
                            break
                    else:
                        # No URL change detected after polling
                        new_url = page.url

            except Exception as e:
                logger.debug(f"[Resolver] Navigation check error: {e}")
                new_url = page.url

            logger.info(f"[Resolver] After click - original: {original_url[:60]}... new: {new_url[:60]}...")

            # Check if we navigated to a valid product page (not homepage/logo)
            is_different = new_url and new_url != original_url and not self._is_same_page(new_url, original_url)
            is_valid_product = is_different and self._is_valid_product_url(new_url, original_url)

            if is_valid_product:
                # Success - we navigated to a valid product page
                product.url = new_url
                product.url_source = "click_resolved"
                product.confidence = min(0.95, product.confidence + 0.15)
                product.extraction_method = "click_resolved"

                logger.info(f"[Resolver] ✓ Resolved via navigation: {new_url[:80]}...")

                # PDP Verification: Extract accurate price and details from the product page
                if self.pdp_extractor and self.config.enable_pdp_verification:
                    if self._pdp_verify_count < self.config.pdp_max_verify_per_retailer:
                        await self._verify_pdp(page, product, new_url)
                        self._pdp_verify_count += 1

                # Go back for next product (only if we navigated in same tab)
                if not new_page:
                    await self._go_back(page, original_url)
                return True

            else:
                # Navigation failed or went to invalid page (homepage, logo, etc.)
                # Check if we captured an href earlier that might be valid
                if found_href and self._is_valid_product_url(found_href, original_url):
                    # Use the href we captured from the link element
                    product.url = found_href
                    product.url_source = "href_resolved"
                    product.confidence = min(0.90, product.confidence + 0.10)
                    product.extraction_method = "href_resolved"

                    logger.info(f"[Resolver] ✓ Resolved via href (navigation was invalid): {found_href[:80]}...")
                    # Note: For href-resolved products, we can't verify PDP since we didn't navigate
                    # The page is still on the SERP
                    return True
                else:
                    # No valid href either - truly failed
                    if is_different and not is_valid_product:
                        logger.warning(f"[Resolver] Click navigated to invalid page (homepage/logo) for '{product.title[:30]}...'")
                        # Go back since we navigated to wrong page
                        await self._go_back(page, original_url)
                    else:
                        logger.warning(f"[Resolver] Click didn't navigate for '{product.title[:30]}...' - same page or no navigation")

                    # Try to close any popups and continue
                    await self._close_popups(page)
                    return False

        except Exception as e:
            logger.warning(f"[Resolver] Failed to resolve '{product.title[:30]}...': {e}")

            # Try to recover page state
            try:
                await self._go_back(page, original_url)
            except Exception:
                pass

            return False

    async def _find_product_link(self, locator, count: int, original_url: str) -> Tuple[Optional[any], Optional[str]]:
        """
        Find a link that looks like a product page, not a search/filter link.

        Args:
            locator: Playwright locator for links to check
            count: Number of links in the locator
            original_url: Original page URL to compare against

        Returns:
            Tuple of (link_element, href) or (None, None) if no product link found.
        """
        from urllib.parse import urlparse

        original_path = urlparse(original_url).path
        logger.info(f"[Resolver] Original URL path: {original_path}")

        # Patterns that indicate a search/filter page (NOT a product page)
        # Be conservative - only filter obvious search/filter URLs
        search_patterns = [
            'searchpage.jsp',  # Best Buy specific search page
            '/search?',        # Generic search query
            '/filter',         # Filter pages
            '/facet',          # Facet navigation
            's?k=',            # Amazon search
            '/s?ref=',         # Amazon search
            'pl?d=',           # Newegg search
        ]

        for i in range(min(count, 5)):  # Check up to 5 links
            try:
                link = locator.nth(i)
                is_visible = await link.is_visible(timeout=500)
                if not is_visible:
                    logger.info(f"[Resolver] Link {i} not visible, skipping")
                    continue

                href = await link.get_attribute('href')
                if not href:
                    logger.info(f"[Resolver] Link {i} has no href, skipping")
                    continue

                # Skip javascript: links
                if href.startswith('javascript:'):
                    logger.info(f"[Resolver] Link {i} is javascript:, skipping")
                    continue

                # Skip anchor-only links
                if href.startswith('#'):
                    logger.info(f"[Resolver] Link {i} is anchor-only, skipping")
                    continue

                # Parse the href
                parsed = urlparse(href)
                link_path = parsed.path.lower()
                full_href = href.lower()
                logger.info(f"[Resolver] Checking link {i}: path={link_path[:60]}, href={href[:80]}")

                # Skip if it looks like it stays on the search page
                is_search_link = any(pattern in link_path or pattern in full_href
                                    for pattern in search_patterns)

                # Also skip if it has the same path as original (search page)
                same_path = link_path == original_path.lower()

                if is_search_link or same_path:
                    logger.info(f"[Resolver] Skipping link (search={is_search_link}, same_path={same_path}): {href[:80]}...")
                    continue

                # This looks like a product link!
                logger.info(f"[Resolver] Found product link candidate: {href[:60]}...")
                return link, href

            except Exception as e:
                logger.debug(f"[Resolver] Error checking link {i}: {e}")
                continue

        logger.info(f"[Resolver] No product links found among {count} candidates")
        return None, None

    async def _go_back(self, page: 'Page', original_url: str) -> None:
        """Navigate back to original page."""
        try:
            # Try browser back first
            await page.go_back(timeout=3000)
            await page.wait_for_load_state('domcontentloaded', timeout=3000)
        except Exception as e:
            logger.debug(f"[Resolver] go_back failed, trying direct navigation: {e}")
            # Fallback: navigate directly
            try:
                await page.goto(original_url, timeout=5000)
                await page.wait_for_load_state('domcontentloaded', timeout=3000)
            except Exception as e2:
                logger.warning(f"[Resolver] Failed to return to original page: {e2}")

    async def _close_popups(self, page: 'Page') -> None:
        """Try to close any popups or modals."""
        try:
            # Common close button selectors
            close_selectors = [
                'button[aria-label="Close"]',
                'button.close',
                '.modal-close',
                '[data-dismiss="modal"]',
                'button:has-text("Close")',
                'button:has-text("X")',
            ]

            for selector in close_selectors:
                try:
                    close_btn = page.locator(selector).first
                    if await close_btn.is_visible(timeout=500):
                        await close_btn.click(timeout=1000)
                        await asyncio.sleep(0.3)
                        break
                except Exception as e:
                    logger.debug(f"[Resolver] Close button selector {selector} failed: {e}")
                    continue

        except Exception as e:
            logger.debug(f"[Resolver] close_popups failed: {e}")

    def _is_same_page(self, url1: str, url2: str) -> bool:
        """Check if two URLs represent the same page (ignoring params)."""
        from urllib.parse import urlparse

        p1 = urlparse(url1)
        p2 = urlparse(url2)

        # Same if path is identical
        return p1.netloc == p2.netloc and p1.path == p2.path

    def _is_valid_product_url(self, url: str, original_url: str) -> bool:
        """
        Check if URL looks like a valid product page, not homepage or error.

        This prevents false positives where clicking navigates to homepage
        (e.g., clicking Amazon logo goes to amazon.com/ref=nav_logo).
        """
        from urllib.parse import urlparse

        if not url:
            return False

        parsed = urlparse(url)
        path = parsed.path.lower().rstrip('/')

        # Reject obvious non-product patterns
        homepage_patterns = [
            '',           # Empty path (homepage)
            '/',          # Root
            '/en',        # Language root
            '/us',        # Country root
            '/home',      # Explicit homepage
            '/index',     # Index page
        ]

        if path in homepage_patterns:
            logger.info(f"[Resolver] Rejecting URL as homepage pattern: {url[:60]}...")
            return False

        # Reject Amazon logo/navigation URLs
        if 'ref=nav_' in url.lower() or 'ref=logo' in url.lower():
            logger.info(f"[Resolver] Rejecting URL as navigation/logo link: {url[:60]}...")
            return False

        # Reject search/category pages (staying on same type of page)
        search_patterns = ['/s?', '/search', '/searchpage', '/category', '/browse']
        if any(p in path for p in search_patterns):
            logger.info(f"[Resolver] Rejecting URL as search/category page: {url[:60]}...")
            return False

        # Look for positive product patterns
        product_patterns = [
            '/dp/',         # Amazon
            '/gp/product/', # Amazon alternative
            '/p/',          # Newegg, generic
            '/ip/',         # Walmart
            '/pd/',         # Target
            '/product/',    # Generic
            '/site/',       # BestBuy
            '/sku/',        # Generic
        ]

        # If path has product pattern, definitely valid
        if any(p in path for p in product_patterns):
            return True

        # Path should be longer than just a few segments for a product
        # e.g., "/some-laptop-model-name-12345" is likely a product
        path_segments = [s for s in path.split('/') if s]
        if len(path_segments) >= 1 and len(path_segments[0]) > 10:
            return True

        # Default: accept if it's different from original and not obviously bad
        return True

    def _is_accessory_link(self, href: str) -> bool:
        """
        Check if link is for an accessory, warranty, or protection plan.

        These are common false positives when searching for product links
        in a container - the container often includes related product links.

        Args:
            href: The link's href attribute

        Returns:
            True if this looks like an accessory/warranty link to skip
        """
        if not href:
            return False

        href_lower = href.lower()

        # Skip patterns for common non-product links
        skip_patterns = [
            'geek-squad',
            'geeksquad',
            'protection-plan',
            'protection/',
            'warranty',
            'insurance',
            'care-plan',
            'careplan',
            'applecare',
            'accidental',
            'extended-warranty',
            'service-plan',
            '/accessories/',
            '/accessory/',
            'add-on',
            '/cart',
            '/checkout',
            'add-to-cart',
            'addtocart',
        ]

        return any(pattern in href_lower for pattern in skip_patterns)

    def _link_matches_product(self, href: str, link_text: str, product_title: str) -> bool:
        """
        Check if a link is likely for the target product.

        Verifies that either the URL or link text contains keywords
        from the product title we're looking for.

        Args:
            href: The link's href attribute
            link_text: The visible text of the link
            product_title: The product title we're searching for

        Returns:
            True if the link appears to be for the target product
        """
        if not href or not product_title:
            return False

        href_lower = href.lower()
        text_lower = (link_text or "").lower()

        # Extract significant words from product title (skip common words)
        stop_words = {'the', 'a', 'an', 'with', 'and', 'or', 'for', 'in', 'on'}
        title_words = [
            word for word in product_title.lower().split()
            if len(word) > 2 and word not in stop_words
        ][:4]  # First 4 significant words

        if not title_words:
            return True  # Can't verify, assume match

        # Check if any title word appears in href or link text
        matches = sum(
            1 for word in title_words
            if word in href_lower or word in text_lower
        )

        # Require at least 1 match for short titles, 2 for longer
        required_matches = 1 if len(title_words) <= 2 else 2
        return matches >= required_matches

    async def _verify_pdp(self, page: 'Page', product: FusedProduct, url: str) -> None:
        """
        Verify product data from the Product Detail Page.

        This extracts accurate price, title, and other details from the actual
        product page, fixing the SERP price accuracy issue.

        Args:
            page: Playwright page (already on PDP)
            product: Product to update with verified data
            url: Current PDP URL
        """
        try:
            logger.info(f"[Resolver] Verifying PDP for '{product.title[:30]}...'")

            # Wait a moment for page to fully render (React/dynamic content)
            await asyncio.sleep(0.5)

            # Extract PDP data
            pdp_data = await self.pdp_extractor.extract(page, url)

            if not pdp_data:
                logger.warning(f"[Resolver] PDP verification failed - no data extracted")
                return

            # Store the full PDP data
            product.pdp_data = pdp_data
            product.pdp_verified = True

            # Update product with verified data
            if pdp_data.price is not None:
                product.verified_price = pdp_data.price

                # Track price discrepancy for monitoring
                if product.price is not None and self.config.pdp_track_discrepancies:
                    discrepancy = abs(product.price - pdp_data.price)
                    product.price_discrepancy = discrepancy

                    if product.price > 0:
                        pct_diff = discrepancy / product.price
                        if pct_diff > self.config.pdp_discrepancy_threshold:
                            logger.warning(
                                f"[PDPVerify] Price discrepancy: SERP=${product.price:.2f} vs "
                                f"PDP=${pdp_data.price:.2f} (diff=${discrepancy:.2f}, {pct_diff*100:.1f}%) "
                                f"for '{product.title[:40]}...'"
                            )

            if pdp_data.title:
                product.verified_title = pdp_data.title

            if pdp_data.original_price is not None:
                product.original_price = pdp_data.original_price

            # Stock status
            product.in_stock = pdp_data.in_stock
            product.stock_status = pdp_data.stock_status

            # Product details
            product.condition = pdp_data.condition
            product.rating = pdp_data.rating
            product.review_count = pdp_data.review_count
            product.specs = pdp_data.specs

            # Boost confidence for verified products
            product.confidence = min(0.98, product.confidence + 0.05)

            serp_price_str = f"${product.price:.2f}" if product.price else "N/A"
            pdp_price_str = f"${pdp_data.price:.2f}" if pdp_data.price else "N/A"
            logger.info(
                f"[Resolver] ✓ PDP verified: {pdp_price_str} "
                f"(SERP was {serp_price_str}) "
                f"stock={pdp_data.stock_status} "
                f"source={pdp_data.extraction_source}"
            )

        except Exception as e:
            logger.warning(f"[Resolver] PDP verification error: {e}")
            # Don't fail the resolution - we still have the URL
