# Intent System Migration Plan

**Status:** DRAFT
**Created:** 2026-01-27
**Goal:** Replace rigid intent categories with natural language "user_purpose" statements

---

## 1. Problem Statement

### Current System (Rigid Categories)

Phase 0 classifies queries into predefined categories:
```json
{
  "intent": "commerce",
  "query_type": "followup",
  "intent_metadata": {"product": "laptop", "constraints": ["cheapest"]}
}
```

This leads to **hardcoded programmatic checks** throughout the codebase:
```python
if intent == "commerce":
    # do commerce thing
elif intent == "informational":
    # do informational thing
```

**Problems:**
1. Rigid categories can't express nuance ("user wants cheap but also quality")
2. Intent inheritance is brittle (followups lose context)
3. Code has 25+ `if intent == X` checks scattered across 40+ files
4. Violates CLAUDE.md: "If LLM makes bad decisions, fix is better context, NOT hardcoded workarounds"

### Proposed System (Natural Language)

Phase 0 extracts a **natural language statement** of what the user wants:
```json
{
  "resolved_query": "search again for the cheapest laptop with nvidia GPU",
  "user_purpose": "User wants to find and buy the cheapest laptop with an nvidia GPU. Price is the top priority. This is a follow-up to the previous search - user wants fresh/updated results.",
  "requires_live_data": true,
  "references_prior_turn": true
}
```

**Benefits:**
1. More expressive - captures nuance and priorities
2. LLM-native - downstream LLMs interpret naturally
3. No programmatic branching on intent values
4. Followups work automatically (purpose explains relationship)

---

## 2. Affected Files Analysis

### 2.1 Core Data Structures (MUST CHANGE)

| File | Current Usage | Migration Impact |
|------|---------------|------------------|
| `libs/gateway/query_analyzer.py` | Defines `QueryAnalysis.intent` | Replace with `user_purpose` field |
| `libs/gateway/context_document.py` | `get_intent()`, `set_section_0()` | Replace with `get_user_purpose()` |
| `apps/prompts/pipeline/phase0_query_analyzer.md` | Intent classification examples | Rewrite for user_purpose extraction |

### 2.2 Programmatic Intent Checks (MUST REMOVE)

| File | Lines | What It Does | Migration Strategy |
|------|-------|--------------|-------------------|
| `apps/services/orchestrator/internet_research_mcp.py` | 247, 261 | `intent == "informational"` → phase1_only | Move to prompt context |
| `libs/gateway/research_index_db.py` | 567, 569 | Cache matching by intent | Match by semantic similarity or purpose keywords |
| `apps/services/gateway/intent_weights.py` | 38-81 | Intent → weight profiles | LLM decides weights from purpose |
| `libs/gateway/unified_flow.py` | 1702 | Navigation/site_search logging | Remove or use purpose keywords |

### 2.3 Prompts That Reference Intent (UPDATE)

| File | Change |
|------|--------|
| `apps/prompts/pipeline/phase0_query_analyzer.md` | Rewrite entirely for user_purpose |
| `apps/prompts/pipeline/phase3_planner_chat.md` | Remove "trust pre-classified intent", read user_purpose |
| `apps/prompts/pipeline/phase3_planner_code.md` | Same |
| `apps/recipes/recipes/pipeline/phase0_query_analyzer.yaml` | Update schema |

### 2.4 Caching & Storage (UPDATE)

| File | Change |
|------|--------|
| `libs/gateway/research_index_db.py` | Store/match on purpose, not intent |
| `libs/gateway/turn_saver.py` | Save user_purpose to turn metadata |
| `libs/gateway/turn_index_db.py` | Index by purpose keywords |

### 2.5 Tests (UPDATE)

| File | Change |
|------|--------|
| `tests/golden_queries/test_electronics_queries.py` | Update assertions |
| `tests/golden_queries/test_pets_queries.py` | Update assertions |
| `scripts/test_intent_classification.py` | Rewrite for user_purpose |

---

## 3. New Schema Design

### 3.1 Phase 0 Output (QueryAnalysis)

**OLD:**
```json
{
  "resolved_query": "...",
  "query_type": "followup",
  "intent": "commerce",
  "intent_metadata": {"product": "laptop"},
  "mode": "chat",
  "content_reference": {...}
}
```

**NEW:**
```json
{
  "resolved_query": "search again for the cheapest laptop with nvidia GPU",
  "user_purpose": "User wants to find and buy the cheapest laptop with an nvidia GPU. Price is the top priority ('cheapest'). This continues their previous laptop search - they want updated/fresh results, not cached data.",
  "action_needed": "live_search",
  "data_requirements": {
    "needs_current_prices": true,
    "needs_product_urls": true,
    "freshness_required": "< 1 hour"
  },
  "prior_context": {
    "continues_topic": "laptop shopping",
    "prior_turn_purpose": "Find cheapest nvidia laptop",
    "relationship": "verification/refresh request"
  },
  "mode": "chat"
}
```

