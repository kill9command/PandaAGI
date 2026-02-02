# Internet Research MCP Architecture

**Status:** SPECIFICATION
**Version:** 5.2
**Updated:** 2026-01-26
**Architecture:** PandaAI v2 (LLM-Driven Research)

---

## Core Principle

**The LLM is the brain. The system provides tools and state.**

Instead of hardcoded phases, extraction pipelines, and complex branching logic, we give the LLM:
- A goal
- Tools (search, visit, done)
- Document-based state
- Constraints (max visits, delays)

The LLM decides what to do, when, and knows when it's done.

---

## Two-Phase Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PHASE 1: INTELLIGENCE                            │
│                                                                      │
│  Goal: Learn about the topic from forums, reviews, articles         │
│  Method: LLM-driven loop with search/visit/done                     │
│  Sources: Reddit, reviews, forums, comparison sites                 │
│  Output: research_state.md with intelligence                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     PHASE 2: PRODUCT FINDING                         │
│                                                                      │
│  Goal: Find products matching Phase 1 intelligence                  │
│  Input: Phase 1 findings + user requirements                        │
│  Method: Visit vendors, extract products                            │
│  Output: Product listings with prices                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 1. Phase 1: Intelligence Gathering (LLM-Driven)

### Overview

Phase 1 uses an **LLM-driven research loop** where the Research Planner decides every action:
- What to search for
- Which pages to visit
- When it has enough information

The system provides tools and executes them. The LLM decides strategy.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    LLM-DRIVEN RESEARCH LOOP                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  TOOLS:                                                              │
│    search(query) → returns URLs + titles + snippets                 │
│    visit(url) → returns sanitized page text                         │
│    done(findings) → exits loop, returns results                     │
│                                                                      │
│  STATE (Document-Based):                                            │
│    research_state.md → goal, findings, visited pages                │
│                                                                      │
│  LOOP:                                                               │
│    1. Research Planner reads state, decides next action             │
│    2. System executes action (search or visit)                      │
│    3. State updated with results                                    │
│    4. Repeat until Planner calls done()                             │
│                                                                      │
│  CONSTRAINTS:                                                        │
│    Max 2 searches                                                   │
│    Max 8 page visits                                                │
│    4-6 second delays between visits                                 │
│    120 second overall timeout                                       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Roles

| Role | Temperature | Purpose |
|------|-------------|---------|
| **Research Planner** | MIND (0.5) | Decides next action, evaluates progress |
| **Result Scorer** | REFLEX (0.3) | Quick scoring of search results |
| **Content Extractor** | MIND (0.5) | Extracts findings from page text |

### The Loop

```
START
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ RESEARCH PLANNER (MIND)                                      │
│                                                              │
│ Reads: research_state.md                                     │
│ Decides: What's the next action?                            │
│                                                              │
│ Options:                                                     │
│   - {"action": "search", "query": "..."}                    │
│   - {"action": "visit", "url": "..."}                       │
│   - {"action": "done"}                                      │
└─────────────────────────────────────────────────────────────┘
  │
  ├─── action = "search" ───────────────────────────────┐
  │                                                      │
  │    ┌────────────────────────────────────────────┐   │
  │    │ BROWSER: Execute Search                     │   │
  │    │ - Navigate to search engine                 │   │
  │    │ - Human-like delays                         │   │
  │    │ - Type query, extract results               │   │
  │    └────────────────────────────────────────────┘   │
  │                         │                            │
  │                         ▼                            │
  │    ┌────────────────────────────────────────────┐   │
  │    │ RESULT SCORER (REFLEX)                      │   │
  │    │ - Score each result for relevance          │   │
  │    │ - Rank by quality                          │   │
  │    └────────────────────────────────────────────┘   │
  │                         │                            │
  │                         ▼                            │
  │    Update research_state.md with search results      │
  │                                                      │
  └──────────────────────────────────────────────────────┘
  │
  ├─── action = "visit" ────────────────────────────────┐
  │                                                      │
  │    ┌────────────────────────────────────────────┐   │
  │    │ BROWSER: Visit Page                         │   │
  │    │ - Navigate to URL                           │   │
  │    │ - Wait for load                             │   │
  │    │ - Detect blockers (CAPTCHA, login)          │   │
  │    │ - Extract and sanitize text                 │   │
  │    │ - Delay 4-6 seconds                         │   │
  │    └────────────────────────────────────────────┘   │
  │                         │                            │
  │                         ▼                            │
  │    ┌────────────────────────────────────────────┐   │
  │    │ CONTENT EXTRACTOR (MIND)                    │   │
  │    │ - Input: page text + goal                   │   │
  │    │ - Output: structured findings               │   │
  │    └────────────────────────────────────────────┘   │
  │                         │                            │
  │                         ▼                            │
  │    Update research_state.md with findings            │
  │                                                      │
  └──────────────────────────────────────────────────────┘
  │
  ├─── action = "done" ─────────────────────────────────┐
  │                                                      │
  │    Return Phase 1 intelligence to caller             │
  │                         │                            │
  └─────────────────────────┴───────────► PHASE 2       │
  │
  ▼
Check constraints:
  - Max iterations reached? → Force done
  - Timeout? → Force done
  │
  ▼
Loop back to RESEARCH PLANNER
```

