"""
orchestrator/page_intelligence/__init__.py

Page Intelligence System - 3-Phase LLM-driven page understanding

This system replaces ad-hoc calibration with a structured pipeline:
  Phase 1: Zone Identification (what zones exist on the page)
  Phase 2: Selector Generation (CSS selectors for each zone)
  Phase 3: Strategy Selection (how to extract from each zone)
  Phase 4: Extraction (no LLM - use selected strategy)

Key Features:
- Document-based IO for debugging (every phase reads/writes JSON docs)
- OCR-DOM cross-reference for zone-aware vision extraction
- Caching per domain/URL pattern for efficiency
- Modular design for easy debugging and extension
"""

from apps.services.tool_server.page_intelligence.service import (
    PageIntelligenceService,
    get_page_intelligence_service,
    close_page_intelligence_service,
    understand_page,
    extract_products,
)
from apps.services.tool_server.page_intelligence.models import (
    Zone,
    ZoneType,
    PageType,
    PageUnderstanding,
    ExtractionStrategy,
    StrategyMethod,
    FieldSelector,
    ZoneSelectors,
    Bounds,
    OCRTextBlock,
)

__all__ = [
    # Service
    "PageIntelligenceService",
    "get_page_intelligence_service",
    "close_page_intelligence_service",
    "understand_page",
    "extract_products",
    # Models
    "Zone",
    "ZoneType",
    "PageType",
    "PageUnderstanding",
    "ExtractionStrategy",
    "StrategyMethod",
    "FieldSelector",
    "ZoneSelectors",
    "Bounds",
    "OCRTextBlock",
]
