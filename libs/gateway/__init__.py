"""
Gateway - Orchestration layer for Panda (8-phase pipeline).

This module is organized into subpackages:
- context/: Context documents, gathering, query analysis (Phase 1-2)
- phases/: Pipeline phase implementations (Phase 1-8)
- execution/: Tool execution, workflows, safety (Phase 4-5)
- parsing/: Response parsing, claims extraction
- validation/: Validation, metrics, confidence (Phase 7)
- persistence/: Turn management, storage (Phase 8)
- research/: Research documents, summarization
- knowledge/: Knowledge graph, entities
- llm/: Gateway-specific LLM recipes (distinct from libs/llm which provides the client)
- util/: Utilities, error handling

Note: libs/llm provides the core LLM client and model routing.
      libs/gateway/llm provides gateway-specific recipe loading.

For backward compatibility, all commonly-used classes are re-exported here.
"""

# ============================================================================
# BACKWARD COMPATIBILITY RE-EXPORTS
# These allow existing imports like `from libs.gateway.X import Y` to work
# even after files have been moved to subpackages.
# ============================================================================

# Execution (from libs.gateway.execution)
from libs.gateway.execution.tool_executor import ToolExecutor, get_tool_executor
from libs.gateway.execution.tool_catalog import ToolCatalog
from libs.gateway.execution.execution_guard import ExecutionGuard, hash_tool_args, detect_circular_calls
from libs.gateway.execution.permission_validator import get_validator, PermissionDecision
from libs.gateway.execution.tool_approval import (
    ToolApprovalManager,
    get_tool_approval_manager,
    APPROVAL_SYSTEM_ENABLED,
)
from libs.gateway.execution.workflow_registry import WorkflowRegistry
from libs.gateway.execution.workflow_matcher import WorkflowMatcher
from libs.gateway.execution.workflow_step_runner import WorkflowStepRunner, WorkflowResult

# Parsing (from libs.gateway.parsing)
from libs.gateway.parsing.response_parser import (
    ResponseParser,
    get_response_parser,
    parse_json_response,
    parse_planner_decision,
    parse_executor_decision,
    parse_tool_selection,
    parse_agent_decision,
)
from libs.gateway.parsing.claims_manager import ClaimsManager, get_claims_manager

# Validation (from libs.gateway.validation)
from libs.gateway.validation.validation_handler import (
    ValidationHandler,
    ValidationFailureContext,
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

# Context (from libs.gateway.context)
from libs.gateway.context.context_document import ContextDocument, TurnMetadata, extract_keywords
from libs.gateway.context.context_gatherer_2phase import ContextGatherer2Phase
from libs.gateway.context.doc_pack_builder import DocPackBuilder
from libs.gateway.context.query_analyzer import QueryAnalyzer, QueryAnalysis, ContentReference

# Persistence (from libs.gateway.persistence)
from libs.gateway.persistence.turn_manager import TurnDirectory
from libs.gateway.persistence.turn_saver import TurnSaver
from libs.gateway.persistence.turn_counter import TurnCounter
from libs.gateway.persistence.turn_search_index import TurnSearchIndex
from libs.gateway.persistence.turn_index_db import get_turn_index_db
from libs.gateway.persistence.user_paths import UserPathResolver

# Research (from libs.gateway.research)
from libs.gateway.research.research_document import ResearchDocumentWriter, ResearchDocument
from libs.gateway.research.research_index_db import get_research_index_db
from libs.gateway.research.smart_summarization import SmartSummarizer, get_summarizer

# Util (from libs.gateway.util)
from libs.gateway.util.error_compactor import ErrorCompactor, CompactedError, get_error_compactor
from libs.gateway.util.principle_extractor import PrincipleExtractor, ImprovementPrinciple
from libs.gateway.util.panda_loop import PandaLoop, LoopResult, format_loop_summary

# LLM (from libs.gateway.llm)
from libs.gateway.llm.recipe_loader import load_recipe, select_recipe

__all__ = [
    # Execution
    "ToolExecutor",
    "get_tool_executor",
    "ToolCatalog",
    "ExecutionGuard",
    "hash_tool_args",
    "detect_circular_calls",
    "get_validator",
    "PermissionDecision",
    "ToolApprovalManager",
    "get_tool_approval_manager",
    "APPROVAL_SYSTEM_ENABLED",
    "WorkflowRegistry",
    "WorkflowMatcher",
    "WorkflowStepRunner",
    "WorkflowResult",
    # Parsing
    "ResponseParser",
    "get_response_parser",
    "parse_json_response",
    "parse_planner_decision",
    "parse_executor_decision",
    "parse_tool_selection",
    "parse_agent_decision",
    "ClaimsManager",
    "get_claims_manager",
    # Validation
    "ValidationHandler",
    "ValidationFailureContext",
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
    # Context
    "ContextDocument",
    "TurnMetadata",
    "extract_keywords",
    "ContextGatherer2Phase",
    "DocPackBuilder",
    "QueryAnalyzer",
    "QueryAnalysis",
    "ContentReference",
    # Persistence
    "TurnDirectory",
    "TurnSaver",
    "TurnCounter",
    "TurnSearchIndex",
    "get_turn_index_db",
    "UserPathResolver",
    # Research
    "ResearchDocumentWriter",
    "ResearchDocument",
    "get_research_index_db",
    "SmartSummarizer",
    "get_summarizer",
    # Util
    "ErrorCompactor",
    "CompactedError",
    "get_error_compactor",
    "PrincipleExtractor",
    "ImprovementPrinciple",
    "PandaLoop",
    "LoopResult",
    "format_loop_summary",
    # LLM
    "load_recipe",
    "select_recipe",
]
