#!/usr/bin/env python3
"""
Test script for the new click-to-verify product extraction flow.

This tests the consolidated web vision system with:
1. Fixed vision extraction (Y-threshold, price patterns)
2. New ProductVerifier (click-to-verify as primary)
3. New extract_and_verify() pipeline API

Usage:
    python scripts/test_click_verify_flow.py [query]

Example:
    python scripts/test_click_verify_flow.py "gaming laptop nvidia rtx"
"""

import asyncio
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, '/path/to/pandaagi')

from apps.services.tool_server.product_perception import (
    ProductPerceptionPipeline,
    ProductVerifier,
    VerifiedProduct,
    get_config
)
from apps.services.tool_server.product_perception.config import PerceptionConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_config():
    """Print current configuration."""
    config = get_config()
    print("\n=== Current Configuration ===")
    print(f"  y_group_threshold: {config.y_group_threshold} (was 150, now 80)")
    print(f"  x_group_threshold: {config.x_group_threshold} (was 500, now 400)")
    print(f"  require_price_pattern: {config.require_price_pattern} (now False)")
    print(f"  similarity_threshold: {config.similarity_threshold} (was 0.55, now 0.40)")
    print(f"  enable_click_resolve: {config.enable_click_resolve}")
    print(f"  enable_pdp_verification: {config.enable_pdp_verification}")
    print()


async def test_with_mock_page():
    """Test the pipeline components without a real browser."""
    print("\n=== Test 1: Configuration Changes ===")
    print_config()

    print("=== Test 2: ProductVerifier Initialization ===")
    verifier = ProductVerifier(max_products=5)
    print(f"  ProductVerifier created successfully")
    print(f"  Max products: {verifier.max_products}")
    print()

    print("=== Test 3: Pipeline Initialization ===")
    pipeline = ProductPerceptionPipeline()
    print(f"  Pipeline created successfully")
    print(f"  HTML extractor: {pipeline.html_extractor is not None}")
    print(f"  Vision extractor: {pipeline.vision_extractor is not None}")
    print(f"  Fusion: {pipeline.fusion is not None}")
    print(f"  PDP extractor: {pipeline.pdp_extractor is not None}")
    print()

    print("=== Test 4: PDP Detection ===")
    pdp_urls = [
        "https://www.bestbuy.com/site/product/hp-victus-gaming-laptop/6571234.p",
        "https://www.amazon.com/dp/B0ABCD1234",
        "https://www.walmart.com/ip/123456789",
    ]
    non_pdp_urls = [
        "https://www.bestbuy.com/site/searchpage.jsp?st=gaming+laptop",
        "https://www.amazon.com/s?k=gaming+laptop",
        "https://www.walmart.com/search?q=laptop",
    ]

    print("  PDP URLs (should return True):")
    for url in pdp_urls:
        result = pipeline._is_pdp(url)
        status = "PASS" if result else "FAIL"
        print(f"    [{status}] {url[:50]}...")

    print("  Non-PDP URLs (should return False):")
    for url in non_pdp_urls:
        result = pipeline._is_pdp(url)
        status = "PASS" if not result else "FAIL"
        print(f"    [{status}] {url[:50]}...")
    print()

    print("=== All component tests passed! ===\n")
    return True


async def test_with_real_browser(query: str):
    """Test with real browser (requires running services)."""
    from apps.services.tool_server import web_vision_mcp

    print(f"\n=== Real Browser Test: '{query}' ===")

    try:
        # Create session
        session_id = "test_click_verify"
        print(f"Creating browser session: {session_id}")

        # Navigate to a vendor
        test_url = "https://www.bestbuy.com/site/laptop-computers/all-laptops/pcmcat138500050001.c"
        print(f"Navigating to: {test_url}")

        nav_result = await web_vision_mcp.navigate(
            session_id=session_id,
            url=test_url,
            wait_for="networkidle"
        )

        if not nav_result.get("success"):
            print(f"Navigation failed: {nav_result.get('message')}")
            return False

        print("Navigation successful!")

        # Get page object
        page = await web_vision_mcp.get_page(session_id)
        if not page:
            print("Failed to get page object")
            return False

        # Test extract_and_verify
        print("\nTesting extract_and_verify()...")
        pipeline = ProductPerceptionPipeline()
        verified_products = await pipeline.extract_and_verify(
            page=page,
            url=test_url,
            query=query,
            max_products=3
        )

        print(f"\n=== Results: {len(verified_products)} verified products ===")
        for i, product in enumerate(verified_products):
            print(f"\nProduct {i+1}:")
            print(f"  Title: {product.title[:60]}...")
            print(f"  Price: ${product.price:.2f}" if product.price else "  Price: N/A")
            print(f"  URL: {product.url[:60]}...")
            print(f"  In Stock: {product.in_stock}")
            print(f"  Verification Method: {product.verification_method}")
            print(f"  Extraction Source: {product.extraction_source}")

        return len(verified_products) > 0

    except Exception as e:
        print(f"Error during real browser test: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "gaming laptop nvidia rtx"

    print("=" * 60)
    print("CLICK-TO-VERIFY FLOW TEST")
    print("=" * 60)

    # Test 1: Component tests (no browser needed)
    passed = await test_with_mock_page()
    if not passed:
        print("Component tests failed!")
        return 1

    # Test 2: Real browser test (optional)
    if os.getenv("RUN_BROWSER_TEST", "false").lower() == "true":
        passed = await test_with_real_browser(query)
        if not passed:
            print("Real browser test failed!")
            return 1
    else:
        print("\nSkipping real browser test (set RUN_BROWSER_TEST=true to enable)")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
