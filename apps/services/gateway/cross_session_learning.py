"""
Cross-Session Learning - Aggregate insights across all sessions

Tracks patterns across all users to improve extraction quality and adapt
to real-world usage patterns over time.

Author: Panda Team
Created: 2025-11-10
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set, Any
from collections import defaultdict, Counter
from pathlib import Path
import json
import os
import time
import logging

logger = logging.getLogger(__name__)


@dataclass
class QueryPattern:
    """A learned query pattern"""
    pattern: str  # The common pattern (e.g., "find X near Y")
    count: int  # How many times seen
    common_preferences: Dict[str, List[str]]  # Common prefs for this pattern
    common_topics: List[str]  # Common topics
    avg_confidence: float  # Average extraction confidence
    last_seen: float  # Timestamp


@dataclass
class UserCluster:
    """A cluster of similar users"""
    cluster_id: str
    common_preferences: Dict[str, str]  # Most common preferences
    common_topics: List[str]  # Common topics
    session_count: int  # Number of sessions in cluster
    avg_turn_count: float  # Average session length


class CrossSessionLearningStore:
    """Aggregates learning across all sessions"""

    def __init__(self, storage_dir: str = "panda_system_docs/shared_state/learning"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # In-memory aggregates (loaded from disk)
        self.query_patterns: Dict[str, QueryPattern] = {}
        self.user_clusters: Dict[str, UserCluster] = {}
        self.preference_corrections: Dict[str, List[Dict]] = defaultdict(list)
        self.extraction_failures: Counter = Counter()

        self._load()
        logger.info(f"[CrossSessionLearning] Initialized with {len(self.query_patterns)} patterns, {len(self.user_clusters)} clusters")

    def _load(self):
        """Load learning data from disk"""
        patterns_file = self.storage_dir / "query_patterns.json"
        if patterns_file.exists():
            try:
                with open(patterns_file, 'r') as f:
                    data = json.load(f)
                    self.query_patterns = {
                        k: QueryPattern(**v) for k, v in data.items()
                    }
            except Exception as e:
                logger.error(f"[CrossSessionLearning] Error loading patterns: {e}")

        clusters_file = self.storage_dir / "user_clusters.json"
        if clusters_file.exists():
            try:
                with open(clusters_file, 'r') as f:
                    data = json.load(f)
                    self.user_clusters = {
                        k: UserCluster(**v) for k, v in data.items()
                    }
            except Exception as e:
                logger.error(f"[CrossSessionLearning] Error loading clusters: {e}")

        failures_file = self.storage_dir / "extraction_failures.json"
        if failures_file.exists():
            try:
                with open(failures_file, 'r') as f:
                    self.extraction_failures = Counter(json.load(f))
            except Exception as e:
                logger.error(f"[CrossSessionLearning] Error loading failures: {e}")

    def _save(self):
        """Save learning data to disk"""
        try:
            patterns_file = self.storage_dir / "query_patterns.json"
            with open(patterns_file, 'w') as f:
                json.dump(
                    {k: asdict(v) for k, v in self.query_patterns.items()},
                    f,
                    indent=2
                )

            clusters_file = self.storage_dir / "user_clusters.json"
            with open(clusters_file, 'w') as f:
                json.dump(
                    {k: asdict(v) for k, v in self.user_clusters.items()},
                    f,
                    indent=2
                )

            failures_file = self.storage_dir / "extraction_failures.json"
            with open(failures_file, 'w') as f:
                json.dump(dict(self.extraction_failures), f, indent=2)

        except Exception as e:
            logger.error(f"[CrossSessionLearning] Error saving: {e}")

    def record_extraction(
        self,
        user_msg: str,
        extracted_preferences: Dict[str, str],
        extracted_topic: Optional[str],
        confidence: float
    ):
        """Record an extraction for learning"""
        # Identify query pattern
        pattern_key = self._identify_pattern(user_msg)

        if pattern_key not in self.query_patterns:
            self.query_patterns[pattern_key] = QueryPattern(
                pattern=pattern_key,
                count=0,
                common_preferences=defaultdict(list),
                common_topics=[],
                avg_confidence=0.0,
                last_seen=time.time()
            )

        pattern = self.query_patterns[pattern_key]
        pattern.count += 1
        pattern.last_seen = time.time()

        # Update common preferences
        for key, value in extracted_preferences.items():
            if value not in pattern.common_preferences[key]:
                pattern.common_preferences[key].append(value)

        # Update common topics
        if extracted_topic and extracted_topic not in pattern.common_topics:
            pattern.common_topics.append(extracted_topic)

        # Update average confidence
        pattern.avg_confidence = (
            (pattern.avg_confidence * (pattern.count - 1) + confidence) / pattern.count
        )

        # Save periodically
        if pattern.count % 10 == 0:
            self._save()

    def record_extraction_failure(self, user_msg: str, reason: str):
        """Record a failed extraction"""
        pattern_key = self._identify_pattern(user_msg)
        failure_key = f"{pattern_key}:{reason}"
        self.extraction_failures[failure_key] += 1

        # Save periodically
        if sum(self.extraction_failures.values()) % 10 == 0:
            self._save()

    def get_suggested_preferences(
        self,
        user_msg: str,
        user_cluster: Optional[str] = None
    ) -> Dict[str, str]:
        """Get suggested preferences based on learned patterns"""
        pattern_key = self._identify_pattern(user_msg)

        suggestions = {}

        # From query pattern
        if pattern_key in self.query_patterns:
            pattern = self.query_patterns[pattern_key]
            for pref_key, values in pattern.common_preferences.items():
                if values:
                    # Use most common value
                    suggestions[pref_key] = values[0]

        # From user cluster
        if user_cluster and user_cluster in self.user_clusters:
            cluster = self.user_clusters[user_cluster]
            for pref_key, value in cluster.common_preferences.items():
                if pref_key not in suggestions:
                    suggestions[pref_key] = value

        return suggestions

    def cluster_user(self, session_context: 'LiveSessionContext') -> str:
        """Assign user to a behavioral cluster"""
        # Simple clustering based on topic and preferences
        topic = session_context.current_topic or "general"
        prefs_signature = "_".join(sorted(session_context.preferences.keys()))

        cluster_key = f"{topic[:20]}_{prefs_signature[:20]}"

        if cluster_key not in self.user_clusters:
            self.user_clusters[cluster_key] = UserCluster(
                cluster_id=cluster_key,
                common_preferences={},
                common_topics=[],
                session_count=0,
                avg_turn_count=0.0
            )

        cluster = self.user_clusters[cluster_key]
        cluster.session_count += 1

        # Update cluster stats
        cluster.avg_turn_count = (
            (cluster.avg_turn_count * (cluster.session_count - 1) + session_context.turn_count)
            / cluster.session_count
        )

        # Update common preferences
        for key, value in session_context.preferences.items():
            cluster.common_preferences[key] = value

        # Update common topics
        if topic and topic not in cluster.common_topics:
            cluster.common_topics.append(topic)

        self._save()

        return cluster_key

    def _identify_pattern(self, user_msg: str) -> str:
        """Identify query pattern from message"""
        import re

        msg_lower = user_msg.lower()

        # Common patterns
        if "find" in msg_lower and "near" in msg_lower:
            return "find_X_near_Y"
        elif re.search(r"(?:buy|purchase|shop)", msg_lower):
            return "shopping"
        elif re.search(r"(?:how to|care|feed|maintain)", msg_lower):
            return "care_instructions"
        elif "what is" in msg_lower or "what are" in msg_lower:
            return "information_seeking"
        elif "compare" in msg_lower or "vs" in msg_lower:
            return "comparison"
        else:
            return "general"

    def get_statistics(self) -> Dict:
        """Get learning statistics"""
        return {
            "total_patterns": len(self.query_patterns),
            "total_clusters": len(self.user_clusters),
            "total_failures": sum(self.extraction_failures.values()),
            "most_common_pattern": max(
                self.query_patterns.items(),
                key=lambda x: x[1].count,
                default=(None, None)
            )[0] if self.query_patterns else None
        }


# Global learning store
_learning_store: Optional[CrossSessionLearningStore] = None


def get_learning_store() -> CrossSessionLearningStore:
    """Get or create global learning store"""
    global _learning_store
    if _learning_store is None:
        _learning_store = CrossSessionLearningStore()
    return _learning_store
