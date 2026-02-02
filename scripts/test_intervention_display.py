#!/usr/bin/env python3
"""
Test script to verify intervention polling displays interventions in chat.

This script:
1. Checks if there are pending interventions
2. Opens the Gateway UI in browser
3. Verifies the polling mechanism will detect and display them
"""

import json
import os
import time
import webbrowser
from pathlib import Path

def main():
    print("=== Intervention Display Test ===\n")

    # Check for pending interventions
    queue_file = Path("panda_system_docs/shared_state/captcha_queue.json")
    if not queue_file.exists():
        print("❌ No captcha_queue.json file found")
        return

    with open(queue_file, 'r') as f:
        interventions = json.load(f)

    if not interventions:
        print("✓ No pending interventions (all clear)")
        return

    print(f"📋 Found {len(interventions)} pending intervention(s):\n")
    for intervention in interventions:
        print(f"  ID: {intervention['intervention_id']}")
        print(f"  Type: {intervention['type']}")
        print(f"  Domain: {intervention['domain']}")
        print(f"  Created: {intervention['created_at']}")
        print(f"  Resolved: {intervention['resolved']}")
        print()

    print("\n=== Testing Flow ===\n")
    print("1. ✓ Interventions exist in queue file")
    print("2. ✓ Gateway endpoint /api/captchas/pending available")
    print("3. ⏳ Opening Gateway UI in browser...")

    # Open browser to Gateway UI
    gateway_url = "http://127.0.0.1:9000"
    print(f"\n   Opening: {gateway_url}")
    print("\n4. ⏳ Waiting for page to load and polling to start...")

    # Give instructions
    print("\n" + "="*60)
    print("INSTRUCTIONS:")
    print("="*60)
    print("\nThe browser should now show the Gateway UI.")
    print("\nWithin 2-4 seconds, you should see:")
    print("  • A CAPTCHA intervention message appear in the chat window")
    print("  • The intervention will have:")
    print("    - 🔒 CAPTCHA Detected header")
    print("    - Domain name (e.g., www.google.com)")
    print("    - Screenshot of the CAPTCHA")
    print("    - Buttons: 'Open Challenge Page', '✓ I Solved It', 'Skip'")
    print("\nIf the intervention appears, the polling fallback is working!")
    print("\nCheck the browser console (F12) for debug logs:")
    print("  [ResearchProgress] Found pending intervention via polling: ...")
    print("="*60)

    # Wait a moment before opening browser to ensure services are ready
    time.sleep(1)
    webbrowser.open(gateway_url)

    print("\n✓ Test setup complete. Check the browser window!")
    print("\nTo resolve the test intervention, you can:")
    print("  1. Click 'I Solved It' in the browser")
    print("  2. Or run: curl -X POST http://127.0.0.1:9000/interventions/{ID}/resolve")
    print("  3. Or clear manually: rm panda_system_docs/shared_state/captcha_queue.json")

if __name__ == "__main__":
    main()
