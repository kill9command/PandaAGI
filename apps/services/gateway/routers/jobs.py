"""
Job Management Router

Provides endpoints for async job management to avoid 524 timeout errors.

Endpoints:
    POST /jobs/start - Start a new async job
    GET /jobs/active - List active jobs
    GET /jobs/{job_id} - Get job status
    POST /jobs/{job_id}/cancel - Cancel a job
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from apps.services.gateway.services.jobs import (
    JOBS,
    create_job,
    get_job,
    cancel_job,
    list_active_jobs,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/start")
async def jobs_start(payload: dict) -> Dict[str, Any]:
    """
    Start a new async job.

    Creates a job that runs in the background and returns immediately
    with a job_id for status polling.

    Args:
        payload: Chat request payload to execute

    Returns:
        Job ID and initial status
    """
    job_id = create_job(payload)
    logger.info(f"[Jobs] Started job {job_id}")
    return {"job_id": job_id, "status": "queued"}


@router.get("/active")
async def jobs_list_active_endpoint() -> Dict[str, Any]:
    """
    List all active (queued or running) jobs.

    Returns:
        List of active job info and count
    """
    active = list_active_jobs()
    return {"active_jobs": active, "count": len(active)}


@router.get("/{job_id}")
async def jobs_get(job_id: str) -> Dict[str, Any]:
    """
    Get job status and result.

    Args:
        job_id: Job identifier

    Returns:
        Job status, result, or error

    Raises:
        HTTPException 404 if job not found
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.post("/{job_id}/cancel")
async def jobs_cancel(job_id: str) -> Dict[str, Any]:
    """
    Cancel a running job.

    Marks the job as cancelled and signals the flow to stop
    at the next checkpoint.

    Args:
        job_id: Job identifier

    Returns:
        Cancellation result

    Raises:
        HTTPException 404 if job not found
    """
    result = cancel_job(job_id)
    if not result.get("ok") and result.get("message") == "Job not found":
        raise HTTPException(404, "job not found")
    return result
