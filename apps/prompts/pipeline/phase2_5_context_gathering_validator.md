# Phase 2.5: Context Gathering Validator

Check if gathered context is ready for planning. **Default to pass.**

**Output:** JSON only.

---

## Output Schema

```json
{
  "status": "pass | retry | clarify",
  "issues": ["[specific problem]"],
  "missing_context": ["[what's missing]"],
  "retry_guidance": ["[how to fix on retry]"],
  "clarification_question": "[question for user] | null"
}
```

---

## Decision Logic

| Condition | Status | Guidance |
|-----------|--------|----------|
| §2 has content sections with actual data | `pass` | |
| §2 has `_meta` blocks but no content below them | `retry` | "Include actual content under each _meta block, not just metadata" |
| §2 references node_ids not found in memory index | `retry` | "Remove unknown node_ids or select valid nodes from memory index" |
| §2 is completely empty AND retrieval found nothing | `retry` | "Re-run retrieval with broader selection" |
| Query is garbled nonsense (extremely rare) | `clarify` | Provide clarification question |

**Default to `pass` when uncertain.**

---

## Key Principle

**The pipeline handles incomplete information.** Don't reject queries because some metadata is missing or context is partial. Let downstream phases work with whatever is available.

Partial context with real data > perfect metadata with empty sections.

## Do NOT

- Return `retry` for minor metadata issues
- Return `clarify` when `retry` would fix the problem
- Be overly strict — the Planner can work around gaps
