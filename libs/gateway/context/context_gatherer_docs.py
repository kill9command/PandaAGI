"""
Document schemas for the Context Gatherer phases.

Each phase reads input documents and produces output documents,
following Pandora's document IO pattern.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from pathlib import Path
from datetime import datetime
import json


@dataclass
class TurnIndexEntry:
    """Single entry in the turn index."""
    turn_number: int
    query_summary: str
    topic: str
    key_entities: List[str]
    has_research: bool
    has_products: bool
    timestamp: Optional[str] = None
    response_preview: str = ""  # First ~150 chars of response for searchability
    quality_score: float = 1.0  # Quality score (0.0-1.0) - degraded turns have lower scores


@dataclass
class TurnIndexDoc:
    """
    Turn Index Document - Pre-built index of recent turns.
    Input to Phase 1 (SCAN).
    """
    session_id: str
    generated_at: str
    entries: List[TurnIndexEntry]
    oldest_turn: int
    newest_turn: int

    def to_markdown(self) -> str:
        lines = [
            "# Turn Index",
            f"**Session:** {self.session_id}",
            f"**Generated:** {self.generated_at}",
            f"**Turns Indexed:** {len(self.entries)}",
            "",
            "---",
            "",
            "## Recent Turns",
            "",
        ]

        for i, entry in enumerate(self.entries):
            # Mark the first entry (highest turn number) as N-1 for follow-up detection
            n1_marker = " ← **PREVIOUS TURN (N-1)**" if i == 0 else ""
            query = entry.query_summary[:80] + "..." if len(entry.query_summary) > 80 else entry.query_summary

            # Add quality warning for degraded turns
            quality_warning = ""
            if entry.quality_score < 0.5:
                quality_warning = " ⚠️ **OUTDATED DATA**"
            elif entry.quality_score < 0.8:
                quality_warning = " ⚠️ *potentially stale*"

            lines.append(f"### Turn {entry.turn_number}{n1_marker}{quality_warning}")
            lines.append(f"- **Query:** {query}")
            lines.append(f"- **Topic:** {entry.topic}")
            if entry.quality_score < 1.0:
                lines.append(f"- **Quality:** {entry.quality_score:.2f} (lower = more outdated)")
            if entry.response_preview:
                lines.append(f"- **Response:** {entry.response_preview}")
            if entry.has_research:
                lines.append(f"- **Has Research:** Yes → [toolresults.md](../turn_{entry.turn_number:06d}/toolresults.md)")
            lines.append("")

        lines.extend([
            "---",
            "",
            "## Index Metadata",
            f"- **Oldest Turn:** {self.oldest_turn}",
            f"- **Newest Turn:** {self.newest_turn}",
        ])

        return "\n".join(lines)


@dataclass
class RelevantTurn:
    """A turn identified as relevant by the SCAN phase."""
    turn_number: int
    relevance: str  # high, medium, low
    reason: str
    expected_info: str
    load_priority: int


@dataclass
class ScanResultDoc:
    """
    Scan Result Document - Output of Phase 1 (SCAN).
    Identifies which previous turns are relevant to the current query.
    """
    query: str
    timestamp: str
    relevant_turns: List[RelevantTurn]
    reasoning: str

    def to_markdown(self) -> str:
        lines = [
            "# Scan Result",
            f"**Query:** {self.query}",
            "**Phase:** 1-SCAN",
            f"**Timestamp:** {self.timestamp}",
            "",
            "---",
            "",
            "## Relevant Turns",
            "",
        ]

        for turn in self.relevant_turns:
            lines.extend([
                f"### Turn {turn.turn_number}",
                f"- **Relevance:** {turn.relevance}",
                f"- **Reason:** {turn.reason}",
                f"- **Expected Info:** {turn.expected_info}",
                f"- **Load Priority:** {turn.load_priority}",
                "",
            ])

        lines.extend([
            "---",
            "",
            "## Scan Reasoning",
            "",
            self.reasoning,
            "",
            "---",
            "",
            "## Turns to Load",
        ])

        for turn in sorted(self.relevant_turns, key=lambda t: t.load_priority):
            lines.append(f"- [x] {turn.turn_number} ({turn.relevance} priority)")

        return "\n".join(lines)

    @classmethod
    def from_llm_response(cls, query: str, response: Dict[str, Any]) -> "ScanResultDoc":
        """Parse LLM JSON response into ScanResultDoc."""
        relevant_turns = []
        for i, turn_data in enumerate(response.get("relevant_turns", [])):
            relevant_turns.append(RelevantTurn(
                turn_number=turn_data.get("turn", 0),
                relevance=turn_data.get("relevance", "medium"),
                reason=turn_data.get("reason", ""),
                expected_info=turn_data.get("expected_info", ""),
                load_priority=i + 1
            ))

        return cls(
            query=query,
            timestamp=datetime.utcnow().isoformat() + "Z",
            relevant_turns=relevant_turns,
            reasoning=response.get("reasoning", "")
        )

    def get_turn_numbers(self) -> List[int]:
        """Get list of turn numbers to load."""
        return [t.turn_number for t in self.relevant_turns]


@dataclass
class ContextBundleEntry:
    """Single context.md loaded for Phase 2."""
    turn_number: int
    original_query: str
    topic: str
    intent: str
    summary: str
    product_findings: List[Dict[str, str]]
    source_references: List[str]


@dataclass
class ContextBundleDoc:
    """
    Context Bundle Document - Loaded context.md files for Phase 2.
    System-assembled input to Phase 2 (READ).
    """
    query: str
    entries: List[ContextBundleEntry]

    def to_markdown(self) -> str:
        lines = [
            "# Context Bundle",
            f"**Query:** {self.query}",
            "**Phase:** 2-READ (input)",
            f"**Turns Loaded:** {len(self.entries)}",
            "",
            "---",
        ]

        for entry in self.entries:
            lines.extend([
                "",
                f"## Turn {entry.turn_number} Context",
                "",
                f"**Original Query:** {entry.original_query}",
                f"**Topic:** {entry.topic}",
                f"**Intent:** {entry.intent}",
                "",
            ])

            if entry.summary:
                lines.extend([
                    "### Summary",
                    entry.summary,
                    "",
                ])

            if entry.product_findings:
                lines.extend([
                    "### Product Findings",
                    "| Product | Price | Vendor |",
                    "|---------|-------|--------|",
                ])
                for product in entry.product_findings[:5]:
                    name = product.get("name", "")[:50]
                    lines.append(f"| {name} | {product.get('price', '')} | {product.get('vendor', '')} |")
                lines.append("")

            if entry.source_references:
                lines.extend([
                    "### Source References",
                ])
                for ref in entry.source_references:
                    lines.append(f"- {ref}")
                lines.append("")

        return "\n".join(lines)


@dataclass
class LinkToFollow:
    """A link that needs to be followed for more detail."""
    turn_number: int
    path: str
    reason: str
    sections_to_extract: List[str]


@dataclass
class ReadResultDoc:
    """
    Read Result Document - Output of Phase 2 (READ).
    Contains direct info from contexts and links to follow.
    """
    query: str
    timestamp: str
    direct_info: Dict[str, str]  # turn_number -> summary of usable info
    links_to_follow: List[LinkToFollow]
    sufficient: bool
    missing_info: str

    def to_markdown(self) -> str:
        lines = [
            "# Read Result",
            f"**Query:** {self.query}",
            "**Phase:** 2-READ",
            f"**Timestamp:** {self.timestamp}",
            "",
            "---",
            "",
            "## Direct Information (Usable As-Is)",
            "",
        ]

        for turn, info in self.direct_info.items():
            lines.extend([
                f"### From Turn {turn}",
                info,
                "",
            ])

        lines.extend([
            "---",
            "",
            "## Links to Follow",
            "",
        ])

        if self.links_to_follow:
            for i, link in enumerate(self.links_to_follow, 1):
                lines.extend([
                    f"### Link {i}",
                    f"- **Path:** {link.path}",
                    f"- **Reason:** {link.reason}",
                    f"- **Extract:** {', '.join(link.sections_to_extract)}",
                    "",
                ])
        else:
            lines.append("*No links to follow - direct info is sufficient*")
            lines.append("")

        lines.extend([
            "---",
            "",
            "## Sufficiency Assessment",
            "",
            f"- **Current Info Sufficient:** {'Yes' if self.sufficient else 'No'}",
            f"- **Missing:** {self.missing_info if self.missing_info else 'None'}",
            f"- **Links Required:** {'Yes' if self.links_to_follow else 'No'} ({len(self.links_to_follow)} links)",
        ])

        return "\n".join(lines)

    @classmethod
    def from_llm_response(cls, query: str, response: Dict[str, Any]) -> "ReadResultDoc":
        """Parse LLM JSON response into ReadResultDoc."""
        links = []
        for link_data in response.get("links_to_follow", []):
            links.append(LinkToFollow(
                turn_number=link_data.get("turn", 0),
                path=link_data.get("link", ""),
                reason=link_data.get("reason", ""),
                sections_to_extract=link_data.get("extract", [])
            ))

        return cls(
            query=query,
            timestamp=datetime.utcnow().isoformat() + "Z",
            direct_info=response.get("direct_info", {}),
            links_to_follow=links,
            sufficient=response.get("sufficient", True),
            missing_info=response.get("missing_info", "")
        )

    def has_links_to_follow(self) -> bool:
        return len(self.links_to_follow) > 0


@dataclass
class LinkedDocsDoc:
    """
    Linked Documents - Content loaded from followed links.
    System-assembled input to Phase 3 (EXTRACT).
    """
    query: str
    documents: Dict[str, str]  # path -> content

    def to_markdown(self) -> str:
        lines = [
            "# Linked Documents",
            f"**Query:** {self.query}",
            "**Phase:** 3-EXTRACT (input)",
            f"**Documents Loaded:** {len(self.documents)}",
            "",
            "---",
        ]

        for i, (path, content) in enumerate(self.documents.items(), 1):
            lines.extend([
                "",
                f"## Document {i}: {Path(path).name}",
                "",
                content[:3000],  # Truncate long docs
                "",
            ])
            if len(content) > 3000:
                lines.append("*[Content truncated...]*")
                lines.append("")

        return "\n".join(lines)


@dataclass
class ExtractedDoc:
    """
    Extracted Document - Output of Phase 3 (EXTRACT).
    Contains information extracted from followed links.
    """
    query: str
    timestamp: str
    extracted: Dict[str, Any]  # Structured extracted information
    need_more: bool

    def to_markdown(self) -> str:
        lines = [
            "# Extracted Information",
            f"**Query:** {self.query}",
            "**Phase:** 3-EXTRACT",
            f"**Timestamp:** {self.timestamp}",
            "",
            "---",
        ]

        # Render extracted info as markdown
        for section, content in self.extracted.items():
            lines.extend([
                "",
                f"## {section.replace('_', ' ').title()}",
                "",
            ])

            if isinstance(content, dict):
                for key, value in content.items():
                    if isinstance(value, list):
                        lines.append(f"**{key}:**")
                        for item in value:
                            lines.append(f"- {item}")
                    else:
                        lines.append(f"**{key}:** {value}")
            elif isinstance(content, list):
                for item in content:
                    lines.append(f"- {item}")
            else:
                lines.append(str(content))

            lines.append("")

        lines.extend([
            "---",
            "",
            "## Extraction Status",
            f"- **Sufficient:** {'Yes' if not self.need_more else 'No'}",
            f"- **Need More:** {'Yes' if self.need_more else 'No'}",
        ])

        return "\n".join(lines)

    @classmethod
    def from_llm_response(cls, query: str, response: Dict[str, Any]) -> "ExtractedDoc":
        """Parse LLM JSON response into ExtractedDoc."""
        return cls(
            query=query,
            timestamp=datetime.utcnow().isoformat() + "Z",
            extracted=response.get("extracted", {}),
            need_more=response.get("need_more", False)
        )


@dataclass
class GatheringMetadata:
    """Metadata about the gathering process."""
    phases_completed: List[str]
    turns_scanned: int
    turns_loaded: int
    links_followed: int
    total_tokens: int


def write_doc(path: Path, content: str) -> None:
    """Write a document to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def read_doc(path: Path) -> Optional[str]:
    """Read a document from disk."""
    if path.exists():
        return path.read_text()
    return None
