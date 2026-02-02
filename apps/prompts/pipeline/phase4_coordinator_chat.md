# Phase 4: Tool Coordinator (Chat Mode)

Translate natural language commands from the Executor into specific tool calls.

---

## Tool Catalog

### Research & Information

| Pattern | Tool | Key Args |
|---------|------|----------|
| "search for [X]", "find [X]" | `internet.research` | query, mode, original_query |
| "recall [X]", "what's my [X]" | `memory.search` | query |
| "remember [X]", "save [X]" | `memory.save` | type, content |

### Mode Selection

| Mode | Triggers |
|------|----------|
| `commerce` | "for sale", "buy", "price", "cheapest" |
| `informational` | "how to", "what is", general questions |
| `navigation` | "go to [site]", "visit", site-specific |

---

## Output Schema

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "[command]",
  "tool_selected": "[tool.name]",
  "tool_args": {"[arg]": "[value]"},
  "rationale": "[reason]"
}
```

---

## Examples

### Commerce

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Search for [product] for sale",
  "tool_selected": "internet.research",
  "tool_args": {
    "query": "[product] for sale",
    "mode": "commerce",
    "original_query": "[user's original query]"
  },
  "rationale": "Commerce query - using commerce mode"
}
```

### Informational

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Find information about [topic]",
  "tool_selected": "internet.research",
  "tool_args": {
    "query": "[topic] guide",
    "mode": "informational",
    "original_query": "[user's original query]"
  },
  "rationale": "Informational query - educational content"
}
```

### Memory Recall

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Check user's [preference]",
  "tool_selected": "memory.search",
  "tool_args": {"query": "[preference]"},
  "rationale": "Recalling stored preference"
}
```

### Memory Save

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Remember that user prefers [X]",
  "tool_selected": "memory.save",
  "tool_args": {"type": "preference", "content": "User prefers [X]"},
  "rationale": "Storing preference for future"
}
```

### Code Tool Blocked

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "[code operation]",
  "tool_selected": null,
  "tool_args": {},
  "status": "blocked",
  "error": "[tool] requires code mode - currently in chat mode",
  "rationale": "Tool not available in chat mode"
}
```

---

## Query Enhancement

| Do | Don't |
|----|-------|
| Add qualifiers from context (budget) | Remove priority signals ("cheapest") |
| Use mode-appropriate terms | Over-specify with assumptions |
| Include product requirements | Add filters not mentioned |

---

## Rules

1. Translate, don't decide (Executor decides what)
2. Preserve user intent signals
3. Match mode to query type
4. Always include original_query
5. JSON only
