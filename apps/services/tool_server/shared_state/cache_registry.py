"""
orchestrator/shared_state/cache_registry.py

Unified registry for tracking cache entries across all cache layers.
Provides global statistics, multi-cache lookups, and coordinated invalidation.
"""
import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from apps.services.tool_server.shared_state.cache_store import CacheStore, CacheEntry
from apps.services.tool_server.shared_state.cache_config import get_cache_config


logger = logging.getLogger(__name__)


@dataclass
class CacheLayerStats:
    """Statistics for a single cache layer."""
    cache_type: str
    entry_count: int
    total_size_mb: float
    total_hits: int
    hit_rate: float
    avg_quality: float
    expired_count: int


@dataclass
class GlobalCacheStats:
    """Global statistics across all cache layers."""
    total_entries: int
    total_size_mb: float
    total_hits: int
    layers: Dict[str, CacheLayerStats]
    cascade_hit_rate: float = 0.0


class CacheRegistry:
    """
    Unified registry for all cache layers.

    Features:
    - Register multiple cache stores
    - Global statistics and monitoring
    - Cascading lookups across layers
    - Coordinated invalidation
    - Debug endpoint support
    """

    def __init__(self):
        """Initialize empty registry."""
        self._stores: Dict[str, CacheStore] = {}
        self._cascade_order: List[str] = []
        self._lock = asyncio.Lock()

        # Statistics tracking
        self._lookup_count = 0
        self._hit_count = 0
        self._cascade_hits: Dict[str, int] = defaultdict(int)

    async def register(
        self,
        cache_type: str,
        store: CacheStore,
        cascade_priority: Optional[int] = None
    ):
        """
        Register a cache store with the registry.

        Args:
            cache_type: Type identifier (e.g., "response", "claims", "tools")
            store: CacheStore instance
            cascade_priority: Priority for cascading lookups (lower = checked first)
        """
        async with self._lock:
            self._stores[cache_type] = store

            # Update cascade order if priority specified
            if cascade_priority is not None:
                # Remove if already in list
                if cache_type in self._cascade_order:
                    self._cascade_order.remove(cache_type)

                # Insert at priority position
                self._cascade_order.insert(cascade_priority, cache_type)
            elif cache_type not in self._cascade_order:
                # Append if not in list and no priority
                self._cascade_order.append(cache_type)

        logger.info(f"[CacheRegistry] Registered {cache_type} cache (cascade order: {self._cascade_order})")

    async def unregister(self, cache_type: str):
        """
        Unregister a cache store.

        Args:
            cache_type: Type identifier
        """
        async with self._lock:
            self._stores.pop(cache_type, None)
            if cache_type in self._cascade_order:
                self._cascade_order.remove(cache_type)

        logger.info(f"[CacheRegistry] Unregistered {cache_type} cache")

    async def get(
        self,
        cache_type: str,
        key: str
    ) -> Optional[CacheEntry]:
        """
        Get entry from specific cache layer.

        Args:
            cache_type: Cache layer identifier
            key: Cache key

        Returns:
            CacheEntry if found, None otherwise
        """
        store = self._stores.get(cache_type)
        if not store:
            logger.warning(f"[CacheRegistry] Cache type {cache_type} not registered")
            return None

        self._lookup_count += 1
        entry = await store.get(key)

        if entry:
            self._hit_count += 1

        return entry

    async def get_cascade(
        self,
        key: str,
        cache_types: Optional[List[str]] = None
    ) -> Optional[tuple[CacheEntry, str]]:
        """
        Get entry using cascading lookup across layers.

        Waterfall pattern: Try each layer in cascade order until found.

        Args:
            key: Cache key
            cache_types: Specific cache types to search (None = use cascade order)

        Returns:
            Tuple of (CacheEntry, cache_type) if found, None otherwise
        """
        search_order = cache_types or self._cascade_order
        self._lookup_count += 1

        for cache_type in search_order:
            store = self._stores.get(cache_type)
            if not store:
                continue

            entry = await store.get(key)
            if entry:
                self._hit_count += 1
                self._cascade_hits[cache_type] += 1
                logger.debug(f"[CacheRegistry] Cascade hit in {cache_type} layer for key {key[:8]}")
                return (entry, cache_type)

        logger.debug(f"[CacheRegistry] Cascade miss for key {key[:8]}")
        return None

    async def put(
        self,
        cache_type: str,
        key: str,
        value: Any,
        **kwargs
    ) -> Optional[CacheEntry]:
        """
        Store entry in specific cache layer.

        Args:
            cache_type: Cache layer identifier
            key: Cache key
            value: Value to store
            **kwargs: Additional arguments for CacheStore.put()

        Returns:
            CacheEntry if stored successfully, None otherwise
        """
        store = self._stores.get(cache_type)
        if not store:
            logger.warning(f"[CacheRegistry] Cache type {cache_type} not registered")
            return None

        return await store.put(key, value, **kwargs)

    async def invalidate(
        self,
        pattern: str = "*",
        cache_types: Optional[List[str]] = None
    ):
        """
        Invalidate entries matching pattern across cache layers.

        Args:
            pattern: Glob pattern for keys (* = all)
            cache_types: Specific cache types to invalidate (None = all)
        """
        target_types = cache_types or list(self._stores.keys())

        for cache_type in target_types:
            store = self._stores.get(cache_type)
            if store:
                await store.invalidate(pattern)

        logger.info(f"[CacheRegistry] Invalidated pattern {pattern} across {len(target_types)} cache layers")

    async def get_stats(self) -> GlobalCacheStats:
        """
        Get global statistics across all cache layers.

        Returns:
            GlobalCacheStats with aggregated metrics
        """
        layer_stats = {}
        total_entries = 0
        total_size_mb = 0.0
        total_hits = 0

        for cache_type, store in self._stores.items():
            stats = await store.get_stats()

            hit_rate = (
                stats["total_hits"] / self._lookup_count
                if self._lookup_count > 0
                else 0.0
            )

            layer_stat = CacheLayerStats(
                cache_type=cache_type,
                entry_count=stats["entry_count"],
                total_size_mb=stats["total_size_mb"],
                total_hits=stats["total_hits"],
                hit_rate=hit_rate,
                avg_quality=stats["avg_quality"],
                expired_count=stats["expired_count"]
            )

            layer_stats[cache_type] = layer_stat
            total_entries += stats["entry_count"]
            total_size_mb += stats["total_size_mb"]
            total_hits += stats["total_hits"]

        # Calculate cascade hit rate
        cascade_hit_rate = (
            self._hit_count / self._lookup_count
            if self._lookup_count > 0
            else 0.0
        )

        return GlobalCacheStats(
            total_entries=total_entries,
            total_size_mb=total_size_mb,
            total_hits=total_hits,
            layers=layer_stats,
            cascade_hit_rate=cascade_hit_rate
        )

    async def get_layer_stats(self, cache_type: str) -> Optional[Dict[str, Any]]:
        """
        Get statistics for a specific cache layer.

        Args:
            cache_type: Cache layer identifier

        Returns:
            Statistics dict or None if not registered
        """
        store = self._stores.get(cache_type)
        if not store:
            return None

        return await store.get_stats()

    async def list_entries(
        self,
        cache_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[CacheEntry]:
        """
        List entries from specific cache layer.

        Args:
            cache_type: Cache layer identifier
            filters: Filter criteria
            limit: Maximum number of results

        Returns:
            List of matching CacheEntry objects
        """
        store = self._stores.get(cache_type)
        if not store:
            return []

        return await store.list(filters=filters, limit=limit)

    def get_cascade_order(self) -> List[str]:
        """
        Get current cascade lookup order.

        Returns:
            List of cache types in cascade order
        """
        return self._cascade_order.copy()

    def get_cascade_stats(self) -> Dict[str, int]:
        """
        Get cascade hit statistics per layer.

        Returns:
            Dict mapping cache_type to hit count
        """
        return dict(self._cascade_hits)

    def reset_stats(self):
        """Reset statistics counters."""
        self._lookup_count = 0
        self._hit_count = 0
        self._cascade_hits.clear()
        logger.info("[CacheRegistry] Statistics reset")


# Global registry instance
_cache_registry: Optional[CacheRegistry] = None
_registry_lock = asyncio.Lock()


async def get_cache_registry() -> CacheRegistry:
    """
    Get global cache registry instance (singleton).

    Returns:
        CacheRegistry instance
    """
    global _cache_registry

    if _cache_registry is None:
        async with _registry_lock:
            if _cache_registry is None:
                _cache_registry = CacheRegistry()
                logger.info("[CacheRegistry] Initialized global cache registry")

    return _cache_registry
