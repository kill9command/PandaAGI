"""
orchestrator/site_calibrator.py

DEPRECATED: This module is deprecated in favor of PageIntelligenceService.

Use the new page intelligence system instead:
    from apps.services.orchestrator.page_intelligence import get_page_intelligence_service

    service = get_page_intelligence_service()
    understanding = await service.understand_page(page, url)
    items = await service.extract(page, understanding)

The new system provides:
- 3-phase pipeline (zone identification, selector generation, strategy selection)
- Multiple extraction strategies (selector, vision, hybrid, prose)
- Async-locked caching with LRU eviction
- Better error handling and debugging support

---

ORIGINAL DOCSTRING (kept for reference):
Site Calibrator - LLM-based learning of site extraction patterns.

On first visit to an unknown site (or when recalibration needed):
1. Capture DOM structure + screenshot
2. Send to LLM with analysis prompt
3. Parse LLM response into SiteSchema
4. Optionally validate schema works
5. Store in registry for future use
"""

import warnings
warnings.warn(
    "site_calibrator is deprecated, use PageIntelligenceService instead",
    DeprecationWarning,
    stacklevel=2
)

import asyncio
import json
import logging
import os
import re
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

import httpx

from apps.services.orchestrator.shared_state.site_schema_registry import (
    SiteSchema,
    SiteSchemaRegistry,
    get_schema_registry
)

logger = logging.getLogger(__name__)

# vLLM endpoint
VLLM_URL = os.getenv("VLLM_URL", "http://127.0.0.1:8000")

# Feedback template for when selectors fail validation
FAILED_SELECTOR_FEEDBACK = """

## ⚠️ CRITICAL: Previously Failed Selectors

The following CSS selectors were tried but **FAILED validation**:

{failed_list}

### Validation Requirements (ALL must pass):
1. **Count**: Selector must match 3-100 elements (not too few, not too broad)
2. **Structure**: 30%+ of matched elements must contain BOTH a title (h1-h4) AND a link
3. **Extraction**: Must be able to extract title + URL from 30%+ of elements
4. **Uniqueness**: At least 50% of extracted URLs must be unique

### Common Failure Patterns:
- **Too broad** (>100 elements): `div[data-*]`, `li`, `div` without qualifiers → matches nav/ads/other
- **No structure**: Elements that are just wrappers without title/link inside
- **All same URL**: Navigation items that link to the same page

### What You MUST Do:
1. **DO NOT** repeat any failed selector
2. Look for more SPECIFIC patterns like:
   - `[data-testid="product-card"]`
   - `.product-item`, `.sku-item`, `.product-tile`
   - `article.product`, `div.product-card`
   - Elements that CONTAIN both `<h3>` (title) and `<a href>` (link)
3. The DOM shows the actual page structure - use it

The page has products (visible in OCR text), so valid selectors exist.
"""

# Calibration prompt templates
LISTING_CALIBRATION_PROMPT = """You are analyzing a retail website's product listing page to learn its structure.

URL: {url}
Domain: {domain}

## DOM Structure (simplified)
```html
{dom_summary}
```

## Visible Text from Page (OCR)
```
{ocr_text}
```

## Your Task
Identify CSS selectors for extracting products from this page. Look for:

1. **PRODUCT_CARD_SELECTOR**: The container element for each product
   - Look for repeating elements with similar structure
   - Common patterns: .product-card, .sku-item, [data-sku-id], .product-tile, li.product

2. **PRODUCT_LINK_SELECTOR**: The clickable link to the product page (within a card)
   - Usually an <a> tag containing or near the product title
   - Common patterns: a.product-title, .product-name a, h4 a, a[data-track="product"]

3. **PRICE_SELECTOR**: The element showing the price (within a card)
   - Look for $XX.XX format
   - Common patterns: .price, .priceView-customer-price, [data-price], .product-price

4. **TITLE_SELECTOR**: The product title element (within a card)
   - Common patterns: .product-title, h4.sku-header, .product-name, h3.product-title

5. **FILTER_SELECTORS**: CSS selectors for filter/facet links to AVOID clicking
   - Usually in a sidebar
   - Common patterns: .facet a, .filter-option, [data-facet], .refinement a

6. **PAGINATION_METHOD**: How to see more products
   - "click_next": Click a Next/More button
   - "scroll_infinite": Scroll down loads more
   - "url_param": Add ?page=N to URL

7. **NEXT_BUTTON_SELECTOR**: If pagination_method is click_next, the selector for the Next button

## Response Format
Return ONLY valid JSON (no markdown, no explanation):
{{
    "product_card_selector": "CSS selector or null",
    "product_link_selector": "CSS selector or null",
    "price_selector": "CSS selector or null",
    "title_selector": "CSS selector or null",
    "filter_selectors": ["selector1", "selector2"],
    "pagination_method": "click_next|scroll_infinite|url_param|null",
    "next_button_selector": "CSS selector or null",
    "confidence": 0.0-1.0,
    "notes": "Brief notes about the page structure"
}}
"""

