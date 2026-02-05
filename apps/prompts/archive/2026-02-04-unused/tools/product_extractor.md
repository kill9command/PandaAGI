# Product Extractor

**Role:** MIND (temp=0.5)
**Purpose:** Extract structured product data from retailer pages

---

## Overview

Extract product information from retailer page content. Handle varying page formats
(search listings, product detail pages) and output standardized product objects.

---

## Input

```
EXTRACTION GOAL:
{what_to_find}

PAGE URL:
{url}

PAGE CONTENT:
{sanitized_page_text}

USER REQUIREMENTS:
{user_requirements_from_query}
```

---

## Output Schema

```json
{
  "products": [
    {
      "name": "Full product name from listing",
      "price": "$799.99",
      "price_numeric": 799.99,
      "currency": "USD",
      "url": "https://...",
      "image_url": "https://... or null",
      "availability": "in_stock | out_of_stock | limited | preorder | unknown",
      "vendor": "amazon.com",
      "specs": {
        "cpu": "Intel i5-13500H",
        "gpu": "RTX 4060",
        "ram": "16GB",
        "storage": "512GB SSD",
        "display": "15.6\" FHD 144Hz"
      },
      "confidence": 0.85,
      "extraction_notes": "optional notes about extraction quality"
    }
  ],
  "page_type": "search_results | product_detail | category_listing",
  "total_found": 12,
  "extraction_method": "llm_extraction",
  "warnings": ["list of any issues encountered"]
}
```

---

## Field Definitions

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Complete product name/title |
| `price` | string | Displayed price with currency symbol |
| `price_numeric` | float | Numeric price for comparison (e.g., 799.99) |
| `url` | string | Direct link to product (PDP or listing) |
| `availability` | enum | Stock status |
| `vendor` | string | Source retailer domain |
| `confidence` | float | 0.0-1.0 extraction confidence |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `currency` | string | ISO currency code (default: USD) |
| `image_url` | string | Product image URL |
| `specs` | object | Key-value pairs of specifications |
| `extraction_notes` | string | Notes about extraction quality |

### Specs Extraction by Domain

**Electronics:**
- CPU, GPU, RAM, Storage, Display, Battery, Weight

**Appliances:**
- Capacity, Power, Dimensions, Features, Energy Rating

**Pets:**
- Size, Material, Compatibility, Intended Species

**General:**
- Brand, Model, Color, Dimensions, Material

---

## Extraction Rules

### 1. Parse All Prices Carefully

**DO:**
- Extract current/sale price, not original price
- Handle price ranges: "$799 - $899" -> use lower price, note in extraction_notes
- Convert "From $799" to 799.99 with note
- Handle per-unit pricing: "$9.99/lb" -> include unit in notes

**DON'T:**
- Use strikethrough/crossed-out prices
- Guess prices not shown on page
- Mix different products' prices

### 2. Build Complete URLs

**DO:**
- Construct full URLs from relative paths
- Include the product URL, not search results URL
- Preserve query parameters that identify the product

**DON'T:**
- Include tracking parameters (utm_, ref=, etc.)
- Return the search page URL for all products

### 3. Extract Specs from Multiple Sources

Look for specs in:
1. Dedicated specs section/table
2. Product title (often contains key specs)
3. Bullet points/feature lists
4. Description text

**Example:** "ASUS ROG Strix G16 Gaming Laptop, 16\" QHD 165Hz, Intel Core i7-13650HX, RTX 4060, 16GB DDR5, 1TB SSD"

Extract from title:
- display: "16\" QHD 165Hz"
- cpu: "Intel Core i7-13650HX"
- gpu: "RTX 4060"
- ram: "16GB DDR5"
- storage: "1TB SSD"

### 4. Availability Detection

| Text Found | Status |
|------------|--------|
| "In Stock", "Add to Cart", "Buy Now" | `in_stock` |
| "Out of Stock", "Sold Out", "Unavailable" | `out_of_stock` |
| "Low Stock", "Only X left", "Limited" | `limited` |
| "Pre-order", "Coming Soon" | `preorder` |
| Cannot determine | `unknown` |

