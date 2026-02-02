# Phase 6: Validator

Validate synthesis output before delivery.

**Output:** JSON only. Must start with `{` and end with `}`.

---

## Output Schema

```json
{
  "decision": "APPROVE | REVISE | RETRY | FAIL",
  "confidence": 0.0-1.0,
  "issues": ["[specific problems]"],
  "checks": {
    "claims_supported": true | false,
    "no_hallucinations": true | false,
    "query_addressed": true | false,
    "coherent_format": true | false
  },
  "revision_hints": "[guidance if REVISE]",
  "suggested_fixes": "[guidance if RETRY]"
}
```

---

## Decision Matrix

| Decision | Confidence | Checks | Action |
|----------|------------|--------|--------|
| APPROVE | >= 0.80 | All pass | Send to user |
| REVISE | 0.50-0.79 | Minor issues | Loop to Synthesis |
| RETRY | 0.30-0.49 | Wrong approach | Loop to Planner |
| FAIL | < 0.30 | Unrecoverable | Send error |

---

## Four Checks

### 1. claims_supported

Every factual claim has evidence in §4 or §1?

| Pass | Fail |
|------|------|
| Price traces to source | Response says $[X], §4 shows $[Y] |
| URL from tool results | "Fastest delivery" with no source |

### 2. no_hallucinations

Any invented information?

| Pass | Fail |
|------|------|
| All products in §4 | Product not in research |
| All URLs from tools | Invented URLs |

### 3. query_addressed

Response answers §0 query?

| Pass | Fail |
|------|------|
| Query for [X], response shows [X] | Asked for [X], got [Y] |
| "Cheapest" shows price comparison | "Under $[N]" shows $[N+100] |

### 4. coherent_format

Well-structured and readable?

| Pass | Fail |
|------|------|
| Headers, lists, markdown links | Raw URLs, wall of text |
| Complete sentences | Ends mid-sentence |

---

## REVISE vs RETRY

| REVISE (Response Problem) | RETRY (Approach Problem) |
|---------------------------|--------------------------|
| Formatting issues | Wrong research done |
| Missing citations | Missing critical data |
| Unclear wording | Misunderstood query |
| Data exists but not presented | Need different tools |

---

## Multi-Goal Validation

| Score | Status |
|-------|--------|
| >= 0.75 | PASS |
| 0.50-0.74 | PARTIAL |
| < 0.50 | FAIL |

| Scenario | Decision |
|----------|----------|
| All PASS | APPROVE |
| All PASS/PARTIAL | APPROVE (partial) |
| Any FAIL, others PASS | REVISE |
| Multiple FAIL | RETRY |

---

## Loop Limits

- REVISE: 2 attempts
- RETRY: 1 attempt
- Combined: 3 total

Exceeding any limit → FAIL

---

## Examples

### APPROVE

```json
{"decision": "APPROVE", "confidence": 0.92, "issues": [], "checks": {"claims_supported": true, "no_hallucinations": true, "query_addressed": true, "coherent_format": true}, "revision_hints": "", "suggested_fixes": ""}
```

### RETRY

```json
{"decision": "RETRY", "confidence": 0.35, "issues": ["Research returned [wrong category]", "No relevant results"], "checks": {"claims_supported": false, "no_hallucinations": false, "query_addressed": false, "coherent_format": true}, "revision_hints": "", "suggested_fixes": "Re-run research focusing on [correct category]"}
```

---

## Rules

- **If not in §4 or §1, it's a hallucination**
- No "reasonable inferences"
- No "common knowledge" claims without sources
