"""
Unified Flow Handler - 9-phase pipeline with 3-tier Planner-Executor-Coordinator loop

Implements the unified document IO architecture:
- Phase 0: Query Analyzer (intent classification, reference resolution)
- Phase 1: Context Gatherer (search prior turns, build §1)
- Phase 2: Reflection (PROCEED/CLARIFY)
- Phase 3: Planner (Strategic - define goals and approach, outputs STRATEGIC_PLAN)
- Phase 4: Executor (Tactical - issues natural language commands, tracks goal progress)
- Phase 5: Coordinator (Tool Expert - translates commands to tool calls)
- Phase 6: Synthesis (response generation)
- Phase 7: Validation (APPROVE/RETRY/REVISE/FAIL)
- Phase 8: Save (procedural save, no LLM)

ARCHITECTURAL UPDATE (2026-01-24):
- Added Executor phase between Planner and Coordinator
- Planner now outputs STRATEGIC_PLAN with route_to: executor | synthesis | clarify
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

from libs.gateway.context_document import ContextDocument, TurnMetadata, extract_keywords
from apps.services.gateway.services.thinking import emit_thinking_event, ThinkingEvent
from libs.gateway.turn_search_index import TurnSearchIndex
from libs.gateway.turn_saver import TurnSaver
from libs.gateway.turn_manager import TurnDirectory
from libs.gateway.context_gatherer_2phase import ContextGatherer2Phase
# Note: ContextGathererRole (deprecated) removed - use ContextGatherer2Phase only
from libs.gateway.turn_counter import TurnCounter
from libs.gateway.user_paths import UserPathResolver
from libs.gateway.research_document import ResearchDocumentWriter, ResearchDocument
from libs.gateway.research_index_db import get_research_index_db
from libs.gateway.recipe_loader import load_recipe, select_recipe
from libs.gateway.doc_pack_builder import DocPackBuilder
from libs.gateway.smart_summarization import SmartSummarizer, get_summarizer
from libs.gateway.query_analyzer import QueryAnalyzer, QueryAnalysis, ContentReference
from libs.gateway.pandora_loop import PandoraLoop, LoopResult, format_loop_summary
from libs.gateway.response_confidence import (
    ResponseConfidenceCalculator,
    AggregateConfidence,
    calculate_aggregate_confidence,
)
from libs.gateway.principle_extractor import (
    PrincipleExtractor,
    ImprovementPrinciple,
)
from libs.gateway.error_compactor import (
    ErrorCompactor,
    CompactedError,
    get_error_compactor,
)
from libs.gateway.tool_approval import (
    ToolApprovalManager,
    get_tool_approval_manager,
    APPROVAL_SYSTEM_ENABLED,
)
from libs.core.url_health import (
    check_url_health,
    get_unhealthy_urls,
    URLHealthStatus,
)
from libs.gateway.turn_index_db import get_turn_index_db

# Memory tools for Planner-Coordinator loop (Tier 2 implementation)
from apps.services.orchestrator.memory_mcp import (
    get_memory_mcp,
    MemorySearchRequest,
    MemorySaveRequest,
    UnifiedMemoryMCP
)

# Intervention system for Category B failures (#56 in IMPLEMENTATION_ROADMAP.md)
from apps.services.orchestrator.intervention_manager import InterventionManager, InterventionStatus

# Workflow system - predictable tool sequences
from libs.gateway.workflow_registry import WorkflowRegistry
from libs.gateway.workflow_matcher import WorkflowMatcher
from libs.gateway.workflow_executor import WorkflowExecutor, WorkflowResult

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

def extract_prices_from_text(text: str) -> List[str]:
    """Extract price values from text (e.g., $624.99, $1,299.00)."""
    # Match prices like $624.99 or $1,299.00 or $999
    pattern = r'\$[\d,]+(?:\.\d{2})?'
    matches = re.findall(pattern, text)
    # Normalize: remove commas and ensure consistent format
    normalized = []
    for m in matches:
        # Remove $ and commas, convert to float for comparison
        clean = m.replace('$', '').replace(',', '')
        try:
            val = float(clean)
            normalized.append(f"${val:.2f}")
        except ValueError:
            pass
    return normalized


def prices_match(response_prices: List[str], research_prices: List[str], tolerance: float = 0.01) -> Tuple[bool, List[str]]:
    """
    Check if response prices exist in research prices.

    Returns (all_matched, missing_prices)
    """
    if not response_prices:
        return True, []

    # Convert to float sets for comparison
    def to_float(p):
        return float(p.replace('$', '').replace(',', ''))

    research_values = set()
    for p in research_prices:
        try:
            research_values.add(to_float(p))
        except ValueError:
            pass

    missing = []
    for rp in response_prices:
        try:
            rv = to_float(rp)
            # Check if this price exists in research (with tolerance)
            found = any(abs(rv - rv2) < tolerance for rv2 in research_values)
            if not found:
                missing.append(rp)
        except ValueError:
            pass

    return len(missing) == 0, missing


def extract_urls_from_text(text: str) -> List[str]:
    """Extract URLs from text."""
    # Match http/https URLs
    url_pattern = r'https?://[^\s\)\]\>\"\'<]+'
    matches = re.findall(url_pattern, text)
    # Clean up trailing punctuation
    cleaned = []
    for url in matches:
        # Remove trailing punctuation that might have been captured
        url = url.rstrip('.,;:!?)')
        if url and len(url) > 10:  # Minimum sensible URL length
            cleaned.append(url)
    return list(set(cleaned))  # Deduplicate


def normalize_url_for_comparison(url: str) -> str:
    """
    Normalize URL for comparison purposes.

    Handles common variations:
    - www. prefix (remove for comparison)
    - Trailing slashes
    - Case sensitivity in domain
    - Query parameters (remove for domain matching)
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url.lower())
        domain = parsed.netloc
        path = parsed.path

        # Remove www. prefix for comparison
        if domain.startswith('www.'):
            domain = domain[4:]

        # Remove trailing slashes from path
        path = path.rstrip('/')

        # Return normalized domain + path (no query params for matching)
        return f"{domain}{path}"
    except Exception:
        return url.lower().rstrip('/')


def url_matches_any(url: str, known_urls: List[str]) -> bool:
    """
    Check if URL matches any of the known URLs (with normalization).

    Uses progressive matching:
    1. Exact match (after normalization)
    2. Domain match (same site, different path is OK)
    """
    normalized = normalize_url_for_comparison(url)
    url_domain = normalized.split('/')[0] if '/' in normalized else normalized

    for known in known_urls:
        known_norm = normalize_url_for_comparison(known)
        known_domain = known_norm.split('/')[0] if '/' in known_norm else known_norm

        # Exact path match
        if normalized == known_norm:
            return True

        # Domain match (we visited this site, paths may differ slightly)
        if url_domain == known_domain:
            return True

    return False


async def verify_url(session: aiohttp.ClientSession, url: str, timeout: int = VALIDATION_URL_TIMEOUT) -> Tuple[str, bool, str]:
    """
    DEPRECATED: This function is no longer used for validation.

    URL verification now uses cross-referencing against research.json instead of
    network requests. This avoids the problem of sites blocking aiohttp requests
    while allowing Playwright browser requests (which research uses).

    Kept for potential future use cases where direct URL verification is needed.

    Original purpose: Verify if a URL is still valid via HEAD request, with GET fallback.
    Returns: (url, is_valid, error_message)
    """
    try:
        # Try HEAD first (lightweight)
        async with session.head(url, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=True) as resp:
            if resp.status == 200:
                return (url, True, "")
            elif resp.status in (301, 302, 303, 307, 308):
                # Redirect is OK
                return (url, True, "")
            elif resp.status == 405:
                # Method Not Allowed - try GET instead (common for Amazon)
                pass  # Fall through to GET below
            else:
                return (url, False, f"HTTP {resp.status}")
    except asyncio.TimeoutError:
        return (url, False, "timeout")
    except aiohttp.ClientError as e:
        # Connection errors - try GET as fallback
        pass
    except Exception as e:
        return (url, False, str(e)[:50])

    # Fallback: Try GET request (for sites that block HEAD)
    try:
        # Use a short read to avoid downloading entire page
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=True) as resp:
            if resp.status == 200:
                return (url, True, "")
            elif resp.status in (301, 302, 303, 307, 308):
                return (url, True, "")
            else:
                return (url, False, f"HTTP {resp.status}")
    except asyncio.TimeoutError:
        return (url, False, "timeout")
    except aiohttp.ClientError as e:
        return (url, False, str(e)[:50])
    except Exception as e:
        return (url, False, str(e)[:50])


