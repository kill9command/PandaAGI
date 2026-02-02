# Skill: Subagent-Driven Development

**Source:** https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md

---

## Overview

Execute plan by dispatching fresh subagent per task, with two-stage review after each: spec compliance review first, then code quality review.

**Core principle:** Fresh subagent per task + two-stage review (spec then quality) = high quality, fast iteration

## When to Use

- Have implementation plan? YES
- Tasks mostly independent? YES
- Stay in this session? YES → subagent-driven-development

If tasks are tightly coupled or you need parallel sessions → use executing-plans instead.

## The Process

```
1. Read plan, extract all tasks with full text
2. Create TodoWrite with all tasks

PER TASK:
3. Dispatch implementer subagent with full task text + context
4. If questions → answer, re-dispatch
5. Implementer: implements, tests, commits, self-reviews
6. Dispatch spec reviewer subagent
7. If spec gaps → implementer fixes, re-review
8. Dispatch code quality reviewer subagent
9. If quality issues → implementer fixes, re-review
10. Mark task complete
11. Repeat for next task

AFTER ALL TASKS:
12. Dispatch final code reviewer for entire implementation
13. Use finishing-a-development-branch skill
```

## Prompt Templates

Three specialized prompts:
- `implementer-prompt.md` - Does the actual work
- `spec-reviewer-prompt.md` - Checks code matches requirements
- `code-quality-reviewer-prompt.md` - Checks code is well-written

## Two-Stage Review

**Stage 1: Spec Compliance**
- Does code match the specification?
- Nothing missing?
- Nothing extra (over-engineering)?

**Stage 2: Code Quality**
- Is the code well-written?
- Test coverage adequate?
- No magic numbers, good naming, etc.?

## Advantages

**vs. Manual execution:**
- Subagents follow TDD naturally
- Fresh context per task (no confusion)
- Parallel-safe (subagents don't interfere)
- Subagent can ask questions before AND during work

**Quality gates:**
- Self-review catches issues before handoff
- Spec compliance prevents over/under-building
- Code quality ensures implementation is solid
- Review loops ensure fixes actually work

**Cost trade-off:**
- More subagent invocations (implementer + 2 reviewers per task)
- Controller does more prep work
- But catches issues early (cheaper than debugging later)

## Example Flow

```
Task 1: Hook installation script

[Dispatch implementer with full task text]
Implementer: "Should hook be user or system level?"
You: "User level (~/.config/)"
Implementer: "Implementing..." → commits

[Dispatch spec reviewer]
Spec reviewer: ✅ All requirements met

[Dispatch code quality reviewer]
Code reviewer: ✅ Approved

[Mark Task 1 complete, move to Task 2...]
```
