# Phase 8: Turn Summary

Generate a concise summary for turn indexing and continuity.

**Output:** JSON only. Must start with `{` and end with `}`.

---

## Input

- `context.md` (§0–§7)

---

## Output Schema

```json
{
  "summary": "1-2 sentence description of what happened",
  "topics": ["<topic_1>", "<topic_2>", "<topic_3>"],
  "has_research": true | false,
  "research_topic": "<category.subcategory>" | null
}
```

---

## Rules

- Focus on outcomes, not process.
- Keep the summary under two sentences.
- Topics must be abstract labels, not brand names.
- If no research occurred, set `has_research` to false and `research_topic` to null.
