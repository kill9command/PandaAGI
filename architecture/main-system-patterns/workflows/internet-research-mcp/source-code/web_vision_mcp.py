"""
orchestrator/web_vision_mcp.py

Web Vision MCP Tool - Vision-guided browser automation

Exposes web.* functions for LLM-driven browser control:
- web.get_screen_state(session_id) - Get page state as compact text
- web.click(session_id, goal) - Click UI element matching description
- web.type_text(session_id, text, into=None) - Type text (optionally click field first)
- web.press_key(session_id, key) - Press keyboard key
- web.scroll(session_id, clicks) - Scroll page
- web.capture_content(session_id, format) - Extract page content
- web.navigate(session_id, url) - Navigate to URL

Architecture:
    User Request → Guide Role → Web Vision Role (LLM plans)
                                        ↓
                                web.navigate/click/type...
                                        ↓
                                UIVisionAgent (DOM + OCR perception)
                                        ↓
                                Playwright browser context
                                        ↓
                                Success/Failure

    The Web Vision Role (defined in apps/prompts/web_vision/core.md) receives
a high-level web task and breaks it down into atomic web.* operations.
"""
from __future__ import annotations
import asyncio
import logging
import json
import os
import tempfile
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

from orchestrator.ui_vision_agent import UIVisionAgent, ActionResult, UICandidate
from orchestrator.crawler_session_manager import get_crawler_session_manager
from orchestrator.browser_session_registry import get_browser_session_registry
from orchestrator.browser_recovery import get_browser_recovery_manager

logger = logging.getLogger(__name__)


# ============================================================================
# Recovery-Aware Page Operations
# ============================================================================


async def _check_page_health(page) -> bool:
    """Quick health check for a page."""
    if page is None:
        return False
    try:
        _ = page.url
        await asyncio.wait_for(page.evaluate("() => true"), timeout=3.0)
        return True
    except Exception:
        return False


async def _safe_page_operation(
    session_id: str,
    operation_name: str,
    operation: callable,
    *args,
    max_retries: int = 2,
    **kwargs
):
    """
    Execute a page operation with automatic recovery on connection failure.

    Args:
        session_id: Browser session identifier
        operation_name: Name for logging
        operation: Async function that takes page as first arg
        max_retries: Maximum retry attempts on connection failure

    Returns:
        Operation result
    """
    recovery_manager = get_browser_recovery_manager()
    last_error = None

    # Capture operations should NOT trigger browser restart to avoid losing page content
    # Browser restart happens mid-flow (e.g., after search submit, before capture)
    # which causes the search results page to be lost
    is_capture_operation = operation_name in ("capture_content", "take_screenshot")

    for attempt in range(max_retries + 1):
        try:
            # Get page (with recovery on subsequent attempts)
            if attempt == 0:
                page = await _get_or_create_page(
                    session_id,
                    skip_deferred_restart=is_capture_operation
                )
            else:
                page = await recovery_manager.get_healthy_page(session_id, auto_recover=True)

            if not page:
                raise RuntimeError(f"Could not get page for session {session_id}")

            # Execute operation
            result = await operation(page, *args, **kwargs)

            # Mark session healthy on success
            recovery_manager.mark_healthy(session_id)
            return result

        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            # Check if this is a connection error
            if recovery_manager.is_connection_error(e):
                logger.warning(
                    f"[WebVisionMCP] {operation_name} connection error "
                    f"(attempt {attempt + 1}/{max_retries + 1}): {str(e)[:100]}"
                )
                recovery_manager.mark_unhealthy(session_id, str(e))

                if attempt < max_retries:
                    # Attempt recovery
                    can_recover, reason = recovery_manager.can_recover(session_id)
                    if can_recover:
                        logger.info(f"[WebVisionMCP] Attempting recovery for {session_id}...")
                        success, _ = await recovery_manager.recover_session(session_id)
                        if success:
                            logger.info(f"[WebVisionMCP] Recovery successful, retrying {operation_name}")
                            continue
                    else:
                        logger.warning(f"[WebVisionMCP] Cannot recover: {reason}")
            else:
                # Non-connection error, don't retry
                raise

    # All retries exhausted
    raise last_error or RuntimeError(f"{operation_name} failed after all retries")


