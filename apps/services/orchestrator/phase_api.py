"""Phase API Endpoints for n8n Integration.

Architecture Reference:
    architecture/main-system-patterns/phase*.md
    architecture/integrations/N8N_INTEGRATION.md (to be created)

This module exposes each pipeline phase as an independent REST endpoint,
enabling external orchestration tools like n8n to control the pipeline flow.

Design Principles:
    - Each phase is stateless - context comes from request or is loaded by turn_id
    - Phases can be called independently with inline state OR by turn_id reference
    - Response includes formatted section content for chaining in n8n
    - Metadata tracks execution time and tokens for monitoring

Endpoints:
    POST /phases/0-query-analyzer   - Phase 0: Query Analyzer
    POST /phases/1-reflection       - Phase 1: Reflection
    POST /phases/2-context-gatherer - Phase 2: Context Gatherer
    POST /phases/3-planner          - Phase 3: Planner
    POST /phases/4-coordinator      - Phase 4: Coordinator
    POST /phases/5-synthesis        - Phase 5: Synthesis
    POST /phases/6-validation       - Phase 6: Validation
    POST /phases/7-save             - Phase 7: Save
"""

import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from libs.core.logging_config import get_logger
from libs.core.exceptions import PhaseError, InterventionRequired
from libs.document_io.context_manager import ContextManager

from apps.phases.phase0_query_analyzer import QueryAnalyzer
from apps.phases.phase1_reflection import Reflection
from apps.phases.phase2_context_gatherer import ContextGatherer
from apps.phases.phase3_planner import Planner
from apps.phases.phase5_synthesis import Synthesis
from apps.phases.phase6_validation import Validation

from apps.services.orchestrator.phase_schemas import (
    PhaseStatus,
    PhaseMetadata,
    TurnSummary,
    Phase0Request,
    Phase0Response,
    Phase1Request,
    Phase1Response,
    Phase2Request,
    Phase2Response,
    Phase3Request,
    Phase3Response,
    Phase4Request,
    Phase4Response,
    Phase5Request,
    Phase5Response,
    Phase6Request,
    Phase6Response,
    Phase7Request,
    Phase7Response,
)
from apps.services.orchestrator.services.turn_manager import get_turn_manager

logger = get_logger(__name__)

# Create router
router = APIRouter(prefix="/phases", tags=["phases"])


# =============================================================================
# Helper Functions
# =============================================================================

def _get_turn_dir(turn_id: int, user_id: str = "default") -> Path:
    """Get the turn directory path."""
    # Use new consolidated path structure under obsidian_memory/Users/
    return Path(f"panda_system_docs/obsidian_memory/Users/{user_id}/turns/turn_{turn_id:06d}")


def _create_temp_context(user_id: str = "default") -> tuple[ContextManager, Path]:
    """Create a temporary context manager for inline mode.

    Returns:
        Tuple of (ContextManager, temp_dir_path)
    """
    import tempfile
    temp_dir = Path(tempfile.mkdtemp(prefix="phase_"))
    return ContextManager(temp_dir), temp_dir


def _format_section_0(analysis) -> str:
    """Format Phase 0 output as section 0 content."""
    content_ref = ""
    if analysis.content_reference:
        ref = analysis.content_reference
        content_ref = f"""
**Content Reference:**
- Title: {ref.title}
- Type: {ref.content_type}
- Site: {ref.site}
- Source Turn: {ref.source_turn}
"""

    return f"""## 0. User Query

**Original:** {analysis.original_query}
**Resolved:** {analysis.resolved_query}
**Was Resolved:** {analysis.was_resolved}
**Query Type:** {analysis.query_type.value}
{content_ref}
**Reasoning:** {analysis.reasoning}
"""


def _format_section_1(result) -> str:
    """Format Phase 1 output as section 1 content."""
    clarify = ""
    if result.decision.value == "CLARIFY":
        clarify = f"\n**Clarification Question:** {result.reasoning}"

    return f"""## 1. Reflection Decision

**Decision:** {result.decision.value}
**Confidence:** {result.confidence}
**Query Type:** {result.query_type or 'N/A'}
**Is Follow-up:** {result.is_followup}

**Reasoning:** {result.reasoning}
{clarify}
"""


