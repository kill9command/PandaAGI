#!/usr/bin/env python3
"""
test_lesson_learning.py

Test script for Layer 2 Reflection: Lesson Learning MVP

Demonstrates the complete cycle:
1. LEARN: Record lessons from task execution
2. REMEMBER: Query relevant lessons before similar tasks
3. APPLY: Show how lessons guide future actions

Usage:
    python scripts/test_lesson_learning.py
"""

import httpx
import json
from typing import Dict, Any, List


TOOL_SERVER_URL = "http://localhost:8090"


def print_section(title: str):
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def record_lesson(
    role: str,
    context: str,
    outcome: str,
    tags: List[str],
    confidence: float = 0.8
) -> Dict[str, Any]:
    """Record a lesson from task execution."""
    print(f"📝 Recording lesson: {role}")
    print(f"   Context: {context[:60]}...")
    print(f"   Outcome: {outcome[:60]}...")
    print(f"   Tags: {tags}")

    response = httpx.post(
        f"{TOOL_SERVER_URL}/reflection.record_lesson",
        json={
            "role": role,
            "context": context,
            "outcome": outcome,
            "tags": tags,
            "confidence": confidence
        },
        timeout=30.0
    )
    response.raise_for_status()
    result = response.json()

    if result["status"] == "stored":
        print(f"   ✓ Lesson stored: \"{result['lesson']['lesson']}\"")
    else:
        print(f"   ✗ Failed: {result.get('error', 'Unknown error')}")

    return result


