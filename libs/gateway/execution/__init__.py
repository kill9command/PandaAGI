"""
Panda Execution Module - Tool execution, workflows, and safety.

Implements Phase 4 (Executor) and Phase 5 (Coordinator) tool dispatch with
permission gates and workflow enforcement.

Contains:
- ToolExecutor: Main tool execution with permissions and constraints
- ToolCatalog: Low-level tool registry and dispatch
- ExecutionGuard: Budget and safety checks
- PermissionValidator: Mode and repo-scoped permission gates
- Workflow system: Registry, matcher, step runner, manager

Architecture Reference:
    architecture/concepts/main-system-patterns/phase4-executor.md
    architecture/concepts/main-system-patterns/phase5-coordinator.md

Design Notes:
- Per architecture, tools should be invoked via workflows. The ToolCatalog
  and ToolExecutor APIs are low-level infrastructure. Prefer WorkflowManager
  for orchestration which ensures workflow-based execution.
- PermissionValidator uses tool-name based gates for safety enforcement.
  This is intentional - mode/repo safety must be enforced regardless of
  workflow metadata.
- ExecutionGuard uses smart_summarization for real-time budget checking
  during execution. This is distinct from libs/compression which handles
  document compression for storage.
"""

from libs.gateway.execution.tool_executor import ToolExecutor, get_tool_executor
from libs.gateway.execution.tool_catalog import ToolCatalog
from libs.gateway.execution.execution_guard import ExecutionGuard, hash_tool_args, detect_circular_calls
from libs.gateway.execution.permission_validator import get_validator, PermissionDecision
from libs.gateway.execution.tool_approval import (
    ToolApprovalManager,
    get_tool_approval_manager,
    APPROVAL_SYSTEM_ENABLED,
)
from libs.gateway.execution.tool_metrics import ToolMetrics
from libs.gateway.execution.workflow_registry import WorkflowRegistry
from libs.gateway.execution.workflow_matcher import WorkflowMatcher
from libs.gateway.execution.workflow_step_runner import WorkflowStepRunner, WorkflowResult
from libs.gateway.execution.workflow_manager import WorkflowManager, get_workflow_manager
from libs.gateway.execution.tool_registration import ToolRegistrar, register_all_tools

__all__ = [
    "ToolExecutor",
    "get_tool_executor",
    "ToolCatalog",
    "ExecutionGuard",
    "hash_tool_args",
    "detect_circular_calls",
    "get_validator",
    "PermissionDecision",
    "ToolApprovalManager",
    "get_tool_approval_manager",
    "APPROVAL_SYSTEM_ENABLED",
    "ToolMetrics",
    "WorkflowRegistry",
    "WorkflowMatcher",
    "WorkflowStepRunner",
    "WorkflowResult",
    "WorkflowManager",
    "get_workflow_manager",
    "ToolRegistrar",
    "register_all_tools",
]