### Input: Goal + Context + Task

The research tool receives these inputs:

| Input | Source | Purpose |
|-------|--------|---------|
| **goal** | User's original query | Priority signals ("cheapest", "best") |
| **context** | Session history | What we were discussing |
| **task** | Planner (Phase 3) | Specific research task |
| **prior_turn_context** | §1 Prior Turn Context | Conversation context for dynamic query building |
| **topic** | §1 Topic Classification | Subject area being researched |

**Example:**
```python
await execute_research(
    goal="can you tell me about jessika aro?",        # User's words
    context="Previous: Russian troll farms discussion", # From session
    task="Research Jessika Aro",                       # From Planner
    intent="informational",
    prior_turn_context="Discussion about Russian information warfare and troll farms",
    topic="Person (Jessika Aro)",
)
```

The Research Planner LLM sees all context and synthesizes:
- **WHAT** to research (from context/task): Jessika Aro
- **HOW** to build queries (from prior_turn_context): Connect to "Russian information warfare journalist"
- **HOW** to prioritize (from goal): User wants information (informational intent)

### Document-Based State

All state flows through a markdown document:

```markdown
# Research State

## Goal (User's Original Query)
{original_query}

## Context (From Session)
{session_context}

## Prior Turn Context
{prior_turn_context}  <!-- From §1, enables dynamic query building -->

## Topic
{topic}  <!-- From §1 Topic Classification -->

## Task
{planner_task}

## Intent
{informational | commerce}

## Search Results
{list of URLs and titles from search, if searched}

## Visited Pages

### Page 1: {url}
**Visited:** {timestamp}
**Findings:**
{extracted findings from this page}

### Page 2: {url}
**Visited:** {timestamp}
**Findings:**
{extracted findings from this page}

## Intelligence Summary

### What to Look For
{specs, features, recommendations learned}

### Price Expectations
{price ranges discovered}

### Recommended Models
{specific models mentioned positively}

### User Warnings
{things to avoid, common issues}

## Status
{in_progress | sufficient | done}

## Iteration
{current_iteration} / {max_iterations}
```

### Browser Tools

The browser provides simple tools. No complex extraction - just get text.

#### search(query) → SearchResults

```python
async def search(query: str) -> SearchResults:
    """
    Execute a web search.

    1. Navigate to search engine
    2. Human-like delays (3-5s before typing)
    3. Type query with keystroke delays (50-150ms)
    4. Wait for results (2-3s)
    5. Extract result URLs and titles from DOM

    Returns:
        SearchResults with list of {url, title, snippet}
    """
```

#### visit(url) → PageText

```python
async def visit(url: str) -> PageText:
    """
    Visit a page and extract its text.

    1. Navigate to URL
    2. Wait for page load
    3. Detect blockers (CAPTCHA, login wall)
       - If blocked: request intervention or skip
    4. Extract text content via ContentSanitizer
       - Remove: scripts, styles, nav, footer, ads
       - Keep: main content, article, product info
    5. Truncate to ~4000 tokens
    6. Wait 4-6 seconds (human delay)

    Returns:
        PageText with sanitized content
    """
```

