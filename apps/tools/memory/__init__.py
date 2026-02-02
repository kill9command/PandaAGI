"""
Memory tools for obsidian_memory integration.

Provides persistent knowledge storage and retrieval for the Panda system.
See architecture/services/OBSIDIAN_MEMORY.md for full specification.

Public API:
- search_memory(): Search for relevant knowledge
- write_memory(): Write new knowledge to memory
- get_user_preferences(): Get user preferences
- update_preference(): Update a specific preference

Usage:
    from apps.tools.memory import search_memory, write_memory

    # Search for knowledge
    results = await search_memory("gaming laptops RTX 4060")

    # Write research findings
    path = await write_memory(
        artifact_type="research",
        topic="Gaming Laptops RTX 4060",
        content={
            "summary": "Best budget gaming laptops with RTX 4060",
            "findings": "...",
        },
        tags=["gaming", "laptops", "rtx-4060"],
        source_urls=["https://reddit.com/r/GamingLaptops"],
        confidence=0.85,
    )
"""

from .search import (
    search_memory,
    search_turns,
    get_user_preferences,
)

from .write import (
    write_memory,
    update_preference,
)

from .index import (
    update_indexes,
    rebuild_all_indexes,
)

from .models import (
    MemoryResult,
    MemoryNote,
    MemoryConfig,
)

from .templates import (
    render_template,
    format_research_content,
    format_product_content,
)

__all__ = [
    # Search
    "search_memory",
    "search_turns",
    "get_user_preferences",
    # Write
    "write_memory",
    "update_preference",
    # Index
    "update_indexes",
    "rebuild_all_indexes",
    # Models
    "MemoryResult",
    "MemoryNote",
    "MemoryConfig",
    # Templates
    "render_template",
    "format_research_content",
    "format_product_content",
]
