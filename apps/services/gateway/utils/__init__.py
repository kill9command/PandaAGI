"""
Gateway Utility Modules

Provides text processing, JSON parsing, and trace management utilities.
"""

from apps.services.gateway.utils.text import (
    contains_keyword_phrase,
    extract_subject_keywords,
    last_user_subject,
    extract_urls,
    is_long_running_query,
    clean_subject,
    normalize_species,
    estimate_token_count,
    # Regex patterns
    ACK_PHRASES,
    SUBJECT_KEYWORDS,
    SPECIES_HINTS,
    SPECIES_ALIASES,
    LEADING_STOPWORDS,
    KEYWORD_STOP_WORDS,
    PREFERENCE_PATTERNS,
    ACTIVITY_PATTERNS,
    OFFER_SKIP_KEYWORDS,
    REPEAT_HINT_RE,
)

from apps.services.gateway.utils.json_helpers import (
    extract_json,
    iter_json_object_slices,
    JSON_FENCE_RE,
)

from apps.services.gateway.utils.trace import (
    build_trace_envelope,
    append_trace,
)

__all__ = [
    # Text utilities
    "contains_keyword_phrase",
    "extract_subject_keywords",
    "last_user_subject",
    "extract_urls",
    "is_long_running_query",
    "clean_subject",
    "normalize_species",
    "estimate_token_count",
    # Patterns
    "ACK_PHRASES",
    "SUBJECT_KEYWORDS",
    "SPECIES_HINTS",
    "SPECIES_ALIASES",
    "LEADING_STOPWORDS",
    "KEYWORD_STOP_WORDS",
    "PREFERENCE_PATTERNS",
    "ACTIVITY_PATTERNS",
    "OFFER_SKIP_KEYWORDS",
    "REPEAT_HINT_RE",
    # JSON utilities
    "extract_json",
    "iter_json_object_slices",
    "JSON_FENCE_RE",
    # Trace utilities
    "build_trace_envelope",
    "append_trace",
]
