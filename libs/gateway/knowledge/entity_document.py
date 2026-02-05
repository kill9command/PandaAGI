"""
Pandora EntityDocument: Entity-centric markdown documents that accumulate information.

This module implements compounding context where entity documents grow over time
as new information is discovered. Each entity gets its own markdown file that
accumulates:
- Properties with sources and timestamps
- Relationships to other entities
- Mentions from turns where the entity appeared

Default entity types and directories:
- vendor -> Knowledge/Vendors/
- product -> Knowledge/Products/
- site -> Knowledge/Sites/
- topic -> Knowledge/Topics/
- person -> Knowledge/People/
- (any other type) -> Knowledge/Other/

The entity type system is extensible - new types automatically map to Other/.
Per architecture guidelines, entity classification should be LLM-driven
rather than hardcoded to specific domains.

Architecture Reference:
    architecture/concepts/MEMORY_ARCHITECTURE.md
"""

import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class EntityProperty:
    """A property of an entity with provenance tracking."""
    value: str
    source: str
    updated: str  # ISO timestamp


@dataclass
class RelatedEntity:
    """A relationship to another entity."""
    entity_id: int
    entity_type: str
    name: str
    relationship: str


@dataclass
class EntityMention:
    """A mention of the entity in a turn."""
    turn: int
    context: str
    date: str  # ISO timestamp


