# Planner-Executor-Coordinator Loop

**Status:** SPECIFICATION
**Version:** 1.0
**Created:** 2026-01-24
**Last Updated:** 2026-01-24

---

## 1. Overview

The Planner-Executor-Coordinator Loop is a 3-tier architecture that separates concerns:

- **Planner (Phase 3)** - Strategic: WHAT needs to be done (goals)
- **Executor (Phase 4)** - Tactical: HOW to accomplish goals (natural language commands)
- **Coordinator (Phase 5)** - Mechanical: Tool selection and execution

**Key Design Principle:** Each tier focuses on one level of abstraction. The Planner sets goals. The Executor determines steps. The Coordinator translates commands to tool calls.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR-MANAGED 3-TIER LOOP                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ORCHESTRATOR                                                                │
│     │                                                                        │
│     ├── Tracks iteration count                                               │
│     ├── Manages phase transitions                                            │
│     └── Handles RETRY/REVISE from Validation                                 │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    PLANNER-EXECUTOR-COORDINATOR LOOP                 │    │
│  │                                                                      │    │
│  │  Phase 3: Planner ─────────────────────────────► MIND (Strategic)    │    │
│  │     │                                                                │    │
│  │     └── Output: STRATEGIC_PLAN (goals, approach)                     │    │
│  │             │                                                        │    │
│  │             ▼                                                        │    │
│  │  ┌───────────────────────────────────────────────────────────────┐  │    │
│  │  │              EXECUTOR-COORDINATOR LOOP                         │  │    │
│  │  │                                                                │  │    │
│  │  │  Phase 4: Executor ─────────────────────► MIND (Tactical)      │  │    │
│  │  │     │                                                          │  │    │
│  │  │     ├── COMMAND: Natural language instruction                  │  │    │
│  │  │     │       ↓                                                  │  │    │
│  │  │     │   Phase 5: Coordinator ───────────► MIND (Tool Expert)   │  │    │
│  │  │     │       │                                                  │  │    │
│  │  │     │       └── Translate command to tool call                 │  │    │
│  │  │     │       └── Execute tool                                   │  │    │
│  │  │     │       └── Return results                                 │  │    │
│  │  │     │       ↓                                                  │  │    │
│  │  │     │   Results appended to §4                                 │  │    │
│  │  │     │       ↓                                                  │  │    │
│  │  │     │   Loop back to Executor                                  │  │    │
│  │  │     │                                                          │  │    │
│  │  │     ├── ANALYZE: Process results (no tool call)                │  │    │
│  │  │     │       ↓                                                  │  │    │
│  │  │     │   Analysis appended to §4                                │  │    │
│  │  │     │       ↓                                                  │  │    │
│  │  │     │   Loop back to Executor                                  │  │    │
│  │  │     │                                                          │  │    │
│  │  │     └── COMPLETE: Goals achieved                               │  │    │
│  │  │             ↓                                                  │  │    │
│  │  │         Exit loop                                              │  │    │
│  │  │                                                                │  │    │
│  │  └───────────────────────────────────────────────────────────────┘  │    │
│  │             │                                                        │    │
│  │             └── COMPLETE ──► Phase 6: Synthesis (VOICE)              │    │
│  │                                                                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Responsibilities

### 2.1 Orchestrator (Loop Owner)

| Responsibility | Description |
|----------------|-------------|
| Iteration tracking | Counts Executor iterations, enforces max 10 |
| Phase transitions | Routes between Planner → Executor ⇄ Coordinator |
| RETRY handling | Loops back to Planner when Validation returns RETRY |
| REVISE handling | Loops back to Synthesis when Validation returns REVISE |
| §4 management | Ensures results are appended, not replaced |
| Context compression | Triggers NERVES if §4 exceeds token limits |

### 2.2 Planner (Phase 3) - Strategic

| Responsibility | Description |
|----------------|-------------|
| Goal definition | Creates STRATEGIC_PLAN with explicit goals |
| Routing decision | Decides executor (need action) or synthesis (can answer) |
| Approach definition | High-level strategy, not specific tools |
| Success criteria | How to know when goals are achieved |

**Output:** `STRATEGIC_PLAN` with goals, approach, success_criteria

### 2.3 Executor (Phase 4) - Tactical

| Responsibility | Description |
|----------------|-------------|
| Step planning | Determines next action to achieve goal |
| Natural language commands | Issues commands like "search for laptops" |
| Goal tracking | Tracks progress on each goal |
| Result analysis | Reasons about accumulated results |
| Completion decision | Decides when goals are achieved |

**Output:** `EXECUTOR_DECISION` with action (COMMAND/ANALYZE/COMPLETE/BLOCKED)

