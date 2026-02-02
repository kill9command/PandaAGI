#!/usr/bin/env python3
"""
Test script to verify PDP detection and extraction pipeline fixes.

Tests:
1. PDP URL detection patterns
2. Search URL detection patterns
3. Navigation link garbage filtering
"""

import sys
sys.path.insert(0, '/home/henry/pythonprojects/pandaai')

from apps.services.orchestrator.product_perception.pipeline import ProductPerceptionPipeline
from apps.services.orchestrator.product_perception.html_extractor import HTMLExtractor
from apps.services.orchestrator.product_perception.fusion import match_html_only
from apps.services.orchestrator.product_perception.models import HTMLCandidate


def test_pdp_detection():
    """Test that PDP URLs are correctly identified."""
    print("\n=== Test 1: PDP URL Detection ===\n")

    pipeline = ProductPerceptionPipeline()

    # URLs that SHOULD be detected as PDPs
    pdp_urls = [
        # Best Buy
        "https://www.bestbuy.com/site/product/hp-victus-gaming-laptop/6571234.p",
        "https://www.bestbuy.com/product/hp-victus-15-gaming-laptop-nvidia-rtx-4050-12345",
        # Amazon
        "https://www.amazon.com/dp/B0ABCD1234",
        "https://www.amazon.com/gp/product/B0ABCD1234",
        # Walmart
        "https://www.walmart.com/ip/123456789",
        # Target
        "https://www.target.com/pd/product-name/-/A-12345678",
        # Newegg
        "https://www.newegg.com/p/N82E16834233123/sku",
        "https://www.newegg.com/item/N82E/123456789",
    ]

    # URLs that should NOT be detected as PDPs (search/listing pages)
    non_pdp_urls = [
        # Search pages
        "https://www.bestbuy.com/site/searchpage.jsp?st=gaming+laptop",
        "https://www.amazon.com/s?k=gaming+laptop",
        "https://www.walmart.com/search?q=laptop",
        "https://www.newegg.com/p/pl?d=gaming+laptop",
        # Category/browse pages
        "https://www.bestbuy.com/site/computers-tablets/laptops/pcmcat138500050001.c",
        "https://www.amazon.com/browse/electronics",
        "https://www.walmart.com/shop/electronics/laptops",
        "https://www.target.com/c/laptops/-/N-5xtdp",
    ]

    print("Testing PDP URLs (should return True):")
    all_passed = True
    for url in pdp_urls:
        result = pipeline._is_pdp(url)
        status = "✓" if result else "✗"
        print(f"  {status} {url[:60]}... -> {result}")
        if not result:
            all_passed = False

    print("\nTesting non-PDP URLs (should return False):")
    for url in non_pdp_urls:
        result = pipeline._is_pdp(url)
        status = "✓" if not result else "✗"
        print(f"  {status} {url[:60]}... -> {result}")
        if result:
            all_passed = False

    if all_passed:
        print("\n✓ Test 1 PASSED: PDP detection works correctly\n")
    else:
        print("\n✗ Test 1 FAILED: Some URLs were misclassified\n")

    return all_passed


