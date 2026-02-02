"""
orchestrator/commerce_mcp.py

DEPRECATED (2025-11-29): Migrate to apps/tools/internet_research.

This module provides legacy commerce endpoints. New code should use:
    from apps.tools.internet_research import execute_full_research

Migration:
    OLD: search_with_recommendations(query)
    NEW: await execute_full_research(goal=query, intent="commerce")

Note: search_with_recommendations() has been updated to use the new API
internally for backward compatibility. Other functions in this file
may still use legacy code.

Deprecated: 2025-11-29
Updated: 2026-01-27 - search_with_recommendations now uses new API
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from apps.services.orchestrator.product_schema import (
    ProductSearchIntent,
    ProductListing,
    SearchQuality,
    infer_item_type,
    infer_category,
)
from apps.services.orchestrator.web_fetcher_resilient import fetch_url
from apps.services.orchestrator.data_normalizer import get_normalizer
from apps.services.orchestrator.memory_store import get_memory_store
# from apps.services.orchestrator import serpapi_mcp  # DEPRECATED - using human_search_engine instead
from apps.services.orchestrator.species_taxonomy import validate_species_match
import httpx
import json
import re
from typing import Dict as TypingDict

logger = logging.getLogger(__name__)

# Prompt cache for recipe-loaded prompts
_prompt_cache: TypingDict[str, str] = {}


def _load_prompt_via_recipe(recipe_name: str, category: str = "tools") -> str:
    """Load prompt via recipe system with inline fallback."""
    cache_key = f"{category}/{recipe_name}"
    if cache_key in _prompt_cache:
        return _prompt_cache[cache_key]
    try:
        from libs.gateway.recipe_loader import load_recipe
        recipe = load_recipe(f"{category}/{recipe_name}")
        content = recipe.get_prompt()
        _prompt_cache[cache_key] = content
        return content
    except Exception as e:
        logger.warning(f"Recipe {cache_key} not found: {e}")
        return ""


def verify_vendor_quality(offer: Dict[str, Any], item_type: str = "unknown") -> Dict[str, Any]:
    """
    Add vendor quality indicators to offer (NEW: 2025-11-13).

    Checks for:
    - Price reasonableness (flag suspiciously low prices)
    - Seller information completeness
    - Health guarantees (for live animals)
    - Review/rating presence

    Args:
        offer: Offer dict with title, description, price, etc.
        item_type: Type of item (live_animal, accessory, etc.)

    Returns:
        Updated offer with vendor_quality_score and vendor_flags
    """
    title = offer.get("title", "").lower()
    description = offer.get("description", "").lower()
    price = offer.get("price") or 0  # Handle None explicitly
    source = offer.get("source", "").lower()

    quality_score = 1.0  # Start at perfect
    flags = []

    # 1. Price reasonableness check (for live animals)
    if item_type == "live_animal" and price > 0:
        # Typical hamster prices: $15-50, hedgehogs: $200-400
        if "hamster" in title and price < 10:
            quality_score *= 0.5
            flags.append("suspiciously_low_price")
            logger.warning(f"[VendorVerify] Suspiciously low price for hamster: ${price} ({title[:50]})")
        elif "hedgehog" in title and price < 100:
            quality_score *= 0.6
            flags.append("suspiciously_low_price")
        elif price > 1000:
            quality_score *= 0.7
            flags.append("suspiciously_high_price")

    # 2. Seller information completeness
    has_seller_name = bool(offer.get("seller") or offer.get("source"))
    has_location = "location" in offer or any(
        word in description for word in ["phone", "email", "contact", "address"]
    )

    if not has_seller_name:
        quality_score *= 0.8
        flags.append("no_seller_info")

    if not has_location and item_type == "live_animal":
        quality_score *= 0.85
        flags.append("no_contact_info")

    # 3. Health guarantees (for live animals)
    if item_type == "live_animal":
        has_health_guarantee = any(
            phrase in description or phrase in title
            for phrase in [
                "health guarantee", "health cert", "veterinarian", "vet check",
                "health checked", "health certificate", "guaranteed healthy"
            ]
        )

        if has_health_guarantee:
            quality_score *= 1.1  # Boost score
            flags.append("has_health_guarantee")
            logger.info(f"[VendorVerify] Health guarantee found: {title[:50]}")
        else:
            quality_score *= 0.9  # Minor penalty
            flags.append("no_health_guarantee")

    # 4. Review/rating indicators
    has_reviews = any(
        word in description or word in title
        for word in ["rating", "review", "star", "feedback", "testimonial"]
    )

    if has_reviews:
        flags.append("has_reviews")
        quality_score *= 1.05  # Small boost

    # 5. Red flags
    red_flags = [
        "no refund", "no returns", "as is", "no warranty",
        "cash only", "wire transfer only", "untraceable payment"
    ]

    for red_flag in red_flags:
        if red_flag in description:
            quality_score *= 0.7
            flags.append(f"red_flag:{red_flag.replace(' ', '_')}")
            logger.warning(f"[VendorVerify] Red flag found: {red_flag} in {title[:50]}")

    # Cap quality score at 1.0 (boosts can't exceed perfect)
    quality_score = min(1.0, quality_score)

    # Add to offer
    offer["vendor_quality_score"] = round(quality_score, 3)
    offer["vendor_flags"] = flags

    # Adjust overall relevance by vendor quality
    if "relevance_score" in offer:
        offer["relevance_score"] *= quality_score

    return offer


async def _extract_product_with_llm(
    html: str,
    url: str,
    intent: ProductSearchIntent,
    *,
    llm_url: str = "http://localhost:8000/v1/chat/completions",
    llm_model: str = "qwen3-coder",
    llm_api_key: str = "qwen-local"
) -> ProductListing:
    """
    Use LLM to extract structured product data and verify relevance.
    Falls back to heuristics if LLM is unavailable.
    """
    
    # Clean HTML to text (simple extraction)
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text[:4000]  # Token budget

    # Load prompt via recipe system
    base_prompt = _load_prompt_via_recipe("product_matcher", "tools")
    if not base_prompt:
        logger.warning("Product matcher prompt not found via recipe")
        base_prompt = "Extract product information from this listing. Output JSON with title, price, relevance_score."

    # Build intent context
    must_have = ', '.join(intent.must_have_attributes) if intent.must_have_attributes else 'none'
    must_not_have = ', '.join(intent.must_not_have_attributes) if intent.must_not_have_attributes else 'none'
    sellers = ', '.join(intent.seller_preferences) if intent.seller_preferences else 'any'

    # Build full prompt with dynamic data
    prompt = f"""{base_prompt}

