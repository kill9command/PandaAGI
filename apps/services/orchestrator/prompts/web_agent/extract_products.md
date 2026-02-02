# Product Extraction Prompt (Stage 2A - Phase 2)

Extract products from this vendor page.

## Query

{query}

## Phase 1 Intelligence (if available)

{phase1_intelligence}

## Page Content

{page_doc}

## Where to Find Products (Priority Order)

1. **DOM PRODUCT DATA section** - Most reliable (structured HTML)
2. **PRODUCTS DETECTED section** - OCR-detected items with prices
3. **NAVIGATION & CONTENT section** - If product types mentioned WITH pricing context

## Extraction Rules

**ANTI-HALLUCINATION (CRITICAL):**
- ONLY extract products LITERALLY visible in the page content above
- NEVER invent products, prices, or details not shown
- If DOM PRODUCT DATA and PRODUCTS DETECTED are both empty, check NAVIGATION & CONTENT
- If nothing has prices or pricing context, return empty products array

**NEVER extract these as products:**
- Business names (company names, store names, brand names)
- Navigation items ("Shop", "Buy Now", "Products", "About", "Contact")
- Taglines or slogans (marketing text)
- Generic category names ("Products", "Available Items", "Our Selection")
- UI elements ("Add to Cart", "View Details", "Learn More")

**ONLY extract actual purchasable items:**
- Must have a specific product name visible above
- Must have pricing info: $XX.XX, "Contact for pricing", or pricing description
- Ask: "Can I point to exactly where this appears in the page content?"

## Output

Respond with JSON only:

```json
{{
  "products": [
    {{
      "name": "Specific product name from page",
      "price": "$XX.XX or 'Contact for pricing' or pricing description",
      "description": "Any additional details visible",
      "in_stock": true
    }}
  ],
  "extraction_source": "dom" | "ocr" | "content",
  "vendor_notes": "Any notes about this vendor from page content"
}}
```

If no products found, return:
```json
{{
  "products": [],
  "extraction_source": "none",
  "vendor_notes": "Why no products could be extracted"
}}
```
