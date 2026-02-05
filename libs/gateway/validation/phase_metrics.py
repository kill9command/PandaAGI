"""
Phase Metrics - Telemetry and timing for pipeline phases.

Extracted from UnifiedFlow to provide:
- Clean separation of concerns
- Reusable metrics across different orchestrators
- Consistent timing and token tracking

Usage:
    metrics = PhaseMetrics()
    metrics.init_turn()

    metrics.start_phase("planner")
    # ... phase execution ...
    metrics.end_phase("planner", tokens_in=100, tokens_out=50)

    metrics.record_decision("route", "synthesis", "Query is simple")
    metrics.record_tool_call("memory.search", success=True, duration_ms=150)

    final_metrics = metrics.finalize_turn(quality_score=0.85, outcome="APPROVED")
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from apps.services.gateway.services.thinking import emit_thinking_event, ThinkingEvent
from apps.phases import PHASE_NAMES

logger = logging.getLogger(__name__)


@dataclass
class PhaseTimingRecord:
    """Timing record for a single phase."""
    phase_name: str
    start_time: float
    end_time: Optional[float] = None
    duration_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class DecisionRecord:
    """Record of a decision made during the turn."""
    decision_type: str
    value: str
    context: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ToolCallRecord:
    """Record of a tool call."""
    tool_name: str
    success: bool
    duration_ms: int = 0
    timestamp: float = field(default_factory=time.time)


class PhaseMetrics:
    """
    Metrics collector for pipeline phases.

    Tracks:
    - Phase timing (start/end/duration)
    - Token usage (input/output per phase and total)
    - Decisions made during the turn
    - Tool calls with success/failure status
    - Overall turn quality and outcome
    """

    def __init__(self):
        """Initialize the metrics collector."""
        self._turn_start: Optional[float] = None
        self._turn_end: Optional[float] = None
        self._phase_timings: Dict[str, PhaseTimingRecord] = {}
        self._decisions: List[DecisionRecord] = []
        self._tool_calls: List[ToolCallRecord] = []
        self._quality_score: float = 0.0
        self._validation_outcome: str = ""
        self._retries: int = 0

    def init_turn(self) -> None:
        """Initialize metrics for a new turn."""
        self._turn_start = time.time()
        self._turn_end = None
        self._phase_timings = {}
        self._decisions = []
        self._tool_calls = []
        self._quality_score = 0.0
        self._validation_outcome = ""
        self._retries = 0
        logger.debug("[PhaseMetrics] Initialized new turn")

    def start_phase(self, phase_name: str) -> None:
        """
        Mark the start of a phase.

        Args:
            phase_name: Name of the phase (e.g., "planner", "synthesis")
        """
        self._phase_timings[phase_name] = PhaseTimingRecord(
            phase_name=phase_name,
            start_time=time.time()
        )
        logger.debug(f"[PhaseMetrics] Started phase: {phase_name}")

    def end_phase(
        self,
        phase_name: str,
        tokens_in: int = 0,
        tokens_out: int = 0
    ) -> None:
        """
        Mark the end of a phase and record metrics.

        Args:
            phase_name: Name of the phase
            tokens_in: Input tokens used
            tokens_out: Output tokens generated
        """
        if phase_name not in self._phase_timings:
            logger.warning(f"[PhaseMetrics] Phase {phase_name} was not started")
            return

        record = self._phase_timings[phase_name]
        record.end_time = time.time()
        record.duration_ms = int((record.end_time - record.start_time) * 1000)
        record.tokens_in = tokens_in
        record.tokens_out = tokens_out

        logger.debug(
            f"[PhaseMetrics] Ended phase: {phase_name} "
            f"({record.duration_ms}ms, {tokens_in}/{tokens_out} tokens)"
        )

    def record_decision(
        self,
        decision_type: str,
        value: str,
        context: str = ""
    ) -> None:
        """
        Record a decision made during the turn.

        Args:
            decision_type: Type of decision (e.g., "route", "intent", "action")
            value: The decision value
            context: Optional context explaining the decision
        """
        self._decisions.append(DecisionRecord(
            decision_type=decision_type,
            value=value,
            context=context
        ))
        logger.debug(f"[PhaseMetrics] Recorded decision: {decision_type}={value}")

    def record_tool_call(
        self,
        tool_name: str,
        success: bool,
        duration_ms: int = 0
    ) -> None:
        """
        Record a tool call.

        Args:
            tool_name: Name of the tool called
            success: Whether the call succeeded
            duration_ms: Duration of the call in milliseconds
        """
        self._tool_calls.append(ToolCallRecord(
            tool_name=tool_name,
            success=success,
            duration_ms=duration_ms
        ))
        logger.debug(
            f"[PhaseMetrics] Recorded tool call: {tool_name} "
            f"(success={success}, {duration_ms}ms)"
        )

    def increment_retries(self) -> None:
        """Increment the retry counter."""
        self._retries += 1
        logger.debug(f"[PhaseMetrics] Retry count: {self._retries}")

    def finalize_turn(
        self,
        quality_score: float,
        validation_outcome: str
    ) -> Dict[str, Any]:
        """
        Finalize and return turn metrics.

        Args:
            quality_score: Final quality score (0.0-1.0)
            validation_outcome: Validation result (APPROVED, RETRY, FAIL, etc.)

        Returns:
            Complete metrics dictionary
        """
        self._turn_end = time.time()
        self._quality_score = quality_score
        self._validation_outcome = validation_outcome

        total_duration_ms = int((self._turn_end - (self._turn_start or self._turn_end)) * 1000)
        total_tokens_in = sum(r.tokens_in for r in self._phase_timings.values())
        total_tokens_out = sum(r.tokens_out for r in self._phase_timings.values())

        metrics = {
            "turn_start": self._turn_start,
            "turn_end": self._turn_end,
            "total_duration_ms": total_duration_ms,
            "phases": {
                name: {
                    "duration_ms": record.duration_ms,
                    "tokens_in": record.tokens_in,
                    "tokens_out": record.tokens_out
                }
                for name, record in self._phase_timings.items()
            },
            "tokens": {
                "total_in": total_tokens_in,
                "total_out": total_tokens_out
            },
            "decisions": [
                {
                    "type": d.decision_type,
                    "value": d.value,
                    "context": d.context
                }
                for d in self._decisions
            ],
            "tools_called": [
                {
                    "tool": t.tool_name,
                    "success": t.success,
                    "duration_ms": t.duration_ms
                }
                for t in self._tool_calls
            ],
            "retries": self._retries,
            "quality_score": quality_score,
            "validation_outcome": validation_outcome
        }

        logger.info(
            f"[PhaseMetrics] Turn finalized: {total_duration_ms}ms, "
            f"{total_tokens_in}/{total_tokens_out} tokens, "
            f"{len(self._phase_timings)} phases, "
            f"{len(self._tool_calls)} tool calls, "
            f"outcome={validation_outcome}"
        )

        return metrics

    def to_dict(self) -> Dict[str, Any]:
        """
        Get current metrics as a dictionary (for intermediate access).

        Returns:
            Current metrics state
        """
        return {
            "turn_start": self._turn_start,
            "phases": {
                name: {
                    "duration_ms": record.duration_ms,
                    "tokens_in": record.tokens_in,
                    "tokens_out": record.tokens_out
                }
                for name, record in self._phase_timings.items()
            },
            "tokens": {
                "total_in": sum(r.tokens_in for r in self._phase_timings.values()),
                "total_out": sum(r.tokens_out for r in self._phase_timings.values())
            },
            "decisions": [
                {"type": d.decision_type, "value": d.value, "context": d.context}
                for d in self._decisions
            ],
            "tools_called": [
                {"tool": t.tool_name, "success": t.success, "duration_ms": t.duration_ms}
                for t in self._tool_calls
            ],
            "retries": self._retries
        }


async def emit_phase_event(
    trace_id: str,
    phase: int,
    status: str,
    reasoning: str = "",
    confidence: float = None,
    details: Dict = None,
    duration_ms: int = 0
) -> None:
    """
    Emit a thinking event for UI visualization.

    Args:
        trace_id: Request trace identifier
        phase: Phase number (0-8)
        status: Phase status ("active", "completed", "error")
        reasoning: Human-readable reasoning for UI
        confidence: Confidence level (0.0-1.0), auto-computed if None
        details: Additional details for UI
        duration_ms: Phase duration in milliseconds
    """
    # Default confidence based on status if not explicitly provided
    if confidence is None:
        if status == "completed":
            confidence = 1.0
        elif status == "active":
            confidence = 0.5
        else:
            confidence = 0.0

    stage_name = f"phase_{phase}_{PHASE_NAMES.get(phase, 'unknown')}"
    logger.info(
        f"[PhaseMetrics] Emitting thinking event: "
        f"trace={trace_id}, stage={stage_name}, status={status}"
    )

    await emit_thinking_event(ThinkingEvent(
        trace_id=trace_id,
        stage=stage_name,
        status=status,
        confidence=confidence,
        duration_ms=duration_ms,
        details=details or {},
        reasoning=reasoning,
        timestamp=time.time()
    ))
