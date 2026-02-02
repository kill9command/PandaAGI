# Phase 6: Validation

**Status:** SPECIFICATION
**Version:** 1.3
**Created:** 2026-01-04
**Updated:** 2026-01-06
**Layer:** MIND role (MIND model @ temp=0.5)

---

## 1. Overview

Phase 6 is the quality gate that ensures response accuracy before delivery to the user. The Validation phase answers the question: **"Is this response accurate and complete?"**

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
| context.md | §0-§5 | Full pipeline context |
| response.md | Complete | Draft response to validate |

**Section Roles:**
- **§0 (User Query):** Ground truth for "query addressed" check
- **§1 (Reflection Decision):** Classification decision (PROCEED/CLARIFY)
- **§2 (Gathered Context):** Valid evidence source for claims
- **§4 (Tool Execution):** Primary evidence source for claims
- **§5 (Synthesis):** The draft being validated

### Outputs

| Document | Section | Content |
|----------|---------|---------|
| context.md | §6 | Validation Result |

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
- Claims from research link to §4 tool results
- Claims from memory link to §2 gathered context
- No "floating" claims without source

**Fail Examples:**
- Response says "$599" but §4 shows "$699"
- Response claims "fastest delivery" with no source
- Response includes specs not found in any research

### 4.2 No Hallucinations

**Question:** Is there any invented information not present in the context?

**Pass Criteria:**
- All product names exist in §4 research
- All URLs were returned by tools
- All features mentioned were found in sources
- No "reasonable assumptions" added

**Fail Examples:**
- Response adds a product not found in research
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
- §0 asks for laptops, response discusses desktops
- §0 asks for "under $800," cheapest shown is $899
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

---

## 5. Decision Logic

### Decision Table

**Canonical Source:** See `architecture/main-system-patterns/UNIVERSAL_CONFIDENCE_SYSTEM.md` for threshold definitions.

| Decision | Confidence Range | Checks Status | Action |
|----------|-----------------|---------------|--------|
| **APPROVE** | >= 0.80 | All 4 pass | Send to user, proceed to Phase 7 (Save) |
| **REVISE** | 0.50 - 0.79 | Minor issues in format or wording | Loop to Phase 5 (Synthesis) with hints |
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
  - Need different tools called
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
    "coherent_format": true | false
  },
  "revision_hints": "Specific guidance for Synthesis if REVISE",
  "suggested_fixes": "Specific guidance for Planner if RETRY"
}
```

**Field Descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `decision` | enum | One of: APPROVE, REVISE, RETRY, FAIL |
| `confidence` | float | 0.0-1.0 score for response quality |
| `issues` | array | Empty if APPROVE, else specific problems |
| `checks` | object | Boolean result for each validation check |
| `revision_hints` | string | Null unless decision is REVISE |
| `suggested_fixes` | string | Null unless decision is RETRY |

---

## 7. Loop Flows

### 7.1 REVISE Loop (to Synthesis)

```
┌─────────────────────────────────────────────────────────────┐
│                      REVISE LOOP                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Phase 5: Synthesis                                         │
│       │                                                     │
│       ▼                                                     │
│  response.md (draft)                                        │
│       │                                                     │
│       ▼                                                     │
│  Phase 6: Validation ───► confidence 0.5-0.8                │
│       │                    issues: ["missing citation"]     │
│       │                    revision_hints: "Add source      │
│       │                    for price claim in paragraph 2"  │
│       │                                                     │
│       ▼ REVISE                                              │
│  ┌─────────────┐                                            │
│  │ Append to   │                                            │
│  │ context.md: │                                            │
│  │ §6.revise_1 │                                            │
│  └─────────────┘                                            │
│       │                                                     │
│       ▼                                                     │
│  Phase 5: Synthesis (attempt 2)                             │
│  [Receives original input + revision_hints]                 │
│       │                                                     │
│       ▼                                                     │
│  Phase 6: Validation                                        │
│       │                                                     │
│       ├── APPROVE ──────────────────► Phase 7 (Save)        │
│       │                                                     │
│       ├── REVISE (attempt 2) ───────► Phase 5               │
│       │                                                     │
│       └── REVISE (attempt 3) ───────► FAIL (max exceeded)   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**REVISE Limit:** Maximum 2 attempts

After 2 failed REVISE attempts, the validator MUST issue FAIL.

### 7.2 RETRY Loop (to Planner)

