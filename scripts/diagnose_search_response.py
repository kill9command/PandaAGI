"""
Diagnose what DuckDuckGo is actually returning.
Save HTML to see if we're getting through but misidentifying the response.
"""
import sys
sys.path.insert(0, '.')

import asyncio
from playwright.async_api import async_playwright
from apps.services.orchestrator.stealth_injector import inject_stealth

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
        )

        await inject_stealth(context, log=True)
        page = await context.new_page()

        # Visit homepage
        print("Visiting DuckDuckGo homepage...")
        await page.goto("https://duckduckgo.com/", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)

        # Perform search
        print("Performing search...")
        query = "test"
        search_url = f"https://duckduckgo.com/?q={query}&t=h_&ia=web"
        await page.goto(search_url, wait_until="networkidle", timeout=30000)

        # Save HTML
        html = await page.content()
        with open("duckduckgo_response.html", "w") as f:
            f.write(html)

        print(f"Saved response to duckduckgo_response.html ({len(html)} bytes)")

        # Check what we got
        if "418" in html:
            print("❌ BLOCKED: 418 error page")
        elif "blocked" in html.lower():
            print("❌ BLOCKED: Contains 'blocked'")
        elif "result" in html.lower():
            print("✅ POSSIBLE SUCCESS: Contains 'result'")
        else:
            print("⚠️  UNKNOWN: Check HTML file")

        # Try to find results
        try:
            results = await page.query_selector_all("article[data-testid='result']")
            print(f"Found {len(results)} results with selector article[data-testid='result']")
        except Exception as e:
            print(f"Error finding results: {e}")

        # Try alternative selectors
        for selector in ["article", ".result", "[data-testid]", "h2"]:
            try:
                elements = await page.query_selector_all(selector)
                print(f"  Selector '{selector}': {len(elements)} elements")
            except:
                pass

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
