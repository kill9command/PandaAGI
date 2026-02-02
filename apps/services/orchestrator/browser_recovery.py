"""
orchestrator/browser_recovery.py

Automatic browser recovery on connection failure.

Provides centralized recovery management for browser sessions:
- Detects dead browser connections (CDP disconnects, crashed tabs, etc.)
- Automatic recovery with exponential backoff
- Prevents concurrent recovery attempts via locking
- Integrates with CrawlerSessionManager and BrowserSessionRegistry

Usage:
    from apps.services.orchestrator.browser_recovery import get_browser_recovery_manager, with_browser_recovery

    # As a decorator
    @with_browser_recovery
    async def my_browser_operation(session_id: str, page):
        await page.goto("https://example.com")

    # Direct usage
    recovery_manager = get_browser_recovery_manager()
    page = await recovery_manager.get_healthy_page(session_id)

Created: 2025-12-04
"""

from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TypeVar

logger = logging.getLogger(__name__)

# Connection error patterns that indicate browser/session is dead
CONNECTION_ERROR_PATTERNS = [
    "writeunixstransport closed",
    "handler is closed",
    "target page, context or browser has been closed",
    "target page or context has been closed",
    "browser has been closed",
    "connection refused",
    "target closed",
    "session closed",
    "closed=true",
    "protocol error",
    "execution context was destroyed",
    "page has been closed",
    "context has been closed",
    "browser closed",
    "connection closed",
    "websocket closed",
    "broken pipe",
    "connection reset",
    "no such session",
    "cdp session closed",
]


@dataclass
class RecoveryAttempt:
    """Tracks a recovery attempt for a session."""
    session_id: str
    started_at: datetime
    attempt_number: int
    success: bool = False
    error: Optional[str] = None
    completed_at: Optional[datetime] = None
    duration_ms: int = 0


@dataclass
class SessionHealth:
    """Tracks health status of a browser session."""
    session_id: str
    last_check: datetime = field(default_factory=datetime.utcnow)
    is_healthy: bool = True
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    recovery_attempts: int = 0
    last_recovery: Optional[datetime] = None


