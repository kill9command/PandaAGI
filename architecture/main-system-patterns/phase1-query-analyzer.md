# Phase 1: Query Analyzer

**Status:** SPECIFICATION
**Version:** 4.0
**Created:** 2026-01-04
**Updated:** 2026-02-05
**Layer:** REFLEX role (MIND model @ temp=0.4)
**Token Budget:** ~1,500 total (includes validation helper)

**Related Concepts:** See Section 13 for full concept alignment.

---

## 1. Overview

Phase 1 is the first stage of the pipeline (Phases 1-8). It runs **before** Context Retrieval/Synthesis (Phases 2.1/2.2) and answers a single question:

> **"What is the user asking about?"**

The Query Analyzer is intentionally **minimal and focused**. It does exactly three things:
1. **Detect junk queries** - Is this garbled/nonsensical input?
2. **Resolve references** - Replace pronouns AND implicit continuations with explicit references
3. **Describe user intent** - Brief natural language statement of what user wants

**Conversational Continuity Principle:** Assume every query continues the previous conversation unless it clearly starts a new topic. This applies to both explicit pronouns ("that thread") and implicit continuations ("tell me the trending threads" after discussing a specific site). A query is only a new topic when it names a completely different subject or explicitly redirects ("forget that, look up Y").

**What Query Analyzer does NOT do:**
- URL lookups (Context Gatherer does this)
- Data requirements analysis (Planner does this)
- Visit record enrichment (Context Gatherer does this)
- Complex turn loading (summaries are pre-formatted before QA is called)

**Key Design Decision:** This phase replaces hardcoded pattern matching with LLM understanding. Instead of regex rules like `if "the thread" in query`, the LLM interprets context naturally.

**Why Natural Language:** Phase 1 outputs `user_purpose` as a 2-4 sentence natural language statement that flows to all downstream phases. This replaces rigid intent categories (commerce, informational, etc.) which were a single point of failure.

---

## 2. Position in Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           8-PHASE PIPELINE                                   │
│                   (All text roles use MIND model via temperature)            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Phase 1: Query Analyzer ───────────────► REFLEX role (temp=0.4)      │   │
│  │    "What is the user asking about?"                                  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│               │                                                             │
│               ▼                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Phase 1.5: Query Analyzer Validator ─► REFLEX role (temp=0.4)         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│     │                                                                        │
│     │  QueryAnalysis object                                                  │
│     ▼                                                                        │
│  Phase 2.1: Context Retrieval ────────────────► MIND role (temp=0.6)        │
│     │                                                                        │
│     ▼                                                                        │
│  Phase 2.2: Context Synthesis ────────────────► MIND role (temp=0.6)        │
│     │                                                                        │
│     ▼                                                                        │
│  Phase 2.5: Context Validator ────────────────► REFLEX role (temp=0.4)      │
│     │                                                                        │
│     ▼                                                                        │
│  Phase 3: Planner ─────────────────────────────► MIND role (temp=0.6)       │
│     │                                                                        │
│     ▼                                                                        │
│  Phase 4: Executor ───────────────────────────► MIND role (temp=0.6)       │
│     │                                                                           │
│     ▼                                                                        │
│  Phase 5: Coordinator ─────────────────────────► REFLEX role (temp=0.4)     │
│     │                                                                           │
│     ▼                                                                        │
│  Phase 6: Synthesis ───────────────────────────► VOICE role (temp=0.7)      │
│     │                                                                        │
│     ▼                                                                        │
│  Phase 7: Validation ──────────────────────────► MIND role (temp=0.6)       │
│     │                                                                        │
│     ▼                                                                        │
│  Phase 8: Save ────────────────────────────────► (No LLM - procedural)      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Input Specification

| Input | Source | Description | Token Estimate |
|-------|--------|-------------|----------------|
| `raw_query` | User | The exact user input, unmodified | 20-100 |
| `turn_summaries` | `context.md` (Turn Summary Appendix) | Summaries from turns N-1, N-2, N-3 | 150-450 |

