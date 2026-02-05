"""
orchestrator/browser_agent.py

Multi-page browsing agent for forums, vendor catalogs, and paginated content.
Uses Web Vision MCP for browser control.

Created: 2025-11-18
Purpose: Enable intelligent multi-page browsing with vision-guided navigation
"""

import asyncio
import logging
import re
from typing import Dict, List, Any, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from apps.services.tool_server.shared import call_llm_json, call_llm_text
from libs.gateway.llm.recipe_loader import load_recipe, RecipeNotFoundError

logger = logging.getLogger(__name__)

# Recipe cache for browser prompts
_recipe_cache: Dict[str, str] = {}


def _load_browser_prompt(name: str) -> str:
    """
    Load a browser prompt via the recipe system.

    Uses caching to avoid repeated recipe loads.

    Args:
        name: Recipe name without path prefix (e.g., "pagination_handler")

    Returns:
        Prompt content as string, or empty string if not found
    """
    if name in _recipe_cache:
        return _recipe_cache[name]

    try:
        recipe = load_recipe(f"browser/{name}")
        prompt = recipe.get_prompt()
        _recipe_cache[name] = prompt
        logger.debug(f"[BrowserAgent] Loaded prompt via recipe: browser/{name}")
        return prompt
    except RecipeNotFoundError:
        logger.warning(f"[BrowserAgent] Recipe not found: browser/{name}")
        return ""
    except Exception as e:
        logger.warning(f"[BrowserAgent] Failed to load recipe browser/{name}: {e}")
        return ""


