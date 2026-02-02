#!/usr/bin/env python3
"""
Fetch the actual content of the DDG 418 and Google /sorry/ pages
to understand what patterns we need to detect.
"""
import asyncio
import logging
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def fetch_blocker_pages():
    """Fetch blocker pages and show content samples."""
    from apps.services.orchestrator.crawler_session_manager import get_crawler_session_manager

    session_mgr = get_crawler_session_manager()

    # Test DDG 418 page
    logger.info("=" * 80)
    logger.info("FETCHING DUCKDUCKGO 418 PAGE")
    logger.info("=" * 80)

    context = await session_mgr.get_or_create_session(
        domain="duckduckgo.com",
        session_id="test_fetch"
    )
    page = await context.new_page()

    try:
        # Trigger DDG search to get 418
        await page.goto("https://duckduckgo.com/?kl=us-en", wait_until="networkidle", timeout=30000)
        search_box = await page.wait_for_selector('input[name="q"]', timeout=10000)
        await search_box.fill("test query")
        await page.keyboard.press("Enter")
        await asyncio.sleep(5)

        ddg_url = page.url
        ddg_content = await page.content()

        logger.info(f"\nDDG URL: {ddg_url}")
        logger.info(f"DDG Content length: {len(ddg_content)}")
        logger.info(f"\nDDG Content preview (first 1000 chars):")
        logger.info("=" * 80)
        logger.info(ddg_content[:1000])
        logger.info("=" * 80)

        # Search for key patterns
        content_lower = ddg_content.lower()
        logger.info(f"\nPattern detection:")
        logger.info(f"  - Contains 'captcha': {('captcha' in content_lower)}")
        logger.info(f"  - Contains '418': {'418' in content_lower}")
        logger.info(f"  - Contains 'bot': {'bot' in content_lower}")
        logger.info(f"  - Contains 'too many requests': {'too many requests' in content_lower}")
        logger.info(f"  - Contains 'unusual traffic': {'unusual traffic' in content_lower}")
        logger.info(f"  - Contains 'automated': {'automated' in content_lower}")

    finally:
        await page.close()

    # Test Google /sorry/ page
    logger.info("\n" + "=" * 80)
    logger.info("FETCHING GOOGLE /SORRY/ PAGE")
    logger.info("=" * 80)

    context2 = await session_mgr.get_or_create_session(
        domain="google.com",
        session_id="test_fetch"
    )
    page2 = await context2.new_page()

    try:
        # Trigger Google search to get /sorry/
        await page2.goto("https://www.google.com/", wait_until="networkidle", timeout=30000)
        search_box = await page2.wait_for_selector('textarea[name="q"]', timeout=10000)
        await search_box.fill("test query")
        await page2.keyboard.press("Enter")
        await asyncio.sleep(5)

        google_url = page2.url
        google_content = await page2.content()

        logger.info(f"\nGoogle URL: {google_url}")
        logger.info(f"Google Content length: {len(google_content)}")
        logger.info(f"\nGoogle Content preview (first 1000 chars):")
        logger.info("=" * 80)
        logger.info(google_content[:1000])
        logger.info("=" * 80)

        # Search for key patterns
        content_lower = google_content.lower()
        logger.info(f"\nPattern detection:")
        logger.info(f"  - Contains 'captcha': {'captcha' in content_lower}")
        logger.info(f"  - Contains 'recaptcha': {'recaptcha' in content_lower}")
        logger.info(f"  - Contains 'bot': {'bot' in content_lower}")
        logger.info(f"  - Contains 'unusual traffic': {'unusual traffic' in content_lower}")
        logger.info(f"  - Contains 'automated': {'automated' in content_lower}")
        logger.info(f"  - Contains 'verify': {'verify' in content_lower}")

    finally:
        await page2.close()


if __name__ == "__main__":
    asyncio.run(fetch_blocker_pages())
