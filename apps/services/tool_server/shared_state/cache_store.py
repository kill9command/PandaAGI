"""
orchestrator/shared_state/cache_store.py

Unified storage interface for all cache layers.
Handles disk I/O, TTL management, serialization, and eviction.
"""
import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable


logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Represents a single cache entry with metadata."""
    key: str
    value: Any
    cache_type: str
    created_at: float  # Unix timestamp
    expires_at: float  # Unix timestamp
    metadata: Dict[str, Any]
    size_bytes: int = 0
    hits: int = 0
    quality: float = 0.0
    claims: List[str] = None  # Related claim IDs

    def __post_init__(self):
        if self.claims is None:
            self.claims = []

    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() > self.expires_at

    @property
    def age_seconds(self) -> float:
        """Get age of entry in seconds."""
        return time.time() - self.created_at

    @property
    def ttl_remaining(self) -> float:
        """Get remaining TTL in seconds."""
        return max(0, self.expires_at - time.time())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheEntry':
        """Create from dictionary."""
        return cls(**data)


class CacheStore(ABC):
    """
    Abstract base class for all cache storage implementations.

    Features:
    - Async I/O for all operations
    - TTL-based expiration
    - Size tracking and limits
    - Eviction policies (LRU, LFU, etc.)
    - Compression and encryption hooks
    """

    def __init__(
        self,
        cache_type: str,
        base_dir: Path,
        max_size_mb: int = 500,
        default_ttl: int = 86400
    ):
        """
        Initialize cache store.

        Args:
            cache_type: Type identifier for this cache (e.g., "response", "tool")
            base_dir: Base directory for cache storage
            max_size_mb: Maximum cache size in megabytes
            default_ttl: Default TTL in seconds
        """
        self.cache_type = cache_type
        self.base_dir = Path(base_dir)
        self.max_size_mb = max_size_mb
        self.default_ttl = default_ttl

        # Ensure directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # In-memory index for fast lookups
        self._index: Dict[str, CacheEntry] = {}
        self._index_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        """Initialize cache by loading index from disk."""
        if self._initialized:
            return

        async with self._index_lock:
            await self._load_index()
            self._initialized = True

        logger.info(f"[CacheStore] Initialized {self.cache_type} cache with {len(self._index)} entries")

    async def get(self, key: str) -> Optional[CacheEntry]:
        """
        Retrieve entry by key.

        Args:
            key: Cache key

        Returns:
            CacheEntry if found and not expired, None otherwise
        """
        if not self._initialized:
            await self.initialize()

        async with self._index_lock:
            entry = self._index.get(key)

            if entry is None:
                return None

            if entry.is_expired:
                # Remove expired entry
                await self._remove_entry(key)
                return None

            # Increment hit counter
            entry.hits += 1
            await self._update_index()

            return entry

    async def put(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        quality: float = 0.0,
        claims: Optional[List[str]] = None
    ) -> CacheEntry:
        """
        Store entry with TTL and metadata.

        Args:
            key: Cache key
            value: Value to store
            ttl: Time-to-live in seconds (None = default)
            metadata: Additional metadata
            quality: Quality score (0.0-1.0)
            claims: Related claim IDs

        Returns:
            Created CacheEntry
        """
        if not self._initialized:
            await self.initialize()

        ttl = ttl or self.default_ttl
        now = time.time()

        entry = CacheEntry(
            key=key,
            value=value,
            cache_type=self.cache_type,
            created_at=now,
            expires_at=now + ttl,
            metadata=metadata or {},
            quality=quality,
            claims=claims or []
        )

        # Serialize and calculate size
        serialized = await self._serialize(entry)
        entry.size_bytes = len(serialized)

        # Write to disk
        await self._write_entry(key, serialized)

        # Update index
        async with self._index_lock:
            self._index[key] = entry
            await self._update_index()

        # Check if eviction needed
        await self._check_eviction()

        logger.debug(f"[CacheStore] Stored {self.cache_type} entry: {key} (size={entry.size_bytes})")
        return entry

    async def invalidate(self, pattern: str = "*"):
        """
        Remove entries matching pattern.

        Args:
            pattern: Glob pattern for keys (* = all)
        """
        if not self._initialized:
            await self.initialize()

        import fnmatch

        async with self._index_lock:
            keys_to_remove = [
                key for key in self._index.keys()
                if fnmatch.fnmatch(key, pattern)
            ]

            for key in keys_to_remove:
                await self._remove_entry(key)

            await self._update_index()

        logger.info(f"[CacheStore] Invalidated {len(keys_to_remove)} {self.cache_type} entries matching {pattern}")

    async def list(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[CacheEntry]:
        """
        List entries matching filters.

        Args:
            filters: Filter criteria (e.g., {"quality__gte": 0.8})
            limit: Maximum number of results

        Returns:
            List of matching CacheEntry objects
        """
        if not self._initialized:
            await self.initialize()

        async with self._index_lock:
            entries = list(self._index.values())

        # Apply filters
        if filters:
            entries = self._apply_filters(entries, filters)

        # Remove expired
        entries = [e for e in entries if not e.is_expired]

        # Apply limit
        if limit:
            entries = entries[:limit]

        return entries

    async def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Statistics dictionary
        """
        if not self._initialized:
            await self.initialize()

        async with self._index_lock:
            entries = list(self._index.values())

        total_size = sum(e.size_bytes for e in entries)
        total_hits = sum(e.hits for e in entries)
        expired_count = sum(1 for e in entries if e.is_expired)

        return {
            "cache_type": self.cache_type,
            "entry_count": len(entries),
            "total_size_mb": total_size / (1024 * 1024),
            "max_size_mb": self.max_size_mb,
            "total_hits": total_hits,
            "expired_count": expired_count,
            "avg_quality": sum(e.quality for e in entries) / len(entries) if entries else 0.0
        }

    # Abstract methods for subclasses to implement

    @abstractmethod
    async def _serialize(self, entry: CacheEntry) -> bytes:
        """Serialize entry to bytes."""
        pass

    @abstractmethod
    async def _deserialize(self, data: bytes) -> CacheEntry:
        """Deserialize bytes to entry."""
        pass

    # Internal methods

    async def _load_index(self):
        """Load index from disk."""
        index_path = self.base_dir / "index.json"

        if not index_path.exists():
            self._index = {}
            return

        try:
            def _read_index():
                with open(index_path, 'r') as f:
                    return json.load(f)

            index_data = await asyncio.to_thread(_read_index)

            self._index = {
                key: CacheEntry.from_dict(data)
                for key, data in index_data.items()
            }
        except Exception as e:
            logger.error(f"[CacheStore] Error loading index: {e}")
            self._index = {}

    async def _update_index(self):
        """Write index to disk."""
        index_path = self.base_dir / "index.json"

        try:
            index_data = {
                key: entry.to_dict()
                for key, entry in self._index.items()
            }

            def _write_index():
                with open(index_path, 'w') as f:
                    json.dump(index_data, f, indent=2)

            await asyncio.to_thread(_write_index)
        except Exception as e:
            logger.error(f"[CacheStore] Error updating index: {e}")

    async def _write_entry(self, key: str, data: bytes):
        """Write entry data to disk."""
        entry_path = self.base_dir / f"{key}.cache"

        try:
            def _write_data():
                with open(entry_path, 'wb') as f:
                    f.write(data)

            await asyncio.to_thread(_write_data)
        except Exception as e:
            logger.error(f"[CacheStore] Error writing entry {key}: {e}")
            raise

    async def _remove_entry(self, key: str):
        """Remove entry from disk and index."""
        entry_path = self.base_dir / f"{key}.cache"

        # Remove from disk
        if entry_path.exists():
            entry_path.unlink()

        # Remove from index
        self._index.pop(key, None)

    async def _check_eviction(self):
        """Check if eviction is needed based on size limit."""
        total_size = sum(e.size_bytes for e in self._index.values())
        max_size_bytes = self.max_size_mb * 1024 * 1024

        if total_size <= max_size_bytes:
            return

        # Evict using LRU policy
        async with self._index_lock:
            # Sort by last access (hits and age)
            entries = sorted(
                self._index.values(),
                key=lambda e: (e.hits, -e.age_seconds)
            )

            # Remove oldest/least accessed until under limit
            for entry in entries:
                if total_size <= max_size_bytes:
                    break

                await self._remove_entry(entry.key)
                total_size -= entry.size_bytes
                logger.info(f"[CacheStore] Evicted {entry.key} (size={entry.size_bytes})")

            await self._update_index()

    def _apply_filters(self, entries: List[CacheEntry], filters: Dict[str, Any]) -> List[CacheEntry]:
        """Apply filter criteria to entries."""
        result = entries

        for key, value in filters.items():
            if "__" in key:
                field, operator = key.rsplit("__", 1)
            else:
                field, operator = key, "eq"

            if operator == "eq":
                result = [e for e in result if getattr(e, field, None) == value]
            elif operator == "gte":
                result = [e for e in result if getattr(e, field, 0) >= value]
            elif operator == "lte":
                result = [e for e in result if getattr(e, field, 0) <= value]
            elif operator == "gt":
                result = [e for e in result if getattr(e, field, 0) > value]
            elif operator == "lt":
                result = [e for e in result if getattr(e, field, 0) < value]

        return result


class JSONCacheStore(CacheStore):
    """Cache store using JSON serialization."""

    async def _serialize(self, entry: CacheEntry) -> bytes:
        """Serialize entry to JSON bytes."""
        data = entry.to_dict()
        json_str = json.dumps(data, indent=2)
        return json_str.encode('utf-8')

    async def _deserialize(self, data: bytes) -> CacheEntry:
        """Deserialize JSON bytes to entry."""
        json_str = data.decode('utf-8')
        entry_dict = json.loads(json_str)
        return CacheEntry.from_dict(entry_dict)
