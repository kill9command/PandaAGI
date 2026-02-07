"""
Thinking Visualization Service

Provides real-time thinking stage events for the frontend visualization system.
Tracks query progress through stages like analyzing, planning, executing, synthesizing.

Architecture Reference:
    architecture/README.md (8-Phase Pipeline)

Design Notes:
- Stage names (guide_analyzing, coordinator_planning, orchestrator_executing,
  guide_synthesizing) are legacy from multi-model design. Current architecture
  uses phase-based roles: Phase 1 Query Analyzer, Phase 3 Planner, Phase 4
  Executor, Phase 5 Coordinator, Phase 6 Synthesizer.
- These names are kept for frontend compatibility - the UI relies on these
  stage identifiers for visualization.
- Confidence heuristics are for UI display purposes, not decision-making.
  Actual validation confidence comes from Phase 7.
"""

import asyncio
import logging
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# =============================================================================
# Thinking Event Model
# =============================================================================


@dataclass
class ThinkingEvent:
    """Represents a thinking stage event for real-time visualization."""

    trace_id: str
    stage: str  # phase_0_query_analyzer, phase_1_reflection, ..., phase_8_save, complete
    status: str  # pending, active, completed, error
    confidence: float  # 0.0-1.0
    duration_ms: int
    details: dict
    reasoning: str
    timestamp: float
    message: str = ""  # Optional message field for complete events (contains final response)
    input_summary: str = ""   # Human-readable summary of what this phase received
    output_summary: str = ""  # Human-readable summary of what this phase produced
    input_raw: str = ""       # Full input content (truncated to 2000 chars)
    output_raw: str = ""      # Full output content (truncated to 2000 chars)

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return asdict(self)


@dataclass
class ActionEvent:
    """Represents a source/action event for the route notifier panel."""

    trace_id: str
    action_type: str  # memory, search, fetch, fetch_retry, route, tool, error, decision
    label: str
    detail: str = ""
    success: Optional[bool] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return asdict(self)


# =============================================================================
# Event Queue Infrastructure
# =============================================================================

# Event queues: trace_id -> queue of ThinkingEvents
THINKING_QUEUES: Dict[str, asyncio.Queue] = {}
_THINKING_QUEUE_LOCK = asyncio.Lock()
_THINKING_CLEANUP_INTERVAL = 300  # Cleanup old queues every 5 minutes
_THINKING_MAX_AGE = 600  # Keep queues for 10 minutes
_THINKING_LAST_CLEANUP = time.time()

# Response store: trace_id -> (response_text, timestamp)
# Persists final responses so they can be fetched via polling if SSE drops
RESPONSE_STORE: Dict[str, tuple] = {}
_RESPONSE_STORE_LOCK = asyncio.Lock()
_RESPONSE_STORE_MAX_AGE = 600  # Keep responses for 10 minutes


# =============================================================================
# Event Emission Functions
# =============================================================================


async def emit_thinking_event(event: ThinkingEvent):
    """Emit a thinking event to the appropriate queue."""
    async with _THINKING_QUEUE_LOCK:
        if event.trace_id not in THINKING_QUEUES:
            THINKING_QUEUES[event.trace_id] = asyncio.Queue()
        await THINKING_QUEUES[event.trace_id].put(event)
        logger.info(
            f"[Thinking] Event emitted: trace={event.trace_id}, stage={event.stage}, status={event.status}"
        )

    # Store final response separately for polling fallback
    if event.stage == "complete" and event.message:
        async with _RESPONSE_STORE_LOCK:
            RESPONSE_STORE[event.trace_id] = (event.message, time.time())
            logger.info(
                f"[ResponseStore] Stored response for trace {event.trace_id}: {len(event.message)} chars"
            )
        # NOTE: Don't delete queue here - let SSE consumer read the complete event first
        # The cleanup_thinking_queues() function will remove old queues periodically


async def emit_action_event(event: ActionEvent):
    """Emit an action/source event to the thinking queue for the route notifier."""
    async with _THINKING_QUEUE_LOCK:
        if event.trace_id not in THINKING_QUEUES:
            THINKING_QUEUES[event.trace_id] = asyncio.Queue()
        await THINKING_QUEUES[event.trace_id].put(event)
        logger.debug(
            f"[Thinking] Action emitted: trace={event.trace_id}, type={event.action_type}, label={event.label}"
        )


async def cleanup_thinking_queues():
    """Remove old thinking queues and expired responses to prevent memory leaks."""
    global _THINKING_LAST_CLEANUP
    now = time.time()
    if now - _THINKING_LAST_CLEANUP < _THINKING_CLEANUP_INTERVAL:
        return

    async with _THINKING_QUEUE_LOCK:
        to_remove = []
        for trace_id in THINKING_QUEUES:
            # Remove if queue is empty and old (no activity)
            queue = THINKING_QUEUES[trace_id]
            if queue.empty():
                to_remove.append(trace_id)

        for trace_id in to_remove:
            del THINKING_QUEUES[trace_id]

        if to_remove:
            logger.info(f"[Thinking] Cleaned up {len(to_remove)} old thinking queues")

    # Also cleanup old responses
    async with _RESPONSE_STORE_LOCK:
        expired = [
            trace_id
            for trace_id, (_, ts) in RESPONSE_STORE.items()
            if now - ts > _RESPONSE_STORE_MAX_AGE
        ]
        for trace_id in expired:
            del RESPONSE_STORE[trace_id]
        if expired:
            logger.info(f"[ResponseStore] Cleaned up {len(expired)} expired responses")

    _THINKING_LAST_CLEANUP = now


