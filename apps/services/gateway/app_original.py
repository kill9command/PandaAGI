from fastapi import FastAPI, HTTPException, Header, Request, Body, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from typing import Any, Deque, Dict, List, Optional
from collections import defaultdict, deque, Counter
from pathlib import Path
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
import httpx, os, json, re, pathlib, asyncio, uuid, time, logging, datetime

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from apps.services.orchestrator import memory_manager
from apps.services.orchestrator.memory_store import get_memory_store
from apps.services.orchestrator import context_ranker
from apps.services.orchestrator.shared_state import (
    ArtifactStore,
    SessionLedger,
    ClaimRegistry,
    RawBundle,
)
from apps.services.orchestrator.shared_state.claims import ClaimRow
from apps.services.gateway.tool_catalog import ToolCatalog
from apps.services.gateway.tool_router import ToolRouter
from apps.services.gateway.plan_linter import PlanLinter
from apps.services.gateway import context_compressor
from apps.services.gateway.intent_classifier import IntentClassifier, IntentType
from apps.services.gateway import quality_integration
from apps.services.gateway.session_context import SessionContextManager
from apps.services.gateway import context_extractors
from apps.services.gateway import pronoun_resolver
from apps.services.gateway.context_summarizer import ContextSummarizer
from apps.services.gateway.unified_context import UnifiedContextManager
from apps.services.gateway.tool_circuit_breaker import ToolCircuitBreaker
from apps.services.gateway.llm_extractor import LLMExtractor, set_llm_extractor, get_llm_extractor
from apps.services.gateway.cross_session_learning import get_learning_store
from apps.services.gateway.research_ws_manager import research_ws_manager
# Import adaptive research function for direct calling (enables WebSocket event streaming)
# REMOVED: Direct import of adaptive_research (Gateway should call orchestrator via HTTP)
# Import CAPTCHA intervention functions for web-based CAPTCHA solver
from apps.services.orchestrator.captcha_intervention import (
    get_all_pending_interventions,
    get_pending_intervention,
    remove_pending_intervention
)
from apps.services.orchestrator.context_builder import (
    WorkingMemoryConfig,
)
from pydantic import ValidationError
from apps.services.orchestrator.shared_state.schema import CapsuleClaim, DistilledCapsule, CapsuleDelta
from scripts import memory_schema
from apps.services.orchestrator.meta_reflection import MetaReflectionGate, ProcessContext

# Cache system imports
from apps.services.orchestrator.shared_state.embedding_service import EMBEDDING_SERVICE
from apps.services.orchestrator.shared_state.tool_cache import TOOL_CACHE
from apps.services.orchestrator.shared_state.response_cache import RESPONSE_CACHE
from libs.gateway.cache_manager import CACHE_MANAGER_GATE, detect_multi_goal_query, CacheStatus

# LLM client for unified flow
from libs.gateway.llm_client import LLMClient

# v5.0 flow ARCHIVED - see archive/v5_flow.py.archived
# Unified flow is now the only active flow

# Unified flow imports
from libs.gateway.unified_flow import UnifiedFlow, UNIFIED_FLOW_ENABLED

# Unified cache system imports
from apps.services.orchestrator.cache_mcp import cache_stats as unified_cache_stats, cache_list
from apps.services.orchestrator.shared_state.cache_sweeper import sweep_now, get_cache_sweeper
from apps.services.orchestrator.shared_state.cache_registry import get_cache_registry

# Contract layer for component validation and repair
from apps.services.gateway.contract_enforcement import (
    CONTRACT_ENFORCER,
    CONTRACT_MONITOR,
    TokenBudgetEnforcer,
)
from apps.services.gateway.circuit_breaker import (
    get_circuit_breaker,
    CircuitOpenError,
)
from apps.services.gateway.contracts import (
    GuideResponse,
    CoordinatorResponse,
    ToolOutput,
    TokenBudget,
)



app = FastAPI(title="Pandora Gateway")
logger = logging.getLogger("uvicorn.error")

# CORS: allow access from phone/laptop on LAN
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

ORCH_URL = os.getenv("ORCH_URL", "http://127.0.0.1:8090")

# Guide/Coordinator endpoints (fall back to legacy SOLVER_/THINK_ envs for compatibility)
GUIDE_URL = os.getenv("GUIDE_URL") or os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
COORDINATOR_URL = os.getenv("COORDINATOR_URL") or os.getenv("THINK_URL", "http://127.0.0.1:8000/v1/chat/completions")
# Model identifiers for OpenAI-compatible requests
GUIDE_MODEL_ID = os.getenv("GUIDE_MODEL_ID") or os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
COORDINATOR_MODEL_ID = os.getenv("COORDINATOR_MODEL_ID") or os.getenv("THINK_MODEL_ID", GUIDE_MODEL_ID)
API_KEY = os.getenv("GATEWAY_API_KEY")
GUIDE_API_KEY = os.getenv("GUIDE_API_KEY") or os.getenv("SOLVER_API_KEY") or os.getenv("SOLVER_BEARER", "qwen-local")
COORDINATOR_API_KEY = os.getenv("COORDINATOR_API_KEY") or os.getenv("THINK_API_KEY") or GUIDE_API_KEY

GUIDE_HEADERS: dict[str, str] = {}
if GUIDE_API_KEY:
    GUIDE_HEADERS["Authorization"] = f"Bearer {GUIDE_API_KEY}"
COORDINATOR_HEADERS: dict[str, str] = {}
if COORDINATOR_API_KEY:
    COORDINATOR_HEADERS["Authorization"] = f"Bearer {COORDINATOR_API_KEY}"

# Legacy compatibility aliases
SOLVER_URL = GUIDE_URL
THINK_URL = COORDINATOR_URL
SOLVER_MODEL_ID = GUIDE_MODEL_ID
THINK_MODEL_ID = COORDINATOR_MODEL_ID
SOLVER_API_KEY = GUIDE_API_KEY
THINK_API_KEY = COORDINATOR_API_KEY
SOLVER_HEADERS = GUIDE_HEADERS
THINK_HEADERS = COORDINATOR_HEADERS

MAX_CYCLES = int(os.getenv("MAX_CYCLES", "3"))
TOKEN_BUDGET = int(os.getenv("TOKEN_BUDGET", "12000"))
MODEL_TIMEOUT = float(os.getenv("MODEL_TIMEOUT", "90"))
PROMPTS_DIR = pathlib.Path(os.getenv("PROMPTS_DIR", "apps/prompts"))
STATIC_DIR = pathlib.Path(os.getenv("STATIC_DIR", "static"))
CONTINUE_WEBHOOK = os.getenv("CONTINUE_WEBHOOK", "")

# Workspace configuration (repo browser / file tree)
_DEFAULT_REPOS_BASE = pathlib.Path(
    os.getenv("REPOS_BASE", str(pathlib.Path.cwd()))
).expanduser()
CONFIG_DIR = pathlib.Path(
    os.getenv("PANDORA_CONFIG_DIR", pathlib.Path.home() / ".config" / "pandora")
).expanduser()
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
REPOS_BASE_CONFIG_PATH = CONFIG_DIR / "repos_base.txt"


def _load_repos_base() -> pathlib.Path:
    workspace_logger = logging.getLogger("workspace")
    """Load repo base from config file or fall back to default/env."""
    if REPOS_BASE_CONFIG_PATH.exists():
        try:
            raw = REPOS_BASE_CONFIG_PATH.read_text(encoding="utf-8").strip()
            if raw:
                candidate = pathlib.Path(raw).expanduser().resolve()
                if candidate.exists() and candidate.is_dir():
                    workspace_logger.info(f"[Workspace] Loaded repo base from config: {candidate}")
                    return candidate
                workspace_logger.warning(
                    "[Workspace] Stored repo base invalid (%s). Falling back to default.",
                    raw,
                )
        except Exception as err:
            workspace_logger.error(f"[Workspace] Failed to read repo base config: {err}")
    try:
        return _DEFAULT_REPOS_BASE.resolve()
    except Exception:
        return pathlib.Path.cwd().resolve()


def _persist_repos_base(path: pathlib.Path) -> None:
    workspace_logger = logging.getLogger("workspace")
    try:
        REPOS_BASE_CONFIG_PATH.write_text(str(path), encoding="utf-8")
    except Exception as err:
        workspace_logger.error(f"[Workspace] Failed to persist repo base {path}: {err}")


def set_repos_base(path: pathlib.Path, persist: bool = True) -> pathlib.Path:
    workspace_logger = logging.getLogger("workspace")
    """Update the global repo base and optionally persist to disk."""
    global REPOS_BASE
    REPOS_BASE = path.resolve()
    if persist:
        _persist_repos_base(REPOS_BASE)
    workspace_logger.info(f"[Workspace] Repo base set to {REPOS_BASE}")
    return REPOS_BASE


REPOS_BASE = _load_repos_base()
PROMPT_BACKUP_DIR = pathlib.Path(os.getenv("PROMPT_BACKUP_DIR", "project_build_instructions/corpora/oldprompts"))
MEMORY_RECALL_ENABLE = os.getenv("MEMORY_RECALL_ENABLE", "1") == "1"
MEMORY_RECALL_K = int(os.getenv("MEMORY_RECALL_K", "3"))
TRANSCRIPTS_DIR = pathlib.Path(os.getenv("TRANSCRIPTS_DIR", "transcripts"))
TRACE_VERBOSE = os.getenv("TRACE_VERBOSE", "0") == "1"  # legacy env toggle (optional)
TRACE_MAX_PREVIEW = int(os.getenv("TRACE_MAX_PREVIEW", "800"))

# Context compression configuration
CONTEXT_WINDOW_SIZE = int(os.getenv("CONTEXT_WINDOW_SIZE", "10"))  # Messages to keep uncompressed
CONTEXT_KEEP_RECENT = int(os.getenv("CONTEXT_KEEP_RECENT", "3"))  # Always keep N most recent
CONTEXT_COMPRESSION_ENABLE = os.getenv("CONTEXT_COMPRESSION_ENABLE", "1") == "1"
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
MEM_INDEX_PATH = pathlib.Path(os.getenv("LONG_TERM_MEMORY_INDEX", "panda_system_docs/memory/long_term/index.json"))
MEM_JSON_DIR = pathlib.Path(os.getenv("LONG_TERM_MEMORY_DIR", "panda_system_docs/memory/long_term/json"))
PROFILE_MEMORY_MAX = int(os.getenv("PROFILE_MEMORY_MAX", "5"))

SHARED_STATE_DIR = pathlib.Path(os.getenv("SHARED_STATE_DIR", "panda_system_docs/shared_state"))
SHARED_STATE_DIR.mkdir(parents=True, exist_ok=True)

# Initialize tool circuit breaker
tool_circuit_breaker = ToolCircuitBreaker(
    failure_threshold=3,  # Open circuit after 3 failures
    window_seconds=300,  # Count failures within 5-minute window
    recovery_timeout=60,  # Wait 60s before testing recovery
    success_threshold=2  # Need 2 successes to close circuit
)
ARTIFACT_STORE = ArtifactStore(SHARED_STATE_DIR / "artifacts")
LEDGER = SessionLedger(SHARED_STATE_DIR / "ledger.db")
CLAIM_REGISTRY = ClaimRegistry(SHARED_STATE_DIR / "ledger.db")
SESSION_CONTEXTS = SessionContextManager(SHARED_STATE_DIR / "session_contexts")

# Unified context manager for Guide injections (Phase 1: rule-based, Phase 2: LLM-assisted)
UNIFIED_CONTEXT_MGR = UnifiedContextManager(
    llm_url=GUIDE_URL,
    enable_llm_curation=os.getenv("ENABLE_LLM_CURATION", "false").lower() == "true",
    enable_metrics=True,
    claim_registry=CLAIM_REGISTRY,
    mem_index_path=MEM_INDEX_PATH,
    mem_json_dir=MEM_JSON_DIR
)
logger.info(f"[Gateway] UnifiedContextManager initialized (LLM curation: {UNIFIED_CONTEXT_MGR.enable_llm_curation})")

TOOL_CATALOG_PATH = pathlib.Path(
    os.getenv("TOOL_CATALOG_PATH", "project_build_instructions/gateway/tool_catalog.json")
)
if TOOL_CATALOG_PATH.exists():
    TOOL_ROUTER = ToolRouter(ToolCatalog.load(TOOL_CATALOG_PATH))
else:
    TOOL_ROUTER = ToolRouter(ToolCatalog(tools=[]))  # empty catalog fallback
PLAN_LINTER = PlanLinter()
INTENT_CLASSIFIER = IntentClassifier()
WM_CONFIG = WorkingMemoryConfig()

# Contract layer initialization
CIRCUIT_BREAKER = get_circuit_breaker()
TOKEN_BUDGET_ENFORCER = TokenBudgetEnforcer(
    TokenBudget(total=TOKEN_BUDGET)
)

# Meta-reflection gate initialization
META_REFLECTION_GATE = MetaReflectionGate(
    llm_url=GUIDE_URL,
    llm_model=GUIDE_MODEL_ID,
    llm_api_key=GUIDE_API_KEY,
    accept_threshold=0.8,
    reject_threshold=0.4,
    max_tokens=80,
    timeout=10.0
)

# v4.0 document-driven flow initialization
V4_LLM_CLIENT = LLMClient(
    guide_url=GUIDE_URL,
    coordinator_url=COORDINATOR_URL,
    guide_model=GUIDE_MODEL_ID,
    coordinator_model=COORDINATOR_MODEL_ID,
    guide_headers={"Authorization": f"Bearer {GUIDE_API_KEY}"} if GUIDE_API_KEY != "none" else {},
    coordinator_headers={"Authorization": f"Bearer {COORDINATOR_API_KEY}"} if COORDINATOR_API_KEY != "none" else {},
    timeout=MODEL_TIMEOUT
)

# Unified flow initialization (7-phase architecture)
# V4Flow and V5Flow are deprecated - UnifiedFlow is the only active flow
UNIFIED_FLOW_HANDLER = UnifiedFlow(
    llm_client=V4_LLM_CLIENT,
    session_context_manager=SESSION_CONTEXTS
) if UNIFIED_FLOW_ENABLED else None

if UNIFIED_FLOW_ENABLED:
    logger.info("[Gateway] Unified 7-phase flow ENABLED")
else:
    logger.warning("[Gateway] Unified flow DISABLED - requests will fail")

# Advanced context features initialization (2025-11-10)
CONTEXT_SUMMARIZER = ContextSummarizer(
    model_url=GUIDE_URL,
    model_id=GUIDE_MODEL_ID,
    api_key=GUIDE_API_KEY
)

