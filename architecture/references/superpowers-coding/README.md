# Superpowers - Agentic Skills Framework

**Source:** https://github.com/obra/superpowers
**Author:** Jesse Vincent (obra)
**License:** MIT

## Overview

Superpowers is a composable skills framework for AI coding agents (Claude Code, Codex, OpenCode). Instead of letting agents jump straight into writing code, it enforces a structured workflow:

1. **Understand** - Ask clarifying questions, explore alternatives
2. **Design** - Present design in digestible chunks for approval
3. **Plan** - Create detailed implementation plans with exact file paths and code
4. **Execute** - Dispatch subagents per task with two-stage review
5. **Verify** - Enforce TDD, verify before claiming completion

## Core Philosophy

> "Your coding agent just has Superpowers" - skills activate automatically, no special commands needed.

Key principles:
- **Test-Driven Development** - Write tests first, always
- **Systematic over ad-hoc** - Process over guessing
- **Complexity reduction** - Simplicity as primary goal
- **Evidence over claims** - Verify before declaring success
- **YAGNI** - You Aren't Gonna Need It

## The Basic Workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. BRAINSTORMING                                                    │
│     - Ask questions one at a time                                    │
│     - Explore 2-3 approaches with trade-offs                         │
│     - Present design in 200-300 word sections                        │
│     - Save to docs/plans/YYYY-MM-DD-<topic>-design.md               │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  2. GIT WORKTREES                                                    │
│     - Create isolated workspace on new branch                        │
│     - Run project setup (npm install, etc.)                          │
│     - Verify clean test baseline                                     │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  3. WRITING PLANS                                                    │
│     - Bite-sized tasks (2-5 minutes each)                            │
│     - Exact file paths, complete code                                │
│     - Verification steps for each task                               │
│     - TDD steps: write test → verify fail → implement → verify pass  │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  4. SUBAGENT-DRIVEN DEVELOPMENT                                      │
│     - Fresh subagent per task (no context pollution)                 │
│     - Two-stage review: spec compliance → code quality               │
│     - Implementer → Spec Reviewer → Code Reviewer                    │
│     - Mark task complete, move to next                               │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  5. FINISHING                                                        │
│     - Verify all tests pass                                          │
│     - Options: merge/PR/keep/discard                                 │
│     - Clean up worktree                                              │
└─────────────────────────────────────────────────────────────────────┘
```

## Skills Library

### Testing & Quality
- `test-driven-development` - RED-GREEN-REFACTOR cycle
- `verification-before-completion` - Evidence before claims
- `systematic-debugging` - 4-phase root cause analysis

### Collaboration & Planning
- `brainstorming` - Socratic design refinement
- `writing-plans` - Detailed implementation breakdown
- `subagent-driven-development` - Fresh subagent per task + review
- `executing-plans` - Batch execution with checkpoints

### Git & Workflow
- `using-git-worktrees` - Isolated parallel branches
- `finishing-a-development-branch` - Merge/PR decisions
- `requesting-code-review` / `receiving-code-review`

### Meta
- `writing-skills` - Create new skills
- `using-superpowers` - System introduction

## Key Documents in This Folder

| File | Description |
|------|-------------|
| `README.md` | This overview |
| `skill-brainstorming.md` | Design refinement workflow |
| `skill-subagent-development.md` | Per-task subagent execution |
| `skill-writing-plans.md` | Implementation plan format |
| `skill-tdd.md` | Test-driven development rules |
| `skill-systematic-debugging.md` | 4-phase debugging methodology |
| `skill-verification.md` | Verification before completion |

## Relevance to Pandora

### Patterns We Already Use
- **Document-based state** - Pandora uses context.md, superpowers uses research_state.md
- **Phase-based workflow** - Both have sequential phases with gates
- **LLM-driven decisions** - Both let the LLM decide next actions

### Patterns Worth Considering
- **Two-stage review** - Spec compliance + code quality as separate reviews
- **Fresh context per task** - Subagents don't inherit pollution from prior tasks
- **Bite-sized tasks** - 2-5 minute tasks with exact verification steps
- **Evidence before claims** - Never claim success without running verification

### Patterns That Don't Apply
- **Subagent dispatching** - Pandora is a single-session system
- **Git worktrees** - Pandora isn't a code development agent
- **TDD enforcement** - Pandora generates responses, not code

## Notable Quotes

> "If you didn't watch the test fail, you don't know if it tests the right thing."

> "Claiming work is complete without verification is dishonesty, not efficiency."

> "3+ fixes failed? Question the architecture."

> "YAGNI ruthlessly - Remove unnecessary features from all designs."

---

**Retrieved:** 2026-01-24
