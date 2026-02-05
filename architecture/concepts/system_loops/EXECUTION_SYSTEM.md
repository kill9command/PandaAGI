# Execution System

**Version:** 3.0
**Updated:** 2026-02-03

---

## 1. Overview

The Execution System is a **3-tier architecture** that separates concerns across Phases 3–5:

- **Planner (Phase 3)** — Strategic: WHAT needs to be done (goals)
- **Executor (Phase 4)** — Tactical: HOW to accomplish goals (natural language commands)
- **Coordinator (Phase 5)** — Mechanical: Tool selection and execution

Each tier focuses on one level of abstraction. The Planner sets goals. The Executor determines steps. The Coordinator translates commands to tool calls.

When the Executor issues a command, the system first tries to match it against a **workflow** (a declarative tool sequence). If no workflow matches, the command falls through to the Coordinator for ad-hoc tool selection.

```
ORCHESTRATOR-MANAGED 3-TIER LOOP

  Phase 3: Planner ──────────────────────────► MIND (Strategic)
     │
     └── STRATEGIC_PLAN (goals, approach)
             │
             ▼
  ┌─────────────────────────────────────────────────────┐
  │          EXECUTOR-COORDINATOR LOOP                   │
  │                                                      │
  │  Phase 4: Executor ──────────────► MIND (Tactical)   │
  │     │                                                │
  │     ├── COMMAND → Try workflow match first            │
  │     │                ↓ (no match)                    │
  │     │            Phase 5: Coordinator ► MIND (Tool)  │
  │     │                └── Execute tool, return results │
  │     │                ↓                               │
  │     │            Results appended to §4              │
  │     │            Loop back to Executor               │
  │     │                                                │
  │     ├── ANALYZE → Process results (no tool call)     │
  │     │            Loop back to Executor               │
  │     │                                                │
  │     └── COMPLETE → Exit loop                         │
  └─────────────────────────────────────────────────────┘
             │
             └── Phase 6: Synthesis (VOICE)
```

---

## 2. Component Responsibilities

### 2.1 Orchestrator (Loop Owner)

| Responsibility | Description |
|----------------|-------------|
| Iteration tracking | Counts Executor iterations, enforces maximum |
| Phase transitions | Routes between Planner → Executor ⇄ Coordinator |
| RETRY handling | Loops back to Planner when Validation returns RETRY |
| REVISE handling | Loops back to Synthesis when Validation returns REVISE |
| §4 management | Ensures results are appended, not replaced |
| Context compression | Triggers NERVES if §4 exceeds token limits |

### 2.2 Planner (Phase 3) — Strategic

| Responsibility | Description |
|----------------|-------------|
| Goal definition | Creates STRATEGIC_PLAN with explicit goals |
| Routing decision | Decides executor (need action) or synthesis (can answer) |
| Approach definition | High-level strategy, not specific tools |
| Success criteria | How to know when goals are achieved |

### 2.3 Executor (Phase 4) — Tactical

| Responsibility | Description |
|----------------|-------------|
| Step planning | Determines next action to achieve goal |
| Natural language commands | Issues commands the Coordinator translates to tool calls |
| Goal tracking | Tracks progress on each goal |
| Result analysis | Reasons about accumulated results |
| Completion decision | Decides when goals are achieved |

### 2.4 Coordinator (Phase 5) — Tool Expert

| Responsibility | Description |
|----------------|-------------|
| Tool catalog ownership | Knows all available tools and signatures |
| Command translation | Converts natural language to tool calls |
| Tool execution | Calls MCP tools |
| Result formatting | Returns structured results with claims |
| Mode enforcement | Rejects code tools in chat mode |

---

## 3. Separation of Concerns

| Tier | Knows About | Does NOT Know About |
|------|-------------|---------------------|
| Planner | User goals, context | Tools, parameters |
| Executor | Goal progress, next step | Tool signatures, MCP servers |
| Coordinator | Tool catalog, signatures | Strategic goals, user intent |

This separation means:
- **Adding new tools** — only update Coordinator's catalog
- **Changing strategy** — only update Planner's prompts
- **Improving tactics** — only update Executor's prompts

---

## 4. Nested Loop Hierarchy

```
Level 0: Turn Loop (Orchestrator)
    └── Level 1: Planner invocation (once per turn, or on RETRY)
            └── Level 2: Executor-Coordinator Loop (bounded iterations)
                    └── Level 3: Tool Execution (internal to Coordinator)
```

The Orchestrator owns all loop limits and enforces them. See ERROR_HANDLING.md for specific limits.

---

## 5. Workflow System

The Workflow System provides **declarative, predictable tool sequences** that replace ad-hoc tool decisions. Instead of the Coordinator deciding which tools to use for each command, the Executor can select a workflow by name, and the workflow defines the exact tool sequence.

**Benefits:**
- Predictable execution paths
- Testable tool sequences
- Self-documenting behavior
- Reduced hallucination in tool selection

**Important:** Workflows do not define tool interfaces. Tool interfaces are defined by **Tool Family Specs** (see TOOL_SYSTEM.md). A workflow can only reference tools that conform to a family spec.

### 5.1 Workflow Structure

Workflows are markdown files with YAML frontmatter. Each workflow defines:

| Component | Purpose |
|-----------|---------|
| **Triggers** | When to activate (action values, patterns, literal matches) |
| **Inputs** | What the workflow needs (from query, context, or prior results) |
| **Steps** | Ordered tool calls with variable interpolation |
| **Outputs** | What the workflow produces |
| **Success criteria** | How to know it worked |
| **Fallback** | What to do on failure |

### 5.2 Trigger Types

| Type | Description | Example |
|------|-------------|---------|
| Action | Matches `user_purpose` + `data_requirements` from Phase 1 | `user_purpose: research cheapest ...` |
| Data requirement | Matches `data_requirements` fields | `needs_current_prices: true` |
| Pattern | Natural language with variable slots | `"find {product} for sale"` |
| Literal | Exact string match | `"search products"` |

### 5.3 Workflow Categories

| Category | Purpose |
|----------|---------|
| Research | Informational and commerce search workflows |
| Meta | Workflows for creating other workflows (self-building) |
| Utility | Common tool sequences (file operations, transformations) |

### 5.4 Workflow Bundles

Workflows can be packaged as **bundles** that include their own tools. This supports the self-building system — the Executor can create new workflow bundles at runtime. See SELF_BUILDING_SYSTEM.md for details.

---

## 6. Planner Workpad

The Planner can externalize short, structured notes into an **ephemeral workpad** while planning. This improves planning discipline without polluting long-term memory or context.md.

The workpad contains:
- **Tasks** — decomposed steps
- **Assumptions** — what the Planner is assuming
- **Constraints** — budget, scope, must-avoid from §0
- **Open questions** — unresolved ambiguities
- **Risks** — what could go wrong

The workpad is strictly ephemeral — it lives only within the current turn. The Executor and Validation phases may read it, but it is never persisted to memory.

---

## 7. Plan Critic (Optional)

Before execution begins, an optional **Critic** LLM pass reviews the plan against constraints and completeness. The Critic can only flag problems — it cannot modify the plan.

| Decision | Meaning |
|----------|---------|
| **PASS** | Plan is sound, proceed to execution |
| **REVISE** | Issues found, Planner must address them before proceeding |
| **BLOCK** | Fundamental problem, cannot proceed without clarification |

The Critic checks for:
- Missing constraints from §0
- Unanswered open questions from the workpad
- Goal-constraint conflicts

This is a lightweight quality gate — not a full validation cycle. It prevents obviously flawed plans from entering the Executor-Coordinator loop.

---

## 8. Fast Path: Skip Executor

When the Planner determines no tools are needed, it routes directly to Synthesis:

```
Planner: route_to: "synthesis"  →  Skip Executor and Coordinator  →  Phase 6: Synthesis
```

Examples: greetings, follow-ups on existing results, memory recall when §2 has the answer.

---

## 9. Multi-Task Loop

For complex requests with many sequential steps and dependencies, an **outer loop** wraps the standard execution system. The Planner detects multi-task scenarios and decomposes them into a task list.

Each task is executed independently through the full pipeline (Phases 3–7), with:
- **Fresh context per task** — prevents context overflow
- **Dependency tracking** — tasks can depend on prior tasks completing first
- **Per-task validation** — each task passes or fails independently
- **Learning persistence** — patterns learned from completed tasks are injected into subsequent task contexts

The outer loop terminates when all tasks pass, all remaining tasks are blocked, or the iteration limit is reached.

---

## 10. Termination Conditions

| Condition | Triggered By | Action |
|-----------|--------------|--------|
| Goals achieved | Executor says COMPLETE | Exit to Synthesis |
| Max iterations | Iteration limit reached | Force exit with warning |
| Blocked | Executor says BLOCKED | Create intervention |
| Consecutive tool failures | Multiple Coordinator errors | Executor reports BLOCKED |
| Planner routes to synthesis | Planner says route_to: synthesis | Skip Executor, go to Synthesis |

---

## 11. Related Documents

- `architecture/main-system-patterns/phase3-planner.md` — Planner specification
- `architecture/main-system-patterns/phase4-executor.md` — Executor specification
- `architecture/main-system-patterns/phase5-coordinator.md` — Coordinator specification
- `architecture/main-system-patterns/phase7-validation.md` — Validation and RETRY/REVISE
- `architecture/concepts/self_building_system/SELF_BUILDING_SYSTEM.md` — Workflow + tool self-creation
- `architecture/concepts/tools_workflows_system/TOOL_SYSTEM.md` — Tool families and sandbox
- `architecture/concepts/error_and_improvement_system/ERROR_HANDLING.md` — Loop limits and halt policy

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-24 | Initial specification for 3-tier architecture |
| 2.0 | 2026-02-03 | Merged with WORKFLOW_SYSTEM.md, removed deleted code refs |
| 3.0 | 2026-02-03 | Distilled to pure concept. Absorbed multi-task loop from RALPH_LOOP.md. Removed JSON/YAML/markdown examples, directory trees, token numbers, worked examples, and content duplicated in SELF_BUILDING_SYSTEM.md. |
| 3.1 | 2026-02-03 | Added Planner Workpad (§6) and Plan Critic (§7) from PLANNER_NOTEBOOKS.md. |

---

**Last Updated:** 2026-02-03
