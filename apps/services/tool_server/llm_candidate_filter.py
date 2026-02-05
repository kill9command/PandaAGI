"""
apps/services/tool_server/llm_candidate_filter.py

LLM-powered intelligent candidate filtering.
Uses LLM to evaluate search results for relevance before visiting.
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

import httpx

from apps.services.tool_server.source_quality_scorer import get_source_quality_scorer


logger = logging.getLogger(__name__)

# Recipe-based prompt loading
_candidate_filter_prompt: Optional[str] = None
_vendor_validator_prompt: Optional[str] = None


def _load_candidate_filter_prompt() -> str:
    """Load the candidate filter prompt from recipe system."""
    global _candidate_filter_prompt
    if _candidate_filter_prompt is None:
        try:
            from libs.gateway.llm.recipe_loader import load_recipe
            recipe = load_recipe("tools/candidate_filter")
            _candidate_filter_prompt = recipe.get_prompt()
            logger.info("[CandidateFilter] Loaded prompt from recipe system")
        except Exception as e:
            logger.warning(f"[CandidateFilter] Recipe load failed: {e}, using fallback")
            _candidate_filter_prompt = "Select the best sources from search results. Return JSON with sources and skipped."
    return _candidate_filter_prompt


def _load_vendor_validator_prompt() -> str:
    """Load the vendor validator prompt from recipe system."""
    global _vendor_validator_prompt
    if _vendor_validator_prompt is None:
        try:
            from libs.gateway.llm.recipe_loader import load_recipe
            recipe = load_recipe("tools/vendor_validator")
            _vendor_validator_prompt = recipe.get_prompt()
            logger.info("[VendorValidator] Loaded prompt from recipe system")
        except Exception as e:
            logger.warning(f"[VendorValidator] Recipe load failed: {e}, using fallback")
            _vendor_validator_prompt = "Validate vendors for the user's goal. Return JSON with approved and rejected."
    return _vendor_validator_prompt


def _repair_json(text: str) -> str:
    """
    Attempt to repair common LLM JSON errors.

    Common issues:
    - Trailing commas before ] or }
    - Missing commas between elements
    - Unescaped newlines in strings
    """
    # Remove trailing commas before ] or }
    text = re.sub(r',(\s*[}\]])', r'\1', text)

    # Fix missing commas between } and { (common in arrays of objects)
    text = re.sub(r'\}(\s*)\{', r'},\1{', text)

    # Fix missing commas between " and { (string followed by object)
    text = re.sub(r'"(\s*)\{', r'",\1{', text)

    # Fix missing commas between } and "
    text = re.sub(r'\}(\s*)"', r'},\1"', text)

    # Fix missing commas between ] and "
    text = re.sub(r'\](\s*)"', r'],\1"', text)

    # Fix missing commas between numbers/booleans and next key
    text = re.sub(r'(\d)(\s*)"(\w+)":', r'\1,\2"\3":', text)
    text = re.sub(r'(true|false|null)(\s*)"(\w+)":', r'\1,\2"\3":', text)

    return text


async def llm_filter_candidates(
    candidates: List[Dict[str, Any]],
    query: str,
    research_goal: str,
    max_candidates: int = 10,
    model_url: Optional[str] = None,
    model_id: Optional[str] = None,
    api_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Use LLM-based SourceQualityScorer to filter search candidates.

    Args:
        candidates: List of search results with url, title, snippet
        query: Original search query
        research_goal: What the research is trying to accomplish
        max_candidates: Max candidates to keep
        model_url: LLM API endpoint (defaults to env SOLVER_URL)
        model_id: Model identifier (defaults to env SOLVER_MODEL_ID)
        api_key: API key (defaults to env SOLVER_API_KEY)

    Returns:
        Filtered list of candidates with llm_reasoning added
    """
    if os.getenv("SOURCE_QUALITY_ENABLE", "true").lower() != "true":
        return candidates[:max_candidates] if max_candidates else candidates

    scorer = get_source_quality_scorer()
    goal = (
        f"Phase 2 product search. {research_goal or 'Find pages where users can buy the product.'} "
        "Prefer vendor product listings; avoid reviews, forums, and purely informational pages."
    )

    try:
        scored = await scorer.score_candidates(
            candidates=candidates,
            query=query,
            goal=goal,
            model_url=model_url,
            model_id=model_id,
            api_key=api_key,
        )
    except Exception as e:
        logger.error(f"[LLM-Filter] SourceQualityScorer failed: {e}")
        return candidates[:max_candidates] if max_candidates else candidates

    if not scored:
        return candidates[:max_candidates] if max_candidates else candidates

    scored.sort(key=lambda c: c.get("quality_score", 0.0), reverse=True)

    min_quality = 0.5
    filtered_candidates = [c for c in scored if c.get("quality_score", 0.0) >= min_quality]
    if len(filtered_candidates) < max_candidates:
        filtered_candidates = scored[:max_candidates]
    else:
        filtered_candidates = filtered_candidates[:max_candidates]

    for candidate in filtered_candidates:
        candidate["llm_reasoning"] = candidate.get("quality_reasoning", "Approved by scorer")

    logger.info(
        f"[LLM-Filter] Kept {len(filtered_candidates)}/{len(candidates)} candidates "
        f"(min_quality={min_quality:.2f})"
    )

    return filtered_candidates


