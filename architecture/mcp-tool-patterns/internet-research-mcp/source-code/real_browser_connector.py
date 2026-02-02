"""
Real Browser Connector - Connect to user's actual Chrome/Firefox instance.

Instead of launching fresh Chromium, connect to the user's real browser
with their real profile, cookies, and login sessions.

This makes automation behave exactly like the user because it IS the user.

Architecture:
1. User starts Chrome with remote debugging: chrome --remote-debugging-port=9222
2. We connect via CDP (Chrome DevTools Protocol)
3. Automation uses user's real sessions, cookies, profiles
4. Sites see normal human fingerprints

Part of Pandora's human-assisted automation system.
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import os

from orchestrator.shared.browser_factory import get_browser_type

logger = logging.getLogger(__name__)


class RealBrowserConnector:
    """
    Connects to user's real Chrome/Firefox instance for human-like automation.

    This allows automation to:
    - Use user's actual browser profile
    - Inherit existing login sessions
    - Have real human fingerprints
    - Avoid fresh browser detection
    """

    def __init__(
        self,
        cdp_url: str = "http://localhost:9222",
        use_real_profile: bool = True
    ):
        """
        Initialize connector.

        Args:
            cdp_url: Chrome DevTools Protocol endpoint URL
            use_real_profile: Whether to use real browser profile (vs fresh)
        """
        self.cdp_url = cdp_url
        self.use_real_profile = use_real_profile
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.connected = False

    async def connect(self) -> Browser:
        """
        Connect to running Chrome instance via CDP.

        Returns:
            Connected Browser instance

        Raises:
            Exception: If connection fails

        Example:
            # Terminal 1: Start Chrome with debugging
            $ google-chrome --remote-debugging-port=9222 --user-data-dir="/tmp/chrome-profile"

            # Terminal 2: Connect from Python
            connector = RealBrowserConnector()
            browser = await connector.connect()
        """
        if self.connected:
            logger.info("[RealBrowser] Already connected")
            return self.browser

        try:
            self.playwright = await async_playwright().start()

            # Connect to existing Chrome instance
            logger.info(f"[RealBrowser] Connecting to Chrome at {self.cdp_url}")
            self.browser = await self.playwright.chromium.connect_over_cdp(self.cdp_url)

            self.connected = True

            # Log connection details
            contexts = self.browser.contexts
            logger.info(
                f"[RealBrowser] Connected successfully! "
                f"Contexts: {len(contexts)}, "
                f"CDP: {self.cdp_url}"
            )

            return self.browser

        except Exception as e:
            logger.error(f"[RealBrowser] Connection failed: {e}")
            logger.error(
                "\nTo fix:\n"
                "1. Start Chrome with remote debugging:\n"
                "   google-chrome --remote-debugging-port=9222 --user-data-dir=\"/tmp/chrome-profile\"\n"
                "2. Or set CDP_URL environment variable to your Chrome's debugging URL\n"
            )
            raise

    async def get_or_create_page(
        self,
        reuse_existing: bool = True
    ) -> Page:
        """
        Get existing page or create new one in user's browser.

        Args:
            reuse_existing: Reuse existing tab if available

        Returns:
            Page instance ready to use
        """
        if not self.connected:
            await self.connect()

        # Get default context (user's main browser context)
        contexts = self.browser.contexts
        if not contexts:
            raise Exception("[RealBrowser] No browser contexts found")

        context = contexts[0]

        # Reuse existing page if requested
        if reuse_existing:
            pages = context.pages
            if pages:
                logger.info(f"[RealBrowser] Reusing existing page: {pages[0].url}")
                return pages[0]

        # Create new page
        page = await context.new_page()
        logger.info("[RealBrowser] Created new page in user's browser")
        return page

    async def disconnect(self):
        """
        Disconnect from browser (leaves browser running).
        """
        if self.browser:
            # Note: We DON'T call browser.close() because that would close user's browser
            # We just disconnect our automation
            logger.info("[RealBrowser] Disconnecting (browser stays open)")
            self.browser = None

        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

        self.connected = False

    async def __aenter__(self):
        """Context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        await self.disconnect()


