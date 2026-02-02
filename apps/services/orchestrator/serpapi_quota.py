"""
orchestrator/serpapi_quota.py

⚠️ DEPRECATED (2025-11-20): This module is deprecated and will be removed.
SerpAPI is no longer used - replaced by direct browser search via Web Vision MCP.

Old approach: Paid SerpAPI for search results (monthly quota, API costs).
New approach: Direct browser navigation (free, no API, no rate limits).

Simple quota tracker for SerpAPI usage.

- Persists remaining monthly quota to panda_system_docs/serpapi/quota.json
- Emits threshold notifications into panda_system_docs/serpapi/notifications.log
- Configurable via environment:
    SERPAPI_MONTHLY_QUOTA (default: 250)
    SERPAPI_NOTIFY_THRESHOLDS (comma-separated, default: "50,25,10,5,4,3,2,1")

Created: 2025-11-15
Deprecated: 2025-11-20 (SerpAPI replaced by Web Vision MCP)
"""
from __future__ import annotations
import os
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

QUOTA_PATH = Path("panda_system_docs/serpapi/quota.json")
NOTIFY_LOG = Path("panda_system_docs/serpapi/notifications.log")
DEFAULT_THRESHOLDS = [50, 25, 10, 5, 4, 3, 2, 1]


def _ensure_parent():
    QUOTA_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTIFY_LOG.parent.mkdir(parents=True, exist_ok=True)


def _load() -> Dict[str, Any]:
    _ensure_parent()
    if not QUOTA_PATH.exists():
        init_quota = int(os.environ.get("SERPAPI_MONTHLY_QUOTA", "250"))
        thresholds = _parse_thresholds(os.environ.get("SERPAPI_NOTIFY_THRESHOLDS"))
        data = {
            "remaining": init_quota,
            "monthly_quota": init_quota,
            "last_reset": datetime.now(timezone.utc).isoformat(),
            "last_notified_threshold": None,
            "thresholds": thresholds,
        }
        QUOTA_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
    try:
        return json.loads(QUOTA_PATH.read_text(encoding="utf-8"))
    except Exception:
        # If index corrupt, reset to defaults
        init_quota = int(os.environ.get("SERPAPI_MONTHLY_QUOTA", "250"))
        data = {
            "remaining": init_quota,
            "monthly_quota": init_quota,
            "last_reset": datetime.now(timezone.utc).isoformat(),
            "last_notified_threshold": None,
            "thresholds": DEFAULT_THRESHOLDS,
        }
        QUOTA_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data


def _write(data: Dict[str, Any]) -> None:
    _ensure_parent()
    QUOTA_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _parse_thresholds(envval: Optional[str]) -> List[int]:
    if not envval:
        return DEFAULT_THRESHOLDS
    parts = [p.strip() for p in envval.split(",") if p.strip()]
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except Exception:
            continue
    # sort descending for predictable behavior
    out_sorted = sorted(set(out), reverse=True)
    return out_sorted if out_sorted else DEFAULT_THRESHOLDS


def get_remaining() -> int:
    data = _load()
    return int(data.get("remaining", 0))


def consume(n: int = 1) -> Dict[str, Any]:
    """
    Consume `n` units from the quota.

    Returns:
      {"ok": bool, "remaining": int, "notify": { "threshold": int, "remaining": int }|None, "error": str|None}
    """
    data = _load()
    remaining = int(data.get("remaining", 0))
    if remaining < n:
        return {"ok": False, "remaining": remaining, "notify": None, "error": "insufficient_quota"}

    remaining -= n
    data["remaining"] = remaining

    # determine thresholds and whether to notify
    thresholds: List[int] = data.get("thresholds", DEFAULT_THRESHOLDS)
    last_notified = data.get("last_notified_threshold")

    # find the highest threshold that is >= remaining and lower than last_notified (if any)
    notify_threshold = None
    for t in sorted(thresholds, reverse=True):
        if remaining <= t:
            if last_notified is None or t < last_notified:
                notify_threshold = t
                break

    # update last_notified if applicable
    if notify_threshold is not None:
        data["last_notified_threshold"] = notify_threshold

    # persist
    _write(data)

    # write notification if needed (append to log)
    notify = None
    if notify_threshold is not None:
        ts = datetime.now(timezone.utc).isoformat()
        msg = f"{ts} - SerpAPI quota threshold reached: {notify_threshold} remaining={remaining}\n"
        with NOTIFY_LOG.open("a", encoding="utf-8") as f:
            f.write(msg)
        notify = {"threshold": notify_threshold, "remaining": remaining}

    return {"ok": True, "remaining": remaining, "notify": notify, "error": None}


def set_remaining(value: int) -> None:
    data = _load()
    data["remaining"] = int(value)
    _write(data)
