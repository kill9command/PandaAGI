"""
PDP (Product Detail Page) Extractor - Universal extraction with proven fallbacks.

Extracts product data from PDPs using multiple strategies:
1. JSON-LD structured data (fast path when available)
2. Known-good selectors for major retailers (reliable fallback)
3. LLM-calibrated selectors (learns for new sites)
4. Vision extraction (screenshot → OCR → spatial analysis)

Major retailers have proven selectors as fallback when LLM calibration fails.
"""

# Known-good selectors for major retailers
# These are tested and reliable - used as fallback when LLM calibration fails
KNOWN_SITE_SELECTORS = {
    "bestbuy.com": {
        "price": '[data-testid="customer-price"] span[aria-hidden="true"]',
        "price_alt": '.priceView-hero-price span[aria-hidden="true"]',
        "title": '.sku-title h1, [data-testid="sku-title"]',
        "cart": '[data-button-state="ADD_TO_CART"], .add-to-cart-button',
    },
    "amazon.com": {
        "price": '#corePrice_feature_div .a-offscreen, .a-price .a-offscreen',
        "price_alt": '#priceblock_ourprice, #priceblock_dealprice',
        "title": '#productTitle',
        "cart": '#add-to-cart-button',
    },
    "walmart.com": {
        "price": '[itemprop="price"], [data-testid="price-wrap"]',
        "price_alt": '.price-characteristic',
        "title": 'h1[itemprop="name"]',
        "cart": '[data-testid="add-to-cart-btn"]',
    },
    "newegg.com": {
        "price": '.price-current',
        "price_alt": '.product-price .price',
        "title": '.product-title',
        "cart": '.btn-primary[title*="Add to cart"]',
    },
    "petco.com": {
        # Petco uses data-testid attributes - these are stable
        "price": '[data-testid*="price"] span, [data-testid*="Price"] span',
        "price_alt": '[class*="PurchaseTypePrice"], [class*="mainPrice"]',
        "title": 'h1',
        "cart": 'button[data-testid*="add-to-cart"], button[aria-label*="Add to Cart"]',
        # Pet supplies have low prices ($5-$100) - don't apply laptop sanity check
        "min_price": 1.0,
    },
    "petsmart.com": {
        # Similar structure to Petco
        "price": '[data-testid*="price"], .product-price',
        "price_alt": '[class*="price"]',
        "title": 'h1',
        "cart": 'button[data-testid*="add-to-cart"], .add-to-cart',
        "min_price": 1.0,
    },
}

import asyncio
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, TYPE_CHECKING
from urllib.parse import urlparse
from dataclasses import dataclass

from .models import PDPData
from .config import get_config

if TYPE_CHECKING:
    from playwright.async_api import Page

from apps.services.tool_server.shared.llm_utils import load_prompt_via_recipe as _load_prompt_via_recipe

logger = logging.getLogger(__name__)


def _load_prompt(prompt_name: str) -> str:
    """Load prompt - maps legacy names to recipe names."""
    return _load_prompt_via_recipe(prompt_name, "tools")


@dataclass
class OCRResult:
    """OCR result with text and bounding box."""
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2

    @property
    def area(self) -> int:
        return self.width * self.height


