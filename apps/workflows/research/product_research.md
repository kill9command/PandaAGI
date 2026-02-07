---
name: product_research
version: "2.0"
category: research
description: >
  Full commerce research: Phase 1 (LLM-driven intelligence gathering) +
  Phase 2 (vendor product extraction). The LLM is the brain - it decides
  what to search, which pages to visit, and when it has enough information.

triggers:
  - action_needed: live_search
  - "data_requirements.needs_current_prices: true"
  - "find me {product}"
  - "buy {product}"
  - "cheapest {product}"
  - "where can I buy {product}"
  - "shop for {product}"
  - "price of {product}"
  - "compare prices for {product}"

inputs:
  goal:
    type: string
    required: true
    from: original_query
    description: "User's query with priority signals (cheapest, best, etc.)"

  context:
    type: string
    required: false
    from: section_2
    description: "Session context from Context Gatherer - checked for prior intelligence"

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

  target_vendors:
    type: integer
    required: false
    default: 3
    description: "Number of vendors to visit in Phase 2 (default: 3)"

constraints:
  phase1_max_searches: 2
  phase1_max_visits: 8
  phase1_visit_delay_seconds: "4-6"
  phase1_timeout_seconds: 120
  max_text_per_page_tokens: 4000

outputs:
  products:
    type: array
    description: "Products found with prices, vendors, and specs"

  recommendation:
    type: string
    description: "Which product is best and why based on user's criteria"

  intelligence:
    type: object
    description: "Phase 1 intelligence: specs, price expectations, warnings"

  price_assessment:
    type: object
    description: "Price analysis - are prices good based on Phase 1 expectations?"

  sources:
    type: array
    description: "URLs visited during research"

  research_state_md:
    type: string
    description: "Full research_state.md document for debugging"

steps:
  # Step 1: Check for prior intelligence in §2
  - name: check_prior_intelligence
    description: >
      Research Planner checks context.md §2 for prior intelligence.
      If §2 contains full intelligence for this domain (recommendations,
      price expectations, specs), Phase 1 can be skipped.
    decision:
      if: "context contains prior_intelligence for topic"
      then: skip_to_phase2
      else: run_phase1

  # Step 2: Phase 1 - LLM-Driven Intelligence Loop
  - name: phase1_intelligence
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
      intent: "commerce"
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
      - vendor_hints
      - search_terms
      - price_range
      - findings
      - sources
      - searches_used
      - pages_visited

  # Step 3: Phase 2 - Product Finding
  - name: phase2_products
    description: >
      Visit exactly 3 vendors using Phase 1 intelligence.
      Extract products and compare to price expectations.
    tool: internet.research.phase2
    args:
      phase1_intelligence: "{{phase1_intelligence}}"
      goal: "{{goal}}"
      vendor_hints: "{{vendor_hints}}"
      search_terms: "{{search_terms}}"
      price_range: "{{price_range}}"
      target_vendors: "{{target_vendors | default: 3}}"
    outputs:
      - products
      - recommendation
      - price_assessment
      - vendors_visited
      - vendors_failed

success_criteria:
  - "products is not empty"

fallback:
  workflow: intelligence_search
  message: "Could not find products with prices. Here's what I learned instead:"
---

## Product Research Workflow

**Architecture Reference:** `architecture/mcp-tool-patterns/internet-research-mcp/INTERNET_RESEARCH_ARCHITECTURE.md`

Full commerce research using the LLM-driven two-phase architecture.
**The LLM is the brain. The system provides tools and state.**

### Core Principle

Instead of hardcoded phases, extraction pipelines, and complex branching logic, we give the LLM:
- A goal
- Tools (search, visit, done)
- Document-based state (`research_state.md`)
- Constraints (max visits, delays)

The LLM decides what to do, when, and knows when it's done.

---