### Input Format

**Turn Summary Appendix:** Phase 8 appends recent turn summaries to the end of `context.md` as a final section. Phase 1 reads that appendix and passes the summaries into the Query Analyzer prompt. This is a lightweight continuity summary and is distinct from Phase 2 retrieval summaries (which are task-specific and generated at retrieval time).

```json
{
  "raw_query": "what did they say about the scraper?",
  "turn_summaries": [
    {
      "turn_id": 814,
      "summary": "User asked about best glass scrapers, researched forums, recommended Triumph brand",
      "content_refs": ["'Best glass scraper' thread on GarageJournal"]
    },
    {
      "turn_id": 813,
      "summary": "User asked about car wax options under $30",
      "content_refs": []
    },
    {
      "turn_id": 812,
      "summary": "User set preference: interested in auto detailing",
      "content_refs": []
    }
  ]
}
```

### Why Only 3 Turns?

- **Recency bias:** References typically point to the last 1-2 turns
- **Token efficiency:** More turns = more tokens = slower inference
- **Diminishing returns:** References to turn N-4 or older are rare

---

## 4. User Purpose Statement

Phase 1 does **not** emit a separate action classification. Instead, it produces a clear `resolved_query` and a 2–4 sentence `user_purpose` statement describing what the user is asking about, why, and any explicit priorities or constraints. This keeps intent grounded in natural language and prevents brittle routing decisions from hardcoded enums.

**Design note:** Downstream phases must route based on `user_purpose` + `data_requirements` rather than a fixed action label.

**Handoff emphasis:** Phase 2.1 prioritizes the **narrative signal** (`resolved_query`, `user_purpose`, and a concise `reasoning` note). Structured fields are helpful hints but not the primary signal. Favor clarity and accuracy in the narrative over strict structural completeness.

---

## 5. Mode Selection (UI-Driven)

Phase 1 does **not** infer mode. Mode is supplied by the UI toggle and passed through as `mode`:

| Mode | Source | Tool Availability |
|------|--------|-------------------|
| `chat` | UI toggle | internet.research, memory.*, browser tools |
| `code` | UI toggle | file.*, git.*, test.* |

### Permission Handling

If `mode=chat` and the user requests code tasks, Phase 1.5 must return `clarify` with a permission question (e.g., “You’re in chat mode. Switch to code mode to proceed?”). In `code` mode, no permission is required for normal coding tasks.

---

## 6. Greeting Handling

Queries that are greetings or lightweight acknowledgements still go through the full pipeline, but the Planner quickly routes them to synthesis:

```
Phase 1 (user_purpose: greeting/acknowledgement) ──► Phase 2 ──► Phase 3 (Planner: COMPLETE) ──► Phase 6 (Synthesis)
```

**The only "fast path" is the Planner's COMPLETE decision**, which skips tool execution (Phase 4/5) and goes directly to synthesis. Phase 1 does NOT skip phases - it only outputs the resolved query and user_purpose.

This ensures:
- Consistent pipeline execution for all queries
- Planner maintains routing authority
- No special-case bypasses that could cause issues

---

## 7. Output Schema

**Minimal output - Query Analyzer only resolves references and describes intent.**

```json
{
  "resolved_query": "string (query with pronouns replaced by explicit references)",
  "user_purpose": "Natural language statement of what the user wants (2-4 sentences)",
  "reference_resolution": {
    "status": "not_needed | resolved | failed",
    "original_references": ["string"],
    "resolved_to": "string | null"
  },
  "was_resolved": true | false,
  "is_junk": false,
  "reasoning": "string (brief explanation)"
}
```

### Fields Removed (now handled elsewhere)

| Field | Now Handled By | Reason |
|-------|---------------|--------|
| `data_requirements` | Planner (Phase 3) | Planner decides what data is needed based on user_purpose |
| `content_reference` | Context Gatherer (Phase 2) | URL lookups are context retrieval |
| `mode` | UI toggle (passed through) | Not an LLM decision |

