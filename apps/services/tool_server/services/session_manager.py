"""
Session Manager for PandaAI Orchestrator

Manages session state: creation, retrieval, and turn history.
Sessions group related turns for conversation continuity.

Architecture Reference:
    architecture/services/user-interface.md
    architecture/main-system-patterns/phase2-context-gathering.md

Session Lifecycle:
    1. get_or_create_session() - Creates or retrieves session
    2. add_turn_to_session() - Associates turn with session
    3. get_session_turns() - Gets all turns for a session
    4. update_session_state() - Updates session preferences/state
"""

import logging
from datetime import datetime
from typing import Any, Optional
from threading import Lock

from pydantic import BaseModel, Field

from apps.services.tool_server.models.turn import Turn


logger = logging.getLogger(__name__)


class Session(BaseModel):
    """
    Session model for tracking conversation state.

    A session groups related turns and maintains state
    like preferences and topic context.
    """
    session_id: str = Field(
        description="Unique session identifier"
    )
    user_id: str = Field(
        default="default",
        description="User who owns this session"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Session creation time"
    )
    last_activity: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last activity timestamp"
    )
    turn_ids: list[int] = Field(
        default_factory=list,
        description="List of turn IDs in this session"
    )
    current_topic: Optional[str] = Field(
        default=None,
        description="Current conversation topic"
    )
    preferences: dict[str, Any] = Field(
        default_factory=dict,
        description="Session-level preferences (budget, style, etc.)"
    )
    state: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary session state"
    )
    is_active: bool = Field(
        default=True,
        description="Whether session is currently active"
    )

    @property
    def turn_count(self) -> int:
        """Number of turns in this session."""
        return len(self.turn_ids)

    @property
    def duration_seconds(self) -> float:
        """Session duration in seconds."""
        return (self.last_activity - self.created_at).total_seconds()


