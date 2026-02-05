"""
apps/services/tool_server/candidate_filter.py

Intelligent pre-visit filtering of search candidates.
Scores and filters search results BEFORE expensive page visits.

STATUS: Dead code — not imported by any active module.
Legacy heuristic fallback; replaced by llm_candidate_filter.py with SourceQualityScorer.
"""
import re
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# TODO(LLM-FIRST): These hardcoded blocklist patterns violate the LLM-first design principle.
# INSTEAD OF: Hardcoded URL pattern blocklists
# SHOULD BE: Pass URL + title + snippet to LLM (via SourceQualityScorer in llm_candidate_filter.py)
#            and let it decide relevance based on the user's ORIGINAL QUERY.
#
# The LLM can understand context that patterns cannot:
# - A forum post ABOUT buying hamsters IS relevant to "where to buy hamster"
# - A wiki page comparing products COULD be useful research
#
# This file is marked as "Legacy heuristic fallback" in the docstring.
# Prefer: apps/services/tool_server/llm_candidate_filter.py with SourceQualityScorer
BLOCKLIST_PATTERNS = [
    r'.*/forum/.*',
    r'.*/thread/.*',
    r'.*/discussion/.*',
    r'.*/blog/.*',
    r'.*/news/.*',
    r'.*/wiki/.*',
    r'.*/help.*',
    r'.*/about.*',
    r'.*/privacy.*',
    r'.*/terms.*',
    r'.*/login.*',
    r'.*/signup.*',
]

# TODO(LLM-FIRST): These indicator lists encode knowledge that the LLM should derive from context.
# INSTEAD OF: Hardcoded positive/negative indicators with fixed weights
# SHOULD BE: Pass candidate info + original_query to LLM, let it score based on user intent.
#
# Example: "syrian hamster" is only relevant if user is searching for hamsters.
#          The current hardcoded +0.3 boost is query-agnostic.
#
# Prefer: apps/services/tool_server/llm_candidate_filter.py with SourceQualityScorer
BAD_INDICATORS = [
    ('checking your browser', -0.5),  # Cloudflare challenge
    ('please enable javascript', -0.4),
    ('access denied', -0.5),
    ('403 forbidden', -0.5),
    ('404 not found', -0.6),
    ('wiki', -0.3),                   # Encyclopedia-style content
    ('forum', -0.3),
    ('discussion', -0.25),
]

# See TODO above - these indicators should be LLM-evaluated, not hardcoded
GOOD_INDICATORS = [
    ('for sale', 0.25),
    ('buy', 0.2),
    ('price', 0.15),
    ('shipping', 0.15),
    ('available', 0.15),
    ('breeder', 0.25),
    ('ethical', 0.2),
    ('pedigree', 0.2),
    ('syrian hamster', 0.3),
]


def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Remove www.
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def is_blocklisted(url: str) -> bool:
    """Check if URL matches blocklist patterns."""
    url_lower = url.lower()
    for pattern in BLOCKLIST_PATTERNS:
        if re.search(pattern, url_lower):
            return True
    return False


def score_candidate(
    url: str,
    title: str,
    snippet: str,
    query_intent: str = "transactional",
    user_location: str = "us"
) -> float:
    """
    Score candidate 0.0-1.0 based on likely relevance and accessibility.

    Args:
        url: Candidate URL
        title: Page title from search result
        snippet: Snippet/description from search result
        query_intent: Query intent (transactional/informational/navigational)
        user_location: User location code (us/uk/au/etc)

    Returns:
        Score 0.0-1.0 (higher = better candidate)
        0.0 means skip this candidate
    """
    domain = extract_domain(url)
    score = 0.5  # Start neutral

    # Check blocklist (immediate reject)
    if is_blocklisted(url):
        logger.info(f"[Filter] BLOCKED: {url} (matches blocklist)")
        return 0.0

    # Generic URL hints for product or listing pages
    url_lower = url.lower()
    if any(token in url_lower for token in ["/product", "/shop", "/store", "/search", "?q=", "?query="]):
        score += 0.1
        logger.debug(f"[Filter] URL product/listing hint: {url[:60]}")

    # Analyze title + snippet
    combined_text = f"{title} {snippet}".lower()

    # Check bad indicators
    for indicator, penalty in BAD_INDICATORS:
        if indicator in combined_text:
            score += penalty  # penalty is negative
            logger.debug(f"[Filter] Bad indicator '{indicator}' → {penalty}")

    # Check good indicators (only for transactional queries)
    if query_intent == "transactional":
        for indicator, bonus in GOOD_INDICATORS:
            if indicator in combined_text:
                score += bonus
                logger.debug(f"[Filter] Good indicator '{indicator}' → +{bonus}")

    # Geo-mismatch penalty (non-US sites for US users buying products)
    if query_intent == "transactional" and user_location == "us":
        if domain.endswith(('.ie', '.co.uk', '.com.au', '.co.nz')):
            score -= 0.2
            logger.debug(f"[Filter] Geo mismatch penalty: {domain} for US user → -0.2")

    # Clamp to [0.0, 1.0]
    final_score = max(0.0, min(1.0, score))

    return final_score


