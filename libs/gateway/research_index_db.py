"""
Research Index Database: SQLite index for efficient research document search.

Enables topic-based retrieval of research documents with:
- Topic hierarchy matching (pet.hamster matches pet.hamster.syrian_hamster)
- Intent filtering (transactional vs informational)
- Quality and freshness ranking
- Scope filtering (new, user, global) - per MEMORY_ARCHITECTURE.md
- Deduplication and superseding logic
"""

import sqlite3
import json
import math
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from .confidence_calibration import (
    get_confidence_floor,
    get_decay_rate,
    CONFIDENCE_FLOORS,
    ContentType,
    DEFAULT_FLOOR
)

logger = logging.getLogger(__name__)

# Thread-local storage for connections
_local = threading.local()


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ResearchIndexEntry:
    """A single entry in the research index."""
    id: str
    turn_number: int
    session_id: str
    primary_topic: str
    keywords: List[str]
    intent: str
    content_types: List[str]  # What info this research contains
    completeness: float
    source_quality: float
    overall_quality: float
    confidence_initial: float
    confidence_current: float
    decay_rate: float
    created_at: float  # Unix timestamp
    expires_at: Optional[float]
    scope: str
    supersedes: Optional[str]
    superseded_by: Optional[str]
    status: str
    usage_count: int
    doc_path: str

    @property
    def age_hours(self) -> float:
        """Age in hours since creation."""
        return (datetime.now(timezone.utc).timestamp() - self.created_at) / 3600

    @property
    def is_expired(self) -> bool:
        """Check if research has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc).timestamp() > self.expires_at


@dataclass
class SearchResult:
    """A research search result with relevance score."""
    entry: ResearchIndexEntry
    score: float
    match_reason: str


# =============================================================================
# Research Index Database
# =============================================================================

class ResearchIndexDB:
    """
    SQLite-based research index for efficient topic-based queries.

    Maintains a database index of all research documents with topic classification
    for fast retrieval by topic, intent, and quality.
    """

    def __init__(self, db_path: Path = None, turns_dir: Path = None):
        self.db_path = db_path or Path("panda_system_docs/research_index.db")
        self.turns_dir = turns_dir or Path("panda_system_docs/turns")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(_local, 'research_connection') or _local.research_connection is None:
            _local.research_connection = sqlite3.connect(str(self.db_path))
            _local.research_connection.row_factory = sqlite3.Row
        return _local.research_connection

    def _init_db(self):
        """Initialize the database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = self._get_connection()

        # Main research table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS research (
                id TEXT PRIMARY KEY,
                turn_number INTEGER NOT NULL,
                session_id TEXT NOT NULL,

                -- Topic classification
                primary_topic TEXT NOT NULL,
                keywords TEXT,
                intent TEXT,
                content_types TEXT,

                -- Quality metrics
                completeness REAL DEFAULT 0.0,
                source_quality REAL DEFAULT 0.0,
                overall_quality REAL DEFAULT 0.0,

                -- Confidence (decays over time)
                confidence_initial REAL DEFAULT 0.85,
                confidence_current REAL DEFAULT 0.85,
                decay_rate REAL DEFAULT 0.02,

                -- Freshness
                created_at REAL NOT NULL,
                expires_at REAL,
                last_verified_at REAL,

                -- Scope & lineage
                scope TEXT DEFAULT 'new',
                supersedes TEXT,
                superseded_by TEXT,
                status TEXT DEFAULT 'active',
                usage_count INTEGER DEFAULT 1,

                -- Document path
                doc_path TEXT NOT NULL
            )
        """)

        # Add content_types column if it doesn't exist (migration)
        try:
            conn.execute("ALTER TABLE research ADD COLUMN content_types TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Indexes for efficient queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_research_topic ON research(primary_topic)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_research_session ON research(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_research_intent ON research(intent)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_research_status ON research(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_research_quality ON research(overall_quality DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_research_created ON research(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_research_scope ON research(scope)")

        # Topic tree for hierarchy queries
        conn.execute("""
            CREATE TABLE IF NOT EXISTS topic_tree (
                path TEXT PRIMARY KEY,
                parent_path TEXT,
                depth INTEGER,
                aliases TEXT
            )
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_topic_parent ON topic_tree(parent_path)")

        # Research locks for concurrent query handling
        conn.execute("""
            CREATE TABLE IF NOT EXISTS research_locks (
                topic TEXT NOT NULL,
                session_id TEXT NOT NULL,
                started_at REAL NOT NULL,
                research_id TEXT,
                PRIMARY KEY (topic, session_id)
            )
        """)

        conn.commit()
        logger.debug(f"[ResearchIndexDB] Initialized at {self.db_path}")

    # =========================================================================
    # Indexing Operations
    # =========================================================================

    def index_research(
        self,
        id: str,
        turn_number: int,
        session_id: str,
        primary_topic: str,
        keywords: List[str],
        intent: str,
        completeness: float,
        source_quality: float,
        overall_quality: float,
        confidence_initial: float,
        decay_rate: float,
        created_at: float,
        expires_at: Optional[float],
        scope: str,
        doc_path: str,
        supersedes: Optional[str] = None,
        content_types: Optional[List[str]] = None
    ):
        """
        Add or update a research document in the index.
        """
        conn = self._get_connection()

        conn.execute("""
            INSERT OR REPLACE INTO research
            (id, turn_number, session_id, primary_topic, keywords, intent, content_types,
             completeness, source_quality, overall_quality,
             confidence_initial, confidence_current, decay_rate,
             created_at, expires_at, scope, supersedes, status, doc_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """, (
            id, turn_number, session_id, primary_topic, json.dumps(keywords), intent,
            json.dumps(content_types or []),
            completeness, source_quality, overall_quality,
            confidence_initial, confidence_initial, decay_rate,
            created_at, expires_at, scope, supersedes, doc_path
        ))

        # Update topic tree
        self._update_topic_tree(primary_topic)

        # Handle superseding
        if supersedes:
            conn.execute("""
                UPDATE research SET status = 'superseded', superseded_by = ?
                WHERE id = ?
            """, (id, supersedes))

        conn.commit()
        logger.debug(f"[ResearchIndexDB] Indexed research {id} (topic={primary_topic})")

    def _update_topic_tree(self, topic_path: str):
        """Ensure topic and all parents exist in topic tree."""
        conn = self._get_connection()

        parts = topic_path.split('.')
        for i in range(len(parts)):
            path = '.'.join(parts[:i+1])
            parent = '.'.join(parts[:i]) if i > 0 else None
            depth = i + 1

            conn.execute("""
                INSERT OR IGNORE INTO topic_tree (path, parent_path, depth, aliases)
                VALUES (?, ?, ?, '[]')
            """, (path, parent, depth))

    # =========================================================================
    # Search Operations
    # =========================================================================

    def search(
        self,
        topic: str,
        intent: Optional[str] = None,
        session_id: Optional[str] = None,
        scope: Optional[str] = None,
        min_quality: float = 0.0,
        include_expired: bool = False,
        limit: int = 10
    ) -> List[SearchResult]:
        """
        Search for research documents by topic with multi-factor ranking.

        Args:
            topic: Topic to search for (matches topic and all children)
            intent: Optional intent filter (transactional, informational)
            session_id: Optional session filter
            scope: Optional scope filter (new, user, global)
            min_quality: Minimum quality threshold
            include_expired: Whether to include expired research
            limit: Maximum results to return

        Returns:
            List of SearchResult sorted by relevance score
        """
        conn = self._get_connection()
        now = datetime.now(timezone.utc).timestamp()

        # Build query
        query = """
            SELECT * FROM research
            WHERE status = 'active'
            AND (primary_topic = ? OR primary_topic LIKE ?)
            AND overall_quality >= ?
        """
        params = [topic, f"{topic}.%", min_quality]

        if intent:
            query += " AND intent = ?"
            params.append(intent)

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)

        if scope:
            query += " AND scope = ?"
            params.append(scope)

        if not include_expired:
            query += " AND (expires_at IS NULL OR expires_at > ?)"
            params.append(now)

        query += " ORDER BY created_at DESC"

        cursor = conn.execute(query, params)
        results = []

        for row in cursor:
            entry = self._row_to_entry(row)

            # Calculate relevance score
            score = self._calculate_score(entry, topic, intent)

            if score > 0.1:  # Minimum threshold
                match_reason = self._get_match_reason(entry, topic, intent)
                results.append(SearchResult(entry=entry, score=score, match_reason=match_reason))

        # Sort by score and limit
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def search_by_keywords(
        self,
        keywords: List[str],
        session_id: Optional[str] = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """
        Search for research documents by keyword match.

        Args:
            keywords: Keywords to search for
            session_id: Optional session filter
            limit: Maximum results to return

        Returns:
            List of SearchResult sorted by keyword match count
        """
        conn = self._get_connection()

        query = """
            SELECT * FROM research
            WHERE status = 'active'
        """
        params = []

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)

        query += " ORDER BY created_at DESC"

        cursor = conn.execute(query, params)
        results = []

        keywords_lower = [k.lower() for k in keywords]

        for row in cursor:
            entry = self._row_to_entry(row)

            # Count keyword matches
            entry_keywords = [k.lower() for k in entry.keywords]
            match_count = sum(1 for kw in keywords_lower if kw in entry_keywords)

            # Also check topic
            topic_words = entry.primary_topic.lower().split('.')
            match_count += sum(1 for kw in keywords_lower if kw in topic_words)

            if match_count > 0:
                # Score based on match ratio
                score = match_count / len(keywords)
                match_reason = f"Matched {match_count}/{len(keywords)} keywords"
                results.append(SearchResult(entry=entry, score=score, match_reason=match_reason))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def search_by_content_needs(
        self,
        topic: str,
        content_needs: List[str],
        session_id: Optional[str] = None,
        min_quality: float = 0.0,
        include_expired: bool = False,
        limit: int = 10
    ) -> Tuple[List[SearchResult], List[str]]:
        """
        Search for research that matches topic AND satisfies content needs.

        Args:
            topic: Topic to search for
            content_needs: What content types the query needs (e.g., ["care_info", "feeding_info"])
            session_id: Optional session filter
            min_quality: Minimum quality threshold
            include_expired: Whether to include expired research
            limit: Maximum results

        Returns:
            Tuple of (matching results, unmet needs list)
        """
        # First get research matching the topic
        topic_results = self.search(
            topic=topic,
            session_id=session_id,
            min_quality=min_quality,
            include_expired=include_expired,
            limit=limit * 2  # Get more to filter
        )

        if not topic_results:
            return [], content_needs  # No research, all needs unmet

        # Filter by content type coverage
        matching_results = []
        all_covered_types = set()

        for result in topic_results:
            entry_types = set(result.entry.content_types)
            needs_set = set(content_needs)

            # Calculate coverage
            covered = entry_types & needs_set
            coverage_ratio = len(covered) / len(needs_set) if needs_set else 0

            if coverage_ratio > 0:
                # Add coverage info to match reason
                result.match_reason += f", Covers: {', '.join(covered)}"
                # Boost score based on coverage
                result.score *= (1 + coverage_ratio * 0.5)
                matching_results.append(result)
                all_covered_types.update(covered)

        # Calculate unmet needs
        unmet_needs = [n for n in content_needs if n not in all_covered_types]

        # Sort by adjusted score
        matching_results.sort(key=lambda r: r.score, reverse=True)

        logger.info(
            f"[ResearchIndexDB] Content search: {len(matching_results)} results, "
            f"unmet needs: {unmet_needs}"
        )

        return matching_results[:limit], unmet_needs

    def find_related(
        self,
        topic: str,
        session_id: Optional[str] = None,
        limit: int = 5
    ) -> List[SearchResult]:
        """
        Find research related to a topic (siblings and parent topics).

        Args:
            topic: Topic to find related research for
            session_id: Optional session filter
            limit: Maximum results

        Returns:
            List of SearchResult for related topics
        """
        conn = self._get_connection()

        # Get parent and sibling topics
        parts = topic.split('.')
        related_topics = []

        # Parent topics
        for i in range(1, len(parts)):
            related_topics.append('.'.join(parts[:i]))

        # Sibling topics (same parent, different leaf)
        if len(parts) > 1:
            parent = '.'.join(parts[:-1])
            related_topics.append(f"{parent}.%")

        results = []
        seen_ids = set()

        for related in related_topics:
            is_pattern = '%' in related

            if is_pattern:
                query = """
                    SELECT * FROM research
                    WHERE status = 'active' AND primary_topic LIKE ? AND primary_topic != ?
                """
                params = [related, topic]
            else:
                query = """
                    SELECT * FROM research
                    WHERE status = 'active' AND primary_topic = ?
                """
                params = [related]

            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)

            query += " ORDER BY overall_quality DESC LIMIT 5"

            cursor = conn.execute(query, params)

            for row in cursor:
                entry = self._row_to_entry(row)
                if entry.id not in seen_ids:
                    seen_ids.add(entry.id)
                    score = 0.5 * entry.overall_quality  # Lower weight for related
                    results.append(SearchResult(
                        entry=entry,
                        score=score,
                        match_reason=f"Related topic: {entry.primary_topic}"
                    ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _calculate_score(
        self,
        entry: ResearchIndexEntry,
        query_topic: str,
        query_intent: Optional[str]
    ) -> float:
        """
        Calculate multi-factor relevance score for a research entry.
        """
        scores = {}
        now = datetime.now(timezone.utc).timestamp()

        # 1. Topic Match (0.0 - 0.35)
        topic_distance = self._topic_distance(entry.primary_topic, query_topic)
        if topic_distance == 0:
            scores['topic'] = 0.35  # Exact match
        elif topic_distance == 1:
            scores['topic'] = 0.25  # Direct child/parent
        elif topic_distance == 2:
            scores['topic'] = 0.15  # Sibling
        else:
            scores['topic'] = 0.05  # Distant

        # 2. Intent Match (0.0 - 0.15)
        if query_intent:
            if entry.intent == query_intent:
                scores['intent'] = 0.15
            elif entry.intent == 'informational':
                scores['intent'] = 0.08  # Info useful for transactional
            else:
                scores['intent'] = 0.0
        else:
            scores['intent'] = 0.10  # No intent preference

        # 3. Quality Score (0.0 - 0.20)
        scores['quality'] = entry.overall_quality * 0.20

        # 4. Freshness (0.0 - 0.15)
        age_hours = entry.age_hours
        if age_hours < 1:
            scores['freshness'] = 0.15
        elif age_hours < 6:
            scores['freshness'] = 0.12
        elif age_hours < 24:
            scores['freshness'] = 0.08
        elif age_hours < 72:
            scores['freshness'] = 0.04
        else:
            scores['freshness'] = 0.01

        # 5. Current Confidence (0.0 - 0.10)
        # Recalculate current confidence with decay using content-type specific floors
        days_old = age_hours / 24

        # Get content-type specific floor (use most conservative if multiple types)
        floor = DEFAULT_FLOOR
        if entry.content_types:
            floors = [get_confidence_floor(ct) for ct in entry.content_types]
            floor = min(floors) if floors else DEFAULT_FLOOR

        decayed = floor + (entry.confidence_initial - floor) * math.exp(-entry.decay_rate * days_old)
        current_confidence = max(floor, decayed)
        scores['confidence'] = current_confidence * 0.10

        # 6. Scope Bonus (0.0 - 0.05)
        if entry.scope == 'global':
            scores['scope'] = 0.05
        elif entry.scope == 'user':
            scores['scope'] = 0.03
        else:
            scores['scope'] = 0.0

        return sum(scores.values())

    def _topic_distance(self, topic1: str, topic2: str) -> int:
        """Calculate distance between two topics in hierarchy."""
        parts1 = topic1.split('.')
        parts2 = topic2.split('.')

        # Find common prefix length
        common = 0
        for i in range(min(len(parts1), len(parts2))):
            if parts1[i] == parts2[i]:
                common += 1
            else:
                break

        # Distance is sum of remaining parts
        return (len(parts1) - common) + (len(parts2) - common)

    def _get_match_reason(
        self,
        entry: ResearchIndexEntry,
        query_topic: str,
        query_intent: Optional[str]
    ) -> str:
        """Generate human-readable match reason."""
        reasons = []

        if entry.primary_topic == query_topic:
            reasons.append("Exact topic match")
        elif query_topic in entry.primary_topic:
            reasons.append("Child topic")
        elif entry.primary_topic in query_topic:
            reasons.append("Parent topic")
        else:
            reasons.append("Related topic")

        if query_intent and entry.intent == query_intent:
            reasons.append(f"Same intent ({entry.intent})")

        reasons.append(f"Quality: {entry.overall_quality:.2f}")
        reasons.append(f"Age: {entry.age_hours:.1f}h")

        return ", ".join(reasons)

    def _row_to_entry(self, row: sqlite3.Row) -> ResearchIndexEntry:
        """Convert database row to ResearchIndexEntry."""
        keywords = json.loads(row["keywords"]) if row["keywords"] else []

        # Parse content_types - handle migration from older entries
        content_types_raw = row["content_types"] if "content_types" in row.keys() else None
        content_types = json.loads(content_types_raw) if content_types_raw else []

        return ResearchIndexEntry(
            id=row["id"],
            turn_number=row["turn_number"],
            session_id=row["session_id"],
            primary_topic=row["primary_topic"],
            keywords=keywords,
            intent=row["intent"] or "informational",
            content_types=content_types,
            completeness=row["completeness"],
            source_quality=row["source_quality"],
            overall_quality=row["overall_quality"],
            confidence_initial=row["confidence_initial"],
            confidence_current=row["confidence_current"],
            decay_rate=row["decay_rate"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            scope=row["scope"] or "new",
            supersedes=row["supersedes"],
            superseded_by=row["superseded_by"],
            status=row["status"] or "active",
            usage_count=row["usage_count"] or 1,
            doc_path=row["doc_path"]
        )

    # =========================================================================
    # Deduplication and Superseding
    # =========================================================================

    def find_overlapping(
        self,
        topic: str,
        intent: str,
        session_id: str
    ) -> List[ResearchIndexEntry]:
        """
        Find existing research that might be superseded by new research.
        """
        conn = self._get_connection()

        cursor = conn.execute("""
            SELECT * FROM research
            WHERE status = 'active'
            AND primary_topic = ?
            AND intent = ?
            AND session_id = ?
            ORDER BY created_at DESC
        """, (topic, intent, session_id))

        return [self._row_to_entry(row) for row in cursor]

    def check_should_supersede(
        self,
        new_quality: float,
        existing: ResearchIndexEntry
    ) -> Tuple[str, Optional[str]]:
        """
        Determine if new research should supersede existing.

        Returns:
            Tuple of (action, existing_id)
            action: 'create', 'supersede', 'merge', 'skip'
        """
        quality_diff = new_quality - existing.overall_quality

        if quality_diff > 0.1:
            # New is significantly better - supersede
            return 'supersede', existing.id
        elif quality_diff < -0.1:
            # Old is significantly better - skip new
            return 'skip', existing.id
        else:
            # Similar quality - could merge
            if existing.age_hours > 6:
                # Old is stale, supersede
                return 'supersede', existing.id
            else:
                # Recent and similar quality - skip to avoid churn
                return 'skip', existing.id

    def mark_superseded_by_turn(
        self,
        prior_turn: int,
        superseded_by_turn: int,
        reason: str
    ) -> bool:
        """
        Mark all research from a prior turn as superseded.

        This is called by the Freshness Analyzer when new research
        discovers that prior information is outdated.

        Args:
            prior_turn: Turn number whose research is now outdated
            superseded_by_turn: Turn number with newer information
            reason: Why this research is being superseded (e.g., "availability_change")

        Returns:
            True if any research was marked as superseded
        """
        conn = self._get_connection()

        # Find all active research from the prior turn
        cursor = conn.execute("""
            SELECT id FROM research
            WHERE turn_number = ? AND status = 'active'
        """, (prior_turn,))

        ids_to_update = [row["id"] for row in cursor]

        if not ids_to_update:
            return False

        # Mark them as superseded
        now = datetime.now(timezone.utc).timestamp()
        for research_id in ids_to_update:
            conn.execute("""
                UPDATE research
                SET status = 'superseded',
                    superseded_by = ?
                WHERE id = ?
            """, (f"turn_{superseded_by_turn}:{reason}", research_id))

        conn.commit()

        logger.info(
            f"[ResearchIndexDB] Marked {len(ids_to_update)} research entries from turn {prior_turn} "
            f"as superseded by turn {superseded_by_turn} ({reason})"
        )

        return True

    # =========================================================================
    # Locking for Concurrent Queries
    # =========================================================================

    def try_acquire_lock(
        self,
        topic: str,
        session_id: str,
        timeout_seconds: float = 120
    ) -> Tuple[bool, Optional[str]]:
        """
        Try to acquire a lock for researching a topic.

        Returns:
            Tuple of (acquired, existing_research_id or None)
        """
        conn = self._get_connection()
        now = datetime.now(timezone.utc).timestamp()

        # Check for existing lock
        cursor = conn.execute("""
            SELECT * FROM research_locks
            WHERE topic = ? AND session_id = ?
        """, (topic, session_id))

        row = cursor.fetchone()

        if row:
            # Lock exists - check if stale
            if now - row["started_at"] > timeout_seconds:
                # Stale lock - delete and acquire
                conn.execute("""
                    DELETE FROM research_locks
                    WHERE topic = ? AND session_id = ?
                """, (topic, session_id))
            else:
                # Active lock - return existing research if available
                return False, row["research_id"]

        # Acquire lock
        try:
            conn.execute("""
                INSERT INTO research_locks (topic, session_id, started_at)
                VALUES (?, ?, ?)
            """, (topic, session_id, now))
            conn.commit()
            return True, None
        except sqlite3.IntegrityError:
            # Race condition - another thread acquired lock
            return False, None

    def release_lock(
        self,
        topic: str,
        session_id: str,
        research_id: Optional[str] = None
    ):
        """Release a research lock."""
        conn = self._get_connection()

        if research_id:
            # Update lock with research ID before deleting (for waiting threads)
            conn.execute("""
                UPDATE research_locks SET research_id = ?
                WHERE topic = ? AND session_id = ?
            """, (research_id, topic, session_id))

        conn.execute("""
            DELETE FROM research_locks
            WHERE topic = ? AND session_id = ?
        """, (topic, session_id))

        conn.commit()

    # =========================================================================
    # Scope Promotion
    # =========================================================================

    def check_promotion(self, research_id: str) -> Optional[str]:
        """
        Check if research should be promoted to higher scope.

        Returns:
            New scope if promotion warranted, None otherwise
        """
        conn = self._get_connection()

        cursor = conn.execute("""
            SELECT * FROM research WHERE id = ?
        """, (research_id,))

        row = cursor.fetchone()
        if not row:
            return None

        entry = self._row_to_entry(row)

        # Promotion thresholds
        if entry.scope == 'new':
            if (entry.usage_count >= 3 and
                entry.overall_quality >= 0.70 and
                entry.age_hours >= 1):
                return 'user'

        elif entry.scope == 'user':
            if (entry.usage_count >= 10 and
                entry.overall_quality >= 0.85 and
                entry.age_hours >= 24):
                return 'global'

        return None

    def promote(self, research_id: str, new_scope: str):
        """Promote research to new scope."""
        conn = self._get_connection()

        conn.execute("""
            UPDATE research SET scope = ? WHERE id = ?
        """, (new_scope, research_id))

        conn.commit()
        logger.info(f"[ResearchIndexDB] Promoted {research_id} to scope={new_scope}")

    def increment_usage(self, research_id: str):
        """Increment usage count for a research document."""
        conn = self._get_connection()

        conn.execute("""
            UPDATE research SET usage_count = usage_count + 1 WHERE id = ?
        """, (research_id,))

        conn.commit()

    # =========================================================================
    # Invalidation (for validation loop-back)
    # =========================================================================

    def invalidate_by_url(self, url: str) -> int:
        """
        Invalidate research entries that reference a specific URL.

        Used when validation detects a dead URL in the response.
        Marks matching entries as 'invalidated' so they won't be reused.

        Returns: number of entries invalidated
        """
        conn = self._get_connection()

        # Search doc_path for entries that might contain this URL
        # Note: This is a heuristic - ideally we'd have URL tracking in the schema
        # Only invalidate entries whose doc_path contains part of the URL
        cursor = conn.execute("""
            UPDATE research
            SET status = 'invalidated'
            WHERE status = 'active' AND doc_path LIKE ?
        """, (f"%{url[:50]}%",))

        # NOTE: We removed the aggressive "invalidate all recent entries" logic
        # that was here. It caused cache thrashing by invalidating unrelated entries.
        # Instead, rely on retry_context.json to tell Context Gatherer what to skip.

        conn.commit()
        count = cursor.rowcount
        if count > 0:
            logger.info(f"[ResearchIndexDB] Invalidated {count} entries for URL: {url[:50]}...")
        else:
            logger.debug(f"[ResearchIndexDB] No entries found matching URL: {url[:50]}...")
        return count

    def invalidate_by_id(self, research_id: str) -> bool:
        """
        Invalidate a specific research entry by ID.

        Returns: True if entry was invalidated
        """
        conn = self._get_connection()

        cursor = conn.execute("""
            UPDATE research
            SET status = 'invalidated'
            WHERE id = ?
        """, (research_id,))

        conn.commit()
        success = cursor.rowcount > 0
        if success:
            logger.info(f"[ResearchIndexDB] Invalidated research: {research_id}")
        return success

    def invalidate_recent(self, hours: float = 1.0) -> int:
        """
        Invalidate all research created in the last N hours.

        Used for aggressive cache clearing on validation failures.

        Returns: number of entries invalidated
        """
        conn = self._get_connection()
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now - (hours * 3600)

        cursor = conn.execute("""
            UPDATE research
            SET status = 'invalidated'
            WHERE status = 'active' AND created_at > ?
        """, (cutoff,))

        conn.commit()
        count = cursor.rowcount
        logger.info(f"[ResearchIndexDB] Invalidated {count} recent entries (last {hours}h)")
        return count

    # =========================================================================
    # Maintenance
    # =========================================================================

    def cleanup_expired(self) -> int:
        """Mark expired research as expired status."""
        conn = self._get_connection()
        now = datetime.now(timezone.utc).timestamp()

        cursor = conn.execute("""
            UPDATE research
            SET status = 'expired'
            WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at < ?
        """, (now,))

        conn.commit()
        return cursor.rowcount

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        conn = self._get_connection()

        total = conn.execute("SELECT COUNT(*) FROM research").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM research WHERE status = 'active'").fetchone()[0]
        by_scope = {}
        for scope in ['new', 'user', 'global']:
            count = conn.execute(
                "SELECT COUNT(*) FROM research WHERE scope = ?", (scope,)
            ).fetchone()[0]
            by_scope[scope] = count

        topics = conn.execute("SELECT COUNT(DISTINCT primary_topic) FROM research").fetchone()[0]

        return {
            "total_research": total,
            "active_research": active,
            "by_scope": by_scope,
            "unique_topics": topics,
            "db_path": str(self.db_path)
        }

    def rebuild_index(self):
        """Rebuild index from research.json files in turn directories."""
        conn = self._get_connection()

        # Clear existing data
        conn.execute("DELETE FROM research")

        indexed = 0
        for turn_dir in self.turns_dir.iterdir():
            if not turn_dir.is_dir():
                continue

            research_json = turn_dir / "research.json"
            if not research_json.exists():
                continue

            try:
                data = json.loads(research_json.read_text())

                self.index_research(
                    id=data["id"],
                    turn_number=data["turn_number"],
                    session_id=data["session_id"],
                    primary_topic=data["topic"]["primary_topic"],
                    keywords=data["topic"]["keywords"],
                    intent=data["topic"]["intent"],
                    completeness=data["quality"]["completeness"],
                    source_quality=data["quality"]["source_quality"],
                    overall_quality=data["quality"]["overall"],
                    confidence_initial=data["confidence"]["initial"],
                    decay_rate=data["confidence"]["decay_rate"],
                    created_at=datetime.fromisoformat(data["created_at"]).timestamp(),
                    expires_at=datetime.fromisoformat(data["expires_at"]).timestamp() if data.get("expires_at") else None,
                    scope=data.get("scope", "new"),  # Default to 'new' for legacy data without scope
                    doc_path=str(turn_dir / "research.md")
                )
                indexed += 1

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"[ResearchIndexDB] Failed to index {research_json}: {e}")

        conn.commit()
        logger.info(f"[ResearchIndexDB] Rebuilt index: {indexed} research documents")


# =============================================================================
# Global Singleton
# =============================================================================

_RESEARCH_INDEX_DB: Optional[ResearchIndexDB] = None


def get_research_index_db() -> ResearchIndexDB:
    """Get the global ResearchIndexDB instance."""
    global _RESEARCH_INDEX_DB
    if _RESEARCH_INDEX_DB is None:
        _RESEARCH_INDEX_DB = ResearchIndexDB()
    return _RESEARCH_INDEX_DB
