# Skill: Test-Driven Development (TDD)

**Source:** https://github.com/obra/superpowers/blob/main/skills/test-driven-development/SKILL.md

---

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn't watch the test fail, you don't know if it tests the right thing.

**Violating the letter of the rules is violating the spirit of the rules.**

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write code before the test? Delete it. Start over.

**No exceptions:**
- Don't keep it as "reference"
- Don't "adapt" it while writing tests
- Don't look at it
- Delete means delete

## Red-Green-Refactor Cycle

```
    ┌─────────┐
    │   RED   │  Write failing test
    └────┬────┘
         │ verify fails correctly
         ▼
    ┌─────────┐
    │  GREEN  │  Minimal code to pass
    └────┬────┘
         │ verify passes (all tests)
         ▼
    ┌─────────┐
    │REFACTOR │  Clean up (stay green)
    └────┬────┘
         │
         ▼
       NEXT
```

### RED - Write Failing Test

Write one minimal test showing what should happen.

**Good:**
```python
def test_retries_failed_operations_3_times():
    attempts = 0
    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise Exception('fail')
        return 'success'

    result = retry_operation(operation)

    assert result == 'success'
    assert attempts == 3
```

**Requirements:**
- One behavior
- Clear name
- Real code (no mocks unless unavoidable)

### Verify RED - Watch It Fail

**MANDATORY. Never skip.**

```bash
pytest path/to/test.py -v
```

Confirm:
- Test fails (not errors)
- Failure message is expected
- Fails because feature missing (not typos)

### GREEN - Minimal Code

Write simplest code to pass the test.

**Don't add:**
- Features not tested
- Refactoring of other code
- "Improvements" beyond the test

### Verify GREEN - Watch It Pass

**MANDATORY.**

Confirm:
- Test passes
- Other tests still pass
- Output pristine (no errors, warnings)

### REFACTOR - Clean Up

After green only:
- Remove duplication
- Improve names
- Extract helpers

**Keep tests green. Don't add behavior.**

## Why Order Matters

**"I'll write tests after to verify it works"**
- Tests written after pass immediately
- Passing immediately proves nothing
- You never saw it catch the bug

**"I already manually tested all edge cases"**
- Manual testing is ad-hoc
- No record of what you tested
- Can't re-run when code changes

**"Deleting X hours of work is wasteful"**
- Sunk cost fallacy
- The time is already gone
- Working code without real tests is technical debt

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Need to explore first" | Fine. Throw away exploration, start with TDD. |
| "Test hard = design unclear" | Hard to test = hard to use. |
| "TDD will slow me down" | TDD faster than debugging. |

## Red Flags - STOP and Start Over

- Code before test
- Test passes immediately
- Can't explain why test failed
- "Just this once"
- "Keep as reference"
- "Already spent X hours"

**All of these mean: Delete code. Start over with TDD.**

## Verification Checklist

Before marking work complete:

- [ ] Every new function/method has a test
- [ ] Watched each test fail before implementing
- [ ] Each test failed for expected reason
- [ ] Wrote minimal code to pass each test
- [ ] All tests pass
- [ ] Output pristine
- [ ] Tests use real code (mocks only if unavoidable)
- [ ] Edge cases and errors covered

## Final Rule

```
Production code → test exists and failed first
Otherwise → not TDD
```

No exceptions without explicit permission.
