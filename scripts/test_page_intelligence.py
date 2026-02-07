#!/usr/bin/env python3
"""
Test script for the Page Intelligence System.

Tests the 3-phase pipeline:
- Phase 1: Zone Identification
- Phase 2: Selector Generation
- Phase 3: Strategy Selection
- Phase 4: Extraction

Usage:
    python scripts/test_page_intelligence.py [url]

Example:
    python scripts/test_page_intelligence.py "https://www.amazon.com/s?k=laptop"
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright

from apps.services.tool_server.page_intelligence import (
    PageIntelligenceService,
    get_page_intelligence_service,
)
from apps.services.tool_server.page_intelligence.dom_sampler import DOMSampler
from apps.services.tool_server.page_intelligence.phases.zone_identifier import ZoneIdentifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_dom_sampler(page, url: str):
    """Test the DOM sampler component."""
    print("\n" + "="*60)
    print("Testing DOM Sampler")
    print("="*60)

    sampler = DOMSampler()

    # Get page context
    context = await sampler.get_page_context(page)

    print(f"\nPage URL: {context.get('url')}")
    print(f"Page Title: {context.get('title')}")
    print(f"\nRepeated Classes (likely item containers):")
    for cls_info in context.get('repeatedClasses', [])[:5]:
        print(f"  {cls_info.get('class')}: {cls_info.get('count')} instances")

    print(f"\nText with Prices (sample):")
    for text in context.get('textWithPrices', [])[:5]:
        print(f"  {text[:80]}...")

    print(f"\nSemantic Containers:")
    for container in context.get('semanticContainers', []):
        print(f"  <{container.get('tag')}>: {container.get('count')} instances")

    print(f"\nPage Indicators:")
    indicators = context.get('indicators', {})
    for key, value in indicators.items():
        print(f"  {key}: {value}")

    return context


async def test_zone_identifier(page_context: dict):
    """Test Phase 1: Zone Identifier."""
    print("\n" + "="*60)
    print("Testing Phase 1: Zone Identifier")
    print("="*60)

    identifier = ZoneIdentifier()
    result = await identifier.identify(page_context)

    print(f"\nPage Type: {result.get('page_type')}")
    print(f"Has Products: {result.get('has_products')}")

    print(f"\nIdentified Zones:")
    for zone in result.get('zones', []):
        zone_type = zone.zone_type.value if hasattr(zone.zone_type, 'value') else zone.zone_type
        print(f"\n  Zone: {zone_type}")
        print(f"    Confidence: {zone.confidence}")
        print(f"    DOM Anchors: {zone.dom_anchors}")
        print(f"    Item Count Estimate: {zone.item_count_estimate}")
        if zone.notes:
            print(f"    Notes: {zone.notes}")

    return result


async def test_full_pipeline(page, url: str):
    """Test the full Page Intelligence pipeline."""
    print("\n" + "="*60)
    print("Testing Full Page Intelligence Pipeline")
    print("="*60)

    # Create debug directory for this test
    debug_dir = Path("panda_system_docs/page_intelligence_debug")
    debug_dir.mkdir(parents=True, exist_ok=True)

    service = PageIntelligenceService(debug_dir=str(debug_dir))

    print(f"\nUnderstanding page: {url}")
    understanding = await service.understand_page(page, url, force_refresh=True)

    print(f"\n--- Page Understanding ---")
    print(f"Domain: {understanding.domain}")
    print(f"Page Type: {understanding.page_type}")
    print(f"Has Products: {understanding.has_products}")
    print(f"Primary Zone: {understanding.primary_zone}")
    print(f"Skip Zones: {understanding.skip_zones}")

    print(f"\n--- Zones ({len(understanding.zones)}) ---")
    for zone in understanding.zones:
        zone_type = zone.zone_type.value if hasattr(zone.zone_type, 'value') else zone.zone_type
        print(f"  {zone_type}: confidence={zone.confidence:.2f}, anchors={zone.dom_anchors}")

    print(f"\n--- Selectors ({len(understanding.selectors)}) ---")
    for zone_type, selectors in understanding.selectors.items():
        print(f"  {zone_type}:")
        print(f"    item_selector: {selectors.item_selector}")
        print(f"    fields: {list(selectors.fields.keys())}")
        print(f"    confidence: {selectors.confidence:.2f}")

    print(f"\n--- Strategies ({len(understanding.strategies)}) ---")
    for strategy in understanding.strategies:
        method = strategy.method.value if hasattr(strategy.method, 'value') else strategy.method
        fallback = strategy.fallback.value if strategy.fallback and hasattr(strategy.fallback, 'value') else strategy.fallback
        print(f"  {strategy.zone}: {method} (fallback={fallback})")
        print(f"    reason: {strategy.reason}")

    # Save understanding to file
    output_file = debug_dir / "understanding.json"
    with open(output_file, 'w') as f:
        json.dump(understanding.to_dict(), f, indent=2, default=str)
    print(f"\nSaved understanding to: {output_file}")

    return understanding


async def test_extraction(page, understanding):
    """Test extraction using the understanding."""
    print("\n" + "="*60)
    print("Testing Extraction")
    print("="*60)

    service = get_page_intelligence_service()

    print(f"\nExtracting from primary zone: {understanding.primary_zone}")
    items = await service.extract(page, understanding)

    print(f"\nExtracted {len(items)} items:")
    for i, item in enumerate(items[:5]):  # Show first 5
        print(f"\n  Item {i+1}:")
        for key, value in item.items():
            if not key.startswith('_'):  # Skip internal fields
                print(f"    {key}: {str(value)[:80]}")

    if len(items) > 5:
        print(f"\n  ... and {len(items) - 5} more items")

    return items


async def main():
    # Default test URL
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.amazon.com/s?k=laptop"

    print(f"\n{'='*60}")
    print(f"Page Intelligence System Test")
    print(f"URL: {url}")
    print(f"{'='*60}")

    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            # Navigate to test URL
            print(f"\nNavigating to {url}...")
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(2)  # Wait for dynamic content

            # Test components
            page_context = await test_dom_sampler(page, url)
            zone_result = await test_zone_identifier(page_context)

            # Test full pipeline
            understanding = await test_full_pipeline(page, url)

            # Test extraction
            if understanding.primary_zone:
                items = await test_extraction(page, understanding)

            print("\n" + "="*60)
            print("All tests completed!")
            print("="*60)

        except Exception as e:
            logger.error(f"Test failed: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
