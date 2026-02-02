"""
orchestrator/browser_session_registry.py

Central registry for all active browser sessions with CDP (Chrome DevTools Protocol) access.
Enables UI-driven browser viewing and control for manual interventions.

Created: 2025-11-22
Part of: Browser Control Integration (Phase 1)
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Literal
from enum import Enum

logger = logging.getLogger(__name__)


class SessionStatus(str, Enum):
    """Browser session status"""
    ACTIVE = "active"           # Browser running normally
    PAUSED = "paused"           # Paused for intervention (CAPTCHA, etc.)
    CLOSED = "closed"           # Browser session terminated
    TIMEOUT = "timeout"         # Session timed out due to inactivity


@dataclass
class BrowserSession:
    """
    Represents a controllable browser session with CDP access.

    This enables users to view and control the browser from their
    laptop/phone via the web UI.
    """
    session_id: str                                  # e.g., "user1_research:web_vision"
    cdp_url: Optional[str] = None                    # CDP WebSocket URL
    cdp_http_url: Optional[str] = None               # CDP HTTP endpoint for DevTools
    status: SessionStatus = SessionStatus.ACTIVE
    current_url: str = "about:blank"
    viewable: bool = True                            # Whether this session can be viewed remotely
    intervention_id: Optional[str] = None            # Linked intervention if paused
    user_agent: Optional[str] = None
    viewport: Optional[Dict[str, int]] = None        # {"width": 1920, "height": 1080}
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    last_url_update: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict = field(default_factory=dict)     # Extra session data

    def update_activity(self):
        """Mark session as active (reset idle timer)"""
        self.last_activity = datetime.utcnow()

    def update_url(self, url: str):
        """Update current URL and activity timestamp"""
        self.current_url = url
        self.last_url_update = datetime.utcnow()
        self.update_activity()

    def is_idle(self, timeout_minutes: int = 30) -> bool:
        """Check if session has been idle for too long"""
        idle_duration = datetime.utcnow() - self.last_activity
        return idle_duration > timedelta(minutes=timeout_minutes)

    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses"""
        return {
            "session_id": self.session_id,
            "cdp_url": self.cdp_url,
            "cdp_http_url": self.cdp_http_url,
            "status": self.status.value,
            "current_url": self.current_url,
            "viewable": self.viewable,
            "intervention_id": self.intervention_id,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "user_agent": self.user_agent,
            "viewport": self.viewport,
            "metadata": self.metadata
        }


