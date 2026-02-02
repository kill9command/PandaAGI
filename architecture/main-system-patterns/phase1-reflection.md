# Phase 1: Reflection

**Status:** SPECIFICATION
**Version:** 1.3
**Created:** 2026-01-04
**Updated:** 2026-01-06
**Layer:** REFLEX role (MIND model @ temp=0.3)
**Token Budget:** ~2,200 total

---

## 1. Overview

Phase 1 is a **fast binary gate** that determines whether the pipeline can proceed with answering the query or needs to ask the user for clarification.

**Core Question:** "Can we answer this query?"

This phase uses the REFLEX role (MIND model with temp=0.3) for fast, deterministic classification. It performs a simple go/no-go decision based on query clarity, not research feasibility.

**Key Design Decision:** Reflection runs BEFORE Context Gatherer. This allows the system to ask for clarification early, avoiding expensive context gathering and research on ambiguous queries.

**Design Principles:**
- Fast execution (small model, minimal tokens)
- Default to PROCEED when uncertain
- Only CLARIFY when genuinely ambiguous AND query could not be resolved by Phase 0
- Act as an early gate before expensive operations

---

## 2. Input/Output Specification

### Inputs

| Input | Source | Description |
|-------|--------|-------------|
| QueryAnalysis | Phase 0 | Original user query, resolved query, reference_resolution status, query_type, content_reference |

**Note:** Phase 1 does NOT have access to gathered context (session preferences, prior turns, cached research). That happens in Phase 2 (Context Gatherer). This phase decides based solely on the query itself.

### Outputs

| Output | Destination | Description |
|--------|-------------|-------------|
| context.md (section 1) | Phase 2 (Context Gatherer) | Reflection decision and query classification |

---

## 3. Output Schema

```json
{
  "decision": "PROCEED | CLARIFY",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation",
  "interaction_type": "ACTION | RETRY | RECALL | CLARIFICATION | INFORMATIONAL",
  "is_followup": boolean,
  "clarification_question": "string if CLARIFY"
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `decision` | enum | PROCEED or CLARIFY - the binary gate output |
| `confidence` | float | 0.0-1.0 confidence in the decision |
| `reasoning` | string | Brief explanation of why this decision was made |
| `interaction_type` | enum | Classification for downstream phases |
| `is_followup` | boolean | Whether this query references prior conversation |
| `clarification_question` | string | The question to ask user (only if CLARIFY) |

---

## 4. Decision Options

| Decision | When to Use | Next Phase |
|----------|-------------|------------|
| **PROCEED** | Query is clear enough to attempt an answer | Phase 2 (Context Gatherer) |
| **CLARIFY** | Query is genuinely ambiguous, cannot proceed | Return to user |

### PROCEED (Default Path)

Use PROCEED when:
- Query intent is understandable
- Phase 0 returned `reference_resolution.status: not_needed` or `resolved`
- Query is explicit enough to search for context
- Even if answer might be incomplete, context gathering and research can fill gaps

### CLARIFY (Exception Path)

Use CLARIFY only when:
- Phase 0 returned `reference_resolution.status: failed` AND the query is genuinely ambiguous
- Query has multiple incompatible interpretations that cannot be guessed
- Critical information is missing that even research cannot provide
- Proceeding would waste resources on wrong interpretation

---

## 4.1 Phase 1 CLARIFY Scope (Pre-Context)

Phase 1 CLARIFY handles **syntactic ambiguity** — queries that cannot be understood without user input, BEFORE gathering context:

| Trigger | Example | Why CLARIFY |
|---------|---------|-------------|
| Unresolved references with no context | "Get me one" (what is "one"?) | No prior context to resolve |
| Grammatically incomplete queries | "The cheapest" | No noun to anchor the search |
| Multiple incompatible literal interpretations | "Book that" (reserve or read?) | Cannot guess user intent |

**Phase 1 does NOT have access to memory/research.** If the query MIGHT be answerable with context, Phase 1 MUST return PROCEED.

**Key Principle:** Phase 1 CLARIFY is for queries that are fundamentally unclear. If there's any reasonable interpretation, PROCEED and let Phase 3 (Planner) handle it with full context.

---

## 5. Interaction Type Classification

**Note:** Phase 1 outputs `interaction_type` (not `query_type`) to distinguish from Phase 0's query classification.

The `interaction_type` field classifies the user's intent for downstream phases:

| Type | Description | Example |
|------|-------------|---------|
| **ACTION** | User wants something done | "Find me a laptop under $500" |
| **RETRY** | User wants fresh/different results | "Search again" / "Try different sources" |
| **RECALL** | User asking about previous results | "What was that first option?" |
| **CLARIFICATION** | User asking about prior response | "What did you mean by that?" |
| **INFORMATIONAL** | User wants to learn/understand | "How do neural networks work?" |

---

## 6. Decision Logic

```
INPUT: QueryAnalysis from Phase 0

