---
name: product_quick_find
version: "1.0"
category: research
description: >
  Phase 2 ONLY: Direct vendor product extraction using EXISTING intelligence.
  Skips Phase 1 research because context.md §2 already contains intelligence
  from a previous turn. Fast path for commerce when we already know what to look for.

triggers:
  - action_needed: live_search
  - "data_requirements.needs_current_prices: true"
  # Only when Planner detects prior intelligence in §2:
  - "§2 contains intelligence for topic"

planner_selection:
  # Planner chooses this workflow when:
  conditions:
    - "action_needed is live_search with needs_current_prices (user wants to buy)"
    - "context.md §2 contains prior_intelligence for this topic"
    - "prior_intelligence has: vendor_hints, search_terms, price_range"
  token_cost_estimate: "~3000-5000 tokens (Phase 2 only)"
  # Compare to product_research which costs ~8000-12000 tokens (Phase 1 + Phase 2)

inputs:
  goal:
    type: string
    required: true
    from: original_query
    description: "User's query with priority signals (cheapest, best, etc.)"

  # Prior intelligence from §2 (REQUIRED for this workflow)
  prior_intelligence:
    type: object
    required: true
    from: section_2_intelligence
    description: "Intelligence from previous research turn"

  vendor_hints:
    type: array
    required: false
    from: section_2_vendor_hints
    description: "Vendors mentioned positively in prior research"

  search_terms:
    type: array
    required: false
    from: section_2_search_terms
    description: "Search terms from prior research"

  price_range:
    type: object
    required: false
    from: section_2_price_range
    description: "Expected price range from prior research"

  target_vendors:
    type: integer
    required: false
    default: 3
    description: "Number of vendors to visit (default: 3)"

constraints:
  max_vendors: 5
  visit_delay_seconds: "4-6"
  timeout_seconds: 90
  max_text_per_page_tokens: 4000

outputs:
  products:
    type: array
    description: "Products found with prices, vendors, and specs"

  recommendation:
    type: string
    description: "Which product is best based on prior intelligence + user criteria"

  price_assessment:
    type: object
    description: "Are prices good compared to prior intelligence expectations?"

  vendors_visited:
    type: array
    description: "Vendors successfully visited"

  vendors_failed:
    type: array
    description: "Vendors that failed to load"

steps:
  - name: phase2_product_extraction
    description: >
      Visit vendors and extract products using prior intelligence.
      No Phase 1 research needed - we already know what to look for.
    tool: internet.research.phase2
    args:
      goal: "{{goal}}"
      phase1_intelligence: "{{prior_intelligence}}"
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
  # If Phase 2 fails with prior intelligence, run full research
  workflow: product_research
  message: "Prior intelligence may be outdated. Running full research..."
---

## Product Quick Find Workflow (Phase 2 Only)

**Architecture Reference:** `architecture/mcp-tool-patterns/internet-research-mcp/INTERNET_RESEARCH_ARCHITECTURE.md`

Phase 2 only product extraction using **existing intelligence from §2**.
**Fast path for commerce when we already know what to look for.**

### Strategy: `phase2_only`

This workflow skips Phase 1 intelligence gathering because `context.md §2`
already contains relevant intelligence from a previous turn.

---

### When Planner Should Select This Workflow

| Condition | Select product_quick_find |
|-----------|----------------------|
| Intent is `commerce` or `transactional` | ✓ Required |
| §2 contains prior intelligence for topic | ✓ Required |
| Prior intelligence has vendor_hints | ✓ Required |
| Prior intelligence has search_terms | ✓ Required |
| Token budget is limited | ✓ Bonus (saves ~4000 tokens) |

**Token Cost:** ~3000-5000 tokens (Phase 2 only)
**Compare to:** `product_research` costs ~8000-12000 tokens (Phase 1 + Phase 2)

---

### Decision Matrix for Planner

```
Commerce Query Received
  │
  ├── Check §2 for prior intelligence
  │
  ├── §2 has FULL intelligence ──────────→ product_quick_find (Phase 2 only)
  │   (vendor_hints, search_terms,           ~3000-5000 tokens
  │    price_range, recommendations)
  │
  ├── §2 has PARTIAL intelligence ────────→ product_research (targeted Phase 1)
  │   (some fields missing)                  ~6000-10000 tokens
  │
  └── §2 has NO intelligence ─────────────→ product_research (full Phase 1 + 2)
      (no prior research)                    ~8000-12000 tokens
```

---

### What Prior Intelligence Should Contain

For this workflow to be selected, §2 should have:

```markdown
## §2 Prior Context

### Prior Research Intelligence (from turn_XXXXX)

**Topic:** Gaming laptops with RTX GPUs

**Intelligence:**
- Key specs: RTX 4060 is sweet spot, 16GB RAM minimum
- Recommended models: Lenovo LOQ, MSI Thin GF63
- Price range: $800-1000 for good value
- Warnings: Avoid X brand for thermal issues

**Vendor Hints:** Amazon, Best Buy, Newegg
**Search Terms:** "Lenovo LOQ RTX 4060", "MSI Thin GF63"
```

---

### Phase 2: Product Finding (3 Vendors)

Uses prior intelligence to find actual products:

1. Build vendor list from `vendor_hints` + known vendors
2. Visit exactly 3 vendors (configurable via `target_vendors`)
3. Search using `search_terms` from prior intelligence
4. Extract products with prices, stock status, specs
5. Compare prices to `price_range` expectations
6. Generate recommendation using prior intelligence criteria

**Vendor Search Patterns:**
| Vendor | URL Pattern |
|--------|-------------|
| Amazon | `amazon.com/s?k={query}` |
| Best Buy | `bestbuy.com/site/searchpage.jsp?st={query}` |
| Newegg | `newegg.com/p/pl?d={query}` |
| Walmart | `walmart.com/search?q={query}` |

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
  "recommendation": "The Lenovo LOQ matches your 'cheapest' criteria at $849...",
  "price_assessment": {
    "range": {"min": 800, "max": 1000},
    "verdict": "good",
    "reason": "Price is within expected range from prior research"
  },
  "vendors_visited": ["amazon.com", "bestbuy.com", "newegg.com"],
  "vendors_failed": []
}
```

---

### Fallback Behavior

If Phase 2 fails with prior intelligence (e.g., products not found, intelligence outdated),
falls back to `product_research` which runs full Phase 1 + Phase 2.

This handles cases where:
- Prior intelligence is stale (prices changed, products discontinued)
- Vendor hints no longer carry the product
- Search terms yield no results

---

### Example Flow

**Previous Turn (informational):**
```
User: "what are the best budget gaming laptops?"
→ Runs intelligence_search
→ Saves intelligence to memory
```

**Current Turn (commerce):**
```
User: "find me one under $900"
→ Planner sees §2 has prior intelligence
→ Selects product_quick_find (Phase 2 only)
→ Skips research, goes directly to vendors
→ Saves ~4000 tokens
```

---

### Token Budget Consideration

The Planner should consider token budget when choosing between:

| Workflow | Token Cost | When to Use |
|----------|-----------|-------------|
| `intelligence_search` | ~4000-8000 | Informational only |
| `product_quick_find` | ~3000-5000 | Commerce + has prior intelligence |
| `product_research` | ~8000-12000 | Commerce + needs full research |

If budget is tight and §2 has intelligence, prefer `product_quick_find`.
If budget is tight and no prior intelligence, prefer `intelligence_search` alone.
