# Phase 0: Query Analyzer

**Status:** SPECIFICATION
**Version:** 1.3
**Created:** 2026-01-04
**Updated:** 2026-01-22
**Layer:** REFLEX role (MIND model @ temp=0.3)
**Token Budget:** ~1,500 total

---

## 1. Overview

Phase 0 is the first stage of the 8-phase pipeline. It runs **before** Reflection (Phase 1) and answers a single question:

> **"What is the user asking about?"**

The Query Analyzer uses the REFLEX role (MIND model with temp=0.3) to:
- Resolve pronoun and reference expressions to explicit entities
- Classify the query type for downstream routing
- Identify references to prior conversation content
- Add minimal latency (~50-100ms) to the pipeline

**Key Design Decision:** This phase replaces hardcoded pattern matching with LLM understanding. Instead of regex rules like `if "the thread" in query`, the LLM interprets context naturally.

---

## 2. Position in Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           8-PHASE PIPELINE                                   │
│                   (All text roles use MIND model via temperature)            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Phase 0: Query Analyzer ──────────────────► REFLEX role (temp=0.3)   │   │
│  │    "What is the user asking about?"                                  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│     │                                                                        │
│     │  QueryAnalysis object                                                  │
│     ▼                                                                        │
│  Phase 1: Reflection ──────────────────────────► REFLEX role (temp=0.3)     │
│     │                                                                        │
│     │  PROCEED ──► Phase 2: Context Gatherer ──► MIND role (temp=0.5)       │
│     │  CLARIFY ──► Return to user                                           │
│     ▼                                                                        │
│  Phase 3: Planner ─────────────────────────────► MIND role (temp=0.5)       │
│     │                                                                        │
│     ▼                                                                        │
│  Phase 4: Coordinator ─────────────────────────► MIND role (temp=0.5)       │
│     │                                                                           │
│     ▼                                                                        │
│  Phase 5: Synthesis ───────────────────────────► VOICE role (temp=0.7)      │
│     │                                                                        │
│     ▼                                                                        │
│  Phase 6: Validation ──────────────────────────► MIND role (temp=0.5)       │
│     │                                                                        │
│     ▼                                                                        │
│  Phase 7: Save ────────────────────────────────► (No LLM - procedural)      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Input Specification

| Input | Source | Description | Token Estimate |
|-------|--------|-------------|----------------|
| `raw_query` | User | The exact user input, unmodified | 20-100 |
| `turn_summaries` | Turn Index | Summaries from turns N-1, N-2, N-3 | 150-450 |

### Input Format

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

## 4. Intent Classification

Phase 0 classifies query intent into one of the following categories. This classification is passed to downstream phases (especially Phase 3 Planner) so they do NOT need to re-classify.

### 4.1 Chat Mode Intents

| Intent | Description | Examples |
|--------|-------------|----------|
| `greeting` | Small talk, pleasantries | "hello", "thanks", "how are you" |
| `preference` | User stating preference | "I like X", "my budget is Y", "I prefer..." |
| `recall` | Memory lookup | "what did you find", "what's my favorite..." |
| `query` | General informational question | "what is X", "how does...", "explain..." |
| `commerce` | Shopping/purchase intent | "find cheapest X", "buy...", "for sale" |
| `navigation` | Go to specific URL/site | "go to amazon.com", "visit X.com" |
| `site_search` | Search within specific site | "find X on reddit", "search Y on amazon" |
| `informational` | Deep research request | "learn about X", "research Y" |

### 4.2 Code Mode Intents

| Intent | Description | Examples |
|--------|-------------|----------|
| `edit` | Modify existing file | "fix the bug in...", "update the function..." |
| `create` | Create new file | "add new component", "create a test file" |
| `git` | Version control operations | "commit changes", "push to main" |
| `test` | Run tests | "run the tests", "check if tests pass" |
| `refactor` | Restructure code | "refactor this to use...", "clean up..." |

