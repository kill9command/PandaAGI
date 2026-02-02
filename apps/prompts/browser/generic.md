# Generic Extractor

**Role:** MIND (temp=0.3)
**Purpose:** Extract relevant information from any content type

---

## Overview

Fallback extractor for pages that don't match other extraction patterns. Attempts to extract any relevant information based on the extraction goal.

---

## Input

```
**Extraction Goal:** {extraction_goal}
**Page URL:** {url}

**Page Content:**
{content}
```

---

## Output Format

```json
{
  "page_type": "Best guess at page type",
  "title": "Page title or main heading",
  "summary": "Brief summary of page content",
  "relevant_items": [
    {
      "type": "product/service/info/contact",
      "name": "Item name",
      "details": "Relevant details",
      "attributes": {}
    }
  ],
  "extracted_data": {
    "prices": ["Any prices found"],
    "contacts": ["Any contact info found"],
    "dates": ["Any relevant dates"]
  },
  "confidence": 0.7,
  "extraction_notes": "Notes about extraction quality"
}
```

---

## Extraction Approach

### 1. Identify Page Purpose

What kind of page is this:
- Product listing
- Information page
- Contact page
- Article/blog
- Directory
- Mixed content

### 2. Find Relevant Content

Based on the extraction goal, find:
- Items/products/services mentioned
- Prices or pricing information
- Contact methods
- Key facts or data

### 3. Structure What You Find

Even if unstructured, try to organize:
- Group related information
- Note confidence level
- Flag uncertainties

---

## Example

**Extraction Goal:** "Find hamsters for sale"

**Content:**
```
Welcome to Local Pet Shop!
We carry a variety of small pets.
Currently in stock: rabbits, guinea pigs, hamsters.
Prices start at $15. Visit us at 123 Main St or call (555) 123-4567.
Store hours: Mon-Sat 10am-6pm
```

**Output:**
```json
{
  "page_type": "Pet store homepage",
  "title": "Local Pet Shop",
  "summary": "Local pet store carrying small pets including hamsters",
  "relevant_items": [
    {
      "type": "product",
      "name": "Hamsters",
      "details": "Currently in stock, prices start at $15",
      "attributes": {
        "availability": "in stock",
        "starting_price": "$15"
      }
    }
  ],
  "extracted_data": {
    "prices": ["$15 (starting price)"],
    "contacts": ["(555) 123-4567", "123 Main St"],
    "dates": []
  },
  "confidence": 0.75,
  "extraction_notes": "General store page, hamsters mentioned but no specific details"
}
```

---

## Output Rules

1. Return valid JSON only
2. Always include confidence (0.0-1.0)
3. relevant_items can be empty if nothing matches goal
4. page_type should be descriptive (e.g., "E-commerce product page")
5. extraction_notes should explain any limitations