# ============================================================================
# Helper Functions
# ============================================================================


async def _get_or_create_page(session_id: str, skip_deferred_restart: bool = False):
    """
    Get existing page or create new browser session.

    Args:
        session_id: Browser session identifier
        skip_deferred_restart: If True, don't trigger browser restart (for capture operations)

    Returns:
        Playwright Page object or None if creation fails
    """
    manager = get_crawler_session_manager()
    registry = get_browser_session_registry()

    # Try to find existing session by looking through all sessions
    sessions = await manager.list_sessions()
    for sess in sessions:
        if sess["session_id"] == session_id:
            context = await manager.get_or_create_session(
                domain=sess["domain"],
                session_id=session_id,
                user_id=sess.get("user_id", "default"),
                skip_deferred_restart=skip_deferred_restart
            )
            page = context.pages[0] if context.pages else await context.new_page()

            # Update session URL if it exists in registry
            if page:
                existing_session = registry.get_session(session_id)
                if existing_session:
                    registry.update_session(session_id, current_url=page.url)

            return page

    # No existing session - create new one
    context = await manager.get_or_create_session(
        domain="web_vision",
        session_id=session_id,
        user_id="default",
        skip_deferred_restart=skip_deferred_restart
    )
    # Reuse existing page if available (avoids creating visible blank tabs)
    page = context.pages[0] if context.pages else await context.new_page()
    # Note: Don't navigate to about:blank - the page is already empty and doing so
    # creates visible blank tabs when browser is running in visible mode

    # Register new browser session in the registry
    try:
        # Extract CDP URL if available
        cdp_url = None
        cdp_http_url = None

        # Try to get CDP connection info from browser
        if hasattr(context, '_browser') and context._browser:
            browser = context._browser
            # Playwright browsers expose CDP via _impl_obj._connection
            if hasattr(browser, '_impl_obj') and hasattr(browser._impl_obj, '_connection'):
                conn = browser._impl_obj._connection
                if hasattr(conn, 'url'):
                    cdp_url = conn.url  # WebSocket URL
                    # Derive HTTP URL from WebSocket URL
                    if cdp_url and cdp_url.startswith('ws://'):
                        cdp_http_url = cdp_url.replace('ws://', 'http://').replace('/devtools/', '/')

        # Get viewport info
        viewport = page.viewport_size if hasattr(page, 'viewport_size') else None

        # Register session
        registry.register_session(
            session_id=session_id,
            cdp_url=cdp_url,
            cdp_http_url=cdp_http_url,
            viewable=True,  # Enable browser control by default
            metadata={
                "domain": "web_vision",
                "user_id": "default",
                "created_by": "web_vision_mcp"
            }
        )

        # Update initial URL
        if page:
            registry.update_session(
                session_id=session_id,
                current_url=page.url,
                viewport=viewport
            )

        logger.info(
            f"[WebVisionMCP] Registered browser session: {session_id} "
            f"(cdp_enabled={cdp_url is not None})"
        )

    except Exception as e:
        logger.warning(f"[WebVisionMCP] Failed to register session {session_id}: {e}")

    return page


async def get_page(session_id: str):
    """
    Public function to get Playwright page object for a session.

    Used by ProductPerceptionPipeline for hybrid extraction.

    Args:
        session_id: Browser session identifier

    Returns:
        Playwright Page object or None
    """
    return await _get_or_create_page(session_id)


# ============================================================================
# Screen State Extraction
# ============================================================================


