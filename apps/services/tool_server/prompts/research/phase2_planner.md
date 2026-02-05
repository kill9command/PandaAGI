# Phase 2 Research Planner

You are planning Phase 2 research (finding actual products from vendors).

## User Query

{query}

## Phase 1 Intelligence

{phase1_intelligence}

## Phase 2 Goal

Find and extract actual products from vendors discovered in Phase 1.

## Query Formats

Phase 2 uses these search patterns (code adds year automatically):

1. WITH vendors from Phase 1: `{{vendor}} {{topic}} {{year}}`
   - Example: "newegg cheap laptop nvidia gpu 2025"
   - Example: "amazon syrian hamsters 2025"

2. FALLBACK (no vendors): `{{topic}} for sale {{year}}`
   - Example: "cheap laptop nvidia gpu for sale 2025"

## Task

Extract the core topic keywords from the query.

## Rules

- Output 2-5 words (the product/item only)
- Remove conversational filler: "find me", "can you", "help me", "please", "where", "what is"
- Remove subjective words: "cheap", "cheapest", "best", "good" (these guide filtering, not search)
- KEEP: product type, brand, specs, price constraints (under $X)
- Output ONLY plain text keywords, no formatting, no backticks, no quotes

## Examples

- "find cheap laptops with nvidia gpu" → laptop nvidia gpu
- "best mechanical keyboard under $100" → mechanical keyboard under $100

## Output

Topic:
