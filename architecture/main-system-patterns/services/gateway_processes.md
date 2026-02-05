# Gateway Service

**Port:** 9000
**Type:** Pipeline Orchestration Service

---

## Overview

The Gateway is a FastAPI service that orchestrates the 8-phase pipeline (Phases 1-8) with internal sub-phases (1.5, 2.1, 2.2, 2.5). It is the primary entry point for all user requests and manages the entire turn lifecycle: query analysis, context retrieval/synthesis, planning, execution, synthesis, validation, and persistence.

The Gateway runs all pipeline phases **locally** — it does not delegate phase logic to other services. The only external service call is to the Tool Server (port 8090) for workflow execution during Phase 5.

```
User Request → Gateway (port 9000)
                  │
                  ├── Phase 1: Query Analyzer
                  ├── Phase 1.5: Query Analyzer Validator
                  ├── Phase 2.1: Context Retrieval
                  ├── Phase 2.2: Context Synthesis
                  ├── Phase 2.5: Context Validator
                  ├── Phase 3: Planner
                  ├── Phase 4: Executor ──────┐
                  ├── Phase 5: Coordinator ───┼──► Tool Server (port 8090)
                  │       ▲                   │    Tool execution (within workflows)
                  │       └───── loop ────────┘
                  ├── Phase 6: Synthesis
                  ├── Phase 7: Validation
                  └── Phase 8: Save
```

---

## Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| **App factory** | `apps/services/gateway/app.py` | FastAPI application, route registration, middleware |
| **UnifiedFlow** | `libs/gateway/unified_flow.py` | Main entry point — receives chat requests, delegates to RequestHandler |
| **RequestHandler** | `libs/gateway/orchestration/request_handler.py` | Phase coordinator — runs Phases 1-8 with loop control |
| **ContextDocument** | `libs/gateway/context/context_document.py` | Accumulating document model (§0-§7) |
| **Tool Server client** | `apps/services/gateway/services/tool_server_client.py` | HTTP client for tool execution calls (invoked by workflows) |

---

## Pipeline Orchestration

The RequestHandler runs the pipeline in a loop that supports validation-driven retries:

```
RequestHandler.run()
    │
    ├── Phase 1: Query Analyzer
    ├── Phase 1.5: Query Analyzer Validator (gate)
    ├── Phase 2.1: Context Retrieval
    ├── Phase 2.2: Context Synthesis (draft §2)
    ├── Phase 2.5: Context Validator (commit §2 on pass)
    │
    └── VALIDATION LOOP (max retries: 3)
        │
        ├── Phase 3-5: Planning + Execution
        │   ├── Phase 3: Planner (strategic goals)
        │   ├── Phase 4: Executor (tactical commands)
        │   └── Phase 5: Coordinator (workflow calls)
        │       └── calls Tool Server (port 8090) for tool execution within workflows
        │
        ├── Phase 6: Synthesis (draft response)
        │
        └── Phase 7: Validation
            ├── APPROVE → break loop, proceed to Phase 8
            ├── RETRY → archive attempt, loop back to Phase 3
            └── FAIL → use best-seen response or fallback
```

### Validation Routing

| Decision | Action | Detail |
|----------|--------|--------|
| **APPROVE** | Exit loop | Response passes all quality checks |
| **RETRY** | Loop to Phase 3 | Archives current attempt, writes retry context, invalidates failed claims, optionally corrects workflow |
| **FAIL** | Exit loop | Uses highest-confidence response seen across all attempts, or fallback error message |

The Gateway tracks the **best-seen response** across retry iterations. If all attempts fail, it returns the response with the highest validation confidence rather than a bare error.

---

## Context Document Flow

The ContextDocument accumulates through phases as sections §0-§7:

| Section | Phase | Content |
|---------|-------|---------|
| §0 | Phase 1 | User query, resolved query, user purpose, data requirements |
| §1 | Phase 1.5 | Query Analyzer validation (pass/retry/clarify) |
| §2 | Phase 2.2 | Gathered context (prior turns, research cache, memory) — committed after Phase 2.5 pass |
| §3 | Phase 3 | Strategic plan (goals, route, workflow intent) |
| §4 | Phases 4-5 | Execution progress (commands, workflow results, claims) |
| §5 | (reserved) | |
| §6 | Phase 6 | Synthesis preview + validation checklist |
| §7 | Phase 7 | Validation result (decision, confidence, issues) |

The ContextDocument is the single working document that flows through all phases. Each phase reads prior sections and appends its own. On retry, §7 accumulates (Attempt 1, Attempt 2, etc.).

---

## Tool Server Integration

The Gateway calls the Tool Server for workflow execution during Phase 5 (Coordinator). The Coordinator selects a workflow, and the WorkflowManager decomposes it into tool calls executed by the Tool Server.

| Aspect | Detail |
|--------|--------|
| **Protocol** | HTTP POST to `http://127.0.0.1:8090/{tool_name}` |
| **Streaming** | SSE for `internet.research` (long-running research) |
| **Protection** | Circuit breaker on Tool Server calls |
| **Timeouts** | Per-tool timeout configuration |

The Gateway does NOT call the Tool Server for pipeline phases. All phase logic (LLM calls, document management, loop control) runs within the Gateway process.

---

## Route Structure

The Gateway serves two categories of routes:

### Local Processing (`routers/`)

Routes that the Gateway handles directly:

| Router | Purpose |
|--------|---------|
| `chat_completions.py` | Main `/v1/chat/completions` endpoint — entry point for all user turns |
| `health.py` | Health checks and readiness probes |
| `thinking.py` | SSE stream for real-time phase progress visualization |
| `jobs.py` | Async job management for long-running turns |
| `tools.py` | Tool discovery and workflow execution metrics |
| `interventions.py` | Human-in-loop prompts (CAPTCHAs, permissions) |
| `websockets.py` | Real-time research progress monitoring |
| `approvals.py` | Workflow pre-execution approval system |
| `transcripts.py` | Turn history access |

### Tool Server Proxy (`routes/`)

Routes that proxy to the Tool Server (port 8090):

| Router | Purpose |
|--------|---------|
| `memory.py` | Memory CRUD operations |
| `cache.py` | Research cache access |
| `turns.py` | Turn document access |
| `status.py` | System status |

---

## Phase Implementations

Each pipeline phase has a dedicated handler in `libs/gateway/orchestration/`:

| Phase | Handler | File |
|-------|---------|------|
| 1 | QueryAnalyzer (includes 1.5 validator) | `libs/gateway/phases/query_analyzer.py` |
| 2.1/2.2/2.5 | ContextGatherer2Phase (retrieval/synthesis/validation) | `libs/gateway/phases/context_gatherer_2phase.py` |
| 3 | PlanningLoop | `libs/gateway/orchestration/planning_loop.py` |
| 4 | ExecutorLoop | `libs/gateway/orchestration/executor_loop.py` |
| 5 | AgentLoop | `libs/gateway/orchestration/agent_loop.py` |
| 6 | SynthesisPhase | `libs/gateway/orchestration/synthesis_phase.py` |
| 7 | ValidationHandler | `libs/gateway/validation/validation_handler.py` |
| 8 | TurnSaver | `libs/gateway/persistence/turn_saver.py` |

Supporting modules:

| Module | Location | Purpose |
|--------|----------|---------|
| Workflow execution | `libs/gateway/execution/` | ToolExecutor, ToolCatalog, WorkflowManager |
| Context management | `libs/gateway/context/` | ContextDocument, document loading |
| Validation | `libs/gateway/validation/` | ValidationHandler, confidence scoring |
| Persistence | `libs/gateway/persistence/` | TurnSaver, TurnDirectory, DocumentWriter |
| LLM client | `libs/llm/` | vLLM client wrapper for all LLM calls |

---

