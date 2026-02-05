# Delegation Workflow

## 🎯 When to Delegate (Issue TICKET)

Issue a TICKET when you need:
- **Fresh data**: Prices, availability, current events, repository state, API responses
- **Version information**: Package versions, API versions, dependency specs, library documentation
- **Code execution**: Bash commands, file operations (read/write/edit), test runs, git operations
- **Retrieval**: Search across documents, web research, documentation lookup, multi-file grep
- **Verification**: Numbers, dates, measurements, specifications that require citation from tools

Do NOT issue a TICKET when:
- Injected context already contains the answer (check capsule claims, user memories)
- Question can be answered from general knowledge
- User is asking about conversation history (check `solver_self_history`)
- Capsule claims are fresh and still within TTL

## 🔍 Delegation Simplified (NEW: 2025-11-15)

**The Coordinator now has `internet.research`** - an adaptive research system that automatically selects the optimal strategy.

**What `internet.research` does:**
- Analyzes your query and session context
- Automatically selects QUICK (fast), STANDARD (cached), or DEEP (full research) strategy
- Reuses cached intelligence from previous queries (40-60% token savings!)
- Uses LLM filtering to visit only high-quality sources

**The Three Strategies (Auto-Selected):**
- **QUICK**: Fast lookups, no intelligence gathering (30-60s)
- **STANDARD**: Reuses cached intelligence from prior research (60-120s)
- **DEEP**: Full intelligence + product search, caches for future (120-180s)

**Your role:** Keep tickets simple. Just specify "search for X" or "find Y".

**Example:**
```json
{
  "_type": "TICKET",
  "goal": "Find Syrian hamsters for sale online",
  "micro_plan": ["Search for hamsters available for purchase"]
}
```

The system automatically:
- Selects DEEP strategy (first query on this topic)
- Gathers intelligence from forums, reviews, breeders
- Searches for products using intelligence
- Caches intelligence for follow-up queries

**Follow-up queries reuse cache automatically:**
```json
{
  "_type": "TICKET",
  "goal": "Show me hamsters under $30",
  "micro_plan": ["Filter results by price"]
}
```
System selects STANDARD strategy and reuses cached intelligence (2-3x faster!)
