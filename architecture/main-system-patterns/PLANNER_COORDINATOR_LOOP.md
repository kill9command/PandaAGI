# Planner-Coordinator Loop

**Status:** SPECIFICATION
**Version:** 2.0
**Created:** 2025-12-28
**Last Updated:** 2026-01-05

---

## 1. Overview

The Planner-Coordinator Loop is an incremental planning pattern where:
- **Orchestrator** manages the loop (flow control, iteration limits, phase transitions)
- **Planner (Phase 3)** creates partial plans with immediate next steps
- **Coordinator (Phase 4)** executes tool requests and returns results
- **Loop continues** until Planner decides planning is complete

**Key Principle:** The Orchestrator owns the loop. Planner decides. Coordinator executes.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR-MANAGED LOOP                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ORCHESTRATOR                                                                │
│     │                                                                        │
│     ├── Tracks iteration count (max 5)                                       │
│     ├── Manages phase transitions                                            │
│     └── Handles RETRY/REVISE from Validation                                 │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     PLANNING LOOP                                    │    │
│  │                                                                      │    │
│  │  Phase 3: Planner ──────────────────────────► MIND                   │    │
│  │     │                                                                │    │
│  │     └── Decision: EXECUTE or COMPLETE                                │    │
│  │             │                                                        │    │
│  │             ▼                                                        │    │
│  │  Phase 4: Coordinator ───────────────────────► (thin executor)       │    │
│  │     │         └── Calls MCP tools                                    │    │
│  │     │         └── MCP tools have own internal loops                  │    │
│  │     │                                                                │    │
│  │     └── Results appended to §4                                       │    │
│  │             │                                                        │    │
│  │             ▼                                                        │    │
│  │  [Orchestrator loops back to Planner with updated §4]                │    │
│  │                                                                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│             │                                                                │
│             └── COMPLETE ──► Phase 5: Synthesis (VOICE)                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Responsibilities

### 2.1 Orchestrator (Loop Owner)

| Responsibility | Description |
|----------------|-------------|
| Iteration tracking | Counts loop iterations, enforces max 5 |
| Phase transitions | Routes between Planner → Coordinator → Planner |
| RETRY handling | Loops back to Planner when Validation returns RETRY |
| REVISE handling | Loops back to Synthesis when Validation returns REVISE |
| §4 management | Ensures results are appended, not replaced |
| Context compression | Triggers NERVES if §4 exceeds token limits |

### 2.2 Planner (Phase 3) - Decision Maker

| Responsibility | Description |
|----------------|-------------|
| Analyze context | Reads §0-§2 to understand query and available context |
| Create task plan | Decides what tools to call |
| Detect patterns | Identifies "remember that..." for memory.save calls |
| Multi-goal handling | Identifies and tracks multiple goals in complex queries |
| Decide completion | Outputs EXECUTE (need more tools) or COMPLETE (done) |

### 2.3 Coordinator (Phase 4) - Tool Executor

| Responsibility | Description |
|----------------|-------------|
| Tool registry | Knows which MCP tools are available |
| Tool execution | Calls MCP tools with parameters from ticket.md |
| Mode enforcement | Rejects code tools in chat mode |
| Result formatting | Formats tool results for §4 and toolresults.md |

**Key Point:** Coordinator is a thin layer. It does NOT make planning decisions or manage loops. Each MCP tool (like `internet.research`) has its own internal loop with its own LLM roles.

---

## 3. Nested Loop Hierarchy

### 3.1 Loop Levels Overview

Three loop mechanisms exist at different scopes:

```
Level 0: Turn Loop (Orchestrator)
    └── Level 1: Planner-Coordinator Loop (max 5 iterations)
            └── Level 2: Tool Execution Loops (tool-specific)
                    └── internet.research: max 3 passes
                    └── browser.navigate: max 10 page loads
                    └── code.execute: max 3 retries
```

### 3.2 Detailed Hierarchy

```
OUTER LOOP (Validation-driven, Orchestrator owns):
├── Max 1 RETRY (back to Phase 3 with preserved §4)
├── Max 2 REVISE (back to Phase 5 only)
└── After limits: FAIL

MIDDLE LOOP (Planner-Coordinator, Orchestrator manages):
├── Max 5 iterations per Planner invocation
├── §4 accumulates across iterations
└── Fresh counter on RETRY

INNER LOOP (MCP tool internal):
├── Each MCP tool has own loop (e.g., internet.research multi-phase)
├── Tool manages its own LLM calls
└── Returns final result to Coordinator
```

### 3.3 Iteration Counting Rules

1. **One Coordinator call = One Level 1 iteration**
   - Even if Coordinator calls multiple tools
   - Even if internet.research runs 3 internal passes

2. **Tool loops are internal to Coordinator**
   - internet.research with 3 passes counts as 1 Coordinator iteration
   - Tools manage their own retry/loop limits

