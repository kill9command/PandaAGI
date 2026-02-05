"""
orchestrator/page_intelligence/phases/zone_identifier.py

Phase 1: Zone Identifier

Analyzes a webpage to identify semantic zones (header, nav, product_grid, etc.)
using LLM with document-based IO.

Input docs:
- page_context.json: URL, title, DOM structure, repeated classes

Output docs:
- zones.json: Identified zones with dom_anchors and bounds
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from apps.services.tool_server.page_intelligence.models import (
    Zone,
    ZoneType,
    PageType,
    Bounds,
    OCRTextBlock,
    PageNotice,
    AvailabilityStatus,
)
from apps.services.tool_server.page_intelligence.llm_client import LLMClient, get_llm_client
from libs.gateway.llm.recipe_loader import load_recipe

logger = logging.getLogger(__name__)


class ZoneIdentifier:
    """
    Phase 1: Identify semantic zones on a webpage.

    Uses LLM to analyze page structure and identify zones like:
    - header, navigation, search_filters
    - product_grid, product_details
    - content_prose, footer, ads, pagination
    """

    def __init__(
        self,
        llm_client: LLMClient = None,
        llm_url: str = None,
        llm_model: str = None,
        debug_dir: str = None
    ):
        """
        Initialize zone identifier.

        Args:
            llm_client: Shared LLM client (recommended)
            llm_url: URL for LLM API (if not using shared client)
            llm_model: Model name
            debug_dir: Directory to save input/output docs for debugging
        """
        self.llm_client = llm_client or get_llm_client(llm_url, llm_model)
        self.debug_dir = Path(debug_dir) if debug_dir else None

        # Load prompt from recipe
        recipe = load_recipe("browser/page_zone_identifier")
        self.prompt = recipe.get_prompt()

    async def identify(
        self,
        page_context: Dict[str, Any],
        ocr_blocks: List[OCRTextBlock] = None
    ) -> Dict[str, Any]:
        """
        Identify zones on the page.

        Args:
            page_context: Page context from DOMSampler.get_page_context()
            ocr_blocks: Optional OCR text blocks with bounds

        Returns:
            {
                "zones": [Zone, ...],
                "page_type": PageType,
                "has_products": bool
            }
        """
        # Prepare input document
        input_doc = self._prepare_input_doc(page_context, ocr_blocks)

        # Save input doc for debugging
        if self.debug_dir:
            self._save_debug_doc("zone_identifier_input.json", input_doc)

        # Build prompt with token budget awareness
        prompt = self._build_prompt(input_doc)

        # Call LLM
        result = await self.llm_client.call(prompt, max_tokens=2000)

        # Save output doc for debugging
        if self.debug_dir:
            self._save_debug_doc("zone_identifier_output.json", result)

        # Parse result into models
        return self._parse_result(result)

    def _prepare_input_doc(
        self,
        page_context: Dict[str, Any],
        ocr_blocks: List[OCRTextBlock] = None
    ) -> Dict[str, Any]:
        """Prepare input document for LLM."""
        doc = {
            "url": page_context.get("url", ""),
            "title": page_context.get("title", ""),
            "search_params": page_context.get("searchParams", {}),
            "dom_structure": page_context.get("structure"),
            "repeated_classes": page_context.get("repeatedClasses", []),
            "text_with_prices": page_context.get("textWithPrices", []),
            "semantic_containers": page_context.get("semanticContainers", []),
            # CRITICAL: Stable selectors should be PREFERRED over class names
            "stable_selectors": page_context.get("stableSelectors", {}),
            "indicators": page_context.get("indicators", {})
        }

        if ocr_blocks:
            doc["ocr_text_blocks"] = [b.to_dict() for b in ocr_blocks[:20]]

        return doc

    def _build_prompt(self, input_doc: Dict[str, Any]) -> str:
        """Build prompt with truncated input to stay within token budget."""
        # Truncate input to ~5000 chars (~1250 tokens)
        input_json = json.dumps(input_doc, indent=2, default=str)
        input_json = self.llm_client.truncate_to_tokens(input_json, 1500)

        return f"""{self.prompt}

---

## Page Context (page_context.json)

```json
{input_json}
```

