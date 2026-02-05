import copy
import datetime
import glob
import hashlib
import httpx
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Load .env file before any other imports that might use env vars
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Centralized logging - must be set up before other imports that use logging
from libs.core.logging_config import setup_logging, get_logger
setup_logging(service_name="tool_server")
logger = get_logger(__name__)

from apps.services.tool_server import bom_normalizer
from apps.services.tool_server import commerce_mcp, spreadsheet_mcp, purchasing_mcp
from apps.services.tool_server import code_mcp, git_mcp, bash_mcp, diagnostics_mcp
# Note: research_orchestrator_mcp (legacy), research_mcp, and search_orchestrator_mcp are deprecated (2025-11-15)
from apps.services.tool_server import reflection_engine
from apps.services.tool_server import repo_scope_mcp, code_verify_mcp, file_operations_mcp, context_snapshot_mcp
from apps.services.tool_server import playwright_stealth_mcp
from apps.services.tool_server import computer_agent_mcp
from apps.services.tool_server.memory_store import (
    get_memory_store,
    initialize_project_memory_bank,
    load_project_memory_bank,
    list_user_projects,
    get_project_metadata,
)
from apps.services.tool_server.web_fetcher import (
    extract_main_content,
    fetch_url_basic,
    stage_scrape_result,
)
from apps.services.tool_server.context_manager_memory import ContextManagerMemory
from apps.services.tool_server.log_rotator import rotate_logs_for_query
from apps.services.tool_server.query_planner import get_query_builder_metrics
from apps.services.tool_server.shared.llm_utils import load_prompt_via_recipe as _load_prompt_via_recipe

# Phase API for n8n integration
from apps.services.tool_server.phase_api import router as phase_router

app = FastAPI(
    title="Panda Tool Server",
    description="Tool execution service - 8-Phase Pipeline support",
)
# Design Note: "Orchestrator" is legacy naming. Current architecture uses "Tool Server".
# This service handles tool execution via MCP endpoints, delegated from Gateway.

# Include Phase API router for n8n integration
app.include_router(phase_router)

# Track startup time for uptime reporting
_start_time = time.time()


@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {
        "status": "healthy",
        "service": "orchestrator",
        "port": 8090,
        "uptime_seconds": int(time.time() - _start_time)
    }


@app.get("/metrics/query-builder")
async def query_builder_metrics():
    """
    Query builder health metrics.

    Tracks success rate of structured JSON parsing vs fallbacks.
    If success_rate drops below 80%, investigate recent_failures.
    """
    return get_query_builder_metrics()


def _load_prompt(prompt_name: str) -> str:
    """Load prompt - maps legacy names to recipe names."""
    return _load_prompt_via_recipe(prompt_name, "tools")


# Add CORS middleware to allow research_monitor.html (served from Gateway port 9000)
# to call Orchestrator intervention resolution endpoint
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:9000",
        "http://127.0.0.1:9000",
        "http://0.0.0.0:9000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Permission Middleware (Defense-in-Depth)
# ============================================================================
# This middleware provides backup validation at the orchestrator level
# for direct orchestrator calls that bypass the gateway.

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse as StarletteJSONResponse


class PermissionMiddleware(BaseHTTPMiddleware):
    """
    Backup permission validation at orchestrator level.

    This provides defense-in-depth for direct orchestrator calls
    that bypass the gateway. Gateway validation is the primary gate.

    Checks X-Panda-Mode header to ensure code-mode tools are only
    called with appropriate mode.
    """

    # Endpoints that require code/continue mode
    CODE_MODE_ENDPOINTS = {
        "/file.write", "/file.create", "/file.edit", "/file.delete",
        "/git.commit", "/git.commit_safe", "/git.add", "/git.push",
        "/git.pull", "/git.branch", "/git.create_pr", "/git.reset",
        "/bash.execute", "/bash.kill",
        "/code.apply_patch", "/code.format",
        "/test.run", "/docs.write_spreadsheet"
    }

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip non-tool endpoints and read-only endpoints
        if path not in self.CODE_MODE_ENDPOINTS:
            return await call_next(request)

        # Check for mode header (gateway sets this when calling orchestrator)
        mode = request.headers.get("X-Panda-Mode", "")

        # If no mode header, this might be a direct call - check env for enforcement
        enforce = os.getenv("ENFORCE_MODE_GATES", "1") == "1"
        if not enforce:
            return await call_next(request)

        # If mode header is present and not code/continue, reject
        if mode and mode not in ("code", "continue"):
            logger.warning(f"[PermissionMiddleware] Blocked {path}: mode={mode}")
            return StarletteJSONResponse(
                status_code=403,
                content={"error": f"Endpoint {path} requires code mode (got: {mode})"}
            )

        # If no mode header at all, this is likely a direct call
        # Allow it for backwards compatibility but log warning
        if not mode:
            logger.debug(f"[PermissionMiddleware] No mode header for {path} - allowing (direct call)")

        return await call_next(request)


app.add_middleware(PermissionMiddleware)


# Module-scope callback for research event broadcasting
async def send_research_event_to_gateway(event: Dict[str, Any]):
    """
    Send research event to Gateway for WebSocket broadcast.
    Module-scope function to avoid async context issues.
    Non-blocking - failures are logged but don't prevent research.

    Uses synchronous requests library to avoid httpx async event loop issues.
    """
    event_type = event.get('type', 'unknown')
    logger.info(f"[ResearchEvent] Attempting to send {event_type}")

    try:
        import requests
        import asyncio

        gateway_host = os.getenv("GATEWAY_HOST")
        if gateway_host:
            gateway_url = f"http://{gateway_host}:9000"
        else:
            gateway_url = os.getenv("GATEWAY_URL", "http://127.0.0.1:9000")

        logger.debug(f"[ResearchEvent] Gateway URL: {gateway_url}")

        # Use synchronous requests in a thread pool to avoid event loop issues
        def sync_post():
            return requests.post(
                f"{gateway_url}/internal/research_event",
                json=event,
                timeout=2.0
            )

        response = await asyncio.to_thread(sync_post)

        if response.status_code == 200:
            logger.info(f"[ResearchEvent] ✓ Successfully sent {event_type}")
        else:
            logger.warning(f"[ResearchEvent] Got status {response.status_code} for {event_type}")
    except Exception as e:
        # Log but don't raise - event delivery failures shouldn't block research
        logger.warning(f"[ResearchEvent] ✗ Failed to send {event_type}: {type(e).__name__}: {e}")

REPOS_BASE = Path(os.getenv("REPOS_BASE", os.getcwd())).resolve()
SCRAPE_STAGING_DIR = Path(
    os.getenv("SCRAPE_STAGING_DIR", "panda_system_docs/scrape_staging")
).expanduser()
BOM_CACHE_DIR = Path(
    os.getenv("BOM_CACHE_DIR", str(SCRAPE_STAGING_DIR / "bom_cache"))
).expanduser()
BOM_CACHE_TTL_SECONDS = max(0, int(os.getenv("BOM_CACHE_TTL_SECONDS", "86400")))
SERPAPI_COUNTRY = os.getenv("BOM_SERPAPI_COUNTRY", "us")
SERPAPI_LANGUAGE = os.getenv("BOM_SERPAPI_LANGUAGE", "en")
SERPAPI_PAUSE = float(os.getenv("BOM_SERPAPI_PAUSE_SEC", "0.6"))
SERPAPI_MAX_RESULTS = max(1, int(os.getenv("BOM_SERPAPI_MAX_RESULTS", "10")))

# Initialize Context Manager Memory Processor
CONTEXT_MANAGER_URL = os.getenv("SOLVER_URL", "http://localhost:8000/v1/chat/completions")
CONTEXT_MANAGER_MODEL_ID = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
CONTEXT_MANAGER_API_KEY = os.getenv("SOLVER_API_KEY", "qwen-local")
CM_MEMORY = ContextManagerMemory(CONTEXT_MANAGER_URL, CONTEXT_MANAGER_MODEL_ID, CONTEXT_MANAGER_API_KEY)


