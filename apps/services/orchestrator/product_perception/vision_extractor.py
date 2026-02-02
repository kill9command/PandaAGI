"""
Vision-based product extraction using EasyOCR + LLM.

Flow:
1. OCR extracts all text with bounding boxes
2. Group text into product "cards" by spatial proximity
3. LLM parses grouped text to extract structured product data
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import httpx

from .models import VisualProduct, BoundingBox, OCRItem
from .config import get_config

logger = logging.getLogger(__name__)

# Prompt cache for recipe-loaded prompts
_prompt_cache: Dict[str, str] = {}


def _load_prompt_via_recipe(recipe_name: str, category: str = "browser") -> str:
    """Load prompt via recipe system with inline fallback."""
    cache_key = f"{category}/{recipe_name}"
    if cache_key in _prompt_cache:
        return _prompt_cache[cache_key]
    try:
        from libs.gateway.recipe_loader import load_recipe
        recipe = load_recipe(f"{category}/{recipe_name}")
        content = recipe.get_prompt()
        _prompt_cache[cache_key] = content
        return content
    except Exception as e:
        logger.warning(f"Recipe {cache_key} not found: {e}")
        return ""


class VisionExtractor:
    """
    Vision-based product extraction using EasyOCR + LLM.

    Strategy:
    1. Run OCR to get all text with positions
    2. Group spatially-close text into product "cards"
    3. Use LLM to parse each card into structured product data
    """

    def __init__(
        self,
        llm_url: str,
        llm_model: str,
        llm_api_key: str,
        ocr_engine=None
    ):
        self.llm_url = llm_url
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self._ocr_engine = ocr_engine
        self.config = get_config()

    def _get_ocr_engine(self):
        """Lazy-load EasyOCR."""
        if self._ocr_engine is None:
            try:
                import easyocr
                self._ocr_engine = easyocr.Reader(
                    ['en'],
                    gpu=self.config.ocr_use_gpu,
                    verbose=False
                )
                logger.info(f"[VisionExtractor] EasyOCR initialized (GPU={self.config.ocr_use_gpu})")
            except Exception as e:
                logger.error(f"[VisionExtractor] Failed to initialize EasyOCR: {e}")
                raise
        return self._ocr_engine

    async def extract(self, screenshot_path: str, query: str) -> List[VisualProduct]:
        """
        Extract products from screenshot using OCR + LLM.

        Args:
            screenshot_path: Path to screenshot PNG file
            query: User's search query (for context)

        Returns:
            List of VisualProduct with title, price, bbox
        """
        import asyncio

        # Step 1: OCR extraction (run in executor to avoid blocking event loop)
        loop = asyncio.get_event_loop()
        ocr_timeout = self.config.ocr_timeout_ms / 1000.0

        try:
            ocr_items = await asyncio.wait_for(
                loop.run_in_executor(None, self._run_ocr, screenshot_path),
                timeout=ocr_timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"[VisionExtractor] OCR timed out after {ocr_timeout}s")
            return []

        logger.info(f"[VisionExtractor] OCR found {len(ocr_items)} text regions")

        if not ocr_items:
            logger.warning("[VisionExtractor] No text found in screenshot")
            return []

        # Step 1.5: Check if this is a "no results" page before proceeding
        no_results_detected, no_results_phrase = self._detect_no_results_page(ocr_items)
        if no_results_detected:
            logger.warning(f"[VisionExtractor] Detected 'no results' page: '{no_results_phrase}'")
            # Return empty list with clear logging - this is expected, not an error
            return []

        # Step 2: Group into product cards by spatial proximity
        product_groups = self._group_into_products(ocr_items)
        logger.info(f"[VisionExtractor] Grouped into {len(product_groups)} potential products")

        if not product_groups:
            logger.warning("[VisionExtractor] No product groups detected")
            return []

        # Step 3: LLM parsing to extract structured data
        products = await self._llm_parse_products(product_groups, query)
        logger.info(f"[VisionExtractor] LLM extracted {len(products)} products")

        # Step 4: Filter out sponsored/ad products
        products = self._filter_sponsored_products(products)

        return products

    def _run_ocr(self, screenshot_path: str) -> List[OCRItem]:
        """
        Run EasyOCR and return structured results.

        Args:
            screenshot_path: Path to image file

        Returns:
            List of OCRItem with text, bbox, confidence
        """
        try:
            ocr = self._get_ocr_engine()
            # EasyOCR returns: list of (bbox, text, confidence)
            # bbox format: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            result = ocr.readtext(screenshot_path)

            if not result:
                return []

            ocr_items = []
            min_confidence = self.config.ocr_confidence_min

            for item in result:
                if len(item) < 3:
                    continue

                bbox_points, text, confidence = item[0], item[1], item[2]

                # Skip low confidence or empty text
                if confidence < min_confidence or not text.strip():
                    continue

                # Convert polygon to simple bbox
                x_coords = [p[0] for p in bbox_points]
                y_coords = [p[1] for p in bbox_points]

                bbox = BoundingBox(
                    x=int(min(x_coords)),
                    y=int(min(y_coords)),
                    width=int(max(x_coords) - min(x_coords)),
                    height=int(max(y_coords) - min(y_coords))
                )

                ocr_items.append(OCRItem(
                    text=text.strip(),
                    bbox=bbox,
                    confidence=confidence
                ))

            return ocr_items

        except Exception as e:
            logger.error(f"[VisionExtractor] OCR failed: {e}")
            return []

    def _detect_no_results_page(self, ocr_items: List[OCRItem]) -> Tuple[bool, str]:
        """
        Detect if the page is explicitly showing a "no results" message.

        This prevents the vision extractor from trying to parse error pages
        as product listings.

        Args:
            ocr_items: List of OCR text items from the page

        Returns:
            Tuple of (is_no_results_page, matched_phrase)
        """
        # Combine all OCR text for analysis
        all_text = ' '.join(item.text for item in ocr_items).lower()

        # Common "no results" phrases across retailers
        no_results_phrases = [
            # Explicit 0 count
            'we found 0 items',
            'found 0 items',
            '0 items found',
            '0 results found',
            '0 results for',
            '0 products found',
            # No results messages
            'no items found',
            'no results found',
            'no products found',
            'no matching products',
            'no items match',
            'no matches found',
            # Sorry messages
            'sorry, no results',
            'sorry, we couldn\'t find',
            'we couldn\'t find any',
            'we could not find',
            # Did not match
            'did not match any products',
            'didn\'t match any products',
            'does not match any',
            'nothing matched your search',
            'your search did not match',
            # Empty state messages
            'try a different search',
            'try searching for something else',
            'no items available',
            'currently unavailable',
            # Newegg specific
            'we have found 0 items that match',
        ]

        for phrase in no_results_phrases:
            if phrase in all_text:
                return (True, phrase)

        return (False, '')

    def _group_into_products(self, ocr_items: List[OCRItem]) -> List[List[OCRItem]]:
        """
        Group OCR text items into product cards based on spatial proximity.

        Strategy:
        - Sort items by Y position (top to bottom)
        - Group items that are vertically close
        - Filter groups that look like products (have price pattern)
        """
        if not ocr_items:
            return []

        config = self.config
        y_threshold = config.y_group_threshold
        max_groups = config.max_ocr_groups

        # Sort by Y position (top to bottom), then X (left to right)
        sorted_items = sorted(ocr_items, key=lambda x: (x.bbox.y, x.bbox.x))

        # Group by vertical proximity
        groups = []
        current_group = []
        current_group_y = None

        for item in sorted_items:
            if not current_group:
                current_group.append(item)
                current_group_y = item.bbox.y
                continue

            # Check vertical distance from group
            y_diff = item.bbox.y - current_group_y

            if y_diff < y_threshold:
                # Close enough, add to current group
                current_group.append(item)
                # Update group Y to average
                current_group_y = sum(i.bbox.y for i in current_group) / len(current_group)
            else:
                # Too far, start new group
                if current_group:
                    groups.append(current_group)
                current_group = [item]
                current_group_y = item.bbox.y

        # Don't forget last group
        if current_group:
            groups.append(current_group)

        logger.debug(f"[VisionExtractor] Spatial grouping created {len(groups)} groups")

        # Price patterns (for logging and optional filtering)
        # Patterns to match: $1,299.99, $1299.99, $999, $1,299
        price_pattern = re.compile(
            r'\$\s*[\d,]+(?:\.\d{2})?'    # $X,XXX or $X,XXX.XX (with optional space)
        )
        # Also match prices without $ but with .99 or .00 endings
        alt_price_pattern = re.compile(
            r'[\d,]+\.\d{2}'  # X,XXX.XX format (must have decimal)
        )

        product_groups = []
        groups_with_price = 0
        groups_without_price = 0

        for i, group in enumerate(groups):
            group_text = ' '.join(item.text for item in group)
            has_price = price_pattern.search(group_text) is not None
            has_alt_price = alt_price_pattern.search(group_text) is not None
            has_any_price = has_price or has_alt_price

            if has_any_price:
                groups_with_price += 1
            else:
                groups_without_price += 1

            # Log all groups for debugging
            if i < 15:
                logger.info(
                    f"[VisionExtractor] Group {i}: {len(group)} items, "
                    f"has_price={has_any_price}, text='{group_text[:150]}...'"
                )

            # Decision: include group or not
            if config.require_price_pattern:
                # Old behavior: only include groups with price patterns
                if has_any_price:
                    product_groups.append(group)
            else:
                # New behavior: include ALL groups, let LLM decide what's a product
                # This is more robust as LLM can identify products even without visible price
                product_groups.append(group)

            if len(product_groups) >= max_groups:
                break

        # Log filtering summary
        logger.info(
            f"[VisionExtractor] Group filtering summary: "
            f"{groups_with_price} with price, {groups_without_price} without price, "
            f"{len(product_groups)} sent to LLM (require_price_pattern={config.require_price_pattern})"
        )

        # If no groups at all, log warning
        if not product_groups and groups:
            all_text = ' '.join(item.text for g in groups for item in g)
            logger.warning(
                f"[VisionExtractor] No groups to process. "
                f"Sample text: '{all_text[:500]}...'"
            )

        return product_groups

    async def _llm_parse_products(
        self,
        product_groups: List[List[OCRItem]],
        query: str
    ) -> List[VisualProduct]:
        """
        Use LLM to parse OCR text groups into structured products.

        Args:
            product_groups: Groups of OCR items representing products
            query: User's search query

        Returns:
            List of VisualProduct
        """
        if not product_groups:
            return []

        # Build prompt with all product groups
        groups_text = self._format_groups_for_prompt(product_groups)

        # Debug: Log OCR text being sent to LLM
        logger.debug(f"[VisionExtractor] OCR groups text:\n{groups_text[:1500]}...")

        # Load prompt via recipe system
        base_prompt = _load_prompt_via_recipe("ocr_items", "browser")
        if not base_prompt:
            logger.warning("[VisionExtractor] OCR items prompt not found via recipe")
            base_prompt = """Extract items for sale from OCR text groups. Return JSON array with title, price, price_numeric fields. Return ONLY the JSON array."""

        prompt = f"""{base_prompt}

