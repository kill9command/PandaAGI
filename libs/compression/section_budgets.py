"""Section word budgets for context.md compression.

Defines the maximum word counts for each section of context.md.
When a section exceeds its budget, NERVES auto-compression is triggered.

Reference: architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md Section 3

Architecture context.md sections (8-phase pipeline):
  §0: Original Query (Phase 1 input)
  §1: Query Analysis (Phase 1 output)
  §2: Gathered Context (Phase 2 output)
  §3: Plan/Goals (Phase 3 output)
  §4: Tool Results (Phase 4/5 output - accumulates)
  §5: Response (Phase 6 output)
  §6: Validation (Phase 7 output)
  Note: Phase 8 (Save) is procedural, doesn't add to context.md
"""

from typing import Optional
import re


# Section budgets for context.md
# | Section | Max Words | Content |
# | §0 | 500 | Original query (rarely exceeds) |
# | §1 | 300 | Query analysis |
# | §2 | 2000 | Gathered context |
# | §3 | 1000 | Plan/goals |
# | §4 | 3000 | Tool results (accumulates) |
# | §5 | 2000 | Response |
# | §6 | 500 | Validation decision |

SECTION_BUDGETS: dict[int, int] = {
    0: 500,   # Original query - rarely exceeds
    1: 300,   # Query analysis
    2: 2000,  # Gathered context
    3: 1000,  # Plan/goals
    4: 3000,  # Tool results - most likely to trigger compression
    5: 2000,  # Response
    6: 500,   # Validation decision
}

# Compression is expensive (3 LLM calls). Only trigger when content
# exceeds budget by this margin.
COMPRESSION_THRESHOLD_MARGIN = 0.20  # 20%

# Minimum compression target (percentage of budget to aim for)
COMPRESSION_TARGET_RATIO = 0.85  # Aim for 85% of budget


def get_word_count(text: str) -> int:
    """
    Count words in text.

    Uses simple whitespace splitting after cleaning.

    Args:
        text: Input text to count words in

    Returns:
        Number of words in text
    """
    if not text:
        return 0

    # Remove markdown code blocks to avoid counting code tokens as words
    # But preserve their presence for accurate structure counting
    cleaned = re.sub(r'```[\s\S]*?```', ' CODE_BLOCK ', text)

    # Remove markdown inline code
    cleaned = re.sub(r'`[^`]+`', ' CODE ', cleaned)

    # Remove URLs (they count as one "word")
    cleaned = re.sub(r'https?://\S+', ' URL ', cleaned)

    # Split on whitespace and count non-empty tokens
    words = cleaned.split()
    return len(words)


def get_section_budget(section_num: int) -> int:
    """
    Get the word budget for a section.

    Args:
        section_num: Section number (0-6)

    Returns:
        Maximum word count for the section

    Raises:
        ValueError: If section_num is not 0-6
    """
    if section_num not in SECTION_BUDGETS:
        raise ValueError(f"Invalid section number: {section_num}. Must be 0-6.")
    return SECTION_BUDGETS[section_num]


def is_over_budget(section_num: int, text: str) -> bool:
    """
    Check if text exceeds the budget for a section.

    Args:
        section_num: Section number (0-6)
        text: Content to check

    Returns:
        True if word count exceeds section budget
    """
    budget = get_section_budget(section_num)
    word_count = get_word_count(text)
    return word_count > budget


def should_compress(section_num: int, text: str) -> bool:
    """
    Determine if compression should be triggered.

    Compression is expensive (3 LLM calls), so only trigger when content
    exceeds budget by a significant margin (>20%).

    Args:
        section_num: Section number (0-6)
        text: Content to check

    Returns:
        True if compression should be triggered
    """
    budget = get_section_budget(section_num)
    word_count = get_word_count(text)
    threshold = budget * (1 + COMPRESSION_THRESHOLD_MARGIN)
    return word_count > threshold


def get_compression_target(section_num: int) -> int:
    """
    Get the target word count after compression.

    Aims for 85% of budget to leave some room for future appends
    (especially important for §4 which accumulates).

    Args:
        section_num: Section number (0-6)

    Returns:
        Target word count after compression
    """
    budget = get_section_budget(section_num)
    return int(budget * COMPRESSION_TARGET_RATIO)


def get_budget_status(section_num: int, text: str) -> dict:
    """
    Get detailed budget status for a section.

    Args:
        section_num: Section number (0-6)
        text: Content to analyze

    Returns:
        Dict with budget analysis:
        - word_count: Current word count
        - budget: Section budget
        - utilization: Percentage of budget used
        - over_budget: Whether over budget
        - should_compress: Whether compression recommended
        - compression_target: Target words if compression needed
    """
    word_count = get_word_count(text)
    budget = get_section_budget(section_num)
    utilization = (word_count / budget) * 100 if budget > 0 else 0

    return {
        "section_num": section_num,
        "word_count": word_count,
        "budget": budget,
        "utilization": round(utilization, 1),
        "over_budget": word_count > budget,
        "should_compress": should_compress(section_num, text),
        "compression_target": get_compression_target(section_num),
    }
