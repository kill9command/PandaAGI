"""
Gateway Dependencies Module

Provides singleton instances with lazy initialization for all Gateway services.
Follows the pattern from Orchestrator service for consistent dependency injection.

Architecture Reference:
    architecture/Implementation/04-SERVICES-OVERVIEW.md
"""

import logging
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

from apps.services.gateway.config import (
    GUIDE_API_KEY,
    GUIDE_MODEL_ID,
    GUIDE_URL,
    COORDINATOR_API_KEY,
    COORDINATOR_MODEL_ID,
    COORDINATOR_URL,
    MEM_INDEX_PATH,
    MEM_JSON_DIR,
    MODEL_TIMEOUT,
    SHARED_STATE_DIR,
    TOKEN_BUDGET,
    TOOL_CATALOG_PATH,
    ENABLE_LLM_CURATION,
)

logger = logging.getLogger("uvicorn.error")

# =============================================================================
# Private Singleton Storage
# =============================================================================

_tool_circuit_breaker: Optional[Any] = None
_artifact_store: Optional[Any] = None
_ledger: Optional[Any] = None
_claim_registry: Optional[Any] = None
_session_contexts: Optional[Any] = None
# NOTE: _unified_context_mgr removed - replaced by context_document.py and context_gatherer_2phase.py
# NOTE: _plan_linter removed - depended on archived tool_router.py
# NOTE: _tool_router and _intent_classifier removed - replaced by LLM-driven user_purpose system
_wm_config: Optional[Any] = None
_circuit_breaker: Optional[Any] = None
_token_budget_enforcer: Optional[Any] = None
_meta_reflection_gate: Optional[Any] = None
_llm_client: Optional[Any] = None
_unified_flow: Optional[Any] = None
_context_summarizer: Optional[Any] = None
_llm_extractor: Optional[Any] = None
_learning_store: Optional[Any] = None
_info_registry: Optional[Any] = None
_recent_short_term: Optional[Dict[str, Deque[Dict[str, Any]]]] = None
_research_ws_manager: Optional[Any] = None


# =============================================================================
# Tool Circuit Breaker
# =============================================================================


def get_tool_circuit_breaker():
    """Get the tool circuit breaker singleton."""
    global _tool_circuit_breaker
    if _tool_circuit_breaker is None:
        from apps.services.gateway.tool_circuit_breaker import ToolCircuitBreaker

        _tool_circuit_breaker = ToolCircuitBreaker(
            failure_threshold=3,  # Open circuit after 3 failures
            window_seconds=300,  # Count failures within 5-minute window
            recovery_timeout=60,  # Wait 60s before testing recovery
            success_threshold=2,  # Need 2 successes to close circuit
        )
        logger.info("[Dependencies] Tool circuit breaker initialized")

        # Wire up the orchestrator client
        from apps.services.gateway.services.orchestrator_client import (
            set_tool_circuit_breaker,
        )

        set_tool_circuit_breaker(_tool_circuit_breaker)

    return _tool_circuit_breaker


# =============================================================================
# Shared State (Artifacts, Ledger, Claims)
# =============================================================================


def get_artifact_store():
    """Get the artifact store singleton."""
    global _artifact_store
    if _artifact_store is None:
        from apps.services.orchestrator.shared_state import ArtifactStore

        _artifact_store = ArtifactStore(SHARED_STATE_DIR / "artifacts")
        logger.info("[Dependencies] Artifact store initialized")
    return _artifact_store


def get_ledger():
    """Get the session ledger singleton."""
    global _ledger
    if _ledger is None:
        from apps.services.orchestrator.shared_state import SessionLedger

        _ledger = SessionLedger(SHARED_STATE_DIR / "ledger.db")
        logger.info("[Dependencies] Session ledger initialized")
    return _ledger


def get_claim_registry():
    """Get the claim registry singleton."""
    global _claim_registry
    if _claim_registry is None:
        from apps.services.orchestrator.shared_state import ClaimRegistry

        _claim_registry = ClaimRegistry(SHARED_STATE_DIR / "ledger.db")
        logger.info("[Dependencies] Claim registry initialized")
    return _claim_registry


def get_session_contexts():
    """Get the session context manager singleton."""
    global _session_contexts
    if _session_contexts is None:
        from apps.services.gateway.session_context import SessionContextManager

        _session_contexts = SessionContextManager(SHARED_STATE_DIR / "session_contexts")
        logger.info("[Dependencies] Session context manager initialized")
    return _session_contexts


# =============================================================================
# Context Management
# =============================================================================

# NOTE: get_unified_context_manager() removed - context now handled by:
# - libs/gateway/context_document.py (document IO pattern)
# - libs/gateway/context_gatherer_2phase.py (context gathering)