def _cache_path_for_url(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return BOM_CACHE_DIR / f"{digest}.json"


def _load_bom_cache(url: str) -> Optional[Dict[str, Any]]:
    if not url:
        return None
    path = _cache_path_for_url(url)
    if not path.exists():
        return None
    if BOM_CACHE_TTL_SECONDS:
        age = time.time() - path.stat().st_mtime
        if age > BOM_CACHE_TTL_SECONDS:
            return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _store_bom_cache(url: str, payload: Dict[str, Any]) -> None:
    if not url:
        return
    try:
        BOM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with _cache_path_for_url(url).open("w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass


def _is_under_repos_base(path: str) -> bool:
    try:
        # Resolve both paths to prevent symlink attacks
        resolved_path = Path(path).resolve(strict=False)
        resolved_base = REPOS_BASE.resolve()
        return resolved_path.is_relative_to(resolved_base)
    except AttributeError:
        # Python <3.9 compatibility: manual check
        resolved_path = Path(path).resolve()
        resolved_base = REPOS_BASE.resolve()
        return str(resolved_path).startswith(str(resolved_base))
    except Exception:
        return False

def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

class DocSearchIn(BaseModel):
    query: str
    repo: Optional[str] = None
    k: int = 12
    max_tokens: int = 1200

def _read_text(path: str, max_bytes: int = 100_000) -> str:
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read(max_bytes)
    except Exception:
        return ""

def _find_excerpt(text: str, needle: str, width: int = 400) -> tuple[int, str]:
    if not text:
        return 0, ""
    m = re.search(re.escape(needle), text, re.IGNORECASE)
    if not m:
        # fallback to head
        return 0, text[:width]
    start = max(0, m.start() - width // 3)
    end = min(len(text), m.end() + width // 3)
    return start, text[start:end]

def _gather_paths(base: str, exts: List[str], limit: int) -> List[str]:
    paths = []
    for ext in exts:
        paths.extend(glob.glob(os.path.join(base, f"**/*{ext}"), recursive=True))
        if len(paths) >= limit:
            break
    # Dedup and cap
    seen = set()
    out = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
        if len(out) >= limit:
            break
    return out

@app.post("/doc.search")
def doc_search(inp: DocSearchIn):
    # Local corpus + optional repo scan
    corpus_dir = os.getenv("CORPUS_DIR", os.path.join(os.getcwd(), "apps", "docs", "corpora"))
    include_mem = os.getenv("DOCSEARCH_INCLUDE_MEMORY", "0") == "1"
    mem_dir = os.getenv("MEM_DIR", "/tmp/mem")
    exts = [".md", ".txt", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".go", ".rs", ".java"]
    max_files = int(os.getenv("DOCSEARCH_MAX_FILES", "200"))
    max_bytes = int(os.getenv("DOCSEARCH_MAX_BYTES", "100000"))
    k = max(1, min(100, inp.k))
    query = (inp.query or "").strip()

    search_roots = []
    if os.path.isdir(corpus_dir):
        search_roots.append(corpus_dir)
    if inp.repo and os.path.isdir(inp.repo):
        search_roots.append(inp.repo)
    if include_mem and os.path.isdir(mem_dir):
        search_roots.append(mem_dir)

    candidate_paths: List[str] = []
    for root in search_roots:
        candidate_paths.extend(_gather_paths(root, exts, max_files))

    # Score files by number of matches (very simple)
    scored = []
    for p in candidate_paths[:max_files]:
        txt = _read_text(p, max_bytes)
        if not txt:
            continue
        hits = len(re.findall(re.escape(query), txt, re.IGNORECASE)) if query else 0
        if query and hits == 0:
            continue
        start, excerpt = _find_excerpt(txt, query, width=500)
        scored.append((hits if hits > 0 else 1, p, start, excerpt))

    # Sort by hits desc, then path
    scored.sort(key=lambda t: (-t[0], t[1]))
    results = []
    for i, (_hits, path, start, excerpt) in enumerate(scored[:k]):
        results.append({
            "id": f"doc_{i}",
            "source": "corpus" if corpus_dir in path else "repo",
            "path": path,
            "span": [int(start), int(start + len(excerpt))],
            "digest": digest_text(path + str(start)),
            "text_excerpt": excerpt
        })

    summary = f"DocSearch results for query='{query}' in {len(search_roots)} root(s); returned {len(results)} item(s)."
    return {"chunks": results, "summary": summary}

class FSReadIn(BaseModel):
    path_or_glob: str
    max_bytes: int = 200000
    strategy: str = "head"

@app.post("/fs.read")
def fs_read(inp: FSReadIn):
    paths = glob.glob(inp.path_or_glob)
    files = []
    for p in paths[:10]:
        try:
            with open(p, "r", errors="ignore") as f:
                data = f.read(inp.max_bytes)
            files.append({"path": p, "bytes": len(data), "digest": digest_text(data), "excerpt": data[:1000]})
        except Exception as e:
            files.append({"path": p, "error": str(e)})
    return {"files": files, "summary": f"Read {len(files)} files."}

class CodeSearchIn(BaseModel):
    repo: str
    query: str
    ripgrep: bool = True
    k: int = 200

@app.post("/code.search")
def code_search(inp: CodeSearchIn):
    # Minimal ripgrep wrapper (if installed); otherwise placeholder
    hits = []
    try:
        if inp.ripgrep:
            cmd = ["rg", "-n", "-e", inp.query, inp.repo]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            for line in out.stdout.splitlines()[:inp.k]:
                try:
                    path, line_no, ctx = line.split(":", 2)
                    hits.append({"path": path, "line": int(line_no), "context": ctx[:200]})
                except:
                    pass
    except Exception as e:
        hits.append({"error": f"ripgrep error: {e}"})
    return {"hits": hits, "summary": f"{len(hits)} hits."}

class RepoDescribeIn(BaseModel):
    repo: str
    max_items: int = 40

class CommerceSearchIn(BaseModel):
    query: str
    user_id: Optional[str] = None
    extra_query: Optional[str] = ""
    max_results: int = 5
    country: str = "us"
    language: str = "en"

class MultiPhaseSearchIn(BaseModel):
    query: str
    session_id: str = "default"
    category: Optional[str] = None
    max_vendors_phase1: int = 10
    max_products_phase2: int = 20

class QuickSearchIn(BaseModel):
    query: str
    session_id: str = "default"
    category: Optional[str] = None
    use_cached_vendors: bool = True

class InternetResearchIn(BaseModel):
    query: str
    intent: str = "informational"  # transactional, informational, navigational
    max_results: int = 5
    min_quality: float = 0.5
    max_candidates: int = 15
    human_assist_allowed: bool = True  # Allow CAPTCHA intervention (default: enabled)
    session_id: str = "default"  # Browser session for cookie reuse
    remaining_token_budget: int = 8000  # Token budget from gateway governance (default: 8k)
    force_refresh: bool = False  # If True, bypass caches and force fresh research
    # Research context from Planner with entities/subtasks/research_type
    research_context: Optional[Dict[str, Any]] = None
    # Turn number for research document indexing
    turn_number: int = 0
    # Deep read mode for multi-page content (forums, articles)
    deep_read: bool = False  # If True, read all pages of thread/article
    # Turn directory path for Document IO compliance (enables recipe-based prompts)
    turn_dir_path: Optional[str] = None
    max_pages: int = 5  # Max pages to read in deep_read mode (default 5, can be up to 20)


# ============================================================================
class ComputerClickIn(BaseModel):
    goal: str  # Description of what to click (e.g., "OK button", "Start menu")
    max_attempts: int = 3
    timeout: float = 30.0

class ComputerTypeTextIn(BaseModel):
    text: str  # Text to type
    into: Optional[str] = None  # Optional field to click first
    interval: float = 0.05

class ComputerPressKeyIn(BaseModel):
    key: str  # Key to press (e.g., "enter", "tab", "esc")
    presses: int = 1

class ComputerScrollIn(BaseModel):
    clicks: int  # Number of scroll clicks (positive=up, negative=down)

class ComputerScreenshotIn(BaseModel):
    save_path: Optional[str] = None  # Optional path to save screenshot

class ComputerGetScreenStateIn(BaseModel):
    """Request current screen state as text description."""
    max_elements: int = 20  # Max UI elements to return
    max_text_len: int = 20  # Max text length per element

# Web Vision Agent Models
class WebGetScreenStateIn(BaseModel):
    """Request current page state as text description."""
    session_id: str
    max_elements: int = 20  # Max UI elements to return
    max_text_len: int = 30  # Max text length per element

class WebClickIn(BaseModel):
    """Click UI element in browser."""
    session_id: str
    goal: str  # Description of what to click
    max_attempts: int = 3
    timeout: float = 30.0

class WebTypeTextIn(BaseModel):
    """Type text in browser."""
    session_id: str
    text: str  # Text to type
    into: Optional[str] = None  # Optional field to click first
    interval: float = 0.05

class WebPressKeyIn(BaseModel):
    """Press keyboard key in browser."""
    session_id: str
    key: str  # Key to press (e.g., "Enter", "Tab")
    presses: int = 1
    after_clicking: Optional[str] = None  # Optional field to click/focus before pressing key

class WebScrollIn(BaseModel):
    """Scroll page up/down."""
    session_id: str
    clicks: int  # Number of scroll clicks (positive=down, negative=up)

class WebCaptureContentIn(BaseModel):
    """Capture page content."""
    session_id: str
    format: str = "markdown"  # "markdown" or "html"

class WebNavigateIn(BaseModel):
    """Navigate to URL."""
    session_id: str
    url: str
    wait_for: str = "networkidle"  # "load", "domcontentloaded", "networkidle"

class InterventionResponseIn(BaseModel):
    session_id: str
    intervention_id: str
    action: str  # "solved", "skip", "cancel"
    user_input: str = ""

class SpreadsheetWriteIn(BaseModel):
    repo: str
    rows: List[Dict[str, Any]]
    filename: Optional[str] = None
    format: str = "csv"


class WebFetchIn(BaseModel):
    url: str
    fetch_mode: Optional[str] = "http"


class SourceAggregateIn(BaseModel):
    """Input model for source.aggregate endpoint."""
    source_url: str                    # Required: URL to aggregate
    source_type: str = "auto"          # auto, github, youtube, arxiv, web
    include_issues: bool = False       # GitHub: include issues
    include_prs: bool = False          # GitHub: include PRs
    max_tokens: int = 8000             # Max output tokens (truncate if larger)


class BomNormalizeIn(BaseModel):
    content: str
    source: Optional[str] = None


class BOMBuildIn(BaseModel):
    url: Optional[str] = None
    query: Optional[str] = None
    repo: Optional[str] = None
    filename: Optional[str] = None
    format: str = "csv"
    use_serpapi: bool = False
    serpapi_max_parts: int = 5
    force_refresh: bool = False

@app.post("/repo.describe")
def repo_describe(inp: RepoDescribeIn):
    repo = inp.repo
    if not _is_under_repos_base(repo):
        raise HTTPException(403, f"repo path outside allowed base: {repo}")
    if not os.path.isdir(repo):
        raise HTTPException(400, f"repo path not found: {repo}")
    try:
        entries = []
        for root, dirs, files in os.walk(repo):
            # Shallow listing for performance
            rel = os.path.relpath(root, repo)
            if rel == ".":
                rel = ""
            for d in sorted(dirs)[: inp.max_items - len(entries)]:
                entries.append(os.path.join(rel, d) + "/")
                if len(entries) >= inp.max_items:
                    break
            if len(entries) >= inp.max_items:
                break
            for f in sorted(files)[: inp.max_items - len(entries)]:
                entries.append(os.path.join(rel, f))
                if len(entries) >= inp.max_items:
                    break
            break  # only top level
        # Detect config files
        hints = []
        for name in ["pyproject.toml", "package.json", "requirements.txt", "setup.cfg", "Cargo.toml"]:
            if os.path.exists(os.path.join(repo, name)):
                hints.append(name)
        summary = {
            "top_entries": entries[: inp.max_items],
            "config": hints,
            "repo": repo,
        }
        return summary
    except Exception as e:
        raise HTTPException(500, f"describe error: {e}")

@app.post("/commerce.search_offers")
def commerce_search_offers(inp: CommerceSearchIn):
    try:
        offers = commerce_mcp.search_offers(
            inp.query,
            user_id=inp.user_id,
            extra_query=inp.extra_query or "",
            max_results=max(1, min(inp.max_results or 5, 10)),
            country=(inp.country or "us").lower()[:5],
            language=(inp.language or "en").lower()[:5],
        )
    except Exception as e:
        raise HTTPException(500, f"commerce lookup error: {e}")

    best = commerce_mcp.best_offer(offers)
    summary = f"{len(offers)} offer(s) found for query '{inp.query}'."
    if best and best.get("price") is not None:
        summary += f" Best offer {best['price']} {best.get('currency') or ''} at {best.get('source', '')}."
    return {"offers": offers, "best_offer": best, "summary": summary}

@app.post("/commerce.search_with_recommendations")
async def commerce_search_with_recommendations(inp: MultiPhaseSearchIn):
    """
    Multi-phase deep search: Intelligence gathering + product matching.
    Phase 1 discovers vendors/specs from community, Phase 2 finds matching products.
    """
    try:
        result = await commerce_mcp.search_with_recommendations(
            query=inp.query,
            session_id=inp.session_id,
            category=inp.category,
            max_vendors_phase1=inp.max_vendors_phase1,
            max_products_phase2=inp.max_products_phase2
        )
        return result
    except Exception as e:
        logger.error(f"[commerce.search_with_recommendations] Error: {e}")
        raise HTTPException(500, f"Multi-phase search error: {e}")

@app.post("/commerce.quick_search")
async def commerce_quick_search(inp: QuickSearchIn):
    """
    Quick product search: Skip Phase 1, use cached vendors or defaults.
    Faster but no community-validated recommendations.
    """
    try:
        result = await commerce_mcp.quick_search(
            query=inp.query,
            session_id=inp.session_id,
            category=inp.category,
            use_cached_vendors=inp.use_cached_vendors
        )
        return result
    except Exception as e:
        logger.error(f"[commerce.quick_search] Error: {e}")
        raise HTTPException(500, f"Quick search error: {e}")

@app.post("/internet.research")
async def internet_research(inp: InternetResearchIn):
    """
    Adaptive internet research - automatically selects optimal strategy.

    NEW (2025-11-15): Single adaptive system that selects QUICK/STANDARD/DEEP
    based on query analysis and session intelligence cache.

    Strategies:
    - QUICK: Fast lookup, no intelligence (30-60s)
    - STANDARD: Reuse cached intelligence (60-120s)
    - DEEP: Full intelligence + products (120-180s)

    Features:
    - LLM-powered strategy selection
    - Session intelligence caching
    - Human-assisted CAPTCHA solving
    - Real-time progress events
    """
    try:
        # Rotate logs for new query (archive previous query's logs)
        rotate_logs_for_query(query_id=inp.session_id, query_preview=inp.query[:60])

        logger.info(f"[internet.research] ADAPTIVE - Query: {inp.query[:60]}...")

        from apps.services.tool_server.internet_research_mcp import adaptive_research
        from apps.services.tool_server.research_event_emitter import ResearchEventEmitter

        # Create event emitter with gateway callback
        emitter = ResearchEventEmitter(inp.session_id, send_research_event_to_gateway)

        # Log research_context if provided
        if inp.research_context:
            logger.info(
                f"[internet.research] Research context: "
                f"intent={inp.research_context.get('intent', 'NOT SET')}, "
                f"target_url={inp.research_context.get('intent_metadata', {}).get('target_url', 'NOT SET')}, "
                f"entities={len(inp.research_context.get('entities', []))}, "
                f"subtasks={len(inp.research_context.get('subtasks', []))}, "
                f"research_type={inp.research_context.get('research_type', 'general')}"
            )
        else:
            logger.info(f"[internet.research] NO research_context provided!")

        # Call adaptive research
        result = await adaptive_research(
            query=inp.query,
            research_goal=None,  # Will default to query
            session_id=inp.session_id,
            human_assist_allowed=inp.human_assist_allowed,
            event_emitter=emitter,
            force_strategy=None,  # Auto-select strategy
            force_refresh=inp.force_refresh,  # Pass retry cache bypass flag
            research_context=inp.research_context,  # Pass entities/subtasks from Planner
            turn_number=inp.turn_number,  # For research document indexing
            deep_read=inp.deep_read,  # Multi-page reading mode
            max_pages=inp.max_pages,  # Max pages for deep read
            turn_dir_path=inp.turn_dir_path  # Turn directory for Document IO compliance
        )

        logger.info(
            f"[internet.research] Complete: {result['strategy_used'].upper()} strategy, "
            f"{result['stats'].get('sources_checked', 0)} sources"
        )

        # Check if result is an error response (rate limited, research failed, etc.)
        if "error" in result:
            logger.warning(f"[internet.research] Error response: {result.get('error')}")
            return {
                "query": result["query"],
                "strategy": result["strategy_used"],
                "strategy_reason": result.get("strategy_reason", result.get("error", "unknown")),
                "findings": [],
                "synthesis": {},
                "stats": result.get("stats", {}),
                "intelligence_cached": result.get("intelligence_cached", False),
                "error": result["error"],
                "message": result.get("message", "Research failed")
            }

        # Return in format expected by Gateway
        return {
            "query": result["query"],
            "strategy": result["strategy_used"],
            "strategy_reason": result.get("strategy_reason", "unknown"),
            "findings": result.get("results", {}).get("findings", []),
            "synthesis": result.get("results", {}).get("synthesis", {}),
            "stats": result["stats"],
            "intelligence_cached": result["intelligence_cached"]
        }

    except Exception as e:
        logger.error(f"[internet.research] Exception: {e}", exc_info=True)
        raise HTTPException(500, f"adaptive research error: {e}")


@app.post("/internet.research/stream")
async def internet_research_stream(request: Request, inp: InternetResearchIn):
    """
    Adaptive internet research with Server-Sent Events (SSE) streaming.

    This endpoint streams research events in real-time to clients using SSE protocol.
    Used by v4.0 document-driven flow for research monitor integration.

    SSE Format:
    event: research_event
    data: {"type": "search_started", "session_id": "...", "data": {...}}

    Final event contains full result:
    event: research_complete
    data: {"query": "...", "strategy": "...", "findings": [...], ...}
    """
    # Rotate logs for new query (archive previous query's logs)
    rotate_logs_for_query(query_id=inp.session_id, query_preview=inp.query[:60])

    async def event_generator():
        """Generate SSE events from research progress."""
        import asyncio
        import json
        from apps.services.tool_server.internet_research_mcp import adaptive_research
        from apps.services.tool_server.research_event_emitter import ResearchEventEmitter

        # Queue to buffer events
        event_queue = asyncio.Queue()

        # Event emitter callback - put events in queue
        async def queue_callback(event: dict):
            await event_queue.put(event)

        # Create event emitter with queue callback
        emitter = ResearchEventEmitter(inp.session_id, queue_callback)

        # Log research_context if provided (for streaming endpoint)
        if inp.research_context:
            logger.info(
                f"[internet.research/stream] Research context: "
                f"entities={len(inp.research_context.get('entities', []))}, "
                f"subtasks={len(inp.research_context.get('subtasks', []))}, "
                f"research_type={inp.research_context.get('research_type', 'general')}"
            )

        # Start research in background task
        async def run_research():
            try:
                result = await adaptive_research(
                    query=inp.query,
                    research_goal=None,
                    session_id=inp.session_id,
                    human_assist_allowed=inp.human_assist_allowed,
                    event_emitter=emitter,
                    force_strategy=None,
                    force_refresh=inp.force_refresh,  # Pass retry cache bypass flag
                    research_context=inp.research_context,  # Pass entities/subtasks from Planner
                    turn_number=inp.turn_number,  # For research document indexing
                    turn_dir_path=inp.turn_dir_path  # Turn directory for Document IO compliance
                )

                # Send final result as completion event
                await event_queue.put({
                    "type": "research_complete",
                    "session_id": inp.session_id,
                    "data": {
                        "query": result["query"],
                        "strategy": result.get("strategy_used", "unknown"),
                        "strategy_reason": result.get("strategy_reason", "No strategy reason provided"),
                        "strategy_decision": result.get("strategy_decision", {}),
                        "findings": result.get("results", {}).get("findings", []),
                        "synthesis": result.get("results", {}).get("synthesis", {}),
                        "stats": result.get("stats", {}),
                        "intelligence_cached": result.get("intelligence_cached", False)
                    }
                })
            except Exception as e:
                logger.error(f"[internet.research/stream] Research error: {e}", exc_info=True)
                await event_queue.put({
                    "type": "research_error",
                    "session_id": inp.session_id,
                    "data": {"error": str(e)}
                })
            finally:
                # Signal completion
                await event_queue.put(None)

        # Start research task
        research_task = asyncio.create_task(run_research())

        try:
            # Stream events as they arrive
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    logger.info(f"[internet.research/stream] Client disconnected")
                    research_task.cancel()
                    break

                # Get next event (timeout to check disconnect periodically)
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Send keep-alive comment
                    yield ": keep-alive\n\n"
                    continue

                # None signals completion
                if event is None:
                    break

                # Format as SSE
                event_type = event.get("type", "research_event")
                event_data = json.dumps(event)

                yield f"event: {event_type}\n"
                yield f"data: {event_data}\n\n"

        finally:
            # Ensure task is cleaned up
            if not research_task.done():
                research_task.cancel()
                try:
                    await research_task
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


class VendorCatalogIn(BaseModel):
    vendor_url: str
    vendor_name: str
    category: str = "all"
    max_items: int = 20
    session_id: str = "default"


@app.post("/vendor.explore_catalog")
async def vendor_explore_catalog(inp: VendorCatalogIn):
    """
    Deep-crawl vendor catalog to extract all available products/listings.

    Example:
        POST /vendor.explore_catalog
        {
            "vendor_url": "https://poppybeehamstery.com/",
            "vendor_name": "Poppy Bee Hamstery",
            "category": "available",
            "max_items": 20,
            "session_id": "default"
        }

    Returns:
        {
            "vendor_name": "Poppy Bee Hamstery",
            "items_found": 8,
            "items": [...],
            "contact_info": {...}
        }
    """
    from apps.services.tool_server.vendor_catalog_mcp import explore_catalog

    logger.info(
        f"[VendorCatalog] Exploring {inp.vendor_name} catalog "
        f"(category={inp.category}, max_items={inp.max_items})"
    )

    try:
        result = await explore_catalog(
            vendor_url=inp.vendor_url,
            vendor_name=inp.vendor_name,
            category=inp.category,
            max_items=inp.max_items,
            session_id=inp.session_id
        )

        logger.info(
            f"[VendorCatalog] Found {result['items_found']} items "
            f"across {result['pages_crawled']} pages"
        )

        return result

    except Exception as e:
        logger.error(f"[VendorCatalog] Exploration failed: {e}", exc_info=True)
        return {
            "vendor_name": inp.vendor_name,
            "vendor_url": inp.vendor_url,
            "items_found": 0,
            "pages_crawled": 0,
            "items": [],
            "error": str(e),
            "contact_info": {},
            "metadata": {
                "category": inp.category,
                "crawl_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
        }


@app.post("/internal/intervention_response")
async def handle_intervention_response(inp: InterventionResponseIn):
    """
    Receive intervention response from Gateway WebSocket.

    This resolves pending human interventions using the captcha_intervention system.
    """
    from apps.services.tool_server.captcha_intervention import get_pending_intervention, remove_pending_intervention

    logger.info(
        f"[InterventionResponse] Received for session={inp.session_id}, "
        f"intervention={inp.intervention_id}, action={inp.action}"
    )

    # Get intervention from global registry
    intervention = get_pending_intervention(inp.intervention_id)
    if not intervention:
        logger.warning(
            f"[InterventionResponse] No pending intervention found: {inp.intervention_id}"
        )
        return {"status": "error", "message": "Intervention not found or already resolved"}

    # Mark resolved based on action
    success = inp.action in ["solved", "continue", "resolved"]
    skip_reason = None if success else inp.action

    intervention.mark_resolved(
        success=success,
        cookies=None,  # Cookies are saved directly by crawler session manager
        skip_reason=skip_reason
    )

    # Clean up from registry after a short delay (allow waiting tasks to wake up)
    # Don't remove immediately - the waiting task needs to read resolution status
    logger.info(
        f"[InterventionResponse] Marked {inp.intervention_id} as "
        f"{'resolved successfully' if success else f'skipped ({skip_reason})'}"
    )

    return {"status": "success", "resolved": success}

@app.get("/captcha.pending")
def get_pending_captchas():
    """Get all pending captcha challenges requiring human intervention."""
    try:
        from apps.services.tool_server import captcha_intervention
        challenges = captcha_intervention.get_pending_challenges()
        return {
            "pending_count": len(challenges),
            "challenges": challenges
        }
    except Exception as e:
        raise HTTPException(500, f"captcha queue error: {e}")

@app.post("/captcha.solve")
def solve_captcha(challenge_id: str):
    """
    Launch visible browser for user to manually solve captcha.

    User will see browser window open, solve the challenge, then close window.
    Session/cookies will be saved for retry.
    """
    try:
        from apps.services.tool_server import captcha_intervention
        result = captcha_intervention.launch_manual_solver(challenge_id)

        if not result["success"]:
            raise HTTPException(500, result.get("error", "Unknown error"))

        return {
            "success": True,
            "session_file": result["session_file"],
            "message": "Captcha solved successfully. Session saved for retry."
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"captcha solve error: {e}")

@app.post("/captcha.retry")
def retry_captcha(challenge_id: str):
    """
    Retry fetching URL after manual captcha intervention.

    Uses saved session from manual solve.
    """
    try:
        from apps.services.tool_server import captcha_intervention
        result = captcha_intervention.retry_with_intervention(challenge_id)

        if not result["success"]:
            raise HTTPException(500, result.get("error", "Retry failed"))

        return {
            "success": True,
            "url": result["url"],
            "title": result.get("title", ""),
            "content_length": len(result.get("text_content", "")),
            "message": "Fetch successful with saved session"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"captcha retry error: {e}")

@app.post("/interventions/{intervention_id}/resolve")
async def resolve_intervention(intervention_id: str, request: Request):
    """
    Resolve intervention request from research monitor.

    Called by research_monitor.html when user clicks "I Solved It".
    Routes to correct intervention system (captcha_intervention._PENDING_INTERVENTIONS).

    Body:
        {
            "resolved": bool,  # True if solved, False if skipped
            "cookies": list[dict] | null  # Optional cookie data
        }
    """
    from apps.services.tool_server.captcha_intervention import get_pending_intervention
    from fastapi.responses import JSONResponse

    try:
        body = await request.json()
        resolved = body.get("resolved", True)
        cookies = body.get("cookies", None)

        intervention = get_pending_intervention(intervention_id)
        if not intervention:
            logger.warning(f"[Intervention] Unknown intervention: {intervention_id}")
            return JSONResponse(
                status_code=404,
                content={"error": "Intervention not found", "intervention_id": intervention_id}
            )

        intervention.mark_resolved(
            success=resolved,
            cookies=cookies,
            skip_reason=None if resolved else "user_skipped"
        )

        logger.info(
            f"[Intervention] Resolved via API: {intervention_id} "
            f"(success={resolved})"
        )

        return {
            "status": "resolved",
            "intervention_id": intervention_id,
            "success": resolved
        }

    except Exception as e:
        logger.error(f"[Intervention] Error resolving {intervention_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/docs.write_spreadsheet")
def docs_write_spreadsheet(inp: SpreadsheetWriteIn):
    if not inp.rows:
        raise HTTPException(400, "rows must be a non-empty list")
    repo = inp.repo
    if not _is_under_repos_base(repo):
        raise HTTPException(403, f"repo path outside allowed base: {repo}")
    if not os.path.isdir(repo):
        raise HTTPException(400, f"repo path not found: {repo}")
    fmt = (inp.format or "csv").lower()
    if fmt not in {"csv", "ods"}:
        raise HTTPException(400, f"unsupported format '{inp.format}'")
    try:
        result = spreadsheet_mcp.write_spreadsheet(
            rows=inp.rows,
            repo_root=repo,
            filename=inp.filename,
            format=fmt,
        )
    except Exception as e:
        raise HTTPException(500, f"write spreadsheet error: {e}")
    return result


@app.post("/web.fetch_text")
def web_fetch_text(inp: WebFetchIn):
    if not inp.url or not inp.url.startswith(("http://", "https://")):
        raise HTTPException(400, "url must start with http:// or https://")
    mode = (inp.fetch_mode or "http").lower()
    try:
        fetched = fetch_url_basic(inp.url, fetch_mode=mode)
        raw_html = fetched.get("raw_html") or ""
        content = extract_main_content(raw_html) if raw_html else ""
        return {
            "url": fetched.get("url") or inp.url,
            "status": fetched.get("status"),
            "title": fetched.get("title"),
            "raw_html": raw_html[:200000],
            "content": content[:200000],
        }
    except Exception as e:
        raise HTTPException(500, f"web fetch error: {e}")


@app.post("/source.aggregate")
async def source_aggregate(inp: SourceAggregateIn):
    """
    Aggregate content from GitHub repos, YouTube videos, arXiv papers, or web pages.

    Uses onefilellm to fetch and structure content for LLM consumption.

    Example:
        POST /source.aggregate
        {
            "source_url": "https://github.com/jimmc414/onefilellm",
            "source_type": "github"
        }

    Returns:
        {
            "status": "success",
            "source_url": "...",
            "source_type": "github",
            "content": "... aggregated content ...",
            "content_length": 12345
        }
    """
    if not inp.source_url or not inp.source_url.startswith(("http://", "https://")):
        raise HTTPException(400, "source_url must start with http:// or https://")

    try:
        logger.info(f"[source.aggregate] Aggregating: {inp.source_url[:80]}...")

        url = inp.source_url.lower()

        # Detect source type if auto
        source_type = inp.source_type.lower()
        if source_type == "auto":
            if "github.com" in url:
                source_type = "github"
            elif "youtube.com" in url or "youtu.be" in url:
                source_type = "youtube"
            elif "arxiv.org" in url:
                source_type = "arxiv"
            else:
                source_type = "web"

        # Import and call appropriate onefilellm function based on source type
        content = ""
        try:
            if source_type == "github":
                from onefilellm import process_github_repo
                content = process_github_repo(inp.source_url)

            elif source_type == "youtube":
                from onefilellm import fetch_youtube_transcript
                content = fetch_youtube_transcript(inp.source_url)

            elif source_type == "arxiv":
                from onefilellm import process_arxiv_pdf
                content = process_arxiv_pdf(inp.source_url)

            else:  # web
                from onefilellm import crawl_and_extract_text
                result = crawl_and_extract_text(
                    inp.source_url,
                    max_depth=1,
                    include_pdfs=True,
                    ignore_epubs=True
                )
                content = result.get("content", "") if isinstance(result, dict) else str(result)

        except ImportError as e:
            raise HTTPException(
                501,
                f"onefilellm not installed or missing function. Run: pip install onefilellm. Error: {e}"
            )

        # Truncate if needed (approx 4 chars per token)
        max_chars = inp.max_tokens * 4
        truncated = False
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n[Content truncated...]"
            truncated = True

        logger.info(
            f"[source.aggregate] Complete: {source_type}, "
            f"{len(content)} chars, truncated={truncated}"
        )

        return {
            "status": "success",
            "source_url": inp.source_url,
            "source_type": source_type,
            "content": content,
            "content_length": len(content),
            "truncated": truncated,
            "token_count": len(content) // 4,  # Approximate token count
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[source.aggregate] Error: {e}", exc_info=True)
        raise HTTPException(500, f"source.aggregate error: {e}")


@app.post("/bom.normalize")
def bom_normalize(inp: BomNormalizeIn):
    try:
        rows = bom_normalizer.normalize_bom_text(inp.content or "", source=inp.source)
    except Exception as e:
        raise HTTPException(500, f"normalize error: {e}")
    return {"rows": rows, "count": len(rows)}


@app.post("/bom.build")
def bom_build(inp: BOMBuildIn):
    if not inp.url and not inp.query:
        raise HTTPException(400, "url or query is required")

    status = "ok"
    messages: List[str] = []
    rows: List[Dict[str, Any]] = []
    base_rows: List[Dict[str, Any]] = []
    spreadsheet_path: Optional[str] = None
    source_url = inp.url
    title = ""
    stage_path: Optional[str] = None
    cache_hit = False
    serpapi_used = False
    serpapi_calls = 0
    priced_rows = 0

    if inp.url and not inp.force_refresh:
        cached = _load_bom_cache(inp.url)
        if cached:
            cache_hit = True
            base_rows = cached.get("rows", [])
            rows = copy.deepcopy(base_rows)
            title = cached.get("title") or ""
            source_url = cached.get("source_url") or inp.url
            stage_path = cached.get("stage_path")
            messages.append("Loaded normalized BOM from cache.")

    if inp.url and not rows:
        try:
            fetched = fetch_url_basic(inp.url, fetch_mode="http")
            source_url = fetched.get("url") or inp.url
            status_code = int(fetched.get("status") or 0)
            if status_code >= 400 or status_code == 0:
                status = "fetch_failed"
                messages.append(f"HTTP {status_code}")
            raw_html = fetched.get("raw_html") or ""
            title = fetched.get("title") or title or ""
            content = extract_main_content(raw_html) if raw_html else ""
            if raw_html:
                try:
                    stage_path = stage_scrape_result(
                        str(SCRAPE_STAGING_DIR),
                        source_url,
                        raw_html,
                        content,
                        {"title": title},
                    )
                except Exception as stage_err:
                    messages.append(f"Stage error: {stage_err}")
            base_rows = bom_normalizer.normalize_bom_text(content, source=source_url)
            rows = copy.deepcopy(base_rows)
            if not rows:
                status = "fetch_failed"
                messages.append("No structured BOM rows detected in fetched content.")
            else:
                _store_bom_cache(
                    source_url,
                    {
                        "rows": base_rows,
                        "title": title,
                        "source_url": source_url,
                        "stage_path": stage_path,
                        "fetched_at": datetime.datetime.utcnow().strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        "cache_version": 1,
                    },
                )
        except Exception as e:
            raise HTTPException(500, f"fetch/normalize error: {e}")

    if not rows and inp.query:
        try:
            query = inp.query
            animal_keywords = ["hamster", "guinea pig", "rabbit", "cat", "dog"]
            if any(keyword in query.lower() for keyword in animal_keywords):
                query = f"{query} live pet"
            offers = commerce_mcp.search_offers(
                query,
                max_results=max(1, min(inp.serpapi_max_parts, SERPAPI_MAX_RESULTS)),
                country=SERPAPI_COUNTRY,
                language=SERPAPI_LANGUAGE,
                pause=SERPAPI_PAUSE,
            )
            serpapi_calls += 1
            serpapi_used = True
            for offer in offers:
                rows.append(
                    {
                        "part": offer.get("title") or inp.query,
                        "quantity": 1,
                        "price": offer.get("price"),
                        "price_text": offer.get("price_text"),
                        "currency": offer.get("currency"),
                        "retailer": offer.get("source"),
                        "price_link": offer.get("link"),
                        "pricing_source": "serpapi",
                        "notes": "SerpAPI query fallback",
                    }
                )
            if rows:
                status = (
                    "ok"
                    if any(r.get("price") is not None for r in rows)
                    else "pricing_missing"
                )
                messages.append("Built BOM rows from SerpAPI query fallback.")
            else:
                status = "fetch_failed"
                messages.append("SerpAPI returned no offers for query fallback.")
        except Exception as e:
            status = "fetch_failed"
            messages.append(f"Query fallback failed: {e}")

    if rows and inp.use_serpapi and status != "fetch_failed":
        serpapi_used = True
        limit = max(1, min(inp.serpapi_max_parts, len(rows)))
        for row in rows[:limit]:
            part_name = (row.get("part") or "").strip()
            if not part_name:
                continue
            extra = row.get("notes") or ""

            # REFLEXION LOOP: Retry with LLM-refined queries if initial search fails
            max_attempts = 3
            current_query = part_name
            offer = None

            for attempt in range(1, max_attempts + 1):
                try:
                    offers = commerce_mcp.search_offers(
                        current_query,
                        max_results=max(1, SERPAPI_MAX_RESULTS),
                        extra_query=str(extra) if attempt == 1 else "",  # Use extra only on first try
                        country=SERPAPI_COUNTRY,
                        language=SERPAPI_LANGUAGE,
                        pause=SERPAPI_PAUSE,
                    )
                    serpapi_calls += 1
                except Exception as e:
                    messages.append(f"Pricing lookup failed for '{part_name}' (attempt {attempt}): {e}")
                    break

                # Try to get best offer
                offer = commerce_mcp.best_offer(offers) or (offers[0] if offers else None)

                if offer:
                    # Success! Found a priced offer
                    messages.append(f"Found pricing for '{part_name}' after {attempt} attempt(s)")
                    break

                # No offer found - use LLM to refine query for next attempt
                if attempt < max_attempts:
                    results_summary = f"Found {len(offers)} offers but none had valid pricing" if offers else "No offers found"
                    current_query = reflection_engine.llm_refine_query(
                        original_query=part_name,
                        search_context=f"product pricing for BOM item: {part_name} (notes: {extra})" if extra else f"product pricing for BOM item: {part_name}",
                        previous_results_summary=results_summary,
                        attempt_number=attempt + 1
                    )
                    messages.append(f"Refining search for '{part_name}': '{current_query}'")

            # Apply pricing if we found an offer
            if offer:
                priced_rows += 1
                if offer.get("price") is not None:
                    row["price"] = offer.get("price")
                if offer.get("price_text"):
                    row["price_text"] = offer.get("price_text")
                if offer.get("currency"):
                    row["currency"] = offer.get("currency")
                row["retailer"] = offer.get("source")
                row["price_link"] = offer.get("link")
                row["pricing_source"] = "serpapi"
        if priced_rows == 0:
            status = "pricing_missing"
            messages.append("SerpAPI enrichment returned no priced offers.")
        elif priced_rows < len(rows):
            status = "pricing_missing"
            missing = len(rows) - priced_rows
            messages.append(f"Pricing missing for {missing} item(s).")

    if rows and inp.repo:
        repo_path = Path(inp.repo)
        if not _is_under_repos_base(str(repo_path)):
            raise HTTPException(403, f"repo outside allowed base: {inp.repo}")
        try:
            sheet = spreadsheet_mcp.write_spreadsheet(
                rows,
                repo_root=str(repo_path),
                filename=inp.filename,
                format=inp.format,
            )
            spreadsheet_path = sheet.get("path")
            messages.append(f"Spreadsheet saved to {spreadsheet_path}.")
        except Exception as e:
            status = "spreadsheet_error"
            messages.append(f"Spreadsheet error: {e}")

    return {
        "status": status,
        "message": "; ".join(messages).strip(),
        "rows": rows,
        "spreadsheet_path": spreadsheet_path,
        "source_url": source_url,
        "title": title,
        "pricing_calls": serpapi_calls,
        "cache_hit": cache_hit,
        "serpapi_used": serpapi_used,
        "priced_rows": priced_rows,
        "stage_path": stage_path,
        "normalized_rows": len(base_rows) if base_rows else len(rows),
    }


class PurchasingLookupIn(BaseModel):
    query: str
    extra_query: Optional[str] = None
    max_results: int = 6
    country: str = "us"
    language: str = "en"
    pause: float = 0.6
    user_id: Optional[str] = None


@app.post("/purchasing.lookup")
def purchasing_lookup(inp: PurchasingLookupIn):
    try:
        return purchasing_mcp.lookup(
            inp.query,
            max_results=max(1, min(10, inp.max_results)),
            extra_query=inp.extra_query or "",
            country=inp.country or "us",
            language=inp.language or "en",
            pause=max(0.1, float(inp.pause)),
            user_id=inp.user_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"purchasing lookup error: {e}")

class ResearchOrchestrateIn(BaseModel):
    query: str
    refinements: Optional[Dict[str, Any]] = None
    max_results: int = 6
    verify_top_n: int = 3
    use_cache: bool = True
    user_preferences: Optional[Dict[str, Any]] = None
    profile_id: str = "default"  # User profile for memory persistence

# DEPRECATED (2025-11-14): Use /internet.research instead (supports human-assist for CAPTCHAs)
# @app.post("/research.orchestrate")
# def research_orchestrate_endpoint(inp: ResearchOrchestrateIn):
#     """
#     DEPRECATED: Use internet.research instead.
#     This endpoint is kept for backward compatibility but will be removed.
#     """
#     try:
#         return research_orchestrator_mcp.research_orchestrate(
#             query=inp.query,
#             refinements=inp.refinements,
#             max_results=inp.max_results,
#             verify_top_n=inp.verify_top_n,
#             use_cache=inp.use_cache,
#             user_preferences=inp.user_preferences,
#             profile_id=inp.profile_id
#         )
#     except Exception as e:
#         raise HTTPException(500, f"research orchestration error: {e}")

class SearchOrchestrateIn(BaseModel):
    query: str
    intent: Optional[str] = None  # transactional, informational, navigational
    max_results: int = 10
    use_cache: bool = True
    profile_id: str = "default"

@app.post("/search.orchestrate")
async def search_orchestrate_endpoint(inp: SearchOrchestrateIn):
    """
    Smart search orchestrator with LLM-powered query expansion.

    Automatically:
    1. Expands query into multiple search angles using LLM
    2. Checks cache for each angle
    3. Executes uncached searches in parallel
    4. Merges and returns comprehensive results

    This is the recommended tool for Coordinator to use for search tasks.
    """
    try:
        return await search_orchestrator_mcp.search_orchestrate(
            query=inp.query,
            intent=inp.intent,
            max_results=inp.max_results,
            use_cache=inp.use_cache,
            profile_id=inp.profile_id
        )
    except Exception as e:
        raise HTTPException(500, f"search orchestration error: {e}")

class SearchGoalIn(BaseModel):
    query: str
    success_criteria: Dict[str, Any]
    max_retries: int = 3

class PersistentSearchIn(BaseModel):
    search_goals: List[SearchGoalIn]

@app.post("/research_mcp.orchestrate")
async def research_mcp_orchestrate_endpoint(inp: PersistentSearchIn):
    """
    Persistent multi-goal search that retries until ALL goals are met.
    Designed for queries like 'find Syrian hamster breeder AND hamster for sale'.
    """
    try:
        # Convert Pydantic models to dicts
        goals_list = [goal.dict() for goal in inp.search_goals]
        return await research_mcp.orchestrate(search_goals=goals_list)
    except Exception as e:
        raise HTTPException(500, f"persistent search error: {e}")

class MemCreateIn(BaseModel):
    title: str
    tags: Optional[List[str]] = None
    body_md: str
    ttl_days: Optional[int] = None
    importance: str = "normal"
    scope: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    user: Optional[str] = None
    session_id: Optional[str] = None
    source_turn_ids: Optional[List[str]] = None
    source: str = "agent"

class SearchPreferenceIn(BaseModel):
    user_id: str
    key: str
    value: str
    category: str

@app.post("/memory.create")
def memory_create(inp: MemCreateIn):
    store = get_memory_store(inp.user)
    result = store.save_memory(
        title=inp.title,
        tags=inp.tags,
        body_md=inp.body_md,
        scope=inp.scope,
        ttl_days=inp.ttl_days,
        importance=inp.importance,
        source=inp.source,
        metadata=inp.metadata,
        session_id=inp.session_id,
        source_turn_ids=inp.source_turn_ids,
    )
    record = result.get("record") or {}
    return {
        "ok": True,
        "memory_id": record.get("id"),
        "scope": result.get("scope"),
        "path": result.get("path"),
        "record": record,
        "embedding_ids": [],
    }

@app.post("/memory.save_search_preference")
def save_search_preference(inp: SearchPreferenceIn):
    store = get_memory_store(inp.user_id)
    result = store.save_search_preference(
        key=inp.key,
        value=inp.value,
        category=inp.category,
    )
    return {"ok": True, "result": result}

class MemQueryIn(BaseModel):
    query: str
    k: int = 8
    scope: Optional[str] = None
    min_score: float = 0.0
    include_body: bool = True
    user: Optional[str] = None

@app.post("/memory.query")
def memory_query(inp: MemQueryIn):
    store = get_memory_store(inp.user)
    items = store.query(
        inp.query,
        k=max(1, int(inp.k)),
        scope=inp.scope,
        min_score=float(inp.min_score),
        include_body=bool(inp.include_body),
    )
    return {"items": items}


class ProjectMemoryInitIn(BaseModel):
    user_id: str
    project_path: str
    scan_repo: bool = True


@app.post("/memory.initialize_project")
def memory_initialize_project(inp: ProjectMemoryInitIn):
    """Initialize memory-bank for a project."""
    try:
        result = initialize_project_memory_bank(
            user_id=inp.user_id,
            project_path=inp.project_path,
            scan_repo=inp.scan_repo,
        )
        return result
    except Exception as e:
        raise HTTPException(500, f"Project initialization error: {e}")


class ProjectMemoryLoadIn(BaseModel):
    user_id: str
    project_path: str


@app.post("/memory.load_project")
def memory_load_project(inp: ProjectMemoryLoadIn):
    """Load memory-bank files for a project."""
    try:
        files = load_project_memory_bank(
            user_id=inp.user_id,
            project_path=inp.project_path,
        )
        metadata = get_project_metadata(
            user_id=inp.user_id,
            project_path=inp.project_path,
        )
        return {
            "files": files,
            "metadata": metadata,
            "initialized": len(files) > 0,
        }
    except Exception as e:
        raise HTTPException(500, f"Project load error: {e}")


class ProjectListIn(BaseModel):
    user_id: str


@app.post("/memory.list_projects")
def memory_list_projects(inp: ProjectListIn):
    """List all projects with memory-banks for a user."""
    try:
        projects = list_user_projects(user_id=inp.user_id)
        return {"projects": projects, "count": len(projects)}
    except Exception as e:
        raise HTTPException(500, f"Project list error: {e}")


# ========================================
# Unified Memory MCP Tools (Tier 2)
# ========================================

class UnifiedMemorySearchIn(BaseModel):
    query: str
    topic_filter: Optional[str] = None
    content_types: Optional[List[str]] = None
    scope: Optional[str] = None  # None = search all scopes; 'new', 'user', 'global' to filter
    session_id: Optional[str] = None
    min_quality: float = 0.3
    k: int = 10


@app.post("/memory.unified_search")
async def memory_unified_search(inp: UnifiedMemorySearchIn):
    """
    Unified memory search across all sources.

    Searches: research index, turn index, memory store, site knowledge.
    Returns ranked results with source attribution.
    """
    try:
        from apps.services.tool_server.memory_mcp import get_memory_mcp, MemorySearchRequest

        mcp = get_memory_mcp(inp.session_id)
        request = MemorySearchRequest(
            query=inp.query,
            topic_filter=inp.topic_filter,
            content_types=inp.content_types,
            scope=inp.scope,
            session_id=inp.session_id,
            min_quality=inp.min_quality,
            k=inp.k
        )

        results = await mcp.search(request)
        return {
            "status": "success",
            "results": [r.to_dict() for r in results],
            "count": len(results)
        }
    except Exception as e:
        raise HTTPException(500, f"Unified search error: {e}")


class UnifiedMemorySaveIn(BaseModel):
    title: str
    content: str
    doc_type: str
    tags: List[str] = []
    scope: str = "new"  # New data starts at 'new' scope per MEMORY_ARCHITECTURE.md
    session_id: Optional[str] = None


@app.post("/memory.unified_save")
async def memory_unified_save(inp: UnifiedMemorySaveIn):
    """
    Save new knowledge to unified memory.

    Supports: preferences, facts, notes.
    """
    try:
        from apps.services.tool_server.memory_mcp import get_memory_mcp, MemorySaveRequest

        mcp = get_memory_mcp(inp.session_id)
        request = MemorySaveRequest(
            title=inp.title,
            content=inp.content,
            doc_type=inp.doc_type,
            tags=inp.tags,
            scope=inp.scope,
            session_id=inp.session_id
        )

        result = await mcp.save(request)
        return result
    except Exception as e:
        raise HTTPException(500, f"Unified save error: {e}")


class UnifiedMemoryRetrieveIn(BaseModel):
    doc_path: Optional[str] = None
    doc_id: Optional[str] = None


@app.post("/memory.unified_retrieve")
async def memory_unified_retrieve(inp: UnifiedMemoryRetrieveIn):
    """
    Retrieve a specific document by path or ID.
    """
    try:
        from apps.services.tool_server.memory_mcp import get_memory_mcp

        mcp = get_memory_mcp()
        result = await mcp.retrieve(doc_path=inp.doc_path, doc_id=inp.doc_id)
        return result
    except Exception as e:
        raise HTTPException(500, f"Unified retrieve error: {e}")


class FileCreateIn(BaseModel):
    repo: str
    file_path: str
    content: str
    mode: str = "fail_if_exists"

@app.post("/file.create")
def file_create(inp: FileCreateIn):
    abspath = os.path.join(inp.repo, inp.file_path)
    if os.path.exists(abspath) and inp.mode == "fail_if_exists":
        raise HTTPException(409, "File already exists")
    os.makedirs(os.path.dirname(abspath), exist_ok=True)
    with open(abspath, "w") as f:
        f.write(inp.content)
    # no git here; see git.commit
    return {"path": abspath, "sha": digest_text(inp.content), "diff_excerpt": inp.content[:300]}

class CodePatchIn(BaseModel):
    repo: str
    file_path: str
    content: str  # full-file content to write (simplified apply_patch)
    mode: str = "create_or_replace"  # future: unified diff support

@app.post("/code.apply_patch")
def code_apply_patch(inp: CodePatchIn):
    # Simplified patch: write content to the given path under repo
    abspath = os.path.join(inp.repo, inp.file_path)
    try:
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "w") as f:
            f.write(inp.content)
        return {"path": abspath, "bytes": len(inp.content), "sha": digest_text(inp.content)}
    except Exception as e:
        raise HTTPException(500, f"apply_patch error: {e}")

class GitCommitIn(BaseModel):
    repo: str
    message: str
    add_paths: List[str]

class VerifyProductIn(BaseModel):
    html_content: str
    query: str

@app.post("/git.commit")
def git_commit(inp: GitCommitIn):
    try:
        subprocess.run(["git", "-C", inp.repo, "add", *inp.add_paths], check=True)
        out = subprocess.run(["git", "-C", inp.repo, "commit", "-m", inp.message],
                             check=True, capture_output=True, text=True)
        shortlog = out.stdout.splitlines()[-1] if out.stdout else "committed"
        return {"commit_id": shortlog, "shortlog": shortlog}
    except Exception as e:
        raise HTTPException(500, f"git error: {e}")

@app.post("/llm.verify_product")
def verify_product(inp: VerifyProductIn):
    try:
        import httpx
        solver_url = os.getenv("SOLVER_URL", "http://localhost:8000/v1/chat/completions")
        solver_api_key = os.getenv("SOLVER_API_KEY", "no_key")

        # Load base prompt from file
        base_prompt = _load_prompt("search_result_verifier")
        if not base_prompt:
            # Fallback inline prompt if file not found
            base_prompt = """You are a search result verifier. Your task is to determine if the following HTML content is for a relevant product based on the user's query.

For live animal searches (e.g., "hamster"):
- The page should be for a live animal for sale
- It should NOT be a toy, figurine, book, cage, or accessory
- Look for words like "live", "adoption", "breeder"
- If it is not a live animal, answer "no"

Answer with only "yes" or "no"."""

        prompt = f"""{base_prompt}

---

Query: "{inp.query}"

HTML Content:
{inp.html_content[:10000]}

Is this a product page for a relevant product based on the query? Answer with only "yes" or "no"."""

        response = httpx.post(
            solver_url,
            headers={"Authorization": f"Bearer {solver_api_key}"},
            json={
                "model": os.getenv("SOLVER_MODEL_ID", "qwen3-coder"),
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 5,
                "temperature": 0.4,
                "top_p": 0.8,
                "stop": ["<|im_end|>", "<|endoftext|>"],
                "repetition_penalty": 1.05
            },
            timeout=30,
        )
        response.raise_for_status()
        llm_response = response.json()
        answer = llm_response["choices"][0]["message"]["content"].strip().lower()
        return {"is_relevant": "yes" in answer}
    except Exception as e:
        raise HTTPException(500, f"LLM verification error: {e}")


# ============================================================================
# Code Operations - File Read/Write/Edit/Glob/Grep
# ============================================================================

class FileReadIn(BaseModel):
    file_path: str
    repo: Optional[str] = None
    offset: int = 0
    limit: Optional[int] = None
    max_bytes: int = 200000


@app.post("/file.read")
def file_read(inp: FileReadIn):
    """Read a file with optional line offset and limit."""
    try:
        return code_mcp.read_file(
            file_path=inp.file_path,
            repo=inp.repo,
            offset=inp.offset,
            limit=inp.limit,
            max_bytes=inp.max_bytes
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"file.read error: {e}")


class FileWriteIn(BaseModel):
    file_path: str
    content: str
    repo: Optional[str] = None
    mode: str = "fail_if_exists"


@app.post("/file.write")
def file_write(inp: FileWriteIn):
    """Write content to a file."""
    try:
        return code_mcp.write_file(
            file_path=inp.file_path,
            content=inp.content,
            repo=inp.repo,
            mode=inp.mode
        )
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        logger.error(f"file.write validation error: {e}", exc_info=True)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"file.write unexpected error: {e}", exc_info=True)
        raise HTTPException(500, f"file.write error: {e}")


class FileDeleteIn(BaseModel):
    file_path: str
    repo: Optional[str] = None
    fail_if_missing: bool = True


@app.post("/file.delete")
def file_delete(inp: FileDeleteIn):
    """Delete a file."""
    try:
        return code_mcp.delete_file(
            file_path=inp.file_path,
            repo=inp.repo,
            fail_if_missing=inp.fail_if_missing
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        logger.error(f"file.delete validation error: {e}", exc_info=True)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"file.delete unexpected error: {e}", exc_info=True)
        raise HTTPException(500, f"file.delete error: {e}")


class FileEditIn(BaseModel):
    file_path: str
    old_string: str
    new_string: str
    repo: Optional[str] = None
    replace_all: bool = False


@app.post("/file.edit")
def file_edit(inp: FileEditIn):
    """Edit a file by replacing exact string matches."""
    try:
        return code_mcp.edit_file(
            file_path=inp.file_path,
            old_string=inp.old_string,
            new_string=inp.new_string,
            repo=inp.repo,
            replace_all=inp.replace_all
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"file.edit error: {e}")


class FileGlobIn(BaseModel):
    pattern: str
    repo: Optional[str] = None
    max_results: int = 100


@app.post("/file.glob")
def file_glob(inp: FileGlobIn):
    """Find files matching a glob pattern."""
    try:
        return code_mcp.glob_files(
            pattern=inp.pattern,
            repo=inp.repo,
            max_results=inp.max_results
        )
    except Exception as e:
        raise HTTPException(500, f"file.glob error: {e}")


class FileGrepIn(BaseModel):
    pattern: str
    repo: Optional[str] = None
    file_pattern: Optional[str] = None
    file_type: Optional[str] = None
    context_before: int = 0
    context_after: int = 0
    max_results: int = 100
    case_sensitive: bool = True
    output_mode: str = "files_with_matches"


@app.post("/file.grep")
def file_grep(inp: FileGrepIn):
    """Search for pattern in files using ripgrep or Python regex."""
    try:
        return code_mcp.grep_files(
            pattern=inp.pattern,
            repo=inp.repo,
            file_pattern=inp.file_pattern,
            file_type=inp.file_type,
            context_before=inp.context_before,
            context_after=inp.context_after,
            max_results=inp.max_results,
            case_sensitive=inp.case_sensitive,
            output_mode=inp.output_mode
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"file.grep error: {e}")


# ============================================================================
# Git Operations
# ============================================================================

class GitStatusIn(BaseModel):
    repo: str


@app.post("/git.status")
def git_status_endpoint(inp: GitStatusIn):
    """Get git status for repository."""
    try:
        return git_mcp.git_status(inp.repo)
    except git_mcp.GitError as e:
        raise HTTPException(500, str(e))


class GitDiffIn(BaseModel):
    repo: str
    cached: bool = False
    paths: Optional[List[str]] = None
    base: Optional[str] = None


@app.post("/git.diff")
def git_diff_endpoint(inp: GitDiffIn):
    """Get git diff output."""
    try:
        return git_mcp.git_diff(
            repo=inp.repo,
            cached=inp.cached,
            paths=inp.paths,
            base=inp.base
        )
    except git_mcp.GitError as e:
        raise HTTPException(500, str(e))


class GitLogIn(BaseModel):
    repo: str
    max_count: int = 10
    format: str = "oneline"
    base: Optional[str] = None


@app.post("/git.log")
def git_log_endpoint(inp: GitLogIn):
    """Get git commit log."""
    try:
        return git_mcp.git_log(
            repo=inp.repo,
            max_count=inp.max_count,
            format=inp.format,
            base=inp.base
        )
    except git_mcp.GitError as e:
        raise HTTPException(500, str(e))


class GitAddIn(BaseModel):
    repo: str
    paths: List[str]


@app.post("/git.add")
def git_add_endpoint(inp: GitAddIn):
    """Stage files for commit."""
    try:
        return git_mcp.git_add(inp.repo, inp.paths)
    except git_mcp.GitError as e:
        raise HTTPException(500, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


class GitCommitNewIn(BaseModel):
    repo: str
    message: str
    add_paths: Optional[List[str]] = None
    amend: bool = False
    allow_empty: bool = False


@app.post("/git.commit_safe")
def git_commit_safe(inp: GitCommitNewIn):
    """Create a git commit with safety checks."""
    try:
        return git_mcp.git_commit(
            repo=inp.repo,
            message=inp.message,
            add_paths=inp.add_paths,
            amend=inp.amend,
            allow_empty=inp.allow_empty
        )
    except git_mcp.GitSafetyError as e:
        raise HTTPException(403, f"Safety check failed: {e}")
    except git_mcp.GitError as e:
        raise HTTPException(500, str(e))


class GitBranchIn(BaseModel):
    repo: str
    branch_name: Optional[str] = None
    delete: Optional[str] = None
    force: bool = False


@app.post("/git.branch")
def git_branch_endpoint(inp: GitBranchIn):
    """Manage git branches."""
    try:
        return git_mcp.git_branch(
            repo=inp.repo,
            branch_name=inp.branch_name,
            delete=inp.delete,
            force=inp.force
        )
    except git_mcp.GitSafetyError as e:
        raise HTTPException(403, f"Safety check failed: {e}")
    except git_mcp.GitError as e:
        raise HTTPException(500, str(e))


class GitPushIn(BaseModel):
    repo: str
    remote: str = "origin"
    branch: Optional[str] = None
    set_upstream: bool = False
    force: bool = False


@app.post("/git.push")
def git_push_endpoint(inp: GitPushIn):
    """Push commits to remote with safety checks."""
    try:
        return git_mcp.git_push(
            repo=inp.repo,
            remote=inp.remote,
            branch=inp.branch,
            set_upstream=inp.set_upstream,
            force=inp.force
        )
    except git_mcp.GitSafetyError as e:
        raise HTTPException(403, f"Safety check failed: {e}")
    except git_mcp.GitError as e:
        raise HTTPException(500, str(e))


class GitPullIn(BaseModel):
    repo: str
    remote: str = "origin"
    branch: Optional[str] = None


@app.post("/git.pull")
def git_pull_endpoint(inp: GitPullIn):
    """Pull changes from remote."""
    try:
        return git_mcp.git_pull(
            repo=inp.repo,
            remote=inp.remote,
            branch=inp.branch
        )
    except git_mcp.GitError as e:
        raise HTTPException(500, str(e))


class CreatePRIn(BaseModel):
    repo: str
    title: str
    body: str
    base: Optional[str] = None
    draft: bool = False


@app.post("/git.create_pr")
def git_create_pr(inp: CreatePRIn):
    """Create a GitHub pull request using gh CLI."""
    try:
        return git_mcp.create_pr_with_gh(
            repo=inp.repo,
            title=inp.title,
            body=inp.body,
            base=inp.base,
            draft=inp.draft
        )
    except git_mcp.GitError as e:
        raise HTTPException(500, str(e))


# ============================================================================
# Bash Execution
# ============================================================================

class BashExecIn(BaseModel):
    command: str
    cwd: Optional[str] = None
    timeout: Optional[int] = 120
    run_in_background: bool = False
    description: Optional[str] = None
    env: Optional[Dict[str, str]] = None


@app.post("/bash.execute")
def bash_execute(inp: BashExecIn):
    """Execute a bash command."""
    try:
        return bash_mcp.execute_command(
            command=inp.command,
            cwd=inp.cwd,
            timeout=inp.timeout,
            run_in_background=inp.run_in_background,
            description=inp.description,
            env=inp.env
        )
    except bash_mcp.BashError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"bash.execute error: {e}")


class BashOutputIn(BaseModel):
    shell_id: str
    filter_regex: Optional[str] = None


@app.post("/bash.get_output")
def bash_get_output(inp: BashOutputIn):
    """Get output from a background shell."""
    try:
        return bash_mcp.get_background_output(inp.shell_id, inp.filter_regex)
    except bash_mcp.BashError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"bash.get_output error: {e}")


class BashKillIn(BaseModel):
    shell_id: str


@app.post("/bash.kill")
def bash_kill(inp: BashKillIn):
    """Kill a background shell."""
    try:
        return bash_mcp.kill_background_shell(inp.shell_id)
    except bash_mcp.BashError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"bash.kill error: {e}")


@app.post("/bash.list")
def bash_list():
    """List all active background shells."""
    try:
        return bash_mcp.list_background_shells()
    except Exception as e:
        raise HTTPException(500, f"bash.list error: {e}")


# ============================================================================
# Code Diagnostics
# ============================================================================

class ValidateFileIn(BaseModel):
    file_path: str
    repo: Optional[str] = None


@app.post("/code.validate")
def code_validate(inp: ValidateFileIn):
    """Auto-detect file type and run appropriate validation."""
    try:
        return diagnostics_mcp.validate_file(inp.file_path, inp.repo)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"code.validate error: {e}")


class RunLinterIn(BaseModel):
    file_path: str
    repo: Optional[str] = None
    config: Optional[str] = None
    tool: str = "pylint"  # pylint, flake8, mypy, eslint


@app.post("/code.lint")
def code_lint(inp: RunLinterIn):
    """Run linter on a file."""
    try:
        if inp.tool == "pylint":
            return diagnostics_mcp.run_pylint(inp.file_path, inp.repo, inp.config)
        elif inp.tool == "flake8":
            return diagnostics_mcp.run_flake8(inp.file_path, inp.repo, inp.config)
        elif inp.tool == "mypy":
            return diagnostics_mcp.run_mypy(inp.file_path, inp.repo, inp.config)
        elif inp.tool == "eslint":
            return diagnostics_mcp.run_eslint(inp.file_path, inp.repo, inp.config)
        else:
            raise HTTPException(400, f"Unknown linter tool: {inp.tool}")
    except diagnostics_mcp.DiagnosticError as e:
        raise HTTPException(500, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"code.lint error: {e}")


class DiagnosticsSummaryIn(BaseModel):
    repo: str
    file_pattern: str = "**/*.py"


@app.post("/code.diagnostics_summary")
def code_diagnostics_summary(inp: DiagnosticsSummaryIn):
    """Get diagnostics summary for multiple files."""
    try:
        return diagnostics_mcp.get_diagnostics_summary(inp.repo, inp.file_pattern)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"code.diagnostics_summary error: {e}")


