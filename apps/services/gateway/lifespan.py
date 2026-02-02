"""
Gateway Application Lifespan Handler

Manages application startup and shutdown events.
Initializes all singleton dependencies during startup.

Architecture Reference:
    architecture/Implementation/04-SERVICES-OVERVIEW.md
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.services.gateway.dependencies import initialize_all
from libs.core.logging_config import setup_logging, get_logger

# Note: We use uvicorn.error logger until setup_logging is called,
# then switch to our unified logger
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.

    Handles startup and shutdown events for the Gateway service.

    Startup:
        - Initializes all singleton dependencies
        - Logs startup message

    Shutdown:
        - Logs shutdown message
        - (Future) Cleanup resources if needed

    Args:
        app: FastAPI application instance
    """
    # ==========================================================================
    # STARTUP
    # ==========================================================================

    # Initialize centralized logging FIRST
    # This ensures all subsequent logs go to logs/panda/system.log
    setup_logging(service_name="gateway")

    # Now use unified logger
    gateway_logger = get_logger("gateway")
    gateway_logger.info("Gateway starting...")

    # Initialize all singleton dependencies
    # This triggers lazy initialization in the correct order
    try:
        initialize_all()
        gateway_logger.info("All dependencies initialized successfully")
    except Exception as e:
        gateway_logger.error(f"Failed to initialize dependencies: {e}")
        raise

    # Log service status
    from apps.services.gateway.dependencies import is_unified_flow_enabled

    if is_unified_flow_enabled():
        gateway_logger.info("Unified 7-phase flow is ENABLED")
    else:
        gateway_logger.warning("Unified flow is DISABLED - requests will fail")

    # Initialize skill registry - discover available skills
    try:
        from libs.gateway.skill_registry import init_skill_registry
        skill_registry = await init_skill_registry()
        skill_count = len(skill_registry.skills)
        gateway_logger.info(f"Skill registry initialized: {skill_count} skills discovered")
    except Exception as e:
        gateway_logger.warning(f"Skill registry initialization failed (non-fatal): {e}")

    gateway_logger.info("Gateway ready to accept requests on port 9000")

    # ==========================================================================
    # YIELD - Application runs here
    # ==========================================================================

    yield

    # ==========================================================================
    # SHUTDOWN
    # ==========================================================================

    gateway_logger.info("Gateway shutting down...")

    # Future: Add cleanup logic here if needed
    # - Close database connections
    # - Flush caches
    # - Cancel pending tasks

    gateway_logger.info("Gateway shutdown complete")
