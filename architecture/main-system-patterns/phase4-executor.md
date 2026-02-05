# Phase 4: Executor

**Status:** SPECIFICATION
**Version:** 1.3
**Created:** 2026-01-24
**Updated:** 2026-02-04
**Layer:** MIND role (Qwen3-Coder-30B-AWQ @ temp=0.6)

**Related Concepts:** See §14 (Concept Alignment)

---

## 1. Overview

The Executor is the **tactical decision-maker** that determines HOW to accomplish the goals set by the Planner. It answers the question: **"What is the next step to achieve this goal?"**

Given:
- The STRATEGIC_PLAN JSON from Planner (canonical output)
- Previous execution results (section 4)
- The original context (sections 0-2)

Decide:
- **COMMAND** - Issue a natural language command to Coordinator
- **ANALYZE** - Reason about accumulated results without tool execution
- **CREATE_TOOL** - Create a new tool (self‑extension)
- **CREATE_WORKFLOW** - Create a new workflow bundle (self‑extension)
- **COMPLETE** - All goals achieved; return to Phase 3 (Planner) which routes to Synthesis
- **BLOCKED** - Cannot proceed due to unrecoverable issue

**Key Design Principle:** The Executor uses **natural language commands** to instruct the Coordinator. It does NOT know tool signatures or parameters. The Coordinator owns the workflow catalog and executes workflows with embedded tools.

---

## 2. Position in Pipeline

```
Phase 3: Planner (Strategic) → WHAT to do (STRATEGIC_PLAN JSON)
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
│  Executor (MIND @ 0.6)                                           │
│     │                                                            │
│     ├── COMMAND: "Run document review workflow for <doc_path>"   │
│     │       ↓                                                    │
│     │   Coordinator selects workflow → executes embedded tools   │
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

**Invocation rule:** Phase 4 runs only when Phase 3 routes to `executor`. If the route is `synthesis`, `clarify`, or `refresh_context`, Phase 4 is not invoked.

### 3.1 From Planner (STRATEGIC_PLAN JSON)

The Executor receives a STRATEGIC_PLAN from the Planner:

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor",
  "goals": [
    {"id": "GOAL_1", "description": "Compare internal docs with external reference"},
    {"id": "GOAL_2", "description": "Apply required updates based on comparison"}
  ],
  "approach": "Read internal docs, research external reference, analyze, edit",
  "success_criteria": "Identified required changes and applied them"
}
```

### 3.2 From Previous Iterations (Section 4)

On subsequent iterations, the Executor sees accumulated results:

```markdown
## 4. Execution Progress

### Executor Iteration 1
**Goal Focus:** GOAL_1 - Compare docs
**Action:** COMMAND
**Command:** "Read the relevant architecture doc to understand current design"
**Coordinator:** file.read → <doc_path>
**Result:** SUCCESS - <N> lines
**Findings:** Current design pattern identified

### Executor Iteration 2
**Goal Focus:** GOAL_1
**Action:** COMMAND
**Command:** "Search for external reference methodology"
**Coordinator:** internet.research → "<reference_topic>"
**Result:** SUCCESS - <N> sources found
**Findings:** Key principles identified
```

### 3.3 Full Context Access

The Executor has access to:
- **§0** - Original user query
- **§1** - Query Analysis Validation (Phase 1.5)
- **§2** - Gathered context (memory, prior research)
- **§3** - Rendered strategic plan view (derived from STRATEGIC_PLAN JSON)
- **§4** - Accumulated execution results

---

## 4. Output Schema

### 4.1 EXECUTOR_DECISION Format

