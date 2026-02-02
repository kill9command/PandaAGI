"""
lib/gateway/performance_tracker.py

Performance tracking for self-learning system.
Records turn outcomes to SQLite for pattern detection and lesson effectiveness tracking.

Document IO:
- Input: metadata.json (from Save phase)
- Output: performance_index.db (turn_outcomes, lesson_stats tables)

Created: 2025-12-11
"""

import sqlite3
import logging
import time
import threading
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Thread lock for singleton initialization
_tracker_lock = threading.Lock()

# Default database location
DEFAULT_DB_PATH = Path("panda_system_docs/performance_index.db")


@dataclass
class TurnOutcome:
    """Represents a single turn's outcome for learning."""
    turn_number: int
    session_id: str
    timestamp: float

    # Classification
    intent: Optional[str] = None
    context_tokens: int = 0

    # Strategy
    strategy_applied: Optional[str] = None
    lesson_consulted: Optional[str] = None

    # Outcome
    validation_decision: str = "APPROVE"  # APPROVE, REVISE, FAIL, LEARN
    revision_count: int = 0
    final_confidence: float = 0.0

    # Learning
    pattern_detected: Optional[str] = None
    lesson_extracted: Optional[str] = None


@dataclass
class LessonStats:
    """Statistics for a single lesson."""
    lesson_id: str
    times_consulted: int = 0
    times_successful: int = 0
    success_rate: float = 0.0
    avg_revision_reduction: float = 0.0
    last_used: float = 0.0
    status: str = "active"  # active, testing, deprecated