class SessionManager:
    """
    Manages session lifecycle with in-memory storage.

    Thread-safe operations for concurrent session management.
    Tracks active sessions and their associated turns.

    Usage:
        manager = SessionManager()

        # Get or create session
        session = manager.get_or_create_session("session_123")

        # Add turn to session
        manager.add_turn_to_session("session_123", turn_id=42)

        # Get session turns
        turn_ids = manager.get_session_turn_ids("session_123")

        # Update session state
        manager.update_session_state("session_123", {"topic": "laptops"})
    """

    def __init__(self):
        """Initialize session manager."""
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()

    def get_or_create_session(
        self,
        session_id: str,
        user_id: str = "default",
    ) -> Session:
        """
        Get existing session or create new one.

        Args:
            session_id: Session identifier
            user_id: User identifier

        Returns:
            Session object (existing or newly created)
        """
        with self._lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]
                session.last_activity = datetime.utcnow()
                logger.debug(f"Retrieved existing session {session_id}")
                return session

            # Create new session
            session = Session(
                session_id=session_id,
                user_id=user_id,
                created_at=datetime.utcnow(),
                last_activity=datetime.utcnow(),
            )
            self._sessions[session_id] = session

            logger.info(f"Created new session {session_id} for user {user_id}")

            return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """
        Get session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Session object, or None if not found
        """
        with self._lock:
            return self._sessions.get(session_id)

    def add_turn_to_session(
        self,
        session_id: str,
        turn_id: int,
    ) -> Optional[Session]:
        """
        Add a turn to a session.

        Args:
            session_id: Session identifier
            turn_id: Turn identifier to add

        Returns:
            Updated Session, or None if session not found
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                logger.warning(f"Session {session_id} not found for turn {turn_id}")
                return None

            if turn_id not in session.turn_ids:
                session.turn_ids.append(turn_id)
            session.last_activity = datetime.utcnow()

            logger.debug(f"Added turn {turn_id} to session {session_id}")

            return session

    def get_session_turn_ids(self, session_id: str) -> list[int]:
        """
        Get all turn IDs for a session.

        Args:
            session_id: Session identifier

        Returns:
            List of turn IDs in chronological order
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return []
            return list(session.turn_ids)

    def get_session_turns(
        self,
        session_id: str,
        turn_manager: Any,  # Avoid circular import
    ) -> list[Turn]:
        """
        Get all turns for a session.

        Args:
            session_id: Session identifier
            turn_manager: TurnManager instance to retrieve turns

        Returns:
            List of Turn objects in chronological order
        """
        turn_ids = self.get_session_turn_ids(session_id)
        turns = []
        for turn_id in turn_ids:
            turn = turn_manager.get_turn(turn_id)
            if turn is not None:
                turns.append(turn)
        return turns

    def update_session_state(
        self,
        session_id: str,
        state_updates: dict[str, Any],
    ) -> Optional[Session]:
        """
        Update session state.

        Args:
            session_id: Session identifier
            state_updates: State key-value pairs to update

        Returns:
            Updated Session, or None if not found
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                logger.warning(f"Session {session_id} not found for state update")
                return None

            session.state.update(state_updates)
            session.last_activity = datetime.utcnow()

            logger.debug(f"Updated session {session_id} state: {list(state_updates.keys())}")

            return session

    def set_session_preference(
        self,
        session_id: str,
        key: str,
        value: Any,
    ) -> Optional[Session]:
        """
        Set a session preference.

        Args:
            session_id: Session identifier
            key: Preference key
            value: Preference value

        Returns:
            Updated Session, or None if not found
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None

            session.preferences[key] = value
            session.last_activity = datetime.utcnow()

            logger.debug(f"Set session {session_id} preference: {key}={value}")

            return session

    def get_session_preference(
        self,
        session_id: str,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Get a session preference.

        Args:
            session_id: Session identifier
            key: Preference key
            default: Default value if not found

        Returns:
            Preference value, or default
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return default
            return session.preferences.get(key, default)

    def set_current_topic(
        self,
        session_id: str,
        topic: str,
    ) -> Optional[Session]:
        """
        Set the current conversation topic.

        Args:
            session_id: Session identifier
            topic: Topic description

        Returns:
            Updated Session, or None if not found
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None

            session.current_topic = topic
            session.last_activity = datetime.utcnow()

            logger.debug(f"Set session {session_id} topic: {topic}")

            return session

    def deactivate_session(self, session_id: str) -> Optional[Session]:
        """
        Mark session as inactive.

        Args:
            session_id: Session identifier

        Returns:
            Updated Session, or None if not found
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None

            session.is_active = False
            session.last_activity = datetime.utcnow()

            logger.info(f"Deactivated session {session_id}")

            return session

    def list_sessions(
        self,
        user_id: Optional[str] = None,
        active_only: bool = False,
        limit: int = 50,
    ) -> list[Session]:
        """
        List sessions, optionally filtered.

        Args:
            user_id: Filter by user ID
            active_only: Only return active sessions
            limit: Maximum sessions to return

        Returns:
            List of sessions, sorted by last activity (newest first)
        """
        with self._lock:
            sessions = list(self._sessions.values())

        # Filter by user
        if user_id is not None:
            sessions = [s for s in sessions if s.user_id == user_id]

        # Filter by active status
        if active_only:
            sessions = [s for s in sessions if s.is_active]

        # Sort by last activity
        sessions.sort(key=lambda s: s.last_activity, reverse=True)

        return sessions[:limit]

    def get_session_count(self) -> int:
        """Get total number of sessions."""
        with self._lock:
            return len(self._sessions)

    def get_active_session_count(self) -> int:
        """Get number of active sessions."""
        with self._lock:
            return sum(1 for s in self._sessions.values() if s.is_active)

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session from memory.

        Note: Does not delete associated turns.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"Deleted session {session_id}")
                return True
            return False

    def cleanup_inactive_sessions(
        self,
        max_age_hours: int = 24,
    ) -> int:
        """
        Remove inactive sessions older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours for inactive sessions

        Returns:
            Number of sessions removed
        """
        now = datetime.utcnow()
        removed = 0

        with self._lock:
            to_remove = []
            for session_id, session in self._sessions.items():
                if not session.is_active:
                    age_hours = (now - session.last_activity).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        to_remove.append(session_id)

            for session_id in to_remove:
                del self._sessions[session_id]
                removed += 1

        if removed > 0:
            logger.info(f"Cleaned up {removed} inactive sessions")

        return removed


# Singleton instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get session manager singleton."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