def _format_section_2(gathered) -> str:
    """Format Phase 2 output as section 2 content."""
    # Format preferences
    prefs = ""
    if gathered.session_preferences:
        prefs = "\n".join(
            f"- **{k}:** {v}"
            for k, v in gathered.session_preferences.items()
        )
    else:
        prefs = "None loaded"

    # Format relevant turns
    turns = ""
    if gathered.relevant_turns:
        turns = "\n".join(
            f"| {t.turn_number or '?'} | {t.relevance:.2f} | {t.summary[:50]}... |"
            for t in gathered.relevant_turns
        )
        turns = f"""
| Turn | Relevance | Summary |
|------|-----------|---------|
{turns}
"""
    else:
        turns = "None found"

    # Format cached research
    research = ""
    if gathered.cached_research:
        research = f"""
**Topic:** {gathered.cached_research.get('topic', 'N/A')}
**Quality:** {gathered.cached_research.get('quality', 'N/A')}
**Age:** {gathered.cached_research.get('age_hours', 'N/A')} hours
"""
    else:
        research = "None available"

    return f"""## 2. Gathered Context

### Session Preferences
{prefs}

### Relevant Prior Turns
{turns}

### Cached Research Intelligence
{research}

### Sufficiency Assessment
{gathered.sufficiency_assessment}

### Source References
{chr(10).join(f'- {s}' for s in gathered.source_references) or 'None'}
"""


def _format_section_3(plan) -> str:
    """Format Phase 3 output as section 3 content."""
    # Format goals
    goals = ""
    if plan.goals:
        goals = "\n".join(
            f"| {g.id} | {g.description} | {g.status.value} | {', '.join(g.dependencies) or '-'} |"
            for g in plan.goals
        )
        goals = f"""
### Goals Identified

| ID | Description | Status | Dependencies |
|----|-------------|--------|--------------|
{goals}
"""

    # Format tool requests
    tools = ""
    if plan.tool_requests:
        tools = "\n".join(
            f"- **{t.tool}**: {t.args}"
            for t in plan.tool_requests
        )
        tools = f"""
### Tool Requests
{tools}
"""

    route = plan.route.value if plan.route else "N/A"

    return f"""## 3. Task Plan

**Decision:** {plan.decision.value}
**Route To:** {route}
**Current Focus:** {plan.current_focus or 'N/A'}

**Reasoning:** {plan.reasoning}
{goals}
{tools}
"""


def _format_section_5(result) -> str:
    """Format Phase 5 output as section 5 content."""
    citations = ""
    if result.citations:
        citations = "\n".join(f"- {c}" for c in result.citations)
        citations = f"""
### Citations
{citations}
"""

    checklist = ""
    if result.validation_checklist:
        checklist = "\n".join(
            f"- [{('x' if v else ' ')}] {k}"
            for k, v in result.validation_checklist.items()
        )
        checklist = f"""
### Validation Checklist
{checklist}
"""

    return f"""## 5. Synthesis

### Response Preview
{result.response_preview}

### Full Response
{result.full_response}
{citations}
{checklist}
"""


def _format_section_6(result) -> str:
    """Format Phase 6 output as section 6 content."""
    # Format checks
    checks = ""
    if result.checks:
        checks = "\n".join(
            f"- [{('PASS' if c.passed else 'FAIL')}] {c.name}: {c.notes or 'OK'}"
            for c in result.checks
        )
        checks = f"""
### Validation Checks
{checks}
"""

    # Format issues
    issues = ""
    if result.issues:
        issues = "\n".join(f"- {i}" for i in result.issues)
        issues = f"""
### Issues Found
{issues}
"""

    revision = ""
    if result.revision_hints:
        revision = f"""
### Revision Hints
{result.revision_hints}
"""

    return f"""## 6. Validation

**Decision:** {result.decision.value}
**Confidence:** {result.confidence}
**Overall Quality:** {result.overall_quality or 'N/A'}

**Reasoning:** {result.reasoning or 'N/A'}
{checks}
{issues}
{revision}
"""


# =============================================================================
# Phase 0: Query Analyzer
# =============================================================================

