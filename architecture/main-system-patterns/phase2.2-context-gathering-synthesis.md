# Phase 2.2: Context Gathering — Synthesis

**Status:** SPECIFICATION  
**Version:** 1.6
**Created:** 2026-02-04  
**Updated:** 2026-02-04  
**Layer:** MIND role (MIND model @ temp=0.6)  
**Question:** "What context should we compile for planning?"

**Related Concepts:** See §9 (Concept Alignment)

---

## 1. Overview

Phase 2.2 is the **synthesis sub-phase** of Context Gathering. It ingests the documents selected by Phase 2.1 and compiles a **draft** §2 Gathered Context section, which is committed to `context.md` only after Phase 2.5 returns `pass`.

**Core output:** §2 Gathered Context (markdown + optional `_meta` blocks) and Constraints section

---

## 2. Position in Pipeline

```
Phase 2.1 (Retrieval) ──► Document Loading ──► Phase 2.2 (Synthesis) ──► Phase 2.5 (Validation) ──► Phase 3
```

---

## 3. Inputs

| Input | Source | Description |
|-------|--------|-------------|
| QueryAnalysis (narrative) | Phase 1 | `resolved_query`, `user_purpose`, `reasoning` — primary signals for synthesis |
| QueryAnalysis (hints) | Phase 1 | Optional structured hints (e.g., `data_requirements`, `content_reference`) |
| Original query | User | Context discipline (grounding) |
| Loaded memory nodes | Procedural load | Full documents for selected memory graph nodes |

**Input Principle:** Phase 2.2 synthesizes from the **memory graph** selected in Phase 2.1. It should treat source type, confidence, and provenance as first-class signals when compiling §2.

### 3.1 Prompt File

**Prompt:** `apps/prompts/pipeline/phase1_context_gatherer.md` (shared with Phase 2.1; filename retained for compatibility). This prompt is the source of truth for LLM behavior during synthesis.

---

## 4. Output Schema (Hybrid: Markdown + `_meta`)

Phase 2.2 writes §2 as **human-readable markdown** with optional `_meta` blocks that bind each section to memory graph `node_id`s. This preserves readability while keeping provenance, confidence, and source linkage explicit for code consumers.

### 4.1 Section Pattern (Reusable)

```markdown
### Section Title

```yaml
_meta:
  source_type: turn_summary | preference | fact | research_cache | visit_record | user_query
  node_ids: ["node_id", "..."]
  confidence_avg: 0.0-1.0
  provenance: ["source_ref", "..."]
```

[Human-readable content derived from the selected nodes]
```

### 4.1.1 Section Standards

- **Canonical source types:** `turn_summary`, `preference`, `fact`, `research_cache`, `visit_record`, `user_query`
  - `user_query` is a **synthetic source type** — it has no backing memory node. It is used only for constraints derived directly from the raw query (see §4.3). Its `node_ids` is always `[]`.
- **Canonical section titles:** `Session Preferences`, `Relevant Prior Turns`, `Cached Research`, `Visit Data`, `Constraints`
- **One section per source_type:** do not mix source types within a section. If mixed, split into separate sections. (Exception: the `Constraints` section — see §4.2.)
- **`_meta` required when nodes are used:** If a section includes any memory nodes, it must include `_meta` with `node_ids`. `_meta` may be omitted only for empty or purely narrative sections.

### 4.2 Constraints Pattern

Constraints remain human-readable but are still tied to node_ids when possible.

**Exception to §4.1.1:** The Constraints section may aggregate constraints from **multiple source types** (e.g., `preference` + `user_query`). When this occurs, list all contributing source types and node_ids in the `_meta` block:

```markdown
### Constraints

```yaml
_meta:
  source_type: [preference, user_query]
  node_ids: ["memory:budget"]
  provenance: ["§0.raw_query", "memory:budget"]
```

- budget: max $800 (required)
- must_avoid: used, refurbished
```

### 4.3 Confidence and Provenance Rules

- **`confidence_avg` computation:**
  - **Weight source:** each memory node's `confidence` field (post-decay, as computed by the Universal Confidence System).
  - **Method:** weighted mean by node recency (newer nodes weighted higher). If recency metadata is unavailable, use simple average.
  - **Inclusion threshold:** Nodes with confidence < 0.30 (EXPIRED) must not be included in §2. This is enforced at synthesis time, not retrieval time.
  - **Missing confidence:** If a node lacks a confidence value, default to 0.50 (MEDIUM) and log a warning for observability.
- **Provenance is required** whenever `_meta` is present.
- **Query-derived constraints** use `_meta.source_type: user_query`, `node_ids: []`, and `provenance: ["§0.raw_query"]`.

---

## 5. §2 Output Format

Phase 2.2 produces a **draft §2** using the **dual-format** structure:
- Human-readable markdown (primary)
- Optional `_meta` YAML blocks for structured shortcuts

If `_meta` blocks are absent, the markdown must still contain the same information, but traceability is reduced. The orchestrator commits the draft to `context.md` only after Phase 2.5 passes.

### 5.2 Planner-Optimized §2 Template

