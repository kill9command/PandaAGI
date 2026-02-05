"""
orchestrator/playwright_stealth_mcp.py

Enhanced Playwright wrapper with captcha/bot detection and stealth mode.

Handles:
1. Bot detection (Cloudflare, reCAPTCHA, access denied)
2. Stealth mode (realistic user agent, viewport, headers)
3. Graceful degradation (return partial results when blocked)
4. Domain learning (track which domains block us)
"""
from __future__ import annotations
import logging
import random
import time
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from apps.services.tool_server.shared.browser_factory import get_browser_type, BROWSER_ENGINE

logger = logging.getLogger(__name__)

# Known-good domains (don't use heavy bot protection)
KNOWN_GOOD_DOMAINS = set([
    # Will be populated over time as we discover working domains
])

# Known-bad domains (always block automation)
KNOWN_BAD_DOMAINS = set([
    # Will be populated when we detect blocks
])

# Realistic user agents (rotate randomly)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")
    except Exception:
        return "unknown"


def _detect_bot_challenge(html: str, title: str, url: str = "") -> tuple[bool, str]:
    """
    Detect if page is a bot challenge/captcha.

    Returns:
        (is_blocked, block_type)
    """
    html_lower = html.lower()
    title_lower = title.lower()
    url_lower = url.lower()

    # URL-based detection (highest confidence)
    url_block_patterns = [
        "/blocked", "/sorry/", "/challenge", "/verify",
        "blocked?url=", "captcha", "/static-pages/418"
    ]
    if any(pattern in url_lower for pattern in url_block_patterns):
        return (True, "url_block_pattern")

    # Cloudflare challenge
    if any(indicator in html_lower for indicator in [
        "checking your browser",
        "cloudflare",
        "ray id:",
        "enable javascript and cookies"
    ]):
        return (True, "cloudflare_challenge")

    # reCAPTCHA / hCaptcha
    if any(indicator in html_lower for indicator in [
        "recaptcha",
        "g-recaptcha",
        "hcaptcha",
        "h-captcha",
        "captcha"
    ]):
        return (True, "recaptcha")

    # Generic human verification (includes Walmart "Robot or human?")
    human_verification_keywords = [
        "robot or human",  # Walmart
        "are you a robot",
        "are you human",
        "verify you are human",
        "prove you're not a robot",
        "human verification",
        "press and hold",  # Walmart button
        "press & hold",
        "confirm you are human",
        "i'm not a robot",
    ]
    if any(indicator in html_lower for indicator in human_verification_keywords):
        return (True, "human_verification")

    # Access denied pages
    if any(indicator in title_lower for indicator in [
        "access denied",
        "403 forbidden",
        "blocked",
        "security check"
    ]) or any(indicator in html_lower for indicator in [
        "access denied",
        "you have been blocked",
        "your ip has been blocked"
    ]):
        return (True, "access_denied")

    # Very short HTML (likely error page)
    if len(html) < 500:
        return (True, "empty_or_error")

    return (False, "")


