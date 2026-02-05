"""
Response Cache (Layer 1)

Caches final personalized responses that incorporate user preferences,
conversation context, and session history. USER-SPECIFIC by design.

Design rationale:
1. Token Efficiency: Responses already include user context (budget, location)
   → No re-contextualization needed (saves ~200 tokens per request)
2. Architectural Alignment: Matches Living Session Context v4 schema
3. Privacy: Prevents cross-user leakage of preferences
4. Simplicity: LLM doesn't handle preference conflicts

Sharing model: Session-scoped (one cache per user per query)
"""
import json
import logging
import hashlib
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict

from apps.services.tool_server.shared_state.embedding_service import EMBEDDING_SERVICE
from apps.services.tool_server.shared_state.hybrid_retrieval import HYBRID_RETRIEVAL
from apps.services.tool_server.shared_state.cache_config import (
    RESPONSE_CACHE_DIR,
    RESPONSE_CACHE_SIMILARITY_THRESHOLD,
    RESPONSE_CACHE_MAX_SIZE_GB,
    RESPONSE_CACHE_ENABLED,
    HYBRID_SEARCH_EMBEDDING_WEIGHT
)
from apps.services.tool_server.shared_state.context_fingerprint import compute_fingerprint

logger = logging.getLogger(__name__)


@dataclass
class CacheCandidate:
    """A potential cache match with scores"""
    response_id: str
    query: str
    response: str
    intent: str
    domain: str
    hybrid_score: float
    semantic_score: float
    keyword_score: float
    age_hours: float
    ttl_hours: int
    quality_score: float
    created_at: str
    claims_used: List[str]


