# Phase 4-6: Services Overview

**Dependencies:** Phases 1-3
**Priority:** High
**Estimated Effort:** 3-4 days combined

---

## Architecture Linkages

This section documents how each implementation decision traces back to the architecture documentation.

### vLLM Model Server (Port 8000)

**Architecture Reference:** `architecture/README.md`, `architecture/LLM-ROLES/llm-roles-reference.md`, `config/model-registry.yaml`

> From `architecture/README.md` (updated 2026-01-06):
> Hot Pool: ~3.3GB always loaded (MIND only - handles all text roles via temperature)
> Cold Pool: EYES loads on-demand (swaps with MIND, ~8-14s overhead)

**Why These Settings (vLLM Tested):** Port 8000 matches canonical service port. `gpu_memory_utilization: 0.80` tested stable. `max_model_len: 4096` tested (can increase to 8192). `--enforce-eager` required on WSL. Single MIND model serves all text roles (REFLEX, NERVES, MIND, VOICE) via temperature. Model swapping (MIND ↔ EYES) for vision tasks. SERVER accessed via remote API. Qwen3-0.6B (REFLEX) is NOT used.

---

### Orchestrator Service (Port 8090)

**Architecture Reference:** `architecture/services/orchestrator-service.md`, `architecture/main-system-patterns/code-mode-architecture.md`

> The Orchestrator is a FastAPI service that executes MCP-style tools on behalf of the Gateway. It is **NOT a pipeline phase** - it's a separate service that the Coordinator (Phase 4) calls.
>
> ```
> Gateway (port 9000) → Phase 4 Coordinator → Orchestrator (port 8090) → MCP tools
> ```

> **Defense-in-Depth:** The Orchestrator implements its own mode gate validation as a backup to the Gateway's permission system.

**Why Separate Service:** Orchestrator is tool execution, not a pipeline phase. Mode gate middleware (`write_tools` check) implements defense-in-depth - mode validated at multiple layers. Exception handlers for `InterventionRequired` and `ToolError` support fail-fast principle. Router organization (file_mcp, git_mcp, memory_mcp) matches architecture tool registry.

---

### Gateway Service (Port 9000)

**Architecture Reference:** `architecture/README.md`, `architecture/main-system-patterns/code-mode-architecture.md`

> | Service | Port | Purpose |
> |---------|------|---------|
> | Gateway | 9000 | Pipeline orchestration and routing |

> **API Flow:** Frontend includes `mode` in request payload → Gateway receives mode → Mode stored on context_doc → Mode passed through all phases

**Why Pipeline Orchestration:** Gateway's `/chat` endpoint instantiates `PipelineOrchestrator` for 8-phase execution. `ChatRequest` model includes `mode: str = "chat"` matching architecture API flow. WebSocket `/ws/chat` enables streaming for long-running operations. Injection endpoint `/inject` supports user intervention during research.

---

### Pipeline Orchestrator Class

**Architecture Reference:** `architecture/main-system-patterns/PLANNER_COORDINATOR_LOOP.md`, `architecture/main-system-patterns/phase6-validation.md`

> **Error Limits:**
> | Limit | Value |
> |-------|-------|
> | Max Planner-Coordinator iterations | 5 |
> | Max RETRY loops | 1 |
> | Max REVISE loops | 2 |

> **Key Principle:** The Orchestrator owns the loop. Planner decides. Coordinator executes.

> **Important:** The Validation phase only outputs a decision. The **Orchestrator** is responsible for tracking attempt counts, enforcing loop limits, routing to appropriate phase.

**Why Orchestrator Owns Loops:** `MAX_PLANNER_ITERATIONS = 5`, `MAX_RETRY_LOOPS = 1`, `MAX_REVISE_LOOPS = 2` match architecture exactly. Phase 1 CLARIFY short-circuits to user (early gate). Validation loop control: APPROVE exits, REVISE loops to Phase 5, RETRY loops to Phase 3. Orchestrator tracks and enforces attempt counts - phases only output decisions.

---

### Service Startup Order

**Architecture Reference:** `architecture/README.md`, `architecture/services/orchestrator-service.md`

> | Service | Port | Purpose |
> |---------|------|---------|
> | Gateway | 9000 | Pipeline orchestration |
> | vLLM | 8000 | LLM inference |
> | Orchestrator | 8090 | Tool execution |
> | Qdrant | 6333 | Vector database |
> | PostgreSQL | 5432 | Relational database |

