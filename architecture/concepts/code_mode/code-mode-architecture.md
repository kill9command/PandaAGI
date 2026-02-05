# Code Mode Architecture

**Version:** 3.0
**Updated:** 2026-02-03

---

## 1. Core Principle

**Code Mode = Chat Mode + Write Tools**

The 9-phase pipeline (Phases 0–8) is identical for both modes. The only differences:

1. **Tool availability** — Code mode unlocks write operations
2. **Mode-specific recipes** — 4 phases load different prompts (Planner, Executor, Coordinator, Synthesis)
3. **Permission validation** — Write operations are gated by mode and repository scope

Everything else — query analysis, reflection, context gathering, validation, save — runs the same regardless of mode.

---

## 2. Mode Selection

The user selects `chat` or `code` mode. Mode is stored on the context document and passed through every phase. Default is `chat` (safe).

---

## 3. Tool Classification

| Category | Chat Mode | Code Mode |
|----------|-----------|-----------|
| **Research** | Web search, doc search, code search | Same |
| **Memory** | Create, query, update | Same |
| **File reading** | Read, glob, grep | Same |
| **Git reading** | Status, diff, log | Same |
| **File writing** | Blocked | Write, create, edit, delete, patch |
| **Git writing** | Blocked | Add, commit, push, pull, branch, PR |
| **Execution** | Blocked | Bash, test runner, sandbox |
| **Documents** | Blocked | Spreadsheet, DOCX, PDF generation |

**Rule:** Chat mode is read-only. Code mode adds write operations. No tool is available in chat but blocked in code.

---

## 4. Pipeline Divergence

| Phase | Name | Mode Behavior |
|-------|------|---------------|
| 0 | Query Analyzer | Unified |
| 1 | Reflection | Unified |
| 2 | Context Gatherer | Unified |
| **3** | **Planner** | **Mode-specific recipe** — code planner can plan file edits, git operations, test runs |
| **4** | **Executor** | **Mode-specific recipe** — code executor emits write-tool commands |
| **5** | **Coordinator** | **Mode-specific recipe + permission validation** — code coordinator executes write tools after permission checks |
| **6** | **Synthesis** | **Mode-specific recipe** — code synthesis uses file references, line numbers, status indicators |
| 7 | Validation | Unified |
| 8 | Save | Unified |

4 of 9 phases diverge. The divergence is recipe selection only — the pipeline structure never changes.

---

## 5. Permission System

Write operations pass through a multi-layer gate:

### Mode Gate
Every tool call is checked against the current mode. Write tools in chat mode are denied immediately. No exceptions.

### Repository Scope
Code mode operations target a **saved repository** — the project the user is working on. Operations within the saved repo are automatically allowed. Operations outside require explicit user approval.

### Defense-in-Depth
Mode enforcement happens at multiple layers independently:
- **Gateway** — Stores mode on request entry
- **Pipeline** — Passes mode through all phases
- **Recipe selection** — Loads mode-appropriate prompts
- **Orchestrator** — Validates mode header on every tool endpoint

Even if one layer is bypassed, the others enforce the gate.

---

## 6. Code Mode Capabilities

Code mode targets a comprehensive software engineering skill set. These are the capabilities the system should demonstrate:

### Test-Driven Development
Write the test first. Watch it fail. Write minimal code to pass. The system never produces code without a corresponding failing test. Tests use real code, not mocks (unless unavoidable). The Red-Green-Refactor cycle is the atomic unit of code production.

### Systematic Debugging
No fixes without root cause investigation. When encountering bugs, the system follows a disciplined process: read error messages completely, reproduce consistently, check recent changes, trace data flow to the source. Symptom fixes are treated as failures. After 3 failed fix attempts, the system escalates — recognizing an architectural problem rather than continuing to thrash.

### Verification Before Completion
Evidence before claims, always. The system never reports success without running the verification command and reading the output. "Should work" and "looks correct" are not acceptable — only fresh test output and exit codes constitute proof.

### Design Through Inquiry
Before building, the system explores requirements through focused questions — one at a time, each building on the last answer. When proposing approaches, it presents 2–3 options with concrete trade-offs rather than asking open-ended questions.

### Structured Planning
Implementation plans are comprehensive and assume zero codebase familiarity. Each task specifies exact file paths, complete code, exact test commands with expected output, and commit points. Tasks follow TDD granularity: write test → verify fail → implement → verify pass → commit.

### Task Isolation
Complex work is decomposed into independent sub-tasks. Each sub-task executes with a fresh context to prevent accumulated confusion. Results are reviewed in two stages: spec compliance first, then code quality.

---

## 7. Response Format

Code mode synthesis produces structured responses with:
- Status indicators (success/failure per operation)
- File references with line numbers (`auth.py:45-67`)
- Lists of modified files
- Test results summary
- Clear separation of what changed and why

Chat mode synthesis produces conversational natural language.

---

## 8. Related Documents

- Phase specs: `architecture/main-system-patterns/phase3-planner.md` through `phase6-synthesis.md`
- Tool system: `architecture/concepts/tools_workflows_system/TOOL_SYSTEM.md`
- Execution system: `architecture/concepts/system_loops/EXECUTION_SYSTEM.md`
- Superpowers reference: `architecture/references/superpowers-coding/`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial with full implementation walkthrough |
| 2.1 | 2026-01-06 | Updated for 9-phase pipeline, agent loop |
| 3.0 | 2026-02-03 | Distilled to pure concept. Removed implementation details, code paths, and phase-by-phase walkthrough. Added target capabilities from superpowers framework. |

---

**Last Updated:** 2026-02-03
