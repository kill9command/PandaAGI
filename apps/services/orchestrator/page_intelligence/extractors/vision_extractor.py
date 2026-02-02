"""
orchestrator/page_intelligence/extractors/vision_extractor.py

Vision Extractor - OCR-based extraction

Extracts data from screenshots using OCR. Best for visual-heavy pages
or when DOM selectors are unreliable.

Uses zone-aware extraction: only processes OCR text within specified zone bounds.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, List, Dict, Any, Optional

from apps.services.orchestrator.page_intelligence.models import (
    Zone,
    Bounds,
    OCRTextBlock,
)
from apps.services.orchestrator.page_intelligence.ocr_dom_mapper import OCRDOMMapper, MappedTextBlock
from apps.services.orchestrator.page_intelligence.llm_client import LLMClient, get_llm_client

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

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


class VisionExtractor:
    """
    Extract data using OCR/vision analysis.

    Uses LLM to interpret OCR text blocks within zone bounds.
    """

    def __init__(
        self,
        llm_client: LLMClient = None,
        llm_url: str = None,
        llm_model: str = None
    ):
        """
        Initialize vision extractor.

        Args:
            llm_client: Shared LLM client (recommended)
            llm_url: URL for LLM API (if not using shared client)
            llm_model: Model name
        """
        self.llm_client = llm_client or get_llm_client(llm_url, llm_model)
        self.ocr_dom_mapper = OCRDOMMapper()

    async def extract(
        self,
        page: 'Page',
        zone: Zone,
        ocr_blocks: List[OCRTextBlock] = None,
        mapped_blocks: List[MappedTextBlock] = None,
        extraction_goal: str = "products"
    ) -> List[Dict[str, Any]]:
        """
        Extract items from a zone using vision/OCR.

        Args:
            page: Playwright page
            zone: Zone to extract from (with bounds)
            ocr_blocks: OCR text blocks (if not provided, uses mapped_blocks)
            mapped_blocks: Pre-mapped OCR-DOM blocks
            extraction_goal: What to extract (products, prices, etc.)

        Returns:
            List of extracted items
        """
        zone_type = zone.zone_type.value if hasattr(zone.zone_type, 'value') else zone.zone_type

        # Get text blocks for this zone
        if mapped_blocks:
            zone_blocks = [b for b in mapped_blocks if b.zone_type == zone_type]
            text_blocks = [
                {"text": b.ocr_block.text, "bounds": b.ocr_block.bounds.to_dict()}
                for b in zone_blocks
            ]
        elif ocr_blocks and zone.bounds:
            # Filter OCR blocks to zone bounds
            text_blocks = []
            for block in ocr_blocks:
                if zone.bounds.overlaps(block.bounds):
                    text_blocks.append({
                        "text": block.text,
                        "bounds": block.bounds.to_dict()
                    })
        else:
            # Fallback: use all text from page
            text_blocks = await self._get_page_text_blocks(page, zone)

        if not text_blocks:
            logger.warning(f"[VisionExtractor] No text blocks found for zone {zone_type}")
            return []

        # Use LLM to interpret text blocks into structured items
        return await self._interpret_text_blocks(text_blocks, extraction_goal, zone_type)

    async def _get_page_text_blocks(
        self,
        page: 'Page',
        zone: Zone
    ) -> List[Dict[str, Any]]:
        """Get text blocks from page DOM as fallback."""
        try:
            # Get visible text with approximate bounds
            text_data = await page.evaluate('''(zoneBounds) => {
                const blocks = [];

                // Get elements with text content
                const elements = document.querySelectorAll('*');
                elements.forEach(el => {
                    const text = el.textContent?.trim();
                    if (!text || text.length < 3 || text.length > 500) return;

                    // Skip if element has children with text (avoid duplicates)
                    if (Array.from(el.children).some(child =>
                        child.textContent?.trim() === text
                    )) return;

                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) return;

                    // Check if in zone bounds
                    if (zoneBounds) {
                        const top = rect.top + window.scrollY;
                        const left = rect.left + window.scrollX;
                        if (top < zoneBounds.top || top > zoneBounds.top + zoneBounds.height) return;
                        if (left < zoneBounds.left || left > zoneBounds.left + zoneBounds.width) return;
                    }

                    blocks.push({
                        text: text.slice(0, 200),
                        bounds: {
                            top: rect.top + window.scrollY,
                            left: rect.left + window.scrollX,
                            width: rect.width,
                            height: rect.height
                        }
                    });
                });

                // Deduplicate by text
                const seen = new Set();
                return blocks.filter(b => {
                    if (seen.has(b.text)) return false;
                    seen.add(b.text);
                    return true;
                }).slice(0, 100);
            }''', zone.bounds.to_dict() if zone.bounds else None)

            return text_data or []

        except Exception as e:
            logger.error(f"[VisionExtractor] Error getting text blocks: {e}")
            return []

    async def _interpret_text_blocks(
        self,
        text_blocks: List[Dict[str, Any]],
        extraction_goal: str,
        zone_type: str
    ) -> List[Dict[str, Any]]:
        """Use LLM to interpret text blocks into structured items."""
        # Sort blocks by position (top to bottom, left to right)
        sorted_blocks = sorted(
            text_blocks,
            key=lambda b: (b["bounds"]["top"], b["bounds"]["left"])
        )

        # Group nearby blocks (same Y coordinate = same row)
        text_summary = "\n".join([
            f"[{b['bounds']['top']:.0f},{b['bounds']['left']:.0f}] {b['text']}"
            for b in sorted_blocks[:50]
        ])

        # Load prompt via recipe system
        base_prompt = _load_prompt_via_recipe("vision_zone", "browser")
        if not base_prompt:
            logger.warning("[VisionExtractor] Vision zone prompt not found via recipe")
            base_prompt = """Analyze OCR text blocks and extract items. Return JSON array of items with title, price, rating fields. Return ONLY the JSON array."""

        prompt = f"""{base_prompt}

