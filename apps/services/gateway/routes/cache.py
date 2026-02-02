"""Cache route handlers for Gateway.

Architecture Reference:
    architecture/services/user-interface.md#Section 6

Endpoints:
    GET    /cache           - List cache entries
    GET    /cache/{topic}   - Get cache entry by topic
    DELETE /cache           - Clear cache
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

class CacheEntry(BaseModel):
    """A single cache entry."""
    topic: str = Field(..., description="Cache topic/key")
    cache_type: str = Field(..., description="Type: research, query, embedding")
    created_at: str = Field(..., description="ISO timestamp of creation")
    expires_at: Optional[str] = Field(None, description="ISO timestamp of expiration")
    size_bytes: int = Field(0, description="Size of cached data in bytes")
    hit_count: int = Field(0, description="Number of cache hits")
    summary: Optional[str] = Field(None, description="Brief summary of cached content")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class CacheListResponse(BaseModel):
    """Response for listing cache entries."""
    entries: list[CacheEntry] = Field(default_factory=list, description="List of cache entries")
    total: int = Field(0, description="Total number of entries")
    total_size_bytes: int = Field(0, description="Total size of all cached data")
    cache_type: Optional[str] = Field(None, description="Filtered cache type if specified")


class CacheDetailResponse(BaseModel):
    """Detailed cache entry with full data."""
    topic: str = Field(..., description="Cache topic/key")
    cache_type: str = Field(..., description="Type: research, query, embedding")
    created_at: str = Field(..., description="ISO timestamp of creation")
    expires_at: Optional[str] = Field(None, description="ISO timestamp of expiration")
    size_bytes: int = Field(0, description="Size of cached data in bytes")
    hit_count: int = Field(0, description="Number of cache hits")
    data: Any = Field(..., description="Cached data")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class CacheClearResponse(BaseModel):
    """Response after clearing cache."""
    status: str = Field(..., description="Clear status")
    message: str = Field(..., description="Status message")
    entries_cleared: int = Field(0, description="Number of entries cleared")
    bytes_freed: int = Field(0, description="Bytes freed")


# =============================================================================
# Endpoints
# =============================================================================

@router.get("", response_model=CacheListResponse)
async def list_cache(
    cache_type: Optional[str] = Query(default=None, description="Filter by cache type"),
    limit: int = Query(default=50, ge=1, le=200, description="Number of entries to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
) -> CacheListResponse:
    """List cache entries.

    Returns a list of cached research results, query results, and embeddings.
    Entries are sorted by creation time (most recent first).

    Args:
        cache_type: Optional filter by cache type (research, query, embedding)
        limit: Maximum number of entries (default 50, max 200)
        offset: Offset for pagination

    Returns:
        CacheListResponse with list of cache entries
    """
    logger.info(f"List cache: type={cache_type}, limit={limit}, offset={offset}")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            params = {
                "limit": limit,
                "offset": offset,
            }
            if cache_type:
                params["cache_type"] = cache_type

            response = await client.get(
                f"{config.orchestrator_url}/cache",
                params=params,
            )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()
            return CacheListResponse(
                entries=[CacheEntry(**e) for e in data.get("entries", [])],
                total=data.get("total", 0),
                total_size_bytes=data.get("total_size_bytes", 0),
                cache_type=cache_type,
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Orchestrator")
        raise HTTPException(
            status_code=503,
            detail={"error": "Orchestrator service unavailable"},
        )


@router.get("/{topic:path}", response_model=CacheDetailResponse)
async def get_cache_entry(topic: str) -> CacheDetailResponse:
    """Get a specific cache entry by topic.

    Returns the full cached data for a topic, including research results
    or other cached information.

    Args:
        topic: Cache topic/key to retrieve

    Returns:
        CacheDetailResponse with full cached data
    """
    logger.info(f"Get cache entry: topic={topic}")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.get(
                f"{config.orchestrator_url}/cache/{topic}",
            )

            if response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail={"error": f"Cache entry not found: {topic}"},
                )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()
            return CacheDetailResponse(**data)

    except httpx.ConnectError:
        logger.error("Cannot connect to Orchestrator")
        raise HTTPException(
            status_code=503,
            detail={"error": "Orchestrator service unavailable"},
        )


@router.delete("", response_model=CacheClearResponse)
async def clear_cache(
    cache_type: Optional[str] = Query(default=None, description="Clear only this cache type"),
    older_than_hours: Optional[int] = Query(default=None, description="Clear entries older than N hours"),
) -> CacheClearResponse:
    """Clear cache entries.

    Clears all cache entries or a subset based on filters.
    This action cannot be undone.

    Args:
        cache_type: Optional filter to clear only specific cache type
        older_than_hours: Optional filter to clear entries older than N hours

    Returns:
        CacheClearResponse with status and count of cleared entries
    """
    logger.info(f"Clear cache: type={cache_type}, older_than={older_than_hours}h")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            params = {}
            if cache_type:
                params["cache_type"] = cache_type
            if older_than_hours:
                params["older_than_hours"] = older_than_hours

            response = await client.delete(
                f"{config.orchestrator_url}/cache",
                params=params,
            )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()
            return CacheClearResponse(
                status=data.get("status", "cleared"),
                message=data.get("message", "Cache cleared successfully"),
                entries_cleared=data.get("entries_cleared", 0),
                bytes_freed=data.get("bytes_freed", 0),
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Orchestrator")
        raise HTTPException(
            status_code=503,
            detail={"error": "Orchestrator service unavailable"},
        )
