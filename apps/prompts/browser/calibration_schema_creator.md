# Calibration Schema Creator

**Role:** MIND (temp=0.1)
**Purpose:** Create extraction schemas for retail page product extraction

---

## Overview

Analyze page structure data to create a schema for extracting products. The schema defines CSS selectors for:
1. **Item container** - The repeating element containing each product
2. **Field selectors** - Selectors within each item for name, price, URL, image

---

## Input

```
SITE INTENT: {site_intent}

PAGE CONTEXT:
- URL: {url}
- Title: {title}
- URL Parameters: {...}
- Text with prices found: [...]

REPEATED ELEMENTS ON PAGE:
[List of repeated class patterns with counts]

SAMPLE HTML:
{html_sample}
```

---

## Output Format

Return ONLY valid JSON:

```json
{
  "item_selector": ".product-card",
  "fields": {
    "name": {
      "selector": ".product-title",
      "attribute": "text"
    },
    "price": {
      "selector": ".price-current",
      "attribute": "text"
    },
    "url": {
      "selector": "a",
      "attribute": "href"
    },
    "image": {
      "selector": "img",
      "attribute": "src"
    }
  },
  "confidence": 0.85,
  "reasoning": "Used .product-card (count: 42) matching expected product count"
}
```

---

## Schema Creation Rules

### 1. Item Selector Selection

Choose from REPEATED ELEMENTS with:
- Count between 10-100 (typical product grid size)
- Class name suggesting product/item (product, item, card, listing)
- Count closest to expected number of products

**Good candidates:**
- `.item-cell` (count: 42)
- `.product-card` (count: 36)
- `.goods-item` (count: 24)

**Bad candidates:**
- `.nav-item` (count: 8) - too few, likely navigation
- `.letter` (count: 200) - too many, likely text styling

### 2. Field Selectors

Within each item, find:

| Field | Common Selectors | Attribute |
|-------|-----------------|-----------|
| name | .title, .name, .product-name, h2, h3 | text |
| price | .price, .price-current, .sale-price, [class*="price"] | text |
| url | a[href], .item-link | href |
| image | img, .product-image img | src or data-src |

### 3. Selector Best Practices

- Use class selectors over tag-only selectors
- Prefer unique class names over generic ones
- Check sample HTML for actual class names
- Use combined selectors with commas for fallbacks: `.price, .sale-price`

---

## Attribute Types

| Attribute | When to Use |
|-----------|-------------|
| `text` | For visible text content |
| `href` | For link URLs |
| `src` | For image sources |
| `data-src` | For lazy-loaded images |
| `content` | For meta/data attributes |

---

## Handling Failures

If previous schema failed, the prompt includes:
- Previous selectors that didn't work
- Feedback about what went wrong

Use this to choose DIFFERENT selectors. Don't repeat failed patterns.

---

## Examples

### Example 1: Newegg-style Page

**Repeated Elements:**
```json
[
  {"selector": ".item-cell", "count": 42},
  {"selector": ".goods-item", "count": 42},
  {"selector": ".item-title", "count": 42}
]
```

**Sample HTML:**
```html
<div class="item-cell">
  <a class="item-title" href="/Product/...">ASUS TUF Gaming</a>
  <li class="price-current"><strong>$899</strong><sup>.99</sup></li>
  <a class="item-img"><img src="..." /></a>
</div>
```

**Output:**
```json
{
  "item_selector": ".item-cell",
  "fields": {
    "name": {"selector": ".item-title", "attribute": "text"},
    "price": {"selector": ".price-current", "attribute": "text"},
    "url": {"selector": ".item-title", "attribute": "href"},
    "image": {"selector": ".item-img img", "attribute": "src"}
  },
  "confidence": 0.90,
  "reasoning": "Clear product grid with .item-cell (42 items). Price in .price-current, title links to product."
}
```

### Example 2: Amazon-style Page

**Repeated Elements:**
```json
[
  {"selector": "[data-component-type='s-search-result']", "count": 48},
  {"selector": ".s-result-item", "count": 48}
]
```

**Output:**
```json
{
  "item_selector": ".s-result-item[data-component-type='s-search-result']",
  "fields": {
    "name": {"selector": "h2 span", "attribute": "text"},
    "price": {"selector": ".a-price .a-offscreen", "attribute": "text"},
    "url": {"selector": "h2 a", "attribute": "href"},
    "image": {"selector": ".s-image", "attribute": "src"}
  },
  "confidence": 0.85,
  "reasoning": "Amazon search results with data attributes. Price in .a-price spans."
}
```

---

## Output Rules

1. Return ONLY valid JSON - no explanation outside the JSON
2. Use selectors that actually appear in the sample HTML
3. item_selector must match one of the repeated elements
4. confidence: 0.9+ for clear patterns, 0.5-0.8 for uncertain
5. reasoning explains selector choices
