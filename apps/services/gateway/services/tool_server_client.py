"""
Tool Server Client Service

Provides circuit breaker protected calls to the Tool Server service.
Handles schema validation, per-tool timeouts, and special SSE streaming
for internet research operations.
"""

import json
import logging
from typing import Any, Callable, Coroutine, Dict, Optional

import httpx
from fastapi import HTTPException

from apps.services.gateway.config import TOOL_SERVER_URL, TOOL_TIMEOUTS

logger = logging.getLogger("uvicorn.error")

# Late imports to avoid circular dependencies - these are set by dependencies.py
_tool_router = None
_tool_circuit_breaker = None
_research_ws_manager = None


def set_tool_router(router):
    """Set the tool router instance (called by dependencies.py)."""
    global _tool_router
    _tool_router = router


def set_tool_circuit_breaker(breaker):
    """Set the tool circuit breaker instance (called by dependencies.py)."""
    global _tool_circuit_breaker
    _tool_circuit_breaker = breaker


def set_research_ws_manager(manager):
    """Set the research WebSocket manager instance (called by dependencies.py)."""
    global _research_ws_manager
    _research_ws_manager = manager


# =============================================================================
# Circuit Breaker Tool Calls
# =============================================================================


async def call_tool_server_with_circuit_breaker(
    client: httpx.AsyncClient,
    tool_name: str,
    args: dict,
    timeout: Optional[float] = None,
) -> dict:
    """
    Call tool_server tool with circuit breaker protection and schema validation.

    Phase 3: Per-tool timeout configuration added for complex operations.

    Args:
        client: HTTP client
        tool_name: Name of the tool (e.g., "search.orchestrate")
        args: Tool arguments
        timeout: Request timeout in seconds (if None, uses TOOL_TIMEOUTS or 30s default)

    Returns:
        Tool response dict

    Raises:
        HTTPException: If circuit is open, schema validation fails, or tool call fails
    """
    global _tool_router, _tool_circuit_breaker, _research_ws_manager

    # Phase 3: Determine timeout (per-tool or default)
    if timeout is None:
        timeout = TOOL_TIMEOUTS.get(tool_name, 30.0)

    logger.info(f"[Circuit Breaker] {tool_name} timeout: {timeout}s")

    # STEP 1: Schema validation (prevent parameter hallucination)
    if _tool_router:
        is_valid, error_msg = _tool_router.catalog.validate_tool_call(tool_name, args)
        if not is_valid:
            logger.error(f"[Schema Validation] BLOCKED {tool_name}: {error_msg}")
            logger.error(f"[Schema Validation] Invalid args: {json.dumps(args, indent=2)}")
            # Record as failure for circuit breaker
            if _tool_circuit_breaker:
                _tool_circuit_breaker.record_failure(
                    tool_name, f"Schema validation failed: {error_msg}"
                )
            # Return error response (don't raise HTTPException - let Gateway continue)
            return {
                "status": "error",
                "error": f"Schema validation failed: {error_msg}",
                "invalid_args": args,
                "tool": tool_name,
            }

    # STEP 2: Check circuit breaker
    if _tool_circuit_breaker:
        allowed, reason = _tool_circuit_breaker.check_allowed(tool_name)
        if not allowed:
            logger.warning(f"[Circuit Breaker] Blocked call to {tool_name}: {reason}")
            raise HTTPException(status_code=503, detail=reason)

    # STEP 2.5: Special handling for internet.research - use direct call for event streaming
    if tool_name == "internet.research":
        return await _handle_internet_research(tool_name, args)

    # For all other tools, use HTTP as before
    try:
        # Make the call
        resp = await client.post(
            f"{TOOL_SERVER_URL}/{tool_name}",
            json=args,
            timeout=timeout,
        )

        # Check for success
        if resp.status_code == 200:
            if _tool_circuit_breaker:
                _tool_circuit_breaker.record_success(tool_name)
            return resp.json()
        else:
            # Record failure
            error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if _tool_circuit_breaker:
                _tool_circuit_breaker.record_failure(tool_name, error_msg)
            raise HTTPException(status_code=resp.status_code, detail=error_msg)

    except httpx.TimeoutException:
        # Phase 3: Enhanced timeout logging with configuration hints
        error_msg = f"Timeout after {timeout}s"
        logger.warning(f"[Circuit Breaker] {tool_name} TIMEOUT: {timeout}s exceeded")

        # Suggest increasing timeout if this is a complex tool
        if tool_name not in TOOL_TIMEOUTS:
            logger.warning(
                f"[Circuit Breaker] Hint: Consider adding {tool_name} to TOOL_TIMEOUTS config"
            )

        if _tool_circuit_breaker:
            _tool_circuit_breaker.record_failure(tool_name, error_msg)
        raise HTTPException(status_code=504, detail=error_msg)

    except httpx.RequestError as e:
        error_msg = f"Request error: {str(e)}"
        if _tool_circuit_breaker:
            _tool_circuit_breaker.record_failure(tool_name, error_msg)
        raise HTTPException(status_code=502, detail=error_msg)

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        if _tool_circuit_breaker:
            _tool_circuit_breaker.record_failure(tool_name, error_msg)
        raise


