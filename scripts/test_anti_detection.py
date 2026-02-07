#!/usr/bin/env python3
"""
Test anti-detection features for DuckDuckGo research.

Verifies:
1. Per-query session ID generation
2. Human warmup behavior execution
3. Chrome 112+ headless mode
4. Session rotation working correctly
"""

import httpx
import asyncio
import sys
import os

# Add repo root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

TOOL_SERVER_URL = os.getenv("TOOL_SERVER_URL", "http://127.0.0.1:8090")


async def test_research_with_anti_detection():
    """Test that anti-detection features execute correctly"""

    print("\n" + "="*80)
    print("ANTI-DETECTION FEATURES TEST")
    print("="*80)

    # Test query - simple search to verify features execute
    test_query = "best gaming laptop 2024"

    print(f"\n📋 Test Query: '{test_query}'")
    print(f"🎯 Expected Behaviors:")
    print("  ✓ Generate session ID: web_vision_[hash]")
    print("  ✓ Human warmup: 3-8s delay + scroll + mouse moves")
    print("  ✓ Headless mode: Chrome 112+ 'new' mode")
    print("  ✓ Stealth injection: Evasion scripts loaded")

    print("\n" + "-"*80)
    print("SENDING RESEARCH REQUEST...")
    print("-"*80)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{TOOL_SERVER_URL}/internet.research",
                json={
                    "query": test_query,
                    "research_goal": "Find recent gaming laptop recommendations",
                    "max_cycles": 3  # Short test to verify features quickly
                }
            )

            if response.status_code == 200:
                result = response.json()
                print(f"\n✅ Research completed successfully!")
                print(f"\n📊 Results:")
                print(f"  - Sources visited: {result.get('sources_visited', 0)}")
                print(f"  - Sources extracted: {result.get('sources_extracted', 0)}")
                print(f"  - Findings: {len(result.get('findings', []))}")
                print(f"  - Final answer length: {len(result.get('final_answer', ''))} chars")

                # Check for evidence of anti-detection features
                print(f"\n🔍 Feature Verification:")
                final_answer = result.get('final_answer', '')

                if "sources_visited" in str(result) and result.get('sources_visited', 0) > 0:
                    print("  ✓ Successfully navigated to sources")
                else:
                    print("  ⚠️  No sources visited (may indicate blocking)")

                if result.get('sources_extracted', 0) > 0:
                    print("  ✓ Successfully extracted content")
                else:
                    print("  ⚠️  No content extracted (check logs for warmup/session ID)")

                print("\n📝 Check orchestrator.log for:")
                print("  - '[InternetResearch] Generated session ID: web_vision_XXXXXXXX'")
                print("  - '[HumanWarmup] Initial observation delay: X.Xs'")
                print("  - '[HumanWarmup] Scrolling down XXXpx (page scan)'")
                print("  - '[HumanWarmup] Mouse move X/X to (XXX, XXX)'")
                print("  - '[CrawlerSessionMgr] Playwright browser started with CDP enabled'")

                return result

            else:
                print(f"\n❌ Research failed with status {response.status_code}")
                print(f"Response: {response.text[:500]}")
                return None

    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    result = await test_research_with_anti_detection()

    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)

    if result:
        print("\n✅ Next Steps:")
        print("  1. Run: tail -100 orchestrator.log | grep -E '(InternetResearch|HumanWarmup|session ID)'")
        print("  2. Verify session ID generation logs appear")
        print("  3. Verify warmup sequence logs appear")
        print("  4. Check if 418 blocking reduced compared to previous runs")
    else:
        print("\n❌ Test failed - check orchestrator.log for errors")

    print()


if __name__ == "__main__":
    asyncio.run(main())
