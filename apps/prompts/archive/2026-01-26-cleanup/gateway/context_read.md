# Context Gatherer - Read Phase Prompt

## Purpose
Phase 2 of the 4-phase context gatherer. Evaluates loaded contexts and decides what links to follow for more detail.

## Prompt Template

CURRENT QUERY: {query}

SCAN RESULT:
{scan_result}

LOADED CONTEXTS:
{context_bundle}

Evaluate what info is useful and which links to follow. Output JSON.

## Expected Output Format

```json
{
  "direct_info": {
    "5": "summary of usable info from turn 5",
    "3": "summary of usable info from turn 3"
  },
  "links_to_follow": [
    {
      "turn": 5,
      "path": "path/to/research.md",
      "reason": "why we need more detail",
      "sections_to_extract": ["products", "prices"]
    }
  ],
  "sufficient": false,
  "missing_info": "what info is still needed"
}
```

## Key Rules

1. **EXTRACT DIRECT INFO:** Pull out specific useful information, don't just note it exists.

2. **SELECTIVE LINKING:** Only follow links if the direct info is insufficient.

3. **PRESERVE SPECIFICS:** Keep vendor names, prices, product names when extracting info.
