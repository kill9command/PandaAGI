"""
Health Check Router

Provides health check endpoints for the Gateway service.

Endpoints:
    GET /healthz - Kubernetes-style health check
    GET /health  - Alias for /healthz
    GET /health/detailed - Detailed health with dependencies
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter

from apps.services.gateway.dependencies import (
    is_unified_flow_enabled,
    get_unified_flow,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> Dict[str, Any]:
    """
    Kubernetes-style health check endpoint.

    Returns:
        Health status dict with unified flow status
    """
    unified_flow = get_unified_flow()
    return {
        "status": "healthy" if unified_flow else "degraded",
        "unified_flow_enabled": is_unified_flow_enabled(),
        "unified_flow_ready": unified_flow is not None,
    }


@router.get("/health")
async def health() -> Dict[str, Any]:
    """
    Health check endpoint (alias for /healthz).

    Returns:
        Health status dict
    """
    return await healthz()


@router.get("/health/detailed")
async def health_detailed() -> Dict[str, Any]:
    """
    Detailed health check with dependency status.

    Returns:
        Detailed health status including all dependencies
    """
    from apps.services.gateway.dependencies import (
        get_llm_client,
        get_claim_registry,
        get_session_contexts,
    )
    # NOTE: get_tool_router and get_intent_classifier removed - replaced by LLM-driven user_purpose

    # Check each dependency
    checks = {}

    try:
        unified_flow = get_unified_flow()
        checks["unified_flow"] = "ok" if unified_flow else "disabled"
    except Exception as e:
        checks["unified_flow"] = f"error: {e}"

    # tool_router and intent_classifier removed - Phase 0 now handles via LLM
    checks["user_purpose_system"] = "ok"

    try:
        llm_client = get_llm_client()
        checks["llm_client"] = "ok" if llm_client else "not initialized"
    except Exception as e:
        checks["llm_client"] = f"error: {e}"

    try:
        claim_registry = get_claim_registry()
        checks["claim_registry"] = "ok" if claim_registry else "not initialized"
    except Exception as e:
        checks["claim_registry"] = f"error: {e}"

    try:
        session_contexts = get_session_contexts()
        checks["session_contexts"] = "ok" if session_contexts else "not initialized"
    except Exception as e:
        checks["session_contexts"] = f"error: {e}"

    # Determine overall status
    all_ok = all(v == "ok" for v in checks.values() if v != "disabled")
    any_error = any("error" in str(v) for v in checks.values())

    if any_error:
        status = "unhealthy"
    elif all_ok:
        status = "healthy"
    else:
        status = "degraded"

    return {
        "status": status,
        "unified_flow_enabled": is_unified_flow_enabled(),
        "checks": checks,
    }
