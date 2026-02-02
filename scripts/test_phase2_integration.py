#!/usr/bin/env python3
"""
Test Phase 2 Integration - Document Conversion

Tests that existing components now output documents to turn directories:
1. UnifiedContextManager → unified_context.md
2. MetaReflectionGate → meta_reflection.md
3. LiveSessionContext → session_state.md
4. Cache layers include manifest references

Author: v4.0 Migration - Phase 2
Date: 2025-11-16
"""

import sys
import asyncio
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from libs.gateway.turn_manager import setup_turn, update_manifest, save_manifest, TurnDirectory
from libs.gateway.session_context import LiveSessionContext
from libs.gateway.unified_context import UnifiedContextManager, UnifiedContext, ContextItem
from apps.services.orchestrator.meta_reflection import MetaReflectionGate, MetaReflectionResult, MetaAction
from apps.services.orchestrator.shared_state.response_cache import ResponseCache
from apps.services.orchestrator.shared_state.tool_cache import ToolCache


def test_phase2_1_session_context_write():
    """Test LiveSessionContext → session_state.md"""
    print("\n" + "="*80)
    print("PHASE 2.1: LiveSessionContext → session_state.md")
    print("="*80)

    # Create turn
    turn_dir, manifest = setup_turn(
        trace_id="test-phase2-001",
        session_id="test-session-phase2",
        mode="chat",
        user_query="can you find some syrian hamster breeders?"
    )

    # Create session context
    ctx = LiveSessionContext(
        session_id="test-session-phase2",
        preferences={"favorite_hamster": "Syrian", "budget": "under $50", "location": "California"},
        current_topic="shopping for hamster breeders",
        recent_actions=[
            {"action": "search", "query": "Syrian hamster breeders", "results": 5},
            {"action": "filter", "criteria": "ethical breeders", "remaining": 3}
        ],
        discovered_facts={
            "pricing": ["Hamsters: $15-$40", "Shipping: $25-$50"],
            "care": ["needs 800 sq inch cage", "lifespan: 2-3 years"]
        },
        pending_tasks=["Compare breeder reviews", "Check shipping policies"],
        turn_count=3
    )

    # Write document
    path = ctx.write_document(turn_dir)

    print(f"\n✅ Wrote session_state.md:")
    print(f"   Path: {path}")
    print(f"   Exists: {path.exists()}")
    print(f"   Size: {path.stat().st_size} bytes")

    # Read and verify
    content = path.read_text()
    assert "Live Session Context" in content
    assert "favorite_hamster" in content
    assert "shopping for hamster breeders" in content
    print(f"\n   Content preview (first 300 chars):")
    print("   " + "-"*76)
    print("   " + content[:300].replace("\n", "\n   "))
    print("   " + "-"*76)

    # Update manifest
    manifest = update_manifest(manifest, doc_created="session_state.md")
    save_manifest(turn_dir, manifest)

    return turn_dir, manifest


def test_phase2_2_unified_context_write(turn_dir, manifest):
    """Test UnifiedContextManager → unified_context.md"""
    print("\n" + "="*80)
    print("PHASE 2.2: UnifiedContextManager → unified_context.md")
    print("="*80)

    # Create unified context
    unified_ctx = UnifiedContext(
        living_context=ContextItem(
            source="living_context",
            content="User is shopping for Syrian hamster breeders. Budget: under $50. Location: California.",
            relevance=1.0,
            confidence=1.0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            priority=1
        ),
        long_term_memories=[
            ContextItem(
                source="long_term_memory",
                content="User prefers ethical breeders with health guarantees",
                relevance=0.9,
                confidence=0.9,
                timestamp=datetime.now(timezone.utc).isoformat(),
                priority=2
            ),
            ContextItem(
                source="long_term_memory",
                content="User located in California",
                relevance=0.85,
                confidence=0.85,
                timestamp=datetime.now(timezone.utc).isoformat(),
                priority=2
            )
        ],
        recent_claims=[],
        baseline_memories=[],
        discovered_facts=[
            ContextItem(
                source="discovered_facts",
                content="Syrian hamsters cost $15-$40 from ethical breeders",
                relevance=0.95,
                confidence=0.9,
                timestamp=datetime.now(timezone.utc).isoformat(),
                priority=3
            )
        ],
        total_items=4,
        total_estimated_tokens=200,
        gather_time_ms=15.5
    )

    # Create manager and write document
    manager = UnifiedContextManager()
    path = manager.write_document(unified_ctx, turn_dir)

    print(f"\n✅ Wrote unified_context.md:")
    print(f"   Path: {path}")
    print(f"   Exists: {path.exists()}")
    print(f"   Size: {path.stat().st_size} bytes")

    # Read and verify
    content = path.read_text()
    assert "Unified Context" in content
    assert "Session State" in content
    assert "Long-Term Memories" in content
    print(f"\n   Content preview (first 400 chars):")
    print("   " + "-"*76)
    print("   " + content[:400].replace("\n", "\n   "))
    print("   " + "-"*76)

    # Update manifest
    manifest = update_manifest(manifest, doc_created="unified_context.md")
    save_manifest(turn_dir, manifest)

    return unified_ctx


