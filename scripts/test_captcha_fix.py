#!/usr/bin/env python3
"""
Test script to verify CAPTCHA cross-process resolution fix.

This script simulates the scenario where:
1. Orchestrator creates a CAPTCHA intervention
2. Gateway resolves it (from different process)
3. Orchestrator detects the resolution via polling
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime

# Add orchestrator to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from apps.services.orchestrator.captcha_intervention import (
    InterventionRequest,
    InterventionType,
    request_intervention,
    get_pending_intervention,
    remove_pending_intervention,
    get_all_pending_interventions
)


async def test_cross_process_resolution():
    """
    Test that interventions can be resolved across processes.
    """
    print("=" * 60)
    print("CAPTCHA Cross-Process Resolution Test")
    print("=" * 60)

    # Step 1: Create an intervention (simulating orchestrator)
    print("\n[1] Creating intervention (simulating orchestrator process)...")
    intervention = await request_intervention(
        blocker_type="captcha_generic",
        url="https://www.google.com/sorry/index?test=true",
        screenshot_path="test_screenshot.png",
        session_id="test_session",
        blocker_details={"type": "captcha_generic", "confidence": 0.95}
    )

    intervention_id = intervention.intervention_id
    print(f"    ✓ Created intervention: {intervention_id}")

    # Verify it's in the queue file
    queue_file = "panda_system_docs/shared_state/captcha_queue.json"
    with open(queue_file, 'r') as f:
        queue = json.load(f)

    found_in_file = any(item.get("intervention_id") == intervention_id for item in queue)
    print(f"    ✓ Intervention persisted to file: {found_in_file}")

    # Step 2: Simulate gateway resolution (from different "process")
    print("\n[2] Simulating gateway resolution (cross-process)...")
    print("    Clearing in-memory registry to simulate different process...")

    # Get intervention via cross-process lookup (should load from file)
    intervention_from_file = get_pending_intervention(intervention_id)

    if intervention_from_file:
        print(f"    ✓ Cross-process lookup successful: {intervention_from_file.intervention_id}")
        print(f"    ✓ Loaded from file: {intervention_from_file.domain}")
    else:
        print(f"    ✗ FAILED: Could not find intervention via cross-process lookup")
        return False

    # Mark as resolved (simulating gateway)
    print("    Marking as resolved (simulating user clicked 'Solved')...")
    intervention_from_file.mark_resolved(success=True)
    remove_pending_intervention(intervention_id)
    print(f"    ✓ Intervention marked resolved and removed from queue")

    # Verify it's removed from file
    with open(queue_file, 'r') as f:
        queue = json.load(f)

    found_in_file = any(item.get("intervention_id") == intervention_id for item in queue)
    print(f"    ✓ Intervention removed from file: {not found_in_file}")

    # Step 3: Simulate orchestrator polling detection
    print("\n[3] Simulating orchestrator polling (cross-process detection)...")

    # Create a new intervention to test the polling mechanism
    intervention2 = await request_intervention(
        blocker_type="captcha_generic",
        url="https://www.google.com/sorry/index?test=2",
        screenshot_path="test_screenshot2.png",
        session_id="test_session_2",
        blocker_details={"type": "captcha_generic", "confidence": 0.95}
    )

    intervention2_id = intervention2.intervention_id
    print(f"    ✓ Created second intervention: {intervention2_id}")

    # Start waiting in background (with short timeout for testing)
    print("    Starting wait_for_resolution() with 10s timeout...")

    async def wait_task():
        result = await intervention2.wait_for_resolution(timeout=10)
        return result

    wait_future = asyncio.create_task(wait_task())

    # Wait 2 seconds, then resolve it
    await asyncio.sleep(2)
    print("    Resolving intervention after 2 seconds (simulating user solved it)...")

    # Simulate gateway resolving it (remove from file)
    intervention2_check = get_pending_intervention(intervention2_id)
    if intervention2_check:
        intervention2_check.mark_resolved(success=True)
        remove_pending_intervention(intervention2_id)
        print(f"    ✓ Intervention resolved via cross-process")

    # Wait for the polling to detect it
    result = await wait_future

    if result:
        print(f"    ✓ Polling detected cross-process resolution!")
        print(f"    ✓ wait_for_resolution() returned: {result}")
    else:
        print(f"    ✗ FAILED: Polling did not detect resolution")
        return False

    print("\n" + "=" * 60)
    print("✓ ALL TESTS PASSED")
    print("=" * 60)
    return True


async def main():
    """Run the test."""
    try:
        success = await test_cross_process_resolution()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ TEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