# =============================================================================
# Queue Access Functions
# =============================================================================


def get_thinking_queue(trace_id: str) -> Optional[asyncio.Queue]:
    """Get the thinking queue for a trace, if it exists."""
    return THINKING_QUEUES.get(trace_id)


def has_thinking_queue(trace_id: str) -> bool:
    """Check if a thinking queue exists for a trace."""
    return trace_id in THINKING_QUEUES


async def get_response(trace_id: str) -> Optional[str]:
    """Get stored response for a trace, if available."""
    async with _RESPONSE_STORE_LOCK:
        entry = RESPONSE_STORE.get(trace_id)
        if entry:
            return entry[0]  # Return response text
    return None


# =============================================================================
# Confidence Calculation
# =============================================================================


def calculate_confidence(stage: str, context: dict) -> float:
    """
    Calculate confidence score (0.0-1.0) for a thinking stage.

    Args:
        stage: Thinking stage name
        context: Context dict with stage-specific data

    Returns:
        Confidence score between 0.0 and 1.0
    """
    if stage == "query_received":
        # High confidence if query is clear and well-formed
        query = context.get("query", "")
        if len(query.strip()) > 10:
            return 0.95
        return 0.7

    elif stage == "guide_analyzing":
        # Confidence based on query classification
        query_type = context.get("query_type", "general")
        complexity = context.get("complexity", "standard")
        if query_type != "general" and complexity != "multi_goal":
            return 0.85
        elif query_type != "general":
            return 0.75
        return 0.65

    elif stage == "coordinator_planning":
        # Confidence based on plan quality
        plan = context.get("plan", {})
        num_steps = len(plan.get("plan_steps", []))
        if num_steps > 0 and num_steps <= 5:
            return 0.9
        elif num_steps > 5:
            return 0.75
        return 0.5

    elif stage == "orchestrator_executing":
        # Confidence based on execution results
        success_rate = context.get("success_rate", 0.0)
        return success_rate

    elif stage == "guide_synthesizing":
        # Confidence based on capsule quality
        num_claims = context.get("num_claims", 0)
        if num_claims >= 5:
            return 0.9
        elif num_claims >= 2:
            return 0.8
        return 0.6

    elif stage == "response_complete":
        # Confidence based on overall success
        if context.get("success", False):
            return 0.95
        return 0.5

    return 0.5  # Default moderate confidence


def boost_confidence_for_patterns(
    base_confidence: float,
    conversation_history: list,
    current_query: str,
    cache_stats: dict = None,
) -> Tuple[float, List[str]]:
    """
    Boost confidence based on conversation patterns.

    Args:
        base_confidence: Initial confidence from strategic analysis
        conversation_history: Recent conversation turns
        current_query: Current user query
        cache_stats: Optional cache hit/miss statistics

    Returns:
        (adjusted_confidence, boost_reasons)
    """
    boost = 0.0
    reasons = []

    # Pattern 1: Query repetition (boost +0.1 if repeated 3+ times)
    query_lower = current_query.lower().strip()
    similar_queries = []

    for msg in conversation_history[-10:]:  # Check last 10 turns
        if msg.get("role") == "user":
            past_query = msg.get("content", "").lower().strip()
            # Use SequenceMatcher for fuzzy matching
            similarity = SequenceMatcher(None, query_lower, past_query).ratio()
            if similarity >= 0.7:  # 70% similarity threshold
                similar_queries.append(past_query)

    if len(similar_queries) >= 3:
        boost += 0.1
        reasons.append(f"Query pattern repeated {len(similar_queries)} times")

    # Pattern 2: High cache hit rate (boost +0.05 if ≥80%)
    if cache_stats:
        hit_rate = cache_stats.get("hit_rate", 0.0)
        if hit_rate >= 0.8:
            boost += 0.05
            reasons.append(f"High cache hit rate ({hit_rate:.0%})")

    # Pattern 3: Topic continuity (boost +0.05 if stayed on topic for 10+ turns)
    # Check if recent conversation has consistent topic keywords
    topic_keywords = set()
    recent_user_msgs = [
        msg.get("content", "").lower()
        for msg in conversation_history[-10:]
        if msg.get("role") == "user"
    ]

    if len(recent_user_msgs) >= 3:
        # Extract common words (excluding stopwords)
        stopwords = {
            "a",
            "an",
            "the",
            "is",
            "are",
            "of",
            "for",
            "to",
            "in",
            "on",
            "and",
            "or",
            "i",
            "you",
            "me",
        }
        all_words = []
        for msg in recent_user_msgs:
            words = [w for w in msg.split() if len(w) > 3 and w not in stopwords]
            all_words.extend(words)

        # Count word frequency
        word_counts = Counter(all_words)

        # If any word appears in 50%+ of recent messages, topic is consistent
        for word, count in word_counts.most_common(5):
            if count >= len(recent_user_msgs) * 0.5:
                topic_keywords.add(word)

        if len(topic_keywords) >= 2:
            boost += 0.05
            reasons.append(
                f"Topic continuity (keywords: {', '.join(list(topic_keywords)[:3])})"
            )

    adjusted_confidence = min(1.0, base_confidence + boost)

    return adjusted_confidence, reasons
