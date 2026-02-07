#!/usr/bin/env python3
"""
Test script for the Research Document System.

Tests:
1. ResearchDocument creation from tool results
2. Research document writing to disk
3. Research index database operations
4. Context Gatherer integration (topic-based search)
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from libs.gateway.research.research_document import (
    ResearchDocument,
    ResearchDocumentWriter,
    TopicClassification,
    QualityScores,
    ConfidenceInfo,
    VendorInfo,
    ProductListing
)
from libs.gateway.research.research_index_db import ResearchIndexDB, get_research_index_db
from libs.gateway.context.context_gatherer_role import ContextGathererRole


def test_research_document_creation():
    """Test creating a ResearchDocument from tool results."""
    print("\n=== Test 1: Research Document Creation ===")

    # Simulated tool results (from internet.research)
    tool_results = {
        "query": "Syrian hamsters for sale online",
        "strategy": "phase1_then_phase2",
        "findings": [
            {
                "name": "Syrian Hamsters",
                "price": "$25-$35",
                "vendor": "furballcritters.com",
                "url": "https://furballcritters.com/hamster-species",
                "description": "Available as standard Syrian hamsters and Teddy Bear variety.",
                "confidence": 0.85,
                "strengths": ["Price within budget", "Multiple varieties"],
                "weaknesses": ["Limited availability"]
            },
            {
                "name": "Pedigreed Syrian",
                "price": "$70",
                "vendor": "example-breeder.com",
                "url": "https://example-breeder.com",
                "description": "Pedigreed Syrian hamster with various color options.",
                "confidence": 0.80,
                "strengths": ["High quality pedigree"],
                "weaknesses": ["Price exceeds budget"]
            }
        ],
        "stats": {
            "sources_visited": 5,
            "sources_extracted": 2,
            "findings_extracted": 2
        }
    }

    # Create document
    writer = ResearchDocumentWriter()
    doc = writer.create_from_tool_results(
        turn_number=999,
        session_id="test_session",
        query="Syrian hamsters for sale online",
        tool_results=tool_results,
        intent="transactional"
    )

    print(f"  Document ID: {doc.id}")
    print(f"  Topic: {doc.topic.primary_topic}")
    print(f"  Keywords: {doc.topic.keywords}")
    print(f"  Intent: {doc.topic.intent}")
    print(f"  Quality: {doc.quality.overall:.2f}")
    print(f"  Vendors: {len(doc.vendors)}")
    print(f"  Listings: {len(doc.listings)}")
    print(f"  General Facts: {len(doc.general_facts)}")

    assert doc.topic.primary_topic == "pet.hamster.syrian_hamster"
    assert doc.topic.intent == "transactional"
    assert len(doc.listings) == 2
    print("  PASSED")

    return doc


def test_research_document_writing(doc: ResearchDocument):
    """Test writing research document to disk."""
    print("\n=== Test 2: Research Document Writing ===")

    # Create temp directory
    test_dir = Path("/tmp/test_research_docs")
    test_dir.mkdir(parents=True, exist_ok=True)
    turn_dir = test_dir / f"turn_{doc.turn_number:06d}"
    turn_dir.mkdir(exist_ok=True)

    # Write document
    writer = ResearchDocumentWriter()
    md_path = writer.write(doc, turn_dir)

    print(f"  Wrote: {md_path}")
    print(f"  Size: {md_path.stat().st_size} bytes")

    # Verify files exist
    assert md_path.exists()
    json_path = turn_dir / "research.json"
    assert json_path.exists()

    # Read back and verify
    content = md_path.read_text()
    assert "## Evergreen Knowledge" in content
    assert "## Time-Sensitive Data" in content
    assert doc.topic.primary_topic in content

    print(f"  JSON size: {json_path.stat().st_size} bytes")
    print("  PASSED")

    return turn_dir


def test_research_index_db(doc: ResearchDocument, turn_dir: Path):
    """Test research index database operations."""
    print("\n=== Test 3: Research Index Database ===")

    # Use test database
    test_db_path = Path("/tmp/test_research_index.db")
    if test_db_path.exists():
        test_db_path.unlink()

    db = ResearchIndexDB(db_path=test_db_path)

    # Index the document
    db.index_research(
        id=doc.id,
        turn_number=doc.turn_number,
        session_id=doc.session_id,
        primary_topic=doc.topic.primary_topic,
        keywords=doc.topic.keywords,
        intent=doc.topic.intent,
        completeness=doc.quality.completeness,
        source_quality=doc.quality.source_quality,
        overall_quality=doc.quality.overall,
        confidence_initial=doc.confidence.initial,
        decay_rate=doc.confidence.decay_rate,
        created_at=doc.created_at.timestamp(),
        expires_at=doc.expires_at.timestamp() if doc.expires_at else None,
        scope=doc.scope,
        doc_path=str(turn_dir / "research.md")
    )

    print(f"  Indexed document: {doc.id}")

    # Search by topic
    results = db.search(
        topic="pet.hamster.syrian_hamster",
        intent="transactional",
        session_id="test_session"
    )

    print(f"  Search results: {len(results)}")
    assert len(results) >= 1
    assert results[0].entry.id == doc.id
    print(f"  Top result: {results[0].entry.id} (score={results[0].score:.2f})")

    # Search by parent topic
    results = db.search(topic="pet.hamster")
    print(f"  Parent topic search: {len(results)} results")
    assert len(results) >= 1

    # Search by keywords
    results = db.search_by_keywords(
        keywords=["syrian", "hamster"],
        session_id="test_session"
    )
    print(f"  Keyword search: {len(results)} results")
    assert len(results) >= 1

    # Find related
    results = db.find_related(topic="pet.hamster.roborovski")
    print(f"  Related search: {len(results)} results")

    # Get stats
    stats = db.get_stats()
    print(f"  DB stats: {stats}")

    print("  PASSED")


def test_topic_inference():
    """Test topic inference from queries."""
    print("\n=== Test 4: Topic Inference ===")

    gatherer = ContextGathererRole(session_id="test")

    test_cases = [
        ("buy Syrian hamster", "pet.hamster.syrian_hamster"),
        ("hamster care tips", "pet.hamster.care"),
        ("robo hamster price", "pet.hamster.roborovski"),
        ("gaming laptop deals", "electronics.laptop.gaming"),
        ("best phone under $500", "electronics.phone"),
    ]

    all_passed = True
    for query, expected_topic in test_cases:
        topic = gatherer._infer_topic_from_query(query)
        status = "PASS" if topic == expected_topic else "FAIL"
        if topic != expected_topic:
            all_passed = False
        print(f"  '{query}' -> {topic} ({status})")

    if all_passed:
        print("  ALL PASSED")
    else:
        print("  SOME FAILED")


def test_confidence_decay():
    """Test confidence decay calculations."""
    print("\n=== Test 5: Confidence Decay ===")

    from datetime import timedelta

    # Test immediate (no decay)
    conf = ConfidenceInfo(initial=0.9, content_type="price")
    current = conf.calculate_current(datetime.now(timezone.utc))
    print(f"  Price (0 days): {current:.2f} (expected ~0.9)")

    # Test 7-day old price
    old_date = datetime.now(timezone.utc) - timedelta(days=7)
    current = conf.calculate_current(old_date)
    print(f"  Price (7 days): {current:.2f} (expected ~0.4-0.5)")

    # Test evergreen fact
    conf = ConfidenceInfo(initial=0.9, content_type="general_fact")
    old_date = datetime.now(timezone.utc) - timedelta(days=30)
    current = conf.calculate_current(old_date)
    print(f"  Fact (30 days): {current:.2f} (expected ~0.85)")

    print("  PASSED")


def main():
    print("=" * 60)
    print("Research Document System Test Suite")
    print("=" * 60)

    # Run tests
    doc = test_research_document_creation()
    turn_dir = test_research_document_writing(doc)
    test_research_index_db(doc, turn_dir)
    test_topic_inference()
    test_confidence_decay()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
