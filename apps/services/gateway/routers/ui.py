"""
UI Router

Provides endpoints for the frontend UI including file tree, repository listing,
and workspace configuration.

Endpoints:
    GET /ui/repos/base - Get current repos base directory
    POST /ui/repos/base - Set repos base directory
    GET /ui/repos - List repositories in the base directory
    GET /ui/filetree - Get jsTree-compatible file tree for a repository
"""

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from apps.services.gateway.config import (
    get_repos_base,
    set_repos_base,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/ui", tags=["ui"])

# Directories to exclude from file tree scanning
EXCLUDED_DIRS = frozenset({
    "node_modules",
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    ".svelte-kit",
    "build",
    "dist",
    ".next",
    ".nuxt",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
    ".coverage",
    "htmlcov",
    ".tox",
    ".eggs",
    "*.egg-info",
    ".idea",
    ".vscode",
})


def _generate_node_id(path: Path, base_path: Path) -> str:
    """Generate a unique ID for a tree node based on relative path."""
    try:
        rel = path.relative_to(base_path)
        # Use path components joined by underscore, replacing problematic chars
        return str(rel).replace("/", "_").replace("\\", "_").replace(".", "_dot_")
    except ValueError:
        # Fallback if path is not relative to base
        return path.name.replace(".", "_dot_")


def _should_exclude(name: str) -> bool:
    """Check if a file/directory name should be excluded."""
    # Check exact match
    if name in EXCLUDED_DIRS:
        return True
    # Check if it's a hidden file/directory (starts with .)
    # but allow certain config files
    if name.startswith(".") and name not in {".gitignore", ".env.example", ".editorconfig"}:
        return True
    # Check egg-info pattern
    if name.endswith(".egg-info"):
        return True
    return False


def _build_tree_node(
    path: Path,
    repo_path: Path,
    git_status: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """
    Recursively build a jsTree-compatible node structure.

    Args:
        path: Current file/directory path
        repo_path: Root repository path (for relative path calculation)
        git_status: Dictionary of relative paths to git status codes

    Returns:
        jsTree node dict or None if path should be excluded
    """
    # Skip excluded directories and files
    if _should_exclude(path.name):
        return None

    # Calculate relative path for git status lookup
    try:
        rel_path = str(path.relative_to(repo_path))
    except ValueError:
        rel_path = ""

    # Build base node
    node: Dict[str, Any] = {
        "id": _generate_node_id(path, repo_path),
        "text": path.name,
        "path": str(path),
    }

    # Add git status indicator if applicable
    status = git_status.get(rel_path, "")
    if status:
        node["git_status"] = status

    if path.is_dir():
        node["type"] = "folder"
        children: List[Dict[str, Any]] = []

        try:
            # Sort: folders first, then files, both alphabetically
            items = sorted(
                path.iterdir(),
                key=lambda x: (not x.is_dir(), x.name.lower())
            )

            for child in items:
                child_node = _build_tree_node(child, repo_path, git_status)
                if child_node is not None:
                    children.append(child_node)

        except PermissionError:
            logger.warning(f"[UI] Permission denied accessing: {path}")
        except OSError as e:
            logger.warning(f"[UI] Error accessing directory {path}: {e}")

        # jsTree expects 'children' to be array or false for empty folders
        node["children"] = children if children else False
    else:
        node["type"] = "file"

    return node


def _get_git_status(repo_path: Path) -> Dict[str, str]:
    """
    Get git status for all modified/staged files in a repository.

    Args:
        repo_path: Path to the git repository

    Returns:
        Dictionary mapping relative file paths to their git status codes
    """
    git_status: Dict[str, str] = {}

    # Check if this is a git repository
    if not (repo_path / ".git").exists():
        return git_status

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if len(line) > 3:
                    status = line[:2].strip()
                    filepath = line[3:].strip()
                    # Handle renamed files (old -> new)
                    if " -> " in filepath:
                        filepath = filepath.split(" -> ")[-1]
                    git_status[filepath] = status

    except subprocess.TimeoutExpired:
        logger.warning(f"[UI] Git status timed out for {repo_path}")
    except FileNotFoundError:
        logger.debug("[UI] Git command not found")
    except Exception as e:
        logger.warning(f"[UI] Error getting git status: {e}")

    return git_status


@router.get("/repos/base")
async def get_repo_base() -> Dict[str, str]:
    """
    Get the current repository base directory.

    Returns:
        Dictionary with 'path' key containing the base path
    """
    return {"path": str(get_repos_base())}


@router.post("/repos/base")
async def set_repo_base_endpoint(
    payload: Dict[str, Any] = Body(..., example={"path": "/home/user/projects"})
) -> Dict[str, str]:
    """
    Set the repository base directory.

    The path must exist and be a directory. The setting is persisted
    to disk and survives server restarts.

    Args:
        payload: Dictionary with 'path' key

    Returns:
        Dictionary with 'path' key containing the new base path

    Raises:
        HTTPException 400 if path is invalid or doesn't exist
    """
    path_value = (payload or {}).get("path")

    if not path_value or not isinstance(path_value, str):
        raise HTTPException(400, "Path is required and must be a string")

    try:
        candidate = Path(path_value).expanduser().resolve()
    except Exception as e:
        raise HTTPException(400, f"Invalid path format: {e}")

    if not candidate.exists():
        raise HTTPException(400, f"Path does not exist: {candidate}")

    if not candidate.is_dir():
        raise HTTPException(400, f"Path is not a directory: {candidate}")

    set_repos_base(candidate, persist=True)
    return {"path": str(get_repos_base())}


@router.get("/repos")
async def list_repos() -> Dict[str, Any]:
    """
    List repositories in the current base directory.

    Returns directories that exist within the repos base path,
    with an indicator of whether they contain a .git directory.

    Returns:
        Dictionary with 'repos' list containing repo info dicts
    """
    base = get_repos_base()

    if not base.exists() or not base.is_dir():
        return {"repos": [], "base": str(base)}

    repos: List[Dict[str, Any]] = []

    try:
        for item in sorted(base.iterdir(), key=lambda x: x.name.lower()):
            if item.is_dir() and not item.name.startswith("."):
                repos.append({
                    "name": item.name,
                    "path": str(item),
                    "git": (item / ".git").exists(),
                })
    except PermissionError:
        logger.warning(f"[UI] Permission denied listing repos at {base}")
    except OSError as e:
        logger.warning(f"[UI] Error listing repos: {e}")

    return {"repos": repos, "base": str(base)}


@router.get("/filetree")
async def get_filetree(
    repo: str = Query(..., description="Absolute path to the repository")
) -> Dict[str, Any]:
    """
    Get a jsTree-compatible file tree structure for a repository.

    The tree includes:
    - Unique IDs for each node
    - Type indicators (folder/file)
    - Absolute paths
    - Git status for modified files (if git repo)

    Directories are sorted before files, both alphabetically.
    Common non-essential directories are excluded (node_modules, __pycache__, etc.)

    Args:
        repo: Absolute path to the repository directory

    Returns:
        Dictionary with 'tree' array and 'repo' path

    Example response:
        {
            "tree": [
                {
                    "id": "src",
                    "text": "src",
                    "type": "folder",
                    "path": "/path/to/repo/src",
                    "children": [
                        {
                            "id": "src_main_py",
                            "text": "main.py",
                            "type": "file",
                            "path": "/path/to/repo/src/main.py"
                        }
                    ]
                }
            ],
            "repo": "/path/to/repo"
        }
    """
    # Validate and resolve the repo path
    try:
        repo_path = Path(repo).resolve()
    except Exception as e:
        raise HTTPException(400, f"Invalid path format: {e}")

    if not repo_path.exists():
        raise HTTPException(404, f"Repository path does not exist: {repo_path}")

    if not repo_path.is_dir():
        raise HTTPException(400, f"Path is not a directory: {repo_path}")

    # Security: Validate repo_path is within REPOS_BASE to prevent path traversal
    repos_base = get_repos_base()
    try:
        repo_path.relative_to(repos_base.resolve())
    except ValueError:
        raise HTTPException(
            403,
            f"Repository path must be within the configured base directory: {repos_base}"
        )

    # Get git status for modified files
    git_status = _get_git_status(repo_path)

    # Build the tree
    tree: List[Dict[str, Any]] = []

    try:
        # Sort: folders first, then files, both alphabetically
        items = sorted(
            repo_path.iterdir(),
            key=lambda x: (not x.is_dir(), x.name.lower())
        )

        for item in items:
            node = _build_tree_node(item, repo_path, git_status)
            if node is not None:
                tree.append(node)

    except PermissionError:
        raise HTTPException(403, f"Permission denied accessing: {repo_path}")
    except OSError as e:
        raise HTTPException(500, f"Error reading directory: {e}")

    return {
        "tree": tree,
        "repo": str(repo_path),
        "git": (repo_path / ".git").exists(),
    }
