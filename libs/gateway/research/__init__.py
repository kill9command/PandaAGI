"""
Pandora Research Module - Research document management and summarization.

Implements research artifact generation and indexing for Phase 8 (Save)
and context retrieval for Phase 2.

Contains:
- ResearchDocument: Research document model with topic classification
- ResearchDocumentWriter: Writing research.md and research.json files
- ResearchHandler: Handles research doc writing and knowledge graph updates
- SmartSummarizer: Intelligent summarization for context budget management
- research_index_db: SQLite research index for topic-based retrieval

Architecture Reference:
    architecture/concepts/main-system-patterns/phase8-save.md
"""

from libs.gateway.research.research_document import ResearchDocumentWriter, ResearchDocument
from libs.gateway.research.research_index_db import get_research_index_db
from libs.gateway.research.smart_summarization import SmartSummarizer, get_summarizer
from libs.gateway.research.research_handler import ResearchHandler, get_research_handler

__all__ = [
    "ResearchDocumentWriter",
    "ResearchDocument",
    "get_research_index_db",
    "SmartSummarizer",
    "get_summarizer",
    "ResearchHandler",
    "get_research_handler",
]
