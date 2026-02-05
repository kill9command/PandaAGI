"""Pandora context document manager.

Manages context.md - the single working document that accumulates
state across all phases of the 8-phase pipeline.

Architecture Reference:
    architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md#3-contextmd-specification

Key Design Principles:
    - Single source of truth for the turn
    - Append-only during pipeline execution
    - Sections numbered §0-§6 mapping to pipeline phases
    - Original query always preserved in section 0

8-Phase Pipeline context.md sections:
    §0: Original Query (Phase 1 input)
    §1: Query Analysis (Phase 1 output)
    §2: Gathered Context (Phase 2 output)
    §3: Plan/Goals (Phase 3 output)
    §4: Tool Results (Phase 4/5 output - accumulates)
    §5: Response (Phase 6 output)
    §6: Validation (Phase 7 output)
    Note: Phase 8 (Save) is procedural, doesn't add sections
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from libs.core.exceptions import DocumentIOError
from libs.core.models import (
    QueryAnalysis,
    ReflectionResult,
    GatheredContext,
    TaskPlan,
    ToolExecutionResult,
    SynthesisResult,
    ValidationResult,
)


class ContextManager:
    """Manages context.md document operations.

    The context.md file is the single working document that accumulates
    state across all 8 phases of the pipeline. Each phase reads the document,
    performs its work, and appends a new section.

    Section mapping (8-phase pipeline):
        - §0: Original Query (Phase 1 input)
        - §1: Query Analysis (Phase 1 output) [legacy: Reflection Decision]
        - §2: Gathered Context (Phase 2 output)
        - §3: Plan/Goals (Phase 3 output) [legacy: Task Plan]
        - §4: Tool Results (Phase 4+5 output) [legacy: Tool Execution]
        - §5: Response (Phase 6 output) [legacy: Synthesis]
        - §6: Validation (Phase 7 output)
        Note: §5 was UNUSED in legacy layout; now used for Response.
    """

    # Section headers - updated names, same indices for code compatibility
    # Note: Section 5 is skipped (§4 accumulates for Executor+Coordinator)
    SECTION_HEADERS = {
        0: "## 0. Original Query",  # Phase 1 input
        1: "## 1. Query Analysis",  # Phase 1 output (legacy: Reflection Decision)
        2: "## 2. Gathered Context",  # Phase 2 output
        3: "## 3. Plan",  # Phase 3 output (legacy: Task Plan)
        4: "## 4. Tool Results",  # Phase 4/5 output (legacy: Tool Execution)
        6: "## 6. Response",  # Phase 6 output (legacy: Synthesis)
        7: "## 7. Validation",  # Phase 7 output
    }

    def __init__(self, turn_dir: Path):
        """
        Initialize context manager.

        Args:
            turn_dir: Directory for this turn (e.g., turns/turn_000815/)
        """
        self.turn_dir = turn_dir
        self.context_path = turn_dir / "context.md"
        self._content: Optional[str] = None

    @property
    def content(self) -> str:
        """Get current context.md content."""
        if self._content is None:
            if self.context_path.exists():
                self._content = self.context_path.read_text()
            else:
                self._content = ""
        return self._content

    def create(self, raw_query: str, session_id: str, turn_number: int) -> None:
        """
        Create new context.md with initial structure.

        Args:
            raw_query: Original user query (preserved for LLM context discipline)
            session_id: User session ID
            turn_number: Turn number
        """
        timestamp = datetime.now().isoformat()

        # Create frontmatter
        content = f"""---
id: turn_{turn_number:06d}_context
turn_number: {turn_number}
session_id: {session_id}
created_at: {timestamp}
---

# Context Document - Turn {turn_number}

## 0. User Query

**Original:** {raw_query}

"""
        self._content = content
        self._save()

    def read_section(self, section: int) -> str:
        """
        Read a specific section from context.md.

        Args:
            section: Section number (0-6)

        Returns:
            Section content (without header)
        """
        if section not in self.SECTION_HEADERS:
            raise ValueError(f"Invalid section: {section}")

        header = self.SECTION_HEADERS[section]
        content = self.content

        # Find section start
        start_idx = content.find(header)
        if start_idx == -1:
            return ""

        # Find section end (next section or EOF)
        section_content = content[start_idx + len(header):]

        # Look for next section header
        for next_section in range(section + 1, 7):
            next_header = self.SECTION_HEADERS[next_section]
            end_idx = section_content.find(next_header)
            if end_idx != -1:
                section_content = section_content[:end_idx]
                break

        return section_content.strip()

    def write_section_0(self, analysis: QueryAnalysis) -> None:
        """
        Enrich section 0 with query analysis results.

        This replaces the basic section 0 with enriched analysis but
        ALWAYS preserves the original query for LLM context discipline.

        Args:
            analysis: Query analysis from Phase 1
        """
        section_content = f"""## 0. Original Query

**Original:** {analysis.original_query}

**Resolved:** {analysis.resolved_query}
**Action Needed:** {analysis.action_needed}
**User Purpose:** {analysis.user_purpose}
**Was Resolved:** {str(analysis.was_resolved).lower()}
"""
        if analysis.content_reference:
            ref = analysis.content_reference
            section_content += f"""**Content Reference:**
