# Phase 2: Core Libraries

**Dependencies:** Phase 1 (Infrastructure)
**Priority:** Critical
**Estimated Effort:** 2-3 days

---

## Architecture Linkages

This section documents how each implementation decision traces back to the architecture documentation.

### Configuration System (Settings Classes)

**Architecture Reference:** `architecture/README.md#System-Summary`, `config/model-registry.yaml`

> From `config/model-registry.yaml` (updated 2026-01-06):
> ```yaml
> hardware:
>   vram_hot_pool_gb: 3.3  # Single MIND model (~3.3GB with compressed-tensors)
>   vram_cold_reserve_gb: 5.0  # EYES when swapped in
> ```

**Why Single MIND Model (vLLM Tested):** Testing showed a single MIND model (Qwen3-Coder-30B-AWQ, ~3.3GB) handles ALL text roles via temperature settings (REFLEX=0.3, NERVES=0.1, MIND=0.5, VOICE=0.7). Qwen3-0.6B (REFLEX) is NOT used. Single vLLM instance on port 8000. EYES loads on-demand via model swap (MIND ↔ EYES). SERVER accessed via remote API.

---

### LLM Client (Multi-Port Design)

**Architecture Reference:** `architecture/main-system-patterns/ERROR_HANDLING.md`, `architecture/llm-roles-reference.md`

> From `ERROR_HANDLING.md`:
> "Every error is a bug that needs to be fixed. Silent fallbacks and graceful degradation HIDE bugs."
>
> **Core Principle:** When something fails: Log full context, create intervention request, STOP processing.

**Why Fail-Fast in Client:** The `LLMClient` raises `InterventionRequired` on HTTP errors instead of retrying silently. This implements the architecture's fail-fast philosophy where development mode halts on all errors for human investigation. No fallbacks - every failure is a learning opportunity.

---

### Model Router (Phase-to-Model Mapping)

**Architecture Reference:** `architecture/LLM-ROLES/llm-roles-reference.md#Phase-Model-Files`, `config/model-registry.yaml#phase_assignments`

> **Simplified Stack (vLLM tested 2026-01-06):**
> | Phase | Model | Role/Temp | Recipe |
> |-------|-------|-----------|--------|
> | 0 Query Analyzer | MIND | REFLEX/0.3 | `query_analyzer.yaml` |
> | 1 Reflection | MIND | REFLEX/0.3 | `reflection.yaml` |
> | 2 Context Gatherer | MIND | MIND/0.5 | `context_gatherer_*.yaml` |
> | 3 Planner | MIND | MIND/0.5 | `planner_*.yaml` |
> | 4 Coordinator | MIND | MIND/0.5 | `coordinator_*.yaml` |
> | 5 Synthesis | MIND | VOICE/0.7 | `synthesizer_*.yaml` |
> | 6 Validation | MIND | MIND/0.5 | `validator.yaml` |

**Why Single MIND Model:** All phases use the same MIND model (Qwen3-Coder-30B-AWQ). Role behavior is controlled by temperature and system prompts. Qwen3-0.6B (REFLEX) is NOT used - MIND handles classification adequately. SERVER (Qwen3-Coder-30B, remote) for heavy coding tasks.

---

### Recipe System

**Architecture Reference:** `architecture/LLM-ROLES/llm-roles-reference.md#Token-Budgets`, `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md`

> | Phase | Model | Total | Prompt | Input | Output |
> |-------|-------|-------|--------|-------|--------|
> | 0 | REFLEX | 1,500 | 500 | 700 | 300 |
> | 2 | MIND | 10,500 | 2,000 | 6,000 | 2,500 |
> | 5 | VOICE | 10,000 | 1,300 | 5,500 | 3,000 |

**Why Token Budgets:** Per-phase token budgets ensure the system respects the 24GB VRAM constraint. Recipe-driven configuration implements "Recipe-driven budgets and schemas" design principle. Mode-specific recipes (chat vs code) match model-registry.yaml specifications.

---

### Pydantic Models (Data Structures)

**Architecture Reference:** `architecture/main-system-patterns/phase0-query-analyzer.md#Output-Schema`, `architecture/main-system-patterns/phase3-planner.md#Output-Formats`, `architecture/main-system-patterns/phase6-validation.md#Output-Schema`

> From Phase 3 architecture:
> **Route Options:** coordinator (Phase 4), synthesis (Phase 5), clarify (return to user)

> From Phase 6 architecture:
> | Decision | Confidence | Action |
> |----------|-----------|--------|
> | APPROVE | >= 0.80 | Send to user |
> | REVISE | 0.50-0.79 | Loop to Phase 5 |
> | RETRY | 0.30-0.49 | Loop to Phase 3 |
> | FAIL | < 0.30 | Send error |

