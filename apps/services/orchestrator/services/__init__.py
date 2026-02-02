"""
PandaAI Orchestrator Services Package

Core services for the orchestrator:
- PipelineService: Executes the 8-phase pipeline
- TurnManager: Manages turn lifecycle and state
- SessionManager: Manages session state
- LLMClient: Communicates with vLLM server
- MemoryStore: Qdrant-based vector memory storage
- TurnStore: File-based turn persistence
- CacheStore: In-memory cache with TTL

Architecture Reference:
    architecture/LLM-ROLES/llm-roles-reference.md
    architecture/main-system-patterns/phase*.md
    architecture/DOCUMENT-IO-SYSTEM/MEMORY_ARCHITECTURE.md
"""

from apps.services.orchestrator.services.llm_client import LLMClient, LLMRole, get_llm_client
from apps.services.orchestrator.services.turn_manager import TurnManager, get_turn_manager
from apps.services.orchestrator.services.session_manager import SessionManager, Session, get_session_manager
from apps.services.orchestrator.services.pipeline import PipelineService, get_pipeline_service
from apps.services.orchestrator.services.memory_store import MemoryStore, Memory
from apps.services.orchestrator.services.turn_store import TurnStore, Turn, TurnSummary
from apps.services.orchestrator.services.cache_store import CacheStore, CacheEntry

__all__ = [
    # LLM Client
    "LLMClient",
    "LLMRole",
    "get_llm_client",
    # Turn Manager
    "TurnManager",
    "get_turn_manager",
    # Session Manager
    "SessionManager",
    "Session",
    "get_session_manager",
    # Pipeline Service
    "PipelineService",
    "get_pipeline_service",
    # Storage Services
    "MemoryStore",
    "Memory",
    "TurnStore",
    "Turn",
    "TurnSummary",
    "CacheStore",
    "CacheEntry",
]