## Service Boundary: Gateway vs Tool Server

The Gateway and Tool Server have distinct responsibilities with a clean boundary at the HTTP layer. This section documents the intentional design decisions at that boundary.

### Workflow Execution Split

The Gateway's `ToolExecutor` (`libs/gateway/execution/tool_executor.py`) is NOT a simple HTTP proxy. It handles:
- **Pre-execution:** Permission validation, constraint enforcement, approval tools
- **Dispatch:** Routes workflow tool calls to the Tool Server via HTTP POST
- **Post-execution:** Claims extraction from workflow results, §4 updates

The Tool Server receives clean tool requests and returns raw results. All orchestration logic (what to do with those results) stays in the Gateway.

### Memory Access Pattern

Memory operations use a **hybrid access pattern** — this is intentional, not a bug:

| Operation | Path | Reason |
|-----------|------|--------|
| **Memory search** (Phase 2.1/2.2) | Direct local access via `apps/tools/memory/` | Context retrieval/synthesis runs in-process; HTTP round-trip adds unnecessary latency for reads |
| **Memory create/delete** (Phase 5) | Via Tool Server HTTP (`/memory.create`, `/memory.query`) | Writes go through Tool Server for consistency and audit |

Phase 2's Context Gatherer (2.1/2.2) imports `apps.tools.memory.search_memory()` directly and reads from `panda_system_docs/obsidian_memory/`. This bypasses the Tool Server for read performance. If the Tool Server later needs to intercept memory reads (rate limiting, logging), this pattern would need to change.

### Turn Persistence Ownership

Turn documents are **written exclusively by the Gateway** (Phase 8, `TurnSaver`). The Tool Server has read-only turn endpoints (`GET /turns`). The Gateway proxy routes in `routes/turns.py` forward read requests to the Tool Server for the UI.

### Phase Implementations

Two sets of phase code exist — they serve different purposes:

| Location | Used By | Purpose |
|----------|---------|---------|
| `libs/gateway/orchestration/` | Gateway pipeline | Full orchestration handlers with loop control, context management, retry logic |
| `apps/phases/` | Tool Server Phase API | Stateless phase classes for independent execution via HTTP |

The Gateway uses `libs/gateway/orchestration/` for its pipeline. The Tool Server exposes `apps/phases/` via `POST /phases/{phase}` endpoints (in `phase_api.py`) for external callers like n8n to run individual phases independently.

These are **intentionally separate implementations** for different execution contexts. The Gateway handlers wrap the phase logic with orchestration concerns (loop state, document accumulation, retry tracking). The `apps/phases/` classes are simpler, stateless versions suitable for standalone invocation.

**Risk:** If phase logic changes, both implementations need updating. The `apps/phases/` classes should be treated as the canonical phase logic, with `libs/gateway/orchestration/` handlers wrapping them with orchestration concerns.

---

## Error Handling

The Gateway follows fail-fast principles at the service level:

| Error | Action |
|-------|--------|
| LLM call failure | Phase HALTs with intervention request |
| Tool Server unreachable | Circuit breaker opens, workflow call fails |
| Phase produces empty output | HALT — no silent continuation |
| Token budget exceeded | HALT — no blind truncation (NERVES compression triggered first) |
| Save failure (Phase 8) | HALT — partial saves create inconsistent state |

All phase-level errors create intervention requests. The Gateway does not attempt automatic recovery beyond the validation retry loop.

---

## Related Documentation

- `architecture/main-system-patterns/services/tool-execution-service.md` - Tool Server (workflow execution)
- `architecture/concepts/system_loops/EXECUTION_SYSTEM.md` - 3-tier execution loop architecture
- `architecture/concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` - context.md schema
- `architecture/concepts/system_loops/CONTEXT_COMPRESSION.md` - NERVES compression triggers
- `architecture/concepts/error_and_improvement_system/ERROR_HANDLING.md` - Fail-fast error handling

---

**Last Updated:** 2026-02-04
