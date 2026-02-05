# Fallback Navigation (Retry After Extraction Mismatch)

The extraction from the current page did NOT match the goal. You need to find a better navigation path.

## Your Task

The previous extraction attempt failed validation because the extracted items didn't match what the user was looking for. Analyze the available navigation links and find a path that will lead to the correct content.

## What to Look For

Search for navigation links that might lead to the goal:
- Category links mentioning the main item type
- Links like "Animals", "Pets", "Our [Animals]", "Available [Animals]"
- Product category navigation
- Menu items related to the goal

## Decision Options

1. **NAVIGATE** - Found a promising link to try
   - Specify the exact link text to click
   - Provide an alternative backup link if available

2. **GIVE_UP** - No viable navigation options
   - Use when all navigation options are exhausted
   - Use when the site clearly doesn't have the goal item

## Output Format

Respond in JSON:
```json
{
    "action": "navigate" | "give_up",
    "reason": "Why this link should have the right content",
    "target": "Exact link text to click",
    "alternative": "Backup link text (optional)"
}
```

## Examples

### Finding a Better Path
Problem: "Extracted water bottles when looking for hamsters"
Navigation links: ["Home", "Animals", "Supplies", "About Us"]
Result: action="navigate", target="Animals", reason="Animals category should list live hamsters"

### No Options Left
Problem: "Extracted dog supplies when looking for hamsters"
Navigation links: ["Dogs", "Cats", "Birds", "Contact"]
Result: action="give_up", reason="Site only sells dog, cat, and bird products - no hamster section"
