"""
orchestrator/smart_calibrator.py

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

---

ORIGINAL DOCUMENTATION (deprecated):

Unified LLM-Driven Calibration System

The LLM learns extraction rules for each domain. We don't hardcode anything.

Flow:
1. FIRST VISIT: LLM analyzes page → generates extraction rules → cached
2. REPEAT VISITS: Use cached rules (fast, no LLM)
3. FAILURE DETECTED: LLM re-learns → updates cache

The LLM teaches the system how to extract. Rules are generated, not coded.
"""
import warnings

import asyncio
import json
import logging
import os
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from playwright.async_api import Page

from apps.services.tool_server.shared.llm_utils import load_prompt_via_recipe as _load_prompt_via_recipe

logger = logging.getLogger(__name__)


# Storage
CALIBRATION_CACHE_FILE = Path("panda_system_docs/schemas/smart_calibration.jsonl")
CALIBRATION_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

# LLM endpoint - use SOLVER_URL which points to the chat completions endpoint
SOLVER_URL = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
SOLVER_API_KEY = os.getenv("SOLVER_API_KEY", "qwen-local")
SOLVER_MODEL = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")


@dataclass
class ExtractionSchema:
    """
    LLM-generated extraction rules for a domain.

    The LLM analyzes a page and generates these rules.
    We cache them and reuse on future visits.
    """
    domain: str

    # What to EXTRACT (LLM-learned selectors)
    product_card_selector: str = ""      # Container for each product
    title_selector: str = ""             # Title within card
    price_selector: str = ""             # Price within card
    link_selector: str = ""              # Link within card
    image_selector: str = ""             # Image within card

    # What to SKIP (LLM-learned nav patterns)
    nav_selectors: List[str] = field(default_factory=list)
    skip_selectors: List[str] = field(default_factory=list)  # Ads, popups, etc.

    # Content boundaries
    content_zone_selector: str = ""      # Main content area

    # Page type detection
    page_type: str = ""                  # listing, pdp, search_results, article

    # Metadata
    created_at: str = ""
    updated_at: str = ""
    llm_model: str = ""
    calibration_count: int = 0

    # Success tracking for self-correction
    extraction_attempts: int = 0
    extraction_successes: int = 0
    last_failure_reason: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        self.updated_at = now

    @property
    def success_rate(self) -> float:
        if self.extraction_attempts == 0:
            return 1.0
        return self.extraction_successes / self.extraction_attempts

    @property
    def product_link_selector(self) -> str:
        """Alias for link_selector for backward compatibility with SiteSchema."""
        return self.link_selector

    @property
    def needs_recalibration(self) -> bool:
        """Check if schema is failing and needs LLM re-learning."""
        # No selectors learned yet
        if not self.product_card_selector:
            return True
        # Success rate dropped below 50% with enough data
        if self.extraction_attempts >= 3 and self.success_rate < 0.5:
            return True
        # Last 2 extractions failed
        if self.extraction_attempts >= 2 and self.extraction_successes == 0:
            return True
        return False

    def record_success(self):
        """Record successful extraction."""
        self.extraction_attempts += 1
        self.extraction_successes += 1
        self.last_failure_reason = ""
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def record_failure(self, reason: str):
        """Record failed extraction."""
        self.extraction_attempts += 1
        self.last_failure_reason = reason
        self.updated_at = datetime.now(timezone.utc).isoformat()


