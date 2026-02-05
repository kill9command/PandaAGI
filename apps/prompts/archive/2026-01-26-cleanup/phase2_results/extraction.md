# Result Extraction

## Extraction Process

For each search result, extract standardized information based on result type.

### Product Extraction

Extract these fields for each product:

| Field | Required | Description |
|-------|----------|-------------|
| title | Yes | Full product name |
| price | Yes | Current price with currency |
| url | Yes | Direct link to product |
| availability | Yes | In Stock / Out of Stock / Limited |
| source | Yes | Vendor/site name |
| attributes | Yes | Key specs as key-value pairs |
| image_url | No | Product image if available |
| rating | No | Star rating if available |
| review_count | No | Number of reviews |

**Attributes to Extract by Domain:**

- **Electronics**: CPU, GPU, RAM, Storage, Display, Battery, Weight
- **Pets**: Size, Material, Compatibility, Features
- **Appliances**: Capacity, Power, Dimensions, Features
- **Travel**: Departure, Arrival, Duration, Stops, Class
- **Health**: Dosage, Ingredients, Quantity, Form

### Guide/Information Extraction

| Field | Required | Description |
|-------|----------|-------------|
| title | Yes | Article/guide title |
| source | Yes | Website name |
| url | Yes | Direct link |
| author | No | Author name if available |
| date | No | Publication date |
| summary | Yes | Key points (2-3 sentences) |
| quality_indicators | Yes | Expertise level, depth, recency |

### Listing Extraction (Travel, Services)

| Field | Required | Description |
|-------|----------|-------------|
| title | Yes | Listing description |
| price | Yes | Price with currency |
| url | Yes | Booking/detail link |
| provider | Yes | Service provider |
| details | Yes | Key details as key-value pairs |
| availability | No | Dates/times available |

## Extraction Methods

Track which method was used for transparency:

1. **known_selectors** (confidence: 0.95): Site-specific CSS selectors
2. **llm_extraction** (confidence: 0.85): LLM-based content extraction
3. **pattern_matching** (confidence: 0.80): Regex/pattern-based extraction
4. **manual_parse** (confidence: 0.70): General HTML parsing

## Handling Incomplete Data

When data is missing:
1. Mark field as `null` or `"unknown"`
2. Lower confidence score appropriately
3. Note in extraction_notes what was missing
4. Still include result if core fields (title, price/summary, url) present

## Deduplication

Before adding to results:
1. Check for duplicate URLs
2. Check for same product/item at different vendors
3. If duplicate found, keep the one with:
   - More complete data
   - Higher confidence
   - Better price (for products)

## Quality Indicators

For each extracted result, assess:

- **Data Completeness**: 0.0-1.0 (percentage of fields filled)
- **Source Authority**: 0.0-1.0 (is source trustworthy?)
- **Information Recency**: 0.0-1.0 (how current is the data?)
- **Extraction Confidence**: 0.0-1.0 (how confident in accuracy?)

Final confidence = weighted average:
```
confidence = (completeness * 0.3) + (authority * 0.3) +
             (recency * 0.2) + (extraction * 0.2)
```
