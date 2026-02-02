"""
Gateway Configuration Module

Centralizes all environment variables, path constants, and configuration
for the Gateway service. Follows the pattern from Orchestrator service.

Architecture Reference:
    architecture/Implementation/04-SERVICES-OVERVIEW.md
    architecture/services/user-interface.md#Section 6
"""

import os
import pathlib
import logging
from functools import lru_cache
from typing import Dict, List, Optional, Any

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger("uvicorn.error")

# =============================================================================
# Service URLs and Connection Settings
# =============================================================================

ORCH_URL = os.getenv("ORCH_URL", "http://127.0.0.1:8090")

# Guide/Coordinator endpoints (fall back to legacy SOLVER_/THINK_ envs for compatibility)
GUIDE_URL = os.getenv("GUIDE_URL") or os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
COORDINATOR_URL = os.getenv("COORDINATOR_URL") or os.getenv("THINK_URL", "http://127.0.0.1:8000/v1/chat/completions")

# Model identifiers for OpenAI-compatible requests
GUIDE_MODEL_ID = os.getenv("GUIDE_MODEL_ID") or os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
COORDINATOR_MODEL_ID = os.getenv("COORDINATOR_MODEL_ID") or os.getenv("THINK_MODEL_ID", GUIDE_MODEL_ID)

# API Keys
API_KEY = os.getenv("GATEWAY_API_KEY")
GUIDE_API_KEY = os.getenv("GUIDE_API_KEY") or os.getenv("SOLVER_API_KEY") or os.getenv("SOLVER_BEARER", "qwen-local")
COORDINATOR_API_KEY = os.getenv("COORDINATOR_API_KEY") or os.getenv("THINK_API_KEY") or GUIDE_API_KEY

# Build headers
GUIDE_HEADERS: Dict[str, str] = {}
if GUIDE_API_KEY:
    GUIDE_HEADERS["Authorization"] = f"Bearer {GUIDE_API_KEY}"
COORDINATOR_HEADERS: Dict[str, str] = {}
if COORDINATOR_API_KEY:
    COORDINATOR_HEADERS["Authorization"] = f"Bearer {COORDINATOR_API_KEY}"

# Legacy compatibility aliases
SOLVER_URL = GUIDE_URL
THINK_URL = COORDINATOR_URL
SOLVER_MODEL_ID = GUIDE_MODEL_ID
THINK_MODEL_ID = COORDINATOR_MODEL_ID
SOLVER_API_KEY = GUIDE_API_KEY
THINK_API_KEY = COORDINATOR_API_KEY
SOLVER_HEADERS = GUIDE_HEADERS
THINK_HEADERS = COORDINATOR_HEADERS

# =============================================================================
# Pipeline Settings
# =============================================================================

MAX_CYCLES = int(os.getenv("MAX_CYCLES", "3"))
TOKEN_BUDGET = int(os.getenv("TOKEN_BUDGET", "12000"))
MODEL_TIMEOUT = float(os.getenv("MODEL_TIMEOUT", "90"))

# =============================================================================
# Path Constants
# =============================================================================

PROMPTS_DIR = pathlib.Path(os.getenv("PROMPTS_DIR", "apps/prompts"))
STATIC_DIR = pathlib.Path(os.getenv("STATIC_DIR", "static"))
PROMPT_BACKUP_DIR = pathlib.Path(os.getenv("PROMPT_BACKUP_DIR", "project_build_instructions/corpora/oldprompts"))
TRANSCRIPTS_DIR = pathlib.Path(os.getenv("TRANSCRIPTS_DIR", "transcripts"))
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

MEM_INDEX_PATH = pathlib.Path(os.getenv("LONG_TERM_MEMORY_INDEX", "panda_system_docs/memory/long_term/index.json"))
MEM_JSON_DIR = pathlib.Path(os.getenv("LONG_TERM_MEMORY_DIR", "panda_system_docs/memory/long_term/json"))

SHARED_STATE_DIR = pathlib.Path(os.getenv("SHARED_STATE_DIR", "panda_system_docs/shared_state"))
SHARED_STATE_DIR.mkdir(parents=True, exist_ok=True)

TOOL_CATALOG_PATH = pathlib.Path(
    os.getenv("TOOL_CATALOG_PATH", "project_build_instructions/gateway/tool_catalog.json")
)

# =============================================================================
# Workspace Configuration (Repo Browser / File Tree)
# =============================================================================

_DEFAULT_REPOS_BASE = pathlib.Path(
    os.getenv("REPOS_BASE", str(pathlib.Path.cwd()))
).expanduser()

CONFIG_DIR = pathlib.Path(
    os.getenv("PANDORA_CONFIG_DIR", pathlib.Path.home() / ".config" / "pandora")
).expanduser()
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

REPOS_BASE_CONFIG_PATH = CONFIG_DIR / "repos_base.txt"


def _load_repos_base() -> pathlib.Path:
    """Load repo base from config file or fall back to default/env."""
    workspace_logger = logging.getLogger("workspace")
    if REPOS_BASE_CONFIG_PATH.exists():
        try:
            raw = REPOS_BASE_CONFIG_PATH.read_text(encoding="utf-8").strip()
            if raw:
                candidate = pathlib.Path(raw).expanduser().resolve()
                if candidate.exists() and candidate.is_dir():
                    workspace_logger.info(f"[Workspace] Loaded repo base from config: {candidate}")
                    return candidate
                workspace_logger.warning(
                    "[Workspace] Stored repo base invalid (%s). Falling back to default.",
                    raw,
                )
        except Exception as err:
            workspace_logger.error(f"[Workspace] Failed to read repo base config: {err}")
    try:
        return _DEFAULT_REPOS_BASE.resolve()
    except Exception:
        return pathlib.Path.cwd().resolve()


def _persist_repos_base(path: pathlib.Path) -> None:
    """Persist repo base path to config file."""
    workspace_logger = logging.getLogger("workspace")
    try:
        REPOS_BASE_CONFIG_PATH.write_text(str(path), encoding="utf-8")
    except Exception as err:
        workspace_logger.error(f"[Workspace] Failed to persist repo base {path}: {err}")


# Global mutable - can be updated at runtime
REPOS_BASE = _load_repos_base()


def set_repos_base(path: pathlib.Path, persist: bool = True) -> pathlib.Path:
    """Update the global repo base and optionally persist to disk."""
    global REPOS_BASE
    workspace_logger = logging.getLogger("workspace")
    REPOS_BASE = path.resolve()
    if persist:
        _persist_repos_base(REPOS_BASE)
    workspace_logger.info(f"[Workspace] Repo base set to {REPOS_BASE}")
    return REPOS_BASE


def get_repos_base() -> pathlib.Path:
    """Get current repos base path."""
    return REPOS_BASE


# =============================================================================
# Memory and Context Settings
# =============================================================================

MEMORY_RECALL_ENABLE = os.getenv("MEMORY_RECALL_ENABLE", "1") == "1"
MEMORY_RECALL_K = int(os.getenv("MEMORY_RECALL_K", "3"))
PROFILE_MEMORY_MAX = int(os.getenv("PROFILE_MEMORY_MAX", "5"))

# Context compression configuration
CONTEXT_WINDOW_SIZE = int(os.getenv("CONTEXT_WINDOW_SIZE", "10"))  # Messages to keep uncompressed
CONTEXT_KEEP_RECENT = int(os.getenv("CONTEXT_KEEP_RECENT", "3"))  # Always keep N most recent
CONTEXT_COMPRESSION_ENABLE = os.getenv("CONTEXT_COMPRESSION_ENABLE", "1") == "1"

# LLM curation flag
ENABLE_LLM_CURATION = os.getenv("ENABLE_LLM_CURATION", "false").lower() == "true"

# =============================================================================
# Tracing and Debug Settings
# =============================================================================

TRACE_VERBOSE = os.getenv("TRACE_VERBOSE", "0") == "1"
TRACE_MAX_PREVIEW = int(os.getenv("TRACE_MAX_PREVIEW", "800"))
CONTINUE_WEBHOOK = os.getenv("CONTINUE_WEBHOOK", "")

# =============================================================================
# Tool Timeouts (Per-tool configuration)
# =============================================================================

TOOL_TIMEOUTS: Dict[str, float] = {
    # Unified internet research with browser verification needs extra time
    # Increased to 7200s (2 hours) to allow for CAPTCHA solving and full research
    "internet.research": 7200.0,

    # Commerce tools need longer timeout for URL verification (legacy)
    "commerce.search_offers": 360.0,

    # Research tools may need comprehensive search
    "research.orchestrate": 360.0,

    # Purchasing verification is moderate (legacy)
    "purchasing.lookup": 60.0,

    # Default: 30s for most tools (if not specified here)
}

# =============================================================================
# Tool Permission Sets (Mode Gates)
# =============================================================================

# Tools allowed in chat mode (read-only + research)
CHAT_ALLOWED = {
    "doc.search",
    "code.search",
    "fs.read",
    "file.read",  # Token-aware file reading
    "file.glob",
    "file.grep",
    "repo.describe",
    "memory.create",
    "memory.query",
    "wiki.search",
    "ocr.read",
    "bom.build",
    "internet.research",
    "commerce.search_offers",
    "commerce.search_with_recommendations",
    "commerce.quick_search",
    "purchasing.lookup",
}