**Why These Models:** Pydantic models enforce the architecture's type contracts at runtime. `QueryType`, `PlannerRoute`, `ValidationDecision` enums match exact schema specifications from phase documentation. Goal tracking supports multi-goal queries per Phase 3 spec.

---

### MIND/EYES Swap Mechanism

**Architecture Reference:** `architecture/LLM-ROLES/llm-roles-reference.md#EYES-Model-Swap-Strategy`

> **Why MIND Swaps (vLLM Tested):**
> - Single MIND model handles ALL text roles (no separate REFLEX model)
> - EYES (~5GB) cannot fit alongside MIND (~3.3GB) within 8GB
> - Text processing pauses during vision tasks

**Why Model Swap Manager:** EYES (~5GB) swaps with MIND (~3.3GB) for vision tasks. `ModelSwapManager` implements the swap strategy: stop MIND, start EYES, execute vision, stop EYES, restart MIND. Thread-safe via asyncio.Lock. Automatic swap-back after vision task completion. Total swap overhead: ~8-14 seconds per vision task.

---

### Exception Handling (Fail-Fast Philosophy)

**Architecture Reference:** `architecture/main-system-patterns/ERROR_HANDLING.md`

> **Design Principles (Development Mode):**
> 1. No silent failures - Every error creates intervention
> 2. No fallbacks - Fallbacks hide bugs
> 3. Full context - Log everything needed to debug
>
> **Category A: Halt and Notify (ALL errors)**
> `httpx.TimeoutException`, `httpx.HTTPStatusError`, `json.JSONDecodeError`, `LLM call failure` → HALT

**Why InterventionRequired:** The exception hierarchy supports the architecture's error handling requirements. All exceptions bubble up to halt processing. Every exception carries `context` dict for debugging. `PhaseError` includes phase number for precise debugging.

---

## Overview

This phase builds the shared libraries used across all services:
- Configuration management
- LLM client and router
- Recipe system
- Pydantic models
- Exception handling

---

## 1. Configuration Management

### 1.1 `libs/core/config.py`

