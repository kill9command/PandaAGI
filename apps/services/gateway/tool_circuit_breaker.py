"""
Tool Circuit Breaker

Prevents repeated calls to failing tools using circuit breaker pattern.
Tracks tool failures and temporarily blocks tools with high failure rates.

Circuit States:
- CLOSED: Normal operation, requests pass through
- OPEN: Too many failures, requests blocked
- HALF_OPEN: Testing if tool has recovered

Thresholds:
- Failure threshold: 3 failures within window
- Recovery timeout: 60 seconds
- Success threshold to close: 2 consecutive successes
"""

import time
import logging
from collections import defaultdict, deque
from enum import Enum
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


class ToolCircuitBreaker:
    """
    Circuit breaker for tool execution.

    Tracks failures per tool and temporarily blocks tools with high failure rates.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        window_seconds: int = 300,
        recovery_timeout: int = 60,
        success_threshold: int = 2
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            window_seconds: Time window for counting failures (seconds)
            recovery_timeout: Time to wait before testing recovery (seconds)
            success_threshold: Consecutive successes needed to close circuit
        """
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        # Track state per tool
        self.states: Dict[str, CircuitState] = defaultdict(lambda: CircuitState.CLOSED)
        self.failure_times: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
        self.open_times: Dict[str, float] = {}
        self.consecutive_successes: Dict[str, int] = defaultdict(int)

    def check_allowed(self, tool_name: str) -> Tuple[bool, Optional[str]]:
        """
        Check if tool execution is allowed.

        Args:
            tool_name: Name of the tool to check

        Returns:
            (allowed, reason) - allowed=True if call should proceed, reason explains why if blocked
        """
        state = self.states[tool_name]

        if state == CircuitState.CLOSED:
            # Normal operation
            return True, None

        elif state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            open_time = self.open_times.get(tool_name, 0)
            if time.time() - open_time >= self.recovery_timeout:
                # Transition to HALF_OPEN to test recovery
                logger.info(f"[Circuit Breaker] {tool_name}: OPEN → HALF_OPEN (recovery timeout reached)")
                self.states[tool_name] = CircuitState.HALF_OPEN
                return True, None
            else:
                # Still in timeout period
                remaining = int(self.recovery_timeout - (time.time() - open_time))
                reason = f"Circuit open: {tool_name} failed {self.failure_threshold}+ times. Retry in {remaining}s."
                return False, reason

        elif state == CircuitState.HALF_OPEN:
            # Allow one test request
            return True, None

        return True, None

    def record_success(self, tool_name: str):
        """
        Record successful tool execution.

        Args:
            tool_name: Name of the tool that succeeded
        """
        state = self.states[tool_name]

        if state == CircuitState.CLOSED:
            # Reset consecutive successes (not needed in closed state)
            self.consecutive_successes[tool_name] = 0

        elif state == CircuitState.HALF_OPEN:
            # Track consecutive successes
            self.consecutive_successes[tool_name] += 1
            logger.info(f"[Circuit Breaker] {tool_name}: Success in HALF_OPEN ({self.consecutive_successes[tool_name]}/{self.success_threshold})")

            if self.consecutive_successes[tool_name] >= self.success_threshold:
                # Transition back to CLOSED
                logger.info(f"[Circuit Breaker] {tool_name}: HALF_OPEN → CLOSED ({self.success_threshold} consecutive successes)")
                self.states[tool_name] = CircuitState.CLOSED
                self.consecutive_successes[tool_name] = 0
                self.failure_times[tool_name].clear()

    def record_failure(self, tool_name: str, error: str):
        """
        Record failed tool execution.

        Args:
            tool_name: Name of the tool that failed
            error: Error message or reason for failure
        """
        now = time.time()
        state = self.states[tool_name]

        # Add failure to history
        self.failure_times[tool_name].append(now)

        # Count recent failures within window
        cutoff = now - self.window_seconds
        recent_failures = sum(1 for t in self.failure_times[tool_name] if t >= cutoff)

        logger.warning(f"[Circuit Breaker] {tool_name}: Failure recorded ({recent_failures}/{self.failure_threshold}): {error}")

        if state == CircuitState.CLOSED:
            if recent_failures >= self.failure_threshold:
                # Transition to OPEN
                logger.error(f"[Circuit Breaker] {tool_name}: CLOSED → OPEN ({recent_failures} failures in {self.window_seconds}s)")
                self.states[tool_name] = CircuitState.OPEN
                self.open_times[tool_name] = now

        elif state == CircuitState.HALF_OPEN:
            # Transition back to OPEN
            logger.error(f"[Circuit Breaker] {tool_name}: HALF_OPEN → OPEN (test request failed)")
            self.states[tool_name] = CircuitState.OPEN
            self.open_times[tool_name] = now
            self.consecutive_successes[tool_name] = 0

    def get_status(self, tool_name: str) -> Dict:
        """
        Get current status of circuit breaker for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Status dictionary with state, failure count, etc.
        """
        state = self.states[tool_name]
        now = time.time()
        cutoff = now - self.window_seconds
        recent_failures = sum(1 for t in self.failure_times[tool_name] if t >= cutoff)

        status = {
            "state": state.value,
            "recent_failures": recent_failures,
            "failure_threshold": self.failure_threshold,
            "window_seconds": self.window_seconds
        }

        if state == CircuitState.OPEN:
            open_time = self.open_times.get(tool_name, 0)
            remaining = max(0, int(self.recovery_timeout - (now - open_time)))
            status["retry_in_seconds"] = remaining

        elif state == CircuitState.HALF_OPEN:
            status["consecutive_successes"] = self.consecutive_successes[tool_name]
            status["success_threshold"] = self.success_threshold

        return status

    def reset(self, tool_name: str):
        """
        Manually reset circuit breaker for a tool.

        Args:
            tool_name: Name of the tool to reset
        """
        logger.info(f"[Circuit Breaker] {tool_name}: Manual reset")
        self.states[tool_name] = CircuitState.CLOSED
        self.failure_times[tool_name].clear()
        self.consecutive_successes[tool_name] = 0
        if tool_name in self.open_times:
            del self.open_times[tool_name]
