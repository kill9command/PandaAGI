# Orchestrator package initializer
# This file makes `orchestrator` a proper Python package so tests and imports like
# `from apps.services.orchestrator.context_builder import ...` succeed when running pytest or other tools.
#
# Keep this file minimal. Importing heavy submodules here would slow test collection.

"""Orchestrator package.

Provides access to orchestrator.* modules:
- context_builder
- web_fetcher
- memory_manager
- playwright_stealth_mcp
- purchasing_mcp
"""

__all__ = ["context_builder", "web_fetcher", "memory_manager", "playwright_stealth_mcp", "purchasing_mcp"]

# Optional: expose a lightweight version string for tooling checks
__version__ = "0.0.1"
