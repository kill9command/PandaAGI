"""File-based turn store for PandaAI Orchestrator.

Architecture Reference:
    architecture/DOCUMENT-IO-SYSTEM/MEMORY_ARCHITECTURE.md
    architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md

Key Design:
    - Stores turns in panda_system_docs/users/{user_id}/turns/ directory
    - Each turn has context.md and metadata.json
    - Turn numbers are per-user (each user starts at turn 1)
    - Zero-padded 6-digit numbering (turn_000001)

Directory Structure:
    panda_system_docs/users/{user_id}/turns/turn_{number}/
        context.md      # The complete turn document (sections 0-6)
        metadata.json   # Turn metadata for indexing
        research.md     # Research results (optional)
        ticket.md       # Task plan (optional)
        toolresults.md  # Tool execution results (optional)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from libs.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class Turn:
    """Complete turn data."""

    turn_number: int
    session_id: str
    turn_dir: Path
    context_content: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    topic: Optional[str] = None
    intent: Optional[str] = None
    quality: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "turn_number": self.turn_number,
            "session_id": self.session_id,
            "turn_dir": str(self.turn_dir),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "topic": self.topic,
            "intent": self.intent,
            "quality": self.quality,
            "metadata": self.metadata,
        }


@dataclass
class TurnSummary:
    """Lightweight turn summary for listing."""

    turn_number: int
    session_id: str
    topic: Optional[str] = None
    intent: Optional[str] = None
    quality: Optional[float] = None
    created_at: Optional[datetime] = None
    query_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "turn_number": self.turn_number,
            "session_id": self.session_id,
            "topic": self.topic,
            "intent": self.intent,
            "quality": self.quality,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "query_preview": self.query_preview,
        }


class TurnStore:
    """File-based turn storage service.

    Stores and retrieves turns from the filesystem. Each turn is stored
    in a directory with context.md and metadata.json files.

    Example usage:
        store = TurnStore()

        # Save a turn
        turn = Turn(
            turn_number=1,
            session_id="henry",
            turn_dir=Path("..."),
            context_content="# Context Document...",
            topic="electronics.laptop",
            quality=0.85,
        )
        await store.save_turn(turn)

        # Load a turn
        loaded = await store.load_turn("henry", 1)

        # List turns
        summaries = await store.list_turns("henry", limit=10)
    """

    def __init__(self):
        """Initialize turn store."""
        self._settings = get_settings()
        self._base_dir = self._settings.panda_system_docs / "users"

    def _get_user_turns_dir(self, session_id: str) -> Path:
        """Get the turns directory for a user."""
        return self._base_dir / session_id / "turns"

    def _get_turn_dir(self, session_id: str, turn_number: int) -> Path:
        """Get the directory for a specific turn."""
        return self._get_user_turns_dir(session_id) / f"turn_{turn_number:06d}"

    async def save_turn(self, turn: Turn) -> None:
        """Save a turn to disk.

        Creates the turn directory and saves:
        - context.md: The complete turn document
        - metadata.json: Turn metadata for indexing

        Args:
            turn: Turn object to save
        """
        turn_dir = self._get_turn_dir(turn.session_id, turn.turn_number)
        turn_dir.mkdir(parents=True, exist_ok=True)

        # Save context.md if provided
        if turn.context_content is not None:
            context_path = turn_dir / "context.md"
            context_path.write_text(turn.context_content)
            logger.debug(f"Saved context.md to {context_path}")

        # Build and save metadata.json
        metadata = {
            "turn_number": turn.turn_number,
            "session_id": turn.session_id,
            "turn_dir": str(turn_dir),
            "created_at": (turn.created_at or datetime.now()).isoformat(),
            "topic": turn.topic,
            "intent": turn.intent,
            "quality": turn.quality,
            **turn.metadata,
        }

        metadata_path = turn_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)

        logger.info(f"Saved turn {turn.turn_number} for session {turn.session_id}")

    async def load_turn(
        self,
        session_id: str,
        turn_number: int,
    ) -> Optional[Turn]:
        """Load a turn from disk.

        Args:
            session_id: User session ID
            turn_number: Turn number to load

        Returns:
            Turn object or None if not found
        """
        turn_dir = self._get_turn_dir(session_id, turn_number)

        if not turn_dir.exists():
            logger.debug(f"Turn {turn_number} not found for session {session_id}")
            return None

        # Load context.md
        context_content = None
        context_path = turn_dir / "context.md"
        if context_path.exists():
            context_content = context_path.read_text()

        # Load metadata.json
        metadata = {}
        metadata_path = turn_dir / "metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path) as f:
                    metadata = json.load(f)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse metadata.json: {e}")

        # Parse created_at
        created_at = None
        if metadata.get("created_at"):
            try:
                created_at = datetime.fromisoformat(metadata["created_at"])
            except (ValueError, TypeError):
                pass

        return Turn(
            turn_number=turn_number,
            session_id=session_id,
            turn_dir=turn_dir,
            context_content=context_content,
            metadata={k: v for k, v in metadata.items()
                     if k not in ("turn_number", "session_id", "turn_dir",
                                  "created_at", "topic", "intent", "quality")},
            created_at=created_at,
            topic=metadata.get("topic"),
            intent=metadata.get("intent"),
            quality=metadata.get("quality"),
        )

    async def list_turns(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[TurnSummary]:
        """List turns for a session.

        Args:
            session_id: User session ID
            limit: Maximum number of turns to return

        Returns:
            List of TurnSummary objects, newest first
        """
        turns_dir = self._get_user_turns_dir(session_id)

        if not turns_dir.exists():
            return []

        summaries = []
        turn_dirs = sorted(turns_dir.iterdir(), reverse=True)

        for turn_dir in turn_dirs[:limit]:
            if not turn_dir.is_dir() or not turn_dir.name.startswith("turn_"):
                continue

            try:
                turn_number = int(turn_dir.name.split("_")[1])
            except (IndexError, ValueError):
                continue

            # Load metadata
            metadata = {}
            metadata_path = turn_dir / "metadata.json"
            if metadata_path.exists():
                try:
                    with open(metadata_path) as f:
                        metadata = json.load(f)
                except json.JSONDecodeError:
                    pass

            # Get query preview from context.md
            query_preview = ""
            context_path = turn_dir / "context.md"
            if context_path.exists():
                try:
                    content = context_path.read_text()
                    # Extract original query
                    for line in content.split("\n"):
                        if line.startswith("**Original:**"):
                            query_preview = line.replace("**Original:**", "").strip()[:200]
                            break
                except Exception:
                    pass

            # Parse created_at
            created_at = None
            if metadata.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(metadata["created_at"])
                except (ValueError, TypeError):
                    pass

            summaries.append(TurnSummary(
                turn_number=turn_number,
                session_id=session_id,
                topic=metadata.get("topic"),
                intent=metadata.get("intent"),
                quality=metadata.get("quality"),
                created_at=created_at,
                query_preview=query_preview,
            ))

        return summaries

    async def get_next_turn_number(self, session_id: str) -> int:
        """Get the next turn number for a session.

        Args:
            session_id: User session ID

        Returns:
            Next sequential turn number (starts at 1)
        """
        turns_dir = self._get_user_turns_dir(session_id)

        if not turns_dir.exists():
            return 1

        max_turn = 0
        for turn_dir in turns_dir.iterdir():
            if turn_dir.is_dir() and turn_dir.name.startswith("turn_"):
                try:
                    turn_num = int(turn_dir.name.split("_")[1])
                    max_turn = max(max_turn, turn_num)
                except (IndexError, ValueError):
                    continue

        return max_turn + 1

    async def delete_turn(
        self,
        session_id: str,
        turn_number: int,
    ) -> bool:
        """Delete a turn and all its contents.

        Args:
            session_id: User session ID
            turn_number: Turn number to delete

        Returns:
            True if deleted, False if not found
        """
        turn_dir = self._get_turn_dir(session_id, turn_number)

        if not turn_dir.exists():
            return False

        import shutil
        shutil.rmtree(turn_dir)
        logger.info(f"Deleted turn {turn_number} for session {session_id}")
        return True

    async def get_turns_by_topic(
        self,
        session_id: str,
        topic: str,
        limit: int = 50,
    ) -> list[TurnSummary]:
        """Find turns matching a topic.

        Args:
            session_id: User session ID
            topic: Topic to search for (partial match)
            limit: Maximum results

        Returns:
            List of matching TurnSummary objects
        """
        all_turns = await self.list_turns(session_id, limit=limit * 2)

        topic_lower = topic.lower()
        matching = [
            t for t in all_turns
            if t.topic and topic_lower in t.topic.lower()
        ]

        return matching[:limit]

    async def update_turn_metadata(
        self,
        session_id: str,
        turn_number: int,
        topic: Optional[str] = None,
        intent: Optional[str] = None,
        quality: Optional[float] = None,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Update turn metadata without modifying context.md.

        Args:
            session_id: User session ID
            turn_number: Turn number
            topic: New topic (optional)
            intent: New intent (optional)
            quality: New quality score (optional)
            extra_metadata: Additional metadata to merge (optional)

        Returns:
            True if updated, False if turn not found
        """
        turn_dir = self._get_turn_dir(session_id, turn_number)
        metadata_path = turn_dir / "metadata.json"

        if not metadata_path.exists():
            return False

        # Load existing metadata
        with open(metadata_path) as f:
            metadata = json.load(f)

        # Update fields
        if topic is not None:
            metadata["topic"] = topic
        if intent is not None:
            metadata["intent"] = intent
        if quality is not None:
            metadata["quality"] = quality
        if extra_metadata:
            metadata.update(extra_metadata)

        # Save updated metadata
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)

        logger.debug(f"Updated metadata for turn {turn_number}")
        return True

    async def turn_exists(self, session_id: str, turn_number: int) -> bool:
        """Check if a turn exists.

        Args:
            session_id: User session ID
            turn_number: Turn number

        Returns:
            True if turn exists
        """
        turn_dir = self._get_turn_dir(session_id, turn_number)
        return turn_dir.exists() and (turn_dir / "context.md").exists()

    async def get_turn_file_path(
        self,
        session_id: str,
        turn_number: int,
        filename: str,
    ) -> Optional[Path]:
        """Get path to a specific file in a turn directory.

        Args:
            session_id: User session ID
            turn_number: Turn number
            filename: Name of file (e.g., "research.md", "ticket.md")

        Returns:
            Path to file or None if turn doesn't exist
        """
        turn_dir = self._get_turn_dir(session_id, turn_number)

        if not turn_dir.exists():
            return None

        return turn_dir / filename
