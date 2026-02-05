"""
ContextDocument: The single accumulating document for each turn.

This module implements the unified document IO architecture where context.md
is the only document that accumulates through the pipeline. Each phase reads
the current state and appends its output section.

Pandora 8-Phase Pipeline context.md sections:
    §0: Original Query (Phase 1 input)
    §1: Query Analysis (Phase 1 output)
    §2: Gathered Context (Phase 2.1/2.2 output)
    §3: Plan (Phase 3 output)
    §4: Tool Results (Phase 4/5 output - accumulates)
    §5: UNUSED (§4 accumulates for Executor + Coordinator)
    §6: Response (Phase 6 output)
    §7: Validation (Phase 7 output)
    Note: Phase 8 (Save) is procedural, doesn't add sections.

Architecture Reference:
    architecture/concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
import json
from datetime import datetime


@dataclass
class ExecutionState:
    """
    Tracks execution state for visibility in context.md header.

    This implements Factor 5 (Unify State) from 12-Factor Agents:
    - All state (phase, iteration, error count) visible in the document
    - Enables debugging by seeing exactly where execution stopped
    - Supports future pause/resume from saved state

    The state is serialized as an HTML comment in context.md header,
    making it invisible to LLMs but visible to developers and tooling.
    """
    current_phase: int = 0
    phase_name: str = ""
    iteration: int = 1
    max_iterations: int = 3
    consecutive_errors: int = 0
    decision_history: List[str] = field(default_factory=list)
    last_decision: str = ""
    started_at: str = ""  # ISO timestamp

    def to_comment_block(self) -> str:
        """Format execution state as HTML comment for context.md header."""
        decisions_str = " → ".join(self.decision_history[-5:]) if self.decision_history else "none"
        return f"""<!-- execution_state