async def filter_candidates_for_intelligence(
    candidates: List[Dict[str, Any]],
    query: str,
    max_candidates: int = 3,
    intent: str = None,
    key_requirements: List[str] = None
) -> List[Dict[str, Any]]:
    """
    Filter URLs for Phase 1 intelligence gathering using SourceQualityScorer.

    Prioritizes: Forums, Reddit, review sites
    Skips: Ads, sponsored results, social media (except Reddit), retailers

    Args:
        candidates: List of search results with url, title, snippet
        query: Original search query
        max_candidates: Max candidates to keep (default: 3)
        intent: Query intent (e.g., "budget", "premium", "comparison")
        key_requirements: Key product requirements from query (e.g., ["NVIDIA GPU", "laptop"])

    Returns:
        Filtered and prioritized list of candidates
    """
    if os.getenv("SOURCE_QUALITY_ENABLE", "true").lower() != "true":
        return candidates[:max_candidates]

    scorer = get_source_quality_scorer()
    goal = (
        "Phase 1 intelligence gathering. Prefer forums, expert reviews, and official guides. "
        "Avoid vendor product listings and purely transactional pages."
    )

    try:
        scored = await scorer.score_candidates(
            candidates=candidates,
            query=query,
            goal=goal,
            key_requirements=key_requirements,
        )
    except Exception as e:
        logger.warning(f"[IntelFilter] SourceQualityScorer failed: {e}")
        return candidates[:max_candidates]

    if not scored:
        return candidates[:max_candidates]

    scored.sort(key=lambda c: c.get("quality_score", 0.0), reverse=True)

    min_quality = 0.3
    filtered_candidates = [c for c in scored if c.get("quality_score", 0.0) >= min_quality]
    if len(filtered_candidates) < max_candidates:
        filtered_candidates = scored[:max_candidates]
    else:
        filtered_candidates = filtered_candidates[:max_candidates]

    logger.info(
        f"[IntelFilter] Kept {len(filtered_candidates)}/{len(candidates)} candidates "
        f"(min_quality={min_quality:.2f})"
    )

    return filtered_candidates


# ==================== VENDOR SELECTION FOR INTELLIGENT SEARCH ====================

# Recipe and prompt cache (loaded once)
_vendor_selector_recipe = None


def _load_vendor_selector_recipe():
    """Lazy-load vendor_selector recipe."""
    global _vendor_selector_recipe
    if _vendor_selector_recipe is None:
        try:
            from libs.gateway.llm.recipe_loader import load_recipe
            _vendor_selector_recipe = load_recipe("vendor_selector")
            logger.info("[VendorSelect] Loaded vendor_selector recipe")
        except Exception as e:
            logger.warning(f"[VendorSelect] Failed to load recipe: {e}, using defaults")
            _vendor_selector_recipe = {"token_budget": {"output": 400}}
    return _vendor_selector_recipe


