# Context Compression

**Version:** 1.0
**Updated:** 2026-02-03

---

## 1. Core Principle

**Never blind truncation.** Every time the system needs to reduce content — whether compressing execution results, trimming loaded documents, or archiving old turns — it uses LLM-powered summarization via the NERVES role (temp=0.3). No character limits, no line-count cutoffs, no dropping the tail end of a document.

NERVES is deterministic summarization: it preserves structure and discards filler.

---

## 2. What NERVES Preserves

| Category | Examples |
|----------|----------|
| **Numbers and quantities** | Prices, counts, measurements, scores, percentages |
| **Claims with sources** | "Lenovo LOQ @ $697 (bestbuy.com)" — claim + attribution intact |
| **Structural formats** | Tables, lists, YAML `_meta` blocks, section headers |
| **Evidence links** | Source references (`[1]`, `[2]`), turn numbers, document IDs |
| **Decisions and outcomes** | Tool selected, status (success/error), goal progress |
| **User constraints** | Budget, preferences, must-avoid, freshness requirements |

---

## 3. What NERVES Drops

| Category | Examples |
|----------|----------|
| **Redundant detail** | Multiple paragraphs restating the same finding |
| **Verbose descriptions** | Long product descriptions when key specs suffice |
| **Intermediate state** | Raw HTML fragments, full API responses already extracted |
| **Duplicate claims** | Same fact from multiple sources — keep highest confidence |
| **Boilerplate** | Repeated headers, template text, formatting padding |

---

## 4. Trigger Points

The Orchestrator monitors token usage and triggers NERVES compression at specific points in the pipeline:

| Trigger | Location | Threshold | Action |
|---------|----------|-----------|--------|
| **§4 growth** | Executor-Coordinator loop | §4 exceeds phase token budget | Compress §4 before next Executor iteration |
| **Document loading** | Phase 2 Context Gatherer | Loaded documents exceed SYNTHESIS call budget | Compress loaded documents before SYNTHESIS LLM call |
| **Turn archival** | Phase 8 Save | Turn moves from active to archived (30+ days) | Generate summary for index, move originals to cold storage |
| **Research results** | Phase 5 Coordinator | Tool results exceed result budget | Compress tool output before appending to §4 |

---

## 5. Compression vs Truncation

Some operations use **budget-aware loading** (not NERVES) as a first pass:

| Strategy | When Used | How It Works |
|----------|-----------|--------------|
| **Priority ordering** | Phase 2 document loading | Load Memory > Research Cache > Recent Turns > Older Turns; stop when budget reached |
| **Per-item limits** | Phase 2 turn loading | Max tokens per loaded turn; items beyond limit are not loaded |
| **Top-N selection** | Research cache | Keep summary + top N claims by confidence |

These are **selection** strategies (choose what to load), not compression. They happen before NERVES. If the selected content still exceeds budget after priority-based selection, NERVES compresses it.

```
Step 1: Select what to load (priority ordering, per-item limits)
Step 2: If still over budget → NERVES compression
Step 3: Never → blind truncation
```

---

## 6. Responsibility

| Actor | Role |
|-------|------|
| **Orchestrator** | Monitors token usage across phases, decides when to trigger NERVES |
| **NERVES** | Executes compression (LLM call at temp=0.3 with summarization prompt) |
| **Phase specs** | Define per-phase token budgets that serve as thresholds |
| **Recipe System** | NERVES compression uses its own recipe with output schema constraints |

The Orchestrator is the only component that triggers NERVES. Individual phases do not call NERVES directly — they report their content, and the Orchestrator compresses when needed.

---

## 7. Design Rationale

**Why not just use larger context windows?**
- Single GPU (RTX 3090, 24GB VRAM) constrains model size and context length
- Larger contexts increase latency and cost per call
- Compression forces the system to identify what matters, improving downstream reasoning

**Why LLM summarization instead of algorithmic compression?**
- Algorithmic approaches (TF-IDF, extractive) lose structure and context
- LLM summarization understands which details are relevant to the current query
- NERVES at temp=0.3 is near-deterministic while preserving semantic meaning

**Why not compress earlier?**
- Content should be available in full for the phase that needs it
- Compression happens at phase boundaries, not within phases
- The Orchestrator compresses between iterations, not during them

---

## 8. Related Documents

- `LLM-ROLES/llm-roles-reference.md` — NERVES role definition (temp=0.3)
- `concepts/system_loops/EXECUTION_SYSTEM.md` — Orchestrator triggers compression (§2.1)
- `concepts/recipe_system/RECIPE_SYSTEM.md` — NERVES uses its own compression recipe
- `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` — context.md growth patterns
- `concepts/error_and_improvement_system/ERROR_HANDLING.md` — Token budget exceeded is a HALT condition
- `main-system-patterns/phase2.2-context-gathering-synthesis.md` — Document truncation strategy

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-03 | Initial specification. Merged context_overflow_defense.md and intelligent_summarization.md into unified concept. |

---

**Last Updated:** 2026-02-03
