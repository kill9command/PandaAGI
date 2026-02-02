"""
Zone Detector for Page Intelligence

Percentage-based position analysis with keyword validation.
Identifies page zones (header, navigation, content, sidebar, footer)
based on element positions and content analysis.

Architecture reference: panda_system_docs/architecture/mcp-tool-patterns/
                       internet-research-mcp/unified-page-intelligence.md
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set
from enum import Enum
import re


class PageZone(Enum):
    """Page zone classifications"""
    HEADER = "header"
    NAVIGATION = "navigation"
    MAIN_CONTENT = "main_content"
    SIDEBAR = "sidebar"
    FOOTER = "footer"
    UNKNOWN = "unknown"


# Zone boundary thresholds (percentage of page height/width)
ZONE_THRESHOLDS = {
    "header_max_y": 0.15,      # Top 15% is likely header
    "footer_min_y": 0.85,      # Bottom 15% is likely footer
    "sidebar_max_width": 0.25, # Narrow columns < 25% width
    "sidebar_left_max_x": 0.25,
    "sidebar_right_min_x": 0.75,
}

# Keywords that hint at zone type
ZONE_KEYWORDS = {
    PageZone.HEADER: {
        "logo", "search", "sign in", "log in", "login", "cart", "menu",
        "account", "register", "subscribe"
    },
    PageZone.NAVIGATION: {
        "home", "about", "contact", "products", "services", "categories",
        "shop", "browse", "departments", "menu", "nav"
    },
    PageZone.FOOTER: {
        "copyright", "©", "privacy", "terms", "policy", "contact us",
        "follow us", "social", "newsletter", "sitemap", "legal",
        "all rights reserved"
    },
    PageZone.SIDEBAR: {
        "filter", "sort", "refine", "categories", "price range",
        "brand", "related", "popular", "trending", "ads", "sponsored"
    },
    PageZone.MAIN_CONTENT: {
        "add to cart", "buy now", "price", "description", "details",
        "specifications", "reviews", "rating", "in stock", "availability"
    },
}


@dataclass
class ZoneClassification:
    """Classification result for an element"""
    zone: PageZone
    confidence: float  # 0.0 to 1.0
    reasons: List[str] = field(default_factory=list)


@dataclass
class PageZoneMap:
    """Map of detected zones on a page"""
    page_width: int
    page_height: int
    zones: Dict[PageZone, List[Tuple[int, int, int, int]]] = field(default_factory=dict)
    # Each zone maps to list of bounding boxes (x, y, width, height)

    def get_dominant_zone_at(self, x: int, y: int) -> PageZone:
        """Get the zone at a specific coordinate"""
        for zone, bboxes in self.zones.items():
            for bx, by, bw, bh in bboxes:
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    return zone
        return PageZone.UNKNOWN


class ZoneDetector:
    """
    Detects page zones using percentage-based position analysis
    combined with keyword validation.
    """

    def __init__(
        self,
        thresholds: Optional[Dict[str, float]] = None,
        keywords: Optional[Dict[PageZone, Set[str]]] = None
    ):
        self.thresholds = thresholds or ZONE_THRESHOLDS
        self.keywords = keywords or ZONE_KEYWORDS

    def classify_element(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        text: str,
        page_width: int,
        page_height: int
    ) -> ZoneClassification:
        """
        Classify a single element into a page zone.

        Args:
            x, y: Element position (top-left)
            width, height: Element dimensions
            text: Text content of element
            page_width, page_height: Total page dimensions

        Returns:
            ZoneClassification with zone, confidence, and reasons
        """
        reasons = []
        zone_scores: Dict[PageZone, float] = {z: 0.0 for z in PageZone}

        # Calculate relative positions
        rel_y = y / page_height if page_height > 0 else 0
        rel_x = x / page_width if page_width > 0 else 0
        rel_width = width / page_width if page_width > 0 else 0
        rel_height = height / page_height if page_height > 0 else 0
        center_x = (x + width / 2) / page_width if page_width > 0 else 0.5

        # Position-based scoring
        position_score = self._score_by_position(
            rel_x, rel_y, rel_width, rel_height, center_x, reasons
        )
        for zone, score in position_score.items():
            zone_scores[zone] += score * 0.6  # Position weight: 60%

        # Keyword-based scoring
        keyword_score = self._score_by_keywords(text.lower(), reasons)
        for zone, score in keyword_score.items():
            zone_scores[zone] += score * 0.4  # Keyword weight: 40%

        # Find best zone
        best_zone = max(zone_scores, key=lambda z: zone_scores[z])
        best_score = zone_scores[best_zone]

        # If no strong signal, default to main content or unknown
        if best_score < 0.2:
            best_zone = PageZone.MAIN_CONTENT if 0.2 < rel_y < 0.8 else PageZone.UNKNOWN
            best_score = 0.3
            reasons.append("weak signal, defaulting based on position")

        return ZoneClassification(
            zone=best_zone,
            confidence=min(1.0, best_score),
            reasons=reasons
        )

    def _score_by_position(
        self,
        rel_x: float,
        rel_y: float,
        rel_width: float,
        rel_height: float,
        center_x: float,
        reasons: List[str]
    ) -> Dict[PageZone, float]:
        """Score zones based on element position"""
        scores: Dict[PageZone, float] = {z: 0.0 for z in PageZone}

        # Header detection (top of page)
        if rel_y < self.thresholds["header_max_y"]:
            scores[PageZone.HEADER] = 0.7
            reasons.append(f"top {int(rel_y * 100)}% of page (header zone)")

            # Could also be navigation if narrow
            if rel_height < 0.05:
                scores[PageZone.NAVIGATION] = 0.5

        # Footer detection (bottom of page)
        if rel_y > self.thresholds["footer_min_y"]:
            scores[PageZone.FOOTER] = 0.8
            reasons.append(f"bottom {int((1 - rel_y) * 100)}% of page (footer zone)")

        # Sidebar detection (narrow columns on sides)
        if rel_width < self.thresholds["sidebar_max_width"]:
            if rel_x < self.thresholds["sidebar_left_max_x"]:
                scores[PageZone.SIDEBAR] = 0.6
                reasons.append("narrow left column (sidebar)")
            elif rel_x > self.thresholds["sidebar_right_min_x"]:
                scores[PageZone.SIDEBAR] = 0.6
                reasons.append("narrow right column (sidebar)")

        # Main content detection (centered, middle of page)
        if 0.2 < rel_y < 0.85 and 0.2 < center_x < 0.8:
            if rel_width > 0.4:  # Wide element
                scores[PageZone.MAIN_CONTENT] = 0.5
                reasons.append("centered wide element in middle of page")

        return scores

    def _score_by_keywords(
        self,
        text: str,
        reasons: List[str]
    ) -> Dict[PageZone, float]:
        """Score zones based on keyword matches"""
        scores: Dict[PageZone, float] = {z: 0.0 for z in PageZone}
        text_lower = text.lower()

        for zone, keywords in self.keywords.items():
            matches = []
            for keyword in keywords:
                if keyword in text_lower:
                    matches.append(keyword)

            if matches:
                # More matches = higher confidence
                score = min(0.8, 0.3 * len(matches))
                scores[zone] = score
                reasons.append(f"keywords [{', '.join(matches[:3])}] suggest {zone.value}")

        return scores

    def build_zone_map(
        self,
        elements: List[Dict],
        page_width: int,
        page_height: int
    ) -> PageZoneMap:
        """
        Build a complete zone map from a list of elements.

        Args:
            elements: List of dicts with keys: x, y, width, height, text
            page_width, page_height: Total page dimensions

        Returns:
            PageZoneMap with detected zones and their bounding boxes
        """
        zone_map = PageZoneMap(
            page_width=page_width,
            page_height=page_height,
            zones={z: [] for z in PageZone}
        )

        for elem in elements:
            x = elem.get("x", 0)
            y = elem.get("y", 0)
            width = elem.get("width", 0)
            height = elem.get("height", 0)
            text = elem.get("text", "")

            classification = self.classify_element(
                x, y, width, height, text, page_width, page_height
            )

            if classification.confidence >= 0.3:
                zone_map.zones[classification.zone].append((x, y, width, height))

        return zone_map

    def is_likely_product_zone(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        text: str,
        page_width: int,
        page_height: int
    ) -> Tuple[bool, float]:
        """
        Check if an element is likely in a product/content zone.
        Useful for filtering out header/footer/sidebar noise.

        Returns:
            (is_product_zone, confidence)
        """
        classification = self.classify_element(
            x, y, width, height, text, page_width, page_height
        )

        product_zones = {PageZone.MAIN_CONTENT, PageZone.UNKNOWN}
        is_product = classification.zone in product_zones

        return (is_product, classification.confidence if is_product else 1 - classification.confidence)

    def filter_product_elements(
        self,
        elements: List[Dict],
        page_width: int,
        page_height: int,
        min_confidence: float = 0.4
    ) -> List[Dict]:
        """
        Filter elements to keep only those likely in product/content zones.

        Args:
            elements: List of element dicts
            page_width, page_height: Page dimensions
            min_confidence: Minimum confidence threshold

        Returns:
            Filtered list of elements
        """
        filtered = []

        for elem in elements:
            x = elem.get("x", 0)
            y = elem.get("y", 0)
            width = elem.get("width", 0)
            height = elem.get("height", 0)
            text = elem.get("text", "")

            is_product, confidence = self.is_likely_product_zone(
                x, y, width, height, text, page_width, page_height
            )

            if is_product and confidence >= min_confidence:
                elem["zone_confidence"] = confidence
                filtered.append(elem)

        return filtered
