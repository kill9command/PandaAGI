"""
apps/services/tool_server/human_search_engine.py

DEPRECATED (2025-11-29): Use web_mcp.py instead.

This module is kept for backward compatibility with commerce_mcp.py.
New code should use:
    from apps.services.tool_server.web_mcp import web_search

The unified web_mcp.py provides:
- Single entry point for ALL web operations
- Proactive schema learning
- Unified SmartPageWaiter

Migration:
    OLD: search_with_fallback(query, page, ...)
    NEW: await web_search(query, search_engine="google")

Created: 2025-11-18
Deprecated: 2025-11-29 (replaced by web_mcp.py)
"""
import logging
import random
import asyncio
import os
from typing import List, Dict, Any
from playwright.async_api import Page, BrowserContext

logger = logging.getLogger(__name__)


async def warmup_session(page: Page, domain: str = "duckduckgo.com") -> None:
    """
    Warmup browser session by visiting homepage and acting human.

    This is a key SerpAPI technique - don't jump straight to searching!
    Instead:
    1. Visit homepage
    2. Wait 3-8 seconds (like reading the page)
    3. Scroll randomly (simulate browsing)
    4. Move mouse around

    This makes the session look much more human before the actual search.
    """
    try:
        logger.info(f"[SessionWarmup] Warming up session on {domain}...")

        # Random wait time (humans take 3-8 seconds to read a page)
        warmup_delay = random.uniform(3.0, 8.0)
        await asyncio.sleep(warmup_delay)

        # Scroll down a bit (humans often scroll)
        try:
            scroll_amount = random.randint(100, 500)
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(random.uniform(0.5, 1.5))

            # Scroll back up (like reviewing the page)
            await page.evaluate(f"window.scrollBy(0, -{scroll_amount})")
            await asyncio.sleep(random.uniform(0.3, 0.8))
        except Exception as e:
            logger.debug(f"[SessionWarmup] Scroll simulation failed (page may not be scrollable): {e}")

        # Move mouse to random positions (simulate human cursor movement)
        try:
            for _ in range(random.randint(2, 4)):
                x = random.randint(100, 800)
                y = random.randint(100, 600)
                await page.mouse.move(x, y)
                await asyncio.sleep(random.uniform(0.2, 0.5))
        except Exception as e:
            logger.debug(f"[SessionWarmup] Mouse movement simulation failed: {e}")

        logger.info(f"[SessionWarmup] Session warmed up for {domain} ({warmup_delay:.1f}s)")

    except Exception as e:
        logger.warning(f"[SessionWarmup] Warmup failed (continuing anyway): {e}")


async def get_page_cdp_url(page: Page) -> str:
    """
    Get CDP DevTools URL for a Playwright page.

    Returns URL that can be opened in browser to view/control the page.
    """
    try:
        # Get CDP port from environment or use default
        cdp_port = os.getenv("PLAYWRIGHT_CDP_PORT", "9223")

        # Get the page's target ID via CDP
        cdp_session = await page.context.new_cdp_session(page)
        target_info = await cdp_session.send("Target.getTargetInfo")
        target_id = target_info.get("targetInfo", {}).get("targetId", "")
        await cdp_session.detach()

        if target_id:
            # Construct DevTools inspector URL
            cdp_url = f"http://localhost:{cdp_port}/devtools/inspector.html?ws=localhost:{cdp_port}/devtools/page/{target_id}"
            logger.info(f"[CDP] Generated DevTools URL for page: {cdp_url[:80]}...")
            return cdp_url
        else:
            logger.warning("[CDP] Could not get target ID, returning base URL")
            return f"http://localhost:{cdp_port}"
    except Exception as e:
        logger.warning(f"[CDP] Failed to get page CDP URL: {e}")
        cdp_port = os.getenv("PLAYWRIGHT_CDP_PORT", "9223")
        return f"http://localhost:{cdp_port}"


