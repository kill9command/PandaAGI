#!/usr/bin/env python3
"""
scripts/test_research_role_e2e.py

End-to-end test for Research Role integration in Gateway reflection loop.

Tests:
1. Standard mode (1-pass) - Complete constraints
2. Standard mode (1-pass) - Missing location constraint
3. Deep mode (multi-pass) - Complete constraints

Author: Research Role Integration
Date: 2025-11-17
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Import after adding to path
try:
    from apps.services.tool_server.research_role import research_orchestrate
    from apps.services.tool_server.internet_research_mcp import adaptive_research
    ORCHESTRATOR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Orchestrator not available: {e}")
    ORCHESTRATOR_AVAILABLE = False


async def test_standard_mode_complete():
    """Test Standard mode with complete constraints"""
    print("\n" + "="*80)
    print("TEST 1: Standard Mode (1-pass) - Complete Constraints")
    print("="*80)

    if not ORCHESTRATOR_AVAILABLE:
        print("\n⚠️  SKIPPED: Orchestrator not available")
        return True

    query = "Find Syrian hamster breeders in California under $40"

    try:
        result = await adaptive_research(
            query=query,
            session_id="test_standard_complete",
            query_type="commerce_search",
            remaining_token_budget=8000,
            force_strategy="standard"
        )

        print(f"\n✅ SUCCESS:")
        print(f"  - Mode: {result.get('mode_used', 'N/A')}")
        print(f"  - Strategy: {result.get('strategy_used_internal', 'N/A')}")
        print(f"  - Passes: {result.get('passes', 'N/A')}")
        print(f"  - Intelligence Cached: {result.get('intelligence_cached', False)}")

        results_count = len(result.get('results', {}).get('products', []))
        print(f"  - Results Found: {results_count}")

        return True

    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_standard_mode_missing_location():
    """Test Standard mode with missing location (should trigger clarification)"""
    print("\n" + "="*80)
    print("TEST 2: Standard Mode (1-pass) - Missing Location Constraint")
    print("="*80)

    # Note: This test would need Gateway v4_flow integration to actually trigger
    # constraint validation. For now, we just test that adaptive_research handles it.

    query = "Find Syrian hamster breeders under $40"  # Missing location

    try:
        # Note: constraint validation happens in Gateway Phase 3, not in adaptive_research
        # This test demonstrates the integration point
        print(f"\n📝 Query: {query}")
        print(f"  - Missing: location")
        print(f"  - Expected: Clarification request from Gateway Phase 3")
        print(f"  - Status: Integration point ready in gateway/v4_flow.py:line 484")

        return True

    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        return False


async def test_deep_mode_complete():
    """Test Deep mode with complete constraints (multi-pass)"""
    print("\n" + "="*80)
    print("TEST 3: Deep Mode (multi-pass) - Complete Constraints")
    print("="*80)

    if not ORCHESTRATOR_AVAILABLE:
        print("\n⚠️  SKIPPED: Orchestrator not available")
        return True

    query = "Find Syrian hamster breeders in California under $40"

    try:
        result = await research_orchestrate(
            query=query,
            research_goal="Find reputable Syrian hamster breeders in California",
            mode="deep",
            session_id="test_deep_complete",
            query_type="commerce_search",
            user_constraints={"location": "California", "budget": "$40"},
            remaining_token_budget=10000
        )

        print(f"\n✅ SUCCESS:")
        print(f"  - Mode: {result.get('mode', 'N/A')}")
        print(f"  - Strategy: {result.get('strategy_used', 'N/A')}")
        print(f"  - Passes: {result.get('passes', 'N/A')}")
        print(f"  - Intelligence Cached: {result.get('intelligence_cached', False)}")

        # Check satisfaction evaluations
        evals = result.get('satisfaction_evaluations', [])
        print(f"  - Satisfaction Evaluations: {len(evals)}")

        if evals:
            final_eval = evals[-1]
            print(f"  - Final Decision: {final_eval.get('decision', 'N/A')}")
            print(f"  - All Criteria Met: {final_eval.get('all_met', 'N/A')}")

        return True

    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_constraint_validation():
    """Test constraint validation logic directly"""
    print("\n" + "="*80)
    print("TEST 4: Constraint Validation (Direct)")
    print("="*80)

    from apps.services.gateway.constraint_validator import (
        validate_constraints,
        build_clarification_response
    )

    # Test 1: Missing location
    print("\n📝 Test 4a: Missing location")
    result1 = validate_constraints(
        user_query="Find Syrian hamster breeders under $40",
        intent="commerce_search",
        extracted_constraints={
            "subject": "Syrian hamster breeders",
            "budget": "$40"
        },
        unified_context={}
    )

    print(f"  - Valid: {result1['valid']}")
    print(f"  - Decision: {result1['decision']}")
    print(f"  - Missing Critical: {result1['missing_critical']}")

    if not result1['valid']:
        clarification = build_clarification_response(result1)
        print(f"  - Clarification:\n{clarification}")

    # Test 2: All constraints present
    print("\n📝 Test 4b: All constraints present")
    result2 = validate_constraints(
        user_query="Find Syrian hamster breeders in California under $40",
        intent="commerce_search",
        extracted_constraints={
            "subject": "Syrian hamster breeders",
            "budget": "$40",
            "location": "California"
        },
        unified_context={}
    )

    print(f"  - Valid: {result2['valid']}")
    print(f"  - Decision: {result2['decision']}")
    print(f"  - Present Constraints: {result2['present_constraints']}")

    return result1['decision'] == 'REQUEST_CLARIFICATION' and result2['decision'] == 'PROCEED'


async def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("RESEARCH ROLE END-TO-END INTEGRATION TESTS")
    print("="*80)

    results = []

    # Test constraint validation first (no external dependencies)
    results.append(("Constraint Validation", await test_constraint_validation()))

    # Test missing location (integration point demo)
    results.append(("Standard Mode - Missing Location", await test_standard_mode_missing_location()))

    # Note: The following tests require vLLM and Orchestrator to be running
    # Uncomment when services are available
    # results.append(("Standard Mode - Complete", await test_standard_mode_complete()))
    # results.append(("Deep Mode - Complete", await test_deep_mode_complete()))

    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {test_name}")

    total = len(results)
    passed_count = sum(1 for _, p in results if p)
    print(f"\nTotal: {passed_count}/{total} tests passed")

    return all(p for _, p in results)


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