@router.post("/0-query-analyzer", response_model=Phase0Response)
async def phase_0_query_analyzer(request: Phase0Request) -> Phase0Response:
    """Execute Phase 0: Query Analyzer.

    Resolves pronouns/references and classifies the query type.

    Can be called:
    - Inline: With raw_query and turn_summaries in request body
    - By reference: With turn_id to load existing context
    """
    start_time = time.time()

    try:
        # Create context manager
        if request.turn_id:
            turn_dir = _get_turn_dir(request.turn_id)
            if not turn_dir.exists():
                raise HTTPException(404, f"Turn {request.turn_id} not found")
            context = ContextManager(turn_dir)
        else:
            context, temp_dir = _create_temp_context()
            # Initialize with query
            context.create(
                raw_query=request.raw_query,
                session_id=request.session_id or "api",
                turn_number=0,
            )

        # Convert turn summaries to dict format
        turn_summaries = [
            {
                "turn": ts.turn_id,
                "summary": ts.summary,
                "content_refs": ts.content_refs,
                "topics": ts.topics,
            }
            for ts in request.turn_summaries
        ]

        # Execute phase
        analyzer = QueryAnalyzer(mode=request.mode)
        analysis = await analyzer.execute(
            context=context,
            raw_query=request.raw_query,
            turn_summaries=turn_summaries,
        )

        # Calculate execution time
        exec_time_ms = (time.time() - start_time) * 1000

        # Format section content
        section_0_content = _format_section_0(analysis)

        return Phase0Response(
            analysis=analysis,
            metadata=PhaseMetadata(
                phase_number=0,
                phase_name="query_analyzer",
                execution_time_ms=exec_time_ms,
                status=PhaseStatus.SUCCESS,
            ),
            section_0_content=section_0_content,
        )

    except PhaseError as e:
        exec_time_ms = (time.time() - start_time) * 1000
        logger.error(f"Phase 0 error: {e}")
        raise HTTPException(500, detail=str(e))

    except InterventionRequired as e:
        exec_time_ms = (time.time() - start_time) * 1000
        logger.warning(f"Phase 0 intervention required: {e}")
        raise HTTPException(
            503,
            detail={
                "error": "intervention_required",
                "message": str(e),
                "context": e.context,
            },
        )


# =============================================================================
# Phase 1: Reflection
# =============================================================================

@router.post("/1-reflection", response_model=Phase1Response)
async def phase_1_reflection(request: Phase1Request) -> Phase1Response:
    """Execute Phase 1: Reflection.

    Decides if query is clear enough to proceed (PROCEED/CLARIFY gate).

    Can be called:
    - Inline: With section_0_content from Phase 0 response
    - By reference: With turn_id to load existing context
    """
    start_time = time.time()

    try:
        # Create context manager
        if request.turn_id:
            turn_dir = _get_turn_dir(request.turn_id)
            if not turn_dir.exists():
                raise HTTPException(404, f"Turn {request.turn_id} not found")
            context = ContextManager(turn_dir)
        else:
            # Need to create context from section_0_content
            if not request.section_0_content:
                raise HTTPException(
                    400,
                    "Either turn_id or section_0_content required",
                )
            context, temp_dir = _create_temp_context()
            # Write section 0 content directly
            context._content = request.section_0_content
            context._save()

        # Execute phase
        reflection = Reflection(mode=request.mode)
        result = await reflection.execute(context=context)

        # Calculate execution time
        exec_time_ms = (time.time() - start_time) * 1000

        # Format section content
        section_1_content = _format_section_1(result)

        # Determine clarification question
        clarification_question = None
        if result.decision.value == "CLARIFY":
            clarification_question = result.reasoning

        return Phase1Response(
            result=result,
            metadata=PhaseMetadata(
                phase_number=1,
                phase_name="reflection",
                execution_time_ms=exec_time_ms,
                status=PhaseStatus.SUCCESS,
            ),
            should_proceed=result.decision.value == "PROCEED",
            clarification_question=clarification_question,
            section_1_content=section_1_content,
        )

    except PhaseError as e:
        logger.error(f"Phase 1 error: {e}")
        raise HTTPException(500, detail=str(e))


# =============================================================================
# Phase 2: Context Gatherer
# =============================================================================

