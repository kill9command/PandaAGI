"""
Hybrid Retrieval System

Combines semantic search (embeddings) with lexical search (BM25 keywords)
to prevent false positives while maintaining high recall.

Problem solved:
- Pure embedding search: "Syrian hamster breeders" matches "Syrian Civil War" (semantic drift)
- Pure keyword search: Misses paraphrases and synonyms (low recall)
- Hybrid search: Requires BOTH semantic similarity AND keyword overlap (high precision + recall)
"""
import logging
import numpy as np
from typing import List, Optional, Dict, Any
from rank_bm25 import BM25Okapi

from apps.services.tool_server.shared_state.embedding_service import EMBEDDING_SERVICE

logger = logging.getLogger(__name__)


class HybridRetrieval:
    """
    Combines semantic search (embeddings) with lexical search (BM25).

    Design philosophy:
    - Semantic search: Understanding meaning, handling synonyms
    - Keyword search: Exact term matching, preventing semantic drift
    - Domain filtering: Preventing cross-domain contamination

    Requires BOTH semantic similarity AND keyword overlap to match.
    """

    def search(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int = 10,
        embedding_weight: float = 0.7,  # 70% semantic, 30% keyword
        min_embedding_score: float = 0.5,
        min_keyword_score: float = 0.1,
        domain_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Hybrid retrieval with domain filtering.

        Args:
            query: User query
            candidates: List of cache entries with 'text', 'embedding', 'domain'
            top_k: Number of results to return
            embedding_weight: Weight for semantic vs keyword (0.0-1.0)
            min_embedding_score: Minimum semantic similarity threshold
            min_keyword_score: Minimum keyword overlap threshold
            domain_filter: Only return results from this domain

        Returns:
            List of ranked candidates with hybrid scores

        Example:
            candidates = [
                {
                    "text": "Syrian hamster breeders",
                    "embedding": np.array([...]),  # 384-dim vector
                    "domain": "purchasing",
                    "claim": <ClaimObject>
                }
            ]

            results = HYBRID_RETRIEVAL.search(
                query="find Syrian hamsters",
                candidates=candidates,
                domain_filter="purchasing"
            )
        """

        if not candidates:
            return []

        # STEP 1: Domain filtering (if specified)
        if domain_filter:
            original_count = len(candidates)
            candidates = [c for c in candidates if c.get("domain") == domain_filter]
            logger.info(
                f"[Hybrid] Domain filter={domain_filter}, "
                f"candidates: {original_count} → {len(candidates)}"
            )

        if not candidates:
            logger.info("[Hybrid] No candidates after domain filtering")
            return []

        # STEP 2: Semantic search (embeddings)
        if not EMBEDDING_SERVICE.is_available():
            logger.warning("[Hybrid] Embeddings unavailable, falling back to keyword-only")
            return self._keyword_only_search(query, candidates, top_k)

        query_embedding = EMBEDDING_SERVICE.embed(query)
        if query_embedding is None:
            logger.warning("[Hybrid] Failed to generate query embedding, falling back to keyword-only")
            return self._keyword_only_search(query, candidates, top_k)

        semantic_scores = []
        for candidate in candidates:
            candidate_embedding = candidate.get("embedding")
            if candidate_embedding is None:
                logger.warning(f"[Hybrid] Candidate missing embedding: {candidate.get('text', '')[:50]}")
                continue

            similarity = EMBEDDING_SERVICE.cosine_similarity(query_embedding, candidate_embedding)
            if similarity >= min_embedding_score:
                semantic_scores.append({
                    "candidate": candidate,
                    "semantic_score": similarity
                })

        logger.info(
            f"[Hybrid] Semantic pass: {len(semantic_scores)}/{len(candidates)} "
            f"above threshold ({min_embedding_score})"
        )

        if not semantic_scores:
            logger.info("[Hybrid] No candidates passed semantic threshold")
            return []

        # STEP 3: Keyword search (BM25)
        corpus = [item["candidate"]["text"] for item in semantic_scores]
        tokenized_corpus = [doc.lower().split() for doc in corpus]

        try:
            bm25 = BM25Okapi(tokenized_corpus)
            query_tokens = query.lower().split()
            bm25_scores = bm25.get_scores(query_tokens)

            # Handle negative BM25 scores (happens when all docs have identical terms)
            # BM25 IDF component goes negative when term appears in ALL documents
            min_bm25 = min(bm25_scores)
            if min_bm25 < 0:
                # Shift all scores to positive range
                bm25_scores = [score - min_bm25 for score in bm25_scores]
                logger.debug(f"[Hybrid] Shifted negative BM25 scores by {-min_bm25:.2f}")

            # Normalize BM25 scores to 0-1 range
            max_bm25 = max(bm25_scores) if bm25_scores else 1.0
            if max_bm25 == 0:
                # All zero scores means perfect keyword match for small identical corpus
                # This typically happens when query matches cached query exactly
                normalized_bm25 = [1.0] * len(bm25_scores)
                logger.info("[Hybrid] All BM25 scores zero (perfect keyword match), setting to 1.0")
            else:
                normalized_bm25 = [score / max_bm25 for score in bm25_scores]

            # Special case: Single candidate gets score of 1.0 if it has ANY keyword overlap
            if len(bm25_scores) == 1 and max_bm25 > 0:
                normalized_bm25 = [1.0]
                logger.info("[Hybrid] Single candidate with keyword overlap, score=1.0")

        except Exception as e:
            logger.error(f"[Hybrid] BM25 failed: {e}, using semantic-only")
            # Fallback to semantic-only if BM25 fails
            semantic_scores.sort(key=lambda x: x["semantic_score"], reverse=True)
            return semantic_scores[:top_k]

        # STEP 4: Combine scores (weighted average)
        hybrid_scores = []
        for i, item in enumerate(semantic_scores):
            keyword_score = normalized_bm25[i]

            # Require minimum keyword overlap (adaptive threshold for few candidates)
            effective_min_keyword = min_keyword_score
            if len(semantic_scores) <= 2:
                # Be more lenient with very few candidates
                effective_min_keyword = min(min_keyword_score, 0.05)

            if keyword_score < effective_min_keyword:
                logger.debug(
                    f"[Hybrid] Filtered out: '{item['candidate']['text'][:50]}...' "
                    f"(keyword={keyword_score:.2f} < {effective_min_keyword})"
                )
                continue

            hybrid_score = (
                embedding_weight * item["semantic_score"] +
                (1 - embedding_weight) * keyword_score
            )

            hybrid_scores.append({
                "candidate": item["candidate"],
                "semantic_score": item["semantic_score"],
                "keyword_score": keyword_score,
                "hybrid_score": hybrid_score
            })

        # STEP 5: Sort by hybrid score and return top-k
        hybrid_scores.sort(key=lambda x: x["hybrid_score"], reverse=True)

        if hybrid_scores:
            logger.info(
                f"[Hybrid] Final: {len(hybrid_scores)} results, "
                f"top score: {hybrid_scores[0]['hybrid_score']:.3f} "
                f"(semantic={hybrid_scores[0]['semantic_score']:.3f}, "
                f"keyword={hybrid_scores[0]['keyword_score']:.3f})"
            )
        else:
            logger.info("[Hybrid] No results after keyword filtering")

        return hybrid_scores[:top_k]

    def _keyword_only_search(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int
    ) -> List[Dict[str, Any]]:
        """
        Fallback to keyword-only search if embeddings unavailable.

        Uses BM25 for ranking.
        """
        logger.info("[Hybrid] Using keyword-only fallback (no embeddings)")

        corpus = [c["text"] for c in candidates]
        tokenized_corpus = [doc.lower().split() for doc in corpus]

        try:
            bm25 = BM25Okapi(tokenized_corpus)
            query_tokens = query.lower().split()
            bm25_scores = bm25.get_scores(query_tokens)

            # Create results with keyword scores only
            results = []
            for i, candidate in enumerate(candidates):
                results.append({
                    "candidate": candidate,
                    "semantic_score": 0.0,  # No embeddings
                    "keyword_score": bm25_scores[i],
                    "hybrid_score": bm25_scores[i]  # Pure keyword
                })

            # Sort and return top-k
            results.sort(key=lambda x: x["hybrid_score"], reverse=True)
            return results[:top_k]

        except Exception as e:
            logger.error(f"[Hybrid] Keyword-only search failed: {e}")
            return []

    def get_config(self) -> dict:
        """Get current hybrid search configuration"""
        return {
            "embedding_weight": 0.7,
            "keyword_weight": 0.3,
            "min_embedding_threshold": 0.5,
            "min_keyword_threshold": 0.1,
            "domain_filtering_enabled": True,
            "embedding_service_available": EMBEDDING_SERVICE.is_available()
        }


# Global singleton
HYBRID_RETRIEVAL = HybridRetrieval()
