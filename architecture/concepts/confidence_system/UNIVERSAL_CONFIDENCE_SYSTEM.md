# Universal Confidence System

**Version:** 2.0
**Updated:** 2026-02-03

---

## 1. Core Principle

**Quality IS Confidence. They are the same thing.**

One number (0.0–1.0) represents how good and reliable something is. High quality = high confidence = trustworthy data. Low quality = low confidence = stale or unreliable data.

One canonical score for external use. The system may internally track sub-components (completeness, source quality, extraction success) for calculation, but exposes ONE `overall_quality` score — the confidence score with decay applied.

---

## 2. Universal Thresholds

These thresholds apply everywhere in the system:

| Score | Level | Validation | Cache | Synthesis |
|-------|-------|------------|-------|-----------|
| **>= 0.80** | HIGH | APPROVE | Use fully | State as fact |
| **0.50–0.79** | MEDIUM | REVISE | Use with note | Hedge language |
| **0.30–0.49** | LOW | RETRY | Prefer fresh | Explicit caveat |
| **< 0.30** | EXPIRED | FAIL | Don't use | Don't include |

Same score, same thresholds, everywhere. No special cases.

---

## 3. Which Phases Use Quality

| Phase | Role | How Quality Is Used |
|-------|------|---------------------|
| Phase 2 | MIND | Context Gatherer filters by quality threshold (>= 0.30 for inclusion) |
| Phase 3 | MIND | Planner decides if cached data is sufficient (>= 0.70 can skip research) |
| Phase 6 | VOICE | Synthesis uses quality for language — high confidence states facts, low confidence hedges |
| Phase 7 | MIND | Validation uses thresholds for APPROVE / REVISE / RETRY / FAIL decisions |
| Phase 8 | None | Save stores quality_score in metadata for future retrieval |

---

## 4. Confidence Metadata

Every data unit in the system carries confidence metadata:

| Field | Type | Description |
|-------|------|-------------|
| `initial` | float | Starting confidence (0.0–1.0) |
| `current` | float | Decayed confidence (calculated) |
| `content_type` | string | Determines decay rate |
| `created_at` | datetime | When data was created |
| `source_type` | string | How data was obtained (llm, ocr, dom, user, cache, aggregated) |
| `agreement_count` | int | How many sources agree (default: 1) |
| `conflict_detected` | bool | Whether sources disagreed (default: false) |

---

## 5. Source Quality Scoring

Source selection and ranking use a single quality score (0.0–1.0) that blends:

- **LLM source-type classification** — the LLM assesses source quality based on type (forum, expert review, official, vendor) and the user's query context
- **Reliability history** — past accuracy of the source, tracked over time
- **Confidence decay** — age-based degradation per content type

When reliability history is insufficient, the system relies on the LLM assessment alone. As history accumulates, reliability data carries increasing weight.

This replaces hardcoded domain lists with an evidence-based, calibrated score. The same universal thresholds from §2 apply.

---

## 6. Content-Type Decay

Different types of information decay at different rates:

| Content Type | Decay Rate | Floor | Half-Life | Category |
|--------------|------------|-------|-----------|----------|
| `availability` | 0.20/day | 0.10 | ~3.5 days | Fast (volatile) |
| `price` | 0.10/day | 0.20 | ~7 days | Fast (volatile) |
| `product_spec` | 0.03/day | 0.50 | ~23 days | Medium (semi-stable) |
| `vendor_info` | 0.02/day | 0.60 | ~35 days | Medium (semi-stable) |
| `strategy` | 0.02/day | 0.50 | ~35 days | Medium (semi-stable) |
| `site_pattern` | 0.01/day | 0.70 | ~70 days | Slow (stable) |
| `preference` | 0.005/day | 0.80 | ~140 days | Slow (stable) |
| `general_fact` | 0.005/day | 0.80 | ~140 days | Slow (stable) |

**Default** (if content type not in table): decay rate 0.02/day, floor 0.30.

**Floor principle:** Facts about the world get higher floors (0.60+). Learned behaviors get lower floors (0.50) because they're context-dependent — a strategy that worked for one query type may not transfer.

---

## 7. Exponential Decay Formula

```
C(t) = floor + (C₀ - floor) × e^(-λt)

Where:
  C(t)   = confidence at time t
  C₀     = initial confidence
  floor  = minimum confidence for content type
  λ      = decay rate (per day)
  t      = age in days
```

**Example:** Price data, initial confidence 0.90:
- Day 0: 0.90
- Day 3: 0.72
- Day 7: 0.55
- Day 14: 0.38
- Day 30: 0.25 (approaching floor of 0.20)

---

## 8. Confidence Flow

Confidence flows through layers, accumulating and refining as data moves through the system:

1. **Extraction** — Raw data is extracted with an initial confidence from the extraction method (OCR, DOM parsing, API response, etc.)
2. **Cross-validation** — When multiple sources report the same data, agreement boosts confidence. Conflict flags the data for resolution using the higher-confidence source.
3. **Claim creation** — Extracted data becomes a claim with confidence, content type, and decay parameters attached.
4. **Document aggregation** — Multiple claims compose into a research document. Document quality is the weighted mean of its claim confidences.
5. **Context and learning** — Successful strategies and patterns are stored with their own confidence, decaying over time. Future similar queries benefit from high-confidence prior strategies.

At every layer, the same thresholds from §2 apply.

---

## 9. Calibration

The system learns whether its confidence estimates are accurate over time.

When a confidence prediction is later validated (user confirms data was correct, or downstream phase successfully uses it), the system records the outcome. Over time, it compares predicted confidence against actual accuracy. If a source consistently claims 85% confidence but is only correct 60% of the time, the calibrated score adjusts to 0.60.

Calibration requires a minimum sample count before it overrides raw confidence. This prevents early noise from distorting scores.

---

## 10. Trust Progression

Data gains trust through successful use:

| Level | Meaning | How It Gets There |
|-------|---------|-------------------|
| **New** | Just created, unproven | Default for all new data |
| **User-trusted** | Proven useful for this user | Repeated successful use, quality stays above threshold |
| **Global** | Universally useful | High usage across contexts, sustained high quality |

Trust level affects how aggressively the system caches and reuses data.

---

## 11. Related Documents

- Phase specs that consume quality: `phase2.2-context-gathering-synthesis.md`, `phase3-planner.md`, `phase6-synthesis.md`, `phase7-validation.md`, `phase8-save.md`
- Research foundation: `architecture/references/confidence-research/CONFIDENCE_RESEARCH.md`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 1.1 | 2026-01-05 | Removed implementation code, consolidated duplicate sections |
| 2.0 | 2026-02-03 | Distilled to pure concept. Moved research citations to references. Removed JSON schemas, storage paths, specific blend weights, and OCR/DOM worked example. Simplified confidence flow to conceptual layers. |

---

**Last Updated:** 2026-02-03
