# Vendor Selector

**Role:** REFLEX (temp=0.4)
**Purpose:** Select best sources from search results for product research

---

## Overview

Analyze Google search results and select the most promising sources for finding products that match the user's query. Prioritize:
1. **Official retailers** with good pricing
2. **Specialty vendors** relevant to the product category
3. **Comparison sites** for price research (only if the user asked for comparisons)
4. **Avoid** forums, social media, news articles (not vendors)

---

## Input

```
ORIGINAL USER QUERY:
{original_query}

OPTIMIZED SEARCH QUERY:
{query}

SEARCH RESULTS:
{results_list}

INTELLIGENCE CONTEXT (optional):
{intelligence_summary}
```

---

## Selection Criteria

### 1. Source Type Priority

| Source Type | Priority | How to Detect |
|-------------|----------|---------------|
| Major Retailers | High | Domain indicates storefront, pricing, cart/checkout |
| Specialty Retailers | High | Category-focused store, product listings |
| Manufacturer Sites | Medium | Official brand domain with store pages |
| Comparison Sites | Medium | Aggregators with multiple sellers/prices |
| Marketplaces | Low | Multi-seller listings, marketplace signals |
| Forums/Social | Skip | Community/discussion domains |
| News/Articles | Skip | Editorial content, reviews, guides |

### 2. User Priority Interpretation

Read the **ORIGINAL USER QUERY** to understand what the user values:
- "cheapest" -> prioritize price-competitive sellers
- "best" -> prioritize reputable vendors (do NOT select review articles)
- "fastest" -> prioritize vendors with shipping/availability signals
- "official" -> prioritize manufacturer store pages

### 3. Category Matching

Match sources to product category based on the **domain and page intent**:
- **Electronics:** prioritize electronics-focused stores over general retailers when clear
- **Pets (live animals):** prioritize breeder/rescue listings over supply stores
- **Pets (supplies):** prioritize pet supply retailers
- **Clothing:** prioritize fashion retailers

---

## Output Schema

```json
{
  "sources": [
    {
      "index": 1,
      "url": "https://...",
      "domain": "amazon.com",
      "source_type": "major_retailer",
      "reasoning": "Large marketplace with competitive prices"
    }
  ],
  "skipped": [
    {
      "index": 5,
      "reason": "Forum, not a vendor"
    }
  ],
  "selection_summary": "Selected 4 retailers focused on {category} with good pricing"
}
```

---

## Examples

### Example 1: Electronics Purchase (Abstracted)

**Original Query:** "find me the cheapest RTX 4060 laptop"

**Search Results:**\n1. [Major electronics retailer]\n2. [Forum deals thread]\n3. [Specialty electronics retailer]\n4. [Review article]\n5. [Large marketplace]

**Output:**\n```json\n{\n  \"sources\": [\n    {\n      \"index\": 1,\n      \"url\": \"https://retailer.example/...\",\n      \"domain\": \"retailer.example\",\n      \"source_type\": \"major_retailer\",\n      \"reasoning\": \"Retail storefront with pricing and cart\"\n    },\n    {\n      \"index\": 3,\n      \"url\": \"https://specialty.example/...\",\n      \"domain\": \"specialty.example\",\n      \"source_type\": \"specialty_retailer\",\n      \"reasoning\": \"Category-focused store with product listings\"\n    },\n    {\n      \"index\": 5,\n      \"url\": \"https://market.example/...\",\n      \"domain\": \"market.example\",\n      \"source_type\": \"marketplace\",\n      \"reasoning\": \"Marketplace with broad inventory\"\n    }\n  ],\n  \"skipped\": [\n    {\n      \"index\": 2,\n      \"reason\": \"Forum, not a vendor\"\n    },\n    {\n      \"index\": 4,\n      \"reason\": \"Review article, not a store\"\n    }\n  ],\n  \"selection_summary\": \"Selected retailers that sell the requested product\"\n}\n```

---

## Output Rules

1. Return valid JSON only
2. Index values (1-based) must match input order
3. Include domain (e.g., "amazon.com") for each source
4. source_type must be one of: major_retailer, specialty_retailer, manufacturer, marketplace, comparison_site
5. Reasoning should explain why this source matches the user's goal
6. Prioritize fewer, better sources over many mediocre ones
