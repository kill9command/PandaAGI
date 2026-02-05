"""
Workflow Registry - Loads and manages workflow definitions.

Workflows are markdown files with YAML frontmatter that define:
- Triggers for matching
- Input/output schemas
- Step sequences
- Success criteria

Usage:
    registry = WorkflowRegistry()
    registry.load_all()
    workflow = registry.get("intelligence_search")
"""

import logging
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class WorkflowInput:
    """Input parameter for a workflow."""
    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    description: str = ""
    from_source: Optional[str] = None  # e.g., "original_query", "section_2"


@dataclass
class WorkflowOutput:
    """Output declaration for a workflow."""
    name: str
    type: str = "string"
    description: str = ""


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    name: str
    tool: str  # e.g., "internal://internet_research.execute_research"
    args: Dict[str, Any] = field(default_factory=dict)
    outputs: List[str] = field(default_factory=list)
    condition: Optional[str] = None  # e.g., "{{can_create}}"


@dataclass
class WorkflowFallback:
    """Fallback behavior when workflow fails."""
    workflow: Optional[str] = None  # Fallback workflow name
    message: str = "Workflow failed."


@dataclass
class Workflow:
    """A complete workflow definition."""
    name: str
    version: str = "1.0"
    category: str = "general"
    description: str = ""
    triggers: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    tool_bundle: Optional[Path] = None
    bundle_root: Optional[Path] = None
    inputs: Dict[str, WorkflowInput] = field(default_factory=dict)
    outputs: Dict[str, WorkflowOutput] = field(default_factory=dict)
    steps: List[WorkflowStep] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    fallback: Optional[WorkflowFallback] = None
    is_bootstrap: bool = False
    source_path: Optional[Path] = None
    raw_markdown: str = ""


