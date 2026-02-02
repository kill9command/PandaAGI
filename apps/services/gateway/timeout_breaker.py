"""
Timeout-Based Circuit Breaker for Tool Calls and LLM Operations

Extends existing circuit_breaker.py with timeout-specific implementation
and exponential backoff for Quality Agent requirements.

Quality Agent Requirement: Prevent research from hanging indefinitely,
provide timeout protection with retry logic.
"""
import asyncio
import logging
import os
from typing import Callable, Any, Optional
from functools import wraps

logger = logging.getLogger(__name__)


class TimeoutError(Exception):
    """Raised when operation times out."""
    pass


class TimeoutBreaker:
    """
    Timeout-based circuit breaker for operations that may hang.

    Quality Agent Requirement: Prevent operations from hanging indefinitely,
    implement graceful degradation with exponential backoff.
    """

    # Default timeouts (configurable via environment)
    RESEARCH_TIMEOUT = int(os.getenv("RESEARCH_TIMEOUT", "300"))  # 5 minutes
    LLM_TIMEOUT = int(os.getenv("MODEL_TIMEOUT", "90"))           # 90 seconds
    TOOL_TIMEOUT = int(os.getenv("TOOL_TIMEOUT", "120"))          # 2 minutes

    def __init__(
        self,
        name: str,
        timeout: int,
        max_retries: int = 3,
        backoff_factor: float = 2.0
    ):
        """
        Initialize timeout breaker.

        Args:
            name: Breaker name (for logging)
            timeout: Base timeout in seconds
            max_retries: Maximum retry attempts
            backoff_factor: Exponential backoff multiplier
        """
        self.name = name
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        # Statistics
        self.total_calls = 0
        self.timeouts = 0
        self.failures = 0
        self.retries = 0
        self.successes = 0

    async def execute(
        self,
        fn: Callable,
        *args,
        fallback: Optional[Callable] = None,
        **kwargs
    ) -> Any:
        """
        Execute function with timeout and retry logic.

        Args:
            fn: Async function to execute
            *args, **kwargs: Arguments to fn
            fallback: Optional fallback function if all retries fail

        Returns:
            Function result or fallback result

        Raises:
            TimeoutError: If max retries exceeded and no fallback
        """

        self.total_calls += 1
        attempt = 0
        last_error = None

        while attempt < self.max_retries:
            attempt += 1

            try:
                # Calculate timeout with exponential backoff
                current_timeout = self.timeout * (self.backoff_factor ** (attempt - 1))

                logger.info(
                    f"[TimeoutBreaker:{self.name}] Attempt {attempt}/{self.max_retries}, "
                    f"timeout: {current_timeout}s"
                )

                # Execute with timeout
                result = await asyncio.wait_for(
                    fn(*args, **kwargs),
                    timeout=current_timeout
                )

                # Success!
                self.successes += 1
                logger.info(f"[TimeoutBreaker:{self.name}] ✓ Success on attempt {attempt}")
                return result

            except asyncio.TimeoutError:
                self.timeouts += 1
                last_error = f"Timeout after {current_timeout}s"
                logger.warning(
                    f"[TimeoutBreaker:{self.name}] ⏱ {last_error} "
                    f"(attempt {attempt}/{self.max_retries})"
                )

                if attempt < self.max_retries:
                    self.retries += 1
                    wait_time = self.backoff_factor ** (attempt - 1)
                    logger.info(f"[TimeoutBreaker:{self.name}] Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)

            except Exception as e:
                self.failures += 1
                last_error = str(e)
                logger.error(
                    f"[TimeoutBreaker:{self.name}] ✗ Error: {e} "
                    f"(attempt {attempt}/{self.max_retries})"
                )

                if attempt < self.max_retries:
                    self.retries += 1
                    wait_time = self.backoff_factor ** (attempt - 1)
                    logger.info(f"[TimeoutBreaker:{self.name}] Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    # Last attempt failed - break out
                    break

        # All retries failed
        if fallback:
            logger.warning(
                f"[TimeoutBreaker:{self.name}] All retries failed, using fallback"
            )
            try:
                if asyncio.iscoroutinefunction(fallback):
                    return await fallback(*args, **kwargs)
                else:
                    return fallback(*args, **kwargs)
            except Exception as e:
                logger.error(f"[TimeoutBreaker:{self.name}] Fallback also failed: {e}")
                # Continue to raise error below

        # No fallback or fallback failed - raise error
        self.failures += 1
        error_msg = f"Timeout breaker tripped for {self.name}: {last_error}"
        logger.error(f"[TimeoutBreaker:{self.name}] {error_msg}")
        raise TimeoutError(error_msg)

    def get_stats(self) -> dict:
        """
        Get timeout breaker statistics.

        Returns:
            Statistics dictionary with success rate and counts
        """
        success_rate = 0.0
        if self.total_calls > 0:
            success_rate = self.successes / self.total_calls

        return {
            "name": self.name,
            "total_calls": self.total_calls,
            "successes": self.successes,
            "timeouts": self.timeouts,
            "failures": self.failures,
            "retries": self.retries,
            "success_rate": f"{success_rate * 100:.1f}%",
            "timeout_seconds": self.timeout,
            "max_retries": self.max_retries
        }

    def reset_stats(self):
        """Reset statistics (for testing)."""
        self.total_calls = 0
        self.timeouts = 0
        self.failures = 0
        self.retries = 0
        self.successes = 0


# Global timeout breakers
RESEARCH_BREAKER = TimeoutBreaker(
    name="research",
    timeout=TimeoutBreaker.RESEARCH_TIMEOUT,
    max_retries=1  # No retries - research is expensive and duplicate requests cause issues
)

LLM_BREAKER = TimeoutBreaker(
    name="llm",
    timeout=TimeoutBreaker.LLM_TIMEOUT,
    max_retries=3
)

TOOL_BREAKER = TimeoutBreaker(
    name="tool",
    timeout=TimeoutBreaker.TOOL_TIMEOUT,
    max_retries=3
)


def with_timeout_breaker(breaker: TimeoutBreaker, fallback: Optional[Callable] = None):
    """
    Decorator to wrap async functions with timeout breaker.

    Args:
        breaker: TimeoutBreaker instance to use
        fallback: Optional fallback function

    Usage:
        @with_timeout_breaker(LLM_BREAKER)
        async def call_llm(prompt):
            return await model_client.chat(prompt)
    """
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            return await breaker.execute(fn, *args, fallback=fallback, **kwargs)
        return wrapper
    return decorator


def get_all_stats() -> dict:
    """Get statistics for all global timeout breakers."""
    return {
        "research": RESEARCH_BREAKER.get_stats(),
        "llm": LLM_BREAKER.get_stats(),
        "tool": TOOL_BREAKER.get_stats()
    }