async def deep_browse(
    url: str,
    browsing_goal: str,
    max_pages: int = 10,
    session_id: str = "default",
    event_emitter: Optional[Any] = None,
    human_assist_allowed: bool = True,
    llm_url: str = None,
    llm_model: str = None,
    llm_api_key: str = None
) -> Optional[Dict[str, Any]]:
    """
    Deep browse a website: Visit initial page and explore related pages intelligently.

    NOW USES WEB VISION MCP for navigation (vision-guided, adaptive).

    Use cases:
    - Forum threads with multiple pages (browse all pages of discussion)
    - Vendor catalogs with pagination (extract all products from all pages)
    - Product listings with "Load More" (get complete inventory)
    - Category navigation (Available, Retired, Upcoming sections)
    - Documentation with page sequences

    Args:
        url: Initial URL to start browsing
        browsing_goal: What we're trying to accomplish
        max_pages: Maximum pages to visit (safety limit, default: 10)
        session_id: Session ID for browser context persistence
        event_emitter: Optional progress event emitter
        human_assist_allowed: Allow CAPTCHA intervention (default: True)
        llm_url, llm_model, llm_api_key: LLM config (optional, from env if not provided)

    Returns:
        {
            "url": str,  # Initial URL
            "pages_visited": List[Dict],  # All pages visited with extractions
            "aggregated_info": Dict,  # Combined extraction from all pages
            "navigation_path": List[str],  # URLs in order visited
            "page_type": str,  # Detected type (forum, catalog, etc.)
            "relevance_score": float,  # Overall relevance (average of all pages)
            "summary": str,  # Summary of all pages combined
            "key_points": List[str],  # Combined key points from all pages
            "text_content": str,  # All sanitized text combined
            "metadata": Dict,  # Metadata with sanitization stats
            "stats": {
                "total_pages": int,
                "relevant_pages": int,
                "stopped_reason": "max_pages|no_more_links|goal_met|low_relevance|duplicates"
            }
        }

        Returns None if initial page failed or not relevant.
    """
    from apps.services.tool_server import web_vision_mcp
    from apps.services.tool_server.content_sanitizer import ContentSanitizer

    logger.info(f"[BrowserAgent] Starting deep browse (Web Vision): {url[:60]}... (max_pages={max_pages})")

    if event_emitter:
        await event_emitter.emit("deep_browse_started", {
            "url": url,
            "max_pages": max_pages,
            "goal": browsing_goal
        })

    # Step 1: Visit initial page using Web Vision
    try:
        # Navigate to initial URL
        await web_vision_mcp.navigate(
            session_id=session_id,
            url=url,
            wait_for="networkidle"
        )

        # Capture content (used for both relevance check and extraction)
        # NOTE: Removed get_screen_state() call - it was doing expensive DOM extraction
        # (1500+ Playwright calls, 10+ seconds) just to get text for relevance check.
        # Using capture_content() is much faster and provides the same information.
        content_result = await web_vision_mcp.capture_content(
            session_id=session_id,
            format="markdown"
        )

        # Check relevance with LLM using captured content
        # Create a compact page state from the content (first 500 chars + title)
        page_title = content_result.get("title", "Unknown")
        content_preview = content_result.get("content", "")[:500]
        page_state = f"Title: {page_title}\nURL: {url}\n\nContent preview:\n{content_preview}"

        is_relevant = await _check_relevance_llm(
            page_state=page_state,
            goal=browsing_goal,
            llm_url=llm_url,
            llm_model=llm_model,
            llm_api_key=llm_api_key
        )

        if not is_relevant:
            logger.warning(f"[BrowserAgent] Initial page not relevant to goal: {browsing_goal}")
            return None

        # Sanitize and extract
        sanitizer = ContentSanitizer()
        sanitized = sanitizer.sanitize(content_result["content"], url)

        # Reconstruct clean_text from chunks
        if "chunks" in sanitized and sanitized["chunks"]:
            clean_text = "\n\n".join(chunk["text"] for chunk in sanitized["chunks"])
        else:
            # Fallback: use raw content if sanitizer failed
            clean_text = content_result["content"]
            logger.warning(f"[BrowserAgent] No chunks from sanitizer, using raw content ({len(clean_text)} chars)")

        # Create initial page result
        initial_result = {
            "url": url,
            "text_content": clean_text,
            "extracted_info": _basic_extraction(clean_text, browsing_goal),
            "relevance_score": 0.8,  # Passed relevance check
            "summary": clean_text[:500] + "..." if len(clean_text) > 500 else clean_text,
            "key_points": [],
            "page_type": "unknown",
            "metadata": {
                "sanitization": sanitized.get("stats", {}),
                "page_info": content_result.get("page_info", {})
            }
        }

    except Exception as e:
        logger.error(f"[BrowserAgent] Failed to visit initial page: {e}")
        return None

    if not initial_result:
        logger.warning(f"[BrowserAgent] Initial page failed or not relevant: {url[:60]}")
        return None

    # Track visited pages
    pages_visited = [initial_result]
    navigation_path = [url]
    visited_urls = {url}  # Deduplicate URLs

    # Step 2: Detect navigation opportunities on first page
    first_page_content = initial_result.get("text_content", "")
    nav_check = await detect_navigation_opportunities(
        page_content=first_page_content,
        url=url,
        browsing_goal=browsing_goal,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key
    )

    logger.info(
        f"[BrowserAgent] Navigation check: has_more={nav_check['has_more_pages']}, "
        f"type={nav_check['navigation_type']}, "
        f"confidence={nav_check.get('confidence', 0):.2f}"
    )

    if not nav_check["has_more_pages"]:
        # Single page only - return as-is
        logger.info(f"[BrowserAgent] No additional pages detected, returning single page result")
        return {
            **initial_result,
            "pages_visited": pages_visited,
            "navigation_path": navigation_path,
            "aggregated_info": initial_result.get("extracted_info", {}),
            "stats": {
                "total_pages": 1,
                "relevant_pages": 1,
                "stopped_reason": "no_more_links"
            }
        }

    # Step 3: Build list of pages to visit
    navigation_type = nav_check["navigation_type"]
    pages_to_visit = []

    # Add next page URL if found
    if nav_check.get("next_page_url"):
        pages_to_visit.append(nav_check["next_page_url"])

    # Add other relevant links (categories, numbered pages, etc.)
    if nav_check.get("other_relevant_links"):
        pages_to_visit.extend(nav_check["other_relevant_links"][:max_pages - 1])

    logger.info(f"[BrowserAgent] Found {len(pages_to_visit)} potential pages to visit")

    # Step 4: Browse additional pages sequentially
    current_page = 1
    stopped_reason = "max_pages"

    for next_url in pages_to_visit:
        if current_page >= max_pages:
            logger.info(f"[BrowserAgent] Max pages reached ({max_pages}), stopping")
            stopped_reason = "max_pages"
            break

        # Skip if already visited (avoid loops)
        if next_url in visited_urls:
            logger.debug(f"[BrowserAgent] Skipping already visited: {next_url[:60]}")
            continue

        current_page += 1

        logger.info(f"[BrowserAgent] Visiting page {current_page}/{max_pages}: {next_url[:60]}...")

        if event_emitter:
            await event_emitter.emit("deep_browse_progress", {
                "page": current_page,
                "total": max_pages,
                "url": next_url,
                "navigation_type": navigation_type
            })

        # Navigate to next page using Web Vision
        next_result = await navigate_to_next(
            current_url=navigation_path[-1],
            next_url=next_url,
            navigation_type=navigation_type,
            session_id=session_id,
            browsing_goal=browsing_goal,
            llm_url=llm_url,
            llm_model=llm_model,
            llm_api_key=llm_api_key
        )

        if not next_result:
            logger.warning(f"[BrowserAgent] Navigation failed to {next_url[:60]}, skipping")
            continue

        # Check relevance of new page
        if next_result.get("relevance_score", 0) < 0.3:
            logger.info(
                f"[BrowserAgent] Low relevance page {current_page} "
                f"(score={next_result['relevance_score']:.2f}), stopping early"
            )
            stopped_reason = "low_relevance"
            break

        # Check content similarity (fast check before LLM)
        similarity = _check_content_similarity(next_result, pages_visited)
        if similarity > 0.9:
            logger.info(
                f"[BrowserAgent] Page {current_page} is 90%+ similar to previous page, stopping"
            )
            stopped_reason = "duplicates"
            break

        # Add to visited pages
        pages_visited.append(next_result)
        navigation_path.append(next_url)
        visited_urls.add(next_url)

        # Log sanitization savings for this page
        san_stats = next_result.get("metadata", {}).get("sanitization", {})
        logger.info(
            f"[BrowserAgent] Page {current_page} sanitized: "
            f"{san_stats.get('reduction_pct', 0):.0f}% size reduction"
        )

        # Check if we should continue (LLM evaluation)
        should_continue = await should_continue_browsing(
            pages_visited=pages_visited,
            browsing_goal=browsing_goal,
            max_pages=max_pages,
            llm_url=llm_url,
            llm_model=llm_model,
            llm_api_key=llm_api_key
        )

        logger.info(
            f"[BrowserAgent] Continue decision: {should_continue['continue']} "
            f"(new_info={should_continue.get('new_info_score', 0):.2f}, "
            f"goal_satisfaction={should_continue.get('goal_satisfaction', 0):.2f})"
        )

        if not should_continue["continue"]:
            logger.info(
                f"[BrowserAgent] Stopping after {current_page} pages: "
                f"{should_continue['reason']}"
            )
            stopped_reason = "goal_met"
            break

        # Detect more pages from current page (for continuous pagination)
        if current_page < max_pages:
            next_page_content = next_result.get("text_content", "")
            next_nav_check = await detect_navigation_opportunities(
                page_content=next_page_content,
                url=next_url,
                browsing_goal=browsing_goal,
                llm_url=llm_url,
                llm_model=llm_model,
                llm_api_key=llm_api_key
            )

            # If there's a next page link, add it to queue
            if next_nav_check.get("next_page_url"):
                if next_nav_check["next_page_url"] not in visited_urls:
                    if next_nav_check["next_page_url"] not in pages_to_visit:
                        pages_to_visit.append(next_nav_check["next_page_url"])

    # Step 5: Aggregate results from all pages
    logger.info(f"[BrowserAgent] Aggregating results from {len(pages_visited)} pages")

    aggregated = await aggregate_multi_page_results(
        pages=pages_visited,
        browsing_goal=browsing_goal,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key
    )

    # Calculate average sanitization reduction
    avg_sanitization = sum(
        p.get("metadata", {}).get("sanitization", {}).get("reduction_pct", 0)
        for p in pages_visited
    ) / len(pages_visited) if pages_visited else 0

    # Build final result
    result = {
        "url": url,
        "pages_visited": pages_visited,
        "aggregated_info": aggregated["extracted_info"],
        "navigation_path": navigation_path,
        "page_type": initial_result.get("page_type", "unknown"),
        "relevance_score": sum(p.get("relevance_score", 0) for p in pages_visited) / len(pages_visited),
        "summary": aggregated["summary"],
        "key_points": aggregated["key_points"],
        "text_content": aggregated.get("combined_text", ""),
        "metadata": {
            **aggregated.get("metadata", {}),
            "deep_browse": True,
            "navigation_type": navigation_type,
            "sanitization": {
                "avg_reduction_pct": avg_sanitization,
                "total_pages_sanitized": len(pages_visited)
            }
        },
        "stats": {
            "total_pages": len(pages_visited),
            "relevant_pages": len([p for p in pages_visited if p.get("relevance_score", 0) >= 0.5]),
            "stopped_reason": stopped_reason,
            "avg_sanitization_reduction": avg_sanitization
        }
    }

    if event_emitter:
        await event_emitter.emit("deep_browse_complete", {
            "pages_visited": len(pages_visited),
            "items_found": aggregated["metadata"].get("total_items", 0),
            "stopped_reason": stopped_reason
        })

    logger.info(
        f"[BrowserAgent] Deep browse complete: {len(pages_visited)} pages, "
        f"{aggregated['metadata'].get('total_items', 0)} items found, "
        f"stopped_reason={stopped_reason}"
    )

    return result


