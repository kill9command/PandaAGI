"""
TurnSaver: Saves all turn documents without summarization.

This module replaces the old Summarizer role. Instead of compressing the turn
into a summary, we save all documents as-is and let the Context Gatherer
summarize at retrieval time.

Responsibilities:
- Save context.md, response.md, ticket.md, toolresults.md
- Generate and save metadata.json
- Index the turn for search
- Update persistent memory (preferences, facts) when needed
- Record turn outcome for learning via turn index

ARCHITECTURAL DECISION (2025-12-30):
Removed LEARN decision and async lesson extraction. Learning now happens
implicitly via turn indexing - the turn index serves as the knowledge base
for retrieval and learning.
"""

import json
import re
import os
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

from libs.gateway.context.context_document import ContextDocument, TurnMetadata, extract_keywords
from libs.gateway.persistence.turn_search_index import TurnSearchIndex

# Optional import for scope promotion (#71)
try:
    from libs.gateway.research.research_index_db import get_research_index_db
    RESEARCH_INDEX_AVAILABLE = True
except ImportError:
    RESEARCH_INDEX_AVAILABLE = False
    get_research_index_db = None

# Import turn index for freshness degradation
try:
    from .turn_index_db import get_turn_index_db
    TURN_INDEX_AVAILABLE = True
except ImportError:
    TURN_INDEX_AVAILABLE = False
    get_turn_index_db = None

# Import recipe loader and LLM client for freshness analysis
try:
    from libs.gateway.llm.recipe_loader import load_recipe
    from libs.gateway.context.doc_pack_builder import DocPackBuilder
    from libs.llm.llm_client import get_llm_client
    FRESHNESS_ANALYZER_AVAILABLE = True
except ImportError:
    FRESHNESS_ANALYZER_AVAILABLE = False
    load_recipe = None
    DocPackBuilder = None
    get_llm_client = None

# Import forever memory (obsidian_memory) with graceful fallback
try:
    from apps.tools.memory import write_memory, update_preference, format_research_content, format_product_content
    FOREVER_MEMORY_AVAILABLE = True
except ImportError:
    FOREVER_MEMORY_AVAILABLE = False
    write_memory = None
    update_preference = None
    format_research_content = None
    format_product_content = None

logger = logging.getLogger(__name__)


class LinkFormatter:
    """
    Generate dual-style links for Obsidian integration.

    Per panda_system_docs/architecture/DOCUMENT-IO-SYSTEM/obsidian-integration.md:
    - Relative markdown links for LLMs and programmatic access
    - Obsidian wikilinks for human navigation and graph view
    """

    def __init__(self, vault_root: Path = Path("panda_system_docs")):
        self.vault_root = vault_root

    def dual_link(self, from_file: Path, to_file: Path, label: str) -> str:
        """Generate both link styles from one call."""
        # Relative markdown link (for LLMs and programmatic access)
        rel_path = os.path.relpath(to_file, from_file.parent)
        md_link = f"[{label}]({rel_path})"

        # Obsidian wikilink (for human navigation)
        try:
            vault_path = to_file.relative_to(self.vault_root)
            wiki_link = f"[[{vault_path.with_suffix('')}|{label}]]"
        except ValueError:
            # to_file is not under vault_root, use absolute path
            wiki_link = f"[[{to_file.with_suffix('')}|{label}]]"

        return f"{md_link} | {wiki_link}"


