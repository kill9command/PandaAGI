---
name: intelligence_search
version: "2.0"
category: research
description: >
  Phase 1 ONLY: LLM-driven intelligence gathering from forums, reviews, and articles.
  The LLM is the brain - it decides what to search, which pages to visit, and
  when it has enough information. Returns intelligence without product lookup.

triggers:
  - action_needed: live_search
  - "data_requirements.needs_current_prices: false"
  - "what are the best {topic}"
  - "tell me about {topic}"
  - "research {topic}"
  - "find information about {topic}"
  - "learn about {topic}"
  - "who is {person}"
  - "what is {thing}"

planner_selection:
  # Planner chooses this workflow when:
  conditions:
    - "action_needed is live_search and user doesn't need prices (informational research)"
    - "token_budget < 6000 (not enough for full product search)"
    - "user explicitly asks for research/information only"
  token_cost_estimate: "~4000-8000 tokens (Phase 1 only)"

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
    from: section_3
    description: "Specific research task from Planner (Phase 3)"

  prior_turn_context:
    type: string
    required: false
    from: section_1_prior_turn
    description: "Conversation context for dynamic query building"

  topic:
    type: string
    required: false
    from: section_1_topic
    description: "Topic classification from Phase 1"

  target_url:
    type: string
    required: false
    from: content_reference.source_url
    description: "Direct URL to visit for follow-up queries (from prior turn's extracted links)"

constraints:
  max_searches: 2
  max_visits: 8
  visit_delay_seconds: "4-6"
  timeout_seconds: 120
  max_text_per_page_tokens: 4000

outputs:
  intelligence:
    type: object
    description: "Extracted intelligence: key_facts, recommendations, price_range, warnings"

  findings:
    type: array
    description: "Key facts discovered during research"

  vendor_hints:
    type: array
    description: "Vendors mentioned positively (can be used by product_quick_find later)"

  search_terms:
    type: array
    description: "Good search terms discovered (can be used by product_quick_find later)"

  price_range:
    type: object
    description: "Price expectations discovered (min, max)"

  sources:
    type: array
    description: "URLs of sources visited"

  research_state_md:
    type: string
    description: "Full research_state.md document for debugging"

steps:
  - name: phase1_intelligence_loop
    description: >
      LLM-driven research loop. Research Planner decides every action:
      search, visit, or done. System executes and updates state.
    tool: internet.research
    args:
      goal: "{{goal}}"
      context: "{{context}}"
      task: "{{task}}"
      prior_turn_context: "{{prior_turn_context}}"
      topic: "{{topic}}"
      intent: "informational"
      target_url: "{{target_url}}"
    state_document: research_state.md
    roles:
      - name: Research Planner
        temperature: 0.5  # MIND
        purpose: "Decides next action, evaluates progress"
        actions:
          - '{"action": "search", "query": "...", "reason": "..."}'
          - '{"action": "visit", "url": "...", "reason": "..."}'
          - '{"action": "done", "reason": "..."}'
      - name: Result Scorer
        temperature: 0.3  # REFLEX
        purpose: "Quick scoring of search results for relevance"
      - name: Content Extractor
        temperature: 0.5  # MIND
        purpose: "Extracts findings from page text"
    outputs:
      - intelligence
      - findings
      - vendor_hints
      - search_terms
      - price_range
      - sources
      - searches_used
      - pages_visited
      - research_state_md

success_criteria:
  - "findings is not empty OR intelligence.key_facts is not empty"
  - "sources is not empty"

fallback:
  workflow: null
  message: "Unable to find relevant information. Try rephrasing your question or being more specific about what you're looking for."
---

## Intelligence Search Workflow (Phase 1 Only)

**Architecture Reference:** `architecture/mcp-tool-patterns/internet-research-mcp/INTERNET_RESEARCH_ARCHITECTURE.md`

Phase 1 only research using the LLM-driven loop.
**The LLM is the brain. The system provides tools and state.**

### Strategy: `phase1_only`

This workflow runs Phase 1 intelligence gathering WITHOUT Phase 2 product lookup.
Use this for informational queries where the user wants to learn, not buy.

---

### When Planner Should Select This Workflow

