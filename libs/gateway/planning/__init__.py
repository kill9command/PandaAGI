"""
Pandora Planning Module - Plan state, goal management, and backtracking.

Implements Phase 3 (Planner) support infrastructure:
- Plan state persistence (plan_state.json)
- Goal normalization and tracking
- Constraint violation recording
- Backtracking strategies for validation failures

Architecture Reference:
    architecture/concepts/main-system-patterns/phase3-planner.md

Design Notes:
- PlanStateManager.check_constraints_for_tool() uses string matching which
  could be refactored to consume workflow constraint metadata instead
- BacktrackingPlanner defines default strategies per constraint type; these
  are sensible defaults but could be made LLM-driven or workflow-defined
- Phase numbering in violation records uses legacy stages; the concepts
  (constraint violation, retry) map correctly to current architecture

Contains:
- PlanStateManager: Goal tracking, constraint validation, violation recording
- BacktrackingPlanner: Replanning engine for constraint violations
"""

from libs.gateway.planning.plan_state import PlanStateManager, get_plan_state_manager
from libs.gateway.planning.backtracking import (
    BacktrackingPlanner,
    BacktrackStrategy,
    BacktrackDecision,
    PlanExecutionState,
    Violation,
    get_backtracking_planner,
)

__all__ = [
    "PlanStateManager",
    "get_plan_state_manager",
    "BacktrackingPlanner",
    "BacktrackStrategy",
    "BacktrackDecision",
    "PlanExecutionState",
    "Violation",
    "get_backtracking_planner",
]