PDP_CALIBRATION_PROMPT = """You are analyzing a retail website's product detail page (PDP) to learn its structure.

URL: {url}
Domain: {domain}

## DOM Structure (simplified)
```html
{dom_summary}
```

## Visible Text from Page (OCR)
```
{ocr_text}
```

## Your Task
Identify CSS selectors for extracting product details from this page.

1. **TITLE_SELECTOR**: The main product title
   - Usually an h1 or prominent heading
   - Common patterns: h1.product-title, [data-product-name], .pdp-title

2. **PRICE_SELECTOR**: The current/sale price
   - Common patterns: .price-current, [data-price], .pdp-price, .sale-price

3. **IMAGE_SELECTOR**: The main product image
   - Common patterns: img.primary-image, .product-gallery img, [data-main-image]

4. **JSON_LD_AVAILABLE**: Does the page have JSON-LD structured data?
   - Look for <script type="application/ld+json"> with Product schema

5. **ADD_TO_CART_SELECTOR**: The add to cart button (for availability detection)
   - Common patterns: button[data-add-to-cart], .add-to-cart-btn, #add-to-cart

## Response Format
Return ONLY valid JSON (no markdown, no explanation):
{{
    "title_selector": "CSS selector or null",
    "price_selector": "CSS selector or null",
    "image_selector": "CSS selector or null",
    "json_ld_available": true|false,
    "add_to_cart_selector": "CSS selector or null",
    "confidence": 0.0-1.0,
    "notes": "Brief notes about the page structure"
}}
"""

SEARCH_RESULTS_CALIBRATION_PROMPT = """You are analyzing a search engine results page to learn its structure.

URL: {url}
Domain: {domain}

## DOM Structure (simplified)
```html
{dom_summary}
```

## Visible Text from Page (OCR)
```
{ocr_text}
```

## Your Task
Identify CSS selectors for extracting search results.

1. **RESULT_CONTAINER_SELECTOR**: Container for each search result
   - Common patterns: .g, [data-hveid], .search-result, .result

2. **RESULT_LINK_SELECTOR**: The main link in each result
   - Common patterns: a h3, .result-title a, a[data-ved]

3. **RESULT_SNIPPET_SELECTOR**: The description/snippet text
   - Common patterns: .snippet, .result-snippet, [data-content-feature]

4. **NEXT_BUTTON_SELECTOR**: Pagination next button
   - Common patterns: a#pnnext, .pagination-next, [aria-label="Next"]

## Response Format
Return ONLY valid JSON (no markdown, no explanation):
{{
    "result_container_selector": "CSS selector or null",
    "result_link_selector": "CSS selector or null",
    "result_snippet_selector": "CSS selector or null",
    "next_button_selector": "CSS selector or null",
    "confidence": 0.0-1.0,
    "notes": "Brief notes about the page structure"
}}
"""