async def fetch(
    url: str,
    strategy: str = "auto",
    wait_until: str = "networkidle",
    timeout: int = 30,
    screenshot: bool = False,
    screenshot_dir: str = "panda_system_docs/scrape_staging/screenshots",
    use_stealth: bool = True,
    context: Optional[Any] = None,  # Optional browser context to reuse
) -> Dict[str, Any]:
    """
    Fetch page with bot detection and stealth mode.

    Args:
        url: URL to fetch
        strategy: "auto", "stealth", "basic"
        wait_until: Playwright wait condition
        timeout: Navigation timeout in seconds
        screenshot: Capture screenshot
        screenshot_dir: Screenshot directory
        use_stealth: Enable stealth mode (realistic browser behavior)

    Returns:
        {
            "success": bool,
            "url": str,
            "status": int,
            "raw_html": str,
            "text_content": str,
            "title": str,
            "screenshot_path": str | None,
            "blocked": bool,
            "block_type": str,
            "error": str | None
        }
    """
    domain = _extract_domain(url)

    # DISABLED: Preemptive blocking prevents legitimate sites from being accessed
    # Sites should be allowed to retry - temporary failures shouldn't be permanent
    # if domain in KNOWN_BAD_DOMAINS:
    #     logger.warning(f"[PlaywrightStealth] Domain {domain} known to block automation, skipping fetch")
    #     return {
    #         "success": False,
    #         "url": url,
    #         "status": 403,
    #         "raw_html": "",
    #         "text_content": "",
    #         "title": "",
    #         "screenshot_path": None,
    #         "blocked": True,
    #         "block_type": "known_bad_domain",
    #         "error": "Domain known to block automation"
    #     }

    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        logger.error(f"[PlaywrightStealth] Playwright not available: {e}")
        return {
            "success": False,
            "url": url,
            "status": 500,
            "raw_html": "",
            "text_content": "",
            "title": "",
            "screenshot_path": None,
            "blocked": False,
            "block_type": "",
            "error": f"Playwright not installed: {e}"
        }

    result = {
        "success": False,
        "url": url,
        "status": 0,
        "raw_html": "",
        "text_content": "",
        "title": "",
        "screenshot_path": None,
        "blocked": False,
        "block_type": "",
        "error": None
    }

    try:
        # Use provided context if available, otherwise create new browser
        should_close_browser = context is None

        if context:
            # Reuse existing context (with saved cookies/session)
            logger.info(f"[PlaywrightStealth] Reusing existing browser context for {url[:60]}")
            page = await context.new_page()
            p = None
            browser = None
        else:
            # Create new browser and context
            p = await async_playwright().start()

            # Launch browser with stealth settings
            browser_type = get_browser_type(p)
            launch_args = []
            if use_stealth and BROWSER_ENGINE == 'chromium':
                launch_args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ]

            browser = await browser_type.launch(
                headless=True,
                args=launch_args
            )

            # === STEALTH ENHANCEMENT: Randomized viewport and fingerprint ===
            # Common desktop resolutions (randomize to avoid fingerprinting)
            viewports = [
                {"width": 1920, "height": 1080},  # Full HD
                {"width": 1366, "height": 768},   # HD
                {"width": 1536, "height": 864},   # HD+
                {"width": 1440, "height": 900},   # WXGA+
                {"width": 2560, "height": 1440},  # QHD
            ]

            # Common timezones (randomize to avoid location fingerprinting)
            timezones = [
                "America/New_York",
                "America/Chicago",
                "America/Los_Angeles",
                "America/Denver",
            ]

            # Create context with realistic settings
            context_options = {
                "viewport": random.choice(viewports) if use_stealth else {"width": 1920, "height": 1080},
                "locale": "en-US",
                "timezone_id": random.choice(timezones) if use_stealth else "America/New_York",
            }

            if use_stealth:
                # Rotate user agent
                context_options["user_agent"] = random.choice(USER_AGENTS)

            context = await browser.new_context(**context_options)

            # Inject stealth JavaScript to bypass bot detection
            from apps.services.tool_server.stealth_injector import inject_stealth
            await inject_stealth(context, log=True)

            page = await context.new_page()

        # Set realistic timeout (for both new and reused contexts)
        page.set_default_navigation_timeout(int(timeout * 1000))

        # === STEALTH ENHANCEMENT: Random delay before navigation ===
        # Mimics human behavior - people don't navigate instantly
        if use_stealth:
            import asyncio
            delay = random.uniform(1.0, 3.0)  # 1-3 second delay
            logger.debug(f"[PlaywrightStealth] Human-like delay: {delay:.1f}s before navigation")
            await asyncio.sleep(delay)

        # Navigate
        logger.info(f"[PlaywrightStealth] Navigating to {url[:60]} with wait_until={wait_until}, timeout={timeout}s")
        response = await page.goto(url, wait_until=wait_until)
        result["status"] = response.status if response else 0
        logger.info(f"[PlaywrightStealth] Navigation complete: HTTP {result['status']}")

        # Get page content
        html = await page.content()
        result["raw_html"] = html

        # Extract text content (strip HTML tags)
        try:
            text_content = await page.inner_text("body")
            result["text_content"] = text_content
        except Exception:
            result["text_content"] = html

        # Get title
        try:
            result["title"] = await page.title()
        except Exception:
            result["title"] = url.split("/")[-1] or url

        # Detect bot challenge
        is_blocked, block_type = _detect_bot_challenge(html, result["title"])
        result["blocked"] = is_blocked
        result["block_type"] = block_type

        if is_blocked:
            logger.warning(
                f"[PlaywrightStealth] Bot challenge detected: {block_type} on {url[:60]}"
            )
            # DISABLED: Don't permanently blocklist domains - temporary failures shouldn't be permanent
            # Let intervention manager or retry logic handle this instead
            # KNOWN_BAD_DOMAINS.add(domain)
            result["success"] = False
            result["error"] = f"Bot challenge detected: {block_type}"
        else:
            # Success - add to known good domains
            KNOWN_GOOD_DOMAINS.add(domain)
            result["success"] = True

        # Screenshot if requested
        if screenshot:
            try:
                Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
                uid = url.replace("://", "_").replace("/", "_")[:120]
                sp = Path(screenshot_dir) / f"{uid}.png"
                await page.screenshot(path=str(sp), full_page=True)
                result["screenshot_path"] = str(sp)
                logger.info(f"[PlaywrightStealth] Screenshot saved: {sp}")
            except Exception as e:
                logger.warning(f"[PlaywrightStealth] Screenshot failed: {e}")

        # Close page when context was provided (we created a new page in that context)
        # This prevents page accumulation in visible browser mode
        if not should_close_browser and page:
            try:
                await page.close()
            except Exception as close_err:
                logger.debug(f"[PlaywrightStealth] Page close: {close_err}")

        # Only close browser if we created it (not if context was provided)
        if should_close_browser and browser:
            await browser.close()
        if should_close_browser and p:
            await p.stop()

    except Exception as e:
        logger.error(f"[PlaywrightStealth] Fetch failed for {url[:60]}: {e}")
        result["error"] = str(e)
        result["success"] = False

    return result