### Phase 1.5 Validator

After the initial QueryAnalysis, Phase 1 runs the **validation helper** (Phase 1.5, REFLEX 0.4) to check:

- Is the query actionable given `resolved_query`?
- Did reference resolution succeed or fail?
- Is the query fundamentally ambiguous (rare - default to pass)?

---

## 8. LLM Prompt Design

### Canonical Prompt

The canonical Phase 1 prompt is maintained at: `apps/prompts/pipeline/phase0_query_analyzer.md` (filename retained for compatibility).

That prompt defines the exact instructions, output schema, guidelines for `user_purpose`, `data_requirements`, mode handling, and examples. The prompt file is the source of truth for the LLM's behavior, all prompts should follow an internal orientation, and instructions for an internal plan do check process.

### System Prompt (Summary)

```
You are a query analyzer. Your job is to understand what the user is asking about.

Given a user query and recent conversation summaries, you must:
1. Resolve any pronouns or references to explicit entities
2. Capture what the user wants in natural language (user_purpose)
3. Identify data requirements (prices, live data, freshness)
4. Pass through UI-provided mode (`chat` or `code`)
5. Correct spelling/terminology using authoritative sources from context

Output JSON only. No explanation outside the JSON.
```

### User Prompt Template

```
Query: {raw_query}

Recent conversation:
Turn {N-1}: {summary_1}
  Content discussed: {content_refs_1}

Turn {N-2}: {summary_2}
  Content discussed: {content_refs_2}

Turn {N-3}: {summary_3}
  Content discussed: {content_refs_3}

Analyze this query and output the QueryAnalysis JSON.
```

---

## 9. Examples

### Example 1: Pronoun Resolution (Recall)

**Input:**
```json
{
  "raw_query": "what did they recommend in the thread?",
  "turn_summaries": [
    {
      "turn_id": 814,
      "summary": "Researched best glass scrapers, found forum discussion recommending Triumph brand",
      "content_refs": ["'Best glass scraper for tint removal' thread on GarageJournal"]
    }
  ]
}
```

**Output:**
```json
{
  "resolved_query": "what did they recommend in the 'Best glass scraper for tint removal' thread on GarageJournal?",
  "user_purpose": "User wants to recall specific recommendations from the GarageJournal forum thread about glass scrapers that was discussed in the previous turn. They want the specific product recommendations from that thread.",
  "data_requirements": {
    "needs_current_prices": false,
    "needs_product_urls": false,
    "needs_live_data": false,
    "freshness_required": null
  },
  "reference_resolution": {
    "status": "resolved",
    "original_references": ["the thread", "they"],
    "resolved_to": "'Best glass scraper for tint removal' thread on GarageJournal"
  },
  "mode": "chat",
  "was_resolved": true,
  "content_reference": {
    "title": "Best glass scraper for tint removal",
    "content_type": "thread",
    "site": "GarageJournal",
    "source_turn": 814
  },
  "reasoning": "Resolved 'the thread' to the GarageJournal thread discussed in turn 814. User wants to recall prior findings."
}
```

### Example 2: Commerce Query (No Resolution)

**Input:**
```json
{
  "raw_query": "what's the cheapest RTX 4060 laptop?",
  "turn_summaries": [
    {
      "turn_id": 810,
      "summary": "Discussed user's budget of $800 for a gaming laptop",
      "content_refs": []
    }
  ]
}
```

