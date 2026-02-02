#!/usr/bin/env python3
"""
Test script to verify page notices extraction is working.

Tests the PageIntelligence system's ability to extract page-level notices
like "Sold in stores only", "Out of stock", etc.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright

from apps.services.orchestrator.page_intelligence import get_page_intelligence_service
from apps.services.orchestrator.page_intelligence.models import AvailabilityStatus

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_page_notices():
    """Test page notices extraction on a few test URLs."""

    # Test URLs that may have availability restrictions
    test_urls = [
        # Petco live animals page (should have "Sold in stores only" notice)
        "https://www.petco.com/shop/en/petcostore/category/small-animal/live-small-animals",
        # Amazon product page (for comparison, usually available online)
        "https://www.amazon.com/s?k=hamster+cage",
    ]

    service = get_page_intelligence_service()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        for url in test_urls:
            logger.info(f"\n{'='*60}")
            logger.info(f"Testing URL: {url}")
            logger.info('='*60)

            try:
                # Navigate to the page
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)  # Wait for dynamic content

                # Get page understanding with force_refresh to bypass cache
                understanding = await service.understand_page(
                    page, url,
                    force_refresh=True,
                    extraction_goal="products"
                )

                # Report results
                logger.info(f"\n--- Page Understanding Results ---")
                logger.info(f"Domain: {understanding.domain}")
                logger.info(f"Page Type: {understanding.page_type.value}")
                logger.info(f"Has Products: {understanding.has_products}")
                logger.info(f"Zones: {[z.zone_type.value for z in understanding.zones]}")

                # Page notices
                logger.info(f"\n--- Page Notices ---")
                logger.info(f"Availability Status: {understanding.availability_status.value}")
                logger.info(f"Page Notices ({len(understanding.page_notices)}):")
                for notice in understanding.page_notices:
                    logger.info(f"  - [{notice.notice_type}] {notice.message}")

                logger.info(f"Purchase Constraints: {understanding.purchase_constraints}")

                # Check helper methods
                if understanding.has_availability_restriction():
                    logger.warning(f"\n⚠️  AVAILABILITY RESTRICTION DETECTED!")
                    logger.warning(f"Summary: {understanding.get_availability_summary()}")
                else:
                    logger.info(f"\n✓ No availability restrictions detected")

            except Exception as e:
                logger.error(f"Error testing {url}: {e}")
                import traceback
                traceback.print_exc()

        await browser.close()

    # Clean up
    await service.close()


if __name__ == "__main__":
    asyncio.run(test_page_notices())
