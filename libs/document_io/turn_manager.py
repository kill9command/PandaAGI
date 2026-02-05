"""Panda turn lifecycle management.

Architecture Reference:
    architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md#13-file-structure
    architecture/main-system-patterns/phase8-save.md

Key Design:
    - Turn directories use zero-padded 6-digit numbering
    - Turn numbers are per-user (each user starts at turn 1)
    - Session ID = permanent user identity

Directory Structure:
    panda_system_docs/users/{user_id}/turns/{turn_number}/
    ├── context.md      # Main turn document (8-phase pipeline)
    ├── research.md     # Research results (if applicable)
    ├── ticket.md       # Plan from Planner (Phase 3)
    ├── toolresults.md  # Tool outputs (Phase 4/5)
    └── metadata.json   # Turn metadata
"""

from datetime import datetime
from pathlib import Path
from typing import Optional
import json

from libs.core.config import get_settings
from libs.core.models import TurnMetadata
from libs.document_io.context_manager import ContextManager


class TurnManager:
    """Manages turn lifecycle and storage.

    Each user has their own namespace of turns starting at turn 1.
    Turns are stored in zero-padded 6-digit directories (turn_000001).
    """

    def __init__(self, session_id: str):
        """
        Initialize turn manager for a session.

        Args:
            session_id: User session identifier (permanent user ID)
        """
        self.session_id = session_id
        self.settings = get_settings()
        self.user_dir = self.settings.panda_system_docs / "users" / session_id
        self.turns_dir = self.user_dir / "turns"

    def get_next_turn_number(self) -> int:
        """
        Get the next turn number for this session.

        Scans the user's turns directory to find the highest existing
        turn number and returns the next sequential number.

        Returns:
            Next sequential turn number (starts at 1 for new users)
        """
        if not self.turns_dir.exists():
            return 1

        # Find highest existing turn number
        max_turn = 0
        for turn_dir in self.turns_dir.iterdir():
            if turn_dir.is_dir() and turn_dir.name.startswith("turn_"):
                try:
                    turn_num = int(turn_dir.name.split("_")[1])
                    max_turn = max(max_turn, turn_num)
                except (IndexError, ValueError):
                    continue

        return max_turn + 1

    def create_turn(self, query: str) -> tuple[int, ContextManager]:
        """
        Create a new turn.

        Creates the turn directory structure and initializes the
        context.md document with the user's query.

        Args:
            query: User's query

        Returns:
            Tuple of (turn_number, context_manager)
        """
        turn_number = self.get_next_turn_number()
        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        turn_dir.mkdir(parents=True, exist_ok=True)

        # Create context manager
        context = ContextManager(turn_dir)
        context.create(query, self.session_id, turn_number)

        # Create initial metadata
        metadata = TurnMetadata(
            turn_number=turn_number,
            session_id=self.session_id,
            turn_dir=str(turn_dir),
        )
        self._save_metadata(turn_dir, metadata)

        return turn_number, context

    def get_turn(self, turn_number: int) -> Optional[ContextManager]:
        """
        Get context manager for an existing turn.

        Args:
            turn_number: Turn number

        Returns:
            ContextManager or None if turn doesn't exist
        """
        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        if not turn_dir.exists():
            return None
        return ContextManager(turn_dir)

    def get_turn_dir(self, turn_number: int) -> Optional[Path]:
        """
        Get the directory path for a turn.

        Args:
            turn_number: Turn number

        Returns:
            Path to turn directory or None if it doesn't exist
        """
        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        if not turn_dir.exists():
            return None
        return turn_dir

    def get_recent_turns(self, limit: int = 10) -> list[TurnMetadata]:
        """
        Get metadata for recent turns.

        Args:
            limit: Maximum number of turns to return

        Returns:
            List of turn metadata, newest first
        """
        if not self.turns_dir.exists():
            return []

        turns = []
        for turn_dir in sorted(self.turns_dir.iterdir(), reverse=True):
            if len(turns) >= limit:
                break

            if turn_dir.is_dir() and turn_dir.name.startswith("turn_"):
                metadata = self._load_metadata(turn_dir)
                if metadata:
                    turns.append(metadata)

        return turns

    def get_turn_summaries(self, limit: int = 5) -> list[dict]:
        """
        Get brief summaries of recent turns for reference resolution.

        Used by Phase 0 (Query Analyzer) to resolve references like
        "that laptop" or "the thread from earlier".

        Args:
            limit: Maximum number of turns

        Returns:
            List of turn summaries with basic info
        """
        summaries = []
        turns = self.get_recent_turns(limit)

        for metadata in turns:
            turn_dir = Path(metadata.turn_dir)
            context = ContextManager(turn_dir)

            # Get section 0 for query info
            section_0 = context.read_section(0)

            summaries.append({
                "turn_number": metadata.turn_number,
                "topic": metadata.topic,
                "action_needed": metadata.action_needed,
                "query_preview": section_0[:200] if section_0 else "",
            })

        return summaries

    def finalize_turn(
        self,
        turn_number: int,
        topic: Optional[str] = None,
        action_needed: Optional[str] = None,
        quality: Optional[float] = None,
    ) -> None:
        """
        Finalize turn with metadata updates.

        Called by Phase 7 (Save) to update turn metadata after
        pipeline completion.

        Args:
            turn_number: Turn to finalize
            topic: Inferred topic
            action_needed: Action classification from Phase 0
            quality: Overall quality score
        """
        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        metadata = self._load_metadata(turn_dir)

        if metadata:
            metadata.topic = topic or metadata.topic
            metadata.action_needed = action_needed or metadata.action_needed
            metadata.quality = quality or metadata.quality
            self._save_metadata(turn_dir, metadata)

    def list_all_turns(self) -> list[int]:
        """
        List all turn numbers for this session.

        Returns:
            List of turn numbers in ascending order
        """
        if not self.turns_dir.exists():
            return []

        turn_numbers = []
        for turn_dir in self.turns_dir.iterdir():
            if turn_dir.is_dir() and turn_dir.name.startswith("turn_"):
                try:
                    turn_num = int(turn_dir.name.split("_")[1])
                    turn_numbers.append(turn_num)
                except (IndexError, ValueError):
                    continue

        return sorted(turn_numbers)

    def get_turns_by_topic(self, topic: str) -> list[TurnMetadata]:
        """
        Find turns matching a topic.

        Args:
            topic: Topic to search for (partial match)

        Returns:
            List of matching turn metadata
        """
        matching = []
        all_turns = self.get_recent_turns(limit=100)

        topic_lower = topic.lower()
        for metadata in all_turns:
            if metadata.topic and topic_lower in metadata.topic.lower():
                matching.append(metadata)

        return matching

    def _save_metadata(self, turn_dir: Path, metadata: TurnMetadata) -> None:
        """Save turn metadata to JSON."""
        metadata_path = turn_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata.model_dump(mode="json"), f, indent=2, default=str)

    def _load_metadata(self, turn_dir: Path) -> Optional[TurnMetadata]:
        """Load turn metadata from JSON."""
        metadata_path = turn_dir / "metadata.json"
        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path) as f:
                data = json.load(f)
            return TurnMetadata(**data)
        except Exception:
            return None

    def delete_turn(self, turn_number: int) -> bool:
        """
        Delete a turn and all its contents.

        Use with caution - this permanently removes the turn.

        Args:
            turn_number: Turn to delete

        Returns:
            True if deleted, False if turn doesn't exist
        """
        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        if not turn_dir.exists():
            return False

        import shutil
        shutil.rmtree(turn_dir)
        return True
