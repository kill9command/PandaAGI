#!/usr/bin/env python3
"""
Test content-type matching for the hamster care scenario.

Scenario:
1. User asks "find me Syrian hamsters for sale" → Research created with purchase_info, vendor_info
2. User asks "how do I care for them" → System checks if existing research covers care_info
3. Expected: System recognizes need for NEW research because care_info is not covered

This tests the key intelligence flow design:
- Research documents track what content types they contain
- Query classification determines what content types are needed
- Sufficiency check matches needs vs available content
"""

import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from libs.gateway.research_document import (
    classify_query_content_needs,
    classify_content_types_from_findings,
    ResearchDocumentWriter,
    TopicClassification
)


def test_query_content_classification():
    """Test that queries are classified to correct content needs."""
    print("\n=== Test 1: Query Content Classification ===\n")

    test_cases = [
        # Purchase queries
        ("find me Syrian hamsters for sale", ["purchase_info"]),
        ("where can I buy a hamster", ["purchase_info"]),
        ("hamster prices", ["purchase_info"]),

        # Care queries
        ("how do I care for a hamster", ["care_info"]),
        ("how to take care of Syrian hamster", ["care_info"]),
        ("caring for hamsters guide", ["care_info"]),

        # Feeding queries
        ("what do hamsters eat", ["feeding_info"]),
        ("hamster diet", ["feeding_info"]),
        ("best food for Syrian hamster", ["feeding_info"]),  # "best" triggers review_info, not purchase_info

        # Housing queries
        ("what cage for hamster", ["housing_info"]),
        ("hamster habitat setup", ["housing_info"]),
        ("best bedding for hamsters", ["housing_info"]),

        # Health queries
        ("hamster health problems", ["health_info"]),
        ("when to take hamster to vet", ["health_info"]),

        # Combined queries
        ("how to care for and feed a hamster", ["care_info", "feeding_info"]),
    ]

    passed = 0
    failed = 0

    for query, expected_needs in test_cases:
        actual = classify_query_content_needs(query)

        # Check if at least expected needs are covered
        expected_set = set(expected_needs)
        actual_set = set(actual)

        # All expected needs should be in actual
        if expected_set <= actual_set:
            print(f"✓ '{query[:40]}...' → {actual}")
            passed += 1
        else:
            print(f"✗ '{query[:40]}...'")
            print(f"  Expected: {expected_needs}")
            print(f"  Got: {actual}")
            failed += 1

    print(f"\nResult: {passed}/{passed + failed} passed")
    return failed == 0


def test_findings_content_classification():
    """Test that research findings are classified to correct content types."""
    print("\n=== Test 2: Findings Content Classification ===\n")

    # Simulate purchase research findings
    purchase_findings = [
        {
            "name": "Syrian Hamster - Golden",
            "price": "$25-35",
            "vendor": "PetSmart",
            "description": "Healthy Syrian hamster available for purchase",
            "url": "https://petsmart.com/hamster"
        },
        {
            "name": "Baby Syrian Hamster",
            "price": "$20",
            "vendor": "Local Breeder",
            "description": "Hand-raised Syrian hamsters from reputable breeder",
        }
    ]

    purchase_types = classify_content_types_from_findings(purchase_findings)
    print(f"Purchase findings content types: {purchase_types}")

    assert "purchase_info" in purchase_types, "Should have purchase_info"
    assert "vendor_info" in purchase_types, "Should have vendor_info"
    print("✓ Purchase findings correctly classified\n")

    # Simulate care research findings
    care_findings = [
        {
            "name": "Syrian Hamster Care Guide",
            "description": "Complete guide to caring for your Syrian hamster. Feed them fresh vegetables daily.",
            "content": "Syrian hamsters need a large cage with bedding and proper nutrition."
        },
        {
            "name": "Hamster Feeding Tips",
            "description": "What to feed your hamster: seeds, vegetables, and protein sources.",
            "content": "A balanced hamster diet includes lab blocks, fresh veggies, and occasional treats."
        }
    ]

    care_types = classify_content_types_from_findings(care_findings)
    print(f"Care findings content types: {care_types}")

    assert "care_info" in care_types, "Should have care_info"
    assert "feeding_info" in care_types, "Should have feeding_info"
    print("✓ Care findings correctly classified\n")

    # Check NO OVERLAP - purchase research should NOT have care_info
    assert "care_info" not in purchase_types, "Purchase research should NOT have care_info"
    print("✓ Purchase research does NOT contain care_info (correct separation)\n")

    return True


