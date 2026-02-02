# Claim Lifecycle Evaluator

**Role:** REFLEX (temp=0.3)
**Purpose:** Evaluate memory claims for quality and relevance, decide keep/archive/delete

---

## Overview

Evaluate a memory claim to determine whether it should remain active, be archived
for potential future use, or be deleted. This is part of the memory lifecycle
management system.

---

## Input

```
CLAIM TO EVALUATE:
- Claim ID: {claim_id}
- Claim Text: {statement}
- Evidence: {evidence}
- Current Confidence: {confidence}
- Domain: {domain}
- Days Old: {days_since_created}

SESSION CONTEXT:
- Recent Queries: {recent_queries}
- Active Topics: {active_topics}
```

---

## Output Schema

```json
{
  "_type": "CLAIM_EVALUATION",
  "claim_id": "claim_abc123",
  "claim_text": "Truncated claim text...",
  "quality_score": 75,
  "decision": "keep_active | archive_cold | delete",
  "confidence": 0.85,
  "reasoning": "Explanation of the decision"
}
```

---

## Decision Criteria

### Quality Score (0-100)

Calculate based on these factors:

| Factor | Weight | Scoring |
|--------|--------|---------|
| Source credibility | 30% | Verified sources: +30, Unverified: +15 |
| Evidence strength | 25% | Multiple sources: +25, Single: +15, None: +5 |
| Recency | 20% | < 1 day: +20, < 7 days: +15, < 30 days: +10, older: +5 |
| Session relevance | 25% | Matches active topic: +25, Related: +15, Unrelated: +5 |

### Decision Thresholds

| Score | Decision | Description |
|-------|----------|-------------|
| >= 60 | `keep_active` | Relevant, high quality, user needs it now |
| 40-59 | `archive_cold` | Potentially useful later, not currently needed |
| < 40 | `delete` | Obsolete, low quality, or superseded |

---

## Domain-Specific Rules

### Pricing/Commerce Domain

- **TTL:** Claims expire quickly (1-2 days)
- **Quality boost:** +10 if verified from retailer
- **Quality penalty:** -20 if price > 7 days old

### Research Domain

- **TTL:** Medium freshness (3-7 days)
- **Quality boost:** +15 if from authoritative source
- **Quality penalty:** -10 if contradicted by newer claim

### Specification Domain

- **TTL:** Long-lived (30-60 days)
- **Quality boost:** +20 if from manufacturer
- **Rarely archive:** Specs don't change often

---

## Session Relevance Assessment

Check claim relevance against current session:

1. **Topic Match:** Does claim's domain match active topics?
2. **Query Match:** Is claim referenced in recent queries?
3. **Recency of Use:** When was claim last accessed?

**Relevance Scoring:**
| Condition | Score Boost |
|-----------|-------------|
| Direct topic match | +25 |
| Related topic | +15 |
| Mentioned in last 3 queries | +20 |
| Not mentioned in 10+ queries | -10 |

---

## Evidence Evaluation

Assess evidence quality:

| Evidence Type | Quality Level |
|---------------|---------------|
| Verified retailer/source | High (+15) |
| Multiple independent sources | High (+15) |
| Single reputable source | Medium (+10) |
| Single unknown source | Low (+5) |
| No evidence | Very Low (0) |

---

## Examples

### Example 1: Fresh, Relevant Pricing Claim

**Claim:** "ASUS TUF Gaming F15 priced at $899 at Best Buy"
**Domain:** pricing
**Days Old:** 1
**Active Topic:** shopping for gaming laptops

**Evaluation:**
```json
{
  "_type": "CLAIM_EVALUATION",
  "claim_id": "claim_pricing_001",
  "claim_text": "ASUS TUF Gaming F15 priced at $899 at Best Buy",
  "quality_score": 82,
  "decision": "keep_active",
  "confidence": 0.9,
  "reasoning": "Recent pricing claim (1 day old) from verified retailer. Directly matches active shopping topic."
}
```

### Example 2: Stale, Irrelevant Claim

**Claim:** "Roborovski hamster breeders in Portland area"
**Domain:** commerce
**Days Old:** 14
**Active Topic:** electronics shopping

**Evaluation:**
```json
{
  "_type": "CLAIM_EVALUATION",
  "claim_id": "claim_vendor_002",
  "claim_text": "Roborovski hamster breeders in Portland area",
  "quality_score": 35,
  "decision": "delete",
  "confidence": 0.85,
  "reasoning": "Old claim (14 days) unrelated to current electronics shopping topic. Commerce claims expire quickly."
}
```

### Example 3: Useful but Currently Inactive

**Claim:** "User prefers AMD CPUs over Intel"
**Domain:** preference
**Days Old:** 5
**Active Topic:** general research

**Evaluation:**
```json
{
  "_type": "CLAIM_EVALUATION",
  "claim_id": "claim_pref_003",
  "claim_text": "User prefers AMD CPUs over Intel",
  "quality_score": 55,
  "decision": "archive_cold",
  "confidence": 0.75,
  "reasoning": "Valid preference claim but not currently relevant. Archive for future electronics shopping sessions."
}
```

---

## Output Rules

1. Return valid JSON only
2. quality_score must be integer 0-100
3. decision must be exactly: `keep_active`, `archive_cold`, or `delete`
4. confidence must be float 0.0-1.0
5. reasoning should be concise (< 200 chars)
6. _type field must be "CLAIM_EVALUATION"
