# Phase 3: Planner - User Prompt Template

## Context Document (Sections 0-2)

{context_md}

## Your Task

Analyze the query and gathered context to create a task plan. Determine:

1. **Can we answer from context?** Look at Section 2 - is the gathered context sufficient?
2. **Do we need tools?** If context is missing or stale, plan tool calls
3. **What's the intent?** Classify the query intent for downstream phases

### Decision Guide

- If Section 2 has fresh, relevant data for the query -> route to `synthesis`
- If data is missing, stale, or research is needed -> route to `coordinator` with tool_requests
- If query is still ambiguous after context -> route to `clarify` (rare)

### Memory Pattern Detection

Check if the query contains memory operations:
- "remember that..." / "my X is..." -> include memory.save tool
- "what's my..." / "what did I say about..." -> include memory.search tool
- "forget that..." / "I no longer..." -> include memory.delete tool

### IMPORTANT: Context Discipline

When creating tool_requests, ALWAYS include the original user query in `args.original_query`. This preserves user priority signals like "cheapest", "best", "fastest" that the LLM needs to make good decisions.

Output your TaskPlan JSON.
