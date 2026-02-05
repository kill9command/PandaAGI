Prompt-version: v1.0.0

# Topic Keyword Extractor

Extract the core topic/product keywords from a user query. Remove all conversational filler.

## Rules

- Output 2-5 words (the core topic only)
- Remove: "find me", "can you", "help me", "for sale", "buy", "please"
- **KEEP price constraints - these are user requirements:**
  - Keep: "cheapest", "budget", "under $X", "affordable"
  - Example: "cheapest laptop nvidia gpu" → "cheapest laptop nvidia gpu"
- Keep: product names, brands, specifications, constraints
- Output ONLY the topic keywords, nothing else

## Examples

"what's the cheapest laptop with nvidia gpu" → "cheapest laptop nvidia gpu"
"find me a budget gaming monitor under $300" → "budget gaming monitor under $300"
"can you help me find Syrian hamsters for sale" → "Syrian hamsters"

## Output

Output the topic keywords on a single line with no additional formatting or explanation.
