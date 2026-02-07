#!/usr/bin/env python3
"""
Test script for observability system
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.services.tool_server.observability import (
    record_tool_call,
    record_role_call,
    record_reflection_cycle,
    record_flow,
    get_collector
)


def test_tool_metrics():
    """Test tool call metrics"""
    print("Testing tool call metrics...")

    # Record some tool calls
    record_tool_call("internet.research", success=True, duration_ms=1500, tokens_out=2000)
    record_tool_call("internet.research", success=True, duration_ms=1200, tokens_out=1800)
    record_tool_call("internet.research", success=False, duration_ms=800, error="Timeout", tokens_out=0)
    record_tool_call("doc.search", success=True, duration_ms=300, tokens_out=500)

    # Get stats
    collector = get_collector()
    tool_stats = collector.get_tool_stats(hours=1)

    assert len(tool_stats) == 2, f"Expected 2 tools, got {len(tool_stats)}"

    # Find internet.research stats
    research_stats = next((s for s in tool_stats if s.tool == "internet.research"), None)
    assert research_stats is not None, "internet.research stats not found"
    assert research_stats.total_calls == 3, f"Expected 3 calls, got {research_stats.total_calls}"
    assert research_stats.successful_calls == 2, f"Expected 2 successful, got {research_stats.successful_calls}"
    assert research_stats.failed_calls == 1, f"Expected 1 failed, got {research_stats.failed_calls}"
    assert research_stats.error_rate > 0, "Expected non-zero error rate"

    print("✅ Tool metrics test passed")


def test_role_metrics():
    """Test role call metrics"""
    print("Testing role call metrics...")

    # Record some role calls
    record_role_call("guide", tokens_in=500, tokens_out=800, duration_ms=200, success=True)
    record_role_call("coordinator", tokens_in=300, tokens_out=400, duration_ms=150, success=True)
    record_role_call("context_manager", tokens_in=2000, tokens_out=600, duration_ms=350, success=True)

    # Get stats
    collector = get_collector()
    role_stats = collector.get_role_stats(hours=1)

    assert "guide" in role_stats, "guide stats not found"
    assert "coordinator" in role_stats, "coordinator stats not found"
    assert "context_manager" in role_stats, "context_manager stats not found"

    guide_stats = role_stats["guide"]
    assert guide_stats["total_calls"] == 1, f"Expected 1 call, got {guide_stats['total_calls']}"
    assert guide_stats["avg_tokens_in"] == 500, f"Expected 500 tokens_in, got {guide_stats['avg_tokens_in']}"

    print("✅ Role metrics test passed")


def test_reflection_metrics():
    """Test reflection cycle metrics"""
    print("Testing reflection cycle metrics...")

    # Record reflection cycles
    record_reflection_cycle(
        session_id="test_session_1",
        cycle_count=2,
        role_sequence=["guide", "coordinator", "context_manager", "guide"],
        role_timings={"guide": 200, "coordinator": 150, "context_manager": 350},
        context_budget_used={"guide": 800, "coordinator": 400, "context_manager": 2000},
        exceeded_cycles=False,
        exceeded_budget=False
    )

    record_reflection_cycle(
        session_id="test_session_2",
        cycle_count=3,
        role_sequence=["guide", "coordinator", "context_manager", "guide", "coordinator", "context_manager", "guide"],
        role_timings={"guide": 400, "coordinator": 300, "context_manager": 700},
        context_budget_used={"guide": 1600, "coordinator": 800, "context_manager": 4000},
        exceeded_cycles=True,
        exceeded_budget=False
    )

    # Get stats
    collector = get_collector()
    reflection_stats = collector.get_reflection_stats(hours=1)

    assert reflection_stats["total_cycles"] == 2, f"Expected 2 cycles, got {reflection_stats['total_cycles']}"
    assert reflection_stats["avg_cycle_count"] == 2.5, f"Expected avg 2.5, got {reflection_stats['avg_cycle_count']}"
    assert reflection_stats["exceeded_cycles_rate"] == 0.5, f"Expected 0.5 rate, got {reflection_stats['exceeded_cycles_rate']}"

    print("✅ Reflection metrics test passed")


def test_flow_metrics():
    """Test flow metrics"""
    print("Testing flow metrics...")

    # Record flows
    record_flow(
        session_id="test_session_1",
        total_duration_ms=2000,
        cycles=2,
        tools_called=3,
        total_tokens=5000,
        exceeded_budget=False
    )

    record_flow(
        session_id="test_session_2",
        total_duration_ms=3000,
        cycles=3,
        tools_called=5,
        total_tokens=12500,
        exceeded_budget=True
    )

    # Get stats
    collector = get_collector()
    flow_stats = collector.get_flow_stats(hours=1)

    assert flow_stats["total_requests"] == 2, f"Expected 2 requests, got {flow_stats['total_requests']}"
    assert flow_stats["avg_duration_ms"] == 2500, f"Expected avg 2500ms, got {flow_stats['avg_duration_ms']}"
    assert flow_stats["budget_exceeded_rate"] == 0.5, f"Expected 0.5 rate, got {flow_stats['budget_exceeded_rate']}"

    print("✅ Flow metrics test passed")


def test_dashboard():
    """Test complete dashboard"""
    print("Testing dashboard...")

    collector = get_collector()
    dashboard = collector.get_dashboard_data(hours=1)

    assert "tools" in dashboard, "Missing tools in dashboard"
    assert "roles" in dashboard, "Missing roles in dashboard"
    assert "reflection" in dashboard, "Missing reflection in dashboard"
    assert "flows" in dashboard, "Missing flows in dashboard"
    assert dashboard["period_hours"] == 1, f"Expected period_hours=1, got {dashboard['period_hours']}"

    print("✅ Dashboard test passed")
    print("\nDashboard data:")
    import json
    print(json.dumps(dashboard, indent=2))


if __name__ == "__main__":
    print("="*60)
    print("Testing Observability System")
    print("="*60 + "\n")

    test_tool_metrics()
    test_role_metrics()
    test_reflection_metrics()
    test_flow_metrics()
    test_dashboard()

    print("\n" + "="*60)
    print("✅ All observability tests passed!")
    print("="*60)
