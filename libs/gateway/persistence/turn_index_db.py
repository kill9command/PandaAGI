"""
SQLite-based turn index - A REBUILDABLE CACHE over the filesystem.

ARCHITECTURAL PRINCIPLE:
    The filesystem (markdown files) is the SOURCE OF TRUTH.
    This database is a COMPUTED INDEX that can be rebuilt at any time.

    If the database gets corrupted or out of sync, just call rebuild_from_filesystem().

Path Computation:
    Paths are NOT stored - they're computed from user_id and turn_number:

    def get_turn_path(user_id: str, turn_number: int) -> Path:
        return OBSIDIAN_MEMORY / "Users" / user_id / "turns" / f"turn_{turn_number:06d}"

Schema:
    - turn_number: Primary key
    - user_id: User identifier (for filtering)
    - session_id: Session identifier (for filtering)
    - timestamp: Unix timestamp (for ordering)
    - topic: Extracted from context.md (for search)
    - intent: Query type (for filtering)
    - keywords: JSON array (for search)
    - validation_outcome: APPROVE, RETRY, REVISE, FAIL
    - quality_score: 0.0-1.0
    - (other metadata fields)
"""

import sqlite3
import json
import logging
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
import threading

logger = logging.getLogger(__name__)

# Thread-local storage for connections
_local = threading.local()

# Schema version for migrations
SCHEMA_VERSION = 4  # v4: Removed turn_dir column (paths are computed)

# Base paths
OBSIDIAN_MEMORY = Path("panda_system_docs/obsidian_memory")
USERS_DIR = OBSIDIAN_MEMORY / "Users"


def get_turn_path(user_id: str, turn_number: int) -> Path:
    """
    Compute the path to a turn directory.

    This is the ONLY place turn paths are defined - no storage needed.
    """
    return USERS_DIR / user_id / "turns" / f"turn_{turn_number:06d}"


@dataclass
class TurnIndexEntry:
    """A single entry in the turn index."""
    turn_number: int
    user_id: str
    session_id: str
    timestamp: float
    topic: str = ""
    intent: str = ""
    keywords: List[str] = field(default_factory=list)
    # Validation and quality tracking
    validation_outcome: str = ""  # APPROVE, RETRY, REVISE, FAIL
    strategy_summary: str = ""
    quality_score: float = 0.0
    user_feedback_status: str = ""  # rejected, accepted, neutral
    feedback_confidence: float = 0.0
    rejection_detected_in: str = ""
    goals_json: str = "[]"

    @property
    def turn_dir(self) -> Path:
        """Compute the turn directory path (not stored)."""
        return get_turn_path(self.user_id, self.turn_number)

    @property
    def context_path(self) -> Path:
        """Path to context.md file."""
        return self.turn_dir / "context.md"