async def detect_navigation_opportunities(
    page_content: str,
    url: str,
    browsing_goal: str,
    llm_url: str = None,
    llm_model: str = None,
    llm_api_key: str = None
) -> Dict[str, Any]:
    """
    Detect if there are more pages to explore on this site.

    Uses hybrid approach:
    1. Pattern matching (fast, deterministic) - pagination links, Next buttons
    2. LLM analysis (intelligent, flexible) - understands navigation semantically

    Args:
        page_content: HTML or text content of current page
        url: Current page URL
        browsing_goal: What we're trying to find
        llm_url, llm_model, llm_api_key: LLM config (optional)

    Returns:
        {
            "has_more_pages": bool,
            "navigation_type": "pagination|load_more|thread|category|none",
            "next_page_url": str or None,  # Direct next page link
            "other_relevant_links": List[str],  # Other pages worth exploring
            "page_numbers": List[int],  # If numbered pagination detected
            "categories": List[str],  # If category navigation detected
            "confidence": float,  # 0.0-1.0
            "reason": str  # Why we think there are more pages
        }
    """
    import os

    # Get LLM config
    if not llm_url:
        llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    # Parse HTML if it looks like HTML
    soup = None
    if page_content.strip().startswith('<'):
        soup = BeautifulSoup(page_content, 'html.parser')
    else:
        # Plain text - create minimal soup for consistency
        soup = BeautifulSoup(f"<html><body>{page_content}</body></html>", 'html.parser')

    # Step 1: Pattern-based detection (fast, deterministic)
    pagination_info = _extract_pagination_links(soup, url)
    category_info = _extract_category_links(soup, url)

    # If we found clear pagination with Next button, return immediately (high confidence)
    if pagination_info.get("next_page_url"):
        return {
            "has_more_pages": True,
            "navigation_type": "pagination",
            "next_page_url": pagination_info["next_page_url"],
            "other_relevant_links": pagination_info.get("page_links", [])[:5],
            "page_numbers": pagination_info.get("page_numbers", []),
            "categories": category_info,
            "confidence": 0.95,
            "reason": "Clear pagination detected (Next button/link found)"
        }

    # If we found categories, high confidence for category navigation
    if len(category_info) >= 2:
        return {
            "has_more_pages": True,
            "navigation_type": "category",
            "next_page_url": None,
            "other_relevant_links": category_info[:10],
            "page_numbers": [],
            "categories": category_info,
            "confidence": 0.9,
            "reason": f"Found {len(category_info)} category links"
        }

    # Step 2: LLM-based detection (intelligent, flexible)
    # Extract all links for LLM analysis
    all_links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        # Convert relative to absolute
        abs_url = urljoin(url, href)
        link_text = a.get_text(strip=True)
        if link_text:  # Only include links with text
            all_links.append({"url": abs_url, "text": link_text})

    # Extract button text (might indicate Load More, etc.)
    buttons = [btn.get_text(strip=True) for btn in soup.find_all('button') if btn.get_text(strip=True)]

    # Load prompt and build context
    base_prompt = _load_browser_prompt("pagination_handler")
    if not base_prompt:
        # Fallback if prompt file not found
        base_prompt = "Analyze webpage for pagination. Return JSON with has_more_pages, navigation_type, next_page_url, other_relevant_links, confidence, reason."

    prompt = f"""{base_prompt}

## Current Page Analysis

**URL:** {url}
**Goal:** {browsing_goal}

**Links found ({len(all_links[:30])} shown):**
{chr(10).join(f"- {link['text']}: {link['url'][:80]}" for link in all_links[:30])}

**Buttons found:**
{chr(10).join(f"- {btn}" for btn in buttons[:10])}

**Categories detected:** {category_info}
**Numbered pages detected:** {pagination_info.get('page_numbers', [])}

IMPORTANT: Return ONLY valid JSON, no other text before or after."""

    try:
        result = await call_llm_json(prompt, llm_url, llm_model, llm_api_key, max_tokens=400)

        # Add pattern-detected info to result
        result["page_numbers"] = pagination_info.get("page_numbers", [])
        result["categories"] = category_info

        # Ensure other_relevant_links is a list
        if not isinstance(result.get("other_relevant_links"), list):
            result["other_relevant_links"] = []

        # Limit to 10 links
        result["other_relevant_links"] = result["other_relevant_links"][:10]

        return result

    except Exception as e:
        logger.warning(f"[BrowserAgent] LLM navigation detection failed: {e}, using pattern-only")

        # Fallback to pattern-only result
        has_more = len(category_info) > 0 or len(pagination_info.get("page_links", [])) > 0

        return {
            "has_more_pages": has_more,
            "navigation_type": "category" if category_info else ("pagination" if pagination_info.get("page_links") else "none"),
            "next_page_url": None,
            "other_relevant_links": (pagination_info.get("page_links", []) + category_info)[:10],
            "page_numbers": pagination_info.get("page_numbers", []),
            "categories": category_info,
            "confidence": 0.5,
            "reason": "Pattern-based detection only (LLM failed)"
        }