# Lesson endpoints removed 2026-01-02 - learning via turn indexing now


# ========================================
# Context Manager Memory Processing
# ========================================

class TurnProcessingRequest(BaseModel):
    session_id: str
    turn_number: int
    user_message: str
    guide_response: str
    tool_results: List[Dict[str, Any]] = []
    capsule: Optional[Dict[str, Any]] = None
    current_context: Dict[str, Any]
    intent_classification: str
    satisfaction_signal: Optional[Dict[str, Any]] = None


@app.post("/context.process_turn")
async def context_process_turn(req: TurnProcessingRequest):
    """
    Context Manager: Process complete turn and extract memories.

    This is the FINAL AUTHORITY on memory updates. Called at the END
    of each request with complete turn data.

    Returns memory update decisions including:
    - Preference updates (with policy enforcement)
    - Topic extraction
    - Fact compression
    - Turn summarization
    - Quality evaluation
    - Cache decisions
    - Learning patterns
    """
    try:
        result = await CM_MEMORY.process_turn(
            session_id=req.session_id,
            turn_number=req.turn_number,
            user_message=req.user_message,
            guide_response=req.guide_response,
            tool_results=req.tool_results,
            capsule=req.capsule,
            current_context=req.current_context,
            intent_classification=req.intent_classification,
            satisfaction_signal=req.satisfaction_signal
        )

        return {
            "status": "success",
            "preferences_updated": result.preferences_updated,
            "preferences_preserved": result.preferences_preserved,
            "preference_reasoning": result.preference_reasoning,
            "topic": result.topic,
            "topic_confidence": result.topic_confidence,
            "facts": result.facts,
            "turn_summary": result.turn_summary,
            "conversation_quality": result.conversation_quality,
            "memory_actions": result.memory_actions,
            "response_cache_entry": result.response_cache_entry,
            "learning_patterns": result.learning_patterns,
            "quality_score": result.quality_score,
            "satisfaction_score": result.satisfaction_score,
            "errors": result.errors
        }

    except Exception as e:
        import traceback
        logger.error(f"[context.process_turn] Error: {e}\n{traceback.format_exc()}")
        # Return fallback (preserve existing context)
        return {
            "status": "error",
            "error": str(e),
            "preferences_updated": {},
            "preferences_preserved": req.current_context.get("preferences", {}),
            "preference_reasoning": {"error": "CM processing failed, preserved existing preferences"},
            "topic": req.current_context.get("current_topic"),
            "topic_confidence": 0.0,
            "facts": {},
            "turn_summary": {"short": "Error processing turn", "bullets": [], "tokens": 0},
            "conversation_quality": {
                "user_need_met": False,
                "information_complete": False,
                "requires_followup": True
            },
            "memory_actions": {
                "cache_response": False,
                "save_to_long_term": False,
                "update_topic": False,
                "update_preferences": False,
                "propagate_quality_feedback": False
            },
            "response_cache_entry": None,
            "learning_patterns": None,
            "quality_score": 0.0,
            "satisfaction_score": 0.0,
            "errors": [str(e)]
        }


