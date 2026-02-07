"""
Request Handler - Main request orchestration logic.

Implements the full request handling flow through all phases:
- Phase 1: Query Analyzer (pre-run in UnifiedFlow)
- Phase 1.5: Query Analyzer Validator
- Phase 2.1/2.2/2.5: Context Retrieval/Synthesis/Validation
- Phase 3-5: Planning Loop
- Phase 6: Synthesis
- Phase 7: Validation
- Phase 8: Save

Architecture Reference:
- architecture/main-system-patterns/unified-flow.md
"""

import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from apps.services.gateway.services.thinking import ActionEvent, emit_action_event

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument
    from libs.gateway.persistence.turn_manager import TurnDirectory

logger = logging.getLogger(__name__)

# Constants
MAX_VALIDATION_RETRIES = 3
CONFIDENCE_THRESHOLD = 0.70


class RequestHandlerConfig:
    """Configuration for request handling."""

    def __init__(
        self,
        max_validation_retries: int = 3,
        confidence_threshold: float = 0.70,
    ):
        self.max_validation_retries = max_validation_retries
        self.confidence_threshold = confidence_threshold


class RequestHandler:
    """
    Handles the full request flow through all phases.

    This class orchestrates the entire request lifecycle:
    1. Query analysis and path setup
    2. Multi-task detection and Panda Loop routing
    3. Context gathering and validation
    4. Planning-Validation loop with retries
    5. Best-seen tracking for response quality
    6. Saving results
    """

    def __init__(
        self,
        llm_client: Any,
        config: Optional[RequestHandlerConfig] = None,
    ):
        self.llm_client = llm_client
        self.config = config or RequestHandlerConfig()

        # Callbacks for UnifiedFlow methods
        self._emit_phase_event: Optional[Callable] = None
        self._init_turn_metrics: Optional[Callable] = None
        self._start_phase: Optional[Callable] = None
        self._end_phase: Optional[Callable] = None
        self._record_decision: Optional[Callable] = None
        self._finalize_turn_metrics: Optional[Callable] = None

        # Phase callbacks
        self._phase1_reflection: Optional[Callable] = None
        self._phase2_context_gatherer: Optional[Callable] = None
        self._phase3_4_planning_loop: Optional[Callable] = None
        self._phase5_synthesis: Optional[Callable] = None
        self._phase6_validation: Optional[Callable] = None
        self._phase7_save: Optional[Callable] = None

        # Helper callbacks
        self._extract_clarification: Optional[Callable] = None
        self._archive_attempt: Optional[Callable] = None
        self._write_retry_context: Optional[Callable] = None
        self._invalidate_claims: Optional[Callable] = None
        self._update_plan_state_from_validation: Optional[Callable] = None

        # External dependencies
        self._get_turn_metrics: Optional[Callable] = None
        self._set_turn_metrics: Optional[Callable] = None

    def set_callbacks(
        self,
        emit_phase_event: Callable,
        init_turn_metrics: Callable,
        start_phase: Callable,
        end_phase: Callable,
        record_decision: Callable,
        finalize_turn_metrics: Callable,
        phase1_reflection: Callable,
        phase2_context_gatherer: Callable,
        phase3_4_planning_loop: Callable,
        phase5_synthesis: Callable,
        phase6_validation: Callable,
        phase7_save: Callable,
        extract_clarification: Callable,
        archive_attempt: Callable,
        write_retry_context: Callable,
        invalidate_claims: Callable,
        update_plan_state_from_validation: Callable,
        get_turn_metrics: Callable,
        set_turn_metrics: Callable,
    ):
        """Set callbacks to UnifiedFlow methods."""
        self._emit_phase_event = emit_phase_event
        self._init_turn_metrics = init_turn_metrics
        self._start_phase = start_phase
        self._end_phase = end_phase
        self._record_decision = record_decision
        self._finalize_turn_metrics = finalize_turn_metrics
        self._phase1_reflection = phase1_reflection
        self._phase2_context_gatherer = phase2_context_gatherer
        self._phase3_4_planning_loop = phase3_4_planning_loop
        self._phase5_synthesis = phase5_synthesis
        self._phase6_validation = phase6_validation
        self._phase7_save = phase7_save
        self._extract_clarification = extract_clarification
        self._archive_attempt = archive_attempt
        self._write_retry_context = write_retry_context
        self._invalidate_claims = invalidate_claims
        self._update_plan_state_from_validation = update_plan_state_from_validation
        self._get_turn_metrics = get_turn_metrics
        self._set_turn_metrics = set_turn_metrics

    async def run(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        mode: str,
        intent: str,
        trace_id: str,
        turn_number: int,
        session_id: str,
        query_analysis: Any,
        start_time: float,
        request_turn_saver: Any,
        panda_loop_handler: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Execute the full request handling flow.

        Args:
            context_doc: The context document
            turn_dir: Turn directory for this request
            mode: "chat" or "code"
            intent: Pre-classified intent
            trace_id: Trace identifier
            turn_number: Turn number
            session_id: Session identifier
            query_analysis: Result from Phase 0
            start_time: Request start timestamp
            request_turn_saver: TurnSaver for this request
            panda_loop_handler: Optional handler for multi-task requests

        Returns:
            Dict with response, context_doc, and metadata
        """
        # Initialize metrics
        self._set_turn_metrics(self._init_turn_metrics())

        retry_count = 0
        response = ""
        validation_result = None
        ticket_content = None
        toolresults_content = None

        # Best-seen tracking (Poetiq pattern)
        best_seen_response: Optional[str] = None
        best_seen_confidence: float = 0.0
        best_seen_attempt: int = 0

        # === Check for multi-task routing ===
        if query_analysis.is_multi_task and query_analysis.task_breakdown and panda_loop_handler:
            return await panda_loop_handler(
                query_analysis, context_doc, turn_number, session_id, mode, trace_id
            )

        # === PHASE 1.5 + PHASE 2.x: Query Analysis Validation and context gathering ===
        logger.info("[RequestHandler] Starting Phase 1.5 + Phase 2.1/2.2/2.5 (validation + context)")

        # Phase 1.5: Query Analysis Validation (fast gate - PROCEED or CLARIFY)
        phase1_start = time.time()
        query_preview = context_doc.query[:200] if context_doc.query else ""
        section0_raw = context_doc.get_section(0) if context_doc.has_section(0) else ""
        await self._emit_phase_event(
            trace_id, 1, "active", "Validating query analysis (Phase 1.5)",
            input_summary=f"Query: {query_preview}",
            input_raw=section0_raw,
        )
        self._start_phase("phase1_5_validation")
        context_doc.update_execution_state(1, "Query Analysis Validation (Phase 1.5)")
        context_doc, decision = await self._phase1_reflection(context_doc, turn_dir)
        context_doc.record_decision(decision)
        self._end_phase("phase1_5_validation")
        self._record_decision("query_analysis_validation", decision)
        phase1_duration = int((time.time() - phase1_start) * 1000)
        section1_raw = context_doc.get_section(1) if context_doc.has_section(1) else ""
        await self._emit_phase_event(
            trace_id, 1, "completed",
            f"Decision: {decision}",
            confidence=0.9 if decision == "PROCEED" else 0.7,
            duration_ms=phase1_duration,
            details={"decision": decision},
            output_summary=f"Decision: {decision}",
            output_raw=section1_raw,
        )
        await emit_action_event(ActionEvent(
            trace_id=trace_id, action_type="decision",
            label=f"Reflection: {decision}",
            success=decision == "PROCEED",
        ))

        if decision == "CLARIFY":
            clarification = self._extract_clarification(context_doc)
            return {
                "response": clarification,
                "needs_clarification": True,
                "context_doc": context_doc,
                "turn_number": turn_number,
                "trace_id": trace_id,
                "unified_flow": True
            }

        # Phase 2: Context Gatherer
        phase2_start = time.time()
        await self._emit_phase_event(
            trace_id, 2, "active", "Gathering context from prior turns and memory",
            input_summary=f"Query: {query_preview}",
        )
        self._start_phase("phase2_context_gatherer")
        context_doc.update_execution_state(2, "Context Gatherer")
        context_doc = await self._phase2_context_gatherer(context_doc)
        self._end_phase("phase2_context_gatherer")
        phase2_duration = int((time.time() - phase2_start) * 1000)
        num_sources = len(context_doc.source_references) if hasattr(context_doc, 'source_references') else 0
        # Build brief source list for summary
        source_labels = []
        if hasattr(context_doc, 'source_references'):
            for ref in context_doc.source_references[:5]:
                if hasattr(ref, 'summary'):
                    source_labels.append(ref.summary[:60] if ref.summary else str(ref))
                elif hasattr(ref, 'path'):
                    source_labels.append(str(ref.path)[-60:])
        source_list_str = ", ".join(source_labels) if source_labels else "none"
        section2_raw = context_doc.get_section(2) if context_doc.has_section(2) else ""
        await self._emit_phase_event(
            trace_id, 2, "completed",
            f"Found {num_sources} relevant sources",
            confidence=0.85,
            duration_ms=phase2_duration,
            details={"sources_found": num_sources},
            output_summary=f"Found {num_sources} sources: {source_list_str}",
            output_raw=section2_raw,
        )
        await emit_action_event(ActionEvent(
            trace_id=trace_id, action_type="memory",
            label=f"Context gathered: {num_sources} sources",
            detail=source_list_str[:200],
            success=num_sources > 0,
        ))

        # === PHASE 2.5: Constraint Extraction ===
        self._extract_and_write_constraints(context_doc, turn_dir)

        # === PHASE 3-4-5-6: Unified Planning-Validation loop ===
        while retry_count < self.config.max_validation_retries:
            logger.info(f"[RequestHandler] Planning-Validation iteration {retry_count + 1}/{self.config.max_validation_retries}")

            # Phase 3-4: Unified Planning Loop
            phase34_start = time.time()
            await self._emit_phase_event(
                trace_id, 3, "active",
                f"Planning strategy (iteration {retry_count + 1})",
                details={"iteration": retry_count + 1},
                input_summary=f"{num_sources} sources, mode={mode}, iteration {retry_count + 1}",
            )
            await emit_action_event(ActionEvent(
                trace_id=trace_id, action_type="route",
                label=f"Planning iteration {retry_count + 1}",
            ))
            self._start_phase("phase3_4_planning_loop")
            context_doc.update_execution_state(
                phase=3,
                phase_name="Planner-Coordinator",
                iteration=retry_count + 1,
                max_iterations=self.config.max_validation_retries
            )
            context_doc, ticket_content, toolresults_content = await self._phase3_4_planning_loop(
                context_doc, turn_dir, mode, intent, trace_id=trace_id
            )
            self._end_phase("phase3_4_planning_loop")
            phase34_duration = int((time.time() - phase34_start) * 1000)

            # Check if planning was blocked
            coordinator_blocked = False
            section4 = context_doc.get_section(4) if context_doc.has_section(4) else ""
            if "BLOCKED" in section4 or "too many tool failures" in section4.lower():
                coordinator_blocked = True
                logger.warning(f"[RequestHandler] Planning was BLOCKED due to tool failures")

            # Emit planner completion event
            num_tools = len(context_doc.claims) if hasattr(context_doc, 'claims') else 0
            section3_raw = context_doc.get_section(3) if context_doc.has_section(3) else ""
            await self._emit_phase_event(
                trace_id, 3, "completed",
                f"Planning complete, {num_tools} claims gathered",
                confidence=0.8 if not coordinator_blocked else 0.4,
                duration_ms=phase34_duration,
                details={"claims": num_tools, "blocked": coordinator_blocked},
                output_summary=f"{num_tools} claims gathered, blocked={coordinator_blocked}",
                output_raw=section3_raw,
            )

            # Phase 6: Synthesis
            phase6_start = time.time()
            num_claims = len(context_doc.claims) if hasattr(context_doc, 'claims') else 0
            await self._emit_phase_event(
                trace_id, 6, "active", "Generating response from gathered context",
                input_summary=f"Sections 0-4, {num_claims} claims",
                input_raw=toolresults_content[:2000] if toolresults_content else "",
            )
            self._start_phase("phase6_synthesis")
            context_doc.update_execution_state(6, "Synthesis")
            context_doc, response = await self._phase5_synthesis(context_doc, turn_dir, mode)
            self._end_phase("phase6_synthesis")
            phase6_duration = int((time.time() - phase6_start) * 1000)
            resp_len = len(response) if response else 0
            await self._emit_phase_event(
                trace_id, 6, "completed",
                f"Response generated ({resp_len} chars)",
                confidence=0.85,
                duration_ms=phase6_duration,
                details={"response_length": resp_len},
                output_summary=f"Response: {response[:300]}..." if response and len(response) > 300 else f"Response: {response}" if response else "No response",
                output_raw=response[:2000] if response else "",
            )

            # Check for synthesizer INVALID
            synthesis_returned_invalid = False
            invalid_reason = None
            if response and response.strip().startswith('{'):
                try:
                    parsed = json.loads(response.strip())
                    if parsed.get("_type") == "INVALID":
                        synthesis_returned_invalid = True
                        invalid_reason = parsed.get("reason", "Synthesizer could not generate valid response")
                        logger.warning(f"[RequestHandler] Synthesizer returned INVALID: {invalid_reason}")
                except (json.JSONDecodeError, ValueError):
                    pass

            # Check if INVALID is due to research failure
            research_failed_keywords = [
                "no findings", "no successful tool", "research failed",
                "couldn't find", "could not find", "unable to find",
                "no results", "zero results", "empty results",
                "multiple attempts", "repeated attempts", "search failed"
            ]
            invalid_reason_lower = invalid_reason.lower() if invalid_reason else ""
            is_research_failure = any(kw in invalid_reason_lower for kw in research_failed_keywords)

            if is_research_failure:
                logger.warning(f"[RequestHandler] Synthesizer INVALID due to research failure - NOT retrying")
                response = f"I wasn't able to find the information you requested. {invalid_reason}"
                synthesis_returned_invalid = False
                logger.info("[RequestHandler] Research failure - skipping validation")

            if synthesis_returned_invalid and retry_count < self.config.max_validation_retries:
                logger.info(f"[RequestHandler] Synthesizer INVALID - forcing RETRY")

                # Import here to avoid circular dependency
                from libs.gateway.validation.validation_result import ValidationResult, ValidationFailureContext

                validation_result = ValidationResult(
                    decision="RETRY",
                    issues=[f"Synthesizer returned INVALID: {invalid_reason}"],
                    confidence=0.0,
                    revision_hints="Research needed - synthesizer could not answer from available context",
                    failure_context=ValidationFailureContext(
                        reason="synthesis_invalid",
                        failed_urls=[],
                        failed_claims=[],
                        mismatches=[],
                        retry_count=retry_count + 1
                    )
                )

                await self._archive_attempt(turn_dir, retry_count)
                await self._write_retry_context(
                    turn_dir, validation_result.failure_context,
                    session_id=session_id, turn_number=turn_number
                )
                await self._invalidate_claims(validation_result.failure_context)

                section7_content = f"""**Decision:** RETRY
**Confidence:** 0.00

### Issues
- Synthesizer returned INVALID: {invalid_reason}

### Suggested Fixes
- Research needed to gather missing evidence.
"""
                if context_doc.has_section(7):
                    attempt_header = f"\n\n---\n\n#### Attempt {retry_count + 1}\n"
                    context_doc.append_to_section(7, attempt_header + section7_content)
                else:
                    section_with_header = f"#### Attempt {retry_count + 1}\n{section7_content}"
                    context_doc.append_section(7, "Validation", section_with_header)

                retry_count += 1
                continue

            # Phase 7: Validation
            phase7_start = time.time()
            await self._emit_phase_event(
                trace_id, 7, "active", "Validating response quality and accuracy",
                input_summary=f"Response to validate ({len(response) if response else 0} chars)",
                input_raw=response[:2000] if response else "",
            )
            self._start_phase("phase7_validation")
            context_doc.update_execution_state(7, "Validation")
            context_doc, response, validation_result = await self._phase6_validation(
                context_doc, turn_dir, response, mode, retry_count
            )
            self._update_plan_state_from_validation(turn_dir, validation_result)
            if validation_result:
                context_doc.record_decision(validation_result.decision)
            self._end_phase("phase7_validation")
            self._record_decision("validation", validation_result.decision if validation_result else "UNKNOWN")
            phase7_duration = int((time.time() - phase7_start) * 1000)
            val_decision = validation_result.decision if validation_result else "UNKNOWN"
            val_confidence = validation_result.confidence if validation_result else 0.0
            val_issues = validation_result.issues if validation_result else []
            section7_output = context_doc.get_section(7) if context_doc.has_section(7) else ""
            await self._emit_phase_event(
                trace_id, 7, "completed",
                f"Validation: {val_decision}",
                confidence=val_confidence,
                duration_ms=phase7_duration,
                details={"decision": val_decision, "issues": val_issues},
                output_summary=f"{val_decision}, confidence: {val_confidence:.2f}, issues: {len(val_issues)}",
                output_raw=section7_output,
            )
            await emit_action_event(ActionEvent(
                trace_id=trace_id, action_type="decision",
                label=f"Validation: {val_decision}",
                detail=f"confidence={val_confidence:.2f}",
                success=val_decision == "APPROVE",
            ))

            # Best-seen tracking
            if validation_result and response:
                current_confidence = validation_result.confidence
                if current_confidence > best_seen_confidence:
                    best_seen_response = response
                    best_seen_confidence = current_confidence
                    best_seen_attempt = retry_count + 1
                    logger.info(
                        f"[RequestHandler] Best-seen updated at attempt {best_seen_attempt}: "
                        f"confidence {best_seen_confidence:.2f}"
                    )

            # Confidence threshold check
            if validation_result and validation_result.decision == "APPROVE":
                confidence = validation_result.confidence
                checks = getattr(validation_result, 'checks', {}) or {}

                query_terms_missing = checks.get('query_terms_in_context') == False
                term_substitution = checks.get('no_term_substitution') == False

                should_override = False
                override_reason = []

                if confidence < self.config.confidence_threshold:
                    should_override = True
                    override_reason.append(f"confidence {confidence:.2f} below threshold {self.config.confidence_threshold}")

                if query_terms_missing:
                    should_override = True
                    override_reason.append("query terms missing from context")

                if term_substitution:
                    should_override = True
                    override_reason.append("term substitution detected")

                if should_override and retry_count < self.config.max_validation_retries:
                    logger.warning(
                        f"[RequestHandler] OVERRIDING APPROVE to RETRY: {', '.join(override_reason)}"
                    )
                    from libs.gateway.validation.validation_result import ValidationResult, ValidationFailureContext
                    validation_result = ValidationResult(
                        decision="RETRY",
                        issues=validation_result.issues + [f"Override: {', '.join(override_reason)}"],
                        confidence=confidence,
                        revision_hints=f"Research needed - {', '.join(override_reason)}",
                        failure_context=ValidationFailureContext(
                            reason="confidence_override",
                            failed_urls=[],
                            failed_claims=[],
                            mismatches=[],
                            retry_count=retry_count + 1
                        )
                    )

            # Handle validation result
            if validation_result.decision == "APPROVE":
                logger.info(f"[RequestHandler] Validation APPROVED on iteration {retry_count + 1}")

                retry_context_path = turn_dir.path / "retry_context.json"
                if retry_context_path.exists():
                    retry_context_path.unlink()
                    logger.debug("[RequestHandler] Cleaned up retry_context.json")

                break

            elif validation_result.decision == "RETRY":
                if coordinator_blocked:
                    logger.warning(f"[RequestHandler] Skipping RETRY - coordinator was BLOCKED")
                    break

                logger.info(f"[RequestHandler] Validation RETRY - looping back (iteration {retry_count + 1})")

                await self._archive_attempt(turn_dir, retry_count)
                await self._write_retry_context(
                    turn_dir, validation_result.failure_context,
                    session_id=session_id, turn_number=turn_number
                )
                await self._invalidate_claims(validation_result.failure_context)

                # Handle workflow_mismatch correction
                suggested_fixes = []
                if validation_result.failure_context:
                    suggested_fixes = validation_result.failure_context.suggested_fixes or []
                for fix in suggested_fixes:
                    if isinstance(fix, str) and fix.startswith("workflow_mismatch:"):
                        workflow_match = re.search(r'Should have used (\w+)', fix)
                        if workflow_match:
                            correct_workflow = workflow_match.group(1)
                            logger.info(f"[RequestHandler] RETRY: Correcting workflow to {correct_workflow}")
                            context_doc.workflow = correct_workflow
                            context_doc.workflow_reason = f"Corrected by validation: {fix}"

                retry_count += 1
                continue

            elif validation_result.decision == "FAIL":
                logger.error(f"[RequestHandler] Validation FAILED: {validation_result.issues}")

                # Best-seen recovery
                current_confidence = validation_result.confidence if validation_result else 0.0
                if best_seen_response and best_seen_confidence > current_confidence:
                    logger.info(
                        f"[RequestHandler] Using best-seen response from attempt {best_seen_attempt}"
                    )
                    response = best_seen_response
                else:
                    is_invalid_response = (
                        not response or
                        response.strip() == "" or
                        '{"_type": "INVALID"}' in response or
                        response.strip().startswith('{') and '_type' in response
                    )

                    if is_invalid_response:
                        logger.warning(f"[RequestHandler] Replacing invalid response with fallback message")
                        response = (
                            "I apologize, but I wasn't able to complete your request successfully. "
                            "The information I gathered wasn't sufficient to provide a reliable response. "
                            "Could you try rephrasing your question, or would you like me to try again?"
                        )

                break

            else:
                logger.warning(f"[RequestHandler] Unknown validation decision: {validation_result.decision}")
                break

        # Check if we exhausted retries
        if retry_count >= self.config.max_validation_retries:
            logger.warning(f"[RequestHandler] Max retries ({self.config.max_validation_retries}) reached")

            current_confidence = validation_result.confidence if validation_result else 0.0
            if best_seen_response and best_seen_confidence > current_confidence:
                logger.info(
                    f"[RequestHandler] Max retries hit - using best-seen from attempt {best_seen_attempt}"
                )
                response = best_seen_response

        # Malformed response protection
        is_malformed_response = False
        if response:
            stripped = response.strip()
            if stripped.startswith('{') and stripped.endswith('}'):
                try:
                    parsed = json.loads(stripped)
                    if parsed.get("_type") == "INVALID":
                        is_malformed_response = True
                    elif "solver_self_history" in parsed and "answer" not in parsed:
                        is_malformed_response = True
                    elif parsed.get("_type") and parsed.get("_type") != "ANSWER":
                        is_malformed_response = True
                except (json.JSONDecodeError, ValueError):
                    pass
        else:
            is_malformed_response = True

        if is_malformed_response:
            logger.warning(f"[RequestHandler] Replacing malformed response with fallback message")
            response = (
                f"I apologize, but I wasn't able to find reliable information to answer your question. "
                f"The research I attempted didn't return sufficient results. "
                f"Would you like me to try a different approach, or could you rephrase your question?"
            )

        # Phase 8: Save
        self._start_phase("phase8_save")
        context_doc.update_execution_state(8, "Save")
        validation_passed = validation_result.decision == "APPROVE" if validation_result else False
        saved_turn_dir = await self._phase7_save(
            context_doc=context_doc,
            response=response,
            ticket_content=ticket_content,
            toolresults_content=toolresults_content,
            validation_result=validation_result
        )
        self._end_phase("phase8_save")

        # Finalize metrics
        turn_metrics = self._get_turn_metrics()
        turn_metrics["retries"] = retry_count
        turn_metrics["claims_count"] = len(context_doc.claims)
        self._set_turn_metrics(turn_metrics)

        quality_score = validation_result.confidence if validation_result else 0.0
        validation_outcome = validation_result.decision if validation_result else "UNKNOWN"
        final_metrics = self._finalize_turn_metrics(quality_score, validation_outcome)
        request_turn_saver.save_metrics(saved_turn_dir, final_metrics)

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"[RequestHandler] Request complete in {elapsed_ms:.0f}ms (turn={turn_number}, retries={retry_count})")

        # Emit completion event
        await self._emit_phase_event(
            trace_id, 8, "completed",
            f"Request complete ({elapsed_ms:.0f}ms)",
            confidence=quality_score,
            duration_ms=int(elapsed_ms),
            details={
                "turn_number": turn_number,
                "retries": retry_count,
                "validation_passed": validation_passed,
                "response_length": len(response) if response else 0
            },
            output_summary=f"Turn {turn_number} saved, validation={'passed' if validation_passed else 'failed'}, {elapsed_ms:.0f}ms",
        )

        return {
            "response": response,
            "context_doc": context_doc,
            "turn_dir": str(saved_turn_dir),
            "turn_number": turn_number,
            "trace_id": trace_id,
            "elapsed_ms": elapsed_ms,
            "validation_passed": validation_passed,
            "retry_count": retry_count,
            "unified_flow": True
        }


    def _extract_and_write_constraints(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory"
    ) -> None:
        """
        Extract constraints from query and write to turn directory + §2.

        This is Phase 2.5 - runs after reflection, before planning.
        Extracted constraints are:
        1. Written to constraints.json for tool executor and validator
        2. Appended to §1 (Query Analysis Validation) as a visible constraints block
        """
        from libs.gateway.constraints import get_constraint_extractor

        extractor = get_constraint_extractor()
        query = context_doc.query
        gathered_context = context_doc.get_section(2) or ""

        constraints = extractor.extract_from_query(query, context=gathered_context)

        # Always write constraints.json (even if empty, for contract compliance)
        extractor.write_constraints(turn_dir, constraints, query)

        # Format and append constraints block to §1
        constraints_block = self._format_constraints_block(constraints)
        if context_doc.has_section(1):
            context_doc.append_to_section(1, constraints_block, separator="\n\n")
        else:
            # §1 should exist from validation, but handle edge case
            context_doc.append_section(1, "Query Analysis Validation", constraints_block)

        if constraints:
            logger.info(
                f"[RequestHandler] Phase 2.5: Extracted {len(constraints)} constraints, "
                f"wrote to constraints.json and §1"
            )
        else:
            logger.debug("[RequestHandler] Phase 2.5: No constraints extracted (empty block written)")

    def _format_constraints_block(self, constraints: List[Dict[str, Any]]) -> str:
        """
        Format constraints as a markdown block for §1.

        Returns a "### Constraints" section with a table of extracted constraints.
        """
        lines = ["### Constraints", ""]

        if not constraints:
            lines.append("_No explicit constraints extracted from query._")
            return "\n".join(lines)

        # Table header
        lines.append("| ID | Type | Limit | Source |")
        lines.append("|-----|------|-------|--------|")

        # Table rows
        for c in constraints:
            cid = c.get("id", "?")
            ctype = c.get("type", "unknown")

            # Format the limit based on constraint type
            if ctype == "file_size":
                max_bytes = c.get("max_bytes", 0)
                original_val = c.get("original_value", "?")
                original_unit = c.get("original_unit", "bytes")
                limit = f"{original_val} {original_unit} ({max_bytes} bytes)"
            else:
                limit = str(c.get("value", c.get("max_bytes", "?")))

            source = c.get("source", "extracted")
            lines.append(f"| {cid} | {ctype} | {limit} | {source} |")

        return "\n".join(lines)


def get_request_handler(
    llm_client: Any,
    config: Optional[RequestHandlerConfig] = None,
) -> RequestHandler:
    """Factory function to create a RequestHandler."""
    return RequestHandler(llm_client, config)
