"""
Context snapshot tool for repository state.

Captures current repository state for context injection before Guide runs.
This provides immediate repo awareness without requiring discovery tools.
"""
import subprocess
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def context_snapshot_repo(
    repo: str,
    max_commits: int = 3,
    **kwargs
) -> Dict[str, Any]:
    """
    Capture current repository state for context injection.

    MCP tool signature:
    {
        "name": "context.snapshot_repo",
        "description": "Get current repository state (branch, dirty files, recent commits)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository path"},
                "max_commits": {"type": "integer", "default": 3, "description": "Number of recent commits to include"}
            },
            "required": ["repo"]
        }
    }

    Args:
        repo: Repository path
        max_commits: Number of recent commits to include (default: 3)

    Returns:
        {
            "branch": "main",
            "dirty_files": ["auth.py", "test_auth.py"],
            "dirty_count": 2,
            "last_commits": [
                {"hash": "abc123", "message": "Add refresh token", "author": "user", "time": "2h ago"}
            ],
            "summary": "On main, 2 uncommitted changes, last commit 2h ago"
        }
    """
    try:
        repo_path = Path(repo).resolve()

        if not repo_path.exists():
            return {
                "error": f"Repository not found: {repo}",
                "branch": "unknown",
                "dirty_files": [],
                "summary": f"Repository not found: {repo}"
            }

        if not (repo_path / ".git").exists():
            return {
                "error": f"Not a git repository: {repo}",
                "branch": "unknown",
                "dirty_files": [],
                "summary": f"Not a git repository: {repo}"
            }

        # Get current branch
        branch = await _get_current_branch(repo_path)

        # Get dirty (uncommitted) files
        dirty_files = await _get_dirty_files(repo_path)

        # Get recent commits
        last_commits = await _get_recent_commits(repo_path, max_commits)

        # Generate summary
        summary = _generate_summary(branch, dirty_files, last_commits)

        return {
            "branch": branch,
            "dirty_files": dirty_files,
            "dirty_count": len(dirty_files),
            "last_commits": last_commits,
            "summary": summary
        }

    except Exception as e:
        logger.error(f"[context.snapshot_repo] Error: {e}")
        return {
            "error": str(e),
            "branch": "unknown",
            "dirty_files": [],
            "summary": f"Error capturing repo snapshot: {str(e)}"
        }


async def _get_current_branch(repo_path: Path) -> str:
    """Get current git branch."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=2
        )

        if result.returncode == 0:
            return result.stdout.strip()

        return "unknown"

    except Exception as e:
        logger.debug(f"[snapshot] Could not get branch: {e}")
        return "unknown"


async def _get_dirty_files(repo_path: Path) -> List[str]:
    """Get list of uncommitted (dirty) files."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=3
        )

        if result.returncode != 0:
            return []

        dirty_files = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            # Parse git status --porcelain output
            # Format: "XY filename" where X=index, Y=worktree
            status_code = line[:2]
            file_path = line[3:].strip()

            # Skip deleted files
            if "D" not in status_code:
                dirty_files.append(file_path)

        return dirty_files[:20]  # Limit to first 20 files

    except Exception as e:
        logger.debug(f"[snapshot] Could not get dirty files: {e}")
        return []