@router.post("/2-context-gatherer", response_model=Phase2Response)
async def phase_2_context_gatherer(request: Phase2Request) -> Phase2Response:
    """Execute Phase 2: Context Gatherer.

    Gathers relevant context from memory, prior turns, and cache.

    Can be called:
    - Inline: With section_0_content and section_1_content
    - By reference: With turn_id to load existing context
    """
    start_time = time.time()

    try:
        # Create context manager
        if request.turn_id:
            turn_dir = _get_turn_dir(request.turn_id)
            if not turn_dir.exists():
                raise HTTPException(404, f"Turn {request.turn_id} not found")
            context = ContextManager(turn_dir)
        else:
            # Need sections 0-1
            if not request.section_0_content or not request.section_1_content:
                raise HTTPException(
                    400,
                    "Either turn_id or section_0_content + section_1_content required",
                )
            context, temp_dir = _create_temp_context()
            # Combine sections
            combined = f"{request.section_0_content}\n\n{request.section_1_content}"
            context._content = combined
            context._save()

        # Execute phase
        gatherer = ContextGatherer(mode=request.mode)
        gathered = await gatherer.execute(
            context=context,
            session_id=request.session_id,
            user_id=request.user_id,
        )

        # Calculate execution time
        exec_time_ms = (time.time() - start_time) * 1000

        # Format section content
        section_2_content = _format_section_2(gathered)

        # Assess sufficiency
        has_sufficient = bool(
            gathered.cached_research
            or gathered.relevant_turns
            or gathered.session_preferences
        )

        return Phase2Response(
            gathered=gathered,
            metadata=PhaseMetadata(
                phase_number=2,
                phase_name="context_gatherer",
                execution_time_ms=exec_time_ms,
                status=PhaseStatus.SUCCESS,
            ),
            has_sufficient_context=has_sufficient,
            section_2_content=section_2_content,
        )

    except PhaseError as e:
        logger.error(f"Phase 2 error: {e}")
        raise HTTPException(500, detail=str(e))


# =============================================================================
# Phase 3: Planner
# =============================================================================

@router.post("/3-planner", response_model=Phase3Response)
async def phase_3_planner(request: Phase3Request) -> Phase3Response:
    """Execute Phase 3: Planner.

    Plans tasks and determines routing (coordinator, synthesis, or clarify).

    Can be called:
    - Inline: With accumulated section contents
    - By reference: With turn_id to load existing context
    """
    start_time = time.time()

    try:
        # Create context manager
        if request.turn_id:
            turn_dir = _get_turn_dir(request.turn_id)
            if not turn_dir.exists():
                raise HTTPException(404, f"Turn {request.turn_id} not found")
            context = ContextManager(turn_dir)
        else:
            # Need sections 0-2 (and optionally 4-6 on RETRY)
            if not all([
                request.section_0_content,
                request.section_1_content,
                request.section_2_content,
            ]):
                raise HTTPException(
                    400,
                    "Either turn_id or section_0/1/2_content required",
                )
            context, temp_dir = _create_temp_context()

            # Combine sections
            sections = [
                request.section_0_content,
                request.section_1_content,
                request.section_2_content,
            ]

            # Add RETRY sections if present
            if request.is_retry:
                if request.section_4_content:
                    sections.append(request.section_4_content)
                if request.section_5_content:
                    sections.append(request.section_5_content)
                if request.section_6_content:
                    sections.append(request.section_6_content)

            context._content = "\n\n".join(sections)
            context._save()

        # Execute phase
        planner = Planner(mode=request.mode)
        plan = await planner.execute(
            context=context,
            session_id=request.session_id,
            is_retry=request.is_retry,
            attempt_number=request.attempt_number,
        )

        # Calculate execution time
        exec_time_ms = (time.time() - start_time) * 1000

        # Format section content
        section_3_content = _format_section_3(plan)

        # Build ticket JSON if routing to coordinator
        ticket_json = None
        if plan.route and plan.route.value == "coordinator":
            ticket_json = {
                "_type": "TICKET",
                "route_to": "coordinator",
                "is_retry": request.is_retry,
                "attempt": request.attempt_number,
                "goals": [
                    {
                        "id": g.id,
                        "description": g.description,
                        "status": g.status.value,
                        "dependencies": g.dependencies,
                    }
                    for g in plan.goals
                ],
                "tool_requests": [
                    {
                        "tool": t.tool,
                        "args": t.args,
                        "goal_id": t.goal_id,
                    }
                    for t in plan.tool_requests
                ],
            }

        return Phase3Response(
            plan=plan,
            metadata=PhaseMetadata(
                phase_number=3,
                phase_name="planner",
                execution_time_ms=exec_time_ms,
                status=PhaseStatus.SUCCESS,
            ),
            route_to=plan.route or "synthesis",
            ticket_json=ticket_json,
            section_3_content=section_3_content,
        )

    except PhaseError as e:
        logger.error(f"Phase 3 error: {e}")
        raise HTTPException(500, detail=str(e))