def get_context_summarizer():
    """Get the context summarizer singleton."""
    global _context_summarizer
    if _context_summarizer is None:
        from apps.services.gateway.context_summarizer import ContextSummarizer

        _context_summarizer = ContextSummarizer(
            model_url=GUIDE_URL,
            model_id=GUIDE_MODEL_ID,
            api_key=GUIDE_API_KEY,
        )
        logger.info("[Dependencies] Context summarizer initialized")
    return _context_summarizer


# =============================================================================
# Tool Infrastructure
# =============================================================================

# NOTE: get_tool_router() removed - tool routing now handled by LLM reading user_purpose


# NOTE: PlanLinter removed - it depended on archived tool_router.py
# def get_plan_linter():
#     """Get the plan linter singleton."""
#     global _plan_linter
#     if _plan_linter is None:
#         from apps.services.gateway.plan_linter import PlanLinter
#         _plan_linter = PlanLinter()
#         logger.info("[Dependencies] Plan linter initialized")
#     return _plan_linter


# =============================================================================
# Intent and Classification
# =============================================================================

# NOTE: get_intent_classifier() removed - intent classification replaced by
# LLM-driven user_purpose extraction in Phase 0. See architecture/plans/INTENT_SYSTEM_MIGRATION.md


def get_wm_config():
    """Get the working memory config singleton."""
    global _wm_config
    if _wm_config is None:
        from apps.services.orchestrator.context_builder import WorkingMemoryConfig

        _wm_config = WorkingMemoryConfig()
        logger.info("[Dependencies] Working memory config initialized")
    return _wm_config


# =============================================================================
# Contract Layer
# =============================================================================


def get_circuit_breaker():
    """Get the contract layer circuit breaker singleton."""
    global _circuit_breaker
    if _circuit_breaker is None:
        from apps.services.gateway.circuit_breaker import (
            get_circuit_breaker as _get_cb,
        )

        _circuit_breaker = _get_cb()
        logger.info("[Dependencies] Circuit breaker initialized")
    return _circuit_breaker


def get_token_budget_enforcer():
    """Get the token budget enforcer singleton."""
    global _token_budget_enforcer
    if _token_budget_enforcer is None:
        from apps.services.gateway.contract_enforcement import TokenBudgetEnforcer
        from apps.services.gateway.contracts import TokenBudget

        _token_budget_enforcer = TokenBudgetEnforcer(TokenBudget(total=TOKEN_BUDGET))
        logger.info("[Dependencies] Token budget enforcer initialized")
    return _token_budget_enforcer


def get_meta_reflection_gate():
    """Get the meta-reflection gate singleton."""
    global _meta_reflection_gate
    if _meta_reflection_gate is None:
        from apps.services.orchestrator.meta_reflection import MetaReflectionGate

        _meta_reflection_gate = MetaReflectionGate(
            llm_url=GUIDE_URL,
            llm_model=GUIDE_MODEL_ID,
            llm_api_key=GUIDE_API_KEY,
            accept_threshold=0.8,
            reject_threshold=0.4,
            max_tokens=80,
            timeout=10.0,
        )
        logger.info("[Dependencies] Meta-reflection gate initialized")
    return _meta_reflection_gate


# =============================================================================
# LLM Clients
# =============================================================================


