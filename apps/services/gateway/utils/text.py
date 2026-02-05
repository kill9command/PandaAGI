"""
Text Processing Utilities

Provides subject extraction, keyword matching, and text analysis functions
for the Gateway service.

Architecture Reference:
    architecture/README.md (Context Discipline + Workflow System)

Design Notes:
- WARNING: This module contains hardcoded heuristics and domain-specific patterns
  (species lists, subject patterns, skip keywords) that conflict with the
  "no hardcoding for relevance decisions" architecture principle.
- Per architecture, LLM-driven interpretation should be preferred over regex matching.
- These utilities should be used ONLY for:
  - UI display formatting (not routing decisions)
  - Legacy compatibility (migrating away from heuristics)
  - Fallback extraction when LLM methods are unavailable
- Do NOT use these patterns to gate pipeline routing or tool selection.
- Relevance decisions should be made by passing the original query to an LLM.
- This module is a candidate for deprecation as LLM-based methods mature.
"""

import re
from typing import Any, List, Tuple

# =============================================================================
# Regex Patterns
# =============================================================================

ACK_PHRASES = re.compile(r"\b(thanks?|thank you|cool|great|awesome|okay|ok)\b", re.IGNORECASE)

SUBJECT_KEYWORDS = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9\s\-]{0,80}(?:hamster|kit|parts?|motor|battery|frame|drone|board|sensor|list|bundle|set|supply|component)s?)",
    re.IGNORECASE,
)

REPEAT_HINT_RE = re.compile(
    r"\b(again|previous|repeat|same ones|earlier results|those again|the same links)\b",
    re.IGNORECASE
)

# =============================================================================
# Species Detection Patterns
# =============================================================================

SPECIES_HINTS = (
    "syrian",
    "teddy",
    "golden",
    "roborovski",
    "winter white",
    "campbell",
    "dwarf",
    "chinese",
    "siberian",
)

# Map common species aliases to their canonical names
SPECIES_ALIASES = {
    "golden": "syrian",
    "teddy": "syrian",
    "fancy": "syrian",
    "winter white": "djungarian",
    "djungarian": "winter white",
    "russian": "dwarf",  # Common shorthand for Russian dwarf
}

# =============================================================================
# Preference and Activity Patterns
# =============================================================================

PREFERENCE_PATTERNS = (
    re.compile(r"\bmy favorite (?:hamster|pet|animal) is (?:a )?(?P<value>[A-Za-z0-9\-\s]+)", re.IGNORECASE),
    re.compile(r"\bmy (?:favorite|fav) is (?:a |the )?(?P<value>[A-Za-z0-9\-\s]+)", re.IGNORECASE),
    re.compile(r"\bi (?:love|prefer) (?:the )?(?P<value>[A-Za-z0-9\-\s]+?) hamster", re.IGNORECASE),
)

ACTIVITY_PATTERNS = (
    re.compile(r"\bsearch(?:ing)? for (?P<target>[A-Za-z0-9\-\s]+) (?:hamsters?|listings?)", re.IGNORECASE),
    re.compile(r"\blook(?:ing)? for (?P<target>[A-Za-z0-9\-\s]+) hamsters", re.IGNORECASE),
)

# =============================================================================
# Filter Keywords
# =============================================================================

OFFER_SKIP_KEYWORDS = (
    "book",
    "guide",
    "manual",
    "poster",
    "print",
    "plush",
    "toy",
    "video",
    "dvd",
    "shirt",
    "set",
    "figurine",
    "calendar",
    "sticker",
    "vitalsource",
    "barnes",
    "ebook",
    "walmart",
)

LEADING_STOPWORDS = (
    "is",
    "are",
    "was",
    "were",
    "the",
    "a",
    "an",
    "my",
    "your",
    "our",
    "favorite",
)

# Stop words to filter out from keyword matching (prevents false cache hits)
KEYWORD_STOP_WORDS = {
    "find", "search", "looking", "get", "show", "online", "for", "sale",
    "buy", "purchase", "some", "any", "the", "and", "with", "can", "you",
    "please", "help", "need", "want", "where", "what", "how", "why", "when"
}