# =============================================================================
# Phase 4: Coordinator (Stub - requires tool infrastructure)
# =============================================================================

@router.post("/4-coordinator", response_model=Phase4Response)
async def phase_4_coordinator(request: Phase4Request) -> Phase4Response:
    """Execute Phase 4: Coordinator.

    Executes tools based on the Planner's ticket.

    NOTE: This is a stub. Full implementation requires the tool execution
    infrastructure (MCP tools, browser, etc.). For n8n integration, consider
    using separate tool endpoints or the full pipeline endpoint.
    """
    start_time = time.time()

    # For now, return a stub response
    # Full implementation would call Coordinator phase with tool infrastructure
    from libs.core.models import ToolExecutionResult

    exec_time_ms = (time.time() - start_time) * 1000

    return Phase4Response(
        result=ToolExecutionResult(
            iteration=1,
            action="DONE",
            reasoning="Stub response - Phase 4 requires tool infrastructure",
            tool_results=[],
            claims_extracted=[],
        ),
        metadata=PhaseMetadata(
            phase_number=4,
            phase_name="coordinator",
            execution_time_ms=exec_time_ms,
            status=PhaseStatus.SUCCESS,
        ),
        action="DONE",
        needs_more_iterations=False,
        section_4_content="## 4. Tool Execution\n\n(Stub - no tools executed)",
        toolresults_content=None,
    )


# =============================================================================
# Phase 5: Synthesis
# =============================================================================

@router.post("/5-synthesis", response_model=Phase5Response)
async def phase_5_synthesis(request: Phase5Request) -> Phase5Response:
    """Execute Phase 5: Synthesis.

    Generates user-facing response from accumulated context.

    Can be called:
    - Inline: With accumulated section contents
    - By reference: With turn_id to load existing context
    """
    start_time = time.time()

    try:
        # Create context manager
        if request.turn_id:
            turn_dir = _get_turn_dir(request.turn_id)
            if not turn_dir.exists():
                raise HTTPException(404, f"Turn {request.turn_id} not found")
            context = ContextManager(turn_dir)
        else:
            # Need at least sections 0-3
            if not all([
                request.section_0_content,
                request.section_1_content,
                request.section_2_content,
                request.section_3_content,
            ]):
                raise HTTPException(
                    400,
                    "Either turn_id or section_0/1/2/3_content required",
                )
            context, temp_dir = _create_temp_context()

            # Combine sections
            sections = [
                request.section_0_content,
                request.section_1_content,
                request.section_2_content,
                request.section_3_content,
            ]
            if request.section_4_content:
                sections.append(request.section_4_content)

            context._content = "\n\n".join(sections)
            context._save()

        # Execute phase
        synthesis = Synthesis(mode=request.mode)
        result = await synthesis.execute(
            context=context,
            toolresults=request.toolresults_content,
            is_revision=request.is_revision,
            revision_hints=request.revision_hints,
        )

        # Calculate execution time
        exec_time_ms = (time.time() - start_time) * 1000

        # Format section content
        section_5_content = _format_section_5(result)

        return Phase5Response(
            result=result,
            metadata=PhaseMetadata(
                phase_number=5,
                phase_name="synthesis",
                execution_time_ms=exec_time_ms,
                status=PhaseStatus.SUCCESS,
            ),
            response=result.full_response,
            section_5_content=section_5_content,
        )

    except PhaseError as e:
        logger.error(f"Phase 5 error: {e}")
        raise HTTPException(500, detail=str(e))


# =============================================================================
# Phase 6: Validation
# =============================================================================

