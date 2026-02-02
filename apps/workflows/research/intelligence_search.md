---
name: intelligence_search
version: "1.0"
category: research
description: >
  Phase 1 intelligence gathering from forums, reviews, and articles.
  Used for informational queries or as the first step of commerce research.
  Gathers specs, recommendations, and price expectations.

triggers:
  - intent: informational
  - intent: live_search
  - "what are the best {topic}"
  - "tell me about {topic}"
  - "research {topic}"
  - "find information about {topic}"
  - "learn about {topic}"

inputs:
  goal:
    type: string
    required: true
    from: original_query
    description: "User's query with priority signals preserved"

  context:
    type: string
    required: false
    from: section_2
    description: "Session context from Context Gatherer"

  task:
    type: string
    required: false
    default: ""
    description: "Specific research task from Planner"

  max_visits:
    type: integer
    required: false
    default: 8
    description: "Maximum pages to visit"

outputs:
  intelligence:
    type: object
    description: "Extracted intelligence with key_facts, recommended_models, price_range"

  findings:
    type: array
    description: "Key facts discovered during research"

  vendor_hints:
    type: array
    description: "Vendors mentioned positively in sources"

  search_terms:
    type: array
    description: "Good search terms discovered for follow-up"

  sources:
    type: array
    description: "URLs of sources visited"

steps:
  - name: execute_phase1_research
    tool: internal://internet_research.execute_research
    args:
      goal: "{{goal}}"
      intent: "informational"
      context: "{{context}}"
      task: "{{task | default: ''}}"
      max_visits: "{{max_visits | default: 8}}"
    outputs:
      - intelligence
      - findings
      - vendor_hints
      - search_terms
      - price_range
      - sources

success_criteria:
  - "findings is not empty OR intelligence.key_facts is not empty"
  - "sources is not empty"

fallback:
  workflow: null
  message: "Unable to find relevant information. Try rephrasing your question or being more specific about what you're looking for."
---

## Intelligence Search Workflow

This workflow wraps Phase 1 of the LLM-driven research loop for gathering
intelligence from web sources like forums, reviews, and comparison articles.

### When This Workflow Runs

Automatically selected when:
- Intent is `informational` or `live_search`
- User asks "what are the best X"
- User says "tell me about X"
- User wants to learn about a topic

### What It Does

1. **Search Phase**: Uses LLM to generate search queries targeting forums,
   reviews, and comparison articles
2. **Visit Phase**: Navigates to promising results, extracts key information
3. **Synthesis Phase**: Consolidates findings into structured intelligence

### Output Format

Returns a `Phase1Intelligence` structure containing:

- **intelligence**: Object with:
  - `key_facts`: Important facts discovered
  - `recommended_models`: Specific product/item recommendations
  - `price_range`: Expected price range if applicable
  - `considerations`: Things to consider when choosing

- **findings**: Array of individual facts/statements extracted

- **vendor_hints**: Vendors mentioned positively (useful for Phase 2)

- **search_terms**: Search terms that yielded good results

### Integration

This workflow is called by the Coordinator when processing informational
queries. It can also be chained with `product_search` for commerce queries
that need intelligence gathering first.

### Example

Input:
```
goal: "what are the best hamster cages for syrian hamsters"
```

Output:
```json
{
  "intelligence": {
    "key_facts": [
      "Syrian hamsters need at least 450 sq inches of floor space",
      "Wire cages allow better ventilation than aquariums",
      "Multiple levels are good for enrichment"
    ],
    "recommended_models": [
      "Prevue 528",
      "Kaytee CritterTrail",
      "Savic Hamster Heaven"
    ],
    "price_range": {"min": 40, "max": 150}
  },
  "findings": [...],
  "vendor_hints": ["Amazon", "Chewy", "PetSmart"]
}
```
