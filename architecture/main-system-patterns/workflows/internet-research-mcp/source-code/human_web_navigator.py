"""
orchestrator/human_web_navigator.py

DEPRECATED (2025-11-29): Use web_mcp.py instead.

This module is kept for backward compatibility with:
- research_orchestrator.py (_call_llm utility)
- vendor_deep_crawler.py (visit_and_read)

New code should use:
    from orchestrator.web_mcp import web_navigate, web_extract

The unified web_mcp.py provides:
- Single entry point for ALL web operations
- Proactive schema learning
- Unified SmartPageWaiter

Migration:
    OLD: visit_and_read(url, page, ...)
    NEW: await web_navigate(url, extract=True)

NOTE: _call_llm() utility function still used internally.
      Will be extracted to shared utilities in future refactor.

Created: 2025-11-15
Deprecated: 2025-11-29 (replaced by web_mcp.py)
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import aiohttp
from orchestrator.content_sanitizer import ContentSanitizer
from orchestrator.shared import call_llm_json

logger = logging.getLogger(__name__)

# Initialize content sanitizer (reusable instance)
_content_sanitizer = ContentSanitizer()

# Prompt loading infrastructure
_PROMPT_DIR = Path(__file__).parent.parent / "apps" / "prompts" / "navigation"
_prompt_cache: Dict[str, str] = {}


def _load_navigation_prompt(prompt_name: str) -> str:
    """Load navigation prompt from file with caching."""
    if prompt_name in _prompt_cache:
        return _prompt_cache[prompt_name]

    prompt_path = _PROMPT_DIR / f"{prompt_name}.md"
    if prompt_path.exists():
        content = prompt_path.read_text()
        _prompt_cache[prompt_name] = content
        return content

    logger.warning(f"[HumanNavigator] Prompt file not found: {prompt_path}")
    return ""  # Fallback to empty string - caller should handle


async def visit_and_read(
    url: str,
    reading_goal: str,
    extraction_template: Optional[Dict] = None,
    context: Optional[Any] = None,
    session_id: str = "default",
    event_emitter: Optional[Any] = None,
    human_assist_allowed: bool = True,  # Default: enabled
    llm_url: str = None,
    llm_model: str = None,
    llm_api_key: str = None
) -> Optional[Dict[str, Any]]:
    """
    Visit a URL and read it like a human would.

    Args:
        url: Where to go
        reading_goal: What we're looking for (e.g., "product information", "research findings")
        extraction_template: Optional hint about what structure to extract
        context: Browser context (for cookie persistence)
        session_id: Session ID for tracking (enables CAPTCHA intervention)
        event_emitter: For progress updates (optional)
        llm_url: LLM endpoint (default from env)
        llm_model: LLM model ID (default from env)
        llm_api_key: LLM API key (default from env)

    Returns:
        {
            "url": "...",
            "page_type": "product_listing|forum_discussion|research_paper|...",
            "relevance_score": 0.85,
            "extracted_info": {...},
            "summary": "Brief summary of what we found",
            "key_points": ["Point 1", "Point 2", ...],
            "metadata": {...}
        }

        Returns None if page not relevant or failed to fetch.
    """

    # Get LLM config from environment if not provided
    if not llm_url:
        import os
        llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    # Step 1: Visit the page (with intervention support)
    if event_emitter:
        await event_emitter.emit("progress", {"step": "fetch", "url": url, "message": f"Fetching {url[:60]}..."})

    fetch_result = await _fetch_with_intervention(
        url=url,
        context=context,
        session_id=session_id,
        event_emitter=event_emitter,
        human_assist_allowed=human_assist_allowed
    )

    if not fetch_result.get("success"):
        logger.warning(f"[HumanNavigator] Failed to fetch {url[:60]}")
        if event_emitter:
            await event_emitter.emit("progress", {"step": "fetch_failed", "url": url, "message": f"Failed to fetch {url[:60]}"})
        return None

    # Step 1.5: Sanitize content before LLM processing
    raw_html = fetch_result.get("raw_html", "")
    if not raw_html:
        # Fallback to text_content if raw_html not available
        text_content = fetch_result.get("text_content", "")
        if not text_content or len(text_content) < 100:
            logger.warning(f"[HumanNavigator] Empty or too short content from {url[:60]}")
            if event_emitter:
                await event_emitter.emit("progress", {"step": "content_empty", "url": url, "message": "Page content too short"})
            return None
        sanitization_metadata = {"used_raw_html": False, "reduction_pct": 0}
    else:
        # Sanitize HTML to remove scripts, ads, navigation, etc.
        if event_emitter:
            await event_emitter.emit("progress", {"step": "sanitize", "url": url, "message": "Cleaning page content..."})

        try:
            sanitized_result = _content_sanitizer.sanitize(
                html=raw_html,
                url=url,
                max_tokens=2000,  # Per-chunk limit
                chunk_strategy="smart"
            )

            # Use first chunk (most pages fit in one chunk after sanitization)
            if sanitized_result["chunks"]:
                text_content = sanitized_result["chunks"][0]["text"]
                sanitization_metadata = {
                    "used_raw_html": True,
                    "reduction_pct": sanitized_result["reduction_pct"],
                    "original_size": sanitized_result["original_size"],
                    "sanitized_size": sanitized_result["sanitized_size"],
                    "chunks_created": len(sanitized_result["chunks"]),
                    "metadata": sanitized_result["metadata"]
                }

                logger.info(
                    f"[HumanNavigator] Content sanitized: {sanitization_metadata['reduction_pct']:.1f}% reduction "
                    f"({sanitization_metadata['original_size']} → {sanitization_metadata['sanitized_size']} chars)"
                )
            else:
                # Sanitizer returned empty - fallback to text_content
                text_content = fetch_result.get("text_content", "")
                sanitization_metadata = {"used_raw_html": False, "sanitization_failed": True}
                logger.warning(f"[HumanNavigator] Sanitization returned empty, using fallback text_content")

        except Exception as sanitize_error:
            logger.error(f"[HumanNavigator] Sanitization error: {sanitize_error}", exc_info=True)
            # Fallback to original text_content
            text_content = fetch_result.get("text_content", "")
            sanitization_metadata = {"used_raw_html": False, "sanitization_error": str(sanitize_error)}

    if not text_content or len(text_content) < 100:
        logger.warning(f"[HumanNavigator] Empty or too short content after sanitization from {url[:60]}")
        if event_emitter:
            await event_emitter.emit("progress", {"step": "content_empty", "url": url, "message": "Page content too short"})
        return None

    # Step 2: Quick scan - Is this page relevant?
    if event_emitter:
        await event_emitter.emit("progress", {"step": "scan", "url": url, "message": "Scanning for relevance..."})

    scan_result = await _scan_for_relevance(
        text=text_content,
        url=url,
        goal=reading_goal,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key
    )

    if scan_result["relevance_score"] < 0.3:
        logger.info(
            f"[HumanNavigator] Page not relevant (score={scan_result['relevance_score']:.2f}): "
            f"{url[:60]} - {scan_result['reason']}"
        )
        if event_emitter:
            await event_emitter.emit("progress", {
                "step": "not_relevant",
                "url": url,
                "message": f"Not relevant (score={scan_result['relevance_score']:.2f}): {scan_result['reason']}"
            })
        return None

    # Step 3: Detect page type automatically
    if event_emitter:
        await event_emitter.emit("progress", {"step": "detect_type", "url": url, "message": "Detecting page type..."})

    page_type = _detect_page_type(text_content, url)
    logger.info(f"[HumanNavigator] Detected page type: {page_type} for {url[:60]}")

    if event_emitter:
        await event_emitter.emit("progress", {"step": "type_detected", "url": url, "message": f"Page type: {page_type}"})

    # Step 4: Read and extract based on what we found
    if event_emitter:
        await event_emitter.emit("progress", {"step": "extract", "url": url, "message": f"Extracting {page_type} data..."})

    extracted = await _read_and_extract(
        text=text_content,
        url=url,
        goal=reading_goal,
        page_type=page_type,
        template_hint=extraction_template,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key
    )

    # Step 5: Validate what we extracted
    if event_emitter:
        await event_emitter.emit("progress", {"step": "validate", "url": url, "message": "Validating extraction..."})

    validated = await _validate_extraction(
        extracted=extracted,
        url=url,
        goal=reading_goal,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key
    )

    if event_emitter:
        await event_emitter.emit("progress", {
            "step": "complete",
            "url": url,
            "message": f"Extracted from {page_type} page (confidence={validated['confidence']:.2f})"
        })

    return {
        "url": url,
        "page_type": page_type,
        "relevance_score": scan_result["relevance_score"],
        "extracted_info": validated["data"],
        "summary": validated["summary"],
        "key_points": validated["key_points"],
        "text_content": text_content,  # Include sanitized content for reuse (e.g., by browser_agent)
        "metadata": {
            "confidence": validated["confidence"],
            "validation_passed": validated["is_valid"],
            "sanitization": sanitization_metadata  # Include sanitization stats
        }
    }


async def _fetch_with_intervention(
    url: str,
    context: Optional[Any],
    session_id: str,
    event_emitter: Optional[Any] = None,
    human_assist_allowed: bool = True,  # Default: enabled
    max_retries: int = 2
) -> Dict[str, Any]:
    """
    Fetch URL with human intervention support for CAPTCHAs.

    Uses captcha_intervention.request_intervention() to create global
    intervention requests that UI can poll and resolve.

    Cookie persistence: Automatically uses crawler_session_manager to persist
    cookies/localStorage across interventions and future visits.
    """
    from orchestrator import playwright_stealth_mcp
    from orchestrator.captcha_intervention import detect_blocker, request_intervention
    from orchestrator.crawler_session_manager import get_crawler_session_manager
    from urllib.parse import urlparse

    # Get or create persistent browser context for this domain
    domain = urlparse(url).netloc
    logger.info(f"[HumanNavigator-DEBUG] context={context}, domain={domain}, session_id={session_id}")
    if not context:
        logger.info(f"[HumanNavigator-DEBUG] Context is None, loading session from disk...")
        session_mgr = get_crawler_session_manager()
        context = await session_mgr.get_or_create_session(
            domain=domain,
            session_id=session_id
        )
        logger.info(f"[HumanNavigator] Using persistent session for {domain} (session={session_id})")
    else:
        logger.info(f"[HumanNavigator-DEBUG] Context was provided, skipping session load")

    for attempt in range(max_retries):
        # Fetch the page
        fetch_result = await playwright_stealth_mcp.fetch(
            url=url,
            strategy="auto",
            use_stealth=True,
            timeout=30,
            wait_until="load",
            context=context
        )

        # Check for blockers - BUT only if fetch actually failed
        # If fetch succeeded with valid cookies, don't trigger intervention
        blocker = None
        raw_html = fetch_result.get("raw_html")
        blocked_flag = fetch_result.get("blocked", False)
        fetch_succeeded = fetch_result.get("success", False)

        # Skip blocker detection if fetch succeeded (cookies worked!)
        if fetch_succeeded and not blocked_flag:
            logger.info(
                f"[HumanNavigator] Fetch succeeded with valid session: {url[:60]} "
                f"(skipping blocker detection)"
            )
            # Don't check for blockers - page is accessible
        else:
            # Check for blockers only if fetch failed OR explicit block flag
            if raw_html or blocked_flag:
                blocker = detect_blocker({
                    "content": raw_html or "",
                    "status": fetch_result.get("status", 0),
                    "url": url,
                    "screenshot_path": fetch_result.get("screenshot_path"),
                    "blocked": blocked_flag,
                    "block_type": fetch_result.get("block_type", "")
                })

            if blocker and blocker["confidence"] >= 0.7:
                logger.warning(
                    f"[HumanNavigator] Blocker detected: {blocker['type'].value} "
                    f"on {url[:60]} (human_assist={'enabled' if human_assist_allowed else 'disabled'})"
                )

                if event_emitter:
                    await event_emitter.emit("progress", {
                        "step": "blocker_detected",
                        "url": url,
                        "message": f"Blocker detected: {blocker['type'].value}"
                    })

                # Only request intervention if human assist is enabled
                if not human_assist_allowed:
                    logger.info(f"[HumanNavigator] Human assist disabled, failing page: {url[:60]}")
                    return {
                        "success": False,
                        "error": f"Blocked by {blocker['type'].value} (human assist not allowed)",
                        "blocker_type": blocker['type'].value
                    }

                if attempt < max_retries - 1:
                    # Request human intervention (registered globally)
                    if event_emitter:
                        await event_emitter.emit("progress", {
                            "step": "requesting_intervention",
                            "url": url,
                            "message": f"Requesting help to solve {blocker['type'].value}..."
                        })

                    intervention = await request_intervention(
                        blocker_type=blocker["type"].value,
                        url=url,
                        screenshot_path=fetch_result.get("screenshot_path"),
                        session_id=session_id,
                        blocker_details=blocker
                    )

                    # Create browser stream for remote interaction
                    # User can now see and control server's browser from their phone/laptop
                    stream_page = None
                    stream = None
                    try:
                        from orchestrator.browser_stream_manager import get_browser_stream_manager

                        # Create a dedicated page for this intervention
                        stream_page = await context.new_page()
                        logger.info(
                            f"[HumanNavigator] Created stream page for intervention: {intervention.intervention_id}"
                        )

                        # Navigate to the blocked URL
                        try:
                            await stream_page.goto(url, wait_until="load", timeout=30000)
                        except Exception as nav_error:
                            logger.warning(
                                f"[HumanNavigator] Navigation error (expected for blocked pages): {nav_error}"
                            )
                            # Continue anyway - CAPTCHA/blocker page should be visible

                        # Create and start browser stream
                        stream_manager = get_browser_stream_manager()
                        stream = await stream_manager.create_stream(
                            stream_id=intervention.intervention_id,
                            page=stream_page,
                            fps=2
                        )

                        logger.info(
                            f"[HumanNavigator] Browser stream created: {intervention.intervention_id} "
                            f"(user can interact remotely)"
                        )

                    except Exception as stream_error:
                        logger.error(
                            f"[HumanNavigator] Error creating browser stream: {stream_error}",
                            exc_info=True
                        )
                        # Continue with intervention even if streaming fails
                        # User can still use fallback "Open in New Tab" option

                    # Emit intervention_needed event for research monitor panel
                    if event_emitter:
                        await event_emitter.emit("intervention_needed", {
                            "intervention_id": intervention.intervention_id,
                            "url": url,
                            "blocker_type": blocker["type"].value,
                            "screenshot_path": fetch_result.get("screenshot_path")
                        })

                        await event_emitter.emit("progress", {
                            "step": "waiting_for_intervention",
                            "url": url,
                            "message": "Waiting for you to solve the blocker..."
                        })

                    # Wait for user resolution (90 second timeout)
                    resolved = await intervention.wait_for_resolution(timeout=180)

                    # Clean up browser stream
                    try:
                        if stream:
                            await stream_manager.stop_stream(intervention.intervention_id)
                            logger.info(
                                f"[HumanNavigator] Browser stream stopped: {intervention.intervention_id}"
                            )
                        if stream_page:
                            await stream_page.close()
                            logger.info(
                                f"[HumanNavigator] Stream page closed: {intervention.intervention_id}"
                            )
                    except Exception as cleanup_error:
                        logger.error(
                            f"[HumanNavigator] Error cleaning up stream: {cleanup_error}",
                            exc_info=True
                        )

                    if resolved:
                        logger.info(f"[HumanNavigator] Intervention resolved, retrying {url[:60]}")

                        session_mgr = get_crawler_session_manager()

                        # Inject cookies from user's browser if provided
                        if intervention.resolved_cookies:
                            logger.info(
                                f"[HumanNavigator] Injecting {len(intervention.resolved_cookies)} cookies "
                                f"from user's browser"
                            )
                            await session_mgr.inject_cookies(
                                domain=domain,
                                session_id=session_id,
                                cookies=intervention.resolved_cookies
                            )
                        else:
                            logger.warning(
                                f"[HumanNavigator] No cookies provided by user. "
                                f"If using manual resolution, cookies should be pasted in research monitor. "
                                f"If using CDP, cookies should be automatic."
                            )

                        # Save session state to disk for permanent persistence
                        # This now includes any injected cookies
                        await session_mgr.save_session_state(
                            domain=domain,
                            session_id=session_id,
                            context=context
                        )
                        logger.info(f"[HumanNavigator] Saved cookies/session to disk for {domain}")

                        if event_emitter:
                            await event_emitter.emit("progress", {
                                "step": "intervention_resolved",
                                "url": url,
                                "message": "Blocker solved! Cookies saved. Retrying..."
                            })
                        continue
                    else:
                        logger.warning(f"[HumanNavigator] Intervention timeout for {url[:60]}")
                        if event_emitter:
                            await event_emitter.emit("progress", {
                                "step": "intervention_timeout",
                                "url": url,
                                "message": "Intervention timeout - moving on"
                            })
                        return fetch_result
                else:
                    # Last retry - skip blocker
                    if event_emitter:
                        await event_emitter.emit("progress", {
                            "step": "blocker_skipped",
                            "url": url,
                            "message": "Blocker detected on final retry - skipping"
                        })
                    return fetch_result

        # Success - save session state for cookie persistence
        if fetch_result.get("success"):
            session_mgr = get_crawler_session_manager()
            await session_mgr.save_session_state(
                domain=domain,
                session_id=session_id,
                context=context
            )
            logger.info(f"[HumanNavigator] Saved session state after successful fetch: {domain}")

        return fetch_result

    return fetch_result


async def _scan_for_relevance(
    text: str,
    url: str,
    goal: str,
    llm_url: str,
    llm_model: str,
    llm_api_key: str
) -> Dict[str, Any]:
    """
    Quick scan: Is this page worth reading?

    Like a human quickly skimming to see if it's useful.
    Uses ~200 tokens - very cheap.
    """
    # Take first 2000 chars + last 1000 chars
    preview = text[:2000]
    if len(text) > 3000:
        preview += "\n\n[...]\n\n" + text[-1000:]

    # Load prompt template from file
    prompt_template = _load_navigation_prompt("relevance_scan")
    if prompt_template:
        prompt = prompt_template.format(url=url, goal=goal, preview=preview)
    else:
        # Fallback inline prompt if file not found
        prompt = f"""You are quickly scanning a webpage to see if it's relevant.

