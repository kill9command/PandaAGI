"""Orchestrator configuration module.

Architecture Reference:
    architecture/services/orchestrator-service.md

Orchestrator Configuration:
    - ORCHESTRATOR_HOST: Host to bind Orchestrator (default: 0.0.0.0)
    - ORCHESTRATOR_PORT: Port to bind Orchestrator (default: 8090)
    - VLLM_URL: Base URL for vLLM service (default: http://localhost:8000/v1)
    - QDRANT_HOST: Qdrant vector database host (default: localhost)
    - QDRANT_PORT: Qdrant vector database port (default: 6333)
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrchestratorConfig(BaseSettings):
    """Orchestrator service configuration.

    The Orchestrator is the internal API that runs the 8-phase pipeline.
    The Gateway forwards requests here for processing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Orchestrator server settings
    host: str = Field(default="0.0.0.0", alias="ORCHESTRATOR_HOST")
    port: int = Field(default=8090, alias="ORCHESTRATOR_PORT")
    workers: int = Field(default=1, alias="ORCHESTRATOR_WORKERS")

    # vLLM connection (single instance serves MIND model for all text roles)
    vllm_host: str = Field(default="localhost", alias="VLLM_HOST")
    vllm_port: int = Field(default=8000, alias="VLLM_PORT")

    # Qdrant connection (vector database for memories)
    qdrant_host: str = Field(default="localhost", alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, alias="QDRANT_PORT")

    # Timeouts (in seconds)
    pipeline_timeout: float = Field(
        default=600.0,
        description="Maximum time for full pipeline execution (10 minutes)"
    )
    phase_timeout: float = Field(
        default=120.0,
        description="Maximum time for individual phase execution (2 minutes)"
    )
    llm_timeout: float = Field(
        default=60.0,
        description="LLM request timeout"
    )

    # Loop limits (from architecture)
    max_planner_iterations: int = Field(
        default=5,
        description="Maximum Planner-Coordinator iterations"
    )
    max_retry_loops: int = Field(
        default=1,
        description="Maximum RETRY loops (back to Phase 3)"
    )
    max_revise_loops: int = Field(
        default=2,
        description="Maximum REVISE loops (back to Phase 5)"
    )

    # Cache settings
    cache_default_ttl: int = Field(
        default=3600,
        description="Default cache TTL in seconds (1 hour)"
    )

    # Development settings
    dev_mode: bool = Field(default=True, alias="DEV_MODE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Paths
    project_root: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent.parent
    )

    @property
    def vllm_url(self) -> str:
        """Get the vLLM base URL."""
        return f"http://{self.vllm_host}:{self.vllm_port}/v1"

    @property
    def qdrant_url(self) -> str:
        """Get the Qdrant URL."""
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @property
    def panda_system_docs(self) -> Path:
        """Get panda_system_docs directory for turn storage."""
        return self.project_root / "panda_system_docs"

    @property
    def turns_dir(self) -> Path:
        """Get base turns directory."""
        return self.panda_system_docs / "users"


@lru_cache()
def get_config() -> OrchestratorConfig:
    """Get cached Orchestrator configuration."""
    return OrchestratorConfig()