**Why This Order:** Docker services (Qdrant, PostgreSQL) start first as infrastructure dependencies. vLLM starts second - models must be loaded before LLM calls. Orchestrator third - depends on vLLM for LLM-powered tools. Gateway last - depends on both vLLM and Orchestrator. Health checks ensure proper initialization order. PID tracking enables clean shutdown.

---

## Overview

This document covers the setup of the three main application services:
1. **vLLM Server** (Port 8000) - Model inference
2. **Orchestrator Service** (Port 8090) - Tool execution
3. **Gateway Service** (Port 9000) - Pipeline orchestration

---

## 1. vLLM Model Server (Port 8000)

### 1.1 Model Download (Simplified Stack - vLLM Tested)

```bash
#!/bin/bash
# scripts/download_models.sh

echo "=== Downloading PandaAI v2 Models (Simplified Stack) ==="

# Create models directory
mkdir -p models

# Download from HuggingFace

echo "Downloading MIND (Qwen3-Coder-30B-AWQ) - handles ALL text roles via temperature..."
huggingface-cli download cyankiwi/Qwen3-Coder-30B-AWQ-4bit --local-dir models/Qwen3-Coder-30B-AWQ

echo "Downloading EYES (Qwen3-VL-2B) - vision tasks, swaps with MIND..."
huggingface-cli download Qwen/Qwen3-VL-2B-Instruct --local-dir models/Qwen3-VL-2B-Instruct

echo "Downloading Embedding model (CPU)..."
huggingface-cli download sentence-transformers/all-MiniLM-L6-v2 --local-dir models/all-MiniLM-L6-v2

# SERVER (Qwen3-Coder-30B) runs on remote machine - not downloaded here
# NOTE: Qwen3-0.6B (REFLEX) is NOT used - MIND handles classification

echo "=== Download Complete ==="
echo ""
echo "Model Summary:"
echo "  MIND:      models/Qwen3-Coder-30B-AWQ (~3.3GB VRAM)"
echo "             (handles REFLEX/NERVES/MIND/VOICE roles via temperature)"
echo "  EYES:      models/Qwen3-VL-2B-Instruct (~5GB VRAM, cold pool)"
echo "  Embedding: models/all-MiniLM-L6-v2 (CPU, no VRAM)"
echo "  SERVER:    Qwen3-Coder-30B (remote, configure SERVER_ENDPOINT in .env)"
echo ""
echo "NOT USED: Qwen3-0.6B (REFLEX) - MIND handles classification"
```

### 1.2 vLLM Startup Configuration (vLLM Tested)

**Single vLLM Instance (All Text Roles)**

```bash
#!/bin/bash
# scripts/start_vllm.sh

# Single MIND model handles ALL text roles via temperature
python -m vllm.entrypoints.openai.api_server \
    --host 0.0.0.0 \
    --port 8000 \
    --model models/Qwen3-Coder-30B-AWQ \
    --served-model-name mind \
    --gpu-memory-utilization 0.80 \
    --max-model-len 4096 \
    --enforce-eager \
    --trust-remote-code

# Notes:
# - Quantization auto-detected as "compressed-tensors" (not AWQ)
# - --enforce-eager required on WSL
# - REFLEX (Qwen3-0.6B) is NOT used - MIND handles classification
# - EYES loads on-demand via model swap (MIND ↔ EYES)
# - SERVER is accessed via remote API at SERVER_ENDPOINT
```

**Option B: Model Swapping (more likely needed)**

Since we have multiple models and limited VRAM, we may need to implement model swapping:

```python
# libs/llm/model_loader.py
"""Dynamic model loading for vLLM."""

import asyncio
from typing import Optional

from libs.core.config import get_settings


class ModelLoader:
    """Manages dynamic model loading in vLLM."""

    def __init__(self):
        self.settings = get_settings()
        self._current_models: set[str] = set()
        self._lock = asyncio.Lock()

    async def ensure_loaded(self, model_id: str) -> bool:
        """
        Ensure a model is loaded in vLLM.

        For hot pool models, they're always loaded.
        For EYES (cold pool), swap VOICE out if needed.
        """
        async with self._lock:
            if model_id in self._current_models:
                return True

            # Check if this is EYES (cold pool)
            if model_id == self.settings.models.eyes:
                await self._swap_for_eyes()
                return True

            return model_id in self._current_models

    async def _swap_for_eyes(self):
        """Swap VOICE for EYES."""
        # Unload VOICE
        # Load EYES
        # This requires vLLM API support for dynamic loading
        pass

    async def swap_back_voice(self):
        """Restore VOICE after EYES is done."""
        pass
```

