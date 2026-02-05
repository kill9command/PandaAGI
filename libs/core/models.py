"""Pydantic models for PandaAI v2."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class ActionNeeded(str, Enum):
    """Phase 0 action classification (replaces old Intent enum).

    See: architecture/main-system-patterns/phase1-query-analyzer.md §4
    """

    LIVE_SEARCH = "live_search"
    RECALL_MEMORY = "recall_memory"
    ANSWER_FROM_CONTEXT = "answer_from_context"
    NAVIGATE_TO_SITE = "navigate_to_site"
    EXECUTE_CODE = "execute_code"
    UNCLEAR = "unclear"


class ReflectionDecision(str, Enum):
    """Phase 1 reflection decisions."""

    PROCEED = "PROCEED"
    CLARIFY = "CLARIFY"


class PlannerRoute(str, Enum):
    """Phase 3 routing decisions."""

    COORDINATOR = "coordinator"
    SYNTHESIS = "synthesis"
    CLARIFY = "clarify"


class PlannerAction(str, Enum):
    """Planner action decisions."""

    EXECUTE = "EXECUTE"
    COMPLETE = "COMPLETE"


class ValidationDecision(str, Enum):
    """Phase 7 validation decisions."""

    APPROVE = "APPROVE"
    REVISE = "REVISE"
    RETRY = "RETRY"
    FAIL = "FAIL"


class GoalStatus(str, Enum):
    """Multi-goal tracking status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


# =============================================================================
# Phase 0: Query Analysis
# =============================================================================

class ContentReference(BaseModel):
    """Reference to prior content.

    All fields except title and content_type are nullable — the LLM may
    not be able to resolve all fields for every reference.
    """

    title: str
    content_type: str  # "thread", "article", "product", "video", "post"
    site: Optional[str] = None
    source_turn: Optional[int] = None
    prior_findings: Optional[str] = None
    source_url: Optional[str] = None
    has_visit_record: bool = False
    visit_record_path: Optional[str] = None


class QueryAnalysis(BaseModel):
    """Phase 1 output: Query analysis result.

    Schema matches the active dataclass in libs/gateway/context/query_analyzer.py.
    See: architecture/main-system-patterns/phase1-query-analyzer.md §7
    See: architecture/contracts/phase_contracts.yaml Phase 0
    """

    original_query: str = ""
    resolved_query: str
    user_purpose: str = ""
    action_needed: Optional[str] = None  # ActionNeeded enum value for turn indexing
    data_requirements: dict[str, Any] = Field(default_factory=dict)
    reference_resolution: dict[str, Any] = Field(default_factory=dict)
    prior_context: dict[str, Any] = Field(default_factory=dict)  # Context from prior turns
    mode: str = "chat"  # "chat" | "code"
    was_resolved: bool = False
    content_reference: Optional[ContentReference] = None
    reasoning: str = ""
    validation: dict[str, Any] = Field(default_factory=dict)
    is_multi_task: bool = False
    task_breakdown: Optional[list[dict[str, Any]]] = None


# =============================================================================
# Phase 1: Reflection
# =============================================================================

class ReflectionResult(BaseModel):
    """Phase 1 output: Reflection decision."""

    decision: ReflectionDecision
    confidence: float = Field(ge=0.0, le=1.0)
    query_type: Optional[str] = None
    is_followup: bool = False
    reasoning: str


# =============================================================================
# Phase 2: Context Gathering
# =============================================================================

class ContextSource(BaseModel):
    """Source reference in gathered context."""

    path: str
    turn_number: Optional[int] = None
    relevance: float = Field(ge=0.0, le=1.0)
    summary: str


class GatheredContext(BaseModel):
    """Phase 2 output: Gathered context."""

    session_preferences: dict[str, Any] = Field(default_factory=dict)
    relevant_turns: list[ContextSource] = Field(default_factory=list)
    cached_research: Optional[dict[str, Any]] = None
    source_references: list[str] = Field(default_factory=list)
    sufficiency_assessment: str = ""


# =============================================================================
# Phase 3: Planning
# =============================================================================

class Goal(BaseModel):
    """Goal in multi-goal queries."""

    id: str
    description: str
    status: GoalStatus = GoalStatus.PENDING
    dependencies: list[str] = Field(default_factory=list)


