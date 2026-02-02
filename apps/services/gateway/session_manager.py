"""
Session Management for Pandora Gateway

Implements session-focused architecture with:
- 3 focus slots max
- State machine transitions
- Token budget tracking
- Auto-rotation on budget exhaustion
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Session state machine."""
    IDLE = "idle"
    DISCOVER = "discover"
    DESIGN = "design"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    COMPLETE = "complete"


class SlotType(Enum):
    """Types of work that can occupy a slot."""
    RESEARCH = "research"
    TASK = "task"
    CODE = "code"


class Session:
    """
    Manages a single conversation session with focus slots and budget tracking.
    """

    def __init__(
        self,
        session_id: str,
        profile_id: str,
        token_budget: int = 12000,
        workspace_dir: str = "panda_system_docs/sessions"
    ):
        self.id = session_id
        self.profile_id = profile_id
        self.token_budget = token_budget
        self.tokens_used = 0
        self.created_at = datetime.utcnow()
        self.workspace_dir = Path(workspace_dir) / session_id

        # Focus slots (max 3)
        self.slots: Dict[int, Optional[Dict[str, Any]]] = {
            1: None,
            2: None,
            3: None
        }

        # State machine
        self.state = SessionState.IDLE
        self.previous_state: Optional[SessionState] = None

        # Continuity tracking
        self.previous_session_id: Optional[str] = None
        self.next_session_id: Optional[str] = None

        # Create workspace
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        # Save initial state
        self._save_focus_md()

    def can_allocate(self, tokens_needed: int) -> bool:
        """Check if budget allows allocation."""
        total_allocated = sum(
            slot["budget"] for slot in self.slots.values() if slot
        )

        if total_allocated + tokens_needed > self.token_budget:
            return False
        return True

    def remaining_budget(self) -> int:
        """Get remaining token budget."""
        total_allocated = sum(
            slot["budget"] for slot in self.slots.values() if slot
        )
        return self.token_budget - total_allocated

    def assign_slot(
        self,
        slot_num: int,
        slot_type: SlotType,
        doc_id: str,
        budget: int,
        description: str
    ) -> bool:
        """
        Assign work to a focus slot.

        Returns:
            True if assigned successfully, False if slot occupied or budget exceeded
        """
        if slot_num not in [1, 2, 3]:
            raise ValueError(f"Invalid slot number: {slot_num}")

        # Check if slot already occupied
        if self.slots[slot_num] is not None:
            logger.warning(f"Slot {slot_num} already occupied")
            return False

        # Check budget
        if not self.can_allocate(budget):
            logger.warning(
                f"Cannot allocate {budget} tokens. "
                f"Remaining: {self.remaining_budget()}"
            )
            return False

        # Assign slot
        self.slots[slot_num] = {
            "type": slot_type.value,
            "id": doc_id,
            "status": "pending",
            "budget": budget,
            "used": 0,
            "description": description,
            "started_at": datetime.utcnow().isoformat()
        }

        logger.info(
            f"Assigned slot {slot_num}: {slot_type.value} {doc_id} "
            f"(budget: {budget} tokens)"
        )

        self._save_focus_md()
        return True

    def update_slot_status(self, slot_num: int, status: str, tokens_used: int = 0):
        """Update slot status and token usage."""
        if slot_num not in [1, 2, 3]:
            raise ValueError(f"Invalid slot number: {slot_num}")

        slot = self.slots[slot_num]
        if slot is None:
            logger.warning(f"Slot {slot_num} is empty, cannot update")
            return

        slot["status"] = status
        slot["used"] += tokens_used
        self.tokens_used += tokens_used

        self._save_focus_md()

    def close_slot(self, slot_num: int, outcome: str = "complete") -> Optional[Dict]:
        """Close a slot and return its data."""
        if slot_num not in [1, 2, 3]:
            raise ValueError(f"Invalid slot number: {slot_num}")

        slot = self.slots[slot_num]
        if slot is None:
            logger.warning(f"Slot {slot_num} already empty")
            return None

        logger.info(f"Closing slot {slot_num}: {outcome}")

        slot_data = self.slots[slot_num]
        slot_data["outcome"] = outcome
        slot_data["closed_at"] = datetime.utcnow().isoformat()

        # Free the slot
        self.slots[slot_num] = None

        self._save_focus_md()
        return slot_data

    def get_available_slots(self) -> List[int]:
        """Get list of available slot numbers."""
        return [num for num, slot in self.slots.items() if slot is None]

    def has_completed_slots(self) -> bool:
        """Check if any slots are in completed status."""
        return any(
            slot and slot["status"] == "complete"
            for slot in self.slots.values()
        )

    def transition_state(self, new_state: SessionState):
        """Transition to a new state."""
        self.previous_state = self.state
        self.state = new_state

        logger.info(f"State transition: {self.previous_state.value} → {new_state.value}")
        self._save_focus_md()

    def is_budget_exhausted(self, threshold: float = 0.95) -> bool:
        """Check if budget is exhausted (above threshold %)."""
        return self.tokens_used >= (self.token_budget * threshold)

    def _save_focus_md(self):
        """Save current state to Focus.md."""
        focus_path = self.workspace_dir / "Focus.md"

        # Calculate totals
        total_allocated = sum(
            slot["budget"] for slot in self.slots.values() if slot
        )

        # Build slot table
        slot_rows = []
        for num in [1, 2, 3]:
            slot = self.slots[num]
            if slot:
                slot_rows.append(
                    f"| {num} | {slot['type']} | {slot['id']} | {slot['status']} | "
                    f"{slot['used']} / {slot['budget']} | {slot['description']} |"
                )
            else:
                slot_rows.append(f"| {num} | - | - | empty | 0 / 0 | (available) |")

        content = f"""# Session Focus: {self.id}

**Profile**: {self.profile_id}
**Created**: {self.created_at.isoformat()}
**State**: {self.state.value}

## Current Focus

### Active Slots (3 max)

| Slot | Type | ID | Status | Budget Used | Description |
|------|------|----|----|-------------|-------------|
{chr(10).join(slot_rows)}

**Total Budget**: {self.tokens_used} / {self.token_budget} tokens ({int(self.tokens_used / self.token_budget * 100)}%)
**Allocated**: {total_allocated} tokens
**Remaining**: {self.token_budget - total_allocated} tokens

### State Machine

**Current State**: {self.state.value}
**Previous State**: {self.previous_state.value if self.previous_state else 'none'}

### Session Continuity

**Previous Session**: {self.previous_session_id or 'none'}
**Next Session**: {self.next_session_id or 'none (active)'}
"""

        focus_path.write_text(content)

    def get_focus_summary(self) -> str:
        """Get brief summary of current focus."""
        active_slots = [
            f"Slot {num}: {slot['description']}"
            for num, slot in self.slots.items()
            if slot
        ]

        if not active_slots:
            return f"Session {self.id}: No active tasks (idle)"

        return f"Session {self.id}: {', '.join(active_slots)}"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session to dict."""
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "token_budget": self.token_budget,
            "tokens_used": self.tokens_used,
            "created_at": self.created_at.isoformat(),
            "state": self.state.value,
            "slots": self.slots,
            "previous_session_id": self.previous_session_id,
            "next_session_id": self.next_session_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """Deserialize session from dict."""
        session = cls(
            session_id=data["id"],
            profile_id=data["profile_id"],
            token_budget=data["token_budget"]
        )
        session.tokens_used = data["tokens_used"]
        session.created_at = datetime.fromisoformat(data["created_at"])
        session.state = SessionState(data["state"])
        session.slots = data["slots"]
        session.previous_session_id = data.get("previous_session_id")
        session.next_session_id = data.get("next_session_id")
        return session


class SessionManager:
    """
    Manages multiple sessions with rotation and continuity tracking.
    """

    def __init__(self, workspace_dir: str = "panda_system_docs/sessions"):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.active_sessions: Dict[str, Session] = {}

    def create_session(
        self,
        profile_id: str,
        token_budget: int = 12000,
        previous_session_id: Optional[str] = None
    ) -> Session:
        """Create a new session."""
        # Generate session ID
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        session_id = f"sess-{timestamp}"

        # If previous session exists, append counter
        if previous_session_id:
            # Extract counter from previous ID or start at 002
            if "-" in previous_session_id and previous_session_id.split("-")[-1].isdigit():
                counter = int(previous_session_id.split("-")[-1]) + 1
                session_id = f"{session_id}-{counter:03d}"
            else:
                session_id = f"{session_id}-002"

        session = Session(
            session_id=session_id,
            profile_id=profile_id,
            token_budget=token_budget
        )

        # Link to previous session
        if previous_session_id and previous_session_id in self.active_sessions:
            prev_session = self.active_sessions[previous_session_id]
            prev_session.next_session_id = session_id
            session.previous_session_id = previous_session_id

        self.active_sessions[session_id] = session

        logger.info(
            f"Created session: {session_id} "
            f"(previous: {previous_session_id or 'none'})"
        )

        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get an active session by ID."""
        return self.active_sessions.get(session_id)

    def close_session(self, session_id: str, reason: str = "completed"):
        """Close a session and archive its workspace."""
        session = self.active_sessions.get(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found")
            return

        logger.info(f"Closing session {session_id}: {reason}")

        # Close all open slots
        for slot_num in [1, 2, 3]:
            if session.slots[slot_num]:
                session.close_slot(slot_num, outcome=reason)

        # Archive workspace
        archive_dir = self.workspace_dir.parent / "archives" / "sessions" / session_id
        archive_dir.mkdir(parents=True, exist_ok=True)

        # Copy workspace to archive
        import shutil
        if session.workspace_dir.exists():
            shutil.copytree(
                session.workspace_dir,
                archive_dir,
                dirs_exist_ok=True
            )

        # Remove from active sessions
        del self.active_sessions[session_id]

        # Save session metadata
        metadata_path = archive_dir / "session_metadata.json"
        metadata_path.write_text(json.dumps(session.to_dict(), indent=2))

    def rotate_session(
        self,
        current_session_id: str,
        reason: str = "budget_exhausted"
    ) -> Session:
        """Close current session and create a new one."""
        current_session = self.active_sessions.get(current_session_id)
        if not current_session:
            raise ValueError(f"Session {current_session_id} not found")

        logger.info(f"Rotating session {current_session_id}: {reason}")

        # Create new session linked to current
        new_session = self.create_session(
            profile_id=current_session.profile_id,
            token_budget=current_session.token_budget,
            previous_session_id=current_session_id
        )

        # Close current session
        self.close_session(current_session_id, reason=reason)

        return new_session


# Global session manager instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
