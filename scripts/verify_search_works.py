"""Verify search actually works with a real query."""
import sys
sys.path.insert(0, '.')

import asyncio
from playwright.async_api import async_playwright
from apps.services.orchestrator.stealth_injector import inject_stealth

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080}
        )
        await inject_stealth(context, log=True)
        page = await context.new_page()

        # Visit homepage
        print("Visiting DuckDuckGo...")
        await page.goto("https://duckduckgo.com/", wait_until="networkidle")
        await asyncio.sleep(2)

        # Real query
        query = "python programming"
        print(f"Searching for: {query}")
        await page.goto(f"https://duckduckgo.com/?q={query.replace(' ', '+')}&t=h_&ia=web", wait_until="networkidle")

        # Check results
        html = await page.content()

        if "418" in html:
            print("❌ BLOCKED (418)")
        elif "blocked" in html.lower():
            print("❌ BLOCKED (contains 'blocked')")
        else:
            # Try to find results with multiple selectors
            results = await page.query_selector_all("article[data-testid='result']")
            if results:
                print(f"✅ SUCCESS: Found {len(results)} results!")
                # Get first result title
                try:
                    first = results[0]
                    title_elem = await first.query_selector("h2")
                    if title_elem:
                        title = await title_elem.text_content()
                        print(f"   First result: {title[:60]}...")
                except:
                    pass
            else:
                # Try alternative selectors
                print("No results with standard selector, trying alternatives...")
                for selector in ["[data-result]", ".result", "article"]:
                    elems = await page.query_selector_all(selector)
                    if elems:
                        print(f"   Found {len(elems)} elements with selector '{selector}'")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
