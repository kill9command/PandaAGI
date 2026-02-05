# Phase 3: Planner

**Status:** SPECIFICATION
**Version:** 2.10
**Created:** 2026-01-04
**Updated:** 2026-02-04
**Layer:** MIND role (MIND model @ temp=0.6)

**Related Concepts:** See §11 (Concept Alignment)

---

## 1. Overview

The Planner is the **strategic decision-maker** that determines WHAT needs to be done. It answers the core question: **"What are the goals and how should we approach them?"**

Given:
- The user's request (section 0)
- The gathered context (section 2)
- On RETRY: Full context including failure feedback (section 0-7)

Decide:
- **executor** - Need tool execution to accomplish goals (go to Phase 4 Executor)
- **synthesis** - Can answer from current context (go to Phase 6 Synthesis)
- **refresh_context** - Missing memory/context; re-run Phase 2.1/2.2 before planning
 
**Precondition:** Planner only runs when Phase 1.5 and Phase 2.5 have already passed. It does not re-check validation signals.

**Memory rule:** The Planner does **not** search memory directly. If required memory is missing from §2, it routes to `refresh_context` to re-run Phase 2.1/2.2.

The Planner outputs a **STRATEGIC_PLAN** (JSON) that defines:
1. **Goals** - What needs to be accomplished
2. **Approach** - High-level strategy (not specific tools)
3. **Success criteria** - How to know when done
4. **Routing decision** - Where to send execution next

**Canonical Output:** The Planner only outputs STRATEGIC_PLAN JSON. The `context.md` §3 view is a derived render produced by the orchestrator for human readability.

**Requirement Awareness:** The Planner reads the original query from §0, which carries all user requirements (budget, preferences, restrictions). Plans should reflect these requirements in goals and approach. Incompatible or ambiguous requirements trigger `clarify` routing.

**Key Design Principle:** The Planner is STRATEGIC, not tactical. It defines goals, not tool calls. The Executor (Phase 4) determines HOW to achieve goals using natural language commands.

**Plan State Initialization:** The Planner initializes plan state with goals derived from §0. This is updated in later phases as goals progress.

**Note:** Phase 1 provides `user_purpose` (natural language statement) and `data_requirements`. The Planner uses these to inform routing and workflow guidance, and should NOT re-interpret them into rigid action enums.

**Workflow Note:** The Planner does not select tools. The Executor issues workflow-oriented commands, and the Coordinator executes workflows with embedded tools.

---

## 2. Input Specification

### 2.1 Initial Run: context.md (section 0-2)

Section 0 includes `user_purpose`, `data_requirements`, and `mode` from Phase 1 Query Analyzer.

Section 2 includes gathered context (memory, preferences, cached research).

```markdown
## 0. User Query
find me the cheapest <product_type> you can find?

**User Purpose:** User wants the cheapest <product_type>. Price is the top priority.
**Mode:** chat
**Data Requirements:** needs_current_prices=true, needs_product_urls=true, freshness_required=< 1 hour

## 2. Gathered Context

### Session Preferences
```yaml
_meta:
  source_type: preference
  node_ids: ["memory:budget"]
  confidence_avg: 0.82
  provenance: ["memory/preferences.json"]
```
- budget: $X–$Y (high confidence)

### Relevant Prior Turns
```yaml
_meta:
  source_type: turn_summary
  node_ids: ["turn:NNN"]
  confidence_avg: 0.78
  provenance: ["turns/turn_000NNN/context.md"]
```
- Turn NNN: Prior comparison of <product_type>

### Cached Research
```yaml
_meta:
  source_type: research_cache
  node_ids: ["research:topic.id"]
  confidence_avg: 0.88
  provenance: ["research_cache/topic.json"]
```
- Found N options; M under $X with <key_feature>

### Constraints
```yaml
_meta:
  source_type: user_query
  node_ids: []
  provenance: ["§0.raw_query"]
```
- must_have: <key_feature>
- budget: max $X

### Source References
- [1] turns/turn_000NNN/context.md
- [2] research_cache/topic.json
```

### 2.2 RETRY Run: context.md (section 0-6)

