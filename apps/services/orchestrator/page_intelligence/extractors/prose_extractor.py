"""
orchestrator/page_intelligence/extractors/prose_extractor.py

Prose Extractor - Handles unstructured content

For pages without clear product grids:
- Contact-based pricing ("Call for price")
- Breeder/specialty sites with prose descriptions
- Article content
- Mixed content pages
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, List, Dict, Any, Optional

from apps.services.orchestrator.page_intelligence.models import Zone
from apps.services.orchestrator.page_intelligence.llm_client import LLMClient, get_llm_client

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# Cache for loaded prompts
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


def _load_extractor_prompt(extractor_type: str) -> str:
    """
    Load extractor prompt via recipe system.

    Args:
        extractor_type: Type of extractor (prose_intel, article, forum, list, news, generic, contact_info)

    Returns:
        Prompt content from recipe, or fallback if not found
    """
    prompt = _load_prompt_via_recipe(extractor_type, "browser")
    if not prompt:
        logger.warning(f"[ProseExtractor] Prompt {extractor_type} not found via recipe")
        return "Extract relevant information from the content. Return valid JSON."
    return prompt


class ProseExtractor:
    """
    Extract information from unstructured prose content.

    Uses LLM to interpret free-form text and extract relevant information.
    Best for:
    - Pages with "Contact for pricing"
    - Breeder sites with prose descriptions
    - Article/blog content
    - Pages where selector extraction fails
    """

    def __init__(
        self,
        llm_client: LLMClient = None,
        llm_url: str = None,
        llm_model: str = None
    ):
        """
        Initialize prose extractor.

        Args:
            llm_client: Shared LLM client (recommended)
            llm_url: URL for LLM API (if not using shared client)
            llm_model: Model name
        """
        self.llm_client = llm_client or get_llm_client(llm_url, llm_model)

    async def extract(
        self,
        page: 'Page',
        zone: Zone = None,
        extraction_goal: str = "products",
        max_text_length: int = 5000,
        query_context: str = None
    ) -> Dict[str, Any]:
        """
        Extract information from prose content.

        Args:
            page: Playwright page
            zone: Optional zone to limit extraction to
            extraction_goal: What to extract (products, article, contact_info)
            max_text_length: Maximum text to send to LLM
            query_context: Original user query for relevance filtering (optional)

        Returns:
            Extracted information (structure depends on goal)
        """
        # Get page text
        page_text = await self._get_page_text(page, zone, max_text_length)

        if not page_text or len(page_text) < 50:
            logger.warning("[ProseExtractor] Insufficient text content")
            return {"error": "Insufficient text content", "items": []}

        # For link-heavy content (forums, news, lists), also extract links
        # Use higher link limit for forums/topic pages which can have 100+ thread links
        page_links = []
        if extraction_goal in ("topics", "threads", "popular_topics", "list_items", "list", "items", "news", "articles"):
            # Forums often have 100+ thread links - use 200 limit for thorough extraction
            link_limit = 200 if extraction_goal in ("topics", "threads", "popular_topics") else 100
            page_links = await self._get_page_links(page, zone, max_links=link_limit)
            logger.info(f"[ProseExtractor] Extracted {len(page_links)} links for {extraction_goal} (limit: {link_limit})")

        # Use LLM to extract based on goal
        if extraction_goal == "products":
            return await self._extract_products(page_text, query_context=query_context)
        elif extraction_goal == "article":
            return await self._extract_article(page_text)
        elif extraction_goal == "contact_info":
            return await self._extract_contact_info(page_text)
        elif extraction_goal in ("topics", "threads", "popular_topics"):
            return await self._extract_topics(page_text, page_links, query_context=query_context)
        elif extraction_goal in ("list_items", "list", "items"):
            return await self._extract_list_items(page_text, page_links)
        elif extraction_goal in ("news", "articles"):
            return await self._extract_news_items(page_text, page_links)
        else:
            return await self._extract_general(page_text, extraction_goal)

    async def _get_page_text(
        self,
        page: 'Page',
        zone: Zone = None,
        max_length: int = 5000
    ) -> str:
        """Get text content from page."""
        try:
            text = await page.evaluate('''(zoneBounds) => {
                let container = document.body;

                // If zone bounds provided, find elements within bounds
                if (zoneBounds) {
                    const main = document.querySelector('main, #main, .main') || document.body;
                    container = main;
                }

                // Get text content, preserving some structure
                const walker = document.createTreeWalker(
                    container,
                    NodeFilter.SHOW_TEXT,
                    null,
                    false
                );

                const texts = [];
                let lastBlock = '';
                while (walker.nextNode()) {
                    const text = walker.currentNode.textContent?.trim();
                    if (text && text.length > 2) {
                        // Check if this is a new block (different parent)
                        const parent = walker.currentNode.parentElement;
                        const tag = parent?.tagName?.toLowerCase();
                        if (['p', 'h1', 'h2', 'h3', 'h4', 'li', 'td', 'div'].includes(tag)) {
                            texts.push('\\n' + text);
                        } else {
                            texts.push(text);
                        }
                    }
                }

                return texts.join(' ').trim();
            }''', zone.bounds.to_dict() if zone and zone.bounds else None)

            return text[:max_length] if text else ""

        except Exception as e:
            logger.error(f"[ProseExtractor] Error getting page text: {e}")
            return ""

    async def _get_page_links(
        self,
        page: 'Page',
        zone: Zone = None,
        max_links: int = 50
    ) -> List[Dict[str, str]]:
        """
        Get links from page with their text and URLs.

        Returns list of {title, url} dicts for each link found.
        Uses zone bounds to filter to content area only (not navigation).
        """
        try:
            links = await page.evaluate('''(args) => {
                const { zoneBounds, maxLinks } = args;
                const results = [];
                const seenUrls = new Set();

                // Find all links on page
                const allLinks = document.querySelectorAll('a[href]');

                for (const a of allLinks) {
                    if (results.length >= maxLinks) break;

                    const href = a.href;
                    const text = a.textContent?.trim();

                    // Skip empty, duplicate, or navigation-only links
                    if (!text || text.length < 3) continue;
                    if (!href || href === '#' || href.startsWith('javascript:')) continue;
                    if (seenUrls.has(href)) continue;

                    // If zone bounds provided, only include links within the zone
                    if (zoneBounds) {
                        const rect = a.getBoundingClientRect();
                        const linkCenterY = rect.top + rect.height / 2;
                        const linkCenterX = rect.left + rect.width / 2;

                        // Check if link is within the zone bounds (with some margin)
                        const margin = 50;
                        const inZone = (
                            linkCenterY >= zoneBounds.top - margin &&
                            linkCenterY <= zoneBounds.bottom + margin &&
                            linkCenterX >= zoneBounds.left - margin &&
                            linkCenterX <= zoneBounds.right + margin
                        );

                        if (!inZone) continue;
                    }

                    // Zone bounds is the primary filter - only include links within content area
                    // If no zone bounds, we already included all links (no position filtering above)
                    // Just add the link
                    seenUrls.add(href);
                    results.push({
                        title: text.substring(0, 200),
                        url: href
                    });
                }

                return results;
            }''', {"zoneBounds": zone.bounds.to_dict() if zone and zone.bounds else None, "maxLinks": max_links})

            return links or []

        except Exception as e:
            logger.error(f"[ProseExtractor] Error getting page links: {e}")
            return []

    async def _extract_products(self, text: str, query_context: str = None) -> Dict[str, Any]:
        """Extract product/recommendation information from prose for intelligence gathering."""
        base_prompt = _load_extractor_prompt("prose_intel")

        # Build context section if query provided
        context_section = ""
        if query_context:
            context_section = f"RESEARCH CONTEXT: {query_context}\n\n"

        prompt = f"""{base_prompt}