## Current Task

**Zone Type:** {zone_type}
**Extraction Goal:** {extraction_goal}

**Text blocks (format: [top,left] text):**
{text_summary}
"""

        # Use shared LLM client
        result = await self.llm_client.call(prompt, max_tokens=2000)

        if "error" in result:
            logger.error(f"[VisionExtractor] LLM error: {result.get('error')}")
            return []

        # Result is already parsed JSON from LLMClient
        # Check if it's a list (items array) or has an "items" key
        if isinstance(result, list):
            return result
        elif "items" in result:
            return result["items"]
        else:
            # Try to extract items from parsed result
            return self._parse_items_response(str(result))

    def _parse_items_response(self, content: str) -> List[Dict[str, Any]]:
        """Parse LLM response to extract items array."""
        # Try to find JSON array in code block
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if json_match:
            try:
                result = json.loads(json_match.group(1))
                if isinstance(result, list):
                    return result
            except (json.JSONDecodeError, ValueError) as e:
                logger.debug(f"[VisionExtractor] Code block parse failed: {e}")

        # Try parsing whole content
        try:
            result = json.loads(content)
            if isinstance(result, list):
                return result
            return []
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"[VisionExtractor] Full content parse failed: {e}")

        # Try to extract array
        try:
            start = content.find('[')
            end = content.rfind(']') + 1
            if start >= 0 and end > start:
                result = json.loads(content[start:end])
                if isinstance(result, list):
                    return result
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"[VisionExtractor] Array extraction failed: {e}")

        logger.warning(f"[VisionExtractor] Could not parse response: {content[:200]}")
        return []

    async def extract_prices_only(
        self,
        page: 'Page',
        zone: Zone
    ) -> List[float]:
        """
        Quick extraction of just prices from a zone.

        Useful for price verification without full extraction.
        """
        text_blocks = await self._get_page_text_blocks(page, zone)

        prices = []
        price_pattern = re.compile(r'\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)')

        for block in text_blocks:
            matches = price_pattern.findall(block["text"])
            for match in matches:
                try:
                    price = float(match.replace(',', ''))
                    prices.append(price)
                except ValueError:
                    pass

        return prices