LLM_EXTRACTOR = LLMExtractor(
    model_url=GUIDE_URL,
    model_id=GUIDE_MODEL_ID,
    api_key=GUIDE_API_KEY
)
set_llm_extractor(LLM_EXTRACTOR)

# Cross-session learning store (lazy-initialized)
LEARNING_STORE = get_learning_store()


# ========================================
# Context Manager Memory Processing
# ========================================

async def process_turn_with_cm(
    session_id: str,
    turn_number: int,
    user_message: str,
    guide_response: str,
    tool_results: List[Dict[str, Any]],
    capsule: Optional[Any],
    current_context: Dict[str, Any],
    intent_classification: str,
    satisfaction_signal: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Call Context Manager to process complete turn and extract memories.

    This is the NEW centralized memory processing path.
    Replaces scattered extraction logic in Gateway.

    Returns:
        Context Manager's memory update decisions
    """
    try:
        # Convert capsule to dict if needed
        capsule_dict = None
        if capsule:
            if hasattr(capsule, '__dict__'):
                capsule_dict = {
                    "claim_summaries": getattr(capsule, 'claim_summaries', {}),
                    "confidence": getattr(capsule, 'confidence', 0.5),
                    "candidates": getattr(capsule, 'candidates', [])
                }
            elif isinstance(capsule, dict):
                capsule_dict = capsule

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{ORCH_URL}/context.process_turn",
                json={
                    "session_id": session_id,
                    "turn_number": turn_number,
                    "user_message": user_message,
                    "guide_response": guide_response,
                    "tool_results": tool_results or [],
                    "capsule": capsule_dict,
                    "current_context": current_context,
                    "intent_classification": intent_classification,
                    "satisfaction_signal": satisfaction_signal
                }
            )
            response.raise_for_status()
            result = response.json()

            if result.get("status") == "error":
                logger.error(f"[CM] Turn processing returned error: {result.get('error')}")

            return result

    except Exception as e:
        logger.error(f"[CM] Failed to process turn: {e}")
        # Return fallback (preserve existing context)
        return {
            "status": "error",
            "error": str(e),
            "preferences_updated": {},
            "preferences_preserved": current_context.get("preferences", {}),
            "preference_reasoning": {"error": "CM call failed, preserved existing preferences"},
            "topic": current_context.get("current_topic"),
            "facts": {},
            "turn_summary": {"short": "Error", "bullets": [], "tokens": 0},
            "conversation_quality": {
                "user_need_met": False,
                "information_complete": False,
                "requires_followup": True
            },
            "memory_actions": {
                "cache_response": False,
                "save_to_long_term": False
            },
            "response_cache_entry": None,
            "learning_patterns": None,
            "quality_score": 0.0,
            "satisfaction_score": 0.0,
            "errors": [str(e)]
        }


# Information provider registry for reflection loop (2025-11-10)
from apps.services.gateway.info_providers import (
    get_info_registry,
    memory_provider,
    quick_search_provider,
    claims_provider,
    session_history_provider
)

INFO_REGISTRY = get_info_registry()
INFO_REGISTRY.register("memory", memory_provider)
INFO_REGISTRY.register("quick_search", quick_search_provider)
INFO_REGISTRY.register("claims", claims_provider)
INFO_REGISTRY.register("session_history", session_history_provider)
logger.info("[Gateway] Info provider registry initialized with 4 providers")

RECENT_SHORT_TERM: defaultdict[str, Deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=6))

# ============================================================================
# THINKING VISUALIZATION INFRASTRUCTURE
# ============================================================================

@dataclass
class ThinkingEvent:
    """Represents a thinking stage event for real-time visualization."""
    trace_id: str
    stage: str  # query_received, guide_analyzing, coordinator_planning, orchestrator_executing, guide_synthesizing, response_complete, complete
    status: str  # pending, active, completed, error
    confidence: float  # 0.0-1.0
    duration_ms: int
    details: dict
    reasoning: str
    timestamp: float
    message: str = ""  # Optional message field for complete events (contains final response)

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return asdict(self)

# Event queues: trace_id -> queue of ThinkingEvents
_THINKING_QUEUES: Dict[str, asyncio.Queue] = {}
_THINKING_QUEUE_LOCK = asyncio.Lock()
_THINKING_CLEANUP_INTERVAL = 300  # Cleanup old queues every 5 minutes
_THINKING_MAX_AGE = 600  # Keep queues for 10 minutes
_THINKING_LAST_CLEANUP = time.time()

# Response store: trace_id -> (response_text, timestamp)
# Persists final responses so they can be fetched via polling if SSE drops
_RESPONSE_STORE: Dict[str, tuple] = {}
_RESPONSE_STORE_LOCK = asyncio.Lock()
_RESPONSE_STORE_MAX_AGE = 600  # Keep responses for 10 minutes

async def _emit_thinking_event(event: ThinkingEvent):
    """Emit a thinking event to the appropriate queue."""
    async with _THINKING_QUEUE_LOCK:
        if event.trace_id not in _THINKING_QUEUES:
            _THINKING_QUEUES[event.trace_id] = asyncio.Queue()
        await _THINKING_QUEUES[event.trace_id].put(event)
        logger.info(f"[Thinking] Event emitted: trace={event.trace_id}, stage={event.stage}, status={event.status}")

    # Store final response separately for polling fallback
    if event.stage == "complete" and event.message:
        async with _RESPONSE_STORE_LOCK:
            _RESPONSE_STORE[event.trace_id] = (event.message, time.time())
            logger.info(f"[ResponseStore] Stored response for trace {event.trace_id}: {len(event.message)} chars")

        # Remove queue so polling returns "complete" instead of "pending"
        async with _THINKING_QUEUE_LOCK:
            if event.trace_id in _THINKING_QUEUES:
                del _THINKING_QUEUES[event.trace_id]
                logger.info(f"[ResponseStore] Removed queue for trace {event.trace_id} (response stored)")

async def _cleanup_thinking_queues():
    """Remove old thinking queues and expired responses to prevent memory leaks."""
    global _THINKING_LAST_CLEANUP
    now = time.time()
    if now - _THINKING_LAST_CLEANUP < _THINKING_CLEANUP_INTERVAL:
        return

    async with _THINKING_QUEUE_LOCK:
        to_remove = []
        for trace_id in _THINKING_QUEUES:
            # Remove if queue is empty and old (no activity)
            queue = _THINKING_QUEUES[trace_id]
            if queue.empty():
                to_remove.append(trace_id)

        for trace_id in to_remove:
            del _THINKING_QUEUES[trace_id]

        if to_remove:
            logger.info(f"[Thinking] Cleaned up {len(to_remove)} old thinking queues")

    # Also cleanup old responses
    async with _RESPONSE_STORE_LOCK:
        expired = [
            trace_id for trace_id, (_, ts) in _RESPONSE_STORE.items()
            if now - ts > _RESPONSE_STORE_MAX_AGE
        ]
        for trace_id in expired:
            del _RESPONSE_STORE[trace_id]
        if expired:
            logger.info(f"[ResponseStore] Cleaned up {len(expired)} expired responses")

    _THINKING_LAST_CLEANUP = now

def _calculate_confidence(stage: str, context: dict) -> float:
    """
    Calculate confidence score (0.0-1.0) for a thinking stage.

    Args:
        stage: Thinking stage name
        context: Context dict with stage-specific data

    Returns:
        Confidence score between 0.0 and 1.0
    """
    if stage == "query_received":
        # High confidence if query is clear and well-formed
        query = context.get("query", "")
        if len(query.strip()) > 10:
            return 0.95
        return 0.7

    elif stage == "guide_analyzing":
        # Confidence based on query classification
        query_type = context.get("query_type", "general")
        complexity = context.get("complexity", "standard")
        if query_type != "general" and complexity != "multi_goal":
            return 0.85
        elif query_type != "general":
            return 0.75
        return 0.65

    elif stage == "coordinator_planning":
        # Confidence based on plan quality
        plan = context.get("plan", {})
        num_steps = len(plan.get("plan_steps", []))
        if num_steps > 0 and num_steps <= 5:
            return 0.9
        elif num_steps > 5:
            return 0.75
        return 0.5

    elif stage == "orchestrator_executing":
        # Confidence based on execution results
        success_rate = context.get("success_rate", 0.0)
        return success_rate

    elif stage == "guide_synthesizing":
        # Confidence based on capsule quality
        num_claims = context.get("num_claims", 0)
        if num_claims >= 5:
            return 0.9
        elif num_claims >= 2:
            return 0.8
        return 0.6

    elif stage == "response_complete":
        # Confidence based on overall success
        if context.get("success", False):
            return 0.95
        return 0.5

    return 0.5  # Default moderate confidence


def boost_confidence_for_patterns(
    base_confidence: float,
    conversation_history: list,
    current_query: str,
    cache_stats: dict = None
) -> tuple[float, list[str]]:
    """
    Boost confidence based on conversation patterns.

    Args:
        base_confidence: Initial confidence from strategic analysis
        conversation_history: Recent conversation turns
        current_query: Current user query
        cache_stats: Optional cache hit/miss statistics

    Returns:
        (adjusted_confidence, boost_reasons)
    """
    boost = 0.0
    reasons = []

    # Pattern 1: Query repetition (boost +0.1 if repeated 3+ times)
    query_lower = current_query.lower().strip()
    similar_queries = []

    for msg in conversation_history[-10:]:  # Check last 10 turns
        if msg.get("role") == "user":
            past_query = msg.get("content", "").lower().strip()
            # Use SequenceMatcher for fuzzy matching
            similarity = SequenceMatcher(None, query_lower, past_query).ratio()
            if similarity >= 0.7:  # 70% similarity threshold
                similar_queries.append(past_query)

    if len(similar_queries) >= 3:
        boost += 0.1
        reasons.append(f"Query pattern repeated {len(similar_queries)} times")

    # Pattern 2: High cache hit rate (boost +0.05 if ≥80%)
    if cache_stats:
        hit_rate = cache_stats.get("hit_rate", 0.0)
        if hit_rate >= 0.8:
            boost += 0.05
            reasons.append(f"High cache hit rate ({hit_rate:.0%})")

    # Pattern 3: Topic continuity (boost +0.05 if stayed on topic for 10+ turns)
    # Check if recent conversation has consistent topic keywords
    topic_keywords = set()
    recent_user_msgs = [
        msg.get("content", "").lower()
        for msg in conversation_history[-10:]
        if msg.get("role") == "user"
    ]

    if len(recent_user_msgs) >= 3:
        # Extract common words (excluding stopwords)
        stopwords = {"a", "an", "the", "is", "are", "of", "for", "to", "in", "on", "and", "or", "i", "you", "me"}
        all_words = []
        for msg in recent_user_msgs:
            words = [w for w in msg.split() if len(w) > 3 and w not in stopwords]
            all_words.extend(words)

        # Count word frequency
        word_counts = Counter(all_words)

        # If any word appears in 50%+ of recent messages, topic is consistent
        for word, count in word_counts.most_common(5):
            if count >= len(recent_user_msgs) * 0.5:
                topic_keywords.add(word)

        if len(topic_keywords) >= 2:
            boost += 0.05
            reasons.append(f"Topic continuity (keywords: {', '.join(list(topic_keywords)[:3])})")

    adjusted_confidence = min(1.0, base_confidence + boost)

    return adjusted_confidence, reasons

# Phase 3: Per-tool timeout configuration
TOOL_TIMEOUTS = {
    # Unified internet research with browser verification needs extra time
    # Increased to 7200s (2 hours) to allow for CAPTCHA solving and full research
    # Each cycle: 60-90s (page state + LLM decision + action + capture)
    "internet.research": 7200.0,

    # Commerce tools need longer timeout for URL verification (legacy)
    "commerce.search_offers": 360.0,

    # Research tools may need comprehensive search
    "research.orchestrate": 360.0,

    # Purchasing verification is moderate (legacy)
    "purchasing.lookup": 60.0,

    # Default: 30s for most tools
    # If not specified here, uses default_timeout parameter
}


async def create_research_event_callback(session_id: str):
    """
    Create callback function for research event streaming.

    This callback is passed to Orchestrator's research function,
    which calls it for each event (search_started, candidate_checking, etc.).

    Args:
        session_id: Session ID for WebSocket broadcast

    Returns:
        Async callback function
    """
    async def broadcast_event(event: Dict[str, Any]):
        """Broadcast event to WebSocket clients."""
        try:
            # Add session_id if not present
            if "session_id" not in event:
                event["session_id"] = session_id

            # Broadcast to all WebSocket clients for this session
            await research_ws_manager.broadcast_event(session_id, event)

            logger.debug(
                f"[ResearchEvents] Broadcast {event.get('type')} "
                f"to session {session_id}"
            )
        except Exception as e:
            logger.warning(f"[ResearchEvents] Failed to broadcast: {e}")

    return broadcast_event


async def call_orchestrator_with_circuit_breaker(
    client: httpx.AsyncClient,
    tool_name: str,
    args: dict,
    timeout: Optional[float] = None
) -> dict:
    """
    Call orchestrator tool with circuit breaker protection and schema validation.

    Phase 3: Per-tool timeout configuration added for complex operations.

    Args:
        client: HTTP client
        tool_name: Name of the tool (e.g., "search.orchestrate")
        args: Tool arguments
        timeout: Request timeout in seconds (if None, uses TOOL_TIMEOUTS or 30s default)

    Returns:
        Tool response dict

    Raises:
        HTTPException: If circuit is open, schema validation fails, or tool call fails
    """
    # Phase 3: Determine timeout (per-tool or default)
    if timeout is None:
        timeout = TOOL_TIMEOUTS.get(tool_name, 30.0)

    logger.info(f"[Circuit Breaker] {tool_name} timeout: {timeout}s")

    # STEP 1: Schema validation (prevent parameter hallucination)
    is_valid, error_msg = TOOL_ROUTER.catalog.validate_tool_call(tool_name, args)
    if not is_valid:
        logger.error(f"[Schema Validation] BLOCKED {tool_name}: {error_msg}")
        logger.error(f"[Schema Validation] Invalid args: {json.dumps(args, indent=2)}")
        # Record as failure for circuit breaker
        tool_circuit_breaker.record_failure(tool_name, f"Schema validation failed: {error_msg}")
        # Return error response (don't raise HTTPException - let Gateway continue)
        return {
            "status": "error",
            "error": f"Schema validation failed: {error_msg}",
            "invalid_args": args,
            "tool": tool_name
        }

    # STEP 2: Check circuit breaker
    allowed, reason = tool_circuit_breaker.check_allowed(tool_name)
    if not allowed:
        logger.warning(f"[Circuit Breaker] Blocked call to {tool_name}: {reason}")
        raise HTTPException(status_code=503, detail=reason)

    # STEP 2.5: Special handling for internet.research - use direct call for event streaming
    if tool_name == "internet.research":
        try:
            # Extract args
            query = args.get("query")
            research_goal = args.get("research_goal")
            mode = args.get("mode", "standard")
            max_sources = args.get("max_sources", 15)
            session_id = args.get("session_id", "default")
            human_assist_allowed = args.get("human_assist_allowed", True)
            token_budget = args.get("token_budget", 10800)
            use_snapshots = args.get("use_snapshots", True)

            logger.info(
                f"[Gateway→Orchestrator] SSE streaming call to adaptive research "
                f"(session: {session_id})"
            )

            # Call orchestrator via HTTP with SSE streaming to get real-time events
            # This enables CAPTCHA intervention notifications and research progress updates
            import httpx

            orchestrator_url = os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8090")

            # Build request payload
            research_payload = {
                "query": query,
                "research_goal": research_goal,
                "session_id": session_id,
                "human_assist_allowed": human_assist_allowed,
                "remaining_token_budget": token_budget if token_budget else 8000
            }

            # Stream events from orchestrator and forward to WebSocket clients
            result = None
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream(
                    "POST",
                    f"{orchestrator_url}/internet.research/stream",
                    json=research_payload
                ) as response:
                    response.raise_for_status()

                    # Parse SSE stream
                    async for line in response.aiter_lines():
                        if not line or line.startswith(":"):
                            continue

                        # Parse SSE format: "data: {...}"
                        if line.startswith("data: "):
                            data_str = line[6:]  # Remove "data: " prefix
                            try:
                                event = json.loads(data_str)
                                event_type = event.get("type")

                                logger.debug(f"[Gateway] SSE event: {event_type}")

                                # Forward event to WebSocket clients
                                await research_ws_manager.broadcast_event(session_id, event)

                                # Capture final result
                                if event_type == "research_complete":
                                    result = event.get("data", {})
                                    logger.info(
                                        f"[Gateway→Orchestrator] Research completed: "
                                        f"{result.get('strategy', 'unknown').upper()}, "
                                        f"{result.get('stats', {}).get('sources_visited', 0)} sources"
                                    )
                                elif event_type == "intervention_needed":
                                    logger.info(
                                        f"[Gateway] CAPTCHA intervention needed: "
                                        f"{event.get('data', {}).get('intervention_id')}"
                                    )
                            except json.JSONDecodeError as e:
                                logger.warning(f"[Gateway] Failed to parse SSE event: {e}")

            if result is None:
                raise Exception("No research_complete event received from orchestrator")

            # Record success for circuit breaker
            tool_circuit_breaker.record_success(tool_name)

            # Transform SSE research_complete data to match expected Gateway format
            # Result from SSE has different structure than direct call
            return {
                "query": result.get("query", query),
                "strategy": result.get("strategy", "unknown"),
                "strategy_reason": result.get("strategy_reason", ""),
                "results": {
                    "findings": result.get("findings", []),
                    "synthesis": result.get("synthesis", {})
                },
                "stats": result.get("stats", {}),
                "intelligence_cached": result.get("intelligence_cached", False)
            }

        except Exception as e:
            logger.error(f"[Gateway→Orchestrator] Research error: {e}", exc_info=True)
            # Record failure for circuit breaker
            tool_circuit_breaker.record_failure(tool_name, str(e))
            raise HTTPException(status_code=500, detail=str(e))

    # For all other tools, use HTTP as before
    try:
        # Make the call
        resp = await client.post(
            f"{ORCH_URL}/{tool_name}",
            json=args,
            timeout=timeout
        )

        # Check for success
        if resp.status_code == 200:
            tool_circuit_breaker.record_success(tool_name)
            return resp.json()
        else:
            # Record failure
            error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
            tool_circuit_breaker.record_failure(tool_name, error_msg)
            raise HTTPException(status_code=resp.status_code, detail=error_msg)

    except httpx.TimeoutException as e:
        # Phase 3: Enhanced timeout logging with configuration hints
        error_msg = f"Timeout after {timeout}s"
        logger.warning(f"[Circuit Breaker] {tool_name} TIMEOUT: {timeout}s exceeded")

        # Suggest increasing timeout if this is a complex tool
        if tool_name not in TOOL_TIMEOUTS:
            logger.warning(f"[Circuit Breaker] Hint: Consider adding {tool_name} to TOOL_TIMEOUTS config")

        tool_circuit_breaker.record_failure(tool_name, error_msg)
        raise HTTPException(status_code=504, detail=error_msg)
    except httpx.RequestError as e:
        error_msg = f"Request error: {str(e)}"
        tool_circuit_breaker.record_failure(tool_name, error_msg)
        raise HTTPException(status_code=502, detail=error_msg)
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        tool_circuit_breaker.record_failure(tool_name, error_msg)
        raise


PRICING_KEYWORDS = (
    "price",
    "pricing",
    "cost",
    "sale",
    "for sale",
    "buy",
    "purchase",
    "parts list",
    "part list",
    "bill of materials",
    "bom",
    "inventory",
    "availability",
    "in stock",
    "drone parts",
    "component list",
    "spreadsheet",
    "csv",
)

SPREADSHEET_KEYWORDS = (
    "spreadsheet",
    "csv",
    "excel",
    "sheet",
    "table",
    "ods",
    "google sheet",
    "write spreadsheet",
    "create spreadsheet",
)

CHAT_ALLOWED = {"doc.search", "code.search", "fs.read", "repo.describe", "memory.create", "memory.query", "wiki.search", "ocr.read", "bom.build", "internet.research", "commerce.search_offers", "commerce.search_with_recommendations", "commerce.quick_search", "purchasing.lookup"}
CONT_ALLOWED = CHAT_ALLOWED | {"file.write", "file.create", "file.edit", "file.delete", "code.apply_patch", "git.commit", "code.format", "test.run", "docs.write_spreadsheet", "bash.execute"}


def _contains_keyword_phrase(text: str, keywords: tuple[str, ...]) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(kw in lowered for kw in keywords)


_ACK_PHRASES = re.compile(r"\b(thanks?|thank you|cool|great|awesome|okay|ok)\b", re.IGNORECASE)
_SUBJECT_KEYWORDS = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9\s\-]{0,80}(?:hamster|kit|parts?|motor|battery|frame|drone|board|sensor|list|bundle|set|supply|component)s?)",
    re.IGNORECASE,
)

_SPECIES_HINTS = (
    "syrian",
    "teddy",
    "golden",
    "roborovski",
    "winter white",
    "campbell",
    "dwarf",
    "chinese",
    "siberian",
)

# Map common species aliases to their canonical names
_SPECIES_ALIASES = {
    "golden": "syrian",
    "teddy": "syrian",
    "fancy": "syrian",
    "winter white": "djungarian",
    "djungarian": "winter white",
    "russian": "dwarf",  # Common shorthand for Russian dwarf
}

def _normalize_species(kw: str) -> str:
    """Normalize species keyword to its canonical form for matching."""
    return _SPECIES_ALIASES.get(kw, kw)

_LEADING_STOPWORDS = (
    "is",
    "are",
    "was",
    "were",
    "the",
    "a",
    "an",
    "my",
    "your",
    "our",
    "favorite",
)


def _clean_subject(value: str) -> str:
    result = (value or "").strip()
    while True:
        lower = result.lower()
        matched = False
        for stop in _LEADING_STOPWORDS:
            prefix = stop + " "
            if lower.startswith(prefix):
                result = result[len(prefix):].lstrip()
                matched = True
                break
        if not matched:
            break
    return result.strip()


def _extract_subject_keywords(text: str) -> str:
    def _refine(candidate: str) -> str | None:
        cand = (candidate or "").strip()
        if not cand:
            return None
        lower = cand.lower()
        if "hamster" in lower:
            ham_candidates = re.findall(
                r"([A-Za-z0-9\-]{1,40}(?:\s[A-Za-z0-9\-]{1,40}){0,3}\s+hamsters?)",
                cand,
                re.IGNORECASE,
            )
            if ham_candidates:
                for ham in reversed(ham_candidates):
                    if any(hint in ham.lower() for hint in _SPECIES_HINTS):
                        return _clean_subject(ham)
                return _clean_subject(ham_candidates[-1])
        if any(hint in lower for hint in _SPECIES_HINTS):
            return _clean_subject(cand)
        return _clean_subject(cand) or None

    matches = _SUBJECT_KEYWORDS.findall(text)
    if not matches:
        return ""

    for candidate in reversed(matches):
        refined = _refine(candidate)
        if refined:
            return refined

    refined_tail = _refine(matches[-1])
    result = refined_tail or matches[-1].strip()
    return _clean_subject(result)


def _last_user_subject(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return ""
    # Skip the latest user message (current turn)
    for msg in reversed(messages[:-1]):
        if msg.get("role") != "user":
            continue
        text = (msg.get("content") or "").strip()
        if not text:
            continue
        if len(text) < 4:
            continue
        if _ACK_PHRASES.search(text) and len(text) < 60:
            continue
        subject = _extract_subject_keywords(text)
        if subject:
            return subject
        if len(text.split()) >= 2:
            return text
    return ""


def _extract_urls(text: str) -> list[str]:
    if not text:
        return []
    try:
        return re.findall(r"https?://[^\s]+", text)
    except Exception:
        return []


def _is_long_running_query(query: str) -> bool:
    """
    Detect if query will likely take >5 minutes (research, shopping, retry, etc.).
    These queries should use SSE for delivery.
    """
    keywords = [
        "retry", "find", "search", "buy", "purchase", "research",
        "for sale", "shop", "compare", "price", "vendor", "product"
    ]
    query_lower = query.lower()
    return any(kw in query_lower for kw in keywords)


RUNTIME_POLICY = {
    "chat_allow_file_create": os.getenv("CHAT_ALLOW_FILE_CREATE", "0") == "1",
    "write_confirm": os.getenv("WRITE_CONFIRM", "1") == "1",
    "chat_allowed_write_paths": [s.strip() for s in os.getenv("CHAT_ALLOWED_WRITE_PATHS", "").split(",") if s.strip()],
    "tool_enables": {}
}

def _get_allowed_write_roots():
    roots = RUNTIME_POLICY.get("chat_allowed_write_paths") or []
    if roots:
        return roots
    return [s.strip() for s in os.getenv("CHAT_ALLOWED_WRITE_PATHS", "").split(",") if s.strip()]

def _tool_enabled(name: str) -> bool:
    # default enabled unless explicitly disabled
    te = RUNTIME_POLICY.get("tool_enables") or {}
    if name in te:
        return bool(te[name])
    # env gate for quick disables (comma-separated names)
    disabled = [s.strip() for s in os.getenv("DISABLED_TOOLS", "").split(",") if s.strip()]
    return name not in disabled

def _profile_key(value: str | None) -> str:
    if not value:
        return "default"
    cleaned = re.sub(r"[^a-z0-9_-]", "_", value.lower())
    cleaned = cleaned.strip("_")
    return cleaned or "default"

def _read_prompt(name: str) -> str:
    try:
        p = PROMPTS_DIR / name
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""

# Module cache for dynamic assembly (avoids I/O overhead)
_MODULE_CACHE: Dict[str, str] = {}

def _read_prompt_cached(name: str) -> str:
    """Read prompt with caching to avoid repeated I/O."""
    if name not in _MODULE_CACHE:
        _MODULE_CACHE[name] = _read_prompt(name)
    return _MODULE_CACHE[name]

CONTEXT_MANAGER_SYSTEM = _read_prompt("context_manager.md")

# Prompts whitelist for editing via API
PROMPT_WHITELIST = {"solver_system.md", "thinking_system.md", "context_manager.md", "io_contracts.md"}

def _estimate_token_count(messages: list[dict[str, Any]]) -> int:
    """
    Estimate token count for a list of messages using word-based heuristic.
    Approximation: words * 1.3 to account for tokenization overhead.
    This is a rough estimate; for precise counting, use tiktoken or similar.
    """
    total_words = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            # Split by whitespace and count
            total_words += len(content.split())
        elif isinstance(content, list):
            # Handle multi-part content (images, text, etc.)
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total_words += len(part["text"].split())
    # Apply 1.3x multiplier for tokenization overhead
    return int(total_words * 1.3)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)
_FOLLOWUP_TICKET_OK_STATUSES = {"empty"}  # Allow retry only for empty search results
_PREFERENCE_PATTERNS = (
    re.compile(r"\bmy favorite (?:hamster|pet|animal) is (?:a )?(?P<value>[A-Za-z0-9\-\s]+)", re.IGNORECASE),
    re.compile(r"\bmy (?:favorite|fav) is (?:a |the )?(?P<value>[A-Za-z0-9\-\s]+)", re.IGNORECASE),  # NEW: handles "my favorite is X"
    re.compile(r"\bi (?:love|prefer) (?:the )?(?P<value>[A-Za-z0-9\-\s]+?) hamster", re.IGNORECASE),
)
_ACTIVITY_PATTERNS = (
    re.compile(r"\bsearch(?:ing)? for (?P<target>[A-Za-z0-9\-\s]+) (?:hamsters?|listings?)", re.IGNORECASE),
    re.compile(r"\blook(?:ing)? for (?P<target>[A-Za-z0-9\-\s]+) hamsters", re.IGNORECASE),
)
_OFFER_SKIP_KEYWORDS = (
    "book",
    "guide",
    "manual",
    "poster",
    "print",
    "plush",
    "toy",
    "video",
    "dvd",
    "shirt",
    "set",
    "figurine",
    "calendar",
    "sticker",
    "vitalsource",
    "barnes",
    "ebook",
    "walmart",
)
_REPEAT_HINT_RE = re.compile(r"\b(again|previous|repeat|same ones|earlier results|those again|the same links)\b", re.IGNORECASE)


def _iter_json_object_slices(text: str):
    depth = 0
    start = None
    in_string = False
    escape = False
    for idx, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == "\"":
                in_string = False
            continue
        if ch == "\"":
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
                if depth == 0 and start is not None:
                    yield text[start : idx + 1]
                    start = None


def _extract_json(obj_or_text):
    if isinstance(obj_or_text, dict):
        return obj_or_text
    text = (obj_or_text or "").strip()

    def _try_load(candidate: str):
        try:
            return json.loads(candidate)
        except Exception:
            return None

    if not text:
        return None
    m = _JSON_FENCE_RE.search(text)
    if m:
        candidate = (m.group(1) or "").strip()
        parsed = _try_load(candidate)
        if parsed is not None:
            return parsed
    parsed = _try_load(text)
    if parsed is not None:
        return parsed
    for slice_text in _iter_json_object_slices(text):
        parsed = _try_load(slice_text.strip())
        if parsed is not None:
            return parsed
    return None


def _build_trace_envelope(
    trace_id: str,
    session_id: str,
    mode: str,
    user_msg: str,
    profile: str,
    repo: str | None,
    policy: dict[str, Any] | None
) -> dict[str, Any]:
    """
    Build a trace envelope for logging.

    Args:
        trace_id: Unique trace identifier
        session_id: Session identifier
        mode: Execution mode (chat/code/plan)
        user_msg: User message text
        profile: Profile identifier
        repo: Repository path (optional)
        policy: Runtime policy dict (optional)

    Returns:
        Trace dictionary with standard structure
    """
    if policy is None:
        policy = {
            "chat_allow_file_create": RUNTIME_POLICY.get("chat_allow_file_create", False),
            "write_confirm": RUNTIME_POLICY.get("write_confirm", True),
            "tool_enables": RUNTIME_POLICY.get("tool_enables", {})
        }

    return {
        "id": trace_id,
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "repo": repo,
        "user": user_msg,
        "profile": profile,
        "session_id": session_id,
        "policy": policy,
        "guide_calls": [],
        "coordinator_calls": [],
        "tools_executed": [],
        "tickets": [],
        "bundles": [],
        "capsules": [],
        "policy_notes": [],
        "deferred": [],
        "injected_context": [],
        "strategic_decisions": [],
        "final": None,
        "dur_ms": None,
        "error": None,
    }


def _append_trace(trace: dict[str, Any]) -> None:
    """
    Append trace to daily transcript log and verbose log.

    Args:
        trace: Trace dictionary to append
    """
    try:
        trace_id = trace.get("id", "unknown")
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        day_file = TRANSCRIPTS_DIR / f"{day}.jsonl"

        # Create day file if it doesn't exist
        if not day_file.exists():
            day_file.write_text("", encoding="utf-8")

        # Append to daily log (compact format)
        with day_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(trace) + "\n")

        # Write verbose log (full format)
        vdir = TRANSCRIPTS_DIR / "verbose" / day
        vdir.mkdir(parents=True, exist_ok=True)
        with (vdir / f"{trace_id}.json").open("w", encoding="utf-8") as vf:
            json.dump(trace, vf, indent=2)

    except Exception as e:
        logger.warning(f"[Trace] Failed to append trace {trace.get('id')}: {e}")


# Stop words to filter out from keyword matching (prevents false cache hits)
_KEYWORD_STOP_WORDS = {
    "find", "search", "looking", "get", "show", "online", "for", "sale",
    "buy", "purchase", "some", "any", "the", "and", "with", "can", "you",
    "please", "help", "need", "want", "where", "what", "how", "why", "when"
}

# Serve static UI files (CSS, JS, etc.)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Serve intervention screenshots
SCREENSHOTS_DIR = Path("panda_system_docs/scrape_staging/screenshots")
if not SCREENSHOTS_DIR.exists():
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")

@app.get("/")
def web_index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"ok": True, "hint": "Static UI not found"})

@app.get("/browser_viewer")
def browser_viewer():
    """Serve noVNC browser viewer for CAPTCHA solving"""
    viewer_path = STATIC_DIR / "browser_viewer.html"
    if viewer_path.exists():
        return FileResponse(str(viewer_path))
    return JSONResponse({"error": "Browser viewer not found"}, status_code=404)

@app.get("/vnc.html")
async def serve_novnc_html():
    """Serve noVNC HTML from /opt/noVNC through the Gateway for Cloudflare compatibility"""
    novnc_path = Path("/opt/noVNC/vnc.html")
    if novnc_path.exists():
        return FileResponse(str(novnc_path))
    return JSONResponse({"error": "noVNC not found"}, status_code=404)

@app.get("/vnc_lite.html")
async def serve_novnc_lite_html():
    """Serve noVNC lite HTML from /opt/noVNC through the Gateway for Cloudflare compatibility"""
    novnc_path = Path("/opt/noVNC/vnc_lite.html")
    if novnc_path.exists():
        return FileResponse(str(novnc_path))
    return JSONResponse({"error": "noVNC lite not found"}, status_code=404)

@app.get("/app/{path:path}")
async def serve_novnc_app(path: str):
    """Serve noVNC app files from /opt/noVNC/app through the Gateway"""
    file_path = Path(f"/opt/noVNC/app/{path}")
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    return JSONResponse({"error": "File not found"}, status_code=404)

@app.get("/core/{path:path}")
async def serve_novnc_core(path: str):
    """Serve noVNC core files from /opt/noVNC/core through the Gateway"""
    file_path = Path(f"/opt/noVNC/core/{path}")
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    return JSONResponse({"error": "File not found"}, status_code=404)

@app.get("/vendor/{path:path}")
async def serve_novnc_vendor(path: str):
    """Serve noVNC vendor files from /opt/noVNC/vendor through the Gateway"""
    file_path = Path(f"/opt/noVNC/vendor/{path}")
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    return JSONResponse({"error": "File not found"}, status_code=404)

@app.websocket("/novnc_ws")
async def novnc_websocket_proxy(websocket: WebSocket):
    """
    WebSocket proxy for noVNC to work through Cloudflare tunnel.
    Proxies WebSocket traffic from browser to local noVNC server.
    """
    import websockets

    # Accept with binary subprotocol (required by noVNC)
    await websocket.accept(subprotocol="binary")

    # Connect to local noVNC websockify server with binary subprotocol
    novnc_url = "ws://localhost:6080/websockify"

    try:
        async with websockets.connect(
            novnc_url,
            subprotocols=["binary"],
            max_size=None,  # No message size limit for VNC frames
        ) as novnc_ws:
            logger.info("[novnc_ws] Connected to local noVNC server")

            # Bi-directional proxy
            async def forward_to_novnc():
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.receive":
                            if "bytes" in msg and msg["bytes"]:
                                await novnc_ws.send(msg["bytes"])
                            elif "text" in msg and msg["text"]:
                                await novnc_ws.send(msg["text"])
                        elif msg["type"] == "websocket.disconnect":
                            break
                except Exception as e:
                    logger.debug(f"[novnc_ws] Forward to noVNC ended: {e}")

            async def forward_to_client():
                try:
                    async for message in novnc_ws:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)
                except Exception as e:
                    logger.debug(f"[novnc_ws] Forward to client ended: {e}")

            # Run both directions concurrently
            await asyncio.gather(
                forward_to_novnc(),
                forward_to_client(),
                return_exceptions=True
            )
    except websockets.exceptions.InvalidStatusCode as e:
        logger.error(f"[novnc_ws] noVNC server rejected connection: {e}")
    except ConnectionRefusedError:
        logger.error("[novnc_ws] noVNC server not running on localhost:6080")
    except Exception as e:
        logger.error(f"[novnc_ws] Proxy error: {type(e).__name__}: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.get("/api/captchas/pending")
async def get_pending_captchas():
    """
    Get all pending CAPTCHA interventions.

    Returns list of interventions with their details for the web UI.
    """
    try:
        interventions = get_all_pending_interventions()
        return {
            "interventions": [i.to_dict() for i in interventions]
        }
    except Exception as e:
        logger.error(f"[CaptchaAPI] Error getting pending captchas: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/captchas/{intervention_id}/resolve")
async def resolve_captcha(intervention_id: str, request: Request):
    """
    Resolve a CAPTCHA intervention.

    Args:
        intervention_id: ID of the intervention to resolve
        request: JSON body with 'action' field ('solved' or 'skipped')

    Returns:
        Status of the resolution
    """
    try:
        body = await request.json()
        action = body.get("action")  # 'solved' or 'skipped'

        if action not in ['solved', 'skipped']:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action '{action}'. Must be 'solved' or 'skipped'"
            )

        intervention = get_pending_intervention(intervention_id)
        if not intervention:
            raise HTTPException(
                status_code=404,
                detail=f"Intervention '{intervention_id}' not found"
            )

        # Mark as resolved
        success = (action == "solved")
        intervention.mark_resolved(
            success=success,
            skip_reason=action if not success else None
        )

        # Remove from pending queue
        remove_pending_intervention(intervention_id)

        logger.info(
            f"[CaptchaAPI] Intervention {intervention_id} marked as {action}"
        )

        return {"status": "resolved", "action": action}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CaptchaAPI] Error resolving captcha: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Browser Control API Endpoints
# ============================================================================

@app.get("/api/browser_sessions")
async def get_browser_sessions():
    """
    Get all viewable browser sessions.

    Returns sessions that can be viewed/controlled via CDP,
    typically those paused for CAPTCHA interventions.
    """
    try:
        # Import here to avoid circular dependencies
        from apps.services.orchestrator.browser_session_registry import get_browser_session_registry

        registry = get_browser_session_registry()
        viewable = registry.get_viewable_sessions()

        return {
            "sessions": [session.to_dict() for session in viewable],
            "count": len(viewable)
        }
    except Exception as e:
        logger.error(f"[BrowserControlAPI] Error getting sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/browser_control/{session_id}")
async def browser_control_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for CDP proxy.

    Proxies CDP messages between web UI and Playwright browser,
    enabling remote browser viewing and control.
    """
    await websocket.accept()

    try:
        # Import CDP proxy
        from apps.services.orchestrator.browser_cdp_proxy import get_cdp_proxy

        # Create proxy connection
        proxy = await get_cdp_proxy()
        success = await proxy.create_proxy_connection(session_id, websocket)

        if not success:
            await websocket.close(code=1008, reason="Failed to connect to browser")

    except WebSocketDisconnect:
        logger.info(f"[BrowserControlWS] Client disconnected: {session_id}")
    except Exception as e:
        logger.error(f"[BrowserControlWS] Error: {e}", exc_info=True)
        try:
            await websocket.close(code=1011, reason=str(e))
        except:
            pass

async def forward_intervention_response(session_id: str, data: dict):
    """Forward intervention response from WebSocket client to orchestrator."""
    try:
        orch_url = os.getenv("ORCH_URL", "http://127.0.0.1:8090")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{orch_url}/internal/intervention_response",
                json={
                    "session_id": session_id,
                    "intervention_id": data.get("intervention_id"),
                    "action": data.get("action"),  # "solved", "skip", "cancel"
                    "user_input": data.get("user_input", "")
                }
            )
            logger.info(f"[InterventionForward] Response {response.status_code} for session {session_id}")
    except Exception as e:
        logger.error(f"[InterventionForward] Error forwarding to orchestrator: {e}")

