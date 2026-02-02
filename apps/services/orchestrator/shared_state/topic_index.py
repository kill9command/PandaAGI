"""
Topic Index for Session Knowledge System.

Manages hierarchical topic organization for session knowledge.
Topics group related claims and enable semantic query matching.

Created: 2025-12-02
"""

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import hashlib

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Topic:
    """A knowledge topic in the hierarchy."""
    topic_id: str
    session_id: str
    topic_name: str
    topic_slug: str
    parent_id: Optional[str]
    embedding: Optional[np.ndarray]

    # Denormalized summaries for fast access
    retailers: List[str] = field(default_factory=list)
    price_range: Dict[str, float] = field(default_factory=dict)  # {"min": 600, "max": 2000}
    key_specs: List[str] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    access_count: int = 1
    source_queries: List[str] = field(default_factory=list)


@dataclass
class TopicMatch:
    """Result from topic search with similarity score."""
    topic: Topic
    similarity: float
    inherited_knowledge: Dict[str, Any] = field(default_factory=dict)
    claim_count: int = 0


class TopicIndex:
    """
    Manages hierarchical topic organization for session knowledge.

    Topics form a tree where:
    - Child topics inherit parent knowledge (retailers, tips)
    - Child topics can override parent values (price ranges)
    - Semantic search finds best-matching topics via embeddings
    """

    def __init__(self, db_path: str | Path):
        """
        Initialize TopicIndex with database path.

        Args:
            db_path: Path to SQLite database (same as ClaimRegistry)
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._ensure_tables()
        self._embedding_service = None

    @property
    def embedding_service(self):
        """Lazy-load embedding service."""
        if self._embedding_service is None:
            from apps.services.orchestrator.shared_state.embedding_service import EmbeddingService
            self._embedding_service = EmbeddingService()
        return self._embedding_service

    def _ensure_tables(self) -> None:
        """Create topics table if not exists."""
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    topic_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    topic_name TEXT NOT NULL,
                    topic_slug TEXT NOT NULL,
                    parent_id TEXT,
                    embedding BLOB,

                    -- Denormalized summaries
                    retailers_json TEXT DEFAULT '[]',
                    price_range_json TEXT DEFAULT '{}',
                    key_specs_json TEXT DEFAULT '[]',

                    -- Metadata
                    created_at REAL NOT NULL,
                    last_accessed REAL NOT NULL,
                    access_count INTEGER DEFAULT 1,
                    source_queries_json TEXT DEFAULT '[]',

                    FOREIGN KEY (parent_id) REFERENCES topics(topic_id)
                )
            """)

            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_topics_session ON topics(session_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_topics_parent ON topics(parent_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_topics_slug ON topics(topic_slug)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_topics_session_slug ON topics(session_id, topic_slug)")

            # Also extend claims table with topic columns if needed
            self._migrate_claims_table()

            self._conn.commit()

    def _migrate_claims_table(self) -> None:
        """Add topic-related columns to claims table if not exists."""
        try:
            cursor = self._conn.execute("PRAGMA table_info(claims)")
            existing_cols = {row[1] for row in cursor.fetchall()}

            new_columns = [
                ("topic_id", "TEXT"),
                ("claim_type", "TEXT DEFAULT 'general'"),
                ("embedding", "BLOB"),
            ]

            for col_name, col_type in new_columns:
                if col_name not in existing_cols:
                    try:
                        self._conn.execute(f"ALTER TABLE claims ADD COLUMN {col_name} {col_type}")
                        logger.info(f"[TopicIndex] Added column {col_name} to claims table")
                    except Exception as e:
                        logger.debug(f"[TopicIndex] Column {col_name} may already exist: {e}")

            # Create index on topic_id for claims
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_topic ON claims(topic_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type)")

        except Exception as e:
            logger.warning(f"[TopicIndex] Migration warning: {e}")

    # ----- CRUD Operations -----

    def create_topic(
        self,
        session_id: str,
        topic_name: str,
        topic_slug: str,
        parent_id: Optional[str] = None,
        source_query: Optional[str] = None,
        retailers: Optional[List[str]] = None,
        price_range: Optional[Dict[str, float]] = None,
        key_specs: Optional[List[str]] = None,
    ) -> Topic:
        """
        Create a new topic with embedding.

        Args:
            session_id: Session this topic belongs to
            topic_name: Human readable name (e.g., "NVIDIA Gaming Laptops")
            topic_slug: URL-safe identifier (e.g., "nvidia_gaming_laptops")
            parent_id: Parent topic ID for inheritance
            source_query: Query that created this topic
            retailers: Known retailers for this topic
            price_range: Price range dict {"min": x, "max": y}
            key_specs: Key specifications

        Returns:
            Created Topic object
        """
        now = time.time()
        topic_id = self._generate_topic_id(session_id, topic_slug)

        # Generate embedding from topic name
        embedding = self.embedding_service.embed(topic_name)
        embedding_bytes = embedding.tobytes() if embedding is not None else None

        source_queries = [source_query] if source_query else []

        with self._lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO topics (
                    topic_id, session_id, topic_name, topic_slug, parent_id,
                    embedding, retailers_json, price_range_json, key_specs_json,
                    created_at, last_accessed, access_count, source_queries_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                topic_id,
                session_id,
                topic_name,
                topic_slug,
                parent_id,
                embedding_bytes,
                json.dumps(retailers or []),
                json.dumps(price_range or {}),
                json.dumps(key_specs or []),
                now,
                now,
                1,
                json.dumps(source_queries),
            ))
            self._conn.commit()

        logger.info(f"[TopicIndex] Created topic: {topic_name} ({topic_id})")

        return Topic(
            topic_id=topic_id,
            session_id=session_id,
            topic_name=topic_name,
            topic_slug=topic_slug,
            parent_id=parent_id,
            embedding=embedding,
            retailers=retailers or [],
            price_range=price_range or {},
            key_specs=key_specs or [],
            created_at=datetime.fromtimestamp(now, tz=timezone.utc),
            last_accessed=datetime.fromtimestamp(now, tz=timezone.utc),
            access_count=1,
            source_queries=source_queries,
        )

    def get_topic(self, topic_id: str) -> Optional[Topic]:
        """Get topic by ID."""
        cursor = self._conn.execute("""
            SELECT topic_id, session_id, topic_name, topic_slug, parent_id,
                   embedding, retailers_json, price_range_json, key_specs_json,
                   created_at, last_accessed, access_count, source_queries_json
            FROM topics WHERE topic_id = ?
        """, (topic_id,))

        row = cursor.fetchone()
        if not row:
            return None

        return self._row_to_topic(row)

    def get_topic_by_slug(self, session_id: str, slug: str) -> Optional[Topic]:
        """Get topic by slug within session."""
        cursor = self._conn.execute("""
            SELECT topic_id, session_id, topic_name, topic_slug, parent_id,
                   embedding, retailers_json, price_range_json, key_specs_json,
                   created_at, last_accessed, access_count, source_queries_json
            FROM topics WHERE session_id = ? AND topic_slug = ?
        """, (session_id, slug))

        row = cursor.fetchone()
        if not row:
            return None

        return self._row_to_topic(row)

    def get_topics_for_session(self, session_id: str) -> List[Topic]:
        """Get all topics for a session."""
        cursor = self._conn.execute("""
            SELECT topic_id, session_id, topic_name, topic_slug, parent_id,
                   embedding, retailers_json, price_range_json, key_specs_json,
                   created_at, last_accessed, access_count, source_queries_json
            FROM topics WHERE session_id = ?
            ORDER BY last_accessed DESC
        """, (session_id,))

        return [self._row_to_topic(row) for row in cursor.fetchall()]

    def update_topic(
        self,
        topic_id: str,
        retailers: Optional[List[str]] = None,
        price_range: Optional[Dict[str, float]] = None,
        key_specs: Optional[List[str]] = None,
        source_query: Optional[str] = None,
    ) -> Optional[Topic]:
        """Update topic fields."""
        topic = self.get_topic(topic_id)
        if not topic:
            return None

        # Merge updates
        if retailers:
            topic.retailers = list(set(topic.retailers + retailers))
        if price_range:
            # Merge price ranges (expand bounds)
            if topic.price_range:
                if 'min' in price_range and 'min' in topic.price_range:
                    topic.price_range['min'] = min(topic.price_range['min'], price_range['min'])
                elif 'min' in price_range:
                    topic.price_range['min'] = price_range['min']
                if 'max' in price_range and 'max' in topic.price_range:
                    topic.price_range['max'] = max(topic.price_range['max'], price_range['max'])
                elif 'max' in price_range:
                    topic.price_range['max'] = price_range['max']
            else:
                topic.price_range = price_range
        if key_specs:
            topic.key_specs = list(set(topic.key_specs + key_specs))
        if source_query and source_query not in topic.source_queries:
            topic.source_queries.append(source_query)

        now = time.time()

        with self._lock:
            self._conn.execute("""
                UPDATE topics SET
                    retailers_json = ?,
                    price_range_json = ?,
                    key_specs_json = ?,
                    source_queries_json = ?,
                    last_accessed = ?,
                    access_count = access_count + 1
                WHERE topic_id = ?
            """, (
                json.dumps(topic.retailers),
                json.dumps(topic.price_range),
                json.dumps(topic.key_specs),
                json.dumps(topic.source_queries),
                now,
                topic_id,
            ))
            self._conn.commit()

        topic.last_accessed = datetime.fromtimestamp(now, tz=timezone.utc)
        topic.access_count += 1

        return topic

    def record_access(self, topic_id: str) -> None:
        """Increment access count and update last_accessed."""
        with self._lock:
            self._conn.execute("""
                UPDATE topics SET
                    last_accessed = ?,
                    access_count = access_count + 1
                WHERE topic_id = ?
            """, (time.time(), topic_id))
            self._conn.commit()

    # ----- Hierarchy Operations -----

    def get_children(self, topic_id: str) -> List[Topic]:
        """Get direct children of a topic."""
        cursor = self._conn.execute("""
            SELECT topic_id, session_id, topic_name, topic_slug, parent_id,
                   embedding, retailers_json, price_range_json, key_specs_json,
                   created_at, last_accessed, access_count, source_queries_json
            FROM topics WHERE parent_id = ?
        """, (topic_id,))

        return [self._row_to_topic(row) for row in cursor.fetchall()]

    def get_ancestors(self, topic_id: str) -> List[Topic]:
        """Get all ancestors (parent chain) of a topic."""
        ancestors = []
        current = self.get_topic(topic_id)

        while current and current.parent_id:
            parent = self.get_topic(current.parent_id)
            if parent:
                ancestors.append(parent)
                current = parent
            else:
                break

        return ancestors

    def get_ancestor_ids(self, topic_id: str) -> List[str]:
        """Get IDs of all ancestors."""
        return [t.topic_id for t in self.get_ancestors(topic_id)]

    def resolve_inheritance(self, topic_id: str) -> Dict[str, Any]:
        """
        Resolve inherited values from ancestors.

        Returns merged knowledge:
        - retailers: union of all ancestor retailers
        - tips: all ancestor tips (from claims)
        - price_range: most specific (child overrides parent)
        - key_specs: union of all specs
        """
        topic = self.get_topic(topic_id)
        if not topic:
            return {}

        ancestors = self.get_ancestors(topic_id)

        # Start with topic's own values
        retailers = set(topic.retailers)
        key_specs = set(topic.key_specs)
        price_range = topic.price_range.copy() if topic.price_range else {}

        # Merge from ancestors (furthest first)
        for ancestor in reversed(ancestors):
            retailers.update(ancestor.retailers)
            key_specs.update(ancestor.key_specs)
            # Price range: keep most specific (don't override with ancestor)
            if not price_range and ancestor.price_range:
                price_range = ancestor.price_range.copy()

        return {
            "retailers": list(retailers),
            "key_specs": list(key_specs),
            "price_range": price_range,
            "inheritance_depth": len(ancestors),
        }

    # ----- Semantic Search -----

    def search_by_embedding(
        self,
        query_embedding: np.ndarray,
        session_id: str,
        min_similarity: float = 0.75,
        limit: int = 5
    ) -> List[TopicMatch]:
        """
        Find topics similar to query embedding.

        Returns list of TopicMatch with similarity scores.
        """
        cursor = self._conn.execute("""
            SELECT topic_id, session_id, topic_name, topic_slug, parent_id,
                   embedding, retailers_json, price_range_json, key_specs_json,
                   created_at, last_accessed, access_count, source_queries_json
            FROM topics WHERE session_id = ?
        """, (session_id,))

        matches = []

        for row in cursor.fetchall():
            embedding_bytes = row[5]
            if not embedding_bytes:
                continue

            topic_embedding = np.frombuffer(embedding_bytes, dtype=np.float32)

            # Compute cosine similarity
            similarity = self._cosine_similarity(query_embedding, topic_embedding)

            if similarity >= min_similarity:
                topic = self._row_to_topic(row)
                inherited = self.resolve_inheritance(topic.topic_id)

                # Get claim count for this topic
                claim_count = self._get_claim_count(topic.topic_id)

                matches.append(TopicMatch(
                    topic=topic,
                    similarity=float(similarity),
                    inherited_knowledge=inherited,
                    claim_count=claim_count,
                ))

        # Sort by similarity descending
        matches.sort(key=lambda m: m.similarity, reverse=True)

        return matches[:limit]

    def search_by_query(
        self,
        query: str,
        session_id: str,
        min_similarity: float = 0.75,
        limit: int = 5
    ) -> List[TopicMatch]:
        """
        Find topics similar to query text.

        Convenience wrapper that embeds query first.
        """
        query_embedding = self.embedding_service.embed(query)
        if query_embedding is None:
            return []

        return self.search_by_embedding(
            query_embedding=query_embedding,
            session_id=session_id,
            min_similarity=min_similarity,
            limit=limit,
        )

    # ----- Helper Methods -----

    def _row_to_topic(self, row: tuple) -> Topic:
        """Convert database row to Topic object."""
        embedding = None
        if row[5]:
            embedding = np.frombuffer(row[5], dtype=np.float32)

        return Topic(
            topic_id=row[0],
            session_id=row[1],
            topic_name=row[2],
            topic_slug=row[3],
            parent_id=row[4],
            embedding=embedding,
            retailers=json.loads(row[6]) if row[6] else [],
            price_range=json.loads(row[7]) if row[7] else {},
            key_specs=json.loads(row[8]) if row[8] else [],
            created_at=datetime.fromtimestamp(row[9], tz=timezone.utc),
            last_accessed=datetime.fromtimestamp(row[10], tz=timezone.utc),
            access_count=row[11],
            source_queries=json.loads(row[12]) if row[12] else [],
        )

    def _generate_topic_id(self, session_id: str, topic_slug: str) -> str:
        """Generate unique topic ID."""
        content = f"{session_id}:{topic_slug}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        if a is None or b is None:
            return 0.0
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _get_claim_count(self, topic_id: str) -> int:
        """Get number of claims for a topic."""
        try:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM claims WHERE topic_id = ?",
                (topic_id,)
            )
            return cursor.fetchone()[0]
        except Exception:
            return 0


# Module-level singleton
_topic_index_cache: Dict[str, TopicIndex] = {}


def get_topic_index(db_path: Optional[str | Path] = None) -> TopicIndex:
    """
    Get or create TopicIndex instance.

    Uses same database as ClaimRegistry by default.
    """
    if db_path is None:
        db_path = Path("panda_system_docs/shared_state/claims.db")

    db_path = Path(db_path)
    cache_key = str(db_path)

    if cache_key not in _topic_index_cache:
        _topic_index_cache[cache_key] = TopicIndex(db_path)

    return _topic_index_cache[cache_key]
