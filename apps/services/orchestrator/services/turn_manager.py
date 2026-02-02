"""
Turn Manager for PandaAI Orchestrator

Manages turn lifecycle: creation, updates, retrieval, and listing.
Uses in-memory storage (can be swapped to PostgreSQL later).

Architecture Reference:
    architecture/main-system-patterns/phase*.md
    architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md

Turn Lifecycle:
    1. create_turn() - Creates turn with PENDING state
    2. update_turn() - Updates turn state, phase results, response
    3. get_turn() - Retrieves turn by ID
    4. list_turns() - Lists recent turns

Turn States:
    - PENDING: Turn created, not yet processing
    - PROCESSING: Pipeline is executing
    - COMPLETED: Pipeline finished successfully
    - FAILED: Pipeline failed
    - CANCELLED: User cancelled
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from threading import Lock

from apps.services.orchestrator.models.turn import (
    Turn,
    TurnState,
    TurnMetadata,
    PhaseResult,
    PhaseStatus,
    ValidationResult,
)
from libs.core.config import get_settings


logger = logging.getLogger(__name__)


class TurnManager:
    """
    Manages turn lifecycle with in-memory storage.

    Thread-safe operations for concurrent turn management.
    Can be extended to use PostgreSQL for persistence.

    Usage:
        manager = TurnManager()

        # Create a new turn
        turn = manager.create_turn("What is Python?", "session_123")

        # Update turn state
        manager.update_turn(turn.metadata.turn_id, state=TurnState.PROCESSING)

        # Get turn
        turn = manager.get_turn(turn_id)

        # List recent turns
        turns = manager.list_turns(limit=10)
    """

    def __init__(self, user_id: str = "default"):
        """
        Initialize turn manager.

        Args:
            user_id: User identifier for turn storage path
        """
        self.user_id = user_id
        self.settings = get_settings()

        # In-memory storage
        self._turns: dict[int, Turn] = {}
        self._next_turn_id: int = 1
        self._lock = Lock()

        # Turn directory for context.md files
        self._turns_dir = self.settings.panda_system_docs / "users" / user_id / "turns"
        self._turns_dir.mkdir(parents=True, exist_ok=True)

    def create_turn(
        self,
        query: str,
        session_id: str,
    ) -> Turn:
        """
        Create a new turn.

        Args:
            query: User's query text
            session_id: Session identifier

        Returns:
            Created Turn object with PENDING state
        """
        with self._lock:
            turn_id = self._next_turn_id
            self._next_turn_id += 1

        # Create turn directory
        turn_dir = self._turns_dir / f"turn_{turn_id:06d}"
        turn_dir.mkdir(parents=True, exist_ok=True)

        # Create turn metadata
        metadata = TurnMetadata(
            turn_id=turn_id,
            session_id=session_id,
            query=query,
            created_at=datetime.utcnow(),
        )

        # Create turn
        turn = Turn(
            metadata=metadata,
            state=TurnState.PENDING,
            phases=[],
        )

        # Store turn
        with self._lock:
            self._turns[turn_id] = turn

        logger.info(f"Created turn {turn_id} for session {session_id}")

        return turn

    def update_turn(
        self,
        turn_id: int,
        state: Optional[TurnState] = None,
        current_phase: Optional[int] = None,
        response: Optional[str] = None,
        quality: Optional[float] = None,
        validation: Optional[ValidationResult] = None,
        error: Optional[str] = None,
        tokens_used: Optional[int] = None,
        resolved_query: Optional[str] = None,
        **kwargs,
    ) -> Optional[Turn]:
        """
        Update turn state and attributes.

        Args:
            turn_id: Turn identifier
            state: New turn state
            current_phase: Currently executing phase
            response: Final response text
            quality: Response quality score
            validation: Validation result
            error: Error message if failed
            tokens_used: Total tokens used
            resolved_query: Query with references resolved
            **kwargs: Additional attributes to update

        Returns:
            Updated Turn object, or None if not found
        """
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                logger.warning(f"Turn {turn_id} not found for update")
                return None

            # Update state
            if state is not None:
                turn.state = state
                if state in (TurnState.COMPLETED, TurnState.FAILED, TurnState.CANCELLED):
                    turn.metadata.completed_at = datetime.utcnow()

            # Update current phase
            if current_phase is not None:
                turn.current_phase = current_phase

            # Update response
            if response is not None:
                turn.response = response

            # Update quality
            if quality is not None:
                turn.quality = quality

            # Update validation
            if validation is not None:
                turn.validation = validation

            # Update error
            if error is not None:
                turn.error = error

            # Update tokens
            if tokens_used is not None:
                turn.tokens_used = tokens_used

            # Update resolved query
            if resolved_query is not None:
                turn.metadata.resolved_query = resolved_query

            # Handle additional kwargs
            for key, value in kwargs.items():
                if hasattr(turn, key):
                    setattr(turn, key, value)
                elif hasattr(turn.metadata, key):
                    setattr(turn.metadata, key, value)

            logger.debug(f"Updated turn {turn_id}: state={turn.state.value}")

            return turn

    def add_phase_result(
        self,
        turn_id: int,
        phase: int,
        name: str,
        status: PhaseStatus,
        duration_ms: Optional[int] = None,
        output: Optional[dict] = None,
        error: Optional[str] = None,
        attempt: int = 1,
    ) -> Optional[Turn]:
        """
        Add a phase result to a turn.

        Args:
            turn_id: Turn identifier
            phase: Phase number (0-7)
            name: Phase name
            status: Phase status
            duration_ms: Phase duration in milliseconds
            output: Phase-specific output data
            error: Error message if failed
            attempt: Attempt number (for REVISE/RETRY loops)

        Returns:
            Updated Turn object, or None if not found
        """
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                logger.warning(f"Turn {turn_id} not found for phase result")
                return None

            result = PhaseResult(
                phase=phase,
                name=name,
                status=status,
                duration_ms=duration_ms,
                output=output,
                error=error,
                attempt=attempt,
            )

            turn.add_phase_result(result)

            logger.debug(f"Added phase {phase} result to turn {turn_id}: {status.value}")

            return turn

    def increment_revise_count(self, turn_id: int) -> Optional[Turn]:
        """Increment REVISE loop counter."""
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                return None
            if turn.can_revise:
                turn.revise_count += 1
            return turn

    def increment_retry_count(self, turn_id: int) -> Optional[Turn]:
        """Increment RETRY loop counter."""
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                return None
            if turn.can_retry:
                turn.retry_count += 1
            return turn

    def get_turn(self, turn_id: int) -> Optional[Turn]:
        """
        Get a turn by ID.

        Args:
            turn_id: Turn identifier

        Returns:
            Turn object, or None if not found
        """
        with self._lock:
            return self._turns.get(turn_id)

    def list_turns(
        self,
        session_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Turn]:
        """
        List turns, optionally filtered by session.

        Args:
            session_id: Filter by session ID (optional)
            limit: Maximum number of turns to return
            offset: Number of turns to skip

        Returns:
            List of Turn objects, sorted by creation time (newest first)
        """
        with self._lock:
            turns = list(self._turns.values())

        # Filter by session if specified
        if session_id is not None:
            turns = [t for t in turns if t.metadata.session_id == session_id]

        # Sort by creation time (newest first)
        turns.sort(key=lambda t: t.metadata.created_at, reverse=True)

        # Apply pagination
        return turns[offset:offset + limit]

    def get_turn_dir(self, turn_id: int) -> Path:
        """Get the directory for a turn's files."""
        return self._turns_dir / f"turn_{turn_id:06d}"

    def get_turn_count(self) -> int:
        """Get total number of turns."""
        with self._lock:
            return len(self._turns)

    def get_session_turns(self, session_id: str) -> list[Turn]:
        """Get all turns for a session."""
        return self.list_turns(session_id=session_id, limit=1000)

    def delete_turn(self, turn_id: int) -> bool:
        """
        Delete a turn from memory.

        Note: Does not delete turn directory/files.

        Args:
            turn_id: Turn identifier

        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            if turn_id in self._turns:
                del self._turns[turn_id]
                logger.info(f"Deleted turn {turn_id} from memory")
                return True
            return False

    def calculate_total_duration(self, turn_id: int) -> Optional[int]:
        """Calculate total duration from phase durations."""
        turn = self.get_turn(turn_id)
        if turn is None:
            return None

        total_ms = 0
        for phase in turn.phases:
            if phase.duration_ms is not None:
                total_ms += phase.duration_ms

        return total_ms if total_ms > 0 else None


# Singleton instance
_turn_manager: Optional[TurnManager] = None


def get_turn_manager(user_id: str = "default") -> TurnManager:
    """Get turn manager singleton."""
    global _turn_manager
    if _turn_manager is None or _turn_manager.user_id != user_id:
        _turn_manager = TurnManager(user_id)
    return _turn_manager
