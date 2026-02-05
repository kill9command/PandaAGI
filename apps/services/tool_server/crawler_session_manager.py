"""
Browser session management for human-assisted web crawling.

Manages long-lived Playwright browser contexts with persistent state:
- Cookie/storage persistence per domain
- Browser fingerprint consistency
- TTL-based cleanup
- Session isolation per user

Part of Panda's human-in-the-loop research architecture.
"""

from playwright.async_api import async_playwright, BrowserContext, Browser, Playwright
from pathlib import Path
import json
import asyncio
import os
import shutil
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import logging

from apps.services.tool_server.shared.browser_factory import get_browser_type

logger = logging.getLogger(__name__)

# Maximum pages before browser restart to prevent memory leaks and connection issues
# Browser typically crashes after ~18-20 pages due to memory exhaustion
MAX_PAGES_BEFORE_RESTART = int(os.getenv("BROWSER_MAX_PAGES_BEFORE_RESTART", "15"))


class CrawlerSession:
    """Single browser session for a domain"""
    
    def __init__(
        self,
        domain: str,
        session_id: str,
        user_id: str,
        context: BrowserContext,
        fingerprint: Dict
    ):
        self.domain = domain
        self.session_id = session_id
        self.user_id = user_id
        self.context = context
        self.fingerprint = fingerprint
        self.created_at = datetime.now()
        self.last_used = datetime.now()
        self.page_count = 0

    def is_expired(self, ttl_hours: Optional[int] = None) -> bool:
        """
        Check if session has expired.

        Args:
            ttl_hours: TTL in hours. If None, session never expires (persistent).

        Returns:
            True if expired, False otherwise
        """
        if ttl_hours is None:
            # Persistent session - never expires
            return False
        return datetime.now() - self.created_at > timedelta(hours=ttl_hours)

    def touch(self):
        """Update last_used timestamp"""
        self.last_used = datetime.now()
        self.page_count += 1

    async def cleanup_excess_pages(self, keep_first: bool = True):
        """
        Close excess pages in the context to prevent blank tab accumulation.

        In visible browser mode (headless=false), extra pages appear as
        visible tabs. This method closes all but the first/active page.

        Args:
            keep_first: If True, keeps the first page; if False, closes all pages.
        """
        try:
            pages = self.context.pages
            if not pages:
                return

            # Keep the first page, close the rest
            pages_to_close = pages[1:] if keep_first else pages

            for page in pages_to_close:
                try:
                    # Don't close pages that are actively being used (check URL)
                    url = page.url
                    if url in ("about:blank", "chrome://newtab/", ""):
                        await page.close()
                        logger.debug(f"[CrawlerSession] Closed blank page: {url}")
                except Exception as e:
                    logger.debug(f"[CrawlerSession] Page close error (may be already closed): {e}")

        except Exception as e:
            logger.warning(f"[CrawlerSession] Error cleaning up pages: {e}")