class UnifiedFlow:
    """
    Unified 7-Phase Flow Handler

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
        self.workflow_registry.load_all()
        self.workflow_matcher = WorkflowMatcher(self.workflow_registry)
        self.workflow_executor = WorkflowExecutor()
        self._register_workflow_tools()
        logger.info(f"[UnifiedFlow] Workflow system loaded: {len(self.workflow_registry.workflows)} workflows")

        # Phase timing and metrics tracking
        self._turn_metrics: Dict[str, Any] = {}
        self._phase_start_times: Dict[str, float] = {}

        logger.info(f"[UnifiedFlow] Initialized (enabled={UNIFIED_FLOW_ENABLED}, smart_summarization={SMART_SUMMARIZATION})")

    def _init_turn_metrics(self) -> Dict[str, Any]:
        """Initialize metrics for a new turn."""
        import time
        return {
            "turn_start": time.time(),
            "phases": {},
            "tokens": {"total_in": 0, "total_out": 0},
            "decisions": [],
            "tools_called": [],
            "retries": 0,
            "quality_score": 0.0,
            "validation_outcome": ""
        }

    def _start_phase(self, phase_name: str):
        """Mark the start of a phase for timing."""
        import time
        self._phase_start_times[phase_name] = time.time()
        logger.debug(f"[Metrics] Started phase: {phase_name}")

    def _end_phase(self, phase_name: str, tokens_in: int = 0, tokens_out: int = 0):
        """Mark the end of a phase and record metrics."""
        import time
        if phase_name not in self._phase_start_times:
            logger.warning(f"[Metrics] Phase {phase_name} was not started")
            return

        duration_ms = int((time.time() - self._phase_start_times[phase_name]) * 1000)

        if "phases" not in self._turn_metrics:
            self._turn_metrics["phases"] = {}

        self._turn_metrics["phases"][phase_name] = {
            "duration_ms": duration_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out
        }

        # Update totals
        if "tokens" in self._turn_metrics:
            self._turn_metrics["tokens"]["total_in"] += tokens_in
            self._turn_metrics["tokens"]["total_out"] += tokens_out

        logger.debug(f"[Metrics] Ended phase: {phase_name} ({duration_ms}ms, {tokens_in}/{tokens_out} tokens)")

    def _record_decision(self, decision_type: str, decision_value: str, context: str = ""):
        """Record a decision made during the turn."""
        if "decisions" not in self._turn_metrics:
            self._turn_metrics["decisions"] = []

        self._turn_metrics["decisions"].append({
            "type": decision_type,
            "value": decision_value,
            "context": context
        })

    def _record_tool_call(self, tool_name: str, success: bool, duration_ms: int = 0):
        """Record a tool call."""
        if "tools_called" not in self._turn_metrics:
            self._turn_metrics["tools_called"] = []

        self._turn_metrics["tools_called"].append({
            "tool": tool_name,
            "success": success,
            "duration_ms": duration_ms
        })

    def _finalize_turn_metrics(self, quality_score: float, validation_outcome: str) -> Dict[str, Any]:
        """Finalize and return turn metrics."""
        import time
        self._turn_metrics["turn_end"] = time.time()
        self._turn_metrics["total_duration_ms"] = int(
            (self._turn_metrics["turn_end"] - self._turn_metrics.get("turn_start", time.time())) * 1000
        )
        self._turn_metrics["quality_score"] = quality_score
        self._turn_metrics["validation_outcome"] = validation_outcome
        return self._turn_metrics

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
        """Emit a thinking event for UI visualization."""
        phase_names = {
            0: "query_analyzer",
            1: "context_gatherer",
            2: "reflection",
            3: "planner",
            4: "executor",
            5: "coordinator",
            6: "synthesis",
            7: "validation",
            8: "complete"
        }

        # Default confidence based on status if not explicitly provided
        if confidence is None:
            if status == "completed":
                confidence = 1.0
            elif status == "active":
                confidence = 0.5
            else:
                confidence = 0.0

        stage_name = f"phase_{phase}_{phase_names.get(phase, 'unknown')}"
        logger.info(f"[UnifiedFlow] Emitting thinking event: trace={trace_id}, stage={stage_name}, status={status}")
        await emit_thinking_event(ThinkingEvent(
            trace_id=trace_id,
            stage=stage_name,
            status=status,
            confidence=confidence,
            duration_ms=duration_ms,
            details=details or {},
            reasoning=reasoning,
            timestamp=time.time()
        ))

    def _cross_check_prices(self, response: str, turn_dir: TurnDirectory) -> Tuple[bool, List[str], str]:
        """
        Cross-check response prices against authoritative tool results.

        Uses toolresults.md as the authoritative source for exact prices.
        Per architecture spec (phase6-validation.md), price priority is:
        1. toolresults.md - Exact prices (authoritative)
        2. section 4 claims table - LLM-summarized
        3. section 1 gathered context - Prior research (may be stale)

        Args:
            response: The synthesized response text
            turn_dir: Turn directory to find toolresults.md

        Returns:
            (passed, missing_prices, hint_message)
        """
        if not ENABLE_PRICE_CROSSCHECK:
            return True, [], ""

        # Extract prices from response
        response_prices = extract_prices_from_text(response)
        if not response_prices:
            logger.debug("[UnifiedFlow] No prices in response, skipping cross-check")
            return True, [], ""

        # Load toolresults.md for this turn (authoritative source per spec)
        toolresults_path = turn_dir.path / "toolresults.md"
        if not toolresults_path.exists():
            # Fallback to research.md if toolresults.md doesn't exist
            research_path = turn_dir.path / "research.md"
            if not research_path.exists():
                logger.debug("[UnifiedFlow] No toolresults.md or research.md, skipping cross-check")
                return True, [], ""
            source_path = research_path
            source_name = "research.md"
        else:
            source_path = toolresults_path
            source_name = "toolresults.md"

        try:
            source_content = source_path.read_text()
            source_prices = extract_prices_from_text(source_content)

            if not source_prices:
                logger.debug(f"[UnifiedFlow] No prices in {source_name}, skipping cross-check")
                return True, [], ""

            # Compare prices
            all_matched, missing = prices_match(response_prices, source_prices)

            if not all_matched:
                hint = (
                    f"PRICE MISMATCH: Response contains prices {missing} not found in {source_name}. "
                    f"Tool results found these prices: {source_prices[:5]}. "
                    f"Please use only prices from the current tool execution data."
                )
                logger.warning(f"[UnifiedFlow] Price cross-check failed: {missing}")
                return False, missing, hint

            logger.info(f"[UnifiedFlow] Price cross-check passed ({len(response_prices)} prices verified against {source_name})")
            return True, [], ""

        except Exception as e:
            logger.error(f"[UnifiedFlow] Price cross-check error: {e}")
            return True, [], ""  # Don't fail on errors, just skip

    async def _verify_urls_in_response(
        self,
        response: str,
        turn_dir: Optional[TurnDirectory] = None
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Verify URLs mentioned in response against research results.

        Cross-references URLs in the response against source_urls from research.json.
        This avoids redundant network requests since research already verified these URLs
        via Playwright browser navigation.

        Args:
            response: The synthesized response text
            turn_dir: Turn directory containing research.json

        Returns:
            (all_valid, valid_urls, invalid_urls)
            - valid_urls: URLs that exist in research.json source_urls
            - invalid_urls: URLs NOT found in research (potentially hallucinated)
        """
        if not ENABLE_URL_VERIFICATION:
            return True, [], []

        urls = extract_urls_from_text(response)
        if not urls:
            return True, [], []

        # Load research.json to get source_urls (URLs that were actually visited)
        research_urls = []
        vendor_urls = []

        if turn_dir:
            research_json_path = turn_dir.path / "research.json"
            if research_json_path.exists():
                try:
                    with open(research_json_path, 'r') as f:
                        research_data = json.load(f)

                    # Get source_urls (primary list of visited URLs)
                    research_urls = research_data.get("source_urls", [])

                    # Also get URLs from vendors and listings for more complete matching
                    for vendor in research_data.get("vendors", []):
                        if vendor.get("url"):
                            vendor_urls.append(vendor["url"])
                    for listing in research_data.get("listings", []):
                        if listing.get("url"):
                            vendor_urls.append(listing["url"])

                    logger.info(
                        f"[UnifiedFlow] URL verification: Loaded {len(research_urls)} source URLs, "
                        f"{len(vendor_urls)} vendor/listing URLs from research.json"
                    )
                except Exception as e:
                    logger.warning(f"[UnifiedFlow] Failed to load research.json: {e}")

        # Combine all known URLs from research
        all_known_urls = list(set(research_urls + vendor_urls))

        if not all_known_urls:
            # No research data - can't verify, so pass (don't block on missing data)
            logger.info("[UnifiedFlow] URL verification: No research URLs to cross-reference, passing")
            return True, urls, []

        # Cross-reference: check each response URL against known research URLs
        valid_urls = []
        invalid_urls = []

        for url in urls:
            if url_matches_any(url, all_known_urls):
                valid_urls.append(url)
                logger.debug(f"[UnifiedFlow] URL verified (in research): {url[:60]}")
            else:
                invalid_urls.append(url)
                logger.warning(
                    f"[UnifiedFlow] URL not found in research (possibly hallucinated): {url[:60]}"
                )

        logger.info(
            f"[UnifiedFlow] URL cross-reference: {len(valid_urls)} verified, "
            f"{len(invalid_urls)} not in research"
        )

        return len(invalid_urls) == 0, valid_urls, invalid_urls

    async def _archive_attempt(self, turn_dir: "TurnDirectory", attempt: int) -> None:
        """
        Archive current turn docs to attempt_N/ subfolder.

        This clears the turn directory for a fresh retry while preserving
        the failed attempt for debugging.
        """
        attempt_dir = turn_dir.path / f"attempt_{attempt}"
        attempt_dir.mkdir(exist_ok=True)

        # Files to archive
        doc_files = ["context.md", "research.md", "ticket.md", "response.md",
                     "scan_result.md", "reflection.md", "toolresults.md"]

        archived_count = 0
        for filename in doc_files:
            src = turn_dir.path / filename
            if src.exists():
                dst = attempt_dir / filename
                shutil.move(str(src), str(dst))
                archived_count += 1
                logger.debug(f"[UnifiedFlow] Archived {filename} to {attempt_dir.name}/")

        logger.info(f"[UnifiedFlow] Archived attempt {attempt} ({archived_count} files) to {attempt_dir}")

    async def _write_retry_context(
        self,
        turn_dir: "TurnDirectory",
        failure_context: ValidationFailureContext,
        session_id: str,
        turn_number: int
    ) -> None:
        """
        Write retry_context.json for Context Gatherer to read.

        This tells Context Gatherer:
        - This is a retry (not first attempt)
        - What failed (PRICE_STALE, URL_INVALID, etc.)
        - What to filter out (specific URLs, prices)
        - To use stricter TTL filtering
        - Session/turn ID for race condition protection

        IMPORTANT: Merges failed_urls from previous attempts to accumulate all failures.
        """
        if not failure_context:
            return

        retry_path = turn_dir.path / "retry_context.json"

        # Load existing retry_context to merge failed_urls from previous attempts
        existing_failed_urls = []
        existing_failed_claims = []
        existing_mismatches = []
        if retry_path.exists():
            try:
                with open(retry_path, "r") as f:
                    existing = json.load(f)
                existing_failed_urls = existing.get("failed_urls", [])
                existing_failed_claims = existing.get("failed_claims", [])
                existing_mismatches = existing.get("mismatches", [])
                logger.info(f"[UnifiedFlow] Merging with {len(existing_failed_urls)} existing failed URLs")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[UnifiedFlow] Could not read existing retry_context: {e}")

        # Merge failed_urls (deduplicate)
        all_failed_urls = list(set(existing_failed_urls + failure_context.failed_urls))
        all_failed_claims = existing_failed_claims + failure_context.failed_claims
        all_mismatches = existing_mismatches + failure_context.mismatches

        # Build merged failure context for instructions
        merged_failure = ValidationFailureContext(
            reason=failure_context.reason,
            failed_urls=all_failed_urls,
            failed_claims=all_failed_claims,
            mismatches=all_mismatches,
            retry_count=failure_context.retry_count
        )

        retry_context = {
            "is_retry": True,
            "session_id": session_id,  # For race condition protection
            "turn_number": turn_number,  # For race condition protection
            "attempt": failure_context.retry_count,
            "reason": failure_context.reason,
            "failed_urls": all_failed_urls,
            "failed_claims": all_failed_claims,
            "mismatches": all_mismatches,
            "instructions": self._get_retry_instructions(merged_failure)
        }

        retry_path.write_text(json.dumps(retry_context, indent=2, default=str))
        logger.info(f"[UnifiedFlow] Wrote retry_context.json: reason={failure_context.reason}, total_failed_urls={len(all_failed_urls)}")

    def _get_retry_instructions(self, failure_context: ValidationFailureContext) -> List[str]:
        """Generate instructions for Context Gatherer based on failure reason."""
        instructions = []

        if failure_context.reason == "PRICE_STALE":
            instructions.append("SKIP all price data from prior turns - prices are stale")
            instructions.append("Only use fresh prices from new research")
            for mismatch in failure_context.mismatches:
                if mismatch.get("field") == "price":
                    instructions.append(f"AVOID price: {mismatch.get('expected')}")

        elif failure_context.reason in ("URL_INVALID", "URL_NOT_IN_RESEARCH"):
            instructions.append("SKIP these URLs - they were not found in research results:")
            for url in failure_context.failed_urls:
                instructions.append(f"  - {url}")
            instructions.append("Only use URLs from the research.json source_urls")
            instructions.append("Do NOT include URLs that were not visited during research")

        elif failure_context.reason == "SPEC_MISMATCH":
            instructions.append("Product specifications have changed")
            instructions.append("SKIP cached product data from prior turns")
            instructions.append("Only use fresh research data")

        elif failure_context.reason == "STOCK_UNAVAILABLE":
            instructions.append("Stock/availability data is stale")
            instructions.append("SKIP stock info from prior turns")
            instructions.append("Only use fresh availability data")

        return instructions

    async def _invalidate_claims(self, failure_context: ValidationFailureContext) -> int:
        """
        Invalidate failed claims so they won't be reused on retry.

        Returns: number of claims invalidated
        """
        if not failure_context:
            return 0

        invalidated = 0

        # Get research index to mark claims as invalid
        try:
            research_index = get_research_index_db()

            # Invalidate by URL if we have failed URLs
            for url in failure_context.failed_urls:
                # Mark any research entries with this URL as expired
                research_index.invalidate_by_url(url)
                invalidated += 1
                logger.info(f"[UnifiedFlow] Invalidated claims for URL: {url[:50]}...")

            # Invalidate specific claims if provided
            for claim in failure_context.failed_claims:
                claim_id = claim.get("id") or claim.get("source", "")
                if claim_id:
                    research_index.invalidate_by_id(claim_id)
                    invalidated += 1

            logger.info(f"[UnifiedFlow] Invalidated {invalidated} claims/entries")

        except Exception as e:
            logger.error(f"[UnifiedFlow] Claim invalidation error: {e}")

        return invalidated

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
        Handle a request using the unified 7-phase flow.

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

        # Initialize metrics for this turn
        self._turn_metrics = self._init_turn_metrics()

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
            base_dir=request_turns_dir  # Use user-specific turns directory
        )
        turn_dir.create()  # Creates the directory

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
        # Store mode, repo, user_id, and trace_id for permission validation and context gathering
        context_doc.mode = mode
        context_doc.repo = repo
        context_doc.user_id = path_resolver.user_id
        context_doc.trace_id = trace_id  # Store for tool result SSE events

        # Store request-specific paths and saver for use in phases
        context_doc._request_turns_dir = request_turns_dir
        context_doc._request_sessions_dir = request_sessions_dir
        context_doc._request_memory_dir = request_memory_dir
        context_doc._request_turn_saver = request_turn_saver

        try:
            retry_count = 0
            response = ""
            validation_result = None
            ticket_content = None
            toolresults_content = None

            # Best-seen tracking (Poetiq pattern)
            # Track the best response across validation iterations to avoid
            # returning a worse response on FAIL or max retries
            best_seen_response: Optional[str] = None
            best_seen_confidence: float = 0.0
            best_seen_attempt: int = 0

            # === PHASE 0: Query Analyzer (before context gathering) ===
            logger.info(f"[UnifiedFlow] Phase 0: Query Analyzer")
            phase0_start = time.time()
            await self._emit_phase_event(trace_id, 0, "active", "Analyzing query intent and references")

            query_analyzer = QueryAnalyzer(
                llm_client=self.llm_client,
                turns_dir=self.turns_dir
            )
            query_analysis = await query_analyzer.analyze(context_doc.query, turn_number)

            # Save query_analysis.json to turn directory for Context Gatherer to use
            query_analysis.save(turn_dir.path)

            # Store full analysis in context_doc §0 (THE SOURCE OF TRUTH)
            # All downstream phases should read user_purpose via context_doc.get_user_purpose()
            original_query = context_doc.query
            analysis_dict = query_analysis.to_dict()
            analysis_dict["original_query"] = original_query  # Add original query
            context_doc.set_section_0(analysis_dict)
            logger.info(f"[UnifiedFlow] Phase 0: action={query_analysis.action_needed}, purpose={query_analysis.user_purpose[:80]}...")

            phase0_duration = int((time.time() - phase0_start) * 1000)
            await self._emit_phase_event(
                trace_id, 0, "completed",
                f"Action: {query_analysis.action_needed}, Mode: {query_analysis.mode}",
                confidence=0.9,
                duration_ms=phase0_duration,
                details={"action_needed": query_analysis.action_needed, "user_purpose": query_analysis.user_purpose[:200]}
            )

            # Log resolution if performed
            if query_analysis.was_resolved:
                logger.info(f"[UnifiedFlow] Query resolved: '{original_query[:30]}...' → '{query_analysis.resolved_query[:50]}...'")

            # Log content reference if present
            if query_analysis.content_reference:
                logger.info(f"[UnifiedFlow] Content reference detected: {query_analysis.content_reference.title[:50]}... ({query_analysis.content_reference.content_type})")

            # Use detected mode from Phase 0 if not explicitly overridden
            if hasattr(query_analysis, 'mode') and query_analysis.mode == "code" and mode == "chat":
                mode = query_analysis.mode
                context_doc.mode = mode
                logger.info(f"[UnifiedFlow] Mode detected by Phase 0: {mode}")

            # === PANDORA LOOP: Multi-task detection and routing ===
            # If Phase 0 detected a multi-task request, route to PandoraLoop
            if query_analysis.is_multi_task and query_analysis.task_breakdown:
                logger.info(f"[UnifiedFlow] Multi-task detected: {len(query_analysis.task_breakdown)} tasks")
                logger.info(f"[UnifiedFlow] Routing to Pandora Loop")

                # Initialize the loop
                loop = PandoraLoop(
                    tasks=query_analysis.task_breakdown,
                    original_query=context_doc.query,
                    session_id=session_id,
                    mode=mode,
                    unified_flow=self,
                    base_turn=turn_number,
                    trace_id=trace_id,
                )

                # Run the loop - each task will call handle_request recursively
                # but those calls won't be multi-task, so they'll go through normal flow
                loop_result = await loop.run()

                # Format the final response
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
                    "is_pandora_loop": True,
                }

            # === PHASE 1-2: Context gathering and reflection ===
            logger.info(f"[UnifiedFlow] Starting phases 1-2 (context gathering)")

            # Phase 1: Context Gatherer
            phase1_start = time.time()
            await self._emit_phase_event(trace_id, 1, "active", "Gathering context from prior turns and memory")
            self._start_phase("phase1_context_gatherer")
            context_doc.update_execution_state(1, "Context Gatherer")
            context_doc = await self._phase1_context_gatherer(context_doc)
            self._end_phase("phase1_context_gatherer")
            phase1_duration = int((time.time() - phase1_start) * 1000)
            num_sources = len(context_doc.source_references) if hasattr(context_doc, 'source_references') else 0
            await self._emit_phase_event(
                trace_id, 1, "completed",
                f"Found {num_sources} relevant sources",
                confidence=0.85,
                duration_ms=phase1_duration,
                details={"sources_found": num_sources}
            )

            # Phase 2: Reflection
            phase2_start = time.time()
            await self._emit_phase_event(trace_id, 2, "active", "Evaluating if clarification is needed")
            self._start_phase("phase2_reflection")
            context_doc.update_execution_state(2, "Reflection")
            context_doc, decision = await self._phase2_reflection(context_doc, turn_dir)
            context_doc.record_decision(decision)  # Record PROCEED/CLARIFY
            self._end_phase("phase2_reflection")
            self._record_decision("reflection", decision)
            phase2_duration = int((time.time() - phase2_start) * 1000)
            await self._emit_phase_event(
                trace_id, 2, "completed",
                f"Decision: {decision}",
                confidence=0.9 if decision == "PROCEED" else 0.7,
                duration_ms=phase2_duration,
                details={"decision": decision}
            )

            if decision == "CLARIFY":
                clarification = self._extract_clarification(context_doc)
                return {
                    "response": clarification,
                    "needs_clarification": True,
                    "context_doc": context_doc,
                    "turn_number": turn_number,
                    "trace_id": trace_id,
                    "unified_flow": True
                }

            # === PHASE 3-4-5-6: Unified Planning-Validation loop ===
            # ARCHITECTURAL DECISION (2025-12-30):
            # Phase 3-4 now use unified planning loop (Planner controls tool execution)
            # On validation RETRY, loop back to Planner with context_doc intact
            while retry_count < MAX_VALIDATION_RETRIES:
                logger.info(f"[UnifiedFlow] Planning-Validation iteration {retry_count + 1}/{MAX_VALIDATION_RETRIES}")

                # Phase 3-4: Unified Planning Loop
                # Planner iteratively decides EXECUTE (run tools) or COMPLETE (go to synthesis)
                # On RETRY, Planner reads §6 validation failure and adjusts plan
                phase34_start = time.time()
                await self._emit_phase_event(
                    trace_id, 3, "active",
                    f"Planning strategy (iteration {retry_count + 1})",
                    details={"iteration": retry_count + 1}
                )
                self._start_phase("phase3_4_planning_loop")
                context_doc.update_execution_state(
                    phase=3,
                    phase_name="Planner-Coordinator",
                    iteration=retry_count + 1,
                    max_iterations=MAX_VALIDATION_RETRIES
                )
                context_doc, ticket_content, toolresults_content = await self._phase3_4_planning_loop(
                    context_doc, turn_dir, mode, intent, trace_id=trace_id
                )
                self._end_phase("phase3_4_planning_loop")
                phase34_duration = int((time.time() - phase34_start) * 1000)

                # Check if planning was blocked (tool failures/timeouts)
                coordinator_blocked = False
                section4 = context_doc.get_section(4) if context_doc.has_section(4) else ""
                if "BLOCKED" in section4 or "too many tool failures" in section4.lower():
                    coordinator_blocked = True
                    logger.warning(f"[UnifiedFlow] Planning was BLOCKED due to tool failures - will skip validation retry")

                # Emit planner completion event
                num_tools = len(context_doc.claims) if hasattr(context_doc, 'claims') else 0
                await self._emit_phase_event(
                    trace_id, 3, "completed",
                    f"Planning complete, {num_tools} claims gathered",
                    confidence=0.8 if not coordinator_blocked else 0.4,
                    duration_ms=phase34_duration,
                    details={"claims": num_tools, "blocked": coordinator_blocked}
                )

                # Phase 6: Synthesis (note: architecture doc maps this as phase 5)
                phase6_start = time.time()
                await self._emit_phase_event(trace_id, 6, "active", "Generating response from gathered context")
                self._start_phase("phase5_synthesis")
                context_doc.update_execution_state(5, "Synthesis")
                context_doc, response = await self._phase5_synthesis(context_doc, turn_dir, mode)
                self._end_phase("phase5_synthesis")
                phase6_duration = int((time.time() - phase6_start) * 1000)
                await self._emit_phase_event(
                    trace_id, 6, "completed",
                    f"Response generated ({len(response) if response else 0} chars)",
                    confidence=0.85,
                    duration_ms=phase6_duration,
                    details={"response_length": len(response) if response else 0}
                )

                # =====================================================================
                # SYNTHESIZER INVALID DETECTION
                # If the Synthesizer itself returned INVALID (recognizing it can't answer),
                # we should force a RETRY to do research rather than pass this to the user.
                # =====================================================================
                synthesis_returned_invalid = False
                invalid_reason = None  # Initialize before conditional block
                if response and response.strip().startswith('{'):
                    try:
                        parsed = json.loads(response.strip())
                        if parsed.get("_type") == "INVALID":
                            synthesis_returned_invalid = True
                            invalid_reason = parsed.get("reason", "Synthesizer could not generate valid response")
                            logger.warning(f"[UnifiedFlow] Synthesizer returned INVALID: {invalid_reason}")
                    except (json.JSONDecodeError, ValueError):
                        pass

                # Check if INVALID is due to research failure (retrying won't help) vs needing more context
                research_failed_keywords = [
                    "no findings", "no successful tool", "research failed",
                    "couldn't find", "could not find", "unable to find",
                    "no results", "zero results", "empty results",
                    "multiple attempts", "repeated attempts", "search failed"
                ]
                invalid_reason_lower = invalid_reason.lower() if invalid_reason else ""
                is_research_failure = any(kw in invalid_reason_lower for kw in research_failed_keywords)

                if is_research_failure:
                    logger.warning(f"[UnifiedFlow] Synthesizer INVALID due to research failure - NOT retrying (would loop forever)")
                    # Convert to user-friendly response instead of raw INVALID JSON
                    response = f"I wasn't able to find the information you requested. {invalid_reason}"
                    synthesis_returned_invalid = False  # Skip retry path
                    # Also skip validation and go straight to save
                    logger.info("[UnifiedFlow] Research failure - skipping validation, returning failure message to user")

                if synthesis_returned_invalid and retry_count < MAX_VALIDATION_RETRIES:
                    logger.info(f"[UnifiedFlow] Synthesizer INVALID - forcing RETRY to gather research (iteration {retry_count + 1})")

                    # Create validation result to trigger retry path
                    validation_result = ValidationResult(
                        decision="RETRY",
                        issues=[f"Synthesizer returned INVALID: {invalid_reason}"],
                        confidence=0.0,
                        revision_hints="Research needed - synthesizer could not answer from available context",
                        failure_context=ValidationFailureContext(
                            reason="synthesis_invalid",
                            failed_urls=[],
                            failed_claims=[],
                            mismatches=[],
                            retry_count=retry_count + 1
                        )
                    )

                    # Skip to retry handling (below validation)
                    # Archive current attempt
                    await self._archive_attempt(turn_dir, retry_count)

                    # Write retry context
                    await self._write_retry_context(
                        turn_dir, validation_result.failure_context,
                        session_id=session_id, turn_number=turn_number
                    )

                    # Invalidate claims
                    await self._invalidate_claims(validation_result.failure_context)

                    # Add §6 section explaining the INVALID
                    section6_content = f"""**Validation Decision:** RETRY

**Reason:** Synthesizer returned INVALID - research needed

**Details:** {invalid_reason}

The synthesizer recognized it could not answer from available context.
Retrying with research to gather the needed information.
"""
                    if context_doc.has_section(6):
                        context_doc.update_section(6, section6_content)
                    else:
                        context_doc.append_section(6, "Validation", section6_content)

                    retry_count += 1
                    continue  # Loop back to Phase 3 (Planner)

                # Phase 7: Validation (note: architecture doc maps this as phase 6)
                phase7_start = time.time()
                await self._emit_phase_event(trace_id, 7, "active", "Validating response quality and accuracy")
                self._start_phase("phase6_validation")
                context_doc.update_execution_state(6, "Validation")
                context_doc, response, validation_result = await self._phase6_validation(
                    context_doc, turn_dir, response, mode, retry_count
                )
                if validation_result:
                    context_doc.record_decision(validation_result.decision)
                self._end_phase("phase6_validation")
                self._record_decision("validation", validation_result.decision if validation_result else "UNKNOWN")
                phase7_duration = int((time.time() - phase7_start) * 1000)
                await self._emit_phase_event(
                    trace_id, 7, "completed",
                    f"Validation: {validation_result.decision if validation_result else 'UNKNOWN'}",
                    confidence=validation_result.confidence if validation_result else 0.0,
                    duration_ms=phase7_duration,
                    details={
                        "decision": validation_result.decision if validation_result else "UNKNOWN",
                        "issues": validation_result.issues if validation_result else []
                    }
                )

                # =====================================================================
                # BEST-SEEN TRACKING (Poetiq pattern)
                # Track the best response we've seen across iterations. If we end up
                # failing or hitting max retries, we can return the best response
                # instead of the latest (potentially worse) one.
                # =====================================================================
                if validation_result and response:
                    current_confidence = validation_result.confidence
                    if current_confidence > best_seen_confidence:
                        best_seen_response = response
                        best_seen_confidence = current_confidence
                        best_seen_attempt = retry_count + 1
                        logger.info(
                            f"[UnifiedFlow] Best-seen updated at attempt {best_seen_attempt}: "
                            f"confidence {best_seen_confidence:.2f}"
                        )

                # =====================================================================
                # CONFIDENCE THRESHOLD CHECK
                # If validator says APPROVE but confidence is low, override to RETRY
                # This catches hallucination cases where the LLM "sounds confident"
                # but the topic wasn't actually covered in the context.
                # =====================================================================
                CONFIDENCE_THRESHOLD = 0.70

                if validation_result and validation_result.decision == "APPROVE":
                    # Check for low confidence with hallucination indicators
                    confidence = validation_result.confidence
                    checks = getattr(validation_result, 'checks', {}) or {}

                    # Extract hallucination signals from checks
                    query_terms_missing = checks.get('query_terms_in_context') == False
                    term_substitution = checks.get('no_term_substitution') == False

                    should_override = False
                    override_reason = []

                    if confidence < CONFIDENCE_THRESHOLD:
                        should_override = True
                        override_reason.append(f"confidence {confidence:.2f} below threshold {CONFIDENCE_THRESHOLD}")

                    if query_terms_missing:
                        should_override = True
                        override_reason.append("query terms missing from context")

                    if term_substitution:
                        should_override = True
                        override_reason.append("term substitution detected")

                    if should_override and retry_count < MAX_VALIDATION_RETRIES:
                        logger.warning(
                            f"[UnifiedFlow] OVERRIDING APPROVE to RETRY: {', '.join(override_reason)}. "
                            f"Response may be hallucinated - forcing research."
                        )
                        # Convert to RETRY to force research
                        validation_result = ValidationResult(
                            decision="RETRY",
                            issues=validation_result.issues + [f"Override: {', '.join(override_reason)}"],
                            confidence=confidence,
                            revision_hints=f"Research needed - {', '.join(override_reason)}",
                            failure_context=ValidationFailureContext(
                                reason="confidence_override",
                                failed_urls=[],
                                failed_claims=[],
                                mismatches=[],
                                retry_count=retry_count + 1
                            )
                        )

                # Handle validation result
                if validation_result.decision == "APPROVE":
                    logger.info(f"[UnifiedFlow] Validation APPROVED on iteration {retry_count + 1}")

                    # Clean up retry_context.json if exists
                    retry_context_path = turn_dir.path / "retry_context.json"
                    if retry_context_path.exists():
                        retry_context_path.unlink()
                        logger.debug("[UnifiedFlow] Cleaned up retry_context.json")

                    break  # Success!

                elif validation_result.decision == "RETRY":
                    # CRITICAL: Skip retry if coordinator was blocked due to tool failures
                    # Retrying won't help - the tool already failed/timed out
                    if coordinator_blocked:
                        logger.warning(f"[UnifiedFlow] Skipping RETRY - coordinator was BLOCKED due to tool failures. Using current response.")
                        # Treat as success with whatever we have
                        break

                    logger.info(f"[UnifiedFlow] Validation RETRY - looping back to Planner (iteration {retry_count + 1})")

                    # Step 1: Archive current attempt docs
                    await self._archive_attempt(turn_dir, retry_count)

                    # Step 2: Write retry_context.json (for tracking)
                    await self._write_retry_context(
                        turn_dir, validation_result.failure_context,
                        session_id=session_id, turn_number=turn_number
                    )

                    # Step 3: Invalidate failed claims
                    await self._invalidate_claims(validation_result.failure_context)

                    # Step 4: context_doc KEEPS ROLLING (don't reset!)
                    # §6 already contains validation failure from _phase6_validation
                    # Planner will read §6 and replan accordingly

                    # Step 5: Loop back to Planner (Phase 3)
                    retry_count += 1
                    continue

                elif validation_result.decision == "FAIL":
                    logger.error(f"[UnifiedFlow] Validation FAILED: {validation_result.issues}")

                    # =========================================================
                    # BEST-SEEN RECOVERY (Poetiq pattern)
                    # If we have a better response from a previous attempt,
                    # use it instead of the failed/invalid current response
                    # =========================================================
                    current_confidence = validation_result.confidence if validation_result else 0.0
                    if best_seen_response and best_seen_confidence > current_confidence:
                        logger.info(
                            f"[UnifiedFlow] Using best-seen response from attempt {best_seen_attempt} "
                            f"(confidence {best_seen_confidence:.2f} > current {current_confidence:.2f})"
                        )
                        response = best_seen_response
                        # Skip the invalid response check since best-seen was validated
                    else:
                        # CRITICAL: Don't return raw invalid response to user
                        # Check if response is unusable (INVALID marker, empty, raw JSON, etc.)
                        is_invalid_response = (
                            not response or
                            response.strip() == "" or
                            '{"_type": "INVALID"}' in response or
                            response.strip().startswith('{') and '_type' in response
                        )

                        if is_invalid_response:
                            # Provide graceful fallback message instead of raw invalid response
                            logger.warning(f"[UnifiedFlow] Replacing invalid response with fallback message")
                            response = (
                                "I apologize, but I wasn't able to complete your request successfully. "
                                "The information I gathered wasn't sufficient to provide a reliable response. "
                                "Could you try rephrasing your question, or would you like me to try again?"
                            )

                    # Don't retry on explicit FAIL, proceed to save with warning
                    break

                else:
                    # Unknown decision, proceed
                    logger.warning(f"[UnifiedFlow] Unknown validation decision: {validation_result.decision}")
                    break

            # Check if we exhausted retries
            if retry_count >= MAX_VALIDATION_RETRIES:
                logger.warning(f"[UnifiedFlow] Max retries ({MAX_VALIDATION_RETRIES}) reached")

                # =========================================================
                # BEST-SEEN RECOVERY ON MAX RETRIES (Poetiq pattern)
                # If we hit max retries and have a better response from
                # an earlier attempt, use it instead of the latest
                # =========================================================
                current_confidence = validation_result.confidence if validation_result else 0.0
                if best_seen_response and best_seen_confidence > current_confidence:
                    logger.info(
                        f"[UnifiedFlow] Max retries hit - using best-seen from attempt {best_seen_attempt} "
                        f"(confidence {best_seen_confidence:.2f} > final {current_confidence:.2f})"
                    )
                    response = best_seen_response

            # =====================================================================
            # MALFORMED RESPONSE PROTECTION
            # Before saving/returning, check if response is usable. If it's raw JSON,
            # malformed output, or empty, replace with graceful fallback message.
            # =====================================================================
            is_malformed_response = False
            if response:
                stripped = response.strip()
                # Check for raw JSON that isn't a proper answer
                if stripped.startswith('{') and stripped.endswith('}'):
                    try:
                        parsed = json.loads(stripped)
                        # Malformed if: has _type but not ANSWER, or missing answer field entirely
                        if parsed.get("_type") == "INVALID":
                            is_malformed_response = True
                        elif "solver_self_history" in parsed and "answer" not in parsed:
                            is_malformed_response = True
                        elif parsed.get("_type") and parsed.get("_type") != "ANSWER":
                            is_malformed_response = True
                    except (json.JSONDecodeError, ValueError):
                        pass
            else:
                is_malformed_response = True  # Empty response

            if is_malformed_response:
                logger.warning(f"[UnifiedFlow] Replacing malformed response with fallback message")
                original_query = context_doc.get_section(0) if context_doc.has_section(0) else "your request"
                response = (
                    f"I apologize, but I wasn't able to find reliable information to answer your question. "
                    f"The research I attempted didn't return sufficient results. "
                    f"Would you like me to try a different approach, or could you rephrase your question?"
                )

            # Phase 8: Save (procedural, no LLM)
            self._start_phase("phase7_save")
            context_doc.update_execution_state(7, "Save")
            validation_passed = validation_result.decision == "APPROVE" if validation_result else False
            saved_turn_dir = await self._phase7_save(
                context_doc=context_doc,
                response=response,
                ticket_content=ticket_content,
                toolresults_content=toolresults_content,
                validation_result=validation_result
            )
            self._end_phase("phase7_save")

            # Record retry count in metrics
            self._turn_metrics["retries"] = retry_count

            # Finalize and persist metrics using request-specific turn_saver
            quality_score = validation_result.confidence if validation_result else 0.0
            validation_outcome = validation_result.decision if validation_result else "UNKNOWN"
            final_metrics = self._finalize_turn_metrics(quality_score, validation_outcome)
            request_turn_saver = getattr(context_doc, '_request_turn_saver', None) or self.turn_saver
            request_turn_saver.save_metrics(saved_turn_dir, final_metrics)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(f"[UnifiedFlow] Request complete in {elapsed_ms:.0f}ms (turn={turn_number}, retries={retry_count})")

            # Emit completion event
            await self._emit_phase_event(
                trace_id, 8, "completed",
                f"Request complete ({elapsed_ms:.0f}ms)",
                confidence=quality_score,
                duration_ms=int(elapsed_ms),
                details={
                    "turn_number": turn_number,
                    "retries": retry_count,
                    "validation_passed": validation_passed,
                    "response_length": len(response) if response else 0
                }
            )

            return {
                "response": response,
                "context_doc": context_doc,
                "turn_dir": str(saved_turn_dir),
                "turn_number": turn_number,
                "trace_id": trace_id,
                "elapsed_ms": elapsed_ms,
                "validation_passed": validation_passed,
                "retry_count": retry_count,
                "unified_flow": True
            }

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

    async def _phase1_context_gatherer(self, context_doc: ContextDocument) -> ContextDocument:
        """
        Phase 1: Context Gatherer

        Searches prior turns and builds §1 (Gathered Context).

        Uses ContextGatherer2Phase: Merged RETRIEVAL + SYNTHESIS (2 LLM calls)
        - 22% token reduction vs deprecated 4-phase
        - 50% fewer LLM calls
        """
        logger.info("[UnifiedFlow] Phase 1: Context Gatherer (2Phase)")

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
        # This fixes action_needed propagation bug where it becomes unclear
        if not new_doc.query_analysis and context_doc.query_analysis:
            new_doc.query_analysis = context_doc.query_analysis
            logger.warning(f"[UnifiedFlow] Recovered Phase 0 query_analysis (action={context_doc.get_action_needed()})")

        # Log the action_needed that will be used downstream
        logger.info(f"[UnifiedFlow] Phase 1 complete: §1 added ({len(new_doc.source_references)} sources), action={new_doc.get_action_needed()}")
        return new_doc

    async def _phase2_reflection(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        max_iterations: int = 3
    ) -> Tuple[ContextDocument, str]:
        """
        Phase 2: Reflection (recipe-based)

        Decides: PROCEED, GATHER_MORE, or CLARIFY.
        Can loop back to Context Gatherer if GATHER_MORE.
        """
        logger.info(f"[UnifiedFlow] Phase 2: Reflection")

        for iteration in range(max_iterations):
            # Write current context.md for recipe to read
            self._write_context_md(turn_dir, context_doc)

            # Load recipe and build doc pack (pipeline recipe)
            try:
                recipe = load_recipe("pipeline/phase2_reflection")
                pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
                prompt = pack.as_prompt()

                # Call LLM
                llm_response = await self.llm_client.call(
                    prompt=prompt,
                    role="guide",
                    max_tokens=recipe.token_budget.output,
                    temperature=0.3
                )

                # Parse JSON response
                result = self._parse_json_response(llm_response)
                decision = result.get("decision", "PROCEED")
                reasoning = result.get("reasoning", "")
                query_type = result.get("query_type", "ACTION")
                is_followup = result.get("is_followup", False)
                confidence = result.get("confidence", 0.8)
                strategy_hint = result.get("strategy_hint")
                clarification_question = result.get("clarification_question")

            except Exception as e:
                logger.error(f"[UnifiedFlow] Reflection recipe failed: {e}")
                raise RuntimeError(f"Reflection phase failed: {e}") from e

            # Append §2 (only on first iteration)
            # Per architecture doc: panda_system_docs/architecture/main-system-patterns/phase2-reflection.md
            if not context_doc.has_section(2):
                section_content = f"""**Decision:** {decision}
**Reasoning:** {reasoning}
**Query Type:** {query_type}
**Is Follow-up:** {str(is_followup).lower()}
**Confidence:** {confidence}
"""
                # Add strategy hint if present
                if strategy_hint:
                    section_content += f"**Strategy Hint:** {strategy_hint}\n"
                # Add clarification question if CLARIFY decision
                if decision == "CLARIFY" and clarification_question:
                    section_content += f"**Clarification Question:** {clarification_question}\n"
                context_doc.append_section(2, "Reflection Decision", section_content)

            if decision == "PROCEED":
                logger.info(f"[UnifiedFlow] Phase 2 complete: PROCEED")
                return context_doc, decision

            elif decision == "CLARIFY":
                logger.info(f"[UnifiedFlow] Phase 2 complete: CLARIFY")
                return context_doc, decision

            # Note: GATHER_MORE was removed from Reflection decisions (2025-12-30)
            # Reflection now only outputs PROCEED or CLARIFY per architecture docs.
            # See: panda_system_docs/architecture/main-system-patterns/phase2-reflection.md

        # Max iterations reached, proceed anyway
        logger.warning(f"[UnifiedFlow] Phase 2: Max iterations reached, proceeding")
        return context_doc, "PROCEED"

    async def _phase3_planner(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        mode: str,
        pre_intent: str = "unknown"
    ) -> Tuple[ContextDocument, str]:
        """
        Phase 3: Planner (recipe-based)

        Creates task plan and decides routing (coordinator or synthesis).
        """
        logger.info(f"[UnifiedFlow] Phase 3: Planner")

        # Read user_purpose from context_doc §0 (set by Phase 0)
        action_needed = context_doc.get_action_needed()
        data_requirements = context_doc.get_data_requirements()
        user_purpose = context_doc.get_user_purpose()
        logger.info(f"[UnifiedFlow] Phase 3 using action from §0: {action_needed}")

        # Add user_purpose to §2 so Planner can see it
        purpose_line = f"\n**User Purpose:** {user_purpose}"
        if action_needed == "navigate_to_site":
            content_ref = context_doc.get_content_reference()
            target = content_ref.get("site", "") if content_ref else ""
            if target:
                purpose_line += f" (target: {target})"

        # Append to existing §2 content
        section2 = context_doc.get_section(2)
        if section2:
            context_doc.update_section(2, section2 + purpose_line)

        if action_needed == "navigate_to_site":
            content_ref = context_doc.get_content_reference()
            target = content_ref.get("site", "") if content_ref else ""
            logger.info(f"[UnifiedFlow] Navigation action: {action_needed} (target: {target})")
        else:
            logger.info(f"[UnifiedFlow] Action needed: {action_needed}")

        # Write current context.md for recipe to read
        self._write_context_md(turn_dir, context_doc)

        # Load recipe and build doc pack (mode-based selection)
        try:
            recipe = load_recipe(f"pipeline/phase3_planner_{mode}")
            pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
            prompt = pack.as_prompt()

            # Call LLM
            llm_response = await self.llm_client.call(
                prompt=prompt,
                role="guide",
                max_tokens=recipe.token_budget.output,
                temperature=0.7
            )

            # Parse TICKET JSON
            ticket = self._parse_json_response(llm_response)

            # Determine routing from ticket
            route_to = self._determine_routing_from_ticket(ticket, pre_intent)

            # Extract goal, tools, and tasks
            goal = ticket.get("user_need", ticket.get("goal", context_doc.query))
            tools = ticket.get("recommended_tools", [])
            intent = ticket.get("intent", pre_intent)
            tasks = ticket.get("tasks", [])

            # NOTE: Previously had site-specific routing override here.
            # DESIGN PRINCIPLE: Trust the Planner's decision. Site-specific queries should be
            # handled by the Planner prompt recognizing navigation/site_search intent and routing
            # appropriately. Python code should not override Planner decisions.

            # Extract phase_hint for research optimization
            phase_hint = ticket.get("phase_hint")
            if phase_hint:
                logger.info(f"[UnifiedFlow] Planner phase_hint: {phase_hint}")
                # Store phase_hint in context_doc for downstream use
                context_doc.phase_hint = phase_hint

        except Exception as e:
            logger.error(f"[UnifiedFlow] Planner recipe failed: {e}")
            raise RuntimeError(f"Planner phase failed: {e}") from e

        # Build §3 content
        # Format tasks from ticket, or use fallback
        if tasks:
            subtasks_lines = []
            for i, task in enumerate(tasks, 1):
                desc = task.get("description", str(task)) if isinstance(task, dict) else str(task)
                subtasks_lines.append(f"{i}. {desc}")
            subtasks_content = "\n".join(subtasks_lines)
        else:
            subtasks_content = f"1. {'Execute required tools' if route_to == 'coordinator' else 'Generate response from context'}"

        section_content = f"""**Goal:** {goal}
**Intent:** {intent}
**Subtasks:**
{subtasks_content}

**Route To:** {route_to}
"""
        # On RETRY loops, §3 already exists - update instead of append
        if context_doc.has_section(3):
            context_doc.update_section(3, section_content)
        else:
            context_doc.append_section(3, "Task Plan", section_content)

        # Write ticket.md
        self._write_ticket_md(turn_dir, ticket)

        logger.info(f"[UnifiedFlow] Phase 3 complete: intent={intent}, route={route_to}")
        return context_doc, route_to

    async def _phase3_4_planning_loop(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        mode: str,
        pre_intent: str = "unknown",
        trace_id: str = ""
    ) -> Tuple[ContextDocument, str, str]:
        """
        Phase 3-4: Planner → Executor → Coordinator Loop

        ARCHITECTURAL UPDATE (2026-01-24):
        Now supports 3-tier architecture with STRATEGIC_PLAN:
        - Planner outputs STRATEGIC_PLAN with route_to: executor | synthesis | clarify
        - If executor: Executor issues natural language commands to Coordinator
        - If synthesis: Skip directly to synthesis (no tools needed)

        LEGACY SUPPORT:
        Also handles PLANNER_DECISION format (EXECUTE/COMPLETE) for backward compatibility.

        Returns:
            (context_doc, ticket_content, toolresults_content)
        """
        logger.info(f"[UnifiedFlow] Phase 3-4: Planner-Executor-Coordinator Loop")

        # Emit thinking event for planner phase
        await self._emit_phase_event(trace_id, 3, "active", "Planning research strategy and goals")

        # Inject available skills into context for Planner visibility
        try:
            from libs.gateway.skill_registry import get_skill_registry
            skill_registry = get_skill_registry()
            skills_xml = skill_registry.get_available_skills_xml()
            context_doc.inject_available_skills(skills_xml)
            logger.debug(f"[UnifiedFlow] Injected {len(skill_registry.skills)} skills into context")
        except Exception as e:
            logger.warning(f"[UnifiedFlow] Could not inject skills (non-fatal): {e}")

        # Read user_purpose from context_doc §0 (set by Phase 0)
        action_needed = context_doc.get_action_needed()
        data_requirements = context_doc.get_data_requirements()
        user_purpose = context_doc.get_user_purpose()

        # BELT-AND-SUSPENDERS: Verify action_needed against query_analysis.json file
        # Catches cases where action_needed was lost during Phase 1 context_doc replacement
        if action_needed == "unclear":
            try:
                qa_path = turn_dir.path / "query_analysis.json"
                if qa_path.exists():
                    qa_data = json.loads(qa_path.read_text())
                    file_action = qa_data.get("action_needed", "unclear")
                    if file_action != action_needed:
                        logger.warning(
                            f"[UnifiedFlow] ACTION MISMATCH in Phase 3-4: context_doc={action_needed}, "
                            f"query_analysis.json={file_action}. Using file value."
                        )
                        action_needed = file_action
                        data_requirements = qa_data.get("data_requirements", {})
                        user_purpose = qa_data.get("user_purpose", "")
                        # Also fix the context_doc for downstream phases
                        context_doc.query_analysis = qa_data
            except Exception as e:
                logger.debug(f"[UnifiedFlow] Could not verify action_needed from file: {e}")

        if action_needed == "navigate_to_site":
            content_ref = context_doc.get_content_reference()
            target = content_ref.get("site", "") if content_ref else ""
            logger.info(f"[UnifiedFlow] Phase 3-4 loop using action from §0: {action_needed} (target: {target})")
        else:
            logger.info(f"[UnifiedFlow] Phase 3-4 loop using action from §0: {action_needed}")

        # Load retry context (failed URLs from previous attempts)
        skip_urls: List[str] = []
        retry_context_path = turn_dir.path / "retry_context.json"
        if retry_context_path.exists():
            try:
                with open(retry_context_path, "r") as f:
                    retry_ctx = json.load(f)
                skip_urls = retry_ctx.get("failed_urls", [])
                if skip_urls:
                    logger.info(f"[UnifiedFlow] Will skip {len(skip_urls)} failed URLs from retry context")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[UnifiedFlow] Could not read retry_context.json: {e}")

        # Load recipe for Planner (mode-based selection only)
        # Domain-specific prompts removed in favor of unified prompts that handle all content types
        recipe = load_recipe(f"pipeline/phase3_planner_{mode}")

        # =====================================================================
        # NEW: 3-TIER ARCHITECTURE (STRATEGIC_PLAN support)
        # =====================================================================
        # First call Planner to get strategic decision
        # If STRATEGIC_PLAN with route_to: executor, use new 3-tier architecture
        # Otherwise, fall through to legacy PLANNER_DECISION loop

        # Write context.md for Planner
        self._write_context_md(turn_dir, context_doc)

        try:
            pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
            prompt = pack.as_prompt()

            planner_response = await self.llm_client.call(
                prompt=prompt,
                role="guide",
                max_tokens=recipe.token_budget.output,
                temperature=0.7
            )

            strategic_plan = self._parse_planner_decision(planner_response)

            # Check if this is new STRATEGIC_PLAN format
            if strategic_plan.get("_type") == "STRATEGIC_PLAN":
                route_to = strategic_plan.get("route_to", "synthesis")
                logger.info(f"[UnifiedFlow] STRATEGIC_PLAN received - route_to: {route_to}")

                # Update §3 with the strategic plan
                self._update_section3_from_strategic_plan(context_doc, strategic_plan)

                if route_to == "synthesis":
                    # No tools needed - go directly to synthesis
                    logger.info("[UnifiedFlow] STRATEGIC_PLAN routes to synthesis - no executor needed")
                    ticket_content = self._build_ticket_from_plan(strategic_plan, [])
                    toolresults_content = "# Tool Results\n\n*(No tools executed - direct synthesis)*"
                    return context_doc, ticket_content, toolresults_content

                elif route_to == "executor":
                    # Use new 3-tier architecture: Executor → Coordinator
                    logger.info("[UnifiedFlow] STRATEGIC_PLAN routes to executor - using 3-tier architecture")
                    return await self._phase4_executor_loop(
                        context_doc, strategic_plan, turn_dir, mode, trace_id=trace_id
                    )

                elif route_to == "clarify":
                    # Need clarification - this will be handled by the caller
                    logger.info("[UnifiedFlow] STRATEGIC_PLAN routes to clarify")
                    ticket_content = json.dumps(strategic_plan, indent=2)
                    toolresults_content = ""
                    return context_doc, ticket_content, toolresults_content

                elif route_to == "brainstorm":
                    # Brainstorming needed - return for handling
                    logger.info("[UnifiedFlow] STRATEGIC_PLAN routes to brainstorm")
                    ticket_content = json.dumps(strategic_plan, indent=2)
                    toolresults_content = ""
                    return context_doc, ticket_content, toolresults_content

            # If not STRATEGIC_PLAN, fall through to legacy loop below
            # (PLANNER_DECISION with EXECUTE/COMPLETE)
            logger.info("[UnifiedFlow] Legacy PLANNER_DECISION format - using existing loop")

        except Exception as e:
            logger.warning(f"[UnifiedFlow] Initial planner call failed: {e} - falling through to legacy loop")

        # =====================================================================
        # LEGACY: PLANNER_DECISION loop (backward compatibility)
        # =====================================================================

        # === PLANNING LOOP CONFIGURATION ===
        MAX_PLANNING_ITERATIONS = 5
        MAX_TOOL_CALLS = 20

        # State tracking
        iteration = 0
        total_tool_calls = 0
        all_tool_results = []
        all_claims = []
        all_rejected = []
        goals_tracker = []  # Track goal progression
        step_log = []
        research_already_called = False
        research_exhausted = False  # True when research returned 0 findings - block ALL retries
        failed_tools = set()

        # Track previous research queries to prevent exact duplicates but allow new queries
        previous_research_queries: set = set()

        # Check if §4 already has research results (from RETRY)
        if context_doc.has_section(4):
            existing_section4 = context_doc.get_section(4)
            if "internet.research" in existing_section4 and "success" in existing_section4:
                logger.info("[UnifiedFlow] RETRY: Found existing research results in §4")
                # DON'T set research_already_called = True on RETRY
                # Instead, extract the previous query to prevent exact duplicates
                # This allows the Planner to retry with a DIFFERENT query
                import re
                query_match = re.search(r'`internet\.research`.*?"query":\s*"([^"]+)"', existing_section4)
                if query_match:
                    previous_research_queries.add(query_match.group(1).lower().strip())
                    logger.info(f"[UnifiedFlow] RETRY: Previous query detected, will allow different queries")

                # CRITICAL: Load tool results from previous attempt so Synthesis has data
                # Find the most recent attempt_N directory and load its toolresults.md
                attempt_dirs = sorted(turn_dir.path.glob("attempt_*"), reverse=True)
                for attempt_dir in attempt_dirs:
                    prev_toolresults = attempt_dir / "toolresults.md"
                    if prev_toolresults.exists():
                        try:
                            content = prev_toolresults.read_text()
                            # Parse the JSON from toolresults.md
                            json_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', content)
                            if json_match:
                                prev_results = json.loads(json_match.group())
                                all_tool_results.extend(prev_results)
                                logger.info(f"[UnifiedFlow] RETRY: Loaded {len(prev_results)} tool results from {attempt_dir.name}")
                                break
                        except Exception as e:
                            logger.warning(f"[UnifiedFlow] Could not load previous tool results: {e}")
        else:
            # Initialize §4 with explicit "no tools yet" message to prevent Planner hallucinations
            context_doc.append_section(4, "Tool Execution", "*(No tools executed yet. This section will be populated when tools are called.)*")

        # === PLANNING LOOP ===
        while iteration < MAX_PLANNING_ITERATIONS:
            iteration += 1
            logger.info(f"[UnifiedFlow] Planning Loop - Iteration {iteration}/{MAX_PLANNING_ITERATIONS}")

            # Write current context.md for Planner to read
            self._write_context_md(turn_dir, context_doc)

            # Check budget before LLM call
            self._check_budget(context_doc, recipe, f"Planning Iteration {iteration}")

            # Call Planner LLM
            try:
                pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
                prompt = pack.as_prompt()

                llm_response = await self.llm_client.call(
                    prompt=prompt,
                    role="guide",
                    max_tokens=recipe.token_budget.output,
                    temperature=0.7
                )

                planner_decision = self._parse_planner_decision(llm_response)

            except Exception as e:
                logger.error(f"[UnifiedFlow] Planner failed at iteration {iteration}: {e}")
                planner_decision = {"action": "COMPLETE", "reasoning": f"Planner error: {e}"}

            action = planner_decision.get("action", "COMPLETE")
            reasoning = planner_decision.get("reasoning", "")
            goals = planner_decision.get("goals", [])
            tools = planner_decision.get("tools", [])

            # Track goals
            if goals:
                goals_tracker = goals

            # === HANDLE COMPLETE ===
            if action == "COMPLETE":
                logger.info(f"[UnifiedFlow] Planning Loop - COMPLETE at iteration {iteration}: {reasoning}")
                step_log.append(f"### Iteration {iteration}: Complete\n**Action:** COMPLETE\n**Goals:** {self._format_goals(goals)}\n**Reasoning:** {reasoning}\n**Total Claims:** {len(all_claims)}")

                # Update §3 with final plan
                self._update_section3_from_planner(context_doc, planner_decision, "synthesis")
                break

            # === HANDLE EXECUTE ===
            if action == "EXECUTE":
                if not tools:
                    logger.warning(f"[UnifiedFlow] EXECUTE with no tools - treating as COMPLETE")
                    step_log.append(f"### Iteration {iteration}: Auto-Complete\n**Action:** EXECUTE (no tools)\n**Reasoning:** {reasoning}")
                    self._update_section3_from_planner(context_doc, planner_decision, "synthesis")
                    break

                step_tools_desc = []
                step_results = []

                for tool_spec in tools:
                    tool_name = tool_spec.get("tool", "")
                    tool_args = tool_spec.get("args", {})

                    if not tool_name:
                        continue

                    # Check limits
                    if total_tool_calls >= MAX_TOOL_CALLS:
                        logger.warning(f"[UnifiedFlow] Max tool calls ({MAX_TOOL_CALLS}) reached")
                        step_tools_desc.append(f"- `{tool_name}`: SKIPPED (max tool calls)")
                        break

                    # Skip failed tools
                    if tool_name in failed_tools:
                        step_tools_desc.append(f"- `{tool_name}`: SKIPPED (previously failed)")
                        continue

                    # Prevent duplicate internet.research calls
                    if tool_name == "internet.research":
                        current_query = tool_args.get("query", "").lower().strip()
                        logger.info(f"[UnifiedFlow] Research guard check: exhausted={research_exhausted}, already_called={research_already_called}, current_query='{current_query[:50]}...'")

                        # Block ALL research if previous attempt returned 0 findings
                        if research_exhausted:
                            logger.warning(f"[UnifiedFlow] Blocking research - previous attempt returned 0 findings")
                            step_tools_desc.append(f"- `{tool_name}`: SKIPPED (research exhausted - 0 findings)")
                            continue

                        # Block same-query calls (but allow different queries on RETRY)
                        if research_already_called and current_query in previous_research_queries:
                            logger.warning(f"[UnifiedFlow] Blocking duplicate internet.research call (same query)")
                            step_tools_desc.append(f"- `{tool_name}`: SKIPPED (already called with same query)")
                            continue
                        elif research_already_called:
                            # Different query on retry - allow it but log
                            logger.info(f"[UnifiedFlow] Allowing new internet.research query on RETRY: {current_query[:50]}...")

                    # Execute tool with timeout
                    if tool_name == "internet.research":
                        tool_timeout = int(os.environ.get("RESEARCH_TIMEOUT", 600))
                    else:
                        tool_timeout = 300

                    total_tool_calls += 1
                    tool_start_time = time.time()
                    try:
                        result = await asyncio.wait_for(
                            self._execute_single_tool(tool_name, tool_args, context_doc, skip_urls=skip_urls),
                            timeout=tool_timeout
                        )
                        tool_success = result.get("status") not in ("error", "failed", "timeout", "denied")
                    except asyncio.TimeoutError:
                        logger.warning(f"[UnifiedFlow] Tool '{tool_name}' timed out after {tool_timeout}s")
                        result = {
                            "tool": tool_name,
                            "status": "timeout",
                            "error": f"Tool execution timed out after {tool_timeout} seconds",
                            "claims": [],
                            "raw_result": {}
                        }
                        failed_tools.add(tool_name)
                        tool_success = False

                    # Record tool call metrics
                    tool_duration_ms = int((time.time() - tool_start_time) * 1000)
                    self._record_tool_call(tool_name, tool_success, tool_duration_ms)

                    step_results.append(result)
                    all_tool_results.append(result)

                    # Track success/failure
                    status = result.get("status", "executed")
                    desc = result.get("description", "executed")
                    step_tools_desc.append(f"- `{tool_name}`: {desc} ({status})")

                    if result.get("status") in ("error", "failed", "timeout"):
                        failed_tools.add(tool_name)
                        # Mark research as exhausted on failure - retries won't help
                        if tool_name == "internet.research":
                            research_exhausted = True
                            logger.warning(f"[UnifiedFlow] Research failed - marking as exhausted (no retries)")
                    elif tool_name == "internet.research":
                        research_already_called = True
                        # Track the query to prevent exact duplicates but allow modified queries
                        query_used = tool_args.get("query", "").lower().strip()
                        if query_used:
                            previous_research_queries.add(query_used)

                        # Check for 0 findings - mark research as exhausted to prevent retry loops
                        raw_result = result.get("result", {})
                        findings = raw_result.get("findings", [])
                        findings_count = len(findings) if findings else 0
                        logger.info(f"[UnifiedFlow] Research completed - findings: {findings_count}")

                        if findings_count == 0:
                            research_exhausted = True
                            logger.warning(f"[UnifiedFlow] Research returned 0 findings - marking as exhausted (no retries)")

                    # Collect claims
                    for claim in result.get("claims", []):
                        all_claims.append(claim)
                        context_doc.add_claim(
                            content=claim['content'],
                            confidence=claim['confidence'],
                            source=claim['source'],
                            ttl_hours=claim.get('ttl_hours', 24)
                        )

                    # Collect rejected products
                    raw_result = result.get("raw_result", {})
                    if isinstance(raw_result, dict):
                        all_rejected.extend(raw_result.get("rejected", []))

                # Build iteration log entry with structured tracking (Priority 1: PM Assistant pattern)
                results_summary = self._summarize_tool_results(step_results)
                iteration_claims = sum(
                    len(r.get("raw_result", {}).get("claims", []))
                    for r in step_results
                    if isinstance(r.get("raw_result"), dict)
                )
                step_entry = f"""### Iteration {iteration}
**Action:** EXECUTE
**Goals:** {self._format_goals(goals)}
**Reasoning:** {reasoning}
**Tools:**
{chr(10).join(step_tools_desc)}
**Results:**
{results_summary}
**Iteration Stats:** {len(step_results)} tools, {iteration_claims} claims extracted
"""
                step_log.append(step_entry)

                # Append results to §4
                context_doc.append_to_section(4, step_entry)

                logger.info(f"[UnifiedFlow] Planning Loop - Iteration {iteration} complete: {len(step_results)} tools executed")

                # All tools skipped but we have claims - force complete
                if not step_results and all_claims:
                    logger.info(f"[UnifiedFlow] All tools skipped with {len(all_claims)} claims - forcing COMPLETE")
                    break

            else:
                # Unknown action - treat as COMPLETE
                logger.warning(f"[UnifiedFlow] Unknown action '{action}' - treating as COMPLETE")
                break

        # === END PLANNING LOOP ===

        # Update §3 with final plan (if not already done)
        if action != "COMPLETE":
            self._update_section3_from_planner(context_doc, planner_decision, "synthesis")

        # Check if we hit max iterations
        if iteration >= MAX_PLANNING_ITERATIONS:
            logger.warning(f"[UnifiedFlow] Planning Loop - Max iterations ({MAX_PLANNING_ITERATIONS}) reached")
            step_log.append(f"### Iteration {iteration}: Max Iterations\n**Decision:** Forced completion")

        # Build final §4 content with claims table (similar to _phase4_coordinator)
        claims_table = ["| Claim | Confidence | Source | TTL |", "|-------|------------|--------|-----|"]
        if all_claims:
            claim_summaries = await self._summarize_claims_batch(all_claims, max_chars_per_claim=300)
            for i, claim in enumerate(all_claims):
                ttl = claim.get('ttl_hours', 24)
                summary = claim_summaries[i] if i < len(claim_summaries) else claim['content'][:100]
                source_display = claim['source'][:60] + "..." if len(claim['source']) > 60 else claim['source']
                claims_table.append(f"| {summary} | {claim['confidence']:.2f} | {source_display} | {ttl}h |")

        # Build rejected products section
        rejected_section = ""
        if all_rejected:
            rejected_lines = ["| Product | Vendor | Rejection Reason |", "|---------|--------|------------------|"]
            for rej in all_rejected[:10]:
                name = rej.get("name", "Unknown")[:40]
                vendor = rej.get("vendor", "unknown")
                reason = rej.get("rejection_reason", "Unknown")[:50]
                rejected_lines.append(f"| {name} | {vendor} | {reason} |")
            rejected_section = f"""
**Rejected Products ({len(all_rejected)} total):**
*Products considered but excluded - DO NOT include these in the response*
{chr(10).join(rejected_lines)}
"""

        # Determine status
        status = "success" if all_claims or iteration == 1 else "partial"

        # Calculate aggregate confidence (Priority 2: PM Assistant pattern)
        claim_confidences = [c.get("confidence", 0.8) for c in all_claims]
        # Count goals from the last planner decision
        goals_achieved = sum(1 for g in goals if g.get("status") == "achieved")
        goals_total = len(goals) if goals else 1

        aggregate_confidence = calculate_aggregate_confidence(
            claim_confidences=claim_confidences,
            goals_achieved=goals_achieved,
            goals_total=goals_total,
            has_tool_results=bool(all_tool_results),
            has_memory_context=bool(context_doc.get_section(1)),
        )

        # Format confidence breakdown
        confidence_section = f"""
**Aggregate Confidence:** {aggregate_confidence.score:.2f}
| Component | Score |
|-----------|-------|
| Claims | {aggregate_confidence.breakdown.get('claim_confidence', 0):.2f} |
| Sources | {aggregate_confidence.breakdown.get('source_quality', 0):.2f} |
| Goals | {aggregate_confidence.breakdown.get('goal_coverage', 0):.2f} |
| Evidence | {aggregate_confidence.breakdown.get('evidence_depth', 0):.2f} |"""

        if aggregate_confidence.issues:
            confidence_section += "\n\n**Confidence Issues:**\n" + "\n".join(f"- {i}" for i in aggregate_confidence.issues)

        # Final §4 content with structured iteration tracking (Priority 1)
        final_section = f"""## Planning Loop ({iteration} iterations)

**Status:** {status}
**Iterations:** {iteration}/{MAX_PLANNING_ITERATIONS}
**Tool Calls:** {total_tool_calls}/{MAX_TOOL_CALLS}
{confidence_section}

{chr(10).join(step_log)}

---

**Claims Extracted:**
{chr(10).join(claims_table)}
{rejected_section}"""
        context_doc.update_section(4, final_section)

        # Build ticket.md and toolresults.md content
        ticket_content = self._build_ticket_content(context_doc, {"tools": [r.get("tool", r.get("tool_name", "unknown")) for r in all_tool_results]})
        toolresults_content = self._build_toolresults_content(context_doc, all_tool_results)

        # Write research documents for internet.research results
        await self._write_research_documents(all_tool_results, context_doc)

        # Update knowledge graph with extracted entities (compounding context)
        await self._update_knowledge_graph(all_tool_results, context_doc)

        # Write toolresults.md for Phase 5
        toolresults_path = turn_dir.doc_path("toolresults.md")
        toolresults_path.write_text(toolresults_content)
        logger.info(f"[UnifiedFlow] Wrote toolresults.md for synthesis ({len(toolresults_content)} chars)")

        # Emit completion events for planner and executor
        await self._emit_phase_event(trace_id, 3, "completed", "Planning complete")
        await self._emit_phase_event(trace_id, 4, "completed", "Execution complete")
        await self._emit_phase_event(trace_id, 5, "completed", "Coordination complete")

        logger.info(f"[UnifiedFlow] Phase 3-4 complete: {iteration} iterations, {len(all_tool_results)} tools, {len(context_doc.claims)} claims")
        return context_doc, ticket_content, toolresults_content

    def _parse_planner_decision(self, llm_response: str) -> Dict[str, Any]:
        """
        Parse STRATEGIC_PLAN or PLANNER_DECISION from LLM response.

        Expected format (new STRATEGIC_PLAN):
        {
            "_type": "STRATEGIC_PLAN",
            "route_to": "executor" | "synthesis" | "clarify",
            "goals": [{"id": "GOAL_1", "description": "...", "priority": "high"}],
            "approach": "High-level strategy description",
            "success_criteria": "How to know when done",
            "reason": "Why this routing decision"
        }

        Also handles legacy PLANNER_DECISION and TICKET formats for backwards compatibility.
        """
        try:
            decision = self._parse_json_response(llm_response)

            # Handle new STRATEGIC_PLAN format (9-phase architecture)
            if decision.get("_type") == "STRATEGIC_PLAN":
                route_to = decision.get("route_to", "synthesis")
                goals = decision.get("goals", [])
                approach = decision.get("approach", "")
                success_criteria = decision.get("success_criteria", "")
                reason = decision.get("reason", "")

                # Map route_to to action
                if route_to == "synthesis":
                    action = "COMPLETE"
                elif route_to == "executor":
                    action = "EXECUTE"
                elif route_to == "clarify":
                    action = "CLARIFY"
                elif route_to == "brainstorm":
                    action = "BRAINSTORM"
                else:
                    action = "COMPLETE"

                return {
                    "_type": "STRATEGIC_PLAN",
                    "action": action,
                    "route_to": route_to,
                    "goals": goals,
                    "approach": approach,
                    "success_criteria": success_criteria,
                    "reasoning": reason
                }

            # Handle PLANNER_DECISION format (legacy)
            if decision.get("_type") == "PLANNER_DECISION":
                return decision

            # Handle legacy TICKET format (backwards compatibility)
            if decision.get("_type") == "TICKET":
                tasks = decision.get("tasks", [])
                planning_notes = decision.get("planning_notes", "")

                # Check if any task has direct_answer=True
                direct_answer = any(
                    isinstance(t, dict) and t.get("direct_answer")
                    for t in tasks
                )

                # Check if needs clarification
                needs_clarification = any(
                    isinstance(t, dict) and t.get("needs_clarification")
                    for t in tasks
                )

                if direct_answer or needs_clarification:
                    return {
                        "_type": "PLANNER_DECISION",
                        "action": "COMPLETE",
                        "goals": [{"id": "GOAL_1", "description": "Answer from context", "status": "achieved"}],
                        "reasoning": planning_notes or "Context sufficient - no tools needed"
                    }
                else:
                    # Convert tasks to tools
                    tools = []
                    goals = []
                    for i, task in enumerate(tasks):
                        # Handle both formats:
                        # - code_strategic.md: {"task": "...", "why": "..."}
                        # - older format: {"description": "..."}
                        if isinstance(task, dict):
                            desc = task.get("description") or task.get("task") or str(task)
                        else:
                            desc = str(task)

                        # Infer tool from task description
                        # NOTE: This is a FALLBACK for legacy TICKET format.
                        # The Planner SHOULD output PLANNER_DECISION with explicit tools.
                        # If you're hitting this code path, the Planner prompt may need updating.
                        desc_lower = desc.lower()
                        if any(kw in desc_lower for kw in ["search", "find", "look for", "research", "go to", "visit", "navigate to"]):
                            tools.append({
                                "tool": "internet.research",
                                "args": {"query": desc}
                            })

                        goals.append({
                            "id": f"GOAL_{i+1}",
                            "description": desc,
                            "status": "in_progress"
                        })

                    return {
                        "_type": "PLANNER_DECISION",
                        "action": "EXECUTE" if tools else "COMPLETE",
                        "tools": tools,
                        "goals": goals,
                        "reasoning": planning_notes
                    }

            # If no recognized format, try to infer action
            if decision.get("action") in ("EXECUTE", "COMPLETE"):
                return decision

            # Default to COMPLETE if we can't parse
            logger.warning("[UnifiedFlow] Could not parse Planner response - defaulting to COMPLETE")
            return {
                "_type": "PLANNER_DECISION",
                "action": "COMPLETE",
                "reasoning": "Could not parse Planner response"
            }

        except Exception as e:
            logger.warning(f"[UnifiedFlow] Failed to parse Planner decision: {e}")
            return {
                "_type": "PLANNER_DECISION",
                "action": "COMPLETE",
                "reasoning": f"Parse error: {str(e)[:100]}"
            }

    def _update_section3_from_planner(
        self,
        context_doc: ContextDocument,
        planner_decision: Dict[str, Any],
        route_to: str
    ):
        """Update §3 (Task Plan) from Planner decision."""
        goals = planner_decision.get("goals", [])
        reasoning = planner_decision.get("reasoning", "")

        # Format goals
        goals_lines = []
        for goal in goals:
            status = goal.get("status", "pending")
            desc = goal.get("description", str(goal))
            goals_lines.append(f"- [{status}] {desc}")

        goals_content = "\n".join(goals_lines) if goals_lines else "- Execute and respond"

        section_content = f"""**Goals:**
{goals_content}

**Route To:** {route_to}
**Planning Notes:** {reasoning}
"""
        if context_doc.has_section(3):
            context_doc.update_section(3, section_content)
        else:
            context_doc.append_section(3, "Task Plan", section_content)

    def _update_section3_from_strategic_plan(
        self,
        context_doc: ContextDocument,
        strategic_plan: Dict[str, Any]
    ):
        """Update §3 (Strategic Plan) from STRATEGIC_PLAN decision."""
        goals = strategic_plan.get("goals", [])
        approach = strategic_plan.get("approach", "")
        success_criteria = strategic_plan.get("success_criteria", "")
        route_to = strategic_plan.get("route_to", "executor")
        reasoning = strategic_plan.get("reasoning", "")

        # Format goals
        goals_lines = []
        for goal in goals:
            priority = goal.get("priority", "medium")
            desc = goal.get("description", str(goal))
            goal_id = goal.get("id", "?")
            goals_lines.append(f"- **{goal_id}** [{priority}]: {desc}")

        goals_content = "\n".join(goals_lines) if goals_lines else "- (No goals specified)"

        section_content = f"""## Strategic Plan

**Goals:**
{goals_content}

**Approach:** {approach}

**Success Criteria:** {success_criteria}

**Route To:** {route_to}

**Reasoning:** {reasoning}
"""
        if context_doc.has_section(3):
            context_doc.update_section(3, section_content)
        else:
            context_doc.append_section(3, "Strategic Plan", section_content)

    def _format_goals(self, goals: List[Dict[str, Any]]) -> str:
        """Format goals for logging."""
        if not goals:
            return "(no goals)"
        parts = []
        for g in goals:
            status = g.get("status", "?")
            gid = g.get("id", "?")
            parts.append(f"{gid}:{status}")
        return ", ".join(parts)

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
        Phase 4: Executor Loop (Tactical)

        The Executor operates in an iterative loop:
        1. Receives goals from Planner (strategic_plan)
        2. Issues natural language commands to Coordinator
        3. Coordinator translates commands to tool calls
        4. Results flow back, Executor tracks goal progress
        5. Loops until COMPLETE or BLOCKED

        Actions:
        - COMMAND: Issue a natural language command to Coordinator
        - ANALYZE: Reason about accumulated results (no tool call)
        - COMPLETE: Goals achieved, proceed to synthesis
        - BLOCKED: Cannot proceed (unrecoverable)

        Returns:
            (context_doc, ticket_content, toolresults_content)
        """
        logger.info("[UnifiedFlow] Phase 4: Executor Loop")

        # Emit thinking events for executor phase
        await self._emit_phase_event(trace_id, 3, "completed", "Planning complete")
        await self._emit_phase_event(trace_id, 4, "active", "Executing research and tool calls")

        # Load executor recipe (mode-based selection only)
        # Domain-specific prompts removed in favor of unified prompts
        recipe = select_recipe("executor", mode)

        # === EXECUTOR LOOP CONFIGURATION ===
        MAX_EXECUTOR_ITERATIONS = 10
        MAX_TOOL_CALLS = 20
        MAX_RESEARCH_CALLS = 2  # Hard cap on research calls to prevent timeout loops

        # State tracking
        iteration = 0
        total_tool_calls = 0
        total_research_calls = 0  # Track research calls specifically
        all_tool_results = []
        all_claims = []
        step_log = []
        completed_research_queries = set()  # Track executed queries to prevent exact duplicates

        # Initialize §4 if not present
        if not context_doc.has_section(4):
            context_doc.append_section(4, "Execution Progress", "*(Executor starting...)*")

        # === EXECUTOR LOOP ===
        while iteration < MAX_EXECUTOR_ITERATIONS:
            iteration += 1
            logger.info(f"[UnifiedFlow] Executor Iteration {iteration}/{MAX_EXECUTOR_ITERATIONS}")

            # Write current context.md for Executor to read
            self._write_context_md(turn_dir, context_doc)

            # Call Executor LLM
            try:
                executor_decision = await self._call_executor_llm(
                    context_doc, strategic_plan, turn_dir, recipe, iteration
                )
            except Exception as e:
                logger.error(f"[UnifiedFlow] Executor failed at iteration {iteration}: {e}")
                executor_decision = {"action": "BLOCKED", "reasoning": f"Executor error: {e}"}

            action = executor_decision.get("action", "COMPLETE")
            command = executor_decision.get("command", "")
            analysis = executor_decision.get("analysis", {})
            goals_progress = executor_decision.get("goals_progress", [])
            reasoning = executor_decision.get("reasoning", "")

            # === HANDLE COMPLETE ===
            if action == "COMPLETE":
                logger.info(f"[UnifiedFlow] Executor COMPLETE at iteration {iteration}: {reasoning}")
                step_log.append(f"### Iteration {iteration}: Complete\n**Action:** COMPLETE\n**Goals:** {self._format_goals(goals_progress)}\n**Reasoning:** {reasoning}")
                break

            # === HANDLE BLOCKED ===
            if action == "BLOCKED":
                logger.warning(f"[UnifiedFlow] Executor BLOCKED at iteration {iteration}: {reasoning}")
                step_log.append(f"### Iteration {iteration}: Blocked\n**Action:** BLOCKED\n**Reason:** {reasoning}")
                break

            # === HANDLE ANALYZE ===
            if action == "ANALYZE":
                logger.info(f"[UnifiedFlow] Executor ANALYZE at iteration {iteration}")
                analysis_content = self._format_executor_analysis(analysis, goals_progress, iteration)
                step_log.append(analysis_content)
                # Update §4 with analysis
                self._append_to_section4(context_doc, analysis_content)
                continue

            # === HANDLE COMMAND ===
            if action == "COMMAND":
                if not command:
                    logger.warning(f"[UnifiedFlow] COMMAND with empty command - treating as COMPLETE")
                    break

                logger.info(f"[UnifiedFlow] Executor COMMAND: {command[:100]}...")

                # Check tool call limit
                if total_tool_calls >= MAX_TOOL_CALLS:
                    logger.warning(f"[UnifiedFlow] Max tool calls ({MAX_TOOL_CALLS}) reached")
                    step_log.append(f"### Iteration {iteration}: Limit Reached\n**Command:** {command}\n**Result:** SKIPPED (max tool calls)")
                    break

                # Check if this is a duplicate research command (same query already executed)
                # We allow different queries - only block exact repeats
                command_lower = command.lower().strip()
                if command_lower in completed_research_queries:
                    logger.warning(f"[UnifiedFlow] Blocking duplicate command - already executed")
                    step_log.append(f"### Iteration {iteration}: Duplicate Blocked\n**Command:** {command}\n**Result:** SKIPPED (this exact command was already executed - check §4 for results)")
                    continue  # Skip this command but continue loop (executor might have other commands)

                # Check if research limit has been reached
                # Detect research-like commands and block if we've exceeded limit
                research_keywords = ["search for", "find ", "look up", "research ", "query "]
                is_research_command = any(kw in command_lower for kw in research_keywords)
                if is_research_command and total_research_calls >= MAX_RESEARCH_CALLS:
                    logger.warning(f"[UnifiedFlow] Research limit reached ({total_research_calls}/{MAX_RESEARCH_CALLS}) - blocking: {command[:50]}...")
                    step_log.append(f"### Iteration {iteration}: Research Limit Reached\n**Command:** {command}\n**Result:** SKIPPED (research limit of {MAX_RESEARCH_CALLS} calls reached - use available data from §1 and prior results)")
                    # Update §4 to tell executor to use existing data
                    self._append_to_section4(context_doc, f"\n**⚠️ RESEARCH LIMIT REACHED:** {total_research_calls} research calls completed. Use the data already gathered in §1 (Forever Memory) and §4 (Execution Progress) to answer the query. Issue COMPLETE to proceed to synthesis.\n")
                    continue

                # Try workflow execution first, then fall back to Coordinator
                try:
                    # Workflow matching - predictable tool sequences
                    coordinator_result = await self._try_workflow_execution(
                        command, context_doc, turn_dir
                    )

                    if coordinator_result is None:
                        # No workflow matched - fall back to Coordinator
                        coordinator_result = await self._coordinator_execute_command(
                            command, context_doc, turn_dir, mode
                        )

                    total_tool_calls += 1

                    # Extract claims from result
                    if coordinator_result.get("claims"):
                        all_claims.extend(coordinator_result["claims"])

                    # Track tool result
                    tool_selected = coordinator_result.get("tool_selected", "unknown")
                    all_tool_results.append({
                        "iteration": iteration,
                        "command": command,
                        "tool": tool_selected,
                        "status": coordinator_result.get("status", "unknown"),
                        "result": coordinator_result.get("result", {})
                    })

                    # Check if internet.research was called - block ALL future research calls
                    # Research should only be called ONCE per request
                    # Track completed commands to prevent exact duplicates
                    completed_research_queries.add(command_lower)

                    if tool_selected == "internet.research":
                        total_research_calls += 1
                        result_data = coordinator_result.get("result", {})
                        findings = result_data.get("findings", [])
                        findings_count = len(findings) if findings else 0
                        status = coordinator_result.get("status", "")
                        logger.info(f"[UnifiedFlow] Research completed: status={status}, findings={findings_count}, total_research_calls={total_research_calls}/{MAX_RESEARCH_CALLS}")

                    # Format result for §4
                    result_content = self._format_executor_command_result(
                        command, coordinator_result, goals_progress, iteration
                    )
                    step_log.append(result_content)
                    self._append_to_section4(context_doc, result_content)

                except Exception as e:
                    logger.error(f"[UnifiedFlow] Coordinator failed for command '{command[:50]}...': {e}")
                    error_content = f"### Iteration {iteration}: Error\n**Command:** {command}\n**Error:** {str(e)[:200]}"
                    step_log.append(error_content)
                    self._append_to_section4(context_doc, error_content)

        # === BUILD FINAL OUTPUTS ===
        # Build ticket content from strategic plan
        ticket_content = self._build_ticket_from_plan(strategic_plan, step_log)

        # Build toolresults.md for Synthesis
        toolresults_content = self._build_toolresults_md(all_tool_results, all_claims)

        # Write toolresults.md
        toolresults_path = turn_dir.path / "toolresults.md"
        toolresults_path.write_text(toolresults_content)
        logger.info(f"[UnifiedFlow] Wrote toolresults.md ({len(toolresults_content)} chars)")

        # Emit completion events
        await self._emit_phase_event(trace_id, 4, "completed", "Execution complete")
        await self._emit_phase_event(trace_id, 5, "completed", "Coordination complete")

        logger.info(f"[UnifiedFlow] Phase 4 Executor complete: {iteration} iterations, {total_tool_calls} tool calls, {total_research_calls} research calls, {len(all_claims)} claims")
        return context_doc, ticket_content, toolresults_content

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
        prompt = pack.as_prompt()

        # Call LLM
        llm_response = await self.llm_client.call(
            prompt=prompt,
            role="executor",
            max_tokens=recipe.token_budget.output,
            temperature=0.5  # Balanced for tactical reasoning
        )

        return self._parse_executor_decision(llm_response)

    def _parse_executor_decision(self, llm_response: str) -> Dict[str, Any]:
        """
        Parse EXECUTOR_DECISION from LLM response.

        Expected format:
        {
            "_type": "EXECUTOR_DECISION",
            "action": "COMMAND" | "ANALYZE" | "COMPLETE" | "BLOCKED",
            "command": "Natural language instruction to Coordinator",
            "analysis": {
                "current_state": "...",
                "findings": "...",
                "next_step_rationale": "..."
            },
            "goals_progress": [
                {"goal_id": "GOAL_1", "status": "in_progress|achieved|blocked", "progress": "..."}
            ],
            "reasoning": "Brief explanation"
        }
        """
        try:
            decision = self._parse_json_response(llm_response)

            if decision.get("_type") == "EXECUTOR_DECISION":
                return decision

            # Try to infer from action field
            if decision.get("action") in ("COMMAND", "ANALYZE", "COMPLETE", "BLOCKED"):
                decision["_type"] = "EXECUTOR_DECISION"
                return decision

            # Default to COMPLETE if we can't parse
            logger.warning("[UnifiedFlow] Could not parse Executor response - defaulting to COMPLETE")
            return {
                "_type": "EXECUTOR_DECISION",
                "action": "COMPLETE",
                "reasoning": "Could not parse Executor response"
            }

        except Exception as e:
            logger.warning(f"[UnifiedFlow] Failed to parse Executor decision: {e}")
            return {
                "_type": "EXECUTOR_DECISION",
                "action": "COMPLETE",
                "reasoning": f"Parse error: {str(e)[:100]}"
            }

    def _register_workflow_tools(self):
        """Register tool handlers with the workflow executor."""
        async def execute_research(goal: str, intent: str = "informational", context: str = "", task: str = "", max_visits: int = 8, **kwargs):
            """Phase 1 intelligence research via workflow."""
            from apps.tools.internet_research import execute_full_research
            result = await execute_full_research(
                goal=goal,
                intent=intent,
                context=context,
                max_visits=max_visits,
                **kwargs
            )
            return result

        async def execute_full_research(goal: str, intent: str = "commerce", context: str = "", target_vendors: int = 3, max_products: int = 10, **kwargs):
            """Full commerce research via workflow."""
            from apps.tools.internet_research import execute_full_research as do_research
            result = await do_research(
                goal=goal,
                intent=intent,
                context=context,
                target_vendors=target_vendors,
                max_products=max_products,
                **kwargs
            )
            return result

        self.workflow_executor.register_tool("internal://internet_research.execute_research", execute_research)
        self.workflow_executor.register_tool("internal://internet_research.execute_full_research", execute_full_research)
        logger.debug("[UnifiedFlow] Registered workflow tools")

    async def _try_workflow_execution(
        self,
        command: str,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
    ) -> Optional[Dict[str, Any]]:
        """
        Try to match and execute a workflow for the command.

        Returns:
            Result dict if workflow executed, None if no match
        """
        # Try to match command to a workflow
        match = self.workflow_matcher.match(command, context_doc)

        if not match or match.confidence < 0.7:
            logger.debug(f"[UnifiedFlow] No workflow match for: {command[:50]}...")
            return None

        logger.info(f"[UnifiedFlow] Workflow matched: {match.workflow.name} (confidence={match.confidence})")

        # Execute the workflow
        result = await self.workflow_executor.execute(
            workflow=match.workflow,
            inputs={
                "goal": context_doc.query,
                **match.extracted_params
            },
            context_doc=context_doc,
            turn_dir=turn_dir,
        )

        # Convert WorkflowResult to Coordinator-compatible format
        if result.success:
            # Extract claims from workflow outputs
            claims = self._extract_claims_from_workflow_result(result)

            return {
                "_type": "COORDINATOR_RESULT",
                "command_received": command,
                "tool_selected": f"workflow:{match.workflow.name}",
                "tool_args": match.extracted_params,
                "status": "success",
                "result": result.outputs,
                "claims": claims,
                "workflow_execution": {
                    "workflow": match.workflow.name,
                    "steps_executed": result.steps_executed,
                    "elapsed_seconds": result.elapsed_seconds,
                }
            }
        else:
            return {
                "_type": "COORDINATOR_RESULT",
                "command_received": command,
                "tool_selected": f"workflow:{match.workflow.name}",
                "status": "error",
                "result": {
                    "error": result.error,
                    "partial_outputs": result.outputs,
                    "fallback_message": result.outputs.get("fallback_message", ""),
                },
                "claims": [],
                "workflow_execution": {
                    "workflow": match.workflow.name,
                    "fallback_used": result.fallback_used,
                }
            }

    def _extract_claims_from_workflow_result(self, result: WorkflowResult) -> List[Dict[str, Any]]:
        """Extract claims from workflow outputs."""
        claims = []
        outputs = result.outputs

        # Extract from findings array (common in research workflows)
        findings = outputs.get("findings", [])
        for finding in findings:
            if isinstance(finding, dict):
                claims.append({
                    "claim_text": finding.get("name", finding.get("statement", "")),
                    "source": finding.get("url", finding.get("source", f"workflow:{result.workflow_name}")),
                    "confidence": finding.get("confidence", 0.7),
                    "tool": f"workflow:{result.workflow_name}",
                    "fields": finding
                })

        # Extract from products array (commerce workflows)
        products = outputs.get("products", [])
        for product in products:
            if isinstance(product, dict):
                claims.append({
                    "claim_text": product.get("name", ""),
                    "source": product.get("url", product.get("vendor", f"workflow:{result.workflow_name}")),
                    "confidence": product.get("confidence", 0.8),
                    "tool": f"workflow:{result.workflow_name}",
                    "fields": {
                        "price": product.get("price"),
                        "vendor": product.get("vendor"),
                        "in_stock": product.get("in_stock"),
                        **product
                    }
                })

        return claims

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
        prompt = pack.as_prompt()

        llm_response = await self.llm_client.call(
            prompt=prompt,
            role="coordinator",
            max_tokens=recipe.token_budget.output,
            temperature=0.3  # Low temp for precise tool selection
        )

        # Parse tool selection
        tool_selection = self._parse_tool_selection(llm_response)

        if tool_selection.get("_type") == "NEEDS_CLARIFICATION":
            return {
                "_type": "COORDINATOR_RESULT",
                "command_received": command,
                "status": "needs_clarification",
                "result": {"options": tool_selection.get("options", [])},
                "claims": []
            }

        if tool_selection.get("_type") == "MODE_VIOLATION":
            return {
                "_type": "COORDINATOR_RESULT",
                "command_received": command,
                "status": "mode_violation",
                "result": {"error": tool_selection.get("error", "")},
                "claims": []
            }

        # Execute the selected tool
        # Handle multiple formats from different prompts:
        # 1. Old format: {"tool": "...", "args": {...}}
        # 2. Array format: {"tools": [{"tool": "...", "args": {...}}]}
        # 3. Coordinator prompt format: {"tool_selected": "...", "tool_args": {...}}
        tool_name = tool_selection.get("tool", "")
        tool_args = tool_selection.get("args", {})

        # If no direct tool, check for Coordinator prompt format (tool_selected/tool_args)
        if not tool_name and tool_selection.get("tool_selected"):
            tool_name = tool_selection.get("tool_selected", "")
            tool_args = tool_selection.get("tool_args", {})

        # If still no tool, check for tools array format
        if not tool_name and tool_selection.get("tools"):
            tools_array = tool_selection.get("tools", [])
            if tools_array and isinstance(tools_array, list) and len(tools_array) > 0:
                first_tool = tools_array[0]
                tool_name = first_tool.get("tool", "")
                tool_args = first_tool.get("args", {})

        if not tool_name:
            return {
                "_type": "COORDINATOR_RESULT",
                "command_received": command,
                "status": "error",
                "result": {"error": "No tool selected"},
                "claims": []
            }

        # Execute tool
        tool_result = await self._execute_tool(tool_name, tool_args, context_doc, turn_dir)

        return {
            "_type": "COORDINATOR_RESULT",
            "command_received": command,
            "tool_selected": tool_name,
            "tool_args": tool_args,
            "status": tool_result.get("status", "success"),
            "result": tool_result.get("result", {}),
            "claims": tool_result.get("claims", [])
        }

    def _parse_tool_selection(self, llm_response: str) -> Dict[str, Any]:
        """
        Parse TOOL_SELECTION from Coordinator LLM response.

        Expected format:
        {
            "_type": "TOOL_SELECTION",
            "command_received": "...",
            "tool": "tool.name",
            "args": {...},
            "reasoning": "..."
        }

        Or for ambiguous commands:
        {
            "_type": "NEEDS_CLARIFICATION",
            "command_received": "...",
            "options": [...]
        }

        Or for mode violations:
        {
            "_type": "MODE_VIOLATION",
            "command_received": "...",
            "error": "..."
        }
        """
        try:
            selection = self._parse_json_response(llm_response)

            if selection.get("_type") in ("TOOL_SELECTION", "NEEDS_CLARIFICATION", "MODE_VIOLATION"):
                return selection

            # Handle COORDINATOR_RESULT format (from phase4_coordinator prompt)
            # Format: {"_type": "COORDINATOR_RESULT", "tool_selected": "...", "tool_args": {...}}
            if selection.get("_type") == "COORDINATOR_RESULT":
                if selection.get("tool_selected"):
                    return {
                        "_type": "TOOL_SELECTION",
                        "tool": selection["tool_selected"],
                        "args": selection.get("tool_args", {}),
                        "reasoning": selection.get("rationale", "")
                    }
                # Handle blocked/error case from mode violations in COORDINATOR_RESULT
                if selection.get("status") == "blocked":
                    return {
                        "_type": "MODE_VIOLATION",
                        "error": selection.get("error", "Tool not available in this mode")
                    }

            # Try to extract tool info from other formats
            if selection.get("tool"):
                return {
                    "_type": "TOOL_SELECTION",
                    "tool": selection["tool"],
                    "args": selection.get("args", {}),
                    "reasoning": selection.get("reasoning", "")
                }

            # Try tool_selected format without _type (flexible parsing)
            if selection.get("tool_selected"):
                return {
                    "_type": "TOOL_SELECTION",
                    "tool": selection["tool_selected"],
                    "args": selection.get("tool_args", {}),
                    "reasoning": selection.get("rationale", "")
                }

            # Handle tools array format from core.md prompt
            # Format: {"tools": [{"tool": "...", "args": {...}}], "rationale": "..."}
            if selection.get("tools") and isinstance(selection["tools"], list):
                tools_array = selection["tools"]
                if tools_array and len(tools_array) > 0:
                    first_tool = tools_array[0]
                    if first_tool.get("tool"):
                        return {
                            "_type": "TOOL_SELECTION",
                            "tool": first_tool["tool"],
                            "args": first_tool.get("args", {}),
                            "reasoning": selection.get("rationale", "")
                        }

            # Handle COORDINATOR_PLAN format from phase4_coordinator_code.md prompt
            # Format: {"_type": "COORDINATOR_PLAN", "subtasks": [{"tool": "...", "file_path": "...", "why": "..."}]}
            if selection.get("_type") == "COORDINATOR_PLAN" and selection.get("subtasks"):
                subtasks = selection["subtasks"]
                if subtasks and isinstance(subtasks, list) and len(subtasks) > 0:
                    first_task = subtasks[0]
                    if first_task.get("tool"):
                        # Extract args from subtask, excluding metadata fields
                        args = {k: v for k, v in first_task.items() if k not in ("tool", "why", "_type")}
                        return {
                            "_type": "TOOL_SELECTION",
                            "tool": first_task["tool"],
                            "args": args,
                            "reasoning": first_task.get("why", "")
                        }

            logger.warning("[UnifiedFlow] Could not parse Coordinator response: %s", selection)
            return {"_type": "ERROR", "error": "Could not parse tool selection"}

        except Exception as e:
            logger.warning(f"[UnifiedFlow] Failed to parse tool selection: {e}")
            return {"_type": "ERROR", "error": f"Parse error: {str(e)[:100]}"}

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context_doc: ContextDocument,
        turn_dir: TurnDirectory
    ) -> Dict[str, Any]:
        """
        Execute a tool and return the result.

        This is a unified tool execution method that handles all tool types.
        """
        logger.info(f"[UnifiedFlow] Executing tool: {tool_name} with args: {list(tool_args.keys())}")

        try:
            # Handle different tool types
            if tool_name == "internet.research":
                return await self._execute_internet_research(tool_args, context_doc, turn_dir)
            elif tool_name == "memory.search":
                return await self._execute_memory_search(tool_args)
            elif tool_name == "memory.save":
                return await self._execute_memory_save(tool_args)
            elif tool_name == "memory.delete":
                return await self._execute_memory_delete(tool_args)
            elif tool_name == "file.read":
                return await self._execute_file_read(tool_args)
            elif tool_name == "file.read_outline":
                return await self._execute_file_read_outline(tool_args)
            elif tool_name == "file.glob":
                return await self._execute_file_glob(tool_args)
            elif tool_name == "file.grep":
                return await self._execute_file_grep(tool_args)
            elif tool_name == "file.edit":
                return await self._execute_file_edit(tool_args)
            elif tool_name == "file.write":
                return await self._execute_file_write(tool_args)
            elif tool_name.startswith("git."):
                return await self._execute_git_tool(tool_name, tool_args)
            elif tool_name == "skill.generator":
                return await self._execute_skill_generator(tool_args, context_doc, turn_dir)
            else:
                logger.warning(f"[UnifiedFlow] Unknown tool: {tool_name}")
                return {"status": "error", "result": {"error": f"Unknown tool: {tool_name}"}, "claims": []}

        except Exception as e:
            logger.error(f"[UnifiedFlow] Tool execution failed: {tool_name}: {e}")
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    def _format_executor_analysis(
        self,
        analysis: Dict[str, Any],
        goals_progress: List[Dict[str, Any]],
        iteration: int
    ) -> str:
        """Format executor analysis for §4."""
        current_state = analysis.get("current_state", "")
        findings = analysis.get("findings", "")
        rationale = analysis.get("next_step_rationale", "")

        goals_str = self._format_goals(goals_progress)

        return f"""### Executor Iteration {iteration}