async def select_vendor_candidates(
    search_results: List[Dict[str, Any]],
    query: str,
    intelligence: Dict[str, Any] = None,
    max_vendors: int = 4,
    original_query: str = None
) -> List[Dict[str, Any]]:
    """
    Select best sources from Google search results.

    CONTEXT DISCIPLINE: Requires original_query so the LLM can interpret
    user priorities (cheapest, best, fastest, etc.) directly from the text.
    See: panda_system_docs/architecture/LLM-ROLES/CONTEXT_DISCIPLINE.md

    Args:
        search_results: List of search results with url, title, snippet
        query: Optimized search query (may have intent words removed for Google)
        intelligence: Phase 1 intelligence (optional, for context)
        max_vendors: Maximum sources to select
        original_query: Original user query with priority signals (REQUIRED for good results)

    Returns:
        List of source candidates with url, domain, source_type, reasoning
    """
    if not search_results:
        logger.warning("[VendorSelect] No search results to process")
        return []

    # Load recipe (cached)
    recipe = _load_vendor_selector_recipe()
    max_tokens = recipe.get("token_budget", {}).get("output", 800) if isinstance(recipe, dict) else 800
    if hasattr(recipe, 'token_budget') and recipe.token_budget:
        max_tokens = recipe.token_budget.output

    # Get model config from env
    model_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    model_id = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
    api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    # Build search results text for prompt
    results_text = []
    for i, r in enumerate(search_results[:15], 1):  # Limit to 15 for token efficiency
        results_text.append(
            f"{i}. URL: {r.get('url', 'N/A')}\n"
            f"   Title: {r.get('title', 'N/A')}\n"
            f"   Snippet: {r.get('snippet', 'N/A')[:150]}"
        )

    # Build intelligence context if available
    intel_context = ""
    if intelligence:
        requirements = intelligence.get("key_requirements", [])
        if requirements:
            intel_context = f"\n\nUser Requirements (from research): {', '.join(requirements[:5])}"

        # Add rich retailer intelligence if available
        retailers = intelligence.get("retailers", {})
        if retailers:
            retailer_lines = []
            for name, info in retailers.items():
                if isinstance(info, dict):
                    score = info.get("relevance_score", 0.5)
                    reasons = info.get("mentioned_for", [])
                    include = info.get("include_in_search", True)
                    if include and score >= 0.5:
                        reason_str = ", ".join(reasons[:3]) if reasons else "general"
                        retailer_lines.append(f"  - {name}: score={score:.2f}, reasons: {reason_str}")
            if retailer_lines:
                intel_context += f"\n\nRETAILER INTELLIGENCE (from Phase 1 research):\n" + "\n".join(retailer_lines)
                intel_context += "\n\n→ PRIORITIZE retailers from this list if they appear in search results!"

    # Add LEARNED vendor quality from past extractions (from vendor registry)
    try:
        from apps.services.tool_server.shared_state.vendor_registry import VendorRegistry
        registry = VendorRegistry()

        # Get domains from search results
        search_domains = set()
        for r in search_results:
            url = r.get('url', '')
            if url:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.lower().replace('www.', '')
                if domain:
                    search_domains.add(domain)

        # Build quality hints from learned experience
        quality_lines = []
        for domain in search_domains:
            vendor = registry.get_vendor(domain)
            if vendor and vendor.total_visits >= 3:  # Only include if we have enough data
                success_rate = vendor.successful_extractions / vendor.total_visits if vendor.total_visits > 0 else 0
                if success_rate >= 0.7:
                    quality_lines.append(f"  - {domain}: HIGH quality (success rate {success_rate:.0%} over {vendor.total_visits} visits)")
                elif success_rate >= 0.4:
                    quality_lines.append(f"  - {domain}: MEDIUM quality (success rate {success_rate:.0%})")
                elif success_rate < 0.3 and vendor.total_visits >= 5:
                    quality_lines.append(f"  - {domain}: LOW quality (often fails extraction)")

        if quality_lines:
            intel_context += f"\n\nLEARNED VENDOR QUALITY (from past extractions):\n" + "\n".join(quality_lines)
            intel_context += "\n\n→ Consider vendor quality when selecting sources."

    except Exception as e:
        logger.debug(f"[SourceSelect] Could not load vendor quality: {e}")

    # CONTEXT DISCIPLINE: Pass original query so LLM can interpret user priorities
    user_query_for_prompt = original_query or query

    if original_query:
        logger.info(f"[SourceSelect] Using original query for context: '{original_query[:60]}...'")
    else:
        logger.warning(f"[SourceSelect] No original_query - LLM may miss user priority signals")

    # Load base prompt from file
    base_prompt = _load_candidate_filter_prompt()

    # Build prompt - LLM interprets user priorities directly from original query
    prompt = f"""{base_prompt}

---

## Current Task

### User's Original Request

{user_query_for_prompt}

### Search Query Used

{query}

### Search Results ({len(search_results)} total)

{chr(10).join(results_text)}

### Additional Context
{intel_context if intel_context else "None available."}

### Selection Target

Select the TOP {max_vendors} sources from the search results."""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                model_url,
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": max_tokens
                },
                headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            result = response.json()

        # Parse LLM response
        llm_content = result["choices"][0]["message"]["content"].strip()
        if "```json" in llm_content:
            llm_content = llm_content.split("```json")[1].split("```")[0].strip()
        elif "```" in llm_content:
            llm_content = llm_content.split("```")[1].split("```")[0].strip()

        # Try to parse, with repair on failure
        try:
            selection = json.loads(llm_content)
        except json.JSONDecodeError as first_error:
            # Try to repair common LLM JSON errors
            logger.warning(f"[SourceSelect] JSON parse failed, attempting repair: {first_error}")
            repaired = _repair_json(llm_content)
            try:
                selection = json.loads(repaired)
                logger.info("[SourceSelect] JSON repair successful")
            except json.JSONDecodeError:
                # Log first 500 chars of response for debugging
                logger.error(f"[SourceSelect] JSON repair failed. Response preview: {llm_content[:500]}...")
                raise first_error  # Re-raise original error for outer handler
        # Handle both old "vendors" and new "sources" schema
        sources_selected = selection.get("sources", selection.get("vendors", []))
        summary = selection.get("summary", "")
        user_intent = selection.get("user_intent", selection.get("intent_detected", ""))

        logger.info(f"[SourceSelect] Intent: {user_intent}")
        logger.info(f"[SourceSelect] {summary}")

        # Build final source list with full URLs
        source_candidates = []
        seen_domains = set()

        for rank, source in enumerate(sources_selected[:max_vendors], 1):
            idx = source.get("index", 0)
            if 1 <= idx <= len(search_results):
                original = search_results[idx - 1]
                actual_url = original.get("url", "")
                actual_domain = _extract_domain(actual_url)
                llm_domain = source.get("domain", "")

                # CRITICAL: Skip when LLM's claimed domain doesn't match actual URL
                # This catches deceptive search results (e.g., title says "Costco" but URL is compare.deals)
                if llm_domain and llm_domain != actual_domain:
                    logger.warning(
                        f"[SourceSelect] SKIPPING - LLM claimed domain '{llm_domain}' for index {idx}, "
                        f"but actual URL is from '{actual_domain}' ({actual_url[:60]}...). "
                        f"This is likely a misleading search result."
                    )
                    continue  # Skip this candidate entirely

                # Always use the actual domain from the URL
                domain = actual_domain

                # Skip duplicate domains
                if domain in seen_domains:
                    logger.info(f"[SourceSelect] Skipping duplicate domain: {domain}")
                    continue
                seen_domains.add(domain)

                source_candidates.append({
                    "url": original.get("url"),
                    "domain": domain,
                    "title": original.get("title", ""),
                    "snippet": original.get("snippet", ""),
                    "rank": rank,
                    "source_type": source.get("source_type", source.get("vendor_type", "unknown")),
                    "reasoning": source.get("reasoning", "Selected by LLM")
                })

                logger.info(
                    f"[SourceSelect] #{rank}: {domain} ({source.get('source_type', source.get('vendor_type'))}) - "
                    f"{source.get('reasoning', '')[:50]}"
                )

        # Log skipped
        for skipped in selection.get("skipped", [])[:5]:
            idx = skipped.get("index", 0)
            if 1 <= idx <= len(search_results):
                logger.debug(
                    f"[SourceSelect] Skipped #{idx}: {search_results[idx-1].get('title', '')[:40]} - "
                    f"{skipped.get('reason', 'N/A')}"
                )

        # Trust LLM's ranking - it has the user's intent context
        # Only add URL quality score for observability, don't re-rank
        for candidate in source_candidates:
            candidate["url_quality"] = score_vendor_url_quality(candidate.get("url", ""), query)

        # VENDOR DIVERSITY ENFORCEMENT: Backfill if we have fewer than 3 unique vendors
        min_vendors = 3
        if len(source_candidates) < min_vendors:
            logger.warning(
                f"[SourceSelect] Only {len(source_candidates)} unique vendors found, "
                f"backfilling to reach {min_vendors} minimum"
            )
            # Find additional vendors from search results that weren't selected
            for result in search_results:
                if len(source_candidates) >= min_vendors:
                    break
                url = result.get("url", "")
                domain = _extract_domain(url)
                if domain and domain not in seen_domains:
                    # Quick heuristic check - skip obvious non-transactional sites
                    skip_patterns = ["youtube", "reddit", "wikipedia", "quora", "facebook", "twitter"]
                    if any(p in domain.lower() for p in skip_patterns):
                        continue
                    seen_domains.add(domain)
                    source_candidates.append({
                        "url": url,
                        "domain": domain,
                        "title": result.get("title", ""),
                        "snippet": result.get("snippet", ""),
                        "rank": len(source_candidates) + 1,
                        "source_type": "backfill",
                        "reasoning": "Added to meet minimum vendor diversity requirement"
                    })
                    logger.info(f"[SourceSelect] Backfill vendor: {domain}")

        return source_candidates

    except json.JSONDecodeError as e:
        logger.error(f"[VendorSelect] Failed to parse LLM response: {e}")
        # Fallback: Use heuristic selection
        return _heuristic_vendor_selection(search_results, max_vendors)

    except Exception as e:
        logger.error(f"[VendorSelect] LLM vendor selection failed: {e}")
        # Fallback: Use heuristic selection
        return _heuristic_vendor_selection(search_results, max_vendors)


