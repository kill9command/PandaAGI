# Phase 3: Document IO System

**Dependencies:** Phase 2 (Core Libraries)
**Priority:** Critical
**Estimated Effort:** 2-3 days

---

## Architecture Linkages

This section documents how each implementation decision traces back to the architecture documentation.

### Context Manager (context.md with §0-§6)

**Architecture Reference:** `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md#3-contextmd-specification`

> `context.md` is the **single working document** that accumulates state across all phases of the pipeline. Each phase reads the document, performs its work, and appends a new section.
>
> **Key Design Principles:**
> - Single source of truth for the turn
> - Append-only during pipeline execution
> - Sections numbered 0-6 mapping to phases
> - Original query always preserved in section 0

**Why This Design:** The `SECTION_HEADERS` dictionary (§0-§6) mirrors the architecture exactly. Section immutability is enforced - `write_section_0()` enriches but never replaces the original query. `_append_section()` ensures append-only behavior. Context discipline preserves the original query so every LLM phase can read user priorities ("cheapest", "best") directly.

---

### Turn Manager (Sequential Numbering)

**Architecture Reference:** `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md#13-file-structure`, `architecture/main-system-patterns/phase7-save.md`

> Turn directories use zero-padded 6-digit numbering:
> - `turn_000001/` (turn 1)
> - `turn_000742/` (turn 742)
>
> **Note:** Turn numbers are per-user (each user starts at turn 1)

**Why Per-User Numbering:** `get_next_turn_number()` scans the user's turns directory to find the highest existing turn number. The `f"turn_{turn_number:06d}"` format matches the architecture spec. Per-user storage path `users/{user_id}/turns/` provides namespace isolation. Session-based isolation (session_id = permanent user identity).

---

### Research Manager (Evergreen vs Time-Sensitive)

**Architecture Reference:** `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md#4-researchmd-specification`

