"""
Turn Directory Manager for v4.0 Document-Driven Architecture

Creates and manages turn directories with manifest tracking.
Each turn gets a directory with all documents produced during that turn.

Author: v4.0 Migration
Date: 2025-11-16
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

# Base directory for all turns (legacy default, now uses per-user paths via base_dir parameter)
TURNS_BASE_DIR = Path("panda_system_docs/obsidian_memory/Users/default/turns")


class TurnDirectory:
    """
    Represents a single turn's directory structure.

    Each turn has:
    - Unique directory: turns/turn_{n}/
    - Manifest tracking all docs created
    - Input/output documents
    """

    def __init__(
        self,
        turn_id: str,
        session_id: str,
        mode: str,
        trace_id: str,
        base_dir: Path = None
    ):
        self.turn_id = turn_id
        self.session_id = session_id
        self.mode = mode
        self.trace_id = trace_id
        # Use provided base_dir or fall back to global default
        self._base_dir = base_dir or TURNS_BASE_DIR
        self.path = self._base_dir / turn_id

    def create(self) -> Path:
        """Create turn directory structure"""
        self.path.mkdir(parents=True, exist_ok=True)
        logger.info(f"[TurnDir] Created directory: {self.path}")
        return self.path

    def doc_path(self, doc_name: str, path_type: str = "turn") -> Path:
        """
        Resolve document path based on type.

        Args:
            doc_name: Document name or path
            path_type: "turn" | "repo" | "absolute" | "session"

        Returns:
            Resolved path

        Path Types:
        - "turn": Local to this turn (turns/turn_000123/doc_name)
        - "repo": Relative to repo root (e.g., panda_system_docs/...)
        - "absolute": Absolute filesystem path
        - "session": Session-specific (shared_state/session_contexts/{session_id}/...)
        """
        if path_type == "turn":
            # Turn-local path
            return self.path / doc_name

        elif path_type == "repo":
            # Repo-relative path (assume already correct)
            return Path(doc_name)

        elif path_type == "absolute":
            # Absolute path
            return Path(doc_name)

        elif path_type == "session":
            # Session-specific path with {session_id} placeholder
            resolved = doc_name.replace("{session_id}", self.session_id)
            return Path(resolved)

        else:
            raise ValueError(f"Unknown path_type: {path_type}")

    def exists(self) -> bool:
        """Check if turn directory exists"""
        return self.path.exists()

    def list_docs(self) -> list[str]:
        """List all documents in turn directory"""
        if not self.exists():
            return []
        return [f.name for f in self.path.iterdir() if f.is_file()]


def create_turn_directory(
    trace_id: str,
    session_id: str,
    mode: str = "chat",
    turn_number: Optional[int] = None
) -> TurnDirectory:
    """
    Create a new turn directory with unique ID.

    Args:
        trace_id: Unique trace ID for this request
        session_id: User session ID
        mode: "chat" or "code"
        turn_number: Optional explicit turn number (auto-increments if None)

    Returns:
        TurnDirectory instance
    """
    # Generate turn ID
    if turn_number is not None:
        turn_id = f"turn_{turn_number:06d}"
    else:
        # Auto-increment: find highest existing turn number for this session
        turn_id = _generate_turn_id(session_id)

    turn_dir = TurnDirectory(turn_id, session_id, mode, trace_id)
    turn_dir.create()

    return turn_dir


def _generate_turn_id(session_id: str) -> str:
    """
    Generate next turn ID by finding highest existing turn number.

    Falls back to trace-based ID if no existing turns found.
    """
    TURNS_BASE_DIR.mkdir(parents=True, exist_ok=True)

    # Find all existing turns
    existing_turns = [
        d.name for d in TURNS_BASE_DIR.iterdir()
        if d.is_dir() and d.name.startswith("turn_")
    ]

    if not existing_turns:
        # First turn ever
        return "turn_000001"

    # Extract turn numbers
    turn_numbers = []
    for turn in existing_turns:
        try:
            num = int(turn.split("_")[1])
            turn_numbers.append(num)
        except (IndexError, ValueError):
            continue

    if not turn_numbers:
        return "turn_000001"

    # Next turn is max + 1
    next_num = max(turn_numbers) + 1
    return f"turn_{next_num:06d}"


def write_user_query(turn_dir: TurnDirectory, query: str, metadata: Optional[Dict] = None) -> Path:
    """
    Write user query to user_query.md

    Args:
        turn_dir: TurnDirectory instance
        query: User's query text
        metadata: Optional metadata (intent, domain, etc.)

    Returns:
        Path to written file
    """
    doc_path = turn_dir.doc_path("user_query.md")

    content = f"""# User Query

**Turn ID:** {turn_dir.turn_id}
**Session ID:** {turn_dir.session_id}
**Timestamp:** {datetime.now(timezone.utc).isoformat()}

