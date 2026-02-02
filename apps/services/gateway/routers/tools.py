"""
Tool Discovery, Execution, and Metrics Router

Provides API endpoints for discovering available tools, executing tools,
and viewing tool execution metrics.

Architecture Reference:
    architecture/Implementation/KNOWLEDGE_GRAPH_AND_UI_PLAN.md#Part 4: Coordinator Verification
    Task 4.2: Tool Registry Discovery Endpoint
    architecture/services/orchestrator-service.md

Endpoints:
    GET /v1/tools - List available tools for a mode (chat/code)
    GET /v1/tools/metrics - Get tool execution statistics
    GET /v1/tools/{tool_name} - Get details for a specific tool
    GET /v1/tools/{tool_name}/metrics - Get metrics for a specific tool
    POST /tool/execute - Execute a single tool via Orchestrator
"""

import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from apps.services.gateway.config import (
    CHAT_ALLOWED,
    CONT_ALLOWED,
    MODEL_TIMEOUT,
    ORCH_URL,
    is_tool_enabled,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["tools"])


@router.get("/v1/tools")
async def list_tools(
    mode: str = Query(
        default="chat",
        description="Tool mode: 'chat' (read-only + research) or 'code' (includes write operations)",
    )
) -> Dict[str, Any]:
    """
    List available tools for the specified mode.

    Tools are filtered based on mode permissions:
    - chat: Read-only tools + research tools
    - code: All chat tools + write operations (file.write, git.commit, etc.)

    Args:
        mode: "chat" or "code"

    Returns:
        {
            "mode": str,
            "tool_count": int,
            "tools": [
                {
                    "name": str,
                    "description": str,
                    "parameters": [
                        {
                            "name": str,
                            "type": str,
                            "required": bool,
                            "description": str,
                            "default": any
                        }
                    ],
                    "keywords": [str],
                    "intents": [str]
                }
            ]
        }
    """
    from apps.services.gateway.dependencies import get_tool_router

    # Get allowed tools for mode
    if mode == "code":
        allowed_tools = CONT_ALLOWED
    else:
        allowed_tools = CHAT_ALLOWED

    # Get tool catalog via tool router
    tool_router = get_tool_router()
    if not tool_router or not tool_router.catalog:
        return {
            "mode": mode,
            "tool_count": 0,
            "tools": [],
            "error": "Tool catalog not initialized",
        }

    catalog = tool_router.catalog

    # Build tool list
    tools = []
    for tool in catalog.tools:
        # Filter by mode permissions
        if tool.name not in allowed_tools:
            continue

        # Build parameter list
        parameters = []
        for param in tool.schema:
            parameters.append({
                "name": param.name,
                "type": param.type,
                "required": param.required,
                "description": param.description,
                "default": param.default,
            })

        tools.append({
            "name": tool.name,
            "description": _get_tool_description(tool.name),
            "parameters": parameters,
            "keywords": tool.keywords,
            "intents": tool.intents,
            "min_score": tool.min_score,
            "critical": tool.critical,
        })

    # Sort by name for consistent ordering
    tools.sort(key=lambda t: t["name"])

    return {
        "mode": mode,
        "tool_count": len(tools),
        "tools": tools,
    }


@router.get("/v1/tools/metrics")
async def get_all_tool_metrics() -> Dict[str, Any]:
    """
    Get tool execution metrics for all tools.

    Returns:
        {
            "stats": {
                "tools": {
                    "tool_name": {
                        "count": int,
                        "success_count": int,
                        "error_count": int,
                        "success_rate": float,
                        "avg_duration_ms": int,
                        "min_duration_ms": int,
                        "max_duration_ms": int
                    }
                },
                "totals": {
                    "count": int,
                    "success_count": int,
                    "error_count": int,
                    "success_rate": float,
                    "avg_duration_ms": int,
                    "unique_tools": int
                }
            },
            "recent": [
                {
                    "tool_name": str,
                    "status": str,
                    "duration_ms": int,
                    "turn_number": int,
                    "timestamp": float,
                    "error": str | null
                }
            ]
        }
    """
    from libs.gateway.tool_metrics import get_tool_metrics

    metrics = get_tool_metrics()

    return {
        "stats": metrics.get_stats(),
        "recent": [e.to_dict() for e in metrics.get_recent(20)],
    }


