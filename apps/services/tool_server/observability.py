"""
Observability System for Panda

Lightweight in-memory metrics collection with reflection-specific tracking.

Usage:
    from apps.services.tool_server.observability import record_tool_call, record_role_call, record_flow, get_collector

    # Record metrics
    record_tool_call("internet.research", success=True, duration_ms=1500, tokens_out=2000)
    record_role_call("guide", tokens_in=500, tokens_out=800, duration_ms=200, success=True)

    # Get dashboard data
    collector = get_collector()
    tool_stats = collector.get_tool_stats(hours=24)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import time


def estimate_tokens(text: str) -> int:
    """Estimate token count (4 chars ≈ 1 token)"""
    if isinstance(text, str):
        return len(text) // 4
    return 0


@dataclass
class ToolCallMetrics:
    """Metrics for a single tool call"""
    tool: str
    success: bool
    duration_ms: int
    error: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class RoleMetrics:
    """Metrics for a single LLM role call"""
    role: str  # guide, coordinator, context_manager
    tokens_in: int
    tokens_out: int
    duration_ms: int
    success: bool
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ReflectionMetrics:
    """Metrics for a complete reflection cycle"""
    session_id: str
    cycle_count: int
    role_sequence: List[str]  # ["guide", "coordinator", "context_manager", "guide"]
    role_timings: Dict[str, int]  # role -> total_ms
    context_budget_used: Dict[str, int]  # role -> tokens_used
    exceeded_cycles: bool
    exceeded_budget: bool
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class FlowMetrics:
    """End-to-end request metrics"""
    session_id: str
    total_duration_ms: int
    cycles: int
    tools_called: int
    total_tokens: int
    exceeded_budget: bool
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ToolStats:
    """Aggregated stats for a tool"""
    tool: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    avg_duration_ms: float = 0.0
    p95_duration_ms: float = 0.0
    total_tokens_out: int = 0
    error_rate: float = 0.0
    recent_errors: List[str] = field(default_factory=list)


class MetricsCollector:
    """In-memory metrics aggregator with reflection tracking"""

    def __init__(self, retention_hours: int = 24):
        self.retention_hours = retention_hours

        # Raw metrics
        self.tool_calls: List[ToolCallMetrics] = []
        self.role_calls: List[RoleMetrics] = []
        self.reflection_cycles: List[ReflectionMetrics] = []
        self.flows: List[FlowMetrics] = []

        # Aggregated stats (cached)
        self._tool_stats_cache: Dict[str, ToolStats] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl_seconds = 60  # Recompute every minute

    def record_tool_call(
        self,
        tool: str,
        success: bool,
        duration_ms: int,
        error: Optional[str] = None,
        tokens_in: int = 0,
        tokens_out: int = 0
    ):
        """Record a tool call"""
        metric = ToolCallMetrics(
            tool=tool,
            success=success,
            duration_ms=duration_ms,
            error=error,
            tokens_in=tokens_in,
            tokens_out=tokens_out
        )

        self.tool_calls.append(metric)
        self._cleanup_old_metrics()
        self._invalidate_cache()

    def record_role_call(
        self,
        role: str,
        tokens_in: int,
        tokens_out: int,
        duration_ms: int,
        success: bool
    ):
        """Record an LLM role call"""
        metric = RoleMetrics(
            role=role,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=duration_ms,
            success=success
        )

        self.role_calls.append(metric)
        self._cleanup_old_metrics()

    def record_reflection_cycle(
        self,
        session_id: str,
        cycle_count: int,
        role_sequence: List[str],
        role_timings: Dict[str, int],
        context_budget_used: Dict[str, int],
        exceeded_cycles: bool,
        exceeded_budget: bool
    ):
        """Record complete reflection cycle"""
        metric = ReflectionMetrics(
            session_id=session_id,
            cycle_count=cycle_count,
            role_sequence=role_sequence,
            role_timings=role_timings,
            context_budget_used=context_budget_used,
            exceeded_cycles=exceeded_cycles,
            exceeded_budget=exceeded_budget
        )

        self.reflection_cycles.append(metric)
        self._cleanup_old_metrics()

    def record_flow(
        self,
        session_id: str,
        total_duration_ms: int,
        cycles: int,
        tools_called: int,
        total_tokens: int,
        exceeded_budget: bool
    ):
        """Record end-to-end flow"""
        metric = FlowMetrics(
            session_id=session_id,
            total_duration_ms=total_duration_ms,
            cycles=cycles,
            tools_called=tools_called,
            total_tokens=total_tokens,
            exceeded_budget=exceeded_budget
        )

        self.flows.append(metric)
        self._cleanup_old_metrics()

    def get_tool_stats(self, hours: int = 24) -> List[ToolStats]:
        """Get aggregated tool statistics"""
        # Check cache
        if self._is_cache_valid():
            return list(self._tool_stats_cache.values())

        # Recompute
        cutoff = datetime.now() - timedelta(hours=hours)
        recent_calls = [c for c in self.tool_calls if c.timestamp >= cutoff]

        # Group by tool
        by_tool = defaultdict(list)
        for call in recent_calls:
            by_tool[call.tool].append(call)

        # Compute stats
        stats = {}
        for tool, calls in by_tool.items():
            successful = [c for c in calls if c.success]
            failed = [c for c in calls if not c.success]

            durations = [c.duration_ms for c in calls]
            durations.sort()

            p95_idx = int(len(durations) * 0.95)
            p95 = durations[p95_idx] if durations else 0

            recent_errors = [c.error for c in failed[-5:] if c.error]  # Last 5 errors

            stats[tool] = ToolStats(
                tool=tool,
                total_calls=len(calls),
                successful_calls=len(successful),
                failed_calls=len(failed),
                avg_duration_ms=sum(durations) / len(durations) if durations else 0,
                p95_duration_ms=p95,
                total_tokens_out=sum(c.tokens_out for c in calls),
                error_rate=len(failed) / len(calls) if calls else 0,
                recent_errors=recent_errors
            )

        self._tool_stats_cache = stats
        self._cache_timestamp = datetime.now()

        return list(stats.values())

    def get_role_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get role-level statistics"""
        cutoff = datetime.now() - timedelta(hours=hours)
        recent_calls = [c for c in self.role_calls if c.timestamp >= cutoff]

        by_role = defaultdict(list)
        for call in recent_calls:
            by_role[call.role].append(call)

        stats = {}
        for role, calls in by_role.items():
            stats[role] = {
                "total_calls": len(calls),
                "avg_tokens_in": sum(c.tokens_in for c in calls) / len(calls) if calls else 0,
                "avg_tokens_out": sum(c.tokens_out for c in calls) / len(calls) if calls else 0,
                "avg_duration_ms": sum(c.duration_ms for c in calls) / len(calls) if calls else 0,
                "total_tokens": sum(c.tokens_in + c.tokens_out for c in calls)
            }

        return stats

    def get_reflection_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get reflection cycle statistics"""
        cutoff = datetime.now() - timedelta(hours=hours)
        recent_cycles = [c for c in self.reflection_cycles if c.timestamp >= cutoff]

        if not recent_cycles:
            return {}

        return {
            "total_cycles": len(recent_cycles),
            "avg_cycle_count": sum(c.cycle_count for c in recent_cycles) / len(recent_cycles),
            "max_cycle_count": max(c.cycle_count for c in recent_cycles),
            "exceeded_cycles_rate": sum(1 for c in recent_cycles if c.exceeded_cycles) / len(recent_cycles),
            "exceeded_budget_rate": sum(1 for c in recent_cycles if c.exceeded_budget) / len(recent_cycles),
            "avg_role_sequence_length": sum(len(c.role_sequence) for c in recent_cycles) / len(recent_cycles)
        }

    def get_flow_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get flow-level statistics"""
        cutoff = datetime.now() - timedelta(hours=hours)
        recent_flows = [f for f in self.flows if f.timestamp >= cutoff]

        if not recent_flows:
            return {}

        return {
            "total_requests": len(recent_flows),
            "avg_duration_ms": sum(f.total_duration_ms for f in recent_flows) / len(recent_flows),
            "avg_cycles": sum(f.cycles for f in recent_flows) / len(recent_flows),
            "avg_tools_per_request": sum(f.tools_called for f in recent_flows) / len(recent_flows),
            "budget_exceeded_rate": sum(1 for f in recent_flows if f.exceeded_budget) / len(recent_flows)
        }

    def get_dashboard_data(self, hours: int = 24) -> Dict[str, Any]:
        """Get complete dashboard data"""
        tool_stats = self.get_tool_stats(hours)
        role_stats = self.get_role_stats(hours)
        reflection_stats = self.get_reflection_stats(hours)
        flow_stats = self.get_flow_stats(hours)

        # Sort tools by error rate (worst first)
        tool_stats.sort(key=lambda s: s.error_rate, reverse=True)

        return {
            "period_hours": hours,
            "tools": [
                {
                    "name": s.tool,
                    "total_calls": s.total_calls,
                    "success_rate": f"{(1 - s.error_rate) * 100:.1f}%",
                    "avg_duration_ms": int(s.avg_duration_ms),
                    "p95_duration_ms": int(s.p95_duration_ms),
                    "total_tokens_out": s.total_tokens_out,
                    "recent_errors": s.recent_errors
                }
                for s in tool_stats
            ],
            "roles": role_stats,
            "reflection": reflection_stats,
            "flows": flow_stats
        }

    def _cleanup_old_metrics(self):
        """Remove metrics older than retention window"""
        cutoff = datetime.now() - timedelta(hours=self.retention_hours)

        self.tool_calls = [c for c in self.tool_calls if c.timestamp >= cutoff]
        self.role_calls = [c for c in self.role_calls if c.timestamp >= cutoff]
        self.reflection_cycles = [c for c in self.reflection_cycles if c.timestamp >= cutoff]
        self.flows = [f for f in self.flows if f.timestamp >= cutoff]

    def _invalidate_cache(self):
        """Invalidate aggregated stats cache"""
        self._cache_timestamp = None

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid"""
        if not self._cache_timestamp:
            return False

        age_seconds = (datetime.now() - self._cache_timestamp).total_seconds()
        return age_seconds < self._cache_ttl_seconds


# Global collector instance
_collector = MetricsCollector()


def get_collector() -> MetricsCollector:
    """Get global metrics collector"""
    return _collector


# Convenience functions
def record_tool_call(
    tool: str,
    success: bool,
    duration_ms: int,
    error: Optional[str] = None,
    tokens_in: int = 0,
    tokens_out: int = 0
):
    """Record tool call metric"""
    _collector.record_tool_call(tool, success, duration_ms, error, tokens_in, tokens_out)


def record_role_call(role: str, tokens_in: int, tokens_out: int, duration_ms: int, success: bool):
    """Record role call metric"""
    _collector.record_role_call(role, tokens_in, tokens_out, duration_ms, success)


def record_reflection_cycle(
    session_id: str,
    cycle_count: int,
    role_sequence: List[str],
    role_timings: Dict[str, int],
    context_budget_used: Dict[str, int],
    exceeded_cycles: bool,
    exceeded_budget: bool
):
    """Record reflection cycle metric"""
    _collector.record_reflection_cycle(
        session_id,
        cycle_count,
        role_sequence,
        role_timings,
        context_budget_used,
        exceeded_cycles,
        exceeded_budget
    )


def record_flow(
    session_id: str,
    total_duration_ms: int,
    cycles: int,
    tools_called: int,
    total_tokens: int,
    exceeded_budget: bool
):
    """Record flow metric"""
    _collector.record_flow(session_id, total_duration_ms, cycles, tools_called, total_tokens, exceeded_budget)
