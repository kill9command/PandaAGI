"""Content type definitions and compression strategies.

Different content types require different compression approaches.
This module defines content types and their associated compression strategies.

Reference: architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class ContentType(Enum):
    """Types of content that may require compression.

    Each type has different compression requirements:
    - CONTEXT_MD: Section content from context.md files
    - RESEARCH_MD: Research document content
    - TOOL_RESULT: Output from tool executions
    - PAGE_DOC: Web page document content
    """

    CONTEXT_MD = "context_md"
    RESEARCH_MD = "research_md"
    TOOL_RESULT = "tool_result"
    PAGE_DOC = "page_doc"


@dataclass
class CompressionStrategy:
    """Compression strategy for a content type.

    Attributes:
        preserve_headers: Whether to preserve markdown headers
        preserve_tables: Whether to preserve table structure
        preserve_links: Whether to preserve source links/references
        preserve_numbers: Whether to preserve numerical data (prices, scores)
        preserve_code: Whether to preserve code blocks
        preserve_decisions: Whether to preserve decision outcomes
        min_compression_ratio: Minimum acceptable compression ratio
        max_attempts: Maximum compression retry attempts
    """

    preserve_headers: bool = True
    preserve_tables: bool = True
    preserve_links: bool = True
    preserve_numbers: bool = True
    preserve_code: bool = False
    preserve_decisions: bool = True
    min_compression_ratio: float = 0.3  # Must reduce to at least 30%
    max_attempts: int = 2


# Content type specific strategies
COMPRESSION_STRATEGIES: dict[ContentType, CompressionStrategy] = {
    ContentType.CONTEXT_MD: CompressionStrategy(
        preserve_headers=True,
        preserve_tables=True,
        preserve_links=True,
        preserve_numbers=True,
        preserve_code=False,  # Code in context can be summarized
        preserve_decisions=True,  # PROCEED/CLARIFY/APPROVE must be kept
        min_compression_ratio=0.4,
        max_attempts=2,
    ),
    ContentType.RESEARCH_MD: CompressionStrategy(
        preserve_headers=True,
        preserve_tables=True,  # Product listings, price tables
        preserve_links=True,  # Source URLs are critical
        preserve_numbers=True,  # Prices, scores, quantities
        preserve_code=False,
        preserve_decisions=False,
        min_compression_ratio=0.35,
        max_attempts=2,
    ),
    ContentType.TOOL_RESULT: CompressionStrategy(
        preserve_headers=True,
        preserve_tables=True,  # Tool output often tabular
        preserve_links=True,
        preserve_numbers=True,  # Results often have metrics
        preserve_code=True,  # Code output should be preserved
        preserve_decisions=False,
        min_compression_ratio=0.4,
        max_attempts=2,
    ),
    ContentType.PAGE_DOC: CompressionStrategy(
        preserve_headers=True,
        preserve_tables=True,
        preserve_links=True,  # Navigation links
        preserve_numbers=True,  # Page content numbers
        preserve_code=False,
        preserve_decisions=False,
        min_compression_ratio=0.3,  # Web pages often very verbose
        max_attempts=3,
    ),
}


def get_compression_strategy(content_type: ContentType) -> CompressionStrategy:
    """
    Get the compression strategy for a content type.

    Args:
        content_type: Type of content to compress

    Returns:
        CompressionStrategy for the content type
    """
    return COMPRESSION_STRATEGIES.get(content_type, CompressionStrategy())


def detect_content_type(content: str, filename: Optional[str] = None) -> ContentType:
    """
    Detect content type from content or filename.

    Args:
        content: Text content to analyze
        filename: Optional filename hint

    Returns:
        Detected ContentType
    """
    # Check filename first if provided
    if filename:
        if filename == "context.md" or filename.endswith("/context.md"):
            return ContentType.CONTEXT_MD
        if filename == "research.md" or filename.endswith("/research.md"):
            return ContentType.RESEARCH_MD
        if "toolresults" in filename.lower():
            return ContentType.TOOL_RESULT
        if filename.endswith("page_content.md"):
            return ContentType.PAGE_DOC

    # Analyze content structure
    content_lower = content.lower()

    # Check for context.md section markers
    if any(
        marker in content
        for marker in [
            "## 0. User Query",
            "## 1. Reflection Decision",
            "## 2. Gathered Context",
            "## 3. Task Plan",
            "## 4. Tool Execution",
            "## 5. Synthesis",
            "## 6. Validation",
        ]
    ):
        return ContentType.CONTEXT_MD

    # Check for research document markers
    if "## Evergreen Knowledge" in content or "## Time-Sensitive Data" in content:
        return ContentType.RESEARCH_MD

    # Check for tool result markers
    if "**Tool:**" in content or "**Result:**" in content:
        return ContentType.TOOL_RESULT

    # Check for page document markers
    if "## Page Text" in content or "**Captured:**" in content:
        return ContentType.PAGE_DOC

    # Default to context_md as most common
    return ContentType.CONTEXT_MD


def build_preservation_prompt(strategy: CompressionStrategy) -> str:
    """
    Build a prompt section describing what to preserve during compression.

    Args:
        strategy: CompressionStrategy to use

    Returns:
        Prompt text describing preservation requirements
    """
    preserve_items = []

    if strategy.preserve_headers:
        preserve_items.append("- Markdown headers and section structure")
    if strategy.preserve_tables:
        preserve_items.append("- Tables and their data (condense rows if needed)")
    if strategy.preserve_links:
        preserve_items.append("- Source references and links (URLs, citations)")
    if strategy.preserve_numbers:
        preserve_items.append("- All numerical data (prices, scores, counts, dates)")
    if strategy.preserve_code:
        preserve_items.append("- Code blocks (summarize explanations, keep code)")
    if strategy.preserve_decisions:
        preserve_items.append("- Decision outcomes (PROCEED, APPROVE, etc.)")

    remove_items = [
        "- Verbose explanations and filler text",
        "- Redundant information",
        "- Low-value details",
        "- Conversational fluff",
    ]

    prompt = "MUST PRESERVE:\n"
    prompt += "\n".join(preserve_items)
    prompt += "\n\nSHOULD REMOVE:\n"
    prompt += "\n".join(remove_items)

    return prompt
