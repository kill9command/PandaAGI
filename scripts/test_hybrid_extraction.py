#!/usr/bin/env python3
"""
Test script for hybrid vision+HTML product extraction pipeline.

Tests the ProductPerceptionPipeline with a real retailer page.
"""

import asyncio
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.services.orchestrator.product_perception import (
    ProductPerceptionPipeline,
    HTMLExtractor,
    VisionExtractor,
    PerceptionConfig,
    set_config,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_html_extractor():
    """Test HTML extractor with sample HTML."""
    logger.info("=" * 60)
    logger.info("Testing HTMLExtractor")
    logger.info("=" * 60)

    # Sample HTML with JSON-LD and product links
    sample_html = '''
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "Product",
            "name": "MSI Gaming Laptop RTX 4080",
            "url": "/product/msi-gaming-123",
            "offers": {"price": "1299.99"}
        }
        </script>
    </head>
    <body>
        <div class="product">
            <a href="/dp/B0CJ3FYS8T">ASUS ROG Strix Gaming Laptop</a>
            <span class="price">$899.99</span>
        </div>
        <div class="product">
            <a href="/site/lenovo-legion/6578901.p">Lenovo Legion Pro</a>
            <span class="price">$1,199.00</span>
        </div>
    </body>
    </html>
    '''

    extractor = HTMLExtractor()
    candidates = await extractor.extract(sample_html, "https://example.com")

    logger.info(f"Found {len(candidates)} HTML candidates:")
    for i, c in enumerate(candidates):
        logger.info(f"  {i+1}. [{c.source}] {c.link_text[:50]} -> {c.url}")

    assert len(candidates) >= 2, "Should find at least 2 candidates"
    logger.info("HTMLExtractor test PASSED")


async def test_vision_extractor_mock():
    """Test vision extractor parsing logic with mock data."""
    logger.info("=" * 60)
    logger.info("Testing VisionExtractor (mock)")
    logger.info("=" * 60)

    # We can't easily test OCR without a real screenshot
    # But we can test the JSON parsing logic
    extractor = VisionExtractor(
        llm_url="http://127.0.0.1:8000",
        llm_model="qwen3-coder",
        llm_api_key="qwen-local"
    )

    # Test JSON extraction
    test_cases = [
        '[{"title": "Test Product", "price": "$99.99", "price_numeric": 99.99}]',
        '```json\n[{"title": "Test", "price": "$50"}]\n```',
        'Here are the products: [{"title": "Product 1", "price": "$100"}]',
    ]

    for i, test in enumerate(test_cases):
        result = extractor._extract_json_array(test)
        logger.info(f"  Test {i+1}: Parsed {len(result)} products from JSON")
        assert len(result) >= 1, f"Should parse at least 1 product from test case {i+1}"

    logger.info("VisionExtractor JSON parsing test PASSED")


async def test_full_pipeline():
    """Test full pipeline with a real browser (requires Playwright)."""
    logger.info("=" * 60)
    logger.info("Testing Full ProductPerceptionPipeline")
    logger.info("=" * 60)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed, skipping full pipeline test")
        return

    # Check if services are running
    import httpx
    try:
        api_key = os.getenv("SOLVER_API_KEY", "qwen-local")
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "http://127.0.0.1:8000/v1/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            if resp.status_code != 200:
                logger.warning(f"vLLM not running (status {resp.status_code}), skipping full pipeline test")
                return
    except Exception as e:
        logger.warning(f"vLLM not reachable ({e}), skipping full pipeline test")
        return

    # Run full test
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Navigate to Best Buy (or another retailer)
        test_url = "https://www.bestbuy.com/site/searchpage.jsp?st=gaming+laptop"
        logger.info(f"Navigating to: {test_url}")

        try:
            await page.goto(test_url, timeout=30000)
            await page.wait_for_load_state('networkidle', timeout=10000)
        except Exception as e:
            logger.warning(f"Navigation failed (may be blocked): {e}")
            await browser.close()
            return

        # Initialize pipeline
        pipeline = ProductPerceptionPipeline()

        # Run extraction
        logger.info("Running hybrid extraction...")
        result = await pipeline.extract_with_stats(
            page=page,
            url=page.url,
            query="gaming laptop"
        )

        logger.info(f"Extraction complete:")
        logger.info(f"  HTML candidates: {result.html_candidates_count}")
        logger.info(f"  Vision products: {result.vision_products_count}")
        logger.info(f"  Fusion matches: {result.fusion_matches}")
        logger.info(f"  Click resolved: {result.click_resolved}")
        logger.info(f"  Total products: {len(result.products)}")
        logger.info(f"  Time: {result.extraction_time_ms:.0f}ms")

        if result.errors:
            logger.warning(f"  Errors: {result.errors}")

        # Show products
        logger.info("\nExtracted products:")
        for i, p in enumerate(result.products[:5]):
            logger.info(f"  {i+1}. {p.title[:50]}...")
            logger.info(f"      Price: {p.price_str}")
            logger.info(f"      URL: {p.url[:60]}...")
            logger.info(f"      Method: {p.extraction_method}, URL source: {p.url_source}")

        await browser.close()

        if len(result.products) > 0:
            logger.info("\nFull pipeline test PASSED")
        else:
            logger.warning("\nFull pipeline test: No products extracted (may be blocked)")


async def main():
    """Run all tests."""
    logger.info("Starting Hybrid Extraction Pipeline Tests")
    logger.info("=" * 60)

    # Configure for testing
    config = PerceptionConfig(
        enable_hybrid=True,
        enable_click_resolve=False,  # Disable for faster testing
        ocr_use_gpu=True,
        save_debug_screenshots=False,
    )
    set_config(config)

    # Run tests
    await test_html_extractor()
    print()
    await test_vision_extractor_mock()
    print()
    await test_full_pipeline()

    logger.info("\n" + "=" * 60)
    logger.info("All tests complete!")


if __name__ == "__main__":
    asyncio.run(main())
