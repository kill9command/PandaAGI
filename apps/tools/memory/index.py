"""
Index maintenance for obsidian_memory.

Per architecture/services/OBSIDIAN_MEMORY.md:
- topic_index.md: Topics → notes mapping
- product_index.md: Products → notes mapping
- tag_index.md: Tags → notes mapping
- recent_index.md: Last 50 modified notes
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from .models import MemoryConfig
from .search import parse_frontmatter

logger = logging.getLogger(__name__)


async def update_indexes(
    note_path: Path,
    topic: str,
    tags: List[str],
    artifact_type: str,
    product_name: Optional[str] = None,
    config: MemoryConfig = None,
    user_id: str = "default",
) -> None:
    """
    Update all relevant indexes after writing a note.

    Args:
        note_path: Path to the note that was written
        topic: Topic of the note
        tags: Tags of the note
        artifact_type: Type of artifact (research, product, preference)
        product_name: Product name (for product notes)
        config: Memory configuration
        user_id: User ID for per-user index directories
    """
    if config is None:
        config = MemoryConfig.load()

    from libs.gateway.persistence.user_paths import UserPathResolver
    resolver = UserPathResolver(user_id)
    indexes_dir = resolver.indexes_dir
    indexes_dir.mkdir(parents=True, exist_ok=True)

    # Get note link for indexes
    try:
        note_rel = note_path.relative_to(config.write_path)
    except ValueError:
        note_rel = note_path

    note_link = f"[[{note_rel.with_suffix('')}]]"

    # Update topic index
    await _update_topic_index(indexes_dir, topic, note_link)

    # Update tag index
    for tag in tags:
        await _update_tag_index(indexes_dir, tag, note_link)

    # Update product index if product
    if artifact_type == "product" and product_name:
        await _update_product_index(indexes_dir, product_name, note_link)

    # Update recent index
    await _update_recent_index(indexes_dir, note_path, note_link, config)

    logger.debug(f"[MemoryIndex] Updated indexes for {note_path.name}")


async def _update_topic_index(
    indexes_dir: Path,
    topic: str,
    note_link: str,
) -> None:
    """Update topic_index.md with the new note."""
    index_path = indexes_dir / "topic_index.md"

    # Load existing index
    if index_path.exists():
        content = index_path.read_text()
        frontmatter, body = parse_frontmatter(content)
    else:
        frontmatter = {
            "artifact_type": "index",
            "index_type": "topic",
            "modified": datetime.now().isoformat(),
            "entry_count": 0,
        }
        body = "# Topic Index\n"

    # Normalize topic for section header
    topic_section = topic.title()

    # Check if topic section exists
    section_pattern = f"## {re.escape(topic_section)}"
    if re.search(section_pattern, body):
        # Check if note already listed
        if note_link not in body:
            # Add to existing section
            body = re.sub(
                f"(## {re.escape(topic_section)}\n)",
                f"\\1- {note_link}\n",
                body
            )
    else:
        # Add new section
        body += f"\n## {topic_section}\n- {note_link}\n"

    # Update frontmatter
    frontmatter["modified"] = datetime.now().isoformat()
    entry_count = body.count("- [[")
    frontmatter["entry_count"] = entry_count

    # Write updated index
    import yaml
    frontmatter_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    index_path.write_text(f"---\n{frontmatter_str}---\n\n{body}", encoding="utf-8")


async def _update_tag_index(
    indexes_dir: Path,
    tag: str,
    note_link: str,
) -> None:
    """Update tag_index.md with the new note."""
    index_path = indexes_dir / "tag_index.md"

    # Load existing index
    if index_path.exists():
        content = index_path.read_text()
        frontmatter, body = parse_frontmatter(content)
    else:
        frontmatter = {
            "artifact_type": "index",
            "index_type": "tag",
            "modified": datetime.now().isoformat(),
            "entry_count": 0,
        }
        body = "# Tag Index\n"

    # Normalize tag for section header
    tag_section = tag.replace("-", " ").title()

    # Check if tag section exists
    section_pattern = f"## {re.escape(tag_section)}"
    if re.search(section_pattern, body):
        # Check if note already listed
        if note_link not in body:
            body = re.sub(
                f"(## {re.escape(tag_section)}\n)",
                f"\\1- {note_link}\n",
                body
            )
    else:
        body += f"\n## {tag_section}\n- {note_link}\n"

    # Update frontmatter
    frontmatter["modified"] = datetime.now().isoformat()
    entry_count = body.count("- [[")
    frontmatter["entry_count"] = entry_count

    import yaml
    frontmatter_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    index_path.write_text(f"---\n{frontmatter_str}---\n\n{body}", encoding="utf-8")


async def _update_product_index(
    indexes_dir: Path,
    product_name: str,
    note_link: str,
) -> None:
    """Update product_index.md with the new product."""
    index_path = indexes_dir / "product_index.md"

    if index_path.exists():
        content = index_path.read_text()
        frontmatter, body = parse_frontmatter(content)
    else:
        frontmatter = {
            "artifact_type": "index",
            "index_type": "product",
            "modified": datetime.now().isoformat(),
            "entry_count": 0,
        }
        body = "# Product Index\n\n## Products\n"

    # Add product if not already listed
    if note_link not in body:
        # Find the Products section or add to end
        if "## Products" in body:
            body = body.replace("## Products\n", f"## Products\n- **{product_name}**: {note_link}\n")
        else:
            body += f"\n## Products\n- **{product_name}**: {note_link}\n"

    frontmatter["modified"] = datetime.now().isoformat()
    entry_count = body.count("- **")
    frontmatter["entry_count"] = entry_count

    import yaml
    frontmatter_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    index_path.write_text(f"---\n{frontmatter_str}---\n\n{body}", encoding="utf-8")


async def _update_recent_index(
    indexes_dir: Path,
    note_path: Path,
    note_link: str,
    config: MemoryConfig,
    max_entries: int = 50,
) -> None:
    """Update recent_index.md with the recently modified note."""
    index_path = indexes_dir / "recent_index.md"

    if index_path.exists():
        content = index_path.read_text()
        frontmatter, body = parse_frontmatter(content)
    else:
        frontmatter = {
            "artifact_type": "index",
            "index_type": "recent",
            "modified": datetime.now().isoformat(),
            "entry_count": 0,
            "max_entries": max_entries,
        }
        body = "# Recent Index\n\n## Recently Modified\n"

    # Parse existing entries
    entries: List[tuple[str, str]] = []  # (timestamp, note_link)
    for line in body.split("\n"):
        match = re.match(r"- \*\*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\*\*: (.+)", line)
        if match:
            entries.append((match.group(1), match.group(2)))

    # Remove existing entry for this note (if any)
    entries = [(ts, link) for ts, link in entries if note_link not in link]

    # Add new entry at the top
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entries.insert(0, (timestamp, note_link))

    # Trim to max entries
    entries = entries[:max_entries]

    # Rebuild body
    lines = ["# Recent Index", "", "## Recently Modified"]
    for ts, link in entries:
        lines.append(f"- **{ts}**: {link}")

    body = "\n".join(lines) + "\n"

    frontmatter["modified"] = datetime.now().isoformat()
    frontmatter["entry_count"] = len(entries)

    import yaml
    frontmatter_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    index_path.write_text(f"---\n{frontmatter_str}---\n\n{body}", encoding="utf-8")


async def rebuild_all_indexes(config: MemoryConfig = None, user_id: str = "default") -> Dict[str, int]:
    """
    Rebuild all indexes from scratch by scanning all notes.

    Returns:
        Dict with counts for each index type
    """
    if config is None:
        config = MemoryConfig.load()

    logger.info("[MemoryIndex] Starting full index rebuild")

    from libs.gateway.persistence.user_paths import UserPathResolver
    resolver = UserPathResolver(user_id)
    indexes_dir = resolver.indexes_dir
    indexes_dir.mkdir(parents=True, exist_ok=True)

    # Clear existing indexes
    topic_index: Dict[str, Set[str]] = {}
    tag_index: Dict[str, Set[str]] = {}
    product_index: Dict[str, str] = {}
    recent_entries: List[tuple[datetime, str, str]] = []  # (mtime, link, path)

    # Scan per-user notes
    search_paths = config.get_user_searchable_paths(user_id)
    for full_path in search_paths:
        if not full_path.exists():
            continue

        for md_file in full_path.rglob("*.md"):
            # Skip index files
            if "Indexes" in str(md_file):
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
                frontmatter, body = parse_frontmatter(content)
            except Exception as e:
                logger.debug(f"Failed to parse {md_file}: {e}")
                continue

            # Get note link
            try:
                note_rel = md_file.relative_to(config.write_path)
            except ValueError:
                try:
                    note_rel = md_file.relative_to(config.vault_path)
                except ValueError:
                    note_rel = md_file

            note_link = f"[[{note_rel.with_suffix('')}]]"

            # Extract topic
            topic = frontmatter.get("topic", "")
            if topic:
                topic_section = topic.title()
                if topic_section not in topic_index:
                    topic_index[topic_section] = set()
                topic_index[topic_section].add(note_link)

            # Extract tags
            tags = frontmatter.get("tags", [])
            for tag in tags:
                tag_section = tag.replace("-", " ").title()
                if tag_section not in tag_index:
                    tag_index[tag_section] = set()
                tag_index[tag_section].add(note_link)

            # Extract product name
            if frontmatter.get("artifact_type") == "product":
                product_name = frontmatter.get("product_name", "")
                if product_name:
                    product_index[product_name] = note_link

            # Track modification time for recent index
            mtime = md_file.stat().st_mtime
            recent_entries.append((datetime.fromtimestamp(mtime), note_link, str(md_file)))

    # Write topic index
    topic_body = "# Topic Index\n"
    for topic_section in sorted(topic_index.keys()):
        topic_body += f"\n## {topic_section}\n"
        for link in sorted(topic_index[topic_section]):
            topic_body += f"- {link}\n"

    _write_index_file(indexes_dir / "topic_index.md", "topic", topic_body, sum(len(v) for v in topic_index.values()))

    # Write tag index
    tag_body = "# Tag Index\n"
    for tag_section in sorted(tag_index.keys()):
        tag_body += f"\n## {tag_section}\n"
        for link in sorted(tag_index[tag_section]):
            tag_body += f"- {link}\n"

    _write_index_file(indexes_dir / "tag_index.md", "tag", tag_body, sum(len(v) for v in tag_index.values()))

    # Write product index
    product_body = "# Product Index\n\n## Products\n"
    for product_name in sorted(product_index.keys()):
        product_body += f"- **{product_name}**: {product_index[product_name]}\n"

    _write_index_file(indexes_dir / "product_index.md", "product", product_body, len(product_index))

    # Write recent index
    recent_entries.sort(key=lambda x: x[0], reverse=True)
    recent_body = "# Recent Index\n\n## Recently Modified\n"
    for mtime, link, _ in recent_entries[:50]:
        timestamp = mtime.strftime("%Y-%m-%d %H:%M")
        recent_body += f"- **{timestamp}**: {link}\n"

    _write_index_file(indexes_dir / "recent_index.md", "recent", recent_body, min(50, len(recent_entries)))

    result = {
        "topics": len(topic_index),
        "tags": len(tag_index),
        "products": len(product_index),
        "recent": min(50, len(recent_entries)),
    }

    logger.info(f"[MemoryIndex] Index rebuild complete: {result}")
    return result


def _write_index_file(path: Path, index_type: str, body: str, entry_count: int) -> None:
    """Write an index file with proper frontmatter."""
    import yaml

    frontmatter = {
        "artifact_type": "index",
        "index_type": index_type,
        "modified": datetime.now().isoformat(),
        "entry_count": entry_count,
    }

    frontmatter_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    path.write_text(f"---\n{frontmatter_str}---\n\n{body}", encoding="utf-8")
