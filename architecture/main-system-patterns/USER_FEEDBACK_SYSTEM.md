# User Feedback System

**Status:** SPECIFICATION
**Version:** 1.1
**Created:** 2025-12-29
**Updated:** 2026-01-05
**Architecture:** PandaAI v2 (8-Phase Pipeline)

---

## Overview

User satisfaction is tracked **implicitly** through conversation analysis - no UI buttons needed. The system detects when users correct, reject, or accept previous responses through their follow-up messages.

**Design Principle:** Let the conversation teach us. If a user corrects the system, that's negative feedback. If they continue productively, that's positive feedback.

**When Detection Happens:** Phase 2 (Context Gatherer) analyzes the user's message for feedback patterns about the previous turn.

**Why Phase 2:** User feedback affects context gathering. If the user rejected the previous response, Context Gatherer:
1. Marks the previous turn as rejected in TurnIndexDB
2. Adds rejection context to §2 (so Planner can avoid repeating the failed approach)
3. Filters the rejected strategy from future similarity searches

**Integration with context.md:** A rejected turn is indexed with `user_feedback_status = 'rejected'`, making it discoverable (with negative weight) for future similar queries.

---

## Feedback Detection Flow

```
+---------------------------------------------------------------------+
|                    USER FEEDBACK DETECTION                           |
+---------------------------------------------------------------------+
|                                                                      |
|  User sends new message (Turn N+1)                                   |
|      |                                                               |
|      v                                                               |
|  Phase 0: Query Analyzer (REFLEX)                                    |
|      |   - Classifies query type                                     |
|      |   - Resolves references ("that one" -> specific item)         |
|      |   - Does NOT detect feedback (that's Phase 2's job)           |
|      |                                                               |
|      v                                                               |
|  Phase 1: Reflection (REFLEX)                                        |
|      - Decides PROCEED or CLARIFY based on query clarity             |
|      |                                                               |
|      v                                                               |
|  Phase 2: Context Gatherer (MIND) analyzes:                          |
|      |                                                               |
|      +-> Is this a CORRECTION to Turn N?                             |
|      |       |                                                       |
|      |       +- Explicit: "No I meant...", "Wrong", "Try again"      |
|      |       +- Rephrased: Same query reworded (similarity >0.8)     |
|      |       +- Abandonment: "Let me rephrase", "Forget that"        |
|      |       |                                                       |
|      |       v                                                       |
|      |   YES -> Mark Turn N as REJECTED                              |
|      |          Add rejection context to section 2                   |
|      |          Filter Turn N from future strategy reuse             |
|      |                                                               |
|      +-> Is this a CONTINUATION of Turn N?                           |
|              |                                                       |
|              +- Follow-up question about response content            |
|              +- Drill-down request ("Tell me more about X")          |
|              +- New but related query                                |
|              |                                                       |
|              v                                                       |
|          YES -> Mark Turn N as ACCEPTED                              |
|                 Boost Turn N's strategy for future reuse             |
|                                                                      |
|          NO -> Leave Turn N as NEUTRAL                               |
|                (Session may have ended, unknown feedback)            |
|                                                                      |
+---------------------------------------------------------------------+
```

---

## Correction Detection

### Patterns

| Category | Pattern Examples | Description |
|----------|------------------|-------------|
| **Explicit Rejection** | "No, I meant...", "That's wrong", "Try again", "Not what I asked" | Direct correction statements |
| **Rephrased Query** | Same question reworded (similarity > 0.8) | User repeats query differently |
| **Abandonment** | "Never mind", "Forget that", "Let me rephrase", "Start over" | User gives up on current approach |

### Explicit Rejection Signals

| Signal | Examples |
|--------|----------|
| Negation at start | "No, ...", "Not what I..." |
| Correction phrase | "I meant...", "I want...", "I need..." |
| Direct rejection | "That's wrong", "You misunderstood" |
| Retry request | "Try again", "That doesn't help" |
| Quality complaint | "Not helpful", "Not useful", "Not what I need" |

