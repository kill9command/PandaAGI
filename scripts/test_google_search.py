#!/usr/bin/env python3
"""
Test Google search with textarea selector fix
"""
import asyncio
import httpx


async def test_google_search():
    """Test if Google search works with new textarea selectors"""

    print("=" * 60)
    print("Testing Google Search with Textarea Selector Fix")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=90.0) as client:
        # Test Google search
        print("\nTest: Google search for 'hamster care'")
        print("-" * 60)

        try:
            response = await client.post(
                "http://127.0.0.1:8090/internet.research",
                json={
                    "query": "hamster care",
                    "research_goal": "Test if Google search works with textarea selector",
                    "max_cycles": 3,
                    "session_id": "google_test_session"
                }
            )

            result = response.json()

            print(f"\nStatus: {response.status_code}")
            print(f"Success: {result.get('success', False)}")

            if result.get("success"):
                print("\n✅ Google search WORKING!")

                # Show some results if available
                if "results" in result:
                    results = result["results"]
                    print(f"\nFound {len(results)} results:")
                    for i, res in enumerate(results[:3], 1):
                        title = res.get("title", "")[:60]
                        url = res.get("url", "")[:80]
                        print(f"{i}. {title}")
                        print(f"   {url}")

                if "summary" in result:
                    print(f"\nSummary: {result['summary'][:200]}...")
            else:
                print(f"\n❌ Google search FAILED")
                print(f"Error: {result.get('error', 'Unknown error')}")

                # Check for specific errors
                if "message" in result:
                    print(f"Message: {result['message']}")

        except httpx.TimeoutException:
            print("\n⏱️ Request timed out after 90 seconds")
            print("This may indicate the browser is still stuck finding elements")

        except Exception as e:
            print(f"\n❌ Test failed with exception: {e}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(test_google_search())