URL: {url}
GOAL: {goal}

PAGE PREVIEW:
{preview}

Task: Is this page relevant for the goal? Answer in JSON:
{{
  "relevance_score": 0.0-1.0,
  "reason": "why relevant or not relevant",
  "page_seems_to_be": "product listing|forum discussion|research paper|news article|guide|general",
  "key_topics_spotted": ["topic1", "topic2"]
}}

Be quick and decisive. We're just checking if it's worth reading fully."""

    result = await call_llm_json(prompt, llm_url, llm_model, llm_api_key, max_tokens=200)
    return result


def _detect_page_type(text: str, url: str) -> str:
    """
    Automatically detect what kind of page this is.

    We don't need to know the site name - just read the structure.

    Types detected:
    - product_listing: Has prices, "add to cart", product specs
    - forum_discussion: Has posts, replies, user mentions
    - research_paper: Has abstract, citations, methodology
    - news_article: Has dateline, byline, article structure
    - guide_tutorial: Has steps, instructions, examples
    - vendor_directory: Has multiple vendor listings
    - general: Doesn't fit other patterns
    """

    text_lower = text.lower()

    # Product listing indicators
    if any(x in text_lower for x in ["add to cart", "buy now", "in stock", "out of stock"]):
        if any(x in text_lower for x in ["$", "price:", "€", "£"]):
            return "product_listing"

    # Forum discussion indicators
    if any(x in text_lower for x in ["posted by", "reply", "quote", "joined:", "posts:"]):
        if text_lower.count("posted") > 3 or text_lower.count("reply") > 3:
            return "forum_discussion"

    # Research paper indicators
    if any(x in text_lower for x in ["abstract:", "introduction", "methodology", "results", "discussion", "references"]):
        if "doi:" in text_lower or "arxiv" in url or "pubmed" in url:
            return "research_paper"

    # News article indicators
    if any(x in text_lower for x in ["published:", "updated:", "reporter", "correspondent"]):
        if len([x for x in text.split('\n') if len(x) > 100]) > 5:  # Has paragraphs
            return "news_article"

    # Guide/tutorial indicators
    if text_lower.count("step ") > 2 or text_lower.count("how to") > 1:
        return "guide_tutorial"

    # Vendor directory indicators
    if text_lower.count("breeder") > 5 or text_lower.count("store") > 5:
        if text_lower.count("contact") > 3 or text_lower.count("location") > 3:
            return "vendor_directory"

    return "general"


async def _read_and_extract(
    text: str,
    url: str,
    goal: str,
    page_type: str,
    template_hint: Optional[Dict],
    llm_url: str,
    llm_model: str,
    llm_api_key: str
) -> Dict[str, Any]:
    """
    Read the page and extract relevant information.

    ADAPTIVE: Extraction adapts to page type, but uses the SAME reading process.
    """

    # Chunk the content intelligently (take first 7000 chars for now)
    content = text[:7000]

    # Build adaptive prompt based on page type and goal
    extraction_prompt = _build_extraction_prompt(
        goal=goal,
        page_type=page_type,
        template_hint=template_hint
    )

    # Load prompt template from file
    prompt_template = _load_navigation_prompt("page_reader")
    if prompt_template:
        prompt = prompt_template.format(
            url=url,
            page_type=page_type,
            goal=goal,
            content=content,
            extraction_prompt=extraction_prompt
        )
    else:
        # Fallback inline prompt if file not found
        prompt = f"""You are reading a webpage to extract useful information.

