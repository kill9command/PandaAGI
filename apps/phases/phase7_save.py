"""Phase 7: Save - Persist turn data.

Architecture Reference:
    architecture/main-system-patterns/phase8-save.md

Role: None (procedural, no LLM)

Question: "What do we preserve for future turns?"

This is a purely procedural phase that persists all turn artifacts
and generates observability data. Unlike other phases, no LLM is
required - this is deterministic file I/O and database operations.

Key Design Principle: Save full documents unsummarized. Summarization
happens at retrieval time (Phase 2), not save time. This preserves
maximum fidelity for context-appropriate summarization later.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from libs.core.config import get_settings
from libs.core.models import ActionNeeded
from libs.core.exceptions import PhaseError, InterventionRequired
from libs.document_io.context_manager import ContextManager
from libs.document_io.turn_manager import TurnManager


class Save:
    """
    Phase 7: Persist turn data.

    No LLM - purely procedural.

    Tasks:
    1. Finalize context.md
    2. Write metadata.json
    3. Write metrics.json
    4. Update turn index (TurnIndexDB)
    5. Update research index (if research was done)
    6. Log to transcript
    """

    PHASE_NUMBER = 7
    PHASE_NAME = "save"

    def __init__(self, mode: str = "chat"):
        """Initialize Save phase."""
        self.mode = mode
        self.settings = get_settings()

    async def execute(
        self,
        context: ContextManager,
        turn_manager: TurnManager,
        turn_number: int,
        topic: Optional[str] = None,
        action_needed: Optional[str] = None,
        quality: Optional[float] = None,
        phase_timings: Optional[dict[str, Any]] = None,
        tools_used: Optional[list[str]] = None,
        claims_count: int = 0,
    ) -> None:
        """
        Persist turn data.

        Args:
            context: Context manager for this turn
            turn_manager: Turn manager for metadata updates
            turn_number: Turn number to finalize
            topic: Inferred topic (from Phase 3)
            action_needed: Action classification (from Phase 0)
            quality: Quality score (from Phase 7)
            phase_timings: Timing data for each phase
            tools_used: List of tools that were called
            claims_count: Number of claims extracted
        """
        turn_dir = context.turn_dir

        # Step 1: context.md is already saved by ContextManager
        # Just verify it exists
        if not context.context_path.exists():
            raise InterventionRequired(
                component=f"Phase {self.PHASE_NUMBER}: {self.PHASE_NAME}",
                error="context.md not found",
                context={"turn_dir": str(turn_dir)},
            )

        # Step 2: Write/update metadata.json
        self._write_metadata(
            turn_dir=turn_dir,
            turn_number=turn_number,
            session_id=turn_manager.session_id,
            topic=topic,
            action_needed=action_needed,
            quality=quality,
            tools_used=tools_used or [],
            claims_count=claims_count,
        )

        # Step 3: Write metrics.json (observability)
        self._write_metrics(
            turn_dir=turn_dir,
            turn_number=turn_number,
            session_id=turn_manager.session_id,
            phase_timings=phase_timings or {},
            quality=quality,
            tools_used=tools_used or [],
            claims_count=claims_count,
        )

        # Step 4: Finalize turn in TurnManager (updates metadata)
        turn_manager.finalize_turn(
            turn_number=turn_number,
            topic=topic,
            action_needed=action_needed,
            quality=quality,
        )

        # Step 5: Log to transcript
        self._log_transcript(
            turn_number=turn_number,
            session_id=turn_manager.session_id,
            context=context,
        )

        # Future: Update turn index, research index, calibration DB

    def _write_metadata(
        self,
        turn_dir: Path,
        turn_number: int,
        session_id: str,
        topic: Optional[str],
        action_needed: Optional[str],
        quality: Optional[float],
        tools_used: list[str],
        claims_count: int,
    ) -> None:
        """Write turn metadata.json."""
        metadata = {
            "turn_number": turn_number,
            "session_id": session_id,
            "timestamp": int(datetime.now().timestamp()),
            "topic": topic,
            "action_needed": action_needed,
            "tools_used": tools_used,
            "claims_count": claims_count,
            "quality_score": quality,
            "content_type": "commerce" if "internet.research" in tools_used else "general",
            "user_feedback_status": "neutral",  # Default until next turn
            "keywords": self._extract_keywords(topic) if topic else [],
        }

        metadata_path = turn_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

    def _write_metrics(
        self,
        turn_dir: Path,
        turn_number: int,
        session_id: str,
        phase_timings: dict[str, Any],
        quality: Optional[float],
        tools_used: list[str],
        claims_count: int,
    ) -> None:
        """Write observability metrics.json."""
        # Build phase timing list
        phases_list = []
        total_duration = 0
        total_tokens = 0

        for phase_num in range(7):
            phase_key = str(phase_num)
            if phase_key in phase_timings:
                timing = phase_timings[phase_key]
                phases_list.append({
                    "phase": self._get_phase_name(phase_num),
                    "phase_number": phase_num,
                    "model_used": timing.get("model", "MIND"),
                    "duration_ms": timing.get("duration_ms", 0),
                    "tokens_in": timing.get("tokens_in", 0),
                    "tokens_out": timing.get("tokens_out", 0),
                })
                total_duration += timing.get("duration_ms", 0)
                total_tokens += timing.get("tokens_in", 0) + timing.get("tokens_out", 0)

        # Find slowest phase
        slowest_phase = None
        slowest_pct = 0
        if phases_list and total_duration > 0:
            slowest = max(phases_list, key=lambda p: p["duration_ms"])
            slowest_phase = slowest["phase"]
            slowest_pct = (slowest["duration_ms"] / total_duration) * 100

        metrics = {
            "turn_number": turn_number,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "timing": {
                "total_duration_ms": total_duration,
                "total_tokens": total_tokens,
                "phases": phases_list,
                "tokens_by_model": self._aggregate_tokens_by_model(phases_list),
                "slowest_phase": slowest_phase,
                "slowest_phase_pct": round(slowest_pct, 1),
            },
            "decisions": phase_timings.get("decisions", []),
            "tools": [
                {"tool": tool, "duration_ms": 0, "success": True, "claims_extracted": 0}
                for tool in tools_used
            ],
            "quality": {
                "validation_result": "APPROVE",  # From Phase 6
                "confidence": quality or 0.0,
                "claims_count": claims_count,
            },
            "calibration_predictions": [],  # For future ECE calculation
        }

        metrics_path = turn_dir / "metrics.json"
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)

    def _log_transcript(
        self,
        turn_number: int,
        session_id: str,
        context: ContextManager,
    ) -> None:
        """Log turn to daily transcript file."""
        transcripts_dir = self.settings.panda_system_docs / "transcripts"
        transcripts_dir.mkdir(parents=True, exist_ok=True)

        # Daily transcript file
        today = datetime.now().strftime("%Y%m%d")
        transcript_path = transcripts_dir / f"{today}.jsonl"

        # Build transcript entry
        entry = {
            "timestamp": datetime.now().isoformat(),
            "turn_number": turn_number,
            "session_id": session_id,
            "query": context.get_original_query(),
            "turn_dir": str(context.turn_dir),
        }

        # Append to transcript
        with open(transcript_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _get_phase_name(self, phase_num: int) -> str:
        """Get phase name from number."""
        names = {
            0: "query_analyzer",
            1: "reflection",
            2: "context_gatherer",
            3: "planner",
            4: "coordinator",
            5: "synthesis",
            6: "validation",
        }
        return names.get(phase_num, f"phase_{phase_num}")

    def _aggregate_tokens_by_model(self, phases: list[dict]) -> dict[str, int]:
        """Aggregate tokens by model."""
        by_model: dict[str, int] = {}
        for phase in phases:
            model = phase.get("model_used", "MIND")
            tokens = phase.get("tokens_in", 0) + phase.get("tokens_out", 0)
            by_model[model] = by_model.get(model, 0) + tokens
        return by_model

    def _extract_keywords(self, topic: str) -> list[str]:
        """Extract keywords from topic string."""
        if not topic:
            return []

        # Simple keyword extraction - split on spaces and filter
        words = topic.lower().split()
        stopwords = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "is", "are"}
        keywords = [w for w in words if w not in stopwords and len(w) > 2]
        return keywords[:10]  # Limit to 10


# Factory function for convenience
def create_save(mode: str = "chat") -> Save:
    """Create a Save instance."""
    return Save(mode=mode)
