"""
Browser Tools for Research

Simple tools: search() and visit()

No complex extraction - just get text and let the LLM interpret it.
"""

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class SearchResults:
    """Results from a web search."""
    success: bool
    query: str
    results: list[dict]  # [{url, title, snippet}, ...]
    error: Optional[str] = None


@dataclass
class PageVisitResult:
    """Result from visiting a page."""
    success: bool
    url: str
    title: str
    text: str  # Sanitized page text
    blocked: bool = False
    blocker_type: Optional[str] = None  # captcha, login, rate_limit
    error: Optional[str] = None


class ResearchBrowser:
    """
    Browser for research operations.

    Provides simple search() and visit() tools.
    Uses existing infrastructure (HumanSearchEngine, ContentSanitizer).
    """

    def __init__(
        self,
        session_id: str,
        visit_delay: tuple[float, float] = (4.0, 6.0),
        max_text_tokens: int = 4000,
        human_assist_allowed: bool = True,
        intervention_timeout: float = 90.0,
    ):
        self.session_id = session_id
        self.visit_delay = visit_delay
        self.max_text_tokens = max_text_tokens
        self.human_assist_allowed = human_assist_allowed
        self.intervention_timeout = intervention_timeout

        # Lazy imports to avoid circular dependencies
        self._search_engine = None
        self._sanitizer = None
        self._browser_session = None

    async def _get_search_engine(self):
        """Get or create the search engine."""
        if self._search_engine is None:
            from apps.services.tool_server.human_search_engine import HumanSearchEngine
            self._search_engine = HumanSearchEngine()
        return self._search_engine

    async def _get_sanitizer(self):
        """Get or create the content sanitizer."""
        if self._sanitizer is None:
            from apps.services.tool_server.content_sanitizer import ContentSanitizer
            self._sanitizer = ContentSanitizer()
        return self._sanitizer

    async def _get_browser_session(self):
        """Browser session is managed internally by web_vision_mcp operations."""
        return self.session_id

    async def search(self, query: str) -> SearchResults:
        """
        Execute a web search.

        1. Navigate to search engine
        2. Human-like delays
        3. Type query, extract results

        Returns:
            SearchResults with list of {url, title, snippet}
        """
        logger.info(f"[ResearchBrowser] Searching: {query}")

        try:
            search_engine = await self._get_search_engine()

            # Execute search with human-like behavior
            results = await search_engine.search(
                query=query,
                num_results=15,
                session_id=self.session_id,
            )

            if not results:
                logger.warning(f"[ResearchBrowser] No search results for: {query}")
                return SearchResults(
                    success=True,
                    query=query,
                    results=[],
                )

            # Convert to simple format
            # Note: HumanSearchEngine.search() returns List[Dict] directly,
            # not a dict with "organic_results" key
            formatted_results = []
            for r in results:
                formatted_results.append({
                    "url": r.get("url", r.get("link", "")),
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", ""),
                })

            logger.info(f"[ResearchBrowser] Found {len(formatted_results)} results")
            return SearchResults(
                success=True,
                query=query,
                results=formatted_results,
            )

        except Exception as e:
            logger.error(f"[ResearchBrowser] Search error: {e}")
            return SearchResults(
                success=False,
                query=query,
                results=[],
                error=str(e),
            )

    async def visit(self, url: str) -> PageVisitResult:
        """
        Visit a page and extract its text.

        1. Navigate to URL
        2. Wait for page load
        3. Detect blockers (CAPTCHA, login)
        4. Extract and sanitize text
        5. Wait human delay

        Returns:
            PageVisitResult with sanitized content
        """
        logger.info(f"[ResearchBrowser] Visiting: {url}")

        try:
            from apps.services.tool_server import web_vision_mcp

            # Navigate to the page
            session = await self._get_browser_session()
            nav_result = await web_vision_mcp.navigate(
                session_id=self.session_id,
                url=url,
                wait_for="networkidle",
            )

            if not nav_result.get("success"):
                error = nav_result.get("error", "Navigation failed")
                logger.warning(f"[ResearchBrowser] Navigation failed: {error}")
                return PageVisitResult(
                    success=False,
                    url=url,
                    title="",
                    text="",
                    error=error,
                )

            # Get the page
            page = await web_vision_mcp.get_page(self.session_id)
            if not page:
                return PageVisitResult(
                    success=False,
                    url=url,
                    title="",
                    text="",
                    error="Could not get page object",
                )

            # Check for blockers
            blocker_type = await self._detect_blocker(page)
            if blocker_type:
                logger.warning(f"[ResearchBrowser] Blocked by: {blocker_type}")

                # Try human intervention if allowed
                if self.human_assist_allowed:
                    resolved = await self._request_human_intervention(
                        url=url,
                        blocker_type=blocker_type,
                        page=page,
                    )
                    if resolved:
                        logger.info(f"[ResearchBrowser] Intervention resolved, continuing")
                        # Re-check for blockers after intervention
                        blocker_type = await self._detect_blocker(page)
                        if blocker_type:
                            logger.warning(f"[ResearchBrowser] Still blocked after intervention")
                            return PageVisitResult(
                                success=False,
                                url=url,
                                title="",
                                text="",
                                blocked=True,
                                blocker_type=blocker_type,
                            )
                        # Continue with extraction below
                    else:
                        logger.warning(f"[ResearchBrowser] Intervention not resolved")
                        return PageVisitResult(
                            success=False,
                            url=url,
                            title="",
                            text="",
                            blocked=True,
                            blocker_type=blocker_type,
                        )
                else:
                    return PageVisitResult(
                        success=False,
                        url=url,
                        title="",
                        text="",
                        blocked=True,
                        blocker_type=blocker_type,
                    )

            # Get page title
            title = await page.title() or ""

            # Get HTML and sanitize
            html = await page.content()
            sanitizer = await self._get_sanitizer()
            result = sanitizer.sanitize(html, url, max_tokens=self.max_text_tokens)

            # Extract text from chunks
            chunks = result.get("chunks", [])
            text = "\n\n".join(chunk.get("text", "") for chunk in chunks)

            # Truncate if still too long (rough token estimate: 4 chars per token)
            max_chars = self.max_text_tokens * 4
            if len(text) > max_chars:
                text = text[:max_chars] + "\n\n[Content truncated...]"

            logger.info(f"[ResearchBrowser] Extracted {len(text)} chars from {url}")

            # Human delay before returning
            delay = random.uniform(*self.visit_delay)
            logger.debug(f"[ResearchBrowser] Waiting {delay:.1f}s (human delay)")
            await asyncio.sleep(delay)

            return PageVisitResult(
                success=True,
                url=url,
                title=title,
                text=text,
            )

        except Exception as e:
            logger.error(f"[ResearchBrowser] Visit error: {e}")
            return PageVisitResult(
                success=False,
                url=url,
                title="",
                text="",
                error=str(e),
            )

    async def _request_human_intervention(
        self, url: str, blocker_type: str, page
    ) -> bool:
        """
        Request human intervention for a blocker.

        Creates an intervention request and waits for resolution.

        Returns:
            True if intervention was resolved successfully, False otherwise
        """
        try:
            from apps.services.tool_server.captcha_intervention import (
                request_intervention,
                InterventionType,
            )

            # Map our blocker types to InterventionType
            blocker_type_map = {
                "captcha": "captcha_generic",
                "cloudflare": "captcha_cloudflare",
                "login_required": "login_required",
                "rate_limit": "rate_limit",
            }
            intervention_type = blocker_type_map.get(blocker_type, "unknown_blocker")

            # Take a screenshot
            screenshot_path = None
            try:
                import os
                from pathlib import Path
                screenshots_dir = Path("panda_system_docs/research_screenshots")
                screenshots_dir.mkdir(parents=True, exist_ok=True)
                screenshot_path = str(screenshots_dir / f"{self.session_id}_{blocker_type}.png")
                await page.screenshot(path=screenshot_path)
                logger.info(f"[ResearchBrowser] Screenshot saved: {screenshot_path}")
            except Exception as e:
                logger.warning(f"[ResearchBrowser] Could not save screenshot: {e}")

            # Create intervention request
            intervention = await request_intervention(
                blocker_type=intervention_type,
                url=url,
                screenshot_path=screenshot_path,
                session_id=self.session_id,
                blocker_details={"detected_by": "ResearchBrowser"},
            )

            logger.info(
                f"[ResearchBrowser] Waiting for human intervention "
                f"(timeout={self.intervention_timeout}s)"
            )

            # Wait for resolution
            resolved = await intervention.wait_for_resolution(
                timeout=self.intervention_timeout
            )

            return resolved and intervention.resolution_success

        except Exception as e:
            logger.error(f"[ResearchBrowser] Intervention request failed: {e}")
            return False

    async def _detect_blocker(self, page) -> Optional[str]:
        """
        Detect if the page is blocked by CAPTCHA, login wall, etc.

        Returns blocker type or None if not blocked.
        """
        try:
            # Get page text for analysis
            body_text = await page.inner_text("body")
            body_lower = body_text.lower() if body_text else ""

            # CAPTCHA indicators
            captcha_indicators = [
                "verify you are human",
                "i'm not a robot",
                "captcha",
                "security check",
                "please verify",
                "unusual traffic",
                "automated access",
            ]
            for indicator in captcha_indicators:
                if indicator in body_lower:
                    return "captcha"

            # Cloudflare
            if "checking your browser" in body_lower or "cloudflare" in body_lower:
                return "cloudflare"

            # Login walls
            login_indicators = [
                "sign in to continue",
                "log in to continue",
                "create an account",
                "login required",
            ]
            for indicator in login_indicators:
                if indicator in body_lower:
                    return "login_required"

            # Rate limit
            if "rate limit" in body_lower or "too many requests" in body_lower:
                return "rate_limit"

            return None

        except Exception as e:
            logger.warning(f"[ResearchBrowser] Blocker detection error: {e}")
            return None

    async def close(self):
        """Clean up browser resources."""
        try:
            from apps.services.tool_server import web_vision_mcp
            await web_vision_mcp.reset_session(self.session_id)
        except Exception as e:
            logger.warning(f"[ResearchBrowser] Error closing session: {e}")


# Helper to extract domain from URL
def get_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except:
        return ""


# Skip list for social media and login-required sites
SKIP_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "pinterest.com",
    "linkedin.com",
}


def should_skip_url(url: str) -> bool:
    """Check if URL should be skipped (social media, login-required)."""
    domain = get_domain(url)
    for skip in SKIP_DOMAINS:
        if skip in domain:
            return True
    return False