async def get_screen_state(
    session_id: str,
    max_elements: int = 20,
    max_text_len: int = 30
) -> Dict[str, Any]:
    """
    Get current web page state as ultra-compact text description.

    Returns UI candidates visible on page formatted as compact text
    for vision-in-the-loop LLM prompts (<300 tokens).

    Args:
        session_id: Browser session identifier
        max_elements: Maximum UI elements to return (default: 20)
        max_text_len: Maximum text length per element (default: 30)

    Returns:
        {
            "success": bool,
            "screen_state": str,
            "element_count": int,
            "estimated_tokens": int,
            "page_info": {"url": str, "title": str, "scroll_position": int},
            "message": str
        }
    """
    async def _do_get_screen_state(page, state_max_elements: int, state_max_text_len: int):
        """Inner screen state extraction."""
        url = page.url

        # Handle race condition where page might be mid-navigation
        try:
            title = await page.title()
        except Exception as title_err:
            if "context was destroyed" in str(title_err) or "navigation" in str(title_err).lower():
                logger.info(f"[WebVisionMCP] Page navigating during get_screen_state, waiting for load...")
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    title = await page.title()
                    url = page.url
                except Exception:
                    title = "Page Loading..."
            else:
                title = "Unknown"

        # Get scroll position
        scroll_info = await page.evaluate("""() => {
            return {
                scrollTop: window.pageYOffset || document.documentElement.scrollTop,
                scrollHeight: document.documentElement.scrollHeight,
                clientHeight: window.innerHeight
            }
        }""")

        scroll_percent = int((scroll_info["scrollTop"] / max(scroll_info["scrollHeight"] - scroll_info["clientHeight"], 1)) * 100)

        # Get viewport size
        viewport = page.viewport_size
        width = viewport["width"] if viewport else 1920
        height = viewport["height"] if viewport else 1080

        # Initialize vision agent
        agent = UIVisionAgent(page=page)

        # Take screenshot (temp file for vision analysis)
        screenshot_path = tempfile.mktemp(suffix=".png", prefix="web_vision_state_")
        await page.screenshot(path=screenshot_path, full_page=False)

        # Extract UI candidates
        candidates = await agent.perception.extract_candidates(
            page=page,
            screenshot_path=screenshot_path
        )

        # Clean up screenshot
        import os as os_module
        try:
            if os_module.path.exists(screenshot_path):
                os_module.unlink(screenshot_path)
        except Exception as cleanup_error:
            logger.warning(f"[WebVisionMCP] Cleanup failed: {cleanup_error}")

        # Sort by confidence and limit
        sorted_candidates = sorted(
            candidates,
            key=lambda c: c.confidence,
            reverse=True
        )[:state_max_elements]

        # Format ultra-compact text
        source_abbrev = {
            "dom": "DOM",
            "vision_ocr": "OCR",
            "vision_shape": "Shp"
        }

        lines = [
            f"URL: {url}",
            f"Title: {title[:50]}..." if len(title) > 50 else f"Title: {title}",
            f"Scroll: {scroll_percent}% of page",
            "",
            f"{len(sorted_candidates)} elements found:"
        ]

        for i, cand in enumerate(sorted_candidates, 1):
            text_preview = cand.text[:state_max_text_len] if cand.text else "(no text)"
            x = int(cand.bbox.x)
            y = int(cand.bbox.y)
            conf = int(cand.confidence * 100)
            src = source_abbrev.get(cand.source.value, "?")

            role_info = ""
            if "role" in cand.metadata:
                role_info = f" role={cand.metadata['role']}"

            lines.append(f"{i}. [{src}] '{text_preview}' @({x},{y}){role_info} {conf}%")

        screen_state = "\n".join(lines)
        estimated_tokens = len(screen_state) // 4

        logger.info(
            f"[WebVisionMCP] Screen state: {len(sorted_candidates)} elements, "
            f"~{estimated_tokens} tokens, scroll={scroll_percent}%"
        )

        return {
            "success": True,
            "screen_state": screen_state,
            "element_count": len(sorted_candidates),
            "estimated_tokens": estimated_tokens,
            "page_info": {
                "url": url,
                "title": title,
                "scroll_position": scroll_percent
            },
            "message": f"Page state captured: {len(sorted_candidates)} elements, ~{estimated_tokens} tokens"
        }

    try:
        return await _safe_page_operation(
            session_id,
            "get_screen_state",
            _do_get_screen_state,
            max_elements,
            max_text_len,
            max_retries=2
        )

    except Exception as e:
        logger.error(f"[WebVisionMCP] get_screen_state failed: {e}", exc_info=True)
        return {
            "success": False,
            "screen_state": "",
            "element_count": 0,
            "estimated_tokens": 0,
            "page_info": None,
            "message": f"Error: {e}"
        }


# ============================================================================
# Atomic Actions (directly exposed to LLM)
# ============================================================================


