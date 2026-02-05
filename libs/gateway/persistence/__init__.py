"""
Panda Persistence Module - Turn management and storage.

Implements Phase 8 (Save) persistence and turn artifact storage:
- Turn directory creation and path resolution
- Document writers and index updates
- Turn metadata storage and search indexing
- Visit records for cached web page access

Architecture Reference:
    architecture/concepts/main-system-patterns/phase8-save.md
    architecture/concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md

Design Notes:
- Multiple turn directory roots exist for historical reasons:
  - Legacy: panda_system_docs/turns/
  - Current: panda_system_docs/obsidian_memory/Users/{user}/turns/
  Use UserPathResolver to get the correct root for a session.
- TurnManager may write user_query.md for backward compatibility, but
  context.md §0 is the canonical source of truth per architecture
- Turn metadata includes legacy fields (action_needed) that are still
  indexed for retrieval; Phase 1 now outputs user_purpose instead

Contains:
- TurnDirectory: Turn directory creation and management
- TurnSaver: Document persistence (implements "save full docs")
- TurnCounter: Monotonic turn ID generation
- TurnSearchIndex: Search indexing for turn retrieval
- UserPathResolver: User-specific path resolution
- DocumentWriter: Generic document writing utilities
"""

from libs.gateway.persistence.turn_manager import TurnDirectory
from libs.gateway.persistence.turn_saver import TurnSaver
from libs.gateway.persistence.turn_counter import TurnCounter
from libs.gateway.persistence.turn_search_index import TurnSearchIndex
from libs.gateway.persistence.turn_index_db import get_turn_index_db
from libs.gateway.persistence.user_paths import UserPathResolver
from libs.gateway.persistence.document_writer import DocumentWriter, get_document_writer

__all__ = [
    "TurnDirectory",
    "TurnSaver",
    "TurnCounter",
    "TurnSearchIndex",
    "get_turn_index_db",
    "UserPathResolver",
    "DocumentWriter",
    "get_document_writer",
]
