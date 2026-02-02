# Obsidian Memory Architecture

**Status:** SPECIFICATION
**Version:** 1.0
**Updated:** 2026-01-23

---

## Overview

Obsidian Memory is PandaAI's **forever memory system** - a persistent knowledge store that enables the system to remember across sessions, learn from past research, and build cumulative knowledge over time.

### The Problem

Without persistent memory:
- Every session starts from zero
- Research findings are lost after the turn ends
- User preferences must be re-learned
- The system can't say "last time you asked about X, we found Y"

### The Solution

A structured markdown vault (`obsidian_memory/`) that:
- Stores research findings permanently
- Tracks user preferences
- Archives important context
- Enables semantic search across all knowledge

---

## Core Principles

### 1. Forever Memory
Knowledge persists indefinitely. Research done in January is still available in December.

### 2. Structured Storage
Everything has a place. Research goes in `/Knowledge/Research/`, preferences in `/Preferences/`, etc.

### 3. Searchable
All content is indexed and searchable by topic, tags, and semantic similarity.

### 4. Traceable
Every artifact has metadata: when created, from what source, confidence level.

### 5. Cumulative
New knowledge builds on old. We don't overwrite - we accumulate and link.

---

## Integration with Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                     8-PHASE PIPELINE + MEMORY                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  User: "find me a cheap gaming laptop"                              │
│                                                                      │
│  Phase 0: Query Analyzer                                            │
│      │                                                               │
│      ▼                                                               │
│  Phase 1: Reflection (PROCEED/CLARIFY)                              │
│      │                                                               │
│      ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Phase 2: Context Gatherer                                    │    │
│  │                                                              │    │
│  │   1. Search turn_index.db (recent 5 turns)                  │    │
│  │   2. Search obsidian_memory/ ◄── FOREVER MEMORY             │    │
│  │      - /Knowledge/Research/  → past research on laptops     │    │
│  │      - /Knowledge/Products/  → known products               │    │
│  │      - /Preferences/         → user's budget preferences    │    │
│  │   3. Build context.md with all relevant knowledge           │    │
│  │                                                              │    │
│  └─────────────────────────────────────────────────────────────┘    │
│      │                                                               │
│      ▼                                                               │
│  Phase 3: Planner                                                   │
│      │                                                               │
│      ▼                                                               │
│  Phase 4: Coordinator (executes tools, including research)         │
│      │                                                               │
│      ▼                                                               │
│  Phase 5: Synthesis                                                 │
│      │                                                               │
│      ▼                                                               │
│  Phase 6: Validation                                                │
│      │                                                               │
│      ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Phase 7: Save                                                │    │
│  │                                                              │    │
│  │   1. Save turn to turn_index.db (existing)                  │    │
│  │   2. Extract knowledge to save ◄── FOREVER MEMORY           │    │
│  │      - Research findings → /Knowledge/Research/             │    │
│  │      - Product info → /Knowledge/Products/                  │    │
│  │      - User preferences → /Preferences/                     │    │
│  │   3. Update indexes                                         │    │
│  │                                                              │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Folder Structure

```
panda_system_docs/
└── obsidian_memory/
    │
    ├── /Knowledge/                  # What we've learned
    │   │
    │   ├── /Research/               # Research findings from internet research
    │   │   ├── gaming_laptops_rtx_4060.md
    │   │   ├── best_budget_monitors.md
    │   │   └── ...
    │   │
    │   ├── /Products/               # Product knowledge
    │   │   ├── lenovo_loq_15.md
    │   │   ├── msi_thin_gf63.md
    │   │   └── ...
    │   │
    │   └── /Facts/                  # Verified facts
    │       ├── rtx_4060_specs.md
    │       └── ...
    │
    ├── /Preferences/                # User preferences learned over time
    │   └── /User/
    │       ├── default.md           # Default user preferences
    │       └── {user_id}.md         # Per-user preferences
    │
    ├── /Context/                    # Archived context documents
    │   └── /Turns/                  # Significant context.md archives
    │       ├── gaming_laptop_research_2026-01.md
    │       └── ...
    │
    ├── /Logs/                       # Change tracking
    │   ├── /Sessions/               # Session summaries
    │   │   └── 2026-01-23.md
    │   └── /Changes/                # Knowledge updates
    │       └── 2026-01-23_research_added.md
    │
    └── /Meta/                       # System files
        ├── /Indexes/                # Search indexes
        │   ├── topic_index.md       # Topics → notes
        │   ├── product_index.md     # Products → notes
        │   ├── tag_index.md         # Tags → notes
        │   └── recent_index.md      # Recently modified
        │
        ├── /Templates/              # Note templates
        │   ├── research_finding.md
        │   ├── product_knowledge.md
        │   └── user_preference.md
        │
        └── /Config/
            └── memory_config.yaml   # Memory system config
```