@app.websocket("/ws/research/{session_id}")
async def research_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time research monitoring.

    Clients connect to receive live events during web research operations.
    """
    await research_ws_manager.connect(websocket, session_id)
    try:
        # Keep connection alive and listen for client messages
        while True:
            data = await websocket.receive_text()
            logger.info(f"[ResearchWS] Received from client: {data}")

            # Parse and handle intervention responses
            try:
                message = json.loads(data)
                if message.get("type") == "intervention_response":
                    # Forward to orchestrator's intervention manager
                    await forward_intervention_response(session_id, message)
                    logger.info(f"[ResearchWS] Forwarded intervention response for session {session_id}")
            except json.JSONDecodeError:
                logger.warning(f"[ResearchWS] Invalid JSON from {session_id}: {data}")
    except WebSocketDisconnect:
        await research_ws_manager.disconnect(websocket, session_id)
    except Exception as e:
        logger.error(f"[ResearchWS] Error: {e}")
        await research_ws_manager.disconnect(websocket, session_id)


@app.websocket("/ws/browser-stream/{stream_id}")
async def browser_stream_websocket(websocket: WebSocket, stream_id: str):
    """
    WebSocket endpoint for live browser streaming.

    Streams Playwright browser frames to client and receives user interactions.
    Used for remote CAPTCHA solving - user sees and controls server's browser.

    Architecture: User Browser ← this WS ← Orchestrator WS ← Playwright
    """
    import websockets

    await websocket.accept()
    logger.info(f"[BrowserStreamWS] Client connected: {stream_id}")

    orchestrator_ws = None

    try:
        # Connect to Orchestrator's WebSocket endpoint
        orch_ws_url = f"ws://127.0.0.1:8090/ws/browser-stream/{stream_id}"
        orchestrator_ws = await websockets.connect(orch_ws_url)
        logger.info(f"[BrowserStreamWS] Connected to Orchestrator stream: {stream_id}")

        # Create bidirectional proxy tasks
        async def forward_from_orchestrator():
            """Forward frames from Orchestrator to user's browser."""
            try:
                async for message in orchestrator_ws:
                    # Forward frame to user's browser
                    await websocket.send_text(message)
            except Exception as e:
                logger.error(f"[BrowserStreamWS] Error forwarding from Orchestrator: {e}")

        async def forward_from_user():
            """Forward user interactions from browser to Orchestrator."""
            try:
                while True:
                    data = await websocket.receive_text()
                    # Forward interaction to Orchestrator
                    await orchestrator_ws.send(data)
            except WebSocketDisconnect:
                logger.info(f"[BrowserStreamWS] User disconnected: {stream_id}")
            except Exception as e:
                logger.error(f"[BrowserStreamWS] Error forwarding from user: {e}")

        # Run both forwarding tasks concurrently
        await asyncio.gather(
            forward_from_orchestrator(),
            forward_from_user(),
            return_exceptions=True
        )

    except websockets.exceptions.WebSocketException as e:
        logger.error(f"[BrowserStreamWS] WebSocket error: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"Stream not available: {stream_id}"
        })
    except Exception as e:
        logger.error(f"[BrowserStreamWS] Error: {e}", exc_info=True)
    finally:
        # Clean up connections
        if orchestrator_ws:
            await orchestrator_ws.close()
        logger.info(f"[BrowserStreamWS] Connection closed: {stream_id}")


