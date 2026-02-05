# Phase 1.5: Query Analyzer Validator

**Status:** SPECIFICATION
**Version:** 1.3
**Created:** 2026-02-04
**Updated:** 2026-02-04
**Layer:** REFLEX role (MIND model @ temp=0.4)
**Token Budget:** ~300-500 total

**Related Concepts:** See §11 (Concept Alignment)

---

## 1. Overview

Phase 1.5 is a **validation helper** that runs immediately after Phase 1 (Query Analyzer). It checks the QueryAnalysis output for consistency, completeness, and actionable clarity. This is not a standalone pipeline phase; it is a sub-phase invoked within Phase 1 to avoid a separate reflection gate while still catching ambiguity early.

**Core Question:** "Is the QueryAnalysis coherent enough to proceed?"

**Primary goals:**
- Catch contradictions between `resolved_query`, `user_purpose`, `data_requirements`, and `mode`
- Detect missing or malformed required fields
- Trigger clarification only when ambiguity is fundamental

---

## 2. Position in Pipeline

```
Phase 1 (Query Analyzer) ──► Phase 1.5 (Validator) ──► Phase 2.1 (Context Retrieval)
```

**Routing:**
- `pass` → proceed to Phase 2.1
- `retry` → re-run Phase 1 with validator issues appended
- `clarify` → ask the user a focused clarification question

**Pipeline Gate:** If status is `retry` or `clarify`, the pipeline ends here. Phase 2.1 only runs when Phase 1.5 returns `pass`.

---

## 3. Inputs

| Input | Source | Description |
|-------|--------|-------------|
| QueryAnalysis | Phase 1 | Full output from Phase 1 Query Analyzer |
| raw_query | User | Original user query (for ambiguity checks) |

**Note:** Phase 1.5 does not expand context or look up additional data. It only validates the Phase 1 output.

---

## 4. Output Schema

The validator writes a `validation` object that is embedded into the Phase 1 output:

```json
{
  "status": "pass | retry | clarify",
  "confidence": 0.0-1.0,
  "issues": ["string"],
  "retry_guidance": ["string"],
  "clarification_question": "string | null"
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `status` | enum | `pass` if analysis is coherent; `retry` if incomplete/inconsistent; `clarify` if fundamentally ambiguous |
| `confidence` | float | Confidence in the validation decision |
| `issues` | array | Human-readable issues found in the analysis (empty if pass) |
| `retry_guidance` | array | Concrete instructions for Phase 1 to fix issues on retry (required when status is `retry`) |
| `clarification_question` | string | Required only when status is `clarify` |

---

## 5. Validation Rules

### 5.1 Pass Conditions

Return `pass` if all are true:
- `resolved_query`, `user_purpose`, `data_requirements`, `mode` are present
- `mode` is compatible with query signals (e.g., file paths imply `mode=code`)
- `reference_resolution.status` is one of `not_needed | resolved | failed`
- No contradictions between `resolved_query` and `reference_resolution`

### 5.2 Retry Conditions

Return `retry` if:
- Any required field is missing or malformed
- `data_requirements` contradict `user_purpose` (e.g., no live data flagged for an explicitly time-sensitive query)
- `mode` conflicts with obvious query signals (e.g., file paths in query but `mode=chat`) and requires permission
- `reference_resolution.status=failed` but `resolved_query` changed anyway (inconsistent resolution)

**Retry requirement:** when `status=retry`, populate `retry_guidance` with explicit fix instructions (e.g., “set `mode=code` because the query references file paths”, “recompute `data_requirements` based on time-sensitivity in the query”).
### 5.3 Clarify Conditions

Return `clarify` when the user query is **fundamentally ambiguous** or when **permission is required** to switch modes:
- Unresolved references with no prior context ("get me that one")
- Missing core entity ("the cheapest")
- Multiple incompatible interpretations ("book that" → reserve vs read)
- Code task requested while `mode=chat` → ask for permission to switch to code mode

**Key Principle:** default to `pass` when uncertain. Over-clarification is worse than proceeding.

---

## 6. Token Budget

| Component | Tokens | Notes |
|-----------|--------|-------|
| System prompt | 120 | Short validator instructions |
| QueryAnalysis | 150 | Minimal pass-through |
| raw_query | 30 | For ambiguity check |
| Output | 80 | Validation object |
| **Total** | **~380** | |

---

## 7. Integration Notes

- Phase 1.5 runs as a **second pass** within Phase 1 orchestration.
- If `retry`, Phase 1 should re-run once with `issues` **and** `retry_guidance` appended to the prompt.
- If `clarify`, the clarification question is returned to the user and the pipeline ends.

---

## 8. Error Handling

All parse failures or schema violations HALT and create interventions. No silent fallbacks.

---

## 9. Observability

Log:
- validation status distribution (pass/retry/clarify)
- top recurring issues
- correlation between `reference_resolution.status=failed` and `clarify`

---

## 10. Related Documents

- `architecture/main-system-patterns/phase1-query-analyzer.md` - Primary Query Analyzer spec
- `architecture/main-system-patterns/phase2.1-context-gathering-retrieval.md` - Downstream phase
- `architecture/concepts/recipe_system/RECIPE_SYSTEM.md` - Recipe execution rules
- `architecture/concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` - Confidence handling
- `architecture/concepts/error_and_improvement_system/ERROR_HANDLING.md` - Fail-fast rules

---

## 11. Concept Alignment

| Concept | Document | Alignment |
|---------|----------|-----------|
| **Recipe System** | `concepts/recipe_system/RECIPE_SYSTEM.md` | Validator runs via a recipe or sub-recipe, producing a structured `validation` object. |
| **Document IO** | `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | Validation is embedded in §0 output for downstream phases. |
| **Confidence System** | `concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` | `confidence` reflects reliability of the analysis. |
| **Error Handling** | `concepts/error_and_improvement_system/ERROR_HANDLING.md` | Fail-fast on invalid output or parse failures. |

---

## 12. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-04 | Initial Phase 1.5 validator specification |
| 1.1 | 2026-02-04 | Removed Phase 1.2 dependency; validator now runs directly after Phase 1. |
| 1.2 | 2026-02-04 | Updated downstream routing to Phase 2.1. |
| 1.3 | 2026-02-04 | Clarified Phase 1.5 as a hard gate before Phase 2.1. |

---

**Last Updated:** 2026-02-04