- Title: {ref.title}
- Type: {ref.content_type}
- Site: {ref.site}
- Source Turn: {ref.source_turn}
"""
            if ref.has_visit_record:
                section_content += f"- Visit Record: {ref.visit_record_path}\n"

        section_content += f"""
**Reasoning:** {analysis.reasoning}

"""
        self._replace_section(0, section_content)

    def write_section_1(self, result: ReflectionResult) -> None:
        """Write Phase 1 query analysis/validation to section 1."""
        section_content = f"""## 1. Query Analysis

**Decision:** {result.decision.value}
**Confidence:** {result.confidence:.2f}
**Query Type:** {result.query_type or 'N/A'}
**Is Follow-up:** {str(result.is_followup).lower()}

**Reasoning:** {result.reasoning}

"""
        self._append_section(1, section_content)

    def write_section_2(self, context: GatheredContext) -> None:
        """Write Phase 2 gathered context to section 2."""
        section_content = """## 2. Gathered Context

"""
        # Session preferences
        if context.session_preferences:
            section_content += "### Session Preferences\n"
            section_content += "| Preference | Value |\n|------------|-------|\n"
            for key, value in context.session_preferences.items():
                section_content += f"| {key} | {value} |\n"
            section_content += "\n"

        # Relevant turns
        if context.relevant_turns:
            section_content += "### Relevant Prior Turns\n"
            section_content += "| Turn | Relevance | Summary |\n|------|-----------|--------|\n"
            for source in context.relevant_turns:
                section_content += f"| {source.turn_number or 'N/A'} | {source.relevance:.2f} | {source.summary} |\n"
            section_content += "\n"

        # Cached research
        if context.cached_research:
            section_content += "### Cached Research Intelligence\n"
            section_content += f"**Topic:** {context.cached_research.get('topic', 'N/A')}\n"
            section_content += f"**Quality Score:** {context.cached_research.get('quality', 'N/A')}\n"
            section_content += f"**Age:** {context.cached_research.get('age', 'N/A')}\n\n"

        # Sufficiency
        section_content += f"### Sufficiency Assessment\n{context.sufficiency_assessment}\n\n"

        # Source references
        if context.source_references:
            section_content += "### Source References\n"
            for i, ref in enumerate(context.source_references, 1):
                section_content += f"- [{i}] {ref}\n"
            section_content += "\n"

        self._append_section(2, section_content)

    def write_section_3(self, plan: TaskPlan, attempt: int = 1) -> None:
        """Write Phase 3 plan to section 3."""
        attempt_header = f" (Attempt {attempt})" if attempt > 1 else ""

        section_content = f"""## 3. Plan{attempt_header}

**Decision:** {plan.decision.value}
**Reasoning:** {plan.reasoning}

"""
        # Goals
        if plan.goals:
            section_content += "### Goals Identified\n\n"
            section_content += "| ID | Description | Status | Dependencies |\n"
            section_content += "|----|-------------|--------|---------------|\n"
            for goal in plan.goals:
                deps = ", ".join(goal.dependencies) if goal.dependencies else "-"
                section_content += f"| {goal.id} | {goal.description} | {goal.status.value} | {deps} |\n"
            section_content += "\n"

        # Current focus
        if plan.current_focus:
            section_content += f"### Current Focus\n{plan.current_focus}\n\n"

        # Tool requests
        if plan.tool_requests:
            section_content += "### Tool Requests\n"
            for req in plan.tool_requests:
                section_content += f"- **Tool:** {req.tool}\n"
                section_content += f"  **Args:** {req.args}\n"
                if req.goal_id:
                    section_content += f"  **Goal:** {req.goal_id}\n"
            section_content += "\n"

        # Route
        if plan.route:
            section_content += f"### Route To\n{plan.route.value}\n\n"

        self._append_section(3, section_content)

    def append_section_4(self, result: ToolExecutionResult) -> None:
        """
        Append tool execution results to section 4.

        Note: Section 4 accumulates across iterations (append-only).
        """
        section_content = f"""### Iteration {result.iteration}
**Action:** {result.action}
**Reasoning:** {result.reasoning}

"""
        # Tool results
        if result.tool_results:
            section_content += "**Tools Called:**\n"
            for tr in result.tool_results:
                status = "SUCCESS" if tr.success else "FAILED"
                section_content += f"- `{tr.tool}` -> {status}"
                if tr.goal_id:
                    section_content += f" (Goal: {tr.goal_id})"
                section_content += "\n"
            section_content += "\n"

        # Claims
        if result.claims_extracted:
            section_content += "**Claims Extracted:**\n"
            section_content += "| Claim | Confidence | Source | TTL |\n"
            section_content += "|-------|------------|--------|-----|\n"
            for claim in result.claims_extracted:
                ttl = f"{claim.ttl_hours}h" if claim.ttl_hours else "N/A"
                section_content += f"| {claim.claim} | {claim.confidence:.2f} | {claim.source} | {ttl} |\n"
            section_content += "\n"

        # Progress
        if result.progress_summary:
            section_content += f"**Progress:** {result.progress_summary}\n\n"

        # Check if section 4 exists, if not create header
        if "## 4. Tool Results" not in self.content and "## 4. Tool Execution" not in self.content:
            full_section = f"## 4. Tool Results\n\n{section_content}"
            self._append_section(4, full_section)
        else:
            # Append to existing section 4
            self._content = self.content + section_content
            self._save()

    def write_section_6(self, result: SynthesisResult, attempt: int = 1) -> None:
        """Write Phase 6 response to section 6."""
        attempt_header = f" (Attempt {attempt})" if attempt > 1 else ""

        section_content = f"""## 6. Response{attempt_header}