# ========================================
# Code Operations Endpoints
# ========================================

@app.post("/file.read_outline")
async def file_read_outline_endpoint(req: dict):
    """
    Get file outline with symbol table (classes, functions).

    MCP tool: file.read_outline

    Args:
        req: {
            "file_path": str,
            "symbol_filter": Optional[str],  # Regex pattern
            "include_docstrings": bool  # Default: True
        }

    Returns:
        {
            "symbols": [{"type": "class", "name": "...", "line": 42, "docstring": "..."}],
            "toc": str,  # Table of contents markdown
            "file_info": {"lines": 150, "size_kb": 8},
            "chunks": [{"offset": 0, "limit": 50, "description": "..."}]
        }
    """
    try:
        result = await file_operations_mcp.file_read_outline(**req)
        return result
    except Exception as e:
        logger.error(f"[file.read_outline] Error: {e}")
        return {"error": str(e)}


@app.post("/repo.scope_discover")
async def repo_scope_discover_endpoint(req: dict):
    """
    Discover repository scope for a goal.

    MCP tool: repo.scope_discover

    Args:
        req: {
            "goal": str,  # Natural language goal (e.g., "authentication module")
            "repo": str,  # Repository path
            "search_patterns": Optional[List[str]],  # Auto-detected if not provided
            "max_files": int  # Default: 20
        }

    Returns:
        {
            "impacted_files": List[str],
            "dependencies": Dict[str, List[str]],
            "suggested_subtasks": List[Dict],
            "file_summaries": Dict[str, Dict],
            "search_patterns": List[str]
        }
    """
    try:
        result = await repo_scope_mcp.repo_scope_discover(**req)
        return result
    except Exception as e:
        logger.error(f"[repo.scope_discover] Error: {e}")
        return {"error": str(e)}


