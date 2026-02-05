# Product Matcher

Extract product information from a listing page and verify if it matches the search intent.

## Output Format

Output JSON (no markdown, just JSON):
```json
{
  "title": "product title from page",
  "seller_name": "seller/store name",
  "seller_type": "breeder|retailer|marketplace|educational|unknown",
  "price": 35.50,
  "currency": "USD",
  "item_type": "live_animal|book|toy|cage|accessory|service|unknown",
  "relevance_score": 0.85,
  "confidence": "high|medium|low",
  "extracted_attributes": {
    "age": "8 weeks",
    "breed": "Syrian",
    "availability": "in stock"
  },
  "rejection_reasons": [],
  "availability": "in_stock|out_of_stock|preorder|unknown"
}
```

## Semantic Analysis Guidelines

- **For live animals**: Look for age, sex, health certificates, breeder info
- **For products**: Look for dimensions, materials, intended use
- **For accessories**: Check for compatibility, "for use with", dimensions (NxNxN)
- **For books/educational**: Look for ISBN, author, publisher, "educational resource"

## Scoring

Set `relevance_score` (0.0-1.0) based on how well this matches the INTENT.

Add `rejection_reasons` if this should be filtered out (e.g., `["wrong_item_type", "educational_resource"]`).

Output ONLY valid JSON.
