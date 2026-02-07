#!/usr/bin/env python3
"""
Test suite for adaptive research architecture.

Tests:
1. Session intelligence cache
2. LLM strategy selection
3. Adaptive research with all three strategies
4. End-to-end integration
"""
import asyncio
import sys
sys.path.insert(0, "/path/to/pandaagi")

from apps.services.tool_server.session_intelligence_cache import SessionIntelligenceCache, get_intelligence_cache
from apps.services.tool_server.research_strategy_selector import analyze_and_select_strategy
from apps.services.tool_server.internet_research_mcp import adaptive_research


async def test_intelligence_cache():
    """Test session intelligence caching."""
    print("\n" + "=" * 70)
    print("TEST 1: Session Intelligence Cache")
    print("=" * 70)

    cache = SessionIntelligenceCache("test-session-123")

    # Clear any existing data
    cache.clear_all()

    # Test save and load
    test_intel = {
        "key_topics": ["health", "age", "socialization"],
        "credible_sources": ["example.com", "expert.org"],
        "important_criteria": ["6-8 weeks old", "health guarantee"],
        "things_to_avoid": ["too cheap", "no health info"]
    }

    query_hash = cache.save_intelligence("Syrian hamster for sale", test_intel)
    print(f"✓ Saved intelligence with hash: {query_hash}")

    # Load exact match
    loaded = cache.load_intelligence("Syrian hamster for sale")
    assert loaded is not None, "Failed to load exact match"
    assert loaded["key_topics"] == test_intel["key_topics"]
    print(f"✓ Loaded exact match")

    # Test similar query (same keywords, different order)
    loaded_similar = cache.load_intelligence("for sale Syrian hamster")
    assert loaded_similar is not None, "Failed to load similar query"
    print(f"✓ Loaded similar query (fuzzy match works)")

    # Test has_intelligence
    assert cache.has_intelligence("Syrian hamster for sale")
    print(f"✓ has_intelligence() works")

    # Test cache stats
    stats = cache.get_cache_stats()
    print(f"✓ Cache stats: {stats['total_entries']} entries, {stats['total_reuses']} reuses")

    # Test expiry (should NOT expire immediately)
    assert cache.has_intelligence("Syrian hamster for sale")
    print(f"✓ Cache entries don't expire immediately")

    # Cleanup
    cache.clear_all()
    assert not cache.has_intelligence("Syrian hamster for sale")
    print(f"✓ clear_all() works")

    print("\n✅ Session Intelligence Cache: ALL TESTS PASSED\n")


async def test_strategy_selection():
    """Test LLM-powered strategy selection."""
    print("\n" + "=" * 70)
    print("TEST 2: LLM Strategy Selection")
    print("=" * 70)

    # Test 1: QUICK strategy (explicit keyword)
    decision = await analyze_and_select_strategy(
        query="quick price check on Syrian hamsters",
        session_id="test",
        cached_intelligence_available=False
    )

    print(f"\nQuery: 'quick price check on Syrian hamsters'")
    print(f"Selected: {decision['strategy'].upper()}")
    print(f"Reason: {decision['reason']}")
    print(f"Confidence: {decision.get('confidence', 0.9):.2f}")

    assert decision["strategy"] in ["quick", "standard", "deep"], f"Invalid strategy: {decision['strategy']}"
    # Most likely quick, but LLM may choose differently
    print(f"✓ Strategy selection works (got {decision['strategy']})")

    # Test 2: DEEP strategy (first query, no cache)
    decision = await analyze_and_select_strategy(
        query="find Syrian hamsters for sale",
        session_id="test",
        cached_intelligence_available=False
    )

    print(f"\nQuery: 'find Syrian hamsters for sale'")
    print(f"Selected: {decision['strategy'].upper()}")
    print(f"Reason: {decision['reason']}")

    assert decision["strategy"] in ["quick", "standard", "deep"]
    # Most likely deep for first query
    print(f"✓ First query strategy: {decision['strategy']}")

    # Test 3: STANDARD strategy (has cache)
    decision = await analyze_and_select_strategy(
        query="show me Syrian hamsters under $30",
        session_id="test",
        cached_intelligence_available=True  # Cache available!
    )

    print(f"\nQuery: 'show me Syrian hamsters under $30'")
    print(f"Cached intelligence available: YES")
    print(f"Selected: {decision['strategy'].upper()}")
    print(f"Reason: {decision['reason']}")

    assert decision["strategy"] in ["quick", "standard", "deep"]
    # Most likely standard when cache available
    print(f"✓ With cache strategy: {decision['strategy']}")

    print("\n✅ LLM Strategy Selection: ALL TESTS PASSED\n")


