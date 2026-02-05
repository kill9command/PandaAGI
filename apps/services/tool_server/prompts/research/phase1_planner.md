# Phase 1 Research Planner

Extract the topic keywords from this user query.

User Query: {query}

Rules:
- Output 2-5 words (the product/item type only)
- Remove conversational filler: find me, can you, help me, please, where, what is
- Remove subjective words: cheap, cheapest, best, good (these guide filtering, not search)
- KEEP: product type, brand, specs, price constraints
- Output ONLY plain text keywords, no formatting, no backticks, no quotes

Examples:
- "find cheap laptops with nvidia gpu" → laptop nvidia gpu
- "where can I buy syrian hamsters" → syrian hamsters
- "best mechanical keyboard under $100" → mechanical keyboard under $100

Output the topic keywords only:
