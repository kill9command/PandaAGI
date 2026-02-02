"""
orchestrator/content_zone_calibrator.py

DEPRECATED: This module is deprecated in favor of PageIntelligenceService.

Use the new page intelligence system instead:
    from apps.services.orchestrator.page_intelligence import get_page_intelligence_service

    service = get_page_intelligence_service()
    understanding = await service.understand_page(page, url)
    items = await service.extract(page, understanding)

The new system provides:
- 3-phase pipeline (zone identification, selector generation, strategy selection)
- Multiple extraction strategies (selector, vision, hybrid, prose)
- Async-locked caching with LRU eviction
- Better error handling and debugging support

---

ORIGINAL DOCSTRING (kept for reference):
Content Zone Calibrator - Automatically learns nav vs content zones per domain.

This system:
1. PROBE - Visit multiple pages on same domain (homepage + listing page)
2. DETECT INVARIANTS - Find elements that appear on ALL pages (these are nav)
3. DETECT VARIANTS - Find elements unique to each page (these are content)
4. LEARN CONTENT ZONE - Find the main content container
5. CACHE PER DOMAIN - Store nav selectors and content zone for fast reuse

Integration:
- Called automatically by UnifiedWebExtractor before extraction
- Provides domain-specific nav filtering without hardcoded word lists
- Works for any site in any language
"""

import warnings
warnings.warn(
    "content_zone_calibrator is deprecated, use PageIntelligenceService instead",
    DeprecationWarning,
    stacklevel=2
)

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Set, Any, TYPE_CHECKING
from urllib.parse import urlparse, urljoin

if TYPE_CHECKING:
    from playwright.async_api import Page, Browser

logger = logging.getLogger(__name__)

# Storage location
CONTENT_ZONE_FILE = Path("panda_system_docs/schemas/content_zones.jsonl")


# =============================================================================
# DATA MODEL
# =============================================================================

@dataclass
class ContentZoneSchema:
    """
    Learned content zone schema for a domain.

    Stores what elements are navigation (invariant across pages)
    vs content (variant per page), AND what patterns indicate products.
    """
    domain: str

    # Nav selectors - elements to SKIP during extraction
    nav_selectors: List[str] = field(default_factory=list)

    # Content zone - the main content container selector
    content_zone_selector: Optional[str] = None

    # Nav text fingerprints - hashes of text that appears on all pages
    nav_text_fingerprints: List[str] = field(default_factory=list)

    # Element class patterns that are navigation
    nav_class_patterns: List[str] = field(default_factory=list)

    # === NEW: Learned product patterns (what TO extract) ===

    # Product URL patterns - regex patterns that indicate product links
    # e.g., ["\\.p\\?", "/site/.*/\\d+\\.p", "/dp/"]
    product_url_patterns: List[str] = field(default_factory=list)

    # Product card selectors - CSS selectors that find product containers
    # e.g., [".sku-item", "[data-sku-id]", ".item-cell"]
    product_card_selectors: List[str] = field(default_factory=list)

    # Price container selectors - where prices are found
    # e.g., [".priceView-customer-price", "[data-testid='price']"]
    price_selectors: List[str] = field(default_factory=list)

    # Content bounds (optional, in pixels)
    content_top: Optional[int] = None
    content_left: Optional[int] = None
    content_right: Optional[int] = None
    content_bottom: Optional[int] = None

    # Metadata
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    pages_probed: int = 0
    calibration_confidence: float = 0.0

    # Stats
    total_uses: int = 0
    successful_filters: int = 0

    # Flags
    skip_homepage_probe: bool = False  # True if homepage probe causes anti-bot blocks

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ContentZoneSchema':
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def is_nav_text(self, text: str) -> bool:
        """Check if text matches a known nav fingerprint."""
        text_hash = hashlib.md5(text.lower().strip().encode()).hexdigest()[:12]
        return text_hash in self.nav_text_fingerprints

    def is_nav_element(self, classes: str, element_id: str = "") -> bool:
        """Check if element classes/id match nav patterns."""
        combined = f"{classes} {element_id}".lower()
        for pattern in self.nav_class_patterns:
            if pattern in combined:
                return True
        return False


# =============================================================================
# CONTENT ZONE REGISTRY
# =============================================================================

