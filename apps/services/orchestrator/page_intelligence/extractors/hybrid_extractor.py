"""
orchestrator/page_intelligence/extractors/hybrid_extractor.py

Hybrid Extractor - Combines selector and vision extraction

Best accuracy by cross-validating DOM extraction with OCR.
Use when high accuracy is critical (e.g., price verification).
"""

import logging
from typing import TYPE_CHECKING, List, Dict, Any, Optional

from apps.services.orchestrator.page_intelligence.models import (
    Zone,
    ZoneSelectors,
    OCRTextBlock,
)
from apps.services.orchestrator.page_intelligence.extractors.selector_extractor import SelectorExtractor
from apps.services.orchestrator.page_intelligence.extractors.vision_extractor import VisionExtractor
from apps.services.orchestrator.page_intelligence.ocr_dom_mapper import OCRDOMMapper, MappedTextBlock

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class HybridExtractor:
    """
    Hybrid extraction combining DOM selectors with OCR verification.

    Flow:
    1. Extract items using CSS selectors (fast, structured)
    2. Extract prices using OCR/vision (accurate for visual text)
    3. Cross-validate: verify DOM-extracted prices match OCR prices
    4. Use OCR prices if DOM prices seem wrong
    """

    def __init__(self):
        self.selector_extractor = SelectorExtractor()
        self.vision_extractor = VisionExtractor()
        self.ocr_dom_mapper = OCRDOMMapper()

    async def extract(
        self,
        page: 'Page',
        zone: Zone,
        zone_selectors: ZoneSelectors,
        ocr_blocks: List[OCRTextBlock] = None,
        mapped_blocks: List[MappedTextBlock] = None,
        verify_fields: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract items using hybrid approach.

        Args:
            page: Playwright page
            zone: Zone to extract from
            zone_selectors: CSS selectors from Phase 2
            ocr_blocks: OCR text blocks
            mapped_blocks: Pre-mapped OCR-DOM blocks
            verify_fields: Fields to verify with OCR (default: ["price"])

        Returns:
            List of extracted items with verification status
        """
        verify_fields = verify_fields or ["price"]

        # Step 1: Extract using selectors
        selector_items = await self.selector_extractor.extract(page, zone_selectors)

        if not selector_items:
            logger.info("[HybridExtractor] Selector extraction empty, falling back to vision")
            return await self.vision_extractor.extract(
                page, zone,
                ocr_blocks=ocr_blocks,
                mapped_blocks=mapped_blocks,
                extraction_goal="products"
            )

        # Step 2: Get OCR prices for verification
        ocr_prices = await self.vision_extractor.extract_prices_only(page, zone)

        if not ocr_prices:
            logger.info("[HybridExtractor] No OCR prices found, returning selector results")
            for item in selector_items:
                item["_verification"] = "no_ocr_available"
            return selector_items

        # Step 3: Cross-validate prices
        verified_items = self._verify_prices(selector_items, ocr_prices)

        return verified_items

    def _verify_prices(
        self,
        selector_items: List[Dict[str, Any]],
        ocr_prices: List[float]
    ) -> List[Dict[str, Any]]:
        """
        Verify DOM-extracted prices against OCR prices.

        Args:
            selector_items: Items from selector extraction
            ocr_prices: Prices detected by OCR

        Returns:
            Items with verification status and corrected prices if needed
        """
        verified = []
        used_ocr_indices = set()

        for item in selector_items:
            dom_price = item.get("price")
            item["_original_price"] = dom_price

            if dom_price is None:
                # No price from DOM, try to find matching OCR price
                item["_verification"] = "no_dom_price"
                verified.append(item)
                continue

            # Find closest matching OCR price
            best_match_idx = None
            best_diff = float('inf')

            for i, ocr_price in enumerate(ocr_prices):
                if i in used_ocr_indices:
                    continue

                diff = abs(dom_price - ocr_price)
                diff_pct = diff / ocr_price if ocr_price > 0 else float('inf')

                # Consider a match if within 5% or $1
                if diff_pct < 0.05 or diff < 1:
                    if diff < best_diff:
                        best_diff = diff
                        best_match_idx = i

            if best_match_idx is not None:
                # Price verified
                item["_verification"] = "verified"
                item["_ocr_price"] = ocr_prices[best_match_idx]
                used_ocr_indices.add(best_match_idx)
            else:
                # Price mismatch - try to find any unused OCR price
                # This might indicate the DOM price is wrong
                item["_verification"] = "unverified"

                # Check if any unused OCR price is reasonable for this item
                unused_prices = [p for i, p in enumerate(ocr_prices) if i not in used_ocr_indices]
                if unused_prices:
                    # Use closest unused price if DOM price seems unreasonable
                    # (e.g., too low, might be a shipping cost)
                    if dom_price < 10 and min(unused_prices) > 20:
                        # DOM price might be shipping, use OCR price
                        closest_ocr = min(unused_prices, key=lambda p: abs(p - 50))  # Assume reasonable price
                        item["price"] = closest_ocr
                        item["_ocr_price"] = closest_ocr
                        item["_verification"] = "corrected_from_ocr"

            verified.append(item)

        # Log verification summary
        verified_count = sum(1 for i in verified if i.get("_verification") == "verified")
        corrected_count = sum(1 for i in verified if i.get("_verification") == "corrected_from_ocr")
        logger.info(f"[HybridExtractor] Verified {verified_count}/{len(verified)} prices, corrected {corrected_count}")

        return verified

    async def extract_with_full_ocr_mapping(
        self,
        page: 'Page',
        zone: Zone,
        zone_selectors: ZoneSelectors,
        screenshot_path: str = None
    ) -> List[Dict[str, Any]]:
        """
        Full hybrid extraction with OCR-DOM mapping.

        More thorough but slower - maps OCR text to DOM elements.
        """
        # Get DOM elements with bounds
        dom_elements = await self.ocr_dom_mapper.get_dom_elements_with_bounds(page)

        # Get OCR blocks (placeholder - integrate with actual OCR)
        ocr_blocks = []  # TODO: Integrate OCR

        # Map OCR to DOM
        mapped_blocks = self.ocr_dom_mapper.map_ocr_to_dom(
            ocr_blocks, dom_elements, [zone]
        )

        # Extract with mapping
        return await self.extract(
            page, zone, zone_selectors,
            mapped_blocks=mapped_blocks
        )
