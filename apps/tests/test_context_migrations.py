"""
Test Context Schema Migrations

Tests all migration paths from v0 → v1 → v2 → v3
"""

import json
import tempfile
from pathlib import Path

from apps.services.gateway.context_migrations import (
    ContextMigration,
    CURRENT_SCHEMA_VERSION,
    migrate_context,
    validate_context,
    get_schema_info
)


def test_v0_to_current():
    """Test migrating from v0 (no schema_version) to current"""
    print("\n" + "="*60)
    print("TEST: v0 → current migration")
    print("="*60)

    v0_data = {
        "session_id": "test_v0",
        "preferences": {"budget": "low", "location": "Boston"},
        "current_topic": "hamsters",
        "recent_actions": [
            {"action": "search", "query": "hamsters"}
        ],
        "discovered_facts": {
            "pricing": ["hamster costs $20"]
        },
        "pending_tasks": ["find breeder"],
        "turn_count": 5,
        "last_updated": 1234567890.0,
        "created_at": 1234567890.0
    }

    print(f"Original data: {json.dumps(v0_data, indent=2)}")

    migrated = migrate_context(v0_data)

    print(f"\nMigrated to v{migrated['schema_version']}")
    print(f"Schema version: {migrated['schema_version']}")
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION

    # Check v1 fields added
    assert "fact_summaries" in migrated
    assert "action_summary" in migrated
    assert "last_summarized_turn" in migrated
    print("✓ v1 fields added (summarization)")

    # Check v2 fields added
    assert "extraction_confidence" in migrated
    assert "extraction_method" in migrated
    assert "entities" in migrated
    print("✓ v2 fields added (extraction metadata)")

    # Check v3 fields added
    assert "user_cluster" in migrated
    assert "learning_feedback" in migrated
    print("✓ v3 fields added (cross-session learning)")

    # Validate
    assert validate_context(migrated)
    print("✓ Schema validation passed")

    print("\n✅ v0 → current migration successful!\n")
    return migrated


def test_v1_to_current():
    """Test migrating from v1 to current"""
    print("\n" + "="*60)
    print("TEST: v1 → current migration")
    print("="*60)

    v1_data = {
        "session_id": "test_v1",
        "preferences": {"budget": "low"},
        "current_topic": "hamsters",
        "recent_actions": [],
        "discovered_facts": {},
        "pending_tasks": [],
        "turn_count": 3,
        "last_updated": 1234567890.0,
        "created_at": 1234567890.0,
        # v1 fields
        "schema_version": 1,
        "fact_summaries": {"pricing": "hamsters cost $15-40"},
        "action_summary": "User searched for hamsters",
        "last_summarized_turn": 2
    }

    print(f"Original schema version: v{v1_data['schema_version']}")

    migrated = migrate_context(v1_data)

    print(f"Migrated to v{migrated['schema_version']}")
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION

    # v1 fields should be preserved
    assert migrated["fact_summaries"] == {"pricing": "hamsters cost $15-40"}
    print("✓ v1 fields preserved")

    # v2 fields should be added
    assert "extraction_confidence" in migrated
    assert "extraction_method" in migrated
    print("✓ v2 fields added")

    # v3 fields should be added
    assert "user_cluster" in migrated
    assert "learning_feedback" in migrated
    print("✓ v3 fields added")

    assert validate_context(migrated)
    print("✓ Schema validation passed")

    print("\n✅ v1 → current migration successful!\n")
    return migrated


def test_v2_to_current():
    """Test migrating from v2 to current"""
    print("\n" + "="*60)
    print("TEST: v2 → current migration")
    print("="*60)

    v2_data = {
        "session_id": "test_v2",
        "preferences": {"budget": "low", "location": "Boston"},
        "current_topic": "hamsters",
        "recent_actions": [],
        "discovered_facts": {},
        "pending_tasks": [],
        "turn_count": 3,
        "last_updated": 1234567890.0,
        "created_at": 1234567890.0,
        # v1 fields
        "schema_version": 2,
        "fact_summaries": {},
        "action_summary": None,
        "last_summarized_turn": 0,
        # v2 fields
        "extraction_confidence": {"budget": 0.9, "location": 0.7},
        "extraction_method": {"budget": "regex", "location": "llm"},
        "entities": ["Syrian hamster", "Boston"]
    }

    print(f"Original schema version: v{v2_data['schema_version']}")

    migrated = migrate_context(v2_data)

    print(f"Migrated to v{migrated['schema_version']}")
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION

    # v2 fields should be preserved
    assert migrated["extraction_confidence"] == {"budget": 0.9, "location": 0.7}
    assert migrated["entities"] == ["Syrian hamster", "Boston"]
    print("✓ v2 fields preserved")

    # v3 fields should be added
    assert "user_cluster" in migrated
    assert "learning_feedback" in migrated
    print("✓ v3 fields added")

    assert validate_context(migrated)
    print("✓ Schema validation passed")

    print("\n✅ v2 → current migration successful!\n")
    return migrated