### Two-Phase Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PHASE 1: INTELLIGENCE                            │
│                                                                      │
│  Goal: Learn about the topic from forums, reviews, articles         │
│  Method: LLM-driven loop with search/visit/done                     │
│  Sources: Reddit, reviews, forums, comparison sites                 │
│  Output: research_state.md with intelligence                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     PHASE 2: PRODUCT FINDING                         │
│                                                                      │
│  Goal: Find products matching Phase 1 intelligence                  │
│  Input: Phase 1 findings + user requirements                        │
│  Method: Visit 3 vendors, extract products                          │
│  Output: Product listings with prices                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

### When This Workflow Runs

Automatically selected when:
- Intent is `commerce` or `transactional`
- User asks to "buy", "find", or "shop for" something
- User asks for "cheapest" or "best price"
- User wants price comparisons

---

### Phase 1: LLM-Driven Intelligence Loop

The Research Planner LLM sees all context and decides every action:
- **WHAT** to research (from context/task)
- **HOW** to build queries (from prior_turn_context)
- **HOW** to prioritize (from goal - user's original words)

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
                             Proceed to Phase 2
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

### Phase 2: Product Finding (3 Vendors)

Uses Phase 1 intelligence to find actual products:

1. Build vendor list from Phase 1 hints + known vendors
2. Visit exactly 3 vendors
3. Search using Phase 1 search terms
4. Extract products and compare to Phase 1 price expectations
5. Generate recommendation based on Phase 1 intelligence

**Vendor Search Patterns:**
| Vendor | URL Pattern |
|--------|-------------|
| Amazon | `amazon.com/s?k={query}` |
| Best Buy | `bestbuy.com/site/searchpage.jsp?st={query}` |
| Newegg | `newegg.com/p/pl?d={query}` |
| Walmart | `walmart.com/search?q={query}` |

---

### Prior Intelligence Bypass

**Critical:** Before starting Phase 1, the Research Planner checks `context.md §2` for prior research intelligence.

| §2 Contains | Decision |
|-------------|----------|
| Full intelligence for this domain | PHASE2_ONLY (skip Phase 1) |
| Partial intelligence (gaps exist) | Targeted Phase 1, then Phase 2 |
| No relevant prior research | PHASE1_THEN_PHASE2 |

This prevents redundant research when the system already has the needed intelligence.

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

## Search Results
{list of URLs and titles from search}

## Visited Pages

### Page 1: {url}
**Findings:**
{extracted findings}

## Intelligence Summary

### What to Look For
{specs, features, recommendations}

### Price Expectations
{price ranges discovered}

### Recommended Models
{specific models mentioned positively}

### User Warnings
{things to avoid, common issues}

## Status
{in_progress | sufficient | done}
```

---

### Output Format

```json
{
  "products": [
    {
      "name": "Lenovo LOQ RTX 4060",
      "price": "$849.99",
      "price_numeric": 849.99,
      "vendor": "amazon.com",
      "url": "https://amazon.com/...",
      "in_stock": true,
      "confidence": 0.9,
      "specs": {
        "gpu": "RTX 4060",
        "ram": "16GB",
        "storage": "512GB SSD"
      }
    }
  ],
  "recommendation": "The Lenovo LOQ offers the best value based on Reddit recommendations...",
  "price_assessment": {
    "range": {"min": 800, "max": 1000},
    "verdict": "good",
    "reason": "Price is within expected range from user reviews"
  },
  "intelligence": {
    "specs_to_look_for": ["RTX 4060", "16GB RAM minimum"],
    "warnings": ["Avoid X brand for thermal issues"],
    "recommended_models": ["Lenovo LOQ", "MSI Thin GF63"]
  },
  "sources": ["reddit.com/r/GamingLaptops/...", "tomshardware.com/..."]
}
```

---

### Fallback Behavior

If no products are found (e.g., niche product, all vendors blocked),
falls back to `intelligence_search` and returns Phase 1 intelligence
so the user still gets useful information.

---

### Priority Signal Handling

The LLM reads user priority signals directly from the goal. Don't pre-classify.

- **"cheapest"** → LLM prioritizes price in recommendations
- **"best"** → LLM prioritizes quality/reviews
- **"under $X"** → LLM filters by price constraint
- **"from [vendor]"** → LLM prioritizes specified vendor

The original query is passed through so the LLM can read these signals directly.
