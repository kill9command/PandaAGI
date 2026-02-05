# Prose Intelligence Extractor

**Role:** MIND (temp=0.3)
**Purpose:** Extract structured information from prose/unstructured content

---

## Overview

Given unstructured page content (prose descriptions, mixed text), extract intelligence about products, services, or offerings. Used when there's no clear product grid.

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

Return JSON with extracted intelligence:

```json
{
  "items": [
    {
      "title": "Product/Service Name",
      "description": "Key description",
      "price": "$XXX or 'Contact for price'",
      "availability": "Available now / Contact required",
      "contact": "Email/phone if mentioned",
      "confidence": 0.8
    }
  ],
  "page_summary": "Brief summary of what this page offers",
  "extraction_notes": "Any caveats about extraction quality"
}
```

---

## Extraction Rules

### 1. Identify Offerings

Look for:
- Named products or services
- Things being sold, offered, or available
- Items with associated prices or "contact for price"

### 2. Extract Key Details

For each offering:
- **title**: Name of the item/service
- **description**: Key attributes, features, specs
- **price**: Explicit price or "Contact for price" if mentioned
- **availability**: When/how it's available
- **contact**: How to inquire (if mentioned)

### 3. Handle Prose Patterns

Common patterns in unstructured content:
- "We have X available for $Y"
- "Contact us for pricing on X"
- "Currently offering X"
- "X - Description. Price: $Y"

---

## Examples

### Example 1: Breeder Site

**Content:**
```
We currently have Syrian hamster babies available! Our golden long-hair
Syrians are $25 each. Please email us at breeder@example.com for availability.
We also have satin coat Syrians available - contact for pricing.
```

**Output:**
```json
{
  "items": [
    {
      "title": "Syrian Hamster - Golden Long-Hair",
      "description": "Baby Syrian hamster, golden long-hair coat",
      "price": "$25",
      "availability": "Available now",
      "contact": "breeder@example.com",
      "confidence": 0.9
    },
    {
      "title": "Syrian Hamster - Satin Coat",
      "description": "Satin coat Syrian hamster",
      "price": "Contact for price",
      "availability": "Available",
      "contact": "breeder@example.com",
      "confidence": 0.8
    }
  ],
  "page_summary": "Breeder offering Syrian hamsters, both priced and contact-for-price options",
  "extraction_notes": "Satin coat pricing not listed"
}
```

### Example 2: Service Page

**Content:**
```
Our web design packages start at $999. We offer basic, pro, and enterprise tiers.
Basic ($999): 5 pages, responsive design
Pro ($2499): 10 pages, custom graphics, SEO
Enterprise: Contact us for custom pricing
```

**Output:**
```json
{
  "items": [
    {
      "title": "Basic Web Design Package",
      "description": "5 pages, responsive design",
      "price": "$999",
      "availability": "Available",
      "contact": null,
      "confidence": 0.95
    },
    {
      "title": "Pro Web Design Package",
      "description": "10 pages, custom graphics, SEO",
      "price": "$2499",
      "availability": "Available",
      "contact": null,
      "confidence": 0.95
    },
    {
      "title": "Enterprise Web Design Package",
      "description": "Custom pricing",
      "price": "Contact for price",
      "availability": "Available",
      "contact": null,
      "confidence": 0.85
    }
  ],
  "page_summary": "Web design service with tiered pricing",
  "extraction_notes": "Enterprise pricing requires inquiry"
}
```

---

## Output Rules

1. Return valid JSON only
2. Always include `items` array (can be empty)
3. Confidence: 0.9+ for explicit data, 0.7-0.89 for inferred, 0.5-0.69 for uncertain
4. Use null for missing optional fields
5. page_summary should be one sentence
