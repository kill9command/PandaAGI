# Contact Info Extractor

**Role:** REFLEX (temp=0.1)
**Purpose:** Extract contact information from pages

---

## Overview

Extract contact details from pages that mention "contact for price" or list contact information for inquiries.

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
  "contacts": [
    {
      "type": "email",
      "value": "contact@example.com",
      "context": "General inquiries"
    },
    {
      "type": "phone",
      "value": "(555) 123-4567",
      "context": "Sales"
    }
  ],
  "business_name": "Business Name if mentioned",
  "location": "City, State or full address if mentioned",
  "hours": "Business hours if mentioned",
  "pricing_note": "Any notes about pricing (e.g., 'call for quote')"
}
```

---

## Contact Types

| Type | Patterns |
|------|----------|
| email | xxx@xxx.xxx |
| phone | (XXX) XXX-XXXX, XXX-XXX-XXXX, +1 XXX XXX XXXX |
| website | URLs mentioned for contact |
| social | @username, facebook.com/xxx |
| form | "Contact form", "Fill out form" |

---

## Extraction Rules

1. Find ALL contact methods mentioned
2. Note the context for each (sales, support, general)
3. Extract business name and location if visible
4. Note any pricing-related instructions

---

## Example

**Content:**
```
Smith's Hamster Haven
123 Pet Lane, Portland, OR 97201

Contact us for available hamsters!
Email: contact@example-store.com
Phone: (503) 555-0123

Open Mon-Sat 10am-6pm
Prices vary by variety - please call for current pricing.
```

**Output:**
```json
{
  "contacts": [
    {
      "type": "email",
      "value": "contact@example-store.com",
      "context": "General contact"
    },
    {
      "type": "phone",
      "value": "(503) 555-0123",
      "context": "General/pricing inquiries"
    }
  ],
  "business_name": "Smith's Hamster Haven",
  "location": "123 Pet Lane, Portland, OR 97201",
  "hours": "Mon-Sat 10am-6pm",
  "pricing_note": "Prices vary by variety - call for current pricing"
}
```

---

## Output Rules

1. Return valid JSON only
2. contacts array can have multiple entries
3. Use null for unavailable fields
4. Include ALL contact methods found
5. context should explain what the contact is for