@app.post("/code.verify_suite")
async def code_verify_suite_endpoint(req: dict):
    """
    Run verification suite (tests + optional lint/typecheck).

    MCP tool: code.verify_suite

    Args:
        req: {
            "target": str,  # Directory or file to verify (default: ".")
            "repo": Optional[str],  # Repository path
            "tests": bool,  # Run tests (default: True)
            "lint": bool,  # Run linter (default: False, opt-in for speed)
            "typecheck": bool,  # Run type checker (default: False, opt-in)
            "timeout": int  # Max seconds per operation (default: 60)
        }

    Returns:
        {
            "tests": {"passed": 12, "failed": 2, "errors": [...], "status": "fail"},
            "lint": {"issues": 5, "details": [...], "status": "warnings"},
            "typecheck": {"errors": 1, "details": [...], "status": "fail"},
            "summary": "12/14 tests passed, 5 lint issues",
            "overall_status": "fail"
        }
    """
    try:
        result = await code_verify_mcp.code_verify_suite(**req)
        return result
    except Exception as e:
        logger.error(f"[code.verify_suite] Error: {e}")
        return {"error": str(e)}


@app.post("/context.snapshot_repo")
async def context_snapshot_repo_endpoint(req: dict):
    """
    Get current repository state snapshot.

    MCP tool: context.snapshot_repo

    Args:
        req: {
            "repo": str,  # Repository path
            "max_commits": int  # Number of recent commits to include (default: 3)
        }

    Returns:
        {
            "branch": "main",
            "dirty_files": ["auth.py", "test_auth.py"],
            "dirty_count": 2,
            "last_commits": [
                {"hash": "abc123", "author": "user", "time": "2h ago", "message": "Add refresh token"}
            ],
            "summary": "On main, 2 uncommitted changes, last commit 2h ago"
        }
    """
    try:
        result = await context_snapshot_mcp.context_snapshot_repo(**req)
        return result
    except Exception as e:
        logger.error(f"[context.snapshot_repo] Error: {e}")
        return {"error": str(e)}