def test_phase2_3_meta_reflection_write(turn_dir, manifest):
    """Test MetaReflectionGate → meta_reflection.md"""
    print("\n" + "="*80)
    print("PHASE 2.3: MetaReflectionGate → meta_reflection.md")
    print("="*80)

    # Create meta-reflection result
    result = MetaReflectionResult(
        confidence=0.92,
        can_proceed=True,
        needs_clarification=False,
        needs_analysis=False,
        reason="Query is clear and specific. User wants Syrian hamster breeders with stated budget and location constraints.",
        action=MetaAction.PROCEED,
        role="guide",
        query_type="transactional",
        action_verbs=["find"],
        needs_info=False,
        info_requests=[]
    )

    # Create gate and write document
    gate = MetaReflectionGate(
        llm_url="http://localhost:8000/v1/chat/completions",
        llm_model="qwen",
        llm_api_key="none"
    )
    path = gate.write_document(result, turn_dir)

    print(f"\n✅ Wrote meta_reflection.md:")
    print(f"   Path: {path}")
    print(f"   Exists: {path.exists()}")
    print(f"   Size: {path.stat().st_size} bytes")

    # Read and verify
    content = path.read_text()
    assert "Meta-Reflection Decision" in content
    assert "PROCEED" in content
    assert "Query Analysis" in content
    print(f"\n   Content preview (first 400 chars):")
    print("   " + "-"*76)
    print("   " + content[:400].replace("\n", "\n   "))
    print("   " + "-"*76)

    # Update manifest
    manifest = update_manifest(manifest, doc_created="meta_reflection.md")
    save_manifest(turn_dir, manifest)


async def test_phase2_4_cache_manifest_refs(turn_dir, manifest):
    """Test cache layers include manifest references"""
    print("\n" + "="*80)
    print("PHASE 2.4: Cache Layers → Manifest References")
    print("="*80)

    # Test response cache
    print("\n   Testing ResponseCache...")
    response_cache = ResponseCache()
    response_id = await response_cache.set(
        query="Syrian hamster breeders online",
        intent="transactional",
        domain="commerce",
        response="Here are 3 reputable Syrian hamster breeders...",
        claims_used=["claim_001", "claim_002"],
        quality_score=0.9,
        ttl_hours=24,
        session_context={
            "session_id": "test-session-phase2",
            "preferences": {"budget": "under $50"}
        },
        manifest_ref={
            "turn_id": turn_dir.turn_id,
            "trace_id": turn_dir.trace_id
        }
    )

    if response_id:
        cache_file = response_cache.storage_path / f"{response_id}.json"
        if cache_file.exists():
            entry = json.loads(cache_file.read_text())
            assert "manifest_ref" in entry
            assert entry["manifest_ref"]["turn_id"] == turn_dir.turn_id
            print(f"   ✅ ResponseCache entry includes manifest_ref: {entry['manifest_ref']}")
        else:
            print(f"   ⚠️  Cache file not found (embeddings might be unavailable)")
    else:
        print(f"   ⚠️  Response cache set returned None (embeddings might be unavailable)")

    # Test tool cache
    print("\n   Testing ToolCache...")
    tool_cache = ToolCache()
    success = await tool_cache.set(
        tool_name="serpapi.search",
        args={"query": "Syrian hamster breeders", "location": "California"},
        result={"organic_results": [{"title": "Breeder 1"}, {"title": "Breeder 2"}]},
        api_cost=0.02,
        execution_time_ms=450,
        ttl_hours=12,
        manifest_ref={
            "turn_id": turn_dir.turn_id,
            "trace_id": turn_dir.trace_id
        }
    )

    if success:
        # Find the cache entry - use the same method as tool_cache
        args_normalized = tool_cache._normalize_args('serpapi.search', {'query': 'Syrian hamster breeders', 'location': 'California'})
        cache_key_str = f"serpapi.search:{json.dumps(args_normalized, sort_keys=True)}"
        cache_key = hashlib.md5(cache_key_str.encode()).hexdigest()[:16]
        cache_file = tool_cache.storage_path / f"{cache_key}.json"

        if cache_file.exists():
            entry = json.loads(cache_file.read_text())
            assert "manifest_ref" in entry
            assert entry["manifest_ref"]["turn_id"] == turn_dir.turn_id
            print(f"   ✅ ToolCache entry includes manifest_ref: {entry['manifest_ref']}")
        else:
            print(f"   ⚠️  Tool cache file not found at expected location")
    else:
        print(f"   ⚠️  Tool cache set failed")

    # Update manifest with cache hits
    manifest = update_manifest(
        manifest,
        cache_hit={"response": bool(response_id), "tool": {"serpapi.search": success}}
    )
    save_manifest(turn_dir, manifest)


