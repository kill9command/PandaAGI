"""
Panda Gateway LLM Module - Gateway-specific LLM utilities.

Provides gateway-local LLM utilities for the 8-phase pipeline:
- Recipe loader and selector for prompt IO contracts
- Token budget allocation profiles
- LLM client wrapper (OpenAI-compatible with vLLM/Qwen settings)

Architecture Reference:
    architecture/README.md (Single-Model System + Role Temperatures)

Layer Distinction:
- libs/llm: Core LLM client and model routing infrastructure
- libs/gateway/llm: Gateway-specific recipe loading and budget allocation

Design Notes:
- LLMClient uses "guide"/"coordinator" role naming which is legacy terminology.
  The current architecture uses phase-based roles (1-8), but this client
  remains compatible as it primarily controls URL routing and temperature.
- select_recipe() includes backward-compatible role mappings. Phase-based
  recipe selection is handled by libs/llm/recipes.py.
- Token budget profiles in token_budget_allocator.py provide baseline
  allocations that may be overridden by recipe-specific budgets.

Contains:
- load_recipe: Load prompt recipe from apps/prompts/
- select_recipe: Select recipe by role (legacy compatibility)
- LLMClient: OpenAI-compatible client with Qwen3-Coder settings
- TokenBudgetAllocator: Budget allocation profiles
"""

from libs.gateway.llm.recipe_loader import load_recipe, select_recipe

__all__ = [
    "load_recipe",
    "select_recipe",
]
