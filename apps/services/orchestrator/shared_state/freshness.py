"""
Freshness heuristics for claim persistence.

The oracle keeps the implementation lightweight but tunable: we primarily scale
TTL based on confidence and allow downstream callers to ask whether a claim
should be refreshed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Union


def _coerce_datetime(value: Union[str, datetime, None]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    value = value.strip()
    try:
        if "T" in value or value.endswith("Z"):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(value)
    except Exception:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


@dataclass(frozen=True)
class FreshnessOracle:
    """
    Simple heuristics for claim TTL.

    These defaults can be overridden via constructor arguments.
    """

    high_conf_seconds: int = 48 * 3600
    medium_conf_seconds: int = 24 * 3600
    low_conf_seconds: int = 6 * 3600

    def suggest_ttl_seconds(self, confidence: str | None) -> int:
        if confidence == "high":
            return self.high_conf_seconds
        if confidence == "low":
            return self.low_conf_seconds
        return self.medium_conf_seconds

    def expiry_timestamp(
        self,
        *,
        last_verified: Union[str, datetime, None],
        ttl_seconds: int,
    ) -> datetime:
        start = _coerce_datetime(last_verified)
        return start + timedelta(seconds=max(0, ttl_seconds))

    def is_stale(
        self,
        *,
        last_verified: Union[str, datetime, None],
        ttl_seconds: int,
        now: Optional[datetime] = None,
    ) -> bool:
        now_dt = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
        expiry = self.expiry_timestamp(last_verified=last_verified, ttl_seconds=ttl_seconds)
        return now_dt >= expiry
