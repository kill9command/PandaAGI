"""
Research Handler - Research document writing and knowledge graph updates.

Extracted from UnifiedFlow to handle:
- research.md writing for internet.research results
- Knowledge graph entity extraction and updates

Architecture Reference:
- architecture/main-system-patterns/phase8-save.md
- architecture/Implementation/KNOWLEDGE_GRAPH_AND_UI_PLAN.md#Part 3: Compounding Context
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument

logger = logging.getLogger(__name__)


class ResearchHandler:
    """
    Handles research document creation and knowledge graph updates.

    Responsibilities:
    - Write research.md documents from internet.research results
    - Index research documents for future retrieval
    - Extract entities and update knowledge graph
    """

    def __init__(self, turns_dir: Path = None):
        """Initialize the research handler."""
        self.turns_dir = turns_dir

    async def write_research_documents(
        self,
        tool_results: List[Dict[str, Any]],
        context_doc: "ContextDocument"
    ):
        """Write research documents for internet.research results."""
        from libs.gateway.research.research_document import ResearchDocumentWriter
        from libs.gateway.research.research_index_db import get_research_index_db

        turns_dir = self.turns_dir
        if not turns_dir:
            # Fallback to default
            from libs.gateway.persistence.user_paths import UserPathResolver
            turns_dir = UserPathResolver.get_turns_dir("default")

        research_writer = ResearchDocumentWriter(turns_dir=turns_dir)
        research_index = get_research_index_db()

        for result in tool_results:
            if result.get("tool") != "internet.research":
                continue
            if result.get("status") != "success":
                continue

            raw_result = result.get("raw_result", {})
            if not raw_result.get("findings"):
                continue

            try:
                resolved_query = result.get("resolved_query", context_doc.query)

                doc = research_writer.create_from_tool_results(
                    turn_number=context_doc.turn_number,
                    session_id=context_doc.session_id,
                    query=resolved_query,
                    tool_results=raw_result,
                    intent="transactional"
                )

                turn_dir = turns_dir / f"turn_{context_doc.turn_number:06d}"
                research_writer.write(doc, turn_dir)

                research_index.index_research(
                    id=doc.id,
                    turn_number=doc.turn_number,
                    session_id=doc.session_id,
                    primary_topic=doc.topic.primary_topic,
                    keywords=doc.topic.keywords,
                    intent=doc.topic.intent,
                    completeness=doc.quality.completeness,
                    source_quality=doc.quality.source_quality,
                    overall_quality=doc.quality.overall,
                    confidence_initial=doc.confidence.initial,
                    decay_rate=doc.confidence.decay_rate,
                    created_at=doc.created_at.timestamp(),
                    expires_at=doc.expires_at.timestamp() if doc.expires_at else None,
                    scope=doc.scope,
                    doc_path=str(turn_dir / "research.md"),
                    content_types=doc.topic.content_types
                )

                logger.info(f"[ResearchHandler] Created research document: {doc.id}")

            except Exception as e:
                logger.error(f"[ResearchHandler] Failed to write research document: {e}")
                raise RuntimeError(f"Failed to write research document: {e}") from e

    async def update_knowledge_graph(
        self,
        tool_results: List[Dict[str, Any]],
        context_doc: "ContextDocument"
    ):
        """
        Update knowledge graph with entities extracted from research results.

        Extracts vendors, products, sites, and other entities from internet.research
        results and stores them in the knowledge graph for compounding context.

        Architecture Reference:
            architecture/Implementation/KNOWLEDGE_GRAPH_AND_UI_PLAN.md#Part 3: Compounding Context
        """
        try:
            from libs.gateway.knowledge.entity_updater import get_entity_updater
        except ImportError:
            logger.debug("[ResearchHandler] EntityUpdater not available, skipping knowledge graph update")
            return

        try:
            updater = get_entity_updater()
            if updater.kg is None:
                logger.debug("[ResearchHandler] KnowledgeGraphDB not initialized, skipping entity extraction")
                return

            for result in tool_results:
                if result.get("tool") != "internet.research":
                    continue
                if result.get("status") != "success":
                    continue

                raw_result = result.get("raw_result", {})
                if not raw_result:
                    continue

                # Process research results through entity updater
                updater.process_research_results(raw_result, context_doc.turn_number)
                logger.info(f"[ResearchHandler] Updated knowledge graph from research (turn {context_doc.turn_number})")

        except Exception as e:
            # Non-fatal: don't break the flow if entity extraction fails
            logger.warning(f"[ResearchHandler] Knowledge graph update failed (non-fatal): {e}")


# Singleton instance
_research_handler: ResearchHandler = None


def get_research_handler(turns_dir: Path = None) -> ResearchHandler:
    """Get or create a ResearchHandler instance."""
    global _research_handler
    if _research_handler is None or turns_dir is not None:
        _research_handler = ResearchHandler(turns_dir=turns_dir)
    return _research_handler