class ProfileBrowserLauncher:
    """
    Alternative: Launch new Chrome with user's real profile.

    This gives us control over the browser lifecycle while still
    using the user's real profile data.
    """

    def __init__(
        self,
        profile_dir: Optional[str] = None,
        headless: bool = False
    ):
        """
        Initialize launcher.

        Args:
            profile_dir: Path to Chrome user data directory
                         Default: Uses system default profile
            headless: Whether to run headless (not recommended)
        """
        self.profile_dir = profile_dir or self._get_default_profile()
        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None

    def _get_default_profile(self) -> str:
        """
        Get default Chrome profile directory for current OS.

        Returns:
            Path to Chrome user data directory
        """
        import platform

        system = platform.system()
        home = os.path.expanduser("~")

        if system == "Linux":
            return os.path.join(home, ".config", "google-chrome")
        elif system == "Darwin":  # macOS
            return os.path.join(home, "Library", "Application Support", "Google", "Chrome")
        elif system == "Windows":
            return os.path.join(home, "AppData", "Local", "Google", "Chrome", "User Data")
        else:
            raise Exception(f"Unsupported OS: {system}")

    async def launch(self) -> Browser:
        """
        Launch Chrome with user's profile.

        Returns:
            Browser instance with user's profile loaded
        """
        try:
            self.playwright = await async_playwright().start()

            browser_type = get_browser_type(self.playwright)
            logger.info(f"[ProfileBrowser] Launching {browser_type.name} with profile: {self.profile_dir}")

            # Launch browser with user profile
            launch_args = []
            if browser_type.name == 'chromium':
                launch_args = [
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                ]

            self.browser = await browser_type.launch_persistent_context(
                user_data_dir=self.profile_dir,
                headless=self.headless,
                args=launch_args,
                # Keep user's existing settings
                accept_downloads=True,
                ignore_https_errors=False,
            )

            logger.info("[ProfileBrowser] Launched successfully with user profile")
            return self.browser

        except Exception as e:
            logger.error(f"[ProfileBrowser] Launch failed: {e}")
            raise

    async def close(self):
        """Close browser and cleanup"""
        if self.browser:
            await self.browser.close()

        if self.playwright:
            await self.playwright.stop()


# Convenience functions

async def connect_to_user_browser(
    cdp_url: Optional[str] = None
) -> tuple[Browser, Page]:
    """
    Quick connect to user's Chrome instance.

    Args:
        cdp_url: Chrome DevTools Protocol URL (default: env CDP_URL or localhost:9222)

    Returns:
        (browser, page) tuple ready to use

    Example:
        browser, page = await connect_to_user_browser()
        await page.goto("https://example.com")
        # Page uses user's real profile, cookies, sessions
    """
    cdp_url = cdp_url or os.getenv("CDP_URL", "http://localhost:9222")

    connector = RealBrowserConnector(cdp_url=cdp_url)
    browser = await connector.connect()
    page = await connector.get_or_create_page(reuse_existing=True)

    return browser, page


async def launch_with_user_profile(
    profile_dir: Optional[str] = None
) -> tuple[Browser, Page]:
    """
    Quick launch Chrome with user's profile.

    Args:
        profile_dir: Path to Chrome profile (default: system default)

    Returns:
        (browser, page) tuple ready to use
    """
    launcher = ProfileBrowserLauncher(profile_dir=profile_dir)
    browser = await launcher.launch()

    # Get first page
    pages = browser.pages
    if pages:
        page = pages[0]
    else:
        page = await browser.new_page()

    return browser, page


if __name__ == "__main__":
    # Test connection to user's browser
    async def test():
        print("Testing connection to user's Chrome...")
        print("\nMake sure Chrome is running with:")
        print("  google-chrome --remote-debugging-port=9222\n")

        try:
            browser, page = await connect_to_user_browser()
            print(f"✓ Connected!")
            print(f"  Current URL: {page.url}")
            print(f"  Browser contexts: {len(browser.contexts)}")

            # Navigate to test
            await page.goto("https://www.google.com")
            print(f"✓ Navigated to Google")
            print(f"  Title: {await page.title()}")

        except Exception as e:
            print(f"✗ Connection failed: {e}")

    asyncio.run(test())
