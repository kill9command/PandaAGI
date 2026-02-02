#!/usr/bin/env python3
"""
Test Phase 1 blocker-mitigation improvements.

Tests:
1. Rate limits fail-fast (no 90s wait)
2. Engine health tracking
3. Brave Search fallback
4. Session warmup behavior
5. Multi-engine failover
"""
import asyncio
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.services.orchestrator.human_search_engine import search_with_fallback
from apps.services.orchestrator.search_engine_health import get_engine_health_tracker
from apps.services.orchestrator.search_rate_limiter import get_search_rate_limiter


async def test_search_with_improvements():
    """Test search with all Phase 1 improvements"""

    print("=" * 80)
    print("PHASE 1 BLOCKER-MITIGATION TEST")
    print("=" * 80)
    print()

    # Test query
    test_query = "python tutorial"
    test_session = f"phase1_test_{int(time.time())}"

    print(f"Test Query: {test_query}")
    print(f"Session ID: {test_session}")
    print()
    print("Expected Behavior:")
    print("  1. 15-second delays between searches (was 2s)")
    print("  2. Session warmup before each search (3-8s delay + scroll + mouse)")
    print("  3. If rate limited: Instant failover to next engine (<1s, not 90s)")
    print("  4. Try DuckDuckGo → Google → Brave in sequence")
    print()
    print("-" * 80)
    print()

    # Get health tracker and rate limiter
    health_tracker = get_engine_health_tracker()
    rate_limiter = get_search_rate_limiter()

    # Show initial health stats
    print("Initial Engine Health:")
    stats = health_tracker.get_stats()
    for engine, engine_stats in stats.items():
        print(f"  {engine}: {engine_stats}")
    print()

    # Perform search
    print(f"Starting search at {time.strftime('%H:%M:%S')}...")
    print("(Watch for session warmup logs, engine attempts, and timing)")
    print()

    start_time = time.time()

    try:
        results = await search_with_fallback(
            query=test_query,
            max_results=5,
            session_id=test_session,
            human_assist_allowed=False  # Disable human intervention for automated test
        )

        elapsed = time.time() - start_time

        print()
        print("=" * 80)
        print(f"SEARCH COMPLETED in {elapsed:.1f}s")
        print("=" * 80)
        print()

        if results:
            print(f"✅ SUCCESS: Got {len(results)} results")
            print()
            print("Sample Results:")
            for i, result in enumerate(results[:3], 1):
                print(f"  {i}. {result['title'][:70]}")
                print(f"     {result['url'][:70]}")
            print()
        else:
            print("⚠️  NO RESULTS: All engines likely rate-limited")
            print("   This is expected if testing repeatedly - engines are protecting themselves")
            print()

        # Show final health stats
        print("Final Engine Health:")
        stats = health_tracker.get_stats()
        for engine, engine_stats in stats.items():
            status = "✅ Healthy" if engine_stats['is_healthy'] else "🔴 Cooldown"
            cooldown = engine_stats['cooldown_remaining']
            success_rate = engine_stats['success_rate'] * 100

            print(f"  {engine}: {status}")
            print(f"    Requests: {engine_stats['total_requests']} "
                  f"(Success: {engine_stats['total_successes']}, "
                  f"Failed: {engine_stats['total_failures']})")
            print(f"    Success Rate: {success_rate:.1f}%")
            if cooldown > 0:
                print(f"    Cooldown: {cooldown:.0f}s remaining")
            print()

        # Key observations
        print("=" * 80)
        print("KEY OBSERVATIONS:")
        print("=" * 80)
        print()

        if elapsed < 90:
            print("✅ PASS: Total time < 90s (no long intervention waits)")
        else:
            print("❌ FAIL: Took >90s (suggests intervention timeout occurred)")

        print()
        print("What to look for in logs above:")
        print("  ✓ [SessionWarmup] messages showing 3-8s delays")
        print("  ✓ [RateLimit] messages showing 15s minimum delays")
        print("  ✓ [HumanSearch] trying multiple engines if needed")
        print("  ✓ [EngineHealth] tracking failures and cooldowns")
        print("  ✓ Fast failover on rate limits (not 90s timeout)")
        print()

        return results

    except Exception as e:
        elapsed = time.time() - start_time
        print()
        print(f"❌ ERROR after {elapsed:.1f}s: {e}")
        print()
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    print()
    print("Note: This test will actually hit search engines.")
    print("      May trigger rate limits if run repeatedly.")
    print()

    asyncio.run(test_search_with_improvements())

    print()
    print("Test complete!")
    print()