### Constraints

| Constraint | Value | Reason |
|------------|-------|--------|
| Max searches | 2 | Avoid detection, usually 1 is enough |
| Max page visits | 8 | Enough for good coverage, limits cost |
| Delay between visits | 4-6 seconds | Human-like behavior |
| Overall timeout | 120 seconds | Don't hang forever |
| Max text per page | 4000 tokens | Fit in context |

### Phase 1 Output

```python
@dataclass
class Phase1Intelligence:
    success: bool
    goal: str

    # What we learned
    intelligence: dict  # specs, recommendations, price expectations
    findings: list      # Key facts discovered

    # For Phase 2
    vendor_hints: list[str]     # Vendors mentioned positively
    search_terms: list[str]     # Good search terms discovered
    price_range: dict           # Expected min/max prices

    # Metadata
    sources: list[str]          # URLs visited
    research_state_md: str      # Full state document
    searches_used: int
    pages_visited: int
    elapsed_seconds: float
```

---

## 2. Phase 2: Product Finding (3 Vendors)

### Overview

Phase 2 uses the intelligence from Phase 1 to find actual products from **3 vendors**.

**Input:** Phase 1 intelligence (what to look for, price range, recommended models)

**Method:**
- Build vendor list from Phase 1 hints + known vendors
- Visit exactly 3 vendors
- Search for products using Phase 1 search terms
- Extract products and compare to Phase 1 price expectations
- Generate recommendation based on Phase 1 intelligence

### Process Flow

```
Phase 1 Intelligence
  │
  ├── vendor_hints: ["amazon", "bestbuy"]
  ├── search_terms: ["Lenovo LOQ RTX 4060"]
  └── price_range: {min: 800, max: 1000}
  │
  ▼
Build vendor list (target: 3):
  1. Vendors from Phase 1 hints
  2. If < 3: Search for "[product] buy" and extract vendor URLs
  3. Known vendors: amazon, bestbuy, newegg, walmart, etc.
  │
  ▼
For each vendor (max 3):
  │
  ├── Build search URL (vendor-specific patterns)
  │   amazon.com/s?k={search_term}
  │   bestbuy.com/site/searchpage.jsp?st={search_term}
  │   newegg.com/p/pl?d={search_term}
  │
  ├── Visit search results page
  │
  ├── Extract products (LLM reads page text)
  │   - name, price, price_numeric, in_stock, specs
  │
  └── Add to product list
  │
  ▼
Generate recommendations:
  +- Compare products to Phase 1 intelligence
  +- Which matches recommended models?
  +- Are prices within expected range?
  +- Generate recommendation text
  │
  ▼
Return Phase2Result with products
```

### Vendor Search URLs

| Vendor | URL Pattern |
|--------|-------------|
| Amazon | `amazon.com/s?k={query}` |
| Best Buy | `bestbuy.com/site/searchpage.jsp?st={query}` |
| Newegg | `newegg.com/p/pl?d={query}` |
| Walmart | `walmart.com/search?q={query}` |
| Target | `target.com/s?searchTerm={query}` |
| B&H | `bhphotovideo.com/c/search?q={query}` |
| Microcenter | `microcenter.com/search/search_results.aspx?Ntt={query}` |

### Phase 2 Output

```python
@dataclass
class Phase2Result:
    success: bool

    # Products found
    products: list[Product]  # name, price, vendor, url, specs

    # Context from Phase 1
    recommendation: str   # Which product is best and why
    price_assessment: str # Are prices good based on Phase 1?

    # Metadata
    vendors_visited: list[str]    # e.g., ["amazon.com", "bestbuy.com", "newegg.com"]
    vendors_failed: list[str]     # Vendors that failed to load
    elapsed_seconds: float

@dataclass
class Product:
    name: str
    price: str              # "$799.99"
    price_numeric: float    # 799.99
    vendor: str             # "amazon.com"
    url: str
    in_stock: bool
    specs: dict
    confidence: float
```

