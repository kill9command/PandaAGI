"""
Tool Registration - Register all tool handlers with ToolCatalog.

This module handles the registration of all tools with the ToolCatalog,
replacing both the old workflow_executor tool registration and the
hardcoded tool dispatch.

Tool naming convention:
- internet.research - Internet research
- memory.search/save/delete - Memory operations
- file.read/write/edit/glob/grep - File operations (code mode)
- git.* - Git operations (code mode only)
- llm.call - Direct LLM call (for workflows)
- workflow.register - Register new workflow dynamically
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from libs.gateway.execution.tool_catalog import ToolCatalog
    from libs.gateway.execution.workflow_registry import WorkflowRegistry

logger = logging.getLogger(__name__)


class ToolRegistrar:
    """
    Registers all tool handlers with the ToolCatalog.

    This centralizes tool registration logic that was previously
    scattered in UnifiedFlow._register_all_tools().
    """

    def __init__(
        self,
        tool_catalog: "ToolCatalog",
        workflow_registry: "WorkflowRegistry",
        tool_executor: Any  # Reference to ToolExecutor for method access
    ):
        self.tool_catalog = tool_catalog
        self.workflow_registry = workflow_registry
        self.tool_executor = tool_executor

    def register_all(self) -> int:
        """
        Register all tool handlers.

        Returns:
            Number of tools registered
        """
        self._register_internet_research_tools()
        self._register_memory_tools()
        self._register_file_tools()
        self._register_git_tools()
        self._register_llm_tools()
        self._register_workflow_tools()

        count = len(self.tool_catalog.list_tools())
        logger.info(f"[ToolRegistrar] Registered {count} tools in catalog")
        return count

    def _register_internet_research_tools(self):
        """Register internet research tools."""

        async def execute_research(goal: str, intent: str = "informational", context: str = "", task: str = "", max_visits: int = 8, **kwargs):
            """Phase 1 intelligence research via workflow."""
            from apps.tools.internet_research import execute_full_research
            result = await execute_full_research(
                goal=goal,
                intent=intent,
                context=context,
                task=task,
                max_visits=max_visits,
                **kwargs
            )
            return result

        self.tool_catalog.register(
            "internet.research",
            execute_research,
            description="Execute internet research for a given goal"
        )

        # Phase 2 product finding
        async def execute_phase2(phase1_intelligence: dict = None, goal: str = "", vendor_hints: list = None, search_terms: list = None, price_range: dict = None, target_vendors: int = 3, **kwargs):
            """Phase 2 product finding using Phase 1 intelligence."""
            from apps.tools.internet_research import execute_phase2 as do_phase2
            result = await do_phase2(
                phase1_intelligence=phase1_intelligence or {},
                goal=goal,
                vendor_hints=vendor_hints or [],
                search_terms=search_terms or [],
                price_range=price_range or {},
                target_vendors=target_vendors,
                **kwargs
            )
            return result.to_dict() if hasattr(result, 'to_dict') else result

        self.tool_catalog.register(
            "internet.research.phase2",
            execute_phase2,
            description="Execute Phase 2 product finding"
        )

        # Legacy URIs for backwards compatibility during migration
        self.tool_catalog.register(
            "internal://internet_research.execute_research",
            execute_research,
            description="[Legacy] Execute internet research"
        )
        self.tool_catalog.register(
            "internal://internet_research.execute_full_research",
            execute_research,
            description="[Legacy] Execute full internet research"
        )
        self.tool_catalog.register(
            "internal://internet_research.execute_phase2",
            execute_phase2,
            description="[Legacy] Execute Phase 2 product finding"
        )

    def _register_memory_tools(self):
        """Register memory tools."""
        te = self.tool_executor

        async def memory_search_handler(query: str, **kwargs):
            """Search memory for relevant items."""
            return await te.execute_memory_search({"query": query, **kwargs})

        async def memory_save_handler(content: str, **kwargs):
            """Save content to memory."""
            return await te.execute_memory_save({"content": content, **kwargs})

        async def memory_delete_handler(memory_id: str, **kwargs):
            """Delete a memory item."""
            return await te.execute_memory_delete({"memory_id": memory_id, **kwargs})

        self.tool_catalog.register(
            "memory.search",
            memory_search_handler,
            description="Search memory for relevant items"
        )
        self.tool_catalog.register(
            "memory.save",
            memory_save_handler,
            description="Save content to memory"
        )
        self.tool_catalog.register(
            "memory.delete",
            memory_delete_handler,
            description="Delete a memory item"
        )

    def _register_file_tools(self):
        """Register file tools (code mode only for write/edit)."""
        te = self.tool_executor

        async def file_read_handler(path: str, **kwargs):
            """Read file contents."""
            return await te.execute_file_read({"path": path, **kwargs})

        async def file_read_outline_handler(path: str, **kwargs):
            """Read file outline/structure."""
            return await te.execute_file_read_outline({"path": path, **kwargs})

        async def file_glob_handler(pattern: str, **kwargs):
            """Find files matching a pattern."""
            return await te.execute_file_glob({"pattern": pattern, **kwargs})

        async def file_grep_handler(pattern: str, **kwargs):
            """Search file contents."""
            return await te.execute_file_grep({"pattern": pattern, **kwargs})

        async def file_write_handler(path: str, content: str, **kwargs):
            """Write content to a file."""
            return await te.execute_file_write({"path": path, "content": content, **kwargs})

        async def file_edit_handler(path: str, **kwargs):
            """Edit a file."""
            return await te.execute_file_edit({"path": path, **kwargs})

        self.tool_catalog.register(
            "file.read",
            file_read_handler,
            description="Read file contents"
        )
        self.tool_catalog.register(
            "file.read_outline",
            file_read_outline_handler,
            description="Read file outline/structure"
        )
        self.tool_catalog.register(
            "file.glob",
            file_glob_handler,
            description="Find files matching a pattern"
        )
        self.tool_catalog.register(
            "file.grep",
            file_grep_handler,
            description="Search file contents"
        )
        self.tool_catalog.register(
            "file.write",
            file_write_handler,
            mode_required="code",
            description="Write content to a file (code mode only)"
        )
        self.tool_catalog.register(
            "file.edit",
            file_edit_handler,
            mode_required="code",
            description="Edit a file (code mode only)"
        )

        # Legacy file.write alias for bootstrap protocol
        self.tool_catalog.register(
            "bootstrap://file_io.write",
            file_write_handler,
            mode_required="code",
            description="[Legacy] Write content to a file"
        )

    def _register_git_tools(self):
        """Register git tools (code mode only)."""
        te = self.tool_executor

        async def git_status_handler(**kwargs):
            """Get git status."""
            return await te.execute_git_tool("git.status", kwargs)

        async def git_diff_handler(**kwargs):
            """Get git diff."""
            return await te.execute_git_tool("git.diff", kwargs)

        async def git_log_handler(**kwargs):
            """Get git log."""
            return await te.execute_git_tool("git.log", kwargs)

        async def git_commit_handler(**kwargs):
            """Create a git commit."""
            return await te.execute_git_tool("git.commit", kwargs)

        self.tool_catalog.register(
            "git.status",
            git_status_handler,
            mode_required="code",
            description="Get git repository status"
        )
        self.tool_catalog.register(
            "git.diff",
            git_diff_handler,
            mode_required="code",
            description="Get git diff"
        )
        self.tool_catalog.register(
            "git.log",
            git_log_handler,
            mode_required="code",
            description="Get git log"
        )
        self.tool_catalog.register(
            "git.commit",
            git_commit_handler,
            mode_required="code",
            description="Create a git commit"
        )

    def _register_llm_tools(self):
        """Register LLM call tools (for workflows)."""

        async def llm_call_handler(prompt: str, role: str = "mind", max_tokens: int = 1500, **kwargs):
            """Direct LLM call for workflows."""
            from libs.llm.llm_client import LLMClient
            client = LLMClient()
            result = await client.generate(
                prompt=prompt,
                role=role,
                max_tokens=max_tokens,
            )
            return {"result": result, "status": "success"}

        self.tool_catalog.register(
            "llm.call",
            llm_call_handler,
            description="Direct LLM call for workflows"
        )
        self.tool_catalog.register(
            "internal://llm.call",
            llm_call_handler,
            description="[Legacy] Direct LLM call"
        )

    def _register_workflow_tools(self):
        """Register workflow management tools."""

        # Tool creation handler
        async def tool_create_handler(
            workflow: str = "",
            tool_name: str = "",
            spec: str = "",
            code: str = "",
            tests: str = "",
            skip_tests: bool = False,
            **kwargs
        ):
            """Create a new tool in a workflow bundle."""
            from libs.gateway.self_extension import create_tool_handler
            return await create_tool_handler(
                workflow=workflow,
                tool_name=tool_name,
                spec=spec,
                code=code,
                tests=tests,
                skip_tests=skip_tests,
                **kwargs
            )

        self.tool_catalog.register(
            "tool.create",
            tool_create_handler,
            mode_required="code",
            description="Create a new tool in a workflow bundle"
        )

        # Tool generation handler (LLM-powered)
        async def tool_generate_handler(
            workflow: str = "",
            tool_name: str = "",
            description: str = "",
            requirements: str = "",
            skip_tests: bool = False,
            **kwargs
        ):
            """Generate and create a new tool using LLM."""
            from libs.gateway.self_extension import generate_tool, get_tool_creator

            # Step 1: Generate tool spec/code/tests using LLM
            generated = await generate_tool(
                tool_name=tool_name,
                description=description,
                workflow_name=workflow,
                requirements=requirements,
            )

            if not generated.success:
                return {
                    "status": "error",
                    "error": f"LLM generation failed: {generated.error}",
                    "tool_name": tool_name,
                }

            # Step 2: Create the tool using the generated content
            creator = get_tool_creator()
            result = await creator.create_tool(
                workflow_name=workflow,
                tool_name=tool_name,
                spec_content=generated.spec,
                impl_content=generated.code,
                test_content=generated.tests,
                skip_tests=skip_tests,
            )

            return {
                "status": "success" if result.success else "error",
                "tool_name": result.tool_name,
                "spec_path": str(result.spec_path) if result.spec_path else None,
                "impl_path": str(result.impl_path) if result.impl_path else None,
                "test_path": str(result.test_path) if result.test_path else None,
                "registered": result.registered,
                "error": result.error,
                "validation_errors": result.validation_errors,
                "test_summary": result.test_result.summary if result.test_result else None,
                "dependencies": generated.dependencies,
            }

        self.tool_catalog.register(
            "tool.generate",
            tool_generate_handler,
            mode_required="code",
            description="Generate and create a new tool using LLM"
        )

        async def workflow_register_handler(
            name: str = "",
            content: str = "",
            path: str = "",
            bundle_dir: str = "",
            **kwargs
        ):
            """Register a new workflow dynamically."""
            workflow_path: Optional[Path] = None

            if path:
                workflow_path = Path(path)
                if workflow_path.is_dir():
                    workflow_path = workflow_path / "workflow.md"
                if not workflow_path.exists():
                    return {
                        "status": "error",
                        "error": f"Workflow path not found: {workflow_path}",
                    }
            else:
                if not content:
                    return {"status": "error", "error": "Missing content or path"}

                if not name:
                    frontmatter, _ = self.workflow_registry._parse_frontmatter(content)
                    name = frontmatter.get("name", "")

                if not name:
                    return {"status": "error", "error": "Missing workflow name"}

                bundle_root = Path(bundle_dir) if bundle_dir else self._get_workflow_bundles_root()
                workflow_path = bundle_root / name / "workflow.md"
                workflow_path.parent.mkdir(parents=True, exist_ok=True)
                workflow_path.write_text(content)

            workflow_obj = self.workflow_registry.register_from_path(workflow_path) if workflow_path else None
            tools_registered: List[str] = []
            if workflow_obj and workflow_obj.tool_bundle:
                tools_registered = self.tool_catalog.register_tools_from_bundle(Path(workflow_obj.tool_bundle))

            if not workflow_obj:
                return {"status": "error", "error": "Failed to register workflow"}

            return {
                "status": "success",
                "workflow": workflow_obj.name,
                "workflow_path": str(workflow_path),
                "tools_registered": tools_registered,
            }

        self.tool_catalog.register(
            "workflow.register",
            workflow_register_handler,
            description="Register a new workflow dynamically"
        )
        self.tool_catalog.register(
            "internal://workflow_registry.register",
            workflow_register_handler,
            description="[Legacy] Register a new workflow dynamically"
        )

        # Workflow validation tools
        async def workflow_validate_tools_handler(tools: list = None, **kwargs):
            """Validate that required tools exist in catalog."""
            tools = tools or []
            missing = [t for t in tools if not self.tool_catalog.has_tool(t)]
            return {
                "status": "success" if not missing else "error",
                "valid": not missing,
                "missing_tools": missing
            }

        async def workflow_check_bootstrap_handler(tools: list = None, **kwargs):
            """Check if workflow uses bootstrap tools (code mode only)."""
            bootstrap_tools = ["file.write", "file.edit", "git.commit", "git.status", "git.diff"]
            tools = tools or []
            uses_bootstrap = any(t in bootstrap_tools or "bootstrap://" in t for t in tools)
            return {
                "status": "success",
                "uses_bootstrap": uses_bootstrap,
                "bootstrap_tools": [t for t in tools if t in bootstrap_tools or "bootstrap://" in t]
            }

        self.tool_catalog.register(
            "workflow.validate_tools",
            workflow_validate_tools_handler,
            description="Validate workflow tool requirements"
        )
        self.tool_catalog.register(
            "internal://workflow_registry.validate_tools",
            workflow_validate_tools_handler,
            description="[Legacy] Validate workflow tool requirements"
        )
        self.tool_catalog.register(
            "workflow.check_bootstrap",
            workflow_check_bootstrap_handler,
            description="Check if workflow uses bootstrap (code mode) tools"
        )
        self.tool_catalog.register(
            "internal://workflow_registry.check_bootstrap",
            workflow_check_bootstrap_handler,
            description="[Legacy] Check if workflow uses bootstrap tools"
        )

    def _get_workflow_bundles_root(self) -> Path:
        """Return the root directory for workflow bundles."""
        return Path(__file__).parent.parent.parent.parent / "panda_system_docs" / "workflows" / "bundles"


def register_all_tools(
    tool_catalog: "ToolCatalog",
    workflow_registry: "WorkflowRegistry",
    tool_executor: Any
) -> int:
    """
    Convenience function to register all tools.

    Args:
        tool_catalog: The ToolCatalog to register tools with
        workflow_registry: The WorkflowRegistry for workflow operations
        tool_executor: Reference to ToolExecutor for method access

    Returns:
        Number of tools registered
    """
    registrar = ToolRegistrar(tool_catalog, workflow_registry, tool_executor)
    return registrar.register_all()
