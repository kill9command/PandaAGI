"""
Section Formatter - Context document section formatting utilities.

Extracted from UnifiedFlow to handle:
- §3 (Task Plan / Strategic Plan) formatting
- §4 (Execution Progress) formatting
- Goal formatting for logging

Architecture Reference:
- architecture/main-system-patterns/phase3-planner.md
- architecture/main-system-patterns/phase4-executor.md
"""

import json
import logging
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument

logger = logging.getLogger(__name__)


class SectionFormatter:
    """
    Formats context document sections for various phases.

    Responsibilities:
    - Format §3 from Planner decisions
    - Format §3 from Strategic Plans
    - Format §4 execution progress
    - Format goals for logging
    """

    def format_goals(self, goals: List[Dict[str, Any]]) -> str:
        """Format goals for logging."""
        if not goals:
            return "(no goals)"
        parts = []
        for g in goals:
            status = g.get("status", "?")
            gid = g.get("id", "?")
            parts.append(f"{gid}:{status}")
        return ", ".join(parts)

    def update_section3_from_planner(
        self,
        context_doc: "ContextDocument",
        planner_decision: Dict[str, Any],
        route_to: str
    ):
        """Update §3 (Task Plan) from Planner decision."""
        goals = planner_decision.get("goals", [])
        reasoning = planner_decision.get("reasoning", "")

        # Format goals
        goals_lines = []
        for goal in goals:
            status = goal.get("status", "pending")
            desc = goal.get("description", str(goal))
            goals_lines.append(f"- [{status}] {desc}")

        goals_content = "\n".join(goals_lines) if goals_lines else "- Execute and respond"

        section_content = f"""**Goals:**
{goals_content}

**Route To:** {route_to}
**Planning Notes:** {reasoning}
"""
        if context_doc.has_section(3):
            context_doc.update_section(3, section_content)
        else:
            context_doc.append_section(3, "Task Plan", section_content)

    def update_section3_from_strategic_plan(
        self,
        context_doc: "ContextDocument",
        strategic_plan: Dict[str, Any]
    ):
        """Update §3 (Strategic Plan) from STRATEGIC_PLAN decision."""
        goals = strategic_plan.get("goals", [])
        approach = strategic_plan.get("approach", "")
        success_criteria = strategic_plan.get("success_criteria", "")
        route_to = strategic_plan.get("route_to", "executor")
        reasoning = strategic_plan.get("reasoning", "")
        refresh_context_request = strategic_plan.get("refresh_context_request") or []
        plan_type = strategic_plan.get("plan_type")

        # Format goals
        goals_lines = []
        for goal in goals:
            priority = goal.get("priority", "medium")
            desc = goal.get("description", str(goal))
            goal_id = goal.get("id", "?")
            goals_lines.append(f"- **{goal_id}** [{priority}]: {desc}")

        goals_content = "\n".join(goals_lines) if goals_lines else "- (No goals specified)"

        refresh_block = ""
        if refresh_context_request:
            refresh_lines = "\n".join(f"- {item}" for item in refresh_context_request)
            refresh_block = f"\n**Refresh Context Request:**\n{refresh_lines}\n"

        section_content = f"""## Strategic Plan

**Goals:**
{goals_content}

**Approach:** {approach}

**Success Criteria:** {success_criteria}

**Route To:** {route_to}
{refresh_block}
{f"**Plan Type:** {plan_type}" + chr(10) if plan_type else ""}
**Reasoning:** {reasoning}
"""
        if context_doc.has_section(3):
            context_doc.update_section(3, section_content)
        else:
            context_doc.append_section(3, "Strategic Plan", section_content)

    def format_executor_analysis(
        self,
        analysis: Dict[str, Any],
        goals_progress: List[Dict[str, Any]],
        iteration: int
    ) -> str:
        """Format executor analysis for §4."""
        current_state = analysis.get("current_state", "")
        findings = analysis.get("findings", "")
        rationale = analysis.get("next_step_rationale", "")

        goals_str = self.format_goals(goals_progress)

        return f"""### Executor Iteration {iteration}
**Action:** ANALYZE
**Goals Progress:** {goals_str}
**Current State:** {current_state}
**Findings:** {findings}
**Next Step:** {rationale}
"""

    def format_executor_command_result(
        self,
        command: str,
        coordinator_result: Dict[str, Any],
        goals_progress: List[Dict[str, Any]],
        iteration: int
    ) -> str:
        """Format executor command result for §4."""
        tool = coordinator_result.get("tool_selected", "unknown")
        status = coordinator_result.get("status", "unknown")
        result = coordinator_result.get("result", {})
        claims = coordinator_result.get("claims", [])
        missing = coordinator_result.get("missing", [])
        message = coordinator_result.get("message", "")

        goals_str = self.format_goals(goals_progress)

        if status == "needs_more_info":
            missing_text = ", ".join(missing) if missing else "unspecified inputs"
            return f"""### Executor Iteration {iteration}
**Action:** COMMAND
**Command:** {command}
**Coordinator:** `{tool}` → {status}
**Goals Progress:** {goals_str}

**⚠️ COORDINATOR NEEDS MORE INFO**
**Missing:** {missing_text}
**Message:** {message or 'Provide additional details and retry with a refined command.'}
"""

        # Format research results clearly for executor to see
        if tool == "internet.research":
            findings = result.get("findings", [])
            findings_count = len(findings)

            if findings_count > 0 and status == "success":
                # Show clear success with extracted content
                # Use longer summary (500 chars) so executor can see actual data
                findings_summary = []
                for i, f in enumerate(findings[:5]):  # Show up to 5
                    title = f.get("title", f.get("name", ""))
                    summary = f.get("summary", f.get("statement", ""))[:500]  # 500 chars for useful context
                    if title or summary:
                        findings_summary.append(f"  {i+1}. {title}: {summary}...")

                findings_text = "\n".join(findings_summary) if findings_summary else "  (content extracted)"

                return f"""### Executor Iteration {iteration}
**Action:** COMMAND
**Command:** {command}
**Coordinator:** `{tool}` → {status}
**Goals Progress:** {goals_str}

**✅ RESEARCH SUCCEEDED:** Found {findings_count} result(s), extracted {len(claims)} claim(s)
**Findings:**
{findings_text}

**Status:** Research complete - sufficient data gathered. Consider COMPLETE if goal achieved.
"""
            else:
                return f"""### Executor Iteration {iteration}
**Action:** COMMAND
**Command:** {command}
**Coordinator:** `{tool}` → {status}
**Goals Progress:** {goals_str}

**⚠️ RESEARCH RETURNED NO RESULTS**
**Status:** {status}, findings: {findings_count}
"""

        # Default format for other tools
        result_str = json.dumps(result, indent=2)
        if len(result_str) > 500:
            result_str = result_str[:500] + "... (truncated)"

        return f"""### Executor Iteration {iteration}
**Action:** COMMAND
**Command:** {command}
**Coordinator:** `{tool}` → {status}
**Goals Progress:** {goals_str}
**Result Preview:** {result_str[:300]}
"""

    def append_to_section4(self, context_doc: "ContextDocument", content: str):
        """Append content to §4 (Execution Progress)."""
        if context_doc.has_section(4):
            existing = context_doc.get_section(4)
            # Remove placeholder text if present
            if existing.startswith("*("):
                context_doc.update_section(4, content)
            else:
                context_doc.update_section(4, existing + "\n\n" + content)
        else:
            context_doc.append_section(4, "Execution Progress", content)


# Singleton instance
_section_formatter: SectionFormatter = None


def get_section_formatter() -> SectionFormatter:
    """Get or create a SectionFormatter instance."""
    global _section_formatter
    if _section_formatter is None:
        _section_formatter = SectionFormatter()
    return _section_formatter