**Action:** ANALYZE
**Goals Progress:** {goals_str}
**Current State:** {current_state}
**Findings:** {findings}
**Next Step:** {rationale}
"""

    def _format_executor_command_result(
        self,
        command: str,
        coordinator_result: Dict[str, Any],
        goals_progress: List[Dict[str, Any]],
        iteration: int
    ) -> str:
        """Format executor command result for §4."""
        tool = coordinator_result.get("tool_selected", "unknown")
        status = coordinator_result.get("status", "unknown")
        result = coordinator_result.get("result", {})
        claims = coordinator_result.get("claims", [])

        goals_str = self._format_goals(goals_progress)

        # Format research results clearly for executor to see
        if tool == "internet.research":
            findings = result.get("findings", [])
            findings_count = len(findings)

            if findings_count > 0 and status == "success":
                # Show clear success with extracted content
                # Use longer summary (500 chars) so executor can see actual data
                findings_summary = []
                for i, f in enumerate(findings[:5]):  # Show up to 5
                    title = f.get("title", f.get("name", ""))
                    summary = f.get("summary", f.get("statement", ""))[:500]  # 500 chars for useful context
                    if title or summary:
                        findings_summary.append(f"  {i+1}. {title}: {summary}...")

                findings_text = "\n".join(findings_summary) if findings_summary else "  (content extracted)"

                return f"""### Executor Iteration {iteration}
