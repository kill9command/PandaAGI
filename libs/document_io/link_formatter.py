"""Link formatting for Markdown and Obsidian compatibility.

Architecture Reference:
    architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md#9-obsidian-integration

Key Design:
    Every document reference includes both link styles:
    - Markdown link (left): Relative path for LLMs and programmatic access
    - Wikilink (right): Obsidian navigation, graph view, backlinks

Example:
    [turn_000815/context.md](../turn_000815/context.md) | [[turns/turn_000815/context|turn_000815]]
"""

from pathlib import Path
from typing import Optional
import os


class LinkFormatter:
    """Generates dual-format links (Markdown + Wikilink).

    Supports:
    - Markdown links: [label](relative_path) - for LLMs and programmatic access
    - Wikilinks: [[vault_path|label]] - for Obsidian navigation
    - Block links: [[path#^block-id|label]] - for claims and decisions
    """

    def __init__(self, vault_root: Path = Path("panda_system_docs")):
        """
        Initialize link formatter.

        Args:
            vault_root: Root directory for Obsidian vault
        """
        self.vault_root = vault_root

    def dual_link(self, from_file: Path, to_file: Path, label: str) -> str:
        """
        Generate both Markdown and Wikilink formats.

        This is the primary method for generating document references.
        The dual format ensures compatibility with both:
        - LLMs reading markdown (relative paths work)
        - Obsidian users (wikilinks enable graph view, backlinks)

        Args:
            from_file: Source file path
            to_file: Target file path
            label: Link label

        Returns:
            Combined link string: "[label](rel_path) | [[vault_path|label]]"
        """
        md_link = self.markdown_link(from_file, to_file, label)
        wiki_link = self.wikilink(to_file, label)
        return f"{md_link} | {wiki_link}"

    def markdown_link(self, from_file: Path, to_file: Path, label: str) -> str:
        """
        Generate relative Markdown link.

        Uses os.path.relpath to compute relative path from source to target.
        This enables LLMs to follow links programmatically.

        Args:
            from_file: Source file
            to_file: Target file
            label: Link label

        Returns:
            Markdown link: [label](relative_path)
        """
        rel_path = os.path.relpath(to_file, from_file.parent)
        return f"[{label}]({rel_path})"

    def wikilink(self, to_file: Path, label: str) -> str:
        """
        Generate Obsidian wikilink.

        Wikilinks use vault-relative paths without file extensions.
        This enables Obsidian's graph view and backlink features.

        Args:
            to_file: Target file
            label: Link label

        Returns:
            Wikilink: [[path|label]]
        """
        try:
            vault_path = to_file.relative_to(self.vault_root)
            # Remove extension for wikilinks (Obsidian convention)
            vault_path_str = str(vault_path.with_suffix(""))
            return f"[[{vault_path_str}|{label}]]"
        except ValueError:
            # File not in vault, use full path
            return f"[[{to_file.with_suffix('')}|{label}]]"

    def block_link(self, file_path: Path, block_id: str, label: str) -> str:
        """
        Generate link to specific block.

        Block links reference specific sections or claims within documents.
        Used for claim attribution and decision tracking.

        Args:
            file_path: Target file
            block_id: Block identifier (e.g., "claim-001")
            label: Link label

        Returns:
            Wikilink with block: [[path#^block-id|label]]
        """
        try:
            vault_path = file_path.relative_to(self.vault_root)
            vault_path_str = str(vault_path.with_suffix(""))
            return f"[[{vault_path_str}#^{block_id}|{label}]]"
        except ValueError:
            return f"[[{file_path.with_suffix('')}#^{block_id}|{label}]]"

    def section_link(self, file_path: Path, section: str, label: str) -> str:
        """
        Generate link to a heading section.

        Section links reference headings within documents.
        Used for linking to specific sections like "## 4. Tool Execution".

        Args:
            file_path: Target file
            section: Section heading (e.g., "4. Tool Execution")
            label: Link label

        Returns:
            Wikilink with section: [[path#section|label]]
        """
        try:
            vault_path = file_path.relative_to(self.vault_root)
            vault_path_str = str(vault_path.with_suffix(""))
            # Replace spaces with hyphens for URL-safe sections
            section_slug = section.replace(" ", "-").lower()
            return f"[[{vault_path_str}#{section_slug}|{label}]]"
        except ValueError:
            section_slug = section.replace(" ", "-").lower()
            return f"[[{file_path.with_suffix('')}#{section_slug}|{label}]]"

    def source_reference(
        self,
        from_file: Path,
        to_file: Path,
        index: int,
        description: str,
    ) -> str:
        """
        Generate numbered source reference.

        Used in context.md section 2 for listing sources with descriptions.

        Args:
            from_file: Source file
            to_file: Target file
            index: Reference number
            description: Brief description

        Returns:
            Formatted reference: - [1] [label](path) | [[path|label]] - "description"
        """
        label = to_file.stem
        dual = self.dual_link(from_file, to_file, label)
        return f"- [{index}] {dual} - \"{description}\""

    def turn_link(
        self,
        from_file: Path,
        turn_number: int,
        document: str = "context.md",
        label: Optional[str] = None,
    ) -> str:
        """
        Generate link to a turn document.

        Convenience method for linking between turns.

        Args:
            from_file: Source file
            turn_number: Target turn number
            document: Document name (default: context.md)
            label: Optional custom label

        Returns:
            Dual-format link to the turn document
        """
        if label is None:
            label = f"Turn {turn_number}"

        # Construct target path relative to vault root
        turn_dir = f"turn_{turn_number:06d}"
        # This assumes we're linking from within the turns directory structure
        to_file = self.vault_root / "users" / "unknown" / "turns" / turn_dir / document

        return self.dual_link(from_file, to_file, label)

    def research_link(self, from_file: Path, turn_number: int) -> str:
        """
        Generate link to a research document.

        Args:
            from_file: Source file
            turn_number: Turn containing the research

        Returns:
            Dual-format link to research.md
        """
        return self.turn_link(from_file, turn_number, "research.md", f"Research (Turn {turn_number})")

    def claim_reference(
        self,
        file_path: Path,
        claim_id: str,
        claim_text: str,
    ) -> str:
        """
        Generate claim reference with block link.

        Used for attributing claims to their sources.

        Args:
            file_path: File containing the claim
            claim_id: Claim block ID (e.g., "claim-001")
            claim_text: Brief claim description

        Returns:
            Block link with claim text
        """
        link = self.block_link(file_path, claim_id, "source")
        return f"{claim_text} {link}"


# Default instance for simple use cases
link_formatter = LinkFormatter()
