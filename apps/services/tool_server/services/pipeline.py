"""
Pipeline Service for PandaAI Orchestrator

Executes the 9-phase pipeline with proper loop control for
RETRY (Phase 3) and REVISE (Phase 5) from validation.

Architecture Reference:
    architecture/LLM-ROLES/llm-roles-reference.md
    architecture/main-system-patterns/phase7-validation.md

9-Phase Pipeline (0-8):
    Phase 0: Query Analyzer (REFLEX role, temp=0.4)
    Phase 1: Reflection (REFLEX role, temp=0.4) - PROCEED/CLARIFY gate
    Phase 2: Context Gatherer (MIND role, temp=0.6)
    Phase 3: Planner (MIND role, temp=0.6)
    Phase 4: Executor (MIND role, temp=0.6) - tool execution
    Phase 5: Coordinator (MIND role, temp=0.6) - tool coordination
    Phase 6: Synthesis (VOICE role, temp=0.7)
    Phase 7: Validation (MIND role, temp=0.6) - quality gate
    Phase 8: Save (procedural, no LLM)

Loop Limits:
    - MAX_PLANNER_ITERATIONS = 5 (Planner-Coordinator loop)
    - MAX_RETRY_LOOPS = 1 (back to Phase 3)
    - MAX_REVISE_LOOPS = 2 (back to Phase 5)

Events:
    Emits events for each phase start/complete for real-time updates.
"""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

from libs.core.config import get_settings
from libs.core.models import (
    ReflectionDecision,
    PlannerAction,
    PlannerRoute,
    ValidationDecision,
)
from libs.core.exceptions import PhaseError, InterventionRequired
from libs.document_io.context_manager import ContextManager

from apps.services.tool_server.models.turn import (
    Turn,
    TurnState,
    PhaseResult,
    PhaseStatus,
)
from apps.services.tool_server.models.events import (
    TurnStartedEvent,
    PhaseStartedEvent,
    PhaseCompletedEvent,
    TurnCompleteEvent,
    ErrorEvent,
    PHASE_NAMES,
    get_phase_name,
)
from apps.services.tool_server.services.turn_manager import TurnManager, get_turn_manager
from apps.services.tool_server.services.session_manager import SessionManager, get_session_manager

# Import phase implementations
# Try apps.phases first (symlink), fall back to apps.main_system_patterns.phases
try:
    from apps.phases import (
        QueryAnalyzer,
        Reflection,
        ContextGatherer,
        Planner,
        Coordinator,
        Synthesis,
        Validation,
        Save,
    )
except ImportError:
    # Fallback: direct import from main-system-patterns (requires path setup)
    # This handles the case where apps.phases symlink doesn't exist
    import sys
    from pathlib import Path as PathLib

    # Add apps/main-system-patterns to path if needed
    phases_path = PathLib(__file__).parent.parent.parent / "main-system-patterns"
    if str(phases_path) not in sys.path:
        sys.path.insert(0, str(phases_path))

    from phases import (
        QueryAnalyzer,
        Reflection,
        ContextGatherer,
        Planner,
        Coordinator,
        Synthesis,
        Validation,
        Save,
    )


logger = logging.getLogger(__name__)


# Type for event callback
EventCallback = Callable[[Any], None]