```python
"""Configuration management for PandaAI v2."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """PostgreSQL database settings."""

    host: str = Field(default="localhost", alias="POSTGRES_HOST")
    port: int = Field(default=5432, alias="POSTGRES_PORT")
    database: str = Field(default="pandora", alias="POSTGRES_DB")
    user: str = Field(default="pandora", alias="POSTGRES_USER")
    password: str = Field(default="pandora", alias="POSTGRES_PASSWORD")

    @property
    def url(self) -> str:
        """Get async database URL."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class QdrantSettings(BaseSettings):
    """Qdrant vector database settings."""

    host: str = Field(default="localhost", alias="QDRANT_HOST")
    port: int = Field(default=6333, alias="QDRANT_PORT")


class VLLMSettings(BaseSettings):
    """vLLM server settings."""

    host: str = Field(default="localhost", alias="VLLM_HOST")
    port: int = Field(default=8000, alias="VLLM_PORT")
    gpu_memory_utilization: float = Field(default=0.90, alias="VLLM_GPU_MEMORY_UTILIZATION")
    max_model_len: int = Field(default=32768, alias="VLLM_MAX_MODEL_LEN")

    # Single vLLM instance serves MIND (shared by NERVES/VOICE roles)
    # REFLEX can be loaded as second model or share MIND with lower temperature
    # EYES loads on-demand via model swap (REFLEX ↔ EYES)

    def get_base_url(self, model_layer: str = "mind") -> str:
        """Get vLLM base URL. Single instance serves all local models."""
        return f"http://{self.host}:{self.port}/v1"


class ServerSettings(BaseSettings):
    """Remote SERVER model settings (Qwen3-Coder-30B)."""

    endpoint: str = Field(default="http://localhost:8001", alias="SERVER_ENDPOINT")
    model: str = Field(default="Qwen/Qwen3-Coder-30B", alias="SERVER_MODEL")
    timeout: int = Field(default=120, alias="SERVER_TIMEOUT")


class ModelSettings(BaseSettings):
    """Model configuration settings."""

    # Hot pool models
    reflex: str = Field(default="Qwen/Qwen3-0.6B", alias="REFLEX_MODEL")
    mind: str = Field(default="cyankiwi/Qwen3-Coder-30B-AWQ-4bit", alias="MIND_MODEL")
    # NERVES and VOICE share MIND model - no separate config needed

    # Cold pool models
    eyes: str = Field(default="Qwen/Qwen3-VL-2B-Instruct", alias="EYES_MODEL")

    # Load timeouts
    eyes_load_timeout: int = Field(default=30, alias="EYES_LOAD_TIMEOUT_SECONDS")
    eyes_unload_after: int = Field(default=60, alias="EYES_UNLOAD_AFTER_SECONDS")

    # Model paths (local)
    reflex_path: str = Field(default="models/Qwen3-0.6B", alias="REFLEX_PATH")
    mind_path: str = Field(default="models/Qwen3-Coder-30B-AWQ", alias="MIND_PATH")
    eyes_path: str = Field(default="models/Qwen3-VL-2B-Instruct", alias="EYES_PATH")


class GatewaySettings(BaseSettings):
    """Gateway service settings."""

    host: str = Field(default="0.0.0.0", alias="GATEWAY_HOST")
    port: int = Field(default=9000, alias="GATEWAY_PORT")
    workers: int = Field(default=1, alias="GATEWAY_WORKERS")


class OrchestratorSettings(BaseSettings):
    """Orchestrator service settings."""

    host: str = Field(default="0.0.0.0", alias="ORCHESTRATOR_HOST")
    port: int = Field(default=8090, alias="ORCHESTRATOR_PORT")
    workers: int = Field(default=1, alias="ORCHESTRATOR_WORKERS")

    @property
    def base_url(self) -> str:
        """Get Orchestrator base URL."""
        return f"http://{self.host}:{self.port}"


class ResearchSettings(BaseSettings):
    """Research configuration settings."""

    min_successful_vendors: int = Field(default=3, alias="MIN_SUCCESSFUL_VENDORS")
    max_passes: int = Field(default=3, alias="RESEARCH_MAX_PASSES")
    satisfaction_threshold: float = Field(default=0.8, alias="RESEARCH_SATISFACTION_THRESHOLD")
    min_request_interval_ms: int = Field(default=2000, alias="MIN_REQUEST_INTERVAL_MS")


class BrowserSettings(BaseSettings):
    """Browser automation settings."""

    headless: bool = Field(default=True, alias="BROWSER_HEADLESS")
    timeout_ms: int = Field(default=30000, alias="PLAYWRIGHT_TIMEOUT_MS")
    viewport_width: int = Field(default=1920, alias="VIEWPORT_WIDTH")
    viewport_height: int = Field(default=1080, alias="VIEWPORT_HEIGHT")


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Development mode
    dev_mode: bool = Field(default=True, alias="DEV_MODE")
    trace_verbose: int = Field(default=1, alias="TRACE_VERBOSE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    fail_fast: bool = Field(default=True, alias="FAIL_FAST")

    # Sub-settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    vllm: VLLMSettings = Field(default_factory=VLLMSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    orchestrator: OrchestratorSettings = Field(default_factory=OrchestratorSettings)
    research: ResearchSettings = Field(default_factory=ResearchSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)

    # Paths
    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent)

    @property
    def panda_system_docs(self) -> Path:
        """Get panda-system-docs directory."""
        return self.project_root / "panda-system-docs"

    @property
    def architecture_dir(self) -> Path:
        """Get architecture directory."""
        return self.project_root / "architecture"

    @property
    def config_dir(self) -> Path:
        """Get config directory."""
        return self.project_root / "config"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def load_model_registry() -> dict[str, Any]:
    """Load model registry from YAML."""
    settings = get_settings()
    registry_path = settings.config_dir / "model-registry.yaml"

    with open(registry_path) as f:
        return yaml.safe_load(f)
```

---

## 2. LLM Client

### 2.1 `libs/llm/client.py`

