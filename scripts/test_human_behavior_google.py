#!/usr/bin/env python3
"""
Test Google search with human behavior simulation to bypass bot detection.
"""
import asyncio
from playwright.async_api import async_playwright
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.services.orchestrator.human_behavior_simulator import search_google_like_human
from apps.services.orchestrator.stealth_injector import inject_stealth
from apps.services.orchestrator.browser_fingerprint import BrowserFingerprint


async def test_google_with_human_behavior():
    """Test if human behavior simulation bypasses Google's bot detection"""

    print("=" * 70)
    print("Testing Google Search with Human Behavior Simulation")
    print("=" * 70)

    # Generate fingerprint
    fingerprint = BrowserFingerprint(user_id="test", session_id="human_test")
    print(f"\nUsing fingerprint: {fingerprint}")

    async with async_playwright() as p:
        # Launch browser with fingerprint
        browser = await p.chromium.launch(
            headless=False,  # Visible mode
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ]
        )

        # Create context with fingerprint
        context_options = fingerprint.apply_to_context_options()
        context = await browser.new_context(**context_options)

        # Inject stealth
        await inject_stealth(context, log=True)

        # Create page
        page = await context.new_page()

        print("\n" + "-" * 70)
        print("Phase 1: Warming up session (visiting Google, scrolling, waiting)")
        print("-" * 70)

        # Navigate to Google with warm-up
        await page.goto("https://www.google.com", wait_until="domcontentloaded")
        print(f"✓ Navigated to: {page.url}")

        # Wait a bit
        await asyncio.sleep(2)

        # Check if we're already blocked
        if "/sorry/" in page.url:
            print("\n❌ BLOCKED: Google redirected to /sorry/ page immediately")
            print(f"   URL: {page.url}")
            await browser.close()
            return False

        print(f"✓ Page title: {await page.title()}")

        print("\n" + "-" * 70)
        print("Phase 2: Performing human-like search for 'hamster care'")
        print("-" * 70)

        # Perform search with human behavior
        success = await search_google_like_human(
            page=page,
            query="hamster care",
            warm_up=False,  # Already on Google
            seed="test_seed"
        )

        if not success:
            print("\n❌ FAILED: Could not complete search")
            await browser.close()
            return False

        # Wait for search results
        await asyncio.sleep(3)

        # Check final URL
        final_url = page.url
        final_title = await page.title()

        print("\n" + "-" * 70)
        print("Phase 3: Checking results")
        print("-" * 70)

        print(f"Final URL: {final_url}")
        print(f"Final title: {final_title}")

        # Check if we reached search results or got blocked
        if "/sorry/" in final_url or "/sorry/" in final_url.lower():
            print("\n❌ BLOCKED: Google showed CAPTCHA/sorry page")
            print(f"   This means bot detection is still catching us")
            result = False
        elif "search?q=" in final_url or "/search?q=" in final_url:
            print("\n✅ SUCCESS: Reached Google search results!")
            print(f"   Human behavior simulation bypassed bot detection!")
            result = True
        else:
            print(f"\n⚠️  UNEXPECTED: Ended up at unexpected URL")
            print(f"   URL: {final_url}")
            result = False

        # Keep browser open for inspection
        print("\n" + "-" * 70)
        print("Browser will stay open for 10 seconds for inspection...")
        print("-" * 70)
        await asyncio.sleep(10)

        await browser.close()
        return result

    print("\n" + "=" * 70)


if __name__ == "__main__":
    result = asyncio.run(test_google_with_human_behavior())
    sys.exit(0 if result else 1)
