"""Gateway route handlers.

Architecture Reference:
    architecture/services/user-interface.md#Section 6

Endpoints (Section 6.1):
    POST   /chat                 - Submit user message
    WS     /chat/stream          - Stream response + progress
    POST   /inject               - Inject message during research
    POST   /intervention/resolve - Mark intervention as resolved
    GET    /turns                - List recent turns
    GET    /turns/{id}           - Get specific turn
    GET    /status               - System health
    GET    /health               - Simple health check (in app.py)
    GET    /metrics              - Observability metrics
    POST   /memory               - Store memory
    GET    /memory/search        - Search memories
    DELETE /memory/{id}          - Delete memory
    GET    /cache                - List cache
    GET    /cache/{topic}        - Get cache entry
    DELETE /cache                - Clear cache
    GET    /diff/last            - Get last proposed diff
"""

from apps.services.gateway.routes.chat import router as chat_router
from apps.services.gateway.routes.turns import router as turns_router
from apps.services.gateway.routes.memory import router as memory_router
from apps.services.gateway.routes.cache import router as cache_router
from apps.services.gateway.routes.status import router as status_router
from apps.services.gateway.routes.diff import router as diff_router

__all__ = [
    "chat_router",
    "turns_router",
    "memory_router",
    "cache_router",
    "status_router",
    "diff_router",
]
