"""
Response Parser - LLM response parsing and JSON repair.

Extracted from UnifiedFlow to provide centralized parsing for:
- Planner decisions (STRATEGIC_PLAN, PLANNER_DECISION, TICKET)
- Executor decisions (EXECUTOR_DECISION)
- Coordinator tool selections (TOOL_SELECTION, COORDINATOR_RESULT)
- Agent decisions (AGENT_DECISION)
- General JSON responses with repair capabilities

All parsers are tolerant of LLM output variations and provide
sensible defaults when parsing fails.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ResponseParser:
    """
    Parses LLM responses with robust error handling and JSON repair.

    Handles common LLM output issues:
    - Code block wrappers (```json ... ```)
    - Trailing commas
    - Single quotes instead of double quotes
    - Typos in key names (="key instead of "key)
    - Broken JSON with extractable content
    """

    def parse_json(self, response: str) -> Dict[str, Any]:
        """
        Parse JSON from LLM response, handling code blocks and common LLM typos.

        Args:
            response: Raw LLM response text

        Returns:
            Parsed dictionary

        Raises:
            ValueError: If JSON cannot be parsed after repair attempts
        """
        text = response.strip()

        # Try to extract from code block
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()

        # Extract JSON boundaries
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            text = text[json_start:json_end]

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"[ResponseParser] JSON parse failed: {e}, attempting repair...")

        # === JSON REPAIR STRATEGIES ===
        repaired = text

        # Fix 1: LLM typo - "="_type" → "_type" (extra = in key)
        repaired = re.sub(r'"="?([a-zA-Z_])', r'"\1', repaired)

        # Fix 1b: LLM typo - " "_type" or " answer" → "_type" or "answer"
        repaired = re.sub(r'"\s+"?([a-zA-Z_])', r'"\1', repaired)

        # Fix 2: Trailing commas before ] or }
        repaired = re.sub(r',\s*([}\]])', r'\1', repaired)

        # Fix 3: Single quotes to double quotes (but not inside strings)
        if "'" in repaired and '"' not in repaired:
            repaired = repaired.replace("'", '"')

        # Try repaired JSON
        try:
            result = json.loads(repaired)
            logger.info("[ResponseParser] JSON repair successful")
            return result
        except json.JSONDecodeError:
            pass

        # === LAST RESORT: Extract answer via regex ===
        answer_match = re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)', text, re.DOTALL)
        if answer_match:
            answer_text = answer_match.group(1)
            answer_text = answer_text.replace('\\"', '"').replace('\\n', '\n')
            logger.warning(f"[ResponseParser] Extracted answer via regex fallback ({len(answer_text)} chars)")
            return {
                "_type": "ANSWER",
                "answer": answer_text,
                "_repaired": True
            }

        # Failed to parse
        logger.error(f"[ResponseParser] Failed to parse JSON: {text[:200]}...")
        raise ValueError(f"LLM response is not valid JSON: {text[:100]}...")

    def parse_planner_decision(self, llm_response: str) -> Dict[str, Any]:
        """
        Parse STRATEGIC_PLAN or PLANNER_DECISION from LLM response.

        Handles formats:
        - STRATEGIC_PLAN (new 9-phase architecture)
        - PLANNER_DECISION (legacy)
        - TICKET (legacy backwards compatibility)

        Returns:
            Dictionary with keys: _type, action, route_to, goals, reasoning, etc.

        Raises:
            ValueError: If response cannot be parsed into a recognized format
        """
        decision = self.parse_json(llm_response)

        # Handle new STRATEGIC_PLAN format (9-phase architecture)
        if decision.get("_type") == "STRATEGIC_PLAN":
            route_to = decision.get("route_to", "synthesis")
            goals = decision.get("goals", [])
            approach = decision.get("approach", "")
            success_criteria = decision.get("success_criteria", "")
            reason = decision.get("reason", "")
            refresh_context_request = decision.get("refresh_context_request", [])
            plan_type = decision.get("plan_type")
            self_extension = decision.get("self_extension")

            # Map route_to to action
            action_map = {
                "synthesis": "COMPLETE",
                "executor": "EXECUTE",
                "clarify": "CLARIFY",
                "brainstorm": "BRAINSTORM",
                "refresh_context": "REFRESH_CONTEXT",
                "self_extension": "SELF_EXTENSION",
            }
            action = action_map.get(route_to, "COMPLETE")

            return {
                "_type": "STRATEGIC_PLAN",
                "action": action,
                "route_to": route_to,
                "goals": goals,
                "approach": approach,
                "success_criteria": success_criteria,
                "reasoning": reason,
                "refresh_context_request": refresh_context_request,
                "plan_type": plan_type,
                "self_extension": self_extension,
            }

        # Handle PLANNER_DECISION format (legacy)
        if decision.get("_type") == "PLANNER_DECISION":
            return decision

        # Handle legacy TICKET format (backwards compatibility)
        if decision.get("_type") == "TICKET":
            return self._convert_ticket_to_planner_decision(decision)

        # If no recognized format, try to infer action
        if decision.get("action") in ("EXECUTE", "COMPLETE"):
            return decision

        # Infer STRATEGIC_PLAN if we have route_to and goals (LLM omitted _type)
        if decision.get("route_to") and "goals" in decision:
            logger.warning("[ResponseParser] Inferring STRATEGIC_PLAN from route_to/goals (missing _type)")
            route_to = decision.get("route_to", "synthesis")
            action_map = {
                "synthesis": "COMPLETE",
                "executor": "EXECUTE",
                "clarify": "CLARIFY",
                "brainstorm": "BRAINSTORM",
                "refresh_context": "REFRESH_CONTEXT",
                "self_extension": "SELF_EXTENSION",
            }
            return {
                "_type": "STRATEGIC_PLAN",
                "action": action_map.get(route_to, "COMPLETE"),
                "route_to": route_to,
                "goals": decision.get("goals", []),
                "approach": decision.get("approach", ""),
                "success_criteria": decision.get("success_criteria", ""),
                "reasoning": decision.get("reason", decision.get("reasoning", "")),
                "refresh_context_request": decision.get("refresh_context_request", []),
                "plan_type": decision.get("plan_type"),
                "self_extension": decision.get("self_extension"),
            }

        # No recognized format — fail-fast instead of silently defaulting to COMPLETE
        raise ValueError(
            f"Planner response has no recognized format (_type={decision.get('_type')}, "
            f"action={decision.get('action')}): {str(decision)[:200]}"
        )

    def _convert_ticket_to_planner_decision(self, ticket: Dict[str, Any]) -> Dict[str, Any]:
        """Convert legacy TICKET format to PLANNER_DECISION."""
        tasks = ticket.get("tasks", [])
        planning_notes = ticket.get("planning_notes", "")

        # Check if any task has direct_answer=True
        direct_answer = any(
            isinstance(t, dict) and t.get("direct_answer")
            for t in tasks
        )

        # Check if needs clarification
        needs_clarification = any(
            isinstance(t, dict) and t.get("needs_clarification")
            for t in tasks
        )

        if direct_answer or needs_clarification:
            return {
                "_type": "PLANNER_DECISION",
                "action": "COMPLETE",
                "goals": [{"id": "GOAL_1", "description": "Answer from context", "status": "achieved"}],
                "reasoning": planning_notes or "Context sufficient - no tools needed"
            }
        else:
            # Convert tasks to tools
            tools = []
            goals = []
            for i, task in enumerate(tasks):
                if isinstance(task, dict):
                    desc = task.get("description") or task.get("task") or str(task)
                else:
                    desc = str(task)

                # Infer tool from task description (fallback)
                desc_lower = desc.lower()
                if any(kw in desc_lower for kw in ["search", "find", "look for", "research", "go to", "visit", "navigate to"]):
                    tools.append({
                        "tool": "internet.research",
                        "args": {"query": desc}
                    })

                goals.append({
                    "id": f"GOAL_{i+1}",
                    "description": desc,
                    "status": "in_progress"
                })

            return {
                "_type": "PLANNER_DECISION",
                "action": "EXECUTE" if tools else "COMPLETE",
                "tools": tools,
                "goals": goals,
                "reasoning": planning_notes
            }

    def parse_executor_decision(self, llm_response: str) -> Dict[str, Any]:
        """
        Parse EXECUTOR_DECISION from LLM response.

        Expected format:
        {
            "_type": "EXECUTOR_DECISION",
            "action": "COMMAND" | "ANALYZE" | "CREATE_WORKFLOW" | "COMPLETE" | "BLOCKED",
            "command": "Natural language instruction",
            "analysis": {...},
            "goals_progress": [...],
            "reasoning": "..."
        }

        Raises:
            ValueError: If response cannot be parsed into a recognized format
        """
        decision = self.parse_json(llm_response)

        if decision.get("_type") == "EXECUTOR_DECISION":
            return decision

        # Try to infer from action field
        if decision.get("action") in ("COMMAND", "ANALYZE", "CREATE_WORKFLOW", "COMPLETE", "BLOCKED"):
            decision["_type"] = "EXECUTOR_DECISION"
            return decision

        # No recognized format — fail-fast instead of silently defaulting to COMPLETE
        raise ValueError(
            f"Executor response has no recognized format (_type={decision.get('_type')}, "
            f"action={decision.get('action')}): {str(decision)[:200]}"
        )

    def parse_tool_selection(self, llm_response: str) -> Dict[str, Any]:
        """
        Parse TOOL_SELECTION from Coordinator LLM response.

        Handles formats:
        - TOOL_SELECTION: {_type, tool, args, reasoning}
        - COORDINATOR_RESULT: {_type, tool_selected, tool_args}
        - COORDINATOR_PLAN: {_type, subtasks: [{tool, ...}]}
        - tools array: {tools: [{tool, args}]}
        - NEEDS_CLARIFICATION
        - MODE_VIOLATION
        """
        try:
            selection = self.parse_json(llm_response)

            if selection.get("_type") in ("TOOL_SELECTION", "NEEDS_CLARIFICATION", "MODE_VIOLATION"):
                return selection

            # Handle COORDINATOR_RESULT format
            if selection.get("_type") == "COORDINATOR_RESULT":
                if selection.get("tool_selected"):
                    return {
                        "_type": "TOOL_SELECTION",
                        "tool": selection["tool_selected"],
                        "args": selection.get("tool_args", {}),
                        "reasoning": selection.get("rationale", "")
                    }
                if selection.get("status") == "blocked":
                    return {
                        "_type": "MODE_VIOLATION",
                        "error": selection.get("error", "Tool not available in this mode")
                    }

            # Try to extract tool info from other formats
            if selection.get("tool"):
                return {
                    "_type": "TOOL_SELECTION",
                    "tool": selection["tool"],
                    "args": selection.get("args", {}),
                    "reasoning": selection.get("reasoning", "")
                }

            # Try tool_selected format without _type
            if selection.get("tool_selected"):
                return {
                    "_type": "TOOL_SELECTION",
                    "tool": selection["tool_selected"],
                    "args": selection.get("tool_args", {}),
                    "reasoning": selection.get("rationale", "")
                }

            # Handle tools array format
            if selection.get("tools") and isinstance(selection["tools"], list):
                tools_array = selection["tools"]
                if tools_array and len(tools_array) > 0:
                    first_tool = tools_array[0]
                    if first_tool.get("tool"):
                        return {
                            "_type": "TOOL_SELECTION",
                            "tool": first_tool["tool"],
                            "args": first_tool.get("args", {}),
                            "reasoning": selection.get("rationale", "")
                        }

            # Handle COORDINATOR_PLAN format
            if selection.get("_type") == "COORDINATOR_PLAN" and selection.get("subtasks"):
                subtasks = selection["subtasks"]
                if subtasks and isinstance(subtasks, list) and len(subtasks) > 0:
                    first_task = subtasks[0]
                    if first_task.get("tool"):
                        args = {k: v for k, v in first_task.items() if k not in ("tool", "why", "_type")}
                        return {
                            "_type": "TOOL_SELECTION",
                            "tool": first_task["tool"],
                            "args": args,
                            "reasoning": first_task.get("why", "")
                        }

            logger.warning("[ResponseParser] Could not parse Coordinator response: %s", selection)
            return {"_type": "ERROR", "error": "Could not parse tool selection"}

        except Exception as e:
            logger.warning(f"[ResponseParser] Failed to parse tool selection: {e}")
            return {"_type": "ERROR", "error": f"Parse error: {str(e)[:100]}"}

    def parse_agent_decision(self, llm_response: str) -> Dict[str, Any]:
        """
        Parse agent decision from LLM response.

        Handles formats:
        - AGENT_DECISION: {action: TOOL_CALL|DONE|BLOCKED, tools: [...]}
        - TOOL_SELECTION (legacy): {_type: TOOL_SELECTION, tool, config}
        - COORDINATOR_SELECTION: {_type: COORDINATOR_SELECTION, workflow_selected, workflow_args}

        Raises:
            ValueError: If response cannot be parsed into a recognized format
        """
        decision = self.parse_json(llm_response)

        # Handle workflow selection format
        if decision.get("_type") == "COORDINATOR_SELECTION":
            status = decision.get("status", "selected")
            if status == "needs_more_info":
                return {
                    "action": "BLOCKED",
                    "reasoning": decision.get("message", "Missing required inputs"),
                }
            if status == "blocked":
                return {
                    "action": "BLOCKED",
                    "reasoning": decision.get("error", "Workflow blocked"),
                }

            workflow_selected = decision.get("workflow_selected") or decision.get("workflow")
            if not workflow_selected:
                return {
                    "action": "BLOCKED",
                    "reasoning": "No workflow selected",
                }
            return {
                "action": "WORKFLOW_CALL",
                "workflow_selected": workflow_selected,
                "workflow_args": decision.get("workflow_args", {}),
                "reasoning": decision.get("rationale", "Workflow selected"),
            }

        # Handle legacy TOOL_SELECTION format
        if decision.get("_type") == "TOOL_SELECTION":
            tool_name = decision.get("tool", "")
            config = decision.get("config", {})
            rationale = decision.get("rationale", "Tool selected")

            if tool_name:
                logger.info(f"[ResponseParser] Converting TOOL_SELECTION to AGENT_DECISION: {tool_name}")
                return {
                    "action": "TOOL_CALL",
                    "tools": [{
                        "tool": tool_name,
                        "args": config,
                        "purpose": rationale
                    }],
                    "reasoning": rationale,
                    "progress_summary": "Executing tool from selection",
                    "remaining_work": "Complete tool execution"
                }
            else:
                return {
                    "action": "DONE",
                    "reasoning": "No tool needed",
                    "progress_summary": "Ready for synthesis"
                }

        # Handle AGENT_DECISION format
        if decision.get("action") in ("TOOL_CALL", "WORKFLOW_CALL", "DONE", "BLOCKED"):
            return decision

        # Try to infer from tool fields
        if decision.get("tool") or decision.get("tools"):
            decision["action"] = "TOOL_CALL"
            if decision.get("tool") and not decision.get("tools"):
                decision["tools"] = [{"tool": decision["tool"], "args": decision.get("config", {}), "purpose": "execute"}]
            return decision

        # No recognized format — fail-fast instead of silently defaulting to BLOCKED
        raise ValueError(
            f"Agent response has no recognized format (action={decision.get('action')}, "
            f"_type={decision.get('_type')}): {str(decision)[:200]}"
        )


# Module-level singleton
_parser: Optional[ResponseParser] = None


def get_response_parser() -> ResponseParser:
    """Get or create the singleton ResponseParser instance."""
    global _parser
    if _parser is None:
        _parser = ResponseParser()
    return _parser


# Convenience functions for direct import
def parse_json_response(response: str) -> Dict[str, Any]:
    """Parse JSON from LLM response with repair."""
    return get_response_parser().parse_json(response)


def parse_planner_decision(llm_response: str) -> Dict[str, Any]:
    """Parse Planner decision."""
    return get_response_parser().parse_planner_decision(llm_response)


def parse_executor_decision(llm_response: str) -> Dict[str, Any]:
    """Parse Executor decision."""
    return get_response_parser().parse_executor_decision(llm_response)


def parse_tool_selection(llm_response: str) -> Dict[str, Any]:
    """Parse tool selection from Coordinator."""
    return get_response_parser().parse_tool_selection(llm_response)


def parse_agent_decision(llm_response: str) -> Dict[str, Any]:
    """Parse agent decision."""
    return get_response_parser().parse_agent_decision(llm_response)
