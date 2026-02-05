"""
Workflow Manager - Workflow loading, matching, and execution.

Extracted from UnifiedFlow to manage:
- Workflow registry loading
- Bundle tool registration
- Tooling context injection
- Workflow execution and result formatting

Architecture Reference:
- architecture/main-system-patterns/phase4-executor.md
"""

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument
    from libs.gateway.persistence.turn_manager import TurnDirectory
    from libs.gateway.execution.workflow_result import WorkflowResult

logger = logging.getLogger(__name__)


class WorkflowManager:
    """
    Manages workflow loading, matching, and execution.

    Responsibilities:
    - Load workflows from registry and bundles
    - Inject tooling context into doc packs
    - Match commands to workflows
    - Execute workflows and format results
    """

    def __init__(
        self,
        workflow_registry: Any,
        workflow_matcher: Any,
        workflow_runner: Any,
        tool_catalog: Any,
        claims_manager: Any,
    ):
        """Initialize the workflow manager."""
        self.workflow_registry = workflow_registry
        self.workflow_matcher = workflow_matcher
        self.workflow_runner = workflow_runner
        self.tool_catalog = tool_catalog
        self.claims_manager = claims_manager

    def get_workflow_bundles_root(self) -> Path:
        """Return the root directory for workflow bundles."""
        return Path(__file__).parent.parent.parent.parent / "panda_system_docs" / "workflows" / "bundles"

    def load_workflows(self) -> None:
        """Load workflows from apps/workflows and panda_system_docs bundles."""
        base_loaded = self.workflow_registry.load_all()
        bundles_root = self.get_workflow_bundles_root()
        bundle_loaded = self.workflow_registry.load_bundles(bundles_root)
        bundle_tools_loaded = self.register_bundle_tools()

        logger.info(
            "[WorkflowManager] Workflow load complete: "
            f"{base_loaded} base workflows, {bundle_loaded} bundles, "
            f"{bundle_tools_loaded} bundle tools"
        )

    def register_bundle_tools(self) -> int:
        """Register tools for any workflows that declare a tool bundle."""
        registered_total = 0
        for workflow in self.workflow_registry.all():
            tool_bundle = workflow.tool_bundle
            if not tool_bundle:
                continue
            if not Path(tool_bundle).exists():
                logger.warning(
                    f"[WorkflowManager] Tool bundle path not found for workflow "
                    f"{workflow.name}: {tool_bundle}"
                )
                continue

            registered = self.tool_catalog.register_tools_from_bundle(Path(tool_bundle))
            registered_total += len(registered)

        return registered_total

    def inject_tooling_context(
        self,
        pack,
        mode: str,
        include_tools: bool = True,
        include_workflows: bool = True,
    ) -> None:
        """Inject dynamic tool/workflow lists into a doc pack."""
        remaining = pack.remaining_budget
        doc_count = (1 if include_tools else 0) + (1 if include_workflows else 0)

        if remaining <= 0 or doc_count == 0:
            return

        per_doc_budget = min(900, max(200, remaining // doc_count))

        if include_tools:
            tools_doc = self.build_tools_context_doc(mode)
            pack.add_doc("available_tools.md", tools_doc, budget=per_doc_budget)

        if include_workflows:
            workflows_doc = self.build_workflows_context_doc()
            pack.add_doc("available_workflows.md", workflows_doc, budget=per_doc_budget)

    def build_tools_context_doc(self, mode: str) -> str:
        """Build a compact tool list for prompt injection."""
        tools = self.tool_catalog.list_tools_with_descriptions(mode)
        tools_sorted = sorted(tools, key=lambda t: t["name"])

        lines = [
            "# Available Tools (dynamic)",
            f"Mode: {mode}",
            "Use only the tool names listed below.",
            "",
        ]

        for tool in tools_sorted:
            desc = tool.get("description") or "No description provided."
            tool_mode = tool.get("mode", "any")
            lines.append(f"- {tool['name']} ({tool_mode}) - {desc}")

        return "\n".join(lines)

    def build_workflows_context_doc(self) -> str:
        """Build a compact workflow list for prompt injection."""
        workflows = sorted(self.workflow_registry.all(), key=lambda w: w.name)

        lines = [
            "# Available Workflows (dynamic)",
            "When selecting a workflow, choose from this list.",
            "",
        ]

        for workflow in workflows:
            triggers = [self.format_workflow_trigger(t) for t in workflow.triggers if t]
            triggers_display = "none"
            if triggers:
                if len(triggers) > 3:
                    triggers_display = ", ".join(triggers[:3]) + f" (+{len(triggers) - 3} more)"
                else:
                    triggers_display = ", ".join(triggers)

            tools_display = ", ".join(workflow.tools) if workflow.tools else "n/a"
            lines.append(
                f"- {workflow.name} (category: {workflow.category}) "
                f"tools: {tools_display} triggers: {triggers_display}"
            )

        return "\n".join(lines)

    def format_workflow_trigger(self, trigger: Any) -> str:
        """Format a workflow trigger for display."""
        if isinstance(trigger, dict):
            if "intent" in trigger:
                return f"intent:{trigger['intent']}"
            return ", ".join(f"{k}:{v}" for k, v in trigger.items())
        if isinstance(trigger, str):
            return trigger
        return str(trigger)

    async def try_workflow_execution(
        self,
        command: str,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        workflow_hint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Try to match and execute a workflow for the command.

        Workflow selection order:
        1. Executor-provided workflow_hint (if provided)
        2. LLM-selected workflow (context_doc.workflow from Planner)
        3. WorkflowMatcher heuristics (fallback)

        Returns:
            Result dict if workflow executed, None if no match
        """
        workflow = None
        match_info = {}

        # Priority 1: Executor-provided workflow hint
        if workflow_hint:
            hinted = self.workflow_registry.get(workflow_hint)
            if hinted:
                workflow = hinted
                logger.info(f"[WorkflowManager] Using executor workflow_hint: {workflow_hint}")
                match_info = {
                    "confidence": 0.9,
                    "matched_trigger": f"executor_hint:{workflow_hint}",
                    "extracted_params": {},
                }
            else:
                normalized_hint = workflow_hint.strip().lower()
                for candidate in self.workflow_registry.all():
                    if candidate.name.lower() == normalized_hint:
                        workflow = candidate
                        logger.info(f"[WorkflowManager] Using normalized workflow_hint: {workflow_hint}")
                        match_info = {
                            "confidence": 0.9,
                            "matched_trigger": f"executor_hint:{workflow_hint}",
                            "extracted_params": {},
                        }
                        break
                if not workflow:
                    logger.warning(
                        f"[WorkflowManager] Executor workflow_hint not found: {workflow_hint}, falling back to planner/matcher"
                    )

        # Priority 2: LLM-selected workflow from Planner (context_doc.workflow)
        if not workflow:
            llm_selected_workflow = getattr(context_doc, 'workflow', None)
            if llm_selected_workflow:
                workflow = self.workflow_registry.get(llm_selected_workflow)
                if workflow:
                    logger.info(f"[WorkflowManager] Using planner workflow: {llm_selected_workflow}")
                    match_info = {
                        "confidence": 0.95,
                        "matched_trigger": f"planner_selected:{llm_selected_workflow}",
                        "extracted_params": {},
                    }
                else:
                    logger.warning(
                        f"[WorkflowManager] Planner selected unknown workflow: {llm_selected_workflow}, "
                        f"falling back to matcher"
                    )

        # Priority 2: Fall back to WorkflowMatcher if no LLM selection
        if not workflow:
            match = self.workflow_matcher.match(command, context_doc)
            if not match or match.confidence < 0.7:
                logger.debug(f"[WorkflowManager] No workflow match for: {command[:50]}...")
                return None
            workflow = match.workflow
            match_info = {
                "confidence": match.confidence,
                "matched_trigger": match.matched_trigger,
                "extracted_params": match.extracted_params,
            }

        logger.info(f"[WorkflowManager] Workflow selected: {workflow.name} (confidence={match_info['confidence']})")

        # Get current mode (default to chat for safety)
        mode = getattr(context_doc, 'mode', 'chat')

        # Execute the workflow via WorkflowStepRunner
        result = await self.workflow_runner.run(
            workflow=workflow,
            inputs={
                "goal": context_doc.query,
                **match_info.get("extracted_params", {})
            },
            context_doc=context_doc,
            turn_dir=turn_dir,
            mode=mode,
        )

        # Convert WorkflowResult to Coordinator-compatible format
        if result.success:
            # Extract claims from workflow outputs
            claims = self.extract_claims_from_workflow_result(result)

            return {
                "_type": "COORDINATOR_RESULT",
                "command_received": command,
                "tool_selected": f"workflow:{workflow.name}",
                "tool_args": match_info.get("extracted_params", {}),
                "status": "success",
                "result": result.outputs,
                "claims": claims,
                "workflow_execution": {
                    "workflow": workflow.name,
                    "steps_executed": result.steps_executed,
                    "elapsed_seconds": result.elapsed_seconds,
                }
            }
        else:
            return {
                "_type": "COORDINATOR_RESULT",
                "command_received": command,
                "tool_selected": f"workflow:{workflow.name}",
                "status": "error",
                "result": {
                    "error": result.error,
                    "partial_outputs": result.outputs,
                    "fallback_message": result.outputs.get("fallback_message", ""),
                },
                "claims": [],
                "workflow_execution": {
                    "workflow": workflow.name,
                    "fallback_used": result.fallback_used,
                }
            }

    async def execute_workflow(
        self,
        workflow_name: str,
        workflow_args: Dict[str, Any],
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        mode: str,
    ) -> Dict[str, Any]:
        """Execute a specific workflow by name with provided args."""
        workflow = self.workflow_registry.get(workflow_name)
        if not workflow:
            return {
                "_type": "COORDINATOR_RESULT",
                "command_received": "",
                "workflow_selected": workflow_name,
                "workflow_args": workflow_args,
                "tool_selected": f"workflow:{workflow_name}",
                "tool_args": workflow_args,
                "status": "error",
                "result": None,
                "claims": [],
                "tool_runs": [],
                "error": f"Unknown workflow: {workflow_name}"
            }

        result = await self.workflow_runner.run(
            workflow=workflow,
            inputs=workflow_args,
            context_doc=context_doc,
            turn_dir=turn_dir,
            mode=mode,
        )

        claims = self.extract_claims_from_workflow_result(result) if result.success else []

        tool_runs = []
        if result.steps_executed:
            step_map = {step.name: step for step in workflow.steps}
            for step_name in result.steps_executed:
                step = step_map.get(step_name)
                if not step:
                    continue
                tool_runs.append({
                    "tool": step.tool,
                    "status": "success",
                    "duration_ms": None,
                })

        return {
            "_type": "COORDINATOR_RESULT",
            "command_received": "",
            "workflow_selected": workflow.name,
            "workflow_args": workflow_args,
            "tool_selected": f"workflow:{workflow.name}",
            "tool_args": workflow_args,
            "status": "success" if result.success else "error",
            "result": result.outputs if result.success else None,
            "claims": claims,
            "tool_runs": tool_runs,
            "error": result.error if not result.success else None,
        }

    def extract_claims_from_workflow_result(self, result: "WorkflowResult") -> List[Dict[str, Any]]:
        """Extract claims from workflow outputs. Delegates to ClaimsManager."""
        return self.claims_manager.extract_claims_from_workflow_result(result)


# Factory function
def get_workflow_manager(
    workflow_registry: Any,
    workflow_matcher: Any,
    workflow_runner: Any,
    tool_catalog: Any,
    claims_manager: Any,
) -> WorkflowManager:
    """Create a WorkflowManager instance."""
    return WorkflowManager(
        workflow_registry=workflow_registry,
        workflow_matcher=workflow_matcher,
        workflow_runner=workflow_runner,
        tool_catalog=tool_catalog,
        claims_manager=claims_manager,
    )