3. **Token budgets are per-level**
   - Level 1: §4 accumulation budget (2,500 tokens)
   - Level 2: Tool-specific budgets (internet.research has its own)

### 3.4 Example Execution

```
Turn starts
├── Planner iteration 1 → route: coordinator
│   └── Coordinator calls internet.research
│       ├── Research pass 1 (internal)
│       ├── Research pass 2 (internal)
│       └── Research pass 3 (internal) → returns results
│   └── Coordinator writes 800 tokens to §4
├── Planner iteration 2 → route: coordinator (needs more)
│   └── Coordinator calls internet.research (different query)
│       └── Research pass 1 → sufficient → returns
│   └── Coordinator writes 600 tokens to §4
├── Planner iteration 3 → route: synthesis
│   └── (exits Planner-Coordinator loop)
└── Phase 5 Synthesis runs

Total: 3 Planner-Coordinator iterations, 4 research passes (internal)
```

### 3.5 Full Loop Count Example

A single turn could have:
- 5 Planner-Coordinator iterations (first attempt)
- Validation: RETRY
- 5 more Planner-Coordinator iterations (retry attempt)
- Total: 10 Coordinator executions possible

---

## 4. Planner Decision Format

### 4.1 EXECUTE Decision

When Planner needs tools executed:

```markdown
## 3. Task Plan

**Decision:** EXECUTE
**Reasoning:** Need to check memory before researching

### Todo
1. [in_progress] Search memory for laptop research
2. [pending] Review what we find
3. [pending] Decide if more research needed

### Tool Request
- **Tool:** memory.search
- **Args:** query="laptop", content_types=["vendor_info"]
```

### 4.2 COMPLETE Decision

When Planner has sufficient information:

```markdown
## 3. Task Plan

**Decision:** COMPLETE
**Reasoning:** Have sufficient information to answer

### Todo
1. [completed] Search memory for laptop research
2. [completed] Review - found fresh data
3. [completed] Route to synthesis

### Route To
synthesis
```

---

## 5. §4 Accumulation

### 5.1 Append Strategy

Each EXECUTE cycle **appends** new tool results to §4 (never replaces):

```markdown
## 4. Tool Execution

### Iteration 1
**Tool:** memory.search
**Result:** 1 document found (48h old, quality 0.75)

### Iteration 2
**Tool:** internet.research
**Result:** Found 15 laptops from 4 vendors
**Claims Extracted:**
| Claim | Confidence | Source |
|-------|------------|--------|
| HP Victus @ $649 | 0.90 | walmart.com |
| Lenovo LOQ @ $697 | 0.92 | bestbuy.com |
```

### 5.2 On RETRY from Validation

When Validation returns RETRY, new results are appended with attempt markers:

```markdown
## 4. Tool Execution

### Attempt 1 (original)
[SEARCH] query: "gaming laptops 2024"
Result: Found 5 candidates at Amazon, Best Buy
Error: Product page returned 404 (stale listing)

### Attempt 2 (retry)
[SEARCH] query: "gaming laptops RTX 4080 2024"
Result: Found 3 candidates at Newegg, B&H Photo
Confidence: 0.85
```

### 5.3 Token Budget Management

- §4 budget: 2500 tokens
- If §4 exceeds 2000 tokens (80% threshold), Orchestrator triggers NERVES compression:
  - Compress older iterations more aggressively
  - Preserve latest iteration in full
  - Keep key findings from all iterations
- If §4 would exceed 2500 tokens even after compression, Orchestrator forces COMPLETE

---

## 6. Termination Conditions

| Condition | Action | Owner |
|-----------|--------|-------|
| Planner says COMPLETE | Exit loop, route to Synthesis | Orchestrator |
| Max iterations (5) reached | Exit loop, route to Synthesis with warning | Orchestrator |
| Tool execution fails | HALT, create intervention | Orchestrator |
| Planner fails | HALT, create intervention | Orchestrator |

**Fail-Fast:** All errors HALT execution and create intervention requests. There are no fallbacks or silent retries.

---

## 7. Multi-Goal Query Handling

### 7.1 Goal Detection

Users often submit queries with multiple distinct goals:
- "Find a gaming laptop under $1500 and recommend a mechanical keyboard"
- "Compare iPhone 15 prices and find a good case for it"

Planner detects multiple goals through LLM analysis:

| Pattern | Example | Goals |
|---------|---------|-------|
| "and" conjunction | "Find laptops AND keyboards" | 2 |
| Comma-separated | "Get price, reviews, availability" | 3 |
| Dependent phrases | "Find a laptop and accessories for it" | 2 (with dependency) |

### 7.2 Goal Tracking in §3

```markdown
## 3. Task Plan

### Goals Identified

| ID | Description | Status | Dependencies |
|----|-------------|--------|--------------|
| GOAL_1 | Find gaming laptop under $1500 | in_progress | - |
| GOAL_2 | Recommend mechanical keyboard | pending | - |

### Current Focus
Addressing GOAL_1 first. Will research laptops, then proceed to GOAL_2.
```

