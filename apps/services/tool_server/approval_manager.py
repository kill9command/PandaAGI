"""
Approval manager for critical code operations and human interventions.

Handles:
- User approval requests for write operations in code mode
- CAPTCHA/auth intervention requests for research mode
"""
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ApprovalRequest:
    """Represents a pending approval request."""
    operation: str
    args: Dict[str, Any]
    message: str
    timestamp: float
    timeout: float = 60.0  # 60 second timeout


class ApprovalManager:
    """
    Manages approval requests for critical operations.

    In code mode, certain operations require user approval:
    - file.write (create new files)
    - file.edit (modify files, especially protected ones)
    - git.commit (commit changes)
    - git.push (push to remote)
    - bash.execute (shell commands)
    """

    def __init__(self):
        self.pending_requests: Dict[str, ApprovalRequest] = {}
        self.approval_responses: Dict[str, bool] = {}

    async def request_approval(
        self,
        operation: str,
        args: Dict[str, Any],
        message: str,
        timeout: float = 60.0,
        auto_approve: bool = False
    ) -> bool:
        """
        Request user approval for operation.

        Args:
            operation: Operation name (e.g., "file.edit")
            args: Operation arguments
            message: Human-readable approval message
            timeout: Seconds to wait for response
            auto_approve: If True, auto-approve (for testing/non-interactive)

        Returns:
            True if approved, False if denied or timeout
        """
        # Auto-approve mode (for testing or non-interactive sessions)
        if auto_approve:
            logger.info(f"[Approval] AUTO-APPROVED: {message}")
            return True

        # Generate unique request ID
        request_id = f"{operation}_{int(time.time() * 1000)}"

        # Create approval request
        request = ApprovalRequest(
            operation=operation,
            args=args,
            message=message,
            timestamp=time.time(),
            timeout=timeout
        )

        self.pending_requests[request_id] = request

        logger.info(f"[Approval] Requesting approval: {message}")

        # Wait for response (with timeout)
        try:
            approved = await self._wait_for_response(request_id, timeout)
            logger.info(f"[Approval] {'APPROVED' if approved else 'DENIED'}: {message}")
            return approved

        except asyncio.TimeoutError:
            logger.warning(f"[Approval] TIMEOUT after {timeout}s: {message}")
            return False

        finally:
            # Clean up
            self.pending_requests.pop(request_id, None)
            self.approval_responses.pop(request_id, None)

    async def _wait_for_response(self, request_id: str, timeout: float) -> bool:
        """
        Wait for approval response with timeout.

        Args:
            request_id: Request ID to wait for
            timeout: Max seconds to wait

        Returns:
            True if approved, False otherwise
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Check if response received
            if request_id in self.approval_responses:
                return self.approval_responses[request_id]

            # Sleep briefly to avoid busy-waiting
            await asyncio.sleep(0.1)

        # Timeout - default to deny
        return False

    def submit_response(self, request_id: str, approved: bool):
        """
        Submit approval response.

        Called by Gateway when user responds to approval request.

        Args:
            request_id: Request ID being responded to
            approved: True if approved, False if denied
        """
        if request_id not in self.pending_requests:
            logger.warning(f"[Approval] Response for unknown request: {request_id}")
            return

        self.approval_responses[request_id] = approved
        logger.info(f"[Approval] Response received: {request_id} = {approved}")

    def get_pending_requests(self) -> Dict[str, ApprovalRequest]:
        """Get all pending approval requests."""
        return self.pending_requests.copy()

    def cancel_request(self, request_id: str):
        """Cancel a pending approval request."""
        self.pending_requests.pop(request_id, None)
        self.approval_responses[request_id] = False

    # ========================================================================
    # Intervention Support (for human-assisted crawling)
    # ========================================================================

    def get_pending_interventions(self, session_id: Optional[str] = None) -> List[Dict]:
        """
        Get pending CAPTCHA/auth interventions.

        Args:
            session_id: Optional filter by session

        Returns:
            List of intervention dicts
        """
        from apps.services.tool_server.captcha_intervention import get_all_pending_interventions

        interventions = get_all_pending_interventions(session_id)
        return [i.to_dict() for i in interventions]

    async def resolve_intervention(
        self,
        intervention_id: str,
        resolved: bool,
        cookies: Optional[List[Dict]] = None
    ) -> bool:
        """
        Mark intervention as resolved by user.

        Args:
            intervention_id: Intervention ID
            resolved: Whether user successfully solved blocker
            cookies: Session cookies (if applicable)

        Returns:
            True if intervention was found and resolved, False if not found
        """
        from apps.services.tool_server.captcha_intervention import (
            get_pending_intervention,
            remove_pending_intervention
        )

        intervention = get_pending_intervention(intervention_id)
        if not intervention:
            logger.warning(f"[Intervention] Unknown intervention: {intervention_id}")
            return False

        # Mark as resolved
        intervention.mark_resolved(success=resolved, cookies=cookies)

        # Remove from pending registry
        remove_pending_intervention(intervention_id)

        logger.info(
            f"[Intervention] Resolved {intervention_id}: "
            f"success={resolved}, domain={intervention.domain}"
        )

        return True

    def get_intervention_stats(self) -> Dict[str, Any]:
        """Get intervention statistics for monitoring"""
        from apps.services.tool_server.captcha_intervention import get_intervention_stats
        return get_intervention_stats()


# Global approval manager instance
_approval_manager = None


def get_approval_manager() -> ApprovalManager:
    """Get the global approval manager instance."""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager


async def require_approval(
    operation: str,
    args: Dict[str, Any],
    force: bool = False,
    auto_approve: bool = False
) -> bool:
    """
    Check if operation requires approval and request if needed.

    Args:
        operation: Operation name
        args: Operation arguments
        force: If True, skip approval (for forced operations)
        auto_approve: If True, auto-approve (for testing)

    Returns:
        True if approved (or no approval needed), False otherwise
    """
    from apps.services.tool_server.safety_validator import (
        get_approval_required_operations,
        format_approval_message
    )

    # Check if operation requires approval
    approval_ops = get_approval_required_operations()

    if operation not in approval_ops:
        # No approval needed
        return True

    if force:
        # Forced operation - already approved
        logger.info(f"[Approval] FORCED (no prompt): {operation}")
        return True

    # Format approval message
    message = format_approval_message(operation, args)

    # Request approval
    manager = get_approval_manager()
    approved = await manager.request_approval(
        operation=operation,
        args=args,
        message=message,
        auto_approve=auto_approve
    )

    return approved


# NOTE: Gateway integration
#
# The Gateway needs to:
# 1. Expose endpoint to get pending approval requests
# 2. Expose endpoint to submit approval responses
# 3. Display approval UI to user
#
# Example Gateway endpoints:
#
# @app.get("/approvals/pending")
# async def get_pending_approvals():
#     manager = get_approval_manager()
#     return manager.get_pending_requests()
#
# @app.post("/approvals/respond")
# async def respond_to_approval(request_id: str, approved: bool):
#     manager = get_approval_manager()
#     manager.submit_response(request_id, approved)
#     return {"status": "ok"}
