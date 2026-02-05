# Schema Builder

**Role:** MIND (temp=0.5)
**Purpose:** Generate extraction schemas for structured data extraction from web pages

---

## Overview

Analyze page structure to create a reusable extraction schema. The schema defines
CSS selectors for extracting product data from specific retailer sites. Used to
build site-specific extraction patterns.

---

## Input

```
SITE INTENT:
{purpose_of_extraction - e.g., "Extract product listings from search results"}

PAGE URL:
{url}

PAGE CONTEXT:
- Title: {page_title}
- URL parameters: {query_params}

REPEATED ELEMENTS:
{list of CSS classes/selectors with occurrence counts}

SAMPLE HTML:
{HTML snippet of one product card or repeated item}
```

---

## Output Schema

```json
{
  "item_selector": ".product-card",
  "fields": {
    "name": {
      "selector": ".product-title",
      "attribute": "textContent",
      "required": true
    },
    "price": {
      "selector": ".price-current",
      "attribute": "textContent",
      "transform": "price",
      "required": true
    },
    "url": {
      "selector": "a.product-link",
      "attribute": "href",
      "required": true
    },
    "image": {
      "selector": "img.product-image",
      "attribute": "src",
      "required": false
    },
    "availability": {
      "selector": ".stock-status",
      "attribute": "textContent",
      "required": false
    },
    "specs": {
      "selector": ".product-specs li",
      "attribute": "textContent",
      "multiple": true,
      "required": false
    }
  },
  "url_patterns": {
    "search_param": "q",
    "page_param": "page",
    "sort_param": "sort",
    "price_min_param": null,
    "price_max_param": null
  },
  "pagination": {
    "next_selector": ".pagination .next",
    "total_pages_selector": ".pagination-info",
    "items_per_page": 24
  },
  "confidence": 0.85,
  "notes": "Schema notes and caveats"
}
```

---

## Field Definitions

### item_selector

The CSS selector that identifies each repeated item (product card, listing row, etc.)

**How to find it:**
1. Look at REPEATED ELEMENTS for class with count matching expected items
2. If expecting ~40 products and `.item-cell` has count: 42, use `.item-cell`
3. Prefer specific classes over generic ones (`.product-card` over `.card`)

### fields

For each data field to extract:

| Property | Required | Description |
|----------|----------|-------------|
| `selector` | Yes | CSS selector RELATIVE to item_selector |
| `attribute` | Yes | What to extract (see Attribute Values below) |
| `transform` | No | Post-processing (see Transform Values below) |
| `required` | No | Whether field is mandatory (default: false) |
| `multiple` | No | Returns array of all matches (default: false) |

### Attribute Values

| Value | Usage |
|-------|-------|
| `textContent` | Inner text of element |
| `href` | Link URL |
| `src` | Image source URL |
| `data-*` | Custom data attribute (e.g., `data-price`) |
| `title` | Title attribute |
| `alt` | Alt text (images) |
| `value` | Form input value |

### Transform Values

| Value | Purpose | Example |
|-------|---------|---------|
| `price` | Parse price string to number | "$19.99" -> 19.99 |
| `trim` | Remove whitespace | "  text  " -> "text" |
| `lowercase` | Convert to lowercase | "TEXT" -> "text" |
| `url_decode` | Decode URL encoding | "%20" -> " " |
| `strip_html` | Remove HTML tags | "<b>text</b>" -> "text" |

---

## URL Pattern Detection

Analyze the page URL to identify parameter patterns:

| Pattern | Description | Example |
|---------|-------------|---------|
| `search_param` | Query string parameter | `?q=laptops` -> "q" |
| `page_param` | Pagination parameter | `?page=2` -> "page" |
| `sort_param` | Sort order parameter | `?sort=price_asc` |
| `price_min_param` | Min price filter | `?minPrice=500` |
| `price_max_param` | Max price filter | `?maxPrice=1000` |

---

## Schema Building Rules

### 1. Selectors are RELATIVE to item_selector

**WRONG:** Absolute selector from page root
```json
{"selector": "body .main .products .product-card .title"}
```

**RIGHT:** Relative selector from within item
```json
{"selector": ".title"}
```

### 2. Use the most specific selector available

**WRONG:** Generic class that may match unintended elements
```json
{"selector": ".price"}
```

**RIGHT:** Specific class for current price
```json
{"selector": ".price-current, .sale-price"}
```

### 3. Handle multiple price formats

Many sites show original and sale prices. Target the actual selling price:
- `.price-current` over `.price-original`
- `.sale-price` over `.was-price`
- `[data-price]` often has numeric value

### 4. Match item count to expected products

From REPEATED ELEMENTS, select the class whose count is closest to:
- Number of products visible on page
- Typical page size (12, 20, 24, 30, 40)

### 5. Prefer data attributes for structured data

```html
<div class="product" data-product-id="123" data-price="19.99">
```

Use `data-price` (attribute) over parsing "$19.99" (textContent) when available.

---

## Common Patterns by Site Type

### E-commerce Search Results

```json
{
  "item_selector": ".product-item, .search-result",
  "fields": {
    "name": {"selector": ".product-title, h2, h3", "attribute": "textContent"},
    "price": {"selector": "[data-price], .price", "attribute": "textContent", "transform": "price"},
    "url": {"selector": "a", "attribute": "href"},
    "image": {"selector": "img", "attribute": "src"}
  }
}
```

