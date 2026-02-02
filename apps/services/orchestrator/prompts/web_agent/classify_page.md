# Page Classification Prompt (Stage 1)

Classify this web page for {phase} research.

## Page Analysis

{page_doc}

## Context

- Current Step: {step} of {max_steps}
- Research Phase: {phase} (1=intelligence/forums, 2=products/vendors)
- Query: {query}

## Understanding User Priority

First, detect what the user wants from the query:
- "cheapest", "lowest price", "budget", "affordable" → **PRICE PRIORITY: lowest first**
- "best", "top rated" → **QUALITY PRIORITY**
- No priority words → **DEFAULT: relevance**

## Page Types

Choose ONE:

**content_page** - Has extractable content relevant to the research
- Phase 1: Forum posts, discussions, recommendations, reviews visible
- Phase 2: Products with names and prices visible (in DOM PRODUCT DATA or PRODUCTS DETECTED)
- **IMPORTANT for PRICE PRIORITY:** Only classify as content_page if:
  - Products appear to be sorted by price already, OR
  - No sort controls are visible (can't sort), OR
  - You're on step 3+ (no more navigation allowed)

**navigation_page** - Need to click to find content
- Homepage, category page, or menu visible
- No actual content yet, just links to content
- **IMPORTANT for PRICE PRIORITY:** If query wants "cheapest" AND products are visible BUT:
  - Products are NOT sorted by price (cheapest not first), AND
  - Sort controls ARE visible (like "Sort by", "Sort By: Relevance", etc.)
  - → Classify as navigation_page so we can click the sort control first
- Only valid on steps 1-2

**blocked** - Access prevented
- CAPTCHA, login wall, bot detection, age verification gate

**no_content** - Nothing useful here
- 404 error, unrelated page
- "Check our Facebook/Instagram for listings"
- Empty listings, "coming soon", "sold out" with no products
- Only navigation/branding visible, no actual content

## Important Rules

1. On step 3+, you can ONLY classify as "content_page" or "no_content" (no more navigation)
2. Look at DOM PRODUCT DATA and PRODUCTS DETECTED sections - if they have items, check if sorting is needed
3. Don't assume content exists just from page title - look at actual content
4. If NAVIGATION & CONTENT only shows menu items and branding, it's navigation_page or no_content
5. **For "cheapest" queries: Sorting by price is MORE IMPORTANT than extracting unsorted results**

## Output

Respond with JSON only:

```json
{{
  "page_type": "content_page" | "navigation_page" | "blocked" | "no_content",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of why this classification"
}}
```
