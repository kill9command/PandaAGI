# PDP Specs Extraction

Extract product specifications from the page content.

## Context

You are extracting technical specifications from a Product Detail Page (PDP). The user is searching for: **{GOAL}**

## Input

Page content (text extracted from PDP):
```
{PAGE_TEXT}
```

## Task

Extract key specifications that are **explicitly stated** on the page. Focus on specs relevant to the user's goal.

## Output Format (JSON only)

```json
{
  "specs": {
    "key": "value"
  }
}
```

## Spec Key Guidelines

Use these normalized keys when applicable:

| Category | Keys to use |
|----------|-------------|
| Graphics | `gpu` |
| Processor | `cpu` |
| Memory | `ram` |
| Storage | `storage` |
| Display | `display` |
| Battery | `battery` |
| Weight | `weight` |
| OS | `os` |

For other specs, use lowercase with underscores (e.g., `screen_size`, `refresh_rate`).

## Rules

1. **Only extract specs explicitly stated on the page** - never guess or infer
2. **Preserve original values with units** - "16GB DDR5", not just "16"
3. **Omit specs not found** - empty object `{}` is valid if no specs found
4. **Focus on user's goal** - if searching for GPU, prioritize graphics specs

## Examples

**Goal:** "laptop with nvidia gpu"
**Page text:** "...featuring RTX 4060 graphics, Intel Core i7-13700H processor, 16GB DDR5 memory..."

```json
{
  "specs": {
    "gpu": "RTX 4060",
    "cpu": "Intel Core i7-13700H",
    "ram": "16GB DDR5"
  }
}
```

**Goal:** "Syrian hamster for sale"
**Page text:** "...Syrian Hamster, healthy and friendly, from ethical breeder..."

```json
{
  "specs": {}
}
```

## Output

Return ONLY the JSON object, no explanation.
