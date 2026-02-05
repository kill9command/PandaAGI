# Tool Server package initializer
# This file makes `tool_server` a proper Python package so tests and imports like
# `from apps.services.tool_server.context_builder import ...` succeed when running pytest or other tools.
#
# Keep this file minimal. Importing heavy submodules here would slow test collection.

"""Tool Server package - Tool execution service.

Architecture Reference:
    architecture/README.md (Tool Server)

Design Notes:
- "Orchestrator" is legacy naming. Current architecture uses "Tool Server" for this service.
- The Tool Server handles tool execution, delegated from the Gateway via workflows.
- MCP modules (*_mcp.py) provide the tool endpoints.

Provides access to tool_server.* modules:
- context_builder
- web_fetcher
- memory_manager
- playwright_stealth_mcp
- purchasing_mcp
"""

__all__ = ["context_builder", "web_fetcher", "memory_manager", "playwright_stealth_mcp", "purchasing_mcp"]

# Optional: expose a lightweight version string for tooling checks
__version__ = "0.0.1"
