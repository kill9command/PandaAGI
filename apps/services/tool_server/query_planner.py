"""
LLM-Driven Search Query Planner

Generates optimized search strategies using LLM to create multiple targeted queries
instead of using raw user input directly.

Architecture: Structured JSON Output
- LLM extracts search components (keywords, site, quoted_phrase, context)
- Code assembles valid search string deterministically
- Fallback chain ensures reliability
- Metrics track success rate for observability
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import json
import httpx

from apps.services.tool_server.shared.llm_utils import load_prompt_via_recipe as _load_prompt_via_recipe

logger = logging.getLogger(__name__)


# =============================================================================
# Structured Query Builder - Types and Metrics
# =============================================================================

class QueryBuildMethod(Enum):
    """How the search query was built - for observability."""
    STRUCTURED_JSON = "structured_json"      # LLM JSON parsed successfully
    RAW_STRING = "raw_string"                # JSON failed, raw string used
    KEYWORD_FALLBACK = "keyword_fallback"    # All failed, extracted keywords


@dataclass
class QueryBuildResult:
    """Result of query building with full observability."""
    query: str
    method: QueryBuildMethod
    llm_raw_response: str = ""
    components: Optional[Dict] = None
    parse_error: Optional[str] = None

    @property
    def used_fallback(self) -> bool:
        return self.method != QueryBuildMethod.STRUCTURED_JSON


class QueryBuilderMetrics:
    """Track query builder health over time."""

    def __init__(self):
        self.total_calls = 0
        self.structured_success = 0
        self.raw_string_fallback = 0
        self.keyword_fallback = 0
        self.recent_failures: List[Dict] = []

    def record(self, result: QueryBuildResult, user_query: str):
        """Record a query build attempt."""
        self.total_calls += 1

        if result.method == QueryBuildMethod.STRUCTURED_JSON:
            self.structured_success += 1
            logger.info(
                f"[QueryBuilder] STRUCTURED_JSON success: '{result.query}' "
                f"(components: {result.components})"
            )
        elif result.method == QueryBuildMethod.RAW_STRING:
            self.raw_string_fallback += 1
            self._record_failure(result, user_query)
            logger.warning(
                f"[QueryBuilder] RAW_STRING fallback - JSON parse failed\n"
                f"  User query: {user_query[:60]}...\n"
                f"  LLM response: {result.llm_raw_response[:100]}...\n"
                f"  Parse error: {result.parse_error}\n"
                f"  Using: '{result.query}'"
            )
        else:
            self.keyword_fallback += 1
            self._record_failure(result, user_query)
            logger.error(
                f"[QueryBuilder] KEYWORD_FALLBACK - all methods failed!\n"
                f"  User query: {user_query}\n"
                f"  LLM response: {result.llm_raw_response[:200]}...\n"
                f"  Parse error: {result.parse_error}\n"
                f"  Falling back to: '{result.query}'"
            )

    def _record_failure(self, result: QueryBuildResult, user_query: str):
        """Store failure for debugging."""
        self.recent_failures.append({
            "timestamp": datetime.now().isoformat(),
            "method": result.method.value,
            "user_query": user_query[:100],
            "llm_response": result.llm_raw_response[:500],
            "parse_error": result.parse_error,
            "query_used": result.query
        })
        # Keep last 50 failures
        self.recent_failures = self.recent_failures[-50:]

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.structured_success / self.total_calls

    def get_health_report(self) -> Dict:
        """Get health report for monitoring."""
        return {
            "total_calls": self.total_calls,
            "structured_success": self.structured_success,
            "raw_string_fallback": self.raw_string_fallback,
            "keyword_fallback": self.keyword_fallback,
            "success_rate": f"{self.success_rate:.1%}",
            "recent_failures_count": len(self.recent_failures),
            "recent_failures": self.recent_failures[-5:]  # Last 5 for quick view
        }


# Global metrics instance
query_builder_metrics = QueryBuilderMetrics()


def get_query_builder_metrics() -> Dict:
    """Get current query builder metrics - for health endpoints."""
    return query_builder_metrics.get_health_report()


# =============================================================================
# Structured Query Builder - Core Functions
# =============================================================================

def _parse_llm_json(raw_response: str) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Robust JSON extraction from LLM response.

    Returns:
        (parsed_dict, None) on success
        (None, error_message) on failure
    """
    text = raw_response.strip()

    # Strip markdown code blocks
    if "```" in text:
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            text = match.group(1)

    # Find JSON object (first { to last })
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1 or start >= end:
        return None, "No JSON object found in response"

    text = text[start:end + 1]

    # Parse JSON
    try:
        data = json.loads(text)
        return data, None
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {str(e)[:100]}"


