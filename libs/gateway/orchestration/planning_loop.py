"""
Planning Loop - Phase 3-4 Planner-Executor-Coordinator logic.

Implements the unified planning loop that supports both:
1. New 3-tier architecture with STRATEGIC_PLAN
2. Legacy PLANNER_DECISION format for backward compatibility

Architecture Reference:
- architecture/main-system-patterns/phase3-planner.md
"""

import os
import re
import json
import logging
import asyncio
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument
    from libs.gateway.persistence.turn_manager import TurnDirectory

logger = logging.getLogger(__name__)


class PlanningLoopConfig:
    """Configuration for the planning loop."""

    def __init__(
        self,
        max_planning_iterations: int = 5,
        max_tool_calls: int = 20,
        research_timeout: int = 600,
        default_timeout: int = 300,
    ):
        self.max_planning_iterations = max_planning_iterations
        self.max_tool_calls = max_tool_calls
        self.research_timeout = research_timeout
        self.default_timeout = default_timeout


class PlanningLoopState:
    """Tracks state during planning loop execution."""

    def __init__(self):
        self.iteration = 0
        self.total_tool_calls = 0
        self.research_already_called = False
        self.research_exhausted = False
        self.previous_research_queries: Set[str] = set()
        self.failed_tools: Set[str] = set()
        self.goals_tracker: List[Dict[str, Any]] = []

        # Accumulated results
        self.all_tool_results: List[Dict[str, Any]] = []
        self.all_claims: List[Dict[str, Any]] = []
        self.all_rejected: List[Dict[str, Any]] = []
        self.step_log: List[str] = []


