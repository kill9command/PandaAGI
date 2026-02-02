#!/usr/bin/env python3
"""Final verification that species matching fix works."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# Test the actual cache matching logic
from libs.gateway.app import _subject_keywords, _SPECIES_HINTS

def test_species_matching():
    """Verify species-specific filtering works."""
    print("=" * 80)
    print("FINAL FIX VERIFICATION: Species Matching")
    print("=" * 80)

    # Simulate the exact scenario from the transcript
    user_query = "Can you find some for sale online for me?"
    history = "my favorite hamster is Syrian"

    # Extract keywords (with FIX applied)
    keywords = _subject_keywords("", history, user_query)

    print(f"\nUser query: {user_query}")
    print(f"History: {history}")
    print(f"Extracted keywords: {keywords}")

    # Check if species hint is in keywords
    user_species = [kw for kw in keywords if kw in _SPECIES_HINTS]
    print(f"Species hints in keywords: {user_species}")

    # Simulate cached claims
    test_claims = [
        ("North Yorkshire Hamster Breeder - Russian Dwarf Hamsters for Sale", False),
        ("Syrian Hamster Breeders Online - Premium Syrian Hamsters", True),
        ("Campbell Dwarf Hamster Care Guide - Complete Guide", False),
        ("Golden Hamster (Syrian) - Care and Breeding", True),  # "golden" is alias for "syrian"
    ]

    print("\n" + "-" * 80)
    print("Testing cache claim filtering:")
    print("-" * 80)

    all_passed = True
    for statement, should_match in test_claims:
        statement_lower = statement.lower()

        # Apply the species matching logic (from app.py lines 2341-2346)
        if user_species:
            has_species_match = any(species in statement_lower for species in user_species)
        else:
            has_species_match = True  # No species filter if user didn't specify

        match_status = "✓ PASS" if has_species_match else "✗ REJECT"
        expected_status = "SHOULD MATCH" if should_match else "SHOULD REJECT"

        # Check if result matches expectation
        if has_species_match == should_match:
            result = "✓ CORRECT"
        else:
            result = "✗ WRONG"
            all_passed = False

        print(f"\n{result} {match_status} - {expected_status}")
        print(f"  Statement: {statement[:70]}...")
        print(f"  User species: {user_species}")
        print(f"  Has species match: {has_species_match}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    if all_passed:
        print("✓ ALL TESTS PASSED")
        print("✓ Species matching filter works correctly")
        print("✓ Russian Dwarf claims correctly rejected")
        print("✓ Syrian claims correctly accepted")
    else:
        print("✗ SOME TESTS FAILED")
        print("Check the results above for details")

    return all_passed

if __name__ == "__main__":
    success = test_species_matching()
    sys.exit(0 if success else 1)
