#!/usr/bin/env python3
"""
Direct test of Google search box typing
"""
import asyncio
import httpx


async def test_google_typing():
    """Test if we can type into Google's search box"""

    print("=" * 60)
    print("Direct Test: Google Search Box Typing")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=30.0) as client:
        session_id = "google_direct_test"

        # Step 1: Navigate to Google
        print("\nStep 1: Navigating to Google...")
        response = await client.post(
            "http://127.0.0.1:8090/web.navigate",
            json={
                "url": "https://www.google.com",
                "session_id": session_id,
                "wait_for": "networkidle"
            }
        )
        print(f"Navigate result: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
            return

        # Step 2: Get screen state to verify Google loaded
        print("\nStep 2: Getting screen state...")
        response = await client.post(
            "http://127.0.0.1:8090/web.get_screen_state",
            json={"session_id": session_id}
        )
        result = response.json()
        page_info = result.get('page_info', {}) or {}
        print(f"Page title: {page_info.get('title', 'N/A')}")
        print(f"URL: {page_info.get('url', 'N/A')}")

        # Step 3: Type into search box
        print("\nStep 3: Typing 'hamster care' into search box...")
        response = await client.post(
            "http://127.0.0.1:8090/web.type_text",
            json={
                "text": "hamster care",
                "into": "search input field",
                "session_id": session_id
            }
        )
        print(f"Type result: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
            result = response.json()
            print(f"Details: {result}")
        else:
            print("✅ Typing successful!")

        # Step 4: Get screen state again to verify typing worked
        print("\nStep 4: Getting screen state after typing...")
        response = await client.post(
            "http://127.0.0.1:8090/web.get_screen_state",
            json={"session_id": session_id}
        )
        result = response.json()
        page_info = result.get('page_info', {}) or {}
        print(f"Page title: {page_info.get('title', 'N/A')}")
        print(f"URL: {page_info.get('url', 'N/A')}")

        # Step 5: Press Enter to search
        print("\nStep 5: Pressing Enter to search...")
        response = await client.post(
            "http://127.0.0.1:8090/web.press_key",
            json={
                "key": "Enter",
                "session_id": session_id
            }
        )
        print(f"Press key result: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
        else:
            print("✅ Enter key pressed!")

        # Step 6: Wait a bit and check if we're on search results
        await asyncio.sleep(3)
        print("\nStep 6: Getting final screen state...")
        response = await client.post(
            "http://127.0.0.1:8090/web.get_screen_state",
            json={"session_id": session_id}
        )
        result = response.json()
        page_info = result.get('page_info', {}) or {}
        final_url = page_info.get('url', '')
        print(f"Final URL: {final_url}")
        print(f"Page title: {page_info.get('title', 'N/A')}")

        if "search?q=" in final_url or "search?q=" in final_url.lower():
            print("\n✅ SUCCESS: Reached Google search results page!")
        else:
            print("\n❌ FAILED: Did not reach search results page")
            print("This suggests typing or Enter key didn't work")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(test_google_typing())