**Action:** COMMAND
**Command:** {command}
**Coordinator:** `{tool}` → {status}
**Goals Progress:** {goals_str}

**✅ RESEARCH SUCCEEDED:** Found {findings_count} result(s), extracted {len(claims)} claim(s)
**Findings:**
{findings_text}

**Status:** Research complete - sufficient data gathered. Consider COMPLETE if goal achieved.
"""
            else:
                return f"""### Executor Iteration {iteration}
**Action:** COMMAND
**Command:** {command}
**Coordinator:** `{tool}` → {status}
**Goals Progress:** {goals_str}

**⚠️ RESEARCH RETURNED NO RESULTS**
**Status:** {status}, findings: {findings_count}
"""

        # Default format for other tools
        result_str = json.dumps(result, indent=2)
        if len(result_str) > 500:
            result_str = result_str[:500] + "... (truncated)"

        return f"""### Executor Iteration {iteration}
**Action:** COMMAND
**Command:** {command}
**Coordinator:** `{tool}` → {status}
**Goals Progress:** {goals_str}
**Result Preview:** {result_str[:300]}
"""

    def _append_to_section4(self, context_doc: ContextDocument, content: str):
        """Append content to §4 (Execution Progress)."""
        if context_doc.has_section(4):
            existing = context_doc.get_section(4)
            # Remove placeholder text if present
            if existing.startswith("*("):
                context_doc.update_section(4, content)
            else:
                context_doc.update_section(4, existing + "\n\n" + content)
        else:
            context_doc.append_section(4, "Execution Progress", content)

    def _build_ticket_from_plan(
        self,
        strategic_plan: Dict[str, Any],
        step_log: List[str]
    ) -> str:
        """Build ticket content from strategic plan and execution log."""
        goals = strategic_plan.get("goals", [])
        approach = strategic_plan.get("approach", "")
        success_criteria = strategic_plan.get("success_criteria", "")

        goals_md = "\n".join([f"- {g.get('description', str(g))}" for g in goals])
        steps_md = "\n\n".join(step_log)

        return f"""# Strategic Plan

## Goals
{goals_md}

## Approach
{approach}

## Success Criteria
{success_criteria}