def _extract_domain(url: str) -> str:
    """Extract domain from URL, normalized (strips www. prefix)."""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Normalize: strip www. prefix for consistent matching
        # "www.bestbuy.com" and "bestbuy.com" should be treated as same domain
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return "unknown"


def _heuristic_vendor_selection(
    search_results: List[Dict[str, Any]],
    max_vendors: int = 4
) -> List[Dict[str, Any]]:
    """
    Fallback heuristic vendor selection when LLM fails.
    Uses domain patterns to identify likely vendors.
    """
    logger.info("[VendorSelect] Using heuristic fallback selection")

    vendor_candidates = []
    seen_domains = set()

    for i, result in enumerate(search_results):
        if len(vendor_candidates) >= max_vendors:
            break

        url = result.get("url", "")
        domain = _extract_domain(url)

        # Skip if already seen
        if domain in seen_domains:
            continue

        combined_text = f"{result.get('title', '')} {result.get('snippet', '')}".lower()
        skip_terms = [
            "forum", "thread", "discussion", "review", "guide", "news", "blog", "wiki",
            "video", "watch", "tutorial",
        ]
        if any(term in combined_text for term in skip_terms):
            continue

        url_quality = score_vendor_url_quality(url, "")
        if url_quality < 0.3:
            continue

        seen_domains.add(domain)
        vendor_candidates.append({
            "url": url,
            "domain": domain,
            "title": result.get("title", ""),
            "snippet": result.get("snippet", ""),
            "rank": len(vendor_candidates) + 1,
            "vendor_type": "unknown",
            "url_quality": round(url_quality, 3),
            "reasoning": "Heuristic selection (non-LLM fallback)"
        })
        logger.info(f"[VendorSelect] Heuristic #{len(vendor_candidates)}: {domain} (url_quality={url_quality:.2f})")

    vendor_candidates.sort(key=lambda c: c.get("url_quality", 0.0), reverse=True)
    return vendor_candidates[:max_vendors]


