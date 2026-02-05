"""
Plan State Manager - Goal and constraint tracking.

Extracted from UnifiedFlow to manage:
- Plan state initialization and persistence
- Goal normalization and status tracking
- Constraint validation and violation recording

Architecture Reference:
- architecture/main-system-patterns/phase3-planner.md
"""

import json
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.persistence.turn_manager import TurnDirectory
    from libs.gateway.validation.validation_result import ValidationResult

logger = logging.getLogger(__name__)


class PlanStateManager:
    """
    Manages plan state including goals, constraints, and violations.

    Responsibilities:
    - Load and save plan_state.json
    - Normalize goals from various formats
    - Track constraint violations
    - Update state from validation results
    """

    def load_constraints_payload(self, turn_dir: "TurnDirectory") -> Dict[str, Any]:
        """Load constraints.json from turn directory."""
        constraints_path = turn_dir.doc_path("constraints.json")
        if not constraints_path.exists():
            return {"constraints": []}
        try:
            return json.loads(constraints_path.read_text())
        except Exception:
            return {"constraints": []}

    def write_plan_state(self, turn_dir: "TurnDirectory", plan_state: Dict[str, Any]) -> None:
        """Write plan_state.json to turn directory."""
        plan_state_path = turn_dir.doc_path("plan_state.json")
        plan_state_path.write_text(json.dumps(plan_state, indent=2))

    def load_plan_state(self, turn_dir: "TurnDirectory") -> Optional[Dict[str, Any]]:
        """Load plan_state.json if it exists."""
        plan_state_path = turn_dir.doc_path("plan_state.json")
        if not plan_state_path.exists():
            return None
        try:
            return json.loads(plan_state_path.read_text())
        except Exception:
            return None

    def normalize_goals(self, goals: List[Any]) -> List[Dict[str, Any]]:
        """Normalize goals to PlanState format."""
        normalized: List[Dict[str, Any]] = []
        for idx, goal in enumerate(goals, start=1):
            if isinstance(goal, dict):
                goal_id = goal.get("id") or goal.get("goal_id") or f"GOAL_{idx}"
                description = goal.get("description") or goal.get("goal") or str(goal)
            else:
                goal_id = f"GOAL_{idx}"
                description = str(goal)
            normalized.append({
                "id": goal_id,
                "description": description,
                "status": "pending"
            })
        return normalized

    def initialize_plan_state(
        self,
        turn_dir: "TurnDirectory",
        goals: List[Any],
        phase: int = 3,
        overwrite: bool = True
    ) -> None:
        """Initialize plan_state.json with goals and constraints."""
        if not overwrite and self.load_plan_state(turn_dir):
            return

        constraints_payload = self.load_constraints_payload(turn_dir)
        constraints = constraints_payload.get("constraints", []) if isinstance(constraints_payload, dict) else []

        plan_state = {
            "goals": self.normalize_goals(goals),
            "constraints": [
                {"id": c.get("id", f"C{idx+1}"), "status": "active"}
                for idx, c in enumerate(constraints)
                if isinstance(c, dict)
            ],
            "violations": [],
            "last_updated_phase": phase
        }
        self.write_plan_state(turn_dir, plan_state)

    def record_constraint_violation(
        self,
        turn_dir: "TurnDirectory",
        constraint_id: str,
        reason: str,
        phase: int = 5
    ) -> None:
        """Record constraint violation in plan_state.json."""
        plan_state = self.load_plan_state(turn_dir) or {}
        violations = plan_state.get("violations", [])
        violations.append({
            "constraint_id": constraint_id,
            "reason": reason,
            "phase": phase
        })
        plan_state["violations"] = violations
        plan_state["last_updated_phase"] = phase

        # Mark constraint as violated if present
        for constraint in plan_state.get("constraints", []):
            if constraint.get("id") == constraint_id:
                constraint["status"] = "violated"

        self.write_plan_state(turn_dir, plan_state)

    def check_constraints_for_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        constraints_payload: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        """Check tool call against constraints. Returns violation dict if any."""
        constraints = constraints_payload.get("constraints", []) if isinstance(constraints_payload, dict) else []
        if not constraints:
            return None

        tool_blob = f"{tool_name} {json.dumps(tool_args, default=str)}".lower()

        for constraint in constraints:
            if not isinstance(constraint, dict):
                continue
            ctype = str(constraint.get("type", "")).lower()
            cvalue = constraint.get("value", None)
            cid = constraint.get("id", "")

            if ctype == "privacy":
                no_external = False
                if isinstance(cvalue, dict):
                    no_external = bool(cvalue.get("no_external_calls"))
                elif isinstance(cvalue, list):
                    no_external = any("no_external" in str(v) for v in cvalue)
                elif isinstance(cvalue, str):
                    no_external = "no_external" in cvalue
                if no_external and tool_name.startswith(("internet.", "browser.")):
                    return {
                        "constraint_id": cid or "privacy",
                        "reason": "External calls forbidden by privacy constraint"
                    }

            if ctype == "must_avoid":
                avoid_terms: List[str] = []
                if isinstance(cvalue, list):
                    avoid_terms = [str(v).lower() for v in cvalue]
                elif isinstance(cvalue, dict):
                    avoid_terms = [str(v).lower() for v in cvalue.values()]
                elif cvalue:
                    avoid_terms = [str(cvalue).lower()]

                for term in avoid_terms:
                    if term and term in tool_blob:
                        return {
                            "constraint_id": cid or "must_avoid",
                            "reason": f"Must-avoid constraint matched: {term}"
                        }

        return None

    def update_from_validation(
        self,
        turn_dir: "TurnDirectory",
        validation_result: Optional["ValidationResult"]
    ) -> None:
        """Update plan_state.json based on validation results."""
        if not validation_result:
            return

        checks = getattr(validation_result, "checks", {}) or {}
        constraints_respected = checks.get("constraints_respected")
        if constraints_respected is False:
            self.record_constraint_violation(
                turn_dir,
                constraint_id="constraints",
                reason="Validator reported constraint violation",
                phase=7
            )


# Singleton instance
_plan_state_manager: Optional[PlanStateManager] = None


def get_plan_state_manager() -> PlanStateManager:
    """Get or create the singleton PlanStateManager instance."""
    global _plan_state_manager
    if _plan_state_manager is None:
        _plan_state_manager = PlanStateManager()
    return _plan_state_manager
