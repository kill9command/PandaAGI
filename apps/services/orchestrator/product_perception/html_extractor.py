"""
HTML-based product URL extraction.

Extracts product URLs from HTML using multiple strategies:
1. JSON-LD structured data (most reliable)
2. URL pattern matching (fast)
3. DOM heuristics (links near prices)
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import HTMLCandidate
from .config import get_config

logger = logging.getLogger(__name__)


class HTMLExtractor:
    """
    Fast HTML-based extraction for product URLs.

    Strategies (in order of reliability):
    1. JSON-LD structured data (most reliable)
    2. URL pattern matching (fast)
    3. DOM heuristics (link + price nearby)
    """

    # Universal product URL patterns
    PRODUCT_URL_PATTERNS = [
        r'/dp/[A-Z0-9]{10}',           # Amazon ASIN
        r'/gp/product/[A-Z0-9]+',      # Amazon alt
        r'/product/[\w-]+',            # Best Buy new style (2024+) and generic
        r'/p/[\w-]+',                  # Newegg style (e.g., /p/2WC-000C-0GXH3) and generic
        r'/item/[\w-]+',               # Newegg alternate style
        r'/site/[^/]+/\d+\.p',         # Best Buy old style
        r'/ip/[\d]+',                  # Walmart
        r'/products/[\w-]+',           # Shopify style
        r'/pd/[\w-]+',                 # Target
    ]

    # URLs to skip (not product pages)
    SKIP_URL_PATTERNS = [
        r'/search',
        r'/category',
        r'/filter',
        r'/sort',
        r'/help',
        r'/account',
        r'/cart',
        r'/wishlist',
        r'/signin',
        r'/reviews',
        r'#',
        r'javascript:',
    ]

    # Sponsored/ad URL patterns to filter out
    SPONSORED_URL_PATTERNS = [
        r'/sponsored/',
        r'/sspa/',              # Amazon sponsored products API
        r'/slredirect/',        # Redirect trackers
        r'/gp/r\.html',         # Amazon redirect
        r'aax-us-east',         # Amazon ad server
        r'aax-us-iad',          # Amazon ad server variant
        r'/adclick',            # Generic ad click
        r'/clicktracker',       # Click tracking
        r'/advertisement/',
        r'doubleclick\.net',    # Google ads
        r'googlesyndication',   # Google ads
        r'/beacon/',            # Analytics beacons
        r'/pixel/',             # Tracking pixels
    ]

    # Link text patterns that are UI elements, not products
    GARBAGE_LINK_TEXT = {
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

    def __init__(self):
        self.config = get_config()
        self._compiled_product_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.PRODUCT_URL_PATTERNS
        ]
        self._compiled_skip_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.SKIP_URL_PATTERNS
        ]
        self._compiled_sponsored_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.SPONSORED_URL_PATTERNS
        ]

    def _is_sponsored_url(self, url: str) -> bool:
        """Check if URL is a sponsored/ad URL that should be filtered."""
        if not url:
            return False
        for pattern in self._compiled_sponsored_patterns:
            if pattern.search(url):
                return True
        return False

    async def extract(self, html: str, base_url: str) -> List[HTMLCandidate]:
        """
        Extract product URL candidates from HTML.

        Args:
            html: Raw HTML content
            base_url: Base URL for resolving relative links

        Returns:
            List of HTMLCandidate with product URLs
        """
        candidates = []
        config = self.config

        soup = BeautifulSoup(html, 'html.parser')

        # Strategy 1: JSON-LD (most reliable when present)
        if config.enable_json_ld:
            json_ld_candidates = self._extract_json_ld(soup, base_url)
            candidates.extend(json_ld_candidates)
            logger.debug(f"[HTMLExtractor] JSON-LD found {len(json_ld_candidates)} candidates")

        # Strategy 2: URL patterns (retailer-specific)
        if config.enable_url_patterns:
            pattern_candidates = self._extract_url_patterns(soup, base_url)
            candidates.extend(pattern_candidates)
            logger.debug(f"[HTMLExtractor] URL patterns found {len(pattern_candidates)} candidates")

        # Strategy 3: DOM heuristics (links near prices)
        if config.enable_dom_heuristics and len(candidates) < 5:
            heuristic_candidates = self._extract_heuristics(soup, base_url)
            candidates.extend(heuristic_candidates)
            logger.debug(f"[HTMLExtractor] Heuristics found {len(heuristic_candidates)} candidates")

        # Deduplicate by URL
        unique = self._deduplicate(candidates)

        # Filter out sponsored/ad URLs
        filtered = []
        sponsored_count = 0
        for candidate in unique:
            if self._is_sponsored_url(candidate.url):
                logger.debug(f"[HTMLExtractor] Filtered sponsored URL: {candidate.url[:60]}...")
                sponsored_count += 1
            else:
                filtered.append(candidate)

        if sponsored_count > 0:
            logger.info(f"[HTMLExtractor] Filtered {sponsored_count} sponsored URLs")

        logger.info(f"[HTMLExtractor] Found {len(filtered)} unique URL candidates from {base_url}")
        return filtered

    def _extract_json_ld(self, soup: BeautifulSoup, base_url: str) -> List[HTMLCandidate]:
        """Extract from JSON-LD structured data (Schema.org Product)."""
        candidates = []

        for script in soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                products = self._find_products_in_json_ld(data)

                for p in products:
                    url = p.get('url') or p.get('offers', {}).get('url')
                    if url:
                        candidates.append(HTMLCandidate(
                            url=urljoin(base_url, url),
                            link_text=p.get('name', ''),
                            context_text=p.get('description', '')[:200] if p.get('description') else '',
                            source="json_ld",
                            confidence=0.95  # High confidence for structured data
                        ))
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue

        return candidates

    def _find_products_in_json_ld(self, data: Any) -> List[Dict]:
        """Recursively find Product objects in JSON-LD data."""
        products = []

        if isinstance(data, dict):
            # Check if this is a Product
            item_type = data.get('@type', '')
            if isinstance(item_type, list):
                item_type = item_type[0] if item_type else ''

            if item_type in ('Product', 'IndividualProduct', 'ProductModel'):
                products.append(data)

            # Check @graph array
            if '@graph' in data:
                products.extend(self._find_products_in_json_ld(data['@graph']))

            # Check nested objects
            for value in data.values():
                if isinstance(value, (dict, list)):
                    products.extend(self._find_products_in_json_ld(value))

        elif isinstance(data, list):
            for item in data:
                products.extend(self._find_products_in_json_ld(item))

        return products

    def _extract_url_patterns(self, soup: BeautifulSoup, base_url: str) -> List[HTMLCandidate]:
        """Extract URLs matching known product page patterns."""
        candidates = []
        seen_urls = set()

        for link in soup.find_all('a', href=True):
            href = link['href']

            # Skip empty or javascript links
            if not href or href.startswith('javascript:') or href == '#':
                continue

            # Check if matches any product pattern
            if not any(p.search(href) for p in self._compiled_product_patterns):
                continue

            # Skip non-product URLs
            if any(p.search(href) for p in self._compiled_skip_patterns):
                continue

            full_url = urljoin(base_url, href)

            # Deduplicate within this method
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Get link text
            link_text = link.get_text(strip=True)

            # If link text is too short (icon/image), try parent
            if len(link_text) < 5:
                parent = link.find_parent(['h2', 'h3', 'h4', 'div', 'span'])
                if parent:
                    link_text = parent.get_text(strip=True)[:150]

            # Skip if still no good text
            if len(link_text) < 3:
                continue

            # Skip garbage UI element text
            if link_text.lower().strip() in self.GARBAGE_LINK_TEXT:
                continue

            candidates.append(HTMLCandidate(
                url=full_url,
                link_text=link_text[:200],
                context_text="",
                source="url_pattern",
                confidence=0.85
            ))

        return candidates

    def _extract_heuristics(self, soup: BeautifulSoup, base_url: str) -> List[HTMLCandidate]:
        """Find links that appear near price-like text."""
        candidates = []
        seen_urls = set()

        # Find all text nodes containing price patterns
        price_pattern = re.compile(r'\$[\d,]+\.?\d*')

        # Look for container elements that have both price and link
        for container in soup.find_all(['div', 'li', 'article', 'section']):
            text = container.get_text()

            # Must have a price
            if not price_pattern.search(text):
                continue

            # Must not be too large (probably a page section, not product card)
            if len(text) > 2000:
                continue

            # Find links within this container
            links = container.find_all('a', href=True)

            for link in links:
                href = link['href']

                # Skip bad URLs
                if not href or any(p.search(href) for p in self._compiled_skip_patterns):
                    continue

                full_url = urljoin(base_url, href)

                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                link_text = link.get_text(strip=True)
                if len(link_text) < 3:
                    continue

                # Skip garbage UI element text
                if link_text.lower().strip() in self.GARBAGE_LINK_TEXT:
                    continue

                candidates.append(HTMLCandidate(
                    url=full_url,
                    link_text=link_text[:200],
                    context_text=text[:300],
                    source="dom_heuristic",
                    confidence=0.7  # Lower confidence for heuristic
                ))

        return candidates

    def _deduplicate(self, candidates: List[HTMLCandidate]) -> List[HTMLCandidate]:
        """Deduplicate candidates by URL, keeping highest confidence."""
        url_to_candidate: Dict[str, HTMLCandidate] = {}

        for c in candidates:
            # Normalize URL (remove tracking params)
            normalized = self._normalize_url(c.url)

            if normalized not in url_to_candidate:
                url_to_candidate[normalized] = c
            elif c.confidence > url_to_candidate[normalized].confidence:
                # Keep higher confidence version
                url_to_candidate[normalized] = c

        return list(url_to_candidate.values())

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        parsed = urlparse(url)
        # Keep scheme, netloc, path - remove query params and fragments
        # (but keep essential product ID params)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
