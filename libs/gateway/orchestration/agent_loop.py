"""
Agent Loop - Core coordination logic for tool execution.

Phase 5 in the Pandora pipeline:
- Selects workflows for Coordinator execution
- LLM decides: WORKFLOW_CALL, DONE, or BLOCKED
- Handles failure categories, retries, and termination

Architecture Reference:
- architecture/main-system-patterns/phase5-coordinator.md
"""

import os
import re
import json
import logging
import asyncio
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument
    from libs.gateway.persistence.turn_manager import TurnDirectory

logger = logging.getLogger(__name__)


# === FAILURE CATEGORIES (Tier 10 #38 implementation) ===
# Category A (Recoverable): LLM decides whether to retry
CATEGORY_A_FAILURES = [
    "timeout",
    "network_error",
    "empty_result",
    "parse_error",
]

# Category B (Critical): Require human intervention
CATEGORY_B_FAILURES = [
    "authentication_failed",
    "permission_denied",
    "service_unavailable",
    "rate_limit_exceeded",
    "invalid_tool",
    "schema_validation_failed",
]


class AgentLoopConfig:
    """Configuration for the agent loop."""

    def __init__(
        self,
        max_steps: int = 10,
        max_consecutive_failures: int = 3,
        max_tool_calls: int = 20,
        max_retries_per_tool: int = 2,
        research_timeout: int = 600,
        default_timeout: int = 300,
        intervention_timeout: int = 180,
    ):
        self.max_steps = max_steps
        self.max_consecutive_failures = max_consecutive_failures
        self.max_tool_calls = max_tool_calls
        self.max_retries_per_tool = max_retries_per_tool
        self.research_timeout = research_timeout
        self.default_timeout = default_timeout
        self.intervention_timeout = intervention_timeout


class AgentLoopState:
    """Tracks state during agent loop execution."""

    def __init__(self):
        self.step = 0
        self.consecutive_failures = 0
        self.total_tool_calls = 0
        self.failed_tools: Set[str] = set()
        self.tool_call_history: List[Tuple[str, str]] = []
        self.termination_reason: Optional[str] = None
        self.research_already_called = False
        self.research_exhausted = False
        self.previous_research_queries: Set[str] = set()

        # Accumulated results
        self.all_tool_results: List[Dict[str, Any]] = []
        self.all_claims: List[Dict[str, Any]] = []
        self.all_rejected: List[Dict[str, Any]] = []
        self.step_log: List[str] = []
        self.final_decision: Optional[Dict[str, Any]] = None


