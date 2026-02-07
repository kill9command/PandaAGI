"""
Reflector Signal Accumulator for Phase 8.1 Batch Memory Reflector.

Tracks per-user signals that indicate when a batch reflection should trigger.
All signal detection is code-based (no LLM). Two trigger conditions:
- Turn count: Every 10 turns
- Signal urgency: Accumulated urgency > 5.0

Architecture Reference:
    architecture/main-system-patterns/phase8.1-batch-memory-reflector.md §2
"""

import json
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from libs.gateway.persistence.user_paths import UserPathResolver

logger = logging.getLogger(__name__)

# Trigger thresholds
TURN_COUNT_THRESHOLD = 10
URGENCY_THRESHOLD = 5.0

# Signal weights
SIGNAL_WEIGHTS = {
    "topic_repetition": 1.0,
    "user_correction": 2.0,
    "high_confidence_research": 1.5,
    "knowledge_boundary": 1.0,
    "contradiction_detected": 2.5,
}

# Correction patterns (user correcting prior info)
CORRECTION_PATTERN = re.compile(
    r'(?:\bactually\b|\bno[,. ]\s|(?:^|\s)i meant\b|\bnot .+,?\s*but\b)',
    re.IGNORECASE
)

# Max topics to track in recent_topics window
MAX_RECENT_TOPICS = 10


@dataclass
class ReflectorSignalState:
    """Per-user signal accumulator state."""
    user_id: str
    turns_since_last_batch: int = 0
    urgency_score: float = 0.0
    last_batch_turn: int = 0
    last_batch_timestamp: float = 0.0
    recent_topics: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "turns_since_last_batch": self.turns_since_last_batch,
            "urgency_score": self.urgency_score,
            "last_batch_turn": self.last_batch_turn,
            "last_batch_timestamp": self.last_batch_timestamp,
            "recent_topics": self.recent_topics,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReflectorSignalState":
        return cls(
            user_id=data.get("user_id", "default"),
            turns_since_last_batch=data.get("turns_since_last_batch", 0),
            urgency_score=data.get("urgency_score", 0.0),
            last_batch_turn=data.get("last_batch_turn", 0),
            last_batch_timestamp=data.get("last_batch_timestamp", 0.0),
            recent_topics=data.get("recent_topics", []),
        )


def _state_path(user_id: str) -> Path:
    """Get path to signal state file for a user."""
    resolver = UserPathResolver(user_id)
    return resolver.logs_dir / "reflector" / "signal_state.json"


def _load_state(user_id: str) -> ReflectorSignalState:
    """Load signal state from disk. Returns default state if not found."""
    path = _state_path(user_id)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return ReflectorSignalState.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[ReflectorSignal] Corrupt state file, resetting: {e}")
    return ReflectorSignalState(user_id=user_id)


def _save_state(state: ReflectorSignalState) -> None:
    """Persist signal state to disk."""
    path = _state_path(state.user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2))


def _extract_topic_words(text: str) -> List[str]:
    """Extract significant words from text for topic comparison."""
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "for", "to", "and",
        "or", "of", "in", "on", "with", "at", "by", "from", "it", "this",
        "that", "what", "how", "why", "when", "where", "who", "which",
        "can", "do", "does", "did", "will", "would", "should", "could",
        "me", "my", "i", "you", "your", "we", "they", "he", "she",
        "about", "find", "get", "tell", "show", "help", "want", "need",
        "best", "good", "new", "more", "some", "any", "all", "just",
    }
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    return [w for w in words if w not in stop_words]


def _topic_overlap(topic_words: List[str], recent_topics: List[str]) -> int:
    """Count how many recent topics have significant word overlap with current."""
    if not topic_words or not recent_topics:
        return 0

    topic_set = set(topic_words)
    overlap_count = 0
    for prior_topic in recent_topics:
        prior_words = set(_extract_topic_words(prior_topic))
        if not prior_words:
            continue
        # Overlap ratio: shared words / smaller set
        shared = topic_set & prior_words
        min_size = min(len(topic_set), len(prior_words))
        if min_size > 0 and len(shared) / min_size > 0.5:
            overlap_count += 1

    return overlap_count


