"""
Workflow Executor - Executes workflow definitions.

Separates workflow loading (what to do) from execution (how to do it).
The Executor owns the tool catalog; workflows reference tools by name.

Usage:
    executor = WorkflowExecutor(tool_catalog)
    result = await executor.execute(workflow, inputs, context_doc)
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Awaitable

from libs.gateway.workflow_registry import Workflow, WorkflowStep
from libs.gateway.forgiving_parser import ForgivingParser

logger = logging.getLogger(__name__)


@dataclass
class WorkflowResult:
    """Result of workflow execution."""
    success: bool
    workflow_name: str
    outputs: Dict[str, Any] = field(default_factory=dict)
    steps_executed: List[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error: Optional[str] = None
    fallback_used: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


class WorkflowError(Exception):
    """Error during workflow execution."""
    pass


class WorkflowExecutor:
    """
    Executes workflow definitions.

    Tool catalog maps tool URIs to async functions:
    - "internal://internet_research.execute_research" -> execute_research_fn
    - "internal://memory.save" -> memory_save_fn
    - "bootstrap://file_io.write" -> file_write_fn
    """

    def __init__(
        self,
        tool_catalog: Optional[Dict[str, Callable[..., Awaitable[Any]]]] = None,
    ):
        self.tool_catalog = tool_catalog or {}
        self.parser = ForgivingParser()

    def register_tool(
        self,
        tool_uri: str,
        handler: Callable[..., Awaitable[Any]]
    ):
        """Register a tool handler."""
        self.tool_catalog[tool_uri] = handler
        logger.debug(f"[WorkflowExecutor] Registered tool: {tool_uri}")

    async def execute(
        self,
        workflow: Workflow,
        inputs: Dict[str, Any],
        context_doc: Optional[Any] = None,
        turn_dir: Optional[Any] = None,
    ) -> WorkflowResult:
        """
        Execute a workflow with given inputs.

        Steps:
        1. Validate inputs against workflow schema
        2. Execute each step in sequence
        3. Pass outputs between steps via template interpolation
        4. Validate success criteria
        5. Return consolidated outputs or fallback
        """
        start_time = time.time()
        steps_executed = []
        step_outputs = {}
        warnings = []

        logger.info(f"[WorkflowExecutor] Starting workflow: {workflow.name}")

        try:
            # 1. Resolve inputs
            resolved_inputs = self._resolve_inputs(
                workflow, inputs, context_doc
            )
            logger.debug(f"[WorkflowExecutor] Resolved inputs: {list(resolved_inputs.keys())}")

            # 2. Execute steps in sequence
            for step in workflow.steps:
                # Check condition
                if step.condition:
                    step_context = {**resolved_inputs, **step_outputs}
                    if not self._evaluate_condition(step.condition, step_context):
                        logger.info(f"[WorkflowExecutor] Skipping step {step.name} (condition not met)")
                        continue

                logger.info(f"[WorkflowExecutor] Executing step: {step.name}")

                # Interpolate args
                step_context = {**resolved_inputs, **step_outputs}
                resolved_args = self._interpolate_args(step.args, step_context)

                # Execute the tool
                result = await self._execute_step(step, resolved_args)

                # Collect outputs
                if isinstance(result, dict):
                    for output_name in step.outputs:
                        if output_name in result:
                            step_outputs[output_name] = result[output_name]
                    # Also collect any unlisted outputs
                    for key, value in result.items():
                        if key not in step_outputs:
                            step_outputs[key] = value

                steps_executed.append(step.name)

            # 3. Validate success criteria
            success = self._validate_success_criteria(
                workflow.success_criteria,
                step_outputs
            )

            elapsed = time.time() - start_time

            if success:
                logger.info(
                    f"[WorkflowExecutor] Workflow {workflow.name} completed "
                    f"successfully in {elapsed:.2f}s"
                )
                return WorkflowResult(
                    success=True,
                    workflow_name=workflow.name,
                    outputs=step_outputs,
                    steps_executed=steps_executed,
                    elapsed_seconds=elapsed,
                    warnings=warnings,
                )
            else:
                # Try fallback
                logger.warning(
                    f"[WorkflowExecutor] Workflow {workflow.name} success criteria not met"
                )
                return await self._handle_fallback(
                    workflow, inputs, context_doc, turn_dir,
                    step_outputs, steps_executed, elapsed, warnings
                )

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[WorkflowExecutor] Workflow {workflow.name} failed: {e}")

            return await self._handle_fallback(
                workflow, inputs, context_doc, turn_dir,
                step_outputs, steps_executed, elapsed, warnings, str(e)
            )

    def _resolve_inputs(
        self,
        workflow: Workflow,
        inputs: Dict[str, Any],
        context_doc: Optional[Any],
    ) -> Dict[str, Any]:
        """Resolve input values from various sources."""
        resolved = {}

        for name, spec in workflow.inputs.items():
            # Priority: explicit input > from_source > default
            if name in inputs:
                resolved[name] = inputs[name]
            elif spec.from_source:
                resolved[name] = self._resolve_from_source(
                    spec.from_source, context_doc
                )
            elif spec.default is not None:
                resolved[name] = spec.default
            elif spec.required:
                # Required but no value - try to extract from context
                if context_doc:
                    resolved[name] = self._extract_from_context(name, context_doc)
                else:
                    resolved[name] = ""

        return resolved

    def _resolve_from_source(
        self,
        from_source: str,
        context_doc: Optional[Any],
    ) -> Any:
        """Resolve a value from a named source."""
        if context_doc is None:
            return None

        if from_source == "original_query":
            return getattr(context_doc, "query", "") or ""
        elif from_source.startswith("section_"):
            section_num = int(from_source.split("_")[1])
            if hasattr(context_doc, "get_section"):
                return context_doc.get_section(section_num) or ""
            return ""
        elif hasattr(context_doc, from_source):
            return getattr(context_doc, from_source)

        return None

    def _extract_from_context(
        self,
        name: str,
        context_doc: Any,
    ) -> Any:
        """Try to extract a named value from context document."""
        # Try common attribute names
        for attr in [name, f"get_{name}", name.lower()]:
            if hasattr(context_doc, attr):
                val = getattr(context_doc, attr)
                if callable(val):
                    return val()
                return val
        return ""

    def _interpolate_args(
        self,
        args: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Interpolate {{variable}} patterns in args.

        Supports:
        - {{goal}} -> context["goal"]
        - {{context.intent}} -> context["context"]["intent"]
        - {{context.intent | default: 'informational'}} -> with default
        """
        resolved = {}

        for key, value in args.items():
            if isinstance(value, str):
                resolved[key] = self._interpolate_string(value, context)
            elif isinstance(value, dict):
                resolved[key] = self._interpolate_args(value, context)
            elif isinstance(value, list):
                resolved[key] = [
                    self._interpolate_string(v, context) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                resolved[key] = value

        return resolved

    def _interpolate_string(
        self,
        template: str,
        context: Dict[str, Any]
    ) -> str:
        """Interpolate {{variable}} patterns in a string."""
        if "{{" not in template:
            return template

        def replace_match(match):
            expr = match.group(1).strip()

            # Handle default values
            if " | default:" in expr:
                path, default = expr.split(" | default:", 1)
                path = path.strip()
                default = default.strip().strip("'\"")
                value = self._get_nested(context, path)
                return str(value) if value is not None else default

            # Simple path lookup
            value = self._get_nested(context, expr)
            return str(value) if value is not None else ""

        return re.sub(r'\{\{([^}]+)\}\}', replace_match, template)

    def _get_nested(self, obj: Dict[str, Any], path: str) -> Any:
        """Get nested value using dot notation."""
        parts = path.split(".")
        current = obj

        for part in parts:
            if current is None:
                return None

            if isinstance(current, dict):
                current = current.get(part)
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                return None

        return current

    async def _execute_step(
        self,
        step: WorkflowStep,
        args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a single step."""
        tool_uri = step.tool

        # Get tool handler
        handler = self.tool_catalog.get(tool_uri)
        if not handler:
            raise WorkflowError(f"Unknown tool: {tool_uri}")

        # Call the handler
        try:
            result = await handler(**args)
            if result is None:
                result = {}
            elif not isinstance(result, dict):
                result = {"result": result}
            return result
        except TypeError as e:
            # Handle argument mismatch
            logger.error(f"[WorkflowExecutor] Tool {tool_uri} argument error: {e}")
            raise WorkflowError(f"Tool argument error: {e}")

    def _evaluate_condition(
        self,
        condition: str,
        context: Dict[str, Any]
    ) -> bool:
        """Evaluate a condition expression."""
        # Simple {{variable}} truthiness check
        if condition.startswith("{{") and condition.endswith("}}"):
            var_name = condition[2:-2].strip()
            value = self._get_nested(context, var_name)
            return bool(value)

        # Use forgiving parser for complex conditions
        return self.parser.evaluate_criterion(condition, context)

    def _validate_success_criteria(
        self,
        criteria: List[str],
        outputs: Dict[str, Any]
    ) -> bool:
        """Validate all success criteria."""
        if not criteria:
            return True

        for criterion in criteria:
            if not self.parser.evaluate_criterion(criterion, outputs):
                logger.debug(
                    f"[WorkflowExecutor] Criterion failed: {criterion}"
                )
                return False

        return True

    async def _handle_fallback(
        self,
        workflow: Workflow,
        inputs: Dict[str, Any],
        context_doc: Optional[Any],
        turn_dir: Optional[Any],
        outputs: Dict[str, Any],
        steps_executed: List[str],
        elapsed: float,
        warnings: List[str],
        error: Optional[str] = None,
    ) -> WorkflowResult:
        """Handle workflow failure with optional fallback."""
        if not workflow.fallback:
            return WorkflowResult(
                success=False,
                workflow_name=workflow.name,
                outputs=outputs,
                steps_executed=steps_executed,
                elapsed_seconds=elapsed,
                error=error or "Success criteria not met",
                warnings=warnings,
            )

        # If fallback workflow specified, try it
        if workflow.fallback.workflow:
            logger.info(
                f"[WorkflowExecutor] Falling back to: {workflow.fallback.workflow}"
            )
            # Note: Fallback execution requires registry access
            # This would be wired up at integration time
            return WorkflowResult(
                success=False,
                workflow_name=workflow.name,
                outputs=outputs,
                steps_executed=steps_executed,
                elapsed_seconds=elapsed,
                error=error,
                fallback_used=workflow.fallback.workflow,
                warnings=warnings + [f"Fallback: {workflow.fallback.message}"],
            )

        # No fallback workflow, just return message
        return WorkflowResult(
            success=False,
            workflow_name=workflow.name,
            outputs={
                **outputs,
                "fallback_message": workflow.fallback.message,
            },
            steps_executed=steps_executed,
            elapsed_seconds=elapsed,
            error=error or workflow.fallback.message,
            warnings=warnings,
        )


def create_tool_catalog_from_unified_flow(unified_flow) -> Dict[str, Callable]:
    """
    Create a tool catalog from UnifiedFlow instance.

    Maps workflow tool URIs to UnifiedFlow methods.
    """
    catalog = {}

    # Research tools
    async def execute_research(goal: str, intent: str = "informational", context: str = "", task: str = "", **kwargs):
        """Wrapper for internet research Phase 1."""
        from apps.tools.internet_research import execute_full_research

        result = await execute_full_research(
            goal=goal,
            intent=intent,
            context=context,
            **kwargs
        )
        return result

    async def execute_full_research_wrapper(goal: str, intent: str = "commerce", context: str = "", target_vendors: int = 3, **kwargs):
        """Wrapper for full commerce research."""
        from apps.tools.internet_research import execute_full_research

        result = await execute_full_research(
            goal=goal,
            intent=intent,
            context=context,
            target_vendors=target_vendors,
            **kwargs
        )
        return result

    # Register research tools
    catalog["internal://internet_research.execute_research"] = execute_research
    catalog["internal://internet_research.execute_full_research"] = execute_full_research_wrapper

    return catalog
