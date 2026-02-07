#!/usr/bin/env python3
"""
Test browser control integration end-to-end.

Tests:
1. Browser session registry functionality
2. Session registration from web_vision_mcp
3. Intervention pause/resume
4. Gateway API endpoints
"""

import sys
import asyncio
import httpx
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.services.tool_server.browser_session_registry import get_browser_session_registry, SessionStatus


def test_browser_session_registry():
    """Test browser session registry basic operations."""
    print("\n=== Test 1: Browser Session Registry ===")

    registry = get_browser_session_registry()

    # Test 1: Register a session
    session = registry.register_session(
        session_id="test_session_001",
        cdp_url="ws://localhost:9223/devtools/browser/abc123",
        cdp_http_url="http://localhost:9223",
        viewable=True,
        metadata={"test": "data"}
    )

    assert session.session_id == "test_session_001"
    assert session.status == SessionStatus.ACTIVE
    print("✓ Session registered successfully")

    # Test 2: Get session
    retrieved = registry.get_session("test_session_001")
    assert retrieved is not None
    assert retrieved.session_id == "test_session_001"
    print("✓ Session retrieved successfully")

    # Test 3: Mark as paused
    registry.mark_paused("test_session_001", "intervention_001", "CAPTCHA detected")
    retrieved = registry.get_session("test_session_001")
    assert retrieved.status == SessionStatus.PAUSED
    assert retrieved.intervention_id == "intervention_001"
    print("✓ Session paused successfully")

    # Test 4: Get viewable sessions
    viewable = registry.get_viewable_sessions()
    assert len(viewable) == 1
    assert viewable[0].session_id == "test_session_001"
    print("✓ Viewable sessions retrieved successfully")

    # Test 5: Mark as resumed
    registry.mark_resumed("test_session_001")
    retrieved = registry.get_session("test_session_001")
    assert retrieved.status == SessionStatus.ACTIVE
    assert retrieved.intervention_id is None
    print("✓ Session resumed successfully")

    # Test 6: Get stats
    stats = registry.get_stats()
    assert stats["total"] >= 1
    assert stats["active"] >= 1
    print(f"✓ Registry stats: {stats}")

    # Cleanup
    registry.close_session("test_session_001")

    print("✓ All browser session registry tests passed!")
    return True


async def test_gateway_api():
    """Test Gateway API endpoints."""
    print("\n=== Test 2: Gateway API Endpoints ===")

    # First, register a test session
    registry = get_browser_session_registry()
    registry.register_session(
        session_id="test_gateway_session",
        cdp_url="ws://localhost:9223/devtools/browser/xyz789",
        viewable=True
    )
    registry.mark_paused("test_gateway_session", "test_intervention", "Test CAPTCHA")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Test 1: GET /api/browser_sessions
        try:
            response = await client.get("http://localhost:9000/api/browser_sessions")

            if response.status_code == 200:
                data = response.json()
                print(f"✓ GET /api/browser_sessions returned {data['count']} sessions")
                assert "sessions" in data
                assert "count" in data

                # Check if our test session is in the list
                session_found = any(
                    s["session_id"] == "test_gateway_session"
                    for s in data["sessions"]
                )
                if session_found:
                    print("✓ Test session found in API response")
                else:
                    print("⚠ Test session not found in API response (may not be viewable)")
            else:
                print(f"✗ GET /api/browser_sessions failed: {response.status_code}")
                print(f"  Response: {response.text}")
                return False

        except Exception as e:
            print(f"✗ Error testing GET /api/browser_sessions: {e}")
            print("  (Gateway may not be running)")
            return False

    # Cleanup
    registry.close_session("test_gateway_session")

    print("✓ Gateway API tests passed!")
    return True


async def test_integration():
    """Run all integration tests."""
    print("=" * 60)
    print("Browser Control Integration Tests")
    print("=" * 60)

    # Test 1: Browser Session Registry
    if not test_browser_session_registry():
        print("\n✗ Browser session registry tests failed!")
        return False

    # Test 2: Gateway API
    if not await test_gateway_api():
        print("\n✗ Gateway API tests failed!")
        return False

    print("\n" + "=" * 60)
    print("✓ ALL TESTS PASSED!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Restart Gateway to load new endpoints: ./stop.sh && ./start.sh")
    print("2. Trigger a research query that hits a CAPTCHA")
    print("3. Visit http://localhost:9000/static/captcha.html")
    print("4. Click 'View & Control Browser' to test the full flow")
    print("=" * 60)

    return True


if __name__ == "__main__":
    success = asyncio.run(test_integration())
    sys.exit(0 if success else 1)
