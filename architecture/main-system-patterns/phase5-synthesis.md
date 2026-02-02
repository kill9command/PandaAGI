# Phase 5: Synthesis

**Status:** SPECIFICATION
**Version:** 2.3
**Created:** 2026-01-04
**Updated:** 2026-01-06
**Layer:** VOICE role (MIND model @ temp=0.7) - User Dialogue

---

## Overview

The Synthesis phase transforms accumulated context into a user-facing response. This is the **only model the user "hears"** - it serves as the voice of Pandora, converting structured data into natural, engaging dialogue.

**Key Question:** "How do I present this to the user?"

```
┌──────────────────────────────────────────────────────────────┐
│                    PHASE 5: SYNTHESIS                         │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ INPUT: context.md (§0-§4) + toolresults.md              │ │
│  │        OR context.md (§0-§3) if no tools                │ │
│  └─────────────────────────────────────────────────────────┘ │
│                            ↓                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ PROCESS: Format response based on intent                │ │
│  │          - Use ONLY data from context.md                │ │
│  │          - Convert URLs to clickable links              │ │
│  │          - Include source citations                     │ │
│  └─────────────────────────────────────────────────────────┘ │
│                            ↓                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ OUTPUT: context.md §5 (preview) + response.md (full)    │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

**Why VOICE Role (MIND @ temp=0.7)?**
- Uses Qwen3-Coder-30B-AWQ model with higher temperature for natural output
- Same model as other phases, but temperature 0.7 for more conversational tone
- Follows formatting instructions precisely

---

## INPUTS

### 1. context.md (§0-§4 or §0-§3)

The accumulated document from previous phases:

```markdown
## 0. User Query
Can you find me some Syrian hamsters for sale?

## 1. Reflection Decision
**Decision:** PROCEED
**Reasoning:** Commerce query, no cached products

## 2. Gathered Context
### Session Preferences
- **favorite_hamster:** Syrian
- **location:** California

### Prior Research Intelligence
(if available from cache)

## 3. Task Plan
**Goal:** Find products/prices for Syrian hamsters
**Intent:** commerce
**Tools Required:** internet.research
**Route To:** coordinator

## 4. Tool Execution
**Tools Called:**
- `internet.research`: Executed internet research

**Claims Extracted:**
| Claim | Confidence | Source | TTL |
|-------|------------|--------|-----|
| Syrian Hamster @ $20 (hubbahubbahamstery.com) - http://hubbahubbahamstery.com/adopt | 0.90 | internet.research | 6h |
| Syrian Hamster @ $35 (petsmart.com) - https://petsmart.com/hamster-123 | 0.85 | internet.research | 6h |
```

### 2. toolresults.md (if tools were executed)

**Location:** `turns/turn_{N}/toolresults.md`

**Purpose:** Contains complete, untruncated tool execution results that may be summarized or truncated in §4 due to token limits.

Synthesis loads toolresults.md to access:
- Full product details, prices, and URLs from research
- Complete file contents from file.read operations
- Detailed test results from test.run operations

**Why Synthesis needs both context.md AND toolresults.md:**
- §4 contains LLM-summarized claims (may lose detail due to token limits)
- toolresults.md contains exact prices, URLs, and product specs
- Synthesis uses toolresults.md for authoritative product/price data

```markdown
# Tool Results

**Turn:** 743

## Execution Log
{
  "tool": "internet.research",
  "result": {
    "findings": [
      {"name": "Syrian Hamster", "price": "$20", "url": "http://...", "attributes": {...}},
      ...
    ]
  }
}
```

**Note:** toolresults.md is also used by Validation (Phase 6) for price cross-checking.

---

## TWO SYNTHESIS PATHS

| Path | Condition | Primary Data Source |
|------|-----------|---------------------|
| **With Tools** | Coordinator completed successfully | §4 claims (fresh data) |
| **Without Tools** | Planner routed directly to Synthesis | §2 gathered context (cached/memory) |

**Note:** If Coordinator fails (BLOCKED), the turn HALTs with an intervention request. Synthesis only runs on successful completion.

### Path 1: With Tools (Fresh Data)

When Coordinator executed tools successfully, §4 contains fresh claims. These take **precedence over §2** (cached context).

**Data Priority:**
1. §4 claims (authoritative - just gathered)
2. toolresults.md (full details)
3. §2 gathered context (supplementary)

### Path 2: Without Tools (Cached/Memory)

When Planner determined tools were unnecessary (recall queries, preference confirmations), Synthesis uses §2 gathered context directly.

**Example:** "What's my favorite hamster?"
- §2 contains: `**favorite_hamster:** Syrian`
- No tool execution needed
- Synthesis responds directly from memory

---

## RESPONSE PATTERNS BY INTENT

Intent-specific formatting ensures responses match user expectations:

| Intent | Response Pattern | Example Structure |
|--------|------------------|-------------------|
| **commerce** | Structured list with prices, links, specs | Headers, bullet points, product cards |
| **query** | Prose explanation with citations | Paragraphs with inline sources |
| **recall** | Direct answer from memory | Single sentence, confirmation |
| **preference** | Acknowledgment + confirmation | "Got it! I'll remember..." |
| **code** | Operation summary, file changes, test results | Code blocks, file lists, status |
| **greeting** | Friendly response, no elaboration | Natural conversation opener |
| **navigation** | List exact titles/items from source | Preserved original wording |

### Commerce Intent Example

```markdown
Great news! I found 2 Syrian hamsters for sale:

## Best Value
**Syrian Hamster - $20** at Hubba-Hubba Hamstery
- Ethical breeder with health guarantees
- [View on Hubba-Hubba Hamstery](http://hubbahubbahamstery.com/adopt)

## Other Options
**Syrian Hamster - $35** at PetSmart
- [View on PetSmart](https://petsmart.com/hamster-123)

Would you like more details on any of these?
```

### Query Intent Example

```markdown
Syrian hamsters are the largest and most popular pet hamster species. They're also known as "golden hamsters" due to their distinctive coloring.

**Key characteristics:**
- Size: 5-7 inches when fully grown
- Lifespan: 2-3 years on average
- Temperament: Generally docile and easy to handle

Source: [American Hamster Association](https://example.com/aha)
```

### Recall Intent Example

```markdown
Yes! Your favorite hamster is the Syrian hamster.
```

### Code Intent Example

```markdown
I've made the requested changes to `auth.py`:

## Changes Made
- Added `validate_token()` function at line 45
- Updated imports to include `jwt` module
- Added unit test in `test_auth.py`

## Files Modified
- `src/auth.py` - Added token validation
- `tests/test_auth.py` - Added 3 test cases

All tests passing
```

---

## SPECIAL CASE: List Queries (Navigation Intent)

When query asks for "topics", "threads", "titles", "popular posts", the response must preserve exact titles:

| Do | Don't |
|----|-------|
| List exact titles as extracted | Summarize into categories |
| Preserve author names if present | Group by topic type |
| Keep original wording | Paraphrase titles |

### Correct Example (Navigation)

```markdown
Here are the recent posts from the aquarium forum:

1. "Pump timer for feeding"
2. "2 fish die after eating Emerald entree food"
3. "Does this tank need replacing?"
4. "Best substrate for planted tanks"
5. "Moving a 75 gallon - help needed"
```

### Wrong Example (Categorized)

```markdown
Here are some topics from the aquarium forum:

**Marine Life**
- Discussions about organisms

**Equipment Reviews**
- Tank setups and equipment questions
```

---

## FORMATTING RULES

### URL Handling

**Rule:** ALWAYS convert URLs in claims to clickable markdown links.

**Claim in §4:**
```
HP Victus at bestbuy.com for $649.99 - https://www.bestbuy.com/product/hp-victus-xyz
```

**Output Format:**
```markdown
**HP Victus - $649.99**
- [View on Best Buy](https://www.bestbuy.com/product/hp-victus-xyz)
```

### Response Structure Elements

| Element | Requirement | Example |
|---------|-------------|---------|
| Opening | Engaging, natural | "Great news! I found..." |
| Structure | Use ## headers | `## Best Options` |
| Links | Clickable markdown | `[View on PetSmart](https://...)` |
| Details | Specific numbers | "$35.50", "8 weeks old" |
| Action | Tell user what to do | "Contact breeder at..." |

### Source Citation Format

Citations must be included when presenting factual claims:

**Inline Citation:**
```markdown
The average Syrian hamster costs between $10-$30 ([PetSmart](https://petco.com/hamsters)).
```

**Section Citation:**
```markdown
## Sources
- [Hubba-Hubba Hamstery](http://hubbahubbahamstery.com/adopt)
- [PetSmart Hamsters](https://petsmart.com/hamster-123)
```

**Product Link Citation:**
```markdown
**Syrian Hamster - $20**
- [View Listing](http://hubbahubbahamstery.com/adopt)
```

---

## OUTPUTS

### 1. response.md (Primary Output)

**Location:** `turns/turn_{N}/response.md`

The full response delivered to the user.

**Commerce Example:**
```markdown
Great news! I found 2 Syrian hamsters for sale:

## Best Value
**Syrian Hamster - $20** at Hubba-Hubba Hamstery
- Ethical breeder with health guarantees
- [View on Hubba-Hubba Hamstery](http://hubbahubbahamstery.com/adopt)

## Other Options
**Syrian Hamster - $35** at PetSmart
- [View on PetSmart](https://petsmart.com/hamster-123)

Would you like more details on any of these?
```

**Recall Example:**
```markdown
Yes! Your favorite hamster is the Syrian hamster.
```

**Code Example:**
```markdown
I've made the requested changes to `auth.py`:

## Changes Made
- Added `validate_token()` function at line 45
- Updated imports to include `jwt` module
- Added unit test in `test_auth.py`

## Files Modified
- `src/auth.py` - Added token validation
- `tests/test_auth.py` - Added 3 test cases

All tests passing
```

### 2. context.md §5 (Appended)

A preview of the response with validation checklist:

```markdown
## 5. Synthesis

**Response Preview:**
Great news! I found 2 Syrian hamsters for sale:

## Best Value
**Syrian Hamster - $20** at Hubba-Hubba Hamstery
...

**Validation Checklist:**
- [x] Claims match evidence
- [x] Intent satisfied
- [x] No hallucinations from prior context
- [x] Appropriate format
```

### 3. Manifest Updates

```json
{
  "docs_created": ["response.md"],
  "doc_pack_usage": {
    "phase5_synthesis": {
      "token_count": 4500,
      "budget": 10000,
      "input_tokens": 3200,
      "output_tokens": 850
    }
  },
  "tokens_used": {
    "synthesizer": 4500
  }
}
```

---

## TOKEN BUDGET

**Total Budget:** ~10,000 tokens

| Component | Tokens | Purpose |
|-----------|--------|---------|
| Prompt fragments | 1,318 | Base constraints, synthesis instructions |
| Input documents | 5,500 | context.md + toolresults.md |
| Output response | 2,900 | User-facing response |
| Buffer | 282 | Safety margin |
| **Total** | **10,000** | Per-synthesis budget |

---

## PROCESS FLOW

| Step | Action | Details |
|------|--------|---------|
| 1. Load Configuration | Load mode-specific settings | Chat vs Code mode determines output token limits |
| 2. Construct Prompt | Build synthesis prompt | Base constraints + mode/intent from §3 + context.md + toolresults.md |
| 3. Call VOICE Role | Invoke Qwen3-Coder-30B-AWQ | Temperature: 0.7, Max tokens: 1000 (chat) or 3100 (code) |
| 4. Write Outputs | Save results | Write response.md, append §5 to context.md |

### Error Handling (Fail-Fast)

If the LLM call fails, the phase HALTs and creates an intervention request:

| Error | Action |
|-------|--------|
| LLM timeout | HALT - create intervention |
| Empty response | HALT - create intervention |
| Model unavailable | HALT - create intervention |

**Rationale:** There are no fallback synthesis patterns. If the VOICE model cannot generate a response, that's a bug to fix, not a condition to work around.

---

## KEY CONSTRAINTS

### 1. Capsule-Only Constraint

**Response must ONLY use data from context.md (no hallucinations)**

- Every factual claim must have evidence in §4 or §2
- Never invent prices, URLs, product names, or specifications
- If data is missing, acknowledge the gap rather than fabricate

### 2. URL Preservation

Claims contain URLs; synthesis MUST format as clickable links:

```markdown
# Wrong
HP Victus at bestbuy.com for $649.99

# Correct
**HP Victus - $649.99**
- [View on Best Buy](https://www.bestbuy.com/product/hp-victus-xyz)
```

### 3. Intent-Aware Formatting

Response structure adapts to query intent - commerce queries get product cards, query intents get prose, code intents get file change summaries.

### 4. §4 vs §2 Priority

Fresh tool data (§4) takes precedence over cached context (§2). If §4 has newer prices, use §4 prices even if §2 has different data.

### 5. Validation Checklist

§5 includes self-validation markers that Phase 6 (Validation) will verify:
- Claims match evidence
- Intent satisfied
- No hallucinations from prior context
- Appropriate format

### 6. Authoritative Spelling/Terminology

Use spelling and terminology from authoritative sources (§4), not the user's potentially misspelled query:

- Names: "jessika aro" → "Jessikka Aro" (from Wikipedia)
- Brands: "nvidia" → "NVIDIA", "playstation" → "PlayStation"
- Products: "iphone" → "iPhone", "macbook" → "MacBook"
- Technical terms: "javascript" → "JavaScript", "postgresql" → "PostgreSQL"

This ensures responses use correct, verifiable terminology from sources.

---

## KEY ARCHITECTURAL POINTS

1. **Single Voice** - VOICE role (MIND @ temp=0.7) is the ONLY interface users interact with directly
2. **Document-Driven** - All data comes from context.md; no external lookups during synthesis
3. **Intent-Adaptive** - Response format matches user intent automatically
4. **Link Preservation** - URLs from research become clickable markdown links
5. **Honest Reporting** - Partial/blocked results are acknowledged, not hidden
6. **Validation-Ready** - §5 includes checklist for Phase 6 verification

---

## RELATED DOCUMENTATION

- `architecture/LLM-ROLES/llm-roles-reference.md` - Model assignments and role definitions
- `architecture/main-system-patterns/phase4-coordinator.md` - Phase 4 (provides §4 and toolresults.md)
- `architecture/main-system-patterns/phase6-validation.md` - Phase 6 (validates response.md)
- `architecture/main-system-patterns/UNIVERSAL_CONFIDENCE_SYSTEM.md` - Quality thresholds for hedging language

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | 2026-01-05 | Updated phase ordering (§1=Reflection, §2=Context) |
| 2.1 | 2026-01-05 | Removed hardcoded claim filtering, aligned with fail-fast |
| 2.2 | 2026-01-05 | Removed prompt/recipe file references, converted process flow to table |

---

**Last Updated:** 2026-01-24

**2026-01-24:** Added constraint #6 (Authoritative Spelling/Terminology) - Synthesis now uses correct spelling from sources, not user's potentially misspelled query.
