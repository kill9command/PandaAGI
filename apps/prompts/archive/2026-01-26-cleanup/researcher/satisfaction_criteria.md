# Research Role: Satisfaction Criteria & Completion Evaluation

## When to Evaluate

**Standard Mode:** No evaluation needed (1-pass only, always complete)

**Deep Mode Only:** After EVERY pass, evaluate: "Do I have enough information to satisfy the research goal?"

## The Four Criteria

### 1. Coverage (Breadth)
**Question:** Did we check enough sources to be confident?

**Thresholds:**
- **Minimum required:** 8-10 credible sources
- **Optimal:** 12-15 sources
- **Maximum useful:** 20 sources (diminishing returns after this)

**How to check:**
```
sources_checked = len(phase1_sources) + len(phase2_sources)
coverage_met = sources_checked >= min_required
```

**Not met if:**
- < 8 sources found (too narrow)
- Only 1-2 domains covered (need diversity)
- All sources from same type (e.g., all forums, no expert sites)

**Example:**
```markdown
### Coverage Check
- Sources found: 12
- Min required: 10
- Domains: 5 (forums, USDA, breeder sites, review sites, expert blogs)
- Status: ✓ MET
```

---

### 2. Quality (Trustworthiness)
**Question:** Are the sources credible and relevant?

**Metrics:**
- **Average confidence score:** From synthesis (0.0-1.0)
- **Minimum threshold:** 0.75-0.80
- **Credibility signals:** USDA licensed, established domain, positive reviews

**How to check:**
```
avg_confidence = synthesis["confidence"]
quality_met = avg_confidence >= min_confidence_threshold
```

**Not met if:**
- Average confidence < 0.75 (low trust)
- Sources contradict each other significantly
- Many low-relevance results (relevance_score < 0.6)

**Example:**
```markdown
### Quality Check
- Avg confidence: 0.82
- Min required: 0.80
- Credible sources: 9/12 (USDA licensed, established forums)
- Status: ✓ MET
```

---

### 3. Completeness (All Required Info Present)
**Question:** Do we have all the information fields needed to answer the query?

**Required Fields by Query Type:**

**Commerce Search (products/vendors):**
- Name
- Location/contact
- Pricing
- Credibility signals (certifications, reviews)
- Availability (optional but valuable)
- Shipping/delivery info

**Informational Research:**
- Key topics covered
- Expert opinions
- Evidence/citations
- Actionable recommendations

**Comparison Research:**
- Pros/cons for each option
- Comparison criteria
- Best use cases

**How to check:**
```
required_info = ["prices", "reputation", "availability", "contact"]
found_info = extract_present_fields(results)
missing = [f for f in required_info if f not in found_info]
completeness_met = len(missing) == 0
```

**Not met if:**
- Missing critical fields (e.g., no pricing for commerce query)
- Incomplete vendor details (name but no contact)
- Research goal has multiple sub-questions, some unanswered

**Example:**
```markdown
### Completeness Check
- Required info: [prices, reputation, availability, health_guarantees]
- Found info: [prices, reputation, health_guarantees]
- Missing: availability (current stock status)
- Status: ✗ NOT MET
```

---

### 4. Contradictions Resolved
**Question:** Are the findings consistent, or do sources disagree?

**Types of contradictions:**
- **Pricing conflicts:** One source says $25, another says $50 for same item
- **Factual disputes:** Source A says X is good, Source B says X is bad
- **Availability conflicts:** Listed as "in stock" on one site, "sold out" on another

**How to handle:**
- **Resolvable:** Check original sources, trust more credible one, note in synthesis
- **Flagged:** Can't resolve, present both views to user with context

**How to check:**
```
contradictions = detect_contradictions(findings)
resolved = [c for c in contradictions if c["status"] == "resolved"]
flagged = [c for c in contradictions if c["status"] == "flagged"]
contradictions_met = len(flagged) == 0
```

**Example:**
```markdown
### Contradictions
- Found: 1 pricing conflict ($30 vs $35 for Golden Syrian)
- Resolution: $35 is current price (verified on vendor site), $30 was old listing
- Flagged: 0
- Status: ✓ RESOLVED
```

---

## The Decision Matrix

After evaluating all four criteria:

| Coverage | Quality | Completeness | Contradictions | Decision |
|----------|---------|--------------|----------------|----------|
| ✓ | ✓ | ✓ | ✓ | **COMPLETE** |
| ✓ | ✓ | ✗ | ✓ | **CONTINUE** (fill gaps) |
| ✗ | ✓ | ✓ | ✓ | **CONTINUE** (check more sources) |
| ✓ | ✗ | ✓ | ✓ | **CONTINUE** (find better sources) |
| ✗ | ✗ | ✗ | ✗ | **CONTINUE** (major issues) |
| Pass 3 | Any | Any | Any | **COMPLETE** (max passes) |

**Rules:**
1. ALL four criteria must be MET to declare COMPLETE
2. If ANY criterion NOT MET → CONTINUE (unless at max passes)
3. Max passes: 3 (hard limit to prevent infinite loops)
4. Pass 3 always completes (return best effort results)

