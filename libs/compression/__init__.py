"""Pandora Smart Summarization / Compression library.

This module provides auto-compression for context.md sections using the NERVES role
(MIND model @ temp=0.3). Compression is triggered when sections exceed their word budgets.

Key Components:
- SmartSummarizer: Main compression class with 3-stage verification
- CompressionVerifier: Verifies critical information is preserved
- ContentType: Enum for different content types with compression strategies
- Section budgets: Word limits per context.md section (§0-§6)

Architecture context.md sections (8-phase pipeline):
  §0: Original Query (Phase 1 input)
  §1: Query Analysis (Phase 1 output)
  §2: Gathered Context (Phase 2 output)
  §3: Plan/Goals (Phase 3 output)
  §4: Tool Results (Phase 4/5 output - accumulates, most likely to compress)
  §5: Response (Phase 6 output)
  §6: Validation (Phase 7 output)

Usage:
    from libs.compression import SmartSummarizer, get_budget_status

    # Check if compression needed
    status = get_budget_status(4, section_content)
    if status["should_compress"]:
        summarizer = SmartSummarizer()
        result = await summarizer.compress_section(4, section_content)
        if result.success:
            use(result.compressed_content)

    # Or use auto-check
    result = await summarizer.compress_if_needed(4, section_content)

Reference:
- architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md Section 3
- architecture/LLM-ROLES/llm-roles-reference.md (NERVES Background Services)
"""

# Section budget utilities
from libs.compression.section_budgets import (
    SECTION_BUDGETS,
    COMPRESSION_THRESHOLD_MARGIN,
    COMPRESSION_TARGET_RATIO,
    get_word_count,
    get_section_budget,
    is_over_budget,
    should_compress,
    get_compression_target,
    get_budget_status,
)

# Content types and strategies
from libs.compression.content_types import (
    ContentType,
    CompressionStrategy,
    COMPRESSION_STRATEGIES,
    get_compression_strategy,
    detect_content_type,
    build_preservation_prompt,
)

# Smart summarizer
from libs.compression.smart_summarizer import (
    SmartSummarizer,
    CompressionResult,
    get_summarizer,
)

# Compression verifier
from libs.compression.compression_verifier import (
    CompressionVerifier,
    VerificationResult,
    get_verifier,
)

__all__ = [
    # Section budgets
    "SECTION_BUDGETS",
    "COMPRESSION_THRESHOLD_MARGIN",
    "COMPRESSION_TARGET_RATIO",
    "get_word_count",
    "get_section_budget",
    "is_over_budget",
    "should_compress",
    "get_compression_target",
    "get_budget_status",
    # Content types
    "ContentType",
    "CompressionStrategy",
    "COMPRESSION_STRATEGIES",
    "get_compression_strategy",
    "detect_content_type",
    "build_preservation_prompt",
    # Smart summarizer
    "SmartSummarizer",
    "CompressionResult",
    "get_summarizer",
    # Compression verifier
    "CompressionVerifier",
    "VerificationResult",
    "get_verifier",
]
