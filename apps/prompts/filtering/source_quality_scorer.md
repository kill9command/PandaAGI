# Source Quality Scorer

**Role:** REFLEX (temp=0.1)
**Purpose:** Score search results for source quality and relevance

---

## Overview

Evaluate search result candidates for source quality based on:
1. Source type (official, expert, forum, vendor, etc.)
2. Likely information quality
3. Relevance to the user's goal

This scoring helps prioritize which sources to visit during research.

---

## Input

```
**Goal:** {goal}
**Original query:** {query}
**Key requirements:** {requirements}

**Candidates:**
1. URL: https://...
   Title: ...
   Snippet: ...
2. URL: ...
   ...
```

---

## Output Format

Return a JSON object with a `results` array:

```json
{
  "results": [
    {
      "index": 1,
      "source_type": "vendor",
      "llm_quality_score": 0.85,
      "confidence": 0.9,
      "reasoning": "Major retailer, likely has accurate product data"
    },
    {
      "index": 2,
      "source_type": "forum",
      "llm_quality_score": 0.70,
      "confidence": 0.8,
      "reasoning": "Community forum, good for opinions but verify facts"
    }
  ]
}
```

---

## Source Types

Classify each result into one of:

| Source Type | Description | Typical Quality |
|-------------|-------------|-----------------|
| `official` | Official brand/manufacturer site | High |
| `expert_review` | Professional review site (Tom's, CNET, etc.) | High |
| `forum` | Community discussion (Reddit, forums) | Medium |
| `vendor` | Retail/shopping site (Amazon, Best Buy) | High for product data |
| `news` | News article | Medium |
| `video` | Video content (YouTube) | Variable |
| `social` | Social media | Low |
| `unknown` | Can't determine | Low |

---

## Quality Scoring Guidelines

### 0.9 - 1.0: Excellent

- Official product pages
- Professional review sites
- Authoritative sources

### 0.7 - 0.89: Good

- Major retailers
- Well-known forums
- Expert blogs

### 0.5 - 0.69: Acceptable

- General forums
- Community Q&A sites
- User blogs

### 0.3 - 0.49: Questionable

- Unknown sources
- Content farms
- Aggregator sites

### 0.0 - 0.29: Poor

- Spam-like domains
- Unrelated content
- Clickbait sites

---

## Relevance Considerations

When scoring, consider:

1. **Goal Match**: Does the source likely have info for this goal?
   - "buy laptop" -> vendor sites score higher
   - "learn about laptops" -> review/forum sites score higher

2. **Content Type**: What kind of info does this source provide?
   - Product listings: vendors
   - Opinions/experiences: forums
   - Specifications: manufacturers

3. **Currency**: Is the info likely current?
   - News from today > article from 2 years ago
   - Active forum > dead forum

---

## Examples

### Example 1: Shopping Goal

**Goal:** "Find cheapest RTX 4060 laptop"

**Candidate:** "Best Buy - RTX 4060 Laptops on Sale"

```json
{
  "index": 1,
  "source_type": "vendor",
  "llm_quality_score": 0.90,
  "confidence": 0.95,
  "reasoning": "Major electronics retailer, reliable for current prices and availability"
}
```

### Example 2: Research Goal

**Goal:** "Understand RTX 4060 laptop performance"

**Candidate:** "Tom's Hardware - RTX 4060 Laptop Benchmarks"

```json
{
  "index": 1,
  "source_type": "expert_review",
  "llm_quality_score": 0.95,
  "confidence": 0.9,
  "reasoning": "Professional tech review site with benchmark data"
}
```

### Example 3: Low Quality Source

**Goal:** "Buy gaming laptop"

**Candidate:** "Top 10 Gaming Laptops You Won't Believe - ClickHere.biz"

```json
{
  "index": 1,
  "source_type": "unknown",
  "llm_quality_score": 0.20,
  "confidence": 0.8,
  "reasoning": "Clickbait title pattern, unknown domain, likely low-quality content"
}
```

---

## Output Rules

1. Return valid JSON with `results` array
2. Index values (1-based) must match input candidate order
3. Every candidate must have a score
4. source_type must be one of the defined types
5. llm_quality_score between 0.0 and 1.0
6. confidence between 0.0 and 1.0
7. reasoning should explain the score
