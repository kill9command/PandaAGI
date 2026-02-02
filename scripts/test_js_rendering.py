"""
Test if DuckDuckGo search results load with JavaScript execution.

CRITICAL FINDING: DuckDuckGo renders results via JavaScript/React.
The page HTML contains only a noscript tag until JS executes.
"""
import sys
sys.path.insert(0, '.')

import asyncio
from playwright.async_api import async_playwright
from apps.services.orchestrator.stealth_injector import inject_stealth

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
        )

        await inject_stealth(context, log=True)
        page = await context.new_page()

        # Visit homepage
        print("Visiting DuckDuckGo...")
        await page.goto("https://duckduckgo.com/", wait_until="networkidle")
        await asyncio.sleep(2)

        # Perform search
        query = "python programming"
        print(f"Searching for: {query}")
        await page.goto(
            f"https://duckduckgo.com/?q={query.replace(' ', '+')}&t=h_&ia=web",
            wait_until="networkidle"
        )

        # Check mainline before waiting
        print("\n[BEFORE WAIT]")
        mainline = await page.query_selector('[data-testid="mainline"]')
        if mainline:
            content = await mainline.inner_html()
            print(f"  Mainline HTML length: {len(content)} chars")
            if "noscript" in content.lower():
                print("  ⚠️  Contains noscript tag - JS not executed yet")

        # Wait for results to actually load (JavaScript execution)
        print("\n[WAITING FOR JS TO RENDER]")
        try:
            # Wait for actual result elements to appear (not just mainline container)
            await page.wait_for_selector('ol[data-testid]', timeout=10000)
            print("  ✅ Found ol[data-testid] element!")

            # Get all possible result containers
            ol_elements = await page.query_selector_all('ol[data-testid]')
            print(f"  Found {len(ol_elements)} ol elements with data-testid")

            for i, ol in enumerate(ol_elements):
                testid = await ol.get_attribute('data-testid')
                li_count = len(await ol.query_selector_all('li'))
                print(f"    ol[data-testid=\"{testid}\"]: {li_count} li elements")

                # Try to get first result
                if li_count > 0:
                    first_li = await ol.query_selector('li')
                    if first_li:
                        text = await first_li.inner_text()
                        print(f"    First item text preview: {text[:100]}...")

        except Exception as e:
            print(f"  ❌ Error waiting for results: {e}")

            # Try alternative selectors
            print("\n[TRYING ALTERNATIVES]")
            for selector in ['[data-testid]', 'ol', 'li[data-layout]', 'article']:
                elements = await page.query_selector_all(selector)
                print(f"  Selector '{selector}': {len(elements)} elements")

        # Check mainline AFTER waiting
        print("\n[AFTER WAIT]")
        mainline = await page.query_selector('[data-testid="mainline"]')
        if mainline:
            content = await mainline.inner_html()
            print(f"  Mainline HTML length: {len(content)} chars")
            if len(content) > 1000:
                print("  ✅ Mainline now has content!")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
