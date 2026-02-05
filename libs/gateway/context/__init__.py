"""
Pandora Context Module - Context building and document management.

Implements Phase 1 (Query Analysis) and Phase 2 (Context Gathering) of the
8-phase pipeline.

Contains:
- ContextDocument: Main document model with sections (§0-§7)
- ContextGatherer2Phase: Two-phase context gathering (Phase 2.1/2.2)
- DocPackBuilder: Recipe-based document packing
- QueryAnalyzer: Query classification and analysis (Phase 1)
- SectionFormatter: Context document section formatting

Architecture Reference:
    architecture/concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md
"""

from libs.gateway.context.context_document import ContextDocument, TurnMetadata, extract_keywords
from libs.gateway.context.context_gatherer_2phase import ContextGatherer2Phase
from libs.gateway.context.doc_pack_builder import DocPackBuilder
from libs.gateway.context.query_analyzer import QueryAnalyzer, QueryAnalysis, ContentReference
from libs.gateway.context.section_formatter import SectionFormatter, get_section_formatter

__all__ = [
    "ContextDocument",
    "TurnMetadata",
    "extract_keywords",
    "ContextGatherer2Phase",
    "DocPackBuilder",
    "QueryAnalyzer",
    "QueryAnalysis",
    "ContentReference",
    "SectionFormatter",
    "get_section_formatter",
]
