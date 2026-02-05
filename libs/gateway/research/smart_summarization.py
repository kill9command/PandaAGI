"""
Panda Smart Summarization System

Automatic context compression to ensure documents fit within per-call LLM context windows.

Usage:
    summarizer = SmartSummarizer(llm_client)

    # Check if compression needed
    plan = summarizer.check_budget(documents, recipe)

    # Invoke with automatic budget management
    response = await summarizer.invoke_with_budget(recipe, documents, variables)

Design Notes:
- This module provides real-time budget checking and compression for LLM calls.
- For context.md section-specific compression during Phase 8 (Save), see
  libs/compression which provides NERVES-based intelligent summarization.
- COMPRESSION_STRATEGIES below overlap with libs/compression/content_types.py.
  Consider consolidating if behavior diverges.
"""
import os
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List

from libs.gateway.llm.recipe_loader import load_recipe

logger = logging.getLogger(__name__)

# Try to import tiktoken for fast token counting
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning("tiktoken not available, using approximate token counting")


class ContentType(Enum):
    """Content type hints for compression strategy."""
    CONTEXT_DOC = "context.md"      # Main context document
    RESEARCH_DOC = "research.md"    # Research findings
    TOOL_RESULT = "tool_result"     # MCP tool output
    PRIOR_TURN = "prior_turn"       # Previous conversation turn
    CONVERSATION = "conversation"   # Chat history
    PAGE_DOC = "page_doc"           # Page intelligence document (Tier 5)
    GENERIC = "generic"             # Unknown type


# Compression strategies per content type
COMPRESSION_STRATEGIES = {
    ContentType.CONTEXT_DOC: {
        "preserve_sections": [0],  # Never compress §0 (user query)
        "priority_sections": [4, 1],  # §4 (tool results) and §1 (context) most important
        "preserve_patterns": [
            r"\$[\d,]+(?:\.\d{2})?",  # Prices
            r"https?://[^\s]+",        # URLs
            r"\[.*?\]\(https?://[^\)]+\)",  # Markdown links
        ],
    },
    ContentType.RESEARCH_DOC: {
        "preserve_sections": [],
        "priority_sections": ["Products", "Claims"],
        "preserve_patterns": [
            r"\$[\d,]+(?:\.\d{2})?",  # Prices
            r"https?://[^\s]+",        # URLs
        ],
    },
    ContentType.TOOL_RESULT: {
        "preserve_sections": [],
        "priority_sections": ["claims", "products"],
        "preserve_patterns": [
            r"\$[\d,]+(?:\.\d{2})?",  # Prices
            r"https?://[^\s]+",        # URLs
        ],
    },
    ContentType.PRIOR_TURN: {
        "preserve_sections": [],
        "priority_sections": ["Response"],
        "preserve_patterns": [],
    },
    ContentType.PAGE_DOC: {
        "preserve_sections": [],
        "priority_sections": ["OCR", "DOM"],
        "preserve_patterns": [
            r"\$[\d,]+(?:\.\d{2})?",  # Prices
        ],
    },
    ContentType.GENERIC: {
        "preserve_sections": [],
        "priority_sections": [],
        "preserve_patterns": [],
    },
}


@dataclass
class TokenBreakdown:
    """Token count breakdown by section."""
    total: int
    by_section: Dict[str, int] = field(default_factory=dict)


@dataclass
class CompressionPlan:
    """Plan for what needs compression."""
    needed: bool
    total_tokens: int = 0
    budget: int = 0
    overflow: int = 0
    compression_ratio: float = 1.0
    targets: List[Dict[str, Any]] = field(default_factory=list)