1. Parse QueryAnalysis fields:
   - resolved_query
   - reference_resolution.status
   - query_type
   - content_reference

2. Evaluate clarity based on reference_resolution.status:

   IF reference_resolution.status == "not_needed"
      Query was already explicit, no references to resolve
      decision = PROCEED
      reasoning = "Query is explicit, no resolution needed"

   ELSE IF reference_resolution.status == "resolved"
      References were found and successfully interpreted
      decision = PROCEED
      reasoning = "Query references resolved successfully"

   ELSE IF reference_resolution.status == "failed"
      References were found but could NOT be resolved
      Check if query is still understandable:

      IF query has a reasonable default interpretation
         decision = PROCEED
         confidence = lower value
         reasoning = "Making reasonable assumption despite unresolved reference"

      ELSE query is genuinely ambiguous
         decision = CLARIFY
         clarification_question = ask for disambiguation

OUTPUT: context.md section 1
```

### Key Principle: Default to PROCEED

When uncertain, **always PROCEED**. The downstream phases (Context Gatherer, Planner, Coordinator) can handle incomplete information better than asking excessive clarifying questions.

Bad user experience: Asking "What do you mean?" for every query
Good user experience: Making reasonable assumptions and asking only when truly necessary

### Using reference_resolution.status

The `reference_resolution.status` from Phase 0 provides an unambiguous signal:

| Status | Meaning | Phase 1 Action |
|--------|---------|----------------|
| `not_needed` | Query had no references to resolve (already explicit) | Strongly favor PROCEED |
| `resolved` | References found and successfully interpreted | Strongly favor PROCEED |
| `failed` | References found but could NOT be resolved | Evaluate if still actionable, lean toward CLARIFY |

---

## 7. Token Budget

| Component | Tokens |
|-----------|--------|
| Prompt | 600 |
| Input (QueryAnalysis) | 1,200 |
| Output (JSON response) | 400 |
| **Total** | **~2,200** |

This is one of the smallest token budgets in the pipeline, reflecting the phase's role as a fast gate.

---

## 8. Examples

### Example 1: PROCEED (Clear Query)

**Input (QueryAnalysis from Phase 0):**
```json
{
  "resolved_query": "What is the cheapest laptop with NVIDIA GPU?",
  "reference_resolution": {
    "status": "not_needed",
    "original_references": [],
    "resolved_to": null
  },
  "query_type": "general_question",
  "content_reference": {
    "title": null,
    "content_type": null,
    "site": null,
    "source_turn": null
  },
  "reasoning": "Query is already explicit, no references to resolve"
}
```

**Output (section 1):**
```json
{
  "decision": "PROCEED",
  "confidence": 0.95,
  "reasoning": "Query intent is clear: find lowest-priced NVIDIA GPU laptop. No ambiguity.",
  "interaction_type": "ACTION",
  "is_followup": false,
  "clarification_question": null
}
```

---

### Example 2: CLARIFY (Ambiguous Query, Unresolved)

**Input (QueryAnalysis from Phase 0):**
```json
{
  "resolved_query": "Get me one",
  "reference_resolution": {
    "status": "failed",
    "original_references": ["one"],
    "resolved_to": null
  },
  "query_type": "followup",
  "content_reference": {
    "title": null,
    "content_type": null,
    "site": null,
    "source_turn": null
  },
  "reasoning": "Could not resolve 'one' - no recent context available"
}
```

**Output (section 1):**
```json
{
  "decision": "CLARIFY",
  "confidence": 0.90,
  "reasoning": "Query 'get me one' has no referent. Phase 0 could not resolve what 'one' refers to.",
  "interaction_type": "ACTION",
  "is_followup": true,
  "clarification_question": "I'm not sure what you'd like me to get. Could you specify what you're looking for?"
}
```

---

### Example 3: PROCEED (Follow-up Successfully Resolved)

**Input (QueryAnalysis from Phase 0):**
```json
{
  "resolved_query": "What about the 16GB RAM version of the Lenovo LOQ 15?",
  "reference_resolution": {
    "status": "resolved",
    "original_references": ["the 16GB version"],
    "resolved_to": "16GB RAM version of the Lenovo LOQ 15"
  },
  "query_type": "followup",
  "content_reference": {
    "title": "Lenovo LOQ 15",
    "content_type": "product",
    "site": "Best Buy",
    "source_turn": 815
  },
  "reasoning": "Resolved '16GB version' to Lenovo LOQ 15 variant based on turn 815 context"
}
```

**Output (section 1):**
```json
{
  "decision": "PROCEED",
  "confidence": 0.95,
  "reasoning": "Phase 0 successfully resolved the follow-up reference. Query is now explicit.",
  "interaction_type": "RECALL",
  "is_followup": true,
  "clarification_question": null
}
```

---

## 9. Section 1 Format in context.md

When written to context.md, the output appears as:

```markdown
## 1. Reflection Decision

