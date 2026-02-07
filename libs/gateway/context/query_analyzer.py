"""
Panda Query Analyzer - Phase 1 of the 8-phase pipeline.

Understands the user's query, resolves references to previous context,
and produces structured analysis that flows through the entire pipeline.

This replaces the hardcoded pattern matching that was in:
- _resolve_query_with_n1() in unified_flow.py
- _preload_for_followup() in context_gatherer_2phase.py
- _detect_followup() in context_gatherer_2phase.py

Architecture Reference:
    architecture/concepts/main-system-patterns/phase1-query-analyzer.md
"""

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from libs.gateway.llm.recipe_loader import load_recipe, RecipeNotFoundError
from libs.gateway.parsing.forgiving_parser import ForgivingParser

logger = logging.getLogger(__name__)


@dataclass
class ContentReference:
    """Reference to specific content from previous turns."""
    title: str                          # Exact title
    content_type: str                   # "thread", "article", "product", "video", "post"
    site: Optional[str] = None          # "reddit.com", "forum.example.com"
    source_turn: Optional[int] = None   # Which turn this was discussed in
    prior_findings: Optional[str] = None  # Summary of what we already know

    # Visit record info (for cached page data)
    source_url: Optional[str] = None           # Direct URL to the content
    has_visit_record: bool = False             # Do we have cached page data?
    visit_record_path: Optional[str] = None    # Path to visit_records/{slug}/