---

## 3. Strategy Selection

| Strategy | When Used | Description |
|----------|-----------|-------------|
| `phase1_only` | Informational queries | LLM-driven research, return intelligence |
| `phase1_and_phase2` | Commerce queries | Research first, then find products |
| `phase2_only` | Commerce + fresh Phase 1 cache | Skip research, go direct to vendors |

### Decision Rules

```
1. Informational intent -> PHASE1_ONLY
   "what is the best X", "how do I", "tell me about"

2. Commerce intent + cached Phase 1 intelligence -> PHASE2_ONLY
   Recent research available for this topic

3. Commerce intent + no cached intelligence -> PHASE1_AND_PHASE2
   Need to learn about topic first, then find products
```

---

## 4. Role Prompts

### Research Planner Prompt

```markdown
# Research Planner

You are planning web research to help answer a user's question.

## Goal
{original_query}

## Intent
{informational | commerce}

## Current State

### Search Results (if any)
{search_results}

### Pages Visited
{list of visited URLs and what was found}

### Evidence So Far
{accumulated_findings}

## Constraints
- You can search up to {remaining_searches} more times
- You can visit up to {remaining_visits} more pages
- You've used {elapsed_time}s of {max_time}s

## Your Decision

Think about:
1. Do I have enough information to answer the user well?
2. If not, what's missing?
3. Should I search, visit a page, or am I done?

For commerce queries, make sure you have:
- Understanding of what makes a good product
- Price expectations
- Recommended models/brands from real users

Output ONE action as JSON:
- {"action": "search", "query": "your search terms", "reason": "why"}
- {"action": "visit", "url": "https://...", "reason": "why"}
- {"action": "done", "reason": "why I have enough"}
```

### Result Scorer Prompt

```markdown
# Result Scorer

Score these search results for relevance to the goal.

## Goal
{original_query}

## Intent
{informational | commerce}

## Search Results
{numbered list of URLs and titles}

## Score Each Result

For each result, output:
- score: 0.0 to 1.0 (how relevant/useful it likely is)
- type: forum | review | vendor | news | official | other
- priority: must_visit | should_visit | maybe | skip

Consider:
- Does the title suggest relevant content?
- Is this a trustworthy source type for this query?
- For commerce: prioritize reviews and forums over vendors

Output as JSON array, ranked by score (highest first).
```

### Content Extractor Prompt

```markdown
# Content Extractor

Extract useful information from this page.

## Goal
{original_query}

## Intent
{informational | commerce}

## Page URL
{url}

## Page Content
{sanitized_page_text}

## What to Extract

### For Informational Queries:
- key_facts: Important information relevant to the goal
- recommendations: Any advice or suggestions
- sources_cited: If the page references other sources

### For Commerce Queries:
- recommended_products: Products mentioned positively
- price_expectations: Price ranges mentioned
- specs_to_look_for: Features users recommend
- warnings: Things to avoid, common issues
- vendors_mentioned: Where users suggest buying

### Always Include:
- relevance: 0.0-1.0 how relevant was this page
- confidence: 0.0-1.0 how confident in the extracted info
- summary: 1-2 sentence summary of what was useful

Output as JSON.
```

---

## 5. Implementation Files

### New Files

```
apps/tools/internet_research/
├── __init__.py              # Exports: execute_research, execute_phase2, execute_full_research
├── state.py                 # ResearchState, to_markdown(), write_to_turn()
├── browser.py               # ResearchBrowser: search(), visit()
├── research_loop.py         # Phase 1: LLM-driven research loop
└── phase2_products.py       # Phase 2: Product finding from 3 vendors

apps/prompts/research/
├── result_scorer.md         # Scorer prompt (ranks search results)
└── content_extractor.md     # Extractor prompt (extracts findings)

apps/prompts/research_planner/
├── core.md                  # Planner core prompt
└── decision_logic.md        # Strategy decision rules + prior intelligence

apps/recipes/recipes/
├── research_planner.yaml    # Recipe for Research Planner
├── research_scorer.yaml     # Recipe for Result Scorer
└── research_extractor.yaml  # Recipe for Content Extractor
```