@router.get("/v1/tools/{tool_name}")
async def get_tool_details(tool_name: str) -> Dict[str, Any]:
    """
    Get details for a specific tool.

    Args:
        tool_name: Name of the tool (e.g., "internet.research")

    Returns:
        Tool details including schema, keywords, and intents
    """
    from apps.services.gateway.dependencies import get_tool_router

    tool_router = get_tool_router()
    if not tool_router or not tool_router.catalog:
        return {
            "error": "Tool catalog not initialized",
            "tool_name": tool_name,
        }

    tool = tool_router.catalog.get(tool_name)
    if not tool:
        return {
            "error": f"Tool '{tool_name}' not found",
            "tool_name": tool_name,
        }

    # Build parameter list
    parameters = []
    for param in tool.schema:
        parameters.append({
            "name": param.name,
            "type": param.type,
            "required": param.required,
            "description": param.description,
            "default": param.default,
        })

    # Check mode permissions
    chat_allowed = tool_name in CHAT_ALLOWED
    code_allowed = tool_name in CONT_ALLOWED

    return {
        "name": tool.name,
        "description": _get_tool_description(tool.name),
        "parameters": parameters,
        "keywords": tool.keywords,
        "intents": tool.intents,
        "min_score": tool.min_score,
        "critical": tool.critical,
        "auto_args": tool.auto_args,
        "regex": tool.regex,
        "permissions": {
            "chat_mode": chat_allowed,
            "code_mode": code_allowed,
        },
    }


@router.get("/v1/tools/{tool_name}/metrics")
async def get_tool_specific_metrics(
    tool_name: str,
    limit: int = Query(default=20, description="Number of recent executions to return"),
) -> Dict[str, Any]:
    """
    Get execution metrics for a specific tool.

    Args:
        tool_name: Name of the tool
        limit: Number of recent executions to return

    Returns:
        {
            "tool_name": str,
            "stats": {
                "count": int,
                "success_count": int,
                "error_count": int,
                "success_rate": float,
                "avg_duration_ms": int,
                "min_duration_ms": int,
                "max_duration_ms": int
            },
            "recent": [...]
        }
    """
    from libs.gateway.tool_metrics import get_tool_metrics

    metrics = get_tool_metrics()

    return {
        "tool_name": tool_name,
        "stats": metrics.get_stats(tool_name),
        "recent": [e.to_dict() for e in metrics.get_recent_for_tool(tool_name, limit)],
    }


# =============================================================================
# Tool Execution Endpoint
# =============================================================================


class ToolExecutePayload(BaseModel):
    """Payload for tool execution request."""

    tool: str
    args: Dict[str, Any] = {}
    mode: str = "chat"
    repo: Optional[str] = None
    session_id: str = "unknown"


