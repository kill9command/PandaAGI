# Phase 3: Planner

**Status:** SPECIFICATION
**Version:** 2.0
**Created:** 2026-01-04
**Updated:** 2026-01-24
**Layer:** MIND role (MIND model @ temp=0.5)

---

## 1. Overview

The Planner is the **strategic decision-maker** that determines WHAT needs to be done. It answers the core question: **"What are the goals and how should we approach them?"**

Given:
- The user's request (section 0)
- The reflection decision (section 1)
- The gathered context (section 2)
- On RETRY: Full context including failure feedback (section 0-7)

Decide:
- **executor** - Need tool execution to accomplish goals (go to Phase 4 Executor)
- **synthesis** - Can answer from current context (go to Phase 6 Synthesis)
- **clarify** - Query ambiguous, return to user

The Planner outputs a **STRATEGIC_PLAN** that defines:
1. **Goals** - What needs to be accomplished
2. **Approach** - High-level strategy (not specific tools)
3. **Success criteria** - How to know when done

**Key Design Principle:** The Planner is STRATEGIC, not tactical. It defines goals, not tool calls. The Executor (Phase 4) determines HOW to achieve goals using natural language commands.

**Note:** Intent classification is handled by Phase 0 (Query Analyzer). The Planner receives pre-classified intent in section 0 and should NOT re-classify it.

---

## 2. Input Specification

### 2.1 Initial Run: context.md (section 0-2)

Section 0 includes pre-classified intent and mode from Phase 0 Query Analyzer.

```markdown
## 0. User Query
whats the cheapest laptop with an nvidia gpu you can find?

**Intent:** commerce
**Mode:** chat
**Query Type:** general_question

## 1. Reflection Decision
**Decision:** PROCEED
**Reasoning:** Commerce query, have some cached intel but need fresh prices
**Query Type:** ACTION
**Is Follow-up:** false

## 2. Gathered Context
### Session Preferences
- **budget:** $500

### Prior Research Intelligence
**Topic:** commerce.laptop
**Quality:** 0.88
**Age:** 1.2 hours
<!-- PHASE2_COMPLETE: fresh_intelligence_available -->

### Relevant Prior Turns
| Turn | Relevance | Summary |
|------|-----------|---------|
| 811 | high | RTX 4050 laptop comparison |

### Source References
- [1] turns/turn_000811/context.md
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
- amazon.com/hamster-123 not found in research.json
- Possible hallucination
**Instruction:** Avoid Amazon, try pet-specific retailers
```

### 2.3 Metadata

| Input | Example | Purpose |
|-------|---------|---------|
| session_id | "abc123" | Session context lookup |
| mode | "chat" or "code" | Tool availability, recipe selection |
| unified_ctx | Object | In-memory context items |
| live_ctx | Object | Session preferences, facts, topic |

---

## 3. Routing Decision Logic

The Planner makes routing decisions by **reasoning about context sufficiency**, not by following rigid rules. The LLM examines:

1. **The query (section 0):** What is the user asking for?
2. **The reflection decision (section 1):** Has the query been classified as PROCEED or CLARIFY?
3. **The gathered context (section 2):** What information do we already have?
4. **The gap:** Can we answer fully with section 2, or do we need more?

**Core Question:** "Can I provide a complete, accurate answer with the current context, or do I need to gather more information first?"

### Routing Decision Table

| If Planner Concludes... | Route To | Reason |
|-------------------------|----------|--------|
| "I have enough context to answer" | synthesis | Direct answer from context (Phase 6) |
| "I need more information or action" | executor | Define goals, Executor handles tactics (Phase 4) |
| "Query is unclear" | clarify | Ask user for clarification (rare) |

### 3.1 Phase 3 CLARIFY Scope (Post-Context)

Phase 3 CLARIFY handles **semantic ambiguity** — queries that remain ambiguous AFTER gathering context from §2:

| Trigger | Example | Why CLARIFY |
|---------|---------|-------------|
| Query clear but user intent ambiguous | "Get me something nice" (§2 shows many interests) | Cannot prioritize without user input |
| Context reveals user-specific info needed | "Compare my options" (no options in §2) | Need user to specify what to compare |
| Multiple valid interpretations with §2 | "The best one" (§2 shows laptops AND keyboards) | Cannot guess which category |

**Phase 3 CLARIFY is RARE.** If Phase 1 PROCEED'd and §2 has relevant context, Phase 3 should almost always route to coordinator or synthesis.

**Decision Tree:**
```
Phase 1 PROCEED'd → Phase 3 receives query with §2 context
  ├── §2 has relevant context → Route to coordinator/synthesis
  ├── §2 empty but query is answerable → Route to coordinator (gather more)
  └── §2 empty AND query requires user-specific info → CLARIFY (rare)
```

**Key Principle:** Phase 1 handles syntactic ambiguity (pre-context). Phase 3 handles semantic ambiguity (post-context). If Phase 1 already PROCEED'd, Phase 3 should rarely override with CLARIFY.

### Routing Guidance (Not Hard Rules)

These are hints for the LLM, not hard requirements:

| Pattern | Likely Route | Reasoning |
|---------|--------------|-----------|
| Greeting, chitchat | synthesis | No external data needed |
| "What did you find?" with section 2 populated | synthesis | Answer from prior results |
| "Find me...", "Search for..." | coordinator | Needs research tools |
| Price/availability queries | coordinator | Needs fresh data |
| Code operations | coordinator | Needs file/git tools |

The LLM may override these based on context. For example:
- "Find me a laptop" with fresh laptop data in section 2 could skip to synthesis
- "What's my favorite color?" with no preferences in section 2 needs memory.query

### Wrong Routing Recovery

If Planner routes incorrectly, Validation catches it:

```
Planner (routes to synthesis) -> Synthesis (weak answer)
    |
    v
Validation: RETRY "Response lacks specifics, no prices found"
    |
    v
Planner (sees section 6 failure) -> NOW routes to Coordinator
    |
    v
Coordinator -> Synthesis -> Validation (APPROVE)
```

**Why This Works:**
- Planner makes best judgment with available info
- Validation is the safety net
- RETRY loop self-corrects wrong routing
- No need for perfect upfront routing criteria

---

## 4. Intent Handling

The Planner receives pre-classified intent from Phase 0 in section 0. It should **NOT re-classify intent**. Instead, use the provided intent to inform tool routing:

### 4.1 Intent to Tool Mapping

| Intent | Primary Tool | Notes |
|--------|--------------|-------|
| `commerce` | `internet.research` | Research with commerce parameters |
| `informational` | `internet.research` | Research with forum/article focus |
| `recall` | `memory.search` | Query user's stored preferences/facts |
| `preference` | `memory.save` | Store user's stated preference |
| `navigation` | `browser.navigate` | Direct site navigation |
| `site_search` | `internet.research` | Research with site restriction |
| `greeting` | (none - synthesis) | Fast-path should handle, but if reached, route to synthesis |
| `query` | (context-dependent) | May need research or may answer from §2 |
| `edit` | `file.edit` | Code mode file modification |
| `create` | `file.write` | Code mode file creation |
| `git` | `git.*` | Version control operations |
| `test` | `test.run` | Execute test suite |
| `refactor` | `file.edit` | Code restructuring |

### 4.2 Intent vs Routing

**Important:** Intent informs tool selection, but does NOT determine routing.

The routing decision (`coordinator` vs `synthesis`) is based on **context sufficiency analysis**:
- Intent `commerce` with fresh data in §2 → might route to `synthesis`
- Intent `greeting` (if not fast-pathed) → routes to `synthesis`
- Intent `recall` with no memory hits in §2 → routes to `coordinator` for `memory.search`

**The Planner is the single source of truth for routing (coordinator vs synthesis).**

---

## 5. Memory Pattern Detection