## Current Task

**User's Search Query:** "{query}"

**OCR Text Groups:**
{groups_text}

Return ONLY the JSON array. Match items to the user's query: "{query}"."""

        try:
            timeout = self.config.llm_timeout_ms / 1000.0

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.llm_url}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.llm_api_key}"},
                    json={
                        "model": self.llm_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 2500
                    }
                )

                if response.status_code != 200:
                    logger.error(f"[VisionExtractor] LLM returned {response.status_code}")
                    return []

                result = response.json()
                content = result.get('choices', [{}])[0].get('message', {}).get('content', '')

                # Debug: Log raw LLM response
                logger.debug(f"[VisionExtractor] LLM raw response: {content[:500]}...")

                # Parse JSON from response
                products_data = self._extract_json_array(content)

                if not products_data:
                    logger.warning(f"[VisionExtractor] LLM returned no products. Raw: {content[:300]}...")
                    # FALLBACK: Try with all OCR text in a single block
                    logger.info("[VisionExtractor] Trying fallback: sending all OCR text as single block")
                    products_data = await self._llm_fallback_all_text(product_groups, query)
                    if not products_data:
                        logger.warning("[VisionExtractor] Fallback also returned no products")
                        return []

                # Convert to VisualProduct objects
                products = []
                used_groups = set()  # Track which groups have been matched

                for i, p in enumerate(products_data):
                    title = p.get('title', '').strip()
                    price_str = p.get('price', '')
                    price_numeric = p.get('price_numeric')

                    # Skip empty entries
                    if not title or len(title) < 3:
                        continue

                    # Find the OCR group that best matches this product
                    matched_idx, bbox_item = self._find_matching_group(
                        title, price_str, product_groups
                    )

                    if matched_idx is not None and bbox_item is not None:
                        # Use the matched group and bbox item
                        used_groups.add(matched_idx)
                        bbox = bbox_item.bbox
                        raw_lines = [item.text for item in product_groups[matched_idx]]
                        avg_confidence = sum(
                            item.confidence for item in product_groups[matched_idx]
                        ) / len(product_groups[matched_idx])

                        logger.info(
                            f"[VisionExtractor] Product '{title[:40]}...' matched to group {matched_idx}, "
                            f"bbox at Y={bbox.y} from item '{bbox_item.text[:30]}...'"
                        )
                    elif i < len(product_groups) and product_groups[i] and i not in used_groups:
                        # Fallback: use index-based matching if no text match found
                        # But prefer price-containing item within the group
                        group = product_groups[i]
                        price_pattern = re.compile(r'\$\s*[\d,]+(?:\.\d{2})?')
                        price_item = next(
                            (item for item in group if price_pattern.search(item.text)),
                            None
                        )
                        bbox_item = price_item if price_item else group[0]
                        bbox = bbox_item.bbox
                        raw_lines = [item.text for item in group]
                        avg_confidence = sum(item.confidence for item in group) / len(group)

                        logger.info(
                            f"[VisionExtractor] Product '{title[:40]}...' using fallback group {i}, "
                            f"bbox at Y={bbox.y} from item '{bbox_item.text[:30]}...'"
                        )
                    else:
                        bbox = BoundingBox(0, 0, 0, 0)
                        raw_lines = []
                        avg_confidence = 0.7
                        logger.warning(
                            f"[VisionExtractor] Product '{title[:40]}...' has no matching OCR group, "
                            f"using zero bbox"
                        )

                    # Parse price if not provided
                    if price_numeric is None and price_str:
                        price_numeric = VisualProduct.parse_price(price_str)

                    products.append(VisualProduct(
                        title=title,
                        price=price_str,
                        price_numeric=price_numeric,
                        bbox=bbox,
                        confidence=avg_confidence * 0.9,  # Slight discount for LLM extraction
                        raw_ocr_lines=raw_lines
                    ))

                return products

        except httpx.TimeoutException:
            logger.error("[VisionExtractor] LLM request timed out")
            return []
        except Exception as e:
            logger.error(f"[VisionExtractor] LLM parsing failed: {e}")
            return []

    def _format_groups_for_prompt(self, product_groups: List[List[OCRItem]]) -> str:
        """Format OCR groups for LLM prompt."""
        parts = []

        for i, group in enumerate(product_groups[:self.config.max_ocr_groups]):
            group_lines = [item.text for item in group]
            parts.append(f"\n--- Group {i + 1} ---")
            parts.append('\n'.join(group_lines))

        return '\n'.join(parts)

    def _find_matching_group(
        self,
        title: str,
        price_str: str,
        product_groups: List[List[OCRItem]]
    ) -> Tuple[Optional[int], Optional[OCRItem]]:
        """
        Find the OCR group that best matches a product title and price.

        Returns:
            Tuple of (group_index, best_bbox_item) or (None, None) if no match
        """
        if not title:
            return None, None

        # Normalize title for matching
        title_lower = title.lower()
        title_words = set(title_lower.split())

        # Price pattern for finding price items
        price_pattern = re.compile(r'\$\s*[\d,]+(?:\.\d{2})?')

        best_match_idx = None
        best_match_score = 0
        best_bbox_item = None

        for idx, group in enumerate(product_groups):
            if not group:
                continue

            # Calculate match score based on word overlap
            group_text = ' '.join(item.text for item in group).lower()
            group_words = set(group_text.split())

            # Word overlap score
            overlap = len(title_words & group_words)
            if overlap == 0:
                continue

            score = overlap / len(title_words) if title_words else 0

            # Bonus if price matches
            if price_str:
                price_clean = price_str.replace(' ', '')
                if price_clean in group_text.replace(' ', ''):
                    score += 0.5

            if score > best_match_score:
                best_match_score = score
                best_match_idx = idx

                # Find best bbox item within this group
                # Priority: 1) item with price, 2) item with brand/model text, 3) center of group
                price_item = None
                title_item = None

                for item in group:
                    item_lower = item.text.lower()

                    # Check for price
                    if price_pattern.search(item.text):
                        price_item = item

                    # Check for title word matches
                    if any(word in item_lower for word in title_words if len(word) > 3):
                        if title_item is None or len(item.text) > len(title_item.text):
                            title_item = item

                # Prefer price item (usually in product card area, not header)
                if price_item:
                    best_bbox_item = price_item
                elif title_item:
                    best_bbox_item = title_item
                else:
                    # Fall back to item closest to center Y of group
                    y_positions = [item.bbox.y for item in group]
                    center_y = sum(y_positions) / len(y_positions)
                    best_bbox_item = min(group, key=lambda i: abs(i.bbox.y - center_y))

        if best_match_idx is not None:
            logger.debug(
                f"[VisionExtractor] Matched title '{title[:40]}...' to group {best_match_idx} "
                f"(score={best_match_score:.2f}, bbox_item='{best_bbox_item.text[:30] if best_bbox_item else 'None'}...')"
            )

        return best_match_idx, best_bbox_item

    async def _llm_fallback_all_text(
        self,
        product_groups: List[List[OCRItem]],
        query: str
    ) -> List[Dict]:
        """
        Fallback: Send all OCR text as a single block for LLM to find products.

        Used when grouped approach returns empty - the grouping might have
        been too aggressive or split products incorrectly.
        """
        # Collect all OCR text
        all_text_items = []
        for group in product_groups:
            for item in group:
                all_text_items.append(item.text)

        all_text = ' '.join(all_text_items)

        if len(all_text) < 50:
            return []

        # Load prompt via recipe system
        base_prompt = _load_prompt_via_recipe("raw_ocr", "browser")
        if not base_prompt:
            logger.warning("[VisionExtractor] Raw OCR prompt not found via recipe")
            base_prompt = """Extract items for sale from raw OCR text. Return JSON array with title, price, price_numeric fields. Return ONLY the JSON array."""

        prompt = f"""{base_prompt}

## Current Task

**User's Search Query:** "{query}"

**Raw OCR Text:**
{all_text[:3000]}

Return a JSON array of items found that match: "{query}".
Return [] only if you truly cannot find any relevant listings."""

        try:
            timeout = self.config.llm_timeout_ms / 1000.0

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.llm_url}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.llm_api_key}"},
                    json={
                        "model": self.llm_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,  # Slightly higher for creative reconstruction
                        "max_tokens": 2000
                    }
                )

                if response.status_code != 200:
                    logger.error(f"[VisionExtractor] Fallback LLM returned {response.status_code}")
                    return []

                result = response.json()
                content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                return self._extract_json_array(content)

        except Exception as e:
            logger.error(f"[VisionExtractor] Fallback LLM failed: {e}")
            return []

    def _extract_json_array(self, text: str) -> List[Dict]:
        """Extract JSON array from LLM response."""
        if not text:
            return []

        # Try direct parse
        try:
            data = json.loads(text.strip())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # Try to find JSON array in text
        # Look for [ ... ] pattern
        match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # Try extracting from markdown code block
        code_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if code_match:
            try:
                return json.loads(code_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        logger.warning(f"[VisionExtractor] Could not parse JSON from: {text[:200]}...")
        return []

    def _filter_sponsored_products(self, products: List[VisualProduct]) -> List[VisualProduct]:
        """
        Filter out sponsored/advertisement products from extraction results.

        Retailers like Amazon, BestBuy, Walmart inject sponsored listings into
        search results. These are often irrelevant to the user's search and
        can pollute product comparisons.

        Args:
            products: List of extracted products

        Returns:
            Filtered list with sponsored products removed
        """
        if not products:
            return products

        # Patterns that indicate sponsored/ad content
        # These appear in product titles, sometimes as prefixes
        sponsored_title_patterns = [
            # Direct sponsored indicators
            'sponsored',
            'advertisement',
            'ad ',  # "Ad " prefix (space prevents matching "adapter")
            '[ad]',
            '(ad)',
            'promoted',
            'featured partner',
            'partner product',

            # Brand-specific ad indicators
            'nimo',       # BestBuy fake brand from ads
            'shop now',   # CTA in ads
            'learn more',
            'see deal',

            # Ad network indicators that might appear in OCR
            'adchoices',
            'ad choice',
            'why this ad',
        ]

        # URL patterns that indicate sponsored products (if URL available)
        sponsored_url_patterns = [
            '/sponsored/',
            'aax-us-east',  # Amazon ad server
            '/slredirect/',
            'clicktracking',
            '/gp/r.html',   # Amazon redirect
            '/sspa/',       # Amazon sponsored products
        ]

        # Title patterns that indicate it's NOT a real product
        non_product_patterns = [
            'free shipping',
            'best seller',
            'top rated',
            'trending now',
            'people also bought',
            'customers also viewed',
            'similar items',
            'you may also like',
            'compare similar',
            'view all',
            'see all',
            'show more',
        ]

        filtered_products = []
        filtered_count = 0

        for product in products:
            title_lower = product.title.lower() if product.title else ''

            # Check for sponsored indicators in title
            is_sponsored = any(pattern in title_lower for pattern in sponsored_title_patterns)

            # Check for non-product patterns
            is_non_product = any(pattern in title_lower for pattern in non_product_patterns)

            # Check raw OCR lines for sponsored indicators
            if product.raw_ocr_lines:
                ocr_text = ' '.join(product.raw_ocr_lines).lower()
                is_sponsored = is_sponsored or any(
                    pattern in ocr_text for pattern in sponsored_title_patterns
                )

            if is_sponsored:
                logger.info(
                    f"[VisionExtractor] Filtered SPONSORED product: '{product.title[:50]}...'"
                )
                filtered_count += 1
            elif is_non_product:
                logger.info(
                    f"[VisionExtractor] Filtered NON-PRODUCT: '{product.title[:50]}...'"
                )
                filtered_count += 1
            else:
                filtered_products.append(product)

        if filtered_count > 0:
            logger.info(
                f"[VisionExtractor] Filtered {filtered_count} sponsored/non-products, "
                f"kept {len(filtered_products)} valid products"
            )

        return filtered_products