---

## Current Task

{context_section}Page text to analyze:
---
{text[:4000]}
---

Return ONLY valid JSON.
"""

        return await self._call_llm(prompt)

    async def _extract_article(self, text: str) -> Dict[str, Any]:
        """Extract article content."""
        base_prompt = _load_extractor_prompt("article")

        prompt = f"""{base_prompt}

---

## Current Task

Page text to analyze:
---
{text[:4000]}
---

Return ONLY valid JSON.
"""

        return await self._call_llm(prompt)

    async def _extract_contact_info(self, text: str) -> Dict[str, Any]:
        """Extract contact information."""
        base_prompt = _load_extractor_prompt("contact_info")
        if not base_prompt:
            # Fallback inline prompt if file not found
            base_prompt = """Extract contact information from this page text.

Return JSON:
{
  "business_name": "Name" or null,
  "phone": "Phone number" or null,
  "email": "Email" or null,
  "address": "Address" or null,
  "contact_form": true or false,
  "social_media": ["link1", "link2"] or []
}

Return ONLY valid JSON."""

        prompt = f"""{base_prompt}

---

Page text:
---
{text[:3000]}
---

Return ONLY valid JSON.
"""

        return await self._call_llm(prompt)

    async def _extract_topics(self, text: str, page_links: List[Dict[str, str]] = None, query_context: str = None) -> Dict[str, Any]:
        """Extract forum topics, threads, or discussions from prose."""
        base_prompt = _load_extractor_prompt("forum")

        # Build context section if query provided
        context_section = ""
        if query_context:
            context_section = f"""## User's Goal
The user asked: **{query_context}**

Focus on extracting the information that answers this query. If they asked for "popular topics", extract the topic/thread TITLES, not timestamps or metadata.

---

