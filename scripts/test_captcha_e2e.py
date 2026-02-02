#!/usr/bin/env python3
"""
End-to-end test simulating the full CAPTCHA resolution flow:
1. Research triggers CAPTCHA
2. Intervention created and waits
3. User solves CAPTCHA via gateway API
4. Research detects resolution and continues
"""

import asyncio
import json
import requests
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from apps.services.orchestrator.captcha_intervention import (
    request_intervention,
    get_pending_intervention
)

GATEWAY_URL = "http://127.0.0.1:9000"


async def simulate_research_with_captcha():
    """
    Simulate the full research flow with CAPTCHA resolution.
    """
    print("=" * 70)
    print("End-to-End CAPTCHA Resolution Test")
    print("=" * 70)

    # Step 1: Simulate research hitting CAPTCHA
    print("\n[1] Simulating research hitting CAPTCHA...")
    print("    (Normally: google search → CAPTCHA detected)")

    intervention = await request_intervention(
        blocker_type="captcha_generic",
        url="https://www.google.com/sorry/index?test=e2e",
        screenshot_path="panda_system_docs/research_screenshots/test_e2e.png",
        session_id="test_e2e_session",
        blocker_details={"type": "captcha_generic", "confidence": 0.95}
    )

    intervention_id = intervention.intervention_id
    print(f"    ✓ CAPTCHA detected and intervention created: {intervention_id}")

    # Step 2: Start waiting for resolution (in background task)
    print("\n[2] Research waiting for user to solve CAPTCHA...")
    print("    (Timeout: 20 seconds for this test)")

    async def research_wait_task():
        """Simulates orchestrator waiting for CAPTCHA resolution."""
        start = time.time()
        result = await intervention.wait_for_resolution(timeout=20)
        duration = time.time() - start

        return {
            "success": result,
            "duration": duration
        }

    wait_task = asyncio.create_task(research_wait_task())
    print("    ✓ Research is now waiting (polling every 2 seconds)...")

    # Step 3: Wait a bit, then simulate user solving CAPTCHA
    await asyncio.sleep(3)
    print("\n[3] Simulating user solving CAPTCHA via UI...")
    print("    (User clicks 'Solved' button → POST /interventions/{id}/resolve)")

    response = requests.post(
        f"{GATEWAY_URL}/interventions/{intervention_id}/resolve",
        json={"resolved": True}
    )

    if response.status_code == 200:
        data = response.json()
        print(f"    ✓ Gateway accepted resolution: {data}")
    else:
        print(f"    ✗ Gateway returned {response.status_code}: {response.text}")
        return False

    # Step 4: Wait for research to detect resolution
    print("\n[4] Waiting for research to detect resolution...")
    result = await wait_task

    if result["success"]:
        print(f"    ✓ Research detected resolution after {result['duration']:.1f}s!")
        print(f"    ✓ Research can now continue with search...")

        if result["duration"] < 5:
            print(f"    ✓ Detection was fast (<5s)")
        else:
            print(f"    ⚠️  Detection took {result['duration']:.1f}s (expected <5s)")
    else:
        print(f"    ✗ Research timed out after {result['duration']:.1f}s")
        return False

    # Step 5: Verify cleanup
    print("\n[5] Verifying cleanup...")
    queue_file = "panda_system_docs/shared_state/captcha_queue.json"
    if os.path.exists(queue_file):
        with open(queue_file, 'r') as f:
            queue = json.load(f)

        found = any(i.get("intervention_id") == intervention_id for i in queue)
        if found:
            print(f"    ⚠️  Intervention still in queue after resolution")
        else:
            print(f"    ✓ Intervention properly removed from queue")
    else:
        print(f"    ✓ Queue file cleared")

    print("\n" + "=" * 70)
    print("✅ END-TO-END TEST PASSED")
    print("=" * 70)
    print("\nSummary:")
    print(f"  • CAPTCHA detected and intervention created")
    print(f"  • User solved CAPTCHA via gateway API")
    print(f"  • Research detected resolution in {result['duration']:.1f}s")
    print(f"  • Search can continue (no 180s timeout!)")
    print("=" * 70)
    return True


async def main():
    """Run the e2e test."""
    try:
        success = await simulate_research_with_captcha()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ TEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
