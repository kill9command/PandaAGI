"""
Data models for hybrid vision+HTML product extraction.

These models represent the different stages of product extraction:
- VisualProduct: Product identified by OCR/vision
- HTMLCandidate: Potential product URL from HTML
- FusedProduct: Final product combining both sources
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any
import re


@dataclass
class BoundingBox:
    """Screen coordinates for a visual element."""
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> Tuple[int, int]:
        """Get center point of bounding box."""
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def area(self) -> int:
        """Get area of bounding box."""
        return self.width * self.height

    def contains(self, other: 'BoundingBox') -> bool:
        """Check if this bbox contains another."""
        return (
            self.x <= other.x and
            self.y <= other.y and
            self.x + self.width >= other.x + other.width and
            self.y + self.height >= other.y + other.height
        )

    def overlaps(self, other: 'BoundingBox') -> bool:
        """Check if this bbox overlaps with another."""
        return not (
            self.x + self.width < other.x or
            other.x + other.width < self.x or
            self.y + self.height < other.y or
            other.y + other.height < self.y
        )

    def to_dict(self) -> Dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass
class OCRItem:
    """Single OCR text detection result."""
    text: str
    bbox: BoundingBox
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "confidence": self.confidence
        }


@dataclass
class VisualProduct:
    """Product identified by vision/OCR system."""
    title: str
    price: Optional[str]  # Raw string like "$1,299.99"
    price_numeric: Optional[float]  # Parsed: 1299.99
    bbox: BoundingBox  # Where on screen (first OCR item's bbox)
    confidence: float  # Overall confidence
    raw_ocr_lines: List[str] = field(default_factory=list)
    ocr_items: List[OCRItem] = field(default_factory=list)

    @staticmethod
    def parse_price(price_str: str) -> Optional[float]:
        """Parse price string to numeric value."""
        if not price_str:
            return None
        # Remove currency symbols and commas
        cleaned = re.sub(r'[^\d.]', '', price_str)
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "price": self.price,
            "price_numeric": self.price_numeric,
            "bbox": self.bbox.to_dict(),
            "confidence": self.confidence,
            "raw_ocr_lines": self.raw_ocr_lines
        }


@dataclass
class HTMLCandidate:
    """Potential product URL extracted from HTML."""
    url: str
    link_text: str
    context_text: str  # Surrounding text for matching
    source: str  # "json_ld" | "url_pattern" | "dom_heuristic"
    confidence: float = 0.8  # Base confidence for HTML extraction

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "link_text": self.link_text,
            "context_text": self.context_text[:100] if self.context_text else "",
            "source": self.source,
            "confidence": self.confidence
        }


@dataclass
class PDPData:
    """
    Verified product data extracted from Product Detail Page.

    This is the authoritative data - more accurate than SERP extraction.
    """
    # Core verified data
    price: Optional[float] = None           # Verified price from PDP
    title: Optional[str] = None             # Full product title
    original_price: Optional[float] = None  # Strikethrough price (if on sale)

    # Availability
    in_stock: bool = True
    stock_status: str = "unknown"           # "in_stock", "out_of_stock", "low_stock", "preorder"

    # Product details
    condition: str = "new"                  # "new", "refurbished", "used", "open_box"
    rating: Optional[float] = None          # Star rating (1.0-5.0)
    review_count: Optional[int] = None      # Number of reviews

    # Specs (key product attributes)
    specs: Dict[str, str] = field(default_factory=dict)

    # Seller info (for marketplaces)
    seller_name: Optional[str] = None       # "Sold by X"
    ships_from: Optional[str] = None        # "Ships from Y"

    # Shipping
    shipping_price: Optional[float] = None  # Shipping cost (None = unknown, 0 = free)
    delivery_estimate: Optional[str] = None # "Arrives by Dec 1"

    # Media
    image_url: Optional[str] = None         # Primary product image

    # Extraction metadata
    extraction_source: str = ""             # "json_ld", "html_selector", "vision"
    extraction_confidence: float = 0.0      # How confident we are in the extraction

    def to_dict(self) -> Dict[str, Any]:
        return {
            "price": self.price,
            "title": self.title,
            "original_price": self.original_price,
            "in_stock": self.in_stock,
            "stock_status": self.stock_status,
            "condition": self.condition,
            "rating": self.rating,
            "review_count": self.review_count,
            "specs": self.specs,
            "seller_name": self.seller_name,
            "ships_from": self.ships_from,
            "shipping_price": self.shipping_price,
            "delivery_estimate": self.delivery_estimate,
            "image_url": self.image_url,
            "extraction_source": self.extraction_source,
            "extraction_confidence": self.extraction_confidence,
        }


@dataclass
class FusedProduct:
    """Final product combining vision + HTML data."""
    # Core data
    title: str                    # From vision (human-readable)
    price: Optional[float]        # From vision (what user sees)
    price_str: str                # Original price string
    url: str                      # From HTML or click-resolved
    vendor: str                   # Retailer domain

    # Confidence & provenance
    confidence: float             # Combined confidence score
    extraction_method: str        # "fusion" | "html_only" | "vision_only" | "click_resolved"
    vision_verified: bool         # True if vision confirmed the product
    url_source: str               # "json_ld" | "pattern_match" | "click_resolved" | "fallback"

    # Optional metadata
    description: str = ""
    bbox: Optional[BoundingBox] = None  # For debugging/click-resolve
    match_score: float = 0.0      # Fusion match score

    # PDP Verification data (NEW)
    pdp_verified: bool = False                    # True if PDP verification ran successfully
    pdp_data: Optional[PDPData] = None            # Full PDP extraction data
    verified_price: Optional[float] = None        # Price from PDP (authoritative)
    verified_title: Optional[str] = None          # Full title from PDP
    original_price: Optional[float] = None        # Strikethrough price (if on sale)
    in_stock: bool = True                         # Stock status from PDP
    stock_status: str = "unknown"                 # Detailed stock status
    condition: str = "new"                        # Product condition
    rating: Optional[float] = None                # Star rating
    review_count: Optional[int] = None            # Number of reviews
    specs: Dict[str, str] = field(default_factory=dict)  # Key specs
    price_discrepancy: Optional[float] = None     # SERP price - PDP price (for monitoring)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "title": self.title,
            "price": self.price,
            "price_str": self.price_str,
            "url": self.url,
            "vendor": self.vendor,
            "confidence": self.confidence,
            "extraction_method": self.extraction_method,
            "vision_verified": self.vision_verified,
            "url_source": self.url_source,
            "description": self.description,
            "bbox": self.bbox.to_dict() if self.bbox else None,
            "match_score": self.match_score,
            # PDP verification fields
            "pdp_verified": self.pdp_verified,
            "verified_price": self.verified_price,
            "verified_title": self.verified_title,
            "original_price": self.original_price,
            "in_stock": self.in_stock,
            "stock_status": self.stock_status,
            "condition": self.condition,
            "rating": self.rating,
            "review_count": self.review_count,
            "specs": self.specs,
            "price_discrepancy": self.price_discrepancy,
        }
        if self.pdp_data:
            result["pdp_data"] = self.pdp_data.to_dict()
        return result

    def get_best_price(self) -> Optional[float]:
        """Get the most accurate price (verified if available, otherwise SERP)."""
        return self.verified_price if self.verified_price is not None else self.price

    def get_best_title(self) -> str:
        """Get the most accurate title (verified if available, otherwise SERP)."""
        return self.verified_title if self.verified_title else self.title

    def to_product_claim(self) -> 'ProductClaim':
        """Convert to existing ProductClaim format for compatibility."""
        from apps.services.tool_server.product_claim_schema import ProductClaim
        return ProductClaim(
            title=self.get_best_title(),
            price=self.get_best_price(),
            currency="USD",
            url=self.url,
            seller_name=self.vendor,
            seller_type="retailer",
            in_stock=self.in_stock,
            description=self.description,
            confidence=self.confidence,
            source_url=self.url,
        )


@dataclass
class ExtractionResult:
    """Complete result from product perception pipeline."""
    products: List[FusedProduct]
    html_candidates_count: int
    vision_products_count: int
    fusion_matches: int
    click_resolved: int
    extraction_time_ms: float
    errors: List[str] = field(default_factory=list)
    pdp_verified: int = 0  # Number of products with PDP verification
    price_discrepancies: int = 0  # Number of products where SERP != PDP price

    def to_dict(self) -> Dict[str, Any]:
        return {
            "products": [p.to_dict() for p in self.products],
            "html_candidates_count": self.html_candidates_count,
            "vision_products_count": self.vision_products_count,
            "fusion_matches": self.fusion_matches,
            "click_resolved": self.click_resolved,
            "pdp_verified": self.pdp_verified,
            "price_discrepancies": self.price_discrepancies,
            "extraction_time_ms": self.extraction_time_ms,
            "errors": self.errors
        }
