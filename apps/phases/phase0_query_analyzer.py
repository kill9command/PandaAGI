"""Phase 0: Query Analyzer - Resolves references and classifies queries.

Architecture Reference:
    architecture/main-system-patterns/phase1-query-analyzer.md

Role: REFLEX (temp=0.4)
Token Budget: ~1,500 total

Responsibilities:
    - Resolve pronouns/references ("the thread" -> specific content)
    - Capture user purpose in natural language
    - Detect content references to prior turns

NOTE: This is a LEGACY wrapper around the BasePhase interface.
The active code path uses libs/gateway/context/query_analyzer.py directly
via unified_flow.py. This file exists for the apps/phases/ interface.
"""

from typing import Optional

from libs.core.models import (
    QueryAnalysis,
    ContentReference,
)
from libs.core.exceptions import PhaseError
from libs.document_io.context_manager import ContextManager

from apps.phases.base_phase import BasePhase


class QueryAnalyzer(BasePhase[QueryAnalysis]):
    """
    Phase 0: Analyze and resolve user queries.

    Uses REFLEX role (temp=0.4) for fast, deterministic classification.
    """

    PHASE_NUMBER = 0
    PHASE_NAME = "query_analyzer"

    SYSTEM_PROMPT = """You are a query analyzer. Your job is to understand what the user is asking about.

Given a user query and recent conversation summaries, you must:
1. Resolve any pronouns or references to explicit entities
2. Capture the user's purpose in natural language
3. Identify if the user is referencing prior content

RULES:
- If the user says "the thread", "that article", "it", etc., find the specific content they mean
- Use the turn summaries to identify what content was discussed
- If you cannot determine what is being referenced, keep the original wording
- Be precise: use exact titles when available

Output JSON only. No explanation outside the JSON.

Output schema:
{
  "resolved_query": "the query with references resolved",
  "user_purpose": "Natural language statement of what the user wants (2-4 sentences)",
  "data_requirements": {
    "needs_current_prices": true | false,
    "needs_product_urls": true | false,
    "needs_live_data": true | false,
    "freshness_required": "< 1 hour | < 24 hours | any | null"
  },
  "reference_resolution": {
    "status": "not_needed | resolved | failed",
    "original_references": ["string"],
    "resolved_to": "string | null"
  },
  "mode": "chat | code",
  "was_resolved": true | false,
  "content_reference": {
    "title": "string | null",
    "content_type": "thread | article | product | video | null",
    "site": "string | null",
    "source_turn": "number | null"
  } or null,
  "reasoning": "brief explanation"
}"""

    async def execute(
        self,
        context: ContextManager,
        raw_query: str,
        turn_summaries: list[dict],
    ) -> QueryAnalysis:
        """
        Analyze user query.

        Args:
            context: Context manager for this turn
            raw_query: Original user query
            turn_summaries: Recent turn summaries for reference resolution

        Returns:
            QueryAnalysis with resolved query and classification
        """
        # Build user prompt
        user_prompt = self._build_user_prompt(raw_query, turn_summaries)

        # Call LLM (automatically uses REFLEX role via phase number)
        response = await self.call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=350,
        )

        # Parse response
        analysis = self._parse_response(raw_query, response)

        # Write to context.md section 0
        context.write_section_0(analysis)

        return analysis

    def _build_user_prompt(self, query: str, turn_summaries: list[dict]) -> str:
        """Build user prompt with context."""
        turns_text = ""
        if turn_summaries:
            for turn in turn_summaries[:3]:  # Include up to 3 recent turns
                turn_num = turn.get('turn') or turn.get('turn_number', '?')
                # Use query or topic
                turn_query = turn.get('query', '')
                topics = turn.get('topics', [])
                topic_str = ', '.join(topics) if topics else ''

                turns_text += f"\nTurn {turn_num}: \"{turn_query}\""
                if topic_str:
                    turns_text += f" (topics: {topic_str})"

                # Include response summary if available
                response = turn.get('response_summary', '')
                if response:
                    turns_text += f"\n  Response: {response[:100]}..."
        else:
            turns_text = "\n(No recent conversation history)"

        return f"""Query: {query}

Recent conversation:{turns_text}

IMPORTANT: If the query contains vague references like "some", "it", "that", "those",
look at the recent conversation to understand what the user is referring to.
For example, if the user previously asked about "hamsters" and now says "find some for sale",
resolve "some" to "hamsters".

Analyze this query and output the QueryAnalysis JSON."""

    def _parse_response(self, original_query: str, response: str) -> QueryAnalysis:
        """Parse LLM response into QueryAnalysis."""
        try:
            data = self.parse_json_response(response)

            # Parse reference resolution
            was_resolved = data.get("was_resolved", False)

            # Parse content reference
            content_ref = None
            if data.get("content_reference"):
                ref = data["content_reference"]
                # Only create if at least title is present
                if ref.get("title"):
                    content_ref = ContentReference(
                        title=ref.get("title", ""),
                        content_type=ref.get("content_type", ""),
                        site=ref.get("site"),
                        source_turn=ref.get("source_turn"),
                    )

            return QueryAnalysis(
                original_query=original_query,
                resolved_query=data.get("resolved_query", original_query),
                user_purpose=data.get("user_purpose", ""),
                data_requirements=data.get("data_requirements", {}),
                reference_resolution=data.get("reference_resolution", {}),
                mode=data.get("mode", "chat"),
                was_resolved=was_resolved,
                content_reference=content_ref,
                reasoning=data.get("reasoning", ""),
            )

        except PhaseError:
            raise
        except Exception as e:
            raise PhaseError(
                f"Failed to parse query analysis response in phase {self.PHASE_NUMBER}",
                phase=self.PHASE_NUMBER,
                context={
                    "phase_name": self.PHASE_NAME,
                    "error": str(e),
                    "response_preview": response[:500],
                },
            )


# Factory function for convenience
def create_query_analyzer(mode: str = "chat") -> QueryAnalyzer:
    """Create a QueryAnalyzer instance."""
    return QueryAnalyzer(mode=mode)
