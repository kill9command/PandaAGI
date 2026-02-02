"""
Test different search engine configurations to find what works.

This script tests various combinations of:
- Browser settings (headless/headed, different args)
- Stealth configurations
- User agents and fingerprints
- Search engines (DuckDuckGo, Google, Brave)
- Request timing and delays

Author: Claude Code
Created: 2025-11-19
"""
import sys
sys.path.insert(0, '.')

import asyncio
import logging
from playwright.async_api import async_playwright, Browser, BrowserContext
from apps.services.orchestrator.stealth_injector import inject_stealth
from apps.services.orchestrator.browser_fingerprint import BrowserFingerprint
import random
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_search(
    browser: Browser,
    config_name: str,
    use_stealth: bool = True,
    headless: bool = True,
    extra_args: list = None,
    user_agent: str = None,
    viewport: dict = None,
    search_engine: str = "duckduckgo"
) -> dict:
    """
    Test a specific browser configuration.

    Returns:
        dict with success status and details
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"TESTING: {config_name}")
    logger.info(f"  Stealth: {use_stealth}, Headless: {headless}")
    logger.info(f"  Search Engine: {search_engine}")
    logger.info(f"{'='*60}")

    result = {
        "config": config_name,
        "success": False,
        "error": None,
        "results_found": 0,
        "blocked": False,
        "response_time": 0
    }

    try:
        start_time = time.time()

        # Create context with specified settings
        context_options = {
            "viewport": viewport or {"width": 1920, "height": 1080},
            "user_agent": user_agent,
            "locale": "en-US",
            "timezone_id": "America/New_York",
        }

        # Remove None values
        context_options = {k: v for k, v in context_options.items() if v is not None}

        context = await browser.new_context(**context_options)

        # Apply stealth if requested
        if use_stealth:
            await inject_stealth(context, log=True)

        page = await context.new_page()

        # Test based on search engine
        if search_engine == "duckduckgo":
            # Visit homepage first (warmup)
            await page.goto("https://duckduckgo.com/", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(random.uniform(2, 4))

            # Perform search
            query = "test search"
            search_url = f"https://duckduckgo.com/?q={query}&t=h_&ia=web"
            await page.goto(search_url, wait_until="networkidle", timeout=30000)

            # Check for rate limit
            content = await page.content()
            if "418" in content or "blocked" in content.lower():
                result["blocked"] = True
                result["error"] = "Rate limited (418 or blocked)"
                logger.warning(f"  ❌ BLOCKED: Rate limit detected")
            else:
                # Try to find results
                try:
                    await page.wait_for_selector("article[data-testid='result']", timeout=5000)
                    results = await page.query_selector_all("article[data-testid='result']")
                    result["results_found"] = len(results)
                    result["success"] = True
                    logger.info(f"  ✅ SUCCESS: Found {len(results)} results")
                except Exception as e:
                    result["error"] = f"No results selector: {str(e)}"
                    logger.warning(f"  ⚠️  No results found: {e}")

        elif search_engine == "google":
            await page.goto("https://www.google.com/", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(random.uniform(2, 4))

            query = "test search"
            search_url = f"https://www.google.com/search?q={query}"
            await page.goto(search_url, wait_until="networkidle", timeout=30000)

            content = await page.content()
            if "unusual traffic" in content.lower() or "captcha" in content.lower():
                result["blocked"] = True
                result["error"] = "Rate limited (unusual traffic)"
                logger.warning(f"  ❌ BLOCKED: Unusual traffic detected")
            else:
                try:
                    await page.wait_for_selector("div#search", timeout=5000)
                    result["success"] = True
                    logger.info(f"  ✅ SUCCESS: Google search page loaded")
                except Exception as e:
                    result["error"] = f"No results: {str(e)}"
                    logger.warning(f"  ⚠️  No results: {e}")

        elif search_engine == "brave":
            await page.goto("https://search.brave.com/", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(random.uniform(2, 4))

            query = "test search"
            search_url = f"https://search.brave.com/search?q={query}"
            await page.goto(search_url, wait_until="networkidle", timeout=30000)

            content = await page.content()
            if "captcha" in content.lower():
                result["blocked"] = True
                result["error"] = "CAPTCHA detected"
                logger.warning(f"  ❌ BLOCKED: CAPTCHA")
            else:
                try:
                    await page.wait_for_selector("div.snippet", timeout=5000)
                    result["success"] = True
                    logger.info(f"  ✅ SUCCESS: Brave search page loaded")
                except Exception as e:
                    result["error"] = f"No results: {str(e)}"
                    logger.warning(f"  ⚠️  No results: {e}")

        result["response_time"] = time.time() - start_time

        await context.close()

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  ❌ ERROR: {e}")

    return result


async def main():
    """Run all test configurations."""
    logger.info("Starting Search Engine Configuration Tests")
    logger.info("=" * 80)

    async with async_playwright() as p:
        # Launch browser with minimal detection
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
            ]
        )

        results = []

        # Test configurations
        configs = [
            # Baseline: Stealth + DuckDuckGo
            {
                "name": "Stealth + DuckDuckGo (baseline)",
                "use_stealth": True,
                "headless": True,
                "search_engine": "duckduckgo"
            },

            # No stealth (control)
            {
                "name": "No Stealth + DuckDuckGo (control)",
                "use_stealth": False,
                "headless": True,
                "search_engine": "duckduckgo"
            },

            # Different user agents
            {
                "name": "Stealth + Chrome UA + DuckDuckGo",
                "use_stealth": True,
                "headless": True,
                "search_engine": "duckduckgo",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            {
                "name": "Stealth + Firefox UA + DuckDuckGo",
                "use_stealth": True,
                "headless": True,
                "search_engine": "duckduckgo",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
            },

            # Different viewports
            {
                "name": "Stealth + Mobile Viewport + DuckDuckGo",
                "use_stealth": True,
                "headless": True,
                "search_engine": "duckduckgo",
                "viewport": {"width": 390, "height": 844}
            },

            # Test other search engines
            {
                "name": "Stealth + Google",
                "use_stealth": True,
                "headless": True,
                "search_engine": "google"
            },
            {
                "name": "Stealth + Brave",
                "use_stealth": True,
                "headless": True,
                "search_engine": "brave"
            },
        ]

        # Run tests with delays between them
        for i, config in enumerate(configs):
            logger.info(f"\n[Test {i+1}/{len(configs)}]")

            result = await test_search(
                browser,
                config_name=config["name"],
                use_stealth=config.get("use_stealth", True),
                headless=config.get("headless", True),
                user_agent=config.get("user_agent"),
                viewport=config.get("viewport"),
                search_engine=config.get("search_engine", "duckduckgo")
            )

            results.append(result)

            # Wait between tests to avoid triggering rate limits
            if i < len(configs) - 1:
                delay = random.uniform(5, 10)
                logger.info(f"  Waiting {delay:.1f}s before next test...")
                await asyncio.sleep(delay)

        await browser.close()

        # Print summary
        logger.info("\n" + "=" * 80)
        logger.info("TEST SUMMARY")
        logger.info("=" * 80)

        successful = [r for r in results if r["success"]]
        blocked = [r for r in results if r["blocked"]]

        logger.info(f"\n✅ Successful: {len(successful)}/{len(results)}")
        logger.info(f"❌ Blocked: {len(blocked)}/{len(results)}")
        logger.info(f"⚠️  Other errors: {len(results) - len(successful) - len(blocked)}/{len(results)}")

        if successful:
            logger.info("\n✅ WORKING CONFIGURATIONS:")
            for r in successful:
                logger.info(f"  - {r['config']} ({r['response_time']:.2f}s, {r['results_found']} results)")

        if blocked:
            logger.info("\n❌ BLOCKED CONFIGURATIONS:")
            for r in blocked:
                logger.info(f"  - {r['config']}: {r['error']}")

        logger.info("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