def _validate_search_components(data: Dict) -> Optional[Dict]:
    """
    Validate and normalize extracted components.

    Returns normalized dict or None if invalid.
    """
    if not isinstance(data, dict):
        return None

    # Extract and validate each field with safe defaults
    keywords = data.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []
    keywords = [str(k).strip() for k in keywords if k]

    site = data.get("site")
    if site and isinstance(site, str):
        site = site.strip().lower()
        # Normalize common variations
        if site in ("null", "none", ""):
            site = None
    else:
        site = None

    quoted_phrase = data.get("quoted_phrase")
    if quoted_phrase and isinstance(quoted_phrase, str):
        quoted_phrase = quoted_phrase.strip()
        if quoted_phrase.lower() in ("null", "none", ""):
            quoted_phrase = None
    else:
        quoted_phrase = None

    context_keywords = data.get("context_keywords", [])
    if not isinstance(context_keywords, list):
        context_keywords = []
    context_keywords = [str(k).strip() for k in context_keywords if k]

    # Must have at least keywords or quoted_phrase
    if not keywords and not quoted_phrase:
        return None

    return {
        "keywords": keywords,
        "site": site,
        "quoted_phrase": quoted_phrase,
        "context_keywords": context_keywords
    }


def _assemble_search_query(components: Dict) -> str:
    """
    Deterministically assemble search query from validated components.

    This is the key benefit: code controls string formatting,
    so no malformed quotes or syntax errors.
    """
    parts = []

    # Add quoted phrase if present (with proper quoting)
    if components.get("quoted_phrase"):
        parts.append(f'"{components["quoted_phrase"]}"')

    # Add main keywords
    if components.get("keywords"):
        parts.extend(components["keywords"])

    # Add context keywords
    if components.get("context_keywords"):
        parts.extend(components["context_keywords"])

    query = " ".join(parts)

    # Add site filter (deterministic, always correct format)
    if components.get("site"):
        query += f" site:{components['site']}"

    return query

def _load_prompt(prompt_name: str) -> str:
    """Load prompt - maps legacy names to recipe names."""
    return _load_prompt_via_recipe(prompt_name, "research")


def _load_query_prompt(prompt_name: str) -> str:
    """Load prompt - maps legacy query prompt names to recipe names."""
    return _load_prompt_via_recipe(prompt_name, "research")


async def simplify_query_for_retailers_async(query: str, llm_url: str = None, llm_api_key: str = None) -> str:
    """
    LLM-based query simplification for retailer search.

    Converts natural language queries to simple keyword searches using LLM.

    Examples:
        "whats the cheapest laptop with an nvidia gpu" → "laptop NVIDIA GPU"
        "Find Syrian hamsters for sale near me" → "Syrian hamster"
    """
    import os

    llm_url = llm_url or os.environ.get("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    llm_api_key = llm_api_key or os.environ.get("SOLVER_API_KEY", "qwen-local")

    # Load prompt from recipe file
    base_prompt = _load_query_prompt("query_sanitizer")
    if not base_prompt:
        base_prompt = """Convert a natural language query to simple search keywords for a retailer website.

Rules:
- Remove conversational phrases (find me, can you, please, etc.)
- Remove commerce phrases (for sale, cheap, best price, etc.)
- Keep product names, brands, and key specifications
- Keep it short (2-5 words typically)
- Preserve brand casing (NVIDIA, RTX, AMD, etc.)

Output ONLY the simplified search terms, nothing else."""

    # Build full prompt with dynamic data
    prompt = f"""{base_prompt}

## Current Query
QUERY: {query}

OUTPUT: Just the simplified search terms, nothing else."""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                llm_url,
                headers={"Authorization": f"Bearer {llm_api_key}"},
                json={
                    "model": "default",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 50,
                    "temperature": 0.1,
                    "top_p": 0.8,
                    "stop": ["<|im_end|>", "<|endoftext|>"],
                    "repetition_penalty": 1.05
                }
            )
            response.raise_for_status()
            result = response.json()["choices"][0]["message"]["content"].strip()

            # Sanity check: result should be shorter and reasonable
            if result and len(result) < len(query) * 2 and len(result) > 2:
                logger.info(f"[QuerySimplify-LLM] '{query}' → '{result}'")
                return result

    except Exception as e:
        logger.warning(f"[QuerySimplify-LLM] Failed: {e}, using fallback")

    # Fallback to simple extraction
    return simplify_query_for_retailers(query)


