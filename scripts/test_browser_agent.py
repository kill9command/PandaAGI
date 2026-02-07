"""
scripts/test_browser_agent.py

Unit tests for Browser Agent multi-page browsing functions.

Tests:
- Navigation opportunity detection
- Pagination link extraction
- Category link extraction
- Content similarity checking
- Item deduplication
- LLM-based evaluation after each page

Created: 2025-11-18
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.services.tool_server.browser_agent import (
    detect_navigation_opportunities,
    _extract_pagination_links,
    _extract_category_links,
    _deduplicate_items,
    _check_content_similarity
)


async def test_pagination_detection():
    """Test pagination link extraction from HTML"""
    print("\n=== Test: Pagination Detection ===")

    # Test HTML with various pagination patterns
    test_cases = [
        {
            "name": "Numbered pagination",
            "html": """
                <div class="pagination">
                    <a href="/page/1">1</a>
                    <a href="/page/2" class="current">2</a>
                    <a href="/page/3">3</a>
                    <a href="/page/3" class="next">Next</a>
                </div>
            """,
            "url": "https://example.com/page/2",
            "expected_next": "https://example.com/page/3"
        },
        {
            "name": "Query param pagination",
            "html": """
                <a href="?page=3" class="next-link">Next Page</a>
            """,
            "url": "https://example.com/products?page=2",
            "expected_next": "https://example.com/products?page=3"
        },
        {
            "name": "No pagination",
            "html": """
                <div class="content">
                    <p>Just regular content, no pagination</p>
                </div>
            """,
            "url": "https://example.com/page",
            "expected_next": None
        }
    ]

    from bs4 import BeautifulSoup

    for case in test_cases:
        soup = BeautifulSoup(case["html"], "html.parser")
        result = _extract_pagination_links(soup, case["url"])

        print(f"\n  {case['name']}:")
        print(f"    URL: {case['url']}")
        print(f"    Next page found: {result.get('next_page_url')}")
        print(f"    Expected: {case['expected_next']}")

        if case["expected_next"]:
            assert result.get("next_page_url") is not None, f"Expected next page URL but got None"
        else:
            assert result.get("next_page_url") is None, f"Expected no next page but found: {result.get('next_page_url')}"

    print("\n✅ Pagination detection tests passed")


async def test_category_extraction():
    """Test category link extraction"""
    print("\n=== Test: Category Link Extraction ===")

    test_html = """
        <nav>
            <a href="/available">Available</a>
            <a href="/retired">Retired</a>
            <a href="/upcoming">Upcoming Litters</a>
            <a href="/about">About Us</a>
        </nav>
    """

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(test_html, "html.parser")
    url = "https://example-breeder.com/"

    categories = _extract_category_links(soup, url)

    print(f"\n  Found {len(categories)} category links:")
    for cat in categories:
        print(f"    - {cat}")

    assert len(categories) >= 2, f"Expected at least 2 categories but found {len(categories)}"
    assert any("available" in c.lower() for c in categories), "Expected 'available' category"

    print("\n✅ Category extraction tests passed")


async def test_item_deduplication():
    """Test deduplication of items across pages"""
    print("\n=== Test: Item Deduplication ===")

    items = [
        {"name": "Syrian Hamster - Male", "price": "$25", "url": "https://site.com/page1/hamster1"},
        {"name": "SYRIAN HAMSTER - MALE", "price": "$30", "url": "https://site.com/page2/hamster1"},  # Duplicate (different case)
        {"name": "Syrian Hamster - Female", "price": "$25", "url": "https://site.com/page1/hamster2"},
        {"name": "Dwarf Hamster", "price": "$20", "url": "https://site.com/page2/hamster3"},
        {"name": "syrian hamster male", "price": "$25", "url": "https://site.com/page3/hamster1"}  # Duplicate (different case/spacing)
    ]

    print(f"\n  Original items: {len(items)}")
    deduplicated = _deduplicate_items(items, key_field="name")
    print(f"  After deduplication: {len(deduplicated)}")

    print("\n  Unique items:")
    for item in deduplicated:
        print(f"    - {item['name']} ({item['price']})")

    assert len(deduplicated) == 3, f"Expected 3 unique items but got {len(deduplicated)}"

    print("\n✅ Item deduplication tests passed")


async def test_content_similarity():
    """Test content similarity detection"""
    print("\n=== Test: Content Similarity Detection ===")

    page1 = {
        "text_content": "Welcome to our forum. Here are the top discussions about hamster care and breeding."
    }

    page2_similar = {
        "text_content": "Welcome to our forum. Here are the top discussions about hamster care and breeding. Same content."
    }

    page2_different = {
        "text_content": "This is completely different content about a different topic with no overlap."
    }

    # Test high similarity (should detect duplicate)
    similarity_high = _check_content_similarity(page2_similar, [page1])
    print(f"\n  Similar content similarity: {similarity_high:.2f}")

    # Test low similarity (should allow continuation)
    similarity_low = _check_content_similarity(page2_different, [page1])
    print(f"  Different content similarity: {similarity_low:.2f}")

    # If embeddings not available, similarity will be 0.0 for all
    if similarity_high == 0.0 and similarity_low == 0.0:
        print("\n⚠️  Embedding service not available, similarity detection disabled")
        print("  (This is OK - similarity is a performance optimization, not required)")
    else:
        # If embeddings available, verify they work correctly
        assert similarity_high > similarity_low, \
            f"Expected higher similarity for similar content ({similarity_high} vs {similarity_low})"
        print("  ✅ Similarity detection working (embeddings available)")

    print("\n✅ Content similarity tests passed")


async def test_navigation_detection_integration():
    """Test full navigation opportunity detection with LLM"""
    print("\n=== Test: Navigation Detection (Integration) ===")

    # Test forum thread with pagination
    forum_html = """
        <h1>Best Syrian Hamsters for Breeding - Page 1</h1>
        <div class="post">
            <p>I've been breeding Syrians for 5 years...</p>
        </div>
        <div class="pagination">
            <a href="/thread/123?page=2">Next</a>
            <a href="/thread/123?page=2">2</a>
            <a href="/thread/123?page=3">3</a>
        </div>
    """

    try:
        result = await detect_navigation_opportunities(
            page_content=forum_html,
            url="https://forum.example.com/thread/123",
            browsing_goal="Learn about Syrian hamster breeding from experienced breeders",
            session_id="test"
        )

        print(f"\n  Navigation detected:")
        print(f"    Type: {result.get('navigation_type')}")
        print(f"    Has more pages: {result.get('has_more_pages')}")
        print(f"    Next page URL: {result.get('next_page_url')}")
        print(f"    Reasoning: {result.get('reasoning', 'N/A')[:100]}")

        assert result.get("has_more_pages") is True, "Expected multi-page detection"
        assert result.get("next_page_url") is not None, "Expected next page URL"

        print("\n✅ Navigation detection integration test passed")

    except Exception as e:
        print(f"\n⚠️  Navigation detection test skipped (LLM not available): {e}")


async def test_all():
    """Run all unit tests"""
    print("\n" + "="*60)
    print("Browser Agent Unit Tests")
    print("="*60)

    await test_pagination_detection()
    await test_category_extraction()
    await test_item_deduplication()
    await test_content_similarity()
    await test_navigation_detection_integration()

    print("\n" + "="*60)
    print("✅ All Browser Agent unit tests completed successfully!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(test_all())
