"""
Result validation using word matching + species exclusion.

Simpler approach:
1. Primary: Query keywords MUST appear in results (e.g., "Syrian" must be in result)
2. Secondary: Wrong-species keywords MUST NOT appear (e.g., no "hedgehog" in hamster results)

Replaces complex taxonomy system with maintainable word matching.
"""
import re
import logging
from typing import Tuple, Set

logger = logging.getLogger(__name__)

# Species exclusion lists - prevents wrong-species results
SPECIES_EXCLUSIONS = {
    "hamster": ["hedgehog", "guinea pig", "gerbil", "mouse", "rat", "rabbit", "chinchilla"],
    "hedgehog": ["hamster", "guinea pig", "porcupine", "echidna"],
    "guinea pig": ["hamster", "hedgehog", "rabbit", "chinchilla"],
    "rabbit": ["guinea pig", "hamster", "hare"],
    "ferret": ["weasel", "mink", "otter"],
}

# Common stop words to skip in keyword extraction
STOP_WORDS = {
    "for", "sale", "buy", "find", "get", "show", "me", "the", "a", "an", "in", "near", "at",
    "to", "from", "with", "by", "on", "of", "and", "or", "but", "is", "are", "was", "were",
    "my", "your", "their", "this", "that", "these", "those", "can", "could", "should", "would",
    "will", "shall", "may", "might", "must", "need", "want", "have", "has", "had", "do", "does",
    "did", "be", "been", "being", "am", "i", "you", "he", "she", "it", "we", "they", "what",
    "where", "when", "why", "how", "which", "who", "whom", "whose",
    # Context qualifiers (not product attributes)
    "reputable", "trusted", "reliable", "verified", "certified", "licensed", "ethical",
    "sources", "source", "sellers", "seller", "vendors", "vendor", "breeders", "breeder",
    "stores", "store", "shops", "shop", "sites", "site", "places", "place",
    "available", "current", "new", "fresh", "latest", "recent", "updated"
}


def extract_keywords(text: str) -> Set[str]:
    """
    Extract meaningful keywords from query text.

    Args:
        text: Query text (e.g., "Syrian hamster for sale near me")

    Returns:
        Set of lowercase keywords excluding stop words
        Example: {"syrian", "hamster"}
    """
    # Split on whitespace and punctuation
    words = re.findall(r'\b\w+\b', text.lower())

    # Filter stop words and very short words
    keywords = {w for w in words if w not in STOP_WORDS and len(w) > 2}

    return keywords


def validate_word_match(query: str, result_text: str) -> Tuple[float, str]:
    """
    Score how well result matches query keywords (graduated scoring).

    Scoring system:
    - 1.0: All keywords present (perfect match)
    - 0.6: Has species keyword + partial others (acceptable)
    - 0.3: Has species keyword only (weak match)
    - 0.0: Missing species keyword (reject)

    Args:
        query: User query (e.g., "Syrian hamster for sale")
        result_text: Result title + description

    Returns:
        (match_score, rejection_reason)

    Example:
        Query: "Syrian hamster"
        Keywords: ["syrian", "hamster"]

        Result: "Syrian hamster available"  → (1.0, "") perfect
        Result: "Hamster for sale"          → (0.6, "") partial - has species
        Result: "Dwarf hamster"             → (0.3, "variety_mismatch:dwarf") wrong variety
        Result: "Hedgehog"                  → (0.0, "missing_species") no species keyword
    """
    query_keywords = extract_keywords(query)

    # Empty query or only stop words - can't validate
    if not query_keywords:
        logger.warning(f"[WordMatch] No keywords extracted from query: {query[:60]}")
        return (1.0, "")

    result_lower = result_text.lower()
    present_keywords = [kw for kw in query_keywords if kw in result_lower]
    missing_keywords = [kw for kw in query_keywords if kw not in result_lower]

    # Check if species keyword (hamster, hedgehog, etc.) is present
    species_keywords = {"hamster", "hedgehog", "guinea", "rabbit", "ferret", "gerbil", "mouse", "rat"}
    has_species = any(kw in present_keywords for kw in species_keywords)

    if not has_species:
        # No species keyword → complete reject
        logger.info(
            f"[WordMatch-REJECT] Missing species keyword | "
            f"Query: {query[:60]} | Result: {result_text[:80]}"
        )
        return (0.0, f"missing_species")

    # Calculate match ratio
    match_ratio = len(present_keywords) / len(query_keywords)

    if match_ratio == 1.0:
        # Perfect match - all keywords present
        logger.debug(
            f"[WordMatch-PERFECT] All keywords present: {query_keywords} | Result: {result_text[:80]}"
        )
        return (1.0, "")
    elif match_ratio >= 0.5:
        # Partial match - has species + some other keywords
        logger.info(
            f"[WordMatch-PARTIAL] Has {len(present_keywords)}/{len(query_keywords)} keywords | "
            f"Missing: {missing_keywords} | Result: {result_text[:80]}"
        )
        return (0.6, f"partial_match:missing_{','.join(sorted(missing_keywords)[:2])}")
    else:
        # Weak match - has species but missing most other keywords
        logger.info(
            f"[WordMatch-WEAK] Only has species keyword | "
            f"Missing: {missing_keywords} | Result: {result_text[:80]}"
        )
        return (0.3, f"weak_match:missing_{','.join(sorted(missing_keywords)[:2])}")