phase: {self.current_phase} ({self.phase_name})
iteration: {self.iteration}/{self.max_iterations}
errors: {self.consecutive_errors}
last_decision: {self.last_decision or 'none'}
decisions: {decisions_str}
started: {self.started_at}
-->"""


@dataclass
class SourceReference:
    """A reference to a source document used in context gathering."""
    path: str
    summary: str
    relevance: float = 0.0

    def to_markdown(self, index: int) -> str:
        return f"- [{index}] {self.path} - \"{self.summary}\""


@dataclass
class Claim:
    """A claim extracted from tool results with provenance."""
    content: str
    confidence: float
    source: str
    ttl_hours: int = 24

    def to_table_row(self) -> str:
        return f"| {self.content} | {self.confidence:.2f} | {self.source} | {self.ttl_hours}h |"


class ContextDocument:
    """
    Manages the accumulating context.md document.

    Pandora 8-Phase Pipeline section mapping:
    - Header: Turn number, session ID, mode, repo (if code mode)
    - §0: Original Query (Phase 1 input - immutable)
    - §1: Query Analysis (Phase 1 output)
    - §2: Gathered Context (Phase 2.1/2.2 output)
    - §3: Plan (Phase 3 output)
    - §4: Tool Results (Phase 4/5 output - accumulates)
    - §6: Response (Phase 6 output)
    - §7: Validation (Phase 7 output)

    Note: §5 is not used (§4 accumulates for Executor + Coordinator).
    Note: Phase 8 (Save) is procedural and doesn't add sections.

    Usage:
        doc = ContextDocument(turn_number=743, session_id="default", query="...")
        doc.append_section(1, "Query Analysis", content)
        doc.append_section(2, "Gathered Context", content)
        ...
        doc.append_section(7, "Validation", content)
        doc.save(turn_dir)
    """

    # Section titles aligned with 8-phase pipeline
    SECTION_TITLES = {
        0: "Original Query",         # Phase 1 input
        1: "Query Analysis",         # Phase 1 output
        2: "Gathered Context",       # Phase 2.1/2.2 output
        3: "Plan",                   # Phase 3 output
        4: "Tool Results",           # Phase 4/5 output (accumulates)
        6: "Response",               # Phase 6 output
        7: "Validation"              # Phase 7 output
    }

    def __init__(self, turn_number: int, session_id: str, query: str):
        self.turn_number = turn_number
        self.session_id = session_id
        self.query = query  # Original query string (for backward compatibility)
        self.sections: Dict[int, dict] = {}  # §1-6 appended by each phase
        self.source_references: List[SourceReference] = []
        self.claims: List[Claim] = []
        self.created_at = datetime.now()
        self.metadata: Dict[str, Any] = {}  # Arbitrary metadata (e.g., knowledge_context)
        self.phase_hint: Optional[str] = None  # Research phase hint from Planner (phase2_only, etc.)
        self.mode: Optional[str] = None  # "chat" or "code" - set by unified_flow
        self.repo: Optional[str] = None  # Repository path for code mode context gathering
        # Full query analysis from Phase 1 (THE SOURCE OF TRUTH)
        # Contains: resolved_query, user_purpose, data_requirements, reference_resolution, validation
        self.query_analysis: Optional[Dict[str, Any]] = None
        # Execution state for 12-Factor Agent visibility (Factor 5: Unify State)
        self.execution_state = ExecutionState(started_at=datetime.now().isoformat())
        # LLM-selected workflow (from Phase 3 STRATEGIC_PLAN)
        # Used by Phase 4 executor to pick the right workflow without intent heuristics
        self.workflow: Optional[str] = None  # e.g., "product_search", "intelligence_search"
        self.workflow_reason: Optional[str] = None  # Why this workflow was selected

    # =========================================================================
    # §0 Query Analysis Methods (Document-Based IO Pattern)
    # =========================================================================

    def set_section_0(self, query_analysis: Dict[str, Any]):
        """
        Set §0 with full query analysis from Phase 1.

        This is the canonical way to store Phase 1 output. All downstream phases
        should read user_purpose from here using get_user_purpose() and related helpers.

        Args:
            query_analysis: Dict containing:
                - resolved_query: str (query with references made explicit)
                - user_purpose: str (natural language statement of what user wants)
                - data_requirements: dict (needs_current_prices, needs_product_urls, etc.)
                - reference_resolution: dict (status, original_references, resolved_to)
                - mode: str (chat, code)
                - content_reference: dict or None
                - reasoning: str
                - validation: dict (status, issues, retry_guidance, clarification_question)
        """
        self.query_analysis = query_analysis
        # Update original query if provided
        if query_analysis.get("original_query"):
            self.query = query_analysis["original_query"]
        elif query_analysis.get("resolved_query"):
            self.query = query_analysis["resolved_query"]

    def get_user_purpose(self) -> str:
        """
        Get natural language user purpose from §0.

        This is the primary way downstream phases understand what the user wants.
        Returns a 2-4 sentence description of user's goal, priorities, and constraints.

        Returns:
            Natural language purpose statement, or empty string if not set.
        """
        if self.query_analysis:
            return self.query_analysis.get("user_purpose", "")
        return ""

    def get_action_needed(self) -> str:
        """
        Get action type needed to satisfy the request from §0.

        Note: This is a legacy field retained for backward compatibility.
        The modern approach uses workflow selection in Phase 3 rather than
        action classification in Phase 1.

        Returns:
            Action type: live_search, recall_memory, answer_from_context,
                        navigate_to_site, execute_code, unclear
            Defaults to "unclear" if not set.
        """
        if self.query_analysis:
            return self.query_analysis.get("action_needed", "unclear")
        return "unclear"

    def get_data_requirements(self) -> Dict[str, Any]:
        """
        Get data requirements from §0.

        Returns:
            Dict with requirements like:
            - needs_current_prices: bool
            - needs_product_urls: bool
            - needs_live_data: bool
            - freshness_required: str ("< 1 hour", "< 24 hours", "any", null)
        """
        if self.query_analysis:
            return self.query_analysis.get("data_requirements", {})
        return {}

    def get_prior_context(self) -> Dict[str, Any]:
        """
        Get prior-context relationship from §0.

        Note: This is a legacy field retained for backward compatibility.
        The modern approach uses N-1 context loading in Phase 2.1/2.2 rather
        than explicit prior_context tracking in Phase 1.

        Returns:
            Dict with:
            - continues_topic: str or None
            - prior_turn_purpose: str or None
            - relationship: str (continuation, verification, modification, new_topic)
        """
        if self.query_analysis:
            return self.query_analysis.get("prior_context", {})
        return {}

    def get_resolved_query(self) -> str:
        """
        Get resolved query from §0.

        The resolved query has references made explicit (e.g., "it" -> "the laptop").

        Returns:
            Resolved query string, or original query if not resolved.
        """
        if self.query_analysis:
            return self.query_analysis.get("resolved_query", self.query)
        return self.query

    def get_relationship(self) -> str:
        """
        Get relationship to prior turn from §0.

        Returns:
            Relationship type: continuation, verification, modification, new_topic
            Defaults to "new_topic" if not set.
        """
        prior_context = self.get_prior_context()
        return prior_context.get("relationship", "new_topic")

    def get_content_reference(self) -> Optional[Dict[str, Any]]:
        """
        Get content reference from §0 (if user is asking about specific prior content).

        Returns:
            Dict with reference info or None:
            - title: str
            - content_type: str (thread, article, product, etc.)
            - site: str
            - source_turn: int
            - source_url: str (if available)
        """
        if self.query_analysis:
            return self.query_analysis.get("content_reference")
        return None

    def _format_section_0(self) -> str:
        """
        Format §0 with full query analysis for markdown output.

        Returns structured §0 content that downstream LLMs can read.
        """
        if not self.query_analysis:
            # Fallback for legacy documents without full query_analysis
            return self.query

        qa = self.query_analysis
        lines = []

        # Original and resolved queries
        lines.append(f"**Original:** {qa.get('original_query', self.query)}")
        resolved = qa.get('resolved_query', '')
        if resolved and resolved != qa.get('original_query', self.query):
            lines.append(f"**Resolved:** {resolved}")
            lines.append(f"**Was Resolved:** true")
        else:
            lines.append(f"**Was Resolved:** false")

        # User purpose (natural language statement of what user wants)
        user_purpose = qa.get('user_purpose', '')
        if user_purpose:
            lines.append(f"**User Purpose:** {user_purpose}")

        # Mode (UI-provided)
        lines.append(f"**Mode:** {qa.get('mode', 'chat')}")

        # Data requirements
        data_reqs = qa.get('data_requirements', {})
        if data_reqs:
            lines.append("**Data Requirements:**")
            if data_reqs.get('needs_current_prices'):
                lines.append("- Needs current prices: yes")
            if data_reqs.get('needs_product_urls'):
                lines.append("- Needs product URLs: yes")
            if data_reqs.get('needs_live_data'):
                lines.append("- Needs live data: yes")
            if data_reqs.get('freshness_required'):
                lines.append(f"- Freshness required: {data_reqs['freshness_required']}")

        # Reference resolution
        ref_res = qa.get('reference_resolution', {})
        if ref_res:
            lines.append("**Reference Resolution:**")
            lines.append(f"- Status: {ref_res.get('status', 'not_needed')}")
            original_refs = ref_res.get('original_references') or []
            if original_refs:
                lines.append(f"- Original references: {', '.join(original_refs)}")
            if ref_res.get('resolved_to'):
                lines.append(f"- Resolved to: {ref_res['resolved_to']}")

        # Content reference (if asking about specific prior content)
        ref = qa.get('content_reference')
        if ref:
            lines.append("")
            lines.append("**Content Reference:**")
            lines.append(f"- Title: {ref.get('title', 'N/A')}")
            lines.append(f"- Type: {ref.get('content_type', 'N/A')}")
            lines.append(f"- Site: {ref.get('site', 'N/A')}")
            lines.append(f"- Source Turn: {ref.get('source_turn', 'N/A')}")
            if ref.get('source_url'):
                lines.append(f"- Source URL: {ref['source_url']}")

        # Reasoning
        if qa.get('reasoning'):
            lines.append("")
            lines.append(f"**Reasoning:** {qa['reasoning']}")

        # Validation (Phase 1.5)
        validation = qa.get("validation") or {}
        if validation:
            lines.append("")
            lines.append("**Validation:**")
            lines.append(f"- Status: {validation.get('status', 'pass')}")
            if validation.get("confidence") is not None:
                lines.append(f"- Confidence: {validation.get('confidence')}")
            issues = validation.get("issues") or []
            if issues:
                lines.append(f"- Issues: {', '.join(issues)}")
            retry_guidance = validation.get("retry_guidance") or []
            if retry_guidance:
                lines.append(f"- Retry guidance: {', '.join(retry_guidance)}")
            if validation.get("clarification_question"):
                lines.append(f"- Clarification question: {validation.get('clarification_question')}")

        return "\n".join(lines)

    # =========================================================================
    # Section Management Methods
    # =========================================================================

    def append_section(self, section_num: int, title: str, content: str):
        """
        Append a new section to the document (§1-6 only).

        Args:
            section_num: Section number (1-7)
            title: Section title (e.g., "Gathered Context")
            content: Markdown content for the section

        Raises:
            ValueError: If section_num is not 1-7 or section already exists
        """
        if section_num < 1 or section_num > 7:
            raise ValueError(f"Section must be 1-7 (§0 is query, set at init). Got: {section_num}")
        if section_num in self.sections:
            raise ValueError(f"Section {section_num} already exists. Cannot overwrite.")
        self.sections[section_num] = {"title": title, "content": content}

    def extend_section(self, section_num: int, additional_content: str):
        """
        Extend an existing section with additional content.

        Used for GATHER_MORE loops where we need to add more context
        without losing existing provenance.

        Args:
            section_num: Section number (1-7)
            additional_content: Content to append to the section

        Raises:
            ValueError: If section doesn't exist or section_num invalid
        """
        if section_num < 1 or section_num > 7:
            raise ValueError(f"Section must be 1-7. Got: {section_num}")
        if section_num not in self.sections:
            raise ValueError(f"Section {section_num} doesn't exist. Use append_section first.")

        # Append to existing content with separator
        current_content = self.sections[section_num]["content"]
        self.sections[section_num]["content"] = f"{current_content}\n\n{additional_content}"

    def update_section(self, section_num: int, new_content: str):
        """
        Replace the content of an existing section.

        Used for revision loops where we need to update the draft response.

        Args:
            section_num: Section number (1-7)
            new_content: New content to replace existing content

        Raises:
            ValueError: If section doesn't exist or section_num invalid
        """
        if section_num < 1 or section_num > 7:
            raise ValueError(f"Section must be 1-7. Got: {section_num}")
        if section_num not in self.sections:
            raise ValueError(f"Section {section_num} doesn't exist. Use append_section first.")

        # Replace content, keep title
        self.sections[section_num]["content"] = new_content

    def append_to_section(self, section_num: int, content: str, separator: str = "\n\n---\n\n"):
        """
        Append content to a section, creating it if needed.

        Used for iterative loops (like Planner-Coordinator) where each iteration
        appends results without overwriting previous iterations.

        Args:
            section_num: Section number (1-7)
            content: Content to append
            separator: Separator between iterations (default: horizontal rule)
        """
        if section_num < 1 or section_num > 7:
            raise ValueError(f"Section must be 1-7. Got: {section_num}")

        if section_num not in self.sections:
            # Create section with standard title
            title = self.SECTION_TITLES.get(section_num, f"Section {section_num}")
            self.sections[section_num] = {"title": title, "content": content}
        else:
            # Append to existing content
            current = self.sections[section_num]["content"]
            self.sections[section_num]["content"] = f"{current}{separator}{content}"

    def add_source_reference(self, path: str, summary: str, relevance: float = 0.0):
        """Add a source reference for context provenance."""
        self.source_references.append(SourceReference(path, summary, relevance))

    def add_claim(self, content: str, confidence: float, source: str, ttl_hours: int = 24):
        """Add a claim extracted from tool results."""
        self.claims.append(Claim(content, confidence, source, ttl_hours))

    def update_execution_state(
        self,
        phase: int,
        phase_name: str,
        iteration: int = None,
        max_iterations: int = None,
        consecutive_errors: int = None
    ):
        """
        Update execution state for visibility in context.md.

        Called at phase transitions to track pipeline progress.
        State is visible in context.md header as HTML comment.

        Args:
            phase: Current phase number (1-8)
            phase_name: Human-readable phase name (e.g., "QueryAnalyzer", "Planner", "Executor")
            iteration: Current iteration within phase (for loops)
            max_iterations: Maximum iterations allowed
            consecutive_errors: Count of consecutive tool failures
        """
        self.execution_state.current_phase = phase
        self.execution_state.phase_name = phase_name
        if iteration is not None:
            self.execution_state.iteration = iteration
        if max_iterations is not None:
            self.execution_state.max_iterations = max_iterations
        if consecutive_errors is not None:
            self.execution_state.consecutive_errors = consecutive_errors

    def record_decision(self, decision: str):
        """
        Record a decision for history tracking.

        Decisions include: PROCEED, CLARIFY, EXECUTE, COMPLETE,
        APPROVE, REVISE, RETRY, FAIL, etc.

        Args:
            decision: The decision made (e.g., "EXECUTE", "APPROVE")
        """
        self.execution_state.decision_history.append(decision)
        self.execution_state.last_decision = decision
        # Keep only last 10 decisions to prevent unbounded growth
        if len(self.execution_state.decision_history) > 10:
            self.execution_state.decision_history = self.execution_state.decision_history[-10:]

    def get_section(self, section_num: int) -> Optional[str]:
        """
        Get the content of a specific section.

        For §0, returns formatted query analysis if available, otherwise raw query.
        """
        if section_num == 0:
            if self.query_analysis:
                return self._format_section_0()
            return self.query
        if section_num in self.sections:
            return self.sections[section_num]["content"]
        return None

    def has_section(self, section_num: int) -> bool:
        """Check if a section exists."""
        if section_num == 0:
            return True  # Query always exists
        return section_num in self.sections

    def get_latest_section(self) -> int:
        """Get the highest section number that exists."""
        if not self.sections:
            return 0
        return max(self.sections.keys())

    def get_markdown(self) -> str:
        """
        Return complete markdown document with §0-§7.

        Format:
        <!-- execution_state ... -->  (if tracking started)

        # Context Document
        **Turn:** {turn_number}
        **Session:** {session_id}

        ---

        ## 0. User Query

        {query}

        ---

        ## 1. Gathered Context
        ...
        """
        lines = []

        # Execution state header (only if tracking started, i.e., phase > 0)
        # This implements Factor 5 (Unify State) from 12-Factor Agents
        # HTML comment format makes it invisible to LLMs but visible to developers
        if self.execution_state.current_phase > 0:
            lines.append(self.execution_state.to_comment_block())
            lines.append("")

        # Build header with mode and repo if available
        header_lines = [
            "# Context Document",
            f"**Turn:** {self.turn_number}",
            f"**Session:** {self.session_id}",
        ]
        if self.mode:
            header_lines.append(f"**Mode:** {self.mode}")
        if self.repo:
            header_lines.append(f"**Repository:** {self.repo}")

        lines = lines + header_lines + [
            "",
        ]

        # §0 with full query analysis (if available) or raw query
        section_0_content = self._format_section_0() if self.query_analysis else self.query
        lines.extend([
            "---",
            "",
            "## 0. User Query",
            "",
            section_0_content,
            ""
        ])

        for i in range(1, 7):
            if i in self.sections:
                lines.extend([
                    "---",
                    "",
                    f"## {i}. {self.sections[i]['title']}",
                    "",
                    self.sections[i]['content'],
                    ""
                ])

        return "\n".join(lines).rstrip() + "\n"

    def get_markdown_up_to(self, section_num: int) -> str:
        """
        Get markdown up to and including a specific section.

        Useful for passing partial context to a phase that shouldn't see later sections.
        """
        lines = []

        # Execution state header (only if tracking started)
        if self.execution_state.current_phase > 0:
            lines.append(self.execution_state.to_comment_block())
            lines.append("")

        # Build header with mode and repo if available
        header_lines = [
            "# Context Document",
            f"**Turn:** {self.turn_number}",
            f"**Session:** {self.session_id}",
        ]
        if self.mode:
            header_lines.append(f"**Mode:** {self.mode}")
        if self.repo:
            header_lines.append(f"**Repository:** {self.repo}")

        # §0 with full query analysis (if available) or raw query
        section_0_content = self._format_section_0() if self.query_analysis else self.query
        lines = lines + header_lines + [
            "",
            "---",
            "",
            "## 0. User Query",
            "",
            section_0_content,
            ""
        ]

        for i in range(1, min(section_num + 1, 7)):
            if i in self.sections:
                lines.extend([
                    "---",
                    "",
                    f"## {i}. {self.sections[i]['title']}",
                    "",
                    self.sections[i]['content'],
                    ""
                ])

        return "\n".join(lines).rstrip() + "\n"

    def save(self, turn_dir: Path):
        """Save context.md to the turn directory."""
        turn_dir.mkdir(parents=True, exist_ok=True)
        (turn_dir / "context.md").write_text(self.get_markdown())

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "turn_number": self.turn_number,
            "session_id": self.session_id,
            "query": self.query,
            "sections": self.sections,
            "source_references": [
                {"path": sr.path, "summary": sr.summary, "relevance": sr.relevance}
                for sr in self.source_references
            ],
            "claims": [
                {"content": c.content, "confidence": c.confidence, "source": c.source, "ttl_hours": c.ttl_hours}
                for c in self.claims
            ],
            "created_at": self.created_at.isoformat()
        }

    @classmethod
    def from_markdown(cls, markdown: str) -> "ContextDocument":
        """
        Parse a context.md file back into a ContextDocument.

        Useful for loading prior turns for search/analysis.
        """
        lines = markdown.split("\n")

        # Parse header
        turn_number = 0
        session_id = ""
        for line in lines[:10]:
            if line.startswith("**Turn:**"):
                turn_number = int(line.split(":")[1].strip())
            elif line.startswith("**Session:**"):
                session_id = line.split(":")[1].strip()

        # Find sections
        sections = {}
        current_section = None
        current_content = []
        query = ""

        for i, line in enumerate(lines):
            if line.startswith("## 0. User Query"):
                current_section = 0
                current_content = []
            elif line.startswith("## ") and ". " in line:
                # Save previous section
                if current_section == 0:
                    query = "\n".join(current_content).strip()
                elif current_section is not None:
                    content = "\n".join(current_content).strip()
                    # Extract title from the header line
                    title_line = lines[i - len(current_content) - 2] if i > len(current_content) + 2 else ""
                    title = line.split(". ", 1)[1] if ". " in line else f"Section {current_section}"
                    sections[current_section] = {"title": title, "content": content}

                # Start new section
                parts = line.replace("## ", "").split(". ", 1)
                try:
                    current_section = int(parts[0])
                except ValueError:
                    current_section = None
                current_content = []
            elif line == "---":
                continue
            elif current_section is not None:
                current_content.append(line)

        # Save last section
        if current_section == 0:
            query = "\n".join(current_content).strip()
        elif current_section is not None:
            content = "\n".join(current_content).strip()
            sections[current_section] = {"title": cls.SECTION_TITLES.get(current_section, f"Section {current_section}"), "content": content}

        doc = cls(turn_number, session_id, query)
        doc.sections = {k: v for k, v in sections.items() if k > 0}
        return doc


@dataclass
class TurnMetadata:
    """
    Metadata for a turn, used for indexing and search.

    Saved as metadata.json in each turn directory.

    Learning fields (per MEMORY_ARCHITECTURE.md):
    - validation_outcome: APPROVE, RETRY, REVISE, FAIL
    - quality_score: 0.0-1.0 (this IS the confidence)
    - strategy_summary: What plan was used (from section 3)
    """
    turn_number: int
    session_id: str
    timestamp: float
    topic: str = ""
    action_needed: str = ""
    workflows_used: List[str] = field(default_factory=list)
    content_type: str = ""
    claims_count: int = 0
    response_quality: float = 0.0
    keywords: List[str] = field(default_factory=list)
    # Learning fields for turn indexing (indexed in TurnIndexDB for retrieval)
    validation_outcome: str = ""  # APPROVE, RETRY, REVISE, FAIL
    quality_score: float = 0.0    # 0.0-1.0 (validation confidence)
    strategy_summary: str = ""    # From section 3 (task plan approach)
    # Legacy learning metadata (for backward compatibility)
    learning: Optional[Dict[str, Any]] = None

    def save(self, turn_dir: Path):
        """Save as metadata.json."""
        turn_dir.mkdir(parents=True, exist_ok=True)
        (turn_dir / "metadata.json").write_text(json.dumps(self.to_dict(), indent=2))

    def to_dict(self) -> dict:
        result = {
            "turn_number": self.turn_number,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "topic": self.topic,
            "workflows_used": self.workflows_used,
            "content_type": self.content_type,
            "claims_count": self.claims_count,
            "response_quality": self.response_quality,
            "keywords": self.keywords,
            # Learning fields (per MEMORY_ARCHITECTURE.md)
            "validation_outcome": self.validation_outcome,
            "quality_score": self.quality_score,
            "strategy_summary": self.strategy_summary
        }
        # Include legacy learning metadata if present
        if self.learning:
            result["learning"] = self.learning
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "TurnMetadata":
        metadata = cls(
            turn_number=data.get("turn_number", 0),
            session_id=data.get("session_id", ""),
            timestamp=data.get("timestamp", 0.0),
            topic=data.get("topic", ""),
            action_needed=data.get("action_needed") or data.get("intent", ""),
            workflows_used=data.get("workflows_used", []),
            content_type=data.get("content_type", ""),
            claims_count=data.get("claims_count", 0),
            response_quality=data.get("response_quality", 0.0),
            keywords=data.get("keywords", []),
            # Learning fields
            validation_outcome=data.get("validation_outcome", ""),
            quality_score=data.get("quality_score", 0.0),
            strategy_summary=data.get("strategy_summary", "")
        )
        # Load legacy learning metadata if present
        if "learning" in data:
            metadata.learning = data["learning"]
        return metadata

    @classmethod
    def load(cls, turn_dir: Path) -> Optional["TurnMetadata"]:
        """Load from metadata.json."""
        metadata_path = turn_dir / "metadata.json"
        if not metadata_path.exists():
            return None
        try:
            data = json.loads(metadata_path.read_text())
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None


def extract_keywords(text: str, max_keywords: int = 10) -> List[str]:
    """
    Simple keyword extraction from text.

    Uses basic frequency analysis. Could be enhanced with TF-IDF or entity extraction.
    """
    import re
    from collections import Counter

    # Normalize and tokenize
    text = text.lower()
    words = re.findall(r'\b[a-z]{3,}\b', text)

    # Remove common stop words
    stop_words = {
        'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had',
        'her', 'was', 'one', 'our', 'out', 'has', 'have', 'been', 'would',
        'could', 'should', 'will', 'just', 'what', 'with', 'this', 'that',
        'from', 'they', 'which', 'their', 'there', 'about', 'into', 'more',
        'some', 'than', 'them', 'then', 'these', 'when', 'where', 'your'
    }
    words = [w for w in words if w not in stop_words]

    # Count and return top keywords
    counter = Counter(words)
    return [word for word, _ in counter.most_common(max_keywords)]
