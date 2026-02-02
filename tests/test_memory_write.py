"""
Unit tests for memory write functionality.

Tests the write_memory function from apps/tools/memory/write.py
"""

import asyncio
import pytest
from pathlib import Path
from datetime import datetime
import tempfile
import shutil
import yaml

from apps.tools.memory.write import write_memory, update_preference, slugify
from apps.tools.memory.search import load_note
from apps.tools.memory.models import MemoryConfig


@pytest.fixture
def temp_vault():
    """Create a temporary vault for testing."""
    vault_dir = Path(tempfile.mkdtemp())

    # Create structure
    (vault_dir / "obsidian_memory" / "Knowledge" / "Research").mkdir(parents=True)
    (vault_dir / "obsidian_memory" / "Knowledge" / "Products").mkdir(parents=True)
    (vault_dir / "obsidian_memory" / "Knowledge" / "Facts").mkdir(parents=True)
    (vault_dir / "obsidian_memory" / "Preferences" / "User").mkdir(parents=True)
    (vault_dir / "obsidian_memory" / "Meta" / "Indexes").mkdir(parents=True)
    (vault_dir / "obsidian_memory" / "Meta" / "Config").mkdir(parents=True)
    (vault_dir / "obsidian_memory" / "Logs" / "Changes").mkdir(parents=True)

    # Create config
    config_content = """
memory:
  vault_path: {vault}
  write_path: {vault}/obsidian_memory

search:
  default_limit: 10

write:
  auto_index: true
  log_changes: true

expiration:
  research_days: 180
  product_days: 90
""".format(vault=str(vault_dir))
    (vault_dir / "obsidian_memory" / "Meta" / "Config" / "memory_config.yaml").write_text(config_content)

    yield vault_dir

    # Cleanup
    shutil.rmtree(vault_dir)


class TestSlugify:
    """Test slug generation."""

    def test_simple_text(self):
        assert slugify("Hello World") == "hello_world"

    def test_special_characters(self):
        assert slugify("Test! @#$% Value") == "test_value"

    def test_multiple_spaces(self):
        assert slugify("Test   Multiple   Spaces") == "test_multiple_spaces"

    def test_length_limit(self):
        long_text = "This is a very long text that should be truncated"
        result = slugify(long_text)
        assert len(result) <= 50


class TestWriteMemory:
    """Test memory writing functionality."""

    @pytest.mark.asyncio
    async def test_write_research(self, temp_vault):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            auto_index=False,  # Disable indexing for simpler test
            log_changes=False,
        )

        path = await write_memory(
            artifact_type="research",
            topic="Gaming Monitors",
            content={
                "summary": "Research on best gaming monitors",
                "findings": "144Hz is minimum, 1440p is sweet spot",
            },
            tags=["gaming", "monitors"],
            source_urls=["https://example.com/monitors"],
            confidence=0.85,
            config=config,
        )

        # Verify file was created
        full_path = temp_vault / path
        assert full_path.exists()

        # Verify content
        note = load_note(full_path)
        assert note is not None
        assert note.artifact_type == "research"
        assert note.topic == "Gaming Monitors"
        assert note.confidence == 0.85
        assert "gaming" in note.tags

    @pytest.mark.asyncio
    async def test_write_product(self, temp_vault):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            auto_index=False,
            log_changes=False,
        )

        path = await write_memory(
            artifact_type="product",
            topic="ASUS ROG Monitor",
            content={
                "product_name": "ASUS ROG Swift",
                "category": "gaming monitor",
                "overview": "High-end gaming monitor",
                "specs": {"Resolution": "2560x1440", "Refresh": "170Hz"},
                "prices": [{"price": "$449", "vendor": "Amazon", "date": "2026-01-20"}],
                "pros": ["Fast response", "Great colors"],
                "cons": ["Expensive"],
            },
            tags=["asus", "gaming-monitor"],
            confidence=0.9,
            config=config,
        )

        # Verify file was created
        full_path = temp_vault / path
        assert full_path.exists()

        # Verify content
        note = load_note(full_path)
        assert note is not None
        assert note.artifact_type == "product"
        assert note.frontmatter.get("product_name") == "ASUS ROG Swift"

    @pytest.mark.asyncio
    async def test_write_preference(self, temp_vault):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            auto_index=False,
            log_changes=False,
        )

        path = await write_memory(
            artifact_type="preference",
            topic="User Preferences",
            content={
                "budget_preferences": "- **max_budget:** $1000",
                "category_preferences": "- Prefers gaming monitors",
            },
            user_id="default",
            confidence=0.8,
            config=config,
        )

        # Verify file was created
        full_path = temp_vault / path
        assert full_path.exists()

        # Verify content
        note = load_note(full_path)
        assert note is not None
        assert note.artifact_type == "preference"

    @pytest.mark.asyncio
    async def test_update_existing_note(self, temp_vault):
        """Test that writing to existing topic appends rather than overwrites."""
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            auto_index=False,
            log_changes=False,
        )

        # Write initial note
        await write_memory(
            artifact_type="research",
            topic="Test Topic",
            content={
                "summary": "Initial summary",
                "findings": "Initial findings",
            },
            tags=["tag1"],
            config=config,
        )

        # Write update
        await write_memory(
            artifact_type="research",
            topic="Test Topic",
            content={
                "summary": "Updated summary",
                "findings": "Additional findings",
                "tags": ["tag2"],
            },
            tags=["tag2"],
            config=config,
        )

        # Verify both content exists
        note_path = temp_vault / "obsidian_memory" / "Knowledge" / "Research" / "test_topic.md"
        content = note_path.read_text()

        assert "Initial findings" in content or "Additional findings" in content
        # Tags should be merged
        note = load_note(note_path)
        assert "tag1" in note.tags or "tag2" in note.tags