def score_vendor_url_quality(url: str, query: str) -> float:
    """
    Score URL quality for product search (0.0-1.0).
    Higher = more likely to have actual product listings.

    Args:
        url: The vendor URL to score
        query: The search query for context

    Returns:
        Quality score between 0.0 and 1.0
    """
    from urllib.parse import urlparse

    score = 0.5  # Base score
    url_lower = url.lower()
    parsed = urlparse(url)
    path = parsed.path.lower()
    query_params = parsed.query.lower()

    # POSITIVE signals (product listing pages)
    positive_patterns = [
        (r'[?&](q|query|search|k|st|d)=', 0.3),   # Has search query param
        (r'/search', 0.2),                       # Search page
        (r'filter|facet|qp=', 0.15),             # Has filters applied
        (r'/product', 0.1),                      # Product in path
        (r'/shop', 0.1),                         # Shop page
        (r'/store', 0.1),                        # Store page
    ]

    # NEGATIVE signals (category/overview pages)
    negative_patterns = [
        (r'/category/', -0.2),
        (r'/browse/', -0.15),
        (r'/about', -0.3),
        (r'/help', -0.3),
        (r'/contact', -0.3),
        (r'/blog/', -0.25),
        (r'/news/', -0.25),
        (r'/forum', -0.3),
        (r'/wiki', -0.25),
    ]

    for pattern, delta in positive_patterns + negative_patterns:
        if re.search(pattern, url_lower):
            score += delta

    # Query term presence in URL (indicates targeted search)
    query_terms = [t for t in query.lower().split() if len(t) > 2]
    terms_in_url = sum(1 for t in query_terms if t in url_lower)
    score += min(0.2, terms_in_url * 0.05)

    # Bonus for generic query indicators
    if any(x in url_lower for x in ['?k=', '?q=', '?st=', '?d=']):
        score += 0.1

    return max(0.0, min(1.0, score))


