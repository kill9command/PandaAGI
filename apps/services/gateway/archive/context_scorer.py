"""Cross-type relevance scoring for unified context allocation.

This module provides uniform relevance scoring across different context sources
(memory, RAG, history, claims) using semantic similarity and source confidence.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from apps.services.tool_server.shared_state.embedding_service import EMBEDDING_SERVICE
from apps.services.gateway.intent_weights import IntentWeights, get_intent_weights

logger = logging.getLogger(__name__)


@dataclass
class ContextItem:
    """A scored context item from any source."""

    source: str  # Source type: memory, rag, history, claims
    content: str  # The actual text content
    tokens: int  # Estimated token count
    base_relevance: float  # Semantic similarity score (0.0-1.0)
    source_confidence: float  # Source-specific confidence (0.0-1.0)
    weighted_score: float  # Final score after intent weighting
    metadata: Dict[str, Any]  # Additional metadata (id, timestamp, etc.)

    @property
    def final_score(self) -> float:
        """Get the final weighted score."""
        return self.weighted_score


# Source confidence values based on reliability
SOURCE_CONFIDENCE = {
    "living_context": 1.0,       # Always trusted (current session)
    "long_term_memory": 0.9,     # High confidence (verified past)
    "baseline_memory": 0.8,      # Moderate confidence (filtered)
    "recall_memory": 0.85,       # High confidence (recall-specific)
    "recent_claims": 0.7,        # Moderate confidence (cached, has conf score)
    "rag": 0.7,                  # Moderate confidence (doc search)
    "doc_search": 0.7,           # Moderate confidence (doc search)
    "history": 0.9,              # High confidence (recent context)
}


class ContextScorer:
    """Scores and ranks context items across different sources."""

    def __init__(self):
        """Initialize the context scorer."""
        self.embedding_service = EMBEDDING_SERVICE

    def score_item(
        self,
        content: str,
        source: str,
        query: str,
        intent: str,
        metadata: Optional[Dict[str, Any]] = None,
        existing_similarity: Optional[float] = None
    ) -> ContextItem:
        """Score a single context item.

        Args:
            content: The text content to score
            source: Source type (memory, rag, history, claims)
            query: User query for relevance calculation
            intent: Classified intent (recall, informational, etc.)
            metadata: Additional metadata about this item
            existing_similarity: Pre-computed similarity score (if available)

        Returns:
            ContextItem with relevance scores
        """
        metadata = metadata or {}

        # Calculate base semantic relevance
        if existing_similarity is not None:
            base_relevance = existing_similarity
        elif source in ["memory", "long_term_memory", "baseline_memory", "recall_memory", "rag", "doc_search"]:
            # Use embedding service for semantic similarity
            try:
                query_emb = self.embedding_service.embed(query)
                content_emb = self.embedding_service.embed(content)
                if query_emb is not None and content_emb is not None:
                    base_relevance = self.embedding_service.cosine_similarity(query_emb, content_emb)
                else:
                    base_relevance = 0.5  # Fallback if embeddings unavailable
            except Exception as e:
                logger.warning(f"[ContextScorer] Failed to compute similarity for {source}: {e}")
                base_relevance = 0.5
        else:
            # For history/living context, use recency-based relevance
            base_relevance = 0.8  # Default high relevance for contextual items

        # Get source confidence
        source_confidence = SOURCE_CONFIDENCE.get(source, 0.5)

        # Override with claim confidence if available
        if source == "recent_claims" and "confidence" in metadata:
            source_confidence = metadata["confidence"]

        # Get intent-based weight multiplier
        intent_weights = get_intent_weights(intent)
        intent_multiplier = intent_weights.get_weight(source)

        # Calculate weighted score
        weighted_score = base_relevance * source_confidence * intent_multiplier

        # Estimate token count (rough approximation: 1 token ≈ 4 characters)
        tokens = len(content) // 4

        return ContextItem(
            source=source,
            content=content,
            tokens=tokens,
            base_relevance=base_relevance,
            source_confidence=source_confidence,
            weighted_score=weighted_score,
            metadata=metadata
        )

    def score_batch(
        self,
        items: List[Dict[str, Any]],
        query: str,
        intent: str
    ) -> List[ContextItem]:
        """Score a batch of context items.

        Args:
            items: List of dicts with 'content', 'source', 'metadata', optional 'similarity'
            query: User query for relevance calculation
            intent: Classified intent

        Returns:
            List of scored ContextItems, sorted by weighted_score descending
        """
        scored_items = []

        for item in items:
            try:
                scored_item = self.score_item(
                    content=item["content"],
                    source=item["source"],
                    query=query,
                    intent=intent,
                    metadata=item.get("metadata", {}),
                    existing_similarity=item.get("similarity")
                )
                scored_items.append(scored_item)
            except Exception as e:
                logger.error(f"[ContextScorer] Failed to score item from {item.get('source')}: {e}")
                continue

        # Sort by weighted score descending
        scored_items.sort(key=lambda x: x.weighted_score, reverse=True)

        return scored_items

    def select_within_budget(
        self,
        scored_items: List[ContextItem],
        budget_tokens: int,
        min_allocations: Optional[Dict[str, int]] = None,
        max_allocations: Optional[Dict[str, int]] = None
    ) -> List[ContextItem]:
        """Select top items within token budget with allocation constraints.

        Args:
            scored_items: Scored and sorted context items
            budget_tokens: Total token budget
            min_allocations: Minimum tokens per source type
            max_allocations: Maximum tokens per source type

        Returns:
            List of selected items within budget
        """
        min_allocations = min_allocations or {}
        max_allocations = max_allocations or {}

        selected = []
        tokens_used = 0
        source_tokens = {}  # Track tokens per source

        # Sort by score descending (should already be sorted)
        sorted_items = sorted(scored_items, key=lambda x: x.weighted_score, reverse=True)

        # First pass: ensure minimum allocations
        for item in sorted_items:
            source = item.source
            min_required = min_allocations.get(source, 0)
            current_source_tokens = source_tokens.get(source, 0)

            if current_source_tokens < min_required and tokens_used + item.tokens <= budget_tokens:
                selected.append(item)
                tokens_used += item.tokens
                source_tokens[source] = current_source_tokens + item.tokens

        # Second pass: fill remaining budget by score
        for item in sorted_items:
            if item in selected:
                continue  # Already selected in first pass

            source = item.source
            current_source_tokens = source_tokens.get(source, 0)
            max_allowed = max_allocations.get(source, budget_tokens)

            # Check if we can add this item
            if (tokens_used + item.tokens <= budget_tokens and
                current_source_tokens + item.tokens <= max_allowed):
                selected.append(item)
                tokens_used += item.tokens
                source_tokens[source] = current_source_tokens + item.tokens

        # Sort selected items by source for better organization
        selected.sort(key=lambda x: (x.source, -x.weighted_score))

        logger.info(f"[ContextScorer] Selected {len(selected)} items, {tokens_used}/{budget_tokens} tokens")
        for source, tokens in source_tokens.items():
            logger.info(f"[ContextScorer]   {source}: {tokens} tokens")

        return selected


# Global instance
CONTEXT_SCORER = ContextScorer()
