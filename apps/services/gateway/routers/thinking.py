"""
Thinking Visualization Router

Provides SSE endpoints for real-time thinking visualization.

Endpoints:
    GET /v1/thinking/{trace_id} - SSE stream of thinking events
    GET /v1/response/{trace_id} - Poll for final response
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from apps.services.gateway.services.thinking import (
    ThinkingEvent,
    ActionEvent,
    THINKING_QUEUES,
    RESPONSE_STORE,
    cleanup_thinking_queues,
    get_thinking_queue,
    has_thinking_queue,
    get_response,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["thinking"])


@router.get("/v1/thinking/{trace_id}")
async def stream_thinking_events(trace_id: str):
    """
    Stream thinking events for a trace via SSE.

    This endpoint provides real-time visualization of the thinking
    process as a query progresses through the pipeline stages.

    Args:
        trace_id: Unique trace identifier

    Returns:
        SSE stream of ThinkingEvent objects
    """
    logger.info(f"[Thinking SSE] Endpoint hit for trace_id={trace_id}")

    async def event_generator():
        """Generate SSE events from the thinking queue."""
        logger.info(f"[Thinking SSE] Starting event generator for trace {trace_id}")

        # Cleanup old queues periodically
        await cleanup_thinking_queues()

        # Check if trace exists
        if not has_thinking_queue(trace_id):
            logger.info(f"[Thinking SSE] No queue for {trace_id}, waiting...")
            # Check if response is already available (completed trace)
            response = await get_response(trace_id)
            if response:
                # Trace completed, send complete event
                yield {
                    "event": "thinking",
                    "data": json.dumps({
                        "trace_id": trace_id,
                        "stage": "complete",
                        "status": "completed",
                        "confidence": 1.0,
                        "duration_ms": 0,
                        "details": {},
                        "reasoning": "Response retrieved from store",
                        "timestamp": time.time(),
                        "message": response,
                    }),
                }
                return
            else:
                # No queue and no response - trace not found or not started
                yield {
                    "event": "thinking",
                    "data": json.dumps({
                        "trace_id": trace_id,
                        "stage": "pending",
                        "status": "pending",
                        "confidence": 0.0,
                        "duration_ms": 0,
                        "details": {},
                        "reasoning": "Waiting for trace to start",
                        "timestamp": time.time(),
                    }),
                }
                # Wait for queue to be created
                for _ in range(30):  # Wait up to 30 seconds
                    await asyncio.sleep(1)
                    if has_thinking_queue(trace_id):
                        break
                else:
                    # Timeout - check response store one more time
                    response = await get_response(trace_id)
                    if response:
                        yield {
                            "event": "thinking",
                            "data": json.dumps({
                                "trace_id": trace_id,
                                "stage": "complete",
                                "status": "completed",
                                "confidence": 1.0,
                                "duration_ms": 0,
                                "details": {},
                                "reasoning": "Response retrieved from store",
                                "timestamp": time.time(),
                                "message": response,
                            }),
                        }
                    return

        # Stream events from queue
        logger.info(f"[Thinking SSE] Getting queue for {trace_id}")
        queue = get_thinking_queue(trace_id)
        if not queue:
            logger.warning(f"[Thinking SSE] Queue not found for {trace_id}, returning")
            return
        logger.info(f"[Thinking SSE] Starting to stream events for {trace_id}, queue size: {queue.qsize()}")

        while True:
            try:
                # Wait for next event with timeout
                event = await asyncio.wait_for(queue.get(), timeout=60.0)

                if isinstance(event, ThinkingEvent):
                    yield {
                        "event": "thinking",
                        "data": json.dumps(event.to_dict()),
                    }

                    # If complete, exit
                    if event.stage == "complete":
                        logger.info(f"[Thinking SSE] Trace {trace_id} complete")
                        return

                elif isinstance(event, ActionEvent):
                    yield {
                        "event": "action",
                        "data": json.dumps(event.to_dict()),
                    }

            except asyncio.TimeoutError:
                # Send keepalive
                yield {
                    "event": "keepalive",
                    "data": json.dumps({"trace_id": trace_id, "timestamp": time.time()}),
                }

            except Exception as e:
                logger.error(f"[Thinking SSE] Error streaming events: {e}")
                yield {
                    "event": "error",
                    "data": json.dumps({"error": str(e), "trace_id": trace_id}),
                }
                return

    return EventSourceResponse(event_generator())


@router.get("/v1/response/{trace_id}")
async def get_response_endpoint(trace_id: str) -> Dict[str, Any]:
    """
    Poll for final response of a trace.

    This is a fallback for clients that don't support SSE.
    Returns the final response if available, or status if still processing.

    Args:
        trace_id: Unique trace identifier

    Returns:
        Response dict with status and optional message
    """
    # Check response store first
    response = await get_response(trace_id)
    if response:
        return {
            "status": "complete",
            "trace_id": trace_id,
            "message": response,
        }

    # Check if queue exists (still processing)
    if has_thinking_queue(trace_id):
        return {
            "status": "processing",
            "trace_id": trace_id,
            "message": None,
        }

    # Not found
    return {
        "status": "not_found",
        "trace_id": trace_id,
        "message": None,
    }
