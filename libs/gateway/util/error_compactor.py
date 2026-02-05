"""
Error Compactor - Formats errors for LLM self-healing.

Implements Factor 9 (Compact Errors) from 12-Factor Agents:
- Classifies errors into known types
- Provides recovery suggestions for each error type
- Formats errors compactly for inclusion in context.md §4
- Helps LLM understand what went wrong and how to recover

Usage:
    compactor = ErrorCompactor()

    # When a tool fails:
    compacted = compactor.compact(exception, "internet.research", {"query": "..."})

    # Format for context.md:
    error_text = compacted.to_context_format()

    # For multiple consecutive failures:
    summary = compactor.format_consecutive_failures([error1, error2, error3])
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
import logging
import re

logger = logging.getLogger(__name__)


@dataclass
class CompactedError:
    """
    A compacted error with classification and recovery suggestion.

    Designed for LLM consumption - concise but informative.
    """
    tool: str
    error_type: str
    message: str
    suggestion: str
    retryable: bool

    def to_context_format(self) -> str:
        """
        Format for inclusion in context.md §4.

        Uses XML-like tags that LLMs parse well, with structured fields
        that enable the Planner/Coordinator to make informed decisions.
        """
        retry_hint = "Retryable with different parameters" if self.retryable else "Not retryable - try alternative approach"
        # Truncate message to avoid bloating context
        truncated_msg = self.message[:200] + "..." if len(self.message) > 200 else self.message
        return f"""<error tool="{self.tool}">
  type: {self.error_type}
  message: {truncated_msg}
  suggestion: {self.suggestion}
  retryable: {retry_hint}
</error>"""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "tool": self.tool,
            "error_type": self.error_type,
            "message": self.message,
            "suggestion": self.suggestion,
            "retryable": self.retryable
        }


# Recovery suggestions by error type
# These help the LLM understand how to recover from each error type
RECOVERY_SUGGESTIONS: Dict[str, str] = {
    "timeout": "Try with simpler query or different source. Consider breaking query into smaller parts.",
    "network_error": "Retry after brief delay. If persistent, try alternative data source.",
    "rate_limit": "Wait before retrying. Consider using cached data or alternative endpoint.",
    "parse_error": "Simplify expected output format. Check if response format changed.",
    "authentication_failed": "Check credentials. May require user intervention or API key refresh.",
    "permission_denied": "Verify access rights. May need escalation or alternative approach.",
    "empty_result": "Broaden search terms or try alternative sources. Query may be too specific.",
    "validation_error": "Check input parameters match expected schema. Review tool documentation.",
    "not_found": "Resource doesn't exist. Try alternative search terms or different source.",
    "blocked": "Site is blocking requests. Try alternative source or wait and retry later.",
    "extraction_failed": "Page structure may have changed. Try different extraction approach.",
    "unknown_error": "Review error details. Consider simplifying the request or trying alternative approach.",
}

# Error types that are generally retryable
RETRYABLE_ERRORS = {
    "timeout",
    "network_error",
    "rate_limit",
    "empty_result",
    "blocked",
}


class ErrorCompactor:
    """
    Compacts errors into LLM-friendly format with recovery suggestions.

    The compactor:
    1. Classifies errors by pattern matching on the error message
    2. Provides relevant recovery suggestions
    3. Determines if the error is retryable
    4. Formats errors compactly for context.md
    """

    def __init__(self):
        """Initialize the error compactor."""
        self.recovery_suggestions = RECOVERY_SUGGESTIONS
        self.retryable_errors = RETRYABLE_ERRORS

    def compact(
        self,
        error: Exception,
        tool_name: str,
        tool_args: Optional[Dict[str, Any]] = None,
    ) -> CompactedError:
        """
        Compact an exception into an LLM-friendly format.

        Args:
            error: The exception that occurred
            tool_name: Name of the tool that failed
            tool_args: Arguments passed to the tool (for context)

        Returns:
            CompactedError with classification and recovery suggestion
        """
        error_type = self._classify_error(error)
        suggestion = self.recovery_suggestions.get(
            error_type,
            "Review error and adjust approach"
        )

        # Add tool-specific context to suggestion if relevant
        if tool_name == "internet.research" and error_type == "empty_result":
            suggestion = "Try broader search terms or different vendors. Consider adding 'reviews' or 'comparison' to query."
        elif tool_name == "internet.research" and error_type == "timeout":
            suggestion = "Research taking too long. Try simpler query or limit to fewer vendors."
        elif tool_name == "memory.search" and error_type == "empty_result":
            suggestion = "No relevant memories found. This is expected for new topics - proceed with research."

        # Build clean error message (strip stack traces for LLM readability)
        error_msg = str(error)
        # Remove common noise patterns
        error_msg = re.sub(r'\n\s+at .*', '', error_msg)  # Strip stack traces
        error_msg = re.sub(r'\s+', ' ', error_msg).strip()  # Normalize whitespace

        return CompactedError(
            tool=tool_name,
            error_type=error_type,
            message=error_msg,
            suggestion=suggestion,
            retryable=error_type in self.retryable_errors,
        )

    def compact_from_result(
        self,
        result: Dict[str, Any],
        tool_name: str,
    ) -> Optional[CompactedError]:
        """
        Compact an error from a tool result dict.

        Many tools return {"status": "error", "error": "..."} rather than
        raising exceptions. This handles those cases.

        Args:
            result: Tool result dictionary
            tool_name: Name of the tool

        Returns:
            CompactedError if result indicates failure, None otherwise
        """
        status = result.get("status", "")
        if status not in ("error", "failed", "timeout"):
            return None

        error_msg = result.get("error", "") or result.get("message", "Unknown error")
        error_type = result.get("error_type", "") or self._classify_error_string(error_msg)

        suggestion = self.recovery_suggestions.get(
            error_type,
            "Review error and adjust approach"
        )

        return CompactedError(
            tool=tool_name,
            error_type=error_type,
            message=str(error_msg)[:200],
            suggestion=suggestion,
            retryable=error_type in self.retryable_errors,
        )

    def _classify_error(self, error: Exception) -> str:
        """
        Classify an exception into a known error type.

        Uses pattern matching on both the exception type and message.
        """
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()

        return self._classify_error_string(f"{error_type} {error_str}")

    def _classify_error_string(self, error_str: str) -> str:
        """
        Classify an error string into a known error type.

        Order matters - more specific patterns should come first.
        """
        error_lower = error_str.lower()

        # Timeout patterns
        if any(p in error_lower for p in ["timeout", "timed out", "deadline exceeded"]):
            return "timeout"

        # Rate limiting patterns
        if any(p in error_lower for p in ["rate limit", "429", "too many requests", "throttl"]):
            return "rate_limit"

        # Network patterns
        if any(p in error_lower for p in ["connection", "network", "dns", "socket", "refused"]):
            return "network_error"

        # Permission/auth patterns
        if any(p in error_lower for p in ["permission", "forbidden", "403"]):
            return "permission_denied"
        if any(p in error_lower for p in ["auth", "unauthorized", "401", "credential"]):
            return "authentication_failed"

        # Parse/format patterns
        if any(p in error_lower for p in ["parse", "json", "decode", "format", "syntax"]):
            return "parse_error"

        # Not found patterns
        if any(p in error_lower for p in ["not found", "404", "does not exist", "no such"]):
            return "not_found"

        # Empty result patterns
        if any(p in error_lower for p in ["empty", "no results", "no data", "zero products"]):
            return "empty_result"

        # Validation patterns
        if any(p in error_lower for p in ["validation", "schema", "invalid", "required field"]):
            return "validation_error"

        # Blocking patterns
        if any(p in error_lower for p in ["blocked", "captcha", "bot detected", "geofence"]):
            return "blocked"

        # Extraction patterns
        if any(p in error_lower for p in ["extraction", "extract", "scrape"]):
            return "extraction_failed"

        return "unknown_error"

    def format_consecutive_failures(
        self,
        failures: List[CompactedError],
        max_display: int = 3,
    ) -> str:
        """
        Format multiple consecutive failures for context.md.

        Provides aggregate view of failures to help LLM understand
        the pattern and make informed retry decisions.

        Args:
            failures: List of CompactedError objects
            max_display: Maximum number of individual failures to show

        Returns:
            Formatted markdown string for §4
        """
        if not failures:
            return ""

        lines = [f"### Consecutive Failures ({len(failures)} total)"]
        lines.append("")

        # Show last N failures (most recent are most relevant)
        for f in failures[-max_display:]:
            lines.append(f.to_context_format())
            lines.append("")

        if len(failures) > max_display:
            lines.append(f"... and {len(failures) - max_display} earlier failures")
            lines.append("")

        # Aggregate analysis
        error_types = [f.error_type for f in failures]
        unique_types = set(error_types)
        retryable_count = sum(1 for f in failures if f.retryable)

        lines.append("**Pattern Analysis:**")
        lines.append(f"- Error types: {', '.join(unique_types)}")
        lines.append(f"- Retryable: {retryable_count}/{len(failures)}")

        # Aggregate recommendation
        if all(f.retryable for f in failures):
            lines.append("")
            lines.append("**Recovery:** All failures are retryable. Consider:")
            lines.append("- Trying alternative sources")
            lines.append("- Simplifying the query")
            lines.append("- Waiting briefly before retry")
        elif retryable_count == 0:
            lines.append("")
            lines.append("**Recovery:** Failures require different approach:")
            lines.append("- Check credentials/permissions")
            lines.append("- Try alternative tools")
            lines.append("- Consider asking user for clarification")
        else:
            lines.append("")
            lines.append("**Recovery:** Mixed failure types. Review specific suggestions above.")

        return "\n".join(lines)


# Module-level singleton for convenience
_error_compactor: Optional[ErrorCompactor] = None


def get_error_compactor() -> ErrorCompactor:
    """Get or create the singleton error compactor instance."""
    global _error_compactor
    if _error_compactor is None:
        _error_compactor = ErrorCompactor()
    return _error_compactor
