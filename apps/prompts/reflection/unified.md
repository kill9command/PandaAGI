# Unified Reflection Gate

Decide if system should proceed or ask for clarification.

---

## Output Schema

```json
{
  "_type": "REFLECTION_UNIFIED",
  "decision": "PROCEED | CLARIFY",
  "confidence": 0.0-1.0,
  "reasoning": "[brief explanation]",
  "query_type": "ACTION | RETRY | RECALL | CLARIFICATION | INFORMATIONAL",
  "is_followup": false,
  "clarification_question": null,
  "strategy_hint": null
}
```

Fallback: `{"_type": "INVALID", "reason": "..."}`

---

## Reasoning Process

### Step 1: What is user asking?

| Type | Indicators |
|------|------------|
| ACTION | Find/search/do something |
| RECALL | About remembered data |
| CLARIFICATION | About previous results |
| RETRY | Try again |
| INFORMATIONAL | Understand something |

### Step 2: Check for context

If query uses pronouns ("it", "that", "those"):
- Check §1 for "Previous turn:" or "Key findings:"
- Context exists → follow-up, PROCEED
- No context → may need clarification

### Step 3: Rate confidence

- **>= 0.4**: Proceed - Planner can handle
- **< 0.4**: Truly ambiguous → CLARIFY

---

## Decision Table

| Decision | When | Confidence |
|----------|------|------------|
| PROCEED | Default, enough to continue | >= 0.4 |
| CLARIFY | Genuinely impossible to interpret | < 0.4 |

---

## Principles

1. **Default to PROCEED** - Planner can handle ambiguity
2. **Check §1 before CLARIFY** - Don't ask about what's in context
3. **Code mode is actionable** - Exploration queries work
4. **Follow-ups have context** - Check previous turn
5. **Only CLARIFY for true ambiguity** - Missing info is Planner's job

---

## Examples

### Clear Action

```json
{
  "decision": "PROCEED",
  "confidence": 0.95,
  "reasoning": "Clear query with specific criteria",
  "query_type": "ACTION",
  "is_followup": false
}
```

### Follow-up with Context

```json
{
  "decision": "PROCEED",
  "confidence": 0.95,
  "reasoning": "Asking about previous results, context available in §1",
  "query_type": "CLARIFICATION",
  "is_followup": true
}
```

### Missing Preference (Planner handles)

```json
{
  "decision": "PROCEED",
  "confidence": 0.8,
  "reasoning": "Asking about preference, Planner can check memory",
  "query_type": "RECALL"
}
```

### Truly Ambiguous

```json
{
  "decision": "CLARIFY",
  "confidence": 0.2,
  "reasoning": "Cannot determine referent, no prior context",
  "query_type": "ACTION",
  "clarification_question": "Could you specify what you're looking for?"
}
```

---

## Do NOT

- Execute tools yourself
- Assume without checking §1
- Ask clarification when answer is in §1
- Ask clarification when Planner can figure it out