@app.post("/internal/browser_frame")
async def receive_browser_frame(frame_data: Dict[str, Any]):
    """
    Internal endpoint for Orchestrator to send browser frames.
    Forwards frames to connected WebSocket clients.
    """
    stream_id = frame_data.get("stream_id")
    # Note: In production, we'd have a manager tracking WebSocket connections
    # For now, the Orchestrator sends frames directly via WebSocket from its side
    return {"ok": True}


@app.post("/internal/research_event")
async def receive_research_event(event: Dict[str, Any]):
    """
    Internal endpoint for Orchestrator to send research events.
    Broadcasts events to connected WebSocket clients.
    """
    session_id = event.get("session_id", "default")
    event_type = event.get("type", "unknown")
    logger.info(f"[ResearchEvent] Received {event_type} event for session {session_id}")
    await research_ws_manager.broadcast_event(session_id, event)
    logger.info(f"[ResearchEvent] Broadcast complete for {event_type}")
    return {"ok": True}

@app.get("/status/cwd")
async def status_cwd():
    """Return current working directory and repos base for UI transparency."""
    return {
        "cwd": str(pathlib.Path.cwd()),
        "repos_base": str(REPOS_BASE),
        "hostname": os.uname().nodename if hasattr(os, 'uname') else 'unknown'
    }

