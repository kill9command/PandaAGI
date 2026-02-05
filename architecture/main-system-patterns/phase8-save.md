# Phase 8: Save

**Status:** SPECIFICATION
**Version:** 3.4
**Created:** 2026-01-04
**Updated:** 2026-02-04
**Layer:** None (procedural, no LLM)

**Related Concepts:** See §11 (Concept Alignment)

---

## 1. Overview

**Question:** "What do we preserve for future turns?"

Phase 8 is a purely procedural phase that persists all turn artifacts and generates observability data. Unlike other phases, no LLM is required - this is deterministic file I/O and database operations.

| Aspect | Specification |
|--------|---------------|
| **Input** | context.md (§0-§7) + response.md + phase timing data |
| **Output** | Turn documents, metrics.json, index updates |
| **LLM Required** | No |
| **Timing** | Runs AFTER response is sent to user |


---

## 2. System Integrations

Phase 8 is the integration point where three systems come together:

```
Turn Execution Complete → Response Sent to User
                              │
                              ▼
                      ┌───────────────┐
                      │   PHASE 8     │
                      │     SAVE      │
                      └───────┬───────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ OBSERVABILITY │    │   CONFIDENCE  │    │ USER FEEDBACK │
│    SYSTEM     │    │    SYSTEM     │    │    SYSTEM     │
├───────────────┤    ├───────────────┤    ├───────────────┤
│ metrics.json  │    │ quality_score │    │ Prepare for   │
│ • timing      │    │ • from §7     │    │ next turn     │
│ • decisions   │    │ • decay rates │    │ detection     │
│ • workflow stats  │    │ • calibration │    │               │
│ • model usage │    │   predictions │    │               │
└───────────────┘    └───────────────┘    └───────────────┘
```

### 2.1 Observability System Integration

**Source:** `architecture/concepts/DOCUMENT-IO-SYSTEM/OBSERVABILITY_SYSTEM.md`

Phase 8 collects timing and decision data accumulated during phases 0-7 and writes `metrics.json`:

| Data | Source Phase | Purpose |
|------|--------------|---------|
| Phase timing (duration_ms) | All phases | Identify bottlenecks |
| Token usage (in/out) | All LLM phases | Track costs |
| Model used per phase | All LLM phases | Verify correct routing |
| Workflow execution stats | Phase 4-5 | Track workflow reliability |
| Decision trail | Phases 1,3,4,7 | Debug failed turns |
| Validation outcome | Phase 7 | Quality tracking |

### 2.2 Confidence System Integration

**Source:** `architecture/concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md`

Phase 8 stores quality scores for future retrieval and calibration:

| Data | Source | Purpose |
|------|--------|---------|
| `quality_score` | Phase 7 validation confidence | Filter stale data in Phase 2 |
| `content_type` | Phase 3 planning | Apply correct decay rate |
| Calibration predictions | Phase 4-5 claims | Later ECE calculation |

---

## 3. Document Storage Structure

Each turn creates a directory with all relevant artifacts:

```
panda_system_docs/users/{user_id}/turns/turn_{NNNNNN}/
├── context.md      # Full accumulated document (§0-§7)
├── response.md     # Final response sent to user
├── artifacts/      # Output files (DOCX/XLSX/PDF/PPTX)
├── plan_state.json  # PlanState tracking goals and execution progress
├── metadata.json   # Turn metadata for indexing
├── metrics.json    # Observability data (timing, decisions, workflows)
├── ticket.md       # Task specification (legacy, if created)
└── toolresults.md  # Workflow execution details (embedded tool runs)
```

### Document Descriptions

| Document | Required | Source | Purpose |
|----------|----------|--------|---------|
| `context.md` | Yes | All phases | Complete turn context for future retrieval |
| `response.md` | Yes | Phase 6 | Final user-facing response |
| `plan_state.json` | Optional | Phase 3/5/7 | PlanState with goals and execution progress |
| `metadata.json` | Yes | Phase 8 | Turn metadata for indexing and search |
| `metrics.json` | Yes | Phase 8 | Observability data (see section 5) |
| `ticket.md` | Optional | Phase 3 | Task plan (legacy, only if created) |
| `toolresults.md` | Optional | Phase 5 | Workflow results (only if Coordinator ran workflows) |

