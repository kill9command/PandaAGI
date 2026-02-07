"""
Turn Models for PandaAI Orchestrator

Defines the core data structures for turn state, metadata, phase results,
and validation outcomes.

Architecture References:
- architecture/services/user-interface.md (Section 6.2 - WebSocket events)
- architecture/main-system-patterns/phase1-query-analyzer.md (action_needed, user_purpose)
- architecture/main-system-patterns/phase7-validation.md (validation schema)
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TurnState(str, Enum):
    """
    State of a turn in the pipeline.

    Lifecycle: PENDING -> PROCESSING -> (COMPLETED | FAILED | CANCELLED)
    """
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PhaseStatus(str, Enum):
    """
    Status of an individual phase execution.
    """
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ValidationDecision(str, Enum):
    """
    Validation phase decision outcomes.

    From architecture/main-system-patterns/phase7-validation.md:
    - APPROVE (>= 0.80): Send to user, proceed to Phase 8
    - REVISE (0.50-0.79): Loop to Phase 6 with hints (max 2 attempts)
    - RETRY (0.30-0.49): Loop to Phase 3 with fixes (max 1 attempt)
    - FAIL (< 0.30): Unrecoverable error or loop limits exceeded
    """
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    RETRY = "RETRY"
    FAIL = "FAIL"


# NOTE: QueryType and Intent enums were removed (2026-02-04).
# Phase 0 now outputs action_needed (str) and user_purpose (str) instead.
# See: architecture/main-system-patterns/phase1-query-analyzer.md


class ValidationChecks(BaseModel):
    """
    Individual validation check results.

    From architecture/main-system-patterns/phase7-validation.md Section 4:
    - claims_supported: Every factual claim has evidence in section 4 or section 2
    - no_hallucinations: No invented information not present in context
    - query_addressed: Response answers what section 0 asked
    - coherent_format: Well-structured and readable response
    """
    claims_supported: bool = Field(
        description="All factual claims have supporting evidence in context"
    )
    no_hallucinations: bool = Field(
        description="No invented information beyond what is in context"
    )
    query_addressed: bool = Field(
        description="Response answers the original query from section 0"
    )
    coherent_format: bool = Field(
        description="Response is well-structured and readable"
    )


class ValidationResult(BaseModel):
    """
    Complete validation output from Phase 6.

    From architecture/main-system-patterns/phase7-validation.md Section 6.
    """
    decision: ValidationDecision = Field(
        description="Validation decision: APPROVE, REVISE, RETRY, or FAIL"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence score (0.0-1.0) for response quality"
    )
    issues: list[str] = Field(
        default_factory=list,
        description="List of specific problems found (empty if APPROVE)"
    )
    checks: ValidationChecks = Field(
        description="Boolean result for each validation check"
    )
    revision_hints: Optional[str] = Field(
        default=None,
        description="Specific guidance for Synthesis if REVISE"
    )
    suggested_fixes: Optional[str] = Field(
        default=None,
        description="Specific guidance for Planner if RETRY"
    )


class PhaseResult(BaseModel):
    """
    Result of a single phase execution.

    Phases 0-8:
    - Phase 0: Query Analyzer (REFLEX role)
    - Phase 1: Reflection (REFLEX role)
    - Phase 2: Context Gatherer (MIND role)
    - Phase 3: Planner (MIND role)
    - Phase 4: Executor (MIND role)
    - Phase 5: Coordinator (REFLEX role)
    - Phase 6: Synthesis (VOICE role)
    - Phase 7: Validation (MIND role)
    - Phase 8: Save (procedural, no LLM)
    """
    phase: int = Field(
        ge=0, le=8,
        description="Phase number (0-8)"
    )
    name: str = Field(
        description="Phase name (e.g., 'query_analyzer', 'reflection')"
    )
    status: PhaseStatus = Field(
        description="Phase execution status"
    )
    duration_ms: Optional[int] = Field(
        default=None,
        description="Phase execution duration in milliseconds"
    )
    output: Optional[dict[str, Any]] = Field(
        default=None,
        description="Phase-specific output data"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if phase failed"
    )
    attempt: int = Field(
        default=1,
        ge=1,
        description="Attempt number (for REVISE/RETRY loops)"
    )


class TurnMetadata(BaseModel):
    """
    Metadata for a conversation turn.

    Contains classification and routing information determined
    by Phase 0 (Query Analyzer) and Phase 1 (Reflection).
    """
    turn_id: int = Field(
        description="Unique turn identifier"
    )
    session_id: str = Field(
        description="Session identifier for grouping related turns"
    )
    query: str = Field(
        description="Original user query (unmodified)"
    )
    resolved_query: Optional[str] = Field(
        default=None,
        description="Query with references resolved (from Phase 0)"
    )
    action_needed: Optional[str] = Field(
        default=None,
        description="Action classification from Phase 0 (live_search, recall_memory, answer_from_context, etc.)"
    )
    user_purpose: Optional[str] = Field(
        default=None,
        description="Natural language statement of user's goal from Phase 0"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Turn creation timestamp"
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Turn completion timestamp"
    )


class Turn(BaseModel):
    """
    Complete turn model with full pipeline state.

    A turn represents a single user query through the 9-phase pipeline,
    including all phase results, validation loops, and final response.
    """
    metadata: TurnMetadata = Field(
        description="Turn metadata including classification"
    )
    state: TurnState = Field(
        default=TurnState.PENDING,
        description="Current turn state"
    )
    phases: list[PhaseResult] = Field(
        default_factory=list,
        description="Results from each executed phase"
    )
    current_phase: Optional[int] = Field(
        default=None,
        description="Currently executing phase number (0-7)"
    )
    response: Optional[str] = Field(
        default=None,
        description="Final response text sent to user"
    )
    quality: Optional[float] = Field(
        default=None,
        ge=0.0, le=1.0,
        description="Response quality score from validation"
    )
    validation: Optional[ValidationResult] = Field(
        default=None,
        description="Final validation result"
    )
    revise_count: int = Field(
        default=0,
        ge=0, le=2,
        description="Number of REVISE loops executed (max 2)"
    )
    retry_count: int = Field(
        default=0,
        ge=0, le=1,
        description="Number of RETRY loops executed (max 1)"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if turn failed"
    )
    tokens_used: int = Field(
        default=0,
        ge=0,
        description="Total tokens used across all phases"
    )
    total_duration_ms: Optional[int] = Field(
        default=None,
        description="Total turn duration in milliseconds"
    )

    def get_phase_result(self, phase: int) -> Optional[PhaseResult]:
        """Get the result for a specific phase number."""
        for result in self.phases:
            if result.phase == phase:
                return result
        return None

    def add_phase_result(self, result: PhaseResult) -> None:
        """Add or update a phase result."""
        # Remove existing result for this phase if present
        self.phases = [p for p in self.phases if p.phase != result.phase]
        self.phases.append(result)
        # Keep phases sorted by phase number
        self.phases.sort(key=lambda p: (p.phase, p.attempt))

    @property
    def is_complete(self) -> bool:
        """Check if turn has reached a terminal state."""
        return self.state in (TurnState.COMPLETED, TurnState.FAILED, TurnState.CANCELLED)

    @property
    def can_revise(self) -> bool:
        """Check if another REVISE loop is allowed."""
        return self.revise_count < 2

    @property
    def can_retry(self) -> bool:
        """Check if another RETRY loop is allowed."""
        return self.retry_count < 1
