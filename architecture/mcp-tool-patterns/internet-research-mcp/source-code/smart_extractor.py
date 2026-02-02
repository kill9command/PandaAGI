"""
orchestrator/smart_extractor.py

Unified Extraction System using LLM-learned rules.

This is THE ONE extractor. It uses UnifiedCalibrator to get LLM-generated
schemas and extracts data using those schemas.

Flow:
1. Get cached schema or calibrate with LLM (self-correcting)
2. Extract using LLM-learned selectors
3. Validate results
4. If validation fails → trigger recalibration
5. Self-corrects automatically via UnifiedCalibrator
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from urllib.parse import urlparse, urljoin

if TYPE_CHECKING:
    from playwright.async_api import Page

# Using PageIntelligence adapter for backwards compatibility
from orchestrator.page_intelligence.legacy_adapter import get_calibrator
from orchestrator.page_intelligence.legacy_adapter import UnifiedCalibratorAdapter as UnifiedCalibrator

logger = logging.getLogger(__name__)


@dataclass
class ExtractedItem:
    """Single extracted item."""
    title: str = ""
    price: str = ""
    url: str = ""
    image_url: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    """Result of extraction."""
    items: List[ExtractedItem] = field(default_factory=list)
    page_type: str = ""
    domain: str = ""
    schema_used: Optional[Dict[str, Any]] = None
    success: bool = False
    error: str = ""
    extraction_method: str = ""


class SmartExtractor:
    """
    Unified extractor using LLM-learned rules.

    Uses UnifiedCalibrator which self-corrects via LLM feedback loop.
    """

    def __init__(self):
        self.calibrator = get_calibrator()

    async def extract(
        self,
        page: 'Page',
        url: str,
        max_items: int = 20,
        force_recalibrate: bool = False
    ) -> ExtractionResult:
        """
        Extract items from page using LLM-learned rules.

        Args:
            page: Playwright page with loaded content
            url: Page URL
            max_items: Maximum items to extract
            force_recalibrate: Force LLM recalibration

        Returns:
            ExtractionResult with items and metadata
        """
        domain = self._get_domain(url)
        result = ExtractionResult(domain=domain)

        # Step 1: Get or create schema (UnifiedCalibrator handles self-correction)
        try:
            schema = await self.calibrator.get_profile(
                page=page,
                url=url,
                force_recalibrate=force_recalibrate
            )
            result.schema_used = schema
            result.page_type = schema.get('site_intent', '')
        except Exception as e:
            logger.error(f"[SmartExtractor] Calibration failed: {e}")
            result.error = f"Calibration failed: {e}"
            return result

        # Check if schema is validated
        if not schema.get('validated'):
            logger.warning(f"[SmartExtractor] Schema not validated for {domain}")
            result.error = "Schema not validated"
            return result

        # Step 2: Extract using schema
        try:
            items = await self._extract_with_schema(page, url, schema, max_items)
            result.items = items
            result.extraction_method = "unified_calibrator"
        except Exception as e:
            logger.error(f"[SmartExtractor] Extraction failed: {e}")
            result.error = f"Extraction failed: {e}"
            return result

        # Step 3: Validate results
        validation = self._validate_results(items, schema)

        if validation['success']:
            result.success = True
            logger.info(f"[SmartExtractor] Extracted {len(items)} items from {domain}")
        else:
            # If validation fails with unified calibrator, force recalibrate once
            if not force_recalibrate:
                logger.info(f"[SmartExtractor] Extraction failed ({validation['reason']}), recalibrating...")
                return await self.extract(page, url, max_items, force_recalibrate=True)
            else:
                result.error = validation['reason']
                logger.warning(f"[SmartExtractor] Extraction failed: {validation['reason']}")

        return result

    async def _extract_with_schema(
        self,
        page: 'Page',
        url: str,
        schema: Dict[str, Any],
        max_items: int
    ) -> List[ExtractedItem]:
        """Extract items using UnifiedCalibrator schema."""

        item_selector = schema.get('item_selector', '')
        if not item_selector:
            logger.warning("[SmartExtractor] No item_selector in schema")
            return []

        # Get field selectors from new schema format
        fields = schema.get('fields', {})
        title_config = fields.get('title', {})
        price_config = fields.get('price', {})
        url_config = fields.get('url', {})
        image_config = fields.get('image', {})

        # Build extraction JavaScript compatible with new schema format
        js_code = f"""(maxItems) => {{
            const results = [];
            const itemSelector = {json.dumps(item_selector)};

            // Field configurations from UnifiedCalibrator schema
            const titleConfig = {json.dumps(title_config)};
            const priceConfig = {json.dumps(price_config)};
            const urlConfig = {json.dumps(url_config)};
            const imageConfig = {json.dumps(image_config)};

            // Helper: extract value based on config
            const extractField = (el, config) => {{
                if (!el || !config || !config.selector) return '';

                const found = el.querySelector(config.selector);
                if (!found) return '';

                const attr = config.attribute || 'textContent';
                let value = '';

                if (attr === 'textContent') {{
                    value = found.innerText?.trim() || found.textContent?.trim() || '';
                }} else if (attr === 'href') {{
                    value = found.href || found.getAttribute('href') || '';
                }} else if (attr === 'src') {{
                    value = found.src || found.getAttribute('data-src') || found.getAttribute('data-lazy-src') || '';
                }} else {{
                    value = found.getAttribute(attr) || '';
                }}

                // Apply transform if specified
                if (config.transform === 'price') {{
                    // Extract price value
                    const priceMatch = value.match(/[\\$\\£\\€]?[\\d,]+\\.?\\d*/);
                    value = priceMatch ? priceMatch[0] : value;
                }}

                return value.replace(/\\s+/g, ' ').trim();
            }};

            // Fallback for title if not found
            const getTitleFallback = (el) => {{
                const fallbacks = ['h2', 'h3', 'h1', 'h4', '.title', '[class*="title"]', 'a[href]'];
                for (const fb of fallbacks) {{
                    const fbEl = el.querySelector(fb);
                    if (fbEl && fbEl.textContent?.trim()) {{
                        return fbEl.textContent.trim().replace(/\\s+/g, ' ');
                    }}
                }}
                return '';
            }};

            // Fallback for URL if not found
            const getUrlFallback = (el) => {{
                const link = el.querySelector('a[href]');
                return link?.href || link?.getAttribute('href') || '';
            }};

            // Fallback for image if not found
            const getImageFallback = (el) => {{
                const img = el.querySelector('img');
                return img?.src || img?.getAttribute('data-src') || '';
            }};

            // Find all items
            const items = document.querySelectorAll(itemSelector);

            for (const item of items) {{
                if (results.length >= maxItems) break;

                // Extract data using config or fallbacks
                let title = extractField(item, titleConfig) || getTitleFallback(item);
                let price = extractField(item, priceConfig);
                let link = extractField(item, urlConfig) || getUrlFallback(item);
                let image = extractField(item, imageConfig) || getImageFallback(item);

                // Skip if no meaningful data
                if (!title && !price && !link) continue;

                results.push({{
                    title: title.slice(0, 200),
                    price: price.slice(0, 50),
                    url: link,
                    image_url: image
                }});
            }}

            return results;
        }}"""

        try:
            raw_items = await page.evaluate(js_code, max_items)

            items = []
            base_url = url
            for raw in raw_items:
                item = ExtractedItem(
                    title=raw.get('title', ''),
                    price=raw.get('price', ''),
                    url=self._resolve_url(raw.get('url', ''), base_url),
                    image_url=raw.get('image_url', ''),
                    raw_data=raw
                )
                items.append(item)

            return items

        except Exception as e:
            logger.error(f"[SmartExtractor] JS extraction failed: {e}")
            return []

    def _validate_results(
        self,
        items: List[ExtractedItem],
        schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate extraction results.

        Returns dict with 'success' bool and 'reason' string.
        """

        # Check: got any items?
        if len(items) == 0:
            return {'success': False, 'reason': 'zero_items_extracted'}

        # Check: items have meaningful data?
        items_with_title = sum(1 for i in items if i.title)
        if items_with_title < len(items) * 0.3:
            return {'success': False, 'reason': 'most_items_missing_title'}

        # Check: items have prices? (for commerce pages)
        site_intent = schema.get('site_intent', '')
        if site_intent in ('product_listings', 'listing', 'search_results'):
            items_with_price = sum(1 for i in items if i.price and '$' in i.price)
            if items_with_price < len(items) * 0.3:
                return {'success': False, 'reason': 'most_items_missing_price'}

        # Check: URLs are unique (not all nav links)
        urls = [i.url for i in items if i.url]
        if urls:
            unique_urls = len(set(urls))
            if unique_urls < len(urls) * 0.5:
                return {'success': False, 'reason': 'duplicate_urls_detected'}

        # Check: URLs look like products (not nav)
        if urls:
            nav_patterns = ['/category/', '/collection/', '/about', '/contact', '/faq', '/help']
            nav_count = sum(1 for u in urls if any(p in u.lower() for p in nav_patterns))
            if nav_count > len(urls) * 0.5:
                return {'success': False, 'reason': 'urls_look_like_navigation'}

        return {'success': True, 'reason': ''}

    def _resolve_url(self, url: str, base_url: str) -> str:
        """Resolve relative URL to absolute."""
        if not url:
            return ""
        if url.startswith(('http://', 'https://')):
            return url
        return urljoin(base_url, url)

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except:
            return "unknown"


# Singleton instance
_extractor: Optional[SmartExtractor] = None


def get_smart_extractor() -> SmartExtractor:
    """Get global SmartExtractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = SmartExtractor()
    return _extractor
