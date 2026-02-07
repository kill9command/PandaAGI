"""
Workflow Step Runner - Executes workflow steps using ToolCatalog.

Ported from WorkflowExecutor with the following changes:
- Uses ToolCatalog instead of internal dict for tool dispatch
- Resolves old tool URIs to new canonical names
- Mode-aware execution (code vs chat)

Usage:
    from libs.gateway.execution.tool_catalog import ToolCatalog
    from libs.gateway.execution.workflow_step_runner import WorkflowStepRunner

    catalog = ToolCatalog()
    # ... register tools ...

    runner = WorkflowStepRunner(catalog)
    result = await runner.run(workflow, inputs, context_doc)
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from libs.gateway.execution.workflow_registry import Workflow, WorkflowStep
from libs.gateway.execution.tool_catalog import ToolCatalog, resolve_tool_uri
from libs.gateway.parsing.forgiving_parser import ForgivingParser

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


class WorkflowStepRunner:
    """
    Executes workflow steps using ToolCatalog.

    Handles:
    - Input resolution from context document
    - {{variable}} interpolation in step arguments
    - Condition evaluation for conditional steps
    - Success criteria validation
    - Fallback handling on failure
    """

    def __init__(self, tool_catalog: ToolCatalog):
        """
        Initialize the runner.

        Args:
            tool_catalog: ToolCatalog instance with registered tools
        """
        self.catalog = tool_catalog
        self.parser = ForgivingParser()

    async def run(
        self,
        workflow: Workflow,
        inputs: Dict[str, Any],
        context_doc: Optional[Any] = None,
        turn_dir: Optional[Any] = None,
        mode: str = "chat",
    ) -> WorkflowResult:
        """
        Execute a workflow with given inputs.

        Steps:
        1. Resolve inputs from provided values, sources, or defaults
        2. Execute each step in sequence (respecting conditions)
        3. Pass outputs between steps via template interpolation
        4. Validate success criteria
        5. Return consolidated outputs or handle fallback

        Args:
            workflow: Workflow definition to execute
            inputs: Input values provided by caller
            context_doc: Optional context document for source resolution
            turn_dir: Optional turn directory for file outputs
            mode: Operating mode ("code" or "chat") for tool validation

        Returns:
            WorkflowResult with success status and outputs
        """
        start_time = time.time()
        steps_executed: List[str] = []
        step_outputs: Dict[str, Any] = {}
        warnings: List[str] = []

        logger.info(f"[WorkflowStepRunner] Starting workflow: {workflow.name}")

        try:
            # 1. Resolve inputs
            resolved_inputs = self._resolve_inputs(workflow, inputs, context_doc)
            logger.debug(f"[WorkflowStepRunner] Resolved inputs: {list(resolved_inputs.keys())}")

            # 2. Execute steps in sequence
            for step in workflow.steps:
                # Check condition
                if step.condition:
                    step_context = {**resolved_inputs, **step_outputs}
                    if not self._evaluate_condition(step.condition, step_context):
                        logger.info(
                            f"[WorkflowStepRunner] Skipping step {step.name} (condition not met)"
                        )
                        continue

                logger.info(f"[WorkflowStepRunner] Executing step: {step.name}")

                # Interpolate args
                step_context = {**resolved_inputs, **step_outputs}
                resolved_args = self._interpolate_args(step.args, step_context)

                # Execute the tool
                result = await self._execute_step(step, resolved_args, mode)

                # Check for tool errors
                if isinstance(result, dict) and result.get("status") == "error":
                    error_msg = result.get("error", "Unknown error")
                    logger.error(
                        f"[WorkflowStepRunner] Step {step.name} failed: {error_msg}"
                    )
                    raise WorkflowError(f"Step '{step.name}' failed: {error_msg}")

                # Collect outputs
                if isinstance(result, dict):
                    # DEBUG: Log result keys and sources
                    logger.info(f"[WorkflowStepRunner] DEBUG: result keys={list(result.keys())}")
                    logger.info(f"[WorkflowStepRunner] DEBUG: result.sources={result.get('sources', 'NOT_PRESENT')}")

                    for output_name in step.outputs:
                        if output_name in result:
                            step_outputs[output_name] = result[output_name]
                    # Also collect any unlisted outputs
                    for key, value in result.items():
                        if key not in step_outputs and key != "status":
                            step_outputs[key] = value

                    # DEBUG: Log collected outputs
                    logger.info(f"[WorkflowStepRunner] DEBUG: step_outputs keys={list(step_outputs.keys())}")
                    logger.info(f"[WorkflowStepRunner] DEBUG: step_outputs.sources={step_outputs.get('sources', 'NOT_PRESENT')}")

                steps_executed.append(step.name)

            # 3. Validate success criteria
            success = self._validate_success_criteria(
                workflow.success_criteria,
                step_outputs
            )

            elapsed = time.time() - start_time

            if success:
                logger.info(
                    f"[WorkflowStepRunner] Workflow {workflow.name} completed "
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
                    f"[WorkflowStepRunner] Workflow {workflow.name} success criteria not met"
                )
                return await self._handle_fallback(
                    workflow, inputs, context_doc, turn_dir,
                    step_outputs, steps_executed, elapsed, warnings
                )

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[WorkflowStepRunner] Workflow {workflow.name} failed: {e}")

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
            # Handle both "section_2" (full section) and "section_2_field" (sub-field hint)
            parts = from_source.split("_")
            section_num = int(parts[1])
            if hasattr(context_doc, "get_section"):
                section_text = context_doc.get_section(section_num) or ""
            else:
                section_text = ""
            # If just "section_N", return full text
            if len(parts) <= 2:
                return section_text
            # "section_N_field" — return full section text as context
            # The downstream tool/LLM will interpret it
            return section_text
        elif from_source.startswith("content_reference."):
            # Handle nested paths like content_reference.source_url
            if hasattr(context_doc, "get_content_reference"):
                content_ref = context_doc.get_content_reference()
                if content_ref:
                    field = from_source.split(".", 1)[1]
                    return content_ref.get(field)
            return None
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

        When the entire value is a single {{variable}} reference (no surrounding text),
        returns the raw value to preserve type (dict, list, etc).
        """
        resolved = {}

        for key, value in args.items():
            if isinstance(value, str):
                # Check if entire value is a pure variable reference {{var}}
                # This preserves type for dicts, lists, etc.
                pure_var_match = re.fullmatch(r'\s*\{\{([^}|]+)\}\}\s*', value)
                if pure_var_match:
                    var_name = pure_var_match.group(1).strip()
                    resolved[key] = self._get_nested(context, var_name)
                else:
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
        args: Dict[str, Any],
        mode: str,
    ) -> Dict[str, Any]:
        """Execute a single step using ToolCatalog."""
        # Resolve tool URI to canonical name
        tool_name = resolve_tool_uri(step.tool)

        logger.debug(
            f"[WorkflowStepRunner] Tool URI '{step.tool}' -> '{tool_name}'"
        )

        # Execute via catalog with mode validation
        return await self.catalog.execute(
            name=tool_name,
            args=args,
            mode=mode,
        )

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
                    f"[WorkflowStepRunner] Criterion failed: {criterion}"
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

        # If fallback workflow specified, note it (execution handled by caller)
        if workflow.fallback.workflow:
            logger.info(
                f"[WorkflowStepRunner] Fallback workflow available: {workflow.fallback.workflow}"
            )
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
