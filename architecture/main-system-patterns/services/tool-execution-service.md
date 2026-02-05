# Tool Execution Service

**Port:** 8090
**Type:** MCP Tool Execution Service
**Code:** `apps/services/tool_server/`

---

## Overview

The Tool Server is a FastAPI service that executes MCP-style tools on behalf of the Gateway.
It is **NOT a pipeline phase** — it's a separate service that the Coordinator (Phase 5)
invokes as part of workflow execution (tools are embedded in workflows).

```
Gateway (port 9000)
    │
    │ Phase 5: Coordinator selects workflow → workflow decomposes into tool calls
    │
    ▼
Tool Server (port 8090)
    │
    ├── file.read, file.write, file.edit
    ├── git.status, git.commit, git.push
    ├── bash.execute
    ├── internet.research
    ├── memory.create, memory.query
    └── ... (all MCP tools)
```

---

## Single-Model Integration

The Tool Server is called by the **Coordinator (Phase 5)** as part of workflow execution, using the
**Qwen3-Coder-30B-AWQ** model (same model used for all roles).

| Component | Model | Tool Server Interaction |
|-----------|-------|------------------------|
| Coordinator | Qwen3-Coder-30B-AWQ | **Primary caller** - selects workflows and issues tool calls |
| Vision | EasyOCR | OCR-based text extraction from images |

The Coordinator's workflow decisions are decomposed into tool calls sent to the Tool Server, which executes the
actual operations (file I/O, git, research, etc.) and returns results for synthesis.

---

## Architecture

```
apps/services/tool_server/app.py      # FastAPI application
    │
    ├── apps/services/tool_server/    # Tool implementations
    │   ├── internet_research_mcp.py  # Web research
    │   ├── memory_store.py           # Memory operations
    │   ├── captcha_intervention.py   # Human-in-loop for CAPTCHAs
    │   └── ...
    │
    └── apps/services/tool_server/shared/  # Shared utilities
        ├── llm_utils.py              # LLM client wrapper
        └── browser_factory.py        # Playwright browser management
```

---

## Tool Categories

### Always Available (Chat + Code Mode)

| Endpoint | Description |
|----------|-------------|
| `/file.read` | Read file contents |
| `/file.glob` | Find files by pattern |
| `/file.grep` | Search file contents |
| `/code.search` | Semantic code search |
| `/git.status` | Repository status |
| `/git.diff` | View changes |
| `/git.log` | Commit history |
| `/internet.research` | Web research (SSE streaming) |
| `/memory.create` | Create memory entry |
| `/memory.query` | Query memories |
| `/doc.search` | Search documentation |

### Code Mode Only

| Endpoint | Description |
|----------|-------------|
| `/file.write` | Write file contents |
| `/file.edit` | Edit file with diff |
| `/file.create` | Create new file |
| `/file.delete` | Delete file |
| `/git.add` | Stage changes |
| `/git.commit` | Create commit |
| `/git.push` | Push to remote |
| `/bash.execute` | Run shell command |
| `/code.apply_patch` | Apply code patches |
| `/test.run` | Run test suite |

---

## Key Endpoints

### `/internet.research` (SSE Streaming)

The primary research tool. Implements multi-phase web research:
- Phase 1: Intelligence gathering (forums, reviews)
- Phase 2: Product extraction (vendor sites)

See: `architecture/main-system-patterns/workflows/internet-research-mcp/`

### `/file.edit`

Applies structured edits to files:
```json
{
  "file_path": "<file_path>",
  "edits": [
    {"start_line": <start>, "end_line": <end>, "new_content": "<content>"}
  ]
}
```

### `/bash.execute`

Executes shell commands with sandboxing:
```json
{
  "command": "<command>",
  "timeout": <seconds>,
  "cwd": "<project_path>"
}
```

---

## Phase API (Legacy)

The Tool Server exposes pipeline phases as independent HTTP endpoints via `apps/services/tool_server/phase_api.py`:

| Endpoint | Phase | Purpose |
|----------|-------|---------|
| `POST /phases/0-query-analyzer` | Legacy Phase 0 | Query analysis (pre‑Phase 1 naming) |
| `POST /phases/1-reflection` | Legacy Phase 1 | Context sufficiency check (reflection gate removed) |
| `POST /phases/2-context-gatherer` | Legacy Phase 2 | Context gathering (superseded by Phase 2.1/2.2/2.5) |
| ... | ... | ... |

**Note:** These endpoints are legacy and intended for external callers that have not migrated to the current Phase 1/1.5/2.1/2.2/2.5 naming.

These endpoints use the stateless phase classes in `apps/phases/` — NOT the Gateway's orchestration handlers in `libs/gateway/orchestration/`.

**Use case:** External workflow engines (n8n) can call individual phases independently without running the full pipeline. Each endpoint accepts a context document and returns the phase output.

**Important:** The Gateway does NOT use these endpoints. It runs phases locally via its own orchestration handlers which add loop control, retry tracking, and document accumulation on top of the base phase logic.

See `gateway_processes.md` § "Service Boundary" for the full separation rationale.

---

## Configuration

```bash
# Tool server port
TOOL_SERVER_PORT=8090

# Browser settings for research
BROWSER_HEADLESS=true
PLAYWRIGHT_TIMEOUT_MS=30000

# Research settings
MIN_SUCCESSFUL_VENDORS=3
RESEARCH_MAX_PASSES=3
```

---

## Related Documentation

- `architecture/main-system-patterns/phase4-executor.md` - How Executor makes tactical decisions
- `architecture/main-system-patterns/phase5-coordinator.md` - How Coordinator translates commands to workflow execution
- `architecture/main-system-patterns/workflows/internet-research-mcp/` - Research tool deep dive
- `architecture/main-system-patterns/services/gateway_processes.md` - Gateway service (pipeline orchestration)

---

**Last Updated:** 2026-02-04
