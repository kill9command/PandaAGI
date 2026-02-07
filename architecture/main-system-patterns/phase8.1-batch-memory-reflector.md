# Phase 8.1: Batch Memory Reflector

**Status:** SPECIFICATION
**Version:** 1.0
**Created:** 2026-02-06
**Layer:** Background (async, post-response)

**Related Concepts:** See §8 (Concept Alignment)

---

## 1. Overview

**Question:** "What patterns emerge across recent turns that deserve permanent memory?"

Phase 8.1 is a background batch process that periodically reviews recent conversation history and extracts differential knowledge — what's NEW, what's CORRECTED, what's CONNECTED, what's UNRESOLVED. One LLM call per batch (typically 10 turns) instead of per-turn extraction.

| Aspect | Specification |
|--------|---------------|
| **Input** | Last N turns' context.md + response.md (batched) |
| **Output** | Staged knowledge files in Knowledge_staging/ |
| **LLM Required** | Yes — MIND role, temp 0.6 |
| **Timing** | Background task triggered by signal accumulator |
| **Trigger** | Every 10 turns OR urgency score > 5.0 |

### Why Batch Over Per-Turn?

Per-turn extraction is myopic — it sees one tree, never the forest. Batch reflection enables:

- **Pattern recognition** across turns (topic clusters, evolving interests)
- **Contradiction detection** (correction in turn N vs claim in turn N-5)
- **Connection discovery** (links between topics discussed in separate turns)
- **Noise filtering** (transient questions vs genuine knowledge)

---

## 2. Trigger System (Signal Accumulator)

Two trigger conditions, whichever comes first:

| Trigger | Threshold | Reset |
|---------|-----------|-------|
| Turn count | 10 turns since last batch | After batch completes |
| Signal urgency | Accumulated score > 5.0 | After batch completes |

### Signal Weights

All signal detection is code-based (no LLM):

| Signal | Weight | Detection Method |
|--------|--------|------------------|
| Same topic repeated (3+ in window) | +1.0 | Word overlap with `recent_topics` |
| User correction ("actually", "no", "I meant") | +2.0 | Regex on query text |
| High-confidence research (APPROVE + quality >= 0.85) | +1.5 | Check validation_result + metadata |
| Knowledge boundary (planner routed to refresh/clarify) | +1.0 | Check §3 route |
| Contradiction detected (freshness analyzer fired) | +2.5 | Check for prior_findings.md in turn_dir |

### Signal State

Per-user state stored in `Users/{user_id}/Logs/reflector/signal_state.json`:

```json
{
  "turns_since_last_batch": 7,
  "urgency_score": 3.5,
  "last_batch_turn": 230,
  "last_batch_timestamp": 1770400000.0,
  "recent_topics": ["troll farms", "reef tanks", "troll farms"]
}
```

### Future: Session Close Hook

`trigger_session_close_reflection(user_id, session_id)` — designed but not wired. Will be connected to an idle timer in future.

---

## 3. Batch Data Assembly

Assembly is all code, no LLM:

1. Query TurnIndexDB for turns since `last_batch_turn` (capped at 10)
2. For each turn: read `context.md` (§0 query, §2 context, §3 plan, §6 response) + `response.md`
3. Compile into single batch document (~4000 tokens, truncate oldest first)
4. BM25 search existing `Knowledge/` with batch's top keywords → include summaries so LLM knows what already exists

---

## 4. LLM Reflector Call

| Aspect | Value |
|--------|-------|
| Recipe | `pipeline/phase8_1_batch_reflector` |
| Role | MIND |
| Temperature | 0.6 |
| Max output tokens | 1500 |
| Calls per batch | 1 |

### Output Schema

```json
{
  "new_facts": [{
    "title": "slug_friendly_title",
    "content": "the fact, 2-5 sentences",
    "source_turns": [238, 240],
    "related_existing": ["Facts/file_a.md", "Concepts/file_b.md"],
    "category": "Facts | Concepts | Patterns"
  }],
  "corrections": [{
    "existing_file": "Facts/some_fact.md",
    "what_changed": "description of correction",
    "source_turns": [241],
    "new_confidence_hint": "higher | lower | same"
  }],
  "connections": [{
    "file_a": "Facts/file_a.md",
    "file_b": "Concepts/file_b.md",
    "relationship": "how they connect",
    "source_turns": [238, 240]
  }],
  "open_questions": [{
    "question": "the unresolved question",
    "source_turns": [239],
    "why_unresolved": "explanation"
  }]
}
```

### Hard Caps (Code-Enforced)

| Category | Max Items |
|----------|-----------|
| new_facts | 2 |
| corrections | 1 |
| connections | 2 |
| open_questions | 2 |

Excess items are truncated after LLM returns.

---

## 5. Quality Gates

All gates are code-enforced, no LLM:

| Gate | Check | On Fail |
|------|-------|---------|
| Turn existence | Every `source_turns` entry exists in TurnIndexDB | Remove item |
| Keyword match | At least 1 keyword from fact appears in cited turn's context.md | Remove item |
| Related file exists | Every `related_existing` path exists on disk | Remove item |
| BM25 dedup | Search fact content against Knowledge/ — reject if score > 0.8 | Remove (already known) |
| Drift guard | Correction targets fact with confidence > 0.9, backed by only 1 turn | Remove correction |

### Confidence Assignment (Code, Not LLM)