class TokenCounter:
    """
    Fast token counting for budget checks.
    Uses tiktoken when available, falls back to approximation.
    """

    def __init__(self, model: str = "cl100k_base"):
        self.encoder = None
        if TIKTOKEN_AVAILABLE:
            try:
                self.encoder = tiktoken.get_encoding(model)
            except Exception as e:
                logger.warning(f"Failed to load tiktoken encoding: {e}")

    def count(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Text to count tokens in

        Returns:
            Token count
        """
        if not text:
            return 0

        if self.encoder:
            return len(self.encoder.encode(text))

        # Fallback: approximate count (1 token ≈ 4 chars for English)
        return len(text) // 4

    def count_sections(self, text: str, section_pattern: str = "## ") -> TokenBreakdown:
        """
        Count tokens per section for targeted compression.

        Args:
            text: Document text with markdown sections
            section_pattern: Pattern that marks section headers

        Returns:
            TokenBreakdown with total and per-section counts
        """
        sections = {}
        current_section = "header"
        current_content = []

        for line in text.split('\n'):
            if line.startswith(section_pattern):
                # Save previous section
                if current_content:
                    sections[current_section] = self.count('\n'.join(current_content))
                # Start new section
                current_section = line.strip()
                current_content = [line]
            else:
                current_content.append(line)

        # Save last section
        if current_content:
            sections[current_section] = self.count('\n'.join(current_content))

        return TokenBreakdown(
            total=self.count(text),
            by_section=sections
        )


class BudgetChecker:
    """Determines compression needs based on recipe budgets."""

    def __init__(self, counter: TokenCounter = None):
        self.counter = counter or TokenCounter()

    def check(
        self,
        documents: Dict[str, str],
        budget: int,
        system_prompt_tokens: int = 0,
        response_reserve: int = 2000
    ) -> CompressionPlan:
        """
        Check if compression is needed.

        Args:
            documents: Dict of document name -> content
            budget: Total token budget for the call
            system_prompt_tokens: Tokens used by system prompt
            response_reserve: Tokens to reserve for response

        Returns:
            CompressionPlan indicating if and how to compress
        """
        available = budget - system_prompt_tokens - response_reserve

        # Count total tokens in all documents
        doc_tokens = {}
        total = 0
        for name, content in documents.items():
            tokens = self.counter.count(content)
            doc_tokens[name] = tokens
            total += tokens

        if total <= available:
            return CompressionPlan(
                needed=False,
                total_tokens=total,
                budget=available
            )

        # Compression needed - determine targets
        overflow = total - available
        compression_ratio = available / total if total > 0 else 1.0

        # Identify compression targets (largest documents first)
        sorted_docs = sorted(doc_tokens.items(), key=lambda x: x[1], reverse=True)
        targets = []
        for name, tokens in sorted_docs:
            # Calculate target size based on proportional reduction
            target_size = int(tokens * compression_ratio)
            targets.append({
                "name": name,
                "current_tokens": tokens,
                "target_tokens": target_size,
                "content_type": self._detect_content_type(name, documents.get(name, ""))
            })

        return CompressionPlan(
            needed=True,
            total_tokens=total,
            budget=available,
            overflow=overflow,
            compression_ratio=compression_ratio,
            targets=targets
        )

    def _detect_content_type(self, name: str, content: str) -> ContentType:
        """Detect content type from name and content patterns."""
        if name == "context.md" or "## 0. User Query" in content or "## §0" in content:
            return ContentType.CONTEXT_DOC
        if name == "research.md" or "## Research Findings" in content:
            return ContentType.RESEARCH_DOC
        if name.startswith("tool:") or "tool_result" in name:
            return ContentType.TOOL_RESULT
        if "turn_" in name or "Previous Turn" in content:
            return ContentType.PRIOR_TURN
        if name == "page.md" or "## OCR" in content or "## DOM" in content:
            return ContentType.PAGE_DOC
        return ContentType.GENERIC


class SummarizationEngine:
    """
    Content-aware compression engine.

    ARCHITECTURAL DECISION (2025-12-30):
    Implements intelligent compression that:
    - Preserves critical elements (prices, URLs, section 0)
    - Uses content-type specific strategies
    - Prioritizes sections by importance
    - Truncates low-priority content first
    """

    def __init__(self, counter: TokenCounter = None):
        self.counter = counter or TokenCounter()

    def compress(
        self,
        content: str,
        content_type: ContentType,
        target_tokens: int
    ) -> str:
        """
        Compress content to target token count.

        Args:
            content: Text to compress
            content_type: Type of content for strategy selection
            target_tokens: Target token count

        Returns:
            Compressed text
        """
        import re

        current_tokens = self.counter.count(content)
        if current_tokens <= target_tokens:
            return content  # Already within budget

        strategy = COMPRESSION_STRATEGIES.get(content_type, COMPRESSION_STRATEGIES[ContentType.GENERIC])

        # Extract preserved elements
        preserved = self._extract_preserved(content, strategy)

        # Parse sections
        sections = self._parse_sections(content, content_type)

        # Determine section priorities
        preserve_sections = strategy.get("preserve_sections", [])
        priority_sections = strategy.get("priority_sections", [])

        # Calculate token budget per section based on priority
        result_sections = []
        remaining_budget = target_tokens - len(preserved) * 10  # Reserve for preserved items

        for section in sections:
            section_num = section.get("num")
            section_name = section.get("name", "")
            section_content = section.get("content", "")

            # Check if this section should be preserved entirely
            if section_num in preserve_sections:
                result_sections.append(section)
                remaining_budget -= self.counter.count(section_content)
                continue

            # Check priority
            is_priority = section_num in priority_sections or section_name in priority_sections

            # Calculate section budget
            section_tokens = self.counter.count(section_content)

            if is_priority:
                # High priority: allocate proportionally more budget
                section_budget = min(section_tokens, remaining_budget // 2)
            else:
                # Low priority: can be truncated aggressively
                section_budget = min(section_tokens, remaining_budget // 4)

            if section_budget <= 0:
                # Skip this section entirely
                section["content"] = f"[{section_name}: content truncated for space]"
            elif section_tokens > section_budget:
                # Truncate section
                section["content"] = self._truncate_section(
                    section_content,
                    section_budget,
                    preserved
                )

            result_sections.append(section)
            remaining_budget -= self.counter.count(section["content"])

        # Reconstruct document
        return self._reconstruct(result_sections, content_type)

    def _extract_preserved(self, content: str, strategy: Dict[str, Any]) -> List[str]:
        """Extract elements that must be preserved."""
        import re
        preserved = []
        for pattern in strategy.get("preserve_patterns", []):
            matches = re.findall(pattern, content)
            preserved.extend(matches)
        return preserved

    def _parse_sections(self, content: str, content_type: ContentType) -> List[Dict[str, Any]]:
        """Parse document into sections."""
        sections = []

        if content_type == ContentType.CONTEXT_DOC:
            # Parse context.md sections (§0, §1, §2, etc.)
            import re
            section_pattern = r'^## (?:§(\d+)|(\d+)\.) (.+?)$'
            current_section = None
            current_content = []

            for line in content.split('\n'):
                match = re.match(section_pattern, line)
                if match:
                    # Save previous section
                    if current_section is not None:
                        sections.append({
                            "num": current_section["num"],
                            "name": current_section["name"],
                            "header": current_section["header"],
                            "content": '\n'.join(current_content)
                        })
                    # Start new section
                    section_num = int(match.group(1) or match.group(2))
                    section_name = match.group(3)
                    current_section = {
                        "num": section_num,
                        "name": section_name,
                        "header": line
                    }
                    current_content = [line]
                else:
                    current_content.append(line)

            # Save last section
            if current_section is not None:
                sections.append({
                    "num": current_section["num"],
                    "name": current_section["name"],
                    "header": current_section["header"],
                    "content": '\n'.join(current_content)
                })
        else:
            # Generic markdown section parsing
            current_name = "header"
            current_content = []

            for line in content.split('\n'):
                if line.startswith('## '):
                    # Save previous section
                    if current_content:
                        sections.append({
                            "num": len(sections),
                            "name": current_name,
                            "header": f"## {current_name}",
                            "content": '\n'.join(current_content)
                        })
                    current_name = line[3:].strip()
                    current_content = [line]
                else:
                    current_content.append(line)

            # Save last section
            if current_content:
                sections.append({
                    "num": len(sections),
                    "name": current_name,
                    "header": f"## {current_name}",
                    "content": '\n'.join(current_content)
                })

        return sections

    def _truncate_section(
        self,
        content: str,
        target_tokens: int,
        preserved: List[str]
    ) -> str:
        """
        Truncate section content to target size while preserving key elements.
        """
        lines = content.split('\n')

        # Find lines containing preserved elements
        preserved_lines = set()
        for i, line in enumerate(lines):
            for item in preserved:
                if item in line:
                    preserved_lines.add(i)

        # Build truncated content
        result_lines = []
        current_tokens = 0

        # Always include header (first line if it's a section header)
        if lines and lines[0].startswith('#'):
            result_lines.append(lines[0])
            current_tokens = self.counter.count(lines[0])

        # Add preserved lines first
        for i in preserved_lines:
            if i < len(lines):
                line = lines[i]
                line_tokens = self.counter.count(line)
                if current_tokens + line_tokens < target_tokens:
                    result_lines.append(line)
                    current_tokens += line_tokens

        # Fill remaining budget with other lines
        for i, line in enumerate(lines):
            if i in preserved_lines:
                continue
            if line.startswith('#'):
                continue

            line_tokens = self.counter.count(line)
            if current_tokens + line_tokens < target_tokens:
                result_lines.append(line)
                current_tokens += line_tokens
            else:
                break

        # Add truncation indicator if we cut content
        if len(result_lines) < len(lines):
            result_lines.append(f"\n[...{len(lines) - len(result_lines)} lines truncated...]")

        return '\n'.join(result_lines)

    def _reconstruct(self, sections: List[Dict[str, Any]], content_type: ContentType) -> str:
        """Reconstruct document from sections."""
        parts = []
        for section in sections:
            parts.append(section.get("content", ""))
        return '\n\n'.join(parts)

    async def compress_with_llm(
        self,
        content: str,
        content_type: ContentType,
        target_tokens: int,
        llm_client
    ) -> str:
        """
        Compress content using LLM for intelligent summarization.

        Implements #16 from IMPLEMENTATION_ROADMAP.md:
        - Uses LLM to summarize while preserving key facts (prices, URLs, claims)
        - Falls back to truncation if LLM fails

        Args:
            content: Text to compress
            content_type: Type of content for strategy selection
            target_tokens: Target token count
            llm_client: LLM client for summarization

        Returns:
            Compressed text
        """
        current_tokens = self.counter.count(content)
        if current_tokens <= target_tokens:
            return content  # Already within budget

        strategy = COMPRESSION_STRATEGIES.get(content_type, COMPRESSION_STRATEGIES[ContentType.GENERIC])
        preserved = self._extract_preserved(content, strategy)

        # Build LLM prompt for summarization
        preserved_items = "\n".join(f"- {p}" for p in preserved[:20]) if preserved else "None"
        compression_ratio = target_tokens / current_tokens
        compression_percent = int(compression_ratio * 100)

        # Load and format the prompt template
        try:
            recipe = load_recipe("memory/turn_compressor")
            prompt_template = recipe.get_prompt()
        except Exception as e:
            logger.warning(f"Failed to load turn_compressor recipe: {e}")
            prompt_template = ""
        if prompt_template:
            prompt = prompt_template.format(
                compression_percent=compression_percent,
                preserved_items=preserved_items,
                content_type=content_type.value,
                content=content
            )
        else:
            # Fallback: inline prompt if file not found
            prompt = f"""Summarize the following content to approximately {compression_percent}% of its current length.

CRITICAL REQUIREMENTS:
1. Preserve ALL of these exact values:
{preserved_items}

2. Preserve the document structure (section headers, bullet points)
3. Keep all prices, URLs, product names, and specific claims
4. Remove redundant explanations, filler words, and verbose phrasing
5. Prioritize factual content over commentary

CONTENT TYPE: {content_type.value}

---
CONTENT TO SUMMARIZE:
{content}
---

SUMMARIZED CONTENT:"""

        try:
            # NERVES role (temp=0.3) for factual summarization
            response = await llm_client.call(
                prompt=prompt,
                role="summarizer",
                max_tokens=target_tokens + 100,  # Small buffer
                temperature=0.3
            )

            # Verify compression achieved target
            result_tokens = self.counter.count(response)
            if result_tokens <= target_tokens * 1.1:  # 10% tolerance
                logger.info(f"[SmartSummarizer] LLM compression: {current_tokens} -> {result_tokens} tokens")
                return response
            else:
                # LLM didn't compress enough - apply truncation
                logger.warning(f"[SmartSummarizer] LLM compression insufficient ({result_tokens} > {target_tokens}), applying truncation")
                return self.compress(response, content_type, target_tokens)

        except Exception as e:
            logger.warning(f"[SmartSummarizer] LLM compression failed: {e}, falling back to truncation")
            return self.compress(content, content_type, target_tokens)


class SmartSummarizer:
    """
    Transparent summarization layer for LLM calls.

    Wraps LLM invocations with automatic budget management:
    1. Check if compression needed
    2. Compress if necessary
    3. Invoke LLM
    """

    def __init__(self, llm_client=None):
        """
        Initialize SmartSummarizer.

        Args:
            llm_client: LLM client for compression calls (optional for now)
        """
        self.llm = llm_client
        self.counter = TokenCounter()
        self.checker = BudgetChecker(self.counter)
        self.engine = SummarizationEngine(self.counter)

        # Configuration from environment
        self.enabled = os.environ.get("COMPRESSION_ENABLED", "true").lower() == "true"
        self.default_budget = int(os.environ.get("DEFAULT_CONTEXT_BUDGET", 12000))
        self.response_reserve = int(os.environ.get("RESPONSE_TOKEN_RESERVE", 2000))
        self.compression_threshold = float(os.environ.get("COMPRESSION_THRESHOLD", 0.9))
        # Use LLM for compression when available (more intelligent but uses tokens)
        self.use_llm_compression = os.environ.get("USE_LLM_COMPRESSION", "false").lower() == "true"

    def check_budget(
        self,
        documents: Dict[str, str],
        budget: int = None,
        system_prompt_tokens: int = 0
    ) -> CompressionPlan:
        """
        Check if documents fit within budget.

        Args:
            documents: Dict of document name -> content
            budget: Token budget (uses default if not specified)
            system_prompt_tokens: Tokens used by system prompt

        Returns:
            CompressionPlan with compression recommendations
        """
        budget = budget or self.default_budget
        return self.checker.check(
            documents=documents,
            budget=budget,
            system_prompt_tokens=system_prompt_tokens,
            response_reserve=self.response_reserve
        )

    async def invoke_with_budget(
        self,
        recipe: Any,
        documents: Dict[str, str],
        variables: Dict[str, Any] = None,
        llm_call_fn=None
    ) -> Any:
        """
        Invoke LLM with automatic budget management.

        This is the primary entry point for budget-aware LLM calls.

        Args:
            recipe: Recipe with token_budget defined
            documents: Dict of document name -> content
            variables: Additional variables for the recipe
            llm_call_fn: Function to call the LLM (async)

        Returns:
            LLM response
        """
        if not self.enabled:
            # Fast path: compression disabled
            if llm_call_fn:
                return await llm_call_fn(documents, variables)
            return None

        # Get budget from recipe
        budget = getattr(recipe, 'token_budget', None)
        if hasattr(budget, 'total'):
            budget = budget.total
        budget = budget or self.default_budget

        # Check if compression needed
        system_tokens = 0
        if hasattr(recipe, 'system_prompt'):
            system_tokens = self.counter.count(recipe.system_prompt)

        plan = self.check_budget(
            documents=documents,
            budget=budget,
            system_prompt_tokens=system_tokens
        )

        if not plan.needed:
            # Fast path: no compression needed
            logger.debug(
                f"[SmartSummarizer] Within budget: {plan.total_tokens}/{plan.budget} tokens"
            )
            if llm_call_fn:
                return await llm_call_fn(documents, variables)
            return None

        # Compression needed
        logger.info(
            f"[SmartSummarizer] Compression needed: {plan.total_tokens} tokens "
            f"exceeds budget {plan.budget} by {plan.overflow} tokens "
            f"(ratio: {plan.compression_ratio:.2f})"
        )

        # Compress documents using the SummarizationEngine
        compressed_documents = {}

        for target in plan.targets:
            doc_name = target['name']
            content = documents.get(doc_name, "")
            content_type = target['content_type']
            target_tokens = target['target_tokens']

            logger.info(
                f"[SmartSummarizer] Compressing {doc_name}: "
                f"{target['current_tokens']} -> {target_tokens} tokens"
                f" (mode: {'LLM' if self.use_llm_compression and self.llm else 'truncation'})"
            )

            # Apply compression - use LLM if available and enabled (#16)
            if self.use_llm_compression and self.llm:
                compressed = await self.engine.compress_with_llm(
                    content=content,
                    content_type=content_type,
                    target_tokens=target_tokens,
                    llm_client=self.llm
                )
            else:
                compressed = self.engine.compress(
                    content=content,
                    content_type=content_type,
                    target_tokens=target_tokens
                )
            compressed_documents[doc_name] = compressed

        # Include unmodified documents that didn't need compression
        for name, content in documents.items():
            if name not in compressed_documents:
                compressed_documents[name] = content

        # Verify compression achieved target
        final_tokens = sum(self.counter.count(c) for c in compressed_documents.values())
        logger.info(
            f"[SmartSummarizer] Compression complete: {plan.total_tokens} -> {final_tokens} tokens "
            f"(target: {plan.budget})"
        )

        # Proceed with compressed documents
        if llm_call_fn:
            return await llm_call_fn(compressed_documents, variables)
        return None

    def count_tokens(self, text: str) -> int:
        """Count tokens in text (convenience method)."""
        return self.counter.count(text)

    def get_section_breakdown(self, text: str) -> TokenBreakdown:
        """Get token breakdown by section (convenience method)."""
        return self.counter.count_sections(text)


# Module-level instance for convenience
_default_summarizer = None


def get_summarizer(llm_client=None) -> SmartSummarizer:
    """
    Get the default SmartSummarizer instance.

    Args:
        llm_client: Optional LLM client for compression

    Returns:
        SmartSummarizer instance
    """
    global _default_summarizer
    if _default_summarizer is None:
        _default_summarizer = SmartSummarizer(llm_client)
    return _default_summarizer


def count_tokens(text: str) -> int:
    """
    Count tokens in text (convenience function).

    Args:
        text: Text to count

    Returns:
        Token count
    """
    return get_summarizer().count_tokens(text)
