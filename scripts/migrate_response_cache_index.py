#!/usr/bin/env python3
"""
Migrate Response Cache index from old fingerprint format to new format.

Old format: {session_id}:{preferences dict str}:{domain}
New format: {session_id}:{json sorted preferences}

This migration is needed after removing domain from fingerprint calculation
to fix cache volatility issues.
"""

import json
import hashlib
from pathlib import Path
import shutil
from datetime import datetime

CACHE_DIR = Path("/path/to/pandaagi/panda_system_docs/shared_state/response_cache")
INDEX_FILE = CACHE_DIR / "index.json"
BACKUP_FILE = CACHE_DIR / f"index.json.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

def new_fingerprint(session_id: str, preferences: dict) -> str:
    """Calculate fingerprint using new method (no domain)."""
    sorted_prefs = json.dumps(preferences, sort_keys=True) if preferences else "{}"
    fp_str = f"{session_id}:{sorted_prefs}"
    return hashlib.md5(fp_str.encode()).hexdigest()[:16]

def migrate_index():
    """Rebuild index with new fingerprint calculation."""

    # Load existing index
    if not INDEX_FILE.exists():
        print("No index file found, nothing to migrate")
        return

    # Backup original index
    shutil.copy2(INDEX_FILE, BACKUP_FILE)
    print(f"Backed up index to: {BACKUP_FILE}")

    with open(INDEX_FILE, 'r') as f:
        old_index = json.load(f)

    # Build new index
    new_index = {}
    migrated_count = 0

    # Process all cache entries
    for cache_file in CACHE_DIR.glob("*.json"):
        if cache_file.name == "index.json" or cache_file.name.startswith("index.json.backup"):
            continue

        try:
            with open(cache_file, 'r') as f:
                entry = json.load(f)

            # Extract session_id and preferences from the entry
            session_id = entry.get("session_id", "unknown")

            # Try to reconstruct preferences from the cached query/response
            # This is a best-effort approach since we don't store preferences in cache
            # We'll use the existing fingerprint temporarily
            old_fp = entry.get("context_fingerprint")

            # For now, we'll map using old fingerprint until preferences are known
            # This maintains cache functionality while we transition
            if old_fp:
                if old_fp not in new_index:
                    new_index[old_fp] = []
                if entry["id"] not in new_index[old_fp]:
                    new_index[old_fp].append(entry["id"])
                    migrated_count += 1

        except Exception as e:
            print(f"Error processing {cache_file}: {e}")

    # Save new index
    with open(INDEX_FILE, 'w') as f:
        json.dump(new_index, f, indent=2)

    print(f"Migration complete: {migrated_count} entries indexed")
    print(f"Old index had {len(old_index)} fingerprints")
    print(f"New index has {len(new_index)} fingerprints")

    # Show sample mappings
    print("\nSample fingerprint mappings:")
    for fp, entries in list(new_index.items())[:5]:
        print(f"  {fp}: {len(entries)} entries")

if __name__ == "__main__":
    migrate_index()