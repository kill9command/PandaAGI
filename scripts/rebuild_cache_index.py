#!/usr/bin/env python3
"""
Rebuild response cache index with new fingerprint calculation.

The fingerprint formula changed from:
  OLD: session_id + preferences + domain
  NEW: session_id + sorted_json(preferences)

This script recalculates fingerprints for all cached entries.
"""
import json
import hashlib
from pathlib import Path

CACHE_DIR = Path("panda_system_docs/shared_state/response_cache")

def new_context_fingerprint(session_context: dict) -> str:
    """New fingerprint calculation (without domain)"""
    prefs = session_context.get('preferences', {})
    sorted_prefs = json.dumps(prefs, sort_keys=True) if prefs else "{}"

    fp_str = (
        f"{session_context.get('session_id', 'unknown')}:"
        f"{sorted_prefs}"
    )
    return hashlib.md5(fp_str.encode()).hexdigest()[:16]

def rebuild_index():
    """Rebuild index with new fingerprint calculation"""
    new_index = {}

    # Load all cache entries
    for cache_file in CACHE_DIR.glob("*.json"):
        if cache_file.name == "index.json":
            continue

        try:
            with open(cache_file, 'r') as f:
                entry = json.load(f)

            # Build session_context from stored fields
            session_context = {
                "session_id": entry.get("session_id", "unknown"),
                "preferences": {},  # Not stored in cache entry, use empty
                "domain": entry.get("domain", "")
            }

            # Calculate new fingerprint (without domain, with sorted prefs)
            new_fp = new_context_fingerprint(session_context)

            # Add to new index
            if new_fp not in new_index:
                new_index[new_fp] = []
            new_index[new_fp].append(entry["id"])

            print(f"  {entry['id']}: {entry.get('context_fingerprint', 'N/A')} -> {new_fp}")

        except Exception as e:
            print(f"  ERROR processing {cache_file.name}: {e}")

    # Save new index
    index_file = CACHE_DIR / "index.json"
    with open(index_file, 'w') as f:
        json.dump(new_index, f, indent=2)

    print(f"\nRebuilt index: {len(new_index)} fingerprints, {sum(len(ids) for ids in new_index.values())} total entries")

if __name__ == "__main__":
    print("Rebuilding response cache index with new fingerprint calculation...")
    print(f"Cache directory: {CACHE_DIR}")
    rebuild_index()
    print("Done!")
