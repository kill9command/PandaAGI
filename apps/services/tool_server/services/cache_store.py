"""In-memory cache store with TTL for PandaAI Orchestrator.

Architecture Reference:
    architecture/DOCUMENT-IO-SYSTEM/MEMORY_ARCHITECTURE.md
    architecture/mcp-tool-patterns/internet-research-mcp/INTERNET_RESEARCH_ARCHITECTURE.md

Key Design:
    - In-memory cache with configurable TTL
    - Default TTL: 1 hour (3600 seconds)
    - Used for research results caching to avoid redundant lookups
    - Thread-safe using asyncio locks

Cache Categories:
    - research: Research results indexed by topic
    - query: Query analysis results
    - extraction: Page extraction results
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with metadata."""

    topic: str
    data: Any
    created_at: datetime
    expires_at: datetime
    hit_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return datetime.now() > self.expires_at

    @property
    def ttl_remaining(self) -> float:
        """Get remaining TTL in seconds."""
        remaining = (self.expires_at - datetime.now()).total_seconds()
        return max(0.0, remaining)

    @property
    def age_seconds(self) -> float:
        """Get age of entry in seconds."""
        return (datetime.now() - self.created_at).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "topic": self.topic,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "hit_count": self.hit_count,
            "is_expired": self.is_expired,
            "ttl_remaining": self.ttl_remaining,
            "age_seconds": self.age_seconds,
            "metadata": self.metadata,
        }


