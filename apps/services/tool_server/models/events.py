"""
WebSocket Event Models for PandaAI Orchestrator

Defines all WebSocket event types for real-time communication between
the orchestrator/gateway and clients (VSCode extension, CLI).

Architecture Reference:
- architecture/services/user-interface.md Section 6.2 (WebSocket Events)

Server -> Client Events:
- turn_started: Turn processing has begun
- phase_started: A phase has started executing
- phase_completed: A phase has finished
- research_progress: Vendor research status update
- product_found: A product was discovered during research
- intervention_required: Human intervention needed (CAPTCHA, etc)
- response_chunk: Streaming response content
- response_complete: Response generation finished
- turn_complete: Turn processing finished
- error: Error occurred

Client -> Server Messages (not modeled here, handled by gateway):
- message: User sends a chat message
- inject: User injects a message during research
- cancel: User cancels current operation
- intervention_resolved: User resolved an intervention
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """WebSocket event types from server to client."""
    TURN_STARTED = "turn_started"
    PHASE_STARTED = "phase_started"
    PHASE_COMPLETED = "phase_completed"
    RESEARCH_PROGRESS = "research_progress"
    PRODUCT_FOUND = "product_found"
    INTERVENTION_REQUIRED = "intervention_required"
    RESPONSE_CHUNK = "response_chunk"
    RESPONSE_COMPLETE = "response_complete"
    TURN_COMPLETE = "turn_complete"
    ERROR = "error"


class ResearchStatus(str, Enum):
    """Status of vendor research progress."""
    PENDING = "pending"
    VISITING = "visiting"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class InterventionType(str, Enum):
    """
    Types of interventions that may be required.

    From architecture/services/user-interface.md Section 7.4:
    - captcha_recaptcha: reCAPTCHA iframe detected
    - captcha_hcaptcha: hCaptcha iframe detected
    - cloudflare: Cloudflare challenge page
    - login_required: Login form detected
    - age_verification: Age gate detected
    - region_blocked: Region restriction
    """
    CAPTCHA_RECAPTCHA = "captcha_recaptcha"
    CAPTCHA_HCAPTCHA = "captcha_hcaptcha"
    CLOUDFLARE = "cloudflare"
    LOGIN_REQUIRED = "login_required"
    AGE_VERIFICATION = "age_verification"
    REGION_BLOCKED = "region_blocked"
    # Generic captcha for backwards compatibility
    CAPTCHA = "captcha"


class BaseEvent(BaseModel):
    """Base class for all WebSocket events."""
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Event timestamp"
    )

    class Config:
        use_enum_values = True


class TurnStartedEvent(BaseEvent):
    """
    Emitted when a new turn begins processing.

    Example: { type: "turn_started", turn_id: 43 }
    """
    type: Literal["turn_started"] = "turn_started"
    turn_id: int = Field(
        description="Unique identifier for this turn"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier"
    )


class PhaseStartedEvent(BaseEvent):
    """
    Emitted when a pipeline phase begins.

    Example: { type: "phase_started", phase: 0, name: "query_analyzer" }
    """
    type: Literal["phase_started"] = "phase_started"
    phase: int = Field(
        ge=0, le=8,
        description="Phase number (0-8)"
    )
    name: str = Field(
        description="Phase name (e.g., 'query_analyzer', 'reflection')"
    )
    turn_id: Optional[int] = Field(
        default=None,
        description="Associated turn ID"
    )
    attempt: int = Field(
        default=1,
        ge=1,
        description="Attempt number for this phase (for REVISE/RETRY loops)"
    )


class PhaseCompletedEvent(BaseEvent):
    """
    Emitted when a pipeline phase completes.

    Example: { type: "phase_completed", phase: 0, duration_ms: 450 }
    """
    type: Literal["phase_completed"] = "phase_completed"
    phase: int = Field(
        ge=0, le=8,
        description="Phase number (0-8)"
    )
    name: str = Field(
        description="Phase name"
    )
    duration_ms: int = Field(
        ge=0,
        description="Phase execution duration in milliseconds"
    )
    turn_id: Optional[int] = Field(
        default=None,
        description="Associated turn ID"
    )
    success: bool = Field(
        default=True,
        description="Whether the phase completed successfully"
    )
    output_summary: Optional[str] = Field(
        default=None,
        description="Brief summary of phase output"
    )


class ResearchProgressEvent(BaseEvent):
    """
    Emitted during Phase 4 (Coordinator) to report vendor research progress.

    Examples:
    - { type: "research_progress", vendor: "bestbuy.com", status: "visiting" }
    - { type: "research_progress", vendor: "bestbuy.com", status: "done", products: 3 }
    """
    type: Literal["research_progress"] = "research_progress"
    vendor: str = Field(
        description="Vendor domain being researched (e.g., 'bestbuy.com')"
    )
    status: ResearchStatus = Field(
        description="Current status of this vendor's research"
    )
    products: Optional[int] = Field(
        default=None,
        ge=0,
        description="Number of products found (when status is 'done')"
    )
    turn_id: Optional[int] = Field(
        default=None,
        description="Associated turn ID"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if status is 'failed'"
    )


class ProductFoundEvent(BaseEvent):
    """
    Emitted when a product is discovered during research.

    Example: { type: "product_found", product: { name: "HP Victus", price: 649, ... } }
    """
    type: Literal["product_found"] = "product_found"
    product: dict[str, Any] = Field(
        description="Product data (name, price, vendor, url, specs, etc.)"
    )
    turn_id: Optional[int] = Field(
        default=None,
        description="Associated turn ID"
    )
    vendor: Optional[str] = Field(
        default=None,
        description="Source vendor for this product"
    )


class InterventionRequiredEvent(BaseEvent):
    """
    Emitted when human intervention is required (CAPTCHA, login, etc).

    Example: { type: "intervention_required", intervention_id: "abc123", type: "captcha", url: "..." }

    From architecture/services/user-interface.md Section 7:
    - Research pauses, browser stays on blocked page
    - User clicks "Open Browser" to focus Playwright window
    - User solves CAPTCHA directly
    - User clicks "Done" in VSCode/CLI
    - Research continues
    """
    type: Literal["intervention_required"] = "intervention_required"
    intervention_id: str = Field(
        description="Unique identifier for this intervention request"
    )
    intervention_type: InterventionType = Field(
        alias="type_of_intervention",
        description="Type of intervention required"
    )
    url: str = Field(
        description="URL where intervention is needed"
    )
    turn_id: Optional[int] = Field(
        default=None,
        description="Associated turn ID"
    )
    vendor: Optional[str] = Field(
        default=None,
        description="Vendor domain requiring intervention"
    )
    screenshot_path: Optional[str] = Field(
        default=None,
        description="Path to screenshot of the blocker page"
    )
    timeout_seconds: int = Field(
        default=300,
        description="Seconds until intervention times out (default 5 minutes)"
    )

    class Config:
        populate_by_name = True


class ResponseChunkEvent(BaseEvent):
    """
    Emitted during streaming response generation.

    Example: { type: "response_chunk", content: "I found 3 laptops..." }
    """
    type: Literal["response_chunk"] = "response_chunk"
    content: str = Field(
        description="Chunk of response content"
    )
    turn_id: Optional[int] = Field(
        default=None,
        description="Associated turn ID"
    )
    is_final: bool = Field(
        default=False,
        description="Whether this is the final chunk"
    )


class ResponseCompleteEvent(BaseEvent):
    """
    Emitted when response generation is complete.

    Example: { type: "response_complete", quality: 0.87 }
    """
    type: Literal["response_complete"] = "response_complete"
    quality: float = Field(
        ge=0.0, le=1.0,
        description="Response quality score from validation"
    )
    tokens: Optional[int] = Field(
        default=None,
        ge=0,
        description="Total tokens used for response generation"
    )
    turn_id: Optional[int] = Field(
        default=None,
        description="Associated turn ID"
    )


class TurnCompleteEvent(BaseEvent):
    """
    Emitted when turn processing is fully complete.

    Example: { type: "turn_complete", turn_id: 43, validation: "APPROVE" }
    """
    type: Literal["turn_complete"] = "turn_complete"
    turn_id: int = Field(
        description="Completed turn ID"
    )
    validation: str = Field(
        description="Final validation decision (APPROVE, FAIL, etc.)"
    )
    quality: Optional[float] = Field(
        default=None,
        ge=0.0, le=1.0,
        description="Final quality score"
    )
    total_duration_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Total turn duration in milliseconds"
    )
    tokens_used: Optional[int] = Field(
        default=None,
        ge=0,
        description="Total tokens used across all phases"
    )


class ErrorEvent(BaseEvent):
    """
    Emitted when an error occurs during processing.

    Example: { type: "error", message: "Research timeout exceeded" }
    """
    type: Literal["error"] = "error"
    message: str = Field(
        description="Human-readable error message"
    )
    code: Optional[str] = Field(
        default=None,
        description="Error code for programmatic handling"
    )
    turn_id: Optional[int] = Field(
        default=None,
        description="Associated turn ID (if applicable)"
    )
    phase: Optional[int] = Field(
        default=None,
        ge=0, le=8,
        description="Phase where error occurred (if applicable)"
    )
    recoverable: bool = Field(
        default=False,
        description="Whether the error can be recovered from"
    )
    details: Optional[dict[str, Any]] = Field(
        default=None,
        description="Additional error details for debugging"
    )


# Union type for all WebSocket events (for type checking and serialization)
WebSocketEvent = Annotated[
    Union[
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
    ],
    Field(discriminator="type")
]


from apps.phases import PHASE_NAMES


def get_phase_name(phase: int) -> str:
    """Get the canonical name for a phase number."""
    return PHASE_NAMES.get(phase, f"unknown_phase_{phase}")
