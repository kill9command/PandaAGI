# Reference Resolver

Resolve references in queries using conversation context.

## Current Query

{query}

## Previous Context

{context}

## Task

Check if the query references something from the previous context. References include:

1. **Pronouns**: "it", "that", "those", "them", "these", "some", "one"
2. **Definite references**: "the thread", "the laptop", "the product", "the article", "the post"
3. **Implicit references**: "tell me more", "how many pages", "what's the price"

If the query references something specific from the previous context, resolve it by making the reference explicit.

If the query is already self-contained OR the previous context is unrelated, return it UNCHANGED.

## Examples

- "find some for sale" + prev="Syrian hamster" → "find Syrian hamsters for sale"
- "how much is it" + prev="RTX 4060 laptop" → "how much is the RTX 4060 laptop"
- "how many pages is the thread" + prev="Best glass scraper thoughts? thread" → "how many pages is the 'Best glass scraper thoughts?' thread"
- "the laptop you mentioned" + prev="Lenovo LOQ gaming laptop" → "the Lenovo LOQ gaming laptop you mentioned"
- "tell me more" + prev="reef tank discussion" → "tell me more about reef tanks"
- "find me laptops under $1000" + prev="hamsters" → "find me laptops under $1000" (unchanged - already explicit)
- "thanks" + prev="anything" → "thanks" (unchanged - not a reference)

## Output

Return ONLY the resolved query (or original if no resolution needed). No explanation.
