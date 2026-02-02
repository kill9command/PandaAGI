#!/usr/bin/env python3
"""
Test the gateway API endpoint for CAPTCHA resolution.

This test verifies:
1. Orchestrator creates intervention
2. Gateway can retrieve it via /api/captchas/pending
3. Gateway can resolve it via POST /interventions/{id}/resolve
4. Returns proper 404 for unknown interventions
"""

import asyncio
import json
import requests
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from apps.services.orchestrator.captcha_intervention import (
    request_intervention,
    get_pending_intervention,
    remove_pending_intervention
)

GATEWAY_URL = "http://127.0.0.1:9000"


async def test_gateway_api():
    """Test the gateway API for CAPTCHA resolution."""
    print("=" * 60)
    print("Gateway CAPTCHA API Test")
    print("=" * 60)

    # Step 1: Create an intervention
    print("\n[1] Creating intervention via orchestrator...")
    intervention = await request_intervention(
        blocker_type="captcha_generic",
        url="https://www.google.com/sorry/index?test=api",
        screenshot_path="test_api_screenshot.png",
        session_id="test_api_session",
        blocker_details={"type": "captcha_generic", "confidence": 0.95}
    )

    intervention_id = intervention.intervention_id
    print(f"    ✓ Created intervention: {intervention_id}")

    # Step 2: Verify gateway can retrieve it
    print("\n[2] Retrieving pending interventions via gateway API...")
    response = requests.get(f"{GATEWAY_URL}/api/captchas/pending")

    if response.status_code == 200:
        data = response.json()
        interventions = data.get("interventions", [])
        found = any(i.get("intervention_id") == intervention_id for i in interventions)

        if found:
            print(f"    ✓ Gateway found intervention in pending list")
        else:
            print(f"    ✗ Gateway did not find intervention")
            print(f"    Pending interventions: {len(interventions)}")
            return False
    else:
        print(f"    ✗ Gateway returned {response.status_code}")
        return False

    # Step 3: Resolve it via gateway API
    print("\n[3] Resolving intervention via gateway API...")
    response = requests.post(
        f"{GATEWAY_URL}/interventions/{intervention_id}/resolve",
        json={"resolved": True}
    )

    if response.status_code == 200:
        data = response.json()
        print(f"    ✓ Gateway returned 200 OK")
        print(f"    Response: {data}")

        # Verify it's removed from queue file
        import os
        queue_file = "panda_system_docs/shared_state/captcha_queue.json"
        if os.path.exists(queue_file):
            with open(queue_file, 'r') as f:
                queue = json.load(f)
            found = any(i.get("intervention_id") == intervention_id for i in queue)
            if found:
                print(f"    ✗ Intervention still in queue file after resolution")
                return False
            else:
                print(f"    ✓ Intervention removed from queue file")
        else:
            print(f"    ✓ Queue file cleared")
    else:
        print(f"    ✗ Gateway returned {response.status_code}")
        print(f"    Response: {response.text}")
        return False

    # Step 4: Test 404 for unknown intervention
    print("\n[4] Testing 404 for unknown intervention...")
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = requests.post(
        f"{GATEWAY_URL}/interventions/{fake_id}/resolve",
        json={"resolved": True}
    )

    if response.status_code == 404:
        print(f"    ✓ Gateway returned 404 for unknown intervention")
        data = response.json()
        print(f"    Error message: {data.get('error')}")
    else:
        print(f"    ✗ Expected 404, got {response.status_code}")
        return False

    print("\n" + "=" * 60)
    print("✓ ALL GATEWAY API TESTS PASSED")
    print("=" * 60)
    return True


async def main():
    """Run the test."""
    try:
        success = await test_gateway_api()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ TEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