**Output:**
```json
{
  "resolved_query": "what's the cheapest RTX 4060 laptop?",
  "user_purpose": "User wants to find the cheapest laptop with an RTX 4060 GPU. Price is the top priority. Prior context suggests a budget around $800 for gaming laptops.",
  "data_requirements": {
    "needs_current_prices": true,
    "needs_product_urls": true,
    "needs_live_data": true,
    "freshness_required": "< 1 hour"
  },
  "reference_resolution": {
    "status": "not_needed",
    "original_references": [],
    "resolved_to": null
  },
  "mode": "chat",
  "was_resolved": false,
  "content_reference": {
    "title": null,
    "content_type": null,
    "site": null,
    "source_turn": null
  },
  "reasoning": "Query is already explicit, no references to resolve. Needs live price data for commerce search."
}
```

### Example 3: Followup Query

**Input:**
```json
{
  "raw_query": "what about the 16GB version?",
  "turn_summaries": [
    {
      "turn_id": 815,
      "summary": "Compared Lenovo LOQ laptops, user interested in 8GB RAM model at $697",
      "content_refs": ["Lenovo LOQ 15 product page on Best Buy"]
    }
  ]
}
```

**Output:**
```json
{
  "resolved_query": "what about the 16GB RAM version of the Lenovo LOQ 15?",
  "user_purpose": "User wants to know about the 16GB RAM version of the Lenovo LOQ 15 laptop. This is a follow-up to the previous comparison where they were looking at the 8GB model at $697. They likely want to see the price difference and specs.",
  "data_requirements": {
    "needs_current_prices": true,
    "needs_product_urls": true,
    "needs_live_data": true,
    "freshness_required": "< 1 hour"
  },
  "reference_resolution": {
    "status": "resolved",
    "original_references": ["the 16GB version"],
    "resolved_to": "16GB RAM version of the Lenovo LOQ 15"
  },
  "mode": "chat",
  "was_resolved": true,
  "content_reference": {
    "title": "Lenovo LOQ 15",
    "content_type": "product",
    "site": "Best Buy",
    "source_turn": 815
  },
  "reasoning": "Resolved '16GB version' to Lenovo LOQ 15 variant based on turn 815 context. Modification of prior commerce query."
}
```

### Example 4: Implicit Continuation (No Pronouns)

**Input:**
```json
{
  "raw_query": "tell me what the trending threads are",
  "turn_summaries": [
    {
      "turn_id": 219,
      "summary": "User asked to visit forum.example.com and find popular topics. Response listed Monster Tanks, Nano Reefs, etc.",
      "content_refs": ["forum.example.com popular topics page"]
    }
  ]
}
```

**Output:**
```json
{
  "resolved_query": "tell me what the trending threads are on forum.example.com",
  "user_purpose": "User wants to see trending threads on forum.example.com. This continues the previous conversation about forum.example.com.",
  "reference_resolution": {
    "status": "resolved",
    "original_references": ["the trending threads"],
    "resolved_to": "trending threads on forum.example.com"
  },
  "was_resolved": true,
  "is_junk": false,
  "reasoning": "No explicit pronouns, but 'the trending threads' continues the forum.example.com context from turn 219. Enriched query with site name."
}
```

### Example 5: Greeting

**Input:**
```json
{
  "raw_query": "hello, how are you?",
  "turn_summaries": []
}
```

**Output:**
```json
{
  "resolved_query": "hello, how are you?",
  "user_purpose": "User is greeting the system. No specific task or information need.",
  "data_requirements": {
    "needs_current_prices": false,
    "needs_product_urls": false,
    "needs_live_data": false,
    "freshness_required": null
  },
  "reference_resolution": {
    "status": "not_needed",
    "original_references": [],
    "resolved_to": null
  },
  "mode": "chat",
  "was_resolved": false,
  "content_reference": {
    "title": null,
    "content_type": null,
    "site": null,
    "source_turn": null
  },
  "reasoning": "Simple greeting, no context needed. Can answer from context without tools."
}
```

### Example 6: Code Mode Query

**Input:**
```json
{
  "raw_query": "fix the bug in auth.py where login fails",
  "turn_summaries": []
}
```

**Output:**
```json
{
  "resolved_query": "fix the bug in auth.py where login fails",
  "user_purpose": "User wants to fix a bug in the auth.py file where the login function is failing. This is a code editing task targeting a specific file.",
  "data_requirements": {
    "needs_current_prices": false,
    "needs_product_urls": false,
    "needs_live_data": false,
    "freshness_required": null
  },
  "reference_resolution": {
    "status": "not_needed",
    "original_references": [],
    "resolved_to": null
  },
  "mode": "code",
  "was_resolved": false,
  "content_reference": {
    "title": null,
    "content_type": null,
    "site": null,
    "source_turn": null
  },
  "reasoning": "Code edit request targeting auth.py file. Mode provided by UI toggle."
}
```

---

## 10. Token Budget Breakdown

| Component | Tokens | Notes |
|-----------|--------|-------|
| System prompt | 200 | Fixed, compressed |
| User prompt template | 100 | Variable structure |
| Turn summaries (3x) | 450 | ~150 per turn |
| Raw query | 50 | Typical length |
| **Total Input** | **800** | |
| Output JSON | 350 | Structured response (larger due to user_purpose) |
| Validation helper | 300 | Short REFLEX pass (status + issues) |
| Buffer | 550 | Safety margin |
| **Total Budget** | **2,000** | |

### Why This Budget Works

- MIND model handles large context but REFLEX role keeps prompts compact
- 2,000 tokens keeps inference fast (~50-150ms)
- Sufficient for 3 turn summaries + query + structured output
- `user_purpose` adds ~50-100 tokens but `query_type` and `intent` removal saves similar amount
- Validation helper adds a small second-pass check without expensive context

---

## 11. Integration Notes

### Downstream Consumers

| Phase | How It Uses QueryAnalysis |
|-------|---------------------------|
| Phase 1 (Validation) | Uses `resolved_query` + `reference_resolution.status` to decide pass/retry/clarify |
| Phase 1 (Validation) | Uses `user_purpose` + `data_requirements` to detect unclear queries that may need clarification |
| Phase 2 (Context Gatherer) | Uses `resolved_query` for searching turns and memory |
| Phase 2 (Context Gatherer) | Uses `content_reference.source_turn` to prioritize loading that turn's context |
| Phase 3 (Planner) | Uses `user_purpose` for goal formulation — the natural language statement flows directly into strategic planning |
| Phase 3 (Planner) | Uses `user_purpose` + `data_requirements` for workflow selection (commerce vs informational) |
| Phase 3 (Planner) | Uses `mode` to select appropriate tool set (chat vs code tools) |
| Phase 5 (Coordinator) | Uses `mode` to determine available MCP tools |

### Why Validation Lives Inside Phase 1

The QueryAnalysis output provides sufficient information for an in-phase validator to make pass/retry/clarify decisions:

- **`resolved_query`**: If the query is clear and actionable, validation passes
- **`reference_resolution.status`**: Unambiguous three-state signal:
  - `not_needed`: Query was already explicit → favor pass
  - `resolved`: References successfully interpreted → favor pass
  - `failed`: References could not be resolved → retry or clarify depending on ambiguity
- **`user_purpose`**: If the statement is vague or contradictory, validation may lean toward clarify
- **`content_reference`**: If a specific content reference was identified, validation knows the user's intent is tied to prior context

This ordering avoids expensive Context Gathering for queries that will ultimately require clarification anyway, without a standalone reflection gate.

### Error Handling (Fail-Fast)

All errors halt processing and create intervention requests. No silent fallbacks.

| Error | Action |
|-------|--------|
| Parse failure | HALT - Log full context, create intervention |
| Empty output | HALT - Log prompt/response, create intervention |
| Model timeout | HALT - Log timeout details, create intervention |
| Schema validation failure | HALT - Log invalid output, create intervention |

**Rationale:** Every failure is a bug. Silent fallbacks hide problems and create compounding issues. Fix the root cause, don't work around it.

### Metrics to Track