### Directory Naming

Turn directories use zero-padded 6-digit numbering:
- `turn_000001/` (turn 1)
- `turn_000742/` (turn 742)

---

## 4. metrics.json Schema

Combines all observability data for the turn:

```json
{
  "turn_number": 742,
  "session_id": "user123",
  "timestamp": "2026-01-05T10:30:00Z",

  "timing": {
    "total_duration_ms": 45000,
    "total_tokens": 12450,
    "phases": [
      {
        "phase": "query_analyzer",
        "phase_number": 0,
        "model_used": "REFLEX",
        "duration_ms": 450,
        "tokens_in": 500,
        "tokens_out": 180
      },
      {
        "phase": "executor",
        "phase_number": 4,
        "model_used": "MIND",
        "duration_ms": 5000,
        "tokens_in": 2000,
        "tokens_out": 500,
        "iterations": 3
      }
    ]
  },

  "decisions": [
    {
      "phase": "query_analysis_validation",
      "phase_number": 1,
      "decision_type": "validation",
      "decision_value": "pass"
    },
    {
      "phase": "planner",
      "phase_number": 3,
      "decision_type": "route",
      "decision_value": "executor"
    },
    {
      "phase": "executor",
      "phase_number": 4,
      "decision_type": "complete",
      "decision_value": "COMPLETE",
      "iterations": 3
    },
    {
      "phase": "validation",
      "phase_number": 7,
      "decision_type": "validation",
      "decision_value": "APPROVE"
    }
  ],

  "workflows": [
    {
      "workflow": "<workflow_name>",
      "duration_ms": 28000,
      "success": true,
      "claims_extracted": 5,
      "tool_runs": 3
    }
  ],

  "quality": {
    "validation_result": "APPROVE",
    "confidence": 0.92,
    "claims_count": 5
  }
}
```

---

## 5. metadata.json Schema

Turn metadata for indexing and retrieval:

```json
{
  "turn_number": 742,
  "session_id": "user123",
  "timestamp": 1765038247,
  "topic": "<topic>",
  "workflows_used": ["<workflow_name>"],
  "claims_count": 5,
  "quality_score": 0.92,
  "content_type": "price",
  "keywords": ["<keyword_1>", "<keyword_2>", "<keyword_3>"]
}
```

### Field Definitions

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `turn_number` | integer | System | Monotonically increasing turn ID |
| `session_id` | string | System | User/session identifier |
| `timestamp` | integer | System | Unix timestamp of turn completion |
| `topic` | string | Phase 3 | Human-readable topic summary |
| `workflows_used` | array | Phase 4-5 | List of workflows invoked |
| `claims_count` | integer | Phase 4-5 | Number of claims extracted |
| `quality_score` | float | Phase 7 | Validation confidence (0.0-1.0) |
| `content_type` | string | Phase 3 | For decay rate selection |
| `keywords` | array | Phase 8 | Extracted keywords for search |

---

## 6. Index Updates

### 7.1 TurnIndexDB

**Purpose:** Enable session-scoped lookup for Context Gatherer (Phase 2)

**Database:** `panda-system-docs/indexes/turn_index.db`

| Column | Type | Purpose |
|--------|------|---------|
| `turn_number` | INTEGER PRIMARY KEY | Unique turn identifier |
| `session_id` | TEXT (indexed) | Session scoping |
| `timestamp` | TEXT (indexed DESC) | Chronological ordering |
| `topic` | TEXT | Topic summary |
| `quality_score` | REAL | For quality filtering |
| `turn_dir` | TEXT | Path to turn directory |

### 7.2 ResearchIndexDB

**Purpose:** Enable research cache lookup and deduplication

**Database:** `panda-system-docs/indexes/research_index.db`

**Triggered When:** a research workflow was called during Phase 4-5

