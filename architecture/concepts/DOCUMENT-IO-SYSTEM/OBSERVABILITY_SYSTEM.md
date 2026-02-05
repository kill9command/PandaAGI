# Observability System

**Version:** 2.0
**Updated:** 2026-02-03

---

## 1. Purpose

Observability enables the system to answer five questions:

1. **Why did this turn fail?** — Decision trail
2. **Where is the bottleneck?** — Phase timing and token usage
3. **Is quality improving?** — Research quality trends
4. **Which tools are unreliable?** — Tool execution stats
5. **Are our confidence scores accurate?** — Calibration tracking

---

## 2. Design Principles

- **Observability is a document.** Following the "everything is a document" pattern, metrics are stored alongside turn data and are retrievable by the Context Gatherer for self-improvement.
- **Build on what exists.** context.md already contains the full decision flow. Observability extracts structured data from it rather than creating parallel systems.
- **Two levels.** Per-turn detail for debugging specific issues. Daily aggregation for trends and system health.

---

## 3. Components

### 3.1 Phase Timing & Token Usage

Every phase records its start time, end time, token consumption (prompt + completion), number of LLM calls, and which model role was used (REFLEX, MIND, VOICE, EYES). Tool calls within the Coordinator are tracked individually.

At the turn level, the system identifies the slowest phase and highest token consumer, enabling quick bottleneck identification. Token usage is broken down by model role for cost tracking.

**Key questions answered:**
- Which phase is the bottleneck?
- Are token budgets being respected?
- Is the right model role being used per phase?

### 3.2 Decision Trail

Every decision point in the pipeline is captured as a structured record: which phase, which model role, what was decided, and why. The decision trail is extracted from context.md sections — the data already exists in the document, observability makes it queryable.

Decision points tracked:
- Phase 0: Action classification and query resolution
- Phase 1: PROCEED or CLARIFY
- Phase 3: Routing decision (coordinator, synthesis, clarify)
- Phase 4–5: Each Executor command and Coordinator tool call (TOOL_CALL, DONE, BLOCKED)
- Phase 7: Validation outcome (APPROVE, REVISE, RETRY, FAIL)

**Key questions answered:**
- What chain of decisions led to a failure?
- Why did the Planner route to coordinator instead of synthesis?
- At which decision point did things go wrong?

### 3.3 Research Quality Trends

Individual research documents carry quality scores. The observability system aggregates these over time — tracking average quality, validation pass rates, cache hit rates, and quality broken down by topic.

This reveals whether the system is improving, whether certain topics consistently produce poor results, and whether the cache is providing value.

**Key questions answered:**
- Is research quality improving or degrading over time?
- Which topics have consistently poor results?
- Is the cache system working (hit rate)?

### 3.4 Tool Execution Stats

Every tool call is tracked: which tool, duration, success or failure, error type. For internet.research specifically, site-level data is captured — which sites were attempted, which succeeded, which blocked the request.

Aggregated stats reveal tool reliability, tail latency, error patterns, and site-level block rates.

**Key questions answered:**
- Which tools are unreliable?
- Which sites are frequently blocking requests?
- Are tool failure rates increasing?

### 3.5 Confidence Calibration

The system tracks predicted confidence scores against actual outcomes. Over time, this reveals whether confidence estimates are accurate or systematically biased.

When the system predicts 85% confidence but actual accuracy is only 70%, that's overconfidence — the calibration system detects this and suggests adjustments. Calibration is tracked per content type (prices may be miscalibrated differently than product specs).

The key metric is Expected Calibration Error (ECE) — a single number representing how well predicted confidence matches reality. Lower is better. The system suggests temperature scaling adjustments when miscalibration is detected.

**Key questions answered:**
- Are we systematically overconfident or underconfident?
- Which content types are miscalibrated?
- What temperature scaling would correct the calibration?

---

## 4. Storage Model

### Per-Turn

Each turn produces a metrics record stored alongside its context.md. This record contains the complete timing breakdown, decision trail, tool execution details, quality scores, and confidence predictions for that turn.

This is the debugging layer — when a specific turn fails, its metrics record tells the full story.

### Daily Aggregation

At the end of each day, per-turn metrics are rolled up into a daily summary: average durations, validation outcome rates, tool success rates, quality averages, cache hit rates, and calibration metrics.

This is the trends layer — it answers "is the system getting better?" without needing to inspect individual turns.

### Trend Database

Daily aggregations feed a trend database for historical queries: quality over the last 30 days, tool reliability over the last week, calibration drift over time. This enables the system to detect gradual degradation that wouldn't be visible in any single turn.

---

## 5. Self-Improvement Loop

Observability data feeds back into the system:

- **Calibration adjustments** refine confidence scores, improving cache reuse decisions and validation thresholds
- **Tool reliability data** informs the Coordinator's tool selection — avoid tools or sites with high failure rates
- **Quality trends by topic** help the Planner decide when cached research is likely sufficient vs when fresh research is needed
- **Decision trail patterns** from failed turns help identify systematic prompt or context issues

The system doesn't just report metrics — it uses them to get better.

---

## 6. Related Documents

- Confidence system: `architecture/concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md`
- Document IO: `architecture/concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md`
- Phase specs: `architecture/main-system-patterns/phase7-validation.md`, `phase8-save.md`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-28 | Initial specification |
| 2.0 | 2026-02-03 | Distilled to pure concept. Removed Python dataclasses, SQL schemas, JSON examples, implementation code, file paths, and debugging bash commands. Added self-improvement loop. |

---

**Last Updated:** 2026-02-03
