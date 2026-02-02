"""
Approval Router - API endpoints for tool approval system.

Implements Factor 6/7 (Pause/Resume + Human Contact) from 12-Factor Agents.
Provides endpoints for UI to:
- View pending approval requests
- Approve or deny tool execution
- Get approval request details

Architecture Reference:
    architecture/Implementation/04-SERVICES-OVERVIEW.md
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from libs.gateway.tool_approval import (
    get_tool_approval_manager,
    APPROVAL_REQUIRED_TOOLS,
    APPROVAL_SYSTEM_ENABLED,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approvals", tags=["approvals"])


# =============================================================================
# Request/Response Models
# =============================================================================


class ApprovalResolveRequest(BaseModel):
    """Request body for resolving an approval."""
    approved: bool
    reason: str = ""


class ApprovalConfig(BaseModel):
    """Configuration for a tool requiring approval."""
    tool_name: str
    reason: str
    timeout: int
    category: str


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/status")
async def get_approval_status():
    """
    Get the status of the approval system.

    Returns:
        enabled: Whether approval system is enabled
        tools: List of tools requiring approval with their configs
    """
    return {
        "enabled": APPROVAL_SYSTEM_ENABLED,
        "tools": [
            {
                "tool_name": tool_name,
                "reason": config.get("reason"),
                "timeout": config.get("timeout"),
                "category": config.get("category"),
            }
            for tool_name, config in APPROVAL_REQUIRED_TOOLS.items()
        ],
    }


@router.get("/pending")
async def get_pending_approvals(session_id: Optional[str] = Query(None)):
    """
    Get all pending approval requests.

    Args:
        session_id: Optional filter by session ID

    Returns:
        List of pending approval requests
    """
    manager = get_tool_approval_manager()
    pending = manager.get_pending(session_id)

    return {
        "count": len(pending),
        "requests": [r.to_dict() for r in pending],
    }


@router.get("/{request_id}")
async def get_approval_request(request_id: str):
    """
    Get details of a specific approval request.

    Args:
        request_id: The approval request ID

    Returns:
        Approval request details

    Raises:
        404: If request not found
    """
    manager = get_tool_approval_manager()
    request = manager.get_request(request_id)

    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")

    return request.to_dict()


@router.post("/{request_id}/resolve")
async def resolve_approval(request_id: str, body: ApprovalResolveRequest):
    """
    Resolve an approval request (approve or deny).

    Args:
        request_id: The approval request ID
        body: Resolution details (approved: bool, reason: str)

    Returns:
        Resolution status

    Raises:
        404: If request not found
    """
    manager = get_tool_approval_manager()

    # Check if request exists
    request = manager.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")

    # Resolve the request
    success = await manager.resolve(
        request_id=request_id,
        approved=body.approved,
        reason=body.reason,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to resolve approval")

    action = "approved" if body.approved else "denied"
    logger.info(
        f"[ApprovalsRouter] Request {request_id} {action} "
        f"(tool={request.tool_name}, reason={body.reason})"
    )

    return {
        "status": "resolved",
        "request_id": request_id,
        "action": action,
        "tool_name": request.tool_name,
    }


@router.post("/{request_id}/approve")
async def approve_request(request_id: str):
    """
    Approve a tool execution request (convenience endpoint).

    Args:
        request_id: The approval request ID

    Returns:
        Resolution status
    """
    return await resolve_approval(
        request_id,
        ApprovalResolveRequest(approved=True),
    )


@router.post("/{request_id}/deny")
async def deny_request(request_id: str, reason: str = ""):
    """
    Deny a tool execution request (convenience endpoint).

    Args:
        request_id: The approval request ID
        reason: Optional reason for denial

    Returns:
        Resolution status
    """
    return await resolve_approval(
        request_id,
        ApprovalResolveRequest(approved=False, reason=reason),
    )


@router.delete("/expired")
async def clear_expired_approvals(max_age_seconds: int = Query(300)):
    """
    Clear expired approval requests.

    Args:
        max_age_seconds: Maximum age of requests to keep (default 300)

    Returns:
        Cleanup status
    """
    manager = get_tool_approval_manager()
    manager.clear_expired(max_age_seconds)

    return {
        "status": "cleared",
        "max_age_seconds": max_age_seconds,
    }
