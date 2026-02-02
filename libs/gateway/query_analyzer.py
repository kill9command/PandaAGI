"""
Query Analyzer - Phase 0 of the pipeline.

Understands the user's query, resolves references to previous context,
and produces structured analysis that flows through the entire pipeline.

This replaces the hardcoded pattern matching that was in:
- _resolve_query_with_n1() in unified_flow.py
- _preload_for_followup() in context_gatherer_2phase.py
- _detect_followup() in context_gatherer_2phase.py

See: panda_system_docs/architecture/main-system-patterns/phase0-query-analyzer.md
"""

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from libs.gateway.recipe_loader import load_recipe, RecipeNotFoundError

logger = logging.getLogger(__name__)


@dataclass
class ContentReference:
    """Reference to specific content from previous turns."""
    title: str                          # Exact title
    content_type: str                   # "thread", "article", "product", "video", "post"
    site: Optional[str] = None          # "reddit.com", "reef2reef.com"
    source_turn: Optional[int] = None   # Which turn this was discussed in
    prior_findings: Optional[str] = None  # Summary of what we already know

    # Visit record info (for cached page data)
    source_url: Optional[str] = None           # Direct URL to the content
    has_visit_record: bool = False             # Do we have cached page data?
    visit_record_path: Optional[str] = None    # Path to visit_records/{slug}/


@dataclass
class QueryAnalysis:
    """
    Output from Query Analyzer role (Phase 0).

    This uses natural language user_purpose instead of rigid intent categories.
    Downstream LLM roles read user_purpose to understand what the user wants.
    """

    # The resolved query - explicit and unambiguous
    resolved_query: str

    # =========================================================================
    # NEW: Natural Language User Purpose (replaces rigid intent categories)
    # =========================================================================

    # Natural language statement of what the user wants (2-4 sentences)
    # Captures: what they want, why, priorities, constraints, relationship to prior turns
    # Example: "User wants to find and buy the cheapest laptop with nvidia GPU.
    #          Price is the top priority. This continues their previous search."
    user_purpose: str = ""

    # What action is needed to satisfy this request
    # live_search: Need to search the web for current data
    # recall_memory: Need to look up user's stored preferences/history
    # answer_from_context: Can answer from gathered context (no tools needed)
    # navigate_to_site: Need to visit a specific URL
    # execute_code: Need to run code operations (code mode)
    # unclear: Need clarification from user
    action_needed: str = "unclear"

    # What kind of data is needed to satisfy the request
    # Example: {"needs_current_prices": true, "needs_product_urls": true, "freshness_required": "< 1 hour"}
    data_requirements: Dict[str, Any] = None

    # How this relates to previous turns
    # Example: {"continues_topic": "laptop shopping", "prior_turn_purpose": "Find cheapest nvidia laptop"}
    prior_context: Dict[str, Any] = None

    # =========================================================================
    # Mode and Reference Resolution
    # =========================================================================

    # Mode classification: "chat" or "code"
    # Determines which tool set and prompts to use
    mode: str = "chat"

    # Was reference resolution performed?
    was_resolved: bool = False

    # If query references previous content
    content_reference: Optional[ContentReference] = None

    # Reasoning for debugging
    reasoning: str = ""

    # =========================================================================
    # Multi-task detection (Pandora Loop)
    # =========================================================================

    # When True, the query requires multiple distinct tasks executed sequentially
    is_multi_task: bool = False

    # Task breakdown for multi-task queries
    # Each task has: id, title, description, acceptance_criteria, priority, depends_on
    task_breakdown: Optional[List[Dict[str, Any]]] = None

    def __post_init__(self):
        if self.data_requirements is None:
            self.data_requirements = {}
        if self.prior_context is None:
            self.prior_context = {}
        if self.task_breakdown is None:
            self.task_breakdown = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "resolved_query": self.resolved_query,
            "user_purpose": self.user_purpose,
            "action_needed": self.action_needed,
            "data_requirements": self.data_requirements,
            "prior_context": self.prior_context,
            "mode": self.mode,
            "was_resolved": self.was_resolved,
            "reasoning": self.reasoning,
            "is_multi_task": self.is_multi_task,
            "task_breakdown": self.task_breakdown if self.task_breakdown else None,
        }
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
                resolved_query=data.get("resolved_query", ""),
                user_purpose=data.get("user_purpose", ""),
                action_needed=data.get("action_needed", "unclear"),
                data_requirements=data.get("data_requirements", {}),
                prior_context=data.get("prior_context", {}),
                mode=data.get("mode", "chat"),
                was_resolved=data.get("was_resolved", False),
                content_reference=content_ref,
                reasoning=data.get("reasoning", ""),
                is_multi_task=data.get("is_multi_task", False),
                task_breakdown=data.get("task_breakdown"),
            )

        except Exception as e:
            logger.warning(f"[QueryAnalyzer] Failed to load analysis from {json_path}: {e}")
            return None