# Tools allowed in code/continue mode (includes write operations)
CONT_ALLOWED = CHAT_ALLOWED | {
    "file.write",
    "file.create",
    "file.edit",
    "file.delete",
    "code.apply_patch",
    "git.commit",
    "code.format",
    "test.run",
    "docs.write_spreadsheet",
    "bash.execute",
}

# =============================================================================
# Keyword Constants (for intent detection)
# =============================================================================

PRICING_KEYWORDS = (
    "price",
    "pricing",
    "cost",
    "sale",
    "for sale",
    "buy",
    "purchase",
    "parts list",
    "part list",
    "bill of materials",
    "bom",
    "inventory",
    "availability",
    "in stock",
    "drone parts",
    "component list",
    "spreadsheet",
    "csv",
)

SPREADSHEET_KEYWORDS = (
    "spreadsheet",
    "csv",
    "excel",
    "sheet",
    "table",
    "ods",
    "google sheet",
    "write spreadsheet",
    "create spreadsheet",
)

# =============================================================================
# Runtime Policy (Mutable at runtime via API)
# =============================================================================

RUNTIME_POLICY: Dict[str, Any] = {
    "chat_allow_file_create": os.getenv("CHAT_ALLOW_FILE_CREATE", "0") == "1",
    "write_confirm": os.getenv("WRITE_CONFIRM", "1") == "1",
    "chat_allowed_write_paths": [s.strip() for s in os.getenv("CHAT_ALLOWED_WRITE_PATHS", "").split(",") if s.strip()],
    "tool_enables": {},
}


def get_allowed_write_roots() -> List[str]:
    """Get list of allowed write paths from runtime policy."""
    roots = RUNTIME_POLICY.get("chat_allowed_write_paths") or []
    if roots:
        return roots
    return [s.strip() for s in os.getenv("CHAT_ALLOWED_WRITE_PATHS", "").split(",") if s.strip()]


def is_tool_enabled(name: str) -> bool:
    """Check if a tool is enabled (not explicitly disabled)."""
    te = RUNTIME_POLICY.get("tool_enables") or {}
    if name in te:
        return bool(te[name])
    # env gate for quick disables (comma-separated names)
    disabled = [s.strip() for s in os.getenv("DISABLED_TOOLS", "").split(",") if s.strip()]
    return name not in disabled


# =============================================================================
# Prompt Configuration
# =============================================================================

# Prompts whitelist for editing via API
PROMPT_WHITELIST = {
    "solver_system.md",
    "thinking_system.md",
    "context_manager.md",
    "io_contracts.md",
}


def read_prompt(name: str) -> str:
    """Read a prompt file from PROMPTS_DIR."""
    try:
        p = PROMPTS_DIR / name
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


# Module cache for dynamic assembly (avoids I/O overhead)
_MODULE_CACHE: Dict[str, str] = {}


def read_prompt_cached(name: str) -> str:
    """Read prompt with caching to avoid repeated I/O."""
    if name not in _MODULE_CACHE:
        _MODULE_CACHE[name] = read_prompt(name)
    return _MODULE_CACHE[name]


# Pre-load commonly used prompts
CONTEXT_MANAGER_SYSTEM = read_prompt("context_manager.md")


# =============================================================================
# Pydantic Settings Class (for dependency injection)
# =============================================================================


class GatewayConfig(BaseSettings):
    """Gateway service configuration using Pydantic settings.

    Provides structured access to configuration with validation.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Gateway server settings
    host: str = Field(default="0.0.0.0", alias="GATEWAY_HOST")
    port: int = Field(default=9000, alias="GATEWAY_PORT")
    workers: int = Field(default=1, alias="GATEWAY_WORKERS")

    # Orchestrator connection
    orchestrator_host: str = Field(default="localhost", alias="ORCHESTRATOR_HOST")
    orchestrator_port: int = Field(default=8090, alias="ORCHESTRATOR_PORT")

    # Timeouts
    request_timeout: float = Field(default=300.0, description="HTTP request timeout in seconds")
    ws_ping_interval: float = Field(default=30.0, description="WebSocket ping interval in seconds")
    ws_ping_timeout: float = Field(default=10.0, description="WebSocket ping timeout in seconds")

    # Development settings
    dev_mode: bool = Field(default=True, alias="DEV_MODE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def orchestrator_url(self) -> str:
        """Get the Orchestrator base URL."""
        return f"http://{self.orchestrator_host}:{self.orchestrator_port}"

    @property
    def orchestrator_ws_url(self) -> str:
        """Get the Orchestrator WebSocket URL."""
        return f"ws://{self.orchestrator_host}:{self.orchestrator_port}"


@lru_cache()
def get_config() -> GatewayConfig:
    """Get cached Gateway configuration."""
    return GatewayConfig()
