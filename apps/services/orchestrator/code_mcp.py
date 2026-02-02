"""
Code MCP - File operations for code manipulation

Provides robust file reading, writing, editing, globbing, and grepping
capabilities similar to Claude Code's file operation tools.
"""

import glob
import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Maximum file size to read (5MB - increased for large repos)
MAX_FILE_SIZE = 5_000_000
# Warning threshold for large files (1MB)
LARGE_FILE_WARNING = 1_000_000
# Chunk size for reading large files (100KB)
CHUNK_SIZE = 100_000
# Maximum lines to return by default
DEFAULT_LINE_LIMIT = 2000
# Maximum line length before truncation
MAX_LINE_LENGTH = 2000


def _safe_path(base_path: str, target_path: str) -> Path:
    """Resolve and validate that target_path is under base_path."""
    base = Path(base_path).resolve()
    target = (base / target_path).resolve()

    if not target.is_relative_to(base):
        raise ValueError(f"Path {target_path} is outside base directory {base_path}")

    return target


def _digest(text: str) -> str:
    """Create short hash digest of text."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def read_file(
    file_path: str,
    repo: Optional[str] = None,
    offset: int = 0,
    limit: Optional[int] = None,
    max_bytes: int = MAX_FILE_SIZE
) -> Dict[str, Any]:
    """
    Read a file with optional line offset and limit.

    Args:
        file_path: Absolute path or relative to repo
        repo: Base repository path for safety checks
        offset: Starting line number (0-indexed)
        limit: Maximum number of lines to return
        max_bytes: Maximum file size to read

    Returns:
        Dict with:
            - path: Full file path
            - lines: List of line strings
            - total_lines: Total line count in file
            - offset: Starting line number
            - limit: Lines returned
            - truncated: Whether file was truncated
            - digest: Content hash
    """
    if repo:
        full_path = _safe_path(repo, file_path)
    else:
        full_path = Path(file_path).resolve()

    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {full_path}")

    if not full_path.is_file():
        raise ValueError(f"Not a file: {full_path}")

    # Check file size
    file_size = full_path.stat().st_size
    large_file_warning = file_size > LARGE_FILE_WARNING

    if file_size > max_bytes:
        raise ValueError(f"File too large: {file_size} bytes (max {max_bytes})")

    # Read file
    try:
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read(max_bytes)
    except UnicodeDecodeError:
        # Binary file
        raise ValueError(f"Cannot read binary file: {full_path}")

    # Split into lines
    all_lines = content.splitlines()
    total_lines = len(all_lines)

    # Apply offset and limit
    start = max(0, offset)
    end = start + (limit or DEFAULT_LINE_LIMIT)
    selected_lines = all_lines[start:end]

    # Truncate long lines
    truncated_lines = []
    for line in selected_lines:
        if len(line) > MAX_LINE_LENGTH:
            truncated_lines.append(line[:MAX_LINE_LENGTH] + "... [truncated]")
        else:
            truncated_lines.append(line)

    # Format with line numbers (cat -n style)
    numbered_lines = []
    for i, line in enumerate(truncated_lines, start=start + 1):
        numbered_lines.append(f"{i:6d}\t{line}")

    return {
        "path": str(full_path),
        "lines": numbered_lines,
        "content": "\n".join(numbered_lines),
        "total_lines": total_lines,
        "file_size": file_size,
        "large_file_warning": large_file_warning,
        "offset": start,
        "limit": len(selected_lines),
        "truncated": file_size >= max_bytes or len(selected_lines) < (end - start),
        "digest": _digest(content),
        "suggested_action": "use_chunks" if large_file_warning else None
    }


def write_file(
    file_path: str,
    content: str,
    repo: Optional[str] = None,
    mode: str = "fail_if_exists"
) -> Dict[str, Any]:
    """
    Write content to a file.

    Args:
        file_path: Relative path to file
        content: File content
        repo: Base repository path
        mode: 'fail_if_exists', 'overwrite', or 'append'

    Returns:
        Dict with path, digest, and bytes written
    """
    if repo:
        full_path = _safe_path(repo, file_path)
    else:
        full_path = Path(file_path).resolve()

    # Check existence
    if full_path.exists() and mode == "fail_if_exists":
        raise FileExistsError(f"File already exists: {full_path}")

    # Create parent directories
    full_path.parent.mkdir(parents=True, exist_ok=True)

    # Write file
    if mode == "append" and full_path.exists():
        with open(full_path, 'a', encoding='utf-8') as f:
            f.write(content)
    else:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)

    return {
        "path": str(full_path),
        "bytes": len(content.encode('utf-8')),
        "digest": _digest(content),
        "mode": mode
    }


def delete_file(
    file_path: str,
    repo: Optional[str] = None,
    fail_if_missing: bool = True
) -> Dict[str, Any]:
    """
    Delete a file.

    Args:
        file_path: Relative path to file
        repo: Base repository path
        fail_if_missing: Whether to raise error if file doesn't exist

    Returns:
        Dict with path and deletion status
    """
    if repo:
        full_path = _safe_path(repo, file_path)
    else:
        full_path = Path(file_path).resolve()

    # Check existence
    if not full_path.exists():
        if fail_if_missing:
            raise FileNotFoundError(f"File not found: {full_path}")
        else:
            return {
                "path": str(full_path),
                "deleted": False,
                "status": "not_found"
            }

    # Check if it's a file (not directory)
    if not full_path.is_file():
        raise ValueError(f"Not a file: {full_path}")

    # Get file info before deletion
    file_size = full_path.stat().st_size

    # Delete the file
    full_path.unlink()

    return {
        "path": str(full_path),
        "deleted": True,
        "bytes": file_size,
        "status": "deleted"
    }


def edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    repo: Optional[str] = None,
    replace_all: bool = False
) -> Dict[str, Any]:
    """
    Edit a file by replacing exact string matches.

    Args:
        file_path: Relative path to file
        old_string: String to replace
        new_string: Replacement string
        repo: Base repository path
        replace_all: Replace all occurrences (default: fail if not unique)

    Returns:
        Dict with path, changes made, and new digest
    """
    if repo:
        full_path = _safe_path(repo, file_path)
    else:
        full_path = Path(file_path).resolve()

    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {full_path}")

    # Read current content
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Check for old_string
    count = content.count(old_string)

    if count == 0:
        raise ValueError(f"String not found in file: {old_string[:100]}")

    if count > 1 and not replace_all:
        raise ValueError(
            f"String appears {count} times in file. Use replace_all=true to replace all occurrences."
        )

    # Perform replacement
    if replace_all:
        new_content = content.replace(old_string, new_string)
    else:
        new_content = content.replace(old_string, new_string, 1)

    # Write back
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    return {
        "path": str(full_path),
        "replacements": count if replace_all else 1,
        "digest": _digest(new_content),
        "preview": new_content[max(0, new_content.find(new_string) - 100):
                               new_content.find(new_string) + len(new_string) + 100]
    }


def glob_files(
    pattern: str,
    repo: Optional[str] = None,
    max_results: int = 100
) -> Dict[str, Any]:
    """
    Find files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g., "**/*.py", "src/**/*.ts")
        repo: Base repository path
        max_results: Maximum number of results

    Returns:
        Dict with matched file paths sorted by modification time
    """
    if repo:
        base_path = Path(repo).resolve()
    else:
        base_path = Path.cwd()

    # Perform glob search
    if '**' in pattern:
        matches = list(base_path.glob(pattern))
    else:
        # Use glob.glob for simpler patterns
        matches = [Path(p) for p in glob.glob(str(base_path / pattern), recursive=True)]

    # Filter to files only
    files = [p for p in matches if p.is_file()]

    # Sort by modification time (newest first)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    # Limit results
    files = files[:max_results]

    # Convert to relative paths
    relative_paths = []
    for f in files:
        try:
            rel = f.relative_to(base_path)
            relative_paths.append(str(rel))
        except ValueError:
            # File outside base path
            relative_paths.append(str(f))

    return {
        "pattern": pattern,
        "base_path": str(base_path),
        "matches": relative_paths,
        "count": len(relative_paths),
        "truncated": len(matches) > max_results
    }


def grep_files(
    pattern: str,
    repo: Optional[str] = None,
    file_pattern: Optional[str] = None,
    file_type: Optional[str] = None,
    context_before: int = 0,
    context_after: int = 0,
    max_results: int = 100,
    case_sensitive: bool = True,
    output_mode: str = "files_with_matches"
) -> Dict[str, Any]:
    """
    Search for pattern in files using ripgrep if available, otherwise Python regex.

    Args:
        pattern: Regex pattern to search for
        repo: Base repository path
        file_pattern: Glob pattern to filter files (e.g., "*.py")
        file_type: File type filter (e.g., "py", "js", "ts")
        context_before: Lines of context before match
        context_after: Lines of context after match
        max_results: Maximum number of results
        case_sensitive: Case-sensitive search
        output_mode: "files_with_matches", "content", or "count"

    Returns:
        Dict with search results
    """
    if repo:
        base_path = Path(repo).resolve()
    else:
        base_path = Path.cwd()

    # Try ripgrep first
    try:
        cmd = ["rg", "--json", pattern, str(base_path)]

        if not case_sensitive:
            cmd.insert(1, "-i")

        if file_pattern:
            cmd.extend(["--glob", file_pattern])

        if file_type:
            cmd.extend(["--type", file_type])

        if context_before > 0:
            cmd.extend(["-B", str(context_before)])

        if context_after > 0:
            cmd.extend(["-A", str(context_after)])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        # Parse ripgrep JSON output
        results = _parse_rg_json(result.stdout, output_mode, max_results)
        results["engine"] = "ripgrep"
        return results

    except (FileNotFoundError, subprocess.SubprocessError):
        # Fallback to Python regex
        return _grep_python(
            pattern, base_path, file_pattern, file_type,
            context_before, context_after, max_results,
            case_sensitive, output_mode
        )


def _parse_rg_json(output: str, output_mode: str, max_results: int) -> Dict[str, Any]:
    """Parse ripgrep JSON output."""
    import json

    files = set()
    matches = []
    counts = {}

    for line in output.splitlines():
        if not line.strip():
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if obj.get("type") == "match":
            data = obj.get("data", {})
            path = data.get("path", {}).get("text", "")
            line_num = data.get("line_number", 0)
            line_text = data.get("lines", {}).get("text", "")

            files.add(path)

            if output_mode == "content":
                matches.append({
                    "path": path,
                    "line": line_num,
                    "content": line_text.rstrip()
                })

            counts[path] = counts.get(path, 0) + 1

    if output_mode == "files_with_matches":
        return {
            "files": sorted(list(files))[:max_results],
            "count": len(files)
        }
    elif output_mode == "content":
        return {
            "matches": matches[:max_results],
            "count": len(matches)
        }
    elif output_mode == "count":
        return {
            "counts": counts,
            "total_matches": sum(counts.values())
        }

    return {"files": [], "count": 0}


def _grep_python(
    pattern: str,
    base_path: Path,
    file_pattern: Optional[str],
    file_type: Optional[str],
    context_before: int,
    context_after: int,
    max_results: int,
    case_sensitive: bool,
    output_mode: str
) -> Dict[str, Any]:
    """Fallback grep using Python regex."""
    # Compile regex
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern: {e}")

    # Determine file extensions
    extensions = []
    if file_type:
        ext_map = {
            "py": [".py"],
            "js": [".js"],
            "ts": [".ts", ".tsx"],
            "go": [".go"],
            "rs": [".rs"],
            "java": [".java"],
            "md": [".md"],
            "txt": [".txt"]
        }
        extensions = ext_map.get(file_type, [])

    # Collect files
    if file_pattern:
        files = list(base_path.glob(file_pattern))
    elif extensions:
        files = []
        for ext in extensions:
            files.extend(base_path.glob(f"**/*{ext}"))
    else:
        files = list(base_path.glob("**/*"))

    # Filter to files only
    files = [f for f in files if f.is_file()]

    # Search files
    file_matches = set()
    content_matches = []
    counts = {}

    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except:
            continue

        for i, line in enumerate(lines):
            if regex.search(line):
                rel_path = str(file_path.relative_to(base_path))
                file_matches.add(rel_path)
                counts[rel_path] = counts.get(rel_path, 0) + 1

                if output_mode == "content":
                    # Include context
                    context_lines = []
                    for j in range(max(0, i - context_before), min(len(lines), i + context_after + 1)):
                        context_lines.append(lines[j].rstrip())

                    content_matches.append({
                        "path": rel_path,
                        "line": i + 1,
                        "content": line.rstrip(),
                        "context": context_lines if (context_before > 0 or context_after > 0) else None
                    })

                if len(file_matches) >= max_results:
                    break

        if len(file_matches) >= max_results:
            break

    if output_mode == "files_with_matches":
        return {
            "files": sorted(list(file_matches))[:max_results],
            "count": len(file_matches),
            "engine": "python"
        }
    elif output_mode == "content":
        return {
            "matches": content_matches[:max_results],
            "count": len(content_matches),
            "engine": "python"
        }
    elif output_mode == "count":
        return {
            "counts": counts,
            "total_matches": sum(counts.values()),
            "engine": "python"
        }

    return {"files": [], "count": 0, "engine": "python"}
