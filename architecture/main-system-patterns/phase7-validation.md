# Phase 7: Validation

**Status:** SPECIFICATION
**Version:** 2.2
**Created:** 2026-01-04
**Updated:** 2026-02-04
**Layer:** MIND role (Qwen3-Coder-30B-AWQ @ temp=0.6)

**Related Concepts:** See §12 (Concept Alignment)

---

## 1. Overview

Phase 7 is the quality gate that ensures response accuracy before delivery to the user. The Validation phase answers the question: **"Is this response accurate and complete?"**

This phase acts as the final checkpoint in the pipeline, verifying that the Synthesis output (response.md) is grounded in evidence, addresses the user's query, and maintains coherent formatting.

**Key Responsibilities:**
- Verify all claims have supporting evidence
- Detect and reject hallucinated content
- Confirm the response addresses the original query
- Ensure formatting quality and readability
- Route to appropriate recovery action if issues found

---

## 2. Inputs and Outputs

### Inputs

| Document | Sections | Purpose |
|----------|----------|---------|
| context.md | §0-§6 | Full pipeline context |
| response.md | Complete | Draft response to validate |

**Section Roles:**
- **§0 (User Query):** Ground truth for "query addressed" check
- **§1 (Query Analysis Validation):** Validation status and reasoning
- **§2 (Gathered Context):** Valid evidence source for claims
- **§4 (Execution Progress):** Primary evidence source for claims (workflow results)
- **§6 (Synthesis):** The draft being validated

### Outputs

| Document | Section | Content |
|----------|---------|---------|
| context.md | §7 | Validation Result |

---

## 3. Token Budget

| Component | Tokens |
|-----------|--------|
| **Total** | ~6,000 |
| Prompt | 1,500 |
| Input | 4,000 |
| Output | 500 |

**Note:** The output is intentionally small (~500 tokens) because validation produces structured decisions, not verbose content.

---

## 4. Validation Checks

The validator performs four mandatory checks:

### 4.1 Claims Supported

**Question:** Does every factual claim in the response have evidence in §4 or §2?

**Pass Criteria:**
- Each price, spec, or factual statement traces to a source
- Claims from research link to §4 workflow results
- Claims from memory link to §2 gathered context
- No "floating" claims without source

**Fail Examples:**
- Response says "<$price>" but §4 shows a different price
- Response claims "<superlative>" with no source
- Response includes specs not found in any research

### 4.2 No Hallucinations

**Question:** Is there any invented information not present in the context?

**Pass Criteria:**
- All item names exist in §4 workflow results
- All URLs were returned by workflows
- All features mentioned were found in sources
- No "reasonable assumptions" added

**Fail Examples:**
- Response adds an item not found in workflow results
- Response invents a "usually" or "typically" claim
- Response includes features not mentioned in sources

### 4.3 Query Addressed

**Question:** Does the response answer what §0 asked?

**Pass Criteria:**
- Core question from §0 has explicit answer
- If §0 asked for "cheapest," response shows price comparison
- If §0 asked for "best," response shows ranking rationale
- Follow-up questions (if any) relate to the topic

**Fail Examples:**
- §0 asks for <item_type A>, response discusses <item_type B>
- §0 asks for "under <$budget>," cheapest shown is above budget
- Response answers a different interpretation of query

### 4.4 Coherent Format

**Question:** Is the response well-structured and readable?

**Pass Criteria:**
- Logical organization (headers, lists where appropriate)
- URLs are clickable markdown links
- No broken formatting or markdown errors
- Appropriate length (not truncated, not padded)

**Fail Examples:**
- Raw URLs instead of markdown links
- Unbalanced markdown (unclosed bold, broken tables)
- Wall of text with no structure
- Abruptly ends mid-sentence

### 4.5 Source Metadata Present

**Question:** Do claims that require sources include `url` or `source_ref`?

**Pass Criteria:**
- Each claim that should have a source includes `url` or `source_ref`
- If a claim lacks source metadata, it is not presented as fact

**Fail Examples:**
- Response includes a price without a URL
- Response cites a source but no corresponding `source_ref` exists

