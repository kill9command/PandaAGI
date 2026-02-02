"""
Research State Manager

Manages the research_state.md document that flows through the research loop.
All state is document-based for transparency and debugging.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING
import json

if TYPE_CHECKING:
    from libs.gateway.turn_manager import TurnDirectory


@dataclass
class SearchResult:
    """A single search result."""
    url: str
    title: str
    snippet: str
    score: float = 0.0
    source_type: str = "unknown"  # forum, review, vendor, news, official
    priority: str = "maybe"  # must_visit, should_visit, maybe, skip


@dataclass
class PageFindings:
    """Findings extracted from a visited page."""
    url: str
    visited_at: str
    relevance: float
    confidence: float
    summary: str
    findings: dict  # Varies by intent: key_facts, recommendations, products, etc.


@dataclass
class ResearchState:
    """
    The complete state of a research session.
    Rendered to/from markdown for LLM consumption.
    """
    goal: str                    # Original user query (preserves priorities like "cheapest")
    intent: str                  # informational | commerce
    context: str = ""            # Session context from Planner (what we were discussing)
    task: str = ""               # Specific task from Planner (what to research)

    # Search results (from search() calls)
    search_results: list[SearchResult] = field(default_factory=list)
    searches_used: int = 0

    # Visited pages and their findings
    visited_pages: list[PageFindings] = field(default_factory=list)

    # Accumulated intelligence (grows as we visit pages)
    intelligence: dict = field(default_factory=dict)

    # Status
    status: str = "in_progress"  # in_progress | sufficient | done
    iteration: int = 0
    max_iterations: int = 10

    # Constraints
    max_searches: int = 2
    max_visits: int = 8

    # Timing
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    elapsed_seconds: float = 0.0
    max_seconds: float = 120.0

    def to_markdown(self) -> str:
        """Render state to markdown for LLM consumption."""
        lines = []

        lines.append("# Research State\n")

        # Goal (original user query)
        lines.append("## Goal (User's Original Query)")
        lines.append(self.goal)
        lines.append("")

        # Context from session/planner
        if self.context:
            lines.append("## Context (From Session)")
            lines.append(self.context)
            lines.append("")

        # Specific task from planner
        if self.task:
            lines.append("## Task")
            lines.append(self.task)
            lines.append("")

        lines.append("## Intent")
        lines.append(self.intent)
        lines.append("")

        # Search results
        lines.append("## Search Results")
        if not self.search_results:
            lines.append("(none yet)")
        else:
            lines.append(f"Found {len(self.search_results)} results:\n")
            for i, r in enumerate(self.search_results[:15], 1):  # Limit to 15
                priority_marker = ""
                if r.priority == "must_visit":
                    priority_marker = " **[MUST VISIT]**"
                elif r.priority == "should_visit":
                    priority_marker = " [should visit]"
                lines.append(f"{i}. [{r.title}]({r.url}){priority_marker}")
                lines.append(f"   - Type: {r.source_type}, Score: {r.score:.2f}")
                if r.snippet:
                    lines.append(f"   - {r.snippet[:150]}...")
                lines.append("")
        lines.append("")

        # Visited pages
        lines.append("## Visited Pages")
        if not self.visited_pages:
            lines.append("(none yet)")
        else:
            for i, page in enumerate(self.visited_pages, 1):
                lines.append(f"### Page {i}: {page.url}")
                lines.append(f"**Visited:** {page.visited_at}")
                lines.append(f"**Relevance:** {page.relevance:.2f}, **Confidence:** {page.confidence:.2f}")
                lines.append(f"**Summary:** {page.summary}")
                lines.append("")
                lines.append("**Findings:**")
                for key, value in page.findings.items():
                    if isinstance(value, list):
                        lines.append(f"- {key}:")
                        for item in value:
                            lines.append(f"  - {item}")
                    else:
                        lines.append(f"- {key}: {value}")
                lines.append("")
        lines.append("")

        # Intelligence summary
        lines.append("## Intelligence Summary")
        if not self.intelligence:
            lines.append("(building...)")
        else:
            for section, content in self.intelligence.items():
                lines.append(f"### {section.replace('_', ' ').title()}")
                if isinstance(content, list):
                    for item in content:
                        lines.append(f"- {item}")
                elif isinstance(content, dict):
                    for k, v in content.items():
                        lines.append(f"- {k}: {v}")
                else:
                    lines.append(str(content))
                lines.append("")
        lines.append("")

        # Status
        lines.append("## Status")
        lines.append(f"- Status: {self.status}")
        lines.append(f"- Iteration: {self.iteration} / {self.max_iterations}")
        lines.append(f"- Searches used: {self.searches_used} / {self.max_searches}")
        lines.append(f"- Pages visited: {len(self.visited_pages)} / {self.max_visits}")
        lines.append(f"- Time elapsed: {self.elapsed_seconds:.1f}s / {self.max_seconds:.0f}s")

        return "\n".join(lines)

    def remaining_searches(self) -> int:
        return self.max_searches - self.searches_used

    def remaining_visits(self) -> int:
        return self.max_visits - len(self.visited_pages)

    def can_search(self) -> bool:
        return self.remaining_searches() > 0

    def can_visit(self) -> bool:
        return self.remaining_visits() > 0

    def is_url_visited(self, url: str) -> bool:
        """Check if we've already visited this URL."""
        visited_urls = [p.url for p in self.visited_pages]
        return url in visited_urls

    def add_search_results(self, results: list[SearchResult]):
        """Add search results to state."""
        self.search_results = results
        self.searches_used += 1

    def add_page_findings(self, findings: PageFindings):
        """Add findings from a visited page."""
        self.visited_pages.append(findings)

    def update_intelligence(self, new_intel: dict):
        """
        Merge new intelligence into accumulated intelligence.
        Lists are appended (deduped), dicts are merged, scalars are overwritten.
        """
        for key, value in new_intel.items():
            if key not in self.intelligence:
                self.intelligence[key] = value
            elif isinstance(value, list) and isinstance(self.intelligence[key], list):
                # Dedupe and append
                existing = set(str(x) for x in self.intelligence[key])
                for item in value:
                    if str(item) not in existing:
                        self.intelligence[key].append(item)
                        existing.add(str(item))
            elif isinstance(value, dict) and isinstance(self.intelligence[key], dict):
                # Merge dicts
                self.intelligence[key].update(value)
            else:
                # Overwrite
                self.intelligence[key] = value

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "goal": self.goal,
            "intent": self.intent,
            "context": self.context,
            "task": self.task,
            "search_results": [
                {"url": r.url, "title": r.title, "snippet": r.snippet,
                 "score": r.score, "source_type": r.source_type, "priority": r.priority}
                for r in self.search_results
            ],
            "searches_used": self.searches_used,
            "visited_pages": [
                {"url": p.url, "visited_at": p.visited_at, "relevance": p.relevance,
                 "confidence": p.confidence, "summary": p.summary, "findings": p.findings}
                for p in self.visited_pages
            ],
            "intelligence": self.intelligence,
            "status": self.status,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "max_searches": self.max_searches,
            "max_visits": self.max_visits,
            "started_at": self.started_at,
            "elapsed_seconds": self.elapsed_seconds,
            "max_seconds": self.max_seconds,
        }

    def write_to_turn(self, turn_dir: "TurnDirectory") -> Path:
        """
        Write research state to turn directory for recipe-based prompt building.

        This enables LLM roles (Result Scorer, Content Extractor, Research Planner)
        to access research state via their recipes' input_docs.

        Args:
            turn_dir: The turn directory to write to

        Returns:
            Path to the written research_state.md file
        """
        output_path = turn_dir.path / "research_state.md"
        output_path.write_text(self.to_markdown(), encoding="utf-8")
        return output_path


def create_initial_state(
    goal: str,
    intent: str,
    context: str = "",
    task: str = "",
    config: Optional[dict] = None,
) -> ResearchState:
    """
    Create initial research state for a new research session.

    Args:
        goal: Original user query (preserves priority signals like "cheapest")
        intent: "informational" or "commerce"
        context: Session context from Planner (what we were discussing)
        task: Specific task from Planner (what to research)
        config: Optional config overrides
    """
    config = config or {}

    return ResearchState(
        goal=goal,
        intent=intent,
        context=context,
        task=task,
        max_searches=config.get("max_searches", 2),
        max_visits=config.get("max_visits", 8),
        max_iterations=config.get("max_iterations", 10),
        max_seconds=config.get("max_seconds", 120.0),
    )