| Field | Type | Purpose |
|-------|------|---------|
| `primary_topic` | TEXT | Dotted path (e.g., `<category.subcategory>` ) |
| `quality_score` | FLOAT | Quality with decay applied |
| `created_at` | TIMESTAMP | When research was conducted |
| `expires_at` | TIMESTAMP | TTL expiration |
| `content_type` | TEXT | For decay rate |

---

## 7. Process Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PHASE 8: SAVE                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [Response already sent to user]                                     │
│              │                                                       │
│              ▼                                                       │
│  Step 1: Create Turn Directory                                       │
│              │                                                       │
│              ▼                                                       │
│  Step 2: Save Core Documents                                         │
│   - context.md (full §0-§7)                                          │
│   - response.md                                                      │
│   - metadata.json                                                    │
│              │                                                       │
│              ▼                                                       │
│  Step 3: Save Optional Documents                                     │
│   - ticket.md (if created)                                           │
│   - toolresults.md (if workflows ran)                                    │
│              │                                                       │
│              ▼                                                       │
│  Step 4: Generate Observability Data                                 │
│   - Collect timing from all phases                                   │
│   - Extract decision trail                                           │
│   - Write metrics.json                                               │
│              │                                                       │
│              ▼                                                       │
│  Step 5: Update TurnIndexDB                                          │
│              │                                                       │
│              ▼                                                       │
│  Step 6: Update ResearchIndexDB (if applicable)                      │
│              │                                                       │
│              ▼                                                       │
│  Step 7: Log Transcript                                              │
│              │                                                       │
│              ▼                                                       │
│           [Done]                                                     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. What Phase 8 Does NOT Do

| Task | Where It Belongs | Why |
|------|------------------|-----|
| Detect "remember that..." patterns | Phase 3 (Planner) | LLM decision → creates memory.save workflow call |
| Execute memory.save | Phase 5 (Coordinator) | Tool execution |
| Summarize documents | Phase 2 (retrieval time) | Context-appropriate summarization |
| Make quality decisions | Phase 7 (Validation) | LLM judgment |

Phase 8 is purely procedural. It saves what other phases produced.

---

## 9. Error Handling (Fail-Fast)

All save operations must succeed or halt with an intervention request:

| Failure | Action |
|---------|--------|
| Directory creation fails | HALT - create intervention |
| Core document write fails | HALT - create intervention |
| Index update fails | HALT - create intervention |
| Metrics generation fails | HALT - create intervention |

**Rationale:** Partial saves create inconsistent state. Every failure is a bug that must be fixed.

---

## 10. Turn Summary Generation

Phase 8 is responsible for generating turn summaries that populate the turn index. This happens **after all turn artifacts are saved**, as an async background task. The summary is appended to `context.md` as the final section (see §10.4).

**Turn Summary Purpose:** This summary is a lightweight continuity snapshot for Phase 1 (Query Analyzer). It is **not** a replacement for Phase 2 retrieval summaries, which are task-specific and generated at retrieval time.

### 10.1 Summary Generation Role

| Aspect | Value |
|--------|-------|
| **Model** | MIND (Qwen3-Coder-30B-AWQ) |
| **Temperature** | 0.3 (REFLEX-like, deterministic) |
| **Prompt** | Dedicated summarization prompt |
| **Trigger** | After Phase 8 completes (async) |

### 10.2 Summary Prompt Pattern

```
Given the completed turn context.md, generate a concise summary for the turn index.

Input: Full context.md (§0-§7)

Output:
{
  "summary": "1-2 sentence description of what happened",
  "topics": ["topic1", "topic2", ...],  // 2-5 keywords
  "has_research": true|false,
  "research_topic": "category.subcategory" or null
}
```

### 10.3 Example

**Input (context.md):**
```markdown
## 0. User Query
Find me a <item_type> under <budget>

## 3. Task Plan
...

## 4. Execution Progress
**Workflow:** <workflow_name>
**Results:** Found <N> items...
...
```

**Output:**
```json
{
  "summary": "Searched for <item_type> under <budget>, found <N> options from <N> sources",
  "topics": ["<topic_1>", "<topic_2>", "<topic_3>"],
  "has_research": true,
  "research_topic": "<category.subcategory>"
}
```