| Source Turns | Base Confidence |
|-------------|-----------------|
| 1 turn | 0.60 |
| 2 turns | 0.75 |
| 3+ turns | 0.75 (or 0.85 if any turn had APPROVE + quality >= 0.80) |

---

## 6. Staging Area

| Aspect | Value |
|--------|-------|
| Path | `Users/{user_id}/Knowledge_staging/` |
| Visibility | NOT searched by MemoryVaultSearcher |
| Frontmatter | `staged_at`, `batch_id`, `promotion_count`, `source_turns`, `confidence` |

The staging area is invisible to the pipeline. MemoryVaultSearcher only scans `resolver.knowledge_dir` which points to `Knowledge/`.

### Promotion Lifecycle

```
Staged (Knowledge_staging/)
    |
    ├── appears in 2+ separate batches (BM25 > 0.7) → Auto-promote to Knowledge/
    |
    ├── /review-memories command → Manual promote/discard (future)
    |
    └── 30 days + promotion_count < 2 → Auto-expire (delete)
```

Auto-promote logic runs in `_check_promotions()` after every batch:
- For each staged file, BM25-compare against new batch's outputs
- If similarity > 0.7: increment `promotion_count` in frontmatter
- If `promotion_count >= 2`: move to `Knowledge/` via `write_memory()`, delete staging file

---

## 7. Observability

Every batch writes `Users/{user_id}/Logs/reflector/batch_{NNN}.json`:

```json
{
  "batch_id": 42,
  "timestamp": "2026-02-06T14:30:00Z",
  "turns_reviewed": [238, 239, 240, 241, 242],
  "trigger": "turn_count",
  "urgency_score": 3.5,
  "quality_gate_results": {
    "items_proposed": 7,
    "items_passed": 4,
    "rejections": [{"item": "...", "gate": "dedup", "reason": "similar to Facts/X.md"}]
  },
  "staged_files": ["Knowledge_staging/Facts/new_fact.md"],
  "promoted_files": ["Knowledge/Facts/promoted_fact.md"],
  "duration_ms": 2400
}
```

---

## 8. Concept Alignment

| Concept | Relevance |
|---------|-----------|
| **Memory Architecture** | Extends Phase 8 per `MEMORY_ARCHITECTURE.md` which specifies "Memory candidates are only committed to the memory store after Validation returns APPROVE." The staging area implements this gate at batch level. |
| **Document IO** | Reads context.md and response.md from turn directories. Writes staged knowledge files with YAML frontmatter. |
| **Confidence System** | Assigns confidence based on source turn count, not LLM judgment. Higher-confidence existing facts resist single-turn corrections (drift guard). |

---

## 9. Error Handling

| Failure | Action |
|---------|--------|
| LLM call fails (timeout, 503) | Wait 30s, retry once. If still fails: log + abort batch. |
| JSON parse failure | Log raw response + abort batch. |
| File read failure | Log per-file, continue with remaining turns. |
| Quality gate rejects all items | Log empty batch, still reset counters. |
| Signal state file corrupt | Reset to defaults, log warning. |

The entire `run_batch()` is wrapped in try/except. Reflector failures never affect the main pipeline.

---

## 10. Data Flow

```
save_turn()
  |
  v
update_signals()          ← code only, ~1ms
  |  reads signal_state.json, increments counters
  |  detects: topic repetition, corrections, research quality, boundaries, contradictions
  |
  ├── should_trigger = False → return (99% of turns)
  |
  └── should_trigger = True →
          |
          v
      asyncio.create_task(BatchReflector.run_batch())    ← background
          |
          v
      [await asyncio.sleep(5)]                            ← yield GPU
          |
          v
      _assemble_batch_input()     ← read last N turns from disk (~50ms)
          |
          v
      _get_existing_knowledge()   ← BM25 search Knowledge/ (~100ms)
          |
          v
      _call_llm()                 ← MIND, temp 0.6, 1500 tokens (~2-5s)
          |
          v
      _apply_quality_gates()      ← code verification (~50ms)
          |
          v
      _write_to_staging()         ← write Knowledge_staging/ files (~10ms)
          |
          v
      _check_promotions()         ← BM25 compare staged vs new, promote/expire (~100ms)
          |
          v
      _write_batch_log()          ← observability JSON (~5ms)
          |
          v
      reset_after_batch()         ← zero counters
```

---

## 11. Implementation Files

| File | Action | Purpose |
|------|--------|---------|
| `libs/gateway/persistence/reflector_signal.py` | CREATE | Signal accumulator (trigger detection) |
| `apps/prompts/pipeline/phase8_1_batch_reflector.md` | CREATE | LLM prompt for batch reflection |
| `apps/recipes/recipes/pipeline/phase8_1_batch_reflector.yaml` | CREATE | Recipe configuration |
| `libs/gateway/persistence/batch_reflector.py` | CREATE | Core batch reflection logic |
| `libs/gateway/persistence/turn_saver.py` | MODIFY | Wire signal accumulator into save_turn() |

---

## 12. Related Documents

- `architecture/main-system-patterns/phase8-save.md` — Parent phase
- `architecture/concepts/memory_system/MEMORY_ARCHITECTURE.md` — Memory validation gate
- `architecture/main-system-patterns/phase2.1-context-gathering-retrieval.md` — How knowledge is retrieved
- `architecture/concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` — Quality scores

---

## 13. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-06 | Initial specification |

---

**Last Updated:** 2026-02-06
