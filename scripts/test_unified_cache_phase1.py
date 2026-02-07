#!/usr/bin/env python3
"""
Test script for Unified Cache System Phase 1 components.

Tests:
1. ContextFingerprint - hashing consistency and backward compatibility
2. CacheStore - storage, retrieval, TTL, eviction
3. CacheConfig - configuration loading and defaults
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.services.tool_server.shared_state.context_fingerprint import (
    ContextFingerprint,
    compute_fingerprint
)
from apps.services.tool_server.shared_state.cache_store import JSONCacheStore, CacheEntry


def test_context_fingerprint():
    """Test ContextFingerprint module."""
    print("\n=== Testing ContextFingerprint ===")

    # Test 1: Basic fingerprint computation
    print("\n1. Basic fingerprint computation...")
    result = compute_fingerprint(
        session_id="test_session",
        context={
            "preferences": {"vendor": "PetSmart", "budget": 50},
            "created_at": "2025-01-01",  # Should be excluded
            "metadata": {"foo": "bar"}  # Should be excluded
        },
        query="find hamsters"
    )

    assert result.primary, "Primary fingerprint should exist"
    assert result.legacy, "Legacy fingerprint should exist for backward compat"
    assert len(result.primary) == 16, "Primary hash should be 16 chars"
    print(f"   ✓ Primary: {result.primary}")
    print(f"   ✓ Legacy: {result.legacy}")
    print(f"   ✓ Version: {result.version}")

    # Test 2: Consistency - same input produces same hash
    print("\n2. Consistency check...")
    result2 = compute_fingerprint(
        session_id="test_session",
        context={
            "preferences": {"vendor": "PetSmart", "budget": 50},
            "created_at": "2025-01-02",  # Different volatile field
            "metadata": {"baz": "qux"}  # Different metadata
        },
        query="find hamsters"
    )

    assert result.primary == result2.primary, "Same semantic context should produce same hash"
    print(f"   ✓ Consistent hashing despite volatile field changes")

    # Test 3: Difference detection
    print("\n3. Difference detection...")
    result3 = compute_fingerprint(
        session_id="test_session",
        context={"preferences": {"vendor": "Petco", "budget": 50}},  # Different vendor
        query="find hamsters"
    )

    assert result.primary != result3.primary, "Different preferences should produce different hash"
    print(f"   ✓ Different contexts produce different hashes")

    # Test 4: Normalization
    print("\n4. Preference normalization...")
    result4a = compute_fingerprint(
        session_id="test",
        context={"preferences": {"b": 2, "a": 1}},  # Unsorted keys
        query="test"
    )
    result4b = compute_fingerprint(
        session_id="test",
        context={"preferences": {"a": 1, "b": 2}},  # Sorted keys
        query="test"
    )

    assert result4a.primary == result4b.primary, "Key order should not affect hash"
    print(f"   ✓ Normalization handles key ordering")

    # Test 5: Verification
    print("\n5. Fingerprint verification...")
    fp = ContextFingerprint()
    is_valid = fp.verify(
        result.primary,
        session_id="test_session",
        context={"preferences": {"vendor": "PetSmart", "budget": 50}},
        query="find hamsters"
    )

    assert is_valid, "Verification should succeed for matching fingerprint"
    print(f"   ✓ Verification works correctly")

    print("\n✅ All ContextFingerprint tests passed!")
    return True


async def test_cache_store():
    """Test CacheStore module."""
    print("\n=== Testing CacheStore ===")

    # Create temporary directory for testing
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "test_cache"

        # Test 1: Initialize cache
        print("\n1. Cache initialization...")
        cache = JSONCacheStore(
            cache_type="test",
            base_dir=cache_dir,
            max_size_mb=1,  # Small for testing eviction
            default_ttl=60
        )
        await cache.initialize()
        print(f"   ✓ Cache initialized at {cache_dir}")

        # Test 2: Store and retrieve
        print("\n2. Store and retrieve...")
        entry = await cache.put(
            key="test_key_1",
            value={"data": "test value 1", "count": 42},
            ttl=300,
            metadata={"source": "test"},
            quality=0.85,
            claims=["claim_1", "claim_2"]
        )

        assert entry.key == "test_key_1"
        assert entry.quality == 0.85
        print(f"   ✓ Stored entry: size={entry.size_bytes} bytes")

        retrieved = await cache.get("test_key_1")
        assert retrieved is not None
        assert retrieved.value["count"] == 42
        assert retrieved.quality == 0.85
        assert len(retrieved.claims) == 2
        assert retrieved.hits == 1  # Incremented on retrieval
        print(f"   ✓ Retrieved entry with correct data")

        # Test 3: Expiration
        print("\n3. TTL expiration...")
        await cache.put(
            key="expired_key",
            value={"data": "will expire"},
            ttl=1  # 1 second
        )

        # Wait for expiration
        await asyncio.sleep(1.5)

        expired = await cache.get("expired_key")
        assert expired is None, "Expired entry should return None"
        print(f"   ✓ Expired entries are removed")

        # Test 4: Multiple entries
        print("\n4. Multiple entries...")
        for i in range(5):
            await cache.put(
                key=f"multi_key_{i}",
                value={"index": i, "data": f"value_{i}"},
                quality=0.5 + (i * 0.1)
            )

        all_entries = await cache.list()
        assert len(all_entries) >= 5, f"Should have at least 5 entries, got {len(all_entries)}"
        print(f"   ✓ Stored {len(all_entries)} entries")

        # Test 5: Filtering
        print("\n5. Entry filtering...")
        high_quality = await cache.list(filters={"quality__gte": 0.8})
        assert len(high_quality) >= 2, "Should find high-quality entries"
        print(f"   ✓ Found {len(high_quality)} high-quality entries (>= 0.8)")

        # Test 6: Statistics
        print("\n6. Cache statistics...")
        stats = await cache.get_stats()
        assert stats["cache_type"] == "test"
        assert stats["entry_count"] > 0
        print(f"   ✓ Stats: {stats['entry_count']} entries, {stats['total_size_mb']:.2f} MB")

        # Test 7: Invalidation with pattern
        print("\n7. Pattern-based invalidation...")
        await cache.put("temp_1", {"data": "temp"})
        await cache.put("temp_2", {"data": "temp"})
        await cache.put("keep_1", {"data": "keep"})

        await cache.invalidate("temp_*")

        assert await cache.get("temp_1") is None
        assert await cache.get("temp_2") is None
        assert await cache.get("keep_1") is not None
        print(f"   ✓ Pattern invalidation works")

        # Test 8: Index persistence
        print("\n8. Index persistence...")
        await cache.put("persist_key", {"data": "persistent"}, ttl=3600)

        # Create new cache instance pointing to same directory
        cache2 = JSONCacheStore(
            cache_type="test",
            base_dir=cache_dir,
            max_size_mb=1,
            default_ttl=60
        )
        await cache2.initialize()

        persisted = await cache2.get("persist_key")
        assert persisted is not None
        assert persisted.value["data"] == "persistent"
        print(f"   ✓ Index persists across restarts")

    print("\n✅ All CacheStore tests passed!")
    return True


def test_cache_config():
    """Test CacheConfig module (if implemented)."""
    print("\n=== Testing CacheConfig ===")

    try:
        from apps.services.tool_server.shared_state.cache_config import get_cache_config, CacheConfig

        # Test 1: Load configuration
        print("\n1. Loading configuration...")
        config = get_cache_config()
        assert config is not None
        print(f"   ✓ Config loaded successfully")

        # Test 2: Cache classes
        print("\n2. Cache class definitions...")
        short_lived = config.get_class_config("short_lived")
        assert short_lived is not None
        assert short_lived.ttl_seconds == 3600
        print(f"   ✓ Short-lived: TTL={short_lived.ttl_seconds}s, Size={short_lived.max_size_mb}MB")

        medium_term = config.get_class_config("medium_term")
        assert medium_term.ttl_seconds == 86400
        print(f"   ✓ Medium-term: TTL={medium_term.ttl_seconds}s, Size={medium_term.max_size_mb}MB")

        # Test 3: Similarity thresholds
        print("\n3. Similarity thresholds...")
        response_threshold = config.get_similarity_threshold("response")
        assert response_threshold == 0.85
        print(f"   ✓ Response threshold: {response_threshold}")

        # Test 4: Cache directories
        print("\n4. Cache directory paths...")
        response_dir = config.get_cache_dir("response")
        assert "response_cache" in str(response_dir)
        print(f"   ✓ Response cache dir: {response_dir}")

        # Test 5: Export to dict
        print("\n5. Configuration export...")
        config_dict = config.to_dict()
        assert "cache_classes" in config_dict
        assert "similarity_thresholds" in config_dict
        print(f"   ✓ Config exports to dict with {len(config_dict)} keys")

        print("\n✅ All CacheConfig tests passed!")
        return True

    except ImportError as e:
        print(f"\n⚠️  CacheConfig module not fully implemented yet")
        print(f"   Error: {e}")
        return False


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print(" Unified Cache System - Phase 1 Tests")
    print("="*60)

    results = {}

    # Test 1: ContextFingerprint
    try:
        results["ContextFingerprint"] = test_context_fingerprint()
    except Exception as e:
        print(f"\n❌ ContextFingerprint tests failed: {e}")
        import traceback
        traceback.print_exc()
        results["ContextFingerprint"] = False

    # Test 2: CacheStore
    try:
        results["CacheStore"] = await test_cache_store()
    except Exception as e:
        print(f"\n❌ CacheStore tests failed: {e}")
        import traceback
        traceback.print_exc()
        results["CacheStore"] = False

    # Test 3: CacheConfig
    try:
        results["CacheConfig"] = test_cache_config()
    except Exception as e:
        print(f"\n❌ CacheConfig tests failed: {e}")
        import traceback
        traceback.print_exc()
        results["CacheConfig"] = False

    # Summary
    print("\n" + "="*60)
    print(" Test Summary")
    print("="*60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for component, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {component:20s} {status}")

    print(f"\n  Total: {passed}/{total} components passed")

    if passed == total:
        print("\n🎉 All Phase 1 components are working correctly!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} component(s) need attention")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
