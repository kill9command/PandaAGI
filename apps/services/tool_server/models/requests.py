"""
API Request/Response Models for PandaAI Orchestrator

Defines all HTTP API request and response models for the gateway endpoints.

Architecture Reference:
- architecture/services/user-interface.md Section 6.1 (API Endpoints)

Endpoints:
- POST /chat: Submit user message
- POST /inject: Inject message during research
- POST /intervention/resolve: Mark intervention as resolved
- GET /turns: List recent turns
- GET /turns/{id}: Get specific turn
- GET /status: System health
- GET /metrics: Observability metrics
- POST /memory: Store memory
- GET /memory/search: Search memories
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from .turn import Turn, TurnMetadata, TurnState, ValidationDecision


# =============================================================================
# Chat Endpoints
# =============================================================================


class ChatRequest(BaseModel):
    """
    Request body for POST /chat endpoint.

    Submits a user message to begin a new turn.
    """
    query: str = Field(
        min_length=1,
        max_length=10000,
        description="User's query text"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session ID to associate this turn with"
    )
    stream: bool = Field(
        default=True,
        description="Whether to stream the response via WebSocket"
    )
    context: Optional[dict[str, Any]] = Field(
        default=None,
        description="Additional context (attached files, selections, etc.)"
    )


class ChatResponse(BaseModel):
    """
    Response body for POST /chat endpoint.

    Returns immediately with turn_id; actual response streams via WebSocket.
    For non-streaming requests, includes the full response.
    """
    turn_id: int = Field(
        description="Unique identifier for this turn"
    )
    response: Optional[str] = Field(
        default=None,
        description="Full response text (only for non-streaming requests)"
    )
    quality: Optional[float] = Field(
        default=None,
        ge=0.0, le=1.0,
        description="Response quality score from validation"
    )
    validation: Optional[ValidationDecision] = Field(
        default=None,
        description="Final validation decision"
    )
    session_id: str = Field(
        description="Session ID for this turn"
    )


# =============================================================================
# Inject Endpoint
# =============================================================================


class InjectRequest(BaseModel):
    """
    Request body for POST /inject endpoint.

    Injects a message during active research to modify behavior.
    Examples: "skip walmart", "focus on laptops under $700"
    """
    message: str = Field(
        min_length=1,
        max_length=1000,
        description="Message to inject (e.g., 'skip walmart', 'focus on price')"
    )
    turn_id: Optional[int] = Field(
        default=None,
        description="Turn ID to inject into (defaults to current active turn)"
    )


class InjectResponse(BaseModel):
    """Response body for POST /inject endpoint."""
    success: bool = Field(
        description="Whether the injection was accepted"
    )
    turn_id: int = Field(
        description="Turn ID that received the injection"
    )
    message: str = Field(
        description="Confirmation or error message"
    )


# =============================================================================
# Intervention Endpoint
# =============================================================================


class InterventionResolveRequest(BaseModel):
    """
    Request body for POST /intervention/resolve endpoint.

    Marks an intervention (CAPTCHA, login, etc.) as resolved.
    """
    intervention_id: str = Field(
        description="ID of the intervention to resolve"
    )
    success: bool = Field(
        default=True,
        description="Whether the intervention was successfully resolved"
    )


class InterventionResolveResponse(BaseModel):
    """Response body for POST /intervention/resolve endpoint."""
    success: bool = Field(
        description="Whether the resolution was processed"
    )
    message: str = Field(
        description="Confirmation or error message"
    )
    research_resumed: bool = Field(
        default=False,
        description="Whether research has resumed"
    )


# =============================================================================
# Turns Endpoints
# =============================================================================


class TurnSummary(BaseModel):
    """Summary of a turn for list views."""
    turn_id: int = Field(description="Turn ID")
    session_id: str = Field(description="Session ID")
    query: str = Field(description="Original user query")
    state: TurnState = Field(description="Current turn state")
    quality: Optional[float] = Field(default=None, description="Quality score")
    validation: Optional[str] = Field(default=None, description="Validation decision")
    created_at: datetime = Field(description="Creation timestamp")
    completed_at: Optional[datetime] = Field(default=None, description="Completion timestamp")
    duration_ms: Optional[int] = Field(default=None, description="Total duration")


class TurnListResponse(BaseModel):
    """
    Response body for GET /turns endpoint.

    Lists recent turns with optional filtering.
    """
    turns: list[TurnSummary] = Field(
        description="List of turn summaries"
    )
    total: int = Field(
        ge=0,
        description="Total number of turns matching filter"
    )
    page: int = Field(
        default=1,
        ge=1,
        description="Current page number"
    )
    page_size: int = Field(
        default=20,
        ge=1, le=100,
        description="Number of turns per page"
    )


class TurnDetailResponse(BaseModel):
    """
    Response body for GET /turns/{id} endpoint.

    Returns full turn details including all phase results.
    """
    turn: Turn = Field(
        description="Complete turn data"
    )


# =============================================================================
# Status Endpoint
# =============================================================================


class ModelStatus(BaseModel):
    """Status of a loaded model."""
    name: str = Field(description="Model name")
    role: str = Field(description="Model role (MIND, EYES, etc.)")
    loaded: bool = Field(description="Whether model is currently loaded")
    temperature: Optional[float] = Field(default=None, description="Current temperature setting")
    vram_mb: Optional[int] = Field(default=None, ge=0, description="VRAM usage in MB")


class SystemState(str, Enum):
    """Overall system state."""
    IDLE = "idle"
    PROCESSING = "processing"
    RESEARCHING = "researching"
    WAITING_INTERVENTION = "waiting_intervention"
    ERROR = "error"
    STARTING = "starting"
    STOPPING = "stopping"


class StatusResponse(BaseModel):
    """
    Response body for GET /status endpoint.

    Returns system health and current state.
    """
    state: SystemState = Field(
        description="Current system state"
    )
    models: list[ModelStatus] = Field(
        default_factory=list,
        description="Status of loaded models"
    )
    current_turn: Optional[int] = Field(
        default=None,
        description="Currently processing turn ID"
    )
    current_phase: Optional[int] = Field(
        default=None,
        description="Currently executing phase (0-7)"
    )
    uptime_seconds: int = Field(
        ge=0,
        description="System uptime in seconds"
    )
    version: str = Field(
        description="Orchestrator version"
    )
    services: dict[str, bool] = Field(
        default_factory=dict,
        description="Health status of dependent services"
    )


# =============================================================================
# Metrics Endpoint
# =============================================================================


class TokenUsage(BaseModel):
    """Token usage statistics."""
    total: int = Field(ge=0, description="Total tokens used")
    input: int = Field(ge=0, description="Input tokens")
    output: int = Field(ge=0, description="Output tokens")
    by_model: dict[str, int] = Field(
        default_factory=dict,
        description="Tokens by model name"
    )
    by_phase: dict[str, int] = Field(
        default_factory=dict,
        description="Tokens by phase name"
    )


class TurnStats(BaseModel):
    """Turn processing statistics."""
    total: int = Field(ge=0, description="Total turns processed")
    completed: int = Field(ge=0, description="Successfully completed turns")
    failed: int = Field(ge=0, description="Failed turns")
    cancelled: int = Field(ge=0, description="Cancelled turns")
    avg_duration_ms: Optional[float] = Field(
        default=None,
        description="Average turn duration in ms"
    )
    avg_quality: Optional[float] = Field(
        default=None,
        ge=0.0, le=1.0,
        description="Average quality score"
    )


class ResearchStats(BaseModel):
    """Research (Phase 4) statistics."""
    total_research_tasks: int = Field(ge=0, description="Total research tasks executed")
    vendors_visited: int = Field(ge=0, description="Total vendor pages visited")
    products_found: int = Field(ge=0, description="Total products discovered")
    interventions_required: int = Field(ge=0, description="Number of interventions required")
    interventions_resolved: int = Field(ge=0, description="Number of interventions resolved")
    avg_research_duration_ms: Optional[float] = Field(
        default=None,
        description="Average research duration in ms"
    )
    by_vendor: dict[str, int] = Field(
        default_factory=dict,
        description="Products found by vendor"
    )


class ValidationStats(BaseModel):
    """Validation (Phase 6) statistics."""
    total_validations: int = Field(ge=0, description="Total validations performed")
    approvals: int = Field(ge=0, description="APPROVE decisions")
    revisions: int = Field(ge=0, description="REVISE decisions")
    retries: int = Field(ge=0, description="RETRY decisions")
    failures: int = Field(ge=0, description="FAIL decisions")
    avg_confidence: Optional[float] = Field(
        default=None,
        ge=0.0, le=1.0,
        description="Average confidence score"
    )


class MetricsResponse(BaseModel):
    """
    Response body for GET /metrics endpoint.

    Returns observability metrics for the current period.
    """
    period_start: datetime = Field(
        description="Start of metrics period"
    )
    period_end: datetime = Field(
        description="End of metrics period"
    )
    tokens: TokenUsage = Field(
        description="Token usage statistics"
    )
    turns: TurnStats = Field(
        description="Turn processing statistics"
    )
    research: ResearchStats = Field(
        description="Research statistics"
    )
    validation: ValidationStats = Field(
        description="Validation statistics"
    )


# =============================================================================
# Memory Endpoints
# =============================================================================


class MemoryCategory(str, Enum):
    """Categories for stored memories."""
    PREFERENCE = "preference"
    FACT = "fact"
    CONTEXT = "context"
    INSTRUCTION = "instruction"


class MemoryRequest(BaseModel):
    """
    Request body for POST /memory endpoint.

    Stores a new memory for future context retrieval.
    """
    content: str = Field(
        min_length=1,
        max_length=5000,
        description="Memory content to store"
    )
    category: MemoryCategory = Field(
        default=MemoryCategory.FACT,
        description="Memory category"
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for memory retrieval"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session to associate memory with"
    )


class Memory(BaseModel):
    """A stored memory item."""
    id: str = Field(description="Unique memory ID")
    content: str = Field(description="Memory content")
    category: MemoryCategory = Field(description="Memory category")
    tags: list[str] = Field(default_factory=list, description="Memory tags")
    created_at: datetime = Field(description="Creation timestamp")
    session_id: Optional[str] = Field(default=None, description="Associated session")
    relevance_score: Optional[float] = Field(
        default=None,
        ge=0.0, le=1.0,
        description="Relevance score (for search results)"
    )


class MemoryResponse(BaseModel):
    """Response body for POST /memory endpoint."""
    success: bool = Field(description="Whether memory was stored")
    memory_id: str = Field(description="ID of stored memory")
    message: str = Field(description="Confirmation message")


class MemorySearchRequest(BaseModel):
    """Request body for GET /memory/search endpoint."""
    query: str = Field(
        min_length=1,
        max_length=1000,
        description="Search query"
    )
    category: Optional[MemoryCategory] = Field(
        default=None,
        description="Filter by category"
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Filter by tags"
    )
    limit: int = Field(
        default=10,
        ge=1, le=50,
        description="Maximum results to return"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Filter by session"
    )


class MemorySearchResponse(BaseModel):
    """Response body for GET /memory/search endpoint."""
    memories: list[Memory] = Field(
        description="Matching memories sorted by relevance"
    )
    total: int = Field(
        ge=0,
        description="Total matching memories"
    )


class MemoryDeleteRequest(BaseModel):
    """Request body for DELETE /memory endpoint."""
    memory_id: Optional[str] = Field(
        default=None,
        description="Specific memory ID to delete"
    )
    query: Optional[str] = Field(
        default=None,
        description="Query to match memories for deletion"
    )
    category: Optional[MemoryCategory] = Field(
        default=None,
        description="Delete all memories in category"
    )


class MemoryDeleteResponse(BaseModel):
    """Response body for DELETE /memory endpoint."""
    success: bool = Field(description="Whether deletion succeeded")
    deleted_count: int = Field(ge=0, description="Number of memories deleted")
    message: str = Field(description="Confirmation message")
