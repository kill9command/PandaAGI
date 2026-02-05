# Page Structure Prompt

You are analyzing a webpage to create a structured NavigationDocument.

## Your Goal

**{query}**

## Raw Page Capture

{raw_capture}

## Your Task

Analyze the raw capture and create a structured document with sections that are **relevant to the goal**.

You decide:
1. What sections exist on this page
2. What type/purpose each section has
3. Which elements belong in each section

## Output Format

```json
{{
  "sections": [
    {{
      "id": "S1",
      "section_type": "string - your label for this section",
      "purpose": "string - why this section matters for the goal",
      "items": [
        {{
          "id": "c5",
          "item_type": "element",
          "content": {{ "type": "input", "placeholder": "Search" }}
        }}
      ],
      "notes": "optional observations"
    }}
  ],
  "assessment": {{
    "page_type": "listing | pdp | navigation | blocked | no_content",
    "has_target_content": true,
    "content_quality": 0.8,
    "blockers": [],
    "notes": "what you observe about this page"
  }}
}}
```

## Section Types (Examples - Create Your Own)

You're not limited to these - create section types that make sense:

| Example Type | When to Use |
|--------------|-------------|
| `search_controls` | Search bar, filters |
| `product_listings` | Products with prices visible |
| `navigation_menu` | Category links, menus |
| `sort_controls` | Sort by price, relevance, etc. |
| `pagination` | Next/prev, page numbers |
| `notices` | Availability warnings, shipping info |
| `blockers` | CAPTCHA, login walls, age gates |
| `content_prose` | Article text, descriptions |

## Item Types

| item_type | content fields |
|-----------|----------------|
| `element` | id, type (link/button/input), text, placeholder, href |
| `product` | name, price, availability, clickable_id |
| `text` | text content |
| `notice` | message, notice_type |

## Rules

1. **Only include sections relevant to the goal**
   - Looking for products? Include product_listings, search_controls, sort_controls
   - Skip sections like footer links, privacy policy, etc.

2. **Link items to interactive elements**
   - If a product can be clicked, include `clickable_id: "c5"`
   - This lets the decision prompt know how to interact

3. **Assess content quality honestly**
   - 0.9+ = Exactly what we need, ready to extract
   - 0.6-0.8 = Relevant content but may need sorting/filtering
   - 0.3-0.5 = Some relevant content, needs navigation
   - <0.3 = Wrong content or blocked

4. **Identify blockers clearly**
   - CAPTCHA, login required, age verification
   - These go in `assessment.blockers[]`

5. **Match user priorities**
   - If query says "cheapest", note if sort controls exist
   - If query says "best rated", look for review/rating controls

## Examples

### E-commerce Listing Page

```json
{{
  "sections": [
    {{
      "id": "S1",
      "section_type": "search_controls",
      "purpose": "Search and filter products",
      "items": [
        {{ "id": "c3", "item_type": "element", "content": {{ "type": "input", "placeholder": "Search" }} }}
      ]
    }},
    {{
      "id": "S2",
      "section_type": "sort_controls",
      "purpose": "Sort results - user wants cheapest",
      "items": [
        {{ "id": "c12", "item_type": "element", "content": {{ "type": "link", "text": "Sort: Featured" }} }},
        {{ "id": "c13", "item_type": "element", "content": {{ "type": "link", "text": "Price: Low to High" }} }}
      ],
      "notes": "Price sort available - click c13 for cheapest first"
    }},
    {{
      "id": "S3",
      "section_type": "product_listings",
      "purpose": "Products matching search",
      "items": [
        {{ "id": "p1", "item_type": "product", "content": {{ "name": "ASUS ROG", "price": "$1,299", "clickable_id": "c20" }} }},
        {{ "id": "p2", "item_type": "product", "content": {{ "name": "HP Pavilion", "price": "$549", "clickable_id": "c21" }} }}
      ]
    }}
  ],
  "assessment": {{
    "page_type": "listing",
    "has_target_content": true,
    "content_quality": 0.7,
    "blockers": [],
    "notes": "Products visible but not sorted by price. Sort control available at c13."
  }}
}}
```

### Blocked Page

```json
{{
  "sections": [
    {{
      "id": "S1",
      "section_type": "blocker",
      "purpose": "CAPTCHA preventing access",
      "items": [
        {{ "id": "b1", "item_type": "notice", "content": {{ "message": "Please verify you are human", "notice_type": "captcha" }} }}
      ]
    }}
  ],
  "assessment": {{
    "page_type": "blocked",
    "has_target_content": false,
    "content_quality": 0.0,
    "blockers": ["captcha"],
    "notes": "CAPTCHA detected, need human intervention"
  }}
}}
```

### Wrong Content

```json
{{
  "sections": [
    {{
      "id": "S1",
      "section_type": "navigation_menu",
      "purpose": "Find correct category",
      "items": [
        {{ "id": "c5", "item_type": "element", "content": {{ "type": "link", "text": "Small Pets" }} }},
        {{ "id": "c6", "item_type": "element", "content": {{ "type": "link", "text": "Live Animals" }} }}
      ],
      "notes": "Search returned accessories, need to navigate to live animals"
    }},
    {{
      "id": "S2",
      "section_type": "wrong_category_products",
      "purpose": "NOT what we want - these are accessories",
      "items": [
        {{ "id": "p1", "item_type": "product", "content": {{ "name": "Hamster Cage", "price": "$49.99" }} }}
      ],
      "notes": "Query was for live hamsters, these are cages/supplies"
    }}
  ],
  "assessment": {{
    "page_type": "listing",
    "has_target_content": false,
    "content_quality": 0.1,
    "blockers": [],
    "notes": "Wrong product category. Need to navigate via c6 (Live Animals) to find actual hamsters."
  }}
}}
```

## Output JSON only - no other text:
