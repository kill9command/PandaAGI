"""
Base Phase - Abstract base class for all pipeline phases.

Each phase follows a consistent pattern:
1. Receive context document and dependencies
2. Execute phase-specific logic
3. Update context document sections
4. Return phase result with metadata

This enables:
- Consistent interfaces across phases
- Independent testing of each phase
- Clear separation of concerns
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument
    from libs.gateway.persistence.turn_manager import TurnDirectory
    from libs.gateway.validation.phase_metrics import PhaseMetrics

logger = logging.getLogger(__name__)


@dataclass
class PhaseResult:
    """Result of a phase execution."""
    success: bool
    phase_name: str

    # Output data (phase-specific)
    data: Dict[str, Any] = field(default_factory=dict)

    # Routing decision (if applicable)
    route_to: Optional[str] = None  # "next_phase", "synthesis", "clarify", "retry"

    # Metrics
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0

    # Error handling
    error: Optional[str] = None

    def __post_init__(self):
        if self.error and self.success:
            logger.warning(f"[{self.phase_name}] PhaseResult has error but success=True")


class BasePhase(ABC):
    """
    Abstract base class for pipeline phases.

    Subclasses must implement:
    - phase_name: str property
    - execute(): async method containing phase logic

    Provides:
    - Consistent logging
    - Metrics integration
    - Error handling wrapper
    """

    def __init__(
        self,
        llm_client,
        metrics: Optional["PhaseMetrics"] = None,
    ):
        """
        Initialize the phase.

        Args:
            llm_client: LLM client for API calls
            metrics: Optional PhaseMetrics instance for telemetry
        """
        self.llm_client = llm_client
        self.metrics = metrics

    @property
    @abstractmethod
    def phase_name(self) -> str:
        """Return the phase name for logging and metrics."""
        pass

    @abstractmethod
    async def execute(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        **kwargs
    ) -> PhaseResult:
        """
        Execute the phase logic.

        Args:
            context_doc: The accumulating context document
            turn_dir: Turn directory for file I/O
            **kwargs: Phase-specific arguments

        Returns:
            PhaseResult with success status and output data
        """
        pass

    async def run(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        **kwargs
    ) -> PhaseResult:
        """
        Run the phase with metrics and error handling.

        This is the main entry point - it wraps execute() with:
        - Phase start/end metrics
        - Error handling
        - Logging

        Args:
            context_doc: The accumulating context document
            turn_dir: Turn directory for file I/O
            **kwargs: Phase-specific arguments

        Returns:
            PhaseResult with success status and output data
        """
        import time
        start_time = time.time()

        logger.info(f"[{self.phase_name}] Starting phase")

        if self.metrics:
            self.metrics.start_phase(self.phase_name)

        try:
            result = await self.execute(context_doc, turn_dir, **kwargs)

            duration_ms = int((time.time() - start_time) * 1000)
            result.duration_ms = duration_ms

            if self.metrics:
                self.metrics.end_phase(
                    self.phase_name,
                    tokens_in=result.tokens_in,
                    tokens_out=result.tokens_out
                )

            logger.info(
                f"[{self.phase_name}] Completed in {duration_ms}ms "
                f"(success={result.success}, route_to={result.route_to})"
            )

            return result

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"[{self.phase_name}] Failed after {duration_ms}ms: {e}", exc_info=True)

            if self.metrics:
                self.metrics.end_phase(self.phase_name, tokens_in=0, tokens_out=0)

            return PhaseResult(
                success=False,
                phase_name=self.phase_name,
                error=str(e),
                duration_ms=duration_ms
            )

    def _log_debug(self, message: str):
        """Log a debug message with phase prefix."""
        logger.debug(f"[{self.phase_name}] {message}")

    def _log_info(self, message: str):
        """Log an info message with phase prefix."""
        logger.info(f"[{self.phase_name}] {message}")

    def _log_warning(self, message: str):
        """Log a warning message with phase prefix."""
        logger.warning(f"[{self.phase_name}] {message}")

    def _log_error(self, message: str):
        """Log an error message with phase prefix."""
        logger.error(f"[{self.phase_name}] {message}")
