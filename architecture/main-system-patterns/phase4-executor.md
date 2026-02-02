# Phase 4: Executor

**Status:** SPECIFICATION
**Version:** 1.0
**Created:** 2026-01-24
**Updated:** 2026-01-24
**Layer:** MIND role (Qwen3-Coder-30B-AWQ @ temp=0.5)

---

## 1. Overview

The Executor is the **tactical decision-maker** that determines HOW to accomplish the goals set by the Planner. It answers the question: **"What is the next step to achieve this goal?"**

Given:
- The strategic plan from Planner (section 3)
- Previous execution results (section 4)
- The original context (sections 0-2)

Decide:
- **COMMAND** - Issue a natural language command to Coordinator
- **ANALYZE** - Reason about accumulated results without tool execution
- **COMPLETE** - All goals achieved, proceed to Synthesis
- **BLOCKED** - Cannot proceed due to unrecoverable issue

**Key Design Principle:** The Executor uses **natural language commands** to instruct the Coordinator. It does NOT know tool signatures or parameters. The Coordinator owns the tool catalog and translates commands into specific tool calls.

---

## 2. Position in Pipeline

```
Phase 3: Planner (Strategic) → WHAT to do (goals, approach)
    ↓
Phase 4: Executor (Tactical) → HOW to do it (natural language commands)
    ↓
Phase 5: Coordinator (Tool Expert) → Tool selection + execution
    ↓
Phase 6: Synthesis → Response generation
```

The Executor operates in a loop with the Coordinator:

```
┌─────────────────────────────────────────────────────────────────┐
│                    EXECUTOR-COORDINATOR LOOP                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Executor (MIND @ 0.5)                                           │
│     │                                                            │
│     ├── COMMAND: "Read the planner architecture doc"             │
│     │       ↓                                                    │
│     │   Coordinator translates → file.read(...)                  │
│     │       ↓                                                    │
│     │   Results appended to §4                                   │
│     │       ↓                                                    │
│     │   Loop back to Executor                                    │
│     │                                                            │
│     ├── ANALYZE: Process accumulated results (no tool call)      │
│     │       ↓                                                    │
│     │   Analysis appended to §4                                  │
│     │       ↓                                                    │
│     │   Loop back to Executor                                    │
│     │                                                            │
│     ├── COMPLETE: Goals achieved → Phase 6 (Synthesis)           │
│     │                                                            │
│     └── BLOCKED: Unrecoverable → Create intervention             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Input Specification

### 3.1 From Planner (Section 3)

The Executor receives a STRATEGIC_PLAN from the Planner:

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor",
  "goals": [
    {"id": "GOAL_1", "description": "Compare architecture docs with external article"},
    {"id": "GOAL_2", "description": "Update planner based on comparison"}
  ],
  "approach": "Read local docs, research external, analyze, edit",
  "success_criteria": "Identified changes and applied them"
}
```

### 3.2 From Previous Iterations (Section 4)

On subsequent iterations, the Executor sees accumulated results:

```markdown
## 4. Execution Progress

### Executor Iteration 1
**Goal Focus:** GOAL_1 - Compare docs
**Action:** COMMAND
**Command:** "Read the planner architecture doc to understand current design"
**Coordinator:** file.read → architecture/main-system-patterns/phase3-planner.md
**Result:** SUCCESS - 752 lines
**Findings:** Current planner uses EXECUTE/COMPLETE pattern with tool specifications

### Executor Iteration 2
**Goal Focus:** GOAL_1
**Action:** COMMAND
**Command:** "Search for 12-factor agent methodology"
**Coordinator:** internet.research → "12-factor agent best practices"
**Result:** SUCCESS - 5 sources found
**Findings:** Key principles identified: config externalization, stateless processes...
```

### 3.3 Full Context Access

The Executor has access to:
- **§0** - Original user query
- **§1** - Reflection decision
- **§2** - Gathered context (memory, prior research)
- **§3** - Strategic plan with goals
- **§4** - Accumulated execution results

---

## 4. Output Schema

### 4.1 EXECUTOR_DECISION Format

