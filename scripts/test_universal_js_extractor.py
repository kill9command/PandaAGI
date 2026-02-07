#!/usr/bin/env python3
"""
Direct test for universal JS extractor on product sites.
Bypasses Google search to directly test extraction on Best Buy, Amazon, etc.
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright
from apps.services.tool_server.product_perception.pipeline import ProductPerceptionPipeline


async def test_site(pipeline: ProductPerceptionPipeline, url: str, name: str):
    """Test universal JS extractor on a specific site."""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"URL: {url}")
    print(f"{'='*60}")

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
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
        )
        page = await context.new_page()

        # Inject stealth scripts
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)

        try:
            print(f"Navigating to {url}...")
            await page.goto(url, wait_until='domcontentloaded', timeout=60000)
            await page.wait_for_timeout(3000)  # Wait for JS to load

            # Test the universal JS extractor directly
            print("Running universal JS extractor...")
            candidates = await pipeline._extract_universal_js(page, url)

            print(f"\n✓ Found {len(candidates)} products via universal JS:")
            for i, c in enumerate(candidates[:10], 1):
                price_str = c.context_text if c.context_text else "no price"
                print(f"  {i}. {c.link_text[:60]}... ({price_str})")
                print(f"     URL: {c.url[:80]}...")

            if len(candidates) >= 3:
                print(f"\n✅ SUCCESS: Universal JS extractor works on {name}!")
            else:
                print(f"\n⚠️  PARTIAL: Found only {len(candidates)} products (need 3+)")

            return len(candidates)

        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            return 0
        finally:
            await browser.close()


async def main():
    """Test universal JS extractor on multiple sites."""

    # Initialize pipeline
    pipeline = ProductPerceptionPipeline()

    # Test sites with product listings
    test_urls = [
        ("Best Buy - Headphones", "https://www.bestbuy.com/site/searchpage.jsp?st=wireless+gaming+headset"),
        ("Amazon - Headphones", "https://www.amazon.com/s?k=wireless+gaming+headset"),
        ("Newegg - Headphones", "https://www.newegg.com/p/pl?d=wireless+gaming+headset"),
    ]

    results = {}
    for name, url in test_urls:
        count = await test_site(pipeline, url, name)
        results[name] = count
        await asyncio.sleep(2)  # Brief pause between sites

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for name, count in results.items():
        status = "✅" if count >= 3 else "⚠️" if count > 0 else "❌"
        print(f"  {status} {name}: {count} products")

    total = sum(results.values())
    print(f"\nTotal products found: {total}")

    if all(c >= 3 for c in results.values()):
        print("\n🎉 Universal JS extractor working on all sites!")
        return 0
    else:
        print("\n⚠️  Some sites need attention")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
