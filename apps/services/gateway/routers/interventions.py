"""
Interventions Router

Provides endpoints for CAPTCHA and permission intervention handling.

Endpoints:
    GET /interventions/pending - List pending interventions
    POST /interventions/{id}/resolve - Resolve an intervention
    GET /api/captchas/pending - List pending CAPTCHAs
    POST /api/captchas/{id}/resolve - Resolve a CAPTCHA
    GET /api/permissions/pending - List pending permission requests
    POST /api/permissions/{id}/resolve - Resolve a permission request
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from apps.services.gateway.services.jobs import cancel_trace

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["interventions"])


# =============================================================================
# Intervention Endpoints
# =============================================================================


@router.get("/interventions/pending")
async def list_pending_interventions() -> Dict[str, Any]:
    """
    List all pending interventions (CAPTCHAs, permissions, extraction_failed, etc.).

    Returns:
        List of pending interventions as dicts
    """
    try:
        from apps.services.tool_server.captcha_intervention import (
            get_all_pending_interventions,
        )

        intervention_objects = get_all_pending_interventions()
        # Convert InterventionRequest objects to dicts for JSON serialization
        interventions = [i.to_dict() for i in intervention_objects]
        return {
            "interventions": interventions,
            "count": len(interventions),
        }
    except ImportError:
        logger.warning("[Interventions] captcha_intervention module not available")
        return {"interventions": [], "count": 0}
    except Exception as e:
        logger.error(f"[Interventions] Error listing interventions: {e}")
        return {"interventions": [], "count": 0, "error": str(e)}


@router.post("/interventions/{intervention_id}/resolve")
async def resolve_intervention(
    intervention_id: str,
    action: str = "resolved",
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve an intervention.

    Args:
        intervention_id: Intervention identifier
        action: Action taken (resolved, skipped, failed)
        notes: Optional notes about resolution

    Returns:
        Resolution result
    """
    try:
        from apps.services.tool_server.captcha_intervention import (
            get_pending_intervention,
            remove_pending_intervention,
        )

        intervention = get_pending_intervention(intervention_id)
        if not intervention:
            raise HTTPException(404, f"Intervention {intervention_id} not found")

        # Remove from pending
        remove_pending_intervention(intervention_id)

        logger.info(f"[Interventions] Resolved {intervention_id}: {action}")
        return {
            "status": "resolved",
            "intervention_id": intervention_id,
            "action": action,
        }

    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(500, "Intervention module not available")
    except Exception as e:
        logger.error(f"[Interventions] Error resolving {intervention_id}: {e}")
        raise HTTPException(500, str(e))


# =============================================================================
# CAPTCHA Endpoints (Legacy API compatibility)
# =============================================================================


@router.get("/api/captchas/pending")
async def list_pending_captchas() -> Dict[str, Any]:
    """
    List pending CAPTCHA interventions.

    Returns:
        List of pending CAPTCHAs
    """
    try:
        from apps.services.tool_server.captcha_intervention import (
            get_all_pending_interventions,
        )

        all_interventions = get_all_pending_interventions()
        captchas = [i.to_dict() for i in all_interventions if i.intervention_type.value == "captcha"]
        return {
            "captchas": captchas,
            "count": len(captchas),
        }
    except ImportError:
        return {"captchas": [], "count": 0}
    except Exception as e:
        logger.error(f"[CAPTCHA] Error listing captchas: {e}")
        return {"captchas": [], "count": 0, "error": str(e)}


@router.post("/api/captchas/{captcha_id}/resolve")
async def resolve_captcha(
    captcha_id: str,
    success: bool = True,
) -> Dict[str, Any]:
    """
    Mark a CAPTCHA as resolved.

    Args:
        captcha_id: CAPTCHA identifier
        success: Whether CAPTCHA was solved successfully

    Returns:
        Resolution result
    """
    action = "resolved" if success else "failed"
    return await resolve_intervention(captcha_id, action=action)


# =============================================================================
# Permission Endpoints
# =============================================================================


@router.get("/api/permissions/pending")
async def list_pending_permissions() -> Dict[str, Any]:
    """
    List pending permission requests.

    Returns:
        List of pending permission requests
    """
    try:
        from apps.services.tool_server.captcha_intervention import (
            get_all_pending_interventions,
        )

        all_interventions = get_all_pending_interventions()
        permissions = [i.to_dict() for i in all_interventions if i.intervention_type.value == "permission"]
        return {
            "permissions": permissions,
            "count": len(permissions),
        }
    except ImportError:
        return {"permissions": [], "count": 0}
    except Exception as e:
        logger.error(f"[Permissions] Error listing permissions: {e}")
        return {"permissions": [], "count": 0, "error": str(e)}


@router.post("/api/permissions/{permission_id}/resolve")
async def resolve_permission(
    permission_id: str,
    granted: bool = True,
) -> Dict[str, Any]:
    """
    Resolve a permission request.

    Args:
        permission_id: Permission identifier
        granted: Whether permission was granted

    Returns:
        Resolution result
    """
    action = "granted" if granted else "denied"
    return await resolve_intervention(permission_id, action=action)


# =============================================================================
# Trace Cancellation (related to interventions)
# =============================================================================


@router.post("/v1/thinking/{trace_id}/cancel")
async def cancel_trace_endpoint(trace_id: str) -> Dict[str, Any]:
    """
    Cancel a running trace/research operation.

    This is used when the frontend wants to cancel an ongoing research
    operation that was started asynchronously (non-jobs mode).

    Args:
        trace_id: Trace identifier

    Returns:
        Cancellation result
    """
    if not trace_id:
        raise HTTPException(400, "trace_id required")

    return cancel_trace(trace_id)