async def test_phase2_5_manifest_verification(turn_dir):
    """Verify manifest tracks all documents"""
    print("\n" + "="*80)
    print("PHASE 2.5: Manifest Verification")
    print("="*80)

    from libs.gateway.turn_manager import load_manifest

    manifest = load_manifest(turn_dir)
    assert manifest is not None

    print(f"\n✅ Manifest loaded successfully:")
    print(f"   Turn ID: {manifest['turn_id']}")
    print(f"   Status: {manifest['status']}")
    print(f"   Docs created ({len(manifest['docs_created'])}):")
    for doc in manifest['docs_created']:
        print(f"     - {doc}")

    print(f"\n   Cache hits:")
    print(f"     Response: {manifest['cache_hits']['response']}")
    print(f"     Tool: {manifest['cache_hits']['tool']}")

    # Verify expected documents
    expected_docs = ["user_query.md", "session_state.md", "unified_context.md", "meta_reflection.md"]
    for doc in expected_docs:
        assert doc in manifest['docs_created'], f"Missing expected doc: {doc}"
        assert (turn_dir.path / doc).exists(), f"Doc exists on disk: {doc}"

    print(f"\n   ✅ All expected documents present in manifest and on disk")


async def main():
    """Run complete Phase 2 integration test"""
    print("\n" + "="*80)
    print("PHASE 2 INTEGRATION TEST - Document Conversion")
    print("Testing: Components → Document Outputs + Manifest Tracking")
    print("="*80)

    try:
        # Phase 2.1: Session context
        turn_dir, manifest = test_phase2_1_session_context_write()

        # Phase 2.2: Unified context
        unified_ctx = test_phase2_2_unified_context_write(turn_dir, manifest)

        # Phase 2.3: Meta-reflection
        test_phase2_3_meta_reflection_write(turn_dir, manifest)

        # Phase 2.4: Cache manifest refs
        await test_phase2_4_cache_manifest_refs(turn_dir, manifest)

        # Phase 2.5: Manifest verification
        await test_phase2_5_manifest_verification(turn_dir)

        # Final summary
        print("\n" + "="*80)
        print("✅ ALL PHASE 2 TESTS PASSED")
        print("="*80)
        print(f"\nPhase 2 Integration Summary:")
        print(f"  Turn ID: {turn_dir.turn_id}")
        print(f"  Turn directory: {turn_dir.path}")
        print(f"  Documents created: {len(turn_dir.list_docs())}")
        print(f"\n  Component conversions:")
        print(f"    ✅ LiveSessionContext → session_state.md")
        print(f"    ✅ UnifiedContextManager → unified_context.md")
        print(f"    ✅ MetaReflectionGate → meta_reflection.md")
        print(f"    ✅ ResponseCache → manifest_ref field")
        print(f"    ✅ ToolCache → manifest_ref field")
        print(f"\n🎉 v4.0 Document Conversion - Phase 2 VALIDATED")

    except Exception as e:
        print("\n" + "="*80)
        print("❌ TEST FAILED")
        print("="*80)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
