"""
Research Document Writers for Unified Research Architecture

Creates structured markdown documents for each research phase:
- research_plan.md: Research Planner output (phase decision)
- phase1_intelligence.md: Phase 1 Intelligence findings
- phase2_results.md: Phase 2 Search results

Author: Research Role Integration
Date: 2025-12-08
"""

import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ResearchPlan:
    """Research Planner output - decides which phases to execute."""
    query: str
    decision: str  # PHASE1_ONLY, PHASE2_ONLY, PHASE1_THEN_PHASE2
    rationale: str
    domain: str = ""

    # Phase 1 strategy (if applicable)
    phase1_goal: str = ""
    phase1_search_terms: List[str] = field(default_factory=list)
    phase1_source_types: List[str] = field(default_factory=list)

    # Phase 2 strategy (if applicable)
    phase2_goal: str = ""
    phase2_target_sources: List[str] = field(default_factory=list)
    phase2_key_requirements: List[str] = field(default_factory=list)

    # Metadata
    turn_number: int = 0
    session_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SourceInfo:
    """Information about a source analyzed in Phase 1."""
    url: str
    source_type: str  # forum, review, guide, official
    quality: float  # 0.0-1.0
    key_findings: str


@dataclass
class DiscoveredAttribute:
    """An attribute discovered during Phase 1 intelligence gathering."""
    key: str
    value: str
    confidence: float  # 0.0-1.0
    source_refs: List[int] = field(default_factory=list)  # Reference indices


@dataclass
class Phase1Intelligence:
    """Phase 1 Intelligence findings - general knowledge from forums/reviews."""
    turn_number: int
    query: str
    domain: str

    # Search execution
    search_queries: List[Dict[str, Any]] = field(default_factory=list)  # {query, result_count}
    sources_analyzed: List[SourceInfo] = field(default_factory=list)

    # Findings
    discovered_attributes: List[DiscoveredAttribute] = field(default_factory=list)
    community_recommendations: List[str] = field(default_factory=list)
    key_insights: str = ""
    warnings: List[str] = field(default_factory=list)

    # Source references
    source_references: List[Dict[str, str]] = field(default_factory=list)  # {url, title}

    # Metadata
    session_id: str = ""
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    from_cache: bool = False
    cache_id: str = ""

    # Error handling
    error: Optional[str] = None


@dataclass
class SearchResult:
    """A single result from Phase 2 search."""
    title: str
    result_type: str  # product, guide, article, listing
    source: str
    url: str
    relevance_score: float  # 0.0-1.0

    # Optional fields (domain-dependent)
    price: Optional[str] = None
    availability: Optional[str] = None

    # Attributes (key-value pairs)
    attributes: Dict[str, str] = field(default_factory=dict)

    # Evaluation
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    extraction_method: str = "unknown"  # known_selectors, llm_extraction, click_verify
    confidence: float = 0.0


@dataclass
class RejectedResult:
    """A result that was rejected during Phase 2."""
    name: str
    source: str
    reason: str


@dataclass
class Phase2Results:
    """Phase 2 Search results - specific items from targeted sources."""
    turn_number: int
    query: str
    domain: str
    result_type: str  # product, guide, comparison, information

    # Strategy
    requirements_from_phase1: List[str] = field(default_factory=list)
    constraints: Dict[str, str] = field(default_factory=dict)  # budget, location, etc.
    sources_searched: List[str] = field(default_factory=list)

    # Results
    results: List[SearchResult] = field(default_factory=list)
    rejected_results: List[RejectedResult] = field(default_factory=list)

    # Statistics
    sources_searched_count: int = 0
    results_evaluated_count: int = 0
    results_viable_count: int = 0
    results_rejected_count: int = 0

    # Source references
    source_references: List[Dict[str, str]] = field(default_factory=list)

    # Metadata
    session_id: str = ""
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    used_phase1_intelligence: bool = False

    # Error handling
    error: Optional[str] = None


# =============================================================================
# Writers
# =============================================================================

class ResearchPlanWriter:
    """Writes research_plan.md documents."""

    def write(self, plan: ResearchPlan, turn_dir: Path) -> Path:
        """Write research_plan.md to turn directory."""
        content = self._render(plan)
        output_path = turn_dir / "research_plan.md"
        output_path.write_text(content)
        logger.info(f"[ResearchPlanWriter] Wrote {output_path}")
        return output_path

    def _render(self, plan: ResearchPlan) -> str:
        """Render ResearchPlan to markdown."""
        lines = [
            "# Research Plan",
            "",
            f"**Query:** {plan.query}",
            f"**Domain:** {plan.domain or 'unknown'}",
            f"**Decision:** {plan.decision}",
            f"**Rationale:** {plan.rationale}",
            f"**Created:** {plan.created_at.isoformat()}",
            "",
            "---",
            "",
        ]

        # Phase 1 Strategy
        if plan.decision in ("PHASE1_ONLY", "PHASE1_THEN_PHASE2"):
            lines.extend([
                "## Phase 1 Strategy",
                "",
                f"**Goal:** {plan.phase1_goal or 'Gather general intelligence'}",
                "",
                "**Search Terms:**",
            ])
            for term in plan.phase1_search_terms:
                lines.append(f"- {term}")
            if not plan.phase1_search_terms:
                lines.append("- (auto-generated)")

            lines.extend([
                "",
                "**Source Types:**",
            ])
            for source_type in plan.phase1_source_types:
                lines.append(f"- {source_type}")
            if not plan.phase1_source_types:
                lines.append("- forums, reviews, guides")
            lines.append("")

        # Phase 2 Strategy
        if plan.decision in ("PHASE2_ONLY", "PHASE1_THEN_PHASE2"):
            lines.extend([
                "## Phase 2 Strategy",
                "",
                f"**Goal:** {plan.phase2_goal or 'Find specific results'}",
                "",
                "**Target Sources:**",
            ])
            for source in plan.phase2_target_sources:
                lines.append(f"- {source}")
            if not plan.phase2_target_sources:
                lines.append("- (domain-appropriate sources)")

            lines.extend([
                "",
                "**Key Requirements:**",
            ])
            for req in plan.phase2_key_requirements:
                lines.append(f"- {req}")
            if not plan.phase2_key_requirements:
                lines.append("- (from Phase 1 or query)")
            lines.append("")

        return "\n".join(lines)


class Phase1IntelligenceWriter:
    """Writes phase1_intelligence.md documents."""

    def write(self, intelligence: Phase1Intelligence, turn_dir: Path) -> Path:
        """Write phase1_intelligence.md to turn directory."""
        content = self._render(intelligence)
        output_path = turn_dir / "phase1_intelligence.md"
        output_path.write_text(content)
        logger.info(f"[Phase1IntelligenceWriter] Wrote {output_path}")
        return output_path

    def _render(self, intel: Phase1Intelligence) -> str:
        """Render Phase1Intelligence to markdown."""
        lines = [
            "# Phase 1: Intelligence Findings",
            "",
            f"**Turn:** {intel.turn_number}",
            f"**Query:** {intel.query}",
            f"**Domain:** {intel.domain or 'unknown'}",
            f"**Executed:** {intel.executed_at.isoformat()}",
        ]

        if intel.from_cache:
            lines.append(f"**From Cache:** Yes (ID: {intel.cache_id})")

        lines.extend(["", "---", ""])

        # Error section (if applicable)
        if intel.error:
            lines.extend([
                "## Error",
                "",
                f"Phase 1 execution failed: {intel.error}",
                "",
                "---",
                "",
            ])

        # Search Queries Used
        lines.extend([
            "## Search Queries Used",
            "",
        ])
        if intel.search_queries:
            for i, sq in enumerate(intel.search_queries, 1):
                query = sq.get("query", "unknown")
                count = sq.get("result_count", 0)
                lines.append(f"{i}. `{query}` → {count} results")
        else:
            lines.append("*(No search queries recorded)*")
        lines.extend(["", "---", ""])

        # Sources Analyzed
        lines.extend([
            "## Sources Analyzed",
            "",
            "| Source | Type | Quality | Key Findings |",
            "|--------|------|---------|--------------|",
        ])
        if intel.sources_analyzed:
            for source in intel.sources_analyzed:
                url_short = source.url[:50] + "..." if len(source.url) > 50 else source.url
                findings_short = source.key_findings[:60] + "..." if len(source.key_findings) > 60 else source.key_findings
                lines.append(f"| {url_short} | {source.source_type} | {source.quality:.2f} | {findings_short} |")
        else:
            lines.append("| *(none)* | - | - | - |")
        lines.extend(["", "---", ""])

        # Discovered Attributes
        lines.extend([
            "## Discovered Attributes",
            "",
            "| Attribute | Value | Confidence | Source |",
            "|-----------|-------|------------|--------|",
        ])
        if intel.discovered_attributes:
            for attr in intel.discovered_attributes:
                refs = ", ".join(f"[{r}]" for r in attr.source_refs) if attr.source_refs else "-"
                lines.append(f"| {attr.key} | {attr.value} | {attr.confidence:.2f} | {refs} |")
        else:
            lines.append("| *(none discovered)* | - | - | - |")
        lines.extend(["", "---", ""])

        # Community Recommendations
        lines.extend([
            "## Community Recommendations",
            "",
        ])
        if intel.community_recommendations:
            for rec in intel.community_recommendations:
                lines.append(f"- {rec}")
        else:
            lines.append("*(No recommendations found)*")
        lines.extend(["", "---", ""])

        # Key Insights
        lines.extend([
            "## Key Insights",
            "",
            intel.key_insights or "*(No insights synthesized)*",
            "",
            "---",
            "",
        ])

        # Warnings/Cautions
        if intel.warnings:
            lines.extend([
                "## Warnings/Cautions",
                "",
            ])
            for warning in intel.warnings:
                lines.append(f"- {warning}")
            lines.extend(["", "---", ""])

        # Source References
        lines.extend([
            "## Source References",
            "",
        ])
        if intel.source_references:
            for i, ref in enumerate(intel.source_references, 1):
                url = ref.get("url", "unknown")
                title = ref.get("title", "Untitled")
                lines.append(f"- [{i}] {url} - \"{title}\"")
        else:
            lines.append("*(No sources)*")

        return "\n".join(lines)