class SiteCalibrator:
    """
    Calibrates extraction schemas for unknown sites using LLM analysis.
    """

    def __init__(self, registry: SiteSchemaRegistry = None):
        self.registry = registry or get_schema_registry()
        self.vllm_url = VLLM_URL

    async def calibrate(
        self,
        page,  # Playwright Page object
        url: str,
        page_type: str,
        force: bool = False,
        max_retries: int = 3
    ) -> Optional[SiteSchema]:
        """
        Calibrate extraction schema for a page with validation feedback loop.

        If validation fails, retries with feedback about failed selectors to help
        the LLM suggest different patterns.

        Args:
            page: Playwright Page object (already navigated)
            url: Current URL
            page_type: "listing", "pdp", or "search_results"
            force: Force recalibration even if schema exists
            max_retries: Maximum calibration attempts with feedback (default 3)

        Returns:
            SiteSchema if calibration successful, None otherwise
        """
        domain = self._extract_domain(url)

        # Skip calibration for blank/invalid pages
        if not domain or domain in ('blank', 'about', 'empty') or url in ('about:blank', ''):
            logger.warning(f"[Calibrator] Skipping calibration for invalid page: {url}")
            return None

        # Check if calibration needed
        if not force:
            existing = self.registry.get(domain, page_type)
            if existing and not existing.needs_recalibration:
                logger.debug(f"[Calibrator] Schema exists for {domain}:{page_type}, skipping calibration")
                return existing

        logger.info(f"[Calibrator] Starting calibration for {domain}:{page_type}")

        try:
            # Capture page data once (reuse across retries)
            dom_summary = await self._get_dom_summary(page)
            ocr_text = await self._get_visible_text(page)

            # Select prompt template
            if page_type == "listing":
                base_prompt = LISTING_CALIBRATION_PROMPT
            elif page_type == "pdp":
                base_prompt = PDP_CALIBRATION_PROMPT
            elif page_type == "search_results":
                base_prompt = SEARCH_RESULTS_CALIBRATION_PROMPT
            else:
                logger.warning(f"[Calibrator] Unknown page_type: {page_type}")
                return None

            # Track failed selectors with reasons for feedback
            failed_selectors: List[Dict[str, str]] = []  # [{selector, reason, details}]
            best_schema = None

            for attempt in range(max_retries):
                # Format base prompt
                formatted_prompt = base_prompt.format(
                    url=url,
                    domain=domain,
                    dom_summary=dom_summary[:8000],
                    ocr_text=ocr_text[:4000]
                )

                # Add feedback about failed selectors on retry
                if failed_selectors:
                    failed_list = "\n".join(
                        f"- `{f['selector']}` → **{f['reason']}**: {f['details']}"
                        for f in failed_selectors
                    )
                    feedback = FAILED_SELECTOR_FEEDBACK.format(failed_list=failed_list)
                    formatted_prompt += feedback
                    logger.info(f"[Calibrator] Retry {attempt + 1}/{max_retries} with feedback about {len(failed_selectors)} failed selector(s)")

                # Increase temperature on retries to get different outputs
                # Start at 0.1, increase by 0.2 each retry (0.1, 0.3, 0.5)
                temperature = 0.1 + (attempt * 0.2)

                # Call LLM
                llm_response = await self._call_llm(formatted_prompt, temperature=temperature)

                if not llm_response:
                    logger.warning(f"[Calibrator] LLM returned empty response (attempt {attempt + 1})")
                    continue

                # Parse response
                schema_data = self._parse_llm_response(llm_response, domain, page_type)

                if not schema_data:
                    logger.warning(f"[Calibrator] Failed to parse LLM response (attempt {attempt + 1})")
                    continue

                # Create schema
                schema = SiteSchema(
                    domain=domain,
                    page_type=page_type,
                    **schema_data
                )

                # Validate schema for listing AND search_results page types
                if page_type in ("listing", "search_results") and schema.product_card_selector:
                    selector = schema.product_card_selector

                    # Skip if we already tried this exact selector
                    if any(f["selector"] == selector for f in failed_selectors):
                        logger.warning(f"[Calibrator] LLM repeated failed selector '{selector}', skipping")
                        continue

                    success, reason, details = await self._validate_listing_schema(page, schema)

                    if success:
                        # Success! Save and return
                        logger.info(f"[Calibrator] ✓ Validation passed for '{selector}' on attempt {attempt + 1}")
                        self.registry.save(schema)
                        logger.info(
                            f"[Calibrator] Calibration complete for {domain}:{page_type} "
                            f"(card={schema.product_card_selector}, link={schema.product_link_selector})"
                        )
                        return schema
                    else:
                        # Track failed selector with details for next attempt
                        failed_selectors.append({
                            "selector": selector,
                            "reason": reason,
                            "details": details
                        })
                        best_schema = schema  # Keep last attempt as fallback
                        logger.warning(
                            f"[Calibrator] Selector '{selector}' failed validation: {reason} - {details} "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                else:
                    # For PDP or no card selector, save directly
                    self.registry.save(schema)
                    logger.info(
                        f"[Calibrator] Calibration complete for {domain}:{page_type} "
                        f"(card={schema.product_card_selector}, link={schema.product_link_selector})"
                    )
                    return schema

            # All retries exhausted - save best attempt with failure flag
            if best_schema:
                tried_selectors = [f["selector"] for f in failed_selectors]
                logger.warning(
                    f"[Calibrator] All {max_retries} attempts failed for {domain}:{page_type}. "
                    f"Tried selectors: {tried_selectors}"
                )
                best_schema.consecutive_failures = 3  # Mark as needing recalibration
                self.registry.save(best_schema)
                return best_schema

            logger.error(f"[Calibrator] Calibration completely failed for {domain}:{page_type}")
            return None

        except Exception as e:
            logger.error(f"[Calibrator] Calibration failed for {domain}:{page_type}: {e}", exc_info=True)
            return None

    async def calibrate_from_success(
        self,
        page,
        url: str,
        page_type: str,
        successful_selectors: Dict[str, str]
    ) -> Optional[SiteSchema]:
        """
        Create schema from known-good selectors (learned from successful extraction).

        Args:
            page: Playwright Page object
            url: Current URL
            page_type: Page type
            successful_selectors: Dict of selectors that worked

        Returns:
            SiteSchema
        """
        domain = self._extract_domain(url)

        schema = SiteSchema(
            domain=domain,
            page_type=page_type,
            **successful_selectors
        )

        # Record initial success
        schema.record_success("learned_from_extraction")

        self.registry.save(schema)

        logger.info(f"[Calibrator] Learned schema from successful extraction: {domain}:{page_type}")
        return schema

    async def _get_dom_summary(self, page) -> str:
        """Get simplified DOM structure for LLM analysis."""
        try:
            # Extract relevant DOM elements
            summary = await page.evaluate("""() => {
                function summarizeElement(el, depth = 0, maxDepth = 4) {
                    if (depth > maxDepth) return '';
                    if (!el || !el.tagName) return '';

                    const tag = el.tagName.toLowerCase();

                    // Skip script, style, svg, etc.
                    if (['script', 'style', 'svg', 'path', 'noscript', 'iframe'].includes(tag)) {
                        return '';
                    }

                    // Build attribute string (only useful attrs)
                    const attrs = [];
                    if (el.id) attrs.push(`id="${el.id}"`);
                    if (el.className && typeof el.className === 'string') {
                        const classes = el.className.trim().split(/\s+/).slice(0, 3).join(' ');
                        if (classes) attrs.push(`class="${classes}"`);
                    }
                    if (el.getAttribute('data-sku')) attrs.push(`data-sku="${el.getAttribute('data-sku')}"`);
                    if (el.getAttribute('data-product')) attrs.push('data-product');
                    if (el.getAttribute('data-hveid')) attrs.push('data-hveid');
                    if (el.href && tag === 'a') {
                        const href = el.getAttribute('href');
                        if (href && !href.startsWith('javascript:')) {
                            attrs.push(`href="${href.substring(0, 60)}..."`);
                        }
                    }

                    const attrStr = attrs.length ? ' ' + attrs.join(' ') : '';
                    const indent = '  '.repeat(depth);

                    // Get text content (truncated)
                    let text = '';
                    if (['a', 'span', 'p', 'h1', 'h2', 'h3', 'h4', 'button'].includes(tag)) {
                        const directText = Array.from(el.childNodes)
                            .filter(n => n.nodeType === 3)
                            .map(n => n.textContent.trim())
                            .join(' ')
                            .substring(0, 50);
                        if (directText) text = directText;
                    }

                    // Build children
                    let children = '';
                    if (el.children && el.children.length > 0 && depth < maxDepth) {
                        const childSummaries = Array.from(el.children)
                            .slice(0, 10)  // Limit children
                            .map(child => summarizeElement(child, depth + 1, maxDepth))
                            .filter(s => s)
                            .join('\\n');
                        if (childSummaries) {
                            children = '\\n' + childSummaries + '\\n' + indent;
                        }
                    }

                    if (text) {
                        return `${indent}<${tag}${attrStr}>${text}</${tag}>`;
                    } else if (children) {
                        return `${indent}<${tag}${attrStr}>${children}</${tag}>`;
                    } else if (['div', 'section', 'article', 'main', 'ul', 'ol', 'li'].includes(tag)) {
                        return `${indent}<${tag}${attrStr}></${tag}>`;
                    }
                    return '';
                }

                const main = document.querySelector('main') || document.body;
                return summarizeElement(main, 0, 4);
            }""")

            return summary or "Could not extract DOM summary"

        except Exception as e:
            logger.warning(f"[Calibrator] Failed to get DOM summary: {e}")
            return "DOM extraction failed"

    async def _get_visible_text(self, page) -> str:
        """Get visible text from page (simpler than full OCR)."""
        try:
            text = await page.evaluate("""() => {
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    {
                        acceptNode: function(node) {
                            const parent = node.parentElement;
                            if (!parent) return NodeFilter.FILTER_REJECT;

                            const tag = parent.tagName.toLowerCase();
                            if (['script', 'style', 'noscript'].includes(tag)) {
                                return NodeFilter.FILTER_REJECT;
                            }

                            const style = window.getComputedStyle(parent);
                            if (style.display === 'none' || style.visibility === 'hidden') {
                                return NodeFilter.FILTER_REJECT;
                            }

                            const text = node.textContent.trim();
                            if (text.length < 2) return NodeFilter.FILTER_REJECT;

                            return NodeFilter.FILTER_ACCEPT;
                        }
                    }
                );

                const texts = [];
                let node;
                while ((node = walker.nextNode()) && texts.length < 200) {
                    const text = node.textContent.trim();
                    if (text && !texts.includes(text)) {
                        texts.push(text);
                    }
                }

                return texts.join('\\n');
            }""")

            return text or "Could not extract visible text"

        except Exception as e:
            logger.warning(f"[Calibrator] Failed to get visible text: {e}")
            return "Text extraction failed"

    async def _call_llm(self, prompt: str, temperature: float = 0.1) -> Optional[str]:
        """
        Call vLLM for calibration analysis.

        Args:
            prompt: The formatted prompt to send
            temperature: LLM temperature (higher = more random, helps break memorization)

        Returns:
            LLM response content or None if failed
        """
        import os

        # Get LLM configuration from environment (same as research_orchestrator)
        model_id = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.vllm_url}/v1/chat/completions",
                    json={
                        "model": model_id,
                        "messages": [
                            {"role": "system", "content": "You are a web scraping expert. Analyze website structure and return JSON selectors. Always analyze the actual DOM provided - do not rely on memorized patterns."},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 1000,
                        "temperature": temperature
                    },
                    headers={"Authorization": f"Bearer {api_key}"}
                )

                if response.status_code != 200:
                    logger.warning(f"[Calibrator] LLM returned status {response.status_code}")
                    return None

                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                return content

        except Exception as e:
            logger.error(f"[Calibrator] LLM call failed: {e}")
            return None

    def _parse_llm_response(
        self,
        response: str,
        domain: str,
        page_type: str
    ) -> Optional[Dict[str, Any]]:
        """Parse LLM response into schema fields."""
        try:
            # Try to extract JSON from response
            # Handle potential markdown code blocks
            response = response.strip()
            if response.startswith("```"):
                # Remove markdown code block
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            # Find JSON object in response
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if not json_match:
                logger.warning(f"[Calibrator] No JSON found in LLM response")
                return None

            data = json.loads(json_match.group())

            # Map response fields to schema fields based on page_type
            schema_data = {}

            if page_type == "listing":
                schema_data["product_card_selector"] = data.get("product_card_selector")
                schema_data["product_link_selector"] = data.get("product_link_selector")
                schema_data["price_selector"] = data.get("price_selector")
                schema_data["title_selector"] = data.get("title_selector")
                schema_data["filter_selectors"] = data.get("filter_selectors", [])
                schema_data["pagination_method"] = data.get("pagination_method")
                schema_data["next_button_selector"] = data.get("next_button_selector")

            elif page_type == "pdp":
                schema_data["title_selector"] = data.get("title_selector")
                schema_data["price_selector"] = data.get("price_selector")
                schema_data["image_selector"] = data.get("image_selector")
                schema_data["json_ld_available"] = data.get("json_ld_available", False)

            elif page_type == "search_results":
                # Map search-specific fields to generic schema fields
                schema_data["product_card_selector"] = data.get("result_container_selector")
                schema_data["product_link_selector"] = data.get("result_link_selector")
                schema_data["next_button_selector"] = data.get("next_button_selector")

            # Filter out None values, empty strings, and "null" strings (LLM artifacts)
            def is_valid_value(v):
                if v is None:
                    return False
                if isinstance(v, str):
                    v_lower = v.strip().lower()
                    # Filter "null", "none", empty strings
                    return v_lower not in ("", "null", "none", "n/a")
                return True

            schema_data = {k: v for k, v in schema_data.items() if is_valid_value(v)}

            # Require at least one meaningful selector for a valid schema
            key_selectors = ['product_card_selector', 'product_link_selector', 'title_selector']
            has_selector = any(k in schema_data for k in key_selectors)

            if not has_selector:
                logger.warning(f"[Calibrator] No valid selectors found for {domain}:{page_type}")
                return None

            return schema_data

        except json.JSONDecodeError as e:
            logger.warning(f"[Calibrator] JSON parse error: {e}")
            return None
        except Exception as e:
            logger.warning(f"[Calibrator] Parse error: {e}")
            return None

    async def _validate_listing_schema(self, page, schema: SiteSchema) -> tuple:
        """
        Validate that a listing schema actually finds usable products.

        Deep validation criteria:
        0. No-results check: Page shouldn't show "0 items found" messages
        1. Element count check: 3-100 elements (too few = wrong, too many = too broad)
        2. Structure check: Elements should contain title (h1-h4) and link
        3. Content extraction: Must be able to extract title + URL from majority
        4. Uniqueness check: Extracted URLs should be unique (not all same link)

        Returns:
            Tuple of (success: bool, reason: str, details: str)
        """
        try:
            if not schema.product_card_selector:
                return (False, "no_selector", "No product_card_selector provided")

            # ═══════════════════════════════════════════════════════════════
            # CHECK 0: No-results page detection
            # ═══════════════════════════════════════════════════════════════
            try:
                body_text = await page.evaluate("() => document.body.innerText.toLowerCase()")
                no_results_phrases = [
                    'we found 0 items', 'found 0 items', '0 items found',
                    '0 results', 'no items found', 'no results found',
                    'no products found', 'no matching products',
                    'sorry, no results', 'we have found 0 items',
                    'did not match any products', 'nothing matched',
                ]
                for phrase in no_results_phrases:
                    if phrase in body_text:
                        reason = "no_results_page"
                        details = f"Page shows '{phrase}' - not a valid product listing"
                        logger.warning(f"[Calibrator] ✗ No-results check: {details}")
                        return (False, reason, details)
                logger.debug("[Calibrator] ✓ No-results check passed")
            except Exception as e:
                logger.debug(f"[Calibrator] No-results check skipped: {e}")

            selector = schema.product_card_selector

            # Try to find product cards
            cards = await page.query_selector_all(selector)
            card_count = len(cards)

            # ═══════════════════════════════════════════════════════════════
            # CHECK 1: Element count validation (not too few, not too many)
            # ═══════════════════════════════════════════════════════════════
            if card_count < 3:
                reason = "too_few"
                details = f"Found only {card_count} elements (need 3+)"
                logger.warning(f"[Calibrator] ✗ Count check: '{selector}' {details}")
                return (False, reason, details)

            if card_count > 100:
                reason = "too_broad"
                details = f"Found {card_count} elements (max 100) - likely matching nav/ads/other elements"
                logger.warning(f"[Calibrator] ✗ Count check: '{selector}' {details}")
                return (False, reason, details)

            logger.info(f"[Calibrator] ✓ Count check: '{selector}' found {card_count} elements")

            # ═══════════════════════════════════════════════════════════════
            # CHECK 2: Structure validation (title + link in elements)
            # ═══════════════════════════════════════════════════════════════
            sample_size = min(15, card_count)
            structure_valid = 0

            for card in cards[:sample_size]:
                try:
                    # Check for title element (h1-h4, or common title classes)
                    has_title = False
                    for title_sel in ['h1', 'h2', 'h3', 'h4', '[class*="title"]', '[class*="name"]', '[role="heading"]']:
                        title_elem = await card.query_selector(title_sel)
                        if title_elem:
                            title_text = await title_elem.text_content() or ""
                            if len(title_text.strip()) > 3:
                                has_title = True
                                break

                    # Check for link element
                    has_link = False
                    link_elem = await card.query_selector('a[href]')
                    if link_elem:
                        href = await link_elem.get_attribute("href") or ""
                        if href.startswith("http") or href.startswith("/"):
                            has_link = True

                    if has_title and has_link:
                        structure_valid += 1

                except Exception:
                    continue

            structure_ratio = structure_valid / sample_size if sample_size > 0 else 0

            if structure_ratio < 0.3:
                reason = "no_structure"
                details = f"Only {structure_valid}/{sample_size} elements have title+link ({structure_ratio:.0%}, need 30%+)"
                logger.warning(f"[Calibrator] ✗ Structure check: {details}")
                return (False, reason, details)

            logger.info(f"[Calibrator] ✓ Structure check: {structure_valid}/{sample_size} elements have title+link ({structure_ratio:.0%})")

            # ═══════════════════════════════════════════════════════════════
            # CHECK 3: Content extraction validation
            # ═══════════════════════════════════════════════════════════════
            extracted_items = []
            link_selector = schema.product_link_selector or "a[href]"

            for card in cards[:sample_size]:
                try:
                    # Extract URL
                    link = await card.query_selector(link_selector)
                    if not link:
                        link = await card.query_selector("a[href]")

                    if not link:
                        continue

                    href = await link.get_attribute("href") or ""

                    # Skip navigation/filter/javascript URLs
                    if not href or href.startswith("javascript:") or href == "#":
                        continue
                    if any(skip in href.lower() for skip in ["/search?", "/category/", "/filter", "/sort", "login", "signin"]):
                        continue

                    # Extract title
                    title = ""
                    for title_sel in ['h3', 'h2', 'h4', 'h1', '[class*="title"]', '[class*="name"]']:
                        title_elem = await card.query_selector(title_sel)
                        if title_elem:
                            title = await title_elem.text_content() or ""
                            title = title.strip()
                            if len(title) > 3:
                                break

                    # Fallback: use link text
                    if not title or len(title) <= 3:
                        title = await link.text_content() or ""
                        title = title.strip()

                    # ENHANCED VALIDATION: Check title is real product content, not navigation/placeholder
                    if href and title and len(title) > 3:
                        title_lower = title.lower()

                        # Filter out navigation/UI text that isn't product content
                        navigation_text = [
                            'add to cart', 'add to bag', 'buy now', 'shop now',
                            'compare', 'view details', 'quick view', 'quick look',
                            'sort', 'filter', 'refine', 'clear all', 'reset',
                            'see more', 'load more', 'show more', 'view all',
                            'next', 'previous', 'back', 'close',
                            'sign in', 'log in', 'register', 'account',
                            'cart', 'wishlist', 'save', 'share',
                            'free shipping', 'best seller', 'new arrival',
                            'sponsored', 'advertisement', 'ad',
                        ]

                        # Check if title is mostly navigation text
                        is_nav_text = any(nav in title_lower for nav in navigation_text)

                        # Also check title has reasonable length (real product titles are usually 10+ chars)
                        has_reasonable_length = len(title.strip()) >= 10

                        # Title should contain at least some alphanumeric content
                        has_product_content = any(c.isalnum() for c in title)

                        if not is_nav_text and has_reasonable_length and has_product_content:
                            extracted_items.append({"url": href, "title": title[:100]})
                        else:
                            logger.debug(f"[Calibrator] Filtered out non-product title: '{title[:50]}...'")

                except Exception:
                    continue

            extraction_ratio = len(extracted_items) / sample_size if sample_size > 0 else 0

            if extraction_ratio < 0.3:
                reason = "extraction_failed"
                details = f"Only {len(extracted_items)}/{sample_size} items extracted ({extraction_ratio:.0%}, need 30%+)"
                logger.warning(f"[Calibrator] ✗ Extraction check: {details}")
                return (False, reason, details)

            logger.info(f"[Calibrator] ✓ Extraction check: {len(extracted_items)}/{sample_size} items extracted ({extraction_ratio:.0%})")

            # ═══════════════════════════════════════════════════════════════
            # CHECK 4: Uniqueness check (URLs should be diverse)
            # ═══════════════════════════════════════════════════════════════
            unique_urls = set(item["url"] for item in extracted_items)
            uniqueness_ratio = len(unique_urls) / len(extracted_items) if extracted_items else 0

            if uniqueness_ratio < 0.5:
                reason = "not_unique"
                details = f"Only {len(unique_urls)}/{len(extracted_items)} unique URLs ({uniqueness_ratio:.0%}, need 50%+)"
                logger.warning(f"[Calibrator] ✗ Uniqueness check: {details}")
                return (False, reason, details)

            logger.info(f"[Calibrator] ✓ Uniqueness check: {len(unique_urls)} unique URLs ({uniqueness_ratio:.0%})")

            # ═══════════════════════════════════════════════════════════════
            # ALL CHECKS PASSED
            # ═══════════════════════════════════════════════════════════════
            logger.info(
                f"[Calibrator] ✓ All validation checks PASSED for '{selector}': "
                f"{card_count} elements, {structure_ratio:.0%} structured, "
                f"{len(extracted_items)} extracted, {len(unique_urls)} unique"
            )
            return (True, "passed", f"{card_count} elements, {len(extracted_items)} extracted, {len(unique_urls)} unique")

        except Exception as e:
            logger.warning(f"[Calibrator] Validation error: {e}")
            return (False, "error", str(e))

    def _extract_domain(self, url: str) -> str:
        """Extract normalized domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path.split('/')[0]
            domain = domain.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return url


# Global instance with thread-safe initialization
import threading
_calibrator: Optional[SiteCalibrator] = None
_calibrator_lock = threading.Lock()


def get_calibrator() -> SiteCalibrator:
    """Get global calibrator instance (thread-safe)."""
    global _calibrator
    if _calibrator is None:
        with _calibrator_lock:
            # Double-check pattern for thread safety
            if _calibrator is None:
                _calibrator = SiteCalibrator()
    return _calibrator
