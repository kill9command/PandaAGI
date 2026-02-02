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

from apps.services.gateway.research_ws_manager import research_ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websockets"])


async def forward_intervention_response(session_id: str, message: dict):
    """Forward intervention response to orchestrator."""
    # TODO: Implement proper forwarding to orchestrator
    logger.info(f"[WebSocket] Forwarding intervention response for {session_id}: {message}")


@router.websocket("/ws/research/{session_id}")
async def research_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time research monitoring.

    Clients connect to receive live events during web research operations.
    """
    await research_ws_manager.connect(websocket, session_id)
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
        await research_ws_manager.disconnect(websocket, session_id)
    except Exception as e:
        logger.error(f"[ResearchWS] Error: {e}")
        await research_ws_manager.disconnect(websocket, session_id)
