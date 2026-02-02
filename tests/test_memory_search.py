"""
Unit tests for memory search functionality.

Tests the search_memory function from apps/tools/memory/search.py
"""

import asyncio
import pytest
from pathlib import Path
from datetime import datetime, timedelta
import tempfile
import shutil

from apps.tools.memory.search import search_memory, get_user_preferences, parse_frontmatter, load_note
from apps.tools.memory.models import MemoryConfig, MemoryResult


@pytest.fixture
def temp_vault():
    """Create a temporary vault for testing."""
    vault_dir = Path(tempfile.mkdtemp())

    # Create structure
    (vault_dir / "obsidian_memory" / "Knowledge" / "Research").mkdir(parents=True)
    (vault_dir / "obsidian_memory" / "Knowledge" / "Products").mkdir(parents=True)
    (vault_dir / "obsidian_memory" / "Preferences" / "User").mkdir(parents=True)

    yield vault_dir

    # Cleanup
    shutil.rmtree(vault_dir)


@pytest.fixture
def sample_research_note(temp_vault):
    """Create a sample research note."""
    content = """---
artifact_type: research
topic: gaming laptops
subtopic: rtx 4060 budget options
created: 2026-01-20T10:00:00
modified: 2026-01-20T10:00:00
source: internet_research
confidence: 0.85
status: active
tags:
  - gaming
  - laptops
  - rtx-4060
  - budget
---

# RTX 4060 Budget Gaming Laptops

## Summary
Research findings on budget gaming laptops with RTX 4060 GPUs.

## Key Findings
- Lenovo LOQ 15 is the best value option
- MSI Thin GF63 is budget champion
- Price range: $700-1000
"""
    note_path = temp_vault / "obsidian_memory" / "Knowledge" / "Research" / "gaming_laptops_rtx_4060.md"
    note_path.write_text(content)
    return note_path


@pytest.fixture
def sample_product_note(temp_vault):
    """Create a sample product note."""
    content = """---
artifact_type: product
product_name: Lenovo LOQ 15
category: gaming laptop
created: 2026-01-20T10:00:00
modified: 2026-01-20T10:00:00
confidence: 0.9
status: active
tags:
  - lenovo
  - gaming-laptop
  - rtx-4060
---

# Lenovo LOQ 15

## Summary
Budget gaming laptop with excellent value.

## Specifications
| Spec | Value |
|------|-------|
| GPU | NVIDIA RTX 4060 |
| CPU | Intel i5-13420H |
| RAM | 16GB DDR5 |
"""
    note_path = temp_vault / "obsidian_memory" / "Knowledge" / "Products" / "lenovo_loq_15.md"
    note_path.write_text(content)
    return note_path


@pytest.fixture
def sample_preference_note(temp_vault):
    """Create a sample preference note."""
    content = """---
artifact_type: preference
user_id: default
created: 2026-01-20T10:00:00
modified: 2026-01-20T10:00:00
confidence: 0.8
status: active
---

# User Preferences: default

## Summary
User prefers budget options.

## Budget Preferences
- **max_budget:** $1000
- **price_sensitivity:** high
"""
    note_path = temp_vault / "obsidian_memory" / "Preferences" / "User" / "default.md"
    note_path.write_text(content)
    return note_path


class TestParseFrontmatter:
    """Test frontmatter parsing."""

    def test_parse_simple_frontmatter(self):
        content = """---
title: Test
tags:
  - one
  - two
---

Body content here.
"""
        frontmatter, body = parse_frontmatter(content)
        assert frontmatter["title"] == "Test"
        assert frontmatter["tags"] == ["one", "two"]
        assert "Body content" in body

    def test_parse_no_frontmatter(self):
        content = "Just body content."
        frontmatter, body = parse_frontmatter(content)
        assert frontmatter == {}
        assert body == content


class TestLoadNote:
    """Test note loading."""

    def test_load_valid_note(self, sample_research_note):
        note = load_note(sample_research_note)
        assert note is not None
        assert note.artifact_type == "research"
        assert note.topic == "gaming laptops"
        assert "gaming" in note.tags

    def test_load_nonexistent_note(self, temp_vault):
        note = load_note(temp_vault / "nonexistent.md")
        assert note is None


class TestSearchMemory:
    """Test memory search functionality."""

    @pytest.mark.asyncio
    async def test_search_by_topic(self, temp_vault, sample_research_note):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            searchable_paths=["obsidian_memory/Knowledge/Research"]
        )

        results = await search_memory(
            query="gaming laptops",
            config=config
        )

        assert len(results) > 0
        assert any("gaming" in r.topic.lower() for r in results)

    @pytest.mark.asyncio
    async def test_search_by_tag(self, temp_vault, sample_research_note):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            searchable_paths=["obsidian_memory/Knowledge/Research"]
        )

        results = await search_memory(
            query="rtx 4060",
            config=config
        )

        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_search_product(self, temp_vault, sample_product_note):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            searchable_paths=["obsidian_memory/Knowledge/Products"]
        )

        results = await search_memory(
            query="Lenovo LOQ",
            config=config
        )

        assert len(results) > 0
        assert results[0].artifact_type == "product"

    @pytest.mark.asyncio
    async def test_search_with_limit(self, temp_vault, sample_research_note, sample_product_note):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            searchable_paths=[
                "obsidian_memory/Knowledge/Research",
                "obsidian_memory/Knowledge/Products"
            ]
        )

        results = await search_memory(
            query="gaming laptop",
            limit=1,
            config=config
        )

        assert len(results) <= 1

    @pytest.mark.asyncio
    async def test_search_no_results(self, temp_vault):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory",
            searchable_paths=["obsidian_memory/Knowledge/Research"]
        )

        results = await search_memory(
            query="nonexistent topic xyz",
            config=config
        )

        assert len(results) == 0


class TestGetUserPreferences:
    """Test user preference retrieval."""

    @pytest.mark.asyncio
    async def test_get_existing_preferences(self, temp_vault, sample_preference_note):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory"
        )

        result = await get_user_preferences(user_id="default", config=config)

        assert result is not None
        assert result.artifact_type == "preference"
        assert "budget" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_get_nonexistent_preferences(self, temp_vault):
        config = MemoryConfig(
            vault_path=temp_vault,
            write_path=temp_vault / "obsidian_memory"
        )

        result = await get_user_preferences(user_id="nonexistent", config=config)

        assert result is None


class TestMemoryResult:
    """Test MemoryResult dataclass."""

    def test_to_context_block(self):
        result = MemoryResult(
            path="Knowledge/Research/test.md",
            relevance=0.85,
            summary="This is a test summary.",
            artifact_type="research",
            topic="Test Topic",
            tags=["test", "example"],
            confidence=0.9,
        )

        block = result.to_context_block()

        assert "Test Topic" in block
        assert "research" in block
        assert "0.85" in block
        assert "test, example" in block


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
