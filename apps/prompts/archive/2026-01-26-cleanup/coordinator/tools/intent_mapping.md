# Intent-Aware Tool Selection

## 🌟 NEW (2025-11-15): Use `internet.research` for ALL Research & Commerce

**`internet.research`** is the adaptive research system that automatically:
1. Analyzes your query and session context
2. Uses standard (1-pass) or deep (multi-pass) mode based on your specification
3. Reuses cached intelligence when available (40-60% token savings!)
4. Uses LLM filtering to visit only the best sources

**The Two Modes (You Select):**
- **standard** (60-120s): Single-pass execution (Phase 1 intelligence → Phase 2 search)
  - When: Most queries, quick lookups, follow-up questions
  - Specify: `"mode": "standard"` (default)
- **deep** (120-240s): Multi-pass execution with satisfaction evaluation
  - When: User explicitly requests "deep research", "thorough research", "comprehensive"
  - Specify: `"mode": "deep"`

**When to use `internet.research`:**
- ✅ **ALL research and commerce queries** - it handles everything!
- ✅ Purchase queries: "find hamsters for sale", "price check on cages"
- ✅ Research queries: "learn about hamster care", "what is best breeder"
- ✅ Quick lookups: "quick search for hamster food"
- ✅ Follow-ups: "show me ones under $30" (reuses cache automatically!)

**Example:**
```json
{"tool": "internet.research", "args": {"query": "find Syrian hamsters for sale", "mode": "standard", "session_id": "user-123"}}
```

The tool will automatically:
1. Execute single-pass research (Phase 1 intelligence → Phase 2 search)
2. Gather intelligence from forums, reviews, experts
3. Use intelligence to find products from credible sources
4. Cache intelligence for fast follow-ups

**When NOT to use `internet.research`:**
- ❌ Simple doc lookups (use `doc.search` instead)
- ❌ Code operations (use `file.*`, `git.*`, `code.*`)
- ❌ Memory operations (use `memory.*`)
- ❌ Deep vendor catalog exploration (use `vendor.explore_catalog` instead)

---

## 🆕 NEW (2025-11-16): `vendor.explore_catalog` for Deep Catalog Crawling

**When to use `vendor.explore_catalog`:**
- User asks to explore a **specific vendor's full catalog**
- Follow-up to initial `internet.research` that detected catalog hints
- User wants to see **all available items** from a vendor (not just samples)
- Vendor has pagination, multiple categories, or large inventory

**Trigger Patterns:**
- "explore [vendor name] catalog"
- "show me everything from [vendor]"
- "deep crawl [vendor]"
- "get all items from [vendor]"
- "browse [vendor] full inventory"

**Example:**
```json
{
  "tool": "vendor.explore_catalog",
  "args": {
    "vendor_url": "https://example-shop.com/available",
    "vendor_name": "Example Pet Shop",
    "category": "all",
    "max_items": 20,
    "session_id": "user-123"
  }
}
```

**Two-Step Research Flow:**

**Step 1: Initial Research** (Use `internet.research`)
```
User: "Find Syrian hamster breeders"
You: internet.research → Returns summary + catalog_hints
Response: "Found Example Pet Shop (5+ items detected) 🔍"
```

**Step 2: Deep Catalog Exploration** (Use `vendor.explore_catalog`)
```
User: "explore Example Pet Shop catalog"
You: vendor.explore_catalog → Returns ALL items with pagination
Response: "Here's the complete catalog: 12 items across 3 pages..."
```

**When NOT to use `vendor.explore_catalog`:**
- ❌ Initial research/discovery (use `internet.research` instead)
- ❌ Comparing multiple vendors (use `internet.research` to get summaries)
- ❌ User hasn't specified a vendor yet (need vendor_url)

**Human-in-the-Loop Pattern:**
1. `internet.research` detects catalogs → shows catalog_hints to user
2. User requests deep-dive → use `vendor.explore_catalog`
3. User controls which vendors to explore (token-efficient!)

---

## Intent Mapping (Simplified!)

**informational** - User wants to learn, understand, or find information
- ✅ USE: `internet.research` (will select DEEP or STANDARD strategy)
- ✅ ALSO: `doc.search` for document lookups
- Examples: "how to care for hamsters", "what food do they need", "research breeders"

**transactional** - User wants to buy, find prices, or locate products
- ✅ USE: `internet.research` (will select QUICK/STANDARD/DEEP based on context)
- Examples: "find hamsters for sale", "price check cages", "buy hamster food"

**navigational** - User wants to find a place, breeder, service, or contact
- ✅ USE: `internet.research` (will select DEEP or STANDARD strategy)
- Examples: "find hamster breeders near me", "locate vet", "rescue organizations"

**code** - User wants file/git/bash operations
- ✅ USE: `file.*`, `git.*`, `bash.execute`, `code.*`
- ❌ NEVER: `internet.research`
- Examples: "read config.yml", "create new file", "commit changes"

## Enforcement Rules

1. **MANDATORY: Use `internet.research` for ALL research and commerce queries**
2. **ALWAYS include `session_id`** - enables cache reuse and STANDARD strategy
3. **NEVER worry about strategy selection** - the system decides automatically
4. **Trust the adaptive system** - it will choose QUICK/STANDARD/DEEP optimally

**Why This Matters**:
- Adaptive strategy selection saves 42% tokens across sessions
- Intelligence caching makes follow-ups 2-3x faster
- LLM filtering ensures you only visit high-quality sources