def update_signals(
    user_id: str,
    query: str,
    topic: str,
    validation_result: Optional[Dict[str, Any]] = None,
    quality_score: float = 0.0,
    section3_content: Optional[str] = None,
    turn_dir: Optional[Path] = None,
) -> Tuple[ReflectorSignalState, bool, str]:
    """
    Update signal accumulator and check if batch should trigger.

    Args:
        user_id: User identifier
        query: The user's query text
        topic: Extracted topic for this turn
        validation_result: Validation output (decision, confidence, etc.)
        quality_score: Turn quality score
        section3_content: Content of §3 (plan) for boundary detection
        turn_dir: Turn directory path for contradiction detection

    Returns:
        Tuple of (updated_state, should_trigger, trigger_reason)
    """
    state = _load_state(user_id)

    # Increment turn counter
    state.turns_since_last_batch += 1

    # Track recent topics (sliding window)
    if topic:
        state.recent_topics.append(topic)
        if len(state.recent_topics) > MAX_RECENT_TOPICS:
            state.recent_topics = state.recent_topics[-MAX_RECENT_TOPICS:]

    # --- Signal detection ---
    urgency_added = 0.0

    # 1. Topic repetition: same topic 3+ times in window
    topic_words = _extract_topic_words(query)
    overlap_count = _topic_overlap(topic_words, state.recent_topics[:-1])  # exclude current
    if overlap_count >= 3:
        urgency_added += SIGNAL_WEIGHTS["topic_repetition"]
        logger.debug(f"[ReflectorSignal] Topic repetition detected ({overlap_count} overlaps)")

    # 2. User correction patterns
    if CORRECTION_PATTERN.search(query):
        urgency_added += SIGNAL_WEIGHTS["user_correction"]
        logger.debug("[ReflectorSignal] User correction detected")

    # 3. High-confidence research
    if validation_result:
        decision = validation_result.get("decision", "")
        if decision == "APPROVE" and quality_score >= 0.85:
            urgency_added += SIGNAL_WEIGHTS["high_confidence_research"]
            logger.debug("[ReflectorSignal] High-confidence research detected")

    # 4. Knowledge boundary (planner routed to refresh/clarify)
    if section3_content:
        s3_lower = section3_content.lower()
        if "refresh_context" in s3_lower or "clarify" in s3_lower:
            urgency_added += SIGNAL_WEIGHTS["knowledge_boundary"]
            logger.debug("[ReflectorSignal] Knowledge boundary detected")

    # 5. Contradiction detected (freshness analyzer wrote prior_findings.md)
    if turn_dir and (turn_dir / "prior_findings.md").exists():
        urgency_added += SIGNAL_WEIGHTS["contradiction_detected"]
        logger.debug("[ReflectorSignal] Contradiction detected via freshness analyzer")

    state.urgency_score += urgency_added

    # --- Check triggers ---
    should_trigger = False
    trigger_reason = ""

    if state.turns_since_last_batch >= TURN_COUNT_THRESHOLD:
        should_trigger = True
        trigger_reason = "turn_count"
        logger.info(
            f"[ReflectorSignal] Batch triggered by turn count "
            f"({state.turns_since_last_batch} turns)"
        )
    elif state.urgency_score >= URGENCY_THRESHOLD:
        should_trigger = True
        trigger_reason = "signal_urgency"
        logger.info(
            f"[ReflectorSignal] Batch triggered by urgency "
            f"(score={state.urgency_score:.1f})"
        )

    # Save state (always, even if not triggering)
    _save_state(state)

    return state, should_trigger, trigger_reason


def reset_after_batch(user_id: str, current_turn: int) -> None:
    """Reset signal counters after a batch completes."""
    import time

    state = _load_state(user_id)
    state.turns_since_last_batch = 0
    state.urgency_score = 0.0
    state.last_batch_turn = current_turn
    state.last_batch_timestamp = time.time()
    # Keep recent_topics for continuity
    _save_state(state)
    logger.info(f"[ReflectorSignal] Reset after batch (last_turn={current_turn})")
