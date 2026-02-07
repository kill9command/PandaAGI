#!/usr/bin/env python3
"""
Test script to verify viability filter fixes work for multiple query types.

Tests:
1. Requirements separation (hard vs nice-to-have)
2. Viability scoring with different requirement types
3. Click resolver accessory detection
4. Stats extraction helper
"""

import asyncio
import sys
sys.path.insert(0, '/path/to/pandaagi')

from apps.services.tool_server.product_viability import _format_requirements, check_keyword_viability
from apps.services.tool_server.product_perception.resolver import URLResolver
from apps.services.tool_server.research_role import ResearchRole


def test_format_requirements():
    """Test that requirements are properly separated into hard vs nice-to-have."""
    print("\n=== Test 1: Requirements Separation ===\n")

    # Test case 1: Laptop with nvidia gpu
    requirements = {
        "user_explicit_requirements": ["laptop", "nvidia gpu", "AI use"],
        "forum_recommendations": ["RTX 4060+", "16GB VRAM", "good cooling"],
        "hard_requirements": ["laptop", "NVIDIA GPU"],
        "nice_to_haves": ["RTX 4060 or better", "16GB RAM"],
        "key_requirements": ["NVIDIA GPU", "laptop", "RTX 4060+"],
        "price_range": {"min": 700, "max": 1500},
        "recommended_brands": ["ASUS", "MSI"]
    }
    query = "I want a laptop with nvidia gpu for AI use"

    hard_text, nice_text = _format_requirements(requirements, query)

    print(f"Query: {query}")
    print(f"\nHARD REQUIREMENTS:\n{hard_text}")
    print(f"\nNICE TO HAVE:\n{nice_text}")

    # Verify RTX 4060+ is in nice-to-have, not hard requirements
    assert "RTX 4060" in nice_text or "4060" in nice_text, "RTX 4060+ should be nice-to-have"
    assert "laptop" in hard_text.lower(), "laptop should be hard requirement"
    assert "nvidia" in hard_text.lower(), "nvidia should be hard requirement"
    print("\n✓ Test 1 PASSED: RTX 4060+ correctly categorized as nice-to-have\n")

    # Test case 2: Hamster cage (non-tech query)
    requirements2 = {
        "user_explicit_requirements": ["hamster cage", "large"],
        "hard_requirements": ["cage", "hamster-appropriate"],
        "nice_to_haves": ["multi-level", "exercise wheel included"],
        "key_requirements": ["hamster cage", "large size"],
        "price_range": {"min": 30, "max": 100}
    }
    query2 = "I need a large hamster cage"

    hard_text2, nice_text2 = _format_requirements(requirements2, query2)

    print(f"Query: {query2}")
    print(f"\nHARD REQUIREMENTS:\n{hard_text2}")
    print(f"\nNICE TO HAVE:\n{nice_text2}")

    assert "hamster" in hard_text2.lower() or "cage" in hard_text2.lower(), "hamster cage should be hard requirement"
    print("\n✓ Test 2 PASSED: Non-tech query works correctly\n")

    # Test case 3: Empty requirements (fallback)
    hard_text3, nice_text3 = _format_requirements({}, "find me something")
    print(f"Empty requirements test:")
    print(f"  Hard: {hard_text3}")
    print(f"  Nice: {nice_text3}")
    # Empty requirements should return a reasonable fallback message
    assert "No specific" in hard_text3 or "None" in hard_text3, "Empty requirements should indicate none specified"
    print("\n✓ Test 3 PASSED: Empty requirements handled correctly\n")


def test_accessory_link_detection():
    """Test that accessory/warranty links are properly detected."""
    print("\n=== Test 2: Accessory Link Detection ===\n")

    resolver = URLResolver()

    # Links that should be skipped
    accessory_links = [
        "/product/geek-squad-protection",
        "/product/1-year-accidental-geek-squad-protection",
        "/product/warranty-plan",
        "/product/applecare-plus",
        "/accessories/laptop-bags",
        "/cart/add",
    ]

    # Links that should NOT be skipped
    product_links = [
        "/product/asus-tuf-gaming-laptop",
        "/product/gigabyte-gaming-a16",
        "/ip/dell-inspiron-15",
        "/dp/B0123456789",
    ]

    print("Testing accessory detection:")
    for link in accessory_links:
        is_accessory = resolver._is_accessory_link(link)
        status = "✓" if is_accessory else "✗"
        print(f"  {status} {link} -> {'SKIP' if is_accessory else 'KEEP'}")
        assert is_accessory, f"Expected {link} to be detected as accessory"

    print("\nTesting product links (should NOT be skipped):")
    for link in product_links:
        is_accessory = resolver._is_accessory_link(link)
        status = "✓" if not is_accessory else "✗"
        print(f"  {status} {link} -> {'SKIP' if is_accessory else 'KEEP'}")
        assert not is_accessory, f"Expected {link} to NOT be detected as accessory"

    print("\n✓ Test 2 PASSED: Accessory links correctly detected\n")