async def search_duckduckgo_human(
    query: str,
    max_results: int = 10,
    session_id: str = "default",
    location: str = "US",
    human_assist_allowed: bool = True
) -> List[Dict[str, Any]]:
    """
    Visit duckduckgo.com in a real browser, type search, extract results.

    Works exactly like a human would:
    1. Open browser
    2. Go to duckduckgo.com
    3. Type search query
    4. Press Enter
    5. Extract organic results from page

    Supports intervention:
    - If CAPTCHA appears, requests human intervention
    - User can solve CAPTCHA via UI
    - Search continues after CAPTCHA solved

    Args:
        query: Search query string
        max_results: Maximum number of results to extract
        session_id: Session ID for cookie persistence
        location: User location (default "US")
        human_assist_allowed: Enable CAPTCHA intervention (default True)

    Returns:
        [
            {
                "url": "https://example.com",
                "title": "Page Title",
                "snippet": "Description",
                "position": 1
            },
            ...
        ]
    """
    from apps.services.tool_server.crawler_session_manager import get_crawler_session_manager
    from apps.services.tool_server.captcha_intervention import detect_blocker, request_intervention

    logger.info(f"[HumanSearch] Searching DuckDuckGo for: {query[:60]} (max_results={max_results})")

    # Use existing crawler session manager for cookie persistence
    session_mgr = get_crawler_session_manager()
    context = await session_mgr.get_or_create_session(
        domain="duckduckgo.com",
        session_id=session_id
    )

    page = await context.new_page()
    results = []

    try:
        # Step 1: Visit DuckDuckGo (with region parameter for US results)
        ddg_url = "https://duckduckgo.com/"
        if location == "US":
            ddg_url = "https://duckduckgo.com/?kl=us-en"  # US region

        logger.info(f"[HumanSearch] Visiting {ddg_url}")
        await page.goto(ddg_url, wait_until="networkidle", timeout=30000)

        # SerpAPI-style session warmup: act like a human before searching!
        # Visit homepage, wait, scroll, move mouse (looks much more natural)
        await warmup_session(page, domain="duckduckgo.com")

        # Check for blockers/CAPTCHAs on initial page load
        page_content = await page.content()
        blocker = detect_blocker({
            "content": page_content,
            "status": 200,
            "url": ddg_url,
            "screenshot_path": None,
            "blocked": False,
            "block_type": ""
        })

        if blocker and blocker["confidence"] >= 0.7:
            logger.warning(f"[HumanSearch] Blocker detected on DDG homepage: {blocker['type'].value}")

            # RATE_LIMIT on homepage: Fail fast, no human intervention needed
            if blocker["type"].value == "rate_limit":
                from apps.services.tool_server.search_rate_limiter import get_search_rate_limiter
                from apps.services.tool_server.search_engine_health import get_engine_health_tracker
                logger.warning(f"[HumanSearch] DuckDuckGo homepage blocked (rate limit), skipping...")
                get_search_rate_limiter().report_rate_limit("DuckDuckGo")
                get_engine_health_tracker().report_failure("DuckDuckGo", "rate_limit")
                return []  # Fail fast - let caller try next engine

            # CAPTCHAs on homepage: Request human intervention
            if human_assist_allowed:
                # Request intervention
                logger.info(f"[HumanSearch] Requesting human intervention for {blocker['type'].value}")

                # Get CDP URL for user to access Playwright browser
                cdp_url = await get_page_cdp_url(page)

                # Take screenshot
                screenshot_path = f"panda_system_docs/scrape_staging/screenshots/search_{session_id}_{int(asyncio.get_event_loop().time())}.png"
                await page.screenshot(path=screenshot_path, full_page=True)

                intervention = await request_intervention(
                    blocker_type=blocker["type"].value,
                    url=ddg_url,
                    screenshot_path=screenshot_path,
                    session_id=session_id,
                    blocker_details=blocker,
                    cdp_url=cdp_url
                )

                if intervention.get("status") == "resolved":
                    logger.info(f"[HumanSearch] CAPTCHA resolved, continuing search...")
                else:
                    logger.warning(f"[HumanSearch] Intervention timeout or failed, aborting search")
                    return []
            else:
                logger.warning(f"[HumanSearch] Human assist disabled, cannot proceed past blocker")
                return []

        # Step 2: Find search box and type query (like a human - with delays!)
        search_box = await page.wait_for_selector('input[name="q"]', timeout=10000)

        # Clear any existing text
        await search_box.click()
        await search_box.fill("")

        # Type with human-like delays (50-150ms between keystrokes)
        logger.info(f"[HumanSearch] Typing query with human-like delays...")
        for char in query:
            await search_box.type(char, delay=random.randint(50, 150))

        # Small pause before pressing Enter (like a human reviewing what they typed)
        await asyncio.sleep(random.uniform(0.3, 0.7))

        # Step 3: Press Enter and wait for results
        logger.info(f"[HumanSearch] Submitting search...")
        await page.keyboard.press("Enter")

        # Wait for results to load
        try:
            await page.wait_for_selector('article[data-testid="result"]', timeout=15000)
        except Exception as e:
            logger.warning(f"[HumanSearch] Timeout waiting for results, checking for blockers: {e}")

        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            logger.warning(f"[HumanSearch] networkidle wait failed: {e}")

        # Check for blockers on results page (CAPTCHA might appear after search)
        results_content = await page.content()
        results_blocker = detect_blocker({
            "content": results_content,
            "status": 200,
            "url": page.url,
            "screenshot_path": None,
            "blocked": False,
            "block_type": ""
        })

        if results_blocker and results_blocker["confidence"] >= 0.7:
            logger.warning(f"[HumanSearch] Blocker detected on results page: {results_blocker['type'].value}")

            # RATE_LIMIT: Fail fast! Don't wait for human, just return empty results
            # This lets the caller try the next search engine immediately
            if results_blocker["type"].value == "rate_limit":
                from apps.services.tool_server.search_rate_limiter import get_search_rate_limiter
                from apps.services.tool_server.search_engine_health import get_engine_health_tracker
                logger.warning(f"[HumanSearch] DuckDuckGo returned no results, trying next...")
                get_search_rate_limiter().report_rate_limit("DuckDuckGo")
                get_engine_health_tracker().report_failure("DuckDuckGo", "rate_limit")
                return []  # Fail fast - let caller try next engine

            # CAPTCHAs: Request human intervention (can actually be solved)
            if human_assist_allowed:
                # Request intervention
                logger.info(f"[HumanSearch] Requesting human intervention for results page blocker")

                # Get CDP URL for user to access Playwright browser
                cdp_url = await get_page_cdp_url(page)

                # Take screenshot
                screenshot_path = f"panda_system_docs/scrape_staging/screenshots/search_results_{session_id}_{int(asyncio.get_event_loop().time())}.png"
                await page.screenshot(path=screenshot_path, full_page=True)

                intervention = await request_intervention(
                    blocker_type=results_blocker["type"].value,
                    url=page.url,
                    screenshot_path=screenshot_path,
                    session_id=session_id,
                    blocker_details=results_blocker,
                    cdp_url=cdp_url
                )

                # Wait for user to resolve the intervention (90 second timeout for CAPTCHAs)
                resolved = await intervention.wait_for_resolution(timeout=180)

                if resolved:
                    logger.info(f"[HumanSearch] Results page CAPTCHA resolved, navigating back to search...")
                    # Wait for rate limit to clear (DuckDuckGo 418 is often time-based)
                    await asyncio.sleep(5)

                    # Navigate to fresh DuckDuckGo search to bypass blocker
                    from urllib.parse import quote_plus
                    fresh_search_url = f"https://duckduckgo.com/?q={quote_plus(query)}&t=h_&kl=us-en"
                    logger.info(f"[HumanSearch] Navigating to fresh search: {fresh_search_url[:80]}...")

                    try:
                        await page.goto(fresh_search_url, wait_until="domcontentloaded", timeout=20000)
                        await asyncio.sleep(2)
                        await page.wait_for_load_state("networkidle", timeout=10000)
                        logger.info(f"[HumanSearch] Successfully navigated to fresh search results")
                    except Exception as nav_error:
                        logger.warning(f"[HumanSearch] Navigation after resolution failed: {nav_error}")
                        # Try refreshing current page as fallback
                        await page.reload(wait_until="domcontentloaded", timeout=15000)
                else:
                    logger.warning(f"[HumanSearch] Intervention timeout, returning no results")
                    return []
            else:
                logger.warning(f"[HumanSearch] Human assist disabled, cannot extract results past blocker")
                return []

        # Step 4: Extract organic results from the page
        logger.info(f"[HumanSearch] Extracting search results...")
        result_elements = await page.query_selector_all('article[data-testid="result"]')

        logger.info(f"[HumanSearch] Found {len(result_elements)} result elements")

        for i, elem in enumerate(result_elements[:max_results]):
            try:
                # Extract link
                link_elem = await elem.query_selector('a[data-testid="result-title-a"]')
                if not link_elem:
                    # Try alternative selector
                    link_elem = await elem.query_selector('h2 a')

                url = await link_elem.get_attribute("href") if link_elem else ""

                # Extract title
                title = await link_elem.inner_text() if link_elem else ""
                title = title.strip()

                # Extract snippet
                snippet_elem = await elem.query_selector('[data-result="snippet"]')
                if not snippet_elem:
                    # Try alternative selector
                    snippet_elem = await elem.query_selector('span[data-testid="result-snippet"]')

                snippet = await snippet_elem.inner_text() if snippet_elem else ""
                snippet = snippet.strip()

                if url and title:
                    results.append({
                        "url": url,
                        "title": title,
                        "snippet": snippet,
                        "position": i + 1
                    })
                    logger.info(f"[HumanSearch]   {i+1}. {title[:60]}...")
            except Exception as e:
                logger.warning(f"[HumanSearch] Error extracting result {i+1}: {e}")
                continue

        logger.info(f"[HumanSearch] Successfully extracted {len(results)} results")

        # Save session state for cookie persistence
        await session_mgr.save_session_state(
            domain="duckduckgo.com",
            session_id=session_id,
            context=context,
            user_id="default"
        )

        return results

    except Exception as e:
        logger.error(f"[HumanSearch] Search failed: {e}", exc_info=True)
        return []

    finally:
        await page.close()


