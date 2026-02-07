"""
Debug script to test response cache fingerprint calculation.

This tests whether the fingerprint calculation is consistent between
storage and retrieval, which is critical for cache hits.
"""
import hashlib
import json

def new_fingerprint(session_context: dict) -> str:
    """
    NEW fingerprint method (response_cache.py:381-406)
    Uses JSON serialization with sort_keys=True
    """
    prefs = session_context.get('preferences', {})
    sorted_prefs = json.dumps(prefs, sort_keys=True) if prefs else "{}"

    fp_str = (
        f"{session_context.get('session_id', 'unknown')}:"
        f"{sorted_prefs}"
    )
    return hashlib.md5(fp_str.encode()).hexdigest()[:16]

def legacy_fingerprint(session_context: dict) -> str:
    """
    LEGACY fingerprint method (response_cache.py:408-418)
    Uses Python dict string representation
    """
    fp_str = (
        f"{session_context.get('session_id', 'unknown')}:"
        f"{session_context.get('preferences', {})}:"  # Dict str() representation
        f"{session_context.get('domain', '')}"
    )
    return hashlib.md5(fp_str.encode()).hexdigest()[:16]

def test_fingerprints():
    """Test various session context scenarios"""

    # Test Case 1: Empty preferences
    print("=" * 60)
    print("Test Case 1: Empty Preferences")
    print("=" * 60)
    ctx1 = {
        "session_id": "test_session",
        "preferences": {},
        "domain": "general"
    }
    print(f"Session: {ctx1}")
    print(f"New FP:    {new_fingerprint(ctx1)}")
    print(f"Legacy FP: {legacy_fingerprint(ctx1)}")
    print()

    # Test Case 2: With preferences
    print("=" * 60)
    print("Test Case 2: With Preferences")
    print("=" * 60)
    ctx2 = {
        "session_id": "test_session",
        "preferences": {"favorite_hamster": "Syrian hamster"},
        "domain": "shopping"
    }
    print(f"Session: {ctx2}")
    print(f"New FP:    {new_fingerprint(ctx2)}")
    print(f"Legacy FP: {legacy_fingerprint(ctx2)}")
    print()

    # Test Case 3: Check if preference dict ordering matters
    print("=" * 60)
    print("Test Case 3: Preference Dict Order (Should be Same)")
    print("=" * 60)
    ctx3a = {
        "session_id": "test_session",
        "preferences": {"a": "1", "b": "2", "c": "3"},
        "domain": "general"
    }
    ctx3b = {
        "session_id": "test_session",
        "preferences": {"c": "3", "a": "1", "b": "2"},  # Different order
        "domain": "general"
    }
    print(f"Session A: {ctx3a}")
    print(f"New FP A:  {new_fingerprint(ctx3a)}")
    print(f"Session B: {ctx3b}")
    print(f"New FP B:  {new_fingerprint(ctx3b)}")
    print(f"Match: {new_fingerprint(ctx3a) == new_fingerprint(ctx3b)}")
    print()

    # Test Case 4: Check domain impact
    print("=" * 60)
    print("Test Case 4: Domain Impact (NEW vs LEGACY)")
    print("=" * 60)
    ctx4a = {
        "session_id": "test_session",
        "preferences": {"favorite_hamster": "Syrian hamster"},
        "domain": "shopping"
    }
    ctx4b = {
        "session_id": "test_session",
        "preferences": {"favorite_hamster": "Syrian hamster"},
        "domain": "purchasing"  # Different domain
    }
    print(f"Session A (domain=shopping): {ctx4a['domain']}")
    print(f"New FP A:    {new_fingerprint(ctx4a)}")
    print(f"Legacy FP A: {legacy_fingerprint(ctx4a)}")
    print(f"Session B (domain=purchasing): {ctx4b['domain']}")
    print(f"New FP B:    {new_fingerprint(ctx4b)}")
    print(f"Legacy FP B: {legacy_fingerprint(ctx4b)}")
    print(f"New Match:    {new_fingerprint(ctx4a) == new_fingerprint(ctx4b)}")  # Should be TRUE (domain ignored)
    print(f"Legacy Match: {legacy_fingerprint(ctx4a) == legacy_fingerprint(ctx4b)}")  # Should be FALSE (domain matters)
    print()

    # Test Case 5: The REAL problem - JSON vs Python dict string
    print("=" * 60)
    print("Test Case 5: JSON vs Python Dict String (THE BUG)")
    print("=" * 60)
    prefs = {"favorite_hamster": "Syrian hamster"}
    json_str = json.dumps(prefs, sort_keys=True)
    python_str = str(prefs)
    print(f"Preferences dict: {prefs}")
    print(f"JSON string:   {json_str}")
    print(f"Python string: {python_str}")
    print(f"Match: {json_str == python_str}")
    print(f"  → JSON uses DOUBLE quotes")
    print(f"  → Python uses SINGLE quotes")
    print()

    # Test Case 6: Simulate actual trace scenario
    print("=" * 60)
    print("Test Case 6: Actual Trace Scenario")
    print("=" * 60)

    # STORAGE (when response was cached)
    storage_ctx = {
        "session_id": "default",
        "preferences": {"favorite_hamster_breed": "Syrian hamster"},
        "domain": "shopping for Syrian hamster for sale"
    }

    # RETRIEVAL (when searching for cache)
    retrieval_ctx = {
        "session_id": "default",
        "preferences": {"favorite_hamster_breed": "Syrian hamster"},
        "domain": "shopping for Syrian hamster for sale"
    }

    print(f"Storage context:   {storage_ctx}")
    print(f"Storage FP (new):  {new_fingerprint(storage_ctx)}")
    print()
    print(f"Retrieval context: {retrieval_ctx}")
    print(f"Retrieval FP (new):    {new_fingerprint(retrieval_ctx)}")
    print(f"Retrieval FP (legacy): {legacy_fingerprint(retrieval_ctx)}")
    print()
    print(f"New Match:    {new_fingerprint(storage_ctx) == new_fingerprint(retrieval_ctx)}")
    print(f"Legacy Match: {new_fingerprint(storage_ctx) == legacy_fingerprint(retrieval_ctx)}")
    print()

if __name__ == "__main__":
    test_fingerprints()