@dataclass
class EntityDocument:
    """
    Manages entity-centric documents that accumulate information.

    These documents live in the Obsidian vault and grow as new information
    is discovered through research. They provide compounding context where
    each turn that mentions an entity adds to its knowledge base.

    Usage:
        doc = EntityDocument(
            entity_type="vendor",
            canonical_name="Example Vendor Name",
            entity_id=42
        )
        doc.add_property("url", "https://example.com", "turn_64")
        doc.add_property("price_range", "$X-$Y", "turn_64")
        doc.add_mention(64, "User researched vendors")
        doc.add_related_entity(15, "product", "Example Product", "sells")
        doc.save(vault_path)
    """
    entity_type: str
    canonical_name: str
    entity_id: int

    # Accumulated data
    summary: str = ""
    properties: Dict[str, Dict[str, str]] = field(default_factory=dict)
    related_entities: List[Dict[str, Any]] = field(default_factory=list)
    mentions: List[Dict[str, Any]] = field(default_factory=list)

    # Directory mapping for entity types
    TYPE_DIRECTORIES = {
        "vendor": "Knowledge/Vendors",
        "product": "Knowledge/Products",
        "site": "Knowledge/Sites",
        "topic": "Knowledge/Topics",
        "person": "Knowledge/People",
    }

    def add_property(self, name: str, value: str, source: str):
        """
        Add or update a property with timestamp.

        Properties are tracked with their source and update timestamp for
        provenance. If a property already exists, it is updated with the
        new value and timestamp.

        Args:
            name: Property name (e.g., "url", "price_range", "location")
            value: Property value
            source: Source of the property (e.g., "turn_64", "wikipedia")
        """
        self.properties[name] = {
            "value": value,
            "source": source,
            "updated": datetime.now().isoformat()
        }

    def add_mention(self, turn_number: int, context: str):
        """
        Record a mention of this entity in a turn.

        Mentions track where and when the entity appeared in conversation,
        building a history of references. Context is truncated to 200 chars.

        Args:
            turn_number: The turn where the entity was mentioned
            context: Surrounding text describing the mention (max 200 chars)
        """
        self.mentions.append({
            "turn": turn_number,
            "context": context[:200] if context else "",
            "date": datetime.now().isoformat()
        })

    def add_related_entity(
        self,
        entity_id: int,
        entity_type: str,
        name: str,
        relationship: str
    ):
        """
        Add a relationship to another entity.

        Relationships are directional from this entity to the target.
        Duplicates (same entity_id and relationship) are automatically
        avoided to prevent redundant links.

        Args:
            entity_id: ID of the related entity
            entity_type: Type of the related entity (vendor, product, etc.)
            name: Canonical name of the related entity
            relationship: Type of relationship (sells, recommends, competes_with, etc.)
        """
        # Avoid duplicates
        for rel in self.related_entities:
            if rel["id"] == entity_id and rel["relationship"] == relationship:
                return

        self.related_entities.append({
            "id": entity_id,
            "type": entity_type,
            "name": name,
            "relationship": relationship
        })

    def to_markdown(self) -> str:
        """
        Generate markdown document with all sections.

        Sections:
        - Header with entity type and ID
        - Summary (if provided)
        - Properties table with value, source, and update date
        - Relationships grouped by type with wiki links
        - Mentions (last 10) with turn links

        Returns:
            Complete markdown document as string
        """
        lines = [
            f"# {self.canonical_name}",
            "",
            f"**Type:** {self.entity_type}",
            f"**Entity ID:** {self.entity_id}",
            "",
        ]

        # Summary section
        if self.summary:
            lines.extend([
                "## Summary",
                "",
                self.summary,
                ""
            ])

        # Properties table
        if self.properties:
            lines.extend([
                "## Properties",
                "",
                "| Property | Value | Source | Updated |",
                "|----------|-------|--------|---------|"
            ])
            for name, data in self.properties.items():
                # Truncate date to just the date portion for display
                updated_date = data.get("updated", "")[:10] if data.get("updated") else ""
                value = data.get("value", "")
                source = data.get("source", "")
                # Escape pipe characters in values
                value = value.replace("|", "\\|") if value else ""
                lines.append(f"| {name} | {value} | {source} | {updated_date} |")
            lines.append("")

        # Relationships section (grouped by type)
        if self.related_entities:
            # Group by relationship type
            by_rel: Dict[str, List[Dict[str, Any]]] = {}
            for rel in self.related_entities:
                rel_type = rel.get("relationship", "related")
                if rel_type not in by_rel:
                    by_rel[rel_type] = []
                by_rel[rel_type].append(rel)

            lines.append("## Relationships")
            lines.append("")

            for rel_type, entities in by_rel.items():
                # Format relationship type as title case
                title = rel_type.replace("_", " ").title()
                lines.append(f"### {title}")
                for ent in entities:
                    ent_type = ent.get("type", "entity")
                    ent_name = ent.get("name", "Unknown")
                    lines.append(f"- [[{ent_type}:{ent_name}]]")
                lines.append("")

        # Mentions section (last 10)
        if self.mentions:
            lines.extend([
                "## Mentions",
                ""
            ])
            # Show only last 10 mentions
            recent_mentions = self.mentions[-10:]
            for mention in recent_mentions:
                turn = mention.get("turn", 0)
                date = mention.get("date", "")[:10] if mention.get("date") else ""
                context = mention.get("context", "")[:50]
                # Add ellipsis if context was truncated
                if len(mention.get("context", "")) > 50:
                    context += "..."
                lines.append(f"- [[turn:{turn}]] ({date}): {context}")
            lines.append("")

        return "\n".join(lines)

    def save(self, vault_path: Path) -> Path:
        """
        Save to appropriate subdirectory based on entity_type.

        Creates the directory if it doesn't exist. Filename is derived
        from the canonical name (lowercased, spaces to hyphens).

        Args:
            vault_path: Path to the Obsidian vault root

        Returns:
            Path to the saved file
        """
        # Determine path based on entity type
        dir_name = self.TYPE_DIRECTORIES.get(
            self.entity_type,
            "Knowledge/Other"
        )
        dir_path = vault_path / dir_name
        dir_path.mkdir(parents=True, exist_ok=True)

        # Sanitize filename
        filename = self._sanitize_filename(self.canonical_name)
        file_path = dir_path / f"{filename}.md"

        # Write the document
        file_path.write_text(self.to_markdown())
        logger.debug(f"[EntityDocument] Saved {self.entity_type}:{self.canonical_name} to {file_path}")

        return file_path

    @classmethod
    def load(cls, file_path: Path) -> Optional["EntityDocument"]:
        """
        Load an EntityDocument from a markdown file.

        Parses the markdown format back into structured data. Returns None
        if the file doesn't exist or can't be parsed.

        Args:
            file_path: Path to the markdown file

        Returns:
            EntityDocument instance or None if loading fails
        """
        if not file_path.exists():
            logger.warning(f"[EntityDocument] File not found: {file_path}")
            return None

        try:
            content = file_path.read_text()
            return cls._parse_markdown(content)
        except Exception as e:
            logger.error(f"[EntityDocument] Failed to load {file_path}: {e}")
            return None

    @classmethod
    def _parse_markdown(cls, content: str) -> Optional["EntityDocument"]:
        """
        Parse markdown content back into an EntityDocument.

        Args:
            content: Markdown content to parse

        Returns:
            EntityDocument instance or None if parsing fails
        """
        lines = content.split("\n")

        # Parse header
        canonical_name = ""
        entity_type = ""
        entity_id = 0

        for line in lines[:10]:
            if line.startswith("# "):
                canonical_name = line[2:].strip()
            elif line.startswith("**Type:**"):
                entity_type = line.split("**Type:**")[1].strip()
            elif line.startswith("**Entity ID:**"):
                try:
                    entity_id = int(line.split("**Entity ID:**")[1].strip())
                except ValueError:
                    entity_id = 0

        if not canonical_name or not entity_type:
            logger.warning("[EntityDocument] Missing required fields in markdown")
            return None

        doc = cls(
            entity_type=entity_type,
            canonical_name=canonical_name,
            entity_id=entity_id
        )

        # Parse sections
        current_section = None
        current_subsection = None
        current_content: List[str] = []

        for line in lines:
            if line.startswith("## Summary"):
                doc._save_section_content(current_section, current_subsection, current_content)
                current_section = "summary"
                current_subsection = None
                current_content = []
            elif line.startswith("## Properties"):
                doc._save_section_content(current_section, current_subsection, current_content)
                current_section = "properties"
                current_subsection = None
                current_content = []
            elif line.startswith("## Relationships"):
                doc._save_section_content(current_section, current_subsection, current_content)
                current_section = "relationships"
                current_subsection = None
                current_content = []
            elif line.startswith("## Mentions"):
                doc._save_section_content(current_section, current_subsection, current_content)
                current_section = "mentions"
                current_subsection = None
                current_content = []
            elif line.startswith("### ") and current_section == "relationships":
                # Relationship subsection
                if current_subsection:
                    doc._parse_relationship_subsection(current_subsection, current_content)
                current_subsection = line[4:].strip()
                current_content = []
            elif current_section:
                current_content.append(line)

        # Save last section
        doc._save_section_content(current_section, current_subsection, current_content)

        return doc

    def _save_section_content(
        self,
        section: Optional[str],
        subsection: Optional[str],
        content: List[str]
    ):
        """Save accumulated content to the appropriate section."""
        if not section:
            return

        if section == "summary":
            self.summary = "\n".join(content).strip()
        elif section == "properties":
            self._parse_properties_table(content)
        elif section == "relationships" and subsection:
            self._parse_relationship_subsection(subsection, content)
        elif section == "mentions":
            self._parse_mentions(content)

    def _parse_properties_table(self, lines: List[str]):
        """Parse the properties table."""
        for line in lines:
            if line.startswith("|") and not line.startswith("| Property") and not line.startswith("|--"):
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 4:
                    name, value, source, updated = parts[0], parts[1], parts[2], parts[3]
                    # Unescape pipe characters
                    value = value.replace("\\|", "|")
                    self.properties[name] = {
                        "value": value,
                        "source": source,
                        "updated": updated
                    }

    def _parse_relationship_subsection(self, subsection: str, lines: List[str]):
        """Parse a relationship subsection."""
        # Convert subsection title back to relationship type
        rel_type = subsection.lower().replace(" ", "_")

        for line in lines:
            if line.startswith("- [["):
                # Parse [[type:name]] format
                match = re.match(r"- \[\[(\w+):([^\]]+)\]\]", line)
                if match:
                    ent_type = match.group(1)
                    ent_name = match.group(2)
                    self.related_entities.append({
                        "id": 0,  # ID not stored in markdown
                        "type": ent_type,
                        "name": ent_name,
                        "relationship": rel_type
                    })

    def _parse_mentions(self, lines: List[str]):
        """Parse the mentions section."""
        for line in lines:
            if line.startswith("- [[turn:"):
                # Parse [[turn:N]] (date): context format
                match = re.match(r"- \[\[turn:(\d+)\]\] \(([^)]*)\): (.+)", line)
                if match:
                    turn = int(match.group(1))
                    date = match.group(2)
                    context = match.group(3).rstrip("...")
                    self.mentions.append({
                        "turn": turn,
                        "date": date,
                        "context": context
                    })

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """
        Convert entity name to safe filename.

        Converts to lowercase, replaces spaces with hyphens, and removes
        or replaces special characters.

        Args:
            name: Entity canonical name

        Returns:
            Safe filename (without extension)
        """
        # Lowercase and replace spaces
        filename = name.lower().replace(" ", "-")
        # Replace problematic characters
        filename = filename.replace("/", "-").replace("\\", "-")
        filename = filename.replace(":", "-").replace("?", "")
        filename = filename.replace("*", "").replace('"', "")
        filename = filename.replace("<", "").replace(">", "")
        filename = filename.replace("|", "-")
        # Remove multiple consecutive hyphens
        while "--" in filename:
            filename = filename.replace("--", "-")
        # Strip leading/trailing hyphens
        filename = filename.strip("-")
        return filename or "unnamed"
