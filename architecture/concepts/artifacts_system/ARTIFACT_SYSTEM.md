# Artifact System

**Status:** SPECIFICATION
**Version:** 4.0
**Updated:** 2026-02-03

**Related Phases:** P3 (intent), P4-P5 (generation), P6 (response reference), P7 (validation), P8 (persistence)

---

## 1. Purpose

Pandora produces files — not just text responses. When a user needs a report, a comparison table, a summary document, or a presentation, the system generates actual files the user can open, edit, and share.

A useful agent doesn't describe documents. It makes them.

---

## 2. Supported Formats

| Format | Use Case |
|--------|----------|
| **DOCX** | Reports, memos, summaries, analysis write-ups |
| **XLSX** | Comparison tables, data exports, budgets, inventories |
| **PDF** | Read-only reports, formal deliverables |
| **PPTX** | Presentations, briefings, visual summaries |

Each format has a plaintext fallback if its library is unavailable. The system degrades but never fails silently.

---

## 3. When to Generate

The Planner decides whether a task needs file output based on user intent:

| Signal | Artifact |
|--------|----------|
| "make me a spreadsheet", "create a report" | Explicit — generate what they asked for |
| Structured data comparison (products, prices, features) | XLSX |
| Written deliverable (analysis, memo, summary) | DOCX |
| Presentable briefing | PPTX |
| Conversational or informational query | Text response only |

**Rule:** The LLM decides. The Planner's strategic plan includes artifact intent when the user's purpose calls for it. Code never forces or prevents artifact generation.

---

## 4. Pipeline Flow

```
Planner     → Strategic plan includes artifact goal
Executor    → "Generate a comparison spreadsheet from the research data"
Coordinator → Calls artifact generator with structured data from §4
Synthesis   → References artifacts in response: "I've created laptop_comparison.xlsx..."
Validation  → Verifies artifact exists, is non-empty, and response mentions it
Save        → Persists artifacts/ directory and manifest
```

---

## 5. Artifact Manifest

Each turn that produces artifacts writes a manifest alongside them:

```json
{
  "turn_id": "turn_000742",
  "artifacts": [
    {
      "type": "xlsx",
      "filename": "laptop_comparison.xlsx",
      "title": "Laptop Comparison",
      "description": "Price and spec comparison of 5 gaming laptops"
    }
  ]
}
```

---

## 6. Storage

```
turns/turn_{NNNNNN}/
├── artifact_manifest.json
└── artifacts/
    ├── laptop_comparison.xlsx
    └── research_summary.docx
```

---

## 7. Response Integration

Synthesis references artifacts naturally in the user response:

> I've put together a detailed comparison: **laptop_comparison.xlsx**
> It includes prices, GPU specs, battery life, and display info across all 5 options.

Artifacts are deliverables, not appendices. The response tells the user what the file contains and why it's useful.

---

## 8. Validation

| Check | Pass Condition |
|-------|----------------|
| File exists | Artifact path resolves to a real file |
| Non-empty | File size > 0 |
| Format matches | Extension matches declared type |
| Referenced in response | User response mentions the artifact |

Artifact validation failure triggers REVISE (regenerate the artifact), not RETRY (redo the whole plan).

---

## 9. Retrieval

Past artifacts are discoverable in future turns. A user can say "update the spreadsheet from yesterday" and Context Gatherer finds the relevant turn by artifact title and type.

The turn index stores `has_artifacts`, `artifact_types`, and `artifact_titles` for this purpose.

---

## 10. Related Documents

- [`phase3-planner.md`](../../main-system-patterns/phase3-planner.md) — Artifact intent in strategic plan
- [`phase6-synthesis.md`](../../main-system-patterns/phase6-synthesis.md) — Artifact references in response
- [`phase8-save.md`](../../main-system-patterns/phase8-save.md) — Artifact persistence
- [`TOOL_SYSTEM.md`](../tools_workflows_system/TOOL_SYSTEM.md) — Tool families that consume/produce files

---

## 11. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-03 | Initial |
| 2.0 | 2026-02-03 | Merged OUTPUT_ARTIFACTS + ARTIFACT_GENERATION |
| 3.0 | 2026-02-03 | Redesigned as core capability with pipeline flow |
| 4.0 | 2026-02-03 | Distilled to pure concept — removed implementation details |

---

**Last Updated:** 2026-02-03