class CrawlerSessionManager:
    """Manages browser contexts for persistent crawling sessions"""

    def __init__(self, base_dir: str, default_ttl_hours: Optional[int] = None):
        """
        Initialize session manager.

        Args:
            base_dir: Directory for session persistence
            default_ttl_hours: TTL in hours (None = indefinite persistence)
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl_hours = default_ttl_hours

        # In-memory session pool
        self.sessions: Dict[str, CrawlerSession] = {}

        # Playwright instances
        self.playwright_instance: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self._lock = asyncio.Lock()

        # External CDP connections (for local_view mode)
        self.external_browsers: Dict[str, Browser] = {}
        self.session_mode: Dict[str, str] = {}  # session_id -> "headless" | "local_view"

        # Deferred restart flag - restart on NEXT call, not mid-operation
        self._pending_restart: bool = False

        # Default mode: local_view (user's browser for CAPTCHA solving)
        # Can be overridden via BROWSER_DEFAULT_MODE env var
        self.default_mode = os.getenv("BROWSER_DEFAULT_MODE", "local_view")

        ttl_desc = f"{default_ttl_hours}h" if default_ttl_hours else "indefinite (persistent)"
        logger.info(
            f"[CrawlerSessionMgr] Initialized with base_dir={base_dir}, "
            f"ttl={ttl_desc}, default_mode={self.default_mode}"
        )

    async def _ensure_browser(self, session_id: str = None):
        """Ensure Playwright browser is running with CDP remote debugging enabled"""
        # Check if this session should use external CDP connection
        if session_id and session_id in self.session_mode:
            if self.session_mode[session_id] == "local_view":
                # Use external browser connection
                if session_id not in self.external_browsers:
                    logger.error(
                        f"[CrawlerSessionMgr] Session {session_id} marked as local_view "
                        f"but no external browser connected"
                    )
                return  # Don't create headless browser for local_view mode

        if not self.browser:
            async with self._lock:
                if not self.browser:  # Double-check after acquiring lock
                    self.playwright_instance = await async_playwright().start()

                    # CDP remote debugging port (configurable via env)
                    cdp_port = int(os.getenv("PLAYWRIGHT_CDP_PORT", "9223"))

                    # Headless mode: True for headless servers, False for dev with X11
                    # Set PLAYWRIGHT_HEADLESS=true (default) for headless servers
                    # Set PLAYWRIGHT_HEADLESS=false for visible browser (requires X server)
                    # Set PLAYWRIGHT_HEADLESS=new for Chrome 112+ headless mode
                    headless_mode = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower()

                    # Base args for all modes
                    launch_args = [
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        f"--remote-debugging-port={cdp_port}",  # Enable CDP
                    ]

                    if headless_mode == "new":
                        # Chrome 112+ "new" headless mode (harder to detect)
                        headless = True
                        launch_args.append("--headless=new")
                    elif headless_mode in ("false", "0", "no"):
                        headless = False  # Visible browser (requires X server)
                    else:
                        headless = True   # Traditional headless (default for servers)

                    browser_type = get_browser_type(self.playwright_instance)

                    logger.info(
                        f"[CrawlerSessionMgr] Launching browser: headless={headless}, "
                        f"PLAYWRIGHT_HEADLESS={headless_mode}, browser={browser_type.name}"
                    )

                    self.browser = await browser_type.launch(
                        headless=headless,
                        args=launch_args if browser_type.name == 'chromium' else []
                    )

                    # Store CDP connection info
                    self.cdp_url = f"localhost:{cdp_port}"

                    logger.info(
                        f"[CrawlerSessionMgr] Playwright browser started with CDP enabled "
                        f"(remote debugging: {self.cdp_url}, visible={not headless})"
                    )

    async def _is_browser_alive(self) -> bool:
        """Check if the browser connection is still alive."""
        if not self.browser:
            return False
        try:
            # Try a simple operation to check if browser is responsive
            # Getting contexts is a lightweight check
            _ = self.browser.contexts
            return True
        except Exception as e:
            logger.warning(f"[CrawlerSessionMgr] Browser health check failed: {e}")
            return False

    async def _restart_browser(self):
        """Restart the browser after a crash/disconnect."""
        logger.warning("[CrawlerSessionMgr] Restarting browser due to page limit or connection failure...")

        async with self._lock:
            # IMPORTANT: Save all session states BEFORE closing browser
            # This preserves cookies/localStorage so Google doesn't see a "fresh" browser
            if self.sessions:
                logger.info(f"[CrawlerSessionMgr] Saving {len(self.sessions)} session states before restart...")
                for session_key, session in list(self.sessions.items()):
                    try:
                        if session.context:
                            await self.save_session_state(
                                domain=session.domain,
                                session_id=session.session_id,
                                context=session.context,
                                user_id=session.user_id
                            )
                            logger.info(f"[CrawlerSessionMgr] Saved state for {session.domain} (user: {session.user_id})")
                    except Exception as e:
                        logger.warning(f"[CrawlerSessionMgr] Failed to save state for {session_key}: {e}")

            # Clean up old browser
            if self.browser:
                try:
                    await self.browser.close()
                except Exception:
                    pass  # Ignore errors closing dead browser
                self.browser = None

            # Clean up playwright instance
            if self.playwright_instance:
                try:
                    await self.playwright_instance.stop()
                except Exception:
                    pass
                self.playwright_instance = None

            # Clear all sessions (they're now invalid, but state is saved to disk)
            old_sessions = list(self.sessions.keys())
            self.sessions.clear()
            if old_sessions:
                logger.info(f"[CrawlerSessionMgr] Cleared {len(old_sessions)} sessions (state preserved on disk)")

        # Re-initialize browser (will be created on next _ensure_browser call)
        await self._ensure_browser()
        logger.info("[CrawlerSessionMgr] Browser restarted successfully")

    def _is_connection_error(self, error: Exception) -> bool:
        """Check if an error indicates a dead browser connection."""
        error_str = str(error).lower()
        connection_error_patterns = [
            "writeunixstransport closed",
            "handler is closed",
            "target page, context or browser has been closed",
            "browser has been closed",
            "connection refused",
            "target closed",
            "session closed",
        ]
        return any(pattern in error_str for pattern in connection_error_patterns)

    async def connect_external_browser(
        self,
        session_id: str,
        cdp_endpoint: str = "http://localhost:9222"
    ) -> bool:
        """
        Connect to an external browser running on user's device.

        This enables "local_view" mode where the user can watch and control
        the browser directly on their laptop/phone while Playwright automation runs.

        Args:
            session_id: Session identifier
            cdp_endpoint: CDP endpoint URL (e.g., "http://localhost:9222")

        Returns:
            True if connection successful, False otherwise

        Example:
            On user's laptop/phone, run:
              Chrome: chrome --remote-debugging-port=9222 --user-data-dir="/tmp/chrome-profile"
              Or: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome \\
                    --remote-debugging-port=9222 \\
                    --user-data-dir="/tmp/chrome-profile"

            Then call this method to connect Playwright to that browser.
        """
        try:
            if not self.playwright_instance:
                self.playwright_instance = await async_playwright().start()

            # Connect to external CDP browser
            browser = await self.playwright_instance.chromium.connect_over_cdp(cdp_endpoint)

            # Store connection
            self.external_browsers[session_id] = browser
            self.session_mode[session_id] = "local_view"

            logger.info(
                f"[CrawlerSessionMgr] Connected to external browser for session {session_id} "
                f"(CDP: {cdp_endpoint})"
            )

            return True

        except Exception as e:
            logger.error(
                f"[CrawlerSessionMgr] Failed to connect to external browser at {cdp_endpoint}: {e}",
                exc_info=True
            )
            return False

    def set_session_mode(self, session_id: str, mode: str):
        """
        Set session mode: 'headless' or 'local_view'.

        Args:
            session_id: Session identifier
            mode: 'headless' (default) or 'local_view' (user's browser)
        """
        if mode not in ["headless", "local_view"]:
            raise ValueError(f"Invalid mode: {mode}. Must be 'headless' or 'local_view'")

        self.session_mode[session_id] = mode
        logger.info(f"[CrawlerSessionMgr] Session {session_id} mode set to: {mode}")

    def _get_session_key(self, domain: str, session_id: str, user_id: str = "default") -> str:
        """Generate unique session key"""
        return f"{user_id}:{session_id}:{domain}"

    def _get_session_dir(self, domain: str, session_id: str) -> Path:
        """Get directory for session persistence"""
        # Sanitize domain for filesystem
        safe_domain = domain.replace(":", "_").replace("/", "_").replace(".", "_")
        return self.base_dir / session_id / safe_domain

    def _get_user_data_dir(self, session_id: str) -> Path:
        """Get user data directory for persistent browser profile"""
        return self.base_dir / session_id / "browser_profile"

    def get_cdp_url(self) -> str:
        """Get CDP remote debugging URL for user connection"""
        if hasattr(self, 'cdp_url'):
            return self.cdp_url
        return "localhost:9223"  # Default

    async def get_or_create_session(
        self,
        domain: str,
        session_id: str,
        user_id: str = "default",
        skip_deferred_restart: bool = False
    ) -> BrowserContext:
        """
        Get existing session or create new one.

        Args:
            domain: Domain name (e.g., "example.com")
            session_id: Session identifier
            user_id: User identifier (default: "default")
            skip_deferred_restart: If True, don't execute deferred restart (for capture operations)

        Returns:
            Playwright BrowserContext ready for use
        """
        # Handle deferred restart from previous call (ensures current operation completes first)
        # Skip if this is a capture operation to avoid losing page content mid-flow
        if self._pending_restart and not skip_deferred_restart:
            logger.info(
                f"[CrawlerSessionMgr] Executing deferred browser restart (from previous page limit)"
            )
            self._pending_restart = False
            await self._restart_browser()

        await self._ensure_browser(session_id=session_id)

        session_key = self._get_session_key(domain, session_id, user_id)

        # Check in-memory pool
        if session_key in self.sessions:
            session = self.sessions[session_key]

            # Check expiry
            if session.is_expired(self.default_ttl_hours):
                logger.info(f"[CrawlerSessionMgr] Session expired: {session_key}")
                await self._cleanup_session(session_key)
            # Check page count - DEFER restart to next call (don't restart mid-operation)
            elif session.page_count >= MAX_PAGES_BEFORE_RESTART:
                logger.warning(
                    f"[CrawlerSessionMgr] Page limit reached ({session.page_count}/{MAX_PAGES_BEFORE_RESTART}), "
                    f"scheduling restart for next navigation (current operation will complete first)"
                )
                self._pending_restart = True
                # Clean up blank pages to help reduce memory before restart
                await session.cleanup_excess_pages()
                # Return current context - restart will happen on NEXT call
                session.touch()
                return session.context
            else:
                session.touch()
                # Clean up blank/unused pages to prevent visible tab accumulation
                await session.cleanup_excess_pages()
                logger.info(
                    f"[CrawlerSessionMgr] Reusing session: {session_key} "
                    f"(pages: {session.page_count}/{MAX_PAGES_BEFORE_RESTART}, mode: {self.session_mode.get(session_id, 'headless')})"
                )
                return session.context

        # Create new session
        session_mode = self.session_mode.get(session_id, self.default_mode)
        logger.info(f"[CrawlerSessionMgr] Creating new session: {session_key} (mode: {session_mode})")

        # Load fingerprint (or generate new)
        from apps.services.tool_server.browser_fingerprint import BrowserFingerprint
        fingerprint = BrowserFingerprint(user_id, session_id)

        # Load persisted state if exists
        session_dir = self._get_session_dir(domain, session_id)
        storage_state = None
        if (session_dir / "state.json").exists():
            try:
                storage_state = str(session_dir / "state.json")
                logger.info(f"[CrawlerSessionMgr] Loading persisted state from {storage_state}")
            except Exception as e:
                logger.warning(f"[CrawlerSessionMgr] Failed to load state: {e}")

        # Determine which browser to use
        if session_mode == "local_view":
            # Use external CDP browser
            if session_id not in self.external_browsers:
                raise RuntimeError(
                    f"Session {session_id} is in local_view mode but no external browser connected. "
                    f"Call connect_external_browser() first."
                )

            browser = self.external_browsers[session_id]

            # For external browsers, get existing context or create one
            contexts = browser.contexts
            if contexts:
                context = contexts[0]  # Use first available context
                logger.info(
                    f"[CrawlerSessionMgr] Using existing context from external browser "
                    f"(contexts: {len(contexts)})"
                )
            else:
                # Create new context in external browser
                context_options = fingerprint.apply_to_context_options()
                if storage_state:
                    context_options["storage_state"] = storage_state
                context = await browser.new_context(**context_options)
                logger.info("[CrawlerSessionMgr] Created new context in external browser")

        else:
            # Use headless browser
            context_options = fingerprint.apply_to_context_options()
            if storage_state:
                context_options["storage_state"] = storage_state

            context = await self.browser.new_context(**context_options)

        # Inject stealth JavaScript to bypass bot detection
        logger.debug(f"[CrawlerSessionMgr] About to inject stealth for {session_key}")
        from apps.services.tool_server.stealth_injector import inject_stealth
        await inject_stealth(context, log=True)
        logger.debug(f"[CrawlerSessionMgr] Stealth injection complete for {session_key}")

        # Store in pool
        session = CrawlerSession(
            domain=domain,
            session_id=session_id,
            user_id=user_id,
            context=context,
            fingerprint=fingerprint.to_dict()
        )
        self.sessions[session_key] = session

        logger.info(
            f"[CrawlerSessionMgr] Session created: {session_key} "
            f"(viewport={fingerprint.viewport}, timezone={fingerprint.timezone}, mode={session_mode})"
        )

        return context

    async def inject_cookies(
        self,
        domain: str,
        session_id: str,
        cookies: list,
        user_id: str = "default"
    ):
        """
        Inject cookies from user's browser into Playwright context.

        Args:
            domain: Domain name
            session_id: Session identifier
            cookies: List of cookie dictionaries from user's browser
            user_id: User identifier
        """
        session_key = self._get_session_key(domain, session_id, user_id)

        if session_key not in self.sessions:
            logger.warning(f"[CrawlerSessionMgr] No active session to inject cookies: {session_key}")
            return False

        session = self.sessions[session_key]
        context = session.context

        try:
            # Format cookies for Playwright
            playwright_cookies = []
            for cookie in cookies:
                playwright_cookie = {
                    "name": cookie.get("name", ""),
                    "value": cookie.get("value", ""),
                    "domain": cookie.get("domain", domain),
                    "path": cookie.get("path", "/"),
                }

                # Add optional fields
                if "expires" in cookie:
                    playwright_cookie["expires"] = cookie["expires"]
                if "httpOnly" in cookie:
                    playwright_cookie["httpOnly"] = cookie["httpOnly"]
                if "secure" in cookie:
                    playwright_cookie["secure"] = cookie["secure"]
                if "sameSite" in cookie:
                    playwright_cookie["sameSite"] = cookie["sameSite"]

                playwright_cookies.append(playwright_cookie)

            # Inject into context
            await context.add_cookies(playwright_cookies)

            logger.info(
                f"[CrawlerSessionMgr] Injected {len(playwright_cookies)} cookies "
                f"into session {session_key}"
            )

            return True

        except Exception as e:
            logger.error(f"[CrawlerSessionMgr] Failed to inject cookies: {e}", exc_info=True)
            return False

    async def save_session_state(
        self,
        domain: str,
        session_id: str,
        context: BrowserContext,
        user_id: str = "default"
    ):
        """
        Save session cookies/storage to disk.

        Args:
            domain: Domain name
            session_id: Session identifier
            context: Playwright BrowserContext to save
            user_id: User identifier
        """
        session_dir = self._get_session_dir(domain, session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Verify context is valid
            if not context:
                logger.error(f"[CrawlerSessionMgr] Cannot save state: context is None")
                return

            # Save storage state (cookies + localStorage + sessionStorage)
            state_path = session_dir / "state.json"

            try:
                await context.storage_state(path=str(state_path))
            except Exception as storage_err:
                logger.error(
                    f"[CrawlerSessionMgr] Failed to save storage state for {domain}: {storage_err}",
                    exc_info=True
                )
                return

            # Verify file was created
            if not state_path.exists():
                logger.error(f"[CrawlerSessionMgr] state.json not created at {state_path}")
                return

            file_size = state_path.stat().st_size
            logger.info(
                f"[CrawlerSessionMgr] Saved session state: {state_path} ({file_size} bytes)"
            )

            # Save metadata
            metadata = {
                "domain": domain,
                "session_id": session_id,
                "user_id": user_id,
                "saved_at": datetime.now().isoformat(),
                "ttl_hours": self.default_ttl_hours
            }
            (session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

            logger.info(
                f"[CrawlerSessionMgr] Session persisted: {domain} "
                f"(ttl={self.default_ttl_hours}h, session_dir={session_dir})"
            )
        except Exception as e:
            logger.error(
                f"[CrawlerSessionMgr] Failed to save session state for {domain}: {e}",
                exc_info=True
            )

    async def _cleanup_session(self, session_key: str):
        """Close and remove session from pool"""
        if session_key in self.sessions:
            session = self.sessions[session_key]
            try:
                await session.context.close()
            except Exception as e:
                logger.warning(f"[CrawlerSessionMgr] Error closing context: {e}")
            del self.sessions[session_key]
            logger.info(f"[CrawlerSessionMgr] Cleaned up session: {session_key}")

    async def cleanup_expired_sessions(self):
        """Remove all expired sessions"""
        expired = []
        for key, session in self.sessions.items():
            if session.is_expired(self.default_ttl_hours):
                expired.append(key)

        for key in expired:
            await self._cleanup_session(key)

        logger.info(f"[CrawlerSessionMgr] Cleaned up {len(expired)} expired sessions")
        return len(expired)

    async def delete_session(
        self,
        domain: str,
        session_id: str,
        user_id: str = "default"
    ):
        """
        Manually delete a session.
        
        Args:
            domain: Domain name
            session_id: Session identifier
            user_id: User identifier
        """
        session_key = self._get_session_key(domain, session_id, user_id)
        await self._cleanup_session(session_key)

        # Delete persisted state
        session_dir = self._get_session_dir(domain, session_id)
        if session_dir.exists():
            shutil.rmtree(session_dir)
            logger.info(f"[CrawlerSessionMgr] Deleted persisted state: {session_dir}")

    async def list_sessions(self, user_id: str = "default") -> List[Dict]:
        """
        List all active sessions for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            List of session info dicts
        """
        user_sessions = []
        for key, session in self.sessions.items():
            if session.user_id == user_id:
                user_sessions.append({
                    "domain": session.domain,
                    "session_id": session.session_id,
                    "created_at": session.created_at.isoformat(),
                    "last_used": session.last_used.isoformat(),
                    "page_count": session.page_count,
                    "is_expired": session.is_expired(self.default_ttl_hours),
                    "fingerprint": session.fingerprint
                })
        return user_sessions

    async def get_stats(self) -> Dict:
        """Get session manager statistics"""
        active_sessions = len(self.sessions)
        expired_sessions = sum(
            1 for s in self.sessions.values()
            if s.is_expired(self.default_ttl_hours)
        )
        total_pages = sum(s.page_count for s in self.sessions.values())

        return {
            "active_sessions": active_sessions,
            "expired_sessions": expired_sessions,
            "total_pages_fetched": total_pages,
            "browser_running": self.browser is not None
        }

    async def shutdown(self):
        """Clean shutdown - close all sessions"""
        logger.info("[CrawlerSessionMgr] Shutting down...")
        
        # Close all sessions
        for key in list(self.sessions.keys()):
            await self._cleanup_session(key)

        # Close browser
        if self.browser:
            await self.browser.close()
            self.browser = None
            
        if self.playwright_instance:
            await self.playwright_instance.stop()
            self.playwright_instance = None

        logger.info("[CrawlerSessionMgr] Shutdown complete")


# Global singleton
_CRAWLER_SESSION_MGR: Optional[CrawlerSessionManager] = None


def get_crawler_session_manager() -> CrawlerSessionManager:
    """Get or create global session manager"""
    global _CRAWLER_SESSION_MGR
    if _CRAWLER_SESSION_MGR is None:
        # Default to 10 years - truly permanent cookie/session storage
        # Set CRAWLER_SESSION_TTL_HOURS=24 for daily expiry if needed for testing
        ttl_hours = int(os.getenv("CRAWLER_SESSION_TTL_HOURS", "87600"))  # 10 years
        _CRAWLER_SESSION_MGR = CrawlerSessionManager(
            base_dir="panda_system_docs/shared_state/crawler_sessions",
            default_ttl_hours=ttl_hours
        )
    return _CRAWLER_SESSION_MGR
