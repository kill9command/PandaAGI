"""
Context Index - File indexing and retrieval for large repositories.

Indexes file trees with summaries, keywords, and metadata for fast
retrieval during Phase 2 context gathering.

Architecture Reference:
- architecture/concepts/CONTEXT_INDEX.md
"""

import hashlib
import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class FileEntry:
    """Indexed file entry."""
    path: str
    relative_path: str
    size: int
    modified: float
    category: str
    summary: str = ""
    keywords: List[str] = field(default_factory=list)
    content_hash: str = ""
    language: str = ""
    line_count: int = 0


@dataclass
class IndexResult:
    """Result of indexing a directory."""
    total_files: int
    indexed: int
    skipped: int
    errors: int
    categories: Dict[str, int]
    root_path: str


@dataclass
class SearchResult:
    """Result of searching the index."""
    entries: List[FileEntry]
    total_matches: int
    query: str


# File extension to category mapping
CATEGORY_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".md": "documentation",
    ".txt": "text",
    ".json": "config",
    ".yaml": "config",
    ".yml": "config",
    ".toml": "config",
    ".ini": "config",
    ".cfg": "config",
    ".html": "web",
    ".css": "web",
    ".sql": "database",
    ".sh": "script",
    ".bash": "script",
    ".dockerfile": "devops",
    ".xml": "data",
    ".csv": "data",
}

# Default ignore patterns
DEFAULT_IGNORE = {
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".tox", "dist", "build",
    "egg-info", ".eggs", ".cache",
}

# Max file size to index content (512KB)
MAX_INDEX_SIZE = 512 * 1024


