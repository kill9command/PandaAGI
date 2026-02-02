"""
Atomic turn number generation for V5 flow.

Uses file locking to prevent race conditions when multiple concurrent
requests try to create turns at the same time.
"""

import json
import fcntl
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TurnCounter:
    """
    Thread-safe, process-safe turn number counter.

    Uses file locking to ensure atomic increment operations across
    multiple concurrent requests.
    """

    def __init__(self, turns_dir: Path = None):
        # Use new consolidated path structure under obsidian_memory/Users/
        self.turns_dir = turns_dir or Path("panda_system_docs/obsidian_memory/Users/default/turns")
        self.turns_dir.mkdir(parents=True, exist_ok=True)
        self.counter_file = self.turns_dir / ".turn_counter.json"
        self.lock_file = self.turns_dir / ".turn_lock"

    def get_next_turn_number(self, session_id: Optional[str] = None) -> int:
        """
        Get the next turn number atomically.

        Args:
            session_id: Optional session ID for session-scoped counters.
                       If None, uses global counter.

        Returns:
            Next turn number (guaranteed unique within scope)
        """
        # Ensure lock file exists
        self.lock_file.touch(exist_ok=True)

        with open(self.lock_file, 'r+') as lock:
            # Acquire exclusive lock
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                # Read current counters
                if self.counter_file.exists():
                    try:
                        counters = json.loads(self.counter_file.read_text())
                    except (json.JSONDecodeError, IOError):
                        counters = {}
                else:
                    counters = {}

                # Determine counter key
                key = session_id if session_id else "_global"

                # Get current value and increment
                current = counters.get(key, self._scan_max_turn_number())
                next_turn = current + 1

                # Update counter
                counters[key] = next_turn
                self.counter_file.write_text(json.dumps(counters, indent=2))

                logger.debug(f"[TurnCounter] Allocated turn {next_turn} for {key}")
                return next_turn

            finally:
                # Release lock
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _scan_max_turn_number(self) -> int:
        """
        Scan existing turn directories to find the maximum turn number.
        Used for initial counter value when no counter file exists.
        """
        max_turn = 0
        try:
            for item in self.turns_dir.iterdir():
                if item.is_dir() and item.name.startswith("turn_"):
                    try:
                        turn_num = int(item.name.split("_")[1])
                        max_turn = max(max_turn, turn_num)
                    except (ValueError, IndexError):
                        continue
        except Exception as e:
            logger.warning(f"[TurnCounter] Error scanning turns: {e}")

        return max_turn

    def reset(self, session_id: Optional[str] = None):
        """
        Reset counter for a session (useful for testing).

        Args:
            session_id: Session to reset, or None for global counter
        """
        self.lock_file.touch(exist_ok=True)

        with open(self.lock_file, 'r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if self.counter_file.exists():
                    counters = json.loads(self.counter_file.read_text())
                else:
                    counters = {}

                key = session_id if session_id else "_global"
                if key in counters:
                    del counters[key]

                self.counter_file.write_text(json.dumps(counters, indent=2))
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


# Global singleton for convenience
_TURN_COUNTER: Optional[TurnCounter] = None


def get_turn_counter() -> TurnCounter:
    """Get the global TurnCounter instance."""
    global _TURN_COUNTER
    if _TURN_COUNTER is None:
        _TURN_COUNTER = TurnCounter()
    return _TURN_COUNTER


def get_next_turn_number(session_id: Optional[str] = None) -> int:
    """Convenience function to get next turn number."""
    return get_turn_counter().get_next_turn_number(session_id)