@app.post("/context.recall_turn")
async def context_recall_turn_endpoint(req: dict):
    """
    Recall details about a previous turn for follow-up questions.

    MCP tool: context.recall_turn

    Use this when the user asks about previous responses, like:
    - "why did you choose those options?"
    - "tell me more about the first one"
    - "what was the price again?"

    Args:
        req: {
            "turn_offset": int,  # How many turns back (1=previous, default: 1)
            "include_claims": bool,  # Include product/claim details (default: true)
            "include_response": bool,  # Include the response that was given (default: true)
            "session_id": str  # Optional session ID
        }

    Returns:
        {
            "turn_id": "turn_000559",
            "user_query": "cheapest laptop with nvidia gpu",
            "summary": "Found 3 laptops with NVIDIA GPUs...",
            "key_findings": ["MSI THIN A15 at $549.99", ...],
            "claims": [...],
            "response_preview": "...",
            "selection_context": {
                "criteria_from_query": ["cheapest", "nvidia gpu"],
                "preferences_at_time": "...",
                "topic": "laptop shopping"
            }
        }
    """
    try:
        result = await context_snapshot_mcp.context_recall_turn(**req)
        return result
    except Exception as e:
        logger.error(f"[context.recall_turn] Error: {e}")
        return {"error": str(e)}


