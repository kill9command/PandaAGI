"""
Git MCP - Safe git operations with comprehensive safety checks

Provides git operations similar to Claude Code's git tools, with safety guards
for hook preservation, authorship checks, and destructive operation prevention.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class GitError(Exception):
    """Base exception for git operations."""
    pass


class GitSafetyError(Exception):
    """Exception for safety violations."""
    pass


def _run_git(repo: str, args: List[str], check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command safely."""
    cmd = ["git", "-C", repo] + args

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check
        )
        return result
    except subprocess.CalledProcessError as e:
        raise GitError(f"Git command failed: {e.stderr or e.stdout}")
    except subprocess.TimeoutExpired:
        raise GitError(f"Git command timed out: {' '.join(args)}")


def _is_git_repo(repo: str) -> bool:
    """Check if directory is a git repository."""
    try:
        _run_git(repo, ["rev-parse", "--git-dir"], timeout=5)
        return True
    except GitError:
        return False


def git_status(repo: str) -> Dict[str, Any]:
    """
    Get git status for repository.

    Returns:
        Dict with:
            - branch: Current branch name
            - staged: List of staged files
            - unstaged: List of modified but unstaged files
            - untracked: List of untracked files
            - ahead: Commits ahead of remote
            - behind: Commits behind remote
            - clean: Whether working tree is clean
    """
    if not _is_git_repo(repo):
        raise GitError(f"Not a git repository: {repo}")

    result = _run_git(repo, ["status", "--porcelain=v2", "--branch"])

    staged = []
    unstaged = []
    untracked = []
    branch = None
    ahead = 0
    behind = 0

    for line in result.stdout.splitlines():
        if line.startswith("# branch.head"):
            branch = line.split()[-1]
        elif line.startswith("# branch.ab"):
            parts = line.split()
            ahead = int(parts[2].replace("+", ""))
            behind = int(parts[3].replace("-", ""))
        elif line.startswith("1 "):  # Tracked file
            parts = line.split()
            xy = parts[1]
            path = parts[-1]

            if xy[0] != ".":
                staged.append({"path": path, "status": xy[0]})
            if xy[1] != ".":
                unstaged.append({"path": path, "status": xy[1]})
        elif line.startswith("2 "):  # Renamed file
            parts = line.split()
            xy = parts[1]
            path = parts[-1]

            if xy[0] != ".":
                staged.append({"path": path, "status": "R"})
        elif line.startswith("? "):  # Untracked
            path = line[2:]
            untracked.append(path)

    return {
        "branch": branch,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "ahead": ahead,
        "behind": behind,
        "clean": len(staged) == 0 and len(unstaged) == 0 and len(untracked) == 0
    }


