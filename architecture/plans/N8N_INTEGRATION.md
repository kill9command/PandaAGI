# n8n Integration Architecture

**Status:** SPECIFICATION
**Version:** 1.0
**Created:** 2026-01-21
**Updated:** 2026-01-21

---

## 1. Overview

This document specifies how external orchestration tools like n8n can control Pandora's 8-phase pipeline. The Phase API exposes each phase as an independent REST endpoint, enabling:

1. **Visual workflow building** - n8n users can design custom flows
2. **Phase-level control** - Call individual phases independently
3. **State management flexibility** - Pass state inline or reference by turn_id
4. **Monitoring integration** - n8n's built-in logging and alerting

**Goal:** Enable n8n to orchestrate the entire 8-phase pipeline, potentially replacing `unified_flow.py` for certain use cases.

---

## 2. Architecture

### 2.1 Phase API Overview

```
n8n Workflow
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR (port 8090)                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Phase API (/phases/*)                                              │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  POST /phases/0-query-analyzer   → QueryAnalyzer.execute()  │   │
│  │  POST /phases/1-reflection       → Reflection.execute()     │   │
│  │  POST /phases/2-context-gatherer → ContextGatherer.execute()│   │
│  │  POST /phases/3-planner          → Planner.execute()        │   │
│  │  POST /phases/4-coordinator      → [Stub - needs tools]     │   │
│  │  POST /phases/5-synthesis        → Synthesis.execute()      │   │
│  │  POST /phases/6-validation       → Validation.execute()     │   │
│  │  POST /phases/7-save             → TurnManager.save()       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  Existing Endpoints                                                 │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  POST /chat         → Full pipeline (unified_flow.py)       │   │
│  │  WS   /chat/stream  → Streaming pipeline                    │   │
│  │  GET  /health       → Health check                          │   │
│  │  ...                                                         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 State Management Options

Each phase endpoint supports two state management approaches:

| Approach | Description | Use Case |
|----------|-------------|----------|
| **Inline** | Pass section contents in request body | Stateless n8n workflows, testing |
| **Turn Reference** | Pass `turn_id` to load from Pandora storage | Stateful workflows, debugging |

**Inline Mode:**
```json
{
  "section_0_content": "## 0. User Query\n...",
  "section_1_content": "## 1. Reflection Decision\n...",
  "session_id": "abc123"
}
```

**Turn Reference Mode:**
```json
{
  "turn_id": 815,
  "session_id": "abc123"
}
```

---

## 3. Endpoint Specifications

### 3.1 Phase 0: Query Analyzer

**Endpoint:** `POST /phases/0-query-analyzer`

**Purpose:** Resolve references and classify query type.

**Request:**
```json
{
  "raw_query": "what did they recommend in the thread?",
  "turn_summaries": [
    {
      "turn_id": 814,
      "summary": "Researched best glass scrapers",
      "content_refs": ["GarageJournal thread"],
      "topics": ["glass", "scraper"]
    }
  ],
  "session_id": "abc123",
  "mode": "chat"
}
```

**Response:**
```json
{
  "analysis": {
    "original_query": "what did they recommend in the thread?",
    "resolved_query": "what did they recommend in the 'Best glass scraper' thread?",
    "was_resolved": true,
    "query_type": "specific_content",
    "reasoning": "Resolved 'the thread' to GarageJournal thread from turn 814"
  },
  "metadata": {
    "phase_number": 0,
    "phase_name": "query_analyzer",
    "execution_time_ms": 85.2,
    "status": "success"
  },
  "section_0_content": "## 0. User Query\n\n**Original:** what did they recommend in the thread?..."
}
```

### 3.2 Phase 1: Reflection

**Endpoint:** `POST /phases/1-reflection`

**Purpose:** PROCEED/CLARIFY gate based on query clarity.

**Request:**
```json
{
  "section_0_content": "## 0. User Query\n...",
  "session_id": "abc123",
  "mode": "chat"
}
```

**Response:**
```json
{
  "result": {
    "decision": "PROCEED",
    "confidence": 0.95,
    "query_type": "ACTION",
    "is_followup": false,
    "reasoning": "Query is clear - asking about previous thread recommendations"
  },
  "metadata": {...},
  "should_proceed": true,
  "clarification_question": null,
  "section_1_content": "## 1. Reflection Decision\n..."
}
```

### 3.3 Phase 2: Context Gatherer

**Endpoint:** `POST /phases/2-context-gatherer`

**Purpose:** Gather relevant context from memory, turns, and cache.

**Request:**
```json
{
  "section_0_content": "...",
  "section_1_content": "...",
  "session_id": "abc123",
  "user_id": "default",
  "mode": "chat"
}
```

**Response:**
```json
{
  "gathered": {
    "session_preferences": {"budget": "$500"},
    "relevant_turns": [...],
    "cached_research": {...},
    "sufficiency_assessment": "Have relevant prior turn but need fresh prices"
  },
  "metadata": {...},
  "has_sufficient_context": false,
  "section_2_content": "## 2. Gathered Context\n..."
}
```

### 3.4 Phase 3: Planner

**Endpoint:** `POST /phases/3-planner`

**Purpose:** Plan tasks and determine routing.

**Request:**
```json
{
  "section_0_content": "...",
  "section_1_content": "...",
  "section_2_content": "...",
  "session_id": "abc123",
  "mode": "chat",
  "is_retry": false,
  "attempt_number": 1
}
```

**Response:**
```json
{
  "plan": {
    "decision": "EXECUTE",
    "route": "coordinator",
    "goals": [...],
    "tool_requests": [{"tool": "internet.research", "args": {...}}],
    "reasoning": "Need fresh product prices from web research"
  },
  "metadata": {...},
  "route_to": "coordinator",
  "ticket_json": {...},
  "section_3_content": "## 3. Task Plan\n..."
}
```

### 3.5 Phase 4: Coordinator (Stub)

**Endpoint:** `POST /phases/4-coordinator`

**Status:** STUB - Full implementation requires tool infrastructure

**Note:** Phase 4 requires the MCP tool execution infrastructure (browser, file system, etc.). For n8n integration, either:
1. Use the full `/chat` endpoint which includes tool execution
2. Build separate tool endpoints for n8n to call directly
3. Use n8n's HTTP nodes to call external APIs directly

### 3.6 Phase 5: Synthesis

**Endpoint:** `POST /phases/5-synthesis`

**Purpose:** Generate user-facing response.

**Request:**
```json
{
  "section_0_content": "...",
  "section_1_content": "...",
  "section_2_content": "...",
  "section_3_content": "...",
  "section_4_content": "...",
  "toolresults_content": "...",
  "session_id": "abc123",
  "mode": "chat",
  "is_revision": false
}
```

**Response:**
```json
{
  "result": {
    "response_preview": "Based on the GarageJournal thread...",
    "full_response": "Based on the GarageJournal thread, users recommend...",
    "citations": ["[1] GarageJournal thread"],
    "validation_checklist": {...}
  },
  "metadata": {...},
  "response": "Based on the GarageJournal thread, users recommend...",
  "section_5_content": "## 5. Synthesis\n..."
}
```

### 3.7 Phase 6: Validation

**Endpoint:** `POST /phases/6-validation`

**Purpose:** Quality gate - APPROVE, REVISE, RETRY, or FAIL.

**Request:**
```json
{
  "section_0_content": "...",
  "section_1_content": "...",
  "section_2_content": "...",
  "section_3_content": "...",
  "section_4_content": "...",
  "section_5_content": "...",
  "toolresults_content": "...",
  "session_id": "abc123",
  "mode": "chat"
}
```

**Response:**
```json
{
  "result": {
    "decision": "APPROVE",
    "confidence": 0.92,
    "checks": [...],
    "issues": [],
    "overall_quality": 0.88
  },
  "metadata": {...},
  "decision": "APPROVE",
  "is_approved": true,
  "needs_retry": false,
  "needs_revision": false,
  "section_6_content": "## 6. Validation\n..."
}
```

### 3.8 Phase 7: Save

**Endpoint:** `POST /phases/7-save`

**Purpose:** Persist the completed turn.

**Request:**
```json
{
  "section_0_content": "...",
  "section_1_content": "...",
  "section_2_content": "...",
  "section_3_content": "...",
  "section_4_content": "...",
  "section_5_content": "...",
  "section_6_content": "...",
  "final_response": "Based on the GarageJournal thread...",
  "quality_score": 0.88,
  "session_id": "abc123",
  "user_id": "default"
}
```

**Response:**
```json
{
  "turn_id": 816,
  "turn_path": "panda_system_docs/users/default/turns/turn_000816",
  "metadata": {...},
  "index_updated": true,
  "summary_generated": false
}
```

---

## 4. n8n Workflow Patterns

### 4.1 Simple Query Flow (No Tools)

```
┌─────────────────┐
│  Webhook        │ ← User query
│  (trigger)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Phase 0        │
│  Query Analyzer │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Phase 1        │
│  Reflection     │
└────────┬────────┘
         │
    ┌────┴────┐
    │ Switch  │
    └────┬────┘
         │
    PROCEED?
    ├── NO ──► Return clarification question
    │
    YES
    │
         ▼
