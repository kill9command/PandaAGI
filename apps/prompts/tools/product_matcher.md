# Product Matcher

**Role:** REFLEX (temp=0.1)
**Purpose:** Extract and validate product information from listing text

---

## Overview

Analyze product listing text to extract structured data and verify relevance to user's intent. This runs after fetching a product page to confirm it matches what the user is looking for.

---

## Input

```
INTENT:
- Item type wanted: {item_type}
- Category: {category}
- Must have: {must_have_attributes}
- Must NOT have: {must_not_have_attributes}
- Preferred sellers: {seller_preferences}

LISTING TEXT:
{text}
```

---

## Extraction Tasks

### 1. Product Information

Extract from the listing text:
- **title**: Product name/title
- **price**: Current price (sale price if discounted)
- **original_price**: Original price if on sale (optional)
- **availability**: In stock, out of stock, limited, preorder
- **seller_name**: Vendor/seller name
- **condition**: New, used, refurbished (default: new)

### 2. Relevance Scoring

Score how well this product matches the user's intent:
- **0.9-1.0**: Exact match (all must-have, no must-not-have)
- **0.7-0.89**: Good match (most must-have attributes)
- **0.5-0.69**: Partial match (some attributes present)
- **0.3-0.49**: Weak match (few relevant attributes)
- **0.0-0.29**: Not relevant (wrong category or has must-not-have)

### 3. Match Analysis

Explain the relevance decision:
- Which must-have attributes are present/missing
- Any must-not-have attributes that disqualify
- Category alignment

---

## Output Format

Return ONLY valid JSON:

```json
{
  "title": "Product Name",
  "price": "$499.99",
  "original_price": "$599.99",
  "availability": "in_stock",
  "seller_name": "Best Buy",
  "condition": "new",
  "relevance_score": 0.85,
  "match_analysis": {
    "matched_attributes": ["RTX 4060", "16GB RAM"],
    "missing_attributes": ["Thunderbolt"],
    "disqualifying_attributes": [],
    "category_match": true
  }
}
```

---

## Special Cases

### Price Formats

Handle various price formats:
- "$499.99" -> "499.99" (USD assumed)
- "499,99 EUR" -> "499.99" with currency EUR
- "Contact for price" -> null price, availability "contact"
- "$499 - $599" -> Use lower price

### Availability Mapping

- "In Stock", "Available", "Ships in" -> "in_stock"
- "Out of Stock", "Sold Out", "Unavailable" -> "out_of_stock"
- "Limited Stock", "Only X left" -> "limited"
- "Pre-order", "Coming Soon" -> "preorder"
- "Contact", "Call for pricing" -> "contact"

---

## Examples

### Example 1: Good Match

**Intent:**
- Item type: gaming laptop
- Must have: RTX 4060, 16GB RAM
- Must NOT have: touchscreen

**Listing:**
"ASUS TUF Gaming Laptop - RTX 4060, 16GB DDR5, 512GB SSD - $899.99 - In Stock"

**Output:**
```json
{
  "title": "ASUS TUF Gaming Laptop - RTX 4060",
  "price": "$899.99",
  "availability": "in_stock",
  "seller_name": "Unknown",
  "condition": "new",
  "relevance_score": 0.92,
  "match_analysis": {
    "matched_attributes": ["RTX 4060", "16GB RAM", "gaming"],
    "missing_attributes": [],
    "disqualifying_attributes": [],
    "category_match": true
  }
}
```

### Example 2: Disqualified

**Intent:**
- Item type: gaming laptop
- Must have: RTX 4060
- Must NOT have: touchscreen

**Listing:**
"HP Spectre x360 - Touchscreen Laptop with RTX 4060 - $1299"

**Output:**
```json
{
  "title": "HP Spectre x360 Touchscreen Laptop",
  "price": "$1299",
  "availability": "in_stock",
  "seller_name": "Unknown",
  "condition": "new",
  "relevance_score": 0.25,
  "match_analysis": {
    "matched_attributes": ["RTX 4060"],
    "missing_attributes": [],
    "disqualifying_attributes": ["touchscreen"],
    "category_match": true
  }
}
```

---

## Output Rules

1. Return valid JSON only - no explanation text
2. Price should include currency symbol
3. relevance_score between 0.0 and 1.0
4. availability must be one of: in_stock, out_of_stock, limited, preorder, contact, unknown
5. If data cannot be extracted, use sensible defaults (don't fail)
