"""
Event Emitter for WebSocket Streaming in PandaAI Orchestrator.

Architecture Reference:
    architecture/services/user-interface.md Section 6.2 (WebSocket Events)

This module provides the EventEmitter class for managing WebSocket connections
and broadcasting events to connected clients during pipeline execution.

Usage pattern:
1. WebSocket handler connects, registers for a turn_id
2. Pipeline runs, pushes events to queue via `emitter.emit(turn_id, event)`
3. WebSocket handler reads from queue and sends to client

Example:
    emitter = EventEmitter()

    # WebSocket handler
    async def websocket_handler(websocket, turn_id):
        await emitter.connect(turn_id, websocket)
        try:
            async for event in emitter.stream_events(turn_id):
                await websocket.send_json(event.model_dump())
        finally:
            await emitter.disconnect(turn_id)

    # Pipeline pushing events
    await emitter.emit(turn_id, PhaseStartedEvent(phase=0, name="query_analyzer"))
"""

import asyncio
import logging
from typing import AsyncIterator, Optional

from fastapi import WebSocket

from apps.services.tool_server.models.events import (
    WebSocketEvent,
    ErrorEvent,
)

logger = logging.getLogger(__name__)


class EventEmitter:
    """Manages WebSocket connections and broadcasts events.

    This class maintains a registry of WebSocket connections indexed by turn_id,
    along with corresponding event queues. Pipeline phases push events to queues,
    and WebSocket handlers consume them for streaming to clients.

    Thread Safety:
        Uses asyncio locks to protect concurrent access to connection and queue
        registries. Safe to use from multiple coroutines.

    Event Flow:
        1. Client connects via WebSocket
        2. Handler calls connect(turn_id, websocket) to register
        3. Pipeline emits events via emit(turn_id, event)
        4. Events queue up in per-turn queues
        5. Handler iterates stream_events(turn_id) to get events
        6. Handler sends events to client
        7. On completion, handler calls disconnect(turn_id)
    """

    # Sentinel value to signal stream end
    _STREAM_END = object()

    def __init__(self):
        """Initialize the event emitter."""
        self._connections: dict[str, WebSocket] = {}  # turn_id -> websocket
        self._queues: dict[str, asyncio.Queue] = {}   # turn_id -> event queue
        self._lock = asyncio.Lock()

    async def connect(self, turn_id: str, websocket: WebSocket) -> None:
        """Register a WebSocket connection for a turn.

        Creates an event queue for this turn and stores the WebSocket reference.
        If a connection already exists for this turn_id, it will be replaced.

        Args:
            turn_id: Unique identifier for the turn (can be int converted to str)
            websocket: FastAPI WebSocket instance
        """
        turn_key = str(turn_id)

        async with self._lock:
            # Clean up existing connection if present
            if turn_key in self._connections:
                logger.warning(f"Replacing existing connection for turn {turn_key}")

            self._connections[turn_key] = websocket
            self._queues[turn_key] = asyncio.Queue()

        logger.info(f"WebSocket connected for turn {turn_key}")

    async def disconnect(self, turn_id: str) -> None:
        """Remove WebSocket connection for a turn.

        Cleans up the connection and queue for the specified turn.
        Safe to call even if no connection exists.

        Args:
            turn_id: Turn identifier to disconnect
        """
        turn_key = str(turn_id)

        async with self._lock:
            if turn_key in self._connections:
                del self._connections[turn_key]

            if turn_key in self._queues:
                # Signal end of stream to any waiting consumers
                queue = self._queues[turn_key]
                try:
                    queue.put_nowait(self._STREAM_END)
                except asyncio.QueueFull:
                    pass
                del self._queues[turn_key]

        logger.info(f"WebSocket disconnected for turn {turn_key}")

    async def emit(self, turn_id: str, event: WebSocketEvent) -> bool:
        """Send an event to the connected WebSocket for a turn.

        Queues the event for delivery to the client. The event will be
        picked up by stream_events() for actual transmission.

        Args:
            turn_id: Turn identifier to send event to
            event: WebSocketEvent to send

        Returns:
            True if event was queued successfully, False if no connection exists
        """
        turn_key = str(turn_id)

        async with self._lock:
            queue = self._queues.get(turn_key)

            if queue is None:
                logger.debug(f"No queue for turn {turn_key}, event dropped: {event.type}")
                return False

            try:
                queue.put_nowait(event)
                logger.debug(f"Emitted {event.type} event for turn {turn_key}")
                return True
            except asyncio.QueueFull:
                logger.warning(f"Queue full for turn {turn_key}, event dropped: {event.type}")
                return False

    async def emit_to_all(self, event: WebSocketEvent) -> int:
        """Broadcast an event to all connected WebSockets.

        Useful for system-wide notifications like server shutdown warnings.

        Args:
            event: WebSocketEvent to broadcast

        Returns:
            Number of connections the event was sent to
        """
        async with self._lock:
            turn_keys = list(self._queues.keys())

        sent_count = 0
        for turn_key in turn_keys:
            if await self.emit(turn_key, event):
                sent_count += 1

        logger.debug(f"Broadcast {event.type} to {sent_count} connections")
        return sent_count

    def get_queue(self, turn_id: str) -> Optional[asyncio.Queue]:
        """Get the event queue for a turn.

        This allows direct queue access for advanced use cases where
        pipeline components need to push events without going through emit().

        Args:
            turn_id: Turn identifier

        Returns:
            asyncio.Queue for the turn, or None if not connected
        """
        turn_key = str(turn_id)
        return self._queues.get(turn_key)

    async def stream_events(self, turn_id: str) -> AsyncIterator[WebSocketEvent]:
        """Yield events from the queue for a turn.

        This is an async generator that yields events as they arrive.
        It will continue until:
        - The turn is disconnected
        - A _STREAM_END sentinel is received
        - The queue is removed

        Args:
            turn_id: Turn identifier to stream events for

        Yields:
            WebSocketEvent instances as they arrive

        Example:
            async for event in emitter.stream_events(turn_id):
                await websocket.send_json(event.model_dump())
        """
        turn_key = str(turn_id)

        while True:
            # Get queue under lock (it might be removed during streaming)
            async with self._lock:
                queue = self._queues.get(turn_key)

            if queue is None:
                logger.debug(f"Stream ended for turn {turn_key}: queue removed")
                break

            try:
                # Wait for next event with timeout to allow checking queue existence
                event = await asyncio.wait_for(queue.get(), timeout=1.0)

                if event is self._STREAM_END:
                    logger.debug(f"Stream ended for turn {turn_key}: end sentinel")
                    break

                yield event

            except asyncio.TimeoutError:
                # Check if connection still exists
                async with self._lock:
                    if turn_key not in self._queues:
                        logger.debug(f"Stream ended for turn {turn_key}: disconnected")
                        break
                # Continue waiting for events
                continue

    async def end_stream(self, turn_id: str) -> None:
        """Signal the end of the event stream for a turn.

        This puts the end sentinel in the queue to gracefully terminate
        stream_events() without disconnecting the WebSocket.

        Args:
            turn_id: Turn identifier to end stream for
        """
        turn_key = str(turn_id)

        async with self._lock:
            queue = self._queues.get(turn_key)
            if queue is not None:
                try:
                    queue.put_nowait(self._STREAM_END)
                    logger.debug(f"Signaled stream end for turn {turn_key}")
                except asyncio.QueueFull:
                    pass

    def is_connected(self, turn_id: str) -> bool:
        """Check if a WebSocket is connected for a turn.

        Args:
            turn_id: Turn identifier to check

        Returns:
            True if connected, False otherwise
        """
        return str(turn_id) in self._connections

    def get_connected_turns(self) -> list[str]:
        """Get list of all connected turn IDs.

        Returns:
            List of turn_id strings with active connections
        """
        return list(self._connections.keys())

    async def emit_error(
        self,
        turn_id: str,
        message: str,
        code: Optional[str] = None,
        phase: Optional[int] = None,
        recoverable: bool = False,
    ) -> bool:
        """Convenience method to emit an error event.

        Args:
            turn_id: Turn identifier
            message: Human-readable error message
            code: Optional error code
            phase: Optional phase number where error occurred
            recoverable: Whether the error can be recovered from

        Returns:
            True if emitted successfully
        """
        event = ErrorEvent(
            message=message,
            code=code,
            turn_id=int(turn_id) if turn_id.isdigit() else None,
            phase=phase,
            recoverable=recoverable,
        )
        return await self.emit(turn_id, event)


# Module-level singleton instance
_emitter: Optional[EventEmitter] = None


def get_event_emitter() -> EventEmitter:
    """Get the singleton EventEmitter instance.

    Returns:
        The global EventEmitter instance
    """
    global _emitter
    if _emitter is None:
        _emitter = EventEmitter()
    return _emitter
