# Research Role: Strategy Selection Guide

## Phase Selection Decision Tree

### Input Analysis
Before selecting a strategy, analyze:

1. **Session Intelligence Cache**
   - Check: `sessions/{session_id}/intelligence_cache.json`
   - Has intelligence for this query? (fuzzy match on sorted keywords)
   - If YES: Consider Phase 2 only
   - If NO: Need Phase 1

2. **Query Type Classification**
   - **Transactional:** "find X", "buy Y", "where to get Z" → Product search
   - **Informational:** "how to X", "what is Y" → Context search
   - **Exploratory:** "research X", "learn about Y" → Deep mode

3. **Mode Directive**
   - **Standard (default):** 1-pass, return results
   - **Deep (user-requested):** Multi-pass, iterate until satisfied

4. **User Constraints**
   - Budget, location, delivery preference, quality requirements
   - Used in Phase 2 to filter/rank results

### Strategy Options

#### Option 1: Phase 2 Only
**When to use:**
- Cached intelligence EXISTS for this topic
- Transactional query (find/buy intent)
- Follow-up query in same session
- Token budget is tight

**Benefits:**
- Saves 3000-4000 tokens (skip Phase 1)
- 2-3x faster (30-60s vs 120s)
- Reuses prior research investment

**Process:**
1. Load intelligence from cache
2. Generate targeted queries using credible sources
3. Search products/vendors with intelligence-guided filtering
4. Return results

**Example:**
```
Turn 1: "Research Syrian hamster breeders" → DEEP (Phase 1+2)
Turn 2: "Find Syrian hamsters under $30" → STANDARD (Phase 2 only, reuse cache)
```

#### Option 2: Phase 1 Only
**When to use:**
- RARE: Only if user explicitly wants "just research the topic, don't find vendors"
- Informational intent without product search
- Building intelligence for later queries

**Process:**
1. Generate context queries
2. Visit forums, expert sites, communities
3. Extract meta-intelligence
4. Cache for session
5. Return intelligence summary (no vendors)

**Example:**
```
User: "I want to learn what matters when choosing a hamster breeder, but don't find any yet"
→ Phase 1 only
```

#### Option 3: Combined (Phase 1 → Phase 2)
**When to use:**
- NO cached intelligence for this topic
- First query on new topic
- Transactional query requiring context
- Standard or Deep mode

**Benefits:**
- Comprehensive: Builds intelligence + finds products in one flow
- Efficient: Single research session covers both needs
- Cache-ready: Intelligence saved for follow-ups

**Process:**
1. Execute Phase 1: Gather intelligence (8-10 sources)
2. Cache intelligence to session
3. Execute Phase 2: Use intelligence to find products (10-15 sources)
4. Return products + synthesis

**Example:**
```
User: "Find Syrian hamster breeders under $40"
Session: No prior research on hamster breeders
→ Phase 1 + Phase 2 (combined)
```

### Mode Selection: Standard vs Deep

#### Standard Mode (1-pass)
**When to use:**
- Most queries (default)
- Transactional intent
- User wants quick results
- No "research" or "learn" keywords
- Token budget normal (~8k available)

**Characteristics:**
- Executes 1 pass only
- Returns immediately after completion
- No satisfaction evaluation
- Duration: 60-180s depending on Phase 1/2 selection

#### Deep Mode (Multi-pass)
**When to use:**
- User explicitly says: "research", "learn about", "explore", "investigate"
- Exploratory intent (not transactional)
- User wants comprehensive understanding
- Complex multi-faceted queries
- Token budget generous (~10k+ available)

**Characteristics:**
- Executes 1-3 passes
- Evaluates satisfaction after each pass
- Generates refined queries if continuing
- Duration: 120-360s depending on iterations

**Triggers:**
- User query contains: "research", "learn", "explore", "deep dive", "comprehensive"
- Coordinator explicitly specifies: `mode: "deep"`
- Multiple sub-questions in query

## Decision Examples

### Example 1: First Query, Transactional
**Query:** "Find Syrian hamster breeders under $40"
**Analysis:**
- Cached intelligence: NO
- Query type: Transactional (find intent)
- Mode: STANDARD (no "research" keyword)

**Decision:**
→ **Phase 1 + Phase 2 (Combined), Standard Mode (1-pass)**

