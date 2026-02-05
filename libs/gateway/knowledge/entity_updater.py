"""
EntityUpdater: Updates entity documents when new research arrives.

This module implements the compounding context pattern where entity documents
grow over time as new information is discovered. When research results arrive,
the EntityUpdater:
1. Extracts entities using EntityExtractor
2. Finds or creates each entity in the knowledge graph
3. Loads or creates the EntityDocument
4. Updates with new properties and mentions
5. Saves the updated document

This creates a knowledge base that compounds - each research turn adds to
the accumulated understanding of entities.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

from .entity_document import EntityDocument

logger = logging.getLogger(__name__)


class EntityUpdater:
    """
    Updates entity documents when new information is discovered.

    Works in conjunction with KnowledgeGraphDB and EntityExtractor to
    maintain entity-centric documents that accumulate information over time.

    Usage:
        from libs.gateway.knowledge.knowledge_graph_db import KnowledgeGraphDB

        kg = KnowledgeGraphDB()
        vault_path = Path("panda_system_docs/obsidian_memory")
        updater = EntityUpdater(kg, vault_path)

        # Process research results from a turn
        updater.process_research_results(research_result, turn_number=64)
    """

    def __init__(self, kg: Any, vault_path: Path):
        """
        Initialize the EntityUpdater.

        Args:
            kg: KnowledgeGraphDB instance for entity storage and lookup
            vault_path: Path to the Obsidian vault root
        """
        self.kg = kg
        self.vault_path = vault_path

    def process_research_results(self, results: Dict[str, Any], turn_number: int):
        """
        Process research results and update relevant entity documents.

        Extracts entities from research findings, ensures they exist in the
        knowledge graph, and updates their markdown documents with new
        information.

        Args:
            results: Research results dict containing:
                - findings: List of finding dicts with content, source, etc.
                - vendors: List of vendor mentions (if extracted)
                - products: List of product mentions (if extracted)
            turn_number: The turn number where this research occurred
        """
        # Import here to avoid circular imports
        try:
            from .entity_extractor import EntityExtractor
        except ImportError:
            logger.warning(
                "[EntityUpdater] EntityExtractor not available, "
                "skipping entity extraction"
            )
            return

        extractor = EntityExtractor()

        # Extract entities from research results
        entities = extractor.extract_from_research(results)

        if not entities:
            logger.debug(
                f"[EntityUpdater] No entities extracted from turn {turn_number}"
            )
            return

        logger.info(
            f"[EntityUpdater] Processing {len(entities)} entities from turn {turn_number}"
        )

        for entity in entities:
            try:
                self._process_entity(entity, turn_number)
            except Exception as e:
                logger.error(
                    f"[EntityUpdater] Failed to process entity "
                    f"{entity.canonical_name}: {e}"
                )

    def _process_entity(self, entity: Any, turn_number: int):
        """
        Process a single extracted entity.

        Args:
            entity: ExtractedEntity from EntityExtractor
            turn_number: The turn where this entity was found
        """
        # Check if entity exists in knowledge graph
        existing = self.kg.find_entity(entity.canonical_name, entity.entity_type)

        if existing:
            entity_id = existing.id
            # Load existing document
            doc = self._load_entity_document(existing)
            if doc is None:
                # Document doesn't exist but entity does - create new doc
                doc = EntityDocument(
                    entity_type=entity.entity_type,
                    canonical_name=entity.canonical_name,
                    entity_id=entity_id
                )
        else:
            # Create new entity in knowledge graph
            entity_id = self.kg.add_entity(
                entity_type=entity.entity_type,
                canonical_name=entity.canonical_name,
                aliases=[entity.text] if entity.text != entity.canonical_name else [],
                data=entity.properties,
                turn_number=turn_number
            )
            # Create new document
            doc = EntityDocument(
                entity_type=entity.entity_type,
                canonical_name=entity.canonical_name,
                entity_id=entity_id
            )

        # Update document with new information
        self._update_document(doc, entity, turn_number)

        # Save updated document
        doc.save(self.vault_path)

        logger.debug(
            f"[EntityUpdater] Updated {entity.entity_type}:{entity.canonical_name} "
            f"(id={entity_id})"
        )

    def _update_document(
        self,
        doc: EntityDocument,
        entity: Any,
        turn_number: int
    ):
        """
        Update an EntityDocument with information from an extracted entity.

        Args:
            doc: EntityDocument to update
            entity: ExtractedEntity with new information
            turn_number: Turn number for source attribution
        """
        # Add/update properties
        for prop_name, prop_value in entity.properties.items():
            if prop_value:  # Only add non-empty properties
                doc.add_property(
                    name=prop_name,
                    value=str(prop_value),
                    source=f"turn_{turn_number}"
                )

        # Add mention
        doc.add_mention(
            turn_number=turn_number,
            context=entity.context if hasattr(entity, 'context') else ""
        )

    def _load_entity_document(self, entity: Any) -> Optional[EntityDocument]:
        """
        Load existing entity document from the vault.

        Searches for the document in the appropriate type directory.

        Args:
            entity: Entity object from knowledge graph with type and canonical_name

        Returns:
            EntityDocument if found, None otherwise
        """
        file_path = self._find_document_path(
            entity.entity_type,
            entity.canonical_name
        )

        if file_path and file_path.exists():
            return EntityDocument.load(file_path)

        return None

    def _find_document_path(
        self,
        entity_type: str,
        canonical_name: str
    ) -> Optional[Path]:
        """
        Find the path where an entity document should be stored.

        Uses the type-to-directory mapping from EntityDocument.

        Args:
            entity_type: Type of entity (vendor, product, site, etc.)
            canonical_name: Canonical name of the entity

        Returns:
            Path to the document file (may not exist yet)
        """
        dir_name = EntityDocument.TYPE_DIRECTORIES.get(
            entity_type,
            "Knowledge/Other"
        )
        dir_path = self.vault_path / dir_name

        # Sanitize filename
        filename = EntityDocument._sanitize_filename(canonical_name)
        file_path = dir_path / f"{filename}.md"

        return file_path

    def update_entity_relationships(
        self,
        source_entity_id: int,
        target_entity_id: int,
        relationship: str,
        turn_number: int
    ):
        """
        Update entity documents with a new relationship.

        When a relationship is discovered (e.g., vendor sells product),
        updates both entity documents with bidirectional links.

        Args:
            source_entity_id: ID of the source entity
            target_entity_id: ID of the target entity
            relationship: Type of relationship
            turn_number: Turn where relationship was discovered
        """
        # Get entities from knowledge graph
        source = self.kg.get_entity_by_id(source_entity_id)
        target = self.kg.get_entity_by_id(target_entity_id)

        if not source or not target:
            logger.warning(
                f"[EntityUpdater] Could not find entities for relationship: "
                f"{source_entity_id} -> {target_entity_id}"
            )
            return

        # Update source document
        source_doc = self._load_entity_document(source)
        if source_doc is None:
            source_doc = EntityDocument(
                entity_type=source.entity_type,
                canonical_name=source.canonical_name,
                entity_id=source.id
            )

        source_doc.add_related_entity(
            entity_id=target.id,
            entity_type=target.entity_type,
            name=target.canonical_name,
            relationship=relationship
        )
        source_doc.save(self.vault_path)

        # Update target document with inverse relationship
        target_doc = self._load_entity_document(target)
        if target_doc is None:
            target_doc = EntityDocument(
                entity_type=target.entity_type,
                canonical_name=target.canonical_name,
                entity_id=target.id
            )

        # Determine inverse relationship
        inverse = self._get_inverse_relationship(relationship)
        target_doc.add_related_entity(
            entity_id=source.id,
            entity_type=source.entity_type,
            name=source.canonical_name,
            relationship=inverse
        )
        target_doc.save(self.vault_path)

        logger.debug(
            f"[EntityUpdater] Added relationship: "
            f"{source.canonical_name} --{relationship}--> {target.canonical_name}"
        )

    def _get_inverse_relationship(self, relationship: str) -> str:
        """
        Get the inverse of a relationship type.

        Args:
            relationship: Forward relationship type

        Returns:
            Inverse relationship type
        """
        inverses = {
            "sells": "sold_by",
            "sold_by": "sells",
            "recommends": "recommended_by",
            "recommended_by": "recommends",
            "competes_with": "competes_with",  # Symmetric
            "mentioned_in": "mentions",
            "mentions": "mentioned_in",
            "parent_of": "child_of",
            "child_of": "parent_of",
            "related_to": "related_to",  # Symmetric
        }
        return inverses.get(relationship, f"inverse_{relationship}")

    def rebuild_entity_documents(self):
        """
        Rebuild all entity documents from the knowledge graph.

        Useful for migration or recovery. Iterates through all entities
        in the knowledge graph and regenerates their documents.
        """
        logger.info("[EntityUpdater] Rebuilding all entity documents")

        # Get all entities from knowledge graph
        entities = self.kg.get_all_entities()
        rebuilt = 0

        for entity in entities:
            try:
                # Create document from entity data
                doc = EntityDocument(
                    entity_type=entity.entity_type,
                    canonical_name=entity.canonical_name,
                    entity_id=entity.id
                )

                # Add properties from entity data
                if entity.entity_data:
                    for key, value in entity.entity_data.items():
                        if value:
                            doc.add_property(key, str(value), "knowledge_graph")

                # Get relationships
                relationships = self.kg.get_relationships(entity.id)
                for rel in relationships:
                    doc.add_related_entity(
                        entity_id=rel.target_entity.id,
                        entity_type=rel.target_entity.entity_type,
                        name=rel.target_entity.canonical_name,
                        relationship=rel.relationship_type
                    )

                # Get mentions
                mentions = self.kg.get_mentions(entity.id)
                for mention in mentions:
                    doc.mentions.append({
                        "turn": mention.turn_number,
                        "context": mention.mention_context or "",
                        "date": mention.created_at if hasattr(mention, 'created_at') else ""
                    })

                # Save document
                doc.save(self.vault_path)
                rebuilt += 1

            except Exception as e:
                logger.error(
                    f"[EntityUpdater] Failed to rebuild document for "
                    f"{entity.canonical_name}: {e}"
                )

        logger.info(f"[EntityUpdater] Rebuilt {rebuilt} entity documents")


# =============================================================================
# Global Singleton
# =============================================================================

_ENTITY_UPDATER: Optional[EntityUpdater] = None


def get_entity_updater(
    kg: Optional[Any] = None,
    vault_path: Optional[Path] = None
) -> EntityUpdater:
    """
    Get the global EntityUpdater instance.

    Creates the instance on first call. If kg or vault_path are provided,
    they override the defaults.

    Args:
        kg: Optional KnowledgeGraphDB instance
        vault_path: Optional path to Obsidian vault

    Returns:
        EntityUpdater instance
    """
    global _ENTITY_UPDATER

    if _ENTITY_UPDATER is None:
        # Import here to avoid circular imports at module load time
        try:
            from .knowledge_graph_db import get_knowledge_graph_db
            kg = kg or get_knowledge_graph_db()
        except ImportError:
            logger.warning(
                "[EntityUpdater] KnowledgeGraphDB not available, "
                "updater will not function"
            )
            kg = None

        vault_path = vault_path or Path("panda_system_docs/obsidian_memory")

        if kg is None:
            # Create a dummy updater that logs warnings
            logger.warning(
                "[EntityUpdater] Creating updater without knowledge graph - "
                "entity updates will be skipped"
            )

        _ENTITY_UPDATER = EntityUpdater(kg, vault_path)

    return _ENTITY_UPDATER