class TurnIndexDB:
    """
    SQLite-based turn index - a rebuildable cache over the filesystem.

    The filesystem is the source of truth. This index can be rebuilt at any time
    by scanning the turn directories and extracting metadata from context.md files.
    """

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or Path("panda_system_docs/turn_index.db")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(_local, 'connection') or _local.connection is None:
            _local.connection = sqlite3.connect(str(self.db_path))
            _local.connection.row_factory = sqlite3.Row
        return _local.connection

    def _init_db(self):
        """Initialize the database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = self._get_connection()

        # Check if we need to migrate from old schema
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='turns'")
        table_exists = cursor.fetchone() is not None

        if table_exists:
            # Check if old turn_dir column exists
            cursor = conn.execute("PRAGMA table_info(turns)")
            columns = {row[1] for row in cursor.fetchall()}

            if "turn_dir" in columns:
                # Migrate: drop and recreate table
                logger.info("[TurnIndexDB] Migrating to v4 schema (removing turn_dir column)")
                conn.execute("DROP TABLE IF EXISTS turns_old")
                conn.execute("ALTER TABLE turns RENAME TO turns_old")
                self._create_tables(conn)

                # Migrate data (excluding turn_dir)
                conn.execute("""
                    INSERT INTO turns (
                        turn_number, user_id, session_id, timestamp, topic, intent, keywords,
                        validation_outcome, strategy_summary, quality_score,
                        user_feedback_status, feedback_confidence, rejection_detected_in, goals_json
                    )
                    SELECT
                        turn_number,
                        COALESCE(user_id, 'default'),
                        session_id,
                        timestamp,
                        topic,
                        intent,
                        keywords,
                        COALESCE(validation_outcome, ''),
                        COALESCE(strategy_summary, ''),
                        COALESCE(quality_score, 0.0),
                        COALESCE(user_feedback_status, ''),
                        COALESCE(feedback_confidence, 0.0),
                        COALESCE(rejection_detected_in, ''),
                        COALESCE(goals_json, '[]')
                    FROM turns_old
                """)
                conn.execute("DROP TABLE turns_old")
                conn.commit()
                logger.info("[TurnIndexDB] Migration complete")
        else:
            self._create_tables(conn)

        conn.commit()
        logger.debug(f"[TurnIndexDB] Initialized at {self.db_path}")

    def _create_tables(self, conn: sqlite3.Connection):
        """Create the database tables."""
        # Main turns table - NO turn_dir column (paths are computed)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS turns (
                turn_number INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                session_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                topic TEXT DEFAULT '',
                intent TEXT DEFAULT '',
                keywords TEXT DEFAULT '[]',
                validation_outcome TEXT DEFAULT '',
                strategy_summary TEXT DEFAULT '',
                quality_score REAL DEFAULT 0.0,
                user_feedback_status TEXT DEFAULT '',
                feedback_confidence REAL DEFAULT 0.0,
                rejection_detected_in TEXT DEFAULT '',
                goals_json TEXT DEFAULT '[]'
            )
        """)

        # Indexes for fast queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON turns(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON turns(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_session ON turns(user_id, session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON turns(timestamp DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_timestamp ON turns(user_id, timestamp DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_validation ON turns(validation_outcome)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_topic ON turns(topic)")  # New: for topic search

        # Schema version tracking
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_info (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute(
            "INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),)
        )

    # =========================================================================
    # REBUILD FROM FILESYSTEM (Source of Truth)
    # =========================================================================

    def rebuild_from_filesystem(self, user_id: str = None) -> int:
        """
        Rebuild the index by scanning the filesystem.

        This is the KEY METHOD that treats the filesystem as source of truth.
        Call this on startup or whenever the database might be out of sync.

        Args:
            user_id: Rebuild only this user's turns (or all if None)

        Returns:
            Number of turns indexed
        """
        conn = self._get_connection()

        # Clear existing entries for this user (or all)
        if user_id:
            conn.execute("DELETE FROM turns WHERE user_id = ?", (user_id,))
        else:
            conn.execute("DELETE FROM turns")

        indexed_count = 0

        # Determine which user directories to scan
        if user_id:
            user_dirs = [USERS_DIR / user_id]
        else:
            user_dirs = [d for d in USERS_DIR.iterdir() if d.is_dir()]

        for user_dir in user_dirs:
            turns_dir = user_dir / "turns"
            if not turns_dir.exists():
                continue

            current_user_id = user_dir.name

            for turn_dir in turns_dir.iterdir():
                if not turn_dir.is_dir() or not turn_dir.name.startswith("turn_"):
                    continue

                try:
                    turn_number = int(turn_dir.name.replace("turn_", ""))
                except ValueError:
                    continue

                # Extract metadata from context.md
                metadata = self._extract_metadata_from_turn(turn_dir, current_user_id)
                if metadata:
                    self._index_turn_internal(conn, turn_number, current_user_id, metadata)
                    indexed_count += 1

        conn.commit()
        logger.info(f"[TurnIndexDB] Rebuilt index from filesystem: {indexed_count} turns indexed")
        return indexed_count

    def _extract_metadata_from_turn(self, turn_dir: Path, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Extract indexable metadata from a turn's context.md file.

        This is where we parse the markdown to extract:
        - User query (topic)
        - Intent
        - Timestamp
        - Validation outcome
        - etc.
        """
        context_file = turn_dir / "context.md"
        if not context_file.exists():
            return None

        try:
            content = context_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"[TurnIndexDB] Failed to read {context_file}: {e}")
            return None

        metadata = {
            "session_id": user_id,  # Default to user_id
            "timestamp": os.path.getmtime(context_file),
            "topic": "",
            "intent": "",
            "keywords": [],
            "validation_outcome": "",
            "quality_score": 0.0,
        }

        # Extract session from header
        session_match = re.search(r'\*\*Session:\*\*\s*(\S+)', content)
        if session_match:
            metadata["session_id"] = session_match.group(1)

        # Extract user query from "## 0. User Query" section
        if "## 0. User Query" in content:
            query_section = content.split("## 0. User Query")[1].split("##")[0]
            lines = [l.strip() for l in query_section.strip().split("\n") if l.strip() and not l.startswith("---")]
            if lines:
                metadata["topic"] = lines[0][:200]  # First non-empty line, truncated

        # Extract intent/query type
        intent_match = re.search(r'\*\*Query Type:\*\*\s*(\w+)', content)
        if intent_match:
            metadata["intent"] = intent_match.group(1)

        # Extract validation outcome
        validation_match = re.search(r'\*\*Validation Result:\*\*\s*(\w+)', content)
        if validation_match:
            metadata["validation_outcome"] = validation_match.group(1)

        # Extract confidence as quality score
        confidence_match = re.search(r'\*\*Confidence:\*\*\s*([\d.]+)', content)
        if confidence_match:
            try:
                metadata["quality_score"] = float(confidence_match.group(1))
            except ValueError:
                pass

        return metadata

    def _index_turn_internal(self, conn: sqlite3.Connection, turn_number: int, user_id: str, metadata: Dict[str, Any]):
        """Internal method to insert a turn into the index."""
        conn.execute("""
            INSERT OR REPLACE INTO turns
            (turn_number, user_id, session_id, timestamp, topic, intent, keywords,
             validation_outcome, quality_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            turn_number,
            user_id,
            metadata.get("session_id", user_id),
            metadata.get("timestamp", 0.0),
            metadata.get("topic", ""),
            metadata.get("intent", ""),
            json.dumps(metadata.get("keywords", [])),
            metadata.get("validation_outcome", ""),
            metadata.get("quality_score", 0.0),
        ))

    # =========================================================================
    # VALIDATION (Check if index matches filesystem)
    # =========================================================================

    def validate_index(self, user_id: str = None) -> Dict[str, Any]:
        """
        Validate that the index matches the filesystem.

        Only counts turns that have a context.md file (valid/complete turns).
        Incomplete turns (no context.md) are skipped.

        Returns:
            Dict with 'valid' bool, 'missing' list, 'orphaned' list
        """
        conn = self._get_connection()

        # Get turns from database
        if user_id:
            cursor = conn.execute("SELECT turn_number, user_id FROM turns WHERE user_id = ?", (user_id,))
        else:
            cursor = conn.execute("SELECT turn_number, user_id FROM turns")

        db_turns = {(row["turn_number"], row["user_id"]) for row in cursor}

        # Get VALID turns from filesystem (must have context.md)
        fs_turns = set()
        incomplete_turns = []
        user_dirs = [USERS_DIR / user_id] if user_id else [d for d in USERS_DIR.iterdir() if d.is_dir()]

        for user_dir in user_dirs:
            turns_dir = user_dir / "turns"
            if not turns_dir.exists():
                continue

            current_user_id = user_dir.name
            for turn_dir in turns_dir.iterdir():
                if turn_dir.is_dir() and turn_dir.name.startswith("turn_"):
                    try:
                        turn_num = int(turn_dir.name.replace("turn_", ""))
                        # Only count as valid if context.md exists
                        if (turn_dir / "context.md").exists():
                            fs_turns.add((turn_num, current_user_id))
                        else:
                            incomplete_turns.append((turn_num, current_user_id))
                    except ValueError:
                        pass

        missing = fs_turns - db_turns  # Valid turns in filesystem but not in DB
        orphaned = db_turns - fs_turns  # In DB but not in filesystem (or incomplete)

        return {
            "valid": len(missing) == 0 and len(orphaned) == 0,
            "db_count": len(db_turns),
            "fs_count": len(fs_turns),
            "incomplete_count": len(incomplete_turns),
            "missing": list(missing),
            "orphaned": list(orphaned),
        }

    def sync_if_needed(self, user_id: str = None) -> bool:
        """
        Check index validity and rebuild if out of sync.

        Returns:
            True if sync was needed, False if already valid
        """
        validation = self.validate_index(user_id)

        if not validation["valid"]:
            logger.warning(
                f"[TurnIndexDB] Index out of sync - "
                f"missing: {len(validation['missing'])}, orphaned: {len(validation['orphaned'])}. "
                f"Rebuilding..."
            )
            self.rebuild_from_filesystem(user_id)
            return True

        return False

    # =========================================================================
    # INDEX ON WRITE (Keep index updated as turns are saved)
    # =========================================================================

    def index_turn(
        self,
        turn_number: int,
        user_id: str,
        session_id: str,
        timestamp: float,
        topic: str = "",
        intent: str = "",
        keywords: List[str] = None,
        validation_outcome: str = "",
        strategy_summary: str = "",
        quality_score: float = 0.0,
        user_feedback_status: str = "",
        feedback_confidence: float = 0.0,
        rejection_detected_in: str = "",
        goals: List[Dict[str, Any]] = None
    ):
        """
        Add or update a turn in the index.

        Called when a new turn is saved to the filesystem.
        """
        conn = self._get_connection()
        goals_json = json.dumps(goals or [])

        conn.execute("""
            INSERT OR REPLACE INTO turns
            (turn_number, user_id, session_id, timestamp, topic, intent, keywords,
             validation_outcome, strategy_summary, quality_score, user_feedback_status,
             feedback_confidence, rejection_detected_in, goals_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            turn_number,
            user_id,
            session_id,
            timestamp,
            topic,
            intent,
            json.dumps(keywords or []),
            validation_outcome,
            strategy_summary,
            quality_score,
            user_feedback_status,
            feedback_confidence,
            rejection_detected_in,
            goals_json
        ))
        conn.commit()

        logger.debug(f"[TurnIndexDB] Indexed turn {turn_number} for user {user_id}")

    def delete_turn(self, turn_number: int):
        """Remove a turn from the index."""
        conn = self._get_connection()
        conn.execute("DELETE FROM turns WHERE turn_number = ?", (turn_number,))
        conn.commit()

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

    def _row_to_entry(self, row: sqlite3.Row) -> TurnIndexEntry:
        """Convert a database row to TurnIndexEntry."""
        keywords = json.loads(row["keywords"]) if row["keywords"] else []
        return TurnIndexEntry(
            turn_number=row["turn_number"],
            user_id=row["user_id"],
            session_id=row["session_id"],
            timestamp=row["timestamp"],
            topic=row["topic"] or "",
            intent=row["intent"] or "",
            keywords=keywords,
            validation_outcome=row["validation_outcome"] or "",
            strategy_summary=row["strategy_summary"] if "strategy_summary" in row.keys() else "",
            quality_score=row["quality_score"] if "quality_score" in row.keys() else 0.0,
            user_feedback_status=row["user_feedback_status"] if "user_feedback_status" in row.keys() else "",
            feedback_confidence=row["feedback_confidence"] if "feedback_confidence" in row.keys() else 0.0,
            rejection_detected_in=row["rejection_detected_in"] if "rejection_detected_in" in row.keys() else "",
            goals_json=row["goals_json"] if "goals_json" in row.keys() else "[]"
        )

    def get_user_turns(
        self,
        user_id: str,
        limit: int = 100,
        session_id: str = None
    ) -> List[TurnIndexEntry]:
        """
        Get turns for a user, ordered by recency.

        Args:
            user_id: User identifier
            limit: Maximum number of results
            session_id: Optional session filter

        Returns:
            List of TurnIndexEntry sorted by timestamp (newest first)
        """
        conn = self._get_connection()

        if session_id:
            cursor = conn.execute("""
                SELECT * FROM turns
                WHERE user_id = ? AND session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, session_id, limit))
        else:
            cursor = conn.execute("""
                SELECT * FROM turns
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, limit))

        return [self._row_to_entry(row) for row in cursor]

    def get_session_turns(
        self,
        session_id: str,
        limit: int = 100,
        since_timestamp: float = None
    ) -> List[TurnIndexEntry]:
        """Get all turns for a session, ordered by recency."""
        conn = self._get_connection()

        if since_timestamp:
            cursor = conn.execute("""
                SELECT * FROM turns
                WHERE session_id = ? AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (session_id, since_timestamp, limit))
        else:
            cursor = conn.execute("""
                SELECT * FROM turns
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (session_id, limit))

        return [self._row_to_entry(row) for row in cursor]

    def search_by_topic(
        self,
        user_id: str,
        query: str,
        limit: int = 20
    ) -> List[TurnIndexEntry]:
        """
        Search turns by topic (using LIKE).

        Args:
            user_id: User identifier
            query: Search query
            limit: Maximum results

        Returns:
            List of matching TurnIndexEntry
        """
        conn = self._get_connection()

        # Simple LIKE search - could be enhanced with FTS5
        search_pattern = f"%{query}%"
        cursor = conn.execute("""
            SELECT * FROM turns
            WHERE user_id = ? AND topic LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (user_id, search_pattern, limit))

        return [self._row_to_entry(row) for row in cursor]

    def search_by_keywords(
        self,
        session_id: str,
        keywords: List[str],
        limit: int = 20
    ) -> List[Tuple[TurnIndexEntry, int]]:
        """Search turns by keyword match."""
        conn = self._get_connection()

        cursor = conn.execute("""
            SELECT * FROM turns
            WHERE session_id = ?
            ORDER BY timestamp DESC
        """, (session_id,))

        scored_results = []
        for row in cursor:
            turn_keywords = json.loads(row["keywords"]) if row["keywords"] else []
            turn_keywords_lower = [k.lower() for k in turn_keywords]
            match_count = sum(1 for kw in keywords if kw.lower() in turn_keywords_lower)

            if match_count > 0:
                entry = self._row_to_entry(row)
                scored_results.append((entry, match_count))

        scored_results.sort(key=lambda x: (-x[1], -x[0].timestamp))
        return scored_results[:limit]

    # =========================================================================
    # FEEDBACK AND VALIDATION TRACKING
    # =========================================================================

    def update_feedback_status(
        self,
        turn_number: int,
        feedback_status: str,
        confidence: float = 0.8,
        rejection_detected_in: str = ""
    ):
        """Update the feedback status for a turn."""
        conn = self._get_connection()
        conn.execute("""
            UPDATE turns
            SET user_feedback_status = ?,
                feedback_confidence = ?,
                rejection_detected_in = ?
            WHERE turn_number = ?
        """, (feedback_status, confidence, rejection_detected_in, turn_number))
        conn.commit()

    def update_validation_outcome(
        self,
        turn_number: int,
        validation_outcome: str,
        quality_score: float = 0.0
    ):
        """Update the validation outcome for a turn."""
        conn = self._get_connection()
        conn.execute("""
            UPDATE turns
            SET validation_outcome = ?,
                quality_score = ?
            WHERE turn_number = ?
        """, (validation_outcome, quality_score, turn_number))
        conn.commit()

    def update_goals(self, turn_number: int, goals: List[Dict[str, Any]]):
        """Update the goals for a turn."""
        conn = self._get_connection()
        goals_json = json.dumps(goals)
        conn.execute("UPDATE turns SET goals_json = ? WHERE turn_number = ?", (goals_json, turn_number))
        conn.commit()

    def get_rejected_turns(self, session_id: str = None, limit: int = 50) -> List[TurnIndexEntry]:
        """Get turns that were rejected by the user."""
        conn = self._get_connection()

        if session_id:
            cursor = conn.execute("""
                SELECT * FROM turns
                WHERE user_feedback_status = 'rejected' AND session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (session_id, limit))
        else:
            cursor = conn.execute("""
                SELECT * FROM turns
                WHERE user_feedback_status = 'rejected'
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))

        return [self._row_to_entry(row) for row in cursor]

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        conn = self._get_connection()

        total_turns = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        user_count = conn.execute("SELECT COUNT(DISTINCT user_id) FROM turns").fetchone()[0]
        session_count = conn.execute("SELECT COUNT(DISTINCT session_id) FROM turns").fetchone()[0]

        return {
            "total_turns": total_turns,
            "user_count": user_count,
            "session_count": session_count,
            "db_path": str(self.db_path),
            "schema_version": SCHEMA_VERSION,
        }

    def get_validation_stats(self, session_id: str = None) -> Dict[str, Any]:
        """Get validation statistics."""
        conn = self._get_connection()

        if session_id:
            cursor = conn.execute(
                "SELECT validation_outcome, COUNT(*) as count FROM turns WHERE session_id = ? GROUP BY validation_outcome",
                (session_id,)
            )
        else:
            cursor = conn.execute("SELECT validation_outcome, COUNT(*) as count FROM turns GROUP BY validation_outcome")

        stats = {"APPROVE": 0, "RETRY": 0, "REVISE": 0, "FAIL": 0, "": 0}
        for row in cursor:
            outcome = row["validation_outcome"] or ""
            stats[outcome] = row["count"]

        total = sum(v for k, v in stats.items() if k)
        stats["approval_rate"] = stats["APPROVE"] / total if total > 0 else 0.0

        return stats

    def get_recent_turns(self, session_id: str = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent turns as dicts (for compatibility)."""
        conn = self._get_connection()

        if session_id:
            cursor = conn.execute("""
                SELECT * FROM turns WHERE session_id = ?
                ORDER BY timestamp DESC LIMIT ?
            """, (session_id, limit))
        else:
            cursor = conn.execute("""
                SELECT * FROM turns ORDER BY timestamp DESC LIMIT ?
            """, (limit,))

        results = []
        for row in cursor:
            entry = self._row_to_entry(row)
            results.append({
                "turn_number": entry.turn_number,
                "user_id": entry.user_id,
                "session_id": entry.session_id,
                "timestamp": entry.timestamp,
                "topic": entry.topic,
                "intent": entry.intent,
                "keywords": entry.keywords,
                "turn_dir": str(entry.turn_dir),  # Computed property
                "validation_outcome": entry.validation_outcome,
                "quality_score": entry.quality_score,
                "user_feedback_status": entry.user_feedback_status,
                "created_at": datetime.fromtimestamp(entry.timestamp).isoformat() if entry.timestamp else ""
            })

        return results

    # =========================================================================
    # FRESHNESS DEGRADATION
    # =========================================================================

    def degrade_quality(
        self,
        turn_number: int,
        factor: float,
        reason: str,
        superseded_by: Optional[int] = None
    ) -> bool:
        """
        Reduce quality_score of a turn due to freshness contradiction.

        This is part of the Information Freshness Degradation System.
        When new research discovers that prior information is outdated
        (e.g., product no longer available at stated price), we downgrade
        the old turn's quality_score so future retrievals prefer fresh data.

        Args:
            turn_number: Turn to degrade
            factor: Degradation multiplier (0.0-1.0, lower = more degradation)
                   - 0.3 = severe (availability_change, product_removed)
                   - 0.5 = moderate (price_change, spec_correction)
            reason: Why this degradation is happening
            superseded_by: Turn number that supersedes this one

        Returns:
            True if degradation was applied, False if turn not found
        """
        conn = self._get_connection()

        # Get current quality
        cursor = conn.execute(
            "SELECT quality_score FROM turns WHERE turn_number = ?",
            (turn_number,)
        )
        row = cursor.fetchone()
        if not row:
            logger.warning(f"[TurnIndexDB] Cannot degrade turn {turn_number} - not found")
            return False

        old_quality = row[0] if row[0] is not None else 0.8
        new_quality = max(0.1, old_quality * factor)  # Floor at 0.1

        # Update quality score
        conn.execute("""
            UPDATE turns
            SET quality_score = ?
            WHERE turn_number = ?
        """, (new_quality, turn_number))

        conn.commit()

        logger.info(
            f"[TurnIndexDB] Quality degraded: turn {turn_number} "
            f"{old_quality:.2f} → {new_quality:.2f} "
            f"(factor={factor:.2f}, reason={reason})"
            + (f", superseded_by={superseded_by}" if superseded_by else "")
        )

        return True

    def get_turn_quality(self, turn_number: int) -> Optional[float]:
        """Get quality score for a turn."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT quality_score FROM turns WHERE turn_number = ?",
            (turn_number,)
        )
        row = cursor.fetchone()
        return row[0] if row else None


# =============================================================================
# GLOBAL SINGLETON WITH STARTUP SYNC
# =============================================================================

_TURN_INDEX_DB: Optional[TurnIndexDB] = None


def get_turn_index_db(sync_on_startup: bool = True) -> TurnIndexDB:
    """
    Get the global TurnIndexDB instance.

    Args:
        sync_on_startup: If True, validate and sync index on first access
    """
    global _TURN_INDEX_DB
    if _TURN_INDEX_DB is None:
        _TURN_INDEX_DB = TurnIndexDB()
        if sync_on_startup:
            _TURN_INDEX_DB.sync_if_needed()
    return _TURN_INDEX_DB


def rebuild_turn_index(user_id: str = None) -> int:
    """Convenience function to rebuild the turn index."""
    db = get_turn_index_db(sync_on_startup=False)
    return db.rebuild_from_filesystem(user_id)
