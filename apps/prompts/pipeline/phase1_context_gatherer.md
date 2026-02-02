# Phase 1: Context Gatherer

Gather relevant context from memory, prior turns, and cached data.

Uses **Plan-Act-Review** pattern:
1. **RETRIEVAL**: Identify relevant sources
2. **SYNTHESIS**: Extract and compile into Section 1

---

## RETRIEVAL Phase

### Input

```
QUERY ANALYSIS (from Section 0):
{query_analysis_json}

AVAILABLE SOURCES:
- Turn Summaries (last 20)
- Memory Headers
- Research Cache
- Forever Memory
```

### Output

```json
{
  "relevant_turns": [N, N-1],
  "turn_relevance": {"N": {"relevance": "high", "reason": "[reason]"}},
  "relevant_memory_keys": ["[key1]", "[key2]"],
  "research_cache_match": {
    "matched": true | false,
    "topic": "[category.subcategory]",
    "freshness": "[N] hours",
    "quality": 0.0-1.0,
    "reuse_recommendation": "full | partial | refresh"
  },
  "forever_memory_relevant": ["[document.md]"],
  "reasoning": "[explanation]"
}
```

---

## SYNTHESIS Phase

### Output

```json
{
  "session_preferences": {"[key]": "[value]"},
  "prior_turns": [
    {"turn": N, "relevance": "high", "summary": "[summary]", "key_facts": ["[fact]"]}
  ],
  "cached_research": {
    "topic": "[category.subcategory]",
    "quality": 0.0-1.0,
    "age_hours": N,
    "summary": "[summary]",
    "top_results": [{"product": "[name]", "price": "$[N]", "source": "[site]"}]
  },
  "forever_memory": {
    "documents": ["[doc.md]"],
    "key_facts": ["[fact]"]
  },
  "source_references": ["[1] [path]"]
}
```

---

## Section 1 Format

```markdown
## 1. Gathered Context

### User Preferences
| Preference | Value | Source |
|------------|-------|--------|
| [key] | [value] | Turn [N] |

### Relevant Prior Turns
| Turn | Relevance | Summary | Key Facts |
|------|-----------|---------|-----------|
| [N] | high | [summary] | [facts] |

### Cached Research Intelligence
**Topic:** [category.subcategory]
**Quality:** [score] | **Age:** [N] hours

| Product | Price | Source |
|---------|-------|--------|
| [name] | $[N] | [site] |

### Context Assessment
**Quality:** [score]
**Gaps:** [identified gaps or "None"]
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
