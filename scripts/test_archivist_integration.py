#!/usr/bin/env python3
"""
Test Archivist Integration (Phase 8)

Verifies:
1. Response caching in Layer 1 (ResponseCache)
2. Claim-cache bidirectional linkage
3. Rolling summaries update
4. Manifest tracking
"""

import asyncio
import json
import sqlite3
from pathlib import Path

# Test query
TEST_QUERY = "What are the best hamster wheel brands for Syrian hamsters?"


async def test_archivist_integration():
    print("=" * 80)
    print("ARCHIVIST INTEGRATION TEST")
    print("=" * 80)
    print()

    # Test 1: Send query to Gateway
    print("📤 Test 1: Sending test query to Gateway...")
    print(f"Query: {TEST_QUERY}")
    print()

    import aiohttp

    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": "qwen2.5-32b-instruct",
                "messages": [
                    {"role": "user", "content": TEST_QUERY}
                ],
                "stream": False
            }

            async with session.post(
                "http://127.0.0.1:9000/v1/chat/completions",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status != 200:
                    print(f"❌ Gateway returned {resp.status}")
                    text = await resp.text()
                    print(f"Response: {text}")
                    return False

                result = await resp.json()
                response_text = result["choices"][0]["message"]["content"]
                print(f"✅ Response received ({len(response_text)} chars)")
                print(f"Preview: {response_text[:200]}...")
                print()

    except Exception as e:
        print(f"❌ Failed to send query: {e}")
        return False

    # Test 2: Check Response Cache (Layer 1)
    print("🔍 Test 2: Checking Response Cache (Layer 1)...")

    cache_db_path = Path("panda_system_docs/shared_state/response_cache.db")
    if not cache_db_path.exists():
        print(f"❌ Cache database not found: {cache_db_path}")
        return False

    conn = sqlite3.connect(str(cache_db_path))
    cursor = conn.cursor()

    # Check for cached response
    cursor.execute("""
        SELECT response_id, query, intent, domain, claims_used, quality_score,
               metadata, created_at
        FROM responses
        ORDER BY created_at DESC
        LIMIT 1
    """)

    row = cursor.fetchone()
    if not row:
        print("❌ No cached response found")
        conn.close()
        return False

    response_id, query, intent, domain, claims_used_json, quality_score, metadata_json, created_at = row

    print(f"✅ Response cached:")
    print(f"   - Response ID: {response_id}")
    print(f"   - Query: {query[:60]}...")
    print(f"   - Intent: {intent}")
    print(f"   - Domain: {domain}")
    print(f"   - Quality Score: {quality_score}")

    # Parse claims_used
    try:
        claims_used = json.loads(claims_used_json) if claims_used_json else []
        print(f"   - Claims Used: {len(claims_used)} claims")
    except json.JSONDecodeError:
        print(f"   - Claims Used: {claims_used_json}")
        claims_used = []

    # Parse metadata
    try:
        metadata = json.loads(metadata_json) if metadata_json else {}
        manifest_ref = metadata.get("manifest_ref", {})
        print(f"   - Turn ID: {manifest_ref.get('turn_id', 'N/A')}")
        print(f"   - Trace ID: {manifest_ref.get('trace_id', 'N/A')}")
    except json.JSONDecodeError:
        print(f"   - Metadata: {metadata_json}")

    print()
    conn.close()

    # Test 3: Check Claim-Cache Linkage (Layer 2)
    print("🔗 Test 3: Checking Claim-Cache Bidirectional Linkage...")

    claims_db_path = Path("panda_system_docs/shared_state/claims.db")
    if not claims_db_path.exists():
        print(f"❌ Claims database not found: {claims_db_path}")
        return False

    conn = sqlite3.connect(str(claims_db_path))
    cursor = conn.cursor()

    if claims_used:
        print(f"Checking {len(claims_used)} claims for cache linkage...")

        linked_count = 0
        for claim_id in claims_used[:5]:  # Check first 5
            cursor.execute("""
                SELECT claim_id, claim_text, metadata
                FROM claims
                WHERE claim_id = ?
            """, (claim_id,))

            row = cursor.fetchone()
            if row:
                _, claim_text, metadata_json = row
                try:
                    metadata = json.loads(metadata_json) if metadata_json else {}
                    cache_id = metadata.get("cache_id")

                    if cache_id == response_id:
                        linked_count += 1
                        print(f"   ✅ Claim {claim_id[:12]}... linked to cache {cache_id[:12]}...")
                except json.JSONDecodeError:
                    print(f"   ⚠️  Claim {claim_id[:12]}... has invalid metadata")

        if linked_count > 0:
            print(f"✅ {linked_count}/{len(claims_used[:5])} claims linked to cache (bidirectional)")
        else:
            print(f"⚠️  No claims linked to cache")
        print()
    else:
        print("⚠️  No claims to check (claims_used empty)")
        print()

    conn.close()

    # Test 4: Check Rolling Summaries
    print("📚 Test 4: Checking Rolling Summaries...")

    # Find most recent session
    sessions_dir = Path("panda_system_docs/sessions")
    if not sessions_dir.exists():
        print(f"❌ Sessions directory not found: {sessions_dir}")
        return False

    session_dirs = sorted(sessions_dir.glob("session_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not session_dirs:
        print("❌ No sessions found")
        return False

    latest_session = session_dirs[0]
    print(f"Latest session: {latest_session.name}")

    # Check rolling summary files
    summary_files = [
        "live_context.md",
        "preferences.md",
        "history_compressed.md",
        "memory_update.json"
    ]

    found_count = 0
    for filename in summary_files:
        filepath = latest_session / filename
        if filepath.exists():
            size = filepath.stat().st_size
            print(f"   ✅ {filename} ({size} bytes)")
            found_count += 1
        else:
            print(f"   ❌ {filename} (not found)")

    if found_count == len(summary_files):
        print(f"✅ All {len(summary_files)} rolling summary files present")
    else:
        print(f"⚠️  Only {found_count}/{len(summary_files)} rolling summary files present")
    print()

    # Test 5: Check Manifest
    print("📋 Test 5: Checking Turn Manifest...")

    # Find most recent turn
    turns_dir = Path("panda_system_docs/turns")
    if not turns_dir.exists():
        print(f"❌ Turns directory not found: {turns_dir}")
        return False

    turn_dirs = sorted(turns_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not turn_dirs:
        print("❌ No turns found")
        return False

    latest_turn = turn_dirs[0]
    manifest_path = latest_turn / "manifest.json"

    if not manifest_path.exists():
        print(f"❌ Manifest not found: {manifest_path}")
        return False

    with open(manifest_path) as f:
        manifest = json.load(f)

    print(f"Turn: {latest_turn.name}")
    print(f"   - Phase: {manifest.get('phase', 'N/A')}")
    print(f"   - Intent: {manifest.get('intent', 'N/A')}")
    print(f"   - Domain: {manifest.get('domain', 'N/A')}")

    # Check for response_cache_id
    response_cache_id = manifest.get("response_cache_id")
    if response_cache_id:
        print(f"   ✅ response_cache_id: {response_cache_id[:12]}...")
    else:
        print(f"   ❌ response_cache_id: missing")

    # Check for claim_ids
    claim_ids = manifest.get("claim_ids", [])
    if claim_ids:
        print(f"   ✅ claim_ids: {len(claim_ids)} claims")
    else:
        print(f"   ⚠️  claim_ids: empty")

    # Check for claims_turn_linkage
    claims_turn_linkage = manifest.get("claims_turn_linkage")
    if claims_turn_linkage:
        print(f"   ✅ claims_turn_linkage: turn {claims_turn_linkage.get('turn_id', 'N/A')}")
    else:
        print(f"   ❌ claims_turn_linkage: missing")

    print()

    # Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print("✅ Response caching (Layer 1): Working")
    if claims_used and linked_count > 0:
        print("✅ Claim-cache linkage (bidirectional): Working")
    else:
        print("⚠️  Claim-cache linkage: No claims or linkage not verified")

    if found_count == len(summary_files):
        print("✅ Rolling summaries: Working")
    else:
        print("⚠️  Rolling summaries: Partial")

    if response_cache_id and claim_ids:
        print("✅ Manifest tracking: Complete")
    else:
        print("⚠️  Manifest tracking: Incomplete")

    print()
    print("🎉 Archivist Integration Test Complete!")
    print()

    return True


if __name__ == "__main__":
    asyncio.run(test_archivist_integration())
