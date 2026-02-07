#!/usr/bin/env python3
"""
Test Computer Agent MCP Layer

Tests get_screen_state function without V4Flow dependencies.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from apps.services.tool_server import computer_agent_mcp

async def test_screen_state():
    """Test get_screen_state MCP function."""
    print("=== Testing computer.get_screen_state ===\n")

    result = await computer_agent_mcp.get_screen_state(
        max_elements=20,
        max_text_len=20
    )

    print(f"✓ Success: {result['success']}")
    print(f"✓ Element count: {result['element_count']}")
    print(f"✓ Estimated tokens: {result['estimated_tokens']}")
    print(f"✓ Screen size: {result['screen_size']}")
    print(f"✓ Message: {result['message']}")
    print(f"\n✓ Screen state (first 500 chars):\n{result['screen_state'][:500]}...")

    # Assertions
    assert "success" in result
    assert "message" in result
    assert "screen_size" in result
    assert result['estimated_tokens'] < 300, "Screen state exceeds 300 tokens!"
    assert result['success'], "get_screen_state failed!"

    print("\n✓ Test passed!")

if __name__ == "__main__":
    asyncio.run(test_screen_state())