def test_link_matches_product():
    """Test that links are matched to products correctly."""
    print("\n=== Test 3: Link-Product Matching ===\n")

    resolver = URLResolver()

    # Test cases: (href, link_text, product_title, expected_match)
    test_cases = [
        ("/product/gaming-laptop-rtx4050", "Gaming Laptop RTX4050", "GAMING A16", True),
        ("/product/geek-squad-protection", "Geek Squad", "GAMING A16", False),
        ("/ip/asus-tuf-gaming", "ASUS TUF Gaming", "ASUS TUF Gaming A16", True),
        ("/product/something-else", "Something Else", "Dell Inspiron 15", False),
        ("/product/dell-inspiron-15-laptop", "Dell Inspiron", "Dell Inspiron 15", True),
    ]

    for href, link_text, product_title, expected in test_cases:
        matches = resolver._link_matches_product(href, link_text, product_title)
        status = "✓" if matches == expected else "✗"
        result = "MATCH" if matches else "NO MATCH"
        expected_str = "MATCH" if expected else "NO MATCH"
        print(f"  {status} '{product_title}' vs '{link_text}' -> {result} (expected: {expected_str})")
        assert matches == expected, f"Expected {expected_str} for {product_title} vs {link_text}"

    print("\n✓ Test 3 PASSED: Link-product matching works correctly\n")


def test_stats_extraction():
    """Test that stats are extracted correctly from different result formats."""
    print("\n=== Test 4: Stats Extraction ===\n")

    role = ResearchRole()

    # Test case 1: intelligent_vendor_search format
    result1 = {
        "synthesis": {
            "total_sources": 4,
            "vendors_visited": ["hp.com", "bestbuy.com", "walmart.com", "lenovo.com"]
        },
        "stats": {}
    }
    count1 = role._extract_sources_count(result1)
    print(f"  intelligent_vendor_search format: {count1} sources")
    assert count1 == 4, f"Expected 4 sources, got {count1}"

    # Test case 2: gather_intelligence format
    result2 = {
        "stats": {
            "sources_checked": 7
        }
    }
    count2 = role._extract_sources_count(result2)
    print(f"  gather_intelligence format: {count2} sources")
    assert count2 == 7, f"Expected 7 sources, got {count2}"

    # Test case 3: Empty result
    count3 = role._extract_sources_count({})
    print(f"  Empty result: {count3} sources")
    assert count3 == 0, f"Expected 0 sources, got {count3}"

    # Test case 4: vendors_visited only (no total_sources)
    result4 = {
        "synthesis": {
            "vendors_visited": ["amazon.com", "newegg.com", "bhphoto.com"]
        }
    }
    count4 = role._extract_sources_count(result4)
    print(f"  vendors_visited only: {count4} sources")
    assert count4 == 3, f"Expected 3 sources, got {count4}"

    print("\n✓ Test 4 PASSED: Stats extraction works for all formats\n")


def test_keyword_viability():
    """Test keyword-based viability fallback for different product types."""
    print("\n=== Test 5: Keyword Viability (Multiple Query Types) ===\n")

    # Test case 1: Laptop query
    product1 = {
        "name": "ASUS TUF Gaming A16 with RTX 4050",
        "url": "/product/asus-tuf-gaming-a16-rtx-4050",
        "description": "Gaming laptop with NVIDIA RTX 4050 GPU"
    }
    requirements1 = {"key_requirements": ["laptop", "NVIDIA GPU"]}
    query1 = "laptop with nvidia gpu"

    result1 = check_keyword_viability(product1, requirements1, query1)
    print(f"  Laptop query: '{query1}' vs '{product1['name'][:40]}...' -> {'VIABLE' if result1 else 'REJECTED'}")
    assert result1, "RTX 4050 laptop should be viable for 'nvidia gpu' query"

    # Test case 2: Hamster query
    product2 = {
        "name": "Large Multi-Level Hamster Cage",
        "url": "/product/hamster-cage-large",
        "description": "Spacious cage for Syrian hamsters"
    }
    requirements2 = {"key_requirements": ["hamster cage", "large"]}
    query2 = "large hamster cage"

    result2 = check_keyword_viability(product2, requirements2, query2)
    print(f"  Hamster query: '{query2}' vs '{product2['name'][:40]}...' -> {'VIABLE' if result2 else 'REJECTED'}")
    assert result2, "Hamster cage should be viable for hamster query"

    # Test case 3: Mismatched product
    product3 = {
        "name": "Cat Food Premium Blend",
        "url": "/product/cat-food",
        "description": "Premium cat food"
    }
    result3 = check_keyword_viability(product3, requirements2, query2)
    print(f"  Mismatch test: '{query2}' vs '{product3['name'][:40]}...' -> {'VIABLE' if result3 else 'REJECTED'}")
    assert not result3, "Cat food should NOT be viable for hamster query"

    print("\n✓ Test 5 PASSED: Keyword viability works for multiple query types\n")


def main():
    """Run all tests."""
    print("=" * 60)
    print("VIABILITY FIXES TEST SUITE")
    print("=" * 60)

    try:
        test_format_requirements()
        test_accessory_link_detection()
        test_link_matches_product()
        test_stats_extraction()
        test_keyword_viability()

        print("=" * 60)
        print("ALL TESTS PASSED ✓")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
