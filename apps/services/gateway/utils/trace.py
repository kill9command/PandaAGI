"""
Trace Management Utilities

Provides trace envelope construction and logging for request tracing.
"""

import datetime
import json
import logging
from typing import Any, Dict, Optional

from apps.services.gateway.config import TRANSCRIPTS_DIR, RUNTIME_POLICY

logger = logging.getLogger("uvicorn.error")


def build_trace_envelope(
    trace_id: str,
    session_id: str,
    mode: str,
    user_msg: str,
    profile: str,
    repo: Optional[str],
    policy: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build a trace envelope for logging.

    Args:
        trace_id: Unique trace identifier
        session_id: Session identifier
        mode: Execution mode (chat/code/plan)
        user_msg: User message text
        profile: Profile identifier
        repo: Repository path (optional)
        policy: Runtime policy dict (optional)

    Returns:
        Trace dictionary with standard structure
    """
    if policy is None:
        policy = {
            "chat_allow_file_create": RUNTIME_POLICY.get("chat_allow_file_create", False),
            "write_confirm": RUNTIME_POLICY.get("write_confirm", True),
            "tool_enables": RUNTIME_POLICY.get("tool_enables", {}),
        }

    return {
        "id": trace_id,
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "repo": repo,
        "user": user_msg,
        "profile": profile,
        "session_id": session_id,
        "policy": policy,
        "guide_calls": [],
        "coordinator_calls": [],
        "tools_executed": [],
        "tickets": [],
        "bundles": [],
        "capsules": [],
        "policy_notes": [],
        "deferred": [],
        "injected_context": [],
        "strategic_decisions": [],
        "final": None,
        "dur_ms": None,
        "error": None,
    }


def append_trace(trace: Dict[str, Any]) -> None:
    """
    Append trace to daily transcript log and verbose log.

    Args:
        trace: Trace dictionary to append
    """
    try:
        trace_id = trace.get("id", "unknown")
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        day_file = TRANSCRIPTS_DIR / f"{day}.jsonl"

        # Create day file if it doesn't exist
        if not day_file.exists():
            day_file.write_text("", encoding="utf-8")

        # Append to daily log (compact format)
        with day_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(trace) + "\n")

        # Write verbose log (full format)
        vdir = TRANSCRIPTS_DIR / "verbose" / day
        vdir.mkdir(parents=True, exist_ok=True)
        with (vdir / f"{trace_id}.json").open("w", encoding="utf-8") as vf:
            json.dump(trace, vf, indent=2)

    except Exception as e:
        logger.warning(f"[Trace] Failed to append trace {trace.get('id')}: {e}")