def test_current_version_no_migration():
    """Test that current version contexts don't get migrated"""
    print("\n" + "="*60)
    print("TEST: Current version (no migration needed)")
    print("="*60)

    current_data = {
        "session_id": "test_current",
        "preferences": {},
        "current_topic": None,
        "recent_actions": [],
        "discovered_facts": {},
        "pending_tasks": [],
        "turn_count": 1,
        "last_updated": 1234567890.0,
        "created_at": 1234567890.0,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "fact_summaries": {},
        "action_summary": None,
        "last_summarized_turn": 0,
        "extraction_confidence": {},
        "extraction_method": {},
        "entities": [],
        "user_cluster": None,
        "learning_feedback": []
    }

    print(f"Schema version: v{current_data['schema_version']} (current)")

    migrated = migrate_context(current_data)

    # Should be unchanged
    assert migrated == current_data
    print("✓ No migration performed (already current)")

    assert validate_context(migrated)
    print("✓ Schema validation passed")

    print("\n✅ Current version test successful!\n")


def test_schema_info():
    """Test schema info retrieval"""
    print("\n" + "="*60)
    print("TEST: Schema information")
    print("="*60)

    for version in range(0, CURRENT_SCHEMA_VERSION + 1):
        info = get_schema_info(version)
        print(f"\nv{version}: {info['description']}")
        if 'added_fields' in info:
            print(f"  Added fields: {', '.join(info['added_fields'])}")

    print("\n✅ Schema info test successful!\n")


def test_session_context_integration():
    """Test LiveSessionContext with automatic migration"""
    print("\n" + "="*60)
    print("TEST: LiveSessionContext integration")
    print("="*60)

    from apps.services.gateway.session_context import (
        LiveSessionContext,
        SessionContextManager
    )

    # Create a v0 context file
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir)

        # Write v0 context manually
        v0_file = storage_path / "test_user.json"
        v0_data = {
            "session_id": "test_user",
            "preferences": {"budget": "low"},
            "current_topic": "hamsters",
            "recent_actions": [],
            "discovered_facts": {"pricing": ["$20"]},
            "pending_tasks": [],
            "turn_count": 3,
            "last_updated": 1234567890.0,
            "created_at": 1234567890.0
            # No schema_version (v0)
        }

        with open(v0_file, 'w') as f:
            json.dump(v0_data, f)

        print(f"Created v0 context file at {v0_file}")

        # Load with SessionContextManager (should auto-migrate)
        manager = SessionContextManager(storage_path)
        ctx = manager.get("test_user")

        print(f"Loaded context: schema v{ctx.schema_version}")
        assert ctx.schema_version == CURRENT_SCHEMA_VERSION
        print("✓ Auto-migration successful")

        # Check fields
        assert ctx.preferences == {"budget": "low"}
        assert ctx.current_topic == "hamsters"
        assert ctx.turn_count == 3
        print("✓ v0 data preserved")

        # Check new fields have defaults
        assert ctx.fact_summaries == {}
        # Note: extraction_confidence gets populated for existing preferences during v1->v2 migration
        assert "budget" in ctx.extraction_confidence
        assert ctx.user_cluster is None
        print("✓ New fields initialized (extraction metadata added for existing preferences)")

        # Save (should save as v3)
        manager.save(ctx)

        # Re-load and verify it's now v3
        with open(v0_file, 'r') as f:
            saved_data = json.load(f)

        assert saved_data["schema_version"] == CURRENT_SCHEMA_VERSION
        print(f"✓ Saved as schema v{saved_data['schema_version']}")

        print("\n✅ LiveSessionContext integration successful!\n")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("CONTEXT SCHEMA MIGRATION TESTS")
    print("="*60)

    # Run all tests
    test_v0_to_current()
    test_v1_to_current()
    test_v2_to_current()
    test_current_version_no_migration()
    test_schema_info()
    test_session_context_integration()

    print("\n" + "="*60)
    print("ALL TESTS PASSED ✅")
    print("="*60)
    print(f"\nCurrent schema version: v{CURRENT_SCHEMA_VERSION}")
    print("Migration paths tested:")
    print("  ✓ v0 → v1 → v2 → v3")
    print("  ✓ v1 → v2 → v3")
    print("  ✓ v2 → v3")
    print("  ✓ v3 (no migration)")
    print("  ✓ LiveSessionContext integration")
    print("\n")
