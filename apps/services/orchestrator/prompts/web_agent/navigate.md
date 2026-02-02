# Navigation Prompt (Stage 2B)

Decide the best action to reach content for: {query}

## Current State

- URL: {url}
- Research Phase: {phase} (1=intelligence/forums, 2=products/vendors)

## Clickable Elements

{clickable_elements}

## Understanding the User's Goal

Read the query carefully to understand what the user wants:

**Price Priority Detection:**
- "cheapest", "lowest price", "budget", "affordable", "cheap" → User wants LOWEST PRICE
- "best", "top rated", "highest rated" → User wants BEST QUALITY
- "fastest", "quickest" → User wants FASTEST SHIPPING/DELIVERY

## Available Actions

You have THREE options:

### 1. SEARCH - Use the site's search bar
**When to use:**
- You're on a homepage, landing page, or category page
- No relevant products are visible yet
- You see a search box/bar on the page
- Need to find specific products matching the query

**How to form search_query:**
- Extract the PRODUCT TYPE from the user's query
- Keep essential specs/requirements
- REMOVE price words (cheapest, budget, etc.) - we'll sort by price after searching
- Examples:
  - Query: "cheapest laptop with nvidia gpu" → search_query: "laptop nvidia gpu"
  - Query: "best wireless headphones under $100" → search_query: "wireless headphones"
  - Query: "budget gaming monitor 144hz" → search_query: "gaming monitor 144hz"

### 2. CLICK - Click a link or button
**When to use:**
- Products are visible but need sorting (click "Price: Low to High")
- Category navigation will get you closer to products
- Sort controls are visible and user wants lowest/highest price

**Priority for LOWEST PRICE queries:**
1. FIRST look for sort controls: "Sort by", "Price: Low to High", "Lowest Price"
2. Click the sort control BEFORE navigating elsewhere

### 3. NO_ACTION - No viable navigation
**When to use:**
- Stuck on a page with no path to products
- All links lead to irrelevant pages

## Navigation Rules

1. **Click target MUST exactly match text in CLICKABLE ELEMENTS above**
   - Case-sensitive exact match required
   - The click will fail if text doesn't match exactly

2. **CHECK THE URL** - Don't click links already in the current URL
   - URL contains "hamsters" → Don't click "Hamsters"
   - URL contains "forum" → Don't click "Forum"

3. **Phase-appropriate targets:**
   - Phase 1 (forums): "Comments", "Discussion", "Thread", "Replies"
   - Phase 2 (products): "Shop", "Products", "For Sale", "Buy", "Store", or use SEARCH

4. **AVOID these links:**
   - About, Contact, FAQ, Blog, Privacy, Terms, Support
   - Cart, Checkout, Login, Register, Account
   - Social media links (Facebook, Instagram, Twitter)

5. **Prefer SEARCH over multi-step navigation:**
   - If you're 2+ clicks away from products, SEARCH is faster
   - Homepage? → Use SEARCH with product terms

6. **For price-priority queries, prioritize sort controls:**
   - If products are visible AND you see "Sort by" → click to sort by price
   - This is MORE IMPORTANT than searching again

## Output

Respond with JSON only:

**To SEARCH:**
```json
{{
  "action": "search",
  "search_query": "product terms to search",
  "reasoning": "Why searching is the best option"
}}
```

**To CLICK:**
```json
{{
  "action": "click",
  "click_target": "Exact text from CLICKABLE ELEMENTS",
  "reasoning": "Why this link will lead to the content we need"
}}
```

**NO viable action:**
```json
{{
  "action": "no_action",
  "reasoning": "Why no suitable action was found"
}}
```
