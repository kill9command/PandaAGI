# Intelligence Extraction Prompt (Stage 2A - Phase 1)

Extract community intelligence from this forum/discussion page.

## Query Context

{query}

## Page Content

{page_doc}

## What to Extract

Look for these in the NAVIGATION & CONTENT section:

1. **Vendor/Brand Recommendations** - SPECIFIC names of stores, breeders, websites people recommend
   - Extract EXACT business names (e.g., "Poppy Bee Hamstery", "Hubba Hubba Hamstery", "Petco")
   - Do NOT generalize to categories like "local breeder" or "pet store" - we need actual names
   - Include the reason why they recommend it
   - Include URL/website if mentioned
   - If someone says "I got mine from [Name]" - extract that exact name

2. **Vendors to Avoid** - SPECIFIC names with negative reviews or warnings
   - Extract exact business names, not generic warnings
   - Include the reason for the warning

3. **Price Expectations** - What people say about typical prices
   - "expect to pay $X", "normal price is...", "anything under $X is a deal"

4. **Quality Tips** - Advice on what to look for
   - "make sure they have...", "ask about...", "look for...", "avoid if..."

5. **Location Info** - If location-specific information is mentioned

## Extraction Rules

- ONLY extract information LITERALLY stated in the content above
- Include the reason/context for each recommendation
- If information seems outdated (mentions old years), note it
- If no relevant information found, return empty arrays

## Output

Respond with JSON only:

```json
{{
  "recommended_vendors": [
    {{"name": "Vendor Name", "reason": "Why recommended", "url": "if mentioned"}}
  ],
  "vendors_to_avoid": [
    {{"name": "Vendor Name", "reason": "Why to avoid"}}
  ],
  "price_expectations": "What people say about typical prices",
  "quality_tips": ["tip 1", "tip 2"],
  "location_info": "Any location-specific info",
  "confidence": 0.0-1.0
}}
```
