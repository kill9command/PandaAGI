# Pandora

Version: 7.0 | Updated: 2026-02-03 | Hardware: RTX 3090 (24GB VRAM)

**Full documentation index:** [`architecture/INDEX.md`](INDEX.md)
**Design workflow:** [`ActualDesignInstructions.md`](../ActualDesignInstructions.md)

---

## Goal

Pandora is a self-adapting agent that interfaces with all digital systems on behalf of its user. It reads documents, writes files, searches the web, manages email, navigates calendars, builds tools it doesn't have yet, and improves itself by learning from every interaction. It runs locally on consumer hardware.

The end state is an agent that can handle any task a human does at a computer — not by having every tool pre-built, but by understanding what's needed and building or adapting to get it done.

---

## How It Gets There

Pandora reaches that goal through three capabilities, built in order:

1. **Reliable pipeline** — A multi-phase document pipeline that takes a user query, gathers context, plans an approach, executes tools, synthesizes a response, validates it, and saves state. Every phase has a defined contract. If the pipeline produces incorrect output, the architecture is wrong and gets fixed before the code.

2. **Tool breadth** — The ability to interface with the digital systems people actually use: files, spreadsheets, documents, PDFs, email, calendars, web browsers, APIs, code execution. Each tool family has a defined interface. Missing tool families are built by the system itself when possible.

3. **Self-adaptation** — The system creates new tools and workflows when existing ones can't handle a task. It plans from the original query, backtracks when goals fail, and learns from failures. Over time it accumulates capabilities without human intervention.

---

## Current Architecture

### Single-Model System

One LLM (Qwen3-Coder-30B-AWQ) plays all roles. Behavior is controlled by temperature and system prompts, not by switching models.

| Role | Temperature | Purpose |
|------|-------------|---------|
| NERVES | 0.3 | Compression, summarization |
| REFLEX | 0.4 | Classification, binary decisions |
| MIND | 0.6 | Reasoning, planning |
| VOICE | 0.7 | User dialogue |

| Component | Model | Server | Notes |
|-----------|-------|--------|-------|
| All text roles | Qwen3-Coder-30B-AWQ | vLLM (:8000) | Single model |
| Vision | EasyOCR | CPU | OCR-based extraction |
| Embedding | all-MiniLM-L6-v2 | CPU | Semantic search |

### 8-Phase Pipeline (Phase 2 Split into 2.1/2.2)

Every user query flows through this pipeline. Each phase reads the accumulated `context.md` document, does its work, and writes its section for the next phase.

| Phase | Name | Role | Purpose |
|-------|------|------|---------|
| 1 | Query Analyzer | REFLEX | Resolve references, capture user purpose + data requirements, validate analysis |
| 2.1 | Context Retrieval | MIND | Identify relevant sources (turns, memory, cache) |
| 2.2 | Context Synthesis | MIND | Compile gathered context into §2 |
| 3 | Planner | MIND | Define goals and strategic approach |
| 4 | Executor | MIND | Produce tactical commands |
| 5 | Coordinator | REFLEX | Translate commands to tool calls, execute tools |
| 6 | Synthesis | VOICE | Generate user-facing response |
| 7 | Validation | MIND | Verify accuracy, approve or retry |
| 8 | Save | Procedural | Persist turn, update indexes |

**Validation helpers:** Phase 1 and Phase 2 each include lightweight validator sub-phases:
- **Phase 1.5** Query Analyzer Validator (coherence + ambiguity check)
- **Phase 2.5** Context Gathering Validator (completeness + constraint coverage)

**Normalization policy:** Phase 1 outputs canonical fields directly; Phase 1.5 validates coherence and completeness.

### Document-Based IO

All state flows through documents per turn:

- `context.md` — Accumulated document. Each phase reads prior sections, writes its own.
- `plan_state.json` — Goals and execution progress.
- `toolresults.md` — Full tool outputs for synthesis and validation.

### Services

| Service | Port | Purpose |
|---------|------|---------|
| Gateway | 9000 | FastAPI webapp, pipeline orchestration |
| vLLM | 8000 | LLM inference |
| Orchestrator | 8090 | Tool execution |

### Workflow System

Declarative workflow definitions replace ad-hoc tool selection. The Planner selects a workflow, the Executor follows its steps, and the Coordinator translates each step to tool calls. When no workflow exists for a task, the system can build one.

### Tool Family Specs (Contracts)

Tool family specs define **the contract** for each capability family (spreadsheet, document, PDF, email, calendar, etc.).  
They are **not** the same as workflows. A workflow is a sequence; a tool family spec is the required interface.

**Rule:** a tool family spec must exist **before or alongside** the first tool/workflow that uses it.  
If missing, the system must create the family spec as part of self‑extension.

### Self-Extension

Pandora can create new tools and workflows at runtime:
- Generate a tool spec (inputs, outputs, constraints)
- Generate implementation code
- Validate in a sandbox
- Register for use in future turns

---

## Design Principles

1. **Design before code** — Architecture docs are written first. Code implements the docs. If code doesn't match docs, fix one or the other until they agree.
2. **Single model** — One model handles all roles. Complexity comes from the pipeline, not the model stack.
3. **Document-based IO** — All phase communication goes through `context.md`. No hidden state.
4. **Quality over speed** — Correct answers matter more than fast answers.
5. **Context discipline** — Pass original queries to any LLM that makes decisions. Fix prompts, not code, when the LLM makes bad choices.
6. **Requirement-aware** — The original query carries all user requirements. Each phase reads §0 and interprets requirements naturally.
7. **Self-building** — The system creates tools and workflows it doesn't have yet.

---

## Benchmark Milestones

These benchmarks measure progress toward the ultimate goal. They are not the goal.

| Milestone | Target | Purpose |
|-----------|--------|---------|
| M1 | Self-extension | Tool and workflow creation at runtime |
| M2 | APEX tool families | Breadth across spreadsheet, document, PDF, email, calendar |
| M3 | Benchmark harness | Automated scoring and regression gates |
| M4 | DeepPlanning | Multi-step planning with backtracking and domain APIs |

**See:** `BENCHMARK_ALIGNMENT.md` for detailed gap analysis.

---

## Quick Start

```bash
./scripts/start.sh        # Start all services
./scripts/stop.sh         # Stop all services
./scripts/health_check.sh # Check service health
```

Access: `http://localhost:9000` (local) or via Cloudflare tunnel (remote).

---

## Documentation Map

| Need | Go To |
|------|-------|
| Full doc index | `architecture/INDEX.md` |
| Debugging protocol | `DEBUG.md` |
| Agent rules | `CLAUDE.md` |
| Design workflow | `ActualDesignInstructions.md` |
| Phase specifications | `main-system-patterns/phase*.md` |
| Concept docs | `concepts/*.md` |
| Benchmark gaps | `BENCHMARK_ALIGNMENT.md` |

---

Last Updated: 2026-02-04