@app.get("/v1/thinking/{trace_id}")
async def thinking_stream(trace_id: str):
    """
    Stream thinking events for a specific trace via Server-Sent Events (SSE).

    This endpoint allows the UI to receive real-time updates about the AI's
    thinking process as it works through a query.

    Args:
        trace_id: The trace/session ID to monitor

    Returns:
        SSE stream of ThinkingEvent objects as JSON
    """
    # Cleanup old queues periodically
    await _cleanup_thinking_queues()

    async def event_generator():
        """Generate SSE events from the thinking queue."""
        # Get or create queue for this trace
        async with _THINKING_QUEUE_LOCK:
            if trace_id not in _THINKING_QUEUES:
                _THINKING_QUEUES[trace_id] = asyncio.Queue()
            queue = _THINKING_QUEUES[trace_id]

        logger.info(f"[Thinking SSE] Client connected for trace {trace_id}, queue size: {queue.qsize()}")

        try:
            # Send initial ping to establish connection
            yield {
                "event": "ping",
                "data": json.dumps({"trace_id": trace_id, "timestamp": time.time()})
            }

            # First, drain all existing events in the queue
            events_sent = 0
            while not queue.empty():
                try:
                    event = queue.get_nowait()
                    events_sent += 1
                    logger.info(f"[Thinking SSE] Sending buffered event {events_sent}: {event.stage}")

                    # Determine event type based on stage
                    event_type = "complete" if event.stage == "complete" else "thinking"

                    # Send event to client
                    yield {
                        "event": event_type,
                        "data": json.dumps(event.to_dict())
                    }

                    # If this is the final event, we're done
                    # Only close on "complete" stage which has the final message, not on "response_complete"
                    if event.stage == "complete":
                        logger.info(f"[Thinking SSE] Stream complete for trace {trace_id} (sent {events_sent} events)")
                        return

                except asyncio.QueueEmpty:
                    break

            logger.info(f"[Thinking SSE] Sent {events_sent} buffered events, now waiting for new events")

            # Then, wait for any new events (in case request is still in progress)
            while True:
                try:
                    # Wait for next event with timeout to allow periodic pings
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    events_sent += 1
                    logger.info(f"[Thinking SSE] Sending live event {events_sent}: {event.stage}")

                    # Determine event type based on stage
                    event_type = "complete" if event.stage == "complete" else "thinking"

                    # Log complete event details
                    if event.stage == "complete":
                        logger.info(f"[Thinking SSE] Complete event has message: {len(event.message)} chars")
                        event_dict = event.to_dict()
                        logger.info(f"[Thinking SSE] Serialized complete event keys: {event_dict.keys()}")

                    # Send event to client
                    yield {
                        "event": event_type,
                        "data": json.dumps(event.to_dict())
                    }

                    # If this is the final event, close the stream
                    # Only close on "complete" stage which has the final message, not on "response_complete"
                    if event.stage == "complete":
                        logger.info(f"[Thinking SSE] Stream complete for trace {trace_id} (sent {events_sent} total events)")
                        # CRITICAL: Wait before closing to let Cloudflared flush the buffer
                        # Without this delay, the final event may not reach the browser
                        await asyncio.sleep(0.5)
                        # Send a final ping to ensure the complete event is flushed
                        yield {
                            "event": "ping",
                            "data": json.dumps({"trace_id": trace_id, "final": True, "timestamp": time.time()})
                        }
                        await asyncio.sleep(0.3)
                        break

                except asyncio.TimeoutError:
                    # Send periodic ping to keep connection alive
                    yield {
                        "event": "ping",
                        "data": json.dumps({"trace_id": trace_id, "timestamp": time.time()})
                    }

        except asyncio.CancelledError:
            logger.info(f"[Thinking SSE] Client disconnected for trace {trace_id}")
            raise

        except Exception as e:
            logger.error(f"[Thinking SSE] Error streaming for trace {trace_id}: {e}")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e), "trace_id": trace_id})
            }

    return EventSourceResponse(event_generator())


@app.get("/v1/response/{trace_id}")
async def get_response(trace_id: str):
    """
    Polling endpoint to retrieve the final response for a trace.

    Use this as a fallback when the SSE connection drops before receiving
    the complete event. Returns the response if available, or status indicating
    it's still pending.

    Args:
        trace_id: The trace/session ID to get the response for

    Returns:
        JSON with response if available, or status if still pending
    """
    async with _RESPONSE_STORE_LOCK:
        if trace_id in _RESPONSE_STORE:
            response_text, timestamp = _RESPONSE_STORE[trace_id]
            logger.info(f"[ResponsePoll] Found response for trace {trace_id}: {len(response_text)} chars")
            return {
                "status": "complete",
                "trace_id": trace_id,
                "response": response_text,
                "timestamp": timestamp
            }

    # Check if we have a pending queue for this trace
    async with _THINKING_QUEUE_LOCK:
        if trace_id in _THINKING_QUEUES:
            logger.info(f"[ResponsePoll] Trace {trace_id} still pending (queue exists)")
            return {
                "status": "pending",
                "trace_id": trace_id,
                "response": None
            }

    logger.info(f"[ResponsePoll] Trace {trace_id} not found")
    return {
        "status": "not_found",
        "trace_id": trace_id,
        "response": None
    }


@app.post("/v1/chat/completions")
async def chat_completions(
    payload: dict,
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_research_mode: str | None = Header(default=None),
    clear_session: bool = False,
):
    # Optional API-key check (enabled when GATEWAY_API_KEY is set)
    if API_KEY:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Missing API key")
        token = authorization.split(" ", 1)[1]
        if token != API_KEY:
            raise HTTPException(401, "Invalid API key")

    # ========================================
    # LIGHTWEIGHT RESEARCH MODE (DISABLED for research/commerce)
    # ========================================
    # IMPORTANT: Lightweight mode bypasses research tools and returns empty results
    # Only allow for non-research queries
    if x_research_mode == "lightweight":
        user_msg = payload.get("messages", [])[-1]["content"].lower() if payload.get("messages") else ""

        # Block lightweight mode for research/commerce queries
        research_keywords = ["find", "search", "buy", "purchase", "for sale", "hamster", "product", "vendor", "price"]
        is_research_query = any(keyword in user_msg for keyword in research_keywords)

        if is_research_query:
            logger.warning(
                f"[Gateway] LIGHTWEIGHT MODE blocked for research query: '{user_msg[:50]}...'"
            )
            logger.info("[Gateway] Forcing full v4 research flow instead of lightweight bypass")
            # Fall through to normal v4 flow below
        else:
            logger.info(f"[Gateway] LIGHTWEIGHT MODE: Direct LLM call for non-research query")

            messages = payload.get("messages", [])
            if not messages:
                raise HTTPException(400, "messages required for lightweight mode")

            model = payload.get("model", SOLVER_MODEL_ID)
            max_tokens = payload.get("max_tokens", 1000)
            temperature = payload.get("temperature", 0.3)

            # Direct LLM call (no v4 flow overhead)
            try:
                import httpx
                async with httpx.AsyncClient(timeout=60.0) as client:
                    llm_resp = await client.post(
                        SOLVER_URL,
                        headers=SOLVER_HEADERS,
                        json={
                            "model": model,
                            "messages": messages,
                            "max_tokens": max_tokens,
                            "temperature": temperature
                        }
                    )
                    llm_resp.raise_for_status()
                    llm_data = llm_resp.json()

                logger.info(f"[Gateway] LIGHTWEIGHT MODE: Success, returning direct response")
                return llm_data

            except Exception as e:
                logger.error(f"[Gateway] LIGHTWEIGHT MODE: Error: {e}")
                raise HTTPException(500, f"LLM call failed: {str(e)}")

    mode = payload.get("mode", "chat")
    user_msg = payload.get("messages", [])[-1]["content"] if payload.get("messages") else ""
    current_repo = payload.get("repo")
    profile_id = _profile_key(payload.get("user_id") or x_user_id)
    history_subject = _last_user_subject(payload.get("messages", []) or [])
    history_hints: list[str] = [history_subject] if history_subject else []

    # Compute session_id early (needed for SESSION_CONTEXTS.get)
    # Accept both "session_id" and "session" for convenience
    trace_id = uuid.uuid4().hex[:16]
    session_id = str(payload.get("session_id") or payload.get("session") or profile_id or trace_id)

    # ========================================
    # UNIFIED 7-PHASE FLOW ROUTING (highest priority)
    # ========================================
    if UNIFIED_FLOW_ENABLED and UNIFIED_FLOW_HANDLER:
        logger.info(f"[UnifiedRouting] Using unified 7-phase flow (trace={trace_id})")

        # Classify intent
        intent_result = INTENT_CLASSIFIER.classify(user_msg, mode)
        intent = intent_result.intent.value if hasattr(intent_result.intent, 'value') else str(intent_result.intent)

        try:
            # Execute unified flow
            start_time = time.time()
            unified_result = await UNIFIED_FLOW_HANDLER.handle_request(
                user_query=user_msg,
                session_id=session_id,
                mode=mode,
                intent=intent,
                trace_id=trace_id,
                turn_number=None,  # Let UnifiedFlow generate atomically
                repo=current_repo  # Pass repo for code mode context gathering
            )
            elapsed_ms = (time.time() - start_time) * 1000

            response_text = unified_result.get("response", "")
            turn_dir = unified_result.get("turn_dir")
            turn_number = unified_result.get("turn_number", 0)
            validation_passed = unified_result.get("validation_passed", True)

            # Build trace for logging
            trace = _build_trace_envelope(
                trace_id=trace_id,
                session_id=session_id,
                mode=mode,
                user_msg=user_msg,
                profile=profile_id,
                repo=current_repo,
                policy=None
            )
            trace["final"] = response_text
            trace["unified_flow"] = True
            trace["unified_turn_dir"] = str(turn_dir) if turn_dir else None
            trace["unified_turn_number"] = turn_number
            trace["validation_passed"] = validation_passed
            trace["elapsed_ms"] = elapsed_ms
            _append_trace(trace)

            logger.info(f"[UnifiedRouting] Unified flow complete (turn={turn_number}, elapsed={elapsed_ms:.0f}ms, validated={validation_passed})")

            # Emit thinking event (progress indicator)
            await _emit_thinking_event(ThinkingEvent(
                trace_id=trace_id,
                stage="response_complete",
                status="completed",
                confidence=1.0 if validation_passed else 0.7,
                duration_ms=int(elapsed_ms),
                details={"unified_flow": True, "turn_number": turn_number, "validation_passed": validation_passed},
                reasoning="Unified 7-phase flow completed",
                timestamp=time.time()
            ))

            # Emit complete event WITH message for SSE clients (required for UI to display response)
            await _emit_thinking_event(ThinkingEvent(
                trace_id=trace_id,
                stage="complete",
                status="completed",
                confidence=1.0 if validation_passed else 0.7,
                duration_ms=int(elapsed_ms),
                details={"unified_flow": True, "turn_number": turn_number},
                reasoning="Response ready",
                timestamp=time.time(),
                message=response_text
            ))
            logger.info(f"[UnifiedRouting] Emitted complete event for SSE (trace={trace_id}, msg_len={len(response_text)})")

            return {
                "id": trace_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": SOLVER_MODEL_ID,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop"
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "turn_number": turn_number,
                "validation_passed": validation_passed
            }

        except Exception as e:
            logger.exception(f"[UnifiedRouting] Error in unified flow: {e}")
            # Return error response - unified flow is the only path when enabled
            return {
                "id": trace_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": SOLVER_MODEL_ID,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": f"I encountered an error processing your request. Please try again. (Error: {type(e).__name__})"},
                        "finish_reason": "stop"
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "error": str(e)
            }

    # If we reach here, no flow handler is available
    logger.error(f"[Gateway] No flow handler available - UNIFIED_FLOW_ENABLED={UNIFIED_FLOW_ENABLED}")
    return {
        "id": trace_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": SOLVER_MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "No flow handler available. Please ensure UNIFIED_FLOW_ENABLED=true in your environment."
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        },
        "error": "No flow handler available"
    }

@app.post("/tool/execute")
async def tool_execute(payload: dict):
    """
    Execute a single tool call via Orchestrator after permission validation.
    Payload: { tool: str, args: {}, mode?: 'chat'|'continue', repo?: str, session_id?: str }
    """
    from libs.gateway.permission_validator import get_validator, PermissionDecision

    tool = payload.get("tool")
    args = payload.get("args") or {}
    mode = payload.get("mode", "chat")
    repo = payload.get("repo") or None
    session_id = payload.get("session_id", "unknown")

    if not tool or not isinstance(args, dict):
        raise HTTPException(400, "invalid payload")

    # Inject repo into args for validation
    if repo and "repo" not in args:
        args["repo"] = repo

    # === Permission Validation (mode gates + repo scope) ===
    validator = get_validator()
    validation = validator.validate(tool, args, mode, session_id)

    if validation.decision == PermissionDecision.DENIED:
        raise HTTPException(403, validation.reason)

    if validation.decision == PermissionDecision.NEEDS_APPROVAL:
        # Return 202 Accepted with approval request info
        return JSONResponse(
            status_code=202,
            content={
                "status": "pending_approval",
                "approval_request_id": validation.approval_request_id,
                "reason": validation.reason,
                "details": validation.approval_details
            }
        )

    # Tool global enable check
    if not _tool_enabled(tool):
        raise HTTPException(403, f"tool disabled: {tool}")

    async with httpx.AsyncClient(timeout=MODEL_TIMEOUT) as client:
        try:
            resp = await client.post(f"{ORCH_URL}/{tool}", json=args)
            resp.raise_for_status()
            return JSONResponse(resp.json())
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, f"orchestrator error: {e}")
        except Exception as e:
            raise HTTPException(500, f"tool execute error: {e}")


# ============================================================================
# Permission Management API Endpoints
# ============================================================================

@app.get("/api/permissions/pending")
async def get_pending_permissions(session_id: str = None):
    """Get all pending permission requests, optionally filtered by session."""
    from libs.gateway.permission_validator import get_validator

    validator = get_validator()
    requests = validator.get_pending_requests(session_id)
    return {"requests": requests}


@app.post("/api/permissions/{request_id}/resolve")
async def resolve_permission(request_id: str, request: Request):
    """Resolve a pending permission request (approve or deny)."""
    from libs.gateway.permission_validator import get_validator

    try:
        body = await request.json()
        approved = body.get("approved", False)
        reason = body.get("reason")

        validator = get_validator()
        success = validator.resolve_request(request_id, approved, reason)

        if success:
            return {"status": "resolved", "approved": approved}
        else:
            raise HTTPException(404, f"Request not found: {request_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Permissions] Error resolving {request_id}: {e}")
        raise HTTPException(500, str(e))


# ---------- Minimal endpoints used by the static UI ----------

@app.get("/teach/tools")
def teach_tools():
    return {"tools": [
        "doc.search", "code.search", "fs.read", "memory.create", "memory.query", "bom.build", "purchasing.lookup", "commerce.search_offers", "docs.write_spreadsheet", "file.create", "git.commit"
    ]}

@app.get("/broker/providers")
def broker_providers():
    return {"providers": [
        {"name": "wiki", "synonyms": ["wikipedia"]},
        {"name": "docs", "synonyms": ["documentation", "docs site"]},
    ]}

@app.post("/broker/request_context")
async def broker_request_context(payload: dict):
    needs = payload.get("needs", []) or []
    fast = bool(payload.get("fast", False))
    token_budget_hint = int(payload.get("token_budget_hint", 1000))
    repo = payload.get("repo") or None
    items = []
    meta = {"hint": "broker v1", "fast": fast}

    async with httpx.AsyncClient(timeout=MODEL_TIMEOUT) as client:
        for need in needs:
            ntype = (need or {}).get("type")
            scopes = (need or {}).get("scopes", [])
            query = (need or {}).get("query", "")
            max_results = int((need or {}).get("max_results", 8))
            if ntype == "search" and ("docs" in scopes or not scopes):
                try:
                    resp = await client.post(f"{ORCH_URL}/doc.search", json={"query": query, "k": max_results, "repo": repo})
                    resp.raise_for_status()
                    js = resp.json()
                    for ch in js.get("chunks", [])[:max_results]:
                        items.append({
                            "type": "doc",
                            "path": ch.get("path"),
                            "excerpt": ch.get("text_excerpt", ""),
                        })
                except Exception as e:
                    items.append({"type": "error", "message": f"doc.search error: {e}"})
            # future: elif scopes include 'wiki' or 'images' call /wiki.search or /ocr.read

    # Pack into a simple text block with headers
    excerpts = []
    for it in items:
        if it.get("type") == "doc":
            p = it.get("path", "?")
            ex = it.get("excerpt", "").strip()
            if ex:
                excerpts.append(f"# {p}\n{ex}")
    packed_text = "\n\n---\n\n".join(excerpts[: max(1, min(20, len(excerpts)))])
    # crude token estimate: words/0.75 ~ tokens
    approx_tokens = int(max(1, len(packed_text.split()) / 0.75)) if packed_text else 0
    # clamp to hint
    if token_budget_hint and approx_tokens > token_budget_hint:
        packed_text = packed_text[: max(200, int(len(packed_text) * (token_budget_hint / approx_tokens)))]
        approx_tokens = token_budget_hint

    return {"packed_text": packed_text, "approx_tokens": approx_tokens, "items": items, "meta": meta}

# ---------- Prompts management (P2) ----------

def _prompt_path(name: str) -> pathlib.Path:
    # prevent path traversal and only allow whitelisted names
    base = PROMPTS_DIR
    if name not in PROMPT_WHITELIST:
        raise HTTPException(400, f"prompt not allowed: {name}")
    return base / name

@app.get("/prompts")
def list_prompts():
    out = []
    for n in sorted(PROMPT_WHITELIST):
        p = _prompt_path(n)
        try:
            stat = p.stat()
            out.append({"name": n, "size": stat.st_size, "mtime": int(stat.st_mtime)})
        except FileNotFoundError:
            out.append({"name": n, "size": 0, "mtime": None})
    return {"prompts": out}

@app.get("/prompts/{name}")
def get_prompt(name: str):
    p = _prompt_path(name)
    try:
        return {"name": name, "content": p.read_text(encoding="utf-8")}
    except FileNotFoundError:
        return {"name": name, "content": ""}

@app.put("/prompts/{name}")
def put_prompt(name: str, req: dict):
    p = _prompt_path(name)
    content = req.get("content")
    if not isinstance(content, str):
        raise HTTPException(400, "content must be string")
    # small guardrail on size (256 KB)
    if len(content.encode("utf-8")) > 256 * 1024:
        raise HTTPException(413, "prompt too large (max 256KB)")
    # Backup old prompt (if exists)
    backup_dir = PROMPT_BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = None
    try:
        if p.exists():
            old = p.read_text(encoding="utf-8")
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_name = f"{name}.{ts}.bak.md"
            backup_path = backup_dir / backup_name
            backup_path.write_text(old, encoding="utf-8")
    except Exception:
        # Non-fatal: proceed even if backup fails
        backup_path = None
    # Write new content
    p.write_text(content, encoding="utf-8")
    return {
        "ok": True,
        "name": name,
        "bytes": len(content.encode("utf-8")),
        "backup": str(backup_path) if backup_path else None
    }

