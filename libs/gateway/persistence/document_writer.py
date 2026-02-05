"""
Document Writer - Turn document generation and persistence.

Extracted from UnifiedFlow to handle:
- context.md writing
- ticket.md generation
- toolresults.md formatting
- research document creation

Architecture Reference:
- architecture/main-system-patterns/phase8-save.md
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument
    from libs.gateway.persistence.turn_manager import TurnDirectory

logger = logging.getLogger(__name__)


class DocumentWriter:
    """
    Handles turn document generation and writing.

    Responsibilities:
    - Write context.md for recipe consumption
    - Generate and write ticket.md
    - Format toolresults.md from execution results
    - Coordinate research document creation
    """

    def __init__(self, turns_dir: Path = None):
        """Initialize the document writer."""
        self.turns_dir = turns_dir

    def write_context_md(self, turn_dir: "TurnDirectory", context_doc: "ContextDocument"):
        """Write context.md to turn directory for recipe to read."""
        context_path = turn_dir.doc_path("context.md")
        context_path.write_text(context_doc.get_markdown())

    def write_ticket_md(self, turn_dir: "TurnDirectory", ticket: Dict[str, Any]):
        """Write ticket.md to turn directory."""
        ticket_path = turn_dir.doc_path("ticket.md")
        content = f"""# Task Ticket

**Goal:** {ticket.get("user_need", "Unknown")}
**Intent:** {ticket.get("intent", "unknown")}
**Tools:** {", ".join(ticket.get("recommended_tools", []))}

## Context
{json.dumps(ticket.get("context", {}), indent=2)}

## Constraints
{chr(10).join(f"- {c}" for c in ticket.get("constraints", []))}
"""
        ticket_path.write_text(content)

    def build_ticket_from_plan(
        self,
        strategic_plan: Dict[str, Any],
        step_log: List[str]
    ) -> str:
        """Build ticket content from strategic plan and execution log."""
        goals = strategic_plan.get("goals", [])
        approach = strategic_plan.get("approach", "")
        success_criteria = strategic_plan.get("success_criteria", "")

        goals_md = "\n".join([f"- {g.get('description', str(g))}" for g in goals])
        steps_md = "\n\n".join(step_log)

        return f"""# Strategic Plan

## Goals
{goals_md}

## Approach
{approach}

## Success Criteria
{success_criteria}

## Execution Log
{steps_md}
"""

    def build_toolresults_md(
        self,
        tool_results: List[Dict[str, Any]],
        claims: List[Dict[str, Any]]
    ) -> str:
        """Build toolresults.md content for Synthesis."""
        if not tool_results:
            return "# Tool Results\n\n*(No tools executed)*"

        content = "# Tool Results\n\n"

        for tr in tool_results:
            iteration = tr.get("iteration", "?")
            command = tr.get("command", "")
            tool = tr.get("tool", "unknown")
            status = tr.get("status", "unknown")
            result = tr.get("result", {})

            content += f"## Iteration {iteration}: {tool}\n"
            content += f"**Command:** {command}\n"
            content += f"**Status:** {status}\n"
            content += f"**Result:**\n```json\n{json.dumps(result, indent=2)[:2000]}\n```\n\n"

        if claims:
            content += "## Extracted Claims\n\n"
            for claim in claims[:20]:  # Limit to 20 claims
                content += f"- {claim.get('claim', str(claim))}\n"

        return content

    def build_ticket_content(self, context_doc: "ContextDocument", plan: Dict[str, Any]) -> str:
        """Build ticket.md content."""
        return f"""# Task Ticket

**Turn:** {context_doc.turn_number}
**Session:** {context_doc.session_id}

## Goal
{context_doc.query}

## Plan
{json.dumps(plan, indent=2)}

## Status
Complete
"""

    def build_toolresults_content(
        self,
        context_doc: "ContextDocument",
        tool_results: List[Dict[str, Any]]
    ) -> str:
        """Build toolresults.md content."""
        return f"""# Tool Results

**Turn:** {context_doc.turn_number}

## Execution Log
{json.dumps(tool_results, indent=2, default=str)}
"""


# Singleton instance
_document_writer: DocumentWriter = None


def get_document_writer(turns_dir: Path = None) -> DocumentWriter:
    """Get or create a DocumentWriter instance."""
    global _document_writer
    if _document_writer is None or turns_dir is not None:
        _document_writer = DocumentWriter(turns_dir=turns_dir)
    return _document_writer