async def navigate_to_next(
    current_url: str,
    next_url: str,
    navigation_type: str,
    session_id: str,
    browsing_goal: str,
    llm_url: str = None,
    llm_model: str = None,
    llm_api_key: str = None
) -> Optional[Dict[str, Any]]:
    """
    Navigate to the next page and fetch content using Web Vision MCP.

    Args:
        current_url: Current page URL (for logging/context)
        next_url: URL to navigate to
        navigation_type: Type of navigation (pagination, load_more, etc.)
        session_id: Session ID for browser context
        browsing_goal: What we're trying to accomplish
        llm_url, llm_model, llm_api_key: LLM config

    Returns:
        Same format as initial page result or None if navigation failed
    """
    from apps.services.tool_server import web_vision_mcp
    from apps.services.tool_server.content_sanitizer import ContentSanitizer

    logger.info(
        f"[BrowserAgent] Navigating: {current_url[:40]}... → {next_url[:40]}... "
        f"(type={navigation_type})"
    )

    try:
        # Navigate using Web Vision
        await web_vision_mcp.navigate(
            session_id=session_id,
            url=next_url,
            wait_for="networkidle"
        )

        # Capture content (used for both relevance check and extraction)
        # NOTE: Removed get_screen_state() - expensive DOM extraction not needed for relevance check
        content_result = await web_vision_mcp.capture_content(
            session_id=session_id,
            format="markdown"
        )

        # Check relevance using captured content
        page_title = content_result.get("title", "Unknown")
        content_preview = content_result.get("content", "")[:500]
        page_state = f"Title: {page_title}\nURL: {next_url}\n\nContent preview:\n{content_preview}"

        is_relevant = await _check_relevance_llm(
            page_state=page_state,
            goal=browsing_goal,
            llm_url=llm_url,
            llm_model=llm_model,
            llm_api_key=llm_api_key
        )

        if not is_relevant:
            logger.info(f"[BrowserAgent] Page not relevant: {next_url[:60]}")
            return None

        # Sanitize
        sanitizer = ContentSanitizer()
        sanitized = sanitizer.sanitize(content_result["content"], next_url)

        # Reconstruct clean_text from chunks
        if "chunks" in sanitized and sanitized["chunks"]:
            clean_text = "\n\n".join(chunk["text"] for chunk in sanitized["chunks"])
        else:
            # Fallback: use raw content if sanitizer failed
            clean_text = content_result["content"]
            logger.warning(f"[BrowserAgent] No chunks from sanitizer, using raw content ({len(clean_text)} chars)")

        # Create page result
        return {
            "url": next_url,
            "text_content": clean_text,
            "extracted_info": _basic_extraction(clean_text, browsing_goal),
            "relevance_score": 0.8,
            "summary": clean_text[:500] + "..." if len(clean_text) > 500 else clean_text,
            "key_points": [],
            "page_type": "unknown",
            "metadata": {
                "sanitization": sanitized.get("stats", {}),
                "page_info": content_result.get("page_info", {})
            }
        }

    except Exception as e:
        logger.error(f"[BrowserAgent] Navigation failed to {next_url[:60]}: {e}")
        return None