@app.get("/debug/observability")
async def debug_observability(hours: int = 24):
    """
    Observability dashboard endpoint.

    Returns metrics for tools, roles, reflection cycles, and flows.

    Query params:
        hours: Number of hours to include in metrics (default: 24)

    Returns:
        {
            "period_hours": 24,
            "tools": [...],
            "roles": {...},
            "reflection": {...},
            "flows": {...}
        }
    """
    from apps.services.tool_server.observability import get_collector

    collector = get_collector()
    return collector.get_dashboard_data(hours=hours)


# ==========================================
# Browser Streaming Endpoints (for remote CAPTCHA solving)
# ==========================================

@app.post("/browser-stream/{stream_id}/connect")
async def browser_stream_connect(stream_id: str, data: dict):
    """
    Connect client to browser stream.
    Gateway WebSocket calls this to subscribe to frames.
    """
    from apps.services.tool_server.browser_stream_manager import get_browser_stream_manager

    manager = get_browser_stream_manager()
    stream = manager.get_stream(stream_id)

    if not stream:
        return {"error": f"Stream not found: {stream_id}"}, 404

    # Note: In a real implementation, we'd track the WebSocket connection
    # For now, we just confirm the stream exists
    return {"ok": True, "stream_id": stream_id}


@app.post("/browser-stream/{stream_id}/click")
async def browser_stream_click(stream_id: str, data: dict):
    """Handle click event from user."""
    from apps.services.tool_server.browser_stream_manager import get_browser_stream_manager

    manager = get_browser_stream_manager()
    stream = manager.get_stream(stream_id)

    if not stream:
        return {"error": f"Stream not found: {stream_id}"}, 404

    await stream.handle_click(x=data["x"], y=data["y"])
    return {"ok": True}


@app.post("/browser-stream/{stream_id}/scroll")
async def browser_stream_scroll(stream_id: str, data: dict):
    """Handle scroll event from user."""
    from apps.services.tool_server.browser_stream_manager import get_browser_stream_manager

    manager = get_browser_stream_manager()
    stream = manager.get_stream(stream_id)

    if not stream:
        return {"error": f"Stream not found: {stream_id}"}, 404

    await stream.handle_scroll(
        delta_x=data.get("delta_x", 0),
        delta_y=data.get("delta_y", 0)
    )
    return {"ok": True}


@app.post("/browser-stream/{stream_id}/typing")
async def browser_stream_typing(stream_id: str, data: dict):
    """Handle typing event from user."""
    from apps.services.tool_server.browser_stream_manager import get_browser_stream_manager

    manager = get_browser_stream_manager()
    stream = manager.get_stream(stream_id)

    if not stream:
        return {"error": f"Stream not found: {stream_id}"}, 404

    await stream.handle_typing(text=data["text"])
    return {"ok": True}


@app.post("/browser-stream/{stream_id}/keypress")
async def browser_stream_keypress(stream_id: str, data: dict):
    """Handle keypress event from user."""
    from apps.services.tool_server.browser_stream_manager import get_browser_stream_manager

    manager = get_browser_stream_manager()
    stream = manager.get_stream(stream_id)

    if not stream:
        return {"error": f"Stream not found: {stream_id}"}, 404

    await stream.handle_keypress(key=data["key"])
    return {"ok": True}


@app.post("/browser-stream/{stream_id}/disconnect")
async def browser_stream_disconnect(stream_id: str, data: dict):
    """Handle client disconnect."""
    from apps.services.tool_server.browser_stream_manager import get_browser_stream_manager

    manager = get_browser_stream_manager()
    stream = manager.get_stream(stream_id)

    if stream:
        # Note: In a real implementation, we'd remove the specific WebSocket client
        # For now, we just log the disconnect
        logger.info(f"[BrowserStream] Client disconnected from {stream_id}")

    return {"ok": True}


