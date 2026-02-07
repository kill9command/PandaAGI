#!/usr/bin/env python3
"""
Test script to verify LLM vendor domain hallucination fix.
"""

import sys
sys.path.insert(0, '/path/to/pandaagi')

from apps.services.tool_server.llm_candidate_filter import _extract_domain


def test_domain_extraction():
    """Test that domains are correctly extracted from URLs."""
    print("\n=== Test: Domain Extraction ===\n")

    test_cases = [
        ("https://www.bestbuy.com/site/product/12345", "bestbuy.com"),
        ("https://hp.com/us-en/shop/pdp/laptop", "hp.com"),
        ("https://www.amazon.com/dp/B0123456789", "amazon.com"),
        ("https://www.newegg.com/p/N82E16834233", "newegg.com"),
        ("https://walmart.com/ip/123456789", "walmart.com"),
    ]

    all_passed = True
    for url, expected in test_cases:
        actual = _extract_domain(url)
        status = "✓" if actual == expected else "✗"
        print(f"  {status} {url[:50]}... → {actual} (expected: {expected})")
        if actual != expected:
            all_passed = False

    if all_passed:
        print("\n✓ All domain extraction tests passed\n")
    else:
        print("\n✗ Some domain extraction tests failed\n")

    return all_passed


def test_hallucination_detection():
    """Verify that hallucinated domains would be caught."""
    print("\n=== Test: Hallucination Detection Logic ===\n")

    # Simulate what the fix does
    test_cases = [
        # (llm_domain, actual_url, should_warn)
        ("bestbuy.com", "https://www.hp.com/us-en/shop/laptop", True),
        ("amazon.com", "https://www.amazon.com/dp/B012345", False),
        ("newegg.com", "https://hp.com/custom/laptop-15t", True),
        ("hp.com", "https://hp.com/shop/pdp/probook", False),
    ]

    all_passed = True
    for llm_domain, actual_url, should_warn in test_cases:
        actual_domain = _extract_domain(actual_url)
        would_warn = llm_domain != actual_domain

        status = "✓" if would_warn == should_warn else "✗"
        result = "WARN" if would_warn else "OK"
        expected = "WARN" if should_warn else "OK"

        print(f"  {status} LLM: '{llm_domain}' vs Actual: '{actual_domain}' → {result} (expected: {expected})")

        if would_warn != should_warn:
            all_passed = False

    if all_passed:
        print("\n✓ Hallucination detection logic correct\n")
    else:
        print("\n✗ Hallucination detection has issues\n")

    return all_passed


def main():
    """Run all tests."""
    print("=" * 60)
    print("VENDOR SELECTION FIX TEST SUITE")
    print("=" * 60)

    results = []
    results.append(("Domain Extraction", test_domain_extraction()))
    results.append(("Hallucination Detection", test_hallucination_detection()))

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


if __name__ == "__main__":
    sys.exit(main())