The Planner is responsible for detecting memory-related patterns in user queries and creating appropriate tool calls. This is NOT done in Phase 7 (Save) - memory operations are explicit tool calls.

### 5.1 Memory Patterns

| Pattern | Tool Call | Example |
|---------|-----------|---------|
| "remember that..." | memory.save | "Remember that I prefer RTX GPUs" |
| "my favorite X is..." | memory.save | "My favorite color is blue" |
| "what's my favorite..." | memory.search | "What's my favorite hamster breed?" |
| "what did I tell you about..." | memory.search | "What did I tell you about my budget?" |
| "forget that..." | memory.delete | "Forget that I like AMD" |
| "I no longer..." | memory.delete | "I no longer want budget options" |

### 5.2 Memory Tool Call in Task Plan

When detecting a memory pattern, Planner includes the tool call in the task plan:

```markdown
## 3. Task Plan

**Goal:** Save user preference for RTX GPUs
**Intent:** preference

### Memory Operation
- **Tool:** memory.save
- **Type:** preference
- **Content:** User prefers RTX GPUs over AMD

**Route To:** coordinator
```

### 5.3 Combined Queries

When a query contains both memory operations and other tasks:

```markdown
## 3. Task Plan

**Goal:** Save preference and find matching laptops
**Intent:** commerce

### Memory Operation
- **Tool:** memory.save
- **Type:** preference
- **Content:** User prefers RTX GPUs

### Research Operation
- **Tool:** internet.research
- **Query:** "gaming laptops with RTX GPU"

**Route To:** coordinator
```

The Coordinator executes both operations, with results appended to §4.

---

## 6. Output Formats

### 6.1 STRATEGIC_PLAN JSON Schema (v1.0)

The Planner outputs a strategic plan that defines goals, not tool calls:

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor" | "synthesis" | "clarify",
  "goals": [
    {
      "id": "GOAL_1",
      "description": "Find cheapest laptop with nvidia gpu",
      "priority": "high" | "medium" | "low"
    },
    {
      "id": "GOAL_2",
      "description": "Compare prices across vendors",
      "priority": "medium",
      "depends_on": "GOAL_1"
    }
  ],
  "approach": "Search for products, compare prices, filter by specs",
  "success_criteria": "Found at least 3 options with prices and specs",
  "context_summary": "User wants cheapest nvidia laptop, no budget specified",
  "reason": "Need fresh product prices - section 2 has no recent data"
}
```

### 6.2 context.md Section 3 Format

```markdown
## 3. Strategic Plan

**Route To:** executor
**Reason:** Commerce query requires fresh product prices

### Goals
| ID | Description | Priority | Dependencies |
|----|-------------|----------|--------------|
| GOAL_1 | Find cheapest laptop with nvidia gpu | high | - |
| GOAL_2 | Compare prices across vendors | medium | GOAL_1 |

### Approach
Search for products, compare prices, filter by specs

### Success Criteria
Found at least 3 options with prices and specs

### Context Summary
User wants cheapest nvidia laptop, no budget specified
```

### 6.3 Field Descriptions

| Field | Required | Description |
|-------|----------|-------------|
| `_type` | Yes | Always "STRATEGIC_PLAN" |
| `route_to` | Yes | "executor", "synthesis", or "clarify" |
| `goals` | Yes | Array of goals to accomplish |
| `approach` | Yes | High-level strategy description |
| `success_criteria` | Yes | How to know when done |
| `context_summary` | No | Brief summary of relevant context |
| `reason` | Yes | Why this routing decision |

### 6.4 Goal Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier (GOAL_1, GOAL_2, etc.) |
| `description` | Yes | What needs to be accomplished |
| `priority` | No | "high", "medium", or "low" (default: medium) |
| `depends_on` | No | Goal ID that must complete first |

**Note:** The Planner does NOT specify tools or tool parameters. The Executor (Phase 4) handles tactical decisions about HOW to accomplish each goal.

---

## 7. RETRY Handling Flow

When Validation (Phase 7) returns RETRY, it loops back to Planner (Phase 3). Planner receives the full context.md with section 7 containing failure information.

### 7.1 Planner's Job on Retry

1. **Read section 6** to understand WHY it failed
2. **Read section 4** to see WHAT was already tried
3. **Create NEW plan** that avoids previous failures
4. **Write updated section 3** with new approach

### 7.2 context.md on Retry (What Planner Sees)

```markdown
## 0. User Query
Find me a Syrian hamster under $30