### 10.4 Index Update

The summary is appended to context.md as the final section and written to `turn_index.db` for fast retrieval by future Phase 1 analysis.

---

## 11. Concept Alignment

This section maps Phase 8's responsibilities to the cross-cutting concept documents.

| Concept | Document | Phase 8 Relevance |
|---------|----------|--------------------|
| **Document IO** | `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | The PRIMARY concept relationship. Phase 8 persists all turn documents: context.md (§0–§7), response.md, metadata.json, toolresults.md, plan state, and artifacts. This is where the document pipeline materializes to disk. |
| **Observability** | `concepts/DOCUMENT-IO-SYSTEM/OBSERVABILITY_SYSTEM.md` | Generates metrics.json with timing, token usage, decision trail, workflow stats, and model usage for every turn. This is the sole source of operational telemetry. |
| **Confidence System** | `concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` | Stores `quality_score` from Phase 7 in metadata.json. This score is used by Phase 2 for future retrieval filtering and by the confidence system for ECE calibration. Content type is stored for decay rate selection. |
| **Memory Architecture** | `concepts/memory_system/MEMORY_ARCHITECTURE.md` | Phase 8 indexes every turn — context.md IS the lesson (§3 of Memory Architecture). Memory candidates approved by Validation are committed here. Turn archival lifecycle (active 0–30 days, archived 30+ days) is managed by Phase 8's index. |
| **Artifact System** | `concepts/artifacts_system/ARTIFACT_SYSTEM.md` | Stores output artifacts (documents, files) and their manifest. Artifacts are linked to turns for future retrieval. |
| **Error Handling** | `concepts/error_and_improvement_system/ERROR_HANDLING.md` | Fail-fast on all save operations. Partial saves create inconsistent state — every write failure (directory creation, document write, index update) HALTs with an intervention request. |
| **Context Compression** | `concepts/system_loops/CONTEXT_COMPRESSION.md` | Turn archival at 30+ days triggers NERVES summarization as a background task. Summary is retained in the index for search; originals move to cold storage. Phase 8 saves full documents — compression happens at retrieval time, not save time. |
| **Recipe System** | `concepts/recipe_system/RECIPE_SYSTEM.md` | No LLM required — Phase 8 is purely procedural. But the turn documents it persists include all recipe outputs from Phases 0–7, making this the permanent record of every recipe invocation. |

---

## 12. Related Documents

- `architecture/main-system-patterns/phase7-validation.md` — Prior phase
- `architecture/main-system-patterns/phase2.1-context-gathering-retrieval.md` — How saved turns are retrieved
- `architecture/concepts/DOCUMENT-IO-SYSTEM/OBSERVABILITY_SYSTEM.md` — metrics.json specification
- `architecture/concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` — Quality scores and decay
- `architecture/concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` — context.md specification

---

## 13. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 2.0 | 2026-01-05 | Added system integrations (Observability, Confidence, User Feedback) |
| 2.1 | 2026-01-05 | Header format consistency |
| 3.0 | 2026-01-24 | **Renumbered from Phase 7 to Phase 8** due to new Executor phase. Updated section numbers (§0-§6→§0-§7). Updated source phase references (Synthesis now Phase 6, Coordinator now Phase 5, Validation now Phase 7). |
| 3.1 | 2026-02-03 | Added §10 Concept Alignment. Fixed wrong paths for Observability, Confidence, and Document IO docs (inline and Related Documents). Removed stale Concept Implementation Touchpoints and Benchmark Gaps sections. Renumbered sections. |
| 3.2 | 2026-02-04 | Removed `action_needed` from persisted turn schema to align with Phase 1 outputs. |
| 3.3 | 2026-02-04 | Moved Turn Summary Generation into Phase 8 and added summary prompt pattern. |
| 3.4 | 2026-02-04 | Shifted persisted metadata and examples to workflow-centric terminology; clarified summary append to context.md. |

---

**Last Updated:** 2026-02-04
