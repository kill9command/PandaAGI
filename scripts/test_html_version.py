"""
Test DuckDuckGo's HTML-only version (no JavaScript required).

DuckDuckGo provides /html endpoint for non-JS browsers.
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

        # Try HTML-only version
        query = "python programming"
        print(f"Testing HTML-only version: /html?q={query}")

        url = f"https://duckduckgo.com/html?q={query.replace(' ', '+')}"
        await page.goto(url, wait_until="networkidle")

        # Save HTML
        html = await page.content()
        with open("duckduckgo_html_version.html", "w") as f:
            f.write(html)
        print(f"Saved HTML ({len(html)} bytes) to duckduckgo_html_version.html")

        # Check for blocking
        if "418" in html or "blocked" in html.lower():
            print("❌ BLOCKED")
        else:
            print("✅ NOT blocked")

        # Try to find results with various selectors
        print("\nSearching for results...")

        selectors_to_try = [
            ('div.result', 'Standard result divs'),
            ('div.results_links', 'Result links container'),
            ('div.links_main', 'Main links'),
            ('a.result__a', 'Result links'),
            ('div.result__body', 'Result bodies'),
        ]

        for selector, description in selectors_to_try:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    print(f"  ✅ {description} ('{selector}'): {len(elements)} elements")
                    if len(elements) > 0:
                        # Get first result
                        first = elements[0]
                        text = await first.inner_text()
                        print(f"     Preview: {text[:100]}...")
                else:
                    print(f"  ❌ {description} ('{selector}'): 0 elements")
            except Exception as e:
                print(f"  ❌ {description} ('{selector}'): Error - {e}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
