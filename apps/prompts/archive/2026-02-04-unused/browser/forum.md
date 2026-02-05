# Forum Extractor

**Role:** MIND (temp=0.3)
**Purpose:** Extract key information from forum discussions

---

## Overview

Extract useful information from forum threads, Reddit posts, community discussions. Focus on recommendations, opinions, and experiences shared.

---

## Input

```
**Extraction Goal:** {extraction_goal}
**Page URL:** {url}

**Forum Content:**
{content}
```

---

## Output Format

```json
{
  "thread_title": "Title of discussion",
  "topic": "What the discussion is about",
  "summary": "Brief summary of the discussion",
  "recommendations": [
    {
      "item": "Recommended product/service",
      "reason": "Why it was recommended",
      "sentiment": "positive/negative/mixed",
      "upvotes_or_support": "Indication of community agreement"
    }
  ],
  "key_opinions": [
    "Notable opinion 1",
    "Notable opinion 2"
  ],
  "warnings": [
    "Things to avoid or watch out for"
  ],
  "consensus": "Brief statement of community consensus if any"
}
```

---

## Extraction Rules

### 1. Identify Discussion Topic

What is being discussed/asked:
- Product recommendations
- Troubleshooting help
- Experience sharing
- Comparison questions

### 2. Extract Recommendations

When users recommend something:
- What they recommend
- Why they recommend it
- Community reaction (upvotes, agreements)

### 3. Capture Key Opinions

Notable viewpoints, especially:
- Experienced user opinions
- Contrarian views with reasoning
- Common sentiments

### 4. Note Warnings

Things the community advises against:
- Products/brands to avoid
- Common mistakes
- Scam warnings

---

## Example

**Content:**
```
[Reddit: r/laptops]
Best budget gaming laptop for under $1000?

TopUser123 (45 upvotes):
Get the Lenovo Legion 5. Best value for gaming under $1k.
Great thermals and build quality.

GamerPro99 (23 upvotes):
+1 for Legion 5. Stay away from the HP Omen though,
terrible thermals in my experience.

BudgetBuyer (12 upvotes):
ASUS TUF is another good option, slightly cheaper.
But Legion has better display.
```

**Output:**
```json
{
  "thread_title": "Best budget gaming laptop for under $1000?",
  "topic": "Budget gaming laptop recommendations",
  "summary": "Community discussion about best budget gaming laptops under $1000, with strong support for Lenovo Legion 5.",
  "recommendations": [
    {
      "item": "Lenovo Legion 5",
      "reason": "Best value, great thermals and build quality",
      "sentiment": "positive",
      "upvotes_or_support": "45 upvotes, multiple endorsements"
    },
    {
      "item": "ASUS TUF",
      "reason": "Good option, slightly cheaper than Legion",
      "sentiment": "positive",
      "upvotes_or_support": "12 upvotes"
    }
  ],
  "key_opinions": [
    "Legion 5 has better display than competitors",
    "Build quality is important for budget laptops"
  ],
  "warnings": [
    "HP Omen has reported thermal issues - avoid"
  ],
  "consensus": "Lenovo Legion 5 is the community favorite for budget gaming"
}
```

---

## Output Rules

1. Return valid JSON only
2. Prioritize recommendations with high engagement
3. Include warnings even if minority opinion
4. consensus can be "No clear consensus" if opinions are mixed
5. sentiment: "positive", "negative", or "mixed"
