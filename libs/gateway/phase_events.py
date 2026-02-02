"""
Phase event emission for V4 Flow progress display.

This module provides utilities for emitting progress events during V4 flow execution,
allowing the chat UI to display what the system is doing in real-time.

Usage:
    async with phase_progress(trace_id, 3, emit_func) as progress:
        # ... phase logic ...
        await progress.update(message="Found 5 tools to execute")
"""
import time
import logging
from typing import Optional, Dict, Any, Callable
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# Map V4 phases to UI stage names and descriptions
# UI stages: query_received, guide_analyzing, coordinator_planning,
#            orchestrator_executing, guide_synthesizing, response_complete
PHASE_TO_STAGE = {
    0: ("query_received", "Setting up turn"),
    1: ("guide_analyzing", "Gathering context"),
    2: ("guide_analyzing", "Analyzing query"),
    3: ("coordinator_planning", "Planning approach"),
    4: ("orchestrator_executing", "Executing tools"),
    5: ("orchestrator_executing", "Extracting evidence"),
    6: ("guide_synthesizing", "Generating response"),
    7: ("guide_synthesizing", "Finalizing"),
    8: ("guide_synthesizing", "Updating memory"),
    9: ("response_complete", "Completing turn"),
}

# Human-readable phase names for logging
PHASE_NAMES = {
    0: "Turn Setup",
    1: "Context Gathering",
    2: "Meta Reflection",
    3: "Strategic Planning",
    4: "Coordinator",
    5: "Claim Extraction",
    6: "Synthesis",
    7: "Finalization",
    8: "Archivist",
    9: "Turn Summary",
}


class ProgressUpdater:
    """Helper class for updating progress within a phase."""

    def __init__(
        self,
        trace_id: str,
        phase_num: int,
        stage: str,
        emit_func: Callable,
        start_time: float,
        state: Dict[str, Any]
    ):
        self.trace_id = trace_id
        self.phase_num = phase_num
        self.stage = stage
        self.emit_func = emit_func
        self.start_time = start_time
        self.state = state

    async def update(self, message: str = None, details: Dict = None, confidence: float = None):
        """Emit a progress update event."""
        if message:
            self.state["message"] = message
        if details:
            self.state["details"].update(details)
        if confidence is not None:
            self.state["confidence"] = confidence

        try:
            await self.emit_func({
                "trace_id": self.trace_id,
                "stage": self.stage,
                "status": "active",
                "confidence": self.state.get("confidence", 0.0),
                "duration_ms": int((time.time() - self.start_time) * 1000),
                "details": self.state["details"],
                "reasoning": self.state["message"],
                "timestamp": time.time(),
                "message": self.state["message"],
                "phase": self.phase_num,
                "phase_name": PHASE_NAMES.get(self.phase_num, "Unknown"),
            })
        except Exception as e:
            logger.warning(f"[PhaseEvents] Failed to emit update: {e}")


