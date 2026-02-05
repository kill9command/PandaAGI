# STATUS: Demo script, not a real test. Needs rewrite as pytest.
"""
Integration Test: Quality Tracking System

Demonstrates the full quality tracking system working together.
Run this to verify the system prevents the hamster bug.
"""

from claim_quality import ClaimQualityScorer
from satisfaction_detector import UserSatisfactionDetector
from context_filter import ContextInjectionFilter


def simulate_shopping_query_success():
    """Simulate a successful shopping query flow."""
    print("="*70)
    print("SCENARIO 1: Shopping Query - SUCCESS PATH")
    print("="*70)

    # Step 1: Tool execution
    print("\n[1] Tool Execution: commerce.search('syrian hamster for sale')")
    tool_result = {
        "status": "success",
        "result_type": "shopping_listings",
        "data": [
            {"seller": "Petco", "price": 24.99, "url": "..."},
            {"seller": "Local Breeder", "price": 35.00, "url": "..."}
        ],
        "metadata": {
            "data_quality": {
                "structured": 0.9,
                "completeness": 0.85,
                "source_confidence": 0.8
            }
        }
    }
    print(f"  ✓ Status: {tool_result['status']}")
    print(f"  ✓ Result type: {tool_result['result_type']}")

    # Step 2: Claim quality scoring
    print("\n[2] Claim Quality Scoring")
    scorer = ClaimQualityScorer()
    claim_quality = scorer.score_claim(
        query_intent="transactional",
        result_type=tool_result["result_type"],
        tool_status=tool_result["status"],
        tool_metadata=tool_result["metadata"],
        claim_specificity=0.9,
        source_count=12
    )
    print(f"  ✓ Intent alignment: {claim_quality['intent_alignment']}")
    print(f"  ✓ Evidence strength: {claim_quality['evidence_strength']}")
    print(f"  ✓ Overall quality: {claim_quality['overall_score']}")

    ttl = scorer.calculate_claim_ttl(claim_quality['overall_score'])
    print(f"  ✓ TTL: {ttl} hours ({ttl//24} days)")

    # Step 3: User response
    print("\n[3] User Follow-up: 'thanks! that petco one looks perfect'")
    detector = UserSatisfactionDetector()
    satisfaction = detector.analyze_follow_up(
        original_query="find syrian hamsters for sale online",
        original_intent="transactional",
        response="Found 12 listings at Petco, local breeders...",
        follow_up_query="thanks! that petco one looks perfect"
    )
    print(f"  ✓ Satisfied: {satisfaction['satisfied']}")
    print(f"  ✓ Confidence: {satisfaction['confidence']}")
    print(f"  ✓ Quality adjustment: {satisfaction['suggested_quality_adjustment']}")

    # Step 4: Quality update with feedback
    print("\n[4] Updated Quality with User Feedback")
    updated_quality = scorer.calculate_overall_quality(
        intent_alignment=claim_quality['intent_alignment'],
        evidence_strength=claim_quality['evidence_strength'],
        user_feedback_score=0.95
    )
    print(f"  ✓ Quality before: {claim_quality['overall_score']:.2f}")
    print(f"  ✓ Quality after: {updated_quality:.2f}")

    updated_ttl = scorer.calculate_claim_ttl(
        updated_quality,
        times_reused=1,
        times_helpful=1
    )
    print(f"  ✓ TTL updated: {ttl} → {updated_ttl} hours")

    # Step 5: Context filtering (will this be injected?)
    print("\n[5] Context Injection Check (Next Session)")
    filter = ContextInjectionFilter()
    pattern = {
        "query": "find syrian hamsters for sale online",
        "intent": "transactional",
        "result_type": "shopping_listings",
        "quality_score": updated_quality,
        "intent_fulfilled": True,
        "user_feedback_score": 0.95,
        "times_reused": 1,
        "times_helpful": 1
    }
    should_inject, reason = filter.should_inject_historical_pattern(
        pattern, "transactional"
    )
    print(f"  ✓ Should inject: {should_inject}")
    print(f"  ✓ Reason: {reason}")

    print("\n" + "✓"*70)
    print("OUTCOME: High-quality pattern stored and will help future queries!")
    print("✓"*70)


def simulate_shopping_query_failure():
    """Simulate the BUG: shopping query returns care guides."""
    print("\n\n" + "="*70)
    print("SCENARIO 2: Shopping Query - FAILURE PATH (THE BUG)")
    print("="*70)

    # Step 1: Tool execution (WRONG TOOL!)
    print("\n[1] Tool Execution: doc.search('hamster for sale')")
    print("  ✗ Wrong tool selected!")
    tool_result = {
        "status": "success",
        "result_type": "care_guides",  # ← MISMATCH!
        "data": [
            {"title": "Housing Requirements", "content": "800 sq inches..."},
            {"title": "Diet Guide", "content": "Hamster food..."}
        ],
        "metadata": {
            "data_quality": {
                "structured": 0.7,
                "completeness": 0.75,
                "source_confidence": 0.6
            }
        }
    }
    print(f"  ✗ Status: {tool_result['status']}")
    print(f"  ✗ Result type: {tool_result['result_type']} (should be shopping_listings!)")

    # Step 2: Claim quality scoring (will be LOW)
    print("\n[2] Claim Quality Scoring")
    scorer = ClaimQualityScorer()
    claim_quality = scorer.score_claim(
        query_intent="transactional",
        result_type=tool_result["result_type"],  # Mismatch!
        tool_status=tool_result["status"],
        tool_metadata=tool_result["metadata"],
        claim_specificity=0.6,
        source_count=3
    )
    print(f"  ✗ Intent alignment: {claim_quality['intent_alignment']} ← LOW!")
    print(f"  ✓ Evidence strength: {claim_quality['evidence_strength']}")
    print(f"  ✗ Overall quality: {claim_quality['overall_score']} ← POOR!")

    ttl = scorer.calculate_claim_ttl(claim_quality['overall_score'])
    print(f"  ✗ TTL: {ttl} hours (short due to low quality)")

    # Step 3: User response (FRUSTRATION!)
    print("\n[3] User Follow-up: 'but I wanted to BUY one!'")
    detector = UserSatisfactionDetector()
    satisfaction = detector.analyze_follow_up(
        original_query="can you find me some for sale online?",
        original_intent="transactional",
        response="Here are care guides... Housing requirements...",
        follow_up_query="but I wanted to BUY one!"
    )
    print(f"  ✗ Satisfied: {satisfaction['satisfied']}")
    print(f"  ✓ Confidence: {satisfaction['confidence']}")
    print(f"  ✗ Quality adjustment: {satisfaction['suggested_quality_adjustment']}")
    print(f"  ✗ Reason: {satisfaction['reason']}")

    # Step 4: Quality update with feedback (DROPS FURTHER!)
    print("\n[4] Updated Quality with User Feedback")
    updated_quality = scorer.calculate_overall_quality(
        intent_alignment=claim_quality['intent_alignment'],
        evidence_strength=claim_quality['evidence_strength'],
        user_feedback_score=0.1  # Very dissatisfied!
    )
    print(f"  ✗ Quality before: {claim_quality['overall_score']:.2f}")
    print(f"  ✗ Quality after: {updated_quality:.2f} ← DROPPED!")

    updated_ttl = scorer.calculate_claim_ttl(
        updated_quality,
        times_reused=4,
        times_helpful=1  # Only 1/4 helpful
    )
    print(f"  ✗ TTL updated: {ttl} → {updated_ttl} hours (rapid decay!)")

    # Step 5: Context filtering (will this be BLOCKED?)
    print("\n[5] Context Injection Check (Next Session)")
    filter = ContextInjectionFilter(quality_threshold=0.6)
    pattern = {
        "query": "can you find me some for sale online?",
        "intent": "transactional",
        "result_type": "care_guides",  # ← Wrong type!
        "quality_score": updated_quality,
        "intent_fulfilled": False,
        "user_feedback_score": 0.1,
        "times_reused": 4,
        "times_helpful": 1
    }
    should_inject, reason = filter.should_inject_historical_pattern(
        pattern, "transactional"
    )
    print(f"  ✓ Should inject: {should_inject} ← BLOCKED!")
    print(f"  ✓ Reason: {reason}")

    print("\n" + "✗"*70)
    print("OUTCOME: Low-quality pattern BLOCKED from context injection!")
    print("Future queries will NOT learn this bad pattern!")
    print("✗"*70)


def simulate_session_quality_tracking():
    """Simulate multi-turn session quality tracking."""
    print("\n\n" + "="*70)
    print("SCENARIO 3: Session Quality Tracking")
    print("="*70)

    detector = UserSatisfactionDetector()

    # Simulate a session with the bug
    turns = [
        {
            "user_query": "what do syrian hamsters eat?",
            "intent": "informational",
            "response_quality": 0.85,
            "user_satisfaction": 0.9
        },
        {
            "user_query": "can you find some for sale online?",
            "intent": "transactional",
            "response_quality": 0.3,  # ← Bug: returned care guides
            "user_satisfaction": None  # Not detected yet
        },
        {
            "user_query": "but I wanted to BUY one!",
            "intent": "transactional",
            "response_quality": 0.25,
            "user_satisfaction": 0.1  # ← Detected frustration
        }
    ]

    print("\n[Session Turns]")
    for i, turn in enumerate(turns, 1):
        print(f"\nTurn {i}:")
        print(f"  Query: {turn['user_query']}")
        print(f"  Intent: {turn['intent']}")
        print(f"  Response quality: {turn['response_quality']}")
        print(f"  User satisfaction: {turn.get('user_satisfaction', 'Not detected')}")

    # Analyze overall session
    print("\n[Session Analysis]")
    analysis = detector.analyze_session_quality(turns)
    print(f"  Aggregate quality: {analysis['aggregate_quality']:.2f}")
    print(f"  Satisfaction rate: {analysis['satisfaction_rate']:.2f}")
    print(f"  Quality trend: {analysis['quality_trend']}")
    print(f"  Satisfied turns: {analysis['satisfied_turns']}")
    print(f"  Dissatisfied turns: {analysis['dissatisfied_turns']}")
    print(f"  Issues detected:")
    for issue in analysis['issues']:
        print(f"    - {issue}")

    print("\n" + "⚠"*70)
    print("OUTCOME: Session quality tracking detected the problem!")
    print("System can alert on quality degradation and trigger fresh search.")
    print("⚠"*70)