class BrowserSessionRegistry:
    """
    Thread-safe central registry for all active browser sessions.

    Manages session lifecycle, status updates, and cleanup.
    """

    def __init__(self):
        self._sessions: Dict[str, BrowserSession] = {}
        self._lock = threading.RLock()
        logger.info("[BrowserSessionRegistry] Initialized")

    def register_session(
        self,
        session_id: str,
        cdp_url: Optional[str] = None,
        cdp_http_url: Optional[str] = None,
        viewable: bool = True,
        metadata: Optional[Dict] = None
    ) -> BrowserSession:
        """
        Register a new browser session.

        Args:
            session_id: Unique session identifier
            cdp_url: Chrome DevTools Protocol WebSocket URL
            cdp_http_url: CDP HTTP endpoint (for DevTools frontend)
            viewable: Whether session can be viewed remotely
            metadata: Additional session data

        Returns:
            BrowserSession object
        """
        with self._lock:
            session = BrowserSession(
                session_id=session_id,
                cdp_url=cdp_url,
                cdp_http_url=cdp_http_url,
                viewable=viewable,
                metadata=metadata or {}
            )
            self._sessions[session_id] = session

            logger.info(
                f"[BrowserSessionRegistry] Registered session: {session_id} "
                f"(viewable={viewable}, cdp={cdp_url is not None})"
            )
            return session

    def get_session(self, session_id: str) -> Optional[BrowserSession]:
        """Get session by ID"""
        with self._lock:
            return self._sessions.get(session_id)

    def update_session(
        self,
        session_id: str,
        **kwargs
    ) -> Optional[BrowserSession]:
        """
        Update session attributes.

        Args:
            session_id: Session to update
            **kwargs: Attributes to update (status, current_url, etc.)
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                logger.warning(f"[BrowserSessionRegistry] Session not found: {session_id}")
                return None

            for key, value in kwargs.items():
                if hasattr(session, key):
                    setattr(session, key, value)

            session.update_activity()
            logger.debug(f"[BrowserSessionRegistry] Updated session: {session_id} ({kwargs})")
            return session

    def mark_paused(
        self,
        session_id: str,
        intervention_id: str,
        reason: Optional[str] = None
    ) -> bool:
        """
        Mark session as paused for intervention.

        Args:
            session_id: Session to pause
            intervention_id: ID of intervention causing pause
            reason: Optional reason (e.g., "captcha_recaptcha")
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            session.status = SessionStatus.PAUSED
            session.intervention_id = intervention_id
            if reason:
                session.metadata["pause_reason"] = reason
            session.update_activity()

            logger.info(
                f"[BrowserSessionRegistry] Paused session: {session_id} "
                f"(intervention={intervention_id}, reason={reason})"
            )
            return True

    def mark_resumed(self, session_id: str) -> bool:
        """Mark session as resumed (after intervention resolved)"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            session.status = SessionStatus.ACTIVE
            session.intervention_id = None
            session.metadata.pop("pause_reason", None)
            session.update_activity()

            logger.info(f"[BrowserSessionRegistry] Resumed session: {session_id}")
            return True

    def close_session(self, session_id: str, reason: str = "normal") -> bool:
        """
        Close a browser session.

        Args:
            session_id: Session to close
            reason: Closure reason (normal, timeout, error)
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            if reason == "timeout":
                session.status = SessionStatus.TIMEOUT
            else:
                session.status = SessionStatus.CLOSED

            session.metadata["close_reason"] = reason
            session.metadata["closed_at"] = datetime.utcnow().isoformat()

            logger.info(f"[BrowserSessionRegistry] Closed session: {session_id} (reason={reason})")
            return True

    def remove_session(self, session_id: str) -> bool:
        """Remove session from registry (cleanup)"""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"[BrowserSessionRegistry] Removed session: {session_id}")
                return True
            return False

    def get_viewable_sessions(self) -> List[BrowserSession]:
        """Get all sessions that can be viewed remotely"""
        with self._lock:
            return [
                session for session in self._sessions.values()
                if session.viewable and session.status != SessionStatus.CLOSED
            ]

    def get_active_sessions(self) -> List[BrowserSession]:
        """Get all active sessions"""
        with self._lock:
            return [
                session for session in self._sessions.values()
                if session.status == SessionStatus.ACTIVE
            ]

    def get_paused_sessions(self) -> List[BrowserSession]:
        """Get all paused sessions (awaiting intervention)"""
        with self._lock:
            return [
                session for session in self._sessions.values()
                if session.status == SessionStatus.PAUSED
            ]

    def cleanup_idle_sessions(self, timeout_minutes: int = 30) -> int:
        """
        Remove idle sessions that have been inactive for too long.

        Args:
            timeout_minutes: Idle timeout in minutes

        Returns:
            Number of sessions cleaned up
        """
        with self._lock:
            idle_sessions = [
                session_id for session_id, session in self._sessions.items()
                if session.is_idle(timeout_minutes) and session.status != SessionStatus.CLOSED
            ]

            for session_id in idle_sessions:
                self.close_session(session_id, reason="timeout")

            logger.info(
                f"[BrowserSessionRegistry] Cleaned up {len(idle_sessions)} idle sessions "
                f"(timeout={timeout_minutes}min)"
            )
            return len(idle_sessions)

    def get_all_sessions(self) -> List[BrowserSession]:
        """Get all sessions (including closed)"""
        with self._lock:
            return list(self._sessions.values())

    def session_count(self) -> int:
        """Get total number of sessions"""
        with self._lock:
            return len(self._sessions)

    def get_stats(self) -> Dict:
        """Get registry statistics"""
        with self._lock:
            total = len(self._sessions)
            active = sum(1 for s in self._sessions.values() if s.status == SessionStatus.ACTIVE)
            paused = sum(1 for s in self._sessions.values() if s.status == SessionStatus.PAUSED)
            closed = sum(1 for s in self._sessions.values() if s.status == SessionStatus.CLOSED)
            viewable = sum(1 for s in self._sessions.values() if s.viewable)

            return {
                "total": total,
                "active": active,
                "paused": paused,
                "closed": closed,
                "viewable": viewable,
                "with_cdp": sum(1 for s in self._sessions.values() if s.cdp_url is not None)
            }


# Global singleton instance
_registry_instance: Optional[BrowserSessionRegistry] = None
_registry_lock = threading.Lock()


def get_browser_session_registry() -> BrowserSessionRegistry:
    """
    Get the global browser session registry (singleton).

    Thread-safe lazy initialization.
    """
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = BrowserSessionRegistry()
    return _registry_instance
