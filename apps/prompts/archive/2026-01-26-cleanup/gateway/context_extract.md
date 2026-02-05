# Context Gatherer - Extract Phase Prompt

## Purpose
Phase 3 of the 4-phase context gatherer. Extracts relevant information from linked documents.

## Prompt Template

CURRENT QUERY: {query}

EXTRACTION FOCUS: {extraction_focus}

LINKED DOCUMENTS:
{linked_docs}

Extract relevant information for the query. Output JSON.

## Expected Output Format

```json
{
  "extracted": {
    "products": [
      {"name": "Product A", "price": "$999", "vendor": "Amazon"}
    ],
    "recommendations": ["recommendation 1", "recommendation 2"],
    "key_facts": ["fact 1", "fact 2"]
  },
  "need_more": false
}
```

## Key Rules

1. **FOCUS ON REQUEST:** Only extract information relevant to the extraction focus.

2. **PRESERVE STRUCTURE:** Keep product details, prices, and vendor information intact.

3. **BE CONCISE:** Extract key information, not entire document contents.
