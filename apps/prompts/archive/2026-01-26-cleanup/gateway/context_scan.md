# Context Gatherer - Scan Phase Prompt

## Purpose
Phase 1 of the 4-phase context gatherer. Identifies relevant turns from the turn index based on the current query.

## Prompt Template

CURRENT QUERY: {query}

TURN INDEX:
{turn_index}

Identify which turns are relevant and why. Output JSON.

## Expected Output Format

```json
{
  "relevant_turns": [
    {
      "turn_number": 5,
      "relevance": "critical|high|medium|low",
      "reason": "why this turn is relevant",
      "expected_info": "what info we expect to find"
    }
  ],
  "reasoning": "your overall reasoning process"
}
```

## Key Rules

1. **RULE ZERO (FOLLOW-UPS):** For follow-up queries (containing "it", "that", "some", "again", "more"), the N-1 turn (immediately preceding) is ALWAYS CRITICAL.

2. **RULE ONE (TOPIC RELEVANCE):** Only mark turns as relevant if their topic matches the current query.

3. **RULE TWO (RECENCY):** More recent turns are generally more relevant than older ones.
