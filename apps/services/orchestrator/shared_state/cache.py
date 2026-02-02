"""
A simple cache for tool outputs, keyed by normalized subtasks.
"""

import json
import time
from typing import Any, Dict, Optional


class ToolCache:
    def __init__(self, max_size: int = 100, ttl: int = 3600):
        self.max_size = max_size
        self.ttl = ttl
        self.cache: Dict[str, Any] = {}
        self.timestamps: Dict[str, float] = {}

    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            if time.time() - self.timestamps[key] < self.ttl:
                return self.cache[key]
            else:
                self.delete(key)
        return None

    def set(self, key: str, value: Any) -> None:
        if len(self.cache) >= self.max_size:
            self._prune()
        self.cache[key] = value
        self.timestamps[key] = time.time()

    def delete(self, key: str) -> None:
        if key in self.cache:
            del self.cache[key]
            del self.timestamps[key]

    def _prune(self) -> None:
        if not self.cache:
            return
        oldest_key = min(self.timestamps, key=self.timestamps.get)
        self.delete(oldest_key)

    @staticmethod
    def normalize_subtask(subtask: Dict[str, Any]) -> str:
        """Create a normalized, sorted string from a subtask dictionary."""
        return json.dumps(subtask, sort_keys=True)