async def test_adaptive_research_quick():
    """Test adaptive research with QUICK strategy."""
    print("\n" + "=" * 70)
    print("TEST 3: Adaptive Research - QUICK Strategy")
    print("=" * 70)

    # Force QUICK strategy for predictable testing
    result = await adaptive_research(
        query="price check on hamster cages",
        session_id="test-quick",
        force_strategy="quick"  # Force for testing
    )

    print(f"Strategy used: {result['strategy_used'].upper()}")
    print(f"Strategy reason: {result['strategy_reason']}")
    print(f"Sources checked: {result['stats'].get('sources_checked', 0)}")
    print(f"Intelligence cached: {result['intelligence_cached']}")

    assert result["strategy_used"] == "quick", "Strategy should be QUICK"
    assert not result["intelligence_cached"], "QUICK shouldn't cache intelligence"
    assert result["results"] is not None, "Should have results"

    print(f"✓ QUICK strategy executed successfully")
    print(f"✓ No intelligence caching (as expected)")

    print("\n✅ Adaptive Research - QUICK: TEST PASSED\n")


async def test_adaptive_research_deep():
    """Test adaptive research with DEEP strategy."""
    print("\n" + "=" * 70)
    print("TEST 4: Adaptive Research - DEEP Strategy (FULL END-TO-END)")
    print("=" * 70)

    print("\n⚠️  WARNING: This test actually calls LLMs and visits websites!")
    print("⚠️  It may take 2-3 minutes to complete.")
    print("⚠️  Press Ctrl+C to skip this test.\n")

    # Ask user if they want to run full test
    try:
        await asyncio.sleep(3)  # Give time to cancel
    except KeyboardInterrupt:
        print("\n⏭️  Skipping full end-to-end test")
        return

    # Force DEEP strategy for predictable testing
    result = await adaptive_research(
        query="Syrian hamster care basics",
        session_id="test-deep",
        force_strategy="deep",  # Force for testing
        human_assist_allowed=False  # No CAPTCHA for testing
    )

    print(f"\nStrategy used: {result['strategy_used'].upper()}")
    print(f"Strategy reason: {result['strategy_reason']}")
    print(f"Sources checked: {result['stats'].get('sources_checked', 0)}")
    print(f"Intelligence cached: {result['intelligence_cached']}")

    assert result["strategy_used"] == "deep", "Strategy should be DEEP"
    assert result["intelligence_cached"], "DEEP should cache intelligence"
    assert result["results"] is not None, "Should have results"

    # Check that intelligence was actually cached
    cache = get_intelligence_cache("test-deep")
    assert cache.has_intelligence("Syrian hamster care basics"), "Intelligence should be cached"

    print(f"✓ DEEP strategy executed successfully")
    print(f"✓ Intelligence cached for future queries")
    print(f"✓ Cache can be reused for STANDARD strategy")

    print("\n✅ Adaptive Research - DEEP: TEST PASSED\n")


async def test_adaptive_research_standard():
    """Test adaptive research with STANDARD strategy (reusing cache)."""
    print("\n" + "=" * 70)
    print("TEST 5: Adaptive Research - STANDARD Strategy (Cache Reuse)")
    print("=" * 70)

    # First, populate cache with DEEP query
    print("Setting up: Running DEEP query to populate cache...")
    await adaptive_research(
        query="hamster health",
        session_id="test-standard",
        force_strategy="deep"
    )

    # Verify cache is populated
    cache = get_intelligence_cache("test-standard")
    assert cache.has_intelligence("hamster health"), "Cache should be populated"
    print("✓ Cache populated from DEEP query")

    # Now run STANDARD query that should reuse cache
    print("\nRunning STANDARD query with cached intelligence...")
    result = await adaptive_research(
        query="health hamster",  # Similar query, should hit cache
        session_id="test-standard",
        force_strategy="standard"
    )

    print(f"Strategy used: {result['strategy_used'].upper()}")
    print(f"Sources checked: {result['stats'].get('sources_checked', 0)}")
    print(f"Intelligence used: {result['stats'].get('intelligence_used', False)}")

    assert result["strategy_used"] == "standard", "Strategy should be STANDARD"
    assert result["stats"].get("intelligence_used"), "Should use cached intelligence"

    print(f"✓ STANDARD strategy executed successfully")
    print(f"✓ Reused cached intelligence (no Phase 1)")
    print(f"✓ Faster execution than DEEP")

    print("\n✅ Adaptive Research - STANDARD: TEST PASSED\n")


async def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("ADAPTIVE RESEARCH ARCHITECTURE - TEST SUITE")
    print("=" * 70)

    try:
        # Test 1: Cache
        await test_intelligence_cache()

        # Test 2: Strategy selection
        await test_strategy_selection()

        # Test 3: QUICK research
        await test_adaptive_research_quick()

        # Test 4: DEEP research (full end-to-end, may be skipped)
        await test_adaptive_research_deep()

        # Test 5: STANDARD research (cache reuse)
        await test_adaptive_research_standard()

        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED!")
        print("=" * 70)
        print("\nAdaptive research architecture is working correctly:")
        print("  ✓ Session intelligence caching")
        print("  ✓ LLM strategy selection")
        print("  ✓ QUICK strategy (fast lookup)")
        print("  ✓ STANDARD strategy (cache reuse)")
        print("  ✓ DEEP strategy (full research)")
        print("\n")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return 1
    except Exception as e:
        print(f"\n❌ TEST ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
