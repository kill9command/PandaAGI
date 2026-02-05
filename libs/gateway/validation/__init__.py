"""
Validation module - Response validation and metrics.

Contains:
- ValidationResult, ValidationFailureContext, GoalStatus: Validation dataclasses
- ValidationHandler: Validation logic, retries, URL verification
- PhaseMetrics: Phase timing and telemetry
- ResponseConfidenceCalculator: Confidence scoring
- phase_events: Event emission for thinking display
"""

from libs.gateway.validation.validation_result import (
    ValidationResult,
    ValidationFailureContext,
    GoalStatus,
    MAX_VALIDATION_RETRIES,
)
from libs.gateway.validation.validation_handler import (
    ValidationHandler,
    get_validation_handler,
    extract_prices_from_text,
    extract_urls_from_text,
    prices_match,
    url_matches_any,
    normalize_url_for_comparison,
)
from libs.gateway.validation.phase_metrics import PhaseMetrics, emit_phase_event
from libs.gateway.validation.response_confidence import (
    ResponseConfidenceCalculator,
    AggregateConfidence,
    calculate_aggregate_confidence,
)

__all__ = [
    "ValidationResult",
    "ValidationFailureContext",
    "GoalStatus",
    "MAX_VALIDATION_RETRIES",
    "ValidationHandler",
    "get_validation_handler",
    "extract_prices_from_text",
    "extract_urls_from_text",
    "prices_match",
    "url_matches_any",
    "normalize_url_for_comparison",
    "PhaseMetrics",
    "emit_phase_event",
    "ResponseConfidenceCalculator",
    "AggregateConfidence",
    "calculate_aggregate_confidence",
]
