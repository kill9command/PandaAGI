"""
Memory search implementation.

Per architecture/services/OBSIDIAN_MEMORY.md:
- Topic match: Query words match topic/subtopic in frontmatter
- Tag match: Query relates to tags
- Content match: Body contains relevant information (including fuzzy matching)
- Recency: Newer knowledge preferred when relevance is equal
"""

import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional, Dict, Any

from .models import MemoryResult, MemoryNote, MemoryConfig

logger = logging.getLogger(__name__)


def parse_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content."""
    import yaml

    if not content.startswith("---"):
        return {}, content

    # Find end of frontmatter
    end_match = re.search(r"\n---\n", content[3:])
    if not end_match:
        return {}, content

    frontmatter_text = content[3:end_match.start() + 3]
    body = content[end_match.end() + 3 + 1:]

    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        frontmatter = {}

    return frontmatter, body


def load_note(path: Path) -> Optional[MemoryNote]:
    """Load a note from disk."""
    if not path.exists() or not path.suffix == ".md":
        return None

    try:
        content = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(content)
        return MemoryNote(path=path, frontmatter=frontmatter, content=body)
    except Exception as e:
        logger.debug(f"Failed to load note {path}: {e}")
        return None


def fuzzy_word_in_text(word: str, text: str, threshold: float = 0.85) -> bool:
    """
    Check if a word has a fuzzy match in text.

    Uses SequenceMatcher to find words that are similar but not identical,
    handling common misspellings (e.g., "jessika" vs "jessikka").

    Args:
        word: Query word to find
        text: Text to search in (should be lowercase)
        threshold: Minimum similarity ratio (0.85 = 85% similar)

    Returns:
        True if exact match or fuzzy match found
    """
    # First try exact substring match (fast path)
    if word in text:
        return True

    # For short words (<=3 chars), require exact match to avoid false positives
    if len(word) <= 3:
        return False

    # Extract potential matching words from text
    # Only compare against words of similar length (±2 chars)
    text_words = re.findall(r'\b\w+\b', text)
    word_len = len(word)

    for text_word in text_words:
        # Skip words that are too different in length
        if abs(len(text_word) - word_len) > 2:
            continue

        # Calculate similarity ratio
        ratio = SequenceMatcher(None, word, text_word).ratio()
        if ratio >= threshold:
            return True

    return False


def calculate_relevance(
    note: MemoryNote,
    query_words: List[str],
    query_lower: str,
    config: MemoryConfig
) -> float:
    """
    Calculate relevance score for a note.

    Scoring:
    - Topic match: 0.4 (exact) or 0.3 (partial)
    - Tag match: 0.2 per matching tag (max 0.3)
    - Content match: 0.1 per word found (max 0.3) - includes fuzzy matching
    - Recency bonus: up to config.recency_weight
    """
    score = 0.0

    # Topic match (ensure string type - YAML may parse as int/float)
    topic = str(note.topic) if note.topic else ""
    topic_lower = topic.lower()
    if topic_lower and topic_lower in query_lower:
        score += 0.4
    elif any(word in topic_lower for word in query_words):
        score += 0.3

    # Subtopic match
    subtopic = note.frontmatter.get("subtopic", "")
    if subtopic:
        subtopic_lower = str(subtopic).lower()
        if any(word in subtopic_lower for word in query_words):
            score += 0.1

    # Tag match (ensure each tag is a string)
    tags = note.tags
    tag_matches = sum(1 for tag in tags if any(word in str(tag).lower() for word in query_words))
    score += min(0.3, tag_matches * 0.15)

    # Content match (sample first 1000 chars) - with fuzzy matching for names/misspellings
    content_sample = note.content[:1000].lower()
    content_matches = sum(1 for word in query_words if fuzzy_word_in_text(word, content_sample))
    score += min(0.3, content_matches * 0.1)

    # Product name match (for product notes)
    product_name = note.frontmatter.get("product_name", "")
    if product_name:
        product_lower = str(product_name).lower()
        if any(word in product_lower for word in query_words):
            score += 0.2

    # Recency bonus
    modified = note.modified
    if modified:
        days_ago = (datetime.now() - modified).days
        if days_ago < 7:
            score += config.recency_weight
        elif days_ago < 30:
            score += config.recency_weight * 0.7
        elif days_ago < 90:
            score += config.recency_weight * 0.4

    # Confidence bonus
    score *= (0.5 + note.confidence * 0.5)

    return min(1.0, score)


async def search_memory(
    query: str,
    folders: List[str] = None,
    tags: List[str] = None,
    limit: int = None,
    include_expired: bool = None,
    artifact_types: List[str] = None,
    config: MemoryConfig = None,
    user_id: str = "default",
) -> List[MemoryResult]:
    """
    Search obsidian_memory for relevant knowledge.

    Args:
        query: Search query
        folders: Specific folders to search (e.g., ["Knowledge/Research"])
        tags: Filter by tags
        limit: Max results (default from config)
        include_expired: Include expired content (default from config)
        artifact_types: Filter by artifact type (research, product, preference)
        config: Memory configuration (loads default if not provided)

    Returns:
        List of MemoryResult sorted by relevance
    """
    if config is None:
        config = MemoryConfig.load()

    if limit is None:
        limit = config.default_limit

    if include_expired is None:
        include_expired = config.include_expired

    # Normalize query
    query_lower = query.lower()
    query_words = [w for w in re.split(r'\W+', query_lower) if len(w) > 2]

    if not query_words:
        return []

    logger.info(f"[MemorySearch] Searching for: {query_words}")

    # Determine paths to search
    if folders:
        search_paths = [config.vault_path / folder for folder in folders]
    else:
        # Use per-user searchable paths (absolute Paths from UserPathResolver)
        search_paths = config.get_user_searchable_paths(user_id)

    # Collect all notes
    notes: List[MemoryNote] = []

    for search_path in search_paths:
        if not search_path.exists():
            continue

        # Walk directory tree
        for md_file in search_path.rglob("*.md"):
            note = load_note(md_file)
            if note:
                notes.append(note)

    logger.info(f"[MemorySearch] Found {len(notes)} notes to search")

    # Filter notes
    filtered_notes = []
    for note in notes:
        # Filter by artifact type
        if artifact_types and note.artifact_type not in artifact_types:
            continue

        # Filter by tags
        if tags:
            note_tags_lower = [t.lower() for t in note.tags]
            if not any(tag.lower() in note_tags_lower for tag in tags):
                continue

        # Filter expired (unless include_expired)
        if not include_expired and note.is_expired:
            continue

        filtered_notes.append(note)

    logger.info(f"[MemorySearch] {len(filtered_notes)} notes after filtering")

    # Score notes
    scored: List[tuple[float, MemoryNote]] = []
    for note in filtered_notes:
        relevance = calculate_relevance(note, query_words, query_lower, config)
        if relevance > 0.55:  # Minimum threshold - require meaningful relevance to reduce noise
            scored.append((relevance, note))

    # Sort by relevance (descending)
    scored.sort(key=lambda x: x[0], reverse=True)

    # Convert to results
    results = []
    for relevance, note in scored[:limit]:
        # Get path relative to vault
        try:
            rel_path = str(note.path.relative_to(config.vault_path))
        except ValueError:
            rel_path = str(note.path)

        result = MemoryResult(
            path=rel_path,
            relevance=relevance,
            summary=note.get_summary(),
            artifact_type=note.artifact_type,
            topic=note.topic,
            tags=note.tags,
            created=note.created,
            modified=note.modified,
            confidence=note.confidence,
            expired=note.is_expired,
            source_urls=note.source_urls,
        )
        results.append(result)

    logger.info(f"[MemorySearch] Returning {len(results)} results")
    return results


async def search_turns(
    query: str,
    limit: int = 5,
    config: MemoryConfig = None,
) -> List[MemoryResult]:
    """
    Search previous turns for relevant context.

    This is a convenience function that searches the turns/ folder
    specifically, looking at context.md and response.md files.
    """
    if config is None:
        config = MemoryConfig.load()

    return await search_memory(
        query=query,
        folders=["turns"],
        limit=limit,
        config=config,
    )


async def get_user_preferences(
    user_id: str = "default",
    config: MemoryConfig = None,
) -> Optional[MemoryResult]:
    """
    Get user preferences from memory.

    Returns the preference note for the specified user, or None if not found.
    Preferences are stored at: obsidian_memory/Users/{user_id}/preferences.md
    """
    if config is None:
        config = MemoryConfig.load()

    from libs.gateway.persistence.user_paths import UserPathResolver
    resolver = UserPathResolver(user_id)
    pref_path = resolver.preferences_file
    note = load_note(pref_path)

    if note is None:
        return None

    return MemoryResult(
        path=str(pref_path.relative_to(config.vault_path)),
        relevance=1.0,
        summary=note.get_summary(max_length=2000),
        artifact_type="preference",
        topic=f"User Preferences: {user_id}",
        confidence=note.confidence,
        modified=note.modified,
    )
