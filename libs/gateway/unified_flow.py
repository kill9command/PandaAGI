"""
Unified Flow Handler - 9-phase pipeline with 3-tier Planner-Executor-Coordinator loop

Implements the unified document IO architecture (canonical ordering from architecture/README.md):
- Phase 0: Query Analyzer - Resolve references, classify query (REFLEX 0.4)
- Phase 1: Reflection - Binary PROCEED/CLARIFY gate (REFLEX 0.4)
- Phase 2: Context Gatherer - Retrieve relevant context (MIND 0.6)
- Phase 3: Planner - Strategic planning, define goals and approach (MIND 0.6)
- Phase 4: Executor - Tactical execution, natural language commands (MIND 0.6)
             (lives in libs/gateway/orchestration/executor_loop.py)
- Phase 5: Coordinator - Tool Expert, translates commands to tool calls (MIND 0.6)
- Phase 6: Synthesis - Generate user-facing response (VOICE 0.7)
- Phase 7: Validation - Quality gate, APPROVE/RETRY/REVISE/FAIL (MIND 0.6)
- Phase 8: Save - Persist turn data (procedural, no LLM)

ARCHITECTURAL UPDATE (2026-01-24):
- Added Executor phase between Planner and Coordinator
- Planner now outputs STRATEGIC_PLAN with route_to: executor | synthesis | clarify | refresh_context
- Executor issues natural language commands (not tool specs)
- Coordinator (Tool Expert) translates commands to tool calls

3-TIER ARCHITECTURE:
  Planner (Strategic)  →  WHAT to do (high-level goals)
      ↓
  Executor (Tactical)  →  HOW to do it (natural language commands)
      ↓
  Coordinator (Tool Expert)  →  Translate commands to tool calls

LEGACY SUPPORT:
- Still handles PLANNER_DECISION format (EXECUTE/COMPLETE) for backward compatibility
- Falls through to existing planning loop if legacy format detected

Key features:
- Single accumulating context.md document
- Recipe-based LLM calls with token budgets
- 3-tier execution with clear separation of concerns
- Response validation before sending
- Summarize at retrieval time, not save time

Author: Unified Architecture Migration
Date: 2025-12-07, Updated: 2026-01-24
"""

import os
import json
import logging
import asyncio
import time
import shutil
import aiohttp
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field

# Context module
from libs.gateway.context.context_document import ContextDocument, TurnMetadata, extract_keywords
from libs.gateway.context.context_gatherer_2phase import ContextGatherer2Phase
from libs.gateway.context.doc_pack_builder import DocPackBuilder
from libs.gateway.context.query_analyzer import QueryAnalyzer, QueryAnalysis, ContentReference
from libs.gateway.context.section_formatter import SectionFormatter, get_section_formatter

# Persistence module
from libs.gateway.persistence.turn_search_index import TurnSearchIndex
from libs.gateway.persistence.turn_saver import TurnSaver
from libs.gateway.persistence.turn_manager import TurnDirectory
from libs.gateway.persistence.turn_counter import TurnCounter
from libs.gateway.persistence.user_paths import UserPathResolver
from libs.gateway.persistence.turn_index_db import get_turn_index_db
from libs.gateway.persistence.document_writer import DocumentWriter, get_document_writer

# Research module
from libs.gateway.research.research_document import ResearchDocumentWriter, ResearchDocument
from libs.gateway.research.research_index_db import get_research_index_db
from libs.gateway.research.smart_summarization import SmartSummarizer, get_summarizer
from libs.gateway.research.research_handler import ResearchHandler, get_research_handler

# LLM module
from libs.gateway.llm.recipe_loader import load_recipe, select_recipe

# Validation module
from libs.gateway.validation.phase_metrics import PhaseMetrics, emit_phase_event as _emit_phase_event
from libs.gateway.validation.response_confidence import (
    ResponseConfidenceCalculator,
    AggregateConfidence,
    calculate_aggregate_confidence,
)
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

# Utility module
from libs.gateway.util.panda_loop import PandaLoop, LoopResult, format_loop_summary
from libs.gateway.util.principle_extractor import PrincipleExtractor, ImprovementPrinciple
from libs.gateway.util.error_compactor import ErrorCompactor, CompactedError, get_error_compactor

# Execution module
from libs.gateway.execution.tool_approval import (
    ToolApprovalManager,
    get_tool_approval_manager,
    APPROVAL_SYSTEM_ENABLED,
)
from libs.gateway.execution.workflow_registry import WorkflowRegistry
from libs.gateway.execution.workflow_matcher import WorkflowMatcher
from libs.gateway.execution.tool_catalog import ToolCatalog
from libs.gateway.execution.workflow_step_runner import WorkflowStepRunner, WorkflowResult
from libs.gateway.execution.execution_guard import ExecutionGuard, hash_tool_args, detect_circular_calls
from libs.gateway.execution.tool_executor import ToolExecutor, get_tool_executor
from libs.gateway.execution.tool_registration import register_all_tools
from libs.gateway.execution.workflow_manager import WorkflowManager, get_workflow_manager
from libs.gateway.planning.plan_state import PlanStateManager, get_plan_state_manager

# Phases module
from libs.gateway.orchestration.agent_loop import AgentLoop, AgentLoopConfig, get_agent_loop
from libs.gateway.orchestration.executor_loop import ExecutorLoop, ExecutorLoopConfig, get_executor_loop
from libs.gateway.orchestration.planning_loop import PlanningLoop, PlanningLoopConfig, get_planning_loop
from libs.gateway.orchestration.request_handler import RequestHandler, RequestHandlerConfig, get_request_handler
from libs.gateway.orchestration.reflection_phase import ReflectionPhase, get_reflection_phase
from libs.gateway.orchestration.synthesis_phase import SynthesisPhase, get_synthesis_phase

# Parsing module
from libs.gateway.parsing.claims_manager import ClaimsManager, get_claims_manager
from libs.gateway.parsing.query_resolver import QueryResolver, get_query_resolver
from libs.gateway.parsing.response_parser import (
    ResponseParser,
    get_response_parser,
    parse_json_response,
    parse_planner_decision,
    parse_executor_decision,
    parse_tool_selection,
    parse_agent_decision,
)

# External dependencies
from apps.services.gateway.services.thinking import emit_thinking_event, ThinkingEvent
from libs.core.url_health import check_url_health, get_unhealthy_urls, URLHealthStatus

# Memory tools for Planner-Coordinator loop (Tier 2 implementation)
from apps.services.tool_server.memory_mcp import (
    get_memory_mcp,
    MemorySearchRequest,
    MemorySaveRequest,
    UnifiedMemoryMCP
)

# Intervention system for Category B failures (#56 in IMPLEMENTATION_ROADMAP.md)
from apps.services.tool_server.intervention_manager import InterventionManager, InterventionStatus

logger = logging.getLogger(__name__)