**Response Preview:**
{result.response_preview}

"""
        # Validation checklist
        if result.validation_checklist:
            section_content += "**Validation Checklist:**\n"
            for check, passed in result.validation_checklist.items():
                mark = "x" if passed else " "
                section_content += f"- [{mark}] {check}\n"
            section_content += "\n"

        self._append_section(6, section_content)

    def write_section_7(self, result: ValidationResult, attempt: int = 1) -> None:
        """Write Phase 7 validation to section 7."""
        attempt_header = f" (Attempt {attempt})" if attempt > 1 else ""

        section_content = f"""## 7. Validation{attempt_header}

**Decision:** {result.decision.value}
**Confidence:** {result.confidence:.2f}

"""
        # Checks
        if result.checks:
            section_content += "### Checks\n"
            section_content += "| Check | Result |\n|-------|--------|\n"
            for check in result.checks:
                status = "PASS" if check.passed else "FAIL"
                section_content += f"| {check.name} | {status} |\n"
            section_content += "\n"

        # Goal validations
        if result.goal_validations:
            section_content += "### Per-Goal Validation\n"
            section_content += "| Goal | Addressed | Quality | Notes |\n"
            section_content += "|------|-----------|---------|-------|\n"
            for gv in result.goal_validations:
                mark = "Y" if gv.addressed else "N"
                section_content += f"| {gv.goal_id} | {mark} | {gv.quality:.2f} | {gv.notes or ''} |\n"
            section_content += "\n"

        # Issues
        if result.issues:
            section_content += "### Issues\n"
            for issue in result.issues:
                section_content += f"- {issue}\n"
            section_content += "\n"

        # Revision hints
        if result.revision_hints:
            section_content += f"### Revision Hints\n{result.revision_hints}\n\n"

        # Overall quality
        if result.overall_quality is not None:
            section_content += f"**Overall Quality:** {result.overall_quality:.2f}\n\n"

        self._append_section(7, section_content)

    def get_full_context(self) -> str:
        """Get complete context.md content."""
        return self.content

    def get_sections(self, *sections: int) -> str:
        """
        Get content of specified sections combined.

        Args:
            *sections: Section numbers to include

        Returns:
            Combined section content
        """
        parts = []
        for section in sections:
            content = self.read_section(section)
            if content:
                parts.append(f"{self.SECTION_HEADERS[section]}\n{content}")
        return "\n\n".join(parts)

    def get_original_query(self) -> str:
        """
        Extract the original query from section 0.

        This is critical for LLM context discipline - the original query
        contains user priorities ("cheapest", "best") that must be passed
        to all LLMs making decisions.

        Returns:
            Original query string
        """
        section_0 = self.read_section(0)
        # Parse "**Original:** {query}" format
        for line in section_0.split("\n"):
            if line.startswith("**Original:**"):
                return line.replace("**Original:**", "").strip()
        return ""

    def get_word_count(self, section: int) -> int:
        """
        Get word count for a section.

        Used to track section size for auto-compression triggering.

        Args:
            section: Section number (0-6)

        Returns:
            Word count
        """
        content = self.read_section(section)
        return len(content.split())

    def get_total_word_count(self) -> int:
        """Get total word count across all sections."""
        return len(self.content.split())

    def _replace_section(self, section: int, new_content: str) -> None:
        """Replace an entire section."""
        header = self.SECTION_HEADERS[section]
        content = self.content

        # Find section
        start_idx = content.find(header)
        if start_idx == -1:
            # Section doesn't exist, append it
            self._content = content + "\n" + new_content
        else:
            # Find end of section
            end_idx = len(content)
            for next_section in range(section + 1, 7):
                next_header = self.SECTION_HEADERS[next_section]
                next_idx = content.find(next_header, start_idx)
                if next_idx != -1:
                    end_idx = next_idx
                    break

            # Replace section
            self._content = content[:start_idx] + new_content + content[end_idx:]

        self._save()

    def _append_section(self, section: int, content: str) -> None:
        """Append content as a new section (append-only behavior)."""
        # Just append - sections are in order
        self._content = self.content + content
        self._save()

    def _save(self) -> None:
        """Save context.md to disk."""
        self.turn_dir.mkdir(parents=True, exist_ok=True)
        self.context_path.write_text(self._content)

    def reload(self) -> None:
        """Force reload content from disk."""
        self._content = None
        _ = self.content  # Trigger reload
