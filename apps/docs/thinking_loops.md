# Thinking Loops: Plan/Act/Review Architecture

**Version:** 2.0.0  
**Status:** Implemented  
**Date:** November 2025

---

## Overview

The Thinking Loops system adds structured **Plan/Act/Review** reasoning to the existing 3-brain architecture (Guide, Coordinator, Context Manager). This enables the system to:

1. **Plan** before acting (reflection on strategy, risks, success criteria)
2. **Act** by executing tools
3. **Review** results with quality diagnostics and adaptive refinement

This mirrors human problem-solving and aligns with research on iterative LLM reasoning ([arXiv 2409.12618](https://arxiv.org/abs/2409.12618)).

---

## Architecture Integration

### User's 4-Role Concept → Existing 3-Brain Mapping

| User's Proposed Role | Maps To | Thinking Loop Phase |
|---------------------|---------|---------------------|
| **Researcher** | Guide (ticket creation) | **Plan**: Reflect on search strategy |
| **Searcher** | Coordinator (tool planning) | **Plan**: Select tools, anticipate issues |
| **Verifier** | Context Manager (claim scoring) | **Review**: Quality diagnostics, rejection analysis |
| **Synthesiser** | Guide (final answer) | **Review**: Check quality, refine if needed |

### Flow Diagram

```
User: "Find Syrian hamsters for sale"
   ↓
Guide (PLAN Phase):
   - Reflection: "Need live animals, not books/toys"
   - Risks: "Educational sites may pollute results"
   - Success criteria: "≥3 verified live animal listings"
   - Creates TICKET with reflection metadata
   ↓
Coordinator (PLAN Phase):
   - Strategy: "Two-phase: source discovery → filtered search"
   - Tool selection: research_mcp + commerce.search_offers
   - Anticipated issues: "First run slow, LLM timeout risk"
   - Creates PLAN with reflection metadata
   ↓
Orchestrator (ACT Phase):
   - Executes tools sequentially
   - Collects results + metadata
   ↓
Context Manager (REVIEW Phase):
   - Extracts candidates from tool results
   - Computes quality_report:
     * 15 fetched, 4 verified, 11 rejected
     * Quality score: 0.27 (BELOW threshold 0.3)
     * Rejection breakdown: {educational: 5, cage: 3, book: 3}
   - Generates suggested_refinement
   ↓
Gateway (REVIEW Phase):
   - Checks quality_report.meets_threshold
   - If FALSE and retries available:
     * Apply suggested_refinement to ticket
     * Retry from Guide (PLAN) with refined filters
   - If TRUE or max retries exhausted:
     * Return results to Guide
   ↓
Guide (REVIEW + Answer):
   - Checks capsule quality_report
   - Synthesizes answer with caveats if quality low
   - Returns to user
```

---

## Key Components

### 1. Enhanced Prompts

#### **solver_system_v2.md** (Guide)

Adds `reflection` block to tickets:

```json
{
  "_type": "TICKET",
  "reflection": {
    "plan": "Two-phase: research breeders → filtered search",
    "assumptions": ["User wants live animals not toys"],
    "risks": ["Educational sites may pollute results"],
    "success_criteria": "≥3 verified live animal listings"
  },
  "goal": "Find live Syrian hamsters from US breeders",
  ...
}
```

**Review phase**: Guide checks `quality_report` in capsule and acknowledges limitations if quality low.

#### **thinking_system_v2.md** (Coordinator)

Adds `reflection` block to plans:

```json
{
  "_type": "PLAN",
  "reflection": {
    "strategy": "Two-phase: source discovery → filtered search",
    "tool_selection_rationale": "research_mcp for trusted sellers first",
    "dependencies": "Sequential: research completes before commerce",
    "anticipated_issues": ["Source discovery slow on first run"]
  },
  "plan": [...],
  ...
}
```

### 2. Schema Extensions

#### **QualityReport** (Pydantic Model)

```python
class QualityReport(BaseModel):
    total_fetched: int
    verified: int
    rejected: int
    rejection_breakdown: Dict[str, int]  # {"educational_resource": 5, "cage": 3}
    quality_score: float  # 0.0-1.0 (verified/total)
    meets_threshold: bool  # True if score >= 0.3
    suggested_refinement: Optional[Dict[str, Any]]
```

#### **CapsuleEnvelope** Updates

Added `quality_report: Optional[QualityReport]` field to both:
- Pydantic model (`orchestrator/shared_state/schema.py`)
- Dataclass (`orchestrator/context_builder.py`)

### 3. Quality Report Generation

**Function**: `_compute_quality_report()` in `context_builder.py`

**Logic**:
1. Check if commerce tools (`commerce.search_offers`, `purchasing.lookup`) were used
2. Aggregate stats from tool responses:
   - `total_fetched`, `verified`, `rejected`
   - Rejection breakdown by reason
3. Compute `quality_score = verified / total_fetched`
4. If score < threshold (default 0.3):
   - Generate `suggested_refinement` based on dominant rejection reasons
   - Map reasons to filter adjustments:
     * `educational_resource` → add `-educational`, `-.edu`, `-classroom`
     * `appears_to_be_cage` → add `-cage`, `-habitat`, `-enclosure`
     * `appears_to_be_book` → add `-book`, `-isbn`, `-paperback`

**Example Output**:

```python
QualityReport(
    total_fetched=15,
    verified=4,
    rejected=11,
    rejection_breakdown={"educational_resource": 5, "cage": 3, "book": 3},
    quality_score=0.27,
    meets_threshold=False,
    suggested_refinement={
        "reason": "High rejection rate: educational_resource (5 items)",
        "add_negative_keywords": ["educational", ".edu", "classroom"],
        "add_positive_keywords": []
    }
)
```

---

## Retry Logic (Future Enhancement)

**Note**: The Gateway retry loop is **NOT yet implemented** but can be added using this pattern:

```python
# In gateway/app.py, _run_ticket() function:

async def _run_ticket_with_retry(ticket, max_retries=2):
    for attempt in range(max_retries):
        # Phase 1: PLAN (Coordinator)
        plan = await _call_coordinator(ticket)
        
        # Phase 2: ACT (Execute tools)
        bundle = await _execute_tools(plan)
        
        # Phase 3: REVIEW (Context Manager)
        capsule = compile_capsule(ticket, bundle, tool_records=...)
        
        quality = capsule.envelope.quality_report
        
        # Success check
        if not quality or quality.meets_threshold:
            return capsule  # Success!
        
        # Retry logic
        if attempt < max_retries - 1 and quality.suggested_refinement:
            logger.info(f"Quality {quality.quality_score:.2f} below threshold. Refining...")
            
            # Apply refinement to ticket
            ticket = _apply_refinement(ticket, quality.suggested_refinement)
            continue  # Retry loop
        
        # Max retries exhausted - return with caveats
        return capsule
```

**Configuration** (add to `.env`):

```bash
# Thinking Loops Configuration
QUALITY_THRESHOLD=0.3        # Minimum quality score (0.0-1.0)
MAX_SEARCH_RETRIES=2         # Maximum retry attempts
ENABLE_ADAPTIVE_REFINEMENT=true
```

---

## Benefits

### 1. Transparent Reasoning
- Reflection logs show **why** decisions were made
- Audit trail for debugging and analysis

### 2. Adaptive Refinement
- System learns from failures
- Automatically adjusts filters based on rejection analysis
- No blind retries - refinements are targeted

### 3. Quality Awareness
- Won't return junk results blindly
- Tracks verification success rate
- Provides caveats when quality is low

### 4. Backward Compatible
- Existing prompts work without modification
- Reflection is additive (optional)
- Quality report only for commerce tools

---

## Example: Syrian Hamster Search

### Turn 1 (Initial)

**User**: "Find me Syrian hamsters for sale"

**Guide Reflection**:
```json
{
  "plan": "Research breeders → search with filters → verify live animals",
  "assumptions": ["User wants live animals not toys/books", "US sellers preferred"],
  "risks": ["Educational sites may pollute", "Cages/accessories in results"],
  "success_criteria": "≥3 verified live animal listings from trusted sellers"
}
```

**Coordinator Reflection**:
```json
{
  "strategy": "Two-phase: source discovery → filtered search. Phase 1 cached after first run.",
  "tool_selection_rationale": "research_mcp identifies trusted breeders before commerce.search_offers",
  "dependencies": "Sequential: research_mcp completes first",
  "anticipated_issues": ["Source discovery adds 2-3s", "LLM extraction timeout risk"]
}
```

**Results**:
- 15 fetched, 4 verified, 11 rejected
- Quality: 0.27 (BELOW threshold)
- Dominant rejection: `educational_resource` (5 items)

**Quality Report Triggers Refinement** (if retry enabled):
```json
{
  "reason": "High rejection rate: educational_resource (5 items)",
  "add_negative_keywords": ["educational", ".edu", "classroom"],
  "add_positive_keywords": []
}
```

### Turn 1 Retry (Automatic)

**Refined Ticket**:
- Added `must_not_have_attributes`: `["cage", "toy", "book", "educational", ".edu", "classroom"]`
- Added `must_have_attributes`: `["live", "breeder"]`

**Results**:
- 12 fetched, 5 verified, 7 rejected
- Quality: 0.42 (ABOVE threshold!)
- Success criteria met: ≥3 listings ✓

**Guide Synthesizes Answer**:
```markdown
Found 5 verified Syrian hamsters from breeders:

1. [Syrian Hamster - 8 weeks old](link) — $35.00 from Happy Paws (in stock)
2. [Golden Syrian Female](link) — $25.00 from PetConnect (available)
...

Quality score: 42% (5/12 verified)
```

---

## Testing

### Manual Test (After Implementation)

1. **Restart Gateway** to load new prompt files
2. **Test query**: "Can you find me Syrian hamsters for sale online?"
3. **Expected behavior**:
   - Guide creates ticket with reflection
   - Coordinator creates plan with reflection
   - Context Manager computes quality_report
   - Quality report appears in capsule envelope
4. **Check transcripts** (`transcripts/verbose/<trace_id>.json`) for:
   - `reflection` blocks in tickets/plans
   - `quality_report` in capsule envelope

### Automated Test

```python
# scripts/test_thinking_loops.py
import asyncio
from orchestrator.context_builder import _compute_quality_report

# Mock tool records with low quality
tool_records = [{
    "tool": "commerce.search_offers",
    "response": {
        "stats": {"raw_count": 15, "verified_count": 4, "rejected_count": 11},
        "rejected": [
            {"rejection_reasons": ["educational_resource"]},
            {"rejection_reasons": ["educational_resource"]},
            {"rejection_reasons": ["appears_to_be_cage"]},
            ...
        ]
    }
}]

report = _compute_quality_report(tool_records)

assert report.quality_score == 0.27  # 4/15
assert not report.meets_threshold
assert "educational" in report.suggested_refinement["add_negative_keywords"]
print("✓ Quality report generation working!")
```

---

## Future Enhancements

1. **Gateway Retry Loop**: Implement automatic refinement + retry in `gateway/app.py`
2. **Configurable Thresholds**: Per-domain quality thresholds (pricing: 0.3, docs: 0.5)
3. **Learning from History**: Track which refinements work best
4. **Multi-level Refinement**: Escalate from negative keywords → seller type → source domains
5. **Cost-Aware Retries**: Factor in API quota before retrying

---

## Files Modified

### Core Implementation
- ✅ `orchestrator/shared_state/schema.py` - Added `QualityReport` model
- ✅ `orchestrator/context_builder.py` - Added quality report generation
- ✅ `project_build_instructions/prompts/solver_system_v2.md` - Guide reflection protocol
- ✅ `project_build_instructions/prompts/thinking_system_v2.md` - Coordinator reflection protocol

### Documentation
- ✅ `project_build_instructions/docs/thinking_loops.md` - This document

### To Be Created (Future)
- ⏳ `gateway/app.py` - Retry loop implementation (commented pattern provided)
- ⏳ `.env.example` - Configuration parameters

---

## References

- **Iteration of Thought**: [arXiv:2409.12618](https://arxiv.org/abs/2409.12618)
- **Chain-of-Thought Prompting**: Improves LLM reasoning by making thinking explicit
- **Inner Dialogue**: Self-reflective prompting enhances decision quality

---

## Summary

The Thinking Loops system transforms the architecture from **reactive** (execute → return) to **reflective** (plan → act → review → adapt). This enables:

- **Smarter planning** with explicit reasoning
- **Quality-aware execution** that detects poor results
- **Adaptive refinement** that learns from failures
- **Transparent operation** with full audit trails

The system is **production-ready** for quality reporting. Gateway retry logic is **optional** and can be added when needed.
