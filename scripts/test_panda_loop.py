#!/usr/bin/env python3
"""
Test script for Panda Loop - Multi-Task Autonomous Execution.

Tests:
1. PandaLoop class in isolation with mock UnifiedFlow
2. Task selection with dependencies
3. Task status transitions
4. Integration with actual pipeline (optional, requires running services)

Usage:
    python scripts/test_panda_loop.py              # Run all tests
    python scripts/test_panda_loop.py --unit       # Unit tests only
    python scripts/test_panda_loop.py --integration # Integration tests (requires services)
"""

import asyncio
import sys
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from libs.gateway.util.panda_loop import PandaLoop, LoopResult, TaskResult, format_loop_summary


# =============================================================================
# Mock Classes for Unit Testing
# =============================================================================

@dataclass
class MockHandleResult:
    """Mock result from handle_request."""
    response: str
    needs_clarification: bool = False
    needs_retry: bool = False
    failure_reason: Optional[str] = None


class MockUnifiedFlow:
    """Mock UnifiedFlow for testing PandaLoop in isolation."""

    def __init__(self, task_outcomes: Dict[str, str] = None):
        """
        Initialize mock.

        Args:
            task_outcomes: Dict mapping task IDs to outcomes ("pass", "fail", "clarify")
                          Default is all tasks pass.
        """
        self.task_outcomes = task_outcomes or {}
        self.call_log = []  # Track calls for verification

    async def handle_request(
        self,
        user_query: str,
        session_id: str,
        mode: str,
        turn_number: int = None,
        trace_id: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Mock handle_request that returns predefined outcomes."""

        # Extract task ID from query
        task_id = None
        if "Task ID |" in user_query:
            # Parse task ID from the table
            for line in user_query.split("\n"):
                if "| Task ID |" in line:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        task_id = parts[2].strip()
                        break

        # Log the call
        self.call_log.append({
            "task_id": task_id,
            "turn_number": turn_number,
            "query_preview": user_query[:100],
        })

        # Determine outcome
        outcome = self.task_outcomes.get(task_id, "pass")

        if outcome == "pass":
            return {
                "response": f"Successfully completed task {task_id}. Used standard patterns.",
                "needs_clarification": False,
                "needs_retry": False,
            }
        elif outcome == "fail":
            return {
                "response": f"Failed to complete task {task_id}.",
                "needs_clarification": False,
                "needs_retry": True,
                "failure_reason": f"Validation failed for {task_id}",
            }
        elif outcome == "clarify":
            return {
                "response": f"Need clarification for task {task_id}.",
                "needs_clarification": True,
                "needs_retry": False,
            }
        else:
            return {
                "response": f"Unknown outcome for {task_id}",
                "needs_clarification": False,
                "needs_retry": False,
            }


# =============================================================================
# Unit Tests
# =============================================================================

async def test_basic_loop():
    """Test basic loop execution with all tasks passing."""
    print("\n" + "=" * 60)
    print("TEST: Basic Loop Execution")
    print("=" * 60)

    tasks = [
        {
            "id": "TASK-001",
            "title": "Create user model",
            "description": "Add User model with fields",
            "acceptance_criteria": ["Model exists", "Fields defined"],
            "priority": 1,
            "status": "pending",
            "depends_on": [],
        },
        {
            "id": "TASK-002",
            "title": "Add authentication routes",
            "description": "Create login and logout endpoints",
            "acceptance_criteria": ["Login works", "Logout works"],
            "priority": 2,
            "status": "pending",
            "depends_on": [],
        },
        {
            "id": "TASK-003",
            "title": "Add session middleware",
            "description": "Session validation middleware",
            "acceptance_criteria": ["Sessions validated"],
            "priority": 3,
            "status": "pending",
            "depends_on": ["TASK-001"],
        },
    ]

    mock_flow = MockUnifiedFlow()

    loop = PandaLoop(
        tasks=tasks,
        original_query="Implement user authentication",
        session_id="test_session",
        mode="code",
        unified_flow=mock_flow,
        base_turn=1,
        trace_id="test_basic",
    )

    result = await loop.run()

    # Verify
    assert result.status == "complete", f"Expected 'complete', got '{result.status}'"
    assert result.passed == 3, f"Expected 3 passed, got {result.passed}"
    assert result.failed == 0, f"Expected 0 failed, got {result.failed}"
    assert len(mock_flow.call_log) == 3, f"Expected 3 calls, got {len(mock_flow.call_log)}"

    print(f"  Status: {result.status}")
    print(f"  Passed: {result.passed}, Failed: {result.failed}")
    print(f"  Summary: {result.summary}")
    print("  PASSED")


async def test_task_dependencies():
    """Test that dependencies are respected."""
    print("\n" + "=" * 60)
    print("TEST: Task Dependencies")
    print("=" * 60)

    tasks = [
        {
            "id": "TASK-001",
            "title": "First task",
            "priority": 1,
            "status": "pending",
            "depends_on": [],
        },
        {
            "id": "TASK-002",
            "title": "Depends on first",
            "priority": 2,
            "status": "pending",
            "depends_on": ["TASK-001"],
        },
        {
            "id": "TASK-003",
            "title": "Depends on second",
            "priority": 3,
            "status": "pending",
            "depends_on": ["TASK-002"],
        },
    ]

    mock_flow = MockUnifiedFlow()
    loop = PandaLoop(
        tasks=tasks,
        original_query="Test dependencies",
        session_id="test_session",
        mode="code",
        unified_flow=mock_flow,
        base_turn=1,
    )

    result = await loop.run()

    # Verify execution order
    call_order = [c["task_id"] for c in mock_flow.call_log]
    assert call_order == ["TASK-001", "TASK-002", "TASK-003"], f"Wrong order: {call_order}"

    print(f"  Execution order: {call_order}")
    print(f"  Status: {result.status}")
    print("  PASSED")


async def test_failed_dependency_blocks():
    """Test that failed dependencies block dependent tasks."""
    print("\n" + "=" * 60)
    print("TEST: Failed Dependency Blocks Dependents")
    print("=" * 60)

    tasks = [
        {
            "id": "TASK-001",
            "title": "First task (will fail)",
            "priority": 1,
            "status": "pending",
            "depends_on": [],
        },
        {
            "id": "TASK-002",
            "title": "Depends on first (will be blocked)",
            "priority": 2,
            "status": "pending",
            "depends_on": ["TASK-001"],
        },
        {
            "id": "TASK-003",
            "title": "Independent task",
            "priority": 3,
            "status": "pending",
            "depends_on": [],
        },
    ]

    # TASK-001 fails, TASK-003 passes
    mock_flow = MockUnifiedFlow(task_outcomes={
        "TASK-001": "fail",
        "TASK-003": "pass",
    })

    loop = PandaLoop(
        tasks=tasks,
        original_query="Test blocking",
        session_id="test_session",
        mode="code",
        unified_flow=mock_flow,
        base_turn=1,
    )

    result = await loop.run()

    # Verify
    assert result.passed == 1, f"Expected 1 passed, got {result.passed}"
    assert result.failed == 1, f"Expected 1 failed, got {result.failed}"
    assert result.blocked == 1, f"Expected 1 blocked, got {result.blocked}"

    # TASK-002 should be blocked
    task2 = next(t for t in result.tasks if t["id"] == "TASK-002")
    assert task2["status"] == "blocked", f"TASK-002 should be blocked, got {task2['status']}"

    print(f"  Status: {result.status}")
    print(f"  Passed: {result.passed}, Failed: {result.failed}, Blocked: {result.blocked}")
    for t in result.tasks:
        print(f"    {t['id']}: {t['status']}")
    print("  PASSED")


async def test_priority_ordering():
    """Test that higher priority (lower number) runs first."""
    print("\n" + "=" * 60)
    print("TEST: Priority Ordering")
    print("=" * 60)

    tasks = [
        {
            "id": "TASK-003",
            "title": "Priority 3",
            "priority": 3,
            "status": "pending",
            "depends_on": [],
        },
        {
            "id": "TASK-001",
            "title": "Priority 1",
            "priority": 1,
            "status": "pending",
            "depends_on": [],
        },
        {
            "id": "TASK-002",
            "title": "Priority 2",
            "priority": 2,
            "status": "pending",
            "depends_on": [],
        },
    ]

    mock_flow = MockUnifiedFlow()
    loop = PandaLoop(
        tasks=tasks,
        original_query="Test priority",
        session_id="test_session",
        mode="code",
        unified_flow=mock_flow,
        base_turn=1,
    )

    result = await loop.run()

    # Verify execution order (by priority)
    call_order = [c["task_id"] for c in mock_flow.call_log]
    assert call_order == ["TASK-001", "TASK-002", "TASK-003"], f"Wrong order: {call_order}"

    print(f"  Execution order: {call_order}")
    print("  PASSED")


async def test_max_iterations():
    """Test that loop stops at max iterations."""
    print("\n" + "=" * 60)
    print("TEST: Max Iterations Limit")
    print("=" * 60)

    # Create more tasks than MAX_ITERATIONS
    tasks = [
        {
            "id": f"TASK-{i:03d}",
            "title": f"Task {i}",
            "priority": i,
            "status": "pending",
            "depends_on": [],
        }
        for i in range(1, 15)  # 14 tasks, but MAX_ITERATIONS is 10
    ]

    mock_flow = MockUnifiedFlow()
    loop = PandaLoop(
        tasks=tasks,
        original_query="Test max iterations",
        session_id="test_session",
        mode="code",
        unified_flow=mock_flow,
        base_turn=1,
    )

    result = await loop.run()

    # Verify
    assert result.status == "max_iterations", f"Expected 'max_iterations', got '{result.status}'"
    assert len(mock_flow.call_log) == 10, f"Expected 10 calls, got {len(mock_flow.call_log)}"

    print(f"  Status: {result.status}")
    print(f"  Tasks executed: {len(mock_flow.call_log)}")
    print("  PASSED")


async def test_format_loop_summary():
    """Test the summary formatting function."""
    print("\n" + "=" * 60)
    print("TEST: Loop Summary Formatting")
    print("=" * 60)

    result = LoopResult(
        status="complete",
        tasks=[
            {"id": "TASK-001", "title": "First task", "status": "passed"},
            {"id": "TASK-002", "title": "Second task", "status": "failed", "notes": "Validation error"},
            {"id": "TASK-003", "title": "Third task", "status": "blocked", "notes": "Blocked by TASK-002"},
        ],
        passed=1,
        failed=1,
        blocked=1,
        summary="1/3 tasks passed, 1 failed, 1 blocked",
        duration_seconds=12.5,
    )

    summary = format_loop_summary(result)

    # Verify key elements present
    assert "Panda Loop Complete" in summary
    assert "COMPLETE" in summary
    assert "TASK-001" in summary
    assert "PASSED" in summary
    assert "FAILED" in summary
    assert "BLOCKED" in summary
    assert "Failure Notes" in summary
    assert "Validation error" in summary

    print("  Summary preview:")
    for line in summary.split("\n")[:15]:
        print(f"    {line}")
    print("  PASSED")


# =============================================================================
# Integration Tests (requires running services)
# =============================================================================

async def test_integration_simple():
    """Integration test with actual UnifiedFlow (requires services)."""
    print("\n" + "=" * 60)
    print("TEST: Integration with Real Pipeline")
    print("=" * 60)

    try:
        from libs.gateway.unified_flow import UnifiedFlow
        from libs.llm.client import get_llm_client

        llm_client = get_llm_client()
        flow = UnifiedFlow(llm_client=llm_client)

        tasks = [
            {
                "id": "TASK-001",
                "title": "List files in current directory",
                "description": "Use ls command to list files",
                "acceptance_criteria": ["Files listed"],
                "priority": 1,
                "status": "pending",
                "depends_on": [],
            },
        ]

        loop = PandaLoop(
            tasks=tasks,
            original_query="List files and show their sizes",
            session_id="integration_test",
            mode="code",
            unified_flow=flow,
            base_turn=1,
            trace_id="integration",
        )

        result = await loop.run()

        print(f"  Status: {result.status}")
        print(f"  Summary: {result.summary}")
        print(f"  Duration: {result.duration_seconds:.1f}s")
        print("  PASSED (if no exceptions)")

    except ImportError as e:
        print(f"  SKIPPED: Required modules not available ({e})")
    except Exception as e:
        print(f"  FAILED: {e}")
        raise


# =============================================================================
# Main
# =============================================================================

async def run_unit_tests():
    """Run all unit tests."""
    print("\n" + "=" * 60)
    print("PANDA LOOP UNIT TESTS")
    print("=" * 60)

    await test_basic_loop()
    await test_task_dependencies()
    await test_failed_dependency_blocks()
    await test_priority_ordering()
    await test_max_iterations()
    await test_format_loop_summary()

    print("\n" + "=" * 60)
    print("ALL UNIT TESTS PASSED")
    print("=" * 60)


async def run_integration_tests():
    """Run integration tests (requires services)."""
    print("\n" + "=" * 60)
    print("PANDA LOOP INTEGRATION TESTS")
    print("=" * 60)

    await test_integration_simple()

    print("\n" + "=" * 60)
    print("INTEGRATION TESTS COMPLETE")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Test Panda Loop")
    parser.add_argument("--unit", action="store_true", help="Run unit tests only")
    parser.add_argument("--integration", action="store_true", help="Run integration tests only")
    args = parser.parse_args()

    if args.unit:
        asyncio.run(run_unit_tests())
    elif args.integration:
        asyncio.run(run_integration_tests())
    else:
        # Run all tests
        asyncio.run(run_unit_tests())
        print("\nSkipping integration tests by default. Use --integration to run them.")


if __name__ == "__main__":
    main()