class PDPExtractor:
    """
    Universal PDP extractor using vision-based spatial analysis.

    Strategy:
    1. JSON-LD (fast path - structured data when available)
    2. Vision extraction (works on ANY page):
       - Screenshot → OCR → find Add to Cart → find price nearby → find title above
    """

    # Patterns for finding cart/buy buttons
    CART_BUTTON_PATTERNS = [
        r'add to cart',
        r'add to bag',
        r'buy now',
        r'add to basket',
        r'purchase',
        r'order now',
    ]

    # Price pattern
    PRICE_PATTERN = re.compile(r'\$[\d,]+\.?\d{0,2}')

    def __init__(self, timeout_ms: int = None):
        self.config = get_config()
        self.timeout_ms = timeout_ms or self.config.pdp_verification_timeout_ms
        self._ocr_engine = None

    def _get_ocr_engine(self):
        """Lazy-load EasyOCR engine."""
        if self._ocr_engine is None:
            import easyocr
            self._ocr_engine = easyocr.Reader(['en'], gpu=False, verbose=False)
            logger.info("[PDPExtractor] EasyOCR initialized")
        return self._ocr_engine

    async def extract(self, page: 'Page', url: str, goal: str = None) -> Optional[PDPData]:
        """
        Extract product data from a PDP including specs.

        Args:
            page: Playwright page object (already on PDP)
            url: Current page URL
            goal: User's search goal (used for targeted specs extraction)

        Returns:
            PDPData with verified product info and specs, or None if extraction failed
        """
        try:
            logger.info(f"[PDPExtractor] Extracting from: {url[:60]}...")

            # Wait for page to stabilize and price to appear
            await self._wait_for_price_content(page)

            # === STEP 1: Extract specs from multiple sources ===
            # Priority: JSON-LD > HTML tables > LLM (for electronics)
            specs = {}

            # Try JSON-LD specs first (most reliable)
            jsonld_specs = await self._extract_specs_from_json_ld(page)
            if jsonld_specs:
                specs.update(jsonld_specs)
                logger.info(f"[PDPExtractor] JSON-LD specs: {list(jsonld_specs.keys())}")

            # Try HTML table/dl specs (fills gaps)
            html_specs = await self._extract_specs_from_html(page)
            if html_specs:
                # Only add specs not already found in JSON-LD
                for key, value in html_specs.items():
                    if key not in specs:
                        specs[key] = value
                if html_specs:
                    logger.info(f"[PDPExtractor] HTML specs added: {[k for k in html_specs if k not in jsonld_specs]}")

            # Use LLM for electronics if critical specs missing
            if goal and self._needs_llm_specs(specs, goal):
                logger.info("[PDPExtractor] Critical specs missing, using LLM extraction...")
                llm_specs = await self._extract_specs_with_llm(page, goal)
                for key, value in llm_specs.items():
                    if key not in specs:
                        specs[key] = value

            if specs:
                logger.info(f"[PDPExtractor] Total specs extracted: {list(specs.keys())}")

            # === STEP 2: Extract price/title using existing strategies ===

            # Strategy 1: Try JSON-LD first (fast, reliable when present)
            json_ld_data = await self._extract_json_ld(page)
            if json_ld_data and json_ld_data.price is not None:
                json_ld_data.specs = specs  # Add specs
                logger.info(f"[PDPExtractor] ✓ JSON-LD: ${json_ld_data.price} - {json_ld_data.title[:50] if json_ld_data.title else 'No title'}...")
                return json_ld_data

            # Strategy 2: Try known-good selectors for major retailers (fast, reliable)
            logger.info("[PDPExtractor] JSON-LD not found, trying known selectors...")
            known_data = await self._extract_with_known_selectors(page, url)
            if known_data and known_data.price is not None:
                known_data.specs = specs  # Add specs
                logger.info(f"[PDPExtractor] ✓ Known selectors: ${known_data.price} - {known_data.title[:50] if known_data.title else 'No title'}...")
                return known_data

            # Strategy 3: LLM-calibrated HTML extraction (learns for new sites)
            logger.info("[PDPExtractor] Known selectors not found, trying LLM-calibrated extraction...")
            html_data = await self._extract_with_html(page, url)
            if html_data and html_data.price is not None:
                html_data.specs = specs  # Add specs
                logger.info(f"[PDPExtractor] ✓ LLM-calibrated: ${html_data.price} - {html_data.title[:50] if html_data.title else 'No title'}...")
                return html_data

            # Strategy 4: Vision-based extraction (fallback when HTML fails)
            logger.info("[PDPExtractor] HTML extraction failed, using vision extraction...")
            vision_data = await self._extract_with_vision(page, url)
            if vision_data and vision_data.price is not None:
                vision_data.specs = specs  # Add specs
                logger.info(f"[PDPExtractor] ✓ Vision: ${vision_data.price} - {vision_data.title[:50] if vision_data.title else 'No title'}...")
                return vision_data

            logger.warning(f"[PDPExtractor] All extraction methods failed for {url[:60]}...")
            return None

        except Exception as e:
            logger.error(f"[PDPExtractor] Extraction failed: {e}")
            return None

    async def _wait_for_price_content(self, page: 'Page', timeout: float = 10.0) -> bool:
        """
        Wait for price content to appear on the page.

        Waits for common price selectors, then scrolls to ensure price is visible.
        Returns True if price content found, False if timeout.
        """
        import time
        start = time.time()

        # Common price selectors across retailers
        price_selectors = [
            '[data-testid*="price"]',           # BestBuy, eBay
            '[class*="price"]',                 # Generic
            '[class*="Price"]',                 # Generic capitalized
            '[itemprop="price"]',               # Schema.org
            '.priceView-hero-price',            # BestBuy specific
            '.price-characteristic',            # Walmart
            '#priceblock_ourprice',             # Amazon
            '.a-price-whole',                   # Amazon
            '.product-price',                   # Generic
            '[data-price]',                     # Generic data attribute
        ]

        logger.info(f"[PDPExtractor] Waiting for price content to load...")

        # Try each selector with short timeout
        for selector in price_selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                if count > 0:
                    # Found price element, wait for it to be visible
                    try:
                        await locator.first.wait_for(state='visible', timeout=2000)
                        logger.info(f"[PDPExtractor] ✓ Price element found: {selector}")

                        # Scroll to ensure price is in viewport
                        await locator.first.scroll_into_view_if_needed()
                        await asyncio.sleep(0.3)  # Brief wait for render
                        return True
                    except Exception:
                        pass  # Element exists but not visible, try next
            except Exception:
                continue

            # Check timeout
            if time.time() - start > timeout:
                break

        # Fallback: look for $ signs in page text
        try:
            # Check if page has any price text
            body_text = await page.locator('body').text_content()
            if body_text and '$' in body_text:
                logger.info(f"[PDPExtractor] Found $ in page content, continuing...")
                # Scroll down a bit to reveal price area (often below hero image)
                await page.evaluate("window.scrollBy(0, 300)")
                await asyncio.sleep(0.5)
                return True
        except Exception:
            pass

        # Last resort: just wait a bit for JS to render
        remaining = timeout - (time.time() - start)
        if remaining > 0:
            logger.info(f"[PDPExtractor] No price selector found, waiting {remaining:.1f}s for render...")
            await asyncio.sleep(min(remaining, 3.0))

        return False

    async def _extract_with_known_selectors(self, page: 'Page', url: str) -> Optional[PDPData]:
        """
        Extract using known-good selectors for major retailers.

        This is a fast, reliable path for sites we've tested thoroughly.
        Falls back gracefully if selectors don't match (site may have changed).
        """
        domain = self._get_vendor(url)
        selectors = KNOWN_SITE_SELECTORS.get(domain)

        if not selectors:
            logger.debug(f"[PDPExtractor] No known selectors for {domain}")
            return None

        logger.info(f"[PDPExtractor] Trying known selectors for {domain}")

        try:
            # JavaScript to extract using known selectors
            js_code = """
            (selectors) => {
                const result = { price: null, title: null, in_stock: true };

                // Helper to clean price
                function cleanPrice(text) {
                    if (!text) return null;
                    const match = text.match(/\\$?([\\d,]+\\.?\\d*)/);
                    if (!match) return null;
                    const num = parseFloat(match[1].replace(/,/g, ''));
                    return isNaN(num) ? null : num;
                }

                // Try primary price selector
                if (selectors.price) {
                    const priceEl = document.querySelector(selectors.price);
                    if (priceEl) {
                        result.price = cleanPrice(priceEl.textContent);
                    }
                }

                // Try alternate price selector
                if (!result.price && selectors.price_alt) {
                    const priceEl = document.querySelector(selectors.price_alt);
                    if (priceEl) {
                        result.price = cleanPrice(priceEl.textContent);
                    }
                }

                // Try title selector
                if (selectors.title) {
                    const titleEl = document.querySelector(selectors.title);
                    if (titleEl) {
                        result.title = titleEl.textContent?.trim().slice(0, 300);
                    }
                }

                // Check cart button for stock status
                if (selectors.cart) {
                    const cartEl = document.querySelector(selectors.cart);
                    result.in_stock = cartEl && cartEl.offsetHeight > 0;
                }

                return result;
            }
            """

            result = await page.evaluate(js_code, selectors)

            if result and result.get('price'):
                price = result['price']
                title = result.get('title') or "Unknown Product"
                in_stock = result.get('in_stock', True)

                # Per-site minimum price (pet stores have low prices, electronics are higher)
                # Default min $1 to filter garbage but accept cheap products
                min_price = selectors.get('min_price', 1)
                if price < min_price:
                    logger.warning(f"[PDPExtractor] Known selector price ${price} too low for {domain} (min: ${min_price}), skipping")
                    return None

                return PDPData(
                    price=price,
                    title=title,
                    in_stock=in_stock,
                    stock_status="in_stock" if in_stock else "out_of_stock",
                    extraction_source="known_selectors",
                    extraction_confidence=0.95,  # High confidence - proven selectors
                )
            else:
                logger.debug(f"[PDPExtractor] Known selectors found no price for {domain}")
                return None

        except Exception as e:
            logger.debug(f"[PDPExtractor] Known selector extraction failed: {e}")
            return None

    async def _extract_with_html(self, page: 'Page', url: str) -> Optional[PDPData]:
        """
        Extract product data using LLM-calibrated selectors.

        Uses the SmartCalibrator pattern:
        1. First visit: LLM analyzes page → learns selectors → cached
        2. Repeat visits: Use cached selectors (fast, no LLM)
        3. Failure: Re-calibrate with LLM

        NO hardcoded selectors. Learns for ANY website.
        """
        try:
            # Using PageIntelligence adapter for backwards compatibility
            from apps.services.tool_server.page_intelligence.legacy_adapter import get_smart_calibrator

            calibrator = get_smart_calibrator()
            domain = self._get_vendor(url)

            # Check if we have a cached PDP schema for this domain
            schema = calibrator.get_schema(url)

            # If no schema or schema is for listing page, calibrate for PDP
            if not schema or schema.page_type != "pdp":
                logger.info(f"[PDPExtractor] No PDP schema for {domain}, running LLM calibration...")
                schema = await self._calibrate_pdp(page, url, calibrator)

            if not schema or not schema.price_selector:
                logger.debug(f"[PDPExtractor] Calibration returned no price selector")
                return None

            # Use the learned selectors to extract
            result = await self._extract_with_learned_selectors(page, schema)

            if result and result.get('price'):
                price = result['price']
                title = result.get('title') or "Unknown Product"
                in_stock = result.get('in_stock', True)

                # Domain-aware sanity check
                site_selectors = KNOWN_SITE_SELECTORS.get(domain, {})
                # Default min $1 to filter garbage but accept cheap products
                min_price = site_selectors.get('min_price', 1)
                if price < min_price:
                    logger.warning(f"[PDPExtractor] Learned selector returned low price ${price} for {domain} (min: ${min_price}), marking as failure")
                    schema.record_failure("price_too_low")
                    calibrator._save_schema(schema)
                    return None

                # Record success
                schema.record_success()
                calibrator._save_schema(schema)

                logger.info(f"[PDPExtractor] LLM-calibrated extraction: ${price} - {title[:50]}...")

                return PDPData(
                    price=price,
                    title=title,
                    in_stock=in_stock,
                    stock_status="in_stock" if in_stock else "out_of_stock",
                    extraction_source="llm_calibrated",
                    extraction_confidence=0.90,
                )
            else:
                # Record failure and trigger re-calibration next time
                if schema:
                    schema.record_failure("no_price_found")
                    calibrator._save_schema(schema)
                logger.debug("[PDPExtractor] Learned selectors found no price")
                return None

        except Exception as e:
            logger.debug(f"[PDPExtractor] LLM-calibrated extraction failed: {e}")
            return None

    async def _calibrate_pdp(self, page: 'Page', url: str, calibrator) -> Optional['ExtractionSchema']:
        """
        Use LLM to learn PDP-specific selectors for this domain.

        Analyzes the page structure and asks LLM to generate:
        - Price selector
        - Title selector
        - Cart button selector (for stock detection)
        """
        import httpx
        import os

        domain = self._get_vendor(url)

        # Collect page info for LLM analysis
        page_info = await page.evaluate("""() => {
            const result = {
                url: location.href,
                title: document.title,
                priceElements: [],
                titleCandidates: [],
                cartButtons: [],
                metaData: {}
            };

            // Helper to build selector for an element
            // Priority: data-testid > id > semantic data-* > semantic class > tag
            function buildSelector(elem) {
                // 1. data-testid is most reliable (Best Buy, modern sites use these)
                const testId = elem.getAttribute('data-testid');
                if (testId && testId.length < 50) {
                    return `[data-testid="${testId}"]`;
                }

                // 2. ID selector
                if (elem.id && !elem.id.match(/^[0-9]/)) {
                    return '#' + elem.id;
                }

                // 3. Other useful data attributes (price, product, etc.)
                const dataAttrs = [...elem.attributes]
                    .filter(a => a.name.startsWith('data-') && a.value && a.value.length < 30)
                    .filter(a => a.name.includes('price') || a.name.includes('product') ||
                                 a.name.includes('sku') || a.name.includes('item'))
                    .slice(0, 1);
                if (dataAttrs.length > 0) {
                    return `[${dataAttrs[0].name}="${dataAttrs[0].value}"]`;
                }

                // 4. Class-based selector - filter out unstable class names
                const tailwindPatterns = /^(text-|font-|bg-|p-|m-|w-|h-|flex|grid|block|inline|hidden|relative|absolute|overflow|rounded|border|shadow|cursor|opacity|z-|gap-|space-|items-|justify-|align-|self-|order-|col-|row-)/;
                // CSS-in-JS patterns: styled-components (sc-), emotion (css-), etc.
                // These have hashes that change between deployments - NEVER use them
                const cssInJsPattern = /-sc-[a-f0-9]+|css-[a-f0-9]+|__[A-Za-z]+-[a-f0-9]+/;
                const classes = (elem.className?.toString() || '').split(' ')
                    .filter(c => c && c.length > 2 && !tailwindPatterns.test(c))
                    .filter(c => !cssInJsPattern.test(c));  // Exclude CSS-in-JS hashed classes

                // Prefer semantic class names WITHOUT hashes
                const semanticClass = classes.find(c =>
                    (c.includes('price') || c.includes('Price') ||
                    c.includes('title') || c.includes('Title') ||
                    c.includes('product') || c.includes('Product') ||
                    c.includes('heading') || c.includes('name')) &&
                    !c.match(/-[a-f0-9]{6,}/)  // No hex hashes
                );

                const tag = elem.tagName.toLowerCase();
                if (semanticClass) {
                    return `${tag}.${semanticClass}`;
                }

                // Fall back to first non-utility, non-hashed class
                const stableClass = classes.find(c => !c.match(/-[a-f0-9]{6,}/));
                if (stableClass) {
                    return `${tag}.${stableClass}`;
                }

                return tag;
            }

            // Find elements with price text
            const priceRegex = /^\\$[\\d,]+(\\.\\d{2})?$/;
            const allElems = document.querySelectorAll('*');

            for (const elem of allElems) {
                const text = (elem.textContent || '').trim();
                const rect = elem.getBoundingClientRect();

                // Skip invisible or off-screen elements
                if (rect.height === 0 || rect.y > 800) continue;

                // Check for price-like text
                if (priceRegex.test(text) && text.length < 15) {
                    result.priceElements.push({
                        selector: buildSelector(elem),
                        text: text,
                        tag: elem.tagName.toLowerCase(),
                        classes: elem.className?.toString().slice(0, 100) || '',
                        y: Math.round(rect.y),
                        parentSelector: elem.parentElement ? buildSelector(elem.parentElement) : ''
                    });
                }
            }

            // Find title candidates (h1, product title patterns)
            const titleElems = document.querySelectorAll('h1, [class*="product-title"], [class*="productTitle"], [id*="title"]');
            for (const elem of titleElems) {
                const text = (elem.textContent || '').trim();
                if (text.length > 10 && text.length < 300) {
                    result.titleCandidates.push({
                        selector: buildSelector(elem),
                        text: text.slice(0, 100),
                        tag: elem.tagName.toLowerCase()
                    });
                }
            }

            // Find cart/buy buttons
            const buttonPatterns = ['add to cart', 'buy now', 'add to bag', 'add to basket'];
            const buttons = document.querySelectorAll('button, input[type="submit"], a[role="button"], [class*="cart"], [class*="buy"]');
            for (const btn of buttons) {
                const text = (btn.textContent || btn.value || '').toLowerCase().trim();
                if (buttonPatterns.some(p => text.includes(p))) {
                    result.cartButtons.push({
                        selector: buildSelector(btn),
                        text: text.slice(0, 50),
                        visible: btn.offsetHeight > 0
                    });
                }
            }

            // Check for meta tags with price info
            const metaPrice = document.querySelector('meta[property="product:price:amount"]');
            if (metaPrice) {
                result.metaData.metaPriceSelector = 'meta[property="product:price:amount"]';
                result.metaData.metaPriceValue = metaPrice.content;
            }

            return result;
        }""")

        # Build LLM prompt - load base prompt from file
        base_prompt = _load_prompt("pdp_selector")
        if not base_prompt:
            # Fallback inline prompt if file not found
            base_prompt = """You are analyzing a Product Detail Page (PDP) to learn extraction selectors.

Choose the BEST CSS selector for:
1. The MAIN product price (not related products, not "was" price)
2. The product title
3. The Add to Cart button (for stock detection)

Respond with ONLY a JSON object (no markdown).

RULES:
1. Use the EXACT selectors from the discovered elements
2. For price, prefer elements with the actual price text, not containers
3. If multiple prices, choose the one closest to the cart button
4. Return empty string "" if you can't determine a selector
5. NEVER use CSS-in-JS hashed class names like "-sc-abc123" or "css-xyz789"
6. PREFER: [data-testid="..."], #id, or semantic class names like ".product-price"
7. AVOID: Classes with hash suffixes like "Price-sc-663c57fc-1" or "styled__Component-abc123" """

        prompt = f"""{base_prompt}

---

## Current Page Analysis

URL: {url}
Page Title: {page_info.get('title', 'Unknown')}

=== PRICE ELEMENTS FOUND (with $ symbol) ===
{json.dumps(page_info.get('priceElements', [])[:10], indent=2)}

=== TITLE CANDIDATES ===
{json.dumps(page_info.get('titleCandidates', [])[:5], indent=2)}

=== CART/BUY BUTTONS ===
{json.dumps(page_info.get('cartButtons', [])[:5], indent=2)}

=== META DATA ===
{json.dumps(page_info.get('metaData', {}), indent=2)}

JSON:"""

        # Call LLM
        try:
            solver_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
            solver_key = os.getenv("SOLVER_API_KEY", "qwen-local")
            solver_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    solver_url,
                    headers={"Authorization": f"Bearer {solver_key}"},
                    json={
                        "model": solver_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 500,
                        "temperature": 0.4,
                        "top_p": 0.8,
                        "stop": ["<|im_end|>", "<|endoftext|>"],
                        "repetition_penalty": 1.05
                    }
                )
                response.raise_for_status()
                content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")

                # Parse JSON response
                if "```" in content:
                    content = content.split("```")[1] if "```json" in content else content.split("```")[1]
                    content = content.replace("json", "").strip()

                start = content.find('{')
                end = content.rfind('}') + 1
                if start >= 0 and end > start:
                    data = json.loads(content[start:end])

                    # Using PageIntelligence adapter for backwards compatibility
                    from apps.services.tool_server.page_intelligence.legacy_adapter import ExtractionSchema
                    schema = ExtractionSchema(
                        domain=domain,
                        page_type="pdp",
                        price_selector=data.get("price_selector", ""),
                        title_selector=data.get("title_selector", ""),
                        product_card_selector=data.get("cart_button_selector", ""),  # Reuse field for cart button
                    )

                    logger.info(f"[PDPExtractor] LLM calibration complete: price={schema.price_selector}, title={schema.title_selector}")
                    calibrator._save_schema(schema)
                    return schema

        except Exception as e:
            logger.warning(f"[PDPExtractor] LLM calibration failed: {e}")

        return None

    async def _extract_with_learned_selectors(self, page: 'Page', schema) -> Optional[Dict]:
        """
        Extract product data using LLM-learned selectors.
        """
        price_selector = schema.price_selector
        title_selector = schema.title_selector
        cart_selector = schema.product_card_selector  # Reused for cart button

        js_code = f"""
        (selectors) => {{
            const result = {{ price: null, title: null, in_stock: true }};

            // Helper to clean price
            function cleanPrice(text) {{
                if (!text) return null;
                const match = text.match(/\\$?([\\d,]+\\.?\\d*)/);
                if (!match) return null;
                const num = parseFloat(match[1].replace(/,/g, ''));
                return isNaN(num) ? null : num;
            }}

            // Try price selector
            if (selectors.price) {{
                const priceEl = document.querySelector(selectors.price);
                if (priceEl) {{
                    result.price = cleanPrice(priceEl.textContent);
                }}
            }}

            // Try title selector
            if (selectors.title) {{
                const titleEl = document.querySelector(selectors.title);
                if (titleEl) {{
                    result.title = titleEl.textContent?.trim().slice(0, 300);
                }}
            }}

            // Check cart button for stock status
            if (selectors.cart) {{
                const cartEl = document.querySelector(selectors.cart);
                result.in_stock = cartEl && cartEl.offsetHeight > 0;
            }}

            // Fallback stock check
            if (!result.in_stock) {{
                const bodyText = document.body.textContent.toLowerCase();
                const outIndicators = ['out of stock', 'sold out', 'unavailable'];
                result.in_stock = !outIndicators.some(i => bodyText.includes(i));
            }}

            return result;
        }}
        """

        try:
            result = await page.evaluate(
                js_code,
                {"price": price_selector, "title": title_selector, "cart": cart_selector}
            )
            return result
        except Exception as e:
            logger.debug(f"[PDPExtractor] Selector extraction failed: {e}")
            return None

    async def _extract_with_vision(self, page: 'Page', url: str) -> Optional[PDPData]:
        """
        Extract product using vision: screenshot → OCR → spatial analysis.

        The algorithm:
        1. Screenshot the page
        2. OCR to get text with positions
        3. Find "Add to Cart" button location (indicates main product area)
        4. Find price closest to cart button
        5. Find title (large text above cart button area)
        6. Determine stock status from cart button presence
        """
        screenshot_path = None
        try:
            # Take screenshot
            screenshot_bytes = await page.screenshot(type='png', full_page=False)

            # Save to temp file for OCR
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(screenshot_bytes)
                screenshot_path = f.name

            # Run OCR
            ocr_results = self._run_ocr(screenshot_path)
            if not ocr_results:
                logger.warning("[PDPExtractor] OCR returned no results")
                return None

            logger.info(f"[PDPExtractor] OCR found {len(ocr_results)} text regions")

            # Find the main product using spatial analysis
            product = self._analyze_spatial_layout(ocr_results, url)
            return product

        except Exception as e:
            logger.error(f"[PDPExtractor] Vision extraction failed: {e}")
            return None
        finally:
            # Cleanup temp file
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    os.remove(screenshot_path)
                except OSError:
                    pass

    def _run_ocr(self, screenshot_path: str) -> List[OCRResult]:
        """Run OCR and return structured results with positions."""
        try:
            ocr = self._get_ocr_engine()
            raw_results = ocr.readtext(screenshot_path)

            results = []
            for item in raw_results:
                if len(item) < 3:
                    continue

                bbox_points, text, confidence = item[0], item[1], item[2]

                # Skip low confidence or empty text
                if confidence < 0.3 or not text.strip():
                    continue

                # Convert polygon to bounding box
                x_coords = [p[0] for p in bbox_points]
                y_coords = [p[1] for p in bbox_points]

                results.append(OCRResult(
                    text=text.strip(),
                    x=int(min(x_coords)),
                    y=int(min(y_coords)),
                    width=int(max(x_coords) - min(x_coords)),
                    height=int(max(y_coords) - min(y_coords)),
                    confidence=confidence
                ))

            return results

        except Exception as e:
            logger.error(f"[PDPExtractor] OCR failed: {e}")
            return []

    # Contact-based pricing patterns
    CONTACT_PRICE_PATTERNS = [
        r'contact\s*(us|for|price)?',
        r'inquire',
        r'call\s*(for|us)',
        r'email\s*(for|us)',
        r'request\s*(a\s*)?quote',
        r'adoption\s*fee',
        r'apply\s*(now|here)?',
        r'application',
        r'price\s*on\s*request',
        r'pricing\s*varies',
        r'ask\s*(for|about)',
    ]

    def _analyze_spatial_layout(self, ocr_results: List[OCRResult], url: str) -> Optional[PDPData]:
        """
        Analyze spatial layout to find the main product.

        Key insight: The "Add to Cart" button anchors the main product area.
        - Price is nearby (within ~200px)
        - Title is above
        - Related products are spatially separated

        Also handles contact-based pricing (breeders, services, etc.)
        """
        # Step 1: Find Add to Cart button
        cart_button = self._find_cart_button(ocr_results)

        # Step 2: Find all prices
        prices = self._find_prices(ocr_results)
        if not prices:
            # No $ prices found - check for contact-based pricing
            logger.info("[PDPExtractor] No $ prices found, checking for contact-based pricing...")
            contact_indicator = self._find_contact_pricing(ocr_results)
            if contact_indicator:
                logger.info(f"[PDPExtractor] Found contact-based pricing: '{contact_indicator}'")
                # Still extract the title
                title = self._find_title_from_page(ocr_results)
                vendor = self._get_vendor(url)
                return PDPData(
                    price=None,  # Contact-based - no numeric price
                    title=title or "Unknown Product",
                    in_stock=True,  # Assume available if contact info shown
                    stock_status="contact_for_availability",
                    extraction_source="vision_spatial_contact",
                    extraction_confidence=0.75,
                )
            logger.warning("[PDPExtractor] No prices found in OCR results")
            return None

        # Step 3: Determine main price
        if cart_button:
            # Find price closest to cart button
            main_price = self._find_closest_price(prices, cart_button)
            in_stock = True
            logger.info(f"[PDPExtractor] Found cart button at y={cart_button.y}, main price: ${main_price[0]}")
        else:
            # No cart button - might be out of stock
            # Use the most prominent price (largest, highest on page)
            main_price = self._find_most_prominent_price(prices)
            in_stock = False
            logger.info(f"[PDPExtractor] No cart button found (out of stock?), using prominent price: ${main_price[0]}")

        if not main_price:
            return None

        price_value, price_result = main_price

        # Step 3.5: Domain-aware sanity check - OCR often misreads prices
        # Different sites have different typical price ranges
        vendor = self._get_vendor(url)
        site_selectors = KNOWN_SITE_SELECTORS.get(vendor, {})
        # Default min $1 to filter garbage (star ratings ~4.5) but accept cheap products
        # Site-specific overrides for electronics sites that don't sell items under $50
        min_price = site_selectors.get('min_price', 1)

        # Pet stores (petco, petsmart) have low prices - $5-$100 is normal
        # Electronics (bestbuy, newegg) have high prices - $100+ is normal
        if price_value < min_price:
            logger.warning(f"[PDPExtractor] Vision price ${price_value} below minimum for {vendor} (${min_price})")
            # Try to find a larger price in the results
            larger_prices = [(p, r) for p, r in prices if p >= min_price]
            if larger_prices:
                # Use the closest larger price to cart button or most prominent
                if cart_button:
                    main_price = self._find_closest_price(larger_prices, cart_button)
                else:
                    main_price = self._find_most_prominent_price(larger_prices)
                if main_price:
                    price_value, price_result = main_price
                    logger.info(f"[PDPExtractor] Using corrected price: ${price_value}")
                else:
                    # For pet stores, accept low prices - they're likely correct
                    if min_price < 10:
                        logger.info(f"[PDPExtractor] Accepting low price ${price_value} for {vendor} (pet store)")
                    else:
                        return None
            else:
                # For pet stores, accept the low price
                if min_price < 10:
                    logger.info(f"[PDPExtractor] Accepting low price ${price_value} for {vendor} (pet store)")
                else:
                    return None

        # Step 4: Find title (large text above the price area)
        title = self._find_title(ocr_results, price_result, cart_button)

        # Step 5: Check for original/sale price
        original_price = self._find_original_price(prices, price_value, price_result)

        # Step 6: Extract vendor from URL
        vendor = self._get_vendor(url)

        return PDPData(
            price=price_value,
            title=title or "Unknown Product",
            original_price=original_price,
            in_stock=in_stock,
            stock_status="in_stock" if in_stock else "out_of_stock",
            extraction_source="vision_spatial",
            extraction_confidence=0.85 if cart_button else 0.70,
        )

    def _find_cart_button(self, ocr_results: List[OCRResult]) -> Optional[OCRResult]:
        """Find Add to Cart / Buy Now button."""
        for result in ocr_results:
            text_lower = result.text.lower()
            for pattern in self.CART_BUTTON_PATTERNS:
                if re.search(pattern, text_lower):
                    return result
        return None

    def _find_prices(self, ocr_results: List[OCRResult]) -> List[Tuple[float, OCRResult]]:
        """Find all price patterns and parse them."""
        prices = []
        for result in ocr_results:
            matches = self.PRICE_PATTERN.findall(result.text)
            for match in matches:
                price_val = self._parse_price(match)
                if price_val and 0.01 < price_val < 50000:  # Sanity check
                    prices.append((price_val, result))
        return prices

    def _find_closest_price(
        self,
        prices: List[Tuple[float, OCRResult]],
        anchor: OCRResult,
        max_distance: int = 300
    ) -> Optional[Tuple[float, OCRResult]]:
        """Find price closest to anchor point (cart button)."""
        if not prices:
            return None

        def distance(p: OCRResult) -> float:
            dx = abs(p.center_x - anchor.center_x)
            dy = abs(p.center_y - anchor.center_y)
            return (dx**2 + dy**2) ** 0.5

        # Sort by distance to anchor
        sorted_prices = sorted(prices, key=lambda x: distance(x[1]))

        # Return closest if within max distance
        closest = sorted_prices[0]
        if distance(closest[1]) <= max_distance:
            return closest

        return sorted_prices[0]  # Return closest anyway

    def _find_most_prominent_price(
        self,
        prices: List[Tuple[float, OCRResult]]
    ) -> Optional[Tuple[float, OCRResult]]:
        """Find most prominent price (for pages without cart button)."""
        if not prices:
            return None

        # Score by: higher on page (lower y) + larger area
        def prominence_score(item: Tuple[float, OCRResult]) -> float:
            price, result = item
            # Higher on page is better (lower y = higher score)
            y_score = 1000 - result.y
            # Larger text is better
            area_score = result.area / 100
            return y_score + area_score

        return max(prices, key=prominence_score)

    def _find_title(
        self,
        ocr_results: List[OCRResult],
        price_result: OCRResult,
        cart_button: Optional[OCRResult]
    ) -> Optional[str]:
        """Find product title (large text above price/cart area)."""
        # Define the "product area" y-coordinate
        if cart_button:
            product_area_y = min(price_result.y, cart_button.y)
        else:
            product_area_y = price_result.y

        # Find text above the product area
        candidates = [
            r for r in ocr_results
            if r.y < product_area_y - 20  # At least 20px above
            and len(r.text) > 10  # Meaningful length
            and not self.PRICE_PATTERN.search(r.text)  # Not a price
            and not any(re.search(p, r.text.lower()) for p in self.CART_BUTTON_PATTERNS)  # Not a button
        ]

        if not candidates:
            return None

        # Score candidates: prefer larger text that's closer to product area
        def title_score(r: OCRResult) -> float:
            # Closer to product area (but still above) is better
            proximity = 500 - abs(r.y - product_area_y)
            # Larger area suggests heading
            size = r.area / 50
            # Longer text is usually more descriptive
            length = min(len(r.text), 100)
            return proximity + size + length

        best = max(candidates, key=title_score)

        # Clean up title
        title = best.text.strip()
        # Remove common prefixes
        for prefix in ["New", "NEW", "Sale", "SALE"]:
            if title.startswith(prefix + " "):
                title = title[len(prefix) + 1:]

        return title

    def _find_original_price(
        self,
        prices: List[Tuple[float, OCRResult]],
        current_price: float,
        current_result: OCRResult
    ) -> Optional[float]:
        """Find original/struck-through price if on sale."""
        for price_val, result in prices:
            # Original price should be higher
            if price_val <= current_price:
                continue
            # Should be near the current price
            if abs(result.y - current_result.y) > 100:
                continue
            # Found a higher price nearby
            return price_val
        return None

    def _find_contact_pricing(self, ocr_results: List[OCRResult]) -> Optional[str]:
        """
        Check if page indicates contact-based pricing.

        Returns the matched text if found, None otherwise.
        """
        for result in ocr_results:
            text_lower = result.text.lower()
            for pattern in self.CONTACT_PRICE_PATTERNS:
                if re.search(pattern, text_lower):
                    return result.text
        return None

    def _find_title_from_page(self, ocr_results: List[OCRResult]) -> Optional[str]:
        """
        Find product title when no price reference is available.

        Uses heuristics:
        - Larger text (headings) near top of page
        - Not navigation or button text
        - Meaningful length
        """
        # Filter candidates: meaningful text, not navigation/buttons
        candidates = [
            r for r in ocr_results
            if len(r.text) > 10
            and len(r.text) < 200
            and r.y < 500  # Upper portion of page
            and not self.PRICE_PATTERN.search(r.text)
            and not any(re.search(p, r.text.lower()) for p in self.CART_BUTTON_PATTERNS)
            and not any(nav in r.text.lower() for nav in [
                'home', 'menu', 'search', 'cart', 'login', 'sign in',
                'shop', 'categories', 'browse', 'filter', 'sort'
            ])
        ]

        if not candidates:
            return None

        # Score by: larger area (heading), higher on page, longer text
        def title_score(r: OCRResult) -> float:
            area_score = r.area / 50
            position_score = 500 - r.y  # Higher on page = better
            length_score = min(len(r.text), 80)
            return area_score + position_score + length_score

        best = max(candidates, key=title_score)
        return best.text.strip()

    def _get_vendor(self, url: str) -> str:
        """Extract vendor domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return "unknown"

    def _parse_price(self, text: str) -> Optional[float]:
        """Parse price from text like '$599.99' or '$1,299'."""
        if not text:
            return None

        # Remove $ and commas
        cleaned = text.replace('$', '').replace(',', '').strip()

        try:
            price = float(cleaned)
            if price < 0 or price > 100000:
                return None
            return round(price, 2)
        except (ValueError, TypeError):
            return None

    # =========================================================================
    # JSON-LD extraction (fast path)
    # =========================================================================

    async def _extract_json_ld(self, page: 'Page') -> Optional[PDPData]:
        """Extract product data from JSON-LD structured data."""
        try:
            json_ld_scripts = await page.query_selector_all('script[type="application/ld+json"]')

            for script in json_ld_scripts:
                try:
                    content = await script.inner_text()
                    data = json.loads(content)

                    # Handle array of items
                    if isinstance(data, list):
                        for item in data:
                            result = self._parse_json_ld_product(item)
                            if result:
                                return result
                    else:
                        result = self._parse_json_ld_product(data)
                        if result:
                            return result

                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.debug(f"[PDPExtractor] JSON-LD parse error: {e}")
                    continue

            return None

        except Exception as e:
            logger.debug(f"[PDPExtractor] JSON-LD extraction failed: {e}")
            return None

    def _parse_json_ld_product(self, data: Dict[str, Any]) -> Optional[PDPData]:
        """Parse a JSON-LD object for product data."""
        item_type = data.get("@type", "")

        # Handle @graph structure
        if "@graph" in data:
            for item in data["@graph"]:
                result = self._parse_json_ld_product(item)
                if result:
                    return result
            return None

        if item_type not in ["Product", "IndividualProduct", "ProductModel"]:
            return None

        try:
            # Extract price
            price = None
            original_price = None

            offers = data.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            if isinstance(offers, dict):
                price_str = offers.get("price") or offers.get("lowPrice")
                if price_str:
                    price = self._parse_price(str(price_str))

                high_price = offers.get("highPrice")
                if high_price and price:
                    high_val = self._parse_price(str(high_price))
                    if high_val and high_val > price:
                        original_price = high_val

            # Extract title
            title = data.get("name", "")

            # Extract availability
            availability = offers.get("availability", "") if isinstance(offers, dict) else ""
            in_stock = "InStock" in availability or "instock" in availability.lower()
            stock_status = "in_stock" if in_stock else "out_of_stock"

            # Extract rating
            rating = None
            review_count = None
            aggregate_rating = data.get("aggregateRating", {})
            if aggregate_rating:
                rating_val = aggregate_rating.get("ratingValue")
                if rating_val:
                    try:
                        rating = float(rating_val)
                    except (ValueError, TypeError):
                        pass
                count_val = aggregate_rating.get("reviewCount") or aggregate_rating.get("ratingCount")
                if count_val:
                    try:
                        review_count = int(count_val)
                    except (ValueError, TypeError):
                        pass

            # Extract image
            image_url = None
            image = data.get("image")
            if isinstance(image, str):
                image_url = image
            elif isinstance(image, list) and image:
                image_url = image[0] if isinstance(image[0], str) else image[0].get("url")
            elif isinstance(image, dict):
                image_url = image.get("url")

            if price is not None:
                return PDPData(
                    price=price,
                    title=title,
                    original_price=original_price,
                    in_stock=in_stock,
                    stock_status=stock_status,
                    rating=rating,
                    review_count=review_count,
                    image_url=image_url,
                    extraction_source="json_ld",
                    extraction_confidence=0.95,
                )

        except Exception as e:
            logger.debug(f"[PDPExtractor] JSON-LD product parse error: {e}")

        return None

    # =========================================================================
    # Specs extraction methods
    # =========================================================================

    # Spec key normalization mappings
    SPEC_KEY_MAPPINGS = {
        # GPU/Graphics
        "graphics": "gpu", "video card": "gpu", "gpu": "gpu", "graphics card": "gpu",
        "graphics processor": "gpu", "video": "gpu", "dedicated graphics": "gpu",
        # CPU/Processor
        "processor": "cpu", "cpu": "cpu", "processor type": "cpu",
        "processor model": "cpu", "chip": "cpu",
        # RAM/Memory
        "memory": "ram", "ram": "ram", "system memory": "ram",
        "installed ram": "ram", "memory size": "ram",
        # Storage
        "storage": "storage", "hard drive": "storage", "ssd": "storage",
        "hdd": "storage", "storage capacity": "storage", "internal storage": "storage",
        "solid state drive": "storage", "hard disk": "storage",
        # Display
        "screen": "display", "display": "display", "resolution": "display",
        "screen size": "display", "display size": "display", "monitor": "display",
        # Battery
        "battery": "battery", "battery life": "battery", "battery capacity": "battery",
        # OS
        "operating system": "os", "os": "os", "platform": "os",
        # Weight
        "weight": "weight", "product weight": "weight",
    }

    def _normalize_spec_key(self, key: str) -> str:
        """Normalize spec keys to standard names."""
        key_lower = key.lower().strip()

        # Check exact and partial matches
        for pattern, normalized in self.SPEC_KEY_MAPPINGS.items():
            if pattern in key_lower:
                return normalized

        # Return cleaned key if no mapping found
        return key_lower.replace(" ", "_").replace("-", "_")

    async def _extract_specs_from_json_ld(self, page: 'Page') -> Dict[str, str]:
        """Extract specs from JSON-LD structured data (additionalProperty)."""
        specs = {}
        try:
            json_ld_scripts = await page.query_selector_all('script[type="application/ld+json"]')

            for script in json_ld_scripts:
                try:
                    content = await script.inner_text()
                    data = json.loads(content)

                    # Handle array
                    if isinstance(data, list):
                        for item in data:
                            specs.update(self._parse_json_ld_specs(item))
                    else:
                        specs.update(self._parse_json_ld_specs(data))

                except (json.JSONDecodeError, Exception):
                    continue

        except Exception as e:
            logger.debug(f"[PDPExtractor] JSON-LD specs extraction failed: {e}")

        return specs

    def _parse_json_ld_specs(self, data: Dict[str, Any]) -> Dict[str, str]:
        """Parse specs from JSON-LD additionalProperty array."""
        specs = {}

        # Handle @graph structure
        if "@graph" in data:
            for item in data["@graph"]:
                specs.update(self._parse_json_ld_specs(item))
            return specs

        item_type = data.get("@type", "")
        if item_type not in ["Product", "IndividualProduct", "ProductModel"]:
            return specs

        # Extract from additionalProperty
        additional_props = data.get("additionalProperty", [])
        if isinstance(additional_props, list):
            for prop in additional_props:
                if isinstance(prop, dict):
                    name = prop.get("name", "")
                    value = prop.get("value", "")
                    if name and value:
                        normalized_key = self._normalize_spec_key(name)
                        specs[normalized_key] = str(value)

        # Extract brand
        brand = data.get("brand")
        if brand:
            if isinstance(brand, dict):
                specs["brand"] = brand.get("name", "")
            elif isinstance(brand, str):
                specs["brand"] = brand

        # Extract model
        model = data.get("model")
        if model:
            specs["model"] = str(model)

        # Extract SKU
        sku = data.get("sku")
        if sku:
            specs["sku"] = str(sku)

        return specs

    async def _extract_specs_from_html(self, page: 'Page') -> Dict[str, str]:
        """Extract specs from HTML tables and definition lists."""
        try:
            js_code = """
            () => {
                const specs = {};

                // Helper to clean text
                function clean(text) {
                    return (text || '').trim().replace(/\\s+/g, ' ');
                }

                // Try <table> elements (common for specs)
                const tables = document.querySelectorAll('table');
                for (const table of tables) {
                    // Skip tables that look like layout tables
                    if (table.rows.length > 50) continue;

                    for (const row of table.rows) {
                        const cells = row.cells;
                        if (cells.length >= 2) {
                            const key = clean(cells[0].textContent);
                            const value = clean(cells[1].textContent);
                            if (key && value && key.length < 50 && value.length < 200) {
                                specs[key] = value;
                            }
                        }
                    }
                }

                // Try <dl> elements (definition lists)
                const dls = document.querySelectorAll('dl');
                for (const dl of dls) {
                    const dts = dl.querySelectorAll('dt');
                    const dds = dl.querySelectorAll('dd');
                    const minLen = Math.min(dts.length, dds.length);
                    for (let i = 0; i < minLen; i++) {
                        const key = clean(dts[i].textContent);
                        const value = clean(dds[i].textContent);
                        if (key && value && key.length < 50 && value.length < 200) {
                            specs[key] = value;
                        }
                    }
                }

                // Try spec-like divs (key: value patterns)
                const specDivs = document.querySelectorAll(
                    '[class*="spec"], [class*="Spec"], [class*="detail"], [class*="Detail"], ' +
                    '[class*="attribute"], [class*="Attribute"], [data-testid*="spec"]'
                );
                for (const div of specDivs) {
                    // Look for label/value pairs within
                    const labels = div.querySelectorAll('[class*="label"], [class*="Label"], [class*="name"], [class*="key"]');
                    const values = div.querySelectorAll('[class*="value"], [class*="Value"], [class*="data"]');
                    const minLen = Math.min(labels.length, values.length);
                    for (let i = 0; i < minLen; i++) {
                        const key = clean(labels[i].textContent);
                        const value = clean(values[i].textContent);
                        if (key && value && key.length < 50 && value.length < 200) {
                            specs[key] = value;
                        }
                    }
                }

                return specs;
            }
            """

            raw_specs = await page.evaluate(js_code)

            # Normalize keys
            normalized = {}
            for key, value in raw_specs.items():
                normalized_key = self._normalize_spec_key(key)
                # Keep first value for each normalized key
                if normalized_key not in normalized:
                    normalized[normalized_key] = value

            return normalized

        except Exception as e:
            logger.debug(f"[PDPExtractor] HTML specs extraction failed: {e}")
            return {}

    async def _extract_specs_with_llm(self, page: 'Page', goal: str) -> Dict[str, str]:
        """Use LLM to extract specs when mechanical extraction fails."""
        import httpx

        try:
            # Get page text for LLM analysis
            page_text = await page.evaluate("""
            () => {
                // Get main content text, avoiding nav/footer
                const main = document.querySelector('main, [role="main"], article, .product-details, #product-details');
                if (main) {
                    return main.textContent.slice(0, 8000);
                }
                // Fallback to body with some filtering
                const body = document.body.textContent;
                return body.slice(0, 8000);
            }
            """)

            if not page_text or len(page_text) < 100:
                return {}

            # Load prompt
            prompt_template = _load_prompt("pdp_specs")
            if not prompt_template:
                logger.warning("[PDPExtractor] pdp_specs.md prompt not found")
                return {}

            prompt = prompt_template.replace("{GOAL}", goal).replace("{PAGE_TEXT}", page_text[:6000])

            # Call LLM
            solver_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
            solver_key = os.getenv("SOLVER_API_KEY", "qwen-local")
            solver_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    solver_url,
                    headers={"Authorization": f"Bearer {solver_key}"},
                    json={
                        "model": solver_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 500,
                        "temperature": 0.6,
                        "top_p": 0.8,
                        "stop": ["<|im_end|>", "<|endoftext|>"],
                        "repetition_penalty": 1.05
                    }
                )
                response.raise_for_status()
                content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")

                # Parse JSON response
                if "```" in content:
                    content = content.split("```")[1] if "```json" in content else content.split("```")[1]
                    content = content.replace("json", "").strip()

                start = content.find('{')
                end = content.rfind('}') + 1
                if start >= 0 and end > start:
                    data = json.loads(content[start:end])
                    specs = data.get("specs", {})
                    if isinstance(specs, dict):
                        logger.info(f"[PDPExtractor] LLM extracted {len(specs)} specs")
                        return specs

        except Exception as e:
            logger.debug(f"[PDPExtractor] LLM specs extraction failed: {e}")

        return {}

    def _needs_llm_specs(self, specs: Dict[str, str], goal: str) -> bool:
        """Check if LLM extraction needed based on goal and existing specs."""
        if not goal:
            return False

        goal_lower = goal.lower()

        # Electronics queries need GPU/CPU specs
        electronics_terms = ["laptop", "computer", "gpu", "nvidia", "gaming", "pc", "desktop", "notebook"]
        if any(term in goal_lower for term in electronics_terms):
            # Need at least GPU or CPU for electronics
            return "gpu" not in specs and "cpu" not in specs

        return False
