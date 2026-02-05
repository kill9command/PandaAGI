# Injection System

**Version:** 2.0
**Updated:** 2026-02-03

---

## 1. Overview

The Injection System allows users to send messages **while a turn is processing**. This enables:

- **Cancellation** — stop processing and return partial results
- **Guidance** — adjust behavior mid-operation (e.g., "focus on X")
- **Redirection** — change what the system is doing

This works at the **Gateway level**, affecting all phases.

---

## 2. Core Concept

In normal flow, a user message starts a turn and the system processes to completion. With injection, messages sent during an active turn are treated as mid-turn instructions rather than new turns.

```
Normal:     User Message → New Turn → Process → Response
Injection:  User Message → New Turn → Processing...
                                         │
                                         ├── User sends "cancel" → Abort, return partial
                                         └── User sends guidance → Adjust, continue
```

The Gateway maintains injection state per session. When a message arrives and a turn is already active, it's routed to the injection queue instead of starting a new turn.

---

## 3. Checkpoints

Every phase checks for pending injections at key points — typically before each LLM call or tool execution.

| Phase | Checkpoint Locations |
|-------|---------------------|
| 0 Query Analyzer | Before classification |
| 1 Reflection | Before LLM call |
| 2 Context Gatherer | Before LLM call |
| 3 Planner | Before LLM call |
| 4 Executor | Before each iteration |
| 5 Coordinator | Before each tool execution |
| 6 Synthesis | Before LLM call |
| 7 Validation | Before LLM call |

At each checkpoint, the system:
1. Checks for cancellation — if found, abort and return partial results
2. Checks for pending guidance messages — if found, process adjustments and continue

---

## 4. Cancellation

When a user sends a cancellation message ("cancel", "stop", "nevermind", etc.):

- The next checkpoint detects the cancellation flag
- Current tool execution completes (no mid-tool interruption)
- All accumulated §4 results are preserved
- If early phases (0–3): return "Cancelled. What would you like to do instead?"
- If mid-execution (4–5): skip to Synthesis with partial §4, generate response from available results
- If during synthesis (6): return results gathered so far
- Validation is skipped; response is marked as partial

---

## 5. Guidance

Users can send guidance messages to adjust behavior without cancelling:

| Pattern | Effect | Applicable Phases |
|---------|--------|-------------------|
| `focus on [X]` | Prioritize X in search/planning | Planner, Coordinator |
| `skip [vendor]` | Don't visit this vendor | Coordinator |
| `also check [site]` | Add source to search list | Coordinator |
| `ignore [criteria]` | Remove a filter or constraint | Planner |
| `prefer [X]` | Weight results toward X | Planner, Synthesis |
| Free-form text | Passed as guidance to current phase | All |

Guidance messages are queued and consumed at the next checkpoint. Multiple rapid messages are all processed together.

---

## 6. Injection During Execution Loop

The Executor–Coordinator loop runs multiple iterations. Injections interact with this loop in three ways:

| Type | Behavior | §4 Preserved | Loop Continues | Iteration Reset |
|------|----------|-------------|----------------|-----------------|
| **CANCEL** | Halt loop, skip to Synthesis with partial results | Yes | No | N/A |
| **REDIRECT** | Complete current tool, inject message as priority context for next Executor iteration | Yes | Yes | No |
| **ADD_CONTEXT** | Append to §2 as user-added context, continue current iteration | Yes | Yes | No |

For redirects, the Executor sees the injected message on its next iteration and adjusts strategy accordingly. The iteration count does not reset.

---

## 7. Edge Cases

- **Rapid multiple injections** — all queued and processed together at next checkpoint
- **Injection after completion** — if turn finishes between message send and injection processing, treat as new turn
- **Injection during long waits** — checkpoints fire periodically during extended operations (e.g., waiting for external responses)

---

## 8. Thread Safety

The injection manager must be thread-safe — the request handler writes injections while the processing task reads them. Session state is always cleaned up when a turn completes, whether by success, cancellation, or error.

---

## 9. Related Documents

- `architecture/concepts/system_loops/EXECUTION_SYSTEM.md` — Execution loop that injections interact with
- `architecture/main-system-patterns/phase3-planner.md` — Planner checkpoint integration
- `architecture/main-system-patterns/phase5-coordinator.md` — Coordinator checkpoint integration
- `architecture/concepts/error_and_improvement_system/ERROR_HANDLING.md` — How injection interacts with error handling

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-29 | Initial specification |
| 1.1 | 2026-01-05 | Added Related Documents and Changelog sections |
| 2.0 | 2026-02-03 | Distilled to pure concept. Removed all Python code (~400 lines), UI mockups, edge case implementations, and stale 2-tier terminology. Updated phase references for 3-tier architecture. |

---

**Last Updated:** 2026-02-03
