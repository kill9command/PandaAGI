# Phase 0: Query Analyzer

Analyze the user query to produce a **natural language statement** of what the user wants.
Your `user_purpose` output flows to all downstream phases.

---

## Output Schema

```json
{
  "resolved_query": "query with references made explicit",
  "user_purpose": "Natural language statement of what the user wants (2-4 sentences)",
  "action_needed": "live_search | recall_memory | answer_from_context | navigate_to_site | execute_code | unclear",
  "data_requirements": {
    "needs_current_prices": true | false,
    "needs_product_urls": true | false,
    "needs_live_data": true | false,
    "freshness_required": "< 1 hour | < 24 hours | any | null"
  },
  "prior_context": {
    "continues_topic": "string or null",
    "prior_turn_purpose": "string or null",
    "relationship": "continuation | verification | modification | new_topic"
  },
  "mode": "chat | code",
  "was_resolved": true | false,
  "content_reference": {
    "title": "string or null",
    "content_type": "thread | article | product | video | null",
    "site": "string or null",
    "source_turn": "number or null"
  },
  "reasoning": "brief explanation"
}
```

---

## user_purpose Guidelines

Capture in natural language:
1. **What** the user wants (product, information, action)
2. **Why** (buying, learning, comparing, verifying)
3. **Priorities** ("cheapest" = price, "best" = quality)
4. **Constraints** (budget, requirements)
5. **Relationship** to prior turns

---

## action_needed

| Value | When to Use |
|-------|-------------|
| `live_search` | Needs current data from web (prices, products, news) |
| `recall_memory` | Asking about stored preferences or past conversations |
| `answer_from_context` | Can answer from context (greeting, simple follow-up) |
| `navigate_to_site` | Wants to go to a specific URL |
| `execute_code` | Code operations (file edits, git, tests) |
| `unclear` | Query is ambiguous |

---

## data_requirements

| Flag | When True |
|------|-----------|
| `needs_current_prices` | Shopping, price comparison |
| `needs_product_urls` | User will click to buy |
| `needs_live_data` | "today", "now", "current", "check again" |
| `freshness_required` | < 1 hour for prices, < 24 hours for reviews |

---

## prior_context.relationship

| Value | Meaning |
|-------|---------|
| `continuation` | Continues same inquiry |
| `verification` | "check again" - wants fresh data |
| `modification` | "what about X instead?" - same topic, different params |
| `new_topic` | Different topic |

---

## Mode Detection

- **Code:** File paths, git commands, code terms → `code`
- **Chat:** Shopping, URLs, research → `chat`
- **Default:** `chat`

---

## Examples

### Example 1: Commerce Query

**Query:** `[adjective] [product] with [feature]`

```json
{
  "resolved_query": "[adjective] [product] with [feature]",
  "user_purpose": "User wants to find and buy [product] with [feature]. [Priority word] indicates [price/quality] priority. Needs current prices from retailers with clickable URLs.",
  "action_needed": "live_search",
  "data_requirements": {
    "needs_current_prices": true,
    "needs_product_urls": true,
    "needs_live_data": true,
    "freshness_required": "< 1 hour"
  },
  "prior_context": {
    "continues_topic": null,
    "prior_turn_purpose": null,
    "relationship": "new_topic"
  },
  "mode": "chat",
  "was_resolved": false,
  "content_reference": null,
  "reasoning": "Commerce query with [priority]. Needs live search."
}
```

### Example 2: Verification Follow-up

**Query:** `check again` / `verify` / `refresh`

```json
{
  "resolved_query": "search again for [prior topic]",
  "user_purpose": "User wants to verify/refresh results from prior search. 'Check again' = wants NEW data, not cached. Run fresh research.",
  "action_needed": "live_search",
  "data_requirements": {
    "needs_current_prices": true,
    "needs_product_urls": true,
    "needs_live_data": true,
    "freshness_required": "< 1 hour"
  },
  "prior_context": {
    "continues_topic": "[topic from prior turn]",
    "prior_turn_purpose": "[purpose from prior turn]",
    "relationship": "verification"
  },
  "mode": "chat",
  "was_resolved": true,
  "content_reference": {
    "content_type": "product",
    "source_turn": "[N-1]"
  },
  "reasoning": "'Check again' = verification request. Wants fresh data."
}
```

### Example 3: Informational Query

**Query:** `how do I [task]` / `what is [topic]`

```json
{
  "resolved_query": "how do I [task]",
  "user_purpose": "User wants to learn about [topic]. Informational - not buying. Evergreen knowledge from guides is appropriate.",
  "action_needed": "live_search",
  "data_requirements": {
    "needs_current_prices": false,
    "needs_product_urls": false,
    "needs_live_data": false,
    "freshness_required": "any"
  },
  "prior_context": {
    "continues_topic": null,
    "prior_turn_purpose": null,
    "relationship": "new_topic"
  },
  "mode": "chat",
  "was_resolved": false,
  "content_reference": null,
  "reasoning": "Informational query. Evergreen knowledge acceptable."
}
```

---

## Do NOT

- Include concrete product names, brands, or prices in reasoning
- Guess at unstated user intent
- Set `needs_current_prices` for informational queries
- Miss "check again" / "verify" as verification requests