### 1.3 Health Check

```bash
#!/bin/bash
# scripts/vllm_health.sh

curl -s http://localhost:8000/health && echo "vLLM: OK" || echo "vLLM: FAILED"
curl -s http://localhost:8000/v1/models | jq '.data[].id'
```

---

## 2. Orchestrator Service (Port 8090)

### 2.1 FastAPI Application

```python
# apps/orchestrator/app.py
"""Orchestrator service - MCP tool execution."""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from libs.core.config import get_settings
from libs.core.exceptions import InterventionRequired, ToolError


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    print(f"Orchestrator starting on port {settings.orchestrator.port}")
    yield
    # Shutdown
    print("Orchestrator shutting down")


app = FastAPI(
    title="PandaAI Orchestrator",
    description="MCP Tool Execution Service",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mode gate middleware
@app.middleware("http")
async def mode_gate_middleware(request: Request, call_next):
    """Check if tool requires code mode."""
    write_tools = {
        "/file/write", "/file/edit", "/file/create", "/file/delete",
        "/git/add", "/git/commit", "/git/push",
        "/bash/execute",
    }

    if request.url.path in write_tools:
        mode = request.headers.get("X-Pandora-Mode", "chat")
        if mode != "code":
            return JSONResponse(
                {"error": "Tool requires code mode"},
                status_code=403,
            )

    return await call_next(request)


# Exception handler
@app.exception_handler(InterventionRequired)
async def intervention_handler(request: Request, exc: InterventionRequired):
    """Handle intervention requests."""
    return JSONResponse(
        {
            "error": "intervention_required",
            "component": exc.component,
            "message": exc.error,
            "context": exc.context,
            "severity": exc.severity,
        },
        status_code=503,
    )


@app.exception_handler(ToolError)
async def tool_error_handler(request: Request, exc: ToolError):
    """Handle tool errors."""
    return JSONResponse(
        {
            "error": "tool_error",
            "tool": exc.tool,
            "message": exc.message,
            "context": exc.context,
        },
        status_code=500,
    )


# Health check
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "orchestrator"}


# Import and register tool routes
from apps.orchestrator.tools import file_mcp, git_mcp, memory_mcp

app.include_router(file_mcp.router, prefix="/file", tags=["file"])
app.include_router(git_mcp.router, prefix="/git", tags=["git"])
app.include_router(memory_mcp.router, prefix="/memory", tags=["memory"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "apps.orchestrator.app:app",
        host=settings.orchestrator.host,
        port=settings.orchestrator.port,
        reload=settings.dev_mode,
    )
```

### 2.2 File Tools Example

```python
# apps/orchestrator/tools/file_mcp.py
"""File operation MCP tools."""

from pathlib import Path
from typing import Optional
import fnmatch

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter()


class FileReadRequest(BaseModel):
    path: str
    encoding: str = "utf-8"


class FileReadResponse(BaseModel):
    content: str
    path: str
    size: int


@router.post("/read")
async def file_read(request: FileReadRequest) -> FileReadResponse:
    """Read file contents."""
    path = Path(request.path)

    if not path.exists():
        raise HTTPException(404, f"File not found: {request.path}")

    if not path.is_file():
        raise HTTPException(400, f"Not a file: {request.path}")

    try:
        content = path.read_text(encoding=request.encoding)
        return FileReadResponse(
            content=content,
            path=str(path),
            size=len(content),
        )
    except Exception as e:
        raise HTTPException(500, f"Error reading file: {e}")


class GlobRequest(BaseModel):
    pattern: str
    path: str = "."


class GlobResponse(BaseModel):
    matches: list[str]
    count: int


@router.post("/glob")
async def file_glob(request: GlobRequest) -> GlobResponse:
    """Find files matching pattern."""
    base = Path(request.path)

    if not base.exists():
        raise HTTPException(404, f"Path not found: {request.path}")

    matches = []
    for path in base.rglob(request.pattern):
        matches.append(str(path))

    return GlobResponse(matches=matches, count=len(matches))


class GrepRequest(BaseModel):
    pattern: str
    path: str = "."
    file_pattern: str = "*"


class GrepMatch(BaseModel):
    file: str
    line_number: int
    content: str


class GrepResponse(BaseModel):
    matches: list[GrepMatch]
    count: int


@router.post("/grep")
async def file_grep(request: GrepRequest) -> GrepResponse:
    """Search file contents."""
    import re

    base = Path(request.path)
    if not base.exists():
        raise HTTPException(404, f"Path not found: {request.path}")

    matches = []
    pattern = re.compile(request.pattern, re.IGNORECASE)

    for path in base.rglob(request.file_pattern):
        if not path.is_file():
            continue

        try:
            lines = path.read_text().splitlines()
            for i, line in enumerate(lines, 1):
                if pattern.search(line):
                    matches.append(GrepMatch(
                        file=str(path),
                        line_number=i,
                        content=line[:200],  # Truncate long lines
                    ))
        except Exception:
            continue  # Skip unreadable files

    return GrepResponse(matches=matches, count=len(matches))
```