---

## Generating Refined Queries for Next Pass

When decision is CONTINUE, identify what's missing and generate targeted queries:

### Missing Coverage
**Problem:** Only 6 sources found, need 8-10

**Solution:** Broaden search
```
Refined queries:
- "{query} site:alternative-forum.com"
- "where to find {query}"
- "{query} online marketplace"
```

### Missing Completeness (Availability)
**Problem:** Have prices and reputation, missing current stock

**Solution:** Deep-crawl vendor sites
```
Next action:
- Visit vendor catalog pages with pagination
- Check /available, /current-stock sections
- Look for "in stock" vs "sold out" indicators

Refined queries:
- "{vendor_name} available now"
- "{vendor_name} current inventory"
- Visit detected catalog URLs directly
```

### Missing Completeness (Genetics Info)
**Problem:** Have basic vendor info, user wanted genetics/lineage details

**Solution:** Specialized queries
```
Refined queries:
- "{query} genetics breeding program"
- "{query} lineage tracking"
- "{vendor_name} breeding lines"
- "site:{vendor_domain} genetics"
```

### Low Quality
**Problem:** Average confidence only 0.65, need 0.80

**Solution:** Find more credible sources
```
Refined queries:
- "{query} site:usda.gov"
- "{query} certified breeders"
- "{query} site:established-forum.com"
```

---

## satisfaction_check.md Output Format

After each pass in Deep mode, write this document:

```markdown
# Satisfaction Check: Pass {n}

## Evaluation Date
{timestamp}

## Pass {n} Results Summary
- Sources checked: {count}
- Vendors found: {count}
- Avg confidence: {0.0-1.0}
- Duration: {seconds}

---

## Criterion 1: Coverage
- **Sources found:** {count}
- **Min required:** 10
- **Domains covered:** {list}
- **Status:** [✓ MET | ✗ NOT MET]
- **Notes:** {explanation}

## Criterion 2: Quality
- **Avg confidence:** {0.0-1.0}
- **Min required:** 0.80
- **Credible sources:** {count}/{total}
- **Status:** [✓ MET | ✗ NOT MET]
- **Notes:** {explanation}

## Criterion 3: Completeness
- **Required info:** [field1, field2, field3]
- **Found info:** [field1, field2]
- **Missing:** [field3]
- **Status:** [✓ MET | ✗ NOT MET]
- **Notes:** {explanation}

## Criterion 4: Contradictions
- **Found:** {count} contradictions
- **Resolved:** {count}
- **Flagged:** {count}
- **Status:** [✓ RESOLVED | ✗ FLAGGED]
- **Details:** {list contradictions}

---

## Decision: [COMPLETE | CONTINUE]

### Reasoning
{Explain why you're completing or continuing}

### If CONTINUE: Next Actions
**What's missing:** {gap analysis}

**Next pass strategy:**
- Focus area: {what to prioritize}
- Max sources: {count}
- Estimated tokens: {count}

**Refined queries:**
1. {query 1}
2. {query 2}
3. {query 3}

**Special actions:**
- [ ] Deep-crawl vendor catalogs for {info}
- [ ] Visit expert sites for {info}
- [ ] Check certification databases

### If COMPLETE: Summary
All criteria met:
- ✓ Coverage: {sources} sources from {domains} domains
- ✓ Quality: {confidence} confidence from credible sources
- ✓ Completeness: All required fields present
- ✓ Contradictions: All resolved

Ready to return results to Context Manager.
```

---

## Special Cases

### Early Completion (Pass 1)
If ALL criteria met on first pass → COMPLETE immediately
Don't force 3 passes if 1 is sufficient

### Partial Success (Pass 3)
If Pass 3 still has gaps → COMPLETE anyway (max passes reached)
Flag the gaps in synthesis for Context Manager to note

### Budget Exhaustion
If token budget critically low mid-Deep mode → COMPLETE current pass
Don't start Pass 3 if insufficient budget

### Zero Results
If Pass 1 finds nothing useful → Try different search angles in Pass 2
If Pass 2 also fails → COMPLETE with "no results" synthesis

---

## Integration with Research Orchestrator

Your evaluation results feed back into the research loop:

```python
# Pseudo-code
for pass_num in range(1, 4):  # Max 3 passes
    execute_pass(pass_num)

    if mode == "standard":
        break  # Standard = 1 pass only

    if mode == "deep":
        evaluation = evaluate_satisfaction(pass_results)

        if evaluation["decision"] == "COMPLETE":
            break
        elif evaluation["decision"] == "CONTINUE":
            refined_queries = generate_refined_queries(evaluation["missing"])
            continue  # Execute next pass
```

Your `satisfaction_check.md` drives this loop.

---

## Remember

You are the **quality gatekeeper** for Deep research. Don't settle for incomplete results when the user asked for comprehensive research. But also don't over-search when criteria are met. Balance thoroughness with efficiency.

**When in doubt:** Continue if Pass 1-2, Complete if Pass 3.
