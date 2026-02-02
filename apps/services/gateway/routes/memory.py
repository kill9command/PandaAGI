"""Memory route handlers for Gateway.

Architecture Reference:
    architecture/services/user-interface.md#Section 6

Endpoints:
    POST   /memory          - Store memory
    GET    /memory/search   - Search memories
    DELETE /memory/{id}     - Delete memory
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
# Request/Response Models
# =============================================================================

class MemoryStoreRequest(BaseModel):
    """Request to store a memory."""
    content: str = Field(..., description="Memory content to store")
    memory_type: str = Field(default="fact", description="Type: fact, preference, context")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    session_id: Optional[str] = Field(None, description="Session context")
    user_id: str = Field(default="default", description="User identifier")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class MemoryStoreResponse(BaseModel):
    """Response after storing memory."""
    memory_id: str = Field(..., description="Unique memory identifier")
    status: str = Field(..., description="Storage status")
    message: str = Field(..., description="Status message")


class MemoryItem(BaseModel):
    """A single memory item."""
    memory_id: str = Field(..., description="Unique memory identifier")
    content: str = Field(..., description="Memory content")
    memory_type: str = Field(..., description="Type: fact, preference, context")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    score: Optional[float] = Field(None, description="Relevance score (for search)")
    created_at: str = Field(..., description="ISO timestamp of creation")
    user_id: str = Field(..., description="User identifier")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class MemorySearchResponse(BaseModel):
    """Response for memory search."""
    memories: list[MemoryItem] = Field(default_factory=list, description="Matching memories")
    total: int = Field(0, description="Total matches")
    query: str = Field(..., description="Search query used")


class MemoryDeleteResponse(BaseModel):
    """Response after deleting memory."""
    status: str = Field(..., description="Deletion status")
    message: str = Field(..., description="Status message")


# =============================================================================
# Endpoints
# =============================================================================

@router.post("", response_model=MemoryStoreResponse)
async def store_memory(request: MemoryStoreRequest) -> MemoryStoreResponse:
    """Store a new memory.

    Memories are stored in the vector database for semantic retrieval.
    They can be facts, preferences, or contextual information.

    Args:
        request: Memory storage request

    Returns:
        MemoryStoreResponse with memory ID and status
    """
    logger.info(f"Store memory: type={request.memory_type}, user={request.user_id}")
    logger.debug(f"Content: {request.content[:100]}...")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(
                f"{config.orchestrator_url}/memory",
                json=request.model_dump(),
            )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()
            return MemoryStoreResponse(
                memory_id=data.get("memory_id", ""),
                status=data.get("status", "stored"),
                message=data.get("message", "Memory stored successfully"),
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Orchestrator")
        raise HTTPException(
            status_code=503,
            detail={"error": "Orchestrator service unavailable"},
        )


@router.get("/search", response_model=MemorySearchResponse)
async def search_memories(
    query: str = Query(..., description="Search query"),
    limit: int = Query(default=10, ge=1, le=50, description="Number of results"),
    memory_type: Optional[str] = Query(default=None, description="Filter by type"),
    user_id: str = Query(default="default", description="User identifier"),
    tags: Optional[str] = Query(default=None, description="Comma-separated tags to filter by"),
) -> MemorySearchResponse:
    """Search memories using semantic similarity.

    Performs vector search against stored memories and returns
    the most relevant matches based on the query.

    Args:
        query: Search query (semantic search)
        limit: Maximum number of results (default 10, max 50)
        memory_type: Optional filter by memory type
        user_id: User identifier for scoping search
        tags: Optional comma-separated tags to filter by

    Returns:
        MemorySearchResponse with matching memories
    """
    logger.info(f"Search memories: query='{query[:50]}...', user={user_id}")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            params = {
                "query": query,
                "limit": limit,
                "user_id": user_id,
            }
            if memory_type:
                params["memory_type"] = memory_type
            if tags:
                params["tags"] = tags

            response = await client.get(
                f"{config.orchestrator_url}/memory/search",
                params=params,
            )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()
            return MemorySearchResponse(
                memories=[MemoryItem(**m) for m in data.get("memories", [])],
                total=data.get("total", 0),
                query=query,
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Orchestrator")
        raise HTTPException(
            status_code=503,
            detail={"error": "Orchestrator service unavailable"},
        )


@router.delete("/{memory_id}", response_model=MemoryDeleteResponse)
async def delete_memory(
    memory_id: str,
    user_id: str = Query(default="default", description="User identifier"),
) -> MemoryDeleteResponse:
    """Delete a specific memory.

    Permanently removes the memory from storage. This action cannot be undone.

    Args:
        memory_id: Memory identifier to delete
        user_id: User identifier (for authorization)

    Returns:
        MemoryDeleteResponse with status
    """
    logger.info(f"Delete memory: id={memory_id}, user={user_id}")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.delete(
                f"{config.orchestrator_url}/memory/{memory_id}",
                params={"user_id": user_id},
            )

            if response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail={"error": f"Memory {memory_id} not found"},
                )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()
            return MemoryDeleteResponse(
                status=data.get("status", "deleted"),
                message=data.get("message", "Memory deleted successfully"),
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Orchestrator")
        raise HTTPException(
            status_code=503,
            detail={"error": "Orchestrator service unavailable"},
        )