## Current Task

INTENT:
- Item type wanted: {intent.item_type}
- Category: {intent.category}
- Must have: {must_have}
- Must NOT have: {must_not_have}
- Preferred sellers: {sellers}

LISTING TEXT:
{text}"""
    
    normalizer = get_normalizer()
    
    try:
        response = httpx.post(
            llm_url,
            json={
                "model": llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 500
            },
            headers={"Authorization": f"Bearer {llm_api_key}"},
            timeout=15  # Phase 1: Reduced from 30s for product extraction
        )
        response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]

        # Extract JSON from response
        data = _extract_json_from_llm(content)

        if not data:
            logger.warning("LLM returned invalid JSON, falling back to heuristics")
            return _extract_product_with_heuristics(url, text, intent, normalizer)

        # Normalize extracted data
        price, currency = normalizer.normalize_price(data.get("price"))
        availability = normalizer.normalize_availability(data.get("availability", "unknown"))
        seller_type = normalizer.normalize_seller_type(
            data.get("seller_name", ""),
            url,
            text[:500]
        )

        return ProductListing(
            title=data.get("title", "Unknown Product"),
            url=url,
            seller_name=data.get("seller_name", "Unknown"),
            seller_type=seller_type,
            price=price,
            currency=currency or data.get("currency", "USD"),
            item_type=data.get("item_type", "unknown"),
            relevance_score=float(data.get("relevance_score", 0.0)),
            confidence=data.get("confidence", "low"),
            extracted_attributes=data.get("extracted_attributes", {}),
            rejection_reasons=data.get("rejection_reasons", []),
            availability=availability,
            verified_at=datetime.utcnow().isoformat(),
        )

    except Exception as e:
        logger.error(f"LLM extraction failed: {e}")
        return _extract_product_with_heuristics(url, text, intent, normalizer)


def _extract_json_from_llm(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from LLM response"""
    # Try to find JSON in markdown code blocks
    json_fence_pattern = re.compile(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', re.IGNORECASE)
    match = json_fence_pattern.search(text)
    
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Try to parse whole text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try to find JSON object
    brace_start = text.find('{')
    if brace_start >= 0:
        brace_count = 0
        for i in range(brace_start, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    try:
                        return json.loads(text[brace_start:i+1])
                    except json.JSONDecodeError:
                        pass
    
    return None


def _extract_product_with_heuristics(
    url: str,
    text: str,
    intent: ProductSearchIntent,
    normalizer
) -> ProductListing:
    """Fallback heuristic extraction when LLM is unavailable"""
    
    # Extract title (first significant line)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    title = lines[0] if lines else "Unknown Product"
    title = title[:200]  # Reasonable limit
    
    # Try to find price
    price_match = re.search(r'\$\s*(\d+(?:\.\d{2})?)', text)
    price = float(price_match.group(1)) if price_match else None
    
    # Check availability
    availability = "unknown"
    if any(word in text.lower() for word in ["in stock", "available", "buy now"]):
        availability = "in_stock"
    elif any(word in text.lower() for word in ["out of stock", "sold out", "unavailable"]):
        availability = "out_of_stock"
    
    # Determine seller type
    seller_type = normalizer.normalize_seller_type("", url, text[:500])
    
    # Basic relevance scoring
    relevance_score = 0.5  # Neutral
    rejection_reasons = []

    text_lower = text.lower()
    url_lower = url.lower()

    # Check for negative signals
    if any(word in text_lower for word in ["book", "ebook", "paperback", "isbn"]):
        rejection_reasons.append("appears_to_be_book")
        relevance_score = 0.3

    if any(word in text_lower for word in ["cage", "habitat", "enclosure"]) and "x" in text_lower:
        rejection_reasons.append("appears_to_be_cage")
        relevance_score = 0.3

    if ".edu" in url_lower or "educational" in text_lower or "classroom" in text_lower:
        rejection_reasons.append("educational_resource")
        relevance_score = 0.2

    # CRITICAL: Subject matching - extract what user is actually searching for
    # From category like "pet:hamster" or "electronics:laptop"
    search_subject = None
    if ":" in intent.category:
        search_subject = intent.category.split(":")[-1].strip().lower()
    else:
        search_subject = intent.category.strip().lower()

    # Also check must_have attributes for specific breeds/models
    subject_keywords = [search_subject] if search_subject else []
    for attr in intent.must_have_attributes:
        if ":" in attr:
            # e.g., "breed:Syrian" → add "syrian"
            subject_keywords.append(attr.split(":")[-1].strip().lower())
        else:
            subject_keywords.append(attr.strip().lower())

    # Check if result actually contains the search subject
    subject_match = False
    wrong_subject = False

    if subject_keywords:
        # Does the result mention what we're looking for?
        subject_match = any(keyword in text_lower or keyword in title.lower()
                           for keyword in subject_keywords if keyword)

        # Detect wrong animals/subjects (common confusions)
        if intent.item_type == "live_animal" and search_subject:
            # Map of subjects to wrong alternatives
            wrong_animals = {
                "hamster": ["hedgehog", "gerbil", "guinea pig", "rat", "mouse", "rabbit", "ferret"],
                "cat": ["dog", "rabbit", "ferret"],
                "dog": ["cat", "wolf", "fox"],
                "bird": ["hamster", "rabbit", "cat", "dog"],
                "rabbit": ["hamster", "guinea pig", "cat"],
                "guinea pig": ["hamster", "gerbil", "rabbit"],
            }

            if search_subject in wrong_animals:
                for wrong_animal in wrong_animals[search_subject]:
                    if wrong_animal in text_lower or wrong_animal in title.lower():
                        wrong_subject = True
                        rejection_reasons.append(f"wrong_animal:{wrong_animal}")
                        break

    # Positive signals for live animals - BUT ONLY IF SUBJECT MATCHES
    if intent.item_type == "live_animal":
        # If we detect wrong subject, give very low score regardless of other signals
        if wrong_subject:
            relevance_score = 0.1
        # If subject matches, apply positive signals
        elif subject_match:
            positive_keywords = ["breeder", "for sale", "adoption", "available"]
            if any(word in text_lower for word in positive_keywords):
                relevance_score = max(relevance_score, 0.8)
            if "breeder" in text_lower or "breeder" in url_lower:
                relevance_score = max(relevance_score, 0.9)
        # If subject doesn't match at all, lower score significantly
        elif subject_keywords:  # We have a subject to match but it's not in the result
            relevance_score = 0.2
            rejection_reasons.append("subject_mismatch")
        # No subject specified (shouldn't happen), use generic scoring
        else:
            positive_keywords = ["breeder", "for sale", "adoption", "available"]
            if any(word in text_lower for word in positive_keywords):
                relevance_score = max(relevance_score, 0.5)
    
    return ProductListing(
        title=title,
        url=url,
        seller_name="Unknown",
        seller_type=seller_type,
        price=price,
        currency="USD",
        item_type=intent.item_type,
        relevance_score=relevance_score,
        confidence="low",
        extracted_attributes={},
        rejection_reasons=rejection_reasons,
        availability=availability,
        verified_at=datetime.utcnow().isoformat(),
    )


async def _verify_url(
    item: Dict[str, Any],
    intent: ProductSearchIntent,
    normalizer: Any
) -> Optional[Dict[str, Any]]:
    """
    Verify a single URL by fetching and extracting product data.
    Returns verified listing dict or None if verification fails.

    Phase 2: Extracted for parallel processing with asyncio.gather
    """
    url = item.get("link") or item.get("product_link")
    if not url:
        return None

    try:
        # Fetch page with resilient fetcher
        fetch_result = await fetch_url(url)

        if not fetch_result.success:
            logger.warning(f"Failed to fetch {url}: {fetch_result.error}")
            return None

        # Extract product data with LLM (fallback to heuristics)
        try:
            listing = await _extract_product_with_llm(
                fetch_result.html,
                url,
                intent
            )
        except Exception as e:
            logger.warning(f"LLM extraction failed for {url}, falling back to heuristics: {e}")
            listing = _extract_product_with_heuristics(url, fetch_result.html[:4000], intent, normalizer)

        # Add fetch method to metadata
        listing.fetch_method = fetch_result.method

        # Normalize price if from SerpAPI
        if not listing.price and item.get("price"):
            listing.price, listing.currency = normalizer.normalize_price(item.get("price"))

        # Convert to dict
        listing_dict = listing.to_dict()

        # Add verification metadata
        listing_dict["verified"] = True
        listing_dict["fetch_method"] = fetch_result.method

        return listing_dict

    except Exception as e:
        logger.error(f"Error processing {url}: {e}")
        return None


async def search_with_intent(
    intent: ProductSearchIntent,
    *,
    user_id: Optional[str] = None,
    max_results: int = 6,
    max_verification: int = 15,
    discovered_sources: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Execute product search with intent-based filtering and quality assessment.
    
    Returns dict with:
    - results: List of verified ProductListing dicts
    - rejected: List of rejected listings
    - quality_score: 0-1 score
    - issues: List of detected issues
    - suggested_refinement: Optional refinement plan
    """
    
    normalizer = get_normalizer()
    
    # Build search query with improved construction
    base_query = intent.category.split(":")[-1] if ":" in intent.category else intent.category

    # For live animals, add explicit "for sale" modifier
    if intent.item_type == "live_animal":
        base_query = f"{base_query} for sale"

    # Add must-have attributes to query (limit to avoid overloading)
    positive_terms = []
    for attr in intent.must_have_attributes:
        if ":" not in attr:  # Simple attribute
            positive_terms.append(attr)

    # For seller preferences, add only top preference to avoid overloading
    if intent.seller_preferences and "breeder" in intent.seller_preferences:
        base_query = f"{base_query} breeder"

    # Build negative keywords - LIMIT TO 3 to avoid over-filtering
    negative_terms = []
    critical_negatives = ["book", "ebook", "toy", "plush"]  # Most critical filters
    for attr in intent.must_not_have_attributes:
        if attr in critical_negatives and len(negative_terms) < 3:
            negative_terms.append(f"-{attr}")

    # Use trusted sources if available
    if discovered_sources:
        high_trust = [s for s in discovered_sources if s.get("trust_score", 0) >= 0.7]
        if high_trust:
            domains = [s.get("domain") for s in high_trust[:3]]
            site_query = " OR ".join([f"site:{d}" for d in domains if d])
            query = f"({site_query}) {base_query} {' '.join(positive_terms[:2])}"
        else:
            query = f"{base_query} {' '.join(positive_terms[:2])} {' '.join(negative_terms)}"
    else:
        query = f"{base_query} {' '.join(positive_terms[:2])} {' '.join(negative_terms)}"
    
    logger.info(f"Executing search with query: {query}")

    # Execute search using Playwright-based human_search_engine
    # Replaced deprecated search_verifier_mcp with direct human_search_engine call
    try:
        from apps.services.orchestrator import human_search_engine
        basic_results = await human_search_engine.search(
            query,
            k=max_results,
            pause=1.0
        )
        # Convert results to expected format
        raw_results = []
        for item in basic_results[:max_results]:
            raw_results.append({
                "title": item.get("title", "Unknown Product"),
                "link": item.get("url") or item.get("link", ""),
                "url": item.get("url") or item.get("link", ""),
                "seller_name": "Unknown",
                "seller_type": "marketplace",
                "price": None,
                "currency": "USD",
                "item_type": intent.item_type,
                "relevance_score": 0.5,
                "confidence": "low",
                "extracted_attributes": {},
                "rejection_reasons": [],
                "availability": "unknown",
                "verified_at": datetime.utcnow().isoformat(),
            })
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return {
            "results": [],
            "rejected": [],
            "quality_score": 0.0,
            "issues": ["search_failed"],
            "suggested_refinement": None,
            "stats": {"raw_count": 0, "verified_count": 0, "rejected_count": 0}
        }

    logger.info(f"Got {len(raw_results)} raw results from search")

    # ZERO-RESULT FALLBACK: If no results, try broader searches (faster, no verification)
    if not raw_results or len(raw_results) == 0:
        logger.warning(f"Initial search returned 0 results, trying simpler fallback strategies")

        # Fallback 1: DuckDuckGo direct search (no browser verification)
        try:
            logger.info("Fallback 1: Trying DuckDuckGo direct search (no verification)")
            ddg_results = await human_search_engine.search(
                query,
                k=max_verification,
                pause=1.0
            )
            # Convert to expected format
            raw_results = [
                {
                    "title": item.get("title", ""),
                    "link": item.get("url", ""),
                    "source": "duckduckgo_fallback",
                    "price": None,
                    "extracted_price": None,
                    "currency": None,
                    "availability": "unknown",
                    "position": item.get("position", 0),
                    "verified": False
                }
                for item in ddg_results
            ]
            logger.info(f"Fallback 1 (DuckDuckGo direct) returned {len(raw_results)} results")
        except Exception as e:
            logger.error(f"Fallback 1 (DuckDuckGo direct) failed: {e}")

        # Fallback 2: If still zero, try simplified query (remove negative filters)
        if not raw_results:
            try:
                simplified_query = base_query  # Just the base, no negatives
                logger.info(f"Fallback 2: Trying simplified DuckDuckGo query: {simplified_query}")

                ddg_results = await human_search_engine.search(
                    simplified_query,
                    k=max_verification,
                    pause=1.0
                )
                # Convert results
                raw_results = [
                    {
                        "title": item.get("title", ""),
                        "link": item.get("url", ""),
                        "source": "duckduckgo_simplified",
                        "price": None,
                        "extracted_price": None,
                        "currency": None,
                        "availability": "unknown",
                        "position": item.get("position", 0),
                        "verified": False
                    }
                    for item in ddg_results
                ]
                logger.info(f"Fallback 2 (simplified DuckDuckGo) returned {len(raw_results)} results")
            except Exception as e:
                logger.error(f"Fallback 2 (simplified query) failed: {e}")

        # Fallback 3: If STILL zero, try most generic query (category only)
        if not raw_results:
            try:
                generic_query = intent.category.split(":")[-1] if ":" in intent.category else intent.category
                logger.info(f"Fallback 3: Trying most generic DuckDuckGo query: {generic_query}")

                ddg_results = await human_search_engine.search(
                    generic_query,
                    k=max_verification,
                    pause=1.0
                )
                raw_results = [
                    {
                        "title": item.get("title", ""),
                        "link": item.get("url", ""),
                        "source": "duckduckgo_generic",
                        "price": None,
                        "extracted_price": None,
                        "currency": None,
                        "availability": "unknown",
                        "position": item.get("position", 0),
                        "verified": False
                    }
                    for item in ddg_results
                ]
                logger.info(f"Fallback 3 (generic DuckDuckGo) returned {len(raw_results)} results")
            except Exception as e:
                logger.error(f"Fallback 3 (generic query) failed: {e}")

        # If all fallbacks failed, return empty with diagnostics
        if not raw_results:
            logger.error(f"All fallback strategies failed for query: {query}")
            return {
                "results": [],
                "rejected": [],
                "quality_score": 0.0,
                "issues": ["zero_results_all_strategies"],
                "suggested_refinement": {
                    "rationale": "All search strategies (original + 3 fallbacks) returned zero results. Query may be too specific or item not available.",
                    "suggestions": [
                        "Try broader search terms",
                        "Check spelling and product availability",
                        "Consider alternative product names"
                    ]
                },
                "stats": {"raw_count": 0, "verified_count": 0, "rejected_count": 0}
            }

    # Phase 2: Sequential URL verification (one at a time to avoid triggering blockers)
    verified_listings: List[Dict[str, Any]] = []
    rejected_listings: List[Dict[str, Any]] = []

    logger.info(f"Starting sequential verification of {len(raw_results[:max_verification])} URLs")

    for i, item in enumerate(raw_results[:max_verification]):
        try:
            result = await _verify_url(item, intent, normalizer)

            if result is None:
                # Verification failed (fetch error, no URL, etc.)
                continue

            # Apply relevance filter
            if result.get("rejection_reasons") or result.get("relevance_score", 0) < 0.7:
                rejected_listings.append(result)
            else:
                verified_listings.append(result)

            # Early termination: Stop if we have enough verified results
            if len(verified_listings) >= max_results:
                logger.info(f"Early termination: {len(verified_listings)} verified (target: {max_results})")
                break

            # Log progress every 5 URLs
            if (i + 1) % 5 == 0:
                logger.info(f"Progress: {i+1} processed, {len(verified_listings)} verified, {len(rejected_listings)} rejected")

        except Exception as e:
            logger.error(f"Exception during verification of URL {i+1}: {e}")

    # Deduplicate verified listings
    if verified_listings:
        verified_listings, duplicates = normalizer.deduplicate_listings(verified_listings)
        rejected_listings.extend(duplicates)
    
    # Calculate quality score
    total_fetched = len(raw_results)
    verified_count = len(verified_listings)
    quality_score = verified_count / max(1, total_fetched) if total_fetched > 0 else 0.0
    
    # Diagnose issues
    issues = _diagnose_issues(verified_listings, rejected_listings, intent)
    
    # Generate refinement suggestion if quality is low
    suggested_refinement = None
    if quality_score < 0.3 and issues:
        suggested_refinement = _generate_refinement(intent, issues, rejected_listings)
    
    results_dicts = verified_listings
    rejected_dicts = rejected_listings
    
    logger.info(f"Search complete: {verified_count} verified, {len(rejected_listings)} rejected, quality={quality_score:.2f}")
    
    return {
        "results": results_dicts,
        "rejected": rejected_dicts,
        "quality_score": quality_score,
        "issues": issues,
        "suggested_refinement": suggested_refinement,
        "stats": {
            "raw_count": total_fetched,
            "verified_count": verified_count,
            "rejected_count": len(rejected_listings)
        }
    }


def _diagnose_issues(
    verified: List[Dict[str, Any]],
    rejected: List[Dict[str, Any]],
    intent: ProductSearchIntent
) -> List[str]:
    """Diagnose why search quality is low"""
    issues = []

    if not rejected:
        return []

    # Count rejection reasons
    reason_counts = {}
    for listing in rejected:
        for reason in listing.get("rejection_reasons", []):
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    
    total_rejected = len(rejected)
    
    # Check for dominant issues
    if reason_counts.get("wrong_item_type", 0) > total_rejected * 0.5:
        issues.append("wrong_item_type_dominant")
    
    if reason_counts.get("educational_resource", 0) > 0:
        issues.append("educational_sites_in_results")
    
    if reason_counts.get("appears_to_be_cage", 0) > 2:
        issues.append("accessory_results_dominant")
    
    if reason_counts.get("appears_to_be_book", 0) > 2:
        issues.append("book_results_dominant")
    
    return issues


def _generate_refinement(
    intent: ProductSearchIntent,
    issues: List[str],
    rejected_samples: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Generate refined search intent based on issues"""
    
    refined_intent = ProductSearchIntent(
        item_type=intent.item_type,
        category=intent.category,
        must_have_attributes=list(intent.must_have_attributes),
        must_not_have_attributes=list(intent.must_not_have_attributes),
        seller_preferences=list(intent.seller_preferences),
        price_range=intent.price_range,
        trusted_sources=list(intent.trusted_sources),
        location=intent.location
    )
    
    # Add negative keywords based on issues
    if "educational_sites_in_results" in issues:
        refined_intent.must_not_have_attributes.extend(["educational", "classroom", ".edu"])
    
    if "accessory_results_dominant" in issues:
        refined_intent.must_not_have_attributes.extend(["cage", "habitat", "enclosure"])
        refined_intent.must_have_attributes.append("live")
    
    if "book_results_dominant" in issues:
        refined_intent.must_not_have_attributes.extend(["book", "ebook", "isbn"])
    
    if "wrong_item_type_dominant" in issues:
        # Strengthen must-have attributes
        if intent.item_type == "live_animal":
            refined_intent.must_have_attributes.append("breeder")
            refined_intent.seller_preferences = ["breeder", "rescue"]
    
    return {
        "intent": refined_intent.to_dict(),
        "rationale": f"Refined based on issues: {', '.join(issues)}"
    }


def best_offer(offers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Select the best offer from a list of offers (lowest price or first)."""
    if not offers:
        return None
    priced = [o for o in offers if o.get('price') is not None]
    if priced:
        return min(priced, key=lambda x: x['price'])
    return offers[0] if offers else None


# Legacy compatibility function - SYNC wrapper
def search_offers(
    query: str,
    *,
    user_id: Optional[str] = None,
    max_results: int = 5,
    extra_query: str = "",
    country: str = "us",
    language: str = "en",
    pause: float = 1.0,
) -> List[Dict[str, Any]]:
    """
    Legacy interface - wraps search_with_intent for backwards compatibility.
    SYNC function that runs async code internally.
    """
    
    # Infer intent from query
    item_type = infer_item_type(query, extra_query)
    category = infer_category(query, extra_query)

    # Build intent with smart filtering
    # Check what the user is actually asking for
    combined_query = (query + " " + extra_query).lower()

    # Default exclusions (things to filter out)
    must_not_have = []

    # If query explicitly asks for something, don't filter it out
    # e.g., "hamster cage" should NOT filter out cages
    if "cage" not in combined_query:
        must_not_have.append("cage")
    if "toy" not in combined_query:
        must_not_have.append("toy")
    if "book" not in combined_query:
        must_not_have.append("book")
    if "plush" not in combined_query:
        must_not_have.append("plush")
    if "accessory" not in combined_query and "accessories" not in combined_query:
        must_not_have.append("accessory")
    if "educational" not in combined_query:
        must_not_have.append("educational")

    # Add specific negative keywords based on detected item type
    if item_type == "live_animal":
        must_not_have.extend(["poster", "print", "calendar", "sticker"])

    intent = ProductSearchIntent(
        item_type=item_type,
        category=category,
        must_have_attributes=["live"] if item_type == "live_animal" else [],
        must_not_have_attributes=must_not_have,
        seller_preferences=["breeder"] if item_type == "live_animal" else [],
    )
    
    # Run async function in sync context
    result = asyncio.run(search_with_intent(intent, user_id=user_id, max_results=max_results))
    raw_offers = result.get("results", [])

    # SPECIES VALIDATION (2025-11-13): Filter out wrong species/varieties
    full_query = f"{query} {extra_query}".strip()
    validated_offers = []
    rejected_offers = []

    for offer in raw_offers:
        # Build result text for validation
        result_text = f"{offer.get('title', '')} {offer.get('description', '')}"

        # Validate species match
        match_score, rejection_reason = validate_species_match(full_query, result_text)

        # Apply species match to relevance score
        original_relevance = offer.get("relevance_score", 0.5)
        offer["relevance_score"] = original_relevance * match_score
        offer["species_match_score"] = match_score

        # Add rejection reason if failed
        if rejection_reason:
            offer.setdefault("rejection_reasons", []).append(rejection_reason)

        # REJECT if complete species mismatch
        if match_score == 0.0:
            rejected_offers.append(offer)
            logger.warning(
                f"[commerce.search_offers] REJECTED (species mismatch): {offer.get('title', 'unknown')[:60]} "
                f"- {rejection_reason}"
            )
        else:
            validated_offers.append(offer)
            if match_score < 1.0:
                match_quality = "perfect" if match_score == 1.0 else "partial" if match_score >= 0.5 else "weak"
                logger.info(
                    f"[commerce.search_offers] ACCEPTED ({match_quality} match): {offer.get('title', 'unknown')[:60]} "
                    f"- score {match_score:.2f} - {rejection_reason or 'ok'}"
                )

    # VENDOR VERIFICATION (2025-11-13): Add quality indicators and adjust scores
    for offer in validated_offers:
        verify_vendor_quality(offer, item_type=item_type)

    # Sort by adjusted relevance score (now includes vendor quality)
    validated_offers.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    logger.info(
        f"[commerce.search_offers] Processing complete: "
        f"{len(validated_offers)} offers (species validation: {len(rejected_offers)} rejected, "
        f"vendor verification: applied)"
    )

    return validated_offers[:max_results]

# ============================================================================
# MULTI-PHASE PRODUCT SEARCH (Added: 2025-11-15)
# Intelligence-driven two-phase search with spec matching
# ============================================================================

async def search_with_recommendations(
    query: str,
    session_id: str = "default",
    category: Optional[str] = None,
    max_vendors_phase1: int = 10,
    max_products_phase2: int = 20
) -> Dict[str, Any]:
    """
    Deep search: Phase 1 (intelligence gathering) + Phase 2 (product search).
    
    Phase 1: Discovers vendors, specs, quality criteria from community sources
    Phase 2: Finds products matching Phase 1 intelligence
    
    Args:
        query: Product search query (e.g., "Syrian hamster")
        session_id: Session ID for browser context reuse
        category: Product category (auto-inferred if None)
        max_vendors_phase1: Max vendors to extract in Phase 1
        max_products_phase2: Max products to return
        
    Returns:
        {
            "mode": "deep",
            "status": "success",
            "phase1": {
                "intelligence": {...},  // Vendor + spec + quality data
                "vendor_count": int,
                "top_vendors": [str]
            },
            "phase2": {
                "products": [...],  // Ranked product listings
                "total_found": int
            },
            "stats": {
                "total_time_sec": float,
                "phase1_time_sec": float,
                "phase2_time_sec": float
            }
        }
    """
    # Updated 2026-01-27: Use new LLM-driven research API
    from apps.tools.internet_research import execute_full_research
    from apps.services.orchestrator.research_event_emitter import ResearchEventEmitter

    # Create event emitter for research monitor
    event_emitter = ResearchEventEmitter(session_id)

    result = await execute_full_research(
        goal=query,
        intent="commerce",
        task=f"Find vendors, products, and pricing information for: {query}",
        session_id=session_id,
        target_vendors=3,
        event_emitter=event_emitter,
        human_assist_allowed=True,
    )

    # Convert to expected format
    phase1_data = result.get("phase1", {}) or {}
    phase2_data = result.get("phase2", {}) or {}

    return {
        "mode": "deep",
        "status": "success" if result.get("success") else "error",
        "phase1": {
            "intelligence": phase1_data.get("intelligence", {}),
            "vendor_count": len(phase1_data.get("vendor_hints", [])),
            "top_vendors": phase1_data.get("vendor_hints", [])[:5],
        },
        "phase2": {
            "products": result.get("products", []),
            "total_found": len(result.get("products", [])),
        },
        "stats": {
            "total_time_sec": result.get("total_elapsed_seconds", 0),
            "phase1_time_sec": phase1_data.get("elapsed_seconds", 0),
            "phase2_time_sec": phase2_data.get("elapsed_seconds", 0),
        },
        "recommendation": result.get("recommendation", ""),
        "price_assessment": result.get("price_assessment", ""),
    }


async def quick_search(
    query: str,
    session_id: str = "default",
    category: Optional[str] = None,
    use_cached_vendors: bool = True
) -> Dict[str, Any]:
    """
    Quick search: Phase 2 only (skip intelligence gathering).
    
    Uses cached Phase 1 intelligence from previous searches or category defaults.
    Faster but no community-validated vendor recommendations.
    
    Args:
        query: Product search query
        session_id: Session ID
        category: Product category (auto-inferred if None)
        use_cached_vendors: Try to use cached vendor list
        
    Returns:
        {
            "mode": "quick",
            "status": "success",
            "vendor_source": "cached|defaults",
            "phase2": {
                "products": [...],
                "total_found": int
            },
            "note": "Quick search - run deep search for recommendations",
            "stats": {
                "total_time_sec": float,
                "cache_hit": bool
            }
        }
    """
    from apps.services.orchestrator.commerce_search_multi_phase import get_search_orchestrator
    
    orchestrator = get_search_orchestrator()
    
    # TODO: Check session cache for previous Phase 1 intelligence
    cached_intelligence = None  # Will be implemented with Context Manager integration
    
    result = await orchestrator.quick_search(
        query=query,
        session_id=session_id,
        category=category,
        cached_intelligence=cached_intelligence
    )
    
    return result