@dataclass
class QueryAnalysis:
    """
    Output from Query Analyzer role (Phase 1).

    MINIMAL OUTPUT - Query Analyzer only does:
    1. Detect junk queries
    2. Resolve pronouns
    3. Describe user intent

    All other analysis (data requirements, URL lookups) is done by downstream phases.
    """

    # Original user input before resolution
    original_query: str = ""

    # The resolved query - pronouns replaced with explicit references
    resolved_query: str = ""

    # Natural language statement of what the user wants (1-2 sentences)
    user_purpose: str = ""

    # Reference resolution details
    reference_resolution: Dict[str, Any] = None

    # Was reference resolution performed?
    was_resolved: bool = False

    # Is this query garbled/junk?
    is_junk: bool = False

    # Reasoning for debugging
    reasoning: str = ""

    # Phase 1.5 validation output
    validation: Dict[str, Any] = None

    # =========================================================================
    # LEGACY FIELDS (retained for backward compatibility during migration)
    # These should NOT be set by Query Analyzer - downstream phases handle them
    # =========================================================================

    # Mode - passed through from UI, not analyzed
    mode: str = "chat"

    # Content reference - enriched by Context Gatherer, not Query Analyzer
    content_reference: Optional[ContentReference] = None

    # Legacy fields (deprecated)
    action_needed: Optional[str] = None
    data_requirements: Dict[str, Any] = None
    prior_context: Optional[Dict[str, Any]] = None
    is_multi_task: bool = False
    task_breakdown: Optional[List[Dict[str, Any]]] = None

    def __post_init__(self):
        if self.data_requirements is None:
            self.data_requirements = {}
        if self.reference_resolution is None:
            self.reference_resolution = {
                "status": "not_needed",
                "original_references": [],
                "resolved_to": None,
            }
        if self.prior_context is None:
            self.prior_context = {}
        if self.validation is None:
            self.validation = {}
        if self.task_breakdown is None:
            self.task_breakdown = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            # Core fields (Query Analyzer output)
            "original_query": self.original_query,
            "resolved_query": self.resolved_query,
            "user_purpose": self.user_purpose,
            "reference_resolution": self.reference_resolution,
            "was_resolved": self.was_resolved,
            "is_junk": self.is_junk,
            "reasoning": self.reasoning,
            "validation": self.validation,
            # Legacy fields (for backward compatibility)
            "mode": self.mode,
            "data_requirements": self.data_requirements,
            "is_multi_task": self.is_multi_task,
            "task_breakdown": self.task_breakdown if self.task_breakdown else None,
        }
        # Optional legacy fields
        if self.action_needed is not None:
            result["action_needed"] = self.action_needed
        if self.prior_context:
            result["prior_context"] = self.prior_context
        if self.content_reference:
            result["content_reference"] = asdict(self.content_reference)
        else:
            result["content_reference"] = None
        return result

    def save(self, turn_dir: Path) -> Path:
        """
        Save QueryAnalysis as a document in the turn directory.

        Args:
            turn_dir: Path to the turn directory (e.g., panda_system_docs/turns/turn_000123)

        Returns:
            Path to the saved document
        """
        # Ensure turn_dir exists
        turn_dir = Path(turn_dir)
        turn_dir.mkdir(parents=True, exist_ok=True)

        # Save as JSON for easy parsing by Context Gatherer
        json_path = turn_dir / "query_analysis.json"
        with open(json_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

        logger.info(f"[QueryAnalyzer] Saved analysis to {json_path}")
        return json_path

    @classmethod
    def load(cls, turn_dir: Path) -> Optional["QueryAnalysis"]:
        """
        Load QueryAnalysis from a turn directory.

        Args:
            turn_dir: Path to the turn directory

        Returns:
            QueryAnalysis if found, None otherwise
        """
        json_path = Path(turn_dir) / "query_analysis.json"
        if not json_path.exists():
            return None

        try:
            with open(json_path, "r") as f:
                data = json.load(f)

            content_ref = None
            if data.get("content_reference"):
                ref_data = data["content_reference"]
                content_ref = ContentReference(
                    title=ref_data.get("title", ""),
                    content_type=ref_data.get("content_type", "unknown"),
                    site=ref_data.get("site"),
                    source_turn=ref_data.get("source_turn"),
                    prior_findings=ref_data.get("prior_findings"),
                    # Visit record info
                    source_url=ref_data.get("source_url"),
                    has_visit_record=ref_data.get("has_visit_record", False),
                    visit_record_path=ref_data.get("visit_record_path")
                )

            return cls(
                original_query=data.get("original_query", ""),
                resolved_query=data.get("resolved_query", ""),
                user_purpose=data.get("user_purpose", ""),
                action_needed=data.get("action_needed"),
                data_requirements=data.get("data_requirements", {}),
                reference_resolution=data.get("reference_resolution"),
                prior_context=data.get("prior_context"),
                mode=data.get("mode", "chat"),
                was_resolved=data.get("was_resolved", False),
                content_reference=content_ref,
                reasoning=data.get("reasoning", ""),
                validation=data.get("validation"),
                is_multi_task=data.get("is_multi_task", False),
                task_breakdown=data.get("task_breakdown"),
            )

        except Exception as e:
            logger.warning(f"[QueryAnalyzer] Failed to load analysis from {json_path}: {e}")
            return None


class QueryAnalyzer:
    """
    Phase 1: Analyzes user queries before Context Gatherer.

    Responsibilities:
    1. Understand what the user is asking
    2. Resolve references to previous context
    3. Identify if asking about specific content
    4. Produce structured analysis for downstream phases
    """

    def __init__(
        self,
        llm_client: Any,
        turns_dir: Path = None,
        max_lookback: int = 3
    ):
        self.llm_client = llm_client
        self.turns_dir = turns_dir or Path("panda_system_docs/turns")
        self.max_lookback = max_lookback

    async def analyze(self, query: str, turn_number: int, mode: str = "chat") -> QueryAnalysis:
        """
        Analyze the user query and resolve any references.

        Fail-fast policy (architecture/main-system-patterns/phase2-context-gathering.md §9):
        - RecipeNotFoundError → propagate (hard error)
        - LLM call failure → propagate (hard error)
        - Parse failure → retry once, then propagate (hard error)

        Args:
            query: Raw user query
            turn_number: Current turn number

        Returns:
            QueryAnalysis with resolved query and context

        Raises:
            RecipeNotFoundError: If the Phase 0 recipe is missing.
            Exception: If the LLM call fails.
            ValueError: If the LLM response cannot be parsed after 1 retry.
        """
        logger.info(f"[QueryAnalyzer] Analyzing query for turn {turn_number}: '{query[:50]}...'")

        # Load recent turn summaries (Appendix preferred; fallback to per-turn extraction)
        turn_summaries = self._load_recent_turns(turn_number)
        if not turn_summaries:
            logger.info("[QueryAnalyzer] No previous turns found for reference resolution")

        # Load prompt from recipe system (raises RecipeNotFoundError on missing)
        recipe = load_recipe("pipeline/phase0_query_analyzer")
        prompt_template = recipe.get_prompt()

        # Use recipe-defined temperature and output budget
        # See: architecture/LLM-ROLES/llm-roles-reference.md (REFLEX role = 0.4)
        temperature = recipe._raw_spec.get("llm_params", {}).get("temperature", 0.4)
        max_tokens = recipe._raw_spec.get("llm_params", {}).get("max_tokens", 200)

        # Format turn summaries
        summaries_text = self._format_turn_summaries(turn_summaries)

        def _format_list(items: List[str]) -> str:
            if not items:
                return "none"
            return "\n".join(f"- {item}" for item in items)

        def build_prompt(retry_context: Optional[Dict[str, Any]] = None) -> str:
            prompt = (
                prompt_template
                + f"\n\n---\n\n## Actual Input\n\n```\nQUERY: {query}\n\nRECENT TURNS:\n{summaries_text}\n```"
            )
            if retry_context:
                issues = _format_list(retry_context.get("issues") or [])
                guidance = _format_list(retry_context.get("retry_guidance") or [])
                prompt += f"\n\n## Validator Feedback\nIssues:\n{issues}\n\nRetry Guidance:\n{guidance}\n"
            return prompt

        async def run_query_analysis(prompt: str) -> QueryAnalysis:
            last_error: Optional[Exception] = None
            for attempt in range(2):
                response = await self.llm_client.call(
                    prompt=prompt,
                    role="query_analyzer",
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                try:
                    parsed = self._parse_response(query, response)
                    return parsed
                except (ValueError, json.JSONDecodeError) as e:
                    last_error = e
                    if attempt == 0:
                        logger.warning(f"[QueryAnalyzer] Parse failed (attempt 1), retrying: {e}")
                        continue
                    logger.error(f"[QueryAnalyzer] Parse failed after retry: {e}")
                    raise
            raise last_error  # type: ignore[misc]

        analysis = await run_query_analysis(build_prompt())
        analysis.original_query = query
        analysis.mode = mode

        # Phase 1.5 validation helper
        validation = await self._run_validation(query, analysis)
        if validation.get("status") == "retry":
            analysis = await run_query_analysis(build_prompt(validation))
            analysis.original_query = query
            analysis.mode = mode
            validation = await self._run_validation(query, analysis)
        analysis.validation = validation

        # NOTE: URL enrichment (visit records, extracted links) is now handled by
        # Context Gatherer (Phase 2), not Query Analyzer. Query Analyzer only
        # resolves pronouns and describes user intent.

        if analysis.was_resolved:
            logger.info(f"[QueryAnalyzer] Resolved: '{query[:30]}...' → '{analysis.resolved_query[:50]}...'")
        else:
            logger.info("[QueryAnalyzer] No resolution needed")

        if analysis.content_reference:
            logger.info(f"[QueryAnalyzer] Content reference: {analysis.content_reference.title[:50]}... ({analysis.content_reference.content_type})")

        return analysis

    def _load_recent_turns(self, turn_number: int) -> List[Dict[str, Any]]:
        """Load summaries of recent turns."""
        summaries = self._load_turn_summary_appendix(turn_number)
        if summaries:
            return summaries

        summaries = []

        for i in range(1, min(self.max_lookback + 1, turn_number)):
            prev_turn = turn_number - i
            turn_dir = self.turns_dir / f"turn_{prev_turn:06d}"

            if not turn_dir.exists():
                continue

            summary = self._extract_turn_summary(turn_dir, prev_turn)
            if summary:
                summaries.append(summary)

        return summaries

    def _load_turn_summary_appendix(self, turn_number: int) -> List[Dict[str, Any]]:
        """
        Load Turn Summary Appendix from the most recent context.md if present.

        Expected to be appended as a final section with a JSON block. Supports:
        - list of summaries
        - object with "turn_summaries"
        - single summary object
        """
        if turn_number <= 1:
            return []

        prev_turn = turn_number - 1
        context_path = self.turns_dir / f"turn_{prev_turn:06d}" / "context.md"
        if not context_path.exists():
            return []

        try:
            content = context_path.read_text()
        except Exception:
            return []

        match = re.search(
            r"##\\s+.*Turn Summary.*?```json\\s*(\\{[\\s\\S]*?\\}|\\[[\\s\\S]*?\\])\\s*```",
            content,
            flags=re.IGNORECASE,
        )
        if not match:
            return []

        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "turn_summaries" in parsed:
            return parsed.get("turn_summaries") or []
        if isinstance(parsed, dict):
            return [parsed]
        return []

    def _extract_turn_summary(self, turn_dir: Path, turn_number: int) -> Optional[Dict[str, Any]]:
        """Extract summary from a turn directory."""
        context_path = turn_dir / "context.md"
        response_path = turn_dir / "response.md"

        if not context_path.exists():
            return None

        try:
            content = context_path.read_text()

            # Extract user query (§0)
            user_query = ""
            if "## 0. User Query" in content:
                query_section = content.split("## 0. User Query")[1]
                if "---" in query_section:
                    query_section = query_section.split("---")[0]
                elif "## 1." in query_section:
                    query_section = query_section.split("## 1.")[0]
                user_query = query_section.strip()[:200]

            # Extract topic if present
            topic = ""
            topic_match = re.search(
                r'\*\*Topic[:\s]*\*\*\s*([^\n]+)',
                content, re.IGNORECASE
            )
            if topic_match:
                topic = topic_match.group(1).strip()

            # Extract key entities (thread titles, product names, etc.)
            entities = []
            # Look for quoted titles
            title_matches = re.findall(r'["\*]{1,2}([^"*\n]{10,100})["\*]{1,2}', content)
            entities.extend(title_matches[:3])  # Limit to 3

            # Extract §4 findings (key results from tool execution)
            # These are critical for follow-up reference resolution
            findings_summary = ""
            if "## 4." in content:
                try:
                    section4 = content.split("## 4.")[1]
                    # End at next top-level section
                    for marker in ["## 5.", "## 6.", "---\n\n##"]:
                        if marker in section4:
                            section4 = section4.split(marker)[0]
                            break
                    # Extract Findings lines (most information-dense)
                    findings_lines = []
                    for line in section4.split("\n"):
                        line_s = line.strip()
                        if line_s.startswith("- ") or line_s.startswith("**Findings:**"):
                            findings_lines.append(line_s)
                    if findings_lines:
                        findings_summary = "\n".join(findings_lines)[:400]
                except Exception:
                    pass

            # Extract brief response summary
            # Response may be in response.md OR in context.md section 5/6
            response_summary = ""
            if response_path.exists():
                try:
                    resp_content = response_path.read_text()
                    if "**Draft Response:**" in resp_content:
                        resp_section = resp_content.split("**Draft Response:**")[1]
                        response_summary = resp_section.strip()[:400]
                    else:
                        response_summary = resp_content.strip()[:400]
                except Exception:
                    pass

            # Fallback: extract from context.md section 5/6 if no response.md
            if not response_summary:
                for section_marker in ["## 6. Synthesis", "## 5. Synthesis"]:
                    if section_marker in content:
                        try:
                            synth_section = content.split(section_marker)[1]
                            if "---" in synth_section:
                                synth_section = synth_section.split("---")[0]
                            if "**Draft Response:**" in synth_section:
                                resp_section = synth_section.split("**Draft Response:**")[1]
                                response_summary = resp_section.strip()[:400]
                                break
                        except Exception:
                            pass

            # Load prior turn's user_purpose from query_analysis.json if available
            prior_user_purpose = None
            prior_analysis_path = turn_dir / "query_analysis.json"
            if prior_analysis_path.exists():
                try:
                    prior_analysis = json.loads(prior_analysis_path.read_text())
                    prior_user_purpose = prior_analysis.get("user_purpose")
                except Exception:
                    pass

            # Load extracted links from research.json for reference resolution
            # This enables follow-up queries like "tell me more about that thread"
            extracted_links = []
            research_path = turn_dir / "research.json"
            if research_path.exists():
                try:
                    research_data = json.loads(research_path.read_text())
                    extracted_links = research_data.get("extracted_links", [])
                except Exception:
                    pass

            return {
                "turn": turn_number,
                "user_query": user_query,
                "topic": topic,
                "entities": entities,
                "response_summary": response_summary,
                "findings_summary": findings_summary,  # §4 execution results for reference resolution
                "user_purpose": prior_user_purpose,  # Include prior purpose for context
                "extracted_links": extracted_links,  # Links with titles for reference resolution
            }

        except Exception as e:
            logger.warning(f"[QueryAnalyzer] Failed to extract turn {turn_number} summary: {e}")
            return None

    def _enrich_with_visit_record(self, content_ref: ContentReference) -> ContentReference:
        """
        Enrich a ContentReference with visit record info if available.

        After the LLM identifies which turn/content is being referenced, this method
        checks for cached page data in visit_records/.
        """
        if not content_ref.source_turn:
            return content_ref

        turn_dir = self.turns_dir / f"turn_{content_ref.source_turn:06d}"
        visit_records_dir = turn_dir / "visit_records"

        if not visit_records_dir.exists():
            logger.debug(f"[QueryAnalyzer] No visit_records directory for turn {content_ref.source_turn}")
            return content_ref

        # Look for manifest.json files in visit_records subdirectories
        for subdir in visit_records_dir.iterdir():
            if not subdir.is_dir():
                continue

            manifest_path = subdir / "manifest.json"
            if not manifest_path.exists():
                continue

            try:
                manifest = json.loads(manifest_path.read_text())

                # Check if this visit record matches the content we're looking for
                manifest_title = manifest.get("title", "").lower()
                manifest_url = manifest.get("source_url", "")
                ref_title = content_ref.title.lower()

                # Match by title similarity or site match
                title_match = (
                    ref_title in manifest_title or
                    manifest_title in ref_title or
                    (content_ref.site and content_ref.site in manifest_url)
                )

                if title_match:
                    # Found matching visit record
                    content_ref.source_url = manifest_url
                    content_ref.has_visit_record = True
                    # Path relative to turns_dir.parent (panda_system_docs)
                    content_ref.visit_record_path = str(subdir.relative_to(self.turns_dir.parent))

                    logger.info(
                        f"[QueryAnalyzer] Found visit record for '{content_ref.title[:30]}...' "
                        f"at {content_ref.visit_record_path}"
                    )
                    return content_ref

            except Exception as e:
                logger.warning(f"[QueryAnalyzer] Error reading manifest {manifest_path}: {e}")
                continue

        logger.debug(f"[QueryAnalyzer] No matching visit record found in turn {content_ref.source_turn}")
        return content_ref

    def _enrich_with_extracted_links(
        self, content_ref: ContentReference, current_turn: int
    ) -> ContentReference:
        """
        Look up source_url from previous turns' research.json extracted_links.

        When user asks about a specific thread/article mentioned in a previous turn,
        this finds the actual URL from that turn's research results.
        """
        if content_ref.source_url:
            # Already have URL, no need to search
            return content_ref

        ref_title = content_ref.title.lower().strip()
        ref_site = content_ref.site.lower() if content_ref.site else None

        # Search recent turns (up to max_lookback)
        for i in range(1, min(self.max_lookback + 1, current_turn)):
            prev_turn = current_turn - i
            turn_dir = self.turns_dir / f"turn_{prev_turn:06d}"
            research_path = turn_dir / "research.json"

            if not research_path.exists():
                continue

            try:
                research_data = json.loads(research_path.read_text())
                extracted_links = research_data.get("extracted_links", [])

                for link in extracted_links:
                    link_title = link.get("title", "").lower().strip()
                    link_url = link.get("url", "")

                    if not link_title or not link_url:
                        continue

                    # Match by title similarity
                    # Use substring matching for flexibility
                    title_match = (
                        ref_title in link_title or
                        link_title in ref_title or
                        # Also try without common prefixes
                        ref_title.replace("the ", "") in link_title or
                        link_title in ref_title.replace("the ", "")
                    )

                    # If site specified, verify URL matches
                    if ref_site and title_match:
                        site_match = ref_site in link_url.lower()
                        if not site_match:
                            continue

                    if title_match:
                        content_ref.source_url = link_url
                        content_ref.source_turn = prev_turn
                        logger.info(
                            f"[QueryAnalyzer] Found URL for '{content_ref.title[:30]}...' "
                            f"in turn {prev_turn}: {link_url[:60]}..."
                        )
                        return content_ref

            except Exception as e:
                logger.warning(f"[QueryAnalyzer] Error reading research.json from turn {prev_turn}: {e}")
                continue

        logger.debug(f"[QueryAnalyzer] No matching extracted_links found for '{ref_title[:30]}...'")
        return content_ref

    def _format_turn_summaries(self, summaries: List[Dict[str, Any]]) -> str:
        """Format turn summaries for the prompt."""
        if not summaries:
            return "No previous turns in this session."

        lines = []
        for s in summaries:
            if "summary" in s:
                turn_id = s.get("turn_id") or s.get("turn") or "unknown"
                lines.append(f"### Turn {turn_id}")
                lines.append(f"**Summary:** {s.get('summary', '').strip()}")
                content_refs = s.get("content_refs") or []
                if content_refs:
                    lines.append(f"**Content refs:** {', '.join(content_refs[:3])}")
                topics = s.get("topics") or []
                if topics:
                    lines.append(f"**Topics:** {', '.join(topics[:5])}")
                lines.append("")
                continue

            turn_label = f"Turn N-{summaries.index(s) + 1}"
            lines.append(f"### {turn_label} (Turn {s.get('turn', 'unknown')})")
            lines.append(f"**User asked:** {s.get('user_query', '')}")
            if s.get('user_purpose'):
                lines.append(f"**Purpose:** {s['user_purpose'][:200]}...")
            if s.get('topic'):
                lines.append(f"**Topic:** {s['topic']}")
            if s.get('entities'):
                lines.append(f"**Key entities:** {', '.join(s['entities'][:3])}")
            if s.get('findings_summary'):
                lines.append(f"**Findings:** {s['findings_summary'][:250]}")
            if s.get('response_summary'):
                lines.append(f"**Response:** {s['response_summary'][:200]}...")

            # Include extracted links with titles for reference resolution
            # This enables follow-up queries like "tell me more about that thread"
            extracted_links = s.get('extracted_links', [])
            if extracted_links:
                lines.append("**Links mentioned:**")
                for link in extracted_links[:10]:  # Limit to 10 links
                    title = link.get('title', '')
                    url = link.get('url', '')
                    context = link.get('context', '')
                    if title and url:
                        if context:
                            lines.append(f"  - \"{title}\" ({context}): {url}")
                        else:
                            lines.append(f"  - \"{title}\": {url}")
            lines.append("")

        return "\n".join(lines)

    async def _run_validation(self, raw_query: str, analysis: QueryAnalysis) -> Dict[str, Any]:
        """Run Phase 1.5 validation helper on the QueryAnalysis output."""
        recipe = load_recipe("pipeline/phase1_5_query_analyzer_validator")
        prompt_template = recipe.get_prompt()

        prompt = (
            prompt_template
            + "\n\n---\n\n## Input\n\n```\n"
            + f"RAW_QUERY: {raw_query}\n\nQUERY_ANALYSIS_JSON:\n{json.dumps(analysis.to_dict(), indent=2)}\n```"
        )

        temperature = recipe._raw_spec.get("llm_params", {}).get("temperature", 0.4)
        max_tokens = recipe._raw_spec.get("llm_params", {}).get("max_tokens", 150)

        response = await self.llm_client.call(
            prompt=prompt,
            role="query_analyzer_validator",
            max_tokens=max_tokens,
            temperature=temperature,
        )

        return self._parse_validation(response)

    def _parse_validation(self, response: str) -> Dict[str, Any]:
        """Parse validator response into a validation object."""
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            raise ValueError(
                f"Phase 1.5: No JSON found in LLM response. "
                f"Response preview: {response[:200]}"
            )

        data = json.loads(json_match.group())
        status = data.get("status", "pass")
        if status not in {"pass", "retry", "clarify"}:
            logger.warning(f"[QueryAnalyzer] Invalid validation.status '{status}', defaulting to pass")
            status = "pass"

        return {
            "status": status,
            "confidence": data.get("confidence", 0.0),
            "issues": data.get("issues") or [],
            "retry_guidance": data.get("retry_guidance") or [],
            "clarification_question": data.get("clarification_question"),
        }

    def _parse_response(self, original_query: str, response: str) -> QueryAnalysis:
        """Parse LLM response into QueryAnalysis.

        Simplified schema - Query Analyzer only outputs:
        - resolved_query, user_purpose, reference_resolution, was_resolved, is_junk, reasoning

        Uses ForgivingParser for robust JSON extraction.

        Raises:
            ValueError: If response contains no parseable JSON after all strategies.
        """
        # Use ForgivingParser for robust JSON extraction
        parser = ForgivingParser()
        schema = {
            "resolved_query": {"type": "string", "default": original_query},
            "user_purpose": {"type": "string", "default": ""},
            "reference_resolution": {
                "type": "object",
                "default": {"status": "not_needed", "original_references": [], "resolved_to": None}
            },
            "was_resolved": {"type": "boolean", "default": False},
            "is_junk": {"type": "boolean", "default": False},
            "reasoning": {"type": "string", "default": ""},
        }
        result = parser.parse(response, schema)

        if not result.success and result.strategy_used == "defaults":
            raise ValueError(
                f"Phase 0: Could not parse LLM response after all strategies. "
                f"Response preview: {response[:200]}"
            )

        if result.warnings:
            logger.warning(f"[QueryAnalyzer] Parse warnings: {result.warnings}")

        data = result.data

        # Extract and validate reference resolution
        reference_resolution = data.get("reference_resolution") or {}
        status = reference_resolution.get("status", "not_needed")
        if status not in {"not_needed", "resolved", "failed"}:
            logger.warning(f"[QueryAnalyzer] Invalid reference_resolution.status '{status}', defaulting to not_needed")
            status = "not_needed"
        reference_resolution = {
            "status": status,
            "original_references": reference_resolution.get("original_references") or [],
            "resolved_to": reference_resolution.get("resolved_to"),
        }

        return QueryAnalysis(
            resolved_query=data.get("resolved_query", original_query),
            user_purpose=data.get("user_purpose", ""),
            reference_resolution=reference_resolution,
            was_resolved=data.get("was_resolved", False),
            is_junk=data.get("is_junk", False),
            reasoning=data.get("reasoning", ""),
        )


async def analyze_query(
    query: str,
    turn_number: int,
    llm_client: Any,
    turns_dir: Path = None,
    mode: str = "chat"
) -> QueryAnalysis:
    """
    Convenience function to analyze a query.

    Args:
        query: Raw user query
        turn_number: Current turn number
        llm_client: LLM client for making calls
        turns_dir: Directory containing turn data

    Returns:
        QueryAnalysis with resolved query and context
    """
    analyzer = QueryAnalyzer(
        llm_client=llm_client,
        turns_dir=turns_dir
    )
    return await analyzer.analyze(query, turn_number, mode=mode)