| Metric | Purpose |
|--------|---------|
| `phase1_latency_ms` | Ensure staying under 100ms target |
| `resolution_rate` | % of queries where `was_resolved: true` |
| `resolution_accuracy` | Spot-check: did resolution match human judgment? |

---

## 12. Design Rationale

### Why a Dedicated Phase?

| Approach | Problem |
|----------|---------|
| **Before (hardcoded patterns)** | Brittle regex like `if "the thread" in query` fails on variations |
| **After (LLM understanding)** | Model interprets "the thread", "that article", "it" naturally from context |

Phase 1 replaces fragile pattern matching with LLM comprehension. The model uses conversation history to resolve references accurately.

### Why Natural Language user_purpose Instead of Intent Categories?

| Approach | Problem |
|----------|---------|
| **Before (13 intent categories)** | Single point of failure: wrong category → wrong routing everywhere downstream. Categories can't express nuance ("user wants cheap but also quality"). |
| **After (natural language user_purpose)** | Each downstream LLM reads the purpose statement and interprets it in context. Phase 7 Validation catches misinterpretations via RETRY. Self-correcting. |

### Why REFLEX Role (temp=0.4)?

| Reason | Benefit |
|--------|---------|
| Speed | Low temperature = faster, more deterministic inference |
| Consistency | Same temp used for Phase 1 validation helper |
| Capability | Sufficient for reference resolution and purpose extraction (not deep reasoning) |
| Simplicity | Uses shared MIND model, no separate model needed |

### Why Include a Validation Helper?

| Reason | Benefit |
|--------|---------|
| Early correction | Catch inconsistent `user_purpose` / `mode` before downstream phases |
| Reduced false clarifications | Default to pass unless ambiguity is fundamental |
| Debugging | Validator issues are explicit and logged as part of Phase 1 output |

---

## 13. Concept Alignment

This section maps Phase 1's responsibilities to the architecture's cross-cutting concept docs.

