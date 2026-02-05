"""Phase 1: Reflection - PROCEED/CLARIFY gate.

Architecture Reference:
    architecture/main-system-patterns/phase1-reflection.md

Role: REFLEX (MIND model @ temp=0.4)
Token Budget: ~2,200 total

Core Question: "Can we answer this query?"

Design Principles:
    - Fast binary gate: PROCEED or CLARIFY
    - Default to PROCEED when uncertain
    - Only CLARIFY when genuinely ambiguous AND query could not be resolved by Phase 0
    - Acts as early gate before expensive operations

This phase runs BEFORE Context Gatherer, allowing the system to ask for
clarification early and avoid expensive context gathering on ambiguous queries.
"""

from typing import Optional

from libs.core.models import ReflectionResult, ReflectionDecision
from libs.core.exceptions import PhaseError
from libs.document_io.context_manager import ContextManager

from apps.phases.base_phase import BasePhase


class Reflection(BasePhase[ReflectionResult]):
    """
    Phase 1: Decide if query is clear enough to proceed.

    Uses REFLEX role (MIND model with temp=0.4) for fast,
    deterministic classification.

    Key Principle: Default to PROCEED when uncertain.
    Bad UX: Asking "What do you mean?" for every query
    Good UX: Making reasonable assumptions and asking only when truly necessary
    """

    PHASE_NUMBER = 1
    PHASE_NAME = "reflection"

    SYSTEM_PROMPT = """You are a query clarity checker. Your job is to decide if we can proceed with answering this query.

SYSTEM CAPABILITIES:
This system can:
- Internet research (search the web, find products, read forums/reviews)
- Coding tasks (write code, debug, explain code)
- Chat and conversation (answer questions, have discussions)
- Memory (remember user preferences and prior conversations)

Given the query analysis from Phase 0, decide:
- PROCEED: Query is clear enough to work on AND within system capabilities
- CLARIFY: Query is incoherent, too vague, OR outside system capabilities

RULES:
- Be generous - if you can reasonably interpret the query, PROCEED
- Only CLARIFY for truly unclear queries where you cannot guess intent
- CLARIFY if the query asks for something the system cannot do (e.g., "call my mom", "order pizza")
- If Phase 0's reference_resolution.status is "not_needed" or "resolved", strongly favor PROCEED
- If reference_resolution.status is "failed", evaluate if query is still actionable

INTERACTION TYPES:
- ACTION: User wants something done (find, buy, search)
- RETRY: User wants fresh/different results (search again)
- RECALL: User asking about previous results (what was that?)
- CLARIFICATION: User asking about prior response (what did you mean?)
- INFORMATIONAL: User wants to learn (how does X work?)

Output JSON only:
{
  "decision": "PROCEED | CLARIFY",
  "confidence": 0.0-1.0,
  "interaction_type": "ACTION | RETRY | RECALL | CLARIFICATION | INFORMATIONAL",
  "is_followup": true/false,
  "clarification_question": "string if CLARIFY, null otherwise",
  "reasoning": "brief explanation"
}"""

    async def execute(
        self,
        context: ContextManager,
    ) -> ReflectionResult:
        """
        Decide if we should proceed or ask for clarification.

        Args:
            context: Context manager with section 0 populated

        Returns:
            ReflectionResult with PROCEED or CLARIFY decision
        """
        # Read section 0 (query analysis)
        section_0 = context.read_section(0)

        if not section_0:
            raise PhaseError(
                "Section 0 not found - Phase 0 must run first",
                phase=self.PHASE_NUMBER,
                context={"phase_name": self.PHASE_NAME},
            )

        # Build user prompt
        user_prompt = f"""Evaluate this query for clarity:

{section_0}

Should I PROCEED or CLARIFY?"""

        # Call LLM (automatically uses REFLEX role via phase number)
        response = await self.call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=400,
        )

        # Parse response
        result = self._parse_response(response)

        # Write to context.md section 1
        context.write_section_1(result)

        return result

    def _parse_response(self, response: str) -> ReflectionResult:
        """Parse LLM response into ReflectionResult."""
        try:
            data = self.parse_json_response(response)

            # Parse decision
            decision_str = data.get("decision", "PROCEED").upper()
            try:
                decision = ReflectionDecision(decision_str)
            except ValueError:
                # Default to PROCEED on invalid decision
                decision = ReflectionDecision.PROCEED

            # Build result
            return ReflectionResult(
                decision=decision,
                confidence=float(data.get("confidence", 0.8)),
                query_type=data.get("interaction_type"),
                is_followup=data.get("is_followup", False),
                reasoning=data.get("reasoning", ""),
            )

        except PhaseError:
            raise
        except Exception as e:
            # Default to PROCEED on parse failure
            # Rationale: Better to try and potentially fail than to ask
            # unnecessary clarification questions
            return ReflectionResult(
                decision=ReflectionDecision.PROCEED,
                confidence=0.5,
                reasoning=f"Parse error, defaulting to PROCEED: {e}",
            )


# Factory function for convenience
def create_reflection(mode: str = "chat") -> Reflection:
    """Create a Reflection instance."""
    return Reflection(mode=mode)