---

## Artifact Format

Every note in obsidian_memory has YAML frontmatter for metadata and searchability.

### Research Finding Template

```markdown
---
artifact_type: research
topic: gaming laptops
subtopic: rtx 4060 budget options
created: 2026-01-23T10:30:00
modified: 2026-01-23T10:30:00
source: internet_research
source_urls:
  - reddit.com/r/GamingLaptops
  - tomshardware.com/reviews/best-gaming-laptops
confidence: 0.85
status: active
tags:
  - gaming
  - laptops
  - rtx-4060
  - budget
related:
  - "[[lenovo_loq_15]]"
  - "[[msi_thin_gf63]]"
expires: 2026-07-23  # Research may be stale after 6 months
---

# RTX 4060 Budget Gaming Laptops

## Summary
Research findings on budget gaming laptops with RTX 4060 GPUs.

## Key Findings

### Recommended Models
- **Lenovo LOQ 15**: Best value, consistently recommended on Reddit
- **MSI Thin GF63**: Budget champion per Tom's Hardware
- **ASUS TUF Gaming**: Durability focus

### Price Expectations
| Tier | Price Range |
|------|-------------|
| Budget | $700-900 |
| Good Value | $800-1000 |
| Premium | $1000+ |

### Specs to Look For
- RTX 4060 (sweet spot for budget gaming)
- 16GB RAM minimum
- 512GB SSD or larger
- 144Hz display

### Warnings
- Avoid Brand X: thermal throttling issues reported
- Check for sales at Best Buy (often has deals)

## Sources
| Source | Date | Relevance |
|--------|------|-----------|
| reddit.com/r/GamingLaptops | 2026-01-23 | User recommendations |
| tomshardware.com | 2026-01-23 | Expert reviews |

## Related Research
- [[best_gaming_laptops_2026]]
- [[rtx_4060_vs_4050_comparison]]
```

### Product Knowledge Template

```markdown
---
artifact_type: product
product_name: Lenovo LOQ 15
category: gaming laptop
created: 2026-01-23T10:30:00
modified: 2026-01-23T10:30:00
source: internet_research
confidence: 0.9
status: active
tags:
  - lenovo
  - gaming-laptop
  - rtx-4060
related:
  - "[[gaming_laptops_rtx_4060]]"
---

# Lenovo LOQ 15

## Overview
Budget gaming laptop frequently recommended in gaming communities.

## Specifications
| Spec | Value |
|------|-------|
| GPU | NVIDIA RTX 4060 |
| CPU | Intel i5-13420H / AMD Ryzen 5 7535HS |
| RAM | 16GB DDR5 |
| Storage | 512GB NVMe SSD |
| Display | 15.6" 144Hz IPS |

## Price History
| Date | Vendor | Price |
|------|--------|-------|
| 2026-01-23 | Best Buy | $799 |
| 2026-01-23 | Amazon | $849 |

## Community Sentiment
- Reddit: Highly recommended for value
- Tom's Hardware: "Budget champion"

## Pros
- Excellent price/performance ratio
- Good thermals for the class
- Solid build quality

## Cons
- Screen could be brighter
- No per-key RGB

## Related
- [[msi_thin_gf63]] - competitor
- [[gaming_laptops_rtx_4060]] - category research
```

### User Preference Template