---

## 5. Decision Logic

### Decision Table

**Canonical Source:** See `architecture/concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` for threshold definitions.

| Decision | Confidence Range | Checks Status | Action |
|----------|-----------------|---------------|--------|
| **APPROVE** | >= 0.80 | All 5 pass | Send to user, proceed to Phase 8 (Save) |
| **REVISE** | 0.50 - 0.79 | Minor issues in format or wording | Loop to Phase 6 (Synthesis) with hints |
| **RETRY** | 0.30 - 0.49 | Wrong approach or missing data | Loop to Phase 3 (Planner) with fixes |
| **FAIL** | < 0.30 | Unrecoverable error or loop limits exceeded | Send error message to user |

### REVISE vs RETRY Decision Guide

```
Is the problem with the RESPONSE or the APPROACH?

RESPONSE problems (→ REVISE):
  - Formatting issues
  - Missing citations
  - Unclear wording
  - Incomplete answer (data exists, not presented)
  - Minor claim phrasing issues

APPROACH problems (→ RETRY):
  - Wrong research was done
  - Missing critical data (not gathered)
  - Misunderstood the query
  - Need different workflows called
  - Fundamental gap in evidence
```

---

## 6. Output Schema

```json
{
  "decision": "APPROVE | REVISE | RETRY | FAIL",
  "confidence": 0.0-1.0,
  "issues": ["list of specific problems found"],
  "checks": {
    "claims_supported": true | false,
    "no_hallucinations": true | false,
    "query_addressed": true | false,
    "coherent_format": true | false,
    "source_metadata_present": true | false
  },
  "revision_hints": "Specific guidance for Synthesis if REVISE",
  "suggested_fixes": "Specific guidance for Planner if RETRY"
}
```

---

## 7. Loop Flows

### 7.1 REVISE Loop (to Synthesis)

```
Phase 6: Synthesis
       │
       ▼
response.md (draft)
       │
       ▼
Phase 7: Validation ───► confidence 0.5-0.8
       │                  issues: ["missing citation"]
       │                  revision_hints: "Add source for price claim"
       │
       ▼ REVISE
┌─────────────┐
│ Append to   │
│ context.md: │
│ §7.revise_1 │
└─────────────┘
       │
       ▼
Phase 6: Synthesis (attempt 2)
[Receives original input + revision_hints]
       │
       ▼
Phase 7: Validation
       │
       ├── APPROVE ──────────────────► Phase 8 (Save)
       │
       ├── REVISE (attempt 2) ───────► Phase 6
       │
       └── REVISE (attempt 3) ───────► FAIL (max exceeded)
```

**REVISE Limit:** Maximum 2 attempts

### 7.2 RETRY Loop (to Planner)

```
Phase 7: Validation ───► confidence < 0.5
       │                  issues: ["researched wrong item category"]
       │                  suggested_fixes: "Query asks for <item_type A>, not <item_type B>"
       │
       ▼ RETRY
┌─────────────┐
│ Append to   │
│ context.md: │
│ §7.retry_1  │
└─────────────┘
       │
       ▼
Phase 3: Planner (attempt 2)
[Receives original input + suggested_fixes]
       │
       ▼
Phase 4 → Phase 5 → Phase 6 → Phase 7
       │
       ├── APPROVE ──────────────────► Phase 8 (Save)
       │
       └── RETRY (attempt 2) ────────► FAIL (max exceeded)
```

**RETRY Limit:** Maximum 1 attempt

### 7.3 Combined Loop Limits

```
Per-Turn Maximum Iterations:
├── REVISE: 2 total
├── RETRY: 1 total
└── Combined: 3 total (2 REVISE + 1 RETRY)

Exceeding any limit → FAIL
```

---

## 8. Multi-Goal Validation Decision Matrix

When a query has multiple goals (detected by Phase 3 Planner), each goal is validated independently.

### 8.1 Per-Goal Scoring

| Score Range | Goal Status |
|-------------|-------------|
| >= 0.75 | PASS |
| 0.50 - 0.74 | PARTIAL |
| < 0.50 | FAIL |

### 8.2 Aggregate Decision Matrix

| Scenario | Decision | Action |
|----------|----------|--------|
| All goals PASS | APPROVE | Proceed to user |
| All goals PASS or PARTIAL, none FAIL | APPROVE (partial) | Proceed with caveat noting partial completion |
| Any goal FAIL, others PASS | REVISE | Back to Synthesis, address failed goal specifically |
| Multiple goals FAIL | RETRY | Back to Planner, re-plan approach |
| All goals FAIL | RETRY | Back to Planner with failure context |

---

## 9. context.md Section 7 Format

### 9.1 APPROVE Output

```markdown
## 7. Validation

**Decision:** APPROVE
**Confidence:** 0.92

### Checks
| Check | Result |
|-------|--------|
| Claims Supported | PASS |
| No Hallucinations | PASS |
| Query Addressed | PASS |
| Coherent Format | PASS |
| Source Metadata Present | PASS |

### Issues
None

### Notes
Response accurately reflects research findings with proper citations.
```

### 9.2 REVISE Output

```markdown
## 7. Validation (Attempt 1)

**Decision:** REVISE
**Confidence:** 0.65

### Checks
| Check | Result |
|-------|--------|
| Claims Supported | FAIL |
| No Hallucinations | PASS |
| Query Addressed | PASS |
| Coherent Format | PASS |
| Source Metadata Present | FAIL |

### Issues
1. Price claim "<$price>" has no `url` or `source_ref` in §4
2. "<feature>" mentioned but not in workflow results

### Revision Hints
Add source metadata for price claims. Remove or verify the missing feature
against §4 workflow results. The recorded price in §4 differs from the response.
```

### 9.3 RETRY Output

```markdown
## 7. Validation (Attempt 1)

**Decision:** RETRY
**Confidence:** 0.32

### Checks
| Check | Result |
|-------|--------|
| Claims Supported | FAIL |
| No Hallucinations | FAIL |
| Query Addressed | FAIL |
| Coherent Format | PASS |
| Source Metadata Present | FAIL |

### Issues
1. Query asked for "<item_type A> under <$budget>"
2. Research in §4 returned only <item_type B>
3. Cannot synthesize correct answer without matching data

### Suggested Fixes
Re-plan research with correct item type. The workflow should target
<item_type A> specifically.
```

---

## 10. Validation Rules

### 10.1 Evidence Linking

When checking `claims_supported`, the validator must:
1. Extract each factual claim from response.md
2. Search §4 and §2 for supporting evidence
3. Mark claim as supported only if evidence exists
4. Single unsupported claim = `claims_supported: false`

### 10.2 Hallucination Detection

The validator MUST NOT:
- Accept "reasonable inferences"
- Allow "common knowledge" claims without sources
- Permit extrapolation beyond source data

If it is not explicitly in §4 or §2, it is a hallucination.

### 10.3 Loop Control

**Important:** The Validation phase only outputs a decision (APPROVE/REVISE/RETRY/FAIL). The **Orchestrator** is responsible for:
- Tracking attempt counts (revise_count, retry_count)
- Enforcing loop limits (max 2 REVISE, max 1 RETRY)
- Routing to the appropriate phase based on the decision
- Converting RETRY/REVISE to FAIL when limits exceeded

Validation does not track state across attempts - it evaluates each response independently.

### 10.4 Requirement Compliance

The validator MUST compare the response against the original query in §0:
- Budget requests honored
- Stated preferences reflected
- Requested scope covered
- Output format matches request

Any unmet requirement sets decision to `REVISE` or `RETRY` (based on severity).

---

## 11. Concept Alignment

This section maps Phase 7's responsibilities to the cross-cutting concept documents.

