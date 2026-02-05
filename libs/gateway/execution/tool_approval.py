"""
Tool Approval Manager - Pre-execution approval for high-stakes tools.

Implements Factor 6/7 (Pause/Resume + Human Contact) from 12-Factor Agents:
- Proactive approval before executing sensitive tools
- Configurable tool list with reasons and timeouts
- Async Future pattern (same as InterventionManager) for pause/resume
- UI integration via API endpoints

This generalizes the CAPTCHA intervention pattern to support pre-execution
approval for any configurable tool.

Usage:
    manager = get_tool_approval_manager()

    # Check if tool requires approval
    if manager.requires_approval("memory.save"):
        request = await manager.request_approval(
            tool_name="memory.save",
            tool_args={"key": "preference", "value": "..."},
            session_id="abc123"
        )
        approved = await request.wait_for_approval(timeout=60)
        if not approved:
            return {"status": "denied", "error": "User denied execution"}

    # Proceed with tool execution
    result = await execute_tool(...)
"""

from __future__ import annotations
import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class ApprovalStatus(Enum):
    """Status of an approval request."""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"
    AUTO_APPROVED = "auto_approved"


# Default tools requiring approval before execution
# Each entry has: reason (why approval needed), timeout (seconds to wait)
# This is configurable via environment variable APPROVAL_REQUIRED_TOOLS
DEFAULT_APPROVAL_TOOLS: Dict[str, Dict[str, Any]] = {
    # Memory operations (persistent state changes)
    "memory.save": {
        "reason": "Modifies persistent memory",
        "timeout": 60,
        "category": "persistence"
    },
    # File operations
    "file.write": {
        "reason": "Creates or modifies files",
        "timeout": 60,
        "category": "filesystem"
    },
    "file.delete": {
        "reason": "Deletes files permanently",
        "timeout": 120,
        "category": "filesystem"
    },
    # Git operations
    "git.commit": {
        "reason": "Commits code changes to repository",
        "timeout": 120,
        "category": "vcs"
    },
    "git.push": {
        "reason": "Pushes changes to remote repository",
        "timeout": 120,
        "category": "vcs"
    },
}


def load_approval_tools_config() -> Dict[str, Dict[str, Any]]:
    """
    Load approval tools configuration from environment or use defaults.

    Environment variable APPROVAL_REQUIRED_TOOLS can override:
    - Set to "none" to disable all approval requirements
    - Set to "default" to use DEFAULT_APPROVAL_TOOLS
    - Set to comma-separated list (e.g., "memory.save,git.push") to customize
    """
    config_str = os.getenv("APPROVAL_REQUIRED_TOOLS", "default")

    if config_str.lower() == "none":
        return {}
    elif config_str.lower() == "default":
        return DEFAULT_APPROVAL_TOOLS.copy()
    else:
        # Parse comma-separated list, use default settings for each
        tools = [t.strip() for t in config_str.split(",") if t.strip()]
        result = {}
        for tool in tools:
            if tool in DEFAULT_APPROVAL_TOOLS:
                result[tool] = DEFAULT_APPROVAL_TOOLS[tool]
            else:
                # Unknown tool - use generic settings
                result[tool] = {
                    "reason": f"Tool '{tool}' requires approval",
                    "timeout": 60,
                    "category": "custom"
                }
        return result


# Module-level configuration (loaded once at import)
APPROVAL_REQUIRED_TOOLS = load_approval_tools_config()

# Feature flag to enable/disable approval system entirely
APPROVAL_SYSTEM_ENABLED = os.getenv("TOOL_APPROVAL_ENABLED", "true").lower() == "true"