# ==================== GOAL-AWARE VENDOR VALIDATION ====================

async def validate_vendors_for_goal(
    vendors: List[Dict[str, Any]],
    goal: str,
    model_url: Optional[str] = None,
    model_id: Optional[str] = None,
    api_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Validate whether vendors are appropriate for the user's goal.

    This is the key function for intelligent vendor selection when using
    intelligence fallback. It prevents visiting pet supply stores when
    looking for live animals, or accessory shops when looking for the main product.

    Args:
        vendors: List of vendor candidates with domain, name, etc.
        goal: User's goal/query (what they're trying to find)
        model_url: LLM API endpoint (defaults to env SOLVER_URL)
        model_id: Model identifier (defaults to env SOLVER_MODEL_ID)
        api_key: API key (defaults to env SOLVER_API_KEY)

    Returns:
        Filtered list of vendors that are likely to have what user wants
    """
    if not vendors:
        return []

    # Get model config from env if not provided
    if not model_url:
        model_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    if not model_id:
        model_id = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
    if not api_key:
        api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    # Build vendor list for prompt
    vendor_lines = []
    for i, v in enumerate(vendors, 1):
        domain = v.get("domain", v.get("name", "unknown"))
        source = v.get("_source", "intelligence")
        vendor_lines.append(f"{i}. {domain} (source: {source})")

    # Load base prompt from file
    base_prompt = _load_vendor_validator_prompt()

    prompt = f"""{base_prompt}