```markdown
---
artifact_type: preference
user_id: default
created: 2026-01-23T10:30:00
modified: 2026-01-23T10:30:00
confidence: 0.8
status: active
---

# User Preferences: default

## Budget Preferences
- Prefers "budget" and "value" options
- Typical budget range: $500-1000
- Price sensitivity: High

## Category Preferences
- Gaming laptops: Prefers performance over portability
- Monitors: Prefers larger screens (27"+)

## Brand Preferences
- Positive: Lenovo, ASUS
- Neutral: MSI, Acer
- Negative: (none recorded)

## Shopping Preferences
- Preferred vendors: Best Buy, Amazon
- Avoids: (none recorded)

## Learned From
- Turn 001234: Asked for "cheapest gaming laptop"
- Turn 001456: Chose Lenovo over MSI when given options
```

---

## Search and Retrieval

### How Context Gatherer Searches Memory

```python
async def search_memory(
    query: str,
    folders: list[str] = None,
    tags: list[str] = None,
    limit: int = 10,
) -> list[MemoryResult]:
    """
    Search obsidian_memory for relevant knowledge.

    Search strategy:
    1. Topic match: Query words match topic/subtopic in frontmatter
    2. Tag match: Query relates to tags
    3. Semantic match: Query similar to content
    4. Recency: Prefer recent over old

    Returns:
        List of MemoryResult with path, relevance, summary
    """
```

### Search Priority

1. **Exact topic match** (topic: "gaming laptops" matches query)
2. **Tag match** (tags include relevant terms)
3. **Fuzzy content match** (body contains relevant information, with 85% similarity threshold for spelling variations like "jessika" vs "jessikka")
4. **Recency** (newer knowledge preferred when relevance is equal)

Note: Fuzzy matching uses `difflib.SequenceMatcher` to handle minor spelling variations in names, brands, and technical terms. Words ≤3 characters require exact match to avoid false positives.

### What Gets Included in Context

The Context Gatherer decides what memory to include based on:

| Factor | Weight | Example |
|--------|--------|---------|
| Topic relevance | High | Query about laptops → laptop research |
| Recency | Medium | Recent research > 6-month-old research |
| Confidence | Medium | High-confidence findings prioritized |
| User preference | High | Always include relevant preferences |

---

## Writing to Memory

### When to Write

Phase 7 (Save) writes to memory when:

1. **Research was performed** → Save findings to `/Knowledge/Research/`
2. **Products were found** → Save to `/Knowledge/Products/`
3. **User preference learned** → Save to `/Preferences/`
4. **Significant context** → Archive to `/Context/Turns/`

### What to Write

| Source | Destination | Condition |
|--------|-------------|-----------|
| Phase 1 intelligence | `/Knowledge/Research/` | New research findings |
| Phase 2 products | `/Knowledge/Products/` | New product info |
| User choices | `/Preferences/User/` | User expressed preference |
| context.md | `/Context/Turns/` | Significant research turn |

### Write Protocol

