"""
orchestrator/page_intelligence/ocr_dom_mapper.py

OCR-DOM Cross-Reference Mapper

Maps OCR-detected text blocks to DOM elements by comparing bounding boxes.
This enables zone-aware vision extraction - we know which OCR text belongs
to which DOM element/zone.

Flow:
1. Get OCR text blocks with bounding boxes from screenshot
2. Get DOM elements with bounding boxes from page
3. Match OCR blocks to DOM elements by bbox overlap
4. Associate each text block with its zone
"""

import logging
from typing import TYPE_CHECKING, List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from apps.services.orchestrator.page_intelligence.models import (
    OCRTextBlock,
    DOMElement,
    Bounds,
    Zone,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


@dataclass
class MappedTextBlock:
    """OCR text block mapped to a DOM element."""
    ocr_block: OCRTextBlock
    dom_element: Optional[DOMElement]
    zone_type: Optional[str]
    match_confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.ocr_block.text,
            "ocr_bounds": self.ocr_block.bounds.to_dict(),
            "dom_selector": self.dom_element.selector if self.dom_element else None,
            "dom_text": self.dom_element.text if self.dom_element else None,
            "zone_type": self.zone_type,
            "match_confidence": self.match_confidence
        }


class OCRDOMMapper:
    """
    Maps OCR text blocks to DOM elements for zone-aware extraction.

    This cross-reference allows:
    - Vision extraction to know which zone each OCR text belongs to
    - Verification that DOM-extracted text matches OCR-detected text
    - Identification of text that exists visually but not in DOM (images, canvas)
    """

    def __init__(self, overlap_threshold: float = 0.3):
        """
        Initialize mapper.

        Args:
            overlap_threshold: Minimum bbox overlap ratio to consider a match
        """
        self.overlap_threshold = overlap_threshold

    async def get_dom_elements_with_bounds(
        self,
        page: 'Page',
        selectors: List[str] = None
    ) -> List[DOMElement]:
        """
        Get DOM elements with their bounding boxes.

        Args:
            page: Playwright page
            selectors: Optional list of selectors to query (default: visible text elements)

        Returns:
            List of DOMElement with bounds
        """
        try:
            elements_data = await page.evaluate('''(selectors) => {
                const results = [];

                // Default: find all visible text-containing elements
                const defaultQuery = selectors && selectors.length > 0
                    ? selectors.join(', ')
                    : 'h1, h2, h3, h4, h5, h6, p, span, a, div, li, td, th, label, button, [class*="price"], [class*="title"], [class*="name"]';

                const elements = document.querySelectorAll(defaultQuery);

                elements.forEach((el, index) => {
                    // Skip hidden elements
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') {
                        return;
                    }

                    // Skip elements with no text
                    const text = el.textContent?.trim();
                    if (!text || text.length === 0 || text.length > 500) {
                        return;
                    }

                    // Get bounding box
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) {
                        return;
                    }

                    // Build a selector for this element
                    let selector = el.tagName.toLowerCase();
                    if (el.id) {
                        selector = '#' + el.id;
                    } else if (el.className && typeof el.className === 'string') {
                        const classes = el.className.split(' ').filter(c => c && c.length < 50);
                        if (classes.length > 0) {
                            selector += '.' + classes.slice(0, 2).join('.');
                        }
                    }

                    // Get relevant attributes
                    const attrs = {};
                    if (el.href) attrs.href = el.href;
                    if (el.src) attrs.src = el.src;
                    if (el.getAttribute('data-price')) attrs.price = el.getAttribute('data-price');

                    results.push({
                        selector: selector,
                        tag: el.tagName.toLowerCase(),
                        text: text.slice(0, 200),
                        bounds: {
                            top: rect.top + window.scrollY,
                            left: rect.left + window.scrollX,
                            width: rect.width,
                            height: rect.height
                        },
                        attributes: attrs
                    });
                });

                return results.slice(0, 500);  // Limit to avoid huge responses
            }''', selectors)

            dom_elements = []
            for data in elements_data:
                dom_elements.append(DOMElement(
                    selector=data.get("selector", ""),
                    tag=data.get("tag", ""),
                    text=data.get("text", ""),
                    bounds=Bounds.from_dict(data.get("bounds", {})),
                    attributes=data.get("attributes", {})
                ))

            logger.info(f"[OCRDOMMapper] Found {len(dom_elements)} DOM elements with bounds")
            return dom_elements

        except Exception as e:
            logger.error(f"[OCRDOMMapper] Error getting DOM elements: {e}")
            return []

    def map_ocr_to_dom(
        self,
        ocr_blocks: List[OCRTextBlock],
        dom_elements: List[DOMElement],
        zones: List[Zone] = None
    ) -> List[MappedTextBlock]:
        """
        Map OCR text blocks to DOM elements by bounding box overlap.

        Args:
            ocr_blocks: Text blocks from OCR with bounds
            dom_elements: DOM elements with bounds
            zones: Optional zones to assign text to

        Returns:
            List of MappedTextBlock with DOM and zone associations
        """
        mapped_blocks = []

        for ocr_block in ocr_blocks:
            best_match: Optional[DOMElement] = None
            best_overlap = 0.0

            # Find DOM element with best bbox overlap
            for dom_el in dom_elements:
                overlap = ocr_block.bounds.overlap_ratio(dom_el.bounds)

                # Also check text similarity as secondary signal
                text_match = self._text_similarity(ocr_block.text, dom_el.text)

                # Combined score: overlap + text similarity bonus
                score = overlap + (0.2 * text_match if overlap > 0.1 else 0)

                if score > best_overlap:
                    best_overlap = score
                    best_match = dom_el

            # Find zone for this block
            zone_type = None
            if zones and best_match:
                zone_type = self._find_zone_for_element(best_match, zones)
            elif zones:
                zone_type = self._find_zone_for_bounds(ocr_block.bounds, zones)

            # Create mapped block
            mapped_blocks.append(MappedTextBlock(
                ocr_block=ocr_block,
                dom_element=best_match if best_overlap >= self.overlap_threshold else None,
                zone_type=zone_type,
                match_confidence=min(best_overlap, 1.0)
            ))

        matched_count = sum(1 for m in mapped_blocks if m.dom_element is not None)
        logger.info(f"[OCRDOMMapper] Mapped {matched_count}/{len(ocr_blocks)} OCR blocks to DOM elements")

        return mapped_blocks

    def _text_similarity(self, text1: str, text2: str) -> float:
        """
        Simple text similarity check.

        Returns 1.0 if one text contains the other, 0.0 otherwise.
        """
        t1 = text1.lower().strip()
        t2 = text2.lower().strip()

        if not t1 or not t2:
            return 0.0

        if t1 in t2 or t2 in t1:
            return 1.0

        # Check word overlap
        words1 = set(t1.split())
        words2 = set(t2.split())
        if words1 and words2:
            intersection = words1 & words2
            union = words1 | words2
            return len(intersection) / len(union) if union else 0.0

        return 0.0

    def _find_zone_for_element(self, element: DOMElement, zones: List[Zone]) -> Optional[str]:
        """Find which zone a DOM element belongs to."""
        # First check if element selector matches any zone anchor
        for zone in zones:
            for anchor in zone.dom_anchors:
                if anchor in element.selector:
                    return zone.zone_type.value if hasattr(zone.zone_type, 'value') else zone.zone_type

        # Fall back to bounds-based matching
        return self._find_zone_for_bounds(element.bounds, zones)

    def _find_zone_for_bounds(self, bounds: Bounds, zones: List[Zone]) -> Optional[str]:
        """Find which zone bounds belong to."""
        best_zone = None
        best_overlap = 0.0

        for zone in zones:
            if zone.bounds:
                overlap = bounds.overlap_ratio(zone.bounds)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_zone = zone.zone_type.value if hasattr(zone.zone_type, 'value') else zone.zone_type

        return best_zone if best_overlap > 0.1 else None

    def get_text_in_zone(
        self,
        mapped_blocks: List[MappedTextBlock],
        zone_type: str
    ) -> List[MappedTextBlock]:
        """Get all text blocks belonging to a specific zone."""
        return [b for b in mapped_blocks if b.zone_type == zone_type]

    def get_unmatched_ocr(
        self,
        mapped_blocks: List[MappedTextBlock]
    ) -> List[OCRTextBlock]:
        """Get OCR blocks that couldn't be matched to DOM elements."""
        return [b.ocr_block for b in mapped_blocks if b.dom_element is None]

    def verify_extraction(
        self,
        extracted_text: str,
        mapped_blocks: List[MappedTextBlock],
        zone_type: str = None
    ) -> Tuple[bool, float]:
        """
        Verify DOM-extracted text against OCR text.

        Args:
            extracted_text: Text extracted from DOM
            mapped_blocks: OCR-DOM mappings
            zone_type: Optional zone to limit verification to

        Returns:
            (verified, confidence) tuple
        """
        if zone_type:
            relevant_blocks = self.get_text_in_zone(mapped_blocks, zone_type)
        else:
            relevant_blocks = mapped_blocks

        if not relevant_blocks:
            return True, 0.5  # No OCR to verify against

        # Check if extracted text appears in any OCR block
        extracted_lower = extracted_text.lower().strip()

        for block in relevant_blocks:
            ocr_lower = block.ocr_block.text.lower().strip()
            if extracted_lower in ocr_lower or ocr_lower in extracted_lower:
                return True, 0.9

            # Check word overlap
            similarity = self._text_similarity(extracted_text, block.ocr_block.text)
            if similarity > 0.5:
                return True, 0.7 + (0.2 * similarity)

        return False, 0.3


