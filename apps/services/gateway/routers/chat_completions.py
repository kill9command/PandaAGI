"""
Chat Completions Router

The main chat endpoint that runs the unified 8-phase flow locally.
This is the primary endpoint used by the webapp.

Endpoints:
    POST /v1/chat/completions - Process chat with unified flow
    POST /chat/completions    - Alias for /v1/chat/completions
"""

import logging
import time
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException

from apps.services.gateway.config import (
    API_KEY,
    GUIDE_URL,
    GUIDE_HEADERS,
    GUIDE_MODEL_ID,
    MODEL_TIMEOUT,
)
from apps.services.gateway.dependencies import (
    get_unified_flow,
    get_claude_flow,
    is_unified_flow_enabled,
)
# NOTE: get_intent_classifier removed - Phase 0 now extracts user_purpose via LLM
from apps.services.gateway.services.thinking import (
    ThinkingEvent,
    emit_thinking_event,
)
from apps.services.gateway.utils.trace import (
    build_trace_envelope,
    append_trace,
)
from apps.services.gateway.utils.text import (
    last_user_subject,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["chat_completions"])


def _profile_key(user_id: Optional[str]) -> str:
    """Generate a profile key from user_id."""
    return user_id or "default"


@router.post("/v1/chat/completions")
@router.post("/chat/completions")
async def chat_completions(
    payload: dict,
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_research_mode: str | None = Header(default=None),
    clear_session: bool = False,
):
    """
    Main chat endpoint - processes user messages through the unified 8-phase flow.

    This is the primary endpoint used by the webapp for all chat interactions.

    Args:
        payload: Chat request with messages, mode, session_id, etc.
        authorization: Bearer token for API key auth
        x_user_id: User ID from header
        x_research_mode: Research mode (lightweight bypasses flow)
        clear_session: Whether to clear session context

    Returns:
        OpenAI-compatible chat completion response
    """
    # Optional API-key check (enabled when GATEWAY_API_KEY is set)
    if API_KEY:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Missing API key")
        token = authorization.split(" ", 1)[1]
        if token != API_KEY:
            raise HTTPException(401, "Invalid API key")

    # ========================================
    # LIGHTWEIGHT RESEARCH MODE (DISABLED for research/commerce)
    # ========================================
    if x_research_mode == "lightweight":
        user_msg = payload.get("messages", [])[-1]["content"].lower() if payload.get("messages") else ""

        # Block lightweight mode for research/commerce queries
        research_keywords = ["find", "search", "buy", "purchase", "for sale", "hamster", "product", "vendor", "price"]
        is_research_query = any(keyword in user_msg for keyword in research_keywords)

        if is_research_query:
            logger.warning(
                f"[Gateway] LIGHTWEIGHT MODE blocked for research query: '{user_msg[:50]}...'"
            )
            logger.info("[Gateway] Forcing full unified flow instead of lightweight bypass")
            # Fall through to normal flow below
        else:
            logger.info(f"[Gateway] LIGHTWEIGHT MODE: Direct LLM call for non-research query")

            messages = payload.get("messages", [])
            if not messages:
                raise HTTPException(400, "messages required for lightweight mode")

            model = payload.get("model", GUIDE_MODEL_ID)
            max_tokens = payload.get("max_tokens", 1000)
            temperature = payload.get("temperature", 0.3)

            # Direct LLM call (no flow overhead)
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    llm_resp = await client.post(
                        GUIDE_URL,
                        headers=GUIDE_HEADERS,
                        json={
                            "model": model,
                            "messages": messages,
                            "max_tokens": max_tokens,
                            "temperature": temperature
                        }
                    )
                    llm_resp.raise_for_status()
                    llm_data = llm_resp.json()

                logger.info(f"[Gateway] LIGHTWEIGHT MODE: Success, returning direct response")
                return llm_data

            except Exception as e:
                logger.error(f"[Gateway] LIGHTWEIGHT MODE: Error: {e}")
                raise HTTPException(500, f"LLM call failed: {str(e)}")

    # Extract request parameters
    mode = payload.get("mode", "chat")
    user_msg = payload.get("messages", [])[-1]["content"] if payload.get("messages") else ""
    current_repo = payload.get("repo")
    profile_id = _profile_key(payload.get("user_id") or x_user_id)
    history_subject = last_user_subject(payload.get("messages", []) or [])

    # Compute session_id and trace_id early
    # Use client-provided trace_id if available (for SSE coordination), otherwise generate
    trace_id = payload.get("trace_id") or uuid.uuid4().hex[:16]
    session_id = str(payload.get("session_id") or payload.get("session") or profile_id or trace_id)

    # ========================================
    # MODEL PROVIDER SELECTION
    # ========================================
    model_provider = payload.get("model_provider", "panda")

    # Select the right flow based on model_provider toggle
    if model_provider == "claude":
        unified_flow = get_claude_flow()
        if unified_flow is None:
            logger.warning("[Gateway] Claude requested but unavailable (no API key or anthropic not installed)")
            unified_flow = get_unified_flow()  # Fall back to Panda
            model_provider = "panda"
        else:
            logger.info(f"[Gateway] Using Claude model provider (trace={trace_id})")
    else:
        unified_flow = get_unified_flow()

    if is_unified_flow_enabled() and unified_flow:
        logger.info(f"[UnifiedRouting] Using unified 8-phase flow (trace={trace_id})")

        # NOTE: Intent classification removed - Phase 0 extracts user_purpose via LLM
        # The unified_flow will run Phase 0 which generates natural language user_purpose

        try:
            # Execute unified flow
            start_time = time.time()
            unified_result = await unified_flow.handle_request(
                user_query=user_msg,
                session_id=session_id,
                mode=mode,
                intent=None,  # Phase 0 will extract user_purpose, not rigid intent
                trace_id=trace_id,
                turn_number=None,  # Let UnifiedFlow generate atomically
                repo=current_repo,  # Pass repo for code mode context gathering
                user_id=profile_id  # Pass user_id for per-user paths
            )
            elapsed_ms = (time.time() - start_time) * 1000

            response_text = unified_result.get("response", "")
            turn_dir = unified_result.get("turn_dir")
            turn_number = unified_result.get("turn_number", 0)
            validation_passed = unified_result.get("validation_passed", True)

            # Build trace for logging
            trace = build_trace_envelope(
                trace_id=trace_id,
                session_id=session_id,
                mode=mode,
                user_msg=user_msg,
                profile=profile_id,
                repo=current_repo,
                policy=None
            )
            trace["final"] = response_text
            trace["unified_flow"] = True
            trace["unified_turn_dir"] = str(turn_dir) if turn_dir else None
            trace["unified_turn_number"] = turn_number
            trace["validation_passed"] = validation_passed
            trace["elapsed_ms"] = elapsed_ms
            append_trace(trace)

            logger.info(f"[UnifiedRouting] Unified flow complete (turn={turn_number}, elapsed={elapsed_ms:.0f}ms, validated={validation_passed})")

            # Emit thinking event (progress indicator)
            await emit_thinking_event(ThinkingEvent(
                trace_id=trace_id,
                stage="response_complete",
                status="completed",
                confidence=1.0 if validation_passed else 0.7,
                duration_ms=int(elapsed_ms),
                details={"unified_flow": True, "turn_number": turn_number, "validation_passed": validation_passed},
                reasoning="Unified 8-phase flow completed",
                timestamp=time.time()
            ))

            # Emit complete event WITH message for SSE clients
            await emit_thinking_event(ThinkingEvent(
                trace_id=trace_id,
                stage="complete",
                status="completed",
                confidence=1.0 if validation_passed else 0.7,
                duration_ms=int(elapsed_ms),
                details={"unified_flow": True, "turn_number": turn_number},
                reasoning="Response ready",
                timestamp=time.time(),
                message=response_text
            ))
            logger.info(f"[UnifiedRouting] Emitted complete event for SSE (trace={trace_id}, msg_len={len(response_text)})")

            return {
                "id": trace_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": GUIDE_MODEL_ID,
                "model_provider": model_provider,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop"
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "turn_number": turn_number,
                "validation_passed": validation_passed
            }

        except Exception as e:
            logger.exception(f"[UnifiedRouting] Error in unified flow: {e}")
            # Return error response
            return {
                "id": trace_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": GUIDE_MODEL_ID,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": f"I encountered an error processing your request. Please try again. (Error: {type(e).__name__})"},
                        "finish_reason": "stop"
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "error": str(e)
            }

    # If we reach here, no flow handler is available
    logger.error(f"[Gateway] No flow handler available - unified_flow_enabled={is_unified_flow_enabled()}")
    return {
        "id": trace_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": GUIDE_MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "No flow handler available. Please ensure UNIFIED_FLOW_ENABLED=true in your environment."
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        },
        "error": "No flow handler available"
    }


@router.get("/v1/model_providers")
async def list_model_providers():
    """Return available model providers for UI toggle."""
    providers = [{"id": "panda", "label": "Panda (Local)", "available": True}]
    claude_flow = get_claude_flow()
    providers.append({
        "id": "claude",
        "label": "Claude (API)",
        "available": claude_flow is not None,
    })
    return {"providers": providers}