On RETRY, Planner receives the **full document**. Critical additions:

| Section | Content | Purpose |
|---------|---------|---------|
| section 4 | Tool execution log | What tools ran, what they found |
| section 5 | Draft response | The response that failed validation |
| section 6 | Validation feedback | **Why it failed** and instructions |

**Section 6 is the key input on retry** - it tells Planner exactly what went wrong:

```markdown
## 6. Validation

### Attempt 1: RETRY
**Reason:** URL_NOT_IN_RESEARCH
**Issues:**
- <source_url> not found in research cache
- Possible hallucination
**Instruction:** Avoid <disallowed_source_type>, prefer <preferred_source_type>
```

### 2.3 Metadata

| Input | Pattern | Purpose |
|-------|---------|---------|
| session_id | "<session_id>" | Session context lookup |
| mode | "chat" or "code" | Tool availability, recipe selection |
| unified_ctx | Object | In-memory context items |
| live_ctx | Object | Session preferences, facts, topic |

---

## 3. Routing Decision Logic

The Planner makes routing decisions by **reasoning about context sufficiency**, not by following rigid rules. The LLM examines:

1. **The query (section 0):** What is the user asking for?
2. **The gathered context (section 2):** What information do we already have?
3. **The gap:** Can we answer fully with section 2, or do we need more?

**Core Question:** "Can I provide a complete, accurate answer with the current context, or do I need to gather more information first?"

### Routing Decision Table

| If Planner Concludes... | Route To | Reason |
|-------------------------|----------|--------|
| "I have enough context to answer" | synthesis | Direct answer from context (Phase 6) |
| "I need more information or action" | executor | Define goals, Executor handles tactics (Phase 4) |
| "Required memory/context missing from §2" | refresh_context | Re-run Phase 2.1/2.2 to gather missing memories |
| "Query is unclear" | clarify | Ask user for clarification (rare) |

### 3.1 Phase 3 CLARIFY Scope (Post-Context)

Phase 3 CLARIFY handles **semantic ambiguity** — queries that remain ambiguous AFTER gathering context from §2:

| Trigger | Pattern Cue | Why CLARIFY |
|---------|-------------|-------------|
| Query clear but user intent ambiguous | Vague request while §2 shows many plausible interest areas | Cannot prioritize without user input |
| Context reveals user-specific info needed | Comparative request with no candidate set in §2 | Need user to specify what to compare |
| Multiple valid interpretations with §2 | Referent like "the best one" while §2 has multiple categories | Cannot infer target category |

**Phase 3 CLARIFY is RARE.** If upstream validation passed and §2 has relevant context, Phase 3 should almost always route to executor or synthesis.

**Decision Tree:**
```
Upstream validation passed → Phase 3 receives query with §2 context
  ├── §2 has relevant context → Route to executor/synthesis
  ├── §2 empty but query is answerable → Route to executor (gather more)
  └── §2 empty AND query requires user-specific info → CLARIFY (rare)
```

**Key Principle:** Phase 1 handles syntactic ambiguity (pre-context). Phase 3 handles semantic ambiguity (post-context). If upstream validation passed, Phase 3 should rarely override with CLARIFY.

### Routing Guidance (Not Hard Rules)

These are hints for the LLM, not hard requirements:

| Pattern | Likely Route | Reasoning |
|---------|--------------|-----------|
| Greeting, chitchat | synthesis | No external data needed |
| "What did you find?" with section 2 populated | synthesis | Answer from prior results |
| "Find me...", "Search for..." | executor | Needs research tools |
| Price/availability queries | executor | Needs fresh data |
| Code operations | executor | Needs file/git tools |

The LLM may override these based on context. For example:
- A discovery request with fresh, sufficient data already in §2 can route to synthesis
- A recall request with no relevant memories in §2 should route to refresh_context

### 3.2 Self‑Building Routing (APEX‑Critical)

If required tools/workflows do not exist, the Planner should route to **self‑extension**:

**Indicators:**
- No workflow matches the task
- Task requires a missing tool family (spreadsheet/doc/pdf/email/calendar)
- Repeated failures with the same missing capability