# Feature flags
UNIFIED_FLOW_ENABLED = os.getenv("UNIFIED_FLOW_ENABLED", "false").lower() == "true"
# ContextGatherer2Phase is now the only implementation (22% token reduction, 50% fewer LLM calls)
# Uses merged RETRIEVAL + SYNTHESIS instead of the deprecated 4-phase SCAN → READ → EXTRACT → COMPILE

# Smart Summarization - automatic context compression to fit LLM budgets
# When enabled, checks document sizes before LLM calls and logs compression needs
SMART_SUMMARIZATION = os.getenv("SMART_SUMMARIZATION", "true").lower() == "true"

# Maximum revision attempts for validation loop
MAX_VALIDATION_REVISIONS = 2

# Validation loop-back settings
# ARCHITECTURAL DECISION (2025-12-30): Default set to 2 (allows 1 retry)
# Value of 1 means NO retries (loop runs once). Value of 2 allows one retry.
MAX_VALIDATION_RETRIES = int(os.getenv("VALIDATION_MAX_LOOPS", "2"))
VALIDATION_URL_TIMEOUT = int(os.getenv("VALIDATION_URL_TIMEOUT", "5"))
ENABLE_URL_VERIFICATION = os.getenv("VALIDATION_ENABLE_URL_CHECK", "true").lower() == "true"

# Price cross-check settings
ENABLE_PRICE_CROSSCHECK = True
import re

# Recipe-based prompt loading replaces the old _load_prompt infrastructure
# All prompts are now loaded via load_recipe() from libs/gateway/recipe_loader.py
# Recipes define prompt paths, token budgets, and other configuration

# Note: ValidationResult, ValidationFailureContext, GoalStatus are now imported
# from libs.gateway.validation.validation_result

# Note: Price/URL extraction functions (extract_prices_from_text, prices_match,
# extract_urls_from_text, normalize_url_for_comparison, url_matches_any) are now
# imported from libs.gateway.validation.validation_handler (removed duplicate
# definitions 2026-02-03)


