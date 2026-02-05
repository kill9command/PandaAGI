# PDP Selector Extraction Prompt

You are analyzing a Product Detail Page (PDP) to learn extraction selectors.

## Input Context

You will receive:
- URL of the page
- Page title
- Price elements found (with $ symbol)
- Title candidates
- Cart/Buy buttons
- Meta data

## Your Task

Choose the BEST CSS selector for:
1. The MAIN product price (not related products, not "was" price)
2. The product title
3. The Add to Cart button (for stock detection)

## Response Format

Respond with ONLY a JSON object (no markdown):
```json
{
    "page_type": "pdp",
    "price_selector": "CSS selector for main price element",
    "title_selector": "CSS selector for product title",
    "cart_button_selector": "CSS selector for cart button",
    "product_card_selector": "",
    "link_selector": "",
    "image_selector": ""
}
```

## Selection Rules

1. Use the EXACT selectors from the discovered elements above
2. For price, prefer elements with the actual price text, not containers
3. If multiple prices, choose the one closest to the cart button (lowest Y position near buttons)
4. Return empty string "" if you can't determine a selector
5. NEVER use CSS-in-JS hashed class names like "-sc-abc123" or "css-xyz789" - these change between deployments!
6. PREFER: [data-testid="..."], #id, or semantic class names like ".product-price"
7. AVOID: Classes with hash suffixes like "Price-sc-663c57fc-1" or "styled__Component-abc123"
