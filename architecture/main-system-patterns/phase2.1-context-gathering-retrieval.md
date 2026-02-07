# Phase 2.1: Context Gathering — Search-First Retrieval

**Status:** SPECIFICATION
**Version:** 2.0
**Created:** 2026-02-04
**Updated:** 2026-02-06
**Question:** "What context is relevant to this query?"

**Related Concepts:** See §9 (Concept Alignment)

---

## 1. Overview

Phase 2.1 is the **retrieval sub-phase** of Context Gathering. It finds relevant prior turns, memory documents, cached research, and preferences — without showing the full memory vault to an LLM.

**Core principle: Search first, then synthesize.** The LLM generates search terms (like typing in Obsidian); code searches the memory vault; results go to Phase 2.2 for synthesis. The LLM never sees the full index.

**Core output:** `SearchResults` — a ranked list of memory documents with relevance scores.

**Precondition:** Phase 1.5 already passed.

### 1.1 Why Search-First (Problem Statement)

The v1.x retrieval approach showed the LLM the entire Unified Memory Index (~50-200+ nodes) and asked it to "select relevant ones." This failed because:

| Problem | Evidence |
|---------|----------|
| **Inclusion bias** | LLM shown large candidate lists rationalizes including everything rather than filtering |
| **Hallucinated relevance** | Turn 236: LLM marked hamster preferences as "high relevance" to a query about Russian troll farms |
| **Copy-paste justification** | All 16 turns marked "Relevance: high" with empty "Usable Info" fields |
| **Wasted tokens** | Full index = ~2000 tokens consumed just to list candidates, before any reasoning happens |

**The fix:** Don't show the index at all. Let the LLM generate search terms (its strength), and let code do the filtering (its strength).

### 1.2 URL Enrichment (Moved from Query Analyzer)

Context Gatherer handles **all context lookups**, including:
- Finding URLs for content references ("that thread" -> actual URL)
- Looking up prior turns' `research.json` for `extracted_links`
- Checking visit records for cached page data

URL lookup is **context retrieval**, not query analysis.

---

## 2. Position in Pipeline

```
Phase 1 (Query Analyzer) --> Phase 1.5 (Validator)
                              |
                              v
                         Phase 2.1 (Search-First Retrieval)
                              |
                              |  Step 1: LLM generates search terms
                              |  Step 2: Code searches memory vault
                              |  Step 3: Deduplicate + rank results
                              |
                              v
                         Phase 2.2 (Synthesis)
                              |
                              v
                         Phase 2.5 (Validation)
                              |
                              v
                            Phase 3
```

---

## 3. Architecture: Two-Step Retrieval

### Step 1: Search Term Generation (LLM)

**Role:** REFLEX (temp=0.4)
**Max tokens:** 200
**Purpose:** Convert the resolved query into 3-5 search phrases that would surface relevant documents if typed into a search box.

**Inputs:**

| Input | Source | Description |
|-------|--------|-------------|
| `resolved_query` | Phase 1 | The query after pronoun/reference resolution |
| `user_purpose` | Phase 1 | What the user is trying to accomplish |
| `reasoning` | Phase 1 | QA reasoning about query intent |

**Output:**

```json
{
  "search_terms": [
    "exact phrase or keyword combination",
    "related concept or entity",
    "alternate phrasing or synonym"
  ],
  "include_preferences": true,
  "include_n_minus_1": true
}
```

**Rules:**
- Generate 3-5 search phrases. Each should be a distinct angle on the query.
- Think like someone typing into a search box — use the words that would appear in relevant documents.
- `include_preferences` — true if the query might benefit from user preference context (e.g., shopping, recommendations). False for general knowledge queries.
- `include_n_minus_1` — true if the query is a follow-up (was_resolved=true) or could reference recent conversation. False if clearly a new, self-contained topic.

**Example — "find syrian hamsters for sale online":**
```json
{
  "search_terms": [
    "syrian hamster",
    "hamster for sale",
    "pet purchase online",
    "hamster breeder"
  ],
  "include_preferences": true,
  "include_n_minus_1": true
}
```

**Example — "tell me what you know about russian troll farms":**
```json
{
  "search_terms": [
    "russian troll farm",
    "internet research agency",
    "online propaganda russia",
    "social media manipulation"
  ],
  "include_preferences": false,
  "include_n_minus_1": false
}
```

### Step 2: Hybrid Search (Code — No LLM)