class BrowserRecoveryManager:
    """
    Centralized manager for browser session recovery.

    Features:
    - Automatic recovery with exponential backoff
    - Concurrent recovery prevention via session locks
    - Health tracking per session
    - Configurable retry limits and timeouts
    """

    # Recovery configuration
    MAX_RECOVERY_ATTEMPTS = 3
    INITIAL_BACKOFF_MS = 500
    MAX_BACKOFF_MS = 10000
    RECOVERY_COOLDOWN_SECONDS = 30  # Minimum time between recovery attempts
    HEALTH_CHECK_INTERVAL_SECONDS = 60

    def __init__(self):
        self._session_health: Dict[str, SessionHealth] = {}
        self._recovery_locks: Dict[str, asyncio.Lock] = {}
        self._recovering_sessions: Set[str] = set()
        self._global_lock = asyncio.Lock()
        self._recovery_history: List[RecoveryAttempt] = []
        self._max_history = 100

        logger.info("[BrowserRecovery] Initialized recovery manager")

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create a lock for a session."""
        if session_id not in self._recovery_locks:
            self._recovery_locks[session_id] = asyncio.Lock()
        return self._recovery_locks[session_id]

    def _get_health(self, session_id: str) -> SessionHealth:
        """Get or create health tracking for a session."""
        if session_id not in self._session_health:
            self._session_health[session_id] = SessionHealth(session_id=session_id)
        return self._session_health[session_id]

    def is_connection_error(self, error: Exception) -> bool:
        """Check if an error indicates a dead browser connection."""
        error_str = str(error).lower()
        return any(pattern in error_str for pattern in CONNECTION_ERROR_PATTERNS)

    def is_recovering(self, session_id: str) -> bool:
        """Check if a session is currently being recovered."""
        return session_id in self._recovering_sessions

    def mark_healthy(self, session_id: str):
        """Mark a session as healthy after successful operation."""
        health = self._get_health(session_id)
        health.is_healthy = True
        health.consecutive_failures = 0
        health.last_check = datetime.utcnow()
        health.last_error = None

    def mark_unhealthy(self, session_id: str, error: str):
        """Mark a session as unhealthy after failed operation."""
        health = self._get_health(session_id)
        health.is_healthy = False
        health.consecutive_failures += 1
        health.last_check = datetime.utcnow()
        health.last_error = error

        logger.warning(
            f"[BrowserRecovery] Session {session_id} marked unhealthy: "
            f"failures={health.consecutive_failures}, error={error[:100]}"
        )

        # Force browser restart on fatal errors or excessive failures
        FATAL_FAILURE_THRESHOLD = 10
        is_fatal_error = any(fatal in error.lower() for fatal in [
            "writeunixstransport closed",
            "handler is closed",
            "browser has been closed",
            "unable to perform operation"
        ])

        if is_fatal_error or health.consecutive_failures >= FATAL_FAILURE_THRESHOLD:
            logger.error(
                f"[BrowserRecovery] FATAL: Browser appears dead (failures={health.consecutive_failures}). "
                f"Scheduling forced restart."
            )
            # Schedule async browser restart
            asyncio.create_task(self._force_browser_restart(session_id))

    def can_recover(self, session_id: str) -> Tuple[bool, str]:
        """
        Check if recovery can be attempted for a session.

        Returns:
            (can_recover, reason)
        """
        health = self._get_health(session_id)

        # Check if already recovering
        if self.is_recovering(session_id):
            return False, "Recovery already in progress"

        # Check recovery attempt limit
        if health.recovery_attempts >= self.MAX_RECOVERY_ATTEMPTS:
            # Check if cooldown has passed
            if health.last_recovery:
                cooldown_end = health.last_recovery + timedelta(seconds=self.RECOVERY_COOLDOWN_SECONDS * 3)
                if datetime.utcnow() < cooldown_end:
                    remaining = (cooldown_end - datetime.utcnow()).seconds
                    return False, f"Max recovery attempts reached, cooldown {remaining}s remaining"
                else:
                    # Reset attempts after extended cooldown
                    health.recovery_attempts = 0

        # Check recovery cooldown
        if health.last_recovery:
            cooldown_end = health.last_recovery + timedelta(seconds=self.RECOVERY_COOLDOWN_SECONDS)
            if datetime.utcnow() < cooldown_end:
                remaining = (cooldown_end - datetime.utcnow()).seconds
                return False, f"Recovery cooldown active, {remaining}s remaining"

        return True, "OK"

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay in seconds."""
        backoff_ms = min(
            self.INITIAL_BACKOFF_MS * (2 ** attempt),
            self.MAX_BACKOFF_MS
        )
        return backoff_ms / 1000.0

    async def _close_dead_session(self, session_id: str):
        """Close a dead session and clean up resources."""
        from apps.services.orchestrator.crawler_session_manager import get_crawler_session_manager
        from apps.services.orchestrator.browser_session_registry import get_browser_session_registry

        manager = get_crawler_session_manager()
        registry = get_browser_session_registry()

        try:
            # Find and delete the session from crawler manager
            sessions = await manager.list_sessions()
            for sess in sessions:
                if sess["session_id"] == session_id:
                    await manager.delete_session(
                        domain=sess["domain"],
                        session_id=session_id,
                        user_id=sess.get("user_id", "default")
                    )
                    logger.info(f"[BrowserRecovery] Deleted dead session from manager: {session_id}")
                    break
            else:
                # Try default domain
                try:
                    await manager.delete_session(domain="web_vision", session_id=session_id)
                    logger.info(f"[BrowserRecovery] Deleted dead session (default domain): {session_id}")
                except Exception:
                    pass

            # Close session in registry
            registry.close_session(session_id, reason="connection_failure")
            registry.remove_session(session_id)
            logger.info(f"[BrowserRecovery] Removed session from registry: {session_id}")

        except Exception as e:
            logger.warning(f"[BrowserRecovery] Error closing dead session {session_id}: {e}")

    async def _check_page_health(self, page) -> Tuple[bool, Optional[str]]:
        """
        Check if a page is healthy and responsive.

        Returns:
            (is_healthy, error_message)
        """
        if page is None:
            return False, "Page is None"

        try:
            # Quick check: try to get page URL
            _ = page.url

            # Try a simple evaluation to verify the connection is alive
            await asyncio.wait_for(
                page.evaluate("() => true"),
                timeout=5.0
            )

            return True, None

        except asyncio.TimeoutError:
            return False, "Health check timed out"
        except Exception as e:
            error_str = str(e)
            if self.is_connection_error(e):
                return False, f"Connection error: {error_str[:100]}"
            # Non-connection errors might be OK (e.g., page is navigating)
            return True, None

    async def _force_browser_restart(self, session_id: str):
        """
        Force a complete browser restart when the browser process is dead.
        This bypasses normal recovery and directly restarts the browser.
        """
        try:
            logger.info(f"[BrowserRecovery] Forcing browser restart for {session_id}")
            from apps.services.orchestrator.crawler_session_manager import get_crawler_session_manager
            manager = get_crawler_session_manager()

            # Clear all sessions by cleaning each one
            for session_key in list(manager.sessions.keys()):
                try:
                    await manager._cleanup_session(session_key)
                except Exception:
                    pass  # Ignore errors during cleanup

            # Restart the browser
            await manager._restart_browser()

            # Reset all health states
            for health in self._session_health.values():
                health.consecutive_failures = 0
                health.recovery_attempts = 0
                health.is_healthy = True

            logger.info("[BrowserRecovery] Browser forcibly restarted, health states reset")
        except Exception as e:
            logger.error(f"[BrowserRecovery] Force restart failed: {e}", exc_info=True)

    async def _check_browser_health(self) -> Tuple[bool, Optional[str]]:
        """
        Check if the browser process is healthy.

        Returns:
            (is_healthy, error_message)
        """
        from apps.services.orchestrator.crawler_session_manager import get_crawler_session_manager

        manager = get_crawler_session_manager()

        try:
            is_alive = await manager._is_browser_alive()
            if not is_alive:
                return False, "Browser is not alive"
            return True, None
        except Exception as e:
            return False, f"Browser health check failed: {e}"

    async def recover_session(self, session_id: str) -> Tuple[bool, Optional[Any]]:
        """
        Attempt to recover a dead session.

        Args:
            session_id: Session identifier

        Returns:
            (success, new_page or None)
        """
        lock = self._get_lock(session_id)
        health = self._get_health(session_id)

        async with lock:
            # Double-check recovery is allowed
            can_recover, reason = self.can_recover(session_id)
            if not can_recover:
                logger.info(f"[BrowserRecovery] Cannot recover {session_id}: {reason}")
                return False, None

            self._recovering_sessions.add(session_id)
            health.recovery_attempts += 1
            health.last_recovery = datetime.utcnow()

            attempt = RecoveryAttempt(
                session_id=session_id,
                started_at=datetime.utcnow(),
                attempt_number=health.recovery_attempts
            )

            try:
                logger.info(
                    f"[BrowserRecovery] Starting recovery for {session_id} "
                    f"(attempt {health.recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})"
                )

                # Step 1: Close the dead session
                await self._close_dead_session(session_id)

                # Step 2: Check if browser itself needs restart
                browser_healthy, browser_error = await self._check_browser_health()
                if not browser_healthy:
                    logger.warning(f"[BrowserRecovery] Browser unhealthy: {browser_error}")
                    from apps.services.orchestrator.crawler_session_manager import get_crawler_session_manager
                    manager = get_crawler_session_manager()
                    await manager._restart_browser()
                    logger.info("[BrowserRecovery] Browser restarted")

                # Step 3: Brief delay before creating new session
                backoff = self._calculate_backoff(health.recovery_attempts - 1)
                logger.info(f"[BrowserRecovery] Waiting {backoff:.1f}s before creating new session")
                await asyncio.sleep(backoff)

                # Step 4: Create new session
                # Import here to avoid circular imports
                from apps.services.orchestrator.web_vision_mcp import _get_or_create_page
                new_page = await _get_or_create_page(session_id)

                if new_page:
                    # Step 5: Verify the new page is healthy
                    is_healthy, health_error = await self._check_page_health(new_page)
                    if is_healthy:
                        logger.info(f"[BrowserRecovery] Recovery successful for {session_id}")
                        self.mark_healthy(session_id)
                        attempt.success = True
                        attempt.completed_at = datetime.utcnow()
                        attempt.duration_ms = int(
                            (attempt.completed_at - attempt.started_at).total_seconds() * 1000
                        )
                        return True, new_page
                    else:
                        logger.warning(
                            f"[BrowserRecovery] New page failed health check: {health_error}"
                        )
                        attempt.error = health_error
                else:
                    logger.warning(f"[BrowserRecovery] Failed to create new page for {session_id}")
                    attempt.error = "Failed to create new page"

                attempt.completed_at = datetime.utcnow()
                attempt.duration_ms = int(
                    (attempt.completed_at - attempt.started_at).total_seconds() * 1000
                )
                return False, None

            except Exception as e:
                logger.error(f"[BrowserRecovery] Recovery failed for {session_id}: {e}", exc_info=True)
                attempt.error = str(e)
                attempt.completed_at = datetime.utcnow()
                attempt.duration_ms = int(
                    (attempt.completed_at - attempt.started_at).total_seconds() * 1000
                )
                return False, None

            finally:
                self._recovering_sessions.discard(session_id)
                self._recovery_history.append(attempt)
                # Trim history if needed
                if len(self._recovery_history) > self._max_history:
                    self._recovery_history = self._recovery_history[-self._max_history:]

    async def get_healthy_page(self, session_id: str, auto_recover: bool = True):
        """
        Get a healthy page for a session, recovering if necessary.

        Args:
            session_id: Session identifier
            auto_recover: Whether to attempt recovery if page is unhealthy

        Returns:
            Healthy page or None
        """
        from apps.services.orchestrator.web_vision_mcp import _get_or_create_page

        page = await _get_or_create_page(session_id)

        if page:
            is_healthy, error = await self._check_page_health(page)
            if is_healthy:
                self.mark_healthy(session_id)
                return page
            else:
                self.mark_unhealthy(session_id, error or "Unknown error")

                if auto_recover:
                    success, new_page = await self.recover_session(session_id)
                    if success:
                        return new_page

        return None

    async def execute_with_recovery(
        self,
        session_id: str,
        operation: Callable,
        *args,
        max_retries: int = 2,
        **kwargs
    ):
        """
        Execute an operation with automatic recovery on connection failure.

        Args:
            session_id: Session identifier
            operation: Async function to execute (receives page as first arg)
            *args: Additional arguments for operation
            max_retries: Maximum retry attempts
            **kwargs: Additional keyword arguments

        Returns:
            Operation result or raises exception
        """
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # Get a healthy page
                page = await self.get_healthy_page(session_id, auto_recover=attempt > 0)

                if not page:
                    raise RuntimeError(f"Could not get healthy page for session {session_id}")

                # Execute the operation
                result = await operation(page, *args, **kwargs)

                # Success - mark healthy
                self.mark_healthy(session_id)
                return result

            except Exception as e:
                last_error = e

                if self.is_connection_error(e):
                    logger.warning(
                        f"[BrowserRecovery] Connection error in operation (attempt {attempt + 1}/{max_retries + 1}): "
                        f"{str(e)[:100]}"
                    )
                    self.mark_unhealthy(session_id, str(e))

                    if attempt < max_retries:
                        # Try recovery
                        can_recover, reason = self.can_recover(session_id)
                        if can_recover:
                            success, _ = await self.recover_session(session_id)
                            if success:
                                continue  # Retry with recovered session
                        else:
                            logger.warning(f"[BrowserRecovery] Cannot recover: {reason}")
                else:
                    # Non-connection error, don't retry
                    raise

        # All retries exhausted
        raise last_error or RuntimeError("Operation failed after all retries")

    def get_stats(self) -> Dict[str, Any]:
        """Get recovery manager statistics."""
        total_recoveries = len(self._recovery_history)
        successful = sum(1 for r in self._recovery_history if r.success)
        failed = total_recoveries - successful

        avg_duration = 0
        if total_recoveries > 0:
            avg_duration = sum(r.duration_ms for r in self._recovery_history) / total_recoveries

        unhealthy_sessions = [
            sid for sid, health in self._session_health.items()
            if not health.is_healthy
        ]

        return {
            "total_recoveries": total_recoveries,
            "successful_recoveries": successful,
            "failed_recoveries": failed,
            "success_rate": successful / total_recoveries if total_recoveries > 0 else 1.0,
            "avg_recovery_duration_ms": avg_duration,
            "currently_recovering": list(self._recovering_sessions),
            "unhealthy_sessions": unhealthy_sessions,
            "tracked_sessions": len(self._session_health),
        }

    def reset_session_health(self, session_id: str):
        """Reset health tracking for a session (e.g., after manual intervention)."""
        if session_id in self._session_health:
            del self._session_health[session_id]
        if session_id in self._recovery_locks:
            del self._recovery_locks[session_id]
        logger.info(f"[BrowserRecovery] Reset health tracking for {session_id}")


