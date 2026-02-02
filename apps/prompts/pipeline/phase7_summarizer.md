# Phase 7: Turn Summarizer

Compress a completed turn into a concise summary for the turn index.

---

## Output Schema

```json
{
  "summary": "[1-2 sentences, max 50 tokens]",
  "topics": ["[topic1]", "[topic2]"],
  "intent": "commerce | query | recall | preference | navigation | greeting | edit | create | git | test | refactor",
  "has_research": true | false,
  "research_topic": "[category.subcategory] | null",
  "key_findings": ["[finding with details]"],
  "preferences_learned": {"[key]": "[value]"},
  "satisfaction_estimate": 0.0-1.0,
  "content_refs": ["[title of content discussed]"]
}
```

---

## Field Guidelines

| Field | Guidance |
|-------|----------|
| `summary` | Focus on OUTCOME, not process. Include key decisions. |
| `topics` | 2-5 keywords for retrieval |
| `has_research` | true if internet.research was called |
| `research_topic` | Format: `category.subcategory` |
| `key_findings` | Include specifics: names, prices, URLs, counts |
| `preferences_learned` | Only NEW preferences this turn |
| `satisfaction_estimate` | 0.0=unmet, 0.5=partial, 0.8=good, 1.0=complete |

---

## Satisfaction Scoring

| Factor | Impact |
|--------|--------|
| Answered question | +0.3 |
| Specific, actionable info | +0.2 |
| Included sources/links | +0.1 |
| Errors or "sorry" | -0.2 |
| Asked for clarification | -0.1 |

---

## Examples

### Commerce Research

```json
{
  "summary": "Found [N] [products] under $[budget]. Recommended [product] at $[price] as best value.",
  "topics": ["[category]", "[spec]", "budget"],
  "intent": "commerce",
  "has_research": true,
  "research_topic": "commerce.[category]",
  "key_findings": [
    "[Product A] at $[price] from [vendor]",
    "[Product B] at $[price] from [vendor]"
  ],
  "preferences_learned": {"budget": "under $[amount]"},
  "satisfaction_estimate": 0.8,
  "content_refs": []
}
```

### Code Edit

```json
{
  "summary": "Fixed [bug] in [file] where [issue]. Tests now passing.",
  "topics": ["[module]", "bug fix", "[feature]"],
  "intent": "edit",
  "has_research": false,
  "research_topic": null,
  "key_findings": [
    "Fixed [issue] in [file]:[function]()",
    "All [N] tests passing"
  ],
  "preferences_learned": {},
  "satisfaction_estimate": 0.9,
  "content_refs": []
}
```

### No Results

```json
{
  "summary": "Search for '[query]' returned no results. Offered alternatives.",
  "topics": ["[category]"],
  "intent": "commerce",
  "has_research": true,
  "research_topic": "[category].[subcategory]",
  "key_findings": [],
  "preferences_learned": {},
  "satisfaction_estimate": 0.3,
  "content_refs": []
}
```

---

## Do NOT

```
BAD: "The user asked about [topic] and we provided information"
GOOD: "Found [N] [items] under $[budget]: [Product A] ($[price]), [Product B] ($[price])"

BAD: key_findings: ["Found some items", "Prices vary"]
GOOD: key_findings: ["[Product] $[price]", "[Product] $[price]"]
```

---

## Rules

1. JSON only, max 300 tokens
2. Preserve specific details (prices, names, URLs)
3. Focus on outcomes, not process
4. Only include NEW preferences
