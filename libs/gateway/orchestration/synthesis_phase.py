"""
Synthesis Phase - Response generation from context.

Extracted from UnifiedFlow to handle:
- Phase 6: Synthesis (draft response generation)
- Response revision based on validation feedback

Architecture Reference:
- architecture/main-system-patterns/phase6-synthesis.md
"""

import json
import logging
from typing import Any, Callable, Dict, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument
    from libs.gateway.persistence.turn_manager import TurnDirectory

logger = logging.getLogger(__name__)


class SynthesisPhase:
    """
    Handles Phase 6 Synthesis and response revision.

    Responsibilities:
    - Generate draft response from gathered context
    - Revise response based on validation feedback
    - Update §6 (Synthesis) section
    """

    def __init__(self, llm_client: Any, doc_pack_builder: Any):
        """Initialize the synthesis phase handler."""
        self.llm_client = llm_client
        self.doc_pack_builder = doc_pack_builder

        # Callbacks
        self._write_context_md: Optional[Callable] = None
        self._check_budget: Optional[Callable] = None
        self._parse_json_response: Optional[Callable] = None

    def set_callbacks(
        self,
        write_context_md: Callable,
        check_budget: Callable,
        parse_json_response: Callable,
    ):
        """Set callbacks to UnifiedFlow methods."""
        self._write_context_md = write_context_md
        self._check_budget = check_budget
        self._parse_json_response = parse_json_response

    async def run_synthesis(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        mode: str,
        recipe,
    ) -> Tuple["ContextDocument", str]:
        """
        Phase 6: Synthesis (recipe-based)

        Generates the draft response from context.md.
        """
        from libs.gateway.llm.recipe_loader import load_recipe

        logger.info(f"[SynthesisPhase] Phase 6: Synthesis")

        # Write current context.md for recipe to read
        if self._write_context_md:
            self._write_context_md(turn_dir, context_doc)

        # Load recipe and build doc pack (mode-based selection only)
        # Domain-specific prompts removed in favor of unified prompts that handle all content types
        try:
            if recipe is None:
                recipe = load_recipe(f"pipeline/phase5_synthesizer_{mode}")

            # Check budget before LLM call
            if self._check_budget:
                self._check_budget(context_doc, recipe, "Phase 6 Synthesis")

            pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
            prompt = pack.as_prompt()

            # Call LLM — VOICE role (temp=0.7) for user-facing response
            # See: architecture/LLM-ROLES/llm-roles-reference.md
            temperature = recipe._raw_spec.get("llm_params", {}).get("temperature", 0.7)
            llm_response = await self.llm_client.call(
                prompt=prompt,
                role="synthesizer",
                max_tokens=recipe.token_budget.output,
                temperature=temperature
            )

            # Parse response (may be JSON with "answer" field or plain text)
            # Be tolerant of LLM format variations - if JSON parsing fails, use raw text
            stripped = llm_response.strip()
            looks_like_json = (
                stripped.startswith("{") or
                stripped.startswith("```json") or
                stripped.startswith("```")
            )
            validation_checklist = None
            if looks_like_json and self._parse_json_response:
                try:
                    result = self._parse_json_response(llm_response)
                    response = result.get("answer", llm_response)
                    validation_checklist = result.get("validation_checklist")
                except (ValueError, json.JSONDecodeError):
                    # JSON parsing failed - just use the raw response
                    logger.warning("[SynthesisPhase] Synthesis JSON parsing failed, using raw response")
                    response = stripped
            else:
                response = stripped

        except Exception as e:
            logger.error(f"[SynthesisPhase] Synthesis recipe failed: {e}")
            raise RuntimeError(f"Synthesis phase failed: {e}") from e

        # Build §6 content (full draft for validation)
        # On RETRY, update existing section
        checklist_lines = self._format_validation_checklist(validation_checklist)
        section_content = f"""**Draft Response:**
{response}

**Validation Checklist:**
{checklist_lines}
"""
        if context_doc.has_section(6):
            context_doc.update_section(6, section_content)
        else:
            context_doc.append_section(6, "Synthesis", section_content)

        logger.info(f"[SynthesisPhase] Phase 6 complete: {len(response)} chars")
        return context_doc, response

    def _format_validation_checklist(self, checklist: Optional[Any]) -> str:
        """Format validation checklist entries for §6."""
        if not checklist or not isinstance(checklist, list):
            return "\n".join([
                "- [ ] Claims match evidence",
                "- [ ] User purpose satisfied",
                "- [ ] No hallucinations from prior context",
                "- [ ] Appropriate format",
                "- [ ] Sources include url + source_ref",
            ])

        lines = []
        for item in checklist:
            if isinstance(item, dict):
                label = str(item.get("item", "Checklist item")).strip()
                status = str(item.get("status", "")).lower()
                if status in ("pass", "true", "yes"):
                    mark = "x"
                elif status in ("na", "n/a"):
                    mark = " "
                    label = f"{label} (n/a)"
                else:
                    mark = " "
                lines.append(f"- [{mark}] {label}")
            else:
                lines.append(f"- [ ] {str(item).strip()}")

        return "\n".join(lines)

    async def revise_synthesis(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        original_response: str,
        revision_hints: str,
        mode: str
    ) -> str:
        """Revise synthesis based on validation hints."""
        from libs.gateway.llm.recipe_loader import load_recipe

        logger.info(f"[SynthesisPhase] Revising synthesis with hints: {revision_hints}")

        # Build revision prompt from recipe system — errors propagate
        recipe = load_recipe("pipeline/response_revision")
        prompt_template = recipe.get_prompt()
        revision_prompt = prompt_template.format(
            original_response=original_response,
            revision_hints=revision_hints
        )

        # VOICE role for revision — slightly lower temp for focused corrections
        temperature = recipe._raw_spec.get("llm_params", {}).get("temperature", 0.7)
        max_tokens = recipe._raw_spec.get("llm_params", {}).get("max_tokens", 2000)
        revised = await self.llm_client.call(
            prompt=revision_prompt,
            role="synthesizer",
            max_tokens=max_tokens,
            temperature=temperature
        )
        return revised.strip()


# Singleton instance
_synthesis_phase: SynthesisPhase = None


def get_synthesis_phase(llm_client: Any = None, doc_pack_builder: Any = None) -> SynthesisPhase:
    """Get or create a SynthesisPhase instance."""
    global _synthesis_phase
    if _synthesis_phase is None or (llm_client is not None and doc_pack_builder is not None):
        _synthesis_phase = SynthesisPhase(llm_client=llm_client, doc_pack_builder=doc_pack_builder)
    return _synthesis_phase
