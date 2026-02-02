#!/usr/bin/env python3
"""Test script for context_ranker module."""

from dataclasses import dataclass
from datetime import datetime, timezone
from apps.services.orchestrator import context_ranker


@dataclass
class MockClaim:
    """Mock claim for testing."""
    text: str
    domain: str = "general"
    updated_at: str = datetime.now(timezone.utc).isoformat()
    confidence: str = "medium"


def test_rank_claims():
    """Test claim ranking."""
    claims = [
        MockClaim(
            text="User wants to search for hamster cages",
            domain="commerce",
            confidence="high"
        ),
        MockClaim(
            text="User prefers Syrian hamsters",
            domain="general",
            confidence="medium"
        ),
        MockClaim(
            text="Code repository is at /home/user/project",
            domain="code",
            confidence="high"
        ),
        MockClaim(
            text="User asked about hamster food yesterday",
            domain="commerce",
            confidence="low"
        ),
    ]

    # Test 1: Commerce-related goal
    print("Test 1: Commerce goal")
    ranked = context_ranker.rank_claims_by_relevance(
        claims,
        current_goal="I need to buy hamster food for my Syrian hamster",
        task_domain="commerce",
        max_results=3
    )
    print(f"  Results: {len(ranked)} items")
    for i, item in enumerate(ranked, 1):
        print(f"    {i}. Score: {item.score:.3f} | {item.item.text[:50]} | Reasons: {item.reasons}")
    print()

    # Test 2: Code-related goal
    print("Test 2: Code goal")
    ranked = context_ranker.rank_claims_by_relevance(
        claims,
        current_goal="Create a new Python file in the repository",
        task_domain="code",
        max_results=3
    )
    print(f"  Results: {len(ranked)} items")
    for i, item in enumerate(ranked, 1):
        print(f"    {i}. Score: {item.score:.3f} | {item.item.text[:50]} | Reasons: {item.reasons}")
    print()


def test_rank_memories():
    """Test memory ranking."""
    memories = [
        {
            "body": "User's favorite hamster is named Fluffy and is a Syrian hamster",
            "tags": ["preference", "hamster", "pet"],
            "metadata": {"type": "preference", "created_at": datetime.now(timezone.utc).isoformat()}
        },
        {
            "body": "User previously searched for hamster cages on Amazon",
            "tags": ["commerce", "shopping"],
            "metadata": {"type": "activity", "created_at": "2024-01-01T00:00:00Z"}
        },
        {
            "body": "User wrote a Python script to analyze hamster activity data",
            "tags": ["code", "python", "analytics"],
            "metadata": {"type": "activity", "created_at": datetime.now(timezone.utc).isoformat()}
        },
    ]

    print("Test 3: Memory ranking")
    ranked = context_ranker.rank_memories_by_relevance(
        memories,
        current_query="What do you know about my hamster?",
        user_context="pet preferences",
        max_results=3
    )
    print(f"  Results: {len(ranked)} items")
    for i, item in enumerate(ranked, 1):
        print(f"    {i}. Score: {item.score:.3f} | {item.item['body'][:50]} | Reasons: {item.reasons}")
    print()


def test_budget_aware_selection():
    """Test budget-aware selection."""
    claims = [
        MockClaim(text="Short claim", confidence="high"),
        MockClaim(text="This is a much longer claim with lots of text that will consume more tokens from the budget", confidence="medium"),
        MockClaim(text="Another medium claim here", confidence="medium"),
        MockClaim(text="Final short one", confidence="low"),
    ]

    print("Test 4: Budget-aware selection")
    ranked = context_ranker.rank_claims_by_relevance(
        claims,
        current_goal="test query",
        max_results=10
    )

    # Test with tight budget
    selected = context_ranker.budget_aware_selection(ranked, max_tokens=20, min_items=2)
    print(f"  Tight budget (20 tokens): {len(selected)} items selected")

    # Test with generous budget
    selected = context_ranker.budget_aware_selection(ranked, max_tokens=200, min_items=2)
    print(f"  Generous budget (200 tokens): {len(selected)} items selected")
    print()


def test_token_estimation():
    """Test token count estimation."""
    test_strings = [
        "Short",
        "This is a medium-length sentence with about 10 words in it.",
        "This is a very long paragraph with lots and lots of text. " * 10,
    ]

    print("Test 5: Token estimation")
    for s in test_strings:
        tokens = context_ranker.estimate_token_count(s)
        print(f"  '{s[:40]}...' => ~{tokens} tokens ({len(s)} chars)")
    print()


if __name__ == "__main__":
    print("=" * 80)
    print("Testing context_ranker module")
    print("=" * 80)
    print()

    test_rank_claims()
    test_rank_memories()
    test_budget_aware_selection()
    test_token_estimation()

    print("=" * 80)
    print("All tests completed successfully!")
    print("=" * 80)
