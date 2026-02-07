#!/usr/bin/env python3
"""Test the click-resolve functionality directly."""

import asyncio
import logging
import sys

# Configure logging to see resolver output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_click_resolve():
    """Test click-resolve on a retailer page."""
    from playwright.async_api import async_playwright
    from apps.services.tool_server.product_perception.pipeline import ProductPerceptionPipeline

    # Test URL - Best Buy laptops
    test_url = "https://www.bestbuy.com/site/searchpage.jsp?st=gaming+laptop"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # Run headless for CI/remote
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()

        print(f"\n=== Navigating to {test_url} ===\n")
        await page.goto(test_url, timeout=30000)
        await page.wait_for_load_state('networkidle', timeout=10000)

        # Wait a moment for JS to render
        await asyncio.sleep(2)

        print("\n=== Running ProductPerceptionPipeline ===\n")
        pipeline = ProductPerceptionPipeline()
        result = await pipeline.extract_with_stats(page, test_url, "gaming laptop")

        print(f"\n=== RESULTS ===")
        print(f"Total products: {len(result.products)}")
        print(f"HTML candidates: {result.html_candidates_count}")
        print(f"Vision products: {result.vision_products_count}")
        print(f"Fusion matches: {result.fusion_matches}")
        print(f"Click resolved: {result.click_resolved}")
        print(f"Time: {result.extraction_time_ms:.0f}ms")
        print(f"Errors: {result.errors}")

        print(f"\n=== PRODUCTS ===")
        for i, product in enumerate(result.products[:5], 1):
            print(f"\n{i}. {product.title[:60]}...")
            print(f"   Price: {product.price}")
            print(f"   URL: {product.url[:80]}..." if product.url else "   URL: None")
            print(f"   URL Source: {product.url_source}")
            print(f"   Confidence: {product.confidence:.2f}")

        await browser.close()

        # Return success based on whether we got resolved URLs
        resolved = sum(1 for p in result.products if p.url_source == "click_resolved")
        return resolved > 0


if __name__ == "__main__":
    success = asyncio.run(test_click_resolve())
    sys.exit(0 if success else 1)