async def click(
    session_id: str,
    goal: str,
    max_attempts: int = 3,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """
    Click a UI element in the browser matching the goal description.

    Args:
        session_id: Browser session identifier
        goal: Description of what to click (e.g., "search button", "next page", "product link")
        max_attempts: Max number of candidates to try
        timeout: Max time to spend (seconds)

    Returns:
        {
            "success": bool,
            "candidate": {...} or null,
            "verification_method": str,
            "metadata": {...},
            "message": str
        }

    Examples:
        web.click(session_id, "search button")
        web.click(session_id, "Add to Cart")
        web.click(session_id, "Next page")
    """
    async def _do_click(page, click_goal: str, click_max_attempts: int, click_timeout: float):
        """Inner click operation."""
        agent = UIVisionAgent(page=page)
        result = await agent.click(click_goal, max_attempts=click_max_attempts, timeout=click_timeout)
        return {
            "success": result.success,
            "candidate": result.candidate.to_dict() if result.candidate else None,
            "verification_method": result.verification_method,
            "metadata": result.metadata,
            "message": _format_result_message(result, click_goal)
        }

    try:
        return await _safe_page_operation(
            session_id,
            "click",
            _do_click,
            goal,
            max_attempts,
            timeout,
            max_retries=2
        )

    except Exception as e:
        logger.error(f"[WebVisionMCP] click failed: {e}", exc_info=True)
        return {
            "success": False,
            "candidate": None,
            "verification_method": "error",
            "metadata": {"error": str(e)},
            "message": f"Failed to click '{goal}': {e}"
        }


async def type_text(
    session_id: str,
    text: str,
    into: Optional[str] = None,
    interval: float = 0.05
) -> Dict[str, Any]:
    """
    Type text in the browser.

    Args:
        session_id: Browser session identifier
        text: Text to type
        into: Optional description of field to click first (e.g., "search box", "username field")
        interval: Interval between keystrokes (seconds)

    Returns:
        {
            "success": bool,
            "verification_method": str,
            "metadata": {...},
            "message": str
        }

    Examples:
        web.type_text(session_id, "hamster cage")
        web.type_text(session_id, "admin@example.com", into="email field")
    """
    async def _do_type_text(page, type_text_val: str, type_into: Optional[str], type_interval: float):
        """Inner type operation."""
        # If target field specified, click it first
        if type_into:
            logger.info(f"[WebVisionMCP] type_text called with into='{type_into}'")
            input_element = None
            click_succeeded = False

            if "search" in type_into.lower() or "input" in type_into.lower():
                common_selectors = [
                    'textarea[name="q"]',
                    'input[name="q"]',
                    'textarea[aria-label*="search" i]',
                    'input[type="search"]',
                    'input[aria-label*="search" i]',
                    'input[placeholder*="search" i]',
                    '#search-input',
                ]

                for selector in common_selectors:
                    try:
                        input_element = await page.query_selector(selector)
                        if input_element:
                            logger.info(f"[WebVisionMCP] Trying direct selector: {selector}")
                            await input_element.click(timeout=5000)
                            logger.info(f"[WebVisionMCP] Successfully clicked using: {selector}")
                            await asyncio.sleep(0.2)
                            click_succeeded = True
                            break
                    except Exception as e:
                        logger.debug(f"[WebVisionMCP] Selector {selector} failed: {e}")
                        continue

            if not click_succeeded:
                agent = UIVisionAgent(page=page)
                click_result = await agent.click(type_into, max_attempts=2, timeout=10.0)

                if not click_result.success:
                    return {
                        "success": False,
                        "verification_method": "click_failed",
                        "metadata": {"error": f"Could not click target field: {type_into}"},
                        "message": f"Failed to click field '{type_into}' before typing"
                    }

                await asyncio.sleep(0.2)

        # Type text with human-like timing
        await page.keyboard.type(type_text_val, delay=type_interval * 1000)

        logger.info(f"[WebVisionMCP] Typed text: {type_text_val[:30]}...")

        return {
            "success": True,
            "verification_method": "keyboard_input",
            "metadata": {"text_length": len(type_text_val), "target": type_into},
            "message": f"Typed text: {type_text_val[:50]}..." if len(type_text_val) > 50 else f"Typed: {type_text_val}"
        }

    try:
        return await _safe_page_operation(
            session_id,
            "type_text",
            _do_type_text,
            text,
            into,
            interval,
            max_retries=2
        )

    except Exception as e:
        logger.error(f"[WebVisionMCP] type_text failed: {e}", exc_info=True)
        return {
            "success": False,
            "verification_method": "error",
            "metadata": {"error": str(e)},
            "message": f"Failed to type text: {e}"
        }


async def press_key(
    session_id: str,
    key: str,
    presses: int = 1,
    after_clicking: Optional[str] = None
) -> Dict[str, Any]:
    """
    Press a keyboard key in the browser.

    Args:
        session_id: Browser session identifier
        key: Key name (e.g., "Enter", "Tab", "Escape", "ArrowDown")
        presses: Number of times to press
        after_clicking: Optional field to click/focus before pressing key (e.g., "search box")

    Returns:
        {
            "success": bool,
            "verification_method": str,
            "metadata": {...},
            "message": str
        }

    Examples:
        web.press_key(session_id, "Enter")
        web.press_key(session_id, "Tab", presses=3)
        web.press_key(session_id, "Enter", after_clicking="search box")
    """
    async def _do_press_key(page, press_key_val: str, press_presses: int, press_after_clicking: Optional[str]):
        """Inner press key operation."""
        # If target field specified, click it first to ensure focus
        if press_after_clicking:
            logger.info(f"[WebVisionMCP] press_key called with after_clicking='{press_after_clicking}'")
            input_element = None

            if "search" in press_after_clicking.lower() or "input" in press_after_clicking.lower():
                common_selectors = [
                    'textarea[name="q"]',
                    'input[name="q"]',
                    'textarea[aria-label*="search" i]',
                    'input[type="search"]',
                    'input[aria-label*="search" i]',
                    'input[placeholder*="search" i]',
                    '#search-input',
                ]

                for selector in common_selectors:
                    input_element = await page.query_selector(selector)
                    if input_element:
                        logger.info(f"[WebVisionMCP] Using direct selector for press_key: {selector}")
                        await input_element.click()
                        break

            if not input_element:
                agent = UIVisionAgent(page=page)
                click_result = await agent.click(press_after_clicking, max_attempts=2, timeout=10.0)

                if not click_result.success:
                    logger.warning(f"[WebVisionMCP] Could not click '{press_after_clicking}' before pressing key, continuing anyway")

            await asyncio.sleep(0.2)

        # Press key multiple times
        for _ in range(press_presses):
            await page.keyboard.press(press_key_val)
            if press_presses > 1:
                await asyncio.sleep(0.1)

        logger.info(f"[WebVisionMCP] Pressed '{press_key_val}' {press_presses} time(s)" + (f" after clicking '{press_after_clicking}'" if press_after_clicking else ""))

        return {
            "success": True,
            "verification_method": "keyboard_input",
            "metadata": {"key": press_key_val, "presses": press_presses, "after_clicking": press_after_clicking},
            "message": f"Pressed '{press_key_val}' {press_presses} time(s)" + (f" (after clicking '{press_after_clicking}')" if press_after_clicking else "")
        }

    try:
        return await _safe_page_operation(
            session_id,
            "press_key",
            _do_press_key,
            key,
            presses,
            after_clicking,
            max_retries=2
        )

    except Exception as e:
        logger.error(f"[WebVisionMCP] press_key failed: {e}", exc_info=True)
        return {
            "success": False,
            "verification_method": "error",
            "metadata": {"error": str(e)},
            "message": f"Failed to press key '{key}': {e}"
        }


async def scroll(
    session_id: str,
    clicks: int
) -> Dict[str, Any]:
    """
    Scroll page up/down.

    Args:
        session_id: Browser session identifier
        clicks: Number of scroll clicks (positive=up/forward, negative=down/backward)

    Returns:
        {
            "success": bool,
            "verification_method": str,
            "metadata": {...},
            "message": str
        }

    Examples:
        web.scroll(session_id, 5)    # Scroll down
        web.scroll(session_id, -3)   # Scroll up
    """
    async def _do_scroll(page, scroll_clicks: int):
        """Inner scroll operation."""
        scroll_amount = scroll_clicks * 100  # 100px per click

        await page.mouse.wheel(0, scroll_amount)

        # Wait for scroll to complete
        await asyncio.sleep(0.3)

        # Get new scroll position
        scroll_info = await page.evaluate("""() => {
            return {
                scrollTop: window.pageYOffset || document.documentElement.scrollTop,
                scrollHeight: document.documentElement.scrollHeight
            }
        }""")

        direction = "down" if scroll_clicks > 0 else "up"
        logger.info(f"[WebVisionMCP] Scrolled {direction} {abs(scroll_clicks)} clicks (now at {scroll_info['scrollTop']}px)")

        return {
            "success": True,
            "verification_method": "scroll",
            "metadata": {
                "clicks": scroll_clicks,
                "scroll_position": scroll_info["scrollTop"],
                "scroll_height": scroll_info["scrollHeight"]
            },
            "message": f"Scrolled {direction} {abs(scroll_clicks)} clicks"
        }

    try:
        return await _safe_page_operation(
            session_id,
            "scroll",
            _do_scroll,
            clicks,
            max_retries=2
        )

    except Exception as e:
        logger.error(f"[WebVisionMCP] scroll failed: {e}", exc_info=True)
        return {
            "success": False,
            "verification_method": "error",
            "metadata": {"error": str(e)},
            "message": f"Failed to scroll: {e}"
        }


async def capture_content(
    session_id: str,
    format: str = "markdown"
) -> Dict[str, Any]:
    """
    Capture page content in specified format.

    Args:
        session_id: Browser session identifier
        format: "markdown" (main content) or "html" (full DOM)

    Returns:
        {
            "success": bool,
            "content": str,
            "url": str,
            "title": str,
            "estimated_tokens": int,
            "message": str
        }

    Examples:
        web.capture_content(session_id, format="markdown")
        web.capture_content(session_id, format="html")
    """
    async def _do_capture_content(page, capture_format: str):
        """Inner capture operation."""
        url = page.url

        # Handle race condition where page might be mid-navigation
        try:
            title = await page.title()
        except Exception as title_err:
            if "context was destroyed" in str(title_err) or "navigation" in str(title_err).lower():
                logger.info(f"[WebVisionMCP] Page navigating, waiting for load...")
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    title = await page.title()
                    url = page.url
                except Exception:
                    title = "Page Loading..."
            else:
                title = "Unknown"

        if capture_format == "html":
            content = await page.content()
            estimated_tokens = len(content) // 4

            logger.info(f"[WebVisionMCP] Captured HTML: {len(content)} chars, ~{estimated_tokens} tokens")

            return {
                "success": True,
                "content": content,
                "url": url,
                "title": title,
                "format": "html",
                "estimated_tokens": estimated_tokens,
                "message": f"Captured HTML: {len(content)} chars"
            }

        elif capture_format == "markdown":
            from orchestrator.content_sanitizer import sanitize_html
            from urllib.parse import urlparse

            html = await page.content()
            domain = urlparse(url).netloc

            sanitized = sanitize_html(html, domain)
            chunks = sanitized.get("chunks", [])
            content_parts = [f"# {title}\n\n**URL:** {url}\n\n"]

            for chunk in chunks:
                if chunk.get("text"):
                    content_parts.append(chunk["text"])
                    content_parts.append("\n\n")

            content = "".join(content_parts)
            estimated_tokens = len(content) // 4

            logger.info(f"[WebVisionMCP] Captured markdown: {len(content)} chars, ~{estimated_tokens} tokens")

            return {
                "success": True,
                "content": content,
                "url": url,
                "title": title,
                "format": "markdown",
                "estimated_tokens": estimated_tokens,
                "message": f"Captured markdown: {len(content)} chars, ~{estimated_tokens} tokens"
            }

        else:
            return {
                "success": False,
                "content": "",
                "url": url,
                "title": title,
                "estimated_tokens": 0,
                "message": f"Unknown format: {capture_format} (use 'markdown' or 'html')"
            }

    try:
        return await _safe_page_operation(
            session_id,
            "capture_content",
            _do_capture_content,
            format,
            max_retries=2
        )

    except Exception as e:
        logger.error(f"[WebVisionMCP] capture_content failed: {e}", exc_info=True)
        return {
            "success": False,
            "content": "",
            "url": "",
            "title": "",
            "estimated_tokens": 0,
            "message": f"Error: {e}"
        }


async def navigate(
    session_id: str,
    url: str,
    wait_for: str = "networkidle"
) -> Dict[str, Any]:
    """
    Navigate to URL with stealth, error handling, and automatic recovery.

    Args:
        session_id: Browser session identifier
        url: Target URL
        wait_for: Wait condition ("load", "domcontentloaded", "networkidle")

    Returns:
        {
            "success": bool,
            "url": str,
            "title": str,
            "status_code": int,
            "message": str
        }

    Examples:
        web.navigate(session_id, "https://example.com")
        web.navigate(session_id, "https://slow-site.com", wait_for="domcontentloaded")
    """
    recovery_manager = get_browser_recovery_manager()

    async def _do_navigate(page, target_url: str) -> Dict[str, Any]:
        """Inner navigation with retry strategies."""
        logger.info(f"[WebVisionMCP] Navigating to: {target_url}")

        # Retry navigation with progressive fallback strategies
        # Note: If first attempt times out, we fail-fast (don't retry)
        wait_strategies = [
            ("domcontentloaded", 30000),  # 30s - if site doesn't respond in 30s, it's likely dead
            ("load", 20000),              # 20s fallback (only used for non-timeout errors)
            ("commit", 15000)             # 15s last resort
        ]

        response = None
        last_error = None

        for attempt, (wait_strategy, timeout_ms) in enumerate(wait_strategies, 1):
            try:
                logger.info(
                    f"[WebVisionMCP] Attempt {attempt}/{len(wait_strategies)}: "
                    f"wait={wait_strategy}, timeout={timeout_ms}ms"
                )
                response = await page.goto(target_url, wait_until=wait_strategy, timeout=timeout_ms)
                if response:
                    logger.info(f"[WebVisionMCP] Success on attempt {attempt} with {wait_strategy}")
                    break
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                logger.warning(
                    f"[WebVisionMCP] Attempt {attempt} failed ({wait_strategy}): {str(e)[:100]}"
                )

                # Check if this is a connection error that needs recovery
                if recovery_manager.is_connection_error(e):
                    # Re-raise to trigger recovery in _safe_page_operation
                    raise

                # FAIL FAST: If first attempt times out completely, don't bother retrying
                # A 60s timeout means the site is likely dead/unreachable
                if attempt == 1 and "timeout" in error_str:
                    logger.warning(
                        f"[WebVisionMCP] Fail-fast: First attempt timed out after {timeout_ms}ms, "
                        f"skipping retries (site likely unreachable)"
                    )
                    break

                if attempt < len(wait_strategies):
                    logger.info(f"[WebVisionMCP] Retrying with fallback strategy...")
                    await asyncio.sleep(1)

        if not response:
            error_msg = str(last_error)[:200] if last_error else "unknown error"
            logger.error(f"[WebVisionMCP] All navigation strategies failed: {error_msg}")
            return {
                "success": False,
                "url": page.url if page else "",
                "title": "",
                "status_code": 0,
                "message": f"Navigation failed: {error_msg}"
            }

        status_code = response.status
        title = await page.title()
        final_url = page.url

        # Check for HTTP errors
        if status_code >= 400:
            logger.warning(f"[WebVisionMCP] Navigation returned {status_code}: {target_url}")
            return {
                "success": False,
                "url": final_url,
                "title": title,
                "status_code": status_code,
                "message": f"Navigation failed: HTTP {status_code}"
            }

        logger.info(f"[WebVisionMCP] Navigation success: {final_url} ({status_code})")

        # Update session URL in registry
        try:
            registry = get_browser_session_registry()
            registry.update_session(session_id, current_url=final_url)
        except Exception as e:
            logger.debug(f"[WebVisionMCP] Could not update session URL: {e}")

        return {
            "success": True,
            "url": final_url,
            "title": title,
            "status_code": status_code,
            "message": f"Navigated to {final_url}"
        }

    try:
        # Use recovery-aware operation wrapper
        return await _safe_page_operation(
            session_id,
            "navigate",
            _do_navigate,
            url,
            max_retries=2
        )

    except Exception as e:
        logger.error(f"[WebVisionMCP] navigate failed: {e}", exc_info=True)
        return {
            "success": False,
            "url": "",
            "title": "",
            "status_code": 0,
            "message": f"Navigation error: {e}"
        }


# ============================================================================
# Utilities
# ============================================================================


def _format_result_message(result: ActionResult, goal: str) -> str:
    """Format ActionResult into human-readable message."""
    if result.success:
        if result.candidate:
            return (
                f"Successfully clicked '{result.candidate.text or goal}' "
                f"(confidence={result.candidate.confidence:.2f}, "
                f"verified via {result.verification_method})"
            )
        else:
            return f"Action completed (verified via {result.verification_method})"
    else:
        if result.verification_method == "no_candidates":
            return f"No UI elements found matching '{goal}'"
        elif result.verification_method == "max_attempts_exceeded":
            attempts = result.metadata.get("attempts", "unknown")
            return f"Failed after {attempts} attempts - no successful verification"
        else:
            return f"Action failed ({result.verification_method})"


async def get_status(session_id: str) -> Dict[str, Any]:
    """
    Get web session status and page info, including health status.

    Returns:
        {
            "session_exists": bool,
            "page_info": {"url": str, "title": str} or null,
            "viewport": {"width": int, "height": int} or null,
            "health": {"is_healthy": bool, "consecutive_failures": int} or null
        }
    """
    recovery_manager = get_browser_recovery_manager()

    async def _do_get_status(page):
        """Inner status check."""
        url = page.url
        title = await page.title()
        viewport = page.viewport_size

        return {
            "url": url,
            "title": title,
            "viewport": viewport or {"width": 1920, "height": 1080}
        }

    try:
        result = await _safe_page_operation(
            session_id,
            "get_status",
            _do_get_status,
            max_retries=1
        )

        # Get health info
        health = recovery_manager._get_health(session_id)

        return {
            "session_exists": True,
            "page_info": {"url": result["url"], "title": result["title"]},
            "viewport": result["viewport"],
            "health": {
                "is_healthy": health.is_healthy,
                "consecutive_failures": health.consecutive_failures,
                "recovery_attempts": health.recovery_attempts
            }
        }

    except Exception as e:
        logger.error(f"[WebVisionMCP] get_status failed: {e}")

        # Still return health info even on failure
        health = recovery_manager._get_health(session_id)

        return {
            "session_exists": False,
            "page_info": None,
            "viewport": None,
            "health": {
                "is_healthy": health.is_healthy,
                "consecutive_failures": health.consecutive_failures,
                "recovery_attempts": health.recovery_attempts
            },
            "error": str(e)
        }


async def get_recovery_stats() -> Dict[str, Any]:
    """
    Get browser recovery manager statistics.

    Returns:
        {
            "total_recoveries": int,
            "successful_recoveries": int,
            "failed_recoveries": int,
            "success_rate": float,
            "avg_recovery_duration_ms": float,
            "currently_recovering": list,
            "unhealthy_sessions": list,
            "tracked_sessions": int
        }
    """
    recovery_manager = get_browser_recovery_manager()
    return recovery_manager.get_stats()


async def reset_session(session_id: str) -> Dict[str, Any]:
    """
    Reset a browser session, clearing health tracking and forcing re-creation.

    Use this when a session is in a bad state and needs to be completely reset.

    Args:
        session_id: Session identifier

    Returns:
        {"success": bool, "message": str}
    """
    recovery_manager = get_browser_recovery_manager()

    try:
        # Reset health tracking
        recovery_manager.reset_session_health(session_id)

        # Close the dead session
        await recovery_manager._close_dead_session(session_id)

        logger.info(f"[WebVisionMCP] Session {session_id} reset successfully")

        return {
            "success": True,
            "message": f"Session {session_id} has been reset. Next operation will create a fresh session."
        }

    except Exception as e:
        logger.error(f"[WebVisionMCP] reset_session failed: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Failed to reset session: {e}"
        }