"""

        prompt = f"""{base_prompt}

---

{context_section}## Current Task

Page text to analyze:
---
{text[:6000]}
---

Return ONLY valid JSON.
"""

        # Topics often have many items, use higher token limit
        result = await self._call_llm(prompt, max_tokens=3000)

        # Attach extracted links to result for reference/navigation
        if page_links:
            result["extracted_links"] = page_links
            logger.info(f"[ProseExtractor] Attached {len(page_links)} links to topics result")

        return result

    async def _extract_list_items(self, text: str, page_links: List[Dict[str, str]] = None) -> Dict[str, Any]:
        """Extract generic list items from page content."""
        base_prompt = _load_extractor_prompt("list")

        prompt = f"""{base_prompt}

---

## Current Task

Page text to analyze:
---
{text[:6000]}
---

Return ONLY valid JSON.
"""

        # List items often have many entries, use higher token limit
        result = await self._call_llm(prompt, max_tokens=3000)

        # Attach extracted links to result for reference/navigation
        if page_links:
            result["extracted_links"] = page_links
            logger.info(f"[ProseExtractor] Attached {len(page_links)} links to list items result")

        return result

    async def _extract_news_items(self, text: str, page_links: List[Dict[str, str]] = None) -> Dict[str, Any]:
        """Extract news articles or blog posts from page content."""
        base_prompt = _load_extractor_prompt("news")

        prompt = f"""{base_prompt}

---

## Current Task

Page text to analyze:
---
{text[:6000]}
---

Return ONLY valid JSON.
"""

        # News items often have many entries, use higher token limit
        result = await self._call_llm(prompt, max_tokens=3000)

        # Attach extracted links to result for reference/navigation
        if page_links:
            result["extracted_links"] = page_links
            logger.info(f"[ProseExtractor] Attached {len(page_links)} links to news items result")

        return result

    async def _extract_general(self, text: str, goal: str) -> Dict[str, Any]:
        """General extraction based on goal."""
        base_prompt = _load_extractor_prompt("generic")

        prompt = f"""{base_prompt}

---

## Current Task

**Extraction Goal:** {goal}

Page text to analyze:
---
{text[:4000]}
---

Return ONLY valid JSON.
"""

        return await self._call_llm(prompt)

    async def _call_llm(self, prompt: str, max_tokens: int = 2000) -> Dict[str, Any]:
        """Call LLM and parse response using shared client."""
        result = await self.llm_client.call(prompt, max_tokens=max_tokens)

        if "error" in result:
            logger.error(f"[ProseExtractor] LLM error: {result.get('error')}")
            return {"error": result.get("error")}

        return result

    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        """Parse JSON from LLM response (legacy - LLMClient now handles parsing)."""
        # Try to find JSON block
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except (json.JSONDecodeError, ValueError) as e:
                logger.debug(f"[ProseExtractor] Code block parse failed: {e}")

        # Try parsing whole content
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"[ProseExtractor] Full content parse failed: {e}")

        # Try to extract JSON object
        try:
            start = content.find('{')
            end = content.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"[ProseExtractor] Object extraction failed: {e}")

        logger.warning(f"[ProseExtractor] Could not parse response: {content[:200]}")
        return {"error": "Could not parse response", "raw": content[:500]}

    async def detect_pricing_model(
        self,
        page: 'Page'
    ) -> str:
        """
        Detect the pricing model used on the page.

        Returns: "fixed", "contact", "auction", "quote", or "unknown"
        """
        try:
            indicators = await page.evaluate('''() => {
                const text = document.body.textContent?.toLowerCase() || '';

                return {
                    hasFixedPrices: /\\$\\d+/.test(text),
                    hasContactForPrice: /contact.*(for|about).*(price|pricing|quote)/i.test(text) ||
                                       /call.*(for|to).*(price|pricing|quote)/i.test(text) ||
                                       /request.*(a|for)?.*(quote|pricing)/i.test(text),
                    hasAuction: /bid|auction|current bid|starting bid/i.test(text),
                    hasQuoteForm: !!document.querySelector('form[action*="quote"], form[action*="contact"], .quote-form, .contact-form'),
                    hasBuyButton: !!document.querySelector('button[class*="buy"], button[class*="cart"], .add-to-cart, .buy-now')
                };
            }''')

            if indicators.get("hasAuction"):
                return "auction"
            elif indicators.get("hasContactForPrice") and not indicators.get("hasFixedPrices"):
                return "contact"
            elif indicators.get("hasQuoteForm") and not indicators.get("hasFixedPrices"):
                return "quote"
            elif indicators.get("hasFixedPrices") or indicators.get("hasBuyButton"):
                return "fixed"
            else:
                return "unknown"

        except Exception as e:
            logger.error(f"[ProseExtractor] Error detecting pricing model: {e}")
            return "unknown"
