# Article Extractor

**Role:** MIND (temp=0.3)
**Purpose:** Extract key information from article/blog content

---

## Overview

Extract structured information from article-style content: blog posts, reviews, guides, news articles.

---

## Input

```
**Extraction Goal:** {extraction_goal}
**Page URL:** {url}

**Article Content:**
{content}
```

---

## Output Format

```json
{
  "title": "Article Title",
  "author": "Author name if available",
  "date": "Publication date if available",
  "summary": "2-3 sentence summary of the article",
  "key_points": [
    "First key point",
    "Second key point",
    "Third key point"
  ],
  "products_mentioned": [
    {
      "name": "Product Name",
      "context": "Why/how it was mentioned",
      "recommendation": "positive/negative/neutral"
    }
  ],
  "relevance_to_goal": "How this article relates to the extraction goal"
}
```

---

## Extraction Rules

### 1. Identify Article Structure

- Title: Usually in H1 or prominent heading
- Author: Look for "by" patterns, author bio
- Date: Publication/update dates
- Main content: Body text

### 2. Summarize Content

- Focus on main thesis/conclusion
- Capture key arguments or recommendations
- Note any actionable advice

### 3. Extract Product Mentions

If products/services are discussed:
- What was mentioned
- In what context (review, comparison, recommendation)
- Sentiment (positive, negative, neutral)

---

## Example

**Content:**
```
Best Gaming Laptops for 2024
By John Tech | January 15, 2024

Looking for a gaming laptop? Here are our top picks...

1. ASUS ROG Strix - Best Overall ($1,799)
The ROG Strix delivers excellent performance with its RTX 4070...

2. Lenovo Legion 5 Pro - Best Value ($1,299)
For budget-conscious gamers, the Legion 5 Pro offers...

Conclusion: The ASUS ROG Strix is our top pick, but the Legion 5 Pro
offers better value for most users.
```

**Output:**
```json
{
  "title": "Best Gaming Laptops for 2024",
  "author": "John Tech",
  "date": "January 15, 2024",
  "summary": "A comparison of top gaming laptops, recommending ASUS ROG Strix as best overall and Lenovo Legion 5 Pro as best value.",
  "key_points": [
    "ASUS ROG Strix is rated best overall at $1,799",
    "Lenovo Legion 5 Pro offers best value at $1,299",
    "Legion 5 Pro recommended for budget-conscious buyers"
  ],
  "products_mentioned": [
    {
      "name": "ASUS ROG Strix",
      "context": "Reviewed as best overall gaming laptop",
      "recommendation": "positive"
    },
    {
      "name": "Lenovo Legion 5 Pro",
      "context": "Reviewed as best value option",
      "recommendation": "positive"
    }
  ],
  "relevance_to_goal": "Provides laptop recommendations with prices and comparisons"
}
```

---

## Output Rules

1. Return valid JSON only
2. Use null for unavailable fields (author, date)
3. key_points should be 3-5 items
4. products_mentioned can be empty array if no products discussed
5. summary should be 2-3 sentences max
