# Phase 8: Save

**Status:** SPECIFICATION
**Version:** 3.0
**Created:** 2026-01-04
**Updated:** 2026-01-24
**Layer:** None (procedural, no LLM)

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

**Key Design Principle:** Save full documents unsummarized. Summarization happens at retrieval time (Phase 2), not save time. This preserves maximum fidelity for context-appropriate summarization later.

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
│ • tool stats  │    │ • calibration │    │               │
│ • model usage │    │   predictions │    │               │
└───────────────┘    └───────────────┘    └───────────────┘
```

### 2.1 Observability System Integration

**Source:** `architecture/DOCUMENT-IO-SYSTEM/OBSERVABILITY_SYSTEM.md`

Phase 8 collects timing and decision data accumulated during phases 0-7 and writes `metrics.json`:

| Data | Source Phase | Purpose |
|------|--------------|---------|
| Phase timing (duration_ms) | All phases | Identify bottlenecks |
| Token usage (in/out) | All LLM phases | Track costs |
| Model used per phase | All LLM phases | Verify correct routing |
| Tool execution stats | Phase 4-5 | Track tool reliability |
| Decision trail | Phases 0,1,3,4,7 | Debug failed turns |
| Validation outcome | Phase 7 | Quality tracking |

### 2.2 Confidence System Integration

**Source:** `architecture/main-system-patterns/UNIVERSAL_CONFIDENCE_SYSTEM.md`

Phase 8 stores quality scores for future retrieval and calibration:

| Data | Source | Purpose |
|------|--------|---------|
| `quality_score` | Phase 7 validation confidence | Filter stale data in Phase 2 |
| `content_type` | Phase 3 intent classification | Apply correct decay rate |
| Calibration predictions | Phase 4-5 claims | Later ECE calculation |

### 2.3 User Feedback System Integration

**Source:** `architecture/main-system-patterns/USER_FEEDBACK_SYSTEM.md`

Phase 8 prepares for feedback detection in the **next turn's Phase 2**:

| Data Stored | Purpose |
|-------------|---------|
| Turn metadata | Enables Phase 2 to find previous turn |
| Response content | Enables correction detection |
| `user_feedback_status: 'neutral'` | Default until next turn updates it |

**Important:** Phase 8 does NOT detect feedback. It stores metadata that enables Phase 2 of the next turn to detect corrections/acceptance.

---

## 3. Document Storage Structure

Each turn creates a directory with all relevant artifacts:

```
panda-system-docs/users/{user_id}/turns/turn_{NNNNNN}/
├── context.md      # Full accumulated document (§0-§7)
├── response.md     # Final response sent to user
├── metadata.json   # Turn metadata for indexing
├── metrics.json    # Observability data (timing, decisions, tools)
├── ticket.md       # Task specification (if Planner created one)
└── toolresults.md  # Tool execution details (if Coordinator ran tools)
```

### Document Descriptions

| Document | Required | Source | Purpose |
|----------|----------|--------|---------|
| `context.md` | Yes | All phases | Complete turn context for future retrieval |
| `response.md` | Yes | Phase 6 | Final user-facing response |
| `metadata.json` | Yes | Phase 8 | Turn metadata for indexing and search |
| `metrics.json` | Yes | Phase 8 | Observability data (see section 4) |
| `ticket.md` | Optional | Phase 3 | Task plan (only if Planner created one) |
| `toolresults.md` | Optional | Phase 5 | Tool results (only if Coordinator ran tools) |

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
      "phase": "reflection",
      "phase_number": 1,
      "decision_type": "proceed",
      "decision_value": "PROCEED"
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

  "tools": [
    {
      "tool": "internet.research",
      "duration_ms": 28000,
      "success": true,
      "claims_extracted": 5
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
  "topic": "gaming laptops",
  "intent": "commerce",
  "tools_used": ["internet.research"],
  "claims_count": 5,
  "quality_score": 0.92,
  "content_type": "price",
  "user_feedback_status": "neutral",
  "keywords": ["laptop", "gaming", "nvidia"]
}
```

### Field Definitions

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `turn_number` | integer | System | Monotonically increasing turn ID |
| `session_id` | string | System | User/session identifier |
| `timestamp` | integer | System | Unix timestamp of turn completion |
| `topic` | string | Phase 3 | Human-readable topic summary |
| `intent` | string | Phase 3 | Intent classification |
| `tools_used` | array | Phase 4-5 | List of tools invoked |
| `claims_count` | integer | Phase 4-5 | Number of claims extracted |
| `quality_score` | float | Phase 7 | Validation confidence (0.0-1.0) |
| `content_type` | string | Phase 3 | For decay rate selection |
| `user_feedback_status` | string | Default | 'neutral' until next turn updates |
| `keywords` | array | Phase 8 | Extracted keywords for search |

---

## 6. Index Updates

### 6.1 TurnIndexDB

**Purpose:** Enable session-scoped lookup for Context Gatherer (Phase 2)

**Database:** `panda-system-docs/indexes/turn_index.db`

| Column | Type | Purpose |
|--------|------|---------|
| `turn_number` | INTEGER PRIMARY KEY | Unique turn identifier |
| `session_id` | TEXT (indexed) | Session scoping |
| `timestamp` | TEXT (indexed DESC) | Chronological ordering |
| `topic` | TEXT | Topic summary |
| `intent` | TEXT | Intent classification |
| `quality_score` | REAL | For quality filtering |
| `user_feedback_status` | TEXT | 'rejected', 'accepted', 'neutral' |
| `turn_dir` | TEXT | Path to turn directory |

### 6.2 ResearchIndexDB

**Purpose:** Enable research cache lookup and deduplication

**Database:** `panda-system-docs/indexes/research_index.db`

**Triggered When:** `internet.research` tool was called during Phase 4-5

| Field | Type | Purpose |
|-------|------|---------|
| `primary_topic` | TEXT | Dotted path (e.g., `commerce.laptop.gaming`) |
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
│   - toolresults.md (if tools ran)                                    │
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
| Detect "remember that..." patterns | Phase 3 (Planner) | LLM decision → creates memory.save tool call |
| Execute memory.save | Phase 5 (Coordinator) | Tool execution |
| Detect user feedback | Phase 2 of NEXT turn | Needs user's next message |
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

## 10. Related Documents

- `architecture/main-system-patterns/phase7-validation.md` - Prior phase
- `architecture/main-system-patterns/phase2-context-gathering.md` - How saved turns are retrieved
- `architecture/DOCUMENT-IO-SYSTEM/OBSERVABILITY_SYSTEM.md` - metrics.json specification
- `architecture/main-system-patterns/UNIVERSAL_CONFIDENCE_SYSTEM.md` - Quality scores and decay
- `architecture/main-system-patterns/USER_FEEDBACK_SYSTEM.md` - Feedback detection (next turn)
- `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` - context.md specification

---

## 11. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 2.0 | 2026-01-05 | Added system integrations (Observability, Confidence, User Feedback) |
| 2.1 | 2026-01-05 | Header format consistency |
| 3.0 | 2026-01-24 | **Renumbered from Phase 7 to Phase 8** due to new Executor phase. Updated section numbers (§0-§6→§0-§7). Updated source phase references (Synthesis now Phase 6, Coordinator now Phase 5, Validation now Phase 7). |

---

**Last Updated:** 2026-01-24