async def aggregate_multi_page_results(
    pages: List[Dict],
    browsing_goal: str,
    llm_url: str = None,
    llm_model: str = None,
    llm_api_key: str = None
) -> Dict[str, Any]:
    """
    Aggregate extractions from multiple pages into unified result.

    Combines:
    - Products from all pages (deduplicated)
    - Information from all pages (consolidated)
    - Provenance (which page each piece came from)
    - Summary across all pages

    Args:
        pages: List of page visit results
        browsing_goal: What we were trying to accomplish
        llm_url, llm_model, llm_api_key: LLM config

    Returns:
        {
            "extracted_info": Dict,  # Aggregated extraction with deduplication
            "summary": str,  # Overall summary of all pages
            "key_points": List[str],  # Combined key points
            "combined_text": str,  # All clean text concatenated
            "metadata": {
                "pages_aggregated": int,
                "total_items": int,  # Total products/entries found
                "unique_items": int,  # After deduplication
                "provenance": Dict[str, str]  # item_id -> source_url mapping
            }
        }
    """
    import os

    # Get LLM config
    if not llm_url:
        llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    if not pages:
        return {
            "extracted_info": {},
            "summary": "No pages to aggregate",
            "key_points": [],
            "combined_text": "",
            "metadata": {"pages_aggregated": 0, "total_items": 0, "unique_items": 0, "provenance": {}}
        }

    # Collect all products/items from all pages
    all_items = []
    provenance = {}  # item_id -> source_url

    for page in pages:
        page_url = page.get("url", "")
        extracted = page.get("extracted_info", {})

        # Extract products if present
        products = extracted.get("products", [])
        if isinstance(products, list):
            for product in products:
                if isinstance(product, dict):
                    # Track provenance
                    item_id = product.get("name", product.get("title", "")).lower().strip()
                    if item_id:
                        all_items.append(product)
                        if item_id not in provenance:
                            provenance[item_id] = page_url

    # Deduplicate items
    unique_items = _deduplicate_items(all_items, key_field="name")

    # Combine all summaries and key points
    all_summaries = [p.get("summary", "") for p in pages if p.get("summary")]
    all_key_points = []
    for p in pages:
        points = p.get("key_points", [])
        if isinstance(points, list):
            all_key_points.extend(points)

    # Combine all text content (sanitized)
    combined_text = "\n\n---\n\n".join([
        f"Page {i+1} ({p.get('url', '')}):\n{p.get('text_content', '')}"
        for i, p in enumerate(pages)
        if p.get("text_content")
    ])

    # Load prompt and build context
    base_prompt = _load_browser_prompt("multi_page_synth")
    if not base_prompt:
        # Fallback if prompt file not found
        base_prompt = "Synthesize multi-page information. Return JSON with summary, key_findings, confidence."

    prompt = f"""{base_prompt}

## Current Synthesis Task

**Goal:** {browsing_goal}

**Summaries from individual pages:**
{chr(10).join(f"{i+1}. {s[:300]}" for i, s in enumerate(all_summaries))}

**Total items found:** {len(all_items)} (unique: {len(unique_items)})

IMPORTANT: Return ONLY valid JSON, no other text before or after."""

    try:
        llm_result = await call_llm_json(prompt, llm_url, llm_model, llm_api_key, max_tokens=500)

        summary = llm_result.get("summary", f"Aggregated information from {len(pages)} pages")
        key_findings = llm_result.get("key_findings", all_key_points[:5])

    except Exception as e:
        logger.warning(f"[BrowserAgent] LLM aggregation failed: {e}, using simple concatenation")

        summary = f"Information from {len(pages)} pages. {all_summaries[0][:200] if all_summaries else ''}"
        key_findings = all_key_points[:5]

    return {
        "extracted_info": {
            "products": unique_items,
            "total_items": len(all_items),
            "unique_items": len(unique_items),
            "aggregated_from_pages": len(pages)
        },
        "summary": summary,
        "key_points": key_findings,
        "combined_text": combined_text,
        "metadata": {
            "pages_aggregated": len(pages),
            "total_items": len(all_items),
            "unique_items": len(unique_items),
            "provenance": provenance
        }
    }