### Rephrased Query Detection

| Condition | Threshold | Result |
|-----------|-----------|--------|
| Embedding similarity to previous query | > 0.8 | Likely correction |
| Same intent classification | Required | Confirms rephrasing |

### Detection Logic

**Input:** Current query, previous query, previous response, session context

**Output:** FeedbackResult containing:
- `feedback_type`: 'rejected' | 'accepted' | 'neutral'
- `confidence`: 0.0-1.0
- `correction_type`: 'explicit' | 'rephrased' | 'abandonment' | null
- `user_said`: The correction text (if rejected)

**Detection Priority Order:**

| Priority | Check | Result if Match |
|----------|-------|-----------------|
| 1 | Explicit rejection pattern | rejected (confidence: 0.9) |
| 2 | Query similarity > 0.8 to previous | rejected (confidence: similarity score) |
| 3 | Abandonment pattern | rejected (confidence: 0.85) |
| 4 | Continuation pattern | accepted (confidence: 0.7) |
| 5 | Default | neutral (confidence: 0.5) |

### Continuation Detection (Acceptance Signals)

| Pattern | Examples |
|---------|----------|
| Follow-up request | "Tell me more about...", "Can you explain..." |
| Drill-down | "What about the...", "Which one..." |
| Comparison | "Compare...", "Between..." |
| Continuation | "And...", "Also...", "What if..." |
| References response content | Mentions product name, price, or detail from response |

---

## Storage Schema

### metadata.json (per turn)

```json
{
  "turn_id": "turn_001233",
  "session_id": "henry",
  "timestamp": "2026-01-04T10:30:00Z",

  "validation_outcome": "APPROVE",
  "quality_score": 0.85,

  "user_feedback": {
    "status": "rejected",
    "detected_at": "2026-01-04T10:32:00Z",
    "detected_in_turn": "turn_001234",
    "correction_type": "explicit_correction",
    "confidence": 0.9,
    "user_said": "No, I meant gaming laptops not business laptops"
  }
}
```

### TurnIndexDB Schema

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `user_feedback_status` | TEXT | 'neutral' | 'rejected', 'accepted', or 'neutral' |
| `feedback_confidence` | REAL | 0.5 | 0.0-1.0 confidence in the feedback detection |
| `rejection_detected_in` | TEXT | null | Turn ID where rejection was detected |

**Index:** `idx_feedback_status` on `user_feedback_status` for filtering

---

## Context Gatherer Integration

### Section 2 Output When Correction Detected

```markdown
## 2. Gathered Context

### Previous Response Feedback
**Status:** REJECTED
**Detected:** Turn 1234 detected that Turn 1233 was rejected
**User said:** "No, I meant gaming laptops not business laptops"
**Previous strategy:** commerce_search with query "laptops under $1000"
**What went wrong:** Wrong product category - returned business laptops

**Instruction for Planner:**
- Do NOT reuse the strategy from Turn 1233
- User wants GAMING laptops, not business laptops
- Adjust search query to be specific: "gaming laptops under $1000"

### Conversation Context
...

### Session Preferences
...
```

---

## Learning Integration

### Strategy Search Filtering

When Context Gatherer (Phase 2) searches for similar past strategies:

| Feedback Status | Search Behavior |
|-----------------|-----------------|
| `rejected` | **Exclude** - Never reuse this strategy |
| `accepted` | **Boost** - Rank higher in results |
| `neutral` | **Include** - Use validation score for ranking |

**Search Order:**
1. Accepted turns (highest priority)
2. Neutral turns
3. Rejected turns (excluded)

Within each group, order by `quality_score DESC`.

### Satisfaction Score Calculation

Combines validation outcome with user feedback. Range: -1.0 to 1.0

| Validation Outcome | Base Score |
|--------------------|------------|
| APPROVE | 0.5 |
| REVISE | 0.3 |
| RETRY | 0.1 |
| FAIL | -0.5 |

