"""
orchestrator/memory_mcp.py

Unified Memory MCP Tools

Provides unified access to all memory systems through MCP tool interface:
- memory.search: Search across all memory sources
- memory.save: Save new knowledge/facts
- memory.retrieve: Retrieve specific documents

Integrates:
- ResearchIndexDB (research documents)
- TurnIndexDB (turn context)
- MemoryStore (preferences, facts)
- SiteKnowledgeCache (navigation tips)

ARCHITECTURAL DECISION (2025-12-30):
Created as part of Tier 2 to provide unified memory access for the
Planner-Coordinator loop, replacing ad-hoc searches with structured tools.
"""

import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Base directories
MEMORY_BASE = Path(os.getenv("MEMORY_BASE_DIR", "panda_system_docs/memory"))
RESEARCH_BASE = Path(os.getenv("RESEARCH_BASE_DIR", "panda_system_docs"))
TURNS_BASE = Path(os.getenv("TURNS_BASE_DIR", "panda_system_docs/turns"))


@dataclass
class MemorySearchResult:
    """A unified search result from any memory source."""
    source: str  # 'research', 'turn', 'memory', 'site_knowledge'
    doc_id: str
    doc_path: str
    title: str
    snippet: str
    score: float
    content_type: str
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemorySearchRequest:
    """Request parameters for memory.search."""
    query: str
    topic_filter: Optional[str] = None
    content_types: Optional[List[str]] = None  # 'research', 'turn', 'preference', 'fact'
    scope: Optional[str] = None  # None = search all scopes; 'new', 'user', 'global' to filter
    session_id: Optional[str] = None
    min_quality: float = 0.3
    k: int = 10


@dataclass
class MemorySaveRequest:
    """Request parameters for memory.save."""
    title: str
    content: str
    doc_type: str  # 'preference', 'fact', 'note'
    tags: List[str] = field(default_factory=list)
    scope: str = "new"  # New data starts at 'new' scope per MEMORY_ARCHITECTURE.md
    session_id: Optional[str] = None