## Query
{query}
"""

    if metadata:
        content += f"\n## Metadata\n"
        for key, value in metadata.items():
            content += f"- **{key}:** {value}\n"

    doc_path.write_text(content)
    logger.info(f"[TurnDir] Wrote user_query.md ({len(query)} chars)")

    return doc_path


def init_manifest(
    turn_id: str,
    session_id: str,
    mode: str,
    trace_id: str,
    user_query: Optional[str] = None
) -> Dict[str, Any]:
    """
    Initialize turn manifest.

    Manifest is the single source of truth for what happened in a turn.
    It tracks all documents created, referenced, cache hits, token usage, etc.

    Args:
        turn_id: Turn identifier
        session_id: Session identifier
        mode: "chat" or "code"
        trace_id: Trace identifier (for linking to v3 transcripts)
        user_query: Optional user query text

    Returns:
        Manifest dict
    """
    manifest = {
        "turn_id": turn_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "mode": mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "in_progress",

        # Documents
        "docs_created": [],
        "docs_referenced": [],

        # Cache tracking
        "cache_hits": {
            "response": False,
            "claims": False,
            "tool": {}
        },

        # Token usage by phase
        "token_usage": {
            "total": 0,
            "by_phase": {}
        },

        # Metadata
        "user_query_preview": user_query[:100] if user_query else None,
        "created_at": time.time(),
        "updated_at": time.time(),

        # Version
        "manifest_version": "1.0"
    }

    return manifest


def save_manifest(turn_dir: TurnDirectory, manifest: Dict[str, Any]) -> Path:
    """
    Save manifest to disk.

    Args:
        turn_dir: TurnDirectory instance
        manifest: Manifest dict

    Returns:
        Path to manifest.json
    """
    manifest["updated_at"] = time.time()

    manifest_path = turn_dir.doc_path("manifest.json")
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    logger.debug(f"[TurnDir] Saved manifest.json ({len(manifest['docs_created'])} docs)")

    return manifest_path


def load_manifest(turn_dir: TurnDirectory) -> Optional[Dict[str, Any]]:
    """
    Load manifest from disk.

    Args:
        turn_dir: TurnDirectory instance

    Returns:
        Manifest dict or None if not found
    """
    manifest_path = turn_dir.doc_path("manifest.json")
    if not manifest_path.exists():
        return None

    with open(manifest_path, 'r') as f:
        manifest = json.load(f)

    return manifest


def update_manifest(
    manifest: Dict[str, Any],
    doc_created: Optional[str] = None,
    doc_referenced: Optional[str] = None,
    tokens_used: Optional[Dict[str, int]] = None,
    cache_hit: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Update manifest with new information.

    Args:
        manifest: Existing manifest dict
        doc_created: Name of document created
        doc_referenced: Path to document referenced
        tokens_used: Dict of {phase: tokens}
        cache_hit: Dict of cache hit info {layer: hit_status}

    Returns:
        Updated manifest
    """
    if doc_created:
        if doc_created not in manifest["docs_created"]:
            manifest["docs_created"].append(doc_created)

    if doc_referenced:
        if doc_referenced not in manifest["docs_referenced"]:
            manifest["docs_referenced"].append(doc_referenced)

    if tokens_used:
        for phase, tokens in tokens_used.items():
            manifest["token_usage"]["by_phase"][phase] = tokens
        manifest["token_usage"]["total"] = sum(manifest["token_usage"]["by_phase"].values())

    if cache_hit:
        manifest["cache_hits"].update(cache_hit)

    manifest["updated_at"] = time.time()

    return manifest


def finalize_manifest(
    manifest: Dict[str, Any],
    final_status: str = "completed",
    error: Optional[str] = None
) -> Dict[str, Any]:
    """
    Finalize manifest at end of turn.

    Args:
        manifest: Existing manifest
        final_status: "completed" or "error"
        error: Optional error message

    Returns:
        Finalized manifest
    """
    manifest["status"] = final_status
    manifest["archived_at"] = datetime.now(timezone.utc).isoformat()

    if error:
        manifest["error"] = error

    manifest["updated_at"] = time.time()

    return manifest


# Convenience function for common workflow
def setup_turn(trace_id: str, session_id: str, mode: str, user_query: str) -> tuple[TurnDirectory, Dict[str, Any]]:
    """
    Complete turn setup: create directory, write query, init manifest.

    Args:
        trace_id: Trace ID
        session_id: Session ID
        mode: "chat" or "code"
        user_query: User's query

    Returns:
        (TurnDirectory, manifest dict)
    """
    # Create turn directory
    turn_dir = create_turn_directory(trace_id, session_id, mode)

    # Write user query
    write_user_query(turn_dir, user_query)

    # Initialize manifest
    manifest = init_manifest(turn_dir.turn_id, session_id, mode, trace_id, user_query)

    # Track user_query.md in manifest
    manifest = update_manifest(manifest, doc_created="user_query.md")

    # Save manifest
    save_manifest(turn_dir, manifest)

    logger.info(
        f"[TurnDir] Setup complete: {turn_dir.turn_id} "
        f"(session={session_id[:8]}, mode={mode})"
    )

    return turn_dir, manifest
