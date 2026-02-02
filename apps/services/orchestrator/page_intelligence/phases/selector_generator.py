"""
orchestrator/page_intelligence/phases/selector_generator.py

Phase 2: Selector Generator

Generates CSS selectors for extracting data from identified zones.
Uses actual HTML samples from zones to ensure selectors are precise.

Input docs:
- zones.json: Zones from Phase 1
- zone_html_samples.json: Actual HTML snippets from each zone

Output docs:
- selectors.json: CSS selectors for each zone's extractable elements
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List

from apps.services.orchestrator.page_intelligence.models import (
    Zone,
    ZoneSelectors,
    FieldSelector,
)
from apps.services.orchestrator.page_intelligence.llm_client import LLMClient, get_llm_client
from libs.gateway.recipe_loader import load_recipe

logger = logging.getLogger(__name__)


class SelectorGenerator:
    """
    Phase 2: Generate CSS selectors based on real HTML samples.

    Key principle: LLM sees REAL HTML from each zone, not guessed structures.
    This ensures generated selectors actually exist in the DOM.
    """

    def __init__(
        self,
        llm_client: LLMClient = None,
        llm_url: str = None,
        llm_model: str = None,
        debug_dir: str = None
    ):
        """
        Initialize selector generator.

        Args:
            llm_client: Shared LLM client (recommended)
            llm_url: URL for LLM API (if not using shared client)
            llm_model: Model name
            debug_dir: Directory to save input/output docs for debugging
        """
        self.llm_client = llm_client or get_llm_client(llm_url, llm_model)
        self.debug_dir = Path(debug_dir) if debug_dir else None

        # Load prompt from recipe
        recipe = load_recipe("browser/page_selector_generator")
        self.prompt = recipe.get_prompt()

    async def generate(
        self,
        zones: List[Zone],
        zone_html_samples: Dict[str, Dict[str, Any]]
    ) -> Dict[str, ZoneSelectors]:
        """
        Generate CSS selectors for identified zones.

        Args:
            zones: Zones from Phase 1
            zone_html_samples: HTML samples from DOMSampler.sample_zones()

        Returns:
            Dict mapping zone_type to ZoneSelectors
        """
        # Prepare input document
        input_doc = self._prepare_input_doc(zones, zone_html_samples)

        # Save input doc for debugging
        if self.debug_dir:
            self._save_debug_doc("selector_generator_input.json", input_doc)

        # Build prompt
        prompt = self._build_prompt(input_doc)

        # Call LLM
        result = await self.llm_client.call(prompt, max_tokens=2500)

        # Save output doc for debugging
        if self.debug_dir:
            self._save_debug_doc("selector_generator_output.json", result)

        # Parse result into models
        return self._parse_result(result)

    def _prepare_input_doc(
        self,
        zones: List[Zone],
        zone_html_samples: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Prepare input document for LLM."""
        zones_doc = []
        for zone in zones:
            zone_type = zone.zone_type.value if hasattr(zone.zone_type, 'value') else zone.zone_type
            zones_doc.append({
                "zone_type": zone_type,
                "confidence": zone.confidence,
                "dom_anchors": zone.dom_anchors,
                "item_count_estimate": zone.item_count_estimate
            })

        samples_doc = {}
        for zone_type, sample in zone_html_samples.items():
            samples_doc[zone_type] = {
                "sample_item_html": sample.get("sample_item_html", "")[:2500],
                "item_selector_hint": sample.get("item_selector_hint"),
                "item_count": sample.get("item_count", 0),
                "visible_text_samples": sample.get("visible_text_samples", [])[:10],
                "repeated_class": sample.get("repeated_class")
            }

        return {
            "zones": zones_doc,
            "zone_html_samples": samples_doc
        }

    def _build_prompt(self, input_doc: Dict[str, Any]) -> str:
        """Build prompt with truncated input."""
        zones_json = json.dumps(input_doc.get("zones", []), indent=2)
        samples_json = json.dumps(input_doc.get("zone_html_samples", {}), indent=2, default=str)

        # Truncate samples to fit token budget
        samples_json = self.llm_client.truncate_to_tokens(samples_json, 2000)

        return f"""{self.prompt}

---

## Zones (zones.json)

```json
{zones_json}
```

## Zone HTML Samples (zone_html_samples.json)

```json
{samples_json}
```

Now generate CSS selectors based on this actual HTML. Return JSON only.
"""

    def _parse_result(self, result: Dict[str, Any]) -> Dict[str, ZoneSelectors]:
        """Parse LLM result into typed models."""
        if "error" in result:
            logger.error(f"[SelectorGenerator] LLM error: {result.get('error')}")
            return {}

        selectors = {}
        zones_data = result.get("zones", {})

        for zone_type, zone_data in zones_data.items():
            try:
                fields = {}
                for field_name, field_data in zone_data.get("fields", {}).items():
                    if isinstance(field_data, dict):
                        fields[field_name] = FieldSelector(
                            selector=str(field_data.get("selector", "")),
                            attribute=str(field_data.get("attribute", "textContent")),
                            transform=field_data.get("transform")
                        )

                selectors[zone_type] = ZoneSelectors(
                    item_selector=str(zone_data.get("item_selector", "")),
                    fields=fields,
                    confidence=float(zone_data.get("confidence", 0.5))
                )
            except (TypeError, ValueError, KeyError) as e:
                logger.warning(f"[SelectorGenerator] Error parsing zone {zone_type}: {e}")

        return selectors

    def _save_debug_doc(self, filename: str, data: Dict[str, Any]):
        """Save document for debugging."""
        if not self.debug_dir:
            return

        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            path = self.debug_dir / filename

            def default_serializer(obj):
                if hasattr(obj, 'to_dict'):
                    return obj.to_dict()
                elif hasattr(obj, '__dict__'):
                    return obj.__dict__
                return str(obj)

            with open(path, 'w') as f:
                json.dump(data, f, indent=2, default=default_serializer)
            logger.debug(f"[SelectorGenerator] Saved debug doc: {path}")
        except (IOError, OSError) as e:
            logger.error(f"[SelectorGenerator] Error saving debug doc: {e}")
        except TypeError as e:
            logger.error(f"[SelectorGenerator] Serialization error in debug doc: {e}")