@app.get("/prompts/{name}/backups")
def list_prompt_backups(name: str):
    if name not in PROMPT_WHITELIST:
        raise HTTPException(400, "prompt not allowed")
    backup_dir = PROMPT_BACKUP_DIR
    backups = []
    if backup_dir.exists():
        for f in sorted(backup_dir.glob(f"{name}.*.bak.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                st = f.stat()
                backups.append({
                    "file": f.name,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime)
                })
            except FileNotFoundError:
                continue
    return {"name": name, "backups": backups}

@app.get("/prompts/{name}/backup")
def get_prompt_backup(name: str, file: str):
    if name not in PROMPT_WHITELIST:
        raise HTTPException(400, "prompt not allowed")
    # Simple validation: file must start with name and end with .bak.md and not contain path separators
    if "/" in file or ".." in file or not file.startswith(name + ".") or not file.endswith(".bak.md"):
        raise HTTPException(400, "invalid backup file name")
    path = PROMPT_BACKUP_DIR / file
    if not path.exists():
        raise HTTPException(404, "backup not found")
    try:
        return {"name": name, "file": file, "content": path.read_text(encoding="utf-8")}
    except Exception as e:
        raise HTTPException(500, f"read error: {e}")

@app.post("/broker/summarize_map")
async def broker_summarize_map(payload: dict):
    return {"summaries": []}

@app.post("/broker/summarize_reduce")
async def broker_summarize_reduce(payload: dict):
    return {"summary": ""}

@app.post("/ui/log")
async def ui_log(payload: dict, request: Request):
    try:
        log_path = pathlib.Path("ui.log")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": payload.get("ts"), "ip": request.client.host, **payload}) + "\n")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, f"log error: {e}")

@app.post("/continue/relay")
async def continue_relay(payload: dict):
    """
    DEPRECATED: Continue IDE integration removed.
    Pandora is now a standalone browser-based IDE with Monaco editor, file tree, and task tracker.
    Use the native code mode instead.
    """
    return {
        "deprecated": True,
        "message": "Continue relay has been removed. Pandora is now standalone with built-in IDE.",
        "migration": "Use code mode with the new Monaco editor, file tree, and task tracker panels."
    }

@app.get("/ui/repos/base")
def ui_repo_base():
    return {"path": str(REPOS_BASE)}


@app.post("/ui/repos/base")
def ui_set_repo_base(payload: Dict[str, Any] = Body(...)):
    path_value = (payload or {}).get("path")
    if not path_value or not isinstance(path_value, str):
        raise HTTPException(400, "Path is required")
    try:
        candidate = pathlib.Path(path_value).expanduser().resolve()
    except Exception:
        raise HTTPException(400, "Invalid path")
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(400, "Path does not exist or is not a directory")
    set_repos_base(candidate, persist=True)
    return {"path": str(REPOS_BASE)}


@app.get("/ui/repos")
def ui_repos():
    base = REPOS_BASE
    if not base.exists() or not base.is_dir():
        return {"repos": []}
    items = []
    for p in base.iterdir():
        try:
            if p.is_dir():
                items.append({"name": p.name, "path": str(p), "git": (p / ".git").exists()})
        except Exception:
            pass
    return {"repos": items}

@app.get("/ui/filetree")
def ui_filetree(repo: str):
    """
    Return jsTree-compatible file tree with git status indicators
    """
    import subprocess

    repo_path = pathlib.Path(repo).resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        return {"error": "Invalid repo path", "tree": []}

    # SECURITY: Validate repo_path is within REPOS_BASE to prevent path traversal
    try:
        repo_path.relative_to(REPOS_BASE.resolve())
    except ValueError:
        return {"error": "Repository path outside allowed base", "tree": []}

    # Get git status if this is a git repo
    git_status = {}
    if (repo_path / ".git").exists():
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=5
            )
            for line in result.stdout.strip().split("\n"):
                if len(line) > 3:
                    status = line[:2]
                    filepath = line[3:]
                    git_status[filepath] = status.strip()
        except Exception:
            pass  # Git not available or failed

    def build_tree_node(path: pathlib.Path, parent_path: str = ""):
        """Recursively build jsTree node structure"""
        rel_path = str(path.relative_to(repo_path)) if path != repo_path else ""

        # Skip hidden files and common ignore patterns
        if path.name.startswith(".") and path.name not in [".gitignore", ".env.example"]:
            return None
        if path.name in ["__pycache__", "node_modules", ".git", "venv", ".venv"]:
            return None

        node = {
            "text": path.name,
            "path": str(path),
        }

        # Check git status
        status = git_status.get(rel_path, "")
        if status:
            node["text"] = f"{node['text']} [{status}]"
            node["icon"] = "jstree-file"  # Could customize based on status

        if path.is_dir():
            node["type"] = "folder"
            node["children"] = []
            try:
                for child in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
                    child_node = build_tree_node(child, rel_path)
                    if child_node:
                        node["children"].append(child_node)
            except PermissionError:
                pass
            if not node["children"]:
                node["children"] = False  # jsTree format for empty folders
        else:
            node["type"] = "file"

        return node

    tree = []
    try:
        for item in sorted(repo_path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
            node = build_tree_node(item)
            if node:
                tree.append(node)
    except Exception as e:
        return {"error": str(e), "tree": []}

    return {"tree": tree, "repo": str(repo_path)}

@app.get("/transcripts")
def list_transcripts(limit: int = 50, q: str | None = None):
    entries = []
    qnorm = (q or "").strip().lower()
    try:
        files = sorted([p for p in TRANSCRIPTS_DIR.glob("*.jsonl")], key=lambda p: p.name, reverse=True)
        for p in files:
            # Read last up to 'limit' lines across files
            lines = p.read_text(encoding="utf-8").splitlines()
            vdir = TRANSCRIPTS_DIR / "verbose" / p.stem
            for line in reversed(lines):
                try:
                    js = json.loads(line)
                    # Filter by user text if q provided
                    if qnorm:
                        u = (js.get("user") or "")
                        if qnorm not in u.lower():
                            continue
                    has_verbose = False
                    try:
                        if vdir.exists():
                            vid = js.get("id")
                            if vid and (vdir / f"{vid}.json").exists():
                                has_verbose = True
                    except Exception:
                        has_verbose = False
                    entries.append({
                        "id": js.get("id"),
                        "ts": js.get("ts"),
                        "mode": js.get("mode"),
                        "repo": js.get("repo"),
                        "user_preview": (js.get("user") or "")[:120],
                        "dur_ms": js.get("dur_ms"),
                        "has_verbose": has_verbose,
                    })
                    if len(entries) >= limit:
                        raise StopIteration
                except StopIteration:
                    raise
                except Exception:
                    continue
            if len(entries) >= limit:
                break
    except StopIteration:
        pass
    except Exception:
        pass
    return {"items": entries}

@app.get("/transcripts/{trace_id}")
def get_transcript(trace_id: str):
    try:
        for p in sorted([p for p in TRANSCRIPTS_DIR.glob("*.jsonl")], key=lambda p: p.name, reverse=True):
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    js = json.loads(line)
                except Exception:
                    continue
                if js.get("id") == trace_id:
                    return js
    except Exception:
        pass
    raise HTTPException(404, "not found")

@app.get("/transcripts/{trace_id}/verbose")
def get_transcript_verbose(trace_id: str):
    try:
        # Find by scanning verbose subdirs
        vbase = TRANSCRIPTS_DIR / "verbose"
        if not vbase.exists():
            raise HTTPException(404, "not found")
        for daydir in sorted(vbase.iterdir(), reverse=True):
            p = daydir / f"{trace_id}.json"
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
    except HTTPException:
        raise
    except Exception:
        pass
    raise HTTPException(404, "not found")

@app.post("/transcripts/delete")
def delete_transcripts(payload: dict):
    ids = payload.get("ids")
    if not isinstance(ids, list) or not all(isinstance(x, str) and x for x in ids):
        raise HTTPException(400, "ids must be a non-empty list of strings")
    ids_set = set(ids)
    deleted = 0
    kept = 0
    files_processed = 0
    try:
        jsonl_files = sorted([p for p in TRANSCRIPTS_DIR.glob("*.jsonl")], key=lambda p: p.name)
        for jf in jsonl_files:
            try:
                lines = jf.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            out_lines = []
            removed_here = 0
            for line in lines:
                try:
                    js = json.loads(line)
                    tid = js.get("id")
                    if tid and tid in ids_set:
                        removed_here += 1
                        continue
                except Exception:
                    # If malformed, keep the line
                    pass
                out_lines.append(line)
            if removed_here > 0:
                tmp = jf.with_suffix(".jsonl.tmp")
                tmp.write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")
                tmp.replace(jf)
                deleted += removed_here
            kept += len(out_lines)
            files_processed += 1
        # Delete verbose files
        vdel = 0
        vbase = TRANSCRIPTS_DIR / "verbose"
        if vbase.exists():
            for daydir in vbase.iterdir():
                if not daydir.is_dir():
                    continue
                for tid in list(ids_set):
                    p = daydir / f"{tid}.json"
                    if p.exists():
                        try:
                            p.unlink()
                            vdel += 1
                        except Exception:
                            pass
        return {"ok": True, "deleted": deleted, "verbose_deleted": vdel, "files_processed": files_processed, "kept_lines": kept}
    except Exception as e:
        raise HTTPException(500, f"delete error: {e}")

@app.get("/policy")
def get_policy():
    """Expose limited, non-sensitive policy info for the UI."""
    return {
        "chat_allow_file_create": bool(RUNTIME_POLICY.get("chat_allow_file_create", False)),
        "write_confirm": bool(RUNTIME_POLICY.get("write_confirm", True)),
        "chat_allowed_write_paths": _get_allowed_write_roots(),
        "tool_enables": RUNTIME_POLICY.get("tool_enables", {}),
    }

@app.post("/policy")
def post_policy(req: dict):
    """Update in-memory policy flags. Not persisted across restarts."""
    try:
        if "chat_allow_file_create" in req:
            RUNTIME_POLICY["chat_allow_file_create"] = bool(req.get("chat_allow_file_create"))
        if "write_confirm" in req:
            RUNTIME_POLICY["write_confirm"] = bool(req.get("write_confirm"))
        if "chat_allowed_write_paths" in req and isinstance(req.get("chat_allowed_write_paths"), list):
            # Normalize strings and drop empties
            roots = []
            for s in req.get("chat_allowed_write_paths"):
                if isinstance(s, str) and s.strip():
                    roots.append(s.strip())
            RUNTIME_POLICY["chat_allowed_write_paths"] = roots
        if "tool_enables" in req and isinstance(req.get("tool_enables"), dict):
            # Only accept boolean-ish values
            out = {}
            for k, v in req.get("tool_enables").items():
                out[str(k)] = bool(v)
            RUNTIME_POLICY["tool_enables"] = out
        return {"ok": True, **get_policy()}
    except Exception as e:
        raise HTTPException(400, f"policy error: {e}")

# ---------------------- Async job execution (avoid 524) ----------------------

JOBS: dict[str, dict] = {}
CANCELLED_JOBS: set[str] = set()  # Track cancelled job IDs
CANCELLED_TRACES: set[str] = set()  # Track cancelled trace IDs


def is_trace_cancelled(trace_id: str) -> bool:
    """Check if a trace has been cancelled."""
    return trace_id in CANCELLED_TRACES

async def _run_chat_job(job_id: str, payload: dict):
    JOBS[job_id]["status"] = "running"; JOBS[job_id]["updated_at"] = time.time()
    # Call our own chat endpoint locally; include API key if enabled
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    try:
        async with httpx.AsyncClient(timeout=MODEL_TIMEOUT) as client:
            resp = await client.post("http://127.0.0.1:9000/v1/chat/completions", json=payload, headers=headers)
            body = None
            try:
                body = resp.json()
            except Exception:
                body = {"status": resp.status_code, "text": (resp.text[:1000] if resp.text else "")}
            if resp.status_code >= 200 and resp.status_code < 300:
                JOBS[job_id]["status"] = "done"
                JOBS[job_id]["result"] = body
            else:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = body
    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = {"message": str(e)}
    finally:
        JOBS[job_id]["updated_at"] = time.time()

@app.post("/jobs/start")
async def jobs_start(payload: dict):
    job_id = uuid.uuid4().hex[:16]
    JOBS[job_id] = {"status": "queued", "created_at": time.time(), "updated_at": time.time()}
    asyncio.create_task(_run_chat_job(job_id, payload))
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/active")
async def jobs_list_active():
    """List all active (queued or running) jobs."""
    active = []
    for job_id, job in JOBS.items():
        if job["status"] in ("queued", "running"):
            active.append({
                "job_id": job_id,
                "status": job["status"],
                "created_at": job["created_at"],
                "updated_at": job["updated_at"]
            })
    return {"active_jobs": active, "count": len(active)}


@app.get("/jobs/{job_id}")
async def jobs_get(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    # Shallow copy without large payloads
    out = {k: v for k, v in job.items() if k in {"status", "result", "error", "created_at", "updated_at"}}
    return out


@app.post("/jobs/{job_id}/cancel")
async def jobs_cancel(job_id: str):
    """
    Cancel a running job.

    This marks the job as cancelled and signals the flow to stop
    at the next checkpoint. The flow will gracefully terminate and
    return a cancellation message.
    """
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")

    if job["status"] not in ("queued", "running"):
        return {"ok": False, "message": f"Job already {job['status']}", "job_id": job_id}

    # Mark job as cancelled
    CANCELLED_JOBS.add(job_id)
    job["status"] = "cancelled"
    job["updated_at"] = time.time()

    # If job has an associated trace_id, mark that too
    trace_id = job.get("trace_id")
    if trace_id:
        CANCELLED_TRACES.add(trace_id)
        logger.info(f"[Jobs] Cancelled job {job_id} (trace={trace_id})")
    else:
        logger.info(f"[Jobs] Cancelled job {job_id}")

    return {"ok": True, "message": "Job cancelled", "job_id": job_id}


@app.post("/v1/thinking/{trace_id}/cancel")
async def cancel_trace(trace_id: str):
    """
    Cancel a running trace/research operation.

    This is used when the frontend wants to cancel an ongoing research
    operation that was started asynchronously (non-jobs mode).
    """
    if not trace_id:
        raise HTTPException(400, "trace_id required")

    # Mark trace as cancelled
    CANCELLED_TRACES.add(trace_id)
    logger.info(f"[Trace] Cancelled trace {trace_id}")

    return {"ok": True, "message": "Trace cancelled", "trace_id": trace_id}


# ============================================================================
# CONTRACT LAYER DEBUG ENDPOINTS
# ============================================================================

@app.get("/debug/contracts")
async def get_contract_violations():
    """
    View contract violations for debugging.

    Returns summary of all contract enforcement actions:
    - Total violations
    - Per-component breakdown
    - Repair success rates
    - Recent violations with details
    """
    return CONTRACT_MONITOR.get_summary()


@app.post("/debug/contracts/clear")
async def clear_contract_violations():
    """Clear all recorded contract violations (useful for testing)"""
    CONTRACT_MONITOR.clear()
    return {"ok": True, "message": "Contract violations cleared"}


@app.get("/debug/circuit-breaker")
async def get_circuit_breaker_status(component: Optional[str] = None):
    """
    View circuit breaker status for all components or a specific one.

    Query params:
        component: Optional component name to check (returns all if omitted)

    Returns:
        Circuit breaker state, failure counts, success rates, etc.
    """
    return CIRCUIT_BREAKER.get_status(component)


@app.post("/debug/circuit-breaker/reset")
async def reset_circuit_breaker(component: Optional[str] = None):
    """
    Reset circuit breaker state (useful for recovery after fixing issues).

    Query params:
        component: Optional component name to reset (resets all if omitted)
    """
    CIRCUIT_BREAKER.reset(component)
    return {"ok": True, "message": f"Circuit breaker reset for {component or 'all components'}"}


@app.get("/debug/token-budget")
async def get_token_budget_report():
    """
    View token budget usage report.

    Returns:
        - Total budget
        - Allocated vs used tokens per component
        - Over-budget components
        - Utilization percentage
    """
    return TOKEN_BUDGET_ENFORCER.get_usage_report()


@app.get("/debug/meta-reflection")
async def get_meta_reflection_stats():
    """
    View meta-reflection statistics.

    Returns:
        - Total calls by role (guide, coordinator, context_manager)
        - Proceed/clarification/analysis rates
        - Average tokens per call
        - Confidence distribution
    """
    return META_REFLECTION_GATE.get_stats()


@app.get("/debug/learning-stats")
async def get_learning_stats():
    """
    View cross-session learning statistics.

    Returns:
        - Total query patterns learned
        - Total user clusters
        - Most common patterns
        - Extraction failure rate
    """
    stats = LEARNING_STORE.get_statistics()

    # Top patterns
    top_patterns = sorted(
        LEARNING_STORE.query_patterns.items(),
        key=lambda x: x[1].count,
        reverse=True
    )[:10]

    # Top clusters
    top_clusters = sorted(
        LEARNING_STORE.user_clusters.values(),
        key=lambda x: x.session_count,
        reverse=True
    )[:10]

    return {
        "summary": stats,
        "top_patterns": [
            {
                "pattern": p[0],
                "count": p[1].count,
                "avg_confidence": p[1].avg_confidence,
                "common_topics": p[1].common_topics[:3]
            }
            for p in top_patterns
        ],
        "top_clusters": [
            {
                "cluster_id": c.cluster_id,
                "session_count": c.session_count,
                "avg_turn_count": c.avg_turn_count,
                "common_topics": c.common_topics[:5]
            }
            for c in top_clusters
        ]
    }


@app.get("/debug/summarizer-stats")
async def get_summarizer_stats():
    """
    View context summarizer statistics.

    Returns:
        - Configuration settings
        - Model info
    """
    return CONTEXT_SUMMARIZER.get_stats()


@app.get("/debug/cache-stats")
async def get_cache_stats():
    """
    View cache system statistics across all 3 layers.

    Returns:
        - Embedding service status
        - Tool cache (Layer 3) stats
        - Response cache (Layer 1) stats
        - Hit rates and token savings
    """
    try:
        return {
            "timestamp": time.time(),
            "embedding_service": EMBEDDING_SERVICE.get_model_info(),
            "layer_3_tool_cache": TOOL_CACHE.get_stats(),
            "layer_1_response_cache": RESPONSE_CACHE.get_stats(),
            "hybrid_search_config": {
                "embedding_weight": 0.7,
                "keyword_weight": 0.3,
                "domain_filtering_enabled": True
            }
        }
    except Exception as e:
        logger.error(f"[CacheStats] Error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }


@app.get("/debug/embedding-quality")
async def get_embedding_quality_metrics(days: int = 7):
    """
    View embedding quality metrics (false positives, accuracy).

    Tracks when embeddings mislead LLM for threshold tuning.

    Args:
        days: Number of days to analyze (default: 7)

    Returns:
        - False positive rate
        - Low quality cache hits
        - Domain confusion events
        - Overall embedding accuracy
    """
    try:
        # Load recent traces
        traces_dir = Path(__file__).parent.parent.parent / "transcripts"
        end_date = datetime.datetime.now(datetime.timezone.utc)
        start_date = end_date - datetime.timedelta(days=days)

        metrics = {
            "false_positives": 0,  # Embedding matched, LLM rejected
            "low_quality_cache": 0,  # Quality <0.60 from cache
            "domain_confusion": 0,  # Cross-domain matches
            "total_cache_hits": 0,
            "embedding_accuracy": 0.0
        }

        # Scan JSONL files in date range
        for date_delta in range(days + 1):
            check_date = end_date - datetime.timedelta(days=date_delta)
            date_str = check_date.strftime("%Y%m%d")
            trace_file = traces_dir / f"{date_str}.jsonl"

            if not trace_file.exists():
                continue

            try:
                with open(trace_file, 'r') as f:
                    for line in f:
                        try:
                            trace = json.loads(line)

                            # Count cache hits
                            if trace.get("cache_hit"):
                                metrics["total_cache_hits"] += 1

                            # Check for embedding quality events
                            event = trace.get("embedding_quality_event")
                            if event:
                                event_type = event.get("type")
                                if event_type == "false_positive":
                                    metrics["false_positives"] += 1
                                elif event_type == "low_quality_cache":
                                    metrics["low_quality_cache"] += 1
                                elif event_type == "domain_confusion":
                                    metrics["domain_confusion"] += 1

                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.warning(f"[EmbeddingQuality] Error reading {trace_file}: {e}")

        # Calculate accuracy
        if metrics["total_cache_hits"] > 0:
            error_count = metrics["false_positives"] + metrics["low_quality_cache"]
            metrics["embedding_accuracy"] = 1.0 - (error_count / metrics["total_cache_hits"])

        metrics["period_days"] = days
        metrics["period_start"] = start_date.isoformat()
        metrics["period_end"] = end_date.isoformat()

        return metrics

    except Exception as e:
        logger.error(f"[EmbeddingQuality] Error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }


@app.get("/debug/unified-cache-stats")
async def get_unified_cache_stats():
    """
    View unified cache system statistics (all layers via CacheRegistry).

    Returns:
        - Global cache statistics
        - Per-layer metrics (response, claims, tools)
        - Cascade hit rates
        - Total entries and size
    """
    try:
        stats = await unified_cache_stats()
        return {
            "status": "healthy",
            "timestamp": time.time(),
            **stats
        }
    except Exception as e:
        logger.error(f"[UnifiedCacheStats] Error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }


@app.get("/debug/cache-timeline")
async def get_cache_timeline(cache_type: str = "response", limit: int = 50):
    """
    View recent cache entries timeline.

    Args:
        cache_type: Cache layer (response, claims, tools)
        limit: Maximum entries to return

    Returns:
        - Recent cache entries with metadata
        - Entry count
        - Cache type
    """
    try:
        result = await cache_list(cache_type, limit=limit)
        return {
            "status": "healthy",
            "timestamp": time.time(),
            **result
        }
    except Exception as e:
        logger.error(f"[CacheTimeline] Error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "cache_type": cache_type,
            "timestamp": time.time()
        }


@app.post("/debug/cache-sweep")
async def trigger_cache_sweep():
    """
    Trigger immediate cache sweep across all layers.

    Returns:
        - Sweep statistics
        - Expired/evicted/pruned counts
        - Duration and errors
    """
    try:
        result = await sweep_now()
        return {
            "status": "success",
            "timestamp": time.time(),
            **result
        }
    except Exception as e:
        logger.error(f"[CacheSweep] Error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }


@app.get("/debug/cache-sweeper-stats")
async def get_cache_sweeper_stats():
    """
    View cache sweeper statistics.

    Returns:
        - Sweeper status (running/stopped)
        - Total sweep count
        - Total expired/evicted/pruned entries
        - Last sweep time
        - Configuration
    """
    try:
        sweeper = await get_cache_sweeper()
        stats = sweeper.get_stats()
        return {
            "status": "healthy",
            "timestamp": time.time(),
            **stats
        }
    except Exception as e:
        logger.error(f"[CacheSweeperStats] Error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }


@app.get("/debug/cache-registry-info")
async def get_cache_registry_info():
    """
    View cache registry information.

    Returns:
        - Registered cache layers
        - Cascade order
        - Per-layer cascade hit statistics
    """
    try:
        registry = await get_cache_registry()
        return {
            "status": "healthy",
            "timestamp": time.time(),
            "cascade_order": registry.get_cascade_order(),
            "cascade_hits": registry.get_cascade_stats(),
            "registered_caches": list(registry._stores.keys())
        }
    except Exception as e:
        logger.error(f"[CacheRegistryInfo] Error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }


@app.get("/debug/unified-context")
async def get_unified_context_metrics():
    """
    View unified context manager metrics.

    Returns:
        - Total curations performed
        - Average gather time (ms)
        - Average curate time (ms)
        - Cache hit rate
        - Average dedup count
        - Curation method breakdown
    """
    try:
        metrics = UNIFIED_CONTEXT_MGR.get_metrics()

        return {
            "status": "healthy",
            "timestamp": time.time(),
            "unified_context": {
                **metrics,
                "llm_curation_enabled": UNIFIED_CONTEXT_MGR.enable_llm_curation,
                "token_budgets": {
                    "meta_reflection": UNIFIED_CONTEXT_MGR.META_REFLECTION_BUDGET,
                    "guide": UNIFIED_CONTEXT_MGR.GUIDE_CONTEXT_BUDGET
                }
            }
        }

    except Exception as e:
        logger.error(f"[UnifiedContext] Error getting metrics: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }


@app.get("/health/detailed")
async def detailed_health_check():
    """
    Detailed health check including contract layer status.

    Returns:
        - Gateway health
        - Circuit breaker status
        - Contract violations
        - Token budget utilization
    """
    try:
        return {
            "status": "healthy",
            "timestamp": time.time(),
            "components": {
                "gateway": {
                    "status": "healthy",
                    "uptime_seconds": time.time() - _START_TIME if '_START_TIME' in globals() else 0
                },
                "circuit_breaker": CIRCUIT_BREAKER.get_status(),
                "contracts": CONTRACT_MONITOR.get_summary(),
                "token_budget": TOKEN_BUDGET_ENFORCER.get_usage_report()
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }

# ============================================================================
# Human-Assisted Web Crawling Endpoints
# ============================================================================

@app.get("/interventions/pending")
async def get_pending_interventions(session_id: Optional[str] = None):
    """
    Get pending CAPTCHA/auth interventions requiring user assistance.

    Args:
        session_id: Optional filter by session

    Returns:
        List of pending intervention requests
    """
    try:
        from apps.services.orchestrator.approval_manager import get_approval_manager

        approval_mgr = get_approval_manager()
        interventions = approval_mgr.get_pending_interventions(session_id)

        return {
            "status": "ok",
            "interventions": interventions,
            "count": len(interventions)
        }
    except Exception as e:
        logger.error(f"[Interventions] Error getting pending: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.post("/interventions/{intervention_id}/resolve")
async def resolve_intervention(
    intervention_id: str,
    request: Request
):
    """
    Mark intervention as resolved by user.

    Args:
        intervention_id: Intervention ID
        request: Request body containing resolved (bool) and cookies (optional)

    Returns:
        Status message
    """
    try:
        # Parse JSON body
        body = await request.json()
        resolved = body.get("resolved", True)
        cookies = body.get("cookies", None)

        from apps.services.orchestrator.approval_manager import get_approval_manager

        approval_mgr = get_approval_manager()
        success = await approval_mgr.resolve_intervention(
            intervention_id=intervention_id,
            resolved=resolved,
            cookies=cookies
        )

        if not success:
            # Intervention not found
            logger.warning(
                f"[Interventions] Intervention not found: {intervention_id}"
            )
            return JSONResponse(
                status_code=404,
                content={
                    "error": f"Intervention {intervention_id} not found",
                    "intervention_id": intervention_id
                }
            )

        logger.info(
            f"[Interventions] Resolved {intervention_id}: "
            f"success={resolved}"
        )

        return {
            "status": "ok",
            "intervention_id": intervention_id,
            "resolved": resolved
        }
    except Exception as e:
        logger.error(f"[Interventions] Error resolving {intervention_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/crawl/sessions")
async def list_crawl_sessions(user_id: str = "default"):
    """
    List active crawler sessions with stats.

    Args:
        user_id: User identifier

    Returns:
        List of active sessions
    """
    try:
        from apps.services.orchestrator.crawler_session_manager import get_crawler_session_manager

        session_mgr = get_crawler_session_manager()
        sessions = await session_mgr.list_sessions(user_id)

        return {
            "status": "ok",
            "sessions": sessions,
            "count": len(sessions)
        }
    except Exception as e:
        logger.error(f"[CrawlSessions] Error listing: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.delete("/crawl/sessions/{domain}")
async def delete_crawl_session(
    domain: str,
    session_id: str = "default",
    user_id: str = "default"
):
    """
    Delete a crawler session for a domain.

    Args:
        domain: Domain name
        session_id: Session identifier
        user_id: User identifier

    Returns:
        Status message
    """
    try:
        from apps.services.orchestrator.crawler_session_manager import get_crawler_session_manager

        session_mgr = get_crawler_session_manager()
        await session_mgr.delete_session(domain, session_id, user_id)

        logger.info(f"[CrawlSessions] Deleted session: {domain}")

        return {
            "status": "ok",
            "domain": domain,
            "deleted": True
        }
    except Exception as e:
        logger.error(f"[CrawlSessions] Error deleting {domain}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.post("/crawl/cleanup")
async def cleanup_expired_sessions():
    """
    Clean up expired crawler sessions.

    Returns:
        Number of sessions cleaned up
    """
    try:
        from apps.services.orchestrator.crawler_session_manager import get_crawler_session_manager

        session_mgr = get_crawler_session_manager()
        count = await session_mgr.cleanup_expired_sessions()

        logger.info(f"[CrawlSessions] Cleaned up {count} expired sessions")

        return {
            "status": "ok",
            "cleaned_up": count
        }
    except Exception as e:
        logger.error(f"[CrawlSessions] Error during cleanup: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/debug/intervention-stats")
async def get_intervention_stats():
    """Get intervention statistics for monitoring"""
    try:
        from apps.services.orchestrator.approval_manager import get_approval_manager

        approval_mgr = get_approval_manager()
        stats = approval_mgr.get_intervention_stats()

        return {
            "status": "ok",
            "stats": stats,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[InterventionStats] Error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# Track start time for uptime
_START_TIME = time.time()


# ============================================================================
# Phase 0 Monitoring Endpoints (Quality Agent Requirement)
# ============================================================================

@app.get("/debug/token-usage")
async def debug_token_usage(limit: int = 10):
    """
    Token usage statistics for recent turns.
    
    Quality Agent Requirement: Monitor token budgets, violations, overflow incidents from Day 1.
    
    Args:
        limit: Number of recent turns to analyze
        
    Returns:
        {
            "turns": [turn_stats],
            "summary": {
                "avg_gateway_usage": int,
                "avg_research_tokens": int,
                "budget_violations": int,
                "overflow_incidents": int
            }
        }
    """
    try:
        import os
        import json
        from datetime import datetime
        
        turns_dir = "panda_system_docs/turns"
        
        if not os.path.exists(turns_dir):
            return {"turns": [], "summary": {}}
        
        # Get recent turns
        turn_ids = sorted([d for d in os.listdir(turns_dir) if os.path.isdir(os.path.join(turns_dir, d))])[-limit:]
        
        turns = []
        for turn_id in turn_ids:
            manifest_path = os.path.join(turns_dir, turn_id, "manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)
                
                token_acct = manifest.get("token_accounting", {})
                turns.append({
                    "turn_id": turn_id,
                    "timestamp": manifest.get("timestamp"),
                    "gateway_budget": token_acct.get("gateway_budget", 12000),
                    "gateway_used": token_acct.get("gateway_used", 0),
                    "research_isolated": token_acct.get("research_tokens", {}).get("total_isolated", 0),
                    "strategy": token_acct.get("strategy_approved", "N/A"),
                    "downgrade": token_acct.get("downgrade_reason"),
                    "overflow_risk": token_acct.get("gateway_used", 0) > 11000
                })
        
        # Calculate summary
        violations = sum(1 for t in turns if t["overflow_risk"])
        overflow_incidents = sum(1 for t in turns if t.get("gateway_used", 0) > 12000)
        
        return {
            "turns": turns,
            "summary": {
                "avg_gateway_usage": sum(t["gateway_used"] for t in turns) // len(turns) if turns else 0,
                "avg_research_tokens": sum(t["research_isolated"] for t in turns) // len(turns) if turns else 0,
                "budget_violations": violations,
                "overflow_incidents": overflow_incidents
            }
        }
    except Exception as e:
        logger.error(f"[TokenUsage] Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/debug/timeout-stats")
async def debug_timeout_stats():
    """
    Timeout breaker statistics.
    
    Quality Agent Requirement: Monitor timeouts, failures, retries from Day 1.
    
    Returns:
        {
            "research": {...},
            "llm": {...},
            "tool": {...}
        }
    """
    try:
        from apps.services.gateway.timeout_breaker import get_all_stats
        return get_all_stats()
    except Exception as e:
        logger.error(f"[TimeoutStats] Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/debug/cm-streaming-stats")
async def debug_cm_streaming_stats(days: int = 7):
    """
    CM streaming statistics (success rate, checkpoint usage).
    
    Quality Agent Requirement: Monitor CM streaming from Day 1.
    
    Args:
        days: Number of days to analyze
        
    Returns:
        {
            "total_turns": int,
            "turns_with_streaming": int,
            "checkpoint_recoveries": int,
            "partial_failures": int,
            "total_failures": int,
            "avg_parts_per_turn": float,
            "avg_cm_calls_per_turn": float,
            "success_rate": str
        }
    """
    try:
        import os
        import json
        from datetime import datetime, timedelta
        
        cutoff = datetime.now() - timedelta(days=days)
        turns_dir = "panda_system_docs/turns"
        
        if not os.path.exists(turns_dir):
            return {"total_turns": 0, "success_rate": "N/A"}
        
        stats = {
            "total_turns": 0,
            "turns_with_streaming": 0,
            "checkpoint_recoveries": 0,
            "partial_failures": 0,
            "total_failures": 0,
            "avg_parts_per_turn": 0.0,
            "avg_cm_calls_per_turn": 0.0
        }
        
        total_parts = 0
        total_calls = 0
        
        for turn_id in os.listdir(turns_dir):
            manifest_path = os.path.join(turns_dir, turn_id, "manifest.json")
            if not os.path.exists(manifest_path):
                continue
            
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            
            turn_time = datetime.fromisoformat(manifest["timestamp"])
            if turn_time < cutoff:
                continue
            
            stats["total_turns"] += 1
            
            cm_recovery = manifest.get("cm_recovery", {})
            if cm_recovery:
                stats["turns_with_streaming"] += 1
                
                if cm_recovery.get("checkpoint_used"):
                    stats["checkpoint_recoveries"] += 1
                
                if cm_recovery.get("partial_success"):
                    stats["partial_failures"] += 1
            
            cm_calls = manifest.get("token_accounting", {}).get("cm_calls", {})
            if cm_calls:
                total_calls += cm_calls.get("count", 0)
                total_parts += cm_calls.get("bundles_processed", 0)
        
        if stats["turns_with_streaming"] > 0:
            stats["avg_parts_per_turn"] = total_parts / stats["turns_with_streaming"]
            stats["avg_cm_calls_per_turn"] = total_calls / stats["turns_with_streaming"]
        
        stats["success_rate"] = f"{(1 - stats['total_failures'] / max(stats['total_turns'], 1)) * 100:.1f}%"
        
        return stats
    except Exception as e:
        logger.error(f"[CMStreamingStats] Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/debug/cache-fingerprint-collisions")
async def debug_cache_fingerprint_collisions(days: int = 7):
    """
    Cache fingerprint collision detection.
    
    Quality Agent Requirement: Monitor validation failures from Day 1.
    
    Args:
        days: Number of days to analyze
        
    Returns:
        {
            "period_days": int,
            "total_fingerprints": int,
            "collisions_detected": int,
            "collision_rate": str,
            "recent_collisions": []
        }
    """
    try:
        # TODO: Implement collision tracking once cache is active
        # For now, return placeholder
        
        return {
            "period_days": days,
            "total_fingerprints": 0,
            "collisions_detected": 0,
            "collision_rate": "0.0%",
            "recent_collisions": [],
            "note": "Full collision tracking will be implemented in Phase 1 (cache integration)"
        }
    except Exception as e:
        logger.error(f"[FingerprintCollisions] Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/debug/phase0-health")
async def debug_phase0_health():
    """
    Phase 0 infrastructure health check.
    
    Checks all Phase 0 components:
    - Token utils (tiktoken availability)
    - Token governance (budget reservation)
    - Timeout breakers (statistics)
    - CM error recovery (checkpoint support)
    - Doc pack builder (import success)
    - Context fingerprint (intent validation)
    
    Returns:
        {
            "status": "healthy" | "degraded" | "unhealthy",
            "components": {...},
            "errors": [...]
        }
    """
    try:
        health = {
            "status": "healthy",
            "components": {},
            "errors": []
        }
        
        # Check token utils
        try:
            from apps.services.gateway.token_utils import count_tokens_safe, TIKTOKEN_AVAILABLE
            health["components"]["token_utils"] = {
                "status": "ok",
                "tiktoken_available": TIKTOKEN_AVAILABLE
            }
        except Exception as e:
            health["components"]["token_utils"] = {"status": "error", "error": str(e)}
            health["errors"].append(f"token_utils: {e}")
            health["status"] = "degraded"
        
        # Check token governance
        try:
            from apps.services.gateway.token_governance import detect_strategy, STRATEGY_BUDGETS
            health["components"]["token_governance"] = {
                "status": "ok",
                "strategies": list(STRATEGY_BUDGETS.keys())
            }
        except Exception as e:
            health["components"]["token_governance"] = {"status": "error", "error": str(e)}
            health["errors"].append(f"token_governance: {e}")
            health["status"] = "unhealthy"
        
        # Check timeout breakers
        try:
            from apps.services.gateway.timeout_breaker import RESEARCH_BREAKER, LLM_BREAKER, TOOL_BREAKER
            health["components"]["timeout_breakers"] = {
                "status": "ok",
                "research_timeout": RESEARCH_BREAKER.timeout,
                "llm_timeout": LLM_BREAKER.timeout,
                "tool_timeout": TOOL_BREAKER.timeout
            }
        except Exception as e:
            health["components"]["timeout_breakers"] = {"status": "error", "error": str(e)}
            health["errors"].append(f"timeout_breakers: {e}")
            health["status"] = "unhealthy"
        
        # Check CM error recovery
        try:
            from apps.services.gateway.cm_error_recovery import CMStreamProcessor
            health["components"]["cm_error_recovery"] = {"status": "ok"}
        except Exception as e:
            health["components"]["cm_error_recovery"] = {"status": "error", "error": str(e)}
            health["errors"].append(f"cm_error_recovery: {e}")
            health["status"] = "degraded"

        # Check doc pack builder
        try:
            from libs.gateway.doc_pack_builder import DocPackBuilder
            health["components"]["doc_pack_builder"] = {"status": "ok"}
        except Exception as e:
            health["components"]["doc_pack_builder"] = {"status": "error", "error": str(e)}
            health["errors"].append(f"doc_pack_builder: {e}")
            health["status"] = "unhealthy"
        
        # Check context fingerprint
        try:
            from apps.services.orchestrator.shared_state.context_fingerprint import compute_fingerprint
            test_fp = compute_fingerprint(
                session_id="test",
                query="test query",
                intent="transactional"  # Quality Agent requirement
            )
            health["components"]["context_fingerprint"] = {
                "status": "ok",
                "intent_validation": "intent" in test_fp.components
            }
        except Exception as e:
            health["components"]["context_fingerprint"] = {"status": "error", "error": str(e)}
            health["errors"].append(f"context_fingerprint: {e}")
            health["status"] = "degraded"
        
        return health
    except Exception as e:
        logger.error(f"[Phase0Health] Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

