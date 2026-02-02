# Implementation Plan: Superpowers for Pandora Code Mode

**Created:** 2026-01-24
**Status:** PROPOSAL

---

## Executive Summary

This plan outlines how to integrate superpowers-style workflows into Pandora's code mode. The goal is to make Pandora's code mode more disciplined: ask before coding, test before implementing, verify before claiming done.

**Key Question:** Is this as good or better than Claude Code?

**Answer:** With these enhancements, Pandora would be **comparable to Claude Code + Superpowers plugin**, with some unique advantages:
- Richer context pipeline (8-phase document flow vs ad-hoc)
- Built-in research capabilities (internet.research, memory)
- Structured permission validation
- Quality-over-speed philosophy already embedded

---

## Gap Analysis: Current vs Superpowers

| Capability | Superpowers | Pandora Current | Gap |
|------------|-------------|-----------------|-----|
| **Brainstorming** | Ask questions one at a time, explore 2-3 approaches | Jumps to planning | ❌ Missing |
| **Design Docs** | Save to docs/plans/YYYY-MM-DD-topic.md | None | ❌ Missing |
| **Bite-sized Tasks** | 2-5 minute steps with exact code | High-level natural language | ⚠️ Partial |
| **TDD Enforcement** | Write test → verify fail → implement → verify pass | Test-after-edit only | ⚠️ Partial |
| **Systematic Debugging** | 4-phase root cause methodology | No structured approach | ❌ Missing |
| **Verification Before Completion** | Evidence before claims, always | Implicit in synthesis | ⚠️ Partial |
| **Two-Stage Review** | Spec compliance + code quality | Single-pass synthesis | ❌ Missing |
| **Git Worktrees** | Isolated workspaces | Not applicable (single repo) | N/A |
| **Subagent Dispatch** | Fresh context per task | Agent loop (same context) | Different approach |

---

## Proposed Architecture

### Option A: Prompt-Only Enhancement (Recommended)

Modify existing prompts to enforce superpowers patterns. No code changes.

**Pros:**
- Zero implementation risk
- Can iterate quickly
- Respects existing token budgets
- No new phases or complexity

**Cons:**
- LLM compliance is probabilistic
- Can't enforce hard gates

### Option B: Phase Additions

Add new phases for brainstorming and verification.

**Pros:**
- Hard enforcement
- Clear audit trail

**Cons:**
- Breaks 8-phase architecture
- Increases latency
- Requires significant code changes

### Recommendation: **Option A** with strategic prompt enhancements

---

## Implementation Plan (Option A)

### Files to Modify (Code Mode Only)

| File | Purpose | Chat Mode Equivalent (NOT touched) |
|------|---------|-----------------------------------|
| `apps/prompts/planner/code_strategic.md` | Code mode planning | `strategic.md` |
| `apps/prompts/coordinator/code_operations_enhanced.md` | Code mode coordination | `core.md` |
| `apps/prompts/synthesizer/code_synthesis.md` | Code mode synthesis | `synthesis.md` |

**Chat mode prompts are NOT modified.** All changes are isolated to code mode.

---

### Phase 1: Brainstorming Gate in Planner

**File:** `apps/prompts/planner/code_strategic.md` (CODE MODE ONLY)

**Change:** Add brainstorming trigger for feature requests.

```markdown
## Brainstorming Gate (Feature Requests Only)

When the query is a feature request (not exploration or bug fix):

### Step 0: Check if Design Exists
- Does §1 contain a design document for this feature?
- If YES → proceed to planning
- If NO → trigger brainstorming

### Brainstorming Output
If brainstorming needed, output:
```json
{
  "_type": "TICKET",
  "route_to": "brainstorm",
  "questions": [
    "What should happen when X fails?",
    "Should this support Y or Z?"
  ],
  "approaches": [
    {"name": "Approach A", "pros": "...", "cons": "..."},
    {"name": "Approach B", "pros": "...", "cons": "..."}
  ],
  "recommendation": "Approach A because..."
}
```

The system will:
1. Present questions to user one at a time
2. After answers, present design in 200-300 word sections
3. Save approved design to docs/plans/
4. Re-enter planner with design context
```

**Estimated tokens:** +400 to planner prompt

---

### Phase 2: TDD Enforcement in Coordinator

**File:** `apps/prompts/coordinator/code_operations_enhanced.md` (CODE MODE ONLY)

**Change:** Add TDD patterns and enforcement.

```markdown
## TDD Enforcement (MANDATORY for Code Changes)

### The Iron Law
```
NO IMPLEMENTATION WITHOUT A FAILING TEST FIRST
```

### TDD Workflow Pattern
For ANY code change (feature, fix, refactor):

```json
{
  "_type": "PLAN",
  "subtasks": [
    {"tool": "file.write", "file_path": "tests/test_new_feature.py", "content": "...", "why": "RED: write failing test"},
    {"tool": "code.verify_suite", "target": "tests/test_new_feature.py", "why": "RED: verify test fails"},
    {"tool": "file.edit", "file_path": "src/feature.py", "why": "GREEN: minimal implementation"},
    {"tool": "code.verify_suite", "target": "tests/test_new_feature.py", "why": "GREEN: verify test passes"},
    {"tool": "git.diff", "repo": ".", "why": "capture changes"}
  ]
}
```

### Verification Steps
- After "RED: write failing test" → test MUST fail
- If test passes immediately → flag as error, test is wrong
- After "GREEN: minimal implementation" → test MUST pass
- If test still fails → debug, don't add more code
```

**Estimated tokens:** +600 to coordinator prompt

---

### Phase 3: Systematic Debugging Methodology

**File:** `apps/prompts/coordinator/code_operations_enhanced.md` (CODE MODE ONLY)

**Change:** Add debugging workflow when tests fail.

```markdown
## Systematic Debugging (When Tests Fail)

### The Iron Law
```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

### Debugging Workflow Pattern
When `code.verify_suite` returns failures:

```json
{
  "_type": "PLAN",
  "subtasks": [
    {"tool": "file.read", "file_path": "...", "why": "Phase 1: read error message carefully"},
    {"tool": "git.diff", "repo": ".", "why": "Phase 1: check recent changes"},
    {"tool": "file.grep", "pattern": "...", "why": "Phase 2: find working examples"},
    {"tool": "file.edit", "file_path": "...", "why": "Phase 4: single minimal fix"},
    {"tool": "code.verify_suite", "target": "...", "why": "Phase 4: verify fix"}
  ],
  "notes": {
    "debugging_phase": 1,
    "hypothesis": "X is the root cause because Y",
    "fix_attempts": 0
  }
}
```

### 3+ Fix Attempts Rule
If `fix_attempts >= 3`:
- STOP fixing
- Report to user: "3+ fixes failed. This may be an architectural issue."
- Ask for guidance before continuing
```

**Estimated tokens:** +500 to coordinator prompt

---

### Phase 4: Verification Before Completion in Synthesis

**File:** `apps/prompts/synthesizer/code_synthesis.md` (CODE MODE ONLY)

**Change:** Require evidence before success claims.

```markdown
## Verification Before Completion (MANDATORY)

### The Iron Law
```
NO SUCCESS CLAIMS WITHOUT VERIFICATION EVIDENCE
```

### Required Evidence
Before ANY success claim, you MUST have in §4:
- Test output showing pass/fail counts
- git.diff output showing actual changes
- lint/typecheck output (if applicable)

### Evidence Format
```markdown
## Verification Results

**Tests:** ✅ 12 passed (output from code.verify_suite)
**Changes:** 3 files modified (output from git.diff)
**Lint:** ✅ No issues (output from code.verify_suite with lint=true)
```

### Forbidden Phrases
NEVER use without evidence in §4:
- "Should work now"
- "This should fix it"
- "Tests should pass"
- "Done" / "Complete" / "Fixed"