```json
{
  "_type": "EXECUTOR_DECISION",
  "action": "COMMAND" | "ANALYZE" | "COMPLETE" | "BLOCKED",
  "command": "Natural language instruction to Coordinator",
  "analysis": {
    "current_state": "Brief summary of progress",
    "findings": "What was discovered or concluded",
    "next_step_rationale": "Why the next action is needed"
  },
  "goals_progress": [
    {"goal_id": "GOAL_1", "status": "in_progress" | "achieved" | "blocked", "progress": "Description"}
  ],
  "reasoning": "Brief explanation of decision"
}
```

### 4.2 Action-Specific Fields

| Action | Required Fields | Optional Fields |
|--------|-----------------|-----------------|
| COMMAND | command, reasoning | analysis, goals_progress |
| ANALYZE | analysis, reasoning | goals_progress |
| COMPLETE | goals_progress, reasoning | analysis |
| BLOCKED | reasoning | analysis, goals_progress |

---

## 5. Natural Language Commands

The Executor issues commands in natural language. The Coordinator translates these to specific tool calls.

### 5.1 Command Examples

| Natural Language Command | Coordinator Translation |
|--------------------------|------------------------|
| "Read the planner architecture doc" | file.read(path="architecture/.../phase3-planner.md") |
| "Search the web for 12-factor agent patterns" | internet.research(query="12-factor agent patterns") |
| "Find files related to authentication" | file.glob(pattern="**/auth*.py") |
| "Save to memory that the user prefers RTX GPUs" | memory.save(type="preference", content="prefers RTX GPUs") |
| "Edit strategic.md to add the new constraint" | file.edit(path="...", changes=...) |
| "Run the test suite for the auth module" | test.run(target="tests/test_auth.py") |
| "Show git status" | git.status() |
| "Search for laptops under $1000 with RTX GPUs" | internet.research(query="laptops under $1000 RTX GPU") |

### 5.2 Command Principles

1. **Be specific about intent** - "Read the planner doc to understand the output format" (not just "read a file")
2. **Include context when helpful** - "Search for cheap laptops - the user wants the best value"
3. **One action per command** - Don't combine multiple operations
4. **Don't specify tool names** - Say "search the web" not "call internet.research"

### 5.3 What NOT to Include in Commands

- Tool names (Coordinator decides)
- Parameter names or schemas
- File paths (unless obvious from context)
- Query syntax or special operators

---

## 6. Action Decision Logic

### 6.1 COMMAND Decision

Issue COMMAND when:
- Need external data (web search, file read)
- Need to modify state (file edit, memory save, git commit)
- Need verification (run tests, check status)

```json
{
  "_type": "EXECUTOR_DECISION",
  "action": "COMMAND",
  "command": "Read the planner architecture doc to understand the current output format",
  "goals_progress": [
    {"goal_id": "GOAL_1", "status": "in_progress", "progress": "Starting doc analysis"}
  ],
  "reasoning": "Need to understand current planner spec before comparison"
}
```

### 6.2 ANALYZE Decision

Issue ANALYZE when:
- Comparing or synthesizing accumulated results
- Making a decision based on gathered data
- No new external data needed

```json
{
  "_type": "EXECUTOR_DECISION",
  "action": "ANALYZE",
  "analysis": {
    "current_state": "Read 3 docs, found 5 external sources",
    "findings": "Current planner aligns with Factor IV but violates Factor III (config externalization). Changes needed: move tool selection to config.",
    "next_step_rationale": "Have enough data to determine required changes"
  },
  "goals_progress": [
    {"goal_id": "GOAL_1", "status": "achieved", "progress": "Comparison complete"},
    {"goal_id": "GOAL_2", "status": "in_progress", "progress": "Ready to implement changes"}
  ],
  "reasoning": "Accumulated enough data to complete comparison analysis"
}
```

### 6.3 COMPLETE Decision

Issue COMPLETE when:
- All goals in the strategic plan are achieved
- Sufficient information gathered to answer the user's query

```json
{
  "_type": "EXECUTOR_DECISION",
  "action": "COMPLETE",
  "goals_progress": [
    {"goal_id": "GOAL_1", "status": "achieved", "progress": "Comparison documented"},
    {"goal_id": "GOAL_2", "status": "achieved", "progress": "Planner updated with new constraints"}
  ],
  "analysis": {
    "current_state": "All goals achieved",
    "findings": "Updated strategic.md with config externalization constraint per 12-factor analysis"
  },
  "reasoning": "Both goals achieved - comparison complete and changes applied"
}
```