class UnifiedMemoryMCP:
    """
    Unified memory access for the Planner-Coordinator loop.

    Provides MCP-style tools for searching, saving, and retrieving
    from all memory systems.
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id
        self._research_index = None
        self._turn_index = None
        self._memory_store = None
        self._site_knowledge = None

    @property
    def research_index(self):
        """Lazy-load research index."""
        if self._research_index is None:
            try:
                from libs.gateway.research.research_index_db import get_research_index_db
                self._research_index = get_research_index_db()
            except ImportError:
                logger.warning("[MemoryMCP] ResearchIndexDB not available")
        return self._research_index

    @property
    def turn_index(self):
        """Lazy-load turn index."""
        if self._turn_index is None:
            try:
                from libs.gateway.persistence.turn_index_db import TurnIndexDB
                self._turn_index = TurnIndexDB()
            except ImportError:
                logger.warning("[MemoryMCP] TurnIndexDB not available")
        return self._turn_index

    @property
    def memory_store(self):
        """Lazy-load memory store."""
        if self._memory_store is None:
            try:
                from apps.services.tool_server.memory_store import get_memory_store
                self._memory_store = get_memory_store()
            except ImportError:
                logger.warning("[MemoryMCP] MemoryStore not available")
        return self._memory_store

    @property
    def site_knowledge(self):
        """Lazy-load site knowledge cache."""
        if self._site_knowledge is None:
            try:
                from apps.services.tool_server.site_knowledge_cache import SiteKnowledgeCache
                self._site_knowledge = SiteKnowledgeCache()
            except ImportError:
                logger.warning("[MemoryMCP] SiteKnowledgeCache not available")
        return self._site_knowledge

    async def search(self, request: MemorySearchRequest) -> List[MemorySearchResult]:
        """
        Search across all memory sources.

        Tool: memory.search

        Args:
            request: Search parameters

        Returns:
            List of unified search results, ranked by relevance
        """
        results = []
        content_types = request.content_types or ['research', 'turn', 'memory']

        logger.info(f"[MemoryMCP] Searching for: {request.query[:50]}... (types={content_types})")

        # 1. Search Research Index
        if 'research' in content_types and self.research_index:
            try:
                research_results = self._search_research(request)
                results.extend(research_results)
            except Exception as e:
                logger.warning(f"[MemoryMCP] Research search failed: {e}")

        # 2. Search Turn Index
        if 'turn' in content_types and self.turn_index:
            try:
                turn_results = self._search_turns(request)
                results.extend(turn_results)
            except Exception as e:
                logger.warning(f"[MemoryMCP] Turn search failed: {e}")

        # 3. Search Memory Store (preferences, facts)
        if any(t in content_types for t in ['memory', 'preference', 'fact']):
            if self.memory_store:
                try:
                    memory_results = self._search_memory(request)
                    results.extend(memory_results)
                except Exception as e:
                    logger.warning(f"[MemoryMCP] Memory search failed: {e}")

        # 4. Search Site Knowledge
        if 'site_knowledge' in content_types and self.site_knowledge:
            try:
                site_results = self._search_site_knowledge(request)
                results.extend(site_results)
            except Exception as e:
                logger.warning(f"[MemoryMCP] Site knowledge search failed: {e}")

        # Sort by score and limit
        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:request.k]

        logger.info(f"[MemoryMCP] Found {len(results)} results")
        return results

    def _search_research(self, request: MemorySearchRequest) -> List[MemorySearchResult]:
        """Search research index."""
        results = []

        # Use topic-based search if topic filter provided
        if request.topic_filter:
            search_results = self.research_index.search_by_topic(
                topic=request.topic_filter,
                session_id=request.session_id,
                min_quality=request.min_quality,
                limit=request.k
            )
        else:
            # Keyword search
            keywords = request.query.lower().split()[:5]
            search_results = self.research_index.search_by_keywords(
                keywords=keywords,
                session_id=request.session_id,
                min_quality=request.min_quality,
                limit=request.k
            )

        for sr in search_results:
            results.append(MemorySearchResult(
                source='research',
                doc_id=sr.entry.id,
                doc_path=sr.entry.doc_path,
                title=f"Research: {sr.entry.primary_topic}",
                snippet=f"Quality: {sr.entry.overall_quality:.2f}, Intent: {sr.entry.intent}",
                score=sr.score,
                content_type='research',
                created_at=datetime.fromtimestamp(sr.entry.created_at).isoformat(),
                metadata={
                    'topic': sr.entry.primary_topic,
                    'keywords': sr.entry.keywords,
                    'intent': sr.entry.intent,
                    'completeness': sr.entry.completeness
                }
            ))

        return results

    def _search_turns(self, request: MemorySearchRequest) -> List[MemorySearchResult]:
        """Search turn index."""
        results = []

        # Get recent turns
        turns = self.turn_index.get_recent_turns(
            session_id=request.session_id,
            limit=request.k * 2  # Get more to filter
        )

        # Simple keyword matching
        keywords = set(request.query.lower().split())

        for turn in turns:
            # Score based on keyword overlap with query/response
            turn_text = f"{turn.get('query', '')} {turn.get('response_summary', '')}".lower()
            turn_keywords = set(turn_text.split())
            overlap = len(keywords & turn_keywords)

            if overlap > 0:
                score = overlap / len(keywords) if keywords else 0
                if score >= request.min_quality:
                    results.append(MemorySearchResult(
                        source='turn',
                        doc_id=str(turn.get('turn_number', 0)),
                        doc_path=f"turns/turn_{turn.get('turn_number', 0)}/context.md",
                        title=f"Turn {turn.get('turn_number')}: {turn.get('query', '')[:50]}...",
                        snippet=turn.get('response_summary', '')[:200],
                        score=score,
                        content_type='turn',
                        created_at=turn.get('created_at', ''),
                        metadata={
                            'turn_number': turn.get('turn_number'),
                            'intent': turn.get('intent'),
                            'topic': turn.get('topic')
                        }
                    ))

        return results

    def _search_memory(self, request: MemorySearchRequest) -> List[MemorySearchResult]:
        """Search memory store (preferences, facts)."""
        results = []

        # Search both short and long term
        memories = self.memory_store.retrieve(
            query=request.query,
            topic=request.topic_filter,
            limit=request.k
        )

        for mem in memories:
            results.append(MemorySearchResult(
                source='memory',
                doc_id=mem.get('id', ''),
                doc_path=mem.get('path', ''),
                title=mem.get('title', 'Memory'),
                snippet=mem.get('content', '')[:200],
                score=mem.get('score', 0.5),
                content_type=mem.get('type', 'memory'),
                created_at=mem.get('created_at', ''),
                metadata={
                    'tags': mem.get('tags', []),
                    'scope': mem.get('scope', 'new')
                }
            ))

        return results

    def _search_site_knowledge(self, request: MemorySearchRequest) -> List[MemorySearchResult]:
        """Search site knowledge cache."""
        results = []

        # Get all domains and filter by query keywords
        domains = self.site_knowledge.list_domains()
        keywords = set(request.query.lower().split())

        for domain in domains:
            entry = self.site_knowledge.get_entry(domain)
            if entry:
                # Score based on domain/tips keyword overlap
                entry_text = f"{domain} {entry.navigation_tips}".lower()
                entry_keywords = set(entry_text.split())
                overlap = len(keywords & entry_keywords)

                if overlap > 0:
                    score = (overlap / len(keywords)) * entry.confidence if keywords else 0
                    results.append(MemorySearchResult(
                        source='site_knowledge',
                        doc_id=domain,
                        doc_path=f"site_knowledge/{domain}.json",
                        title=f"Site: {domain}",
                        snippet=entry.navigation_tips[:200],
                        score=score,
                        content_type='site_knowledge',
                        created_at=entry.created_at,
                        metadata={
                            'page_type': entry.page_type,
                            'confidence': entry.confidence,
                            'success_count': entry.success_count
                        }
                    ))

        return results

    async def save(self, request: MemorySaveRequest) -> Dict[str, Any]:
        """
        Save new knowledge/fact to memory.

        Tool: memory.save

        Args:
            request: Save parameters

        Returns:
            Result with doc_id and status
        """
        logger.info(f"[MemoryMCP] Saving {request.doc_type}: {request.title[:50]}...")

        if not self.memory_store:
            return {"status": "error", "message": "Memory store not available"}

        try:
            result = self.memory_store.store(
                content=request.content,
                title=request.title,
                doc_type=request.doc_type,
                tags=request.tags,
                scope=request.scope,
                session_id=request.session_id or self.session_id
            )

            return {
                "status": "saved",
                "doc_id": result.get('id', ''),
                "doc_path": result.get('path', ''),
                "scope": request.scope
            }

        except Exception as e:
            logger.error(f"[MemoryMCP] Save failed: {e}")
            return {"status": "error", "message": str(e)}

    async def retrieve(self, doc_path: str = None, doc_id: str = None) -> Dict[str, Any]:
        """
        Retrieve a specific document by path or ID.

        Tool: memory.retrieve

        Args:
            doc_path: Path to document (e.g., "turns/turn_42/context.md")
            doc_id: Document ID for memory store lookups

        Returns:
            Document content and metadata
        """
        if not doc_path and not doc_id:
            return {"status": "error", "message": "Provide doc_path or doc_id"}

        logger.info(f"[MemoryMCP] Retrieving: {doc_path or doc_id}")

        try:
            if doc_path:
                # Try to load from filesystem
                full_path = RESEARCH_BASE / doc_path
                if full_path.exists():
                    content = full_path.read_text()
                    return {
                        "status": "found",
                        "doc_path": doc_path,
                        "content": content,
                        "size": len(content)
                    }

                # Try turns base
                full_path = TURNS_BASE.parent / doc_path
                if full_path.exists():
                    content = full_path.read_text()
                    return {
                        "status": "found",
                        "doc_path": doc_path,
                        "content": content,
                        "size": len(content)
                    }

            if doc_id and self.memory_store:
                # Try memory store
                result = self.memory_store.get_by_id(doc_id)
                if result:
                    return {
                        "status": "found",
                        "doc_id": doc_id,
                        "content": result.get('content', ''),
                        "metadata": result
                    }

            return {"status": "not_found", "message": f"Document not found: {doc_path or doc_id}"}

        except Exception as e:
            logger.error(f"[MemoryMCP] Retrieve failed: {e}")
            return {"status": "error", "message": str(e)}


# Singleton instance
_memory_mcp_instance: Optional[UnifiedMemoryMCP] = None


def get_memory_mcp(session_id: Optional[str] = None) -> UnifiedMemoryMCP:
    """Get or create the unified memory MCP instance."""
    global _memory_mcp_instance
    if _memory_mcp_instance is None:
        _memory_mcp_instance = UnifiedMemoryMCP(session_id)
    elif session_id:
        _memory_mcp_instance.session_id = session_id
    return _memory_mcp_instance


# MCP Tool Definitions for tool_catalog.json
MEMORY_TOOL_DEFINITIONS = {
    "memory.search": {
        "description": "Search across all memory systems (research, turns, preferences, facts, site knowledge)",
        "parameters": {
            "query": {"type": "string", "required": True, "description": "Search query"},
            "topic_filter": {"type": "string", "required": False, "description": "Filter by topic hierarchy"},
            "content_types": {"type": "array", "required": False, "description": "Types to search: research, turn, memory, site_knowledge"},
            "scope": {"type": "string", "required": False, "description": "Scope filter: new, user, global (omit to search all)"},
            "session_id": {"type": "string", "required": False, "description": "Session ID for scoping"},
            "min_quality": {"type": "number", "required": False, "default": 0.3, "description": "Minimum quality threshold"},
            "k": {"type": "integer", "required": False, "default": 10, "description": "Max results to return"}
        }
    },
    "memory.save": {
        "description": "Save new knowledge, facts, or preferences to memory",
        "parameters": {
            "title": {"type": "string", "required": True, "description": "Title or label for the memory"},
            "content": {"type": "string", "required": True, "description": "Content to save"},
            "doc_type": {"type": "string", "required": True, "description": "Type: preference, fact, note"},
            "tags": {"type": "array", "required": False, "description": "Tags for categorization"},
            "scope": {"type": "string", "required": False, "default": "new", "description": "Scope: new, user, global"},
            "session_id": {"type": "string", "required": False, "description": "Session ID for scoping"}
        }
    },
    "memory.retrieve": {
        "description": "Retrieve a specific document by path or ID",
        "parameters": {
            "doc_path": {"type": "string", "required": False, "description": "Path to document"},
            "doc_id": {"type": "string", "required": False, "description": "Document ID"}
        }
    }
}
