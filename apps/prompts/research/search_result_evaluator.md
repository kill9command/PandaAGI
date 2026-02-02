# Search Result Evaluator

**Role:** REFLEX (temp=0.2)
**Purpose:** Evaluate search result quality to determine if additional queries are needed

---

## Overview

Assess the quality and completeness of search results to decide whether the
research goal has been satisfied or if additional searches are needed.

---

## Input

```
RESEARCH GOAL:
{goal}

REQUIRED FIELDS:
{required_fields}

SEARCH RESULTS SUMMARY:
{results_summary}
```

---

## Output Schema

```json
{
  "satisfied": true,
  "quality_score": 0.85,
  "gaps": "Description of what's missing",
  "recommendation": "continue | stop",
  "suggested_refinements": [
    "Add pricing keywords",
    "Try specific retailer"
  ]
}
```

---

## Evaluation Criteria

### 1. Result Count Assessment

| Count | Score Contribution | Action |
|-------|-------------------|--------|
| 0 results | -0.4 | Definitely continue, try different query |
| 1-2 results | -0.2 | Likely continue, need more variety |
| 3-5 results | +0.1 | Acceptable, may stop if quality good |
| 5+ results | +0.2 | Good variety, stop if relevant |

### 2. Required Field Coverage

For each required field, check if it's present in results:

| Field | Found in | Score Impact |
|-------|----------|--------------|
| Title | Result title | +0.1 |
| URL/Link | Result link | +0.1 |
| Price | Snippet mentions $, price, cost | +0.15 |
| Availability | Snippet mentions stock, shipping | +0.1 |

**Field Coverage Score = (fields_found / fields_required) * 0.4**

### 3. Source Diversity

| Diversity | Score Impact |
|-----------|--------------|
| 3+ unique domains | +0.1 |
| Mix of retailer types | +0.1 |
| Only 1 domain | -0.1 |

### 4. Relevance Signals

Check snippets for relevance to goal:

| Signal | Score Impact |
|--------|--------------|
| Product keywords match | +0.1 |
| Transactional words (buy, shop, price) | +0.1 |
| Irrelevant content (reviews only, forums) | -0.1 |

---

## Quality Thresholds

| Score | Interpretation | Recommendation |
|-------|----------------|----------------|
| >= 0.8 | High quality | STOP - results sufficient |
| 0.6 - 0.79 | Acceptable | STOP - unless specific gaps |
| 0.4 - 0.59 | Marginal | CONTINUE - try refined query |
| < 0.4 | Poor | CONTINUE - significantly different query |

---

## Refinement Suggestions

When quality is low, suggest specific improvements:

### For Low Result Count
- "Try broader keywords"
- "Remove restrictive filters"
- "Try alternative product names"

### For Missing Pricing
- "Add 'price' or 'buy' to query"
- "Add 'for sale' keyword"
- "Try specific retailer name"

### For Poor Relevance
- "Add more specific product attributes"
- "Remove ambiguous terms"
- "Try exact product model name"

### For Low Diversity
- "Try different search engine"
- "Add retailer-specific query"
- "Try shopping-focused search"

---

## Examples

### Example 1: Good Results

**Goal:** Find RTX 4060 laptops under $1000

**Results:**
1. Best Buy - RTX 4060 Gaming Laptops from $849
2. Newegg - Shop RTX 4060 Laptops on Sale
3. Amazon - RTX 4060 Gaming Laptop Deals
4. Walmart - Budget Gaming Laptops with RTX 4060
5. Dell - Inspiron Gaming with RTX 4060

**Evaluation:**
```json
{
  "satisfied": true,
  "quality_score": 0.88,
  "gaps": "No significant gaps",
  "recommendation": "stop",
  "suggested_refinements": []
}
```

### Example 2: Poor Results

**Goal:** Find Syrian hamster breeders

**Results:**
1. Wikipedia - Syrian hamster
2. Reddit - Hamster care tips
3. PetSmart - Hamster supplies

**Evaluation:**
```json
{
  "satisfied": false,
  "quality_score": 0.35,
  "gaps": "No results from actual breeders or sellers. Only informational and supply results.",
  "recommendation": "continue",
  "suggested_refinements": [
    "Add 'for sale' or 'breeder' to query",
    "Try 'Syrian hamster breeder near me'",
    "Search for specific hamstery names"
  ]
}
```

### Example 3: Marginal Results

**Goal:** Buy wireless gaming headset

**Results:**
1. Amazon - Wireless Gaming Headsets
2. Tom's Guide - Best Wireless Gaming Headsets 2026

**Evaluation:**
```json
{
  "satisfied": false,
  "quality_score": 0.52,
  "gaps": "Only 1 retail source. Second result is a review site.",
  "recommendation": "continue",
  "suggested_refinements": [
    "Try broader or alternative keywords",
    "Add 'Best Buy' or 'Newegg' to query for more retail results"
  ]
}
```

---

## Output Rules

1. Return valid JSON only
2. quality_score must be between 0.0 and 1.0
3. recommendation must be exactly "continue" or "stop"
4. gaps should be empty string if none, not null
5. suggested_refinements should be empty array if satisfied