### 6.4 BLOCKED Decision

Issue BLOCKED when:
- Required resource unavailable
- Permission denied with no workaround
- External dependency failure
- Cannot proceed without user intervention

```json
{
  "_type": "EXECUTOR_DECISION",
  "action": "BLOCKED",
  "goals_progress": [
    {"goal_id": "GOAL_1", "status": "blocked", "progress": "Cannot access required file"}
  ],
  "reasoning": "File auth.py requires elevated permissions not available in current mode"
}
```

---

## 7. Goal Tracking

### 7.1 Goal Status Values

| Status | Meaning |
|--------|---------|
| `pending` | Not yet started |
| `in_progress` | Currently being worked on |
| `achieved` | Successfully completed |
| `blocked` | Cannot proceed |

### 7.2 Goal Progress Updates

Each iteration updates goal progress:

```json
"goals_progress": [
  {"goal_id": "GOAL_1", "status": "achieved", "progress": "Found 3 laptops under budget"},
  {"goal_id": "GOAL_2", "status": "in_progress", "progress": "Need to compare specs"}
]
```

### 7.3 Goal Dependencies

When goals have dependencies, the Executor must complete dependencies first:

```markdown
GOAL_1: Find gaming laptop
GOAL_2: Find accessories for chosen laptop (depends on GOAL_1)

Iteration 1: COMMAND - search for laptops (GOAL_1)
Iteration 2: ANALYZE - select best laptop (GOAL_1 achieved)
Iteration 3: COMMAND - search for accessories for [selected laptop] (GOAL_2)
Iteration 4: COMPLETE
```

---

## 8. Section 4 Output Format

The Executor's decisions and results are accumulated in §4:

```markdown
## 4. Execution Progress

### Strategic Plan
**Goals:**
- GOAL_1: Compare architecture docs with 12-factor article
- GOAL_2: Update planner based on comparison

**Approach:** Read local docs, research external, analyze, edit

---

### Executor Iteration 1
**Goal Focus:** GOAL_1 - Compare docs
**Action:** COMMAND
**Command:** "Read the planner architecture doc to understand current design"
**Coordinator:** file.read → architecture/main-system-patterns/phase3-planner.md
**Result:** SUCCESS - 752 lines
**Executor Analysis:** Current planner uses EXECUTE/COMPLETE pattern with tool specifications

### Executor Iteration 2
**Goal Focus:** GOAL_1
**Action:** COMMAND
**Command:** "Search for 12-factor agent methodology"
**Coordinator:** internet.research → "12-factor agent best practices"
**Result:** SUCCESS - 5 sources found
**Executor Analysis:** Key principles: config externalization, stateless processes...

### Executor Iteration 3
**Action:** ANALYZE
**Goal Focus:** GOAL_1
**Comparison Results:**
- Alignment: Factor IV (tools as attached resources) ✓
- Violation: Factor III (config in environment) ✗
- Changes needed: Externalize tool selection to config
**Goals Progress:** GOAL_1 achieved, GOAL_2 in_progress

### Executor Iteration 4
**Action:** COMMAND
**Command:** "Update strategic.md to add configuration externalization"
**Coordinator:** file.edit → apps/prompts/planner/strategic.md
**Result:** SUCCESS

### Executor Iteration 5
**Action:** COMPLETE
**Goals:** 2/2 achieved
**Summary:** Compared architecture, identified 1 violation, applied fix
```

---

## 9. Token Budget

**Total Budget:** ~3,500 tokens per iteration

| Component | Tokens | Purpose |
|-----------|--------|---------|
| Prompt fragments | 800 | System instructions, role definition |
| Input documents | 2,000 | §0-§4 (compressed if needed) |
| Output | 500 | EXECUTOR_DECISION JSON |
| Buffer | 200 | Safety margin |

**Note:** The Executor has a focused prompt without tool catalog (Coordinator owns that), keeping token usage low.

---

## 10. Loop Limits

| Limit | Value | Action on Exceed |
|-------|-------|------------------|
| Max iterations | 10 | Force COMPLETE, warn in §4 |
| Max consecutive COMMAND | 5 | Require ANALYZE before more commands |
| Max tool failures | 3 | BLOCKED with intervention |

---

## 11. Interaction with Coordinator

### 11.1 Command Handoff