def detect_price_priority(query: str) -> str:
    """
    Detect user's price priority from the original query.

    Returns:
        "low" if user wants cheapest/budget options
        "high" if user wants premium/expensive options
        None if no clear price priority

    Examples:
        "cheapest laptop" → "low"
        "budget gaming PC" → "low"
        "best premium laptop" → "high"
        "laptop with nvidia gpu" → None
    """
    query_lower = query.lower()

    # Keywords indicating user wants low prices
    low_price_keywords = [
        "cheapest", "cheap", "budget", "affordable", "inexpensive",
        "lowest price", "best deal", "on sale", "clearance",
        "under $", "less than $", "below $"
    ]

    # Keywords indicating user wants high-end/premium
    high_price_keywords = [
        "premium", "high-end", "luxury", "expensive", "top of the line",
        "flagship", "best money can buy"
    ]

    for keyword in low_price_keywords:
        if keyword in query_lower:
            logger.info(f"[PriceDetect] Found low-price keyword '{keyword}' in query")
            return "low"

    for keyword in high_price_keywords:
        if keyword in query_lower:
            logger.info(f"[PriceDetect] Found high-price keyword '{keyword}' in query")
            return "high"

    return None


def simplify_query_for_retailers(query: str) -> str:
    """
    Fast fallback query simplification using keyword extraction.

    Converts natural language queries to simple keyword searches.
    """
    import re

    query_lower = query.lower().strip()

    # Remove common conversational prefixes
    for prefix in ["find me ", "show me ", "get me ", "i need ", "i want ",
                   "can you find ", "help me find ", "looking for ", "search for "]:
        if query_lower.startswith(prefix):
            query_lower = query_lower[len(prefix):]

    # Remove common suffixes
    for suffix in [" for sale", " near me", " online", " please", " for me",
                   " to buy", " to purchase"]:
        if query_lower.endswith(suffix):
            query_lower = query_lower[:-len(suffix)]

    # Remove price modifiers (but not the price itself if specific)
    query_lower = re.sub(r'\b(cheap|cheapest|best|good|great|affordable|budget)\b', '', query_lower)

    # Extract key terms (brands, products, specs)
    tech_terms = ["laptop", "monitor", "keyboard", "mouse", "gpu", "cpu", "ssd",
                  "nvidia", "rtx", "geforce", "amd", "intel", "gaming", "hamster",
                  "4060", "4070", "4080", "4090", "syrian", "phone", "tablet"]

    words = query_lower.split()
    key_words = []
    for w in words:
        if any(t in w.lower() for t in tech_terms) or len(w) > 3:
            key_words.append(w)

    result = " ".join(key_words[:6]) if key_words else query_lower
    result = " ".join(result.split())  # Clean spaces

    if result != query.lower().strip():
        logger.info(f"[QuerySimplify] '{query}' → '{result}'")

    return result


def construct_vendor_search_url(
    retailer: str,
    query: str,
    price_range: Dict = None,
    sort_by_price: str = None
) -> str:
    """
    Get starting URL for a vendor.

    The web agent handles searching, filtering, and sorting via the UI.
    We just provide the homepage as a starting point.

    Args:
        retailer: Domain of the retailer (e.g., "bestbuy.com")
        query: Search query (passed to agent, not encoded in URL)
        price_range: Dict with 'min' and 'max' price values (agent handles via UI)
        sort_by_price: "low" or "high" (agent handles via UI)

    Returns:
        Homepage URL - agent navigates from there
    """
    # NOTE: No hardcoded search URL patterns or site-specific templates
    # The web agent uses the site's search functionality and UI controls
    # This follows architecture principle: teach the system, don't hardcode per-site

    if sort_by_price:
        logger.debug(f"[VendorURL] sort_by_price={sort_by_price} - agent will handle via UI")
    if price_range:
        logger.debug(f"[VendorURL] price_range={price_range} - agent will handle via UI")

    # Always start at homepage - agent finds search bar and navigates
    return f"https://www.{retailer}/"