**Note:** Code mode intents are only used when `mode: "code"`. In chat mode, code-related queries use chat intents.

---

## 5. Mode Detection

Phase 0 detects the operating mode based on query content and context:

| Mode | Detection Signals | Tool Availability |
|------|-------------------|-------------------|
| `chat` | General questions, shopping, research | internet.research, memory.*, browser tools |
| `code` | File paths, function names, git operations | file.*, git.*, test.* |

### Mode Detection Rules

1. **Explicit code signals:** File paths (`auth.py`), git commands (`commit`), code terms (`function`, `refactor`) → `code`
2. **Explicit chat signals:** Shopping terms (`buy`, `cheapest`), URLs, research terms → `chat`
3. **Ambiguous:** Default to session's current mode or `chat` if no session context

---

## 6. Greeting Intent Handling

Queries classified as `greeting` intent (hello, thanks, bye) still go through the full pipeline, but the Planner quickly routes them to synthesis:

```
Phase 0 (intent: greeting) ──► Phase 1-2 ──► Phase 3 (Planner: COMPLETE) ──► Phase 5 (Synthesis)
```

**The only "fast path" is the Planner's COMPLETE decision**, which skips tool execution (Phase 4) and goes directly to synthesis. Phase 0 does NOT skip phases - it only classifies intent.

This ensures:
- Consistent pipeline execution for all queries
- Planner maintains routing authority
- No special-case bypasses that could cause issues

---

## 7. Output Schema

```json
{
  "resolved_query": "string",
  "reference_resolution": {
    "status": "not_needed | resolved | failed",
    "original_references": ["string"],
    "resolved_to": "string | null"
  },
  "query_type": "specific_content | general_question | followup | new_topic",
  "intent": "greeting | preference | recall | query | commerce | navigation | site_search | informational | edit | create | git | test | refactor",
  "mode": "chat | code",
  "content_reference": {
    "title": "string | null",
    "content_type": "thread | article | product | video | null",
    "site": "string | null",
    "source_turn": "number | null"
  },
  "reasoning": "string"
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `resolved_query` | string | The query with all references made explicit. If no resolution needed, equals `raw_query`. |
| `reference_resolution` | object | Status of reference resolution attempt. |
| `reference_resolution.status` | enum | `not_needed` = query was already explicit (no references); `resolved` = references found and successfully resolved; `failed` = references found but could not be resolved (ambiguous). |
| `reference_resolution.original_references` | array | List of detected references (e.g., ["the thread", "it"]). Empty if status is `not_needed`. |
| `reference_resolution.resolved_to` | string | The resolved interpretation (if status is `resolved`). Null otherwise. |
| `query_type` | enum | Classification of what kind of query this is. |
| `intent` | enum | The classified intent (see Section 4). Used by downstream phases for routing. |
| `mode` | enum | Operating mode: `chat` or `code`. Determines available tools. |
| `content_reference` | object | Details about referenced prior content, if any. All fields nullable. |
| `content_reference.title` | string | Exact title of referenced content (e.g., thread title, article name). |
| `content_reference.content_type` | enum | Type of content being referenced. |
| `content_reference.site` | string | Domain or site name (e.g., "GarageJournal", "Reddit"). |
| `content_reference.source_turn` | number | Turn number where this content was discussed. |
| `reasoning` | string | Brief explanation of how the resolution was performed. |

### Reference Resolution Status Values

| Status | Meaning | Phase 1 Implication |
|--------|---------|---------------------|
| `not_needed` | Query was already explicit, no references to resolve | Strongly favor PROCEED |
| `resolved` | References found and successfully interpreted | Strongly favor PROCEED |
| `failed` | References found but could not be resolved | Lean toward CLARIFY |

### Query Type Definitions

| Type | Description | Example |
|------|-------------|---------|
| `specific_content` | Asking about a specific piece of prior content | "what did they say about..." |
| `general_question` | New question not tied to prior content | "what's the best laptop?" |
| `followup` | Continues prior topic but not specific content | "what about price?" |
| `new_topic` | Explicit topic change | "now let's talk about cars" |

---

## 8. LLM Prompt Design

### System Prompt

```
You are a query analyzer. Your job is to understand what the user is asking about.