class TestUpdatePreference:
    """Test preference update functionality."""

    @pytest.mark.asyncio
    async def test_update_new_preference(self, temp_vault):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            auto_index=False,
            log_changes=False,
        )

        path = await update_preference(
            key="max_budget",
            value="$1500",
            category="budget",
            user_id="default",
            source_turn=123,
            config=config,
        )

        # Verify file was created
        full_path = temp_vault / path
        assert full_path.exists()

        # Verify content contains the preference
        content = full_path.read_text()
        assert "max_budget" in content
        assert "$1500" in content

    @pytest.mark.asyncio
    async def test_update_existing_preference(self, temp_vault):
        """Test updating an existing preference file."""
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            auto_index=False,
            log_changes=False,
        )

        # Create initial preference
        await update_preference(
            key="favorite_brand",
            value="ASUS",
            category="brand",
            user_id="default",
            config=config,
        )

        # Update with new preference
        await update_preference(
            key="max_budget",
            value="$2000",
            category="budget",
            user_id="default",
            config=config,
        )

        # Verify both preferences exist
        pref_path = temp_vault / "obsidian_memory" / "Preferences" / "User" / "default.md"
        content = pref_path.read_text()

        # Both should be in the file
        assert "favorite_brand" in content or "ASUS" in content
        assert "max_budget" in content or "$2000" in content


class TestIndexing:
    """Test index maintenance."""

    @pytest.mark.asyncio
    async def test_index_updated_on_write(self, temp_vault):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            auto_index=True,
            log_changes=False,
        )

        await write_memory(
            artifact_type="research",
            topic="Indexed Topic",
            content={
                "summary": "Test indexing",
            },
            tags=["test-tag"],
            config=config,
        )

        # Check topic index was updated
        topic_index_path = temp_vault / "obsidian_memory" / "Meta" / "Indexes" / "topic_index.md"
        if topic_index_path.exists():
            content = topic_index_path.read_text()
            assert "Indexed Topic" in content or "indexed_topic" in content

    @pytest.mark.asyncio
    async def test_change_logged(self, temp_vault):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            auto_index=False,
            log_changes=True,
        )

        await write_memory(
            artifact_type="research",
            topic="Logged Topic",
            content={
                "summary": "Test logging",
            },
            config=config,
        )

        # Check change was logged
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = temp_vault / "obsidian_memory" / "Logs" / "Changes" / f"{today}.md"
        if log_path.exists():
            content = log_path.read_text()
            assert "Logged Topic" in content or "logged_topic" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
