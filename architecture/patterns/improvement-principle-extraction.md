# Improvement Principle Extraction

## Overview

When a response goes through revision (REVISE → APPROVE), the system extracts a transferable principle explaining **why the revision was better**. These principles are stored in Memory Bank and retrieved for future similar queries.

## Architecture

```
Iteration 1: Synthesis → Validator (REVISE, hints: "use table format")
                              ↓
                    Store: original_response, revision_hints
                              ↓
Iteration 2: Synthesis (with hints) → Validator (APPROVE)
                              ↓
                    PrincipleExtractor (async, non-blocking)
                              ↓
                    Memory Bank: Improvements/Principles/
                              ↓
Future queries: Context Gatherer → Principles in §1
```

## Implementation

### Key Files

| File | Purpose |
|------|---------|
| `libs/gateway/principle_extractor.py` | Extraction logic and storage |
| `libs/gateway/unified_flow.py` | Integration in validation loop |
| `apps/tools/memory/models.py` | Search path configuration |

### Trigger Condition

Principle extraction triggers when:
1. `decision == "APPROVE"` in validation
2. `revision_count > 0` (at least one revision happened)
3. `revision_hints_for_principle` is not empty

### Extraction Flow

```python
# In unified_flow.py _phase6_validation()
if revision_count > 0 and revision_hints_for_principle:
    extractor = PrincipleExtractor(self.llm_client)
    asyncio.create_task(
        extractor.extract_and_store(
            original_response=original_response_for_principle,
            revised_response=response,
            revision_hints=revision_hints_for_principle,
            query=query_section[:500],
            turn_id=turn_id,
            revision_focus=revision_focus_for_principle,
        )
    )
```

### Principle Format

Principles are stored as markdown files:

```markdown
---
category: formatting
trigger_pattern: price comparison queries
source_turn: turn_001234
confidence: 0.8
created_at: 2026-01-24T15:00:00
tags: [improvement-principle, formatting]
---

# Price Comparison Table Format

When presenting price comparisons, use a markdown table with columns
for Product, Price, and Source rather than prose paragraphs.

## Why This Works

Users can scan tables faster than reading sentences. Side-by-side
comparison is more intuitive for decision-making.

## Pattern

**Original issue:** Response listed prices in paragraph form.

**Successful fix:** Converted to table format with clear headers.
```

### Storage Location

Principles are stored in:
```
panda_system_docs/obsidian_memory/Improvements/Principles/
```

This path is included in `searchable_paths` so Context Gatherer automatically retrieves relevant principles via semantic search.

## Retrieval

Principles are retrieved like any other memory:

1. Context Gatherer Phase 2 searches all `searchable_paths`
2. Semantic similarity matches query to principle trigger patterns
3. Relevant principles appear in §1 with other context

No special retrieval logic needed - the existing memory search handles it.

## Design Decisions

### Async Extraction

Principle extraction runs as `asyncio.create_task()` (fire-and-forget):
- **Pro**: No latency impact on response delivery
- **Pro**: Extraction failure doesn't break validation
- **Con**: Might miss some extractions if process exits

### Truncation

Original and revised responses are truncated to 800 chars each:
- Keeps extraction prompt small (~500 tokens output budget)
- Uses 60% start + 40% end to capture key differences

### Confidence

All extracted principles start at confidence 0.8. Future enhancement could:
- Track principle usage and success
- Adjust confidence based on validation outcomes

## Token Budget

| Component | Tokens |
|-----------|--------|
| Extraction prompt | ~400 |
| Truncated responses | ~300 each |
| Output | ~150 |
| **Total** | ~1150 |

Uses REFLEX role (temp 0.3) for consistent, structured output.

## Example

**Query**: "find the cheapest gaming laptops"

**Original response** (got REVISE):
```
The MSI Thin costs $749.99 at Amazon. The ASUS TUF Dash F15 costs
$799.99 at Best Buy. The Lenovo IdeaPad Gaming 3 costs $649.99...
```

**Revision hints**: "Use table format for price comparisons"

**Revised response** (got APPROVE):
```
| Laptop | Price | Retailer |
|--------|-------|----------|
| Lenovo IdeaPad Gaming 3 | $649.99 | Amazon |
| MSI Thin | $749.99 | Amazon |
| ASUS TUF Dash F15 | $799.99 | Best Buy |
```

**Extracted principle**:
- Category: `formatting`
- Trigger: `price comparison queries`
- Description: "When comparing multiple products by price, use a table format with Product, Price, and Retailer columns for easy scanning."

**Future query**: "compare prices for mechanical keyboards"

Context Gatherer finds the principle via semantic match ("price comparison") and includes it in §1. Synthesizer sees the principle and uses table format from the start.
