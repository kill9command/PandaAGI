"""
orchestrator/page_intelligence/extractors/selector_extractor.py

Selector Extractor - CSS-based extraction (no LLM)

Fast, reliable extraction using CSS selectors from Phase 2.
Best for standard e-commerce grids with high-confidence selectors.
"""

import logging
import re
from typing import TYPE_CHECKING, List, Dict, Any, Optional

from apps.services.tool_server.page_intelligence.models import ZoneSelectors, FieldSelector

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class SelectorExtractor:
    """
    Extract data using CSS selectors.

    No LLM call - pure DOM traversal using selectors from Phase 2.
    """

    def __init__(self):
        pass

    async def extract(
        self,
        page: 'Page',
        zone_selectors: ZoneSelectors,
        max_items: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Extract items from a zone using CSS selectors.

        Args:
            page: Playwright page
            zone_selectors: Selectors from Phase 2
            max_items: Maximum items to extract

        Returns:
            List of extracted items with fields
        """
        if not zone_selectors.item_selector:
            logger.warning("[SelectorExtractor] No item selector provided")
            return []

        try:
            items = await page.evaluate('''(config) => {
                const { itemSelector, fields, maxItems } = config;

                const items = document.querySelectorAll(itemSelector);
                if (!items || items.length === 0) {
                    return { error: 'No items found', selector: itemSelector };
                }

                const extracted = [];

                for (let i = 0; i < Math.min(items.length, maxItems); i++) {
                    const item = items[i];
                    const data = { _index: i };

                    for (const [fieldName, fieldConfig] of Object.entries(fields)) {
                        try {
                            const el = item.querySelector(fieldConfig.selector);
                            if (!el) {
                                data[fieldName] = null;
                                continue;
                            }

                            let value;
                            const attr = fieldConfig.attribute || 'textContent';

                            if (attr === 'textContent') {
                                value = el.textContent?.trim();
                            } else if (attr === 'href' || attr === 'src') {
                                value = el[attr];
                            } else {
                                value = el.getAttribute(attr);
                            }

                            // Apply transforms
                            if (fieldConfig.transform === 'price' && value) {
                                // Extract price number
                                const match = value.match(/[$]?([\d,]+\.?\d*)/);
                                if (match) {
                                    value = parseFloat(match[1].replace(/,/g, ''));
                                }
                            } else if (fieldConfig.transform === 'rating' && value) {
                                // Extract rating number
                                const match = value.match(/([\d.]+)/);
                                if (match) {
                                    value = parseFloat(match[1]);
                                }
                            } else if (fieldConfig.transform === 'trim' && value) {
                                value = value.trim();
                            }

                            data[fieldName] = value;
                        } catch (e) {
                            data[fieldName] = null;
                            data['_error_' + fieldName] = e.message;
                        }
                    }

                    extracted.push(data);
                }

                return {
                    items: extracted,
                    total_found: items.length,
                    extracted_count: extracted.length
                };
            }''', {
                "itemSelector": zone_selectors.item_selector,
                "fields": {k: v.to_dict() for k, v in zone_selectors.fields.items()},
                "maxItems": max_items
            })

            if "error" in items:
                logger.warning(f"[SelectorExtractor] {items.get('error')}: {items.get('selector')}")
                return []

            logger.info(f"[SelectorExtractor] Extracted {items.get('extracted_count')}/{items.get('total_found')} items")
            return items.get("items", [])

        except Exception as e:
            logger.error(f"[SelectorExtractor] Extraction error: {e}")
            return []

    async def extract_single(
        self,
        page: 'Page',
        selectors: Dict[str, FieldSelector]
    ) -> Dict[str, Any]:
        """
        Extract a single item (e.g., PDP) using field selectors.

        Args:
            page: Playwright page
            selectors: Field selectors (not relative to item container)

        Returns:
            Dict with extracted field values
        """
        try:
            result = await page.evaluate('''(fields) => {
                const data = {};

                for (const [fieldName, fieldConfig] of Object.entries(fields)) {
                    try {
                        const el = document.querySelector(fieldConfig.selector);
                        if (!el) {
                            data[fieldName] = null;
                            continue;
                        }

                        let value;
                        const attr = fieldConfig.attribute || 'textContent';

                        if (attr === 'textContent') {
                            value = el.textContent?.trim();
                        } else if (attr === 'href' || attr === 'src') {
                            value = el[attr];
                        } else {
                            value = el.getAttribute(attr);
                        }

                        // Apply transforms
                        if (fieldConfig.transform === 'price' && value) {
                            const match = value.match(/[$]?([\d,]+\.?\d*)/);
                            if (match) {
                                value = parseFloat(match[1].replace(/,/g, ''));
                            }
                        }

                        data[fieldName] = value;
                    } catch (e) {
                        data[fieldName] = null;
                    }
                }

                return data;
            }''', {k: v.to_dict() for k, v in selectors.items()})

            return result

        except Exception as e:
            logger.error(f"[SelectorExtractor] Single extraction error: {e}")
            return {}

    async def validate_selectors(
        self,
        page: 'Page',
        zone_selectors: ZoneSelectors
    ) -> Dict[str, Any]:
        """
        Validate that selectors work on the current page.

        Returns validation result with match counts.
        """
        try:
            result = await page.evaluate('''(config) => {
                const { itemSelector, fields } = config;

                const validation = {
                    item_selector_matches: 0,
                    field_matches: {},
                    valid: false
                };

                // Check item selector
                const items = document.querySelectorAll(itemSelector);
                validation.item_selector_matches = items.length;

                if (items.length === 0) {
                    validation.error = 'Item selector matched 0 elements';
                    return validation;
                }

                // Check field selectors within first item
                const firstItem = items[0];
                for (const [fieldName, fieldConfig] of Object.entries(fields)) {
                    const el = firstItem.querySelector(fieldConfig.selector);
                    validation.field_matches[fieldName] = el ? 1 : 0;
                }

                // Valid if item selector works and at least one field matches
                const anyFieldMatches = Object.values(validation.field_matches).some(v => v > 0);
                validation.valid = items.length > 0 && anyFieldMatches;

                return validation;
            }''', {
                "itemSelector": zone_selectors.item_selector,
                "fields": {k: v.to_dict() for k, v in zone_selectors.fields.items()}
            })

            return result

        except Exception as e:
            logger.error(f"[SelectorExtractor] Validation error: {e}")
            return {"valid": False, "error": str(e)}