class UnifiedFlow:
    """
    Unified 9-Phase Flow Handler

    Combines V5's document model with V4's recipe system.
    Each phase reads the current context.md state and appends its output section.
    """

    def __init__(
        self,
        llm_client,
        session_context_manager=None,
        turns_dir: Path = None,
        sessions_dir: Path = None,
        memory_dir: Path = None
    ):
        self.llm_client = llm_client
        self.session_context_manager = session_context_manager

        # Store explicit overrides if provided (for backward compatibility)
        # If not provided, paths will be computed per-request based on user_id
        self._explicit_turns_dir = turns_dir
        self._explicit_sessions_dir = sessions_dir
        self._explicit_memory_dir = memory_dir

        # Default paths for backward compatibility (used when user_id not provided)
        self.turns_dir = turns_dir or UserPathResolver.get_turns_dir("default")
        self.sessions_dir = sessions_dir or UserPathResolver.get_sessions_dir("default")
        self.memory_dir = memory_dir or UserPathResolver.get_memory_dir("default")

        # Note: TurnSaver is now created per-request with user-specific paths
        # This default instance is kept for backward compatibility
        self.turn_saver = TurnSaver(
            turns_dir=self.turns_dir,
            sessions_dir=self.sessions_dir,
            memory_dir=self.memory_dir
        )

        # DocPackBuilder for recipe-based LLM calls
        self.doc_pack_builder = DocPackBuilder(
            use_smart_compression=True,
            use_llm_compression=False  # Keep sync for now
        )

        # Smart Summarization for automatic context compression
        self.summarizer = get_summarizer(llm_client) if SMART_SUMMARIZATION else None

        # Intervention manager for Category B failures (#56 in IMPLEMENTATION_ROADMAP.md)
        # Handles critical tool failures that require human intervention
        self.intervention_manager = InterventionManager()

        # Workflow system - predictable tool sequences
        # Workflows define what tools to call; PLAN selects workflows, not tools
        self.workflow_registry = WorkflowRegistry()

        # Refactored modules (2026-02-02)
        self.phase_metrics = PhaseMetrics()
        self.validation_handler = get_validation_handler(llm_client=llm_client)
        self.claims_manager = get_claims_manager(llm_client)
        self.execution_guard = ExecutionGuard(self.summarizer)

        # Unified tool catalog - single source of truth for all tool dispatch
        self.tool_catalog = ToolCatalog()

        # ToolExecutor must be created before tool registration (tools reference it)
        self.tool_executor = ToolExecutor(
            tool_catalog=self.tool_catalog,
            claims_manager=self.claims_manager,
            llm_client=llm_client
        )
        register_all_tools(self.tool_catalog, self.workflow_registry, self.tool_executor)

        # Load workflows (apps/workflows + panda_system_docs bundles)
        self.workflow_matcher = WorkflowMatcher(self.workflow_registry)
        self.workflow_runner = WorkflowStepRunner(self.tool_catalog)

        # Workflow manager (extracted 2026-02-03)
        self.workflow_manager = get_workflow_manager(
            workflow_registry=self.workflow_registry,
            workflow_matcher=self.workflow_matcher,
            workflow_runner=self.workflow_runner,
            tool_catalog=self.tool_catalog,
            claims_manager=self.claims_manager,
        )
        self.workflow_manager.load_workflows()
        logger.info(f"[UnifiedFlow] Workflow system loaded: {len(self.workflow_registry.workflows)} workflows")

        # Plan state manager (extracted 2026-02-03)
        self.plan_state_manager = get_plan_state_manager()

        # Document writer (extracted 2026-02-03)
        self.document_writer = get_document_writer(turns_dir=self.turns_dir)

        # Query resolver (extracted 2026-02-03)
        self.query_resolver = get_query_resolver(llm_client=llm_client, turns_dir=self.turns_dir)

        # Research handler (extracted 2026-02-03)
        self.research_handler = get_research_handler(turns_dir=self.turns_dir)

        # Section formatter (extracted 2026-02-03)
        self.section_formatter = get_section_formatter()

        self.response_parser = get_response_parser()

        # Agent loop for Phase 4 Coordinator (extracted 2026-02-03)
        self.agent_loop = get_agent_loop(
            llm_client=llm_client,
            doc_pack_builder=self.doc_pack_builder,
            response_parser=self.response_parser,
            intervention_manager=self.intervention_manager
        )

        # Planning loop for Phase 3-4 (extracted 2026-02-03)
        self.planning_loop = get_planning_loop(
            llm_client=llm_client,
            doc_pack_builder=self.doc_pack_builder,
            response_parser=self.response_parser
        )

        # Request handler for main request orchestration (extracted 2026-02-03)
        self.request_handler = get_request_handler(llm_client=llm_client)

        # Executor loop for Phase 4 (extracted 2026-02-03)
        self.executor_loop = get_executor_loop(llm_client=llm_client)

        # Reflection phase for Phase 2 (extracted 2026-02-03)
        self.reflection_phase = get_reflection_phase(llm_client=llm_client, doc_pack_builder=self.doc_pack_builder)

        # Synthesis phase for Phase 5 (extracted 2026-02-03)
        self.synthesis_phase = get_synthesis_phase(llm_client=llm_client, doc_pack_builder=self.doc_pack_builder)

        # Legacy: Phase timing (delegates to PhaseMetrics)
        self._turn_metrics: Dict[str, Any] = {}
        self._phase_start_times: Dict[str, float] = {}

        logger.info(f"[UnifiedFlow] Initialized (enabled={UNIFIED_FLOW_ENABLED}, smart_summarization={SMART_SUMMARIZATION})")

    def _init_turn_metrics(self) -> Dict[str, Any]:
        """Initialize metrics for a new turn. Delegates to PhaseMetrics."""
        self.phase_metrics.init_turn()
        # Return dict for backward compatibility
        return self.phase_metrics.to_dict()

    def _start_phase(self, phase_name: str):
        """Mark the start of a phase for timing. Delegates to PhaseMetrics."""
        self.phase_metrics.start_phase(phase_name)

    def _end_phase(self, phase_name: str, tokens_in: int = 0, tokens_out: int = 0):
        """Mark the end of a phase and record metrics. Delegates to PhaseMetrics."""
        self.phase_metrics.end_phase(phase_name, tokens_in, tokens_out)

    def _record_decision(self, decision_type: str, decision_value: str, context: str = ""):
        """Record a decision made during the turn. Delegates to PhaseMetrics."""
        self.phase_metrics.record_decision(decision_type, decision_value, context)

    def _record_tool_call(self, tool_name: str, success: bool, duration_ms: int = 0):
        """Record a tool call. Delegates to PhaseMetrics."""
        self.phase_metrics.record_tool_call(tool_name, success, duration_ms)

    def _finalize_turn_metrics(self, quality_score: float, validation_outcome: str) -> Dict[str, Any]:
        """Finalize and return turn metrics. Delegates to PhaseMetrics."""
        return self.phase_metrics.finalize_turn(quality_score, validation_outcome)

    async def _emit_phase_event(
        self,
        trace_id: str,
        phase: int,
        status: str,
        reasoning: str = "",
        confidence: float = None,
        details: Dict = None,
        duration_ms: int = 0
    ):
        """Emit a thinking event for UI visualization. Delegates to phase_metrics module."""
        await _emit_phase_event(
            trace_id=trace_id,
            phase=phase,
            status=status,
            reasoning=reasoning,
            confidence=confidence,
            details=details,
            duration_ms=duration_ms
        )

    # Note: Legacy emit_thinking_event code removed. Now delegated to phase_metrics module.

    def _cross_check_prices(self, response: str, turn_dir: TurnDirectory) -> Tuple[bool, List[str], str]:
        """Cross-check response prices. Delegates to ValidationHandler."""
        return self.validation_handler.cross_check_prices(response, turn_dir)

    async def _verify_urls_in_response(
        self,
        response: str,
        turn_dir: Optional[TurnDirectory] = None
    ) -> Tuple[bool, List[str], List[str]]:
        """Verify URLs in response. Delegates to ValidationHandler."""
        return await self.validation_handler.verify_urls_in_response(response, turn_dir)

    async def _archive_attempt(self, turn_dir: "TurnDirectory", attempt: int) -> None:
        """Archive current turn docs. Delegates to ValidationHandler."""
        await self.validation_handler.archive_attempt(turn_dir, attempt)

    async def _write_retry_context(
        self,
        turn_dir: "TurnDirectory",
        failure_context: ValidationFailureContext,
        session_id: str,
        turn_number: int
    ) -> None:
        """Write retry context. Delegates to ValidationHandler."""
        await self.validation_handler.write_retry_context(
            turn_dir, failure_context, session_id, turn_number
        )

    def _get_retry_instructions(self, failure_context: ValidationFailureContext) -> List[str]:
        """Get retry instructions. Delegates to ValidationHandler."""
        return self.validation_handler.get_retry_instructions(failure_context)

    async def _invalidate_claims(self, failure_context: ValidationFailureContext) -> int:
        """Invalidate failed claims. Delegates to ValidationHandler."""
        return await self.validation_handler.invalidate_claims(failure_context)

    async def handle_request(
        self,
        user_query: str,
        session_id: str,
        mode: str = "chat",
        intent: str = "unknown",
        trace_id: str = "",
        turn_number: int = None,
        repo: str = None,
        user_id: str = None
    ) -> Dict[str, Any]:
        """
        Handle a request using the unified 9-phase flow.
        Delegates main request orchestration to RequestHandler.

        Args:
            user_query: User's query
            session_id: Session identifier
            mode: "chat" or "code"
            intent: Pre-classified intent (optional)
            trace_id: Trace identifier
            turn_number: Turn number (auto-assigned if None)
            repo: Repository path for code mode context gathering
            user_id: User identifier for per-user data paths (defaults to "default")

        Returns:
            Dict with response, context_doc, and metadata
        """
        start_time = time.time()

        # Resolve user-specific paths
        path_resolver = UserPathResolver(user_id)
        request_turns_dir = self._explicit_turns_dir or path_resolver.turns_dir
        request_sessions_dir = self._explicit_sessions_dir or path_resolver.sessions_dir
        request_memory_dir = self._explicit_memory_dir or path_resolver.memory_dir

        # Ensure directories exist
        path_resolver.ensure_dirs()

        # Create request-specific TurnSaver with user paths
        request_turn_saver = TurnSaver(
            turns_dir=request_turns_dir,
            sessions_dir=request_sessions_dir,
            memory_dir=request_memory_dir,
            user_id=path_resolver.user_id
        )

        logger.info(f"[UnifiedFlow] Starting request (trace={trace_id}, mode={mode}, user={path_resolver.user_id})")

        # Determine turn number using user-specific counter
        if turn_number is None:
            turn_counter = TurnCounter(turns_dir=request_turns_dir)
            turn_number = turn_counter.get_next_turn_number(session_id)

        # Create turn directory for this request (in user's turns directory)
        turn_id = f"turn_{turn_number:06d}"
        turn_dir = TurnDirectory(
            turn_id=turn_id,
            session_id=session_id,
            mode=mode,
            trace_id=trace_id,
            base_dir=request_turns_dir
        )
        turn_dir.create()

        # Clean query: Remove UI-added prefixes
        clean_query = user_query
        for prefix in ["Question: ", "Answer: ", "Q: ", "A: "]:
            if clean_query.startswith(prefix):
                clean_query = clean_query[len(prefix):].strip()
                logger.info(f"[UnifiedFlow] Stripped UI prefix '{prefix}' from query")
                break

        # Create context document with §0 (query)
        context_doc = ContextDocument(
            turn_number=turn_number,
            session_id=session_id,
            query=clean_query
        )
        context_doc.mode = mode
        context_doc.repo = repo
        context_doc.user_id = path_resolver.user_id
        context_doc.trace_id = trace_id

        # Store request-specific paths and saver for use in phases
        context_doc._request_turns_dir = request_turns_dir
        context_doc._request_sessions_dir = request_sessions_dir
        context_doc._request_memory_dir = request_memory_dir
        context_doc._request_turn_saver = request_turn_saver

        try:
            # === PHASE 0: Query Analyzer ===
            logger.info(f"[UnifiedFlow] Phase 0: Query Analyzer")
            phase0_start = time.time()
            await self._emit_phase_event(trace_id, 0, "active", "Analyzing query purpose and references")

            query_analyzer = QueryAnalyzer(
                llm_client=self.llm_client,
                turns_dir=self.turns_dir
            )
            query_analysis = await query_analyzer.analyze(context_doc.query, turn_number, mode=mode)

            # Save query_analysis.json to turn directory
            query_analysis.save(turn_dir.path)

            # Store full analysis in context_doc §0 (THE SOURCE OF TRUTH)
            original_query = context_doc.query
            query_analysis.original_query = original_query
            context_doc.set_section_0(query_analysis.to_dict())
            logger.info(f"[UnifiedFlow] Phase 0: purpose={query_analysis.user_purpose[:80]}...")

            phase0_duration = int((time.time() - phase0_start) * 1000)
            await self._emit_phase_event(
                trace_id, 0, "completed",
                f"Mode: {query_analysis.mode}",
                confidence=0.9,
                duration_ms=phase0_duration,
                details={"user_purpose": query_analysis.user_purpose[:200]}
            )

            # Log resolution if performed
            if query_analysis.was_resolved:
                logger.info(f"[UnifiedFlow] Query resolved: '{original_query[:30]}...' → '{query_analysis.resolved_query[:50]}...'")

            # Log content reference if present
            if query_analysis.content_reference:
                logger.info(f"[UnifiedFlow] Content reference detected: {query_analysis.content_reference.title[:50]}... ({query_analysis.content_reference.content_type})")

            # Mode is UI-provided; Phase 1 does not override it

            # === PANDA LOOP: Multi-task detection and routing ===
            if query_analysis.is_multi_task and query_analysis.task_breakdown:
                logger.info(f"[UnifiedFlow] Multi-task detected: {len(query_analysis.task_breakdown)} tasks")
                logger.info(f"[UnifiedFlow] Routing to Panda Loop")

                loop = PandaLoop(
                    tasks=query_analysis.task_breakdown,
                    original_query=context_doc.query,
                    session_id=session_id,
                    mode=mode,
                    unified_flow=self,
                    base_turn=turn_number,
                    trace_id=trace_id,
                )

                loop_result = await loop.run()
                response = format_loop_summary(loop_result)

                return {
                    "response": response,
                    "loop_result": {
                        "status": loop_result.status,
                        "passed": loop_result.passed,
                        "failed": loop_result.failed,
                        "blocked": loop_result.blocked,
                        "summary": loop_result.summary,
                        "tasks": loop_result.tasks,
                    },
                    "context_doc": context_doc,
                    "turn_number": turn_number,
                    "trace_id": trace_id,
                    "unified_flow": True,
                    "is_panda_loop": True,
                }

            # === DELEGATE TO REQUEST HANDLER for Phases 1-7 ===
            self.request_handler.set_callbacks(
                emit_phase_event=self._emit_phase_event,
                init_turn_metrics=self._init_turn_metrics,
                start_phase=self._start_phase,
                end_phase=self._end_phase,
                record_decision=self._record_decision,
                finalize_turn_metrics=self._finalize_turn_metrics,
                phase1_reflection=self._phase1_reflection,
                phase2_context_gatherer=self._phase2_context_gatherer,
                phase3_4_planning_loop=self._phase3_4_planning_loop,
                phase5_synthesis=self._phase5_synthesis,
                phase6_validation=self._phase6_validation,
                phase7_save=self._phase7_save,
                extract_clarification=self._extract_clarification,
                archive_attempt=self._archive_attempt,
                write_retry_context=self._write_retry_context,
                invalidate_claims=self._invalidate_claims,
                update_plan_state_from_validation=self._update_plan_state_from_validation,
                get_turn_metrics=lambda: self._turn_metrics,
                set_turn_metrics=lambda m: setattr(self, '_turn_metrics', m),
            )

            return await self.request_handler.run(
                context_doc=context_doc,
                turn_dir=turn_dir,
                mode=mode,
                intent=intent,
                trace_id=trace_id,
                turn_number=turn_number,
                session_id=session_id,
                query_analysis=query_analysis,
                start_time=start_time,
                request_turn_saver=request_turn_saver,
            )

        except Exception as e:
            logger.exception(f"[UnifiedFlow] Error in request handling: {e}")
            return {
                "response": f"I encountered an error processing your request: {str(e)}",
                "error": str(e),
                "context_doc": context_doc,
                "turn_number": turn_number,
                "trace_id": trace_id,
                "unified_flow": True
            }

    # ========== Phase Implementations ==========

    async def _phase1_reflection(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        max_iterations: int = 3
    ) -> Tuple[ContextDocument, str]:
        """Phase 1.5: Query Analysis Validation. Fast PROCEED/CLARIFY gate using only §0."""
        validation = None
        if context_doc.query_analysis:
            validation = context_doc.query_analysis.get("validation")

        if validation:
            status = validation.get("status", "pass")
            # Only CLARIFY for explicitly garbled/nonsensical queries
            # "retry" means metadata incomplete but query is legitimate - proceed anyway
            decision = "CLARIFY" if status == "clarify" else "PROCEED"
            section_content = f"""**Status:** {status}
**Confidence:** {validation.get('confidence', 0.0)}
**Issues:** {', '.join(validation.get('issues') or []) or 'none'}
"""
            if validation.get("retry_guidance"):
                section_content += f"**Retry Guidance:** {', '.join(validation.get('retry_guidance') or [])}\n"
            if validation.get("clarification_question"):
                section_content += f"**Clarification Question:** {validation.get('clarification_question')}\n"

            if not context_doc.has_section(1):
                context_doc.append_section(1, "Query Analysis Validation", section_content)
            return context_doc, decision

        raise RuntimeError("Phase 1.5 validation missing from query analysis; cannot proceed.")

    async def _phase2_context_gatherer(self, context_doc: ContextDocument) -> ContextDocument:
        """
        Phase 2.1/2.2/2.5: Context Gatherer

        Searches prior turns and builds §2 (Gathered Context).

        Uses ContextGatherer2Phase: Retrieval + Synthesis + Validation
        """
        logger.info("[UnifiedFlow] Phase 2.1/2.2/2.5: Context Gatherer")

        # Use request-specific paths from context_doc, fall back to instance defaults
        turns_dir = getattr(context_doc, '_request_turns_dir', None) or self.turns_dir
        sessions_dir = getattr(context_doc, '_request_sessions_dir', None) or self.sessions_dir
        user_id = getattr(context_doc, 'user_id', None)

        gatherer = ContextGatherer2Phase(
            session_id=context_doc.session_id,
            llm_client=self.llm_client,
            turns_dir=turns_dir,
            sessions_dir=sessions_dir,
            mode=context_doc.mode or "chat",
            repo=context_doc.repo,
            user_id=user_id
        )

        # Gather context (creates a new ContextDocument with §0 and §1)
        new_doc = await gatherer.gather(
            query=context_doc.query,
            turn_number=context_doc.turn_number
        )

        # Carry over user_id and request-specific attributes from original context_doc
        new_doc.user_id = getattr(context_doc, 'user_id', None)
        new_doc.mode = getattr(context_doc, 'mode', None)
        new_doc.repo = getattr(context_doc, 'repo', None)
        new_doc._request_turns_dir = getattr(context_doc, '_request_turns_dir', None)
        new_doc._request_sessions_dir = getattr(context_doc, '_request_sessions_dir', None)
        new_doc._request_memory_dir = getattr(context_doc, '_request_memory_dir', None)
        new_doc._request_turn_saver = getattr(context_doc, '_request_turn_saver', None)

        # CRITICAL: Preserve query_analysis from Phase 0 if gatherer didn't load it
        if not new_doc.query_analysis and context_doc.query_analysis:
            new_doc.query_analysis = context_doc.query_analysis
            logger.warning("[UnifiedFlow] Recovered Phase 0 query_analysis")

        # Carry over §1 (Query Analysis Validation) from old context_doc
        section1_content = context_doc.get_section(1)
        if section1_content and not new_doc.has_section(1):
            new_doc.append_section(1, "Query Analysis Validation", section1_content)

        logger.info(f"[UnifiedFlow] Phase 2 complete: §2 added ({len(new_doc.source_references)} sources)")
        return new_doc

    async def _refresh_context(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        mode: str,
        trace_id: str = ""
    ) -> ContextDocument:
        """Refresh context by re-running Phase 2.1/2.2 and return updated context."""
        logger.info("[UnifiedFlow] Refreshing context (Phase 2.1/2.2) per Planner request")
        refreshed = await self._phase2_context_gatherer(context_doc)
        self._write_context_md(turn_dir, refreshed)
        return refreshed

    # Note: _phase3_planner was removed (2026-02-03) - dead code
    # The system now uses _phase3_4_planning_loop which delegates to PlanningLoop

    async def _phase3_4_planning_loop(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        mode: str,
        pre_intent: str = "unknown",
        trace_id: str = ""
    ) -> Tuple[ContextDocument, str, str]:
        """Phase 3-4: Planner-Executor-Coordinator Loop. Delegates to PlanningLoop."""
        recipe = load_recipe(f"pipeline/phase3_planner_{mode}")

        self.planning_loop.set_callbacks(
            write_context_md=self._write_context_md,
            check_budget=self._check_budget,
            inject_tooling_context=self._inject_tooling_context,
            execute_single_tool=self._execute_single_tool,
            record_tool_call=self._record_tool_call,
            summarize_tool_results=self._summarize_tool_results,
            summarize_claims_batch=self._summarize_claims_batch,
            build_ticket_content=self._build_ticket_content,
            build_toolresults_content=self._build_toolresults_content,
            build_ticket_from_plan=self._build_ticket_from_plan,
            write_research_documents=self._write_research_documents,
            update_knowledge_graph=self._update_knowledge_graph,
            emit_phase_event=self._emit_phase_event,
            update_section3_from_planner=self._update_section3_from_planner,
            update_section3_from_strategic_plan=self._update_section3_from_strategic_plan,
            initialize_plan_state=self._initialize_plan_state,
            format_goals=self._format_goals,
            phase4_executor_loop=self._phase4_executor_loop,
            refresh_context=self._refresh_context,
        )

        return await self.planning_loop.run(
            context_doc=context_doc,
            turn_dir=turn_dir,
            mode=mode,
            pre_intent=pre_intent,
            trace_id=trace_id,
            recipe=recipe,
        )

    def _parse_planner_decision(self, llm_response: str) -> Dict[str, Any]:
        """Parse Planner decision. Delegates to ResponseParser."""
        return self.response_parser.parse_planner_decision(llm_response)

    def _update_section3_from_planner(
        self,
        context_doc: ContextDocument,
        planner_decision: Dict[str, Any],
        route_to: str
    ):
        """Update §3 from Planner. Delegates to SectionFormatter."""
        self.section_formatter.update_section3_from_planner(context_doc, planner_decision, route_to)

    def _update_section3_from_strategic_plan(
        self,
        context_doc: ContextDocument,
        strategic_plan: Dict[str, Any]
    ):
        """Update §3 from Strategic Plan. Delegates to SectionFormatter."""
        self.section_formatter.update_section3_from_strategic_plan(context_doc, strategic_plan)

    def _format_goals(self, goals: List[Dict[str, Any]]) -> str:
        """Format goals for logging. Delegates to SectionFormatter."""
        return self.section_formatter.format_goals(goals)

    # =========================================================================
    # PHASE 4: EXECUTOR LOOP (NEW - 9-phase architecture)
    # =========================================================================

    async def _phase4_executor_loop(
        self,
        context_doc: ContextDocument,
        strategic_plan: Dict[str, Any],
        turn_dir: TurnDirectory,
        mode: str,
        trace_id: str = ""
    ) -> Tuple[ContextDocument, str, str]:
        """
        Phase 4: Executor Loop (Tactical) - Delegates to ExecutorLoop.

        See libs.gateway.orchestration.executor_loop for implementation.
        """
        # Load executor recipe for the callback closure
        recipe = select_recipe("executor", mode)

        # Create callback that includes recipe
        async def call_executor_llm(ctx_doc, plan, tdir, iteration):
            return await self._call_executor_llm(ctx_doc, plan, tdir, recipe, iteration)

        # Set callbacks
        self.executor_loop.set_callbacks(
            write_context_md=self._write_context_md,
            emit_phase_event=self._emit_phase_event,
            call_executor_llm=call_executor_llm,
            format_goals=self._format_goals,
            format_executor_analysis=self._format_executor_analysis,
            append_to_section4=self._append_to_section4,
            try_workflow_execution=self._try_workflow_execution,
            coordinator_execute_command=lambda cmd, ctx, tdir: self._coordinator_execute_command(cmd, ctx, tdir, mode),
            format_executor_command_result=self._format_executor_command_result,
            build_ticket_from_plan=self._build_ticket_from_plan,
            build_toolresults_md=self._build_toolresults_md,
            execute_single_tool=self._execute_single_tool,
        )

        return await self.executor_loop.run(
            context_doc=context_doc,
            strategic_plan=strategic_plan,
            turn_dir=turn_dir,
            mode=mode,
            trace_id=trace_id,
        )

    async def _call_executor_llm(
        self,
        context_doc: ContextDocument,
        strategic_plan: Dict[str, Any],
        turn_dir: TurnDirectory,
        recipe,
        iteration: int
    ) -> Dict[str, Any]:
        """Call the Executor LLM to decide next tactical step."""
        # Build prompt pack
        pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
        mode = getattr(context_doc, "mode", "chat")
        self._inject_tooling_context(pack, mode, include_tools=False, include_workflows=True)
        prompt = pack.as_prompt()

        # Call LLM — MIND role (temp=0.6) for tactical reasoning
        # See: architecture/LLM-ROLES/llm-roles-reference.md
        temperature = recipe._raw_spec.get("llm_params", {}).get("temperature", 0.6)
        llm_response = await self.llm_client.call(
            prompt=prompt,
            role="executor",
            max_tokens=recipe.token_budget.output,
            temperature=temperature
        )

        return self.response_parser.parse_executor_decision(llm_response)

    # Note: _register_all_tools was removed (2026-02-03) - dead code
    # Tool registration is done in __init__ via register_all_tools()

    def _inject_tooling_context(
        self,
        pack,
        mode: str,
        include_tools: bool = True,
        include_workflows: bool = True,
    ) -> None:
        """Inject tool/workflow lists into doc pack. Delegates to WorkflowManager."""
        self.workflow_manager.inject_tooling_context(pack, mode, include_tools, include_workflows)

    async def _try_workflow_execution(
        self,
        command: str,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        workflow_hint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Try workflow execution. Delegates to WorkflowManager."""
        return await self.workflow_manager.try_workflow_execution(
            command, context_doc, turn_dir, workflow_hint=workflow_hint
        )

    async def _coordinator_execute_command(
        self,
        command: str,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        mode: str
    ) -> Dict[str, Any]:
        """
        Call Coordinator (Tool Expert) to translate command and execute.

        The Coordinator:
        1. Receives natural language command from Executor
        2. Translates to specific tool call
        3. Executes the tool
        4. Returns result with claims

        Returns:
            {
                "_type": "COORDINATOR_RESULT",
                "command_received": "...",
                "tool_selected": "tool.name",
                "tool_args": {...},
                "status": "success" | "error",
                "result": {...},
                "claims": [...]
            }
        """
        # Load coordinator recipe (mode-based selection)
        recipe = load_recipe(f"pipeline/phase4_coordinator_{mode}")

        # Build prompt with the command
        # Write command to §4 for Coordinator to read
        command_marker = f"**Executor Command:** {command}"
        self._append_to_section4(context_doc, command_marker)
        self._write_context_md(turn_dir, context_doc)

        # Build prompt pack and call LLM
        pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
        self._inject_tooling_context(pack, mode, include_tools=False, include_workflows=True)
        prompt = pack.as_prompt()

        # REFLEX role (temp=0.4) for deterministic tool selection
        # See: architecture/LLM-ROLES/llm-roles-reference.md
        temperature = recipe._raw_spec.get("llm_params", {}).get("temperature", 0.4)
        llm_response = await self.llm_client.call(
            prompt=prompt,
            role="coordinator",
            max_tokens=recipe.token_budget.output,
            temperature=temperature
        )

        # Parse workflow selection
        selection = self.response_parser.parse_json(llm_response)

        if selection.get("_type") == "NEEDS_CLARIFICATION" or selection.get("status") == "needs_more_info":
            return {
                "_type": "COORDINATOR_RESULT",
                "command_received": command,
                "status": "needs_more_info",
                "missing": selection.get("missing", []),
                "message": selection.get("message", ""),
                "result": None,
                "claims": [],
            }

        if selection.get("_type") == "MODE_VIOLATION" or selection.get("status") == "blocked":
            return {
                "_type": "COORDINATOR_RESULT",
                "command_received": command,
                "status": "blocked",
                "error": selection.get("error", ""),
                "requires_approval": selection.get("requires_approval", False),
                "result": None,
                "claims": [],
            }

        workflow_selected = selection.get("workflow_selected") or selection.get("workflow")
        workflow_args = selection.get("workflow_args", {}) or {}

        if not workflow_selected:
            return {
                "_type": "COORDINATOR_RESULT",
                "command_received": command,
                "status": "error",
                "error": "No workflow selected",
                "result": None,
                "claims": []
            }

        if "original_query" not in workflow_args:
            workflow_args["original_query"] = context_doc.query

        workflow_result = await self.workflow_manager.execute_workflow(
            workflow_selected,
            workflow_args,
            context_doc,
            turn_dir,
            mode,
        )

        claims = workflow_result.get("claims", [])
        if claims:
            missing_metadata = [
                c for c in claims if not c.get("url") or not c.get("source_ref")
            ]
            if missing_metadata:
                return {
                    "_type": "COORDINATOR_RESULT",
                    "command_received": command,
                    "workflow_selected": workflow_selected,
                    "workflow_args": workflow_args,
                    "status": "blocked",
                    "error": "Missing source metadata in workflow results",
                    "requires_retry": True,
                    "result": None,
                    "claims": claims,
                }

        workflow_result["command_received"] = command
        workflow_result["workflow_selected"] = workflow_selected
        workflow_result["workflow_args"] = workflow_args
        return workflow_result

    def _parse_tool_selection(self, llm_response: str) -> Dict[str, Any]:
        """Parse tool selection from Coordinator. Delegates to ResponseParser."""
        return self.response_parser.parse_tool_selection(llm_response)

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context_doc: ContextDocument,
        turn_dir: TurnDirectory
    ) -> Dict[str, Any]:
        """Execute a tool via ToolCatalog. Delegates to ToolExecutor."""
        return await self.tool_executor.execute_tool(tool_name, tool_args, context_doc, turn_dir)

    async def _execute_workflow(
        self,
        workflow_name: str,
        workflow_args: Dict[str, Any],
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
    ) -> Dict[str, Any]:
        """Execute a workflow via WorkflowManager."""
        mode = getattr(context_doc, "mode", "chat")
        return await self.workflow_manager.execute_workflow(
            workflow_name, workflow_args, context_doc, turn_dir, mode
        )

    def _format_executor_analysis(
        self,
        analysis: Dict[str, Any],
        goals_progress: List[Dict[str, Any]],
        iteration: int
    ) -> str:
        """Format executor analysis. Delegates to SectionFormatter."""
        return self.section_formatter.format_executor_analysis(analysis, goals_progress, iteration)

    def _format_executor_command_result(
        self,
        command: str,
        coordinator_result: Dict[str, Any],
        goals_progress: List[Dict[str, Any]],
        iteration: int
    ) -> str:
        """Format executor command result. Delegates to SectionFormatter."""
        return self.section_formatter.format_executor_command_result(command, coordinator_result, goals_progress, iteration)

    def _append_to_section4(self, context_doc: ContextDocument, content: str):
        """Append to §4. Delegates to SectionFormatter."""
        self.section_formatter.append_to_section4(context_doc, content)

    def _build_ticket_from_plan(
        self,
        strategic_plan: Dict[str, Any],
        step_log: List[str]
    ) -> str:
        """Build ticket content. Delegates to DocumentWriter."""
        return self.document_writer.build_ticket_from_plan(strategic_plan, step_log)

    def _build_toolresults_md(
        self,
        tool_results: List[Dict[str, Any]],
        claims: List[Dict[str, Any]]
    ) -> str:
        """Build toolresults.md. Delegates to DocumentWriter."""
        return self.document_writer.build_toolresults_md(tool_results, claims)

    async def _phase4_coordinator(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        mode: str,
        trace_id: str = ""
    ) -> Tuple[ContextDocument, str, str]:
        """
        Phase 4: Coordinator (Agent Loop)
        Delegates to AgentLoop for the actual execution.
        """
        # Load recipe for config
        recipe = load_recipe(f"pipeline/phase4_coordinator_{mode}")

        # Set callbacks for the agent loop
        self.agent_loop.set_callbacks(
            write_context_md=self._write_context_md,
            check_budget=self._check_budget,
            inject_tooling_context=self._inject_tooling_context,
            execute_single_tool=self._execute_single_tool,
            execute_workflow=self._execute_workflow,
            hash_tool_args=self._hash_tool_args,
            detect_circular_calls=self._detect_circular_calls,
            summarize_tool_results=self._summarize_tool_results,
            summarize_claims_batch=self._summarize_claims_batch,
            build_ticket_content=self._build_ticket_content,
            build_toolresults_content=self._build_toolresults_content,
            write_research_documents=self._write_research_documents,
            update_knowledge_graph=self._update_knowledge_graph,
            emit_phase_event=self._emit_phase_event,
        )

        return await self.agent_loop.run(
            context_doc=context_doc,
            turn_dir=turn_dir,
            mode=mode,
            trace_id=trace_id,
            recipe=recipe,
        )

    def _parse_agent_decision(self, llm_response: str) -> Dict[str, Any]:
        """Parse agent decision. Delegates to ResponseParser."""
        return self.response_parser.parse_agent_decision(llm_response)

    async def _phase5_synthesis(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        mode: str
    ) -> Tuple[ContextDocument, str]:
        """Phase 6: Synthesis. Delegates to SynthesisPhase."""
        self.synthesis_phase.set_callbacks(
            write_context_md=self._write_context_md,
            check_budget=self._check_budget,
            parse_json_response=self._parse_json_response,
        )
        recipe = load_recipe(f"pipeline/phase5_synthesizer_{mode}")
        return await self.synthesis_phase.run_synthesis(context_doc, turn_dir, mode, recipe)

    async def _call_validator_llm_impl(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        revision_count: int
    ) -> Dict[str, Any]:
        """Call the validator LLM and return parsed result."""
        recipe = load_recipe("pipeline/phase6_validator")
        self._check_budget(context_doc, recipe, f"Phase 7 Validation (revision={revision_count})")
        pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
        prompt = pack.as_prompt()
        # MIND role (temp=0.6) for nuanced quality judgment
        # See: architecture/LLM-ROLES/llm-roles-reference.md
        temperature = recipe._raw_spec.get("llm_params", {}).get("temperature", 0.6)
        llm_response = await self.llm_client.call(
            prompt=prompt,
            role="validator",
            max_tokens=recipe.token_budget.output,
            temperature=temperature
        )
        return self._parse_json_response(llm_response)

    async def _phase6_validation(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        response: str,
        mode: str,
        loop_count: int = 0
    ) -> Tuple[ContextDocument, str, ValidationResult]:
        """
        Phase 7: Validation - Delegates to ValidationHandler.

        See libs.gateway.validation.validation_handler for implementation.
        """
        # Set callbacks
        self.validation_handler.set_callbacks(
            write_context_md=self._write_context_md,
            call_validator_llm=self._call_validator_llm_impl,
            parse_json_response=self._parse_json_response,
            check_budget=self._check_budget,
            revise_synthesis=self._revise_synthesis,
            get_unhealthy_urls=get_unhealthy_urls,
            principle_extractor=PrincipleExtractor(self.llm_client),
        )

        return await self.validation_handler.run_validation(
            context_doc=context_doc,
            turn_dir=turn_dir,
            response=response,
            mode=mode,
            loop_count=loop_count,
        )

    def _write_validation_section(
        self,
        context_doc: ContextDocument,
        result: str,
        confidence: float,
        revision_count: int,
        issues: List[str],
        suggested_fixes: Optional[List[str]] = None,
        checks: Optional[Dict[str, bool]] = None,
        urls_ok: bool = True,
        price_ok: bool = True
    ):
        """Write §7 Validation section. Delegates to ValidationHandler."""
        self.validation_handler.write_validation_section(
            context_doc, result, confidence, revision_count, issues,
            suggested_fixes, checks, urls_ok, price_ok
        )

    async def _phase7_save(
        self,
        context_doc: ContextDocument,
        response: str,
        ticket_content: Optional[str] = None,
        toolresults_content: Optional[str] = None,
        validation_result: Optional["ValidationResult"] = None
    ) -> Path:
        """
        Phase 8: Save

        Saves all turn documents (unsummarized) and indexes the turn.
        """
        logger.info(f"[UnifiedFlow] Phase 8: Save")

        # Convert ValidationResult dataclass to dict for turn_saver
        validation_dict = None
        if validation_result:
            validation_dict = {
                "decision": validation_result.decision,
                "confidence": validation_result.confidence,
                "issues": validation_result.issues,
                "revision_hints": validation_result.revision_hints
                # Note: 'learning' field removed (2025-12-30) - learning happens
                # implicitly via turn indexing, not explicit LEARN decisions
            }

        # Use request-specific turn_saver from context_doc, fall back to instance default
        turn_saver = getattr(context_doc, '_request_turn_saver', None) or self.turn_saver

        turn_dir = await turn_saver.save_turn(
            context_doc=context_doc,
            response=response,
            ticket_content=ticket_content,
            toolresults_content=toolresults_content,
            validation_result=validation_dict
        )

        logger.info(f"[UnifiedFlow] Phase 7 complete: saved to {turn_dir}")
        return turn_dir

    # ========== Helper Methods ==========

    def _check_budget(
        self,
        context_doc: ContextDocument,
        recipe,
        phase_name: str
    ) -> None:
        """Check budget. Delegates to ExecutionGuard."""
        self.execution_guard.check_budget(context_doc, recipe, phase_name)

    def _detect_circular_calls(self, call_history: List[Tuple[str, str]], window: int = 4) -> bool:
        """Detect circular call patterns. Delegates to ExecutionGuard."""
        return self.execution_guard.detect_circular_calls(call_history, window)

    def _hash_tool_args(self, args: Dict[str, Any]) -> str:
        """Hash tool arguments. Delegates to ExecutionGuard."""
        return self.execution_guard.hash_tool_args(args)

    # Note: _get_next_turn_number was removed (2026-02-03) - dead code
    # Use TurnCounter directly: TurnCounter(turns_dir).get_next_turn_number(session_id)

    def _write_context_md(self, turn_dir: TurnDirectory, context_doc: ContextDocument):
        """Write context.md. Delegates to DocumentWriter."""
        self.document_writer.write_context_md(turn_dir, context_doc)

    def _write_ticket_md(self, turn_dir: TurnDirectory, ticket: Dict[str, Any]):
        """Write ticket.md. Delegates to DocumentWriter."""
        self.document_writer.write_ticket_md(turn_dir, ticket)

    def _load_constraints_payload(self, turn_dir: TurnDirectory) -> Dict[str, Any]:
        """Load constraints. Delegates to PlanStateManager."""
        return self.plan_state_manager.load_constraints_payload(turn_dir)

    def _load_plan_state(self, turn_dir: TurnDirectory) -> Optional[Dict[str, Any]]:
        """Load plan state. Delegates to PlanStateManager."""
        return self.plan_state_manager.load_plan_state(turn_dir)

    def _initialize_plan_state(
        self,
        turn_dir: TurnDirectory,
        goals: List[Any],
        phase: int = 3,
        overwrite: bool = True
    ) -> None:
        """Initialize plan state. Delegates to PlanStateManager."""
        self.plan_state_manager.initialize_plan_state(turn_dir, goals, phase, overwrite)

    def _check_constraints_for_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        constraints_payload: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        """Check constraints. Delegates to PlanStateManager."""
        return self.plan_state_manager.check_constraints_for_tool(tool_name, tool_args, constraints_payload)

    def _update_plan_state_from_validation(
        self,
        turn_dir: TurnDirectory,
        validation_result: Optional["ValidationResult"]
    ) -> None:
        """Update plan state from validation. Delegates to PlanStateManager."""
        self.plan_state_manager.update_from_validation(turn_dir, validation_result)

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from LLM response. Delegates to ResponseParser."""
        return self.response_parser.parse_json(response)

    def _determine_routing_from_ticket(self, ticket: Dict[str, Any], pre_intent: str) -> str:
        """
        Determine routing from ticket.

        DESIGN PRINCIPLE: Trust the Planner's decision. The Planner prompt is responsible
        for specifying the correct route_to and tools. Python code should not override
        or second-guess this decision with fallback logic.

        If the Planner specifies coordinator without tools, that indicates a prompt issue
        that should be fixed in the prompt, not worked around in code.
        """
        route = ticket.get("route_to", "")
        tools = ticket.get("recommended_tools", [])
        tasks = ticket.get("tasks", [])

        # Trust explicit route from Planner
        if route:
            return route

        # If Planner specified tasks or tools, use coordinator
        if tools or tasks:
            return "coordinator"

        # Default to synthesis (generate from context)
        return "synthesis"

    async def _execute_tools(
        self,
        plan: Dict[str, Any],
        context_doc: ContextDocument,
        mode: str,
        skip_urls: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Execute tools from plan. Delegates to ToolExecutor."""
        return await self.tool_executor.execute_tools(plan, context_doc, skip_urls)

    async def _execute_single_tool(
        self,
        tool_name: str,
        config: Dict[str, Any],
        context_doc: ContextDocument,
        skip_urls: List[str] = None,
        turn_dir: Optional[TurnDirectory] = None
    ) -> Dict[str, Any]:
        """Execute a single tool and extract claims. Delegates to ToolExecutor."""
        return await self.tool_executor.execute_single_tool(tool_name, config, context_doc, skip_urls, turn_dir)

    def _extract_claims_from_result(
        self,
        tool_name: str,
        result: Dict[str, Any],
        config: Dict[str, Any],
        skip_urls: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Extract claims from tool result. Delegates to ClaimsManager."""
        return self.claims_manager.extract_claims_from_result(tool_name, result, config, skip_urls)

    async def _execute_memory_tool(
        self,
        tool_name: str,
        tool_request: Dict[str, Any],
        context_doc: ContextDocument
    ) -> Dict[str, Any]:
        """Execute memory.* tools locally. Delegates to ToolExecutor."""
        return await self.tool_executor.execute_memory_tool(tool_name, tool_request, context_doc)

    async def _check_tool_approval(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """Check if tool requires approval and wait for it. Delegates to ToolExecutor."""
        return await self.tool_executor._check_tool_approval(tool_name, tool_args, session_id)

    def _summarize_tool_results(self, tool_results: List[Dict[str, Any]]) -> str:
        """Summarize tool results. Delegates to ClaimsManager."""
        return self.claims_manager.summarize_tool_results(tool_results)

    async def _summarize_claims_batch(
        self,
        claims: List[Dict[str, Any]],
        max_chars_per_claim: int = 100
    ) -> List[str]:
        """Summarize claims batch. Delegates to ClaimsManager."""
        return await self.claims_manager.summarize_claims_batch(claims, max_chars_per_claim)

    def _extract_claim_key_facts(self, content: str, max_chars: int = 100) -> str:
        """Extract key facts from claim. Delegates to ClaimsManager."""
        return self.claims_manager.extract_claim_key_facts(content, max_chars)

    # Note: _extract_resolved_query_from_plan was removed (2026-02-03) - dead code
    # The ToolExecutor has its own version at libs/gateway/execution/tool_executor.py:473

    def _build_ticket_content(self, context_doc: ContextDocument, plan: Dict[str, Any]) -> str:
        """Build ticket content. Delegates to DocumentWriter."""
        return self.document_writer.build_ticket_content(context_doc, plan)

    def _build_toolresults_content(
        self,
        context_doc: ContextDocument,
        tool_results: List[Dict[str, Any]]
    ) -> str:
        """Build toolresults content. Delegates to DocumentWriter."""
        return self.document_writer.build_toolresults_content(context_doc, tool_results)

    async def _write_research_documents(
        self,
        tool_results: List[Dict[str, Any]],
        context_doc: ContextDocument
    ):
        """Write research documents. Delegates to ResearchHandler."""
        await self.research_handler.write_research_documents(tool_results, context_doc)

    async def _update_knowledge_graph(
        self,
        tool_results: List[Dict[str, Any]],
        context_doc: ContextDocument
    ):
        """Update knowledge graph. Delegates to ResearchHandler."""
        await self.research_handler.update_knowledge_graph(tool_results, context_doc)

    async def _revise_synthesis(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        original_response: str,
        revision_hints: str,
        mode: str
    ) -> str:
        """Revise synthesis. Delegates to SynthesisPhase."""
        return await self.synthesis_phase.revise_synthesis(
            context_doc, turn_dir, original_response, revision_hints, mode
        )

    def _extract_clarification(self, context_doc: ContextDocument) -> str:
        """Extract clarification. Delegates to QueryResolver."""
        return self.query_resolver.extract_clarification(context_doc)

    async def _resolve_query_from_context(self, query: str, context_doc: ContextDocument) -> str:
        """DEPRECATED: Delegates to QueryResolver."""
        return await self.query_resolver.resolve_query_from_context(query, context_doc)

    async def _resolve_query_with_n1(self, query: str, turn_number: int, session_id: str) -> str:
        """Resolve N-1 references. Delegates to QueryResolver."""
        return await self.query_resolver.resolve_query_with_n1(query, turn_number, session_id)

    # NOTE: _context_has_product_data method was removed (PIPELINE_FIX_PLAN.md)
    # It was only used by the COMMERCE OVERRIDE block which was also removed
