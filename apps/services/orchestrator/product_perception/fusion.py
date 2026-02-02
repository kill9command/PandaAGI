"""
Product fusion - matches vision products to HTML URL candidates.

Uses fuzzy string matching to find the best URL for each
visually-identified product.
"""

import logging
import re
from difflib import SequenceMatcher
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse

from .models import VisualProduct, HTMLCandidate, FusedProduct
from .config import get_config

logger = logging.getLogger(__name__)


class ProductFusion:
    """
    Matches vision products to HTML URL candidates.

    Strategy:
    1. For each vision product, find best matching HTML candidate
    2. Use fuzzy string matching on title vs link_text
    3. Boost confidence when both sources agree
    4. Mark unmatched products for click-resolve fallback
    """

    def __init__(self, similarity_threshold: float = None):
        self.config = get_config()
        self.similarity_threshold = similarity_threshold or self.config.similarity_threshold

    def match(
        self,
        vision_products: List[VisualProduct],
        html_candidates: List[HTMLCandidate],
        base_url: str
    ) -> List[FusedProduct]:
        """
        Match vision products to HTML URLs.

        Args:
            vision_products: Products identified by OCR/vision
            html_candidates: URL candidates from HTML extraction
            base_url: Current page URL (fallback)

        Returns:
            List of FusedProduct with URLs where matched
        """
        vendor = urlparse(base_url).netloc
        fused = []
        used_urls = set()

        # Pre-process HTML candidates for faster matching
        html_lookup = self._build_lookup(html_candidates)

        logger.info(f"[Fusion] Matching {len(vision_products)} vision products to {len(html_candidates)} HTML candidates")

        for vp in vision_products:
            best_match, best_score = self._find_best_match(vp, html_candidates, used_urls)

            if best_match and best_score >= self.similarity_threshold:
                # Good match found
                used_urls.add(best_match.url)

                fused.append(FusedProduct(
                    title=vp.title,
                    price=vp.price_numeric,
                    price_str=vp.price or "",
                    url=best_match.url,
                    vendor=vendor,
                    confidence=min(0.98, vp.confidence + self.config.boost_on_match),
                    extraction_method="fusion",
                    vision_verified=True,
                    url_source=best_match.source,
                    bbox=vp.bbox,
                    match_score=best_score
                ))

                logger.debug(f"[Fusion] Matched '{vp.title[:40]}...' to URL (score={best_score:.2f})")

            else:
                # No match - use fallback URL, mark for potential click-resolve
                fused.append(FusedProduct(
                    title=vp.title,
                    price=vp.price_numeric,
                    price_str=vp.price or "",
                    url=base_url,  # Fallback to search page
                    vendor=vendor,
                    confidence=vp.confidence * 0.7,  # Lower confidence without URL
                    extraction_method="vision_only",
                    vision_verified=True,
                    url_source="fallback",
                    bbox=vp.bbox,
                    match_score=best_score or 0.0
                ))

                logger.debug(f"[Fusion] No match for '{vp.title[:40]}...' (best score={best_score or 0:.2f})")

        # Stats
        matched = sum(1 for p in fused if p.url_source != "fallback")
        logger.info(f"[Fusion] Matched {matched}/{len(fused)} products to URLs")

        return fused

    def _find_best_match(
        self,
        vision_product: VisualProduct,
        html_candidates: List[HTMLCandidate],
        used_urls: set
    ) -> Tuple[Optional[HTMLCandidate], float]:
        """Find the best matching HTML candidate for a vision product."""
        best_match = None
        best_score = 0.0

        vision_title = self._normalize_text(vision_product.title)

        for hc in html_candidates:
            if hc.url in used_urls:
                continue

            # Compare vision title to HTML link text
            link_text = self._normalize_text(hc.link_text)
            score = self._similarity(vision_title, link_text)

            # Also try context text if link text is short
            if len(hc.link_text) < 25 and hc.context_text:
                context = self._normalize_text(hc.context_text)
                context_score = self._similarity(vision_title, context)
                score = max(score, context_score * 0.9)  # Slight discount for context

            # Try matching significant words
            word_score = self._word_overlap_score(vision_title, link_text)
            score = max(score, word_score)

            if score > best_score:
                best_score = score
                best_match = hc

        return best_match, best_score

    def _build_lookup(self, candidates: List[HTMLCandidate]) -> Dict[str, HTMLCandidate]:
        """Build lookup dict for faster matching."""
        lookup = {}
        for c in candidates:
            # Index by normalized link text
            key = self._normalize_text(c.link_text)
            if key not in lookup:
                lookup[key] = c
        return lookup

    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison."""
        if not text:
            return ""

        # Lowercase
        text = text.lower()

        # Remove special characters except spaces
        text = re.sub(r'[^\w\s]', ' ', text)

        # Collapse multiple spaces
        text = ' '.join(text.split())

        return text.strip()

    def _similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity using SequenceMatcher."""
        if not s1 or not s2:
            return 0.0

        return SequenceMatcher(None, s1, s2).ratio()

    def _word_overlap_score(self, s1: str, s2: str) -> float:
        """
        Calculate similarity based on word overlap.

        This is often better than character-level similarity for product titles
        where word order may vary.
        """
        if not s1 or not s2:
            return 0.0

        # Extract significant words (length >= 3)
        words1 = set(w for w in s1.split() if len(w) >= 3)
        words2 = set(w for w in s2.split() if len(w) >= 3)

        if not words1 or not words2:
            return 0.0

        # Calculate Jaccard similarity
        intersection = len(words1 & words2)
        union = len(words1 | words2)

        if union == 0:
            return 0.0

        return intersection / union


