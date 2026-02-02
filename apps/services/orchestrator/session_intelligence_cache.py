"""
orchestrator/session_intelligence_cache.py

Session-scoped intelligence caching for adaptive research.
Stores Phase 1 intelligence for reuse across queries in same session.

Created: 2025-11-15
"""
import json
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependencies
_embedding_service = None

def _get_embedding_service():
    """Lazy load embedding service to avoid startup overhead."""
    global _embedding_service
    if _embedding_service is None:
        try:
            from apps.services.orchestrator.shared_state.embedding_service import EMBEDDING_SERVICE
            _embedding_service = EMBEDDING_SERVICE
        except ImportError:
            logger.warning("[IntelCache] Embedding service not available, semantic matching disabled")
            _embedding_service = False  # Mark as unavailable
    return _embedding_service if _embedding_service else None


# Semantic similarity threshold for cache matching
# 0.7 = moderately similar (catches "hamster" -> "Syrian hamsters for sale")
# 0.8 = more strict (requires more word overlap)
SEMANTIC_SIMILARITY_THRESHOLD = 0.65

CACHE_DIR = Path("panda_system_docs/sessions")


def _parse_datetime_aware(dt_string: str) -> datetime:
    """Parse datetime string and ensure it's timezone-aware (UTC).

    Handles both naive and aware datetime strings for backward compatibility.
    """
    dt = datetime.fromisoformat(dt_string)
    if dt.tzinfo is None:
        # Naive datetime - assume UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


TTL_HOURS = 24
CACHE_VERSION = "1.1"  # Bump when intelligence format changes (breaks old caches)


