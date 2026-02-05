"""
Tool Catalog - Unified registry for all tools available to Coordinator and workflows.

Replaces:
- WorkflowExecutor's internal tool_catalog dict
- Coordinator's hardcoded tool dispatch

Design:
- Tools register with name, handler, and optional mode requirement
- Mode validation ensures code-only tools can't run in chat mode
- Single source of truth for all tool dispatch

Usage:
    catalog = ToolCatalog()
    catalog.register("internet.research", handler_fn)
    catalog.register("git.commit", handler_fn, mode_required="code")

    result = await catalog.execute("internet.research", args, context)
"""

import logging
import hashlib
import importlib.util
import inspect
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Definition of a registered tool."""
    name: str
    handler: Callable[..., Awaitable[Any]]
    mode_required: Optional[str] = None  # "code", "chat", or None for any
    description: str = ""


class ToolCatalog:
    """
    Unified tool registry for Coordinator and workflows.

    Tool naming convention:
        - internet.research - Internet research tool
        - memory.search, memory.save, memory.delete - Memory tools
        - file.read, file.write, file.edit, file.glob, file.grep - File tools
        - git.status, git.commit, git.diff - Git tools (code mode only)
        - bash.execute - Bash execution (code mode only)
        - llm.call - Direct LLM call (for workflows)
        - workflow.register - Register new workflow dynamically

    Mode validation:
        - None: Tool available in any mode
        - "code": Tool only available in code mode
        - "chat": Tool only available in chat mode
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register_tools_from_bundle(self, tools_dir: Path) -> List[str]:
        """
        Register tools defined in a workflow bundle's tools directory.

        Expects paired files:
          tools/{tool_spec}.md
          tools/{tool_spec}.py
        """
        registered: List[str] = []

        if not tools_dir.exists():
            logger.warning(f"[ToolCatalog] Tools dir not found: {tools_dir}")
            return registered

        for spec_path in sorted(tools_dir.glob("*.md")):
            if spec_path.name.lower() == "readme.md":
                continue

            spec = self._load_tool_spec(spec_path)
            if not spec:
                continue

            tool_name = spec["name"]
            if self.has_tool(tool_name) and not spec.get("override", False):
                logger.info(f"[ToolCatalog] Tool already registered, skipping: {tool_name}")
                continue

            handler = self._load_tool_handler(spec, spec_path, tools_dir)
            if not handler:
                continue

            self.register(
                tool_name,
                handler,
                mode_required=spec.get("mode_required"),
                description=spec.get("description", ""),
            )
            registered.append(tool_name)

        if registered:
            logger.info(f"[ToolCatalog] Registered {len(registered)} bundle tools from {tools_dir}")
        return registered

    def _load_tool_spec(self, spec_path: Path) -> Optional[Dict[str, Any]]:
        """Load tool spec from markdown frontmatter."""
        try:
            content = spec_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"[ToolCatalog] Failed to read tool spec {spec_path}: {e}")
            return None

        frontmatter, _ = self._parse_frontmatter(content)
        spec = frontmatter or {}

        name = (
            spec.get("name")
            or spec.get("tool")
            or spec.get("tool_name")
            or spec.get("id")
        )
        if not name:
            name = self._infer_tool_name_from_content(content) or self._infer_tool_name_from_filename(spec_path)

        if not name:
            logger.warning(f"[ToolCatalog] Tool spec missing name: {spec_path}")
            return None

        description = str(spec.get("description", "")).strip()
        mode = spec.get("mode") or spec.get("mode_required") or spec.get("requires_mode")
        mode_required = self._normalize_mode(mode)

        entrypoint = (
            spec.get("entrypoint")
            or spec.get("function")
            or spec.get("callable")
            or spec.get("handler")
        )
        module_ref = (
            spec.get("module")
            or spec.get("python")
            or spec.get("python_file")
            or spec.get("file")
            or spec.get("script")
        )

        override = bool(spec.get("override") or spec.get("allow_override"))

        return {
            "name": name,
            "description": description,
            "mode_required": mode_required,
            "entrypoint": entrypoint,
            "module": module_ref,
            "override": override,
        }

    def _load_tool_handler(
        self,
        spec: Dict[str, Any],
        spec_path: Path,
        tools_dir: Path,
    ) -> Optional[Callable[..., Awaitable[Any]]]:
        """Load tool handler from python module."""
        entrypoint = spec.get("entrypoint") or spec_path.stem
        module_ref = spec.get("module")

        if entrypoint and ":" in entrypoint:
            module_ref, entrypoint = entrypoint.split(":", 1)

        if not module_ref:
            module_ref = spec_path.with_suffix(".py").name

        module_path = Path(module_ref)
        if not module_path.is_absolute():
            module_path = tools_dir / module_path

        if module_path.suffix == "":
            module_path = module_path.with_suffix(".py")

        if not module_path.exists():
            logger.warning(f"[ToolCatalog] Tool code file not found: {module_path}")
            return None

        module = self._load_module_from_file(module_path)
        if not module:
            return None

        handler = getattr(module, entrypoint, None)
        if not callable(handler):
            logger.warning(f"[ToolCatalog] Tool handler not found: {entrypoint} in {module_path}")
            return None

        return self._wrap_handler(handler)

    def _load_module_from_file(self, module_path: Path):
        """Load a python module from file path."""
        module_hash = hashlib.sha1(str(module_path).encode("utf-8")).hexdigest()[:12]
        module_name = f"bundle_tool_{module_path.stem}_{module_hash}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if not spec or not spec.loader:
                logger.error(f"[ToolCatalog] Failed to load module spec: {module_path}")
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[call-arg]
            return module
        except Exception as e:
            logger.error(f"[ToolCatalog] Module load failed for {module_path}: {e}")
            return None

    def _wrap_handler(self, handler: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
        """Ensure tool handler is async."""
        if inspect.iscoroutinefunction(handler):
            return handler

        async def async_wrapper(**kwargs):
            return handler(**kwargs)

        return async_wrapper

    def _infer_tool_name_from_filename(self, spec_path: Path) -> str:
        """Infer tool name from spec filename."""
        return spec_path.stem.replace("_", ".")

    def _infer_tool_name_from_content(self, content: str) -> Optional[str]:
        """Try to infer tool name from content if frontmatter is missing."""
        match = re.search(r'^\s*name:\s*([a-zA-Z0-9_.-]+)\s*$', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

    def _normalize_mode(self, mode: Optional[str]) -> Optional[str]:
        """Normalize mode string to catalog format."""
        if not mode:
            return None
        mode = str(mode).strip().lower()
        if mode in ("any", "all", "both"):
            return None
        if mode in ("code", "chat"):
            return mode
        return None

    def _parse_frontmatter(self, content: str) -> Tuple[Dict[str, Any], str]:
        """Parse YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return {}, content

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        yaml_content = parts[1].strip()
        markdown_body = parts[2].strip() if len(parts) > 2 else ""

        try:
            frontmatter = yaml.safe_load(yaml_content) or {}
            return frontmatter, markdown_body
        except yaml.YAMLError as e:
            logger.error(f"[ToolCatalog] YAML parse error: {e}")
            return {}, content

    def register(
        self,
        name: str,
        handler: Callable[..., Awaitable[Any]],
        mode_required: Optional[str] = None,
        description: str = "",
    ) -> None:
        """
        Register a tool handler.

        Args:
            name: Tool name (e.g., "internet.research")
            handler: Async function to call when tool is invoked
            mode_required: "code", "chat", or None for any mode
            description: Human-readable description of what the tool does
        """
        self._tools[name] = ToolDefinition(
            name=name,
            handler=handler,
            mode_required=mode_required,
            description=description,
        )
        logger.debug(f"[ToolCatalog] Registered tool: {name} (mode: {mode_required or 'any'})")

    def unregister(self, name: str) -> bool:
        """
        Unregister a tool.

        Args:
            name: Tool name to remove

        Returns:
            True if tool was removed, False if not found
        """
        if name in self._tools:
            del self._tools[name]
            logger.debug(f"[ToolCatalog] Unregistered tool: {name}")
            return True
        return False

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get tool definition by name."""
        return self._tools.get(name)

    def validate_mode(
        self,
        name: str,
        current_mode: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a tool can be used in the current mode.

        Args:
            name: Tool name
            current_mode: Current operating mode ("code" or "chat")

        Returns:
            Tuple of (is_valid, error_reason)
            - (True, None) if tool can be used
            - (False, "reason") if tool cannot be used
        """
        tool = self._tools.get(name)

        if not tool:
            return False, f"Unknown tool: {name}"

        if tool.mode_required is None:
            # Tool works in any mode
            return True, None

        if tool.mode_required != current_mode:
            return False, f"Tool '{name}' requires {tool.mode_required} mode (current: {current_mode})"

        return True, None

    async def execute(
        self,
        name: str,
        args: Dict[str, Any],
        context: Optional[Any] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a tool by name.

        Args:
            name: Tool name
            args: Arguments to pass to the tool handler
            context: Optional context document
            mode: Current mode for validation (if None, skips mode check)

        Returns:
            Dict with execution result, always includes "status" key
        """
        tool = self._tools.get(name)

        if not tool:
            logger.error(f"[ToolCatalog] Unknown tool: {name}")
            return {
                "status": "error",
                "error": f"Unknown tool: {name}",
                "available_tools": list(self._tools.keys()),
            }

        # Validate mode if provided
        if mode is not None:
            valid, reason = self.validate_mode(name, mode)
            if not valid:
                logger.warning(f"[ToolCatalog] Mode validation failed: {reason}")
                return {
                    "status": "error",
                    "error": reason,
                    "mode_required": tool.mode_required,
                }

        # Execute the handler
        try:
            logger.info(f"[ToolCatalog] Executing tool: {name}")
            result = await tool.handler(**args)

            # Normalize result to dict
            if result is None:
                result = {"status": "success"}
            elif not isinstance(result, dict):
                result = {"status": "success", "result": result}
            elif "status" not in result:
                result["status"] = "success"

            return result

        except TypeError as e:
            # Argument mismatch
            logger.error(f"[ToolCatalog] Tool {name} argument error: {e}")
            return {
                "status": "error",
                "error": f"Invalid arguments for tool '{name}': {e}",
            }
        except Exception as e:
            logger.error(f"[ToolCatalog] Tool {name} execution failed: {e}")
            return {
                "status": "error",
                "error": f"Tool execution failed: {e}",
            }

    def list_tools(self, mode: Optional[str] = None) -> List[str]:
        """
        List available tools.

        Args:
            mode: If provided, only return tools available in this mode

        Returns:
            List of tool names
        """
        if mode is None:
            return list(self._tools.keys())

        return [
            name for name, tool in self._tools.items()
            if tool.mode_required is None or tool.mode_required == mode
        ]

    def list_tools_with_descriptions(
        self,
        mode: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        List tools with their descriptions.

        Args:
            mode: If provided, only return tools available in this mode

        Returns:
            List of dicts with 'name', 'description', and 'mode' keys
        """
        result = []

        for name, tool in self._tools.items():
            if mode is not None and tool.mode_required is not None:
                if tool.mode_required != mode:
                    continue

            result.append({
                "name": name,
                "description": tool.description,
                "mode": tool.mode_required or "any",
            })

        return result

    def get_tool_names_by_category(self) -> Dict[str, List[str]]:
        """
        Group tools by their category prefix.

        Returns:
            Dict mapping category to list of tool names
            e.g., {"internet": ["internet.research"], "memory": ["memory.search", ...]}
        """
        categories: Dict[str, List[str]] = {}

        for name in self._tools:
            if "." in name:
                category = name.split(".")[0]
            else:
                category = "other"

            if category not in categories:
                categories[category] = []
            categories[category].append(name)

        return categories


# URI mapping for backwards compatibility with workflow definitions
# Maps old internal:// URIs to new tool names
URI_TO_TOOL_NAME = {
    "internal://internet_research.execute_research": "internet.research",
    "internal://internet_research.execute_full_research": "internet.research_full",
    "internal://memory.search": "memory.search",
    "internal://memory.save": "memory.save",
    "internal://memory.delete": "memory.delete",
    "internal://llm.call": "llm.call",
    "bootstrap://file_io.read": "file.read",
    "bootstrap://file_io.write": "file.write",
    "bootstrap://file_io.edit": "file.edit",
    "bootstrap://file_io.glob": "file.glob",
    "bootstrap://file_io.grep": "file.grep",
    "internal://workflow_registry.register": "workflow.register",
}


def resolve_tool_uri(uri: str) -> str:
    """
    Resolve a tool URI to its canonical name.

    Supports both old URI format and new canonical names:
    - "internal://internet_research.execute_research" -> "internet.research"
    - "internet.research" -> "internet.research" (passthrough)

    Args:
        uri: Tool URI or canonical name

    Returns:
        Canonical tool name
    """
    # Check if it's an old-style URI
    if uri in URI_TO_TOOL_NAME:
        return URI_TO_TOOL_NAME[uri]

    # Already a canonical name or unknown URI - pass through
    return uri


# Module-level singleton for shared tool catalog
_catalog: Optional[ToolCatalog] = None


def get_tool_catalog() -> ToolCatalog:
    """Get or create the singleton tool catalog."""
    global _catalog
    if _catalog is None:
        _catalog = ToolCatalog()
    return _catalog