Given a user query and recent conversation summaries, you must:
1. Resolve any pronouns or references to explicit entities
2. Classify the query type
3. Identify if the user is referencing prior content
4. Correct spelling/terminology using authoritative sources from context

RULES:
- If the user says "the thread", "that article", "it", etc., find the specific content they mean
- Use the turn summaries to identify what content was discussed
- If you cannot determine what is being referenced, keep the original wording
- Be precise: use exact titles when available
- Use authoritative spelling from context (e.g., "jessika" → "Jessikka" if prior turn has correct spelling)

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

### Example 1: Pronoun Resolution

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
  "reference_resolution": {
    "status": "resolved",
    "original_references": ["the thread", "they"],
    "resolved_to": "'Best glass scraper for tint removal' thread on GarageJournal"
  },
  "query_type": "specific_content",
  "intent": "recall",
  "mode": "chat",
  "content_reference": {
    "title": "Best glass scraper for tint removal",
    "content_type": "thread",
    "site": "GarageJournal",
    "source_turn": 814
  },
  "reasoning": "Resolved 'the thread' to the GarageJournal thread discussed in turn 814"
}
```

### Example 2: No Resolution Needed

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
  "reference_resolution": {
    "status": "not_needed",
    "original_references": [],
    "resolved_to": null
  },
  "query_type": "general_question",
  "intent": "commerce",
  "mode": "chat",
  "content_reference": {
    "title": null,
    "content_type": null,
    "site": null,
    "source_turn": null
  },
  "reasoning": "Query is already explicit, no references to resolve. Commerce intent detected from 'cheapest' and product category."
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
  "reference_resolution": {
    "status": "resolved",
    "original_references": ["the 16GB version"],
    "resolved_to": "16GB RAM version of the Lenovo LOQ 15"
  },
  "query_type": "followup",
  "intent": "commerce",
  "mode": "chat",
  "content_reference": {
    "title": "Lenovo LOQ 15",
    "content_type": "product",
    "site": "Best Buy",
    "source_turn": 815
  },
  "reasoning": "Resolved '16GB version' to Lenovo LOQ 15 variant based on turn 815 context. Followup on commerce query."
}
```

