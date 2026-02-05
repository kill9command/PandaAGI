"""
OCR-DOM Validator for Page Intelligence

Cross-validation for text grounding with agreement boost.
Validates OCR extractions against DOM elements to increase
confidence in extracted data.

Architecture reference: panda_system_docs/architecture/mcp-tool-patterns/
                       internet-research-mcp/unified-page-intelligence.md
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set
from difflib import SequenceMatcher
import re

from .models import OCRTextBlock, DOMElement, MatchedItem, PageDocument


# Validation thresholds
VALIDATION_CONFIG = {
    "text_similarity_threshold": 0.75,  # Minimum similarity for text match
    "position_tolerance_px": 50,        # Position tolerance in pixels
    "position_tolerance_pct": 0.05,     # Position tolerance as % of page
    "agreement_boost": 0.15,            # Confidence boost when OCR and DOM agree
    "disagreement_penalty": 0.10,       # Confidence penalty when they disagree
    "ocr_only_floor": 0.60,             # Max confidence for OCR-only items
    "dom_only_floor": 0.70,             # Max confidence for DOM-only items
}


@dataclass
class ValidationResult:
    """Result of validating an extraction"""
    is_valid: bool
    confidence: float
    source: str  # "ocr", "dom", "both"
    issues: List[str] = field(default_factory=list)
    matches: List[str] = field(default_factory=list)


@dataclass
class CrossValidationReport:
    """Report from cross-validating OCR and DOM extractions"""
    ocr_item_count: int
    dom_item_count: int
    matched_count: int
    unmatched_ocr: int
    unmatched_dom: int
    average_confidence: float
    agreement_rate: float  # Percentage of items that matched
    issues: List[str] = field(default_factory=list)


class OCRDOMValidator:
    """
    Validates extractions by cross-referencing OCR and DOM data.
    Agreement between sources boosts confidence; disagreement lowers it.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or VALIDATION_CONFIG

    def validate_text_match(
        self,
        ocr_text: str,
        dom_text: str
    ) -> Tuple[bool, float]:
        """
        Check if OCR text matches DOM text.

        Returns:
            (is_match, similarity_score)
        """
        # Normalize texts
        ocr_norm = self._normalize_text(ocr_text)
        dom_norm = self._normalize_text(dom_text)

        if not ocr_norm or not dom_norm:
            return (False, 0.0)

        # Exact match
        if ocr_norm == dom_norm:
            return (True, 1.0)

        # Fuzzy match
        similarity = SequenceMatcher(None, ocr_norm, dom_norm).ratio()

        is_match = similarity >= self.config["text_similarity_threshold"]
        return (is_match, similarity)

    def validate_position_match(
        self,
        ocr_x: int,
        ocr_y: int,
        dom_x: int,
        dom_y: int,
        page_width: int,
        page_height: int
    ) -> Tuple[bool, float]:
        """
        Check if OCR position matches DOM position.

        Returns:
            (is_match, proximity_score)
        """
        # Calculate distance
        dx = abs(ocr_x - dom_x)
        dy = abs(ocr_y - dom_y)

        # Check pixel tolerance
        px_tolerance = self.config["position_tolerance_px"]
        if dx <= px_tolerance and dy <= px_tolerance:
            # Calculate proximity score (closer = higher)
            max_dist = px_tolerance * 1.414  # sqrt(2) * tolerance
            actual_dist = (dx**2 + dy**2) ** 0.5
            proximity = 1.0 - (actual_dist / max_dist)
            return (True, max(0.5, proximity))

        # Check percentage tolerance
        pct_tolerance = self.config["position_tolerance_pct"]
        dx_pct = dx / page_width if page_width > 0 else 1.0
        dy_pct = dy / page_height if page_height > 0 else 1.0

        if dx_pct <= pct_tolerance and dy_pct <= pct_tolerance:
            proximity = 1.0 - ((dx_pct + dy_pct) / (2 * pct_tolerance))
            return (True, max(0.5, proximity))

        return (False, 0.0)

    def find_matches(
        self,
        ocr_items: List[OCRTextBlock],
        dom_items: List[DOMElement],
        page_width: int,
        page_height: int
    ) -> List[MatchedItem]:
        """
        Find matching pairs between OCR and DOM items.

        Returns:
            List of MatchedItem with cross-referenced data
        """
        matched = []
        used_dom_indices: Set[int] = set()

        for ocr_item in ocr_items:
            best_match: Optional[Tuple[int, DOMElement, float, float]] = None
            best_score = 0.0

            for dom_idx, dom_item in enumerate(dom_items):
                if dom_idx in used_dom_indices:
                    continue

                # Check text similarity
                text_match, text_sim = self.validate_text_match(
                    ocr_item.text, dom_item.text
                )
                if not text_match:
                    continue

                # Check position proximity
                pos_match, pos_sim = self.validate_position_match(
                    ocr_item.x, ocr_item.y,
                    dom_item.x, dom_item.y,
                    page_width, page_height
                )

                # Combined score (text weighted more than position)
                combined_score = text_sim * 0.7 + (pos_sim if pos_match else 0) * 0.3

                if combined_score > best_score:
                    best_score = combined_score
                    best_match = (dom_idx, dom_item, text_sim, pos_sim if pos_match else 0)

            if best_match:
                dom_idx, dom_item, text_sim, pos_sim = best_match
                used_dom_indices.add(dom_idx)

                # Calculate boosted confidence
                base_confidence = (ocr_item.confidence + 0.8) / 2  # Assume DOM is 0.8
                boosted = min(1.0, base_confidence + self.config["agreement_boost"])

                matched.append(MatchedItem(
                    ocr_item=ocr_item,
                    dom_item=dom_item,
                    text_similarity=text_sim,
                    position_proximity=pos_sim,
                    combined_confidence=boosted,
                    agreement_type="both"
                ))
            else:
                # OCR-only item (no DOM match)
                capped_confidence = min(
                    ocr_item.confidence,
                    self.config["ocr_only_floor"]
                )
                matched.append(MatchedItem(
                    ocr_item=ocr_item,
                    dom_item=None,
                    text_similarity=0.0,
                    position_proximity=0.0,
                    combined_confidence=capped_confidence,
                    agreement_type="ocr_only"
                ))

        # Add DOM-only items (not matched to any OCR)
        for dom_idx, dom_item in enumerate(dom_items):
            if dom_idx not in used_dom_indices:
                capped_confidence = self.config["dom_only_floor"]
                matched.append(MatchedItem(
                    ocr_item=None,
                    dom_item=dom_item,
                    text_similarity=0.0,
                    position_proximity=0.0,
                    combined_confidence=capped_confidence,
                    agreement_type="dom_only"
                ))

        return matched

    def validate_extraction(
        self,
        extracted_value: str,
        ocr_items: List[OCRTextBlock],
        dom_items: List[DOMElement],
        value_type: str = "generic"
    ) -> ValidationResult:
        """
        Validate a specific extracted value against OCR and DOM sources.

        Args:
            extracted_value: The value to validate (e.g., a price)
            ocr_items: OCR extractions
            dom_items: DOM extractions
            value_type: Type of value ("price", "title", "generic")

        Returns:
            ValidationResult with confidence and source info
        """
        issues = []
        matches = []

        # Check OCR
        ocr_found = False
        ocr_confidence = 0.0
        for item in ocr_items:
            if self._value_in_text(extracted_value, item.text, value_type):
                ocr_found = True
                ocr_confidence = max(ocr_confidence, item.confidence)
                matches.append(f"OCR: '{item.text[:50]}...' (conf: {item.confidence:.2f})")

        # Check DOM
        dom_found = False
        for item in dom_items:
            if self._value_in_text(extracted_value, item.text, value_type):
                dom_found = True
                matches.append(f"DOM: '{item.text[:50]}...'")

        # Determine validation result
        if ocr_found and dom_found:
            # Both agree - high confidence
            confidence = min(1.0, ocr_confidence + self.config["agreement_boost"])
            return ValidationResult(
                is_valid=True,
                confidence=confidence,
                source="both",
                matches=matches
            )
        elif dom_found:
            # DOM only - medium-high confidence
            return ValidationResult(
                is_valid=True,
                confidence=self.config["dom_only_floor"],
                source="dom",
                matches=matches,
                issues=["Not found in OCR"]
            )
        elif ocr_found:
            # OCR only - medium confidence
            return ValidationResult(
                is_valid=True,
                confidence=min(ocr_confidence, self.config["ocr_only_floor"]),
                source="ocr",
                matches=matches,
                issues=["Not found in DOM"]
            )
        else:
            # Not found anywhere
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                source="none",
                issues=["Value not found in OCR or DOM"]
            )

    def cross_validate_page(
        self,
        page_doc: PageDocument
    ) -> CrossValidationReport:
        """
        Cross-validate all items in a PageDocument.

        Returns:
            CrossValidationReport with statistics
        """
        page_width = page_doc.capture_quality.viewport_width or 1920
        page_height = page_doc.capture_quality.viewport_height or 1080

        matched_items = self.find_matches(
            page_doc.ocr_items,
            page_doc.dom_items,
            page_width,
            page_height
        )

        # Update page document with matched items
        page_doc.matched_items = matched_items

        # Calculate statistics
        both_count = sum(1 for m in matched_items if m.agreement_type == "both")
        ocr_only = sum(1 for m in matched_items if m.agreement_type == "ocr_only")
        dom_only = sum(1 for m in matched_items if m.agreement_type == "dom_only")

        avg_confidence = (
            sum(m.combined_confidence for m in matched_items) / len(matched_items)
            if matched_items else 0.0
        )

        total_items = len(page_doc.ocr_items) + len(page_doc.dom_items)
        agreement_rate = (both_count * 2) / total_items if total_items > 0 else 0.0

        issues = []
        if agreement_rate < 0.3:
            issues.append(f"Low agreement rate: {agreement_rate:.1%}")
        if ocr_only > both_count:
            issues.append(f"Many OCR-only items ({ocr_only}) may indicate DOM extraction issues")
        if dom_only > both_count:
            issues.append(f"Many DOM-only items ({dom_only}) may indicate OCR quality issues")

        return CrossValidationReport(
            ocr_item_count=len(page_doc.ocr_items),
            dom_item_count=len(page_doc.dom_items),
            matched_count=both_count,
            unmatched_ocr=ocr_only,
            unmatched_dom=dom_only,
            average_confidence=avg_confidence,
            agreement_rate=agreement_rate,
            issues=issues
        )

    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison"""
        if not text:
            return ""
        # Lowercase, strip whitespace, collapse multiple spaces
        normalized = text.lower().strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized

    def _value_in_text(
        self,
        value: str,
        text: str,
        value_type: str
    ) -> bool:
        """Check if a value appears in text"""
        value_norm = self._normalize_text(value)
        text_norm = self._normalize_text(text)

        if not value_norm or not text_norm:
            return False

        if value_type == "price":
            # For prices, extract numeric part and compare
            value_nums = re.findall(r'[\d,]+\.?\d*', value)
            text_nums = re.findall(r'[\d,]+\.?\d*', text)
            return any(vn in text_nums for vn in value_nums if vn)

        # Default: substring or fuzzy match
        if value_norm in text_norm:
            return True

        # Fuzzy match for longer values
        if len(value_norm) > 10:
            sim = SequenceMatcher(None, value_norm, text_norm).ratio()
            return sim > 0.8

        return False


def validate_product_extraction(
    product: Dict,
    page_doc: PageDocument
) -> Dict:
    """
    Convenience function to validate a product extraction.

    Args:
        product: Dict with name, price, url, etc.
        page_doc: PageDocument with OCR and DOM data

    Returns:
        Product dict with added validation info
    """
    validator = OCRDOMValidator()

    validations = {}

    # Validate price if present
    if product.get("price"):
        price_result = validator.validate_extraction(
            str(product["price"]),
            page_doc.ocr_items,
            page_doc.dom_items,
            value_type="price"
        )
        validations["price_validation"] = {
            "valid": price_result.is_valid,
            "confidence": price_result.confidence,
            "source": price_result.source
        }

    # Validate name if present
    if product.get("name"):
        name_result = validator.validate_extraction(
            product["name"],
            page_doc.ocr_items,
            page_doc.dom_items,
            value_type="generic"
        )
        validations["name_validation"] = {
            "valid": name_result.is_valid,
            "confidence": name_result.confidence,
            "source": name_result.source
        }

    # Calculate overall confidence
    confidence_scores = [
        v["confidence"] for v in validations.values() if v.get("valid")
    ]
    overall_confidence = (
        sum(confidence_scores) / len(confidence_scores)
        if confidence_scores else 0.0
    )

    product["_validation"] = {
        "details": validations,
        "overall_confidence": overall_confidence,
        "grounded": overall_confidence >= 0.5
    }

    return product
