# Phase 5: Synthesis - User Prompt Template

## Original Query

{original_query}

## Context Document

{context_md}

## Tool Results (if applicable)

{tool_results_md}

## Revision Hints (if REVISE)

{revision_hints}

## Your Task

Generate a natural, engaging response for the user based on the context above.

### Guidelines

1. **Use ONLY data from the context**: Do not invent prices, products, or facts
2. **Match the intent**: Format response appropriately for the query type (commerce, query, recall, etc.)
3. **Include clickable links**: Convert all URLs to markdown format `[text](url)`
4. **Be conversational**: You are the voice the user hears - be helpful and natural
5. **Cite sources**: Link claims to where they came from

### Data Priority

- Section 4 (Tool Execution): Primary source for fresh data (prices, products)
- Section 2 (Gathered Context): Supplementary context (preferences, prior findings)
- If Section 4 has newer data than Section 2, use Section 4

### If Data is Missing

If the context lacks information to fully answer the query:
- Acknowledge what you DO have
- Note what's missing
- Offer to search again or provide alternatives

Output your SynthesisResult JSON.
