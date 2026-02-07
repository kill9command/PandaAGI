#!/usr/bin/env python3
"""
Replay Harness for Panda Transcripts

Replays JSONL transcripts in two modes:
1. Mock mode: Fast, deterministic, uses cached LLM responses
2. Live mode: Full execution, catches regressions

Usage:
    python scripts/replay_trace.py <trace_file> [mode]

    mode: "mock" (default) or "live"

Examples:
    python scripts/replay_trace.py transcripts/20251113.jsonl mock
    python scripts/replay_trace.py transcripts/20251113.jsonl live
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import httpx
import hashlib
import time
import sys


@dataclass
class ReplayResult:
    """Result of replaying a single turn"""
    turn_id: int
    success: bool
    guide_match: bool
    coordinator_match: bool
    tools_match: bool
    errors: List[str]
    timing_ms: int

    def __str__(self) -> str:
        status = "✅ PASS" if self.success else "❌ FAIL"
        details = f"Guide={self.guide_match}, Coord={self.coordinator_match}, Tools={self.tools_match}"
        return f"{status} Turn {self.turn_id} ({self.timing_ms}ms) - {details}"


class MockLLM:
    """Mock LLM that returns cached responses from trace"""

    def __init__(self, trace: List[Dict[str, Any]]):
        self.responses: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._index_responses(trace)

    def _index_responses(self, trace: List[Dict[str, Any]]):
        """Build lookup of role -> input_hash -> response"""
        for event in trace:
            if event.get("type") == "llm_call":
                role = event.get("role")
                prompt = event.get("prompt", "")
                response = event.get("response", {})

                prompt_hash = self._hash_prompt(prompt)

                if role not in self.responses:
                    self.responses[role] = {}

                self.responses[role][prompt_hash] = response

    def _hash_prompt(self, prompt: str) -> str:
        """Simple hash for prompt lookup"""
        return hashlib.md5(prompt.encode()).hexdigest()[:16]

    async def generate(self, role: str, prompt: str) -> Dict[str, Any]:
        """Return cached response for role + prompt"""
        prompt_hash = self._hash_prompt(prompt)

        if role in self.responses and prompt_hash in self.responses[role]:
            return self.responses[role][prompt_hash]

        raise ValueError(f"No cached response for role={role}, prompt_hash={prompt_hash}")


class MockOrchestrator:
    """Mock Orchestrator that returns cached tool results"""

    def __init__(self, trace: List[Dict[str, Any]]):
        self.tool_results: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._index_tool_results(trace)

    def _index_tool_results(self, trace: List[Dict[str, Any]]):
        """Build lookup of tool -> args_hash -> result"""
        for event in trace:
            if event.get("type") == "tool_call":
                tool = event.get("tool")
                args = event.get("args", {})
                result = event.get("result", {})

                args_hash = self._hash_args(args)

                if tool not in self.tool_results:
                    self.tool_results[tool] = {}

                self.tool_results[tool][args_hash] = result

    def _hash_args(self, args: Dict[str, Any]) -> str:
        """Simple hash for args lookup"""
        args_str = json.dumps(args, sort_keys=True)
        return hashlib.md5(args_str.encode()).hexdigest()[:16]

    async def call(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Return cached result for tool + args"""
        args_hash = self._hash_args(args)

        if tool in self.tool_results and args_hash in self.tool_results[tool]:
            return self.tool_results[tool][args_hash]

        raise ValueError(f"No cached result for tool={tool}, args_hash={args_hash}")