class ContextIndex:
    """
    File index for large repository context retrieval.

    Features:
    - Indexes file trees with metadata and summaries
    - SQLite-backed for persistence
    - Keyword-based search
    - Category filtering
    - Incremental updates (only re-index changed files)
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize context index.

        Args:
            db_path: Path to SQLite database (default: in-memory)
        """
        self.db_path = str(db_path) if db_path else ":memory:"
        self._local = threading.local()
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS context_index (
                path TEXT PRIMARY KEY,
                relative_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                modified REAL NOT NULL,
                category TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                keywords TEXT DEFAULT '[]',
                content_hash TEXT DEFAULT '',
                language TEXT DEFAULT '',
                line_count INTEGER DEFAULT 0,
                indexed_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_category ON context_index(category);
            CREATE INDEX IF NOT EXISTS idx_language ON context_index(language);

            CREATE TABLE IF NOT EXISTS index_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        conn.commit()

    def index_directory(
        self,
        root: Path,
        patterns: Optional[List[str]] = None,
        ignore_dirs: Optional[set] = None,
        max_files: int = 10000,
    ) -> IndexResult:
        """
        Index a directory tree.

        Args:
            root: Root directory to index
            patterns: File glob patterns to include (default: all)
            ignore_dirs: Directory names to skip
            max_files: Maximum files to index

        Returns:
            IndexResult with statistics
        """
        root = Path(root).resolve()
        ignore = ignore_dirs or DEFAULT_IGNORE
        conn = self._get_conn()

        total = 0
        indexed = 0
        skipped = 0
        errors = 0
        categories: Dict[str, int] = {}

        for dirpath, dirnames, filenames in os.walk(root):
            # Filter ignored directories
            dirnames[:] = [d for d in dirnames if d not in ignore and not d.startswith(".")]

            for filename in filenames:
                if total >= max_files:
                    break

                filepath = Path(dirpath) / filename
                total += 1

                # Skip binary/large files
                if filepath.stat().st_size > MAX_INDEX_SIZE:
                    skipped += 1
                    continue

                # Apply pattern filter
                if patterns:
                    if not any(filepath.match(p) for p in patterns):
                        skipped += 1
                        continue

                try:
                    entry = self._index_file(filepath, root)
                    if entry:
                        self._upsert_entry(conn, entry)
                        indexed += 1
                        categories[entry.category] = categories.get(entry.category, 0) + 1
                except Exception as e:
                    errors += 1
                    logger.debug(f"[ContextIndex] Error indexing {filepath}: {e}")

        # Store metadata
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("root_path", str(root)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("last_indexed", datetime.now().isoformat()),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("total_files", str(indexed)),
        )
        conn.commit()

        logger.info(
            f"[ContextIndex] Indexed {indexed}/{total} files "
            f"({skipped} skipped, {errors} errors)"
        )

        return IndexResult(
            total_files=total,
            indexed=indexed,
            skipped=skipped,
            errors=errors,
            categories=categories,
            root_path=str(root),
        )

    def _index_file(self, filepath: Path, root: Path) -> Optional[FileEntry]:
        """Index a single file."""
        stat = filepath.stat()
        ext = filepath.suffix.lower()
        category = CATEGORY_MAP.get(ext, "other")
        relative = str(filepath.relative_to(root))

        # Check if already indexed and unchanged
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT modified, content_hash FROM context_index WHERE path = ?",
            (str(filepath),),
        ).fetchone()

        if existing and existing["modified"] == stat.st_mtime:
            return None  # Unchanged, skip

        # Read content for summary/keywords
        summary = ""
        keywords = []
        line_count = 0
        content_hash = ""
        language = self._detect_language(ext)

        try:
            content = filepath.read_text(errors="replace")
            line_count = content.count("\n") + 1
            content_hash = hashlib.md5(content.encode()).hexdigest()[:12]

            # Extract summary (first docstring or first few lines)
            summary = self._extract_summary(content, language)

            # Extract keywords
            keywords = self._extract_keywords(content, filepath.name, language)
        except Exception:
            pass

        return FileEntry(
            path=str(filepath),
            relative_path=relative,
            size=stat.st_size,
            modified=stat.st_mtime,
            category=category,
            summary=summary,
            keywords=keywords,
            content_hash=content_hash,
            language=language,
            line_count=line_count,
        )

    def _upsert_entry(self, conn: sqlite3.Connection, entry: FileEntry) -> None:
        """Insert or update a file entry."""
        conn.execute("""
            INSERT OR REPLACE INTO context_index
            (path, relative_path, size, modified, category, summary, keywords,
             content_hash, language, line_count, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry.path,
            entry.relative_path,
            entry.size,
            entry.modified,
            entry.category,
            entry.summary,
            json.dumps(entry.keywords),
            entry.content_hash,
            entry.language,
            entry.line_count,
            datetime.now().timestamp(),
        ))

    def search(
        self,
        query: str,
        category: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 20,
    ) -> SearchResult:
        """
        Search the index.

        Args:
            query: Search query (matches path, summary, keywords)
            category: Filter by category
            language: Filter by language
            limit: Maximum results

        Returns:
            SearchResult with matching entries
        """
        conn = self._get_conn()
        query_lower = query.lower()
        terms = query_lower.split()

        # Build SQL query
        conditions = []
        params = []

        for term in terms:
            conditions.append(
                "(LOWER(relative_path) LIKE ? OR LOWER(summary) LIKE ? OR LOWER(keywords) LIKE ?)"
            )
            like = f"%{term}%"
            params.extend([like, like, like])

        if category:
            conditions.append("category = ?")
            params.append(category)

        if language:
            conditions.append("language = ?")
            params.append(language)

        where = " AND ".join(conditions) if conditions else "1=1"

        # Execute search
        rows = conn.execute(
            f"SELECT * FROM context_index WHERE {where} ORDER BY modified DESC LIMIT ?",
            params + [limit],
        ).fetchall()

        entries = [self._row_to_entry(row) for row in rows]

        # Get total count
        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM context_index WHERE {where}",
            params,
        ).fetchone()
        total = count_row["cnt"] if count_row else len(entries)

        return SearchResult(
            entries=entries,
            total_matches=total,
            query=query,
        )

    def get_summary(self, max_tokens: int = 1000) -> str:
        """
        Get compact index summary for planner.

        Args:
            max_tokens: Approximate token limit

        Returns:
            Summary string with directory structure and key files
        """
        conn = self._get_conn()

        # Get categories
        categories = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM context_index GROUP BY category ORDER BY cnt DESC"
        ).fetchall()

        # Get top directories
        dirs = conn.execute("""
            SELECT
                SUBSTR(relative_path, 1, INSTR(relative_path || '/', '/')) as dir,
                COUNT(*) as cnt
            FROM context_index
            GROUP BY dir
            ORDER BY cnt DESC
            LIMIT 15
        """).fetchall()

        # Get largest files
        large_files = conn.execute(
            "SELECT relative_path, size, category FROM context_index ORDER BY size DESC LIMIT 5"
        ).fetchall()

        # Get recently modified
        recent = conn.execute(
            "SELECT relative_path, category FROM context_index ORDER BY modified DESC LIMIT 5"
        ).fetchall()

        # Get metadata
        meta = {}
        for row in conn.execute("SELECT key, value FROM index_meta").fetchall():
            meta[row["key"]] = row["value"]

        # Build summary
        lines = []
        lines.append(f"Repository: {meta.get('root_path', 'unknown')}")
        lines.append(f"Total indexed: {meta.get('total_files', '0')} files")
        lines.append(f"Last indexed: {meta.get('last_indexed', 'never')}")
        lines.append("")

        lines.append("Categories:")
        for row in categories:
            lines.append(f"  {row['category']}: {row['cnt']} files")
        lines.append("")

        lines.append("Top directories:")
        for row in dirs[:10]:
            lines.append(f"  {row['dir']} ({row['cnt']} files)")
        lines.append("")

        lines.append("Recently modified:")
        for row in recent:
            lines.append(f"  {row['relative_path']} [{row['category']}]")

        summary = "\n".join(lines)

        # Rough token truncation
        if len(summary) > max_tokens * 4:
            summary = summary[: max_tokens * 4] + "\n..."

        return summary

    def get_files_by_category(
        self,
        category: str,
        limit: int = 50,
    ) -> List[FileEntry]:
        """Get files by category."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM context_index WHERE category = ? ORDER BY modified DESC LIMIT ?",
            (category, limit),
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_file(self, path: str) -> Optional[FileEntry]:
        """Get a specific file entry."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM context_index WHERE path = ? OR relative_path = ?",
            (path, path),
        ).fetchone()
        return self._row_to_entry(row) if row else None

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        conn = self._get_conn()

        total = conn.execute("SELECT COUNT(*) as cnt FROM context_index").fetchone()["cnt"]

        categories = {}
        for row in conn.execute(
            "SELECT category, COUNT(*) as cnt FROM context_index GROUP BY category"
        ).fetchall():
            categories[row["category"]] = row["cnt"]

        languages = {}
        for row in conn.execute(
            "SELECT language, COUNT(*) as cnt FROM context_index WHERE language != '' GROUP BY language"
        ).fetchall():
            languages[row["language"]] = row["cnt"]

        total_size = conn.execute(
            "SELECT SUM(size) as total FROM context_index"
        ).fetchone()["total"] or 0

        total_lines = conn.execute(
            "SELECT SUM(line_count) as total FROM context_index"
        ).fetchone()["total"] or 0

        return {
            "total_files": total,
            "total_size_bytes": total_size,
            "total_lines": total_lines,
            "categories": categories,
            "languages": languages,
        }

    def clear(self) -> None:
        """Clear the entire index."""
        conn = self._get_conn()
        conn.execute("DELETE FROM context_index")
        conn.execute("DELETE FROM index_meta")
        conn.commit()

    def _row_to_entry(self, row: sqlite3.Row) -> FileEntry:
        """Convert a database row to FileEntry."""
        keywords = []
        try:
            keywords = json.loads(row["keywords"])
        except (json.JSONDecodeError, TypeError):
            pass

        return FileEntry(
            path=row["path"],
            relative_path=row["relative_path"],
            size=row["size"],
            modified=row["modified"],
            category=row["category"],
            summary=row["summary"],
            keywords=keywords,
            content_hash=row["content_hash"],
            language=row["language"],
            line_count=row["line_count"],
        )

    @staticmethod
    def _detect_language(ext: str) -> str:
        """Detect programming language from extension."""
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".php": "php",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".cs": "csharp",
            ".swift": "swift",
            ".kt": "kotlin",
            ".r": "r",
            ".sql": "sql",
            ".sh": "bash",
            ".md": "markdown",
        }
        return lang_map.get(ext, "")

    @staticmethod
    def _extract_summary(content: str, language: str) -> str:
        """Extract summary from file content."""
        lines = content.split("\n")

        # Try to find docstring/module doc
        if language == "python":
            # Look for module-level docstring
            for i, line in enumerate(lines[:10]):
                stripped = line.strip()
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    # Collect docstring lines
                    quote = stripped[:3]
                    if stripped.endswith(quote) and len(stripped) > 6:
                        return stripped[3:-3].strip()
                    doc_lines = [stripped[3:]]
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if quote in lines[j]:
                            doc_lines.append(lines[j].split(quote)[0])
                            break
                        doc_lines.append(lines[j].strip())
                    return " ".join(doc_lines).strip()

        # Fallback: first non-empty, non-comment line
        for line in lines[:5]:
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", "//", "/*", "*", "<!--")):
                return stripped[:200]

        return ""

    @staticmethod
    def _extract_keywords(content: str, filename: str, language: str) -> List[str]:
        """Extract keywords from file content."""
        import re

        keywords = set()

        # Add filename parts
        name_parts = re.split(r"[_.\-/]", filename.rsplit(".", 1)[0])
        keywords.update(p.lower() for p in name_parts if len(p) > 2)

        # Extract class/function names for Python
        if language == "python":
            for match in re.finditer(r"(?:class|def)\s+(\w+)", content):
                name = match.group(1)
                if not name.startswith("_"):
                    keywords.add(name.lower())

        # Extract imports
        if language == "python":
            for match in re.finditer(r"(?:from|import)\s+([\w.]+)", content):
                module = match.group(1).split(".")[-1]
                if len(module) > 2:
                    keywords.add(module.lower())

        return sorted(list(keywords))[:20]


# Singleton
_context_index: Optional[ContextIndex] = None


def get_context_index(db_path: Optional[Path] = None) -> ContextIndex:
    """Get or create the singleton ContextIndex."""
    global _context_index
    if _context_index is None:
        _context_index = ContextIndex(db_path=db_path)
    return _context_index
