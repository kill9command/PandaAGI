# Phase 2: Reflection

Fast binary gate: Can we answer this query?

---

## Output Schema

```json
{
  "decision": "PROCEED | CLARIFY",
  "confidence": 0.0-1.0,
  "reasoning": "[brief explanation]",
  "interaction_type": "ACTION | RETRY | RECALL | CLARIFICATION | INFORMATIONAL",
  "is_followup": true | false,
  "clarification_question": "[question if CLARIFY, null otherwise]"
}
```

---

## Decision Rules

| Decision | When | Next Phase |
|----------|------|------------|
| **PROCEED** | Query is clear enough | Phase 3 (Planner) |
| **CLARIFY** | Genuinely ambiguous | Return to user |

### PROCEED (Default)

Use when:
- Query intent is understandable
- `reference_resolution.status: not_needed` or `resolved`
- Even if context is thin (downstream phases can gather more)

**When uncertain, PROCEED.** Let Planner handle nuance.

### CLARIFY (Exception)

Use **only** when:
- `reference_resolution.status: failed` AND query is genuinely ambiguous
- Multiple incompatible interpretations
- Critical info missing that research cannot provide

---

## reference_resolution.status

| Status | Action |
|--------|--------|
| `not_needed` | Strongly favor PROCEED |
| `resolved` | Strongly favor PROCEED |
| `failed` | Evaluate if actionable, lean CLARIFY |

---

## Interaction Types

| Type | Example |
|------|---------|
| ACTION | "Find me [X]" |
| RETRY | "Search again" |
| RECALL | "What was that first option?" |
| CLARIFICATION | "What did you mean?" |
| INFORMATIONAL | "How do [X] work?" |

---

## Examples

### PROCEED - Clear Query

```json
{
  "decision": "PROCEED",
  "confidence": 0.95,
  "reasoning": "Query intent clear: find [product]. No ambiguity.",
  "interaction_type": "ACTION",
  "is_followup": false,
  "clarification_question": null
}
```

### PROCEED - Resolved Follow-up

```json
{
  "decision": "PROCEED",
  "confidence": 0.95,
  "reasoning": "Phase 0 resolved the reference. Query now explicit.",
  "interaction_type": "RECALL",
  "is_followup": true,
  "clarification_question": null
}
```

### CLARIFY - Unresolved Reference

```json
{
  "decision": "CLARIFY",
  "confidence": 0.90,
  "reasoning": "Query '[vague reference]' has no referent. Phase 0 could not resolve.",
  "interaction_type": "ACTION",
  "is_followup": true,
  "clarification_question": "Could you specify what you're looking for?"
}
```

---

## Do NOT

- Ask clarification when Phase 0 resolved successfully
- Over-classify as CLARIFY to "be safe"
- Spend tokens on detailed analysis (Planner's job)
