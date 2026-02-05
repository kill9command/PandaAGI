# Error Handling Architecture

**Version:** 2.0
**Updated:** 2026-02-03

---

## 1. Philosophy: Fail Fast, Fix Fast

Every error is a bug that needs to be fixed. Silent fallbacks and graceful degradation hide bugs and create compounding problems.

**Wrong:** "If the tool fails, fall back to keyword search."
Result: Silent failures, hidden bugs, bad data, confused debugging.

**Correct:** "If the tool fails, STOP and notify human for investigation."
Result: Every failure is a learning opportunity, bugs get fixed at the root.

---

## 2. Error Response

When something fails, the system:

1. **Logs the full error context** — phase, tool, error, stack trace
2. **Creates an intervention request** — structured record for human review
3. **Halts processing** — don't make things worse
4. **Returns partial results if available** — don't waste what already worked
5. **Tells the user** — honest error message, not a generic fallback

---

## 3. Per-Phase Guardrails

Every phase halts on error and creates an intervention request. The critical rule is what the system must **never** do as a fallback:

| Phase | Never Do This |
|-------|---------------|
| Phase 0 (Query Analyzer) | Fall back to raw query without analysis. Skip reference resolution silently. Default to any action classification without proper analysis. |
| Phase 1 (Reflection) | Default to PROCEED. Skip reflection and move to context gathering. |
| Phase 2 (Context Gatherer) | Fall back to empty context. Use keyword search as fallback. Silently continue with partial data. |
| Phase 3 (Planner) | Use keyword-based tool selection as fallback. Default to any particular tool. |
| Phase 4–5 (Executor + Coordinator) | Continue to next tool after failure. Return partial results without intervention. Silently skip failed tools. |
| Phase 6 (Synthesis) | Format raw claims as fallback response. Return generic "couldn't find" messages. |
| Phase 7 (Validation) | Default to APPROVE. Skip validation entirely. |
| Phase 8 (Save) | *Exception:* Save failures don't halt the user response, but still create an intervention. The user gets their response; persistence issues are investigated separately. |

---

## 4. Intervention System

All errors produce intervention requests — structured records containing the phase, tool, error type, error message, session context, and turn ID. These are queued for human review.

### Priority Levels

| Priority | Type | Examples |
|----------|------|----------|
| **Critical** | System health | LLM service down, database corruption |
| **High** | User-blocking | Permission denied, tool failure, CAPTCHA |
| **Medium** | Quality issues | Schema failure, extraction error |
| **Low** | Informational | Limit exceeded, validation failure |

### Resolution Workflow

1. Human sees the intervention in the monitoring UI
2. Human investigates — checks logs, reproduces, identifies root cause
3. Human fixes — updates code, config, or prompts
4. Human marks resolved with notes
5. User retries their query if appropriate

---

## 5. Loop Limits

Even with fail-fast, the system needs hard limits to prevent infinite loops:

| Mechanism | Limit | On Limit Reached |
|-----------|-------|------------------|
| Executor–Coordinator loop | 5 iterations | Halt + intervention |
| RETRY (Validation → Planner) | 1 | Halt + intervention |
| REVISE (Validation → Synthesis) | 2 | Halt + intervention |
| LLM calls per turn | 25 | Halt + intervention |

---

## 6. Queue Backpressure

The intervention queue has limits to prevent unbounded growth:

| Parameter | Limit | Behavior When Exceeded |
|-----------|-------|----------------------|
| Max queue size | 50 | Write to emergency log instead |
| Max per session | 5 | Merge with existing intervention of same type |
| Max per error type | 10 | Increment occurrence count on existing entry |

When the queue is full, no intervention is lost — overflow goes to an emergency log. But a full queue signals that system health is questionable and needs immediate attention.

---

## 7. Future: Production Mode

Development mode treats all errors as halt-worthy. Production mode will introduce graduated handling:

- **Transient errors** — Retry with backoff (network timeouts, rate limits)
- **Recoverable errors** — Retry then fallback (tool unavailable, try alternative)
- **Permanent errors** — Fail immediately (config missing, permission denied)

Until then: **all errors → halt + intervention.** The development philosophy is that every silent fallback is a bug you'll pay for later.

---

## 8. Design Principles

1. **No silent failures** — Every error creates an intervention
2. **No fallbacks** — Fallbacks hide bugs
3. **Full context** — Log everything needed to reproduce and debug
4. **Human in the loop** — Developer reviews and fixes root causes
5. **Fix the root cause** — Don't patch symptoms

---

## 9. Related Documents

- Observability system: `architecture/concepts/DOCUMENT-IO-SYSTEM/OBSERVABILITY_SYSTEM.md`
- Execution loops: `architecture/concepts/system_loops/EXECUTION_SYSTEM.md`
- Backtracking: `architecture/concepts/backtracking/BACKTRACKING_POLICY.md`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-29 | Initial specification |
| 1.1 | 2026-01-05 | Adapted for 9-phase pipeline |
| 2.0 | 2026-02-03 | Distilled to pure concept. Removed Python code (per-phase try/except blocks, dataclasses, backpressure functions, logging patterns), JSON examples, and file paths. Consolidated per-phase guardrails into table. |

---

**Last Updated:** 2026-02-03
