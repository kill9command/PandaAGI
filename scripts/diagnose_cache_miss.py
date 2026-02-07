"""
Diagnostic script to understand why cache search is failing.

Checks:
1. What fingerprints are in the index
2. What preferences structure is being used
3. What session_ids exist
4. Simulate actual cache search
"""
import json
import hashlib
from pathlib import Path

def new_fingerprint(session_context: dict) -> str:
    """Same as response_cache.py"""
    prefs = session_context.get('preferences', {})
    sorted_prefs = json.dumps(prefs, sort_keys=True) if prefs else "{}"

    fp_str = (
        f"{session_context.get('session_id', 'unknown')}:"
        f"{sorted_prefs}"
    )
    return hashlib.md5(fp_str.encode()).hexdigest()[:16]

def legacy_fingerprint(session_context: dict) -> str:
    """Same as response_cache.py legacy"""
    fp_str = (
        f"{session_context.get('session_id', 'unknown')}:"
        f"{session_context.get('preferences', {})}:"
        f"{session_context.get('domain', '')}"
    )
    return hashlib.md5(fp_str.encode()).hexdigest()[:16]

def diagnose():
    cache_dir = Path("/path/to/pandaagi/panda_system_docs/shared_state/response_cache")

    print("=" * 80)
    print("CACHE DIAGNOSTIC REPORT")
    print("=" * 80)
    print()

    # Load index
    index_path = cache_dir / "index.json"
    with open(index_path, 'r') as f:
        index = json.load(f)

    print(f"INDEX: Found {len(index)} fingerprints")
    print()

    # Analyze each fingerprint
    print("=" * 80)
    print("CACHED ENTRIES BY SESSION")
    print("=" * 80)

    session_groups = {}

    for fp, response_ids in index.items():
        # Load first response to get session info
        response_file = cache_dir / f"{response_ids[0]}.json"
        if not response_file.exists():
            continue

        with open(response_file, 'r') as f:
            entry = json.load(f)

        session_id = entry.get("session_id", "unknown")
        if session_id not in session_groups:
            session_groups[session_id] = []

        session_groups[session_id].append({
            "fingerprint": fp,
            "response_ids": response_ids,
            "query": entry.get("query", ""),
            "intent": entry.get("intent", ""),
            "domain": entry.get("domain", ""),
            "context_fp": entry.get("context_fingerprint", "")
        })

    for session_id, entries in session_groups.items():
        print(f"\nSession ID: {session_id}")
        print(f"  Entries: {len(entries)}")
        for entry in entries[:3]:  # Show first 3
            print(f"    - Query: '{entry['query'][:60]}...'")
            print(f"      FP: {entry['fingerprint']}, Intent: {entry['intent']}, Domain: {entry['domain'][:40]}")
        if len(entries) > 3:
            print(f"    ... and {len(entries) - 3} more")

    print()
    print("=" * 80)
    print("TEST SCENARIOS")
    print("=" * 80)

    # Test Scenario 1: User with "default" session, no preferences
    print("\nScenario 1: session=default, no preferences")
    ctx1 = {
        "session_id": "default",
        "preferences": {},
        "domain": "general"
    }
    fp1_new = new_fingerprint(ctx1)
    fp1_legacy = legacy_fingerprint(ctx1)
    print(f"  New FP:    {fp1_new}")
    print(f"  Legacy FP: {fp1_legacy}")
    print(f"  In index (new):    {fp1_new in index}")
    print(f"  In index (legacy): {fp1_legacy in index}")

    if fp1_new in index:
        print(f"  ✓ Found entries: {index[fp1_new]}")

    # Test Scenario 2: User with Syrian hamster preference
    print("\nScenario 2: session=default, favorite_hamster_breed=Syrian hamster")
    ctx2 = {
        "session_id": "default",
        "preferences": {"favorite_hamster_breed": "Syrian hamster"},
        "domain": "shopping"
    }
    fp2_new = new_fingerprint(ctx2)
    fp2_legacy = legacy_fingerprint(ctx2)
    print(f"  New FP:    {fp2_new}")
    print(f"  Legacy FP: {fp2_legacy}")
    print(f"  In index (new):    {fp2_new in index}")
    print(f"  In index (legacy): {fp2_legacy in index}")

    if fp2_new in index:
        print(f"  ✓ Found entries: {index[fp2_new]}")

    # Test Scenario 3: Check first actual cached entry
    print("\nScenario 3: Reverse-engineer first cache entry")
    first_entry_file = cache_dir / "02d52475bfd8c962.json"
    if first_entry_file.exists():
        with open(first_entry_file, 'r') as f:
            first_entry = json.load(f)

        print(f"  Query: '{first_entry['query']}'")
        print(f"  Session ID: {first_entry['session_id']}")
        print(f"  Domain: {first_entry['domain']}")
        print(f"  Context FP (stored): {first_entry['context_fingerprint']}")

        # Try to reverse-engineer what preferences would generate this FP
        # We know: session_id = "default", preferences = ???
        # Try empty preferences
        test_ctx = {
            "session_id": first_entry["session_id"],
            "preferences": {},
            "domain": first_entry["domain"]
        }
        test_fp = new_fingerprint(test_ctx)
        print(f"  Test FP (empty prefs): {test_fp}")
        print(f"  Match: {test_fp == first_entry['context_fingerprint']}")

    print()
    print("=" * 80)
    print("INDEX LOOKUP SIMULATION")
    print("=" * 80)

    # Simulate what happens when Gateway calls cache search
    print("\nSimulating Gateway cache search:")
    print("  User query: 'can you find some for sale?'")
    print("  Intent: transactional")
    print("  Session context from test trace:")

    # From the test summary, we know the user said "Syrian hamster is my favorite"
    # This should set a preference. Let's check what preference key was used.

    # Check all cached entries to see what preference keys exist
    print()
    print("Checking what preference structures exist in cache:")
    seen_prefs = set()
    for fp, response_ids in list(index.items())[:5]:  # Check first 5
        response_file = cache_dir / f"{response_ids[0]}.json"
        if response_file.exists():
            with open(response_file, 'r') as f:
                entry = json.load(f)

            # Try to extract preferences from context_fingerprint
            # This is hard to do in reverse, so let's just show the stored FP
            print(f"\n  Entry: '{entry['query'][:50]}...'")
            print(f"    Stored context_fingerprint: {entry['context_fingerprint']}")
            print(f"    Session: {entry['session_id']}")

            # Try empty preferences
            test_empty = {
                "session_id": entry["session_id"],
                "preferences": {},
            }
            fp_empty = new_fingerprint(test_empty)
            if fp_empty == entry["context_fingerprint"]:
                print(f"    → Preferences: EMPTY ✓")
                seen_prefs.add("empty")
            else:
                print(f"    → Preferences: NOT EMPTY (can't reverse-engineer exact values)")

if __name__ == "__main__":
    diagnose()