> **Purpose:** Contains full research results from internet.research tool calls:
> - Evergreen knowledge (facts that don't expire)
> - Time-sensitive data (prices, availability)
>
> ```markdown
> ## Evergreen Knowledge
> *Facts that don't expire:*
>
> ## Time-Sensitive Data
> *Expires in 6 hours:*
> ```

**Why Dual Sections:** The `create()` method generates research.md with explicit `## Evergreen Knowledge` and `## Time-Sensitive Data` sections. TTL-based expiration (`expires = timestamp + timedelta(hours=6)`) matches the 6-hour TTL specification. `append_evergreen()` and `append_time_sensitive()` ensure knowledge is categorized correctly. JSON companion file (`research.json`) supports indexing in ResearchIndexDB.

---

### Link Formatter (Dual Markdown + Wikilink)

**Architecture Reference:** `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md#9-obsidian-integration`

> Every document reference includes both link styles:
> ```markdown
> - [turn_000815/context.md](../turn_000815/context.md) | [[turns/turn_000815/context|turn_000815]]
> ```
> - **Markdown link** (left): Relative path for LLMs and programmatic access
> - **Wikilink** (right): Obsidian navigation, graph view, backlinks

**Why Dual Format:** `dual_link()` generates the exact format specified: `"[label](rel_path) | [[vault_path|label]]"`. Relative markdown links (via `os.path.relpath()`) enable programmatic link-following by LLMs. Wikilinks remove file extensions (`.with_suffix("")`) matching Obsidian conventions. `block_link()` supports block-level linking (`[[path#^block-id|label]]`) for claims and decisions.

---

### Webpage Cache Manager

**Architecture Reference:** `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md#6-webpage_cache-specification`

> **Purpose:** When the system visits a web page, it creates a webpage_cache capturing everything about that visit. This enables answering follow-up questions from cached data without re-navigating.
>
> **Retrieval Hierarchy:**
> | Priority | Source | Speed |
> |----------|--------|-------|
> | 1 | manifest.json content_summary | Instant |
> | 2 | extracted_data.json | Instant |
> | 3 | page_content.md | Instant |
> | 4 | Navigate to source_url | Slow |

**Why Cache-First:** Context Gatherer checks `webpage_cache` FIRST before routing to Research. Manifest format matches architecture exactly: url, url_slug, title, visited_at, captured flags, content_summary, answerable_questions. Three-file capture: `page_content.md`, `extracted_data.json`, screenshot. `can_answer_from_cache()` implements the cache-first retrieval pattern. URL slug generation creates filesystem-safe slugs truncated to 100 characters.

---

## Overview

This phase implements the document-centric IO model:
- context.md management (§0-§6 sections)
- Turn lifecycle management
- Research document handling
- Link formatting (dual Markdown + Wikilink)
- Webpage cache management

**Key Principle:** Everything is a document. All state flows through `context.md`.

---

## 1. Context Manager

### 1.1 `libs/document_io/context_manager.py`

```python
"""Context document manager for PandaAI v2.

Manages context.md - the single working document that accumulates
state across all phases of the pipeline.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import re

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
    """Manages context.md document operations."""

    SECTION_HEADERS = {
        0: "## 0. User Query",
        1: "## 1. Reflection Decision",
        2: "## 2. Gathered Context",
        3: "## 3. Task Plan",
        4: "## 4. Tool Execution",
        5: "## 5. Synthesis",
        6: "## 6. Validation",
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
            raw_query: Original user query
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

        Args:
            analysis: Query analysis from Phase 0
        """
        section_content = f"""## 0. User Query

**Original:** {analysis.original_query}

**Resolved:** {analysis.resolved_query}
**Query Type:** {analysis.query_type.value}
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
            if ref.has_webpage_cache:
                section_content += f"- Webpage Cache: {ref.webpage_cache_path}\n"

        section_content += f"""
**Reasoning:** {analysis.reasoning}

"""
        self._replace_section(0, section_content)

    def write_section_1(self, result: ReflectionResult) -> None:
        """Write Phase 1 reflection decision to section 1."""
        section_content = f"""## 1. Reflection Decision

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
        """Write Phase 3 task plan to section 3."""
        attempt_header = f" (Attempt {attempt})" if attempt > 1 else ""

        section_content = f"""## 3. Task Plan{attempt_header}

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

        Note: Section 4 accumulates across iterations.
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
                section_content += f"- `{tr.tool}` → {status}"
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
        if "## 4. Tool Execution" not in self.content:
            full_section = f"## 4. Tool Execution\n\n{section_content}"
            self._append_section(4, full_section)
        else:
            # Append to existing section 4
            self._content = self.content + section_content
            self._save()

    def write_section_5(self, result: SynthesisResult, attempt: int = 1) -> None:
        """Write Phase 5 synthesis to section 5."""
        attempt_header = f" (Attempt {attempt})" if attempt > 1 else ""

        section_content = f"""## 5. Synthesis{attempt_header}

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

        self._append_section(5, section_content)

    def write_section_6(self, result: ValidationResult, attempt: int = 1) -> None:
        """Write Phase 6 validation to section 6."""
        attempt_header = f" (Attempt {attempt})" if attempt > 1 else ""

        section_content = f"""## 6. Validation{attempt_header}

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
                mark = "✓" if gv.addressed else "✗"
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

        self._append_section(6, section_content)

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
        """Append content as a new section."""
        # Just append - sections are in order
        self._content = self.content + content
        self._save()

    def _save(self) -> None:
        """Save context.md to disk."""
        self.turn_dir.mkdir(parents=True, exist_ok=True)
        self.context_path.write_text(self._content)
```

---

## 2. Turn Manager

### 2.1 `libs/document_io/turn_manager.py`

```python
"""Turn lifecycle management for PandaAI v2."""

from datetime import datetime
from pathlib import Path
from typing import Optional
import json

from libs.core.config import get_settings
from libs.core.models import TurnMetadata, Intent
from libs.document_io.context_manager import ContextManager


class TurnManager:
    """Manages turn lifecycle and storage."""

    def __init__(self, session_id: str):
        """
        Initialize turn manager for a session.

        Args:
            session_id: User session identifier (permanent user ID)
        """
        self.session_id = session_id
        self.settings = get_settings()
        self.user_dir = self.settings.panda_system_docs / "users" / session_id
        self.turns_dir = self.user_dir / "turns"

    def get_next_turn_number(self) -> int:
        """
        Get the next turn number for this session.

        Returns:
            Next sequential turn number
        """
        if not self.turns_dir.exists():
            return 1

        # Find highest existing turn number
        max_turn = 0
        for turn_dir in self.turns_dir.iterdir():
            if turn_dir.is_dir() and turn_dir.name.startswith("turn_"):
                try:
                    turn_num = int(turn_dir.name.split("_")[1])
                    max_turn = max(max_turn, turn_num)
                except (IndexError, ValueError):
                    continue

        return max_turn + 1

    def create_turn(self, query: str) -> tuple[int, ContextManager]:
        """
        Create a new turn.

        Args:
            query: User's query

        Returns:
            Tuple of (turn_number, context_manager)
        """
        turn_number = self.get_next_turn_number()
        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        turn_dir.mkdir(parents=True, exist_ok=True)

        # Create context manager
        context = ContextManager(turn_dir)
        context.create(query, self.session_id, turn_number)

        # Create initial metadata
        metadata = TurnMetadata(
            turn_number=turn_number,
            session_id=self.session_id,
            turn_dir=str(turn_dir),
        )
        self._save_metadata(turn_dir, metadata)

        return turn_number, context

    def get_turn(self, turn_number: int) -> Optional[ContextManager]:
        """
        Get context manager for an existing turn.

        Args:
            turn_number: Turn number

        Returns:
            ContextManager or None if turn doesn't exist
        """
        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        if not turn_dir.exists():
            return None
        return ContextManager(turn_dir)

    def get_recent_turns(self, limit: int = 10) -> list[TurnMetadata]:
        """
        Get metadata for recent turns.

        Args:
            limit: Maximum number of turns to return

        Returns:
            List of turn metadata, newest first
        """
        if not self.turns_dir.exists():
            return []

        turns = []
        for turn_dir in sorted(self.turns_dir.iterdir(), reverse=True):
            if len(turns) >= limit:
                break

            if turn_dir.is_dir() and turn_dir.name.startswith("turn_"):
                metadata = self._load_metadata(turn_dir)
                if metadata:
                    turns.append(metadata)

        return turns

    def get_turn_summaries(self, limit: int = 5) -> list[dict]:
        """
        Get brief summaries of recent turns for reference resolution.

        Args:
            limit: Maximum number of turns

        Returns:
            List of turn summaries with basic info
        """
        summaries = []
        turns = self.get_recent_turns(limit)

        for metadata in turns:
            turn_dir = Path(metadata.turn_dir)
            context = ContextManager(turn_dir)

            # Get §0 for query info
            section_0 = context.read_section(0)

            summaries.append({
                "turn_number": metadata.turn_number,
                "topic": metadata.topic,
                "intent": metadata.intent.value if metadata.intent else None,
                "query_preview": section_0[:200] if section_0 else "",
            })

        return summaries

    def finalize_turn(
        self,
        turn_number: int,
        topic: Optional[str] = None,
        intent: Optional[Intent] = None,
        quality: Optional[float] = None,
    ) -> None:
        """
        Finalize turn with metadata updates.

        Called by Phase 7 (Save).

        Args:
            turn_number: Turn to finalize
            topic: Inferred topic
            intent: Query intent
            quality: Overall quality score
        """
        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        metadata = self._load_metadata(turn_dir)

        if metadata:
            metadata.topic = topic or metadata.topic
            metadata.intent = intent or metadata.intent
            metadata.quality = quality or metadata.quality
            self._save_metadata(turn_dir, metadata)

    def _save_metadata(self, turn_dir: Path, metadata: TurnMetadata) -> None:
        """Save turn metadata to JSON."""
        metadata_path = turn_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata.model_dump(mode="json"), f, indent=2, default=str)

    def _load_metadata(self, turn_dir: Path) -> Optional[TurnMetadata]:
        """Load turn metadata from JSON."""
        metadata_path = turn_dir / "metadata.json"
        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path) as f:
                data = json.load(f)
            return TurnMetadata(**data)
        except Exception:
            return None
```

---

## 3. Research Manager

### 3.1 `libs/document_io/research_manager.py`

```python
"""Research document management for PandaAI v2."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
import json

from libs.core.config import get_settings


class ResearchManager:
    """Manages research.md documents."""

    def __init__(self, turn_dir: Path):
        """
        Initialize research manager.

        Args:
            turn_dir: Turn directory
        """
        self.turn_dir = turn_dir
        self.research_path = turn_dir / "research.md"
        self.research_json_path = turn_dir / "research.json"

    def create(
        self,
        query: str,
        session_id: str,
        turn_number: int,
        topic: str,
        intent: str,
    ) -> None:
        """
        Create new research.md document.

        Args:
            query: Research query
            session_id: User session
            turn_number: Turn number
            topic: Inferred topic
            intent: Query intent
        """
        timestamp = datetime.now()
        expires = timestamp + timedelta(hours=6)

        content = f"""# Research Document
**ID:** research_{turn_number}_{timestamp.strftime('%Y%m%d%H%M%S')}
**Turn:** {turn_number}
**Session:** {session_id}
**Query:** {query}

## Metadata
- **Topic:** {topic}
- **Intent:** {intent}
- **Quality:** pending
- **Created:** {timestamp.isoformat()}
- **Expires:** {expires.isoformat()} (time-sensitive data)

## Evergreen Knowledge
*Facts that don't expire:*

(To be populated by research tool)

## Time-Sensitive Data
*Expires in 6 hours:*

(To be populated by research tool)

## Linked From
- [context.md](./context.md) §4 Tool Execution

"""
        self.research_path.write_text(content)

        # Create JSON for indexing
        self._save_json({
            "turn_number": turn_number,
            "session_id": session_id,
            "topic": topic,
            "intent": intent,
            "created_at": timestamp.isoformat(),
            "expires_at": expires.isoformat(),
            "quality": None,
        })

    def append_evergreen(self, content: str) -> None:
        """Append evergreen knowledge."""
        self._append_to_section("Evergreen Knowledge", content)

    def append_time_sensitive(self, content: str) -> None:
        """Append time-sensitive data."""
        self._append_to_section("Time-Sensitive Data", content)

    def set_quality(self, quality: float) -> None:
        """Update quality score."""
        data = self._load_json()
        data["quality"] = quality
        self._save_json(data)

        # Also update in markdown
        content = self.research_path.read_text()
        content = content.replace("**Quality:** pending", f"**Quality:** {quality:.2f}")
        self.research_path.write_text(content)

    def add_findings(self, findings: list[dict]) -> None:
        """
        Add product/content findings.

        Args:
            findings: List of finding dicts with name, price, vendor, url, etc.
        """
        content = "\n### Current Listings\n"
        content += "| Product | Price | Vendor | URL |\n"
        content += "|---------|-------|--------|-----|\n"

        for finding in findings:
            name = finding.get("name", "Unknown")
            price = finding.get("price", "N/A")
            vendor = finding.get("vendor", "Unknown")
            url = finding.get("url", "#")
            content += f"| {name} | {price} | {vendor} | [link]({url}) |\n"

        content += "\n"
        self.append_time_sensitive(content)

    def _append_to_section(self, section_name: str, content: str) -> None:
        """Append content to a named section."""
        current = self.research_path.read_text()

        # Find section
        section_marker = f"## {section_name}"
        idx = current.find(section_marker)
        if idx == -1:
            return

        # Find next section or end
        next_section_idx = current.find("\n## ", idx + len(section_marker))
        if next_section_idx == -1:
            # Append at end
            self.research_path.write_text(current + "\n" + content)
        else:
            # Insert before next section
            updated = current[:next_section_idx] + "\n" + content + current[next_section_idx:]
            self.research_path.write_text(updated)

    def _save_json(self, data: dict) -> None:
        """Save research metadata JSON."""
        with open(self.research_json_path, "w") as f:
            json.dump(data, f, indent=2)

    def _load_json(self) -> dict:
        """Load research metadata JSON."""
        if not self.research_json_path.exists():
            return {}
        with open(self.research_json_path) as f:
            return json.load(f)
```

---

## 4. Link Formatter

### 4.1 `libs/document_io/link_formatter.py`

```python
"""Link formatting for Markdown and Obsidian compatibility."""

from pathlib import Path
import os


class LinkFormatter:
    """Generates dual-format links (Markdown + Wikilink)."""

    def __init__(self, vault_root: Path = Path("panda-system-docs")):
        """
        Initialize link formatter.

        Args:
            vault_root: Root directory for Obsidian vault
        """
        self.vault_root = vault_root

    def dual_link(self, from_file: Path, to_file: Path, label: str) -> str:
        """
        Generate both Markdown and Wikilink formats.

        Args:
            from_file: Source file path
            to_file: Target file path
            label: Link label

        Returns:
            Combined link string: "[label](rel_path) | [[vault_path|label]]"
        """
        md_link = self.markdown_link(from_file, to_file, label)
        wiki_link = self.wikilink(to_file, label)
        return f"{md_link} | {wiki_link}"

    def markdown_link(self, from_file: Path, to_file: Path, label: str) -> str:
        """
        Generate relative Markdown link.

        Args:
            from_file: Source file
            to_file: Target file
            label: Link label

        Returns:
            Markdown link: [label](relative_path)
        """
        rel_path = os.path.relpath(to_file, from_file.parent)
        return f"[{label}]({rel_path})"

    def wikilink(self, to_file: Path, label: str) -> str:
        """
        Generate Obsidian wikilink.

        Args:
            to_file: Target file
            label: Link label

        Returns:
            Wikilink: [[path|label]]
        """
        try:
            vault_path = to_file.relative_to(self.vault_root)
            # Remove extension for wikilinks
            vault_path_str = str(vault_path.with_suffix(""))
            return f"[[{vault_path_str}|{label}]]"
        except ValueError:
            # File not in vault, use full path
            return f"[[{to_file.with_suffix('')}|{label}]]"

    def block_link(self, file_path: Path, block_id: str, label: str) -> str:
        """
        Generate link to specific block.

        Args:
            file_path: Target file
            block_id: Block identifier (e.g., "claim-001")
            label: Link label

        Returns:
            Wikilink with block: [[path#^block-id|label]]
        """
        try:
            vault_path = file_path.relative_to(self.vault_root)
            vault_path_str = str(vault_path.with_suffix(""))
            return f"[[{vault_path_str}#^{block_id}|{label}]]"
        except ValueError:
            return f"[[{file_path.with_suffix('')}#^{block_id}|{label}]]"

    def source_reference(
        self,
        from_file: Path,
        to_file: Path,
        index: int,
        description: str,
    ) -> str:
        """
        Generate numbered source reference.

        Args:
            from_file: Source file
            to_file: Target file
            index: Reference number
            description: Brief description

        Returns:
            Formatted reference: - [1] [label](path) | [[path|label]] - "description"
        """
        label = to_file.stem
        dual = self.dual_link(from_file, to_file, label)
        return f"- [{index}] {dual} - \"{description}\""


# Default instance
link_formatter = LinkFormatter()
```

---

## 5. Webpage Cache Manager

### 5.1 `libs/document_io/webpage_cache.py`

```python
"""Webpage cache management for PandaAI v2."""

from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import json
import re


class WebpageCacheManager:
    """Manages cached webpage data."""

    def __init__(self, turn_dir: Path):
        """
        Initialize cache manager.

        Args:
            turn_dir: Turn directory
        """
        self.turn_dir = turn_dir
        self.cache_dir = turn_dir / "webpage_cache"

    def create_cache(self, url: str, title: str) -> Path:
        """
        Create cache directory for a URL.

        Args:
            url: Page URL
            title: Page title

        Returns:
            Path to cache directory
        """
        slug = self._url_to_slug(url)
        cache_path = self.cache_dir / slug
        cache_path.mkdir(parents=True, exist_ok=True)

        # Create initial manifest
        manifest = {
            "url": url,
            "url_slug": slug,
            "title": title,
            "visited_at": datetime.now().isoformat(),
            "turn_number": self._get_turn_number(),
            "captured": {
                "page_content": False,
                "screenshot": False,
                "extracted_data": False,
            },
            "content_summary": {},
            "answerable_questions": [],
        }
        self._save_manifest(cache_path, manifest)

        return cache_path

    def get_cache(self, url: str) -> Optional[Path]:
        """
        Get cache directory for a URL if it exists.

        Args:
            url: Page URL

        Returns:
            Cache path or None
        """
        slug = self._url_to_slug(url)
        cache_path = self.cache_dir / slug
        return cache_path if cache_path.exists() else None

    def get_manifest(self, cache_path: Path) -> dict:
        """Get manifest for a cache."""
        manifest_path = cache_path / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                return json.load(f)
        return {}

    def save_page_content(self, cache_path: Path, content: str) -> None:
        """Save page content markdown."""
        content_path = cache_path / "page_content.md"
        content_path.write_text(content)

        # Update manifest
        manifest = self.get_manifest(cache_path)
        manifest["captured"]["page_content"] = True
        self._save_manifest(cache_path, manifest)

    def save_extracted_data(self, cache_path: Path, data: dict) -> None:
        """Save extracted structured data."""
        data_path = cache_path / "extracted_data.json"
        with open(data_path, "w") as f:
            json.dump(data, f, indent=2)

        # Update manifest
        manifest = self.get_manifest(cache_path)
        manifest["captured"]["extracted_data"] = True
        self._save_manifest(cache_path, manifest)

    def save_screenshot(self, cache_path: Path, screenshot_path: Path) -> None:
        """Record screenshot path in manifest."""
        manifest = self.get_manifest(cache_path)
        manifest["captured"]["screenshot"] = True
        manifest["screenshot_path"] = str(screenshot_path)
        self._save_manifest(cache_path, manifest)

    def update_content_summary(self, cache_path: Path, summary: dict) -> None:
        """Update content summary in manifest."""
        manifest = self.get_manifest(cache_path)
        manifest["content_summary"] = summary
        self._save_manifest(cache_path, manifest)

    def set_answerable_questions(self, cache_path: Path, questions: list[str]) -> None:
        """Set questions answerable from cache."""
        manifest = self.get_manifest(cache_path)
        manifest["answerable_questions"] = questions
        self._save_manifest(cache_path, manifest)

    def can_answer_from_cache(self, url: str, question: str) -> bool:
        """
        Check if a question can be answered from cache.

        Args:
            url: Page URL
            question: User question

        Returns:
            True if likely answerable from cache
        """
        cache_path = self.get_cache(url)
        if not cache_path:
            return False

        manifest = self.get_manifest(cache_path)
        answerable = manifest.get("answerable_questions", [])

        # Simple keyword matching
        question_lower = question.lower()
        for template in answerable:
            if template.lower() in question_lower:
                return True

        return False

    def get_cached_answer(self, url: str, question: str) -> Optional[str]:
        """
        Try to answer question from cache.

        Args:
            url: Page URL
            question: User question

        Returns:
            Answer if found, None otherwise
        """
        cache_path = self.get_cache(url)
        if not cache_path:
            return None

        manifest = self.get_manifest(cache_path)
        summary = manifest.get("content_summary", {})

        question_lower = question.lower()

        # Check for common patterns
        if "how many pages" in question_lower:
            page_info = summary.get("page_info", "")
            if page_info:
                return f"The page has {page_info}"

        if "how many comments" in question_lower:
            count = summary.get("comment_count")
            if count is not None:
                return f"There are {count} comments"

        return None

    def _url_to_slug(self, url: str) -> str:
        """Convert URL to filesystem-safe slug."""
        # Remove protocol
        slug = re.sub(r'^https?://', '', url)
        # Replace special chars
        slug = re.sub(r'[^\w\-]', '_', slug)
        # Truncate
        return slug[:100]

    def _get_turn_number(self) -> int:
        """Extract turn number from directory name."""
        try:
            return int(self.turn_dir.name.split("_")[1])
        except (IndexError, ValueError):
            return 0

    def _save_manifest(self, cache_path: Path, manifest: dict) -> None:
        """Save manifest JSON."""
        manifest_path = cache_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
```

---

## 6. Verification Checklist

Before proceeding to Phase 4, verify:

- [ ] ContextManager can create and parse context.md
- [ ] ContextManager can read/write all sections (§0-§6)
- [ ] TurnManager creates sequential turn numbers per session
- [ ] TurnManager creates proper directory structure
- [ ] ResearchManager creates research.md with correct format
- [ ] LinkFormatter generates valid dual-format links
- [ ] WebpageCacheManager creates and retrieves cached data
- [ ] All document operations are atomic (no partial writes)

---

## Deliverables Checklist

| Item | File | Status |
|------|------|--------|
| Context Manager | `libs/document_io/context_manager.py` | |
| Turn Manager | `libs/document_io/turn_manager.py` | |
| Research Manager | `libs/document_io/research_manager.py` | |
| Link Formatter | `libs/document_io/link_formatter.py` | |
| Webpage Cache | `libs/document_io/webpage_cache.py` | |
| `__init__.py` | `libs/document_io/__init__.py` | |

---

**Previous Phase:** [02-CORE-LIBRARIES.md](./02-CORE-LIBRARIES.md)
**Next Phase:** [04-VLLM-SERVER.md](./04-VLLM-SERVER.md)