async def _handle_internet_research(tool_name: str, args: dict) -> dict:
    """
    Handle internet.research with SSE streaming for real-time events.

    Args:
        tool_name: Tool name (internet.research)
        args: Tool arguments

    Returns:
        Research results dict
    """
    global _tool_circuit_breaker, _research_ws_manager

    try:
        # Extract args
        query = args.get("query")
        research_goal = args.get("research_goal")
        session_id = args.get("session_id", "default")
        human_assist_allowed = args.get("human_assist_allowed", True)
        token_budget = args.get("token_budget", 10800)

        logger.info(
            f"[Gateway→ToolServer] SSE streaming call to adaptive research "
            f"(session: {session_id})"
        )

        # Call tool_server via HTTP with SSE streaming to get real-time events
        # This enables CAPTCHA intervention notifications and research progress updates

        # Build request payload
        research_payload = {
            "query": query,
            "research_goal": research_goal,
            "session_id": session_id,
            "human_assist_allowed": human_assist_allowed,
            "remaining_token_budget": token_budget if token_budget else 8000,
        }

        # Stream events from tool_server and forward to WebSocket clients
        research_timeout = TOOL_TIMEOUTS.get("internet.research", 180.0)
        result = None
        async with httpx.AsyncClient(timeout=research_timeout) as client:
            async with client.stream(
                "POST",
                f"{TOOL_SERVER_URL}/internet.research/stream",
                json=research_payload,
            ) as response:
                response.raise_for_status()

                # Parse SSE stream
                async for line in response.aiter_lines():
                    if not line or line.startswith(":"):
                        continue

                    # Parse SSE format: "data: {...}"
                    if line.startswith("data: "):
                        data_str = line[6:]  # Remove "data: " prefix
                        try:
                            event = json.loads(data_str)
                            event_type = event.get("type")

                            logger.debug(f"[Gateway] SSE event: {event_type}")

                            # Forward event to WebSocket clients
                            if _research_ws_manager:
                                await _research_ws_manager.broadcast_event(
                                    session_id, event
                                )

                            # Capture final result
                            if event_type == "research_complete":
                                result = event.get("data", {})
                                logger.info(
                                    f"[Gateway→ToolServer] Research completed: "
                                    f"{result.get('strategy', 'unknown').upper()}, "
                                    f"{result.get('stats', {}).get('sources_visited', 0)} sources"
                                )
                            elif event_type == "intervention_needed":
                                logger.info(
                                    f"[Gateway] CAPTCHA intervention needed: "
                                    f"{event.get('data', {}).get('intervention_id')}"
                                )
                        except json.JSONDecodeError as e:
                            logger.warning(f"[Gateway] Failed to parse SSE event: {e}")

        if result is None:
            raise Exception("No research_complete event received from tool_server")

        # Record success for circuit breaker
        if _tool_circuit_breaker:
            _tool_circuit_breaker.record_success(tool_name)

        # Transform SSE research_complete data to match expected Gateway format
        # Result from SSE has different structure than direct call
        return {
            "query": result.get("query", query),
            "strategy": result.get("strategy", "unknown"),
            "strategy_reason": result.get("strategy_reason", ""),
            "results": {
                "findings": result.get("findings", []),
                "synthesis": result.get("synthesis", {}),
            },
            "stats": result.get("stats", {}),
            "intelligence_cached": result.get("intelligence_cached", False),
        }

    except Exception as e:
        logger.error(f"[Gateway→ToolServer] Research error: {e}", exc_info=True)
        # Record failure for circuit breaker
        if _tool_circuit_breaker:
            _tool_circuit_breaker.record_failure(tool_name, str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Research Event Callback Factory
# =============================================================================


def create_research_event_callback(
    session_id: str,
) -> Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]:
    """
    Create a callback function for research events that broadcasts to WebSocket clients.

    Args:
        session_id: Session ID for WebSocket routing

    Returns:
        Async callback function that accepts event dicts
    """

    async def callback(event: Dict[str, Any]) -> None:
        """Broadcast research event to connected WebSocket clients."""
        if _research_ws_manager:
            await _research_ws_manager.broadcast_event(session_id, event)

    return callback