**Strategic Plan Template:**

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor",
  "plan_type": "self_extend",
  "self_extension": {
    "action": "CREATE_WORKFLOW",
    "workflow_name": "<workflow_name>",
    "required_tools": ["<tool_family.read>", "<tool_family.write>"]
  },
  "goals": [
    {"id": "G1", "description": "Create workflow bundle with required tools"},
    {"id": "G2", "description": "Execute workflow to produce required artifacts"}
  ],
  "success_criteria": "Workflow created, tools validated, artifacts produced"
}
```

See: `architecture/concepts/self_building_system/SELF_BUILDING_SYSTEM.md`.

### Wrong Routing Recovery

If Planner routes incorrectly, Validation catches it:

```
Planner (routes to synthesis) -> Synthesis (weak answer)
    |
    v
Validation: RETRY "Response lacks required evidence"
    |
    v
Planner (sees section 6 failure) -> NOW routes to executor
    |
    v
Executor -> Coordinator -> Synthesis -> Validation (APPROVE)
```

**Why This Works:**
- Planner makes best judgment with available info
- Validation is the safety net
- RETRY loop self-corrects wrong routing
- No need for perfect upfront routing criteria

---

## 4. Purpose-Based Routing

The Planner receives `user_purpose` and `data_requirements` from Phase 1 in §0. It should **NOT** convert these into rigid action enums. Instead, it uses the natural language statement plus data requirements to choose a workflow and routing.

### 4.1 Purpose → Approach Heuristics

| user_purpose signal | Primary Approach | Notes |
|---------------------|-----------------|-------|
| Discovery/comparison intent | `internet.research` workflow | Use `data_requirements` to choose commerce vs informational |
| Recall intent | `memory.search` | Query stored preferences/facts |
| Explicit URL navigation intent | `browser.navigate` | Direct site navigation |
| Code task intent (file/git/test operations) | Code tools (`file.edit`, `git.*`, `test.run`) | Mode must be `code` |
| Greeting/acknowledgement | Route to synthesis | No tools needed |

### 4.2 Workflow Selection Using data_requirements

When the purpose indicates research, the Planner selects a workflow based on `data_requirements`:

| data_requirements | Workflow | Description |
|-------------------|----------|-------------|
| `needs_current_prices: true` + no prior intelligence | `product_research` | Full commerce research (Phase 1 + Phase 2.1/2.2) |
| `needs_current_prices: true` + prior intelligence in §2 | `product_quick_find` | Fast commerce (Phase 2.1/2.2 only, reuses prior intelligence) |
| `needs_current_prices: false` | `intelligence_search` | Informational research (Phase 1 only) |

### 4.3 Routing vs Sufficiency

**Important:** Workflow selection does NOT determine routing. Routing depends on **context sufficiency**.

The routing decision (`executor` vs `synthesis` vs `refresh_context`) is based on **context sufficiency analysis**:
- If §2 already contains fresh data → route to `synthesis`
- If the query is a greeting/acknowledgement → route to `synthesis`
- If memory signals exist but no memory hits in §2 → route to `refresh_context` to re-run Phase 2.1/2.2

**The Planner is the single source of truth for routing (executor vs synthesis vs refresh_context).**

**Synthesis handoff:** When routing to `synthesis`, the Planner still writes §3. Phase 6 reads §3 for intent framing and §2 for facts.

---

## 5. Output Format (Canonical JSON)

### 5.1 STRATEGIC_PLAN JSON Schema (v1.0)

The Planner outputs a strategic plan that defines goals, not tool calls:

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor" | "synthesis" | "clarify" | "refresh_context",
  "goals": [
    {
      "id": "GOAL_1",
      "description": "Identify lowest-cost option meeting <key_constraints>",
      "priority": "high" | "medium" | "low"
    },
    {
      "id": "GOAL_2",
      "description": "Compare candidates across sources",
      "priority": "medium",
      "depends_on": "GOAL_1"
    }
  ],
  "approach": "Gather candidates, compare attributes, filter by constraints",
  "success_criteria": "Found sufficient options with verified attributes",
  "context_summary": "User prioritizes lowest cost; constraints unspecified",
  "reason": "Need fresh data - section 2 lacks recent evidence",
  "refresh_context_request": ["missing <preference>", "no prior turn for <topic>"]
}
```

