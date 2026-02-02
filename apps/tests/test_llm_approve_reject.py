#!/usr/bin/env python3
"""Test the new APPROVE/REJECT LLM filter implementation."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import asyncio
from libs.gateway.app import _llm_filter_cache_relevance
from apps.services.orchestrator.shared_state.claims import ClaimRow

def test_approve_reject_filter():
    """Test that the LLM filter correctly uses APPROVE/REJECT decisions."""
    print("=" * 80)
    print("LLM APPROVE/REJECT FILTER TEST")
    print("=" * 80)

    # Simulate the exact scenario from the transcript
    user_query = "Can you find some for sale online for me?"
    user_context = "my favorite hamster is Syrian"
    intent = "transactional"

    # Create test cache candidates
    candidates = [
        (
            ClaimRow(
                claim_id="test_russian_1",
                statement="North Yorkshire Hamster Breeder - Russian Dwarf Hamsters for Sale from vendor (unknown)",
                confidence=0.9,
                source_tool="commerce.search_offers",
                metadata={
                    "title": "North Yorkshire Hamster Breeder - Russian Dwarf Hamsters for Sale",
                    "link": "https://north-yorkshire-hamster-breeder.yolasite.com/",
                    "domain": "pricing",
                    "topics": ["purchase", "pricing"],
                    "matched_intent": "transactional"
                }
            ),
            0.75  # keyword_score
        ),
        (
            ClaimRow(
                claim_id="test_syrian_1",
                statement="Syrian Hamster Breeders Online - Premium Syrian Hamsters for Sale",
                confidence=0.9,
                source_tool="commerce.search_offers",
                metadata={
                    "title": "Syrian Hamster Breeders Online - Premium Syrian Hamsters",
                    "link": "https://syrian-hamster-breeders.com/",
                    "domain": "pricing",
                    "topics": ["purchase", "pricing"],
                    "matched_intent": "transactional"
                }
            ),
            0.80  # keyword_score
        ),
        (
            ClaimRow(
                claim_id="test_robo_1",
                statement="Roborovski Hamster Care Guide - Complete Care Instructions",
                confidence=0.85,
                source_tool="doc.search",
                metadata={
                    "title": "Roborovski Hamster Care Guide",
                    "link": "https://hamster-care.com/roborovski",
                    "domain": "informational",
                    "topics": ["care", "guide"],
                    "matched_intent": "informational"
                }
            ),
            0.60  # keyword_score
        ),
        (
            ClaimRow(
                claim_id="test_syrian_2",
                statement="Golden Hamster (Syrian) Breeders - Pet Quality Syrian Hamsters",
                confidence=0.88,
                source_tool="commerce.search_offers",
                metadata={
                    "title": "Golden Hamster Breeders",
                    "link": "https://golden-hamster-breeders.com/",
                    "domain": "pricing",
                    "topics": ["purchase", "breeding"],
                    "matched_intent": "transactional"
                }
            ),
            0.72  # keyword_score
        ),
    ]

    print(f"\nUser query: {user_query}")
    print(f"User context: {user_context}")
    print(f"Intent: {intent}")
    print(f"\nTest candidates: {len(candidates)}")

    for i, (claim, score) in enumerate(candidates, 1):
        print(f"\n{i}. {claim.statement[:70]}...")
        print(f"   Keyword score: {score:.2f}")
        print(f"   Claim ID: {claim.claim_id}")

    print("\n" + "-" * 80)
    print("Calling LLM filter with APPROVE/REJECT logic...")
    print("-" * 80)

    try:
        # Run the filter
        filtered = _llm_filter_cache_relevance(
            query=user_query,
            candidates=candidates,
            intent=intent,
            user_context=user_context
        )

        print(f"\n✓ LLM filter completed successfully")
        print(f"  Input candidates: {len(candidates)}")
        print(f"  Filtered results: {len(filtered)}")

        print("\n" + "=" * 80)
        print("RESULTS")
        print("=" * 80)

        if filtered:
            print(f"\n✓ {len(filtered)} candidates APPROVED by LLM:")
            for claim, score in filtered:
                print(f"\n  ✓ APPROVED: {claim.statement[:70]}...")
                print(f"    Claim ID: {claim.claim_id}")
                print(f"    Keyword score: {score:.2f}")
        else:
            print("\n✗ No candidates approved by LLM")

        # Verify expected behavior
        approved_ids = {claim.claim_id for claim, _ in filtered}
        rejected_ids = {claim.claim_id for claim, _ in candidates if claim.claim_id not in approved_ids}

        print(f"\n  Rejected by LLM: {len(rejected_ids)} candidates")
        for claim, score in candidates:
            if claim.claim_id in rejected_ids:
                print(f"    ✗ REJECTED: {claim.statement[:70]}...")
                print(f"      Claim ID: {claim.claim_id}")

        # Validate expectations
        print("\n" + "=" * 80)
        print("VALIDATION")
        print("=" * 80)

        all_passed = True

        # Russian Dwarf should be REJECTED
        if "test_russian_1" in approved_ids:
            print("\n✗ FAIL: Russian Dwarf hamster was APPROVED (should be REJECTED)")
            all_passed = False
        else:
            print("\n✓ PASS: Russian Dwarf hamster was REJECTED (correct)")

        # Syrian hamsters should be APPROVED
        syrian_approved = [cid for cid in ["test_syrian_1", "test_syrian_2"] if cid in approved_ids]
        if not syrian_approved:
            print("✗ FAIL: No Syrian hamster results were APPROVED (at least one should be)")
            all_passed = False
        else:
            print(f"✓ PASS: {len(syrian_approved)} Syrian hamster result(s) APPROVED")

        # Roborovski care guide should be REJECTED (wrong intent)
        if "test_robo_1" in approved_ids:
            print("✗ FAIL: Roborovski care guide was APPROVED (should be REJECTED - wrong intent)")
            all_passed = False
        else:
            print("✓ PASS: Roborovski care guide was REJECTED (wrong intent)")

        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)

        if all_passed:
            print("\n✓ ALL VALIDATION CHECKS PASSED")
            print("✓ LLM correctly uses APPROVE/REJECT decisions")
            print("✓ Species matching works correctly")
            print("✓ Intent filtering works correctly")
            return True
        else:
            print("\n✗ SOME VALIDATION CHECKS FAILED")
            print("Review the results above for details")
            return False

    except Exception as e:
        print(f"\n✗ ERROR: LLM filter failed with exception:")
        print(f"  {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_approve_reject_filter()
    sys.exit(0 if success else 1)
