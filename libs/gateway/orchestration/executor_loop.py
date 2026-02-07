"""
Executor Loop - Phase 4 Executor orchestration logic.

Implements the Executor loop that:
1. Receives goals from Planner (strategic_plan)
2. Issues natural language commands to Coordinator
3. Coordinator translates commands to tool calls
4. Results flow back, Executor tracks goal progress
5. Loops until COMPLETE or BLOCKED

Architecture Reference:
- architecture/main-system-patterns/phase4-executor.md
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

import yaml

from apps.services.gateway.services.thinking import ActionEvent, emit_action_event

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument
    from libs.gateway.persistence.turn_manager import TurnDirectory

logger = logging.getLogger(__name__)


class ExecutorLoopConfig:
    """Configuration for the executor loop."""

    def __init__(
        self,
        max_executor_iterations: int = 10,
        max_tool_calls: int = 20,
        max_research_calls: int = 2,
    ):
        self.max_executor_iterations = max_executor_iterations
        self.max_tool_calls = max_tool_calls
        self.max_research_calls = max_research_calls


class ExecutorLoopState:
    """Tracks state during executor loop execution."""

    def __init__(self):
        self.iteration = 0
        self.total_tool_calls = 0
        self.total_research_calls = 0
        self.tool_failures = 0
        self.parse_failures = 0
        self.consecutive_commands = 0
        self.all_tool_results: List[Dict[str, Any]] = []
        self.all_claims: List[Dict[str, Any]] = []
        self.step_log: List[str] = []
        self.completed_research_queries: Set[str] = set()
        self.trace_id: str = ""


class ExecutorLoop:
    """
    Executes the Phase 4 Executor Loop.

    The Executor operates in an iterative loop:
    - COMMAND: Issue a natural language command to Coordinator
    - ANALYZE: Reason about accumulated results (no tool call)
    - COMPLETE: Goals achieved, proceed to synthesis
    - BLOCKED: Cannot proceed (unrecoverable)
    """

    def __init__(
        self,
        llm_client: Any,
        config: Optional[ExecutorLoopConfig] = None,
    ):
        self.llm_client = llm_client
        self.config = config or ExecutorLoopConfig()

        # Callbacks for UnifiedFlow methods
        self._write_context_md: Optional[Callable] = None
        self._emit_phase_event: Optional[Callable] = None
        self._call_executor_llm: Optional[Callable] = None
        self._format_goals: Optional[Callable] = None
        self._format_executor_analysis: Optional[Callable] = None
        self._append_to_section4: Optional[Callable] = None
        self._try_workflow_execution: Optional[Callable] = None
        self._coordinator_execute_command: Optional[Callable] = None
        self._format_executor_command_result: Optional[Callable] = None
        self._build_ticket_from_plan: Optional[Callable] = None
        self._build_toolresults_md: Optional[Callable] = None
        self._execute_single_tool: Optional[Callable] = None

    def set_callbacks(
        self,
        write_context_md: Callable,
        emit_phase_event: Callable,
        call_executor_llm: Callable,
        format_goals: Callable,
        format_executor_analysis: Callable,
        append_to_section4: Callable,
        try_workflow_execution: Callable,
        coordinator_execute_command: Callable,
        format_executor_command_result: Callable,
        build_ticket_from_plan: Callable,
        build_toolresults_md: Callable,
        execute_single_tool: Callable,
    ):
        """Set callbacks to UnifiedFlow methods."""
        self._write_context_md = write_context_md
        self._emit_phase_event = emit_phase_event
        self._call_executor_llm = call_executor_llm
        self._format_goals = format_goals
        self._format_executor_analysis = format_executor_analysis
        self._append_to_section4 = append_to_section4
        self._try_workflow_execution = try_workflow_execution
        self._coordinator_execute_command = coordinator_execute_command
        self._format_executor_command_result = format_executor_command_result
        self._build_ticket_from_plan = build_ticket_from_plan
        self._build_toolresults_md = build_toolresults_md
        self._execute_single_tool = execute_single_tool

    async def run(
        self,
        context_doc: "ContextDocument",
        strategic_plan: Dict[str, Any],
        turn_dir: "TurnDirectory",
        mode: str,
        trace_id: str = "",
    ) -> Tuple["ContextDocument", str, str]:
        """
        Execute the executor loop.

        Returns:
            (context_doc, ticket_content, toolresults_content)
        """
        logger.info("[ExecutorLoop] Phase 4: Executor Loop")

        # Emit thinking events
        await self._emit_phase_event(trace_id, 3, "completed", "Planning complete")
        await self._emit_phase_event(trace_id, 4, "active", "Executing research and tool calls")

        # State tracking
        state = ExecutorLoopState()
        state.trace_id = trace_id

        # Initialize §4 if not present
        if not context_doc.has_section(4):
            context_doc.append_section(4, "Execution Progress", "*(Executor starting...)*")

        # === EXECUTOR LOOP ===
        while state.iteration < self.config.max_executor_iterations:
            state.iteration += 1
            logger.info(f"[ExecutorLoop] Iteration {state.iteration}/{self.config.max_executor_iterations}")

            # Write current context.md for Executor to read
            self._write_context_md(turn_dir, context_doc)

            # Call Executor LLM — parse failures handled gracefully to preserve results
            try:
                executor_decision = await self._call_executor_llm(
                    context_doc, strategic_plan, turn_dir, state.iteration
                )
            except (ValueError, KeyError) as e:
                state.parse_failures += 1
                logger.warning(
                    f"[ExecutorLoop] Executor parse failure at iteration {state.iteration} "
                    f"({state.parse_failures} total): {e}"
                )
                state.step_log.append(
                    f"### Iteration {state.iteration}: Parse Failure\n"
                    f"**Error:** LLM response could not be parsed\n"
                    f"**Detail:** {str(e)[:200]}"
                )
                if state.parse_failures >= 2:
                    logger.warning("[ExecutorLoop] 2 parse failures — exiting loop with accumulated results")
                    break
                continue  # Retry on first failure

            action = executor_decision.get("action", "COMPLETE")
            command = executor_decision.get("command", "")
            workflow_hint = executor_decision.get("workflow_hint")
            analysis = executor_decision.get("analysis", {})
            goals_progress = executor_decision.get("goals_progress", [])
            reasoning = executor_decision.get("reasoning", "")
            tool_spec = executor_decision.get("tool_spec")
            tool_code = executor_decision.get("tool_code")
            workflow_spec = executor_decision.get("workflow_spec")

            # === HANDLE COMPLETE ===
            if action == "COMPLETE":
                logger.info(f"[ExecutorLoop] COMPLETE at iteration {state.iteration}: {reasoning}")
                state.step_log.append(
                    f"### Iteration {state.iteration}: Complete\n"
                    f"**Action:** COMPLETE\n"
                    f"**Goals:** {self._format_goals(goals_progress)}\n"
                    f"**Reasoning:** {reasoning}"
                )
                break

            # === HANDLE CREATE_TOOL / CREATE_WORKFLOW ===
            if action == "CREATE_WORKFLOW":
                state.consecutive_commands = 0
                created = await self._handle_create_workflow(
                    workflow_spec=workflow_spec,
                    context_doc=context_doc,
                    turn_dir=turn_dir,
                    state=state,
                    goals_progress=goals_progress,
                    reasoning=reasoning,
                )
                if not created:
                    break
                continue

            if action == "CREATE_TOOL":
                logger.warning(f"[ExecutorLoop] CREATE_TOOL requested at iteration {state.iteration}")
                payload = tool_spec or {}
                state.step_log.append(
                    f"### Iteration {state.iteration}: Self-Extension Request\n"
                    f"**Action:** CREATE_TOOL\n"
                    f"**Payload:** {payload}\n"
                    f"**Reasoning:** {reasoning or 'Self-extension requested'}"
                )
                self._append_to_section4(
                    context_doc,
                    "\n**⚠️ CREATE_TOOL REQUESTED:** Tools are created only as part of "
                    "CREATE_WORKFLOW in this system. Use CREATE_WORKFLOW with tool_specs.\n"
                )
                break

            # === HANDLE BLOCKED ===
            if action == "BLOCKED":
                logger.warning(f"[ExecutorLoop] BLOCKED at iteration {state.iteration}: {reasoning}")
                state.step_log.append(
                    f"### Iteration {state.iteration}: Blocked\n"
                    f"**Action:** BLOCKED\n"
                    f"**Reason:** {reasoning}"
                )
                break

            # === HANDLE ANALYZE ===
            if action == "ANALYZE":
                logger.info(f"[ExecutorLoop] ANALYZE at iteration {state.iteration}")
                state.consecutive_commands = 0  # Reset on non-COMMAND
                analysis_content = self._format_executor_analysis(analysis, goals_progress, state.iteration)
                state.step_log.append(analysis_content)
                self._append_to_section4(context_doc, analysis_content)
                continue

            # === HANDLE COMMAND ===
            if action == "COMMAND":
                state.consecutive_commands += 1

                # Enforce consecutive COMMAND limit (spec §10: max 5)
                if state.consecutive_commands > 5:
                    logger.warning(f"[ExecutorLoop] 5 consecutive COMMANDs — forcing ANALYZE")
                    state.consecutive_commands = 0
                    self._append_to_section4(
                        context_doc,
                        f"\n**⚠️ ANALYZE REQUIRED:** 5 consecutive commands issued. "
                        f"Review accumulated results before issuing more commands.\n"
                    )
                    continue

                await self._handle_command(
                    command,
                    context_doc,
                    turn_dir,
                    mode,
                    state,
                    goals_progress,
                    workflow_hint=workflow_hint,
                )

                # Check tool failure limit (spec §10: max 3 failures → BLOCKED)
                if state.tool_failures >= 3:
                    logger.warning(f"[ExecutorLoop] {state.tool_failures} tool failures — marking BLOCKED")
                    state.step_log.append(
                        f"### Iteration {state.iteration}: Failure Limit\n"
                        f"**Action:** BLOCKED\n"
                        f"**Reason:** {state.tool_failures} tool failures exceeded limit of 3"
                    )
                    break

        # === BUILD FINAL OUTPUTS ===
        ticket_content = self._build_ticket_from_plan(strategic_plan, state.step_log)
        toolresults_content = self._build_toolresults_md(state.all_tool_results, state.all_claims)

        # Write toolresults.md
        toolresults_path = turn_dir.path / "toolresults.md"
        toolresults_path.write_text(toolresults_content)
        logger.info(f"[ExecutorLoop] Wrote toolresults.md ({len(toolresults_content)} chars)")

        # Emit completion events
        await self._emit_phase_event(trace_id, 4, "completed", "Execution complete")
        await self._emit_phase_event(trace_id, 5, "completed", "Coordination complete")

        logger.info(
            f"[ExecutorLoop] Phase 4 complete: {state.iteration} iterations, "
            f"{state.total_tool_calls} tool calls, {state.total_research_calls} research calls, "
            f"{len(state.all_claims)} claims"
        )
        return context_doc, ticket_content, toolresults_content

    async def _handle_command(
        self,
        command: str,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        mode: str,
        state: ExecutorLoopState,
        goals_progress: List[Dict[str, Any]],
        workflow_hint: Optional[str] = None,
    ) -> None:
        """Handle a COMMAND action from the executor."""
        if not command:
            logger.warning(f"[ExecutorLoop] COMMAND with empty command - treating as COMPLETE")
            return

        logger.info(f"[ExecutorLoop] COMMAND: {command[:100]}...")

        # Check tool call limit
        if state.total_tool_calls >= self.config.max_tool_calls:
            logger.warning(f"[ExecutorLoop] Max tool calls ({self.config.max_tool_calls}) reached")
            state.step_log.append(
                f"### Iteration {state.iteration}: Limit Reached\n"
                f"**Command:** {command}\n"
                f"**Result:** SKIPPED (max tool calls)"
            )
            return

        # Check if this is a duplicate research command
        command_lower = command.lower().strip()
        if command_lower in state.completed_research_queries:
            logger.warning(f"[ExecutorLoop] Blocking duplicate command - already executed")
            duplicate_msg = (
                f"### Iteration {state.iteration}: Duplicate Blocked\n"
                f"**Command:** {command}\n"
                f"**Result:** SKIPPED (this exact command was already executed - check §4 for results)"
            )
            state.step_log.append(duplicate_msg)
            self._append_to_section4(
                context_doc,
                f"\n**⚠️ DUPLICATE COMMAND BLOCKED:** This exact command was already executed. "
                f"Review the results above in §4. Either issue COMPLETE if the goal is achieved, "
                f"or try a DIFFERENT command.\n"
            )
            return

        # Check if research limit has been reached
        research_keywords = ["search for", "find ", "look up", "research ", "query "]
        is_research_command = any(kw in command_lower for kw in research_keywords)
        if is_research_command and state.total_research_calls >= self.config.max_research_calls:
            logger.warning(
                f"[ExecutorLoop] Research limit reached ({state.total_research_calls}/"
                f"{self.config.max_research_calls}) - blocking: {command[:50]}..."
            )
            state.step_log.append(
                f"### Iteration {state.iteration}: Research Limit Reached\n"
                f"**Command:** {command}\n"
                f"**Result:** SKIPPED (research limit of {self.config.max_research_calls} calls reached)"
            )
            self._append_to_section4(
                context_doc,
                f"\n**⚠️ RESEARCH LIMIT REACHED:** {state.total_research_calls} research calls completed. "
                f"Use the data already gathered in §1 and §4 to answer the query. "
                f"Issue COMPLETE to proceed to synthesis.\n"
            )
            return

        # Try workflow execution first, then fall back to Coordinator
        try:
            coordinator_result = await self._try_workflow_execution(
                command, context_doc, turn_dir, workflow_hint=workflow_hint
            )

            if coordinator_result is None:
                coordinator_result = await self._coordinator_execute_command(
                    command, context_doc, turn_dir
                )

            state.total_tool_calls += 1

            # Extract claims from result
            if coordinator_result.get("claims"):
                state.all_claims.extend(coordinator_result["claims"])

            # Track tool result
            tool_selected = coordinator_result.get("tool_selected", "unknown")
            state.all_tool_results.append({
                "iteration": state.iteration,
                "command": command,
                "tool": tool_selected,
                "status": coordinator_result.get("status", "unknown"),
                "result": coordinator_result.get("result", {})
            })

            # Track completed commands
            state.completed_research_queries.add(command_lower)

            # Emit action event for route notifier
            if state.trace_id:
                tool_status = coordinator_result.get("status", "unknown")
                if "research" in (tool_selected or "").lower():
                    action_type = "search"
                elif "fetch" in (tool_selected or "").lower() or "browser" in (tool_selected or "").lower():
                    action_type = "fetch"
                else:
                    action_type = "tool"
                await emit_action_event(ActionEvent(
                    trace_id=state.trace_id,
                    action_type=action_type,
                    label=f"{tool_selected}: {command[:80]}",
                    detail=tool_status,
                    success=tool_status in ("success", "complete", "completed"),
                ))

            if tool_selected == "internet.research":
                state.total_research_calls += 1
                result_data = coordinator_result.get("result", {})
                findings = result_data.get("findings", [])
                findings_count = len(findings) if findings else 0
                status = coordinator_result.get("status", "")
                logger.info(
                    f"[ExecutorLoop] Research completed: status={status}, findings={findings_count}, "
                    f"total_research_calls={state.total_research_calls}/{self.config.max_research_calls}"
                )

            # Format result for §4
            result_content = self._format_executor_command_result(
                command, coordinator_result, goals_progress, state.iteration
            )
            state.step_log.append(result_content)
            self._append_to_section4(context_doc, result_content)

        except Exception as e:
            state.tool_failures += 1
            logger.error(
                f"[ExecutorLoop] Coordinator failed for command '{command[:50]}...' "
                f"(failure {state.tool_failures}/3): {e}"
            )
            error_content = (
                f"### Iteration {state.iteration}: Error\n"
                f"**Command:** {command}\n"
                f"**Error:** {str(e)[:200]}\n"
                f"**Tool Failures:** {state.tool_failures}/3"
            )
            state.step_log.append(error_content)
            self._append_to_section4(context_doc, error_content)

            if state.trace_id:
                await emit_action_event(ActionEvent(
                    trace_id=state.trace_id,
                    action_type="error",
                    label=f"Tool failed: {command[:60]}",
                    detail=str(e)[:200],
                    success=False,
                ))

    def _build_workflow_markdown(self, workflow_spec: Dict[str, Any]) -> str:
        """Build workflow markdown with YAML frontmatter from workflow_spec."""
        if not isinstance(workflow_spec, dict):
            raise ValueError("workflow_spec must be an object")

        if workflow_spec.get("content"):
            return str(workflow_spec["content"])

        name = workflow_spec.get("name")
        if not name:
            raise ValueError("workflow_spec.name is required")

        frontmatter: Dict[str, Any] = {}
        for key in (
            "name",
            "version",
            "category",
            "description",
            "triggers",
            "tools",
            "inputs",
            "outputs",
            "steps",
            "success_criteria",
            "fallback",
            "tool_bundle",
            "bootstrap",
        ):
            value = workflow_spec.get(key)
            if value not in (None, "", [], {}):
                frontmatter[key] = value

        try:
            yaml_content = yaml.safe_dump(frontmatter, sort_keys=False).strip()
        except yaml.YAMLError as e:
            raise ValueError(f"workflow_spec could not be serialized: {e}") from e
        body = workflow_spec.get("body") or "## Workflow\n\n(Generated by executor)\n"
        return f"---\n{yaml_content}\n---\n\n{body}"

    async def _handle_create_workflow(
        self,
        workflow_spec: Optional[Dict[str, Any]],
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        state: ExecutorLoopState,
        goals_progress: List[Dict[str, Any]],
        reasoning: str,
    ) -> bool:
        """Handle CREATE_WORKFLOW action from Executor."""
        if not self._execute_single_tool:
            logger.warning("[ExecutorLoop] execute_single_tool not configured for CREATE_WORKFLOW")
            self._append_to_section4(
                context_doc,
                "\n**⚠️ CREATE_WORKFLOW FAILED:** Tool executor not configured.\n"
            )
            return False

        if not workflow_spec:
            logger.warning("[ExecutorLoop] CREATE_WORKFLOW missing workflow_spec")
            self._append_to_section4(
                context_doc,
                "\n**⚠️ CREATE_WORKFLOW FAILED:** Missing workflow_spec.\n"
            )
            return False

        try:
            workflow_content = self._build_workflow_markdown(workflow_spec)
        except ValueError as e:
            self._append_to_section4(
                context_doc,
                f"\n**⚠️ CREATE_WORKFLOW FAILED:** {str(e)}\n"
            )
            return False

        tools = workflow_spec.get("tools", []) or []
        name = workflow_spec.get("name", "workflow")
        bundle_dir = workflow_spec.get("bundle_dir", "")
        tool_specs = workflow_spec.get("tool_specs", []) or []

        # If tools are declared, require tool_specs for each tool
        if tools:
            if not tool_specs:
                self._append_to_section4(
                    context_doc,
                    "\n**⚠️ CREATE_WORKFLOW FAILED:** tools declared but tool_specs missing.\n"
                )
                return False
            spec_index = {ts.get("tool_name"): ts for ts in tool_specs if isinstance(ts, dict)}
            missing_specs = [t for t in tools if t not in spec_index]
            if missing_specs:
                self._append_to_section4(
                    context_doc,
                    f"\n**⚠️ CREATE_WORKFLOW FAILED:** Missing tool_specs for: {missing_specs}\n"
                )
                return False

        # Create tools first (mandatory when tools are declared)
        for tool_name in tools:
            spec_payload = spec_index.get(tool_name, {})
            create_args = {
                "workflow": name,
                "tool_name": tool_name,
                "spec": spec_payload.get("spec", ""),
                "code": spec_payload.get("code", ""),
                "tests": spec_payload.get("tests", ""),
                "skip_tests": spec_payload.get("skip_tests", False),
            }
            if not create_args["spec"] or not create_args["code"]:
                self._append_to_section4(
                    context_doc,
                    f"\n**⚠️ CREATE_WORKFLOW FAILED:** tool_spec for {tool_name} missing spec or code.\n"
                )
                return False

            tool_result = await self._execute_single_tool(
                "tool.create",
                create_args,
                context_doc,
                skip_urls=None,
                turn_dir=turn_dir,
            )
            state.total_tool_calls += 1
            raw_tool = tool_result.get("raw_result", {})
            tool_status = "success" if tool_result.get("status") == "success" and raw_tool.get("status") == "success" else "error"
            state.all_tool_results.append({
                "iteration": state.iteration,
                "command": f"Create tool: {tool_name}",
                "tool": "tool.create",
                "status": tool_status,
                "result": raw_tool or tool_result,
            })
            if tool_status != "success":
                self._append_to_section4(
                    context_doc,
                    f"\n**⚠️ CREATE_WORKFLOW FAILED:** Tool creation failed for {tool_name}.\n"
                )
                state.tool_failures += 1
                return False

        # Validate tool availability before registration
        if tools:
            validate_result = await self._execute_single_tool(
                "workflow.validate_tools",
                {"tools": tools},
                context_doc,
                skip_urls=None,
                turn_dir=turn_dir,
            )
            state.total_tool_calls += 1
            validation = validate_result.get("raw_result", {})
            if validate_result.get("status") != "success" or not validation.get("valid", False):
                missing_tools = validation.get("missing_tools", [])
                state.step_log.append(
                    f"### Iteration {state.iteration}: CREATE_WORKFLOW Validation Failed\n"
                    f"**Workflow:** {name}\n"
                    f"**Missing Tools:** {missing_tools}\n"
                    f"**Reasoning:** {reasoning or 'Missing tools'}"
                )
                self._append_to_section4(
                    context_doc,
                    f"\n**⚠️ CREATE_WORKFLOW BLOCKED:** Missing tools: {missing_tools}\n"
                )
                state.tool_failures += 1
                return False

        # Register workflow
        register_result = await self._execute_single_tool(
            "workflow.register",
            {"name": name, "content": workflow_content, "bundle_dir": bundle_dir},
            context_doc,
            skip_urls=None,
            turn_dir=turn_dir,
        )
        state.total_tool_calls += 1
        raw = register_result.get("raw_result", {})
        status = "success" if register_result.get("status") == "success" and raw.get("status") == "success" else "error"

        coordinator_result = {
            "tool_selected": "workflow.register",
            "status": status,
            "result": raw or register_result,
            "claims": [],
        }
        state.all_tool_results.append({
            "iteration": state.iteration,
            "command": f"Register workflow: {name}",
            "tool": "workflow.register",
            "status": status,
            "result": raw or register_result,
        })
        result_content = self._format_executor_command_result(
            f"Register workflow: {name}",
            coordinator_result,
            goals_progress,
            state.iteration,
        )
        state.step_log.append(result_content)
        self._append_to_section4(context_doc, result_content)

        if status != "success":
            state.tool_failures += 1
            return False

        logger.info(f"[ExecutorLoop] CREATE_WORKFLOW completed: {name}")
        return True


def get_executor_loop(
    llm_client: Any,
    config: Optional[ExecutorLoopConfig] = None,
) -> ExecutorLoop:
    """Factory function to create an ExecutorLoop."""
    return ExecutorLoop(llm_client, config)