| Feedback Status | Final Score |
|-----------------|-------------|
| `rejected` | -1.0 (overrides validation) |
| `accepted` | base + 0.5 (capped at 1.0) |
| `neutral` | base score (use validation only) |

**Key Principle:** User rejection is the strongest signal - it overrides even a successful validation.

---

## Phase Integration Summary

| Phase | Model Layer | Feedback Responsibility |
|-------|-------------|------------------------|
| **Phase 0: Query Analyzer** | REFLEX (Qwen3-0.6B) | Classifies query type (runs BEFORE feedback detection) |
| **Phase 1: Reflection** | REFLEX (Qwen3-0.6B) | Decides PROCEED or CLARIFY based on query clarity |
| **Phase 2: Context Gatherer** | MIND (Qwen3-Coder-30B) | Detect corrections, update previous turn, add feedback context to section 2 |
| **Phase 3: Planner** | MIND (Qwen3-Coder-30B) | See rejection context in §2, avoid repeating failed strategy |
| **Phase 7: Save** | (No LLM) | Store feedback status in metadata.json and TurnIndexDB |

---

## Edge Cases

### Multiple Corrections in Sequence

If user corrects multiple times in a row:
1. Each correction marks the previous turn as rejected
2. Planner sees pattern: "Multiple rejections - be more careful"
3. Consider CLARIFY more often to avoid further frustration

### Ambiguous Feedback

If unclear whether message is correction or new topic:
- Default to "neutral" (conservative)
- Don't mark previous turn as rejected unless confident

### Session Boundaries

If no message follows a turn (session ends):
- Turn remains "neutral"
- Slightly lower confidence for reuse than "accepted" turns

---

## Feedback Status Definitions

### Status Definitions

| Status | Trigger | Examples |
|--------|---------|----------|
| **REJECTED** | Next turn contains correction signals | "No", "Wrong", "That's not what I meant", "Try again", same query rephrased |
| **ACCEPTED** | Next turn shows continuation or satisfaction | "Tell me more", "I'll go with that one", "Thanks", new unrelated query |
| **NEUTRAL** | No clear signal | Session ended (30+ min timeout), ambiguous query |

### Rejection Signals (Detail)

| Type | Examples |
|------|----------|
| Explicit | "no", "wrong", "that's not what I meant", "actually", "try again" |
| Implicit | Same intent rephrased (embedding similarity > 0.85) |
| Abandonment | "never mind", "forget that", "let me rephrase" |

### Acceptance Signals (Detail)

| Type | Examples |
|------|----------|
| Follow-up | "Tell me more about the first one" |
| Action taken | "I'll go with the Lenovo", "Thanks, ordering now" |
| Topic change | New unrelated query (implies satisfaction - user moved on) |

**Important:** "New unrelated query" = implicit acceptance. If user asks about laptops, gets answer, then asks about hamster food, the laptop response is marked ACCEPTED.

### Ranking Impact

| Status | Weight | Effect |
|--------|--------|--------|
| `rejected` | -1.0 | Never reuse this strategy |
| `accepted` | +0.5 | Prefer this strategy |
| `neutral` | 0.0 | Use validation score only |

**Final Ranking Formula:**
```
ranking_score = (validation_quality * 0.6) + (feedback_weight * 0.4)
```

### Session Timeout

- No follow-up within 30 minutes → session ended
- Turn marked as NEUTRAL
- Neutral turns rank below accepted turns in searches

---

## Related Documents

- `architecture/LLM-ROLES/llm-roles-reference.md` - Model stack and layer assignments
- `architecture/main-system-patterns/phase0-query-analyzer.md` - Phase 0 details
- `architecture/main-system-patterns/phase1-reflection.md` - Phase 1 details
- `architecture/main-system-patterns/phase2-context-gathering.md` - Phase 2 details (where detection happens)
- `architecture/main-system-patterns/phase7-save.md` - Turn persistence (stores feedback status)

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-29 | Initial specification |
| 1.1 | 2026-01-05 | Removed implementation code, converted to tables/specification format |

---

**Last Updated:** 2026-01-05