async def build_phase1_search_terms(
    user_query: str,
    query_type: str = "general",
    mode: str = "standard",
    intent: str = "general",
    intent_metadata: Optional[Dict] = None,
    prior_turn_context: Optional[str] = None,
    topic: Optional[str] = None,
    solver_url: Optional[str] = None,
    solver_model_id: Optional[str] = None,
    solver_api_key: Optional[str] = None
) -> List[str]:
    """
    Build Phase 1 search terms for internet search engines.

    Uses STRUCTURED JSON OUTPUT for reliability:
    1. LLM extracts search components (keywords, site, quoted_phrase, context_keywords)
    2. Code assembles valid search string deterministically
    3. Fallback chain: structured JSON → raw string → keyword extraction
    4. Metrics track success rate for observability

    Args:
        user_query: Original user query (what user asked)
        query_type: Unused, kept for backward compatibility
        mode: Unused, kept for backward compatibility
        intent: Query intent - "navigation" and "site_search" bypass Google
        intent_metadata: Contains target_url, site_name for special intents
        prior_turn_context: Summary of previous turn for context-aware query building
        topic: Topic classification from context gatherer
        solver_url: URL of the LLM solver service
        solver_model_id: Model ID to use
        solver_api_key: API key for authentication

    Returns:
        List containing search terms to send to search engine
        For navigation/site_search: Returns empty list (direct navigation)
    """
    import os

    # Use env vars as defaults
    solver_url = solver_url or os.environ.get("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    solver_model_id = solver_model_id or os.environ.get("SOLVER_MODEL_ID", "qwen3-coder")
    solver_api_key = solver_api_key or os.environ.get("SOLVER_API_KEY", "qwen-local")

    intent_metadata = intent_metadata or {}

    # NAVIGATION: Skip Google, direct URL navigation handled downstream
    if intent == "navigation":
        target_url = intent_metadata.get("target_url", "")
        logger.info(f"[QueryPlanner] NAVIGATION intent - direct navigation to: {target_url}")
        return []

    # SITE_SEARCH: Skip Google, direct site navigation handled downstream
    if intent == "site_search":
        site_name = intent_metadata.get("site_name", "")
        logger.info(f"[QueryPlanner] SITE_SEARCH intent - direct navigation to: {site_name}")
        return []

    logger.info(f"[SearchTermBuilder] Building search terms for: '{user_query}'")

    # Load structured JSON prompt
    base_prompt = _load_query_prompt("phase1_search_terms_structured")
    if not base_prompt:
        # Fallback prompt if file missing
        base_prompt = """Extract search components from the user's query. Output JSON only.

## Output Format
```json
{"keywords": ["main", "search", "terms"], "site": "domain.com or null", "quoted_phrase": "exact phrase or null", "context_keywords": ["from", "prior", "context"]}
```

## Rules
1. **keywords**: Core search terms (2-6 words). Remove filler ("find me", "can you", "please").
2. **site**: If user mentions a specific site (Reddit → reddit.com, Reef2Reef → reef2reef.com), map it. Otherwise null.
3. **quoted_phrase**: If user wants a SPECIFIC article/thread title (in quotes), preserve it exactly. Otherwise null.
4. **context_keywords**: If conversation context is provided AND relevant, add connecting keywords. Otherwise empty array.

Output ONLY the JSON object, no explanation."""

    # Build prompt with context
    context_section = ""
    if prior_turn_context:
        context_section = f"\n**Context:** {prior_turn_context[:300]}\n"

    prompt = f"""{base_prompt}

**Query:** "{user_query}"{context_section}"""

    llm_raw_response = ""
    build_result: QueryBuildResult

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                solver_url,
                headers={
                    "Authorization": f"Bearer {solver_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": solver_model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 150,
                    "top_p": 0.8,
                    "stop": ["<|im_end|>", "<|endoftext|>"],
                    "repetition_penalty": 1.05
                }
            )
            response.raise_for_status()
            result = response.json()
            llm_raw_response = result["choices"][0]["message"]["content"].strip()

            # ===== ATTEMPT 1: Parse as structured JSON =====
            parsed, parse_error = _parse_llm_json(llm_raw_response)

            if parsed:
                components = _validate_search_components(parsed)
                if components:
                    # SUCCESS: Assemble query from validated components
                    query = _assemble_search_query(components)
                    build_result = QueryBuildResult(
                        query=query,
                        method=QueryBuildMethod.STRUCTURED_JSON,
                        llm_raw_response=llm_raw_response,
                        components=components
                    )
                    query_builder_metrics.record(build_result, user_query)
                    logger.info(f"[SearchTermBuilder] '{user_query[:50]}...' → '{query}'")
                    return [query]
                else:
                    parse_error = "JSON parsed but validation failed (no keywords or quoted_phrase)"

            # ===== ATTEMPT 2: Use raw response as query (if it looks like one) =====
            # Sometimes LLM outputs a plain query string instead of JSON
            raw_as_query = llm_raw_response.strip().strip('"').strip("'").strip('`')
            # Remove markdown if present
            if raw_as_query.startswith("```"):
                lines = raw_as_query.split('\n')
                raw_as_query = '\n'.join(lines[1:-1]) if len(lines) > 2 else raw_as_query[3:]
            raw_as_query = raw_as_query.strip()

            # Check if it looks like a search query (short, no JSON structure)
            if (raw_as_query
                and '{' not in raw_as_query
                and len(raw_as_query.split()) <= 12
                and "I'll" not in raw_as_query
                and "help you" not in raw_as_query):

                # Fix unbalanced quotes just in case
                if raw_as_query.count('"') % 2 == 1:
                    if ' site:' in raw_as_query:
                        parts = raw_as_query.split(' site:')
                        parts[0] = parts[0].replace('"', '')
                        raw_as_query = ' site:'.join(parts)
                    else:
                        raw_as_query = raw_as_query.replace('"', '')

                build_result = QueryBuildResult(
                    query=raw_as_query,
                    method=QueryBuildMethod.RAW_STRING,
                    llm_raw_response=llm_raw_response,
                    parse_error=parse_error
                )
                query_builder_metrics.record(build_result, user_query)
                logger.info(f"[SearchTermBuilder] '{user_query[:50]}...' → '{raw_as_query}' (raw fallback)")
                return [raw_as_query]

            # ===== ATTEMPT 3: Keyword extraction fallback =====
            fallback_query = _extract_keywords_fallback(user_query)
            build_result = QueryBuildResult(
                query=fallback_query,
                method=QueryBuildMethod.KEYWORD_FALLBACK,
                llm_raw_response=llm_raw_response,
                parse_error=parse_error or "Response doesn't look like a search query"
            )
            query_builder_metrics.record(build_result, user_query)
            logger.info(f"[SearchTermBuilder] '{user_query[:50]}...' → '{fallback_query}' (keyword fallback)")
            return [fallback_query]

    except Exception as e:
        # Network/LLM error - go straight to keyword fallback
        fallback_query = _extract_keywords_fallback(user_query)
        build_result = QueryBuildResult(
            query=fallback_query,
            method=QueryBuildMethod.KEYWORD_FALLBACK,
            llm_raw_response=llm_raw_response,
            parse_error=f"LLM call failed: {str(e)[:100]}"
        )
        query_builder_metrics.record(build_result, user_query)
        logger.error(f"[SearchTermBuilder] LLM failed: {e}, using keyword fallback")
        return [fallback_query]


