# Universal Confidence System

**Status:** SPECIFICATION
**Version:** 1.1
**Updated:** 2026-01-05
**Architecture:** PandaAI v2
**Canonical Source:** This is THE authoritative document for confidence scores, quality thresholds, and decay rates. Other docs should reference this file rather than duplicating values.

---

## Overview

**Quality IS Confidence. They are the same thing.**

One number (0.0 - 1.0) that represents how good/reliable something is:
- High quality = high confidence = trustworthy data
- Low quality = low confidence = stale or unreliable data

**One canonical score for external use.** The system may internally track sub-components
(completeness, source_quality, extraction_success) for calculation, but exposes ONE
`overall_quality` score that IS the confidence score with decay applied.

---

## Which Phases Use Quality Scores

Quality scores are used throughout the pipeline:

| Phase | Model | How Quality Is Used |
|-------|-------|---------------------|
| Phase 2 | MIND | Context Gatherer filters by quality threshold (>= 0.30 for inclusion) |
| Phase 3 | MIND | Planner decides if cached data is good enough (>= 0.70 can skip research) |
| Phase 5 | VOICE | Synthesis uses quality for language (high = facts, low = hedge) |
| Phase 6 | MIND | Validation uses thresholds for APPROVE/REVISE/RETRY/FAIL decisions |
| Phase 7 | None | Save stores quality_score in metadata.json for future retrieval |

**See:** `architecture/LLM-ROLES/llm-roles-reference.md` for complete model assignments.

---

## Universal Thresholds

These thresholds apply **everywhere** in the system:

| Quality Score | Meaning | Actions |
|---------------|---------|---------|
| **>= 0.80** | HIGH | Validation: APPROVE | Cache: Use fully | Synthesis: State as fact |
| **0.50-0.79** | MEDIUM | Validation: REVISE | Cache: Use with note | Synthesis: Hedge language |
| **0.30-0.49** | LOW | Validation: RETRY | Cache: Prefer fresh | Synthesis: Explicit caveat |
| **< 0.30** | EXPIRED | Validation: FAIL | Cache: Don't use | Synthesis: Don't include |

---

## Research Foundation

This architecture is informed by academic research and industry best practices:

### Academic Research

