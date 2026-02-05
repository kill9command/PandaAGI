# Navigation Decision

You are navigating a website to find content matching a specific goal.

## Your Task

Analyze the current page state and decide whether to:
1. **EXTRACT** - This page has content matching the goal
2. **NAVIGATE** - Need to click a link to find the content
3. **GIVE_UP** - This website doesn't have what we're looking for

## Decision Rules

### When to EXTRACT:
- You see products/listings matching the goal
- You see contact info for a vendor selling the goal item
- You see PRICES and products visible on the page
- Use if this is a SEARCH RESULTS page (url_type=search_results) with products visible

### When to NAVIGATE:
- This is a homepage with no products
- This is a category overview without actual listings
- You're clearly on the wrong section of the site
- Look for navigation links that might lead to the goal

### When to GIVE_UP:
- The site clearly doesn't sell/offer the goal item
- You've exhausted navigation options
- The page is blocked, requires login, or is an error page

## Critical Decision Logic

1. **If this is a SEARCH RESULTS page with products visible:**
   - STRONGLY PREFER EXTRACT over NAVIGATE
   - Clicking "Filters", "Sort", "Refine" will likely LOSE existing price filters!

2. **If PRICE FILTER is already applied in the URL:**
   - DO NOT navigate to filter/category pages - you'll lose the filter!
   - EXTRACT what's visible, even if results seem limited

3. **For BREEDER/HAMSTERY/CATTERY sites without prices:**
   - Look for "Adoption", "Pricing", "Fees" pages
   - Use content_type "contact_vendor" if no prices shown

4. **If products are visible with prices:**
   - EXTRACT first, we'll validate the results after
   - Don't try to "improve" the search by navigating

5. **Only NAVIGATE if:**
   - This is a homepage with no products
   - This is a category overview without actual listings
   - You're clearly on the wrong section of the site

## Content Types

When extracting, specify the content type:
- `product_listing` - E-commerce product grid or search results
- `contact_vendor` - Breeder/vendor with contact info but no prices
- `marketplace` - Classifieds or marketplace listings

## Output Format

Respond in JSON format:
```json
{
    "action": "extract" | "navigate" | "give_up",
    "reason": "Brief explanation of your decision",
    "target": "Exact link text to click (only for navigate)",
    "alternative": "Backup link text if first doesn't work (optional)",
    "hints": {
        "content_type": "product_listing" | "contact_vendor" | "marketplace",
        "has_prices": true | false,
        "notes": "Any extraction notes"
    }
}
```
