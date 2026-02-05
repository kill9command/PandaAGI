"""Panda Document IO System.

This module implements the document-centric IO model:
- context.md management (sections §0-§6, 8-phase pipeline)
- Turn lifecycle management
- Research document handling
- Link formatting (dual Markdown + Wikilink)
- Webpage cache management

Key Principle: Everything is a document. All state flows through context.md.

Architecture Reference:
    architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md

Usage:
    from libs.document_io import (
        TurnManager,
        ContextManager,
        ResearchManager,
        LinkFormatter,
        WebpageCacheManager,
        link_formatter,  # Default instance
    )

    # Create a new turn
    turn_manager = TurnManager(session_id="user123")
    turn_number, context = turn_manager.create_turn("What's the cheapest laptop?")

    # Write sections
    context.write_section_0(query_analysis)
    context.write_section_1(analysis_result)

    # Create research document
    research = ResearchManager(context.turn_dir)
    research.create(query, session_id, turn_number, topic, intent)

    # Generate links
    formatter = LinkFormatter()
    link = formatter.dual_link(from_file, to_file, "label")
"""

from libs.document_io.context_manager import ContextManager
from libs.document_io.turn_manager import TurnManager
from libs.document_io.research_manager import ResearchManager
from libs.document_io.link_formatter import LinkFormatter, link_formatter
from libs.document_io.webpage_cache import WebpageCacheManager

__all__ = [
    # Managers
    "ContextManager",
    "TurnManager",
    "ResearchManager",
    "LinkFormatter",
    "WebpageCacheManager",
    # Default instances
    "link_formatter",
]