## Execution Log
{steps_md}
"""

    def _build_toolresults_md(
        self,
        tool_results: List[Dict[str, Any]],
        claims: List[Dict[str, Any]]
    ) -> str:
        """Build toolresults.md content for Synthesis."""
        if not tool_results:
            return "# Tool Results\n\n*(No tools executed)*"

        content = "# Tool Results\n\n"

        for tr in tool_results:
            iteration = tr.get("iteration", "?")
            command = tr.get("command", "")
            tool = tr.get("tool", "unknown")
            status = tr.get("status", "unknown")
            result = tr.get("result", {})

            content += f"## Iteration {iteration}: {tool}\n"
            content += f"**Command:** {command}\n"
            content += f"**Status:** {status}\n"
            content += f"**Result:**\n```json\n{json.dumps(result, indent=2)[:2000]}\n```\n\n"

        if claims:
            content += "## Extracted Claims\n\n"
            for claim in claims[:20]:  # Limit to 20 claims
                content += f"- {claim.get('claim', str(claim))}\n"

        return content

    # =========================================================================
    # TOOL EXECUTION HELPERS (for _execute_tool)
    # =========================================================================

    async def _execute_internet_research(
        self,
        tool_args: Dict[str, Any],
        context_doc: ContextDocument,
        turn_dir: TurnDirectory
    ) -> Dict[str, Any]:
        """Execute internet.research tool."""
        query = tool_args.get("query", "")

        if not query:
            return {"status": "error", "result": {"error": "Missing query"}, "claims": []}

        # Read user_purpose from context_doc §0 (set by Phase 0's QueryAnalysis)
        # This is the canonical source - NOT tool_args
        action_needed = context_doc.get_action_needed()
        data_requirements = context_doc.get_data_requirements()
        user_purpose = context_doc.get_user_purpose()
        prior_context = context_doc.get_prior_context()
        logger.info(f"[UnifiedFlow] internet.research using action from §0: {action_needed}")

        # BELT-AND-SUSPENDERS: Verify action_needed against query_analysis.json
        # Catches cases where action_needed was lost during Phase 1 context_doc replacement
        if action_needed == "unclear":
            try:
                qa_path = turn_dir.path / "query_analysis.json"
                if qa_path.exists():
                    qa_data = json.loads(qa_path.read_text())
                    file_action = qa_data.get("action_needed", "unclear")
                    if file_action != action_needed:
                        logger.warning(
                            f"[UnifiedFlow] ACTION MISMATCH DETECTED: context_doc={action_needed}, "
                            f"query_analysis.json={file_action}. Using file value."
                        )
                        action_needed = file_action
                        data_requirements = qa_data.get("data_requirements", {})
                        user_purpose = qa_data.get("user_purpose", "")
                        prior_context = qa_data.get("prior_context", {})
            except Exception as e:
                logger.debug(f"[UnifiedFlow] Could not verify action_needed from file: {e}")

        # Map action_needed + data_requirements to legacy intent for orchestrator compatibility
        # Phase 0 now handles follow-up detection via prior_context.relationship
        # Commerce queries: needs_current_prices=true indicates shopping
        # Verification follow-ups: relationship="verification" with prior commerce context
        if data_requirements.get("needs_current_prices"):
            intent = "commerce"
        elif action_needed == "navigate_to_site":
            intent = "navigation"
        elif action_needed == "recall_memory":
            intent = "recall"
        elif action_needed == "live_search":
            intent = "informational"
        else:
            intent = "informational"

        # Build intent_metadata from new schema for backward compatibility
        content_ref = context_doc.get_content_reference()
        intent_metadata = {}
        if content_ref:
            intent_metadata["target_url"] = content_ref.get("source_url", "")
            intent_metadata["site_name"] = content_ref.get("site", "")

        logger.info(f"[UnifiedFlow] Mapped to legacy intent: {intent} (needs_prices={data_requirements.get('needs_current_prices')})")

        if action_needed == "navigate_to_site":
            target = intent_metadata.get("target_url") or intent_metadata.get("site_name", "")
            logger.info(f"[UnifiedFlow] internet.research target: {target}")

        # Use existing research infrastructure
        # Call the Orchestrator's /internet.research endpoint
        # IMPORTANT: intent and intent_metadata must be inside research_context (legacy)
        # Also include user_purpose and data_requirements (new system)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "http://127.0.0.1:8090/internet.research",
                    json={
                        "query": query,
                        "intent": intent,  # Top level for Pydantic model (legacy)
                        "session_id": context_doc.session_id or "default",
                        "human_assist_allowed": True,
                        # Put both legacy and new fields in research_context
                        "research_context": {
                            # Legacy fields (for backward compatibility)
                            "intent": intent,
                            "intent_metadata": intent_metadata,
                            # New fields (LLM-driven)
                            "user_purpose": user_purpose,
                            "action_needed": action_needed,
                            "data_requirements": data_requirements,
                            "prior_context": prior_context,
                        },
                        # Pass turn directory path for Document IO compliance
                        "turn_dir_path": str(turn_dir.path) if turn_dir else None,
                    },
                    timeout=aiohttp.ClientTimeout(total=300)  # 5 min timeout for research
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        # Extract claims from findings (orchestrator returns findings, not claims)
                        findings = result.get("findings", [])
                        claims = []
                        for finding in findings[:10]:  # Limit to 10
                            # Build claim content from available fields
                            content = finding.get("summary") or finding.get("title") or finding.get("statement") or ""
                            if not content and finding.get("name"):
                                # Product finding
                                name = finding.get("name", "")
                                price = finding.get("price", "")
                                vendor = finding.get("vendor", "")
                                parts = [name]
                                if price:
                                    parts.append(f"- ${price}" if isinstance(price, (int, float)) else f"- {price}")
                                if vendor:
                                    parts.append(f"at {vendor}")
                                content = " ".join(parts)
                            if content:
                                claims.append({
                                    "content": content[:1000],
                                    "confidence": 0.8,
                                    "source": finding.get("url", "internet.research"),
                                    "ttl_hours": 6
                                })
                        logger.info(f"[UnifiedFlow] Research returned {len(findings)} findings, extracted {len(claims)} claims")
                        return {
                            "status": "success",
                            "result": result,
                            "claims": claims
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "status": "error",
                            "result": {"error": f"Research failed: {error_text[:200]}"},
                            "claims": []
                        }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def _execute_memory_search(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute memory.search tool."""
        query = tool_args.get("query", "")
        if not query:
            return {"status": "error", "result": {"error": "Missing query"}, "claims": []}

        try:
            memory_mcp = get_memory_mcp()
            request = MemorySearchRequest(query=query, limit=10)
            results = await memory_mcp.search(request)
            return {
                "status": "success",
                "result": {"memories": [r.model_dump() for r in results]},
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def _execute_memory_save(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute memory.save tool."""
        content = tool_args.get("content", "")
        memory_type = tool_args.get("type", "fact")

        if not content:
            return {"status": "error", "result": {"error": "Missing content"}, "claims": []}

        try:
            memory_mcp = get_memory_mcp()
            request = MemorySaveRequest(content=content, type=memory_type)
            result = await memory_mcp.save(request)
            return {
                "status": "success",
                "result": {"saved": True, "id": result.id if result else None},
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def _execute_memory_delete(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute memory.delete tool."""
        query = tool_args.get("query", "")
        if not query:
            return {"status": "error", "result": {"error": "Missing query"}, "claims": []}

        try:
            memory_mcp = get_memory_mcp()
            # Memory delete would search and delete matching entries
            # Implementation depends on memory system capabilities
            return {
                "status": "success",
                "result": {"deleted": True},
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def _execute_file_read(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file.read tool."""
        file_path = tool_args.get("file_path", "")
        offset = tool_args.get("offset", 0)
        limit = tool_args.get("limit", 200)

        if not file_path:
            return {"status": "error", "result": {"error": "Missing file_path"}, "claims": []}

        try:
            path = Path(file_path)
            if not path.exists():
                return {"status": "error", "result": {"error": f"File not found: {file_path}"}, "claims": []}

            content = path.read_text()
            lines = content.split('\n')

            # Apply offset and limit
            selected_lines = lines[offset:offset + limit]
            result_content = '\n'.join(selected_lines)

            return {
                "status": "success",
                "result": {
                    "content": result_content,
                    "total_lines": len(lines),
                    "offset": offset,
                    "limit": limit
                },
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def _execute_file_read_outline(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file.read_outline tool - extracts symbols (functions, classes) from code files."""
        from apps.services.orchestrator.file_operations_mcp import file_read_outline

        file_path = tool_args.get("file_path", "")
        symbol_filter = tool_args.get("symbol_filter")
        include_docstrings = tool_args.get("include_docstrings", True)

        if not file_path:
            return {"status": "error", "result": {"error": "Missing file_path"}, "claims": []}

        try:
            result = await file_read_outline(
                file_path=file_path,
                symbol_filter=symbol_filter,
                include_docstrings=include_docstrings
            )

            if result.get("error"):
                return {"status": "error", "result": result, "claims": []}

            return {
                "status": "success",
                "result": result,
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def _execute_file_glob(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file.glob tool."""
        pattern = tool_args.get("pattern", "")
        if not pattern:
            return {"status": "error", "result": {"error": "Missing pattern"}, "claims": []}

        try:
            import glob
            import os
            # Ensure we're in project root for relative patterns
            project_root = Path(__file__).parent.parent.parent
            original_cwd = os.getcwd()
            try:
                os.chdir(project_root)
                matches = glob.glob(pattern, recursive=True)
            finally:
                os.chdir(original_cwd)
            return {
                "status": "success",
                "result": {"files": matches[:100]},  # Limit results
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def _execute_file_grep(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file.grep tool."""
        pattern = tool_args.get("pattern", "")
        glob_pattern = tool_args.get("glob", "**/*")

        if not pattern:
            return {"status": "error", "result": {"error": "Missing pattern"}, "claims": []}

        try:
            import subprocess
            import os
            # Run from project root for consistent paths
            project_root = str(Path(__file__).parent.parent.parent)
            result = subprocess.run(
                ["grep", "-r", "-n", "-l", pattern, "."],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=project_root
            )
            files = result.stdout.strip().split('\n') if result.stdout else []
            return {
                "status": "success",
                "result": {"files": [f for f in files if f][:100]},
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def _execute_file_edit(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file.edit tool."""
        file_path = tool_args.get("file_path", "")
        old_string = tool_args.get("old_string", "")
        new_string = tool_args.get("new_string", "")

        if not file_path or old_string is None:
            return {"status": "error", "result": {"error": "Missing file_path or old_string"}, "claims": []}

        try:
            path = Path(file_path)
            if not path.exists():
                return {"status": "error", "result": {"error": f"File not found: {file_path}"}, "claims": []}

            content = path.read_text()
            if old_string not in content:
                return {"status": "error", "result": {"error": "old_string not found in file"}, "claims": []}

            new_content = content.replace(old_string, new_string, 1)
            path.write_text(new_content)

            return {
                "status": "success",
                "result": {"edited": True, "file": file_path},
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def _execute_file_write(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file.write tool."""
        file_path = tool_args.get("file_path", "")
        content = tool_args.get("content", "")

        if not file_path:
            return {"status": "error", "result": {"error": "Missing file_path"}, "claims": []}

        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

            return {
                "status": "success",
                "result": {"written": True, "file": file_path, "bytes": len(content)},
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def _execute_git_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute git.* tools."""
        try:
            import subprocess

            if tool_name == "git.status":
                result = subprocess.run(["git", "status"], capture_output=True, text=True, timeout=30)
                return {"status": "success", "result": {"output": result.stdout}, "claims": []}

            elif tool_name == "git.diff":
                result = subprocess.run(["git", "diff"], capture_output=True, text=True, timeout=30)
                return {"status": "success", "result": {"output": result.stdout}, "claims": []}

            elif tool_name == "git.commit_safe":
                message = tool_args.get("message", "")
                add_paths = tool_args.get("add_paths", [])

                if add_paths:
                    subprocess.run(["git", "add"] + add_paths, timeout=30)

                result = subprocess.run(
                    ["git", "commit", "-m", message],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                return {"status": "success", "result": {"output": result.stdout}, "claims": []}

            else:
                return {"status": "error", "result": {"error": f"Unknown git tool: {tool_name}"}, "claims": []}

        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def _execute_skill_generator(
        self,
        tool_args: Dict[str, Any],
        context_doc: ContextDocument,
        turn_dir: TurnDirectory
    ) -> Dict[str, Any]:
        """Execute skill.generator tool."""
        name = tool_args.get("name", "")
        description = tool_args.get("description", "")

        if not name:
            return {"status": "error", "result": {"error": "Missing skill name"}, "claims": []}

        try:
            # Use existing skill generator infrastructure
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "http://127.0.0.1:8090/skill/generate",
                    json={"name": name, "description": description},
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {"status": "success", "result": result, "claims": []}
                    else:
                        error_text = await response.text()
                        return {"status": "error", "result": {"error": error_text[:200]}, "claims": []}
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def _phase4_coordinator(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        mode: str,
        trace_id: str = ""
    ) -> Tuple[ContextDocument, str, str]:
        """
        Phase 4: Coordinator (Agent Loop)

        Operates like Claude Code - iteratively:
        1. Read context.md (includes §4 with previous step results)
        2. LLM decides: TOOL_CALL, DONE, or BLOCKED
        3. If TOOL_CALL: execute tools, append to §4, loop
        4. If DONE/BLOCKED: exit loop
        """
        logger.info(f"[UnifiedFlow] Phase 4: Coordinator (Agent Loop)")

        # Emit thinking events for coordinator phase
        await self._emit_phase_event(trace_id, 5, "active", "Coordinating tool execution and research")

        # Load retry context to get failed_urls (if this is a retry attempt)
        skip_urls: List[str] = []
        retry_context_path = turn_dir.path / "retry_context.json"
        if retry_context_path.exists():
            try:
                with open(retry_context_path, "r") as f:
                    retry_ctx = json.load(f)
                skip_urls = retry_ctx.get("failed_urls", [])
                if skip_urls:
                    logger.info(f"[UnifiedFlow] Phase 4: Will skip {len(skip_urls)} failed URLs from retry context")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[UnifiedFlow] Could not read retry_context.json: {e}")

        # Load recipe to get agent loop config (mode-based selection)
        recipe = load_recipe(f"pipeline/phase4_coordinator_{mode}")
        agent_config = getattr(recipe, '_raw_spec', {}).get('agent_loop', {})
        max_steps = agent_config.get('max_steps', 10)

        # Track if internet.research has already been called this turn
        # (Prevents LLM from ignoring prompt instructions to only call it once)
        # Initialize early so we can set it based on §4 check
        research_already_called = False
        research_exhausted = False  # True when research returned 0 findings - block ALL retries
        previous_research_queries: set = set()

        # Initialize §4 with header
        # On RETRY: Keep existing §4 content (research results) - don't re-run research
        if context_doc.has_section(4):
            existing_section4 = context_doc.get_section(4)
            # Check if research was already executed (look for success marker)
            if "internet.research" in existing_section4 and "success" in existing_section4:
                logger.info("[UnifiedFlow] RETRY: Keeping existing §4 with research results")
                # DON'T block all research - extract query to allow DIFFERENT queries
                import re
                query_match = re.search(r'`internet\.research`.*?"query":\s*"([^"]+)"', existing_section4)
                if query_match:
                    previous_research_queries.add(query_match.group(1).lower().strip())
                    research_already_called = True  # Only blocks same query
                # Don't clear §4 - keep the research results
            else:
                context_doc.update_section(4, "*(Agent loop restarting...)*")
        else:
            context_doc.append_section(4, "Tool Execution", "*(Agent loop starting...)*")

        # Accumulated results across all steps
        all_tool_results = []
        all_claims = []
        all_rejected = []
        step_log = []

        # === TERMINATION TRACKING ===
        # Limits per architecture doc (phase4-coordinator.md)
        MAX_CONSECUTIVE_FAILURES = 3   # Same error repeating 3x = systemic issue
        MAX_TOOL_CALLS = 20            # Safety net for runaway tool invocations
        MAX_RETRIES_PER_TOOL = 2       # Persistent failures won't resolve

        # === FAILURE CATEGORIES (Tier 10 #38 implementation) ===
        # Category A (Recoverable): LLM decides whether to retry
        CATEGORY_A_FAILURES = [
            "timeout",
            "network_error",
            "empty_result",
            "parse_error",
        ]

        # Category B (Critical): Require human intervention
        CATEGORY_B_FAILURES = [
            "authentication_failed",
            "permission_denied",
            "service_unavailable",
            "rate_limit_exceeded",
            "invalid_tool",
            "schema_validation_failed",
        ]

        # Combined for backward compatibility
        CRITICAL_FAILURES = CATEGORY_B_FAILURES

        # State tracking
        consecutive_failures = 0
        total_tool_calls = 0
        failed_tools = set()
        tool_call_history = []  # For circular detection: [(tool_name, args_hash), ...]
        termination_reason = None

        # === AGENT LOOP ===
        step = 0
        final_decision = None

        while step < max_steps:
            step += 1
            logger.info(f"[UnifiedFlow] Agent Loop - Step {step}/{max_steps}")

            # 1. Write current context.md (with accumulated §4)
            self._write_context_md(turn_dir, context_doc)

            # Check budget before LLM call
            self._check_budget(context_doc, recipe, f"Phase 4 Step {step}")

            # 2. Build prompt and call LLM for decision
            try:
                pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
                prompt = pack.as_prompt()

                llm_response = await self.llm_client.call(
                    prompt=prompt,
                    role="coordinator",
                    max_tokens=recipe.token_budget.output,
                    temperature=0.4  # Lower temp for more deterministic tool selection
                )

                decision = self._parse_agent_decision(llm_response)

            except Exception as e:
                logger.error(f"[UnifiedFlow] Agent decision failed at step {step}: {e}")
                decision = {"action": "BLOCKED", "reasoning": f"LLM error: {e}"}

            action = decision.get("action", "BLOCKED")
            reasoning = decision.get("reasoning", "")

            # 3. Handle decision
            if action == "DONE":
                logger.info(f"[UnifiedFlow] Agent Loop - DONE at step {step}: {reasoning}")
                step_log.append(f"### Step {step}: Complete\n**Decision:** DONE\n**Reasoning:** {reasoning}")
                final_decision = decision
                break

            if action == "BLOCKED":
                logger.warning(f"[UnifiedFlow] Agent Loop - BLOCKED at step {step}: {reasoning}")
                step_log.append(f"### Step {step}: Blocked\n**Decision:** BLOCKED\n**Reason:** {reasoning}")
                final_decision = decision
                break

            # 4. TOOL_CALL - Execute tools
            tools_to_execute = decision.get("tools", [])
            if not tools_to_execute:
                logger.warning(f"[UnifiedFlow] Agent Loop - TOOL_CALL but no tools specified")
                step_log.append(f"### Step {step}: Error\n**Issue:** TOOL_CALL with no tools")
                continue

            step_results = []
            step_tools_desc = []

            for tool_spec in tools_to_execute:
                tool_name = tool_spec.get("tool", "")
                tool_args = tool_spec.get("args", {})
                tool_purpose = tool_spec.get("purpose", "execute")

                if not tool_name:
                    continue

                # === CHECK: Max tool calls limit ===
                if total_tool_calls >= MAX_TOOL_CALLS:
                    logger.warning(f"[UnifiedFlow] Max tool calls ({MAX_TOOL_CALLS}) reached, stopping")
                    termination_reason = "max_tool_calls"
                    step_tools_desc.append(f"- `{tool_name}`: SKIPPED (max tool calls reached)")
                    break

                # Skip tools that have already failed/timed out (prevents retry loops)
                if tool_name in failed_tools:
                    logger.info(f"[UnifiedFlow] Skipping '{tool_name}' - already failed/timed out")
                    step_tools_desc.append(f"- `{tool_name}`: SKIPPED (previously failed)")
                    continue

                # GUARD: Prevent duplicate internet.research calls
                # LLM sometimes ignores prompt instructions - enforce programmatically
                if tool_name == "internet.research":
                    current_query = tool_args.get("query", "").lower().strip()
                    logger.info(f"[UnifiedFlow] Research guard check: exhausted={research_exhausted}, already_called={research_already_called}, current_query='{current_query[:50]}...', previous_queries={len(previous_research_queries)}")

                    # Block ALL research if previous attempt returned 0 findings
                    # (Different queries won't help - the site/search is just not returning results)
                    if research_exhausted:
                        logger.warning(f"[UnifiedFlow] Blocking research - previous attempt returned 0 findings")
                        step_tools_desc.append(f"- `{tool_name}`: SKIPPED (research exhausted - 0 findings)")
                        continue

                    # Block same-query calls (but allow different queries on RETRY)
                    if research_already_called and current_query in previous_research_queries:
                        logger.warning(f"[UnifiedFlow] Blocking duplicate internet.research call (same query)")
                        step_tools_desc.append(f"- `{tool_name}`: SKIPPED (already called with same query)")
                        continue
                    elif research_already_called:
                        logger.info(f"[UnifiedFlow] Allowing new internet.research query on RETRY: {current_query[:50]}...")

                # === CHECK: Circular call pattern ===
                args_hash = self._hash_tool_args(tool_args)
                tool_call_history.append((tool_name, args_hash))
                if self._detect_circular_calls(tool_call_history):
                    logger.warning(f"[UnifiedFlow] Circular call pattern detected, stopping")
                    termination_reason = "circular_pattern"
                    step_tools_desc.append(f"- `{tool_name}`: SKIPPED (circular pattern detected)")
                    break

                # Execute the tool with timeout
                # Use RESEARCH_TIMEOUT for internet.research (can take 10+ minutes with CAPTCHAs)
                # Other tools use shorter timeout
                if tool_name == "internet.research":
                    tool_timeout = int(os.environ.get("RESEARCH_TIMEOUT", 600))  # Default 10 min for research
                else:
                    tool_timeout = 300  # 5 min for other tools

                total_tool_calls += 1
                try:
                    result = await asyncio.wait_for(
                        self._execute_single_tool(
                            tool_name, tool_args, context_doc, skip_urls=skip_urls
                        ),
                        timeout=tool_timeout
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[UnifiedFlow] Tool '{tool_name}' timed out after {tool_timeout}s")
                    result = {
                        "tool": tool_name,
                        "status": "timeout",
                        "error": f"Tool execution timed out after {tool_timeout} seconds",
                        "claims": [],
                        "raw_result": {}
                    }
                    # Mark tool as failed to prevent retries
                    failed_tools.add(tool_name)
                    consecutive_failures += 1
                    context_doc.update_execution_state(4, "Coordinator", consecutive_errors=consecutive_failures)
                    logger.warning(f"[UnifiedFlow] Consecutive failures: {consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}")

                # === CHECK: Category B Critical Failures (require intervention) ===
                error_type = result.get("error_type", "") or result.get("error", "")
                if any(crit in str(error_type).lower() for crit in CATEGORY_B_FAILURES):
                    logger.error(f"[UnifiedFlow] Category B failure detected: {error_type}")

                    # Request human intervention
                    intervention = await self.intervention_manager.request_intervention(
                        blocker_type="critical_failure",
                        url=result.get("url", "tool execution"),
                        blocker_details={
                            "failure_type": error_type,
                            "tool": tool_name,
                            "context": f"Executing {tool_name}",
                            "options": ["Proceed anyway", "Skip this source", "Cancel query"]
                        }
                    )

                    # Wait for resolution with timeout (default 180s)
                    intervention_timeout = int(os.environ.get("INTERVENTION_TIMEOUT", "180"))
                    resolved = await intervention.wait_for_resolution(timeout=intervention_timeout)

                    if not resolved or intervention.status == InterventionStatus.CANCELLED:
                        logger.warning(f"[UnifiedFlow] Intervention cancelled/timeout for {tool_name}")
                        termination_reason = f"critical_failure:{error_type}"
                        step_results.append(result)
                        all_tool_results.append(result)
                        break
                    elif intervention.status == InterventionStatus.SKIPPED:
                        # User chose to skip this source
                        logger.info(f"[UnifiedFlow] User skipped {tool_name}, continuing")
                        failed_tools.add(tool_name)
                        step_results.append(result)
                        all_tool_results.append(result)
                        continue  # Continue with next tool
                    else:
                        # User chose to proceed anyway
                        logger.info(f"[UnifiedFlow] User approved proceeding despite {error_type}")
                        # Continue with the result as-is

                # Check if result indicates failure (error or no claims)
                if result.get("status") in ("error", "failed", "timeout"):
                    failed_tools.add(tool_name)
                    consecutive_failures += 1
                    context_doc.update_execution_state(4, "Coordinator", consecutive_errors=consecutive_failures)
                    # Mark research as exhausted on failure - retries won't help
                    if tool_name == "internet.research":
                        research_exhausted = True
                        logger.warning(f"[UnifiedFlow] Research failed - marking as exhausted (no retries)")
                else:
                    # Reset on success
                    consecutive_failures = 0
                    context_doc.update_execution_state(4, "Coordinator", consecutive_errors=0)
                    # Mark internet.research as called (prevents duplicate calls with same query)
                    if tool_name == "internet.research":
                        research_already_called = True
                        # Track the query to prevent exact duplicates but allow modified queries
                        query_used = tool_args.get("query", "").lower().strip()
                        if query_used:
                            previous_research_queries.add(query_used)

                        # Check for 0 findings - mark research as exhausted to prevent retry loops
                        raw_result = result.get("result", {})
                        findings = raw_result.get("findings", [])
                        findings_count = len(findings) if findings else 0
                        logger.info(f"[UnifiedFlow] Research marked as called, tracking query: '{query_used[:50]}...' (total tracked: {len(previous_research_queries)}, findings: {findings_count})")

                        if findings_count == 0:
                            research_exhausted = True
                            logger.warning(f"[UnifiedFlow] Research returned 0 findings - marking as exhausted (no retries)")

                step_results.append(result)
                all_tool_results.append(result)

                # Collect description
                status = result.get("status", "executed")
                desc = result.get("description", tool_purpose)
                step_tools_desc.append(f"- `{tool_name}`: {desc} ({status})")

                # Collect claims
                for claim in result.get("claims", []):
                    all_claims.append(claim)
                    context_doc.add_claim(
                        content=claim['content'],
                        confidence=claim['confidence'],
                        source=claim['source'],
                        ttl_hours=claim.get('ttl_hours', 24)
                    )

                # Collect rejected products
                raw_result = result.get("raw_result", {})
                if isinstance(raw_result, dict):
                    all_rejected.extend(raw_result.get("rejected", []))

            # === CHECK: Termination triggered during tool execution ===
            if termination_reason:
                logger.warning(f"[UnifiedFlow] Agent Loop - Terminating: {termination_reason}")
                step_log.append(f"### Step {step}: Terminated\n**Reason:** {termination_reason}")
                if "critical_failure" in termination_reason:
                    final_decision = {"action": "BLOCKED", "reasoning": termination_reason}
                else:
                    # For max_tool_calls or circular_pattern, return partial results
                    final_decision = {"action": "DONE", "reasoning": f"Early termination: {termination_reason}"}
                break

            # === CHECK: All tools skipped (e.g., duplicate research blocked) ===
            # If coordinator requested tools but all were skipped, force DONE
            # This triggers when: (1) we have claims in memory, OR (2) on RETRY with existing §4 results
            if not step_results and (all_claims or research_already_called):
                logger.info(f"[UnifiedFlow] All tools skipped at step {step}, forcing DONE (claims={len(all_claims)}, retry_with_results={research_already_called})")
                step_log.append(f"### Step {step}: Auto-Complete\n**Decision:** DONE (research already executed)\n**Claims:** {len(all_claims)}")
                final_decision = {"action": "DONE", "reasoning": "Research already complete, using existing results"}
                break

            # 5. Build step log entry
            results_summary = self._summarize_tool_results(step_results)
            step_entry = f"""### Step {step}
**Action:** {reasoning}
**Tools:**
{chr(10).join(step_tools_desc)}
**Results:**
{results_summary}
"""
            step_log.append(step_entry)

            # 6. Update §4 with accumulated log
            updated_section = chr(10).join(step_log)
            context_doc.update_section(4, updated_section)

            logger.info(f"[UnifiedFlow] Agent Loop - Step {step} complete: {len(step_results)} tools executed")

            # === EARLY TERMINATION FOR CONSECUTIVE FAILURES ===
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.warning(f"[UnifiedFlow] Agent Loop - Too many consecutive failures ({consecutive_failures}), exiting")
                step_log.append(f"### Step {step}: Aborted\n**Decision:** BLOCKED (too many tool failures)\n**Failed tools:** {', '.join(failed_tools)}")
                final_decision = {"action": "BLOCKED", "reasoning": f"Too many tool failures: {', '.join(failed_tools)}"}
                break

            # === EARLY TERMINATION FOR NAVIGATIONAL/GENERAL QUERIES ===
            # The LLM may not recognize when to stop, so we enforce it in code
            # For navigational or general info queries, 1-2 successful research calls is enough
            if step >= 1 and all_claims:
                # Check if this is a navigational/general query (not commerce)
                action_needed = context_doc.get_action_needed()
                data_reqs = context_doc.get_data_requirements()

                # Navigation or informational queries (not needing current prices) terminate early
                is_navigational = (
                    action_needed == "navigate_to_site" or
                    (action_needed == "live_search" and not data_reqs.get("needs_current_prices", False))
                )

                # For navigational/general queries with claims, stop after 1 step
                # For commerce, allow up to 3 steps to gather more products
                if is_navigational and len(all_claims) >= 2:
                    logger.info(f"[UnifiedFlow] Early termination: navigational query with {len(all_claims)} claims after step {step}")
                    step_log.append(f"### Step {step}: Early Complete\n**Decision:** DONE (navigational query satisfied)\n**Claims:** {len(all_claims)}")
                    final_decision = {"action": "DONE", "reasoning": "Navigational query satisfied with sufficient content"}
                    break
                elif not is_navigational and step >= 3 and len(all_claims) >= 5:
                    # Commerce/other: stop after 3 steps with 5+ claims
                    logger.info(f"[UnifiedFlow] Early termination: commerce query with {len(all_claims)} claims after step {step}")
                    step_log.append(f"### Step {step}: Early Complete\n**Decision:** DONE (sufficient products found)\n**Claims:** {len(all_claims)}")
                    final_decision = {"action": "DONE", "reasoning": "Sufficient products gathered"}
                    break

        # === END AGENT LOOP ===

        # Check if we hit max steps
        if step >= max_steps and final_decision is None:
            logger.warning(f"[UnifiedFlow] Agent Loop - Max steps ({max_steps}) reached")
            step_log.append(f"### Step {step}: Max Steps Reached\n**Decision:** Forced exit after {max_steps} steps")

        # Build final §4 content with claims table
        claims_table = ["| Claim | Confidence | Source | TTL |", "|-------|------------|--------|-----|"]
        if all_claims:
            claim_summaries = await self._summarize_claims_batch(all_claims, max_chars_per_claim=300)
            for i, claim in enumerate(all_claims):
                ttl = claim.get('ttl_hours', 24)
                summary = claim_summaries[i] if i < len(claim_summaries) else claim['content'][:100]
                source_display = claim['source'][:60] + "..." if len(claim['source']) > 60 else claim['source']
                claims_table.append(f"| {summary} | {claim['confidence']:.2f} | {source_display} | {ttl}h |")

        # Build rejected products section
        rejected_section = ""
        if all_rejected:
            rejected_lines = ["| Product | Vendor | Rejection Reason |", "|---------|--------|------------------|"]
            for rej in all_rejected[:10]:
                name = rej.get("name", "Unknown")[:40]
                vendor = rej.get("vendor", "unknown")
                reason = rej.get("rejection_reason", "Unknown")[:50]
                rejected_lines.append(f"| {name} | {vendor} | {reason} |")
            rejected_section = f"""
**Rejected Products ({len(all_rejected)} total):**
*Products considered but excluded - DO NOT include these in the response*
{chr(10).join(rejected_lines)}
"""

        # Determine status based on final_decision
        if final_decision:
            status = "success" if final_decision.get("action") == "DONE" else "blocked"
        elif step >= max_steps:
            status = "partial"
        else:
            status = "unknown"

        # Build termination info for observability
        termination_info = ""
        if termination_reason:
            termination_info = f"\n**Termination Reason:** {termination_reason}"
        elif step >= max_steps:
            termination_info = f"\n**Termination Reason:** max_iterations ({max_steps})"

        # Final §4 content
        final_section = f"""## Execution Log ({step} steps)

**Status:** {status}
**Iterations:** {step}/{max_steps}
**Tool Calls:** {total_tool_calls}/{MAX_TOOL_CALLS}{termination_info}

{chr(10).join(step_log)}

---

**Claims Extracted:**
{chr(10).join(claims_table)}
{rejected_section}"""
        context_doc.update_section(4, final_section)

        # Build ticket.md and toolresults.md content
        ticket_content = self._build_ticket_content(context_doc, {"tools": [r.get("tool", r.get("tool_name", "unknown")) for r in all_tool_results]})
        toolresults_content = self._build_toolresults_content(context_doc, all_tool_results)

        # Write research documents for internet.research results
        await self._write_research_documents(all_tool_results, context_doc)

        # Update knowledge graph with extracted entities (compounding context)
        await self._update_knowledge_graph(all_tool_results, context_doc)

        # Write toolresults.md for Phase 5
        toolresults_path = turn_dir.doc_path("toolresults.md")
        toolresults_path.write_text(toolresults_content)
        logger.info(f"[UnifiedFlow] Wrote toolresults.md for synthesis ({len(toolresults_content)} chars)")

        # Emit completion event
        await self._emit_phase_event(trace_id, 5, "completed", "Coordination complete")

        logger.info(f"[UnifiedFlow] Phase 4 complete: {step} steps, {len(all_tool_results)} tools, {len(context_doc.claims)} claims")
        return context_doc, ticket_content, toolresults_content

    def _parse_agent_decision(self, llm_response: str) -> Dict[str, Any]:
        """Parse agent decision from LLM response.

        Handles two formats:
        1. AGENT_DECISION: {action: TOOL_CALL|DONE|BLOCKED, tools: [...]}
        2. TOOL_SELECTION (legacy): {_type: TOOL_SELECTION, tool: "...", config: {...}}
        """
        try:
            # Try to parse as JSON
            decision = self._parse_json_response(llm_response)

            # Handle legacy TOOL_SELECTION format (from core.md prompt)
            if decision.get("_type") == "TOOL_SELECTION":
                tool_name = decision.get("tool", "")
                config = decision.get("config", {})
                rationale = decision.get("rationale", "Tool selected")

                if tool_name:
                    logger.info(f"[UnifiedFlow] Converting TOOL_SELECTION to AGENT_DECISION: {tool_name}")
                    return {
                        "action": "TOOL_CALL",
                        "tools": [{
                            "tool": tool_name,
                            "args": config,
                            "purpose": rationale
                        }],
                        "reasoning": rationale,
                        "progress_summary": "Executing tool from selection",
                        "remaining_work": "Complete tool execution"
                    }
                else:
                    # No tool specified - treat as DONE (synthesis can handle)
                    return {
                        "action": "DONE",
                        "reasoning": "No tool needed",
                        "progress_summary": "Ready for synthesis"
                    }

            # Handle AGENT_DECISION format
            if "action" in decision:
                return decision

            # Try to infer action from content
            response_lower = llm_response.lower()
            if "done" in response_lower:
                decision["action"] = "DONE"
            elif "blocked" in response_lower:
                decision["action"] = "BLOCKED"
            elif decision.get("tool") or decision.get("tools"):
                # Has tool info but no action - assume TOOL_CALL
                decision["action"] = "TOOL_CALL"
                if decision.get("tool") and not decision.get("tools"):
                    decision["tools"] = [{"tool": decision["tool"], "args": decision.get("config", {}), "purpose": "execute"}]
            else:
                decision["action"] = "BLOCKED"
                decision["reasoning"] = "Could not parse action from response"

            return decision

        except Exception as e:
            logger.warning(f"[UnifiedFlow] Failed to parse agent decision: {e}")
            return {
                "action": "BLOCKED",
                "reasoning": f"Failed to parse LLM response: {str(e)[:100]}"
            }

    async def _phase5_synthesis(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        mode: str
    ) -> Tuple[ContextDocument, str]:
        """
        Phase 5: Synthesis (recipe-based)

        Generates the draft response from context.md.
        """
        logger.info(f"[UnifiedFlow] Phase 5: Synthesis")

        # Write current context.md for recipe to read
        self._write_context_md(turn_dir, context_doc)

        # Load recipe and build doc pack (mode-based selection only)
        # Domain-specific prompts removed in favor of unified prompts that handle all content types
        try:
            recipe = load_recipe(f"pipeline/phase5_synthesizer_{mode}")

            # Check budget before LLM call
            self._check_budget(context_doc, recipe, "Phase 5 Synthesis")
            pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
            prompt = pack.as_prompt()

            # Call LLM
            llm_response = await self.llm_client.call(
                prompt=prompt,
                role="guide",
                max_tokens=recipe.token_budget.output,
                temperature=0.7
            )

            # Parse response (may be JSON with "answer" field or plain text)
            # Be tolerant of LLM format variations - if JSON parsing fails, use raw text
            stripped = llm_response.strip()
            looks_like_json = (
                stripped.startswith("{") or
                stripped.startswith("```json") or
                stripped.startswith("```")
            )
            if looks_like_json:
                try:
                    result = self._parse_json_response(llm_response)
                    response = result.get("answer", llm_response)
                except (ValueError, json.JSONDecodeError):
                    # JSON parsing failed - just use the raw response
                    logger.warning("[UnifiedFlow] Synthesis JSON parsing failed, using raw response")
                    response = stripped
            else:
                response = stripped

        except Exception as e:
            logger.error(f"[UnifiedFlow] Synthesis recipe failed: {e}")
            raise RuntimeError(f"Synthesis phase failed: {e}") from e

        # Build §5 content (full draft for validation)
        # On RETRY, update existing section
        section_content = f"""**Draft Response:**
{response}
"""
        if context_doc.has_section(5):
            context_doc.update_section(5, section_content)
        else:
            context_doc.append_section(5, "Synthesis", section_content)

        logger.info(f"[UnifiedFlow] Phase 5 complete: {len(response)} chars")
        return context_doc, response

    async def _phase6_validation(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        response: str,
        mode: str,
        loop_count: int = 0
    ) -> Tuple[ContextDocument, str, ValidationResult]:
        """
        Phase 6: Validation (recipe-based)

        Validates the response before sending:
        - Claims match evidence
        - No hallucinations
        - Response addresses query
        - Coherent formatting
        - URL verification (NEW)
        - Price cross-check (NEW)

        Returns ValidationResult with decision: APPROVE, REVISE, RETRY, or FAIL
        - REVISE: Minor issues, re-synthesize with hints
        - RETRY: Stale data detected, loop back to Phase 1
        """
        logger.info(f"[UnifiedFlow] Phase 6: Validation (loop={loop_count})")

        checks_performed = []
        all_issues = []
        revision_count = 0
        confidence = 0.8

        # Initialize URL tracking variables (avoid NameError if URL check is skipped)
        valid_urls: List[str] = []
        invalid_urls: List[str] = []

        # Track original response and hints for principle extraction
        # When REVISE succeeds (APPROVE after revision), we extract a transferable principle
        original_response_for_principle = response
        revision_hints_for_principle = ""
        revision_focus_for_principle = ""

        # PROGRAMMATIC URL CHECK (defense in depth - catches what LLM might miss)
        # This runs BEFORE the LLM validation as a pre-filter
        unhealthy_urls, url_issues = get_unhealthy_urls(response)
        if unhealthy_urls:
            logger.warning(f"[UnifiedFlow] Programmatic URL check failed: {url_issues}")
            checks_performed.append("programmatic_url_check_failed")

            # For commerce queries with fake URLs, we need to RETRY
            # Check if this is a commerce/transactional query
            original_query = context_doc.get_original_query() if hasattr(context_doc, 'get_original_query') else ""
            is_commerce = any(kw in original_query.lower() for kw in [
                "buy", "purchase", "for sale", "cheapest", "price", "cost", "order"
            ])

            if is_commerce:
                # Commerce query with bad URLs - must retry to get real links
                logger.warning(f"[UnifiedFlow] Commerce query with fake URLs - triggering RETRY")

                failure_context = ValidationFailureContext(
                    reason="FAKE_URL_DETECTED",
                    failed_claims=[],
                    failed_urls=unhealthy_urls,
                    mismatches=[],
                    retry_count=loop_count + 1,
                    suggested_fixes=["Evidence contains fake/corrupted URLs - re-research needed to get real product links"]
                )

                self._write_validation_section(
                    context_doc, "RETRY", 0.3, 0,
                    ["Programmatic URL check: " + "; ".join(url_issues)],
                    ["Re-research needed - URLs appear to be placeholders or corrupted"]
                )

                return context_doc, response, ValidationResult(
                    decision="RETRY",
                    confidence=0.3,
                    issues=["Programmatic URL check failed: " + "; ".join(url_issues)],
                    failure_context=failure_context,
                    checks_performed=checks_performed,
                    retry_count=loop_count + 1
                )
            else:
                # Non-commerce query - log warning but continue to LLM validation
                # The LLM might still catch it, or it might not matter as much
                all_issues.append(f"Programmatic URL check warning: {'; '.join(url_issues)}")
                logger.info(f"[UnifiedFlow] Non-commerce query - continuing to LLM validation despite URL issues")
        else:
            checks_performed.append("programmatic_url_check_passed")
            logger.debug("[UnifiedFlow] Programmatic URL check passed")

        while revision_count <= MAX_VALIDATION_REVISIONS:
            # Write current context.md for recipe to read (§5 contains draft response)
            self._write_context_md(turn_dir, context_doc)

            # Load recipe and build doc pack (pipeline recipe)
            llm_response = ""  # Initialize before try block for error handler
            try:
                recipe = load_recipe("pipeline/phase6_validator")

                # Check budget before LLM call
                self._check_budget(context_doc, recipe, f"Phase 6 Validation (revision={revision_count})")

                pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
                prompt = pack.as_prompt()

                # Call LLM
                llm_response = await self.llm_client.call(
                    prompt=prompt,
                    role="guide",
                    max_tokens=recipe.token_budget.output,
                    temperature=0.3
                )

                # Parse VALIDATION JSON
                result = self._parse_json_response(llm_response)
                decision = result.get("decision", "APPROVE")
                issues_raw = result.get("issues", [])
                # Ensure issues is a list (LLM may return string)
                if isinstance(issues_raw, str):
                    issues = [issues_raw] if issues_raw else []
                else:
                    issues = issues_raw or []
                confidence = result.get("confidence", 0.8)
                revision_hints = result.get("revision_hints", "")
                suggested_fixes_raw = result.get("suggested_fixes", [])
                # Ensure suggested_fixes is a list (LLM may return string)
                if isinstance(suggested_fixes_raw, str):
                    suggested_fixes = [suggested_fixes_raw] if suggested_fixes_raw else []
                else:
                    suggested_fixes = suggested_fixes_raw or []
                checks = result.get("checks", {})
                checks_performed.append("llm_validation")

                # Parse goal statuses for multi-goal queries (#57)
                goal_statuses_raw = result.get("goal_statuses", [])
                goal_statuses = []
                for gs in goal_statuses_raw:
                    goal_statuses.append(GoalStatus(
                        goal_id=gs.get("goal_id", "unknown"),
                        description=gs.get("description", ""),
                        score=gs.get("score", 0.0),
                        status=gs.get("status", "unfulfilled"),
                        evidence=gs.get("evidence")
                    ))

                # Handle RETRY from LLM validator (results_match_intent=false, all_tasks_completed=false)
                if decision == "RETRY":
                    logger.info(f"[UnifiedFlow] LLM Validator returned RETRY: {issues}")

                    failure_context = ValidationFailureContext(
                        reason="LLM_VALIDATION_RETRY",
                        failed_claims=[],
                        failed_urls=[],
                        mismatches=[],
                        retry_count=loop_count + 1,
                        suggested_fixes=suggested_fixes
                    )

                    # Write §6 with suggested_fixes so Planner can read them
                    self._write_validation_section(
                        context_doc, "RETRY", confidence, revision_count, issues, suggested_fixes
                    )

                    return context_doc, response, ValidationResult(
                        decision="RETRY",
                        confidence=confidence,
                        issues=issues,
                        failure_context=failure_context,
                        checks_performed=checks_performed,
                        retry_count=loop_count + 1
                    )

            except Exception as e:
                logger.error(f"[UnifiedFlow] Validator recipe failed: {e}")
                # Fallback: Try to extract decision via regex if JSON parsing failed
                decision_match = re.search(r'"decision"\s*:\s*"(APPROVE|REVISE|RETRY|FAIL)"', llm_response)
                if decision_match:
                    decision = decision_match.group(1)
                    logger.warning(f"[UnifiedFlow] Extracted validation decision via regex fallback: {decision}")
                    if decision == "RETRY":
                        # Extract issues if possible
                        issues_match = re.search(r'"issues"\s*:\s*\[(.*?)\]', llm_response, re.DOTALL)
                        issues = []
                        if issues_match:
                            try:
                                issues = [s.strip().strip('"') for s in issues_match.group(1).split('",') if s.strip()]
                            except:
                                issues = ["Validation identified issues but couldn't parse details"]
                        return context_doc, response, ValidationResult(
                            decision="RETRY",
                            confidence=0.5,
                            issues=issues,
                            failure_context=ValidationFailureContext(
                                reason="LLM_VALIDATION_RETRY",
                                failed_claims=[],
                                failed_urls=[],
                                mismatches=[],
                                retry_count=loop_count + 1,
                                suggested_fixes=[]
                            ),
                            checks_performed=checks_performed,
                            retry_count=loop_count + 1
                        )
                    elif decision == "APPROVE":
                        # Proceed with approval via fallback
                        result = {"decision": "APPROVE", "confidence": 0.7}
                        issues = []
                        confidence = 0.7
                        revision_hints = ""
                        suggested_fixes = []
                        checks = {}
                        goal_statuses = []
                    else:
                        raise RuntimeError(f"Validation phase failed: {e}") from e
                else:
                    raise RuntimeError(f"Validation phase failed: {e}") from e

            if decision == "APPROVE":
                # Initialize check results with defaults
                urls_ok = True  # Will be updated by URL verification check
                valid_urls = []
                invalid_urls = []

                # ADDITIONAL CHECK 1: Cross-check prices against fresh research
                price_ok, missing_prices, price_hint = self._cross_check_prices(response, turn_dir)
                checks_performed.append("price_crosscheck")

                if not price_ok:
                    all_issues.append(f"Price mismatch: {missing_prices}")

                    # If this is the first loop and prices are stale, trigger RETRY
                    if loop_count < MAX_VALIDATION_RETRIES - 1:
                        logger.warning(f"[UnifiedFlow] Price mismatch detected, triggering RETRY")

                        failure_context = ValidationFailureContext(
                            reason="PRICE_STALE",
                            failed_claims=[],
                            failed_urls=[],
                            mismatches=[{"field": "price", "expected": p, "actual": "unknown"} for p in missing_prices],
                            retry_count=loop_count + 1
                        )

                        # Build §6 content for RETRY
                        self._write_validation_section(context_doc, "RETRY", confidence, revision_count, all_issues)

                        return context_doc, response, ValidationResult(
                            decision="RETRY",
                            confidence=0.0,
                            issues=all_issues,
                            failure_context=failure_context,
                            checks_performed=checks_performed,
                            prices_checked=len(missing_prices),
                            retry_count=loop_count + 1
                        )

                    # Max loops reached, try REVISE instead
                    if revision_count < MAX_VALIDATION_REVISIONS:
                        decision = "REVISE"
                        issues.append(f"Stale prices detected: {missing_prices}")
                        revision_hints = price_hint
                        logger.warning(f"[UnifiedFlow] Max loops reached, trying REVISE")

                # ADDITIONAL CHECK 2: URL verification (cross-reference against research.json)
                # NOTE: This check is now advisory-only (no RETRY) because:
                # 1. Phase 1 intelligence URLs may not be in research.json
                # 2. The research already visited and validated URLs via browser
                # 3. Triggering RETRY causes infinite loops with no benefit
                if decision == "APPROVE":
                    urls_ok, valid_urls, invalid_urls = await self._verify_urls_in_response(response, turn_dir)
                    checks_performed.append("url_verification")

                    if not urls_ok:
                        # Log the issue but DON'T trigger RETRY - just note it
                        logger.warning(
                            f"[UnifiedFlow] Some URLs not in research.json (advisory only, not blocking): "
                            f"{[u[:50] for u in invalid_urls]}"
                        )
                        # Don't add to all_issues or trigger RETRY - this was causing infinite loops

                # All checks passed - APPROVE or APPROVE_PARTIAL (#57)
                if decision == "APPROVE":
                    # Check for partial success with multi-goal queries
                    partial_message = None
                    final_decision = "APPROVE"

                    if goal_statuses:
                        fulfilled = [g for g in goal_statuses if g.status == "fulfilled"]
                        unfulfilled = [g for g in goal_statuses if g.status in ("unfulfilled", "partial")]

                        if fulfilled and unfulfilled:
                            # Some goals succeeded, some didn't -> APPROVE_PARTIAL
                            final_decision = "APPROVE_PARTIAL"
                            fulfilled_desc = ", ".join(g.description[:50] for g in fulfilled)
                            unfulfilled_desc = ", ".join(g.description[:50] for g in unfulfilled)
                            partial_message = (
                                f"I found information about: {fulfilled_desc}. "
                                f"However, I couldn't find reliable information about: {unfulfilled_desc} - "
                                f"would you like me to search specifically for that?"
                            )
                            logger.info(f"[UnifiedFlow] Phase 6: APPROVE_PARTIAL - {len(fulfilled)} fulfilled, {len(unfulfilled)} unfulfilled")

                    logger.info(f"[UnifiedFlow] Phase 6: Validation {final_decision} (confidence={confidence:.2f})")

                    # Extract improvement principle if this APPROVE followed a REVISE
                    # This captures "what made the revision better" for future similar queries
                    if revision_count > 0 and revision_hints_for_principle:
                        try:
                            # Get turn_id from turn_dir name
                            turn_id = turn_dir.name if hasattr(turn_dir, 'name') else str(turn_dir)

                            # Get original query from context document
                            query_section = context_doc.get_section(0) or ""

                            extractor = PrincipleExtractor(self.llm_client)
                            # Run async extraction (non-blocking - fire and forget)
                            asyncio.create_task(
                                extractor.extract_and_store(
                                    original_response=original_response_for_principle,
                                    revised_response=response,
                                    revision_hints=revision_hints_for_principle,
                                    query=query_section[:500],  # Truncate query for context
                                    turn_id=turn_id,
                                    revision_focus=revision_focus_for_principle,
                                )
                            )
                            logger.info(f"[UnifiedFlow] Triggered async principle extraction for successful revision")
                        except Exception as e:
                            # Principle extraction is optional - don't fail validation
                            logger.warning(f"[UnifiedFlow] Principle extraction failed (non-fatal): {e}")

                    self._write_validation_section(
                        context_doc, final_decision,
                        confidence, revision_count, [],
                        checks=checks, urls_ok=urls_ok, price_ok=price_ok
                    )

                    # Extract term_analysis and unsourced_claims from LLM result if present
                    term_analysis = result.get("term_analysis", {})
                    unsourced_claims = result.get("unsourced_claims", [])

                    return context_doc, response, ValidationResult(
                        decision=final_decision,
                        confidence=confidence,
                        issues=[],
                        checks_performed=checks_performed,
                        urls_verified=len(valid_urls),
                        retry_count=loop_count,
                        goal_statuses=goal_statuses,
                        partial_message=partial_message,
                        checks=checks,
                        term_analysis=term_analysis,
                        unsourced_claims=unsourced_claims
                    )

            if decision == "REVISE" and revision_count < MAX_VALIDATION_REVISIONS:
                revision_count += 1
                logger.info(f"[UnifiedFlow] Phase 6: REVISE requested (attempt {revision_count})")
                logger.info(f"[UnifiedFlow] Issues: {issues}")
                logger.info(f"[UnifiedFlow] Hints: {revision_hints}")

                # Store hints for principle extraction (if APPROVE follows REVISE)
                revision_hints_for_principle = revision_hints
                revision_focus_for_principle = result.get("revision_focus", "")

                # Loop back to synthesis with hints
                response = await self._revise_synthesis(context_doc, turn_dir, response, revision_hints, mode)

                # Update §5 with revised response for next validation iteration
                revised_section = f"""**Draft Response (Revision {revision_count}):**
{response}
"""
                context_doc.update_section(5, revised_section)
                all_issues.extend(issues)

            else:
                # FAIL or max revisions reached
                logger.warning(f"[UnifiedFlow] Phase 6: Validation FAILED - {issues}")
                all_issues.extend(issues)
                self._write_validation_section(context_doc, "FAILED", confidence, revision_count, all_issues)

                return context_doc, response, ValidationResult(
                    decision="FAIL",
                    confidence=0.0,
                    issues=all_issues,
                    checks_performed=checks_performed,
                    retry_count=loop_count
                )

        # Should not reach here, but handle gracefully
        self._write_validation_section(context_doc, "FAILED", confidence, revision_count, all_issues)
        return context_doc, response, ValidationResult(
            decision="FAIL",
            confidence=0.0,
            issues=all_issues + ["Max revision attempts reached"],
            checks_performed=checks_performed,
            retry_count=loop_count
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
        """Write §6 Validation section to context document.

        For RETRY decisions, includes suggested_fixes so Planner can read them
        and adjust the plan accordingly.

        Args:
            checks: LLM validator's individual check results (claims_supported, no_hallucinations, etc.)
            urls_ok: Result of URL verification check
            price_ok: Result of price cross-check
        """
        passed = result == "APPROVED"

        # Use individual checks if provided, otherwise fall back to overall passed status
        if checks is None:
            checks = {}

        # Build section content
        section_content = f"""**Validation Result:** {result}
**Confidence:** {confidence:.2f}
**Revision Attempts:** {revision_count}
**Issues Found:** {", ".join(issues) if issues else "None"}
"""

        # Add suggested fixes for RETRY decisions (Planner reads these)
        if result == "RETRY" and suggested_fixes:
            section_content += f"""
**Decision:** RETRY
**Suggested Fixes for Planner:**
{chr(10).join(f"- {fix}" for fix in suggested_fixes)}
"""

        # Build checklist with granular check results
        # Each check uses its individual value from the LLM, or falls back to passed
        section_content += f"""
**Validation Checklist:**
- [{"x" if checks.get("claims_supported", passed) else " "}] Claims match evidence
- [{"x" if checks.get("no_hallucinations", passed) else " "}] No hallucinations
- [{"x" if checks.get("query_addressed", passed) else " "}] Response addresses query
- [{"x" if passed else " "}] Coherent formatting
- [{"x" if urls_ok else " "}] URLs verified
- [{"x" if price_ok else " "}] Prices cross-checked
- [{"x" if checks.get("all_tasks_completed", passed) else " "}] All tasks completed
- [{"x" if checks.get("results_match_intent", passed) else " "}] Results match intent
"""

        # ARCHITECTURAL FIX (2025-12-30): Use append_to_section to preserve retry history
        # On RETRY, append with attempt marker instead of overwriting
        if context_doc.has_section(6):
            # Add attempt header for retry history preservation
            attempt_header = f"\n\n---\n\n#### Attempt {revision_count + 1}\n"
            context_doc.append_to_section(6, attempt_header + section_content)
        else:
            # First validation - create section with attempt 1 header
            section_with_header = f"#### Attempt 1\n{section_content}"
            context_doc.append_section(6, "Validation", section_with_header)
        logger.info(f"[UnifiedFlow] Phase 6 complete: {result} (attempt {revision_count + 1})")

    async def _phase7_save(
        self,
        context_doc: ContextDocument,
        response: str,
        ticket_content: Optional[str] = None,
        toolresults_content: Optional[str] = None,
        validation_result: Optional["ValidationResult"] = None
    ) -> Path:
        """
        Phase 7: Save

        Saves all turn documents (unsummarized) and indexes the turn.
        """
        logger.info(f"[UnifiedFlow] Phase 7: Save")

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
        """
        Check if context document fits within recipe budget.
        Logs warning if compression would be needed.

        Args:
            context_doc: Current context document
            recipe: Recipe with token_budget
            phase_name: Name of the phase for logging
        """
        if not self.summarizer:
            return

        content = context_doc.get_markdown()
        documents = {"context.md": content}

        # Get budget from recipe
        budget = getattr(recipe, 'token_budget', None)
        if hasattr(budget, 'total'):
            budget = budget.total
        budget = budget or 12000

        plan = self.summarizer.check_budget(documents, budget)

        if plan.needed:
            logger.warning(
                f"[UnifiedFlow] {phase_name}: Context exceeds budget "
                f"({plan.total_tokens}/{plan.budget} tokens, overflow={plan.overflow})"
            )
        else:
            logger.debug(
                f"[UnifiedFlow] {phase_name}: Context within budget "
                f"({plan.total_tokens}/{plan.budget} tokens)"
            )

    def _detect_circular_calls(self, call_history: List[Tuple[str, str]], window: int = 4) -> bool:
        """
        Detect circular call patterns like A→B→A→B in tool call history.

        Args:
            call_history: List of (tool_name, args_hash) tuples
            window: Size of pattern window to check (default 4 for A→B→A→B)

        Returns:
            True if circular pattern detected
        """
        if len(call_history) < window:
            return False

        # Check for A→B→A→B pattern (same 2-call sequence repeated)
        recent = call_history[-window:]
        if window >= 4:
            first_pair = (recent[0], recent[1])
            second_pair = (recent[2], recent[3])
            if first_pair == second_pair:
                return True

        # Check for A→A→A pattern (same call 3+ times)
        if len(call_history) >= 3:
            last_three = call_history[-3:]
            if len(set(last_three)) == 1:
                return True

        return False

    def _hash_tool_args(self, args: Dict[str, Any]) -> str:
        """Create a simple hash of tool arguments for circular detection."""
        import hashlib
        args_str = json.dumps(args, sort_keys=True, default=str)
        return hashlib.md5(args_str.encode()).hexdigest()[:8]

    def _get_next_turn_number(self, session_id: str, user_id: str = None) -> int:
        """Get the next turn number atomically.

        Deprecated: Use TurnCounter directly with user-specific turns_dir instead.
        This method is kept for backward compatibility.
        """
        # Use default turns_dir for backward compatibility
        turns_dir = UserPathResolver.get_turns_dir(user_id)
        turn_counter = TurnCounter(turns_dir=turns_dir)
        return turn_counter.get_next_turn_number(session_id)

    def _write_context_md(self, turn_dir: TurnDirectory, context_doc: ContextDocument):
        """Write context.md to turn directory for recipe to read."""
        context_path = turn_dir.doc_path("context.md")
        context_path.write_text(context_doc.get_markdown())

    def _write_ticket_md(self, turn_dir: TurnDirectory, ticket: Dict[str, Any]):
        """Write ticket.md to turn directory."""
        ticket_path = turn_dir.doc_path("ticket.md")
        content = f"""# Task Ticket

**Goal:** {ticket.get("user_need", "Unknown")}
**Intent:** {ticket.get("intent", "unknown")}
**Tools:** {", ".join(ticket.get("recommended_tools", []))}

## Context
{json.dumps(ticket.get("context", {}), indent=2)}

## Constraints
{chr(10).join(f"- {c}" for c in ticket.get("constraints", []))}
"""
        ticket_path.write_text(content)

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from LLM response, handling code blocks and common LLM typos."""
        text = response.strip()

        # Try to extract from code block
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()

        # Extract JSON boundaries
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            text = text[json_start:json_end]

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"[UnifiedFlow] JSON parse failed: {e}, attempting repair...")

        # === JSON REPAIR STRATEGIES ===

        repaired = text

        # Fix 1: LLM typo - "="_type" → "_type" (extra = in key)
        # This catches patterns like "="_type": or "=_type":
        repaired = re.sub(r'"="?([a-zA-Z_])', r'"\1', repaired)

        # Fix 1b: LLM typo - " "_type" or " answer" → "_type" or "answer"
        # Leading space before key name
        repaired = re.sub(r'"\s+"?([a-zA-Z_])', r'"\1', repaired)

        # Fix 2: Trailing commas before ] or }
        repaired = re.sub(r',\s*([}\]])', r'\1', repaired)

        # Fix 3: Single quotes to double quotes (but not inside strings)
        # Only apply if no double quotes exist in the problematic area
        if "'" in repaired and '"' not in repaired:
            repaired = repaired.replace("'", '"')

        # Try repaired JSON
        try:
            result = json.loads(repaired)
            logger.info("[UnifiedFlow] JSON repair successful")
            return result
        except json.JSONDecodeError:
            pass

        # === LAST RESORT: Extract answer via regex ===
        # If JSON is broken but we can see the answer, extract it
        answer_match = re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)', text, re.DOTALL)
        if answer_match:
            answer_text = answer_match.group(1)
            # Unescape the string
            answer_text = answer_text.replace('\\"', '"').replace('\\n', '\n')
            logger.warning(f"[UnifiedFlow] Extracted answer via regex fallback ({len(answer_text)} chars)")
            return {
                "_type": "ANSWER",
                "answer": answer_text,
                "_repaired": True
            }

        # Failed to parse - raise error
        logger.error(f"[UnifiedFlow] Failed to parse JSON from LLM response: {text[:200]}...")
        raise ValueError(f"LLM response is not valid JSON: {text[:100]}...")

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
        """Execute tools from plan."""
        results = []
        skip_urls = skip_urls or []

        # Handle single tool selection
        if plan.get("_type") == "TOOL_SELECTION" or "tool" in plan:
            tool_name = plan.get("tool", "internet.research")
            config = plan.get("config", {})

            result = await self._execute_single_tool(tool_name, config, context_doc, skip_urls=skip_urls)
            results.append(result)

        # Handle multi-step plan
        elif "steps" in plan:
            for step in plan.get("steps", []):
                tool_name = step.get("tool", "")
                config = step.get("config", step.get("arguments", {}))

                result = await self._execute_single_tool(tool_name, config, context_doc, skip_urls=skip_urls)
                results.append(result)

        # No valid plan format - error, don't silently fallback
        else:
            logger.error(f"[UnifiedFlow] Invalid tool plan format: {plan}")
            raise ValueError(f"Coordinator returned invalid plan format. Expected 'tool' or 'steps' key, got: {list(plan.keys())}")

        return results

    async def _execute_single_tool(
        self,
        tool_name: str,
        config: Dict[str, Any],
        context_doc: ContextDocument,
        skip_urls: List[str] = None
    ) -> Dict[str, Any]:
        """Execute a single tool and extract claims."""
        import httpx
        from libs.gateway.permission_validator import get_validator, PermissionDecision

        skip_urls = skip_urls or []

        logger.info(f"[UnifiedFlow] Executing tool: {tool_name}")

        # === Permission Validation ===
        # Validates mode gates (chat vs code) and repository scope (saved repo vs external)
        validator = get_validator()
        mode = getattr(context_doc, "mode", "chat")
        session_id = context_doc.session_id

        validation = validator.validate(tool_name, config, mode, session_id)

        if validation.decision == PermissionDecision.DENIED:
            logger.warning(f"[UnifiedFlow] Tool denied by permission validator: {validation.reason}")
            return {
                "tool": tool_name,
                "status": "denied",
                "description": f"Permission denied: {validation.reason}",
                "raw_result": None,
                "claims": []
            }

        if validation.decision == PermissionDecision.NEEDS_APPROVAL:
            logger.info(
                f"[UnifiedFlow] Tool needs approval: {tool_name} - "
                f"request_id={validation.approval_request_id}"
            )

            # Wait for user approval (with timeout)
            approved = await validator.wait_for_approval(validation.approval_request_id)

            if not approved:
                logger.warning(f"[UnifiedFlow] Approval denied/timed out for {tool_name}")
                return {
                    "tool": tool_name,
                    "status": "approval_denied",
                    "description": f"User did not approve operation: {validation.reason}",
                    "raw_result": None,
                    "claims": []
                }

            logger.info(f"[UnifiedFlow] Approval granted for {tool_name}")

        # === End Permission Validation ===

        try:
            # Build tool request with required fields
            tool_request = dict(config)

            # Ensure query is present
            # Priority: 1) Coordinator-provided query, 2) Planner task description, 3) User query
            if "query" not in tool_request:
                # Try to extract resolved query from Planner's task description in §3
                resolved_query = self._extract_resolved_query_from_plan(context_doc)
                if resolved_query:
                    tool_request["query"] = resolved_query
                    logger.info(f"[UnifiedFlow] Using resolved query from Planner: '{resolved_query[:60]}...'")
                else:
                    tool_request["query"] = context_doc.query
                    logger.info(f"[UnifiedFlow] Using raw user query: '{context_doc.query[:60]}...'")
            # If query was provided in config, use it as-is (it came from Coordinator which should have resolved context)

            # Ensure session_id for tools that need it
            if "session_id" not in tool_request:
                tool_request["session_id"] = context_doc.session_id

            # Pass turn_number for research document indexing
            if "turn_number" not in tool_request:
                tool_request["turn_number"] = context_doc.turn_number

            # Pass repo parameter for code tools (repo.scope_discover, file.*, git.*)
            if "repo" not in tool_request and context_doc.repo:
                if tool_name.startswith("repo.") or tool_name.startswith("file.") or tool_name.startswith("git."):
                    tool_request["repo"] = context_doc.repo
                    logger.info(f"[UnifiedFlow] Passing repo={context_doc.repo} to {tool_name}")

            # Pass goal parameter for repo.scope_discover (derived from query)
            if tool_name == "repo.scope_discover" and "goal" not in tool_request:
                tool_request["goal"] = context_doc.query
                logger.info(f"[UnifiedFlow] Passing goal='{context_doc.query[:50]}...' to repo.scope_discover")

            # Pass phase_hint and intent to research tools (from Planner ticket)
            if "research" in tool_name:
                if "research_context" not in tool_request:
                    tool_request["research_context"] = {}

                # Check if task description indicates user wants MORE results
                # Planner includes "additional" in task description for expand/retry queries
                query = tool_request.get("query", "").lower()
                if "additional" in query or "more" in query or "retry" in query or "refresh" in query:
                    tool_request["force_refresh"] = True
                    logger.info(f"[UnifiedFlow] Detected expand/retry pattern in query - setting force_refresh=True")

                # Add phase_hint if available
                if hasattr(context_doc, "phase_hint") and context_doc.phase_hint:
                    tool_request["research_context"]["phase_hint"] = context_doc.phase_hint
                    logger.info(f"[UnifiedFlow] Adding phase_hint={context_doc.phase_hint} to {tool_name}")

                # Read user_purpose from context_doc §0 (set by Phase 0)
                action_needed = context_doc.get_action_needed()
                data_requirements = context_doc.get_data_requirements()
                user_purpose = context_doc.get_user_purpose()
                prior_context = context_doc.get_prior_context()
                logger.info(f"[UnifiedFlow] Using action from §0: {action_needed} for {tool_name}")

                # Map action_needed + data_requirements to legacy intent for orchestrator
                # Phase 0 now handles follow-up detection via prior_context.relationship
                if data_requirements.get("needs_current_prices"):
                    intent = "commerce"
                elif action_needed == "navigate_to_site":
                    intent = "navigation"
                elif action_needed == "recall_memory":
                    intent = "recall"
                elif action_needed == "live_search":
                    intent = "informational"
                else:
                    intent = "informational"

                # Build intent_metadata from new schema for backward compatibility
                content_ref = context_doc.get_content_reference()
                intent_metadata = {}
                if content_ref:
                    intent_metadata["target_url"] = content_ref.get("source_url", "")
                    intent_metadata["site_name"] = content_ref.get("site", "")

                logger.info(f"[UnifiedFlow] Mapped to legacy intent: {intent} for {tool_name}")

                # Add both legacy and new fields to research_context
                tool_request["research_context"]["intent"] = intent
                tool_request["research_context"]["intent_metadata"] = intent_metadata
                tool_request["research_context"]["user_purpose"] = user_purpose
                tool_request["research_context"]["action_needed"] = action_needed
                tool_request["research_context"]["data_requirements"] = data_requirements
                tool_request["research_context"]["prior_context"] = prior_context

                # Extract topic from §1 (Gathered Context) and pass to research_context
                # This helps _build_smart_shopping_queries understand what "vendors" refers to
                section1 = context_doc.get_section(1) or ""
                topic_match = re.search(r'\*\*Topic:\*\*\s*(.+?)(?:\n|$)', section1)
                if topic_match:
                    topic = topic_match.group(1).strip()
                    tool_request["research_context"]["topic"] = topic
                    logger.info(f"[UnifiedFlow] Adding topic='{topic}' to research_context")

                # Extract user preferences from §1 for additional context
                prefs_match = re.search(r'### User Preferences\n([\s\S]*?)(?=\n###|\n---|\Z)', section1)
                if prefs_match:
                    prefs_text = prefs_match.group(1).strip()
                    tool_request["research_context"]["user_preferences"] = prefs_text
                    logger.info(f"[UnifiedFlow] Adding user_preferences to research_context")

                # Extract prior turn context from §1 for dynamic query building
                # This enables SearchTermBuilder to use conversation context
                prior_turn_match = re.search(r'### Prior Turn Context\n([\s\S]*?)(?=\n###|\n---|\Z)', section1)
                if prior_turn_match:
                    prior_turn_text = prior_turn_match.group(1).strip()
                    # Only include if it has meaningful content (not just "no prior context")
                    if prior_turn_text and len(prior_turn_text) > 20 and "no prior" not in prior_turn_text.lower():
                        tool_request["research_context"]["prior_turn_context"] = prior_turn_text[:500]
                        logger.info(f"[UnifiedFlow] Adding prior_turn_context to research_context ({len(prior_turn_text)} chars)")

                # Pass the original user query (for LLM context discipline)
                tool_request["research_context"]["user_query"] = context_doc.query

                # Pass content_reference if we're looking for specific content (read from §0)
                # This enables site-specific search when we have site + title but no URL
                content_ref = context_doc.get_content_reference()
                if content_ref:
                    tool_request["research_context"]["content_reference"] = {
                        "title": content_ref.get("title", ""),
                        "content_type": content_ref.get("content_type", ""),
                        "site": content_ref.get("site", ""),
                        "source_url": content_ref.get("source_url", ""),
                        "has_visit_record": content_ref.get("has_visit_record", False)
                    }
                    logger.info(
                        f"[UnifiedFlow] Adding content_reference to research: "
                        f"title='{content_ref.get('title', '')[:40]}...', site={content_ref.get('site')}, "
                        f"source_url={content_ref.get('source_url')}"
                    )

                # Prior vendors are discovered by the research orchestrator through:
                # 1. Search results (DDG/Google returns vendor URLs)
                # 2. Research index (stores vendor data from previous research)
                # 3. Vendor registry (known vendor catalog)
                #
                # We do NOT extract vendors from prose text with regex - that approach
                # matched garbage like "Not" from "Retailers: Not specified."

                # DEBUG: Log the full research_context being sent
                logger.info(
                    f"[UnifiedFlow] Research context for {tool_name}: "
                    f"intent={tool_request['research_context'].get('intent')}, "
                    f"topic={tool_request['research_context'].get('topic')}, "
                    f"target_url={tool_request['research_context'].get('intent_metadata', {}).get('target_url')}"
                )

            logger.info(f"[UnifiedFlow] Tool request: {tool_name} - query={tool_request.get('query', '')[:50]}...")

            # === Handle memory.* tools locally (Tier 2 implementation) ===
            # Memory tools run in-process without going through orchestrator
            if tool_name.startswith("memory."):
                tool_result = await self._execute_memory_tool(tool_name, tool_request, context_doc)
                claims = self._extract_claims_from_result(tool_name, tool_result, config, skip_urls=skip_urls)
                return {
                    "tool": tool_name,
                    "status": "success",
                    "description": f"Executed {tool_name}",
                    "raw_result": tool_result,
                    "claims": claims,
                    "resolved_query": tool_request.get("query", context_doc.query)
                }

            # === Handle skill.* tools locally (Self-extension capability) ===
            # Skill tools run in-process for generating new skills
            if tool_name.startswith("skill."):
                tool_result = await self._execute_skill_tool(tool_name, tool_request, context_doc)
                claims = self._extract_claims_from_result(tool_name, tool_result, config, skip_urls=skip_urls)
                return {
                    "tool": tool_name,
                    "status": "success",
                    "description": f"Executed {tool_name}",
                    "raw_result": tool_result,
                    "claims": claims,
                    "resolved_query": tool_request.get("query", context_doc.query)
                }

            # Call orchestrator - each tool has its own endpoint
            orch_url = os.environ.get("ORCH_URL", "http://127.0.0.1:8090")
            tool_endpoint = f"{orch_url}/{tool_name}"

            # Use RESEARCH_TIMEOUT for research tools, otherwise MODEL_TIMEOUT
            if "research" in tool_name:
                timeout = float(os.environ.get("RESEARCH_TIMEOUT", 3600))
            else:
                timeout = float(os.environ.get("MODEL_TIMEOUT", 1800))

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    tool_endpoint,
                    json=tool_request
                )
                response.raise_for_status()
                tool_result = response.json()

            # Emit tool_result event for bash tools (for terminal display)
            if tool_name.startswith("bash"):
                trace_id = getattr(context_doc, "trace_id", None)
                if trace_id:
                    await emit_thinking_event(ThinkingEvent(
                        trace_id=trace_id,
                        stage="tool_result",
                        status="completed",
                        confidence=1.0 if tool_result.get("exit_code", 0) == 0 else 0.5,
                        duration_ms=int(tool_result.get("elapsed_seconds", 0) * 1000),
                        details={
                            "tool": tool_name,
                            "command": tool_result.get("command", config.get("command", "")),
                            "stdout": tool_result.get("stdout", ""),
                            "stderr": tool_result.get("stderr", ""),
                            "exit_code": tool_result.get("exit_code", 0),
                            "raw_result": tool_result
                        },
                        reasoning=f"Bash command executed",
                        timestamp=time.time()
                    ))
                    logger.info(f"[UnifiedFlow] Emitted tool_result event for {tool_name}")

            # Extract claims from result (filter out failed URLs from retry)
            claims = self._extract_claims_from_result(tool_name, tool_result, config, skip_urls=skip_urls)

            return {
                "tool": tool_name,
                "status": "success",
                "description": f"Executed {tool_name}",
                "raw_result": tool_result,
                "claims": claims,
                "resolved_query": tool_request.get("query", context_doc.query)
            }

        except httpx.TimeoutException as e:
            logger.error(f"[UnifiedFlow] Tool timeout ({tool_name}): {type(e).__name__}")
            raise RuntimeError(f"Tool '{tool_name}' timed out after {timeout}s") from e
        except httpx.HTTPStatusError as e:
            logger.error(f"[UnifiedFlow] Tool HTTP error ({tool_name}): {e.response.status_code}")
            raise RuntimeError(f"Tool '{tool_name}' returned HTTP {e.response.status_code}") from e
        except Exception as e:
            logger.error(f"[UnifiedFlow] Tool execution failed ({tool_name}): {type(e).__name__}: {e}")
            raise RuntimeError(f"Tool '{tool_name}' execution failed: {type(e).__name__}: {e}") from e

    def _extract_claims_from_result(
        self,
        tool_name: str,
        result: Dict[str, Any],
        config: Dict[str, Any],
        skip_urls: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Extract claims from tool result, filtering out failed URLs from retry context."""
        claims = []
        skip_urls = skip_urls or []

        if tool_name == "internet.research":
            # Extract from research findings
            findings = result.get("findings", [])
            logger.info(f"[UnifiedFlow] Claim extraction: {len(findings)} findings, keys={list(findings[0].keys()) if findings else 'none'}")
            skipped_count = 0
            for finding in findings[:10]:  # Limit to 10
                # Skip findings with URLs that failed in previous retry attempts
                finding_url = finding.get("url", "")
                if finding_url and any(skip_url in finding_url or finding_url in skip_url for skip_url in skip_urls):
                    logger.info(f"[UnifiedFlow] Skipping finding with failed URL: {finding_url[:80]}...")
                    skipped_count += 1
                    continue
                # Build claim content from available fields
                # Product findings have: name, price, vendor
                # Article findings have: summary, title
                # Phase 1 intelligence findings have: statement
                content = finding.get("summary") or finding.get("title") or finding.get("statement") or ""
                if not content and finding.get("name"):
                    # Product finding - build descriptive content
                    name = finding.get("name", "")
                    price = finding.get("price", "")
                    vendor = finding.get("vendor", "")
                    parts = [name]
                    if price:
                        # Format price with $ if it's a number
                        if isinstance(price, (int, float)):
                            parts.append(f"- ${price}")
                        elif str(price).replace('.', '').replace(',', '').isdigit():
                            parts.append(f"- ${price}")
                        else:
                            parts.append(f"- {price}")  # Already formatted or N/A
                    if vendor:
                        parts.append(f"at {vendor}")
                    content = " ".join(parts)

                claims.append({
                    # Use higher limit for list content (topics, threads, items)
                    "content": content[:1000] if content else "",
                    "confidence": 0.8,
                    "source": finding.get("url", "internet.research"),
                    "ttl_hours": 6
                })

            # Extract from answer if present
            answer = result.get("answer", "")
            if answer:
                claims.append({
                    "content": answer[:300],
                    "confidence": 0.85,
                    "source": "internet.research/synthesis",
                    "ttl_hours": 6
                })

        elif tool_name == "memory.search":
            # Extract claims from memory search results
            results_list = result.get("results", [])
            for item in results_list:
                # Each result has: source, doc_id, title, snippet, score, content_type
                content = item.get("snippet") or item.get("title", "")
                if content:
                    claims.append({
                        "content": content[:1000],
                        "confidence": min(0.95, item.get("score", 0.7) + 0.2),
                        "source": f"memory/{item.get('source', 'unknown')}",
                        "ttl_hours": 24
                    })

        elif tool_name == "memory.retrieve":
            # Extract claim from retrieved document
            doc_content = result.get("content", "")
            if doc_content:
                claims.append({
                    "content": doc_content[:2000],
                    "confidence": 0.95,
                    "source": f"memory/{result.get('doc_path', 'document')}",
                    "ttl_hours": 24
                })

        elif tool_name == "memory.save":
            # No claims to extract from save operation, just confirmation
            if result.get("status") == "saved":
                claims.append({
                    "content": f"Saved: {result.get('doc_id', 'document')}",
                    "confidence": 1.0,
                    "source": "memory/save",
                    "ttl_hours": 168  # 1 week
                })

        elif tool_name == "memory.recall":
            # Legacy support for memory.recall
            items = result.get("items", [])
            for item in items:
                claims.append({
                    "content": item.get("content", str(item))[:1000],
                    "confidence": 0.95,
                    "source": "memory",
                    "ttl_hours": 24
                })

        elif tool_name == "skill.generator":
            # Claims from skill generation
            if result.get("status") == "success":
                skill_name = result.get("skill_name", "unknown")
                claims.append({
                    "content": f"Generated skill: {skill_name} at {result.get('skill_path', '')}",
                    "confidence": 1.0,
                    "source": "skill/generator",
                    "ttl_hours": 168  # 1 week - skills are persistent
                })
            elif result.get("status") == "error":
                claims.append({
                    "content": f"Skill generation failed: {result.get('error', 'unknown')}",
                    "confidence": 1.0,
                    "source": "skill/generator",
                    "ttl_hours": 1
                })

        if tool_name == "internet.research":
            logger.info(f"[UnifiedFlow] Extracted {len(claims)} claims from internet.research")
        return claims

    async def _execute_memory_tool(
        self,
        tool_name: str,
        tool_request: Dict[str, Any],
        context_doc: ContextDocument
    ) -> Dict[str, Any]:
        """
        Execute memory.* tools locally using UnifiedMemoryMCP.

        Tier 2 implementation - provides unified access to:
        - memory.search: Search research, turns, preferences, site knowledge
        - memory.save: Save new knowledge/facts
        - memory.retrieve: Retrieve specific documents

        Args:
            tool_name: memory.search, memory.save, or memory.retrieve
            tool_request: Tool parameters
            context_doc: Current context document

        Returns:
            Tool result dict
        """
        memory_mcp = get_memory_mcp(context_doc.session_id)

        try:
            if tool_name == "memory.search":
                # Build search request from tool args
                request = MemorySearchRequest(
                    query=tool_request.get("query", context_doc.query),
                    topic_filter=tool_request.get("topic_filter"),
                    content_types=tool_request.get("content_types"),
                    scope=tool_request.get("scope"),  # None = search all scopes
                    session_id=tool_request.get("session_id", context_doc.session_id),
                    min_quality=tool_request.get("min_quality", 0.3),
                    k=tool_request.get("k", 10)
                )
                results = await memory_mcp.search(request)
                logger.info(f"[UnifiedFlow] memory.search found {len(results)} results")

                # Enrich results with age_hours for Planner decision-making
                enriched_results = []
                now = datetime.now()
                for r in results:
                    result_dict = r.to_dict()
                    # Calculate age in hours from created_at
                    try:
                        created = datetime.fromisoformat(r.created_at.replace('Z', '+00:00'))
                        if created.tzinfo:
                            created = created.replace(tzinfo=None)
                        age_hours = (now - created).total_seconds() / 3600
                        result_dict['age_hours'] = round(age_hours, 1)
                        result_dict['freshness'] = 'fresh' if age_hours < 24 else ('stale' if age_hours > 48 else 'aging')
                    except (ValueError, TypeError):
                        result_dict['age_hours'] = None
                        result_dict['freshness'] = 'unknown'
                    enriched_results.append(result_dict)

                return {
                    "status": "success",
                    "results": enriched_results,
                    "count": len(results)
                }

            elif tool_name == "memory.save":
                # Factor 6/7: Pre-execution approval for high-stakes tools
                denial = await self._check_tool_approval(
                    tool_name=tool_name,
                    tool_args=tool_request,
                    session_id=context_doc.session_id
                )
                if denial:
                    return denial

                # Build save request from tool args
                request = MemorySaveRequest(
                    title=tool_request.get("title", "Untitled"),
                    content=tool_request.get("content", ""),
                    doc_type=tool_request.get("doc_type", "note"),
                    tags=tool_request.get("tags", []),
                    scope=tool_request.get("scope", "new"),  # New data starts at 'new' scope per MEMORY_ARCHITECTURE.md
                    session_id=tool_request.get("session_id", context_doc.session_id)
                )
                result = await memory_mcp.save(request)
                logger.info(f"[UnifiedFlow] memory.save: {result.get('status')}")
                return result

            elif tool_name == "memory.retrieve":
                # Retrieve by path or ID
                result = await memory_mcp.retrieve(
                    doc_path=tool_request.get("doc_path"),
                    doc_id=tool_request.get("doc_id")
                )
                logger.info(f"[UnifiedFlow] memory.retrieve: {result.get('status')}")
                return result

            else:
                logger.warning(f"[UnifiedFlow] Unknown memory tool: {tool_name}")
                return {
                    "status": "error",
                    "message": f"Unknown memory tool: {tool_name}"
                }

        except Exception as e:
            logger.error(f"[UnifiedFlow] Memory tool error ({tool_name}): {e}")
            return {
                "status": "error",
                "message": str(e)
            }

    async def _synthesize_skill_instructions(
        self,
        name: str,
        description: str,
        source: str,
        context_doc: ContextDocument
    ) -> str:
        """
        Synthesize skill instructions from research context.

        When Planner calls skill.generator without instructions, this method
        uses the LLM to generate proper SKILL.md instructions from §4 research.

        Args:
            name: Skill name
            description: Skill description
            source: Source URL/concept
            context_doc: Context document with §4 research results

        Returns:
            Generated instructions markdown
        """
        # Get research context from §4
        section4 = context_doc.get_section(4) or ""

        prompt = f"""Generate SKILL.md instructions for a Pandora skill.

Skill Name: {name}
Description: {description}
Source: {source}

Research Context (from tool execution):
{section4[:4000]}

Generate complete instructions that include:
1. ## When to Use - triggers and appropriate contexts
2. ## Syntax/Usage - how to invoke and use the skill
3. ## Examples - 2-3 concrete examples
4. ## Notes - limitations, best practices

Output ONLY the instructions markdown (no JSON, no preamble).
Keep it concise but complete (300-800 words)."""

        try:
            response = await self.llm_client.call(
                prompt=prompt,
                role="guide",
                max_tokens=1500,
                temperature=0.5
            )

            # Clean up response
            instructions = response.strip()

            # Ensure we have valid instructions
            if len(instructions) < 100:
                logger.warning(f"[UnifiedFlow] Generated instructions too short ({len(instructions)} chars), using fallback")
                instructions = f"""## When to Use
Use this skill when users ask about {name} or related topics.

## Description
{description}

## Source
Derived from: {source}

## Notes
This skill was auto-generated. Review and customize as needed."""

            return instructions

        except Exception as e:
            logger.error(f"[UnifiedFlow] Failed to synthesize instructions: {e}")
            # Return minimal fallback instructions
            return f"""## When to Use
Use this skill for {name} related tasks.

## Description
{description}

## Source
{source}"""

    async def _execute_skill_tool(
        self,
        tool_name: str,
        tool_request: Dict[str, Any],
        context_doc: ContextDocument
    ) -> Dict[str, Any]:
        """
        Execute skill.* tools locally using SkillGeneratorMCP.

        Self-extension capability - allows Pandora to build new skills:
        - skill.generator: Generate new skills from specifications

        Args:
            tool_name: skill.generator (currently the only skill tool)
            tool_request: Tool parameters including name, description, instructions
            context_doc: Current context document

        Returns:
            Tool result dict with status and details
        """
        try:
            if tool_name == "skill.generator":
                from apps.services.orchestrator.skill_generator_mcp import get_skill_generator_mcp

                skill_gen = get_skill_generator_mcp(session_id=context_doc.session_id)

                # Extract parameters from tool request
                name = tool_request.get("name", "")
                description = tool_request.get("description", "")
                instructions = tool_request.get("instructions", "")
                source = tool_request.get("source", "")

                # If instructions not provided, synthesize from research context
                if not instructions or len(instructions) < 50:
                    instructions = await self._synthesize_skill_instructions(
                        name=name,
                        description=description,
                        source=source,
                        context_doc=context_doc
                    )
                    logger.info(f"[UnifiedFlow] Synthesized instructions for {name}: {len(instructions)} chars")

                result = await skill_gen.generate_skill(
                    name=name,
                    description=description,
                    instructions=instructions,
                    author=tool_request.get("author", "pandora-generated"),
                    version=tool_request.get("version", "1.0"),
                    source=source,
                    license=tool_request.get("license", ""),
                    compatibility=tool_request.get("compatibility", ""),
                    allowed_tools=tool_request.get("allowed_tools"),
                    scripts=tool_request.get("scripts"),
                    references=tool_request.get("references"),
                )

                logger.info(f"[UnifiedFlow] skill.generator: {result.status} - {result.skill_name}")
                return result.to_dict()

            elif tool_name == "skill.validate":
                from apps.services.orchestrator.skill_generator_mcp import get_skill_generator_mcp

                skill_gen = get_skill_generator_mcp(session_id=context_doc.session_id)
                result = await skill_gen.validate_skill(
                    skill_path=tool_request.get("skill_path", "")
                )
                logger.info(f"[UnifiedFlow] skill.validate: valid={result.get('valid')}")
                return result

            elif tool_name == "skill.delete":
                from apps.services.orchestrator.skill_generator_mcp import get_skill_generator_mcp

                skill_gen = get_skill_generator_mcp(session_id=context_doc.session_id)
                result = await skill_gen.delete_skill(
                    name=tool_request.get("name", "")
                )
                logger.info(f"[UnifiedFlow] skill.delete: {result.get('status')}")
                return result

            elif tool_name == "skill.list":
                from libs.gateway.skill_registry import get_skill_registry

                registry = get_skill_registry()
                skills = list(registry.skills.values())
                return {
                    "status": "success",
                    "skills": [
                        {
                            "name": s.name,
                            "description": s.description,
                            "path": str(s.path),
                            "tier": s.tier,
                        }
                        for s in skills
                    ],
                    "count": len(skills)
                }

            else:
                logger.warning(f"[UnifiedFlow] Unknown skill tool: {tool_name}")
                return {
                    "status": "error",
                    "message": f"Unknown skill tool: {tool_name}"
                }

        except Exception as e:
            logger.error(f"[UnifiedFlow] Skill tool error ({tool_name}): {e}")
            return {
                "status": "error",
                "message": str(e)
            }

    async def _check_tool_approval(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Check if tool requires approval and wait for it.

        Implements Factor 6/7 (Pause/Resume + Human Contact) from 12-Factor Agents.
        This method can be called before any tool execution to check if approval
        is required and handle the approval flow.

        Args:
            tool_name: Name of the tool to execute
            tool_args: Arguments for the tool
            session_id: Session identifier

        Returns:
            None if approved or no approval needed,
            Dict with error details if denied
        """
        if not APPROVAL_SYSTEM_ENABLED:
            return None

        approval_manager = get_tool_approval_manager()
        if not approval_manager.requires_approval(tool_name):
            return None

        logger.info(f"[UnifiedFlow] Tool '{tool_name}' requires pre-execution approval")

        # Request approval
        approval_request = await approval_manager.request_approval(
            tool_name=tool_name,
            tool_args=tool_args,
            session_id=session_id,
        )

        # Get timeout from config
        config = approval_manager.get_tool_config(tool_name)
        timeout = config.get("timeout", 60) if config else 60

        # Wait for user response
        approved = await approval_request.wait_for_approval(timeout=timeout)

        if not approved:
            reason = approval_request.deny_reason or "Timeout or user denial"
            logger.warning(f"[UnifiedFlow] Tool '{tool_name}' execution denied: {reason}")
            return {
                "status": "denied",
                "error": f"User denied execution of {tool_name}",
                "reason": reason,
                "tool": tool_name,
            }

        logger.info(f"[UnifiedFlow] Tool '{tool_name}' execution approved")
        return None

    def _summarize_tool_results(self, tool_results: List[Dict[str, Any]]) -> str:
        """
        Summarize tool results with detailed findings.

        For internet.research, includes:
        - Phase 1: Intelligence gathered (forums, recommendations, key criteria)
        - Phase 2: Products found (names, prices, vendors)

        For failed tools, uses ErrorCompactor to provide:
        - Error classification
        - Recovery suggestions
        - Retryability indication
        """
        summaries = []
        error_compactor = get_error_compactor()

        for result in tool_results:
            status = result.get("status", "unknown")
            tool = result.get("tool", "unknown")
            claims_count = len(result.get("claims", []))
            summaries.append(f"- {tool}: {status} ({claims_count} claims)")

            # Handle failed tools with error compaction (Factor 9: Compact Errors)
            if status in ("error", "failed", "timeout"):
                compacted = error_compactor.compact_from_result(result, tool)
                if compacted:
                    summaries.append(compacted.to_context_format())
                continue  # Skip success-only processing for failed tools

            # For internet.research, add detailed breakdown
            if tool == "internet.research" and status == "success":
                raw_result = result.get("raw_result", {})

                # Phase 1 Intelligence
                intelligence = raw_result.get("intelligence", {})
                if intelligence:
                    key_criteria = intelligence.get("key_criteria", [])
                    credible_sources = intelligence.get("credible_sources", [])
                    recommendations = intelligence.get("key_recommendations", [])

                    if key_criteria or credible_sources or recommendations:
                        summaries.append("  **Phase 1 Intelligence:**")
                        if key_criteria:
                            summaries.append(f"  - Key criteria: {', '.join(key_criteria[:5])}")
                        if credible_sources:
                            sources_display = [s.get('name', s.get('url', 'unknown'))[:30] for s in credible_sources[:3]]
                            summaries.append(f"  - Sources: {', '.join(sources_display)}")
                        if recommendations:
                            summaries.append(f"  - Recommendations: {', '.join(recommendations[:3])}")

                # Phase 2 Products
                findings = raw_result.get("findings", [])
                product_findings = [f for f in findings if f.get("type") == "product" or f.get("price")]

                if product_findings:
                    summaries.append(f"  **Phase 2 Products ({len(product_findings)} found):**")
                    for pf in product_findings[:5]:  # Show up to 5 products
                        name = pf.get("name", pf.get("title", "Unknown"))[:40]
                        price = pf.get("price", "N/A")
                        vendor = pf.get("vendor", pf.get("source", ""))[:20]
                        url = pf.get("url", "")
                        if url and vendor:
                            summaries.append(f"  - {name} | {price} | {vendor} | {url}")
                        elif vendor:
                            summaries.append(f"  - {name} | {price} | {vendor}")
                        else:
                            summaries.append(f"  - {name} | {price}")

                    if len(product_findings) > 5:
                        summaries.append(f"  - ... and {len(product_findings) - 5} more products")

                # General/Navigational findings (non-product research results)
                # IMPORTANT: Show the actual content so Synthesis can use it directly
                general_findings = [f for f in findings if f.get("type") in ("source_summary", "user_insight", None) and not f.get("price")]
                if general_findings and not product_findings:
                    # Only show if no products (to avoid duplication for commerce queries)
                    summaries.append(f"  **Research Findings ({len(general_findings)} items):**")
                    for gf in general_findings[:5]:  # Show up to 5 findings
                        statement = gf.get("statement", gf.get("content", ""))
                        source = gf.get("source", "")[:50]
                        if statement:
                            # For list-style content (topics, items), preserve structure
                            # Limit to 800 chars to fit in context while showing useful content
                            if len(statement) > 800:
                                preview = statement[:800] + "..."
                            else:
                                preview = statement
                            # Format as indented block for readability
                            preview_lines = preview.split("\n")
                            if len(preview_lines) > 1:
                                # Multi-line content - indent each line
                                summaries.append(f"  - Source: {source}")
                                for line in preview_lines[:20]:  # Max 20 lines per finding
                                    if line.strip():
                                        summaries.append(f"    {line.strip()}")
                                if len(preview_lines) > 20:
                                    summaries.append(f"    ... and {len(preview_lines) - 20} more lines")
                            else:
                                # Single line content
                                summaries.append(f"  - {preview}")
                    if len(general_findings) > 5:
                        summaries.append(f"  - ... and {len(general_findings) - 5} more findings")
                    # Signal that we have content for the query
                    summaries.append("  **Status: Content extracted - task may be DONE**")

                # Strategy used
                strategy = raw_result.get("strategy", "unknown")
                if strategy:
                    summaries.append(f"  Strategy: {strategy}")

        return "\n".join(summaries) if summaries else "No tool results"

    async def _summarize_claims_batch(
        self,
        claims: List[Dict[str, Any]],
        max_chars_per_claim: int = 100
    ) -> List[str]:
        """
        Summarize all claims using LLM in a single batch call.

        MUST PRESERVE: price, vendor name, product name, key specs.
        Uses pattern extraction ONLY as fallback if LLM fails.
        """
        if not claims:
            return []

        # Build batch prompt for LLM
        claims_text = "\n".join([
            f"{i+1}. {c.get('content', '')[:300]}"
            for i, c in enumerate(claims)
        ])

        # Load prompt from recipe system
        try:
            recipe = load_recipe("memory/claim_summarizer")
            prompt_template = recipe.get_prompt()
            prompt = prompt_template.format(
                max_chars=max_chars_per_claim,
                claims_text=claims_text
            )
        except Exception as e:
            logger.warning(f"[UnifiedFlow] Failed to load claim_summarizer recipe: {e}, using fallback")
            # Fallback if recipe not found
            prompt = f"""Summarize each claim to ~{max_chars_per_claim} characters.

CRITICAL - Preserve KEY FACTS from each claim:
- If there's a price, keep it EXACT (e.g., $794.99)
- If there's a vendor/source, include it
- If there's a measurement/spec (height, size, material), keep it
- If it's factual info (how-to, specifications), preserve the key details
- Do NOT add information that isn't in the original claim

Format: One summary per line, numbered 1-N. No extra text.

CLAIMS TO SUMMARIZE:
{claims_text}

SUMMARIES:"""

        try:
            response = await self.llm_client.call(
                prompt=prompt,
                role="guide",
                max_tokens=len(claims) * 50,  # ~50 tokens per summary
                temperature=0.2
            )

            # Parse numbered summaries
            summaries = []
            for line in response.strip().split('\n'):
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith('-')):
                    # Remove numbering: "1. Summary" -> "Summary" or "- Summary" -> "Summary"
                    summary = re.sub(r'^[\d]+\.\s*', '', line)
                    summary = re.sub(r'^-\s*', '', summary).strip()
                    if summary:
                        summaries.append(summary)

            # Validate we got all summaries
            if len(summaries) >= len(claims):
                logger.info(f"[UnifiedFlow] LLM summarized {len(claims)} claims successfully")
                return summaries[:len(claims)]

            logger.warning(f"[UnifiedFlow] LLM returned {len(summaries)} summaries for {len(claims)} claims, using fallback")

        except Exception as e:
            logger.error(f"[UnifiedFlow] Claim summarization LLM call failed: {e}")

        # Fallback: pattern extraction if LLM fails
        logger.info(f"[UnifiedFlow] Using pattern extraction fallback for {len(claims)} claims")
        return [self._extract_claim_key_facts(c.get('content', ''), max_chars_per_claim) for c in claims]

    def _extract_claim_key_facts(self, content: str, max_chars: int = 100) -> str:
        """FALLBACK ONLY: Extract key facts using regex if LLM fails."""
        if len(content) <= max_chars:
            return content

        # Extract price
        price_match = re.search(r'\$[\d,]+(?:\.\d{2})?', content)
        price = price_match.group() if price_match else ""

        # Extract vendor
        vendor_match = re.search(r'(?:at|from)\s+([a-zA-Z0-9.-]+\.(?:com|org|net))', content, re.I)
        vendor = f"at {vendor_match.group(1)}" if vendor_match else ""

        # Get product name
        if " - $" in content:
            product = content.split(" - $")[0][:60]
        else:
            product = content[:60]

        parts = [p for p in [product.strip(), price, vendor] if p]
        result = " - ".join(parts) if parts else content[:max_chars]
        return result[:max_chars]

    def _extract_resolved_query_from_plan(self, context_doc: ContextDocument) -> Optional[str]:
        """
        Extract resolved query from Planner's task description in §3.

        When user says "can you find any others?", the Planner creates a task like
        "Search internet for additional gaming laptops with RTX 4060". This method
        extracts that resolved query to use for the research tool.

        Returns:
            Resolved query string, or None if not found
        """
        try:
            # Check if §3 exists
            if not context_doc.has_section(3):
                return None

            section_content = context_doc.get_section(3)
            if not section_content:
                return None

            # Look for task descriptions that indicate search operations
            # Pattern: "Search internet for X" or just the Subtasks line

            # Try to find search-related patterns
            # IMPORTANT: Use word boundary \b to avoid matching "internet.research"
            # Use [ \t]+ instead of \s+ to exclude newlines (which caused false matches)
            # Patterns matched:
            # - "Search internet for X"
            # - "Search again for X"
            # - "Search for X"
            # - "Research X"
            # - "Find X"
            search_match = re.search(
                r'(?:Search(?:\s+(?:internet|again))?\s+for|\bResearch|\bFind)[ \t]+(.+?)(?:\n|$)',
                section_content,
                re.IGNORECASE
            )
            if search_match:
                query = search_match.group(1).strip()
                # Clean up trailing punctuation
                query = query.rstrip('.')
                if len(query) > 10:  # Must be meaningful
                    return query

            # Try to find resolved query in Goals section
            # Format: "- [status] Search again for Syrian hamster vendors"
            goals_match = re.search(
                r'\[(?:achieved|in_progress|pending)\]\s*(.+?)(?:\n|$)',
                section_content,
                re.IGNORECASE
            )
            if goals_match:
                goal_text = goals_match.group(1).strip()
                # Extract the actual query from the goal
                # Remove "Search ... for" prefix to get the subject
                subject_match = re.search(
                    r'(?:Search(?:\s+\w+)?\s+for|Find|Research)\s+(.+)',
                    goal_text,
                    re.IGNORECASE
                )
                if subject_match:
                    subject = subject_match.group(1).strip().rstrip('.')
                    if len(subject) > 5:
                        return subject

            # Try to find task description in Subtasks section
            subtask_match = re.search(
                r'(?:\d+\.\s*)(.+?)(?:\n|$)',
                section_content
            )
            if subtask_match:
                task = subtask_match.group(1).strip()
                # Extract actionable query from task description
                if any(kw in task.lower() for kw in ['search', 'find', 'research', 'additional']):
                    # Remove common prefixes
                    for prefix in ['Execute required tools for ', 'Execute ', 'Generate response from ']:
                        if task.startswith(prefix):
                            task = task[len(prefix):]
                    if len(task) > 10:
                        return task

            return None

        except Exception as e:
            logger.warning(f"[UnifiedFlow] Failed to extract resolved query from plan: {e}")
            return None

    def _build_ticket_content(self, context_doc: ContextDocument, plan: Dict[str, Any]) -> str:
        """Build ticket.md content."""
        return f"""# Task Ticket

**Turn:** {context_doc.turn_number}
**Session:** {context_doc.session_id}

## Goal
{context_doc.query}

## Plan
{json.dumps(plan, indent=2)}

## Status
Complete
"""

    def _build_toolresults_content(
        self,
        context_doc: ContextDocument,
        tool_results: List[Dict[str, Any]]
    ) -> str:
        """Build toolresults.md content."""
        return f"""# Tool Results

**Turn:** {context_doc.turn_number}

## Execution Log
{json.dumps(tool_results, indent=2, default=str)}
"""

    async def _write_research_documents(
        self,
        tool_results: List[Dict[str, Any]],
        context_doc: ContextDocument
    ):
        """Write research documents for internet.research results."""
        research_writer = ResearchDocumentWriter(turns_dir=self.turns_dir)
        research_index = get_research_index_db()

        for result in tool_results:
            if result.get("tool") != "internet.research":
                continue
            if result.get("status") != "success":
                continue

            raw_result = result.get("raw_result", {})
            if not raw_result.get("findings"):
                continue

            try:
                resolved_query = result.get("resolved_query", context_doc.query)

                doc = research_writer.create_from_tool_results(
                    turn_number=context_doc.turn_number,
                    session_id=context_doc.session_id,
                    query=resolved_query,
                    tool_results=raw_result,
                    intent="transactional"
                )

                turn_dir = self.turns_dir / f"turn_{context_doc.turn_number:06d}"
                research_writer.write(doc, turn_dir)

                research_index.index_research(
                    id=doc.id,
                    turn_number=doc.turn_number,
                    session_id=doc.session_id,
                    primary_topic=doc.topic.primary_topic,
                    keywords=doc.topic.keywords,
                    intent=doc.topic.intent,
                    completeness=doc.quality.completeness,
                    source_quality=doc.quality.source_quality,
                    overall_quality=doc.quality.overall,
                    confidence_initial=doc.confidence.initial,
                    decay_rate=doc.confidence.decay_rate,
                    created_at=doc.created_at.timestamp(),
                    expires_at=doc.expires_at.timestamp() if doc.expires_at else None,
                    scope=doc.scope,
                    doc_path=str(turn_dir / "research.md"),
                    content_types=doc.topic.content_types
                )

                logger.info(f"[UnifiedFlow] Created research document: {doc.id}")

            except Exception as e:
                logger.error(f"[UnifiedFlow] Failed to write research document: {e}")
                raise RuntimeError(f"Failed to write research document: {e}") from e

    async def _update_knowledge_graph(
        self,
        tool_results: List[Dict[str, Any]],
        context_doc: ContextDocument
    ):
        """
        Update knowledge graph with entities extracted from research results.

        Extracts vendors, products, sites, and other entities from internet.research
        results and stores them in the knowledge graph for compounding context.

        Architecture Reference:
            architecture/Implementation/KNOWLEDGE_GRAPH_AND_UI_PLAN.md#Part 3: Compounding Context
        """
        try:
            from libs.gateway.entity_updater import get_entity_updater
        except ImportError:
            logger.debug("[UnifiedFlow] EntityUpdater not available, skipping knowledge graph update")
            return

        try:
            updater = get_entity_updater()
            if updater.kg is None:
                logger.debug("[UnifiedFlow] KnowledgeGraphDB not initialized, skipping entity extraction")
                return

            for result in tool_results:
                if result.get("tool") != "internet.research":
                    continue
                if result.get("status") != "success":
                    continue

                raw_result = result.get("raw_result", {})
                if not raw_result:
                    continue

                # Process research results through entity updater
                updater.process_research_results(raw_result, context_doc.turn_number)
                logger.info(f"[UnifiedFlow] Updated knowledge graph from research (turn {context_doc.turn_number})")

        except Exception as e:
            # Non-fatal: don't break the flow if entity extraction fails
            logger.warning(f"[UnifiedFlow] Knowledge graph update failed (non-fatal): {e}")

    async def _revise_synthesis(
        self,
        context_doc: ContextDocument,
        turn_dir: TurnDirectory,
        original_response: str,
        revision_hints: str,
        mode: str
    ) -> str:
        """Revise synthesis based on validation hints."""
        logger.info(f"[UnifiedFlow] Revising synthesis with hints: {revision_hints}")

        # Build revision prompt from recipe system
        try:
            recipe = load_recipe("pipeline/response_revision")
            prompt_template = recipe.get_prompt()
            revision_prompt = prompt_template.format(
                original_response=original_response,
                revision_hints=revision_hints
            )
        except Exception as e:
            logger.warning(f"[UnifiedFlow] Failed to load response_revision recipe: {e}, using fallback")
            # Fallback if recipe not found
            revision_prompt = f"""Please revise the following response based on the validation feedback.

ORIGINAL RESPONSE:
{original_response}

VALIDATION FEEDBACK:
{revision_hints}

INSTRUCTIONS:
- Address the issues identified in the validation feedback
- Keep the response focused on answering the user's query
- Only include claims that have supporting evidence
- Remove any hallucinated or unsupported information

Please provide the revised response:"""

        try:
            revised = await self.llm_client.call(
                prompt=revision_prompt,
                role="guide",
                max_tokens=2000,
                temperature=0.5
            )
            return revised.strip()
        except Exception as e:
            logger.error(f"[UnifiedFlow] Revision failed: {e}")
            raise RuntimeError(f"Response revision failed: {e}") from e

    def _extract_clarification(self, context_doc: ContextDocument) -> str:
        """Extract clarification question from context."""
        section2 = context_doc.get_section(2)
        if section2 and "clarification" in section2.lower():
            # Try to extract the question
            lines = section2.split("\n")
            for line in lines:
                if "?" in line:
                    return line.strip()

        return "Could you please provide more details about your request?"

    async def _resolve_query_from_context(self, query: str, context_doc: ContextDocument) -> str:
        """
        DEPRECATED: Use _resolve_query_with_n1() instead.

        This function used the full gathered context which could include irrelevant
        older turns, causing the LLM to resolve pronouns incorrectly (e.g., resolving
        "some" to laptops from Turn N-2 instead of hamsters from Turn N-1).

        The new _resolve_query_with_n1() only uses the immediately preceding turn
        and runs BEFORE context gathering for correct resolution.

        Keeping this for backward compatibility but should not be called.
        """
        gathered = context_doc.get_section(1) or ""

        # Quick check: if query is explicit and long enough, skip resolution
        query_lower = query.lower()
        word_count = len(query.split())
        has_explicit_subject = any(kw in query_lower for kw in [
            'hamster', 'laptop', 'phone', 'computer', 'reef', 'aquarium',
            'fish', 'coral', 'pet', 'amazon', 'ebay', 'google', '.com', '.org'
        ])

        if word_count >= 10 and has_explicit_subject:
            logger.info(f"[UnifiedFlow] Query explicit, skipping resolution: '{query[:50]}'")
            return query

        if not gathered.strip():
            logger.info(f"[UnifiedFlow] No context, skipping resolution: '{query[:50]}'")
            return query

        # Use LLM to resolve vague references - load prompt from recipe system
        try:
            recipe = load_recipe("pipeline/reference_resolver")
            prompt_template = recipe.get_prompt()
            prompt = prompt_template.format(query=query, context=gathered[:2000])
        except Exception as e:
            logger.warning(f"[UnifiedFlow] Failed to load reference_resolver recipe: {e}, using fallback")
            # Fallback if recipe not found
            prompt = f"""Resolve any vague references in this query using the conversation context.

QUERY: {query}

CONTEXT:
{gathered[:2000]}

TASK:
- If the query contains vague words like "some", "them", "it", "those", "these", "that", "one", replace them with the specific subject from context
- If the query is a follow-up question about something mentioned in context (like "the topics", "the results", "tell me more"), prepend the subject
- If the query is already specific and complete, return it unchanged

OUTPUT:
Return ONLY the resolved query (or the original if no resolution needed). No explanation."""

        try:
            resolved = await self.llm_client.call(
                prompt=prompt,
                role="guide",
                max_tokens=200,
                temperature=0.1
            )
            resolved = resolved.strip()

            # Sanity check: if LLM returned something reasonable
            if resolved and len(resolved) > 3 and len(resolved) < len(query) * 5:
                if resolved != query:
                    logger.info(f"[UnifiedFlow] LLM resolved query: '{query}' → '{resolved}'")
                return resolved
            else:
                logger.warning(f"[UnifiedFlow] LLM returned invalid resolution: '{resolved[:100]}', using original")
                return query

        except Exception as e:
            logger.error(f"[UnifiedFlow] Query resolution LLM call failed: {e}")
            return query

    async def _resolve_query_with_n1(self, query: str, turn_number: int, session_id: str) -> str:
        """
        Resolve references using the immediately preceding turn (N-1).

        This runs BEFORE context gathering to ensure the query is explicit
        before we search for relevant context.

        ARCHITECTURAL FIX (2026-01-04): Always provides N-1 context to the LLM.
        The LLM decides if resolution is needed - no hardcoded pattern matching.

        This handles:
        - Pronouns: "it", "that", "those", "some"
        - Definite references: "the thread", "the laptop", "the product"
        - Implicit references: "tell me more", "how many pages"

        Examples:
        - "find some for sale" + N-1="Syrian hamster" → "find Syrian hamsters for sale"
        - "how many pages is the thread" + N-1="Best glass scraper" → "how many pages is the 'Best glass scraper' thread"
        - "find me laptops" + N-1="hamsters" → "find me laptops" (unchanged - already explicit)
        """
        # ARCHITECTURAL FIX (2026-01-04): Removed hardcoded pattern matching
        # Always provide N-1 context to LLM and let it decide if resolution is needed.
        # This fixes cases like "the thread" which didn't match vague pronoun patterns
        # but still needed resolution to connect to the previous discussion.

        # Load N-1 turn content
        n1_turn_number = turn_number - 1
        if n1_turn_number < 1:
            logger.debug("[UnifiedFlow] No N-1 turn available, skipping resolution")
            return query

        n1_dir = self.turns_dir / f"turn_{n1_turn_number:06d}"
        if not n1_dir.exists():
            logger.debug(f"[UnifiedFlow] N-1 turn dir not found: {n1_dir}")
            return query

        # Read N-1 context
        n1_context_path = n1_dir / "context.md"
        n1_response_path = n1_dir / "response.md"

        n1_query = ""
        n1_response = ""

        # Extract query from N-1
        if n1_context_path.exists():
            try:
                content = n1_context_path.read_text()
                if "## 0. User Query" in content:
                    query_section = content.split("## 0. User Query")[1]
                    if "---" in query_section:
                        query_section = query_section.split("---")[0]
                    n1_query = query_section.strip()[:200]
            except Exception as e:
                logger.warning(f"[UnifiedFlow] Failed to read N-1 query: {e}")

        # Extract response from N-1
        if n1_response_path.exists():
            try:
                content = n1_response_path.read_text()
                # Get the draft response section
                if "**Draft Response:**" in content:
                    response_section = content.split("**Draft Response:**")[1]
                    if "---" in response_section:
                        response_section = response_section.split("---")[0]
                    n1_response = response_section.strip()[:500]
                else:
                    n1_response = content.strip()[:500]
            except Exception as e:
                logger.warning(f"[UnifiedFlow] Failed to read N-1 response: {e}")

        if not n1_query and not n1_response:
            logger.debug("[UnifiedFlow] N-1 has no extractable content, skipping resolution")
            return query

        # Build N-1 summary
        n1_summary = ""
        if n1_query:
            n1_summary += f"User asked: {n1_query}\n"
        if n1_response:
            n1_summary += f"Response: {n1_response}"

        logger.info(f"[UnifiedFlow] N-1 Resolution: query='{query[:50]}', N-1 topic='{n1_query[:50]}...'")

        # LLM prompt - load from recipe system
        try:
            recipe = load_recipe("pipeline/reference_resolver")
            prompt_template = recipe.get_prompt()
            prompt = prompt_template.format(query=query, context=n1_summary[:800])
        except Exception as e:
            logger.warning(f"[UnifiedFlow] Failed to load reference_resolver recipe: {e}, using fallback")
            # Fallback if recipe not found
            prompt = f"""Resolve any vague references in the current query using the previous message.

CURRENT QUERY: {query}

PREVIOUS MESSAGE (what was just discussed):
{n1_summary[:800]}

TASK:
- If the query contains pronouns like "some", "it", "that", "those", "them", "these" that refer to something from the previous message, replace them with the specific subject.
- If the query is already complete and explicit (has a clear subject), return it UNCHANGED.
- If the previous message is unrelated (like "thanks" or "ok"), return the query UNCHANGED.

EXAMPLES:
- "find some for sale" + prev="Syrian hamster is favorite" → "find Syrian hamsters for sale"
- "find some laptops for sale" + prev="Syrian hamster" → "find some laptops for sale" (unchanged - already has subject)
- "how much is it" + prev="RTX 4060 costs $800" → "how much is the RTX 4060"
- "tell me more" + prev="Discussed reef tanks" → "tell me more about reef tanks"
- "thanks" + prev="anything" → "thanks" (unchanged)

OUTPUT: Return ONLY the resolved query (or original if no resolution needed). No explanation."""

        try:
            resolved = await self.llm_client.call(
                prompt=prompt,
                role="guide",
                max_tokens=200,
                temperature=0.1
            )
            resolved = resolved.strip()

            # Remove any quotes the LLM might have added
            if resolved.startswith('"') and resolved.endswith('"'):
                resolved = resolved[1:-1]
            if resolved.startswith("'") and resolved.endswith("'"):
                resolved = resolved[1:-1]

            # Sanity checks
            if not resolved or len(resolved) < 3:
                logger.warning(f"[UnifiedFlow] N-1 resolution returned empty/short, using original")
                return query

            if len(resolved) > len(query) * 5:
                logger.warning(f"[UnifiedFlow] N-1 resolution too long, using original")
                return query

            if resolved != query:
                logger.info(f"[UnifiedFlow] N-1 RESOLVED: '{query}' → '{resolved}'")
            else:
                logger.debug(f"[UnifiedFlow] N-1 resolution: query unchanged (already explicit)")

            return resolved

        except Exception as e:
            logger.error(f"[UnifiedFlow] N-1 resolution LLM call failed: {e}")
            return query

    # NOTE: _context_has_product_data method was removed (PIPELINE_FIX_PLAN.md)
    # It was only used by the COMMERCE OVERRIDE block which was also removed
