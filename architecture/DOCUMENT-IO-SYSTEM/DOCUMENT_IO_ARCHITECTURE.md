# Document IO Architecture

**Status:** SPECIFICATION
**Version:** 2.0
**Created:** 2026-01-04
**Updated:** 2026-01-05
**Purpose:** Define how all documents flow through the system, their formats, linking patterns, and retrieval mechanisms.

---

## 1. Core Principle: Everything is a Document

The system uses a **document-centric IO model** where:
- Every piece of information lives in a markdown document
- Documents link to each other for provenance and detail retrieval
- The Context Gatherer is the single entry point for all context retrieval
- Summarized context lives in `context.md`, full details live in linked documents

```
┌─────────────────────────────────────────────────────────────────┐
│                    DOCUMENT HIERARCHY                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Phase 0 - Query Analyzer (REFLEX)                             │
│       │                                                         │
│       └── query_analysis.json                                   │
│           ├── resolved_query: Query with references made explicit│
│           ├── content_reference: Specific content being referenced│
│           │   ├── source_url: Direct URL to revisit             │
│           │   ├── has_webpage_cache: Do we have cached page data?│
│           │   └── webpage_cache_path: Path to cached data        │
│           └── query_type: specific_content | general | followup │
│                                                                 │
│   context.md (summary layer + conversation history)             │
│       │                                                         │
│       ├── §0: User Query (immutable, original + resolved)       │
│       ├── §1: Reflection Decision (REFLEX - PROCEED | CLARIFY)  │
│       ├── §2: Gathered Context (MIND - Context Gatherer)        │
│       ├── §3: Task Plan + Goals (MIND - Planner)                │
│       ├── §4: Tool Execution + Goal Attribution (MIND - Coord)  │
│       ├── §5: Synthesis (VOICE - final response)                │
│       └── §6: Validation (MIND - per-goal if multi-goal)        │
│                                                                 │
│       Links to:                                                 │
│       ├── research.md (full research details)                   │
│       ├── prior context.md files                                │
│       └── memory/*.json (long-term facts)                       │
│                                                                 │
│   Note: context.md files ARE the history. Each turn's           │
│   context.md shows the complete flow and can be searched        │
│   for patterns and lessons.                                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Model Assignment

The 5-Model Cognitive Stack assigns specific models to each section of context.md:

| Section | Phase | Model | Role | Purpose |
|---------|-------|-------|------|---------|
| §0 | 0 | REFLEX | Query Analyzer | Intent classification, reference resolution |
| §1 | 1 | REFLEX | Reflection | Fast PROCEED/CLARIFY gate decision |
| §2 | 2 | MIND | Context Gatherer | Retrieval planning, link following, synthesis |
| §3 | 3 | MIND | Planner | Task decomposition, goal identification |
| §4 | 4 | MIND | Coordinator | Tool orchestration, execution tracking |
| §5 | 5 | VOICE | Synthesis | User-facing response generation |
| §6 | 6 | MIND | Validation | Quality assessment, goal verification |

**Model Specifications (Final Build):**

| Role | Model | VRAM | Purpose |
|------|-------|------|---------|
| MIND | Qwen3-Coder-30B-AWQ | ~5.3GB | All text roles via temperature |
| EYES | Qwen3-VL-2B-Instruct | ~5.0GB | Vision processing (vLLM swap) |
| SERVER | Qwen3-Coder-30B | Remote | Heavy coding (remote server) |

**Text Roles (all use MIND model):**

| Role | Temperature | Purpose |
|------|-------------|---------|
| REFLEX | 0.3 | Fast gates, classification, intent detection |
| NERVES | 0.1 | Compression (auto-triggered when docs exceed budget) |
| MIND | 0.5 | Planning, reasoning, coordination (keystone) |
| VOICE | 0.7 | User dialogue, natural synthesis |

**Design Rationale:**
- REFLEX handles high-frequency, low-latency decisions (Phase 0, 1)
- MIND handles complex reasoning tasks (Phases 2, 3, 4, 6)
- VOICE handles user-facing output (Phase 5) for natural dialogue
- EYES loads on-demand for visual content processing

---

## 3. context.md Specification

`context.md` is the **single working document** that accumulates state across all phases of the pipeline. Each phase reads the document, performs its work, and appends a new section.

**Key Design Principles:**
- Single source of truth for the turn
- **Append-only** during pipeline execution (phases never modify prior sections)
- Sections numbered 0-6 mapping to phases
- Original query always preserved in §0

### Section Size Management (NERVES Auto-Compression)

Each section tracks its word count. When a section exceeds its max size budget, NERVES (MIND @ temp=0.1) auto-compresses:

| Section | Max Words | Typical Content |
|---------|-----------|-----------------|
| §0 | 500 | User query (rarely exceeds) |
| §1 | 300 | Reflection decision |
| §2 | 2000 | Gathered context |
| §3 | 1000 | Task plan |
| §4 | 3000 | Tool execution (accumulates across iterations) |
| §5 | 2000 | Synthesis response |
| §6 | 500 | Validation decision |

**Auto-Compression Flow:**
```
Section write attempted
        │
        ▼
Check: section_words > max_words?
        │
        ├── NO → Write normally
        │
        └── YES → Trigger NERVES compression
                  │
                  ▼
            NERVES (temp=0.1) compresses content
            preserving format but summarizing details
                  │
                  ▼
            Verify compression (see llm-roles-reference.md)
                  │
                  ▼
            Write compressed content
```

**§4 is most likely to trigger compression** since it accumulates tool results across Planner-Coordinator loop iterations. NERVES preserves the iteration structure but summarizes verbose tool outputs.

**Location:** `panda-system-docs/users/{user_id}/turns/turn_XXXXXX/context.md`

### 3.1 Section Structure

```markdown
## 0. User Query
[Original user input - IMMUTABLE after Phase 0 enrichment]