### Example 4: Greeting

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
  "reference_resolution": {
    "status": "not_needed",
    "original_references": [],
    "resolved_to": null
  },
  "query_type": "general_question",
  "intent": "greeting",
  "mode": "chat",
  "content_reference": {
    "title": null,
    "content_type": null,
    "site": null,
    "source_turn": null
  },
  "reasoning": "Simple greeting, no context needed. Fast path enabled."
}
```

### Example 5: Code Mode Query

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
  "reference_resolution": {
    "status": "not_needed",
    "original_references": [],
    "resolved_to": null
  },
  "query_type": "general_question",
  "intent": "edit",
  "mode": "code",
  "content_reference": {
    "title": null,
    "content_type": null,
    "site": null,
    "source_turn": null
  },
  "reasoning": "Code edit request targeting auth.py file. Mode set to code based on file path reference."
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
| Output JSON | 200 | Structured response |
| Buffer | 500 | Safety margin |
| **Total Budget** | **1,500** | |

### Why This Budget Works

- MIND model handles large context but REFLEX role keeps prompts compact
- 1,500 tokens keeps inference fast (~50-100ms)
- Sufficient for 3 turn summaries + query + structured output

---

## 11. Integration Notes

### Downstream Consumers

| Phase | How It Uses QueryAnalysis |
|-------|---------------------------|
| Phase 1 (Reflection) | Uses `resolved_query` + `query_type` to decide PROCEED or CLARIFY |
| Phase 1 (Reflection) | Uses `reference_resolution.status` to detect ambiguous references that may need clarification |
| Phase 2 (Context Gatherer) | Uses `resolved_query` for searching turns and memory |
| Phase 2 (Context Gatherer) | Uses `content_reference.source_turn` to prioritize loading that turn's context |
| Phase 3 (Planner) | Uses `intent` for tool routing (commerce→research, recall→memory, etc.) |
| Phase 3 (Planner) | Uses `mode` to select appropriate tool set (chat vs code tools) |
| Phase 4 (Coordinator) | Uses `mode` to determine available MCP tools |

### Why Reflection Comes Before Context Gathering

The QueryAnalysis output provides sufficient information for Reflection to make PROCEED/CLARIFY decisions:

- **`resolved_query`**: If the query is clear and actionable, Reflection can PROCEED
- **`reference_resolution.status`**: Unambiguous three-state signal:
  - `not_needed`: Query was already explicit → favor PROCEED
  - `resolved`: References successfully interpreted → favor PROCEED
  - `failed`: References could not be resolved → lean toward CLARIFY
- **`query_type`**: Helps Reflection assess whether the query is specific enough to act on
- **`content_reference`**: If a specific content reference was identified, Reflection knows the user's intent is tied to prior context

This ordering avoids expensive Context Gathering for queries that will ultimately require clarification anyway.

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
| `phase0_latency_ms` | Ensure staying under 100ms target |
| `resolution_rate` | % of queries where `was_resolved: true` |
| `resolution_accuracy` | Spot-check: did resolution match human judgment? |

---

## 12. Design Rationale

### Why a Dedicated Phase?

| Approach | Problem |
|----------|---------|
| **Before (hardcoded patterns)** | Brittle regex like `if "the thread" in query` fails on variations |
| **After (LLM understanding)** | Model interprets "the thread", "that article", "it" naturally from context |

Phase 0 replaces fragile pattern matching with LLM comprehension. The model uses conversation history to resolve references accurately.

### Why REFLEX Role (temp=0.3)?

| Reason | Benefit |
|--------|---------|
| Speed | Low temperature = faster, more deterministic inference |
| Consistency | Same temp used for Phase 1 (Reflection) |
| Capability | Sufficient for reference resolution (not deep reasoning) |
| Simplicity | Uses shared MIND model, no separate model needed |

### Why Not Combine with Phase 1?

| Reason | Benefit |
|--------|---------|
| Separation of concerns | Resolution is distinct from PROCEED/CLARIFY decision |
| Model appropriateness | Resolution needs speed, not reasoning depth |
| Debugging | Isolated phases are easier to diagnose |

---

## 13. Related Documents

- `architecture/main-system-patterns/phase1-reflection.md` - Next phase (uses QueryAnalysis)
- `architecture/main-system-patterns/phase2-context-gathering.md` - Uses resolved_query for search
- `architecture/LLM-ROLES/llm-roles-reference.md` - Model assignments

---

## 14. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 1.1 | 2026-01-05 | Removed implementation file references, added Related Documents and Changelog |
| 1.2 | 2026-01-05 | Replaced `was_resolved` boolean with `reference_resolution` object containing 3-state status enum (`not_needed`, `resolved`, `failed`) for unambiguous Phase 1 handling |
| 1.3 | 2026-01-22 | Added Intent Classification (Section 4), Mode Detection (Section 5). Added `intent`, `mode` fields to output schema. Phase 0 now owns intent classification (previously duplicated in Phase 3). Greeting intent handled via Planner COMPLETE decision (no phase skipping). |
| 1.4 | 2026-01-24 | Added spelling/terminology correction as responsibility #4 in LLM Prompt Design. Query Analyzer now normalizes user input to authoritative spelling from context (names, brands, products, technical terms). |

---

**Last Updated:** 2026-01-24
