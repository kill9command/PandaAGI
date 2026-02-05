"""
Tool Creator - Creates tools in workflow bundles.

Architecture Reference:
- architecture/concepts/SELF_BUILDING_SYSTEM.md
- architecture/concepts/TOOL_SYSTEM.md

Creation Flow:
1. Validate spec schema
2. Create backup of existing files (if any)
3. Write spec (.md) and implementation (.py) files
4. Run tests in sandbox
5. On failure: rollback and record failure
6. On success: register tool in catalog
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from libs.gateway.self_extension.spec_validator import (
    ToolSpecValidator,
    ValidationResult,
    get_spec_validator,
)
from libs.gateway.self_extension.backup_manager import (
    BackupManager,
    RollbackContext,
    get_backup_manager,
)
from libs.gateway.self_extension.sandbox_runner import (
    SandboxRunner,
    SandboxResult,
    get_sandbox_runner,
    run_tool_tests,
)

if TYPE_CHECKING:
    from libs.gateway.execution.tool_catalog import ToolCatalog

logger = logging.getLogger(__name__)


@dataclass
class ToolCreationResult:
    """Result of tool creation."""
    success: bool
    tool_name: str
    spec_path: Optional[Path] = None
    impl_path: Optional[Path] = None
    test_path: Optional[Path] = None
    error: Optional[str] = None
    validation_errors: Optional[List[str]] = None
    test_result: Optional[SandboxResult] = None
    registered: bool = False


class ToolCreator:
    """
    Creates tools in workflow bundles with validation, testing, and rollback.

    Responsibilities:
    - Validate tool spec schema
    - Write tool files (spec.md, impl.py, test.py)
    - Run tests in sandbox
    - Register tool in catalog on success
    - Rollback on failure
    """

    def __init__(
        self,
        bundles_root: Path,
        tool_catalog: Optional["ToolCatalog"] = None,
        spec_validator: Optional[ToolSpecValidator] = None,
        sandbox_runner: Optional[SandboxRunner] = None,
    ):
        """
        Initialize tool creator.

        Args:
            bundles_root: Root directory for workflow bundles
            tool_catalog: Tool catalog for registration (optional)
            spec_validator: Spec validator (optional, uses singleton)
            sandbox_runner: Test runner (optional, uses singleton)
        """
        self.bundles_root = Path(bundles_root)
        self.tool_catalog = tool_catalog
        self.spec_validator = spec_validator or get_spec_validator()
        self.sandbox_runner = sandbox_runner or get_sandbox_runner()

    async def create_tool(
        self,
        workflow_name: str,
        tool_name: str,
        spec_content: str,
        impl_content: str,
        test_content: Optional[str] = None,
        skip_tests: bool = False,
        plan_state_path: Optional[Path] = None,
    ) -> ToolCreationResult:
        """
        Create a tool in a workflow bundle.

        Args:
            workflow_name: Name of the workflow bundle
            tool_name: Name of the tool (e.g., "spreadsheet_read")
            spec_content: Tool spec markdown with YAML frontmatter
            impl_content: Python implementation code
            test_content: Optional test code
            skip_tests: Skip test execution (for bootstrap)
            plan_state_path: Path to plan_state.json for failure recording

        Returns:
            ToolCreationResult with success/failure details
        """
        result = ToolCreationResult(success=False, tool_name=tool_name)

        # 1. Validate spec
        validation = self.spec_validator.validate_spec_content(spec_content)
        if not validation.valid:
            result.error = "Spec validation failed"
            result.validation_errors = [f"{e.field}: {e.message}" for e in validation.errors]
            logger.warning(f"[ToolCreator] Spec validation failed: {result.validation_errors}")
            return result

        # 2. Setup paths
        bundle_dir = self.bundles_root / workflow_name
        tools_dir = bundle_dir / "tools"
        tests_dir = bundle_dir / "tests"

        # Derive filenames from tool_name
        safe_name = tool_name.replace(".", "_")
        spec_path = tools_dir / f"{safe_name}.md"
        impl_path = tools_dir / f"{safe_name}.py"
        test_path = tests_dir / f"{safe_name}_test.py" if test_content else None

        result.spec_path = spec_path
        result.impl_path = impl_path
        result.test_path = test_path

        # 3. Backup existing files and create with rollback support
        backup_manager = get_backup_manager(bundle_dir)
        files_to_backup = [spec_path, impl_path]
        if test_path:
            files_to_backup.append(test_path)

        with RollbackContext(backup_manager, files_to_backup, plan_state_path) as ctx:
            try:
                # Create directories
                tools_dir.mkdir(parents=True, exist_ok=True)
                if test_content:
                    tests_dir.mkdir(parents=True, exist_ok=True)

                # 4. Write files
                spec_path.write_text(spec_content)
                impl_path.write_text(impl_content)
                if test_content and test_path:
                    test_path.write_text(test_content)

                logger.info(f"[ToolCreator] Wrote tool files for {tool_name} in {bundle_dir}")

                # 5. Run tests (if provided and not skipped)
                if test_content and test_path and not skip_tests:
                    test_result = await run_tool_tests([test_path], working_dir=bundle_dir)
                    result.test_result = test_result

                    if not test_result.success:
                        ctx.mark_failed(f"Tests failed: {test_result.summary}")
                        result.error = f"Tests failed: {test_result.summary}"
                        return result

                # 6. Register tool in catalog (if available)
                if self.tool_catalog:
                    try:
                        registered_tools = self.tool_catalog.register_tools_from_bundle(tools_dir)
                        result.registered = tool_name in registered_tools or any(
                            tool_name in t for t in registered_tools
                        )
                        if result.registered:
                            logger.info(f"[ToolCreator] Registered tool: {tool_name}")
                    except Exception as e:
                        logger.warning(f"[ToolCreator] Tool registration failed (non-fatal): {e}")

                result.success = True
                logger.info(f"[ToolCreator] Successfully created tool: {tool_name}")
                return result

            except Exception as e:
                ctx.mark_failed(str(e))
                result.error = str(e)
                logger.error(f"[ToolCreator] Tool creation failed: {e}")
                return result

    def create_tool_sync(
        self,
        workflow_name: str,
        tool_name: str,
        spec_content: str,
        impl_content: str,
        test_content: Optional[str] = None,
        skip_tests: bool = False,
        plan_state_path: Optional[Path] = None,
    ) -> ToolCreationResult:
        """Synchronous wrapper for create_tool."""
        import asyncio
        return asyncio.run(self.create_tool(
            workflow_name, tool_name, spec_content, impl_content,
            test_content, skip_tests, plan_state_path
        ))


# Module-level factory
def get_tool_creator(
    bundles_root: Optional[Path] = None,
    tool_catalog: Optional["ToolCatalog"] = None
) -> ToolCreator:
    """Create a ToolCreator with default paths."""
    if bundles_root is None:
        bundles_root = Path(__file__).parent.parent.parent.parent / "panda_system_docs" / "workflows" / "bundles"
    return ToolCreator(bundles_root, tool_catalog)


async def create_tool_handler(
    workflow: str,
    tool_name: str,
    spec: str,
    code: str,
    tests: str = "",
    skip_tests: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Handler function for CREATE_TOOL action.

    This is the function registered in ToolCatalog for tool.create.

    Args:
        workflow: Workflow bundle name
        tool_name: Tool name
        spec: Tool spec markdown
        code: Python implementation
        tests: Test code (optional)
        skip_tests: Skip test execution

    Returns:
        Dict with status and details
    """
    creator = get_tool_creator()
    result = await creator.create_tool(
        workflow_name=workflow,
        tool_name=tool_name,
        spec_content=spec,
        impl_content=code,
        test_content=tests if tests else None,
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
    }