async def get_ocr_text_blocks(
    screenshot_path: str,
    ocr_engine: str = "easyocr",
    min_confidence: float = 0.5
) -> List[OCRTextBlock]:
    """
    Get OCR text blocks from a screenshot using EasyOCR.

    Args:
        screenshot_path: Path to screenshot image
        ocr_engine: OCR engine to use (currently only 'easyocr' supported)
        min_confidence: Minimum confidence threshold for OCR results

    Returns:
        List of OCRTextBlock with bounding boxes and text
    """
    import asyncio
    from pathlib import Path

    if not Path(screenshot_path).exists():
        logger.warning(f"[OCRDOMMapper] Screenshot not found: {screenshot_path}")
        return []

    try:
        import easyocr

        # Run OCR in thread pool (EasyOCR is CPU-intensive)
        def run_ocr():
            reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            return reader.readtext(screenshot_path)

        loop = asyncio.get_event_loop()
        ocr_results = await loop.run_in_executor(None, run_ocr)

        text_blocks = []
        for (bbox, text, confidence) in ocr_results:
            if confidence >= min_confidence:
                # EasyOCR bbox is [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                x = min(p[0] for p in bbox)
                y = min(p[1] for p in bbox)
                width = max(p[0] for p in bbox) - x
                height = max(p[1] for p in bbox) - y

                text_blocks.append(OCRTextBlock(
                    text=text,
                    bounds=Bounds(x=x, y=y, width=width, height=height),
                    confidence=confidence
                ))

        logger.info(f"[OCRDOMMapper] Extracted {len(text_blocks)} OCR text blocks")
        return text_blocks

    except ImportError:
        logger.warning("[OCRDOMMapper] EasyOCR not installed. Install with: pip install easyocr")
        return []
    except Exception as e:
        logger.error(f"[OCRDOMMapper] OCR extraction failed: {e}")
        return []


def convert_ocr_items_to_blocks(ocr_items: List[Dict[str, Any]]) -> List[OCRTextBlock]:
    """
    Convert OCR items (from research_orchestrator) to OCRTextBlock format.

    This bridges the OCR results from research_orchestrator.py (Tier 1.1)
    to the page_intelligence models.

    Args:
        ocr_items: List of dicts with text, x, y, width, height, confidence

    Returns:
        List of OCRTextBlock
    """
    blocks = []
    for item in ocr_items:
        blocks.append(OCRTextBlock(
            text=item.get("text", ""),
            bounds=Bounds(
                x=item.get("x", 0),
                y=item.get("y", 0),
                width=item.get("width", 0),
                height=item.get("height", 0)
            ),
            confidence=item.get("confidence", 0.5)
        ))
    return blocks