def get_llm_client():
    """Get the LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        from libs.gateway.llm_client import LLMClient

        _llm_client = LLMClient(
            guide_url=GUIDE_URL,
            coordinator_url=COORDINATOR_URL,
            guide_model=GUIDE_MODEL_ID,
            coordinator_model=COORDINATOR_MODEL_ID,
            guide_headers=(
                {"Authorization": f"Bearer {GUIDE_API_KEY}"}
                if GUIDE_API_KEY != "none"
                else {}
            ),
            coordinator_headers=(
                {"Authorization": f"Bearer {COORDINATOR_API_KEY}"}
                if COORDINATOR_API_KEY != "none"
                else {}
            ),
            timeout=MODEL_TIMEOUT,
        )
        logger.info("[Dependencies] LLM client initialized")
    return _llm_client


def get_llm_extractor():
    """Get the LLM extractor singleton."""
    global _llm_extractor
    if _llm_extractor is None:
        from apps.services.gateway.llm_extractor import (
            LLMExtractor,
            set_llm_extractor,
        )

        _llm_extractor = LLMExtractor(
            model_url=GUIDE_URL,
            model_id=GUIDE_MODEL_ID,
            api_key=GUIDE_API_KEY,
        )
        set_llm_extractor(_llm_extractor)
        logger.info("[Dependencies] LLM extractor initialized")
    return _llm_extractor


# =============================================================================
# Unified Flow
# =============================================================================


def get_unified_flow():
    """Get the unified flow handler singleton."""
    global _unified_flow
    if _unified_flow is None:
        from libs.gateway.unified_flow import UnifiedFlow, UNIFIED_FLOW_ENABLED

        if UNIFIED_FLOW_ENABLED:
            _unified_flow = UnifiedFlow(
                llm_client=get_llm_client(),
                session_context_manager=get_session_contexts(),
            )
            logger.info("[Dependencies] Unified 7-phase flow ENABLED")
        else:
            logger.warning("[Dependencies] Unified flow DISABLED - requests will fail")
    return _unified_flow


def is_unified_flow_enabled() -> bool:
    """Check if unified flow is enabled."""
    from libs.gateway.unified_flow import UNIFIED_FLOW_ENABLED

    return UNIFIED_FLOW_ENABLED


# =============================================================================
# Learning and Memory
# =============================================================================


def get_learning_store():
    """Get the cross-session learning store singleton."""
    global _learning_store
    if _learning_store is None:
        from apps.services.gateway.cross_session_learning import (
            get_learning_store as _get_ls,
        )

        _learning_store = _get_ls()
        logger.info("[Dependencies] Learning store initialized")
    return _learning_store


def get_info_registry():
    """Get the info provider registry singleton."""
    global _info_registry
    if _info_registry is None:
        from apps.services.gateway.info_providers import (
            get_info_registry as _get_ir,
            memory_provider,
            quick_search_provider,
            claims_provider,
            session_history_provider,
        )

        _info_registry = _get_ir()
        _info_registry.register("memory", memory_provider)
        _info_registry.register("quick_search", quick_search_provider)
        _info_registry.register("claims", claims_provider)
        _info_registry.register("session_history", session_history_provider)
        logger.info("[Dependencies] Info provider registry initialized with 4 providers")
    return _info_registry


# =============================================================================
# Short-Term Memory
# =============================================================================


def get_recent_short_term() -> Dict[str, Deque[Dict[str, Any]]]:
    """Get the recent short-term memory storage."""
    global _recent_short_term
    if _recent_short_term is None:
        _recent_short_term = defaultdict(lambda: deque(maxlen=6))
    return _recent_short_term


# =============================================================================
# WebSocket Manager
# =============================================================================


def get_research_ws_manager():
    """Get the research WebSocket manager singleton."""
    global _research_ws_manager
    if _research_ws_manager is None:
        from apps.services.gateway.research_ws_manager import research_ws_manager

        _research_ws_manager = research_ws_manager

        # Wire up the orchestrator client
        from apps.services.gateway.services.orchestrator_client import (
            set_research_ws_manager,
        )

        set_research_ws_manager(_research_ws_manager)

        logger.info("[Dependencies] Research WebSocket manager initialized")
    return _research_ws_manager


# =============================================================================
# Initialization Helper
# =============================================================================


def initialize_all():
    """
    Initialize all singleton dependencies.

    Call this during application startup to ensure all services are ready.
    This triggers lazy initialization of all singletons in the correct order.
    """
    logger.info("[Dependencies] Initializing all singletons...")

    # Core infrastructure
    get_tool_circuit_breaker()
    get_artifact_store()
    get_ledger()
    get_claim_registry()
    get_session_contexts()

    # Context management (unified_context_manager removed - now using document IO)
    get_context_summarizer()

    # Tool infrastructure
    # NOTE: get_plan_linter() removed - depended on archived tool_router.py

    # Classification (intent_classifier removed - now LLM-driven)
    get_wm_config()

    # Contract layer
    get_circuit_breaker()
    get_token_budget_enforcer()
    get_meta_reflection_gate()

    # LLM clients
    get_llm_client()
    get_llm_extractor()

    # Flow
    get_unified_flow()

    # Learning
    get_learning_store()
    get_info_registry()

    # WebSocket
    get_research_ws_manager()

    logger.info("[Dependencies] All singletons initialized")


# =============================================================================
# Reset (for testing)
# =============================================================================


def reset_all():
    """
    Reset all singletons to None.

    Use this in tests to ensure clean state between test runs.
    """
    global _tool_circuit_breaker, _artifact_store, _ledger, _claim_registry
    global _session_contexts
    global _wm_config, _circuit_breaker, _token_budget_enforcer
    global _meta_reflection_gate, _llm_client, _unified_flow, _context_summarizer
    global _llm_extractor, _learning_store, _info_registry, _recent_short_term
    global _research_ws_manager

    _tool_circuit_breaker = None
    _artifact_store = None
    _ledger = None
    _claim_registry = None
    _session_contexts = None
    _wm_config = None
    _circuit_breaker = None
    _token_budget_enforcer = None
    _meta_reflection_gate = None
    _llm_client = None
    _unified_flow = None
    _context_summarizer = None
    _llm_extractor = None
    _learning_store = None
    _info_registry = None
    _recent_short_term = None
    _research_ws_manager = None

    logger.info("[Dependencies] All singletons reset")