class CacheStore:
    """In-memory cache with TTL support.

    Provides a simple key-value cache with automatic expiration.
    Used primarily for caching research results to avoid redundant
    lookups within a session.

    Example usage:
        cache = CacheStore()

        # Set with default TTL (1 hour)
        await cache.set("laptops_under_1000", research_data)

        # Set with custom TTL
        await cache.set("price_check", prices, ttl_seconds=300)

        # Get (returns None if expired or not found)
        data = await cache.get("laptops_under_1000")

        # Check expiration
        if await cache.is_expired("laptops_under_1000"):
            # Refresh the data

        # List all entries
        entries = await cache.list_entries()

        # Clear specific or all
        await cache.clear("laptops_under_1000")
        await cache.clear()  # Clear all
    """

    DEFAULT_TTL_SECONDS = 3600  # 1 hour

    def __init__(self, default_ttl_seconds: int = DEFAULT_TTL_SECONDS):
        """Initialize cache store.

        Args:
            default_ttl_seconds: Default TTL for entries (default: 1 hour)
        """
        self._cache: dict[str, CacheEntry] = {}
        self._default_ttl = default_ttl_seconds
        self._lock = asyncio.Lock()

    async def set(
        self,
        topic: str,
        data: Any,
        ttl_seconds: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Store data in cache.

        Args:
            topic: Cache key/topic
            data: Data to store (any JSON-serializable type)
            ttl_seconds: Time to live in seconds (default: 1 hour)
            metadata: Optional metadata dict
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        now = datetime.now()

        entry = CacheEntry(
            topic=topic,
            data=data,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
            hit_count=0,
            metadata=metadata or {},
        )

        async with self._lock:
            self._cache[topic] = entry

        logger.debug(f"Cached '{topic}' with TTL={ttl}s")

    async def get(self, topic: str) -> Optional[Any]:
        """Get data from cache.

        Args:
            topic: Cache key/topic

        Returns:
            Cached data or None if not found/expired
        """
        async with self._lock:
            entry = self._cache.get(topic)

            if entry is None:
                return None

            if entry.is_expired:
                # Remove expired entry
                del self._cache[topic]
                logger.debug(f"Cache miss (expired): '{topic}'")
                return None

            # Increment hit count
            entry.hit_count += 1
            logger.debug(f"Cache hit: '{topic}' (hits={entry.hit_count})")
            return entry.data

    async def get_entry(self, topic: str) -> Optional[CacheEntry]:
        """Get full cache entry including metadata.

        Args:
            topic: Cache key/topic

        Returns:
            CacheEntry or None if not found/expired
        """
        async with self._lock:
            entry = self._cache.get(topic)

            if entry is None:
                return None

            if entry.is_expired:
                del self._cache[topic]
                return None

            entry.hit_count += 1
            return entry

    async def is_expired(self, topic: str) -> bool:
        """Check if a cache entry is expired.

        Args:
            topic: Cache key/topic

        Returns:
            True if expired or not found, False if valid
        """
        async with self._lock:
            entry = self._cache.get(topic)

            if entry is None:
                return True

            return entry.is_expired

    async def exists(self, topic: str) -> bool:
        """Check if a valid (non-expired) entry exists.

        Args:
            topic: Cache key/topic

        Returns:
            True if entry exists and is not expired
        """
        async with self._lock:
            entry = self._cache.get(topic)
            return entry is not None and not entry.is_expired

    async def list_entries(
        self,
        include_expired: bool = False,
    ) -> list[CacheEntry]:
        """List all cache entries.

        Args:
            include_expired: Whether to include expired entries

        Returns:
            List of CacheEntry objects
        """
        async with self._lock:
            entries = []
            expired_keys = []

            for key, entry in self._cache.items():
                if entry.is_expired:
                    if include_expired:
                        entries.append(entry)
                    else:
                        expired_keys.append(key)
                else:
                    entries.append(entry)

            # Clean up expired entries
            for key in expired_keys:
                del self._cache[key]

            return entries

    async def clear(self, topic: Optional[str] = None) -> int:
        """Clear cache entries.

        Args:
            topic: Specific topic to clear, or None to clear all

        Returns:
            Number of entries cleared
        """
        async with self._lock:
            if topic is not None:
                if topic in self._cache:
                    del self._cache[topic]
                    logger.debug(f"Cleared cache entry: '{topic}'")
                    return 1
                return 0
            else:
                count = len(self._cache)
                self._cache.clear()
                logger.debug(f"Cleared all cache entries ({count})")
                return count

    async def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Returns:
            Number of entries removed
        """
        async with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired
            ]

            for key in expired_keys:
                del self._cache[key]

            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

            return len(expired_keys)

    async def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        async with self._lock:
            total = len(self._cache)
            expired = sum(1 for e in self._cache.values() if e.is_expired)
            total_hits = sum(e.hit_count for e in self._cache.values())

            return {
                "total_entries": total,
                "active_entries": total - expired,
                "expired_entries": expired,
                "total_hits": total_hits,
                "default_ttl_seconds": self._default_ttl,
            }

    async def extend_ttl(
        self,
        topic: str,
        additional_seconds: int,
    ) -> bool:
        """Extend TTL for an existing entry.

        Args:
            topic: Cache key/topic
            additional_seconds: Additional seconds to add to TTL

        Returns:
            True if extended, False if not found
        """
        async with self._lock:
            entry = self._cache.get(topic)

            if entry is None or entry.is_expired:
                return False

            entry.expires_at += timedelta(seconds=additional_seconds)
            logger.debug(f"Extended TTL for '{topic}' by {additional_seconds}s")
            return True

    async def update(
        self,
        topic: str,
        data: Any,
        preserve_ttl: bool = True,
    ) -> bool:
        """Update data for an existing entry.

        Args:
            topic: Cache key/topic
            data: New data to store
            preserve_ttl: Keep existing TTL (True) or reset to default (False)

        Returns:
            True if updated, False if not found
        """
        async with self._lock:
            entry = self._cache.get(topic)

            if entry is None or entry.is_expired:
                return False

            entry.data = data

            if not preserve_ttl:
                entry.expires_at = datetime.now() + timedelta(seconds=self._default_ttl)

            logger.debug(f"Updated cache entry: '{topic}'")
            return True

    def __len__(self) -> int:
        """Get number of entries (including expired)."""
        return len(self._cache)

    async def get_or_set(
        self,
        topic: str,
        factory: callable,
        ttl_seconds: Optional[int] = None,
    ) -> Any:
        """Get from cache or set using factory function.

        Args:
            topic: Cache key/topic
            factory: Async callable to generate data if not cached
            ttl_seconds: TTL for new entries

        Returns:
            Cached or newly generated data
        """
        data = await self.get(topic)
        if data is not None:
            return data

        # Generate new data
        if asyncio.iscoroutinefunction(factory):
            data = await factory()
        else:
            data = factory()

        await self.set(topic, data, ttl_seconds=ttl_seconds)
        return data
