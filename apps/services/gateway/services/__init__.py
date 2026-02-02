"""
Gateway Service Modules

Provides thinking visualization, orchestrator client, and job management services.
"""

from apps.services.gateway.services.thinking import (
    ThinkingEvent,
    emit_thinking_event,
    cleanup_thinking_queues,
    calculate_confidence,
    boost_confidence_for_patterns,
    get_thinking_queue,
    get_response,
    has_thinking_queue,
    THINKING_QUEUES,
    RESPONSE_STORE,
)

from apps.services.gateway.services.jobs import (
    JOBS,
    CANCELLED_JOBS,
    CANCELLED_TRACES,
    is_trace_cancelled,
    run_chat_job,
    create_job,
    get_job,
    cancel_job,
    cancel_trace,
    list_active_jobs,
)

from apps.services.gateway.services.orchestrator_client import (
    call_orchestrator_with_circuit_breaker,
    create_research_event_callback,
)

__all__ = [
    # Thinking
    "ThinkingEvent",
    "emit_thinking_event",
    "cleanup_thinking_queues",
    "calculate_confidence",
    "boost_confidence_for_patterns",
    "get_thinking_queue",
    "get_response",
    "has_thinking_queue",
    "THINKING_QUEUES",
    "RESPONSE_STORE",
    # Jobs
    "JOBS",
    "CANCELLED_JOBS",
    "CANCELLED_TRACES",
    "is_trace_cancelled",
    "run_chat_job",
    "create_job",
    "get_job",
    "cancel_job",
    "cancel_trace",
    "list_active_jobs",
    # Orchestrator client
    "call_orchestrator_with_circuit_breaker",
    "create_research_event_callback",
]
