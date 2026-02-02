"""
orchestrator/calibrator - LLM-Driven Site Calibration

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

For backwards compatibility, use the legacy adapter:
    from apps.services.orchestrator.page_intelligence.legacy_adapter import get_calibrator

    calibrator = get_calibrator()
    schema = await calibrator.get_profile(page, url)
"""

from .llm_calibrator import LLMCalibrator

# Re-export from legacy adapter for backwards compatibility
from apps.services.orchestrator.page_intelligence.legacy_adapter import (
    get_calibrator,
    get_smart_calibrator,
    get_content_zone_calibrator,
    get_content_zone_registry,
)

__all__ = [
    "LLMCalibrator",
    "get_calibrator",
    "get_smart_calibrator",
    "get_content_zone_calibrator",
    "get_content_zone_registry",
]