class ContentZoneRegistry:
    """Registry for storing and retrieving content zone schemas."""

    def __init__(self, cache_path: Path = CONTENT_ZONE_FILE):
        self.cache_path = cache_path
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._schemas: Dict[str, ContentZoneSchema] = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return

        if self.cache_path.exists():
            try:
                with open(self.cache_path, 'r') as f:
                    for line in f:
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        schema = ContentZoneSchema.from_dict(data)
                        self._schemas[schema.domain] = schema
                logger.info(f"[ContentZoneRegistry] Loaded {len(self._schemas)} content zone schemas")
            except Exception as e:
                logger.error(f"[ContentZoneRegistry] Load error: {e}")

        self._loaded = True

    def _save(self):
        try:
            with open(self.cache_path, 'w') as f:
                for schema in self._schemas.values():
                    f.write(json.dumps(schema.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"[ContentZoneRegistry] Save error: {e}")

    def get(self, domain: str) -> Optional[ContentZoneSchema]:
        self._load()
        domain = self._normalize_domain(domain)
        return self._schemas.get(domain)

    def save(self, schema: ContentZoneSchema):
        self._load()
        schema.updated_at = datetime.now(timezone.utc).isoformat()
        self._schemas[schema.domain] = schema
        self._save()
        logger.info(f"[ContentZoneRegistry] Saved schema for {schema.domain}")

    def delete(self, domain: str):
        self._load()
        domain = self._normalize_domain(domain)
        if domain in self._schemas:
            del self._schemas[domain]
            self._save()

    def _normalize_domain(self, domain: str) -> str:
        domain = domain.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain


# Global registry
_registry: Optional[ContentZoneRegistry] = None

def get_content_zone_registry() -> ContentZoneRegistry:
    global _registry
    if _registry is None:
        _registry = ContentZoneRegistry()
    return _registry


# =============================================================================
# CONTENT ZONE CALIBRATOR
# =============================================================================

@dataclass
class ElementFingerprint:
    """Fingerprint of a DOM element for comparison across pages."""
    tag: str
    classes: str
    element_id: str
    text_hash: str  # MD5 of trimmed text content
    text_preview: str  # First 50 chars for debugging
    selector_path: str  # CSS path to element
    rect_top: int
    rect_left: int
    is_link: bool
    href_pattern: str  # Generalized href pattern

    def __hash__(self):
        # Hash based on structure, not text (to find repeated nav items)
        return hash((self.tag, self.classes, self.element_id, self.selector_path[:100]))

    def __eq__(self, other):
        if not isinstance(other, ElementFingerprint):
            return False
        return (self.tag == other.tag and
                self.classes == other.classes and
                self.element_id == other.element_id)


class ContentZoneCalibrator:
    """
    Calibrates content zones by comparing multiple pages on a domain.

    Algorithm:
    1. Visit homepage + listing page
    2. Extract fingerprints of all interactive elements (links, buttons)
    3. Find invariants (elements on both pages) = navigation
    4. Find variants (elements only on listing page) = content
    5. Identify content zone (container with most variants)
    6. Build nav selectors from invariants
    """

    def __init__(self, registry: ContentZoneRegistry = None):
        self.registry = registry or get_content_zone_registry()

    async def calibrate(
        self,
        page: 'Page',
        url: str,
        force: bool = False
    ) -> Optional[ContentZoneSchema]:
        """
        Calibrate content zone for a domain.

        Args:
            page: Playwright page (already on the listing/search page)
            url: Current URL
            force: Force recalibration even if schema exists

        Returns:
            ContentZoneSchema or None if calibration fails
        """
        domain = self._extract_domain(url)

        # Check cache
        if not force:
            existing = self.registry.get(domain)
            if existing and existing.calibration_confidence >= 0.5:
                logger.debug(f"[ContentZoneCalibrator] Using cached schema for {domain}")
                return existing

        logger.info(f"[ContentZoneCalibrator] Starting calibration for {domain}")

        try:
            # Get fingerprints from current page (listing/search page)
            listing_fingerprints = await self._extract_fingerprints(page, url)
            logger.info(f"[ContentZoneCalibrator] Extracted {len(listing_fingerprints)} fingerprints from listing page")

            # Check if we should skip homepage probing for this domain
            existing_schema = self.registry.get(domain)
            should_skip_homepage = existing_schema and existing_schema.skip_homepage_probe

            # Try to visit homepage for comparison (unless flagged to skip)
            homepage_fingerprints = None
            if not should_skip_homepage:
                homepage_fingerprints = await self._probe_homepage(page, url)
            else:
                logger.info(f"[ContentZoneCalibrator] Skipping homepage probe for {domain} (previously caused blocks)")

            if homepage_fingerprints:
                logger.info(f"[ContentZoneCalibrator] Extracted {len(homepage_fingerprints)} fingerprints from homepage")

                # Find invariants (nav) and variants (content)
                invariants, variants = self._compare_fingerprints(
                    listing_fingerprints,
                    homepage_fingerprints
                )

                logger.info(f"[ContentZoneCalibrator] Found {len(invariants)} invariants (nav), {len(variants)} variants (content)")

                # Build schema
                schema = self._build_schema(domain, invariants, variants, listing_fingerprints)
                schema.pages_probed = 2
                # Preserve skip_homepage_probe flag if it was set (from previous blocking)
                if should_skip_homepage:
                    schema.skip_homepage_probe = True

            else:
                # Homepage probe failed - check if we got blocked
                page_ok = True
                try:
                    current_title = await page.title()
                    if any(x in current_title.lower() for x in ['moment', 'captcha', 'verify', 'robot', 'blocked']):
                        logger.warning(f"[ContentZoneCalibrator] Page blocked after homepage probe: {current_title}")
                        # Try to reload the original page
                        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                        await asyncio.sleep(3)
                        # Check if still blocked
                        current_title = await page.title()
                        if any(x in current_title.lower() for x in ['moment', 'captcha', 'verify', 'robot', 'blocked']):
                            logger.warning(f"[ContentZoneCalibrator] Still blocked after reload")
                            page_ok = False
                except Exception as e:
                    logger.warning(f"[ContentZoneCalibrator] Error checking/recovering page state: {e}")
                    page_ok = False

                if page_ok:
                    # Single page analysis - use heuristics
                    logger.info(f"[ContentZoneCalibrator] Homepage probe failed, using single-page analysis")
                    schema = await self._single_page_calibration(page, url, listing_fingerprints)
                    schema.pages_probed = 1
                    # Preserve skip_homepage_probe flag if it was set
                    if should_skip_homepage:
                        schema.skip_homepage_probe = True
                else:
                    # Page is blocked - return basic schema from fingerprints only
                    logger.warning(f"[ContentZoneCalibrator] Page blocked, returning basic schema")
                    schema = self._build_schema_from_fingerprints_only(domain, listing_fingerprints)
                    schema.pages_probed = 1
                    schema.calibration_confidence = 0.3  # Low confidence
                    schema.skip_homepage_probe = True  # Flag to skip homepage probe next time
                    # Skip pattern learning since page is blocked
                    self.registry.save(schema)
                    return schema

            # Learn product patterns (URL patterns, card selectors, price selectors)
            await self._learn_product_patterns(page, url, schema)

            # Validate and save
            if schema and (schema.nav_selectors or schema.content_zone_selector or schema.product_url_patterns):
                schema.calibration_confidence = self._calculate_confidence(schema)
                self.registry.save(schema)
                logger.info(
                    f"[ContentZoneCalibrator] Calibration complete for {domain}: "
                    f"{len(schema.nav_selectors)} nav selectors, "
                    f"content zone: {schema.content_zone_selector}, "
                    f"product URL patterns: {schema.product_url_patterns}, "
                    f"card selectors: {schema.product_card_selectors}, "
                    f"confidence: {schema.calibration_confidence:.0%}"
                )
                return schema

            logger.warning(f"[ContentZoneCalibrator] Calibration produced empty schema for {domain}")
            return None

        except Exception as e:
            logger.error(f"[ContentZoneCalibrator] Calibration failed for {domain}: {e}", exc_info=True)
            return None

    async def _extract_fingerprints(self, page: 'Page', url: str) -> List[ElementFingerprint]:
        """Extract fingerprints of all interactive elements on a page."""

        js_code = """() => {
            const fingerprints = [];

            // Get all links and interactive elements
            const elements = document.querySelectorAll('a[href], button, [role="button"], [onclick]');

            for (const el of elements) {
                try {
                    const rect = el.getBoundingClientRect();

                    // Skip invisible elements
                    if (rect.width === 0 || rect.height === 0) continue;
                    if (rect.top < 0 || rect.top > 5000) continue;

                    const tag = el.tagName.toLowerCase();
                    const classes = el.className?.toString() || '';
                    const id = el.id || '';
                    const text = el.textContent?.trim().slice(0, 100) || '';

                    // Get href pattern (generalize IDs/numbers)
                    let hrefPattern = '';
                    if (tag === 'a') {
                        const href = el.getAttribute('href') || '';
                        hrefPattern = href
                            .replace(/\\/\\d+/g, '/{ID}')
                            .replace(/[?&][^=]+=\\d+/g, '?param={ID}')
                            .slice(0, 100);
                    }

                    // Build simple selector path
                    let selectorPath = tag;
                    if (id) {
                        selectorPath = '#' + id;
                    } else if (classes) {
                        const firstClass = classes.split(/\\s+/)[0];
                        if (firstClass && !firstClass.includes('{')) {
                            selectorPath = tag + '.' + firstClass;
                        }
                    }

                    // Get parent context
                    let parent = el.parentElement;
                    let parentSelector = '';
                    for (let i = 0; i < 3 && parent; i++) {
                        if (parent.id) {
                            parentSelector = '#' + parent.id + ' ' + parentSelector;
                            break;
                        }
                        const pc = parent.className?.toString().split(/\\s+/)[0];
                        if (pc && !pc.includes('{')) {
                            parentSelector = parent.tagName.toLowerCase() + '.' + pc + ' ' + parentSelector;
                        }
                        parent = parent.parentElement;
                    }

                    fingerprints.push({
                        tag: tag,
                        classes: classes.slice(0, 200),
                        id: id,
                        text: text,
                        selector: (parentSelector + selectorPath).trim(),
                        top: Math.round(rect.top),
                        left: Math.round(rect.left),
                        isLink: tag === 'a',
                        hrefPattern: hrefPattern
                    });
                } catch (e) {
                    continue;
                }
            }

            return fingerprints;
        }"""

        raw_fingerprints = await page.evaluate(js_code)

        fingerprints = []
        for fp in raw_fingerprints:
            text_hash = hashlib.md5(fp['text'].lower().encode()).hexdigest()[:12]
            fingerprints.append(ElementFingerprint(
                tag=fp['tag'],
                classes=fp['classes'],
                element_id=fp['id'],
                text_hash=text_hash,
                text_preview=fp['text'][:50],
                selector_path=fp['selector'],
                rect_top=fp['top'],
                rect_left=fp['left'],
                is_link=fp['isLink'],
                href_pattern=fp['hrefPattern']
            ))

        return fingerprints

    async def _probe_homepage(self, page: 'Page', current_url: str) -> Optional[List[ElementFingerprint]]:
        """Visit homepage and extract fingerprints."""
        parsed = urlparse(current_url)
        homepage_url = f"{parsed.scheme}://{parsed.netloc}/"

        # Skip if already on homepage
        if current_url.rstrip('/') == homepage_url.rstrip('/'):
            return None

        try:
            # Save current URL to return to
            original_url = page.url

            # Navigate to homepage
            await page.goto(homepage_url, wait_until='domcontentloaded', timeout=15000)
            await asyncio.sleep(1)

            # Check for anti-bot
            title = await page.title()
            if any(x in title.lower() for x in ['moment', 'captcha', 'verify', 'robot']):
                logger.warning(f"[ContentZoneCalibrator] Anti-bot on homepage: {title}")
                await page.goto(original_url, wait_until='domcontentloaded', timeout=15000)
                return None

            # Extract fingerprints
            fingerprints = await self._extract_fingerprints(page, homepage_url)

            # Return to original page
            await page.goto(original_url, wait_until='domcontentloaded', timeout=15000)
            await asyncio.sleep(1)

            return fingerprints

        except Exception as e:
            logger.warning(f"[ContentZoneCalibrator] Homepage probe failed: {e}")
            # DON'T navigate back here - let the caller handle it
            # Navigating back after a timeout can trigger anti-bot protection
            return None

    def _compare_fingerprints(
        self,
        listing_fps: List[ElementFingerprint],
        homepage_fps: List[ElementFingerprint]
    ) -> tuple:
        """
        Compare fingerprints to find invariants (nav) and variants (content).

        Invariants: Elements that appear on BOTH pages (same structure)
        Variants: Elements only on listing page (the actual content)
        """
        # Create lookup by structural key
        homepage_keys = set()
        for fp in homepage_fps:
            # Key by structure, not text content
            key = (fp.tag, fp.classes[:50], fp.element_id, fp.selector_path[:50])
            homepage_keys.add(key)

        invariants = []
        variants = []

        for fp in listing_fps:
            key = (fp.tag, fp.classes[:50], fp.element_id, fp.selector_path[:50])

            if key in homepage_keys:
                # This element structure exists on homepage = likely nav
                invariants.append(fp)
            else:
                # This element only on listing page = likely content
                variants.append(fp)

        return invariants, variants

    def _build_schema(
        self,
        domain: str,
        invariants: List[ElementFingerprint],
        variants: List[ElementFingerprint],
        all_fingerprints: List[ElementFingerprint]
    ) -> ContentZoneSchema:
        """Build ContentZoneSchema from invariants and variants."""

        schema = ContentZoneSchema(domain=domain)

        # Build nav selectors from invariants
        nav_selectors = set()
        nav_text_fingerprints = set()
        nav_class_patterns = set()

        for fp in invariants:
            # Add text fingerprint
            if fp.text_preview and len(fp.text_preview) > 2:
                nav_text_fingerprints.add(fp.text_hash)

            # Add class patterns
            for cls in fp.classes.split():
                cls_lower = cls.lower()
                if any(nav_word in cls_lower for nav_word in ['nav', 'menu', 'header', 'footer', 'sidebar', 'breadcrumb']):
                    nav_class_patterns.add(cls_lower)

            # Build selector if specific enough
            if fp.element_id:
                nav_selectors.add(f"#{fp.element_id}")
            elif fp.selector_path and '.' in fp.selector_path:
                nav_selectors.add(fp.selector_path)

        schema.nav_selectors = list(nav_selectors)[:50]  # Limit
        schema.nav_text_fingerprints = list(nav_text_fingerprints)[:200]
        schema.nav_class_patterns = list(nav_class_patterns)[:30]

        # Find content zone from variants
        if variants:
            # Group variants by their parent selector prefix
            parent_counts = {}
            for fp in variants:
                # Get first 2 parts of selector as parent
                parts = fp.selector_path.split()
                parent = ' '.join(parts[:2]) if len(parts) >= 2 else parts[0] if parts else ''
                if parent:
                    parent_counts[parent] = parent_counts.get(parent, 0) + 1

            # Find most common parent = content zone
            if parent_counts:
                best_parent = max(parent_counts, key=parent_counts.get)
                if parent_counts[best_parent] >= 3:
                    schema.content_zone_selector = best_parent

            # Calculate content bounds
            tops = [fp.rect_top for fp in variants if fp.rect_top > 0]
            lefts = [fp.rect_left for fp in variants if fp.rect_left > 0]

            if tops:
                schema.content_top = min(tops) - 50  # Some padding
                schema.content_bottom = max(tops) + 500
            if lefts:
                schema.content_left = min(lefts) - 50
                schema.content_right = max(lefts) + 800

        return schema

    async def _learn_product_patterns(self, page: 'Page', url: str, schema: ContentZoneSchema) -> None:
        """
        Learn product URL patterns and card selectors from a listing page.

        This detects:
        1. Product URL patterns - by finding links near prices
        2. Product card selectors - containers with price + title + link
        3. Price selectors - where prices appear on the page
        """
        logger.info(f"[ContentZoneCalibrator] Learning product patterns for {schema.domain}")

        js_code = """() => {
            const result = {
                productUrls: [],
                cardSelectors: [],
                priceSelectors: [],
                debug: {
                    priceElementsFound: 0,
                    cardsFound: 0,
                    urlPatternsRaw: [],
                    nodesWalked: 0,
                    searchScope: 'full'
                }
            };

            // Guard against null body
            if (!document.body) return result;

            const priceRe = /\\$[\\d,]+\\.?\\d{0,2}/;
            const MAX_NODES = 5000; // Prevent browser crash on heavy pages
            let nodesWalked = 0;

            // ================================================================
            // STEP 1: Find all price elements
            // Try targeted search first (faster, safer), fall back to TreeWalker
            // ================================================================
            const priceElements = [];

            // FAST PATH: Try querySelectorAll for common price patterns first
            const fastPriceSelectors = [
                '[class*="price"]:not(nav *):not(header *):not(footer *)',
                '[data-testid*="price"]:not(nav *):not(header *):not(footer *)',
                '[class*="Price"]:not(nav *):not(header *):not(footer *)'
            ];

            for (const sel of fastPriceSelectors) {
                try {
                    const elements = document.querySelectorAll(sel);
                    for (const el of elements) {
                        if (priceElements.length >= 50) break;
                        const text = el.textContent?.trim() || '';
                        if (priceRe.test(text) && text.length < 30 && !text.includes(' - ')) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0 && rect.top > 100) {
                                priceElements.push({ element: el, y: rect.top, x: rect.left });
                            }
                        }
                    }
                } catch (e) {}
            }

            // If fast path found enough prices, skip TreeWalker
            if (priceElements.length >= 10) {
                result.debug.searchScope = 'fast';
            } else {
                // SLOW PATH: TreeWalker for sites without standard price classes
                result.debug.searchScope = 'treewalker';

                // Try to narrow scope to main content area
                let searchRoot = document.body;
                const mainContent = document.querySelector('main, [role="main"], #main, .main-content, [class*="results"], [class*="listings"]');
                if (mainContent) {
                    searchRoot = mainContent;
                    result.debug.searchScope = 'treewalker-scoped';
                }

                try {
                    const walker = document.createTreeWalker(searchRoot, NodeFilter.SHOW_TEXT, {
                        acceptNode: n => {
                            const text = n.textContent?.trim() || '';
                            if (!priceRe.test(text)) return NodeFilter.FILTER_SKIP;
                            if (text.length > 30) return NodeFilter.FILTER_SKIP;
                            // Skip price ranges like "$100 - $200" (these are filters)
                            if (text.includes(' - ') || text.includes(' to ')) return NodeFilter.FILTER_SKIP;
                            const parent = n.parentElement;
                            if (!parent) return NodeFilter.FILTER_SKIP;
                            // Skip nav elements
                            if (parent.closest('nav, header, footer, [role="navigation"]')) return NodeFilter.FILTER_SKIP;
                            // Skip filter/checkbox elements (common in sidebar filters)
                            const parentClass = parent.className?.toLowerCase() || '';
                            if (parentClass.includes('checkbox') || parentClass.includes('filter') ||
                                parentClass.includes('facet') || parentClass.includes('range')) return NodeFilter.FILTER_SKIP;
                            // Skip aside/sidebar elements
                            if (parent.closest('aside, [class*="sidebar"], [class*="filter"], [class*="facet"]')) return NodeFilter.FILTER_SKIP;
                            return NodeFilter.FILTER_ACCEPT;
                        }
                    });

                    // Max nodes limit is enforced in the while loop, not in acceptNode
                    // Using FILTER_REJECT in acceptNode would skip entire subtrees
                    while (walker.nextNode() && priceElements.length < 50) {
                        nodesWalked++;
                        if (nodesWalked > MAX_NODES) break;
                        const parent = walker.currentNode.parentElement;
                        if (!parent) continue;
                        try {
                            const rect = parent.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0 && rect.top > 100) {
                                priceElements.push({
                                    element: parent,
                                    y: rect.top,
                                    x: rect.left
                                });
                            }
                        } catch (e) {}
                    }
                } catch (e) {
                    result.debug.treeWalkerError = e.message;
                }
            }

            result.debug.priceElementsFound = priceElements.length;
            result.debug.nodesWalked = nodesWalked;

            // ================================================================
            // STEP 2: For each price, find the containing product card
            // ================================================================
            const cardCandidates = new Map(); // selector -> count
            const urlPatterns = new Map(); // pattern -> count
            const priceSelectorCandidates = new Map(); // selector -> count

            for (const priceInfo of priceElements.slice(0, 30)) {
                const priceEl = priceInfo.element;

                // Record price selector
                const priceClass = priceEl.className?.toString().split(/\\s+/).find(c =>
                    c.toLowerCase().includes('price') || c.length > 3
                );
                if (priceClass) {
                    const priceSel = '.' + priceClass;
                    priceSelectorCandidates.set(priceSel, (priceSelectorCandidates.get(priceSel) || 0) + 1);
                }

                // Walk up to find product card
                let el = priceEl;
                for (let i = 0; i < 8 && el; i++) {
                    el = el.parentElement;
                    if (!el || el === document.body) break;

                    // Check if this looks like a product card
                    const links = el.querySelectorAll('a[href]');
                    const hasTitle = el.querySelector('h1,h2,h3,h4,[class*="title"],[class*="name"]');

                    if (links.length > 0 && hasTitle) {
                        // Found a product card candidate
                        result.debug.cardsFound++;

                        // Record card selector
                        const cardClass = el.className?.toString().split(/\\s+/).find(c =>
                            c.length > 3 && !c.includes('{')
                        );
                        if (cardClass) {
                            cardCandidates.set('.' + cardClass, (cardCandidates.get('.' + cardClass) || 0) + 1);
                        }

                        // Check for data attributes
                        for (const attr of ['data-sku', 'data-sku-id', 'data-product-id', 'data-asin', 'data-item-id']) {
                            if (el.hasAttribute(attr)) {
                                cardCandidates.set('[' + attr + ']', (cardCandidates.get('[' + attr + ']') || 0) + 1);
                            }
                        }

                        // Record URL patterns from product links
                        for (const link of links) {
                            const href = link.href || '';
                            if (!href || href.includes('javascript:')) continue;

                            try {
                                const urlObj = new URL(href);
                                const path = urlObj.pathname;

                                // Extract meaningful URL patterns
                                // Look for patterns like: /product/, /p/, .p?, /dp/, /site/.../123.p
                                const patterns = [];

                                if (path.includes('/product')) patterns.push('/product');
                                if (path.includes('/dp/')) patterns.push('/dp/');
                                if (path.match(/\\/p\\//)) patterns.push('/p/');
                                if (path.match(/\\.p$/)) patterns.push('\\\\.p$');
                                if (path.match(/\\.p\\?/)) patterns.push('\\\\.p\\\\?');
                                if (path.match(/\\/item/)) patterns.push('/item');
                                if (path.match(/\\/itm\\//)) patterns.push('/itm/');  // eBay item pages
                                if (path.match(/\\/pd\\//)) patterns.push('/pd/');
                                if (path.match(/\\/ip\\//)) patterns.push('/ip/');
                                if (path.match(/\\/sch\\//)) patterns.push('/sch/');  // eBay search results
                                if (path.match(/\\/site\\/[^\\/]+\\/\\d+/)) patterns.push('/site/[^/]+/\\\\d+');

                                // Also check for SKU in query params
                                if (urlObj.search.includes('skuId=')) patterns.push('skuId=');
                                if (urlObj.search.includes('productId=')) patterns.push('productId=');

                                for (const p of patterns) {
                                    urlPatterns.set(p, (urlPatterns.get(p) || 0) + 1);
                                    if (!result.debug.urlPatternsRaw.includes(p)) {
                                        result.debug.urlPatternsRaw.push(p);
                                    }
                                }
                            } catch (e) {}
                        }

                        break; // Found card, stop walking up
                    }
                }
            }

            // ================================================================
            // STEP 3: Convert to sorted lists (most common first)
            // ================================================================
            result.productUrls = [...urlPatterns.entries()]
                .filter(([k, v]) => v >= 2)
                .sort((a, b) => b[1] - a[1])
                .map(([k, v]) => k)
                .slice(0, 10);

            result.cardSelectors = [...cardCandidates.entries()]
                .filter(([k, v]) => v >= 2)
                .sort((a, b) => b[1] - a[1])
                .map(([k, v]) => k)
                .slice(0, 10);

            result.priceSelectors = [...priceSelectorCandidates.entries()]
                .filter(([k, v]) => v >= 2)
                .sort((a, b) => b[1] - a[1])
                .map(([k, v]) => k)
                .slice(0, 5);

            return result;
        }"""

        try:
            data = await page.evaluate(js_code)

            # Debug output
            debug = data.get('debug', {})
            if debug:
                logger.info(
                    f"[ContentZoneCalibrator] Pattern learning debug: "
                    f"scope={debug.get('searchScope', 'unknown')}, "
                    f"nodes={debug.get('nodesWalked', 0)}, "
                    f"priceElements={debug.get('priceElementsFound', 0)}, "
                    f"cardsFound={debug.get('cardsFound', 0)}, "
                    f"rawUrls={debug.get('urlPatternsRaw', [])[:5]}"
                )
                if debug.get('treeWalkerError'):
                    logger.warning(f"[ContentZoneCalibrator] TreeWalker error: {debug['treeWalkerError']}")

            schema.product_url_patterns = data.get('productUrls', [])
            schema.product_card_selectors = data.get('cardSelectors', [])
            schema.price_selectors = data.get('priceSelectors', [])

            logger.info(
                f"[ContentZoneCalibrator] Learned patterns for {schema.domain}: "
                f"URL patterns: {schema.product_url_patterns}, "
                f"card selectors: {schema.product_card_selectors}, "
                f"price selectors: {schema.price_selectors}"
            )

        except Exception as e:
            logger.warning(f"[ContentZoneCalibrator] Failed to learn product patterns: {e}")
            # Fallback: use well-known patterns for major sites
            self._apply_known_site_patterns(schema)

    def _apply_known_site_patterns(self, schema: ContentZoneSchema) -> None:
        """
        Apply known patterns for major e-commerce sites as fallback.

        Called when dynamic pattern learning fails (e.g., browser crash).

        TODO(LLM-FIRST): This entire method violates the LLM-first design principle.
        INSTEAD OF: Hardcoded CSS selectors per domain
        SHOULD BE:
        1. Dynamic pattern learning (which this is a fallback for) should be more robust
        2. If learning fails, use generic heuristics that work across sites
        3. Let the LLM analyze page structure to identify product cards/prices

        The problem with hardcoded selectors:
        - Sites change their HTML structure regularly, breaking these patterns
        - Every new site requires manual pattern addition
        - An LLM can identify "this looks like a price" from context

        Until we can remove this, it serves as a last-resort fallback when the
        browser-based learning fails. The system should prefer:
        1. _learn_product_patterns() - dynamic LLM-guided learning
        2. Generic CSS patterns like [class*="price"] (structural, not site-specific)
        3. This hardcoded fallback (last resort)

        See: panda_system_docs/architecture/LLM-ROLES/CONTEXT_DISCIPLINE.md
        """
        domain = schema.domain.lower()

        # TODO(LLM-FIRST): REMOVE site-specific patterns when dynamic learning is robust.
        # These hardcoded selectors are fragile and violate LLM-first design.
        # Known site patterns - fallback when learning crashes
        KNOWN_PATTERNS = {
            'ebay.com': {
                'product_url_patterns': ['/itm/', '/sch/'],
                'product_card_selectors': ['.s-item', '[data-viewport]', '.srp-results'],
                'price_selectors': ['.s-item__price', '[class*="price"]']
            },
            'amazon.com': {
                'product_url_patterns': ['/dp/'],
                'product_card_selectors': ['[data-asin]', '.s-result-item', '.sg-col-inner'],
                'price_selectors': ['.a-price', '.a-offscreen']
            },
            'walmart.com': {
                'product_url_patterns': ['/ip/'],
                'product_card_selectors': ['[data-item-id]', '[class*="product-card"]'],
                'price_selectors': ['[data-automation-id*="price"]', '[class*="price"]']
            },
            'bestbuy.com': {
                'product_url_patterns': ['.p?', '/site/'],
                'product_card_selectors': ['[data-sku-id]', '.sku-item'],
                'price_selectors': ['.priceView-customer-price', '[class*="price"]']
            },
            'newegg.com': {
                'product_url_patterns': ['/p/'],
                'product_card_selectors': ['.item-cell', '.item-container'],
                'price_selectors': ['.price-current', '[class*="price"]']
            },
            'target.com': {
                'product_url_patterns': ['/p/'],
                'product_card_selectors': ['[data-test="product-card"]'],
                'price_selectors': ['[data-test="current-price"]']
            }
        }

        for site_domain, patterns in KNOWN_PATTERNS.items():
            if site_domain in domain:
                if not schema.product_url_patterns:
                    schema.product_url_patterns = patterns['product_url_patterns']
                if not schema.product_card_selectors:
                    schema.product_card_selectors = patterns['product_card_selectors']
                if not schema.price_selectors:
                    schema.price_selectors = patterns['price_selectors']
                logger.info(
                    f"[ContentZoneCalibrator] Applied known patterns for {site_domain}: "
                    f"URL patterns: {schema.product_url_patterns}"
                )
                break

    def _build_schema_from_fingerprints_only(
        self,
        domain: str,
        fingerprints: List[ElementFingerprint]
    ) -> ContentZoneSchema:
        """
        Build a basic schema from fingerprints only.

        Used when page is blocked and we can't do full calibration.
        Uses heuristics based on position and class names.
        """
        schema = ContentZoneSchema(domain=domain)

        # Use position-based nav detection from fingerprints
        nav_text_fingerprints = set()
        nav_class_patterns = set()

        for fp in fingerprints:
            # Elements in top 150px are likely nav
            if fp.rect_top < 150:
                if fp.text_preview:
                    nav_text_fingerprints.add(fp.text_hash)

            # Class-based detection
            classes_lower = fp.classes.lower()
            for nav_word in ['nav', 'menu', 'header', 'footer', 'sidebar']:
                if nav_word in classes_lower:
                    nav_class_patterns.add(nav_word)
                    if fp.text_preview:
                        nav_text_fingerprints.add(fp.text_hash)

        schema.nav_text_fingerprints = list(nav_text_fingerprints)[:100]
        schema.nav_class_patterns = list(nav_class_patterns)

        return schema

    async def _single_page_calibration(
        self,
        page: 'Page',
        url: str,
        fingerprints: List[ElementFingerprint]
    ) -> ContentZoneSchema:
        """
        Calibrate from a single page using heuristics.

        Uses position-based and class-based detection when we can't
        compare multiple pages.
        """
        domain = self._extract_domain(url)
        schema = ContentZoneSchema(domain=domain)

        # Heuristic 1: Elements in top 150px are likely header/nav
        # Heuristic 2: Elements in left 200px might be sidebar
        # Heuristic 3: Look for nav-related class names

        nav_class_patterns = set()
        nav_text_fingerprints = set()

        for fp in fingerprints:
            # Position-based nav detection
            is_likely_nav = False

            # Top of page = likely header
            if fp.rect_top < 150:
                is_likely_nav = True

            # Very left side might be sidebar
            if fp.rect_left < 100:
                is_likely_nav = True

            # Class-based nav detection
            classes_lower = fp.classes.lower()
            for nav_word in ['nav', 'menu', 'header', 'footer', 'sidebar', 'breadcrumb', 'promo', 'banner', 'toolbar']:
                if nav_word in classes_lower:
                    is_likely_nav = True
                    nav_class_patterns.add(nav_word)

            # ID-based nav detection
            id_lower = fp.element_id.lower()
            for nav_word in ['nav', 'menu', 'header', 'footer', 'sidebar']:
                if nav_word in id_lower:
                    is_likely_nav = True

            if is_likely_nav and fp.text_preview:
                nav_text_fingerprints.add(fp.text_hash)

        schema.nav_class_patterns = list(nav_class_patterns)
        schema.nav_text_fingerprints = list(nav_text_fingerprints)[:100]

        # Use JavaScript to find the main content container
        content_selector = await page.evaluate("""() => {
            // Common content container selectors
            const candidates = [
                'main', '[role="main"]', '#main', '.main-content',
                '#content', '.content', '[class*="search-results"]',
                '[class*="product-list"]', '[class*="results"]',
                '[class*="listing"]', '[class*="grid"]'
            ];

            for (const sel of candidates) {
                const el = document.querySelector(sel);
                if (el) {
                    const rect = el.getBoundingClientRect();
                    // Must be substantial
                    if (rect.height > 300 && rect.width > 400) {
                        return sel;
                    }
                }
            }
            return null;
        }""")

        if content_selector:
            schema.content_zone_selector = content_selector

        # Get content bounds from page
        bounds = await page.evaluate("""() => {
            const main = document.querySelector('main, [role="main"], #main, .main-content, #content');
            if (main) {
                const rect = main.getBoundingClientRect();
                return {
                    top: Math.round(rect.top),
                    left: Math.round(rect.left),
                    right: Math.round(rect.right),
                    bottom: Math.round(rect.bottom)
                };
            }
            return null;
        }""")

        if bounds:
            schema.content_top = bounds['top']
            schema.content_left = bounds['left']
            schema.content_right = bounds['right']
            schema.content_bottom = bounds['bottom']

        return schema

    def _calculate_confidence(self, schema: ContentZoneSchema) -> float:
        """Calculate confidence score for the schema."""
        score = 0.0

        # More nav patterns = higher confidence
        if len(schema.nav_text_fingerprints) >= 10:
            score += 0.15
        elif len(schema.nav_text_fingerprints) >= 5:
            score += 0.08

        if len(schema.nav_class_patterns) >= 3:
            score += 0.15
        elif len(schema.nav_class_patterns) >= 1:
            score += 0.08

        # Content zone found
        if schema.content_zone_selector:
            score += 0.15

        # Content bounds found
        if schema.content_top is not None:
            score += 0.07

        # Multiple pages probed
        if schema.pages_probed >= 2:
            score += 0.15

        # Product URL patterns learned (important!)
        if len(schema.product_url_patterns) >= 2:
            score += 0.15
        elif len(schema.product_url_patterns) >= 1:
            score += 0.08

        # Product card selectors learned
        if len(schema.product_card_selectors) >= 2:
            score += 0.1
        elif len(schema.product_card_selectors) >= 1:
            score += 0.05

        # Price selectors learned
        if len(schema.price_selectors) >= 1:
            score += 0.05

        return min(1.0, score)

    def _extract_domain(self, url: str) -> str:
        """Extract normalized domain from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]
        domain = domain.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_calibrator: Optional[ContentZoneCalibrator] = None

def get_content_zone_calibrator() -> ContentZoneCalibrator:
    """Get singleton calibrator instance."""
    global _calibrator
    if _calibrator is None:
        _calibrator = ContentZoneCalibrator()
    return _calibrator


# =============================================================================
# HELPER FUNCTIONS FOR EXTRACTION
# =============================================================================

def is_nav_element(
    schema: Optional[ContentZoneSchema],
    text: str,
    classes: str = "",
    element_id: str = "",
    rect_top: int = 0,
    rect_left: int = 0
) -> bool:
    """
    Check if an element is navigation based on learned schema.

    Args:
        schema: ContentZoneSchema for the domain (or None)
        text: Element text content
        classes: Element class string
        element_id: Element ID
        rect_top: Element top position in pixels
        rect_left: Element left position in pixels

    Returns:
        True if element appears to be navigation
    """
    # If no schema, use basic heuristics
    if not schema:
        # Position-based
        if rect_top < 100 or rect_left < 50:
            return True
        # Class-based fallback
        classes_lower = classes.lower()
        for nav_word in ['nav', 'menu', 'header', 'footer', 'sidebar']:
            if nav_word in classes_lower:
                return True
        return False

    # Use schema
    if schema.is_nav_text(text):
        return True

    if schema.is_nav_element(classes, element_id):
        return True

    # Check content bounds
    if schema.content_top is not None and rect_top < schema.content_top:
        return True
    if schema.content_left is not None and rect_left < schema.content_left:
        return True

    return False


def get_product_patterns_js(schema: Optional[ContentZoneSchema]) -> str:
    """
    Generate JavaScript code for product URL matching based on learned schema.

    Returns JS code that defines productUrlRe and cardSelectors.
    """
    if not schema or not schema.product_url_patterns:
        # Fallback: hardcoded patterns for common sites
        return """
        const productUrlRe = /\\/product[s]?\\/|\\/p\\/|\\/dp\\/|\\/ip\\/|\\/item[s]?\\/|\\/pd\\/|\\/n82e|\\/i\\/|[?&]skuId=|[?&]item=|[?&]product=|\\.p\\?|\\.p$/i;
        const cardSelectors = ['[data-asin]', '[data-product-id]', '[data-sku]', '[data-sku-id]', '[class*="product-card"]', '[class*="product-item"]', '[class*="sku-item"]', '.item-cell'];
        """

    # Build regex from learned patterns
    patterns = schema.product_url_patterns[:15]  # Limit
    # Escape for JS regex
    escaped = [p.replace('/', '\\/') for p in patterns]
    regex_str = '|'.join(escaped)

    # Card selectors
    card_sels = schema.product_card_selectors[:10] if schema.product_card_selectors else []
    card_sels_json = json.dumps(card_sels)

    return f"""
    const productUrlRe = /{regex_str}/i;
    const cardSelectors = {card_sels_json};
    """


def get_nav_filter_js(schema: Optional[ContentZoneSchema]) -> str:
    """
    Generate JavaScript code for nav filtering based on schema.

    Returns JS code that can be inserted into page.evaluate() calls.
    """
    if not schema:
        return """
        function isNavElement(el) {
            // Fallback: position and class based
            const rect = el.getBoundingClientRect();
            if (rect.top < 100) return true;

            let parent = el;
            while (parent) {
                const tag = parent.tagName?.toLowerCase();
                if (tag === 'nav' || tag === 'header' || tag === 'footer') return true;
                const role = parent.getAttribute?.('role');
                if (role === 'navigation' || role === 'banner') return true;
                const cls = (parent.className || '').toLowerCase();
                if (/\\b(nav|menu|header|footer|sidebar)\\b/.test(cls)) return true;
                parent = parent.parentElement;
            }
            return false;
        }
        """

    # Build JS from schema
    nav_fingerprints = json.dumps(schema.nav_text_fingerprints[:100])
    nav_class_patterns = json.dumps(schema.nav_class_patterns[:20])
    content_top = schema.content_top or 0
    content_left = schema.content_left or 0

    return f"""
    const _navFingerprints = new Set({nav_fingerprints});
    const _navClassPatterns = {nav_class_patterns};
    const _contentTop = {content_top};
    const _contentLeft = {content_left};

    function hashText(text) {{
        // Simple hash for text matching
        let hash = 0;
        const str = text.toLowerCase().trim();
        for (let i = 0; i < str.length; i++) {{
            hash = ((hash << 5) - hash) + str.charCodeAt(i);
            hash |= 0;
        }}
        return hash.toString(16).slice(-12);
    }}

    function isNavElement(el) {{
        const rect = el.getBoundingClientRect();

        // Position check
        if (_contentTop > 0 && rect.top < _contentTop) return true;
        if (_contentLeft > 0 && rect.left < _contentLeft) return true;

        // Text fingerprint check
        const text = el.textContent?.trim() || '';
        if (text.length > 0 && text.length < 50) {{
            const hash = hashText(text);
            if (_navFingerprints.has(hash)) return true;
        }}

        // Class pattern check
        const cls = (el.className || '').toLowerCase();
        for (const pattern of _navClassPatterns) {{
            if (cls.includes(pattern)) return true;
        }}

        // Standard nav container check
        let parent = el;
        while (parent) {{
            const tag = parent.tagName?.toLowerCase();
            if (tag === 'nav' || tag === 'header' || tag === 'footer') return true;
            const role = parent.getAttribute?.('role');
            if (role === 'navigation' || role === 'banner') return true;
            parent = parent.parentElement;
        }}

        return false;
    }}
    """
