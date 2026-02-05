"""
Backtracking Planner - Replanning engine for constraint violations.

Implements DeepPlanning backtracking capabilities:
1. Detect violations during plan execution
2. Decide backtracking strategy (replan, skip, abort)
3. Modify plan to avoid violations
4. Track backtracking history for learning

Architecture Reference:
- architecture/BENCHMARK_ALIGNMENT.md (M5)
- architecture/concepts/CONSTRAINT_MANAGER.md
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.persistence.turn_manager import TurnDirectory

logger = logging.getLogger(__name__)


class BacktrackStrategy(Enum):
    """Strategy for handling constraint violations."""
    SKIP_STEP = "skip_step"           # Skip the violating step, continue
    REPLAN = "replan"                 # Generate alternative plan
    SUBSTITUTE = "substitute"         # Replace with alternative step
    ABORT = "abort"                   # Abort entire plan
    RETRY_WITH_PARAMS = "retry"       # Retry with modified parameters


@dataclass
class Violation:
    """Recorded constraint violation."""
    constraint_id: str
    constraint_type: str
    step_index: int
    step_action: str
    reason: str
    timestamp: str = ""
    recoverable: bool = True


@dataclass
class BacktrackDecision:
    """Decision on how to handle a violation."""
    strategy: BacktrackStrategy
    violation: Violation
    modified_step: Optional[Dict[str, Any]] = None
    skip_to_step: Optional[int] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "violation": {
                "constraint_id": self.violation.constraint_id,
                "constraint_type": self.violation.constraint_type,
                "step_index": self.violation.step_index,
                "step_action": self.violation.step_action,
                "reason": self.violation.reason,
                "recoverable": self.violation.recoverable,
            },
            "modified_step": self.modified_step,
            "skip_to_step": self.skip_to_step,
            "reason": self.reason,
        }


@dataclass
class PlanExecutionState:
    """State of plan execution with backtracking support."""
    steps: List[Dict[str, Any]]
    current_step: int = 0
    completed_steps: List[int] = field(default_factory=list)
    skipped_steps: List[int] = field(default_factory=list)
    violations: List[Violation] = field(default_factory=list)
    backtrack_decisions: List[BacktrackDecision] = field(default_factory=list)
    max_backtracks: int = 3
    backtrack_count: int = 0
    aborted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_step": self.current_step,
            "total_steps": len(self.steps),
            "completed_steps": self.completed_steps,
            "skipped_steps": self.skipped_steps,
            "violations": [
                {
                    "constraint_id": v.constraint_id,
                    "step_index": v.step_index,
                    "reason": v.reason,
                }
                for v in self.violations
            ],
            "backtrack_count": self.backtrack_count,
            "max_backtracks": self.max_backtracks,
            "aborted": self.aborted,
        }


class BacktrackingPlanner:
    """
    Planner with backtracking support for constraint violations.

    Features:
    - Monitors plan execution for violations
    - Decides backtracking strategy per constraint type
    - Modifies plans to satisfy constraints
    - Tracks backtracking history
    """

    # Default strategies per constraint type
    DEFAULT_STRATEGIES = {
        "budget": BacktrackStrategy.SUBSTITUTE,      # Find cheaper alternative
        "file_size": BacktrackStrategy.RETRY_WITH_PARAMS,  # Reduce output
        "time": BacktrackStrategy.SKIP_STEP,         # Skip slow steps
        "availability": BacktrackStrategy.SUBSTITUTE, # Find available alternative
        "location": BacktrackStrategy.SUBSTITUTE,    # Find nearby alternative
        "privacy": BacktrackStrategy.SKIP_STEP,      # Skip external calls
        "must_avoid": BacktrackStrategy.SUBSTITUTE,  # Find alternative
    }

    def __init__(
        self,
        max_backtracks: int = 3,
        strategies: Optional[Dict[str, BacktrackStrategy]] = None,
    ):
        """
        Initialize backtracking planner.

        Args:
            max_backtracks: Maximum backtrack attempts before abort
            strategies: Custom strategies per constraint type
        """
        self.max_backtracks = max_backtracks
        self.strategies = {**self.DEFAULT_STRATEGIES, **(strategies or {})}

    def create_execution_state(
        self,
        steps: List[Dict[str, Any]],
    ) -> PlanExecutionState:
        """Create initial execution state for a plan."""
        return PlanExecutionState(
            steps=steps,
            max_backtracks=self.max_backtracks,
        )

    def handle_violation(
        self,
        state: PlanExecutionState,
        constraint_id: str,
        constraint_type: str,
        reason: str,
        step_index: Optional[int] = None,
    ) -> BacktrackDecision:
        """
        Handle a constraint violation during execution.

        Args:
            state: Current execution state
            constraint_id: ID of violated constraint
            constraint_type: Type of constraint (budget, time, etc.)
            reason: Description of violation
            step_index: Index of violating step (default: current)

        Returns:
            BacktrackDecision with strategy and modifications
        """
        step_idx = step_index if step_index is not None else state.current_step
        step = state.steps[step_idx] if step_idx < len(state.steps) else {}
        step_action = step.get("action", step.get("tool", "unknown"))

        # Record violation
        violation = Violation(
            constraint_id=constraint_id,
            constraint_type=constraint_type,
            step_index=step_idx,
            step_action=step_action,
            reason=reason,
            recoverable=state.backtrack_count < state.max_backtracks,
        )
        state.violations.append(violation)

        # Check if we've exceeded max backtracks
        if state.backtrack_count >= state.max_backtracks:
            decision = BacktrackDecision(
                strategy=BacktrackStrategy.ABORT,
                violation=violation,
                reason=f"Exceeded max backtracks ({state.max_backtracks})",
            )
            state.aborted = True
            state.backtrack_decisions.append(decision)
            logger.warning(
                f"[BacktrackingPlanner] Aborting: exceeded max backtracks "
                f"({state.backtrack_count}/{state.max_backtracks})"
            )
            return decision

        # Get strategy for this constraint type
        strategy = self.strategies.get(constraint_type, BacktrackStrategy.SKIP_STEP)

        # Create decision based on strategy
        decision = self._create_decision(state, violation, strategy, step)

        state.backtrack_count += 1
        state.backtrack_decisions.append(decision)

        logger.info(
            f"[BacktrackingPlanner] Handling violation: {constraint_type} "
            f"-> {strategy.value} (backtrack {state.backtrack_count}/{state.max_backtracks})"
        )

        return decision

    def _create_decision(
        self,
        state: PlanExecutionState,
        violation: Violation,
        strategy: BacktrackStrategy,
        step: Dict[str, Any],
    ) -> BacktrackDecision:
        """Create a backtrack decision based on strategy."""

        if strategy == BacktrackStrategy.SKIP_STEP:
            return BacktrackDecision(
                strategy=strategy,
                violation=violation,
                skip_to_step=violation.step_index + 1,
                reason=f"Skipping step {violation.step_index} due to {violation.constraint_type} constraint",
            )

        elif strategy == BacktrackStrategy.RETRY_WITH_PARAMS:
            modified = self._modify_step_for_constraint(step, violation)
            return BacktrackDecision(
                strategy=strategy,
                violation=violation,
                modified_step=modified,
                reason=f"Retrying with modified parameters for {violation.constraint_type}",
            )

        elif strategy == BacktrackStrategy.SUBSTITUTE:
            alternative = self._find_alternative_step(step, violation)
            return BacktrackDecision(
                strategy=strategy,
                violation=violation,
                modified_step=alternative,
                reason=f"Substituting alternative for {violation.constraint_type} constraint",
            )

        elif strategy == BacktrackStrategy.REPLAN:
            return BacktrackDecision(
                strategy=strategy,
                violation=violation,
                reason=f"Full replan required for {violation.constraint_type} constraint",
            )

        else:  # ABORT
            return BacktrackDecision(
                strategy=BacktrackStrategy.ABORT,
                violation=violation,
                reason=f"Cannot recover from {violation.constraint_type} violation",
            )

    def _modify_step_for_constraint(
        self,
        step: Dict[str, Any],
        violation: Violation,
    ) -> Dict[str, Any]:
        """Modify step parameters to satisfy constraint."""
        modified = dict(step)
        args = dict(modified.get("args", modified.get("arguments", {})))

        ctype = violation.constraint_type

        if ctype == "file_size":
            # Reduce content or output size
            if "content" in args:
                # Truncate content to fit
                args["content"] = args["content"][:1000] + "...[truncated]"
            if "max_results" in args:
                args["max_results"] = min(args.get("max_results", 10), 5)
            modified["_constraint_modification"] = "reduced_output"

        elif ctype == "budget":
            # Request cheaper option
            args["max_price"] = args.get("max_price", 100) * 0.7
            args["sort_by"] = "price_low"
            modified["_constraint_modification"] = "budget_reduced"

        elif ctype == "time":
            # Request faster option
            args["max_duration"] = args.get("max_duration", 60) * 0.5
            args["prefer_direct"] = True
            modified["_constraint_modification"] = "faster_option"

        modified["args"] = args
        return modified

    def _find_alternative_step(
        self,
        step: Dict[str, Any],
        violation: Violation,
    ) -> Dict[str, Any]:
        """Find alternative step that satisfies constraint."""
        alternative = dict(step)
        action = step.get("action", step.get("tool", ""))
        args = dict(alternative.get("args", alternative.get("arguments", {})))

        ctype = violation.constraint_type

        # Mark as alternative
        alternative["_is_alternative"] = True
        alternative["_original_action"] = action

        if ctype == "budget":
            # Search for cheaper alternatives
            args["sort_by"] = "price_low"
            args["max_results"] = args.get("max_results", 5) + 3
            alternative["_constraint_note"] = "Finding cheaper alternatives"

        elif ctype == "availability":
            # Search for available alternatives
            args["available_only"] = True
            args["include_alternatives"] = True
            alternative["_constraint_note"] = "Finding available alternatives"

        elif ctype == "location":
            # Search nearby locations
            args["expand_radius"] = True
            args["max_distance"] = args.get("max_distance", 10) * 1.5
            alternative["_constraint_note"] = "Expanding search area"

        elif ctype == "must_avoid":
            # Add exclusion filter
            avoid_term = violation.reason.split(":")[-1].strip() if ":" in violation.reason else ""
            existing_exclude = args.get("exclude", [])
            if isinstance(existing_exclude, str):
                existing_exclude = [existing_exclude]
            existing_exclude.append(avoid_term)
            args["exclude"] = existing_exclude
            alternative["_constraint_note"] = f"Excluding {avoid_term}"

        alternative["args"] = args
        return alternative

    def apply_decision(
        self,
        state: PlanExecutionState,
        decision: BacktrackDecision,
    ) -> None:
        """
        Apply backtrack decision to execution state.

        Args:
            state: Execution state to modify
            decision: Decision to apply
        """
        step_idx = decision.violation.step_index

        if decision.strategy == BacktrackStrategy.SKIP_STEP:
            state.skipped_steps.append(step_idx)
            if decision.skip_to_step is not None:
                state.current_step = decision.skip_to_step

        elif decision.strategy in (BacktrackStrategy.RETRY_WITH_PARAMS,
                                    BacktrackStrategy.SUBSTITUTE):
            if decision.modified_step:
                # Replace step with modified version
                state.steps[step_idx] = decision.modified_step

        elif decision.strategy == BacktrackStrategy.REPLAN:
            # Mark for replanning - caller should handle
            pass

        elif decision.strategy == BacktrackStrategy.ABORT:
            state.aborted = True

    def should_continue(self, state: PlanExecutionState) -> bool:
        """Check if execution should continue."""
        if state.aborted:
            return False
        if state.current_step >= len(state.steps):
            return False
        return True

    def mark_step_complete(self, state: PlanExecutionState, step_index: int) -> None:
        """Mark a step as completed."""
        if step_index not in state.completed_steps:
            state.completed_steps.append(step_index)
        state.current_step = step_index + 1

    def save_state(
        self,
        turn_dir: "TurnDirectory",
        state: PlanExecutionState,
    ) -> None:
        """Save execution state to turn directory."""
        state_path = turn_dir.doc_path("execution_state.json")
        state_path.write_text(json.dumps(state.to_dict(), indent=2))

        # Also update plan_state.json with backtracking info
        plan_state_path = turn_dir.doc_path("plan_state.json")
        if plan_state_path.exists():
            plan_state = json.loads(plan_state_path.read_text())
        else:
            plan_state = {}

        plan_state["backtracking"] = {
            "enabled": True,
            "backtrack_count": state.backtrack_count,
            "max_backtracks": state.max_backtracks,
            "skipped_steps": state.skipped_steps,
            "aborted": state.aborted,
        }

        plan_state_path.write_text(json.dumps(plan_state, indent=2))

    def load_state(
        self,
        turn_dir: "TurnDirectory",
        steps: List[Dict[str, Any]],
    ) -> Optional[PlanExecutionState]:
        """Load execution state from turn directory."""
        state_path = turn_dir.doc_path("execution_state.json")
        if not state_path.exists():
            return None

        try:
            data = json.loads(state_path.read_text())
            state = PlanExecutionState(
                steps=steps,
                current_step=data.get("current_step", 0),
                completed_steps=data.get("completed_steps", []),
                skipped_steps=data.get("skipped_steps", []),
                max_backtracks=data.get("max_backtracks", self.max_backtracks),
                backtrack_count=data.get("backtrack_count", 0),
                aborted=data.get("aborted", False),
            )
            return state
        except Exception as e:
            logger.error(f"[BacktrackingPlanner] Failed to load state: {e}")
            return None


# Singleton instance
_backtracking_planner: Optional[BacktrackingPlanner] = None


def get_backtracking_planner() -> BacktrackingPlanner:
    """Get or create the singleton BacktrackingPlanner instance."""
    global _backtracking_planner
    if _backtracking_planner is None:
        _backtracking_planner = BacktrackingPlanner()
    return _backtracking_planner
