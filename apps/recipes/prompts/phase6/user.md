# Phase 6: Validation - User Prompt Template

## Context Document (Sections 0-5)

{context_md}

## Synthesized Response (from Phase 5)

{synthesis_response}

## Your Task

Validate the synthesized response against the context document. Perform all four mandatory checks:

### 1. Claims Supported Check
- Extract each factual claim from the response (prices, specs, product names)
- Search Section 4 (Tool Execution) and Section 2 (Gathered Context) for evidence
- Mark as FAIL if ANY claim lacks supporting evidence

### 2. No Hallucinations Check
- Verify all product names exist in Section 4/2
- Verify all URLs were returned by tools
- Verify all features/specs are from sources
- Mark as FAIL if ANY invented information detected

### 3. Query Addressed Check
- Compare response to original query in Section 0
- Does it answer what was actually asked?
- Does it satisfy the user's intent (cheapest, best, etc.)?

### 4. Coherent Format Check
- Are URLs clickable markdown links? `[text](url)`
- Is structure logical (headers, lists)?
- Is formatting valid (no broken markdown)?

### Decision Guide

- **APPROVE**: All 4 checks pass, confidence >= 0.80
- **REVISE**: Minor issues fixable by Synthesis (formatting, wording)
- **RETRY**: Fundamental issues requiring re-planning (wrong data, missed query)
- **FAIL**: Unrecoverable or limits exceeded

### For Multi-Goal Queries

If Section 3 shows multiple goals, validate each:
- Check if each goal is addressed
- Score each goal's quality
- Use aggregate decision matrix

Output your ValidationResult JSON.