### 2.4 Coordinator (Phase 5) - Tool Expert

| Responsibility | Description |
|----------------|-------------|
| Tool catalog ownership | Knows all available tools and signatures |
| Command translation | Converts natural language to tool calls |
| Tool execution | Calls MCP tools |
| Result formatting | Returns structured results with claims |
| Mode enforcement | Rejects code tools in chat mode |

**Output:** `COORDINATOR_RESULT` with tool selected, args, status, result, claims

---

## 3. Information Flow

### 3.1 Planner → Executor

```
Planner outputs STRATEGIC_PLAN:
{
  "goals": [
    {"id": "GOAL_1", "description": "Find cheap laptops"},
    {"id": "GOAL_2", "description": "Compare prices"}
  ],
  "approach": "Search products, filter by price",
  "success_criteria": "Found 3+ options with prices"
}

Executor receives goals and begins tactical planning.
```

### 3.2 Executor → Coordinator

```
Executor issues natural language command:
{
  "action": "COMMAND",
  "command": "Search for cheap laptops under $800 with good reviews"
}

Coordinator translates to tool call:
{
  "tool": "internet.research",
  "args": {"query": "cheap laptops under $800 good reviews", "mode": "commerce"}
}
```

### 3.3 Coordinator → Executor (Results)

```
Coordinator returns:
{
  "command_received": "Search for cheap laptops...",
  "tool_selected": "internet.research",
  "status": "success",
  "result": {findings: [...]},
  "claims": [
    {"claim": "HP Victus @ $649", "confidence": 0.90, "source": "walmart.com"}
  ]
}

Results formatted and appended to §4.
Executor sees results on next iteration.
```

---

## 4. Nested Loop Hierarchy

### 4.1 Loop Levels Overview

```
Level 0: Turn Loop (Orchestrator)
    └── Level 1: Planner invocation (once per turn, or on RETRY)
            └── Level 2: Executor-Coordinator Loop (max 10 iterations)
                    └── Level 3: Tool Execution (internal to Coordinator)
                            └── internet.research: max 3 passes
                            └── browser.navigate: max 10 page loads
```

### 4.2 Iteration Counting

| Level | Counter | Max | Reset On |
|-------|---------|-----|----------|
| Turn | turn_number | N/A | Never |
| Planner | planner_invocations | 2 | Never (RETRY limit) |
| Executor | executor_iterations | 10 | Each Planner invocation |
| Tool internal | varies | varies | Each Coordinator call |

### 4.3 Example Execution

```
Turn starts
├── Phase 3: Planner
│   └── Output: STRATEGIC_PLAN with 2 goals
│
├── Phase 4-5: Executor-Coordinator Loop
│   ├── Executor iteration 1
│   │   └── COMMAND: "Search for cheap laptops"
│   │   └── Coordinator: internet.research → 5 products
│   │
│   ├── Executor iteration 2
│   │   └── ANALYZE: Compare prices, select top 3
│   │
│   ├── Executor iteration 3
│   │   └── COMPLETE: Goals achieved
│   │
│   └── Exit loop
│
├── Phase 6: Synthesis
├── Phase 7: Validation → APPROVE
└── Phase 8: Save
```

---

## 5. Section 4 Format

### 5.1 Structure

```markdown
## 4. Execution Progress

### Strategic Plan
**Goals:**
- GOAL_1: Find cheap laptops under $800
- GOAL_2: Compare and rank options

**Approach:** Search products, compare prices, identify best value

---

### Executor Iteration 1
**Goal Focus:** GOAL_1 - Find cheap laptops
**Action:** COMMAND
**Command:** "Search for cheap laptops under $800 with good reviews"
**Coordinator:** internet.research → "cheap laptops under $800 good reviews"
**Result:** SUCCESS - 5 products found
**Claims:**
| Claim | Confidence | Source |
|-------|------------|--------|
| HP Victus @ $649 | 0.90 | walmart.com |
| Lenovo LOQ @ $697 | 0.92 | bestbuy.com |
**Executor Analysis:** Found good options, need to compare

### Executor Iteration 2
**Goal Focus:** GOAL_1, GOAL_2
**Action:** ANALYZE
**Analysis:**
- HP Victus: $649, RTX 4050, 16GB RAM - best price
- Lenovo LOQ: $697, RTX 4050, 16GB RAM - better build
- Best value: HP Victus (same specs, $48 cheaper)
**Goals Progress:** GOAL_1 achieved, GOAL_2 achieved

### Executor Iteration 3
**Action:** COMPLETE
**Goals:** 2/2 achieved
**Summary:** Found 5 laptops, compared specs/prices, identified HP Victus as best value
```