class ToolRequest(BaseModel):
    """Tool request from Planner."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    goal_id: Optional[str] = None


class TaskPlan(BaseModel):
    """Phase 3 output: Task plan."""

    decision: PlannerAction
    route: Optional[PlannerRoute] = None
    goals: list[Goal] = Field(default_factory=list)
    current_focus: Optional[str] = None
    tool_requests: list[ToolRequest] = Field(default_factory=list)
    reasoning: str


# =============================================================================
# Phase 4: Coordination
# =============================================================================

class ToolResult(BaseModel):
    """Result from a tool execution."""

    tool: str
    goal_id: Optional[str] = None
    success: bool
    result: Any
    error: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class Claim(BaseModel):
    """Extracted claim with evidence."""

    claim: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    ttl_hours: Optional[int] = None


class ToolExecutionResult(BaseModel):
    """Phase 4 output: Tool execution result."""

    iteration: int
    action: str  # "TOOL_CALL" or "DONE"
    reasoning: str
    tool_results: list[ToolResult] = Field(default_factory=list)
    claims_extracted: list[Claim] = Field(default_factory=list)
    progress_summary: Optional[str] = None


# =============================================================================
# Phase 5: Synthesis
# =============================================================================

class SynthesisResult(BaseModel):
    """Phase 5 output: Synthesis result."""

    response_preview: str
    full_response: str
    citations: list[str] = Field(default_factory=list)
    validation_checklist: dict[str, bool] = Field(default_factory=dict)


# =============================================================================
# Phase 7: Validation
# =============================================================================

class ValidationCheck(BaseModel):
    """Individual validation check with optional granular scoring.

    The score/evidence/issues fields support the Poetiq-style soft scoring
    pattern where checks have granular confidence instead of just pass/fail.
    """

    name: str
    passed: bool
    score: float = Field(default=1.0, ge=0.0, le=1.0)  # Granular score (1.0 = perfect)
    evidence: list[str] = Field(default_factory=list)  # Supporting evidence for passing
    issues: list[str] = Field(default_factory=list)    # Specific problems found
    notes: Optional[str] = None


class GoalValidation(BaseModel):
    """Per-goal validation result."""

    goal_id: str
    addressed: bool
    quality: float = Field(ge=0.0, le=1.0)
    notes: Optional[str] = None


class ValidationResult(BaseModel):
    """Phase 7 output: Validation result.

    Includes best-seen tracking fields (Poetiq pattern) to preserve the
    highest-quality response across validation attempts, returning it on
    FAIL or max retries instead of the latest (potentially worse) response.
    """

    decision: ValidationDecision
    confidence: float = Field(ge=0.0, le=1.0)
    checks: list[ValidationCheck] = Field(default_factory=list)
    goal_validations: list[GoalValidation] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    revision_hints: Optional[str] = None
    overall_quality: Optional[float] = Field(ge=0.0, le=1.0, default=None)
    reasoning: Optional[str] = None  # Why this decision was made
    # Best-seen tracking (Poetiq pattern)
    best_response: Optional[str] = None           # Best response seen so far
    best_confidence: Optional[float] = None       # Confidence of best response
    attempt_number: int = 1                       # Current attempt number


# =============================================================================
# Turn Metadata
# =============================================================================

class TurnMetadata(BaseModel):
    """Metadata for a turn."""

    turn_number: int
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    topic: Optional[str] = None
    action_needed: Optional[str] = None  # ActionNeeded enum value from Phase 0
    quality: Optional[float] = Field(ge=0.0, le=1.0, default=None)
    turn_dir: str
    embedding_id: Optional[str] = None


# =============================================================================
# Intervention
# =============================================================================

class InterventionSeverity(str, Enum):
    """Intervention request severity."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class InterventionRequest(BaseModel):
    """Request for human intervention."""

    id: str = Field(default_factory=lambda: f"int_{datetime.now().strftime('%Y%m%d%H%M%S')}")
    timestamp: datetime = Field(default_factory=datetime.now)
    type: str
    severity: InterventionSeverity
    component: str
    context: dict[str, Any] = Field(default_factory=dict)
    error_details: str
    page_state: Optional[dict[str, Any]] = None
    recovery_attempted: bool = False
    recovery_result: Optional[str] = None
    suggested_action: Optional[str] = None
    model_used: Optional[str] = None
