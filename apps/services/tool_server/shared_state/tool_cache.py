"""
Tool Output Cache (Layer 3)

Caches raw tool outputs (SerpApi, Playwright, doc.search, etc.)
WITHOUT user context. Shared across all users.

Design:
- Sharing model: Query-scoped (by tool + normalized args)
- User attribution: None (raw tool outputs are universal)
- Privacy: No user-specific data stored
- Example: User A's SerpApi call → User B reuses cached results

Purpose: Reduce API costs and latency for repeated queries.
"""
import json
import logging
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import os

from apps.services.tool_server.shared_state.cache_config import (
    TOOL_CACHE_DIR,
    TOOL_CACHE_MAX_SIZE_GB,
    get_tool_ttl
)

logger = logging.getLogger(__name__)


class ToolCache:
    """
    Layer 3: Shared tool output cache (cross-user reuse)

    All users share the same tool cache. If User A calls SerpApi
    for "Syrian hamsters", User B's identical query hits cache.
    """

    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize tool cache storage.

        DESIGN DECISION: Tool cache is SHARED across all users.
        - Raw API results are universal (SerpApi, Playwright, etc.)
        - No user context in cache keys (only tool + args)
        - Privacy-safe: Only generic query results cached
        """
        self.storage_path = storage_path or TOOL_CACHE_DIR
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Index: tool_name -> list of cache entry filenames
        self.index = {}
        self._load_index()

        logger.info(f"[ToolCache] Initialized at {self.storage_path}")

    def _load_index(self):
        """Load index of cached tools"""
        try:
            index_path = self.storage_path / "index.json"
            if index_path.exists():
                with open(index_path, 'r') as f:
                    self.index = json.load(f)
                logger.info(f"[ToolCache] Loaded index with {len(self.index)} tool types")
        except Exception as e:
            logger.error(f"[ToolCache] Failed to load index: {e}")
            self.index = {}

    def _save_index(self):
        """Save index to disk"""
        try:
            index_path = self.storage_path / "index.json"
            with open(index_path, 'w') as f:
                json.dump(self.index, f, indent=2)
        except Exception as e:
            logger.error(f"[ToolCache] Failed to save index: {e}")

    async def get(self, tool_name: str, args: dict) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached tool result with semantic fallback.

        STRATEGY:
        1. Try exact match (MD5 hash of args)
        2. If miss/expired, try semantic search (embedding similarity > 0.85)

        Args:
            tool_name: Name of tool (e.g., "research.orchestrate")
            args: Tool arguments

        Returns:
            Cached result dict with:
                - result: Tool output
                - age_hours: Hours since cached
                - api_cost: Original API cost
                - execution_time_ms: Original execution time
            None if cache miss or expired
        """
        try:
            # PHASE 1: Try exact match
            cache_key = self._generate_cache_key(tool_name, args)
            cache_file = self.storage_path / f"{cache_key}.json"

            if cache_file.exists():
                with open(cache_file, 'r') as f:
                    entry = json.load(f)

                # Check expiration
                created_at = datetime.fromisoformat(entry["created_at"])
                age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
                ttl_hours = entry.get("ttl_hours", 24)

                if age_hours <= ttl_hours:
                    # Check version compatibility
                    cache_version = entry.get("cache_version", "v1")
                    if cache_version == "v1":
                        logger.info(f"[ToolCache-HIT-EXACT] {tool_name} (age={age_hours:.1f}h, saved=${entry.get('api_cost', 0):.3f})")
                        return {
                            "result": entry["result"],
                            "age_hours": age_hours,
                            "api_cost": entry.get("api_cost", 0),
                            "execution_time_ms": entry.get("execution_time_ms", 0),
                            "created_at": entry["created_at"]
                        }
                else:
                    logger.debug(f"[ToolCache-EXPIRED] {tool_name} (age={age_hours:.1f}h > ttl={ttl_hours}h), trying semantic search...")

            # PHASE 2: Semantic search fallback (for commerce/purchasing tools only)
            if tool_name in ["commerce.search_offers", "purchasing.lookup", "research.orchestrate"]:
                semantic_result = await self._semantic_search(tool_name, args)
                if semantic_result:
                    return semantic_result

            logger.debug(f"[ToolCache-MISS] {tool_name} (no exact or semantic match)")
            return None

        except Exception as e:
            logger.error(f"[ToolCache] Failed to retrieve cache for {tool_name}: {e}")
            return None

    async def set(
        self,
        tool_name: str,
        args: dict,
        result: Any,
        api_cost: float = 0.0,
        execution_time_ms: int = 0,
        ttl_hours: Optional[int] = None,
        manifest_ref: Optional[Dict[str, str]] = None  # v4.0: turn_id, trace_id
    ) -> bool:
        """
        Store tool result in shared cache.

        Args:
            tool_name: Name of tool
            args: Tool arguments
            result: Tool output to cache
            api_cost: API cost of this call
            execution_time_ms: Execution time
            ttl_hours: TTL override (None = use default from config)

        Returns:
            True if cached successfully
        """
        try:
            # Get TTL
            if ttl_hours is None:
                ttl_hours = get_tool_ttl(tool_name)

            # Don't cache if TTL is 0
            if ttl_hours == 0:
                logger.debug(f"[ToolCache] Not caching {tool_name} (TTL=0)")
                return False

            # Generate cache key
            cache_key = self._generate_cache_key(tool_name, args)
            cache_file = self.storage_path / f"{cache_key}.json"

            # Create cache entry
            entry = {
                "tool_name": tool_name,
                "args": self._normalize_args(tool_name, args),
                "args_hash": cache_key,
                "cache_version": "v1",
                "result": result,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ttl_hours": ttl_hours,
                "api_cost": api_cost,
                "execution_time_ms": execution_time_ms,
                "user_attribution": None,  # Shared cache
                "sharing": "cross-user",
                "manifest_ref": manifest_ref or {}  # v4.0: turn manifest reference
            }

            # Save to disk
            with open(cache_file, 'w') as f:
                json.dump(entry, f, indent=2)

            # Update index
            if tool_name not in self.index:
                self.index[tool_name] = []
            if cache_key not in self.index[tool_name]:
                self.index[tool_name].append(cache_key)
            self._save_index()

            logger.info(f"[ToolCache-STORE] {tool_name} (ttl={ttl_hours}h, cost=${api_cost:.3f})")
            return True

        except Exception as e:
            logger.error(f"[ToolCache] Failed to store cache for {tool_name}: {e}")
            return False

    def _normalize_args(self, tool_name: str, args: dict) -> dict:
        """
        Normalize arguments for consistent cache keys.

        - Sort keys alphabetically
        - Remove None values
        - Convert lists to sorted tuples (order-independent)
        """
        normalized = {}
        for key in sorted(args.keys()):
            value = args[key]
            if value is None:
                continue
            if isinstance(value, list):
                normalized[key] = sorted([str(v) for v in value])
            else:
                normalized[key] = value
        return normalized

    def _generate_cache_key(self, tool_name: str, args: dict) -> str:
        """Generate deterministic cache key from tool + args"""
        normalized = self._normalize_args(tool_name, args)
        key_str = f"{tool_name}:{json.dumps(normalized, sort_keys=True)}"
        return hashlib.md5(key_str.encode()).hexdigest()[:16]

    async def _semantic_search(self, tool_name: str, args: dict) -> Optional[Dict[str, Any]]:
        """
        Semantic search for similar cached queries using embeddings.

        Args:
            tool_name: Tool to search cache for
            args: Tool arguments (must contain 'query' key)

        Returns:
            Cached result if similarity > 0.85, else None
        """
        try:
            # Extract query from args
            query = args.get("query", "")
            if not query:
                return None

            # Get embedding service (lazy import to avoid circular deps)
            try:
                from apps.services.tool_server.shared_state.embedding_service import EMBEDDING_SERVICE
            except ImportError:
                logger.warning("[ToolCache-Semantic] Embedding service not available, skipping semantic search")
                return None

            # Get all cache IDs for this tool
            cache_ids = self.index.get(tool_name, [])
            if not cache_ids:
                return None

            logger.debug(f"[ToolCache-Semantic] Searching {len(cache_ids)} {tool_name} cache entries for query: {query[:50]}...")

            # Compute embedding for current query
            query_embedding = EMBEDDING_SERVICE.embed(query)
            if query_embedding is None:
                return None

            # Search all cached entries
            best_match = None
            best_similarity = 0.0
            SIMILARITY_THRESHOLD = 0.85

            for cache_id in cache_ids:
                cache_file = self.storage_path / f"{cache_id}.json"
                if not cache_file.exists():
                    continue

                try:
                    with open(cache_file, 'r') as f:
                        entry = json.load(f)

                    # Check expiration first
                    created_at = datetime.fromisoformat(entry["created_at"])
                    age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
                    ttl_hours = entry.get("ttl_hours", 24)

                    if age_hours > ttl_hours:
                        continue  # Skip expired

                    # Extract cached query
                    cached_query = entry.get("args", {}).get("query", "")
                    if not cached_query:
                        continue

                    # Compute embedding for cached query
                    cached_embedding = EMBEDDING_SERVICE.embed(cached_query)
                    if cached_embedding is None:
                        continue

                    # Calculate cosine similarity
                    import numpy as np
                    similarity = np.dot(query_embedding, cached_embedding) / (
                        np.linalg.norm(query_embedding) * np.linalg.norm(cached_embedding)
                    )

                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = (cache_id, entry, cached_query)

                except Exception as e:
                    logger.debug(f"[ToolCache-Semantic] Failed to process {cache_id}: {e}")
                    continue

            # Return best match if above threshold
            if best_match and best_similarity >= SIMILARITY_THRESHOLD:
                cache_id, entry, cached_query = best_match
                age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(entry["created_at"])).total_seconds() / 3600

                logger.info(
                    f"[ToolCache-HIT-SEMANTIC] {tool_name} (similarity={best_similarity:.3f}, "
                    f"age={age_hours:.1f}h, saved=${entry.get('api_cost', 0):.3f})\n"
                    f"  Query: {query[:60]}...\n"
                    f"  Matched: {cached_query[:60]}..."
                )

                return {
                    "result": entry["result"],
                    "age_hours": age_hours,
                    "api_cost": entry.get("api_cost", 0),
                    "execution_time_ms": entry.get("execution_time_ms", 0),
                    "created_at": entry["created_at"],
                    "semantic_match": True,
                    "similarity": best_similarity
                }

            logger.debug(f"[ToolCache-Semantic] No match above threshold (best={best_similarity:.3f})")
            return None

        except Exception as e:
            logger.error(f"[ToolCache-Semantic] Failed: {e}")
            return None


    async def cleanup_expired(self) -> int:
        """
        Background task: Remove expired cache entries.

        Returns:
            Number of entries deleted
        """
        deleted = 0
        try:
            for cache_file in self.storage_path.glob("*.json"):
                if cache_file.name == "index.json":
                    continue

                try:
                    with open(cache_file, 'r') as f:
                        entry = json.load(f)

                    created_at = datetime.fromisoformat(entry["created_at"])
                    age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
                    ttl_hours = entry.get("ttl_hours", 24)

                    if age_hours > ttl_hours:
                        cache_file.unlink()
                        deleted += 1
                        logger.debug(f"[ToolCache-CLEANUP] Deleted {cache_file.name}")

                except Exception as e:
                    logger.warning(f"[ToolCache-CLEANUP] Failed to process {cache_file}: {e}")

            if deleted > 0:
                logger.info(f"[ToolCache-CLEANUP] Deleted {deleted} expired entries")

                # Rebuild index
                self.index = {}
                self._load_index()

        except Exception as e:
            logger.error(f"[ToolCache-CLEANUP] Failed: {e}")

        return deleted

    def get_stats(self) -> dict:
        """Get cache statistics"""
        total_entries = 0
        total_size_bytes = 0

        for cache_file in self.storage_path.glob("*.json"):
            if cache_file.name == "index.json":
                continue
            total_entries += 1
            total_size_bytes += cache_file.stat().st_size

        return {
            "total_entries": total_entries,
            "total_size_mb": total_size_bytes / (1024 * 1024),
            "total_size_gb": total_size_bytes / (1024 * 1024 * 1024),
            "max_size_gb": TOOL_CACHE_MAX_SIZE_GB,
            "tool_types": len(self.index),
            "storage_path": str(self.storage_path)
        }


# Global singleton
TOOL_CACHE = ToolCache()