Code searches the memory vault using **two complementary methods** run in parallel, then fuses results:

#### 2a. Keyword Search (BM25)

Uses `rank_bm25.BM25Okapi` against the document corpus.

**Searched locations (per-user via `UserPathResolver`):**

| Location | What's There | Search Target |
|----------|-------------|---------------|
| `Users/{user_id}/turns/turn_NNNNNN/` | Prior turn context docs | `context.md` content + `metadata.json` keywords/topic |
| `Users/{user_id}/Knowledge/` | Research, products, facts, concepts | `.md` file content |
| `Users/{user_id}/sessions/{session}/preferences.md` | User preferences | File content |
| `Users/{user_id}/Beliefs/` | User beliefs | `.md` file content |

**Process:**
1. Tokenize each document (lowercase, split on whitespace)
2. Build BM25 index over all documents
3. For each search term, score all documents
4. Normalize scores to 0.0-1.0 (min-max scaling)

#### 2b. Semantic Search (Embeddings)

Uses `EmbeddingService` (all-MiniLM-L6-v2, 384 dims) + cosine similarity.

**Process:**
1. Embed each search term using `EmbeddingService.embed()`
2. Compare against pre-computed document embeddings (or compute on-the-fly for small vaults)
3. Cosine similarity score per document per search term
4. Minimum threshold: 0.40 (below this = no semantic match)

#### 2c. Score Fusion (Reciprocal Rank Fusion)

Combine BM25 and embedding results using **Reciprocal Rank Fusion (RRF)** rather than weighted averaging. RRF is rank-based, so it avoids the score normalization problems of raw BM25 scores.

```
RRF_score(doc) = sum over all search_terms:
    1/(k + rank_bm25(doc, term)) + 1/(k + rank_embedding(doc, term))
```

Where `k = 60` (standard RRF constant).

**Why RRF over weighted average:**
- BM25 scores are unbounded and corpus-dependent — normalization is fragile
- RRF uses only rank positions, making it robust across different scoring distributions
- A document that ranks top-5 in both BM25 and embedding consistently surfaces, even if raw scores differ wildly

#### 2d. Always-Include Rules

Regardless of search scores, always include:
- **Preferences** — if `include_preferences=true` from Step 1
- **N-1 turn** — if `include_n_minus_1=true` from Step 1
- **Explicitly referenced turns** — if QA `reference_resolution` resolved to a specific turn

These are appended with a flag `source: "always_include"` so synthesis knows they were not search-matched.

### Step 3: Deduplicate and Rank

1. Union all results across search terms
2. Deduplicate by document path (keep highest score)
3. Sort by RRF score descending
4. Return top-K results (K=15 default, configurable)

---

## 4. Output Schema (SearchResults)

```json
{
  "search_terms_used": ["string", "..."],
  "results": [
    {
      "document_path": "string",
      "source_type": "turn_summary | preference | fact | research_cache | visit_record",
      "node_id": "string",
      "rrf_score": 0.0,
      "bm25_rank": 0,
      "embedding_rank": 0,
      "snippet": "string (first 200 chars of matching content)",
      "source": "search | always_include"
    }
  ],
  "stats": {
    "total_documents_searched": 0,
    "bm25_matches": 0,
    "embedding_matches": 0,
    "final_results": 0
  }
}
```

### 4.1 Schema Rules

1. **Results are ranked.** Highest RRF score first.
2. **Empty results are valid.** New topic with no prior context = empty results array. This is not an error.
3. **`node_id` required.** Every result must have a stable node_id for provenance tracking in Phase 2.2.
4. **`snippet` required.** Short preview of why this document matched. Used by Phase 2.2 to decide what to load fully.
5. **`source` field distinguishes** search-matched results from always-include rules.

---

## 5. Existing Infrastructure (Already Built)

Phase 2.1 reuses existing codebase components — no new dependencies required:

| Component | Location | Role in Phase 2.1 |
|-----------|----------|-------------------|
| `EmbeddingService` | `apps/services/tool_server/shared_state/embedding_service.py` | all-MiniLM-L6-v2 embeddings (384 dims, CPU, ~20-50ms/text) |
| `HybridRetrieval` | `apps/services/tool_server/shared_state/hybrid_retrieval.py` | BM25 + cosine hybrid scoring with domain filtering |
| `TurnSearchIndex` | `libs/gateway/persistence/turn_search_index.py` | Session-scoped turn search with keyword + recency + quality weighting |
| `TurnIndexDB` | `libs/gateway/persistence/turn_index_db.py` | SQLite index for O(1) session-scoped turn lookup |
| `UserPathResolver` | `libs/gateway/persistence/user_paths.py` | Per-user directory resolution |
| `download_embedding_model.py` | `scripts/download_embedding_model.py` | Model already downloaded locally |