@router.post("/tool/execute")
async def tool_execute(payload: ToolExecutePayload) -> JSONResponse:
    """
    Execute a single tool call via Orchestrator after permission validation.

    This endpoint proxies tool execution requests to the Orchestrator service,
    validating permissions first.

    Args:
        payload: {
            tool: str - Tool name (e.g., "file.read", "fs.read")
            args: dict - Tool arguments
            mode: str - "chat" or "code" (default: "chat")
            repo: str - Optional repository path
            session_id: str - Session identifier
        }

    Returns:
        Tool execution result from Orchestrator, or error response.
    """
    from libs.gateway.permission_validator import get_validator, PermissionDecision

    tool = payload.tool
    args = payload.args.copy() if payload.args else {}
    mode = payload.mode
    repo = payload.repo
    session_id = payload.session_id

    if not tool:
        raise HTTPException(400, "tool name required")

    # Inject repo into args for validation
    if repo and "repo" not in args:
        args["repo"] = repo

    # === Permission Validation (mode gates + repo scope) ===
    validator = get_validator()
    validation = validator.validate(tool, args, mode, session_id)

    if validation.decision == PermissionDecision.DENIED:
        raise HTTPException(403, validation.reason)

    if validation.decision == PermissionDecision.NEEDS_APPROVAL:
        # Return 202 Accepted with approval request info
        return JSONResponse(
            status_code=202,
            content={
                "status": "pending_approval",
                "approval_request_id": validation.approval_request_id,
                "reason": validation.reason,
                "details": validation.approval_details,
            },
        )

    # Tool global enable check
    if not is_tool_enabled(tool):
        raise HTTPException(403, f"tool disabled: {tool}")

    # Forward to Orchestrator
    async with httpx.AsyncClient(timeout=MODEL_TIMEOUT) as client:
        try:
            resp = await client.post(f"{ORCH_URL}/{tool}", json=args)
            resp.raise_for_status()
            return JSONResponse(resp.json())
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                e.response.status_code, f"orchestrator error: {e}"
            )
        except Exception as e:
            raise HTTPException(500, f"tool execute error: {e}")


# =============================================================================
# Helper Functions
# =============================================================================


def _get_tool_description(tool_name: str) -> str:
    """
    Get a human-readable description for a tool.

    These descriptions supplement the parameter schemas with context
    about what each tool does.
    """
    descriptions = {
        # Research tools
        "internet.research": (
            "Unified internet research tool. Searches the web, visits pages, "
            "extracts content, and verifies information. Supports standard and "
            "deep research modes."
        ),
        "commerce.search_offers": (
            "Search for product offers across multiple commerce sites. "
            "Returns pricing, availability, and vendor information."
        ),
        "purchasing.lookup": (
            "Quick lookup of purchasing options for a product. "
            "Lighter weight than full commerce search."
        ),
        # Document tools
        "doc.search": (
            "Search through documentation and markdown files. "
            "Useful for finding information in project docs."
        ),
        "code.search": (
            "Search through code files using regex or literal patterns. "
            "Supports file type filtering."
        ),
        "fs.read": (
            "Read the contents of a file. Supports text and binary files."
        ),
        "file.read": (
            "Read file contents with token-aware chunking. "
            "Supports offset and limit for large files."
        ),
        "file.glob": (
            "Find files by glob pattern. Returns matching file paths."
        ),
        "file.grep": (
            "Search file contents with regex. Returns matching lines."
        ),
        "repo.describe": (
            "Get an overview of a repository structure and key files."
        ),
        # Memory tools
        "memory.create": (
            "Create a new memory entry for long-term storage. "
            "Memories persist across sessions."
        ),
        "memory.query": (
            "Query stored memories by topic or keyword."
        ),
        # Other tools
        "wiki.search": (
            "Search Wikipedia for information on a topic."
        ),
        "ocr.read": (
            "Extract text from an image using OCR."
        ),
        "bom.build": (
            "Build a bill of materials (BOM) from requirements."
        ),
        # Write tools (code mode only)
        "file.write": (
            "Write content to a file. Creates file if it doesn't exist."
        ),
        "file.create": (
            "Create a new file with initial content."
        ),
        "file.edit": (
            "Edit an existing file with targeted changes."
        ),
        "file.delete": (
            "Delete a file from the filesystem."
        ),
        "code.apply_patch": (
            "Apply a unified diff patch to files."
        ),
        "git.commit": (
            "Create a git commit with the specified message."
        ),
        "code.format": (
            "Format code files according to style rules."
        ),
        "test.run": (
            "Run test suite and return results."
        ),
        "docs.write_spreadsheet": (
            "Create or update a spreadsheet document."
        ),
        "bash.execute": (
            "Execute a bash command and return output."
        ),
    }

    return descriptions.get(tool_name, f"Tool: {tool_name}")
