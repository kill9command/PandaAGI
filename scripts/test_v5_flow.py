#!/usr/bin/env python3
"""
Test the V5Flow (simplified document IO) implementation.

This test verifies the complete 6-phase pipeline with:
1. Context Gatherer finding prior preferences
2. Reflection deciding to proceed
3. Planner classifying intent
4. Coordinator skipped (for recall)
5. Synthesis generating correct response
6. Turn saved with full documents
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from libs.gateway.v5_flow import V5Flow
from libs.gateway.context.context_document import ContextDocument
from libs.gateway.persistence.turn_saver import TurnSaver


class MockLLMClient:
    """Mock LLM client for testing without actual LLM calls."""

    async def generate(self, prompt: str, max_tokens: int = 1000, temperature: float = 0.7) -> str:
        """Generate mock responses based on prompt content."""

        # Reflection phase
        if "Reflection phase" in prompt:
            return '{"decision": "PROCEED", "reasoning": "Found preferences in context"}'

        # Synthesis phase
        if "Synthesis phase" in prompt:
            # Check for preference recall
            if "favorite_hamster" in prompt.lower() or "syrian" in prompt.lower():
                return "Your favorite hamster is the Syrian hamster."
            if "laptop" in prompt.lower():
                return "Here are some laptops with NVIDIA GPUs I found..."
            return "I've processed your request."

        return "Mock response"


async def setup_test_data():
    """Create test preference data."""
    # Create a prior turn with hamster preference
    turns_dir = Path("panda_system_docs/turns")
    sessions_dir = Path("panda_system_docs/sessions")

    # Create session preferences
    session_dir = sessions_dir / "v5_test_user"
    session_dir.mkdir(parents=True, exist_ok=True)

    prefs_content = """# User Preferences

## General

- **favorite_hamster:** Syrian hamster
- **location:** online

---

*Updated automatically by turn saver*
"""
    (session_dir / "preferences.md").write_text(prefs_content)
    print(f"Created test preferences at {session_dir / 'preferences.md'}")

    # Create a prior turn
    turn_dir = turns_dir / "turn_000900"
    turn_dir.mkdir(parents=True, exist_ok=True)

    context_content = """# Context Document
**Turn:** 900
**Session:** v5_test_user

---

## 0. User Query

my favorite hamster is the syrian hamster

---

## 1. Gathered Context

### Session Preferences
*(No preferences stored yet)*

---

## 2. Reflection Decision

**Decision:** PROCEED
**Reasoning:** User is stating a preference.
**Route:** synthesis

---

## 3. Task Plan

**Goal:** Acknowledge user's hamster preference
**Intent:** preference
**Subtasks:**
1. Acknowledge the preference statement

**Tools Required:** none
**Route To:** synthesis

---

## 5. Synthesis

**Response Preview:**
I've noted that your favorite hamster is the Syrian hamster.

**Validation Checklist:**
- [x] Claims match evidence
- [x] Intent satisfied
"""
    (turn_dir / "context.md").write_text(context_content)
    (turn_dir / "response.md").write_text("I've noted that your favorite hamster is the Syrian hamster.")

    import json
    metadata = {
        "turn_number": 900,
        "session_id": "v5_test_user",
        "timestamp": 1765045000.0,
        "topic": "hamster preference",
        "intent": "preference",
        "tools_used": [],
        "claims_count": 0,
        "response_quality": 0.95,
        "keywords": ["hamster", "syrian", "favorite", "preference"]
    }
    (turn_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    print(f"Created test turn at {turn_dir}")
    return session_dir, turn_dir


async def cleanup_test_data(session_dir: Path, turn_dirs: list):
    """Clean up test data."""
    import shutil

    for turn_dir in turn_dirs:
        if turn_dir.exists():
            shutil.rmtree(turn_dir)
            print(f"Cleaned up: {turn_dir}")

    if session_dir.exists():
        shutil.rmtree(session_dir)
        print(f"Cleaned up: {session_dir}")


async def test_preference_recall():
    """Test that V5Flow correctly recalls a preference."""
    print("\n" + "=" * 60)
    print("  TEST: Preference Recall with V5Flow")
    print("=" * 60)

    # Setup test data
    session_dir, prior_turn_dir = await setup_test_data()
    test_turn_dirs = [prior_turn_dir]

    try:
        # Create V5Flow with mock LLM
        flow = V5Flow(
            llm_client=MockLLMClient(),
            session_context_manager=None
        )

        # Test: Recall preference
        print("\n[TEST] Query: 'what's my favorite hamster?'")
        result = await flow.handle_request(
            user_query="what's my favorite hamster?",
            session_id="v5_test_user",
            mode="chat",
            trace_id="test_trace_001",
            turn_number=901
        )

        print(f"\n[RESULT]")
        print(f"Response: {result['response']}")
        print(f"Turn dir: {result.get('turn_dir', 'N/A')}")
        print(f"Elapsed: {result.get('elapsed_ms', 0):.0f}ms")

        # Add new turn to cleanup list
        if result.get('turn_dir'):
            test_turn_dirs.append(Path(result['turn_dir']))

        # Verify response
        print("\n[VERIFICATION]")
        if "syrian" in result['response'].lower():
            print("✅ PASS: Response contains 'Syrian'")
            success = True
        else:
            print("❌ FAIL: Response does not contain 'Syrian'")
            success = False

        # Show the context.md that was built
        context_doc = result.get('context_doc')
        if context_doc:
            print("\n[CONTEXT.MD]")
            print(context_doc.get_markdown())

        return success

    finally:
        # Cleanup
        print("\n[CLEANUP]")
        await cleanup_test_data(session_dir, test_turn_dirs)


async def test_preference_statement():
    """Test that V5Flow correctly handles a new preference statement."""
    print("\n" + "=" * 60)
    print("  TEST: Preference Statement with V5Flow")
    print("=" * 60)

    # Create session dir
    sessions_dir = Path("panda_system_docs/sessions")
    session_dir = sessions_dir / "v5_test_user2"
    session_dir.mkdir(parents=True, exist_ok=True)

    test_turn_dirs = []

    try:
        # Create V5Flow with mock LLM
        flow = V5Flow(
            llm_client=MockLLMClient(),
            session_context_manager=None
        )

        # Test: State preference
        print("\n[TEST] Query: 'my favorite color is blue'")
        result = await flow.handle_request(
            user_query="my favorite color is blue",
            session_id="v5_test_user2",
            mode="chat",
            trace_id="test_trace_002",
            turn_number=1
        )

        print(f"\n[RESULT]")
        print(f"Response: {result['response']}")

        # Add turn to cleanup list
        if result.get('turn_dir'):
            test_turn_dirs.append(Path(result['turn_dir']))

        # Verify preference was saved
        prefs_file = session_dir / "preferences.md"
        if prefs_file.exists():
            prefs_content = prefs_file.read_text()
            print(f"\n[PREFERENCES.MD]")
            print(prefs_content)

            if "favorite_color" in prefs_content.lower() or "blue" in prefs_content.lower():
                print("\n✅ PASS: Preference was saved")
                success = True
            else:
                print("\n❌ FAIL: Preference was not saved correctly")
                success = False
        else:
            print("\n⚠️  WARNING: preferences.md not created")
            success = False

        return success

    finally:
        # Cleanup
        print("\n[CLEANUP]")
        await cleanup_test_data(session_dir, test_turn_dirs)


async def main():
    print("\n" + "=" * 60)
    print("  V5FLOW INTEGRATION TESTS")
    print("=" * 60)

    results = []

    # Test 1: Preference Recall
    results.append(("Preference Recall", await test_preference_recall()))

    # Test 2: Preference Statement
    results.append(("Preference Statement", await test_preference_statement()))

    # Summary
    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("  🎉 ALL TESTS PASSED")
    else:
        print("  ❌ SOME TESTS FAILED")
    print("=" * 60 + "\n")

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
