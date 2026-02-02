#!/usr/bin/env python3
"""
Test script for replay harness

Tests the replay functionality with a simple mock trace
"""

import json
import tempfile
import asyncio
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.replay_trace import TraceReplayer


def create_test_trace() -> str:
    """Create a simple test trace in temp file"""
    trace_events = [
        # Turn 1: Simple query
        {
            "type": "user_message",
            "content": "What is a Syrian hamster?",
            "timestamp": "2025-11-13T10:00:00"
        },
        {
            "type": "llm_call",
            "role": "guide",
            "prompt": "What is a Syrian hamster?",
            "response": {
                "ticket": {
                    "goal": "Provide information about Syrian hamsters",
                    "subtasks": [
                        {"kind": "search", "q": "Syrian hamster information"}
                    ]
                }
            }
        },
        {
            "type": "llm_call",
            "role": "coordinator",
            "prompt": json.dumps({
                "goal": "Provide information about Syrian hamsters",
                "subtasks": [{"kind": "search", "q": "Syrian hamster information"}]
            }),
            "response": {
                "plan": {
                    "actions": [
                        {
                            "tool": "doc.search",
                            "args": {"query": "Syrian hamster", "k": 5}
                        }
                    ]
                }
            }
        },
        {
            "type": "tool_call",
            "tool": "doc.search",
            "args": {"query": "Syrian hamster", "k": 5},
            "result": {
                "results": [
                    {"content": "Syrian hamsters are solitary animals..."}
                ]
            }
        },
        # Turn 2: Follow-up query
        {
            "type": "user_message",
            "content": "How big do they get?",
            "timestamp": "2025-11-13T10:01:00"
        },
        {
            "type": "llm_call",
            "role": "guide",
            "prompt": "How big do they get?",
            "response": {
                "ticket": {
                    "goal": "Provide size information for Syrian hamsters",
                    "subtasks": [
                        {"kind": "search", "q": "Syrian hamster size"}
                    ]
                }
            }
        },
        {
            "type": "llm_call",
            "role": "coordinator",
            "prompt": json.dumps({
                "goal": "Provide size information for Syrian hamsters",
                "subtasks": [{"kind": "search", "q": "Syrian hamster size"}]
            }),
            "response": {
                "plan": {
                    "actions": [
                        {
                            "tool": "doc.search",
                            "args": {"query": "Syrian hamster size", "k": 3}
                        }
                    ]
                }
            }
        },
        {
            "type": "tool_call",
            "tool": "doc.search",
            "args": {"query": "Syrian hamster size", "k": 3},
            "result": {
                "results": [
                    {"content": "Syrian hamsters grow 5-7 inches long..."}
                ]
            }
        }
    ]

    # Write to temp file
    temp_file = tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.jsonl',
        delete=False
    )

    for event in trace_events:
        temp_file.write(json.dumps(event) + '\n')

    temp_file.close()
    return temp_file.name


async def test_replay():
    """Test replay functionality"""
    print("Creating test trace...")
    trace_file = create_test_trace()

    try:
        print(f"Test trace: {trace_file}")

        # Test mock mode
        print("\n" + "="*60)
        print("Testing MOCK mode")
        print("="*60)

        replayer = TraceReplayer(trace_file, mode="mock")
        results = await replayer.replay()

        # Verify results
        assert len(results) == 2, f"Expected 2 results, got {len(results)}"

        for result in results:
            assert result.success, f"Turn {result.turn_id} failed: {result.errors}"
            assert result.guide_match, f"Turn {result.turn_id}: Guide mismatch"
            assert result.coordinator_match, f"Turn {result.turn_id}: Coordinator mismatch"
            assert result.tools_match, f"Turn {result.turn_id}: Tools mismatch"

        print("\n✅ All tests passed!")

    finally:
        # Cleanup
        Path(trace_file).unlink()
        print(f"\nCleaned up: {trace_file}")


if __name__ == "__main__":
    asyncio.run(test_replay())
