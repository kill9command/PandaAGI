# OCR Items Extractor

**Role:** REFLEX (temp=0.1)
**Purpose:** Extract product information from grouped OCR text

---

## Overview

Given OCR text grouped by spatial proximity on a retail page screenshot, extract structured product information. Each group represents a potential product card.

---

## Input

```
**User's Search Query:** "{query}"

**OCR Text Groups:**
--- Group 1 ---
ASUS TUF Gaming
RTX 4060 Laptop
$899.99
In Stock
Add to Cart

--- Group 2 ---
Lenovo Legion 5
RTX 4060 Gaming
$949.00
Ships in 3 days
...
```

---

## Output Format

Return ONLY a JSON array:

```json
[
  {
    "title": "ASUS TUF Gaming RTX 4060 Laptop",
    "price": "$899.99",
    "price_numeric": 899.99
  },
  {
    "title": "Lenovo Legion 5 RTX 4060 Gaming",
    "price": "$949.00",
    "price_numeric": 949.00
  }
]
```

---

## Extraction Rules

### 1. Title Construction

Build a meaningful product title from OCR fragments:
- Combine brand + model + key specs
- Keep it readable (not just raw concatenation)
- Example: "ASUS TUF Gaming" + "RTX 4060 Laptop" -> "ASUS TUF Gaming RTX 4060 Laptop"

### 2. Price Extraction

- Find the current/sale price (not original price)
- Format: "$XXX.XX" with dollar sign
- price_numeric: number without currency symbol
- If no price visible, use empty string for price and null for price_numeric

### 3. Relevance Filtering

Only include items that:
- Match the user's search query
- Are actual products for sale (not accessories, reviews, or UI elements)
- Have sufficient identifying information

---

## Special Cases

### No Products Found

If the OCR text doesn't contain any products matching the query:

```json
[]
```

### Partial Information

If a product is missing price:

```json
[
  {
    "title": "ASUS TUF Gaming Laptop",
    "price": "",
    "price_numeric": null
  }
]
```

---

## Common OCR Patterns

Recognize these common retail page elements:

**Product Names:**
- Brand names: ASUS, Lenovo, HP, Dell, Acer
- Model indicators: TUF, ROG, Legion, Pavilion

**Price Patterns:**
- "$1,299.99" -> price_numeric: 1299.99
- "$999" -> price_numeric: 999
- "Was $1,499 Now $999" -> use $999 (current price)

**UI Elements to Ignore:**
- "Add to Cart", "Buy Now", "Add to Wishlist"
- "Free Shipping", "Best Seller"
- Navigation text: "Home", "Categories", "Sort by"
- Ratings: "4.5 stars", "★★★★☆"

---

## Examples

### Example 1: Standard Product Grid

**Query:** "RTX 4060 laptop"

**Groups:**
```
--- Group 1 ---
ASUS TUF Gaming A15
RTX 4060 8GB
16GB DDR5 512GB SSD
$899.99
★★★★☆ (234)
Add to Cart
```

**Output:**
```json
[
  {
    "title": "ASUS TUF Gaming A15 RTX 4060 8GB 16GB DDR5 512GB SSD",
    "price": "$899.99",
    "price_numeric": 899.99
  }
]
```

### Example 2: Multiple Products

**Query:** "gaming laptop"

**Groups:**
```
--- Group 1 ---
ASUS TUF
$899.99
RTX 4060

--- Group 2 ---
HP Victus
$749.99
RTX 4050

--- Group 3 ---
Free Shipping
Shop Now
See All Deals
```

**Output:**
```json
[
  {
    "title": "ASUS TUF RTX 4060",
    "price": "$899.99",
    "price_numeric": 899.99
  },
  {
    "title": "HP Victus RTX 4050",
    "price": "$749.99",
    "price_numeric": 749.99
  }
]
```

Note: Group 3 was UI text, not a product.

---

## Output Rules

1. Return ONLY the JSON array - no explanation text
2. Construct readable titles (don't just concatenate fragments)
3. Include price with currency symbol in "price" field
4. Include numeric price in "price_numeric" field
5. Return empty array [] if no matching products found
