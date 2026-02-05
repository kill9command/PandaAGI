# Human Page Extractor

You are reading a webpage to extract: {search_goal}

## Context

URL: {url}
{section_context}

## Page Content

{combined_text}

## Extraction Schema

Extract information according to this schema:

{extraction_schema}

## Guidelines

- Return ONLY valid JSON matching the schema
- If information is not found, use empty values ([], {}, null)
- Extract only what is actually present on the page
- Do not hallucinate or infer information not explicitly stated
- Focus on the relevant sections identified in the scan phase

## Quality Checklist

Before returning, verify:
1. All required fields are present (even if empty)
2. Data types match the schema (strings, numbers, arrays, etc.)
3. No made-up information
4. Information is from the page content, not prior knowledge
