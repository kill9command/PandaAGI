from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from apps.services.gateway.tool_catalog import ToolCatalog, ToolMetadata
from apps.services.gateway.intent_classifier import IntentClassifier, IntentType


@dataclass
class RouterSuggestion:
    tool: ToolMetadata
    score: float
    resolved_args: Dict[str, str]
    reason: str
    applied: bool = False

    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def min_score(self) -> float:
        return self.tool.min_score

    def to_plan_step(self) -> Dict[str, Dict[str, str]]:
        return {"tool": self.tool.name, "args": self.resolved_args}


class ToolRouter:
    def __init__(self, catalog: ToolCatalog):
        self.catalog = catalog
        self.intent_classifier = IntentClassifier()

    def suggest(
        self,
        *,
        ticket_goal: str,
        ticket_micro_plan: Sequence[str],
        user_message: str,
        repo: str | None = None,
        session_id: str | None = None,
    ) -> List[RouterSuggestion]:
        query_seed = _derive_query(ticket_goal, ticket_micro_plan, user_message)
        haystack = "\n".join(filter(None, [ticket_goal, " ".join(ticket_micro_plan), user_message])).lower()

        # Classify intent
        intent_signal = self.intent_classifier.classify(
            query=user_message or ticket_goal,
            context=" ".join(ticket_micro_plan)
        )

        # Use intent type value (e.g., "informational", "transactional")
        intent_type = intent_signal.intent.value if intent_signal.confidence >= 0.3 else None

        suggestions: List[RouterSuggestion] = []
        for tool in self.catalog.tools:
            # Pass intent to match_score for intent-aware filtering
            score = tool.match_score(haystack, intent=intent_type)
            if score <= 0:
                continue
            resolved_args = {}
            for key, value in tool.auto_args.items():
                if value == "{{query}}":
                    resolved_args[key] = query_seed
                elif value == "{{repo}}":
                    resolved_args[key] = (repo or "")
                elif value == "{{session_id}}":
                    resolved_args[key] = (session_id or "default")
                else:
                    resolved_args[key] = value

            # Include intent info in reason for debugging
            reason = f"keywords matched score={score:.2f}"
            if intent_type:
                reason += f", intent={intent_type} (conf={intent_signal.confidence:.2f})"

            suggestions.append(
                RouterSuggestion(
                    tool=tool,
                    score=score,
                    resolved_args=resolved_args,
                    reason=reason,
                )
            )
        return suggestions


def _derive_query(goal: str, micro_plan: Sequence[str], user_message: str) -> str:
    if goal:
        return goal.strip()[:120]
    for item in micro_plan:
        if item:
            return item.strip()[:120]
    return (user_message or "").strip()[:120]

