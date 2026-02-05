"""
Memory Context Builder

Builds LLM-ready context from memory search results using intelligent
summarization to maximize information within token budget.

Key features:
- Loads full document content for high-relevance matches
- Uses SmartSummarizer to compress while preserving key facts
- Includes source URLs and Obsidian links
- Dynamic budget based on query type

Usage:
    builder = MemoryContextBuilder()
    context = await builder.build(
        memory_results=results,
        query_type="informational_memory",
        has_tool_results=False
    )
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from libs.gateway.llm.token_budget_allocator import get_allocator, TokenBudgetAllocator
from libs.gateway.research.smart_summarization import (
    SmartSummarizer,
    get_summarizer,
    TokenCounter,
    ContentType,
)

logger = logging.getLogger(__name__)

# Base path for memory documents
VAULT_PATH = Path("panda_system_docs")


@dataclass
class MemoryDocument:
    """A memory document with full content and metadata."""

    path: str
    topic: Optional[str]
    relevance: float
    confidence: float
    artifact_type: str
    tags: List[str]
    source_urls: List[str]
    content: str  # Full document content
    summary: str  # Short summary for fallback
    expired: bool = False


class MemoryContextBuilder:
    """
    Builds LLM-ready context from memory search results.

    Uses intelligent summarization to maximize information
    within token budget while preserving key facts and sources.
    """

    # Relevance threshold for loading full document content
    HIGH_RELEVANCE_THRESHOLD = 0.5

    # Minimum tokens per document (ensures meaningful content)
    MIN_TOKENS_PER_DOC = 200

    def __init__(
        self,
        summarizer: SmartSummarizer = None,
        allocator: TokenBudgetAllocator = None
    ):
        """
        Initialize MemoryContextBuilder.

        Args:
            summarizer: SmartSummarizer instance (uses default if not provided)
            allocator: TokenBudgetAllocator instance (uses default if not provided)
        """
        self.summarizer = summarizer or get_summarizer()
        self.allocator = allocator or get_allocator()
        self.counter = TokenCounter()

    async def build(
        self,
        memory_results: List[Any],
        query_type: str = "follow_up",
        has_tool_results: bool = True,
        load_full_content: bool = True
    ) -> str:
        """
        Build context from memory results within token budget.

        For high-relevance results, loads full document content.
        Uses SmartSummarizer to intelligently compress while preserving
        key facts, prices, URLs, and source links.

        Args:
            memory_results: List of MemoryResult from search
            query_type: Query type for budget allocation
            has_tool_results: Whether tool results will be included
            load_full_content: Whether to load full docs for high relevance

        Returns:
            Formatted context string ready for LLM consumption
        """
        if not memory_results:
            return ""

        # Get token budget for memory
        token_budget = self.allocator.get_memory_budget(
            query_type=query_type,
            has_tool_results=has_tool_results,
            memory_result_count=len(memory_results)
        )

        logger.info(
            f"[MemoryContextBuilder] Building context for {len(memory_results)} results "
            f"(budget: {token_budget} tokens, query_type: {query_type})"
        )

        # Load documents with full content for high-relevance matches
        documents = await self._load_documents(
            memory_results,
            load_full_content=load_full_content
        )

        if not documents:
            return ""

        # Calculate current token usage
        total_tokens = sum(
            self.counter.count(doc.content)
            for doc in documents
        )

        logger.info(
            f"[MemoryContextBuilder] Loaded {len(documents)} documents "
            f"({total_tokens} tokens, budget: {token_budget})"
        )

        # Compress if over budget
        if total_tokens > token_budget:
            documents = await self._compress_documents(documents, token_budget)

        # Format with sources included
        return self._format_context(documents)

    async def _load_documents(
        self,
        memory_results: List[Any],
        load_full_content: bool = True
    ) -> List[MemoryDocument]:
        """
        Load memory documents, with full content for high-relevance matches.

        Args:
            memory_results: List of MemoryResult from search
            load_full_content: Whether to load full docs for high relevance

        Returns:
            List of MemoryDocument with content loaded
        """
        documents = []

        for result in memory_results:
            # Determine if we should load full content
            should_load_full = (
                load_full_content and
                result.relevance >= self.HIGH_RELEVANCE_THRESHOLD
            )

            content = result.summary  # Default to summary

            if should_load_full:
                # Load full document content
                full_path = VAULT_PATH / result.path
                if full_path.exists():
                    try:
                        raw_content = full_path.read_text(encoding="utf-8")
                        # Strip frontmatter for cleaner content
                        content = self._strip_frontmatter(raw_content)
                        logger.debug(
                            f"[MemoryContextBuilder] Loaded full content for "
                            f"{result.path} ({len(content)} chars)"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[MemoryContextBuilder] Failed to load {result.path}: {e}"
                        )
                        content = result.summary

            # Build document
            doc = MemoryDocument(
                path=result.path,
                topic=result.topic,
                relevance=result.relevance,
                confidence=result.confidence,
                artifact_type=result.artifact_type,
                tags=result.tags or [],
                source_urls=result.source_urls or [],
                content=content,
                summary=result.summary,
                expired=getattr(result, 'expired', False),
            )
            documents.append(doc)

        return documents

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return content

        # Find end of frontmatter
        lines = content.split("\n")
        in_frontmatter = True
        body_start = 0

        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                body_start = i + 1
                break

        if body_start > 0:
            return "\n".join(lines[body_start:]).strip()

        return content

    async def _compress_documents(
        self,
        documents: List[MemoryDocument],
        token_budget: int
    ) -> List[MemoryDocument]:
        """
        Compress documents to fit within token budget.

        Uses SmartSummarizer for intelligent compression that preserves
        key facts, prices, URLs, and sources.

        Args:
            documents: List of MemoryDocument to compress
            token_budget: Target token budget

        Returns:
            List of MemoryDocument with compressed content
        """
        # Sort by relevance (most relevant first)
        sorted_docs = sorted(documents, key=lambda d: d.relevance, reverse=True)

        # Calculate per-document budget based on relevance weighting
        total_relevance = sum(d.relevance for d in sorted_docs)
        if total_relevance == 0:
            total_relevance = len(sorted_docs)

        compressed_docs = []
        remaining_budget = token_budget

        for doc in sorted_docs:
            # Allocate budget proportionally to relevance
            doc_share = doc.relevance / total_relevance
            doc_budget = max(
                self.MIN_TOKENS_PER_DOC,
                int(token_budget * doc_share)
            )

            # Don't exceed remaining budget
            doc_budget = min(doc_budget, remaining_budget)

            if doc_budget < self.MIN_TOKENS_PER_DOC:
                # Not enough budget for meaningful content, skip
                logger.debug(
                    f"[MemoryContextBuilder] Skipping {doc.path} "
                    f"(budget exhausted: {remaining_budget} remaining)"
                )
                continue

            current_tokens = self.counter.count(doc.content)

            if current_tokens <= doc_budget:
                # Already within budget
                compressed_docs.append(doc)
                remaining_budget -= current_tokens
            else:
                # Need to compress
                compressed_content = self.summarizer.engine.compress(
                    content=doc.content,
                    content_type=ContentType.RESEARCH_DOC,
                    target_tokens=doc_budget
                )

                # Create new document with compressed content
                compressed_doc = MemoryDocument(
                    path=doc.path,
                    topic=doc.topic,
                    relevance=doc.relevance,
                    confidence=doc.confidence,
                    artifact_type=doc.artifact_type,
                    tags=doc.tags,
                    source_urls=doc.source_urls,
                    content=compressed_content,
                    summary=doc.summary,
                    expired=doc.expired,
                )
                compressed_docs.append(compressed_doc)

                actual_tokens = self.counter.count(compressed_content)
                remaining_budget -= actual_tokens

                logger.debug(
                    f"[MemoryContextBuilder] Compressed {doc.path}: "
                    f"{current_tokens} -> {actual_tokens} tokens"
                )

        logger.info(
            f"[MemoryContextBuilder] Compressed {len(documents)} -> {len(compressed_docs)} docs "
            f"(budget used: {token_budget - remaining_budget}/{token_budget})"
        )

        return compressed_docs

    def _format_context(self, documents: List[MemoryDocument]) -> str:
        """
        Format documents as context for LLM consumption.

        Includes source URLs and related links for attribution.

        Args:
            documents: List of MemoryDocument to format

        Returns:
            Formatted markdown string
        """
        if not documents:
            return ""

        lines = [
            "### Forever Memory (Persistent Knowledge)",
            "",
        ]

        for doc in documents:
            # Header with topic and metadata
            title = doc.topic or doc.path
            expired_note = " *(may be outdated)*" if doc.expired else ""
            lines.append(f"#### {title}{expired_note}")

            # Metadata line
            meta_parts = [
                f"Relevance: {doc.relevance:.2f}",
                f"Confidence: {doc.confidence:.2f}",
                f"Type: {doc.artifact_type}",
            ]
            lines.append(f"*{' | '.join(meta_parts)}*")

            # Tags (if any)
            if doc.tags:
                lines.append(f"Tags: {', '.join(doc.tags[:5])}")

            lines.append("")

            # Content
            lines.append(doc.content)

            # Sources (if any)
            if doc.source_urls:
                lines.append("")
                sources = doc.source_urls[:5]  # Limit to 5 sources
                if len(sources) == 1:
                    lines.append(f"**Source:** {sources[0]}")
                else:
                    lines.append("**Sources:**")
                    for source in sources:
                        lines.append(f"- {source}")

            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)


# Module-level instance
_builder: Optional[MemoryContextBuilder] = None


def get_memory_context_builder() -> MemoryContextBuilder:
    """Get the global MemoryContextBuilder instance."""
    global _builder
    if _builder is None:
        _builder = MemoryContextBuilder()
    return _builder


async def build_memory_context(
    memory_results: List[Any],
    query_type: str = "follow_up",
    has_tool_results: bool = True
) -> str:
    """
    Convenience function to build memory context.

    Args:
        memory_results: List of MemoryResult from search
        query_type: Query type for budget allocation
        has_tool_results: Whether tool results will be included

    Returns:
        Formatted context string
    """
    builder = get_memory_context_builder()
    return await builder.build(
        memory_results=memory_results,
        query_type=query_type,
        has_tool_results=has_tool_results
    )
