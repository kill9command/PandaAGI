# Navigation Decision Prompt

You are navigating a website to find: **{query}**

## NavigationDocument

{navigation_document}

## Site Knowledge

{site_knowledge}

## Step: {step}/{max_steps}

## Your Task

Based on the NavigationDocument (which YOU structured), decide what action to take.

**Reference sections by ID** in your reasoning (e.g., "Looking at S2 (product_listings)...").

## Available Actions

| action | When to use | Required fields |
|--------|-------------|-----------------|
| `click` | Navigate via link/button | `target_id` (element ID like "c5") |
| `type` | Enter text into input | `target_id`, `input_text` |
| `scroll` | Load more content | - |
| `extract` | Pull data from current page | - |
| `request_help` | CAPTCHA or blocker needs human | - |
| `finish` | Done, return results | - |

## Decision Rules

1. **Use the assessment**
   - If `has_target_content: true` and `content_quality > 0.7` → likely ready to extract
   - If blockers present → request_help
   - If `content_quality < 0.5` → need to navigate

2. **Reference sections in reasoning**
   - "S2 shows products with prices, ready to extract"
   - "S1 has search control (c3), will use to search"
   - "S3 has sort controls, user wants cheapest so clicking c12"

3. **For search/type actions**
   - Remove price words from input ("cheapest laptop" → "laptop")
   - Find input element in sections

4. **expected_state is REQUIRED**
   - Predict what page should look like after action
   - Helps verify action succeeded

## Output Format

```json
{{
  "action": "click",
  "target_id": "c5",
  "input_text": "",
  "expected_state": {{
    "page_type": "listing",
    "must_see": ["$", "laptop"]
  }},
  "reasoning": "S2 shows products but not sorted. S3 has 'Price: Low to High' (c12). User wants cheapest, so clicking to sort.",
  "confidence": 0.85
}}
```

## Examples

### Ready to extract

```json
{{
  "action": "extract",
  "expected_state": {{
    "page_type": "listing"
  }},
  "reasoning": "S2 (product_listings) shows 5 products with prices. Assessment shows content_quality=0.85 and has_target_content=true. Ready to extract.",
  "confidence": 0.95
}}
```

### Need to search

```json
{{
  "action": "type",
  "target_id": "c3",
  "input_text": "laptop nvidia gpu",
  "expected_state": {{
    "page_type": "listing",
    "must_see": ["$", "laptop", "nvidia"]
  }},
  "reasoning": "S1 (search_controls) has input field c3. No products visible yet. Searching for laptops.",
  "confidence": 0.9
}}
```

### Need to sort

```json
{{
  "action": "click",
  "target_id": "c12",
  "expected_state": {{
    "page_type": "listing",
    "must_see": ["$", "Price"]
  }},
  "reasoning": "S2 shows products but S3 (sort_controls) indicates current sort is 'Featured'. User wants cheapest. Clicking 'Price: Low to High' (c12).",
  "confidence": 0.85
}}
```

### Blocked by CAPTCHA

```json
{{
  "action": "request_help",
  "expected_state": {{
    "page_type": "listing"
  }},
  "reasoning": "Assessment shows blockers=['captcha']. S1 (blocker) confirms CAPTCHA. Need human intervention.",
  "confidence": 0.95
}}
```

### Wrong content, need to navigate

```json
{{
  "action": "click",
  "target_id": "c8",
  "expected_state": {{
    "page_type": "listing",
    "must_see": ["hamster", "live", "pet"]
  }},
  "reasoning": "Assessment shows has_target_content=false, content_quality=0.1. S2 shows accessories not live animals. S1 (navigation_menu) has 'Live Animals' link (c8). Navigating to correct category.",
  "confidence": 0.7
}}
```

## Output JSON only - no other text:
