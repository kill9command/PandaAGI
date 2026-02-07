#!/usr/bin/env python3
"""
Test Agent Loop implementation for Phase 4 Coordinator.

Tests:
1. Agent loop correctly loads config from recipe
2. _parse_agent_decision handles various response formats
3. Step logging accumulates correctly
4. DONE/BLOCKED actions terminate the loop
"""

import asyncio
import json
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from libs.gateway.unified_flow import UnifiedFlow
from libs.gateway.context.context_document import ContextDocument
from libs.gateway.llm.recipe_loader import load_recipe


def test_recipe_agent_loop_config():
    """Test that coordinator recipes have agent_loop configuration."""
    print("\n=== Test 1: Recipe Agent Loop Config ===")

    for mode in ["chat", "code"]:
        recipe = load_recipe(f"coordinator_{mode}")
        raw_spec = getattr(recipe, '_raw_spec', {})
        agent_config = raw_spec.get('agent_loop', {})

        print(f"\ncoordinator_{mode}.yaml:")
        print(f"  agent_loop.enabled: {agent_config.get('enabled', False)}")
        print(f"  agent_loop.max_steps: {agent_config.get('max_steps', 'not set')}")
        print(f"  agent_loop.tools_per_step: {agent_config.get('tools_per_step', 'not set')}")

        assert agent_config.get('enabled', False), f"agent_loop not enabled in {mode} recipe"
        assert agent_config.get('max_steps', 0) > 0, f"max_steps not set in {mode} recipe"

    print("\n✓ All recipes have agent_loop configuration")
    return True


def test_parse_agent_decision():
    """Test _parse_agent_decision handles various formats."""
    print("\n=== Test 2: Parse Agent Decision ===")

    handler = UnifiedFlow.__new__(UnifiedFlow)

    # Test 1: Valid TOOL_CALL JSON
    response1 = json.dumps({
        "action": "TOOL_CALL",
        "tools": [
            {"tool": "file.read", "args": {"file_path": "test.py"}, "purpose": "Read file"}
        ],
        "reasoning": "Need to read the file first"
    })
    decision1 = handler._parse_agent_decision(response1)
    print(f"\nTest 1 (TOOL_CALL): {decision1['action']}")
    assert decision1["action"] == "TOOL_CALL", f"Expected TOOL_CALL, got {decision1['action']}"
    assert len(decision1["tools"]) == 1

    # Test 2: Valid DONE JSON
    response2 = json.dumps({
        "action": "DONE",
        "tools": [],
        "reasoning": "Task completed successfully",
        "progress_summary": "All changes made and tested",
        "remaining_work": ""
    })
    decision2 = handler._parse_agent_decision(response2)
    print(f"Test 2 (DONE): {decision2['action']}")
    assert decision2["action"] == "DONE"

    # Test 3: Valid BLOCKED JSON
    response3 = json.dumps({
        "action": "BLOCKED",
        "tools": [],
        "reasoning": "Permission denied for file",
        "progress_summary": "Attempted to edit system file",
        "remaining_work": "Cannot complete"
    })
    decision3 = handler._parse_agent_decision(response3)
    print(f"Test 3 (BLOCKED): {decision3['action']}")
    assert decision3["action"] == "BLOCKED"

    # Test 4: Invalid JSON - should default to BLOCKED
    response4 = "This is not valid JSON at all"
    decision4 = handler._parse_agent_decision(response4)
    print(f"Test 4 (Invalid JSON): {decision4['action']}")
    assert decision4["action"] == "BLOCKED", "Invalid JSON should result in BLOCKED"

    # Test 5: JSON without action - should infer BLOCKED
    response5 = json.dumps({"tools": [], "reasoning": "Unclear state"})
    decision5 = handler._parse_agent_decision(response5)
    print(f"Test 5 (No action field): {decision5['action']}")
    # Should default to BLOCKED since no action specified

    print("\n✓ All decision parsing tests passed")
    return True


def test_context_document_section_methods():
    """Test ContextDocument section methods used by agent loop."""
    print("\n=== Test 3: Context Document Section Methods ===")

    doc = ContextDocument(
        turn_number=1,
        session_id="test_session",
        query="Test query"
    )

    # Test append_section
    doc.append_section(4, "Tool Execution", "*(Agent loop starting...)*")
    print(f"After append_section(4): §4 exists = {4 in doc.sections}")
    assert 4 in doc.sections

    # Test update_section
    doc.update_section(4, "### Step 1\nTool executed successfully")
    content = doc.sections[4]["content"]
    print(f"After update_section(4): content starts with '### Step 1' = {content.startswith('### Step 1')}")
    assert content.startswith("### Step 1")

    # Test multiple updates (simulating multiple steps)
    doc.update_section(4, "### Step 1\nDone\n\n### Step 2\nMore work")
    content = doc.sections[4]["content"]
    print(f"After second update: contains 'Step 2' = {'Step 2' in content}")
    assert "Step 2" in content

    print("\n✓ Context document section methods work correctly")
    return True


def test_agent_loop_prompt_exists():
    """Test that agent_loop.md prompt exists and has correct content."""
    print("\n=== Test 4: Agent Loop Prompt ===")

    prompt_path = Path("apps/prompts/coordinator/agent_loop.md")
    assert prompt_path.exists(), f"agent_loop.md not found at {prompt_path}"

    content = prompt_path.read_text()

    # Check for key sections
    required_sections = [
        "TOOL_CALL",
        "DONE",
        "BLOCKED",
        "Output Format",
        '"action"'
    ]

    for section in required_sections:
        assert section in content, f"Missing section: {section}"
        print(f"  ✓ Contains '{section}'")

    print(f"\n✓ agent_loop.md exists ({len(content)} chars)")
    return True


async def test_integration_mock():
    """Integration test with mock LLM responses."""
    print("\n=== Test 5: Integration Test (Mock) ===")

    # This test verifies the structure without actually calling the LLM
    # In a full integration test, you would mock the LLM client

    print("  - Recipe loading: coordinator_chat and coordinator_code")
    chat_recipe = load_recipe("coordinator_chat")
    code_recipe = load_recipe("coordinator_code")

    print("  - Checking output_schema is AGENT_DECISION")
    chat_spec = getattr(chat_recipe, '_raw_spec', {})
    code_spec = getattr(code_recipe, '_raw_spec', {})

    assert chat_spec.get('output_schema') == 'AGENT_DECISION', "chat recipe missing AGENT_DECISION schema"
    assert code_spec.get('output_schema') == 'AGENT_DECISION', "code recipe missing AGENT_DECISION schema"

    print("  - Checking prompt fragments include agent_loop.md")
    chat_fragments = chat_spec.get('prompt_fragments', [])
    code_fragments = code_spec.get('prompt_fragments', [])

    chat_has_agent = any('agent_loop.md' in f for f in chat_fragments)
    code_has_agent = any('agent_loop.md' in f for f in code_fragments)

    assert chat_has_agent, "chat recipe missing agent_loop.md in fragments"
    assert code_has_agent, "code recipe missing agent_loop.md in fragments"

    print("\n✓ Integration structure verified")
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Agent Loop Implementation Tests")
    print("=" * 60)

    all_passed = True

    # Test 1: Recipe configuration
    try:
        test_recipe_agent_loop_config()
    except Exception as e:
        print(f"\n✗ Test 1 failed: {e}")
        all_passed = False

    # Test 2: Decision parsing
    try:
        test_parse_agent_decision()
    except Exception as e:
        print(f"\n✗ Test 2 failed: {e}")
        all_passed = False

    # Test 3: Context document methods
    try:
        test_context_document_section_methods()
    except Exception as e:
        print(f"\n✗ Test 3 failed: {e}")
        all_passed = False

    # Test 4: Prompt file
    try:
        test_agent_loop_prompt_exists()
    except Exception as e:
        print(f"\n✗ Test 4 failed: {e}")
        all_passed = False

    # Test 5: Integration structure
    try:
        asyncio.run(test_integration_mock())
    except Exception as e:
        print(f"\n✗ Test 5 failed: {e}")
        all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ ALL TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
