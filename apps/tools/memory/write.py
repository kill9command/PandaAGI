"""
Memory write implementation.

Per architecture/services/OBSIDIAN_MEMORY.md:
1. Check for existing note on same topic
2. If exists: Update with new information (append, don't overwrite)
3. If new: Create note from template
4. Update indexes in Meta/Indexes/
5. Log the change in Logs/Changes/
"""

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

from .models import MemoryConfig
from .search import parse_frontmatter, load_note
from .index import update_indexes
from .templates import render_template

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    """Convert text to a safe filename slug."""
    # Lowercase and replace spaces with underscores
    slug = text.lower().replace(" ", "_")
    # Remove non-alphanumeric (keeping underscores)
    slug = re.sub(r'[^a-z0-9_]', '', slug)
    # Collapse multiple underscores
    slug = re.sub(r'_+', '_', slug)
    # Trim underscores from ends
    slug = slug.strip('_')
    return slug[:50]  # Limit length


async def write_memory(
    artifact_type: str,
    content: Dict[str, Any],
    topic: str,
    tags: List[str] = None,
    source_urls: List[str] = None,
    confidence: float = 0.8,
    related: List[str] = None,
    user_id: str = "default",
    config: MemoryConfig = None,
) -> str:
    """
    Write a note to obsidian_memory.

    Args:
        artifact_type: "research", "product", or "preference"
        content: Structured content for the note (dict with fields)
        topic: Topic of the note
        tags: List of tags
        source_urls: Source URLs for research
        confidence: Confidence score (0.0-1.0)
        related: Related note paths
        user_id: User ID for preference notes
        config: Memory configuration

    Returns:
        Path to the written note (relative to vault)
    """
    if config is None:
        config = MemoryConfig.load()

    tags = tags or []
    source_urls = source_urls or []
    related = related or []

    now = datetime.now()
    now_iso = now.isoformat()

    # Determine target path (per-user via UserPathResolver)
    from libs.gateway.persistence.user_paths import UserPathResolver
    resolver = UserPathResolver(user_id)

    if artifact_type == "research":
        folder = resolver.knowledge_dir / "Research"
        filename = f"{slugify(topic)}.md"
        expires = (now + timedelta(days=config.research_expiry_days)).isoformat()
    elif artifact_type == "product":
        folder = resolver.knowledge_dir / "Products"
        product_name = content.get("product_name", topic)
        filename = f"{slugify(product_name)}.md"
        expires = (now + timedelta(days=config.product_expiry_days)).isoformat()
    elif artifact_type == "preference":
        folder = resolver.user_dir
        filename = "preferences.md"
        expires = None  # Preferences don't expire
    elif artifact_type == "fact":
        folder = resolver.knowledge_dir / "Facts"
        filename = f"{slugify(topic)}.md"
        expires = None  # Facts don't expire
    else:
        folder = resolver.knowledge_dir / "Research"
        filename = f"{slugify(topic)}.md"
        expires = (now + timedelta(days=config.research_expiry_days)).isoformat()

    folder.mkdir(parents=True, exist_ok=True)
    note_path = folder / filename

    # Check for existing note
    existing_note = load_note(note_path)

    if existing_note:
        # Update existing note
        logger.info(f"[MemoryWrite] Updating existing note: {note_path}")
        updated_content = _merge_note(existing_note, content, artifact_type, now_iso)
        note_path.write_text(updated_content, encoding="utf-8")
    else:
        # Create new note from template
        logger.info(f"[MemoryWrite] Creating new note: {note_path}")

        template_vars = {
            "topic": topic,
            "subtopic": content.get("subtopic", ""),
            "created": now_iso,
            "modified": now_iso,
            "source": content.get("source", "system"),
            "source_urls": source_urls,
            "confidence": confidence,
            "tags": tags,
            "related": related,
            "expires": expires,
            "title": content.get("title", topic),
            "summary": content.get("summary", ""),
            "findings": content.get("findings", ""),
            "source_table": _format_source_table(source_urls),
            "related_links": _format_related_links(related),
            # Product-specific
            "product_name": content.get("product_name", topic),
            "category": content.get("category", ""),
            "overview": content.get("overview", ""),
            "specs_table": _format_specs_table(content.get("specs", {})),
            "price_table": _format_price_table(content.get("prices", [])),
            "sentiment": content.get("sentiment", ""),
            "pros": _format_list(content.get("pros", [])),
            "cons": _format_list(content.get("cons", [])),
            # Preference-specific
            "user_id": user_id,
            "budget_preferences": content.get("budget_preferences", "*Not recorded*"),
            "category_preferences": content.get("category_preferences", "*Not recorded*"),
            "brand_preferences": content.get("brand_preferences", "*Not recorded*"),
            "shopping_preferences": content.get("shopping_preferences", "*Not recorded*"),
            "learned_from": content.get("learned_from", "*From user interactions*"),
        }

        note_content = render_template(artifact_type, template_vars)
        note_path.write_text(note_content, encoding="utf-8")

    # Update indexes (per-user)
    if config.auto_index:
        await update_indexes(
            note_path=note_path,
            topic=topic,
            tags=tags,
            artifact_type=artifact_type,
            product_name=content.get("product_name") if artifact_type == "product" else None,
            config=config,
            user_id=user_id,
        )

    # Log the change (per-user)
    if config.log_changes:
        await _log_change(
            action="update" if existing_note else "create",
            note_path=note_path,
            topic=topic,
            artifact_type=artifact_type,
            config=config,
            user_id=user_id,
        )

    # Return relative path
    try:
        return str(note_path.relative_to(config.vault_path))
    except ValueError:
        return str(note_path)