```python
"""vLLM HTTP client for PandaAI v2."""

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx
from pydantic import BaseModel

from libs.core.config import get_settings
from libs.core.exceptions import LLMError, InterventionRequired


class LLMRequest(BaseModel):
    """LLM request payload."""

    model: str
    messages: list[dict[str, str]]
    temperature: float = 0.7
    max_tokens: int = 2000
    stream: bool = False


class LLMResponse(BaseModel):
    """LLM response."""

    content: str
    model: str
    usage: dict[str, int]
    finish_reason: str


@dataclass
class TokenUsage:
    """Token usage tracking."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMClient:
    """Async HTTP client for vLLM server."""

    def __init__(self):
        self.settings = get_settings()
        self._clients: dict[str, httpx.AsyncClient] = {}

    async def _get_client(self, model_layer: str) -> httpx.AsyncClient:
        """Get or create HTTP client for specific model layer."""
        if model_layer not in self._clients:
            base_url = self.settings.vllm.get_base_url(model_layer)
            self._clients[model_layer] = httpx.AsyncClient(
                base_url=base_url,
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        return self._clients[model_layer]

    async def close(self):
        """Close all HTTP clients."""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def complete(
        self,
        model_layer: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        """
        Send completion request to vLLM.

        Args:
            model_layer: Model layer name (reflex, nerves, mind, voice, eyes)
            messages: Chat messages
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            LLMResponse with generated content

        Raises:
            LLMError: On API errors
            InterventionRequired: On critical failures (fail-fast mode)
        """
        client = await self._get_client(model_layer)

        # Get model ID from settings for the request
        model_id = getattr(self.settings.models, model_layer, model_layer)

        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            return LLMResponse(
                content=data["choices"][0]["message"]["content"],
                model=data["model"],
                usage=data["usage"],
                finish_reason=data["choices"][0]["finish_reason"],
            )

        except httpx.HTTPStatusError as e:
            if self.settings.fail_fast:
                raise InterventionRequired(
                    component="LLMClient",
                    error=f"HTTP {e.response.status_code}: {e.response.text}",
                    context={"model_layer": model_layer, "endpoint": "/chat/completions"},
                )
            raise LLMError(f"HTTP error: {e}") from e

        except httpx.RequestError as e:
            base_url = self.settings.vllm.get_base_url(model_layer)
            if self.settings.fail_fast:
                raise InterventionRequired(
                    component="LLMClient",
                    error=f"Request failed: {e}",
                    context={"model_layer": model_layer, "base_url": base_url},
                )
            raise LLMError(f"Request error: {e}") from e

    async def stream(
        self,
        model_layer: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> AsyncIterator[str]:
        """
        Stream completion from vLLM.

        Args:
            model_layer: Model layer name (reflex, nerves, mind, voice, eyes)

        Yields:
            Text chunks as they arrive
        """
        client = await self._get_client(model_layer)
        model_id = getattr(self.settings.models, model_layer, model_layer)

        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        # Parse SSE data
                        import json
                        chunk = json.loads(data)
                        if chunk["choices"][0].get("delta", {}).get("content"):
                            yield chunk["choices"][0]["delta"]["content"]

        except httpx.HTTPStatusError as e:
            if self.settings.fail_fast:
                raise InterventionRequired(
                    component="LLMClient",
                    error=f"Stream HTTP {e.response.status_code}",
                    context={"model_layer": model_layer},
                )
            raise LLMError(f"Stream error: {e}") from e

    async def health_check(self, model_layer: str = "mind") -> bool:
        """Check if vLLM server is healthy for a specific model layer."""
        try:
            client = await self._get_client(model_layer)
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    async def health_check_all(self) -> dict[str, bool]:
        """Check health of all vLLM instances."""
        results = {}
        for layer in ["reflex", "nerves", "mind", "voice"]:
            results[layer] = await self.health_check(layer)
        return results


# Singleton instance
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
```

---

## 3. Model Router

### 3.1 `libs/llm/router.py`

```python
"""Model routing for the 5-model cognitive stack."""

from enum import Enum
from typing import Any

from libs.core.config import get_settings, load_model_registry
from libs.llm.client import get_llm_client, LLMResponse


class ModelLayer(Enum):
    """Model layer identifiers."""

    REFLEX = "reflex"  # Layer 0 - Fast gates, classification (Qwen3-0.6B)
    NERVES = "nerves"  # Layer 1 - Routing, compression (shares MIND)
    MIND = "mind"      # Layer 2 - Planning, reasoning (Qwen3-Coder-30B-AWQ, keystone)
    VOICE = "voice"    # Layer 3 - User dialogue, synthesis (shares MIND)
    EYES = "eyes"      # Layer 4 - Vision tasks (Qwen3-VL-2B, cold pool)
    SERVER = "server"  # Remote - Heavy coding (Qwen3-Coder-30B)


# Phase to model mapping
PHASE_MODEL_MAP = {
    0: ModelLayer.REFLEX,  # Query Analyzer
    1: ModelLayer.REFLEX,  # Reflection
    2: ModelLayer.MIND,    # Context Gatherer
    3: ModelLayer.MIND,    # Planner
    4: ModelLayer.MIND,    # Coordinator
    5: ModelLayer.VOICE,   # Synthesis
    6: ModelLayer.MIND,    # Validation
}


class ModelRouter:
    """Routes requests to appropriate models in the cognitive stack."""

    def __init__(self):
        self.settings = get_settings()
        self.client = get_llm_client()
        self._model_registry = load_model_registry()

        # Default parameters per model (from registry)
        self._default_params = {}
        for model_key, config in self._model_registry.get("models", {}).items():
            try:
                layer = ModelLayer(model_key)
                self._default_params[layer] = config.get("parameters", {})
            except ValueError:
                continue  # Skip unknown model keys

    def get_model_for_phase(self, phase: int) -> ModelLayer:
        """Get the model layer for a pipeline phase."""
        if phase not in PHASE_MODEL_MAP:
            raise ValueError(f"Unknown phase: {phase}")
        return PHASE_MODEL_MAP[phase]

    def get_layer_name(self, layer: ModelLayer) -> str:
        """Get the layer name string for a ModelLayer enum."""
        return layer.value

    def get_default_params(self, layer: ModelLayer) -> dict[str, Any]:
        """Get default parameters for a model layer."""
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
            **kwargs: Additional parameters

        Returns:
            LLM response
        """
        layer = self.get_model_for_phase(phase)
        return await self.complete(layer, messages, **kwargs)


# Singleton instance
_model_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """Get model router singleton."""
    global _model_router
    if _model_router is None:
        _model_router = ModelRouter()
    return _model_router
```

