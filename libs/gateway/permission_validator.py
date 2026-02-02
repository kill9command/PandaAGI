"""
Combined mode enforcement and repository-scoped permissions.

Validates tool operations against:
1. Mode gates (chat vs code/continue)
2. Repository scope (saved repo vs external)
3. Prompts for user approval when needed

Configuration (env vars):
- SAVED_REPO: Primary repo path (operations here always allowed in code mode)
- ENFORCE_MODE_GATES: Enable enforcement (default: 1)
- EXTERNAL_REPO_TIMEOUT: Timeout for approval prompts (default: 180)
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from pathlib import Path
import os
import asyncio
import logging
import uuid
import time
import json

logger = logging.getLogger(__name__)


class PermissionDecision(str, Enum):
    """Result of permission validation."""
    ALLOWED = "allowed"           # Proceed immediately
    DENIED = "denied"             # Reject - mode doesn't allow
    NEEDS_APPROVAL = "needs_approval"  # Pause for user approval


@dataclass
class ValidationResult:
    """Result of validating a tool operation."""
    decision: PermissionDecision
    tool: str
    reason: str
    approval_request_id: Optional[str] = None
    approval_details: Optional[Dict[str, Any]] = None


@dataclass
class PermissionRequest:
    """A pending permission request awaiting user approval."""
    request_id: str
    tool: str
    target_path: str
    reason: str
    session_id: str
    operation_details: Dict[str, Any]
    created_at: float = field(default_factory=time.time)

    # Resolution state
    resolved: bool = False
    approved: bool = False
    resolved_at: Optional[float] = None
    rejection_reason: Optional[str] = None

    # Async event for waiting - created lazily
    _resolution_event: Optional[asyncio.Event] = field(default=None, repr=False)

    def _ensure_event(self) -> asyncio.Event:
        """Ensure the resolution event exists (create if needed)."""
        if self._resolution_event is None:
            self._resolution_event = asyncio.Event()
        return self._resolution_event

    async def wait_for_resolution(self, timeout: float = 180) -> bool:
        """Wait for user to approve/deny. Returns True if approved."""
        event = self._ensure_event()
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return self.approved
        except asyncio.TimeoutError:
            self.mark_resolved(approved=False, reason="timeout")
            return False

    def mark_resolved(self, approved: bool, reason: Optional[str] = None):
        """Mark as resolved by user."""
        self.resolved = True
        self.approved = approved
        self.resolved_at = time.time()
        self.rejection_reason = reason

        # Signal waiting coroutines
        event = self._ensure_event()
        event.set()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API/UI."""
        return {
            "request_id": self.request_id,
            "tool": self.tool,
            "target_path": self.target_path,
            "reason": self.reason,
            "session_id": self.session_id,
            "operation_details": self.operation_details,
            "created_at": self.created_at,
            "resolved": self.resolved,
            "approved": self.approved if self.resolved else None,
            "rejection_reason": self.rejection_reason
        }


