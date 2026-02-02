#!/usr/bin/env python3
import json
import hashlib

# Original fingerprint generation (pre-fix)
def original_fingerprint(session_context):
    fp_str = (
        f"{session_context.get('session_id', 'unknown')}:"
        f"{session_context.get('preferences', {})}:"  # Dict str representation
        f"{session_context.get('domain', '')}"        # Volatile from extract_topic()
    )
    return hashlib.md5(fp_str.encode()).hexdigest()[:16]

# New fingerprint generation (post-fix)
def new_fingerprint(session_context):
    prefs = session_context.get('preferences', {})
    sorted_prefs = json.dumps(prefs, sort_keys=True) if prefs else "{}"

    fp_str = (
        f"{session_context.get('session_id', 'unknown')}:"
        f"{sorted_prefs}"  # REMOVED domain to avoid volatility
    )
    return hashlib.md5(fp_str.encode()).hexdigest()[:16]

# Test with different scenarios
test_cases = [
    {
        "name": "Cache hit scenario (from transcript)",
        "context": {
            "session_id": "henry",
            "preferences": {
                "budget": "online search for sale items",
                "location": "online",
                "favorite_hamster_breed": "Syrian hamster"
            },
            "domain": "shopping for hamsters online"
        }
    },
    {
        "name": "Current scenario (from henry.json)",
        "context": {
            "session_id": "henry",
            "preferences": {
                "budget": "online search for sale items",
                "location": "online",
                "favorite_hamster_breed": "Syrian hamster"
            },
            "domain": "shopping for Syrian hamsters"
        }
    },
    {
        "name": "Empty preferences",
        "context": {
            "session_id": "henry",
            "preferences": {},
            "domain": "shopping for Syrian hamsters"
        }
    },
    {
        "name": "Different preference order",
        "context": {
            "session_id": "henry",
            "preferences": {
                "favorite_hamster_breed": "Syrian hamster",
                "budget": "online search for sale items",
                "location": "online"
            },
            "domain": "shopping for hamsters online"
        }
    }
]

print("FINGERPRINT ANALYSIS")
print("=" * 60)

# Expected fingerprint from cache
expected_fp = "60aee7a9a1645bad"
print(f"Expected fingerprint (from cache): {expected_fp}")
print()

for tc in test_cases:
    print(f"Test Case: {tc['name']}")
    print(f"  Preferences: {tc['context'].get('preferences')}")
    print(f"  Domain: {tc['context'].get('domain')}")

    orig_fp = original_fingerprint(tc['context'])
    new_fp = new_fingerprint(tc['context'])

    print(f"  Original FP: {orig_fp} {'✓ MATCH' if orig_fp == expected_fp else '✗ MISS'}")
    print(f"  New FP:      {new_fp} {'✓ MATCH' if new_fp == expected_fp else '✗ MISS'}")
    print()

print("\nDEBUG DETAILS:")
print("=" * 60)

# Show exact string that creates the expected fingerprint
for tc in test_cases[:2]:
    print(f"\nContext: {tc['name']}")

    # Original method
    fp_str_orig = (
        f"{tc['context'].get('session_id', 'unknown')}:"
        f"{tc['context'].get('preferences', {})}:"
        f"{tc['context'].get('domain', '')}"
    )
    print(f"Original fp_str: {fp_str_orig[:100]}...")
    print(f"Original hash: {hashlib.md5(fp_str_orig.encode()).hexdigest()[:16]}")

    # New method
    prefs = tc['context'].get('preferences', {})
    sorted_prefs = json.dumps(prefs, sort_keys=True) if prefs else "{}"
    fp_str_new = (
        f"{tc['context'].get('session_id', 'unknown')}:"
        f"{sorted_prefs}"
    )
    print(f"New fp_str: {fp_str_new[:100]}...")
    print(f"New hash: {hashlib.md5(fp_str_new.encode()).hexdigest()[:16]}")