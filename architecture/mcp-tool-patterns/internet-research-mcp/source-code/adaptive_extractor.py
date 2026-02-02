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
AdaptiveContentExtractor - Automated content extraction for ANY website type.

This system uses an "inside-out" approach with site-type-aware strategies:
1. Detect site type (commerce, forum, wiki, news, docs, generic)
2. Select appropriate anchor patterns for that site type
3. Find anchors in DOM, walk UP to find content containers
4. Extract structured data from containers
5. Learn and cache winning patterns per domain

Works without calibration on any website by using universal patterns.
"""

import warnings
warnings.warn(
    "adaptive_extractor is deprecated, use smart_extractor instead",
    DeprecationWarning,
    stacklevel=2
)

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


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
class ExtractedItem:
    """Universal container for extracted content."""
    url: str
    title: str
    site_type: str
    source_strategy: str

    # Optional fields depending on site type
    price: Optional[str] = None           # Commerce
    author: Optional[str] = None          # Forum, News
    date: Optional[str] = None            # Forum, News, Wiki
    snippet: Optional[str] = None         # Generic, Search
    image_url: Optional[str] = None       # Commerce, News
    replies: Optional[int] = None         # Forum
    votes: Optional[int] = None           # Forum (Reddit-style)
    references: Optional[List[str]] = None  # Wiki
    code_block: Optional[str] = None      # Docs

    confidence: float = 0.8

    def to_dict(self) -> Dict:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class LearnedPattern:
    """Cached pattern that worked for a domain."""
    domain: str
    site_type: str
    best_strategy: str
    success_count: int = 0
    fail_count: int = 0
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    avg_items_extracted: float = 0.0

    # Strategy-specific hints learned from the page
    hints: Dict[str, Any] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    @property
    def needs_relearning(self) -> bool:
        """Check if pattern should be relearned."""
        if self.success_count + self.fail_count < 3:
            return False  # Not enough data
        return self.success_rate < 0.5


class PatternCache:
    """Persistent cache for learned extraction patterns."""

    def __init__(self, cache_path: str = "panda_system_docs/schemas/learned_patterns.jsonl"):
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._patterns: Dict[str, LearnedPattern] = {}
        self._load_cache()

    def _load_cache(self):
        """Load patterns from disk."""
        if not self.cache_path.exists():
            return

        try:
            with open(self.cache_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    pattern = LearnedPattern(
                        domain=data["domain"],
                        site_type=data["site_type"],
                        best_strategy=data["best_strategy"],
                        success_count=data.get("success_count", 0),
                        fail_count=data.get("fail_count", 0),
                        last_success=data.get("last_success"),
                        last_failure=data.get("last_failure"),
                        avg_items_extracted=data.get("avg_items_extracted", 0.0),
                        hints=data.get("hints", {})
                    )
                    self._patterns[pattern.domain] = pattern
            logger.info(f"[PatternCache] Loaded {len(self._patterns)} patterns")
        except Exception as e:
            logger.error(f"[PatternCache] Load error: {e}")

    def _save_cache(self):
        """Save all patterns to disk."""
        try:
            with open(self.cache_path, 'w') as f:
                for pattern in self._patterns.values():
                    data = {
                        "domain": pattern.domain,
                        "site_type": pattern.site_type,
                        "best_strategy": pattern.best_strategy,
                        "success_count": pattern.success_count,
                        "fail_count": pattern.fail_count,
                        "last_success": pattern.last_success,
                        "last_failure": pattern.last_failure,
                        "avg_items_extracted": pattern.avg_items_extracted,
                        "hints": pattern.hints
                    }
                    f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"[PatternCache] Save error: {e}")

    def get(self, domain: str) -> Optional[LearnedPattern]:
        """Get cached pattern for domain."""
        return self._patterns.get(domain)

    def record_success(self, domain: str, site_type: str, strategy: str,
                       items_count: int, hints: Dict = None):
        """Record a successful extraction."""
        now = datetime.now(timezone.utc).isoformat()

        if domain in self._patterns:
            pattern = self._patterns[domain]
            pattern.success_count += 1
            pattern.last_success = now
            # Update average
            total = pattern.success_count
            pattern.avg_items_extracted = (
                (pattern.avg_items_extracted * (total - 1) + items_count) / total
            )
            if hints:
                pattern.hints.update(hints)
        else:
            pattern = LearnedPattern(
                domain=domain,
                site_type=site_type,
                best_strategy=strategy,
                success_count=1,
                last_success=now,
                avg_items_extracted=float(items_count),
                hints=hints or {}
            )
            self._patterns[domain] = pattern

        self._save_cache()
        logger.info(f"[PatternCache] Recorded success for {domain}: {strategy} ({items_count} items)")

    def record_failure(self, domain: str, site_type: str, strategy: str):
        """Record a failed extraction."""
        now = datetime.now(timezone.utc).isoformat()

        if domain in self._patterns:
            pattern = self._patterns[domain]
            pattern.fail_count += 1
            pattern.last_failure = now
        else:
            pattern = LearnedPattern(
                domain=domain,
                site_type=site_type,
                best_strategy=strategy,
                fail_count=1,
                last_failure=now
            )
            self._patterns[domain] = pattern

        self._save_cache()
        logger.info(f"[PatternCache] Recorded failure for {domain}: {strategy}")

    def clear_pattern(self, domain: str):
        """Clear pattern for domain (for relearning)."""
        if domain in self._patterns:
            del self._patterns[domain]
            self._save_cache()
            logger.info(f"[PatternCache] Cleared pattern for {domain}")


# Global pattern cache
_pattern_cache: Optional[PatternCache] = None


def get_pattern_cache() -> PatternCache:
    """Get singleton pattern cache."""
    global _pattern_cache
    if _pattern_cache is None:
        _pattern_cache = PatternCache()
    return _pattern_cache


class AdaptiveContentExtractor:
    """
    Extracts structured content from any website using adaptive strategies.

    The system:
    1. Detects site type from URL/content patterns
    2. Uses site-type-specific anchor patterns
    3. Walks UP the DOM from anchors to find containers
    4. Extracts structured data
    5. Learns what works per domain
    """

    # TODO(LLM-FIRST): Site type detection should use LLM classification, not hardcoded patterns.
    # This is a duplicate of the same pattern in unified_web_extractor.py - both violate
    # the LLM-first design principle.
    #
    # INSTEAD OF: Hardcoded domain patterns (amazon, ebay, reddit, etc.)
    # SHOULD BE: Let the LLM classify site type based on page content analysis.
    #
    # Recommended approach:
    # 1. Remove domain-specific patterns entirely
    # 2. Keep generic URL path patterns (they're structural, not site-specific)
    # 3. Use LLM + page content for final classification
    #
    # See: panda_system_docs/architecture/LLM-ROLES/CONTEXT_DISCIPLINE.md
    SITE_TYPE_URL_PATTERNS = {
        SiteType.COMMERCE: [
            # Generic path patterns are OK - they're structural
            r'/shop', r'/store', r'/product', r'/buy', r'/cart',
            # TODO(LLM-FIRST): REMOVE domain-specific patterns below
            r'amazon\.', r'ebay\.', r'walmart\.', r'bestbuy\.', r'newegg\.',
            r'etsy\.', r'aliexpress\.', r'shopify',
        ],
        SiteType.FORUM: [
            r'/forum', r'/thread', r'/discussion', r'/community', r'/topic',
            # TODO(LLM-FIRST): REMOVE domain-specific patterns
            r'reddit\.com', r'discourse\.', r'phpbb', r'vbulletin',
            r'stackexchange\.', r'stackoverflow\.', r'/r/', r'/comments/',
        ],
        SiteType.WIKI: [
            # TODO(LLM-FIRST): REMOVE domain-specific patterns
            r'wikipedia\.', r'/wiki/', r'fandom\.com',
            r'wikia\.', r'mediawiki', r'/w/',
        ],
        SiteType.NEWS: [
            r'/news', r'/article', r'/story', r'/blog', r'/post',
            # TODO(LLM-FIRST): REMOVE domain-specific patterns
            r'cnn\.', r'bbc\.', r'nytimes\.', r'theguardian\.',
            r'techcrunch\.', r'verge\.', r'wired\.', r'arstechnica\.',
        ],
        SiteType.DOCS: [
            r'/docs', r'/documentation', r'/api', r'/reference', r'/guide',
            # TODO(LLM-FIRST): REMOVE domain-specific patterns
            r'readthedocs\.', r'gitbook\.', r'swagger\.', r'/man/',
        ],
        SiteType.SEARCH: [
            # Search engine detection - OK for extraction strategy selection
            r'google\.com/search', r'bing\.com/search', r'duckduckgo\.com',
            r'search\.yahoo\.', r'/search\?', r'[?&]q=',
        ],
    }

    # Content signals are more acceptable than domain patterns because they
    # analyze what's ON the page rather than assuming by domain name.
    # However, an LLM could still do this better with full context.
    SITE_TYPE_SIGNALS = {
        SiteType.COMMERCE: ['add to cart', 'buy now', 'price', 'in stock', 'out of stock', 'shipping'],
        SiteType.FORUM: ['reply', 'post', 'thread', 'joined', 'member since', 'posts:', 'upvote', 'downvote'],
        SiteType.WIKI: ['[edit]', 'references', 'citation', 'see also', 'external links', 'categories'],
        SiteType.NEWS: ['by ', 'published', 'updated', 'read more', 'min read', 'comments', 'share'],
        SiteType.DOCS: ['api', 'endpoint', 'parameter', 'returns', 'example', 'code', 'syntax'],
        SiteType.SEARCH: ['results', 'showing', 'pages', 'next', 'previous', 'search results'],
    }

    def __init__(self):
        self.pattern_cache = get_pattern_cache()

    async def detect_site_type(self, page: 'Page', url: str) -> SiteType:
        """Auto-detect what type of site this is."""
        url_lower = url.lower()

        # Check URL patterns first (fast)
        for site_type, patterns in self.SITE_TYPE_URL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, url_lower):
                    logger.info(f"[SiteDetector] Detected {site_type.value} from URL: {pattern}")
                    return site_type

        # Check page content signals (slower but more accurate)
        try:
            page_text = await page.evaluate('''() => {
                return document.body?.innerText?.toLowerCase().substring(0, 5000) || '';
            }''')

            scores = {st: 0 for st in SiteType}
            for site_type, signals in self.SITE_TYPE_SIGNALS.items():
                for signal in signals:
                    if signal in page_text:
                        scores[site_type] += 1

            # Get highest scoring type
            best_type = max(scores, key=scores.get)
            if scores[best_type] >= 2:
                logger.info(f"[SiteDetector] Detected {best_type.value} from signals (score={scores[best_type]})")
                return best_type
        except Exception as e:
            logger.warning(f"[SiteDetector] Content detection error: {e}")

        logger.info("[SiteDetector] Falling back to GENERIC site type")
        return SiteType.GENERIC

    async def extract(self, page: 'Page', url: str,
                      site_type: SiteType = None,
                      max_items: int = 20) -> List[ExtractedItem]:
        """
        Extract content from the page.

        Args:
            page: Playwright page object
            url: Current URL
            site_type: Optional site type override (auto-detected if not provided)
            max_items: Maximum items to extract

        Returns:
            List of ExtractedItem objects
        """
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace('www.', '')

        # Check for cached pattern
        cached_pattern = self.pattern_cache.get(domain)
        if cached_pattern and not cached_pattern.needs_relearning:
            logger.info(f"[Extractor] Using cached pattern for {domain}: {cached_pattern.best_strategy}")
            site_type = SiteType(cached_pattern.site_type)

        # Auto-detect site type if not provided
        if site_type is None:
            site_type = await self.detect_site_type(page, url)

        logger.info(f"[Extractor] Extracting from {domain} as {site_type.value}")

        # Try strategies in order of likelihood for this site type
        strategies = self._get_strategies_for_type(site_type)

        best_results = []
        best_strategy = None

        for strategy_name, strategy_func in strategies:
            try:
                results = await strategy_func(page, url, max_items)

                # Score the results
                score = self._score_results(results, site_type)

                if len(results) > len(best_results) or (
                    len(results) == len(best_results) and score > self._score_results(best_results, site_type)
                ):
                    best_results = results
                    best_strategy = strategy_name

                # If we got good results, stop trying more strategies
                if len(results) >= 3 and score >= 0.6:
                    logger.info(f"[Extractor] Strategy '{strategy_name}' found {len(results)} items (score={score:.2f})")
                    break

            except Exception as e:
                logger.warning(f"[Extractor] Strategy '{strategy_name}' failed: {e}")
                continue

        # Record results in cache
        if best_results and len(best_results) >= 3:
            self.pattern_cache.record_success(
                domain=domain,
                site_type=site_type.value,
                strategy=best_strategy,
                items_count=len(best_results)
            )
        elif best_strategy:
            self.pattern_cache.record_failure(
                domain=domain,
                site_type=site_type.value,
                strategy=best_strategy
            )

        logger.info(f"[Extractor] Final: {len(best_results)} items via '{best_strategy}'")
        return best_results

    def _get_strategies_for_type(self, site_type: SiteType) -> List[tuple]:
        """Get ordered list of strategies for a site type."""
        # Common strategies available for all types
        common = [
            ("heading_first", self._extract_heading_first),
            ("link_cluster", self._extract_link_clusters),
            ("list_items", self._extract_list_items),
        ]

        type_specific = {
            SiteType.COMMERCE: [
                ("price_first", self._extract_price_first),
                ("product_data_attr", self._extract_product_data_attrs),
            ],
            SiteType.FORUM: [
                ("timestamp_first", self._extract_timestamp_first),
                ("post_container", self._extract_post_containers),
                ("vote_first", self._extract_vote_first),
            ],
            SiteType.WIKI: [
                ("wiki_section", self._extract_wiki_sections),
                ("reference_first", self._extract_references),
            ],
            SiteType.NEWS: [
                ("article_card", self._extract_article_cards),
                ("date_first", self._extract_date_first),
            ],
            SiteType.DOCS: [
                ("section_header", self._extract_section_headers),
                ("code_block", self._extract_code_blocks),
            ],
            SiteType.SEARCH: [
                ("search_result", self._extract_search_results),
            ],
            SiteType.GENERIC: [],
        }

        # Type-specific first, then common fallbacks
        return type_specific.get(site_type, []) + common

    def _score_results(self, results: List[ExtractedItem], site_type: SiteType) -> float:
        """Score extraction results quality."""
        if not results:
            return 0.0

        score = 0.0

        for item in results:
            # Base score for having URL and title
            if item.url and len(item.url) > 10:
                score += 0.3
            if item.title and len(item.title) > 10:
                score += 0.3

            # Bonus for type-specific fields
            if site_type == SiteType.COMMERCE and item.price:
                score += 0.2
            if site_type == SiteType.FORUM and (item.author or item.date):
                score += 0.2
            if site_type == SiteType.NEWS and item.date:
                score += 0.2
            if item.snippet and len(item.snippet) > 20:
                score += 0.1

        # Normalize by count
        return score / len(results)

    # =========================================================================
    # COMMERCE STRATEGIES
    # =========================================================================

    async def _extract_price_first(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Find prices, walk UP to find product cards."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();
            const pricePattern = /\\$[\\d,]+\\.?\\d{0,2}/;

            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT,
                { acceptNode: (node) => pricePattern.test(node.textContent?.trim() || '') &&
                                        node.textContent.trim().length < 20
                                        ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP }
            );

            const priceNodes = [];
            while (walker.nextNode()) priceNodes.push(walker.currentNode);

            for (const priceNode of priceNodes) {
                if (results.length >= maxItems) break;

                let element = priceNode.parentElement;
                let card = null;

                for (let i = 0; i < 10 && element; i++) {
                    const links = element.querySelectorAll('a[href]');
                    const hasProductLink = Array.from(links).some(a => {
                        const href = a.href || '';
                        return href.includes('/product') || href.includes('/p/') ||
                               href.includes('/dp/') || href.includes('/ip/') ||
                               href.includes('/item') || href.includes('/pd/') ||
                               href.includes('/n82e');
                    });
                    const hasTitle = element.querySelector('h1,h2,h3,h4,[class*="title"],[class*="name"]');

                    if (hasProductLink && hasTitle) { card = element; break; }
                    element = element.parentElement;
                }

                if (!card) continue;

                const priceMatch = priceNode.textContent.match(/\\$[\\d,]+\\.?\\d{0,2}/);
                const price = priceMatch ? priceMatch[0] : '';

                let productUrl = '', title = '';
                for (const link of card.querySelectorAll('a[href]')) {
                    const href = link.href || '';
                    if (!href || href.includes('javascript:')) continue;
                    const isProduct = href.includes('/product') || href.includes('/p/') ||
                                     href.includes('/dp/') || href.includes('/ip/') ||
                                     href.includes('/n82e');
                    if (isProduct || !productUrl) {
                        productUrl = href;
                        title = link.textContent?.trim() || '';
                        if (title.length < 10) {
                            const h = card.querySelector('h1,h2,h3,h4,[class*="title"]');
                            if (h) title = h.textContent?.trim() || '';
                        }
                        if (isProduct) break;
                    }
                }

                if (!productUrl || seen.has(productUrl) || title.length < 10) continue;
                seen.add(productUrl);

                results.push({ url: productUrl, title: title.substring(0, 200), price, strategy: 'price_first' });
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'], price=r.get('price'),
            site_type='commerce', source_strategy='price_first'
        ) for r in (results or [])]

    async def _extract_product_data_attrs(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Find elements with product data attributes."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();

            const selectors = [
                '[data-product-id]', '[data-sku]', '[data-asin]', '[data-item-id]',
                '[data-testid*="product"]', '[data-component*="product"]',
                '[class*="product-card"]', '[class*="product-item"]'
            ];

            for (const selector of selectors) {
                const elements = document.querySelectorAll(selector);
                for (const el of elements) {
                    if (results.length >= maxItems) break;

                    const link = el.querySelector('a[href]') || el.closest('a');
                    if (!link) continue;

                    const href = link.href || '';
                    if (!href || seen.has(href)) continue;
                    seen.add(href);

                    const titleEl = el.querySelector('h1,h2,h3,h4,[class*="title"],[class*="name"]');
                    const priceEl = el.querySelector('[class*="price"]');

                    const title = (titleEl?.textContent || link.textContent || '').trim();
                    if (title.length < 10) continue;

                    results.push({
                        url: href,
                        title: title.substring(0, 200),
                        price: priceEl?.textContent?.match(/\\$[\\d,]+\\.?\\d{0,2}/)?.[0] || '',
                        strategy: 'product_data_attr'
                    });
                }
                if (results.length >= 3) break;
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'], price=r.get('price'),
            site_type='commerce', source_strategy='product_data_attr'
        ) for r in (results or [])]

    # =========================================================================
    # FORUM STRATEGIES
    # =========================================================================

    async def _extract_timestamp_first(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Find timestamps, walk UP to find forum posts."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();

            const timeElements = document.querySelectorAll(
                'time, [class*="time"], [class*="date"], [class*="posted"], [datetime], [class*="ago"]'
            );

            for (const timeEl of timeElements) {
                if (results.length >= maxItems) break;

                let element = timeEl.parentElement;
                let post = null;

                for (let i = 0; i < 8 && element; i++) {
                    const hasLink = element.querySelector('a[href]');
                    const hasAuthor = element.querySelector('[class*="author"], [class*="user"], [class*="member"], [class*="username"]');
                    const hasContent = element.querySelector('p, [class*="content"], [class*="body"], [class*="message"], [class*="text"]');

                    if (hasLink && (hasAuthor || hasContent)) { post = element; break; }
                    element = element.parentElement;
                }

                if (!post) continue;

                const link = post.querySelector('a[href]:not([href="#"])');
                const authorEl = post.querySelector('[class*="author"], [class*="user"], [class*="member"]');
                const titleEl = post.querySelector('h1,h2,h3,h4,[class*="title"],[class*="subject"]');
                const contentEl = post.querySelector('p, [class*="content"], [class*="body"]');

                const postUrl = link?.href || '';
                if (!postUrl || seen.has(postUrl)) continue;
                seen.add(postUrl);

                const title = (titleEl?.textContent || link?.textContent || '').trim();
                if (title.length < 5) continue;

                results.push({
                    url: postUrl,
                    title: title.substring(0, 200),
                    author: authorEl?.textContent?.trim().substring(0, 50) || '',
                    date: timeEl.textContent?.trim() || timeEl.getAttribute('datetime') || '',
                    snippet: contentEl?.textContent?.trim().substring(0, 300) || '',
                    strategy: 'timestamp_first'
                });
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'], author=r.get('author'),
            date=r.get('date'), snippet=r.get('snippet'),
            site_type='forum', source_strategy='timestamp_first'
        ) for r in (results or [])]

    async def _extract_post_containers(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Find forum post containers directly."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();

            const selectors = [
                '[class*="post"]', '[class*="comment"]', '[class*="thread"]',
                '[class*="topic"]', '[class*="entry"]', 'article'
            ];

            for (const selector of selectors) {
                const elements = document.querySelectorAll(selector);
                if (elements.length < 3) continue;

                for (const el of elements) {
                    if (results.length >= maxItems) break;

                    const link = el.querySelector('a[href]:not([href="#"])');
                    if (!link) continue;

                    const href = link.href || '';
                    if (!href || seen.has(href)) continue;
                    seen.add(href);

                    const titleEl = el.querySelector('h1,h2,h3,h4,[class*="title"]');
                    const title = (titleEl?.textContent || link.textContent || '').trim();
                    if (title.length < 5) continue;

                    const authorEl = el.querySelector('[class*="author"], [class*="user"]');
                    const timeEl = el.querySelector('time, [class*="time"], [class*="date"]');

                    results.push({
                        url: href,
                        title: title.substring(0, 200),
                        author: authorEl?.textContent?.trim().substring(0, 50) || '',
                        date: timeEl?.textContent?.trim() || '',
                        strategy: 'post_container'
                    });
                }
                if (results.length >= 3) break;
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'], author=r.get('author'), date=r.get('date'),
            site_type='forum', source_strategy='post_container'
        ) for r in (results or [])]

    async def _extract_vote_first(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Find vote buttons (Reddit-style), walk UP to find posts."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();

            // Find upvote/downvote elements
            const voteEls = document.querySelectorAll(
                '[class*="vote"], [class*="upvote"], [class*="score"], [aria-label*="vote"], [data-click-id*="vote"]'
            );

            for (const voteEl of voteEls) {
                if (results.length >= maxItems) break;

                let element = voteEl.parentElement;
                let post = null;

                for (let i = 0; i < 8 && element; i++) {
                    const hasLink = element.querySelector('a[href*="/comments/"], a[href*="/post/"], a[href*="/thread/"]');
                    if (hasLink) { post = element; break; }
                    element = element.parentElement;
                }

                if (!post) continue;

                const link = post.querySelector('a[href*="/comments/"], a[href*="/post/"]') ||
                            post.querySelector('h1 a, h2 a, h3 a');
                if (!link) continue;

                const href = link.href || '';
                if (!href || seen.has(href)) continue;
                seen.add(href);

                const title = link.textContent?.trim() || '';
                if (title.length < 5) continue;

                const authorEl = post.querySelector('[class*="author"], [href*="/user/"], [href*="/u/"]');
                const scoreEl = post.querySelector('[class*="score"], [class*="votes"]');

                results.push({
                    url: href,
                    title: title.substring(0, 200),
                    author: authorEl?.textContent?.trim().substring(0, 50) || '',
                    votes: parseInt(scoreEl?.textContent?.replace(/[^\\d-]/g, '') || '0') || 0,
                    strategy: 'vote_first'
                });
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'], author=r.get('author'),
            votes=r.get('votes'),
            site_type='forum', source_strategy='vote_first'
        ) for r in (results or [])]

    # =========================================================================
    # WIKI STRATEGIES
    # =========================================================================

    async def _extract_wiki_sections(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Extract wiki article sections."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();

            // Find section headings with edit links (Wikipedia pattern)
            const headings = document.querySelectorAll('h2, h3, h4');

            for (const heading of headings) {
                if (results.length >= maxItems) break;

                const editLink = heading.querySelector('[class*="edit"], a[href*="edit"]');
                const headingText = heading.textContent?.replace(/\\[edit\\]/gi, '').trim();

                if (!headingText || headingText.length < 3) continue;

                // Get the section content
                let content = '';
                let sibling = heading.nextElementSibling;
                while (sibling && !sibling.matches('h2, h3, h4')) {
                    if (sibling.matches('p')) {
                        content += sibling.textContent?.trim() + ' ';
                        if (content.length > 300) break;
                    }
                    sibling = sibling.nextElementSibling;
                }

                const sectionId = heading.id || headingText.toLowerCase().replace(/\\s+/g, '_');
                const sectionUrl = window.location.href.split('#')[0] + '#' + sectionId;

                if (seen.has(sectionUrl)) continue;
                seen.add(sectionUrl);

                results.push({
                    url: sectionUrl,
                    title: headingText.substring(0, 200),
                    snippet: content.trim().substring(0, 300),
                    strategy: 'wiki_section'
                });
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'], snippet=r.get('snippet'),
            site_type='wiki', source_strategy='wiki_section'
        ) for r in (results or [])]

    async def _extract_references(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Extract references from wiki pages."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();

            // Find reference links
            const refLinks = document.querySelectorAll(
                '.references a[href^="http"], .reflist a[href^="http"], [class*="citation"] a[href^="http"]'
            );

            for (const link of refLinks) {
                if (results.length >= maxItems) break;

                const href = link.href || '';
                if (!href || seen.has(href)) continue;
                seen.add(href);

                const title = link.textContent?.trim() || new URL(href).hostname;

                results.push({
                    url: href,
                    title: title.substring(0, 200),
                    strategy: 'reference'
                });
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'],
            site_type='wiki', source_strategy='reference'
        ) for r in (results or [])]

    # =========================================================================
    # NEWS STRATEGIES
    # =========================================================================

    async def _extract_article_cards(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Extract news article cards."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();

            const selectors = [
                'article', '[class*="article"]', '[class*="story"]', '[class*="post"]',
                '[class*="card"]', '[class*="item"]'
            ];

            for (const selector of selectors) {
                const elements = document.querySelectorAll(selector);
                if (elements.length < 3) continue;

                for (const el of elements) {
                    if (results.length >= maxItems) break;

                    const link = el.querySelector('a[href]');
                    if (!link) continue;

                    const href = link.href || '';
                    if (!href || seen.has(href) || href.includes('#')) continue;
                    seen.add(href);

                    const titleEl = el.querySelector('h1,h2,h3,h4,[class*="title"],[class*="headline"]');
                    const title = (titleEl?.textContent || link.textContent || '').trim();
                    if (title.length < 10) continue;

                    const authorEl = el.querySelector('[class*="author"], [class*="byline"], [rel="author"]');
                    const timeEl = el.querySelector('time, [class*="time"], [class*="date"]');
                    const snippetEl = el.querySelector('p, [class*="excerpt"], [class*="summary"], [class*="description"]');
                    const imgEl = el.querySelector('img');

                    results.push({
                        url: href,
                        title: title.substring(0, 200),
                        author: authorEl?.textContent?.trim().substring(0, 50) || '',
                        date: timeEl?.textContent?.trim() || timeEl?.getAttribute('datetime') || '',
                        snippet: snippetEl?.textContent?.trim().substring(0, 300) || '',
                        image_url: imgEl?.src || '',
                        strategy: 'article_card'
                    });
                }
                if (results.length >= 3) break;
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'], author=r.get('author'),
            date=r.get('date'), snippet=r.get('snippet'), image_url=r.get('image_url'),
            site_type='news', source_strategy='article_card'
        ) for r in (results or [])]

    async def _extract_date_first(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Find dates, walk UP to find article containers."""
        # Similar to timestamp_first but optimized for news sites
        return await self._extract_timestamp_first(page, url, max_items)

    # =========================================================================
    # DOCS STRATEGIES
    # =========================================================================

    async def _extract_section_headers(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Extract documentation section headers."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();

            const headings = document.querySelectorAll('h1, h2, h3, h4');

            for (const heading of headings) {
                if (results.length >= maxItems) break;

                const id = heading.id || heading.querySelector('a')?.getAttribute('href')?.replace('#', '');
                if (!id) continue;

                const title = heading.textContent?.trim();
                if (!title || title.length < 3) continue;

                const sectionUrl = window.location.href.split('#')[0] + '#' + id;
                if (seen.has(sectionUrl)) continue;
                seen.add(sectionUrl);

                // Get content preview
                let content = '';
                let sibling = heading.nextElementSibling;
                while (sibling && !sibling.matches('h1, h2, h3, h4') && content.length < 300) {
                    content += sibling.textContent?.trim() + ' ';
                    sibling = sibling.nextElementSibling;
                }

                results.push({
                    url: sectionUrl,
                    title: title.substring(0, 200),
                    snippet: content.trim().substring(0, 300),
                    strategy: 'section_header'
                });
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'], snippet=r.get('snippet'),
            site_type='docs', source_strategy='section_header'
        ) for r in (results or [])]

    async def _extract_code_blocks(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Extract code examples from documentation."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];

            const codeBlocks = document.querySelectorAll('pre code, pre, [class*="highlight"]');

            for (const block of codeBlocks) {
                if (results.length >= maxItems) break;

                const code = block.textContent?.trim();
                if (!code || code.length < 20) continue;

                // Find the heading above this code block
                let heading = block.closest('section, article, div')?.querySelector('h1, h2, h3, h4');
                const title = heading?.textContent?.trim() || 'Code Example';

                results.push({
                    url: window.location.href,
                    title: title.substring(0, 200),
                    code_block: code.substring(0, 500),
                    strategy: 'code_block'
                });
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'], code_block=r.get('code_block'),
            site_type='docs', source_strategy='code_block'
        ) for r in (results or [])]

    # =========================================================================
    # SEARCH STRATEGIES
    # =========================================================================

    async def _extract_search_results(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Extract search engine results."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();

            // Find all h3 elements (common in search results)
            const h3s = document.querySelectorAll('h3');

            for (const h3 of h3s) {
                if (results.length >= maxItems) break;

                // Find parent anchor or sibling anchor
                let anchor = h3.closest('a');
                if (!anchor) anchor = h3.parentElement?.querySelector('a');
                if (!anchor) anchor = h3.parentElement?.parentElement?.querySelector('a');

                if (!anchor) continue;

                const href = anchor.href || '';
                if (!href || seen.has(href) || href.includes('google.com/search')) continue;
                seen.add(href);

                const title = h3.textContent?.trim();
                if (!title || title.length < 5) continue;

                // Find snippet
                let snippet = '';
                const parent = h3.closest('div');
                if (parent) {
                    const snippetEl = parent.querySelector('[class*="snippet"], [class*="description"], .VwiC3b');
                    snippet = snippetEl?.textContent?.trim().substring(0, 300) || '';
                }

                results.push({
                    url: href,
                    title: title.substring(0, 200),
                    snippet,
                    strategy: 'search_result'
                });
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'], snippet=r.get('snippet'),
            site_type='search', source_strategy='search_result'
        ) for r in (results or [])]

    # =========================================================================
    # GENERIC STRATEGIES (fallbacks)
    # =========================================================================

    async def _extract_heading_first(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Find headings with links - universal fallback."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();

            const headings = document.querySelectorAll('h1 a, h2 a, h3 a, h4 a, a h1, a h2, a h3, a h4');

            for (const el of headings) {
                if (results.length >= maxItems) break;

                const link = el.tagName === 'A' ? el : el.closest('a') || el.querySelector('a');
                if (!link) continue;

                const href = link.href || '';
                if (!href || href === '#' || seen.has(href)) continue;
                if (href.includes('javascript:')) continue;

                seen.add(href);

                const heading = el.tagName.startsWith('H') ? el : el.querySelector('h1,h2,h3,h4');
                const title = (heading?.textContent || link.textContent || '').trim();

                if (title.length < 5) continue;

                let snippet = '';
                const parent = link.closest('article, section, div, li');
                if (parent) {
                    const p = parent.querySelector('p, [class*="excerpt"], [class*="summary"]');
                    snippet = p?.textContent?.trim().substring(0, 300) || '';
                }

                results.push({
                    url: href,
                    title: title.substring(0, 200),
                    snippet,
                    strategy: 'heading_first'
                });
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'], snippet=r.get('snippet'),
            site_type='generic', source_strategy='heading_first'
        ) for r in (results or [])]

    async def _extract_link_clusters(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Find clusters of related links."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();

            const containers = document.querySelectorAll('li, article, [class*="item"], [class*="card"], [class*="entry"]');

            for (const container of containers) {
                if (results.length >= maxItems) break;

                const links = container.querySelectorAll('a[href]');
                if (links.length === 0) continue;

                let primaryLink = null;
                for (const link of links) {
                    const href = link.href || '';
                    if (!href || href === '#' || href.includes('javascript:')) continue;
                    if (link.textContent?.trim().length > 10) {
                        primaryLink = link;
                        break;
                    }
                }

                if (!primaryLink) continue;

                const href = primaryLink.href;
                if (seen.has(href)) continue;
                seen.add(href);

                const title = primaryLink.textContent?.trim() || '';
                if (title.length < 5) continue;

                results.push({
                    url: href,
                    title: title.substring(0, 200),
                    strategy: 'link_cluster'
                });
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'],
            site_type='generic', source_strategy='link_cluster'
        ) for r in (results or [])]

    async def _extract_list_items(self, page: 'Page', url: str, max_items: int) -> List[ExtractedItem]:
        """Extract from list structures (ul/ol)."""
        results = await page.evaluate('''(maxItems) => {
            const results = [];
            const seen = new Set();

            const lists = document.querySelectorAll('ul, ol');

            for (const list of lists) {
                const items = list.querySelectorAll('li');
                if (items.length < 3) continue;

                for (const item of items) {
                    if (results.length >= maxItems) break;

                    const link = item.querySelector('a[href]');
                    if (!link) continue;

                    const href = link.href || '';
                    if (!href || href === '#' || seen.has(href)) continue;
                    seen.add(href);

                    const title = link.textContent?.trim() || '';
                    if (title.length < 5) continue;

                    results.push({
                        url: href,
                        title: title.substring(0, 200),
                        strategy: 'list_items'
                    });
                }
            }

            return results;
        }''', max_items)

        return [ExtractedItem(
            url=r['url'], title=r['title'],
            site_type='generic', source_strategy='list_items'
        ) for r in (results or [])]


# Singleton instance
_extractor: Optional[AdaptiveContentExtractor] = None


def get_adaptive_extractor() -> AdaptiveContentExtractor:
    """Get singleton extractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = AdaptiveContentExtractor()
    return _extractor
