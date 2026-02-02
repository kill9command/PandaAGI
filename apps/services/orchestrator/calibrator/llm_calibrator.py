"""
orchestrator/calibrator/llm_calibrator.py

DEPRECATED: This module is deprecated in favor of PageIntelligenceService.

Use the new page intelligence system instead:
    from apps.services.orchestrator.page_intelligence import get_page_intelligence_service

    service = get_page_intelligence_service()
    understanding = await service.understand_page(page, url)
    items = await service.extract(page, understanding)

---

ORIGINAL DOCUMENTATION (deprecated):

LLM-Driven Site Calibrator

Instead of hard-coded selectors, the LLM:
1. Analyzes the page and decides what elements matter
2. Creates its own extraction schema
3. Tests the schema and self-corrects if wrong
4. Loops up to MAX_ITERATIONS to get it right
"""
import warnings

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Any
from urllib.parse import urlparse, parse_qs

import aiohttp

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger("calibrator.llm")

MAX_ITERATIONS = 3

# Prompt cache for recipe-loaded prompts
_prompt_cache: Dict[str, str] = {}


def _load_prompt_via_recipe(recipe_name: str, category: str = "browser") -> str:
    """Load prompt via recipe system with inline fallback."""
    cache_key = f"{category}/{recipe_name}"
    if cache_key in _prompt_cache:
        return _prompt_cache[cache_key]
    try:
        from libs.gateway.recipe_loader import load_recipe
        recipe = load_recipe(f"{category}/{recipe_name}")
        content = recipe.get_prompt()
        _prompt_cache[cache_key] = content
        return content
    except Exception as e:
        logger.warning(f"Recipe {cache_key} not found: {e}")
        return ""


