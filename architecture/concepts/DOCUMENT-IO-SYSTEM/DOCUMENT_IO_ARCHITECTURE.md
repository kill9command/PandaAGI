# Document IO Architecture

**Version:** 3.4
**Updated:** 2026-02-04

---

## 1. Core Principle

**Everything is a document.**

Every piece of information in the system lives in a markdown document. Documents link to each other for provenance and detail retrieval. Summarized context lives in `context.md`; full details live in linked documents.

---

## 2. context.md — The Working Document

`context.md` is the single working document that accumulates state across all phases of the pipeline. Each phase reads the document, performs its work, and appends a new section.

**Design rules:**
- **Single source of truth** for the turn
- **Append-only** during pipeline execution — phases never modify prior sections
- **Original query always preserved** in §0
- Sections map to phases
 - Turn Summary Appendix is appended after Phase 8 completes

### Section Layout

| Section | Written By | Content |
|---------|-----------|---------|
| §0 | Phase 1 (Query Analyzer) | Original query, resolved query, user purpose, data requirements, mode, reference resolution |
| §1 | Phase 1.5 (Query Analyzer Validator) | PASS/RETRY/CLARIFY decision with reasoning and retry guidance |
| §2 | Phase 2.2 (Context Synthesis) | Gathered context — prior turns, cached research, preferences |
| §3 | Phase 3 (Planner) | Strategic plan, goals, routing decision |
| §4 | Phase 4–5 (Executor + Coordinator) | Tool execution log — accumulates across iterations |
| §5 | Phase 6 (Synthesis) | User-facing response |
| §6 | Phase 7 (Validation) | Quality assessment, per-goal validation if multi-goal |
| Appendix | Phase 8 (Save) | Turn Summary Appendix appended at end of context.md |

**Sub-Phase Note:** Phases 1.5, 2.1, 2.2, and 2.5 do not create their own numbered sections beyond §1. They enrich the owning phase’s output and validation.

### Section Immutability

- §0–§1 are immutable after Phase 1 completes
- §2–§3 are immutable after their phase completes
- §4 accumulates during the Executor–Coordinator loop
- §5 may be rewritten on REVISE loops
- §3–§6 may be rewritten on RETRY loops

### Auto-Compression

Each section has a word budget. When a section exceeds its budget, NERVES (the compression role, temperature 0.1) auto-compresses the content — preserving structure but summarizing verbose details. §4 is the most likely trigger since it accumulates tool results across iterations.

### Turn Summary Appendix

After Phase 8 completes, it appends a **Turn Summary Appendix** to the end of `context.md`. Phase 1 reads this appendix in the next turn to populate `turn_summaries` in its prompt. The appendix is append-only and should not be modified during the active pipeline run.

---

## 3. Context Discipline

**Pass the original query to every LLM that makes decisions.**

The user's raw words contain priorities ("cheapest", "best", "fastest") that inform every downstream decision. Search queries get sanitized for search engines — "cheapest" removed because Google handles it poorly — but LLMs making decisions must see the original.

Don't pre-classify user priorities. "Transactional" doesn't mean "price-focused" — it just means the user wants to buy. The LLM reads "cheapest" directly from §0.

When an LLM makes a bad decision, the fix is always better context, not programmatic workarounds.

---

## 4. Research Documents

Research documents contain the full results from tool calls — complete vendor information, product listings, source URLs, and confidence scores. `context.md` §2 contains summaries; research documents contain the detail.

### Evergreen vs Time-Sensitive

Research splits into two categories:

| Category | Examples | Behavior |
|----------|----------|----------|
| **Evergreen** | Vendor legitimacy, product specs, general facts | Decays slowly, high reuse value |
| **Time-sensitive** | Prices, availability, stock status | Decays quickly, needs refresh for accuracy |

This split enables the Planner to decide: "I have fresh evergreen knowledge but stale prices — only refresh the time-sensitive data."

### Research Lifecycle

Research documents progress through stages:

1. **Created** — Generated from tool results, indexed for future retrieval
2. **Active** — Retrieved and used by Context Gatherer for similar queries
3. **Stale** — Quality decayed below threshold, triggers selective refresh
4. **Expired** — Archived, no longer included in context

New research supersedes old research on the same topic. The system doesn't update documents — it creates new ones.

---

## 5. Webpage Cache

When the system visits a web page, it captures everything about that visit. This enables answering follow-up questions from cached data without re-navigating.

A webpage cache captures:
- **Manifest** — What was captured, content summary, answerable questions
- **Page content** — Full text of the page
- **Extracted data** — Structured data pulled from the page (prices, specs, comments)

### Cache-First Retrieval

The Context Gatherer checks cached data before routing to tools:

| Priority | Source | When |
|----------|--------|------|
| 1 | Manifest summary | Simple facts (page count, comment count) |
| 2 | Extracted data | Structured data (prices, specs) |
| 3 | Page content | Full text search needed |
| 4 | Navigate to URL | Fresh data needed (stock, availability) |
| 5 | Search | No prior visit, new content |

### When to Navigate vs Use Cache

Static facts (page count, thread title, author) → use cache. Volatile data (price, stock, new comments) → navigate fresh. The content type decay rates from the Confidence System determine when cached data is too stale.

---

## 6. Document Linking

Documents reference each other using relative markdown links for provenance:

| Link Type | From → To | Purpose |
|-----------|-----------|---------|
| Research link | context.md §2 → research.md | Full research details |
| History link | context.md §2 → prior context.md | Prior turn details |
| Memory link | context.md §2 → memory | User facts and preferences |
| Provenance link | research.md → source URLs | Original data source |
| Backlink | research.md → context.md | Where research was used |

### Link-Following

The Context Gatherer follows links internally during its 2-phase process:
1. **Retrieval phase** — Identifies relevant turns and decides which links to follow
2. **Synthesis phase** — Loads linked documents, extracts relevant sections, compiles §2

Link-following has depth and budget limits to prevent runaway retrieval. The system follows links up to 2 levels deep and stops when the token budget for linked content is consumed.

---

## 7. Memory Documents

User-specific memory is stored per-user. Global knowledge is shared.

- **Per-user** — Preferences (budget, location, favorites) and learned facts about the user
- **Global** — LLM-learned site patterns, source reliability data

Memory is searchable by the Context Gatherer and included in §2 when relevant.

---

## 8. Multi-Goal Queries

When a user query contains multiple distinct goals, the document structure supports parallel tracking:

- §3 lists all goals with IDs, statuses, and dependencies
- §4 attributes tool execution results to specific goals
- §6 validates each goal independently with per-goal quality scores

The overall quality score is the aggregate of per-goal scores.

---

## 9. Error Recovery

The append-only structure supports error recovery loops:

- **REVISE** — Validation writes its hints, Synthesis rewrites §5 with attempt number
- **RETRY** — Validation writes suggested fixes, pipeline replays from §3 onward with attempt number

Each attempt is labeled, preserving the history of what was tried and why.

---

## 10. Related Documents

- Phase specs: `architecture/main-system-patterns/phase1-query-analyzer.md` through `phase8-save.md`
- Confidence system: `architecture/concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md`
- Obsidian integration: `architecture/references/obsidian-integration/OBSIDIAN_INTEGRATION.md`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 2.0 | 2026-01-05 | Consolidated sections, removed duplicate routing docs |
| 3.0 | 2026-02-03 | Distilled to pure concept. Removed JSON schemas, Python code, token budgets, model assignment table, directory trees, and worked examples. Moved Obsidian integration to references. |
| 3.1 | 2026-02-04 | Updated section layout for Phase 1/1.5, removed action_needed, and added Turn Summary Appendix. |
| 3.2 | 2026-02-04 | Removed Phase 1.2 reference after normalization moved into Phase 1. |
| 3.3 | 2026-02-04 | Added Phase 2.1/2.2 sub-phase note for context gathering. |
| 3.4 | 2026-02-04 | Clarified §2 is written by Phase 2.2 (Context Synthesis). |

---

**Last Updated:** 2026-02-04
