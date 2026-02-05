"""Phase API Request/Response Schemas for n8n Integration.

Architecture Reference:
    architecture/main-system-patterns/phase*.md
    architecture/integrations/N8N_INTEGRATION.md (to be created)

This module defines the REST API schemas for exposing each pipeline phase
as an independent endpoint. This enables external orchestration tools like
n8n to control the pipeline flow.

Design Principles:
    - Each phase has explicit input/output schemas
    - State can be passed via turn_id (Panda manages context.md) or inline
    - Phases are stateless - all state comes from request or is loaded by turn_id
    - Responses include phase output plus execution metadata
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from libs.core.models import (
    QueryAnalysis,
    ContentReference,
    ReflectionResult,
    ReflectionDecision,
    GatheredContext,
    TaskPlan,
    PlannerRoute,
    PlannerAction,
    ToolExecutionResult,
    SynthesisResult,
    ValidationResult,
    ValidationDecision,
)


# =============================================================================
# Common Types
# =============================================================================

class PhaseStatus(str, Enum):
    """Phase execution status."""
    SUCCESS = "success"
    ERROR = "error"
    INTERVENTION_REQUIRED = "intervention_required"


class TurnSummary(BaseModel):
    """Summary of a prior turn for context."""
    turn_id: int
    summary: str
    content_refs: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class PhaseMetadata(BaseModel):
    """Execution metadata returned with every phase response."""
    phase_number: int
    phase_name: str
    execution_time_ms: float
    tokens_used: int = 0
    status: PhaseStatus = PhaseStatus.SUCCESS
    error: Optional[str] = None


# =============================================================================
# Phase 0: Query Analyzer
# =============================================================================

class Phase0Request(BaseModel):
    """Request for Phase 0: Query Analyzer.

    Input Sources:
        - raw_query: The exact user input
        - turn_summaries: Recent turn summaries for reference resolution

    Alternative: Provide turn_id to load from existing turn context.
    """
    raw_query: str = Field(..., description="The exact user input")
    turn_summaries: list[TurnSummary] = Field(
        default_factory=list,
        description="Recent turn summaries for reference resolution (max 5)"
    )

    # Alternative: load from existing turn
    turn_id: Optional[int] = Field(
        None,
        description="If provided, load context from this turn instead of inline"
    )
    session_id: Optional[str] = Field(
        None,
        description="Session ID for context lookup"
    )

    # Mode selection
    mode: str = Field("chat", description="Operating mode: 'chat' or 'code'")


class Phase0Response(BaseModel):
    """Response from Phase 0: Query Analyzer."""
    analysis: QueryAnalysis = Field(..., description="Query analysis result")
    metadata: PhaseMetadata = Field(..., description="Execution metadata")

    # Context.md section content (for passing to next phase)
    section_0_content: str = Field(
        ...,
        description="Formatted section 0 content for context.md"
    )


# =============================================================================
# Phase 1: Reflection
# =============================================================================

class Phase1Request(BaseModel):
    """Request for Phase 1: Reflection.

    Input Sources:
        - query_analysis: Phase 0 output (inline)

    Alternative: Provide turn_id to load from existing turn context.
    """
    query_analysis: Optional[QueryAnalysis] = Field(
        None,
        description="Phase 0 output (inline mode)"
    )
    section_0_content: Optional[str] = Field(
        None,
        description="Section 0 content from Phase 0 response"
    )

    # Alternative: load from existing turn
    turn_id: Optional[int] = Field(
        None,
        description="If provided, load context from this turn"
    )
    session_id: Optional[str] = Field(None, description="Session ID")
    mode: str = Field("chat", description="Operating mode")


class Phase1Response(BaseModel):
    """Response from Phase 1: Reflection."""
    result: ReflectionResult = Field(..., description="Reflection decision")
    metadata: PhaseMetadata = Field(..., description="Execution metadata")

    # Decision helpers
    should_proceed: bool = Field(
        ...,
        description="True if decision is PROCEED"
    )
    clarification_question: Optional[str] = Field(
        None,
        description="Question to ask user if CLARIFY"
    )

    # Context.md section content
    section_1_content: str = Field(
        ...,
        description="Formatted section 1 content for context.md"
    )


# =============================================================================
# Phase 2: Context Gatherer
# =============================================================================

class Phase2Request(BaseModel):
    """Request for Phase 2: Context Gatherer.

    Prerequisite: Phase 1 must have decided PROCEED.

    Input Sources:
        - section_0_content: From Phase 0
        - section_1_content: From Phase 1

    Alternative: Provide turn_id to load accumulated context.
    """
    section_0_content: Optional[str] = Field(
        None,
        description="Section 0 content from Phase 0"
    )
    section_1_content: Optional[str] = Field(
        None,
        description="Section 1 content from Phase 1"
    )

    # Alternative: load from existing turn
    turn_id: Optional[int] = Field(
        None,
        description="If provided, load context from this turn"
    )
    session_id: str = Field(..., description="Session ID for context lookup")
    user_id: str = Field("default", description="User ID for preferences")
    mode: str = Field("chat", description="Operating mode")


class Phase2Response(BaseModel):
    """Response from Phase 2: Context Gatherer."""
    gathered: GatheredContext = Field(
        ...,
        description="Gathered context result"
    )
    metadata: PhaseMetadata = Field(..., description="Execution metadata")

    # Context assessment
    has_sufficient_context: bool = Field(
        False,
        description="True if context is likely sufficient for synthesis"
    )

    # Context.md section content
    section_2_content: str = Field(
        ...,
        description="Formatted section 2 content for context.md"
    )


# =============================================================================
# Phase 3: Planner
# =============================================================================

class Phase3Request(BaseModel):
    """Request for Phase 3: Planner.

    Input Sources:
        - Sections 0-2 content (accumulated)
        - On RETRY: Sections 0-6 with failure context

    Alternative: Provide turn_id to load accumulated context.
    """
    # Accumulated context (inline mode)
    section_0_content: Optional[str] = None
    section_1_content: Optional[str] = None
    section_2_content: Optional[str] = None

    # RETRY context (when coming from Validation)
    section_4_content: Optional[str] = Field(
        None,
        description="Tool execution results (on RETRY)"
    )
    section_5_content: Optional[str] = Field(
        None,
        description="Previous synthesis (on RETRY)"
    )
    section_6_content: Optional[str] = Field(
        None,
        description="Validation feedback (on RETRY)"
    )
    is_retry: bool = Field(False, description="True if this is a RETRY attempt")
    attempt_number: int = Field(1, description="Current attempt number")

    # Alternative: load from existing turn
    turn_id: Optional[int] = Field(
        None,
        description="If provided, load context from this turn"
    )
    session_id: str = Field(..., description="Session ID")
    mode: str = Field("chat", description="Operating mode")


class Phase3Response(BaseModel):
    """Response from Phase 3: Planner."""
    plan: TaskPlan = Field(..., description="Task plan result")
    metadata: PhaseMetadata = Field(..., description="Execution metadata")

    # Routing decision
    route_to: PlannerRoute = Field(
        ...,
        description="Where to route: coordinator, synthesis, or clarify"
    )

    # Ticket for Coordinator (if route_to == coordinator)
    ticket_json: Optional[dict[str, Any]] = Field(
        None,
        description="Ticket JSON for Coordinator execution"
    )

    # Context.md section content
    section_3_content: str = Field(
        ...,
        description="Formatted section 3 content for context.md"
    )


# =============================================================================
# Phase 4: Coordinator
# =============================================================================

class Phase4Request(BaseModel):
    """Request for Phase 4: Coordinator.

    Executes tools based on the Planner's ticket.

    Input Sources:
        - Sections 0-3 content
        - ticket_json: Tool execution plan from Planner

    Alternative: Provide turn_id to load accumulated context.
    """
    # Accumulated context (inline mode)
    section_0_content: Optional[str] = None
    section_1_content: Optional[str] = None
    section_2_content: Optional[str] = None
    section_3_content: Optional[str] = None

    # Ticket from Planner
    ticket_json: Optional[dict[str, Any]] = Field(
        None,
        description="Ticket JSON from Planner"
    )

    # Alternative: load from existing turn
    turn_id: Optional[int] = Field(
        None,
        description="If provided, load context from this turn"
    )
    session_id: str = Field(..., description="Session ID")
    mode: str = Field("chat", description="Operating mode")

    # Iteration control (for Planner-Coordinator loop)
    max_iterations: int = Field(
        5,
        description="Maximum tool execution iterations"
    )


class Phase4Response(BaseModel):
    """Response from Phase 4: Coordinator."""
    result: ToolExecutionResult = Field(
        ...,
        description="Tool execution result"
    )
    metadata: PhaseMetadata = Field(..., description="Execution metadata")

    # Loop status
    action: str = Field(
        ...,
        description="Action taken: TOOL_CALL or DONE"
    )
    needs_more_iterations: bool = Field(
        False,
        description="True if more iterations needed"
    )

    # Context.md section content
    section_4_content: str = Field(
        ...,
        description="Formatted section 4 content for context.md"
    )

    # toolresults.md content (full results for Synthesis/Validation)
    toolresults_content: Optional[str] = Field(
        None,
        description="Full tool results for Synthesis and Validation"
    )


# =============================================================================
# Phase 5: Synthesis
# =============================================================================

class Phase5Request(BaseModel):
    """Request for Phase 5: Synthesis.

    Generates user-facing response from accumulated context.

    Input Sources:
        - Sections 0-4 content
        - toolresults_content (if tools were executed)

    Alternative: Provide turn_id to load accumulated context.
    """
    # Accumulated context (inline mode)
    section_0_content: Optional[str] = None
    section_1_content: Optional[str] = None
    section_2_content: Optional[str] = None
    section_3_content: Optional[str] = None
    section_4_content: Optional[str] = None

    # Full tool results
    toolresults_content: Optional[str] = Field(
        None,
        description="Full tool results from Coordinator"
    )

    # Alternative: load from existing turn
    turn_id: Optional[int] = Field(
        None,
        description="If provided, load context from this turn"
    )
    session_id: str = Field(..., description="Session ID")
    mode: str = Field("chat", description="Operating mode")

    # REVISE context (from Validation)
    revision_hints: Optional[str] = Field(
        None,
        description="Revision hints from Validation (on REVISE)"
    )
    is_revision: bool = Field(False, description="True if this is a revision")


class Phase5Response(BaseModel):
    """Response from Phase 5: Synthesis."""
    result: SynthesisResult = Field(..., description="Synthesis result")
    metadata: PhaseMetadata = Field(..., description="Execution metadata")

    # User response
    response: str = Field(..., description="User-facing response")

    # Context.md section content
    section_5_content: str = Field(
        ...,
        description="Formatted section 5 content for context.md"
    )


# =============================================================================
# Phase 6: Validation
# =============================================================================

class Phase6Request(BaseModel):
    """Request for Phase 6: Validation.

    Validates the synthesized response for quality.

    Input Sources:
        - Sections 0-5 content
        - toolresults_content (for claim verification)

    Alternative: Provide turn_id to load accumulated context.
    """
    # Accumulated context (inline mode)
    section_0_content: Optional[str] = None
    section_1_content: Optional[str] = None
    section_2_content: Optional[str] = None
    section_3_content: Optional[str] = None
    section_4_content: Optional[str] = None
    section_5_content: Optional[str] = None

    # Full tool results for verification
    toolresults_content: Optional[str] = Field(
        None,
        description="Full tool results for claim verification"
    )

    # Alternative: load from existing turn
    turn_id: Optional[int] = Field(
        None,
        description="If provided, load context from this turn"
    )
    session_id: str = Field(..., description="Session ID")
    mode: str = Field("chat", description="Operating mode")


class Phase6Response(BaseModel):
    """Response from Phase 6: Validation."""
    result: ValidationResult = Field(..., description="Validation result")
    metadata: PhaseMetadata = Field(..., description="Execution metadata")

    # Decision helpers
    decision: ValidationDecision = Field(
        ...,
        description="Validation decision: APPROVE, REVISE, RETRY, FAIL"
    )
    is_approved: bool = Field(
        ...,
        description="True if decision is APPROVE"
    )
    needs_retry: bool = Field(
        ...,
        description="True if decision is RETRY (back to Planner)"
    )
    needs_revision: bool = Field(
        ...,
        description="True if decision is REVISE (back to Synthesis)"
    )

    # Context.md section content
    section_6_content: str = Field(
        ...,
        description="Formatted section 6 content for context.md"
    )


# =============================================================================
# Phase 7: Save (Procedural)
# =============================================================================

class Phase7Request(BaseModel):
    """Request for Phase 7: Save.

    Persists the completed turn. This is procedural (no LLM).

    Input Sources:
        - All sections content (0-6)
        - Final response

    Alternative: Provide turn_id to save existing turn context.
    """
    # All sections (inline mode)
    section_0_content: Optional[str] = None
    section_1_content: Optional[str] = None
    section_2_content: Optional[str] = None
    section_3_content: Optional[str] = None
    section_4_content: Optional[str] = None
    section_5_content: Optional[str] = None
    section_6_content: Optional[str] = None

    # Final response
    final_response: str = Field(..., description="Final user response")
    quality_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall quality score"
    )

    # Turn metadata
    turn_id: Optional[int] = Field(
        None,
        description="Turn ID (if updating existing turn)"
    )
    session_id: str = Field(..., description="Session ID")
    user_id: str = Field("default", description="User ID")


class Phase7Response(BaseModel):
    """Response from Phase 7: Save."""
    turn_id: int = Field(..., description="Saved turn ID")
    turn_path: str = Field(..., description="Path to turn directory")
    metadata: PhaseMetadata = Field(..., description="Execution metadata")

    # Index updates
    index_updated: bool = Field(
        False,
        description="True if turn index was updated"
    )
    summary_generated: bool = Field(
        False,
        description="True if turn summary was generated"
    )


# =============================================================================
# Aggregate Types for Full Pipeline State
# =============================================================================

class FullContextState(BaseModel):
    """Complete pipeline state for debugging or resumption.

    Can be used to pass full state between systems or resume
    a pipeline at any point.
    """
    turn_id: Optional[int] = None
    session_id: str
    user_id: str = "default"
    mode: str = "chat"

    # Section contents (accumulated)
    section_0: Optional[str] = None
    section_1: Optional[str] = None
    section_2: Optional[str] = None
    section_3: Optional[str] = None
    section_4: Optional[str] = None
    section_5: Optional[str] = None
    section_6: Optional[str] = None

    # Additional state
    toolresults: Optional[str] = None
    ticket_json: Optional[dict[str, Any]] = None
    final_response: Optional[str] = None
    quality_score: Optional[float] = None

    # Pipeline progress
    current_phase: int = 0
    is_complete: bool = False
    validation_decision: Optional[ValidationDecision] = None
