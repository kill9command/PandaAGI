# List Extractor

**Role:** REFLEX (temp=0.1)
**Purpose:** Extract items from list-style content

---

## Overview

Extract structured items from pages with list-style content: bulleted lists, numbered lists, definition lists, comparison tables.

---

## Input

```
**Extraction Goal:** {extraction_goal}
**Page URL:** {url}

**Page Content:**
{content}
```

---

## Output Format

```json
{
  "list_title": "Title or heading of the list",
  "list_type": "ranked/unranked/comparison/features",
  "items": [
    {
      "rank": 1,
      "name": "Item name",
      "description": "Description or details",
      "attributes": {
        "price": "$XXX",
        "rating": "4.5/5"
      }
    }
  ],
  "context": "What this list represents"
}
```

---

## List Types

| Type | Description |
|------|-------------|
| ranked | Numbered/ordered list (top 10, best, etc.) |
| unranked | Bulleted/unordered list |
| comparison | Side-by-side comparison |
| features | Feature/spec list |

---

## Extraction Rules

### 1. Identify List Structure

- Headers/titles for context
- List markers (numbers, bullets, dashes)
- Repeated patterns

### 2. Extract Each Item

- Name/title of item
- Description or details
- Any associated attributes (price, rating, specs)

### 3. Preserve Order

For ranked lists, maintain the ranking order.

---

## Example

**Content:**
```
Top 5 Gaming Laptops Under $1000

1. Lenovo Legion 5 - $899
   RTX 4050, 16GB RAM, 512GB SSD
   Rating: 4.5/5

2. ASUS TUF Gaming - $849
   RTX 4050, 16GB RAM, 512GB SSD
   Rating: 4.3/5

3. HP Victus 16 - $799
   RTX 4050, 8GB RAM, 512GB SSD
   Rating: 4.1/5
```

**Output:**
```json
{
  "list_title": "Top 5 Gaming Laptops Under $1000",
  "list_type": "ranked",
  "items": [
    {
      "rank": 1,
      "name": "Lenovo Legion 5",
      "description": "RTX 4050, 16GB RAM, 512GB SSD",
      "attributes": {
        "price": "$899",
        "rating": "4.5/5"
      }
    },
    {
      "rank": 2,
      "name": "ASUS TUF Gaming",
      "description": "RTX 4050, 16GB RAM, 512GB SSD",
      "attributes": {
        "price": "$849",
        "rating": "4.3/5"
      }
    },
    {
      "rank": 3,
      "name": "HP Victus 16",
      "description": "RTX 4050, 8GB RAM, 512GB SSD",
      "attributes": {
        "price": "$799",
        "rating": "4.1/5"
      }
    }
  ],
  "context": "Ranked list of budget gaming laptops"
}
```

---

## Output Rules

1. Return valid JSON only
2. rank is null for unranked lists
3. attributes object contains any key-value pairs found
4. Keep original order from source
5. list_type must be one of: ranked, unranked, comparison, features
