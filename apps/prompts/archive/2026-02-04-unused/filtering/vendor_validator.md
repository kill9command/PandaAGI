# Vendor Validator

**Role:** REFLEX (temp=0.1)
**Purpose:** Validate whether vendors are appropriate for the user's goal

---

## Overview

Evaluate candidate vendors from research intelligence to determine if they are
likely to have what the user is looking for. Prevents visiting irrelevant
sources (e.g., pet supply stores when looking for live animals).

---

## Input

```
USER'S GOAL:
{goal}

CANDIDATE VENDORS (from research intelligence):
{vendor_list}
```

---

## Output Schema

```json
{
  "approved": [
    {
      "index": 1,
      "reason": "Why this vendor is appropriate for the goal"
    }
  ],
  "rejected": [
    {
      "index": 3,
      "reason": "Why this vendor is NOT appropriate for the goal"
    }
  ],
  "summary": "Brief summary of validation decisions"
}
```

---

## Validation Rules

### 1. Match Vendor Type to Goal

| User Goal | Appropriate Vendors | Inappropriate Vendors |
|-----------|--------------------|-----------------------|
| Buy live animals | Breeders, rescues, pet stores with live animals | Pet supply stores (food, accessories only) |
| Buy pet supplies | Pet supply stores, Amazon, Walmart | Breeders, animal rescues |
| Buy electronics | Electronics retailers, manufacturers | Pet stores, grocery stores |
| Buy clothing | Fashion retailers, department stores | Electronics stores |

### 2. Vendor Category Analysis

For each vendor, determine what they actually sell:

**Pet-Related Vendors:**
- **Breeders/Rescues:** Sell live animals -> APPROVE for animal purchase
- **Pet Supply Stores** (Chewy, PetSmart, Petco): Sell food/accessories -> REJECT for live animal purchase
- **Adoption Sites** (Petfinder, Adopt-a-Pet): Animal adoption -> APPROVE for animal purchase

**Electronics Vendors:**
- **Major Retailers** (Best Buy, Amazon, Newegg): APPROVE for electronics
- **Specialty** (B&H Photo, Micro Center): APPROVE for electronics
- **Manufacturers** (Dell, HP, Lenovo): APPROVE for brand-specific

### 3. Special Cases

**Hamster/Small Pet Example:**
- Goal: "Buy a Syrian hamster"
- Chewy.com: Sells hamster SUPPLIES, not live hamsters -> REJECT
- PetSmart: May have live animals in-store, but mostly supplies online -> CAUTIOUS
- Local breeder: Sells live hamsters -> APPROVE
- Petfinder: Adoption listings -> APPROVE

**Electronics Example:**
- Goal: "Buy RTX 4060 laptop"
- Best Buy: Major electronics retailer -> APPROVE
- Costco: Has electronics section -> APPROVE
- PetSmart: Wrong category entirely -> REJECT

---

## Confidence Levels

Assign confidence to each decision:

| Confidence | Criteria |
|------------|----------|
| High (0.9+) | Vendor category clearly matches or mismatches goal |
| Medium (0.6-0.8) | Vendor might have the item, worth checking |
| Low (< 0.6) | Uncertain, but including to avoid missing options |

---

## Examples

### Example 1: Live Animal Purchase

**Goal:** "Find Syrian hamster for sale near me"

**Vendors:**
1. Chewy.com (source: intelligence)
2. Example Pet Store (source: intelligence)
3. Petfinder.com (source: intelligence)
4. PetSmart (source: intelligence)

**Output:**
```json
{
  "approved": [
    {
      "index": 2,
      "reason": "Hamstery - specializes in breeding and selling hamsters"
    },
    {
      "index": 3,
      "reason": "Pet adoption site with live animal listings"
    }
  ],
  "rejected": [
    {
      "index": 1,
      "reason": "Chewy sells pet supplies, not live animals"
    },
    {
      "index": 4,
      "reason": "PetSmart primarily sells supplies online; live animals in-store only"
    }
  ],
  "summary": "Approved 2 vendors that sell live hamsters. Rejected pet supply stores."
}
```

### Example 2: Electronics Purchase

**Goal:** "Buy cheapest RTX 4060 gaming laptop"

**Vendors:**
1. Best Buy (source: search)
2. Newegg (source: search)
3. Dell.com (source: intelligence)
4. Reddit (source: search)

**Output:**
```json
{
  "approved": [
    {
      "index": 1,
      "reason": "Major electronics retailer with competitive pricing"
    },
    {
      "index": 2,
      "reason": "Tech-focused retailer specializing in PC hardware"
    },
    {
      "index": 3,
      "reason": "Laptop manufacturer - official source for Dell laptops"
    }
  ],
  "rejected": [
    {
      "index": 4,
      "reason": "Reddit is a forum, not a vendor - cannot purchase from"
    }
  ],
  "summary": "Approved 3 legitimate electronics retailers. Rejected non-vendor."
}
```

---

## Output Rules

1. Return valid JSON only
2. Index values (1-based) must match input order
3. Every vendor must appear in either approved or rejected
4. Provide clear, specific reasoning for each decision
5. Summary should explain the overall validation strategy