---

## 3. Gateway Service (Port 9000)

### 3.1 FastAPI Application

```python
# apps/gateway/app.py
"""Gateway service - Pipeline orchestration."""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from libs.core.config import get_settings
from apps.gateway.pipeline.orchestrator import PipelineOrchestrator


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    print(f"Gateway starting on port {settings.gateway.port}")
    yield
    print("Gateway shutting down")


app = FastAPI(
    title="PandaAI Gateway",
    description="Pipeline Orchestration Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    query: str
    session_id: str
    mode: str = "chat"  # "chat" or "code"


class ChatResponse(BaseModel):
    response: str
    turn_number: int
    session_id: str


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy", "service": "gateway"}


@app.post("/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint.

    Executes the 8-phase pipeline.
    """
    orchestrator = PipelineOrchestrator(
        session_id=request.session_id,
        mode=request.mode,
    )

    result = await orchestrator.execute(request.query)

    return ChatResponse(
        response=result["response"],
        turn_number=result["turn_number"],
        session_id=request.session_id,
    )


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for streaming responses."""
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_json()

            orchestrator = PipelineOrchestrator(
                session_id=data["session_id"],
                mode=data.get("mode", "chat"),
            )

            # Stream phases
            async for update in orchestrator.execute_streaming(data["query"]):
                await websocket.send_json(update)

    except Exception as e:
        await websocket.close(code=1011, reason=str(e))


class InjectRequest(BaseModel):
    session_id: str
    message: str


@app.post("/inject")
async def inject_message(request: InjectRequest):
    """
    Inject message during research.

    Allows user to cancel, skip, or modify ongoing research.
    """
    # TODO: Implement injection system
    return {"status": "injected", "message": request.message}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "apps.gateway.app:app",
        host=settings.gateway.host,
        port=settings.gateway.port,
        reload=settings.dev_mode,
    )
```

### 3.2 Pipeline Orchestrator

```python
# apps/gateway/pipeline/orchestrator.py
"""Pipeline orchestrator - executes 8-phase pipeline."""

from typing import Any, AsyncIterator

from libs.core.config import get_settings
from libs.core.models import (
    ReflectionDecision,
    PlannerAction,
    ValidationDecision,
)
from libs.document_io.turn_manager import TurnManager
from libs.document_io.context_manager import ContextManager

# Phase imports (to be implemented)
# from apps.phases.phase0_query_analyzer import QueryAnalyzer
# from apps.phases.phase1_reflection import Reflection
# etc.


class PipelineOrchestrator:
    """Orchestrates the 8-phase pipeline."""

    MAX_PLANNER_ITERATIONS = 5
    MAX_RETRY_LOOPS = 1
    MAX_REVISE_LOOPS = 2

    def __init__(self, session_id: str, mode: str = "chat"):
        """
        Initialize orchestrator.

        Args:
            session_id: User session ID
            mode: "chat" or "code"
        """
        self.session_id = session_id
        self.mode = mode
        self.settings = get_settings()
        self.turn_manager = TurnManager(session_id)

    async def execute(self, query: str) -> dict[str, Any]:
        """
        Execute the full pipeline.

        Args:
            query: User query

        Returns:
            Result dict with response, turn_number, etc.
        """
        # Create turn
        turn_number, context = self.turn_manager.create_turn(query)

        try:
            # Phase 0: Query Analyzer
            analysis = await self._run_phase_0(query, context)

            # Phase 1: Reflection
            reflection = await self._run_phase_1(context)

            if reflection.decision == ReflectionDecision.CLARIFY:
                return self._clarify_response(reflection, turn_number)

            # Phase 2: Context Gatherer
            await self._run_phase_2(context)

            # Planner-Coordinator Loop
            retry_count = 0
            while retry_count <= self.MAX_RETRY_LOOPS:
                # Phase 3: Planner
                plan = await self._run_phase_3(context, attempt=retry_count + 1)

                if plan.route and plan.route.value == "clarify":
                    return self._clarify_response(plan, turn_number)

                # Phase 4: Coordinator (if needed)
                if plan.decision == PlannerAction.EXECUTE:
                    await self._run_planner_coordinator_loop(context, plan)

                # Phase 5: Synthesis
                synthesis = await self._run_phase_5(context)

                # Phase 6: Validation
                validation = await self._run_phase_6(context)

                if validation.decision == ValidationDecision.APPROVE:
                    break
                elif validation.decision == ValidationDecision.REVISE:
                    # REVISE loops back to Phase 5
                    for revise_attempt in range(self.MAX_REVISE_LOOPS):
                        synthesis = await self._run_phase_5(context, attempt=revise_attempt + 2)
                        validation = await self._run_phase_6(context, attempt=revise_attempt + 2)
                        if validation.decision == ValidationDecision.APPROVE:
                            break
                    break
                elif validation.decision == ValidationDecision.RETRY:
                    retry_count += 1
                    continue
                else:  # FAIL
                    return self._error_response(validation, turn_number)

            # Phase 7: Save
            await self._run_phase_7(context, turn_number)

            # Return response
            return {
                "response": synthesis.full_response,
                "turn_number": turn_number,
                "quality": validation.overall_quality,
            }

        except Exception as e:
            if self.settings.fail_fast:
                raise
            return self._error_response(str(e), turn_number)

    async def execute_streaming(self, query: str) -> AsyncIterator[dict]:
        """
        Execute pipeline with streaming updates.

        Yields:
            Progress updates for each phase
        """
        turn_number, context = self.turn_manager.create_turn(query)

        yield {"type": "start", "turn_number": turn_number}

        # Phase 0
        yield {"type": "phase", "phase": 0, "status": "running"}
        analysis = await self._run_phase_0(query, context)
        yield {"type": "phase", "phase": 0, "status": "complete"}

        # Continue with other phases...
        # (Similar pattern for each phase)

    async def _run_phase_0(self, query: str, context: ContextManager):
        """Run Phase 0: Query Analyzer."""
        # TODO: Implement
        pass

    async def _run_phase_1(self, context: ContextManager):
        """Run Phase 1: Reflection."""
        # TODO: Implement
        pass

    async def _run_phase_2(self, context: ContextManager):
        """Run Phase 2: Context Gatherer."""
        # TODO: Implement
        pass

    async def _run_phase_3(self, context: ContextManager, attempt: int = 1):
        """Run Phase 3: Planner."""
        # TODO: Implement
        pass

    async def _run_planner_coordinator_loop(self, context: ContextManager, plan):
        """Execute Planner-Coordinator loop."""
        iteration = 0
        while iteration < self.MAX_PLANNER_ITERATIONS:
            iteration += 1

            # Run Coordinator
            result = await self._run_phase_4(context, plan, iteration)

            # Check if done
            if result.action == "DONE":
                break

            # Run Planner again
            plan = await self._run_phase_3(context)
            if plan.decision == PlannerAction.COMPLETE:
                break

    async def _run_phase_4(self, context: ContextManager, plan, iteration: int):
        """Run Phase 4: Coordinator."""
        # TODO: Implement
        pass

    async def _run_phase_5(self, context: ContextManager, attempt: int = 1):
        """Run Phase 5: Synthesis."""
        # TODO: Implement
        pass

    async def _run_phase_6(self, context: ContextManager, attempt: int = 1):
        """Run Phase 6: Validation."""
        # TODO: Implement
        pass

    async def _run_phase_7(self, context: ContextManager, turn_number: int):
        """Run Phase 7: Save."""
        # TODO: Implement
        pass

    def _clarify_response(self, result, turn_number: int) -> dict:
        """Build clarification response."""
        return {
            "response": f"I need some clarification: {result.reasoning}",
            "turn_number": turn_number,
            "needs_clarification": True,
        }

    def _error_response(self, error, turn_number: int) -> dict:
        """Build error response."""
        return {
            "response": f"I encountered an error: {error}",
            "turn_number": turn_number,
            "error": True,
        }
```

