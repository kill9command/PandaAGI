# Backtracking & Replanning Policy

**Version:** 1.1
**Updated:** 2026-02-03

---

## Overview

The Backtracking Policy defines **when and how the system abandons a failing plan, rewinds, and replans**. This is required for multi-goal tasks with step dependencies.

This policy is **planner-driven**: Validation issues, goal failures, or tool failures produce structured signals that force a replan.

---

## Triggers (When to Backtrack)

Backtrack when any of the following occur:

- **Requirement violation** (budget/scope/must-avoid from §0) detected in Phase 5 or Phase 7
- **Tool execution failure** that blocks progress (timeout, permission, missing tool)
- **Missing evidence** (validation says claims not supported)
- **Workflow mismatch** (validator indicates wrong workflow for user purpose)
- **Goal dependency failure** (downstream goals depend on failed prerequisite)

---

## Backtracking Levels

1. **Local Retry (same plan)**
   - Use when a tool failed transiently (timeout, intermittent errors).
2. **Partial Replan (same goals, new steps)**
   - Use when requirements are violated but goals remain feasible.
3. **Full Replan (new goals/approach)**
   - Use when requirements change or plan is infeasible.
4. **Clarify**
   - Use when requirements conflict or are missing/ambiguous.

---

## Policy Algorithm

1. **Phase 7 Validation** outputs `RETRY` with reason tags.
2. **Planner** reads the validation result and the current plan state.
3. Planner selects **backtracking level**:
   - Local Retry → keep goals, adjust steps
   - Partial Replan → keep goals, change approach
   - Full Replan → revise goals + approach
   - Clarify → ask user
4. Planner writes an updated STRATEGIC_PLAN and marks a new revision in the plan state so downstream phases detect the replan.

---

## Plan State

The system maintains plan state across replans, tracking:
- Goals and their statuses
- Retry history
- Last updated phase

A replan writes a **revision marker** so downstream phases can detect that the plan changed mid-turn.

---

## Validation Reason Tags

Phase 7 tags validation results with one or more:
- `requirement_violation`
- `tool_failure`
- `missing_evidence`
- `workflow_mismatch`
- `goal_dependency_failure`

The Planner uses these tags to choose the correct backtracking level.

---

## Related Documents

- `architecture/main-system-patterns/phase3-planner.md`
- `architecture/main-system-patterns/phase7-validation.md`
- `architecture/concepts/error_and_improvement_system/ERROR_HANDLING.md`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-03 | Initial specification |
| 1.1 | 2026-02-03 | Abstracted plan_state.json to concept. Fixed header formatting. Added changelog. |

---

**Last Updated:** 2026-02-03