class PlanningLoop:
    """
    Executes the Phase 3-4 Planning Loop.

    Supports both:
    - New STRATEGIC_PLAN format with route_to: executor | synthesis | clarify | refresh_context
    - Legacy PLANNER_DECISION format with EXECUTE/COMPLETE actions
    """

    def __init__(
        self,
        llm_client: Any,
        doc_pack_builder: Any,
        response_parser: Any,
        config: Optional[PlanningLoopConfig] = None,
    ):
        self.llm_client = llm_client
        self.doc_pack_builder = doc_pack_builder
        self.response_parser = response_parser
        self.config = config or PlanningLoopConfig()

        # Callbacks for UnifiedFlow methods
        self._write_context_md: Optional[Callable] = None
        self._check_budget: Optional[Callable] = None
        self._inject_tooling_context: Optional[Callable] = None
        self._execute_single_tool: Optional[Callable] = None
        self._record_tool_call: Optional[Callable] = None
        self._summarize_tool_results: Optional[Callable] = None
        self._summarize_claims_batch: Optional[Callable] = None
        self._build_ticket_content: Optional[Callable] = None
        self._build_toolresults_content: Optional[Callable] = None
        self._build_ticket_from_plan: Optional[Callable] = None
        self._write_research_documents: Optional[Callable] = None
        self._update_knowledge_graph: Optional[Callable] = None
        self._emit_phase_event: Optional[Callable] = None
        self._update_section3_from_planner: Optional[Callable] = None
        self._update_section3_from_strategic_plan: Optional[Callable] = None
        self._initialize_plan_state: Optional[Callable] = None
        self._format_goals: Optional[Callable] = None
        self._phase4_executor_loop: Optional[Callable] = None
        self._refresh_context: Optional[Callable] = None

    def set_callbacks(
        self,
        write_context_md: Callable,
        check_budget: Callable,
        inject_tooling_context: Callable,
        execute_single_tool: Callable,
        record_tool_call: Callable,
        summarize_tool_results: Callable,
        summarize_claims_batch: Callable,
        build_ticket_content: Callable,
        build_toolresults_content: Callable,
        build_ticket_from_plan: Callable,
        write_research_documents: Callable,
        update_knowledge_graph: Callable,
        emit_phase_event: Callable,
        update_section3_from_planner: Callable,
        update_section3_from_strategic_plan: Callable,
        initialize_plan_state: Callable,
        format_goals: Callable,
        phase4_executor_loop: Callable,
        refresh_context: Optional[Callable] = None,
    ):
        """Set callbacks to UnifiedFlow methods."""
        self._write_context_md = write_context_md
        self._check_budget = check_budget
        self._inject_tooling_context = inject_tooling_context
        self._execute_single_tool = execute_single_tool
        self._record_tool_call = record_tool_call
        self._summarize_tool_results = summarize_tool_results
        self._summarize_claims_batch = summarize_claims_batch
        self._build_ticket_content = build_ticket_content
        self._build_toolresults_content = build_toolresults_content
        self._build_ticket_from_plan = build_ticket_from_plan
        self._write_research_documents = write_research_documents
        self._update_knowledge_graph = update_knowledge_graph
        self._emit_phase_event = emit_phase_event
        self._update_section3_from_planner = update_section3_from_planner
        self._update_section3_from_strategic_plan = update_section3_from_strategic_plan
        self._initialize_plan_state = initialize_plan_state
        self._format_goals = format_goals
        self._phase4_executor_loop = phase4_executor_loop
        self._refresh_context = refresh_context

    async def run(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        mode: str,
        pre_intent: str = "unknown",
        trace_id: str = "",
        recipe: Any = None,
    ) -> Tuple["ContextDocument", str, str]:
        """
        Execute the planning loop.

        Returns:
            (context_doc, ticket_content, toolresults_content)
        """
        logger.info("[PlanningLoop] Phase 3-4: Planner-Executor-Coordinator Loop")

        # Emit thinking event
        if self._emit_phase_event:
            await self._emit_phase_event(trace_id, 3, "active", "Planning research strategy and goals")

        # Load retry context
        skip_urls = self._load_retry_context(turn_dir)

        # Write context.md for Planner
        if self._write_context_md:
            self._write_context_md(turn_dir, context_doc)

        # Try new STRATEGIC_PLAN format first
        strategic_result = await self._try_strategic_plan(
            context_doc, turn_dir, mode, trace_id, recipe
        )
        if strategic_result is not None:
            return strategic_result

        # Fall through to legacy PLANNER_DECISION loop
        logger.info("[PlanningLoop] Legacy PLANNER_DECISION format - using existing loop")
        return await self._run_legacy_loop(
            context_doc, turn_dir, mode, trace_id, recipe, skip_urls
        )

    def _load_retry_context(self, turn_dir: "TurnDirectory") -> List[str]:
        """Load failed URLs from retry context."""
        skip_urls: List[str] = []
        retry_context_path = turn_dir.path / "retry_context.json"
        if retry_context_path.exists():
            try:
                with open(retry_context_path, "r") as f:
                    retry_ctx = json.load(f)
                skip_urls = retry_ctx.get("failed_urls", [])
                if skip_urls:
                    logger.info(f"[PlanningLoop] Will skip {len(skip_urls)} failed URLs")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[PlanningLoop] Could not read retry_context.json: {e}")
        return skip_urls

    async def _try_strategic_plan(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        mode: str,
        trace_id: str,
        recipe: Any,
        allow_refresh: bool = True,
        allow_executor: bool = True,
        post_execution_outputs: Optional[Tuple["ContextDocument", str, str]] = None,
    ) -> Optional[Tuple["ContextDocument", str, str]]:
        """
        Try to use the new STRATEGIC_PLAN format.
        Returns None if should fall through to legacy loop.
        """
        try:
            pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
            if self._inject_tooling_context:
                self._inject_tooling_context(pack, mode, include_tools=False, include_workflows=True)
            prompt = pack.as_prompt()

            # MIND role temp=0.6 for strategic planning
            # See: architecture/LLM-ROLES/llm-roles-reference.md
            temperature = recipe._raw_spec.get("llm_params", {}).get("temperature", 0.6)
            planner_response = await self.llm_client.call(
                prompt=prompt,
                role="planner",
                max_tokens=recipe.token_budget.output,
                temperature=temperature
            )

            strategic_plan = self.response_parser.parse_planner_decision(planner_response)

            # Check if this is new STRATEGIC_PLAN format
            if strategic_plan.get("_type") != "STRATEGIC_PLAN":
                return None  # Fall through to legacy loop

            route_to = strategic_plan.get("route_to", "synthesis")

            logger.info(f"[PlanningLoop] STRATEGIC_PLAN received - route_to: {route_to}")

            # Update §3 with the strategic plan
            if self._update_section3_from_strategic_plan:
                self._update_section3_from_strategic_plan(context_doc, strategic_plan)
            if self._initialize_plan_state:
                self._initialize_plan_state(
                    turn_dir,
                    strategic_plan.get("goals", []),
                    phase=3,
                    overwrite=True
                )

            fallback_ticket = post_execution_outputs[1] if post_execution_outputs else ""
            fallback_toolresults = post_execution_outputs[2] if post_execution_outputs else ""

            if route_to == "refresh_context":
                logger.info("[PlanningLoop] STRATEGIC_PLAN routes to refresh_context")
                if allow_refresh and self._refresh_context:
                    refreshed = await self._refresh_context(
                        context_doc=context_doc,
                        turn_dir=turn_dir,
                        mode=mode,
                        trace_id=trace_id
                    )
                    return await self._try_strategic_plan(
                        refreshed,
                        turn_dir,
                        mode,
                        trace_id,
                        recipe,
                        allow_refresh=False,
                        allow_executor=allow_executor,
                        post_execution_outputs=post_execution_outputs,
                    )
                return None

            if route_to == "synthesis":
                logger.info("[PlanningLoop] STRATEGIC_PLAN routes to synthesis - no executor needed")
                ticket_content = fallback_ticket
                if not ticket_content and self._build_ticket_from_plan:
                    ticket_content = self._build_ticket_from_plan(strategic_plan, [])
                toolresults_content = fallback_toolresults or "# Tool Results\n\n*(No tools executed - direct synthesis)*"
                return context_doc, ticket_content, toolresults_content

            elif route_to == "executor":
                if not allow_executor:
                    logger.warning("[PlanningLoop] Executor route requested after execution; returning prior outputs")
                    if post_execution_outputs:
                        return post_execution_outputs
                    return None
                logger.info("[PlanningLoop] STRATEGIC_PLAN routes to executor - using 3-tier architecture")
                if self._phase4_executor_loop:
                    executor_result = await self._phase4_executor_loop(
                        context_doc, strategic_plan, turn_dir, mode, trace_id=trace_id
                    )
                    if executor_result:
                        # Replan after execution for final routing
                        return await self._try_strategic_plan(
                            executor_result[0],
                            turn_dir,
                            mode,
                            trace_id,
                            recipe,
                            allow_refresh=allow_refresh,
                            allow_executor=False,
                            post_execution_outputs=executor_result,
                        ) or executor_result
                return None  # Fall through if no executor loop

            elif route_to == "clarify":
                logger.info("[PlanningLoop] STRATEGIC_PLAN routes to clarify")
                ticket_content = json.dumps(strategic_plan, indent=2)
                return context_doc, ticket_content, fallback_toolresults

            elif route_to == "brainstorm":
                logger.info("[PlanningLoop] STRATEGIC_PLAN routes to brainstorm")
                ticket_content = json.dumps(strategic_plan, indent=2)
                return context_doc, ticket_content, ""

            elif route_to == "self_extension" or strategic_plan.get("plan_type") == "self_extend" or strategic_plan.get("self_extension"):
                logger.info("[PlanningLoop] STRATEGIC_PLAN routes to self_extension - creating missing tools")
                return await self._handle_self_extension(
                    context_doc, strategic_plan, turn_dir, mode, trace_id
                )

            return None  # Unknown route, fall through to legacy

        except ValueError as e:
            # Parse error — Planner LLM returned non-STRATEGIC_PLAN format, fall through to legacy loop
            logger.warning(f"[PlanningLoop] Planner LLM parse error (Phase 3): {e} - falling through to legacy loop")
            return None

    async def _handle_self_extension(
        self,
        context_doc: "ContextDocument",
        strategic_plan: Dict[str, Any],
        turn_dir: "TurnDirectory",
        mode: str,
        trace_id: str
    ) -> Tuple["ContextDocument", str, str]:
        """
        Handle self-extension routing: generate missing tools then re-route to executor.

        This implements M2 from BENCHMARK_ALIGNMENT.md:
        1. Extract missing tools from strategic_plan
        2. Generate each tool using LLM
        3. Register tools in catalog
        4. Re-route to executor with updated plan
        """
        from libs.gateway.self_extension import generate_tool, get_tool_creator
        from libs.gateway.execution.tool_catalog import get_tool_catalog

        missing_tools = strategic_plan.get("missing_tools", [])
        if not missing_tools:
            logger.warning("[PlanningLoop] Self-extension triggered but no missing_tools specified")
            # Fall back to synthesis
            ticket_content = json.dumps(strategic_plan, indent=2)
            return context_doc, ticket_content, ""

        logger.info(f"[PlanningLoop] Self-extension: generating {len(missing_tools)} missing tools")

        # Track results
        created_tools: List[str] = []
        failed_tools: List[str] = []
        tool_creator = get_tool_creator()
        tool_catalog = get_tool_catalog()

        for tool_name in missing_tools:
            try:
                # Get description from plan if available
                tool_descriptions = strategic_plan.get("tool_descriptions", {})
                description = tool_descriptions.get(
                    tool_name,
                    f"Tool to perform {tool_name} operations"
                )

                # Derive workflow from tool name (e.g., "spreadsheet.read" -> "spreadsheet")
                workflow_name = tool_name.split(".")[0] if "." in tool_name else "utility"

                logger.info(f"[PlanningLoop] Generating tool: {tool_name} (workflow: {workflow_name})")

                # Step 1: Generate tool spec, code, tests using LLM
                generated = await generate_tool(
                    tool_name=tool_name,
                    description=description,
                    workflow_name=workflow_name,
                    requirements=f"Required for query: {context_doc.query[:200]}"
                )

                if not generated.success:
                    logger.error(f"[PlanningLoop] Tool generation failed for {tool_name}: {generated.error}")
                    failed_tools.append(tool_name)
                    continue

                # Step 2: Create tool (validate, backup, write, test, register)
                result = await tool_creator.create_tool(
                    workflow_name=workflow_name,
                    tool_name=tool_name,
                    spec_content=generated.spec,
                    impl_content=generated.code,
                    test_content=generated.tests,
                    skip_tests=False  # Always run tests for safety
                )

                if result.success:
                    logger.info(f"[PlanningLoop] Tool created: {tool_name} (registered: {result.registered})")
                    created_tools.append(tool_name)
                else:
                    logger.error(f"[PlanningLoop] Tool creation failed for {tool_name}: {result.error}")
                    failed_tools.append(tool_name)

            except Exception as e:
                logger.error(f"[PlanningLoop] Exception creating tool {tool_name}: {e}")
                failed_tools.append(tool_name)

        # Update context document with self-extension results
        extension_summary = f"""**Self-Extension Results:**
- Created: {created_tools if created_tools else 'None'}
- Failed: {failed_tools if failed_tools else 'None'}
"""
        context_doc.append_to_section(3, extension_summary)

        # Write self_extension.json to turn directory
        extension_log = {
            "triggered_by": "missing_tools",
            "missing_tools": missing_tools,
            "created": created_tools,
            "failed": failed_tools,
            "trace_id": trace_id
        }
        extension_path = turn_dir.path / "self_extension.json"
        extension_path.write_text(json.dumps(extension_log, indent=2))

        # If all tools failed, fall back to synthesis with explanation
        if not created_tools:
            logger.warning("[PlanningLoop] All tool creations failed - falling back to synthesis")
            ticket_content = json.dumps({
                "plan": strategic_plan,
                "self_extension_failed": True,
                "failed_tools": failed_tools
            }, indent=2)
            toolresults_content = "# Tool Results\n\n*(Self-extension failed - no tools created)*"
            return context_doc, ticket_content, toolresults_content

        # Remove created tools from missing_tools and re-route to executor
        remaining_missing = [t for t in missing_tools if t not in created_tools]
        if remaining_missing:
            logger.warning(f"[PlanningLoop] Some tools still missing: {remaining_missing}")
            strategic_plan["missing_tools"] = remaining_missing
        else:
            strategic_plan.pop("missing_tools", None)

        # Update route to executor now that tools are available
        strategic_plan["route_to"] = "executor"
        logger.info("[PlanningLoop] Self-extension complete - routing to executor")

        # Call executor loop with updated plan
        if self._phase4_executor_loop:
            return await self._phase4_executor_loop(
                context_doc, strategic_plan, turn_dir, mode, trace_id=trace_id
            )

        # Fallback if no executor configured
        ticket_content = json.dumps(strategic_plan, indent=2)
        return context_doc, ticket_content, ""

    async def _run_legacy_loop(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        mode: str,
        trace_id: str,
        recipe: Any,
        skip_urls: List[str]
    ) -> Tuple["ContextDocument", str, str]:
        """Run the legacy PLANNER_DECISION loop."""
        state = PlanningLoopState()

        # Initialize §4 and load previous results if RETRY
        self._initialize_section4(context_doc, turn_dir, state)

        # Last planner decision for finalization
        planner_decision: Dict[str, Any] = {}
        action = "COMPLETE"
        goals: List[Dict[str, Any]] = []

        # === PLANNING LOOP ===
        while state.iteration < self.config.max_planning_iterations:
            state.iteration += 1
            logger.info(f"[PlanningLoop] Iteration {state.iteration}/{self.config.max_planning_iterations}")

            # Write current context.md
            if self._write_context_md:
                self._write_context_md(turn_dir, context_doc)

            # Check budget
            if self._check_budget:
                self._check_budget(context_doc, recipe, f"Planning Iteration {state.iteration}")

            # Get planner decision
            planner_decision = await self._get_planner_decision(
                context_doc, turn_dir, mode, state, recipe
            )

            action = planner_decision.get("action", "COMPLETE")
            reasoning = planner_decision.get("reasoning", "")
            goals = planner_decision.get("goals", [])
            tools = planner_decision.get("tools", [])

            # Track goals
            if goals:
                state.goals_tracker = goals

            # Handle COMPLETE
            if action == "COMPLETE":
                logger.info(f"[PlanningLoop] COMPLETE at iteration {state.iteration}: {reasoning}")
                goals_str = self._format_goals(goals) if self._format_goals else str(goals)
                state.step_log.append(
                    f"### Iteration {state.iteration}: Complete\n"
                    f"**Action:** COMPLETE\n**Goals:** {goals_str}\n"
                    f"**Reasoning:** {reasoning}\n**Total Claims:** {len(state.all_claims)}"
                )
                if self._update_section3_from_planner:
                    self._update_section3_from_planner(context_doc, planner_decision, "synthesis")
                break

            # Handle EXECUTE
            if action == "EXECUTE":
                if not tools:
                    logger.warning("[PlanningLoop] EXECUTE with no tools - treating as COMPLETE")
                    state.step_log.append(
                        f"### Iteration {state.iteration}: Auto-Complete\n"
                        f"**Action:** EXECUTE (no tools)\n**Reasoning:** {reasoning}"
                    )
                    if self._update_section3_from_planner:
                        self._update_section3_from_planner(context_doc, planner_decision, "synthesis")
                    break

                await self._execute_tools(
                    context_doc, turn_dir, state, tools, skip_urls, goals, reasoning
                )

                # All tools skipped but we have claims - force complete
                if not state.all_tool_results and state.all_claims:
                    logger.info(f"[PlanningLoop] All tools skipped with {len(state.all_claims)} claims - forcing COMPLETE")
                    break

            elif action == "REFRESH_CONTEXT":
                # Planner wants context refresh but we're in the inner loop
                # (strategic-level refresh already happened or was blocked).
                # The planner has goals but chose the wrong route — convert to EXECUTE
                # so the executor can fetch the data via tools.
                logger.warning(
                    f"[PlanningLoop] REFRESH_CONTEXT in inner loop at iteration {state.iteration} "
                    f"— converting to EXECUTE (planner has {len(goals)} goals that need tool execution)"
                )
                if not tools:
                    # No tools specified — can't execute, treat as COMPLETE
                    logger.warning("[PlanningLoop] REFRESH_CONTEXT with no tools — treating as COMPLETE")
                    if self._update_section3_from_planner:
                        self._update_section3_from_planner(context_doc, planner_decision, "synthesis")
                    break

                await self._execute_tools(
                    context_doc, turn_dir, state, tools, skip_urls, goals, reasoning
                )

                if not state.all_tool_results and state.all_claims:
                    logger.info(f"[PlanningLoop] All tools skipped with {len(state.all_claims)} claims - forcing COMPLETE")
                    break

            else:
                # Unknown action - treat as COMPLETE
                logger.warning(f"[PlanningLoop] Unknown action '{action}' - treating as COMPLETE")
                break

        # === END PLANNING LOOP ===
        return await self._finalize(
            context_doc, turn_dir, state, trace_id, planner_decision, action, goals
        )

    def _initialize_section4(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        state: PlanningLoopState
    ):
        """Initialize §4 and load previous results if RETRY."""
        if context_doc.has_section(4):
            existing = context_doc.get_section(4)
            if "internet.research" in existing and "success" in existing:
                logger.info("[PlanningLoop] RETRY: Found existing research results in §4")
                # Extract previous query to prevent duplicates
                query_match = re.search(r'`internet\.research`.*?"query":\s*"([^"]+)"', existing)
                if query_match:
                    state.previous_research_queries.add(query_match.group(1).lower().strip())
                    logger.info("[PlanningLoop] RETRY: Previous query detected, will allow different queries")

                # Load previous tool results
                attempt_dirs = sorted(turn_dir.path.glob("attempt_*"), reverse=True)
                for attempt_dir in attempt_dirs:
                    prev_toolresults = attempt_dir / "toolresults.md"
                    if prev_toolresults.exists():
                        try:
                            content = prev_toolresults.read_text()
                            json_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', content)
                            if json_match:
                                prev_results = json.loads(json_match.group())
                                state.all_tool_results.extend(prev_results)
                                logger.info(f"[PlanningLoop] RETRY: Loaded {len(prev_results)} tool results from {attempt_dir.name}")
                                break
                        except Exception as e:
                            logger.warning(f"[PlanningLoop] Could not load previous tool results: {e}")
        else:
            context_doc.append_section(4, "Tool Execution", "*(No tools executed yet. This section will be populated when tools are called.)*")

    async def _get_planner_decision(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        mode: str,
        state: PlanningLoopState,
        recipe: Any
    ) -> Dict[str, Any]:
        """Get planner decision from LLM."""
        try:
            pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
            if self._inject_tooling_context:
                self._inject_tooling_context(pack, mode, include_tools=False, include_workflows=True)
            prompt = pack.as_prompt()

            # MIND role temp=0.6 for planning
            temperature = recipe._raw_spec.get("llm_params", {}).get("temperature", 0.6)
            llm_response = await self.llm_client.call(
                prompt=prompt,
                role="planner",
                max_tokens=recipe.token_budget.output,
                temperature=temperature
            )

            return self.response_parser.parse_planner_decision(llm_response)

        except Exception as e:
            logger.error(f"[PlanningLoop] Planner failed at iteration {state.iteration}: {e}")
            raise

    async def _execute_tools(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        state: PlanningLoopState,
        tools: List[Dict[str, Any]],
        skip_urls: List[str],
        goals: List[Dict[str, Any]],
        reasoning: str
    ):
        """Execute tools from planner decision."""
        step_tools_desc = []
        step_results = []

        for tool_spec in tools:
            tool_name = tool_spec.get("tool", "")
            tool_args = tool_spec.get("args", {})

            if not tool_name:
                continue

            # Check limits
            if state.total_tool_calls >= self.config.max_tool_calls:
                logger.warning(f"[PlanningLoop] Max tool calls ({self.config.max_tool_calls}) reached")
                step_tools_desc.append(f"- `{tool_name}`: SKIPPED (max tool calls)")
                break

            # Skip failed tools
            if tool_name in state.failed_tools:
                step_tools_desc.append(f"- `{tool_name}`: SKIPPED (previously failed)")
                continue

            # Research guard
            if tool_name == "internet.research":
                skip_reason = self._check_research_guard(state, tool_args)
                if skip_reason:
                    step_tools_desc.append(f"- `{tool_name}`: SKIPPED ({skip_reason})")
                    continue

            # Execute tool
            result = await self._execute_tool(
                context_doc, turn_dir, tool_name, tool_args, skip_urls, state
            )

            step_results.append(result)
            state.all_tool_results.append(result)

            # Track success/failure
            status = result.get("status", "executed")
            desc = result.get("description", "executed")
            step_tools_desc.append(f"- `{tool_name}`: {desc} ({status})")

            # Update state based on result
            self._track_result(tool_name, tool_args, result, context_doc, state)

        # Build iteration log entry
        results_summary = ""
        if self._summarize_tool_results and step_results:
            results_summary = self._summarize_tool_results(step_results)

        iteration_claims = sum(
            len(r.get("raw_result", {}).get("claims", []))
            for r in step_results
            if isinstance(r.get("raw_result"), dict)
        )

        goals_str = self._format_goals(goals) if self._format_goals else str(goals)
        step_entry = f"""### Iteration {state.iteration}
**Action:** EXECUTE
**Goals:** {goals_str}
**Reasoning:** {reasoning}
**Tools:**
{chr(10).join(step_tools_desc)}
**Results:**
{results_summary}
**Iteration Stats:** {len(step_results)} tools, {iteration_claims} claims extracted
"""
        state.step_log.append(step_entry)

        # Append results to §4
        context_doc.append_to_section(4, step_entry)

        logger.info(f"[PlanningLoop] Iteration {state.iteration} complete: {len(step_results)} tools executed")

    def _check_research_guard(
        self,
        state: PlanningLoopState,
        tool_args: Dict[str, Any]
    ) -> Optional[str]:
        """Check if research should be blocked. Returns skip reason or None."""
        current_query = tool_args.get("query", "").lower().strip()
        logger.info(f"[PlanningLoop] Research guard check: exhausted={state.research_exhausted}, already_called={state.research_already_called}, query='{current_query[:50]}...'")

        if state.research_exhausted:
            logger.warning("[PlanningLoop] Blocking research - previous attempt returned 0 findings")
            return "research exhausted - 0 findings"

        if state.research_already_called and current_query in state.previous_research_queries:
            logger.warning("[PlanningLoop] Blocking duplicate research (same query)")
            return "already called with same query"

        if state.research_already_called:
            logger.info(f"[PlanningLoop] Allowing new research query on RETRY: {current_query[:50]}...")

        return None

    async def _execute_tool(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        tool_name: str,
        tool_args: Dict[str, Any],
        skip_urls: List[str],
        state: PlanningLoopState
    ) -> Dict[str, Any]:
        """Execute a single tool with timeout."""
        if tool_name == "internet.research":
            timeout = int(os.environ.get("RESEARCH_TIMEOUT", self.config.research_timeout))
        else:
            timeout = self.config.default_timeout

        state.total_tool_calls += 1
        tool_start_time = time.time()
        tool_success = False

        try:
            if self._execute_single_tool:
                result = await asyncio.wait_for(
                    self._execute_single_tool(
                        tool_name, tool_args, context_doc, skip_urls=skip_urls, turn_dir=turn_dir
                    ),
                    timeout=timeout
                )
                tool_success = result.get("status") not in ("error", "failed", "timeout", "denied")
            else:
                result = {"status": "error", "error": "No tool executor configured"}
        except asyncio.TimeoutError:
            logger.warning(f"[PlanningLoop] Tool '{tool_name}' timed out after {timeout}s")
            result = {
                "tool": tool_name,
                "status": "timeout",
                "error": f"Tool execution timed out after {timeout} seconds",
                "claims": [],
                "raw_result": {}
            }
            state.failed_tools.add(tool_name)
            tool_success = False

        # Record metrics
        tool_duration_ms = int((time.time() - tool_start_time) * 1000)
        if self._record_tool_call:
            self._record_tool_call(tool_name, tool_success, tool_duration_ms)

        return result

    def _track_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Dict[str, Any],
        context_doc: "ContextDocument",
        state: PlanningLoopState
    ):
        """Track tool result and update state."""
        if result.get("status") in ("error", "failed", "timeout"):
            state.failed_tools.add(tool_name)
            if tool_name == "internet.research":
                state.research_exhausted = True
                logger.warning("[PlanningLoop] Research failed - marking as exhausted")
        elif tool_name == "internet.research":
            state.research_already_called = True
            query_used = tool_args.get("query", "").lower().strip()
            if query_used:
                state.previous_research_queries.add(query_used)

            # Check for 0 findings
            raw_result = result.get("result", {})
            findings = raw_result.get("findings", [])
            findings_count = len(findings) if findings else 0
            logger.info(f"[PlanningLoop] Research completed - findings: {findings_count}")

            if findings_count == 0:
                state.research_exhausted = True
                logger.warning("[PlanningLoop] Research returned 0 findings - marking as exhausted")

        # Collect claims
        for claim in result.get("claims", []):
            state.all_claims.append(claim)
            context_doc.add_claim(
                content=claim['content'],
                confidence=claim['confidence'],
                source=claim['source'],
                ttl_hours=claim.get('ttl_hours', 24)
            )

        # Collect rejected products
        raw_result = result.get("raw_result", {})
        if isinstance(raw_result, dict):
            state.all_rejected.extend(raw_result.get("rejected", []))

    async def _finalize(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        state: PlanningLoopState,
        trace_id: str,
        planner_decision: Dict[str, Any],
        action: str,
        goals: List[Dict[str, Any]]
    ) -> Tuple["ContextDocument", str, str]:
        """Finalize the planning loop and build output documents."""
        # Update §3 with final plan (if not already done)
        if action != "COMPLETE" and self._update_section3_from_planner:
            self._update_section3_from_planner(context_doc, planner_decision, "synthesis")

        # Initialize plan_state.json
        if self._initialize_plan_state:
            self._initialize_plan_state(
                turn_dir,
                goals if goals else [{"id": "GOAL_1", "description": context_doc.query}],
                phase=3,
                overwrite=True
            )

        # Check if we hit max iterations
        if state.iteration >= self.config.max_planning_iterations:
            logger.warning(f"[PlanningLoop] Max iterations ({self.config.max_planning_iterations}) reached")
            state.step_log.append(f"### Iteration {state.iteration}: Max Iterations\n**Decision:** Forced completion")

        # Build claims table
        claims_table = ["| Claim | Confidence | Source | TTL |", "|-------|------------|--------|-----|"]
        if state.all_claims:
            if self._summarize_claims_batch:
                claim_summaries = await self._summarize_claims_batch(state.all_claims, max_chars_per_claim=300)
            else:
                claim_summaries = [c['content'][:100] for c in state.all_claims]

            for i, claim in enumerate(state.all_claims):
                ttl = claim.get('ttl_hours', 24)
                summary = claim_summaries[i] if i < len(claim_summaries) else claim['content'][:100]
                source_display = claim['source'][:60] + "..." if len(claim['source']) > 60 else claim['source']
                claims_table.append(f"| {summary} | {claim['confidence']:.2f} | {source_display} | {ttl}h |")

        # Build rejected products section
        rejected_section = ""
        if state.all_rejected:
            rejected_lines = ["| Product | Vendor | Rejection Reason |", "|---------|--------|------------------|"]
            for rej in state.all_rejected[:10]:
                name = rej.get("name", "Unknown")[:40]
                vendor = rej.get("vendor", "unknown")
                reason = rej.get("rejection_reason", "Unknown")[:50]
                rejected_lines.append(f"| {name} | {vendor} | {reason} |")
            rejected_section = f"""
**Rejected Products ({len(state.all_rejected)} total):**
*Products considered but excluded - DO NOT include these in the response*
{chr(10).join(rejected_lines)}
"""

        # Determine status
        status = "success" if state.all_claims or state.iteration == 1 else "partial"

        # Calculate aggregate confidence
        from libs.gateway.validation.response_confidence import calculate_aggregate_confidence
        claim_confidences = [c.get("confidence", 0.8) for c in state.all_claims]
        goals_achieved = sum(1 for g in goals if g.get("status") == "achieved")
        goals_total = len(goals) if goals else 1

        aggregate_confidence = calculate_aggregate_confidence(
            claim_confidences=claim_confidences,
            goals_achieved=goals_achieved,
            goals_total=goals_total,
            has_tool_results=bool(state.all_tool_results),
            has_memory_context=bool(context_doc.get_section(2)),
        )

        # Format confidence breakdown
        confidence_section = f"""
**Aggregate Confidence:** {aggregate_confidence.score:.2f}
| Component | Score |
|-----------|-------|
| Claims | {aggregate_confidence.breakdown.get('claim_confidence', 0):.2f} |
| Sources | {aggregate_confidence.breakdown.get('source_quality', 0):.2f} |
| Goals | {aggregate_confidence.breakdown.get('goal_coverage', 0):.2f} |
| Evidence | {aggregate_confidence.breakdown.get('evidence_depth', 0):.2f} |"""

        if aggregate_confidence.issues:
            confidence_section += "\n\n**Confidence Issues:**\n" + "\n".join(f"- {i}" for i in aggregate_confidence.issues)

        # Final §4 content
        final_section = f"""## Planning Loop ({state.iteration} iterations)

**Status:** {status}
**Iterations:** {state.iteration}/{self.config.max_planning_iterations}
**Tool Calls:** {state.total_tool_calls}/{self.config.max_tool_calls}
{confidence_section}

{chr(10).join(state.step_log)}

---

**Claims Extracted:**
{chr(10).join(claims_table)}
{rejected_section}"""
        context_doc.update_section(4, final_section)

        # Build output documents
        if self._build_ticket_content:
            ticket_content = self._build_ticket_content(
                context_doc,
                {"tools": [r.get("tool", r.get("tool_name", "unknown")) for r in state.all_tool_results]}
            )
        else:
            ticket_content = ""

        if self._build_toolresults_content:
            toolresults_content = self._build_toolresults_content(context_doc, state.all_tool_results)
        else:
            toolresults_content = ""

        # Write research documents
        if self._write_research_documents:
            await self._write_research_documents(state.all_tool_results, context_doc)

        # Update knowledge graph
        if self._update_knowledge_graph:
            await self._update_knowledge_graph(state.all_tool_results, context_doc)

        # Write toolresults.md
        toolresults_path = turn_dir.doc_path("toolresults.md")
        toolresults_path.write_text(toolresults_content)
        logger.info(f"[PlanningLoop] Wrote toolresults.md ({len(toolresults_content)} chars)")

        # Emit completion events
        if self._emit_phase_event:
            await self._emit_phase_event(trace_id, 3, "completed", "Planning complete")
            await self._emit_phase_event(trace_id, 4, "completed", "Execution complete")
            await self._emit_phase_event(trace_id, 5, "completed", "Coordination complete")

        logger.info(f"[PlanningLoop] Complete: {state.iteration} iterations, {len(state.all_tool_results)} tools, {len(context_doc.claims)} claims")
        return context_doc, ticket_content, toolresults_content


def get_planning_loop(
    llm_client: Any,
    doc_pack_builder: Any,
    response_parser: Any,
    config: Optional[PlanningLoopConfig] = None
) -> PlanningLoop:
    """Factory function to create a PlanningLoop instance."""
    return PlanningLoop(
        llm_client=llm_client,
        doc_pack_builder=doc_pack_builder,
        response_parser=response_parser,
        config=config
    )