# Global singleton
_recovery_manager: Optional[BrowserRecoveryManager] = None
_recovery_lock = asyncio.Lock()


def get_browser_recovery_manager() -> BrowserRecoveryManager:
    """Get the global browser recovery manager (singleton)."""
    global _recovery_manager
    if _recovery_manager is None:
        _recovery_manager = BrowserRecoveryManager()
    return _recovery_manager


# Type variable for decorator
T = TypeVar('T')


def with_browser_recovery(
    session_id_param: str = "session_id",
    max_retries: int = 2
):
    """
    Decorator for browser operations that need automatic recovery.

    Usage:
        @with_browser_recovery(session_id_param="session_id")
        async def my_operation(session_id: str, page, other_arg):
            # page is passed automatically after recovery
            await page.goto(url)

    The decorated function receives the page as the second argument (after session_id).
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract session_id from args or kwargs
            session_id = kwargs.get(session_id_param)
            if session_id is None and args:
                # Try to get from first positional arg
                session_id = args[0]

            if not session_id:
                raise ValueError(f"Could not determine session_id from {session_id_param}")

            recovery_manager = get_browser_recovery_manager()

            async def operation_with_page(page, *op_args, **op_kwargs):
                # Call the original function with page injected
                return await func(session_id, page, *op_args[1:], **op_kwargs)

            return await recovery_manager.execute_with_recovery(
                session_id,
                operation_with_page,
                *args,
                max_retries=max_retries,
                **kwargs
            )

        return wrapper
    return decorator