async def should_continue_browsing(
    pages_visited: List[Dict],
    browsing_goal: str,
    max_pages: int,
    llm_url: str = None,
    llm_model: str = None,
    llm_api_key: str = None
) -> Dict[str, Any]:
    """
    Decide if we should continue browsing more pages using LLM evaluation.

    Evaluates after EACH page:
    - Did this page add new information? (new_info_score)
    - Have we met the goal? (goal_satisfaction)
    - Are we seeing diminishing returns?

    Args:
        pages_visited: Pages visited so far
        browsing_goal: What we're trying to accomplish
        max_pages: Maximum pages allowed
        llm_url, llm_model, llm_api_key: LLM config

    Returns:
        {
            "continue": bool,
            "reason": str,
            "confidence": float,  # 0.0-1.0
            "new_info_score": float,  # 0.0-1.0 (how much new info last page added)
            "goal_satisfaction": float  # 0.0-1.0 (how well we've met the goal)
        }
    """
    import os

    # Hard limit check
    if len(pages_visited) >= max_pages:
        return {
            "continue": False,
            "reason": f"Max pages limit reached ({max_pages})",
            "confidence": 1.0,
            "new_info_score": 0.0,
            "goal_satisfaction": 1.0
        }

    # Need at least 2 pages to compare
    if len(pages_visited) < 2:
        return {
            "continue": True,
            "reason": "Need more pages for comparison",
            "confidence": 0.8,
            "new_info_score": 1.0,
            "goal_satisfaction": 0.0
        }

    # Get LLM config
    if not llm_url:
        llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    # Build context
    last_page = pages_visited[-1]
    previous_pages = pages_visited[:-1]

    # Summarize what we learned from previous pages (last 3 for context)
    previous_summaries = [p.get("summary", "") for p in previous_pages[-3:]]
    previous_info = "\n".join(f"Page {i+1}: {s[:200]}" for i, s in enumerate(previous_summaries))

    # What we learned from the last page
    last_page_summary = last_page.get("summary", "")
    last_page_items = len(last_page.get("extracted_info", {}).get("products", []))

    # Count total items so far
    total_items = sum(
        len(p.get("extracted_info", {}).get("products", []))
        for p in pages_visited
    )

    # Load prompt and build context
    base_prompt = _load_browser_prompt("continuation")
    if not base_prompt:
        # Fallback if prompt file not found
        base_prompt = "Evaluate whether to continue browsing. Return JSON with continue, reason, confidence, new_info_score, goal_satisfaction."

    prompt = f"""{base_prompt}

## Current Browsing State

**Goal:** {browsing_goal}

**Pages visited so far:** {len(pages_visited)}

**What we learned from previous pages:**
{previous_info}

**What we learned from the LAST page (Page {len(pages_visited)}):**
{last_page_summary[:300]}

**Statistics:**
- Total items/products found so far: {total_items}
- Items from last page: {last_page_items}

IMPORTANT: Return ONLY valid JSON, no other text before or after."""

    try:
        result = await call_llm_json(prompt, llm_url, llm_model, llm_api_key, max_tokens=300)

        # Safety check: if new info score is very low, override to stop
        if result.get("new_info_score", 1.0) < 0.3 and len(pages_visited) >= 3:
            logger.info(
                f"[BrowserAgent] Low new info score ({result['new_info_score']:.2f}), "
                f"overriding to stop"
            )
            result["continue"] = False
            result["reason"] = (
                f"Diminishing returns: last page only {result['new_info_score']:.0%} new information"
            )

        logger.debug(
            f"[BrowserAgent] LLM evaluation: continue={result['continue']}, "
            f"new_info={result.get('new_info_score', 0):.2f}, "
            f"goal_satisfaction={result.get('goal_satisfaction', 0):.2f}"
        )

        return result

    except Exception as e:
        logger.warning(f"[BrowserAgent] LLM evaluation failed: {e}, defaulting to continue")

        return {
            "continue": True,
            "reason": "LLM evaluation failed, continuing cautiously",
            "confidence": 0.5,
            "new_info_score": 0.5,
            "goal_satisfaction": 0.3
        }


