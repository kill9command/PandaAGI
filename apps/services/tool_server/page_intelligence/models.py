"""
orchestrator/page_intelligence/models.py

Data models for the Page Intelligence System.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional
import json


class ZoneType(str, Enum):
    """Semantic zone types on a webpage."""
    # Universal zones
    HEADER = "header"
    NAVIGATION = "navigation"
    FOOTER = "footer"
    ADS = "ads"
    PAGINATION = "pagination"
    CONTENT_PROSE = "content_prose"

    # Search engine zones
    INSTANT_ANSWER = "instant_answer"  # AI/instant answers at top (DuckDuckGo ZCI, Google snippets)
    ORGANIC_RESULTS = "organic_results"  # Actual search results (NOT instant answers)

    # Commerce zones
    SEARCH_FILTERS = "search_filters"
    PRODUCT_GRID = "product_grid"
    PRODUCT_DETAILS = "product_details"

    # Forum/Discussion zones
    THREAD_LIST = "thread_list"
    POPULAR_TOPICS = "popular_topics"
    DISCUSSION_CONTENT = "discussion_content"
    POST_LIST = "post_list"
    COMMENTS = "comments"
    USER_INFO = "user_info"

    # News/Article zones
    ARTICLE_LIST = "article_list"
    ARTICLE_CONTENT = "article_content"
    NEWS_FEED = "news_feed"

    # Wiki zones
    WIKI_CONTENT = "wiki_content"
    TABLE_OF_CONTENTS = "table_of_contents"

    # Generic list zones (universal fallback for any list content)
    LIST_CONTENT = "list_content"
    ITEM_GRID = "item_grid"

    UNKNOWN = "unknown"


class PageType(str, Enum):
    """Overall page classification."""
    # Commerce pages
    SEARCH_RESULTS = "search_results"
    PRODUCT_DETAIL = "product_detail"
    CATEGORY = "category"

    # General pages
    HOMEPAGE = "homepage"
    ARTICLE = "article"

    # Forum/Discussion pages
    FORUM_INDEX = "forum_index"
    FORUM_THREAD = "forum_thread"
    DISCUSSION_BOARD = "discussion_board"

    # News pages
    NEWS_INDEX = "news_index"
    NEWS_ARTICLE = "news_article"
    BLOG_INDEX = "blog_index"

    # Wiki pages
    WIKI_PAGE = "wiki_page"
    WIKI_INDEX = "wiki_index"

    # Generic fallback
    LIST_PAGE = "list_page"
    OTHER = "other"


class StrategyMethod(str, Enum):
    """Extraction strategy methods."""
    SELECTOR_EXTRACTION = "selector_extraction"
    VISION_EXTRACTION = "vision_extraction"
    HYBRID_EXTRACTION = "hybrid_extraction"
    PROSE_EXTRACTION = "prose_extraction"


@dataclass
class Bounds:
    """Bounding box for a zone or element."""
    top: float = 0
    left: float = 0
    width: float = 0
    height: float = 0

    def to_dict(self) -> Dict[str, float]:
        """Return bounds with computed bottom/right for JS compatibility."""
        return {
            "top": self.top,
            "left": self.left,
            "width": self.width,
            "height": self.height,
            "bottom": self.top + self.height,
            "right": self.left + self.width
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Bounds':
        return cls(
            top=data.get("top", 0),
            left=data.get("left", 0),
            width=data.get("width", 0),
            height=data.get("height", 0)
        )

    def contains_point(self, x: float, y: float) -> bool:
        """Check if a point is within bounds."""
        return (
            self.left <= x <= self.left + self.width and
            self.top <= y <= self.top + self.height
        )

    def overlaps(self, other: 'Bounds') -> bool:
        """Check if two bounds overlap."""
        return not (
            self.left + self.width < other.left or
            other.left + other.width < self.left or
            self.top + self.height < other.top or
            other.top + other.height < self.top
        )

    def overlap_ratio(self, other: 'Bounds') -> float:
        """Calculate overlap ratio (0-1) between two bounds."""
        if not self.overlaps(other):
            return 0.0

        # Calculate intersection
        x1 = max(self.left, other.left)
        y1 = max(self.top, other.top)
        x2 = min(self.left + self.width, other.left + other.width)
        y2 = min(self.top + self.height, other.top + other.height)

        intersection = (x2 - x1) * (y2 - y1)
        smaller_area = min(
            self.width * self.height,
            other.width * other.height
        )

        return intersection / smaller_area if smaller_area > 0 else 0.0


@dataclass
class Zone:
    """A semantic zone identified on the page."""
    zone_type: ZoneType
    confidence: float
    dom_anchors: List[str] = field(default_factory=list)
    bounds: Optional[Bounds] = None
    item_count_estimate: int = 0
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone_type": self.zone_type.value if isinstance(self.zone_type, ZoneType) else self.zone_type,
            "confidence": self.confidence,
            "dom_anchors": self.dom_anchors,
            "bounds": self.bounds.to_dict() if self.bounds else None,
            "item_count_estimate": self.item_count_estimate,
            "notes": self.notes
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Zone':
        zone_type = data.get("zone_type", "unknown")
        if isinstance(zone_type, str):
            try:
                zone_type = ZoneType(zone_type)
            except ValueError:
                zone_type = ZoneType.UNKNOWN

        bounds = None
        if data.get("bounds"):
            bounds = Bounds.from_dict(data["bounds"])

        return cls(
            zone_type=zone_type,
            confidence=data.get("confidence", 0.5),
            dom_anchors=data.get("dom_anchors", []),
            bounds=bounds,
            item_count_estimate=data.get("item_count_estimate", 0),
            notes=data.get("notes", "")
        )


@dataclass
class FieldSelector:
    """CSS selector for extracting a field from an item."""
    selector: str
    attribute: str = "textContent"
    transform: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"selector": self.selector, "attribute": self.attribute}
        if self.transform:
            d["transform"] = self.transform
        return d

    @classmethod
    def from_dict(cls, data: Dict) -> 'FieldSelector':
        return cls(
            selector=data.get("selector", ""),
            attribute=data.get("attribute", "textContent"),
            transform=data.get("transform")
        )


@dataclass
class ZoneSelectors:
    """CSS selectors for extracting data from a zone."""
    item_selector: str
    fields: Dict[str, FieldSelector] = field(default_factory=dict)
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_selector": self.item_selector,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "confidence": self.confidence
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ZoneSelectors':
        fields = {}
        for k, v in data.get("fields", {}).items():
            fields[k] = FieldSelector.from_dict(v) if isinstance(v, dict) else v

        return cls(
            item_selector=data.get("item_selector", ""),
            fields=fields,
            confidence=data.get("confidence", 0.5)
        )


@dataclass
class ExtractionStrategy:
    """Extraction strategy for a zone."""
    zone: str
    method: StrategyMethod
    confidence: float
    fallback: Optional[StrategyMethod] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "zone": self.zone,
            "method": self.method.value if isinstance(self.method, StrategyMethod) else self.method,
            "confidence": self.confidence,
            "reason": self.reason
        }
        if self.fallback:
            d["fallback"] = self.fallback.value if isinstance(self.fallback, StrategyMethod) else self.fallback
        return d

    @classmethod
    def from_dict(cls, data: Dict) -> 'ExtractionStrategy':
        method = data.get("method", "selector_extraction")
        if isinstance(method, str):
            try:
                method = StrategyMethod(method)
            except ValueError:
                method = StrategyMethod.SELECTOR_EXTRACTION

        fallback = data.get("fallback")
        if fallback and isinstance(fallback, str):
            try:
                fallback = StrategyMethod(fallback)
            except ValueError:
                fallback = None

        return cls(
            zone=data.get("zone", ""),
            method=method,
            confidence=data.get("confidence", 0.5),
            fallback=fallback,
            reason=data.get("reason", "")
        )


@dataclass
class OCRTextBlock:
    """Text block detected by OCR with position."""
    text: str
    bounds: Bounds
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "bounds": self.bounds.to_dict(),
            "confidence": self.confidence
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'OCRTextBlock':
        return cls(
            text=data.get("text", ""),
            bounds=Bounds.from_dict(data.get("bounds", {})),
            confidence=data.get("confidence", 1.0)
        )


@dataclass
class DOMElement:
    """DOM element with position for OCR cross-reference."""
    selector: str
    tag: str
    text: str
    bounds: Bounds
    attributes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selector": self.selector,
            "tag": self.tag,
            "text": self.text,
            "bounds": self.bounds.to_dict(),
            "attributes": self.attributes
        }


class AvailabilityStatus(str, Enum):
    """Availability status for products on a page."""
    AVAILABLE_ONLINE = "available_online"
    IN_STORE_ONLY = "in_store_only"
    OUT_OF_STOCK = "out_of_stock"
    LIMITED_AVAILABILITY = "limited_availability"
    PRE_ORDER = "pre_order"
    COMING_SOON = "coming_soon"
    UNKNOWN = "unknown"


@dataclass
class PageNotice:
    """An important notice or restriction found on a page."""
    notice_type: str  # "availability", "shipping", "restriction", "info", "warning"
    message: str  # The actual notice text
    applies_to: str = "page"  # "page", "products", "category"
    confidence: float = 0.8

    def to_dict(self) -> Dict[str, Any]:
        return {
            "notice_type": self.notice_type,
            "message": self.message,
            "applies_to": self.applies_to,
            "confidence": self.confidence
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'PageNotice':
        return cls(
            notice_type=data.get("notice_type", "info"),
            message=data.get("message", ""),
            applies_to=data.get("applies_to", "page"),
            confidence=data.get("confidence", 0.8)
        )


@dataclass
class PageUnderstanding:
    """Complete understanding of a page from all 3 phases."""
    url: str
    domain: str
    page_type: PageType
    zones: List[Zone] = field(default_factory=list)
    selectors: Dict[str, ZoneSelectors] = field(default_factory=dict)
    strategies: List[ExtractionStrategy] = field(default_factory=list)
    primary_zone: Optional[str] = None
    skip_zones: List[str] = field(default_factory=list)
    has_products: bool = False
    has_list_content: bool = False  # True if page has list-based content (topics, threads, articles)
    created_at: datetime = field(default_factory=datetime.utcnow)
    cache_fingerprint: str = ""
    notes: str = ""

    # Page-level intelligence (notices, availability, constraints)
    page_notices: List[PageNotice] = field(default_factory=list)
    availability_status: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    purchase_constraints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "domain": self.domain,
            "page_type": self.page_type.value if isinstance(self.page_type, PageType) else self.page_type,
            "zones": [z.to_dict() for z in self.zones],
            "selectors": {k: v.to_dict() for k, v in self.selectors.items()},
            "strategies": [s.to_dict() for s in self.strategies],
            "primary_zone": self.primary_zone,
            "skip_zones": self.skip_zones,
            "has_products": self.has_products,
            "has_list_content": self.has_list_content,
            "created_at": self.created_at.isoformat(),
            "cache_fingerprint": self.cache_fingerprint,
            "notes": self.notes,
            # Page-level intelligence
            "page_notices": [n.to_dict() for n in self.page_notices],
            "availability_status": self.availability_status.value if isinstance(self.availability_status, AvailabilityStatus) else self.availability_status,
            "purchase_constraints": self.purchase_constraints
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict) -> 'PageUnderstanding':
        page_type = data.get("page_type", "other")
        if isinstance(page_type, str):
            try:
                page_type = PageType(page_type)
            except ValueError:
                page_type = PageType.OTHER

        zones = [Zone.from_dict(z) for z in data.get("zones", [])]
        selectors = {k: ZoneSelectors.from_dict(v) for k, v in data.get("selectors", {}).items()}
        strategies = [ExtractionStrategy.from_dict(s) for s in data.get("strategies", [])]

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except ValueError:
                created_at = datetime.utcnow()
        elif not created_at:
            created_at = datetime.utcnow()

        # Parse page notices
        page_notices = [PageNotice.from_dict(n) for n in data.get("page_notices", [])]

        # Parse availability status
        availability_status = data.get("availability_status", "unknown")
        if isinstance(availability_status, str):
            try:
                availability_status = AvailabilityStatus(availability_status)
            except ValueError:
                availability_status = AvailabilityStatus.UNKNOWN

        return cls(
            url=data.get("url", ""),
            domain=data.get("domain", ""),
            page_type=page_type,
            zones=zones,
            selectors=selectors,
            strategies=strategies,
            primary_zone=data.get("primary_zone"),
            skip_zones=data.get("skip_zones", []),
            has_products=data.get("has_products", False),
            has_list_content=data.get("has_list_content", False),
            created_at=created_at,
            cache_fingerprint=data.get("cache_fingerprint", ""),
            notes=data.get("notes", ""),
            page_notices=page_notices,
            availability_status=availability_status,
            purchase_constraints=data.get("purchase_constraints", [])
        )

    def get_strategy_for_zone(self, zone_type: str) -> Optional[ExtractionStrategy]:
        """Get extraction strategy for a specific zone."""
        for strategy in self.strategies:
            if strategy.zone == zone_type:
                return strategy
        return None

    def get_selectors_for_zone(self, zone_type: str) -> Optional[ZoneSelectors]:
        """Get CSS selectors for a specific zone."""
        return self.selectors.get(zone_type)

    def get_zone(self, zone_type: str) -> Optional[Zone]:
        """Get zone by type."""
        for zone in self.zones:
            zone_type_val = zone.zone_type.value if isinstance(zone.zone_type, ZoneType) else zone.zone_type
            if zone_type_val == zone_type:
                return zone
        return None

    def has_availability_restriction(self) -> bool:
        """Check if page has any availability restrictions (in-store only, out of stock, etc.)."""
        if self.availability_status not in (AvailabilityStatus.AVAILABLE_ONLINE, AvailabilityStatus.UNKNOWN):
            return True
        # Check for restriction notices
        for notice in self.page_notices:
            if notice.notice_type in ("availability", "restriction", "shipping"):
                return True
        return False

    def get_availability_summary(self) -> str:
        """Get a human-readable summary of availability status and restrictions."""
        parts = []

        # Add availability status
        if self.availability_status == AvailabilityStatus.IN_STORE_ONLY:
            parts.append("Available in stores only")
        elif self.availability_status == AvailabilityStatus.OUT_OF_STOCK:
            parts.append("Currently out of stock")
        elif self.availability_status == AvailabilityStatus.LIMITED_AVAILABILITY:
            parts.append("Limited availability")
        elif self.availability_status == AvailabilityStatus.PRE_ORDER:
            parts.append("Available for pre-order")
        elif self.availability_status == AvailabilityStatus.COMING_SOON:
            parts.append("Coming soon")

        # Add relevant notices
        for notice in self.page_notices:
            if notice.notice_type in ("availability", "restriction", "shipping"):
                parts.append(notice.message)

        # Add purchase constraints
        for constraint in self.purchase_constraints:
            parts.append(constraint)

        return "; ".join(parts) if parts else ""

    def get_notices_by_type(self, notice_type: str) -> List[PageNotice]:
        """Get all notices of a specific type."""
        return [n for n in self.page_notices if n.notice_type == notice_type]


# === Tier 6: PageDocument for OCR-DOM Integration ===

@dataclass
class CaptureQuality:
    """Quality metrics for page capture.

    ARCHITECTURAL DECISION (2025-12-30):
    Added to track capture reliability for confidence calibration.
    """
    screenshot_captured: bool = False
    screenshot_size_kb: int = 0
    dom_element_count: int = 0
    ocr_text_count: int = 0
    ocr_confidence_avg: float = 0.0
    dom_ocr_overlap_ratio: float = 0.0  # How much OCR matches DOM
    capture_duration_ms: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def is_high_quality(self) -> bool:
        """Check if capture is high quality (good for extraction)."""
        return (
            self.screenshot_captured and
            self.dom_element_count > 10 and
            self.ocr_confidence_avg > 0.7 and
            self.dom_ocr_overlap_ratio > 0.5
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "screenshot_captured": self.screenshot_captured,
            "screenshot_size_kb": self.screenshot_size_kb,
            "dom_element_count": self.dom_element_count,
            "ocr_text_count": self.ocr_text_count,
            "ocr_confidence_avg": self.ocr_confidence_avg,
            "dom_ocr_overlap_ratio": self.dom_ocr_overlap_ratio,
            "capture_duration_ms": self.capture_duration_ms,
            "notes": self.notes,
            "is_high_quality": self.is_high_quality
        }


@dataclass
class MatchedItem:
    """OCR text block matched to a DOM element.

    ARCHITECTURAL DECISION (2025-12-30):
    Created for OCR-DOM cross-validation in Tier 6.
    """
    ocr_block: OCRTextBlock
    dom_element: Optional[DOMElement] = None
    zone_type: Optional[str] = None
    match_confidence: float = 0.0
    validated: bool = False  # True if OCR and DOM agree

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ocr_text": self.ocr_block.text,
            "ocr_bounds": self.ocr_block.bounds.to_dict(),
            "ocr_confidence": self.ocr_block.confidence,
            "dom_selector": self.dom_element.selector if self.dom_element else None,
            "dom_text": self.dom_element.text if self.dom_element else None,
            "zone_type": self.zone_type,
            "match_confidence": self.match_confidence,
            "validated": self.validated
        }


@dataclass
class PageDocument:
    """
    Complete page capture with OCR-DOM cross-reference.

    ARCHITECTURAL DECISION (2025-12-30):
    This is the unified data structure for page intelligence.
    It contains:
    - URL and screenshot path for reference
    - OCR items with bounding boxes
    - DOM items with bounding boxes
    - Matched items (OCR cross-referenced with DOM)
    - Capture quality metrics

    Used by:
    - Planner: to understand what's on the page
    - Validator: to verify extracted claims
    - Research Orchestrator: to extract products/content
    """
    url: str
    screenshot_path: str = ""
    ocr_items: List[OCRTextBlock] = field(default_factory=list)
    dom_items: List[DOMElement] = field(default_factory=list)
    matched_items: List[MatchedItem] = field(default_factory=list)
    capture_quality: CaptureQuality = field(default_factory=CaptureQuality)
    page_understanding: Optional[PageUnderstanding] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "screenshot_path": self.screenshot_path,
            "ocr_items": [item.to_dict() for item in self.ocr_items],
            "dom_items": [item.to_dict() for item in self.dom_items],
            "matched_items": [item.to_dict() for item in self.matched_items],
            "capture_quality": self.capture_quality.to_dict(),
            "page_understanding": self.page_understanding.to_dict() if self.page_understanding else None,
            "created_at": self.created_at.isoformat()
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def get_text_in_zone(self, zone_type: str) -> List[str]:
        """Get all text in a specific zone."""
        return [
            item.ocr_block.text
            for item in self.matched_items
            if item.zone_type == zone_type
        ]

    def get_validated_items(self) -> List[MatchedItem]:
        """Get items where OCR and DOM agree."""
        return [item for item in self.matched_items if item.validated]

    def get_unmatched_ocr(self) -> List[OCRTextBlock]:
        """Get OCR blocks that couldn't be matched to DOM."""
        matched_texts = {item.ocr_block.text for item in self.matched_items}
        return [item for item in self.ocr_items if item.text not in matched_texts]

    @property
    def match_rate(self) -> float:
        """Ratio of OCR items matched to DOM."""
        if not self.ocr_items:
            return 0.0
        return len(self.matched_items) / len(self.ocr_items)

    @property
    def validation_rate(self) -> float:
        """Ratio of matched items that are validated."""
        if not self.matched_items:
            return 0.0
        validated = sum(1 for item in self.matched_items if item.validated)
        return validated / len(self.matched_items)