# Backward compatibility alias
plan_phase1_queries = build_phase1_search_terms


def _extract_keywords_fallback(user_query: str) -> str:
    """
    Simple keyword extraction fallback when LLM fails.

    Removes common filler words and returns remaining keywords.
    """
    filler_words = {
        # Conversational
        "can", "you", "could", "would", "please", "help", "me", "i", "want",
        "to", "find", "get", "show", "looking", "for", "the", "a", "an",
        "whats", "what", "is", "are", "how", "do", "does", "need", "some",
        "any", "most", "really", "very",
        # Commerce filler (but NOT price constraints - those are user requirements)
        "sale", "buy", "purchase", "online",
        "near", "nearby", "local", "store", "shop"
        # NOTE: "cheapest", "budget", "affordable" are NOT filler - they're user price requirements
        # NOTE: "price", "cost" are NOT filler - they indicate price-focused search
    }

    words = user_query.lower().split()
    keywords = [w for w in words if w not in filler_words and len(w) > 1]

    # Keep at least 2 words, max 8
    if len(keywords) < 2:
        keywords = words[:4]  # Just take first few words if too aggressive

    return " ".join(keywords[:8])


async def plan_phase2_queries(
    user_query: str,
    intelligence: Optional[Dict] = None,
    mode: str = "standard",  # "standard" or "deep"
    solver_url: str = "http://127.0.0.1:8000",
    solver_model_id: str = "qwen3-coder",
    solver_api_key: str = "qwen-local"
) -> List[str]:
    """
    Generate Phase 2 vendor-specific queries using Phase 1 intelligence.

    VENDOR-FIRST STRATEGY:
    1. If Phase 1 found recommended vendors: "{vendor_name} {topic} for sale {year}"
    2. Fallback if no vendors: "{topic} for sale {year}"

    This ensures Phase 2 searches for specific vendors that were recommended
    in forum discussions (Phase 1) rather than generic searches.

    Args:
        user_query: Original user query (e.g., "Find Syrian hamsters for sale")
        intelligence: Phase 1 intelligence containing:
            - recommended_vendors: [{name, reason, url}, ...]
            - credible_sources: [vendor_name, ...]
            - retailers_mentioned: [retailer, ...]
        mode: "standard" (up to 3 vendors) or "deep" (up to 5 vendors)
        solver_url: URL of the LLM solver service
        solver_model_id: Model ID to use
        solver_api_key: API key for authentication

    Returns:
        List of Phase 2 queries:
        - With vendors: ["{vendor1} {topic} for sale {year}", "{vendor2} {topic}...", ...]
        - Without vendors: ["{topic} for sale {year}"]
    """
    import os
    from datetime import datetime

    # Use env vars as defaults
    solver_url = solver_url or os.environ.get("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    solver_model_id = solver_model_id or os.environ.get("SOLVER_MODEL_ID", "qwen3-coder")
    solver_api_key = solver_api_key or os.environ.get("SOLVER_API_KEY", "qwen-local")

    intelligence = intelligence or {}
    logger.info(f"[QueryPlanner] Phase 2 query for: '{user_query}' with intelligence keys: {list(intelligence.keys())}")

    # Get current year for recency filtering
    current_year = datetime.now().year

    # ===== STEP 1: Extract topic keywords =====
    # Load prompt from recipe file (reuses same extractor as Phase 1)
    base_prompt = _load_query_prompt("topic_keyword_extractor")
    if not base_prompt:
        base_prompt = """Extract the core topic/product keywords from a user query. Remove all conversational filler.

Rules:
- Output 2-5 words (the core topic only)
- Remove: "find me", "can you", "help me", "for sale", "buy", "please"
- KEEP price constraints (user requirements): "cheapest", "budget", "under $X", "affordable"
- Keep: product names, brands, specifications, constraints
- Output ONLY the topic keywords, nothing else

Examples:
"what's the cheapest laptop with nvidia gpu" → "cheapest laptop nvidia gpu"
"find me a budget gaming monitor under $300" → "budget gaming monitor under $300"
"can you help me find Syrian hamsters for sale" → "Syrian hamsters\""""

    # Build full prompt with dynamic data
    prompt = f"""{base_prompt}

## Current Query
Query: {user_query}

Topic:"""

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                solver_url,
                headers={
                    "Authorization": f"Bearer {solver_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": solver_model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 30,
                    "top_p": 0.8,
                    "stop": ["<|im_end|>", "<|endoftext|>"],
                    "repetition_penalty": 1.05
                }
            )
            response.raise_for_status()
            result = response.json()
            topic = result["choices"][0]["message"]["content"].strip()

            # Clean up the response - remove any formatting LLM might add
            topic = topic.strip('"').strip("'").strip('`').strip()
            # Remove markdown code blocks if present
            if topic.startswith("```"):
                topic = topic.split("```")[1] if "```" in topic[3:] else topic[3:]
            topic = topic.strip('`').strip()
            # Remove newlines - take only first line
            if '\n' in topic:
                topic = topic.split('\n')[0].strip()

            # Validation: reject if LLM returned conversational response
            if len(topic.split()) > 8 or "I'll" in topic or "help you" in topic or "Here" in topic:
                logger.warning(f"[QueryPlanner] LLM returned invalid topic: '{topic[:50]}...', using fallback")
                topic = _extract_keywords_fallback(user_query)

    except Exception as e:
        logger.error(f"[QueryPlanner] Topic extraction failed: {e}", exc_info=True)
        topic = _extract_keywords_fallback(user_query)

    # ===== STEP 2: Extract vendor names from Phase 1 intelligence =====
    vendor_names = []

    # Source 1: recommended_vendors (structured data from forum extraction)
    recommended = intelligence.get("recommended_vendors", [])
    for vendor in recommended:
        if isinstance(vendor, dict):
            name = vendor.get("name", "").strip()
            if name and len(name) > 2:
                vendor_names.append(name)
        elif isinstance(vendor, str) and len(vendor.strip()) > 2:
            vendor_names.append(vendor.strip())

    # Source 2: credible_sources (often contains vendor names)
    credible = intelligence.get("credible_sources", [])
    for source in credible:
        if isinstance(source, str) and len(source.strip()) > 2:
            # Avoid duplicates
            source_clean = source.strip()
            if source_clean not in vendor_names:
                vendor_names.append(source_clean)

    # Source 3: retailers_mentioned (from guides/forums)
    retailers = intelligence.get("retailers_mentioned", [])
    for retailer in retailers:
        if isinstance(retailer, str) and len(retailer.strip()) > 2:
            retailer_clean = retailer.strip()
            if retailer_clean not in vendor_names:
                vendor_names.append(retailer_clean)

    # Deduplicate and limit based on mode
    seen = set()
    unique_vendors = []
    for v in vendor_names:
        v_lower = v.lower()
        if v_lower not in seen:
            seen.add(v_lower)
            unique_vendors.append(v)

    max_vendors = 5 if mode == "deep" else 3
    vendor_names = unique_vendors[:max_vendors]

    logger.info(f"[QueryPlanner] Phase 2 found {len(vendor_names)} vendors from intelligence: {vendor_names}")

    # ===== STEP 3: Generate queries =====
    queries = []

    if vendor_names:
        # VENDOR-SPECIFIC QUERIES: "{vendor} {topic} {year}"
        for vendor in vendor_names:
            query = f"{vendor} {topic} {current_year}"
            queries.append(query)
            logger.info(f"[QueryPlanner] Phase 2 vendor query: '{query}'")
    else:
        # FALLBACK: Generic query when no vendors found
        query = f"{topic} for sale {current_year}"
        queries.append(query)
        logger.info(f"[QueryPlanner] Phase 2 fallback (no vendors): '{query}'")

    return queries