---

## 4. Recipe System

### 4.1 `libs/llm/recipes.py`

```python
"""Recipe system for phase configuration."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from libs.core.config import get_settings


@dataclass
class TokenBudget:
    """Token budget for a phase."""

    total: int
    prompt: int
    input: int
    output: int

    def validate(self, prompt_tokens: int, input_tokens: int) -> bool:
        """Check if tokens are within budget."""
        return (
            prompt_tokens <= self.prompt and
            input_tokens <= self.input and
            (prompt_tokens + input_tokens) <= (self.total - self.output)
        )


@dataclass
class Recipe:
    """Configuration recipe for a phase."""

    name: str
    model: str
    token_budget: TokenBudget
    temperature: float = 0.7
    max_tokens: int = 2000
    system_prompt: str = ""
    user_prompt_template: str = ""
    output_schema: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> "Recipe":
        """Load recipe from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        budget_data = data.get("token_budget", {})
        token_budget = TokenBudget(
            total=budget_data.get("total", 8000),
            prompt=budget_data.get("prompt", 2000),
            input=budget_data.get("input", 4000),
            output=budget_data.get("output", 2000),
        )

        return cls(
            name=data.get("name", path.stem),
            model=data.get("model", "mind"),
            token_budget=token_budget,
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 2000),
            system_prompt=data.get("system_prompt", ""),
            user_prompt_template=data.get("user_prompt_template", ""),
            output_schema=data.get("output_schema", {}),
            extra=data.get("extra", {}),
        )


class RecipeLoader:
    """Loads and caches recipe configurations."""

    def __init__(self):
        self.settings = get_settings()
        self.recipes_dir = self.settings.project_root / "apps" / "recipes"
        self._cache: dict[str, Recipe] = {}

    def load(self, name: str) -> Recipe:
        """
        Load a recipe by name.

        Args:
            name: Recipe name (without .yaml extension)

        Returns:
            Recipe configuration

        Raises:
            FileNotFoundError: If recipe file doesn't exist
        """
        if name in self._cache:
            return self._cache[name]

        path = self.recipes_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Recipe not found: {path}")

        recipe = Recipe.from_yaml(path)
        self._cache[name] = recipe
        return recipe

    def load_phase_recipe(self, phase: int, mode: str = "chat") -> Recipe:
        """
        Load recipe for a specific phase.

        Args:
            phase: Phase number (0-6)
            mode: 'chat' or 'code'

        Returns:
            Recipe for the phase
        """
        recipe_names = {
            0: "query_analyzer",
            1: "reflection",
            2: f"context_gatherer_{mode}",
            3: f"planner_{mode}",
            4: f"coordinator_{mode}",
            5: f"synthesizer_{mode}",
            6: "validator",
        }

        name = recipe_names.get(phase)
        if not name:
            raise ValueError(f"No recipe defined for phase {phase}")

        return self.load(name)

    def clear_cache(self):
        """Clear recipe cache."""
        self._cache.clear()


# Singleton instance
_recipe_loader: RecipeLoader | None = None


def get_recipe_loader() -> RecipeLoader:
    """Get recipe loader singleton."""
    global _recipe_loader
    if _recipe_loader is None:
        _recipe_loader = RecipeLoader()
    return _recipe_loader
```

---

## 5. Pydantic Models

### 5.1 `libs/core/models.py`