class AgentLoop:
    """
    Executes the agent loop for Phase 4 Coordinator.

    This encapsulates the iterative tool execution logic that was
    previously in UnifiedFlow._phase4_coordinator().
    """

    def __init__(
        self,
        llm_client: Any,
        doc_pack_builder: Any,
        response_parser: Any,
        intervention_manager: Any,
        config: Optional[AgentLoopConfig] = None,
    ):
        self.llm_client = llm_client
        self.doc_pack_builder = doc_pack_builder
        self.response_parser = response_parser
        self.intervention_manager = intervention_manager
        self.config = config or AgentLoopConfig()

        # Callbacks for UnifiedFlow methods
        self._write_context_md: Optional[Callable] = None
        self._check_budget: Optional[Callable] = None
        self._inject_tooling_context: Optional[Callable] = None
        self._execute_single_tool: Optional[Callable] = None
        self._execute_workflow: Optional[Callable] = None
        self._hash_tool_args: Optional[Callable] = None
        self._detect_circular_calls: Optional[Callable] = None
        self._summarize_tool_results: Optional[Callable] = None
        self._summarize_claims_batch: Optional[Callable] = None
        self._build_ticket_content: Optional[Callable] = None
        self._build_toolresults_content: Optional[Callable] = None
        self._write_research_documents: Optional[Callable] = None
        self._update_knowledge_graph: Optional[Callable] = None
        self._emit_phase_event: Optional[Callable] = None

    def set_callbacks(
        self,
        write_context_md: Callable,
        check_budget: Callable,
        inject_tooling_context: Callable,
        execute_single_tool: Callable,
        execute_workflow: Callable,
        hash_tool_args: Callable,
        detect_circular_calls: Callable,
        summarize_tool_results: Callable,
        summarize_claims_batch: Callable,
        build_ticket_content: Callable,
        build_toolresults_content: Callable,
        write_research_documents: Callable,
        update_knowledge_graph: Callable,
        emit_phase_event: Callable,
    ):
        """Set callbacks to UnifiedFlow methods."""
        self._write_context_md = write_context_md
        self._check_budget = check_budget
        self._inject_tooling_context = inject_tooling_context
        self._execute_single_tool = execute_single_tool
        self._execute_workflow = execute_workflow
        self._hash_tool_args = hash_tool_args
        self._detect_circular_calls = detect_circular_calls
        self._summarize_tool_results = summarize_tool_results
        self._summarize_claims_batch = summarize_claims_batch
        self._build_ticket_content = build_ticket_content
        self._build_toolresults_content = build_toolresults_content
        self._write_research_documents = write_research_documents
        self._update_knowledge_graph = update_knowledge_graph
        self._emit_phase_event = emit_phase_event

    async def run(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        mode: str,
        trace_id: str = "",
        recipe: Any = None,
    ) -> Tuple["ContextDocument", str, str]:
        """
        Execute the agent loop.

        Returns:
            (context_doc, ticket_content, toolresults_content)
        """
        logger.info("[AgentLoop] Phase 4: Coordinator (Agent Loop)")

        # Emit thinking event
        if self._emit_phase_event:
            await self._emit_phase_event(trace_id, 5, "active", "Coordinating tool execution and research")

        # Load retry context
        skip_urls = self._load_retry_context(turn_dir)

        # Get config from recipe if provided
        if recipe:
            agent_config = getattr(recipe, '_raw_spec', {}).get('agent_loop', {})
            self.config.max_steps = agent_config.get('max_steps', self.config.max_steps)

        # Initialize state
        state = AgentLoopState()
        self._initialize_section4(context_doc, state)

        # === AGENT LOOP ===
        while state.step < self.config.max_steps:
            state.step += 1
            logger.info(f"[AgentLoop] Step {state.step}/{self.config.max_steps}")

            # 1. Write current context.md
            if self._write_context_md:
                self._write_context_md(turn_dir, context_doc)

            # Check budget
            if self._check_budget and recipe:
                self._check_budget(context_doc, recipe, f"Phase 4 Step {state.step}")

            # 2. Get LLM decision
            decision = await self._get_decision(context_doc, turn_dir, mode, state, recipe)

            action = decision.get("action", "BLOCKED")
            reasoning = decision.get("reasoning", "")

            # 3. Handle decision
            if action == "DONE":
                logger.info(f"[AgentLoop] DONE at step {state.step}: {reasoning}")
                state.step_log.append(f"### Step {state.step}: Complete\n**Decision:** DONE\n**Reasoning:** {reasoning}")
                state.final_decision = decision
                break

            if action == "BLOCKED":
                logger.warning(f"[AgentLoop] BLOCKED at step {state.step}: {reasoning}")
                state.step_log.append(f"### Step {state.step}: Blocked\n**Decision:** BLOCKED\n**Reason:** {reasoning}")
                state.final_decision = decision
                break

            # 4. WORKFLOW_CALL - Execute workflow
            if action == "WORKFLOW_CALL":
                workflow_name = decision.get("workflow_selected")
                workflow_args = decision.get("workflow_args", {})
                if not workflow_name:
                    logger.warning("[AgentLoop] WORKFLOW_CALL but no workflow selected")
                    state.step_log.append(f"### Step {state.step}: Error\n**Issue:** WORKFLOW_CALL with no workflow")
                    continue

                await self._execute_workflow_call(
                    context_doc, turn_dir, state, workflow_name, workflow_args, reasoning
                )
            else:
                # Legacy TOOL_CALL - Execute tools
                tools_to_execute = decision.get("tools", [])
                if not tools_to_execute:
                    logger.warning("[AgentLoop] TOOL_CALL but no tools specified")
                    state.step_log.append(f"### Step {state.step}: Error\n**Issue:** TOOL_CALL with no tools")
                    continue

                await self._execute_tools(
                    context_doc, turn_dir, state, tools_to_execute, skip_urls, reasoning
                )

            # Check if terminated during tool execution
            if state.termination_reason:
                self._handle_termination(state)
                break

            # Check if all tools skipped
            if self._check_all_skipped(state):
                break

            # Update §4 with accumulated log
            context_doc.update_section(4, "\n".join(state.step_log))

            logger.info(f"[AgentLoop] Step {state.step} complete")

            # Check for consecutive failures
            if state.consecutive_failures >= self.config.max_consecutive_failures:
                self._handle_consecutive_failures(state)
                break

            # Check for early termination
            if self._check_early_termination(context_doc, state):
                break

        # === END AGENT LOOP ===
        return await self._finalize(context_doc, turn_dir, state, trace_id)

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
                    logger.info(f"[AgentLoop] Will skip {len(skip_urls)} failed URLs")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[AgentLoop] Could not read retry_context.json: {e}")
        return skip_urls

    def _initialize_section4(
        self,
        context_doc: "ContextDocument",
        state: AgentLoopState
    ):
        """Initialize §4 with header, preserving retry context."""
        if context_doc.has_section(4):
            existing = context_doc.get_section(4)
            if "internet.research" in existing and "success" in existing:
                logger.info("[AgentLoop] RETRY: Keeping existing §4 with research results")
                query_match = re.search(r'`internet\.research`.*?"query":\s*"([^"]+)"', existing)
                if query_match:
                    state.previous_research_queries.add(query_match.group(1).lower().strip())
                    state.research_already_called = True
            else:
                context_doc.update_section(4, "*(Agent loop restarting...)*")
        else:
            context_doc.append_section(4, "Tool Execution", "*(Agent loop starting...)*")

    async def _get_decision(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        mode: str,
        state: AgentLoopState,
        recipe: Any
    ) -> Dict[str, Any]:
        """Get LLM decision for this step."""
        pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
        if self._inject_tooling_context:
            self._inject_tooling_context(pack, mode, include_tools=False, include_workflows=True)
        prompt = pack.as_prompt()

        # REFLEX role temp=0.4 for coordination decisions
        temperature = recipe._raw_spec.get("llm_params", {}).get("temperature", 0.4)
        llm_response = await self.llm_client.call(
            prompt=prompt,
            role="coordinator",
            max_tokens=recipe.token_budget.output,
            temperature=temperature
        )

        selection = self.response_parser.parse_json(llm_response)

        status = selection.get("status", "selected")
        if selection.get("_type") == "MODE_VIOLATION" or status == "blocked":
            return {
                "action": "BLOCKED",
                "reasoning": selection.get("error", "Workflow blocked"),
            }

        if status == "needs_more_info":
            missing = selection.get("missing", [])
            message = selection.get("message", "Missing required inputs")
            return {
                "action": "BLOCKED",
                "reasoning": f"needs_more_info: {message} (missing: {missing})",
            }

        workflow_selected = selection.get("workflow_selected") or selection.get("workflow")
        workflow_args = selection.get("workflow_args", {}) or {}

        if not workflow_selected:
            return {
                "action": "BLOCKED",
                "reasoning": "No workflow selected",
            }

        return {
            "action": "WORKFLOW_CALL",
            "workflow_selected": workflow_selected,
            "workflow_args": workflow_args,
            "reasoning": selection.get("rationale", "Workflow selected"),
        }

    async def _execute_workflow_call(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        state: AgentLoopState,
        workflow_name: str,
        workflow_args: Dict[str, Any],
        reasoning: str
    ) -> None:
        """Execute a single workflow selection."""
        if not self._execute_workflow:
            logger.warning("[AgentLoop] No workflow executor configured")
            state.step_log.append(
                f"### Step {state.step}: Error\n**Issue:** WORKFLOW_CALL but no workflow executor configured"
            )
            return

        if "original_query" not in workflow_args:
            workflow_args["original_query"] = context_doc.query

        state.total_tool_calls += 1
        result = await self._execute_workflow(
            workflow_name, workflow_args, context_doc, turn_dir
        )

        claims = result.get("claims", [])
        missing_meta = [c for c in claims if not c.get("url") or not c.get("source_ref")]
        if missing_meta:
            result["status"] = "blocked"
            result["error"] = "Missing source metadata in workflow results"
            state.termination_reason = "critical_failure:missing_source_metadata"

        tool_result = {
            "tool": f"workflow:{workflow_name}",
            "status": result.get("status", "unknown"),
            "result": result.get("result", {}),
            "claims": claims,
            "error": result.get("error", ""),
            "workflow_selected": workflow_name,
            "workflow_args": workflow_args,
        }

        self._track_result(f"workflow:{workflow_name}", workflow_args, tool_result, context_doc, state)
        state.all_tool_results.append(tool_result)

        step_results = [tool_result]
        results_summary = ""
        if self._summarize_tool_results:
            results_summary = self._summarize_tool_results(step_results)

        step_entry = f"""### Step {state.step}
**Action:** {reasoning}
**Workflow:** {workflow_name}
**Results:**
{results_summary}
"""
        state.step_log.append(step_entry)

    async def _execute_tools(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        state: AgentLoopState,
        tools_to_execute: List[Dict[str, Any]],
        skip_urls: List[str],
        reasoning: str
    ):
        """Execute the requested tools."""
        step_results = []
        step_tools_desc = []

        for tool_spec in tools_to_execute:
            tool_name = tool_spec.get("tool", "")
            tool_args = tool_spec.get("args", {})
            tool_purpose = tool_spec.get("purpose", "execute")

            if not tool_name:
                continue

            # Check max tool calls
            if state.total_tool_calls >= self.config.max_tool_calls:
                logger.warning(f"[AgentLoop] Max tool calls ({self.config.max_tool_calls}) reached")
                state.termination_reason = "max_tool_calls"
                step_tools_desc.append(f"- `{tool_name}`: SKIPPED (max tool calls reached)")
                break

            # Skip failed tools
            if tool_name in state.failed_tools:
                logger.info(f"[AgentLoop] Skipping '{tool_name}' - already failed")
                step_tools_desc.append(f"- `{tool_name}`: SKIPPED (previously failed)")
                continue

            # Research guard
            if tool_name == "internet.research":
                skip_reason = self._check_research_guard(state, tool_args)
                if skip_reason:
                    step_tools_desc.append(f"- `{tool_name}`: SKIPPED ({skip_reason})")
                    continue

            # Circular call detection
            if self._hash_tool_args and self._detect_circular_calls:
                args_hash = self._hash_tool_args(tool_args)
                state.tool_call_history.append((tool_name, args_hash))
                if self._detect_circular_calls(state.tool_call_history):
                    logger.warning("[AgentLoop] Circular call pattern detected")
                    state.termination_reason = "circular_pattern"
                    step_tools_desc.append(f"- `{tool_name}`: SKIPPED (circular pattern detected)")
                    break

            # Execute tool
            result = await self._execute_tool(
                context_doc, turn_dir, tool_name, tool_args, skip_urls, state
            )

            # Handle Category B failures
            if self._is_category_b_failure(result):
                should_break = await self._handle_category_b_failure(
                    tool_name, result, state, step_results
                )
                if should_break:
                    break
                continue

            # Track result
            self._track_result(tool_name, tool_args, result, context_doc, state)

            step_results.append(result)
            state.all_tool_results.append(result)

            # Build description
            status = result.get("status", "executed")
            desc = result.get("description", tool_purpose)
            step_tools_desc.append(f"- `{tool_name}`: {desc} ({status})")

        # Build step log entry
        if step_results or step_tools_desc:
            results_summary = ""
            if self._summarize_tool_results and step_results:
                results_summary = self._summarize_tool_results(step_results)

            step_entry = f"""### Step {state.step}
**Action:** {reasoning}
**Tools:**
{chr(10).join(step_tools_desc)}
**Results:**
{results_summary}
"""
            state.step_log.append(step_entry)

    def _check_research_guard(
        self,
        state: AgentLoopState,
        tool_args: Dict[str, Any]
    ) -> Optional[str]:
        """Check if research should be blocked. Returns skip reason or None."""
        current_query = tool_args.get("query", "").lower().strip()

        if state.research_exhausted:
            logger.warning("[AgentLoop] Blocking research - previous attempt returned 0 findings")
            return "research exhausted - 0 findings"

        if state.research_already_called and current_query in state.previous_research_queries:
            logger.warning("[AgentLoop] Blocking duplicate research (same query)")
            return "already called with same query"

        if state.research_already_called:
            logger.info(f"[AgentLoop] Allowing new research query on RETRY: {current_query[:50]}...")

        return None

    async def _execute_tool(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        tool_name: str,
        tool_args: Dict[str, Any],
        skip_urls: List[str],
        state: AgentLoopState
    ) -> Dict[str, Any]:
        """Execute a single tool with timeout."""
        if tool_name == "internet.research":
            timeout = int(os.environ.get("RESEARCH_TIMEOUT", self.config.research_timeout))
        else:
            timeout = self.config.default_timeout

        state.total_tool_calls += 1

        try:
            if self._execute_single_tool:
                result = await asyncio.wait_for(
                    self._execute_single_tool(
                        tool_name, tool_args, context_doc, skip_urls=skip_urls, turn_dir=turn_dir
                    ),
                    timeout=timeout
                )
            else:
                result = {"status": "error", "error": "No tool executor configured"}
        except asyncio.TimeoutError:
            logger.warning(f"[AgentLoop] Tool '{tool_name}' timed out after {timeout}s")
            result = {
                "tool": tool_name,
                "status": "timeout",
                "error": f"Tool execution timed out after {timeout} seconds",
                "claims": [],
                "raw_result": {}
            }
            state.failed_tools.add(tool_name)
            state.consecutive_failures += 1
            context_doc.update_execution_state(4, "Coordinator", consecutive_errors=state.consecutive_failures)

        return result

    def _is_category_b_failure(self, result: Dict[str, Any]) -> bool:
        """Check if result is a Category B (critical) failure."""
        error_type = result.get("error_type", "") or result.get("error", "")
        return any(crit in str(error_type).lower() for crit in CATEGORY_B_FAILURES)

    async def _handle_category_b_failure(
        self,
        tool_name: str,
        result: Dict[str, Any],
        state: AgentLoopState,
        step_results: List[Dict[str, Any]]
    ) -> bool:
        """Handle Category B failure. Returns True if loop should break."""
        from apps.services.tool_server.intervention_manager import InterventionStatus

        error_type = result.get("error_type", "") or result.get("error", "")
        logger.error(f"[AgentLoop] Category B failure detected: {error_type}")

        intervention = await self.intervention_manager.request_intervention(
            blocker_type="critical_failure",
            url=result.get("url", "tool execution"),
            blocker_details={
                "failure_type": error_type,
                "tool": tool_name,
                "context": f"Executing {tool_name}",
                "options": ["Proceed anyway", "Skip this source", "Cancel query"]
            }
        )

        resolved = await intervention.wait_for_resolution(timeout=self.config.intervention_timeout)

        if not resolved or intervention.status == InterventionStatus.CANCELLED:
            logger.warning(f"[AgentLoop] Intervention cancelled/timeout for {tool_name}")
            state.termination_reason = f"critical_failure:{error_type}"
            step_results.append(result)
            state.all_tool_results.append(result)
            return True

        if intervention.status == InterventionStatus.SKIPPED:
            logger.info(f"[AgentLoop] User skipped {tool_name}, continuing")
            state.failed_tools.add(tool_name)
            step_results.append(result)
            state.all_tool_results.append(result)
            return False  # Continue with next tool

        # User chose to proceed
        logger.info(f"[AgentLoop] User approved proceeding despite {error_type}")
        return False

    def _track_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Dict[str, Any],
        context_doc: "ContextDocument",
        state: AgentLoopState
    ):
        """Track tool result and update state."""
        if result.get("status") in ("error", "failed", "timeout"):
            state.failed_tools.add(tool_name)
            state.consecutive_failures += 1
            context_doc.update_execution_state(4, "Coordinator", consecutive_errors=state.consecutive_failures)

            if tool_name == "internet.research":
                state.research_exhausted = True
                logger.warning("[AgentLoop] Research failed - marking as exhausted")
        else:
            state.consecutive_failures = 0
            context_doc.update_execution_state(4, "Coordinator", consecutive_errors=0)

            if tool_name == "internet.research":
                state.research_already_called = True
                query_used = tool_args.get("query", "").lower().strip()
                if query_used:
                    state.previous_research_queries.add(query_used)

                # Check for 0 findings
                raw_result = result.get("result", {})
                findings = raw_result.get("findings", [])
                if not findings:
                    state.research_exhausted = True
                    logger.warning("[AgentLoop] Research returned 0 findings - marking as exhausted")

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

    def _handle_termination(self, state: AgentLoopState):
        """Handle loop termination."""
        logger.warning(f"[AgentLoop] Terminating: {state.termination_reason}")
        state.step_log.append(f"### Step {state.step}: Terminated\n**Reason:** {state.termination_reason}")

        if "critical_failure" in state.termination_reason:
            state.final_decision = {"action": "BLOCKED", "reasoning": state.termination_reason}
        else:
            state.final_decision = {"action": "DONE", "reasoning": f"Early termination: {state.termination_reason}"}

    def _check_all_skipped(self, state: AgentLoopState) -> bool:
        """Check if all tools were skipped."""
        # Check if we have any results from this step
        step_result_count = len(state.all_tool_results) - (state.step - 1) * 10  # Approximation
        if step_result_count <= 0 and (state.all_claims or state.research_already_called):
            logger.info(f"[AgentLoop] All tools skipped, forcing DONE (claims={len(state.all_claims)})")
            state.step_log.append(f"### Step {state.step}: Auto-Complete\n**Decision:** DONE (research already executed)")
            state.final_decision = {"action": "DONE", "reasoning": "Research already complete, using existing results"}
            return True
        return False

    def _handle_consecutive_failures(self, state: AgentLoopState):
        """Handle too many consecutive failures."""
        logger.warning(f"[AgentLoop] Too many consecutive failures ({state.consecutive_failures}), exiting")
        state.step_log.append(
            f"### Step {state.step}: Aborted\n**Decision:** BLOCKED (too many tool failures)\n"
            f"**Failed tools:** {', '.join(state.failed_tools)}"
        )
        state.final_decision = {"action": "BLOCKED", "reasoning": f"Too many tool failures: {', '.join(state.failed_tools)}"}

    def _check_early_termination(
        self,
        context_doc: "ContextDocument",
        state: AgentLoopState
    ) -> bool:
        """Check for early termination conditions."""
        if state.step >= 1 and state.all_claims:
            action_needed = context_doc.get_action_needed()
            data_reqs = context_doc.get_data_requirements()

            is_navigational = (
                action_needed == "navigate_to_site" or
                (action_needed == "live_search" and not data_reqs.get("needs_current_prices", False))
            )

            if is_navigational and len(state.all_claims) >= 2:
                logger.info(f"[AgentLoop] Early termination: navigational query with {len(state.all_claims)} claims")
                state.step_log.append(f"### Step {state.step}: Early Complete\n**Decision:** DONE (navigational query satisfied)")
                state.final_decision = {"action": "DONE", "reasoning": "Navigational query satisfied with sufficient content"}
                return True

            if not is_navigational and state.step >= 3 and len(state.all_claims) >= 5:
                logger.info(f"[AgentLoop] Early termination: commerce query with {len(state.all_claims)} claims")
                state.step_log.append(f"### Step {state.step}: Early Complete\n**Decision:** DONE (sufficient products found)")
                state.final_decision = {"action": "DONE", "reasoning": "Sufficient products gathered"}
                return True

        return False

    async def _finalize(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        state: AgentLoopState,
        trace_id: str
    ) -> Tuple["ContextDocument", str, str]:
        """Finalize the agent loop and build output documents."""
        # Check if we hit max steps
        if state.step >= self.config.max_steps and state.final_decision is None:
            logger.warning(f"[AgentLoop] Max steps ({self.config.max_steps}) reached")
            state.step_log.append(f"### Step {state.step}: Max Steps Reached\n**Decision:** Forced exit")

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
        if state.final_decision:
            status = "success" if state.final_decision.get("action") == "DONE" else "blocked"
        elif state.step >= self.config.max_steps:
            status = "partial"
        else:
            status = "unknown"

        # Build termination info
        termination_info = ""
        if state.termination_reason:
            termination_info = f"\n**Termination Reason:** {state.termination_reason}"
        elif state.step >= self.config.max_steps:
            termination_info = f"\n**Termination Reason:** max_iterations ({self.config.max_steps})"

        # Final §4 content
        final_section = f"""## Execution Log ({state.step} steps)

**Status:** {status}
**Iterations:** {state.step}/{self.config.max_steps}
**Tool Calls:** {state.total_tool_calls}/{self.config.max_tool_calls}{termination_info}

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
        logger.info(f"[AgentLoop] Wrote toolresults.md ({len(toolresults_content)} chars)")

        # Emit completion event
        if self._emit_phase_event:
            await self._emit_phase_event(trace_id, 5, "completed", "Coordination complete")

        logger.info(f"[AgentLoop] Complete: {state.step} steps, {len(state.all_tool_results)} tools, {len(context_doc.claims)} claims")
        return context_doc, ticket_content, toolresults_content


def get_agent_loop(
    llm_client: Any,
    doc_pack_builder: Any,
    response_parser: Any,
    intervention_manager: Any,
    config: Optional[AgentLoopConfig] = None
) -> AgentLoop:
    """Factory function to create an AgentLoop instance."""
    return AgentLoop(
        llm_client=llm_client,
        doc_pack_builder=doc_pack_builder,
        response_parser=response_parser,
        intervention_manager=intervention_manager,
        config=config
    )
