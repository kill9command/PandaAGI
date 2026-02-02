# V2 Architecture Porting Analysis

**Purpose:** Identify features from Pandora v2 worth porting to the current system.

**Source:** `/home/henry/pythonprojects/pandaaiv2test/architecture/`

---

## Executive Summary

V2 represents a **simplification and formalization** of the current 8-phase system into a cleaner 6-phase design with better separation of concerns. The key innovations are:

1. **Workflow-centric execution** (no direct tool calls from PLAN)
2. **Forgiving kernel parsing** (semantic extraction, not rigid formats)
3. **Progressive memory loading** (one file per iteration)
4. **Constraint enforcement** (kernel validates between iterations)
5. **Confidence decay by content type** (prices decay faster than facts)

---

## Architecture Comparison

| Aspect | V1 (Current) | V2 |
|--------|--------------|-----|
| **Phases** | 8 (0-7) | 6 (§0-§5) |
| **Tool Execution** | Coordinator executes directly | Workflows define tool sequences |
| **Memory Loading** | Bulk load in Phase 2 | One file per GATHER iteration |
| **Format Parsing** | Strict (regex-based) | Forgiving (semantic fallbacks) |
| **Constraints** | Ad-hoc enforcement | Kernel validates between iterations |
| **Confidence** | Single decay rate | Content-type specific decay |
| **Self-Extension** | Not implemented | System creates own tools |

---

## Phase Mapping

```
V1 Current                          V2 Target
─────────────────────────────────────────────────────────
Phase 0: Query Analyzer      →      §0 UNDERSTAND (merged)
Phase 1: Reflection          ┐
Phase 2: Context Gatherer    ┘ →    §1 GATHER (combined)
Phase 3: Planner             ┐
Phase 4: Coordinator         ┘ →    §2 PLAN + Workflows
Phase 5: Synthesis           →      §3 SYNTHESIZE
Phase 6: Validation          →      §4 VALIDATE
Phase 7: Save                →      §5 SAVE
```

---

## Features Worth Porting

### 1. Workflow-Centric Execution (HIGH PRIORITY)

**Current Problem:** Coordinator makes ad-hoc tool decisions. Same query can trigger different tool sequences depending on LLM mood.

**V2 Solution:** PLAN selects workflows by name. Workflows are self-documenting markdown files that define predictable tool sequences.

```
V1 (Current):
  Planner → ticket.md (what to do)
  Coordinator → reads ticket, decides tools ad-hoc
                ↓
  Problem: Tool selection varies, hard to debug

V2 (Target):
  PLAN → "WORKFLOW: product_search {query: 'hamsters'}"
  Kernel → loads workflows/product_search.md
  Workflow Executor → executes defined tool sequence
                ↓
  Benefit: Same input = same tools, predictable, testable
```

**Migration Path:**
1. Create `apps/workflows/` directory
2. Convert common tool patterns to workflow markdown files
3. Modify Planner to emit workflow commands instead of tool decisions
4. Create Workflow Executor kernel component
5. Coordinator becomes the executor inside workflows

**Files to Create:**
- `apps/workflows/product_search.md`
- `apps/workflows/web_research.md`
- `apps/workflows/memory_lookup.md`
- `apps/workflows/code_edit.md`
- `libs/gateway/workflow_executor.py`
- `libs/gateway/workflow_matcher.py`

---

### 2. Forgiving Kernel Parsing (HIGH PRIORITY)

**Current Problem:** LLM outputs that don't match exact format cause parse failures. LLM wastes tokens on formatting instead of thinking.

**V2 Solution:** Parse semantically with fallback patterns.

```python
# V1 (Current) - Rigid
def parse_plan(output):
    match = re.search(r"### Status: (COMPLETE|WORKFLOW)", output)
    if not match:
        raise ParseError("Missing status header")  # FAIL

# V2 (Target) - Forgiving
def parse_plan(output):
    # Try structured first
    if match := re.search(r"### Status: (\w+)", output):
        return match.group(1)
    # Fall back to semantic extraction
    if "complete" in output.lower() and "need" not in output.lower():
        return "COMPLETE"
    if "workflow" in output.lower() or "search" in output.lower():
        return "WORKFLOW"
    # Sensible default
    return "CONTINUE"
```