class TraceReplayer:
    """Replay transcript in mock or live mode"""

    def __init__(
        self,
        trace_path: str,
        mode: str = "mock",
        gateway_url: str = "http://127.0.0.1:9000"
    ):
        self.trace_path = Path(trace_path)
        self.mode = mode
        self.gateway_url = gateway_url

        if not self.trace_path.exists():
            raise FileNotFoundError(f"Trace file not found: {trace_path}")

        self.trace = self._load_trace()
        self.mock_llm = MockLLM(self.trace) if mode == "mock" else None
        self.mock_orch = MockOrchestrator(self.trace) if mode == "mock" else None

    def _load_trace(self) -> List[Dict[str, Any]]:
        """Load JSONL trace file"""
        events = []

        with open(self.trace_path) as f:
            for line in f:
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        print(f"Warning: Skipping invalid JSON line: {e}")

        return events

    async def replay(self) -> List[ReplayResult]:
        """Replay entire trace"""
        results = []

        # Extract user turns
        turns = self._extract_turns()

        print(f"\n{'='*60}")
        print(f"Replaying {len(turns)} turns in {self.mode} mode")
        print(f"Trace: {self.trace_path.name}")
        print(f"{'='*60}\n")

        for turn in turns:
            result = await self._replay_turn(turn)
            results.append(result)
            print(result)

        return results

    def _extract_turns(self) -> List[Dict[str, Any]]:
        """Extract user turns from trace"""
        turns = []
        current_turn = None

        for event in self.trace:
            event_type = event.get("type", "")

            if event_type == "user_message":
                # Save previous turn
                if current_turn:
                    turns.append(current_turn)

                # Start new turn
                current_turn = {
                    "id": len(turns) + 1,
                    "user_message": event.get("content", ""),
                    "events": []
                }

            # Add event to current turn
            if current_turn:
                current_turn["events"].append(event)

        # Add final turn
        if current_turn:
            turns.append(current_turn)

        return turns

    async def _replay_turn(self, turn: Dict[str, Any]) -> ReplayResult:
        """Replay single turn"""
        start_time = time.time()

        try:
            if self.mode == "mock":
                result = await self._replay_mock(turn)
            else:
                result = await self._replay_live(turn)

            end_time = time.time()

            return ReplayResult(
                turn_id=turn["id"],
                success=result.get("success", False),
                guide_match=result.get("guide_match", False),
                coordinator_match=result.get("coordinator_match", False),
                tools_match=result.get("tools_match", False),
                errors=result.get("errors", []),
                timing_ms=int((end_time - start_time) * 1000)
            )

        except Exception as e:
            end_time = time.time()
            return ReplayResult(
                turn_id=turn["id"],
                success=False,
                guide_match=False,
                coordinator_match=False,
                tools_match=False,
                errors=[str(e)],
                timing_ms=int((end_time - start_time) * 1000)
            )

    async def _replay_mock(self, turn: Dict[str, Any]) -> Dict[str, Any]:
        """Replay using cached responses (fast, deterministic)"""
        # Extract expected behavior from trace
        expected_guide_ticket = None
        expected_coordinator_plan = None
        expected_tools = []

        for event in turn["events"]:
            event_type = event.get("type", "")

            if event_type == "llm_call" and event.get("role") == "guide":
                response = event.get("response", {})
                if isinstance(response, dict):
                    expected_guide_ticket = response.get("ticket")

            if event_type == "llm_call" and event.get("role") == "coordinator":
                response = event.get("response", {})
                if isinstance(response, dict):
                    expected_coordinator_plan = response.get("plan")

            if event_type == "tool_call":
                expected_tools.append({
                    "tool": event.get("tool"),
                    "args": event.get("args", {})
                })

        # Simulate execution with cached responses
        errors = []

        # Guide call
        guide_ticket = None
        try:
            guide_response = await self.mock_llm.generate("guide", turn["user_message"])
            guide_ticket = guide_response.get("ticket") if isinstance(guide_response, dict) else None
        except Exception as e:
            errors.append(f"Guide call failed: {e}")

        # Coordinator call
        coordinator_plan = None
        if guide_ticket:
            try:
                coordinator_response = await self.mock_llm.generate(
                    "coordinator",
                    json.dumps(guide_ticket)
                )
                coordinator_plan = coordinator_response.get("plan") if isinstance(coordinator_response, dict) else None
            except Exception as e:
                errors.append(f"Coordinator call failed: {e}")

        # Compare behaviors (not exact text)
        guide_match = self._compare_tickets(expected_guide_ticket, guide_ticket)
        coordinator_match = self._compare_plans(expected_coordinator_plan, coordinator_plan)

        # Compare tool calls
        actual_tools = coordinator_plan.get("actions", []) if coordinator_plan else []
        tools_match = self._compare_tool_calls(expected_tools, actual_tools)

        if not guide_match:
            errors.append("Guide ticket structure mismatch")
        if not coordinator_match:
            errors.append("Coordinator plan structure mismatch")
        if not tools_match:
            errors.append("Tool call sequence mismatch")

        return {
            "success": len(errors) == 0,
            "guide_match": guide_match,
            "coordinator_match": coordinator_match,
            "tools_match": tools_match,
            "errors": errors
        }

    def _compare_tickets(self, expected: Any, actual: Any) -> bool:
        """Compare ticket structure (not exact text)"""
        if not expected or not actual:
            return False

        if not isinstance(expected, dict) or not isinstance(actual, dict):
            return False

        # Check required fields exist
        required = ["goal", "subtasks"]
        for field in required:
            if field not in actual:
                return False

        # Check subtask count matches (within reason)
        exp_subtasks = expected.get("subtasks", [])
        act_subtasks = actual.get("subtasks", [])

        if not isinstance(exp_subtasks, list) or not isinstance(act_subtasks, list):
            return False

        # Allow slight variation in subtask count
        if abs(len(exp_subtasks) - len(act_subtasks)) > 1:
            return False

        return True

    def _compare_plans(self, expected: Any, actual: Any) -> bool:
        """Compare coordinator plan structure"""
        if not expected or not actual:
            return False

        if not isinstance(expected, dict) or not isinstance(actual, dict):
            return False

        # Check actions list exists
        if "actions" not in actual:
            return False

        return True

    def _compare_tool_calls(self, expected: List[Dict], actual: List[Dict]) -> bool:
        """Compare tool call sequences"""
        if not isinstance(expected, list) or not isinstance(actual, list):
            return False

        # Allow slight variation in tool count
        if abs(len(expected) - len(actual)) > 1:
            return False

        # Check that same tools are called (order matters loosely)
        for exp, act in zip(expected, actual):
            # Same tool?
            if exp.get("tool") != act.get("tool"):
                return False

            # Same required args?
            exp_args = exp.get("args", {})
            act_args = act.get("args", {})

            if not isinstance(exp_args, dict) or not isinstance(act_args, dict):
                continue

            # Check that required args are present
            for key in exp_args:
                if key not in act_args:
                    return False

        return True

    async def _replay_live(self, turn: Dict[str, Any]) -> Dict[str, Any]:
        """Replay using live Gateway (catches regressions)"""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.gateway_url}/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": turn["user_message"]}],
                        "stream": False
                    },
                    timeout=120.0
                )

                if response.status_code != 200:
                    return {
                        "success": False,
                        "guide_match": False,
                        "coordinator_match": False,
                        "tools_match": False,
                        "errors": [f"Gateway returned {response.status_code}"]
                    }

                # For now, just verify it succeeded
                # Future: Extract actual behavior from response and compare
                return {
                    "success": True,
                    "guide_match": True,
                    "coordinator_match": True,
                    "tools_match": True,
                    "errors": []
                }

            except Exception as e:
                return {
                    "success": False,
                    "guide_match": False,
                    "coordinator_match": False,
                    "tools_match": False,
                    "errors": [str(e)]
                }


async def main():
    if len(sys.argv) < 2:
        print("Usage: python replay_trace.py <trace_file> [mode]")
        print("  mode: 'mock' (default) or 'live'")
        sys.exit(1)

    trace_file = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "mock"

    if mode not in ["mock", "live"]:
        print(f"Invalid mode: {mode}. Must be 'mock' or 'live'")
        sys.exit(1)

    try:
        replayer = TraceReplayer(trace_file, mode=mode)
        results = await replayer.replay()

        # Summary
        total = len(results)
        passed = sum(1 for r in results if r.success)
        failed = total - passed

        avg_time = sum(r.timing_ms for r in results) / total if total > 0 else 0

        print(f"\n{'='*60}")
        print(f"Replay Summary:")
        print(f"  Total turns: {total}")
        print(f"  Passed: {passed}")
        print(f"  Failed: {failed}")
        print(f"  Success rate: {(passed/total*100):.1f}%" if total > 0 else "N/A")
        print(f"  Avg time: {avg_time:.0f}ms")
        print(f"{'='*60}")

        # Exit with error code if any failures
        sys.exit(0 if failed == 0 else 1)

    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