class SmartCalibrator:
    """
    DEPRECATED: Use PageIntelligenceService instead.

    LLM-driven calibration system.

    The LLM analyzes pages and generates extraction rules.
    Rules are cached per domain and auto-updated on failures.
    """

    def __init__(self):
        warnings.warn(
            "SmartCalibrator is deprecated. Use PageIntelligenceService instead:\n"
            "  from apps.services.tool_server.page_intelligence import get_page_intelligence_service\n"
            "  service = get_page_intelligence_service()\n"
            "  understanding = await service.understand_page(page, url)\n"
            "  items = await service.extract(page, understanding)",
            DeprecationWarning,
            stacklevel=2
        )
        self._cache: Dict[str, ExtractionSchema] = {}
        self._load_cache()

    def _load_cache(self):
        """Load cached schemas from disk."""
        if not CALIBRATION_CACHE_FILE.exists():
            return

        try:
            with open(CALIBRATION_CACHE_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        domain = data.get('domain', '')
                        if domain:
                            self._cache[domain] = ExtractionSchema(**data)
                    except json.JSONDecodeError:
                        continue
            logger.info(f"[SmartCalibrator] Loaded {len(self._cache)} cached schemas")
        except Exception as e:
            logger.warning(f"[SmartCalibrator] Failed to load cache: {e}")

    def _save_schema(self, schema: ExtractionSchema):
        """Save/update schema in cache file."""
        self._cache[schema.domain] = schema

        # Rewrite entire file (simple approach for JSONL)
        try:
            with open(CALIBRATION_CACHE_FILE, 'w') as f:
                for s in self._cache.values():
                    f.write(json.dumps(asdict(s)) + '\n')
            logger.debug(f"[SmartCalibrator] Saved schema for {schema.domain}")
        except Exception as e:
            logger.error(f"[SmartCalibrator] Failed to save schema: {e}")

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

    def get_schema(self, url: str) -> Optional[ExtractionSchema]:
        """Get cached schema for domain (if exists)."""
        domain = self._get_domain(url)
        return self._cache.get(domain)

    def delete_calibration(self, domain: str) -> bool:
        """
        Delete cached calibration for a domain.

        Used by recovery to force recalibration on next visit.

        Args:
            domain: Domain to delete calibration for

        Returns:
            True if deleted, False if not found
        """
        domain = domain.lower().strip()
        if domain.startswith('www.'):
            domain = domain[4:]

        if domain in self._cache:
            del self._cache[domain]
            # Rewrite cache file without this domain
            try:
                with open(CALIBRATION_CACHE_FILE, 'w') as f:
                    for s in self._cache.values():
                        f.write(json.dumps(asdict(s)) + '\n')
                logger.info(f"[SmartCalibrator] Deleted calibration for {domain}")
                return True
            except Exception as e:
                logger.error(f"[SmartCalibrator] Failed to save after delete: {e}")
        return False

    async def calibrate(
        self,
        page: 'Page',
        url: str,
        force: bool = False,
        failed_reason: str = ""
    ) -> ExtractionSchema:
        """
        Get or create extraction schema for this page.

        Args:
            page: Playwright page with loaded content
            url: Page URL
            force: Force recalibration even if cached
            failed_reason: Why previous extraction failed (for LLM context)

        Returns:
            ExtractionSchema with LLM-learned rules
        """
        domain = self._get_domain(url)

        # Check cache first
        cached = self._cache.get(domain)

        if cached and not force and not cached.needs_recalibration():
            logger.info(f"[SmartCalibrator] Using cached schema for {domain}")
            return cached

        # Need to calibrate with LLM
        if cached:
            logger.info(f"[SmartCalibrator] Re-calibrating {domain} (reason: {failed_reason or 'low success rate'})")
        else:
            logger.info(f"[SmartCalibrator] First calibration for {domain}")

        schema = await self._llm_calibrate(page, url, cached, failed_reason)
        self._save_schema(schema)

        return schema

    async def _llm_calibrate(
        self,
        page: 'Page',
        url: str,
        previous_schema: Optional[ExtractionSchema],
        failed_reason: str
    ) -> ExtractionSchema:
        """
        Use LLM to analyze page and generate extraction rules.
        """
        domain = self._get_domain(url)

        # Get page content for LLM
        page_info = await self._get_page_info(page)

        # Build prompt
        prompt = self._build_calibration_prompt(
            url=url,
            page_info=page_info,
            previous_schema=previous_schema,
            failed_reason=failed_reason
        )

        # Call LLM
        try:
            llm_response = await self._call_llm(prompt)
            schema = self._parse_llm_response(domain, llm_response, previous_schema)
            logger.info(
                f"[SmartCalibrator] LLM calibration complete for {domain}: "
                f"card={schema.product_card_selector}, price={schema.price_selector}"
            )
            return schema
        except Exception as e:
            logger.error(f"[SmartCalibrator] LLM calibration failed: {e}")
            # Return previous schema or empty one
            if previous_schema:
                return previous_schema
            return ExtractionSchema(domain=domain)

    async def _get_page_info(self, page: 'Page') -> Dict[str, Any]:
        """Extract page information for LLM analysis."""

        info = await page.evaluate("""() => {
            const result = {
                title: document.title,
                url: location.href,
                bodyClasses: document.body.className,
                sampleElements: [],
                pricePatterns: [],
                linkPatterns: [],
                structuralHints: [],
                discoveredContainers: [],
                repeatingPatterns: []
            };

            // STRATEGY 1: Find elements with common product-related class names
            const commonSelectors = [
                '[class*="product"]', '[class*="item"]', '[class*="card"]',
                '[class*="listing"]', '[class*="result"]', '[class*="tile"]',
                '[data-sku]', '[data-product]', '[data-item]', '[data-asin]'
            ];
            const interesting = document.querySelectorAll(commonSelectors.join(', '));
            for (const el of [...interesting].slice(0, 10)) {
                result.sampleElements.push({
                    tag: el.tagName.toLowerCase(),
                    classes: el.className?.toString().slice(0, 150) || '',
                    dataAttrs: [...el.attributes]
                        .filter(a => a.name.startsWith('data-'))
                        .map(a => a.name)
                        .slice(0, 5),
                    hasPrice: /\\$[\\d,]+/.test(el.textContent || ''),
                    hasLink: el.querySelector('a[href]') !== null,
                    childCount: el.children.length
                });
            }

            // STRATEGY 2: Find ALL elements containing price text and trace to container
            // This is the KEY discovery method - find prices first, then work backwards
            const allElements = document.body.querySelectorAll('*');
            const priceRegex = /^\\$[\\d,]+(\\.\\d{2})?$/;
            const priceContainers = new Map(); // Track unique container classes

            // Helper: build best selector for an element
            const buildSelector = (el) => {
                // Prefer data attributes (Amazon, Walmart style)
                const dataAttrs = [...el.attributes]
                    .filter(a => a.name.startsWith('data-') &&
                        (a.name.includes('asin') || a.name.includes('product') ||
                         a.name.includes('item') || a.name.includes('sku') ||
                         a.name.includes('component-type')))
                    .slice(0, 1);

                if (dataAttrs.length > 0) {
                    const attr = dataAttrs[0];
                    // For specific values like data-component-type="s-search-result"
                    if (attr.value && attr.value.length < 30 && !attr.value.includes(' ')) {
                        return `[${attr.name}="${attr.value}"]`;
                    }
                    return `[${attr.name}]`;
                }

                // Fall back to class-based selector
                const cls = el.className?.toString().split(' ')[0] || '';
                const tag = el.tagName.toLowerCase();
                return cls ? `${tag}.${cls}` : tag;
            };

            for (const el of allElements) {
                // Check if this element's direct text looks like a price
                const directText = (el.textContent || '').trim();
                if (priceRegex.test(directText) && directText.length < 20) {
                    // Found a price element! Trace up to find the product container
                    let container = el.parentElement;
                    let depth = 0;
                    while (container && depth < 8) {
                        // A good container has: multiple children, a link, reasonable size
                        const hasLink = container.querySelector('a[href]') !== null;
                        const hasImage = container.querySelector('img') !== null;
                        const childCount = container.children.length;

                        // Check for data attributes that indicate product container
                        const hasProductAttr = [...container.attributes].some(a =>
                            a.name.startsWith('data-') &&
                            (a.name.includes('asin') || a.name.includes('product') ||
                             a.name.includes('item') || a.name.includes('sku') ||
                             a.value?.includes('search-result') || a.value?.includes('product'))
                        );

                        if ((hasLink && childCount >= 2) || hasProductAttr) {
                            // Found likely product container
                            const selector = buildSelector(container);

                            if (!priceContainers.has(selector)) {
                                priceContainers.set(selector, {
                                    selector: selector,
                                    fullClasses: container.className?.toString().slice(0, 100) || '',
                                    dataAttrs: [...container.attributes]
                                        .filter(a => a.name.startsWith('data-'))
                                        .map(a => a.name)
                                        .slice(0, 5),
                                    priceElTag: el.tagName.toLowerCase(),
                                    priceElClass: el.className?.toString().split(' ')[0] || '',
                                    priceText: directText,
                                    hasImage: hasImage,
                                    hasProductAttr: hasProductAttr,
                                    childCount: childCount,
                                    depth: depth
                                });
                            }
                            break;
                        }
                        container = container.parentElement;
                        depth++;
                    }

                    // Also record the price element itself
                    const priceClass = el.className?.toString().split(' ')[0] || '';
                    result.pricePatterns.push({
                        tag: el.tagName.toLowerCase(),
                        class: priceClass,
                        selector: priceClass ? `.${priceClass}` : el.tagName.toLowerCase(),
                        sample: directText
                    });
                }
            }

            // Convert price containers to array, prioritizing those with data attributes
            const containers = [...priceContainers.values()];
            containers.sort((a, b) => {
                // Prioritize containers with product data attributes
                if (a.hasProductAttr && !b.hasProductAttr) return -1;
                if (!a.hasProductAttr && b.hasProductAttr) return 1;
                // Then prioritize those with images
                if (a.hasImage && !b.hasImage) return -1;
                if (!a.hasImage && b.hasImage) return 1;
                return 0;
            });
            result.discoveredContainers = containers.slice(0, 10);

            // STRATEGY 3: Find repeating similar elements (grid detection)
            // Look for groups of elements with the same class that appear multiple times
            const classCounts = new Map();
            for (const el of document.body.querySelectorAll('[class]')) {
                const firstClass = el.className?.toString().split(' ')[0];
                if (firstClass && firstClass.length > 3) {
                    classCounts.set(firstClass, (classCounts.get(firstClass) || 0) + 1);
                }
            }

            // Classes that appear 5+ times are likely repeating items
            const repeating = [...classCounts.entries()]
                .filter(([cls, count]) => count >= 5 && count <= 100)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 10);

            for (const [cls, count] of repeating) {
                const sample = document.querySelector('.' + CSS.escape(cls));
                if (sample) {
                    result.repeatingPatterns.push({
                        class: cls,
                        count: count,
                        tag: sample.tagName.toLowerCase(),
                        hasLink: sample.querySelector('a') !== null,
                        hasPrice: /\\$[\\d,]+/.test(sample.textContent || ''),
                        childCount: sample.children.length
                    });
                }
            }

            // STRATEGY 4: Find product links and trace to containers
            const productLinkPatterns = [
                'a[href*="/product"]', 'a[href*="/p/"]', 'a[href*="/dp/"]',
                'a[href*="/item"]', 'a[href*="/itm/"]', 'a[href*="/pd/"]',
                'a[href*="/ip/"]'  // Walmart
            ];
            const links = document.querySelectorAll(productLinkPatterns.join(', '));
            for (const link of [...links].slice(0, 5)) {
                const parent = link.closest('[class]');
                result.linkPatterns.push({
                    href: link.href.slice(0, 100),
                    linkClasses: link.className?.toString().slice(0, 50) || '',
                    parentTag: parent?.tagName.toLowerCase() || '',
                    parentClasses: parent?.className?.toString().slice(0, 80) || ''
                });
            }

            // Structural hints
            const main = document.querySelector('main, [role="main"], #main, .main-content');
            if (main) {
                result.structuralHints.push('has_main_element: ' + (main.tagName + (main.id ? '#' + main.id : '')));
            }

            const nav = document.querySelector('nav, [role="navigation"], header');
            if (nav) {
                result.structuralHints.push('has_nav: true');
            }

            // Grid/list indicators
            const grids = document.querySelectorAll('[class*="grid"], [class*="list"], [class*="results"]');
            if (grids.length > 0) {
                result.structuralHints.push('grid_classes: ' + [...grids].slice(0, 3).map(g => g.className?.split(' ')[0]).join(', '));
            }

            return result;
        }""")

        # Also get a simplified HTML snippet of the main content
        try:
            html_snippet = await page.evaluate("""() => {
                const main = document.querySelector('main, [role="main"], .main-content, #content') || document.body;
                // Get simplified structure (no text content, just tags and classes)
                const simplify = (el, depth = 0) => {
                    if (depth > 4) return '';
                    const tag = el.tagName?.toLowerCase() || '';
                    const cls = el.className?.toString().split(' ').slice(0, 2).join('.') || '';
                    const id = el.id ? '#' + el.id : '';
                    const attrs = [...(el.attributes || [])]
                        .filter(a => a.name.startsWith('data-'))
                        .slice(0, 2)
                        .map(a => `[${a.name}]`)
                        .join('');

                    let result = '  '.repeat(depth) + tag + id + (cls ? '.' + cls : '') + attrs + '\\n';

                    // Only include interesting children
                    const dominated = el.querySelectorAll('[class*="product"], [class*="item"], [class*="card"], [class*="price"]');
                    if (dominated.length > 0 && depth < 3) {
                        for (const child of [...el.children].slice(0, 5)) {
                            result += simplify(child, depth + 1);
                        }
                    }
                    return result;
                };
                return simplify(main).slice(0, 2000);
            }""")
            info['html_structure'] = html_snippet
        except:
            info['html_structure'] = ''

        return info

    def _build_calibration_prompt(
        self,
        url: str,
        page_info: Dict[str, Any],
        previous_schema: Optional[ExtractionSchema],
        failed_reason: str
    ) -> str:
        """Build the LLM prompt for calibration."""
        # Load base prompt via recipe system
        base_prompt = _load_prompt_via_recipe("calibration_selector_generator", "browser")
        if not base_prompt:
            logger.warning("Calibration selector generator prompt not found via recipe")
            base_prompt = "You are analyzing a webpage to generate CSS selectors for data extraction. Respond with JSON only."

        # Build dynamic context
        dynamic_context = f"""
URL: {url}
Page Title: {page_info.get('title', 'Unknown')}

=== DISCOVERED PRODUCT CONTAINERS (from price detection) ===
These containers were found by locating price text ($X.XX) and tracing up to parent elements:
{json.dumps(page_info.get('discoveredContainers', []), indent=2)}

=== REPEATING ELEMENTS (likely product grid) ===
Classes that appear multiple times (candidates for product cards):
{json.dumps(page_info.get('repeatingPatterns', []), indent=2)}

=== PRICE ELEMENTS FOUND ===
{json.dumps(page_info.get('pricePatterns', [])[:8], indent=2)}

=== PRODUCT LINK PATTERNS ===
{json.dumps(page_info.get('linkPatterns', []), indent=2)}

=== ELEMENTS WITH COMMON PRODUCT-RELATED CLASS NAMES ===
{json.dumps(page_info.get('sampleElements', []), indent=2)}

=== STRUCTURAL HINTS ===
{chr(10).join(page_info.get('structuralHints', []))}
"""

        if previous_schema and failed_reason:
            dynamic_context += f"""
PREVIOUS ATTEMPT FAILED:
- Reason: {failed_reason}
- Previous card selector: {previous_schema.product_card_selector}
- Previous price selector: {previous_schema.price_selector}

The previous selectors did not work. Generate DIFFERENT selectors.
"""

        prompt = f"""{base_prompt}

## Current Task

{dynamic_context}

JSON:"""

        return prompt

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM for calibration."""

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                SOLVER_URL,
                headers={
                    "Authorization": f"Bearer {SOLVER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": SOLVER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1000,
                    "temperature": 0.1,  # Low temp for consistent structured output
                }
            )
            response.raise_for_status()

            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content

    def _parse_llm_response(
        self,
        domain: str,
        response: str,
        previous_schema: Optional[ExtractionSchema]
    ) -> ExtractionSchema:
        """Parse LLM response into ExtractionSchema."""

        # Try to extract JSON from response
        try:
            # Handle markdown code blocks
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            # Find JSON object
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                json_str = response[start:end]
                data = json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[SmartCalibrator] Failed to parse LLM response: {e}")
            logger.debug(f"Response was: {response[:500]}")
            # Return previous or empty schema
            if previous_schema:
                return previous_schema
            return ExtractionSchema(domain=domain)

        # Build schema from parsed data
        schema = ExtractionSchema(
            domain=domain,
            page_type=data.get("page_type", ""),
            product_card_selector=data.get("product_card_selector", ""),
            title_selector=data.get("title_selector", ""),
            price_selector=data.get("price_selector", ""),
            link_selector=data.get("link_selector", ""),
            image_selector=data.get("image_selector", ""),
            nav_selectors=data.get("nav_selectors", []),
            skip_selectors=data.get("skip_selectors", []),
            content_zone_selector=data.get("content_zone_selector", ""),
            llm_model=os.getenv("MODEL_NAME", "unknown"),
        )

        # Preserve stats from previous schema
        if previous_schema:
            schema.calibration_count = previous_schema.calibration_count + 1
            schema.created_at = previous_schema.created_at

        return schema


# Singleton instance
_calibrator: Optional[SmartCalibrator] = None


def get_smart_calibrator() -> SmartCalibrator:
    """Get global SmartCalibrator instance."""
    global _calibrator
    if _calibrator is None:
        _calibrator = SmartCalibrator()
    return _calibrator
