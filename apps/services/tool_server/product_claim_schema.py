"""
orchestrator/product_claim_schema.py

Product claim schema for evidence-based shopping results.

Products are extracted from web pages and stored as claims with:
- Structured data (price, availability, seller)
- Provenance (source URL, extraction timestamp)
- TTL (products expire after 24-48 hours)
- Confidence scoring (extraction quality)
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class ProductClaim:
    """
    Structured product claim extracted from a web page.

    This represents a product listing that was found and verified.
    Products have short TTL (24-48h) since inventory changes quickly.
    """
    # Core product info
    title: str
    price: Optional[float]
    currency: str = "USD"
    url: str = ""

    # Seller info
    seller_name: str = "Unknown"
    seller_type: str = "unknown"  # breeder, pet_store, marketplace, individual

    # Availability
    in_stock: bool = True
    stock_quantity: Optional[int] = None

    # Product details
    description: str = ""
    item_type: str = "unknown"  # live_animal, supplies, food, cage, toy, etc.
    breed_or_variant: Optional[str] = None
    age: Optional[str] = None
    price_note: Optional[str] = None  # e.g., "adoption fee", "$35 deposit + $35 pickup"

    # Provenance
    source_url: str = ""
    extracted_at: str = ""
    confidence: float = 0.0  # 0.0-1.0, LLM extraction confidence

    # Metadata
    ttl_hours: int = 24  # Products expire in 24 hours by default
    claim_type: str = "product_listing"

    def to_claim_dict(self) -> Dict[str, Any]:
        """
        Convert to claim format for claim registry.

        Returns:
            Dict compatible with claim registry storage
        """
        # Format price display
        price_str = f"${self.price:.2f}" if self.price else "Price not listed"

        # Create concise summary
        summary_parts = [self.title]
        if self.price:
            summary_parts.append(f"({price_str})")
        if self.seller_name != "Unknown":
            summary_parts.append(f"from {self.seller_name}")

        return {
            "claim_type": "product_listing",
            "summary": " ".join(summary_parts),
            "title": self.title,
            "body": self.description or self.title,

            # Structured product data
            "product": {
                "title": self.title,
                "price": self.price,
                "currency": self.currency,
                "url": self.url,
                "seller_name": self.seller_name,
                "seller_type": self.seller_type,
                "in_stock": self.in_stock,
                "stock_quantity": self.stock_quantity,
                "item_type": self.item_type,
                "breed_or_variant": self.breed_or_variant,
                "age": self.age,
                "price_note": self.price_note,
            },

            # Provenance
            "source_url": self.source_url,
            "extracted_at": self.extracted_at,
            "confidence": self.confidence,

            # TTL
            "ttl_hours": self.ttl_hours,
            "expires_at": (
                datetime.fromisoformat(self.extracted_at.replace("Z", "+00:00")) +
                timedelta(hours=self.ttl_hours)
            ).isoformat() if self.extracted_at else None,
        }


def create_product_claim(
    title: str,
    price: Optional[float],
    url: str,
    seller_name: str = "Unknown",
    seller_type: str = "unknown",
    in_stock: bool = True,
    description: str = "",
    item_type: str = "unknown",
    breed_or_variant: Optional[str] = None,
    age: Optional[str] = None,
    source_url: str = "",
    confidence: float = 0.8,
    ttl_hours: int = 24,
) -> ProductClaim:
    """
    Helper function to create a product claim with defaults.

    Args:
        title: Product title
        price: Price in USD (None if not listed)
        url: Direct link to product page
        seller_name: Seller/store name
        seller_type: breeder, pet_store, marketplace, individual
        in_stock: Whether product is available
        description: Product description
        item_type: live_animal, supplies, food, etc.
        breed_or_variant: Specific breed or variant
        age: Age of animal (if applicable)
        source_url: Source page URL
        confidence: Extraction confidence (0.0-1.0)
        ttl_hours: Hours until claim expires

    Returns:
        ProductClaim instance
    """
    return ProductClaim(
        title=title,
        price=price,
        url=url or source_url,
        seller_name=seller_name,
        seller_type=seller_type,
        in_stock=in_stock,
        description=description,
        item_type=item_type,
        breed_or_variant=breed_or_variant,
        age=age,
        source_url=source_url,
        extracted_at=datetime.utcnow().isoformat() + "Z",
        confidence=confidence,
        ttl_hours=ttl_hours,
        claim_type="product_listing",
    )


def is_product_claim(claim: Dict[str, Any]) -> bool:
    """Check if a claim is a product listing."""
    return claim.get("claim_type") == "product_listing"


def get_product_data(claim: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract product data from a claim."""
    return claim.get("product") if is_product_claim(claim) else None