async def optimize_query_for_phase(
    user_query: str,
    phase: str,
    context: Dict[str, Any] = None
) -> str:
    """
    Optimize search query based on research phase.

    PATTERNS:
    - Phase 1 (intelligence): LLM generates query with appropriate source type
    - Phase 2 (shopping):     {vendor} {topic} for sale {year} (if vendors available)
                              or {topic} for sale {year} (fallback)

    Args:
        user_query: Original user query
        phase: "intelligence" or "shopping"
        context: Additional context including:
            - intent, intent_metadata: For navigation bypass
            - intelligence: Phase 1 intelligence with vendor recommendations

    Returns:
        Optimized query string

    Examples:
        Phase 1: "best egg nog recipe" → "egg nog recipe"
        Phase 1: "find cheap laptops with nvidia gpu" → "laptops nvidia gpu reddit"
        Phase 2 (with vendors): "find Syrian hamsters" → "Poppybee Hamstery Syrian hamsters for sale 2025"
        Phase 2 (no vendors): "find Syrian hamsters" → "Syrian hamsters for sale 2025"
    """
    import os

    context = context or {}

    # Get current year for queries
    current_year = datetime.now().year

    if phase == "intelligence":
        # Use plan_phase1_queries - LLM generates full query with appropriate source type
        intent = context.get("intent", "informational")
        intent_metadata = context.get("intent_metadata", {})
        queries = await plan_phase1_queries(
            user_query=user_query,
            intent=intent,
            intent_metadata=intent_metadata
        )
        # Return first query (or fallback)
        optimized = queries[0] if queries else f"{_extract_keywords_fallback(user_query)} {current_year}"
        return optimized

    elif phase == "shopping":
        # Use plan_phase2_queries with intelligence for vendor-specific queries
        intelligence = context.get("intelligence", {})
        queries = await plan_phase2_queries(
            user_query=user_query,
            intelligence=intelligence
        )
        # Return first query (or fallback)
        optimized = queries[0] if queries else f"{_extract_keywords_fallback(user_query)} for sale {current_year}"
        return optimized

    else:
        logger.warning(f"[QueryPlanner] Unknown phase: {phase}, returning original query")
        return user_query


# NOTE: construct_retailer_search_url removed - use construct_vendor_search_url instead
# It's a sync function that does the same thing with more features (price filtering)