async def search_google_human(
    query: str,
    max_results: int = 10,
    session_id: str = "default",
    location: str = "US",
    human_assist_allowed: bool = True
) -> List[Dict[str, Any]]:
    """
    Visit google.com in a real browser, type search, extract results.

    Alternative to DuckDuckGo if needed.

    Args:
        query: Search query string
        max_results: Maximum number of results to extract
        session_id: Session ID for cookie persistence
        location: User location (default "US")

    Returns:
        List of result dicts (same format as search_duckduckgo_human)
    """
    from apps.services.tool_server.crawler_session_manager import get_crawler_session_manager
    from apps.services.tool_server.captcha_intervention import detect_blocker, request_intervention

    logger.info(f"[HumanSearch] Searching Google for: {query[:60]} (max_results={max_results})")

    session_mgr = get_crawler_session_manager()
    context = await session_mgr.get_or_create_session(
        domain="google.com",
        session_id=session_id
    )

    page = await context.new_page()
    results = []

    try:
        # Visit Google
        google_url = "https://www.google.com/"
        logger.info(f"[HumanSearch] Visiting {google_url}")
        await page.goto(google_url, wait_until="networkidle", timeout=30000)

        # SerpAPI-style session warmup for Google too
        await warmup_session(page, domain="google.com")

        # Find search box
        search_box = await page.wait_for_selector('textarea[name="q"]', timeout=10000)

        # Type query with human-like delays
        logger.info(f"[HumanSearch] Typing query...")
        for char in query:
            await search_box.type(char, delay=random.randint(50, 150))

        await asyncio.sleep(random.uniform(0.3, 0.7))

        # Submit search
        logger.info(f"[HumanSearch] Submitting search...")
        await page.keyboard.press("Enter")

        # Wait for results
        try:
            await page.wait_for_selector('div#search', timeout=15000)
        except Exception as e:
            logger.warning(f"[HumanSearch] Timeout waiting for Google results: {e}")

        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            logger.warning(f"[HumanSearch] networkidle wait failed: {e}")

        # Check for blockers on Google results page
        google_content = await page.content()
        results_blocker = detect_blocker({
            "content": google_content,
            "status": 200,
            "url": page.url,
            "screenshot_path": None,
            "blocked": False,
            "block_type": ""
        })

        if results_blocker and results_blocker["confidence"] >= 0.7:
            logger.warning(f"[HumanSearch] Blocker detected on Google results page: {results_blocker['type'].value}")

            # RATE_LIMIT: Fail fast! No 90s wait
            if results_blocker["type"].value == "rate_limit":
                from apps.services.tool_server.search_rate_limiter import get_search_rate_limiter
                from apps.services.tool_server.search_engine_health import get_engine_health_tracker
                logger.warning(f"[HumanSearch] Google returned no results, trying next...")
                get_search_rate_limiter().report_rate_limit("Google")
                get_engine_health_tracker().report_failure("Google", "rate_limit")
                return []  # Fail fast - let caller try next engine

            # CAPTCHAs: Request human intervention
            if human_assist_allowed:
                # Request intervention
                logger.info(f"[HumanSearch] Requesting human intervention for Google blocker")

                # Get CDP URL for user to access Playwright browser
                cdp_url = await get_page_cdp_url(page)

                # Take screenshot
                screenshot_path = f"panda_system_docs/scrape_staging/screenshots/google_{session_id}_{int(asyncio.get_event_loop().time())}.png"
                await page.screenshot(path=screenshot_path, full_page=True)

                intervention = await request_intervention(
                    blocker_type=results_blocker["type"].value,
                    url=page.url,
                    screenshot_path=screenshot_path,
                    session_id=session_id,
                    blocker_details=results_blocker,
                    cdp_url=cdp_url
                )

                # Wait for user to resolve the intervention (90 second timeout)
                resolved = await intervention.wait_for_resolution(timeout=180)

                if resolved:
                    logger.info(f"[HumanSearch] Google CAPTCHA resolved, navigating back to search...")
                    # Wait for CAPTCHA solution to propagate
                    await asyncio.sleep(5)

                    # Extract the original search URL from the /sorry/ page's continue parameter
                    current_url = page.url
                    target_url = None

                    if '/sorry/' in current_url and 'continue=' in current_url:
                        from urllib.parse import urlparse, parse_qs, unquote
                        try:
                            parsed = urlparse(current_url)
                            params = parse_qs(parsed.query)
                            if 'continue' in params:
                                target_url = unquote(params['continue'][0])
                                logger.info(f"[HumanSearch] Extracted continue URL: {target_url[:80]}...")
                        except Exception as parse_error:
                            logger.warning(f"[HumanSearch] Failed to parse continue URL: {parse_error}")

                    # If we couldn't extract the URL, construct a fresh Google search
                    if not target_url:
                        from urllib.parse import quote_plus
                        target_url = f"https://www.google.com/search?q={quote_plus(query)}"
                        logger.info(f"[HumanSearch] Using fresh Google search URL")

                    # Navigate to the target URL
                    try:
                        logger.info(f"[HumanSearch] Navigating to: {target_url[:80]}...")
                        await page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
                        await asyncio.sleep(2)
                        await page.wait_for_load_state("networkidle", timeout=10000)
                        logger.info(f"[HumanSearch] Successfully navigated to search results")
                    except Exception as nav_error:
                        logger.warning(f"[HumanSearch] Navigation after resolution failed: {nav_error}")
                        # Try refreshing as fallback
                        await page.reload(wait_until="domcontentloaded", timeout=15000)
                else:
                    logger.warning(f"[HumanSearch] Intervention timeout, returning no results")
                    return []
            else:
                logger.warning(f"[HumanSearch] Human assist disabled, cannot extract results past Google blocker")
                return []

        # Extract results
        logger.info(f"[HumanSearch] Extracting search results...")
        result_elements = await page.query_selector_all('div.g')

        logger.info(f"[HumanSearch] Found {len(result_elements)} result elements")

        for i, elem in enumerate(result_elements[:max_results]):
            try:
                # Extract link
                link_elem = await elem.query_selector('a')
                url = await link_elem.get_attribute("href") if link_elem else ""

                # Extract title
                title_elem = await elem.query_selector('h3')
                title = await title_elem.inner_text() if title_elem else ""
                title = title.strip()

                # Extract snippet
                snippet_elem = await elem.query_selector('div[data-sncf]')
                if not snippet_elem:
                    snippet_elem = await elem.query_selector('div.VwiC3b')

                snippet = await snippet_elem.inner_text() if snippet_elem else ""
                snippet = snippet.strip()

                if url and title and url.startswith("http"):
                    results.append({
                        "url": url,
                        "title": title,
                        "snippet": snippet,
                        "position": i + 1
                    })
                    logger.info(f"[HumanSearch]   {i+1}. {title[:60]}...")
            except Exception as e:
                logger.warning(f"[HumanSearch] Error extracting result {i+1}: {e}")
                continue

        logger.info(f"[HumanSearch] Successfully extracted {len(results)} results")

        # Save session state
        await session_mgr.save_session_state(
            domain="google.com",
            session_id=session_id,
            context=context,
            user_id="default"
        )

        return results

    except Exception as e:
        logger.error(f"[HumanSearch] Google search failed: {e}", exc_info=True)
        return []

    finally:
        await page.close()


