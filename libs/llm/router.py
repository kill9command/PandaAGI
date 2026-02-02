"""Model routing for the 5-model cognitive stack.

All text phases use MIND model (Qwen3-4B-AWQ) with different temperatures:
- REFLEX role (temp=0.3): Classification, binary decisions (Phases 0-1)
- NERVES role (temp=0.1): Compression, low creativity
- MIND role (temp=0.5): Reasoning, planning (Phases 2-4, 6)
- VOICE role (temp=0.7): User dialogue, synthesis (Phase 5)

EYES model (Qwen3-VL-2B) swaps with MIND for vision tasks.
SERVER (Qwen3-Coder-30B) is accessed via remote API for heavy coding.
"""

from enum import Enum
from typing import Any

from libs.core.config import get_settings, load_model_registry
from libs.llm.client import get_llm_client, LLMResponse


class ModelLayer(Enum):
    """Model layer identifiers."""

    REFLEX = "reflex"  # Layer 0 - Fast gates, classification (Qwen3-0.6B)
    NERVES = "nerves"  # Layer 1 - Routing, compression (shares MIND)
    MIND = "mind"      # Layer 2 - Planning, reasoning (Qwen3-4B-AWQ, keystone)
    VOICE = "voice"    # Layer 3 - User dialogue, synthesis (shares MIND)
    EYES = "eyes"      # Layer 4 - Vision tasks (Qwen3-VL-2B, cold pool)
    SERVER = "server"  # Remote - Heavy coding (Qwen3-Coder-30B)


# Phase to model mapping
# Note: All phases use MIND model with different temperatures (roles)
# Phases 0-1: REFLEX role (temp=0.3) - but uses MIND model
# Phases 2-4, 6: MIND role (temp=0.5)
# Phase 5: VOICE role (temp=0.7) - but uses MIND model
PHASE_MODEL_MAP = {
    0: ModelLayer.MIND,   # Query Analyzer (REFLEX role, temp=0.3)
    1: ModelLayer.MIND,   # Reflection (REFLEX role, temp=0.3)
    2: ModelLayer.MIND,   # Context Gatherer (MIND role, temp=0.5)
    3: ModelLayer.MIND,   # Planner (MIND role, temp=0.5)
    4: ModelLayer.MIND,   # Coordinator (MIND role, temp=0.5)
    5: ModelLayer.MIND,   # Synthesis (VOICE role, temp=0.7)
    6: ModelLayer.MIND,   # Validation (MIND role, temp=0.5)
}

# Phase to temperature mapping (role behavior)
PHASE_TEMPERATURE_MAP = {
    0: 0.3,  # REFLEX role
    1: 0.3,  # REFLEX role
    2: 0.5,  # MIND role
    3: 0.5,  # MIND role
    4: 0.5,  # MIND role
    5: 0.7,  # VOICE role
    6: 0.5,  # MIND role
}


class ModelRouter:
    """Routes requests to appropriate models in the cognitive stack."""

    def __init__(self):
        self.settings = get_settings()
        self.client = get_llm_client()
        self._model_registry = None

        # Default parameters per model (loaded lazily)
        self._default_params = {}

    def _load_registry(self):
        """Load model registry lazily."""
        if self._model_registry is None:
            try:
                self._model_registry = load_model_registry()
                for model_key, config in self._model_registry.get("models", {}).items():
                    try:
                        layer = ModelLayer(model_key)
                        self._default_params[layer] = config.get("parameters", {})
                    except ValueError:
                        continue  # Skip unknown model keys
            except FileNotFoundError:
                # Registry file doesn't exist yet, use defaults
                self._model_registry = {}

    def get_model_for_phase(self, phase: int) -> ModelLayer:
        """Get the model layer for a pipeline phase."""
        if phase not in PHASE_MODEL_MAP:
            raise ValueError(f"Unknown phase: {phase}")
        return PHASE_MODEL_MAP[phase]

    def get_temperature_for_phase(self, phase: int) -> float:
        """Get the temperature for a pipeline phase (role behavior)."""
        if phase not in PHASE_TEMPERATURE_MAP:
            raise ValueError(f"Unknown phase: {phase}")
        return PHASE_TEMPERATURE_MAP[phase]

    def get_layer_name(self, layer: ModelLayer) -> str:
        """Get the layer name string for a ModelLayer enum."""
        return layer.value

    def get_default_params(self, layer: ModelLayer) -> dict[str, Any]:
        """Get default parameters for a model layer."""
        self._load_registry()
        return self._default_params.get(layer, {}).copy()

    async def complete(
        self,
        layer: ModelLayer,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """
        Send completion to specified model layer.

        Args:
            layer: Target model layer
            messages: Chat messages
            temperature: Override default temperature
            max_tokens: Override default max_tokens

        Returns:
            LLM response
        """
        layer_name = self.get_layer_name(layer)
        params = self.get_default_params(layer)

        # Apply overrides
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        return await self.client.complete(
            model_layer=layer_name,
            messages=messages,
            temperature=params.get("temperature", 0.7),
            max_tokens=params.get("max_tokens", 2000),
        )

    async def complete_for_phase(
        self,
        phase: int,
        messages: list[dict[str, str]],
        **kwargs,
    ) -> LLMResponse:
        """
        Send completion using the model assigned to a phase.

        Args:
            phase: Pipeline phase number (0-6)
            messages: Chat messages
            **kwargs: Additional parameters (temperature, max_tokens)

        Returns:
            LLM response
        """
        layer = self.get_model_for_phase(phase)

        # Use phase-specific temperature if not overridden
        if "temperature" not in kwargs:
            kwargs["temperature"] = self.get_temperature_for_phase(phase)

        return await self.complete(layer, messages, **kwargs)


# Singleton instance
_model_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """Get model router singleton."""
    global _model_router
    if _model_router is None:
        _model_router = ModelRouter()
    return _model_router
