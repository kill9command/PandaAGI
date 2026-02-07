#!/usr/bin/env python3
"""
View pending CAPTCHA interventions and resolve them.

Shows all pending CAPTCHAs and provides simple interface to mark them as solved/skipped.
"""
import sys
sys.path.insert(0, '.')

import json
import os
from datetime import datetime
from pathlib import Path

def load_captcha_queue():
    """Load pending interventions from shared storage"""
    queue_file = Path("panda_system_docs/shared_state/captcha_queue.json")

    if not queue_file.exists():
        return []

    try:
        with open(queue_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading CAPTCHA queue: {e}")
        return []

def format_intervention(intervention, index):
    """Format intervention for display"""
    created = intervention.get("created_at", "unknown")
    if created != "unknown":
        try:
            dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
            created = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            pass

    print(f"\n{'='*80}")
    print(f"[{index}] CAPTCHA Intervention")
    print(f"{'='*80}")
    print(f"  ID: {intervention.get('intervention_id')}")
    print(f"  Type: {intervention.get('type', 'unknown')}")
    print(f"  URL: {intervention.get('url')}")
    print(f"  Domain: {intervention.get('domain')}")
    print(f"  Session: {intervention.get('session_id')}")
    print(f"  Created: {created}")

    screenshot = intervention.get('screenshot_path')
    if screenshot:
        print(f"  Screenshot: {screenshot}")
        if os.path.exists(screenshot):
            print(f"    ✅ File exists ({os.path.getsize(screenshot)} bytes)")
        else:
            print(f"    ❌ File not found")

    cdp_url = intervention.get('cdp_url')
    if cdp_url:
        print(f"\n  🌐 Browser DevTools URL:")
        print(f"     chrome://inspect")
        print(f"     Then click 'inspect' on: {cdp_url}")

    details = intervention.get('blocker_details', {})
    if details:
        indicators = details.get('indicators', [])
        confidence = details.get('confidence', 0)
        print(f"\n  Detection confidence: {confidence:.0%}")
        if indicators:
            print(f"  Indicators:")
            for ind in indicators:
                print(f"    - {ind}")

    print(f"{'='*80}")

def main():
    """Main entry point"""
    print("\n" + "="*80)
    print("CAPTCHA Intervention Viewer")
    print("="*80)

    interventions = load_captcha_queue()

    if not interventions:
        print("\n✅ No pending CAPTCHA interventions")
        print("\nTo test the system:")
        print("  1. Make sure PLAYWRIGHT_HEADLESS=false in .env")
        print("  2. Run a search that triggers a CAPTCHA")
        print("  3. The browser window will appear for you to solve it")
        print("  4. After solving, the search continues automatically")
        return

    print(f"\n⚠️  Found {len(interventions)} pending intervention(s)\n")

    for i, intervention in enumerate(interventions, 1):
        format_intervention(intervention, i)

    print("\n" + "="*80)
    print("HOW TO SOLVE CAPTCHAS:")
    print("="*80)
    print("""
1. A visible browser window should already be open (if not, check PLAYWRIGHT_HEADLESS=false)

2. Connect to the browser using Chrome DevTools Protocol:
   - Open: chrome://inspect
   - Click "inspect" on the remote target
   - OR use the CDP URL shown above

3. Solve the CAPTCHA in the browser window

4. The system will automatically detect when you've solved it and continue

5. If the browser window is not visible:
   - Check .env for PLAYWRIGHT_HEADLESS=false
   - Restart services: ./stop.sh && ./start.sh

ALTERNATIVE: Browser Window Method
-----------------------------------
If PLAYWRIGHT_HEADLESS=false is set, you should see a visible Chrome window.
Just switch to it and solve the CAPTCHA directly - no need for DevTools!
""")

    print("\n" + "="*80)
    print("MANUAL RESOLUTION (if needed):")
    print("="*80)
    print("""
If you need to manually mark interventions as resolved:

    python3 scripts/resolve_captcha.py <intervention_id> solved

Or to skip:

    python3 scripts/resolve_captcha.py <intervention_id> skipped
""")

if __name__ == "__main__":
    main()
