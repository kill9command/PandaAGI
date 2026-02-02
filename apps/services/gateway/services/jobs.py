"""
Job Management Service

Provides async job execution infrastructure for long-running operations.
Prevents 524 timeout errors by returning job IDs immediately and allowing
status polling.
"""

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

from apps.services.gateway.config import API_KEY, MODEL_TIMEOUT

logger = logging.getLogger("uvicorn.error")

# =============================================================================
# Job State Storage
# =============================================================================

# Active jobs: job_id -> job metadata
JOBS: Dict[str, Dict[str, Any]] = {}

# Cancelled job IDs (tracked separately for quick lookup)
CANCELLED_JOBS: set[str] = set()

# Cancelled trace IDs (for stopping in-flight traces)
CANCELLED_TRACES: set[str] = set()


# =============================================================================
# Cancellation Checks
# =============================================================================


def is_trace_cancelled(trace_id: str) -> bool:
    """Check if a trace has been cancelled."""
    return trace_id in CANCELLED_TRACES


def is_job_cancelled(job_id: str) -> bool:
    """Check if a job has been cancelled."""
    return job_id in CANCELLED_JOBS


# =============================================================================
# Job Execution
# =============================================================================


async def run_chat_job(job_id: str, payload: dict):
    """
    Execute a chat job by calling the local chat endpoint.

    Args:
        job_id: Unique job identifier
        payload: Chat request payload
    """
    JOBS[job_id]["status"] = "running"
    JOBS[job_id]["updated_at"] = time.time()

    # Call our own chat endpoint locally; include API key if enabled
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=MODEL_TIMEOUT) as client:
            resp = await client.post(
                "http://127.0.0.1:9000/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            body = None
            try:
                body = resp.json()
            except Exception:
                body = {
                    "status": resp.status_code,
                    "text": (resp.text[:1000] if resp.text else ""),
                }

            if resp.status_code >= 200 and resp.status_code < 300:
                JOBS[job_id]["status"] = "done"
                JOBS[job_id]["result"] = body
            else:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = body

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = {"message": str(e)}

    finally:
        JOBS[job_id]["updated_at"] = time.time()


# =============================================================================
# Job Management Functions
# =============================================================================


def create_job(payload: dict) -> str:
    """
    Create a new job and start it in the background.

    Args:
        payload: Chat request payload

    Returns:
        Job ID for status polling
    """
    job_id = uuid.uuid4().hex[:16]
    JOBS[job_id] = {
        "status": "queued",
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    asyncio.create_task(run_chat_job(job_id, payload))
    return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Get job status and result.

    Args:
        job_id: Job identifier

    Returns:
        Job dict or None if not found
    """
    job = JOBS.get(job_id)
    if not job:
        return None

    # Return shallow copy without large payloads
    return {
        k: v
        for k, v in job.items()
        if k in {"status", "result", "error", "created_at", "updated_at"}
    }


def cancel_job(job_id: str) -> Dict[str, Any]:
    """
    Cancel a running job.

    This marks the job as cancelled and signals the flow to stop
    at the next checkpoint. The flow will gracefully terminate and
    return a cancellation message.

    Args:
        job_id: Job identifier

    Returns:
        Result dict with success status
    """
    job = JOBS.get(job_id)
    if not job:
        return {"ok": False, "message": "Job not found", "job_id": job_id}

    if job["status"] not in ("queued", "running"):
        return {"ok": False, "message": f"Job already {job['status']}", "job_id": job_id}

    # Mark job as cancelled
    CANCELLED_JOBS.add(job_id)
    job["status"] = "cancelled"
    job["updated_at"] = time.time()

    # If job has an associated trace_id, mark that too
    trace_id = job.get("trace_id")
    if trace_id:
        CANCELLED_TRACES.add(trace_id)
        logger.info(f"[Jobs] Cancelled job {job_id} (trace={trace_id})")
    else:
        logger.info(f"[Jobs] Cancelled job {job_id}")

    return {"ok": True, "message": "Job cancelled", "job_id": job_id}


def cancel_trace(trace_id: str) -> Dict[str, Any]:
    """
    Cancel a running trace/research operation.

    This is used when the frontend wants to cancel an ongoing research
    operation that was started asynchronously (non-jobs mode).

    Args:
        trace_id: Trace identifier

    Returns:
        Result dict with success status
    """
    if not trace_id:
        return {"ok": False, "message": "trace_id required"}

    # Mark trace as cancelled
    CANCELLED_TRACES.add(trace_id)
    logger.info(f"[Trace] Cancelled trace {trace_id}")

    return {"ok": True, "message": "Trace cancelled", "trace_id": trace_id}


def list_active_jobs() -> List[Dict[str, Any]]:
    """
    List all active (queued or running) jobs.

    Returns:
        List of active job info dicts
    """
    active = []
    for job_id, job in JOBS.items():
        if job["status"] in ("queued", "running"):
            active.append(
                {
                    "job_id": job_id,
                    "status": job["status"],
                    "created_at": job["created_at"],
                    "updated_at": job["updated_at"],
                }
            )
    return active
