"""
orchestrator/page_intelligence/phases/strategy_selector.py

Phase 3: Strategy Selector

Chooses extraction strategy for each zone based on:
- Zone properties (type, confidence, bounds)
- Selector quality
- Extraction goals

Input docs:
- zones.json: Zones from Phase 1
- selectors.json: Selectors from Phase 2
- extraction_goal.json: What we're trying to extract

Output docs:
- strategy.json: Extraction strategy per zone
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List

from apps.services.tool_server.page_intelligence.models import (
    Zone,
    ZoneSelectors,
    ExtractionStrategy,
    StrategyMethod,
)
from apps.services.tool_server.page_intelligence.llm_client import LLMClient, get_llm_client
from libs.gateway.llm.recipe_loader import load_recipe

logger = logging.getLogger(__name__)


class StrategySelector:
    """
    Phase 3: Select extraction strategy for each zone.

    Strategies:
    - selector_extraction: Fast, reliable when selectors are good
    - vision_extraction: Works without DOM, for visual-heavy pages
    - hybrid_extraction: Best accuracy, combines both
    - prose_extraction: For unstructured content, contact-based pricing
    """

    def __init__(
        self,
        llm_client: LLMClient = None,
        llm_url: str = None,
        llm_model: str = None,
        debug_dir: str = None
    ):
        """
        Initialize strategy selector.

        Args:
            llm_client: Shared LLM client (recommended)
            llm_url: URL for LLM API (if not using shared client)
            llm_model: Model name
            debug_dir: Directory to save input/output docs for debugging
        """
        self.llm_client = llm_client or get_llm_client(llm_url, llm_model)
        self.debug_dir = Path(debug_dir) if debug_dir else None

        # Load prompt from recipe
        recipe = load_recipe("browser/page_strategy_selector")
        self.prompt = recipe.get_prompt()

    async def select(
        self,
        zones: List[Zone],
        selectors: Dict[str, ZoneSelectors],
        extraction_goal: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Select extraction strategy for each zone.

        Args:
            zones: Zones from Phase 1
            selectors: Selectors from Phase 2
            extraction_goal: What we're trying to extract

        Returns:
            {
                "strategies": [ExtractionStrategy, ...],
                "primary_zone": str,
                "skip_zones": [str, ...]
            }
        """
        # Prepare input document
        input_doc = self._prepare_input_doc(zones, selectors, extraction_goal)

        # Save input doc for debugging
        if self.debug_dir:
            self._save_debug_doc("strategy_selector_input.json", input_doc)

        # Build prompt
        prompt = self._build_prompt(input_doc)

        # Call LLM
        result = await self.llm_client.call(prompt, max_tokens=1500)

        # Save output doc for debugging
        if self.debug_dir:
            self._save_debug_doc("strategy_selector_output.json", result)

        # Parse result into models
        return self._parse_result(result)

    def _prepare_input_doc(
        self,
        zones: List[Zone],
        selectors: Dict[str, ZoneSelectors],
        extraction_goal: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare input document for LLM."""
        zones_doc = []
        for zone in zones:
            zone_type = zone.zone_type.value if hasattr(zone.zone_type, 'value') else zone.zone_type
            zones_doc.append({
                "zone_type": zone_type,
                "confidence": zone.confidence,
                "item_count_estimate": zone.item_count_estimate,
                "notes": zone.notes
            })

        selectors_doc = {}
        for zone_type, zone_sel in selectors.items():
            selectors_doc[zone_type] = {
                "item_selector": zone_sel.item_selector,
                "field_count": len(zone_sel.fields),
                "fields": list(zone_sel.fields.keys()),
                "confidence": zone_sel.confidence
            }

        return {
            "zones": zones_doc,
            "selectors": selectors_doc,
            "extraction_goal": extraction_goal
        }

    def _build_prompt(self, input_doc: Dict[str, Any]) -> str:
        """Build prompt."""
        return f"""{self.prompt}

---

## Zones (zones.json)

```json
{json.dumps(input_doc.get("zones", []), indent=2)}
```

## Selectors Summary (selectors.json)

```json
{json.dumps(input_doc.get("selectors", {}), indent=2)}
```

## Extraction Goal (extraction_goal.json)

```json
{json.dumps(input_doc.get("extraction_goal", {}), indent=2)}
```

Now select extraction strategies. Return JSON only.
"""

    def _parse_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Parse LLM result into typed models."""
        if "error" in result:
            logger.error(f"[StrategySelector] LLM error: {result.get('error')}")
            return {
                "strategies": [],
                "primary_zone": None,
                "skip_zones": []
            }

        strategies = []
        for s_data in result.get("strategies", []):
            try:
                method_str = s_data.get("method", "selector_extraction")
                try:
                    method = StrategyMethod(method_str)
                except ValueError:
                    method = StrategyMethod.SELECTOR_EXTRACTION
                    logger.debug(f"[StrategySelector] Unknown method: {method_str}")

                fallback = None
                fallback_str = s_data.get("fallback")
                if fallback_str:
                    try:
                        fallback = StrategyMethod(fallback_str)
                    except ValueError:
                        logger.debug(f"[StrategySelector] Unknown fallback: {fallback_str}")

                strategy = ExtractionStrategy(
                    zone=str(s_data.get("zone", "")),
                    method=method,
                    confidence=float(s_data.get("confidence", 0.5)),
                    fallback=fallback,
                    reason=str(s_data.get("reason", ""))
                )
                strategies.append(strategy)
            except (TypeError, ValueError, KeyError) as e:
                logger.warning(f"[StrategySelector] Error parsing strategy: {e}")

        return {
            "strategies": strategies,
            "primary_zone": result.get("primary_zone"),
            "skip_zones": result.get("skip_zones", [])
        }

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
                elif hasattr(obj, 'value'):
                    return obj.value
                return str(obj)

            with open(path, 'w') as f:
                json.dump(data, f, indent=2, default=default_serializer)
            logger.debug(f"[StrategySelector] Saved debug doc: {path}")
        except (IOError, OSError) as e:
            logger.error(f"[StrategySelector] Error saving debug doc: {e}")
        except TypeError as e:
            logger.error(f"[StrategySelector] Serialization error in debug doc: {e}")

    def select_default_strategy(
        self,
        zones: List[Zone],
        selectors: Dict[str, ZoneSelectors]
    ) -> Dict[str, Any]:
        """
        Select strategies without LLM call (fast fallback).

        Uses simple heuristics based on selector confidence.
        """
        strategies = []
        primary_zone = None
        skip_zones = []

        for zone in zones:
            zone_type = zone.zone_type.value if hasattr(zone.zone_type, 'value') else zone.zone_type

            # Skip non-content zones
            if zone_type in ["header", "footer", "ads", "navigation"]:
                skip_zones.append(zone_type)
                continue

            zone_sel = selectors.get(zone_type)

            if zone_sel and zone_sel.confidence > 0.7:
                method = StrategyMethod.SELECTOR_EXTRACTION
                fallback = StrategyMethod.HYBRID_EXTRACTION
            elif zone_sel and zone_sel.confidence > 0.4:
                method = StrategyMethod.HYBRID_EXTRACTION
                fallback = StrategyMethod.VISION_EXTRACTION
            elif zone_type in ["product_grid", "product_details"]:
                method = StrategyMethod.VISION_EXTRACTION
                fallback = StrategyMethod.PROSE_EXTRACTION
            else:
                method = StrategyMethod.PROSE_EXTRACTION
                fallback = None

            strategies.append(ExtractionStrategy(
                zone=zone_type,
                method=method,
                confidence=zone_sel.confidence if zone_sel else 0.3,
                fallback=fallback,
                reason="Heuristic selection based on selector confidence"
            ))

            # Set primary zone
            if zone_type in ["product_grid", "product_details"] and not primary_zone:
                primary_zone = zone_type

        return {
            "strategies": strategies,
            "primary_zone": primary_zone,
            "skip_zones": skip_zones
        }
