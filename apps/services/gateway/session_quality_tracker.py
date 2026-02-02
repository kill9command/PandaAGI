"""
Session Quality Tracker

Tracks quality across conversation turns and detects user satisfaction.
Integrates with satisfaction_detector.py for pattern recognition.
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .satisfaction_detector import UserSatisfactionDetector


class SessionQualityTracker:
    """Tracks quality metrics across conversation turns."""

    def __init__(self, db_path: str = "panda_system_docs/shared_state/session_quality.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._ensure_tables()
        self.detector = UserSatisfactionDetector()

    def _ensure_tables(self):
        """Create session_turns table if it doesn't exist."""
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS session_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_id INTEGER NOT NULL,
                    user_query TEXT NOT NULL,
                    intent TEXT,
                    response_quality REAL DEFAULT 0.5,
                    claims_used TEXT,  -- JSON array of claim IDs
                    intent_fulfilled BOOLEAN DEFAULT 1,
                    user_satisfaction REAL DEFAULT NULL,
                    satisfaction_reason TEXT DEFAULT NULL,
                    cache_hit BOOLEAN DEFAULT 0,
                    timestamp TEXT NOT NULL,
                    UNIQUE(session_id, turn_id)
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_turns_session
                ON session_turns(session_id)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_turns_satisfaction
                ON session_turns(user_satisfaction)
            """)
            self._conn.commit()

    def record_turn(
        self,
        session_id: str,
        turn_id: int,
        user_query: str,
        intent: Optional[str] = None,
        response_quality: float = 0.5,
        claims_used: Optional[List[str]] = None,
        intent_fulfilled: bool = True,
        cache_hit: bool = False,
    ) -> None:
        """Record a conversation turn."""
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO session_turns (
                    session_id, turn_id, user_query, intent, response_quality,
                    claims_used, intent_fulfilled, cache_hit, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    turn_id,
                    user_query,
                    intent,
                    response_quality,
                    json.dumps(claims_used or []),
                    int(intent_fulfilled),
                    int(cache_hit),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()

    def detect_satisfaction_from_follow_up(
        self,
        session_id: str,
        current_turn_id: int,
        current_query: str,
        current_intent: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Detect user satisfaction from follow-up query.
        Updates the previous turn's satisfaction score.

        Returns:
            Satisfaction analysis dict or None if no previous turn
        """
        # Get previous turn
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT turn_id, user_query, intent, response_quality, claims_used
                FROM session_turns
                WHERE session_id = ? AND turn_id < ?
                ORDER BY turn_id DESC
                LIMIT 1
                """,
                (session_id, current_turn_id),
            )
            row = cursor.fetchone()

        if not row:
            return None  # First turn in session

        prev_turn_id, prev_query, prev_intent, prev_quality, prev_claims_json = row
        prev_claims = json.loads(prev_claims_json) if prev_claims_json else []

        # Analyze follow-up
        satisfaction = self.detector.analyze_follow_up(
            original_query=prev_query,
            original_intent=prev_intent or "unknown",
            response="",  # We don't need full response text
            follow_up_query=current_query,
            follow_up_intent=current_intent,
        )

        # Convert satisfaction to score
        if satisfaction["satisfied"] is True:
            satisfaction_score = 0.9
        elif satisfaction["satisfied"] is False:
            satisfaction_score = 0.1
        else:
            satisfaction_score = 0.5  # Neutral

        # Update previous turn with satisfaction
        with self._lock:
            self._conn.execute(
                """
                UPDATE session_turns
                SET user_satisfaction = ?,
                    satisfaction_reason = ?
                WHERE session_id = ? AND turn_id = ?
                """,
                (
                    satisfaction_score,
                    satisfaction["reason"],
                    session_id,
                    prev_turn_id,
                ),
            )
            self._conn.commit()

        # Return satisfaction analysis with previous turn info
        return {
            **satisfaction,
            "previous_turn_id": prev_turn_id,
            "previous_claims": prev_claims,
            "satisfaction_score": satisfaction_score,
        }

    def get_session_turns(
        self, session_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent turns for a session."""
        cursor = self._conn.execute(
            """
            SELECT turn_id, user_query, intent, response_quality,
                   claims_used, intent_fulfilled, user_satisfaction,
                   satisfaction_reason, cache_hit, timestamp
            FROM session_turns
            WHERE session_id = ?
            ORDER BY turn_id DESC
            LIMIT ?
            """,
            (session_id, limit),
        )

        turns = []
        for row in cursor.fetchall():
            turns.append(
                {
                    "turn_id": row[0],
                    "user_query": row[1],
                    "intent": row[2],
                    "response_quality": row[3],
                    "claims_used": json.loads(row[4]) if row[4] else [],
                    "intent_fulfilled": bool(row[5]),
                    "user_satisfaction": row[6],
                    "satisfaction_reason": row[7],
                    "cache_hit": bool(row[8]),
                    "timestamp": row[9],
                }
            )
        return list(reversed(turns))  # Return in chronological order

    def analyze_session_quality(self, session_id: str) -> Dict[str, Any]:
        """Analyze overall quality for a session."""
        turns = self.get_session_turns(session_id, limit=100)

        if not turns:
            return {
                "aggregate_quality": 0.5,
                "quality_trend": "stable",
                "satisfaction_rate": 0.5,
                "issues": [],
            }

        return self.detector.analyze_session_quality(turns)

    def update_claim_quality_from_feedback(
        self,
        claim_id: str,
        satisfaction_score: float,
        claim_db_path: str = "panda_system_docs/shared_state/claims.db",
    ) -> None:
        """Update claim quality based on user feedback."""
        conn = sqlite3.connect(claim_db_path)
        cursor = conn.cursor()

        try:
            # Update claim with user feedback
            cursor.execute(
                """
                UPDATE claims
                SET user_feedback_score = ?,
                    times_reused = times_reused + 1,
                    times_helpful = times_helpful + CASE WHEN ? > 0.6 THEN 1 ELSE 0 END,
                    last_used_at = ?
                WHERE claim_id = ?
                """,
                (
                    satisfaction_score,
                    satisfaction_score,
                    datetime.now(timezone.utc).isoformat(),
                    claim_id,
                ),
            )

            # If quality drops too low, mark for deprecation
            cursor.execute(
                """
                UPDATE claims
                SET deprecated = 1,
                    deprecation_reason = 'Low user satisfaction'
                WHERE claim_id = ? AND
                      (intent_alignment * 0.4 + evidence_strength * 0.3 + ? * 0.3) < 0.3
                """,
                (claim_id, satisfaction_score),
            )

            conn.commit()
        finally:
            conn.close()

    def propagate_feedback_to_claims(self, session_id: str) -> int:
        """
        Propagate user feedback to claims used in dissatisfied turns.

        Returns:
            Number of claims updated
        """
        turns = self.get_session_turns(session_id, limit=10)
        updated_count = 0

        for turn in turns:
            if turn["user_satisfaction"] is not None and turn["user_satisfaction"] < 0.4:
                # User was dissatisfied - update all claims from that turn
                for claim_id in turn["claims_used"]:
                    try:
                        self.update_claim_quality_from_feedback(
                            claim_id, turn["user_satisfaction"]
                        )
                        updated_count += 1
                    except Exception as e:
                        # Log error but continue processing other claims
                        print(f"Error updating claim {claim_id}: {e}")

        return updated_count

    def close(self):
        """Close database connection."""
        with self._lock:
            self._conn.close()