@asynccontextmanager
async def phase_progress(
    trace_id: str,
    phase_num: int,
    emit_func: Callable,
    details: Optional[Dict[str, Any]] = None
):
    """
    Context manager for emitting phase start/complete events.

    Automatically emits:
    - Start event when entering the context
    - Progress events via the yielded updater
    - Complete event when exiting (success or error)

    Args:
        trace_id: The trace ID for this request
        phase_num: The phase number (0-9)
        emit_func: Async function to emit events
        details: Optional initial details dict

    Yields:
        ProgressUpdater: Object with .update() method for progress updates

    Example:
        async with phase_progress(trace_id, 3, emit_func) as progress:
            await progress.update(message="Loading tools")
            tools = load_tools()
            await progress.update(message=f"Found {len(tools)} tools")
    """
    stage, description = PHASE_TO_STAGE.get(phase_num, ("unknown", "Processing"))
    phase_name = PHASE_NAMES.get(phase_num, "Unknown")
    start_time = time.time()

    # Initialize state
    state = {
        "message": description,
        "details": details.copy() if details else {},
        "confidence": 0.0,
    }

    # Emit start event
    try:
        await emit_func({
            "trace_id": trace_id,
            "stage": stage,
            "status": "active",
            "confidence": 0.0,
            "duration_ms": 0,
            "details": state["details"],
            "reasoning": f"{description}...",
            "timestamp": time.time(),
            "message": description,
            "phase": phase_num,
            "phase_name": phase_name,
        })
        logger.debug(f"[PhaseEvents] Phase {phase_num} ({phase_name}) started")
    except Exception as e:
        logger.warning(f"[PhaseEvents] Failed to emit phase start: {e}")

    # Create updater
    updater = ProgressUpdater(
        trace_id=trace_id,
        phase_num=phase_num,
        stage=stage,
        emit_func=emit_func,
        start_time=start_time,
        state=state
    )

    try:
        yield updater

        # Emit success event
        duration_ms = int((time.time() - start_time) * 1000)
        final_confidence = state.get("confidence", 0.9)

        try:
            await emit_func({
                "trace_id": trace_id,
                "stage": stage,
                "status": "completed",
                "confidence": final_confidence,
                "duration_ms": duration_ms,
                "details": state["details"],
                "reasoning": f"{state['message']} ({duration_ms}ms)",
                "timestamp": time.time(),
                "message": f"{description}",
                "phase": phase_num,
                "phase_name": phase_name,
            })
            logger.debug(f"[PhaseEvents] Phase {phase_num} ({phase_name}) completed in {duration_ms}ms")
        except Exception as e:
            logger.warning(f"[PhaseEvents] Failed to emit phase complete: {e}")

    except Exception as e:
        # Emit error event
        duration_ms = int((time.time() - start_time) * 1000)

        try:
            await emit_func({
                "trace_id": trace_id,
                "stage": stage,
                "status": "error",
                "confidence": 0.0,
                "duration_ms": duration_ms,
                "details": {"error": str(e)[:200]},
                "reasoning": f"{phase_name} failed: {str(e)[:100]}",
                "timestamp": time.time(),
                "message": f"{description} failed",
                "phase": phase_num,
                "phase_name": phase_name,
            })
            logger.debug(f"[PhaseEvents] Phase {phase_num} ({phase_name}) failed: {e}")
        except Exception as emit_error:
            logger.warning(f"[PhaseEvents] Failed to emit phase error: {emit_error}")

        # Re-raise the original exception
        raise


async def emit_tool_progress(
    trace_id: str,
    emit_func: Callable,
    tool_name: str,
    status: str,  # "starting", "running", "complete", "error"
    details: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None
):
    """
    Emit a tool-specific progress event during Phase 4.

    Args:
        trace_id: The trace ID for this request
        emit_func: Async function to emit events
        tool_name: Name of the tool being executed
        status: Current status of the tool
        details: Optional details about the tool execution
        message: Optional custom message
    """
    status_messages = {
        "starting": f"Starting: {tool_name}",
        "running": f"Running: {tool_name}",
        "complete": f"Complete: {tool_name}",
        "error": f"Failed: {tool_name}",
    }

    try:
        await emit_func({
            "trace_id": trace_id,
            "stage": "orchestrator_executing",
            "status": "active" if status != "error" else "error",
            "confidence": 0.5 if status == "running" else (0.9 if status == "complete" else 0.0),
            "duration_ms": 0,
            "details": {
                "tool_name": tool_name,
                "tool_status": status,
                **(details or {})
            },
            "reasoning": message or status_messages.get(status, f"{tool_name}: {status}"),
            "timestamp": time.time(),
            "message": message or status_messages.get(status, f"{tool_name}"),
            "phase": 4,
            "phase_name": "Coordinator",
            "is_tool_event": True,
        })
    except Exception as e:
        logger.warning(f"[PhaseEvents] Failed to emit tool progress: {e}")