## 1. Reflection Decision
[Phase 1: Reflection output]

## 2. Gathered Context
[Phase 2: Context Gatherer output]

## 3. Task Plan
[Phase 3: Planner output]

## 4. Tool Execution
[Phase 4: Coordinator output - accumulates]

## 5. Synthesis
[Phase 5: Synthesis output]

## 6. Validation
[Phase 6: Validation output]
```

### 3.2 Section 0: User Query

**Written By:** Pipeline entry (creates with raw query), enriched by Phase 0 (adds resolved_query)
**Read By:** All phases
**Mutable:** Never (after Phase 0 enrichment)
**Purpose:** Immutable record of what user asked, plus resolved form

Contains:
- `original_query`: Raw user input (set at pipeline entry)
- `resolved_query`: Query with references made explicit (set by Phase 0)
- `query_type`: Classification from Phase 0 (`specific_content`, `general_question`, `followup`, `new_topic`)
- `content_reference`: Details about referenced prior content (if any)

```markdown
## 0. User Query

**Original:** whats the cheapest laptop with nvidia gpu

**Resolved:** whats the cheapest laptop with nvidia gpu
**Query Type:** general_question
**Was Resolved:** false
**Content Reference:** none

**Reasoning:** Query is already explicit, no references to resolve
```

**Example with reference resolution:**
```markdown
## 0. User Query

**Original:** what did they recommend in the thread?

**Resolved:** what did they recommend in the 'Best glass scraper for tint removal' thread on GarageJournal?
**Query Type:** specific_content
**Was Resolved:** true
**Content Reference:**
- Title: Best glass scraper for tint removal
- Type: thread
- Site: GarageJournal
- Source Turn: 814

**Reasoning:** Resolved 'the thread' to the GarageJournal thread discussed in turn 814
```

**Purpose:** Preserves the exact user input for context discipline. Every LLM that makes decisions can read user priorities ("cheapest", "best") directly.

### 3.3 Section 1: Reflection Decision

**Written By:** Phase 1 (Reflection)
**Read By:** Phases 2, 3, orchestrator
**Mutable:** Never after Phase 1 completes

```markdown
## 1. Reflection Decision

**Decision:** PROCEED
**Confidence:** 0.95
**Query Type:** ACTION
**Is Follow-up:** false

**Reasoning:** Query intent is clear: find lowest-priced NVIDIA GPU laptop.
```

**Decision Options:**
| Decision | Next Step |
|----------|-----------|
| PROCEED | Continue to Phase 2 |
| CLARIFY | Return clarification question to user |

### 3.4 Section 2: Gathered Context

**Written By:** Phase 2 (Context Gatherer)
**Read By:** Phases 3, 4, 5, 6
**Mutable:** Never after Phase 2 completes

```markdown
## 2. Gathered Context

### Session Preferences
| Preference | Value | Source |
|------------|-------|--------|
| budget | $500-800 | Turn 808 |
| location | California | Turn 790 |

### Relevant Prior Turns
| Turn | Relevance | Summary |
|------|-----------|---------|
| 811 | high | RTX 4050 laptop comparison |
| 809 | medium | Budget discussion |

### Cached Research Intelligence
**Topic:** commerce.laptop
**Quality Score:** 0.88
**Age:** 1.2 hours

**Top Results:**
| Product | Price | Source |
|---------|-------|--------|
| Lenovo LOQ 15 | $697 | bestbuy.com |

### Source References
- [1] turns/turn_000811/context.md
- [2] research_cache/commerce.laptop.json
```

### 3.5 Section 3: Task Plan

**Written By:** Phase 3 (Planner)
**Read By:** Phase 4, Phase 5, Phase 6
**Mutable:** Updated on RETRY loops

```markdown
## 3. Task Plan

**Goal:** Find cheapest laptop with nvidia gpu
**Intent:** commerce
**Subtasks:**
1. Search for laptops with nvidia gpu
2. Compare prices across vendors

**Route To:** coordinator
```

**Route Options:**
| Route | Next Phase |
|-------|------------|
| coordinator | Phase 4 (tool execution) |
| synthesis | Phase 5 (direct answer) |
| clarify | Return to user |

### 3.6 Section 4: Tool Execution

**Written By:** Phase 4 (Coordinator)
**Read By:** Phase 5, Phase 6
**Mutable:** Accumulates during agent loop iterations

```markdown
## 4. Tool Execution

### Iteration 1
**Action:** TOOL_CALL
**Reasoning:** Need to search for nvidia laptops
**Tools Called:**
- `internet.research(query="nvidia gpu laptop under $1000", mode="commerce")`

**Results:**
- SUCCESS: Found 12 products across 4 vendors

### Iteration 2
**Action:** DONE
**Reasoning:** Sufficient product data gathered
**Progress Summary:** 5 laptops verified with prices

---

### Claims Extracted

| Claim | Confidence | Source | TTL |
|-------|------------|--------|-----|
| Lenovo LOQ 15 @ $697 | 0.92 | bestbuy.com | 6h |
| HP Victus 15 @ $649 | 0.90 | walmart.com | 6h |

### Termination
**Reason:** DONE
**Iterations:** 2/10
**Tool Calls:** 2/20
```

### 3.7 Section 5: Synthesis

**Written By:** Phase 5 (Synthesis)
**Read By:** Phase 6
**Mutable:** Updated on REVISE loops

```markdown
## 5. Synthesis

**Response Preview:**
Great news! I found 2 laptops with nvidia GPUs under $800:

## Best Value
**HP Victus 15 - $649** at Walmart
- [View on Walmart](https://walmart.com/...)

## Other Options
**Lenovo LOQ 15 - $697** at Best Buy
- [View on Best Buy](https://bestbuy.com/...)

**Validation Checklist:**
- [x] Claims match evidence
- [x] Intent satisfied
- [x] No hallucinations
- [x] Appropriate format
```

### 3.8 Section 6: Validation

**Written By:** Phase 6 (Validation)
**Read By:** Orchestrator (for loop decisions)
**Mutable:** Accumulates across attempts

```markdown
## 6. Validation

**Decision:** APPROVE
**Confidence:** 0.92

### Checks
| Check | Result |
|-------|--------|
| Claims Supported | PASS |
| No Hallucinations | PASS |
| Query Addressed | PASS |
| Coherent Format | PASS |

### Issues
None

### Notes
Response accurately reflects research findings with proper citations.
```

**On REVISE:**
```markdown
## 6. Validation (Attempt 1)

**Decision:** REVISE
**Confidence:** 0.65

### Issues
1. Price claim "$599" has no source in §4

### Revision Hints
Add source citation for price claim. §4 shows $697, not $599.
```

### 3.9 Token Budget Allocation

Each phase has a token budget for reading/writing context.md:

| Phase | Reads Sections | Writes Section | Budget |
|-------|----------------|----------------|--------|
| 0 | - | enriches §0 | 1,500 |
| 1 | §0 | §1 | 2,200 |
| 2 | §0, §1 | §2 | 10,500 |
| 3 | §0, §1, §2 | §3 | 5,750 |
| 4 | §0-§3, §4* | §4 | 8,000-12,000 |
| 5 | §0-§4 | §5 | 10,000 |
| 6 | §0-§5 | §6 | 6,000 |

*§4 accumulates during Coordinator iterations

### 3.10 Context Discipline

**Critical Rule:** Pass the original query (§0) to every LLM that makes decisions.

```
User query:          "find me the cheapest laptop with nvidia gpu"
                              ↓
Sanitized for Google: "laptop with NVIDIA GPU for sale"
                              ↑
                    "cheapest" removed - good for Google, bad for LLM decisions
```

**Model Applicability:**

| Model | Role | Needs Original Query |
|-------|------|---------------------|
| REFLEX | Classification | Yes - needs original for intent |
| NERVES | Compression | No - operates on gathered context |
| MIND | Planning/Reasoning | **Primary** - most decisions here |
| VOICE | Synthesis | Yes - needs original for response tone |
| EYES | Vision | Yes - needs goal context for extraction |

**Intent vs User Priorities (Different Concepts):**

| Concept | Example Values | Purpose |
|---------|---------------|---------|
| **Intent** (routing) | `transactional`, `informational` | System routing, cache TTL |
| **User Priority** (LLM reads) | "cheapest", "best", "fastest" | LLM decision-making |

Don't pre-classify user priorities. "Transactional" doesn't mean "price-focused" - it just means user wants to buy. The LLM reads "cheapest" directly.

**Anti-Patterns:**
```python
# WRONG - Pre-classifying user priority
if "cheap" in query:
    priority_intent = "price_focused"

# WRONG - Hardcoded workaround for missing context
if intent == "price_focused":
    vendors = reorder_by_price_retailers(vendors)

# WRONG - Only passing sanitized query
result = await select_sources(query=optimized_query)  # Missing original!
```

**Correct Pattern:**
```python
# RIGHT - Pass original query for LLM to interpret
result = await select_sources(
    search_results=results,
    optimized_query=sanitized,      # For search engines
    original_query=user_input       # For LLM decisions
)
```

**Debugging LLM Decision Errors:**
1. IDENTIFY: What decision was wrong?
2. DIAGNOSE: Is the LLM seeing the original query?
3. FIX: Add `original_query` parameter, include in prompt
4. VERIFY: LLM now makes correct decision

**The fix is ALWAYS better context, not programmatic workarounds.**

### 3.11 Document Lifecycle

```
┌────────────────────────────────────────────────────────────────┐
│                    context.md LIFECYCLE                         │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  User Query Arrives                                             │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────┐                                            │
│  │ Create context.md│                                           │
│  │ Write §0 (raw)   │                                           │
│  └────────┬────────┘                                            │
│           │                                                     │
│           ▼                                                     │
│  Phase 0: Query Analyzer ───────► Enrich §0 (resolved_query,    │
│           │                       query_type, content_reference)│
│           ▼                                                     │
│  Phase 1: Reflection ────────────► Write §1                     │
│           │                                                     │
│           ├── CLARIFY ───────────► Return to user (skip save)   │
│           │                                                     │
│           ▼ PROCEED                                             │
│  Phase 2: Context Gatherer ──────► Write §2                     │
│           │                                                     │
│           ▼                                                     │
│  Phase 3: Planner ───────────────► Write §3                     │
│           │                                                     │
│           ├── clarify ───────────► Return to user (skip save)   │
│           │                                                     │
│           ▼ coordinator/synthesis                               │
│  Phase 4: Coordinator ───────────► Write §4 (accumulates)       │
│           │                                                     │
│           ▼                                                     │
│  Phase 5: Synthesis ─────────────► Write §5                     │
│           │                                                     │
│           ▼                                                     │
│  Phase 6: Validation ────────────► Write §6                     │
│           │                                                     │
│           ├── REVISE ────────────► Loop to Phase 5 (max 2)      │
│           ├── RETRY ─────────────► Loop to Phase 3 (max 1)      │
│           ├── FAIL ──────────────► Error to user                │
│           │                                                     │
│           ▼ APPROVE                                             │
│  Phase 7: Save ──────────────────► Save context.md to disk      │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### 3.12 Error Recovery Formats

**On REVISE Loop:**
```markdown
## 6. Validation (Attempt 1)
**Decision:** REVISE
**Revision Hints:** ...

## 5. Synthesis (Attempt 2)
**Response Preview:** [revised response]

## 6. Validation (Attempt 2)
**Decision:** APPROVE
```

**On RETRY Loop:**
```markdown
## 6. Validation (Attempt 1)
**Decision:** RETRY
**Suggested Fixes:** ...

## 3. Task Plan (Attempt 2)
**Previous Attempt Failed:** ...
**New Approach:** ...

## 4. Tool Execution (Attempt 2)
[New tool execution]

## 5. Synthesis (Attempt 2)
[New synthesis]

## 6. Validation (Attempt 2)
**Decision:** APPROVE
```

### 3.13 Multi-Goal Query Structure

When a user query contains multiple distinct goals:

**§3 Task Plan (Multi-Goal):**
```markdown
## 3. Task Plan

### Goals Identified

| ID | Description | Status | Dependencies |
|----|-------------|--------|--------------|
| GOAL_1 | Find gaming laptop under $1500 | in_progress | - |
| GOAL_2 | Recommend mechanical keyboard | pending | - |

### Current Focus
Addressing GOAL_1 first. Will research laptops, then proceed to GOAL_2.

### Execution Plan
1. [GOAL_1] Search memory for laptop research
2. [GOAL_1] Execute internet research if needed
3. [GOAL_2] Search memory for keyboard info
4. [GOAL_2] Execute internet research if needed
```

**§4 Tool Execution (Multi-Goal):**
```markdown
## 4. Tool Execution

### 4.1 Research Results (GOAL_1)
**Tool:** internet.research
**Goal:** GOAL_1 - Find gaming laptop under $1500
**Confidence:** 0.85
**Result:** Found 15 laptops from 4 vendors...

### 4.2 Research Results (GOAL_2)
**Tool:** internet.research
**Goal:** GOAL_2 - Recommend mechanical keyboard
**Confidence:** 0.80
**Result:** Found 8 keyboards from 3 vendors...
```

**§6 Validation (Multi-Goal):**
```markdown
## 6. Validation

**Outcome:** APPROVE

### Per-Goal Validation
| Goal | Addressed | Quality | Notes |
|------|-----------|---------|-------|
| GOAL_1 | ✓ | 0.85 | Found 15 options within budget |
| GOAL_2 | ✓ | 0.80 | Found 8 quality keyboards |

**Overall Quality:** 0.825
```

---

## 4. research.md Specification

**Location:** `panda-system-docs/users/{user_id}/turns/turn_XXXXXX/research.md`

**Purpose:** Contains **full research results** from internet.research tool calls:
- Complete vendor information
- All product listings with prices
- Evergreen knowledge (facts that don't expire)
- Time-sensitive data (prices, availability)
- Source URLs and confidence scores

**Key Feature:** This is where the **full detail** lives. context.md links here.

```markdown
# Research Document
**ID:** research_759_abc123
**Turn:** 759
**Session:** henry
**Query:** Syrian hamsters for sale online

## Metadata
- **Topic:** pet.hamster.syrian_hamster
- **Intent:** transactional
- **Quality:** 0.85
- **Created:** 2025-12-06T18:44:00Z
- **Expires:** 2025-12-07T00:44:00Z (time-sensitive data)

## Evergreen Knowledge
*Facts that don't expire:*

### Reputable Sources
| Vendor | Type | Reliability | URL |
|--------|------|-------------|-----|
| furballcritters.com | Breeder | 0.85 | https://... |
| poppybeehamstery.com | Breeder | 0.80 | https://... |

### General Facts
- Syrian hamsters also called "Golden" or "Teddy Bear" hamsters
- Teddy Bear variety is long-haired, larger, easier to handle
- Typical price range: $10-$70 depending on pedigree

## Time-Sensitive Data
*Expires in 6 hours:*

### Current Listings
| Product | Price | Vendor | In Stock | URL |
|---------|-------|--------|----------|-----|
| Syrian Hamsters | $25-$35 | furballcritters.com | Yes | [link] |
| Retired Breeder | $10 | furballcritters.com | Yes | [link] |

## Linked From
- [turn_000759/context.md](./context.md) §4 Tool Execution
- [turn_000760/context.md](../turn_000760/context.md) §1 Prior Research
```

---

## 5. query_analysis.json Specification

**Location:** `panda-system-docs/users/{user_id}/turns/turn_XXXXXX/query_analysis.json`

**Purpose:** Contains the output from Phase 0 (Query Analyzer with REFLEX model):
- Resolved query (references made explicit)
- Content reference (if asking about specific content from prior turns)
- Query type classification

**Key Feature:** Read by Context Gatherer (Phase 2) to use the resolved query and prioritize loading specific turns.

```json
{
  "original_query": "how many pages is the thread?",
  "resolved_query": "how many pages is the 'Best glass scraper thoughts?' Reddit thread?",
  "was_resolved": true,
  "query_type": "specific_content",
  "content_reference": {
    "title": "Best glass scraper thoughts?",
    "content_type": "thread",
    "site": "reddit.com",
    "source_turn": 847,
    "prior_findings": "Thread about bathroom cleaning tools",
    "source_url": "https://reddit.com/r/Aquariums/comments/abc123/best_glass_scraper",
    "has_webpage_cache": true,
    "webpage_cache_path": "turn_000847/webpage_cache/reddit_abc123/"
  },
  "reasoning": "User said 'the thread' referring to thread discussed in turn N-1."
}
```

**Usage by Context Gatherer:**
1. Loads `query_analysis.json`
2. Sees `has_webpage_cache: true` → checks cached data FIRST
3. If answer found in cache → includes directly in §1 (no navigation)
4. If fresh data needed → includes `source_url` for direct navigation (no search)
5. Falls back to turn index search only if no content_reference

---

## 6. webpage_cache/ Specification

**Location:** `panda-system-docs/users/{user_id}/turns/turn_XXXXXX/webpage_cache/{url_slug}/`

**Purpose:** When the system visits a web page, it creates a webpage_cache capturing everything about that visit. This enables answering follow-up questions from cached data without re-navigating.

**Key Principle:** Context Gatherer checks webpage_cache FIRST before routing to Research.

### 6.1 manifest.json

Describes what was captured and summarizes the content:

```json
{
  "url": "https://reddit.com/r/Aquariums/comments/abc123/best_glass_scraper",
  "url_slug": "reddit_abc123",
  "title": "Best glass scraper thoughts?",
  "visited_at": "2026-01-04T10:30:00Z",
  "turn_number": 847,

  "captured": {
    "page_content": true,
    "screenshot": true,
    "extracted_data": true
  },

  "content_summary": {
    "type": "forum_thread",
    "site": "reddit.com",
    "has_pagination": true,
    "page_info": "Page 1 of 3",
    "comment_count": 47,
    "visible_elements": ["title", "comments", "pagination", "sidebar", "voting"]
  },

  "answerable_questions": [
    "how many pages",
    "how many comments",
    "who wrote the top comment",
    "what is the thread about"
  ]
}
```

### 6.2 page_content.md

Full OCR/text capture of the page:

```markdown
# Page Content: Best glass scraper thoughts?

**URL:** https://reddit.com/r/Aquariums/comments/abc123/best_glass_scraper
**Captured:** 2026-01-04T10:30:00Z

---

## Page Text

r/Aquariums

**Best glass scraper thoughts?**
Posted by u/AquaristBob • 2 days ago

I'm looking for recommendations on glass scrapers for my 75 gallon tank...

[47 comments]

**Top Comment:**
u/ReefKeeper99 • 127 points
I've been using the Flipper Max for 3 years now and it's fantastic...

**Page 1 of 3** | Next →

---

## Visible Elements
- Thread title
- Original post content
- 47 comments (first 25 visible)
- Pagination: Page 1 of 3
- Sidebar with subreddit info
```

### 6.3 extracted_data.json

Structured extractions from the page:

```json
{
  "thread_title": "Best glass scraper thoughts?",
  "author": "u/AquaristBob",
  "posted": "2 days ago",
  "subreddit": "r/Aquariums",
  "comment_count": 47,
  "pagination": {
    "current_page": 1,
    "total_pages": 3
  },
  "top_comments": [
    {
      "author": "u/ReefKeeper99",
      "points": 127,
      "text": "I've been using the Flipper Max for 3 years now..."
    }
  ],
  "products_mentioned": [
    {"name": "Flipper Max", "mentions": 5},
    {"name": "Mag-Float", "mentions": 3}
  ]
}
```

### 6.4 Retrieval Hierarchy

Context Gatherer checks sources in this order (fastest to slowest):

| Priority | Source | When to Use | Speed |
|----------|--------|-------------|-------|
| 1 | manifest.json content_summary | Simple facts (page count, comment count) | Instant |
| 2 | extracted_data.json | Structured data (prices, specs) | Instant |
| 3 | page_content.md | Full text search needed | Instant |
| 4 | Navigate to source_url | Fresh data needed (current price, availability) | Slow |
| 5 | Search | No prior visit, new content | Slowest |

### 6.5 When to Navigate vs Use Cached Data

| Question Type | Use Cached | Navigate |
|---------------|------------|----------|
| "how many pages/comments" | ✓ manifest | |
| "what's the top comment" | ✓ extracted_data | |
| "what did the thread say about X" | ✓ page_content | |
| "what's the current price" | | ✓ (prices change) |
| "is it still in stock" | | ✓ (availability changes) |
| "check for new comments" | | ✓ (user wants fresh) |

---

## 7. Memory Documents

User-specific memory is stored per-user. Global knowledge is shared.

**Per-User Memory:** `panda-system-docs/users/{user_id}/`
```
users/{user_id}/
├── preferences.md      # User preferences (favorite_hamster: Syrian)
└── facts.md            # Learned facts about user
```

**Global Knowledge:** `panda-system-docs/site_knowledge/`
```
site_knowledge/
├── amazon.com.json     # LLM-learned patterns for Amazon
└── bestbuy.com.json    # LLM-learned patterns for Best Buy
```

---

## 8. Link System

### 8.1 How Documents Link

Every document uses **relative markdown links** for provenance.
To support Obsidian, documents also include **wikilinks** to the same targets.

```markdown
## Source References
- [1] [turn_000759/research.md](../turn_000759/research.md) - "Full research"
- [2] [turn_000759/context.md](../turn_000759/context.md) - "Turn context"

## Source References (Obsidian)
- [[turns/turn_000759/research|research_759_abc123]] - "Full research"
- [[turns/turn_000759/context|turn_000759]] - "Turn context"
```

### 8.2 Link Types

| Link Type | From | To | Purpose |
|-----------|------|-----|---------|
| Research Link | context.md §2 | research.md | Get full research details |
| History Link | context.md §2 | prior context.md | Get prior turn details |
| Memory Link | context.md §2 | memory/*.json | Get user facts/preferences |
| Provenance Link | research.md | source URLs | Original data source |
| Backlink | research.md | context.md | Where this research was used |

### 8.3 Following Links

The Context Gatherer can **follow links** when it needs more detail:

```
Context Gatherer 2-Phase Process (MIND model):
  Phase 1 (RETRIEVAL): Identifies relevant turns, decides what to use directly vs follow
  Phase 2 (SYNTHESIS): Follows links to research.md files, extracts details, compiles §1

Link-following is handled internally by the Context Gatherer, not by Reflection.
```

### 8.4 Link-Following Constraints

To prevent runaway retrieval and protect token budgets:

**Depth Limit:**
```python
MAX_LINK_DEPTH = 2

# Level 0: Current context.md (being built)
# Level 1: Linked research.md files
# Level 2: Claim sources within research.md (if any)
# Level 3+: NOT FOLLOWED
```

**Token Budget During Link-Following:**
```python
TOTAL_LINK_BUDGET = 8000  # Total tokens for linked content
PER_DOCUMENT_CAP = 2000   # Max tokens per linked document
STOP_THRESHOLD = 0.80     # Stop at 80% budget consumed
```

---

## 9. Obsidian Integration

### 9.1 Vault Structure

**Obsidian Vault:** The project root (`pandaaiv2/`) can serve as the Obsidian vault.
**Architecture Docs:** `architecture/` contains design documentation.
**Runtime Data:** `turns/`, `memory/` contain runtime data that Obsidian can also view and navigate.

### 9.2 Dual-Link Format

Every document reference includes both link styles:

```markdown
- [turn_000815/context.md](../turn_000815/context.md) | [[turns/turn_000815/context|turn_000815]]
```

- **Markdown link** (left): Relative path for LLMs and programmatic access
- **Wikilink** (right): Obsidian navigation, graph view, backlinks

### 9.3 LinkFormatter Utility

Links are generated mechanically in Phase 7 (Save):

```python
class LinkFormatter:
    def __init__(self, vault_root: Path = Path("turns")):
        self.vault_root = vault_root

    def dual_link(self, from_file: Path, to_file: Path, label: str) -> str:
        """Generate both link styles from one call."""
        # Relative markdown link (for LLMs)
        rel_path = os.path.relpath(to_file, from_file.parent)
        md_link = f"[{label}]({rel_path})"

        # Obsidian wikilink (for humans)
        vault_path = to_file.relative_to(self.vault_root)
        wiki_link = f"[[{vault_path.with_suffix('')}|{label}]]"

        return f"{md_link} | {wiki_link}"
```

### 9.4 Frontmatter Standard

All documents include YAML frontmatter for indexing and Obsidian filtering:

```yaml
---
id: turn_000815_context
turn_number: 815
session_id: user_abc
topic: commerce.laptop
intent: transactional
content_types: [context, research]
scope: user
quality: 0.85
created_at: 2026-01-04T10:45:30Z
---
```

| Key | Type | Description |
|-----|------|-------------|
| `id` | string | Unique document identifier |
| `turn_number` | int | Turn sequence number |
| `session_id` | string | User/session identifier |
| `topic` | string | Hierarchical topic (e.g., `commerce.laptop`) |
| `intent` | string | Query intent: `transactional`, `navigation`, `informational` |
| `content_types` | list | Content types in doc: `context`, `research`, `pricing` |
| `scope` | string | `user` or `system` |
| `quality` | float | Quality score 0.0-1.0 |
| `created_at` | datetime | ISO 8601 timestamp |

### 9.5 Block IDs and Tags

**Block IDs** for precision linking to specific claims or decisions:

```markdown
- HP Victus 15 @ $649 (walmart.com) ^claim-001
- Decision: PROCEED ^decision-reflection
```

These enable direct links: `[[turn_000815/context#^claim-001]]`

**Standard Tags** for filtering:

| Tag | Usage |
|-----|-------|
| `#turn` | Turn documents |
| `#context` | Context files |
| `#research` | Research output |
| `#metrics` | Performance metrics |
| `#decision` | Decision points |

### 9.6 Non-Markdown Artifacts

For JSON/CSV files that should appear in Obsidian, create a `.md` wrapper:

```markdown
# metrics (turn_000815)

- Source: [metrics.json](./metrics.json)
- Linked turn: [[turns/turn_000815/context|turn_000815]]

## Key Fields
- total_duration_ms: 2340
- total_tokens: 6850
```

### 9.7 Index Notes

Each major directory should include an `index.md` for navigation:

```markdown
# Turns Index

Recent turns and navigation.

## Recent
- [[turns/turn_000815/context|Turn 815]] - laptop research
- [[turns/turn_000814/context|Turn 814]] - budget discussion

## By Topic
- #commerce - Shopping queries
- #research - Information gathering
```

Locations:
- `turns/index.md`
- `memory/index.md`
- `research_cache/index.md`

---

## 10. Context Gatherer Flow (2-Phase)

The Context Gatherer (using **MIND** model) uses a **2-phase LLM-driven approach** that handles all retrieval and link-following internally.

### 10.1 Phase 1: RETRIEVAL

```python
def retrieval_phase(query, turn_number, preferences):
    """
    Phase 1: Identify relevant context and decide what to follow
    Model: MIND (Qwen3-Coder-30B-Instruct)
    """
    # 1. Load deterministic inputs
    turn_index = load_turn_index(session_id, limit=20)
    cached_intel = check_intelligence_cache(query, preferences)
    research_hits = search_research_index(query, preferences)
    strategy_patterns = load_matching_strategies(query)

    # 2. LLM evaluates and decides
    retrieval_result = llm_call(
        model="MIND",
        recipe="context_gatherer_retrieval.yaml",
        inputs={
            "query": query,
            "turn_index": turn_index,
            "cached_intel": cached_intel,
            "research_hits": research_hits,
            "strategy_patterns": strategy_patterns
        }
    )

    return retrieval_result
```

### 10.2 Phase 2: SYNTHESIS

```python
def synthesis_phase(query, retrieval_result):
    """
    Phase 2: Follow links and compile final context.md §1
    Model: MIND (Qwen3-Coder-30B-Instruct)
    """
    # 1. Load linked documents (if any)
    linked_content = {}
    for link in retrieval_result.links_to_follow:
        doc = read_document(link.path)
        linked_content[link.path] = extract_sections(doc, link.sections_to_extract)

    # 2. LLM compiles final §1
    context_section = llm_call(
        model="MIND",
        recipe="context_gatherer_synthesis.yaml",
        inputs={
            "query": query,
            "direct_info": retrieval_result.direct_info,
            "linked_content": linked_content,
            "preferences": preferences
        }
    )

    return context_section  # context.md §1
```

### 10.3 Key Principle: Internal Link-Following

Link-following happens **within** the Context Gatherer's 2-phase process:
- Phase 1 (RETRIEVAL) decides which links to follow
- Phase 2 (SYNTHESIS) loads and extracts from those links

There is **no GATHER_MORE loop** from Reflection back to Context Gatherer.

---

## 11. Decisions and Routing

### 11.1 Reflection Decisions

Reflection (using **REFLEX** model) reviews the user query and context.md §1:

| Decision | Meaning | Next Action |
|----------|---------|-------------|
| PROCEED | Query is clear, system can continue | Go to Planner |
| CLARIFY | Query is ambiguous | Ask user |

**Note:** Reflection does NOT assess research sufficiency. It only determines if the query is clear enough to proceed.

### 11.2 Planner Routing (Research Sufficiency)

The **Planner** (Phase 3, using **MIND** model) decides whether gathered context is sufficient or if tools are needed:

```
┌─────────────────────────────────────────────────────────────────┐
│              SUFFICIENCY ASSESSMENT (informs §1)                │
│            Planner uses this to decide routing in §3            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SUFFICIENT + transactional  → Planner routes to Synthesis      │
│       (have fresh listings)    (skip tools, use cached research)│
│                                                                 │
│  SUFFICIENT + informational  → Planner routes to Synthesis      │
│       (have evergreen facts)   (skip tools, use cached facts)   │
│                                                                 │
│  STALE_RESEARCH              → Planner routes to Coordinator    │
│       (have evergreen, need    (refresh time-sensitive data)    │
│        fresh prices)                                            │
│                                                                 │
│  NEEDS_RESEARCH              → Planner routes to Coordinator    │
│       (no relevant research)   (full research needed)           │
│                                                                 │
│  NEEDS_MORE                  → Planner routes to Coordinator    │
│       (have partial info)      (tools will gather remaining)    │
│                                                                 │
│  AMBIGUOUS                   → Reflection returns CLARIFY       │
│       (query unclear)          (ask user)                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Routing Authority:** The Planner (Phase 3) is the single source of truth for routing decisions.

---

## 12. Research Document Lifecycle

### 12.1 Creation

```
User Query → Coordinator (MIND) → internet.research tool
                              ↓
                         Tool Results
                              ↓
                    ┌─────────────────┐
                    │ research.md     │
                    │ - Evergreen     │
                    │ - Time-Sensitive│
                    │ - Links         │
                    └─────────────────┘
                              ↓
                    Index in database
                              ↓
                    Link from context.md
```

### 12.2 Retrieval

```
New Query → Context Gatherer (MIND)
                ↓
        Infer Topic (using preferences)
                ↓
        Search Research Index
                ↓
        ┌───────────────────────────────┐
        │ Found: research_759           │
        │ Topic: pet.hamster.syrian     │
        │ Quality: 0.85                 │
        │ Age: 2 hours                  │
        └───────────────────────────────┘
                ↓
        Include summary in context.md §1
                ↓
        (Phase 2 SYNTHESIS) Follow links for full content
```

### 12.3 Expiration and Refresh

```
Research Document Lifecycle:

  Created ──────► Active ──────► Stale ──────► Expired
     │              │              │              │
     │              │              │              │
   Index         Retrieve      Refresh?       Archive
                 + Use         (new query)    (cleanup)
                                    │
                                    ▼
                              New research.md
                              (supersedes old)
```

### 12.4 Scope Promotion

```
New Scope ──────► User Scope ──────► Global Scope
    │                  │                   │
    │                  │                   │
 trust >= 0.50     trust >= 0.80       Proven reliable
 usage >= 3        usage >= 10         across users
 age >= 1 hour     age >= 24 hours
```

---

## 13. File Structure

```
pandaaiv2/                              # Project root (can serve as Obsidian vault)
│
├── architecture/                       # Design documentation (NOT runtime data)
│   ├── DOCUMENT-IO-SYSTEM/
│   │   └── DOCUMENT_IO_ARCHITECTURE.md # This document
│   ├── main-system-patterns/
│   ├── mcp-tool-patterns/
│   └── LLM-ROLES/
│
└── panda-system-docs/                  # Runtime data root
    │
    ├── users/                          # Per-user persistent data
    │   └── {user_id}/                  # e.g., "henry", "bob"
    │       ├── preferences.md          # User preferences
    │       ├── facts.md                # Learned facts about user
    │       └── turns/                  # User's turn history
    │           └── turn_000001/
    │               ├── query_analysis.json  # Phase 0 output
    │               ├── context.md           # Turn context (§0-§6)
    │               ├── research.md          # Full research details
    │               ├── research.json        # Structured research data
    │               ├── toolresults.md       # Tool execution details
    │               ├── ticket.md            # Task plan from Planner
    │               ├── metrics.json         # Observability data
    │               ├── metadata.json        # Turn metadata
    │               └── webpage_cache/       # Cached page visit data
    │                   └── {url_slug}/
    │                       ├── manifest.json
    │                       ├── page_content.md
    │                       ├── extracted_data.json
    │                       └── screenshot.png
    │
    ├── site_knowledge/                 # Global: LLM-learned site patterns
    │   ├── amazon.com.json
    │   └── bestbuy.com.json
    │
    ├── observability/                  # Global: Aggregated metrics
    │   ├── daily/
    │   │   └── YYYY-MM-DD.json
    │   └── trends.db
    │
    ├── indexes/                        # Database indexes (migrating to PostgreSQL)
    │   ├── turn_index.db               # Indexes all users' turns
    │   ├── research_index.db           # Indexes research documents
    │   └── source_reliability.db       # Source validation tracking
    │
    └── archive/                        # Cold storage for old turns
        └── YYYY-MM/
            └── {user_id}/
                └── turn_XXXXXX/
```

**Note:** SQLite databases in `indexes/` are migrating to PostgreSQL. See `architecture/DOCKER-INTEGRATION/DOCKER_ARCHITECTURE.md` for migration strategy.

**Note:** The `session_id` field in indexes represents a user identity (permanent), not a temporary session. Turn numbers are per-user.

---

## 14. Example Flows

### 14.1 Example: Using Cached Research

```
User: "Can you find me some for sale online please?"
      (preferences: favorite_hamster=Syrian)
      (Previous turn: discussed Syrian hamster care)

Phase 0 - Query Analyzer (REFLEX):
  ├── Load recent turn summaries (N-1, N-2, N-3)
  ├── Detect: "some" refers to Syrian hamsters from previous turn
  └── Output: QueryAnalysis
      ├── resolved_query: "Can you find me some Syrian hamsters for sale online?"
      ├── content_reference: null (not specific content)
      └── query_type: "followup"

Phase 1 - Reflection (REFLEX):
  ├── Check: Query is clear and actionable? YES
  └── Decision: PROCEED

Phase 2 - Context Gatherer (MIND):
  ├── Use resolved_query for searching
  ├── Infer topic: pet.hamster.syrian_hamster (from preferences)
  ├── Search research index → Found research_759 (2h old)
  ├── Search prior turns → Found turns 758, 759
  └── Build context.md §2 with summaries + links

Phase 3 - Planner (MIND):
  ├── Check: Have research_759 with fresh listings in §2? YES
  ├── Reasoning: Cached research is sufficient, no tools needed
  └── Route: synthesis (skip Coordinator)

Phase 5 - Synthesis (VOICE):
  ├── Read context.md (has research summary)
  ├── Need more detail? Follow link to research_759/research.md
  ├── Extract current listings
  └── Generate response with prices

Result: User gets answer WITHOUT new internet search
        (used cached research from 2 hours ago)
```

### 14.2 Example: Specific Content Reference (With Visit Record)

```
User: "how many pages is the thread?"
      (Previous turn: discussed "Best glass scraper thoughts?" Reddit thread)

Phase 0 - Query Analyzer (REFLEX):
  ├── Load recent turn summaries
  ├── Detect: "the thread" refers to specific content from N-1
  ├── Check: Does turn 847 have webpage_cache for this URL?
  │   └── Found: turn_847/webpage_cache/reddit_abc123/manifest.json
  └── Output: QueryAnalysis
      ├── resolved_query: "how many pages is the 'Best glass scraper thoughts?' Reddit thread?"
      ├── content_reference:
      │   ├── title: "Best glass scraper thoughts?"
      │   ├── content_type: "thread"
      │   ├── site: "reddit.com"
      │   ├── source_turn: 847
      │   ├── source_url: "https://reddit.com/r/Aquariums/comments/abc123/..."
      │   ├── has_webpage_cache: true  ← KEY
      │   └── webpage_cache_path: "turn_000847/webpage_cache/reddit_abc123/"
      └── query_type: "specific_content"

Phase 1 - Reflection (REFLEX):
  ├── Check: Query is clear and actionable? YES
  └── Decision: PROCEED

Phase 2 - Context Gatherer (MIND):
  ├── Load query_analysis.json
  ├── See: has_webpage_cache = true
  ├── Load: turn_847/webpage_cache/reddit_abc123/manifest.json
  │   └── manifest.content_summary.page_info = "Page 1 of 3"
  ├── ANSWER FOUND IN CACHED DATA!
  └── Build context.md §2:
      "The thread has 3 pages (from cached visit record)"

Phase 3 - Planner (MIND):
  ├── Check: Answer is in §2 from cached data
  └── Route: Direct to Synthesis (no tools needed)

Phase 5 - Synthesis (VOICE):
  └── Generate: "The thread has 3 pages."

Result: User gets answer WITHOUT ANY NAVIGATION
        (used cached webpage_cache from 2 hours ago)
```

### 14.3 Example: Question Requiring Fresh Data

```
User: "is the laptop still in stock?"
      (Previous turn: discussed Lenovo LOQ laptop on Best Buy)

Phase 0 - Query Analyzer (REFLEX):
  └── Output: QueryAnalysis
      ├── content_reference:
      │   ├── has_webpage_cache: true
      │   └── source_url: "https://bestbuy.com/site/lenovo-loq/..."
      └── query_type: "specific_content"

Phase 1 - Reflection (REFLEX):
  ├── Check: Query is clear and actionable? YES
  └── Decision: PROCEED

Phase 2 - Context Gatherer (MIND):
  ├── Load webpage_cache manifest
  ├── Question: "is it in stock?" = availability
  ├── Availability changes frequently → cached data may be stale
  └── Build context.md §2:
      "Cached data exists but stock status may have changed.
       source_url available for fresh check."

Phase 3 - Planner (MIND):
  ├── See: User asking about current stock
  ├── Cached data not sufficient for availability
  └── Route: Coordinator with source_url for navigation

Phase 4 - Coordinator (MIND):
  ├── Navigate directly to source_url (no search!)
  └── Extract current stock status

Result: Direct navigation to URL (no search query built)
```

---

## 15. Related Documents

- `architecture/LLM-ROLES/llm-roles-reference.md` - Model stack overview
- `architecture/main-system-patterns/phase*.md` - Phase-by-phase documentation
- `architecture/mcp-tool-patterns/` - Tool implementations
- `apps/prompts/` - Prompt templates
- `apps/recipes/*.yaml` - Token budgets and configs

---

**Last Updated:** 2026-01-06
