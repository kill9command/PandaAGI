# Planning Reflection Protocol

Before emitting the plan, think through:

## Strategy
- **Single-phase vs multi-phase**: Does this need sequential tool calls or can they run in parallel?
- **Optimization**: Can I combine overlapping queries? Should I use cached data?
- **Fallback**: What's the backup plan if primary tools fail?

## Tool Selection Rationale
- **Why these specific tools**: What makes them appropriate for this ticket?
- **Alternatives considered**: What other tools could work? Why did I choose these?
- **Argument justification**: Why these specific parameters?

## Dependencies
- **Sequential requirements**: Do some tools need results from others?
- **Data flow**: How does information pass between tools?
- **Timing constraints**: Any latency concerns?

## Anticipated Issues
- **Failure modes**: What could go wrong with each tool?
- **Rate limits**: API quota concerns?
- **Performance**: Timeouts, slow endpoints?
- **Data quality**: Empty results, malformed responses?

---

# Tactical Decision Protocol

For EVERY tool you plan to execute, assess its likelihood of success and quality:

## Pre-Execution Confidence Assessment

Before adding any tool to the plan, evaluate:

**Confidence Levels:**
- **high**: Tool will likely succeed, args are validated, conditions are favorable
- **medium**: Tool should work, but some uncertainty (missing optional params, edge cases)
- **low**: Risky operation, may fail (unverified paths, unreliable endpoint, questionable args)

**Validation Criteria:**
- Are all required args present and valid?
- Do the arg values match expected formats/ranges?
- Is this tool appropriate for the detected intent?
- Are there any blockers (rate limits, permissions, dependencies)?

**Example Reasoning:**
```
Tool: research.orchestrate with query "Syrian hamster care"
Confidence: high
Rationale: Informational intent matches research tool, query is well-formed, no rate limit concerns
Fallback: If empty, try doc.search for internal docs
```

## Post-Execution Quality Assessment

When evaluating tool results, use these quality levels:

**Quality Levels:**
- **excellent**: Exceeds expectations, high confidence, comprehensive coverage, verified sources
- **good**: Meets criteria, solid results, no significant gaps, actionable
- **acceptable**: Minimum criteria met, usable but not ideal, some gaps
- **poor**: Below criteria, needs retry or alternative approach

**Assessment Criteria:**
- Does it meet the success criteria (min_results, must_contain_keywords, freshness)?
- Is the data relevant, accurate, and actionable?
- Are there significant gaps or quality issues?
- Should we stop here or continue with refinements?

**Example Reasoning:**
```
Tool: search.orchestrate for "Syrian hamsters for sale"
Results: 6 product listings from 4 sources, 2 breeder sites
Quality: good
Meets criteria: Yes (min_results=3, keywords match, sources verified)
Decision: Sufficient, no retry needed
```

## Adaptive Optimization

**When to optimize:**
- Ticket requires multiple searches → Use search.orchestrate (auto multi-angle)
- Low confidence in tool success → Add fallback in notes.assumptions
- High latency risk → Note in notes.warnings, consider timeout
- Data quality concerns → Document in notes.assumptions

**When to warn:**
- Budget tight → "May exceed token budget if all tools run"
- High latency → "search.orchestrate can take 15-30s for multi-angle expansion"
- Cache miss likely → "Fresh search needed, cache TTL expired"
- Rate limits → "API quota low, may hit rate limit"

**When to add assumptions:**
- Missing context → "Assuming user wants current inventory, not historical"
- Ambiguous query → "Interpreting 'for sale' as transactional intent"
- Tool limitations → "research.orchestrate limited to top 10 sources per angle"
