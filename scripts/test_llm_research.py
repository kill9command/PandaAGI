#!/usr/bin/env python3
"""
Test the new LLM-driven research system.

Usage:
    python scripts/test_llm_research.py "find me a cheap gaming laptop"
    python scripts/test_llm_research.py --phase1-only "what are the best budget laptops"
"""

import asyncio
import argparse
import json
import logging
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(name)-30s | %(message)s",
)

# Reduce noise from other loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def test_phase1(goal: str, context: str = "", task: str = ""):
    """Test Phase 1 only (informational)."""
    from apps.tools.internet_research import execute_research

    print(f"\n{'='*60}")
    print(f"PHASE 1 TEST")
    print(f"{'='*60}")
    print(f"Goal: {goal}")
    if context:
        print(f"Context: {context}")
    if task:
        print(f"Task: {task}")
    print()

    result = await execute_research(
        goal=goal,
        intent="informational",
        context=context,
        task=task,
    )

    print(f"\n{'='*60}")
    print("PHASE 1 RESULT")
    print(f"{'='*60}")
    print(f"Success: {result.success}")
    print(f"Searches used: {result.searches_used}")
    print(f"Pages visited: {result.pages_visited}")
    print(f"Elapsed: {result.elapsed_seconds:.1f}s")
    print(f"\nSources visited:")
    for url in result.sources:
        print(f"  - {url}")
    print(f"\nIntelligence gathered:")
    print(json.dumps(result.intelligence, indent=2))
    print(f"\nFindings:")
    for f in result.findings[:5]:
        print(f"  - {f}")
    print(f"\n--- Research State ---")
    print(result.research_state_md)

    return result


async def test_full(goal: str, context: str = "", task: str = "", target_vendors: int = 3):
    """Test full research (Phase 1 + Phase 2)."""
    from apps.tools.internet_research import execute_full_research

    print(f"\n{'='*60}")
    print(f"FULL RESEARCH TEST")
    print(f"{'='*60}")
    print(f"Goal: {goal}")
    if context:
        print(f"Context: {context}")
    if task:
        print(f"Task: {task}")
    print(f"Target vendors: {target_vendors}")
    print()

    result = await execute_full_research(
        goal=goal,
        intent="commerce",
        context=context,
        task=task,
        target_vendors=target_vendors,
    )

    print(f"\n{'='*60}")
    print("FULL RESEARCH RESULT")
    print(f"{'='*60}")
    print(f"Success: {result['success']}")
    print(f"Total elapsed: {result.get('total_elapsed_seconds', 0):.1f}s")

    # Phase 1 summary
    p1 = result.get("phase1", {})
    print(f"\n--- Phase 1 ---")
    print(f"Pages visited: {p1.get('pages_visited', 0)}")
    print(f"Vendor hints: {p1.get('vendor_hints', [])}")
    print(f"Search terms: {p1.get('search_terms', [])}")
    print(f"Price range: {p1.get('price_range', {})}")

    # Phase 2 summary
    p2 = result.get("phase2", {})
    print(f"\n--- Phase 2 ---")
    print(f"Vendors visited: {p2.get('vendors_visited', [])}")
    print(f"Vendors failed: {p2.get('vendors_failed', [])}")

    # Products
    products = result.get("products", [])
    print(f"\n--- Products Found ({len(products)}) ---")
    for p in products[:10]:
        print(f"  {p['name'][:50]:50} | {p['price']:12} | {p['vendor']}")

    # Recommendations
    print(f"\n--- Recommendation ---")
    print(result.get("recommendation", "None"))
    print(f"\n--- Price Assessment ---")
    print(result.get("price_assessment", "None"))

    # Research state
    if result.get("research_state"):
        print(f"\n--- Research State (Phase 1) ---")
        print(result["research_state"][:2000])

    return result


def main():
    parser = argparse.ArgumentParser(description="Test LLM-driven research")
    parser.add_argument("goal", help="The research goal/query (user's original words)")
    parser.add_argument("--context", default="", help="Session context (what we were discussing)")
    parser.add_argument("--task", default="", help="Specific task from Planner")
    parser.add_argument("--phase1-only", action="store_true", help="Run Phase 1 only")
    parser.add_argument("--vendors", type=int, default=3, help="Number of vendors for Phase 2")

    args = parser.parse_args()

    if args.phase1_only:
        asyncio.run(test_phase1(args.goal, context=args.context, task=args.task))
    else:
        asyncio.run(test_full(args.goal, context=args.context, task=args.task, target_vendors=args.vendors))


if __name__ == "__main__":
    main()
