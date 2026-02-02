# Phase 1: Reflection - User Prompt Template

## Query Analysis from Phase 0

{context_section_0}

## Your Task

Based on the query analysis above, decide whether to PROCEED with answering or CLARIFY with the user.

Remember:
- If `reference_resolution.status` is "not_needed" or "resolved", strongly favor PROCEED
- If `reference_resolution.status` is "failed", evaluate if the query is still actionable
- Default to PROCEED when uncertain - downstream phases can handle incomplete information

Output your ReflectionResult JSON.
