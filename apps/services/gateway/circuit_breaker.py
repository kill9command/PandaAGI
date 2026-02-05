"""
Circuit Breaker pattern for Panda Gateway.

Prevents cascading failures by "opening" circuits after repeated failures.
When a circuit is open, calls fail fast with a clear error instead of
repeatedly attempting an operation that's likely to fail.

This is especially important for LLM calls which can be slow and expensive.
"""

from collections import defaultdict, deque
from typing import Dict, Callable, Any, Optional, Deque
from dataclasses import dataclass
from enum import Enum
import time
import logging
import asyncio
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """States of a circuit breaker"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject calls immediately
    HALF_OPEN = "half_open"  # Testing if system recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 3  # Failures before opening circuit
    success_threshold: int = 2  # Successes to close from half-open
    timeout: int = 60  # Seconds before trying half-open
    window_size: int = 10  # Number of recent calls to track


class CircuitOpenError(Exception):
    """Raised when circuit is open"""
    def __init__(self, component: str, last_error: Optional[str] = None):
        self.component = component
        self.last_error = last_error
        super().__init__(
            f"Circuit open for {component}. "
            f"Last error: {last_error or 'unknown'}"
        )


class CircuitBreaker:
    """
    Circuit breaker for protecting against cascading failures.

    Usage:
        breaker = CircuitBreaker()

        # Synchronous
        result = breaker.call("my_component", my_function, arg1, arg2)

        # Async
        result = await breaker.call_async("my_component", my_async_function, arg1, arg2)
    """

    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig()

        # State tracking per component
        self.states: Dict[str, CircuitState] = defaultdict(lambda: CircuitState.CLOSED)
        self.failure_counts: Dict[str, int] = defaultdict(int)
        self.success_counts: Dict[str, int] = defaultdict(int)
        self.last_failure_time: Dict[str, float] = {}
        self.last_error: Dict[str, str] = {}

        # Track recent call results (for statistics)
        self.recent_calls: Dict[str, Deque[bool]] = defaultdict(
            lambda: deque(maxlen=self.config.window_size)
        )

    def call(self, component: str, fn: Callable, *args, **kwargs) -> Any:
        """
        Call function with circuit breaker protection (synchronous).

        Args:
            component: Component name (for tracking)
            fn: Function to call
            *args: Arguments to function
            **kwargs: Keyword arguments to function

        Returns:
            Function result

        Raises:
            CircuitOpenError: If circuit is open
            Exception: Original exception from function
        """
        # Check if circuit is open
        if self._should_reject(component):
            raise CircuitOpenError(component, self.last_error.get(component))

        try:
            # Execute function
            result = fn(*args, **kwargs)

            # Success! Record it
            self._record_success(component)

            return result

        except Exception as e:
            # Failure! Record it
            self._record_failure(component, str(e))

            # Re-raise original exception
            raise

    async def call_async(self, component: str, fn: Callable, *args, **kwargs) -> Any:
        """
        Call async function with circuit breaker protection.

        Args:
            component: Component name (for tracking)
            fn: Async function to call
            *args: Arguments to function
            **kwargs: Keyword arguments to function

        Returns:
            Function result

        Raises:
            CircuitOpenError: If circuit is open
            Exception: Original exception from function
        """
        # Check if circuit is open
        if self._should_reject(component):
            raise CircuitOpenError(component, self.last_error.get(component))

        try:
            # Execute async function
            result = await fn(*args, **kwargs)

            # Success! Record it
            self._record_success(component)

            return result

        except Exception as e:
            # Failure! Record it
            self._record_failure(component, str(e))

            # Re-raise original exception
            raise

    def _should_reject(self, component: str) -> bool:
        """Check if we should reject calls to this component"""
        state = self.states[component]

        if state == CircuitState.CLOSED:
            return False

        if state == CircuitState.OPEN:
            # Check if timeout has elapsed (try half-open)
            if self._timeout_elapsed(component):
                self._transition_to_half_open(component)
                return False
            return True

        if state == CircuitState.HALF_OPEN:
            # Allow calls in half-open state (testing recovery)
            return False

        return False

    def _timeout_elapsed(self, component: str) -> bool:
        """Check if timeout has elapsed since last failure"""
        last_failure = self.last_failure_time.get(component, 0)
        return time.time() - last_failure > self.config.timeout

    def _record_success(self, component: str):
        """Record successful call"""
        self.recent_calls[component].append(True)
        self.success_counts[component] += 1

        state = self.states[component]

        if state == CircuitState.HALF_OPEN:
            # In half-open, count successes
            if self.success_counts[component] >= self.config.success_threshold:
                self._transition_to_closed(component)
        elif state == CircuitState.CLOSED:
            # In closed state, reset failure count on success
            self.failure_counts[component] = 0

    def _record_failure(self, component: str, error: str):
        """Record failed call"""
        self.recent_calls[component].append(False)
        self.failure_counts[component] += 1
        self.last_failure_time[component] = time.time()
        self.last_error[component] = error

        state = self.states[component]

        if state == CircuitState.CLOSED:
            # Check if we should open circuit
            if self.failure_counts[component] >= self.config.failure_threshold:
                self._transition_to_open(component)

        elif state == CircuitState.HALF_OPEN:
            # Any failure in half-open state re-opens circuit
            self._transition_to_open(component)

    def _transition_to_open(self, component: str):
        """Transition circuit to OPEN state"""
        self.states[component] = CircuitState.OPEN
        logger.error(
            f"[CircuitBreaker] Opening circuit for {component} "
            f"after {self.failure_counts[component]} failures. "
            f"Last error: {self.last_error.get(component, 'unknown')}"
        )

    def _transition_to_half_open(self, component: str):
        """Transition circuit to HALF_OPEN state"""
        self.states[component] = CircuitState.HALF_OPEN
        self.success_counts[component] = 0  # Reset success counter
        logger.info(
            f"[CircuitBreaker] Entering half-open state for {component} "
            f"(testing recovery)"
        )

    def _transition_to_closed(self, component: str):
        """Transition circuit to CLOSED state"""
        self.states[component] = CircuitState.CLOSED
        self.failure_counts[component] = 0
        self.success_counts[component] = 0
        logger.info(
            f"[CircuitBreaker] Closing circuit for {component} "
            f"(recovered after {self.success_counts[component]} successes)"
        )

    def get_status(self, component: Optional[str] = None) -> Dict[str, Any]:
        """
        Get circuit breaker status.

        Args:
            component: Optional specific component to check

        Returns:
            Status dict
        """
        if component:
            recent = list(self.recent_calls.get(component, []))
            success_rate = (sum(recent) / len(recent) * 100) if recent else 100.0

            return {
                "component": component,
                "state": self.states[component].value,
                "failure_count": self.failure_counts[component],
                "success_count": self.success_counts[component],
                "last_error": self.last_error.get(component),
                "last_failure_time": self.last_failure_time.get(component),
                "success_rate": round(success_rate, 1),
                "recent_calls": recent
            }

        # Return status for all components
        return {
            comp: self.get_status(comp)
            for comp in set(list(self.states.keys()) + list(self.failure_counts.keys()))
        }

    def reset(self, component: Optional[str] = None):
        """
        Reset circuit breaker state (useful for testing or manual recovery).

        Args:
            component: Optional specific component to reset (resets all if None)
        """
        if component:
            self.states[component] = CircuitState.CLOSED
            self.failure_counts[component] = 0
            self.success_counts[component] = 0
            self.recent_calls[component].clear()
            logger.info(f"[CircuitBreaker] Manually reset circuit for {component}")
        else:
            self.states.clear()
            self.failure_counts.clear()
            self.success_counts.clear()
            self.recent_calls.clear()
            self.last_failure_time.clear()
            self.last_error.clear()
            logger.info("[CircuitBreaker] Manually reset all circuits")


# Decorator for easy circuit breaker integration
def with_circuit_breaker(component: str, breaker: Optional[CircuitBreaker] = None):
    """
    Decorator to add circuit breaker protection to a function.

    Usage:
        @with_circuit_breaker("my_component")
        def my_function():
            ...

        @with_circuit_breaker("my_async_component")
        async def my_async_function():
            ...
    """
    _breaker = breaker or _get_global_breaker()

    def decorator(fn: Callable):
        if asyncio.iscoroutinefunction(fn):
            @wraps(fn)
            async def async_wrapper(*args, **kwargs):
                return await _breaker.call_async(component, fn, *args, **kwargs)
            return async_wrapper
        else:
            @wraps(fn)
            def sync_wrapper(*args, **kwargs):
                return _breaker.call(component, fn, *args, **kwargs)
            return sync_wrapper

    return decorator


# Global circuit breaker instance
_global_breaker: Optional[CircuitBreaker] = None


def get_circuit_breaker() -> CircuitBreaker:
    """Get or create global circuit breaker instance"""
    global _global_breaker
    if _global_breaker is None:
        _global_breaker = CircuitBreaker()
    return _global_breaker


def _get_global_breaker() -> CircuitBreaker:
    """Internal: get global breaker"""
    return get_circuit_breaker()
