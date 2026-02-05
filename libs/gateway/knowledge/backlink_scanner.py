"""
Backlink Scanner: Scans markdown files for wiki links and manages backlink indexing.

Detects wiki link patterns in Obsidian-style markdown files:
- [[Target]] - simple wiki link
- [[Target|Display Text]] - aliased wiki link
- [[type:Name]] - typed entity link (e.g., [[vendor:Poppybee]])

Integrates with KnowledgeGraphDB to store bidirectional backlinks for navigation
and orphan detection.
"""

import re
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Set, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.knowledge.knowledge_graph_db import KnowledgeGraphDB

logger = logging.getLogger(__name__)


# =============================================================================
# Wiki Link Patterns
# =============================================================================

# Standard wiki link: [[Target]] or [[Target|Display Text]]
WIKI_LINK_PATTERN = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')

# Typed entity link: [[type:Name]] (e.g., [[vendor:Poppybee]])
TYPED_LINK_PATTERN = re.compile(r'\[\[(\w+):([^\]|]+)(?:\|([^\]]+))?\]\]')


# =============================================================================
# Link Resolution Configuration
# =============================================================================

# Mapping of entity types to their vault subdirectories
ENTITY_TYPE_DIRS = {
    "vendor": "Knowledge/Vendors",
    "product": "Knowledge/Products",
    "site": "Knowledge/Sites",
    "topic": "Knowledge/Topics",
    "person": "Knowledge/People",
    "concept": "Knowledge/Concepts",
    "fact": "Knowledge/Facts",
    "turn": "Users/{user_id}/turns",
}

# Default vault path
DEFAULT_VAULT_PATH = Path("panda_system_docs/obsidian_memory")


# =============================================================================
# Data Classes
# =============================================================================

class WikiLink:
    """Represents a parsed wiki link."""

    def __init__(
        self,
        target: str,
        display_text: Optional[str] = None,
        link_type: str = "wiki",
        entity_type: Optional[str] = None,
        line_number: int = 0
    ):
        self.target = target
        self.display_text = display_text or target
        self.link_type = link_type  # "wiki", "entity", "turn"
        self.entity_type = entity_type  # For typed links: vendor, product, etc.
        self.line_number = line_number

    def __repr__(self) -> str:
        if self.entity_type:
            return f"WikiLink([[{self.entity_type}:{self.target}]], line={self.line_number})"
        return f"WikiLink([[{self.target}]], line={self.line_number})"

    def __eq__(self, other) -> bool:
        if not isinstance(other, WikiLink):
            return False
        return (
            self.target == other.target
            and self.entity_type == other.entity_type
            and self.link_type == other.link_type
        )

    def __hash__(self) -> int:
        return hash((self.target, self.entity_type, self.link_type))


# =============================================================================
# Backlink Scanner
# =============================================================================