---

## 4. Startup Order

```bash
#!/bin/bash
# scripts/start.sh (complete version)

set -e

echo "=== Starting PandaAI v2 ==="

# Load environment
source .env 2>/dev/null || true

# 1. Start Docker services
echo "[1/4] Starting Docker services..."
docker compose up -d

# Wait for Docker services
echo "  Waiting for Qdrant..."
until curl -s http://localhost:6333/health > /dev/null 2>&1; do sleep 1; done
echo "  ✓ Qdrant ready"

echo "  Waiting for PostgreSQL..."
until docker compose exec -T postgres pg_isready -U pandora > /dev/null 2>&1; do sleep 1; done
echo "  ✓ PostgreSQL ready"

# 2. Start vLLM
echo "[2/4] Starting vLLM..."
python -m vllm.entrypoints.openai.api_server \
    --host 0.0.0.0 \
    --port 8000 \
    --model meta-llama/Llama-3.1-8B-Instruct \
    --gpu-memory-utilization 0.90 \
    > logs/vllm.log 2>&1 &
VLLM_PID=$!
echo "  vLLM started (PID: $VLLM_PID)"

# Wait for vLLM
until curl -s http://localhost:8000/health > /dev/null 2>&1; do sleep 2; done
echo "  ✓ vLLM ready"

# 3. Start Orchestrator
echo "[3/4] Starting Orchestrator..."
python -m uvicorn apps.orchestrator.app:app \
    --host 0.0.0.0 \
    --port 8090 \
    > logs/orchestrator.log 2>&1 &
ORCH_PID=$!
echo "  Orchestrator started (PID: $ORCH_PID)"

# Wait for Orchestrator
until curl -s http://localhost:8090/health > /dev/null 2>&1; do sleep 1; done
echo "  ✓ Orchestrator ready"

# 4. Start Gateway
echo "[4/4] Starting Gateway..."
python -m uvicorn apps.gateway.app:app \
    --host 0.0.0.0 \
    --port 9000 \
    > logs/gateway.log 2>&1 &
GW_PID=$!
echo "  Gateway started (PID: $GW_PID)"

# Wait for Gateway
until curl -s http://localhost:9000/health > /dev/null 2>&1; do sleep 1; done
echo "  ✓ Gateway ready"

echo ""
echo "=== PandaAI v2 Started ==="
echo ""
echo "Services:"
echo "  Gateway:      http://localhost:9000"
echo "  Orchestrator: http://localhost:8090"
echo "  vLLM:         http://localhost:8000"
echo "  Qdrant:       http://localhost:6333"
echo "  PostgreSQL:   localhost:5432"
echo ""
echo "PIDs saved to .pids"
echo "$VLLM_PID $ORCH_PID $GW_PID" > .pids
```

---

## 5. Verification Checklist

- [ ] vLLM server starts and loads model(s)
- [ ] vLLM health endpoint responds
- [ ] Orchestrator starts and connects to vLLM
- [ ] Orchestrator health endpoint responds
- [ ] Gateway starts and connects to Orchestrator
- [ ] Gateway health endpoint responds
- [ ] `/chat` endpoint accepts requests (returns placeholder)
- [ ] Mode gate middleware blocks write operations in chat mode

---

## Deliverables Summary

| Service | Port | Main File |
|---------|------|-----------|
| vLLM | 8000 | (external) |
| Orchestrator | 8090 | `apps/orchestrator/app.py` |
| Gateway | 9000 | `apps/gateway/app.py` |

---

**Previous Phase:** [03-DOCUMENT-IO.md](./03-DOCUMENT-IO.md)
**Next Phase:** [05-PIPELINE-PHASES.md](./05-PIPELINE-PHASES.md)
