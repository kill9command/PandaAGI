#!/usr/bin/env python3
"""
Test script to verify search rate limiting is working.

This will:
1. Make multiple search requests
2. Monitor timing between requests
3. Check for rate limit errors
4. Verify SERP cache is working
"""
import asyncio
import time
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.services.orchestrator import human_search_engine
from apps.services.orchestrator.search_rate_limiter import get_search_rate_limiter
from apps.services.orchestrator.serp_cache import get_serp_cache

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


async def test_rate_limiting():
    """Test that rate limiting prevents burst traffic."""

    print("\n" + "="*80)
    print("TEST 1: Rate Limiting Between Searches")
    print("="*80)

    queries = [
        "best hamster bedding reddit",
        "hamster care guide",
        "Syrian hamster for sale"
    ]

    start_time = time.time()
    search_times = []

    for i, query in enumerate(queries):
        query_start = time.time()

        print(f"\n[{i+1}/{len(queries)}] Searching: {query}")
        results = await human_search_engine.search(query, k=5, session_id="test_rate_limit")

        query_end = time.time()
        elapsed = query_end - query_start
        search_times.append(elapsed)

        print(f"  ✓ Got {len(results)} results in {elapsed:.2f}s")

        if i > 0:
            time_since_last = query_start - search_times[i-1]
            print(f"  ⏱ Time since last search: {time_since_last:.2f}s")

    total_time = time.time() - start_time

    print(f"\n📊 Results:")
    print(f"  Total time: {total_time:.2f}s")
    print(f"  Average search time: {sum(search_times)/len(search_times):.2f}s")

    # Check rate limiter stats
    rate_limiter = get_search_rate_limiter()
    print(f"\n🚦 Rate Limiter State:")
    print(f"  Consecutive blocks: {rate_limiter._consecutive_blocks}")
    print(f"  Current backoff: {rate_limiter._current_backoff:.1f}s")

    print("\n" + "="*80)
    print("TEST 2: SERP Cache (Repeat Searches)")
    print("="*80)

    # Repeat same searches - should hit cache
    cache_start = time.time()
    for i, query in enumerate(queries):
        query_start = time.time()

        print(f"\n[{i+1}/{len(queries)}] Re-searching (should hit cache): {query}")
        results = await human_search_engine.search(query, k=5, session_id="test_rate_limit")

        query_end = time.time()
        elapsed = query_end - query_start

        print(f"  ✓ Got {len(results)} results in {elapsed:.2f}s")
        if elapsed < 0.1:
            print(f"  🎯 CACHE HIT! (< 0.1s)")

    cache_total = time.time() - cache_start
    print(f"\n📊 Cache Results:")
    print(f"  Total time: {cache_total:.2f}s (vs {total_time:.2f}s original)")
    print(f"  Speedup: {total_time/cache_total:.1f}x faster")

    # Check cache stats
    serp_cache = get_serp_cache()
    stats = serp_cache.get_stats()
    print(f"\n💾 SERP Cache Stats:")
    print(f"  Entries: {stats['entries']}")
    print(f"  Hits: {stats['hits']}")
    print(f"  Misses: {stats['misses']}")
    print(f"  Hit rate: {stats['hit_rate']*100:.1f}%")

    print("\n✅ Test complete!")


if __name__ == "__main__":
    asyncio.run(test_rate_limiting())