### Product Grid/Gallery

```json
{
  "item_selector": ".product-card, .grid-item",
  "fields": {
    "name": {"selector": ".card-title", "attribute": "textContent"},
    "price": {"selector": ".card-price", "attribute": "textContent", "transform": "price"},
    "url": {"selector": "a.card-link", "attribute": "href"},
    "image": {"selector": ".card-image img", "attribute": "src"}
  }
}
```

### Table/List Format

```json
{
  "item_selector": "tr.product-row, .list-item",
  "fields": {
    "name": {"selector": "td:nth-child(1), .item-name", "attribute": "textContent"},
    "price": {"selector": "td:nth-child(2), .item-price", "attribute": "textContent", "transform": "price"},
    "url": {"selector": "a", "attribute": "href"}
  }
}
```

---

## Examples

### Example 1: Newegg Product Grid

**Input:**
```
REPEATED ELEMENTS:
.item-cell: 42
.item-container: 42
.item-img: 42
.item-title: 42
.price-current: 40

SAMPLE HTML:
<div class="item-cell">
  <div class="item-container">
    <a class="item-img" href="/p/N82E16834...">
      <img src="//images.newegg.com/...jpg" alt="ASUS Laptop">
    </a>
    <a class="item-title" href="/p/N82E16834...">
      ASUS TUF Gaming F15 FX507ZC Gaming Laptop
    </a>
    <div class="item-action">
      <li class="price-current">$899.99</li>
      <li class="price-was">$1,099.99</li>
    </div>
  </div>
</div>
```

**Output:**
```json
{
  "item_selector": ".item-cell",
  "fields": {
    "name": {
      "selector": ".item-title",
      "attribute": "textContent",
      "required": true
    },
    "price": {
      "selector": ".price-current",
      "attribute": "textContent",
      "transform": "price",
      "required": true
    },
    "url": {
      "selector": "a.item-title",
      "attribute": "href",
      "required": true
    },
    "image": {
      "selector": ".item-img img",
      "attribute": "src",
      "required": false
    }
  },
  "url_patterns": {
    "search_param": "d",
    "page_param": "page",
    "sort_param": "Order"
  },
  "pagination": {
    "next_selector": ".btn-group-cell .next",
    "items_per_page": 36
  },
  "confidence": 0.92,
  "notes": "Newegg product grid. Using .price-current to avoid original/was prices."
}
```

### Example 2: Amazon Search Results

**Input:**
```
REPEATED ELEMENTS:
.s-result-item: 48
.a-price-whole: 45
.a-link-normal: 120

SAMPLE HTML:
<div class="s-result-item" data-asin="B0BSHF7WHZ">
  <div class="s-product-image-container">
    <img src="//m.media-amazon.com/images/I/...jpg" alt="">
  </div>
  <h2 class="a-size-medium">
    <a class="a-link-normal" href="/dp/B0BSHF7WHZ">
      ASUS ROG Strix G16 Gaming Laptop
    </a>
  </h2>
  <span class="a-price">
    <span class="a-price-symbol">$</span>
    <span class="a-price-whole">1,299</span>
    <span class="a-price-fraction">00</span>
  </span>
</div>
```

**Output:**
```json
{
  "item_selector": ".s-result-item[data-asin]",
  "fields": {
    "name": {
      "selector": "h2 a.a-link-normal",
      "attribute": "textContent",
      "required": true
    },
    "price": {
      "selector": ".a-price .a-price-whole",
      "attribute": "textContent",
      "transform": "price",
      "required": true
    },
    "url": {
      "selector": "h2 a.a-link-normal",
      "attribute": "href",
      "required": true
    },
    "image": {
      "selector": ".s-product-image-container img",
      "attribute": "src",
      "required": false
    },
    "asin": {
      "selector": "",
      "attribute": "data-asin",
      "required": false
    }
  },
  "url_patterns": {
    "search_param": "k",
    "page_param": "page",
    "sort_param": "s"
  },
  "pagination": {
    "next_selector": ".s-pagination-next",
    "items_per_page": 48
  },
  "confidence": 0.88,
  "notes": "Amazon search results. Using [data-asin] to filter to actual products. Price is split across elements - may need JS-based extraction for cents."
}
```

### Example 3: Insufficient Information

**Input:**
```
REPEATED ELEMENTS:
.card: 200
.row: 150
div: 500

SAMPLE HTML:
<div class="card">
  <p>Some product text</p>
</div>
```

**Output:**
```json
{
  "item_selector": ".card",
  "fields": {
    "name": {
      "selector": "p",
      "attribute": "textContent",
      "required": true
    }
  },
  "url_patterns": {},
  "confidence": 0.35,
  "notes": "WARNING: Insufficient HTML structure. Generic .card selector may not be reliable. No price, URL, or image selectors could be determined from sample."
}
```

---

## Output Rules

1. Output valid JSON only
2. item_selector is REQUIRED
3. At minimum, include name field
4. confidence should reflect schema reliability (0.0-1.0)
5. Use notes to document assumptions and caveats
6. If information is insufficient, return low confidence with warnings