Now analyze this page and return zones JSON only.
"""

    def _parse_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Parse LLM result into typed models."""
        if "error" in result:
            logger.error(f"[ZoneIdentifier] LLM error: {result.get('error')}")
            return {
                "zones": [],
                "page_type": PageType.OTHER,
                "has_products": False,
                "page_notices": [],
                "availability_status": AvailabilityStatus.UNKNOWN,
                "purchase_constraints": [],
                "error": result.get("error")
            }

        # Parse zones
        zones = []
        for z_data in result.get("zones", []):
            try:
                zone_type_str = z_data.get("zone_type", "unknown")
                try:
                    zone_type = ZoneType(zone_type_str)
                except ValueError:
                    zone_type = ZoneType.UNKNOWN
                    logger.debug(f"[ZoneIdentifier] Unknown zone type: {zone_type_str}")

                bounds = None
                if z_data.get("bounds"):
                    bounds = Bounds.from_dict(z_data["bounds"])

                zone = Zone(
                    zone_type=zone_type,
                    confidence=float(z_data.get("confidence", 0.5)),
                    dom_anchors=z_data.get("dom_anchors", []),
                    bounds=bounds,
                    item_count_estimate=int(z_data.get("item_count_estimate", 0)),
                    notes=str(z_data.get("notes", ""))
                )
                zones.append(zone)
            except (TypeError, ValueError) as e:
                logger.warning(f"[ZoneIdentifier] Error parsing zone: {e}, data: {z_data}")

        # Parse page type
        page_type_str = result.get("page_type", "other")
        try:
            page_type = PageType(page_type_str)
        except ValueError:
            page_type = PageType.OTHER
            logger.debug(f"[ZoneIdentifier] Unknown page type: {page_type_str}")

        # Parse page notices
        page_notices = []
        for n_data in result.get("page_notices", []):
            try:
                notice = PageNotice(
                    notice_type=str(n_data.get("notice_type", "info")),
                    message=str(n_data.get("message", "")),
                    applies_to=str(n_data.get("applies_to", "page")),
                    confidence=float(n_data.get("confidence", 0.8))
                )
                page_notices.append(notice)
                logger.info(f"[ZoneIdentifier] Found page notice: {notice.notice_type} - {notice.message[:50]}...")
            except (TypeError, ValueError) as e:
                logger.warning(f"[ZoneIdentifier] Error parsing notice: {e}, data: {n_data}")

        # Parse availability status
        availability_str = result.get("availability_status", "unknown")
        try:
            availability_status = AvailabilityStatus(availability_str)
        except ValueError:
            availability_status = AvailabilityStatus.UNKNOWN
            logger.debug(f"[ZoneIdentifier] Unknown availability status: {availability_str}")

        # Log important availability info
        if availability_status != AvailabilityStatus.UNKNOWN:
            logger.info(f"[ZoneIdentifier] Availability status: {availability_status.value}")

        # Parse purchase constraints
        purchase_constraints = result.get("purchase_constraints", [])
        if not isinstance(purchase_constraints, list):
            purchase_constraints = []
        purchase_constraints = [str(c) for c in purchase_constraints]

        if purchase_constraints:
            logger.info(f"[ZoneIdentifier] Purchase constraints: {purchase_constraints}")

        # Determine has_list_content from zones or explicit flag
        has_list_content = bool(result.get("has_list_content", False))
        if not has_list_content:
            # Infer from zone types
            list_zone_types = {
                ZoneType.THREAD_LIST, ZoneType.POPULAR_TOPICS, ZoneType.POST_LIST,
                ZoneType.ARTICLE_LIST, ZoneType.NEWS_FEED, ZoneType.LIST_CONTENT,
                ZoneType.ITEM_GRID, ZoneType.PRODUCT_GRID
            }
            for zone in zones:
                if zone.zone_type in list_zone_types:
                    has_list_content = True
                    break

        return {
            "zones": zones,
            "page_type": page_type,
            "has_products": bool(result.get("has_products", False)),
            "has_list_content": has_list_content,
            "page_notices": page_notices,
            "availability_status": availability_status,
            "purchase_constraints": purchase_constraints
        }

    def _save_debug_doc(self, filename: str, data: Dict[str, Any]):
        """Save document for debugging."""
        if not self.debug_dir:
            return

        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            path = self.debug_dir / filename
            with open(path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            logger.debug(f"[ZoneIdentifier] Saved debug doc: {path}")
        except (IOError, OSError) as e:
            logger.error(f"[ZoneIdentifier] Error saving debug doc: {e}")
        except TypeError as e:
            logger.error(f"[ZoneIdentifier] Serialization error in debug doc: {e}")