# =============================================================================
# Utility Functions
# =============================================================================


def contains_keyword_phrase(text: str, keywords: Tuple[str, ...]) -> bool:
    """Check if text contains any of the keyword phrases."""
    if not text:
        return False
    lowered = text.lower()
    return any(kw in lowered for kw in keywords)


def normalize_species(kw: str) -> str:
    """Normalize species keyword to its canonical form for matching."""
    return SPECIES_ALIASES.get(kw, kw)


def clean_subject(value: str) -> str:
    """Clean subject string by removing leading stopwords."""
    result = (value or "").strip()
    while True:
        lower = result.lower()
        matched = False
        for stop in LEADING_STOPWORDS:
            prefix = stop + " "
            if lower.startswith(prefix):
                result = result[len(prefix):].lstrip()
                matched = True
                break
        if not matched:
            break
    return result.strip()


def extract_subject_keywords(text: str) -> str:
    """
    Extract subject keywords from text.

    Attempts to find relevant subject matter (e.g., "syrian hamsters",
    "drone parts") from the input text.
    """
    def _refine(candidate: str) -> str | None:
        cand = (candidate or "").strip()
        if not cand:
            return None
        lower = cand.lower()
        if "hamster" in lower:
            ham_candidates = re.findall(
                r"([A-Za-z0-9\-]{1,40}(?:\s[A-Za-z0-9\-]{1,40}){0,3}\s+hamsters?)",
                cand,
                re.IGNORECASE,
            )
            if ham_candidates:
                for ham in reversed(ham_candidates):
                    if any(hint in ham.lower() for hint in SPECIES_HINTS):
                        return clean_subject(ham)
                return clean_subject(ham_candidates[-1])
        if any(hint in lower for hint in SPECIES_HINTS):
            return clean_subject(cand)
        return clean_subject(cand) or None

    matches = SUBJECT_KEYWORDS.findall(text)
    if not matches:
        return ""

    for candidate in reversed(matches):
        refined = _refine(candidate)
        if refined:
            return refined

    refined_tail = _refine(matches[-1])
    result = refined_tail or matches[-1].strip()
    return clean_subject(result)


def last_user_subject(messages: List[dict[str, Any]]) -> str:
    """
    Extract the subject from the last substantive user message.

    Skips acknowledgment phrases and very short messages.
    """
    if not messages:
        return ""
    # Skip the latest user message (current turn)
    for msg in reversed(messages[:-1]):
        if msg.get("role") != "user":
            continue
        text = (msg.get("content") or "").strip()
        if not text:
            continue
        if len(text) < 4:
            continue
        if ACK_PHRASES.search(text) and len(text) < 60:
            continue
        subject = extract_subject_keywords(text)
        if subject:
            return subject
        if len(text.split()) >= 2:
            return text
    return ""


def extract_urls(text: str) -> List[str]:
    """Extract all URLs from text."""
    if not text:
        return []
    try:
        return re.findall(r"https?://[^\s]+", text)
    except Exception:
        return []


def is_long_running_query(query: str) -> bool:
    """
    Detect if query will likely take >5 minutes (research, shopping, retry, etc.).
    These queries should use SSE for delivery.
    """
    keywords = [
        "retry", "find", "search", "buy", "purchase", "research",
        "for sale", "shop", "compare", "price", "vendor", "product"
    ]
    query_lower = query.lower()
    return any(kw in query_lower for kw in keywords)


def estimate_token_count(messages: List[dict[str, Any]]) -> int:
    """
    Estimate token count for a list of messages using word-based heuristic.

    Approximation: words * 1.3 to account for tokenization overhead.
    This is a rough estimate; for precise counting, use tiktoken or similar.
    """
    total_words = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            # Split by whitespace and count
            total_words += len(content.split())
        elif isinstance(content, list):
            # Handle multi-part content (images, text, etc.)
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total_words += len(part["text"].split())
    # Apply 1.3x multiplier for tokenization overhead
    return int(total_words * 1.3)