@dataclass
class ToolApprovalRequest:
    """
    A single approval request for tool execution.

    Uses asyncio.Future pattern (same as Intervention) to block execution
    until user approves, denies, or timeout occurs.
    """
    request_id: str
    tool_name: str
    tool_args: Dict[str, Any]
    reason: str
    session_id: str
    category: str = "general"
    created_at: float = field(default_factory=time.time)
    status: ApprovalStatus = ApprovalStatus.PENDING
    resolved_at: Optional[float] = None
    deny_reason: str = ""

    # Future for async waiting
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    async def wait_for_approval(self, timeout: float = 60) -> bool:
        """
        Block until user approves/denies or timeout.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if approved, False if denied/timeout
        """
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return self.status == ApprovalStatus.APPROVED
        except asyncio.TimeoutError:
            logger.warning(
                f"[ToolApproval] Timeout waiting for approval: {self.request_id} "
                f"(tool={self.tool_name}, waited {timeout}s)"
            )
            self.status = ApprovalStatus.TIMEOUT
            self.resolved_at = time.time()
            return False

    def approve(self):
        """Mark request as approved and signal waiting task."""
        if self.status != ApprovalStatus.PENDING:
            logger.warning(f"[ToolApproval] Already resolved: {self.request_id}")
            return

        self.status = ApprovalStatus.APPROVED
        self.resolved_at = time.time()
        self._event.set()

        logger.info(
            f"[ToolApproval] Approved: {self.request_id} (tool={self.tool_name})"
        )

    def deny(self, reason: str = ""):
        """Mark request as denied and signal waiting task."""
        if self.status != ApprovalStatus.PENDING:
            logger.warning(f"[ToolApproval] Already resolved: {self.request_id}")
            return

        self.status = ApprovalStatus.DENIED
        self.deny_reason = reason
        self.resolved_at = time.time()
        self._event.set()

        logger.info(
            f"[ToolApproval] Denied: {self.request_id} (tool={self.tool_name}, reason={reason})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "tool_args": self._sanitize_args(self.tool_args),
            "reason": self.reason,
            "session_id": self.session_id,
            "category": self.category,
            "status": self.status.value,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "resolved_at": datetime.fromtimestamp(self.resolved_at).isoformat() if self.resolved_at else None,
            "deny_reason": self.deny_reason,
        }

    def _sanitize_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize tool args for display (truncate large values, hide secrets)."""
        sanitized = {}
        for key, value in args.items():
            # Hide potential secrets
            if any(s in key.lower() for s in ["password", "secret", "key", "token"]):
                sanitized[key] = "***hidden***"
            elif isinstance(value, str) and len(value) > 200:
                sanitized[key] = value[:200] + "..."
            elif isinstance(value, (list, dict)) and len(str(value)) > 500:
                sanitized[key] = f"<{type(value).__name__} with {len(value)} items>"
            else:
                sanitized[key] = value
        return sanitized


class ToolApprovalManager:
    """
    Manages pre-execution approval for high-stakes tools.

    This extends the intervention pattern to support proactive approval
    before tool execution, rather than reactive intervention after blocks.

    Responsibilities:
    - Check if a tool requires approval
    - Create approval requests
    - Track pending approvals
    - Resolve approvals based on user actions
    - Emit events for UI notification
    """

    def __init__(self, event_emitter: Optional[Any] = None):
        """
        Initialize approval manager.

        Args:
            event_emitter: Optional event emitter for broadcasting to UI
        """
        self.event_emitter = event_emitter
        self._pending: Dict[str, ToolApprovalRequest] = {}
        self._config = APPROVAL_REQUIRED_TOOLS

    def requires_approval(self, tool_name: str) -> bool:
        """Check if a tool requires pre-execution approval."""
        if not APPROVAL_SYSTEM_ENABLED:
            return False
        return tool_name in self._config

    def get_tool_config(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a tool requiring approval."""
        return self._config.get(tool_name)

    async def request_approval(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        session_id: str,
    ) -> ToolApprovalRequest:
        """
        Request approval before executing a tool.

        Creates approval request and notifies UI. The caller should then
        await request.wait_for_approval() to block until resolved.

        Args:
            tool_name: Name of tool requiring approval
            tool_args: Arguments that will be passed to the tool
            session_id: Session identifier

        Returns:
            ToolApprovalRequest object (await .wait_for_approval())
        """
        config = self._config.get(tool_name, {})
        request = ToolApprovalRequest(
            request_id=str(uuid.uuid4()),
            tool_name=tool_name,
            tool_args=tool_args,
            reason=config.get("reason", f"Tool '{tool_name}' requires approval"),
            session_id=session_id,
            category=config.get("category", "general"),
        )

        self._pending[request.request_id] = request

        # Emit event for UI notification
        await self._emit_approval_needed(request)

        logger.info(
            f"[ToolApprovalManager] Requested approval: {request.request_id} "
            f"(tool={tool_name}, session={session_id})"
        )

        return request

    async def resolve(
        self,
        request_id: str,
        approved: bool,
        reason: str = ""
    ) -> bool:
        """
        Resolve an approval request.

        Args:
            request_id: Approval request ID
            approved: True to approve, False to deny
            reason: Optional reason (for deny)

        Returns:
            True if resolved successfully, False if not found
        """
        request = self._pending.get(request_id)
        if not request:
            logger.warning(f"[ToolApprovalManager] Unknown request: {request_id}")
            return False

        if approved:
            request.approve()
        else:
            request.deny(reason)

        # Remove from pending after brief delay (allow status to be read)
        asyncio.create_task(self._cleanup_after_delay(request_id, delay=5.0))

        # Emit resolution event
        await self._emit_approval_resolved(request)

        return True

    async def _cleanup_after_delay(self, request_id: str, delay: float):
        """Clean up resolved request after delay."""
        await asyncio.sleep(delay)
        if request_id in self._pending:
            del self._pending[request_id]

    def get_pending(self, session_id: Optional[str] = None) -> List[ToolApprovalRequest]:
        """
        Get all pending approval requests.

        Args:
            session_id: Optional filter by session

        Returns:
            List of pending ToolApprovalRequest objects
        """
        requests = [
            r for r in self._pending.values()
            if r.status == ApprovalStatus.PENDING
        ]
        if session_id:
            requests = [r for r in requests if r.session_id == session_id]
        return requests

    def get_request(self, request_id: str) -> Optional[ToolApprovalRequest]:
        """Get a specific approval request by ID."""
        return self._pending.get(request_id)

    def clear_expired(self, max_age_seconds: int = 300):
        """Clear approval requests older than max_age_seconds."""
        now = time.time()
        to_remove = []
        for request_id, request in self._pending.items():
            age = now - request.created_at
            if age > max_age_seconds and request.status != ApprovalStatus.PENDING:
                to_remove.append(request_id)

        for request_id in to_remove:
            del self._pending[request_id]

        if to_remove:
            logger.info(f"[ToolApprovalManager] Cleared {len(to_remove)} expired requests")

    async def _emit_approval_needed(self, request: ToolApprovalRequest):
        """Emit event to notify UI that approval is needed."""
        if not self.event_emitter:
            return

        try:
            event_data = {
                "type": "tool_approval_needed",
                "request_id": request.request_id,
                "tool_name": request.tool_name,
                "tool_args": request._sanitize_args(request.tool_args),
                "reason": request.reason,
                "session_id": request.session_id,
                "category": request.category,
                "created_at": datetime.fromtimestamp(request.created_at).isoformat(),
            }

            if hasattr(self.event_emitter, 'emit'):
                await self.event_emitter.emit("tool_approval_needed", event_data)
            elif hasattr(self.event_emitter, 'emit_event'):
                await self.event_emitter.emit_event("tool_approval_needed", event_data)
        except Exception as e:
            logger.warning(f"[ToolApprovalManager] Failed to emit approval needed event: {e}")

    async def _emit_approval_resolved(self, request: ToolApprovalRequest):
        """Emit event to notify UI that approval was resolved."""
        if not self.event_emitter:
            return

        try:
            event_data = {
                "type": "tool_approval_resolved",
                "request_id": request.request_id,
                "tool_name": request.tool_name,
                "status": request.status.value,
                "deny_reason": request.deny_reason,
            }

            if hasattr(self.event_emitter, 'emit'):
                await self.event_emitter.emit("tool_approval_resolved", event_data)
            elif hasattr(self.event_emitter, 'emit_event'):
                await self.event_emitter.emit_event("tool_approval_resolved", event_data)
        except Exception as e:
            logger.warning(f"[ToolApprovalManager] Failed to emit resolution event: {e}")


# Global singleton instance
_tool_approval_manager: Optional[ToolApprovalManager] = None


def get_tool_approval_manager() -> ToolApprovalManager:
    """Get or create the global ToolApprovalManager instance."""
    global _tool_approval_manager
    if _tool_approval_manager is None:
        _tool_approval_manager = ToolApprovalManager()
        logger.info(
            f"[ToolApproval] Initialized manager (enabled={APPROVAL_SYSTEM_ENABLED}, "
            f"tools={list(APPROVAL_REQUIRED_TOOLS.keys())})"
        )
    return _tool_approval_manager


def set_tool_approval_manager(manager: ToolApprovalManager):
    """Set the global ToolApprovalManager instance (for testing/customization)."""
    global _tool_approval_manager
    _tool_approval_manager = manager
