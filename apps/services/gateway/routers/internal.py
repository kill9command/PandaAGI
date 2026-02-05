"""
Internal Router - Endpoints for inter-service communication.

Provides endpoints that the Tool Server calls to send events to the Gateway,
which then broadcasts them to connected WebSocket clients.

Endpoints:
    POST /internal/research_event - Receive research events from Tool Server
    POST /internal/browser_frame - Receive browser frames (optional, for live view)
"""

import logging
from typing import Dict, Any

from fastapi import APIRouter

from apps.services.gateway.dependencies import get_research_ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/research_event")
async def receive_research_event(event: Dict[str, Any]):
    """
    Internal endpoint for Tool Server to send research events.
    Broadcasts events to connected WebSocket clients.

    Event types include:
        - research_started: Research phase began
        - phase_started: A specific phase started
        - phase_complete: A phase completed
        - intervention_needed: CAPTCHA/blocker detected, human help needed
        - intervention_resolved: Intervention was resolved
        - research_complete: Research finished
        - vendor_progress: Progress update on vendor visits
    """
    session_id = event.get("session_id", "default")
    event_type = event.get("type", "unknown")

    logger.info(f"[ResearchEvent] Received {event_type} event for session {session_id}")

    research_ws_manager = get_research_ws_manager()
    if research_ws_manager:
        await research_ws_manager.broadcast_event(session_id, event)
        logger.info(f"[ResearchEvent] Broadcast complete for {event_type}")
    else:
        logger.warning(f"[ResearchEvent] No WebSocket manager available, event not broadcast")

    return {"ok": True}


@router.post("/browser_frame")
async def receive_browser_frame(frame_data: Dict[str, Any]):
    """
    Internal endpoint for Tool Server to send browser frames.
    Used for live browser view in research monitor.
    """
    session_id = frame_data.get("session_id", "default")

    research_ws_manager = get_research_ws_manager()
    if research_ws_manager:
        await research_ws_manager.broadcast_event(session_id, {
            "type": "browser_frame",
            "data": frame_data
        })

    return {"ok": True}
