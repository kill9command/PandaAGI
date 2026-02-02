#!/usr/bin/env python3
"""
Manually resolve a CAPTCHA intervention.

Usage:
    python3 scripts/resolve_captcha.py <intervention_id> <action>

Where action is: solved, skipped, or cancelled
"""
import sys
sys.path.insert(0, '.')

import asyncio
from apps.services.orchestrator.captcha_intervention import get_pending_intervention, remove_pending_intervention

async def main():
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/resolve_captcha.py <intervention_id> <action>")
        print("  action: solved, skipped, or cancelled")
        sys.exit(1)

    intervention_id = sys.argv[1]
    action = sys.argv[2]

    if action not in ['solved', 'skipped', 'cancelled']:
        print(f"Error: Invalid action '{action}'. Must be: solved, skipped, or cancelled")
        sys.exit(1)

    # Get intervention
    intervention = get_pending_intervention(intervention_id)

    if not intervention:
        print(f"Error: Intervention '{intervention_id}' not found")
        print("\nRun 'python3 scripts/view_captchas.py' to see pending interventions")
        sys.exit(1)

    print(f"Resolving intervention: {intervention_id}")
    print(f"  Type: {intervention.intervention_type.value}")
    print(f"  URL: {intervention.url}")
    print(f"  Action: {action}")

    # Mark as resolved
    success = (action == "solved")
    intervention.mark_resolved(
        success=success,
        skip_reason=action if not success else None
    )

    # Clean up
    remove_pending_intervention(intervention_id)

    print(f"\n✅ Intervention marked as {action}")

if __name__ == "__main__":
    asyncio.run(main())