Use this canonical layout to make §2 easy for Phase 3 to consume:

```markdown
## 2. Gathered Context

### Session Preferences
```yaml
_meta:
  source_type: preference
  node_ids: ["node_id", "..."]
  confidence_avg: 0.0-1.0
  provenance: ["source_ref", "..."]
```
- budget: $500–800 (high confidence)
- preferred_brands: Lenovo, ASUS (medium confidence)

### Relevant Prior Turns
```yaml
_meta:
  source_type: turn_summary
  node_ids: ["node_id", "..."]
  confidence_avg: 0.0-1.0
  provenance: ["source_ref", "..."]
```
- Turn 811: Compared RTX 4050 laptops under $1k; Lenovo LOQ at $697 was top pick
- Turn 809: User confirmed max budget $800

### Cached Research
```yaml
_meta:
  source_type: research_cache
  node_ids: ["node_id", "..."]
  confidence_avg: 0.0-1.0
  provenance: ["source_ref", "..."]
```
- 12 laptops found; 3 under $800 with RTX 4050
- Best current match: Lenovo LOQ 15 at $697 (bestbuy.com)

### Visit Data
```yaml
_meta:
  source_type: visit_record
  node_ids: ["node_id", "..."]
  confidence_avg: 0.0-1.0
  provenance: ["source_ref", "..."]
```
- BestBuy LOQ 15: $697, In Stock (1.2h ago)

### Constraints
```yaml
_meta:
  source_type: user_query
  node_ids: []
  provenance: ["§0.raw_query"]
```
- must_have: NVIDIA GPU
- budget: max $800
- must_avoid: used/refurbished
```

### 5.1 Token Budget

| Component | Budget |
|-----------|--------|
| §2 output (total) | ~5,000 tokens |
| Per prior-turn summary | 1,500 tokens max |

**Overflow handling:** Phase 2.2 does not manage token budgets directly. If §2 exceeds its allocation, the **NERVES role (temp=0.3)** auto-compresses per the Prompt Management System §5 compression hierarchy:

1. **Section overflow** → compress that section only
2. **Document overflow** → compress largest sections first
3. **Call overflow** → aggressive compression, drop low-relevance content

Phase 2.2 should prioritize **high-confidence, recent** content to minimize compression triggers.

---

## 6. Error Handling

- **Unparseable output** → retry once, then HALT with intervention
- **Missing required sections** → Phase 2.5 will return retry guidance
- **Empty output (no markdown produced)** → HALT, log full context, create intervention. No silent fallbacks.
- **Fabricated content (claims not traceable to loaded nodes)** → Caught by Phase 2.5 provenance check. If `_meta.node_ids` references non-existent nodes, Phase 2.5 returns `retry` with guidance.
- **Missing confidence on source nodes** → Default to 0.50 (MEDIUM), log warning. Do not HALT.
- **Model timeout** → HALT, log timeout details, create intervention.

### 6.1 Empty-State Behavior

If Phase 2.1 returns zero relevant nodes (e.g., new user, new topic), Phase 2.2 produces a **minimal §2 scaffold**:

```markdown
## §2 Gathered Context

### Constraints

_meta:
  source_type: user_query
  node_ids: []
  provenance: ["§0.raw_query"]

[Any constraints extractable from the raw query]
```

All other sections are **omitted** (not empty — absent). Phase 3 treats absent sections as "no prior context available" and routes to executor for research.

---

## 7. Observability

Track:
- Context quality scores
- Source coverage (turns, memory, research, visit data)
- Missing constraint frequency

---

## 8. Related Documents

- `architecture/main-system-patterns/phase2.1-context-gathering-retrieval.md` — Upstream retrieval
- `architecture/main-system-patterns/phase2.5-context-gathering-validator.md` — Validation helper
- `architecture/concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` — §2 output format

---

## 9. Concept Alignment

| Concept | Document | Alignment |
|---------|----------|-----------|
| **Document IO** | `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | Writes §2 Gathered Context with optional `_meta` blocks. |
| **Prompt Management** | `concepts/recipe_system/PROMPT_MANAGEMENT_SYSTEM.md` | Synthesis prompt uses original query + loaded documents to enforce context discipline. |
| **Confidence System** | `concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` | Carries quality and freshness data into §2 for Planner decisions. |

---

## 10. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-04 | Initial Phase 2.2 synthesis specification |
| 1.1 | 2026-02-04 | Aligned inputs with unified memory graph from Phase 2.1. |
| 1.2 | 2026-02-04 | Switched to hybrid markdown + `_meta` output tied to memory graph nodes. |
| 1.3 | 2026-02-04 | Added section standards and confidence/provenance rules. |
| 1.4 | 2026-02-04 | Added prompt reference, `user_query` source type, confidence computation details, token budget, expanded error handling, empty-state behavior, and Constraints mixed-type exemption. |
| 1.5 | 2026-02-04 | Clarified draft §2 output and commit after Phase 2.5 pass. |
| 1.6 | 2026-02-04 | Added planner-optimized §2 template. |

---

**Last Updated:** 2026-02-04
