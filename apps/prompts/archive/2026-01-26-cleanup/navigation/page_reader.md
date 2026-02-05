# Page Reader

You are reading a webpage to extract useful information.

## Context

URL: {url}
PAGE TYPE: {page_type}
READING GOAL: {goal}

## Content

{content}

## Extraction Instructions

{extraction_prompt}

## Guidelines

- Extract information as JSON
- Be thorough but only extract what's actually present
- Do not hallucinate or make up information
- If information is missing, use null or empty values
- **IMPORTANT**: If extracting products, limit to the TOP 10 most relevant products to avoid truncation

## Extraction Templates by Page Type

### Product Listing
```json
{
  "products": [
    {
      "title": "...",
      "price": number or null,
      "currency": "USD|EUR|GBP|etc",
      "availability": "in_stock|out_of_stock|unknown",
      "specs": {"key": "value"},
      "vendor": "...",
      "location": "..." or null
    }
  ]
}
```

### Forum Discussion
```json
{
  "discussion_topic": "...",
  "key_recommendations": ["...", "..."],
  "mentioned_vendors": [{"name": "...", "sentiment": "positive|negative|neutral", "context": "..."}],
  "helpful_tips": ["...", "..."],
  "warnings": ["...", "..."],
  "community_consensus": "..."
}
```

### Research Paper
```json
{
  "title": "...",
  "authors": ["..."],
  "abstract": "...",
  "key_findings": ["...", "..."],
  "methodology": "...",
  "conclusions": "...",
  "limitations": ["..."],
  "doi": "..." or null
}
```

### News Article
```json
{
  "headline": "...",
  "date": "...",
  "author": "...",
  "summary": "...",
  "key_facts": ["...", "..."],
  "entities_mentioned": [{"name": "...", "type": "person|org|location", "role": "..."}]
}
```

### Guide/Tutorial
```json
{
  "title": "...",
  "topic": "...",
  "steps": [{"step": 1, "instruction": "...", "details": "..."}],
  "tips": ["...", "..."],
  "requirements": ["...", "..."],
  "warnings": ["...", "..."]
}
```

### Vendor Directory
```json
{
  "vendors": [
    {
      "name": "...",
      "type": "breeder|store|marketplace|other",
      "location": "...",
      "contact": "...",
      "specialties": ["..."]
    }
  ]
}
```

### General (flexible structure)
```json
{
  "main_topic": "...",
  "key_information": ["...", "..."],
  "relevant_details": {"key": "value"},
  "actionable_insights": ["...", "..."]
}
```
