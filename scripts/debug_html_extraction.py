#!/usr/bin/env python3
"""Debug HTML extraction to understand what URLs are being found/rejected."""

import asyncio
import re
import sys

# Add project root to path
sys.path.insert(0, '/path/to/pandaagi')

async def debug_extraction():
    """Fetch Best Buy page and analyze link structure."""
    from playwright.async_api import async_playwright
    from apps.services.tool_server.product_perception.html_extractor import HTMLExtractor

    url = "https://www.bestbuy.com/site/searchpage.jsp?st=gaming+laptop"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        print(f"Navigating to {url}...")
        try:
            await page.goto(url, timeout=60000, wait_until='domcontentloaded')
            await asyncio.sleep(5)  # Let JS render
        except Exception as e:
            print(f"Navigation failed: {e}")
            await browser.close()
            return

        html = await page.content()
        await browser.close()

    print(f"\nHTML length: {len(html)} chars\n")

    # Test HTMLExtractor
    print("=" * 80)
    print("TESTING HTMLExtractor:")
    print("=" * 80)

    extractor = HTMLExtractor()
    candidates = await extractor.extract(html, url)

    print(f"\nHTMLExtractor found {len(candidates)} candidates:\n")
    for i, c in enumerate(candidates[:20], 1):
        print(f"{i}. URL: {c.url[:100]}...")
        print(f"   TEXT: {c.link_text[:80] if c.link_text else '(empty)'}...")
        print(f"   SOURCE: {c.source}, CONFIDENCE: {c.confidence}")
        print()

    if not candidates:
        print("NO CANDIDATES FOUND!")
        # Debug: manually check for /product/ pattern
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        print("\nManual check for /product/ links:")
        product_links = soup.find_all('a', href=re.compile(r'/product/'))
        print(f"Found {len(product_links)} links with /product/")
        for link in product_links[:5]:
            print(f"  {link.get('href', '')[:80]}...")


if __name__ == "__main__":
    asyncio.run(debug_extraction())
