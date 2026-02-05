"""
Validation result dataclasses.

Contains:
- ValidationFailureContext: Context for validation failures
- GoalStatus: Status of a single goal in multi-goal queries
- ValidationResult: Result from Phase 6 validation
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Default max validation retries
MAX_VALIDATION_RETRIES = 3


@dataclass
class ValidationFailureContext:
    """
    Context for validation failures, used to invalidate claims and trigger retry.
    """
    reason: str  # URL_NOT_IN_RESEARCH, PRICE_STALE, SPEC_MISMATCH, LLM_VALIDATION_RETRY
    failed_claims: List[Dict[str, Any]] = field(default_factory=list)
    failed_urls: List[str] = field(default_factory=list)
    mismatches: List[Dict[str, Any]] = field(default_factory=list)
    retry_count: int = 1
    max_retries: int = MAX_VALIDATION_RETRIES
    suggested_fixes: List[str] = field(default_factory=list)  # From Validator for Planner


@dataclass
class GoalStatus:
    """Status of a single goal in multi-goal queries (#57 from IMPLEMENTATION_ROADMAP.md)."""
    goal_id: str
    description: str
    score: float  # 0.0-1.0
    status: str  # 'fulfilled', 'partial', 'unfulfilled'
    evidence: Optional[str] = None


@dataclass
class ValidationResult:
    """Result from Phase 6 validation.

    ARCHITECTURAL DECISION (2025-12-30):
    - Removed LEARN decision - learning now happens implicitly via turn indexing.
    - Added APPROVE_PARTIAL for multi-goal queries where some goals succeed (#57)

    ARCHITECTURAL DECISION (2026-01-24):
    - Added checks dict to capture hallucination indicators from validator
    - Added term_analysis for query/response term alignment checking
    """
    decision: str  # APPROVE, APPROVE_PARTIAL, REVISE, RETRY, FAIL
    confidence: float = 0.8
    issues: List[str] = field(default_factory=list)
    revision_hints: Optional[str] = None
    failure_context: Optional[ValidationFailureContext] = None
    checks_performed: List[str] = field(default_factory=list)
    urls_verified: int = 0
    prices_checked: int = 0
    retry_count: int = 0
    # Multi-goal support (#57)
    goal_statuses: List[GoalStatus] = field(default_factory=list)
    partial_message: Optional[str] = None  # Message for partial success
    # Hallucination detection (2026-01-24)
    checks: dict = field(default_factory=dict)  # Validator checks (query_terms_in_context, no_term_substitution, etc.)
    term_analysis: dict = field(default_factory=dict)  # Query vs response term analysis
    unsourced_claims: list = field(default_factory=list)  # Claims in response with no source in context