class PerformanceTracker:
    """
    Tracks turn outcomes and lesson effectiveness.

    Document IO Pattern:
    - Input: TurnOutcome dataclass (populated from metadata.json)
    - Output: SQLite database with queryable history
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with self._connect() as conn:
            # Enable WAL mode for better concurrent access
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                -- Track outcomes per turn for pattern analysis
                CREATE TABLE IF NOT EXISTS turn_outcomes (
                    turn_number INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,

                    -- Classification
                    intent TEXT,
                    context_tokens INTEGER DEFAULT 0,

                    -- Strategy
                    strategy_applied TEXT,
                    lesson_consulted TEXT,

                    -- Outcome
                    validation_decision TEXT DEFAULT 'APPROVE',
                    revision_count INTEGER DEFAULT 0,
                    final_confidence REAL DEFAULT 0.0,

                    -- Learning
                    pattern_detected TEXT,
                    lesson_extracted TEXT
                );

                -- Track lesson effectiveness over time
                CREATE TABLE IF NOT EXISTS lesson_stats (
                    lesson_id TEXT PRIMARY KEY,
                    times_consulted INTEGER DEFAULT 0,
                    times_successful INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 0.0,
                    avg_revision_reduction REAL DEFAULT 0.0,
                    last_used REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'active'
                );

                -- Indexes for fast pattern matching
                CREATE INDEX IF NOT EXISTS idx_outcomes_intent
                    ON turn_outcomes(intent, validation_decision);
                CREATE INDEX IF NOT EXISTS idx_outcomes_recent
                    ON turn_outcomes(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_outcomes_session
                    ON turn_outcomes(session_id, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_outcomes_strategy
                    ON turn_outcomes(strategy_applied, validation_decision);
            """)
            logger.info(f"[PerformanceTracker] Initialized database at {self.db_path}")

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ==================== Turn Outcome Recording ====================

    def record_outcome(self, outcome: TurnOutcome) -> None:
        """
        Record a turn outcome to the database.

        Input Document: TurnOutcome (from metadata.json learning fields)
        Output: Row in turn_outcomes table
        """
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO turn_outcomes (
                    turn_number, session_id, timestamp,
                    intent, context_tokens,
                    strategy_applied, lesson_consulted,
                    validation_decision, revision_count, final_confidence,
                    pattern_detected, lesson_extracted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                outcome.turn_number,
                outcome.session_id,
                outcome.timestamp,
                outcome.intent,
                outcome.context_tokens,
                outcome.strategy_applied,
                outcome.lesson_consulted,
                outcome.validation_decision,
                outcome.revision_count,
                outcome.final_confidence,
                outcome.pattern_detected,
                outcome.lesson_extracted,
            ))

        logger.info(
            f"[PerformanceTracker] Recorded turn {outcome.turn_number}: "
            f"decision={outcome.validation_decision}, revisions={outcome.revision_count}"
        )

        # Update lesson stats if a lesson was consulted
        if outcome.lesson_consulted:
            self._update_lesson_stats(
                lesson_id=outcome.lesson_consulted,
                success=(outcome.validation_decision in ["APPROVE", "LEARN"]),
                revision_count=outcome.revision_count
            )

    def record_from_metadata(self, metadata: Dict[str, Any]) -> None:
        """
        Record outcome from metadata.json format.

        Input Document: metadata.json with learning fields
        """
        learning = metadata.get("learning") or {}

        outcome = TurnOutcome(
            turn_number=metadata.get("turn_number", 0),
            session_id=metadata.get("session_id", "unknown"),
            timestamp=metadata.get("timestamp", time.time()),
            intent=metadata.get("intent"),
            context_tokens=learning.get("context_tokens", 0),
            strategy_applied=learning.get("strategy_applied"),
            lesson_consulted=learning.get("lesson_consulted"),
            validation_decision=learning.get("validation_decision", "APPROVE"),
            revision_count=learning.get("revision_count", 0),
            final_confidence=metadata.get("response_quality", 0.0),
            pattern_detected=learning.get("pattern_detected"),
            lesson_extracted=learning.get("lesson_extracted"),
        )

        self.record_outcome(outcome)

    # ==================== Lesson Stats ====================

    def _update_lesson_stats(
        self,
        lesson_id: str,
        success: bool,
        revision_count: int
    ) -> None:
        """Update lesson effectiveness statistics."""
        with self._connect() as conn:
            # Get current stats
            row = conn.execute(
                "SELECT * FROM lesson_stats WHERE lesson_id = ?",
                (lesson_id,)
            ).fetchone()

            if row:
                times_consulted = row["times_consulted"] + 1
                times_successful = row["times_successful"] + (1 if success else 0)
                success_rate = times_successful / times_consulted

                conn.execute("""
                    UPDATE lesson_stats SET
                        times_consulted = ?,
                        times_successful = ?,
                        success_rate = ?,
                        last_used = ?
                    WHERE lesson_id = ?
                """, (
                    times_consulted,
                    times_successful,
                    success_rate,
                    time.time(),
                    lesson_id,
                ))
            else:
                # Create new stats entry
                conn.execute("""
                    INSERT INTO lesson_stats (
                        lesson_id, times_consulted, times_successful,
                        success_rate, last_used, status
                    ) VALUES (?, 1, ?, ?, ?, 'active')
                """, (
                    lesson_id,
                    1 if success else 0,
                    1.0 if success else 0.0,
                    time.time(),
                ))

        logger.debug(f"[PerformanceTracker] Updated stats for lesson: {lesson_id}")

    def get_lesson_stats(self, lesson_id: str) -> Optional[LessonStats]:
        """Get statistics for a specific lesson."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM lesson_stats WHERE lesson_id = ?",
                (lesson_id,)
            ).fetchone()

            if row:
                return LessonStats(
                    lesson_id=row["lesson_id"],
                    times_consulted=row["times_consulted"],
                    times_successful=row["times_successful"],
                    success_rate=row["success_rate"],
                    avg_revision_reduction=row["avg_revision_reduction"],
                    last_used=row["last_used"],
                    status=row["status"],
                )
            return None

    def get_all_lesson_stats(self) -> List[LessonStats]:
        """Get statistics for all lessons."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM lesson_stats ORDER BY success_rate DESC"
            ).fetchall()

            return [
                LessonStats(
                    lesson_id=row["lesson_id"],
                    times_consulted=row["times_consulted"],
                    times_successful=row["times_successful"],
                    success_rate=row["success_rate"],
                    avg_revision_reduction=row["avg_revision_reduction"],
                    last_used=row["last_used"],
                    status=row["status"],
                )
                for row in rows
            ]

    # ==================== Pattern Queries ====================

    def query_recent_failures(
        self,
        intent: str,
        limit: int = 10,
        hours: float = 24.0
    ) -> List[TurnOutcome]:
        """
        Query recent failures for a specific intent.
        Used for recurring failure pattern detection.
        """
        cutoff = time.time() - (hours * 3600)

        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM turn_outcomes
                WHERE intent = ?
                  AND validation_decision IN ('FAIL', 'REVISE')
                  AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (intent, cutoff, limit)).fetchall()

            return [self._row_to_outcome(row) for row in rows]

    def query_strategy_effectiveness(
        self,
        strategy: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Query effectiveness of a specific strategy.
        Returns success rate and average revision count.
        """
        with self._connect() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN validation_decision IN ('APPROVE', 'LEARN') THEN 1 ELSE 0 END) as successes,
                    AVG(revision_count) as avg_revisions
                FROM turn_outcomes
                WHERE strategy_applied = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (strategy, limit)).fetchone()

            if row and row["total"] > 0:
                return {
                    "strategy": strategy,
                    "total_uses": row["total"],
                    "success_rate": row["successes"] / row["total"],
                    "avg_revisions": row["avg_revisions"] or 0.0,
                }
            return {
                "strategy": strategy,
                "total_uses": 0,
                "success_rate": 0.0,
                "avg_revisions": 0.0,
            }

    def query_intent_stats(self, intent: str, hours: float = 168.0) -> Dict[str, Any]:
        """
        Query statistics for a specific intent over time window.
        Default: last 7 days (168 hours).
        """
        cutoff = time.time() - (hours * 3600)

        with self._connect() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN validation_decision IN ('APPROVE', 'LEARN') THEN 1 ELSE 0 END) as successes,
                    AVG(revision_count) as avg_revisions,
                    AVG(context_tokens) as avg_context_tokens
                FROM turn_outcomes
                WHERE intent = ?
                  AND timestamp > ?
            """, (intent, cutoff)).fetchone()

            if row and row["total"] > 0:
                return {
                    "intent": intent,
                    "total_turns": row["total"],
                    "success_rate": row["successes"] / row["total"],
                    "avg_revisions": row["avg_revisions"] or 0.0,
                    "avg_context_tokens": row["avg_context_tokens"] or 0,
                }
            return {
                "intent": intent,
                "total_turns": 0,
                "success_rate": 0.0,
                "avg_revisions": 0.0,
                "avg_context_tokens": 0,
            }

    def _row_to_outcome(self, row: sqlite3.Row) -> TurnOutcome:
        """Convert database row to TurnOutcome."""
        return TurnOutcome(
            turn_number=row["turn_number"],
            session_id=row["session_id"],
            timestamp=row["timestamp"],
            intent=row["intent"],
            context_tokens=row["context_tokens"],
            strategy_applied=row["strategy_applied"],
            lesson_consulted=row["lesson_consulted"],
            validation_decision=row["validation_decision"],
            revision_count=row["revision_count"],
            final_confidence=row["final_confidence"],
            pattern_detected=row["pattern_detected"],
            lesson_extracted=row["lesson_extracted"],
        )

    # ==================== Deprecation ====================

    def deprecate_low_performers(self, min_uses: int = 10, threshold: float = 0.4) -> List[str]:
        """
        Deprecate lessons with success rate below threshold after min_uses.
        Returns list of deprecated lesson IDs.
        """
        deprecated = []

        with self._connect() as conn:
            rows = conn.execute("""
                SELECT lesson_id FROM lesson_stats
                WHERE times_consulted >= ?
                  AND success_rate < ?
                  AND status = 'active'
            """, (min_uses, threshold)).fetchall()

            for row in rows:
                lesson_id = row["lesson_id"]
                conn.execute(
                    "UPDATE lesson_stats SET status = 'deprecated' WHERE lesson_id = ?",
                    (lesson_id,)
                )
                deprecated.append(lesson_id)
                logger.warning(f"[PerformanceTracker] Deprecated low-performing lesson: {lesson_id}")

        return deprecated


# Global singleton
_tracker: Optional[PerformanceTracker] = None


def get_performance_tracker() -> PerformanceTracker:
    """Get global performance tracker instance (thread-safe)."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            # Double-check after acquiring lock
            if _tracker is None:
                _tracker = PerformanceTracker()
    return _tracker