### 7.3 Goal Dependencies

Some goals depend on others:

```markdown
### Goals Identified

| ID | Description | Status | Dependencies |
|----|-------------|--------|--------------|
| GOAL_1 | Find gaming laptop | in_progress | - |
| GOAL_2 | Find accessories for chosen laptop | blocked | GOAL_1 |
```

**Unblocking Rules:**
- Blocked goals unblock when dependency reaches COMPLETE
- Planner handles quality-based decisions (skip, retry, ask user)

### 7.4 Sequential Research Constraint

**Internet research must be sequential** (one at a time) due to:
- Anti-bot detection on websites
- Shared browser context
- Rate limiting from search engines

The Planner-Coordinator loop is already sequential, so multi-goal research naturally executes in order.

### 7.5 §4 Goal Attribution

Tool results indicate which goal they address:

```markdown
## 4. Tool Execution

### Iteration 1 (GOAL_1)
**Tool:** internet.research
**Goal:** GOAL_1 - Find gaming laptop under $1500
**Result:** Found 15 laptops from 4 vendors

### Iteration 2 (GOAL_2)
**Tool:** internet.research
**Goal:** GOAL_2 - Recommend mechanical keyboard
**Result:** Found 8 keyboards from 3 vendors
```

---

## 8. Multi-Goal Validation

Validation checks each goal individually (not averaging):

| Scenario | Outcome |
|----------|---------|
| All goals >= 0.80 quality | APPROVE |
| All goals >= 0.50, some < 0.80 | REVISE |
| Any goal < 0.50 | RETRY (for failed goal) |
| Some succeed, some have no data | APPROVE (partial) with acknowledgment |
| All goals failed | FAIL |

**Partial Success:** Response explicitly states: "I found X for goal 1, but could not find Y for goal 2."

---

## 9. Memory Pattern Detection

Planner is responsible for detecting memory-related patterns in queries:

| Pattern | Action |
|---------|--------|
| "remember that..." | Create memory.save tool call |
| "what's my favorite..." | Create memory.search tool call |
| "forget that..." | Create memory.delete tool call |

These become part of the task plan and are executed via Coordinator.

---

## 10. Flow Example

```
User: "Find me a gaming laptop under $1000"

ORCHESTRATOR: Start Planner-Coordinator loop

ITERATION 1:
├── Phase 3: Planner (MIND)
│   └── Decision: EXECUTE memory.search(query="laptop")
│
├── Phase 4: Coordinator
│   └── Calls memory.search MCP tool
│   └── Returns: 1 doc found, 48h old, quality 0.75
│
└── ORCHESTRATOR: Append to §4, loop back to Planner

ITERATION 2:
├── Phase 3: Planner (MIND) - sees §4 with stale data
│   └── Decision: EXECUTE internet.research(query="gaming laptop under $1000")
│
├── Phase 4: Coordinator
│   └── Calls internet.research MCP tool
│   └── [MCP tool runs its own internal research loop]
│   └── Returns: 15 laptops from 4 vendors
│
└── ORCHESTRATOR: Append to §4, loop back to Planner

ITERATION 3:
├── Phase 3: Planner (MIND) - sees §4 with good results
│   └── Decision: COMPLETE, route to synthesis
│
└── ORCHESTRATOR: Exit loop, proceed to Phase 5

Phase 5: Synthesis (VOICE)
Phase 6: Validation (MIND)
    └── APPROVE
Phase 7: Save
```

---

## 11. Incremental vs Full-Plan-Upfront

| Aspect | Full Plan Upfront (Old) | Incremental (Current) |
|--------|-------------------------|------------------------|
| Planner calls | Once per turn | Multiple (iterative) |
| Coordinator role | Executes full plan | Executes single step |
| Planner visibility | Sees results only on RETRY | Sees results after each step |
| Adaptation | Cannot adapt mid-plan | Adapts based on intermediate results |
| Wasted work | May execute unnecessary steps | Stops when sufficient data found |

---

## 12. Related Documents

- `architecture/main-system-patterns/phase3-planner.md` - Planner phase specification
- `architecture/main-system-patterns/phase4-coordinator.md` - Coordinator phase specification
- `architecture/main-system-patterns/phase6-validation.md` - Validation and RETRY/REVISE handling
- `architecture/LLM-ROLES/llm-roles-reference.md` - Model stack overview
- `architecture/DOCUMENT-IO-SYSTEM/MEMORY_ARCHITECTURE.md` - Memory integration

---

## 13. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-28 | Initial specification |
| 2.0 | 2026-01-05 | Clarified Orchestrator owns loop, Coordinator is thin executor, removed implementation code, added memory pattern detection |

---

**Last Updated:** 2026-01-05
