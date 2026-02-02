# News Extractor

**Role:** MIND (temp=0.3)
**Purpose:** Extract key information from news articles

---

## Overview

Extract structured information from news articles, press releases, and announcements.

---

## Input

```
**Extraction Goal:** {extraction_goal}
**Page URL:** {url}

**News Content:**
{content}
```

---

## Output Format

```json
{
  "headline": "Article headline",
  "publication": "Publication name",
  "date": "Publication date",
  "author": "Author name",
  "summary": "1-2 sentence summary",
  "key_facts": [
    "Important fact 1",
    "Important fact 2",
    "Important fact 3"
  ],
  "entities": {
    "companies": ["Company names mentioned"],
    "products": ["Products mentioned"],
    "people": ["People mentioned"]
  },
  "relevance_to_goal": "How this relates to the extraction goal"
}
```

---

## Extraction Rules

### 1. Identify News Structure

- Headline: Main title
- Byline: Author, publication, date
- Lead: First paragraph summary
- Body: Supporting details

### 2. Extract Key Facts

Focus on:
- Who, what, when, where, why
- Quantitative data (numbers, statistics)
- Quotes or statements

### 3. Identify Entities

- Companies/organizations
- Products/services
- People mentioned

---

## Example

**Content:**
```
TechNews Daily
January 20, 2024 | By Sarah Chen

NVIDIA Announces RTX 5000 Series

NVIDIA today announced its next-generation RTX 5000 series graphics cards,
promising 2x performance over the RTX 4000 series.

The RTX 5090 will launch at $1,999 in February, followed by the RTX 5080
at $999 in March. CEO Jensen Huang called it "the biggest generational leap
in gaming graphics."

Dell and HP have already announced laptops featuring the new GPUs.
```

**Output:**
```json
{
  "headline": "NVIDIA Announces RTX 5000 Series",
  "publication": "TechNews Daily",
  "date": "January 20, 2024",
  "author": "Sarah Chen",
  "summary": "NVIDIA announced RTX 5000 series graphics cards with 2x performance improvement, launching RTX 5090 at $1,999 in February.",
  "key_facts": [
    "RTX 5000 series promises 2x performance over RTX 4000",
    "RTX 5090 launches February 2024 at $1,999",
    "RTX 5080 launches March 2024 at $999"
  ],
  "entities": {
    "companies": ["NVIDIA", "Dell", "HP"],
    "products": ["RTX 5000", "RTX 5090", "RTX 5080", "RTX 4000"],
    "people": ["Jensen Huang"]
  },
  "relevance_to_goal": "Provides information about new GPU releases and pricing"
}
```

---

## Output Rules

1. Return valid JSON only
2. Use null for unavailable metadata (date, author)
3. key_facts should be 3-5 items
4. entities can have empty arrays if none found
5. summary should be 1-2 sentences max
