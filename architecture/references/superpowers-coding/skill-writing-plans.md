# Skill: Writing Plans

**Source:** https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md

---

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for our codebase and questionable taste. Document everything they need to know: which files to touch for each task, code, testing, docs they might need to check, how to test it.

**Assume:** Skilled developer, but knows almost nothing about our toolset or problem domain. Assume they don't know good test design very well.

**Principles:** DRY. YAGNI. TDD. Frequent commits.

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" - step
- "Run it to make sure it fails" - step
- "Implement the minimal code to make the test pass" - step
- "Run the tests and make sure they pass" - step
- "Commit" - step

## Plan Document Header

Every plan MUST start with:

```markdown
# [Feature Name] Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

## Task Structure Template

```markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

**Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

**Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
```

## Key Requirements

- **Exact file paths always** - No "in the appropriate file"
- **Complete code in plan** - Not "add validation" but actual code
- **Exact commands with expected output** - Not "run tests" but full command
- **Reference relevant skills** - With @ syntax
- **DRY, YAGNI, TDD** - Always

## Execution Handoff

After saving the plan, offer execution choice:

**1. Subagent-Driven (this session)**
- Fresh subagent per task
- Review between tasks
- Fast iteration

**2. Parallel Session (separate)**
- Open new session in worktree
- Batch execution with checkpoints