async def _get_recent_commits(repo_path: Path, max_commits: int) -> List[Dict[str, str]]:
    """Get recent commit history."""
    try:
        # Format: hash|author|time|message
        format_str = "%h|%an|%ar|%s"

        result = subprocess.run(
            ["git", "log", f"-n{max_commits}", f"--format={format_str}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=3
        )

        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            parts = line.split("|", maxsplit=3)
            if len(parts) == 4:
                commit_hash, author, time_ago, message = parts
                commits.append({
                    "hash": commit_hash,
                    "author": author,
                    "time": time_ago,
                    "message": message[:60]  # Truncate long messages
                })

        return commits

    except Exception as e:
        logger.debug(f"[snapshot] Could not get commits: {e}")
        return []


def _generate_summary(
    branch: str,
    dirty_files: List[str],
    last_commits: List[Dict[str, str]]
) -> str:
    """Generate human-readable summary."""
    parts = []

    # Branch info
    parts.append(f"On {branch}")

    # Dirty files
    if dirty_files:
        count = len(dirty_files)
        if count == 1:
            parts.append(f"1 uncommitted change")
        else:
            parts.append(f"{count} uncommitted changes")
    else:
        parts.append("working tree clean")

    # Last commit
    if last_commits:
        last_commit = last_commits[0]
        parts.append(f"last commit {last_commit['time']}")

    return ", ".join(parts)


async def context_recall_turn(
    turn_offset: int = 1,
    include_claims: bool = True,
    include_response: bool = True,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Recall details about a previous turn for follow-up questions.

    Use this when the user asks about previous responses, like:
    - "why did you choose those options?"
    - "tell me more about the first one"
    - "what was the price again?"

    MCP tool signature:
    {
        "name": "context.recall_turn",
        "description": "Recall details about a previous turn to answer follow-up questions",
        "inputSchema": {
            "type": "object",
            "properties": {
                "turn_offset": {"type": "integer", "default": 1, "description": "How many turns back (1=previous, 2=two back)"},
                "include_claims": {"type": "boolean", "default": true, "description": "Include product/claim details"},
                "include_response": {"type": "boolean", "default": true, "description": "Include the response that was given"},
                "session_id": {"type": "string", "description": "Session ID to look up turns for"}
            },
            "required": []
        }
    }

    Returns:
        {
            "turn_id": "turn_000559",
            "user_query": "cheapest laptop with nvidia gpu",
            "summary": "Found 3 laptops with NVIDIA GPUs...",
            "claims": [...],  # Products/findings from that turn
            "response_preview": "...",  # What was shown to user
            "selection_context": {
                "criteria_from_query": ["cheapest", "nvidia gpu"],
                "preferences_at_time": {"budget": "online search"},
                "topic": "laptop shopping"
            }
        }
    """
    import json
    import re
    from pathlib import Path

    try:
        # Find the turns directory
        turns_dir = Path("/home/henry/pythonprojects/pandaai/panda_system_docs/turns")

        if not turns_dir.exists():
            return {
                "error": "Turns directory not found",
                "turn_id": None,
                "summary": "Could not access previous turn data"
            }

        # Get list of turns, sorted by turn number
        turn_dirs = sorted(
            [d for d in turns_dir.iterdir() if d.is_dir() and d.name.startswith("turn_")],
            key=lambda x: int(x.name.split("_")[1])
        )

        if not turn_dirs:
            return {
                "error": "No previous turns found",
                "turn_id": None,
                "summary": "No conversation history available"
            }

        # Get the target turn (offset from end)
        target_idx = len(turn_dirs) - turn_offset
        if target_idx < 0:
            return {
                "error": f"Not enough turns in history (requested {turn_offset} back, only {len(turn_dirs)} available)",
                "turn_id": None,
                "summary": "Requested turn not available"
            }

        target_turn_dir = turn_dirs[target_idx]
        turn_id = target_turn_dir.name

        logger.info(f"[context.recall_turn] Recalling {turn_id} (offset={turn_offset})")

        result = {
            "turn_id": turn_id,
            "user_query": None,
            "summary": None,
            "key_findings": [],
            "claims": [],
            "response_preview": None,
            "selection_context": {}
        }

        # Read user_query.md
        user_query_path = target_turn_dir / "user_query.md"
        if user_query_path.exists():
            content = user_query_path.read_text().strip()
            # Extract query text after "## Query" section
            if "## Query" in content:
                query_section = content.split("## Query")[-1].strip()
                # Remove "Question:" prefix if present
                if query_section.startswith("Question:"):
                    query_section = query_section[9:].strip()
                result["user_query"] = query_section[:200]
            else:
                # Fallback: skip markdown headers and metadata lines
                lines = []
                for line in content.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("**"):
                        lines.append(line)
                result["user_query"] = " ".join(lines)[:200]

        # Read turn_summary.json (has the LLM-generated summary)
        summary_path = target_turn_dir / "turn_summary.json"
        if summary_path.exists():
            try:
                summary_data = json.loads(summary_path.read_text())
                result["summary"] = summary_data.get("short_summary")
                result["key_findings"] = summary_data.get("key_findings", [])[:5]
                result["selection_context"]["topic"] = summary_data.get("topic")
                result["selection_context"]["preferences_learned"] = summary_data.get("preferences_learned", {})
            except json.JSONDecodeError:
                pass

        # Read capsule.json or capsule.md for claims
        if include_claims:
            capsule_json_path = target_turn_dir / "capsule.json"
            capsule_md_path = target_turn_dir / "capsule.md"

            if capsule_json_path.exists():
                try:
                    capsule_data = json.loads(capsule_json_path.read_text())
                    claims = capsule_data.get("claims", [])
                    # Format claims for easy reading
                    for claim in claims[:10]:  # Max 10 claims
                        formatted = {
                            "statement": claim.get("statement") or claim.get("claim_text") or claim.get("claim"),
                            "source": claim.get("source_url") or claim.get("url"),
                            "confidence": claim.get("confidence", 0.0)
                        }
                        # Extract price if present
                        if claim.get("price"):
                            formatted["price"] = claim["price"]
                        result["claims"].append(formatted)
                except json.JSONDecodeError:
                    pass

            elif capsule_md_path.exists():
                # Parse markdown capsule (fallback)
                content = capsule_md_path.read_text()
                # Extract claim lines (usually bullet points)
                claim_lines = re.findall(r'[-*]\s+\*\*(.+?)\*\*.*?@\s*\$?([\d,.]+)', content)
                for name, price in claim_lines[:10]:
                    result["claims"].append({
                        "statement": name.strip(),
                        "price": price.strip()
                    })

        # Read answer.md or response for what was shown
        if include_response:
            answer_path = target_turn_dir / "answer.md"
            response_path = target_turn_dir / "response.md"

            content = None
            if answer_path.exists():
                content = answer_path.read_text()
            elif response_path.exists():
                content = response_path.read_text()

            if content:
                # Try to parse as JSON first
                try:
                    answer_data = json.loads(content)
                    result["response_preview"] = answer_data.get("answer", content)[:500]
                except (json.JSONDecodeError, TypeError):
                    result["response_preview"] = content[:500]

        # Read context.md for preferences at time of query
        context_path = target_turn_dir / "context.md"
        if context_path.exists():
            content = context_path.read_text()
            # Extract preferences line
            prefs_match = re.search(r'User preferences:\s*(.+?)(?:\n|;|$)', content)
            if prefs_match:
                result["selection_context"]["preferences_at_time"] = prefs_match.group(1).strip()

        # Extract selection criteria from the original query
        if result["user_query"]:
            query_lower = result["user_query"].lower()
            criteria = []
            if "cheap" in query_lower:
                criteria.append("lowest price")
            if "best" in query_lower:
                criteria.append("best value/quality")
            if any(word in query_lower for word in ["nvidia", "rtx", "geforce"]):
                criteria.append("NVIDIA GPU required")
            if any(word in query_lower for word in ["amd", "radeon"]):
                criteria.append("AMD GPU required")
            if "gaming" in query_lower:
                criteria.append("gaming capable")
            result["selection_context"]["criteria_from_query"] = criteria

        logger.info(
            f"[context.recall_turn] Recalled {turn_id}: "
            f"query='{result['user_query'][:50] if result['user_query'] else 'N/A'}', "
            f"claims={len(result['claims'])}"
        )

        return result

    except Exception as e:
        logger.error(f"[context.recall_turn] Error: {e}", exc_info=True)
        return {
            "error": str(e),
            "turn_id": None,
            "summary": f"Error recalling turn: {str(e)}"
        }


# For orchestrator app.py registration
__all__ = ["context_snapshot_repo", "context_recall_turn"]