def match_html_only(
    html_candidates: List[HTMLCandidate],
    base_url: str,
    max_products: int = 20
) -> List[FusedProduct]:
    """
    Create FusedProduct list from HTML candidates only (no vision).

    Used as fallback when vision extraction fails.
    """
    vendor = urlparse(base_url).netloc
    products = []

    # Filter out common UI element text that's not actual product names
    UI_GARBAGE_PATTERNS = {
        # Common UI buttons
        'quick view', 'add to cart', 'add to bag', 'buy now', 'shop now',
        'view details', 'see details', 'learn more', 'read more',
        'next', 'previous', 'prev', 'back', 'forward',
        'compare', 'save', 'share', 'wishlist', 'notify me',
        'sold out', 'out of stock', 'in stock', 'available',
        'free shipping', 'fast delivery', 'best seller', 'new arrival',
        'see more', 'show more', 'load more', 'view all', 'see all',
        'sign in', 'sign up', 'login', 'register', 'subscribe',
        'close', 'dismiss', 'skip', 'cancel', 'ok', 'yes', 'no',
        # Navigation items
        'home', 'menu', 'search', 'account', 'cart', 'checkout',
        'order status', 'saved items', 'recently viewed',
        'help', 'support', 'contact us', 'customer service',
        # Best Buy specific
        'yardbird', 'best buy outlet', 'best buy business',
        'gift ideas', 'gift cards', 'black friday deals', 'deal of the day',
        'discover', 'my best buy memberships', 'credit cards',
        'featured', 'trending', 'top deals',
        'best buy',  # Retailer name as navigation link
        # Amazon specific
        'see options', 'amazon secured card', 'amazon business card',
        'amazon prime', 'amazon basics', 'amazon renewed',
        '4 capacities', '5 capacities', '6 capacities', '7 capacities',
        'debug info copied.',
        'amazon', 'amazon.com',  # Retailer name as navigation link
        # Newegg specific
        'refurbished core component',
        'newegg', 'newegg.com',  # Retailer name
        # Walmart specific
        'walmart', 'walmart.com',  # Retailer name
        # Target specific
        'target', 'target.com',  # Retailer name
        # Generic navigation
        'all departments', 'all categories', 'browse all',
        'stores', 'locations', 'store locator',
        # Category/breadcrumb navigation (common on PDPs and listing pages)
        'computers', 'computers & tablets', 'tablets',
        'electronics', 'gaming', 'gaming laptops',
        'laptops', 'laptop computers', 'notebooks',
        'desktops', 'desktop computers',
        'phones', 'cell phones', 'smartphones',
        'tv', 'tvs', 'televisions',
        'appliances', 'home appliances',
        'video games', 'pc gaming',
        'audio', 'headphones', 'speakers',
        'cameras', 'camera', 'drones',
        'smart home', 'wearables',
        # Department names
        'department', 'departments', 'shop by category',
        'shop all', 'shop by brand', 'brands',
    }

    for hc in html_candidates[:max_products * 3]:  # Check more to filter garbage
        # Skip very short link text (probably icons/buttons)
        if len(hc.link_text.strip()) < 5:
            continue

        # Skip common UI element text
        link_lower = hc.link_text.lower().strip()
        if link_lower in UI_GARBAGE_PATTERNS:
            continue

        # Skip if it starts with common UI patterns
        if any(link_lower.startswith(p) for p in ['click to', 'tap to', 'select to']):
            continue

        # Skip if no letters (just numbers/symbols)
        if not any(c.isalpha() for c in hc.link_text):
            continue

        if len(products) >= max_products:
            break
        # Try to extract price from context
        price_match = re.search(r'\$[\d,]+\.?\d*', hc.context_text or hc.link_text)
        price_str = price_match.group() if price_match else ""
        price_numeric = None
        if price_str:
            try:
                price_numeric = float(re.sub(r'[^\d.]', '', price_str))
            except ValueError:
                pass

        products.append(FusedProduct(
            title=hc.link_text,
            price=price_numeric,
            price_str=price_str,
            url=hc.url,
            vendor=vendor,
            confidence=hc.confidence * 0.8,  # Discount for no vision verification
            extraction_method="html_only",
            vision_verified=False,
            url_source=hc.source,
            bbox=None,
            match_score=0.0
        ))

    return products