URL: {url}
PAGE TYPE: {page_type}
READING GOAL: {goal}

CONTENT:
{content}

{extraction_prompt}

Extract information as JSON. Be thorough but only extract what's actually present.

IMPORTANT: If extracting products, limit to the TOP 10 most relevant products to avoid truncation."""

    result = await call_llm_json(prompt, llm_url, llm_model, llm_api_key, max_tokens=3000)
    return result


def _build_extraction_prompt(
    goal: str,
    page_type: str,
    template_hint: Optional[Dict] = None
) -> str:
    """
    Build extraction instructions based on what we're looking for and what we found.

    This is where the intelligence lives - we adapt to ANY page type.
    """

    if template_hint:
        # User provided a hint about what they want
        return f"""Extract information matching this structure:
{json.dumps(template_hint, indent=2)}

If information is missing, use null. Don't hallucinate."""

    # Adaptive extraction based on page type and goal
    if page_type == "product_listing":
        return """Extract:
{
  "products": [
    {
      "title": "...",
      "price": number or null,
      "currency": "USD|EUR|GBP|etc",
      "availability": "in_stock|out_of_stock|unknown",
      "specs": {"key": "value"},
      "vendor": "...",
      "location": "..." or null
    }
  ]
}"""

    elif page_type == "forum_discussion":
        return """Extract:
{
  "discussion_topic": "...",
  "key_recommendations": ["...", "..."],
  "mentioned_vendors": [{"name": "...", "sentiment": "positive|negative|neutral", "context": "..."}],
  "helpful_tips": ["...", "..."],
  "warnings": ["...", "..."],
  "community_consensus": "..."
}"""

    elif page_type == "research_paper":
        return """Extract:
{
  "title": "...",
  "authors": ["..."],
  "abstract": "...",
  "key_findings": ["...", "..."],
  "methodology": "...",
  "conclusions": "...",
  "limitations": ["..."],
  "doi": "..." or null
}"""

    elif page_type == "news_article":
        return """Extract:
{
  "headline": "...",
  "date": "...",
  "author": "...",
  "summary": "...",
  "key_facts": ["...", "..."],
  "entities_mentioned": [{"name": "...", "type": "person|org|location", "role": "..."}]
}"""

    elif page_type == "guide_tutorial":
        return """Extract:
{
  "title": "...",
  "topic": "...",
  "steps": [{"step": 1, "instruction": "...", "details": "..."}],
  "tips": ["...", "..."],
  "requirements": ["...", "..."],
  "warnings": ["...", "..."]
}"""

    elif page_type == "vendor_directory":
        return """Extract:
{
  "vendors": [
    {
      "name": "...",
      "type": "breeder|store|marketplace|other",
      "location": "...",
      "contact": "...",
      "specialties": ["..."]
    }
  ]
}"""

    else:  # general
        return f"""Extract information relevant to: {goal}

Use this flexible structure:
{{
  "main_topic": "...",
  "key_information": ["...", "..."],
  "relevant_details": {{"key": "value"}},
  "actionable_insights": ["...", "..."]
}}"""


