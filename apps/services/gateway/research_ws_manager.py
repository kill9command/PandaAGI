"""
gateway/research_ws_manager.py

WebSocket connection manager for research monitoring dashboard.
Manages client connections and broadcasts research events.
"""
from __future__ import annotations
import logging
from typing import Dict, List, Set
from fastapi import WebSocket
import json
import asyncio

logger = logging.getLogger(__name__)


class ResearchWebSocketManager:
    """
    Manages WebSocket connections for research monitoring.

    Responsibilities:
    - Accept/remove client connections
    - Broadcast events to all connected clients
    - Track active research sessions
    """

    def __init__(self):
        # WebSocket connections by session_id
        self.connections: Dict[str, Set[WebSocket]] = {}
        # Lock for thread-safe operations
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str):
        """
        Accept a new WebSocket connection.

        Args:
            websocket: WebSocket connection
            session_id: Research session identifier
        """
        await websocket.accept()

        async with self.lock:
            if session_id not in self.connections:
                self.connections[session_id] = set()
            self.connections[session_id].add(websocket)

        logger.info(f"[ResearchWS] Client connected to session {session_id} "
                   f"(total: {len(self.connections[session_id])} clients)")

    async def disconnect(self, websocket: WebSocket, session_id: str):
        """
        Remove a WebSocket connection.

        Args:
            websocket: WebSocket connection
            session_id: Research session identifier
        """
        async with self.lock:
            if session_id in self.connections:
                self.connections[session_id].discard(websocket)
                if not self.connections[session_id]:
                    del self.connections[session_id]

        logger.info(f"[ResearchWS] Client disconnected from session {session_id}")

    async def broadcast_event(self, session_id: str, event: Dict):
        """
        Broadcast an event to all clients in a session.

        Args:
            session_id: Research session identifier
            event: Event data to broadcast
        """
        if session_id not in self.connections:
            logger.warning(f"[ResearchWS] No connections found for session {session_id}")
            return

        # Get snapshot of connections
        async with self.lock:
            websockets = self.connections.get(session_id, set()).copy()

        logger.info(f"[ResearchWS] Broadcasting {event.get('type')} to {len(websockets)} clients in session {session_id}")

        # Broadcast to all (remove dead connections)
        dead_connections = []
        for websocket in websockets:
            try:
                await websocket.send_json(event)
            except Exception as e:
                logger.warning(f"[ResearchWS] Failed to send to client: {e}")
                dead_connections.append(websocket)

        # Clean up dead connections
        if dead_connections:
            async with self.lock:
                for websocket in dead_connections:
                    if session_id in self.connections:
                        self.connections[session_id].discard(websocket)

    async def broadcast_to_all(self, event: Dict):
        """
        Broadcast an event to all connected clients (all sessions).

        Args:
            event: Event data to broadcast
        """
        async with self.lock:
            all_sessions = list(self.connections.keys())

        for session_id in all_sessions:
            await self.broadcast_event(session_id, event)

    def get_active_sessions(self) -> List[str]:
        """Get list of active session IDs with connected clients."""
        return list(self.connections.keys())

    def get_client_count(self, session_id: str) -> int:
        """Get number of connected clients for a session."""
        return len(self.connections.get(session_id, set()))


# Global instance
research_ws_manager = ResearchWebSocketManager()
