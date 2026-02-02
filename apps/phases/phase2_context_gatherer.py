"""Phase 2: Context Gatherer - Retrieves relevant context.

Architecture Reference:
    architecture/main-system-patterns/phase2-context-gathering.md

Role: MIND (MIND model @ temp=0.5)
Token Budget: ~10,500 total (across 2 LLM calls)

Question: "What context does this query need?"

This phase only runs when Phase 1 (Reflection) has decided PROCEED.

Design Pattern: Plan-Act-Review with two distinct LLM calls:
    1. RETRIEVAL: Identify what's relevant (turn summaries, memory, research cache)
    2. SYNTHESIS: Extract and compile relevant information into section 2
"""

from pathlib import Path
from typing import Optional, Any

from libs.core.models import GatheredContext, ContextSource
from libs.core.exceptions import PhaseError
from libs.document_io.context_manager import ContextManager

from apps.phases.base_phase import BasePhase


class ContextGatherer(BasePhase[GatheredContext]):
    """
    Phase 2: Gather relevant context for the query.

    Uses MIND role (MIND model with temp=0.5) for reasoning
    about what context is relevant.

    Two-phase process:
    1. RETRIEVAL: Identify relevant turns, research, memory
    2. SYNTHESIS: Follow links, extract details, compile section 2
    """

    PHASE_NUMBER = 2
    PHASE_NAME = "context_gatherer"

    RETRIEVAL_SYSTEM_PROMPT = """You identify relevant context sources for a user query.

Given a query, determine what context to gather:
1. Session preferences that apply (budget, location, brands)
2. Prior turns that might be relevant
3. Cached research to check
4. Memory items to search

Output JSON:
{
  "load_preferences": ["budget", "location"],
  "search_turns": {
    "keywords": ["laptop", "gaming"],
    "max_results": 5
  },
  "check_research": {
    "topic": "commerce.laptop",
    "max_age_hours": 24
  },
  "search_memory": {
    "query": "user preferences for laptops"
  },
  "reasoning": "why these sources are relevant"
}"""

    SYNTHESIS_SYSTEM_PROMPT = """You synthesize gathered context into a structured format.

Given the query and retrieved documents, extract and compile relevant information.

CRITICAL: Only include data that ACTUALLY EXISTS in the provided context.
- If no prior turns are mentioned, use empty array: "relevant_turns": []
- If no research cache is mentioned, use null: "cached_research": null
- DO NOT make up or hallucinate any data

Output JSON:
{
  "session_preferences": {
    "key": "value from USER PREFERENCES section"
  },
  "relevant_turns": [],
  "cached_research": null,
  "sufficiency_assessment": "Can we answer with this context? What's missing?",
  "source_references": []
}"""

    async def execute(
        self,
        context: ContextManager,
        session_id: str,
        turn_index: Optional[Any] = None,
        memory_store: Optional[Any] = None,
        research_cache: Optional[Any] = None,
        user_id: Optional[str] = None,
    ) -> GatheredContext:
        """
        Gather context for the current query.

        Args:
            context: Context manager with sections 0-1
            session_id: User session for preferences/memory
            turn_index: Optional turn index for searching prior turns
            memory_store: Optional memory store for user facts
            research_cache: Optional research cache for prior research
            user_id: User ID for loading preferences from local storage

        Returns:
            GatheredContext with relevant information
        """
        # Phase 1: Retrieval - identify what to gather
        retrieval_plan = await self._retrieval_phase(context, session_id)

        # Load user preferences from local storage
        user_preferences = await self._load_user_preferences(user_id or session_id)

        # Phase 2: Synthesis - extract and compile
        gathered = await self._synthesis_phase(
            context,
            retrieval_plan,
            turn_index,
            memory_store,
            research_cache,
            user_preferences,
        )

        # Write to context.md section 2
        context.write_section_2(gathered)

        return gathered

    async def _load_user_preferences(self, user_id: str) -> dict[str, Any]:
        """Load user preferences from local storage."""
        import re
        # Use new consolidated path structure under obsidian_memory/Users/
        prefs_path = Path("panda_system_docs/obsidian_memory/Users") / user_id / "preferences.md"
        facts_path = Path("panda_system_docs/obsidian_memory/Users") / user_id / "facts.md"

        preferences = {}
        facts = []

        # Load preferences
        if prefs_path.exists():
            content = prefs_path.read_text()
            # Parse markdown list items: - **key:** value
            pattern = r"-\s+\*\*([^:*]+):\*\*\s*(.+?)(?=\n-|\n\n|\Z)"
            for match in re.finditer(pattern, content, re.DOTALL):
                key = match.group(1).strip()
                value = match.group(2).strip()
                preferences[key] = value

        # Load facts
        if facts_path.exists():
            content = facts_path.read_text()
            fact_matches = re.findall(r"-\s+(.+?)(?=\n-|\n\n|\Z)", content)
            facts = [f.strip() for f in fact_matches if f.strip() and not f.startswith("*")]

        return {
            "preferences": preferences,
            "facts": facts,
        }

    async def _retrieval_phase(
        self,
        context: ContextManager,
        session_id: str,
    ) -> dict[str, Any]:
        """
        Identify what context to gather.

        Returns retrieval plan specifying which sources to load.
        """
        # Read previous sections
        section_0 = context.read_section(0)
        section_1 = context.read_section(1)

        user_prompt = f"""Query context:
{section_0}

Reflection:
{section_1}

Session ID: {session_id}

What context should I gather for this query?"""

        response = await self.call_llm(
            system_prompt=self.RETRIEVAL_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=500,
        )

        try:
            return self.parse_json_response(response)
        except PhaseError:
            # Return minimal plan on parse failure
            return {
                "load_preferences": [],
                "search_turns": {},
                "check_research": {},
                "reasoning": "Parse error in retrieval phase",
            }

    async def _synthesis_phase(
        self,
        context: ContextManager,
        retrieval_plan: dict[str, Any],
        turn_index: Optional[Any],
        memory_store: Optional[Any],
        research_cache: Optional[Any],
        user_preferences: Optional[dict[str, Any]] = None,
    ) -> GatheredContext:
        """
        Synthesize gathered context into section 2.

        Follows links, extracts relevant sections, compiles summary.
        """
        section_0 = context.read_section(0)
        user_preferences = user_preferences or {"preferences": {}, "facts": []}

        # Build context with loaded user preferences
        prefs_str = ""
        if user_preferences.get("preferences"):
            prefs_str = "\n".join(
                f"- {k}: {v}" for k, v in user_preferences["preferences"].items()
            )
        facts_str = ""
        if user_preferences.get("facts"):
            facts_str = "\n".join(f"- {f}" for f in user_preferences["facts"])

        loaded_context = f"""Retrieval Plan:
- Preferences to load: {retrieval_plan.get('load_preferences', [])}
- Turn search: {retrieval_plan.get('search_turns', {})}
- Research check: {retrieval_plan.get('check_research', {})}
- Memory search: {retrieval_plan.get('search_memory', {})}

USER PREFERENCES FROM MEMORY:
{prefs_str if prefs_str else '(none saved)'}

USER FACTS FROM MEMORY:
{facts_str if facts_str else '(none saved)'}

Query:
{section_0}"""

        user_prompt = f"""Based on this retrieval plan, user preferences, and query, synthesize the context:

{loaded_context}

IMPORTANT: Include any user preferences/facts found in the session_preferences field.
Generate a sufficiency assessment and identify what context would be helpful."""

        response = await self.call_llm(
            system_prompt=self.SYNTHESIS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=500,
        )

        try:
            data = self.parse_json_response(response)
            # Ensure user preferences are included even if LLM didn't extract them
            if user_preferences.get("preferences"):
                if "session_preferences" not in data:
                    data["session_preferences"] = {}
                data["session_preferences"].update(user_preferences["preferences"])
            return self._build_gathered_context(data)
        except PhaseError:
            # Return minimal context with user preferences on parse failure
            return GatheredContext(
                session_preferences=user_preferences.get("preferences", {}),
                relevant_turns=[],
                cached_research=None,
                source_references=[],
                sufficiency_assessment="Unable to gather context. Will need fresh research.",
            )

    def _build_gathered_context(self, data: dict[str, Any]) -> GatheredContext:
        """Build GatheredContext from parsed response."""
        # Parse relevant turns
        relevant_turns = []
        for turn_data in data.get("relevant_turns", []):
            # Handle case where LLM returns strings instead of dicts
            if isinstance(turn_data, str):
                continue  # Skip malformed entries
            if not isinstance(turn_data, dict):
                continue
            relevant_turns.append(
                ContextSource(
                    path=f"turns/turn_{turn_data.get('turn', 0):06d}/context.md",
                    turn_number=turn_data.get("turn"),
                    relevance=turn_data.get("relevance", 0.5),
                    summary=turn_data.get("summary", ""),
                )
            )

        # Build cached research info
        cached_research = None
        cr = data.get("cached_research")
        if cr and isinstance(cr, dict):
            cached_research = {
                "topic": cr.get("topic", ""),
                "quality": cr.get("quality", 0.0),
                "age": f"{cr.get('age_hours', 0)} hours",
                "summary": cr.get("summary", ""),
                "still_relevant": cr.get("still_relevant", False),
            }

        return GatheredContext(
            session_preferences=data.get("session_preferences", {}),
            relevant_turns=relevant_turns,
            cached_research=cached_research,
            source_references=data.get("source_references", []),
            sufficiency_assessment=data.get(
                "sufficiency_assessment",
                "No prior context found. Will need fresh research.",
            ),
        )


# Factory function for convenience
def create_context_gatherer(mode: str = "chat") -> ContextGatherer:
    """Create a ContextGatherer instance."""
    return ContextGatherer(mode=mode)