| Concept | Document | How Phase 1 Implements It |
|---------|----------|--------------------------|
| **Recipe System** | `concepts/recipe_system/RECIPE_SYSTEM.md` | Phase 1 runs via a recipe: REFLEX role, ~1,500 token budget, `QUERY_ANALYSIS` output schema. The recipe governs inputs, budget, and validation — no ad-hoc LLM calls. |
| **Prompt Management** | `concepts/recipe_system/PROMPT_MANAGEMENT_SYSTEM.md` | Phase 1 embodies the "LLM-First Decisions" principle. Reference resolution, purpose extraction, and data requirement inference are LLM decisions, not code. The canonical prompt (`apps/prompts/pipeline/phase0_query_analyzer.md`) is the source of truth for behavior. |
| **Document IO** | `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | Phase 1 writes to §0 of context.md (append-only). It receives `raw_query` plus the Turn Summary Appendix (last N summaries) from the end of context.md via the recipe. All downstream phases read §0 for the original query — this is the "context discipline" principle. |
| **Code Mode** | `concepts/code_mode/code-mode-architecture.md` | Phase 1 passes through `mode` from the UI toggle (chat vs code). Phase 1.5 enforces permission when a code task is requested in chat mode. This choice propagates through the pipeline — selecting mode-specific recipes at Phases 3, 4, 5, 6 and controlling tool availability in Phase 5. |
| **Execution System** | `concepts/system_loops/EXECUTION_SYSTEM.md` | Phase 1's `user_purpose` + `data_requirements` output feeds into the workflow trigger system. The Planner uses these to select workflows (e.g., commerce vs informational). |
| **Memory Architecture** | `concepts/memory_system/MEMORY_ARCHITECTURE.md` | Phase 1 reads recent turn summaries from the Turn Summary Appendix at the end of `context.md` (sourced by Phase 8 from the turn index). Phase 1 respects the access rule: it reads from memory indexes but does not write. |
| **Error Handling** | `concepts/error_and_improvement_system/ERROR_HANDLING.md` | Phase 1 follows fail-fast: parse failures, empty outputs, timeouts, and schema validation failures all HALT and create interventions. No silent fallbacks, no default routing labels. |
| **Confidence System** | `concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` | The `reference_resolution.status` (not_needed / resolved / failed) is a confidence signal for Phase 1 validation. Failed resolution increases retry/clarify likelihood. |
| **Observability** | `concepts/DOCUMENT-IO-SYSTEM/OBSERVABILITY_SYSTEM.md` | Phase 1 produces timing data (latency), decision data (mode, resolution status), and quality metrics (resolution_rate, resolution_accuracy) — all three components of the observability system. |
| **LLM Roles** | `LLM-ROLES/llm-roles-reference.md` | Phase 1 uses REFLEX role (temp=0.4) — a low temperature for classification and validation decisions. This follows the "right-sized roles" principle: classification doesn't need MIND's reasoning depth. |

---

## 14. Related Documents

- `architecture/main-system-patterns/phase1-reflection.md` - Deprecated reflection gate (superseded by Phase 1 validation)
- `architecture/main-system-patterns/phase1.5-query-analyzer-validator.md` - Validation helper spec
- `architecture/main-system-patterns/phase2.1-context-gathering-retrieval.md` - Uses resolved_query for search
- `architecture/LLM-ROLES/llm-roles-reference.md` - Model assignments
- `apps/prompts/pipeline/phase0_query_analyzer.md` - Canonical Phase 1 prompt (source of truth)

---

## 15. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 1.1 | 2026-01-05 | Removed implementation file references, added Related Documents and Changelog |
| 1.2 | 2026-01-05 | Replaced `was_resolved` boolean with `reference_resolution` object containing 3-state status enum (`not_needed`, `resolved`, `failed`) for unambiguous Phase 1 handling |
| 1.3 | 2026-01-22 | Added Intent Classification (Section 4), Mode Detection (Section 5). Added `intent`, `mode` fields to output schema. Phase 1 now owns intent classification (previously duplicated in Phase 3). Greeting intent handled via Planner COMPLETE decision (no phase skipping). |
| 1.4 | 2026-01-24 | Added spelling/terminology correction as responsibility #4 in LLM Prompt Design. |
| 2.0 | 2026-02-03 | **Replaced `intent` (13 categories) with `user_purpose` (natural language).** Added `data_requirements`. Removed code-mode intent split. Updated examples and integration notes. |
| 3.0 | 2026-02-04 | Renamed Phase 0 to Phase 1, removed Reflection gate, and added Phase 1 validation helper output. Updated pipeline diagram and validation implications. |
| 3.1 | 2026-02-04 | Removed `action_needed` output; routing now derives from `user_purpose` + `data_requirements`. Updated examples and integration notes. |
| 3.2 | 2026-02-04 | Sourced `turn_summaries` from the Turn Summary Appendix at the end of `context.md`. |
| 3.3 | 2026-02-04 | Clarified UI-toggle mode source of truth and removed action classification references. |
| 3.4 | 2026-02-04 | Removed Phase 1.2 normalization step; validation now runs directly on Phase 1 output. |
| 3.5 | 2026-02-04 | Updated pipeline diagram to reflect Phase 2.1/2.2/2.5 sub-phases. |
| 3.6 | 2026-02-04 | Emphasized narrative handoff quality for Phase 2.1 retrieval. |
| 4.0 | 2026-02-05 | **Major simplification.** Removed `data_requirements`, `content_reference`, `mode` from output. Added `is_junk`. URL enrichment moved to Context Gatherer. Query Analyzer now only: (1) detects junk, (2) resolves pronouns, (3) describes intent. |
| 4.1 | 2026-02-05 | **Added Conversational Continuity principle.** Query Analyzer now assumes queries continue the previous conversation unless clearly a new topic. Resolves implicit continuations (not just explicit pronouns). Added Example 4 (implicit continuation). |

---

**Last Updated:** 2026-02-05