```
┌─────────────────────────────────────────────────────────────┐
│                       RETRY LOOP                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Phase 3: Planner                                           │
│       │                                                     │
│       ▼                                                     │
│  Phase 4: Coordinator                                       │
│       │                                                     │
│       ▼                                                     │
│  Phase 5: Synthesis                                         │
│       │                                                     │
│       ▼                                                     │
│  Phase 6: Validation ───► confidence < 0.5                  │
│       │                    issues: ["researched wrong       │
│       │                    product category"]               │
│       │                    suggested_fixes: "Query asks     │
│       │                    for laptops, research returned   │
│       │                    only desktops. Re-plan with      │
│       │                    correct product type."           │
│       │                                                     │
│       ▼ RETRY                                               │
│  ┌─────────────┐                                            │
│  │ Append to   │                                            │
│  │ context.md: │                                            │
│  │ §6.retry_1  │                                            │
│  └─────────────┘                                            │
│       │                                                     │
│       ▼                                                     │
│  Phase 3: Planner (attempt 2)                               │
│  [Receives original input + suggested_fixes]                │
│       │                                                     │
│       ▼                                                     │
│  Phase 4 → Phase 5 → Phase 6                                │
│       │                                                     │
│       ├── APPROVE ──────────────────► Phase 7 (Save)        │
│       │                                                     │
│       └── RETRY (attempt 2) ────────► FAIL (max exceeded)   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**RETRY Limit:** Maximum 1 attempt

After 1 failed RETRY attempt, the validator MUST issue FAIL.

**§4 Handling on RETRY:** New tool results are **appended** to §4 (not replaced). This preserves the history of what was tried. If context.md exceeds token limits, NERVES performs smart summarization to compress older §4 attempts while preserving recent results.

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

When a query has multiple goals (detected by Phase 3 Planner), each goal is validated independently. The final decision uses this matrix:

### 8.1 Per-Goal Scoring

| Score Range | Goal Status |
|-------------|-------------|
| ≥ 0.75 | PASS |
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

### 8.3 Weighted Scoring (Optional)

If goals have different priorities (from Planner §3):

```yaml
goals:
  - id: find_price
    priority: high      # weight: 1.5
    score: 0.82
  - id: compare_specs
    priority: medium    # weight: 1.0
    score: 0.45

weighted_average = (0.82 * 1.5 + 0.45 * 1.0) / (1.5 + 1.0) = 0.67
```

### 8.4 Edge Cases

| Case | Score | Decision |
|------|-------|----------|
| Single goal at exactly 0.50 | PARTIAL | APPROVE (partial) with caveat |
| Two goals: 0.90 and 0.49 | PASS + FAIL | REVISE - address failed goal |
| Three goals: 0.80, 0.60, 0.55 | PASS + PARTIAL + PARTIAL | APPROVE (partial) |
| One goal 0.95, one goal 0.30 | PASS + FAIL | REVISE - critical failure on one goal |

### 8.5 Partial Success Response

When APPROVE (partial) is issued, the response should explicitly acknowledge incomplete goals:

```markdown
I found X for your first request (gaming laptops under $1500).

However, I could not find reliable information for your second request
(compatible accessories). Would you like me to search again with different terms?
```

---

## 9. context.md Section 6 Format

### 9.1 APPROVE Output

```markdown
## 6. Validation

**Decision:** APPROVE
**Confidence:** 0.92

### Checks
| Check | Result |
|-------|--------|
| Claims Supported | PASS |
| No Hallucinations | PASS |
| Query Addressed | PASS |
| Coherent Format | PASS |

### Issues
None

### Notes
Response accurately reflects research findings with proper citations.
```

### 9.2 REVISE Output

```markdown
## 6. Validation (Attempt 1)

**Decision:** REVISE
**Confidence:** 0.65

### Checks
| Check | Result |
|-------|--------|
| Claims Supported | FAIL |
| No Hallucinations | PASS |
| Query Addressed | PASS |
| Coherent Format | PASS |

### Issues
1. Price claim "$599 at Best Buy" has no source in §4
2. "Free shipping" mentioned but not in research results

### Revision Hints
Add source citations for price claims. Remove or verify the shipping claim
against §4 tool results. The Lenovo price in §4 shows $697, not $599.
```

### 9.3 RETRY Output

```markdown
## 6. Validation (Attempt 1)

**Decision:** RETRY
**Confidence:** 0.32

### Checks
| Check | Result |
|-------|--------|
| Claims Supported | FAIL |
| No Hallucinations | FAIL |
| Query Addressed | FAIL |
| Coherent Format | PASS |

### Issues
1. Query asked for "gaming laptops under $800"
2. Research in §4 returned only desktop computers
3. Cannot synthesize correct answer without laptop data

### Suggested Fixes
Re-plan research with correct product type: "gaming laptops" not "gaming
computers." The internet.research tool should search for laptops specifically.
Ensure price filter is applied in research phase.
```

### 9.4 FAIL Output

```markdown
## 6. Validation (Final)

**Decision:** FAIL
**Confidence:** 0.15

### Checks
| Check | Result |
|-------|--------|
| Claims Supported | FAIL |
| No Hallucinations | FAIL |
| Query Addressed | FAIL |
| Coherent Format | FAIL |

### Issues
1. Maximum RETRY attempts (1) exceeded
2. Research continues to return wrong product category
3. Unable to gather valid data for this query

