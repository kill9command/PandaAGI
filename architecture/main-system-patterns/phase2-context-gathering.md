# Phase 2: Context Gatherer

**Status:** SPECIFICATION
**Version:** 1.5
**Created:** 2026-01-04
**Updated:** 2026-01-24
**Layer:** MIND role (MIND model @ temp=0.5)
**Question:** "What context does this query need?"
**Prerequisite:** Phase 1 (Reflection) must have decided PROCEED

---

## 1. Overview

Phase 2 is the **Context Gatherer** - responsible for assembling all relevant context needed to answer the user's query. It reads Section 0 (user query) and Section 1 (Reflection decision), then writes gathered context to Section 2.

**This phase only runs when Phase 1 (Reflection) has decided PROCEED.** Queries that were clarified, rejected, or otherwise handled by Reflection do not reach this phase.

**Key Responsibilities:**
- Read Section 0 (user query from Phase 0)
- Read Section 1 (Reflection decision - confirms PROCEED)
- Identify relevant prior turns, memory, and cached research
- Extract and compile relevant information into Section 2
- Evaluate whether cached data can answer the query (fast path)

**Design Principle:** The Context Gatherer uses a **Plan-Act-Review** pattern with two distinct LLM calls: RETRIEVAL (identify what's relevant) and SYNTHESIS (extract and compile).

---

## 2. Flow Diagram

```
                         Phase 1: Reflection
                           (decided PROCEED)
                                  |
                                  v
+-----------------------------------------------------------------------------+
|                         PHASE 2: CONTEXT GATHERER                           |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +---------------------------------------------------------------------+   |
|  |                      INPUT ASSEMBLY                                  |   |
|  |                                                                      |   |
|  |   QueryAnalysis --+---> Turn Index (prior turns)                     |   |
|  |   from Phase 0    |                                                  |   |
|  |                   +---> Memory Store (preferences, facts)            |   |
|  |                   |                                                  |   |
|  |                   +---> Research Cache (cached intelligence)         |   |
|  |                   |                                                  |   |
|  |                   +---> Visit Records (cached page data)             |   |
|  |                   |                                                  |   |
|  |                   +---> Obsidian Memory (forever memory) ◄── NEW     |   |
|  |                         /Knowledge/Research/                         |   |
|  |                         /Knowledge/Products/                         |   |
|  |                         /Preferences/                                |   |
|  +---------------------------------------------------------------------+   |
|                                    |                                        |
|                                    v                                        |
|  +---------------------------------------------------------------------+   |
|  |               LLM CALL 1: RETRIEVAL (~5,500 tokens)                 |   |
|  |                                                                      |   |
|  |   Input:  QueryAnalysis + Turn Summaries + Memory Headers           |   |
|  |                                                                      |   |
|  |   Task:   "Which of these sources are relevant to this query?"      |   |
|  |                                                                      |   |
|  |   Output: RetrievalPlan                                              |   |
|  |           +-- relevant_turns: [811, 809]                            |   |
|  |           +-- relevant_memory_keys: ["budget", "preferred_brands"]  |   |
|  |           +-- research_cache_match: true/false                      |   |
|  |           +-- webpage_cache_needed: ["visit_abc123", ...]           |   |
|  |           +-- reasoning: "why these sources"                        |   |
|  +---------------------------------------------------------------------+   |
|                                    |                                        |
|                                    v                                        |
|  +---------------------------------------------------------------------+   |
|  |                      DOCUMENT RETRIEVAL                              |   |
|  |                                                                      |   |
|  |   Load identified documents:                                         |   |
|  |   +-- turns/turn_000811/context.md                                  |   |
|  |   +-- turns/turn_000809/context.md                                  |   |
|  |   +-- memory/preferences.json (filtered keys)                       |   |
|  |   +-- research_cache/commerce.laptop.json                           |   |
|  |   +-- webpage_cache/visit_abc123.json                               |   |
|  +---------------------------------------------------------------------+   |
|                                    |                                        |
|                                    v                                        |
|  +---------------------------------------------------------------------+   |
|  |               LLM CALL 2: SYNTHESIS (~5,000 tokens)                 |   |
|  |                                                                      |   |
|  |   Input:  QueryAnalysis + Loaded Documents                          |   |
|  |                                                                      |   |
|  |   Task:   "Extract relevant context and compile into S1 format"     |   |
|  |                                                                      |   |
|  |   Output: GatheredContext                                            |   |
|  |           +-- session_preferences: {...}                            |   |
|  |           +-- prior_turns: [{turn, relevance, summary}, ...]        |   |
|  |           +-- cached_research: {topic, quality, age, summary}       |   |
|  |           +-- visit_data: [{url, extracted_data}, ...]              |   |
|  |           +-- source_references: [...]                              |   |
|  +---------------------------------------------------------------------+   |
|                                    |                                        |
|                                    v                                        |
|  +---------------------------------------------------------------------+   |
|  |                      WRITE context.md                                |   |
|  |                                                                      |   |
|  |   Writes:                                                            |   |
|  |   +-- S2: Gathered Context (structured markdown)                    |   |
|  +---------------------------------------------------------------------+   |
|                                                                             |
+-----------------------------------------------------------------------------+
                                    |
                                    v
                              Phase 3: Planner
```

---

## 3. Input Sources

| Source | Location | Content | Used For |
|--------|----------|---------|----------|
| **QueryAnalysis** | Phase 0 output | resolved_query, content_reference, query_type | Understanding what to search for |
| **Reflection Decision** | Phase 1 output | PROCEED decision | Confirms this phase should run |
| **Turn Index** | `panda-system-docs/indexes/turn_index.db` | Turn summaries, topics, timestamps | Finding relevant prior conversations |
| **Memory Store** | `panda-system-docs/users/{user_id}/preferences.md`, `facts.md` | User preferences, learned facts | Personalizing context |
| **Research Index** | `panda-system-docs/indexes/research_index.db` | Cached research index by topic | Finding prior research |
| **Visit Records** | Per-turn: `users/{user_id}/turns/turn_{N}/webpage_cache/` | Cached page extractions | Retrieving specific content without re-visiting |

### 3.1 QueryAnalysis (from Phase 0)

```json
{
  "original_query": "what's the cheapest laptop with nvidia gpu",
  "resolved_query": "cheapest laptop with NVIDIA GPU",
  "reference_resolution": {
    "status": "not_needed",
    "original_references": [],
    "resolved_to": null
  },
  "query_type": "general_question",
  "content_reference": null,
  "reasoning": "New shopping query, no prior context referenced"
}
```

### 3.2 Phase 1 Reflection Decision

Phase 2 only runs when Phase 1 (Reflection) outputs `PROCEED`. The Reflection phase evaluates whether the query is clear, appropriate, and ready for context gathering.

```json
{
  "decision": "PROCEED",
  "confidence": 0.95,
  "reasoning": "Query is clear and actionable, no clarification needed"
}
```

### 3.3 Turn Index Entry Format

```json
{
  "turn_id": 811,
  "timestamp": "2026-01-04T14:30:00Z",
  "summary": "Compared RTX 4050 laptops under $1000",
  "topics": ["laptop", "nvidia", "gaming", "budget"],
  "intent": "commerce",
  "has_research": true,
  "research_topic": "commerce.laptop"
}
```

### 3.4 Memory Store Format

```json
// preferences.json
{
  "budget": {"value": "$500-800", "confidence": 0.9, "source_turn": 808},
  "preferred_brands": {"value": ["Lenovo", "ASUS"], "confidence": 0.7, "source_turn": 805},
  "location": {"value": "California", "confidence": 0.95, "source_turn": 790}
}

// facts.json
{
  "owns_macbook_pro": {"value": true, "confidence": 0.85, "source_turn": 750},
  "programming_languages": {"value": ["Python", "TypeScript"], "confidence": 0.9, "source_turn": 720}
}
```

### 3.5 Research Cache Format

```json
{
  "topic": "commerce.laptop",
  "cache_key": "nvidia_gpu_laptop_budget",
  "created_at": "2026-01-04T13:15:00Z",
  "expires_at": "2026-01-04T19:15:00Z",
  "quality_score": 0.88,
  "summary": "Found 12 laptops with NVIDIA GPUs from 5 vendors",
  "claims": [
    {"claim": "Lenovo LOQ 15 @ $697", "source": "bestbuy.com", "confidence": 0.92},
    {"claim": "ASUS TUF @ $749", "source": "amazon.com", "confidence": 0.88}
  ],
  "webpage_cache": ["visit_abc123", "visit_def456"]
}
```

### 3.6 Visit Record Format

```json
{
  "visit_id": "visit_abc123",
  "url": "https://www.bestbuy.com/site/lenovo-loq-15...",
  "visited_at": "2026-01-04T13:20:00Z",
  "page_type": "product",
  "extracted_data": {
    "title": "Lenovo LOQ 15 Gaming Laptop",
    "price": "$697.00",
    "specs": {
      "gpu": "NVIDIA RTX 4050",
      "ram": "16GB DDR5",
      "storage": "512GB SSD"
    },
    "availability": "In Stock"
  },
  "extraction_quality": 0.95
}
```

---

## 4. Two-Phase Process Detail

### 4.1 Phase A: RETRIEVAL

**Purpose:** Identify which sources contain relevant context without loading full documents.

**Input Composition:**
```
SYSTEM PROMPT (~800 tokens)
+-- Role definition
+-- Available source types
+-- Output schema

USER PROMPT (~4,200 tokens)
+-- QueryAnalysis (~300 tokens)
+-- Turn Summaries - last 20 turns (~2,500 tokens)
|   +-- For each: {turn_id, timestamp, summary, topics}
+-- Memory Headers (~400 tokens)
|   +-- For each: {key, value_preview, last_updated}
+-- Research Cache Headers (~500 tokens)
|   +-- For each: {topic, age_hours, quality_score}
+-- Visit Record Headers (~500 tokens)
    +-- For each: {visit_id, url, page_type, age_hours}

OUTPUT (~500 tokens)
+-- RetrievalPlan JSON
```

**RetrievalPlan Schema:**
```json
{
  "relevant_turns": [811, 809],
  "turn_relevance": {
    "811": {"relevance": "high", "reason": "Same topic - laptop shopping"},
    "809": {"relevance": "medium", "reason": "Related budget discussion"}
  },
  "relevant_memory_keys": ["budget", "preferred_brands", "location"],
  "research_cache_match": {
    "matched": true,
    "topic": "commerce.laptop",
    "freshness": "1.2 hours",
    "quality": 0.88,
    "reuse_recommendation": "full"
  },
  "webpage_cache_needed": ["visit_abc123", "visit_def456"],
  "reasoning": "User asking about laptops again. Turn 811 has relevant comparison. Research cache is fresh and high quality. Loading visit records for price verification."
}
```

### 4.2 Document Loading (Procedural)

After RETRIEVAL, the system loads the identified documents based on the RetrievalPlan:

| Document Type | Source | Loading Rule |
|---------------|--------|--------------|
| **Relevant Turns** | `panda-system-docs/users/{user_id}/turns/turn_{N}/context.md` | Load and truncate to max 1,500 tokens each |
| **Memory Files** | `panda-system-docs/users/{user_id}/preferences.md`, `facts.md` | Load only keys specified in `relevant_memory_keys` |
| **Research Docs** | Via `research_index.db` → `users/{user_id}/turns/turn_{N}/research.json` | Load if `research_cache_match.matched == true` |
| **Visit Records** | `panda-system-docs/users/{user_id}/turns/turn_{N}/webpage_cache/{url_slug}/` | Load each visit_id in `webpage_cache_needed` |

All loaded documents are collected into a `documents` map for the SYNTHESIS phase.

### 4.3 Phase B: SYNTHESIS

**Purpose:** Extract relevant information from loaded documents and compile into structured format.

**Input Composition:**
```
SYSTEM PROMPT (~700 tokens)
+-- Role definition
+-- Output format specification
+-- Evidence linking requirements

USER PROMPT (~3,800 tokens)
+-- QueryAnalysis (~300 tokens)
+-- Original User Query (~50 tokens) [CRITICAL for context discipline]
+-- Loaded Documents (~3,000 tokens)
|   +-- Turn contexts (truncated)
|   +-- Memory values
|   +-- Research cache summary
|   +-- Visit record data
+-- Instructions (~450 tokens)

OUTPUT (~500 tokens)
+-- GatheredContext structured data
```

**GatheredContext Schema:**
```json
{
  "session_preferences": {
    "budget": "$500-800",
    "location": "California",
    "preferred_brands": ["Lenovo", "ASUS"]
  },
  "prior_turns": [
    {
      "turn": 811,
      "relevance": "high",
      "summary": "Compared RTX 4050 laptops under $1000, favored Lenovo LOQ",
      "key_facts": ["Lenovo LOQ at $697 was top pick", "User wanted thin bezels"]
    }
  ],
  "cached_research": {
    "topic": "commerce.laptop",
    "quality": 0.88,
    "age_hours": 1.2,
    "summary": "12 laptops found, 3 under $800 with RTX 4050",
    "top_results": [
      {"product": "Lenovo LOQ 15", "price": "$697", "source": "bestbuy.com"}
    ]
  },
  "visit_data": [
    {
      "url": "https://bestbuy.com/...",
      "extracted": {"price": "$697.00", "stock": "In Stock"}
    }
  ],
  "source_references": [
    "[1] turns/turn_000811/context.md",
    "[2] research_cache/commerce.laptop.json",
    "[3] webpage_cache/visit_abc123.json"
  ]
}
```

---

## 5. Section 2 Output Format

### 5.1 Dual-Format Specification

§2 uses a **dual-format structure**: human-readable markdown with embedded machine-parseable YAML `_meta` blocks per section. This enables:
1. **Programmatic access**: Phase 3 (Planner) extracts structured data from `_meta` for routing decisions
2. **LLM reasoning**: Markdown body provides rich context for LLM interpretation
3. **Debuggability**: Transcripts remain human-readable

### 5.2 Format Structure

The SYNTHESIS phase output is formatted into markdown for `context.md`:

```markdown
## 2. Gathered Context

### Session Preferences

```yaml
_meta:
  type: preferences
  count: 3
  confidence: 0.87
```

| Preference | Value | Source |
|------------|-------|--------|
| budget | $500-800 | Turn 808 |
| location | California | Turn 790 |
| preferred_brands | Lenovo, ASUS | Turn 805 |

### Relevant Prior Turns

```yaml
_meta:
  type: turn_context
  relevant_turns: [811, 809]
  highest_relevance: "high"
```

| Turn | Relevance | Summary | Key Facts |
|------|-----------|---------|-----------|
| 811 | high | Compared RTX 4050 laptops under $1000 | Lenovo LOQ at $697 was top pick; User wanted thin bezels |
| 809 | medium | Discussed budget constraints | Firm limit of $800 |

### Cached Research Intelligence

```yaml
_meta:
  type: research_cache
  topic: commerce.laptop
  quality_score: 0.88
  freshness_score: 0.92
  age_hours: 1.2
  expires_hours: 5.8
  source_count: 12
```

**Topic:** commerce.laptop
**Quality Score:** 0.88 (High confidence)
**Age:** 1.2 hours
**Expires:** 5.8 hours

**Summary:** Found 12 laptops with NVIDIA GPUs from 5 vendors. 3 options under $800 with RTX 4050.

**Top Results:**
| Product | Price | Source | Last Verified |
|---------|-------|--------|---------------|
| Lenovo LOQ 15 | $697 | bestbuy.com | 1.2h ago |
| ASUS TUF A15 | $749 | amazon.com | 1.2h ago |
| HP Victus 15 | $799 | walmart.com | 1.2h ago |

### Visit Record Data

```yaml
_meta:
  type: visit_data
  visit_count: 2
  freshness_avg: 1.2
```

| URL | Data Point | Value | Freshness |
|-----|------------|-------|-----------|
| bestbuy.com/lenovo-loq... | price | $697.00 | 1.2h |
| bestbuy.com/lenovo-loq... | stock | In Stock | 1.2h |
| amazon.com/asus-tuf... | price | $749.99 | 1.2h |

### Source References

- [1] `turns/turn_000811/context.md` - Prior laptop comparison
- [2] `research_cache/commerce.laptop.json` - Cached research (quality: 0.88)
- [3] `webpage_cache/visit_abc123.json` - Best Buy product page
- [4] `webpage_cache/visit_def456.json` - Amazon product page

### Context Assessment

```yaml
_meta:
  type: assessment
  context_quality: 0.88
  gaps_identified: []
```

**Context Quality:** 0.88 (High)
**Gaps:** None identified

---
```

### 5.3 Parsing Rules for Phase 3 (Planner)

Planner extracts structured data from `_meta` YAML blocks to inform its reasoning:

| Field | Location | Used For |
|-------|----------|----------|
| `quality_score` | `_meta.quality_score` in Cached Research | Assess data reliability |
| `gaps_identified` | `_meta.gaps_identified` | Identify what's missing |
| `age_hours` | `_meta.age_hours` | Assess data freshness |
| `context_quality` | `_meta.context_quality` in Assessment | Overall context quality |

**Note:** Planner makes its own routing decision based on this data. Phase 2 does not prescribe whether tools are needed.

---

## 6. Visit Record Retrieval

Visit records enable **content reuse without re-visiting pages**. This is critical for:
- Answering follow-up questions about previously visited products
- Verifying prices without additional network requests
- Building context from prior research

### 6.1 When to Use Visit Records

| Scenario | Use Visit Record? | Reason |
|----------|-------------------|--------|
| "Tell me more about that Lenovo" | Yes | User referencing prior content |
| "Is it still in stock?" | Yes, then verify | Check cache first, verify if critical |
| "Find me a different laptop" | No | New search needed |
| "Compare the specs" | Yes | Comparing cached data |

### 6.2 Visit Record Linking

Visit records are linked through:
1. **content_reference** from Phase 0 QueryAnalysis
2. **research_cache** which stores webpage_cache IDs
3. **turn context** which references what was visited

```
User Query: "what were the specs on that Lenovo?"
                     |
                     v
Phase 0 QueryAnalysis:
  content_reference:
    title: "Lenovo LOQ 15"
    source_turn: 811
                     |
                     v
Phase 1 Reflection:
  decision: PROCEED
  reasoning: "Query references prior content, clear intent"
                     |
                     v
Phase 2 RETRIEVAL:
  Finds turn 811 -> has research_topic "commerce.laptop"
  Loads research_cache -> finds webpage_cache "visit_abc123"
  Returns webpage_cache_needed: ["visit_abc123"]
                     |
                     v
Phase 2 SYNTHESIS:
  Loads visit_abc123 -> extracts full spec data
  Includes in S2 for downstream phases
```

---

## 7. Token Budget Breakdown

**Total Budget:** ~10,500 tokens (across 2 LLM calls)

### 7.1 RETRIEVAL Call (~5,500 tokens)

| Component | Tokens | Notes |
|-----------|--------|-------|
| System prompt | 800 | Role, schema, instructions |
| QueryAnalysis | 300 | From Phase 0 |
| Turn summaries (20) | 2,500 | 125 tokens each |
| Memory headers | 400 | Key-value previews |
| Research cache headers | 500 | Topic, age, quality |
| Visit record headers | 500 | ID, URL, type |
| **Input subtotal** | **5,000** | |
| Output (RetrievalPlan) | 500 | JSON response |
| **RETRIEVAL total** | **5,500** | |

### 7.2 SYNTHESIS Call (~5,000 tokens)

| Component | Tokens | Notes |
|-----------|--------|-------|
| System prompt | 700 | Role, format, evidence rules |
| QueryAnalysis | 300 | From Phase 0 |
| Original query | 50 | Context discipline |
| Loaded documents | 3,000 | Variable, truncated as needed |
| Instructions | 450 | Extraction guidance |
| **Input subtotal** | **4,500** | |
| Output (GatheredContext) | 500 | Structured JSON |
| **SYNTHESIS total** | **5,000** | |

### 7.3 Document Truncation Strategy

When loaded documents exceed budget:

1. **Priority order:** Memory > Research Cache > Recent Turns > Older Turns
2. **Per-turn limit:** 1,500 tokens max
3. **Research cache:** Keep summary + top 5 claims
4. **Visit records:** Keep extracted_data only (drop raw HTML references)

---

## 8. Routing (Determined by Planner)

**Phase 2 does not make routing decisions.** It gathers context and writes §2. Phase 3 (Planner) reads §2 and decides whether tools are needed.

### 8.1 Planner Routes to Synthesis (No Tools)

When Planner determines the gathered context is sufficient to answer the query:

**Flow:**
```
Phase 2 -> Phase 3 (decides: synthesis) -> Phase 5 -> Phase 6 -> Phase 7
```

### 8.2 Planner Routes to Coordinator (Tools Needed)

When Planner determines tools are needed (research, memory operations, etc.):

**Flow:**
```
Phase 2 -> Phase 3 (decides: coordinator) -> Phase 4 -> Phase 5 -> Phase 6 -> Phase 7
```

**Note:** All queries go through Phases 0-3 in order. Planner decides whether to include Phase 4.

---

## 9. Error Handling (Fail-Fast)

All errors halt processing and create intervention requests. No silent failures.

| Error | Action |
|-------|--------|
| Turn not found | HALT - Log error, create intervention |
| Memory key missing | HALT - Log error, create intervention |
| Research cache corrupted | HALT - Log error, create intervention |
| Visit record missing | HALT - Log error, create intervention |
| LLM timeout | HALT - Log timeout details, create intervention |
| Token budget exceeded | HALT - Log budget details, create intervention |

**Rationale:** Every failure is a bug. If a turn is "not found" but was expected, that's a data integrity issue to fix. Silent exclusions hide problems and create compounding issues.

---

## 10. Quality Gates

| Gate | Check | Action on Failure |
|------|-------|-------------------|
| Schema validation | Output matches GatheredContext schema | Retry LLM call |
| Source linking | All claims reference a source | Flag unlinked claims |
| Freshness check | Cached data within TTL | Mark stale, recommend refresh |
| Relevance threshold | At least one relevant source found | Log warning, proceed with empty context |

---

## 11. Turn Summary Generation

The Context Gatherer is also responsible for generating turn summaries that populate the turn index. This happens **after Phase 7 (Save)** completes, as a background task.

### 11.1 Summary Generation Role

| Aspect | Value |
|--------|-------|
| **Model** | MIND (Qwen3-Coder-30B-AWQ) |
| **Temperature** | 0.3 (REFLEX-like, deterministic) |
| **Prompt** | Dedicated summarization prompt |
| **Trigger** | After turn is saved (async) |

### 11.2 Summary Prompt Pattern

```
Given the completed turn context.md, generate a concise summary for the turn index.

Input: Full context.md (§0-§6)

Output:
{
  "summary": "1-2 sentence description of what happened",
  "topics": ["topic1", "topic2", ...],  // 2-5 keywords
  "intent": "commerce|query|recall|preference|navigation|greeting",
  "has_research": true|false,
  "research_topic": "category.subcategory" or null
}
```

### 11.3 Example

**Input (context.md):**
```markdown
## 0. User Query
Find me a cheap laptop with nvidia gpu

## 3. Task Plan
**Intent:** commerce
...

## 4. Tool Execution
**Tool:** internet.research
**Results:** Found 12 laptops...
...
```

**Output:**
```json
{
  "summary": "Searched for budget NVIDIA GPU laptops, found 12 options from 5 vendors",
  "topics": ["laptop", "nvidia", "gpu", "budget", "gaming"],
  "intent": "commerce",
  "has_research": true,
  "research_topic": "commerce.laptop"
}
```

### 11.4 Index Update

The summary is written to `turn_index.db` for fast retrieval by future Context Gatherer calls.

---

## 12. Related Documents

- `architecture/LLM-ROLES/llm-roles-reference.md` - Model assignments and phase pipeline overview
- `architecture/main-system-patterns/phase0-query-analyzer.md` - Phase 0 (provides QueryAnalysis)
- `architecture/main-system-patterns/phase1-reflection.md` - Phase 1 (must PROCEED for this phase to run)
- `architecture/main-system-patterns/phase3-planner.md` - Phase 3 (receives Section 2 output)
- `architecture/main-system-patterns/MEMORY_ARCHITECTURE.md` - Memory system and turn index
- `architecture/main-system-patterns/UNIVERSAL_CONFIDENCE_SYSTEM.md` - Quality thresholds for cache decisions
- `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` - Document IO and context.md format

---

## 13. Supplementary Sources Formatting

The Context Gatherer receives supplementary information from multiple sources. These are formatted with distinct headers to prevent conflation:

### 13.1 Source Types and Headers

| Source | Header | Output Section | Content Type |
|--------|--------|----------------|--------------|
| Session Memory | `===== SESSION MEMORY - USER PREFERENCES =====` | `### User Preferences` | Personal preferences from current session |
| Cached Intelligence | `===== CACHED INTELLIGENCE (Phase 1) =====` | `### Cached Intelligence` | Research cache from prior turns |
| Forever Memory | `===== FOREVER MEMORY (Persistent Knowledge) =====` | `### Forever Memory Knowledge` | Knowledge documents (research, facts, analysis) |
| Stored Preferences | `===== STORED USER PREFERENCES =====` | `### User Preferences` | Persistent personal preferences |

### 13.2 Critical Constraint: Relevance Filtering

**The Context Gatherer MUST filter for relevance.** Only content that directly relates to the current query should appear in context.md. Irrelevant sections should be OMITTED entirely, not just labeled differently.

| Query Topic | Forever Memory Content | User Preferences | Action |
|-------------|----------------------|------------------|--------|
| Russian troll farms | russian_information_warfare_history.md | "favorite hamster: Syrian" | Include Forever Memory, **OMIT** User Preferences |
| Syrian hamsters | russian_information_warfare_history.md | "favorite hamster: Syrian" | **OMIT** Forever Memory, Include User Preferences |
| Cheap laptops | rtx_4060_budget_gaming_laptops.md | "budget: $500-800" | Include Forever Memory, Include User Preferences |

**The LLM must evaluate each supplementary source and ask: "Is this relevant to what the user is asking about?"**
- If YES → Include in appropriate section
- If NO → Omit entirely (don't create the section)

### 13.3 Implementation Note

The prompt explicitly instructs the LLM to route content to the correct output section based on the source header. This prevents knowledge documents from being mislabeled as preferences or vice versa.

---

## 14. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 1.1 | 2026-01-05 | Updated phase ordering (was Phase 1, now Phase 2) |
| 1.2 | 2026-01-05 | Removed implementation references, added Changelog |
| 1.3 | 2026-01-05 | Added dual-format §2 specification with YAML `_meta` blocks for programmatic parsing; updated QueryAnalysis to use `reference_resolution` schema |
| 1.4 | 2026-01-06 | Added Turn Summary Generation section (§11) - Context Gatherer generates turn summaries for index |
| 1.5 | 2026-01-24 | Added Supplementary Sources Formatting section (§13) - Clarifies distinction between Forever Memory Knowledge and User Preferences |

---

**Last Updated:** 2026-01-24
