# Context Document Log

Quick reference for document flow through the 8-phase pipeline.

---

## Phase-by-Phase IO

| Phase | LLM | Inputs | Outputs |
|-------|-----|--------|---------|
| 0 | REFLEX | raw_query, turn_summaries (N-1, N-2, N-3) | query_analysis.json, context.md §0 (enriched) |
| 1 | REFLEX | query_analysis.json | context.md §1 (reflection decision) |
| 2 | MIND | query_analysis.json, turn_index.db, research_index.db, intelligence_cache, webpage_cache/ | context.md §2 |
| 3 | MIND | context.md §0-§2 | context.md §3, ticket.md |
| 4 | MIND | context.md §0-§3, ticket.md, §4 (accumulates) | context.md §4, toolresults.md |
| 5 | VOICE | context.md §0-§4, toolresults.md | context.md §5, response.md |
| 6 | MIND | context.md §0-§5, response.md | context.md §6 |
| 7 | None | context.md (complete) | turns/turn_XXXXXX/ (persisted) |

---

## Section Input Sources

### §0 User Query
```
Sources:
├── raw_query (user input)
├── turn_summaries[N-1, N-2, N-3] (from turn_index.db)
└── Phase 0 enrichment:
    ├── resolved_query
    ├── query_type
    └── content_reference
```

### §1 Reflection Decision
```
Sources:
├── context.md §0 (query)
└── query_analysis.json (Phase 0 output)
```

### §2 Gathered Context
```
Sources:
├── query_analysis.json (Phase 0 output)
├── context.md §1 (reflection decision - PROCEED)
├── turn_index.db (prior turn summaries)
├── research_index.db (cached research hits)
├── intelligence_cache/ (session intel)
├── webpage_cache/ (cached page data)
│   ├── manifest.json
│   ├── page_content.md
│   └── extracted_data.json
├── memory/preferences.json
├── memory/facts.json
└── prior context.md files (via links_to_follow)
```

### §3 Task Plan
```
Sources:
├── context.md §0 (query)
├── context.md §1 (reflection decision)
└── context.md §2 (gathered context)

Outputs:
├── context.md §3
└── ticket.md (structured task breakdown)
```

### §4 Tool Execution
```
Sources:
├── context.md §0-§3
├── ticket.md
├── §4 prior iterations (accumulates)
└── Tool results (internet.research, memory.*, file.*, etc.)

Outputs:
├── context.md §4 (iterations + claims)
└── toolresults.md (detailed results)
```

### §5 Synthesis
```
Sources:
├── context.md §0-§4
├── toolresults.md
└── research.md (via links if needed)

Outputs:
├── context.md §5
└── response.md (user-facing response)
```

### §6 Validation
```
Sources:
├── context.md §0-§5
└── response.md

Outputs:
├── context.md §6
└── Decision: APPROVE | REVISE | RETRY | FAIL
```

---

## Turn Directory Structure

```
turns/turn_XXXXXX/
├── query_analysis.json     # Phase 0 output
├── context.md              # §0-§6 accumulated
├── ticket.md               # Phase 3 task plan
├── toolresults.md          # Phase 4 tool details
├── response.md             # Phase 5 user response
├── research.md             # Full research (if any)
├── research.json           # Structured research data
├── metrics.json            # Timing/decisions/quality
├── metadata.json           # Turn metadata
└── webpage_cache/          # Cached page visits
    └── {url_slug}/
        ├── manifest.json
        ├── page_content.md
        ├── extracted_data.json
        └── screenshot.png
```

---

## Database Sources

| Database | Used By | Content |
|----------|---------|---------|
| turn_index.db | Phase 0, 2 | Turn summaries, topic, quality |
| research_index.db | Phase 2 | Research docs by topic/query |
| source_reliability.db | Phase 4, 6 | Domain trust scores |

---

## Loop Flows

```
REVISE Loop (max 2):
  Phase 6 → Phase 5 → Phase 6

RETRY Loop (max 1):
  Phase 6 → Phase 3 → Phase 4 → Phase 5 → Phase 6

Combined max: 3 iterations (2 REVISE + 1 RETRY)
```

---

## Role Assignment Summary

All text roles use MIND model (Qwen3-Coder-30B-AWQ) with different temperatures:

| Role | Temp | Phases | Purpose |
|------|------|--------|---------|
| REFLEX | 0.3 | 0, 1 | Fast gates, classification, reflection |
| MIND | 0.5 | 2, 3, 4, 6 | Context gathering, planning, coordination, validation |
| VOICE | 0.7 | 5 | User-facing synthesis |
| EYES | 0.3 | 4 (swap) | Vision processing (Qwen3-VL-2B, separate model) |

---

**Last Updated:** 2026-01-06
