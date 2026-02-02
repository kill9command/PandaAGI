#!/usr/bin/env python3
"""
Test script for Session Knowledge System.

Tests:
1. Topic creation and retrieval
2. Claim categorization
3. Semantic search
4. Knowledge retrieval and Phase 1 skip decisions

Usage:
    python scripts/test_knowledge_system.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.services.orchestrator.shared_state.claim_types import ClaimType
from apps.services.orchestrator.shared_state.topic_index import TopicIndex, get_topic_index
from apps.services.orchestrator.knowledge_retriever import KnowledgeRetriever, get_knowledge_retriever
from apps.services.orchestrator.knowledge_extractor import KnowledgeExtractor, get_knowledge_extractor


def test_claim_types():
    """Test ClaimType categorization."""
    print("\n=== Testing ClaimType Categorization ===")

    test_cases = [
        ("Amazon sells RTX 4060 laptops", ClaimType.RETAILER),
        ("Best Buy carries gaming laptops", ClaimType.RETAILER),
        ("RTX 4060 laptops range from $700-$1000", ClaimType.MARKET_INFO),
        ("Current price is $799 at Amazon", ClaimType.PRICE),
        ("Check for open-box deals at Best Buy", ClaimType.BUYING_TIP),
        ("RTX 4060 has 8GB VRAM", ClaimType.SPEC_INFO),
        ("In stock at Newegg", ClaimType.AVAILABILITY),
        ("User prefers budget options", ClaimType.PREFERENCE),
        ("Must have 16GB RAM minimum", ClaimType.CONSTRAINT),
        ("Some random statement", ClaimType.GENERAL),
    ]

    passed = 0
    for statement, expected_type in test_cases:
        result = ClaimType.from_statement(statement)
        status = "✓" if result == expected_type else "✗"
        if result == expected_type:
            passed += 1
        print(f"  {status} '{statement[:40]}...' → {result.value} (expected: {expected_type.value})")

    print(f"\n  Passed: {passed}/{len(test_cases)}")
    return passed == len(test_cases)


def test_topic_index():
    """Test TopicIndex creation and retrieval."""
    print("\n=== Testing TopicIndex ===")

    # Use test database
    test_db = Path("panda_system_docs/shared_state/test_knowledge.db")
    test_db.parent.mkdir(parents=True, exist_ok=True)

    # Clean up old test data
    if test_db.exists():
        test_db.unlink()

    topic_index = TopicIndex(test_db)

    # Create a topic
    print("  Creating topic: NVIDIA RTX 4060 Laptops")
    topic = topic_index.create_topic(
        session_id="test_session",
        topic_name="NVIDIA RTX 4060 Laptops",
        topic_slug="nvidia_rtx_4060_laptops",
        parent_id=None,
        source_query="find laptop with rtx 4060",
        retailers=["amazon", "bestbuy", "newegg"],
        price_range={"min": 700, "max": 1200},
        key_specs=["RTX 4060", "16GB RAM", "512GB SSD"],
    )
    print(f"  ✓ Created topic: {topic.topic_id}")

    # Retrieve topic
    retrieved = topic_index.get_topic(topic.topic_id)
    assert retrieved is not None, "Failed to retrieve topic"
    assert retrieved.topic_name == "NVIDIA RTX 4060 Laptops"
    print(f"  ✓ Retrieved topic: {retrieved.topic_name}")

    # Search by query
    print("  Searching for 'rtx 4060 gaming laptop'...")
    matches = topic_index.search_by_query(
        query="rtx 4060 gaming laptop",
        session_id="test_session",
        min_similarity=0.5,
    )
    print(f"  ✓ Found {len(matches)} matching topics")
    if matches:
        print(f"    Best match: {matches[0].topic.topic_name} (similarity: {matches[0].similarity:.2f})")

    # Create child topic
    print("  Creating child topic: Budget RTX 4060 Laptops")
    child = topic_index.create_topic(
        session_id="test_session",
        topic_name="Budget RTX 4060 Laptops",
        topic_slug="budget_rtx_4060_laptops",
        parent_id=topic.topic_id,
        source_query="cheap rtx 4060 laptop under 800",
        retailers=["amazon"],
        price_range={"min": 700, "max": 800},
    )
    print(f"  ✓ Created child topic: {child.topic_id}")

    # Test inheritance
    inherited = topic_index.resolve_inheritance(child.topic_id)
    print(f"  ✓ Inherited knowledge: {len(inherited['retailers'])} retailers, {len(inherited['key_specs'])} specs")

    # Clean up
    test_db.unlink()
    print("  ✓ Cleaned up test database")

    return True


async def test_knowledge_retriever():
    """Test KnowledgeRetriever."""
    print("\n=== Testing KnowledgeRetriever ===")

    # Use test database
    test_db = Path("panda_system_docs/shared_state/test_knowledge.db")

    # Clean up old test data
    if test_db.exists():
        test_db.unlink()

    # First create some topics (this also creates claims table with topic columns)
    topic_index = TopicIndex(test_db)

    topic_index.create_topic(
        session_id="test_session",
        topic_name="NVIDIA Gaming Laptops",
        topic_slug="nvidia_gaming_laptops",
        retailers=["amazon", "bestbuy", "newegg"],
        price_range={"min": 700, "max": 2000},
        key_specs=["NVIDIA GPU", "Gaming Display"],
    )

    topic_index.create_topic(
        session_id="test_session",
        topic_name="RTX 4060 Laptops",
        topic_slug="rtx_4060_laptops",
        retailers=["amazon", "bestbuy"],
        price_range={"min": 700, "max": 1000},
        key_specs=["RTX 4060", "8GB VRAM"],
    )

    # Create claim registry for test database
    from apps.services.orchestrator.shared_state.claims import ClaimRegistry
    test_claim_registry = ClaimRegistry(test_db)

    # Test retrieval using custom retriever with injected registry
    retriever = KnowledgeRetriever("test_session", test_db)
    retriever._claim_registry = test_claim_registry  # Inject test registry

    print("  Querying: 'laptop with rtx 4060'")
    context = await retriever.retrieve_for_query("laptop with rtx 4060")

    print(f"  ✓ Retrieved knowledge context:")
    print(f"    - Topics matched: {len(context.matched_topics)}")
    print(f"    - Best similarity: {context.best_match_similarity:.2f}")
    print(f"    - Retailers: {context.retailers}")
    print(f"    - Knowledge completeness: {context.knowledge_completeness:.0%}")
    print(f"    - Phase 1 skip recommended: {context.phase1_skip_recommended}")
    print(f"    - Reason: {context.phase1_skip_reason}")

    # Clean up
    test_claim_registry.close()
    test_db.unlink()

    return True


async def test_knowledge_extractor():
    """Test KnowledgeExtractor."""
    print("\n=== Testing KnowledgeExtractor ===")

    extractor = KnowledgeExtractor("test_session")

    # Test rule-based extraction
    print("  Testing rule-based topic extraction...")

    result = extractor._extract_topic_rules(
        query="find cheap gaming laptop with rtx 4060",
        vendors=["amazon.com", "bestbuy.com"],
        products=[{"price": 799}, {"price": 899}],
    )

    if result:
        print(f"  ✓ Extracted topic:")
        print(f"    - Name: {result.topic_name}")
        print(f"    - Slug: {result.topic_slug}")
        print(f"    - Retailers: {result.retailers}")
        print(f"    - Price range: {result.price_range}")
    else:
        print("  ✗ Failed to extract topic")
        return False

    return True


async def test_end_to_end():
    """Test end-to-end flow: extract → store → retrieve → skip decision."""
    print("\n=== Testing End-to-End Flow ===")

    test_db = Path("panda_system_docs/shared_state/test_e2e_knowledge.db")
    if test_db.exists():
        test_db.unlink()

    session_id = "e2e_test_session"

    # Create topic index (also creates claims table)
    topic_index = TopicIndex(test_db)

    # Create claim registry for test
    from apps.services.orchestrator.shared_state.claims import ClaimRegistry
    test_claim_registry = ClaimRegistry(test_db)

    # Simulate first query - should NOT skip Phase 1
    print("\n  Query 1: 'laptop with rtx 4060'")
    retriever = KnowledgeRetriever(session_id, test_db)
    retriever._claim_registry = test_claim_registry
    context1 = await retriever.retrieve_for_query("laptop with rtx 4060")
    print(f"    Phase 1 skip: {context1.phase1_skip_recommended} (expected: False)")

    # Simulate research completion - store knowledge
    print("\n  Storing knowledge from research...")
    topic_index.create_topic(
        session_id=session_id,
        topic_name="RTX 4060 Laptops",
        topic_slug="rtx_4060_laptops",
        source_query="laptop with rtx 4060",
        retailers=["amazon", "bestbuy", "newegg"],
        price_range={"min": 700, "max": 1000},
        key_specs=["RTX 4060", "8GB VRAM", "16GB RAM"],
    )
    print("    ✓ Stored topic: RTX 4060 Laptops")

    # Simulate follow-up query - SHOULD skip Phase 1
    print("\n  Query 2: 'rtx 4060 laptop under 900' (follow-up)")
    context2 = await retriever.retrieve_for_query("rtx 4060 laptop under 900")
    print(f"    Matched topics: {len(context2.matched_topics)}")
    print(f"    Retailers: {context2.retailers}")
    print(f"    Knowledge completeness: {context2.knowledge_completeness:.0%}")
    print(f"    Phase 1 skip: {context2.phase1_skip_recommended} (expected: True)")
    print(f"    Reason: {context2.phase1_skip_reason}")

    success = context2.phase1_skip_recommended and len(context2.retailers) >= 2
    print(f"\n  {'✓' if success else '✗'} End-to-end test {'passed' if success else 'FAILED'}")

    # Clean up
    test_claim_registry.close()
    test_db.unlink()

    return success


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Session Knowledge System Tests")
    print("=" * 60)

    results = []

    # Test 1: ClaimType categorization
    results.append(("ClaimType", test_claim_types()))

    # Test 2: TopicIndex
    results.append(("TopicIndex", test_topic_index()))

    # Test 3: KnowledgeRetriever
    results.append(("KnowledgeRetriever", await test_knowledge_retriever()))

    # Test 4: KnowledgeExtractor
    results.append(("KnowledgeExtractor", await test_knowledge_extractor()))

    # Test 5: End-to-end
    results.append(("End-to-End", await test_end_to_end()))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_passed = False

    print("\n" + ("All tests passed!" if all_passed else "Some tests failed."))
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
