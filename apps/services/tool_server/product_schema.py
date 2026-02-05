"""
orchestrator/product_schema.py

Universal product schema for adaptive search.
Works for any product category - not specific to hamsters or any single item type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime


@dataclass
class ProductSearchIntent:
    """
    Captures what the user wants - interpreted by Coordinator.
    Generalizable to any product category.
    """
    item_type: str  # "live_animal", "electronics", "furniture", "service", "book", etc.
    category: str   # "pet:hamster", "computing:laptop", "home:couch", etc.
    must_have_attributes: List[str] = field(default_factory=list)  # ["alive", "breed:Syrian", "age:<12weeks"]
    must_not_have_attributes: List[str] = field(default_factory=list)  # ["toy", "book", "cage", "accessory"]
    seller_preferences: List[str] = field(default_factory=list)  # ["breeder", "small_shop"] or ["big_retailer"]
    price_range: Optional[Tuple[float, float]] = None
    trusted_sources: List[str] = field(default_factory=list)  # From source discovery
    location: str = "USA"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_type": self.item_type,
            "category": self.category,
            "must_have": self.must_have_attributes,
            "must_not_have": self.must_not_have_attributes,
            "seller_preferences": self.seller_preferences,
            "price_range": list(self.price_range) if self.price_range else None,
            "trusted_sources": self.trusted_sources,
            "location": self.location,
        }


@dataclass
class ProductListing:
    """
    Structured product extraction target.
    Universal schema that adapts to any product type.
    """
    title: str
    url: str
    seller_name: str
    seller_type: str  # "breeder", "retailer", "marketplace", "educational", "unknown"
    price: Optional[float]
    currency: str = "USD"
    item_type: str = "unknown"  # "live_animal", "book", "toy", "cage", "accessory", "service"
    relevance_score: float = 0.0  # 0.0-1.0
    confidence: str = "low"  # "high", "medium", "low"
    extracted_attributes: Dict[str, Any] = field(default_factory=dict)
    rejection_reasons: List[str] = field(default_factory=list)
    availability: str = "unknown"  # "in_stock", "out_of_stock", "preorder", "unknown"
    verified_at: Optional[str] = None
    fetch_method: Optional[str] = None  # Which method successfully fetched
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "seller_name": self.seller_name,
            "seller_type": self.seller_type,
            "price": self.price,
            "currency": self.currency,
            "item_type": self.item_type,
            "relevance_score": self.relevance_score,
            "confidence": self.confidence,
            "extracted_attributes": self.extracted_attributes,
            "rejection_reasons": self.rejection_reasons,
            "availability": self.availability,
            "verified_at": self.verified_at,
            "fetch_method": self.fetch_method,
        }
    
    @property
    def is_accepted(self) -> bool:
        """Check if listing passes filters"""
        return not self.rejection_reasons and self.relevance_score >= 0.7


@dataclass
class SourceRecommendation:
    """
    Trusted source discovered through research.
    """
    domain: str
    source_type: str  # "breeder_registry", "marketplace", "direct_breeder", "retailer", "forum"
    trust_score: float  # 0.0-1.0
    reasons: List[str] = field(default_factory=list)  # Why this source is recommended
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "source_type": self.source_type,
            "trust_score": self.trust_score,
            "reasons": self.reasons,
            "metadata": self.metadata,
        }


@dataclass
class SourceDiscoveryResult:
    """
    Result from source discovery research phase.
    """
    trusted_sources: List[SourceRecommendation] = field(default_factory=list)
    seller_type_guidance: List[str] = field(default_factory=list)
    avoid_signals: List[str] = field(default_factory=list)
    regional_resources: List[Dict[str, str]] = field(default_factory=list)
    search_strategies: List[str] = field(default_factory=list)
    discovered_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trusted_sources": [src.to_dict() for src in self.trusted_sources],
            "seller_type_guidance": self.seller_type_guidance,
            "avoid_signals": self.avoid_signals,
            "regional_resources": self.regional_resources,
            "search_strategies": self.search_strategies,
            "discovered_at": self.discovered_at or datetime.utcnow().isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SourceDiscoveryResult:
        """Create from dictionary"""
        trusted = [
            SourceRecommendation(**src)
            for src in data.get("trusted_sources", [])
        ]
        return cls(
            trusted_sources=trusted,
            seller_type_guidance=data.get("seller_type_guidance", []),
            avoid_signals=data.get("avoid_signals", []),
            regional_resources=data.get("regional_resources", []),
            search_strategies=data.get("search_strategies", []),
            discovered_at=data.get("discovered_at"),
        )


@dataclass
class SearchQuality:
    """
    Quality assessment of search results.
    """
    total_fetched: int
    verified_count: int
    rejected_count: int
    quality_score: float  # 0.0-1.0 (verified / total)
    issues: List[str] = field(default_factory=list)
    suggested_refinement: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_fetched": self.total_fetched,
            "verified_count": self.verified_count,
            "rejected_count": self.rejected_count,
            "quality_score": self.quality_score,
            "issues": self.issues,
            "suggested_refinement": self.suggested_refinement,
        }


# Utility functions for schema inference

def infer_item_type(query: str, context: str = "") -> str:
    """
    Infer item type from query text.
    Returns one of: live_animal, electronics, furniture, book, toy, service, unknown
    """
    combined = (query + " " + context).lower()
    
    # Live animal indicators
    if any(word in combined for word in ["hamster", "dog", "cat", "bird", "fish", "reptile", "pet", "puppy", "kitten", "breeder", "adoption"]):
        return "live_animal"
    
    # Electronics
    if any(word in combined for word in ["laptop", "phone", "computer", "tablet", "tv", "monitor", "camera", "headphones"]):
        return "electronics"
    
    # Furniture
    if any(word in combined for word in ["couch", "sofa", "chair", "table", "desk", "bed", "dresser", "cabinet"]):
        return "furniture"
    
    # Books
    if any(word in combined for word in ["book", "novel", "textbook", "ebook", "paperback", "hardcover", "isbn"]):
        return "book"
    
    # Toys
    if any(word in combined for word in ["toy", "plush", "figurine", "action figure", "doll", "game"]):
        return "toy"
    
    # Services
    if any(word in combined for word in ["service", "repair", "consultation", "subscription", "membership"]):
        return "service"
    
    return "unknown"


def infer_category(query: str, context: str = "") -> str:
    """
    Infer category from query.
    Format: "domain:specific" like "pet:hamster" or "computing:laptop"
    """
    combined = (query + " " + context).lower()
    
    # Pets
    if "hamster" in combined:
        return "pet:hamster"
    elif "dog" in combined or "puppy" in combined:
        return "pet:dog"
    elif "cat" in combined or "kitten" in combined:
        return "pet:cat"
    elif any(word in combined for word in ["bird", "parrot", "parakeet"]):
        return "pet:bird"
    
    # Computing
    if "laptop" in combined:
        return "computing:laptop"
    elif "desktop" in combined or "pc" in combined:
        return "computing:desktop"
    elif "tablet" in combined:
        return "computing:tablet"
    
    # Generic fallback
    item_type = infer_item_type(query, context)
    return f"{item_type}:general"


def extract_price_range(query: str) -> Optional[Tuple[float, float]]:
    """
    Extract price range from query text.
    Examples: "under $50", "$20-$40", "between $30 and $60"
    """
    import re
    
    # Pattern: "under $X" or "less than $X"
    match = re.search(r'(?:under|less than|below)\s*\$?(\d+(?:\.\d+)?)', query, re.IGNORECASE)
    if match:
        max_price = float(match.group(1))
        return (0.0, max_price)
    
    # Pattern: "$X-$Y" or "$X to $Y"
    match = re.search(r'\$?(\d+(?:\.\d+)?)\s*(?:-|to)\s*\$?(\d+(?:\.\d+)?)', query, re.IGNORECASE)
    if match:
        min_price = float(match.group(1))
        max_price = float(match.group(2))
        return (min_price, max_price)
    
    # Pattern: "between $X and $Y"
    match = re.search(r'between\s*\$?(\d+(?:\.\d+)?)\s*and\s*\$?(\d+(?:\.\d+)?)', query, re.IGNORECASE)
    if match:
        min_price = float(match.group(1))
        max_price = float(match.group(2))
        return (min_price, max_price)
    
    return None
