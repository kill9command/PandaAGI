"""Chat route handlers for Gateway.

Architecture Reference:
    architecture/services/user-interface.md#Section 6

Endpoints:
    POST /chat                   - Submit user message (proxy to Orchestrator)
    WebSocket /chat/stream       - Stream response + progress
    POST /inject                 - Inject message during research
    POST /intervention/resolve   - Mark intervention as resolved

WebSocket Events (Section 6.2):
    Client -> Server:
        { type: "message", content: "find me a laptop" }
        { type: "inject", content: "skip walmart" }
        { type: "cancel" }
        { type: "intervention_resolved", intervention_id: "abc123" }

    Server -> Client:
        { type: "turn_started", turn_id: 43 }
        { type: "phase_started", phase: 0, name: "query_analyzer" }
        { type: "phase_completed", phase: 0, duration_ms: 450 }
        { type: "research_progress", vendor: "bestbuy.com", status: "visiting" }
        { type: "product_found", product: { name: "HP Victus", price: 649, ... } }
        { type: "intervention_required", intervention_id: "abc123", type: "captcha", url: "..." }
        { type: "response_chunk", content: "I found 3 laptops..." }
        { type: "response_complete", quality: 0.87 }
        { type: "turn_complete", turn_id: 43, validation: "APPROVE" }
"""

import asyncio
import json
import logging
from typing import Optional

import httpx
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel, Field

from apps.services.gateway.config import get_config


logger = logging.getLogger(__name__)
config = get_config()

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class ChatRequest(BaseModel):
    """Chat endpoint request model.

    Fields:
        message: User query (required)
        session_id: User session identifier (required)
        user_id: User identifier (defaults to "default")
        mode: "chat" or "code" mode (defaults to "chat")
    """
    message: str = Field(..., description="User query")
    session_id: str = Field(..., description="Session identifier")
    user_id: str = Field(default="default", description="User identifier")
    mode: str = Field(default="chat", description="Mode: 'chat' or 'code'")


class ChatResponse(BaseModel):
    """Chat endpoint response model.

    Fields:
        response: Synthesized answer
        turn_number: Turn identifier
        confidence: Quality score from validation (0-1)
        needs_clarification: Whether clarification is needed
        error: Whether an error occurred
    """
    response: str = Field(..., description="Synthesized answer")
    turn_number: int = Field(..., description="Turn number for this response")
    confidence: float = Field(default=0.0, description="Quality score (0-1)")
    needs_clarification: bool = Field(default=False, description="Whether clarification is needed")
    error: bool = Field(default=False, description="Whether an error occurred")


class InjectRequest(BaseModel):
    """Injection request during research.

    Allows user to send messages during active research:
        - "cancel" - Cancel ongoing research
        - "skip" - Skip current vendor
        - Custom message - Passed to research context
    """
    session_id: str = Field(..., description="Session identifier")
    message: str = Field(..., description="Injection message")


class InjectResponse(BaseModel):
    """Injection response."""
    status: str = Field(..., description="Injection status")
    message: str = Field(..., description="Status message")


class InterventionResolveRequest(BaseModel):
    """Request to mark intervention as resolved."""
    intervention_id: str = Field(..., description="Intervention ID to resolve")
    session_id: str = Field(..., description="Session identifier")
    action: str = Field(default="resolved", description="Action taken: resolved, skipped")


class InterventionResolveResponse(BaseModel):
    """Response after resolving intervention."""
    status: str = Field(..., description="Resolution status")
    message: str = Field(..., description="Status message")


