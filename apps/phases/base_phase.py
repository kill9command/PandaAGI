"""Base class for all pipeline phases.

Architecture Reference:
    architecture/Implementation/05-PIPELINE-PHASES.md

Design Principles:
    - All phases inherit from BasePhase
    - Phases use router.complete_for_phase() for automatic model/temp selection
    - Phases read from and write to context.md sections
    - Fail-fast on all errors (no silent fallbacks)
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, TypeVar, Generic

from pydantic import BaseModel

from libs.core.config import get_settings
from libs.core.exceptions import PhaseError, InterventionRequired
from libs.core.panda_logger import get_panda_logger
from libs.llm.router import get_model_router, ModelRouter
from libs.document_io.context_manager import ContextManager


# Generic type for phase result
T = TypeVar("T", bound=BaseModel)


class BasePhase(ABC, Generic[T]):
    """Abstract base class for all pipeline phases.

    Each phase:
    1. Reads context from previous phases via ContextManager
    2. Calls LLM via ModelRouter with appropriate phase number
    3. Writes its section to context.md
    4. Returns a result model

    The ModelRouter automatically selects the correct model and temperature
    based on the phase number:
    - Phases 0-1: REFLEX role (temp=0.3)
    - Phases 2-4, 6: MIND role (temp=0.5)
    - Phase 5: VOICE role (temp=0.7)
    """

    # Phase number (0-6) - override in subclasses
    PHASE_NUMBER: int = -1

    # Phase name for logging
    PHASE_NAME: str = "base"

    def __init__(self, mode: str = "chat"):
        """
        Initialize phase.

        Args:
            mode: Operating mode ("chat" or "code")
        """
        self.mode = mode
        self.settings = get_settings()
        self._router: Optional[ModelRouter] = None

    @property
    def router(self) -> ModelRouter:
        """Get model router (lazy initialization)."""
        if self._router is None:
            self._router = get_model_router()
        return self._router

    @abstractmethod
    async def execute(
        self,
        context: ContextManager,
        **kwargs,
    ) -> T:
        """
        Execute the phase logic.

        Args:
            context: Context manager for this turn
            **kwargs: Phase-specific arguments

        Returns:
            Phase result model

        Raises:
            PhaseError: On phase execution failure
            InterventionRequired: On unrecoverable errors
        """
        pass

    async def call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Call LLM with automatic phase-based routing.

        Uses complete_for_phase() which automatically selects:
        - Model: Based on phase number
        - Temperature: Based on phase role

        Args:
            system_prompt: System message
            user_prompt: User message
            max_tokens: Override default max tokens

        Returns:
            LLM response content

        Raises:
            PhaseError: On LLM call failure
        """
        import time
        plog = get_panda_logger()

        try:
            kwargs = {}
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens

            start_time = time.time()
            response = await self.router.complete_for_phase(
                phase=self.PHASE_NUMBER,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                **kwargs,
            )
            elapsed_ms = (time.time() - start_time) * 1000

            if not response or not response.content:
                raise PhaseError(
                    f"Empty response from LLM in phase {self.PHASE_NUMBER}",
                    phase=self.PHASE_NUMBER,
                    context={"phase_name": self.PHASE_NAME},
                )

            # Log the LLM call
            role = self._get_role_for_phase()
            plog.llm_call(
                role=role,
                prompt=f"[System]: {system_prompt[:200]}...\n[User]: {user_prompt[:300]}...",
                response=response.content[:500],
                tokens_in=getattr(response, 'prompt_tokens', 0),
                tokens_out=getattr(response, 'completion_tokens', 0),
                elapsed_ms=elapsed_ms,
            )

            return response.content

        except PhaseError:
            raise
        except Exception as e:
            plog.error(f"Phase{self.PHASE_NUMBER}", f"LLM call failed: {e}")
            raise PhaseError(
                f"LLM call failed in phase {self.PHASE_NUMBER}: {e}",
                phase=self.PHASE_NUMBER,
                context={
                    "phase_name": self.PHASE_NAME,
                    "error": str(e),
                },
            )

    def _get_role_for_phase(self) -> str:
        """Get the LLM role name for this phase."""
        if self.PHASE_NUMBER in (0, 1):
            return "REFLEX"
        elif self.PHASE_NUMBER == 5:
            return "VOICE"
        else:
            return "MIND"

    def parse_json_response(self, response: str) -> dict[str, Any]:
        """
        Parse JSON from LLM response.

        Handles common issues like:
        - JSON wrapped in markdown code blocks
        - Extra text before/after JSON

        Args:
            response: Raw LLM response

        Returns:
            Parsed JSON as dict

        Raises:
            PhaseError: On parse failure
        """
        import json
        import re

        # Try direct parse first
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code block
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
        if code_block_match:
            try:
                return json.loads(code_block_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding JSON object in response
        json_match = re.search(r"\{[\s\S]*\}", response)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # All parsing attempts failed
        raise PhaseError(
            f"Failed to parse JSON response in phase {self.PHASE_NUMBER}",
            phase=self.PHASE_NUMBER,
            context={
                "phase_name": self.PHASE_NAME,
                "response_preview": response[:500],
            },
        )

    def create_intervention(
        self,
        error: str,
        context: Optional[dict[str, Any]] = None,
        severity: str = "HIGH",
    ) -> InterventionRequired:
        """
        Create an intervention request.

        Used when the phase encounters an unrecoverable error
        that requires human attention.

        Args:
            error: Error description
            context: Additional context
            severity: Severity level (LOW, MEDIUM, HIGH)

        Returns:
            InterventionRequired exception
        """
        return InterventionRequired(
            component=f"Phase {self.PHASE_NUMBER}: {self.PHASE_NAME}",
            error=error,
            context=context or {},
            severity=severity,
        )