def _merge_note(
    existing: Any,  # MemoryNote
    new_content: Dict[str, Any],
    artifact_type: str,
    modified: str,
) -> str:
    """Merge new content into existing note."""
    # Update frontmatter
    frontmatter = existing.frontmatter.copy()
    frontmatter["modified"] = modified

    # Merge tags
    existing_tags = set(frontmatter.get("tags", []))
    new_tags = set(new_content.get("tags", []))
    frontmatter["tags"] = list(existing_tags | new_tags)

    # Merge source_urls
    existing_urls = set(frontmatter.get("source_urls", []))
    new_urls = set(new_content.get("source_urls", []))
    frontmatter["source_urls"] = list(existing_urls | new_urls)

    # Merge related
    existing_related = set(frontmatter.get("related", []))
    new_related = set(new_content.get("related", []))
    frontmatter["related"] = list(existing_related | new_related)

    # Build updated content
    body = existing.content

    # Append new findings if provided
    if new_content.get("findings"):
        body += f"\n\n## Update ({modified[:10]})\n\n{new_content['findings']}"

    # Append new summary if different
    if new_content.get("summary") and new_content["summary"] not in body:
        body += f"\n\n### Additional Notes\n{new_content['summary']}"

    # Rebuild the file
    import yaml
    frontmatter_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)

    return f"---\n{frontmatter_str}---\n\n{body}"


def _format_source_table(urls: List[str]) -> str:
    """Format source URLs as a markdown table."""
    if not urls:
        return "| (none) | - | - |"

    rows = []
    today = datetime.now().strftime("%Y-%m-%d")
    for url in urls[:10]:  # Limit to 10
        # Extract domain
        domain = url.split("/")[2] if "/" in url else url
        rows.append(f"| {domain} | {today} | Research source |")

    return "\n".join(rows)


def _format_related_links(related: List[str]) -> str:
    """Format related notes as wikilinks."""
    if not related:
        return "*No related notes*"

    links = [f"- [[{r}]]" for r in related]
    return "\n".join(links)


def _format_specs_table(specs: Dict[str, str]) -> str:
    """Format specs dict as markdown table."""
    if not specs:
        return "| (none) | - |"

    rows = [f"| {k} | {v} |" for k, v in specs.items()]
    return "\n".join(rows)


def _format_price_table(prices: List[Dict[str, Any]]) -> str:
    """Format price history as markdown table."""
    if not prices:
        return "| (none) | - | - |"

    rows = []
    for price in prices[:10]:
        date = price.get("date", datetime.now().strftime("%Y-%m-%d"))
        vendor = price.get("vendor", "Unknown")
        amount = price.get("price", "N/A")
        rows.append(f"| {date} | {vendor} | {amount} |")

    return "\n".join(rows)


