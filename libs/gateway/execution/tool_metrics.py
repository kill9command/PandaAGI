"""
Tool Execution Metrics Tracking

Provides simple metrics tracking for tool executions, enabling observability
into tool usage patterns, success rates, and performance.

Architecture Reference:
    architecture/Implementation/KNOWLEDGE_GRAPH_AND_UI_PLAN.md#Part 4: Coordinator Verification
    Task 4.1: Add Tool Execution Metrics

Usage:
    from libs.gateway.execution.tool_metrics import record_tool_execution, get_tool_metrics

    # Record an execution
    record_tool_execution(
        tool_name="internet.research",
        status="success",
        duration_ms=1500,
        turn_number=42
    )

    # Get metrics
    metrics = get_tool_metrics()
    stats = metrics.get_stats("internet.research")
    recent = metrics.get_recent(limit=20)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import defaultdict
import time
import threading
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolExecution:
    """Record of a single tool execution."""

    tool_name: str
    status: str  # "success" or "error"
    duration_ms: int
    turn_number: int
    timestamp: float
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses."""
        return {
            "tool_name": self.tool_name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "turn_number": self.turn_number,
            "timestamp": self.timestamp,
            "error": self.error,
        }


class ToolMetrics:
    """
    Track tool execution metrics for observability.

    Thread-safe singleton that records tool executions and provides
    aggregated statistics for monitoring and debugging.

    Features:
        - Record success/error status with duration
        - Get per-tool statistics (count, success rate, avg duration)
        - Get recent executions for debugging
        - Thread-safe for concurrent access
    """

    # Maximum executions to keep in memory
    MAX_EXECUTIONS = 1000

    def __init__(self):
        self._executions: List[ToolExecution] = []
        self._lock = threading.Lock()
        logger.info("[ToolMetrics] Initialized")

    def record(
        self,
        tool_name: str,
        status: str,
        duration_ms: int,
        turn_number: int,
        error: Optional[str] = None,
    ) -> None:
        """
        Record a tool execution.

        Args:
            tool_name: Name of the tool executed (e.g., "internet.research")
            status: Execution status - "success" or "error"
            duration_ms: Execution duration in milliseconds
            turn_number: Turn number when execution occurred
            error: Optional error message if status is "error"
        """
        execution = ToolExecution(
            tool_name=tool_name,
            status=status,
            duration_ms=duration_ms,
            turn_number=turn_number,
            timestamp=time.time(),
            error=error,
        )

        with self._lock:
            self._executions.append(execution)

            # Prune old executions if we exceed max
            if len(self._executions) > self.MAX_EXECUTIONS:
                # Keep most recent half
                self._executions = self._executions[-(self.MAX_EXECUTIONS // 2) :]

        logger.debug(
            f"[ToolMetrics] Recorded: {tool_name} {status} "
            f"({duration_ms}ms, turn {turn_number})"
        )

    def get_stats(self, tool_name: Optional[str] = None) -> Dict:
        """
        Get execution statistics.

        Args:
            tool_name: Optional tool name to filter by. If None, returns
                      stats for all tools.

        Returns:
            Dictionary with statistics:
                - If tool_name provided: {count, success_count, error_count,
                  success_rate, avg_duration_ms, min_duration_ms, max_duration_ms}
                - If no tool_name: {tools: {tool_name: stats_dict, ...}, totals: {...}}
        """
        with self._lock:
            if tool_name:
                return self._compute_stats_for_tool(tool_name)
            else:
                return self._compute_all_stats()

    def _compute_stats_for_tool(self, tool_name: str) -> Dict:
        """Compute stats for a single tool (called with lock held)."""
        tool_executions = [e for e in self._executions if e.tool_name == tool_name]

        if not tool_executions:
            return {
                "tool_name": tool_name,
                "count": 0,
                "success_count": 0,
                "error_count": 0,
                "success_rate": 0.0,
                "avg_duration_ms": 0,
                "min_duration_ms": 0,
                "max_duration_ms": 0,
            }

        success_count = sum(1 for e in tool_executions if e.status == "success")
        error_count = sum(1 for e in tool_executions if e.status == "error")
        durations = [e.duration_ms for e in tool_executions]

        return {
            "tool_name": tool_name,
            "count": len(tool_executions),
            "success_count": success_count,
            "error_count": error_count,
            "success_rate": success_count / len(tool_executions) if tool_executions else 0.0,
            "avg_duration_ms": int(sum(durations) / len(durations)) if durations else 0,
            "min_duration_ms": min(durations) if durations else 0,
            "max_duration_ms": max(durations) if durations else 0,
        }

    def _compute_all_stats(self) -> Dict:
        """Compute stats for all tools (called with lock held)."""
        # Group by tool name
        by_tool: Dict[str, List[ToolExecution]] = defaultdict(list)
        for execution in self._executions:
            by_tool[execution.tool_name].append(execution)

        # Compute per-tool stats
        tools = {}
        total_count = 0
        total_success = 0
        total_error = 0
        all_durations = []

        for tool_name in sorted(by_tool.keys()):
            stats = self._compute_stats_for_tool(tool_name)
            tools[tool_name] = stats
            total_count += stats["count"]
            total_success += stats["success_count"]
            total_error += stats["error_count"]
            all_durations.extend(e.duration_ms for e in by_tool[tool_name])

        return {
            "tools": tools,
            "totals": {
                "count": total_count,
                "success_count": total_success,
                "error_count": total_error,
                "success_rate": total_success / total_count if total_count else 0.0,
                "avg_duration_ms": int(sum(all_durations) / len(all_durations)) if all_durations else 0,
                "unique_tools": len(tools),
            },
        }

    def get_recent(self, limit: int = 100) -> List[ToolExecution]:
        """
        Get recent executions.

        Args:
            limit: Maximum number of executions to return (default 100)

        Returns:
            List of recent ToolExecution objects, most recent first
        """
        with self._lock:
            # Return most recent first
            return list(reversed(self._executions[-limit:]))

    def get_recent_for_tool(self, tool_name: str, limit: int = 20) -> List[ToolExecution]:
        """
        Get recent executions for a specific tool.

        Args:
            tool_name: Tool to filter by
            limit: Maximum number of executions to return

        Returns:
            List of recent ToolExecution objects for this tool, most recent first
        """
        with self._lock:
            tool_executions = [e for e in self._executions if e.tool_name == tool_name]
            return list(reversed(tool_executions[-limit:]))

    def clear(self) -> None:
        """Clear all recorded executions (useful for testing)."""
        with self._lock:
            self._executions.clear()
        logger.info("[ToolMetrics] Cleared all executions")


# =============================================================================
# Singleton Instance
# =============================================================================

_metrics: Optional[ToolMetrics] = None
_metrics_lock = threading.Lock()


def get_tool_metrics() -> ToolMetrics:
    """
    Get the singleton ToolMetrics instance.

    Returns:
        The global ToolMetrics instance
    """
    global _metrics
    if _metrics is None:
        with _metrics_lock:
            if _metrics is None:
                _metrics = ToolMetrics()
    return _metrics


def record_tool_execution(
    tool_name: str,
    status: str,
    duration_ms: int,
    turn_number: int,
    error: Optional[str] = None,
) -> None:
    """
    Convenience function to record a tool execution.

    Args:
        tool_name: Name of the tool executed
        status: "success" or "error"
        duration_ms: Execution duration in milliseconds
        turn_number: Turn number when execution occurred
        error: Optional error message if status is "error"
    """
    get_tool_metrics().record(
        tool_name=tool_name,
        status=status,
        duration_ms=duration_ms,
        turn_number=turn_number,
        error=error,
    )


# =============================================================================
# Reset (for testing)
# =============================================================================


def reset_tool_metrics() -> None:
    """Reset the singleton (useful for testing)."""
    global _metrics
    with _metrics_lock:
        _metrics = None