| Condition | Select intelligence_search |
|-----------|---------------------------|
| `action_needed: live_search` with `needs_current_prices: false` | ✓ Yes |
| User asks "what is", "who is", "tell me about" | ✓ Yes |
| Token budget < 6000 | ✓ Yes (not enough for full research) |
| User explicitly wants research only | ✓ Yes |
| `action_needed: live_search` but no budget for Phase 2 | ✓ Yes (return intelligence only) |

**Token Cost:** ~4000-8000 tokens (Phase 1 only)

---

### LLM-Driven Research Loop

```
START
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ RESEARCH PLANNER (MIND - temp 0.5)                          │
│                                                              │
│ Reads: research_state.md                                     │
│ Decides: What's the next action?                            │
│                                                              │
│ Options:                                                     │
│   - {"action": "search", "query": "..."}                    │
│   - {"action": "visit", "url": "..."}                       │
│   - {"action": "done"}                                      │
└─────────────────────────────────────────────────────────────┘
  │
  ├─── action = "search" ──→ Execute search, score results
  │                          Update research_state.md
  │
  ├─── action = "visit" ───→ Visit page, extract content
  │                          Update research_state.md
  │
  └─── action = "done" ────→ Return Phase 1 intelligence
                             (NO Phase 2 - workflow ends)
```

**Constraints:**
| Constraint | Value | Reason |
|------------|-------|--------|
| Max searches | 2 | Avoid detection, usually 1 is enough |
| Max page visits | 8 | Enough for good coverage, limits cost |
| Delay between visits | 4-6 seconds | Human-like behavior |
| Overall timeout | 120 seconds | Don't hang forever |
| Max text per page | 4000 tokens | Fit in context |

**LLM Roles:**
| Role | Temperature | Purpose |
|------|-------------|---------|
| Research Planner | 0.5 (MIND) | Decides next action, evaluates progress |
| Result Scorer | 0.3 (REFLEX) | Quick scoring of search results |
| Content Extractor | 0.5 (MIND) | Extracts findings from page text |

---

### Document-Based State

All state flows through `research_state.md`:

```markdown
# Research State

## Goal (User's Original Query)
{original_query}

## Prior Turn Context
{prior_turn_context}  <!-- Enables dynamic query building -->

## Topic
{topic}  <!-- From §1 Topic Classification -->

## Action
informational (research-mode parameter for internet.research tool)

## Search Results
{list of URLs and titles from search}

## Visited Pages

### Page 1: {url}
**Findings:**
{extracted findings}

## Intelligence Summary

### Key Facts
{important facts relevant to the goal}

### Recommendations
{advice or suggestions from sources}

### Price Expectations (if applicable)
{price ranges discovered}

### Warnings
{things to avoid, common issues}

## Status
{in_progress | sufficient | done}
```

---

### Output Format

```json
{
  "intelligence": {
    "key_facts": [
      "Syrian hamsters need at least 450 sq inches of floor space",
      "Wire cages allow better ventilation than aquariums",
      "Multiple levels are good for enrichment"
    ],
    "recommendations": [
      "Prevue 528 is highly recommended for value",
      "Avoid glass tanks due to poor ventilation"
    ],
    "price_range": {"min": 40, "max": 150},
    "warnings": ["Crittertrail cages are too small for adults"]
  },
  "findings": [
    "Syrian hamsters need minimum 450 sq in floor space",
    "Wire spacing should be no more than 0.5 inches"
  ],
  "vendor_hints": ["Amazon", "Chewy", "PetSmart"],
  "search_terms": ["large hamster cage", "Prevue 528"],
  "sources": ["reddit.com/r/hamsters/...", "hamsterhideout.com/..."]
}
```

---

### Chaining with Product Lookup

The output of this workflow (especially `vendor_hints`, `search_terms`, `price_range`)
can be passed to `product_quick_find` workflow if the user later wants to buy.

This allows the Planner to:
1. Run `intelligence_search` first (learn about topic)
2. Store intelligence in §2
3. Later run `product_quick_find` using cached intelligence (skip Phase 1)

---

### Example

**Input:**
```
goal: "what are the best hamster cages for syrian hamsters"
action_needed: live_search (needs_current_prices: false)
```

**Output:** Intelligence about hamster cages without visiting vendor sites.
User learns what to look for before deciding to buy.