### 3.2 Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `resolved_query` | string | Query with references made explicit |
| `user_purpose` | string | **Natural language statement** of what user wants (2-4 sentences) |
| `action_needed` | enum | `live_search`, `recall_memory`, `answer_from_context`, `navigate_to_site`, `unclear` |
| `data_requirements` | object | What kind of data is needed to satisfy the request |
| `prior_context` | object | How this relates to previous turns |
| `mode` | enum | `chat` or `code` |

### 3.3 user_purpose Guidelines

The `user_purpose` field should capture:
1. **What** the user wants (product, information, action)
2. **Why** they want it (buying, learning, comparing)
3. **Priorities** ("cheapest" = price priority, "best" = quality priority)
4. **Constraints** (budget, brand preferences, requirements)
5. **Relationship to prior turns** (new topic, continuation, verification)

**Good user_purpose examples:**
```
"User wants to buy a laptop with an nvidia GPU. Price is the top priority - they said 'cheapest'. They need current prices from online retailers with working URLs."

"User wants to verify the laptop prices from the previous search are still accurate. This is a follow-up to turn N-1 where we found MSI at $699. They want fresh data, not cached results."

"User wants to learn about hamster care, specifically for Syrian hamsters. This is informational research - they're not buying anything. Evergreen knowledge is acceptable."

"User wants to navigate to Amazon.com and search for RTX 4060 laptops. They want to see the actual Amazon page, not cached results."
```

---

## 4. Implementation Phases

### Phase 1: Add New Fields (Non-Breaking)

**Goal:** Add `user_purpose` alongside existing `intent` field

1. **Update QueryAnalysis dataclass** (`query_analyzer.py`)
   ```python
   @dataclass
   class QueryAnalysis:
       resolved_query: str
       user_purpose: str = ""  # NEW
       action_needed: str = "unclear"  # NEW
       data_requirements: Dict[str, Any] = None  # NEW
       prior_context: Dict[str, Any] = None  # NEW
       # Keep legacy fields for now
       intent: str = "informational"
       query_type: str = "general_question"
   ```

2. **Update Phase 0 prompt** to generate `user_purpose`
   - Add examples showing user_purpose generation
   - Keep generating `intent` for backward compatibility

3. **Update context_document.py**
   - Add `get_user_purpose()` method
   - Keep `get_intent()` working

4. **Update context.md §0 format**
   - Include both `user_purpose` and legacy `intent`

**Tests:** Verify existing tests still pass, new field is populated

### Phase 2: Update Prompts to Read user_purpose

**Goal:** LLM roles read `user_purpose` instead of checking `intent`

1. **Update Phase 3 Planner prompt**
   - Remove "trust pre-classified intent"
   - Add "Read user_purpose from §0 to understand what user wants"
   - Update routing logic examples to show reading purpose

2. **Update Phase 4 Coordinator prompt** (if exists)
   - Read user_purpose for tool selection decisions

3. **Update Phase 5 Synthesis prompt**
   - Use user_purpose for response framing

**Tests:** Manual testing of full pipeline with new prompts

### Phase 3: Remove Programmatic Intent Checks

**Goal:** Eliminate `if intent == X` code

1. **internet_research_mcp.py** (lines 247, 261)
   - Before: `if intent == "informational": phase1_only = True`
   - After: Pass `user_purpose` to research, let it decide phases
   - Or: Check `data_requirements.needs_product_urls` boolean

2. **intent_weights.py** (entire file)
   - Option A: Delete file, let LLM decide weights from purpose
   - Option B: Extract keywords from purpose to select weights
   - Option C: Keep as fallback, reduce reliance over time

3. **research_index_db.py** (lines 567-572)
   - Before: `if entry.intent == query_intent`
   - After: Semantic similarity of `user_purpose` strings
   - Or: Match on `action_needed` field

4. **unified_flow.py** (line 1702)
   - Remove navigation/site_search special logging
   - Use `action_needed` field if needed

**Tests:** Full integration tests after each removal

### Phase 4: Update Caching & Storage

**Goal:** Store and match on purpose, not intent

1. **research_index_db.py**
   - Store `user_purpose` in cache entries
   - Match based on purpose similarity (not exact intent match)

2. **turn_saver.py**
   - Save `user_purpose` to turn metadata
   - Index for future turn lookups