### 5.2 On RETRY from Validation

When Validation returns RETRY, new iterations are marked with attempt number:

```markdown
## 4. Execution Progress

### Attempt 1 (original)
[Previous iterations preserved]

### Attempt 2 (retry)

### Executor Iteration 1 (Attempt 2)
**Action:** COMMAND
**Command:** "Search pet-specific retailers for hamsters"
**Coordinator:** internet.research → focus on Petco, PetSmart
**Result:** SUCCESS - 3 verified products
```

---

## 6. Termination Conditions

| Condition | Triggered By | Action |
|-----------|--------------|--------|
| Goals achieved | Executor says COMPLETE | Exit to Synthesis |
| Max iterations | 10 Executor iterations | Force exit with warning |
| Blocked | Executor says BLOCKED | Create intervention |
| Tool failure | 3 consecutive Coordinator errors | Executor reports BLOCKED |
| Planner routes to synthesis | Planner says route_to: synthesis | Skip Executor, go to Synthesis |

---

## 7. Benefits of 3-Tier Architecture

### 7.1 Separation of Concerns

| Tier | Knows About | Does NOT Know About |
|------|-------------|---------------------|
| Planner | User goals, context | Tools, parameters |
| Executor | Goal progress, next step | Tool signatures, MCP servers |
| Coordinator | Tool catalog, signatures | Strategic goals, user intent |

### 7.2 Token Efficiency

| Component | Current (Old) | New | Change |
|-----------|---------------|-----|--------|
| Planner | ~5,750 (with tools) | ~3,500 (goals only) | -39% |
| Executor | N/A | ~3,500 (tactical) | NEW |
| Coordinator | ~8,000 (full loop) | ~2,500 (per command) | -69% |

The Coordinator is now called per-command rather than managing the entire loop, so its prompt is much smaller.

### 7.3 Maintainability

- **Adding new tools:** Only update Coordinator's catalog
- **Changing strategy:** Only update Planner's prompts
- **Improving tactics:** Only update Executor's prompts

---

## 8. Fast Path: Skip Executor

When the Planner determines no tools are needed:

```
Planner: route_to: "synthesis"
    ↓
Skip Executor and Coordinator entirely
    ↓
Phase 6: Synthesis
```

Examples:
- Greeting: "Hello!"
- Follow-up on existing results: "Why did you pick those?"
- Memory recall with fresh §2: "What's my favorite color?"

---

## 9. Example: Full Flow

**Query:** "Compare our planner docs with 12-factor methodology, then update them"

```
Phase 3: Planner
├── Goal 1: Compare architecture with 12-factor
├── Goal 2: Update based on comparison
├── Approach: Read docs, research, analyze, edit
└── Route: executor

Phase 4-5: Executor-Coordinator Loop

Iteration 1:
├── Executor: COMMAND "Read the planner architecture doc"
└── Coordinator: file.read → planner.md content

Iteration 2:
├── Executor: COMMAND "Search for 12-factor agent methodology"
└── Coordinator: internet.research → 5 sources

Iteration 3:
├── Executor: ANALYZE
└── Findings: Aligns with Factor IV, violates Factor III

Iteration 4:
├── Executor: COMMAND "Update strategic.md to add config externalization"
└── Coordinator: file.edit → changes applied

Iteration 5:
├── Executor: COMPLETE
└── Goals: 2/2 achieved

Phase 6: Synthesis → Response
Phase 7: Validation → APPROVE
Phase 8: Save
```

---

## 10. Related Documents

- `architecture/main-system-patterns/phase3-planner.md` - Planner specification
- `architecture/main-system-patterns/phase4-executor.md` - Executor specification
- `architecture/main-system-patterns/phase5-coordinator.md` - Coordinator specification
- `architecture/main-system-patterns/phase7-validation.md` - Validation and RETRY/REVISE
- `architecture/LLM-ROLES/llm-roles-reference.md` - Model stack overview
- `architecture/DOCUMENT-IO-SYSTEM/MEMORY_ARCHITECTURE.md` - Memory integration

---

## 11. Migration from 2-Tier Architecture

The previous architecture combined planning and tool selection:

```
OLD: Planner (goals + tools) → Coordinator (execute tools)
NEW: Planner (goals) → Executor (commands) → Coordinator (translate + execute)
```

**Key Changes:**
1. Planner outputs STRATEGIC_PLAN instead of PLANNER_DECISION
2. New Executor phase handles tactical decisions
3. Coordinator translates natural language commands
4. Phase numbers shifted: Synthesis 5→6, Validation 6→7, Save 7→8

---

## 12. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-24 | Initial specification for 3-tier architecture |

---

**Last Updated:** 2026-01-24
