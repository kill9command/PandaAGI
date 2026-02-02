"""
Gateway Router Modules

Provides FastAPI routers for all Gateway endpoints.
Organized by function following the architecture spec.

Architecture Reference:
    architecture/services/user-interface.md#Section 6

Router Organization:
    - health: Health check and basic status endpoints
    - thinking: Thinking visualization SSE endpoints
    - jobs: Async job management endpoints
    - transcripts: Turn history and trace endpoints
    - interventions: CAPTCHA and permission intervention endpoints
    - internal: Debug, cache, and other internal endpoints
    - tools: Tool discovery and metrics endpoints
"""

from apps.services.gateway.routers.health import router as health_router
from apps.services.gateway.routers.thinking import router as thinking_router
from apps.services.gateway.routers.jobs import router as jobs_router
from apps.services.gateway.routers.transcripts import router as transcripts_router
from apps.services.gateway.routers.interventions import router as interventions_router
from apps.services.gateway.routers.chat_completions import router as chat_completions_router
from apps.services.gateway.routers.internal import router as internal_router
from apps.services.gateway.routers.approvals import router as approvals_router
from apps.services.gateway.routers.tools import router as tools_router
from apps.services.gateway.routers.websockets import router as websockets_router
from apps.services.gateway.routers.ui import router as ui_router

__all__ = [
    "health_router",
    "thinking_router",
    "jobs_router",
    "transcripts_router",
    "interventions_router",
    "chat_completions_router",
    "internal_router",
    "approvals_router",
    "tools_router",
    "websockets_router",
    "ui_router",
]
