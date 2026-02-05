#!/usr/bin/env python3
"""Test to diagnose the cache matching issue with hamster queries."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from apps.services.gateway.intent_classifier import IntentClassifier, IntentType

def test_intent_classification():
    """Test intent classification for the hamster queries."""
    classifier = IntentClassifier()

    test_cases = [
        # Original query (user's favorite is Syrian)
        ("do you know what my favorite hamster is?", "informational", "Asking about preference"),

        # The problematic query
        ("Can you find some for sale online for me?", "transactional", "Implicit purchase query"),

        # Explicit versions
        ("find Syrian hamsters for sale online", "transactional", "Explicit purchase"),
        ("find hamster breeders", "navigational", "Finding services"),
        ("what food do hamsters need", "informational", "Care question"),
    ]

    print("=" * 80)
    print("INTENT CLASSIFICATION TEST")
    print("=" * 80)

    for query, expected_intent, description in test_cases:
        result = classifier.classify(query=query, context="")
        match_status = "✓" if result.intent.value == expected_intent else "✗"

        print(f"\n{match_status} Query: {query}")
        print(f"  Description: {description}")
        print(f"  Expected: {expected_intent}")
        print(f"  Got: {result.intent.value} (confidence: {result.confidence:.2f})")
        print(f"  Reason: {result.reason}")

def test_keyword_extraction():
    """Test keyword extraction for cache matching."""
    from libs.gateway.app import _subject_keywords

    print("\n" + "=" * 80)
    print("KEYWORD EXTRACTION TEST")
    print("=" * 80)

    test_cases = [
        ("Can you find some for sale online for me?", "my favorite hamster is Syrian", ""),
        ("find Syrian hamsters for sale", "", ""),
        ("find Russian dwarf hamsters", "", ""),
    ]

    for user_msg, history_subject, ticket_goal in test_cases:
        keywords = _subject_keywords(ticket_goal, history_subject, user_msg)
        print(f"\nQuery: {user_msg}")
        print(f"History: {history_subject}")
        print(f"Keywords: {keywords}")

def analyze_cache_claim():
    """Analyze the cached claim that was incorrectly matched."""
    print("\n" + "=" * 80)
    print("CACHED CLAIM ANALYSIS")
    print("=" * 80)

    # This is the claim that was returned (from SQLite output)
    cached_claim = {
        "claim_id": "clm_6b2ede124b05b4eb",
        "statement": "North Yorkshire Hamster Breeder - Russian Dwarf Hamsters for Sale from vendor (unknown)",
        "metadata": {
            "offer_index": 4,
            "price_text": "",
            "source": "vendor",
            "availability": "unknown",
            "link": "https://north-yorkshire-hamster-breeder.yolasite.com/",
            "title": "North Yorkshire Hamster Breeder - Russian Dwarf Hamsters for Sale",
            "score": 0.702,
            "source_tool": "commerce.search_offers",
            "domain": "pricing",
            "topics": ["purchase", "pricing"],
            "matched_intent": "transactional"  # This was set when claim was created
        }
    }

    print("\nCached Claim:")
    print(f"  ID: {cached_claim['claim_id']}")
    print(f"  Statement: {cached_claim['statement']}")
    print(f"  Domain: {cached_claim['metadata']['domain']}")
    print(f"  Matched Intent: {cached_claim['metadata']['matched_intent']}")
    print(f"  Topics: {cached_claim['metadata']['topics']}")

    print("\n** Problem Identification **")
    print("  ✗ Statement contains 'Russian Dwarf' but user wants 'Syrian'")
    print("  ✗ No species-specific metadata to filter by")
    print("  ✓ Intent matches (both transactional)")
    print("  ✓ Domain matches (pricing)")

    print("\nKeyword Overlap Analysis:")
    user_query = "Can you find some for sale online for me?"
    user_keywords = ["hamster", "sale", "online"]  # Expected from query
    claim_keywords = ["hamster", "breeder", "russian", "dwarf", "sale"]  # From claim

    overlap = set(user_keywords) & set(claim_keywords)
    relevance = len(overlap) / len(user_keywords) if user_keywords else 0

    print(f"  User keywords: {user_keywords}")
    print(f"  Claim keywords: {claim_keywords}")
    print(f"  Overlap: {overlap}")
    print(f"  Relevance: {relevance:.2f} (threshold: 0.5)")
    print(f"  → Would pass keyword filter: {relevance >= 0.5}")

def main():
    """Run all diagnostic tests."""
    test_intent_classification()
    test_keyword_extraction()
    analyze_cache_claim()

    print("\n" + "=" * 80)
    print("CONCLUSIONS")
    print("=" * 80)
    print("""
1. **Intent Classification**: Works correctly (transactional)
2. **Keyword Matching**: Too broad (only needs 'hamster' + 'sale')
3. **Missing Context**: User's preference 'Syrian' not incorporated
4. **No Entity Filtering**: No mechanism to match species/breed specificity

**Root Cause**: Cache matching uses keyword overlap without entity-level filtering.
The system matched on "hamster + sale" but didn't check that "Russian Dwarf" ≠ "Syrian".
""")

if __name__ == "__main__":
    main()