```json
{
  "_type": "EXECUTOR_DECISION",
  "action": "COMMAND" | "ANALYZE" | "CREATE_TOOL" | "CREATE_WORKFLOW" | "COMPLETE" | "BLOCKED",
  "command": "Natural language instruction to Coordinator",
  "workflow_hint": "Optional workflow name or intent label",
  "tool_spec": { "name": "...", "inputs": [], "outputs": [], "dependencies": [] },
  "tool_code": "python code (optional)",
  "workflow_spec": { "name": "...", "triggers": [], "steps": [] },
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
| COMMAND | command, reasoning | workflow_hint, analysis, goals_progress |
| CREATE_TOOL | tool_spec, reasoning | tool_code, analysis, goals_progress |
| CREATE_WORKFLOW | workflow_spec, reasoning | analysis, goals_progress |
| ANALYZE | analysis, reasoning | goals_progress |
| COMPLETE | goals_progress, reasoning | analysis |
| BLOCKED | reasoning | analysis, goals_progress |

---

## 5. Natural Language Commands

The Executor issues commands in natural language. The Coordinator translates these to specific tool calls.

### 5.1 Command Patterns

| Natural Language Command | Coordinator Translation (Template) |
|--------------------------|-----------------------------------|
| "Run document review workflow for <doc_path>" | workflow.execute(name="<workflow_name>", args={...}) |
| "Run research workflow for <topic>" | workflow.execute(name="<workflow_name>", args={...}) |
| "Run file discovery workflow for <component>" | workflow.execute(name="<workflow_name>", args={...}) |
| "Run memory update workflow for <preference>" | workflow.execute(name="<workflow_name>", args={...}) |
| "Run edit workflow for <doc> to add <constraint>" | workflow.execute(name="<workflow_name>", args={...}) |
| "Run test workflow for <module>" | workflow.execute(name="<workflow_name>", args={...}) |
| "Run repo status workflow" | workflow.execute(name="<workflow_name>", args={...}) |
| "Run commerce workflow for <item> under <budget> with <constraint>" | workflow.execute(name="<workflow_name>", args={...}) |

### 5.2 Command Principles

1. **Be specific about intent** - "Read the planner doc to understand the output format" (not just "read a file")
2. **Include context when helpful** - "Search for <item> under <budget> - user wants best value"
3. **One action per command** - Don't combine multiple operations
4. **Prefer workflow intent** - Frame commands as workflow tasks ("run research workflow for <topic>")
5. **Don't specify tool names** - Say "search the web" not "call internet.research"

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
  "command": "Read the relevant architecture doc to understand the current output format",
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
    "current_state": "Read internal docs, gathered external references",
    "findings": "Alignment and gaps identified. Changes needed to meet external reference constraints.",
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
    {"goal_id": "GOAL_2", "status": "achieved", "progress": "Updates applied"}
  ],
  "analysis": {
    "current_state": "All goals achieved",
    "findings": "Applied required updates based on comparison analysis"
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
  "reasoning": "Required file access not available in current mode"
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
  {"goal_id": "GOAL_1", "status": "achieved", "progress": "Found sufficient options under budget"},
  {"goal_id": "GOAL_2", "status": "in_progress", "progress": "Need to compare attributes"}
]
```

### 7.3 Goal Dependencies

When goals have dependencies, the Executor must complete dependencies first:

```markdown
GOAL_1: Find primary item
GOAL_2: Find accessories for chosen item (depends on GOAL_1)

Iteration 1: COMMAND - search for primary items (GOAL_1)
Iteration 2: ANALYZE - select best item (GOAL_1 achieved)
Iteration 3: COMMAND - search for compatible accessories (GOAL_2)
Iteration 4: COMPLETE
```

---

## 8. Section 4 Output Format

The Executor's decisions and results are accumulated in §4:

```markdown
## 4. Execution Progress

### Strategic Plan
**Goals:**
- GOAL_1: Compare internal docs with external reference
- GOAL_2: Apply required updates based on comparison

**Approach:** Read internal docs, research external reference, analyze, edit

---

### Executor Iteration 1
**Goal Focus:** GOAL_1 - Compare docs
**Action:** COMMAND
**Command:** "Read the relevant architecture doc to understand current design"
**Coordinator:** file.read → <doc_path>
**Result:** SUCCESS - 752 lines
**Executor Analysis:** Current design pattern identified

### Executor Iteration 2
**Goal Focus:** GOAL_1
**Action:** COMMAND
**Command:** "Search for external reference methodology"
**Coordinator:** internet.research → "<reference_topic>"
**Result:** SUCCESS - 5 sources found
**Executor Analysis:** Key principles identified

### Executor Iteration 3
**Action:** ANALYZE
**Goal Focus:** GOAL_1
**Comparison Results:**
- Alignment: <alignment_point> ✓
- Gap: <gap_point> ✗
- Changes needed: <required_change>
**Goals Progress:** GOAL_1 achieved, GOAL_2 in_progress

### Executor Iteration 4
**Action:** COMMAND
**Command:** "Update <doc> to add required constraint"
**Coordinator:** file.edit → <doc_path>
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
  "command": "Run research workflow for <item> under <budget> with <constraint>",
  "workflow_hint": "<workflow_name_or_intent>"
}

Coordinator receives command, selects workflow:
{
  "workflow": "<workflow_name>",
  "args": {
    "query": "<item> under <budget> with <constraint>",
    "mode": "<workflow_mode>"
  }
}

Coordinator executes workflow, returns:
{
  "command_received": "Run research workflow for <item> under <budget> with <constraint>",
  "workflow_selected": "<workflow_name>",
  "status": "success",
  "result": { ... },
  "claims": [ ... ]
}

If the Coordinator cannot proceed due to missing or ambiguous inputs, it returns a structured missing‑info response so the Executor can refine the command:

```
{
  "command_received": "Run research workflow for <item> under <budget> with <constraint>",
  "status": "needs_more_info",
  "missing": ["<required_input_1>", "<required_input_2>"],
  "message": "Need <required_input_1> and <required_input_2> to continue"
}
```
```

### 11.2 Result Format in §4

The Orchestrator formats Coordinator results for Executor:

```markdown
### Executor Iteration N
**Action:** COMMAND
**Command:** "Search for <item> under <budget> with <constraint>"
**Coordinator:** internet.research → "<item> under <budget> with <constraint>"
**Result:** SUCCESS - <N> results found
**Claims:**
| Claim | Confidence | Source |
|-------|------------|--------|
| <item> @ <$price> | 0.90 | <source_domain> |
| <item> @ <$price> | 0.92 | <source_domain> |
```

---

## 12. Pattern Templates

### 12.1 Simple Research

**Query:** "<discovery request with budget>"

**Strategic Plan:**
```json
{
  "goals": [{"id": "GOAL_1", "description": "Find options with good value under budget"}],
  "approach": "Search for options, filter by constraints"
}
```

**Executor Iteration 1:**
```json
{
  "action": "COMMAND",
  "command": "Search for <item> under <budget> with <constraint>",
  "goals_progress": [{"goal_id": "GOAL_1", "status": "in_progress"}],
  "reasoning": "Need fresh product data to answer"
}
```

**Executor Iteration 2:**
```json
{
  "action": "COMPLETE",
  "goals_progress": [{"goal_id": "GOAL_1", "status": "achieved", "progress": "Found sufficient options under budget"}],
  "reasoning": "Have sufficient product data to answer user"
}
```

### 12.2 Multi-Step Analysis

**Query:** "<compare internal doc with external reference, then update>"

**Executor Iteration 1:**
```json
{
  "action": "COMMAND",
  "command": "Read the relevant architecture doc to understand current design",
  "reasoning": "Need to understand current state before comparison"
}
```

**Executor Iteration 2:**
```json
{
  "action": "COMMAND",
  "command": "Search for external reference methodology and best practices",
  "reasoning": "Need external reference for comparison"
}
```

**Executor Iteration 3:**
```json
{
  "action": "ANALYZE",
  "analysis": {
    "findings": "Current design aligns with <alignment_point> but violates <gap_point>. Need to apply <required_change>.",
    "next_step_rationale": "Ready to make changes based on analysis"
  },
  "reasoning": "Have enough data to complete comparison"
}
```