### 5.2 Derived context.md Section 3 (Rendered View)

This section is **rendered from the STRATEGIC_PLAN JSON** by the orchestrator. The Planner does not author this markdown directly.

```markdown
## 3. Strategic Plan

**Route To:** executor
**Reason:** Query requires fresh, verifiable data

### Goals
| ID | Description | Priority | Dependencies |
|----|-------------|----------|--------------|
| GOAL_1 | Identify lowest-cost option meeting <key_constraints> | high | - |
| GOAL_2 | Compare candidates across sources | medium | GOAL_1 |

### Approach
Gather candidates, compare attributes, filter by constraints

### Success Criteria
Found sufficient options with verified attributes

### Context Summary
User prioritizes lowest cost; constraints unspecified
```

### 5.3 Field Descriptions

| Field | Required | Description |
|-------|----------|-------------|
| `_type` | Yes | Always "STRATEGIC_PLAN" |
| `route_to` | Yes | "executor", "synthesis", "clarify", or "refresh_context" |
| `goals` | Yes | Array of goals to accomplish |
| `approach` | Yes | High-level strategy description |
| `success_criteria` | Yes | How to know when done |
| `context_summary` | No | Brief summary of relevant context |
| `reason` | Yes | Why this routing decision |
| `refresh_context_request` | No | List of missing memories/context to fetch when route_to is `refresh_context` |

### 5.4 Goal Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier (GOAL_1, GOAL_2, etc.) |
| `description` | Yes | What needs to be accomplished |
| `priority` | No | "high", "medium", or "low" (default: medium) |
| `depends_on` | No | Goal ID that must complete first |

**Note:** The Planner does NOT specify tools or tool parameters. The Executor (Phase 4) handles tactical decisions about HOW to accomplish each goal.

---

## 6. RETRY Handling Flow

When Validation (Phase 7) returns RETRY, it loops back to Planner (Phase 3). Planner receives the full context.md with section 7 containing failure information.

**Retry reading order (to reduce confusion):**
1. §7 Validation (why it failed)
2. §4 Execution (what was tried)
3. §0 User Query + §2 Gathered Context (requirements + evidence)

### 6.1 Planner's Job on Retry

1. **Read section 6** to understand WHY it failed
2. **Read section 4** to see WHAT was already tried
3. **Create NEW plan** that avoids previous failures
4. **Emit updated STRATEGIC_PLAN JSON**; orchestrator re-renders §3

### 6.2 context.md on Retry (What Planner Sees)

```markdown
## 0. User Query
Find me a <item_type> under <$budget>

## 1. Query Analysis Validation
**Status:** pass

## 2. Gathered Context
[Original context - still valid]

## 3. Strategic Plan (Previous - Will Be Replaced)
**Route To:** executor
**Goals:**
- GOAL_1: Find <item_type> for sale under <$budget>

## 4. Execution Progress (Previous Attempt)
### Executor Iteration 1
**Command:** "Search for <item_type> under <$budget>"
**Coordinator:** <research_tool_family>
**Result:** Found N candidate listings
**Claims:**
| Claim | Source |
|-------|--------|
| <item> @ <$price> (<source_domain>) | <research_tool_family> |

## 5. (Reserved for Coordinator Results)

## 6. Synthesis (Previous Attempt)
[Previous response that failed validation]

## 7. Validation
### Attempt 1: RETRY
**Reason:** URL_NOT_IN_RESEARCH
**Issues:**
- <source_url> not found in research cache
- Possible hallucination
**Instruction:** Avoid <disallowed_source_type>, prefer <preferred_source_type>
```

### 6.3 Planner Output on Retry

Rendered section 3 view derived from updated STRATEGIC_PLAN JSON:

```markdown
## 3. Strategic Plan (Attempt 2)

**Previous Attempt Failed:** URL hallucination from <source_type>
**Lesson Learned:** <source_type> URLs were not verified

### Goals
| ID | Description | Priority |
|----|-------------|----------|
| GOAL_1 | Find <item_type> from <preferred_source_type> under <$budget> | high |

### Approach
Focus on <preferred_source_type> sources and <alternative_sources>.
Avoid <disallowed_source_type> where verification failed.

### Success Criteria
Found at least <N> verified listings from <preferred_source_type>.

**Route To:** executor
```

### 6.4 STRATEGIC_PLAN JSON on Retry

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor",
  "reason": "Retry after validation failure - focusing on verified source types",
  "is_retry": true,
  "attempt": 2,

  "previous_failure": {
    "reason": "URL_NOT_IN_RESEARCH",
    "failed_sources": ["<source_domain>"],
    "instruction": "Avoid <disallowed_source_type>, prefer <preferred_source_type>"
  },

  "goals": [
    {
      "id": "GOAL_1",
      "description": "Find <item_type> from <preferred_source_type>",
      "priority": "high"
    }
  ],

  "approach": "Focus on <preferred_source_type> and <alternative_sources>. Avoid <disallowed_source_type>.",
  "success_criteria": "Found at least <N> verified listings from <preferred_source_type>",

  "constraints": {
    "avoid_sources": ["<source_domain>"],
    "prefer_sources": ["<source_domain_1>", "<source_domain_2>", "<source_type_group>"]
  }
}
```

### 6.5 Retry Flow Diagram

```
Phase 7 (Validation)
    |
    +-- RETRY: Writes failure to section 7
            |
            v
Phase 3 (Planner) <- Receives full context.md
    |
    +-- Reads section 7: Why it failed
    +-- Reads section 4: What was tried
    +-- Emits STRATEGIC_PLAN JSON; renderer updates §3
            |
            v
Phase 4 (Executor) -> Determines tactical steps
            |
            v
Phase 5 (Coordinator) -> Executes tool calls
            |
            v
Phase 6 (Synthesis) -> New response
            |
            v
Phase 7 (Validation) -> Check again
```

**Key Points:**
- Context is NOT reset (section 1-6 preserved)
- Section 4 is **appended** on retry (new results marked with attempt number)
- Section 7 accumulates across attempts
- Planner sees full failure history (what was tried in §4, why it failed in §7)
- Max 1 RETRY attempt before FAIL (max 2 REVISE attempts)
- If §4 exceeds token limits, Orchestrator triggers NERVES compression

---

## 7. Multi-Goal Query Handling

When a user query contains multiple distinct goals, the Planner:

1. **Detects** multiple goals in the query
2. **Enumerates** goals in the plan output with status tracking
3. **Plans** sequential research execution (one goal at a time)
4. **Tracks** dependencies between goals ("find X and accessories for X")

### 7.1 Template Section 3 with Multi-Goal

```markdown
## 3. Strategic Plan

**Route To:** executor
**Reason:** Multiple categories require separate research

### Goals

| ID | Description | Priority | Dependencies |
|----|-------------|----------|--------------|
| GOAL_1 | Find primary item under <$budget> | high | - |
| GOAL_2 | Recommend complementary item | medium | - |
| GOAL_3 | Suggest accessories dependent on GOAL_1 | medium | GOAL_1 |

### Approach
Research each category separately. GOAL_3 depends on GOAL_1 results (need primary item details for compatibility).

### Success Criteria
At least <N> options per category with verified attributes.
```

### 7.2 Sequential Research Constraint

**Critical:** Internet research MUST be sequential (one goal at a time) due to website anti-bot measures. The Planner-Coordinator loop handles this naturally.

### 7.3 Dependency Handling

When goals have dependencies:

```markdown
### Goals Identified

| ID | Description | Status | Dependencies |
|----|-------------|--------|--------------|
| GOAL_1 | Find primary item | pending | - |
| GOAL_2 | Find compatible accessories | pending | GOAL_1 |