async def search_brave_human(
    query: str,
    max_results: int = 10,
    session_id: str = "default",
    location: str = "US",
    human_assist_allowed: bool = True
) -> List[Dict[str, Any]]:
    """
    Visit search.brave.com in a real browser, type search, extract results.

    Brave Search is privacy-focused and less aggressive with rate limiting than Google/DDG.

    Args:
        query: Search query string
        max_results: Maximum number of results to extract
        session_id: Session ID for cookie persistence
        location: User location (default "US")
        human_assist_allowed: Enable CAPTCHA intervention (default True)

    Returns:
        List of result dicts
    """
    from apps.services.tool_server.crawler_session_manager import get_crawler_session_manager
    from apps.services.tool_server.captcha_intervention import detect_blocker, request_intervention

    logger.info(f"[HumanSearch] Searching Brave for: {query[:60]} (max_results={max_results})")

    session_mgr = get_crawler_session_manager()
    context = await session_mgr.get_or_create_session(
        domain="search.brave.com",
        session_id=session_id
    )

    page = await context.new_page()
    results = []

    try:
        # Visit Brave Search
        brave_url = "https://search.brave.com/"
        logger.info(f"[HumanSearch] Visiting {brave_url}")
        await page.goto(brave_url, wait_until="networkidle", timeout=30000)

        # Session warmup
        await warmup_session(page, domain="search.brave.com")

        # Find search box (Brave uses id="searchbox")
        search_box = await page.wait_for_selector('input[name="q"]', timeout=10000)

        # Type query with human-like delays
        logger.info(f"[HumanSearch] Typing query...")
        await search_box.click()
        await search_box.fill("")
        for char in query:
            await search_box.type(char, delay=random.randint(50, 150))

        await asyncio.sleep(random.uniform(0.3, 0.7))

        # Submit search
        logger.info(f"[HumanSearch] Submitting search...")
        await page.keyboard.press("Enter")

        # Wait for results
        try:
            await page.wait_for_selector('div.snippet', timeout=15000)
        except Exception as e:
            logger.warning(f"[HumanSearch] Timeout waiting for Brave results: {e}")

        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            logger.warning(f"[HumanSearch] networkidle wait failed: {e}")

        # Check for blockers
        brave_content = await page.content()
        results_blocker = detect_blocker({
            "content": brave_content,
            "status": 200,
            "url": page.url,
            "screenshot_path": None,
            "blocked": False,
            "block_type": ""
        })

        if results_blocker and results_blocker["confidence"] >= 0.7:
            logger.warning(f"[HumanSearch] Blocker detected on Brave results: {results_blocker['type'].value}")

            # RATE_LIMIT: Fail fast
            if results_blocker["type"].value == "rate_limit":
                from apps.services.tool_server.search_rate_limiter import get_search_rate_limiter
                from apps.services.tool_server.search_engine_health import get_engine_health_tracker
                logger.warning(f"[HumanSearch] Brave returned no results, trying next...")
                get_search_rate_limiter().report_rate_limit("Brave")
                get_engine_health_tracker().report_failure("Brave", "rate_limit")
                return []

            # CAPTCHAs: Request human intervention
            if human_assist_allowed:
                cdp_url = await get_page_cdp_url(page)
                screenshot_path = f"panda_system_docs/scrape_staging/screenshots/brave_{session_id}_{int(asyncio.get_event_loop().time())}.png"
                await page.screenshot(path=screenshot_path, full_page=True)

                intervention = await request_intervention(
                    blocker_type=results_blocker["type"].value,
                    url=page.url,
                    screenshot_path=screenshot_path,
                    session_id=session_id,
                    blocker_details=results_blocker,
                    cdp_url=cdp_url
                )

                resolved = await intervention.wait_for_resolution(timeout=180)
                if not resolved:
                    logger.warning(f"[HumanSearch] Brave intervention timeout, returning no results")
                    return []

        # Extract results (Brave uses div.snippet for result containers)
        logger.info(f"[HumanSearch] Extracting Brave results...")
        result_elements = await page.query_selector_all('div.snippet')

        logger.info(f"[HumanSearch] Found {len(result_elements)} Brave result elements")

        for i, elem in enumerate(result_elements[:max_results]):
            try:
                # Extract title (in <a> tag with class="result-header")
                title_elem = await elem.query_selector('a.result-header')
                title = await title_elem.inner_text() if title_elem else ""
                title = title.strip()

                # Extract URL (from same <a> tag)
                url_elem = await elem.query_selector('a.result-header')
                url = await url_elem.get_attribute("href") if url_elem else ""

                # Extract snippet (in div.snippet-description)
                snippet_elem = await elem.query_selector('div.snippet-description')
                snippet = await snippet_elem.inner_text() if snippet_elem else ""
                snippet = snippet.strip()

                if url and title:
                    results.append({
                        "url": url,
                        "title": title,
                        "snippet": snippet,
                        "position": i + 1
                    })
                    logger.info(f"[HumanSearch]   {i+1}. {title[:60]}...")
            except Exception as e:
                logger.warning(f"[HumanSearch] Error extracting Brave result {i+1}: {e}")
                continue

        logger.info(f"[HumanSearch] Successfully extracted {len(results)} Brave results")

        # Save session state
        await session_mgr.save_session_state(
            domain="search.brave.com",
            session_id=session_id,
            context=context,
            user_id="default"
        )

        return results

    except Exception as e:
        logger.error(f"[HumanSearch] Brave search failed: {e}", exc_info=True)
        return []
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def search_with_fallback(
    query: str,
    max_results: int = 10,
    session_id: str = "default",
    location: str = "US",
    human_assist_allowed: bool = True
) -> List[Dict[str, Any]]:
    """
    Try multiple search engines until one succeeds.

    RATE LIMITING & CACHING:
    - Checks cache before hitting search engines
    - Enforces minimum 2s delay between searches (global rate limiter)
    - Adds 3s backoff when switching from DDG to Google
    - Reports rate limits for exponential backoff

    Priority order:
    1. DuckDuckGo (no login required, privacy-focused)
    2. Google (if DDG fails)
    3. Brave Search (privacy-focused, less aggressive blocking)

    Args:
        query: Search query string
        max_results: Maximum number of results
        session_id: Session ID for cookie persistence
        location: User location
        human_assist_allowed: Enable human intervention for CAPTCHAs

    Returns:
        List of result dicts from whichever engine succeeded
    """
    from apps.services.tool_server.search_rate_limiter import get_search_rate_limiter
    from apps.services.tool_server.serp_cache import get_serp_cache

    rate_limiter = get_search_rate_limiter()
    serp_cache = get_serp_cache()

    engines = [
        ("DuckDuckGo", search_duckduckgo_human),
        ("Google", search_google_human),
        ("Brave", search_brave_human)
    ]

    for idx, (engine_name, engine_func) in enumerate(engines):
        # Check cache first
        cached_results = serp_cache.get(query, engine_name.lower(), session_id)
        if cached_results is not None:
            logger.info(f"[HumanSearch] Using cached {engine_name} results ({len(cached_results)} results)")
            rate_limiter.report_success()
            return cached_results

        # Add backoff delay when switching engines (DDG → Google)
        if idx > 0:
            logger.info("[HumanSearch] Switching engines, adding 3s backoff to avoid immediate hammer...")
            await asyncio.sleep(3.0)

        # Enforce rate limit
        await rate_limiter.acquire(query, engine_name)

        try:
            logger.info(f"[HumanSearch] Trying {engine_name}...")
            results = await engine_func(
                query=query,
                max_results=max_results,
                session_id=session_id,
                location=location,
                human_assist_allowed=human_assist_allowed
            )

            if results and len(results) > 0:
                logger.info(f"[HumanSearch] {engine_name} succeeded with {len(results)} results")
                # Cache successful results
                serp_cache.put(query, engine_name.lower(), results, session_id)
                rate_limiter.report_success()
                return results
            else:
                logger.warning(f"[HumanSearch] {engine_name} returned no results, trying next...")
                # Report potential rate limit (empty results might indicate blocking)
                rate_limiter.report_rate_limit(engine_name)
        except Exception as e:
            logger.warning(f"[HumanSearch] {engine_name} failed: {e}, trying next...")
            rate_limiter.report_rate_limit(engine_name)
            continue

    # All failed
    logger.error(f"[HumanSearch] All search engines failed for: {query[:60]}")
    return []


