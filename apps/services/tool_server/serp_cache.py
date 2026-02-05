"""
orchestrator/serp_cache.py

Cross-turn SERP result cache to avoid redundant search engine requests.

Design:
- Caches search results by (query, engine, session_id) key
- TTL-based expiration (default 1 hour for SERP freshness)
- LRU eviction when cache grows too large
- Thread-safe for concurrent access

Created: 2025-11-18
Part of fix for research pipeline rate limiting issues.
"""
import logging
import hashlib
import json
import time
from typing import List, Dict, Any, Optional, Tuple
from collections import OrderedDict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SERPCache:
    """
    Cache for search engine results pages (SERP).

    Reduces redundant searches by caching results for a TTL period.
    """

    def __init__(
        self,
        ttl_seconds: int = 3600,      # 1 hour default
        max_entries: int = 1000,       # Max cache size
        min_results: int = 3           # Min results to cache
    ):
        """
        Args:
            ttl_seconds: Time-to-live for cached results (default 1 hour)
            max_entries: Maximum cache entries before LRU eviction
            min_results: Minimum results required to cache (skip empty/blocked)
        """
        self._cache: OrderedDict[str, Tuple[List[Dict[str, Any]], float]] = OrderedDict()
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._min_results = min_results
        self._hits = 0
        self._misses = 0

    def _make_key(self, query: str, engine: str, session_id: str) -> str:
        """
        Generate cache key from query parameters.

        Args:
            query: Search query
            engine: Search engine name (duckduckgo, google, etc.)
            session_id: Session ID

        Returns:
            Cache key hash
        """
        # Normalize query (lowercase, strip whitespace)
        normalized_query = query.lower().strip()

        # Create deterministic key
        key_data = {
            "query": normalized_query,
            "engine": engine.lower(),
            "session_id": session_id
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    def get(
        self,
        query: str,
        engine: str,
        session_id: str = "default"
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve cached search results.

        Args:
            query: Search query
            engine: Search engine name
            session_id: Session ID

        Returns:
            Cached results if found and not expired, None otherwise
        """
        key = self._make_key(query, engine, session_id)

        if key not in self._cache:
            self._misses += 1
            logger.debug(f"[SERPCache] MISS: {engine} query='{query[:40]}...'")
            return None

        results, cached_at = self._cache[key]

        # Check expiration
        age = time.time() - cached_at
        if age > self._ttl:
            # Expired, remove from cache
            del self._cache[key]
            self._misses += 1
            logger.debug(
                f"[SERPCache] EXPIRED: {engine} query='{query[:40]}...' "
                f"(age={age:.0f}s, ttl={self._ttl}s)"
            )
            return None

        # Move to end (LRU)
        self._cache.move_to_end(key)
        self._hits += 1

        logger.info(
            f"[SERPCache] HIT: {engine} query='{query[:40]}...' "
            f"({len(results)} results, age={age:.0f}s)"
        )
        return results

    def put(
        self,
        query: str,
        engine: str,
        results: List[Dict[str, Any]],
        session_id: str = "default"
    ) -> None:
        """
        Store search results in cache.

        Args:
            query: Search query
            engine: Search engine name
            results: Search results to cache
            session_id: Session ID
        """
        # Skip caching if too few results (likely blocked/empty)
        if len(results) < self._min_results:
            logger.debug(
                f"[SERPCache] SKIP: {engine} query='{query[:40]}...' "
                f"(only {len(results)} results, min={self._min_results})"
            )
            return

        key = self._make_key(query, engine, session_id)

        # Evict oldest if at capacity
        if len(self._cache) >= self._max_entries and key not in self._cache:
            evicted_key = next(iter(self._cache))
            del self._cache[evicted_key]
            logger.debug(f"[SERPCache] EVICT: {evicted_key} (LRU, at capacity)")

        self._cache[key] = (results, time.time())
        self._cache.move_to_end(key)

        logger.info(
            f"[SERPCache] STORE: {engine} query='{query[:40]}...' "
            f"({len(results)} results, cache_size={len(self._cache)})"
        )

    def invalidate(self, query: str, engine: str, session_id: str = "default") -> None:
        """
        Invalidate cached results for a query.

        Args:
            query: Search query
            engine: Search engine name
            session_id: Session ID
        """
        key = self._make_key(query, engine, session_id)
        if key in self._cache:
            del self._cache[key]
            logger.info(f"[SERPCache] INVALIDATE: {engine} query='{query[:40]}...'")

    def clear(self) -> None:
        """Clear all cached results."""
        count = len(self._cache)
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        logger.info(f"[SERPCache] CLEAR: removed {count} entries")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            {
                "entries": int,
                "hits": int,
                "misses": int,
                "hit_rate": float
            }
        """
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0

        return {
            "entries": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
            "max_entries": self._max_entries,
            "ttl_seconds": self._ttl
        }


# Global singleton instance
_global_serp_cache: Optional[SERPCache] = None


def get_serp_cache() -> SERPCache:
    """
    Get the global SERP cache instance.

    Returns:
        SERPCache singleton
    """
    global _global_serp_cache
    if _global_serp_cache is None:
        _global_serp_cache = SERPCache(
            ttl_seconds=3600,    # 1 hour
            max_entries=1000,    # 1000 queries
            min_results=3        # Must have 3+ results to cache
        )
    return _global_serp_cache
