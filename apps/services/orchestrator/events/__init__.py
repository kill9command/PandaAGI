"""
PandaAI Orchestrator Events Package.

Architecture Reference:
    architecture/services/user-interface.md Section 6.2 (WebSocket Events)

This package provides:
- EventEmitter: Manages WebSocket connections and broadcasts events
- Event types: All WebSocket event models for type-safe event handling
- Helper functions: create_event() and convenience constructors

Example usage:

    from apps.services.orchestrator.events import (
        EventEmitter,
        get_event_emitter,
        create_event,
        PhaseStartedEvent,
        ResearchProgressEvent,
    )

    # Get the singleton emitter
    emitter = get_event_emitter()

    # Connect a WebSocket
    await emitter.connect(turn_id, websocket)

    # Emit events from pipeline
    await emitter.emit(turn_id, PhaseStartedEvent(phase=0, name="query_analyzer"))

    # Or use the helper
    await emitter.emit(turn_id, create_event("phase_completed", phase=0, duration_ms=450))

    # Stream events to client
    async for event in emitter.stream_events(turn_id):
        await websocket.send_json(event.model_dump())
"""

from apps.services.orchestrator.events.emitter import (
    EventEmitter,
    get_event_emitter,
)

from apps.services.orchestrator.events.types import (
    # Enums
    EventType,
    ResearchStatus,
    InterventionType,
    # Base
    BaseEvent,
    # Event types
    TurnStartedEvent,
    PhaseStartedEvent,
    PhaseCompletedEvent,
    ResearchProgressEvent,
    ProductFoundEvent,
    InterventionRequiredEvent,
    ResponseChunkEvent,
    ResponseCompleteEvent,
    TurnCompleteEvent,
    ErrorEvent,
    # Union type
    WebSocketEvent,
    # Helpers
    PHASE_NAMES,
    get_phase_name,
    create_event,
    create_phase_started,
    create_phase_completed,
    create_research_progress,
)

__all__ = [
    # Emitter
    "EventEmitter",
    "get_event_emitter",
    # Enums
    "EventType",
    "ResearchStatus",
    "InterventionType",
    # Base
    "BaseEvent",
    # Event types
    "TurnStartedEvent",
    "PhaseStartedEvent",
    "PhaseCompletedEvent",
    "ResearchProgressEvent",
    "ProductFoundEvent",
    "InterventionRequiredEvent",
    "ResponseChunkEvent",
    "ResponseCompleteEvent",
    "TurnCompleteEvent",
    "ErrorEvent",
    # Union type
    "WebSocketEvent",
    # Helpers
    "PHASE_NAMES",
    "get_phase_name",
    "create_event",
    "create_phase_started",
    "create_phase_completed",
    "create_research_progress",
]