## 1. Reflection Decision
**Decision:** PROCEED

## 2. Gathered Context
[Original context - still valid]

## 3. Strategic Plan (Previous - Will Be Replaced)
**Route To:** executor
**Goals:**
- GOAL_1: Find Syrian hamsters for sale under $30

## 4. Execution Progress (Previous Attempt)
### Executor Iteration 1
**Command:** "Search for Syrian hamsters for sale"
**Coordinator:** internet.research
**Result:** Found 2 products
**Claims:**
| Claim | Source |
|-------|--------|
| Syrian Hamster @ $25 (amazon.com) | internet.research |

## 5. (Reserved for Coordinator Results)

## 6. Synthesis (Previous Attempt)
[Previous response that failed validation]

## 7. Validation
### Attempt 1: RETRY
**Reason:** URL_NOT_IN_RESEARCH
**Issues:**
- amazon.com/hamster-123 not found in research.json
- Possible hallucination
**Instruction:** Avoid Amazon, try pet-specific retailers
```

### 7.3 Planner Output on Retry

Updated section 3 with new strategic plan:

```markdown
## 3. Strategic Plan (Attempt 2)

**Previous Attempt Failed:** URL hallucination from Amazon
**Lesson Learned:** Amazon URLs were not verified

### Goals
| ID | Description | Priority |
|----|-------------|----------|
| GOAL_1 | Find Syrian hamsters from pet-specific retailers | high |

### Approach
Focus on pet specialty stores (Petco, PetSmart) and local breeders.
Avoid general marketplaces where URL verification has failed.

### Success Criteria
Found at least 2 verified product listings from pet stores.

**Route To:** executor
```

### 7.4 STRATEGIC_PLAN JSON on Retry

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor",
  "reason": "Retry after validation failure - focusing on pet-specific retailers",
  "is_retry": true,
  "attempt": 2,

  "previous_failure": {
    "reason": "URL_NOT_IN_RESEARCH",
    "failed_sources": ["amazon.com"],
    "instruction": "Avoid Amazon, try pet-specific retailers"
  },

  "goals": [
    {
      "id": "GOAL_1",
      "description": "Find Syrian hamsters from pet-specific retailers",
      "priority": "high"
    }
  ],

  "approach": "Focus on pet specialty stores and local breeders. Avoid general marketplaces.",
  "success_criteria": "Found at least 2 verified product listings from pet stores",

  "constraints": {
    "avoid_sources": ["amazon.com"],
    "prefer_sources": ["petco.com", "petsmart.com", "local breeders"]
  }
}
```

### 7.5 Retry Flow Diagram

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
    +-- Writes section 3: New strategic plan avoiding failures
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

## 8. Multi-Goal Query Handling

When a user query contains multiple distinct goals, the Planner:

1. **Detects** multiple goals in the query
2. **Enumerates** goals in section 3 with status tracking
3. **Plans** sequential research execution (one goal at a time)
4. **Tracks** dependencies between goals ("find X and accessories for X")

### 8.1 Example Section 3 with Multi-Goal

```markdown
## 3. Task Plan

### Goals Identified

| ID | Description | Status | Dependencies |
|----|-------------|--------|--------------|
| GOAL_1 | Find gaming laptop under $1500 | in_progress | - |
| GOAL_2 | Recommend mechanical keyboard | pending | - |
| GOAL_3 | Suggest laptop accessories | pending | GOAL_1 |

### Execution Plan

1. [GOAL_1] Execute internet.research for laptops
2. [GOAL_2] Execute internet.research for keyboards
3. [GOAL_3] Execute internet.research for accessories (after GOAL_1 completes)

**Route To:** coordinator
```

