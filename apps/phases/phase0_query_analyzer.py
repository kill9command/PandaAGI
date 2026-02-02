"""Phase 0: Query Analyzer - Resolves references and classifies queries.

Architecture Reference:
    architecture/main-system-patterns/phase0-query-analyzer.md

Role: REFLEX (MIND model @ temp=0.3)
Token Budget: ~1,500 total

Responsibilities:
    - Resolve pronouns/references ("the thread" -> specific content)
    - Classify query type (specific_content, general_question, followup)
    - Detect content references to prior turns
    - Add minimal latency (~50-100ms) to the pipeline

Key Design Decision:
    This phase replaces hardcoded pattern matching with LLM understanding.
    Instead of regex rules like `if "the thread" in query`, the LLM
    interprets context naturally.
"""

from typing import Optional

from libs.core.models import (
    QueryAnalysis,
    QueryType,
    ContentReference,
)
from libs.core.exceptions import PhaseError
from libs.document_io.context_manager import ContextManager

from apps.phases.base_phase import BasePhase


class QueryAnalyzer(BasePhase[QueryAnalysis]):
    """
    Phase 0: Analyze and resolve user queries.

    Uses REFLEX role (MIND model with temp=0.3) for fast,
    deterministic classification.
    """

    PHASE_NUMBER = 0
    PHASE_NAME = "query_analyzer"

    SYSTEM_PROMPT = """You are a query analyzer. Your job is to understand what the user is asking about.

Given a user query and recent conversation summaries, you must:
1. Resolve any pronouns or references to explicit entities
2. Classify the query type
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
  "reference_resolution": {
    "status": "not_needed | resolved | failed",
    "original_references": ["string"],
    "resolved_to": "string | null"
  },
  "query_type": "specific_content | general_question | followup | new_topic",
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
            max_tokens=300,
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
            for turn in turn_summaries[:5]:  # Include up to 5 recent turns
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
            ref_resolution = data.get("reference_resolution", {})
            status = ref_resolution.get("status", "not_needed")
            was_resolved = status == "resolved"

            # Parse content reference
            content_ref = None
            if data.get("content_reference"):
                ref = data["content_reference"]
                # Only create if at least title is present
                if ref.get("title"):
                    content_ref = ContentReference(
                        title=ref.get("title", ""),
                        content_type=ref.get("content_type", ""),
                        site=ref.get("site", ""),
                        source_turn=ref.get("source_turn", 0),
                    )

            # Parse query type
            query_type_str = data.get("query_type", "general_question")
            try:
                query_type = QueryType(query_type_str)
            except ValueError:
                query_type = QueryType.GENERAL_QUESTION

            return QueryAnalysis(
                original_query=original_query,
                resolved_query=data.get("resolved_query", original_query),
                was_resolved=was_resolved,
                query_type=query_type,
                content_reference=content_ref,
                reasoning=data.get("reasoning", ""),
            )

        except PhaseError:
            raise
        except Exception as e:
            # Return minimal valid result on parse failure
            # Note: In production, this would be an intervention
            return QueryAnalysis(
                original_query=original_query,
                resolved_query=original_query,
                was_resolved=False,
                query_type=QueryType.GENERAL_QUESTION,
                reasoning=f"Parse error: {e}",
            )


# Factory function for convenience
def create_query_analyzer(mode: str = "chat") -> QueryAnalyzer:
    """Create a QueryAnalyzer instance."""
    return QueryAnalyzer(mode=mode)