1. **Check for existing note** on same topic
2. **If exists**: Update with new information (don't overwrite, append)
3. **If new**: Create note from template
4. **Update indexes** in `/Meta/Indexes/`
5. **Log the change** in `/Logs/Changes/`

---

## Index Maintenance

### Primary Indexes

Located in `/Meta/Indexes/`:

| Index | Purpose | Updated |
|-------|---------|---------|
| `topic_index.md` | Topic → notes mapping | On every write |
| `product_index.md` | Product → notes mapping | When products added |
| `tag_index.md` | Tag → notes mapping | On every write |
| `recent_index.md` | Last 50 modified notes | On every write |

### Topic Index Format

```markdown
---
artifact_type: index
index_type: topic
modified: 2026-01-23T10:30:00
entry_count: 42
---

# Topic Index

## Gaming
- [[gaming_laptops_rtx_4060]]
- [[gaming_monitors_2026]]
- [[gaming_keyboards]]

## Laptops
- [[gaming_laptops_rtx_4060]]
- [[ultrabook_comparison]]
- [[lenovo_loq_15]]

## Budget
- [[gaming_laptops_rtx_4060]]
- [[budget_monitors]]
```

---

## Expiration and Freshness

### Research Freshness

Research findings have an `expires` field (default: 6 months):

```yaml
expires: 2026-07-23  # Research may be stale after this date
```

When Context Gatherer retrieves expired research:
- Still includes it, but marks as "may be outdated"
- Suggests re-research if query is about current prices/availability

### Preference Persistence

User preferences don't expire but have confidence decay:
- Recent preferences: confidence 0.9
- 30+ days old: confidence 0.7
- 90+ days old: confidence 0.5

---

## Implementation Files

```
apps/tools/memory/
├── __init__.py
├── search.py           # Search obsidian_memory
├── write.py            # Write to obsidian_memory
├── index.py            # Maintain indexes
├── templates.py        # Note templates
└── models.py           # MemoryResult, MemoryNote dataclasses

libs/gateway/
└── context_gatherer.py # Updated to search memory
```

---

## Configuration

```yaml
# panda_system_docs/obsidian_memory/Meta/Config/memory_config.yaml

memory:
  vault_path: panda_system_docs/obsidian_memory

search:
  default_limit: 10
  max_results: 50
  include_expired: true
  recency_weight: 0.3

write:
  auto_index: true
  log_changes: true

expiration:
  research_days: 180      # 6 months
  product_days: 90        # 3 months
  preference_decay: true

folders:
  knowledge: Knowledge
  preferences: Preferences
  context: Context
  logs: Logs
  meta: Meta
```

---

## Example Flow

### User asks about gaming laptops (with memory)

**Turn 1** (January 15):
```
User: "find me a cheap gaming laptop with RTX"

Phase 2 (Context Gatherer):
  - Searches turn_index: no recent turns on laptops
  - Searches obsidian_memory: no existing research
  - Context: minimal

Phase 4 (Coordinator):
  - Runs internet research (Phase 1 + Phase 2)
  - Finds: Lenovo LOQ, MSI Thin, price range $800-1000

Phase 7 (Save):
  - Writes to /Knowledge/Research/gaming_laptops_rtx_4060.md
  - Writes to /Knowledge/Products/lenovo_loq_15.md
  - Updates topic_index.md
```

**Turn 2** (January 23):
```
User: "what about that Lenovo laptop you mentioned?"

Phase 2 (Context Gatherer):
  - Searches turn_index: finds Turn 1 (recent)
  - Searches obsidian_memory:
    - Finds /Knowledge/Research/gaming_laptops_rtx_4060.md
    - Finds /Knowledge/Products/lenovo_loq_15.md
  - Context: rich with prior research!

Phase 3 (Planner):
  - "User is referring to Lenovo LOQ 15 from previous research"
  - "Can provide details without new research"

Phase 5 (Synthesis):
  - Uses memory knowledge to answer directly
  - No new research needed
```

**Turn 3** (March 15):
```
User: "I want to buy a gaming laptop, budget around $800"

Phase 2 (Context Gatherer):
  - Searches obsidian_memory:
    - Finds research (marked "may be outdated" - 2 months old)
    - Finds user preference: budget-conscious
  - Context: includes prior research + staleness note

Phase 3 (Planner):
  - "Have prior research but it's 2 months old"
  - "Prices may have changed - do fresh research"
  - "User prefers budget options - focus on value"
```

---

## Summary

| Aspect | Design |
|--------|--------|
| **Location** | `panda_system_docs/obsidian_memory/` |
| **Purpose** | Forever memory for research, products, preferences |
| **Read** | Context Gatherer (Phase 2) searches memory |
| **Write** | Save phase (Phase 7) writes new knowledge |
| **Format** | Markdown with YAML frontmatter |
| **Search** | Topic match, tag match, semantic, recency |
| **Expiration** | Research: 6 months, Products: 3 months |

The system remembers what it learns and uses that knowledge in future conversations.

---

**Last Updated:** 2026-01-24 (v1.1)

**v1.1 Changes:** Added fuzzy matching (85% similarity threshold) to Search Priority for handling spelling variations in names, brands, and technical terms.