def test_garbage_link_filtering():
    """Test that navigation/category links are filtered out."""
    print("\n=== Test 2: Garbage Link Filtering ===\n")

    extractor = HTMLExtractor()

    # Link texts that should be filtered (garbage/navigation)
    garbage_links = [
        "Best Buy",
        "Computers & Tablets",
        "Gaming Laptops",
        "Electronics",
        "Home",
        "Cart",
        "Add to Cart",
        "See All",
        "Amazon",
        "Walmart",
    ]

    # Link texts that should NOT be filtered (actual products)
    product_links = [
        "HP Victus 15.6 inch Gaming Laptop with RTX 4050",
        "ASUS TUF Gaming A16 FA617NS-G15",
        "Lenovo LOQ 15IRX9 Gaming Laptop",
        "Dell G15 5530 Gaming Notebook",
        "MSI Katana 15 B13VGK-1613US",
    ]

    print("Testing garbage link text (should be in GARBAGE_LINK_TEXT):")
    all_passed = True
    for text in garbage_links:
        is_garbage = text.lower().strip() in extractor.GARBAGE_LINK_TEXT
        status = "✓" if is_garbage else "✗"
        print(f"  {status} '{text}' -> {'FILTERED' if is_garbage else 'KEPT'}")
        if not is_garbage:
            all_passed = False

    print("\nTesting product link text (should NOT be in GARBAGE_LINK_TEXT):")
    for text in product_links:
        is_garbage = text.lower().strip() in extractor.GARBAGE_LINK_TEXT
        status = "✓" if not is_garbage else "✗"
        print(f"  {status} '{text[:40]}...' -> {'FILTERED' if is_garbage else 'KEPT'}")
        if is_garbage:
            all_passed = False

    if all_passed:
        print("\n✓ Test 2 PASSED: Garbage filtering works correctly\n")
    else:
        print("\n✗ Test 2 FAILED: Some links were misclassified\n")

    return all_passed


def test_html_only_filtering():
    """Test that match_html_only filters navigation links."""
    print("\n=== Test 3: HTML-Only Match Filtering ===\n")

    # Create candidates that include garbage navigation links
    candidates = [
        HTMLCandidate(
            url="https://www.bestbuy.com/",
            link_text="Best Buy",
            context_text="",
            source="url_pattern",
            confidence=0.85
        ),
        HTMLCandidate(
            url="https://www.bestbuy.com/site/computers-tablets/pcmcat138500050001.c",
            link_text="Computers & Tablets",
            context_text="",
            source="url_pattern",
            confidence=0.85
        ),
        HTMLCandidate(
            url="https://www.bestbuy.com/site/laptops/gaming-laptops/pcmcat287600050003.c",
            link_text="Gaming Laptops",
            context_text="",
            source="url_pattern",
            confidence=0.85
        ),
        HTMLCandidate(
            url="https://www.bestbuy.com/product/hp-victus-gaming-laptop-12345",
            link_text="HP Victus 15.6\" Gaming Laptop - NVIDIA GeForce RTX 4050",
            context_text="$799.99",
            source="url_pattern",
            confidence=0.85
        ),
    ]

    products = match_html_only(candidates, "https://www.bestbuy.com/")

    print(f"Input candidates: {len(candidates)}")
    print(f"Output products: {len(products)}")
    print("\nProducts kept:")
    for p in products:
        print(f"  - {p.title[:50]}...")

    # Should only keep the actual product, not the navigation links
    expected_count = 1  # Only the HP Victus
    all_passed = len(products) == expected_count

    if all_passed:
        # Verify the right product was kept
        if products and "HP Victus" in products[0].title:
            print("\n✓ Test 3 PASSED: Navigation links were filtered, product kept\n")
        else:
            print("\n✗ Test 3 FAILED: Wrong product kept\n")
            all_passed = False
    else:
        print(f"\n✗ Test 3 FAILED: Expected {expected_count} product, got {len(products)}\n")

    return all_passed


def main():
    """Run all tests."""
    print("=" * 60)
    print("PDP DETECTION AND FILTERING TEST SUITE")
    print("=" * 60)

    results = []

    try:
        results.append(("PDP URL Detection", test_pdp_detection()))
        results.append(("Garbage Link Filtering", test_garbage_link_filtering()))
        results.append(("HTML-Only Match Filtering", test_html_only_filtering()))

        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)

        all_passed = True
        for name, passed in results:
            status = "✓ PASSED" if passed else "✗ FAILED"
            print(f"  {status}: {name}")
            if not passed:
                all_passed = False

        print("=" * 60)
        if all_passed:
            print("ALL TESTS PASSED ✓")
        else:
            print("SOME TESTS FAILED ✗")
        print("=" * 60)

        return 0 if all_passed else 1

    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
