---
name: product_search
version: "1.0"
category: research
description: >
  Full commerce research: Phase 1 intelligence + Phase 2 product finding.
  Gathers intelligence first, then visits vendors to find actual products
  with prices. Used for shopping queries.

triggers:
  - intent: commerce
  - intent: transactional
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
    description: "Session context from Context Gatherer"

  target_vendors:
    type: integer
    required: false
    default: 3
    description: "Number of vendors to visit in Phase 2"

  max_products:
    type: integer
    required: false
    default: 10
    description: "Maximum products to return"

outputs:
  products:
    type: array
    description: "Products found with prices, vendors, and specs"

  recommendation:
    type: string
    description: "Which product is best and why based on user's criteria"

  intelligence:
    type: object
    description: "Phase 1 intelligence used to guide product search"

  price_assessment:
    type: object
    description: "Price analysis - is the price good, fair, or high?"

steps:
  - name: execute_full_research
    tool: internal://internet_research.execute_full_research
    args:
      goal: "{{goal}}"
      intent: "commerce"
      context: "{{context}}"
      target_vendors: "{{target_vendors | default: 3}}"
      max_products: "{{max_products | default: 10}}"
    outputs:
      - products
      - recommendation
      - price_assessment
      - intelligence
      - phase1
      - phase2
      - findings
      - sources

success_criteria:
  - "products is not empty"
  - "products.length >= 1"

fallback:
  workflow: intelligence_search
  message: "Could not find products with prices. Here's what I learned about the topic instead:"
---

## Product Search Workflow

Full commerce research workflow that runs Phase 1 (intelligence gathering)
followed by Phase 2 (vendor product extraction).

### When This Workflow Runs

Automatically selected when:
- Intent is `commerce` or `transactional`
- User asks to "buy", "find", or "shop for" something
- User asks for "cheapest" or "best price"
- User wants price comparisons

### What It Does

1. **Phase 1 - Intelligence Gathering**:
   - Searches forums and review sites
   - Identifies recommended products/brands
   - Learns price expectations
   - Discovers good vendors to check

2. **Phase 2 - Product Finding**:
   - Uses Phase 1 insights to select vendors
   - Visits vendor sites and extracts products
   - Gets actual prices, stock status, specs
   - Compares against Phase 1 price expectations

3. **Recommendation Generation**:
   - Synthesizes findings with user's original criteria
   - If user said "cheapest", recommends lowest price
   - If user said "best", recommends highest quality

### Output Format

```json
{
  "products": [
    {
      "name": "Prevue 528 Large Hamster Cage",
      "price": 89.99,
      "vendor": "Amazon",
      "url": "https://amazon.com/...",
      "in_stock": true,
      "confidence": 0.9,
      "specs": {
        "dimensions": "32x21x24 inches",
        "floor_space": "672 sq in"
      }
    }
  ],
  "recommendation": "The Prevue 528 offers the best value...",
  "price_assessment": {
    "range": {"min": 40, "max": 150},
    "average": 80,
    "verdict": "fair"
  },
  "intelligence": {...}
}
```

### Fallback Behavior

If no products are found (e.g., niche product, all vendors blocked),
the workflow falls back to `intelligence_search` and returns the
intelligence gathered so the user still gets useful information.

### Priority Signal Handling

The workflow preserves user priority signals in the goal:

- **"cheapest"** - Phase 2 sorts by price ascending
- **"best"** - Phase 2 prioritizes highly-rated products
- **"under $X"** - Phase 2 filters by price constraint
- **"from [vendor]"** - Phase 2 prioritizes specified vendor

### Example

Input:
```
goal: "find me the cheapest laptop with nvidia gpu under $1000"
```

Output includes products sorted by price, filtered to under $1000,
with recommendation explaining the best value option.