class Phase2ResultsWriter:
    """Writes phase2_results.md documents."""

    def write(self, results: Phase2Results, turn_dir: Path) -> Path:
        """Write phase2_results.md to turn directory."""
        content = self._render(results)
        output_path = turn_dir / "phase2_results.md"
        output_path.write_text(content)
        logger.info(f"[Phase2ResultsWriter] Wrote {output_path}")
        return output_path

    def _render(self, results: Phase2Results) -> str:
        """Render Phase2Results to markdown."""
        lines = [
            "# Phase 2: Search Results",
            "",
            f"**Turn:** {results.turn_number}",
            f"**Query:** {results.query}",
            f"**Domain:** {results.domain or 'unknown'}",
            f"**Result Type:** {results.result_type}",
            f"**Executed:** {results.executed_at.isoformat()}",
            f"**Used Phase 1 Intelligence:** {'Yes' if results.used_phase1_intelligence else 'No'}",
            "",
            "---",
            "",
        ]

        # Error section (if applicable)
        if results.error:
            lines.extend([
                "## Error",
                "",
                f"Phase 2 execution failed: {results.error}",
                "",
                "---",
                "",
            ])

        # Search Strategy
        lines.extend([
            "## Search Strategy",
            "",
        ])

        if results.requirements_from_phase1:
            lines.append("**Requirements from Phase 1:**")
            for req in results.requirements_from_phase1:
                lines.append(f"- {req}")
            lines.append("")

        if results.constraints:
            lines.append("**Constraints:**")
            for key, value in results.constraints.items():
                lines.append(f"- {key}: {value}")
            lines.append("")

        lines.append("**Sources Searched:**")
        for source in results.sources_searched:
            lines.append(f"- {source}")
        if not results.sources_searched:
            lines.append("- *(none)*")
        lines.extend(["", "---", ""])

        # Results Found
        lines.extend([
            "## Results Found",
            "",
        ])

        if results.results:
            for i, result in enumerate(results.results, 1):
                lines.extend([
                    f"### {i}. {result.title}",
                    "",
                    f"- **Type:** {result.result_type}",
                    f"- **Source:** {result.source}",
                    f"- **URL:** {result.url}",
                    f"- **Relevance Score:** {result.relevance_score:.2f}",
                ])

                if result.price:
                    lines.append(f"- **Price:** {result.price}")
                if result.availability:
                    lines.append(f"- **Availability:** {result.availability}")

                if result.attributes:
                    lines.extend(["", "**Attributes:**"])
                    for key, value in result.attributes.items():
                        lines.append(f"  - {key}: {value}")

                if result.strengths:
                    lines.extend(["", "**Strengths:**"])
                    for strength in result.strengths:
                        lines.append(f"  - {strength}")

                if result.weaknesses:
                    lines.extend(["", "**Weaknesses:**"])
                    for weakness in result.weaknesses:
                        lines.append(f"  - {weakness}")

                lines.extend([
                    "",
                    f"- **Extraction Method:** {result.extraction_method}",
                    f"- **Confidence:** {result.confidence:.2f}",
                    "",
                ])
        else:
            lines.append("*(No results found)*")
            lines.append("")

        lines.extend(["---", ""])

        # Rejected Results
        if results.rejected_results:
            lines.extend([
                "## Rejected Results",
                "",
                "| Result | Source | Reason |",
                "|--------|--------|--------|",
            ])
            for rejected in results.rejected_results:
                name_short = rejected.name[:40] + "..." if len(rejected.name) > 40 else rejected.name
                lines.append(f"| {name_short} | {rejected.source} | {rejected.reason} |")
            lines.extend(["", "---", ""])

        # Search Statistics
        lines.extend([
            "## Search Statistics",
            "",
            f"- Sources searched: {results.sources_searched_count}",
            f"- Results evaluated: {results.results_evaluated_count}",
            f"- Results viable: {results.results_viable_count}",
            f"- Results rejected: {results.results_rejected_count}",
            "",
            "---",
            "",
        ])

        # Source References
        lines.extend([
            "## Source References",
            "",
        ])
        if results.source_references:
            for i, ref in enumerate(results.source_references, 1):
                url = ref.get("url", "unknown")
                title = ref.get("title", "Untitled")
                lines.append(f"- [{i}] {url} - \"{title}\"")
        else:
            lines.append("*(No sources)*")

        return "\n".join(lines)


