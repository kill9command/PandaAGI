#!/usr/bin/env python3
"""
Test Web Vision MCP Layer

Tests web.* functions for vision-guided browser automation.

Note: Requires a running browser session. Use with caution as it will
actually navigate and interact with web pages.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import logging
from apps.services.orchestrator import web_vision_mcp
from apps.services.orchestrator.crawler_session_manager import get_session_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_session_initialization():
    """Test: Initialize browser session"""
    print("=== Test 1: Initialize Browser Session ===\n")

    manager = get_session_manager()
    session_id = "test_web_vision"
    domain = "example.com"

    # Create session
    await manager.get_or_create_session(
        domain=domain,
        session_id=session_id,
        user_id="test_user"
    )

    # Check status
    status = await web_vision_mcp.get_status(session_id)
    print(f"✓ Session exists: {status['session_exists']}")
    print(f"✓ Page info: {status['page_info']}")
    print(f"✓ Viewport: {status['viewport']}\n")

    assert status['session_exists'], "Session should exist"
    print("✓ Test 1 passed!\n")

    return session_id


async def test_navigate():
    """Test: Navigate to URL"""
    print("=== Test 2: Navigate to URL ===\n")

    session_id = "test_web_vision"

    result = await web_vision_mcp.navigate(
        session_id=session_id,
        url="https://example.com",
        wait_for="networkidle"
    )

    print(f"✓ Success: {result['success']}")
    print(f"✓ URL: {result['url']}")
    print(f"✓ Title: {result['title']}")
    print(f"✓ Status code: {result['status_code']}")
    print(f"✓ Message: {result['message']}\n")

    assert result['success'], "Navigation should succeed"
    assert result['status_code'] == 200, "Should get HTTP 200"
    print("✓ Test 2 passed!\n")


async def test_get_screen_state():
    """Test: Get page state"""
    print("=== Test 3: Get Screen State ===\n")

    session_id = "test_web_vision"

    result = await web_vision_mcp.get_screen_state(
        session_id=session_id,
        max_elements=20,
        max_text_len=30
    )

    print(f"✓ Success: {result['success']}")
    print(f"✓ Element count: {result['element_count']}")
    print(f"✓ Estimated tokens: {result['estimated_tokens']}")
    print(f"✓ Page info: {result['page_info']}")
    print(f"\n✓ Screen state (first 500 chars):\n{result['screen_state'][:500]}...\n")

    assert result['success'], "get_screen_state should succeed"
    assert result['element_count'] > 0, "Should find elements on page"
    assert result['estimated_tokens'] < 300, "Screen state should be <300 tokens"
    print("✓ Test 3 passed!\n")


async def test_scroll():
    """Test: Scroll page"""
    print("=== Test 4: Scroll Page ===\n")

    session_id = "test_web_vision"

    result = await web_vision_mcp.scroll(
        session_id=session_id,
        clicks=3
    )

    print(f"✓ Success: {result['success']}")
    print(f"✓ Message: {result['message']}")
    print(f"✓ Metadata: {result['metadata']}\n")

    assert result['success'], "Scroll should succeed"
    print("✓ Test 4 passed!\n")


async def test_capture_content():
    """Test: Capture page content"""
    print("=== Test 5: Capture Content (Markdown) ===\n")

    session_id = "test_web_vision"

    result = await web_vision_mcp.capture_content(
        session_id=session_id,
        format="markdown"
    )

    print(f"✓ Success: {result['success']}")
    print(f"✓ URL: {result['url']}")
    print(f"✓ Title: {result['title']}")
    print(f"✓ Content length: {len(result['content'])} chars")
    print(f"✓ Estimated tokens: {result['estimated_tokens']}")
    print(f"\n✓ Content preview (first 300 chars):\n{result['content'][:300]}...\n")

    assert result['success'], "Content capture should succeed"
    assert len(result['content']) > 0, "Should have captured content"
    print("✓ Test 5 passed!\n")


async def test_cleanup():
    """Test: Cleanup session"""
    print("=== Test 6: Cleanup ===\n")

    manager = get_session_manager()
    session_id = "test_web_vision"

    # Close session
    await manager.close_session(session_id)

    # Verify closed
    status = await web_vision_mcp.get_status(session_id)
    print(f"✓ Session exists: {status['session_exists']}")

    assert not status['session_exists'], "Session should be closed"
    print("✓ Test 6 passed!\n")


async def run_all_tests():
    """Run all tests sequentially"""
    print("\n" + "="*60)
    print("Web Vision MCP Test Suite")
    print("="*60 + "\n")

    try:
        # Test 1: Initialize
        session_id = await test_session_initialization()

        # Test 2: Navigate
        await test_navigate()

        # Test 3: Get screen state
        await test_get_screen_state()

        # Test 4: Scroll
        await test_scroll()

        # Test 5: Capture content
        await test_capture_content()

        # Test 6: Cleanup
        await test_cleanup()

        print("="*60)
        print("✅ All tests passed!")
        print("="*60 + "\n")

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}\n")
        raise

    except Exception as e:
        print(f"\n❌ Error during tests: {e}\n")
        raise


if __name__ == "__main__":
    asyncio.run(run_all_tests())
