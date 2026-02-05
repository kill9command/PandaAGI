"""
Context Ranker - Relevance-based claim ranking and context optimization

Provides semantic similarity scoring for claims and memories to enable
selective injection based on current task relevance.
"""

import re
from typing import List, Tuple, Dict, Any
from dataclasses import dataclass


@dataclass
class RankedItem:
    """Item with relevance score."""
    score: float
    item: Any
    reasons: List[str]


def _tokenize(text: str) -> set:
    """Simple tokenization with stopword removal."""
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should',
        'can', 'could', 'may', 'might', 'must', 'this', 'that', 'these', 'those'
    }

    # Lowercase and extract alphanumeric words
    words = re.findall(r'\b[a-z0-9_]+\b', text.lower())
    return {w for w in words if w not in stopwords and len(w) > 2}


def _keyword_overlap_score(text1: str, text2: str) -> float:
    """Calculate Jaccard similarity between two texts."""
    tokens1 = _tokenize(text1)
    tokens2 = _tokenize(text2)

    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1 & tokens2
    union = tokens1 | tokens2

    return len(intersection) / len(union) if union else 0.0


def _domain_boost(claim_domain: str, task_domain: str) -> float:
    """Boost score if domains match."""
    if claim_domain == task_domain:
        return 1.5
    if claim_domain == "general":
        return 1.2
    return 1.0


def _recency_boost(updated_at: str, max_age_seconds: int = 3600) -> float:
    """Boost recent claims."""
    from datetime import datetime, timezone

    try:
        updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        age_seconds = (now - updated).total_seconds()

        if age_seconds < max_age_seconds:
            # Linear decay from 1.3 to 1.0 over max_age
            return 1.3 - (0.3 * (age_seconds / max_age_seconds))
        return 1.0
    except:
        return 1.0


def rank_claims_by_relevance(
    claims: List[Any],
    current_goal: str,
    task_domain: str = "general",
    max_results: int = 10
) -> List[RankedItem]:
    """
    Rank claims by relevance to current goal.

    Args:
        claims: List of claim objects with REQUIRED .text attribute,
                optional .domain, .updated_at, .confidence attributes
        current_goal: Current task description
        task_domain: Domain of current task (code, commerce, research, general)
        max_results: Maximum number of results to return

    Returns:
        List of RankedItem objects sorted by score (descending)
    """
    ranked = []

    for claim in claims:
        try:
            # Safety check: Skip claims without required .text attribute
            if not hasattr(claim, 'text') or not claim.text:
                continue

            # Base keyword overlap score
            score = _keyword_overlap_score(claim.text, current_goal)
            reasons = []

            if score > 0.3:
                reasons.append(f"keyword_overlap={score:.2f}")

            # Apply domain boost
            domain_mult = _domain_boost(
                getattr(claim, 'domain', 'general'),
                task_domain
            )
            if domain_mult > 1.0:
                reasons.append(f"domain_match={domain_mult:.1f}x")
            score *= domain_mult

            # Apply recency boost
            if hasattr(claim, 'updated_at'):
                recency_mult = _recency_boost(claim.updated_at)
                if recency_mult > 1.0:
                    reasons.append(f"recent={recency_mult:.2f}x")
                score *= recency_mult

            # Confidence boost
            if hasattr(claim, 'confidence'):
                conf_map = {"high": 1.2, "medium": 1.0, "low": 0.8}
                conf_mult = conf_map.get(claim.confidence, 1.0)
                if conf_mult != 1.0:
                    reasons.append(f"confidence={claim.confidence}")
                score *= conf_mult

            if score > 0:
                ranked.append(RankedItem(score=score, item=claim, reasons=reasons))

        except Exception:
            # Skip problematic claims silently to avoid breaking the ranking process
            continue

    # Sort by score descending
    ranked.sort(key=lambda x: x.score, reverse=True)

    return ranked[:max_results]


def rank_memories_by_relevance(
    memories: List[Dict[str, Any]],
    current_query: str,
    user_context: str = "",
    max_results: int = 5
) -> List[RankedItem]:
    """
    Rank memories by relevance to current query.

    Args:
        memories: List of memory dicts with 'body', 'tags', 'metadata'
        current_query: Current user query
        user_context: Additional context (e.g., recent conversation)
        max_results: Maximum number of results to return

    Returns:
        List of RankedItem objects sorted by score (descending)
    """
    ranked = []
    combined_query = f"{current_query} {user_context}"

    for memory in memories:
        body = memory.get('body', '')
        tags = memory.get('tags', [])
        metadata = memory.get('metadata', {})

        # Base text similarity
        score = _keyword_overlap_score(body, combined_query)
        reasons = []

        if score > 0.2:
            reasons.append(f"text_match={score:.2f}")

        # Tag boost
        tag_text = ' '.join(tags) if tags else ''
        tag_score = _keyword_overlap_score(tag_text, current_query)
        if tag_score > 0.3:
            score += tag_score * 0.5  # Tags worth 50% of body match
            reasons.append(f"tag_match={tag_score:.2f}")

        # Recency boost for short-term memories
        if 'created_at' in metadata:
            recency_mult = _recency_boost(metadata['created_at'], max_age_seconds=7200)
            if recency_mult > 1.0:
                reasons.append(f"recent={recency_mult:.2f}x")
            score *= recency_mult

        # User preference boost
        if metadata.get('type') == 'preference':
            score *= 1.3
            reasons.append("preference")

        if score > 0:
            ranked.append(RankedItem(score=score, item=memory, reasons=reasons))

    # Sort by score descending
    ranked.sort(key=lambda x: x.score, reverse=True)

    return ranked[:max_results]


def estimate_token_count(text: str) -> int:
    """Rough token count estimate (1 token ≈ 4 chars)."""
    return len(text) // 4


def budget_aware_selection(
    ranked_items: List[RankedItem],
    max_tokens: int,
    min_items: int = 3
) -> List[Any]:
    """
    Select items within token budget, prioritizing high scores.

    Args:
        ranked_items: Pre-ranked items (highest score first)
        max_tokens: Maximum token budget
        min_items: Minimum items to include (ignoring budget if needed)

    Returns:
        List of selected items
    """
    selected = []
    tokens_used = 0

    for ranked in ranked_items:
        item = ranked.item

        # Estimate tokens
        if hasattr(item, 'text'):
            item_tokens = estimate_token_count(item.text)
        elif isinstance(item, dict) and 'body' in item:
            item_tokens = estimate_token_count(item['body'])
        else:
            item_tokens = estimate_token_count(str(item))

        # Include if within budget or below minimum
        if tokens_used + item_tokens <= max_tokens or len(selected) < min_items:
            selected.append(item)
            tokens_used += item_tokens
        else:
            # Budget exhausted
            break

    return selected