# Convenience function for backward compatibility
async def search(
    query: str,
    k: int = 10,
    session_id: str = "default",
    location: str = "US",
    human_assist_allowed: bool = True
) -> List[Dict[str, Any]]:
    """
    Human-style search with fallback (drop-in replacement for old API-based search).

    Args:
        query: Search query
        k: Max results
        session_id: Session ID
        location: User location

    Returns:
        List of search results
    """
    return await search_with_fallback(
        query=query,
        max_results=k,
        session_id=session_id,
        location=location,
        human_assist_allowed=human_assist_allowed
    )


class HumanSearchEngine:
    """
    Class wrapper around search functions for apps/tools/internet_research/browser.py.

    Provides an object-oriented interface to the human-like search functions.
    """

    def __init__(self, human_assist_allowed: bool = True):
        """
        Initialize the search engine.

        Args:
            human_assist_allowed: Whether to allow human intervention for CAPTCHAs
        """
        self.human_assist_allowed = human_assist_allowed

    async def search(
        self,
        query: str,
        num_results: int = 10,
        session_id: str = "default",
        location: str = "US",
    ) -> List[Dict[str, Any]]:
        """
        Execute a human-like web search with fallback across engines.

        Args:
            query: Search query string
            num_results: Maximum number of results to return
            session_id: Session ID for cookie persistence
            location: User location (default "US")

        Returns:
            List of result dicts with keys: url, title, snippet
        """
        return await search_with_fallback(
            query=query,
            max_results=num_results,
            session_id=session_id,
            location=location,
            human_assist_allowed=self.human_assist_allowed
        )