**Decision:** PROCEED
**Confidence:** 0.95
**Interaction Type:** ACTION
**Is Follow-up:** false

**Reasoning:** Query intent is clear: find lowest-priced NVIDIA GPU laptop. No ambiguity.
```

Or for CLARIFY:

```markdown
## 1. Reflection Decision

**Decision:** CLARIFY
**Confidence:** 0.90
**Interaction Type:** ACTION
**Is Follow-up:** true

**Reasoning:** Query 'get me one' has no referent. Phase 0 could not resolve what 'one' refers to.

**Clarification Question:** I'm not sure what you'd like me to get. Could you specify what you're looking for?
```

---

## 10. Integration Points

### Upstream (Phase 0)
- Receives: QueryAnalysis object with resolved_query, reference_resolution, query_type, content_reference
- Key signal: `reference_resolution.status` indicates if Phase 0 could interpret the query

### Downstream (Phase 2)
- Provides: interaction_type classification for Context Gatherer routing decisions
- If PROCEED: Pipeline continues to Context Gatherer (Phase 2)
- If CLARIFY: Pipeline exits early, returns clarification question to user

---

## 11. Anti-Patterns

**DO NOT:**
- Ask for clarification when Phase 0 resolved the query (`reference_resolution.status: resolved`)
- Over-classify as CLARIFY to "be safe"
- Add complex logic or multiple decision branches
- Spend tokens on detailed analysis (that's the Planner's job)
- Wait for context gathering before deciding - this phase happens BEFORE context

**DO:**
- Default to PROCEED when uncertain
- Keep reasoning brief
- Trust downstream phases to handle nuance
- Use `reference_resolution.status` as a strong signal

---

## 12. Related Documents

- `architecture/main-system-patterns/phase0-query-analyzer.md` - Prior phase (provides QueryAnalysis)
- `architecture/main-system-patterns/phase2-context-gathering.md` - Next phase (if PROCEED)
- `architecture/LLM-ROLES/llm-roles-reference.md` - Model assignments

---

## 13. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 1.1 | 2026-01-05 | Updated phase ordering (was Phase 2, now Phase 1) |
| 1.2 | 2026-01-05 | Removed implementation references, added Related Documents and Changelog |
| 1.3 | 2026-01-05 | Updated to use `reference_resolution.status` enum instead of `was_resolved` boolean; added Phase 1 CLARIFY Scope section defining syntactic vs semantic ambiguity handling |

---

**Last Updated:** 2026-01-05