### 8.2 Sequential Research Constraint

**Critical:** Internet research MUST be sequential (one goal at a time) due to website anti-bot measures. The Planner-Coordinator loop handles this naturally.

### 8.3 Dependency Handling

When goals have dependencies:

```markdown
### Goals Identified

| ID | Description | Status | Dependencies |
|----|-------------|--------|--------------|
| GOAL_1 | Find gaming laptop | pending | - |
| GOAL_2 | Find compatible accessories | pending | GOAL_1 |

### Execution Order
1. GOAL_1 must complete first (need laptop model for accessories)
2. GOAL_2 uses GOAL_1 results to search for compatible accessories
```

---

## 9. Token Budget

**Total Budget:** ~5,750 tokens

| Component | Tokens | Purpose |
|-----------|--------|---------|
| Prompt fragments | 1,540 | System instructions, role definition |
| Input documents | 2,000 | context.md (§0-§2 initial, §0-§6 on RETRY) |
| Output | 2,000 | TICKET JSON and §3 content |
| Buffer | 210 | Safety margin |
| **Total** | **5,750** | |

---

## 10. Examples

### 10.1 Example: Commerce Query (Route to Executor)

**Query:** "find me the cheapest gaming laptop with an RTX 4050"

**Section 2:** Empty or stale research

**Planner Output:**

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor",
  "goals": [
    {"id": "GOAL_1", "description": "Find gaming laptops with RTX 4050", "priority": "high"},
    {"id": "GOAL_2", "description": "Identify cheapest option", "priority": "high", "depends_on": "GOAL_1"}
  ],
  "approach": "Search for RTX 4050 laptops, compare prices across retailers",
  "success_criteria": "Found at least 3 laptops with verified prices",
  "reason": "No fresh data in section 2, need current prices"
}
```

**Reasoning:** No fresh data in section 2, need research to find current prices. Executor will determine how to search.

---

### 10.2 Example: Follow-up Query (Route to Synthesis)

**Query:** "why did you pick those options?"

**Section 2:** Contains previous laptop comparison from turn 743

**Planner Output:**

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "synthesis",
  "goals": [
    {"id": "GOAL_1", "description": "Explain selection criteria for previously shown laptops"}
  ],
  "approach": "Reference prior findings in section 2, explain rationale",
  "success_criteria": "User understands why those options were selected",
  "reason": "All needed context is in section 2 from previous turn"
}
```

**Reasoning:** All needed context is in section 2 from previous turn. No new research required.

---

### 10.3 Example: Code Task (Route to Executor)

**Query:** "add error handling to the login function in auth.py"

**Mode:** code

**Planner Output:**

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor",
  "goals": [
    {"id": "GOAL_1", "description": "Understand current login function implementation", "priority": "high"},
    {"id": "GOAL_2", "description": "Add appropriate error handling", "priority": "high", "depends_on": "GOAL_1"},
    {"id": "GOAL_3", "description": "Verify changes work correctly", "priority": "medium", "depends_on": "GOAL_2"}
  ],
  "approach": "Read current code, add try/except blocks, run tests",
  "success_criteria": "Error handling added and tests pass",
  "reason": "Need to read and modify code files"
}
```

**Reasoning:** Need to read file, edit it, and run tests. Executor will determine specific operations.

---

### 10.4 Example: Greeting (Route to Synthesis)

**Query:** "hello, how are you?"

**Planner Output:**

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "synthesis",
  "goals": [
    {"id": "GOAL_1", "description": "Respond to greeting"}
  ],
  "approach": "Generate friendly conversational response",
  "success_criteria": "User feels acknowledged",
  "reason": "Simple greeting, no tools needed"
}
```

**Reasoning:** No tools needed, simple conversational response.

---