def filter_candidates(
    candidates: List[Dict[str, Any]],
    query_intent: str = "transactional",
    user_location: str = "us",
    min_score: float = 0.3,
    max_candidates: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Filter and score search candidates before visiting.

    Args:
        candidates: List of search results with url, title, snippet
        query_intent: Query intent type
        user_location: User location code
        min_score: Minimum quality score to keep (0.0-1.0)
        max_candidates: Max candidates to return (None = no limit)

    Returns:
        Filtered and sorted list of candidates with quality_score added
    """
    scored_candidates = []

    for candidate in candidates:
        url = candidate.get('url', '')
        title = candidate.get('title', '')
        snippet = candidate.get('snippet', '')

        # Score this candidate
        score = score_candidate(url, title, snippet, query_intent, user_location)

        # Skip if below threshold
        if score < min_score:
            logger.info(
                f"[Filter] SKIP (score {score:.2f} < {min_score}): "
                f"{url[:60]} - {title[:40]}"
            )
            continue

        # Add score to candidate
        candidate['quality_score'] = score
        scored_candidates.append(candidate)

        logger.info(
            f"[Filter] KEEP (score {score:.2f}): "
            f"{url[:60]} - {title[:40]}"
        )

    # Sort by score (highest first)
    scored_candidates.sort(key=lambda c: c['quality_score'], reverse=True)

    # Limit to max_candidates if specified
    if max_candidates and len(scored_candidates) > max_candidates:
        logger.info(
            f"[Filter] Limiting to top {max_candidates} of {len(scored_candidates)} candidates"
        )
        scored_candidates = scored_candidates[:max_candidates]

    logger.info(
        f"[Filter] Summary: {len(candidates)} input → {len(scored_candidates)} kept "
        f"(filtered {len(candidates) - len(scored_candidates)})"
    )

    return scored_candidates


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test with real bad examples from logs
    test_candidates = [
        {
            'url': 'https://www.allkpop.com/forum/threads/i-want-a-hamster.20585/',
            'title': 'I want a hamster - K-POP Forum',
            'snippet': 'Forum discussion about wanting a hamster as a pet'
        },
        {
            'url': 'https://www.poppybeehamstery.com/hamsters-for-sale',
            'title': 'Syrian Hamsters for Sale - Poppy Bee Hamstery',
            'snippet': 'Ethical Syrian hamster breeder. $35 per hamster. Shipping available.'
        },
        {
            'url': 'https://whatsoftware.com/hamster-vpn',
            'title': 'Download Hamster VPN Software',
            'snippet': 'Free VPN software download for Windows and Mac'
        },
        {
            'url': 'https://www.amazon.com/hamster-cage/s?k=hamster+cage',
            'title': 'Amazon.com: Hamster Cage',
            'snippet': 'Shop for hamster cages on Amazon'
        },
        {
            'url': 'https://furballcritters.com/syrian-hamsters',
            'title': 'Syrian Hamsters - Furball Critters',
            'snippet': 'Healthy Syrian hamsters for sale. $35. Ethical breeding practices.'
        }
    ]

    print("\n" + "=" * 80)
    print("CANDIDATE FILTER TEST")
    print("=" * 80 + "\n")

    filtered = filter_candidates(
        test_candidates,
        query_intent="transactional",
        user_location="us",
        min_score=0.3
    )

    print(f"\n\nFINAL RESULTS: {len(filtered)}/{len(test_candidates)} candidates kept")
    for i, c in enumerate(filtered, 1):
        print(f"{i}. [{c['quality_score']:.2f}] {c['title']}")
        print(f"   {c['url']}")
