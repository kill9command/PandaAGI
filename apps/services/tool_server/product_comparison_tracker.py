"""
orchestrator/product_comparison_tracker.py

Product comparison tracker for Phase 2 shopping.
Maintains a running "top N" list of best deals as retailers are visited.

Created: 2025-11-24
"""

import logging
from typing import List, Dict, Any
import re

logger = logging.getLogger(__name__)


class ProductComparisonTracker:
    """
    Track top N deals as we visit retailers.
    Automatically drops worse deals as better ones are found.
    """

    def __init__(self, max_products: int = 4):
        """
        Initialize tracker.

        Args:
            max_products: Maximum number of products to track (default: 4)
        """
        self.max_products = max_products
        self.top_products = []  # List of top deals
        self.seen_urls = set()  # Deduplication
        self.total_considered = 0  # Counter for stats

    def add_product(self, product: Dict[str, Any]) -> bool:
        """
        Add product to tracker. Returns True if product made the cut.

        Args:
            product: Product dict with name, price, vendor, url, etc.

        Returns:
            True if product was added to top list, False if rejected/dropped
        """
        url = product.get("url", "")

        # Skip duplicates (but allow multiple products from same search page)
        # Search pages often return multiple products with the same page URL
        is_search_page = any(x in url.lower() for x in [
            "searchpage", "/search", "/s?", "/p/pl?", "?q=", "?st=", "search.jsp", "?k="
        ])

        if not is_search_page and url in self.seen_urls:
            logger.info(f"[Tracker] Skipping duplicate product URL: {url[:80]}")
            return False
        elif is_search_page:
            # Allow multiple products from search pages
            logger.debug(f"[Tracker] Search page product (allowing): {product.get('name', 'unknown')[:60]}")

        self.seen_urls.add(url)
        self.total_considered += 1

        # Parse price and determine price status
        price_str = product.get("price", "")
        price_numeric = self._parse_price(price_str)
        price_status = self._determine_price_status(price_str, price_numeric)

        logger.info(f"[Tracker] Processing product: {product.get('name', 'unknown')[:60]} - price_str='{price_str}', price_numeric={price_numeric}, status={price_status}")

        # Store price info on product
        product["_price_numeric"] = price_numeric
        product["_price_status"] = price_status

        # Add to list (even without price - we return whatever info is available)
        self.top_products.append(product)

        # Sort by value score (priced products first, then by price/confidence)
        self.top_products.sort(key=lambda p: self._calculate_value_score(p))

        # Keep only top N
        if len(self.top_products) > self.max_products:
            dropped = self.top_products.pop()
            price_info = f"${dropped['_price_numeric']:.2f}" if dropped.get('_price_status') == 'priced' else dropped.get('_price_status', 'unknown')
            logger.info(
                f"[Tracker] Dropped worse deal: {dropped['name'][:40]} "
                f"({price_info}) from {dropped['vendor']} "
                f"(keeping top {self.max_products})"
            )
            return False

        price_info = f"${price_numeric:.2f}" if price_status == 'priced' else price_status
        logger.info(
            f"[Tracker] Added to top {len(self.top_products)}: "
            f"{product['name'][:40]} ({price_info}) from {product['vendor']}"
        )
        return True

    def _determine_price_status(self, price_str: str, price_numeric: float) -> str:
        """
        Determine price status from string and numeric value.

        Returns:
            - "priced": Has valid numeric price
            - "contact": Requires contacting vendor (breeders, etc.)
            - "unknown": Price not available or couldn't be parsed
        """
        if price_numeric > 0:
            return "priced"

        price_lower = str(price_str).lower()
        contact_keywords = [
            "contact", "inquire", "call", "email", "ask", "varies", "request",
            "adoption", "fee", "apply", "application", "quote", "pricing"
        ]
        if any(kw in price_lower for kw in contact_keywords):
            return "contact"

        return "unknown"

    def _parse_price(self, price_str: str) -> float:
        """
        Parse price string to numeric value.

        Examples:
            "$719.00" → 719.0
            "$1,299.99" → 1299.99
            "1500" → 1500.0
            "N/A" → 0.0 (invalid)
        """
        try:
            # Remove currency symbols and commas
            clean = re.sub(r'[$,]', '', str(price_str))
            return float(clean)
        except (ValueError, TypeError):
            return 0.0

    def _calculate_value_score(self, product: Dict[str, Any]) -> float:
        """
        Calculate value score for sorting.
        Lower score = better value.

        Factors:
        - Price status (priced > contact > unknown)
        - Price (lower better, for priced products)
        - Confidence (higher better)

        Returns:
            Float score (lower is better)
        """
        price = product.get("_price_numeric", 0)
        price_status = product.get("_price_status", "unknown")
        confidence = product.get("confidence", 0.7)

        # Base score by price status:
        # - priced products: 0 + price-based score
        # - contact products: 1,000,000 + confidence-based score
        # - unknown products: 2,000,000 + confidence-based score
        if price_status == "priced" and price > 0:
            # Score = price / confidence (lower price, higher confidence = better)
            score = price / max(confidence, 0.1)
        elif price_status == "contact":
            # Contact products: rank by confidence only
            score = 1_000_000 + (1 - confidence) * 1000
        else:
            # Unknown products: lowest priority, rank by confidence
            score = 2_000_000 + (1 - confidence) * 1000

        return score

    def get_top_products(self) -> List[Dict[str, Any]]:
        """Get final top products."""
        return self.top_products

    def get_summary(self) -> str:
        """Get comparison summary for logging."""
        if not self.top_products:
            return "No products tracked"

        summary = f"Top {len(self.top_products)} deals (from {self.total_considered} considered):\n"
        for i, p in enumerate(self.top_products, 1):
            price_status = p.get('_price_status', 'unknown')
            if price_status == 'priced':
                price_display = f"${p['_price_numeric']:.2f}"
            elif price_status == 'contact':
                price_display = "Contact for price"
            else:
                price_display = "Price unknown"

            summary += (
                f"{i}. {p['name'][:40]} - "
                f"{price_display} at {p['vendor']} "
                f"(confidence: {p.get('confidence', 0.7):.2f})\n"
            )

        return summary

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about comparison."""
        return {
            "total_considered": self.total_considered,
            "top_count": len(self.top_products),
            "max_products": self.max_products,
            "unique_vendors": len(set(p.get("vendor", "") for p in self.top_products))
        }
