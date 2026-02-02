#!/usr/bin/env python3
"""
Test Brave Search as alternative to Google.
Brave is privacy-focused and has less aggressive bot detection.
"""
import asyncio
from playwright.async_api import async_playwright
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.services.orchestrator.human_behavior_simulator import HumanBehaviorSimulator
from apps.services.orchestrator.stealth_injector import inject_stealth
from apps.services.orchestrator.browser_fingerprint import BrowserFingerprint


async def test_brave_search():
    """Test Brave Search with same automation"""

    print("=" * 70)
    print("Testing Brave Search (Alternative to Google)")
    print("=" * 70)

    fingerprint = BrowserFingerprint(user_id="test", session_id="brave_test")
    print(f"\nUsing fingerprint: {fingerprint}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )

        context = await browser.new_context(**fingerprint.apply_to_context_options())
        await inject_stealth(context, log=True)

        page = await context.new_page()

        print("\nPhase 1: Navigate to Brave Search...")
        await page.goto("https://search.brave.com/", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        print(f"✓ Navigated to: {page.url}")
        print(f"✓ Page title: {await page.title()}")

        # Check if blocked
        if "sorry" in page.url.lower() or "captcha" in page.url.lower():
            print("\n❌ BLOCKED by Brave Search")
            await browser.close()
            return False

        print("\nPhase 2: Searching for 'hamster care'...")

        # Find search box (Brave uses different selectors)
        search_box = await page.query_selector('input[name="q"]')
        if not search_box:
            search_box = await page.query_selector('input[type="search"]')

        if not search_box:
            print("❌ Could not find search box")
            await browser.close()
            return False

        # Use human behavior
        simulator = HumanBehaviorSimulator(page, seed="brave_test")
        await simulator.click_like_human(search_box, move_mouse=True)
        await simulator.type_like_human("hamster care", min_delay_ms=60, max_delay_ms=150)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")

        # Wait for results
        await asyncio.sleep(3)

        final_url = page.url
        final_title = await page.title()

        print(f"\nFinal URL: {final_url}")
        print(f"Final title: {final_title}")

        # Check results
        if "sorry" in final_url.lower() or "captcha" in final_url.lower():
            print("\n❌ BLOCKED: Brave showed CAPTCHA")
            result = False
        elif "search?q=" in final_url or "/search?q=" in final_url:
            print("\n✅ SUCCESS: Reached Brave search results!")
            print("   Brave Search works with automation!")
            result = True
        else:
            print(f"\n⚠️  Unexpected URL: {final_url}")
            result = False

        print("\nBrowser will stay open for 5 seconds...")
        await asyncio.sleep(5)

        await browser.close()
        return result


if __name__ == "__main__":
    result = asyncio.run(test_brave_search())
    sys.exit(0 if result else 1)
