"""
Test script for human-assisted web crawling.

Tests:
1. Browser fingerprint generation
2. Blocker detection
3. Intervention request/resolve flow
4. Session persistence
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_browser_fingerprint():
    """Test browser fingerprint generation"""
    print("\n" + "="*60)
    print("TEST 1: Browser Fingerprint Generation")
    print("="*60)

    from apps.services.orchestrator.browser_fingerprint import BrowserFingerprint

    # Test deterministic generation
    fp1 = BrowserFingerprint("test-user", "session-123")
    fp2 = BrowserFingerprint("test-user", "session-123")

    assert fp1.user_agent == fp2.user_agent, "User agents should match"
    assert fp1.viewport == fp2.viewport, "Viewports should match"
    assert fp1.timezone == fp2.timezone, "Timezones should match"

    print(f"✓ Deterministic fingerprint generation works")
    print(f"  User-Agent: {fp1.user_agent[:60]}...")
    print(f"  Viewport: {fp1.viewport}")
    print(f"  Timezone: {fp1.timezone}")
    print(f"  Locale: {fp1.locale}")

    # Test different sessions have different fingerprints
    fp3 = BrowserFingerprint("test-user", "session-456")
    assert fp1.user_agent != fp3.user_agent or fp1.viewport != fp3.viewport, \
        "Different sessions should have different fingerprints"

    print(f"✓ Different sessions generate different fingerprints")


async def test_blocker_detection():
    """Test CAPTCHA/blocker detection"""
    print("\n" + "="*60)
    print("TEST 2: Blocker Detection")
    print("="*60)

    from apps.services.orchestrator.captcha_intervention import detect_blocker, InterventionType

    # Test reCAPTCHA detection
    page_with_recaptcha = {
        "content": '<html><body><div class="g-recaptcha"></div></body></html>',
        "status": 200,
        "url": "https://example.com"
    }
    blocker = detect_blocker(page_with_recaptcha)
    assert blocker is not None, "Should detect reCAPTCHA"
    assert blocker["type"] == InterventionType.CAPTCHA_RECAPTCHA
    assert blocker["confidence"] >= 0.9
    print(f"✓ reCAPTCHA detected: confidence={blocker['confidence']}")

    # Test Cloudflare detection
    page_with_cloudflare = {
        "content": '<html><body>Cloudflare checking your browser before accessing example.com</body></html>',
        "status": 200,
        "url": "https://example.com"
    }
    blocker = detect_blocker(page_with_cloudflare)
    assert blocker is not None, "Should detect Cloudflare"
    assert blocker["type"] == InterventionType.CAPTCHA_CLOUDFLARE
    print(f"✓ Cloudflare detected: confidence={blocker['confidence']}")

    # Test clean page (no blocker)
    clean_page = {
        "content": '<html><body><h1>Welcome</h1><p>' + 'x'*200 + '</p></body></html>',
        "status": 200,
        "url": "https://example.com"
    }
    blocker = detect_blocker(clean_page)
    assert blocker is None, "Clean page should not be flagged"
    print(f"✓ Clean page correctly identified (no blocker)")

    # Test rate limiting
    rate_limited_page = {
        "content": "",
        "status": 429,
        "url": "https://example.com"
    }
    blocker = detect_blocker(rate_limited_page)
    assert blocker is not None, "Should detect rate limiting"
    assert blocker["type"] == InterventionType.RATE_LIMIT
    print(f"✓ Rate limiting detected: confidence={blocker['confidence']}")


async def test_intervention_flow():
    """Test intervention request and resolution"""
    print("\n" + "="*60)
    print("TEST 3: Intervention Request/Resolve Flow")
    print("="*60)

    from apps.services.orchestrator.captcha_intervention import (
        request_intervention,
        get_pending_intervention,
        get_all_pending_interventions
    )

    # Create intervention
    intervention = await request_intervention(
        blocker_type="captcha_recaptcha",
        url="https://example.com/page",
        screenshot_path="/tmp/screenshot.png",
        session_id="test-session"
    )

    print(f"✓ Intervention created: {intervention.intervention_id}")
    print(f"  Type: {intervention.intervention_type.value}")
    print(f"  Domain: {intervention.domain}")

    # Check pending
    pending = get_all_pending_interventions()
    assert len(pending) == 1, "Should have 1 pending intervention"
    print(f"✓ Intervention in pending registry")

    # Retrieve by ID
    retrieved = get_pending_intervention(intervention.intervention_id)
    assert retrieved is not None, "Should retrieve intervention by ID"
    assert retrieved.intervention_id == intervention.intervention_id
    print(f"✓ Retrieved intervention by ID")

    # Test async wait with immediate resolution (in background task)
    async def resolve_after_delay():
        await asyncio.sleep(1)
        intervention.mark_resolved(success=True, cookies=[{"name": "test", "value": "123"}])

    asyncio.create_task(resolve_after_delay())

    # Wait for resolution
    resolved = await intervention.wait_for_resolution(timeout=5)
    assert resolved == True, "Should resolve successfully"
    assert intervention.resolved == True
    assert intervention.resolution_success == True
    print(f"✓ Intervention resolved successfully")
    print(f"  Resolution time: {(intervention.resolved_at - intervention.created_at).total_seconds():.2f}s")

    # Test timeout
    intervention2 = await request_intervention(
        blocker_type="captcha_hcaptcha",
        url="https://example.com/page2",
        screenshot_path="/tmp/screenshot2.png",
        session_id="test-session"
    )

    resolved = await intervention2.wait_for_resolution(timeout=2)
    assert resolved == False, "Should timeout and return False"
    print(f"✓ Timeout handling works correctly")


async def test_session_manager():
    """Test crawler session manager"""
    print("\n" + "="*60)
    print("TEST 4: Crawler Session Manager")
    print("="*60)

    from apps.services.orchestrator.crawler_session_manager import CrawlerSessionManager
    from pathlib import Path
    import shutil

    # Create test directory
    test_dir = Path("panda_system_docs/shared_state/crawler_sessions_test")
    if test_dir.exists():
        shutil.rmtree(test_dir)

    session_mgr = CrawlerSessionManager(
        base_dir=str(test_dir),
        default_ttl_hours=24
    )

    # Create session
    context = await session_mgr.get_or_create_session(
        domain="example.com",
        session_id="test-session",
        user_id="test-user"
    )

    print(f"✓ Session created successfully")
    assert context is not None, "Should create browser context"

    # Save session state
    await session_mgr.save_session_state(
        domain="example.com",
        session_id="test-session",
        context=context,
        user_id="test-user"
    )

    print(f"✓ Session state saved to disk")

    # Verify persistence
    session_dir = test_dir / "test-session" / "example_com"
    assert (session_dir / "state.json").exists(), "State file should exist"
    assert (session_dir / "metadata.json").exists(), "Metadata file should exist"
    print(f"✓ Session files persisted: {session_dir}")

    # List sessions
    sessions = await session_mgr.list_sessions(user_id="test-user")
    assert len(sessions) == 1, "Should have 1 active session"
    print(f"✓ Session listed: {sessions[0]['domain']}")

    # Cleanup
    await session_mgr.shutdown()
    shutil.rmtree(test_dir)
    print(f"✓ Session manager shutdown successfully")


async def main():
    """Run all tests"""
    print("\n" + "#"*60)
    print("# HUMAN-ASSISTED WEB CRAWLING TEST SUITE")
    print("#"*60)

    try:
        await test_browser_fingerprint()
        await test_blocker_detection()
        await test_intervention_flow()
        await test_session_manager()

        print("\n" + "="*60)
        print("ALL TESTS PASSED ✓")
        print("="*60)
        print("\nHuman-assisted crawling system is ready to use!")
        print("\nNext steps:")
        print("1. Update internet.research tool to use human_assist_allowed parameter")
        print("2. Add intervention_handler.js to static/index.html")
        print("3. Add research_panel.css to static/index.html")
        print("4. Test with real CAPTCHA site")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
