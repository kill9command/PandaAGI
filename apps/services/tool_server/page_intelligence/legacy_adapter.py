"""
orchestrator/page_intelligence/legacy_adapter.py

Adapter layer that provides SmartCalibrator/UnifiedCalibrator-compatible interface
while using the new PageIntelligenceService internally.

This allows gradual migration from the old calibrators to the new system.

Usage:
    # Replace old imports:
    # from apps.services.tool_server.smart_calibrator import get_smart_calibrator

    # With new adapter:
    from apps.services.tool_server.page_intelligence.legacy_adapter import get_smart_calibrator

    # Same API, but uses PageIntelligenceService internally
    calibrator = get_smart_calibrator()
    schema = calibrator.get_schema(url)
"""

import asyncio
import logging
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from urllib.parse import urlparse

from apps.services.tool_server.page_intelligence.service import (
    PageIntelligenceService,
    get_page_intelligence_service,
)
from apps.services.tool_server.page_intelligence.models import (
    PageUnderstanding,
    ZoneSelectors,
    StrategyMethod,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


@dataclass
class ExtractionSchema:
    """
    Legacy ExtractionSchema compatible with SmartCalibrator.

    Adapted from PageUnderstanding for backwards compatibility.
    """
    domain: str

    # What to EXTRACT (selectors)
    product_card_selector: str = ""
    title_selector: str = ""
    price_selector: str = ""
    link_selector: str = ""
    image_selector: str = ""

    # Page type
    page_type: str = "listing"  # "listing", "pdp", "search_results"

    # Learning metadata
    created_at: str = ""
    updated_at: str = ""
    success_count: int = 0
    failure_count: int = 0
    last_failure_reason: str = ""

    # Page-level intelligence
    page_notices: List[str] = field(default_factory=list)
    availability_status: str = "unknown"
    purchase_constraints: List[str] = field(default_factory=list)

    # Source tracking
    _from_page_intelligence: bool = True
    _understanding: Optional[PageUnderstanding] = field(default=None, repr=False)

    def has_availability_restriction(self) -> bool:
        """Check if there are availability restrictions."""
        if self.availability_status not in ("available_online", "unknown"):
            return True
        return bool(self.page_notices or self.purchase_constraints)

    def get_availability_summary(self) -> str:
        """Get human-readable availability summary."""
        parts = []
        if self.availability_status == "in_store_only":
            parts.append("Available in stores only")
        elif self.availability_status == "out_of_stock":
            parts.append("Out of stock")
        parts.extend(self.page_notices)
        parts.extend(self.purchase_constraints)
        return "; ".join(parts) if parts else ""

    def record_success(self):
        """Record successful extraction."""
        self.success_count += 1
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def record_failure(self, reason: str = ""):
        """Record failed extraction."""
        self.failure_count += 1
        self.last_failure_reason = reason
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict (excluding internal fields)."""
        d = asdict(self)
        d.pop('_from_page_intelligence', None)
        d.pop('_understanding', None)
        return d

    @classmethod
    def from_page_understanding(
        cls,
        understanding: PageUnderstanding,
        zone_type: str = None
    ) -> 'ExtractionSchema':
        """
        Create ExtractionSchema from PageUnderstanding.

        Maps the new zone-based selectors to the old flat selector format.
        """
        domain = understanding.domain

        # Find the primary product zone
        target_zone = zone_type or understanding.primary_zone or "product_grid"
        selectors = understanding.get_selectors_for_zone(target_zone)

        # Map to legacy format
        schema = cls(domain=domain)

        if selectors:
            schema.product_card_selector = selectors.item_selector

            # Map field selectors
            for field_name, field_sel in selectors.fields.items():
                if field_name in ("title", "name", "product_name"):
                    schema.title_selector = field_sel.selector
                elif field_name in ("price", "cost", "amount"):
                    schema.price_selector = field_sel.selector
                elif field_name in ("link", "url", "href"):
                    schema.link_selector = field_sel.selector
                elif field_name in ("image", "img", "photo"):
                    schema.image_selector = field_sel.selector

        # Determine page type
        page_type_map = {
            "search_results": "search_results",
            "product_detail": "pdp",
            "category": "listing",
            "homepage": "listing",
        }
        pt = understanding.page_type.value if hasattr(understanding.page_type, 'value') else str(understanding.page_type)
        schema.page_type = page_type_map.get(pt, "listing")

        schema.created_at = understanding.created_at.isoformat() if understanding.created_at else ""
        schema.updated_at = datetime.now(timezone.utc).isoformat()

        # Copy page-level intelligence
        schema.page_notices = [n.message for n in understanding.page_notices]
        schema.availability_status = (
            understanding.availability_status.value
            if hasattr(understanding.availability_status, 'value')
            else str(understanding.availability_status)
        )
        schema.purchase_constraints = understanding.purchase_constraints.copy()

        schema._understanding = understanding

        return schema


class SmartCalibratorAdapter:
    """
    Adapter that provides SmartCalibrator API using PageIntelligenceService.

    Drop-in replacement for get_smart_calibrator().
    """

    def __init__(self):
        self._service = get_page_intelligence_service()
        self._schema_cache: Dict[str, ExtractionSchema] = {}
        self._cache_file = Path("panda_system_docs/schemas/smart_calibration_v2.jsonl")
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_cache()

    def _load_cache(self):
        """Load cached schemas from disk."""
        if not self._cache_file.exists():
            return

        try:
            with open(self._cache_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        domain = data.get('domain', '')
                        if domain:
                            self._schema_cache[domain] = ExtractionSchema(**{
                                k: v for k, v in data.items()
                                if k in ExtractionSchema.__dataclass_fields__ and k != '_understanding'
                            })
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.debug(f"[Adapter] Skip invalid cache line: {e}")
        except (IOError, OSError) as e:
            logger.warning(f"[Adapter] Error loading cache: {e}")

    def _save_schema(self, schema: ExtractionSchema):
        """Save schema to cache file."""
        try:
            self._schema_cache[schema.domain] = schema

            # Append to file
            with open(self._cache_file, 'a') as f:
                f.write(json.dumps(schema.to_dict()) + '\n')
        except (IOError, OSError, TypeError) as e:
            logger.error(f"[Adapter] Error saving schema: {e}")

    def get_schema(self, url: str) -> Optional[ExtractionSchema]:
        """
        Get cached schema for URL (synchronous, no LLM call).

        Returns None if not cached - caller should use calibrate() for learning.
        """
        domain = self._get_domain(url)
        return self._schema_cache.get(domain)

    async def calibrate(
        self,
        page: 'Page',
        url: str,
        site_intent: str = None,
        force: bool = False
    ) -> ExtractionSchema:
        """
        Calibrate extraction for a site using PageIntelligenceService.

        Args:
            page: Playwright page (already navigated)
            url: Current URL
            site_intent: What we want to extract (ignored, uses page analysis)
            force: Force recalibration even if cached

        Returns:
            ExtractionSchema compatible with old SmartCalibrator API
        """
        domain = self._get_domain(url)
        logger.info(f"[Adapter] Calibrating {domain} via PageIntelligenceService (force={force})")

        # Use the new system
        understanding = await self._service.understand_page(page, url, force_refresh=force)

        # Convert to legacy format
        schema = ExtractionSchema.from_page_understanding(understanding)

        # Cache it
        self._save_schema(schema)

        logger.info(f"[Adapter] Calibration complete for {domain}: card={schema.product_card_selector}, price={schema.price_selector}")

        return schema

    async def extract(
        self,
        page: 'Page',
        url: str,
        schema: ExtractionSchema = None
    ) -> List[Dict[str, Any]]:
        """
        Extract items using PageIntelligenceService.

        Args:
            page: Playwright page
            url: Current URL
            schema: Optional pre-cached schema (if None, will calibrate)

        Returns:
            List of extracted items
        """
        # If we have a cached understanding, use it
        if schema and schema._understanding:
            return await self._service.extract(page, schema._understanding)

        # Otherwise run full pipeline
        return await self._service.quick_extract(page, url)

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")


class UnifiedCalibratorAdapter:
    """
    Adapter that provides UnifiedCalibrator API using PageIntelligenceService.

    Drop-in replacement for get_calibrator().
    """

    def __init__(self):
        self._smart_adapter = SmartCalibratorAdapter()
        self._service = get_page_intelligence_service()

    async def get_profile(
        self,
        page: 'Page',
        url: str,
        force_recalibrate: bool = False
    ) -> Dict[str, Any]:
        """
        Get site profile using PageIntelligenceService.

        Returns a dict with:
        - schema: ExtractionSchema
        - understanding: PageUnderstanding (new)
        - url_patterns: dict (for URL building)
        """
        domain = self._get_domain(url)

        # Get understanding
        understanding = await self._service.understand_page(
            page, url,
            force_refresh=force_recalibrate
        )

        # Convert to legacy schema
        schema = ExtractionSchema.from_page_understanding(understanding)

        return {
            "domain": domain,
            "schema": schema,
            "understanding": understanding,
            "url_patterns": {
                "search": f"https://{domain}/search?q={{query}}",
            },
            "page_type": understanding.page_type.value if hasattr(understanding.page_type, 'value') else str(understanding.page_type),
        }

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")

    def get_url_context(self, url: str) -> Dict[str, Any]:
        """
        Get URL context using basic parsing.

        Returns context about search queries, filters, etc. from URL.
        """
        from urllib.parse import parse_qs, unquote

        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        context = {
            "is_filtered": False,
            "search_query": None,
            "price_filter": None,
            "page": None,
            "source": "basic_parsing"
        }

        # Common search params
        for param in ['q', 'k', 'query', 'search', 'keyword']:
            if param in params:
                context["search_query"] = unquote(params[param][0])
                break

        # Common price params
        price_params = ['price_max', 'maxPrice', 'max_price', 'price']
        for param in price_params:
            if param in params:
                try:
                    context["price_filter"] = {"max": float(params[param][0])}
                    context["is_filtered"] = True
                except (ValueError, IndexError):
                    pass
                break

        # Common pagination params
        for param in ['page', 'p', 'pg']:
            if param in params:
                try:
                    context["page"] = int(params[param][0])
                except (ValueError, IndexError):
                    pass
                break

        return context

    def delete_calibration(self, domain: str) -> bool:
        """
        Delete cached calibration for a domain.

        Returns True if something was deleted.
        """
        # Clear from PageIntelligence cache
        try:
            from apps.services.tool_server.page_intelligence.cache import get_cache
            cache = get_cache()
            # The cache uses domain as key, try to invalidate
            if hasattr(cache, '_memory_cache') and domain in cache._memory_cache:
                del cache._memory_cache[domain]
                logger.info(f"[Adapter] Cleared PageIntelligence cache for {domain}")
                return True
        except Exception as e:
            logger.debug(f"[Adapter] Could not clear cache for {domain}: {e}")

        return False


@dataclass
class ContentZoneSchema:
    """
    Legacy ContentZoneSchema compatible with ContentZoneCalibrator.

    Adapted from PageUnderstanding for backwards compatibility.
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

    # Product URL patterns - regex patterns that indicate product links
    product_url_patterns: List[str] = field(default_factory=list)

    # Product card selectors - CSS selectors that find product containers
    product_card_selectors: List[str] = field(default_factory=list)

    # Price container selectors - where prices are found
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

    # Page-level intelligence (from PageUnderstanding)
    page_notices: List[str] = field(default_factory=list)  # Human-readable notices
    availability_status: str = "unknown"  # available_online, in_store_only, out_of_stock, etc.
    purchase_constraints: List[str] = field(default_factory=list)

    # Internal reference
    _understanding: Optional[PageUnderstanding] = field(default=None, repr=False)

    def has_availability_restriction(self) -> bool:
        """Check if there are availability restrictions."""
        if self.availability_status not in ("available_online", "unknown"):
            return True
        return bool(self.page_notices or self.purchase_constraints)

    def get_availability_summary(self) -> str:
        """Get human-readable availability summary."""
        parts = []
        if self.availability_status == "in_store_only":
            parts.append("Available in stores only")
        elif self.availability_status == "out_of_stock":
            parts.append("Out of stock")
        elif self.availability_status == "limited_availability":
            parts.append("Limited availability")
        parts.extend(self.page_notices)
        parts.extend(self.purchase_constraints)
        return "; ".join(parts) if parts else ""

    @classmethod
    def from_page_understanding(cls, understanding: PageUnderstanding) -> 'ContentZoneSchema':
        """
        Create ContentZoneSchema from PageUnderstanding.

        Maps the new zone-based structure to the old flat format.
        """
        schema = cls(domain=understanding.domain)

        # Get primary zone selectors
        primary_zone = understanding.primary_zone or "product_grid"
        selectors = understanding.get_selectors_for_zone(primary_zone)

        if selectors:
            # Map item selector to product card
            if selectors.item_selector:
                schema.product_card_selectors = [selectors.item_selector]

            # Extract field selectors
            for field_name, field_sel in selectors.fields.items():
                if field_name in ("price", "cost", "amount"):
                    schema.price_selectors.append(field_sel.selector)

        # Map zones to content zone
        if understanding.zones:
            # Use the first content zone as the main content selector
            # zones is a List[Zone], not a dict
            for zone in understanding.zones:
                zone_type = zone.zone_type.value if hasattr(zone.zone_type, 'value') else str(zone.zone_type)
                if zone_type not in ("navigation", "header", "footer", "sidebar", "ads"):
                    # Zone uses dom_anchors list for CSS selectors
                    if zone.dom_anchors:
                        schema.content_zone_selector = zone.dom_anchors[0]
                        break

        # Set confidence from zones average or default
        if understanding.zones:
            schema.calibration_confidence = sum(z.confidence for z in understanding.zones) / len(understanding.zones)
        else:
            schema.calibration_confidence = 0.5

        # Set timestamps
        schema.created_at = understanding.created_at.isoformat() if understanding.created_at else ""
        schema.updated_at = datetime.now(timezone.utc).isoformat()

        # Copy page-level intelligence
        schema.page_notices = [n.message for n in understanding.page_notices]
        schema.availability_status = (
            understanding.availability_status.value
            if hasattr(understanding.availability_status, 'value')
            else str(understanding.availability_status)
        )
        schema.purchase_constraints = understanding.purchase_constraints.copy()

        # Log if there are restrictions
        if schema.page_notices or schema.availability_status != "unknown":
            logger.info(
                f"[Adapter] Page intelligence for {schema.domain}: "
                f"availability={schema.availability_status}, "
                f"notices={len(schema.page_notices)}, "
                f"constraints={len(schema.purchase_constraints)}"
            )

        # Store reference
        schema._understanding = understanding

        return schema


class ContentZoneCalibratorAdapter:
    """
    Adapter that provides ContentZoneCalibrator API using PageIntelligenceService.

    Drop-in replacement for get_content_zone_calibrator().
    """

    def __init__(self):
        self._service = get_page_intelligence_service()
        self._schema_cache: Dict[str, ContentZoneSchema] = {}

    async def calibrate(
        self,
        page: 'Page',
        url: str,
        force: bool = False
    ) -> ContentZoneSchema:
        """
        Calibrate content zones for a site using PageIntelligenceService.

        Args:
            page: Playwright page (already navigated)
            url: Current URL
            force: Force recalibration

        Returns:
            ContentZoneSchema compatible with old ContentZoneCalibrator API
        """
        domain = self._get_domain(url)
        logger.info(f"[Adapter] ContentZone calibrating {domain} via PageIntelligenceService")

        # Use the new system
        understanding = await self._service.understand_page(page, url, force_refresh=force)

        # Convert to legacy format
        schema = ContentZoneSchema.from_page_understanding(understanding)

        # Cache it
        self._schema_cache[domain] = schema

        logger.info(
            f"[Adapter] ContentZone calibration complete for {domain}: "
            f"card_selectors={schema.product_card_selectors}, "
            f"price_selectors={schema.price_selectors}, "
            f"confidence={schema.calibration_confidence:.0%}"
        )

        # Log availability restrictions prominently
        if schema.has_availability_restriction():
            logger.warning(
                f"[Adapter] AVAILABILITY RESTRICTION for {domain}: "
                f"{schema.get_availability_summary()}"
            )

        return schema

    def get_schema(self, domain: str) -> Optional[ContentZoneSchema]:
        """Get cached schema for domain."""
        return self._schema_cache.get(domain)

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")


class ContentZoneRegistryAdapter:
    """
    Adapter that provides ContentZoneRegistry API.

    Drop-in replacement for get_content_zone_registry().
    """

    def __init__(self):
        self._calibrator = ContentZoneCalibratorAdapter()

    def get(self, domain: str) -> Optional[ContentZoneSchema]:
        """Get cached schema for domain."""
        return self._calibrator.get_schema(domain)


# Global instances
_smart_adapter: Optional[SmartCalibratorAdapter] = None
_unified_adapter: Optional[UnifiedCalibratorAdapter] = None
_content_zone_adapter: Optional[ContentZoneCalibratorAdapter] = None
_content_zone_registry: Optional[ContentZoneRegistryAdapter] = None


def get_smart_calibrator() -> SmartCalibratorAdapter:
    """Get the SmartCalibrator adapter (uses PageIntelligenceService)."""
    global _smart_adapter
    if _smart_adapter is None:
        _smart_adapter = SmartCalibratorAdapter()
        logger.info("[Adapter] SmartCalibratorAdapter initialized (using PageIntelligenceService)")
    return _smart_adapter


def get_calibrator() -> UnifiedCalibratorAdapter:
    """Get the UnifiedCalibrator adapter (uses PageIntelligenceService)."""
    global _unified_adapter
    if _unified_adapter is None:
        _unified_adapter = UnifiedCalibratorAdapter()
        logger.info("[Adapter] UnifiedCalibratorAdapter initialized (using PageIntelligenceService)")
    return _unified_adapter


def get_content_zone_calibrator() -> ContentZoneCalibratorAdapter:
    """Get the ContentZoneCalibrator adapter (uses PageIntelligenceService)."""
    global _content_zone_adapter
    if _content_zone_adapter is None:
        _content_zone_adapter = ContentZoneCalibratorAdapter()
        logger.info("[Adapter] ContentZoneCalibratorAdapter initialized (using PageIntelligenceService)")
    return _content_zone_adapter


def get_content_zone_registry() -> ContentZoneRegistryAdapter:
    """Get the ContentZoneRegistry adapter (uses PageIntelligenceService)."""
    global _content_zone_registry
    if _content_zone_registry is None:
        _content_zone_registry = ContentZoneRegistryAdapter()
        logger.info("[Adapter] ContentZoneRegistryAdapter initialized (using PageIntelligenceService)")
    return _content_zone_registry
