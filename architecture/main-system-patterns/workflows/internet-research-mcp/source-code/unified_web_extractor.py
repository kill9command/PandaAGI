"""
DEPRECATED: This module is superseded by smart_extractor.py

Use smart_extractor.py instead - it provides LLM-driven self-correcting
extraction that learns page structures automatically.

Migration:
    from orchestrator.smart_extractor import get_smart_extractor
    extractor = get_smart_extractor()
    result = await extractor.extract(page, url)

---
ORIGINAL DOCSTRING (kept for reference):
UnifiedWebExtractor - ONE extraction system for ALL webpages.

This is the single entry point for extracting structured content from any webpage.
It automatically detects site type and applies the best extraction strategy.

Architecture:
1. CALIBRATE - Learn nav vs content zones per domain (auto, first visit)
2. DETECT - Classify page type (commerce, forum, wiki, news, docs, search, generic)
3. EXTRACT - Apply site-type-specific strategies with learned nav filtering
4. LEARN - Cache winning patterns per domain for faster future extractions
5. FALLBACK - Use calibration/schema system if universal methods fail

Usage:
    extractor = get_unified_extractor()
    results = await extractor.extract(page, url)
    # results is List[ExtractedContent] - works for any site type
"""

import warnings
warnings.warn(
    "unified_web_extractor is deprecated, use smart_extractor instead",
    DeprecationWarning,
    stacklevel=2
)

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any, TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from playwright.async_api import Page

# Import content zone calibrator via PageIntelligence adapter
try:
    from orchestrator.page_intelligence.legacy_adapter import (
        get_content_zone_calibrator,
        get_content_zone_registry,
        ContentZoneSchema
    )
    # These functions still need the old module for JS generation
    from orchestrator.content_zone_calibrator import (
        get_nav_filter_js,
        get_product_patterns_js,
    )
    CALIBRATOR_AVAILABLE = True
except ImportError:
    CALIBRATOR_AVAILABLE = False
    ContentZoneSchema = None
    def get_product_patterns_js(schema):
        return ""

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================

class SiteType(Enum):
    """Types of websites we can extract from."""
    COMMERCE = "commerce"      # E-commerce, product listings
    FORUM = "forum"            # Forums, discussion boards, Reddit
    WIKI = "wiki"              # Wikipedia, wikis, knowledge bases
    NEWS = "news"              # News sites, blogs, articles
    DOCS = "docs"              # Documentation, API references
    SEARCH = "search"          # Search engine results
    GENERIC = "generic"        # Fallback for unknown sites


@dataclass
class ExtractedContent:
    """
    Universal container for extracted content.
    Works for any site type - fields are optional based on what's available.
    """
    url: str
    title: str

    # Metadata
    site_type: str = "generic"
    extraction_method: str = "unknown"
    confidence: float = 0.8

    # Content fields (populated based on site type)
    price: Optional[str] = None           # Commerce
    author: Optional[str] = None          # Forum, News
    date: Optional[str] = None            # Forum, News, Wiki
    snippet: Optional[str] = None         # All types - description/excerpt
    image_url: Optional[str] = None       # Commerce, News
    votes: Optional[int] = None           # Forum (Reddit-style)
    replies: Optional[int] = None         # Forum

    def to_dict(self) -> Dict:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}

    def to_html_candidate(self):
        """Convert to HTMLCandidate for compatibility with existing pipeline."""
        from orchestrator.product_perception.models import HTMLCandidate
        return HTMLCandidate(
            url=self.url,
            link_text=self.title,
            context_text=self.price or self.snippet or "",
            source=self.extraction_method,
            confidence=self.confidence
        )


@dataclass
class LearnedPattern:
    """Cached pattern that worked for a domain."""
    domain: str
    site_type: str
    best_strategy: str
    success_count: int = 0
    fail_count: int = 0
    last_used: Optional[str] = None
    avg_items: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.5

    @property
    def needs_relearning(self) -> bool:
        return self.success_rate < 0.4 and (self.success_count + self.fail_count) >= 3


# =============================================================================
# PATTERN CACHE - Learns what works per domain
# =============================================================================