### 10.5 Example: Ambiguous Query (Route to Clarify)

**Query:** "get me some"

**Section 2:** No relevant context

**Planner Output:**

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "clarify",
  "goals": [],
  "approach": "Cannot determine approach without knowing what user wants",
  "success_criteria": "N/A - need clarification",
  "reason": "Query incomplete - no object specified",
  "clarification_question": "What would you like me to find for you?"
}
```

**Reasoning:** No object specified, cannot proceed without more information.

---

### 10.6 Example: RETRY with Failure Context

**Query:** "find me a Syrian hamster under $30"

**Section 7 (from previous attempt):**
```markdown
### Attempt 1: RETRY
**Reason:** URL_NOT_IN_RESEARCH
**Issues:**
- amazon.com/hamster-123 not found in research.json
**Instruction:** Avoid Amazon, try pet-specific retailers
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
    "instruction": "Avoid Amazon"
  },
  "goals": [
    {"id": "GOAL_1", "description": "Find Syrian hamsters from pet-specific retailers under $30", "priority": "high"}
  ],
  "approach": "Search pet specialty stores (Petco, PetSmart) and breeder directories. Avoid general marketplaces.",
  "success_criteria": "Found at least 2 verified listings from pet stores",
  "constraints": {
    "avoid_sources": ["amazon.com"],
    "prefer_sources": ["petco.com", "petsmart.com"]
  },
  "reason": "Retry with different approach per validation feedback"
}
```

---

## 11. Key Principles

1. **Strategic, Not Tactical:** Planner defines WHAT (goals), not HOW (tools)
2. **LLM-Driven Reasoning:** Route decision based on context sufficiency analysis
3. **Self-Correcting:** Validation catches wrong routing via RETRY loop
4. **Context Discipline:** Original query always visible for user priority signals
5. **No Hardcoded Rules:** LLM reasons about each query individually
6. **Goal-Oriented:** Every plan has explicit goals and success criteria
7. **Separation of Concerns:** Executor handles tactics, Coordinator handles tools

---

## 12. Related Documents

- `architecture/main-system-patterns/phase0-query-analyzer.md` - Phase 0 (provides intent, mode, query_type in §0)
- `architecture/LLM-ROLES/llm-roles-reference.md` - Model assignments and role definitions
- `architecture/main-system-patterns/phase2-context-gathering.md` - Phase 2 (provides §2 context)
- `architecture/main-system-patterns/phase4-executor.md` - Phase 4 (tactical decisions, natural language commands)
- `architecture/main-system-patterns/phase5-coordinator.md` - Phase 5 (tool selection and execution)
- `architecture/main-system-patterns/phase6-synthesis.md` - Phase 6 (synthesis route)
- `architecture/main-system-patterns/PLANNER_EXECUTOR_COORDINATOR_LOOP.md` - 3-tier loop specification
- `architecture/DOCUMENT-IO-SYSTEM/MEMORY_ARCHITECTURE.md` - Memory system for memory.* tool calls

---

## 13. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 1.1 | 2026-01-05 | Added memory pattern detection (section 5), removed implementation references |
| 1.2 | 2026-01-05 | Removed recipe/prompt file references from Related Documents |
| 1.3 | 2026-01-05 | Added Phase 3 CLARIFY Scope section defining semantic vs syntactic ambiguity; clarified relationship with Phase 1 CLARIFY |
| 1.4 | 2026-01-22 | Consolidated intent classification to Phase 0. Replaced Intent Taxonomy section with Intent Handling section that references Phase 0 output. Updated Input Specification to show intent/mode in §0. Added Phase 0 to Related Documents. |
| 2.0 | 2026-01-24 | **Major revision:** Changed output from TICKET to STRATEGIC_PLAN. Planner is now strategic (goals) not tactical (tools). Added Executor phase between Planner and Coordinator. Updated routing to executor/synthesis/clarify. Updated all examples to new format. |

---

**Last Updated:** 2026-01-24
