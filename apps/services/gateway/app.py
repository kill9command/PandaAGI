"""
Gateway FastAPI Application - Pipeline Orchestration Service

This is the slim app factory that imports from organized modules.
The original monolithic app.py is preserved as app_original.py.

Architecture Reference:
    architecture/Implementation/04-SERVICES-OVERVIEW.md
    architecture/services/user-interface.md

Structure:
    - config.py: All environment variables and constants
    - dependencies.py: Singleton instances with lazy initialization
    - lifespan.py: Application startup/shutdown handlers
    - services/: Business logic (thinking, jobs, tool_server_client)
    - utils/: Utility functions (text, json_helpers, trace)
    - routers/: Internal API endpoints
    - routes/: External API endpoints (proxy to Tool Server)
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Configuration and lifespan
from apps.services.gateway.config import (
    STATIC_DIR,
    get_config,
)
from apps.services.gateway.lifespan import lifespan

# Internal routers (local processing)
from apps.services.gateway.routers import (
    health_router,
    thinking_router,
    jobs_router,
    transcripts_router,
    interventions_router,
    chat_completions_router,
    internal_router,
    approvals_router,
    tools_router,
    websockets_router,
    ui_router,
)

# External routers (proxy to Tool Server)
from apps.services.gateway.routes import (
    chat_router,
    turns_router,
    memory_router,
    cache_router,
    status_router,
    diff_router,
)

logger = logging.getLogger("uvicorn.error")
config = get_config()

# =============================================================================
# Application Factory
# =============================================================================

app = FastAPI(
    title="Panda Gateway",
    description="Pipeline Orchestration Service - 8-Phase Document Pipeline",
    version="5.0.0",
    lifespan=lifespan,
)

# =============================================================================
# Middleware
# =============================================================================

# CORS: allow access from phone/laptop on LAN
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Static Files
# =============================================================================

# Mount static files directory
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Mount screenshots directory for research visualization
screenshots_dir = Path("panda_system_docs/scrape_staging/screenshots")
if screenshots_dir.exists():
    app.mount("/screenshots", StaticFiles(directory=str(screenshots_dir)), name="screenshots")

# Mount new Svelte UI at root (if built), old UI at /legacy
new_ui_dir = Path("apps/ui/build")
NEW_UI_AVAILABLE = new_ui_dir.exists()
if NEW_UI_AVAILABLE:
    logger.info(f"[Gateway] New Svelte UI will be served at /")
    # Mount new UI assets (JS, CSS in _app/)
    new_ui_app_dir = new_ui_dir / "_app"
    if new_ui_app_dir.exists():
        app.mount("/_app", StaticFiles(directory=str(new_ui_app_dir)), name="new_ui_app")
    # Mount new UI icons
    new_ui_icons_dir = new_ui_dir / "icons"
    if new_ui_icons_dir.exists():
        app.mount("/icons", StaticFiles(directory=str(new_ui_icons_dir)), name="new_ui_icons")
    # Mount legacy UI at /legacy for fallback
    app.mount("/legacy", StaticFiles(directory=str(STATIC_DIR), html=True), name="legacy_ui")
else:
    logger.info(f"[Gateway] New UI not built, using legacy UI at /")

# =============================================================================
# Internal Routers (Local Processing)
# =============================================================================

# Health check endpoints
app.include_router(health_router)

# Thinking visualization SSE endpoints
app.include_router(thinking_router)

# Async job management endpoints
app.include_router(jobs_router)

# Transcript/trace history endpoints
app.include_router(transcripts_router)

# Intervention (CAPTCHA, permission) endpoints
app.include_router(interventions_router)

# Tool approval endpoints (pre-execution approval for high-stakes tools)
app.include_router(approvals_router)

# Chat completions endpoint (main chat with unified flow)
app.include_router(chat_completions_router)

# Tool discovery and metrics endpoints
app.include_router(tools_router)

# Internal endpoints (inter-service communication)
app.include_router(internal_router)

# WebSocket endpoints (research monitoring, browser control)
app.include_router(websockets_router)

# UI endpoints (file tree, repo browser)
app.include_router(ui_router)

# =============================================================================
# External Routers (Proxy to Tool Server)
# =============================================================================

# Chat endpoints (proxy to Tool Server)
app.include_router(chat_router, tags=["chat"])

# Turn history endpoints (proxy to Tool Server)
app.include_router(turns_router, prefix="/turns", tags=["turns"])

# Memory endpoints (proxy to Tool Server)
app.include_router(memory_router, prefix="/memory", tags=["memory"])

# Cache endpoints (proxy to Tool Server)
app.include_router(cache_router, prefix="/cache", tags=["cache"])

# Status endpoints (proxy to Tool Server) - routes already have paths
app.include_router(status_router, tags=["status"])

# Diff endpoints (proxy to Tool Server)
app.include_router(diff_router, prefix="/diff", tags=["diff"])

# =============================================================================
# Backward Compatibility Aliases
# =============================================================================

# Legacy endpoint aliases will be added here as endpoints are migrated
# from app_original.py to the new routers.
#
# Example:
# app.add_api_route("/v1/chat/completions", chat_completions, methods=["POST"])
# app.add_api_route("/transcripts", list_turns, methods=["GET"])

# =============================================================================
# Root and Static Page Endpoints
# =============================================================================


@app.get("/")
def web_index():
    """Serve the main web UI (new Svelte UI if built, otherwise legacy)."""
    from fastapi.responses import FileResponse, JSONResponse

    # Prefer new Svelte UI if available
    new_ui_index = Path("apps/ui/build/index.html")
    if new_ui_index.exists():
        return FileResponse(str(new_ui_index))

    # Fallback to legacy UI
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"ok": True, "hint": "No UI found - run: cd apps/ui && npm install && npm run build"})


@app.get("/browser_viewer")
def browser_viewer():
    """Serve noVNC browser viewer for CAPTCHA solving."""
    from fastapi.responses import FileResponse, JSONResponse

    viewer_path = STATIC_DIR / "browser_viewer.html"
    if viewer_path.exists():
        return FileResponse(str(viewer_path))
    return JSONResponse({"error": "Browser viewer not found"}, status_code=404)


@app.get("/vnc.html")
def vnc_html():
    """Serve VNC HTML page."""
    from fastapi.responses import FileResponse, JSONResponse

    vnc_path = STATIC_DIR / "vnc.html"
    if vnc_path.exists():
        return FileResponse(str(vnc_path))
    return JSONResponse({"error": "VNC page not found"}, status_code=404)


@app.get("/captcha.html")
def captcha_html():
    """Serve CAPTCHA solver page."""
    from fastapi.responses import FileResponse, JSONResponse

    captcha_path = STATIC_DIR / "captcha.html"
    if captcha_path.exists():
        return FileResponse(str(captcha_path))
    return JSONResponse({"error": "CAPTCHA page not found"}, status_code=404)


@app.get("/research_monitor")
def research_monitor():
    """Serve research monitor page."""
    from fastapi.responses import FileResponse, JSONResponse

    monitor_path = STATIC_DIR / "research_monitor.html"
    if monitor_path.exists():
        return FileResponse(str(monitor_path))
    return JSONResponse({"error": "Research monitor not found"}, status_code=404)


@app.get("/api/info")
async def api_info():
    """API info endpoint with service information."""
    from apps.services.gateway.dependencies import is_unified_flow_enabled

    return {
        "service": "Panda Gateway",
        "version": "5.0.0",
        "unified_flow_enabled": is_unified_flow_enabled(),
        "docs": "/docs",
        "health": "/healthz",
    }


@app.get("/transcripts")
@app.get("/transcripts/{path:path}")
def spa_transcripts(path: str = ""):
    """SPA fallback for /transcripts routes - serve new UI index for client-side routing."""
    from fastapi.responses import FileResponse, RedirectResponse

    new_ui_index = Path("apps/ui/build/index.html")
    if new_ui_index.exists():
        return FileResponse(str(new_ui_index))
    # Fallback to legacy transcripts page
    return RedirectResponse(url="/legacy/transcripts.html")


# =============================================================================
# Note on Migration
# =============================================================================

# The following endpoints from app_original.py still need to be migrated:
#
# Chat Processing:
#   - POST /v1/chat/completions (main chat endpoint with unified flow)
#
# WebSocket Endpoints:
#   - WebSocket /ws/research/{session_id}
#   - WebSocket /novnc_ws
#   - WebSocket /ws/browser_control/{session_id}
#   - WebSocket /ws/browser-stream/{stream_id}
#
# Debug Endpoints:
#   - GET/POST /debug/* (21 endpoints)
#
# UI Endpoints:
#   - GET /ui/log (not yet migrated)
#
# Prompt Management:
#   - GET /prompts
#   - GET /prompts/{name}
#   - POST /prompts/{name}
#   - POST /prompts/{name}/backup
#   - POST /prompts/{name}/restore
#
# Broker Endpoints:
#   - GET /broker/{topic}
#   - POST /broker/{topic}
#   - DELETE /broker/{topic}
#   - GET /broker/list
#
# Policy Endpoints:
#   - GET /policy
#   - POST /policy
#
# Tool Endpoints:
#   - POST /tool/execute
#   - GET /teach/tools
#
# Crawl Endpoints:
#   - POST /crawl/url
#   - POST /crawl/batch
#   - POST /crawl/smart
#
# Continue Relay:
#   - POST /continue/relay
#
# Static Pages:
#   - GET /browser_viewer
#   - GET /vnc.html
#   - GET /captcha.html
#   - GET /research_monitor
#
# Contract Debug:
#   - GET/POST /debug/contracts/*
#   - GET /debug/circuit-breaker
#   - GET /debug/token-budget
#
# These endpoints will be gradually migrated to the routers/ directory.
# Until then, they can be accessed by running app_original.py instead.
