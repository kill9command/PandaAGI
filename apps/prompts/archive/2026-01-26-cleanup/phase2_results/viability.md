# Result Viability Evaluation

## Viability Assessment

Every result must be evaluated against requirements from the research plan and Phase 1 intelligence.

## Evaluation Criteria

### 1. Requirement Matching

Score each result against discovered requirements:

```
For each requirement from Phase 1 or research_plan:
  - MEETS: Result satisfies requirement (+1.0)
  - PARTIAL: Result partially satisfies (+0.5)
  - FAILS: Result does not satisfy (-0.5)
  - UNKNOWN: Cannot determine (0.0)
```

### 2. Constraint Checking

Check hard constraints (pass/fail):

| Constraint Type | Check | Action if Fail |
|----------------|-------|----------------|
| Budget | price <= max_budget | Reject |
| Location | available in region | Reject |
| Availability | in stock / bookable | Flag as warning |
| Compatibility | meets compatibility reqs | Reject |

### 3. Quality Factors

Score soft factors (0.0-1.0):

- **Source Reputation**: Known reliable vendor?
- **Data Freshness**: Price/availability current?
- **Review Sentiment**: Positive reviews?
- **Value Score**: Price vs. features ratio

## Viability Score Calculation

```
base_score = requirement_match_score  # -1.0 to 1.0
quality_modifier = avg(quality_factors)  # 0.0 to 1.0

viability = (base_score + 1) / 2 * quality_modifier
# Result: 0.0 to 1.0
```

## Classification Thresholds

| Score Range | Classification | Action |
|-------------|---------------|--------|
| 0.80 - 1.00 | Excellent | Include, highlight |
| 0.60 - 0.79 | Good | Include |
| 0.40 - 0.59 | Marginal | Include with caveats |
| 0.20 - 0.39 | Poor | Include in rejected list |
| 0.00 - 0.19 | Unviable | Reject with reason |

## Rejection Reasons

When rejecting, specify clear reason:

- `over_budget`: Exceeds maximum price
- `out_of_stock`: Not available
- `missing_requirement`: Lacks required feature/spec
- `incompatible`: Doesn't meet compatibility constraints
- `low_quality`: Poor reviews or reputation
- `outdated`: Information too old
- `incomplete_data`: Missing critical information

## Strengths and Weaknesses

For each viable result, identify:

**Strengths** (things that match or exceed requirements):
- "Under budget by $X"
- "Exceeds recommended spec for [attribute]"
- "Highly rated (X stars, N reviews)"
- "From trusted vendor"

**Weaknesses** (things that fall short or have caveats):
- "Only X GB RAM (recommended: Y GB)"
- "Limited availability"
- "No returns policy"
- "Mixed reviews on [aspect]"

## Ranking Results

After viability scoring, rank by:

1. **Primary**: Viability score (descending)
2. **Secondary**: Confidence score (descending)
3. **Tertiary**: Price/value (domain-dependent)

## Output Structure

For each result:
```json
{
  "title": "...",
  "viability_score": 0.85,
  "classification": "excellent",
  "requirements_met": ["RTX 4060", "16GB RAM"],
  "requirements_partial": ["512GB SSD (wanted 1TB)"],
  "requirements_failed": [],
  "constraints_passed": true,
  "strengths": ["Under budget", "Good reviews"],
  "weaknesses": ["Only 512GB storage"],
  "recommendation": "Strong candidate - meets core requirements"
}
```