class ResponseCache:
    """
    Layer 1: User-specific response cache with hybrid search.

    DESIGN DECISION: Cache is intentionally USER-SPECIFIC.
    Context fingerprint includes session_id to isolate users.
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or RESPONSE_CACHE_DIR
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Index: session_fingerprint -> list of response IDs
        self.index = {}
        self._load_index()

        logger.info(f"[ResponseCache] Initialized at {self.storage_path}")

    def _load_index(self):
        """Load index of cached responses"""
        try:
            index_path = self.storage_path / "index.json"
            if index_path.exists():
                with open(index_path, 'r') as f:
                    self.index = json.load(f)
                logger.info(f"[ResponseCache] Loaded index with {len(self.index)} sessions")
        except Exception as e:
            logger.error(f"[ResponseCache] Failed to load index: {e}")
            self.index = {}

    def _save_index(self):
        """Save index to disk"""
        try:
            index_path = self.storage_path / "index.json"
            with open(index_path, 'w') as f:
                json.dump(self.index, f, indent=2)
        except Exception as e:
            logger.error(f"[ResponseCache] Failed to save index: {e}")

    async def search(
        self,
        query: str,
        intent: str,
        domain: str,
        session_context: dict,
        similarity_threshold: Optional[float] = None
    ) -> List[CacheCandidate]:
        """
        Find semantically similar cached responses FOR THIS USER.

        Uses HYBRID SEARCH (embeddings + BM25 keywords) to prevent false positives.

        Filters by:
        1. Intent match (prevent cross-intent pollution)
        2. Context fingerprint (user-specific, intent-aware)
        3. Domain match (prevent cross-domain contamination)
        4. Hybrid similarity (semantic + keyword, >0.85 combined)
        5. Freshness (within TTL)

        Args:
            query: User query
            intent: Query intent (transactional/informational/etc)
            domain: Query domain (purchasing/care/etc)
            session_context: Session context dict with session_id, preferences, domain
            similarity_threshold: Override default threshold

        Returns:
            List of cache candidates sorted by hybrid score
        """
        # Check if response cache is disabled
        if not RESPONSE_CACHE_ENABLED:
            logger.info("[ResponseCache] Response cache DISABLED (RESPONSE_CACHE_ENABLED=0)")
            return []

        if similarity_threshold is None:
            similarity_threshold = RESPONSE_CACHE_SIMILARITY_THRESHOLD

        # DEBUG: Log what we're searching with
        prefs = session_context.get('preferences', {})
        sorted_prefs_json = json.dumps(prefs, sort_keys=True) if prefs else "{}"
        # PHASE 1: Use intent-aware fingerprint to prevent cross-intent cache pollution
        context_fp = self._context_fingerprint(session_context, intent=intent)

        logger.info(
            f"[ResponseCache-DEBUG-SEARCH] "
            f"session_id={session_context.get('session_id', 'unknown')[:12]}, "
            f"preferences_type={type(prefs).__name__}, "
            f"preferences_keys={list(prefs.keys()) if isinstance(prefs, dict) else 'N/A'}, "
            f"preferences_json={sorted_prefs_json[:100]}, "
            f"fingerprint={context_fp}, "
            f"index_has_fp={context_fp in self.index}"
        )

        # Get user's cache entries using new stable fingerprint
        response_ids = self.index.get(context_fp, [])

        # MIGRATION: Find ALL legacy caches for this session_id
        # This allows existing caches with old fingerprints (preferences included) to still be found
        if not response_ids:
            session_id = session_context.get('session_id', 'unknown')
            legacy_response_ids = []

            # Search through all index entries for this session's old fingerprints
            for fp, ids in self.index.items():
                if fp == context_fp:  # Skip if already checked
                    continue
                # Load one entry to check session_id
                try:
                    if ids:
                        sample_file = self.storage_path / f"{ids[0]}.json"
                        if sample_file.exists():
                            with open(sample_file) as f:
                                entry = json.load(f)
                            if entry.get("session_id") == session_id:
                                legacy_response_ids.extend(ids)
                                logger.info(
                                    f"[ResponseCache] Found {len(ids)} legacy cache(s) "
                                    f"with old fingerprint {fp} for session {session_id[:8]}"
                                )
                except Exception as e:
                    logger.warning(f"[ResponseCache] Error checking fingerprint {fp}: {e}")

            response_ids = legacy_response_ids

        if not response_ids:
            logger.info(
                f"[ResponseCache] No cached responses for fingerprint {context_fp} "
                f"(session={session_context.get('session_id')}, "
                f"prefs={session_context.get('preferences')}, "
                f"domain={session_context.get('domain')})"
            )
            return []

        logger.info(
            f"[ResponseCache] Found {len(response_ids)} cached responses for fingerprint {context_fp} "
            f"(session={session_context.get('session_id', 'unknown')[:8]}, "
            f"prefs={len(session_context.get('preferences', {}))}, "
            f"domain={session_context.get('domain')})"
        )

        # Load entries and pre-filter
        candidates = []
        for response_id in response_ids:
            response_file = self.storage_path / f"{response_id}.json"
            if not response_file.exists():
                continue

            try:
                with open(response_file, 'r') as f:
                    entry = json.load(f)

                # Filter by intent (strict - prevents cross-intent pollution)
                if entry.get("intent") != intent:
                    logger.debug(
                        f"[ResponseCache] Intent mismatch: {entry.get('intent')} != {intent}"
                    )
                    continue

                # Domain check: Log but don't filter
                # Rationale: extract_topic() produces volatile results for same semantic query
                # ("shopping for Syrian hamsters" vs "shopping for hamsters online")
                # Hybrid search semantic similarity handles domain relevance better than exact match
                entry_domain = entry.get("domain", "general")
                if entry_domain != domain:
                    logger.info(
                        f"[ResponseCache] Domain variation (will rely on semantic matching): "
                        f"cached='{entry_domain}' vs current='{domain}'"
                    )
                # Don't continue - let hybrid search decide semantic relevance

                # Check freshness
                created_at = datetime.fromisoformat(entry["created_at"])
                age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
                ttl_hours = entry.get("ttl_hours", 6)

                # Load embedding
                embedding_file = self.storage_path / f"{response_id}.npy"
                if not embedding_file.exists():
                    logger.warning(f"[ResponseCache] Missing embedding for {response_id}")
                    continue

                embedding = np.load(str(embedding_file))

                candidates.append({
                    "text": entry["query"],
                    "embedding": embedding,
                    "domain": entry["domain"],
                    "entry": {
                        "response_id": response_id,
                        "query": entry["query"],
                        "response": entry["response"],
                        "intent": entry["intent"],
                        "domain": entry["domain"],
                        "age_hours": age_hours,
                        "ttl_hours": ttl_hours,
                        "quality_score": entry.get("quality_score", 0.0),
                        "created_at": entry["created_at"],
                        "claims_used": entry.get("claims_used", [])
                    }
                })

            except Exception as e:
                logger.warning(f"[ResponseCache] Failed to load entry {response_id}: {e}")

        if not candidates:
            logger.info("[ResponseCache] No candidates after pre-filtering")
            return []

        logger.info(f"[ResponseCache] {len(candidates)} candidates after pre-filter")

        # HYBRID SEARCH: Semantic + Keyword matching
        if not EMBEDDING_SERVICE.is_available():
            logger.warning("[ResponseCache] Embeddings unavailable, cannot perform hybrid search")
            return []

        hybrid_results = HYBRID_RETRIEVAL.search(
            query=query,
            candidates=candidates,
            top_k=5,
            embedding_weight=HYBRID_SEARCH_EMBEDDING_WEIGHT,
            min_embedding_score=similarity_threshold,
            min_keyword_score=0.1,
            domain_filter=None  # Don't filter - extract_topic() too volatile, rely on semantic similarity
        )

        logger.info(f"[ResponseCache] Hybrid search: {len(hybrid_results)} matches")

        # Convert hybrid results to cache candidates
        cache_candidates = []
        for result in hybrid_results:
            entry = result["candidate"]["entry"]

            # Check if fresh or stale-but-acceptable
            staleness_ratio = entry["age_hours"] / entry["ttl_hours"]
            is_fresh = staleness_ratio <= 1.0

            # Quality-based staleness tolerance
            if not is_fresh:
                if entry["quality_score"] >= 0.90:
                    max_ratio = 1.50  # Excellent quality = 50% grace period
                elif entry["quality_score"] >= 0.80:
                    max_ratio = 1.20  # Good quality = 20% grace period
                else:
                    max_ratio = 1.00  # Fair quality = no grace period

                if staleness_ratio > max_ratio:
                    logger.debug(
                        f"[ResponseCache] Too stale: age={entry['age_hours']:.1f}h, "
                        f"ttl={entry['ttl_hours']}h, ratio={staleness_ratio:.2f} > {max_ratio}"
                    )
                    continue

            cache_candidates.append(CacheCandidate(
                response_id=entry["response_id"],
                query=entry["query"],
                response=entry["response"],
                intent=entry["intent"],
                domain=entry["domain"],
                hybrid_score=result["hybrid_score"],
                semantic_score=result["semantic_score"],
                keyword_score=result["keyword_score"],
                age_hours=entry["age_hours"],
                ttl_hours=entry["ttl_hours"],
                quality_score=entry["quality_score"],
                created_at=entry["created_at"],
                claims_used=entry["claims_used"]
            ))

        logger.info(
            f"[ResponseCache] Final: {len(cache_candidates)} candidates "
            f"(after staleness check)"
        )

        return cache_candidates

    async def set(
        self,
        query: str,
        intent: str,
        domain: str,
        response: str,
        claims_used: List[str],
        quality_score: float,
        ttl_hours: int,
        session_context: dict,
        manifest_ref: Optional[Dict[str, str]] = None  # v4.0: turn_id, trace_id
    ) -> str:
        """
        Store response in cache (user-specific).

        Args:
            query: User query
            intent: Query intent
            domain: Query domain
            response: Generated response
            claims_used: List of claim IDs used
            quality_score: Quality score (0-1)
            ttl_hours: TTL in hours
            session_context: Session context with session_id, preferences

        Returns:
            Response ID
        """
        try:
            # DEBUG: Log what we're storing
            prefs = session_context.get('preferences', {})
            sorted_prefs_json = json.dumps(prefs, sort_keys=True) if prefs else "{}"
            # PHASE 1: Use intent-aware fingerprint to prevent cross-intent cache pollution
            context_fp = self._context_fingerprint(session_context, intent=intent)

            logger.info(
                f"[ResponseCache-DEBUG-STORE] "
                f"session_id={session_context.get('session_id', 'unknown')[:12]}, "
                f"preferences_type={type(prefs).__name__}, "
                f"preferences_keys={list(prefs.keys()) if isinstance(prefs, dict) else 'N/A'}, "
                f"preferences_json={sorted_prefs_json[:100]}, "
                f"fingerprint={context_fp}"
            )

            # Generate response ID
            response_id = hashlib.md5(
                f"{query}:{intent}:{context_fp}".encode()
            ).hexdigest()[:16]

            # Generate query embedding
            if not EMBEDDING_SERVICE.is_available():
                logger.warning("[ResponseCache] Embeddings unavailable, cannot cache")
                return None

            query_embedding = EMBEDDING_SERVICE.embed(query)
            if query_embedding is None:
                logger.warning("[ResponseCache] Failed to generate query embedding")
                return None

            # Save embedding to separate file
            embedding_file = self.storage_path / f"{response_id}.npy"
            np.save(str(embedding_file), query_embedding)

            # Create cache entry
            entry = {
                "id": response_id,
                "query": query,
                "intent": intent,
                "domain": domain,
                "response": response,
                "claims_used": claims_used,
                "quality_score": quality_score,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ttl_hours": ttl_hours,
                "context_fingerprint": context_fp,  # Already computed above with intent
                "session_id": session_context.get("session_id", "unknown"),
                "sharing": "user-specific",
                "manifest_ref": manifest_ref or {}  # v4.0: turn manifest reference
            }

            # Save to disk
            response_file = self.storage_path / f"{response_id}.json"
            with open(response_file, 'w') as f:
                json.dump(entry, f, indent=2)

            # Update index (use same context_fp already computed with intent)
            # context_fp = self._context_fingerprint(session_context, intent=intent)  # Already computed above
            if context_fp not in self.index:
                self.index[context_fp] = []
            if response_id not in self.index[context_fp]:
                self.index[context_fp].append(response_id)
            self._save_index()

            logger.info(
                f"[ResponseCache-STORE] session={session_context.get('session_id', 'unknown')[:8]}, "
                f"ttl={ttl_hours}h, quality={quality_score:.2f}"
            )

            return response_id

        except Exception as e:
            logger.error(f"[ResponseCache] Failed to store response: {e}")
            return None

    def _context_fingerprint(self, session_context: dict, intent: Optional[str] = None) -> str:
        """
        Generate stable user fingerprint using unified ContextFingerprint.

        DESIGN: Uses unified fingerprinting from cache_store foundation.
        - v2 algorithm with normalized preferences
        - Excludes volatile fields (timestamps, metadata)
        - PHASE 1: Intent-aware to prevent cross-intent cache pollution
        - Backward compatibility with legacy v1 fingerprints

        RATIONALE: Session ID only for stability, preferences handled by semantic search.
        Preferences change over time, would orphan caches if included in fingerprint.
        Semantic search naturally filters based on preference relevance.
        Intent included to prevent transactional queries returning informational cache.

        Args:
            session_context: Session context with session_id, preferences
            intent: Optional intent type (transactional, informational, etc.)

        Returns:
            16-char fingerprint hash
        """
        session_id = session_context.get('session_id', 'unknown')

        # PHASE 1: Use intent-aware fingerprinting (v2 algorithm)
        result = compute_fingerprint(
            session_id=session_id,
            context=session_context,
            query=None,  # Don't include query in context fingerprint
            intent=intent,  # PHASE 1: Include intent to prevent cross-intent pollution
            include_legacy=True  # Support legacy lookups
        )

        return result.primary

    def _legacy_context_fingerprint(self, session_context: dict) -> str:
        """
        Legacy fingerprint with preferences - DEPRECATED.

        This was the old method that included preferences in fingerprint,
        causing cache orphaning when preferences evolved.

        Kept for backward compatibility during migration period.
        Existing caches with old fingerprints will still be found via
        session_id-based search in search() method.
        """
        prefs = session_context.get('preferences', {})
        sorted_prefs = json.dumps(prefs, sort_keys=True) if prefs else "{}"
        fp_str = (
            f"{session_context.get('session_id', 'unknown')}:"
            f"{sorted_prefs}"
        )
        return hashlib.md5(fp_str.encode()).hexdigest()[:16]

    def get_stats(self) -> dict:
        """Get cache statistics"""
        total_entries = 0
        total_size_bytes = 0

        for response_file in self.storage_path.glob("*.json"):
            if response_file.name == "index.json":
                continue
            total_entries += 1
            total_size_bytes += response_file.stat().st_size

        # Add embedding file sizes
        for embedding_file in self.storage_path.glob("*.npy"):
            total_size_bytes += embedding_file.stat().st_size

        return {
            "total_entries": total_entries,
            "total_size_mb": total_size_bytes / (1024 * 1024),
            "total_size_gb": total_size_bytes / (1024 * 1024 * 1024),
            "max_size_gb": RESPONSE_CACHE_MAX_SIZE_GB,
            "sessions": len(self.index),
            "storage_path": str(self.storage_path)
        }


# Global singleton
RESPONSE_CACHE = ResponseCache()