### 5.1 What Needs Extension

| Component | Change Needed |
|-----------|--------------|
| `TurnSearchIndex` | Add `search_knowledge()` and `search_all()` methods to search beyond turns (Knowledge/, Beliefs/, etc.) |
| `HybridRetrieval` | Add `search_documents()` method that accepts file paths instead of pre-built candidate dicts |
| `EmbeddingService` | Add optional document embedding cache (`.npy` sidecar files) for frequently searched docs |

### 5.2 Performance Budget

| Operation | Expected Latency | Notes |
|-----------|-----------------|-------|
| Step 1: Search term generation (LLM) | 500-1500ms | Single LLM call, REFLEX role, 200 max tokens |
| Step 2a: BM25 search (code) | 10-50ms | In-memory, ~200 docs |
| Step 2b: Embedding search (code) | 50-200ms | CPU embedding + cosine, ~200 docs |
| Step 2c: Score fusion (code) | <5ms | Simple rank arithmetic |
| **Total Phase 2.1** | **~600-1800ms** | Down from ~20,000ms (v1.x LLM retrieval call) |

---

## 6. Error Handling

| Condition | Action |
|-----------|--------|
| LLM fails to generate search terms | Fallback: extract keywords from `resolved_query` using `_extract_keywords()` |
| Embedding service unavailable | Degrade to BM25-only search (keyword matching) |
| No documents found by any search term | Valid outcome (new topic). Return empty results. Proceed to Phase 2.2 with minimal scaffold. |
| Document path in results doesn't exist on disk | Skip it, log warning. Do not HALT. |
| Search term generation returns >10 terms | Truncate to first 5. Log warning. |

---

## 7. Observability

Track:
- Search terms generated per query (count and content)
- BM25 match rate vs embedding match rate
- RRF score distribution (are results well-separated or clustered?)
- Always-include usage frequency
- Phase 2.1 total latency (should be <2s consistently)
- False negative rate: queries where Phase 2.2 says "missing context" that existed in vault but wasn't found

---

## 8. Related Documents

- `architecture/main-system-patterns/phase2.2-context-gathering-synthesis.md` — Downstream synthesis
- `architecture/main-system-patterns/phase2.5-context-gathering-validator.md` — Validation helper
- `architecture/concepts/memory_system/MEMORY_ARCHITECTURE.md` — Memory and turn index rules

---

## 9. Concept Alignment

| Concept | Document | Alignment |
|---------|----------|-----------|
| **Recipe System** | `concepts/recipe_system/RECIPE_SYSTEM.md` | Step 1 (search term generation) uses a recipe. Step 2 (search) is procedural code. |
| **Document IO** | `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | Uses turn summaries and memory docs as search corpus. |
| **Error Handling** | `concepts/error_and_improvement_system/ERROR_HANDLING.md` | Graceful degradation (embedding fallback to BM25-only). Empty results are not errors. |
| **LLM Context Discipline** | `CLAUDE.md` | LLM generates search terms (its strength). Code does filtering (its strength). No hardcoded relevance decisions. |

---

## 10. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-04 | Initial Phase 2.1 retrieval specification |
| 1.1 | 2026-02-04 | Clarified Phase 1.5 pass as a hard precondition. |
| 1.2 | 2026-02-04 | Prioritized narrative inputs and made structured hints optional. |
| 1.3 | 2026-02-04 | Unified all retrieval inputs into a single memory graph index. |
| 1.4 | 2026-02-04 | Replaced example output with universal RetrievalPlan schema + rules. |
| 1.5 | 2026-02-05 | Minor edits for consistency. |
| **2.0** | **2026-02-06** | **BREAKING: Replaced LLM-based retrieval with Search-First architecture.** Removed Unified Memory Index LLM selection. Added Step 1 (LLM search term generation) + Step 2 (BM25 + embedding hybrid search). Added RRF score fusion. Added always-include rules. Documented existing infrastructure reuse. Added performance budget. |

---

**Last Updated:** 2026-02-06
