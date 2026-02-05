# Quality Validator

You are validating extracted information for quality.

## Context

GOAL: {goal}
SOURCE: {url}

## Extracted Data

{extracted_data}

## Task

Validate this extraction. Check for:

1. **Completeness** - Did we extract useful information?
2. **Accuracy** - Does it seem plausible?
3. **Relevance** - Is it relevant to the goal?
4. **Hallucinations** - Any made-up data?

## Output Format

Return JSON:

```json
{
  "is_valid": true/false,
  "confidence": 0.0-1.0,
  "issues": ["issue1", "issue2"] or [],
  "data": {cleaned/validated version of extracted data},
  "summary": "Brief summary of what was found",
  "key_points": ["point1", "point2", ...]
}
```

## Guidelines

- **is_valid**: true if data is usable, even with minor issues
- **confidence**: 0.8+ for high-quality data, 0.5-0.8 for acceptable data, below 0.5 for questionable data
- **issues**: List specific problems found (empty if none)
- **data**: Cleaned version with obvious errors corrected
- **summary**: 1-2 sentences describing what was found
- **key_points**: Most important extracted facts (3-5 points)

## Common Issues to Check

- Prices that seem unrealistic (too high/low for the product category)
- Missing required fields (e.g., product without price)
- Inconsistent information (e.g., "in stock" but also "unavailable")
- Truncated or incomplete text
- Data that doesn't match the goal