### Execution Order
1. GOAL_1 must complete first (need primary item details for accessories)
2. GOAL_2 uses GOAL_1 results to search for compatible accessories
```

---

## 8. Token Budget

**Total Budget:** ~5,750 tokens

| Component | Tokens | Purpose |
|-----------|--------|---------|
| Prompt fragments | 1,540 | System instructions, role definition |
| Input documents | 2,000 | context.md (§0-§2 initial, §0-§7 on RETRY) |
| Output | 2,000 | TICKET JSON and §3 content |
| Buffer | 210 | Safety margin |
| **Total** | **5,750** | |

---

## 9. Pattern Templates

### 9.1 Template: Discovery/Commerce (Route to Executor)

**Query:** "<discovery request with constraints>"

**Section 2:** Empty or stale research

**Planner Output:**

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor",
  "goals": [
    {"id": "GOAL_1", "description": "Identify candidates meeting <key_constraints>", "priority": "high"},
    {"id": "GOAL_2", "description": "Compare candidates across sources", "priority": "high", "depends_on": "GOAL_1"}
  ],
  "approach": "Gather candidates, compare attributes, filter by constraints",
  "success_criteria": "Found sufficient options with verified attributes",
  "reason": "Section 2 lacks fresh evidence for current conditions"
}
```

**Reasoning:** No fresh evidence in §2; executor must gather current data.

---

### 9.2 Template: Follow-up/Explanation (Route to Synthesis)

**Query:** "<follow-up asking about prior choices>"

**Section 2:** Contains prior comparison from turn <NNN>

**Planner Output:**

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "synthesis",
  "goals": [
    {"id": "GOAL_1", "description": "Explain selection criteria for prior options"}
  ],
  "approach": "Reference prior findings in section 2, explain rationale",
  "success_criteria": "User understands the selection criteria",
  "reason": "All needed context already exists in section 2"
}
```

**Reasoning:** §2 already contains sufficient evidence.

---

### 9.3 Template: Code Task (Route to Executor)

**Query:** "<code change request with file/function reference>"

**Mode:** code

**Planner Output:**

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor",
  "goals": [
    {"id": "GOAL_1", "description": "Understand current implementation", "priority": "high"},
    {"id": "GOAL_2", "description": "Apply requested change", "priority": "high", "depends_on": "GOAL_1"},
    {"id": "GOAL_3", "description": "Verify changes behave correctly", "priority": "medium", "depends_on": "GOAL_2"}
  ],
  "approach": "Inspect code, implement changes, verify behavior",
  "success_criteria": "Change implemented and verified",
  "reason": "Requires reading and modifying code"
}
```

**Reasoning:** Requires code access and modifications.

---

### 9.4 Template: Greeting (Route to Synthesis)

**Query:** "<greeting or acknowledgement>"

**Planner Output:**

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "synthesis",
  "goals": [
    {"id": "GOAL_1", "description": "Respond to greeting"}
  ],
  "approach": "Provide a friendly conversational response",
  "success_criteria": "User feels acknowledged",
  "reason": "No tools required"
}
```

**Reasoning:** No external data or actions required.

---

### 9.5 Template: Ambiguous Query (Route to Clarify)

**Query:** "<incomplete request>"

**Section 2:** No relevant context

**Planner Output:**

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "clarify",
  "goals": [],
  "approach": "Cannot determine approach without missing details",
  "success_criteria": "N/A - need clarification",
  "reason": "Query incomplete",
  "clarification_question": "<targeted clarification question>"
}
```

**Reasoning:** Missing required details to proceed.

---

### 9.6 Template: RETRY with Failure Context

**Query:** "<discovery request with constraints>"

**Section 7 (from previous attempt):**
```markdown
### Attempt 1: RETRY
**Reason:** URL_NOT_IN_RESEARCH
**Issues:**
- <source_url> not found in research cache
**Instruction:** Avoid <disallowed_source_type>, prefer <preferred_source_type>
```

