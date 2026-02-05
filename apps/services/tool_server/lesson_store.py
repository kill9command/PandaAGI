"""
orchestrator/lesson_store.py

Simple JSON-based lesson storage for cross-session learning.
Implements Layer 2 reflection: storing lessons and applying them proactively.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Default storage location
LESSON_DIR = Path("panda_system_docs/lessons")
LESSON_FILE = LESSON_DIR / "lessons.jsonl"


@dataclass
class Lesson:
    """A single lesson learned from task execution."""

    timestamp: str  # ISO 8601 UTC timestamp
    role: str  # "guide", "coordinator", "context_manager", or tool name
    context: str  # What was being attempted
    lesson: str  # What was learned
    tags: List[str]  # Searchable tags (e.g., ["bom", "pricing", "reflexion"])
    confidence: float  # 0.0-1.0, how confident we are in this lesson

    # Optional fields
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    related_tools: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Lesson:
        """Create from dictionary."""
        return cls(**data)


class LessonStore:
    """
    Simple JSON-based lesson storage.

    Lessons are stored in JSONL format (one JSON object per line) for easy append operations.
    """

    def __init__(self, lesson_file: Optional[Path] = None):
        """
        Initialize lesson store.

        Args:
            lesson_file: Path to lessons file (defaults to LESSON_FILE)
        """
        self.lesson_file = lesson_file or LESSON_FILE
        self._ensure_storage_exists()

    def _ensure_storage_exists(self):
        """Create storage directory and file if they don't exist."""
        self.lesson_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.lesson_file.exists():
            self.lesson_file.touch()
            logger.info(f"Created lesson storage at {self.lesson_file}")

    def add_lesson(
        self,
        role: str,
        context: str,
        lesson: str,
        tags: List[str],
        confidence: float = 0.8,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        related_tools: Optional[List[str]] = None
    ) -> Lesson:
        """
        Add a new lesson to storage.

        Args:
            role: Which component learned this ("guide", "coordinator", etc.)
            context: What was being attempted
            lesson: What was learned
            tags: Searchable tags
            confidence: How confident we are (0.0-1.0)
            session_id: Optional session identifier
            task_id: Optional task identifier
            related_tools: Optional list of related tool names

        Returns:
            The created Lesson object
        """
        # Create lesson with current timestamp
        lesson_obj = Lesson(
            timestamp=datetime.now(timezone.utc).isoformat(),
            role=role,
            context=context,
            lesson=lesson,
            tags=tags,
            confidence=confidence,
            session_id=session_id,
            task_id=task_id,
            related_tools=related_tools
        )

        # Append to JSONL file
        with open(self.lesson_file, 'a') as f:
            f.write(json.dumps(lesson_obj.to_dict()) + '\n')

        logger.info(f"Stored lesson from {role}: {lesson[:80]}{'...' if len(lesson) > 80 else ''}")
        return lesson_obj

    def query_lessons(
        self,
        role: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_confidence: float = 0.5,
        limit: int = 10,
        related_tools: Optional[List[str]] = None
    ) -> List[Lesson]:
        """
        Query lessons from storage.

        Args:
            role: Filter by role (e.g., "coordinator")
            tags: Filter by tags (must match ANY tag)
            min_confidence: Minimum confidence threshold
            limit: Maximum number of lessons to return
            related_tools: Filter by related tools (must match ANY tool)

        Returns:
            List of matching lessons, most recent first
        """
        if not self.lesson_file.exists():
            return []

        lessons = []

        # Read all lessons from JSONL
        with open(self.lesson_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    lesson_obj = Lesson.from_dict(data)

                    # Apply filters
                    if role and lesson_obj.role != role:
                        continue

                    if lesson_obj.confidence < min_confidence:
                        continue

                    if tags:
                        # Match ANY tag
                        if not any(tag in lesson_obj.tags for tag in tags):
                            continue

                    if related_tools:
                        # Match ANY tool
                        if not lesson_obj.related_tools:
                            continue
                        if not any(tool in lesson_obj.related_tools for tool in related_tools):
                            continue

                    lessons.append(lesson_obj)

                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping malformed lesson line: {e}")
                    continue

        # Sort by timestamp descending (most recent first)
        lessons.sort(key=lambda x: x.timestamp, reverse=True)

        return lessons[:limit]

    def get_all_lessons(self) -> List[Lesson]:
        """Get all lessons, most recent first."""
        return self.query_lessons(limit=1000)

    def get_lessons_for_context(
        self,
        context_keywords: List[str],
        role: Optional[str] = None,
        limit: int = 5
    ) -> List[Lesson]:
        """
        Get lessons relevant to a specific context.

        Args:
            context_keywords: Keywords to search in context and tags
            role: Optional role filter
            limit: Maximum lessons to return

        Returns:
            Relevant lessons, scored by keyword matches
        """
        all_lessons = self.query_lessons(role=role, limit=100)

        # Score lessons by keyword relevance
        scored_lessons = []
        for lesson in all_lessons:
            score = 0
            text = f"{lesson.context} {' '.join(lesson.tags)} {lesson.lesson}".lower()

            for keyword in context_keywords:
                if keyword.lower() in text:
                    score += 1

            if score > 0:
                scored_lessons.append((score, lesson))

        # Sort by score descending
        scored_lessons.sort(key=lambda x: x[0], reverse=True)

        return [lesson for _, lesson in scored_lessons[:limit]]

    def clear_low_confidence_lessons(self, threshold: float = 0.3):
        """
        Remove lessons below a confidence threshold.

        Args:
            threshold: Confidence threshold (lessons below this are removed)

        Returns:
            Number of lessons removed
        """
        if not self.lesson_file.exists():
            return 0

        kept_lessons = []
        removed_count = 0

        # Read all lessons
        with open(self.lesson_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    lesson_obj = Lesson.from_dict(data)

                    if lesson_obj.confidence >= threshold:
                        kept_lessons.append(data)
                    else:
                        removed_count += 1

                except json.JSONDecodeError:
                    continue

        # Rewrite file with only kept lessons
        with open(self.lesson_file, 'w') as f:
            for data in kept_lessons:
                f.write(json.dumps(data) + '\n')

        logger.info(f"Removed {removed_count} low-confidence lessons (threshold: {threshold})")
        return removed_count

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about stored lessons."""
        all_lessons = self.get_all_lessons()

        if not all_lessons:
            return {
                "total_lessons": 0,
                "by_role": {},
                "avg_confidence": 0.0,
                "top_tags": []
            }

        # Count by role
        by_role = {}
        for lesson in all_lessons:
            by_role[lesson.role] = by_role.get(lesson.role, 0) + 1

        # Average confidence
        avg_confidence = sum(l.confidence for l in all_lessons) / len(all_lessons)

        # Top tags
        tag_counts = {}
        for lesson in all_lessons:
            for tag in lesson.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_lessons": len(all_lessons),
            "by_role": by_role,
            "avg_confidence": round(avg_confidence, 2),
            "top_tags": [{"tag": tag, "count": count} for tag, count in top_tags]
        }


# Global instance
_store: Optional[LessonStore] = None


def get_lesson_store() -> LessonStore:
    """Get the global lesson store instance."""
    global _store
    if _store is None:
        _store = LessonStore()
    return _store