class BacklinkScanner:
    """
    Scans markdown files for wiki links and builds backlink index.

    Usage:
        from libs.gateway.knowledge.backlink_scanner import BacklinkScanner
        from libs.gateway.knowledge.knowledge_graph_db import get_knowledge_graph_db

        kg = get_knowledge_graph_db()
        scanner = BacklinkScanner(kg)

        # Scan a single file
        links = scanner.scan_file(Path("some/file.md"))

        # Scan and register in database
        scanner.scan_and_register(Path("some/file.md"))

        # Rebuild entire vault index
        scanner.rebuild_all_backlinks(vault_path)

        # Find orphan files (no incoming links)
        orphans = scanner.get_orphan_files(vault_path)
    """

    def __init__(
        self,
        kg: Optional["KnowledgeGraphDB"] = None,
        vault_path: Optional[Path] = None
    ):
        """
        Initialize the backlink scanner.

        Args:
            kg: KnowledgeGraphDB instance for storing backlinks.
                If None, scanning works but registration is skipped.
            vault_path: Base path to the Obsidian vault.
                Defaults to panda_system_docs/obsidian_memory/
        """
        self.kg = kg
        self.vault_path = vault_path or DEFAULT_VAULT_PATH

    # =========================================================================
    # Core Scanning Methods
    # =========================================================================

    def scan_file(self, file_path: Path) -> List[WikiLink]:
        """
        Scan a markdown file for wiki links.

        Args:
            file_path: Path to the markdown file to scan.

        Returns:
            List of WikiLink objects found in the file.
        """
        if not file_path.exists():
            logger.warning(f"[BacklinkScanner] File not found: {file_path}")
            return []

        if not file_path.suffix.lower() == ".md":
            logger.debug(f"[BacklinkScanner] Skipping non-markdown file: {file_path}")
            return []

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"[BacklinkScanner] Failed to read {file_path}: {e}")
            return []

        links = []
        lines = content.split("\n")

        for line_number, line in enumerate(lines, start=1):
            # Skip code blocks
            if line.strip().startswith("```"):
                continue

            # Find typed entity links first (more specific pattern)
            for match in TYPED_LINK_PATTERN.finditer(line):
                entity_type = match.group(1).lower()
                target = match.group(2).strip()
                display_text = match.group(3).strip() if match.group(3) else None

                # Determine link type
                if entity_type == "turn":
                    link_type = "turn"
                else:
                    link_type = "entity"

                links.append(WikiLink(
                    target=target,
                    display_text=display_text,
                    link_type=link_type,
                    entity_type=entity_type,
                    line_number=line_number
                ))

            # Find standard wiki links (exclude typed links already found)
            for match in WIKI_LINK_PATTERN.finditer(line):
                full_match = match.group(0)
                target = match.group(1).strip()
                display_text = match.group(2).strip() if match.group(2) else None

                # Skip if this is a typed link (already processed)
                if ":" in target and target.split(":")[0].lower() in ENTITY_TYPE_DIRS:
                    continue

                links.append(WikiLink(
                    target=target,
                    display_text=display_text,
                    link_type="wiki",
                    entity_type=None,
                    line_number=line_number
                ))

        logger.debug(f"[BacklinkScanner] Found {len(links)} links in {file_path}")
        return links

    def scan_file_tuples(
        self,
        file_path: Path
    ) -> List[Tuple[str, str, int]]:
        """
        Scan a file for wiki links and return as tuples.

        This is the simple interface specified in the plan.

        Args:
            file_path: Path to the markdown file.

        Returns:
            List of (target, link_text, line_number) tuples.
        """
        links = self.scan_file(file_path)
        return [
            (link.target, link.display_text, link.line_number)
            for link in links
        ]

    # =========================================================================
    # Link Resolution
    # =========================================================================

    def resolve_link_target(
        self,
        link: WikiLink,
        source_dir: Optional[Path] = None,
        user_id: str = "default"
    ) -> Optional[Path]:
        """
        Resolve a wiki link to an actual file path.

        Resolution rules:
        - [[Name]] -> search for Name.md in vault
        - [[vendor:Name]] -> Knowledge/Vendors/name.md
        - [[product:Name]] -> Knowledge/Products/name.md
        - [[turn:123]] -> Users/{user_id}/turns/turn_000123/context.md
        - Handle case-insensitive matching

        Args:
            link: WikiLink to resolve.
            source_dir: Directory of the source file (for relative resolution).
            user_id: User ID for turn links.

        Returns:
            Path to the target file, or None if not resolvable.
        """
        target = link.target
        entity_type = link.entity_type

        # Handle typed entity links
        if entity_type and entity_type in ENTITY_TYPE_DIRS:
            dir_template = ENTITY_TYPE_DIRS[entity_type]

            # Special handling for turns
            if entity_type == "turn":
                try:
                    turn_number = int(target)
                    dir_path = self.vault_path / dir_template.format(user_id=user_id)
                    return dir_path / f"turn_{turn_number:06d}" / "context.md"
                except ValueError:
                    logger.warning(f"[BacklinkScanner] Invalid turn number: {target}")
                    return None

            # Other typed entities
            dir_path = self.vault_path / dir_template
            filename = self._normalize_filename(target)
            target_path = dir_path / f"{filename}.md"

            # Try exact match first
            if target_path.exists():
                return target_path

            # Try case-insensitive match
            return self._find_case_insensitive(dir_path, filename)

        # Handle standard wiki links
        # Try relative to source directory first
        if source_dir:
            relative_path = source_dir / f"{target}.md"
            if relative_path.exists():
                return relative_path

        # Search in common locations
        search_dirs = [
            self.vault_path / "Knowledge" / "Concepts",
            self.vault_path / "Knowledge" / "Facts",
            self.vault_path / "Knowledge" / "Products",
            self.vault_path / "Knowledge" / "Research",
            self.vault_path / "Beliefs",
            self.vault_path / "Maps",
            self.vault_path,
        ]

        filename = self._normalize_filename(target)

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            # Try exact match
            target_path = search_dir / f"{filename}.md"
            if target_path.exists():
                return target_path

            # Try case-insensitive
            found = self._find_case_insensitive(search_dir, filename)
            if found:
                return found

        # Not found
        logger.debug(f"[BacklinkScanner] Could not resolve link: {link}")
        return None

    def _normalize_filename(self, name: str) -> str:
        """
        Normalize a link target to a filename.

        Converts "Some Name" to "some-name" or "some_name".
        """
        # Replace spaces with hyphens
        filename = name.lower().replace(" ", "-")
        # Remove or replace problematic characters
        filename = re.sub(r'[<>:"/\\|?*]', "", filename)
        return filename

    def _find_case_insensitive(
        self,
        directory: Path,
        filename: str
    ) -> Optional[Path]:
        """
        Find a file in a directory using case-insensitive matching.

        Args:
            directory: Directory to search.
            filename: Filename (without extension) to find.

        Returns:
            Path to matching file, or None.
        """
        if not directory.exists():
            return None

        filename_lower = filename.lower()

        for file_path in directory.iterdir():
            if file_path.is_file() and file_path.suffix.lower() == ".md":
                if file_path.stem.lower() == filename_lower:
                    return file_path

        return None

    # =========================================================================
    # Registration Methods
    # =========================================================================

    def scan_and_register(
        self,
        file_path: Path,
        user_id: str = "default"
    ) -> int:
        """
        Scan a file for wiki links and register backlinks in the database.

        Args:
            file_path: Path to the markdown file.
            user_id: User ID for resolving turn links.

        Returns:
            Number of backlinks registered.
        """
        if not self.kg:
            logger.warning("[BacklinkScanner] No KnowledgeGraphDB - skipping registration")
            return 0

        links = self.scan_file(file_path)
        if not links:
            return 0

        # Make source path relative to vault
        try:
            source_relative = file_path.relative_to(self.vault_path)
        except ValueError:
            source_relative = file_path

        source_str = str(source_relative)
        source_dir = file_path.parent

        registered = 0
        for link in links:
            # Resolve target path
            target_path = self.resolve_link_target(link, source_dir, user_id)

            if target_path:
                try:
                    target_relative = target_path.relative_to(self.vault_path)
                except ValueError:
                    target_relative = target_path

                target_str = str(target_relative)
            else:
                # Use the raw target for unresolved links
                target_str = link.target

            # Build link text for display
            if link.entity_type:
                link_text = f"[[{link.entity_type}:{link.target}]]"
            else:
                link_text = f"[[{link.target}]]"

            # Register in database
            try:
                self.kg.add_backlink(
                    source_file=source_str,
                    target_file=target_str,
                    link_text=link_text,
                    link_type=link.link_type,
                    line_number=link.line_number
                )
                registered += 1
            except Exception as e:
                logger.error(f"[BacklinkScanner] Failed to register backlink: {e}")

        logger.debug(f"[BacklinkScanner] Registered {registered} backlinks from {file_path}")
        return registered

    def rebuild_all_backlinks(
        self,
        vault_path: Optional[Path] = None,
        user_id: str = "default"
    ) -> Dict[str, int]:
        """
        Scan entire vault and rebuild the backlink index.

        Args:
            vault_path: Path to the vault. Defaults to self.vault_path.
            user_id: User ID for resolving turn links.

        Returns:
            Dict with scan statistics: {"files_scanned", "links_found", "links_registered"}
        """
        vault = vault_path or self.vault_path

        if not vault.exists():
            logger.error(f"[BacklinkScanner] Vault path does not exist: {vault}")
            return {"files_scanned": 0, "links_found": 0, "links_registered": 0}

        # Clear existing backlinks if we have a database
        if self.kg:
            try:
                self.kg.clear_backlinks()
            except Exception as e:
                logger.warning(f"[BacklinkScanner] Could not clear existing backlinks: {e}")

        stats = {
            "files_scanned": 0,
            "links_found": 0,
            "links_registered": 0,
        }

        # Recursively scan all markdown files
        for md_file in vault.rglob("*.md"):
            # Skip hidden files and directories
            if any(part.startswith(".") for part in md_file.parts):
                continue

            stats["files_scanned"] += 1
            links = self.scan_file(md_file)
            stats["links_found"] += len(links)

            if self.kg:
                registered = self.scan_and_register(md_file, user_id)
                stats["links_registered"] += registered

        logger.info(
            f"[BacklinkScanner] Rebuilt backlink index: "
            f"scanned {stats['files_scanned']} files, "
            f"found {stats['links_found']} links, "
            f"registered {stats['links_registered']} backlinks"
        )

        return stats

    # =========================================================================
    # Orphan Detection
    # =========================================================================

    def get_orphan_files(
        self,
        vault_path: Optional[Path] = None,
        exclude_dirs: Optional[List[str]] = None
    ) -> List[Path]:
        """
        Find files with no incoming backlinks (orphan files).

        Orphan files are markdown files that are not linked to from any other file.
        These may be candidates for cleanup or better integration.

        Args:
            vault_path: Path to the vault. Defaults to self.vault_path.
            exclude_dirs: Directory names to exclude (e.g., ["Meta", "Logs"]).

        Returns:
            List of paths to orphan files.
        """
        vault = vault_path or self.vault_path
        exclude_dirs = exclude_dirs or ["Meta", "Logs", ".obsidian"]

        if not vault.exists():
            return []

        # Collect all markdown files
        all_files: Set[Path] = set()
        for md_file in vault.rglob("*.md"):
            # Skip excluded directories
            if any(excluded in md_file.parts for excluded in exclude_dirs):
                continue
            # Skip hidden files
            if any(part.startswith(".") for part in md_file.parts):
                continue
            all_files.add(md_file)

        # Collect all link targets
        linked_files: Set[Path] = set()

        for md_file in all_files:
            links = self.scan_file(md_file)
            for link in links:
                target = self.resolve_link_target(link, md_file.parent)
                if target and target.exists():
                    linked_files.add(target)

        # Orphans are files with no incoming links
        orphans = all_files - linked_files

        # Sort for consistent output
        return sorted(orphans)

    def get_link_statistics(
        self,
        vault_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Get statistics about links in the vault.

        Returns:
            Dict with statistics about link density, orphans, etc.
        """
        vault = vault_path or self.vault_path

        if not vault.exists():
            return {}

        stats = {
            "total_files": 0,
            "total_links": 0,
            "wiki_links": 0,
            "entity_links": 0,
            "turn_links": 0,
            "orphan_count": 0,
            "average_links_per_file": 0.0,
            "most_linked_targets": [],
        }

        target_counts: Dict[str, int] = {}

        for md_file in vault.rglob("*.md"):
            if any(part.startswith(".") for part in md_file.parts):
                continue

            stats["total_files"] += 1
            links = self.scan_file(md_file)
            stats["total_links"] += len(links)

            for link in links:
                if link.link_type == "wiki":
                    stats["wiki_links"] += 1
                elif link.link_type == "entity":
                    stats["entity_links"] += 1
                elif link.link_type == "turn":
                    stats["turn_links"] += 1

                # Track target popularity
                target_key = f"{link.entity_type}:{link.target}" if link.entity_type else link.target
                target_counts[target_key] = target_counts.get(target_key, 0) + 1

        # Calculate averages
        if stats["total_files"] > 0:
            stats["average_links_per_file"] = stats["total_links"] / stats["total_files"]

        # Get most linked targets
        sorted_targets = sorted(target_counts.items(), key=lambda x: x[1], reverse=True)
        stats["most_linked_targets"] = sorted_targets[:10]

        # Count orphans
        orphans = self.get_orphan_files(vault)
        stats["orphan_count"] = len(orphans)

        return stats


# =============================================================================
# Convenience Functions
# =============================================================================

def scan_file_for_links(file_path: Path) -> List[Tuple[str, str, int]]:
    """
    Convenience function to scan a file for wiki links.

    Args:
        file_path: Path to the markdown file.

    Returns:
        List of (target, link_text, line_number) tuples.
    """
    scanner = BacklinkScanner()
    return scanner.scan_file_tuples(file_path)


def rebuild_vault_backlinks(
    vault_path: Path = None,
    kg: "KnowledgeGraphDB" = None
) -> Dict[str, int]:
    """
    Convenience function to rebuild all backlinks in a vault.

    Args:
        vault_path: Path to the vault.
        kg: Optional KnowledgeGraphDB for storing results.

    Returns:
        Statistics dict.
    """
    scanner = BacklinkScanner(kg=kg, vault_path=vault_path)
    return scanner.rebuild_all_backlinks()
