"""
Knowledge Graph Database: SQLite-based entity, relationship, and backlink storage.

Implements the Knowledge Graph layer for Pandora's memory system with:
- Entity storage with canonical names and aliases
- Entity mentions in documents (entity -> document mapping)
- Relationships between entities (entity -> entity graph)
- Bidirectional backlinks between documents (Obsidian-style)

ARCHITECTURAL PRINCIPLE:
    This is a PRIMARY data store (not a cache) for knowledge graph data.
    Entities and relationships are created as research discovers them.
    The graph can be queried to provide context for future requests.

Schema Overview:
    entities        - Core entity records (vendors, products, sites, topics, etc.)
    entity_mentions - Where entities appear in documents
    relationships   - Edges between entities (sells, recommends, competes_with, etc.)
    backlinks       - Document-to-document links (bidirectional wiki links)
"""

import sqlite3
import json
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Thread-local storage for connections
_local = threading.local()

# Schema version for migrations
SCHEMA_VERSION = 1

# Default database path
DEFAULT_DB_PATH = Path("panda_system_docs/knowledge_graph.db")


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Entity:
    """
    An entity in the knowledge graph.

    Entity types: vendor, product, person, site, topic, thread
    """
    id: int
    entity_type: str
    canonical_name: str
    aliases: List[str] = field(default_factory=list)
    confidence: float = 0.5
    entity_data: Dict[str, Any] = field(default_factory=dict)
    first_seen_turn: int = 0
    last_seen_turn: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        """Ensure aliases is always a list."""
        if self.aliases is None:
            self.aliases = []
        if self.entity_data is None:
            self.entity_data = {}


@dataclass
class Relationship:
    """
    A relationship between two entities in the knowledge graph.

    Relationship types: sells, recommends, mentioned_in, competes_with,
                       parent_of, located_in, etc.
    """
    id: int
    source_entity: Entity
    target_entity: Entity
    relationship_type: str
    confidence: float = 0.5
    weight: float = 1.0
    source_document: Optional[str] = None
    source_turn: int = 0
    created_at: Optional[datetime] = None


@dataclass
class EntityMention:
    """
    A mention of an entity in a document.

    Tracks where entities appear with context and property values.
    """
    id: int
    entity_id: int
    document_path: str
    turn_number: int
    context: str = ""
    property_name: Optional[str] = None
    property_value: Optional[str] = None
    confidence: float = 0.5
    created_at: Optional[datetime] = None


@dataclass
class Backlink:
    """
    A bidirectional link between documents.

    Tracks wiki links like [[target]] or [[target|display text]].
    """
    id: int
    source_file: str
    target_file: str
    link_text: str
    link_type: str = "wiki"  # wiki, entity, url
    line_number: Optional[int] = None
    created_at: Optional[datetime] = None


# =============================================================================
# Knowledge Graph Database
# =============================================================================