### 5. Confidence Scoring

| Score | Criteria |
|-------|----------|
| 0.90-1.0 | All fields extracted, clear formatting |
| 0.70-0.89 | Most fields extracted, minor ambiguity |
| 0.50-0.69 | Key fields present, some specs missing |
| 0.30-0.49 | Only basic fields (name, price), significant gaps |
| < 0.30 | Minimal data, high uncertainty |

---

## Handling Different Page Types

### Search Results Page

- Extract each product card/listing
- Specs may be limited to highlights
- URLs should link to individual product pages
- Set page_type: "search_results"

### Product Detail Page (PDP)

- Extract single product with full details
- Look for complete specs section
- URL is the current page
- Set page_type: "product_detail"

### Category Listing

- Similar to search results
- May have filters applied
- Set page_type: "category_listing"

---

## Validation Checks

Before including a product:

1. **Has minimum required fields:** name AND (price OR availability)
2. **Price is plausible:** Not $0, not obviously wrong (TV for $1)
3. **Name is specific:** Not generic category name ("Laptops")
4. **URL is valid:** Properly formed, points to product

---

## Examples

### Example 1: Search Results Extraction

**Input:**
```
EXTRACTION GOAL: RTX 4060 gaming laptops under $1000

PAGE CONTENT:
ASUS TUF Gaming F15 - RTX 4060 | Intel i7 | 16GB RAM | 512GB SSD
$899.99 | In Stock | Free Shipping
[Add to Cart]

Lenovo LOQ 15 Gaming - RTX 4060 Laptop | AMD Ryzen 7 | 16GB | 1TB
$849.00 | Low Stock | Ships in 2-3 days
[Add to Cart]

MSI Thin GF63 - RTX 4050 | Intel i5 | 8GB | 512GB
$699.99 | In Stock
[Add to Cart]
```

**Output:**
```json
{
  "products": [
    {
      "name": "ASUS TUF Gaming F15 - RTX 4060",
      "price": "$899.99",
      "price_numeric": 899.99,
      "url": "https://example.com/asus-tuf-f15-rtx4060",
      "availability": "in_stock",
      "vendor": "example.com",
      "specs": {
        "gpu": "RTX 4060",
        "cpu": "Intel i7",
        "ram": "16GB",
        "storage": "512GB SSD"
      },
      "confidence": 0.90
    },
    {
      "name": "Lenovo LOQ 15 Gaming - RTX 4060",
      "price": "$849.00",
      "price_numeric": 849.00,
      "url": "https://example.com/lenovo-loq-15-rtx4060",
      "availability": "limited",
      "vendor": "example.com",
      "specs": {
        "gpu": "RTX 4060",
        "cpu": "AMD Ryzen 7",
        "ram": "16GB",
        "storage": "1TB"
      },
      "confidence": 0.90
    },
    {
      "name": "MSI Thin GF63 - RTX 4050",
      "price": "$699.99",
      "price_numeric": 699.99,
      "url": "https://example.com/msi-thin-gf63-rtx4050",
      "availability": "in_stock",
      "vendor": "example.com",
      "specs": {
        "gpu": "RTX 4050",
        "cpu": "Intel i5",
        "ram": "8GB",
        "storage": "512GB"
      },
      "confidence": 0.85,
      "extraction_notes": "RTX 4050 not RTX 4060 - may not match user requirements"
    }
  ],
  "page_type": "search_results",
  "total_found": 3,
  "extraction_method": "llm_extraction",
  "warnings": []
}
```

### Example 2: Incomplete Data Handling

**Input:**
```
PAGE CONTENT:
Gaming Laptop Deal!
Was $1299 NOW $999
Limited time offer
```

**Output:**
```json
{
  "products": [],
  "page_type": "search_results",
  "total_found": 0,
  "extraction_method": "llm_extraction",
  "warnings": ["Insufficient product information - no product name or specs found"]
}
```

---

## Output Rules

1. Output valid JSON only
2. Include ALL products found on the page (up to 20)
3. Order by relevance to extraction goal
4. Always set page_type, total_found, extraction_method
5. Use warnings array for any extraction issues
