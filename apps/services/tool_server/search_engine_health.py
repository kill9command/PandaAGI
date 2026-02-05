"""
orchestrator/search_engine_health.py

Per-engine health tracking to avoid wasting time on blocked search engines.

Tracks which engines are currently blocked/rate-limited and provides smart
engine selection based on health scores.

Created: 2025-11-19
Part of Phase 1 blocker mitigation improvements.
"""
import time
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class EngineHealth:
    """Health status for a single search engine"""
    engine_name: str
    consecutive_failures: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    total_requests: int = 0
    total_successes: int = 0
    total_failures: int = 0
    cooldown_until: Optional[float] = None  # Unix timestamp when engine can be retried


class SearchEngineHealthTracker:
    """
    Tracks health of multiple search engines and provides smart engine selection.

    Features:
    - Per-engine failure tracking
    - Automatic cooldown periods after blocks
    - Success rate monitoring
    - Smart engine selection (healthiest first)
    """

    def __init__(
        self,
        base_cooldown_seconds: float = 60.0,
        max_cooldown_seconds: float = 600.0
    ):
        """
        Args:
            base_cooldown_seconds: Initial cooldown after first failure (default 60s)
            max_cooldown_seconds: Maximum cooldown period (default 10 minutes)
        """
        self.engines: Dict[str, EngineHealth] = {}
        self.base_cooldown = base_cooldown_seconds
        self.max_cooldown = max_cooldown_seconds
        logger.info(
            f"[EngineHealth] Initialized with base_cooldown={base_cooldown_seconds}s, "
            f"max_cooldown={max_cooldown_seconds}s"
        )

    def _get_or_create_engine(self, engine_name: str) -> EngineHealth:
        """Get or create health record for an engine"""
        if engine_name not in self.engines:
            self.engines[engine_name] = EngineHealth(engine_name=engine_name)
            logger.info(f"[EngineHealth] Tracking new engine: {engine_name}")
        return self.engines[engine_name]

    def is_healthy(self, engine_name: str) -> bool:
        """
        Check if an engine is currently healthy (not in cooldown).

        Args:
            engine_name: Name of search engine (e.g., "DuckDuckGo", "Google")

        Returns:
            True if engine can be used, False if in cooldown
        """
        engine = self._get_or_create_engine(engine_name)

        # No cooldown set - engine is healthy
        if engine.cooldown_until is None:
            return True

        # Check if cooldown has expired
        now = time.time()
        if now >= engine.cooldown_until:
            logger.info(
                f"[EngineHealth] {engine_name} cooldown expired, marking healthy"
            )
            engine.cooldown_until = None
            engine.consecutive_failures = 0
            return True

        # Still in cooldown
        remaining = engine.cooldown_until - now
        logger.debug(
            f"[EngineHealth] {engine_name} still in cooldown ({remaining:.0f}s remaining)"
        )
        return False

    def report_success(self, engine_name: str) -> None:
        """
        Report successful search on an engine.

        Clears cooldown and resets failure count.
        """
        engine = self._get_or_create_engine(engine_name)
        engine.total_requests += 1
        engine.total_successes += 1
        engine.last_success_time = time.time()

        # Clear failures and cooldown
        if engine.consecutive_failures > 0 or engine.cooldown_until is not None:
            logger.info(
                f"[EngineHealth] {engine_name} successful! "
                f"Clearing {engine.consecutive_failures} consecutive failures"
            )
        engine.consecutive_failures = 0
        engine.cooldown_until = None

    def report_failure(self, engine_name: str, failure_type: str = "rate_limit") -> None:
        """
        Report failed search on an engine (rate limit or other block).

        Implements exponential backoff cooldown.

        Args:
            engine_name: Name of search engine
            failure_type: Type of failure ("rate_limit", "captcha", etc.)
        """
        engine = self._get_or_create_engine(engine_name)
        engine.total_requests += 1
        engine.total_failures += 1
        engine.last_failure_time = time.time()
        engine.consecutive_failures += 1

        # Calculate exponential backoff cooldown
        # 1st failure: 60s, 2nd: 120s, 3rd: 240s, 4th: 480s, max: 600s
        cooldown_duration = min(
            self.base_cooldown * (2 ** (engine.consecutive_failures - 1)),
            self.max_cooldown
        )

        engine.cooldown_until = time.time() + cooldown_duration

        success_rate = (
            (engine.total_successes / engine.total_requests * 100)
            if engine.total_requests > 0 else 0
        )

        logger.warning(
            f"[EngineHealth] {engine_name} {failure_type}! "
            f"Consecutive failures: {engine.consecutive_failures}, "
            f"Cooldown: {cooldown_duration:.0f}s, "
            f"Success rate: {success_rate:.1f}% ({engine.total_successes}/{engine.total_requests})"
        )

    def get_healthy_engines(self, engine_names: List[str]) -> List[str]:
        """
        Filter list of engines to only healthy ones, sorted by health score.

        Args:
            engine_names: List of engine names to consider

        Returns:
            List of healthy engine names, sorted best to worst
        """
        healthy = []
        for name in engine_names:
            if self.is_healthy(name):
                healthy.append(name)

        # Sort by success rate (best first)
        healthy.sort(key=lambda name: self._get_success_rate(name), reverse=True)

        if healthy:
            logger.info(
                f"[EngineHealth] Healthy engines ({len(healthy)}/{len(engine_names)}): "
                f"{', '.join(healthy)}"
            )
        else:
            logger.warning(
                f"[EngineHealth] No healthy engines available! All {len(engine_names)} are in cooldown"
            )

        return healthy

    def _get_success_rate(self, engine_name: str) -> float:
        """Get success rate for an engine (0.0 to 1.0)"""
        engine = self._get_or_create_engine(engine_name)
        if engine.total_requests == 0:
            return 1.0  # No data - assume healthy
        return engine.total_successes / engine.total_requests

    def get_stats(self) -> Dict:
        """Get health statistics for all tracked engines"""
        stats = {}
        for name, engine in self.engines.items():
            stats[name] = {
                "total_requests": engine.total_requests,
                "total_successes": engine.total_successes,
                "total_failures": engine.total_failures,
                "consecutive_failures": engine.consecutive_failures,
                "success_rate": self._get_success_rate(name),
                "is_healthy": self.is_healthy(name),
                "cooldown_remaining": (
                    engine.cooldown_until - time.time()
                    if engine.cooldown_until and engine.cooldown_until > time.time()
                    else 0
                )
            }
        return stats


# Global singleton
_global_health_tracker: Optional[SearchEngineHealthTracker] = None


def get_engine_health_tracker() -> SearchEngineHealthTracker:
    """Get the global search engine health tracker instance"""
    global _global_health_tracker
    if _global_health_tracker is None:
        _global_health_tracker = SearchEngineHealthTracker(
            base_cooldown_seconds=60.0,   # 1 minute base cooldown
            max_cooldown_seconds=600.0     # 10 minutes max cooldown
        )
    return _global_health_tracker
