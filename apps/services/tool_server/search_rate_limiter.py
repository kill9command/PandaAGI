"""
orchestrator/search_rate_limiter.py

Global search rate limiter to prevent bursts that trigger 418/CAPTCHA blocks.

Design:
- Enforces minimum delay between ANY search engine requests (DDG, Google, etc.)
- Uses asyncio.Lock to serialize search requests across all sessions
- Maintains last_request timestamp to calculate required delay
- Provides exponential backoff when rate limits are detected

Created: 2025-11-18
Part of fix for research pipeline rate limiting issues.
"""
import asyncio
import time
import logging
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SearchRateLimiter:
    """
    Global singleton rate limiter for all search engine requests.

    Prevents burst traffic by enforcing minimum delays between searches.
    """

    def __init__(
        self,
        min_delay_seconds: float = 2.0,
        backoff_on_block: float = 10.0,
        max_backoff: float = 60.0
    ):
        """
        Args:
            min_delay_seconds: Minimum seconds between any two searches (default 2s)
            backoff_on_block: Additional delay after detecting rate limit (default 10s)
            max_backoff: Maximum backoff delay (default 60s)
        """
        self._lock = asyncio.Lock()
        self._last_request: Optional[float] = None
        self._min_delay = min_delay_seconds
        self._backoff_delay = backoff_on_block
        self._max_backoff = max_backoff
        self._current_backoff = 0.0
        self._consecutive_blocks = 0

    async def acquire(self, query: str, engine: str = "unknown") -> None:
        """
        Acquire permission to make a search request.

        Blocks until enough time has passed since last request.

        Args:
            query: Search query (for logging)
            engine: Search engine name (for logging)
        """
        async with self._lock:
            now = time.time()

            if self._last_request is not None:
                # Calculate required delay
                elapsed = now - self._last_request
                required_delay = self._min_delay + self._current_backoff

                if elapsed < required_delay:
                    wait_time = required_delay - elapsed
                    logger.info(
                        f"[RateLimit] Throttling {engine} search: waiting {wait_time:.1f}s "
                        f"(query: {query[:40]}...)"
                    )
                    await asyncio.sleep(wait_time)
                    now = time.time()

            self._last_request = now
            logger.debug(
                f"[RateLimit] Approved {engine} search: {query[:40]}... "
                f"(backoff: {self._current_backoff:.1f}s)"
            )

    def report_rate_limit(self, engine: str) -> None:
        """
        Report that a rate limit was encountered.

        Increases backoff for subsequent requests.

        Args:
            engine: Search engine that returned rate limit
        """
        self._consecutive_blocks += 1

        # Exponential backoff: 10s, 20s, 40s, max 60s
        self._current_backoff = min(
            self._backoff_delay * (2 ** (self._consecutive_blocks - 1)),
            self._max_backoff
        )

        logger.warning(
            f"[RateLimit] {engine} rate limit detected! "
            f"Increasing backoff to {self._current_backoff:.1f}s "
            f"({self._consecutive_blocks} consecutive blocks)"
        )

    def report_success(self) -> None:
        """
        Report that a search succeeded without rate limiting.

        Gradually reduces backoff.
        """
        if self._consecutive_blocks > 0:
            self._consecutive_blocks = max(0, self._consecutive_blocks - 1)
            self._current_backoff = max(
                0,
                self._backoff_delay * (2 ** (self._consecutive_blocks - 1))
            )
            logger.info(
                f"[RateLimit] Search succeeded, reducing backoff to {self._current_backoff:.1f}s"
            )

    def reset(self) -> None:
        """Reset backoff state (for testing or manual intervention)."""
        self._consecutive_blocks = 0
        self._current_backoff = 0.0
        logger.info("[RateLimit] Backoff reset")


# Global singleton instance
_global_limiter: Optional[SearchRateLimiter] = None


def get_search_rate_limiter() -> SearchRateLimiter:
    """
    Get the global search rate limiter instance.

    Returns:
        SearchRateLimiter singleton
    """
    global _global_limiter
    if _global_limiter is None:
        # SerpAPI-style delays: much longer base delay to avoid rate limits
        # They typically use 15-30s between searches from same IP
        _global_limiter = SearchRateLimiter(
            min_delay_seconds=15.0,     # 15s between searches (like SerpAPI)
            backoff_on_block=30.0,      # +30s after rate limit (was 10s)
            max_backoff=120.0           # Max 2 minutes backoff (was 60s)
        )
    return _global_limiter
