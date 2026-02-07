"""
Document schemas for the 2-Phase Context Gatherer.

Consolidates 4 phases (SCAN, READ, EXTRACT, COMPILE) into 2 phases:
- RETRIEVAL: Identifies relevant turns AND evaluates their contexts
- SYNTHESIS: Extracts from links (if any) AND compiles final context

Token budget: ~10,500 tokens (27% reduction from 14,500)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from .search_results import SearchResults


@dataclass
class MemoryNode:
    """Unified memory graph node for Phase 2.1 retrieval."""
    node_id: str
    source_type: str  # turn_summary | preference | fact | research_cache | visit_record
    summary: str
    confidence: float = 0.0
    timestamp: Optional[str] = None
    source_ref: str = ""
    links: List[str] = field(default_factory=list)


@dataclass
class RetrievalPlanDoc:
    """RetrievalPlan output for Phase 2.1."""
    selected_nodes: Dict[str, List[str]]
    selection_reasons: Dict[str, str]
    coverage: Dict[str, bool]
    reasoning: str

    @classmethod
    def from_llm_response(
        cls,
        response: Dict[str, Any],
        valid_node_ids: Optional[set[str]] = None,
    ) -> "RetrievalPlanDoc":
        selected_nodes = response.get("selected_nodes") or {}
        selection_reasons = response.get("selection_reasons") or {}

        # Ensure all keys exist
        for key in ["turn_summary", "preference", "fact", "research_cache", "visit_record"]:
            selected_nodes.setdefault(key, [])
            selection_reasons.setdefault(key, "")

        # Validate node ids
        if valid_node_ids is not None:
            invalid = []
            for key, nodes in selected_nodes.items():
                for node_id in nodes:
                    if node_id not in valid_node_ids:
                        invalid.append(node_id)
            if invalid:
                raise ValueError(f"RetrievalPlan contains invalid node_ids: {invalid}")

        coverage = response.get("coverage") or {
            "has_prior_turns": bool(selected_nodes.get("turn_summary")),
            "has_memory": bool(selected_nodes.get("preference") or selected_nodes.get("fact")),
            "has_cached_research": bool(selected_nodes.get("research_cache")),
            "has_visit_data": bool(selected_nodes.get("visit_record")),
        }

        return cls(
            selected_nodes=selected_nodes,
            selection_reasons=selection_reasons,
            coverage=coverage,
            reasoning=response.get("reasoning", ""),
        )


@dataclass
class RetrievalTurn:
    """A turn identified and evaluated in the RETRIEVAL phase."""
    turn_number: int
    relevance: str  # critical, high, medium, low
    reason: str
    usable_info: str  # What can be used directly (was in READ)
    expected_info: str
    load_priority: int


@dataclass
class LinkToFollow:
    """A link that needs to be followed for more detail."""
    turn_number: int
    path: str
    reason: str
    sections_to_extract: List[str]


@dataclass
class RetrievalResultDoc:
    """
    Retrieval Result Document - Output of Phase 1 (RETRIEVAL).

    Merges SCAN + READ into single output:
    - Identifies relevant turns (was SCAN)
    - Provides direct info from those turns (was READ)
    - Lists links to follow for more detail (was READ)
    """
    query: str
    timestamp: str
    relevant_turns: List[RetrievalTurn]
    direct_info: Dict[str, str]  # turn_number -> usable info
    links_to_follow: List[LinkToFollow]
    sufficient: bool
    missing_info: str
    reasoning: str

    # Followup detection metadata
    is_followup: bool = False
    inherited_topic: Optional[str] = None

    def to_markdown(self) -> str:
        lines = [
            "# Retrieval Result",
            f"**Query:** {self.query}",
            "**Phase:** RETRIEVAL (merged SCAN+READ)",
            f"**Timestamp:** {self.timestamp}",
        ]

        if self.is_followup:
            lines.append(f"**Follow-up Detected:** Yes (topic: {self.inherited_topic})")

        lines.extend([
            "",
            "---",
            "",
            "## Relevant Turns Identified",
            "",
        ])

        for turn in self.relevant_turns:
            lines.extend([
                f"### Turn {turn.turn_number}",
                f"- **Relevance:** {turn.relevance}",
                f"- **Reason:** {turn.reason}",
                f"- **Usable Info:** {turn.usable_info[:200]}..." if len(turn.usable_info) > 200 else f"- **Usable Info:** {turn.usable_info}",
                "",
            ])

        lines.extend([
            "---",
            "",
            "## Direct Information (Usable As-Is)",
            "",
        ])

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
            "",
            "---",
            "",
            "## Reasoning",
            "",
            self.reasoning,
        ])

        return "\n".join(lines)

    @classmethod
    def from_llm_response(
        cls,
        query: str,
        response: Dict[str, Any],
        is_followup: bool = False,
        inherited_topic: Optional[str] = None,
        memory_index: Optional[Dict[str, MemoryNode]] = None,
    ) -> "RetrievalResultDoc":
        """Parse LLM JSON response into RetrievalResultDoc.

        Supports legacy schema (turns/links_to_follow) and RetrievalPlan schema.
        """
        if "selected_nodes" in response:
            plan = RetrievalPlanDoc.from_llm_response(
                response,
                valid_node_ids=set(memory_index.keys()) if memory_index else None,
            )
            return cls.from_retrieval_plan(
                query=query,
                plan=plan,
                memory_index=memory_index or {},
                is_followup=is_followup,
                inherited_topic=inherited_topic,
            )

        relevant_turns = []
        direct_info = {}

        # Parse turns (merged SCAN + READ output)
        for i, turn_data in enumerate(response.get("turns", [])):
            turn_num = turn_data.get("turn", 0)
            usable = turn_data.get("usable_info", turn_data.get("summary", ""))

            relevant_turns.append(RetrievalTurn(
                turn_number=turn_num,
                relevance=turn_data.get("relevance", "medium"),
                reason=turn_data.get("reason", ""),
                usable_info=usable,
                expected_info=turn_data.get("expected_info", ""),
                load_priority=i + 1
            ))

            # Build direct_info dict
            if usable:
                direct_info[str(turn_num)] = usable

        # Parse links to follow
        links = []
        for link_data in response.get("links_to_follow", []):
            links.append(LinkToFollow(
                turn_number=link_data.get("turn", 0),
                path=link_data.get("path", link_data.get("link", "")),
                reason=link_data.get("reason", ""),
                sections_to_extract=link_data.get("extract", link_data.get("sections_to_extract", []))
            ))

        return cls(
            query=query,
            timestamp=datetime.utcnow().isoformat() + "Z",
            relevant_turns=relevant_turns,
            direct_info=direct_info,
            links_to_follow=links,
            sufficient=response.get("sufficient", True),
            missing_info=response.get("missing_info", ""),
            reasoning=response.get("reasoning", ""),
            is_followup=is_followup,
            inherited_topic=inherited_topic
        )

    @classmethod
    def from_retrieval_plan(
        cls,
        query: str,
        plan: RetrievalPlanDoc,
        memory_index: Dict[str, MemoryNode],
        is_followup: bool = False,
        inherited_topic: Optional[str] = None,
    ) -> "RetrievalResultDoc":
        relevant_turns: List[RetrievalTurn] = []
        direct_info: Dict[str, str] = {}
        links: List[LinkToFollow] = []

        # Turn summaries → relevant_turns + context.md links
        for i, node_id in enumerate(plan.selected_nodes.get("turn_summary", []), start=1):
            node = memory_index.get(node_id)
            if not node:
                continue
            turn_num = 0
            if node_id.startswith("turn:"):
                try:
                    turn_num = int(node_id.split("turn:")[1])
                except ValueError:
                    turn_num = 0
            relevant_turns.append(RetrievalTurn(
                turn_number=turn_num,
                relevance="high",
                reason=plan.selection_reasons.get("turn_summary", ""),
                usable_info="",
                expected_info="",
                load_priority=i,
            ))
            if node.source_ref:
                links.append(LinkToFollow(
                    turn_number=turn_num,
                    path=node.source_ref,
                    reason=plan.selection_reasons.get("turn_summary", ""),
                    sections_to_extract=["prior_turn_context"],
                ))

        # Other nodes → links to follow
        def _add_links(source_type: str, sections: List[str]):
            for node_id in plan.selected_nodes.get(source_type, []):
                node = memory_index.get(node_id)
                if not node or not node.source_ref:
                    continue
                links.append(LinkToFollow(
                    turn_number=0,
                    path=node.source_ref,
                    reason=plan.selection_reasons.get(source_type, ""),
                    sections_to_extract=sections,
                ))

        _add_links("preference", ["preferences"])
        _add_links("fact", ["facts"])
        _add_links("research_cache", ["research_cache"])
        _add_links("visit_record", ["visit_record"])

        return cls(
            query=query,
            timestamp=datetime.utcnow().isoformat() + "Z",
            relevant_turns=relevant_turns,
            direct_info=direct_info,
            links_to_follow=links,
            sufficient=False,
            missing_info="",
            reasoning=plan.reasoning,
            is_followup=is_followup,
            inherited_topic=inherited_topic,
        )

    @classmethod
    def from_search_results(
        cls,
        query: str,
        search_results: "SearchResults",
        is_followup: bool = False,
        inherited_topic: Optional[str] = None,
    ) -> "RetrievalResultDoc":
        """Bridge: Convert SearchResults to RetrievalResultDoc for synthesis.

        Maps search result items to the legacy format so _phase_synthesis()
        works unchanged.

        Architecture Reference:
            architecture/main-system-patterns/phase2.1-context-gathering-retrieval.md v2.0
        """
        relevant_turns = []
        direct_info = {}
        links = []

        for i, item in enumerate(search_results.results):
            if item.source_type == "turn_summary":
                turn_num = 0
                if "turn:" in item.node_id:
                    try:
                        turn_num = int(item.node_id.split("turn:")[1])
                    except (ValueError, IndexError):
                        pass

                relevant_turns.append(RetrievalTurn(
                    turn_number=turn_num,
                    relevance="high" if item.source == "search" else "critical",
                    reason=f"Matched search terms (RRF={item.rrf_score:.3f})",
                    usable_info=item.snippet,
                    expected_info="",
                    load_priority=i + 1,
                ))

                if item.content:
                    direct_info[str(turn_num)] = item.content[:1500]

                links.append(LinkToFollow(
                    turn_number=turn_num,
                    path=item.document_path,
                    reason=f"Search match (RRF={item.rrf_score:.3f})",
                    sections_to_extract=["prior_turn_context"],
                ))
            else:
                # Non-turn items: knowledge, preferences, beliefs, research cache
                links.append(LinkToFollow(
                    turn_number=0,
                    path=item.document_path,
                    reason=f"{item.source_type} match (RRF={item.rrf_score:.3f})",
                    sections_to_extract=[item.source_type],
                ))

        return cls(
            query=query,
            timestamp=datetime.utcnow().isoformat() + "Z",
            relevant_turns=relevant_turns,
            direct_info=direct_info,
            links_to_follow=links,
            sufficient=bool(search_results.results),
            missing_info="",
            reasoning=(
                f"Search-first retrieval: {len(search_results.results)} results "
                f"from {len(search_results.search_terms_used)} search terms"
            ),
            is_followup=is_followup,
            inherited_topic=inherited_topic,
        )

    def has_links_to_follow(self) -> bool:
        return len(self.links_to_follow) > 0

    def get_turn_numbers(self) -> List[int]:
        """Get list of turn numbers identified as relevant."""
        return [t.turn_number for t in self.relevant_turns]


@dataclass
class SynthesisInputDoc:
    """
    Input document assembled for SYNTHESIS phase.

    Contains:
    - Retrieval result (direct info + links to follow)
    - Linked document content (if links were followed)
    - Supplementary sources (cache, research index, lessons, session memory)
    """
    query: str
    retrieval_result: RetrievalResultDoc
    linked_docs: Dict[str, str]  # path -> content
    cached_intelligence: Optional[Dict[str, Any]]
    intel_metadata: Optional[Dict[str, Any]]
    research_index_results: List[Dict[str, Any]]
    matching_lessons: List[Any]
    session_memory: Dict[str, str]

    def to_markdown(self) -> str:
        lines = [
            "# Synthesis Input",
            f"**Query:** {self.query}",
            "**Phase:** SYNTHESIS (merged EXTRACT+COMPILE)",
            "",
            "---",
            "",
        ]

        # Direct info section
        lines.extend([
            "## Direct Information from Retrieval",
            "",
        ])
        for turn, info in self.retrieval_result.direct_info.items():
            lines.extend([
                f"### Turn {turn}",
                info,
                "",
            ])

        # Linked docs section (if any)
        if self.linked_docs:
            lines.extend([
                "---",
                "",
                "## Linked Documents to Extract From",
                "",
            ])
            for path, content in self.linked_docs.items():
                lines.extend([
                    f"### {path}",
                    content[:2000],
                    "",
                ])
                if len(content) > 2000:
                    lines.append("*[Content truncated...]*")
                    lines.append("")

        # Supplementary sources
        if self.cached_intelligence:
            age = self.intel_metadata.get("age_hours", 0) if self.intel_metadata else 0
            lines.extend([
                "---",
                "",
                "## Cached Intelligence",
                f"*Age: {age:.1f}h*",
                "",
            ])
            retailers = self.cached_intelligence.get("retailers", {})
            if isinstance(retailers, dict):
                lines.append(f"**Retailers:** {', '.join(list(retailers.keys())[:5])}")
            elif isinstance(retailers, list):
                lines.append(f"**Retailers:** {', '.join(retailers[:5])}")
            lines.append("")

        if self.research_index_results:
            lines.extend([
                "---",
                "",
                "## Research Index Matches",
                "",
            ])
            for doc in self.research_index_results[:3]:
                lines.append(f"- **{doc.get('topic', 'unknown')}** (quality={doc.get('quality_score', 0):.2f})")
            lines.append("")

        if self.matching_lessons:
            lines.extend([
                "---",
                "",
                "## Matching Strategy Lessons",
                "",
            ])
            for lesson in self.matching_lessons[:2]:
                lines.append(f"- {getattr(lesson, 'lesson_id', str(lesson))}: {getattr(lesson, 'strategy_profile', '')}")
            lines.append("")

        if any(self.session_memory.values()):
            lines.extend([
                "---",
                "",
                "## Session Memory",
                "",
            ])
            if self.session_memory.get("preferences"):
                lines.append(f"**Preferences:** {self.session_memory['preferences'][:200]}...")
            lines.append("")

        return "\n".join(lines)