class PipelineService:
    """
    Orchestrates the 9-phase pipeline execution.

    Responsibilities:
    1. Create and manage turns
    2. Execute phases in sequence (0-7)
    3. Manage the Planner-Coordinator loop (Phase 3-4)
    4. Handle RETRY (back to Phase 3, max 1) and REVISE (back to Phase 5, max 2)
    5. Emit events for each phase start/complete
    6. Return final response to user

    Key Principle: The PipelineService owns loop control.
    Phases only OUTPUT decisions (EXECUTE/COMPLETE, APPROVE/REVISE/RETRY/FAIL).

    Usage:
        service = PipelineService(session_id="abc123")

        # Run pipeline
        turn = await service.run_pipeline(turn)

        # Or with event callbacks
        async def on_event(event):
            print(f"Event: {event.type}")

        turn = await service.run_pipeline(turn, on_event=on_event)
    """

    # Loop limits from architecture
    MAX_PLANNER_ITERATIONS = 5
    MAX_RETRY_LOOPS = 1
    MAX_REVISE_LOOPS = 2

    def __init__(
        self,
        session_id: str,
        user_id: str = "default",
        mode: str = "chat",
    ):
        """
        Initialize pipeline service.

        Args:
            session_id: Session identifier
            user_id: User identifier
            mode: Operating mode ("chat" or "code")
        """
        self.session_id = session_id
        self.user_id = user_id
        self.mode = mode
        self.settings = get_settings()

        # Managers
        self.turn_manager = get_turn_manager(user_id)
        self.session_manager = get_session_manager()

        # Phase instances (lazily initialized)
        self._phases: dict[int, Any] = {}

        # Event callback
        self._event_callback: Optional[EventCallback] = None

    def _get_phase(self, phase_num: int):
        """Get or create phase instance."""
        if phase_num not in self._phases:
            phase_classes = {
                0: QueryAnalyzer,
                1: Reflection,
                2: ContextGatherer,
                3: Planner,
                4: Coordinator,
                5: Synthesis,
                6: Validation,
                7: Save,
            }
            phase_class = phase_classes.get(phase_num)
            if phase_class is None:
                raise ValueError(f"Invalid phase number: {phase_num}")
            self._phases[phase_num] = phase_class(mode=self.mode)
        return self._phases[phase_num]

    def _emit_event(self, event: Any) -> None:
        """Emit an event to the callback if set."""
        if self._event_callback is not None:
            try:
                self._event_callback(event)
            except Exception as e:
                logger.warning(f"Event callback error: {e}")

    async def run_pipeline(
        self,
        turn: Turn,
        on_event: Optional[EventCallback] = None,
    ) -> Turn:
        """
        Execute the full 9-phase pipeline.

        Args:
            turn: Turn to process
            on_event: Optional callback for phase events

        Returns:
            Updated Turn with response and validation

        Raises:
            PhaseError: On phase execution failure
            InterventionRequired: On unrecoverable errors
        """
        self._event_callback = on_event
        turn_id = turn.metadata.turn_id
        query = turn.metadata.query

        # Mark turn as processing
        self.turn_manager.update_turn(turn_id, state=TurnState.PROCESSING)

        # Emit turn started event
        self._emit_event(TurnStartedEvent(
            turn_id=turn_id,
            session_id=self.session_id,
        ))

        # Create turn directory and context
        turn_dir = self.turn_manager.get_turn_dir(turn_id)
        context = ContextManager(turn_dir)
        context.create(query, self.session_id, turn_id)

        start_time = time.time()

        try:
            # Run the pipeline
            turn = await self._execute_pipeline(turn, context)

            # Calculate duration
            duration_ms = int((time.time() - start_time) * 1000)
            turn.total_duration_ms = duration_ms

            # Mark turn as completed
            self.turn_manager.update_turn(
                turn_id,
                state=TurnState.COMPLETED,
                response=turn.response,
                quality=turn.quality,
                validation=turn.validation,
            )

            # Emit turn complete event
            self._emit_event(TurnCompleteEvent(
                turn_id=turn_id,
                validation=turn.validation.decision.value if turn.validation else "UNKNOWN",
                quality=turn.quality,
                total_duration_ms=duration_ms,
                tokens_used=turn.tokens_used,
            ))

            # Add turn to session
            self.session_manager.add_turn_to_session(self.session_id, turn_id)

            return turn

        except InterventionRequired as e:
            logger.error(f"Intervention required: {e}")
            self._emit_event(ErrorEvent(
                turn_id=turn_id,
                message=str(e),
                code="INTERVENTION_REQUIRED",
                recoverable=False,
            ))
            self.turn_manager.update_turn(turn_id, state=TurnState.FAILED, error=str(e))
            turn.state = TurnState.FAILED
            turn.error = str(e)
            raise

        except PhaseError as e:
            logger.error(f"Phase {e.phase} error: {e}")
            self._emit_event(ErrorEvent(
                turn_id=turn_id,
                phase=e.phase,
                message=str(e),
                code="PHASE_ERROR",
                recoverable=False,
            ))
            self.turn_manager.update_turn(turn_id, state=TurnState.FAILED, error=str(e))
            turn.state = TurnState.FAILED
            turn.error = str(e)
            raise

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            self._emit_event(ErrorEvent(
                turn_id=turn_id,
                message=str(e),
                code="PIPELINE_ERROR",
                recoverable=False,
            ))
            self.turn_manager.update_turn(turn_id, state=TurnState.FAILED, error=str(e))
            turn.state = TurnState.FAILED
            turn.error = str(e)
            raise

    async def _execute_pipeline(
        self,
        turn: Turn,
        context: ContextManager,
    ) -> Turn:
        """
        Execute the core pipeline logic (phases 0-7).

        Handles RETRY (back to Phase 3) and REVISE (back to Phase 5) loops.
        """
        turn_id = turn.metadata.turn_id
        query = turn.metadata.query

        # =====================================================================
        # Phase 0: Query Analyzer
        # =====================================================================
        analysis = await self._run_phase(turn, 0, context, query=query)

        # Update turn with resolved query
        if analysis.was_resolved:
            turn.metadata.resolved_query = analysis.resolved_query

        # =====================================================================
        # Phase 1: Reflection (Early Gate)
        # =====================================================================
        reflection = await self._run_phase(turn, 1, context)

        # Early exit on CLARIFY
        if reflection.decision == ReflectionDecision.CLARIFY:
            logger.info(f"Turn {turn_id}: Phase 1 CLARIFY - needs clarification")
            turn.response = f"I need some clarification: {reflection.reasoning}"
            turn.quality = 0.0
            return turn

        # =====================================================================
        # Phase 2: Context Gatherer
        # =====================================================================
        await self._run_phase(turn, 2, context)

        # =====================================================================
        # Main execution with RETRY loop
        # =====================================================================
        retry_count = 0
        synthesis_result = None
        validation_result = None

        while retry_count <= self.MAX_RETRY_LOOPS:
            attempt = retry_count + 1
            logger.info(f"Turn {turn_id}: Pipeline attempt {attempt}")

            # -----------------------------------------------------------------
            # Phase 3: Planner
            # -----------------------------------------------------------------
            plan = await self._run_phase(turn, 3, context, attempt=attempt)

            # Check for CLARIFY route from Planner
            if plan.route == PlannerRoute.CLARIFY:
                logger.info(f"Turn {turn_id}: Planner requested clarification")
                turn.response = f"I need clarification: {plan.reasoning}"
                turn.quality = 0.0
                return turn

            # -----------------------------------------------------------------
            # Phase 4: Coordinator (Planner-Coordinator loop)
            # -----------------------------------------------------------------
            if plan.decision == PlannerAction.EXECUTE:
                await self._run_planner_coordinator_loop(turn, context, plan)

            # -----------------------------------------------------------------
            # Phase 5: Synthesis (with REVISE loop)
            # -----------------------------------------------------------------
            synthesis_result = await self._run_phase(turn, 5, context, attempt=1)

            # -----------------------------------------------------------------
            # Phase 6: Validation (with REVISE sub-loop)
            # -----------------------------------------------------------------
            validation_result = await self._run_phase(turn, 6, context, attempt=1)

            # Process validation decision
            if validation_result.decision == ValidationDecision.APPROVE:
                logger.info(f"Turn {turn_id}: Validation APPROVE")
                break

            elif validation_result.decision == ValidationDecision.REVISE:
                # REVISE loop (back to Phase 5)
                revise_result = await self._run_revise_loop(
                    turn, context, validation_result
                )
                synthesis_result = revise_result["synthesis"]
                validation_result = revise_result["validation"]
                if revise_result["approved"]:
                    break
                # REVISE exhausted, continue with best effort
                logger.warning(f"Turn {turn_id}: REVISE loop exhausted")
                break

            elif validation_result.decision == ValidationDecision.RETRY:
                # RETRY loop (back to Phase 3)
                retry_count += 1
                self.turn_manager.increment_retry_count(turn_id)

                if retry_count > self.MAX_RETRY_LOOPS:
                    logger.warning(f"Turn {turn_id}: Max RETRY loops exceeded")
                    turn.response = "I was unable to complete your request after retrying."
                    turn.quality = validation_result.confidence
                    turn.validation = validation_result
                    return turn

                logger.info(f"Turn {turn_id}: RETRY - back to Phase 3 (attempt {retry_count + 1})")
                continue

            else:  # FAIL
                logger.error(f"Turn {turn_id}: Validation FAIL")
                turn.response = "I encountered an error and could not complete your request."
                turn.quality = validation_result.confidence
                turn.validation = validation_result
                return turn

        # =====================================================================
        # Phase 7: Save
        # =====================================================================
        await self._run_phase(turn, 7, context, turn_number=turn_id)

        # Set final response
        response_path = context.turn_dir / "response.md"
        if response_path.exists():
            turn.response = response_path.read_text()
        elif synthesis_result:
            turn.response = synthesis_result.full_response

        turn.quality = validation_result.confidence if validation_result else 0.0
        turn.validation = validation_result

        return turn

    async def _run_phase(
        self,
        turn: Turn,
        phase_num: int,
        context: ContextManager,
        attempt: int = 1,
        **kwargs,
    ) -> Any:
        """
        Run a single phase with event emission.

        Args:
            turn: Current turn
            phase_num: Phase number (0-7)
            context: Context manager
            attempt: Attempt number for loops
            **kwargs: Phase-specific arguments

        Returns:
            Phase result

        Raises:
            PhaseError: On phase failure
        """
        turn_id = turn.metadata.turn_id
        phase_name = get_phase_name(phase_num)

        # Update turn state
        self.turn_manager.update_turn(turn_id, current_phase=phase_num)

        # Emit phase started
        self._emit_event(PhaseStartedEvent(
            phase=phase_num,
            name=phase_name,
            turn_id=turn_id,
            attempt=attempt,
        ))

        start_time = time.time()

        try:
            # Get phase instance and execute
            phase = self._get_phase(phase_num)
            result = await phase.execute(context, **kwargs)

            duration_ms = int((time.time() - start_time) * 1000)

            # Add phase result to turn
            self.turn_manager.add_phase_result(
                turn_id,
                phase=phase_num,
                name=phase_name,
                status=PhaseStatus.COMPLETED,
                duration_ms=duration_ms,
                output=result.model_dump() if hasattr(result, "model_dump") else None,
                attempt=attempt,
            )

            # Emit phase completed
            self._emit_event(PhaseCompletedEvent(
                phase=phase_num,
                name=phase_name,
                duration_ms=duration_ms,
                turn_id=turn_id,
                success=True,
            ))

            logger.info(f"Turn {turn_id}: Phase {phase_num} ({phase_name}) completed in {duration_ms}ms")

            return result

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)

            # Add failed phase result
            self.turn_manager.add_phase_result(
                turn_id,
                phase=phase_num,
                name=phase_name,
                status=PhaseStatus.FAILED,
                duration_ms=duration_ms,
                error=str(e),
                attempt=attempt,
            )

            # Emit phase completed with failure
            self._emit_event(PhaseCompletedEvent(
                phase=phase_num,
                name=phase_name,
                duration_ms=duration_ms,
                turn_id=turn_id,
                success=False,
            ))

            logger.error(f"Turn {turn_id}: Phase {phase_num} ({phase_name}) failed: {e}")

            raise

    async def _run_planner_coordinator_loop(
        self,
        turn: Turn,
        context: ContextManager,
        initial_plan,
    ) -> None:
        """
        Execute the Planner-Coordinator loop (max 5 iterations).

        The loop continues until:
        - Planner returns COMPLETE
        - Max iterations reached
        - Planner routes to SYNTHESIS
        """
        turn_id = turn.metadata.turn_id
        iteration = 0
        current_plan = initial_plan

        while iteration < self.MAX_PLANNER_ITERATIONS:
            iteration += 1
            logger.info(f"Turn {turn_id}: Planner-Coordinator iteration {iteration}")

            # -----------------------------------------------------------------
            # Phase 4: Coordinator (execute tools)
            # -----------------------------------------------------------------
            coordinator_result = await self._run_phase(
                turn, 4, context,
                plan=current_plan,
                iteration=iteration,
            )

            # Check if Coordinator signals done
            if coordinator_result.action == "DONE":
                logger.info(f"Turn {turn_id}: Coordinator signaled DONE")
                break

            # -----------------------------------------------------------------
            # Phase 3: Planner (re-plan based on results)
            # -----------------------------------------------------------------
            current_plan = await self._run_phase(turn, 3, context)

            # Check Planner decision
            if current_plan.decision == PlannerAction.COMPLETE:
                logger.info(f"Turn {turn_id}: Planner signaled COMPLETE")
                break

            if current_plan.route == PlannerRoute.SYNTHESIS:
                logger.info(f"Turn {turn_id}: Planner routing to synthesis")
                break

        if iteration >= self.MAX_PLANNER_ITERATIONS:
            logger.warning(f"Turn {turn_id}: Max Planner iterations ({self.MAX_PLANNER_ITERATIONS}) reached")

    async def _run_revise_loop(
        self,
        turn: Turn,
        context: ContextManager,
        initial_validation,
    ) -> dict[str, Any]:
        """
        Execute the REVISE loop (Phase 5 <-> Phase 6, max 2 times).

        Returns:
            Dict with:
                - approved: True if validation passed
                - synthesis: Final synthesis result
                - validation: Final validation result
        """
        turn_id = turn.metadata.turn_id
        revise_count = 0
        synthesis_result = None
        validation_result = initial_validation

        while revise_count < self.MAX_REVISE_LOOPS:
            revise_count += 1
            self.turn_manager.increment_revise_count(turn_id)
            attempt = revise_count + 1  # +1 because original was attempt 1

            logger.info(f"Turn {turn_id}: REVISE loop iteration {revise_count}")

            # Phase 5: Synthesis (with revision hints)
            synthesis_result = await self._run_phase(
                turn, 5, context,
                attempt=attempt,
                revision_hints=validation_result.revision_hints,
            )

            # Phase 6: Validation
            validation_result = await self._run_phase(
                turn, 6, context,
                attempt=attempt,
            )

            if validation_result.decision == ValidationDecision.APPROVE:
                logger.info(f"Turn {turn_id}: REVISE loop APPROVE")
                return {
                    "approved": True,
                    "synthesis": synthesis_result,
                    "validation": validation_result,
                }

            if validation_result.decision != ValidationDecision.REVISE:
                # RETRY or FAIL - exit REVISE loop
                logger.info(f"Turn {turn_id}: REVISE loop {validation_result.decision.value}")
                break

        # Max REVISE attempts reached
        logger.warning(f"Turn {turn_id}: Max REVISE attempts ({self.MAX_REVISE_LOOPS}) reached")
        return {
            "approved": False,
            "synthesis": synthesis_result,
            "validation": validation_result,
        }

    async def run_pipeline_streaming(
        self,
        turn: Turn,
    ) -> AsyncIterator[dict]:
        """
        Execute pipeline with streaming progress updates.

        Yields progress dicts for real-time WebSocket updates.

        Yields:
            Progress dicts with type, phase, status, message, etc.
        """
        turn_id = turn.metadata.turn_id
        query = turn.metadata.query

        # Mark turn as processing
        self.turn_manager.update_turn(turn_id, state=TurnState.PROCESSING)

        yield {"type": "turn_started", "turn_id": turn_id, "session_id": self.session_id}

        # Create turn directory and context
        turn_dir = self.turn_manager.get_turn_dir(turn_id)
        context = ContextManager(turn_dir)
        context.create(query, self.session_id, turn_id)

        start_time = time.time()

        try:
            # Phase 0
            yield {"type": "phase_started", "phase": 0, "name": "query_analyzer"}
            analysis = await self._get_phase(0).execute(context, query=query)
            yield {"type": "phase_completed", "phase": 0, "name": "query_analyzer"}

            # Phase 1
            yield {"type": "phase_started", "phase": 1, "name": "reflection"}
            reflection = await self._get_phase(1).execute(context)
            yield {"type": "phase_completed", "phase": 1, "name": "reflection"}

            if reflection.decision == ReflectionDecision.CLARIFY:
                yield {
                    "type": "clarify",
                    "message": reflection.reasoning,
                    "turn_id": turn_id,
                }
                return

            # Phase 2
            yield {"type": "phase_started", "phase": 2, "name": "context_gatherer"}
            await self._get_phase(2).execute(context)
            yield {"type": "phase_completed", "phase": 2, "name": "context_gatherer"}

            # Phase 3
            yield {"type": "phase_started", "phase": 3, "name": "planner"}
            plan = await self._get_phase(3).execute(context)
            yield {"type": "phase_completed", "phase": 3, "name": "planner"}

            # Phase 4 (if needed)
            if plan.decision == PlannerAction.EXECUTE:
                yield {"type": "phase_started", "phase": 4, "name": "coordinator"}
                yield {"type": "progress", "phase": 4, "message": "Executing tools..."}
                await self._run_planner_coordinator_loop(turn, context, plan)
                yield {"type": "phase_completed", "phase": 4, "name": "coordinator"}

            # Phase 5
            yield {"type": "phase_started", "phase": 5, "name": "synthesis"}
            synthesis_result = await self._get_phase(5).execute(context)
            yield {"type": "phase_completed", "phase": 5, "name": "synthesis"}

            # Phase 6
            yield {"type": "phase_started", "phase": 6, "name": "validation"}
            validation_result = await self._get_phase(6).execute(context)
            yield {"type": "phase_completed", "phase": 6, "name": "validation"}

            # Phase 7
            yield {"type": "phase_started", "phase": 7, "name": "save"}
            await self._get_phase(7).execute(context, turn_number=turn_id)
            yield {"type": "phase_completed", "phase": 7, "name": "save"}

            # Complete
            duration_ms = int((time.time() - start_time) * 1000)
            yield {
                "type": "turn_complete",
                "turn_id": turn_id,
                "response": synthesis_result.full_response if synthesis_result else "",
                "quality": validation_result.confidence if validation_result else 0.0,
                "total_duration_ms": duration_ms,
            }

            # Update turn state
            self.turn_manager.update_turn(
                turn_id,
                state=TurnState.COMPLETED,
                response=synthesis_result.full_response if synthesis_result else "",
                quality=validation_result.confidence if validation_result else 0.0,
            )

        except Exception as e:
            logger.error(f"Streaming pipeline error: {e}", exc_info=True)
            yield {
                "type": "error",
                "message": str(e),
                "turn_id": turn_id,
            }
            self.turn_manager.update_turn(turn_id, state=TurnState.FAILED, error=str(e))


# Singleton instance
_pipeline_service: Optional[PipelineService] = None


def get_pipeline_service(
    session_id: str = "default",
    user_id: str = "default",
    mode: str = "chat",
) -> PipelineService:
    """Get pipeline service (creates new instance for each session)."""
    return PipelineService(session_id=session_id, user_id=user_id, mode=mode)