# =============================================================================
# Utility Functions
# =============================================================================

def generate_topic_hash(topic_normalized: str) -> str:
    """Generate a hash for cache lookup."""
    return hashlib.sha256(topic_normalized.encode()).hexdigest()[:12]


def normalize_topic(query: str, domain: str = "") -> str:
    """
    Normalize a query into a cacheable topic.

    Removes user-specific terms (budget, location, commerce filler) and normalizes text.
    Goal: Extract the core entity/subject (e.g., "syrian hamsters" from "find Syrian hamsters for sale online please")
    """
    import re

    topic = query.lower()

    # Remove punctuation first
    topic = re.sub(r'[?!.,;:\'"(){}[\]]', '', topic)

    # Remove budget/price terms
    topic = re.sub(r'\b(under|below|above|over|around|about|~)\s*\$?\d+\b', '', topic)
    topic = re.sub(r'\$\d+[\d,]*(\.\d+)?', '', topic)
    topic = re.sub(r'\b(cheap|cheapest|budget|affordable|expensive|premium)\b', '', topic)

    # Remove location terms
    topic = re.sub(r'\b(in|near|around|at)\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)*\b', '', topic, flags=re.IGNORECASE)

    # Remove common filler words (expanded list)
    stopwords = {
        # Basic articles/pronouns
        'the', 'a', 'an', 'for', 'me', 'my', 'i', 'we', 'you', 'your', 'some',
        # Question words
        'can', 'could', 'would', 'should', 'do', 'does', 'is', 'are', 'was', 'were',
        'what', 'whats', "what's", 'where', 'when', 'how', 'which', 'who',
        # Action words (keep the subject, not the action)
        'find', 'get', 'buy', 'want', 'need', 'looking', 'search', 'show', 'help',
        'recommend', 'suggest', 'give', 'tell', 'know',
        # Commerce filler
        'sale', 'sales', 'online', 'purchase', 'order', 'shop', 'store', 'website',
        'available', 'stock', 'inventory',
        # Quality words
        'best', 'good', 'great', 'top', 'nice', 'quality',
        # Politeness
        'please', 'thanks', 'thank', 'appreciate',
        # Misc
        'just', 'also', 'very', 'really', 'actually', 'currently', 'right', 'now',
    }
    words = topic.split()
    words = [w for w in words if w not in stopwords and len(w) > 1]

    # Clean up
    topic = ' '.join(words)
    topic = re.sub(r'\s+', ' ', topic).strip()

    return topic
