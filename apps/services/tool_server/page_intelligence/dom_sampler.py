"""
orchestrator/page_intelligence/dom_sampler.py

DOM Sampler - Extracts HTML snippets from identified zones

Takes zone definitions (with DOM anchors) and extracts actual HTML
from those zones. This HTML is fed to Phase 2 (Selector Generator)
so it can create precise CSS selectors based on real structure.
"""

import logging
from typing import TYPE_CHECKING, List, Dict, Any, Optional

from apps.services.tool_server.page_intelligence.models import Zone, Bounds

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class DOMSampler:
    """
    Extracts HTML samples from identified zones.

    Used between Phase 1 (Zone Identification) and Phase 2 (Selector Generation)
    to provide real HTML structure for selector creation.
    """

    def __init__(self, max_sample_length: int = 3000):
        """
        Initialize sampler.

        Args:
            max_sample_length: Maximum HTML length per sample
        """
        self.max_sample_length = max_sample_length

    async def sample_zones(
        self,
        page: 'Page',
        zones: List[Zone]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Extract HTML samples from each zone.

        Args:
            page: Playwright page
            zones: Zones identified by Phase 1

        Returns:
            Dict mapping zone_type to {html, item_count, sample_item_html}
        """
        samples = {}

        for zone in zones:
            zone_type = zone.zone_type.value if hasattr(zone.zone_type, 'value') else zone.zone_type

            if not zone.dom_anchors:
                logger.debug(f"[DOMSampler] Zone {zone_type} has no DOM anchors, skipping")
                continue

            sample = await self._sample_zone(page, zone)
            if sample:
                samples[zone_type] = sample
                logger.info(f"[DOMSampler] Sampled zone '{zone_type}': {len(sample.get('html', ''))} chars, {sample.get('item_count', 0)} items")

        return samples

    async def _sample_zone(
        self,
        page: 'Page',
        zone: Zone
    ) -> Optional[Dict[str, Any]]:
        """
        Extract HTML sample from a single zone.

        Args:
            page: Playwright page
            zone: Zone to sample

        Returns:
            {html, item_count, sample_item_html, bounds} or None
        """
        try:
            result = await page.evaluate('''(config) => {
                const { anchors, maxLength, itemCountEstimate } = config;

                // Find the zone container using anchors
                let container = null;
                for (const anchor of anchors) {
                    try {
                        container = document.querySelector(anchor);
                        if (container) break;
                    } catch (e) {
                        // Invalid selector, try next
                    }
                }

                if (!container) {
                    return { error: 'No container found for anchors: ' + anchors.join(', ') };
                }

                // Get container bounds
                const rect = container.getBoundingClientRect();
                const bounds = {
                    top: rect.top + window.scrollY,
                    left: rect.left + window.scrollX,
                    width: rect.width,
                    height: rect.height
                };

                // Get full HTML (truncated)
                const fullHtml = container.outerHTML;

                // Find repeated child elements (likely items)
                const classCounts = {};
                container.querySelectorAll('*').forEach(el => {
                    if (el.className && typeof el.className === 'string') {
                        el.className.split(' ').forEach(cls => {
                            if (cls && cls.length > 2 && cls.length < 50) {
                                classCounts[cls] = (classCounts[cls] || 0) + 1;
                            }
                        });
                    }
                });

                // Find class that appears closest to estimated item count
                let bestClass = null;
                let bestDiff = Infinity;
                for (const [cls, count] of Object.entries(classCounts)) {
                    // Look for classes with reasonable item counts (3-100)
                    if (count >= 3 && count <= 100) {
                        const diff = Math.abs(count - (itemCountEstimate || 20));
                        if (diff < bestDiff) {
                            bestDiff = diff;
                            bestClass = cls;
                        }
                    }
                }

                // Get sample item HTML
                let sampleItemHtml = '';
                let itemSelector = null;
                let actualItemCount = 0;

                if (bestClass) {
                    const items = container.querySelectorAll('.' + bestClass);
                    actualItemCount = items.length;
                    if (items.length > 0) {
                        // Get the first item's parent (the actual item container)
                        let itemEl = items[0];

                        // Walk up to find a reasonable container (has the item class)
                        while (itemEl && itemEl !== container) {
                            if (itemEl.className && typeof itemEl.className === 'string' &&
                                itemEl.className.split(' ').includes(bestClass)) {
                                break;
                            }
                            itemEl = itemEl.parentElement;
                        }

                        if (itemEl && itemEl !== container) {
                            sampleItemHtml = itemEl.outerHTML.slice(0, 2500);

                            // Build item selector
                            itemSelector = itemEl.tagName.toLowerCase();
                            if (itemEl.className && typeof itemEl.className === 'string') {
                                const classes = itemEl.className.split(' ')
                                    .filter(c => c && c.length < 50)
                                    .slice(0, 3);
                                if (classes.length > 0) {
                                    itemSelector += '.' + classes.join('.');
                                }
                            }
                        }
                    }
                }

                // If no item found, try to get first significant child
                if (!sampleItemHtml) {
                    const significantChildren = Array.from(container.children).filter(child => {
                        return child.children.length > 2 || child.textContent?.trim().length > 50;
                    });
                    if (significantChildren.length > 0) {
                        sampleItemHtml = significantChildren[0].outerHTML.slice(0, 2500);
                        actualItemCount = significantChildren.length;
                    }
                }

                // Get visible text in zone for context
                const visibleText = [];
                const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const text = walker.currentNode.textContent?.trim();
                    if (text && text.length > 3 && text.length < 100) {
                        visibleText.push(text);
                        if (visibleText.length >= 10) break;
                    }
                }

                return {
                    html: fullHtml.slice(0, maxLength),
                    sample_item_html: sampleItemHtml,
                    item_selector_hint: itemSelector,
                    item_count: actualItemCount,
                    bounds: bounds,
                    visible_text_samples: visibleText,
                    repeated_class: bestClass
                };
            }''', {
                "anchors": zone.dom_anchors,
                "maxLength": self.max_sample_length,
                "itemCountEstimate": zone.item_count_estimate
            })

            if result and "error" not in result:
                return result
            else:
                logger.warning(f"[DOMSampler] Failed to sample zone: {result.get('error', 'unknown')}")
                return None

        except Exception as e:
            logger.error(f"[DOMSampler] Error sampling zone: {e}")
            return None

    async def get_page_context(
        self,
        page: 'Page',
        include_structure: bool = True
    ) -> Dict[str, Any]:
        """
        Get overall page context for Phase 1 (Zone Identification).

        Returns URL, title, DOM structure summary, repeated classes, etc.
        """
        try:
            context = await page.evaluate('''(includeStructure) => {
                // Simplified DOM structure
                function simplifyElement(el, depth = 0) {
                    if (depth > 4) return null;
                    if (!el || el.nodeType !== 1) return null;

                    const tag = el.tagName.toLowerCase();

                    // Skip non-content elements
                    if (['script', 'style', 'noscript', 'svg', 'path', 'meta', 'link'].includes(tag)) {
                        return null;
                    }

                    // Skip hidden
                    if (el.hidden || getComputedStyle(el).display === 'none') {
                        return null;
                    }

                    const obj = { tag };

                    // Include key attributes
                    if (el.id) obj.id = el.id;
                    if (el.className && typeof el.className === 'string') {
                        obj.class = el.className.split(' ').filter(c => c).slice(0, 3).join(' ');
                    }
                    if (el.role) obj.role = el.role;

                    // CRITICAL: Include data-testid and other stable data attributes
                    // These are designed to be stable selectors (used by testing frameworks)
                    const dataTestId = el.getAttribute('data-testid');
                    if (dataTestId) obj.dataTestId = dataTestId;

                    // Also check for other common stable data attributes
                    const dataType = el.getAttribute('data-type');
                    if (dataType) obj.dataType = dataType;
                    const dataRole = el.getAttribute('data-role');
                    if (dataRole) obj.dataRole = dataRole;

                    // Include text for leaf nodes
                    if (el.children.length === 0 || el.children.length <= 2) {
                        const text = el.textContent?.trim();
                        if (text && text.length < 100) {
                            obj.text = text.slice(0, 80);
                        }
                    }

                    // Recurse
                    if (includeStructure && el.children.length > 0) {
                        const children = [];
                        for (const child of el.children) {
                            const simplified = simplifyElement(child, depth + 1);
                            if (simplified) {
                                children.push(simplified);
                                if (children.length >= 10) break;
                            }
                        }
                        if (children.length > 0) obj.children = children;
                    }

                    return obj;
                }

                // Get main content area
                const main = document.querySelector('main, #main, .main, [role="main"]') || document.body;
                const structure = includeStructure ? simplifyElement(main, 0) : null;

                // Count repeated classes (for finding product grids)
                const classCounts = {};
                document.querySelectorAll('*').forEach(el => {
                    if (el.className && typeof el.className === 'string') {
                        el.className.split(' ').forEach(cls => {
                            if (cls && cls.length > 2 && cls.length < 50 && /^[a-zA-Z]/.test(cls)) {
                                classCounts[cls] = (classCounts[cls] || 0) + 1;
                            }
                        });
                    }
                });

                // Filter to interesting repeated classes (likely item containers)
                const repeatedClasses = Object.entries(classCounts)
                    .filter(([k, v]) => v >= 5 && v <= 200)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 20)
                    .map(([cls, count]) => ({ class: '.' + cls, count }));

                // Get text with prices
                const pricePattern = /\\$\\d+(?:,\\d+)?(?:\\.\\d+)?/g;
                const textWithPrices = [];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const text = walker.currentNode.textContent?.trim();
                    if (text && pricePattern.test(text) && text.length < 200) {
                        textWithPrices.push(text);
                        if (textWithPrices.length >= 15) break;
                    }
                }

                // Get semantic containers
                const semanticContainers = [];
                ['header', 'nav', 'main', 'aside', 'footer', 'article', 'section'].forEach(tag => {
                    const els = document.querySelectorAll(tag);
                    if (els.length > 0) {
                        semanticContainers.push({ tag, count: els.length });
                    }
                });

                // CRITICAL: Find all data-testid elements (these are STABLE selectors)
                // data-testid is used by testing frameworks and is designed to be stable
                const dataTestIdElements = [];
                document.querySelectorAll('[data-testid]').forEach(el => {
                    const testId = el.getAttribute('data-testid');
                    const tag = el.tagName.toLowerCase();
                    const rect = el.getBoundingClientRect();
                    // Only include visible elements with reasonable size
                    if (rect.width > 50 && rect.height > 50) {
                        dataTestIdElements.push({
                            selector: `[data-testid="${testId}"]`,
                            tag: tag,
                            testId: testId,
                            size: { width: Math.round(rect.width), height: Math.round(rect.height) },
                            childCount: el.children.length
                        });
                    }
                });

                // Also find elements with id attributes (also stable)
                const idElements = [];
                document.querySelectorAll('[id]').forEach(el => {
                    const id = el.id;
                    // Skip common noise like React IDs
                    if (id && !id.startsWith('__') && !id.startsWith(':r') && id.length < 50) {
                        const tag = el.tagName.toLowerCase();
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 50 && rect.height > 50) {
                            idElements.push({
                                selector: `#${id}`,
                                tag: tag,
                                id: id,
                                size: { width: Math.round(rect.width), height: Math.round(rect.height) },
                                childCount: el.children.length
                            });
                        }
                    }
                });

                // Check for common e-commerce indicators
                const hasSearchResults = !!document.querySelector('[class*="search-result"], [class*="product-list"], [class*="product-grid"]');
                const hasFilters = !!document.querySelector('[class*="filter"], [class*="facet"], [class*="refine"]');
                const hasPagination = !!document.querySelector('[class*="pagination"], [class*="pager"], .page-numbers, .pageNav');

                // Extract pagination metadata (page count, current page)
                // Default to 1 page if no pagination found (single-page content)
                let paginationInfo = { totalPages: 1, currentPage: 1 };
                if (hasPagination) {
                    const pagNav = document.querySelector('[class*="pagination"], [class*="pager"], .page-numbers, .pageNav, nav[class*="page"]');
                    if (pagNav) {
                        // Look for "Page X of Y" text pattern
                        const pageOfMatch = pagNav.textContent.match(/page\\s*(\\d+)\\s*of\\s*(\\d+)/i);
                        if (pageOfMatch) {
                            paginationInfo = {
                                currentPage: parseInt(pageOfMatch[1]),
                                totalPages: parseInt(pageOfMatch[2])
                            };
                        } else {
                            // Look for numbered page links (get the highest number)
                            const pageLinks = pagNav.querySelectorAll('a[href*="page"], a[href*="/page-"]');
                            let maxPage = 1;
                            pageLinks.forEach(link => {
                                const pageMatch = link.textContent.match(/^(\\d+)$/);
                                if (pageMatch) {
                                    const pageNum = parseInt(pageMatch[1]);
                                    if (pageNum > maxPage) maxPage = pageNum;
                                }
                                // Also check href for page number
                                const hrefMatch = link.href.match(/page[=-](\\d+)/i);
                                if (hrefMatch) {
                                    const pageNum = parseInt(hrefMatch[1]);
                                    if (pageNum > maxPage) maxPage = pageNum;
                                }
                            });
                            paginationInfo = { totalPages: maxPage, currentPage: 1 };
                        }
                    }
                }

                return {
                    url: window.location.href,
                    title: document.title,
                    searchParams: Object.fromEntries(new URLSearchParams(window.location.search)),
                    structure: structure,
                    repeatedClasses: repeatedClasses,
                    textWithPrices: textWithPrices,
                    semanticContainers: semanticContainers,
                    // STABLE SELECTORS - these should be preferred over class names
                    stableSelectors: {
                        dataTestId: dataTestIdElements.slice(0, 30),  // Elements with data-testid
                        ids: idElements.slice(0, 30)  // Elements with id attribute
                    },
                    indicators: {
                        hasSearchResults,
                        hasFilters,
                        hasPagination
                    },
                    paginationInfo: paginationInfo
                };
            }''', include_structure)

            return context or {}

        except Exception as e:
            logger.error(f"[DOMSampler] Error getting page context: {e}")
            return {"error": str(e), "url": page.url if page else "unknown"}

    async def get_element_html(
        self,
        page: 'Page',
        selector: str,
        max_length: int = 2000
    ) -> Optional[str]:
        """
        Get HTML for a specific element by selector.

        Args:
            page: Playwright page
            selector: CSS selector
            max_length: Maximum HTML length

        Returns:
            HTML string or None
        """
        try:
            html = await page.evaluate('''(config) => {
                const { selector, maxLength } = config;
                const el = document.querySelector(selector);
                if (!el) return null;
                return el.outerHTML.slice(0, maxLength);
            }''', {"selector": selector, "maxLength": max_length})

            return html

        except Exception as e:
            logger.error(f"[DOMSampler] Error getting element HTML: {e}")
            return None