class SessionIntelligenceCache:
    """
    Cache for Phase 1 intelligence results.

    Enables STANDARD strategy by reusing intelligence across queries.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.cache_path = CACHE_DIR / session_id / "intelligence_cache.json"
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

    def _hash_query(self, query: str) -> str:
        """
        Hash query for similarity matching.

        Uses sorted keywords to catch variations:
        "Syrian hamster for sale" ≈ "buy Syrian hamster online"
        """
        # Extract keywords, lowercase, sort, hash
        keywords = sorted(query.lower().split())
        keyword_string = "_".join(keywords)
        return hashlib.md5(keyword_string.encode()).hexdigest()[:12]

    def _find_semantically_similar_entry(
        self,
        query: str,
        entries: List[Dict],
        threshold: float = SEMANTIC_SIMILARITY_THRESHOLD
    ) -> Tuple[Optional[Dict], float]:
        """
        Find cached entry semantically similar to query using embeddings.

        This enables cache hits for follow-up queries like:
        - "find some for sale" matching cached "Syrian hamsters for sale online"
        - "where can I buy them" matching cached "laptop GPU purchase options"

        Args:
            query: Query to match
            entries: List of cache entries to search
            threshold: Minimum similarity score (0.0-1.0)

        Returns:
            (matching_entry, similarity_score) or (None, 0.0) if no match
        """
        embedding_service = _get_embedding_service()
        if not embedding_service or not embedding_service.is_available():
            logger.debug("[IntelCache] Semantic matching unavailable (no embedding service)")
            return None, 0.0

        if not entries:
            return None, 0.0

        try:
            # Get embedding for the query
            query_embedding = embedding_service.embed(query)
            if query_embedding is None:
                return None, 0.0

            # Find best matching entry
            best_entry = None
            best_score = 0.0

            for entry in entries:
                original_query = entry.get("original_query", "")
                if not original_query:
                    continue

                # Get embedding for cached query
                cached_embedding = embedding_service.embed(original_query)
                if cached_embedding is None:
                    continue

                # Compute similarity
                score = embedding_service.cosine_similarity(query_embedding, cached_embedding)

                if score > best_score:
                    best_score = score
                    best_entry = entry

            if best_score >= threshold:
                logger.info(
                    f"[IntelCache] Semantic match found: '{query[:40]}...' "
                    f"≈ '{best_entry['original_query'][:40]}...' "
                    f"(score: {best_score:.3f})"
                )
                return best_entry, best_score

            if best_score > 0:
                logger.debug(
                    f"[IntelCache] Best semantic match below threshold: "
                    f"score={best_score:.3f} < {threshold}"
                )

            return None, 0.0

        except Exception as e:
            logger.warning(f"[IntelCache] Semantic matching failed: {e}")
            return None, 0.0

    def save_intelligence(self, query: str, intelligence: Dict, sources: List[Dict] = None, stats: Dict = None) -> str:
        """
        Save intelligence with 24h TTL.

        Args:
            query: Original query
            intelligence: Intelligence dict from Phase 1
            sources: Optional list of sources used
            stats: Optional stats from Phase 1

        Returns:
            query_hash for this entry
        """
        query_hash = self._hash_query(query)

        # Load existing cache
        cache_data = self._load_cache()

        # Create new entry
        entry = {
            "version": CACHE_VERSION,  # For invalidation when format changes
            "query_hash": query_hash,
            "original_query": query,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=TTL_HOURS)).isoformat(),
            "ttl_hours": TTL_HOURS,
            "intelligence": intelligence,
            "sources": sources or [],
            "stats": stats or {},
            "reuse_count": 0
        }

        # Remove old entry for same query if exists
        cache_data["entries"] = [e for e in cache_data["entries"] if e["query_hash"] != query_hash]

        # Add new entry
        cache_data["entries"].append(entry)

        # Cleanup expired entries
        cache_data["entries"] = [
            e for e in cache_data["entries"]
            if _parse_datetime_aware(e["expires_at"]) > datetime.now(timezone.utc)
        ]

        # Save to disk
        self._save_cache(cache_data)

        logger.info(f"[IntelCache] Saved intelligence for query hash: {query_hash} (expires in {TTL_HOURS}h)")
        return query_hash

    def load_intelligence(self, query: str, force_refresh: bool = False) -> Optional[Dict]:
        """
        Load intelligence if available and fresh.

        Uses two-stage matching:
        1. Exact hash match (fast)
        2. Semantic similarity match via embeddings (fallback for follow-up queries)

        Args:
            query: Query to find intelligence for
            force_refresh: If True, bypass cache and return None (forces fresh research)

        Returns:
            Intelligence dict if found and valid, None otherwise
        """
        # FORCE REFRESH: Skip cache lookup entirely
        if force_refresh:
            query_hash = self._hash_query(query)
            logger.info(
                f"[IntelCache] FORCE REFRESH requested - bypassing cache for query hash: {query_hash}"
            )
            return None

        query_hash = self._hash_query(query)
        cache_data = self._load_cache()

        # Stage 1: Exact hash match (fast path)
        for entry in cache_data["entries"]:
            if entry["query_hash"] == query_hash:
                # Check version compatibility
                entry_version = entry.get("version", "1.0")  # Old entries may not have version
                if entry_version != CACHE_VERSION:
                    logger.info(
                        f"[IntelCache] Cache VERSION MISMATCH for query hash: {query_hash} "
                        f"(cache: {entry_version}, current: {CACHE_VERSION})"
                    )
                    return None

                # Check expiry
                expires_at = _parse_datetime_aware(entry["expires_at"])
                if expires_at > datetime.now(timezone.utc):
                    # Valid entry - increment reuse count
                    entry["reuse_count"] += 1
                    self._save_cache(cache_data)

                    age_minutes = (datetime.now(timezone.utc) - _parse_datetime_aware(entry["created_at"])).total_seconds() / 60
                    logger.info(
                        f"[IntelCache] Cache HIT (exact hash) for query hash: {query_hash} "
                        f"(age: {age_minutes:.1f}m, reuse_count: {entry['reuse_count']})"
                    )
                    # Merge sources into intelligence for downstream consumers
                    result = dict(entry["intelligence"])
                    if entry.get("sources"):
                        result["sources"] = entry["sources"]
                    return result
                else:
                    logger.info(f"[IntelCache] Cache EXPIRED for query hash: {query_hash}")
                    # Don't return yet - try semantic match on other entries
                    break

        # Stage 2: Semantic similarity match (fallback for follow-up queries)
        # Filter to valid entries only (non-expired, correct version)
        now = datetime.now(timezone.utc)
        valid_entries = [
            e for e in cache_data["entries"]
            if e.get("version", "1.0") == CACHE_VERSION
            and _parse_datetime_aware(e["expires_at"]) > now
        ]

        if valid_entries:
            semantic_match, similarity = self._find_semantically_similar_entry(query, valid_entries)
            if semantic_match:
                # Found semantic match - increment reuse count
                semantic_match["reuse_count"] = semantic_match.get("reuse_count", 0) + 1
                self._save_cache(cache_data)

                age_minutes = (now - _parse_datetime_aware(semantic_match["created_at"])).total_seconds() / 60
                logger.info(
                    f"[IntelCache] Cache HIT (semantic, sim={similarity:.3f}) "
                    f"query='{query[:30]}...' matched='{semantic_match['original_query'][:30]}...' "
                    f"(age: {age_minutes:.1f}m, reuse_count: {semantic_match['reuse_count']})"
                )
                # Merge sources into intelligence for downstream consumers
                result = dict(semantic_match["intelligence"])
                if semantic_match.get("sources"):
                    result["sources"] = semantic_match["sources"]
                return result

        logger.info(f"[IntelCache] Cache MISS for query hash: {query_hash} (no semantic match either)")
        return None

    def has_intelligence(self, query: str) -> bool:
        """
        Quick check for cache hit without loading full intelligence.

        Used by strategy selector to decide between STANDARD vs DEEP.
        """
        intelligence = self.load_intelligence(query)
        return intelligence is not None

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics for monitoring.

        Returns:
            {
                "total_entries": int,
                "total_reuses": int,
                "avg_reuse_count": float,
                "oldest_age_hours": float,
                "newest_age_hours": float
            }
        """
        cache_data = self._load_cache()
        entries = cache_data["entries"]

        if not entries:
            return {
                "total_entries": 0,
                "total_reuses": 0,
                "avg_reuse_count": 0.0,
                "oldest_age_hours": 0.0,
                "newest_age_hours": 0.0
            }

        now = datetime.now(timezone.utc)
        ages_hours = [
            (now - _parse_datetime_aware(e["created_at"])).total_seconds() / 3600
            for e in entries
        ]

        total_reuses = sum(e["reuse_count"] for e in entries)

        return {
            "total_entries": len(entries),
            "total_reuses": total_reuses,
            "avg_reuse_count": total_reuses / len(entries) if entries else 0.0,
            "oldest_age_hours": max(ages_hours) if ages_hours else 0.0,
            "newest_age_hours": min(ages_hours) if ages_hours else 0.0
        }

    def clear_expired(self):
        """Remove expired entries from cache."""
        cache_data = self._load_cache()

        before_count = len(cache_data["entries"])
        cache_data["entries"] = [
            e for e in cache_data["entries"]
            if _parse_datetime_aware(e["expires_at"]) > datetime.now(timezone.utc)
        ]
        after_count = len(cache_data["entries"])

        if before_count > after_count:
            self._save_cache(cache_data)
            logger.info(f"[IntelCache] Cleared {before_count - after_count} expired entries")

    def clear_all(self):
        """Clear entire cache for this session."""
        cache_data = {
            "cache_version": CACHE_VERSION,
            "session_id": self.session_id,
            "entries": []
        }
        self._save_cache(cache_data)
        logger.info(f"[IntelCache] Cleared all entries for session {self.session_id}")

    def get_all_entries(self, include_expired: bool = False) -> List[Dict]:
        """
        Get all cache entries (public API for knowledge retrieval).

        Args:
            include_expired: If True, include expired entries too

        Returns:
            List of cache entries
        """
        cache_data = self._load_cache()
        entries = cache_data.get("entries", [])

        if include_expired:
            return entries

        # Filter to non-expired entries only
        now = datetime.now(timezone.utc)
        return [
            e for e in entries
            if _parse_datetime_aware(e["expires_at"]) > now
        ]

    def _load_cache(self) -> Dict:
        """Load cache file from disk."""
        if not self.cache_path.exists():
            return {
                "cache_version": CACHE_VERSION,
                "session_id": self.session_id,
                "entries": []
            }

        try:
            with open(self.cache_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"[IntelCache] Failed to load cache, creating new: {e}")
            return {
                "cache_version": CACHE_VERSION,
                "session_id": self.session_id,
                "entries": []
            }

    def _save_cache(self, data: Dict):
        """Save cache file to disk."""
        try:
            with open(self.cache_path, "w") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            logger.error(f"[IntelCache] Failed to save cache: {e}")


# Global cache instances (one per session)
_cache_instances: Dict[str, SessionIntelligenceCache] = {}


def get_intelligence_cache(session_id: str) -> SessionIntelligenceCache:
    """
    Get or create cache instance for session.

    Singleton pattern - one cache per session_id.
    """
    if session_id not in _cache_instances:
        _cache_instances[session_id] = SessionIntelligenceCache(session_id)
    return _cache_instances[session_id]
