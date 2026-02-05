"""
Reflection Phase - Context sufficiency evaluation.

Extracted from UnifiedFlow to handle:
- Phase 1: Reflection (PROCEED/CLARIFY decision)

Architecture Reference:
- architecture/main-system-patterns/phase1-reflection.md
"""

import logging
from typing import Any, Callable, Dict, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument
    from libs.gateway.persistence.turn_manager import TurnDirectory

logger = logging.getLogger(__name__)


class ReflectionPhase:
    """
    Handles Phase 2 Reflection decision.

    Responsibilities:
    - Evaluate context sufficiency
    - Decide PROCEED or CLARIFY
    - Build §1 (Query Analysis Validation) section (legacy fallback)
    """

    def __init__(self, llm_client: Any, doc_pack_builder: Any):
        """Initialize the reflection phase handler."""
        self.llm_client = llm_client
        self.doc_pack_builder = doc_pack_builder

        # Callbacks
        self._write_context_md: Optional[Callable] = None
        self._parse_json_response: Optional[Callable] = None

    def set_callbacks(
        self,
        write_context_md: Callable,
        parse_json_response: Callable,
    ):
        """Set callbacks to UnifiedFlow methods."""
        self._write_context_md = write_context_md
        self._parse_json_response = parse_json_response

    async def run_reflection(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        max_iterations: int = 3
    ) -> Tuple["ContextDocument", str]:
        """
        Phase 1: Reflection (legacy fallback, recipe-based)

        Decides: PROCEED or CLARIFY.
        """
        from libs.gateway.llm.recipe_loader import load_recipe

        logger.info("[ReflectionPhase] Phase 1: Reflection (legacy)")

        for iteration in range(max_iterations):
            # Write current context.md for recipe to read
            if self._write_context_md:
                self._write_context_md(turn_dir, context_doc)

            # Load recipe and build doc pack (pipeline recipe)
            try:
                recipe = load_recipe("pipeline/phase2_reflection")
                pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
                prompt = pack.as_prompt()

                # Call LLM — REFLEX role (temp=0.4) for binary classification
                # See: architecture/LLM-ROLES/llm-roles-reference.md
                temperature = recipe._raw_spec.get("llm_params", {}).get("temperature", 0.4)
                llm_response = await self.llm_client.call(
                    prompt=prompt,
                    role="reflection",
                    max_tokens=recipe.token_budget.output,
                    temperature=temperature
                )

                # Parse JSON response
                if self._parse_json_response:
                    result = self._parse_json_response(llm_response)
                else:
                    import json
                    result = json.loads(llm_response)

                decision = result.get("decision", "PROCEED")
                reasoning = result.get("reasoning", "")
                interaction_type = result.get("interaction_type", "ACTION")
                is_followup = result.get("is_followup", False)
                confidence = result.get("confidence", 0.8)
                strategy_hint = result.get("strategy_hint")
                clarification_question = result.get("clarification_question")

            except Exception as e:
                logger.error(f"[ReflectionPhase] Phase 1 failed: {e}")
                raise

            # Append §1 (only on first iteration)
            if not context_doc.has_section(1):
                section_content = f"""**Decision:** {decision}
**Reasoning:** {reasoning}
**Interaction Type:** {interaction_type}
**Is Follow-up:** {str(is_followup).lower()}
**Confidence:** {confidence}
"""
                # Add strategy hint if present
                if strategy_hint:
                    section_content += f"**Strategy Hint:** {strategy_hint}\n"
                # Add clarification question if CLARIFY decision
                if decision == "CLARIFY" and clarification_question:
                    section_content += f"**Clarification Question:** {clarification_question}\n"
                context_doc.append_section(1, "Query Analysis Validation", section_content)

            if decision == "PROCEED":
                logger.info("[ReflectionPhase] Phase 1 complete: PROCEED (legacy)")
                return context_doc, decision

            elif decision == "CLARIFY":
                logger.info("[ReflectionPhase] Phase 1 complete: CLARIFY (legacy)")
                return context_doc, decision

            # Note: GATHER_MORE was removed from Reflection decisions (2025-12-30)
            # Reflection now only outputs PROCEED or CLARIFY per architecture docs.
            # See: panda_system_docs/architecture/main-system-patterns/phase2-reflection.md

        # Max iterations reached, proceed anyway
        logger.warning("[ReflectionPhase] Phase 1: Max iterations reached, proceeding (legacy)")
        return context_doc, "PROCEED"


# Singleton instance
_reflection_phase: ReflectionPhase = None


def get_reflection_phase(llm_client: Any = None, doc_pack_builder: Any = None) -> ReflectionPhase:
    """Get or create a ReflectionPhase instance."""
    global _reflection_phase
    if _reflection_phase is None or (llm_client is not None and doc_pack_builder is not None):
        _reflection_phase = ReflectionPhase(llm_client=llm_client, doc_pack_builder=doc_pack_builder)
    return _reflection_phase