**Migration Path:**
1. Audit all `extract_*` functions in `libs/gateway/`
2. Add semantic fallback patterns
3. Log format mismatches (don't fail, but track)
4. Reduce format requirements in prompts

**Files to Modify:**
- `libs/llm/response_parser.py`
- `libs/gateway/unified_flow.py` (per-phase parsers)
- `apps/prompts/**/*.md` (reduce format strictness)

---

### 3. Progressive Memory Loading (MEDIUM PRIORITY)

**Current Problem:** Phase 2 loads all relevant context at once, potentially exceeding token budgets or diluting attention.

**V2 Solution:** GATHER iterates - one file per iteration, distills, then requests next.

```
V1 (Current):
  Phase 2 Retrieval → "Here are 5 relevant memories"
  Phase 2 Load → Loads all 5 files at once (~15K tokens)
  Phase 2 Synthesis → Extracts from massive context
                ↓
  Problem: Token overflow, diluted attention

V2 (Target):
  GATHER Iter 1 → See index, request file A
  GATHER Iter 2 → Distill A to notes, request file B
  GATHER Iter 3 → Merge notes, request file C
  GATHER Done → Pass distilled context (~2K tokens)
                ↓
  Benefit: Each file gets full attention, stays in budget
```

**Migration Path:**
1. Modify Phase 2 to iterate (max 5 files)
2. Add distillation step between file loads
3. Pass distilled notes forward, not raw content
4. Set hard limit: one file per iteration

**Files to Modify:**
- `libs/gateway/unified_flow.py` (Phase 2 loop)
- `apps/prompts/pipeline/context_gatherer.md`
- `libs/gateway/context_document.py` (distillation)

---

### 4. Constraint Declaration & Enforcement (MEDIUM PRIORITY)

**Current Problem:** Budget/time constraints mentioned in query but not tracked. LLM might ignore "under $200" mid-research.

**V2 Solution:** PLAN declares constraints. Kernel enforces between iterations.

```yaml
# V2 Constraint Declaration (from PLAN output)
Constraints:
  - budget: 200 USD
  - min_sources: 3
  - duration: 5 days
```

```python
# V2 Kernel Enforcement (between PLAN iterations)
def check_constraints(constraints, current_results):
    for product in current_results:
        if product.price > constraints.budget:
            return Feedback(
                violation="budget exceeded",
                message=f"Product costs ${product.price}, budget is ${constraints.budget}"
            )
    return None  # OK to continue
```

**Migration Path:**
1. Add constraint extraction to Planner output
2. Create `libs/gateway/constraint_manager.py`
3. Add constraint check between Coordinator iterations
4. Feed violations back to PLAN with guidance

**Files to Create:**
- `libs/gateway/constraint_manager.py`

**Files to Modify:**
- `apps/prompts/pipeline/planner.md` (add constraint declaration)
- `libs/gateway/unified_flow.py` (add enforcement hooks)

---

### 5. Content-Type Confidence Decay (MEDIUM PRIORITY)

**Current Problem:** All confidence scores decay at same rate. Price from yesterday treated same as product spec from yesterday.

**V2 Solution:** Decay rate depends on content type.

```python
# V2 Decay Rates
DECAY_RATES = {
    "availability": 0.20,  # 20%/day - very volatile
    "price": 0.10,         # 10%/day - changes often
    "product_spec": 0.03,  # 3%/day - rarely changes
    "preference": 0.005,   # 0.5%/day - very stable
}

def apply_decay(claim):
    age_days = (now - claim.extracted_at).days
    decay_rate = DECAY_RATES.get(claim.content_type, 0.05)
    claim.confidence *= (1 - decay_rate) ** age_days
    return claim
```

**Migration Path:**
1. Add `content_type` field to claim schema
2. Modify research extraction to classify content types
3. Apply type-specific decay in quality scoring
4. Update validation thresholds

**Files to Modify:**
- `libs/gateway/claims.py` (add content_type)
- `apps/services/orchestrator/internet_research_mcp.py` (classify types)
- `libs/gateway/quality_scoring.py` (apply decay)

---

### 6. Per-Phase Self-Validation (LOW PRIORITY)

**Current Problem:** Phase 6 (Validation) catches all errors. Early phases don't self-correct.

**V2 Solution:** Each phase has lightweight validation with 1x retry before escalation.

```python
# V2 Per-Phase Validation
def run_phase_understand(query):
    output = llm_call(understand_prompt, query)
    result = parse_understand(output)

    if not validate_understand(result):
        # Retry once with feedback
        output = llm_call(understand_prompt, query, feedback="Missing resolved query")
        result = parse_understand(output)

    if not validate_understand(result):
        # Only now escalate
        raise PhaseValidationError("UNDERSTAND failed after retry")

    return result
```

**Migration Path:**
1. Add `validate_*` functions for each phase
2. Add retry logic to phase runners
3. Track retry counts per phase
4. Escalate to Phase 6 only after phase-level retries exhausted

**Files to Create:**
- `libs/gateway/phase_validators.py`

**Files to Modify:**
- `libs/gateway/unified_flow.py` (add per-phase retry)

---

### 7. Self-Extension: System Creates Tools (LOW PRIORITY)

**Current Problem:** Adding new capabilities requires developer intervention.

**V2 Solution:** System recognizes missing capability and creates it through the same pipeline.

```
User: "I need to analyze GitHub repos"
  ↓
UNDERSTAND: New capability needed
  ↓
PLAN: Route = self-extend, Action = CREATE_TOOL
  ↓
Workflow: research_apis → code_generate → sandbox_test → tool_register
  ↓
New tool available for future queries
```

**5 Bootstrap Tools (cannot be self-created):**
1. Code Sandbox
2. Context Guard
3. Constraint Manager
4. File I/O
5. Tool Registry

**Migration Path:** This is a major feature. Defer until core improvements are stable.

---

## Features NOT Worth Porting

### 1. 6-Phase Reduction

**Why Not:** V1's 8 phases provide more granular control. The extra phases (Reflection, Planner separate from Coordinator) give better debugging and audit trails. Don't simplify just for simplicity.

### 2. Turn.md vs context.md

**Why Not:** V1's context.md pattern is equivalent. Just naming difference.

### 3. Qwen3-4B vs Qwen3-Coder-30B

**Why Not:** V1's larger model is better for coding tasks. V2's smaller model is a hardware constraint, not a feature.

---

## Implementation Priority

### Phase 1: Foundation (Weeks 1-2)
1. **Forgiving Kernel Parsing** - Immediate benefit, low risk
2. **Content-Type Confidence Decay** - Simple enhancement

### Phase 2: Execution Model (Weeks 3-4)
3. **Workflow-Centric Execution** - Major architectural change
4. **Constraint Declaration & Enforcement** - Pairs with workflows

### Phase 3: Memory Optimization (Weeks 5-6)
5. **Progressive Memory Loading** - Requires Phase 2 changes
6. **Per-Phase Self-Validation** - Polish

### Phase 4: Advanced (Future)
7. **Self-Extension** - Major feature, defer

---

## Migration Risks

| Risk | Mitigation |
|------|------------|
| Workflow abstraction slows development | Start with 5 common workflows, expand gradually |
| Forgiving parsing masks real errors | Log all fallback usage, review weekly |
| Progressive loading increases latency | Set max iterations (5), profile |
| Constraint enforcement too strict | Allow soft violations with warnings |

---

## Open Questions

1. **Workflow granularity:** Should `product_search` be one workflow or `search + extract + validate`?

2. **Memory iteration limit:** V2 uses max 5 files. Is that enough for complex research queries?

3. **Constraint types:** What constraints beyond budget/duration? Quality thresholds? Source counts?

4. **Self-extension scope:** Which tools should be self-creatable vs bootstrap? Where's the line?

---

## Next Steps

1. **Review this document** - Discuss with team, adjust priorities
2. **Prototype workflows** - Create 3 workflow files, test pattern
3. **Audit parsing code** - Find rigid parsers, plan semantic fallbacks
4. **Add content_type to claims** - Quick win for decay improvement

---

**Document Version:** 1.0
**Created:** 2026-02-02
**Based On:** pandaaiv2test/architecture/ analysis