def test_hamster_care_scenario():
    """
    Test the complete hamster care scenario.

    Scenario:
    1. User asks "find me Syrian hamsters for sale"
    2. System does research, creates doc with content_types=[purchase_info, vendor_info]
    3. User asks "how do I care for them"
    4. System checks: does existing research cover care_info?
    5. Expected: NO - need new research
    """
    print("\n=== Test 3: Hamster Care Scenario ===\n")

    # Step 1: Simulate research for "Syrian hamsters for sale"
    print("Step 1: User asks 'find me Syrian hamsters for sale'")

    purchase_query = "find me Syrian hamsters for sale"
    purchase_query_needs = classify_query_content_needs(purchase_query)
    print(f"  Query needs: {purchase_query_needs}")

    # Simulate research findings (purchase-focused)
    purchase_findings = [
        {"name": "Syrian Hamster", "price": "$25", "vendor": "PetSmart", "description": "Available now"},
        {"name": "Golden Hamster", "price": "$30", "vendor": "Petco", "description": "In stock"},
    ]

    purchase_content_types = classify_content_types_from_findings(purchase_findings)
    print(f"  Research content types: {purchase_content_types}")

    # Step 2: Check coverage for purchase query
    purchase_needs_set = set(purchase_query_needs)
    purchase_covered = set(purchase_content_types) & purchase_needs_set

    if purchase_covered == purchase_needs_set:
        print(f"  ✓ Purchase query fully covered by research")
    else:
        unmet = purchase_needs_set - purchase_covered
        print(f"  ✗ Purchase query NOT fully covered. Unmet: {unmet}")

    print()

    # Step 3: User asks follow-up "how do I care for them"
    print("Step 2: User asks 'how do I care for them'")

    care_query = "how do I care for them"
    care_query_needs = classify_query_content_needs(care_query)
    print(f"  Query needs: {care_query_needs}")

    # Step 4: Check if existing purchase research covers care needs
    care_needs_set = set(care_query_needs)
    care_covered = set(purchase_content_types) & care_needs_set
    care_unmet = care_needs_set - care_covered

    print(f"  Existing research has: {purchase_content_types}")
    print(f"  Care query needs: {care_query_needs}")
    print(f"  Covered: {list(care_covered)}")
    print(f"  Unmet: {list(care_unmet)}")

    # Key assertion: care_info should NOT be covered by purchase research
    if "care_info" in care_unmet:
        print(f"  ✓ CORRECT: care_info is NOT covered - need new research!")
        return True
    else:
        print(f"  ✗ WRONG: System thinks care_info is covered when it shouldn't be")
        return False


def test_research_document_content_types():
    """Test that ResearchDocumentWriter correctly classifies content types."""
    print("\n=== Test 4: ResearchDocumentWriter Content Types ===\n")

    writer = ResearchDocumentWriter()

    # Test with purchase-focused results
    purchase_results = {
        "findings": [
            {"name": "Syrian Hamster", "price": "$25", "vendor": "PetSmart"},
            {"name": "Golden Hamster", "price": "$30", "vendor": "Petco"},
        ],
        "stats": {"sources_visited": 3, "sources_extracted": 2}
    }

    doc = writer.create_from_tool_results(
        turn_number=1,
        session_id="test",
        query="Syrian hamsters for sale",
        tool_results=purchase_results,
        intent="transactional"
    )

    print(f"Research document topic: {doc.topic.primary_topic}")
    print(f"Research document content_types: {doc.topic.content_types}")

    assert "purchase_info" in doc.topic.content_types, "Should have purchase_info"
    assert "vendor_info" in doc.topic.content_types, "Should have vendor_info"
    assert "care_info" not in doc.topic.content_types, "Should NOT have care_info"

    print("✓ ResearchDocumentWriter correctly classifies content types\n")
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("CONTENT-TYPE MATCHING TEST SUITE")
    print("Testing the hamster care scenario intelligence flow")
    print("=" * 60)

    results = []

    results.append(("Query Content Classification", test_query_content_classification()))
    results.append(("Findings Content Classification", test_findings_content_classification()))
    results.append(("Hamster Care Scenario", test_hamster_care_scenario()))
    results.append(("ResearchDocumentWriter Content Types", test_research_document_content_types()))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All tests passed! Content-type matching is working correctly.")
        print()
        print("The hamster care scenario:")
        print("  1. 'find Syrian hamsters for sale' → creates research with purchase_info")
        print("  2. 'how do I care for them' → needs care_info")
        print("  3. System correctly identifies that care_info is NOT covered")
        print("  4. System will trigger NEW research for care information")
    else:
        print("Some tests failed. Please review the output above.")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