class PatternCache:
    """Persistent cache for learned extraction patterns."""

    def __init__(self, cache_path: str = "panda_system_docs/schemas/extraction_patterns.jsonl"):
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._patterns: Dict[str, LearnedPattern] = {}
        self._load()

    def _load(self):
        if not self.cache_path.exists():
            return
        try:
            with open(self.cache_path, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    self._patterns[data["domain"]] = LearnedPattern(**data)
            logger.info(f"[PatternCache] Loaded {len(self._patterns)} patterns")
        except Exception as e:
            logger.error(f"[PatternCache] Load error: {e}")

    def _save(self):
        try:
            with open(self.cache_path, 'w') as f:
                for p in self._patterns.values():
                    f.write(json.dumps(asdict(p)) + "\n")
        except Exception as e:
            logger.error(f"[PatternCache] Save error: {e}")

    def get(self, domain: str) -> Optional[LearnedPattern]:
        return self._patterns.get(domain)

    def record(self, domain: str, site_type: str, strategy: str, success: bool, items: int = 0):
        now = datetime.now(timezone.utc).isoformat()

        if domain in self._patterns:
            p = self._patterns[domain]
            if success:
                p.success_count += 1
                p.avg_items = (p.avg_items * (p.success_count - 1) + items) / p.success_count
            else:
                p.fail_count += 1
            p.last_used = now
            # Update best strategy if this one is consistently better
            if success and strategy != p.best_strategy and p.success_count > 2:
                p.best_strategy = strategy
        else:
            self._patterns[domain] = LearnedPattern(
                domain=domain,
                site_type=site_type,
                best_strategy=strategy,
                success_count=1 if success else 0,
                fail_count=0 if success else 1,
                last_used=now,
                avg_items=float(items) if success else 0.0
            )

        self._save()

    def clear(self, domain: str):
        if domain in self._patterns:
            del self._patterns[domain]
            self._save()


# Global cache
_cache: Optional[PatternCache] = None

def get_pattern_cache() -> PatternCache:
    global _cache
    if _cache is None:
        _cache = PatternCache()
    return _cache


# =============================================================================
# UNIFIED WEB EXTRACTOR
# =============================================================================

class UnifiedWebExtractor:
    """
    Single extraction system for ALL webpages.

    Automatically detects site type and applies best strategy.
    Learns from successes/failures per domain.
    Uses content zone calibration for automatic nav/content detection.
    """

    # TODO(LLM-FIRST): Site type detection should use LLM classification, not hardcoded patterns.
    # INSTEAD OF: Hardcoded domain patterns (amazon, ebay, walmart, etc.)
    # SHOULD BE: Let the LLM classify site type based on page content analysis.
    #
    # Why this matters:
    # - New commerce sites get misclassified as GENERIC
    # - Content analysis (CONTENT_SIGNALS below) is already more flexible
    # - LLM can understand nuance (a product review page vs product listing)
    #
    # Recommended approach:
    # 1. Remove domain-specific patterns entirely
    # 2. Keep generic URL path patterns (they're structural, not site-specific)
    # 3. Use LLM + page content for final classification
    #
    # See: panda_system_docs/architecture/LLM-ROLES/CONTEXT_DISCIPLINE.md
    URL_PATTERNS = {
        SiteType.COMMERCE: [
            # TODO(LLM-FIRST): REMOVE domain-specific patterns below
            r'amazon\.', r'ebay\.', r'walmart\.', r'bestbuy\.', r'newegg\.',
            r'etsy\.', r'aliexpress\.', r'target\.', r'homedepot\.',
            # Generic path patterns are OK - they're structural
            r'/shop', r'/store', r'/product', r'/buy', r'/cart', r'/item',
        ],
        SiteType.FORUM: [
            # TODO(LLM-FIRST): REMOVE domain-specific patterns
            r'reddit\.com', r'stackoverflow\.', r'stackexchange\.', r'discourse\.',
            r'/forum', r'/thread', r'/discussion', r'/community', r'/r/',
            r'/comments/', r'quora\.', r'slashdot\.',
        ],
        SiteType.WIKI: [
            # TODO(LLM-FIRST): REMOVE domain-specific patterns
            r'wikipedia\.', r'fandom\.com', r'wikia\.', r'/wiki/',
        ],
        SiteType.NEWS: [
            # TODO(LLM-FIRST): REMOVE domain-specific patterns
            r'cnn\.', r'bbc\.', r'nytimes\.', r'theguardian\.', r'reuters\.',
            r'techcrunch\.', r'theverge\.', r'wired\.', r'arstechnica\.',
            r'/news', r'/article', r'/story', r'/blog',
            r'news\.ycombinator\.', r'hackernews',
        ],
        SiteType.DOCS: [
            # TODO(LLM-FIRST): REMOVE domain-specific patterns
            r'docs\.', r'readthedocs\.', r'gitbook\.', r'swagger\.',
            r'/docs', r'/documentation', r'/api', r'/reference',
        ],
        SiteType.SEARCH: [
            # Search engine detection - these are OK as they're identifying
            # search result pages specifically for extraction strategy
            r'google\.com/search', r'bing\.com/search', r'duckduckgo\.com',
            r'/search\?', r'[?&]q=',
        ],
    }

    # Content signals are more acceptable than domain patterns because they
    # analyze what's ON the page rather than assuming by domain name.
    # However, an LLM could still do this better with full context.
    CONTENT_SIGNALS = {
        SiteType.COMMERCE: ['add to cart', 'buy now', 'price', 'in stock', 'shipping', 'sold by'],
        SiteType.FORUM: ['reply', 'post', 'comment', 'upvote', 'downvote', 'joined', 'points'],
        SiteType.WIKI: ['[edit]', 'references', 'see also', 'external links', 'categories'],
        SiteType.NEWS: ['published', 'updated', 'by ', 'min read', 'share', 'subscribe'],
        SiteType.DOCS: ['api', 'endpoint', 'parameter', 'returns', 'example', 'import'],
        SiteType.SEARCH: ['results', 'showing', 'pages', 'did you mean'],
    }

    def __init__(self):
        self.cache = get_pattern_cache()
        self._content_zone_cache: Dict[str, Optional[ContentZoneSchema]] = {}
        self._last_availability_notice: Optional[Dict[str, Any]] = None

    def get_last_availability_notice(self) -> Optional[Dict[str, Any]]:
        """
        Get the last availability notice from calibration.

        Returns None if no restrictions, or a dict with:
        - domain: str
        - status: str (e.g., "in_store_only", "out_of_stock")
        - summary: str (human-readable summary)
        - notices: List[str] (individual notice messages)
        - constraints: List[str] (purchase constraints)

        This allows callers to report availability restrictions to users
        instead of just failing silently.
        """
        return self._last_availability_notice

    async def _get_content_zone_schema(self, page: 'Page', url: str) -> Optional[ContentZoneSchema]:
        """
        Get or calibrate content zone schema for a domain.

        This learns what elements are navigation vs content automatically.
        """
        if not CALIBRATOR_AVAILABLE:
            return None

        domain = urlparse(url).netloc.replace('www.', '')

        # Check memory cache
        if domain in self._content_zone_cache:
            return self._content_zone_cache[domain]

        # Check persistent cache
        registry = get_content_zone_registry()
        schema = registry.get(domain)

        if schema and schema.calibration_confidence >= 0.5:
            self._content_zone_cache[domain] = schema
            return schema

        # Calibrate (first visit or low confidence)
        try:
            calibrator = get_content_zone_calibrator()
            schema = await calibrator.calibrate(page, url)
            self._content_zone_cache[domain] = schema
            return schema
        except Exception as e:
            logger.warning(f"[UnifiedExtractor] Content zone calibration failed: {e}")
            self._content_zone_cache[domain] = None
            return None

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    async def extract(self, page: 'Page', url: str,
                      max_items: int = 20,
                      site_type: SiteType = None,
                      skip_calibration: bool = False) -> List[ExtractedContent]:
        """
        Extract content from any webpage.

        Args:
            page: Playwright page object
            url: Current URL
            max_items: Maximum items to extract
            site_type: Optional override (auto-detected if not provided)
            skip_calibration: Skip content zone calibration (faster but less accurate)

        Returns:
            List of ExtractedContent objects
        """
        domain = urlparse(url).netloc.replace('www.', '')

        # Get or calibrate content zone schema (learns nav vs content automatically)
        content_zone_schema = None
        if not skip_calibration:
            content_zone_schema = await self._get_content_zone_schema(page, url)
            if content_zone_schema:
                logger.info(
                    f"[UnifiedExtractor] Using content zone schema for {domain}: "
                    f"{len(content_zone_schema.nav_text_fingerprints)} nav fingerprints, "
                    f"content zone: {content_zone_schema.content_zone_selector}"
                )

                # Check for availability restrictions - log and store for caller
                if hasattr(content_zone_schema, 'has_availability_restriction') and content_zone_schema.has_availability_restriction():
                    availability_summary = content_zone_schema.get_availability_summary()
                    logger.warning(
                        f"[UnifiedExtractor] AVAILABILITY NOTICE for {domain}: {availability_summary}"
                    )
                    # Store availability info for caller to access
                    self._last_availability_notice = {
                        "domain": domain,
                        "status": content_zone_schema.availability_status,
                        "summary": availability_summary,
                        "notices": content_zone_schema.page_notices,
                        "constraints": content_zone_schema.purchase_constraints
                    }
                else:
                    self._last_availability_notice = None

        # Check cache for learned pattern
        cached = self.cache.get(domain)
        if cached and not cached.needs_relearning:
            site_type = SiteType(cached.site_type)
            logger.info(f"[UnifiedExtractor] Using cached pattern for {domain}: {cached.best_strategy}")

        # Auto-detect site type if not provided
        if site_type is None:
            site_type = await self._detect_site_type(page, url)

        logger.info(f"[UnifiedExtractor] Extracting {domain} as {site_type.value}")

        # Get strategies for this site type
        strategies = self._get_strategies(site_type)

        # Generate nav filter JS from schema
        nav_filter_js = get_nav_filter_js(content_zone_schema) if CALIBRATOR_AVAILABLE else self._get_fallback_nav_filter_js()

        # Generate product patterns JS from schema (for commerce strategies)
        product_patterns_js = get_product_patterns_js(content_zone_schema) if CALIBRATOR_AVAILABLE else ""

        # Try strategies until we get good results
        best_results = []
        best_strategy = None

        for strategy_name, strategy_fn in strategies:
            try:
                results = await strategy_fn(page, url, max_items, nav_filter_js, product_patterns_js)

                # Score results
                score = self._score_results(results, site_type)

                if len(results) > len(best_results):
                    best_results = results
                    best_strategy = strategy_name

                # Good enough - stop trying
                if len(results) >= 3 and score >= 0.5:
                    logger.info(f"[UnifiedExtractor] {strategy_name}: {len(results)} items (score={score:.2f})")
                    break

            except Exception as e:
                logger.debug(f"[UnifiedExtractor] {strategy_name} failed: {e}")
                continue

        # Record in cache
        success = len(best_results) >= 3
        self.cache.record(domain, site_type.value, best_strategy or "none", success, len(best_results))

        logger.info(f"[UnifiedExtractor] Result: {len(best_results)} items via {best_strategy}")
        return best_results

    async def extract_as_candidates(self, page: 'Page', url: str, max_items: int = 20):
        """Extract and return as HTMLCandidate objects for pipeline compatibility."""
        results = await self.extract(page, url, max_items)
        return [r.to_html_candidate() for r in results]

    # =========================================================================
    # SITE TYPE DETECTION
    # =========================================================================

    async def _detect_site_type(self, page: 'Page', url: str) -> SiteType:
        """Auto-detect what type of site this is."""
        url_lower = url.lower()

        # Check URL patterns (fast)
        for site_type, patterns in self.URL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, url_lower):
                    return site_type

        # Check page content (slower)
        try:
            text = await page.evaluate('() => document.body?.innerText?.toLowerCase().slice(0, 3000) || ""')

            scores = {st: 0 for st in SiteType}
            for site_type, signals in self.CONTENT_SIGNALS.items():
                for signal in signals:
                    if signal in text:
                        scores[site_type] += 1

            best = max(scores, key=scores.get)
            if scores[best] >= 2:
                return best
        except:
            pass

        return SiteType.GENERIC

    # =========================================================================
    # STRATEGY SELECTION
    # =========================================================================

    def _get_strategies(self, site_type: SiteType) -> List[tuple]:
        """Get ordered list of (name, function) strategies for site type."""

        # Type-specific strategies first
        type_strategies = {
            SiteType.COMMERCE: [
                ("price_first", self._strategy_price_first),
                ("product_cards", self._strategy_product_cards),
            ],
            SiteType.FORUM: [
                ("timestamp_first", self._strategy_timestamp_first),
                ("vote_first", self._strategy_vote_first),
                ("post_containers", self._strategy_post_containers),
            ],
            SiteType.WIKI: [
                ("wiki_links", self._strategy_wiki_links),
            ],
            SiteType.NEWS: [
                ("article_cards", self._strategy_article_cards),
                ("news_items", self._strategy_news_items),
            ],
            SiteType.DOCS: [
                ("doc_sections", self._strategy_doc_sections),
            ],
            SiteType.SEARCH: [
                ("search_results", self._strategy_search_results),
            ],
            SiteType.GENERIC: [],
        }

        # Universal fallbacks
        fallbacks = [
            ("heading_links", self._strategy_heading_links),
            ("list_items", self._strategy_list_items),
            ("link_clusters", self._strategy_link_clusters),
        ]

        return type_strategies.get(site_type, []) + fallbacks

    def _score_results(self, results: List[ExtractedContent], site_type: SiteType) -> float:
        """Score extraction quality."""
        if not results:
            return 0.0

        score = 0.0
        for r in results:
            if r.url and len(r.url) > 10:
                score += 0.3
            if r.title and len(r.title) > 10:
                score += 0.3
            if site_type == SiteType.COMMERCE and r.price:
                score += 0.2
            if site_type == SiteType.FORUM and (r.author or r.date):
                score += 0.2
            if r.snippet and len(r.snippet) > 20:
                score += 0.1

        return score / len(results)

    def _get_fallback_nav_filter_js(self) -> str:
        """Get fallback nav filter JS when calibrator not available."""
        return """
        function isNavElement(el) {
            const rect = el.getBoundingClientRect();
            if (rect.top < 100) return true;

            let parent = el;
            while (parent) {
                const tag = parent.tagName?.toLowerCase();
                if (tag === 'nav' || tag === 'header' || tag === 'footer') return true;
                const role = parent.getAttribute?.('role');
                if (role === 'navigation' || role === 'banner' || role === 'contentinfo') return true;
                const cls = (parent.className || '').toLowerCase();
                if (/\\b(nav|menu|header|footer|sidebar|promo-?bar)\\b/.test(cls)) return true;
                parent = parent.parentElement;
            }
            return false;
        }
        """

    # =========================================================================
    # EXTRACTION STRATEGIES
    # =========================================================================

    async def _strategy_price_first(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """Commerce: Find prices, walk UP to find product cards."""
        # Build JS with calibrated nav filter and learned product patterns
        js_code = nav_filter_js + product_patterns_js + """
        (function(max) {
            const results = [], seen = new Set();
            const priceRe = /\\$[\\d,]+\\.?\\d{0,2}/;

            // Use learned productUrlRe if available, otherwise fallback
            if (typeof productUrlRe === 'undefined') {
                var productUrlRe = /\\/product[s]?\\/|\\/p\\/|\\/dp\\/|\\/ip\\/|\\/item[s]?\\/|\\/pd\\/|\\/n82e|\\/i\\/|[?&]skuId=|[?&]item=|[?&]product=|\\.p\\?|\\.p$/i;
            }

            // Nav/promotional words to filter out (fallback)
            const navWords = [
                'today\\'s deals', 'best deals', 'cyber monday', 'black friday', 'email deals',
                'sign up', 'sign in', 'log in', 'create account', 'view all', 'see all',
                'clearance', 'sale items', 'shop now', 'learn more', 'quick view',
                'cart', 'wishlist', 'my account', 'order status', 'track order',
                'customer service', 'help center', 'gift cards', 'registry',
                'credit card', 'financing', 'free shipping', 'price match',
                'weekly ad', 'store finder', 'store pickup', 'curbside',
                'get it by', 'shipping info', 'return policy', 'contact us'
            ];

            // Find text nodes with prices
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
                acceptNode: n => priceRe.test(n.textContent?.trim() || '') &&
                                 n.textContent.trim().length < 20 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP
            });

            const priceNodes = [];
            while (walker.nextNode()) priceNodes.push(walker.currentNode);

            for (const pn of priceNodes) {
                if (results.length >= max) break;

                // Skip prices in nav elements (uses calibrated isNavElement if available)
                if (typeof isNavElement === 'function' && isNavElement(pn.parentElement)) continue;

                // Walk up to find card
                let el = pn.parentElement, card = null;
                for (let i = 0; i < 10 && el; i++) {
                    // Skip if we hit a nav container
                    const tag = el.tagName?.toLowerCase();
                    if (tag === 'nav' || tag === 'header' || tag === 'footer') break;

                    const links = el.querySelectorAll('a[href]');
                    const hasProductLink = [...links].some(a => productUrlRe.test(a.href || ''));
                    const hasTitle = el.querySelector('h1,h2,h3,h4,[class*="title"],[class*="name"]');
                    if (hasProductLink && hasTitle) { card = el; break; }
                    el = el.parentElement;
                }
                if (!card) continue;

                // Extract
                const price = pn.textContent.match(priceRe)?.[0] || '';
                let prodUrl = '', title = '';

                for (const link of card.querySelectorAll('a[href]')) {
                    const href = link.href || '';
                    if (!href || href.includes('javascript:')) continue;
                    const isProd = productUrlRe.test(href);
                    if (isProd || !prodUrl) {
                        prodUrl = href;
                        title = link.textContent?.trim() || '';
                        if (title.length < 15) {
                            const h = card.querySelector('h1,h2,h3,h4,[class*="title"],[class*="name"]');
                            if (h) title = h.textContent?.trim() || '';
                        }
                        if (isProd) break;
                    }
                }

                // Must have product URL pattern OR very long title (real product names are 20+ chars)
                const hasProductUrl = productUrlRe.test(prodUrl);
                if (!hasProductUrl && title.length < 25) continue;

                // Filter out nav/promotional links
                if (!prodUrl || seen.has(prodUrl)) continue;
                if (title.length < 15) continue;
                const tl = title.toLowerCase();
                if (navWords.some(w => tl.includes(w))) continue;
                // Also filter titles that are too short or look like nav (2-3 short words)
                const wordCount = title.split(/\\s+/).length;
                if (wordCount < 3 && title.length < 25) continue;

                seen.add(prodUrl);
                results.push({ url: prodUrl, title: title.slice(0, 200), price });
            }
            return results;
        })
        """
        data = await page.evaluate(js_code, max_items)

        return [ExtractedContent(url=d['url'], title=d['title'], price=d.get('price'),
                                 site_type='commerce', extraction_method='price_first') for d in (data or [])]

    async def _strategy_product_cards(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """Commerce: Find product cards by data attributes."""
        js_code = nav_filter_js + product_patterns_js + """
        (function(max) {
            const results = [], seen = new Set();
            // Use learned cardSelectors if available, otherwise fallback
            const selectors = (typeof cardSelectors !== 'undefined' && cardSelectors.length > 0) ? cardSelectors :
                ['[data-asin]', '[data-product-id]', '[data-sku]', '[data-sku-id]', '[class*="product-card"]',
                 '[class*="product-item"]', '[data-testid*="product"]', '[class*="sku-item"]', '.item-cell'];

            // Nav/promotional words to filter out
            const navWords = [
                'today\\'s deals', 'best deals', 'cyber monday', 'black friday', 'email deals',
                'sign up', 'sign in', 'view all', 'see all', 'clearance', 'shop now',
                'quick view', 'cart', 'wishlist', 'my account', 'gift cards'
            ];

            // Skip elements inside nav/header/footer
            function isInNavContainer(el) {
                let parent = el;
                while (parent) {
                    const tag = parent.tagName?.toLowerCase();
                    if (tag === 'nav' || tag === 'header' || tag === 'footer') return true;
                    const role = parent.getAttribute?.('role');
                    if (role === 'navigation' || role === 'banner') return true;
                    parent = parent.parentElement;
                }
                return false;
            }

            for (const sel of selectors) {
                for (const el of document.querySelectorAll(sel)) {
                    if (results.length >= max) break;
                    // Use calibrated nav filter if available
                    if (typeof isNavElement === 'function' && isNavElement(el)) continue;
                    if (isInNavContainer(el)) continue;

                    const link = el.querySelector('a[href]');
                    if (!link) continue;
                    const href = link.href || '';
                    if (!href || seen.has(href)) continue;

                    const titleEl = el.querySelector('h1,h2,h3,h4,[class*="title"],[class*="name"]');
                    const priceEl = el.querySelector('[class*="price"]');
                    const title = (titleEl?.textContent || link.textContent || '').trim();
                    if (title.length < 15) continue;

                    // Filter nav/promo titles
                    const tl = title.toLowerCase();
                    if (navWords.some(w => tl.includes(w))) continue;

                    seen.add(href);
                    results.push({
                        url: href,
                        title: title.slice(0, 200),
                        price: priceEl?.textContent?.match(/\\$[\\d,]+\\.?\\d{0,2}/)?.[0] || ''
                    });
                }
                if (results.length >= 3) break;
            }
            return results;
        })
        """
        data = await page.evaluate(js_code, max_items)

        return [ExtractedContent(url=d['url'], title=d['title'], price=d.get('price'),
                                 site_type='commerce', extraction_method='product_cards') for d in (data or [])]

    async def _strategy_timestamp_first(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """Forum: Find timestamps, walk UP to find posts."""
        data = await page.evaluate('''(max) => {
            const results = [], seen = new Set();
            const timeEls = document.querySelectorAll('time, [datetime], [class*="time"], [class*="date"], [class*="ago"]');

            for (const timeEl of timeEls) {
                if (results.length >= max) break;

                let el = timeEl.parentElement, post = null;
                for (let i = 0; i < 8 && el; i++) {
                    const hasLink = el.querySelector('a[href]');
                    const hasAuthor = el.querySelector('[class*="author"],[class*="user"],[href*="/u/"]');
                    if (hasLink && hasAuthor) { post = el; break; }
                    el = el.parentElement;
                }
                if (!post) continue;

                const link = post.querySelector('a[href]:not([href="#"])');
                const authorEl = post.querySelector('[class*="author"],[class*="user"],[href*="/u/"]');
                const titleEl = post.querySelector('h1,h2,h3,h4,[class*="title"]');

                const postUrl = link?.href || '';
                if (!postUrl || seen.has(postUrl)) continue;

                const title = (titleEl?.textContent || link?.textContent || '').trim();
                if (title.length < 5) continue;

                seen.add(postUrl);
                results.push({
                    url: postUrl,
                    title: title.slice(0, 200),
                    author: authorEl?.textContent?.trim().slice(0, 50) || '',
                    date: timeEl.textContent?.trim() || timeEl.getAttribute('datetime') || ''
                });
            }
            return results;
        }''', max_items)

        return [ExtractedContent(url=d['url'], title=d['title'], author=d.get('author'), date=d.get('date'),
                                 site_type='forum', extraction_method='timestamp_first') for d in (data or [])]

    async def _strategy_vote_first(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """Forum: Find vote buttons (Reddit), walk UP to find posts."""
        data = await page.evaluate('''(max) => {
            const results = [], seen = new Set();
            const voteEls = document.querySelectorAll('[class*="vote"],[class*="score"],[aria-label*="vote"]');

            for (const voteEl of voteEls) {
                if (results.length >= max) break;

                let el = voteEl.parentElement, post = null;
                for (let i = 0; i < 8 && el; i++) {
                    const link = el.querySelector('a[href*="/comments/"],a[href*="/post/"]');
                    if (link) { post = el; break; }
                    el = el.parentElement;
                }
                if (!post) continue;

                const link = post.querySelector('a[href*="/comments/"]') || post.querySelector('h1 a,h2 a,h3 a');
                if (!link) continue;

                const href = link.href || '';
                if (!href || seen.has(href)) continue;

                const title = link.textContent?.trim() || '';
                if (title.length < 5) continue;

                const authorEl = post.querySelector('[href*="/user/"],[href*="/u/"]');
                const scoreEl = post.querySelector('[class*="score"]');

                seen.add(href);
                results.push({
                    url: href,
                    title: title.slice(0, 200),
                    author: authorEl?.textContent?.trim().slice(0, 50) || '',
                    votes: parseInt(scoreEl?.textContent?.replace(/[^\\d-]/g, '') || '0') || 0
                });
            }
            return results;
        }''', max_items)

        return [ExtractedContent(url=d['url'], title=d['title'], author=d.get('author'), votes=d.get('votes'),
                                 site_type='forum', extraction_method='vote_first') for d in (data or [])]

    async def _strategy_post_containers(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """Forum: Find post/comment containers."""
        data = await page.evaluate('''(max) => {
            const results = [], seen = new Set();
            const sels = ['[class*="post"]','[class*="comment"]','[class*="thread"]','[class*="entry"]','article'];

            for (const sel of sels) {
                const els = document.querySelectorAll(sel);
                if (els.length < 3) continue;

                for (const el of els) {
                    if (results.length >= max) break;
                    const link = el.querySelector('a[href]:not([href="#"])');
                    if (!link) continue;

                    const href = link.href || '';
                    if (!href || seen.has(href)) continue;

                    const titleEl = el.querySelector('h1,h2,h3,h4,[class*="title"]');
                    const title = (titleEl?.textContent || link.textContent || '').trim();
                    if (title.length < 5) continue;

                    const timeEl = el.querySelector('time,[class*="time"],[class*="date"]');

                    seen.add(href);
                    results.push({
                        url: href,
                        title: title.slice(0, 200),
                        date: timeEl?.textContent?.trim() || ''
                    });
                }
                if (results.length >= 3) break;
            }
            return results;
        }''', max_items)

        return [ExtractedContent(url=d['url'], title=d['title'], date=d.get('date'),
                                 site_type='forum', extraction_method='post_containers') for d in (data or [])]

    async def _strategy_wiki_links(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """Wiki: Extract internal wiki links."""
        data = await page.evaluate('''(max) => {
            const results = [], seen = new Set();

            // Find content area links (not nav)
            const content = document.querySelector('#content, #mw-content-text, .mw-parser-output, main, article');
            if (!content) return results;

            const links = content.querySelectorAll('a[href*="/wiki/"]:not([href*="action="]):not([href*="Special:"])');

            for (const link of links) {
                if (results.length >= max) break;
                const href = link.href || '';
                if (!href || seen.has(href) || href.includes('#')) continue;

                const title = link.textContent?.trim() || '';
                if (title.length < 3) continue;

                seen.add(href);
                results.push({ url: href, title: title.slice(0, 200) });
            }
            return results;
        }''', max_items)

        return [ExtractedContent(url=d['url'], title=d['title'],
                                 site_type='wiki', extraction_method='wiki_links') for d in (data or [])]

    async def _strategy_article_cards(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """News: Find article cards."""
        data = await page.evaluate('''(max) => {
            const results = [], seen = new Set();
            const sels = ['article','[class*="article"]','[class*="story"]','[class*="post"]','[class*="card"]'];

            for (const sel of sels) {
                const els = document.querySelectorAll(sel);
                if (els.length < 3) continue;

                for (const el of els) {
                    if (results.length >= max) break;
                    const link = el.querySelector('a[href]');
                    if (!link) continue;

                    const href = link.href || '';
                    if (!href || seen.has(href) || href.includes('#')) continue;

                    const titleEl = el.querySelector('h1,h2,h3,h4,[class*="title"],[class*="headline"]');
                    const title = (titleEl?.textContent || link.textContent || '').trim();
                    if (title.length < 10) continue;

                    const authorEl = el.querySelector('[class*="author"],[class*="byline"]');
                    const timeEl = el.querySelector('time,[class*="time"],[class*="date"]');
                    const snippetEl = el.querySelector('p,[class*="excerpt"],[class*="summary"]');

                    seen.add(href);
                    results.push({
                        url: href,
                        title: title.slice(0, 200),
                        author: authorEl?.textContent?.trim().slice(0, 50) || '',
                        date: timeEl?.textContent?.trim() || '',
                        snippet: snippetEl?.textContent?.trim().slice(0, 200) || ''
                    });
                }
                if (results.length >= 3) break;
            }
            return results;
        }''', max_items)

        return [ExtractedContent(url=d['url'], title=d['title'], author=d.get('author'),
                                 date=d.get('date'), snippet=d.get('snippet'),
                                 site_type='news', extraction_method='article_cards') for d in (data or [])]

    async def _strategy_news_items(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """News: Hacker News style - find score/points, walk up."""
        data = await page.evaluate('''(max) => {
            const results = [], seen = new Set();

            // HN-specific: find titleline links
            const titleLinks = document.querySelectorAll('.titleline > a, .storylink, .athing a.storylink');

            for (const link of titleLinks) {
                if (results.length >= max) break;
                const href = link.href || '';
                if (!href || seen.has(href)) continue;

                const title = link.textContent?.trim() || '';
                if (title.length < 5) continue;

                // Find associated metadata
                const row = link.closest('tr, .athing');
                const nextRow = row?.nextElementSibling;
                const scoreEl = nextRow?.querySelector('.score');
                const userEl = nextRow?.querySelector('.hnuser, a[href*="user?"]');
                const ageEl = nextRow?.querySelector('.age');

                seen.add(href);
                results.push({
                    url: href,
                    title: title.slice(0, 200),
                    author: userEl?.textContent?.trim() || '',
                    date: ageEl?.textContent?.trim() || '',
                    votes: parseInt(scoreEl?.textContent?.replace(/[^\\d]/g, '') || '0') || 0
                });
            }

            // Fallback: general news items
            if (results.length < 3) {
                const items = document.querySelectorAll('[class*="item"], [class*="story"], li');
                for (const item of items) {
                    if (results.length >= max) break;
                    const link = item.querySelector('a[href^="http"]');
                    if (!link) continue;

                    const href = link.href || '';
                    if (!href || seen.has(href)) continue;

                    const title = link.textContent?.trim() || '';
                    if (title.length < 10) continue;

                    seen.add(href);
                    results.push({ url: href, title: title.slice(0, 200) });
                }
            }

            return results;
        }''', max_items)

        return [ExtractedContent(url=d['url'], title=d['title'], author=d.get('author'),
                                 date=d.get('date'), votes=d.get('votes'),
                                 site_type='news', extraction_method='news_items') for d in (data or [])]

    async def _strategy_doc_sections(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """Docs: Extract documentation sections."""
        data = await page.evaluate('''(max) => {
            const results = [], seen = new Set();
            const headings = document.querySelectorAll('h1[id], h2[id], h3[id], h1 a[href^="#"], h2 a[href^="#"], h3 a[href^="#"]');

            for (const h of headings) {
                if (results.length >= max) break;

                const id = h.id || h.querySelector('a')?.getAttribute('href')?.slice(1);
                if (!id) continue;

                const title = h.textContent?.trim();
                if (!title || title.length < 3) continue;

                const sectionUrl = window.location.href.split('#')[0] + '#' + id;
                if (seen.has(sectionUrl)) continue;

                // Get snippet from next paragraph
                let snippet = '';
                let next = h.nextElementSibling;
                while (next && !next.matches('h1,h2,h3,h4') && snippet.length < 200) {
                    if (next.matches('p')) snippet += next.textContent?.trim() + ' ';
                    next = next.nextElementSibling;
                }

                seen.add(sectionUrl);
                results.push({
                    url: sectionUrl,
                    title: title.slice(0, 200),
                    snippet: snippet.trim().slice(0, 200)
                });
            }
            return results;
        }''', max_items)

        return [ExtractedContent(url=d['url'], title=d['title'], snippet=d.get('snippet'),
                                 site_type='docs', extraction_method='doc_sections') for d in (data or [])]

    async def _strategy_search_results(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """Search: Extract search engine results."""
        data = await page.evaluate('''(max) => {
            const results = [], seen = new Set();

            // Find h3 elements (common in search results)
            const h3s = document.querySelectorAll('h3');

            for (const h3 of h3s) {
                if (results.length >= max) break;

                let anchor = h3.closest('a') || h3.parentElement?.querySelector('a') ||
                            h3.parentElement?.parentElement?.querySelector('a');
                if (!anchor) continue;

                const href = anchor.href || '';
                if (!href || seen.has(href) || href.includes('google.com/search')) continue;

                const title = h3.textContent?.trim();
                if (!title || title.length < 5) continue;

                // Find snippet
                let snippet = '';
                const parent = h3.closest('div');
                if (parent) {
                    const snippetEl = parent.querySelector('[class*="snippet"], .VwiC3b, [data-sncf]');
                    snippet = snippetEl?.textContent?.trim().slice(0, 200) || '';
                }

                seen.add(href);
                results.push({ url: href, title: title.slice(0, 200), snippet });
            }
            return results;
        }''', max_items)

        return [ExtractedContent(url=d['url'], title=d['title'], snippet=d.get('snippet'),
                                 site_type='search', extraction_method='search_results') for d in (data or [])]

    # =========================================================================
    # FALLBACK STRATEGIES (work on any site)
    # =========================================================================

    async def _strategy_heading_links(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """Generic: Find headings with links (excluding navigation)."""
        data = await page.evaluate('''(max) => {
            const results = [], seen = new Set();

            // Check if in navigation
            function isInNav(el) {
                let parent = el;
                while (parent) {
                    const tag = parent.tagName?.toLowerCase();
                    if (tag === 'nav' || tag === 'header' || tag === 'footer') return true;
                    const role = parent.getAttribute?.('role');
                    if (role === 'navigation' || role === 'banner') return true;
                    parent = parent.parentElement;
                }
                return false;
            }

            const headings = document.querySelectorAll('h1 a, h2 a, h3 a, h4 a, a h1, a h2, a h3, a h4');

            for (const el of headings) {
                if (results.length >= max) break;
                if (isInNav(el)) continue;

                const link = el.tagName === 'A' ? el : el.closest('a');
                if (!link) continue;

                const href = link.href || '';
                if (!href || href === '#' || seen.has(href) || href.includes('javascript:')) continue;

                const heading = el.tagName.startsWith('H') ? el : el.querySelector('h1,h2,h3,h4');
                const title = (heading?.textContent || link.textContent || '').trim();
                if (title.length < 10) continue;  // Increased minimum

                seen.add(href);
                results.push({ url: href, title: title.slice(0, 200) });
            }
            return results;
        }''', max_items)

        return [ExtractedContent(url=d['url'], title=d['title'],
                                 site_type='generic', extraction_method='heading_links') for d in (data or [])]

    async def _strategy_list_items(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """Generic: Extract from lists (excluding navigation)."""
        data = await page.evaluate('''(max) => {
            const results = [], seen = new Set();

            // Nav/promotional words to filter
            const navWords = [
                'sign in', 'sign up', 'log in', 'cart', 'wishlist', 'account',
                'help', 'contact', 'about us', 'careers', 'press', 'privacy',
                'terms', 'shipping', 'returns', 'faq', 'support', 'store locator',
                'gift card', 'credit card', 'newsletter', 'subscribe'
            ];

            // Check if list is in navigation
            function isNavList(list) {
                let parent = list;
                while (parent) {
                    const tag = parent.tagName?.toLowerCase();
                    if (tag === 'nav' || tag === 'header' || tag === 'footer') return true;
                    const role = parent.getAttribute?.('role');
                    if (role === 'navigation' || role === 'banner' || role === 'contentinfo') return true;
                    const cls = parent.className?.toLowerCase() || '';
                    if (/\\b(nav|menu|sidebar|footer|header)\\b/.test(cls)) return true;
                    const id = parent.id?.toLowerCase() || '';
                    if (/\\b(nav|menu|sidebar|footer|header)\\b/.test(id)) return true;
                    parent = parent.parentElement;
                }
                return false;
            }

            for (const list of document.querySelectorAll('ul, ol')) {
                // Skip nav lists
                if (isNavList(list)) continue;

                const items = list.querySelectorAll('li');
                if (items.length < 3) continue;

                for (const item of items) {
                    if (results.length >= max) break;

                    const link = item.querySelector('a[href]');
                    if (!link) continue;

                    const href = link.href || '';
                    if (!href || href === '#' || seen.has(href)) continue;

                    const title = link.textContent?.trim() || '';
                    if (title.length < 10) continue;  // Increased minimum

                    // Filter nav/promo titles
                    const tl = title.toLowerCase();
                    if (navWords.some(w => tl.includes(w))) continue;

                    seen.add(href);
                    results.push({ url: href, title: title.slice(0, 200) });
                }
            }
            return results;
        }''', max_items)

        return [ExtractedContent(url=d['url'], title=d['title'],
                                 site_type='generic', extraction_method='list_items') for d in (data or [])]

    async def _strategy_link_clusters(self, page: 'Page', url: str, max_items: int, nav_filter_js: str = "", product_patterns_js: str = "") -> List[ExtractedContent]:
        """Generic: Find clusters of related links (excluding navigation)."""
        data = await page.evaluate('''(max) => {
            const results = [], seen = new Set();

            // Check if in navigation
            function isInNav(el) {
                let parent = el;
                while (parent) {
                    const tag = parent.tagName?.toLowerCase();
                    if (tag === 'nav' || tag === 'header' || tag === 'footer') return true;
                    const role = parent.getAttribute?.('role');
                    if (role === 'navigation' || role === 'banner' || role === 'contentinfo') return true;
                    const cls = parent.className?.toLowerCase() || '';
                    if (/\\b(nav|menu|sidebar|footer)\\b/.test(cls)) return true;
                    parent = parent.parentElement;
                }
                return false;
            }

            const containers = document.querySelectorAll('li, article, [class*="item"], [class*="card"], [class*="entry"]');

            for (const container of containers) {
                if (results.length >= max) break;
                if (isInNav(container)) continue;

                const links = container.querySelectorAll('a[href]');
                let primaryLink = null;

                for (const link of links) {
                    const href = link.href || '';
                    if (!href || href === '#' || href.includes('javascript:')) continue;
                    if (link.textContent?.trim().length > 15) {  // Increased minimum
                        primaryLink = link;
                        break;
                    }
                }
                if (!primaryLink) continue;

                const href = primaryLink.href;
                if (seen.has(href)) continue;

                const title = primaryLink.textContent?.trim() || '';
                if (title.length < 10) continue;  // Increased minimum

                seen.add(href);
                results.push({ url: href, title: title.slice(0, 200) });
            }
            return results;
        }''', max_items)

        return [ExtractedContent(url=d['url'], title=d['title'],
                                 site_type='generic', extraction_method='link_clusters') for d in (data or [])]


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_extractor: Optional[UnifiedWebExtractor] = None

def get_unified_extractor() -> UnifiedWebExtractor:
    """Get singleton extractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = UnifiedWebExtractor()
    return _extractor
