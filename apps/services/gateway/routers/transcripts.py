"""
Transcripts Router

Provides endpoints for turn history and trace management.
These are the internal endpoints that read from local transcript files.

Endpoints:
    GET /transcripts - List recent transcripts
    GET /transcripts/{trace_id} - Get specific transcript
    GET /transcripts/{trace_id}/verbose - Get verbose transcript
    POST /transcripts/delete - Delete transcripts
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from apps.services.gateway.config import TRANSCRIPTS_DIR

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


def _list_transcript_files(days: int = 7) -> List[Path]:
    """List transcript files from recent days."""
    import datetime

    files = []
    today = datetime.datetime.now(datetime.timezone.utc)

    for i in range(days):
        day = today - datetime.timedelta(days=i)
        day_str = day.strftime("%Y%m%d")
        day_file = TRANSCRIPTS_DIR / f"{day_str}.jsonl"
        if day_file.exists():
            files.append(day_file)

    return files


def _load_transcripts(files: List[Path], limit: int = 50) -> List[Dict[str, Any]]:
    """Load transcripts from files."""
    transcripts = []

    for file_path in files:
        if len(transcripts) >= limit:
            break

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if len(transcripts) >= limit:
                        break
                    try:
                        trace = json.loads(line.strip())
                        transcripts.append(trace)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"[Transcripts] Failed to read {file_path}: {e}")

    # Sort by timestamp (most recent first)
    transcripts.sort(key=lambda t: t.get("ts", ""), reverse=True)

    return transcripts[:limit]


@router.get("")
async def list_transcripts(
    limit: int = Query(default=50, ge=1, le=200, description="Number of transcripts"),
    days: int = Query(default=7, ge=1, le=30, description="Days to search"),
) -> Dict[str, Any]:
    """
    List recent transcripts.

    Args:
        limit: Maximum number of transcripts to return
        days: Number of days to search back

    Returns:
        List of transcript summaries
    """
    files = _list_transcript_files(days)
    transcripts = _load_transcripts(files, limit)

    # Return summaries (not full traces)
    summaries = []
    for trace in transcripts:
        summaries.append({
            "id": trace.get("id"),
            "ts": trace.get("ts"),
            "mode": trace.get("mode"),
            "user": trace.get("user", "")[:100] + "..." if len(trace.get("user", "")) > 100 else trace.get("user", ""),
            "profile": trace.get("profile"),
            "session_id": trace.get("session_id"),
            "dur_ms": trace.get("dur_ms"),
            "error": trace.get("error") is not None,
        })

    return {
        "transcripts": summaries,
        "count": len(summaries),
        "limit": limit,
        "days": days,
    }


@router.get("/{trace_id}")
async def get_transcript(trace_id: str) -> Dict[str, Any]:
    """
    Get a specific transcript by trace ID.

    Args:
        trace_id: Trace identifier

    Returns:
        Full transcript data

    Raises:
        HTTPException 404 if not found
    """
    # Search in verbose directory first (has full data)
    import datetime

    # Try recent days
    today = datetime.datetime.now(datetime.timezone.utc)
    for i in range(14):  # Search up to 2 weeks back
        day = today - datetime.timedelta(days=i)
        day_str = day.strftime("%Y%m%d")
        verbose_file = TRANSCRIPTS_DIR / "verbose" / day_str / f"{trace_id}.json"

        if verbose_file.exists():
            try:
                with open(verbose_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[Transcripts] Failed to read {verbose_file}: {e}")

    # Fallback: search in daily JSONL files
    files = _list_transcript_files(14)
    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        trace = json.loads(line.strip())
                        if trace.get("id") == trace_id:
                            return trace
                    except json.JSONDecodeError:
                        continue
        except Exception:
            continue

    raise HTTPException(404, f"Transcript {trace_id} not found")


@router.get("/{trace_id}/verbose")
async def get_transcript_verbose(trace_id: str) -> Dict[str, Any]:
    """
    Get verbose transcript with full details.

    Args:
        trace_id: Trace identifier

    Returns:
        Full verbose transcript data

    Raises:
        HTTPException 404 if not found
    """
    import datetime

    today = datetime.datetime.now(datetime.timezone.utc)
    for i in range(14):
        day = today - datetime.timedelta(days=i)
        day_str = day.strftime("%Y%m%d")
        verbose_file = TRANSCRIPTS_DIR / "verbose" / day_str / f"{trace_id}.json"

        if verbose_file.exists():
            try:
                with open(verbose_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                raise HTTPException(500, f"Failed to read transcript: {e}")

    raise HTTPException(404, f"Verbose transcript {trace_id} not found")


@router.post("/delete")
async def delete_transcripts(
    trace_ids: Optional[List[str]] = None,
    before_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Delete transcripts.

    Args:
        trace_ids: List of specific trace IDs to delete
        before_date: Delete all transcripts before this date (YYYYMMDD)

    Returns:
        Deletion result with count
    """
    deleted = 0
    errors = []

    if trace_ids:
        # Delete specific traces from verbose directory
        import datetime

        today = datetime.datetime.now(datetime.timezone.utc)
        for trace_id in trace_ids:
            for i in range(30):
                day = today - datetime.timedelta(days=i)
                day_str = day.strftime("%Y%m%d")
                verbose_file = TRANSCRIPTS_DIR / "verbose" / day_str / f"{trace_id}.json"

                if verbose_file.exists():
                    try:
                        verbose_file.unlink()
                        deleted += 1
                        break
                    except Exception as e:
                        errors.append(f"Failed to delete {trace_id}: {e}")

    if before_date:
        # Delete all files before date
        try:
            import datetime

            cutoff = datetime.datetime.strptime(before_date, "%Y%m%d")

            # Delete daily files
            for file_path in TRANSCRIPTS_DIR.glob("*.jsonl"):
                try:
                    file_date = datetime.datetime.strptime(file_path.stem, "%Y%m%d")
                    if file_date < cutoff:
                        file_path.unlink()
                        deleted += 1
                except ValueError:
                    continue
                except Exception as e:
                    errors.append(f"Failed to delete {file_path}: {e}")

            # Delete verbose directories
            for dir_path in (TRANSCRIPTS_DIR / "verbose").glob("*"):
                if dir_path.is_dir():
                    try:
                        dir_date = datetime.datetime.strptime(dir_path.name, "%Y%m%d")
                        if dir_date < cutoff:
                            import shutil
                            shutil.rmtree(dir_path)
                            deleted += 1
                    except ValueError:
                        continue
                    except Exception as e:
                        errors.append(f"Failed to delete {dir_path}: {e}")

        except ValueError as e:
            errors.append(f"Invalid date format: {e}")

    return {
        "deleted": deleted,
        "errors": errors if errors else None,
    }
