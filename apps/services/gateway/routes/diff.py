"""Diff route handlers for Gateway.

Architecture Reference:
    architecture/services/user-interface.md#Section 3.2.1

The chat panel supports a review-first coding loop:
1. Assistant proposes a patch (unified or side-by-side diff)
2. User reviews with inline file links and context chips
3. User chooses Apply, Open Diff, or Reject
4. Edits are never applied without explicit user action

Endpoints:
    GET /diff/last - Get last proposed diff for a session
"""

import logging
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from apps.services.gateway.config import get_config


logger = logging.getLogger(__name__)
config = get_config()

router = APIRouter()


# =============================================================================
# Response Models
# =============================================================================

class FileChange(BaseModel):
    """A single file change in a diff."""
    file_path: str = Field(..., description="Absolute path to file")
    change_type: str = Field(..., description="Type: create, modify, delete, rename")
    old_path: Optional[str] = Field(None, description="Original path if renamed")
    additions: int = Field(0, description="Lines added")
    deletions: int = Field(0, description="Lines deleted")
    unified_diff: str = Field(..., description="Unified diff content")
    language: Optional[str] = Field(None, description="Detected language for syntax highlighting")


class DiffProposal(BaseModel):
    """A proposed set of changes (diff)."""
    diff_id: str = Field(..., description="Unique diff identifier")
    turn_number: int = Field(..., description="Turn that proposed this diff")
    session_id: str = Field(..., description="Session identifier")
    created_at: str = Field(..., description="ISO timestamp of creation")
    status: str = Field(..., description="Status: pending, applied, rejected, expired")
    summary: str = Field(..., description="Brief description of changes")
    files: list[FileChange] = Field(default_factory=list, description="List of file changes")
    total_additions: int = Field(0, description="Total lines added")
    total_deletions: int = Field(0, description="Total lines deleted")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class DiffLastResponse(BaseModel):
    """Response for getting the last proposed diff."""
    has_diff: bool = Field(..., description="Whether there is a pending diff")
    diff: Optional[DiffProposal] = Field(None, description="The diff proposal if exists")


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/last", response_model=DiffLastResponse)
async def get_last_diff(
    session_id: str = Query(..., description="Session identifier"),
    status: Optional[str] = Query(default="pending", description="Filter by status"),
) -> DiffLastResponse:
    """Get the last proposed diff for a session.

    Returns the most recent diff proposal for the given session.
    By default, only returns pending (unapplied) diffs.

    Args:
        session_id: Session identifier
        status: Filter by status (pending, applied, rejected, expired)

    Returns:
        DiffLastResponse with the diff proposal if exists
    """
    logger.info(f"Get last diff: session={session_id}, status={status}")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.get(
                f"{config.tool_server_url}/diff/last",
                params={
                    "session_id": session_id,
                    "status": status,
                },
            )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()

            if data.get("has_diff") and data.get("diff"):
                return DiffLastResponse(
                    has_diff=True,
                    diff=DiffProposal(
                        diff_id=data["diff"].get("diff_id", ""),
                        turn_number=data["diff"].get("turn_number", 0),
                        session_id=data["diff"].get("session_id", session_id),
                        created_at=data["diff"].get("created_at", ""),
                        status=data["diff"].get("status", "pending"),
                        summary=data["diff"].get("summary", ""),
                        files=[FileChange(**f) for f in data["diff"].get("files", [])],
                        total_additions=data["diff"].get("total_additions", 0),
                        total_deletions=data["diff"].get("total_deletions", 0),
                        metadata=data["diff"].get("metadata", {}),
                    ),
                )
            else:
                return DiffLastResponse(has_diff=False, diff=None)

    except httpx.ConnectError:
        logger.error("Cannot connect to Tool Server")
        raise HTTPException(
            status_code=503,
            detail={"error": "Tool Server service unavailable"},
        )