| Concept | Document | Phase 7 Relevance |
|---------|----------|--------------------|
| **Confidence System** | `concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` | The PRIMARY concept relationship. Validation uses confidence thresholds to route decisions: APPROVE ≥ 0.80, REVISE 0.50–0.79, RETRY 0.30–0.49, FAIL < 0.30. Multi-goal validation uses per-goal scoring (§8). |
| **Error Handling** | `concepts/error_and_improvement_system/ERROR_HANDLING.md` | RETRY and FAIL are the pipeline's error recovery mechanisms. FAIL is the terminal error state. Loop limits (max 2 REVISE, max 1 RETRY) are enforced by the Orchestrator, not by Validation itself. |
| **Improvement Extraction** | `concepts/error_and_improvement_system/improvement-principle-extraction.md` | When a REVISE cycle succeeds (REVISE → re-Synthesis → APPROVE), the system extracts what went wrong and what fixed it. This turn-local learning improves future responses. |
| **Execution System** | `concepts/system_loops/EXECUTION_SYSTEM.md` | Validation feeds the loop control system: RETRY → Phase 3 (Planner), REVISE → Phase 6 (Synthesis). The Orchestrator tracks attempt counts and converts to FAIL when limits are exceeded. |
| **Backtracking Policy** | `concepts/self_building_system/BACKTRACKING_POLICY.md` | Validation decisions feed into the backtracking system. RETRY triggers replanning; the backtracking policy determines replan scope (local retry vs partial/full replan). Reason tags in §7 guide the Planner's backtracking level. |
| **Memory Architecture** | `concepts/memory_system/MEMORY_ARCHITECTURE.md` | Memory staging gate: memory candidates are only committed to the store after Validation returns APPROVE. On REVISE, RETRY, or FAIL, candidates are discarded (§7 of Memory Architecture). |
| **Document IO** | `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | Reads §0–§6 (full pipeline context) plus response.md. Writes §7 (Validation Result). §7 accumulates across attempts — each attempt adds a numbered block (Attempt 1, Attempt 2, etc.). |
| **Recipe System** | `concepts/recipe_system/RECIPE_SYSTEM.md` | Executed as a MIND recipe with ~6,000 token budget. Intentionally small output (~500 tokens) because validation produces structured decisions, not verbose content. |
| **LLM Roles** | `LLM-ROLES/llm-roles-reference.md` | Uses the MIND role (temp=0.6) for judgment reasoning. MIND temperature provides balanced evaluation — deterministic enough for consistent quality checks, flexible enough for nuanced judgment. |
| **Prompt Management** | `concepts/recipe_system/PROMPT_MANAGEMENT_SYSTEM.md` | Validation prompt carries §0 (original query) for requirement compliance checking. The four mandatory checks (claims supported, no hallucinations, query addressed, coherent format) are embedded in the prompt. |

---

## 12. Related Documents

- `architecture/LLM-ROLES/llm-roles-reference.md` — Model layer assignments
- `architecture/main-system-patterns/phase3-planner.md` — Phase 3 (RETRY target)
- `architecture/main-system-patterns/phase6-synthesis.md` — Phase 6 (REVISE target)
- `architecture/main-system-patterns/phase8-save.md` — Phase 8 (on APPROVE)
- `architecture/concepts/system_loops/EXECUTION_SYSTEM.md` — Loop control
- `architecture/concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` — Quality thresholds
- `architecture/concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` — context.md format
- `architecture/concepts/self_building_system/BACKTRACKING_POLICY.md` — Replanning policy

---

## 13. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 1.1 | 2026-01-05 | Added §4 append behavior on RETRY, clarified Orchestrator owns loop control |
| 1.2 | 2026-01-05 | Fixed Related Documents paths |
| 1.3 | 2026-01-05 | Added Multi-Goal Validation Decision Matrix |
| 2.0 | 2026-01-24 | **Renumbered from Phase 6 to Phase 7** due to new Executor phase. Updated section numbers (§6→§7). Updated loop targets (Synthesis now Phase 6, Save now Phase 8). |
| 2.1 | 2026-02-03 | Added §11 Concept Alignment. Fixed wrong UNIVERSAL_CONFIDENCE_SYSTEM.md path in decision table and Related Documents. Removed stale Concept Implementation Touchpoints and Benchmark Gaps sections. |
| 2.2 | 2026-02-04 | Updated to Phase 1.5 validation language, workflow terminology, source metadata check, and abstracted examples. |

---

**Last Updated:** 2026-02-04
