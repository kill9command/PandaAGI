from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from apps.services.gateway.tool_router import RouterSuggestion


@dataclass
class PlanLinter:
    def apply(
        self,
        plan: List[Dict[str, Dict]],
        suggestions: List[RouterSuggestion],
    ) -> Tuple[List[Dict[str, Dict]], List[str]]:
        """Ensure required tools are present and schemas look sane."""

        notes: List[str] = []
        normalized_plan = [_ensure_schema(step) for step in plan]
        existing_tools = {step.get("tool") for step in normalized_plan if isinstance(step, dict)}

        for suggestion in suggestions:
            required = suggestion.score >= suggestion.min_score and suggestion.tool.critical
            if required and suggestion.name not in existing_tools:
                normalized_plan.append(suggestion.to_plan_step())
                suggestion.applied = True
                existing_tools.add(suggestion.name)
                notes.append(f"auto_added:{suggestion.name}")
            else:
                suggestion.applied = suggestion.name in existing_tools

        return normalized_plan, notes


def _ensure_schema(step: Dict) -> Dict:
    if not isinstance(step, dict):
        return {}
    tool = step.get("tool")
    args = step.get("args")
    if not isinstance(tool, str):
        return {}
    if not isinstance(args, dict):
        args = {}
    return {"tool": tool, "args": args}