# ==============================================================================
# Computer Agent - Desktop Automation
# ==============================================================================

@app.post("/computer.click")
async def computer_click(inp: ComputerClickIn):
    """
    Click a UI element on the desktop by description.

    Uses vision-guided targeting (OCR + shape detection) to find and click
    UI elements matching the goal description.

    Example: {"goal": "Start menu", "max_attempts": 3, "timeout": 30.0}
    """
    try:
        result = await computer_agent_mcp.click(
            goal=inp.goal,
            max_attempts=inp.max_attempts,
            timeout=inp.timeout
        )
        return result
    except Exception as e:
        logger.error(f"[computer.click] Error: {e}")
        raise HTTPException(500, f"Computer click failed: {e}")


@app.post("/computer.type_text")
async def computer_type_text(inp: ComputerTypeTextIn):
    """
    Type text on the keyboard.

    Optionally clicks a target field first if 'into' is specified.
    Uses human-like typing intervals.

    Example: {"text": "hello world", "into": "search box", "interval": 0.05}
    """
    try:
        result = await computer_agent_mcp.type_text(
            text=inp.text,
            into=inp.into,
            interval=inp.interval
        )
        return result
    except Exception as e:
        logger.error(f"[computer.type_text] Error: {e}")
        raise HTTPException(500, f"Computer type text failed: {e}")


@app.post("/computer.press_key")
async def computer_press_key(inp: ComputerPressKeyIn):
    """
    Press a keyboard key.

    Supports special keys like "enter", "tab", "esc", etc.

    Example: {"key": "enter", "presses": 1}
    """
    try:
        result = await computer_agent_mcp.press_key(
            key=inp.key,
            presses=inp.presses
        )
        return result
    except Exception as e:
        logger.error(f"[computer.press_key] Error: {e}")
        raise HTTPException(500, f"Computer press key failed: {e}")


@app.post("/computer.scroll")
async def computer_scroll(inp: ComputerScrollIn):
    """
    Scroll mouse wheel.

    Positive clicks = scroll up, negative clicks = scroll down.

    Example: {"clicks": -5}
    """
    try:
        result = await computer_agent_mcp.scroll(
            clicks=inp.clicks
        )
        return result
    except Exception as e:
        logger.error(f"[computer.scroll] Error: {e}")
        raise HTTPException(500, f"Computer scroll failed: {e}")


@app.post("/computer.screenshot")
async def computer_screenshot(inp: ComputerScreenshotIn):
    """
    Capture screenshot of the desktop.

    Returns screen size and path to saved screenshot.

    Example: {"save_path": "/tmp/screen.png"}
    """
    try:
        result = await computer_agent_mcp.screenshot(
            save_path=inp.save_path
        )
        return result
    except Exception as e:
        logger.error(f"[computer.screenshot] Error: {e}")
        raise HTTPException(500, f"Computer screenshot failed: {e}")


@app.post("/computer.get_screen_state")
async def computer_get_screen_state_endpoint(payload: ComputerGetScreenStateIn):
    """Get current screen state for vision-in-the-loop."""
    from apps.services.tool_server import computer_agent_mcp
    result = await computer_agent_mcp.get_screen_state(
        max_elements=payload.max_elements,
        max_text_len=payload.max_text_len
    )
    return result


@app.get("/computer.status")
async def computer_status():
    """
    Get Computer Agent status and configuration.

    Returns initialization status, config, screen size, and mouse position.
    """
    try:
        result = await computer_agent_mcp.get_status()
        return result
    except Exception as e:
        logger.error(f"[computer.status] Error: {e}")
        raise HTTPException(500, f"Computer status failed: {e}")


# ============================================================================
# Web Vision Agent Endpoints
# ============================================================================

@app.post("/web.get_screen_state")
async def web_get_screen_state_endpoint(payload: WebGetScreenStateIn):
    """Get current page state for vision-in-the-loop web automation."""
    try:
        from apps.services.tool_server import web_vision_mcp
        result = await web_vision_mcp.get_screen_state(
            session_id=payload.session_id,
            max_elements=payload.max_elements,
            max_text_len=payload.max_text_len
        )
        return result
    except Exception as e:
        logger.error(f"[web.get_screen_state] Error: {e}")
        raise HTTPException(500, f"Web get_screen_state failed: {e}")


@app.post("/web.click")
async def web_click_endpoint(payload: WebClickIn):
    """Click UI element in browser."""
    try:
        from apps.services.tool_server import web_vision_mcp
        result = await web_vision_mcp.click(
            session_id=payload.session_id,
            goal=payload.goal,
            max_attempts=payload.max_attempts,
            timeout=payload.timeout
        )
        return result
    except Exception as e:
        logger.error(f"[web.click] Error: {e}")
        raise HTTPException(500, f"Web click failed: {e}")


@app.post("/web.type_text")
async def web_type_text_endpoint(payload: WebTypeTextIn):
    """Type text in browser."""
    try:
        from apps.services.tool_server import web_vision_mcp
        result = await web_vision_mcp.type_text(
            session_id=payload.session_id,
            text=payload.text,
            into=payload.into,
            interval=payload.interval
        )
        return result
    except Exception as e:
        logger.error(f"[web.type_text] Error: {e}")
        raise HTTPException(500, f"Web type_text failed: {e}")


@app.post("/web.press_key")
async def web_press_key_endpoint(payload: WebPressKeyIn):
    """Press keyboard key in browser."""
    try:
        from apps.services.tool_server import web_vision_mcp
        result = await web_vision_mcp.press_key(
            session_id=payload.session_id,
            key=payload.key,
            presses=payload.presses,
            after_clicking=payload.after_clicking
        )
        return result
    except Exception as e:
        logger.error(f"[web.press_key] Error: {e}")
        raise HTTPException(500, f"Web press_key failed: {e}")


@app.post("/web.scroll")
async def web_scroll_endpoint(payload: WebScrollIn):
    """Scroll page up/down."""
    try:
        from apps.services.tool_server import web_vision_mcp
        result = await web_vision_mcp.scroll(
            session_id=payload.session_id,
            clicks=payload.clicks
        )
        return result
    except Exception as e:
        logger.error(f"[web.scroll] Error: {e}")
        raise HTTPException(500, f"Web scroll failed: {e}")


@app.post("/web.capture_content")
async def web_capture_content_endpoint(payload: WebCaptureContentIn):
    """Capture page content as markdown or HTML."""
    try:
        from apps.services.tool_server import web_vision_mcp
        result = await web_vision_mcp.capture_content(
            session_id=payload.session_id,
            format=payload.format
        )
        return result
    except Exception as e:
        logger.error(f"[web.capture_content] Error: {e}")
        raise HTTPException(500, f"Web capture_content failed: {e}")


@app.post("/web.navigate")
async def web_navigate_endpoint(payload: WebNavigateIn):
    """Navigate to URL with stealth and error handling."""
    try:
        from apps.services.tool_server import web_vision_mcp
        result = await web_vision_mcp.navigate(
            session_id=payload.session_id,
            url=payload.url,
            wait_for=payload.wait_for
        )
        return result
    except Exception as e:
        logger.error(f"[web.navigate] Error: {e}")
        raise HTTPException(500, f"Web navigate failed: {e}")


@app.get("/web.status")
async def web_status_endpoint(session_id: str):
    """Get web session status and page info."""
    try:
        from apps.services.tool_server import web_vision_mcp
        result = await web_vision_mcp.get_status(session_id)
        return result
    except Exception as e:
        logger.error(f"[web.status] Error: {e}")
        raise HTTPException(500, f"Web status failed: {e}")


# Browser Control Endpoints (Local View Mode)

class BrowserConnectRequest(BaseModel):
    session_id: str
    cdp_endpoint: str = "http://localhost:9222"

class BrowserModeRequest(BaseModel):
    session_id: str
    mode: str  # "headless" or "local_view"


@app.post("/api/browser/connect")
async def connect_external_browser(req: BrowserConnectRequest):
    """
    Connect to an external browser running on user's device for local_view mode.

    User should first launch Chrome/Chromium with remote debugging:
      Chrome: chrome --remote-debugging-port=9222 --user-data-dir="/tmp/chrome-profile"
      Mac: /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \\
             --remote-debugging-port=9222 --user-data-dir="/tmp/chrome-profile"

    Then this endpoint connects Playwright to that browser, enabling the user to
    watch and control the browser directly while automation runs.
    """
    try:
        from apps.services.tool_server.crawler_session_manager import get_crawler_session_manager

        manager = get_crawler_session_manager()
        success = await manager.connect_external_browser(
            session_id=req.session_id,
            cdp_endpoint=req.cdp_endpoint
        )

        if success:
            return {
                "status": "connected",
                "session_id": req.session_id,
                "cdp_endpoint": req.cdp_endpoint,
                "message": "Successfully connected to external browser. Session is now in local_view mode."
            }
        else:
            raise HTTPException(500, "Failed to connect to external browser")

    except Exception as e:
        logger.error(f"[browser/connect] Error: {e}", exc_info=True)
        raise HTTPException(500, f"Browser connection failed: {e}")


@app.post("/api/browser/mode")
async def set_browser_mode(req: BrowserModeRequest):
    """
    Set session mode: 'headless' (default) or 'local_view' (user's browser).

    Call this BEFORE starting a research session to configure the mode.
    For local_view mode, call /api/browser/connect first.
    """
    try:
        from apps.services.tool_server.crawler_session_manager import get_crawler_session_manager

        manager = get_crawler_session_manager()
        manager.set_session_mode(req.session_id, req.mode)

        return {
            "status": "success",
            "session_id": req.session_id,
            "mode": req.mode
        }

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"[browser/mode] Error: {e}", exc_info=True)
        raise HTTPException(500, f"Set mode failed: {e}")


@app.get("/api/browser/info/{session_id}")
async def get_browser_info(session_id: str):
    """
    Get browser connection info for a session.

    Returns CDP URL, mode, and connection status.
    """
    try:
        from apps.services.tool_server.crawler_session_manager import get_crawler_session_manager

        manager = get_crawler_session_manager()

        mode = manager.session_mode.get(session_id, "headless")
        is_connected = session_id in manager.external_browsers
        cdp_url = manager.get_cdp_url() if mode == "headless" else None

        return {
            "session_id": session_id,
            "mode": mode,
            "external_browser_connected": is_connected,
            "cdp_url": cdp_url
        }

    except Exception as e:
        logger.error(f"[browser/info] Error: {e}", exc_info=True)
        raise HTTPException(500, f"Get browser info failed: {e}")


@app.websocket("/ws/browser-stream/{stream_id}")
async def browser_stream_websocket(websocket: WebSocket, stream_id: str):
    """
    WebSocket endpoint for browser streaming.

    Gateway connects here to receive frames and send user interactions.
    Frames flow: Playwright → BrowserStream → this WS → Gateway WS → User Browser
    """
    from apps.services.tool_server.browser_stream_manager import get_browser_stream_manager
    import json

    await websocket.accept()
    logger.info(f"[BrowserStreamWS] Gateway connected for stream: {stream_id}")

    manager = get_browser_stream_manager()
    stream = manager.get_stream(stream_id)

    if not stream:
        await websocket.send_json({
            "type": "error",
            "message": f"Stream not found: {stream_id}"
        })
        await websocket.close()
        return

    # Add this WebSocket to the stream's client list
    stream.add_client(websocket)

    try:
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            event_type = message.get("type")

            # Handle user interactions
            if event_type == "click":
                await stream.handle_click(x=message["x"], y=message["y"])
            elif event_type == "scroll":
                await stream.handle_scroll(
                    delta_x=message.get("delta_x", 0),
                    delta_y=message.get("delta_y", 0)
                )
            elif event_type == "typing":
                await stream.handle_typing(text=message["text"])
            elif event_type == "keypress":
                await stream.handle_keypress(key=message["key"])

    except WebSocketDisconnect:
        logger.info(f"[BrowserStreamWS] Gateway disconnected from stream: {stream_id}")
    except Exception as e:
        logger.error(f"[BrowserStreamWS] Error: {e}", exc_info=True)
    finally:
        stream.remove_client(websocket)