class WorkflowRegistry:
    """
    Registry of available workflows.

    - Loads from apps/workflows/ on startup
    - Loads bundle workflows from panda_system_docs/workflows/bundles
    - Supports dynamic registration
    - Tracks bootstrap vs user-created workflows
    """

    def __init__(self):
        self.workflows: Dict[str, Workflow] = {}
        self.bootstrap_tools: Set[str] = {"file_io", "code_execution"}
        self._intent_index: Dict[str, List[str]] = {}  # intent -> [workflow_names]
        self._trigger_index: Dict[str, str] = {}  # trigger -> workflow_name

    def load_all(
        self,
        workflows_dir: Optional[Path] = None,
    ) -> int:
        """
        Load all workflows from directory.

        Args:
            workflows_dir: Path to workflows directory

        Returns:
            Number of workflows loaded
        """
        if workflows_dir is None:
            # Default to apps/workflows/ relative to project root
            workflows_dir = Path(__file__).parent.parent.parent / "apps" / "workflows"

        if not workflows_dir.exists():
            logger.warning(f"[WorkflowRegistry] Workflows dir not found: {workflows_dir}")
            return 0

        loaded = 0
        for md_path in workflows_dir.rglob("*.md"):
            if md_path.name == "README.md":
                continue
            # Skip template files (contain {{placeholders}} that break YAML parsing)
            if "templates" in md_path.parts:
                continue

            try:
                if md_path.parent.name == "_bootstrap":
                    workflow = self._load_workflow(md_path, is_bootstrap=True)
                else:
                    workflow = self._load_workflow(md_path)

                if workflow:
                    self.workflows[workflow.name] = workflow
                    self._index_workflow(workflow)
                    loaded += 1
                    logger.info(f"[WorkflowRegistry] Loaded workflow: {workflow.name}")
            except Exception as e:
                logger.error(f"[WorkflowRegistry] Failed to load {md_path}: {e}")

        logger.info(f"[WorkflowRegistry] Loaded {loaded} workflows")
        return loaded

    def load_bundles(self, bundles_dir: Optional[Path] = None) -> int:
        """
        Load workflow bundles from panda_system_docs/workflows/bundles.

        Bundle structure:
          panda_system_docs/workflows/bundles/{workflow_name}/workflow.md
        """
        if bundles_dir is None:
            bundles_dir = Path(__file__).parent.parent.parent / "panda_system_docs" / "workflows" / "bundles"

        if not bundles_dir.exists():
            logger.info(f"[WorkflowRegistry] Bundle dir not found: {bundles_dir}")
            return 0

        loaded = 0
        for md_path in bundles_dir.rglob("workflow.md"):
            try:
                workflow = self._load_workflow(md_path)
                if workflow:
                    self.workflows[workflow.name] = workflow
                    self._index_workflow(workflow)
                    loaded += 1
                    logger.info(f"[WorkflowRegistry] Loaded bundle workflow: {workflow.name}")
            except Exception as e:
                logger.error(f"[WorkflowRegistry] Failed to load bundle {md_path}: {e}")

        logger.info(f"[WorkflowRegistry] Loaded {loaded} bundle workflows")
        return loaded

    def _load_workflow(
        self,
        path: Path,
        is_bootstrap: bool = False
    ) -> Optional[Workflow]:
        """Load a single workflow from markdown file."""
        content = path.read_text(encoding="utf-8")

        # Parse YAML frontmatter
        frontmatter, markdown_body = self._parse_frontmatter(content)
        if not frontmatter:
            logger.warning(f"[WorkflowRegistry] No frontmatter in {path}")
            return None

        workflow_name = frontmatter.get("name", path.stem)
        bundle_root = path.parent if path.name == "workflow.md" else None
        tool_bundle = self._resolve_tool_bundle_path(
            frontmatter.get("tool_bundle"),
            workflow_name,
            path,
            bundle_root
        )
        tools = self._normalize_tools(frontmatter.get("tools", []))

        # Build workflow object
        workflow = Workflow(
            name=workflow_name,
            version=str(frontmatter.get("version", "1.0")),
            category=frontmatter.get("category", "general"),
            description=frontmatter.get("description", ""),
            triggers=frontmatter.get("triggers", []),
            tools=tools,
            tool_bundle=tool_bundle,
            bundle_root=bundle_root,
            inputs=self._parse_inputs(frontmatter.get("inputs", {})),
            outputs=self._parse_outputs(frontmatter.get("outputs", {})),
            steps=self._parse_steps(frontmatter.get("steps", [])),
            success_criteria=frontmatter.get("success_criteria", []),
            fallback=self._parse_fallback(frontmatter.get("fallback")),
            is_bootstrap=is_bootstrap or frontmatter.get("bootstrap", False),
            source_path=path,
            raw_markdown=markdown_body,
        )

        return workflow

    def _normalize_tools(self, tools_value: Any) -> List[str]:
        """Normalize tools list from frontmatter."""
        if not tools_value:
            return []
        if isinstance(tools_value, str):
            return [tools_value]
        if isinstance(tools_value, list):
            return [str(tool) for tool in tools_value if tool]
        return []

    def _resolve_tool_bundle_path(
        self,
        tool_bundle_value: Optional[str],
        workflow_name: str,
        workflow_path: Path,
        bundle_root: Optional[Path],
    ) -> Optional[Path]:
        """Resolve tool_bundle path from frontmatter or bundle defaults."""
        if tool_bundle_value:
            raw = str(tool_bundle_value)
            raw = raw.replace("{workflow_name}", workflow_name).replace("{name}", workflow_name)
            candidate = Path(raw).expanduser()

            if not candidate.is_absolute():
                # Try relative to workflow file
                rel_candidate = (workflow_path.parent / candidate).resolve()
                if rel_candidate.exists():
                    return rel_candidate

                # Try relative to project root
                project_root = Path(__file__).parent.parent.parent
                root_candidate = (project_root / candidate).resolve()
                if root_candidate.exists():
                    return root_candidate

            return candidate

        # Default: bundle tools/ directory if this is a bundle workflow
        if bundle_root:
            default_bundle = bundle_root / "tools"
            return default_bundle

        return None

    def _parse_frontmatter(self, content: str) -> tuple[Dict[str, Any], str]:
        """Parse YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return {}, content

        # Find the closing ---
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        yaml_content = parts[1].strip()
        markdown_body = parts[2].strip() if len(parts) > 2 else ""

        try:
            frontmatter = yaml.safe_load(yaml_content) or {}
            return frontmatter, markdown_body
        except yaml.YAMLError as e:
            logger.error(f"[WorkflowRegistry] YAML parse error: {e}")
            return {}, content

    def _parse_inputs(self, inputs_spec: Dict[str, Any]) -> Dict[str, WorkflowInput]:
        """Parse input specifications."""
        inputs = {}
        for name, spec in inputs_spec.items():
            if isinstance(spec, dict):
                inputs[name] = WorkflowInput(
                    name=name,
                    type=spec.get("type", "string"),
                    required=spec.get("required", False),
                    default=spec.get("default"),
                    description=spec.get("description", ""),
                    from_source=spec.get("from"),
                )
            else:
                inputs[name] = WorkflowInput(name=name, default=spec)
        return inputs

    def _parse_outputs(self, outputs_spec: Dict[str, Any]) -> Dict[str, WorkflowOutput]:
        """Parse output specifications."""
        outputs = {}
        for name, spec in outputs_spec.items():
            if isinstance(spec, dict):
                outputs[name] = WorkflowOutput(
                    name=name,
                    type=spec.get("type", "string"),
                    description=spec.get("description", ""),
                )
            else:
                outputs[name] = WorkflowOutput(name=name)
        return outputs

    def _parse_steps(self, steps_spec: List[Dict[str, Any]]) -> List[WorkflowStep]:
        """Parse step specifications."""
        steps = []
        for spec in steps_spec:
            steps.append(WorkflowStep(
                name=spec.get("name", f"step_{len(steps)}"),
                tool=spec.get("tool", ""),
                args=spec.get("args", {}),
                outputs=spec.get("outputs", []),
                condition=spec.get("condition"),
            ))
        return steps

    def _parse_fallback(self, fallback_spec: Optional[Dict]) -> Optional[WorkflowFallback]:
        """Parse fallback specification."""
        if not fallback_spec:
            return None
        return WorkflowFallback(
            workflow=fallback_spec.get("workflow"),
            message=fallback_spec.get("message", "Workflow failed."),
        )

    def _index_workflow(self, workflow: Workflow):
        """Index workflow by triggers for fast lookup."""
        for trigger in workflow.triggers:
            # Handle dict-style trigger: {intent: commerce}
            if isinstance(trigger, dict):
                if "intent" in trigger:
                    intent = trigger["intent"]
                    if intent not in self._intent_index:
                        self._intent_index[intent] = []
                    self._intent_index[intent].append(workflow.name)
                continue

            # Handle string trigger
            if not isinstance(trigger, str):
                continue

            if trigger.startswith("intent:"):
                # Intent trigger: "intent: commerce"
                intent = trigger.split(":", 1)[1].strip()
                if intent not in self._intent_index:
                    self._intent_index[intent] = []
                self._intent_index[intent].append(workflow.name)
            else:
                # Pattern trigger: "find me {product}"
                self._trigger_index[trigger.lower()] = workflow.name

    def get(self, name: str) -> Optional[Workflow]:
        """Get a workflow by name."""
        return self.workflows.get(name)

    def get_by_intent(self, intent: str) -> List[Workflow]:
        """Get workflows matching an intent."""
        names = self._intent_index.get(intent, [])
        return [self.workflows[n] for n in names if n in self.workflows]

    def get_by_category(self, category: str) -> List[Workflow]:
        """Get workflows in a category."""
        return [w for w in self.workflows.values() if w.category == category]

    def all(self) -> List[Workflow]:
        """Get all workflows."""
        return list(self.workflows.values())

    def validate_tools(self, tools: List[str]) -> tuple[List[str], List[str]]:
        """
        Separate valid tools from bootstrap tools.

        Returns:
            Tuple of (valid_tools, bootstrap_tools)
        """
        valid = []
        bootstrap = []

        for tool in tools:
            # Extract tool name from full path
            tool_name = tool.split("://")[-1].split(".")[0]
            if tool_name in self.bootstrap_tools:
                bootstrap.append(tool)
            else:
                valid.append(tool)

        return valid, bootstrap

    def check_bootstrap(self, bootstrap_tools: List[str]) -> tuple[bool, str]:
        """
        Check if workflow can be created (no bootstrap dependencies).

        Returns:
            Tuple of (can_create, reason)
        """
        if bootstrap_tools:
            return False, f"Requires bootstrap tools: {bootstrap_tools}"
        return True, ""

    def register(self, workflow: Workflow) -> bool:
        """
        Register a workflow dynamically.

        Args:
            workflow: Workflow to register

        Returns:
            True if registered successfully
        """
        if workflow.name in self.workflows:
            logger.warning(f"[WorkflowRegistry] Overwriting workflow: {workflow.name}")

        self.workflows[workflow.name] = workflow
        self._index_workflow(workflow)
        logger.info(f"[WorkflowRegistry] Registered workflow: {workflow.name}")
        return True

    def register_from_path(self, path: Path) -> Optional[Workflow]:
        """
        Register a workflow from a file path.

        Args:
            path: Path to workflow markdown file

        Returns:
            Workflow if registered successfully, else None
        """
        workflow = self._load_workflow(path)
        if workflow:
            self.register(workflow)
            return workflow
        return None

    def unregister(self, name: str) -> bool:
        """
        Unregister a workflow.

        Args:
            name: Workflow name to unregister

        Returns:
            True if unregistered successfully
        """
        if name not in self.workflows:
            return False

        workflow = self.workflows.pop(name)

        # Remove from indexes
        for intent, names in list(self._intent_index.items()):
            if name in names:
                names.remove(name)

        for trigger, wf_name in list(self._trigger_index.items()):
            if wf_name == name:
                del self._trigger_index[trigger]

        logger.info(f"[WorkflowRegistry] Unregistered workflow: {name}")
        return True

    def list_names(self) -> List[str]:
        """List all workflow names."""
        return list(self.workflows.keys())

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        categories = {}
        for w in self.workflows.values():
            categories[w.category] = categories.get(w.category, 0) + 1

        return {
            "total": len(self.workflows),
            "by_category": categories,
            "bootstrap_tools": list(self.bootstrap_tools),
            "intents_indexed": list(self._intent_index.keys()),
        }
