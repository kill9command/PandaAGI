#!/usr/bin/env python3
"""
Test stealth JavaScript integration with Google and DuckDuckGo.

Verifies that:
1. navigator.webdriver is hidden
2. Search engines don't block us
3. We can fetch search results successfully
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_stealth_detection():
    """Test that stealth JavaScript hides automation flags"""
    from playwright.async_api import async_playwright
    from apps.services.tool_server.stealth_injector import inject_stealth

    print("=" * 70)
    print("TEST 1: Stealth Detection Flags")
    print("=" * 70)

    async with async_playwright() as p:
        # Launch with stealth args
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )

        # Create context and inject stealth
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
        )

        await inject_stealth(context, log=True)

        page = await context.new_page()
        await page.goto('about:blank')

        # Check all detection flags
        results = await page.evaluate("""() => {
            return {
                webdriver: navigator.webdriver,
                chrome: typeof window.chrome,
                plugins: navigator.plugins.length,
                languages: navigator.languages,
                permissions: typeof navigator.permissions.query
            };
        }""")

        print("\nDetection Flags:")
        print(f"  navigator.webdriver: {results['webdriver']} {'✓ HIDDEN' if not results['webdriver'] else '❌ EXPOSED'}")
        print(f"  window.chrome: {results['chrome']} {'✓ PRESENT' if results['chrome'] == 'object' else '❌ MISSING'}")
        print(f"  navigator.plugins.length: {results['plugins']} {'✓ POPULATED' if results['plugins'] > 0 else '❌ EMPTY'}")
        print(f"  navigator.languages: {results['languages']} ✓")
        print(f"  navigator.permissions.query: {results['permissions']} ✓")

        await browser.close()

        # Overall pass/fail
        if results['webdriver'] == False and results['chrome'] == 'object' and results['plugins'] > 0:
            print("\n✅ PASS: All stealth flags look good!")
            return True
        else:
            print("\n❌ FAIL: Some detection flags are exposed")
            return False


async def test_google_search():
    """Test that Google doesn't block us"""
    from playwright.async_api import async_playwright
    from apps.services.tool_server.stealth_injector import inject_stealth

    print("\n" + "=" * 70)
    print("TEST 2: Google Search (Real Bot Detection Test)")
    print("=" * 70)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        await inject_stealth(context, log=False)

        page = await context.new_page()

        try:
            print("\nNavigating to Google search...")
            response = await page.goto(
                'https://www.google.com/search?q=hamster+care+tips',
                wait_until='domcontentloaded',
                timeout=30000
            )

            title = await page.title()
            url = page.url
            html = await page.content()

            print(f"  HTTP Status: {response.status}")
            print(f"  Page Title: {title}")
            print(f"  Final URL: {url[:80]}...")

            # Check for blocking indicators
            is_blocked = (
                '/sorry/' in url.lower() or
                'captcha' in html.lower() or
                'unusual traffic' in html.lower() or
                'automated' in html.lower()
            )

            if is_blocked:
                print(f"\n❌ BLOCKED: Google detected automation")
                print(f"  Blocking page detected in response")

                # Save screenshot for debugging
                screenshot_path = "panda_system_docs/scrape_staging/screenshots/google_stealth_test_blocked.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"  Screenshot saved: {screenshot_path}")

                await browser.close()
                return False
            else:
                print(f"\n✅ SUCCESS: Google search worked!")

                # Check if we got results
                search_results = await page.query_selector_all('div.g')
                print(f"  Found {len(search_results)} search results")

                # Save screenshot for verification
                screenshot_path = "panda_system_docs/scrape_staging/screenshots/google_stealth_test_success.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"  Screenshot saved: {screenshot_path}")

                await browser.close()
                return True

        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            await browser.close()
            return False


async def test_duckduckgo_search():
    """Test that DuckDuckGo doesn't block us"""
    from playwright.async_api import async_playwright
    from apps.services.tool_server.stealth_injector import inject_stealth

    print("\n" + "=" * 70)
    print("TEST 3: DuckDuckGo Search")
    print("=" * 70)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        await inject_stealth(context, log=False)

        page = await context.new_page()

        try:
            print("\nNavigating to DuckDuckGo search...")
            response = await page.goto(
                'https://duckduckgo.com/?q=hamster+care+tips',
                wait_until='domcontentloaded',
                timeout=30000
            )

            title = await page.title()
            url = page.url
            html = await page.content()

            print(f"  HTTP Status: {response.status}")
            print(f"  Page Title: {title}")
            print(f"  Final URL: {url[:80]}...")

            # Check for blocking indicators
            is_blocked = (
                'captcha' in html.lower() or
                'unusual traffic' in html.lower() or
                'automated' in html.lower() or
                'blocked' in html.lower()
            )

            if is_blocked:
                print(f"\n❌ BLOCKED: DuckDuckGo detected automation")
                screenshot_path = "panda_system_docs/scrape_staging/screenshots/ddg_stealth_test_blocked.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"  Screenshot saved: {screenshot_path}")
                await browser.close()
                return False
            else:
                print(f"\n✅ SUCCESS: DuckDuckGo search worked!")

                # Check if we got results
                results = await page.query_selector_all('[data-testid="result"]')
                print(f"  Found {len(results)} search results")

                screenshot_path = "panda_system_docs/scrape_staging/screenshots/ddg_stealth_test_success.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"  Screenshot saved: {screenshot_path}")

                await browser.close()
                return True

        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            await browser.close()
            return False


async def main():
    """Run all stealth tests"""
    print("\n" + "=" * 70)
    print("STEALTH INTEGRATION TEST SUITE")
    print("=" * 70)
    print("Testing browser stealth against detection and search engines\n")

    # Test 1: Stealth flags
    test1_pass = await test_stealth_detection()

    # Test 2: Google
    test2_pass = await test_google_search()

    # Test 3: DuckDuckGo
    test3_pass = await test_duckduckgo_search()

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"  Test 1 (Stealth Flags):  {'✅ PASS' if test1_pass else '❌ FAIL'}")
    print(f"  Test 2 (Google Search):  {'✅ PASS' if test2_pass else '❌ FAIL'}")
    print(f"  Test 3 (DuckDuckGo):     {'✅ PASS' if test3_pass else '❌ FAIL'}")
    print("=" * 70)

    all_pass = test1_pass and test2_pass and test3_pass

    if all_pass:
        print("\n🎉 ALL TESTS PASSED! Stealth integration is working!")
        return 0
    else:
        print("\n⚠️  Some tests failed. See details above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
