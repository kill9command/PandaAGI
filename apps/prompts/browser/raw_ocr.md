# Raw OCR Extractor

**Role:** REFLEX (temp=0.2)
**Purpose:** Extract product information from raw, ungrouped OCR text

---

## Overview

Given raw OCR text from a retail page (not pre-grouped), find and extract products for sale. This is a fallback when spatial grouping fails.

---

## Input

```
**User's Search Query:** "{query}"

**Raw OCR Text:**
ASUS TUF Gaming A15 RTX 4060 $899.99 In Stock Add to Cart Lenovo Legion 5 RTX 4060 $949.00 Ships in 3 days HP Victus 16 RTX 4050 $749.99 Best Seller Free Shipping on Orders Over $35 ...
```

---

## Your Task

1. Scan the raw text for product listings
2. Identify product boundaries (usually: brand/model -> price -> availability)
3. Extract structured data for each product
4. Filter to only products matching the user's query

---

## Output Format

Return ONLY a JSON array:

```json
[
  {
    "title": "ASUS TUF Gaming A15 RTX 4060",
    "price": "$899.99",
    "price_numeric": 899.99
  },
  {
    "title": "Lenovo Legion 5 RTX 4060",
    "price": "$949.00",
    "price_numeric": 949.00
  }
]
```

---

## Extraction Strategy

### 1. Find Price Anchors

Prices usually appear near product names. Look for patterns:
- `$XXX.XX`
- `$X,XXX.XX`
- `$XXX`

Each price likely corresponds to one product.

### 2. Look Backwards for Product Name

From each price, look backwards for:
- Brand names (ASUS, Lenovo, HP, Dell, Acer, etc.)
- Model names (TUF, ROG, Legion, Pavilion, etc.)
- Specs (RTX, GTX, i7, Ryzen, etc.)

### 3. Look Forwards for Confirmation

After price, you might see:
- "In Stock", "Ships in X days" (confirms it's a product)
- "Add to Cart", "Buy Now" (confirms it's a product)
- "Out of Stock" (confirms it's a product, just unavailable)

### 4. Filter Noise

Ignore:
- Navigation text
- Promotional banners
- Categories and filters
- Footer text

---

## Common Raw OCR Challenges

### Run-together Text

OCR often produces:
```
ASUS TUF$899.99In Stock
```

Split at prices: "ASUS TUF" is the product, "$899.99" is the price.

### Missing Spaces

```
RTX4060laptop$899
```

Interpret as: "RTX 4060 laptop" at $899.

### Mixed Content

```
Sort by Price ASUS TUF $899 Lenovo Legion $949 Filter by Brand
```

Extract products, ignore UI: ASUS TUF at $899, Lenovo Legion at $949.

---

## Examples

### Example: Laptop Search

**Query:** "gaming laptop"

**Raw OCR:**
```
Search Results Gaming Laptops ASUS TUF Gaming A15 RTX 4060 8GB $899.99 Add to Cart ★★★★☆ Lenovo Legion 5 15.6" RTX 4060 $949.00 In Stock HP Victus 16 RTX 4050 $749.99 Free 2-Day Shipping Sort By Price Low to High
```

**Output:**
```json
[
  {
    "title": "ASUS TUF Gaming A15 RTX 4060 8GB",
    "price": "$899.99",
    "price_numeric": 899.99
  },
  {
    "title": "Lenovo Legion 5 15.6\" RTX 4060",
    "price": "$949.00",
    "price_numeric": 949.00
  },
  {
    "title": "HP Victus 16 RTX 4050",
    "price": "$749.99",
    "price_numeric": 749.99
  }
]
```

---

## Output Rules

1. Return ONLY the JSON array - no explanation text
2. Construct readable product titles from scattered OCR fragments
3. Match products to the user's query
4. Return empty array [] only if truly no products found
5. Be creative in parsing - OCR text is messy, use context clues