ALWAYS use with evidence:
- "Tests pass: 12/12 (see verification output)"
- "Fix verified: test_login now passes"
- "Changes committed: abc123"
```

**Estimated tokens:** +300 to synthesis prompt

---

### Phase 5: Design Documentation

**File:** `apps/prompts/planner/code_strategic.md` (CODE MODE ONLY)

**Change:** Save designs to docs/plans/.

```markdown
## Design Documentation

After brainstorming approval, save design:

```json
{
  "_type": "TICKET",
  "route_to": "coordinator",
  "tasks": [
    {"task": "Create design document", "why": "Document approved design"},
    {"task": "Implement feature per design", "why": "Execute approved plan"}
  ],
  "design_doc": {
    "path": "docs/plans/2026-01-24-feature-name.md",
    "content": "# Feature Name\n\n## Goal\n...\n\n## Architecture\n..."
  }
}
```

The Coordinator will:
1. Write design doc with `file.write`
2. Commit design doc
3. Proceed with implementation
```

**Estimated tokens:** +200 to planner prompt

---

## Token Budget Analysis

| Phase | Current | After Enhancement | Delta |
|-------|---------|-------------------|-------|
| Planner (code) | 1,400 prompt | 2,000 prompt | +600 |
| Coordinator (code) | 4,659 prompt | 5,759 prompt | +1,100 |
| Synthesis (code) | 1,130 prompt | 1,430 prompt | +300 |
| **Total** | 7,189 | 9,189 | **+2,000** |

**Impact:** Fits within existing budgets (coordinator has 12,000 total budget).

---

## Comparison: Pandora + Superpowers vs Claude Code

| Aspect | Claude Code | Pandora + Superpowers |
|--------|-------------|----------------------|
| **Brainstorming** | Via superpowers plugin | Built into planner prompt |
| **TDD Enforcement** | Via superpowers plugin | Built into coordinator prompt |
| **Debugging** | Via superpowers plugin | Built into coordinator prompt |
| **Verification** | Via superpowers plugin | Built into synthesis prompt |
| **Context Pipeline** | Ad-hoc tool calls | Structured 8-phase flow |
| **Research** | Web search tools | Full internet.research with caching |
| **Memory** | MCP servers | Built-in turn/session/forever memory |
| **Permission Model** | Bash allow rules | 4-layer defense-in-depth |
| **Hardware** | Anthropic cloud | Local RTX 3090 (Qwen3-30B) |
| **Cost** | API usage fees | Local compute only |

**Verdict:** With these enhancements, Pandora would have **superpowers-equivalent capabilities** with additional advantages in context management, memory, and cost.

---

## Implementation Order

1. **Phase 4 (Verification)** - Easiest, highest impact
2. **Phase 2 (TDD)** - Medium complexity, enforces test-first
3. **Phase 3 (Debugging)** - Medium complexity, helps when stuck
4. **Phase 1 (Brainstorming)** - Higher complexity, requires flow changes
5. **Phase 5 (Documentation)** - Nice-to-have, can defer

---

## Risks

| Risk | Mitigation |
|------|------------|
| Prompt bloat | Monitor token usage, compress if needed |
| LLM non-compliance | Add examples, test iteratively |
| Increased latency | Acceptable for quality-over-speed philosophy |
| Brainstorming friction | Make it optional for small changes |

---

## Success Criteria

1. **TDD compliance:** 80%+ of code changes follow RED-GREEN pattern
2. **Verification compliance:** 100% of success claims have evidence
3. **Debugging efficiency:** <3 fix attempts for most bugs
4. **User satisfaction:** Reduced "that didn't work" follow-ups

---

## Next Steps

1. Review this plan
2. Decide: Implement all phases or start with subset?
3. Implement Phase 4 (Verification) first as proof of concept
4. Iterate based on results

---

**Author:** Analysis based on superpowers framework and Pandora code mode architecture
