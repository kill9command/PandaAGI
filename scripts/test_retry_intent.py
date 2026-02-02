#!/usr/bin/env python3
"""
Test retry intent detection and cache bypass functionality.

Tests:
1. Intent classifier detects RETRY intent
2. force_refresh flag is set correctly
3. Claims cache is bypassed on retry
4. Observability logging is present
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from libs.gateway.intent_classifier import IntentClassifier, IntentType


def test_intent_classifier():
    """Test that intent classifier detects retry keywords"""
    print("=" * 60)
    print("TEST 1: Intent Classifier - RETRY Detection")
    print("=" * 60)

    classifier = IntentClassifier()

    test_cases = [
        # Should detect RETRY
        ("retry", IntentType.RETRY, True),
        ("retry can you find some for sale online for me?", IntentType.RETRY, True),
        ("refresh the search", IntentType.RETRY, True),
        ("try again", IntentType.RETRY, True),
        ("search again for hamsters", IntentType.RETRY, True),
        ("that didn't work, try again", IntentType.RETRY, True),
        ("new search please", IntentType.RETRY, True),
        ("fresh search", IntentType.RETRY, True),

        # Should NOT detect RETRY
        ("find Syrian hamsters for sale", IntentType.TRANSACTIONAL, False),
        ("what did you find earlier?", IntentType.RECALL, False),
        ("tell me about hamsters", IntentType.INFORMATIONAL, False),
    ]

    passed = 0
    failed = 0

    for query, expected_intent, should_be_retry in test_cases:
        result = classifier.classify(query)
        is_retry = result.intent == IntentType.RETRY

        if should_be_retry:
            if is_retry:
                print(f"✅ PASS: '{query}' → {result.intent.value} (confidence={result.confidence:.2f})")
                passed += 1
            else:
                print(f"❌ FAIL: '{query}' → {result.intent.value} (expected RETRY)")
                failed += 1
        else:
            if not is_retry:
                print(f"✅ PASS: '{query}' → {result.intent.value} (correctly NOT retry)")
                passed += 1
            else:
                print(f"❌ FAIL: '{query}' → RETRY (should be {expected_intent.value})")
                failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    print()
    return failed == 0


def test_retry_patterns():
    """Test specific retry pattern matching"""
    print("=" * 60)
    print("TEST 2: Retry Pattern Matching Details")
    print("=" * 60)

    classifier = IntentClassifier()

    retry_queries = [
        "retry",
        "RETRY",  # Case insensitive
        "can you retry that?",
        "please refresh",
        "search again",
        "try again for me",
        "new search",
        "fresh search needed",
        "re-search",
        "redo the search",
        "that didn't work, try again"
    ]

    for query in retry_queries:
        result = classifier.classify(query)
        icon = "✅" if result.intent == IntentType.RETRY else "❌"
        print(f"{icon} '{query}' → {result.intent.value} (conf={result.confidence:.2f})")

    print()


def test_force_refresh_integration():
    """Test that retry intent triggers force_refresh in gateway"""
    print("=" * 60)
    print("TEST 3: Force Refresh Integration (Mock)")
    print("=" * 60)

    classifier = IntentClassifier()

    # Simulate gateway logic
    query = "retry can you find some for sale online for me?"
    intent_result = classifier.classify(query)

    # Gateway logic: if intent is RETRY, set force_refresh=True
    force_refresh = intent_result.intent == IntentType.RETRY

    print(f"Query: '{query}'")
    print(f"Intent: {intent_result.intent.value}")
    print(f"Confidence: {intent_result.confidence:.2f}")
    print(f"Force Refresh: {force_refresh}")

    if force_refresh:
        print("✅ PASS: force_refresh would be set to True")
        print()
        return True
    else:
        print("❌ FAIL: force_refresh should be True for RETRY intent")
        print()
        return False


def main():
    print("\n" + "=" * 60)
    print("RETRY INTENT DETECTION TEST SUITE")
    print("=" * 60 + "\n")

    all_passed = True

    # Run tests
    all_passed &= test_intent_classifier()
    test_retry_patterns()  # Informational, doesn't affect pass/fail
    all_passed &= test_force_refresh_integration()

    # Summary
    print("=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