async def _validate_extraction(
    extracted: Dict[str, Any],
    url: str,
    goal: str,
    llm_url: str,
    llm_model: str,
    llm_api_key: str
) -> Dict[str, Any]:
    """
    Validate that extracted data makes sense.

    Like a human double-checking their notes.
    """

    extracted_data = json.dumps(extracted, indent=2)

    # Load prompt template from file
    prompt_template = _load_navigation_prompt("quality_validator")
    if prompt_template:
        prompt = prompt_template.format(
            goal=goal,
            url=url,
            extracted_data=extracted_data
        )
    else:
        # Fallback inline prompt if file not found
        prompt = f"""You are validating extracted information for quality.

GOAL: {goal}
SOURCE: {url}

EXTRACTED DATA:
{extracted_data}

Task: Validate this extraction. Check for:
1. Completeness - Did we extract useful information?
2. Accuracy - Does it seem plausible?
3. Relevance - Is it relevant to the goal?
4. Hallucinations - Any made-up data?

Return JSON:
{{
  "is_valid": true/false,
  "confidence": 0.0-1.0,
  "issues": ["issue1", "issue2"] or [],
  "data": {{cleaned/validated version of extracted data}},
  "summary": "Brief summary of what was found",
  "key_points": ["point1", "point2", ...]
}}"""

    result = await call_llm_json(prompt, llm_url, llm_model, llm_api_key, max_tokens=800)
    return result