def _format_list(items: List[str]) -> str:
    """Format list as markdown bullet points."""
    if not items:
        return "- (none recorded)"

    return "\n".join(f"- {item}" for item in items)


async def _log_change(
    action: str,
    note_path: Path,
    topic: str,
    artifact_type: str,
    config: MemoryConfig,
    user_id: str = "default",
) -> None:
    """Log a change to per-user Logs/Changes/."""
    from libs.gateway.persistence.user_paths import UserPathResolver
    resolver = UserPathResolver(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    log_dir = resolver.logs_dir / "Changes"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"{today}.md"

    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"- **{timestamp}** [{action}] {artifact_type}: {topic} → {note_path.name}\n"

    if log_file.exists():
        existing = log_file.read_text()
        log_file.write_text(existing + entry)
    else:
        header = f"# Changes Log: {today}\n\n"
        log_file.write_text(header + entry)


async def update_preference(
    key: str,
    value: str,
    category: str = "general",
    user_id: str = "default",
    source_turn: int = None,
    config: MemoryConfig = None,
) -> str:
    """
    Update a specific user preference.

    This is a convenience function for updating individual preferences
    without rewriting the entire preference note.

    Args:
        key: Preference key (e.g., "favorite_brand")
        value: Preference value (e.g., "Lenovo")
        category: Category (budget, category, brand, shopping)
        user_id: User ID
        source_turn: Turn number where this was learned
        config: Memory configuration

    Returns:
        Path to the preference note
    """
    if config is None:
        config = MemoryConfig.load()

    from libs.gateway.persistence.user_paths import UserPathResolver
    resolver = UserPathResolver(user_id)
    pref_path = resolver.preferences_file

    existing = load_note(pref_path)
    if existing is None:
        # Create new preference note
        content = {
            f"{category}_preferences": f"- **{key}:** {value}",
            "learned_from": f"- Turn {source_turn}: Learned {key}" if source_turn else "",
        }
        return await write_memory(
            artifact_type="preference",
            content=content,
            topic=f"User Preferences: {user_id}",
            user_id=user_id,
            config=config,
        )

    # Update existing preference
    now_iso = datetime.now().isoformat()
    frontmatter = existing.frontmatter.copy()
    frontmatter["modified"] = now_iso

    body = existing.content

    # Try to find and update the category section
    category_header = f"## {category.title()} Preferences"
    if category_header in body:
        # Find the section and add/update the preference
        lines = body.split("\n")
        new_lines = []
        in_section = False
        preference_added = False

        for line in lines:
            if line.strip() == category_header:
                in_section = True
                new_lines.append(line)
                continue

            if in_section and line.startswith("## "):
                # End of section
                if not preference_added:
                    new_lines.append(f"- **{key}:** {value}")
                    preference_added = True
                in_section = False

            if in_section and f"**{key}:**" in line:
                # Update existing preference
                new_lines.append(f"- **{key}:** {value}")
                preference_added = True
                continue

            new_lines.append(line)

        if in_section and not preference_added:
            new_lines.append(f"- **{key}:** {value}")

        body = "\n".join(new_lines)
    else:
        # Add new section
        body += f"\n\n{category_header}\n- **{key}:** {value}\n"

    # Add to Learned From
    if source_turn:
        learned_from = f"\n- Turn {source_turn}: Learned {key} = {value}"
        if "## Learned From" in body:
            body = body.replace("## Learned From\n", f"## Learned From\n{learned_from}")
        else:
            body += f"\n\n## Learned From{learned_from}\n"

    # Write updated note
    import yaml
    frontmatter_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    pref_path.write_text(f"---\n{frontmatter_str}---\n\n{body}", encoding="utf-8")

    logger.info(f"[MemoryWrite] Updated preference {key} for user {user_id}")

    try:
        return str(pref_path.relative_to(config.vault_path))
    except ValueError:
        return str(pref_path)
