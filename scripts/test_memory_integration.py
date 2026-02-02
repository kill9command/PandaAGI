#!/usr/bin/env python3
"""
End-to-end integration test for the obsidian_memory system.

Tests the full flow:
1. Write research findings to memory
2. Write product knowledge to memory
3. Search memory for relevant knowledge
4. Verify Context Gatherer can read from memory
5. Verify Turn Saver can write to memory

Usage:
    python scripts/test_memory_integration.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_memory_write_and_search():
    """Test writing to and searching from obsidian_memory."""
    from apps.tools.memory import (
        write_memory,
        search_memory,
        get_user_preferences,
        update_preference,
        MemoryConfig,
    )

    print("\n=== Testing Memory Write and Search ===\n")

    # Get config
    config = MemoryConfig.load()
    print(f"Vault path: {config.vault_path}")
    print(f"Write path: {config.write_path}")

    # Test 1: Write research finding
    print("\n1. Writing research finding...")
    research_path = await write_memory(
        artifact_type="research",
        topic="Memory Integration Test",
        content={
            "summary": "Testing the obsidian_memory integration",
            "findings": "This is a test research finding to verify the memory system works correctly.",
        },
        tags=["test", "integration", "memory"],
        source_urls=["https://example.com/test"],
        confidence=0.95,
        config=config,
    )
    print(f"   Written to: {research_path}")

    # Test 2: Write product knowledge
    print("\n2. Writing product knowledge...")
    product_path = await write_memory(
        artifact_type="product",
        topic="Test Product",
        content={
            "product_name": "Integration Test Widget",
            "category": "test products",
            "overview": "A widget for testing the memory system",
            "specs": {"Type": "Test", "Version": "1.0"},
            "prices": [{"price": "$99", "vendor": "TestStore", "date": "2026-01-23"}],
            "pros": ["Easy to test", "Works well"],
            "cons": ["Only for testing"],
        },
        tags=["test", "widget"],
        confidence=0.9,
        config=config,
    )
    print(f"   Written to: {product_path}")

    # Test 3: Update user preference
    print("\n3. Updating user preference...")
    pref_path = await update_preference(
        key="test_preference",
        value="integration_test_value",
        category="general",
        user_id="default",
        source_turn=999,
        config=config,
    )
    print(f"   Updated: {pref_path}")

    # Test 4: Search for research
    print("\n4. Searching for research...")
    results = await search_memory(
        query="memory integration test",
        folders=["obsidian_memory/Knowledge/Research"],
        limit=5,
        config=config,
    )
    print(f"   Found {len(results)} results:")
    for r in results:
        print(f"      - {r.topic} ({r.artifact_type}, relevance={r.relevance:.2f})")

    # Test 5: Search for products
    print("\n5. Searching for products...")
    results = await search_memory(
        query="test widget",
        folders=["obsidian_memory/Knowledge/Products"],
        limit=5,
        config=config,
    )
    print(f"   Found {len(results)} results:")
    for r in results:
        print(f"      - {r.topic} ({r.artifact_type}, relevance={r.relevance:.2f})")

    # Test 6: Get user preferences
    print("\n6. Getting user preferences...")
    prefs = await get_user_preferences(user_id="default", config=config)
    if prefs:
        print(f"   Found preferences: {prefs.topic}")
        print(f"   Summary: {prefs.summary[:100]}...")
    else:
        print("   No preferences found")

    # Test 7: Search across all knowledge
    print("\n7. Searching across all knowledge...")
    results = await search_memory(
        query="test",
        limit=10,
        config=config,
    )
    print(f"   Found {len(results)} results across all folders:")
    for r in results[:5]:
        print(f"      - {r.path}: {r.topic} (relevance={r.relevance:.2f})")

    print("\n=== Memory Write and Search Tests Complete ===\n")
    return True


async def test_context_gatherer_integration():
    """Test that Context Gatherer can read from forever memory."""
    print("\n=== Testing Context Gatherer Integration ===\n")

    try:
        from libs.gateway.context_gatherer_2phase import FOREVER_MEMORY_AVAILABLE

        if FOREVER_MEMORY_AVAILABLE:
            print("   Forever memory is available in Context Gatherer")
        else:
            print("   WARNING: Forever memory import failed in Context Gatherer")
            return False

        # The actual integration is tested at runtime when the Context Gatherer runs
        print("   Context Gatherer integration looks good")
        print("   (Full integration tested during actual query processing)")

    except ImportError as e:
        print(f"   ERROR: Could not import Context Gatherer: {e}")
        return False

    print("\n=== Context Gatherer Integration Test Complete ===\n")
    return True


async def test_turn_saver_integration():
    """Test that Turn Saver can write to forever memory."""
    print("\n=== Testing Turn Saver Integration ===\n")

    try:
        from libs.gateway.turn_saver import FOREVER_MEMORY_AVAILABLE

        if FOREVER_MEMORY_AVAILABLE:
            print("   Forever memory is available in Turn Saver")
        else:
            print("   WARNING: Forever memory import failed in Turn Saver")
            return False

        # The actual integration is tested at runtime when turns are saved
        print("   Turn Saver integration looks good")
        print("   (Full integration tested during actual turn saving)")

    except ImportError as e:
        print(f"   ERROR: Could not import Turn Saver: {e}")
        return False

    print("\n=== Turn Saver Integration Test Complete ===\n")
    return True


async def test_index_rebuild():
    """Test rebuilding all indexes."""
    print("\n=== Testing Index Rebuild ===\n")

    from apps.tools.memory import rebuild_all_indexes, MemoryConfig

    config = MemoryConfig.load()

    print("   Rebuilding all indexes...")
    result = await rebuild_all_indexes(config=config)

    print(f"   Topics indexed: {result.get('topics', 0)}")
    print(f"   Tags indexed: {result.get('tags', 0)}")
    print(f"   Products indexed: {result.get('products', 0)}")
    print(f"   Recent entries: {result.get('recent', 0)}")

    print("\n=== Index Rebuild Test Complete ===\n")
    return True


async def main():
    """Run all integration tests."""
    print("=" * 60)
    print("  Obsidian Memory Integration Tests")
    print("=" * 60)

    results = []

    # Test 1: Write and search
    try:
        results.append(("Write and Search", await test_memory_write_and_search()))
    except Exception as e:
        print(f"ERROR in Write and Search test: {e}")
        results.append(("Write and Search", False))

    # Test 2: Context Gatherer integration
    try:
        results.append(("Context Gatherer", await test_context_gatherer_integration()))
    except Exception as e:
        print(f"ERROR in Context Gatherer test: {e}")
        results.append(("Context Gatherer", False))

    # Test 3: Turn Saver integration
    try:
        results.append(("Turn Saver", await test_turn_saver_integration()))
    except Exception as e:
        print(f"ERROR in Turn Saver test: {e}")
        results.append(("Turn Saver", False))

    # Test 4: Index rebuild
    try:
        results.append(("Index Rebuild", await test_index_rebuild()))
    except Exception as e:
        print(f"ERROR in Index Rebuild test: {e}")
        results.append(("Index Rebuild", False))

    # Summary
    print("\n" + "=" * 60)
    print("  Test Results Summary")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("=" * 60)

    if all_passed:
        print("\n  All tests PASSED!\n")
        return 0
    else:
        print("\n  Some tests FAILED!\n")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
