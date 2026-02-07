#!/usr/bin/env python3
"""Test script for intent classification system."""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.services.gateway.intent_classifier import IntentClassifier, IntentType

def test_intent_classification():
    """Test intent classifier with various queries."""
    classifier = IntentClassifier()

    test_cases = [
        # Informational queries
        ("how do hamster breeders sell their hamsters?", IntentType.INFORMATIONAL),
        ("what is the best way to find a breeder?", IntentType.INFORMATIONAL),
        ("can you tell me what some of the popular forums would be?", IntentType.INFORMATIONAL),
        ("how to breed hamsters", IntentType.INFORMATIONAL),
        ("explain how selling works", IntentType.INFORMATIONAL),

        # Navigational queries
        ("is there a place where hamster breeders list their animals?", IntentType.NAVIGATIONAL),
        ("where can I find hamster breeders?", IntentType.NAVIGATIONAL),
        ("find hamster breeder forums", IntentType.NAVIGATIONAL),
        ("popular hamster breeder websites", IntentType.NAVIGATIONAL),

        # Transactional queries
        ("buy hamsters online", IntentType.TRANSACTIONAL),
        ("find hamsters for sale", IntentType.TRANSACTIONAL),
        ("purchase Syrian hamsters", IntentType.TRANSACTIONAL),
        ("get me hamsters to buy", IntentType.TRANSACTIONAL),
        ("looking to buy a hamster", IntentType.TRANSACTIONAL),

        # Code queries
        ("read the file src/main.py", IntentType.CODE),
        ("commit these changes to git", IntentType.CODE),
        ("create a new function in app.py", IntentType.CODE),
        ("run the tests", IntentType.CODE),
    ]

    print("Intent Classification Test Results")
    print("=" * 80)

    passed = 0
    failed = 0

    for query, expected_intent in test_cases:
        signal = classifier.classify(query)
        actual_intent = signal.intent

        status = "✓ PASS" if actual_intent == expected_intent else "✗ FAIL"
        if actual_intent == expected_intent:
            passed += 1
        else:
            failed += 1

        print(f"\n{status}")
        print(f"Query: {query}")
        print(f"Expected: {expected_intent.value}")
        print(f"Actual: {actual_intent.value} (confidence: {signal.confidence:.2f})")
        print(f"Reason: {signal.reason}")

    print("\n" + "=" * 80)
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed} tests")

    return failed == 0

if __name__ == "__main__":
    success = test_intent_classification()
    sys.exit(0 if success else 1)