### Error Message
I apologize, but I was unable to find accurate information about gaming
laptops under $800. My research attempts returned incorrect results.
Please try rephrasing your query or asking again later.
```

---

## 10. Decision Examples

### Example 1: APPROVE

**Scenario:** User asked for "cheapest laptop with nvidia gpu"

**Response includes:**
- Lenovo LOQ at $697 (matches §4 exactly)
- Link to Best Buy (URL from §4)
- RTX 4050 specs (from §4 research)
- Price comparison table with sources

**Validation Result:**
```json
{
  "decision": "APPROVE",
  "confidence": 0.94,
  "issues": [],
  "checks": {
    "claims_supported": true,
    "no_hallucinations": true,
    "query_addressed": true,
    "coherent_format": true
  },
  "revision_hints": null,
  "suggested_fixes": null
}
```

### Example 2: REVISE

**Scenario:** User asked for laptop recommendations

**Response issues:**
- Good content but URLs are raw text, not markdown links
- Missing citation for one price claim

**Validation Result:**
```json
{
  "decision": "REVISE",
  "confidence": 0.68,
  "issues": [
    "URLs not formatted as markdown links",
    "Price $749 mentioned without source reference"
  ],
  "checks": {
    "claims_supported": false,
    "no_hallucinations": true,
    "query_addressed": true,
    "coherent_format": false
  },
  "revision_hints": "Convert all URLs to markdown link format [text](url). Add source citation for the $749 price claim - verify against §4 tool results.",
  "suggested_fixes": null
}
```

### Example 3: RETRY

**Scenario:** User asked for "best coffee makers under $50"

**Response issues:**
- §4 contains research about coffee beans, not coffee makers
- Wrong product category was researched

**Validation Result:**
```json
{
  "decision": "RETRY",
  "confidence": 0.22,
  "issues": [
    "Research returned coffee beans, not coffee makers",
    "No valid coffee maker data in §4",
    "Cannot answer query with current research"
  ],
  "checks": {
    "claims_supported": false,
    "no_hallucinations": true,
    "query_addressed": false,
    "coherent_format": true
  },
  "revision_hints": null,
  "suggested_fixes": "Re-plan research to search for 'coffee makers' or 'coffee machines' instead of 'coffee'. Ensure product category is correct before executing research."
}
```

### Example 4: FAIL

**Scenario:** After 2 REVISE attempts, response still has hallucinated content

**Validation Result:**
```json
{
  "decision": "FAIL",
  "confidence": 0.25,
  "issues": [
    "Maximum REVISE attempts (2) exceeded",
    "Response continues to include product not in §4",
    "Synthesis unable to produce grounded response"
  ],
  "checks": {
    "claims_supported": false,
    "no_hallucinations": false,
    "query_addressed": true,
    "coherent_format": true
  },
  "revision_hints": null,
  "suggested_fixes": null
}
```

---

## 11. Validation Rules

### 11.1 Evidence Linking

When checking `claims_supported`, the validator must:
1. Extract each factual claim from response.md
2. Search §4 and §2 for supporting evidence
3. Mark claim as supported only if evidence exists
4. Single unsupported claim = `claims_supported: false`

### 11.2 Hallucination Detection

The validator MUST NOT:
- Accept "reasonable inferences"
- Allow "common knowledge" claims without sources
- Permit extrapolation beyond source data

If it is not explicitly in §4 or §2, it is a hallucination.

### 11.3 Loop Control

**Important:** The Validation phase only outputs a decision (APPROVE/REVISE/RETRY/FAIL). The **Orchestrator** is responsible for:
- Tracking attempt counts (revise_count, retry_count)
- Enforcing loop limits (max 2 REVISE, max 1 RETRY)
- Routing to the appropriate phase based on the decision
- Converting RETRY/REVISE to FAIL when limits exceeded

Validation does not track state across attempts - it evaluates each response independently.

---

## 12. Related Documents

- `architecture/LLM-ROLES/llm-roles-reference.md` - Model layer assignments
- `architecture/main-system-patterns/phase3-planner.md` - Phase 3 (RETRY target)
- `architecture/main-system-patterns/phase5-synthesis.md` - Phase 5 (REVISE target)
- `architecture/main-system-patterns/phase7-save.md` - Phase 7 (on APPROVE)
- `architecture/main-system-patterns/PLANNER_COORDINATOR_LOOP.md` - Orchestrator loop control
- `architecture/main-system-patterns/UNIVERSAL_CONFIDENCE_SYSTEM.md` - Quality thresholds
- `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` - context.md format

---

## 13. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 1.1 | 2026-01-05 | Added §4 append behavior on RETRY, clarified Orchestrator owns loop control, removed implementation code |
| 1.2 | 2026-01-05 | Fixed Related Documents paths, added PLANNER_COORDINATOR_LOOP and UNIVERSAL_CONFIDENCE_SYSTEM references |
| 1.3 | 2026-01-05 | Added Multi-Goal Validation Decision Matrix (section 8) with per-goal scoring thresholds and aggregate decision rules |

---

**Last Updated:** 2026-01-05