```python
"""Pydantic models for PandaAI v2."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class QueryType(str, Enum):
    """Query type classification."""

    SPECIFIC_CONTENT = "specific_content"
    GENERAL_QUESTION = "general_question"
    FOLLOWUP = "followup"
    NEW_TOPIC = "new_topic"


class Intent(str, Enum):
    """Query intent classification."""

    TRANSACTIONAL = "transactional"
    INFORMATIONAL = "informational"
    NAVIGATIONAL = "navigational"


class ReflectionDecision(str, Enum):
    """Phase 1 reflection decisions."""

    PROCEED = "PROCEED"
    CLARIFY = "CLARIFY"


class PlannerRoute(str, Enum):
    """Phase 3 routing decisions."""

    COORDINATOR = "coordinator"
    SYNTHESIS = "synthesis"
    CLARIFY = "clarify"


class PlannerAction(str, Enum):
    """Planner action decisions."""

    EXECUTE = "EXECUTE"
    COMPLETE = "COMPLETE"


class ValidationDecision(str, Enum):
    """Phase 6 validation decisions."""

    APPROVE = "APPROVE"
    REVISE = "REVISE"
    RETRY = "RETRY"
    FAIL = "FAIL"


class GoalStatus(str, Enum):
    """Multi-goal tracking status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


# =============================================================================
# Phase 0: Query Analysis
# =============================================================================

class ContentReference(BaseModel):
    """Reference to prior content."""

    title: str
    content_type: str  # "thread", "article", "product", etc.
    site: str
    source_turn: int
    prior_findings: Optional[str] = None
    source_url: Optional[str] = None
    has_webpage_cache: bool = False
    webpage_cache_path: Optional[str] = None


class QueryAnalysis(BaseModel):
    """Phase 0 output: Query analysis result."""

    original_query: str
    resolved_query: str
    was_resolved: bool = False
    query_type: QueryType
    intent: Optional[Intent] = None
    content_reference: Optional[ContentReference] = None
    reasoning: str


# =============================================================================
# Phase 1: Reflection
# =============================================================================

class ReflectionResult(BaseModel):
    """Phase 1 output: Reflection decision."""

    decision: ReflectionDecision
    confidence: float = Field(ge=0.0, le=1.0)
    query_type: Optional[str] = None
    is_followup: bool = False
    reasoning: str


# =============================================================================
# Phase 2: Context Gathering
# =============================================================================

class ContextSource(BaseModel):
    """Source reference in gathered context."""

    path: str
    turn_number: Optional[int] = None
    relevance: float = Field(ge=0.0, le=1.0)
    summary: str


class GatheredContext(BaseModel):
    """Phase 2 output: Gathered context."""

    session_preferences: dict[str, Any] = Field(default_factory=dict)
    relevant_turns: list[ContextSource] = Field(default_factory=list)
    cached_research: Optional[dict[str, Any]] = None
    source_references: list[str] = Field(default_factory=list)
    sufficiency_assessment: str = ""


# =============================================================================
# Phase 3: Planning
# =============================================================================

class Goal(BaseModel):
    """Goal in multi-goal queries."""

    id: str
    description: str
    status: GoalStatus = GoalStatus.PENDING
    dependencies: list[str] = Field(default_factory=list)


class ToolRequest(BaseModel):
    """Tool request from Planner."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    goal_id: Optional[str] = None


class TaskPlan(BaseModel):
    """Phase 3 output: Task plan."""

    decision: PlannerAction
    route: Optional[PlannerRoute] = None
    goals: list[Goal] = Field(default_factory=list)
    current_focus: Optional[str] = None
    tool_requests: list[ToolRequest] = Field(default_factory=list)
    reasoning: str


# =============================================================================
# Phase 4: Coordination
# =============================================================================

class ToolResult(BaseModel):
    """Result from a tool execution."""

    tool: str
    goal_id: Optional[str] = None
    success: bool
    result: Any
    error: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class Claim(BaseModel):
    """Extracted claim with evidence."""

    claim: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    ttl_hours: Optional[int] = None


class ToolExecutionResult(BaseModel):
    """Phase 4 output: Tool execution result."""

    iteration: int
    action: str  # "TOOL_CALL" or "DONE"
    reasoning: str
    tool_results: list[ToolResult] = Field(default_factory=list)
    claims_extracted: list[Claim] = Field(default_factory=list)
    progress_summary: Optional[str] = None


# =============================================================================
# Phase 5: Synthesis
# =============================================================================

class SynthesisResult(BaseModel):
    """Phase 5 output: Synthesis result."""

    response_preview: str
    full_response: str
    citations: list[str] = Field(default_factory=list)
    validation_checklist: dict[str, bool] = Field(default_factory=dict)


# =============================================================================
# Phase 6: Validation
# =============================================================================

class ValidationCheck(BaseModel):
    """Individual validation check."""

    name: str
    passed: bool
    notes: Optional[str] = None


class GoalValidation(BaseModel):
    """Per-goal validation result."""

    goal_id: str
    addressed: bool
    quality: float = Field(ge=0.0, le=1.0)
    notes: Optional[str] = None


class ValidationResult(BaseModel):
    """Phase 6 output: Validation result."""

    decision: ValidationDecision
    confidence: float = Field(ge=0.0, le=1.0)
    checks: list[ValidationCheck] = Field(default_factory=list)
    goal_validations: list[GoalValidation] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    revision_hints: Optional[str] = None
    overall_quality: Optional[float] = Field(ge=0.0, le=1.0, default=None)
    reasoning: Optional[str] = None  # Why this decision was made


# =============================================================================
# Turn Metadata
# =============================================================================

class TurnMetadata(BaseModel):
    """Metadata for a turn."""

    turn_number: int
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    topic: Optional[str] = None
    intent: Optional[Intent] = None
    quality: Optional[float] = Field(ge=0.0, le=1.0, default=None)
    turn_dir: str
    embedding_id: Optional[str] = None


# =============================================================================
# Intervention
# =============================================================================

class InterventionSeverity(str, Enum):
    """Intervention request severity."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class InterventionRequest(BaseModel):
    """Request for human intervention."""

    id: str = Field(default_factory=lambda: f"int_{datetime.now().strftime('%Y%m%d%H%M%S')}")
    timestamp: datetime = Field(default_factory=datetime.now)
    type: str
    severity: InterventionSeverity
    component: str
    context: dict[str, Any] = Field(default_factory=dict)
    error_details: str
    page_state: Optional[dict[str, Any]] = None
    recovery_attempted: bool = False
    recovery_result: Optional[str] = None
    suggested_action: Optional[str] = None
    model_used: Optional[str] = None
```

