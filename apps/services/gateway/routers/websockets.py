"""
WebSocket Endpoints Router

Handles real-time WebSocket connections for:
- Research monitoring
- Browser control
- Browser streaming
- noVNC proxy
"""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from apps.services.gateway.dependencies import get_research_ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websockets"])


async def forward_intervention_response(session_id: str, message: dict):
    """Forward intervention response to orchestrator via captcha_intervention module."""
    try:
        from apps.services.tool_server.captcha_intervention import (
            get_pending_intervention,
            remove_pending_intervention,
        )

        intervention_id = message.get("intervention_id")
        if not intervention_id:
            logger.warning(f"[WebSocket] No intervention_id in response: {message}")
            return

        intervention = get_pending_intervention(intervention_id)
        if not intervention:
            logger.warning(f"[WebSocket] Intervention {intervention_id} not found")
            return

        remove_pending_intervention(intervention_id)
        action = message.get("action", "resolved")
        logger.info(f"[WebSocket] Resolved intervention {intervention_id}: {action}")
    except ImportError:
        logger.error("[WebSocket] captcha_intervention module not available")
    except Exception as e:
        logger.error(f"[WebSocket] Error forwarding intervention: {e}")


@router.websocket("/ws/research/{session_id}")
async def research_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time research monitoring.

    Clients connect to receive live events during web research operations.
    """
    ws_manager = get_research_ws_manager()
    await ws_manager.connect(websocket, session_id)
    try:
        # Keep connection alive and listen for client messages
        while True:
            data = await websocket.receive_text()
            logger.info(f"[ResearchWS] Received from client: {data}")

            # Parse and handle intervention responses
            try:
                message = json.loads(data)
                if message.get("type") == "intervention_response":
                    # Forward to orchestrator's intervention manager
                    await forward_intervention_response(session_id, message)
                    logger.info(f"[ResearchWS] Forwarded intervention response for session {session_id}")
            except json.JSONDecodeError:
                logger.warning(f"[ResearchWS] Invalid JSON from {session_id}: {data}")
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, session_id)
    except Exception as e:
        logger.error(f"[ResearchWS] Error: {e}")
        await ws_manager.disconnect(websocket, session_id)