# ============================================================================
# Helper Functions
# ============================================================================

async def _check_relevance_llm(
    page_state: str,
    goal: str,
    llm_url: str = None,
    llm_model: str = None,
    llm_api_key: str = None
) -> bool:
    """
    Use LLM to check if page is relevant to browsing goal.

    Args:
        page_state: Compact text description of page (~300 tokens)
        goal: What we're trying to accomplish

    Returns:
        bool: True if page is relevant to goal
    """
    import os

    if not llm_url:
        llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    # Load prompt and build context
    base_prompt = _load_browser_prompt("relevance_checker")
    if not base_prompt:
        # Fallback if prompt file not found
        base_prompt = "Evaluate if page is relevant to goal. Answer yes or no."

    prompt = f"""{base_prompt}

## Page State

{page_state}

## Browsing Goal

{goal}"""

    try:
        # Use text function since we expect plain text "yes" or "no"
        response = await call_llm_text(prompt, llm_url, llm_model, llm_api_key, max_tokens=10)
        return "yes" in response.lower()
    except Exception as e:
        logger.warning(f"[BrowserAgent] Relevance check failed: {e}, assuming relevant")
        return True  # Default to relevant if check fails


def _basic_extraction(text: str, goal: str) -> Dict[str, Any]:
    """
    Basic extraction of products/items from text.

    This is a simple fallback - in production you'd want more sophisticated extraction.

    Args:
        text: Clean text content
        goal: Browsing goal for context

    Returns:
        {
            "products": List[Dict],  # Extracted products/items
            "extraction_method": str  # How extraction was performed
        }
    """
    # Very basic extraction - just return text chunks as "products"
    # In production, this would use NER, structured extraction, etc.

    lines = [line.strip() for line in text.split('\n') if line.strip()]
    products = []

    for i, line in enumerate(lines[:20]):  # Max 20 items
        if len(line) > 20:  # Skip short lines
            products.append({
                "name": line[:100],
                "description": line,
                "source_line": i + 1
            })

    return {
        "products": products,
        "extraction_method": "basic_text_chunking"
    }


