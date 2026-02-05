"""
Panda Knowledge Module - Knowledge graph and entity management.

Implements the persistent knowledge layer for compounding context across turns:
- Knowledge graph database for entities and relationships
- Entity document generation (Obsidian-style markdown)
- Backlink scanning for cross-document navigation

Architecture Reference:
    architecture/concepts/MEMORY_ARCHITECTURE.md

Integration Notes:
- The knowledge graph is a primary store (not cache) for structured memory
- Currently under-utilized in Phase 2 retrieval which focuses on turn summaries
- Future integration: Phase 2.1 should query knowledge graph for entity context
- Entity types are extensible; the TYPE_DIRECTORIES mapping provides defaults
  but new types map to Knowledge/Other/ automatically

Contains:
- KnowledgeGraphDB: SQLite-based knowledge graph with entity/relationship storage
- EntityDocument: Entity-centric markdown documents that accumulate information
- EntityExtractor: Extract entities from research outputs
- BacklinkScanner: Scan for backlinks between documents
"""

from libs.gateway.knowledge.knowledge_graph_db import KnowledgeGraphDB

__all__ = [
    "KnowledgeGraphDB",
]
