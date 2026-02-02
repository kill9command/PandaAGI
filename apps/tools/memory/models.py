"""
Memory system data models.

Per architecture/services/OBSIDIAN_MEMORY.md, defines:
- MemoryResult: Search result with path, relevance, summary
- MemoryNote: Note structure with frontmatter and content
- MemoryConfig: Memory system configuration
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path


@dataclass
class MemoryResult:
    """A search result from obsidian_memory."""

    path: str
    """Path to the note relative to vault root."""

    relevance: float
    """Relevance score 0.0-1.0."""

    summary: str
    """Brief summary of the content (first 200 chars or custom)."""

    artifact_type: str
    """Type: research, product, preference, turn, etc."""

    topic: Optional[str] = None
    """Topic from frontmatter."""

    tags: List[str] = field(default_factory=list)
    """Tags from frontmatter."""

    created: Optional[datetime] = None
    """Creation timestamp."""

    modified: Optional[datetime] = None
    """Last modified timestamp."""

    confidence: float = 0.8
    """Confidence score from frontmatter."""

    expired: bool = False
    """Whether the content has expired."""

    source_urls: List[str] = field(default_factory=list)
    """Source URLs if any."""

    def to_context_block(self) -> str:
        """Format as a context block for LLM consumption."""
        lines = [f"### {self.topic or self.path}"]

        if self.expired:
            lines.append("*Note: This information may be outdated.*")

        lines.append(f"Type: {self.artifact_type} | Relevance: {self.relevance:.2f} | Confidence: {self.confidence:.2f}")

        if self.tags:
            lines.append(f"Tags: {', '.join(self.tags)}")

        lines.append("")
        lines.append(self.summary)

        if self.source_urls:
            lines.append("")
            lines.append("Sources: " + ", ".join(self.source_urls[:3]))

        return "\n".join(lines)


@dataclass
class MemoryNote:
    """A note in obsidian_memory with frontmatter and content."""

    path: Path
    """Absolute path to the note file."""

    frontmatter: Dict[str, Any]
    """YAML frontmatter metadata."""

    content: str
    """Markdown content (without frontmatter)."""

    @property
    def artifact_type(self) -> str:
        return self.frontmatter.get("artifact_type", "unknown")

    @property
    def topic(self) -> Optional[str]:
        return self.frontmatter.get("topic")

    @property
    def tags(self) -> List[str]:
        return self.frontmatter.get("tags", [])

    @property
    def confidence(self) -> float:
        return self.frontmatter.get("confidence", 0.8)

    @property
    def created(self) -> Optional[datetime]:
        created = self.frontmatter.get("created")
        if isinstance(created, datetime):
            return created
        if isinstance(created, str):
            try:
                return datetime.fromisoformat(created)
            except ValueError:
                return None
        return None

    @property
    def modified(self) -> Optional[datetime]:
        modified = self.frontmatter.get("modified")
        if isinstance(modified, datetime):
            return modified
        if isinstance(modified, str):
            try:
                return datetime.fromisoformat(modified)
            except ValueError:
                return None
        return None

    @property
    def expires(self) -> Optional[datetime]:
        expires = self.frontmatter.get("expires")
        if isinstance(expires, datetime):
            return expires
        if isinstance(expires, str):
            try:
                return datetime.fromisoformat(expires)
            except ValueError:
                return None
        return None

    @property
    def is_expired(self) -> bool:
        if self.expires is None:
            return False
        return datetime.now() > self.expires

    @property
    def source_urls(self) -> List[str]:
        """
        Get source URLs and links from frontmatter.

        Checks both 'source_urls' and 'links' fields.
        Parses Obsidian-style [[link]] format into readable references.
        """
        urls = []

        # Check source_urls field
        source_urls = self.frontmatter.get("source_urls", [])
        if isinstance(source_urls, list):
            urls.extend(source_urls)

        # Check links field (Obsidian-style [[link]] format)
        links = self.frontmatter.get("links", [])
        if isinstance(links, list):
            for link in links:
                if isinstance(link, str):
                    # Remove [[ and ]] if present, also handle quotes
                    clean = link.strip()
                    if clean.startswith("[[") and clean.endswith("]]"):
                        clean = clean[2:-2]
                    clean = clean.strip('"').strip("'")
                    if clean and clean not in urls:
                        urls.append(f"See: {clean}")

        # Check source field (single source string)
        source = self.frontmatter.get("source", "")
        if source and isinstance(source, str) and source not in urls:
            urls.append(source)

        return urls

    def get_summary(self, max_length: int = 200) -> str:
        """Extract summary from content."""
        # Look for ## Summary section
        lines = self.content.split("\n")
        in_summary = False
        summary_lines = []

        for line in lines:
            if line.strip().lower() == "## summary":
                in_summary = True
                continue
            if in_summary:
                if line.startswith("## "):
                    break
                if line.strip():
                    summary_lines.append(line.strip())

        if summary_lines:
            summary = " ".join(summary_lines)
        else:
            # Fallback: first paragraph
            summary = self.content.split("\n\n")[0] if self.content else ""

        if len(summary) > max_length:
            summary = summary[:max_length - 3] + "..."

        return summary


@dataclass
class MemoryConfig:
    """Configuration for the memory system."""

    vault_path: Path
    """Root vault path for search."""

    write_path: Path
    """Path where new knowledge is written."""

    default_limit: int = 10
    """Default number of results to return."""

    max_results: int = 50
    """Maximum results allowed."""

    include_expired: bool = True
    """Whether to include expired content in search."""

    recency_weight: float = 0.3
    """Weight for recency in relevance scoring."""

    auto_index: bool = True
    """Auto-update indexes on write."""

    log_changes: bool = True
    """Log all changes."""

    research_expiry_days: int = 180
    """Days until research expires."""

    product_expiry_days: int = 90
    """Days until product info expires."""

    searchable_paths: List[str] = field(default_factory=lambda: [
        "obsidian_memory/Knowledge",       # Shared knowledge (Research, Products, Concepts)
        "obsidian_memory/Users",           # Per-user data (turns, preferences, projects)
        "obsidian_memory/Beliefs",         # Shared beliefs
        "obsidian_memory/Maps",            # Shared maps
        "obsidian_memory/Improvements",    # Extracted improvement principles from successful revisions
    ])
    """Paths within vault to search."""

    @classmethod
    def load(cls, config_path: Path = None) -> "MemoryConfig":
        """Load configuration from YAML file."""
        import yaml

        if config_path is None:
            config_path = Path("panda_system_docs/obsidian_memory/Meta/Config/memory_config.yaml")

        if not config_path.exists():
            # Return defaults
            return cls(
                vault_path=Path("panda_system_docs"),
                write_path=Path("panda_system_docs/obsidian_memory")
            )

        with open(config_path) as f:
            data = yaml.safe_load(f)

        memory = data.get("memory", {})
        search = data.get("search", {})
        write = data.get("write", {})
        expiration = data.get("expiration", {})

        return cls(
            vault_path=Path(memory.get("vault_path", "panda_system_docs")),
            write_path=Path(memory.get("write_path", "panda_system_docs/obsidian_memory")),
            default_limit=search.get("default_limit", 10),
            max_results=search.get("max_results", 50),
            include_expired=search.get("include_expired", True),
            recency_weight=search.get("recency_weight", 0.3),
            auto_index=write.get("auto_index", True),
            log_changes=write.get("log_changes", True),
            research_expiry_days=expiration.get("research_days", 180),
            product_expiry_days=expiration.get("product_days", 90),
            searchable_paths=search.get("searchable_paths", [
                "obsidian_memory/Knowledge",
                "obsidian_memory/Users",
                "obsidian_memory/Beliefs",
                "obsidian_memory/Maps",
                "obsidian_memory/Improvements",
            ])
        )
