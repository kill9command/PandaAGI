"""Turn route handlers for Gateway.

Architecture Reference:
    architecture/services/user-interface.md#Section 6

Endpoints:
    GET /turns          - List recent turns
    GET /turns/{id}     - Get specific turn
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

class TurnSummary(BaseModel):
    """Summary of a single turn."""
    turn_number: int = Field(..., description="Turn identifier")
    query: str = Field(..., description="Original user query (truncated)")
    query_type: Optional[str] = Field(None, description="Query type classification")
    intent: Optional[str] = Field(None, description="Intent classification")
    quality: Optional[float] = Field(None, description="Quality score (0-1)")
    validation: Optional[str] = Field(None, description="Validation decision")
    created_at: str = Field(..., description="ISO timestamp of turn creation")
    session_id: Optional[str] = Field(None, description="Session identifier")


class TurnListResponse(BaseModel):
    """Response for listing turns."""
    turns: list[TurnSummary] = Field(default_factory=list, description="List of turn summaries")
    total: int = Field(0, description="Total number of turns")
    offset: int = Field(0, description="Current offset")
    limit: int = Field(20, description="Results per page")


class TurnDetail(BaseModel):
    """Detailed information about a single turn."""
    turn_number: int = Field(..., description="Turn identifier")
    query: str = Field(..., description="Original user query")
    response: str = Field(..., description="Generated response")
    query_type: Optional[str] = Field(None, description="Query type classification")
    intent: Optional[str] = Field(None, description="Intent classification")
    quality: Optional[float] = Field(None, description="Quality score (0-1)")
    validation: Optional[str] = Field(None, description="Validation decision")
    created_at: str = Field(..., description="ISO timestamp of turn creation")
    session_id: Optional[str] = Field(None, description="Session identifier")
    user_id: Optional[str] = Field(None, description="User identifier")
    context_path: Optional[str] = Field(None, description="Path to context.md file")
    phases: Optional[list[dict[str, Any]]] = Field(None, description="Phase execution details")
    research_results: Optional[dict[str, Any]] = Field(None, description="Research results if applicable")


# =============================================================================
# Endpoints
# =============================================================================

@router.get("", response_model=TurnListResponse)
async def list_turns(
    limit: int = Query(default=20, ge=1, le=100, description="Number of turns to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    session_id: Optional[str] = Query(default=None, description="Filter by session ID"),
    user_id: Optional[str] = Query(default=None, description="Filter by user ID"),
) -> TurnListResponse:
    """List recent turns.

    Returns a paginated list of recent conversation turns,
    sorted by creation time (most recent first).

    Args:
        limit: Number of turns to return (default 20, max 100)
        offset: Offset for pagination
        session_id: Optional filter by session ID
        user_id: Optional filter by user ID

    Returns:
        TurnListResponse with list of turn summaries
    """
    logger.info(f"List turns: limit={limit}, offset={offset}, session_id={session_id}")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            params = {
                "limit": limit,
                "offset": offset,
            }
            if session_id:
                params["session_id"] = session_id
            if user_id:
                params["user_id"] = user_id

            response = await client.get(
                f"{config.tool_server_url}/turns",
                params=params,
            )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()
            return TurnListResponse(
                turns=[TurnSummary(**t) for t in data.get("turns", [])],
                total=data.get("total", 0),
                offset=data.get("offset", offset),
                limit=data.get("limit", limit),
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Tool Server")
        raise HTTPException(
            status_code=503,
            detail={"error": "Tool Server service unavailable"},
        )


@router.get("/{turn_id}", response_model=TurnDetail)
async def get_turn(turn_id: int) -> TurnDetail:
    """Get details for a specific turn.

    Returns full details including query, response, context path,
    phase execution details, and research results if applicable.

    Args:
        turn_id: Turn number to retrieve

    Returns:
        TurnDetail with full turn information
    """
    logger.info(f"Get turn: {turn_id}")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.get(
                f"{config.tool_server_url}/turns/{turn_id}",
            )

            if response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail={"error": f"Turn {turn_id} not found"},
                )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()
            return TurnDetail(**data)

    except httpx.ConnectError:
        logger.error("Cannot connect to Tool Server")
        raise HTTPException(
            status_code=503,
            detail={"error": "Tool Server service unavailable"},
        )