| File | Purpose |
|------|---------|
| `__init__.py` | Main entry points: `execute_full_research()`, `execute_research()`, `execute_phase2()` |
| `state.py` | `ResearchState` class with `to_markdown()` and `write_to_turn()` |
| `browser.py` | `ResearchBrowser` with `search(query)` and `visit(url)` tools |
| `research_loop.py` | Phase 1 LLM loop: Planner decides, system executes |
| `phase2_products.py` | Phase 2: Visit 3 vendors, extract products, generate recommendations |

### Existing Files (Reused)

| File | Purpose |
|------|---------|
| `apps/services/orchestrator/content_sanitizer.py` | HTML → clean text |
| `apps/services/orchestrator/captcha_intervention.py` | CAPTCHA handling |
| `apps/services/orchestrator/human_search_engine.py` | Browser search |
| `apps/services/orchestrator/web_vision_mcp.py` | Playwright browser management |

### Deprecated Files

| File | Status | Reason |
|------|--------|--------|
| `apps/services/orchestrator/research_orchestrator.py` | DEPRECATED | Replaced by research_loop.py |

### Test Script

```bash
# Test Phase 1 only (informational)
python scripts/test_llm_research.py --phase1-only "what are the best budget gaming laptops"

# Test full research (Phase 1 + Phase 2 with 3 vendors)
python scripts/test_llm_research.py "find me a cheap gaming laptop"

# Customize vendor count
python scripts/test_llm_research.py --vendors 5 "find RTX 4060 laptops"
```

---

## 6. Document IO Compliance

The research subsystem follows Pandora's Document IO architecture for LLM role management.

### Turn Directory Threading

The `turn_dir` is passed through the entire research call chain:

```
unified_flow.py (Phase 4)
    → HTTP POST /internet.research (turn_dir_path in JSON)
    → apps/orchestrator/app.py
    → internet_research_mcp.py::adaptive_research(turn_dir_path)
    → research_role.py::research_orchestrate(turn_dir_path)
    → ResearchLoop(turn_dir=turn_dir)
```

This enables research LLM roles to access turn documents via recipes.

### Recipe-Based Prompts

When `turn_dir` is available, the Research Planner uses recipe-based prompt building:

```python
# In research_loop.py::_get_planner_decision()
if self.turn_dir:
    # Write state for recipe to read
    state.write_to_turn(self.turn_dir)

    # Load recipe and build prompt
    recipe = load_recipe("research_planner")
    builder = DocPackBuilder(use_smart_compression=True)
    pack = await builder.build_async(recipe, self.turn_dir)
    prompt = pack.as_prompt()
```

### State Persistence

`ResearchState.write_to_turn()` writes `research_state.md` to the turn directory:

```python
def write_to_turn(self, turn_dir: TurnDirectory) -> Path:
    output_path = turn_dir.path / "research_state.md"
    output_path.write_text(self.to_markdown())
    return output_path
```

This allows recipes to include `research_state.md` as an input document.

### Prior Intelligence Checking

**Critical:** The Research Planner checks `context.md §2` for prior research intelligence.

If §2 contains relevant intelligence from a previous turn:
- Product recommendations from forums/reviews
- Price expectations and typical ranges
- Key specs and features to look for

The Planner can skip Phase 1 entirely and go directly to Phase 2.

**Decision Matrix:**

| §2 Contains | Decision |
|-------------|----------|
| Full intelligence for this domain | PHASE2_ONLY |
| Partial intelligence (gaps exist) | Targeted Phase 1, then Phase 2 |
| No relevant prior research | PHASE1_THEN_PHASE2 |

This prevents redundant Phase 1 research when the system already has the needed intelligence.

### Recipes

| Recipe | Role | Input Docs | Output |
|--------|------|------------|--------|
| `research_planner.yaml` | Research Planner | context.md, research_state.md | research_plan.md |
| `research_scorer.yaml` | Result Scorer | context.md, research_state.md | scored_results.json |
| `research_extractor.yaml` | Content Extractor | context.md, research_state.md | page_findings.json |

---

## 7. Example Flow

