"""
End-to-end test for human-assisted web crawling integration.

Tests the complete flow from API request through tool execution.
"""

import asyncio
import aiohttp
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_orchestrator_endpoint():
    """Test that orchestrator endpoint accepts new parameters"""
    print("\n" + "="*60)
    print("TEST 1: Orchestrator Endpoint Integration")
    print("="*60)

    url = "http://127.0.0.1:8090/internet.research"

    # Test with human_assist_allowed disabled (default behavior)
    payload1 = {
        "query": "hamster care guide",
        "intent": "informational",
        "max_results": 3,
        "human_assist_allowed": False,
        "session_id": "test-e2e-session"
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload1, timeout=aiohttp.ClientTimeout(total=60)) as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✓ Orchestrator endpoint accepts human_assist_allowed parameter")
                    print(f"  Status: {result.get('status')}")
                    print(f"  Results found: {len(result.get('results', []))}")

                    # Check stats for new fields
                    stats = result.get('stats', {})
                    if 'human_assist_enabled' in stats:
                        print(f"✓ Stats include human_assist_enabled: {stats['human_assist_enabled']}")
                    if 'interventions_requested' in stats:
                        print(f"✓ Stats include interventions_requested: {stats['interventions_requested']}")
                    if 'interventions_resolved' in stats:
                        print(f"✓ Stats include interventions_resolved: {stats['interventions_resolved']}")
                else:
                    print(f"❌ Request failed with status {response.status}")
                    text = await response.text()
                    print(f"   Response: {text}")
                    return False

        except asyncio.TimeoutError:
            print(f"❌ Request timed out after 60s")
            return False
        except Exception as e:
            print(f"❌ Request failed: {e}")
            return False

    return True


async def test_gateway_endpoints():
    """Test that gateway endpoints are accessible"""
    print("\n" + "="*60)
    print("TEST 2: Gateway Intervention Endpoints")
    print("="*60)

    async with aiohttp.ClientSession() as session:
        # Test pending interventions endpoint
        try:
            async with session.get("http://127.0.0.1:9000/interventions/pending") as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✓ /interventions/pending endpoint accessible")
                    print(f"  Pending interventions: {len(result.get('interventions', []))}")
                else:
                    print(f"❌ /interventions/pending returned {response.status}")
                    return False
        except Exception as e:
            print(f"❌ Failed to access /interventions/pending: {e}")
            return False

        # Test crawler sessions endpoint
        try:
            async with session.get("http://127.0.0.1:9000/crawl/sessions?user_id=test") as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✓ /crawl/sessions endpoint accessible")
                    print(f"  Active sessions: {len(result.get('sessions', []))}")
                else:
                    print(f"❌ /crawl/sessions returned {response.status}")
                    return False
        except Exception as e:
            print(f"❌ Failed to access /crawl/sessions: {e}")
            return False

        # Test intervention stats endpoint
        try:
            async with session.get("http://127.0.0.1:9000/debug/intervention-stats") as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✓ /debug/intervention-stats endpoint accessible")
                    print(f"  Total interventions: {result.get('total_interventions', 0)}")
                    print(f"  Resolved: {result.get('resolved_interventions', 0)}")
                else:
                    print(f"❌ /debug/intervention-stats returned {response.status}")
                    return False
        except Exception as e:
            print(f"❌ Failed to access /debug/intervention-stats: {e}")
            return False

    return True


async def test_session_manager_initialization():
    """Test that session manager initializes correctly"""
    print("\n" + "="*60)
    print("TEST 3: Session Manager Initialization")
    print("="*60)

    try:
        from apps.services.tool_server.crawler_session_manager import get_crawler_session_manager

        mgr = get_crawler_session_manager()
        print(f"✓ Session manager singleton accessible")
        print(f"  Base directory: {mgr.base_dir}")
        print(f"  Default TTL: {mgr.default_ttl_hours}h")

        # List sessions
        sessions = await mgr.list_sessions(user_id="test")
        print(f"✓ Can list sessions: {len(sessions)} active")

        return True

    except Exception as e:
        print(f"❌ Session manager initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_ui_files_exist():
    """Test that UI files are present"""
    print("\n" + "="*60)
    print("TEST 4: UI Files Present")
    print("="*60)

    files_to_check = [
        "static/intervention_handler.js",
        "static/research_panel.css",
        "static/index.html"
    ]

    all_exist = True
    for file_path in files_to_check:
        path = Path(file_path)
        if path.exists():
            print(f"✓ {file_path} exists ({path.stat().st_size} bytes)")
        else:
            print(f"❌ {file_path} not found")
            all_exist = False

    # Check that index.html includes the new files
    index_html = Path("static/index.html").read_text()
    if "intervention_handler.js" in index_html:
        print(f"✓ index.html includes intervention_handler.js")
    else:
        print(f"❌ index.html missing intervention_handler.js")
        all_exist = False

    if "research_panel.css" in index_html:
        print(f"✓ index.html includes research_panel.css")
    else:
        print(f"❌ index.html missing research_panel.css")
        all_exist = False

    return all_exist


async def main():
    """Run all end-to-end tests"""
    print("\n" + "#"*60)
    print("# HUMAN-ASSISTED WEB CRAWLING - E2E TEST SUITE")
    print("#"*60)

    results = []

    try:
        # Test 1: Orchestrator endpoint
        result1 = await test_orchestrator_endpoint()
        results.append(("Orchestrator Endpoint", result1))

        # Test 2: Gateway endpoints
        result2 = await test_gateway_endpoints()
        results.append(("Gateway Endpoints", result2))

        # Test 3: Session manager
        result3 = await test_session_manager_initialization()
        results.append(("Session Manager", result3))

        # Test 4: UI files
        result4 = await test_ui_files_exist()
        results.append(("UI Files", result4))

        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)

        all_passed = True
        for test_name, passed in results:
            status = "✓ PASSED" if passed else "❌ FAILED"
            print(f"{test_name}: {status}")
            if not passed:
                all_passed = False

        if all_passed:
            print("\n" + "="*60)
            print("ALL E2E TESTS PASSED ✓")
            print("="*60)
            print("\nHuman-assisted crawling is fully integrated!")
            print("\nTo test with a real CAPTCHA site:")
            print("1. Use the Gateway web UI at http://127.0.0.1:9000")
            print("2. Send a research query")
            print("3. If a CAPTCHA is detected, the intervention modal will appear")
            print("4. Solve the CAPTCHA manually")
            print("5. Click 'Resolved' to continue")
            return 0
        else:
            print("\n" + "="*60)
            print("SOME TESTS FAILED ❌")
            print("="*60)
            return 1

    except Exception as e:
        print(f"\n❌ E2E TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
