"""
orchestrator/shared_state/cache_sweeper.py

Centralized cache eviction sweeper.
Applies eviction policies across all cache layers on a scheduled interval.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from apps.services.orchestrator.shared_state.cache_registry import get_cache_registry
from apps.services.orchestrator.shared_state.cache_config import get_cache_config

logger = logging.getLogger(__name__)


class CacheSweeper:
    """
    Centralized eviction sweeper for all cache layers.

    Features:
    - Scheduled eviction checks
    - TTL-based expiration
    - Size-based eviction (LRU/LFU)
    - Quality-based pruning
    - Statistics tracking
    """

    def __init__(
        self,
        check_interval: Optional[int] = None,
        enable_quality_pruning: bool = True,
        min_quality_threshold: float = 0.3
    ):
        """
        Initialize cache sweeper.

        Args:
            check_interval: Check interval in seconds (None = use config)
            enable_quality_pruning: Enable quality-based pruning
            min_quality_threshold: Minimum quality to keep entries
        """
        config = get_cache_config()
        self.check_interval = check_interval or config.eviction_check_interval_seconds
        self.enable_quality_pruning = enable_quality_pruning
        self.min_quality_threshold = min_quality_threshold

        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Statistics
        self._sweep_count = 0
        self._total_expired = 0
        self._total_evicted = 0
        self._total_pruned = 0
        self._last_sweep_time: Optional[datetime] = None

        logger.info(
            f"[CacheSweeper] Initialized with interval={self.check_interval}s, "
            f"quality_pruning={enable_quality_pruning}, "
            f"min_quality={min_quality_threshold}"
        )

    async def start(self):
        """Start the eviction sweeper."""
        if self._running:
            logger.warning("[CacheSweeper] Already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._sweep_loop())
        logger.info("[CacheSweeper] Started")

    async def stop(self):
        """Stop the eviction sweeper."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("[CacheSweeper] Stopped")

    async def sweep_now(self) -> Dict[str, Any]:
        """
        Perform immediate sweep across all caches.

        Returns:
            Sweep statistics
        """
        logger.info("[CacheSweeper] Starting manual sweep")
        return await self._perform_sweep()

    async def _sweep_loop(self):
        """Main sweep loop."""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)
                await self._perform_sweep()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[CacheSweeper] Error in sweep loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying

    async def _perform_sweep(self) -> Dict[str, Any]:
        """
        Perform sweep across all cache layers.

        Returns:
            Sweep statistics
        """
        sweep_start = datetime.now(timezone.utc)
        registry = await get_cache_registry()

        # Get global stats before sweep
        stats_before = await registry.get_stats()

        expired_count = 0
        evicted_count = 0
        pruned_count = 0
        errors = []

        # Sweep each cache layer
        for cache_type in registry._stores.keys():
            try:
                layer_stats = await self._sweep_layer(cache_type)
                expired_count += layer_stats["expired"]
                evicted_count += layer_stats["evicted"]
                pruned_count += layer_stats["pruned"]
            except Exception as e:
                logger.error(f"[CacheSweeper] Error sweeping {cache_type}: {e}")
                errors.append({"cache_type": cache_type, "error": str(e)})

        # Update global statistics
        self._sweep_count += 1
        self._total_expired += expired_count
        self._total_evicted += evicted_count
        self._total_pruned += pruned_count
        self._last_sweep_time = sweep_start

        # Get stats after sweep
        stats_after = await registry.get_stats()

        sweep_duration = (datetime.now(timezone.utc) - sweep_start).total_seconds()

        result = {
            "sweep_number": self._sweep_count,
            "timestamp": sweep_start.isoformat(),
            "duration_seconds": sweep_duration,
            "expired": expired_count,
            "evicted": evicted_count,
            "pruned": pruned_count,
            "entries_before": stats_before.total_entries,
            "entries_after": stats_after.total_entries,
            "size_before_mb": stats_before.total_size_mb,
            "size_after_mb": stats_after.total_size_mb,
            "errors": errors
        }

        logger.info(
            f"[CacheSweeper] Sweep #{self._sweep_count} complete: "
            f"expired={expired_count}, evicted={evicted_count}, pruned={pruned_count}, "
            f"duration={sweep_duration:.2f}s"
        )

        return result

    async def _sweep_layer(self, cache_type: str) -> Dict[str, int]:
        """
        Sweep a single cache layer.

        Args:
            cache_type: Cache layer identifier

        Returns:
            Layer sweep statistics
        """
        registry = await get_cache_registry()
        store = registry._stores.get(cache_type)

        if not store:
            return {"expired": 0, "evicted": 0, "pruned": 0}

        expired_count = 0
        evicted_count = 0
        pruned_count = 0

        # Get all entries
        entries = await store.list()

        # Collect expired entries
        expired_keys = []
        for entry in entries:
            if entry.is_expired:
                expired_keys.append(entry.key)

        # Remove expired entries
        for key in expired_keys:
            await store._remove_entry(key)
            expired_count += 1

        # Quality-based pruning (if enabled)
        if self.enable_quality_pruning:
            low_quality_entries = [
                e for e in entries
                if not e.is_expired and e.quality < self.min_quality_threshold
            ]

            # Prune lowest quality first
            low_quality_entries.sort(key=lambda e: e.quality)

            for entry in low_quality_entries:
                await store._remove_entry(entry.key)
                pruned_count += 1
                logger.debug(
                    f"[CacheSweeper] Pruned low-quality entry {entry.key} "
                    f"(quality={entry.quality:.2f})"
                )

        # Check if size-based eviction needed
        await store._check_eviction()

        # Count evictions (entries removed beyond expired/pruned)
        entries_after = await store.list()
        final_count = len(entries_after)
        initial_count = len(entries)
        evicted_count = max(0, initial_count - final_count - expired_count - pruned_count)

        # Update index
        await store._update_index()

        return {
            "expired": expired_count,
            "evicted": evicted_count,
            "pruned": pruned_count
        }

    def get_stats(self) -> Dict[str, Any]:
        """
        Get sweeper statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "running": self._running,
            "check_interval": self.check_interval,
            "sweep_count": self._sweep_count,
            "total_expired": self._total_expired,
            "total_evicted": self._total_evicted,
            "total_pruned": self._total_pruned,
            "last_sweep_time": self._last_sweep_time.isoformat() if self._last_sweep_time else None,
            "quality_pruning_enabled": self.enable_quality_pruning,
            "min_quality_threshold": self.min_quality_threshold
        }


# Global sweeper instance
_cache_sweeper: Optional[CacheSweeper] = None
_sweeper_lock = asyncio.Lock()


async def get_cache_sweeper() -> CacheSweeper:
    """
    Get global cache sweeper instance (singleton).

    Returns:
        CacheSweeper instance
    """
    global _cache_sweeper

    if _cache_sweeper is None:
        async with _sweeper_lock:
            if _cache_sweeper is None:
                _cache_sweeper = CacheSweeper()
                logger.info("[CacheSweeper] Initialized global sweeper")

    return _cache_sweeper


async def start_sweeper():
    """Start the global cache sweeper."""
    sweeper = await get_cache_sweeper()
    await sweeper.start()


async def stop_sweeper():
    """Stop the global cache sweeper."""
    sweeper = await get_cache_sweeper()
    await sweeper.stop()


async def sweep_now() -> Dict[str, Any]:
    """Perform immediate sweep."""
    sweeper = await get_cache_sweeper()
    return await sweeper.sweep_now()