class KnowledgeGraphDB:
    """
    Manages entity extraction, relationships, and backlinks.

    This is the central storage for Pandora's knowledge graph, enabling:
    - Entity-centric memory (what do we know about "Poppybee Hamstery"?)
    - Relationship queries (who sells "Syrian Hamsters"?)
    - Backlink navigation (what documents link to this one?)

    Usage:
        kg = KnowledgeGraphDB()

        # Add entity
        vendor_id = kg.add_entity(
            entity_type="vendor",
            canonical_name="Poppybee Hamstery",
            aliases=["poppybee"],
            data={"url": "https://...", "location": "TX"}
        )

        # Add relationship
        kg.add_relationship(vendor_id, product_id, "sells", confidence=0.9)

        # Query relationships
        relationships = kg.get_relationships(product_id, "sells", direction="incoming")

        # Get backlinks to a document
        backlinks = kg.get_backlinks_to("Knowledge/Products/syrian-hamster.md")
    """

    def __init__(self, db_path: Path = None):
        """
        Initialize the knowledge graph database.

        Args:
            db_path: Path to SQLite database file. Defaults to panda_system_docs/knowledge_graph.db
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        conn_attr = 'knowledge_graph_connection'
        if not hasattr(_local, conn_attr) or getattr(_local, conn_attr) is None:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrent access
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            setattr(_local, conn_attr, conn)
        return getattr(_local, conn_attr)

    def _init_db(self):
        """Initialize the database schema."""
        # Create parent directory if using file-based database (not :memory:)
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        elif self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = self._get_connection()

        # Core entity table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY,
                entity_type TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                aliases TEXT,
                first_seen_turn INTEGER DEFAULT 0,
                last_seen_turn INTEGER DEFAULT 0,
                confidence REAL DEFAULT 0.5,
                entity_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(entity_type, canonical_name)
            )
        """)

        # Entity mentions in documents
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entity_mentions (
                id INTEGER PRIMARY KEY,
                entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                document_path TEXT NOT NULL,
                turn_number INTEGER DEFAULT 0,
                mention_context TEXT,
                property_name TEXT,
                property_value TEXT,
                confidence REAL DEFAULT 0.5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Entity relationships
        conn.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY,
                source_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                target_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                relationship_type TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                weight REAL DEFAULT 1.0,
                source_document TEXT,
                source_turn INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_entity_id, target_entity_id, relationship_type)
            )
        """)

        # Document backlinks (bidirectional)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backlinks (
                id INTEGER PRIMARY KEY,
                source_file TEXT NOT NULL,
                target_file TEXT NOT NULL,
                link_text TEXT,
                link_type TEXT DEFAULT 'wiki',
                line_number INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_file, target_file, link_text)
            )
        """)

        # Indexes for fast queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(canonical_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_name_lower ON entities(LOWER(canonical_name))")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_entity ON entity_mentions(entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_doc ON entity_mentions(document_path)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_turn ON entity_mentions(turn_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relationship_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_backlinks_source ON backlinks(source_file)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_backlinks_target ON backlinks(target_file)")

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

        conn.commit()
        logger.debug(f"[KnowledgeGraphDB] Initialized at {self.db_path}")

    # =========================================================================
    # Entity Operations
    # =========================================================================

    def add_entity(
        self,
        entity_type: str,
        canonical_name: str,
        aliases: List[str] = None,
        data: Dict[str, Any] = None,
        turn_number: int = 0,
        confidence: float = 0.5
    ) -> int:
        """
        Add or update an entity in the knowledge graph.

        If an entity with the same type and canonical name exists, it will be updated.

        Args:
            entity_type: Type of entity (vendor, product, person, site, topic, thread)
            canonical_name: Normalized/canonical name for the entity
            aliases: Alternative names for the entity
            data: Additional structured data (url, price_range, location, etc.)
            turn_number: Turn number where entity was discovered
            confidence: Confidence score for entity identification (0.0-1.0)

        Returns:
            Entity ID (existing or newly created)
        """
        conn = self._get_connection()
        aliases_json = json.dumps(aliases or [])
        data_json = json.dumps(data or {})

        with self._lock:
            # Check if entity exists
            cursor = conn.execute("""
                SELECT id, first_seen_turn, aliases, entity_data
                FROM entities
                WHERE entity_type = ? AND canonical_name = ?
            """, (entity_type, canonical_name))

            row = cursor.fetchone()

            if row:
                # Update existing entity
                entity_id = row["id"]
                existing_first_seen = row["first_seen_turn"]

                # Merge aliases
                existing_aliases = json.loads(row["aliases"]) if row["aliases"] else []
                merged_aliases = list(set(existing_aliases + (aliases or [])))

                # Merge entity data
                existing_data = json.loads(row["entity_data"]) if row["entity_data"] else {}
                merged_data = {**existing_data, **(data or {})}

                conn.execute("""
                    UPDATE entities
                    SET aliases = ?,
                        entity_data = ?,
                        last_seen_turn = ?,
                        confidence = MAX(confidence, ?),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    json.dumps(merged_aliases),
                    json.dumps(merged_data),
                    max(turn_number, existing_first_seen),
                    confidence,
                    entity_id
                ))

                logger.debug(f"[KnowledgeGraphDB] Updated entity {entity_id}: {canonical_name}")
            else:
                # Create new entity
                cursor = conn.execute("""
                    INSERT INTO entities
                    (entity_type, canonical_name, aliases, entity_data,
                     first_seen_turn, last_seen_turn, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    entity_type,
                    canonical_name,
                    aliases_json,
                    data_json,
                    turn_number,
                    turn_number,
                    confidence
                ))
                entity_id = cursor.lastrowid

                logger.debug(f"[KnowledgeGraphDB] Created entity {entity_id}: {canonical_name}")

            conn.commit()
            return entity_id

    def find_entity(
        self,
        name: str,
        entity_type: str = None
    ) -> Optional[Entity]:
        """
        Find an entity by name (canonical or alias) and optionally type.

        Args:
            name: Name to search for (case-insensitive)
            entity_type: Optional type filter

        Returns:
            Entity if found, None otherwise
        """
        conn = self._get_connection()
        name_lower = name.lower()

        # Build query
        if entity_type:
            # First try exact match on canonical name
            cursor = conn.execute("""
                SELECT * FROM entities
                WHERE entity_type = ? AND LOWER(canonical_name) = ?
            """, (entity_type, name_lower))
        else:
            cursor = conn.execute("""
                SELECT * FROM entities
                WHERE LOWER(canonical_name) = ?
            """, (name_lower,))

        row = cursor.fetchone()

        if row:
            return self._row_to_entity(row)

        # Try searching in aliases
        if entity_type:
            cursor = conn.execute("""
                SELECT * FROM entities
                WHERE entity_type = ?
            """, (entity_type,))
        else:
            cursor = conn.execute("SELECT * FROM entities")

        for row in cursor:
            aliases = json.loads(row["aliases"]) if row["aliases"] else []
            if any(alias.lower() == name_lower for alias in aliases):
                return self._row_to_entity(row)

        return None

    def get_entity(self, entity_id: int) -> Optional[Entity]:
        """
        Get an entity by ID.

        Args:
            entity_id: Entity ID

        Returns:
            Entity if found, None otherwise
        """
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
        row = cursor.fetchone()

        if row:
            return self._row_to_entity(row)
        return None

    def get_entities_by_type(
        self,
        entity_type: str,
        limit: int = 100
    ) -> List[Entity]:
        """
        Get all entities of a specific type.

        Args:
            entity_type: Type of entities to retrieve
            limit: Maximum number of results

        Returns:
            List of entities
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT * FROM entities
            WHERE entity_type = ?
            ORDER BY last_seen_turn DESC
            LIMIT ?
        """, (entity_type, limit))

        return [self._row_to_entity(row) for row in cursor]

    def search_entities(
        self,
        query: str,
        entity_type: str = None,
        limit: int = 20
    ) -> List[Entity]:
        """
        Search entities by name (partial match).

        Args:
            query: Search query
            entity_type: Optional type filter
            limit: Maximum number of results

        Returns:
            List of matching entities
        """
        conn = self._get_connection()
        pattern = f"%{query}%"

        if entity_type:
            cursor = conn.execute("""
                SELECT * FROM entities
                WHERE entity_type = ?
                AND (canonical_name LIKE ? OR aliases LIKE ?)
                ORDER BY confidence DESC, last_seen_turn DESC
                LIMIT ?
            """, (entity_type, pattern, pattern, limit))
        else:
            cursor = conn.execute("""
                SELECT * FROM entities
                WHERE canonical_name LIKE ? OR aliases LIKE ?
                ORDER BY confidence DESC, last_seen_turn DESC
                LIMIT ?
            """, (pattern, pattern, limit))

        return [self._row_to_entity(row) for row in cursor]

    def _row_to_entity(self, row: sqlite3.Row) -> Entity:
        """Convert a database row to an Entity."""
        return Entity(
            id=row["id"],
            entity_type=row["entity_type"],
            canonical_name=row["canonical_name"],
            aliases=json.loads(row["aliases"]) if row["aliases"] else [],
            confidence=row["confidence"],
            entity_data=json.loads(row["entity_data"]) if row["entity_data"] else {},
            first_seen_turn=row["first_seen_turn"],
            last_seen_turn=row["last_seen_turn"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
        )

    # =========================================================================
    # Relationship Operations
    # =========================================================================

    def add_relationship(
        self,
        source_id: int,
        target_id: int,
        relationship_type: str,
        confidence: float = 0.5,
        weight: float = 1.0,
        source_document: str = None,
        turn: int = 0
    ) -> int:
        """
        Add a relationship between two entities.

        If the relationship already exists, its confidence and weight are updated
        (increased if new confidence is higher).

        Args:
            source_id: Source entity ID
            target_id: Target entity ID
            relationship_type: Type of relationship (sells, recommends, mentioned_in, etc.)
            confidence: Confidence score (0.0-1.0)
            weight: Strength of relationship (higher = stronger)
            source_document: Document where relationship was discovered
            turn: Turn number where relationship was discovered

        Returns:
            Relationship ID
        """
        conn = self._get_connection()

        with self._lock:
            # Check if relationship exists
            cursor = conn.execute("""
                SELECT id, confidence, weight
                FROM relationships
                WHERE source_entity_id = ? AND target_entity_id = ? AND relationship_type = ?
            """, (source_id, target_id, relationship_type))

            row = cursor.fetchone()

            if row:
                # Update existing relationship (strengthen it)
                rel_id = row["id"]
                new_confidence = max(row["confidence"], confidence)
                new_weight = row["weight"] + weight  # Accumulate weight

                conn.execute("""
                    UPDATE relationships
                    SET confidence = ?,
                        weight = ?,
                        source_document = COALESCE(?, source_document),
                        source_turn = MAX(source_turn, ?)
                    WHERE id = ?
                """, (new_confidence, new_weight, source_document, turn, rel_id))

                logger.debug(f"[KnowledgeGraphDB] Updated relationship {rel_id}")
            else:
                # Create new relationship
                cursor = conn.execute("""
                    INSERT INTO relationships
                    (source_entity_id, target_entity_id, relationship_type,
                     confidence, weight, source_document, source_turn)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (source_id, target_id, relationship_type, confidence, weight, source_document, turn))

                rel_id = cursor.lastrowid
                logger.debug(f"[KnowledgeGraphDB] Created relationship {rel_id}")

            conn.commit()
            return rel_id

    def get_relationships(
        self,
        entity_id: int,
        relationship_type: str = None,
        direction: str = "outgoing"
    ) -> List[Relationship]:
        """
        Get relationships for an entity.

        Args:
            entity_id: Entity ID to get relationships for
            relationship_type: Optional filter by relationship type
            direction: "outgoing" (entity is source), "incoming" (entity is target), or "both"

        Returns:
            List of Relationships with populated source/target entities
        """
        conn = self._get_connection()
        relationships = []

        # Build queries based on direction
        if direction in ("outgoing", "both"):
            if relationship_type:
                cursor = conn.execute("""
                    SELECT r.*,
                           s.id as s_id, s.entity_type as s_type, s.canonical_name as s_name,
                           s.aliases as s_aliases, s.confidence as s_confidence,
                           s.entity_data as s_data, s.first_seen_turn as s_first,
                           s.last_seen_turn as s_last, s.created_at as s_created, s.updated_at as s_updated,
                           t.id as t_id, t.entity_type as t_type, t.canonical_name as t_name,
                           t.aliases as t_aliases, t.confidence as t_confidence,
                           t.entity_data as t_data, t.first_seen_turn as t_first,
                           t.last_seen_turn as t_last, t.created_at as t_created, t.updated_at as t_updated
                    FROM relationships r
                    JOIN entities s ON r.source_entity_id = s.id
                    JOIN entities t ON r.target_entity_id = t.id
                    WHERE r.source_entity_id = ? AND r.relationship_type = ?
                    ORDER BY r.weight DESC, r.confidence DESC
                """, (entity_id, relationship_type))
            else:
                cursor = conn.execute("""
                    SELECT r.*,
                           s.id as s_id, s.entity_type as s_type, s.canonical_name as s_name,
                           s.aliases as s_aliases, s.confidence as s_confidence,
                           s.entity_data as s_data, s.first_seen_turn as s_first,
                           s.last_seen_turn as s_last, s.created_at as s_created, s.updated_at as s_updated,
                           t.id as t_id, t.entity_type as t_type, t.canonical_name as t_name,
                           t.aliases as t_aliases, t.confidence as t_confidence,
                           t.entity_data as t_data, t.first_seen_turn as t_first,
                           t.last_seen_turn as t_last, t.created_at as t_created, t.updated_at as t_updated
                    FROM relationships r
                    JOIN entities s ON r.source_entity_id = s.id
                    JOIN entities t ON r.target_entity_id = t.id
                    WHERE r.source_entity_id = ?
                    ORDER BY r.weight DESC, r.confidence DESC
                """, (entity_id,))

            for row in cursor:
                relationships.append(self._row_to_relationship(row))

        if direction in ("incoming", "both"):
            if relationship_type:
                cursor = conn.execute("""
                    SELECT r.*,
                           s.id as s_id, s.entity_type as s_type, s.canonical_name as s_name,
                           s.aliases as s_aliases, s.confidence as s_confidence,
                           s.entity_data as s_data, s.first_seen_turn as s_first,
                           s.last_seen_turn as s_last, s.created_at as s_created, s.updated_at as s_updated,
                           t.id as t_id, t.entity_type as t_type, t.canonical_name as t_name,
                           t.aliases as t_aliases, t.confidence as t_confidence,
                           t.entity_data as t_data, t.first_seen_turn as t_first,
                           t.last_seen_turn as t_last, t.created_at as t_created, t.updated_at as t_updated
                    FROM relationships r
                    JOIN entities s ON r.source_entity_id = s.id
                    JOIN entities t ON r.target_entity_id = t.id
                    WHERE r.target_entity_id = ? AND r.relationship_type = ?
                    ORDER BY r.weight DESC, r.confidence DESC
                """, (entity_id, relationship_type))
            else:
                cursor = conn.execute("""
                    SELECT r.*,
                           s.id as s_id, s.entity_type as s_type, s.canonical_name as s_name,
                           s.aliases as s_aliases, s.confidence as s_confidence,
                           s.entity_data as s_data, s.first_seen_turn as s_first,
                           s.last_seen_turn as s_last, s.created_at as s_created, s.updated_at as s_updated,
                           t.id as t_id, t.entity_type as t_type, t.canonical_name as t_name,
                           t.aliases as t_aliases, t.confidence as t_confidence,
                           t.entity_data as t_data, t.first_seen_turn as t_first,
                           t.last_seen_turn as t_last, t.created_at as t_created, t.updated_at as t_updated
                    FROM relationships r
                    JOIN entities s ON r.source_entity_id = s.id
                    JOIN entities t ON r.target_entity_id = t.id
                    WHERE r.target_entity_id = ?
                    ORDER BY r.weight DESC, r.confidence DESC
                """, (entity_id,))

            for row in cursor:
                relationships.append(self._row_to_relationship(row))

        return relationships

    def get_related_entities(
        self,
        entity_id: int,
        relationship_type: str,
        direction: str = "outgoing"
    ) -> List[Entity]:
        """
        Get entities related to an entity by a specific relationship type.

        This is a convenience method that extracts just the related entities
        from relationship queries.

        Args:
            entity_id: Entity ID
            relationship_type: Type of relationship
            direction: "outgoing" returns targets, "incoming" returns sources

        Returns:
            List of related entities
        """
        relationships = self.get_relationships(entity_id, relationship_type, direction)

        if direction == "outgoing":
            return [r.target_entity for r in relationships]
        else:
            return [r.source_entity for r in relationships]

    def _row_to_relationship(self, row: sqlite3.Row) -> Relationship:
        """Convert a database row to a Relationship with populated entities."""
        source_entity = Entity(
            id=row["s_id"],
            entity_type=row["s_type"],
            canonical_name=row["s_name"],
            aliases=json.loads(row["s_aliases"]) if row["s_aliases"] else [],
            confidence=row["s_confidence"],
            entity_data=json.loads(row["s_data"]) if row["s_data"] else {},
            first_seen_turn=row["s_first"],
            last_seen_turn=row["s_last"],
            created_at=datetime.fromisoformat(row["s_created"]) if row["s_created"] else None,
            updated_at=datetime.fromisoformat(row["s_updated"]) if row["s_updated"] else None
        )

        target_entity = Entity(
            id=row["t_id"],
            entity_type=row["t_type"],
            canonical_name=row["t_name"],
            aliases=json.loads(row["t_aliases"]) if row["t_aliases"] else [],
            confidence=row["t_confidence"],
            entity_data=json.loads(row["t_data"]) if row["t_data"] else {},
            first_seen_turn=row["t_first"],
            last_seen_turn=row["t_last"],
            created_at=datetime.fromisoformat(row["t_created"]) if row["t_created"] else None,
            updated_at=datetime.fromisoformat(row["t_updated"]) if row["t_updated"] else None
        )

        return Relationship(
            id=row["id"],
            source_entity=source_entity,
            target_entity=target_entity,
            relationship_type=row["relationship_type"],
            confidence=row["confidence"],
            weight=row["weight"],
            source_document=row["source_document"],
            source_turn=row["source_turn"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
        )

    # =========================================================================
    # Entity Mention Operations
    # =========================================================================

    def add_mention(
        self,
        entity_id: int,
        document_path: str,
        turn_number: int = 0,
        context: str = "",
        property_name: str = None,
        property_value: str = None,
        confidence: float = 0.5
    ) -> int:
        """
        Add a mention of an entity in a document.

        Args:
            entity_id: ID of the mentioned entity
            document_path: Path to the document containing the mention
            turn_number: Turn number where mention was found
            context: Surrounding text snippet for context
            property_name: Optional property being mentioned (e.g., "price", "url")
            property_value: Optional value of the property
            confidence: Confidence score for the mention

        Returns:
            Mention ID
        """
        conn = self._get_connection()

        with self._lock:
            cursor = conn.execute("""
                INSERT INTO entity_mentions
                (entity_id, document_path, turn_number, mention_context,
                 property_name, property_value, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (entity_id, document_path, turn_number, context[:500] if context else "",
                  property_name, property_value, confidence))

            mention_id = cursor.lastrowid

            # Update entity's last_seen_turn
            conn.execute("""
                UPDATE entities
                SET last_seen_turn = MAX(last_seen_turn, ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (turn_number, entity_id))

            conn.commit()

            logger.debug(f"[KnowledgeGraphDB] Added mention {mention_id} for entity {entity_id}")
            return mention_id

    def get_entity_mentions(
        self,
        entity_id: int,
        limit: int = 50
    ) -> List[EntityMention]:
        """
        Get all mentions of an entity.

        Args:
            entity_id: Entity ID
            limit: Maximum number of results

        Returns:
            List of EntityMention objects
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT * FROM entity_mentions
            WHERE entity_id = ?
            ORDER BY turn_number DESC, created_at DESC
            LIMIT ?
        """, (entity_id, limit))

        return [self._row_to_mention(row) for row in cursor]

    def get_document_mentions(
        self,
        document_path: str
    ) -> List[EntityMention]:
        """
        Get all entity mentions in a document.

        Args:
            document_path: Path to the document

        Returns:
            List of EntityMention objects
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT * FROM entity_mentions
            WHERE document_path = ?
            ORDER BY created_at DESC
        """, (document_path,))

        return [self._row_to_mention(row) for row in cursor]

    def _row_to_mention(self, row: sqlite3.Row) -> EntityMention:
        """Convert a database row to an EntityMention."""
        return EntityMention(
            id=row["id"],
            entity_id=row["entity_id"],
            document_path=row["document_path"],
            turn_number=row["turn_number"],
            context=row["mention_context"] or "",
            property_name=row["property_name"],
            property_value=row["property_value"],
            confidence=row["confidence"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
        )

    # =========================================================================
    # Backlink Operations
    # =========================================================================

    def add_backlink(
        self,
        source_file: str,
        target_file: str,
        link_text: str,
        link_type: str = "wiki",
        line_number: int = None
    ) -> int:
        """
        Register a backlink between documents.

        Args:
            source_file: File containing the link
            target_file: File being linked to
            link_text: The link text (e.g., "[[Syrian Hamster]]")
            link_type: Type of link (wiki, entity, url)
            line_number: Optional line number where link appears

        Returns:
            Backlink ID
        """
        conn = self._get_connection()

        with self._lock:
            # Use INSERT OR REPLACE to handle duplicates
            cursor = conn.execute("""
                INSERT OR REPLACE INTO backlinks
                (source_file, target_file, link_text, link_type, line_number)
                VALUES (?, ?, ?, ?, ?)
            """, (source_file, target_file, link_text, link_type, line_number))

            backlink_id = cursor.lastrowid
            conn.commit()

            logger.debug(f"[KnowledgeGraphDB] Added backlink: {source_file} -> {target_file}")
            return backlink_id

    def get_backlinks_to(self, target_file: str) -> List[Dict[str, Any]]:
        """
        Get all documents linking TO this file.

        Args:
            target_file: Target file path

        Returns:
            List of dicts with source_file, link_text, link_type, line_number
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT source_file, link_text, link_type, line_number, created_at
            FROM backlinks
            WHERE target_file = ?
            ORDER BY created_at DESC
        """, (target_file,))

        return [
            {
                "source_file": row["source_file"],
                "link_text": row["link_text"],
                "link_type": row["link_type"],
                "line_number": row["line_number"],
                "created_at": row["created_at"]
            }
            for row in cursor
        ]

    def get_links_from(self, source_file: str) -> List[Dict[str, Any]]:
        """
        Get all documents this file links TO.

        Args:
            source_file: Source file path

        Returns:
            List of dicts with target_file, link_text, link_type, line_number
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT target_file, link_text, link_type, line_number, created_at
            FROM backlinks
            WHERE source_file = ?
            ORDER BY line_number, created_at
        """, (source_file,))

        return [
            {
                "target_file": row["target_file"],
                "link_text": row["link_text"],
                "link_type": row["link_type"],
                "line_number": row["line_number"],
                "created_at": row["created_at"]
            }
            for row in cursor
        ]

    def delete_backlinks_from(self, source_file: str) -> int:
        """
        Delete all backlinks from a source file.

        Useful when re-scanning a file to refresh its links.

        Args:
            source_file: Source file path

        Returns:
            Number of backlinks deleted
        """
        conn = self._get_connection()

        with self._lock:
            cursor = conn.execute("""
                DELETE FROM backlinks WHERE source_file = ?
            """, (source_file,))
            conn.commit()
            return cursor.rowcount

    def rebuild_backlink_index(self):
        """
        Placeholder for scanner integration.

        This method will be called by the BacklinkScanner to rebuild the
        entire backlink index by scanning the obsidian_memory vault.

        For now, this is a no-op. The BacklinkScanner will call
        delete_backlinks_from() and add_backlink() directly.
        """
        logger.info("[KnowledgeGraphDB] rebuild_backlink_index() called - awaiting scanner integration")
        pass

    # =========================================================================
    # Statistics and Maintenance
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge graph statistics."""
        conn = self._get_connection()

        entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        relationship_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        mention_count = conn.execute("SELECT COUNT(*) FROM entity_mentions").fetchone()[0]
        backlink_count = conn.execute("SELECT COUNT(*) FROM backlinks").fetchone()[0]

        # Entity type breakdown
        cursor = conn.execute("""
            SELECT entity_type, COUNT(*) as count
            FROM entities
            GROUP BY entity_type
            ORDER BY count DESC
        """)
        entity_types = {row["entity_type"]: row["count"] for row in cursor}

        # Relationship type breakdown
        cursor = conn.execute("""
            SELECT relationship_type, COUNT(*) as count
            FROM relationships
            GROUP BY relationship_type
            ORDER BY count DESC
        """)
        relationship_types = {row["relationship_type"]: row["count"] for row in cursor}

        return {
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "mention_count": mention_count,
            "backlink_count": backlink_count,
            "entity_types": entity_types,
            "relationship_types": relationship_types,
            "db_path": str(self.db_path),
            "schema_version": SCHEMA_VERSION
        }

    def vacuum(self):
        """Compact the database file."""
        conn = self._get_connection()
        conn.execute("VACUUM")
        logger.info("[KnowledgeGraphDB] Database vacuumed")


# =============================================================================
# Global Singleton
# =============================================================================

_KNOWLEDGE_GRAPH_DB: Optional[KnowledgeGraphDB] = None


def get_knowledge_graph_db(db_path: Path = None) -> KnowledgeGraphDB:
    """
    Get the global KnowledgeGraphDB instance.

    Args:
        db_path: Optional custom database path (only used on first call)

    Returns:
        KnowledgeGraphDB singleton instance
    """
    global _KNOWLEDGE_GRAPH_DB
    if _KNOWLEDGE_GRAPH_DB is None:
        _KNOWLEDGE_GRAPH_DB = KnowledgeGraphDB(db_path)
    return _KNOWLEDGE_GRAPH_DB


def reset_knowledge_graph_db():
    """Reset the global singleton (for testing)."""
    global _KNOWLEDGE_GRAPH_DB
    _KNOWLEDGE_GRAPH_DB = None