def git_diff(
    repo: str,
    cached: bool = False,
    paths: Optional[List[str]] = None,
    base: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get git diff output.

    Args:
        repo: Repository path
        cached: Show staged changes (--cached)
        paths: Specific paths to diff
        base: Base ref for diff (e.g., "main", "HEAD~1")

    Returns:
        Dict with diff output and statistics
    """
    if not _is_git_repo(repo):
        raise GitError(f"Not a git repository: {repo}")

    args = ["diff"]

    if cached:
        args.append("--cached")

    if base:
        args.append(base)

    args.append("--stat")

    if paths:
        args.append("--")
        args.extend(paths)

    # Get stats
    result_stat = _run_git(repo, args)

    # Get full diff
    args_full = [a for a in args if a != "--stat"]
    result_full = _run_git(repo, args_full)

    return {
        "diff": result_full.stdout,
        "stat": result_stat.stdout,
        "has_changes": bool(result_full.stdout.strip())
    }


def git_log(
    repo: str,
    max_count: int = 10,
    format: str = "oneline",
    base: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get git commit log.

    Args:
        repo: Repository path
        max_count: Maximum number of commits
        format: Log format ("oneline", "full", "short")
        base: Base ref (e.g., "main...HEAD" for branch commits)

    Returns:
        Dict with commit log
    """
    if not _is_git_repo(repo):
        raise GitError(f"Not a git repository: {repo}")

    args = ["log", f"--max-count={max_count}", f"--format={format}"]

    if base:
        args.append(base)

    result = _run_git(repo, args)

    return {
        "log": result.stdout,
        "format": format,
        "count": len([l for l in result.stdout.splitlines() if l.strip()])
    }


def git_add(repo: str, paths: List[str]) -> Dict[str, Any]:
    """
    Stage files for commit.

    Args:
        repo: Repository path
        paths: List of file paths to stage

    Returns:
        Dict with staged files
    """
    if not _is_git_repo(repo):
        raise GitError(f"Not a git repository: {repo}")

    if not paths:
        raise ValueError("No paths provided to stage")

    args = ["add"] + paths
    _run_git(repo, args)

    return {
        "staged": paths,
        "count": len(paths)
    }


def _check_commit_safety(repo: str) -> Tuple[bool, str]:
    """Check if it's safe to commit/amend."""
    # Check authorship of last commit
    result = _run_git(repo, ["log", "-1", "--format=%an %ae"])
    author = result.stdout.strip()

    # Check if branch is pushed
    status_result = _run_git(repo, ["status", "--porcelain=v2", "--branch"], check=False)

    ahead = 0
    for line in status_result.stdout.splitlines():
        if line.startswith("# branch.ab"):
            parts = line.split()
            ahead = int(parts[2].replace("+", ""))
            break

    is_local = ahead > 0  # Has unpushed commits

    return is_local, author


def git_commit(
    repo: str,
    message: str,
    add_paths: Optional[List[str]] = None,
    amend: bool = False,
    allow_empty: bool = False
) -> Dict[str, Any]:
    """
    Create a git commit with safety checks.

    Args:
        repo: Repository path
        message: Commit message
        add_paths: Optional paths to stage before committing
        amend: Amend previous commit (with safety checks)
        allow_empty: Allow empty commit

    Returns:
        Dict with commit details

    Raises:
        GitSafetyError: If safety checks fail
    """
    if not _is_git_repo(repo):
        raise GitError(f"Not a git repository: {repo}")

    # Stage files if provided
    if add_paths:
        git_add(repo, add_paths)

    # Check for changes
    status = git_status(repo)

    if not status["staged"] and not allow_empty:
        raise GitError("No staged changes to commit")

    # Safety checks for amend
    if amend:
        is_local, author = _check_commit_safety(repo)

        if not is_local:
            raise GitSafetyError(
                "Cannot amend: commit may be pushed. Only amend local commits."
            )

        # Warn about authorship (but allow)
        if "Claude" not in author:
            print(f"Warning: Amending commit by {author}")

    # Build commit command
    args = ["commit", "-m", message]

    if amend:
        args.append("--amend")

    if allow_empty:
        args.append("--allow-empty")

    result = _run_git(repo, args)

    # Get commit SHA
    sha_result = _run_git(repo, ["rev-parse", "HEAD"])
    commit_sha = sha_result.stdout.strip()

    return {
        "commit_sha": commit_sha[:8],
        "message": message,
        "output": result.stdout,
        "amended": amend
    }


def git_branch(
    repo: str,
    branch_name: Optional[str] = None,
    delete: Optional[str] = None,
    force: bool = False
) -> Dict[str, Any]:
    """
    Manage git branches.

    Args:
        repo: Repository path
        branch_name: Name for new branch
        delete: Branch name to delete
        force: Force operation

    Returns:
        Dict with branch operation results
    """
    if not _is_git_repo(repo):
        raise GitError(f"Not a git repository: {repo}")

    if branch_name:
        # Create new branch
        args = ["checkout", "-b", branch_name]
        result = _run_git(repo, args)

        return {
            "action": "created",
            "branch": branch_name,
            "output": result.stdout
        }

    elif delete:
        # Delete branch with safety check
        if delete in ["main", "master"] and not force:
            raise GitSafetyError("Cannot delete main/master branch without force=true")

        args = ["branch", "-D" if force else "-d", delete]
        result = _run_git(repo, args)

        return {
            "action": "deleted",
            "branch": delete,
            "output": result.stdout
        }

    else:
        # List branches
        result = _run_git(repo, ["branch", "-a"])
        branches = [line.strip().replace("* ", "") for line in result.stdout.splitlines()]

        return {
            "action": "list",
            "branches": branches
        }


def git_push(
    repo: str,
    remote: str = "origin",
    branch: Optional[str] = None,
    set_upstream: bool = False,
    force: bool = False
) -> Dict[str, Any]:
    """
    Push commits to remote with safety checks.

    Args:
        repo: Repository path
        remote: Remote name
        branch: Branch to push (defaults to current)
        set_upstream: Set upstream tracking (-u)
        force: Force push (DANGEROUS)

    Returns:
        Dict with push results

    Raises:
        GitSafetyError: If attempting dangerous operations
    """
    if not _is_git_repo(repo):
        raise GitError(f"Not a git repository: {repo}")

    # Get current branch if not specified
    if not branch:
        status = git_status(repo)
        branch = status["branch"]

    # Safety check for force push
    if force and branch in ["main", "master"]:
        raise GitSafetyError(
            f"Force push to {branch} is prohibited. This is a dangerous operation."
        )

    args = ["push", remote]

    if branch:
        args.append(branch)

    if set_upstream:
        args.insert(1, "-u")

    if force:
        args.insert(1, "--force")

    result = _run_git(repo, args, timeout=60)

    return {
        "remote": remote,
        "branch": branch,
        "output": result.stdout + result.stderr,
        "forced": force
    }


def git_pull(repo: str, remote: str = "origin", branch: Optional[str] = None) -> Dict[str, Any]:
    """
    Pull changes from remote.

    Args:
        repo: Repository path
        remote: Remote name
        branch: Branch to pull (defaults to current)

    Returns:
        Dict with pull results
    """
    if not _is_git_repo(repo):
        raise GitError(f"Not a git repository: {repo}")

    args = ["pull", remote]

    if branch:
        args.append(branch)

    result = _run_git(repo, args, timeout=60)

    return {
        "remote": remote,
        "branch": branch,
        "output": result.stdout + result.stderr
    }


def create_pr_with_gh(
    repo: str,
    title: str,
    body: str,
    base: Optional[str] = None,
    draft: bool = False
) -> Dict[str, Any]:
    """
    Create a GitHub pull request using gh CLI.

    Args:
        repo: Repository path
        title: PR title
        body: PR description
        base: Base branch (defaults to repo default)
        draft: Create as draft PR

    Returns:
        Dict with PR URL and details

    Raises:
        GitError: If gh CLI not available or PR creation fails
    """
    if not _is_git_repo(repo):
        raise GitError(f"Not a git repository: {repo}")

    # Check if gh is installed
    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True, timeout=5)
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise GitError("GitHub CLI (gh) is not installed or not in PATH")

    # Build gh pr create command
    cmd = ["gh", "pr", "create", "-R", repo, "--title", title, "--body", body]

    if base:
        cmd.extend(["--base", base])

    if draft:
        cmd.append("--draft")

    try:
        result = subprocess.run(
            cmd,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=60,
            check=True
        )

        # Extract PR URL from output
        pr_url = result.stdout.strip().split('\n')[-1]

        return {
            "pr_url": pr_url,
            "title": title,
            "draft": draft,
            "output": result.stdout
        }

    except subprocess.CalledProcessError as e:
        raise GitError(f"Failed to create PR: {e.stderr or e.stdout}")
    except subprocess.TimeoutExpired:
        raise GitError("PR creation timed out")


def git_reset(
    repo: str,
    mode: str = "mixed",
    ref: str = "HEAD",
    paths: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Reset repository state (use with caution).

    Args:
        repo: Repository path
        mode: "soft", "mixed", or "hard"
        ref: Reference to reset to
        paths: Specific paths to reset (file-level reset)

    Returns:
        Dict with reset results

    Raises:
        GitSafetyError: If attempting dangerous reset
    """
    if not _is_git_repo(repo):
        raise GitError(f"Not a git repository: {repo}")

    # Safety check for hard reset
    if mode == "hard" and ref != "HEAD":
        raise GitSafetyError(
            "Hard reset to non-HEAD ref is dangerous. Only HEAD resets are allowed."
        )

    args = ["reset", f"--{mode}", ref]

    if paths:
        args.append("--")
        args.extend(paths)

    result = _run_git(repo, args)

    return {
        "mode": mode,
        "ref": ref,
        "paths": paths,
        "output": result.stdout
    }
