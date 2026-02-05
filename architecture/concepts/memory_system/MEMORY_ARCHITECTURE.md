# Memory Architecture

**Version:** 2.0
**Updated:** 2026-02-03

---

## 1. Core Principle

**Everything is a document.** Every piece of information — research results, user preferences, past turn context, site knowledge — lives in a document with rich metadata. All documents share the same metadata model and are searchable through one unified interface.

---

## 2. Access Rules

The pipeline has clear boundaries for who accesses memory and when:

- **Phase 0 (Query Analyzer)** resolves references and classifies the query. Runs once, done.
- **Phase 1 (Reflection)** gates the query — PROCEED or CLARIFY. Runs once, done.
- **Phase 2 (Context Gatherer)** gathers ALL relevant context from ALL sources — turn history, past research, user preferences, cached intelligence. Writes §2. Runs once, done. Never runs again this turn.
- **Phase 3+ (Planner, Executor, Coordinator)** take over for the rest of the turn. The Planner reads §2 and orchestrates everything else — deciding what tools to call, whether to search for more, whether to save new memories.

**The Context Gatherer never runs twice.** After Phase 2, the Planner owns all further memory operations through the Coordinator's tool calls.

---

## 3. context.md IS the Lesson

Every completed turn produces a context.md with the full decision flow: what was asked (§0), what context was gathered (§2), what plan was made (§3), what tools executed (§4), what response was synthesized (§5), and whether it validated (§6).

**This file IS the lesson.** No separate lesson extraction. No special "LEARN" decision.

Phase 8 indexes every context.md. Future Context Gatherers search this index to find similar past turns and include them in §2. The Planner sees what worked before and makes better decisions.

Learning is automatic:
1. Turn completes → context.md saved → indexed
2. Similar query arrives → Context Gatherer finds it → includes in §2
3. Planner sees what worked before → makes better decisions

---

## 4. Document Metadata

Every document shares the same metadata model:

| Field | Purpose |
|-------|---------|
| `id` | Unique identifier |
| `primary_topic` | Hierarchical topic (e.g., `electronics.laptop`, `pet.hamster.syrian`) |
| `keywords` | Searchable keywords |
| `user_purpose` | Natural language purpose statement from Phase 1 |
| `data_requirements` | Data need flags from Phase 1 |
| `content_types` | What the document contains (vendor_info, preference, site_pattern, context, etc.) |
| `scope` | Trust level: new, user, or global |
| `quality` | Confidence score 0.0–1.0 |
| `created_at` | Timestamp |
| `expires_at` | Optional TTL |

**"Type" is just metadata.** A research document has `content_types: [vendor_info, pricing]`. A preference has `content_types: [preference]`. A past turn has `content_types: [context]`. They're all documents — the metadata distinguishes them, not separate storage systems.

---

## 5. Unified Search

One search interface covers all document types — research, turns, preferences, site knowledge. Searches accept natural language or keywords, with optional filters for topic, content type, scope, quality threshold, and freshness.

The system searches across all indexes and returns results ranked by relevance and quality. No separate search per document type.

---

## 6. Memory Tools

The Planner accesses memory through three tools:

| Tool | Purpose |
|------|---------|
| `memory.search` | Search all documents with filters (topic, content type, scope, quality, freshness) |
| `memory.save` | Save new documents (preferences, facts, site knowledge) |
| `memory.retrieve` | Get a specific document by ID or path |

These are the only memory operations. The Context Gatherer uses the same search infrastructure internally during Phase 2, but after that, only the Planner initiates memory operations.

---

## 7. Memory Staging

During planning, the Planner may identify items worth saving to memory — preferences, facts, workflow patterns. These are written to a **memory candidates** staging area, not directly to the memory store.

**The commit rule:** Memory candidates are only committed to the memory store after Validation returns APPROVE. On REVISE, RETRY, or FAIL, candidates are discarded.

This prevents polluting memory with items from failed or revised turns. Only knowledge from successful turns enters long-term storage.

**Guidelines for memory candidates:**
- Only stable, cross-turn knowledge (preferences, facts, patterns)
- Never transient data (prices, URLs, ephemeral task state)
- Session scope by default, global only when explicitly warranted

---

## 8. Per-User Storage

User preferences and facts are stored as markdown files in per-user directories. This provides natural isolation between users, human-readable data, and integration with the markdown-based document system.

Turn numbers are per-user. Each user's history is independent.

---

## 9. Source Reliability

The system tracks extraction outcomes by domain — which sites succeed, which block requests, what the extraction quality is. This is global knowledge (shared across users) because reliability is site-specific, not user-specific.

Aggregated reliability feeds into the source quality scoring blend described in the Confidence System. Sites with poor track records are deprioritized in future source selection.

---

## 10. Scope Promotion

Documents gain trust through successful use:

```
NEW ──────────► USER ──────────► GLOBAL
(just created)   (proven useful)   (universally useful)
```

| Scope | Description | Persistence |
|-------|-------------|-------------|
| **New** | Just created, unproven | TTL expiration |
| **User** | Proven useful for this user | Persists indefinitely |
| **Global** | Useful across all users | Highest trust level |

A document is "used" when it appears in §2 and contributes to a turn. Validation outcomes affect trust: APPROVE increases it, RETRY and FAIL decrease it, REVISE has no effect.

Demotion is also possible — if a global document's trust drops, it reverts to user scope. If a user document's trust drops further, it reverts to new scope.

See the Confidence System for trust calculation and threshold details.

---

## 11. No Session Lifecycle

The system is stateless per-turn with persistent document storage. There is no session start or end.

`session_id` is a **user identity**, not a temporary session. It namespaces user-specific data (preferences, research, turn history) and filters Context Gatherer searches.

Each turn is self-contained:
1. Turn arrives
2. Context Gatherer retrieves relevant history from persistent storage
3. Pipeline executes
4. Phase 8 saves everything
5. No in-memory state carried forward

The system is always "on" — no initialization needed, no cleanup needed. TTL and confidence decay handle staleness automatically. Scope promotion handles trust automatically.

---

## 12. Turn Archival

Turns have a retention lifecycle:

| Age | Status | Behavior |
|-----|--------|----------|
| 0–30 days | **Active** | Full context.md and research.md preserved and searchable |
| 30+ days | **Archived** | Summary retained in index, originals moved to cold storage |

Archived turns remain searchable by their summary metadata. Full originals are accessible but stored separately. This keeps the active index fast while preserving history.

---

## 13. Related Documents

- Confidence system: `architecture/concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md`
- Document IO: `architecture/concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md`
- Context Retrieval: `architecture/main-system-patterns/phase2.1-context-gathering-retrieval.md`
- Context Synthesis: `architecture/main-system-patterns/phase2.2-context-gathering-synthesis.md`
- Planner: `architecture/main-system-patterns/phase3-planner.md`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-28 | Initial specification |
| 1.1 | 2026-01-04 | Adapted for 9-phase pipeline with Phase 0 |
| 2.0 | 2026-02-03 | Distilled to pure concept. Removed Python code, SQL schemas, directory trees, worked examples, role assignment table, and phase-by-phase integration summary. Fixed stale `intent` references to `action_needed`. |
| 2.1 | 2026-02-04 | Replaced `action_needed` with `user_purpose` + `data_requirements` to match Phase 1 schema. |
| 2.1 | 2026-02-03 | Added Memory Staging (§7) from PLANNER_NOTEBOOKS.md. |

---

**Last Updated:** 2026-02-03
