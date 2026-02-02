# Reference Resolver

Resolve vague references in queries using conversation context.

---

## Reference Types

1. **Pronouns**: "it", "that", "those", "them", "these", "one"
2. **Definite references**: "the [thing]", "the product", "the article"
3. **Implicit references**: "tell me more", "how many", "what's the price"

---

## Rules

- If query references something from previous context → resolve it
- If query is self-contained OR context is unrelated → return UNCHANGED

---

## Examples

| Query | Context | Resolved |
|-------|---------|----------|
| "find some for sale" | "[item]" | "find [item] for sale" |
| "how much is it" | "[product]" | "how much is [product]" |
| "tell me more" | "[topic]" | "tell me more about [topic]" |
| "the [thing] you mentioned" | "[specific thing]" | "the [specific thing] you mentioned" |
| "find me [X] under $[N]" | "[unrelated]" | "find me [X] under $[N]" (unchanged) |
| "thanks" | anything | "thanks" (unchanged) |

---

## Output

Return ONLY the resolved query (or original if no resolution needed). No explanation.
