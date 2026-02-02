"""
Intelligence Cache Manager for Global Phase 1 Caching

Provides cross-session caching of Phase 1 intelligence findings.
Cache is shared across all users for common topics.

Cache Structure:
    panda_system_docs/intelligence_cache/
    ├── index.json              # Cache index with topics + TTLs
    └── {topic_hash}/           # Per-topic directory
        ├── intelligence.md     # Cached Phase 1 findings
        └── metadata.json       # Cache metadata

Author: Research Role Integration
Date: 2025-12-08
"""

import json
import shutil
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import logging
import threading

from libs.gateway.research_doc_writers import (
    Phase1Intelligence,
    Phase1IntelligenceWriter,
    generate_topic_hash,
    normalize_topic
)

logger = logging.getLogger(__name__)

# Default cache directory
DEFAULT_CACHE_DIR = Path("panda_system_docs/intelligence_cache")

# Default TTL: 24 hours
DEFAULT_TTL_HOURS = 24


@dataclass
class CacheEntry:
    """Metadata for a cached intelligence entry."""
    topic_normalized: str
    topic_original: str
    domain: str
    keywords: List[str]
    created_at: float  # Unix timestamp
    expires_at: float  # Unix timestamp
    hits: int
    last_hit: float  # Unix timestamp
    source_turn: int
    hash_id: str


class IntelligenceCacheManager:
    """
    Manages global Phase 1 intelligence cache.

    Features:
    - Cross-session caching (shared across all users)
    - Topic normalization for better cache hits
    - TTL-based expiration
    - Hit tracking for analytics
    - Thread-safe operations
    """

    def __init__(self, cache_dir: Path = None, ttl_hours: int = DEFAULT_TTL_HOURS):
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.ttl_hours = ttl_hours
        self.index_path = self.cache_dir / "index.json"
        self._lock = threading.Lock()

        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Load or initialize index
        self._index = self._load_index()

        logger.info(f"[IntelligenceCache] Initialized with {len(self._index.get('entries', {}))} entries")

    def _load_index(self) -> Dict[str, Any]:
        """Load cache index from disk."""
        if self.index_path.exists():
            try:
                with open(self.index_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[IntelligenceCache] Failed to load index: {e}")

        return {"entries": {}, "version": "1.0"}

    def _save_index(self):
        """Save cache index to disk."""
        with open(self.index_path, 'w') as f:
            json.dump(self._index, f, indent=2)

    def lookup(self, query: str, domain: str = "") -> Optional[Phase1Intelligence]:
        """
        Look up cached intelligence for a query.

        Args:
            query: User query
            domain: Optional domain hint

        Returns:
            Phase1Intelligence if cache hit, None otherwise
        """
        topic_normalized = normalize_topic(query, domain)
        hash_id = generate_topic_hash(topic_normalized)

        with self._lock:
            entry_data = self._index.get("entries", {}).get(hash_id)

            if not entry_data:
                logger.debug(f"[IntelligenceCache] Miss: no entry for '{topic_normalized}' (hash={hash_id})")
                return None

            # Check expiration
            if time.time() > entry_data.get("expires_at", 0):
                logger.info(f"[IntelligenceCache] Expired: '{topic_normalized}' (hash={hash_id})")
                self._remove_entry(hash_id)
                return None

            # Load intelligence from file
            intel_path = self.cache_dir / hash_id / "intelligence.md"
            if not intel_path.exists():
                logger.warning(f"[IntelligenceCache] Missing file: {intel_path}")
                self._remove_entry(hash_id)
                return None

            # Update hit statistics
            entry_data["hits"] = entry_data.get("hits", 0) + 1
            entry_data["last_hit"] = time.time()
            self._index["entries"][hash_id] = entry_data
            self._save_index()

            # Parse intelligence from markdown (simplified - return metadata)
            intel = self._load_intelligence(hash_id, entry_data)

            logger.info(
                f"[IntelligenceCache] Hit: '{topic_normalized}' "
                f"(hash={hash_id}, hits={entry_data['hits']})"
            )

            return intel

    def store(
        self,
        query: str,
        domain: str,
        intelligence: Phase1Intelligence,
        keywords: List[str] = None
    ) -> str:
        """
        Store intelligence in cache.

        Args:
            query: Original query
            domain: Domain classification
            intelligence: Phase 1 findings to cache
            keywords: Optional keywords for search

        Returns:
            Cache hash ID
        """
        topic_normalized = normalize_topic(query, domain)
        hash_id = generate_topic_hash(topic_normalized)

        with self._lock:
            # Create cache entry directory
            entry_dir = self.cache_dir / hash_id
            entry_dir.mkdir(parents=True, exist_ok=True)

            # Write intelligence document
            writer = Phase1IntelligenceWriter()
            intel_path = entry_dir / "intelligence.md"

            # Update intelligence metadata for cache
            intelligence.from_cache = False
            intelligence.cache_id = hash_id

            content = writer._render(intelligence)
            intel_path.write_text(content)

            # Create cache entry
            now = time.time()
            entry = CacheEntry(
                topic_normalized=topic_normalized,
                topic_original=query,
                domain=domain,
                keywords=keywords or self._extract_keywords(topic_normalized),
                created_at=now,
                expires_at=now + (self.ttl_hours * 3600),
                hits=0,
                last_hit=now,
                source_turn=intelligence.turn_number,
                hash_id=hash_id
            )

            # Write metadata
            metadata_path = entry_dir / "metadata.json"
            with open(metadata_path, 'w') as f:
                json.dump(asdict(entry), f, indent=2)

            # Update index
            self._index["entries"][hash_id] = asdict(entry)
            self._save_index()

            logger.info(
                f"[IntelligenceCache] Stored: '{topic_normalized}' "
                f"(hash={hash_id}, ttl={self.ttl_hours}h)"
            )

            return hash_id

    def invalidate(self, hash_id: str) -> bool:
        """
        Invalidate a cache entry.

        Args:
            hash_id: Cache hash ID

        Returns:
            True if entry was removed, False if not found
        """
        with self._lock:
            return self._remove_entry(hash_id)

    def invalidate_by_topic(self, query: str, domain: str = "") -> bool:
        """
        Invalidate cache entry by topic.

        Args:
            query: Query to invalidate
            domain: Optional domain hint

        Returns:
            True if entry was removed, False if not found
        """
        topic_normalized = normalize_topic(query, domain)
        hash_id = generate_topic_hash(topic_normalized)
        return self.invalidate(hash_id)

    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.

        Returns:
            Number of entries removed
        """
        removed = 0
        now = time.time()

        with self._lock:
            expired_ids = []
            for hash_id, entry in self._index.get("entries", {}).items():
                if now > entry.get("expires_at", 0):
                    expired_ids.append(hash_id)

            for hash_id in expired_ids:
                self._remove_entry(hash_id)
                removed += 1

        if removed > 0:
            logger.info(f"[IntelligenceCache] Cleaned up {removed} expired entries")

        return removed

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        entries = self._index.get("entries", {})
        now = time.time()

        total = len(entries)
        expired = sum(1 for e in entries.values() if now > e.get("expires_at", 0))
        total_hits = sum(e.get("hits", 0) for e in entries.values())

        # Domain breakdown
        domains = {}
        for entry in entries.values():
            domain = entry.get("domain", "unknown")
            domains[domain] = domains.get(domain, 0) + 1

        return {
            "total_entries": total,
            "active_entries": total - expired,
            "expired_entries": expired,
            "total_hits": total_hits,
            "domains": domains,
            "cache_dir": str(self.cache_dir),
            "ttl_hours": self.ttl_hours
        }

    def list_entries(self, domain: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        List cache entries.

        Args:
            domain: Optional domain filter
            limit: Max entries to return

        Returns:
            List of entry metadata
        """
        entries = []
        now = time.time()

        for hash_id, entry in self._index.get("entries", {}).items():
            if domain and entry.get("domain") != domain:
                continue

            entry_info = {
                "hash_id": hash_id,
                "topic": entry.get("topic_normalized", ""),
                "domain": entry.get("domain", "unknown"),
                "hits": entry.get("hits", 0),
                "expired": now > entry.get("expires_at", 0),
                "created_at": datetime.fromtimestamp(entry.get("created_at", 0)).isoformat(),
                "expires_at": datetime.fromtimestamp(entry.get("expires_at", 0)).isoformat(),
            }
            entries.append(entry_info)

            if len(entries) >= limit:
                break

        # Sort by hits (most popular first)
        entries.sort(key=lambda x: x["hits"], reverse=True)

        return entries

    def _remove_entry(self, hash_id: str) -> bool:
        """Remove a cache entry (internal, assumes lock held)."""
        if hash_id not in self._index.get("entries", {}):
            return False

        # Remove from index
        del self._index["entries"][hash_id]
        self._save_index()

        # Remove directory
        entry_dir = self.cache_dir / hash_id
        if entry_dir.exists():
            shutil.rmtree(entry_dir)

        logger.debug(f"[IntelligenceCache] Removed entry: {hash_id}")
        return True

    def _extract_keywords(self, topic: str) -> List[str]:
        """Extract keywords from normalized topic."""
        words = topic.split()
        # Filter very short words
        return [w for w in words if len(w) > 2]

    def _load_intelligence(self, hash_id: str, entry_data: Dict) -> Phase1Intelligence:
        """Load Phase1Intelligence from cache."""
        # Create a minimal Phase1Intelligence object with cache info
        intel = Phase1Intelligence(
            turn_number=entry_data.get("source_turn", 0),
            query=entry_data.get("topic_original", ""),
            domain=entry_data.get("domain", ""),
            from_cache=True,
            cache_id=hash_id
        )

        # Try to load full content from metadata
        metadata_path = self.cache_dir / hash_id / "metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                    # Could expand this to load full intelligence structure
            except (json.JSONDecodeError, IOError):
                pass

        return intel


# Singleton instance
_cache_instance = None
_cache_lock = threading.Lock()


def get_intelligence_cache() -> IntelligenceCacheManager:
    """Get the global intelligence cache instance."""
    global _cache_instance

    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                _cache_instance = IntelligenceCacheManager()

    return _cache_instance