---

## Current Task

**USER'S GOAL:** {goal}

**CANDIDATE VENDORS (from research intelligence):**
{chr(10).join(vendor_lines)}

For each vendor, determine if they are LIKELY to have what the user wants."""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                model_url,
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 800
                },
                headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            result = response.json()

        # Parse LLM response
        llm_content = result["choices"][0]["message"]["content"].strip()
        if "```json" in llm_content:
            llm_content = llm_content.split("```json")[1].split("```")[0].strip()
        elif "```" in llm_content:
            llm_content = llm_content.split("```")[1].split("```")[0].strip()

        # Parse with repair fallback
        try:
            validation_result = json.loads(llm_content)
        except json.JSONDecodeError:
            validation_result = json.loads(_repair_json(llm_content))
        approved_list = validation_result.get("approved", [])
        rejected_list = validation_result.get("rejected", [])
        summary = validation_result.get("summary", "")

        logger.info(f"[VendorValidate] {summary}")

        # Build approved vendor indices
        approved_indices = {item.get("index") for item in approved_list}

        # Filter vendors
        validated_vendors = []
        for i, vendor in enumerate(vendors, 1):
            if i in approved_indices:
                # Find the approval reason
                approval = next((a for a in approved_list if a.get("index") == i), {})
                vendor["validation_reason"] = approval.get("reason", "Approved by LLM")
                validated_vendors.append(vendor)
                logger.info(f"[VendorValidate] APPROVED: {vendor.get('domain', 'unknown')} - {vendor.get('validation_reason')}")
            else:
                # Find the rejection reason
                rejection = next((r for r in rejected_list if r.get("index") == i), {})
                reason = rejection.get("reason", "Rejected by LLM")
                logger.info(f"[VendorValidate] REJECTED: {vendor.get('domain', 'unknown')} - {reason}")

        logger.info(f"[VendorValidate] Validated {len(validated_vendors)}/{len(vendors)} vendors for goal: {goal[:50]}")
        return validated_vendors

    except json.JSONDecodeError as e:
        logger.error(f"[VendorValidate] Failed to parse LLM response: {e}")
        # Fallback: return all vendors (don't block on LLM failure)
        return vendors

    except Exception as e:
        logger.error(f"[VendorValidate] Error during validation: {e}")
        # Fallback: return all vendors (don't block on LLM failure)
        return vendors


# Quick test
if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)

    async def test():
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
                'url': 'https://www.petfinder.com/small-furry/syrian-hamster',
                'title': 'Syrian Hamsters for Adoption - Petfinder',
                'snippet': 'Find Syrian hamsters for adoption near you. Browse listings from shelters and rescues.'
            },
            {
                'url': 'https://furballcritters.com/syrian-hamsters',
                'title': 'Syrian Hamsters - Furball Critters',
                'snippet': 'Healthy Syrian hamsters for sale. $35. Ethical breeding practices.'
            }
        ]

        print("\n" + "=" * 80)
        print("LLM CANDIDATE FILTER TEST")
        print("=" * 80 + "\n")

        filtered = await llm_filter_candidates(
            test_candidates,
            query="find Syrian hamster for sale",
            research_goal="Find reputable sellers and breeders of Syrian hamsters with pricing",
            max_candidates=10
        )

        print(f"\n\nFINAL RESULTS: {len(filtered)}/{len(test_candidates)} candidates kept")
        for i, c in enumerate(filtered, 1):
            print(f"{i}. {c['title']}")
            print(f"   {c['url']}")
            print(f"   Reason: {c.get('llm_reasoning', 'N/A')}")
            print()

    asyncio.run(test())