┌─────────────────┐
│  Phase 2        │
│  Context        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Phase 3        │
│  Planner        │
└────────┬────────┘
         │
    ┌────┴────┐
    │ Switch  │
    └────┬────┘
         │
    route_to?
    ├── coordinator ──► [Phase 4 stub - use /chat instead]
    │
    synthesis
    │
         ▼
┌─────────────────┐
│  Phase 5        │
│  Synthesis      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Phase 6        │
│  Validation     │
└────────┬────────┘
         │
    ┌────┴────┐
    │ Switch  │
    └────┬────┘
         │
    decision?
    ├── RETRY ──► Back to Phase 3
    ├── REVISE ──► Back to Phase 5
    ├── FAIL ──► Return error
    │
    APPROVE
    │
         ▼
┌─────────────────┐
│  Phase 7        │
│  Save           │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Respond to     │
│  Webhook        │ → User response
└─────────────────┘
```

### 4.2 Loop Pattern for RETRY/REVISE

n8n supports loops via the Loop node or by connecting outputs back to inputs:

```javascript
// Pseudo-code for n8n loop logic
let attempt = 1;
let maxRetries = 2;
let maxRevisions = 2;

while (true) {
  let validation = callPhase6(context);

  if (validation.is_approved) {
    break;
  } else if (validation.needs_retry && attempt < maxRetries) {
    // Back to Planner with failure context
    context.section_6_content = validation.section_6_content;
    context = callPhase3(context, is_retry=true);
    context = callPhase5(context);
    attempt++;
  } else if (validation.needs_revision && revisions < maxRevisions) {
    // Back to Synthesis with hints
    context = callPhase5(context, revision_hints=validation.result.revision_hints);
  } else {
    // FAIL
    return { error: validation.result.issues };
  }
}
```

---

## 5. State Accumulation Pattern

The key challenge for n8n is managing the accumulated `context.md` state.

### 5.1 n8n Variable Accumulation

Use n8n's Set node to accumulate section content:

```javascript
// After each phase, append section content to state
$json.state = $json.state || {};
$json.state.section_0 = $("Phase 0").item.json.section_0_content;
$json.state.section_1 = $("Phase 1").item.json.section_1_content;
// ... etc.
```

### 5.2 Full Context State Model

For complex workflows, use the `FullContextState` model:

```json
{
  "turn_id": null,
  "session_id": "abc123",
  "user_id": "default",
  "mode": "chat",
  "section_0": "## 0. User Query\n...",
  "section_1": "## 1. Reflection Decision\n...",
  "section_2": "## 2. Gathered Context\n...",
  "section_3": null,
  "section_4": null,
  "section_5": null,
  "section_6": null,
  "toolresults": null,
  "ticket_json": null,
  "final_response": null,
  "quality_score": null,
  "current_phase": 2,
  "is_complete": false
}
```

---

## 6. Known Limitations

### 6.1 Phase 4 (Coordinator) Stub

Phase 4 requires:
- Browser automation (Playwright)
- MCP tool infrastructure
- Research orchestration

**Workarounds:**
1. Use full `/chat` endpoint for queries needing tools
2. Build separate tool endpoints
3. Use n8n's HTTP nodes directly

### 6.2 Token Budget Management

n8n doesn't natively track LLM tokens. Options:
- Monitor `metadata.tokens_used` in responses
- Implement budget tracking in n8n workflow
- Use Pandora's built-in limits

### 6.3 Error Handling

Phase errors return HTTP 500 with error details. n8n should:
- Use IF nodes to check `metadata.status`
- Handle `intervention_required` (HTTP 503) specially
- Implement retry logic for transient failures

---

## 7. Implementation Files

| File | Purpose |
|------|---------|
| `apps/services/orchestrator/phase_schemas.py` | Request/response models |
| `apps/services/orchestrator/phase_api.py` | REST endpoints |
| `apps/services/orchestrator/app.py` | Router registration |

---

## 8. Testing

### 8.1 curl Examples

**Phase 0:**
```bash
curl -X POST http://localhost:8090/phases/0-query-analyzer \
  -H "Content-Type: application/json" \
  -d '{
    "raw_query": "find me a cheap laptop",
    "turn_summaries": [],
    "session_id": "test",
    "mode": "chat"
  }'
```

**Phase 1:**
```bash
curl -X POST http://localhost:8090/phases/1-reflection \
  -H "Content-Type: application/json" \
  -d '{
    "section_0_content": "## 0. User Query\n\n**Original:** find me a cheap laptop\n...",
    "session_id": "test",
    "mode": "chat"
  }'
```

### 8.2 n8n Workflow Import

A sample n8n workflow JSON will be provided in:
`architecture/integrations/n8n_workflows/simple_query.json`

---

## 9. Related Documents

- `architecture/README.md` - System overview
- `architecture/main-system-patterns/phase*.md` - Individual phase specs
- `architecture/services/orchestrator-service.md` - Orchestrator service
- `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` - context.md format

---

## 10. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-21 | Initial specification |

---

**Last Updated:** 2026-01-21