class QueryAnalyzer:
    """
    Phase 0: Analyzes user queries before Context Gatherer.

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
        max_lookback: int = 1
    ):
        self.llm_client = llm_client
        self.turns_dir = turns_dir or Path("panda_system_docs/turns")
        self.max_lookback = max_lookback

    async def analyze(self, query: str, turn_number: int) -> QueryAnalysis:
        """
        Analyze the user query and resolve any references.

        Args:
            query: Raw user query
            turn_number: Current turn number

        Returns:
            QueryAnalysis with resolved query and context
        """
        logger.info(f"[QueryAnalyzer] Analyzing query for turn {turn_number}: '{query[:50]}...'")

        # Load recent turn summaries (may be empty for first turn)
        turn_summaries = self._load_recent_turns(turn_number)

        # NOTE: We still run the LLM even without previous turns!
        # Intent classification (navigation, commerce, etc.) is critical
        # and doesn't depend on having previous context.
        if not turn_summaries:
            logger.info("[QueryAnalyzer] No previous turns, will still classify intent")

        # Load prompt from recipe system
        try:
            recipe = load_recipe("pipeline/phase0_query_analyzer")
            prompt_template = recipe.get_prompt()
        except RecipeNotFoundError as e:
            logger.warning(f"[QueryAnalyzer] Recipe not found: {e}, returning query unchanged")
            return QueryAnalysis(
                resolved_query=query,
                was_resolved=False,
                user_purpose=f"User asked: {query}",
                action_needed="unclear",
                reasoning="Recipe not found, skipped analysis"
            )

        # Format turn summaries
        summaries_text = self._format_turn_summaries(turn_summaries)

        # Build full prompt by appending actual input data
        # The prompt template contains documentation and examples; we append the actual data
        prompt = prompt_template + f"\n\n---\n\n## Actual Input\n\n```\nQUERY: {query}\n\nRECENT TURNS:\n{summaries_text}\n```"

        try:
            response = await self.llm_client.call(
                prompt=prompt,
                role="query_analyzer",
                max_tokens=500,
                temperature=0.1
            )

            # Parse response
            analysis = self._parse_response(query, response)

            # Enrich with visit record info if there's a content reference
            if analysis.content_reference:
                analysis.content_reference = self._enrich_with_visit_record(
                    analysis.content_reference
                )
                # Also check extracted_links from previous turns' research.json
                if not analysis.content_reference.source_url:
                    analysis.content_reference = self._enrich_with_extracted_links(
                        analysis.content_reference, turn_number
                    )

            if analysis.was_resolved:
                logger.info(f"[QueryAnalyzer] Resolved: '{query[:30]}...' → '{analysis.resolved_query[:50]}...'")
            else:
                logger.info(f"[QueryAnalyzer] No resolution needed, action={analysis.action_needed}")

            if analysis.content_reference:
                logger.info(f"[QueryAnalyzer] Content reference: {analysis.content_reference.title[:50]}... ({analysis.content_reference.content_type})")

            return analysis

        except Exception as e:
            logger.error(f"[QueryAnalyzer] LLM call failed: {e}")
            return QueryAnalysis(
                resolved_query=query,
                was_resolved=False,
                user_purpose=f"User asked: {query}",
                action_needed="unclear",
                reasoning=f"Analysis failed: {str(e)}"
            )

    def _load_recent_turns(self, turn_number: int) -> List[Dict[str, Any]]:
        """Load summaries of recent turns."""
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

            # Extract brief response summary
            # Response may be in response.md OR in context.md section 5
            response_summary = ""
            if response_path.exists():
                try:
                    resp_content = response_path.read_text()
                    if "**Draft Response:**" in resp_content:
                        resp_section = resp_content.split("**Draft Response:**")[1]
                        response_summary = resp_section.strip()[:200]
                    else:
                        response_summary = resp_content.strip()[:200]
                except Exception:
                    pass

            # Fallback: extract from context.md section 5 if no response.md
            if not response_summary and "## 5. Synthesis" in content:
                try:
                    section5 = content.split("## 5. Synthesis")[1]
                    if "---" in section5:
                        section5 = section5.split("---")[0]
                    if "**Draft Response:**" in section5:
                        resp_section = section5.split("**Draft Response:**")[1]
                        response_summary = resp_section.strip()[:200]
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

            return {
                "turn": turn_number,
                "user_query": user_query,
                "topic": topic,
                "entities": entities,
                "response_summary": response_summary,
                "user_purpose": prior_user_purpose,  # Include prior purpose for context
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
            turn_label = f"Turn N-{summaries.index(s) + 1}" if summaries.index(s) == 0 else f"Turn N-{summaries.index(s) + 1}"
            lines.append(f"### {turn_label} (Turn {s['turn']})")
            lines.append(f"**User asked:** {s['user_query']}")
            if s.get('user_purpose'):
                lines.append(f"**Purpose:** {s['user_purpose'][:200]}...")  # Include purpose for context
            if s['topic']:
                lines.append(f"**Topic:** {s['topic']}")
            if s['entities']:
                lines.append(f"**Key entities:** {', '.join(s['entities'][:3])}")
            if s['response_summary']:
                lines.append(f"**Response:** {s['response_summary'][:150]}...")
            lines.append("")

        return "\n".join(lines)

    def _parse_response(self, original_query: str, response: str) -> QueryAnalysis:
        """Parse LLM response into QueryAnalysis with user_purpose."""
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                logger.warning("[QueryAnalyzer] No JSON found in response")
                return QueryAnalysis(
                    resolved_query=original_query,
                    user_purpose=f"User asked: {original_query}",
                    action_needed="unclear",
                    reasoning="Failed to parse response"
                )

            data = json.loads(json_match.group())

            # Extract content reference if present
            content_ref = None
            if data.get("content_reference"):
                ref_data = data["content_reference"]
                content_ref = ContentReference(
                    title=ref_data.get("title", ""),
                    content_type=ref_data.get("content_type", "unknown"),
                    site=ref_data.get("site"),
                    source_turn=ref_data.get("source_turn"),
                    prior_findings=ref_data.get("prior_findings"),
                    source_url=ref_data.get("source_url"),
                    has_visit_record=ref_data.get("has_visit_record", False),
                    visit_record_path=ref_data.get("visit_record_path")
                )

            # Extract and validate action_needed
            action_needed = data.get("action_needed", "unclear")
            valid_actions = {
                "live_search", "recall_memory", "answer_from_context",
                "navigate_to_site", "execute_code", "unclear"
            }
            if action_needed not in valid_actions:
                logger.warning(f"[QueryAnalyzer] Invalid action_needed '{action_needed}', defaulting to unclear")
                action_needed = "unclear"

            # Extract and validate mode
            mode = data.get("mode", "chat")
            valid_modes = {"chat", "code"}
            if mode not in valid_modes:
                logger.warning(f"[QueryAnalyzer] Invalid mode '{mode}', defaulting to chat")
                mode = "chat"

            # Extract multi-task detection
            is_multi_task = data.get("is_multi_task", False)
            task_breakdown = data.get("task_breakdown")

            # Validate task breakdown if present
            if is_multi_task and task_breakdown:
                validated_tasks = []
                for i, task in enumerate(task_breakdown):
                    validated_task = {
                        "id": task.get("id", f"TASK-{i+1:03d}"),
                        "title": task.get("title", f"Task {i+1}"),
                        "description": task.get("description", ""),
                        "acceptance_criteria": task.get("acceptance_criteria", []),
                        "priority": task.get("priority", i + 1),
                        "depends_on": task.get("depends_on", []),
                        "status": "pending",
                    }
                    validated_tasks.append(validated_task)
                task_breakdown = validated_tasks
                logger.info(f"[QueryAnalyzer] Multi-task detected: {len(task_breakdown)} tasks")
            else:
                task_breakdown = None

            return QueryAnalysis(
                resolved_query=data.get("resolved_query", original_query),
                user_purpose=data.get("user_purpose", ""),
                action_needed=action_needed,
                data_requirements=data.get("data_requirements", {}),
                prior_context=data.get("prior_context", {}),
                mode=mode,
                was_resolved=data.get("was_resolved", False),
                content_reference=content_ref,
                reasoning=data.get("reasoning", ""),
                is_multi_task=is_multi_task,
                task_breakdown=task_breakdown,
            )

        except json.JSONDecodeError as e:
            logger.warning(f"[QueryAnalyzer] JSON parse error: {e}")
            return QueryAnalysis(
                resolved_query=original_query,
                user_purpose=f"User asked: {original_query}",
                action_needed="unclear",
                reasoning=f"JSON parse error: {str(e)}"
            )


async def analyze_query(
    query: str,
    turn_number: int,
    llm_client: Any,
    turns_dir: Path = None
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
    return await analyzer.analyze(query, turn_number)