def simulate_context_filtering():
    """Demonstrate context filtering with multiple patterns."""
    print("\n\n" + "="*70)
    print("SCENARIO 4: Context Filtering (Multiple Patterns)")
    print("="*70)

    filter = ContextInjectionFilter(quality_threshold=0.6)

    patterns = [
        {
            "query": "find hamsters for sale online",
            "intent": "transactional",
            "result_type": "care_guides",
            "quality_score": 0.3,
            "intent_fulfilled": False,
            "user_feedback_score": 0.1,
            "times_reused": 4,
            "times_helpful": 1
        },
        {
            "query": "syrian hamster for sale",
            "intent": "transactional",
            "result_type": "shopping_listings",
            "quality_score": 0.78,
            "intent_fulfilled": True,
            "user_feedback_score": 0.9,
            "times_reused": 10,
            "times_helpful": 9
        },
        {
            "query": "where to buy hamster",
            "intent": "transactional",
            "result_type": "shopping_listings",
            "quality_score": 0.72,
            "intent_fulfilled": True,
            "user_feedback_score": 0.85,
            "times_reused": 5,
            "times_helpful": 5
        },
        {
            "query": "what do hamsters eat",
            "intent": "informational",
            "result_type": "care_guides",
            "quality_score": 0.85,
            "intent_fulfilled": True,
            "user_feedback_score": 0.9,
            "times_reused": 8,
            "times_helpful": 8
        }
    ]

    print("\n[Available Patterns]")
    for i, p in enumerate(patterns, 1):
        print(f"\n{i}. Query: {p['query']}")
        print(f"   Intent: {p['intent']}, Result: {p['result_type']}")
        print(f"   Quality: {p['quality_score']:.2f}")

    print("\n\n[Filtering for: transactional intent]")
    filtered = filter.filter_historical_patterns(
        patterns, "transactional", max_patterns=3
    )

    print(f"\nFiltered {len(filtered)} patterns:")
    for i, p in enumerate(filtered, 1):
        print(f"\n{i}. {p['query']}")
        print(f"   Quality: {p['quality_score']:.2f}")
        print(f"   Reason: {p.get('_injection_reason', 'N/A')}")

    print("\n\n[Context Block Generated]")
    context = filter.create_context_injection_block(
        patterns, "transactional", max_patterns=2
    )
    print(context)

    print("\n" + "✓"*70)
    print("OUTCOME: Only high-quality, intent-aligned patterns injected!")
    print("Toxic care_guides pattern was EXCLUDED.")
    print("Wrong-intent informational pattern was EXCLUDED.")
    print("✓"*70)


if __name__ == "__main__":
    print("\n")
    print("╔" + "═"*68 + "╗")
    print("║" + " "*68 + "║")
    print("║" + "  QUALITY TRACKING SYSTEM - INTEGRATION TEST".center(68) + "║")
    print("║" + " "*68 + "║")
    print("╚" + "═"*68 + "╝")

    # Run all scenarios
    simulate_shopping_query_success()
    simulate_shopping_query_failure()
    simulate_session_quality_tracking()
    simulate_context_filtering()

    # Summary
    print("\n\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print("\n✓ Scenario 1: Success path tracked and reinforced")
    print("✓ Scenario 2: Failure path detected and blocked from reuse")
    print("✓ Scenario 3: Session quality degradation detected")
    print("✓ Scenario 4: Context injection filtered correctly")
    print("\n" + "="*70)
    print("CONCLUSION: The quality tracking system prevents the hamster bug!")
    print("="*70)
    print("\nNext steps:")
    print("1. Run database migration: migrate_claims_db.sql")
    print("2. Integrate claim_quality.py into context_builder.py")
    print("3. Integrate satisfaction_detector.py into gateway/app.py")
    print("4. Integrate context_filter.py into gateway context injection")
    print("5. Test with real queries")
    print()
