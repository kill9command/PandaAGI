"""LLM libraries for PandaAI v2."""

from libs.llm.client import LLMClient, LLMRequest, LLMResponse, TokenUsage, get_llm_client
from libs.llm.router import ModelLayer, ModelRouter, get_model_router, PHASE_MODEL_MAP
from libs.llm.recipes import Recipe, TokenBudget, RecipeLoader, get_recipe_loader
from libs.llm.model_swap import ModelSwapManager, get_model_swap_manager

__all__ = [
    # Client
    "LLMClient",
    "LLMRequest",
    "LLMResponse",
    "TokenUsage",
    "get_llm_client",
    # Router
    "ModelLayer",
    "ModelRouter",
    "get_model_router",
    "PHASE_MODEL_MAP",
    # Recipes
    "Recipe",
    "TokenBudget",
    "RecipeLoader",
    "get_recipe_loader",
    # Model Swap
    "ModelSwapManager",
    "get_model_swap_manager",
]
