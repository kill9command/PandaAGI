"""
orchestrator/shared/browser_factory.py

Centralized browser instance factory for consistent browser configuration.

Usage:
    from orchestrator.shared.browser_factory import get_browser_type, launch_browser

    # Get the configured browser type
    browser_type = get_browser_type(playwright)
    browser = await browser_type.launch(headless=True)

    # Or use the convenience function
    browser = await launch_browser(playwright, headless=True)
"""

import os
import logging
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from playwright.async_api import Playwright, Browser, BrowserType

logger = logging.getLogger(__name__)

def _get_browser_engine() -> str:
    """Get browser engine setting (read fresh from env each time for proper dotenv support)."""
    return os.environ.get('BROWSER_ENGINE', 'firefox').lower()


# Backward compatibility: expose as a property-like function for imports
# Usage: from browser_factory import BROWSER_ENGINE (will be 'firefox' or 'chromium')
# This is evaluated lazily when accessed
class _BrowserEngineProperty:
    def __repr__(self):
        return _get_browser_engine()
    def __str__(self):
        return _get_browser_engine()
    def __eq__(self, other):
        return _get_browser_engine() == other
    def lower(self):
        return _get_browser_engine()

BROWSER_ENGINE = _BrowserEngineProperty()


def get_browser_type(playwright: 'Playwright') -> 'BrowserType':
    """
    Get the configured browser type from Playwright instance.

    Returns chromium or firefox based on BROWSER_ENGINE env var.
    Default: firefox (more stable on heavy JS sites)
    """
    engine = _get_browser_engine()
    if engine == 'chromium':
        logger.debug("[BrowserFactory] Using Chromium browser engine")
        return playwright.chromium
    else:
        logger.debug("[BrowserFactory] Using Firefox browser engine")
        return playwright.firefox


async def launch_browser(
    playwright: 'Playwright',
    headless: bool = True,
    args: Optional[List[str]] = None,
    **kwargs
) -> 'Browser':
    """
    Launch a browser with consistent configuration.

    Args:
        playwright: Playwright instance
        headless: Run in headless mode (default: True)
        args: Additional browser args (Chromium-specific args are filtered for Firefox)
        **kwargs: Additional launch options

    Returns:
        Browser instance
    """
    engine = _get_browser_engine()
    browser_type = get_browser_type(playwright)

    # Filter Chromium-specific args if using Firefox
    if engine != 'chromium' and args:
        # Firefox doesn't support these Chromium args
        chromium_only_args = {
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
            '--disable-extensions',
        }
        args = [a for a in args if a not in chromium_only_args and not a.startswith('--js-flags')]

    launch_kwargs = {'headless': headless, **kwargs}
    if args and engine == 'chromium':
        launch_kwargs['args'] = args

    logger.info(f"[BrowserFactory] Launching {engine} browser (headless={headless})")
    return await browser_type.launch(**launch_kwargs)


def get_default_user_agent() -> str:
    """Get a default user agent string for the configured browser."""
    engine = _get_browser_engine()
    if engine == 'chromium':
        return 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    else:
        return 'Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0'


def get_sync_browser_type(playwright):
    """
    Get the configured browser type from sync Playwright instance.

    For use with sync_playwright() contexts.
    """
    engine = _get_browser_engine()
    if engine == 'chromium':
        return playwright.chromium
    else:
        return playwright.firefox