| Paper | Key Contribution |
|-------|------------------|
| [Survey of Confidence Estimation and Calibration in LLMs (NAACL 2024)](https://aclanthology.org/2024.naacl-long.366.pdf) | ECE metric, temperature scaling, calibration methods |
| [Can LLMs Express Their Uncertainty? (ICLR 2024)](https://arxiv.org/pdf/2306.13063) | Verbalized confidence analysis, overconfidence patterns |
| [Uncertainty Quantification in LLMs (2025)](https://arxiv.org/abs/2503.15850) | Taxonomy of uncertainty sources |
| [Cache Freshness for Real-Time Applications](https://arxiv.org/html/2412.20221v1) | Bounded staleness, write-reactive policies |
| [Information Freshness in Cache Systems](https://user.eng.umd.edu/~ulukus/papers/journal/aoi-cache.pdf) | Age of Information (AoI) metric |
| [MISP Threat Intelligence Scoring](https://arxiv.org/pdf/1803.11052) | Decay functions for information relevance |

### Key Research Findings

**LLMs Are Systematically Overconfident:**
- Studies show LLMs are overconfident in 84.3% of scenarios ([Can LLMs Express Their Uncertainty?](https://arxiv.org/html/2306.13063))
- Verbalized confidence typically falls in 80-100% range, often in multiples of 5
- Even frontier models (Claude, GPT-4) show ECE of 0.12+ vs human experts at 0.03-0.05
- This means **raw LLM confidence scores need calibration**

**Industry Best Practices:**
- [Microsoft Document Intelligence](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept/accuracy-confidence): Target 80%+ for general use, near 100% for sensitive (financial/medical)
- [Mindee ML Confidence Guide](https://www.mindee.com/blog/how-use-confidence-scores-ml-models): 0.5 is natural binary threshold; use precision-recall curves to tune
- Production recommendation: Add human review stage for scores below threshold

**Calibration Methods:**
- Post-hoc calibration (isotonic regression, histogram binning) reduces ECE significantly
- Temperature scaling: `calibrated_score = softmax(logits / T)` where T > 1 reduces overconfidence
- Domain-specific validation is critical - calibration varies substantially by category

### Threshold Justification

Our thresholds align with research:

| Our Threshold | Research Basis |
|---------------|----------------|
| **>= 0.80 (HIGH)** | Industry standard for production systems; aligns with human expectations |
| **0.50-0.79 (MEDIUM)** | Above binary decision threshold (0.5); requires hedging |
| **0.30-0.49 (LOW)** | Below typical confidence but may contain useful signal |
| **< 0.30 (EXPIRED)** | Too low to trust; research shows performance degrades significantly |

**Important:** Because LLMs tend toward overconfidence, our 0.80 threshold is appropriately conservative. A raw LLM "85% confident" claim may actually be 60-70% accurate after calibration.

---

## Core Principles

### 1. Everything Gets Confidence

Every data unit in the system carries confidence metadata:

| Field | Type | Description |
|-------|------|-------------|
| **Core Confidence** | | |
| `initial` | float | Starting confidence (0.0 - 1.0) |
| `current` | float | Decayed confidence (calculated) |
| **Decay Parameters** | | |
| `content_type` | string | Determines decay rate |
| `created_at` | datetime | When data was created |
| `decay_rate` | float | Per-day decay rate |
| `floor` | float | Minimum confidence (never drops below) |
| **Calibration** | | |
| `validation_count` | int | How many times validated |
| `validation_success` | int | How many validations passed |
| `calibrated` | float? | Adjusted based on track record |
| **Provenance** | | |
| `source_type` | string | llm, ocr, dom, user, cache, aggregated |
| `source_id` | string | Specific source identifier |
| `source_quality` | float | Quality of original source |
| **Multi-Source** | | |
| `agreement_count` | int | How many sources agree (default: 1) |
| `conflict_detected` | bool | Sources disagreed (default: false) |

### 1.1 Source Quality Scoring (LLM-First)

Source selection and ranking use a single quality score (0.0-1.0) that blends:
- **LLM source-type classification** (forum, expert_review, official, vendor)
- **Reliability history** from `memory/source_reliability.db`
- **Confidence decay** based on content type
- **Query context** (goal, intent, original user query)

**Default Blend:**
- If reliability samples < min_samples: `quality = llm_quality_score`
- Else: `quality = 0.6 * llm_quality_score + 0.4 * reliability_score`

**Thresholds (same as universal):**
- **>= 0.80:** Accept and prioritize
- **0.50-0.79:** Accept with hedging / lower rank
- **0.30-0.49:** Deprioritize; prefer fresher sources
- **< 0.30:** Exclude from results

This replaces hardcoded domain lists with an evidence-based, calibrated score.

### 2. Content-Type Specific Decay

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

**Floor Rationale:**

| Type | Floor | Why |
|------|-------|-----|
| `vendor_info` | 0.60 | Vendor legitimacy rarely changes. Amazon, Best Buy, Newegg remain reliable retailers. Even stale vendor info is likely still valid. |
| `strategy` | 0.50 | Strategies are context-dependent. A search pattern that worked for "gaming laptops" may not work for "hamster cages". Strategies should decay further to avoid over-reliance on potentially outdated approaches. |

**Rule of thumb:**
- Facts about the world -> higher floor (0.60+)
- Learned behaviors -> lower floor (0.50)

### 3. Exponential Decay Formula

```
C(t) = floor + (C0 - floor) * e^(-lambda*t)

Where:
  C(t)   = confidence at time t
  C0     = initial confidence
  floor  = minimum confidence for content type
  lambda = decay rate (per day)
  t      = age in days
```

**Example:** Price with initial confidence 0.90, decay rate 0.10, floor 0.20:
- Day 0: 0.90
- Day 3: 0.72
- Day 7: 0.55
- Day 14: 0.38
- Day 30: 0.25 (approaching floor)

### 4. Calibration Through Feedback

The system learns whether its confidence estimates are accurate.

**Calibration Formula:**
```
calibrated_confidence = validation_success / validation_count
```

**Rules:**
- Minimum 5 validations required before calibration applies
- If a source claims 85% confidence but is only correct 60% of the time, calibrated = 0.60
- Calibration is stored per source_id in `observability/calibration.db`

**Expected Calibration Error (ECE):**
```
ECE = Sum (|accuracy_bin - confidence_bin| * bin_size) / total_samples
```

| Term | Description |
|------|-------------|
| Predictions | Grouped into confidence bins (0.0-0.1, 0.1-0.2, etc.) |
| Comparison | Average confidence vs. actual accuracy per bin |
| Perfect calibration | ECE = 0 |

---

## Confidence Flow

```
+--------------------------------------------------------------------+
|                    CONFIDENCE FLOW THROUGH SYSTEM                   |
+--------------------------------------------------------------------+
|                                                                     |
|  LAYER 1: EXTRACTION                                                |
|  +-------------------------------------------------------------+   |
|  | OCR Extraction                                               |   |
|  | +-- Text: "Price: $1,049.99"                                |   |
|  | +-- OCR Confidence: 0.92                                    |   |
|  | +-- Bounding Box: (x: 450, y: 320, w: 120, h: 24)          |   |
|  |                                                              |   |
|  | DOM Extraction                                               |   |
|  | +-- Text: "$1,049.99"                                       |   |
|  | +-- Selector: ".price-current"                              |   |
|  | +-- Selector Confidence: 0.85 (based on site knowledge)    |   |
|  +-------------------------------------------------------------+   |
|                          |                                          |
|                          v                                          |
|  LAYER 2: CROSS-VALIDATION                                         |
|  +-------------------------------------------------------------+   |
|  | OCR text matches DOM text?                                   |   |
|  | +-- YES -> Agreement boost: +0.05                            |   |
|  | +-- NO  -> Conflict detected, use higher-confidence source   |   |
|  |                                                              |   |
|  | Combined Confidence: max(0.92, 0.85) + 0.05 = 0.97          |   |
|  | (capped at 0.99)                                            |   |
|  +-------------------------------------------------------------+   |
|                          |                                          |
|                          v                                          |
|  LAYER 3: CLAIM CREATION                                           |
|  +-------------------------------------------------------------+   |
|  | Claim: "Acer Nitro V costs $1,049.99 at antonline.com"      |   |
|  | +-- Initial Confidence: 0.97                                |   |
|  | +-- Content Type: price                                     |   |
|  | +-- Decay Rate: 0.10/day                                    |   |
|  | +-- Floor: 0.20                                             |   |
|  | +-- Source: ocr+dom (validated)                             |   |
|  | +-- TTL: 6 hours                                            |   |
|  +-------------------------------------------------------------+   |
|                          |                                          |
|                          v                                          |
|  LAYER 4: DOCUMENT AGGREGATION                                     |
|  +-------------------------------------------------------------+   |
|  | Research Document (5 claims)                                 |   |
|  | +-- Claim 1: confidence 0.97                                |   |
|  | +-- Claim 2: confidence 0.85                                |   |
|  | +-- Claim 3: confidence 0.92                                |   |
|  | +-- Claim 4: confidence 0.78                                |   |
|  | +-- Claim 5: confidence 0.88                                |   |
|  |                                                              |   |
|  | Aggregate Confidence: weighted_mean = 0.88                   |   |
|  | Quality Score: 0.75 (completeness + source + extraction)    |   |
|  +-------------------------------------------------------------+   |
|                          |                                          |
|                          v                                          |
|  LAYER 5: CONTEXT/LESSON                                           |
|  +-------------------------------------------------------------+   |
|  | context.md (Turn 1211)                                       |   |
|  | +-- Topic: electronics.laptop                               |   |
|  | +-- Strategy: single search task                            |   |
|  | +-- Validation: APPROVE (success)                           |   |
|  | +-- Strategy Confidence: 0.95                               |   |
|  | +-- Content Type: strategy                                  |   |
|  | +-- Decay Rate: 0.02/day                                    |   |
|  |                                                              |   |
|  | Future similar query:                                        |   |
|  | "This strategy worked before with 95% confidence"           |   |
|  +-------------------------------------------------------------+   |
|                                                                     |
+--------------------------------------------------------------------+
```

---

## How Quality Is Used

**Same score, same thresholds, everywhere.**

See "Which Phases Use Quality Scores" section above for the complete table.

**Key Principle:** One score. No multiple levels. No promotion/demotion complexity.

---

## Data Storage

**research.json (simplified):**
```json
{
  "id": "research_1211_abc123",
  "quality": 0.85,
  "created_at": "2025-12-29T10:30:00Z",
  "content_type": "price",
  "claims": [
    {
      "text": "MSI Cyborg costs $1099 at Best Buy",
      "quality": 0.90,
      "source": "bestbuy.com"
    }
  ]
}
```

**TurnIndexDB:**

See `architecture/main-system-patterns/MEMORY_ARCHITECTURE.md` for the canonical schema. Just one field:
- `quality_score` - Overall turn quality (0.0-1.0)

**Storage Locations:**
- Turn documents: `turns/turn_{N}/`
- Session data: `sessions/{session_id}/`
- Global indexes: `memory/turn_index.db`, `memory/research_index.db`
- Source reliability: `memory/source_reliability.db`
- Calibration data: `observability/calibration.db`

---

## Quality Decay

Quality decays over time. See "Content-Type Specific Decay" section above for the complete decay rates and floors table.

**Decay Calculation:**
```
current_quality = floor + (initial_quality - floor) * e^(-decay_rate * days_old)
```

**Default values** (if content_type not in table):
- Default decay rate: 0.02/day
- Default floor: 0.30

---

## Scope System

Data progresses through trust levels based on usage and validation outcomes.
See `architecture/main-system-patterns/MEMORY_ARCHITECTURE.md` for the full promotion/demotion rules.

| Scope | Meaning | Promotion Criteria |
|-------|---------|-------------------|
| **new** | Just created, unproven | Default for new data |
| **user** | Proven useful for this user | usage >= 3, quality >= 0.50, age >= 1h |
| **global** | Universally useful | usage >= 10, quality >= 0.80, age >= 24h |

**Important:** Do NOT use "session" as a scope. Use "new" for newly created data.
The session_id field handles user/session namespacing separately from scope.

---

## Related Documents

- `architecture/LLM-ROLES/llm-roles-reference.md` - Model assignments per phase (REFLEX, NERVES, MIND, VOICE, EYES)
- `architecture/main-system-patterns/MEMORY_ARCHITECTURE.md` - Memory system and promotion rules
- `architecture/main-system-patterns/phase2-context-gathering.md` - Context Gatherer quality filtering
- `architecture/main-system-patterns/phase3-planner.md` - Planner quality decisions
- `architecture/main-system-patterns/phase6-validation.md` - Validation thresholds
- `architecture/main-system-patterns/phase7-save.md` - Save stores quality in metadata

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification for PandaAI v2 |
| 1.1 | 2026-01-05 | Removed implementation code, added Phase 5/7 to usage table, consolidated duplicate sections |

---

**Last Updated:** 2026-01-05
