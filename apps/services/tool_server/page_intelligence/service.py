"""
orchestrator/page_intelligence/service.py

Page Intelligence Service - Main Entry Point

THE CANONICAL EXTRACTION SYSTEM for Panda.

Replaces previous calibration systems (UnifiedCalibrator, LLMCalibrator).
Orchestrates the 3-phase page understanding pipeline:
  Phase 1: Zone Identification
  Phase 2: Selector Generation
  Phase 3: Strategy Selection
  Phase 4: Extraction (using selected strategy)

Usage:
    from apps.services.tool_server.page_intelligence import get_page_intelligence_service

    service = get_page_intelligence_service()

    # Understand a page (runs Phase 1-3 or uses cache)
    understanding = await service.understand_page(page, url)

    # Extract data using the understanding
    items = await service.extract(page, understanding)
"""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, List, Optional
from urllib.parse import urlparse

from apps.services.tool_server.page_intelligence.models import (
    PageUnderstanding,
    PageType,
    Zone,
    ZoneSelectors,
    ExtractionStrategy,
    StrategyMethod,
    OCRTextBlock,
    AvailabilityStatus,
)
from apps.services.tool_server.content_sanitizer import sanitize_html
from apps.services.tool_server.page_intelligence.dom_sampler import DOMSampler
from apps.services.tool_server.page_intelligence.ocr_dom_mapper import OCRDOMMapper
from apps.services.tool_server.page_intelligence.llm_client import LLMClient, get_llm_client, close_llm_client
from apps.services.tool_server.page_intelligence.phases.zone_identifier import ZoneIdentifier
from apps.services.tool_server.page_intelligence.phases.selector_generator import SelectorGenerator
from apps.services.tool_server.page_intelligence.phases.strategy_selector import StrategySelector
from apps.services.tool_server.page_intelligence.extractors.selector_extractor import SelectorExtractor
from apps.services.tool_server.page_intelligence.extractors.vision_extractor import VisionExtractor
from apps.services.tool_server.page_intelligence.extractors.hybrid_extractor import HybridExtractor
from apps.services.tool_server.page_intelligence.extractors.prose_extractor import ProseExtractor
from apps.services.tool_server.page_intelligence.cache import PageIntelligenceCache, get_page_intelligence_cache

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class PageIntelligenceService:
    """
    Main service for page understanding and extraction.

    This is the CANONICAL extraction system for Panda, replacing
    the older UnifiedCalibrator and LLMCalibrator.

    Flow:
    1. Check cache for existing understanding (with async locking)
    2. If cache miss, run Phase 1-3 pipeline
    3. Use understanding to extract data with appropriate strategy
    """

    def __init__(
        self,
        llm_url: str = None,
        llm_model: str = None,
        cache: PageIntelligenceCache = None,
        debug_dir: str = None
    ):
        """
        Initialize the page intelligence service.

        Args:
            llm_url: URL for LLM API
            llm_model: Model name
            cache: Cache instance (uses global if not provided)
            debug_dir: Directory to save debug docs for all phases
        """
        # Shared LLM client (reuses aiohttp session)
        self.llm_client = get_llm_client(llm_url, llm_model)
        self.cache = cache or get_page_intelligence_cache()
        self.debug_dir = Path(debug_dir) if debug_dir else None

        # Initialize components
        self.dom_sampler = DOMSampler()
        self.ocr_dom_mapper = OCRDOMMapper()

        # Phase handlers (share LLM client)
        self.zone_identifier = ZoneIdentifier(
            llm_client=self.llm_client,
            debug_dir=str(self.debug_dir) if self.debug_dir else None
        )
        self.selector_generator = SelectorGenerator(
            llm_client=self.llm_client,
            debug_dir=str(self.debug_dir) if self.debug_dir else None
        )
        self.strategy_selector = StrategySelector(
            llm_client=self.llm_client,
            debug_dir=str(self.debug_dir) if self.debug_dir else None
        )

        # Extractors (share LLM client for session reuse)
        self.selector_extractor = SelectorExtractor()
        self.vision_extractor = VisionExtractor(
            llm_client=self.llm_client
        )
        self.hybrid_extractor = HybridExtractor()
        self.prose_extractor = ProseExtractor(
            llm_client=self.llm_client
        )

    async def close(self):
        """Close resources (aiohttp session)."""
        await close_llm_client()

    async def understand_page(
        self,
        page: 'Page',
        url: str = None,
        force_refresh: bool = False,
        extraction_goal: str = "products"
    ) -> PageUnderstanding:
        """
        Understand a page's structure (zones, selectors, strategies).

        Uses cache with async locking to prevent duplicate LLM calls
        when multiple requests hit the same URL concurrently.

        Args:
            page: Playwright page (already navigated)
            url: Optional URL override
            force_refresh: Skip cache and re-analyze
            extraction_goal: What we want to extract

        Returns:
            PageUnderstanding with zones, selectors, and strategies
        """
        url = url or page.url
        domain = self._get_domain(url)

        logger.info(f"[PageIntelligence] Understanding page: {domain}")

        # Get page context for fingerprinting
        page_context = await self.dom_sampler.get_page_context(page)

        if force_refresh:
            # Bypass cache entirely
            understanding = await self._run_pipeline(page, url, page_context, extraction_goal)
            self.cache.put(understanding, page_context)
            return understanding

        # Use cache with async locking to prevent duplicate LLM calls
        async def compute_understanding():
            return await self._run_pipeline(page, url, page_context, extraction_goal)

        return await self.cache.get_or_compute(url, page_context, compute_understanding)

    async def _run_pipeline(
        self,
        page: 'Page',
        url: str,
        page_context: Dict[str, Any],
        extraction_goal: str
    ) -> PageUnderstanding:
        """Run the 3-phase understanding pipeline."""
        domain = self._get_domain(url)

        logger.info(f"[PageIntelligence] Running Phase 1: Zone Identification")

        # Phase 1: Zone Identification
        zone_result = await self.zone_identifier.identify(page_context)
        zones = zone_result.get("zones", [])
        page_type = zone_result.get("page_type", PageType.OTHER)
        has_products = zone_result.get("has_products", False)
        has_list_content = zone_result.get("has_list_content", False)

        # Extract page-level intelligence (notices, availability, constraints)
        page_notices = zone_result.get("page_notices", [])
        availability_status = zone_result.get("availability_status", AvailabilityStatus.UNKNOWN)
        purchase_constraints = zone_result.get("purchase_constraints", [])

        # Log important page intelligence
        if page_notices:
            logger.info(f"[PageIntelligence] Found {len(page_notices)} page notices for {domain}")
        if availability_status != AvailabilityStatus.UNKNOWN:
            logger.info(f"[PageIntelligence] Availability: {availability_status.value} for {domain}")

        if not zones:
            logger.warning(f"[PageIntelligence] No zones identified for {domain}")
            return self._create_fallback_understanding(url, domain, page_type)

        logger.info(f"[PageIntelligence] Identified {len(zones)} zones, running Phase 2: Selector Generation")

        # Sample HTML from zones for Phase 2
        zone_html_samples = await self.dom_sampler.sample_zones(page, zones)

        # Phase 2: Selector Generation
        selectors = await self.selector_generator.generate(zones, zone_html_samples)

        if not selectors:
            logger.warning(f"[PageIntelligence] No selectors generated for {domain}")

        logger.info(f"[PageIntelligence] Generated selectors for {len(selectors)} zones, running Phase 3: Strategy Selection")

        # Phase 3: Strategy Selection
        strategy_result = await self.strategy_selector.select(
            zones, selectors,
            {"goal": extraction_goal, "page_type": page_type.value if hasattr(page_type, 'value') else page_type}
        )
        strategies = strategy_result.get("strategies", [])
        primary_zone = strategy_result.get("primary_zone")
        skip_zones = strategy_result.get("skip_zones", [])

        if not strategies:
            logger.info(f"[PageIntelligence] Using default strategy selection")
            strategy_result = self.strategy_selector.select_default_strategy(zones, selectors)
            strategies = strategy_result.get("strategies", [])
            primary_zone = strategy_result.get("primary_zone")
            skip_zones = strategy_result.get("skip_zones", [])

        logger.info(f"[PageIntelligence] Pipeline complete: {len(strategies)} strategies, primary zone: {primary_zone}")

        return PageUnderstanding(
            url=url,
            domain=domain,
            page_type=page_type,
            zones=zones,
            selectors=selectors,
            strategies=strategies,
            primary_zone=primary_zone,
            skip_zones=skip_zones,
            has_products=has_products,
            has_list_content=has_list_content,
            created_at=datetime.utcnow(),
            page_notices=page_notices,
            availability_status=availability_status,
            purchase_constraints=purchase_constraints
        )

    def _create_fallback_understanding(
        self,
        url: str,
        domain: str,
        page_type: PageType
    ) -> PageUnderstanding:
        """Create fallback understanding when pipeline fails."""
        return PageUnderstanding(
            url=url,
            domain=domain,
            page_type=page_type,
            zones=[],
            selectors={},
            strategies=[ExtractionStrategy(
                zone="page",
                method=StrategyMethod.PROSE_EXTRACTION,
                confidence=0.3,
                reason="Fallback: no zones identified"
            )],
            primary_zone=None,
            skip_zones=[],
            has_products=False,
            created_at=datetime.utcnow(),
            notes="Fallback understanding - pipeline failed to identify zones"
        )

    async def extract(
        self,
        page: 'Page',
        understanding: PageUnderstanding,
        zone_type: str = None,
        ocr_blocks: List[OCRTextBlock] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract data from page using the understanding.

        Args:
            page: Playwright page
            understanding: Page understanding from understand_page()
            zone_type: Specific zone to extract from (uses primary_zone if not specified)
            ocr_blocks: Optional OCR text blocks for vision extraction

        Returns:
            List of extracted items
        """
        # Determine which zone to extract from
        target_zone = zone_type or understanding.primary_zone

        if not target_zone:
            # No specific zone, use prose extraction on whole page
            logger.info("[PageIntelligence] No target zone, using prose extraction")
            return await self._extract_prose(page, understanding)

        # Get strategy for target zone
        strategy = understanding.get_strategy_for_zone(target_zone)
        if not strategy:
            logger.warning(f"[PageIntelligence] No strategy for zone {target_zone}")
            strategy = ExtractionStrategy(
                zone=target_zone,
                method=StrategyMethod.SELECTOR_EXTRACTION,
                confidence=0.5,
                fallback=StrategyMethod.VISION_EXTRACTION,
                reason="Default strategy"
            )

        # Get zone and selectors
        zone = understanding.get_zone(target_zone)
        selectors = understanding.get_selectors_for_zone(target_zone)

        logger.info(f"[PageIntelligence] Extracting from zone '{target_zone}' using {strategy.method.value}")

        # Extract using selected strategy
        items = await self._extract_with_strategy(
            page, strategy, zone, selectors, ocr_blocks
        )

        # If extraction failed and we have a fallback, try it
        if not items and strategy.fallback:
            logger.info(f"[PageIntelligence] Primary extraction failed, trying fallback: {strategy.fallback.value}")
            fallback_strategy = ExtractionStrategy(
                zone=target_zone,
                method=strategy.fallback,
                confidence=strategy.confidence * 0.7,
                reason="Fallback after primary failed"
            )
            items = await self._extract_with_strategy(
                page, fallback_strategy, zone, selectors, ocr_blocks
            )

        return items

    async def _extract_with_strategy(
        self,
        page: 'Page',
        strategy: ExtractionStrategy,
        zone: Optional[Zone],
        selectors: Optional[ZoneSelectors],
        ocr_blocks: List[OCRTextBlock] = None
    ) -> List[Dict[str, Any]]:
        """Extract using a specific strategy."""
        method = strategy.method

        if method == StrategyMethod.SELECTOR_EXTRACTION:
            if selectors:
                return await self.selector_extractor.extract(page, selectors)
            else:
                logger.warning("[PageIntelligence] No selectors for selector_extraction")
                return []

        elif method == StrategyMethod.VISION_EXTRACTION:
            if zone:
                return await self.vision_extractor.extract(
                    page, zone,
                    ocr_blocks=ocr_blocks,
                    extraction_goal="products"
                )
            else:
                logger.warning("[PageIntelligence] No zone for vision_extraction")
                return []

        elif method == StrategyMethod.HYBRID_EXTRACTION:
            if zone and selectors:
                return await self.hybrid_extractor.extract(
                    page, zone, selectors,
                    ocr_blocks=ocr_blocks
                )
            elif selectors:
                return await self.selector_extractor.extract(page, selectors)
            elif zone:
                return await self.vision_extractor.extract(page, zone)
            else:
                return []

        elif method == StrategyMethod.PROSE_EXTRACTION:
            result = await self.prose_extractor.extract(
                page, zone,
                extraction_goal="products"
            )
            return result.get("items", [])

        else:
            logger.warning(f"[PageIntelligence] Unknown strategy method: {method}")
            return []

    async def _extract_prose(
        self,
        page: 'Page',
        understanding: PageUnderstanding
    ) -> List[Dict[str, Any]]:
        """Extract using prose extraction when no zone is available."""
        result = await self.prose_extractor.extract(
            page,
            extraction_goal="products"
        )
        return result.get("items", [])

    async def extract_all_zones(
        self,
        page: 'Page',
        understanding: PageUnderstanding
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract from all identified zones.

        Returns:
            Dict mapping zone_type to extracted items
        """
        results = {}

        for strategy in understanding.strategies:
            if strategy.zone in understanding.skip_zones:
                continue

            items = await self.extract(page, understanding, zone_type=strategy.zone)
            if items:
                results[strategy.zone] = items

        return results

    async def quick_extract(
        self,
        page: 'Page',
        url: str = None,
        extraction_goal: str = "products"
    ) -> List[Dict[str, Any]]:
        """
        Convenience method: understand page and extract in one call.

        Args:
            page: Playwright page
            url: Optional URL override
            extraction_goal: What to extract

        Returns:
            List of extracted items
        """
        understanding = await self.understand_page(
            page, url,
            extraction_goal=extraction_goal
        )
        return await self.extract(page, understanding)

    async def extract_from_html(
        self,
        html: str,
        url: str,
        extraction_goal: str = "products",
        query_context: str = None,
        max_tokens: int = 4000
    ) -> List[Dict[str, Any]]:
        """
        Simplified extraction: HTML → Clean Text → LLM Extraction.

        Bypasses selector generation entirely. Uses ContentSanitizer
        to clean HTML and ProseExtractor to extract structured data.

        This approach is more reliable because:
        1. ContentSanitizer handles noise removal mechanically (code)
        2. ProseExtractor uses LLM to interpret text (MIND decides)
        3. No hallucinated selectors that don't exist in the DOM

        Aligns with architecture principle: "Code captures, EYES structures, MIND decides"

        Args:
            html: Raw HTML content
            url: Source URL (for logging/context)
            extraction_goal: What to extract ("products", "article", etc.)
            query_context: Original user query for relevance filtering
            max_tokens: Maximum tokens for sanitized content

        Returns:
            List of extracted items (products, articles, etc.)
        """
        domain = self._get_domain(url)
        logger.info(f"[PageIntelligence] Simplified extraction for {domain}")

        # Step 1: Sanitize HTML to clean text
        sanitized = sanitize_html(html, url, max_tokens=max_tokens)

        if not sanitized.get("chunks"):
            logger.warning(f"[PageIntelligence] No content after sanitization for {domain}")
            return []

        # Step 2: Combine chunks into text (use first chunks up to budget)
        chunks = sanitized["chunks"]
        clean_text = "\n\n".join(c["text"] for c in chunks)

        if len(clean_text) < 50:
            logger.warning(f"[PageIntelligence] Insufficient content after sanitization for {domain}")
            return []

        logger.info(f"[PageIntelligence] Sanitized {sanitized.get('original_size', 0)} -> {len(clean_text)} chars ({sanitized.get('reduction_pct', 0)}% reduction)")

        # Step 3: Extract using ProseExtractor (LLM-based)
        # ProseExtractor expects extraction_goal, not zone parameter for text extraction
        result = await self.prose_extractor._extract_products(
            clean_text,
            query_context=query_context
        )

        items = result.get("items", [])
        logger.info(f"[PageIntelligence] Extracted {len(items)} items from {domain}")

        return items

    async def extract_from_page_simplified(
        self,
        page: 'Page',
        url: str = None,
        extraction_goal: str = "products",
        query_context: str = None,
        max_tokens: int = 4000
    ) -> List[Dict[str, Any]]:
        """
        Simplified extraction from Playwright page.

        Gets HTML from page and uses extract_from_html() for clean pipeline.
        Use this instead of quick_extract() for more reliable extraction.

        Args:
            page: Playwright page (already navigated)
            url: Optional URL override
            extraction_goal: What to extract
            query_context: Original user query for relevance filtering
            max_tokens: Maximum tokens for sanitized content

        Returns:
            List of extracted items
        """
        url = url or page.url
        try:
            html = await page.content()
            return await self.extract_from_html(
                html=html,
                url=url,
                extraction_goal=extraction_goal,
                query_context=query_context,
                max_tokens=max_tokens
            )
        except Exception as e:
            logger.error(f"[PageIntelligence] Simplified extraction failed: {e}")
            return []

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")


# Global instance with thread-safe initialization
_service: Optional[PageIntelligenceService] = None
_service_lock = threading.Lock()


def get_page_intelligence_service(
    llm_url: str = None,
    llm_model: str = None,
    debug_dir: str = None
) -> PageIntelligenceService:
    """Get or create the global service instance (thread-safe)."""
    global _service
    if _service is None:
        with _service_lock:
            # Double-check pattern
            if _service is None:
                _service = PageIntelligenceService(
                    llm_url=llm_url,
                    llm_model=llm_model,
                    debug_dir=debug_dir
                )
    return _service


async def close_page_intelligence_service():
    """Close the global service and release resources."""
    global _service
    with _service_lock:
        if _service:
            await _service.close()
            _service = None


# Convenience functions
async def understand_page(
    page: 'Page',
    url: str = None,
    force_refresh: bool = False
) -> PageUnderstanding:
    """Understand a page's structure."""
    service = get_page_intelligence_service()
    return await service.understand_page(page, url, force_refresh)


async def extract_products(
    page: 'Page',
    url: str = None
) -> List[Dict[str, Any]]:
    """Quick extraction of products from a page."""
    service = get_page_intelligence_service()
    return await service.quick_extract(page, url, extraction_goal="products")


async def extract_from_html(
    html: str,
    url: str,
    extraction_goal: str = "products",
    query_context: str = None,
    max_tokens: int = 4000
) -> List[Dict[str, Any]]:
    """
    Simplified extraction: HTML → Clean Text → LLM.

    Bypasses selector generation. Uses ContentSanitizer + ProseExtractor.

    Args:
        html: Raw HTML content
        url: Source URL
        extraction_goal: What to extract ("products", "article", etc.)
        query_context: Original user query for relevance filtering
        max_tokens: Maximum tokens for sanitized content

    Returns:
        List of extracted items
    """
    service = get_page_intelligence_service()
    return await service.extract_from_html(
        html=html,
        url=url,
        extraction_goal=extraction_goal,
        query_context=query_context,
        max_tokens=max_tokens
    )


async def extract_from_page_simplified(
    page: 'Page',
    url: str = None,
    extraction_goal: str = "products",
    query_context: str = None,
    max_tokens: int = 4000
) -> List[Dict[str, Any]]:
    """
    Simplified extraction from Playwright page.

    Preferred method - bypasses selector generation.

    Args:
        page: Playwright page (already navigated)
        url: Optional URL override
        extraction_goal: What to extract
        query_context: Original user query for relevance filtering
        max_tokens: Maximum tokens for sanitized content

    Returns:
        List of extracted items
    """
    service = get_page_intelligence_service()
    return await service.extract_from_page_simplified(
        page=page,
        url=url,
        extraction_goal=extraction_goal,
        query_context=query_context,
        max_tokens=max_tokens
    )