---

## 6. Exception Handling

### 6.1 `libs/core/exceptions.py`

```python
"""Custom exceptions for PandaAI v2."""

from typing import Any, Optional


class PandaAIError(Exception):
    """Base exception for PandaAI v2."""

    def __init__(self, message: str, context: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.context = context or {}


class LLMError(PandaAIError):
    """LLM-related errors."""

    pass


class DocumentIOError(PandaAIError):
    """Document IO errors."""

    pass


class PhaseError(PandaAIError):
    """Pipeline phase errors."""

    def __init__(
        self,
        message: str,
        phase: int,
        context: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, context)
        self.phase = phase


class ToolError(PandaAIError):
    """MCP tool errors."""

    def __init__(
        self,
        message: str,
        tool: str,
        context: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, context)
        self.tool = tool


class ValidationError(PandaAIError):
    """Validation errors (not Pydantic)."""

    pass


class InterventionRequired(PandaAIError):
    """
    Error requiring human intervention.

    In fail-fast mode, this halts execution and notifies human.
    """

    def __init__(
        self,
        component: str,
        error: str,
        context: Optional[dict[str, Any]] = None,
        severity: str = "HIGH",
    ):
        message = f"[{severity}] Intervention required in {component}: {error}"
        super().__init__(message, context)
        self.component = component
        self.error = error
        self.severity = severity


class BudgetExceededError(PandaAIError):
    """Token budget exceeded."""

    def __init__(
        self,
        phase: int,
        budget: int,
        actual: int,
        context: Optional[dict[str, Any]] = None,
    ):
        message = f"Phase {phase} exceeded token budget: {actual}/{budget}"
        super().__init__(message, context)
        self.phase = phase
        self.budget = budget
        self.actual = actual


class ResearchError(PandaAIError):
    """Research-related errors."""

    pass


class CaptchaDetectedError(PandaAIError):
    """CAPTCHA detected during navigation."""

    def __init__(
        self,
        url: str,
        captcha_type: str,
        context: Optional[dict[str, Any]] = None,
    ):
        message = f"CAPTCHA detected ({captcha_type}) at {url}"
        super().__init__(message, context)
        self.url = url
        self.captcha_type = captcha_type
```

---

## 7. MIND/EYES Model Swap Manager

### 7.1 `libs/llm/model_swap.py`

