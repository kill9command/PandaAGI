"""
WebSocket Event Types Re-exports and Helpers.

Architecture Reference:
    architecture/services/user-interface.md Section 6.2 (WebSocket Events)

This module re-exports all event types from apps.services.orchestrator.models.events
and provides helper functions for creating events.

Example:
    from apps.services.orchestrator.events.types import (
        create_event,
        PhaseStartedEvent,
        ResearchProgressEvent,
        EventType,
    )

    # Create events using the helper
    event = create_event("phase_started", phase=0, name="query_analyzer")

    # Or use the class directly
    event = PhaseStartedEvent(phase=0, name="query_analyzer")
"""

from typing import Any, Optional

from apps.services.orchestrator.models.events import (
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
)

# Re-export all public symbols
__all__ = [
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
    # Helpers from models.events
    "PHASE_NAMES",
    "get_phase_name",
    # Local helpers
    "create_event",
]

# Event type to class mapping
_EVENT_CLASSES = {
    "turn_started": TurnStartedEvent,
    "phase_started": PhaseStartedEvent,
    "phase_completed": PhaseCompletedEvent,
    "research_progress": ResearchProgressEvent,
    "product_found": ProductFoundEvent,
    "intervention_required": InterventionRequiredEvent,
    "response_chunk": ResponseChunkEvent,
    "response_complete": ResponseCompleteEvent,
    "turn_complete": TurnCompleteEvent,
    "error": ErrorEvent,
}


def create_event(event_type: str, **kwargs: Any) -> WebSocketEvent:
    """Create a WebSocket event by type name.

    This is a convenience function for creating events when the type
    is determined dynamically (e.g., from configuration or string input).

    Args:
        event_type: Event type string (e.g., "phase_started", "error")
        **kwargs: Event-specific parameters

    Returns:
        A WebSocketEvent instance of the appropriate type

    Raises:
        ValueError: If event_type is not recognized

    Example:
        # Create a phase started event
        event = create_event(
            "phase_started",
            phase=0,
            name="query_analyzer",
            turn_id=42,
        )

        # Create an error event
        event = create_event(
            "error",
            message="Research timeout exceeded",
            code="TIMEOUT",
            recoverable=True,
        )

        # Create a research progress event
        event = create_event(
            "research_progress",
            vendor="bestbuy.com",
            status="visiting",
        )
    """
    event_class = _EVENT_CLASSES.get(event_type)

    if event_class is None:
        valid_types = ", ".join(sorted(_EVENT_CLASSES.keys()))
        raise ValueError(
            f"Unknown event type: '{event_type}'. "
            f"Valid types are: {valid_types}"
        )

    return event_class(**kwargs)


def create_phase_started(
    phase: int,
    turn_id: Optional[int] = None,
    attempt: int = 1,
) -> PhaseStartedEvent:
    """Create a phase started event with automatic name lookup.

    Args:
        phase: Phase number (0-7)
        turn_id: Optional turn ID
        attempt: Attempt number (default 1)

    Returns:
        PhaseStartedEvent with name automatically populated
    """
    return PhaseStartedEvent(
        phase=phase,
        name=get_phase_name(phase),
        turn_id=turn_id,
        attempt=attempt,
    )


def create_phase_completed(
    phase: int,
    duration_ms: int,
    turn_id: Optional[int] = None,
    success: bool = True,
    output_summary: Optional[str] = None,
) -> PhaseCompletedEvent:
    """Create a phase completed event with automatic name lookup.

    Args:
        phase: Phase number (0-7)
        duration_ms: Phase duration in milliseconds
        turn_id: Optional turn ID
        success: Whether phase completed successfully
        output_summary: Optional brief summary of output

    Returns:
        PhaseCompletedEvent with name automatically populated
    """
    return PhaseCompletedEvent(
        phase=phase,
        name=get_phase_name(phase),
        duration_ms=duration_ms,
        turn_id=turn_id,
        success=success,
        output_summary=output_summary,
    )


def create_research_progress(
    vendor: str,
    status: str,
    products: Optional[int] = None,
    turn_id: Optional[int] = None,
    error: Optional[str] = None,
) -> ResearchProgressEvent:
    """Create a research progress event.

    Args:
        vendor: Vendor domain (e.g., "bestbuy.com")
        status: Status string ("pending", "visiting", "done", "failed", "skipped")
        products: Number of products found (when status is "done")
        turn_id: Optional turn ID
        error: Error message (when status is "failed")

    Returns:
        ResearchProgressEvent
    """
    return ResearchProgressEvent(
        vendor=vendor,
        status=ResearchStatus(status),
        products=products,
        turn_id=turn_id,
        error=error,
    )
