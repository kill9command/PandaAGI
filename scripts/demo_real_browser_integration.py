#!/usr/bin/env python3
"""
Demo: Real Browser Integration

Shows how to use the complete "human-like browser automation" system.

Before running:
1. Start Chrome with debugging:
   google-chrome --remote-debugging-port=9222

2. Run this script:
   python3 scripts/demo_real_browser_integration.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.services.orchestrator.real_browser_connector import connect_to_user_browser
from apps.services.orchestrator.browser_task_runtime import (
    execute_browser_task,
    BrowserAction,
    ActionType
)


async def demo_google_search():
    """
    Demo 1: Simple Google search using real browser.

    This demonstrates:
    - Connecting to user's real Chrome
    - Vision-based element finding
    - Human-like typing
    - Task execution with retries
    """
    print("=" * 70)
    print("DEMO 1: Google Search with Real Browser")
    print("=" * 70)

    try:
        # Connect to user's Chrome
        print("\n→ Connecting to your Chrome browser...")
        browser, page = await connect_to_user_browser()
        print(f"✓ Connected! Currently on: {page.url}")

        # Define task as sequence of actions
        actions = [
            BrowserAction(
                type=ActionType.NAVIGATE,
                params={"url": "https://www.google.com"},
                description="Navigate to Google"
            ),

            BrowserAction(
                type=ActionType.WAIT,
                params={"seconds": 2},
                description="Wait for page load"
            ),

            BrowserAction(
                type=ActionType.TYPE,
                params={
                    "text": "hamster care guide",
                    "into": "search"
                },
                description="Type search query (human-like typing)"
            ),

            BrowserAction(
                type=ActionType.WAIT,
                params={"seconds": 1},
                description="Pause before submitting"
            ),

            BrowserAction(
                type=ActionType.PRESS_KEY,
                params={"key": "Enter"},
                description="Press Enter to search"
            ),

            BrowserAction(
                type=ActionType.WAIT,
                params={"seconds": 3},
                description="Wait for search results"
            ),
        ]

        # Execute task
        print("\n→ Executing task...")
        result = await execute_browser_task(
            page=page,
            actions=actions,
            session_id="demo_search",
            task_description="Search Google for hamster care guide"
        )

        # Show results
        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)
        print(f"Success: {result.success}")
        print(f"Actions completed: {result.actions_completed}/{result.actions_completed + result.actions_failed}")
        print(f"Execution time: {result.execution_time_seconds:.1f}s")
        print(f"Human interventions: {result.human_interventions}")

        if result.error:
            print(f"Error: {result.error}")

        final_url = page.url
        if "/sorry/" in final_url:
            print("\n⚠️  Google showed CAPTCHA page")
            print("   In production, system would pause for human to solve it")
        elif "search?q=" in final_url:
            print("\n✓ Successfully reached search results!")
            print(f"   Final URL: {final_url[:80]}...")

    except Exception as e:
        print(f"\n✗ Demo failed: {e}")
        print("\nMake sure Chrome is running with:")
        print("  google-chrome --remote-debugging-port=9222")


async def demo_data_extraction():
    """
    Demo 2: Navigate to site and extract data.

    This demonstrates:
    - Visual data extraction
    - Scrolling behavior
    - Multi-step workflows
    """
    print("\n\n" + "=" * 70)
    print("DEMO 2: Navigate and Extract Data")
    print("=" * 70)

    try:
        print("\n→ Connecting to your Chrome browser...")
        browser, page = await connect_to_user_browser()

        actions = [
            BrowserAction(
                type=ActionType.NAVIGATE,
                params={"url": "https://news.ycombinator.com"},
                description="Go to Hacker News"
            ),

            BrowserAction(
                type=ActionType.WAIT,
                params={"seconds": 2},
                description="Wait for page load"
            ),

            BrowserAction(
                type=ActionType.SCREENSHOT,
                params={"path": "/tmp/hackernews_demo.png"},
                description="Take screenshot"
            ),

            BrowserAction(
                type=ActionType.SCROLL,
                params={"direction": "down", "amount": 500},
                description="Scroll down"
            ),

            BrowserAction(
                type=ActionType.WAIT,
                params={"seconds": 1}
            ),
        ]

        print("\n→ Executing task...")
        result = await execute_browser_task(
            page=page,
            actions=actions,
            session_id="demo_extraction",
            task_description="Visit Hacker News and scroll"
        )

        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)
        print(f"Success: {result.success}")
        print(f"Actions completed: {result.actions_completed}")
        print(f"Final URL: {page.url}")

        if result.success:
            print("\n✓ Successfully navigated and scrolled")
            print("  Screenshot saved: /tmp/hackernews_demo.png")

    except Exception as e:
        print(f"\n✗ Demo failed: {e}")


async def demo_human_intervention():
    """
    Demo 3: Task that requires human intervention.

    This demonstrates:
    - Automatic detection of intervention needs
    - Pausing for human input
    - Resuming after intervention
    """
    print("\n\n" + "=" * 70)
    print("DEMO 3: Human Intervention Handling")
    print("=" * 70)

    try:
        print("\n→ Connecting to your Chrome browser...")
        browser, page = await connect_to_user_browser()

        actions = [
            BrowserAction(
                type=ActionType.NAVIGATE,
                params={"url": "https://example.com"},
                description="Navigate to example site"
            ),

            BrowserAction(
                type=ActionType.WAIT,
                params={"seconds": 1}
            ),

            BrowserAction(
                type=ActionType.HUMAN_INTERVENTION,
                params={"reason": "Demo: Simulating CAPTCHA or login"},
                description="Request human intervention"
            ),

            BrowserAction(
                type=ActionType.SCREENSHOT,
                params={"path": "/tmp/after_intervention.png"},
                description="Take screenshot after intervention"
            ),
        ]

        print("\n→ Executing task...")
        print("   (This will timeout after 5 min if no intervention)")

        result = await execute_browser_task(
            page=page,
            actions=actions,
            session_id="demo_intervention",
            task_description="Demo human intervention workflow"
        )

        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)
        print(f"Success: {result.success}")
        print(f"Human interventions: {result.human_interventions}")

    except Exception as e:
        print(f"\n✗ Demo failed: {e}")


async def main():
    """Run all demos"""

    print("\n" + "#" * 70)
    print("# Real Browser Integration Demonstration")
    print("#" * 70)
    print("\nThis demonstrates the complete 'human-like browser automation' system.")
    print("\nPrerequisite: Chrome must be running with remote debugging:")
    print("  google-chrome --remote-debugging-port=9222")
    print("\nPress Ctrl+C to skip any demo\n")

    try:
        # Demo 1: Basic search
        await demo_google_search()

        # Demo 2: Data extraction
        await demo_data_extraction()

        # Demo 3: Human intervention (commented out to avoid timeout)
        # await demo_human_intervention()

    except KeyboardInterrupt:
        print("\n\n✓ Demos interrupted by user")

    print("\n" + "#" * 70)
    print("# Demos Complete")
    print("#" * 70)
    print("\nFor integration details, see: REAL_BROWSER_INTEGRATION.md")
    print()


if __name__ == "__main__":
    asyncio.run(main())