class TurnSaver:
    """
    Saves all turn documents without summarization.

    Usage:
        saver = TurnSaver()
        await saver.save_turn(
            context_doc=context_doc,
            response="Your favorite hamster is Syrian.",
            ticket_content=ticket_md,  # Optional
            toolresults_content=toolresults_md  # Optional
        )
    """

    def __init__(
        self,
        turns_dir: Path = None,
        sessions_dir: Path = None,
        memory_dir: Path = None,
        user_id: str = None
    ):
        self.user_id = user_id or "default"
        # Use new consolidated path structure under obsidian_memory/Users/
        self.turns_dir = turns_dir or Path(f"panda_system_docs/obsidian_memory/Users/{self.user_id}/turns")
        self.sessions_dir = sessions_dir or Path(f"panda_system_docs/obsidian_memory/Users/{self.user_id}/sessions")
        self.memory_dir = memory_dir or Path(f"panda_system_docs/obsidian_memory/Users/{self.user_id}/memory")

    async def save_turn(
        self,
        context_doc: ContextDocument,
        response: str,
        ticket_content: Optional[str] = None,
        toolresults_content: Optional[str] = None,
        response_quality: float = 0.8,
        validation_result: Optional[Dict[str, Any]] = None
    ) -> Path:
        """
        Save all turn documents.

        Args:
            context_doc: The accumulated context document
            response: The final response to user
            ticket_content: Optional ticket.md content
            toolresults_content: Optional toolresults.md content
            response_quality: Quality score for the response
            validation_result: Optional validation output with learning metadata

        Returns:
            Path to the turn directory
        """
        turn_number = context_doc.turn_number
        session_id = context_doc.session_id

        # Create turn directory
        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        turn_dir.mkdir(parents=True, exist_ok=True)

        # Save context.md (includes §0 query)
        context_doc.save(turn_dir)
        logger.info(f"Saved context.md to {turn_dir}")

        # Append Related Documents section to context.md (Obsidian integration)
        self._append_related_documents(turn_dir, turn_number)

        # Save response.md
        (turn_dir / "response.md").write_text(response)

        # Save optional documents
        if ticket_content:
            (turn_dir / "ticket.md").write_text(ticket_content)

        if toolresults_content:
            (turn_dir / "toolresults.md").write_text(toolresults_content)

        # Generate and save metadata (include learning data)
        metadata = self._generate_metadata(
            context_doc,
            response,
            response_quality,
            validation_result,
            toolresults_content=toolresults_content
        )
        metadata.save(turn_dir)

        # Index for search (include user_id for per-user isolation)
        # Try to get user_id from context_doc if not set on self
        user_id = getattr(context_doc, 'user_id', None) or self.user_id
        search_index = TurnSearchIndex(session_id, user_id=user_id)
        search_index.index_turn(turn_dir, metadata)

        # Check scope promotion for used research (#71 from IMPLEMENTATION_ROADMAP.md)
        if validation_result and validation_result.get("decision") == "APPROVE":
            await self._check_scope_promotions(context_doc)

        # Update persistent memory if needed
        await self._update_persistent_memory(context_doc, response)

        # Schedule forever memory save as background task (non-blocking)
        # This runs AFTER the response is sent to the user
        self.schedule_memory_save(
            context_doc, response, metadata, validation_result, turn_dir
        )

        # Schedule freshness analysis (background task - detects stale data)
        # This compares new findings with prior turns and downgrades outdated info
        self.schedule_freshness_analysis(context_doc, validation_result, turn_dir)

        # Schedule turn summary generation (background task - appends to context.md)
        self.schedule_turn_summary(context_doc, turn_dir)

        # Self-learning: Record outcome and trigger extraction if LEARN
        await self._process_learning(
            context_doc, metadata, validation_result, turn_dir
        )

        logger.info(f"Turn {turn_number} saved to {turn_dir}")
        return turn_dir

    def save_metrics(
        self,
        turn_dir: Path,
        metrics: Dict[str, Any]
    ) -> Path:
        """
        Save turn metrics to metrics.json.

        Args:
            turn_dir: Path to the turn directory
            metrics: Dictionary containing:
                - turn_start: Unix timestamp
                - turn_end: Unix timestamp
                - total_duration_ms: Total turn duration
                - phases: Dict of phase_name -> {duration_ms, tokens_in, tokens_out}
                - tokens: {total_in, total_out}
                - decisions: List of {type, value, context}
                - tools_called: List of {tool, success, duration_ms}
                - retries: Number of retry attempts
                - quality_score: Final quality score
                - validation_outcome: APPROVE/RETRY/REVISE/FAIL

        Returns:
            Path to the metrics.json file
        """
        metrics_path = turn_dir / "metrics.json"

        # Add workflow stats
        workflow_stats = self._extract_workflow_metrics(metrics.get("tools_called", []), metrics)
        if workflow_stats:
            metrics["workflows"] = workflow_stats

        # Add summary stats
        metrics["summary"] = {
            "total_duration_ms": metrics.get("total_duration_ms", 0),
            "total_tokens_in": metrics.get("tokens", {}).get("total_in", 0),
            "total_tokens_out": metrics.get("tokens", {}).get("total_out", 0),
            "phase_count": len(metrics.get("phases", {})),
            "tool_count": len(metrics.get("tools_called", [])),
            "decision_count": len(metrics.get("decisions", [])),
            "success_rate": self._calculate_tool_success_rate(metrics.get("tools_called", []))
        }

        with open(metrics_path, 'w') as f:
            json.dump(metrics, f, indent=2, default=str)

        logger.info(f"Saved metrics.json to {metrics_path}")
        return metrics_path

    def _extract_workflow_metrics(
        self,
        tools_called: List[Dict[str, Any]],
        metrics: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Aggregate workflow stats from tool call records."""
        workflows: Dict[str, Dict[str, Any]] = {}

        for call in tools_called or []:
            tool_name = call.get("tool", "")
            if not tool_name.startswith("workflow:"):
                continue
            workflow_name = tool_name.split("workflow:", 1)[-1]
            if not workflow_name:
                continue

            entry = workflows.setdefault(
                workflow_name,
                {
                    "workflow": workflow_name,
                    "duration_ms": 0,
                    "success": True,
                    "claims_extracted": 0,
                    "tool_runs": 0
                }
            )
            entry["duration_ms"] += int(call.get("duration_ms", 0) or 0)
            entry["tool_runs"] += 1
            if call.get("success") is False:
                entry["success"] = False

        if workflows:
            total_claims = metrics.get("claims_count", 0)
            if total_claims and len(workflows) == 1:
                only = next(iter(workflows.values()))
                only["claims_extracted"] = total_claims

        return list(workflows.values())

    def _calculate_tool_success_rate(self, tools_called: List[Dict]) -> float:
        """Calculate tool success rate from tool call records."""
        if not tools_called:
            return 1.0
        successes = sum(1 for t in tools_called if t.get("success", True))
        return successes / len(tools_called)

    def _generate_metadata(
        self,
        context_doc: ContextDocument,
        response: str,
        response_quality: float,
        validation_result: Optional[Dict[str, Any]] = None,
        toolresults_content: Optional[str] = None
    ) -> TurnMetadata:
        """
        Generate metadata for the turn, including learning data.

        Learning fields (per MEMORY_ARCHITECTURE.md and phase7-send-and-save.md):
        - validation_outcome: APPROVE, RETRY, REVISE, FAIL (from validation_result)
        - quality_score: 0.0-1.0 (from validation_result confidence)
        - strategy_summary: What plan was used (from section 3)
        """
        # Extract topic from query or task plan
        topic = self._extract_topic(context_doc)

        # Extract action_needed from §0 for legacy intent mapping
        action_needed = self._extract_action_needed(context_doc)

        # Extract workflows used from execution logs
        workflows_used = self._extract_workflows_used(
            context_doc, toolresults_content=toolresults_content
        )

        # Extract content type for decay/quality selection
        content_type = self._extract_content_type(context_doc)

        # Extract keywords from query and response
        combined_text = f"{context_doc.query} {response}"
        keywords = extract_keywords(combined_text, max_keywords=10)

        # Extract learning fields
        validation_outcome = ""
        quality_score = response_quality  # Default to response_quality
        if validation_result:
            validation_outcome = validation_result.get("decision", "")
            # Use validation confidence as quality_score if available
            if "confidence" in validation_result:
                quality_score = validation_result.get("confidence", response_quality)

        # Extract strategy summary from section 3 (task plan)
        strategy_summary = self._extract_strategy_summary(context_doc)

        metadata = TurnMetadata(
            turn_number=context_doc.turn_number,
            session_id=context_doc.session_id,
            timestamp=datetime.now().timestamp(),
            topic=topic,
            action_needed=action_needed,
            workflows_used=workflows_used,
            content_type=content_type,
            claims_count=len(context_doc.claims),
            response_quality=response_quality,
            keywords=keywords,
            # Learning fields for TurnIndexDB
            validation_outcome=validation_outcome,
            quality_score=quality_score,
            strategy_summary=strategy_summary
        )

        # Add legacy learning metadata if available (for backward compatibility)
        if validation_result:
            learning = validation_result.get("learning") or {}
            metadata.learning = {
                "validation_decision": validation_result.get("decision", "APPROVE"),
                "revision_count": learning.get("revision_count", 0),
                "strategy_applied": learning.get("strategy_applied"),
                "lesson_consulted": learning.get("lesson_consulted"),
                "pattern_detected": learning.get("pattern_detected"),
            }

        return metadata

    def _extract_topic(self, context_doc: ContextDocument) -> str:
        """Extract topic from the context document."""
        # Try to get from task plan section
        task_plan = context_doc.get_section(3)
        if task_plan:
            # Look for "**Goal:**" line
            for line in task_plan.split("\n"):
                if line.startswith("**Goal:**"):
                    return line.replace("**Goal:**", "").strip()

        # Fallback: first few words of query
        query_words = context_doc.query.split()[:5]
        return " ".join(query_words)

    def _extract_action_needed(self, context_doc: ContextDocument) -> str:
        """
        Extract action_needed from the context document.

        Primary source: §0 query analysis action_needed + data_requirements (Phase 0)
        Maps to legacy intent values for turn index compatibility.
        Fallback: task plan section (legacy)
        """
        # PRIMARY: Get action_needed from §0 query analysis (the canonical source)
        action_needed = context_doc.get_action_needed()
        data_requirements = context_doc.get_data_requirements()

        # Map action_needed + data_requirements to legacy intent for storage
        if data_requirements.get("needs_current_prices"):
            return "commerce"
        elif action_needed == "navigate_to_site":
            return "navigation"
        elif action_needed == "recall_memory":
            return "recall"
        elif action_needed == "live_search":
            return "informational"
        elif action_needed != "unclear":
            return action_needed

        # FALLBACK: Legacy - look in §3 task plan for "**Intent:**" line
        task_plan = context_doc.get_section(3)
        if task_plan:
            for line in task_plan.split("\n"):
                if line.startswith("**Intent:**"):
                    return line.replace("**Intent:**", "").strip()

        return "unknown"

    def _extract_workflows_used(
        self,
        context_doc: ContextDocument,
        toolresults_content: Optional[str] = None
    ) -> List[str]:
        """Extract workflows used from execution context and tool results."""
        workflows = set()

        if context_doc.workflow:
            workflows.add(context_doc.workflow)

        tool_execution = context_doc.get_section(4) or ""
        for match in re.findall(r'workflow:([A-Za-z0-9_\-]+)', tool_execution):
            workflows.add(match)

        if toolresults_content:
            for match in re.findall(r'workflow:([A-Za-z0-9_\-]+)', toolresults_content):
                workflows.add(match)
            for match in re.findall(r'"workflow_selected"\s*:\s*"([^"]+)"', toolresults_content):
                workflows.add(match)

        return sorted(workflows)

    def _extract_content_type(self, context_doc: ContextDocument) -> str:
        """Extract content type for decay/quality selection."""
        data_reqs = context_doc.get_data_requirements() if hasattr(context_doc, "get_data_requirements") else {}
        if data_reqs.get("needs_current_prices"):
            return "price"
        if data_reqs.get("needs_live_data"):
            return "live_data"

        if context_doc.query_analysis:
            content_ref = context_doc.query_analysis.get("content_reference") or {}
            content_type = content_ref.get("content_type")
            if content_type:
                return content_type

        return "general"

    def _extract_strategy_summary(self, context_doc: ContextDocument) -> str:
        """
        Extract strategy summary from section 3 (task plan).

        Per MEMORY_ARCHITECTURE.md, strategy_summary captures the approach used
        for this turn, enabling learning from past successful strategies.

        Looks for:
        - Route To line (coordinator vs synthesis)
        - Strategy Applied section
        - Research Type
        - Goal + Intent combination as fallback
        """
        task_plan = context_doc.get_section(3)
        if not task_plan:
            return ""

        parts = []

        # Extract route
        for line in task_plan.split("\n"):
            if line.startswith("**Route To:**"):
                route = line.replace("**Route To:**", "").strip()
                parts.append(f"route:{route}")
                break

        # Extract research type if present
        for line in task_plan.split("\n"):
            if "research_type" in line.lower() or line.startswith("**Research Type:**"):
                # Try to extract value
                if ":" in line:
                    value = line.split(":", 1)[1].strip().strip('"').strip("'")
                    if value:
                        parts.append(f"research:{value}")
                break

        # Extract goal (brief summary of what was planned)
        goal = self._extract_topic(context_doc)
        if goal:
            # Truncate to reasonable length for summary
            if len(goal) > 50:
                goal = goal[:47] + "..."
            parts.append(f"goal:{goal}")

        # Join parts into strategy summary
        return "; ".join(parts) if parts else ""

    async def _check_scope_promotions(self, context_doc: ContextDocument):
        """
        Check if any research used in this turn should be promoted to higher scope.

        Implements #71 from IMPLEMENTATION_ROADMAP.md:
        - After successful validation (APPROVE), check research used in turn
        - If promotion criteria met (usage_count, quality, age), promote scope
        - session → user (3+ uses, 0.70+ quality, 1h+ age)
        - user → global (10+ uses, 0.85+ quality, 24h+ age)
        """
        if not RESEARCH_INDEX_AVAILABLE:
            return

        try:
            research_index = get_research_index_db()

            # Find research paths from source_references
            for ref in context_doc.source_references:
                path = ref.path
                if not path or 'research' not in path.lower():
                    continue

                # Try to find matching research entry by path
                # The research_index stores doc_path, so we search by that
                results = research_index.search(
                    query="",  # Not using semantic search
                    session_id=context_doc.session_id,
                    k=50  # Get enough to find matching path
                )

                for entry in results:
                    if entry.get("doc_path") and path in entry.get("doc_path", ""):
                        research_id = entry.get("id")
                        if research_id:
                            # Increment usage count
                            research_index.increment_usage(research_id)

                            # Check if promotion warranted
                            new_scope = research_index.check_promotion(research_id)
                            if new_scope:
                                research_index.promote(research_id, new_scope)
                                logger.info(f"[TurnSaver] Promoted research {research_id} to {new_scope}")
                        break

        except Exception as e:
            logger.debug(f"[TurnSaver] Scope promotion check failed: {e}")

    async def _update_persistent_memory(
        self,
        context_doc: ContextDocument,
        response: str
    ):
        """
        Update persistent memory based on the turn.

        Detects:
        - Preference statements ("my favorite X is Y")
        - Fact statements ("remember that I...")
        - Intent = "preference"
        """
        session_dir = self.sessions_dir / context_doc.session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        query = context_doc.query.lower()
        action_needed = self._extract_action_needed(context_doc)

        # Detect preference statements
        preferences_to_save = []

        # Check for "my favorite X is Y" pattern
        favorite_match = re.search(
            r'my favorite\s+(\w+)\s+is\s+(?:the\s+)?(.+?)(?:\.|$)',
            query,
            re.IGNORECASE
        )
        if favorite_match:
            key = f"favorite_{favorite_match.group(1)}"
            value = favorite_match.group(2).strip()
            preferences_to_save.append((key, value))

        # Check for "I prefer X" pattern
        prefer_match = re.search(
            r'i prefer\s+(.+?)(?:\.|$)',
            query,
            re.IGNORECASE
        )
        if prefer_match:
            preferences_to_save.append(("preference", prefer_match.group(1).strip()))

        # Check for recall_memory action (previously "preference" intent)
        if action_needed == "recall_memory" and not preferences_to_save:
            # Try to extract from query
            preferences_to_save.append(("stated_preference", query))

        # Save preferences
        if preferences_to_save:
            await self._append_preferences(session_dir, preferences_to_save)

        # Detect fact statements ("remember that...")
        remember_match = re.search(
            r'remember\s+(?:that\s+)?(.+?)(?:\.|$)',
            query,
            re.IGNORECASE
        )
        if remember_match:
            fact = remember_match.group(1).strip()
            await self._append_fact(session_dir, fact)

    async def _append_preferences(
        self,
        session_dir: Path,
        preferences: List[tuple]
    ):
        """Append preferences to preferences.md."""
        prefs_file = session_dir / "preferences.md"

        # Load existing content
        existing_content = ""
        if prefs_file.exists():
            existing_content = prefs_file.read_text()

        # Parse existing preferences
        existing_prefs = {}
        for line in existing_content.split("\n"):
            if line.startswith("- **") and ":**" in line:
                parts = line.split(":**", 1)
                if len(parts) == 2:
                    key = parts[0].replace("- **", "").strip()
                    existing_prefs[key] = parts[1].strip()

        # Update with new preferences
        for key, value in preferences:
            existing_prefs[key] = value

        # Write back
        lines = ["# User Preferences", "", "## General", ""]
        for key, value in existing_prefs.items():
            lines.append(f"- **{key}:** {value}")

        lines.extend(["", "---", "", "*Updated automatically by turn saver*", ""])
        prefs_file.write_text("\n".join(lines))

        logger.info(f"Updated preferences: {dict(preferences)}")

    async def _append_fact(self, session_dir: Path, fact: str):
        """Append a fact to facts.md."""
        facts_file = session_dir / "facts.md"

        # Load existing content
        existing_facts = []
        if facts_file.exists():
            content = facts_file.read_text()
            for line in content.split("\n"):
                if line.strip().startswith("- "):
                    existing_facts.append(line.strip()[2:])

        # Add new fact if not duplicate
        if fact not in existing_facts:
            existing_facts.append(fact)

        # Write back
        lines = ["# User Facts", "", "## Remembered Facts", ""]
        for f in existing_facts:
            lines.append(f"- {f}")

        lines.extend(["", "---", "", "*Updated automatically by turn saver*", ""])
        facts_file.write_text("\n".join(lines))

        logger.info(f"Added fact: {fact}")

    def schedule_memory_save(
        self,
        context_doc: ContextDocument,
        response: str,
        metadata: TurnMetadata,
        validation_result: Optional[Dict[str, Any]],
        turn_dir: Path
    ):
        """
        Schedule memory save as a background task (non-blocking).

        This is called after the response is sent to the user, so memory
        operations don't slow down the response.
        """
        if not FOREVER_MEMORY_AVAILABLE:
            return

        import asyncio
        asyncio.create_task(
            self._save_to_forever_memory_background(
                context_doc, response, metadata, validation_result, turn_dir
            )
        )
        logger.debug("[TurnSaver] Scheduled background memory save")

    async def _save_to_forever_memory_background(
        self,
        context_doc: ContextDocument,
        response: str,
        metadata: TurnMetadata,
        validation_result: Optional[Dict[str, Any]],
        turn_dir: Path
    ):
        """
        Background task to save knowledge to forever memory.

        Quality filters applied:
        1. Validation must be APPROVE (not RETRY, REVISE, FAIL)
        2. Confidence must be >= 0.7
        3. Must have substantial content (not empty findings)
        4. Duplicate detection handled by write_memory (merges, doesn't duplicate)
        """
        try:
            await self._save_to_forever_memory(
                context_doc, response, metadata, validation_result, turn_dir
            )
        except Exception as e:
            # Background task - log but don't raise
            logger.error(f"[TurnSaver] Background memory save failed: {e}")

    async def _save_to_forever_memory(
        self,
        context_doc: ContextDocument,
        response: str,
        metadata: TurnMetadata,
        validation_result: Optional[Dict[str, Any]],
        turn_dir: Path
    ):
        """
        Save knowledge to forever memory (obsidian_memory).

        Per architecture/services/OBSIDIAN_MEMORY.md:
        - Research findings → /Knowledge/Research/
        - Product info → /Knowledge/Products/
        - User preferences → /Preferences/User/

        Quality filters:
        - Only APPROVED turns (not RETRY, REVISE, FAIL)
        - Confidence >= 0.7
        - Must have substantial content
        """
        if not FOREVER_MEMORY_AVAILABLE:
            return

        # QUALITY FILTER 1: Only save for APPROVED turns
        if validation_result:
            decision = validation_result.get("decision", "APPROVE")
            if decision != "APPROVE":
                logger.debug(f"[TurnSaver] Skipping memory save (validation={decision}, need APPROVE)")
                return

        # QUALITY FILTER 2: Check confidence threshold
        confidence = metadata.quality_score if metadata else 0.5
        MIN_CONFIDENCE = 0.7
        if confidence < MIN_CONFIDENCE:
            logger.debug(f"[TurnSaver] Skipping memory save (confidence={confidence:.2f} < {MIN_CONFIDENCE})")
            return

        # Check if this is a memorable turn
        if not self._is_memorable_turn(context_doc, metadata):
            return

        saved_count = 0

        try:
            # Extract research findings
            research_content = self._extract_research_for_memory(context_doc, turn_dir)
            if research_content:
                # QUALITY FILTER 3: Must have substantial content
                findings = research_content.get("findings", "")
                summary = research_content.get("summary", "")
                if len(findings) < 50 and len(summary) < 50:
                    logger.debug("[TurnSaver] Skipping research save (insufficient content)")
                else:
                    topic = research_content.get("topic", "research")
                    await write_memory(
                        artifact_type="research",
                        topic=topic,
                        content=research_content,
                        tags=research_content.get("tags", []),
                        source_urls=research_content.get("source_urls", []),
                        confidence=confidence,
                    )
                    logger.info(f"[TurnSaver] Saved research to memory: {topic} (confidence={confidence:.2f})")
                    saved_count += 1

            # Extract product knowledge
            products = self._extract_products_for_memory(context_doc, turn_dir)
            for product in products:
                # QUALITY FILTER 3: Must have product name
                product_name = product.get("product_name", "")
                if not product_name or product_name == "unknown":
                    logger.debug("[TurnSaver] Skipping product save (no product name)")
                    continue

                await write_memory(
                    artifact_type="product",
                    topic=product_name,
                    content=product,
                    tags=product.get("tags", []),
                    confidence=product.get("confidence", confidence),
                )
                logger.info(f"[TurnSaver] Saved product to memory: {product_name}")
                saved_count += 1

            # Extract and save user preferences (always save if detected)
            preferences = self._extract_preferences_for_memory(context_doc, response)
            for key, value, category in preferences:
                await update_preference(
                    key=key,
                    value=value,
                    category=category,
                    source_turn=context_doc.turn_number,
                )
                logger.info(f"[TurnSaver] Saved preference: {key}={value}")
                saved_count += 1

            if saved_count > 0:
                logger.info(f"[TurnSaver] Background memory save complete: {saved_count} items saved")

        except Exception as e:
            logger.warning(f"[TurnSaver] Failed to save to forever memory: {e}")

    def _is_memorable_turn(
        self,
        context_doc: ContextDocument,
        metadata: TurnMetadata
    ) -> bool:
        """Determine if this turn should be saved to forever memory."""
        # Check action_needed (mapped to legacy intent values by _extract_action_needed)
        action = metadata.action_needed if metadata else self._extract_action_needed(context_doc)
        memorable_intents = {"transactional", "informational", "research", "commerce"}

        if action in memorable_intents:
            return True

        # Check if research was performed (has research.md or research.json)
        turn_dir = self.turns_dir / f"turn_{context_doc.turn_number:06d}"
        if (turn_dir / "research.md").exists() or (turn_dir / "research.json").exists():
            return True

        # Check if products were mentioned in response
        if "| Product |" in (context_doc.get_section(4) or ""):
            return True

        return False

    def _extract_research_for_memory(
        self,
        context_doc: ContextDocument,
        turn_dir: Path
    ) -> Optional[Dict[str, Any]]:
        """Extract research findings for saving to forever memory."""
        # Check for research.json first (structured data)
        research_json_path = turn_dir / "research.json"
        if research_json_path.exists():
            try:
                with open(research_json_path) as f:
                    data = json.load(f)

                topic = data.get("topic", {})
                if isinstance(topic, dict):
                    topic_name = topic.get("primary_topic", "research")
                else:
                    topic_name = str(topic) if topic else "research"

                # Build findings with intelligence summary AND product listings with URLs
                findings_parts = []

                # Add intelligence summary if available
                intel_summary = data.get("intelligence", {}).get("summary", "")
                if intel_summary:
                    findings_parts.append(intel_summary)

                # Add product listings with URLs (critical for forever memory)
                listings = data.get("listings", [])
                if listings:
                    findings_parts.append("\n### Product Listings\n")
                    for listing in listings[:10]:  # Limit to 10 products
                        name = listing.get("name", "Unknown")
                        price = listing.get("price", "N/A")
                        vendor = listing.get("vendor", "unknown")
                        url = listing.get("url", "")
                        if url:
                            findings_parts.append(f"- **{name}** - {price} at {vendor}\n  URL: {url}")
                        else:
                            findings_parts.append(f"- **{name}** - {price} at {vendor}")

                findings_content = "\n".join(findings_parts)

                return {
                    "topic": topic_name,
                    "subtopic": data.get("topic", {}).get("subtopic", "") if isinstance(data.get("topic"), dict) else "",
                    "summary": data.get("summary", ""),
                    "findings": findings_content,
                    "source_urls": data.get("visited_urls", []),
                    "tags": self._extract_tags_from_content(data),
                    "source": "internet_research",
                }
            except Exception as e:
                logger.debug(f"[TurnSaver] Failed to parse research.json: {e}")

        # Fall back to research.md
        research_md_path = turn_dir / "research.md"
        if research_md_path.exists():
            try:
                content = research_md_path.read_text()
                topic = self._extract_topic(context_doc)

                # Extract summary from markdown
                summary = ""
                if "## Summary" in content:
                    summary_section = content.split("## Summary")[1]
                    if "##" in summary_section:
                        summary_section = summary_section.split("##")[0]
                    summary = summary_section.strip()[:500]

                return {
                    "topic": topic,
                    "summary": summary,
                    "findings": content[:2000],  # First 2000 chars
                    "tags": self._extract_tags_from_query(context_doc.query),
                    "source": "internet_research",
                }
            except Exception as e:
                logger.debug(f"[TurnSaver] Failed to parse research.md: {e}")

        return None

    def _extract_products_for_memory(
        self,
        context_doc: ContextDocument,
        turn_dir: Path
    ) -> List[Dict[str, Any]]:
        """Extract product knowledge for saving to forever memory."""
        products = []

        # Check tool execution section (§4) for product tables
        tool_section = context_doc.get_section(4)
        if not tool_section:
            return products

        # Parse product table rows
        in_table = False
        for line in tool_section.split("\n"):
            if line.startswith("| Product ") or line.startswith("|---"):
                in_table = True
                continue

            if in_table and line.startswith("|"):
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 3:
                    product_name = parts[0]
                    price = parts[1] if len(parts) > 1 else ""
                    vendor = parts[-1] if len(parts) > 2 else ""

                    # Skip header-like rows
                    if product_name.lower() in ("product", "name", "---"):
                        continue

                    products.append({
                        "product_name": product_name,
                        "category": self._extract_topic(context_doc),
                        "overview": f"Found in research for: {context_doc.query[:100]}",
                        "prices": [{"price": price, "vendor": vendor, "date": datetime.now().strftime("%Y-%m-%d")}],
                        "tags": self._extract_tags_from_query(context_doc.query),
                        "confidence": 0.8,
                    })

            elif in_table and not line.startswith("|"):
                in_table = False

        return products[:5]  # Limit to 5 products

    def _extract_preferences_for_memory(
        self,
        context_doc: ContextDocument,
        response: str
    ) -> List[tuple]:
        """Extract user preferences for saving to forever memory."""
        preferences = []
        query = context_doc.query.lower()

        # Budget preference patterns
        budget_patterns = [
            (r'budget(?:\s+is)?[\s:]+\$?([\d,]+)', 'max_budget'),
            (r'under\s+\$?([\d,]+)', 'max_budget'),
            (r'around\s+\$?([\d,]+)', 'target_budget'),
            (r'cheap(?:est)?|budget|affordable', 'price_sensitivity'),
        ]

        for pattern, key in budget_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                value = match.group(1) if match.lastindex else "high"
                if key == "price_sensitivity":
                    value = "high"
                preferences.append((key, value, "budget"))
                break

        # Brand preference patterns (from user choices in conversation)
        if "prefer" in query or "like" in query or "favorite" in query:
            brand_match = re.search(r'(?:prefer|like|favorite)\s+(\w+)', query, re.IGNORECASE)
            if brand_match:
                brand = brand_match.group(1)
                # Filter out common non-brand words
                if brand.lower() not in ("the", "a", "an", "this", "that", "something", "it"):
                    preferences.append((f"liked_brand", brand, "brand"))

        return preferences

    def _extract_tags_from_content(self, data: Dict[str, Any]) -> List[str]:
        """Extract tags from research data structure."""
        tags = []

        # Get from topic
        topic = data.get("topic", {})
        if isinstance(topic, dict):
            primary = topic.get("primary_topic", "")
            if primary:
                tags.append(primary.lower().replace(" ", "-"))

        # Get from keywords
        intelligence = data.get("intelligence", {})
        keywords = intelligence.get("keywords", [])
        tags.extend([k.lower().replace(" ", "-") for k in keywords[:5]])

        return list(set(tags))[:10]

    def _extract_tags_from_query(self, query: str) -> List[str]:
        """Extract tags from a query string."""
        # Remove common words
        stop_words = {"the", "a", "an", "is", "are", "for", "to", "and", "or", "of", "in", "on", "with", "best", "find", "me", "get", "buy", "want", "need", "looking"}

        words = re.findall(r'\b\w+\b', query.lower())
        tags = [w for w in words if w not in stop_words and len(w) > 2]

        return list(set(tags))[:10]

    async def _process_learning(
        self,
        context_doc: ContextDocument,
        metadata: TurnMetadata,
        validation_result: Optional[Dict[str, Any]],
        turn_dir: Path
    ):
        """
        Record turn outcome for analytics.

        ARCHITECTURAL DECISION (2025-12-30):
        Removed LEARN decision and async lesson extraction. Learning now happens
        implicitly via turn indexing.
        """
        if not validation_result:
            return

        decision = validation_result.get("decision", "APPROVE")

        # Import here to avoid circular imports
        try:
            from libs.gateway.util.performance_tracker import get_performance_tracker, TurnOutcome
        except ImportError as e:
            logger.warning(f"Performance tracker not available: {e}")
            return

        # Record turn outcome for analytics
        tracker = get_performance_tracker()
        import time

        outcome = TurnOutcome(
            turn_number=context_doc.turn_number,
            session_id=context_doc.session_id,
            timestamp=time.time(),
            action_needed=metadata.action_needed,
            context_tokens=self._estimate_context_tokens(context_doc),
            strategy_applied=None,  # Legacy field
            lesson_consulted=None,  # Legacy field
            validation_decision=decision,
            revision_count=0,
            pattern_detected=None,  # Legacy field
        )
        tracker.record_outcome(outcome)

        logger.debug(
            f"[TurnSaver] Recorded outcome: turn={context_doc.turn_number}, "
            f"decision={decision}"
        )

    def _estimate_context_tokens(self, context_doc: ContextDocument) -> int:
        """Estimate token count in context document."""
        # Rough estimate: 4 chars per token
        total_chars = len(context_doc.query)

        for section_num in range(7):  # §0 through §6
            content = context_doc.get_section(section_num)
            if content:
                total_chars += len(content)

        return total_chars // 4

    def _append_related_documents(self, turn_dir: Path, turn_number: int) -> None:
        """
        Append Related Documents section to context.md for Obsidian integration.

        Per panda_system_docs/architecture/DOCUMENT-IO-SYSTEM/obsidian-integration.md:
        - Generates dual links (markdown + wikilink) for each related document
        - Only includes links to files that actually exist
        - Links to: research.md, metrics.json, previous turn context.md

        This section enables:
        - Human navigation in Obsidian (graph view, backlinks)
        - LLM navigation (Context Gatherer can follow links)
        """
        context_path = turn_dir / "context.md"
        if not context_path.exists():
            logger.warning(f"context.md not found at {context_path}, skipping Related Documents")
            return

        formatter = LinkFormatter(vault_root=Path("panda_system_docs"))
        links = []

        # Check for research.md
        research_path = turn_dir / "research.md"
        if research_path.exists():
            link = formatter.dual_link(context_path, research_path, "Research")
            links.append(f"- {link}")

        # Check for metrics.json
        metrics_path = turn_dir / "metrics.json"
        if metrics_path.exists():
            link = formatter.dual_link(context_path, metrics_path, "Metrics")
            links.append(f"- {link}")

        # Check for previous turn context.md
        if turn_number > 1:
            prev_turn_dir = self.turns_dir / f"turn_{turn_number - 1:06d}"
            prev_context_path = prev_turn_dir / "context.md"
            if prev_context_path.exists():
                link = formatter.dual_link(context_path, prev_context_path, "Previous Turn")
                links.append(f"- {link}")

        # Only append if there are related documents
        if links:
            related_section = "\n---\n\n## Related Documents\n" + "\n".join(links) + "\n"

            # Append to context.md
            with open(context_path, 'a') as f:
                f.write(related_section)

            logger.debug(f"Appended Related Documents section with {len(links)} links to {context_path}")

    # =========================================================================
    # FRESHNESS ANALYSIS (Background Task - runs after response sent)
    # =========================================================================

    def schedule_freshness_analysis(
        self,
        context_doc: ContextDocument,
        validation_result: Optional[Dict[str, Any]],
        turn_dir: Path
    ):
        """
        Schedule freshness analysis as a background task.

        This runs AFTER the response is sent to the user, so it doesn't
        affect response latency. It detects when new research contradicts
        prior data and downgrades the quality of outdated information.
        """
        if not FRESHNESS_ANALYZER_AVAILABLE:
            logger.debug("[TurnSaver] Freshness analyzer not available - skipping")
            return

        # Only run for live_search queries where new research was conducted
        action_needed = context_doc.get_action_needed() if hasattr(context_doc, 'get_action_needed') else ""
        if action_needed != "live_search":
            logger.debug(f"[TurnSaver] Skipping freshness analysis for action: {action_needed}")
            return

        # Check if research was performed (has §4 content)
        section4 = context_doc.get_section(4) or ""
        if not section4 or len(section4) < 100:
            logger.debug("[TurnSaver] Skipping freshness analysis - no substantial research in §4")
            return

        # Schedule as background task
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._run_freshness_analysis(context_doc, turn_dir))
            else:
                asyncio.run(self._run_freshness_analysis(context_doc, turn_dir))
            logger.info(f"[TurnSaver] Scheduled freshness analysis for turn {context_doc.turn_number}")
        except Exception as e:
            logger.warning(f"[TurnSaver] Failed to schedule freshness analysis: {e}")

    # =========================================================================
    # TURN SUMMARY (Background Task - runs after response sent)
    # =========================================================================

    def schedule_turn_summary(
        self,
        context_doc: ContextDocument,
        turn_dir: Path
    ):
        """
        Schedule turn summary generation as a background task.

        This runs AFTER the response is sent to the user. It appends a final
        Turn Summary section to context.md and updates the turn index.
        """
        if not FRESHNESS_ANALYZER_AVAILABLE:
            logger.debug("[TurnSaver] Turn summary recipe not available - skipping")
            return

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._run_turn_summary(context_doc, turn_dir))
            else:
                asyncio.run(self._run_turn_summary(context_doc, turn_dir))
            logger.info(f"[TurnSaver] Scheduled turn summary for turn {context_doc.turn_number}")
        except Exception as e:
            logger.warning(f"[TurnSaver] Failed to schedule turn summary: {e}")

    async def _run_turn_summary(
        self,
        context_doc: ContextDocument,
        turn_dir: Path
    ):
        """Generate and append the turn summary to context.md and index."""
        try:
            recipe = load_recipe("pipeline/phase7_summarizer")
            if not recipe:
                logger.warning("[TurnSaver] Could not load phase7_summarizer recipe")
                return

            context_path = turn_dir / "context.md"
            if not context_path.exists():
                logger.warning("[TurnSaver] context.md missing - cannot generate summary")
                return

            doc_pack = DocPackBuilder(recipe)
            doc_pack.add_document("context.md", context_path)
            prompt = doc_pack.build()

            llm_client = get_llm_client()
            response = await llm_client.complete(
                prompt=prompt,
                temperature=0.3,
                max_tokens=200
            )

            summary = self._parse_turn_summary(response)
            if not summary:
                logger.warning("[TurnSaver] Failed to parse turn summary output")
                return

            self._append_turn_summary_section(context_path, summary)
            self._apply_turn_summary_to_index(context_doc, turn_dir, summary)

        except Exception as e:
            logger.warning(f"[TurnSaver] Turn summary generation failed: {e}")

    def _parse_turn_summary(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse the LLM's turn summary JSON response."""
        if not response:
            return None

        text = response.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

    def _append_turn_summary_section(
        self,
        context_path: Path,
        summary: Dict[str, Any]
    ) -> None:
        """Append Turn Summary section to context.md (if missing)."""
        content = context_path.read_text()
        if "## 8. Turn Summary" in content or "## Turn Summary" in content:
            return

        summary_text = summary.get("summary", "").strip()
        topics = summary.get("topics") or []
        has_research = summary.get("has_research", False)
        research_topic = summary.get("research_topic") if has_research else None

        section = "\n---\n\n## 8. Turn Summary\n"
        section += f"**Summary:** {summary_text}\n"
        if topics:
            section += f"**Topics:** {', '.join(topics)}\n"
        section += f"**Has Research:** {str(bool(has_research)).lower()}\n"
        section += f"**Research Topic:** {research_topic if research_topic else 'null'}\n"

        with open(context_path, 'a') as f:
            f.write(section)

    def _apply_turn_summary_to_index(
        self,
        context_doc: ContextDocument,
        turn_dir: Path,
        summary: Dict[str, Any]
    ) -> None:
        """Update metadata and turn index with summary topics."""
        metadata = TurnMetadata.load(turn_dir)
        if not metadata:
            return

        summary_text = summary.get("summary", "").strip()
        topics = summary.get("topics") or []

        if summary_text:
            metadata.topic = summary_text
        if topics:
            metadata.keywords = topics

        if not metadata.action_needed:
            metadata.action_needed = self._extract_action_needed(context_doc)

        metadata.save(turn_dir)

        user_id = getattr(context_doc, 'user_id', None) or self.user_id
        search_index = TurnSearchIndex(context_doc.session_id, user_id=user_id)
        search_index.index_turn(turn_dir, metadata)

    async def _run_freshness_analysis(
        self,
        context_doc: ContextDocument,
        turn_dir: Path
    ):
        """
        Run the Freshness Analyzer LLM to detect contradictions.

        This uses the freshness_analyzer recipe to analyze:
        - §2 (Prior context with old findings)
        - §4 (New research findings)
        - §6 (Response sent to user)

        And detect if new findings contradict prior data.
        """
        try:
            # Load the freshness analyzer recipe
            recipe = load_recipe("freshness_analyzer")
            if not recipe:
                logger.warning("[TurnSaver] Could not load freshness_analyzer recipe")
                return

            # Extract prior findings from §2 for comparison
            prior_findings = self._extract_prior_findings(context_doc)
            if not prior_findings:
                logger.debug("[TurnSaver] No prior findings to analyze for freshness")
                return

            # Build prior_findings.md content
            prior_findings_md = "# Prior Findings\n\n"
            for finding in prior_findings:
                prior_findings_md += f"- **Turn {finding['turn']}**: {finding['claim']}\n"

            # Write prior_findings.md temporarily
            prior_findings_path = turn_dir / "prior_findings.md"
            prior_findings_path.write_text(prior_findings_md)

            # Build the prompt using DocPackBuilder
            doc_pack = DocPackBuilder(recipe)
            doc_pack.add_document("context.md", turn_dir / "context.md")
            doc_pack.add_document("prior_findings.md", prior_findings_path)
            prompt = doc_pack.build()

            # Call the LLM
            llm_client = get_llm_client()
            response = await llm_client.complete(
                prompt=prompt,
                temperature=0.3,  # Low temperature for analytical task
                max_tokens=500
            )

            # Parse the response
            analysis = self._parse_freshness_analysis(response)

            # Apply downgrades if contradictions found
            if analysis and analysis.get("contradictions_found"):
                await self._apply_freshness_downgrades(
                    analysis.get("contradictions", []),
                    context_doc.turn_number
                )

            # Clean up temp file
            if prior_findings_path.exists():
                prior_findings_path.unlink()

        except Exception as e:
            logger.warning(f"[TurnSaver] Freshness analysis failed: {e}")

    def _extract_prior_findings(self, context_doc: ContextDocument) -> List[Dict[str, Any]]:
        """
        Extract claims from prior turns in §2 that might be outdated.

        Looks for product/price claims in the Gathered Context section.
        """
        findings = []

        section2 = context_doc.get_section(2) or ""
        if not section2:
            return findings

        # Look for Prior Turn Context
        prior_match = re.search(
            r'### Prior Turn Context\n([\s\S]*?)(?=\n###|\n---|\Z)',
            section2
        )
        if not prior_match:
            return findings

        prior_text = prior_match.group(1)

        # Extract turn number and claims
        # Pattern: "Turn N:" or "turn_000XXX" followed by content
        turn_pattern = re.compile(
            r'(?:Turn\s+(\d+)|turn_0*(\d+))[:\s]*(.*?)(?=Turn\s+\d+|turn_0|\Z)',
            re.IGNORECASE | re.DOTALL
        )

        for match in turn_pattern.finditer(prior_text):
            turn_num = int(match.group(1) or match.group(2))
            content = match.group(3).strip()

            # Extract price/product claims
            # Pattern: "Product @ $Price" or "Product - $Price"
            claim_pattern = re.compile(
                r'([^@\-\n]+?)(?:@|\s+-\s+)\$?([\d,]+(?:\.\d{2})?)',
                re.IGNORECASE
            )
            for claim_match in claim_pattern.finditer(content):
                product = claim_match.group(1).strip()
                price = claim_match.group(2)
                if product and price:
                    findings.append({
                        "turn": turn_num,
                        "claim": f"{product} @ ${price}",
                        "product": product,
                        "price": float(price.replace(",", ""))
                    })

        return findings

    def _parse_freshness_analysis(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse the LLM's freshness analysis response."""
        try:
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return None

            analysis = json.loads(json_match.group())

            # Validate structure
            if analysis.get("_type") != "FRESHNESS_ANALYSIS":
                return None

            return analysis

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[TurnSaver] Failed to parse freshness analysis: {e}")
            return None

    async def _apply_freshness_downgrades(
        self,
        contradictions: List[Dict[str, Any]],
        current_turn: int
    ):
        """
        Apply quality downgrades to prior turns based on detected contradictions.

        Degradation factors by contradiction type:
        - availability_change: 0.3 (severe - product no longer exists)
        - price_change: 0.5 (moderate - price outdated)
        - product_removed: 0.3 (severe - product delisted)
        - spec_correction: 0.5 (moderate - specs changed)
        - retailer_change: 0.5 (moderate - different retailer)
        - general_update: 0.5 (moderate - general correction)
        """
        if not TURN_INDEX_AVAILABLE:
            logger.warning("[TurnSaver] Turn index not available - cannot apply downgrades")
            return

        if not contradictions:
            return

        degradation_factors = {
            "availability_change": 0.3,
            "price_change": 0.5,
            "product_removed": 0.3,
            "spec_correction": 0.5,
            "retailer_change": 0.5,
            "general_update": 0.5,
        }

        turn_db = get_turn_index_db(sync_on_startup=False)

        for contradiction in contradictions:
            prior_turn = contradiction.get("prior_turn")
            if not prior_turn:
                continue

            contradiction_type = contradiction.get("contradiction_type", "general_update")
            confidence = contradiction.get("confidence", 0.8)

            # Get degradation factor
            factor = degradation_factors.get(contradiction_type, 0.5)

            # Apply confidence to factor (higher confidence = more degradation)
            # factor * confidence gives effective degradation
            effective_factor = factor + (1 - factor) * (1 - confidence)

            # Apply the degradation
            success = turn_db.degrade_quality(
                turn_number=prior_turn,
                factor=effective_factor,
                reason=f"{contradiction_type}: {contradiction.get('new_finding', 'outdated')}",
                superseded_by=current_turn
            )

            if success:
                logger.info(
                    f"[TurnSaver] Freshness degradation applied: "
                    f"turn {prior_turn} quality reduced by {(1-effective_factor)*100:.0f}% "
                    f"({contradiction_type}, confidence={confidence:.2f})"
                )

                # Also mark research as superseded if available
                if RESEARCH_INDEX_AVAILABLE:
                    try:
                        research_db = get_research_index_db()
                        # Mark old research as superseded by new research
                        research_db.mark_superseded_by_turn(
                            prior_turn=prior_turn,
                            superseded_by_turn=current_turn,
                            reason=contradiction_type
                        )
                    except Exception as e:
                        logger.debug(f"[TurnSaver] Could not mark research as superseded: {e}")