class PermissionValidator:
    """
    Validates tool operations against mode and repository scope.

    Configuration (env vars):
    - SAVED_REPO: Primary repo path (operations here always allowed in code mode)
    - ENFORCE_MODE_GATES: Enable enforcement (default: 1)
    - EXTERNAL_REPO_TIMEOUT: Timeout for approval prompts (default: 180)
    """

    # Tools that require code/continue mode (write operations)
    CODE_MODE_TOOLS = {
        "file.write", "file.create", "file.edit", "file.delete",
        "code.apply_patch",
        "git.commit", "git.commit_safe", "git.add",
        "git.push", "git.pull", "git.branch", "git.create_pr", "git.reset",
        "test.run", "docs.write_spreadsheet",
        "bash.execute", "bash.kill"
    }

    # Tools that are always allowed (read-only or safe)
    ALWAYS_ALLOWED = {
        "doc.search", "code.search", "fs.read", "repo.describe",
        "repo.scope_discover",  # Code exploration - read-only repo structure discovery
        "memory.create", "memory.query", "memory.update",
        "wiki.search", "ocr.read", "bom.build",
        "internet.research",
        "commerce.search_offers", "commerce.search_with_recommendations",
        "commerce.quick_search", "purchasing.lookup",
        "file.read", "file.glob", "file.grep",
        "git.status", "git.diff", "git.log",
        "bash.get_output", "bash.list",  # Read-only bash operations
        "skill.generator", "skill.validate", "skill.delete", "skill.list"  # Self-extension
    }

    # Persistence file for cross-process communication
    QUEUE_FILE = "panda_system_docs/shared_state/permission_queue.json"

    def __init__(self):
        self.saved_repo = os.environ.get("SAVED_REPO", "")
        self.enforce = os.environ.get("ENFORCE_MODE_GATES", "1") == "1"
        self.approval_timeout = float(os.environ.get("EXTERNAL_REPO_TIMEOUT", "180"))

        # Pending approval requests (in-memory)
        self._pending: Dict[str, PermissionRequest] = {}

        # Load any persisted pending requests
        self._load_persisted_requests()

        logger.info(
            f"[PermissionValidator] Initialized: saved_repo={self.saved_repo!r}, "
            f"enforce={self.enforce}, timeout={self.approval_timeout}s"
        )

    def _load_persisted_requests(self):
        """Load pending requests from disk (for cross-process recovery)."""
        try:
            if os.path.exists(self.QUEUE_FILE):
                with open(self.QUEUE_FILE, 'r') as f:
                    data = json.load(f)
                    for item in data:
                        if not item.get("resolved", False):
                            req = PermissionRequest(
                                request_id=item["request_id"],
                                tool=item["tool"],
                                target_path=item["target_path"],
                                reason=item["reason"],
                                session_id=item["session_id"],
                                operation_details=item["operation_details"],
                                created_at=item.get("created_at", time.time())
                            )
                            self._pending[req.request_id] = req
        except Exception as e:
            logger.warning(f"[PermissionValidator] Failed to load persisted requests: {e}")

    def _persist_pending(self):
        """Persist pending requests for cross-process access."""
        try:
            os.makedirs(os.path.dirname(self.QUEUE_FILE), exist_ok=True)
            pending_list = [
                r.to_dict() for r in self._pending.values()
                if not r.resolved
            ]
            with open(self.QUEUE_FILE, 'w') as f:
                json.dump(pending_list, f, indent=2)
        except Exception as e:
            logger.error(f"[PermissionValidator] Failed to persist: {e}")

    def _resolve_path(self, path: str, repo: Optional[str] = None) -> Path:
        """Resolve path to absolute, accounting for repo prefix."""
        if repo:
            full_path = Path(repo) / path
        else:
            full_path = Path(path)
        return full_path.resolve()

    def _is_under_saved_repo(self, path: Path) -> bool:
        """Check if path is under the saved repository."""
        if not self.saved_repo:
            return True  # No saved repo configured = allow all

        try:
            saved_resolved = Path(self.saved_repo).resolve()
            return path.is_relative_to(saved_resolved)
        except (ValueError, AttributeError):
            # Python <3.9 fallback
            return str(path).startswith(str(Path(self.saved_repo).resolve()))

    def _extract_paths_from_args(
        self,
        tool: str,
        args: Dict[str, Any]
    ) -> List[Path]:
        """Extract target paths from tool arguments."""
        paths = []
        repo = args.get("repo")

        # File tools
        if tool in {"file.read", "file.write", "file.create", "file.edit", "file.delete"}:
            file_path = args.get("file_path") or args.get("path")
            if file_path:
                paths.append(self._resolve_path(file_path, repo))

        # Glob/grep - check the search root
        elif tool in {"file.glob", "file.grep"}:
            if repo:
                paths.append(Path(repo).resolve())
            else:
                # If no repo, check the pattern's base directory
                pattern = args.get("pattern", "")
                if pattern and "/" in pattern:
                    base = pattern.split("*")[0].rsplit("/", 1)[0]
                    if base:
                        paths.append(Path(base).resolve())

        # Git tools - repo is required
        elif tool.startswith("git."):
            if repo:
                paths.append(Path(repo).resolve())

        # Bash - check cwd
        elif tool in {"bash.execute", "bash.kill"}:
            cwd = args.get("cwd")
            if cwd:
                paths.append(Path(cwd).resolve())

        return paths

    def validate(
        self,
        tool: str,
        args: Dict[str, Any],
        mode: str,
        session_id: str
    ) -> ValidationResult:
        """
        Validate a tool operation.

        Args:
            tool: Tool name (e.g., "file.write")
            args: Tool arguments
            mode: Current mode ("chat" or "code"/"continue")
            session_id: Session identifier

        Returns:
            ValidationResult with decision and details
        """
        # Skip if enforcement disabled
        if not self.enforce:
            return ValidationResult(
                decision=PermissionDecision.ALLOWED,
                tool=tool,
                reason="enforcement_disabled"
            )

        # Always-allowed tools pass immediately
        if tool in self.ALWAYS_ALLOWED:
            return ValidationResult(
                decision=PermissionDecision.ALLOWED,
                tool=tool,
                reason="read_only_tool"
            )

        # Unknown tools (not in either list) - allow in code mode, deny in chat
        is_code_mode = mode in ("code", "continue")

        # Check mode gate for code-mode tools
        if tool in self.CODE_MODE_TOOLS:
            if not is_code_mode:
                return ValidationResult(
                    decision=PermissionDecision.DENIED,
                    tool=tool,
                    reason=f"Tool '{tool}' requires code mode (current: {mode})"
                )

            # In code mode, check repo scope
            paths = self._extract_paths_from_args(tool, args)

            for path in paths:
                if not self._is_under_saved_repo(path):
                    # External path - needs approval
                    request_id = str(uuid.uuid4())
                    request = PermissionRequest(
                        request_id=request_id,
                        tool=tool,
                        target_path=str(path),
                        reason=f"Operation targets path outside saved repo: {path}",
                        session_id=session_id,
                        operation_details={
                            "tool": tool,
                            "args": {k: str(v)[:200] for k, v in args.items()},  # Truncate large values
                            "saved_repo": self.saved_repo
                        }
                    )
                    self._pending[request_id] = request
                    self._persist_pending()

                    logger.info(
                        f"[PermissionValidator] Approval needed: {tool} -> {path} "
                        f"(saved_repo={self.saved_repo}, request_id={request_id})"
                    )

                    return ValidationResult(
                        decision=PermissionDecision.NEEDS_APPROVAL,
                        tool=tool,
                        reason=f"Path '{path}' is outside saved repo '{self.saved_repo}'",
                        approval_request_id=request_id,
                        approval_details=request.to_dict()
                    )

        # Unknown tool in code mode - allow (backwards compatible)
        if is_code_mode and tool not in self.ALWAYS_ALLOWED and tool not in self.CODE_MODE_TOOLS:
            logger.debug(f"[PermissionValidator] Unknown tool '{tool}' allowed in code mode")
            return ValidationResult(
                decision=PermissionDecision.ALLOWED,
                tool=tool,
                reason="unknown_tool_code_mode"
            )

        # Unknown tool in chat mode - deny (safety default)
        if not is_code_mode and tool not in self.ALWAYS_ALLOWED:
            return ValidationResult(
                decision=PermissionDecision.DENIED,
                tool=tool,
                reason=f"Unknown tool '{tool}' not allowed in chat mode"
            )

        # All checks passed
        return ValidationResult(
            decision=PermissionDecision.ALLOWED,
            tool=tool,
            reason="all_checks_passed"
        )

    async def wait_for_approval(self, request_id: str) -> bool:
        """Wait for user to approve a pending request."""
        request = self._pending.get(request_id)
        if not request:
            logger.warning(f"[PermissionValidator] Request not found: {request_id}")
            return False

        logger.info(f"[PermissionValidator] Waiting for approval: {request_id} (timeout={self.approval_timeout}s)")
        approved = await request.wait_for_resolution(self.approval_timeout)

        # Clean up
        if request_id in self._pending:
            del self._pending[request_id]
            self._persist_pending()

        logger.info(f"[PermissionValidator] Approval result for {request_id}: {approved}")
        return approved

    def resolve_request(
        self,
        request_id: str,
        approved: bool,
        reason: Optional[str] = None
    ) -> bool:
        """Resolve a pending approval request."""
        request = self._pending.get(request_id)
        if not request:
            logger.warning(f"[PermissionValidator] Cannot resolve - not found: {request_id}")
            return False

        request.mark_resolved(approved, reason)
        self._persist_pending()

        logger.info(
            f"[PermissionValidator] Request {request_id} resolved: "
            f"approved={approved}, reason={reason}"
        )
        return True

    def get_pending_requests(
        self,
        session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all pending approval requests."""
        requests = [
            r.to_dict() for r in self._pending.values()
            if not r.resolved
        ]
        if session_id:
            requests = [r for r in requests if r["session_id"] == session_id]
        return requests

    def cancel_request(self, request_id: str) -> bool:
        """Cancel a pending request (e.g., on session end)."""
        if request_id in self._pending:
            request = self._pending[request_id]
            request.mark_resolved(approved=False, reason="cancelled")
            del self._pending[request_id]
            self._persist_pending()
            return True
        return False


# Global instance
_validator: Optional[PermissionValidator] = None


def get_validator() -> PermissionValidator:
    """Get or create the global validator instance."""
    global _validator
    if _validator is None:
        _validator = PermissionValidator()
    return _validator


def reset_validator():
    """Reset the global validator (for testing)."""
    global _validator
    _validator = None