```python
"""Model swap manager for MIND/EYES on vLLM.

EYES (vision model, Qwen3-VL-2B, ~5GB) swaps with MIND (Qwen3-Coder-30B-AWQ, ~3.3GB).
Only one model can be loaded at a time within the 24GB VRAM budget.

When vision tasks are needed:
1. Stop MIND vLLM instance
2. Start EYES vLLM instance
3. Execute vision task
4. Stop EYES, restart MIND

This swap takes ~60-90 seconds each way (model loads from disk).
"""

import asyncio
import subprocess
from pathlib import Path
from typing import Optional

from libs.core.config import get_settings
from libs.core.exceptions import InterventionRequired


class ModelSwapManager:
    """Manages MIND <-> EYES model swapping on single vLLM instance."""

    def __init__(self):
        self.settings = get_settings()
        self._current_model: str = "mind"  # mind or eyes
        self._swap_lock = asyncio.Lock()
        self._vllm_process: Optional[subprocess.Popen] = None

    @property
    def is_eyes_loaded(self) -> bool:
        """Check if EYES is currently loaded."""
        return self._current_model == "eyes"

    @property
    def is_mind_loaded(self) -> bool:
        """Check if MIND is currently loaded."""
        return self._current_model == "mind"

    async def ensure_eyes(self) -> bool:
        """
        Ensure EYES model is loaded.

        Stops MIND and starts EYES if needed.
        All text processing pauses during swap.

        Returns:
            True if EYES is now loaded
        """
        async with self._swap_lock:
            if self._current_model == "eyes":
                return True

            try:
                # 1. Stop MIND vLLM instance
                await self._stop_vllm()

                # 2. Start EYES vLLM instance
                await self._start_eyes()

                self._current_model = "eyes"
                return True

            except Exception as e:
                raise InterventionRequired(
                    component="ModelSwapManager",
                    error=f"Failed to swap to EYES: {e}",
                    context={"current_model": self._current_model},
                )

    async def ensure_mind(self) -> bool:
        """
        Ensure MIND model is loaded.

        Stops EYES and starts MIND if needed.

        Returns:
            True if MIND is now loaded
        """
        async with self._swap_lock:
            if self._current_model == "mind":
                return True

            try:
                # 1. Stop EYES vLLM instance
                await self._stop_vllm()

                # 2. Start MIND vLLM instance
                await self._start_mind()

                self._current_model = "mind"
                return True

            except Exception as e:
                raise InterventionRequired(
                    component="ModelSwapManager",
                    error=f"Failed to swap to MIND: {e}",
                    context={"current_model": self._current_model},
                )

    async def _stop_vllm(self):
        """Stop current vLLM instance."""
        if self._vllm_process:
            self._vllm_process.terminate()
            self._vllm_process.wait()
            self._vllm_process = None
            await asyncio.sleep(5)  # Allow GPU memory to free

    async def _start_mind(self):
        """Start MIND vLLM instance (Qwen3-Coder-30B-AWQ)."""
        models_dir = self.settings.project_root / "models"

        cmd = [
            "python", "-m", "vllm.entrypoints.openai.api_server",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--model", str(models_dir / "Qwen3-Coder-30B-AWQ"),
            "--served-model-name", "mind",
            "--gpu-memory-utilization", "0.80",
            "--max-model-len", "4096",
            "--enforce-eager",  # Required on WSL
            "--trust-remote-code",
        ]

        self._vllm_process = subprocess.Popen(
            cmd,
            stdout=open("logs/vllm_mind.log", "a"),
            stderr=subprocess.STDOUT,
        )

        # Wait for model to load (~30-45s)
        await asyncio.sleep(45)

    async def _start_eyes(self):
        """Start EYES vLLM instance (Qwen3-VL-2B)."""
        models_dir = self.settings.project_root / "models"

        cmd = [
            "python", "-m", "vllm.entrypoints.openai.api_server",
            "--host", "0.0.0.0",
            "--port", "8000",  # Same port - models swap
            "--model", str(models_dir / "Qwen3-VL-2B-Instruct"),
            "--served-model-name", "eyes",
            "--gpu-memory-utilization", "0.80",
            "--max-model-len", "4096",
            "--enforce-eager",  # Required on WSL
            "--trust-remote-code",
        ]

        self._vllm_process = subprocess.Popen(
            cmd,
            stdout=open("logs/vllm_eyes.log", "a"),
            stderr=subprocess.STDOUT,
        )

        # Wait for model to load (~30-45s)
        await asyncio.sleep(45)


# Singleton instance
_model_swap_manager: ModelSwapManager | None = None


def get_model_swap_manager() -> ModelSwapManager:
    """Get model swap manager singleton."""
    global _model_swap_manager
    if _model_swap_manager is None:
        _model_swap_manager = ModelSwapManager()
    return _model_swap_manager
```

### 7.2 Usage Example

```python
# In Phase 4 Coordinator when vision task is needed:

from libs.llm.model_swap import get_model_swap_manager

async def execute_vision_task(image_path: str) -> dict:
    """Execute a task requiring EYES model (Qwen3-VL-2B)."""
    swap_manager = get_model_swap_manager()

    # Swap MIND -> EYES (~60-90s overhead)
    await swap_manager.ensure_eyes()

    try:
        # Use EYES for vision task
        client = get_llm_client()
        response = await client.complete(
            model_layer="eyes",
            messages=[
                {"role": "user", "content": f"Analyze this image: {image_path}"}
            ],
        )
        return {"result": response.content}

    finally:
        # Swap back EYES -> MIND (~60-90s overhead)
        await swap_manager.ensure_mind()
```

---

## 8. Verification Checklist

Before proceeding to Phase 3, verify:

- [ ] `libs/core/config.py` loads `.env` correctly
- [ ] `libs/core/config.py` loads `model-registry.yaml`
- [ ] `libs/llm/client.py` can connect to vLLM (when running)
- [ ] `libs/llm/router.py` maps phases to models correctly
- [ ] `libs/llm/recipes.py` loads YAML recipes
- [ ] `libs/core/models.py` validates all Pydantic models
- [ ] `libs/core/exceptions.py` defines all exception types
- [ ] All imports work (`python -c "from libs.core import config"`)

---

## Deliverables Checklist

| Item | File | Status |
|------|------|--------|
| Configuration | `libs/core/config.py` | |
| LLM Client | `libs/llm/client.py` | |
| Model Router | `libs/llm/router.py` | |
| Recipe Loader | `libs/llm/recipes.py` | |
| Model Swap Manager | `libs/llm/model_swap.py` | |
| Pydantic Models | `libs/core/models.py` | |
| Exceptions | `libs/core/exceptions.py` | |
| `__init__.py` files | Various | |

---

**Previous Phase:** [01-INFRASTRUCTURE.md](./01-INFRASTRUCTURE.md)
**Next Phase:** [03-DOCUMENT-IO.md](./03-DOCUMENT-IO.md)
