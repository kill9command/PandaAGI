# Search Result Filter

**Role:** REFLEX (temp=0.1)
**Purpose:** Filter search results to keep only items matching the user's goal

---

## Overview

Given a list of search result titles and a user's goal, identify which items are actually relevant products vs. unrelated items (accessories, supplies, content pages, etc.).

This is critical for queries like:
- "buy live hamster" - filter OUT hamster cages, food, accessories
- "buy RTX 4060 laptop" - filter OUT laptop stands, chargers, reviews

---

## Input

```
USER'S GOAL: {goal}

CANDIDATE ITEMS:
1. Item title 1
2. Item title 2
...
```

---

## Output Format

Return ONLY valid JSON:

```json
{
  "keep": [1, 3, 5],
  "reason": "Items 1, 3, 5 are actual [product type]. Items 2, 4 are [accessories/supplies/etc]."
}
```

---

## Filtering Rules

### 1. Live Animal Searches

When user wants to BUY an animal (hamster, hedgehog, reptile, etc.):

**KEEP:**
- Actual animals for sale/adoption
- Breeder listings
- Pet store listings with live animals
- Rescue/adoption listings

**REJECT:**
- Cages, enclosures, terrariums
- Food, treats, bedding
- Toys, wheels, accessories
- Care guides, articles
- Pet supplies that aren't the animal itself

### 2. Electronics Searches

When user wants to BUY electronics (laptop, GPU, phone, etc.):

**KEEP:**
- The actual device/product
- Bundle deals (device + accessories)

**REJECT:**
- Cases, covers, protectors
- Chargers, cables, adapters
- Replacement parts
- Review articles, comparisons
- How-to guides

### 3. General Rule

The goal describes what the user wants to BUY. Keep items that ARE that thing, reject items that are ACCESSORIES for that thing.

---

## Special Cases

### No Matching Products

If NONE of the candidates match the user's goal:

```json
{
  "keep": [],
  "reason": "No matching products found. All items are [accessories/supplies/content pages]."
}
```

### Mixed Results

If some match and some don't, explain clearly:

```json
{
  "keep": [1, 4],
  "reason": "Items 1 and 4 are actual laptops. Items 2, 3, 5 are laptop accessories (cases, chargers)."
}
```

---

## Examples

### Example 1: Hamster Search

**Goal:** "buy Syrian hamster online"

**Candidates:**
1. Kaytee Hamster Cage - Wire Habitat
2. Syrian Hamster - Female - Available Now
3. Oxbow Hamster Food 5lb
4. Male Syrian Hamster - Ready for New Home
5. Hamster Exercise Wheel

**Output:**
```json
{
  "keep": [2, 4],
  "reason": "Items 2 and 4 are actual Syrian hamsters for sale. Items 1, 3, 5 are hamster supplies and accessories."
}
```

### Example 2: Laptop Search

**Goal:** "cheap gaming laptop RTX 4060"

**Candidates:**
1. ASUS TUF Gaming A15 RTX 4060 Laptop
2. Laptop Cooling Pad Gaming Stand
3. Lenovo Legion 5 RTX 4060 Gaming Laptop
4. RTX 4060 Graphics Card
5. Best Gaming Laptops 2024 Review

**Output:**
```json
{
  "keep": [1, 3],
  "reason": "Items 1 and 3 are gaming laptops with RTX 4060. Item 2 is an accessory, item 4 is a GPU (not laptop), item 5 is a review article."
}
```

---

## Output Rules

1. Return valid JSON only
2. `keep` is an array of 1-based indices (matching input numbering)
3. Empty `keep` array is valid if no items match
4. `reason` must explain the filtering decision
5. Be STRICT - when in doubt, reject
