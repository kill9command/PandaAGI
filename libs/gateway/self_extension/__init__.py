"""
Self-Extension Package - Tool and workflow creation pipeline.

Implements M2 (Self-Extension Pipeline) from BENCHMARK_ALIGNMENT.md:
- Tool spec validation
- Backup and rollback
- Sandbox test execution
- Tool creation with registration

Architecture Reference:
- architecture/concepts/SELF_BUILDING_SYSTEM.md
- architecture/concepts/TOOL_SYSTEM.md
"""

from libs.gateway.self_extension.spec_validator import (
    ToolSpecValidator,
    ValidationResult,
    ValidationError,
    get_spec_validator,
    validate_tool_spec,
)

from libs.gateway.self_extension.backup_manager import (
    BackupManager,
    RollbackContext,
    get_backup_manager,
)

from libs.gateway.self_extension.sandbox_runner import (
    SandboxRunner,
    SandboxResult,
    TestResult,
    get_sandbox_runner,
    run_tool_tests,
)

from libs.gateway.self_extension.tool_creator import (
    ToolCreator,
    ToolCreationResult,
    get_tool_creator,
    create_tool_handler,
)

from libs.gateway.self_extension.llm_tool_generator import (
    LLMToolGenerator,
    GeneratedTool,
    get_llm_tool_generator,
    generate_tool,
)

__all__ = [
    # Spec Validator
    "ToolSpecValidator",
    "ValidationResult",
    "ValidationError",
    "get_spec_validator",
    "validate_tool_spec",
    # Backup Manager
    "BackupManager",
    "RollbackContext",
    "get_backup_manager",
    # Sandbox Runner
    "SandboxRunner",
    "SandboxResult",
    "TestResult",
    "get_sandbox_runner",
    "run_tool_tests",
    # Tool Creator
    "ToolCreator",
    "ToolCreationResult",
    "get_tool_creator",
    "create_tool_handler",
    # LLM Tool Generator
    "LLMToolGenerator",
    "GeneratedTool",
    "get_llm_tool_generator",
    "generate_tool",
]
