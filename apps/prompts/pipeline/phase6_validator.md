# Phase 7: Validation

Validate synthesis output before delivery.

**Output:** JSON only. Must start with `{` and end with `}`.

---

## Inputs

- `context.md` §0–§6 (query, validation status, gathered context, plan, execution, synthesis)
- `response.md` (optional; if present, treat §6 as canonical when conflicts exist)

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
    "coherent_format": true | false,
    "source_metadata_present": true | false
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

## Validation Checks

### 1) claims_supported

Every factual claim has evidence in §4 (workflow results) or §2 (gathered context).

If any claim cannot be traced to evidence, mark `claims_supported: false`.

### 2) no_hallucinations

No invented information. If it is not in §4 or §2, it is a hallucination.

### 3) query_addressed

The response directly answers §0 and respects all stated constraints
(scope, budget, preferences, format, and required comparisons).

If any requirement from §0 is unmet, mark `query_addressed: false`.

### 4) coherent_format

Readable, structured output with valid markdown and complete sentences.

### 5) source_metadata_present

Claims that require sources include `url` or `source_ref`, and those
identifiers correspond to evidence in §4 or §2.

If a claim is presented as factual without source metadata, mark `false`.

---

## REVISE vs RETRY

**REVISE (Response Problem):**
- Evidence exists but is missing or misused
- Missing citations or source metadata
- Formatting or clarity issues
- Partial answer with available data

**RETRY (Approach Problem):**
- Missing critical evidence
- Wrong research approach or missing workflows
- Misunderstood or unaddressed requirements

---

## Multi-Goal Validation

If multiple goals are present, validate each independently and aggregate:
- All PASS → APPROVE
- PASS/PARTIAL only → APPROVE (partial)
- Any FAIL with others PASS → REVISE
- Multiple FAIL → RETRY

---

## Rules

- **If not in §4 or §2, it's a hallucination**
- No "reasonable inferences"
- No "common knowledge" claims without sources
