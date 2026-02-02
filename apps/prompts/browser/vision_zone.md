# Vision Zone Extractor

**Role:** REFLEX (temp=0.1)
**Purpose:** Extract items from OCR text blocks within a page zone

---

## Overview

Given OCR text blocks from a specific zone on a retail page, extract structured items. Each text block has coordinates (top, left) indicating its position on the page.

---

## Input

```
**Zone Type:** {zone_type}
**Extraction Goal:** {extraction_goal}

**Text blocks (format: [top,left] text):**
[100,50] ASUS TUF Gaming
[100,200] $899.99
[100,350] 4.5 stars
[150,50] Lenovo Legion 5
[150,200] $949.00
...
```

---

## Output Format

Return ONLY a JSON array of items:

```json
[
  {
    "title": "ASUS TUF Gaming",
    "price": "$899.99",
    "rating": "4.5 stars"
  },
  {
    "title": "Lenovo Legion 5",
    "price": "$949.00",
    "rating": null
  }
]
```

---

## Extraction Strategy

### 1. Group by Y Coordinate (Row)

Text blocks with similar `top` values are on the same row:
- [100,50] and [100,200] are on the same row (both top=100)
- [150,50] is on a different row (top=150)

### 2. Identify Item Boundaries

Each item typically spans:
- One or more rows
- Title usually leftmost and/or first row
- Price usually has $ symbol
- Rating may have "stars" or star symbol

### 3. Field Recognition

| Field | Patterns |
|-------|----------|
| title | Longest text, brand names, model numbers |
| price | $XXX.XX, $X,XXX.XX |
| rating | X.X stars, X/5, (XXX reviews) |
| availability | In Stock, Ships in X days |

---

## Zone Types

The zone_type tells you what kind of content to expect:

| Zone Type | Content | Focus |
|-----------|---------|-------|
| `product_grid` | Multiple product cards | Extract all visible products |
| `search_results` | Search result list | Extract product listings |
| `featured` | Featured/promoted items | Extract highlighted items |
| `related` | Related/similar products | Extract secondary items |
| `category` | Category/brand listing | Extract category items |

---

## Examples

### Example 1: Product Grid

**Zone Type:** product_grid
**Extraction Goal:** Extract laptops from search results

**Text blocks:**
```
[80,50] ASUS TUF Gaming A15
[80,300] RTX 4060
[100,50] $899.99
[100,200] In Stock
[100,350] 4.5 stars (234)
[200,50] Lenovo Legion 5
[200,300] RTX 4060
[220,50] $949.00
[220,350] 4.3 stars (189)
```

**Output:**
```json
[
  {
    "title": "ASUS TUF Gaming A15 RTX 4060",
    "price": "$899.99",
    "rating": "4.5 stars (234)"
  },
  {
    "title": "Lenovo Legion 5 RTX 4060",
    "price": "$949.00",
    "rating": "4.3 stars (189)"
  }
]
```

### Example 2: Sparse Data

**Zone Type:** search_results
**Extraction Goal:** Extract products

**Text blocks:**
```
[50,100] HP Victus 16
[70,100] $749
[150,100] Dell G15
[170,100] $829.99
```

**Output:**
```json
[
  {
    "title": "HP Victus 16",
    "price": "$749",
    "rating": null
  },
  {
    "title": "Dell G15",
    "price": "$829.99",
    "rating": null
  }
]
```

---

## Handling Noise

Ignore text that is clearly UI elements:
- "Add to Cart", "Buy Now"
- "Sort by", "Filter"
- "Page 1 of 5"
- Navigation items

---

## Output Rules

1. Return ONLY a JSON array - no explanation
2. Every item must have at least a `title`
3. Use `null` for missing optional fields (price, rating)
4. Combine related text blocks into meaningful titles
5. Include currency symbol in price field