**User:** "Find me a cheap gaming laptop with an RTX card"

### Iteration 1: Research Planner

**Input (research_state.md):**
```markdown
# Research State
## Goal
Find me a cheap gaming laptop with an RTX card
## Intent
commerce
## Search Results
(none yet)
## Visited Pages
(none yet)
## Status
in_progress
## Iteration
1 / 10
```

**Output:**
```json
{
  "action": "search",
  "query": "best budget RTX gaming laptop 2026 reviews reddit",
  "reason": "Need to find reviews and real user opinions on RTX laptops"
}
```

### Iteration 2: After Search

**Updated state with search results...**

**Output:**
```json
{
  "action": "visit",
  "url": "https://reddit.com/r/GamingLaptops/...",
  "reason": "Reddit discussion about budget RTX laptops - real user experiences"
}
```

### Iteration 3: After Reddit Visit

**Updated state with findings:**
- Users recommend Lenovo LOQ for value
- RTX 4060 is sweet spot for budget
- Avoid X brand for thermal issues
- $800-1000 is realistic budget

**Output:**
```json
{
  "action": "visit",
  "url": "https://tomshardware.com/best-budget-gaming-laptops",
  "reason": "Expert review to complement user opinions"
}
```

### Iteration 4: After Tom's Hardware

**Updated state with findings:**
- Confirms Lenovo LOQ recommendation
- Adds MSI Thin as budget option
- Price benchmarks align with Reddit

**Output:**
```json
{
  "action": "done",
  "reason": "Have user recommendations (Reddit), expert reviews (Tom's Hardware), price expectations ($800-1000), and specific models to look for. Ready for Phase 2 product finding."
}
```

### Phase 2: Find Products

Using Phase 1 intelligence:
- Search terms: "Lenovo LOQ RTX 4060", "MSI Thin GF63"
- Vendor hints: Best Buy, Amazon mentioned in reviews
- Price range: $800-1000

Visit vendors, extract products, return with recommendations.

---

## 8. CAPTCHA & Intervention

Same as before - noVNC for human intervention when blocked.

See previous architecture for details on:
- CAPTCHA detection
- noVNC setup
- Intervention flow

---

## 9. Configuration

```bash
# Phase 1 constraints
PHASE1_MAX_SEARCHES=2
PHASE1_MAX_VISITS=8
PHASE1_TIMEOUT_SECONDS=120
PHASE1_VISIT_DELAY_SECONDS=5

# Browser
PLAYWRIGHT_TIMEOUT_MS=30000
BROWSER_HEADLESS=true

# Models
MIND_MODEL=qwen3-coder-30b
MIND_TEMPERATURE=0.5
REFLEX_MODEL=qwen3-coder-30b
REFLEX_TEMPERATURE=0.3

# Content
SANITIZE_MAX_TOKENS=4000
```

---

## Summary

| Aspect | Design |
|--------|--------|
| **Control** | LLM (Research Planner) decides what to do |
| **State** | Document-based (research_state.md) |
| **Roles** | Planner (MIND), Scorer (REFLEX), Extractor (MIND) |
| **Tools** | search(), visit(), done() |
| **Extraction** | Sanitize HTML → LLM reads text |
| **Stopping** | LLM decides when sufficient |
| **Constraints** | Max searches, visits, timeout |
| **Phase 1** | Intelligence gathering (what to look for) |
| **Phase 2** | Product finding (where to buy) |

The LLM plans, executes, evaluates, and knows when it's done. We just provide the tools and constraints.

---

**Last Updated:** 2026-01-26 (v5.2)

**v5.2 Changes:**
- Added Document IO Compliance section (§6): turn_dir threading, recipe-based prompts, state persistence
- Research Planner now checks context.md §2 for prior intelligence before starting Phase 1
- Added new recipe files: research_planner.yaml, research_scorer.yaml, research_extractor.yaml
- Updated implementation files list to reflect new prompt/recipe structure

**v5.1 Changes:** Added `prior_turn_context` and `topic` to research input specification. SearchTermBuilder now receives conversation context for dynamic query building instead of hardcoded patterns.
