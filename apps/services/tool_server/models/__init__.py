"""
Orchestrator Pydantic Models

This package contains all data models for the PandaAI orchestrator:
- turn.py: Turn state, metadata, phase results, validation
- events.py: WebSocket event types (Server -> Client)
- requests.py: API request/response models
"""

from .turn import (
    Turn,
    TurnState,
    TurnMetadata,
    PhaseResult,
    PhaseStatus,
    ValidationResult,
    ValidationDecision,
    ValidationChecks,
)

from .events import (
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
    WebSocketEvent,
)

from .requests import (
    ChatRequest,
    ChatResponse,
    InjectRequest,
    TurnListResponse,
    StatusResponse,
    MetricsResponse,
    MemoryRequest,
    MemorySearchResponse,
    Memory,
    ModelStatus,
    ResearchStats,
)

__all__ = [
    # Turn models
    "Turn",
    "TurnState",
    "TurnMetadata",
    "PhaseResult",
    "PhaseStatus",
    "ValidationResult",
    "ValidationDecision",
    "ValidationChecks",
    # Event models
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
    "WebSocketEvent",
    # Request/Response models
    "ChatRequest",
    "ChatResponse",
    "InjectRequest",
    "TurnListResponse",
    "StatusResponse",
    "MetricsResponse",
    "MemoryRequest",
    "MemorySearchResponse",
    "Memory",
    "ModelStatus",
    "ResearchStats",
]