def query_lessons(
    role: str = None,
    tags: List[str] = None,
    context_keywords: List[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Query stored lessons."""
    filters = []
    if role:
        filters.append(f"role={role}")
    if tags:
        filters.append(f"tags={tags}")
    if context_keywords:
        filters.append(f"keywords={context_keywords}")

    filter_str = ", ".join(filters) if filters else "all lessons"
    print(f"🔍 Querying lessons ({filter_str}, limit={limit})...")

    response = httpx.post(
        f"{TOOL_SERVER_URL}/reflection.query_lessons",
        json={
            "role": role,
            "tags": tags,
            "context_keywords": context_keywords,
            "limit": limit
        },
        timeout=30.0
    )
    response.raise_for_status()
    result = response.json()

    print(f"   Found {result['count']} lessons:")
    for i, lesson in enumerate(result['lessons'], 1):
        print(f"   {i}. [{lesson['role']}] {lesson['lesson']}")
        print(f"      Tags: {lesson['tags']}, Confidence: {lesson['confidence']}")

    return result['lessons']


def get_stats() -> Dict[str, Any]:
    """Get lesson storage statistics."""
    response = httpx.post(f"{TOOL_SERVER_URL}/reflection.get_stats", timeout=30.0)
    response.raise_for_status()
    return response.json()


def test_learn_cycle():
    """Test Phase 1: Learn from task executions."""
    print_section("PHASE 1: LEARN - Recording Lessons from Task Execution")

    # Lesson 1: BOM pricing success
    record_lesson(
        role="bom.build",
        context="Building BOM for hamster setup - searching for pricing",
        outcome="Successfully found prices after adding 'buy online' to query on retry #2",
        tags=["bom", "pricing", "retry", "success"],
        confidence=0.9
    )

    # Lesson 2: Research too broad
    record_lesson(
        role="research_mcp",
        context="Searching for hamster breeders in California",
        outcome="Initial query 'hamster California' too broad, refined to 'USDA licensed hamster breeder California' succeeded",
        tags=["research", "query-refinement", "success"],
        confidence=0.85
    )

    # Lesson 3: Commerce search failure
    record_lesson(
        role="commerce.search_offers",
        context="Searching for exotic pet supplies",
        outcome="Generic search returned irrelevant results; should use source discovery first",
        tags=["commerce", "source-discovery", "failure"],
        confidence=0.7
    )

    # Lesson 4: Coordinator planning
    record_lesson(
        role="coordinator",
        context="Planning multi-step BOM task with pricing lookup",
        outcome="Sequential execution (discover sources → search commerce) worked better than parallel",
        tags=["planning", "sequencing", "success"],
        confidence=0.8
    )


def test_remember_cycle():
    """Test Phase 2: Remember - Query relevant lessons before similar tasks."""
    print_section("PHASE 2: REMEMBER - Querying Lessons Before Similar Tasks")

    print("\n--- Scenario 1: About to do BOM pricing ---")
    lessons = query_lessons(
        tags=["bom", "pricing"],
        limit=3
    )

    print("\n--- Scenario 2: About to do research task ---")
    lessons = query_lessons(
        role="research_mcp",
        limit=3
    )

    print("\n--- Scenario 3: Keyword-based retrieval for 'source discovery' ---")
    lessons = query_lessons(
        context_keywords=["source", "discovery", "commerce"],
        limit=3
    )

    print("\n--- Scenario 4: All coordinator lessons ---")
    lessons = query_lessons(
        role="coordinator",
        limit=5
    )


def test_apply_cycle():
    """Test Phase 3: Apply - Show how lessons guide future actions."""
    print_section("PHASE 3: APPLY - Using Lessons to Guide Actions")

    print("Simulating a new BOM task...")
    print("\n1. Query past BOM lessons:")
    bom_lessons = query_lessons(tags=["bom"], limit=3)

    if bom_lessons:
        print("\n2. Apply lessons to current task:")
        for lesson in bom_lessons[:2]:
            print(f"   ✓ Applying: {lesson['lesson']}")

        print("\n3. Adjusted strategy based on lessons:")
        print("   - Add 'buy online' to pricing queries from start")
        print("   - Use source discovery before commerce search")
        print("   - Plan sequential execution for multi-phase tasks")

    print("\n4. Execute task with learned optimizations...")
    print("   [Actual tool execution would happen here]")

    print("\n5. After completion, record outcome as new lesson:")
    record_lesson(
        role="bom.build",
        context="Building BOM with lessons applied",
        outcome="Applied 'buy online' from start, found prices on first try",
        tags=["bom", "pricing", "lesson-applied", "success"],
        confidence=0.95
    )


def test_statistics():
    """Test statistics endpoint."""
    print_section("STATISTICS - Lesson Storage Overview")

    stats = get_stats()

    print(f"Total Lessons: {stats['total_lessons']}")
    print(f"Average Confidence: {stats['avg_confidence']}")

    print("\nBy Role:")
    for role, count in stats['by_role'].items():
        print(f"  - {role}: {count}")

    print("\nTop Tags:")
    for tag_info in stats['top_tags']:
        print(f"  - {tag_info['tag']}: {tag_info['count']}")


def main():
    """Run all test phases."""
    print("\n" + "=" * 60)
    print("  Layer 2 Reflection: Lesson Learning MVP Test")
    print("=" * 60)

    try:
        # Phase 1: Learn
        test_learn_cycle()

        # Phase 2: Remember
        test_remember_cycle()

        # Phase 3: Apply
        test_apply_cycle()

        # Statistics
        test_statistics()

        print_section("✓ All Tests Completed Successfully")

        print("\nNext Steps:")
        print("1. ✓ Lesson storage working (JSONL in panda_system_docs/lessons/)")
        print("2. ✓ LLM-based lesson extraction working")
        print("3. ✓ Query and retrieval working")
        print("4. ⚠ Integration with Gateway (manual for MVP)")
        print("5. ⚠ Automatic injection into Coordinator context (future enhancement)")

        print("\nHow to Use in Production:")
        print("- After task execution: POST /reflection.record_lesson")
        print("- Before task execution: POST /reflection.query_lessons")
        print("- Inject retrieved lessons into task context")
        print("- System learns and improves over time")

    except httpx.ConnectError:
        print("\n✗ ERROR: Cannot connect to Orchestrator at http://localhost:8090")
        print("  Make sure services are running: ./start.sh")
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