class LLMCalibrator:
    """
    DEPRECATED: Use PageIntelligenceService instead.

    LLM-driven site calibrator that learns extraction patterns through iteration.

    Flow:
    1. Show LLM the page HTML/structure
    2. LLM creates extraction schema (selectors for products, prices, etc.)
    3. Test the schema on the page
    4. If results are wrong/empty, show LLM the error and let it fix
    5. Loop until success or MAX_ITERATIONS
    """

    def __init__(
        self,
        llm_url: str = None,
        llm_model: str = None,
    ):
        warnings.warn(
            "LLMCalibrator is deprecated. Use PageIntelligenceService instead:\n"
            "  from apps.services.orchestrator.page_intelligence import get_page_intelligence_service\n"
            "  service = get_page_intelligence_service()\n"
            "  understanding = await service.understand_page(page, url)",
            DeprecationWarning,
            stacklevel=2
        )
        self.llm_url = llm_url or os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        self.llm_model = llm_model or os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        self.api_key = os.getenv("LLM_API_KEY", "qwen-local")

        logger.info(f"[LLM-Calibrator] Initialized with URL: {self.llm_url}, model: {self.llm_model}")

    async def calibrate(
        self,
        page: 'Page',
        url: str,
        site_intent: str = None
    ) -> Dict[str, Any]:
        """
        Calibrate extraction for a site using LLM-driven iteration.

        Args:
            page: Playwright page (already navigated to site)
            url: Current URL
            site_intent: What we want to extract (e.g., "product listings", "forum posts")

        Returns:
            Calibration schema with selectors and patterns
        """
        domain = urlparse(url).netloc.replace("www.", "")

        # Get page info for LLM
        page_context = await self._get_page_context(page, url)

        # Detect site intent if not provided
        if not site_intent:
            site_intent = await self._detect_site_intent(page_context)

        logger.info(f"[LLM-Calibrator] Calibrating {domain} for: {site_intent}")

        schema = None
        feedback = None

        for iteration in range(MAX_ITERATIONS):
            logger.info(f"[LLM-Calibrator] Iteration {iteration + 1}/{MAX_ITERATIONS}")

            # Ask LLM to create/fix schema
            schema = await self._llm_create_schema(
                page_context=page_context,
                site_intent=site_intent,
                previous_schema=schema,
                feedback=feedback
            )

            if not schema:
                logger.warning("[LLM-Calibrator] LLM failed to create schema")
                continue

            # Test the schema
            test_result = await self._test_schema(page, schema)

            if test_result["success"]:
                logger.info(f"[LLM-Calibrator] Schema validated successfully!")
                schema["validated"] = True
                schema["domain"] = domain
                schema["site_intent"] = site_intent
                schema["learned_at"] = datetime.now().isoformat()
                return schema
            else:
                # Prepare feedback for next iteration
                feedback = test_result["feedback"]
                logger.info(f"[LLM-Calibrator] Schema failed: {feedback}")

        # Return best effort even if not fully validated
        if schema:
            schema["validated"] = False
            schema["domain"] = domain
            schema["site_intent"] = site_intent
            schema["learned_at"] = datetime.now().isoformat()

        return schema or {"error": "Calibration failed after max iterations"}

    async def _get_page_context(self, page: 'Page', url: str) -> Dict[str, Any]:
        """Extract page context for LLM analysis."""
        try:
            context = await page.evaluate('''() => {
                // Get simplified DOM structure
                function simplifyElement(el, depth = 0) {
                    if (depth > 4) return null;
                    if (!el || el.nodeType !== 1) return null;

                    const tag = el.tagName.toLowerCase();

                    // Skip script, style, hidden
                    if (['script', 'style', 'noscript', 'svg', 'path'].includes(tag)) return null;
                    if (el.hidden || el.style.display === 'none') return null;

                    const obj = { tag };

                    // Include important attributes
                    if (el.id) obj.id = el.id;
                    if (el.className && typeof el.className === 'string') {
                        obj.class = el.className.split(' ').slice(0, 3).join(' ');
                    }
                    if (el.href) obj.href = el.href.slice(0, 100);
                    if (el.name) obj.name = el.name;

                    // Include text for leaf-ish nodes
                    const text = el.textContent?.trim();
                    if (text && text.length < 100 && el.children.length < 3) {
                        obj.text = text.slice(0, 80);
                    }

                    // Recurse for children
                    const children = [];
                    for (const child of el.children) {
                        const simplified = simplifyElement(child, depth + 1);
                        if (simplified) children.push(simplified);
                        if (children.length > 10) break;
                    }
                    if (children.length > 0) obj.children = children;

                    return obj;
                }

                // Get main content area
                const main = document.querySelector('main, #main, .main, [role="main"]') || document.body;
                const structure = simplifyElement(main, 0);

                // Get all visible text snippets with prices
                const pricePattern = /\\$\\d+(?:,\\d+)?(?:\\.\\d+)?/g;
                const textWithPrices = [];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const text = walker.currentNode.textContent?.trim();
                    if (text && pricePattern.test(text) && text.length < 200) {
                        textWithPrices.push(text);
                        if (textWithPrices.length > 20) break;
                    }
                }

                // Get a sample of repeated elements (likely product cards)
                const classCounts = {};
                document.querySelectorAll('*').forEach(el => {
                    if (el.className && typeof el.className === 'string') {
                        // Count each class separately
                        el.className.split(' ').forEach(cls => {
                            if (cls && cls.length > 2) {
                                classCounts[cls] = (classCounts[cls] || 0) + 1;
                            }
                        });
                    }
                });

                // Find classes with many instances (repeated elements = likely items)
                const repeatedClasses = Object.entries(classCounts)
                    .filter(([k, v]) => v >= 5 && v < 200 && !k.startsWith('.') && /^[a-zA-Z]/.test(k))
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 20)
                    .map(([k, v]) => ({ class: '.' + k, count: v }));

                // Sample HTML from first repeated element
                let sampleHTML = '';
                if (repeatedClasses.length > 0) {
                    // repeatedClasses[0].class already has the '.' prefix
                    const sample = document.querySelector(repeatedClasses[0].class);
                    if (sample) {
                        sampleHTML = sample.outerHTML.slice(0, 2000);
                    }
                }

                // URL info
                const url = window.location.href;
                const searchParams = Object.fromEntries(new URLSearchParams(window.location.search));

                return {
                    url: url,
                    title: document.title,
                    searchParams: searchParams,
                    textWithPrices: textWithPrices,
                    repeatedClasses: repeatedClasses,
                    sampleHTML: sampleHTML,
                    structure: structure
                };
            }''')

            return context or {}

        except Exception as e:
            logger.error(f"[LLM-Calibrator] Error getting page context: {e}")
            return {"error": str(e)}

    async def _detect_site_intent(self, page_context: Dict) -> str:
        """Detect what type of content the site has."""
        # Quick heuristic based on context
        if page_context.get("textWithPrices"):
            return "product_listings"

        url = page_context.get("url", "")
        if "reddit" in url or "forum" in url:
            return "forum_posts"
        if "wiki" in url:
            return "wiki_article"

        return "product_listings"  # Default for retail sites

    async def _llm_create_schema(
        self,
        page_context: Dict,
        site_intent: str,
        previous_schema: Dict = None,
        feedback: str = None
    ) -> Optional[Dict]:
        """Ask LLM to create or fix extraction schema."""

        prompt = self._build_schema_prompt(
            page_context=page_context,
            site_intent=site_intent,
            previous_schema=previous_schema,
            feedback=feedback
        )

        try:
            request_data = {
                "model": self.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 2000
            }
            logger.debug(f"[LLM-Calibrator] Sending request to {self.llm_url}")

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.llm_url,
                    json=request_data,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data["choices"][0]["message"]["content"]
                        logger.info(f"[LLM-Calibrator] Got LLM response: {len(content)} chars")
                        return self._parse_schema_response(content)
                    else:
                        body = await response.text()
                        logger.error(f"[LLM-Calibrator] LLM API error: {response.status} - {body[:200]}")

        except Exception as e:
            logger.error(f"[LLM-Calibrator] LLM request failed: {e}")

        return None

    def _build_schema_prompt(
        self,
        page_context: Dict,
        site_intent: str,
        previous_schema: Dict = None,
        feedback: str = None
    ) -> str:
        """Build prompt for LLM to create extraction schema."""
        # Load base prompt via recipe system
        base_instructions = _load_prompt_via_recipe("calibration_schema_creator", "browser")
        if not base_instructions:
            logger.warning("Calibration schema creator prompt not found via recipe")
            base_instructions = "You are analyzing a web page to create an extraction schema. Respond with JSON only."

        repeated = page_context.get('repeatedClasses', [])
        # Filter to likely item containers (10-100 instances usually means product cards)
        likely_items = [r for r in repeated if 10 <= r.get('count', 0) <= 100]

        # Build dynamic context
        dynamic_context = f"""
SITE INTENT: {site_intent}

PAGE CONTEXT:
- URL: {page_context.get('url', 'unknown')}
- Title: {page_context.get('title', 'unknown')}
- URL Parameters: {json.dumps(page_context.get('searchParams', {}), indent=2)}
- Text with prices found: {json.dumps(page_context.get('textWithPrices', [])[:10], indent=2)}

IMPORTANT - REPEATED ELEMENTS ON PAGE (use these as item_selector candidates):
{json.dumps(likely_items[:10], indent=2)}

These classes appear multiple times - the one with count closest to the number of products is likely your item_selector.
For example, if there are ~40 products and ".item-cell" has count: 42, use ".item-cell" as item_selector.

SAMPLE HTML (likely a product card or repeated item):
{page_context.get('sampleHTML', 'No sample available')[:3000]}
"""

        if previous_schema and feedback:
            dynamic_context += f"""

PREVIOUS ATTEMPT (FAILED):
{json.dumps(previous_schema, indent=2)}

WHAT WENT WRONG:
{feedback}

Please fix the schema based on this feedback.
"""

        prompt = f"""{base_instructions}

## Current Task

{dynamic_context}
"""
        return prompt

    def _parse_schema_response(self, content: str) -> Optional[Dict]:
        """Parse LLM response to extract JSON schema."""
        try:
            # Try to find JSON in the response
            # Look for JSON block
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
            if json_match:
                return json.loads(json_match.group(1))

            # Try parsing the whole content
            return json.loads(content)

        except json.JSONDecodeError:
            # Try to extract just the JSON part
            try:
                start = content.find('{')
                end = content.rfind('}') + 1
                if start >= 0 and end > start:
                    return json.loads(content[start:end])
            except:
                pass

        logger.warning(f"[LLM-Calibrator] Failed to parse schema: {content[:200]}")
        return None

    async def _test_schema(self, page: 'Page', schema: Dict) -> Dict[str, Any]:
        """Test the extraction schema on the page."""

        item_selector = schema.get("item_selector")
        fields = schema.get("fields", {})

        if not item_selector:
            return {
                "success": False,
                "feedback": "No item_selector provided. Need a CSS selector to find repeated items."
            }

        try:
            # Test extraction and get sample HTML for feedback
            results = await page.evaluate('''(schema) => {
                const items = document.querySelectorAll(schema.item_selector);
                if (items.length === 0) {
                    return { error: "No items found with selector: " + schema.item_selector };
                }

                const extracted = [];
                const errors = [];

                // Get sample HTML from first item for feedback
                const firstItem = items[0];
                const sampleHTML = firstItem.innerHTML.slice(0, 2000);

                // List available selectors in first item
                const availableElements = [];
                firstItem.querySelectorAll('*').forEach(el => {
                    const tag = el.tagName.toLowerCase();
                    const cls = el.className && typeof el.className === 'string'
                        ? '.' + el.className.split(' ')[0]
                        : '';
                    const text = el.textContent?.trim().slice(0, 50);
                    if (text && text.length > 2) {
                        availableElements.push({ selector: tag + cls, text: text });
                    }
                });

                items.forEach((item, i) => {
                    if (i >= 5) return; // Test first 5 items

                    const data = {};

                    for (const [field, config] of Object.entries(schema.fields || {})) {
                        try {
                            const el = item.querySelector(config.selector);
                            if (el) {
                                let value;
                                if (config.attribute === 'textContent') {
                                    value = el.textContent?.trim();
                                } else if (config.attribute === 'href' || config.attribute === 'src') {
                                    value = el[config.attribute];
                                } else {
                                    value = el.getAttribute(config.attribute);
                                }

                                // Apply transform
                                if (config.transform === 'price' && value) {
                                    const match = value.match(/[$]?([\d,]+\.?\d*)/);
                                    if (match) {
                                        value = parseFloat(match[1].replace(',', ''));
                                    }
                                }

                                data[field] = value;
                            } else {
                                data[field] = null;
                                errors.push("Field '" + field + "' selector '" + config.selector + "' not found");
                            }
                        } catch (e) {
                            errors.push("Error extracting " + field + ": " + e.message);
                        }
                    }

                    extracted.push(data);
                });

                return {
                    itemCount: items.length,
                    extracted: extracted,
                    errors: errors.slice(0, 5),
                    sampleHTML: sampleHTML,
                    availableElements: availableElements.slice(0, 20)
                };
            }''', schema)

            # Analyze results
            if "error" in results:
                return {
                    "success": False,
                    "feedback": results["error"]
                }

            item_count = results.get("itemCount", 0)
            extracted = results.get("extracted", [])
            errors = results.get("errors", [])
            sample_html = results.get("sampleHTML", "")
            available = results.get("availableElements", [])

            # Check quality
            if item_count == 0:
                return {
                    "success": False,
                    "feedback": f"Selector '{item_selector}' matched 0 items. Try a different selector."
                }

            # Check if we got meaningful data
            fields_with_data = set()
            for item in extracted:
                for field, value in item.items():
                    if value:
                        fields_with_data.add(field)

            if not fields_with_data:
                # Give LLM the actual HTML so it can see what selectors exist
                feedback = f"""Found {item_count} items but all field extractions were empty.

ACTUAL HTML INSIDE FIRST ITEM (use this to find correct selectors):
{sample_html[:1500]}

AVAILABLE ELEMENTS (selector -> sample text):
{json.dumps(available[:15], indent=2)}

Fix the field selectors based on this actual HTML structure."""
                return {
                    "success": False,
                    "feedback": feedback
                }

            # Check if we got key fields
            has_title = any(item.get("title") for item in extracted)
            has_price = any(item.get("price") for item in extracted)

            if not has_title and "title" in fields:
                feedback = f"""Title extraction failed.

ERRORS: {errors[:3]}

ACTUAL HTML INSIDE FIRST ITEM (use this to find correct title selector):
{sample_html[:1500]}

AVAILABLE ELEMENTS:
{json.dumps([e for e in available if 'title' in e.get('text', '').lower() or len(e.get('text', '')) > 10][:10], indent=2)}

Look for the product name in the HTML and provide the correct CSS selector."""
                return {
                    "success": False,
                    "feedback": feedback
                }

            # Success!
            return {
                "success": True,
                "item_count": item_count,
                "sample": extracted[:2],
                "fields_extracted": list(fields_with_data)
            }

        except Exception as e:
            return {
                "success": False,
                "feedback": f"JavaScript error: {str(e)}"
            }


async def test_llm_calibrator():
    """Quick test of the LLM calibrator."""
    from playwright.async_api import async_playwright

    calibrator = LLMCalibrator()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Test on Amazon
        await page.goto("https://www.amazon.com/s?k=laptop")
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(3)

        schema = await calibrator.calibrate(page, page.url)

        print("\n=== CALIBRATION RESULT ===")
        print(json.dumps(schema, indent=2, default=str))

        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_llm_calibrator())
