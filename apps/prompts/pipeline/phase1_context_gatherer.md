# Phase 2: Context Gatherer

Gather relevant context from memory, prior turns, and cached data.

Uses **Plan-Act-Review** pattern:
1. **RETRIEVAL**: Identify relevant sources
2. **SYNTHESIS**: Extract and compile into Section 2

---

## RETRIEVAL Phase

### Input

```
QUERY ANALYSIS (from Section 0):
{query_analysis_json}

UNIFIED MEMORY INDEX (memory graph nodes):
[
  {
    "node_id": "turn:<id>",
    "source_type": "turn_summary | preference | fact | research_cache | visit_record",
    "summary": "<short preview>",
    "confidence": 0.0-1.0,
    "timestamp": "<iso or age>",
    "source_ref": "<path to full doc>",
    "links": ["node_id", "..."]
  }
]
```

### Output (RetrievalPlan JSON)

```json
{
  "selected_nodes": {
    "turn_summary": ["node_id", "..."],
    "preference": ["node_id", "..."],
    "fact": ["node_id", "..."],
    "research_cache": ["node_id", "..."],
    "visit_record": ["node_id", "..."]
  },
  "selection_reasons": {
    "turn_summary": "string",
    "preference": "string",
    "fact": "string",
    "research_cache": "string",
    "visit_record": "string"
  },
  "coverage": {
    "has_prior_turns": true | false,
    "has_memory": true | false,
    "has_cached_research": true | false,
    "has_visit_data": true | false
  },
  "reasoning": "short narrative rationale"
}
```

---

## SYNTHESIS Phase

### Output (Section 2 with `_meta`)

```markdown
## 2. Gathered Context

### Session Preferences
```yaml
_meta:
  source_type: preference
  node_ids: ["node_id", "..."]
  confidence_avg: 0.0-1.0
  provenance: ["source_ref", "..."]
```
- [preference_key]: [value]

### Relevant Prior Turns
```yaml
_meta:
  source_type: turn_summary
  node_ids: ["node_id", "..."]
  confidence_avg: 0.0-1.0
  provenance: ["source_ref", "..."]
```
- [turn_summary_line]

### Cached Research
```yaml
_meta:
  source_type: research_cache
  node_ids: ["node_id", "..."]
  confidence_avg: 0.0-1.0
  provenance: ["source_ref", "..."]
```
- [research_summary_line]

### Visit Data
```yaml
_meta:
  source_type: visit_record
  node_ids: ["node_id", "..."]
  confidence_avg: 0.0-1.0
  provenance: ["source_ref", "..."]
```
- [visit_summary_line]

### Constraints
```yaml
_meta:
  source_type: [preference, user_query]
  node_ids: ["node_id", "..."]
  provenance: ["§0.raw_query", "source_ref"]
```
- [constraint_key]: [value]
```

---

## Relevance Filtering

**Only include content directly related to current query.**

| Query | Include | Omit |
|-------|---------|------|
| [Topic A] | Memory about [A] | Unrelated [B] |
| [Topic B] | Memory about [B] | Unrelated [A] |

---

## Token Budget

| Component | Tokens |
|-----------|--------|
| RETRIEVAL | ~5,500 |
| SYNTHESIS | ~5,000 |
| **Total** | ~10,500 |

### Truncation Priority (when over budget)

1. Memory (keep)
2. Research Cache (keep)
3. Recent Turns (trim)
4. Older Turns (drop first)

Per-turn limit: 1,500 tokens max