@router.post("/6-validation", response_model=Phase6Response)
async def phase_6_validation(request: Phase6Request) -> Phase6Response:
    """Execute Phase 6: Validation.

    Validates the synthesized response for quality.

    Can be called:
    - Inline: With accumulated section contents
    - By reference: With turn_id to load existing context
    """
    start_time = time.time()

    try:
        # Create context manager
        if request.turn_id:
            turn_dir = _get_turn_dir(request.turn_id)
            if not turn_dir.exists():
                raise HTTPException(404, f"Turn {request.turn_id} not found")
            context = ContextManager(turn_dir)
        else:
            # Need sections 0-5
            if not all([
                request.section_0_content,
                request.section_1_content,
                request.section_2_content,
                request.section_3_content,
                request.section_5_content,
            ]):
                raise HTTPException(
                    400,
                    "Either turn_id or section_0/1/2/3/5_content required",
                )
            context, temp_dir = _create_temp_context()

            # Combine sections
            sections = [
                request.section_0_content,
                request.section_1_content,
                request.section_2_content,
                request.section_3_content,
            ]
            if request.section_4_content:
                sections.append(request.section_4_content)
            sections.append(request.section_5_content)

            context._content = "\n\n".join(sections)
            context._save()

        # Execute phase
        validation = Validation(mode=request.mode)
        result = await validation.execute(
            context=context,
            toolresults=request.toolresults_content,
        )

        # Calculate execution time
        exec_time_ms = (time.time() - start_time) * 1000

        # Format section content
        section_6_content = _format_section_6(result)

        return Phase6Response(
            result=result,
            metadata=PhaseMetadata(
                phase_number=6,
                phase_name="validation",
                execution_time_ms=exec_time_ms,
                status=PhaseStatus.SUCCESS,
            ),
            decision=result.decision,
            is_approved=result.decision.value == "APPROVE",
            needs_retry=result.decision.value == "RETRY",
            needs_revision=result.decision.value == "REVISE",
            section_6_content=section_6_content,
        )

    except PhaseError as e:
        logger.error(f"Phase 6 error: {e}")
        raise HTTPException(500, detail=str(e))


# =============================================================================
# Phase 7: Save (Procedural)
# =============================================================================

@router.post("/7-save", response_model=Phase7Response)
async def phase_7_save(request: Phase7Request) -> Phase7Response:
    """Execute Phase 7: Save.

    Persists the completed turn. This is procedural (no LLM).

    Can be called:
    - Inline: With all section contents
    - By reference: With turn_id to save existing turn
    """
    start_time = time.time()

    try:
        turn_manager = get_turn_manager(request.user_id)

        # Get or create turn
        if request.turn_id:
            turn = turn_manager.get_turn(request.turn_id)
            if not turn:
                raise HTTPException(404, f"Turn {request.turn_id} not found")
            turn_id = request.turn_id
        else:
            # Create new turn
            turn = turn_manager.create_turn(
                query=request.final_response[:100],  # Preview
                session_id=request.session_id,
            )
            turn_id = turn.metadata.turn_id

        # Get turn directory
        turn_dir = _get_turn_dir(turn_id, request.user_id)
        turn_dir.mkdir(parents=True, exist_ok=True)

        # Write context.md with all sections
        context = ContextManager(turn_dir)
        sections = []
        if request.section_0_content:
            sections.append(request.section_0_content)
        if request.section_1_content:
            sections.append(request.section_1_content)
        if request.section_2_content:
            sections.append(request.section_2_content)
        if request.section_3_content:
            sections.append(request.section_3_content)
        if request.section_4_content:
            sections.append(request.section_4_content)
        if request.section_5_content:
            sections.append(request.section_5_content)
        if request.section_6_content:
            sections.append(request.section_6_content)

        if sections:
            context._content = "\n\n".join(sections)
            context._save()

        # Update turn state
        turn_manager.update_turn(
            turn_id,
            response=request.final_response,
            quality=request.quality_score,
        )

        # Calculate execution time
        exec_time_ms = (time.time() - start_time) * 1000

        return Phase7Response(
            turn_id=turn_id,
            turn_path=str(turn_dir),
            metadata=PhaseMetadata(
                phase_number=7,
                phase_name="save",
                execution_time_ms=exec_time_ms,
                status=PhaseStatus.SUCCESS,
            ),
            index_updated=True,
            summary_generated=False,  # Summary generation is async
        )

    except Exception as e:
        logger.error(f"Phase 7 error: {e}")
        raise HTTPException(500, detail=str(e))