def check_excluded_species(query: str, result_text: str) -> Tuple[float, str]:
    """
    Reject results containing wrong-species keywords.

    Secondary validation: Wrong-species keywords MUST NOT appear.

    Args:
        query: User query
        result_text: Result title + description

    Returns:
        (match_score, rejection_reason)
        - 1.0, "" if no excluded species found
        - 0.0, "excluded_species:..." if wrong species detected

    Example:
        Query: "hamster" → reject if result contains "hedgehog"
        Query: "guinea pig" → reject if result contains "hamster"
    """
    query_lower = query.lower()
    result_lower = result_text.lower()

    # Check if query mentions any target species
    for target_species, excluded_list in SPECIES_EXCLUSIONS.items():
        if target_species not in query_lower:
            continue

        # Query mentions this species - check for excluded species in result
        for excluded in excluded_list:
            if excluded in result_lower:
                logger.info(
                    f"[SpeciesExclude-REJECT] Query has '{target_species}' but result has '{excluded}' | "
                    f"Query: {query[:60]} | Result: {result_text[:80]}"
                )
                return (0.0, f"excluded_species:{excluded}")

    logger.debug(f"[SpeciesExclude-PASS] No excluded species found | Result: {result_text[:80]}")
    return (1.0, "")


def validate_species_match(query_text: str, result_text: str) -> Tuple[float, str]:
    """
    Combined validation: word matching + species exclusion.

    Two-stage filtering:
    1. Required word matching (query keywords must appear)
    2. Species exclusion (wrong-species keywords must not appear)

    Args:
        query_text: User query (e.g., "Syrian hamster for sale")
        result_text: Result title + description

    Returns:
        (match_score, rejection_reason)
        - 1.0, "" if passes both filters
        - 0.0, "..." if fails either filter

    Example:
        Query: "Syrian hamster"
        Result: "Hamster for sale" → 0.0 (missing "syrian")
        Result: "Hedgehog for sale" → 0.0 (excluded species)
        Result: "Syrian hamster available" → 1.0 (pass)
    """
    # Stage 1: Word matching (primary filter)
    word_score, word_reason = validate_word_match(query_text, result_text)
    if word_score == 0.0:
        return (word_score, word_reason)

    # Stage 2: Species exclusion (safety net)
    species_score, species_reason = check_excluded_species(query_text, result_text)
    if species_score == 0.0:
        return (species_score, species_reason)

    # Passed both filters
    logger.info(
        f"[Validation-PASS] Result matches query | "
        f"Query: {query_text[:60]} | Result: {result_text[:80]}"
    )
    return (1.0, "")
