# Orchestrator Service

**Port:** 8090
**Type:** MCP Tool Execution Service

---

## Overview

The Orchestrator is a FastAPI service that executes MCP-style tools on behalf of the Gateway.
It is **NOT a pipeline phase** - it's a separate service that the Coordinator (Phase 4)
calls to execute tools.

```
Gateway (port 9000)
    │
    │ Phase 4: Coordinator decides tool calls
    │
    ▼
Orchestrator (port 8090)
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

The Orchestrator is called by the **Coordinator (Phase 4)**, which uses the
**Qwen3-Coder-30B-AWQ** model (same model used for all roles).

| Component | Model | Orchestrator Interaction |
|-----------|-------|--------------------------|
| Coordinator | Qwen3-Coder-30B-AWQ | **Primary caller** - decides which tools to invoke |
| Vision | EasyOCR | OCR-based text extraction from images |

The Coordinator's tool decisions are sent to the Orchestrator, which executes the
actual operations (file I/O, git, research, etc.) and returns results for synthesis.

---

## Architecture

```
apps/services/orchestrator/app.py     # FastAPI application
    │
    ├── apps/services/orchestrator/   # Tool implementations
    │   ├── internet_research_mcp.py  # Web research
    │   ├── memory_store.py           # Memory operations
    │   ├── captcha_intervention.py   # Human-in-loop for CAPTCHAs
    │   └── ...
    │
    └── apps/services/orchestrator/shared/  # Shared utilities
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

See: `architecture/mcp-tool-patterns/internet-research-mcp/`

### `/file.edit`

Applies structured edits to files:
```json
{
  "file_path": "src/auth.py",
  "edits": [
    {"start_line": 45, "end_line": 50, "new_content": "..."}
  ]
}
```

### `/bash.execute`

Executes shell commands with sandboxing:
```json
{
  "command": "pytest tests/",
  "timeout": 120,
  "cwd": "/project/path"
}
```

---

## Configuration

```bash
# Orchestrator port
ORCH_PORT=8090

# Browser settings for research
BROWSER_HEADLESS=true
PLAYWRIGHT_TIMEOUT_MS=30000

# Research settings
MIN_SUCCESSFUL_VENDORS=3
RESEARCH_MAX_PASSES=3
```

---

## Related Documentation

- `architecture/main-system-patterns/phase4-coordinator.md` - How Coordinator invokes tools
- `architecture/mcp-tool-patterns/internet-research-mcp/` - Research tool deep dive

---

**Last Updated:** 2026-01-09
