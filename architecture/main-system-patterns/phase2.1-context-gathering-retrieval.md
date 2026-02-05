# Phase 2.1: Context Gathering — Retrieval

**Status:** SPECIFICATION  
**Version:** 1.4  
**Created:** 2026-02-04  
**Updated:** 2026-02-04  
**Layer:** MIND role (MIND model @ temp=0.6)  
**Question:** "Which sources are relevant to this query?"

**Related Concepts:** See §9 (Concept Alignment)

---

## 1. Overview

Phase 2.1 is the **retrieval sub-phase** of Context Gathering. It selects which sources should be loaded (turns, memory keys, research cache, visit records) without loading full documents. This keeps the next step efficient and focused.

**Core output:** `RetrievalPlan`

**Precondition:** Phase 2.1 assumes Phase 1.5 already passed; if Phase 2.1 is invoked, the gate has been satisfied.

---

## 2. Position in Pipeline

```
Phase 1 (Query Analyzer) ──► Phase 1.5 (Validator)
                             │
                             ▼
                        Phase 2.1 (Retrieval)
                             │
                             ▼
                     Document Loading (procedural)
                             │
                             ▼
                        Phase 2.2 (Synthesis)
                             │
                             ▼
                        Phase 2.5 (Validation)
                             │
                             ▼
                           Phase 3
```

---

## 3. Inputs

| Input | Source | Description |
|-------|--------|-------------|
| QueryAnalysis (narrative) | Phase 1 | `resolved_query`, `user_purpose`, `reasoning` — primary signals for retrieval |
| QueryAnalysis (hints) | Phase 1 | Optional structured hints (e.g., `data_requirements`, `content_reference`, `reference_resolution`) |
| Unified Memory Index | Memory graph | All retrievable items normalized as memory nodes (see §3.1) |

**Input Principle:** Phase 2.1 prioritizes **quality of narrative signal** over rigid structure. If structured hints are missing or inconsistent, infer the retrieval plan from `resolved_query` and `user_purpose` rather than failing.

### 3.1 Unified Memory Index (Obsidian-Style)

All retrievable inputs are treated as **memory nodes** in a single, linked graph. This lets Phase 2.1 search across **every source** with one retrieval step and then filter by relevance, confidence, and provenance.

| Field | Type | Description |
|-------|------|-------------|
| `node_id` | string | Stable identifier (e.g., `turn:811`, `memory:budget`, `visit:abc123`) |
| `source_type` | enum | `turn_summary`, `preference`, `fact`, `research_cache`, `visit_record` |
| `summary` | string | Short description or preview |
| `confidence` | float | 0.0–1.0 confidence score |
| `timestamp` | string | ISO timestamp or age_hours |
| `source_ref` | string | Path or pointer to full document |
| `links` | array | Linked node_ids (Obsidian-style back/forward links) |

**Retrieval behavior:** Phase 2.1 searches the memory graph for relevant nodes, then returns a RetrievalPlan that lists selected `node_id`s grouped by `source_type`, with a brief relevance reason per group.

---

## 4. Output Schema (RetrievalPlan)

```json
{
  "selected_nodes": {
    "turn_summary": ["node_id", "..."],
    "preference": ["node_id", "..."],
    "fact": ["node_id", "..."],
    "research_cache": ["node_id", "..."],
    "visit_record": ["node_id", "..."]
  },
  "selection_reasons": {
    "turn_summary": "string",
    "preference": "string",
    "fact": "string",
    "research_cache": "string",
    "visit_record": "string"
  },
  "coverage": {
    "has_prior_turns": true | false,
    "has_memory": true | false,
    "has_cached_research": true | false,
    "has_visit_data": true | false
  },
  "reasoning": "short narrative rationale"
}
```

### 4.1 Schema Rules (Pattern-Level)

1. **All keys must exist.** Use empty arrays when nothing is selected.
2. **Only valid `node_id`s.** Every ID must exist in the Unified Memory Index.
3. **Selection reasons required** for any non-empty group. Empty group → `""` or `"none"`.
4. **Coverage is derived** from the `selected_nodes` arrays.
5. **Reasoning is short** (one paragraph max).

---

## 5. Document Loading (Procedural)

Phase 2.1 does **not** load full documents. It returns a RetrievalPlan which the system uses to load:
- `turn_summary` → prior turn `context.md`
- `preference` / `fact` → memory documents
- `research_cache` → cached research documents
- `visit_record` → cached visit records

---

## 6. Error Handling

- **Parse failure / invalid schema** → HALT with intervention  
- **Empty retrieval lists** → valid outcome (new topic), proceed to Phase 2.2 with minimal inputs

---

## 7. Observability

Track:
- Distribution of selected source types (turns vs memory vs cache)
- Average number of sources selected
- RetrievalPlan quality (downstream validation failures correlated)

---

## 8. Related Documents

- `architecture/main-system-patterns/phase2.2-context-gathering-synthesis.md` — Downstream synthesis
- `architecture/main-system-patterns/phase2.5-context-gathering-validator.md` — Validation helper
- `architecture/concepts/memory_system/MEMORY_ARCHITECTURE.md` — Memory and turn index rules

---

## 9. Concept Alignment

| Concept | Document | Alignment |
|---------|----------|-----------|
| **Recipe System** | `concepts/recipe_system/RECIPE_SYSTEM.md` | RetrievalPlan is a structured recipe output with fixed schema. |
| **Document IO** | `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | Uses turn summaries and indexes to decide which documents to load. |
| **Error Handling** | `concepts/error_and_improvement_system/ERROR_HANDLING.md` | Fail-fast on invalid outputs; empty retrieval is not an error. |

---

## 10. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-04 | Initial Phase 2.1 retrieval specification |
| 1.1 | 2026-02-04 | Clarified Phase 1.5 pass as a hard precondition. |
| 1.2 | 2026-02-04 | Prioritized narrative inputs and made structured hints optional. |
| 1.3 | 2026-02-04 | Unified all retrieval inputs into a single memory graph index. |
| 1.4 | 2026-02-04 | Replaced example output with universal RetrievalPlan schema + rules. |

---

**Last Updated:** 2026-02-04