**Executor Iteration 4:**
```json
{
  "action": "COMMAND",
  "command": "Edit <doc> to apply required change",
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
7. **Constraint-respecting** - Commands must honor Phase 2 constraints; if blocked, trigger replanning

---

## 14. Concept Alignment

This section maps Phase 4's responsibilities to the cross-cutting concept documents.

| Concept | Document | Phase 4 Relevance |
|---------|----------|--------------------|
| **Execution System** | `concepts/system_loops/EXECUTION_SYSTEM.md` | Phase 4 is the **tactical tier** of the 3-tier architecture. It operates in a bounded loop with the Coordinator (Phase 5). The Orchestrator manages iteration tracking, §4 append semantics, and NERVES compression when §4 exceeds token limits. |
| **Self-Building System** | `concepts/self_building_system/SELF_BUILDING_SYSTEM.md` | The Executor can issue CREATE_TOOL and CREATE_WORKFLOW actions when required capabilities are missing. It provides tool specs, code, and test requirements; the Coordinator handles actual creation and validation. |
| **Backtracking Policy** | `concepts/self_building_system/BACKTRACKING_POLICY.md` | When tool failures or requirement violations occur, the Executor reports BLOCKED, which feeds back to the Planner for replanning. The Executor interprets failure patterns (consecutive tool failures, permission denials) and decides whether to retry locally or escalate. |
| **Tool System** | `concepts/tools_workflows_system/TOOL_SYSTEM.md` | The Executor does NOT know tool signatures — that's the Coordinator's job. But it initiates tool creation via the Self-Building System when required tool families are missing. |
| **Document IO** | `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | Reads §0–§2, STRATEGIC_PLAN JSON, and the growing §4. §3 is a rendered view derived from the plan. Writes to §4 (Execution Progress). §4 is always **appended**, never replaced — each iteration adds a new block with action, results, and goal progress. |
| **Recipe System** | `concepts/recipe_system/RECIPE_SYSTEM.md` | Executed as a MIND recipe, ~3,500 tokens per iteration. The focused prompt (no tool catalog) keeps token usage low. Each iteration is a separate recipe invocation. |
| **Error Handling** | `concepts/error_and_improvement_system/ERROR_HANDLING.md` | Enforces loop limits: max 10 iterations, max 5 consecutive COMMANDs without ANALYZE, max 3 tool failures → BLOCKED with intervention. All limits are fail-fast — no silent degradation. |
| **Confidence System** | `concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` | Claims from tool results include confidence scores. The Executor uses these in ANALYZE decisions — low-confidence results may trigger additional commands for verification before declaring COMPLETE. |
| **LLM Roles** | `LLM-ROLES/llm-roles-reference.md` | Uses the MIND role (temp=0.6) for tactical reasoning. The MIND temperature provides balanced reasoning about next steps without the determinism of REFLEX or the creativity of VOICE. |
| **Prompt Management** | `concepts/recipe_system/PROMPT_MANAGEMENT_SYSTEM.md` | Natural language commands are a key prompt design principle. The Executor describes intent in natural language; the Coordinator translates. This separation means the Executor prompt never includes tool catalogs or parameter schemas. |

---

## 15. Related Documents

- `architecture/main-system-patterns/phase3-planner.md` — Prior phase (provides strategic plan)
- `architecture/main-system-patterns/phase5-coordinator.md` — Next phase (translates commands)
- `architecture/concepts/system_loops/EXECUTION_SYSTEM.md` — Full loop specification
- `architecture/main-system-patterns/phase6-synthesis.md` — After COMPLETE
- `architecture/LLM-ROLES/llm-roles-reference.md` — Model and temperature specs

---

## 16. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-24 | Initial specification |
| 1.1 | 2026-02-03 | Added §14 Concept Alignment. Removed stale Concept Implementation Touchpoints and Benchmark Gaps sections. |
| 1.2 | 2026-02-04 | Aligned inputs to STRATEGIC_PLAN JSON canonical output. Abstracted examples into pattern templates. Clarified invocation rule and input sections. |
| 1.3 | 2026-02-04 | Switched command interface to workflow-oriented handling. Coordinator executes workflows with embedded tools. |

---

**Last Updated:** 2026-02-04