**Reasoning:**
- Need intelligence (first query on topic)
- Transactional intent requires products
- Standard mode sufficient for direct query

---

### Example 2: Follow-up Query, Cached Intelligence
**Query:** "Show me Syrian hamster breeders in California"
**Analysis:**
- Cached intelligence: YES (from previous query about hamster breeders)
- Query type: Transactional
- Mode: STANDARD

**Decision:**
→ **Phase 2 Only, Standard Mode (1-pass)**

**Reasoning:**
- Intelligence already cached
- Just need to find specific vendors
- Saves 40-60% tokens

---

### Example 3: Exploratory Research
**Query:** "Research Syrian hamster breeders, I want to understand genetics and reputation"
**Analysis:**
- Cached intelligence: NO
- Query type: Exploratory (research intent)
- Mode: DEEP (user said "research")
- Sub-goals: genetics, reputation

**Decision:**
→ **Phase 1 + Phase 2 (Combined), Deep Mode (multi-pass)**

**Reasoning:**
- Need comprehensive intelligence
- Multiple aspects to explore (genetics, reputation)
- User wants understanding, not just vendor list
- Iterate until both aspects covered

---

### Example 4: Informational Only
**Query:** "What should I look for when choosing a hamster breeder?"
**Analysis:**
- Cached intelligence: NO
- Query type: Informational (no buy intent)
- Mode: STANDARD

**Decision:**
→ **Phase 1 Only, Standard Mode (1-pass)**

**Reasoning:**
- User wants knowledge, not vendors
- Phase 1 gathers expert advice, forum discussions
- No product search needed

---

### Example 5: Token Budget Constraint
**Query:** "Find Syrian hamster breeders"
**Analysis:**
- Cached intelligence: NO
- Token budget: 5000 tokens remaining (low!)
- Query type: Transactional

**Decision:**
→ **Phase 2 Only (skip Phase 1), Standard Mode (1-pass)**
OR
→ **Downgrade to QUICK strategy, fewer sources**

**Reasoning:**
- Phase 1 + Phase 2 would exceed budget (~8k tokens)
- Must choose: Either skip Phase 1 or reduce source count
- Prefer Phase 2 with generic queries (no intelligence)

---

## Strategy Configuration Output

When you select a strategy, output this structure in `research_plan.md`:

```markdown
## Strategy Decision

- **Mode:** [STANDARD | DEEP]
- **Execution:** [Phase 1 + Phase 2 | Phase 2 only | Phase 1 only]
- **Reason:** [Brief explanation]
- **Token budget allocation:**
  - Phase 1: [N tokens | skipped]
  - Phase 2: [N tokens]
  - Total estimated: [N tokens]

## Phase 1 Configuration (if executing)
- Max sources: 8-10
- Context queries: [list 4-5 queries]
- Expected intelligence fields: [topics, sources, criteria, ranges]

## Phase 2 Configuration
- Max sources: 10-15
- Targeted queries: [list 3-5 queries]
- Match criteria: [user constraints]
- Intelligence source: [cached | fresh from Phase 1 | none]
```

## Common Mistakes to Avoid

❌ **Always doing Phase 1+2:** Wastes tokens when intelligence is cached
✅ **Check cache first:** Reuse when available

❌ **Phase 2 without intelligence on new topics:** Low-quality results
✅ **Phase 1+2 on first query:** Build intelligence base

❌ **Deep mode for simple transactional queries:** Wastes time
✅ **Standard mode default:** Only Deep when user explicitly wants research

❌ **Ignoring token budget:** Causes downstream failures
✅ **Validate budget before strategy:** Downgrade if needed

❌ **Phase 1 only for transactional queries:** User wanted vendors, not knowledge
✅ **Match phases to intent:** Transactional = Phase 2, Informational = Phase 1

## Integration with Coordinator

The Coordinator provides you with a `plan.md` that includes:

```json
{
  "tool": "internet.research",
  "args": {
    "query": "...",
    "research_goal": "...",
    "mode": "standard|deep"  // ← Coordinator's recommendation
  }
}
```

You MUST respect the `mode` directive, but YOU decide the Phase 1/2 strategy based on session context.

**Coordinator says "standard" →** You decide: Phase 2 only OR Phase 1+2
**Coordinator says "deep" →** You decide: Multi-pass with Phase 1+2

The Coordinator provides intent and mode. You provide execution strategy.