def get_domain_stats() -> Dict[str, Any]:
    """
    Get statistics about known good/bad domains.

    Returns:
        {
            "known_good_count": int,
            "known_bad_count": int,
            "known_good_domains": list,
            "known_bad_domains": list
        }
    """
    return {
        "known_good_count": len(KNOWN_GOOD_DOMAINS),
        "known_bad_count": len(KNOWN_BAD_DOMAINS),
        "known_good_domains": sorted(list(KNOWN_GOOD_DOMAINS)),
        "known_bad_domains": sorted(list(KNOWN_BAD_DOMAINS))
    }


def clear_domain_cache():
    """Clear known good/bad domain lists (for testing)."""
    KNOWN_GOOD_DOMAINS.clear()
    KNOWN_BAD_DOMAINS.clear()
    logger.info("[PlaywrightStealth] Domain cache cleared")


def fetch_page(url: str, wait_until: str = "networkidle", timeout: int = 30, screenshot: bool = False, screenshot_dir: str = "panda_system_docs/scrape_staging/screenshots") -> Dict[str, Any]:
    """
    Synchronous wrapper for backwards compatibility with web_fetcher.py.

    Note: This uses asyncio.run() internally, which may not work in all contexts.
    Prefer using the async fetch() function directly when possible.
    """
    import asyncio
    result = asyncio.run(fetch(
        url=url,
        wait_until=wait_until,
        timeout=timeout,
        screenshot=screenshot,
        screenshot_dir=screenshot_dir,
        strategy="auto",
        use_stealth=True
    ))
    return {
        "url": result.get("url", url),
        "status": result.get("status", 0),
        "raw_html": result.get("raw_html", ""),
        "title": result.get("title", ""),
        "screenshot_path": result.get("screenshot_path")
    }