```
Executor outputs:
{
  "action": "COMMAND",
  "command": "Search for cheap laptops with good reviews"
}

Coordinator receives command, translates to:
{
  "tool": "internet.research",
  "args": {
    "query": "cheap laptops with good reviews",
    "mode": "commerce"
  }
}

Coordinator executes tool, returns:
{
  "command_received": "Search for cheap laptops with good reviews",
  "tool_selected": "internet.research",
  "status": "success",
  "result": { ... },
  "claims": [ ... ]
}
```

### 11.2 Result Format in §4

The Orchestrator formats Coordinator results for Executor:

```markdown
### Executor Iteration N
**Action:** COMMAND
**Command:** "Search for cheap laptops with good reviews"
**Coordinator:** internet.research → "cheap laptops good reviews"
**Result:** SUCCESS - 12 products found
**Claims:**
| Claim | Confidence | Source |
|-------|------------|--------|
| HP Victus @ $649 | 0.90 | walmart.com |
| Lenovo LOQ @ $697 | 0.92 | bestbuy.com |
```

---

## 12. Examples

### 12.1 Simple Research Query

**Query:** "Find me cheap laptops"

**Strategic Plan:**
```json
{
  "goals": [{"id": "GOAL_1", "description": "Find cheap laptops with good value"}],
  "approach": "Search for laptops, filter by price"
}
```

**Executor Iteration 1:**
```json
{
  "action": "COMMAND",
  "command": "Search for cheap laptops under $800 with good reviews",
  "goals_progress": [{"goal_id": "GOAL_1", "status": "in_progress"}],
  "reasoning": "Need fresh product data to answer"
}
```

**Executor Iteration 2:**
```json
{
  "action": "COMPLETE",
  "goals_progress": [{"goal_id": "GOAL_1", "status": "achieved", "progress": "Found 5 laptops under $800"}],
  "reasoning": "Have sufficient product data to answer user"
}
```

### 12.2 Multi-Step Analysis

**Query:** "Compare our planner with 12-factor methodology, then update it"

**Executor Iteration 1:**
```json
{
  "action": "COMMAND",
  "command": "Read the planner architecture doc to understand current design",
  "reasoning": "Need to understand current state before comparison"
}
```

**Executor Iteration 2:**
```json
{
  "action": "COMMAND",
  "command": "Search for 12-factor agent methodology and best practices",
  "reasoning": "Need external reference for comparison"
}
```

**Executor Iteration 3:**
```json
{
  "action": "ANALYZE",
  "analysis": {
    "findings": "Current planner aligns with Factor IV but violates Factor III. Need to externalize config.",
    "next_step_rationale": "Ready to make changes based on analysis"
  },
  "reasoning": "Have enough data to complete comparison"
}
```

**Executor Iteration 4:**
```json
{
  "action": "COMMAND",
  "command": "Edit strategic.md to add configuration externalization constraint",
  "reasoning": "Implementing the identified change"
}
```

**Executor Iteration 5:**
```json
{
  "action": "COMPLETE",
  "goals_progress": [
    {"goal_id": "GOAL_1", "status": "achieved"},
    {"goal_id": "GOAL_2", "status": "achieved"}
  ],
  "reasoning": "Comparison complete and changes applied"
}
```

---

## 13. Key Principles

1. **Tactical, not strategic** - The Planner sets goals; the Executor determines steps
2. **Natural language commands** - Don't specify tools; the Coordinator translates
3. **Goal-focused** - Every action should advance a goal
4. **ANALYZE before COMPLETE** - Reason about results before declaring done
5. **One step at a time** - React to results, adjust approach as needed
6. **Explicit progress tracking** - Update goals_progress every iteration

---

## 14. Related Documents

- `architecture/main-system-patterns/phase3-planner.md` - Prior phase (provides strategic plan)
- `architecture/main-system-patterns/phase5-coordinator.md` - Next phase (translates commands)
- `architecture/main-system-patterns/PLANNER_EXECUTOR_COORDINATOR_LOOP.md` - Full loop specification
- `architecture/main-system-patterns/phase6-synthesis.md` - After COMPLETE
- `architecture/LLM-ROLES/llm-roles-reference.md` - Model and temperature specs

---

## 15. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-24 | Initial specification |

---

**Last Updated:** 2026-01-24
