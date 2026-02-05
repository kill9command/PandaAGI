# Phase 2.5: Context Gathering Validator

**Status:** SPECIFICATION
**Version:** 1.3
**Created:** 2026-02-04
**Updated:** 2026-02-04
**Layer:** REFLEX role (MIND model @ temp=0.4)
**Token Budget:** ~1,000 total

**Related Concepts:** See §11 (Concept Alignment)

---

## 1. Overview

Phase 2.5 is a **validation helper** that runs after Phase 2.2 (Context Gatherer Synthesis). It verifies that gathered context is complete, constraint-aware, and clear enough for planning. This sub-phase prevents downstream planning from proceeding with missing or contradictory context.

**Core Question:** "Is the gathered context sufficient to plan?"

**Primary goals:**
- Confirm required constraints were captured (budget, must-have, disqualifiers)
- Identify missing key data that would block planning
- Trigger clarification only when user input is required

---

## 2. Position in Pipeline

```
Phase 2.2 (Synthesis) ──► Phase 2.5 (Validator) ──► Phase 3 (Planner)
```

**Routing:**
- `pass` → proceed to Phase 3
- `retry` → re-run Phase 2 synthesis with missing-context list
- `clarify` → ask user for missing core constraints

---

## 3. Inputs

| Input | Source | Description |
|-------|--------|-------------|
| GatheredContext | Phase 2.2 | Structured context summary (S2 draft) |
| constraints | Phase 2.2 | Extracted constraint list | 
| raw_query | User | Original user query for requirement grounding |
| QueryAnalysis | Phase 1 | `user_purpose`, `data_requirements` |

---

## 4. Output Schema

```json
{
  "status": "pass | retry | clarify",
  "issues": ["string"],
  "missing_context": ["string"],
  "retry_guidance": ["string"],
  "clarification_question": "string | null"
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `status` | enum | `pass` if context is sufficient; `retry` if context is incomplete but derivable; `clarify` if user input is required |
| `issues` | array | Human-readable validation issues |
| `missing_context` | array | Concrete missing elements (e.g., "max budget", "required GPU model") |
| `retry_guidance` | array | Concrete instructions for Phase 2 to fix issues on retry (required when status is `retry`) |
| `clarification_question` | string | Required only when status is `clarify` |

---

## 5. Validation Rules

### 5.1 Pass Conditions

Return `pass` if:
- Constraints extracted match query intent
- GatheredContext includes relevant prior turns/memory when indicated by QueryAnalysis
- Cached research or visit data is present when explicitly referenced
- No conflicting signals in constraints or gathered context

### 5.2 Retry Conditions

Return `retry` if:
- Constraints are missing but derivable from existing documents
- Visit data referenced in context is missing or incomplete
- GatheredContext lacks a required section (preferences/prior turns/cached research) but data is available
- `_meta` is missing for sections that include memory nodes
- `node_ids` in `_meta` do not exist in the Unified Memory Index
- `confidence_avg` does not match the Universal Confidence System rule (use weighted mean of `current` confidence when available, otherwise simple average)
- Canonical section titles are missing when nodes are present (`Session Preferences`, `Relevant Prior Turns`, `Cached Research`, `Visit Data`, `Constraints`)

**Retry requirement:** when `status=retry`, populate `retry_guidance` with explicit fix instructions (e.g., “include visit_data for cited URL”, “extract budget constraint from turn 811”).

### 5.4 Memory Integrity + Confidence Downgrade Policy

When invalid or broken memory nodes are detected, Phase 2.5 should:

1. **Fail fast on structural breaks:** If `node_id` does not exist or `source_ref` cannot be loaded, return `retry` (do not proceed).
2. **Safe downgrade on verified staleness/conflict:** If a node exists but is **provably stale or contradictory** (e.g., conflicts with newer sources loaded in this turn), reduce its confidence **once** by a capped delta (e.g., `-0.10`) and never below the Universal Confidence floor for its content type.
3. **No downgrade on uncertainty:** If the validator cannot verify staleness/conflict, do **not** downgrade. Return `retry` or `clarify` instead.

This prevents accidental global downgrades while still letting the system learn from verified bad memory.

### 5.3 Clarify Conditions

Return `clarify` only when the user must provide information:
- Missing core constraint (budget, location, must-have) that cannot be inferred
- Query intent ambiguous after context load
- Conflicting user constraints that require disambiguation

**Key Principle:** default to `retry` when missing data is retrievable without user input.

---

## 6. Token Budget

| Component | Tokens | Notes |
|-----------|--------|-------|
| System prompt | 250 | Validation rules |
| GatheredContext summary | 500 | Compact form only |
| QueryAnalysis | 150 | Intent grounding |
| Output | 100 | Validation object |
| **Total** | **~1,000** | |

---

## 7. Integration Notes

- Phase 2.5 runs after Phase 2.2 SYNTHESIS but before committing final §2 to `context.md`.
- If `retry`, Phase 2 should re-run SYNTHESIS once with `missing_context` **and** `retry_guidance`.
- If `clarify`, the clarification question is returned to the user and the pipeline ends.
- Phase 3 should consume §2 only when Phase 2.5 status is `pass`.

---

## 8. Error Handling

All parse failures or schema violations HALT and create interventions. No silent fallbacks.

---

## 9. Observability

Track:
- pass/retry/clarify rates
- top missing_context categories
- correlation between `data_requirements` and validation failures

---

## 10. Related Documents

- `architecture/main-system-patterns/phase2.2-context-gathering-synthesis.md` - Context synthesis spec
- `architecture/main-system-patterns/phase3-planner.md` - Downstream planner
- `architecture/main-system-patterns/phase1-query-analyzer.md` - Upstream query analysis
- `architecture/concepts/recipe_system/RECIPE_SYSTEM.md` - Recipe execution rules
- `architecture/concepts/error_and_improvement_system/ERROR_HANDLING.md` - Fail-fast rules

---

## 11. Concept Alignment

| Concept | Document | Alignment |
|---------|----------|-----------|
| **Recipe System** | `concepts/recipe_system/RECIPE_SYSTEM.md` | Validator runs via a recipe or sub-recipe with structured output. |
| **Document IO** | `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | Writes optional `_meta` validation block in §2. |
| **Confidence System** | `concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` | Validation quality is a confidence signal for downstream planning. |
| **Error Handling** | `concepts/error_and_improvement_system/ERROR_HANDLING.md` | Fail-fast on invalid output or parse failures. |

---

## 12. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-04 | Initial Phase 2.5 validator specification |
| 1.1 | 2026-02-04 | Clarified Phase 2.2 dependency for validation placement. |
| 1.2 | 2026-02-04 | Added validation rules for `_meta`, node_ids, and confidence_avg. |
| 1.3 | 2026-02-04 | Added section-title checks and memory integrity/downgrade policy. |

---

**Last Updated:** 2026-02-04
