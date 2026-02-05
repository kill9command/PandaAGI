"""Configuration management for PandaAI v2."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """PostgreSQL database settings."""

    host: str = Field(default="localhost", alias="POSTGRES_HOST")
    port: int = Field(default=5432, alias="POSTGRES_PORT")
    database: str = Field(default="panda", alias="POSTGRES_DB")
    user: str = Field(default="panda", alias="POSTGRES_USER")
    password: str = Field(default="panda", alias="POSTGRES_PASSWORD")

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
    api_key: str = Field(default="qwen-local", alias="SOLVER_API_KEY")

    # Single vLLM instance serves MIND (handles all text roles via temperature)
    # REFLEX/NERVES/VOICE roles all use MIND with different temperatures
    # EYES loads on-demand via model swap (MIND ↔ EYES)

    def get_base_url(self, model_layer: str = "mind") -> str:
        """Get vLLM base URL. Single instance serves all local models."""
        return f"http://{self.host}:{self.port}/v1"


class ServerSettings(BaseSettings):
    """Remote SERVER model settings (Qwen3-Coder-30B)."""

    endpoint: str = Field(default="http://localhost:8001", alias="SERVER_ENDPOINT")
    model: str = Field(default="Qwen/Qwen3-Coder-30B-AWQ", alias="SERVER_MODEL")
    timeout: int = Field(default=120, alias="SERVER_TIMEOUT")


class ModelSettings(BaseSettings):
    """Model configuration settings."""

    # Model names as served by vLLM (--served-model-name)
    mind: str = Field(default="qwen3-coder", alias="MIND_MODEL")

    # Cold pool models
    eyes: str = Field(default="eyes", alias="EYES_MODEL")

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


class ToolServerSettings(BaseSettings):
    """Tool Server service settings."""

    host: str = Field(default="0.0.0.0", alias="TOOL_SERVER_HOST")
    port: int = Field(default=8090, alias="TOOL_SERVER_PORT")
    workers: int = Field(default=1, alias="TOOL_SERVER_WORKERS")

    @property
    def base_url(self) -> str:
        """Get Tool Server base URL."""
        return f"http://{self.host}:{self.port}"


class ResearchSettings(BaseSettings):
    """Research configuration settings."""

    min_successful_vendors: int = Field(default=3, alias="MIN_SUCCESSFUL_VENDORS")
    max_passes: int = Field(default=3, alias="RESEARCH_MAX_PASSES")
    satisfaction_threshold: float = Field(default=0.8, alias="RESEARCH_SATISFACTION_THRESHOLD")
    min_request_interval_ms: int = Field(default=2000, alias="MIN_REQUEST_INTERVAL_MS")


class BrowserSettings(BaseModel):
    """Browser automation settings (uses nested delimiter PANDA_BROWSER__)."""

    headless: bool = True
    timeout_ms: int = 30000
    viewport_width: int = 1920
    viewport_height: int = 1080


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",  # Use BROWSER__HEADLESS=true for nested settings
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
    tool_server: ToolServerSettings = Field(default_factory=ToolServerSettings)
    research: ResearchSettings = Field(default_factory=ResearchSettings)
    browser_config: BrowserSettings = Field(default_factory=BrowserSettings)

    # Paths
    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent)

    @property
    def panda_system_docs(self) -> Path:
        """Get panda_system_docs directory."""
        return self.project_root / "panda_system_docs"

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
