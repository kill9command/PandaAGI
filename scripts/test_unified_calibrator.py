#!/usr/bin/env python3
"""
Test script for the LLM-Driven Unified Site Calibrator.

The calibrator uses LLM to:
1. Analyze page structure
2. Create extraction schema
3. Test and self-correct (up to 3 iterations)
4. Save "instruction manual" for future use

Usage:
    python scripts/test_unified_calibrator.py
    python scripts/test_unified_calibrator.py --url https://amazon.com/s?k=laptop
    python scripts/test_unified_calibrator.py --force  # Ignore cache
    python scripts/test_unified_calibrator.py --list   # Show saved schemas
"""

import argparse
import asyncio
import json
import logging
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.services.tool_server.unified_calibrator import UnifiedCalibrator, get_calibrator

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


# Test sites
TEST_SITES = {
    "amazon": "https://www.amazon.com/s?k=laptop",
    "newegg": "https://www.newegg.com/p/pl?d=laptop",
    "bestbuy": "https://www.bestbuy.com/site/searchpage.jsp?st=laptop",
    "walmart": "https://www.walmart.com/search?q=laptop",
}


async def test_calibration(url: str, force: bool = False):
    """Test calibration on a single URL."""
    from playwright.async_api import async_playwright

    logger.info(f"\n{'='*60}")
    logger.info(f"Testing calibration for: {url}")
    logger.info(f"{'='*60}\n")

    calibrator = get_calibrator()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        try:
            # Navigate to site
            logger.info(f"Navigating to {url}...")
            await page.goto(url, timeout=60000)
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            # Run calibration
            schema = await calibrator.get_profile(
                page=page,
                url=url,
                force_recalibrate=force
            )

            # Print results
            print_schema(schema)

            return schema

        except Exception as e:
            logger.error(f"Calibration failed: {e}")
            import traceback
            traceback.print_exc()
            return None

        finally:
            await browser.close()


def print_schema(schema: dict):
    """Pretty print a calibration schema."""
    print("\n" + "="*60)
    print(f"CALIBRATION SCHEMA: {schema.get('domain', 'unknown')}")
    print("="*60)

    print(f"\nSite Intent: {schema.get('site_intent', 'unknown')}")
    print(f"Validated: {'Yes' if schema.get('validated') else 'No (best effort)'}")
    print(f"Learned: {schema.get('learned_at', 'unknown')}")

    print("\n--- ITEM EXTRACTION ---")
    print(f"  Item selector: {schema.get('item_selector')}")

    if schema.get("fields"):
        print("\n  Fields:")
        for field, config in schema["fields"].items():
            selector = config.get("selector", "N/A")
            attr = config.get("attribute", "textContent")
            print(f"    {field}: {selector} -> {attr}")

    print("\n--- URL PATTERNS ---")
    patterns = schema.get("url_patterns", {})
    print(f"  Search param: {patterns.get('search_param')}")
    print(f"  Price param: {patterns.get('price_param')}")
    print(f"  Price encoding: {patterns.get('price_encoding')}")

    if schema.get("error"):
        print(f"\n--- ERROR ---")
        print(f"  {schema['error']}")

    print("\n" + "="*60 + "\n")


def list_schemas():
    """List all saved schemas."""
    schema_dir = Path("site_profiles")
    if not schema_dir.exists():
        print("No schemas saved yet.")
        return

    schemas = list(schema_dir.glob("*.json"))
    if not schemas:
        print("No schemas saved yet.")
        return

    print(f"\n{'='*60}")
    print("SAVED CALIBRATION SCHEMAS")
    print("="*60 + "\n")

    for path in sorted(schemas):
        try:
            with open(path) as f:
                schema = json.load(f)
            status = "VALIDATED" if schema.get("validated") else "PARTIAL"
            search = schema.get("url_patterns", {}).get("search_param", "?")
            print(f"  [{status}] {path.stem}")
            print(f"           Search param: {search}")
            print(f"           Learned: {schema.get('learned_at', 'unknown')[:19]}")
            print()
        except Exception as e:
            print(f"  [ERROR] {path.stem}: {e}")


async def main():
    parser = argparse.ArgumentParser(description="Test LLM-Driven Site Calibrator")
    parser.add_argument("--site", type=str, help="Site name (amazon, newegg, bestbuy, walmart)")
    parser.add_argument("--url", type=str, help="Specific URL to test")
    parser.add_argument("--force", action="store_true", help="Force recalibration (ignore cache)")
    parser.add_argument("--list", action="store_true", help="List saved schemas")
    parser.add_argument("--all", action="store_true", help="Test all sites")

    args = parser.parse_args()

    if args.list:
        list_schemas()
        return

    if args.url:
        await test_calibration(args.url, force=args.force)
        return

    if args.site:
        if args.site in TEST_SITES:
            await test_calibration(TEST_SITES[args.site], force=args.force)
        else:
            print(f"Unknown site: {args.site}")
            print(f"Available: {', '.join(TEST_SITES.keys())}")
        return

    if args.all:
        for name, url in TEST_SITES.items():
            print(f"\n\n{'#'*60}")
            print(f"# Testing {name.upper()}")
            print(f"{'#'*60}")
            await test_calibration(url, force=args.force)
        return

    # Default: show help
    parser.print_help()
    print("\nExamples:")
    print("  python scripts/test_unified_calibrator.py --site amazon")
    print("  python scripts/test_unified_calibrator.py --url https://example.com/search")
    print("  python scripts/test_unified_calibrator.py --list")
    print("  python scripts/test_unified_calibrator.py --all")


if __name__ == "__main__":
    asyncio.run(main())