# =============================================================================
# HTTP Endpoints
# =============================================================================

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Submit a user message for processing.

    This endpoint proxies the request to the Orchestrator service,
    which executes the 8-phase pipeline.

    Args:
        request: Chat request with message and session info

    Returns:
        ChatResponse with synthesized answer and metadata

    Raises:
        HTTPException: If Orchestrator is unavailable or returns error
    """
    logger.info(f"Chat request: session={request.session_id}, mode={request.mode}")
    logger.debug(f"Query: {request.message[:100]}...")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(config.request_timeout)) as client:
            response = await client.post(
                f"{config.orchestrator_url}/chat",
                json=request.model_dump(),
                headers={
                    "X-Pandora-Mode": request.mode,
                    "X-Session-Id": request.session_id,
                },
            )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                logger.error(f"Orchestrator error: {response.status_code} - {error_detail}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=error_detail,
                )

            data = response.json()
            logger.info(f"Chat complete: turn={data.get('turn_number')}, confidence={data.get('confidence', 0):.2f}")

            return ChatResponse(
                response=data.get("response", ""),
                turn_number=data.get("turn_number", 0),
                confidence=data.get("confidence", 0.0),
                needs_clarification=data.get("needs_clarification", False),
                error=data.get("error", False),
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Orchestrator")
        raise HTTPException(
            status_code=503,
            detail={"error": "Orchestrator service unavailable", "url": config.orchestrator_url},
        )
    except httpx.TimeoutException:
        logger.error("Orchestrator request timed out")
        raise HTTPException(
            status_code=504,
            detail={"error": "Request timed out", "timeout": config.request_timeout},
        )


@router.post("/inject", response_model=InjectResponse)
async def inject_message(request: InjectRequest) -> InjectResponse:
    """Inject a message during active research.

    Allows user to send commands during research:
        - "cancel" - Cancel ongoing research
        - "skip" - Skip current vendor
        - Custom message - Passed to research context

    Args:
        request: Injection request with session and message

    Returns:
        InjectResponse with status
    """
    logger.info(f"Inject request: session={request.session_id}, message={request.message}")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(
                f"{config.orchestrator_url}/inject",
                json=request.model_dump(),
            )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()
            return InjectResponse(
                status=data.get("status", "acknowledged"),
                message=data.get("message", "Injection acknowledged"),
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Orchestrator for injection")
        raise HTTPException(
            status_code=503,
            detail={"error": "Orchestrator service unavailable"},
        )


@router.post("/intervention/resolve", response_model=InterventionResolveResponse)
async def resolve_intervention(request: InterventionResolveRequest) -> InterventionResolveResponse:
    """Mark an intervention as resolved.

    Called after user solves a CAPTCHA, logs in, or otherwise
    resolves a blocker during research.

    Args:
        request: Resolution request with intervention ID and action

    Returns:
        InterventionResolveResponse with status
    """
    logger.info(f"Intervention resolve: id={request.intervention_id}, action={request.action}")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(
                f"{config.orchestrator_url}/intervention/resolve",
                json=request.model_dump(),
            )

            if response.status_code != 200:
                error_detail = response.json() if response.content else {"error": "Unknown error"}
                raise HTTPException(status_code=response.status_code, detail=error_detail)

            data = response.json()
            return InterventionResolveResponse(
                status=data.get("status", "resolved"),
                message=data.get("message", "Intervention resolved"),
            )

    except httpx.ConnectError:
        logger.error("Cannot connect to Orchestrator for intervention resolution")
        raise HTTPException(
            status_code=503,
            detail={"error": "Orchestrator service unavailable"},
        )


# =============================================================================
# WebSocket Endpoint
# =============================================================================

@router.websocket("/chat/stream")
async def websocket_chat_stream(websocket: WebSocket):
    """WebSocket endpoint for streaming chat responses.

    Enables real-time progress updates during long-running operations
    like research. Proxies WebSocket connection to Orchestrator.

    Client -> Server Messages:
        { type: "message", content: "find me a laptop", session_id: "...", user_id: "...", mode: "chat" }
        { type: "inject", content: "skip walmart" }
        { type: "cancel" }
        { type: "intervention_resolved", intervention_id: "abc123" }

    Server -> Client Messages:
        { type: "turn_started", turn_id: 43 }
        { type: "phase_started", phase: 0, name: "query_analyzer" }
        { type: "phase_completed", phase: 0, duration_ms: 450 }
        { type: "research_progress", vendor: "bestbuy.com", status: "visiting" }
        { type: "research_progress", vendor: "bestbuy.com", status: "done", products: 3 }
        { type: "product_found", product: { name: "HP Victus", price: 649, ... } }
        { type: "intervention_required", intervention_id: "abc123", type: "captcha", url: "..." }
        { type: "response_chunk", content: "I found 3 laptops..." }
        { type: "response_complete", quality: 0.87 }
        { type: "turn_complete", turn_id: 43, validation: "APPROVE" }
        { type: "error", message: "..." }
    """
    await websocket.accept()
    logger.info("WebSocket connection accepted")

    orchestrator_ws: Optional[websockets.WebSocketClientProtocol] = None

    try:
        # Connect to Orchestrator WebSocket
        orchestrator_ws_url = f"{config.orchestrator_ws_url}/chat/stream"
        orchestrator_ws = await websockets.connect(
            orchestrator_ws_url,
            ping_interval=config.ws_ping_interval,
            ping_timeout=config.ws_ping_timeout,
        )
        logger.info(f"Connected to Orchestrator WebSocket: {orchestrator_ws_url}")

        async def forward_to_orchestrator():
            """Forward messages from client to Orchestrator."""
            try:
                while True:
                    data = await websocket.receive_text()
                    logger.debug(f"Client -> Orchestrator: {data[:100]}...")
                    await orchestrator_ws.send(data)
            except WebSocketDisconnect:
                logger.info("Client disconnected")
            except Exception as e:
                logger.error(f"Error forwarding to Orchestrator: {e}")

        async def forward_to_client():
            """Forward messages from Orchestrator to client."""
            try:
                async for message in orchestrator_ws:
                    logger.debug(f"Orchestrator -> Client: {str(message)[:100]}...")
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)
            except websockets.ConnectionClosed:
                logger.info("Orchestrator WebSocket closed")
            except Exception as e:
                logger.error(f"Error forwarding to client: {e}")

        # Run both forwarding tasks concurrently
        await asyncio.gather(
            forward_to_orchestrator(),
            forward_to_client(),
            return_exceptions=True,
        )

    except websockets.exceptions.WebSocketException as e:
        logger.error(f"Cannot connect to Orchestrator WebSocket: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"Cannot connect to Orchestrator: {str(e)}",
        })

    except WebSocketDisconnect:
        logger.info("Client WebSocket disconnected")

    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
        except Exception:
            pass

    finally:
        # Clean up Orchestrator connection
        if orchestrator_ws:
            try:
                await orchestrator_ws.close()
            except Exception:
                pass

        # Close client connection
        try:
            await websocket.close()
        except Exception:
            pass

        logger.info("WebSocket connections closed")