3. **turn_index_db.py**
   - Add purpose to search index
   - Enable semantic search on purpose

**Tests:** Verify cache hits/misses work correctly

### Phase 5: Deprecate Legacy Fields

**Goal:** Remove `intent`, `query_type`, `intent_metadata`

1. Add deprecation warnings to `get_intent()`, etc.
2. Update all tests to use new fields
3. After 2 weeks with no issues, remove legacy fields
4. Update architecture docs

---

## 5. Migration Strategy for Programmatic Checks

### 5.1 `if intent == "informational"` → What?

**Current code:**
```python
if intent == "informational":
    phase1_only = True  # Skip product extraction
```

**Options:**

**Option A: Check data_requirements**
```python
if not data_requirements.get("needs_product_urls"):
    phase1_only = True
```

**Option B: Check action_needed**
```python
if action_needed == "answer_from_context":
    phase1_only = True
```

**Option C: Pass to LLM (best)**
- Include `user_purpose` in research prompt
- LLM decides whether to extract products or just facts
- No programmatic branching

### 5.2 `if intent == "commerce"` → What?

**Current code:**
```python
if intent == "commerce":
    verify_urls = True
    check_freshness = True
```

**Migration:**
```python
if data_requirements.get("needs_product_urls"):
    verify_urls = True
if data_requirements.get("freshness_required"):
    check_freshness = True
```

Or better: Pass `user_purpose` to validation, let LLM decide what to check.

### 5.3 Intent Weights → What?

**Current code:**
```python
weights = get_intent_weights(intent)  # Returns hardcoded profile
```

**Option A: Keyword extraction**
```python
def get_weights_from_purpose(user_purpose: str) -> IntentWeights:
    if "buy" in purpose or "price" in purpose or "cheapest" in purpose:
        return TRANSACTIONAL_WEIGHTS
    elif "learn" in purpose or "how does" in purpose:
        return INFORMATIONAL_WEIGHTS
    # etc.
```

**Option B: Let LLM decide (better)**
- Pass user_purpose to context gatherer prompt
- LLM decides what context sources are relevant
- No hardcoded weight profiles

---

## 6. Testing Strategy

### 6.1 Unit Tests

| Test | What It Validates |
|------|-------------------|
| `test_phase0_user_purpose.py` | user_purpose is generated correctly |
| `test_purpose_continuity.py` | Followups reference prior purpose |
| `test_data_requirements.py` | Requirements correctly extracted |

### 6.2 Integration Tests

| Test | What It Validates |
|------|-------------------|
| `test_commerce_flow.py` | Commerce queries trigger research |
| `test_followup_flow.py` | "check again" triggers refresh |
| `test_informational_flow.py` | Info queries return facts, not products |

### 6.3 Golden Query Tests

Update existing golden query tests to validate:
- `user_purpose` captures the right information
- `action_needed` matches expected behavior
- Pipeline produces correct results

---

## 7. Rollback Plan

If issues arise:
1. **Phase 1-2:** Just revert prompt changes, code still uses `intent`
2. **Phase 3:** Restore `if intent ==` checks, they still work
3. **Phase 4:** Cache has both fields, can match on either
4. **Phase 5:** Don't do this until confident

---

## 8. Success Criteria

1. **No `if intent == X` in hot path** (except deprecation logging)
2. **"check again" triggers research** (user_purpose captures continuation)
3. **Prompts read user_purpose** (not intent categories)
4. **Tests pass** with new schema
5. **Cache hit rate maintained** (semantic matching works)

---

## 9. Open Questions

1. **How to handle mode?** Keep `mode: chat | code` or fold into purpose?
2. **Cache key generation?** Hash of purpose or extract keywords?
3. **Intent weights?** Delete entirely or keep as fallback?
4. **Backward compatibility?** How long to maintain legacy `intent` field?

---

## 10. Files to Modify (Summary)

### Must Modify (Core)
- `libs/gateway/query_analyzer.py`
- `libs/gateway/context_document.py`
- `apps/prompts/pipeline/phase0_query_analyzer.md`
- `apps/prompts/pipeline/phase3_planner_chat.md`

### Should Modify (Remove hardcoding)
- `apps/services/orchestrator/internet_research_mcp.py`
- `libs/gateway/research_index_db.py`
- `apps/services/gateway/intent_weights.py`
- `libs/gateway/unified_flow.py`

### May Modify (Storage)
- `libs/gateway/turn_saver.py`
- `libs/gateway/turn_index_db.py`

### Update (Tests)
- `tests/golden_queries/test_*.py`
- `scripts/test_intent_classification.py`

---

**Next Step:** Get user approval on this plan before implementing.