def _extract_pagination_links(soup: BeautifulSoup, current_url: str) -> Dict[str, Any]:
    """
    Extract pagination links using pattern matching.

    Looks for:
    - "Next" links (text: Next, next page, », →, older, more)
    - Numbered page links (1, 2, 3...)
    - URL patterns (page=N, /page/N/)

    Returns:
        {
            "next_page_url": str or None,
            "page_links": List[str],  # All numbered page URLs
            "page_numbers": List[int]  # Detected page numbers
        }
    """
    pagination_info = {
        "next_page_url": None,
        "page_links": [],
        "page_numbers": []
    }

    # Look for "Next" link (various forms)
    next_patterns = ["next", "next page", "»", "→", "older", "more", "continue"]

    for a in soup.find_all('a', href=True):
        link_text = a.get_text(strip=True).lower()
        if any(pattern in link_text for pattern in next_patterns):
            next_url = urljoin(current_url, a['href'])
            pagination_info["next_page_url"] = next_url
            break

    # Look for numbered page links
    for a in soup.find_all('a', href=True):
        link_text = a.get_text(strip=True)
        # Check if text is a number
        if link_text.isdigit():
            page_num = int(link_text)
            page_url = urljoin(current_url, a['href'])
            pagination_info["page_links"].append(page_url)
            pagination_info["page_numbers"].append(page_num)

    # Look for page=N in current URL to generate next page
    if not pagination_info["next_page_url"] and "page=" in current_url:
        match = re.search(r'page=(\d+)', current_url)
        if match:
            current_page = int(match.group(1))
            next_page_url = re.sub(r'page=\d+', f'page={current_page + 1}', current_url)
            pagination_info["next_page_url"] = next_page_url

    # Look for /page/N/ pattern
    if not pagination_info["next_page_url"] and "/page/" in current_url:
        match = re.search(r'/page/(\d+)', current_url)
        if match:
            current_page = int(match.group(1))
            next_page_url = re.sub(r'/page/\d+', f'/page/{current_page + 1}', current_url)
            pagination_info["next_page_url"] = next_page_url

    return pagination_info


def _extract_category_links(soup: BeautifulSoup, current_url: str) -> List[str]:
    """
    Extract category navigation links.

    Looks for common category patterns:
    - /available, /retired, /upcoming, /sold
    - /category/*, /catalog/*, /inventory/*

    Returns:
        List of category URLs (up to 10)
    """
    category_links = []
    category_patterns = [
        r'/available',
        r'/retired',
        r'/upcoming',
        r'/sold',
        r'/category/',
        r'/catalog',
        r'/inventory',
        r'/listings'
    ]

    for a in soup.find_all('a', href=True):
        href = a['href']
        abs_url = urljoin(current_url, href)

        for pattern in category_patterns:
            if re.search(pattern, abs_url.lower()):
                if abs_url not in category_links:
                    category_links.append(abs_url)

    return category_links[:10]  # Limit to 10 categories


def _deduplicate_items(items: List[Dict], key_field: str = "name") -> List[Dict]:
    """
    Deduplicate items across pages using fuzzy matching on key field.

    Args:
        items: List of item dicts
        key_field: Field to use for matching (default: "name")

    Returns:
        List of unique items
    """
    if not items:
        return []

    seen_keys = set()
    unique_items = []

    for item in items:
        if not isinstance(item, dict):
            continue

        # Get key for this item (try multiple field names)
        key = item.get(key_field) or item.get("title") or item.get("id")

        if not key:
            # No identifiable key, keep item
            unique_items.append(item)
            continue

        # Normalize key for comparison
        # Remove punctuation, extra whitespace, convert to lowercase
        normalized_key = str(key).lower().strip()
        # Remove punctuation and normalize whitespace
        normalized_key = re.sub(r'[^\w\s]', '', normalized_key)  # Remove punctuation
        normalized_key = re.sub(r'\s+', ' ', normalized_key)  # Normalize whitespace
        normalized_key = normalized_key.strip()

        if normalized_key not in seen_keys:
            seen_keys.add(normalized_key)
            unique_items.append(item)

    return unique_items


def _check_content_similarity(new_page: Dict, previous_pages: List[Dict]) -> float:
    """
    Quick similarity check using embeddings to detect duplicate content.

    Args:
        new_page: New page result
        previous_pages: Previously visited pages

    Returns:
        0.0-1.0 (0 = totally different, 1 = exact duplicate)
    """
    try:
        from apps.services.tool_server.shared_state.embedding_service import EMBEDDING_SERVICE

        new_summary = new_page.get("summary", "")
        if not new_summary:
            return 0.0

        new_embedding = EMBEDDING_SERVICE.embed(new_summary)
        if new_embedding is None:
            return 0.0

        # Compare with last 3 pages
        similarities = []
        for prev_page in previous_pages[-3:]:
            prev_summary = prev_page.get("summary", "")
            if not prev_summary:
                continue

            prev_embedding = EMBEDDING_SERVICE.embed(prev_summary)
            if prev_embedding is None:
                continue

            sim = EMBEDDING_SERVICE.cosine_similarity(new_embedding, prev_embedding)
            similarities.append(sim)

        # Return max similarity (how similar to most similar previous page)
        return max(similarities) if similarities else 0.0

    except Exception as e:
        logger.debug(f"[BrowserAgent] Similarity check failed: {e}")
        return 0.0  # Assume different if check fails
