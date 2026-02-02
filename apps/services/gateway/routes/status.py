"""Status route handlers for Gateway.

Architecture Reference:
    architecture/services/user-interface.md#Section 6

Endpoints:
    GET /status     - System health (aggregated from all services)
    GET /metrics    - Observability metrics
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

class ServiceStatus(BaseModel):
    """Status of a single service."""
    name: str = Field(..., description="Service name")
    status: str = Field(..., description="Status: healthy, degraded, unhealthy")
    version: Optional[str] = Field(None, description="Service version")
    uptime_seconds: Optional[float] = Field(None, description="Service uptime in seconds")
    last_check: str = Field(..., description="ISO timestamp of last health check")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional status details")


class ModelStatus(BaseModel):
    """Status of a loaded model."""
    name: str = Field(..., description="Model name")
    role: str = Field(..., description="Role: MIND, EYES, REFLEX, etc.")
    status: str = Field(..., description="Status: loaded, loading, unloaded")
    vram_mb: Optional[float] = Field(None, description="VRAM usage in MB")
    requests_served: int = Field(0, description="Total requests served")
    avg_latency_ms: Optional[float] = Field(None, description="Average latency in ms")


class SystemStatusResponse(BaseModel):
    """Full system status response."""
    status: str = Field(..., description="Overall status: healthy, degraded, unhealthy")
    gateway: ServiceStatus = Field(..., description="Gateway service status")
    orchestrator: Optional[ServiceStatus] = Field(None, description="Orchestrator status")
    vllm: Optional[ServiceStatus] = Field(None, description="vLLM server status")
    models: list[ModelStatus] = Field(default_factory=list, description="Loaded models")
    database: Optional[ServiceStatus] = Field(None, description="Database status")
    qdrant: Optional[ServiceStatus] = Field(None, description="Qdrant vector DB status")
    active_sessions: int = Field(0, description="Number of active sessions")
    active_research: int = Field(0, description="Number of active research operations")


class MetricsResponse(BaseModel):
    """Observability metrics response."""
    timestamp: str = Field(..., description="ISO timestamp of metrics collection")
    period: str = Field(..., description="Metrics period: today, 24h, 7d")

    # Request metrics
    total_requests: int = Field(0, description="Total requests received")
    successful_requests: int = Field(0, description="Successful requests")
    failed_requests: int = Field(0, description="Failed requests")
    avg_response_time_ms: float = Field(0.0, description="Average response time in ms")

    # Turn metrics
    total_turns: int = Field(0, description="Total turns processed")
    turns_by_type: dict[str, int] = Field(default_factory=dict, description="Turns by query type")
    avg_quality_score: float = Field(0.0, description="Average quality score")
    validation_stats: dict[str, int] = Field(default_factory=dict, description="Validation decisions")

    # Token metrics
    total_tokens: int = Field(0, description="Total tokens used")
    tokens_by_model: dict[str, int] = Field(default_factory=dict, description="Tokens by model")
    tokens_by_role: dict[str, int] = Field(default_factory=dict, description="Tokens by role")

    # Research metrics
    research_count: int = Field(0, description="Total research operations")
    vendors_visited: int = Field(0, description="Total vendor pages visited")
    products_found: int = Field(0, description="Total products found")
    interventions_required: int = Field(0, description="CAPTCHAs and blockers encountered")
    interventions_resolved: int = Field(0, description="Interventions resolved by user")

    # Error metrics
    errors_by_phase: dict[str, int] = Field(default_factory=dict, description="Errors by phase")
    retry_count: int = Field(0, description="Total RETRY loops triggered")
    revise_count: int = Field(0, description="Total REVISE loops triggered")

    # Cache metrics
    cache_hits: int = Field(0, description="Cache hits")
    cache_misses: int = Field(0, description="Cache misses")
    cache_size_mb: float = Field(0.0, description="Total cache size in MB")


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status() -> SystemStatusResponse:
    """Get aggregated system health status.

    Collects health information from all services and returns
    an aggregated view of system status.

    Returns:
        SystemStatusResponse with status of all components
    """
    logger.info("Getting system status")

    from datetime import datetime, timezone

    # Start with Gateway status (always available since we're running)
    gateway_status = ServiceStatus(
        name="gateway",
        status="healthy",
        version="2.0.0",
        last_check=datetime.now(timezone.utc).isoformat(),
        details={
            "port": config.port,
            "orchestrator_url": config.orchestrator_url,
        },
    )

    # Try to get Orchestrator status
    orchestrator_status = None
    vllm_status = None
    model_statuses = []
    database_status = None
    qdrant_status = None
    active_sessions = 0
    active_research = 0

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            response = await client.get(f"{config.orchestrator_url}/status")

            if response.status_code == 200:
                data = response.json()

                orchestrator_status = ServiceStatus(
                    name="orchestrator",
                    status=data.get("status", "healthy"),
                    version=data.get("version"),
                    uptime_seconds=data.get("uptime_seconds"),
                    last_check=datetime.now(timezone.utc).isoformat(),
                    details=data.get("details", {}),
                )

                # Extract nested status info if available
                if "vllm" in data:
                    vllm_status = ServiceStatus(**data["vllm"])

                if "models" in data:
                    # Transform orchestrator model format to gateway format
                    for m in data["models"]:
                        model_statuses.append(ModelStatus(
                            name=m.get("name", "unknown"),
                            role=m.get("role", "UNKNOWN"),
                            status="loaded" if m.get("loaded", False) else "unloaded",
                            vram_mb=m.get("vram_mb"),
                            requests_served=m.get("requests_served", 0),
                            avg_latency_ms=m.get("avg_latency_ms"),
                        ))

                if "database" in data:
                    database_status = ServiceStatus(**data["database"])

                if "qdrant" in data:
                    qdrant_status = ServiceStatus(**data["qdrant"])

                active_sessions = data.get("active_sessions", 0)
                active_research = data.get("active_research", 0)

    except httpx.ConnectError:
        logger.warning("Cannot connect to Orchestrator for status check")
        orchestrator_status = ServiceStatus(
            name="orchestrator",
            status="unhealthy",
            last_check=datetime.now(timezone.utc).isoformat(),
            details={"error": "Connection refused"},
        )
    except Exception as e:
        logger.error(f"Error getting Orchestrator status: {e}")
        orchestrator_status = ServiceStatus(
            name="orchestrator",
            status="unknown",
            last_check=datetime.now(timezone.utc).isoformat(),
            details={"error": str(e)},
        )

    # Determine overall status
    overall_status = "healthy"
    if orchestrator_status and orchestrator_status.status != "healthy":
        overall_status = "degraded" if orchestrator_status.status == "degraded" else "unhealthy"

    return SystemStatusResponse(
        status=overall_status,
        gateway=gateway_status,
        orchestrator=orchestrator_status,
        vllm=vllm_status,
        models=model_statuses,
        database=database_status,
        qdrant=qdrant_status,
        active_sessions=active_sessions,
        active_research=active_research,
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    period: str = Query(default="today", description="Period: today, 24h, 7d"),
) -> MetricsResponse:
    """Get observability metrics.

    Returns detailed metrics about system usage, performance,
    and errors for the specified time period.

    Args:
        period: Time period for metrics (today, 24h, 7d)

    Returns:
        MetricsResponse with detailed metrics
    """
    logger.info(f"Getting metrics: period={period}")

    from datetime import datetime, timezone

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.get(
                f"{config.orchestrator_url}/metrics",
                params={"period": period},
            )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()
            return MetricsResponse(
                timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                period=period,
                total_requests=data.get("total_requests", 0),
                successful_requests=data.get("successful_requests", 0),
                failed_requests=data.get("failed_requests", 0),
                avg_response_time_ms=data.get("avg_response_time_ms", 0.0),
                total_turns=data.get("total_turns", 0),
                turns_by_type=data.get("turns_by_type", {}),
                avg_quality_score=data.get("avg_quality_score", 0.0),
                validation_stats=data.get("validation_stats", {}),
                total_tokens=data.get("total_tokens", 0),
                tokens_by_model=data.get("tokens_by_model", {}),
                tokens_by_role=data.get("tokens_by_role", {}),
                research_count=data.get("research_count", 0),
                vendors_visited=data.get("vendors_visited", 0),
                products_found=data.get("products_found", 0),
                interventions_required=data.get("interventions_required", 0),
                interventions_resolved=data.get("interventions_resolved", 0),
                errors_by_phase=data.get("errors_by_phase", {}),
                retry_count=data.get("retry_count", 0),
                revise_count=data.get("revise_count", 0),
                cache_hits=data.get("cache_hits", 0),
                cache_misses=data.get("cache_misses", 0),
                cache_size_mb=data.get("cache_size_mb", 0.0),
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Orchestrator for metrics")
        raise HTTPException(
            status_code=503,
            detail={"error": "Orchestrator service unavailable"},
        )
