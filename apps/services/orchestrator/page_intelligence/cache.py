"""
orchestrator/page_intelligence/cache.py

Page Intelligence Cache

Caches page understanding (zones, selectors, strategies) for reuse.
Uses fingerprinting based on URL pattern + DOM structure hash.

Features:
- Async locking to prevent duplicate LLM calls on concurrent requests
- LRU eviction for memory cache to prevent unbounded growth
- Per-domain disk storage with automatic cleanup
- Fingerprint-based cache keys (URL pattern + DOM structure)
"""

import asyncio
import json
import logging
import hashlib
import os
import re
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Awaitable
from urllib.parse import urlparse, parse_qs

from apps.services.orchestrator.page_intelligence.models import PageUnderstanding

logger = logging.getLogger(__name__)


class PageIntelligenceCache:
    """
    Cache for page understanding results with async locking and LRU eviction.

    Fingerprinting strategy:
    1. Domain (amazon.com)
    2. URL pattern (path structure, key query params)
    3. DOM structure hash (repeated classes, semantic containers)

    Cache hit when fingerprint matches -> skip Phase 1-3, use cached understanding.
    """

    def __init__(
        self,
        storage_path: str = None,
        max_age_hours: int = 24,
        max_entries_per_domain: int = 50,
        max_memory_entries: int = 100
    ):
        """
        Initialize cache.

        Args:
            storage_path: Directory to store cache files
            max_age_hours: Maximum age before cache entry expires
            max_entries_per_domain: Maximum cached entries per domain on disk
            max_memory_entries: Maximum entries in memory cache (LRU eviction)
        """
        self.storage_path = Path(storage_path) if storage_path else Path("panda_system_docs/page_intelligence_cache")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.max_age = timedelta(hours=max_age_hours)
        self.max_entries_per_domain = max_entries_per_domain
        self.max_memory_entries = max_memory_entries

        # LRU memory cache using OrderedDict
        self._memory_cache: OrderedDict[str, PageUnderstanding] = OrderedDict()

        # Async locks for preventing duplicate LLM calls
        self._locks: Dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()  # Lock for creating new locks

    def _get_cache_key(self, url: str, page_context: Dict[str, Any] = None) -> str:
        """Get cache key from URL and context."""
        domain = self._get_domain(url)
        fingerprint = self._compute_fingerprint(url, page_context)
        return f"{domain}:{fingerprint}"

    async def _get_lock(self, cache_key: str) -> asyncio.Lock:
        """Get or create a lock for a cache key."""
        async with self._locks_lock:
            if cache_key not in self._locks:
                self._locks[cache_key] = asyncio.Lock()
            return self._locks[cache_key]

    def get(
        self,
        url: str,
        page_context: Dict[str, Any] = None
    ) -> Optional[PageUnderstanding]:
        """
        Get cached understanding for a URL/page (synchronous check).

        Args:
            url: Page URL
            page_context: Optional page context for fingerprint matching

        Returns:
            PageUnderstanding if cache hit, None if miss
        """
        # Skip cache if disabled via environment variable
        if os.getenv("DISABLE_CACHING", "").lower() in ("true", "1", "yes"):
            return None

        domain = self._get_domain(url)
        cache_key = self._get_cache_key(url, page_context)

        # Check memory cache first (moves to end for LRU)
        if cache_key in self._memory_cache:
            understanding = self._memory_cache[cache_key]
            if self._is_valid(understanding):
                # Move to end (most recently used)
                self._memory_cache.move_to_end(cache_key)
                logger.debug(f"[PageIntelligenceCache] Memory cache hit for {domain}")
                return understanding
            else:
                # Expired, remove from memory
                del self._memory_cache[cache_key]

        # Check disk cache
        fingerprint = self._compute_fingerprint(url, page_context)
        understanding = self._load_from_disk(domain, fingerprint)
        if understanding and self._is_valid(understanding):
            # Warm memory cache with LRU eviction
            self._memory_cache_put(cache_key, understanding)
            logger.info(f"[PageIntelligenceCache] Disk cache hit for {domain}")
            return understanding

        logger.debug(f"[PageIntelligenceCache] Cache miss for {domain}")
        return None

    async def get_or_compute(
        self,
        url: str,
        page_context: Dict[str, Any],
        compute_fn: Callable[[], Awaitable[PageUnderstanding]]
    ) -> PageUnderstanding:
        """
        Get from cache or compute with locking to prevent duplicate work.

        This is the primary method for cache access - it prevents multiple
        concurrent requests from all running the expensive LLM pipeline.

        Args:
            url: Page URL
            page_context: Page context for fingerprinting
            compute_fn: Async function to compute understanding if cache miss

        Returns:
            PageUnderstanding from cache or freshly computed
        """
        cache_key = self._get_cache_key(url, page_context)
        lock = await self._get_lock(cache_key)

        try:
            async with lock:
                # Double-check pattern: check cache again after acquiring lock
                cached = self.get(url, page_context)
                if cached:
                    logger.debug(f"[PageIntelligenceCache] Cache hit after lock acquisition")
                    return cached

                # Cache miss - run expensive computation
                logger.info(f"[PageIntelligenceCache] Computing understanding for {self._get_domain(url)}")
                understanding = await compute_fn()

                # Store result
                self.put(understanding, page_context)
                return understanding
        finally:
            # Periodically clean up stale locks to prevent memory leak
            # Only clean up if lock count exceeds threshold
            if len(self._locks) > self.max_memory_entries:
                await self._cleanup_stale_locks_async()

    def _memory_cache_put(self, cache_key: str, understanding: PageUnderstanding):
        """Put into memory cache with LRU eviction."""
        # If key exists, move to end
        if cache_key in self._memory_cache:
            self._memory_cache.move_to_end(cache_key)
            self._memory_cache[cache_key] = understanding
        else:
            # Add new entry
            self._memory_cache[cache_key] = understanding
            # Evict oldest if over limit
            while len(self._memory_cache) > self.max_memory_entries:
                oldest_key = next(iter(self._memory_cache))
                del self._memory_cache[oldest_key]
                logger.debug(f"[PageIntelligenceCache] Evicted LRU entry: {oldest_key}")

    def put(
        self,
        understanding: PageUnderstanding,
        page_context: Dict[str, Any] = None
    ):
        """
        Store understanding in cache.

        Args:
            understanding: Page understanding to cache
            page_context: Page context used for fingerprinting
        """
        # Skip cache if disabled via environment variable
        if os.getenv("DISABLE_CACHING", "").lower() in ("true", "1", "yes"):
            logger.debug("[PageIntelligenceCache] Cache save skipped (caching disabled)")
            return

        domain = understanding.domain or self._get_domain(understanding.url)
        fingerprint = self._compute_fingerprint(understanding.url, page_context)
        cache_key = f"{domain}:{fingerprint}"

        # Update understanding with fingerprint
        understanding.cache_fingerprint = fingerprint
        understanding.created_at = datetime.utcnow()

        # Store in memory with LRU
        self._memory_cache_put(cache_key, understanding)

        # Store on disk
        self._save_to_disk(domain, fingerprint, understanding)

        # Cleanup old disk entries
        self._cleanup_domain(domain)

        logger.info(f"[PageIntelligenceCache] Cached understanding for {domain}")

    def invalidate(self, url: str, page_context: Dict[str, Any] = None):
        """Invalidate cache entries for a URL."""
        domain = self._get_domain(url)
        fingerprint = self._compute_fingerprint(url, page_context)
        cache_key = f"{domain}:{fingerprint}"

        # Remove from memory
        if cache_key in self._memory_cache:
            del self._memory_cache[cache_key]

        # Remove from disk
        cache_file = self._get_cache_file(domain, fingerprint)
        if cache_file.exists():
            try:
                cache_file.unlink()
                logger.info(f"[PageIntelligenceCache] Invalidated cache for {domain}")
            except OSError as e:
                logger.error(f"[PageIntelligenceCache] Failed to delete cache file: {e}")

    def invalidate_domain(self, domain: str):
        """Invalidate all cache entries for a domain."""
        domain = domain.replace("www.", "")

        # Clear memory cache entries for domain
        keys_to_delete = [k for k in self._memory_cache if k.startswith(f"{domain}:")]
        for key in keys_to_delete:
            del self._memory_cache[key]

        # Clear disk cache
        domain_dir = self.storage_path / domain
        if domain_dir.exists():
            deleted_count = 0
            for cache_file in domain_dir.glob("*.json"):
                try:
                    cache_file.unlink()
                    deleted_count += 1
                except OSError as e:
                    logger.error(f"[PageIntelligenceCache] Failed to delete {cache_file}: {e}")
            logger.info(f"[PageIntelligenceCache] Invalidated {deleted_count} entries for {domain}")

    def _compute_fingerprint(
        self,
        url: str,
        page_context: Dict[str, Any] = None
    ) -> str:
        """
        Compute cache fingerprint for a URL/page.

        Fingerprint components:
        1. URL pattern (path structure, without specific IDs)
        2. DOM structure hash (if page_context provided)
        """
        parsed = urlparse(url)

        # Normalize path (replace IDs with placeholders)
        path = self._normalize_path(parsed.path)

        # Get relevant query params (exclude session, tracking params)
        params = parse_qs(parsed.query)
        relevant_params = self._get_relevant_params(params)

        # Build fingerprint base
        fingerprint_parts = [path, json.dumps(relevant_params, sort_keys=True)]

        # Add DOM structure hash if available
        if page_context:
            dom_hash = self._hash_dom_structure(page_context)
            fingerprint_parts.append(dom_hash)

        # Compute hash
        fingerprint_str = "|".join(fingerprint_parts)
        return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]

    def _normalize_path(self, path: str) -> str:
        """
        Normalize URL path by replacing IDs with placeholders.

        /products/12345/reviews -> /products/{id}/reviews
        """
        # Replace numeric IDs
        normalized = re.sub(r'/\d+(?=/|$)', '/{id}', path)

        # Replace UUIDs
        normalized = re.sub(
            r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            '/{uuid}',
            normalized,
            flags=re.IGNORECASE
        )

        # Replace ASINs (Amazon)
        normalized = re.sub(r'/[A-Z0-9]{10}(?=/|$)', '/{asin}', normalized)

        return normalized

    def _get_relevant_params(self, params: Dict[str, List[str]]) -> Dict[str, str]:
        """Get query params relevant for caching (exclude tracking, session)."""
        exclude_params = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'ref', 'ref_', 'tag', 'linkCode', 'linkId', 'fbclid', 'gclid',
            'session', 'sid', 'timestamp', 'ts', 'token', 'dib', 'dib_tag'
        }

        # Params that affect page structure
        relevant_params = {
            'q', 'k', 'query', 'search', 'keyword',  # Search
            'category', 'cat', 'c',  # Category
            'sort', 'order', 'sortBy',  # Sorting
            'page', 'p',  # Pagination
        }

        result = {}
        for key, values in params.items():
            if key.lower() not in exclude_params:
                if key.lower() in relevant_params:
                    result[key] = values[0] if len(values) == 1 else values

        return result

    def _hash_dom_structure(self, page_context: Dict[str, Any]) -> str:
        """Compute hash of DOM structure from page context."""
        structure_parts = []

        # Use repeated classes (indicates item types)
        repeated = page_context.get("repeatedClasses", [])
        if repeated:
            top_classes = sorted(repeated, key=lambda x: x.get("count", 0), reverse=True)[:5]
            structure_parts.append(json.dumps(top_classes, sort_keys=True))

        # Use semantic containers
        containers = page_context.get("semanticContainers", [])
        if containers:
            structure_parts.append(json.dumps(containers, sort_keys=True))

        # Use indicators
        indicators = page_context.get("indicators", {})
        if indicators:
            structure_parts.append(json.dumps(indicators, sort_keys=True))

        if not structure_parts:
            return "no_structure"

        structure_str = "|".join(structure_parts)
        return hashlib.sha256(structure_str.encode()).hexdigest()[:8]

    def _is_valid(self, understanding: PageUnderstanding) -> bool:
        """Check if cached understanding is still valid."""
        if not understanding.created_at:
            return False

        age = datetime.utcnow() - understanding.created_at
        return age < self.max_age

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        return domain

    def _get_cache_file(self, domain: str, fingerprint: str) -> Path:
        """Get cache file path for domain/fingerprint."""
        domain_dir = self.storage_path / domain
        return domain_dir / f"{fingerprint}.json"

    def _load_from_disk(
        self,
        domain: str,
        fingerprint: str
    ) -> Optional[PageUnderstanding]:
        """Load understanding from disk cache."""
        cache_file = self._get_cache_file(domain, fingerprint)

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
            return PageUnderstanding.from_dict(data)
        except json.JSONDecodeError as e:
            logger.error(f"[PageIntelligenceCache] Invalid JSON in cache file {cache_file}: {e}")
            # Remove corrupt cache file
            try:
                cache_file.unlink()
            except OSError:
                pass
            return None
        except (OSError, IOError) as e:
            logger.error(f"[PageIntelligenceCache] Error reading cache file {cache_file}: {e}")
            return None
        except Exception as e:
            logger.error(f"[PageIntelligenceCache] Unexpected error loading cache: {e}")
            return None

    def _save_to_disk(
        self,
        domain: str,
        fingerprint: str,
        understanding: PageUnderstanding
    ):
        """Save understanding to disk cache."""
        domain_dir = self.storage_path / domain
        try:
            domain_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"[PageIntelligenceCache] Failed to create cache directory: {e}")
            return

        cache_file = self._get_cache_file(domain, fingerprint)

        try:
            with open(cache_file, 'w') as f:
                json.dump(understanding.to_dict(), f, indent=2, default=str)
        except (OSError, IOError) as e:
            logger.error(f"[PageIntelligenceCache] Error saving cache file: {e}")
        except TypeError as e:
            logger.error(f"[PageIntelligenceCache] Serialization error: {e}")

    def _cleanup_domain(self, domain: str):
        """Remove old cache entries for domain if over limit."""
        domain_dir = self.storage_path / domain
        if not domain_dir.exists():
            return

        try:
            cache_files = list(domain_dir.glob("*.json"))
        except OSError as e:
            logger.error(f"[PageIntelligenceCache] Error listing cache files: {e}")
            return

        if len(cache_files) <= self.max_entries_per_domain:
            return

        # Sort by modification time, delete oldest
        # Handle race condition: file may be deleted between list and stat
        def safe_mtime(f: Path) -> float:
            try:
                return f.stat().st_mtime
            except (OSError, FileNotFoundError):
                return 0  # Treat missing files as oldest

        cache_files.sort(key=safe_mtime)
        files_to_delete = cache_files[:-self.max_entries_per_domain]

        deleted_count = 0
        for cache_file in files_to_delete:
            try:
                cache_file.unlink()
                deleted_count += 1
            except FileNotFoundError:
                # File already deleted by another process - not an error
                pass
            except OSError as e:
                logger.error(f"[PageIntelligenceCache] Error deleting {cache_file}: {e}")

        if deleted_count > 0:
            logger.info(f"[PageIntelligenceCache] Cleaned up {deleted_count} old entries for {domain}")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        stats = {
            "memory_entries": len(self._memory_cache),
            "memory_max": self.max_memory_entries,
            "active_locks": len(self._locks),
            "disk_domains": 0,
            "disk_entries": 0
        }

        if self.storage_path.exists():
            try:
                for domain_dir in self.storage_path.iterdir():
                    if domain_dir.is_dir():
                        stats["disk_domains"] += 1
                        stats["disk_entries"] += len(list(domain_dir.glob("*.json")))
            except OSError as e:
                logger.error(f"[PageIntelligenceCache] Error getting stats: {e}")

        return stats

    async def _cleanup_stale_locks_async(self):
        """
        Clean up locks that are no longer needed (internal async version).

        Called automatically when lock count exceeds threshold.
        """
        try:
            async with self._locks_lock:
                # Remove locks that aren't currently held
                keys_to_remove = [
                    key for key, lock in self._locks.items()
                    if not lock.locked()
                ]

                for key in keys_to_remove:
                    del self._locks[key]

                if keys_to_remove:
                    logger.debug(f"[PageIntelligenceCache] Cleaned up {len(keys_to_remove)} stale locks, {len(self._locks)} remaining")
        except Exception as e:
            # Don't let cleanup errors affect main operation
            logger.warning(f"[PageIntelligenceCache] Lock cleanup error: {e}")

    async def cleanup_stale_locks(self):
        """Clean up locks that are no longer needed (public API)."""
        await self._cleanup_stale_locks_async()


# Global instance with thread-safe initialization
_cache: Optional[PageIntelligenceCache] = None
_cache_lock = threading.Lock()


def get_page_intelligence_cache(
    storage_path: str = None,
    max_age_hours: int = 24,
    max_memory_entries: int = 100
) -> PageIntelligenceCache:
    """Get or create the global cache instance (thread-safe)."""
    global _cache
    if _cache is None:
        with _cache_lock:
            # Double-check pattern
            if _cache is None:
                _cache = PageIntelligenceCache(
                    storage_path=storage_path,
                    max_age_hours=max_age_hours,
                    max_memory_entries=max_memory_entries
                )
    return _cache