**Planner Output (Attempt 2):**

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor",
  "is_retry": true,
  "attempt": 2,
  "previous_failure": {
    "reason": "URL_NOT_IN_RESEARCH",
    "instruction": "Avoid <disallowed_source_type>"
  },
  "goals": [
    {"id": "GOAL_1", "description": "Find options from <preferred_source_type> under <constraints>", "priority": "high"}
  ],
  "approach": "Search verified sources in <preferred_source_type>, avoid disallowed sources",
  "success_criteria": "Found at least <N> verified listings from preferred sources",
  "constraints": {
    "avoid_sources": ["<source_domain>"],
    "prefer_sources": ["<source_domain_1>", "<source_domain_2>"]
  },
  "reason": "Retry with approach adjusted per validation feedback"
}
```

---

## 10. Key Principles

1. **Strategic, Not Tactical:** Planner defines WHAT (goals), not HOW (tools)
2. **LLM-Driven Reasoning:** Route decision based on context sufficiency analysis
3. **Self-Correcting:** Validation catches wrong routing via RETRY loop
4. **Context Discipline:** Original query always visible for user priority signals
5. **No Hardcoded Rules:** LLM reasons about each query individually
6. **Goal-Oriented:** Every plan has explicit goals and success criteria
7. **Separation of Concerns:** Executor handles tactics, Coordinator handles tools

---

## 11. Concept Alignment

This section maps Phase 3's responsibilities to the cross-cutting concept documents.

| Concept | Document | Phase 3 Relevance |
|---------|----------|--------------------|
| **Execution System** | `concepts/system_loops/EXECUTION_SYSTEM.md` | Phase 3 is the **strategic tier** of the 3-tier architecture. It defines goals and routing (executor vs synthesis vs clarify). The Planner Workpad (§6 of Execution System) and Plan Critic (§7) are optional pre-execution quality gates available to this phase. |
| **Backtracking Policy** | `concepts/self_building_system/BACKTRACKING_POLICY.md` | When Validation returns RETRY with failure feedback in §7, the Planner decides: local retry (adjust approach), partial replan (change specific goals), full replan (new strategy), or clarify (ask user). Plan state tracks goal progress across attempts. |
| **Self-Building System** | `concepts/self_building_system/SELF_BUILDING_SYSTEM.md` | When required tools or workflows don't exist, the Planner routes to self-extension — emitting CREATE_WORKFLOW or CREATE_TOOL goals. The Executor and Coordinator handle the actual creation. |
| **Memory Architecture** | `concepts/memory_system/MEMORY_ARCHITECTURE.md` | The Planner does **not** search memory directly. If required memory is missing from §2, it routes to `refresh_context` to re-run Phase 2.1/2.2. Memory candidates are written to a staging area and only committed after Validation returns APPROVE (Memory Staging, §7 of Memory Architecture). |
| **Recipe System** | `concepts/recipe_system/RECIPE_SYSTEM.md` | Executed as a MIND recipe with ~5,750 token budget. The recipe defines the STRATEGIC_PLAN output schema. Mode-specific recipes (chat vs code) adjust available routing options. |
| **Document IO** | `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | Reads §0–§2 on initial run, or §0–§7 on RETRY (full document with failure feedback). Emits STRATEGIC_PLAN JSON; orchestrator renders §3 (Strategic Plan). On RETRY, §4 is preserved and appended, not replaced. |
| **Confidence System** | `concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` | Uses quality scores from §2 to inform routing. Cached research with quality ≥ 0.70 may allow skipping fresh research. Low quality scores trigger executor routing for new data. |
| **Code Mode** | `concepts/code_mode/code-mode-architecture.md` | Mode-specific planning: code mode enables code tools (`file.edit`, `git.*`, `test.run`), chat mode restricts to research and memory tools. The Planner reads `mode` from §0 to select the appropriate recipe. |
| **Tool System** | `concepts/tools_workflows_system/TOOL_SYSTEM.md` | The Planner doesn't know tool signatures (that's the Coordinator's job) but understands tool families conceptually for routing decisions and workflow selection. |
| **Error Handling** | `concepts/error_and_improvement_system/ERROR_HANDLING.md` | RETRY handling is the Planner's core error recovery mechanism. Max 1 RETRY attempt before FAIL. The Planner reads §7 failure feedback and creates a new plan that avoids previous failures. |
| **Improvement Extraction** | `concepts/error_and_improvement_system/improvement-principle-extraction.md` | On RETRY, the Planner learns from failure context: what was tried (§4), why it failed (§7), and adjusts its approach accordingly. This is turn-local learning that feeds into the retry plan. |
| **LLM Roles** | `LLM-ROLES/llm-roles-reference.md` | Uses the MIND role (temp=0.6) for reasoning about goals, routing, and context sufficiency. Strategic planning requires the MIND temperature for balanced reasoning. |
| **Prompt Management** | `concepts/recipe_system/PROMPT_MANAGEMENT_SYSTEM.md` | The Planner prompt carries the original query (§0) for context discipline — ensuring user priorities (budget, preferences) are visible when making routing decisions. |

---

## 12. Related Documents

- `architecture/main-system-patterns/phase1-query-analyzer.md` — Phase 1 (provides user_purpose, data_requirements, mode in §0)
- `architecture/LLM-ROLES/llm-roles-reference.md` — Model assignments and role definitions
- `architecture/main-system-patterns/phase2.2-context-gathering-synthesis.md` — Phase 2.2 (provides §2 context)
- `architecture/main-system-patterns/phase4-executor.md` — Phase 4 (tactical decisions, natural language commands)
- `architecture/main-system-patterns/phase5-coordinator.md` — Phase 5 (tool selection and execution)
- `architecture/main-system-patterns/phase6-synthesis.md` — Phase 6 (synthesis route)
- `architecture/concepts/system_loops/EXECUTION_SYSTEM.md` — 3-tier loop specification
- `architecture/concepts/memory_system/MEMORY_ARCHITECTURE.md` — Memory system for memory.* tool calls

---

## 13. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 1.1 | 2026-01-05 | Added memory pattern detection (section 5), removed implementation references |
| 1.2 | 2026-01-05 | Removed recipe/prompt file references from Related Documents |
| 1.3 | 2026-01-05 | Added Phase 3 CLARIFY Scope section defining semantic vs syntactic ambiguity; clarified relationship with Phase 1 CLARIFY |
| 1.4 | 2026-01-22 | Consolidated intent handling to Phase 1. Replaced Intent Taxonomy section with Purpose Handling section that references Phase 1 output. Updated Input Specification to show user_purpose/mode in §0. Added Phase 1 to Related Documents. |
| 2.0 | 2026-01-24 | **Major revision:** Changed output from TICKET to STRATEGIC_PLAN. Planner is now strategic (goals) not tactical (tools). Added Executor phase between Planner and Coordinator. Updated routing to executor/synthesis/clarify. Updated all examples to new format. |
| 2.1 | 2026-02-03 | Added §12 Concept Alignment. Fixed routing references (coordinator → executor). Updated memory examples to STRATEGIC_PLAN format. Fixed multi-goal example to be strategic (no tool names). Fixed stale paths in Related Documents. Removed stale Concept Implementation Touchpoints and Benchmark Gaps sections. |
| 2.2 | 2026-02-04 | Removed `action_needed` dependency; Planner now routes using `user_purpose` + `data_requirements`. Updated examples and routing section. |
| 2.3 | 2026-02-04 | Clarified upstream validation gate and corrected routing references to executor. |
| 2.4 | 2026-02-04 | Added refresh_context route for missing memory; Planner no longer searches memory directly. |
| 2.5 | 2026-02-04 | Removed memory pattern detection; updated section numbering and memory architecture alignment. |
| 2.6 | 2026-02-04 | Updated §2 example to match planner-optimized memory graph format. |
| 2.7 | 2026-02-04 | Added refresh_context_request field and retry reading order guidance. |
| 2.8 | 2026-02-04 | Abstracted examples into pattern templates and placeholders. |
| 2.9 | 2026-02-04 | Made STRATEGIC_PLAN JSON canonical; §3 markdown is a derived render. |
| 2.10 | 2026-02-04 | Clarified workflow guidance lives downstream (Executor/Coordinator), not in Planner tool selection. |

---

**Last Updated:** 2026-02-04
