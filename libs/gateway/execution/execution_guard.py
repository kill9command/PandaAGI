"""
Execution Guard - Budget and safety checks for pipeline execution.

Extracted from UnifiedFlow to provide:
- Token budget checking before LLM calls
- Circular call detection for tool loops
- Tool argument hashing for deduplication

These guards prevent:
- Context overflow causing truncation
- Infinite loops in tool execution
- Redundant API calls
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument
    from libs.gateway.research.smart_summarization import SmartSummarizer

logger = logging.getLogger(__name__)


class ExecutionGuard:
    """
    Guards against common execution problems.

    Responsibilities:
    - Check context fits within token budget
    - Detect circular tool call patterns
    - Hash tool arguments for comparison
    """

    def __init__(self, summarizer: Optional["SmartSummarizer"] = None):
        """
        Initialize the execution guard.

        Args:
            summarizer: Optional SmartSummarizer for budget checking
        """
        self.summarizer = summarizer

    def check_budget(
        self,
        context_doc: "ContextDocument",
        recipe: Any,
        phase_name: str
    ) -> bool:
        """
        Check if context document fits within recipe budget.

        Logs warning if compression would be needed.

        Args:
            context_doc: Current context document
            recipe: Recipe with token_budget
            phase_name: Name of the phase for logging

        Returns:
            True if within budget, False if exceeds
        """
        if not self.summarizer:
            return True

        content = context_doc.get_markdown()
        documents = {"context.md": content}

        # Get budget from recipe
        budget = getattr(recipe, 'token_budget', None)
        if hasattr(budget, 'total'):
            budget = budget.total
        budget = budget or 12000

        plan = self.summarizer.check_budget(documents, budget)

        if plan.needed:
            logger.warning(
                f"[ExecutionGuard] {phase_name}: Context exceeds budget "
                f"({plan.total_tokens}/{plan.budget} tokens, overflow={plan.overflow})"
            )
            return False
        else:
            logger.debug(
                f"[ExecutionGuard] {phase_name}: Context within budget "
                f"({plan.total_tokens}/{plan.budget} tokens)"
            )
            return True

    def detect_circular_calls(
        self,
        call_history: List[Tuple[str, str]],
        window: int = 4
    ) -> bool:
        """
        Detect circular call patterns like A→B→A→B in tool call history.

        Args:
            call_history: List of (tool_name, args_hash) tuples
            window: Size of pattern window to check (default 4 for A→B→A→B)

        Returns:
            True if circular pattern detected
        """
        if len(call_history) < window:
            return False

        # Check for A→B→A→B pattern (same 2-call sequence repeated)
        recent = call_history[-window:]
        if window >= 4:
            first_pair = (recent[0], recent[1])
            second_pair = (recent[2], recent[3])
            if first_pair == second_pair:
                logger.warning(
                    f"[ExecutionGuard] Circular pattern detected: "
                    f"{first_pair[0]}→{second_pair[0]}→{first_pair[0]}→{second_pair[0]}"
                )
                return True

        # Check for A→A→A pattern (same call 3+ times)
        if len(call_history) >= 3:
            last_three = call_history[-3:]
            if len(set(last_three)) == 1:
                logger.warning(
                    f"[ExecutionGuard] Repeated call pattern detected: "
                    f"{last_three[0][0]} called 3+ times"
                )
                return True

        return False

    def hash_tool_args(self, args: Dict[str, Any]) -> str:
        """
        Create a simple hash of tool arguments for circular detection.

        Args:
            args: Tool arguments dictionary

        Returns:
            8-character hex hash
        """
        args_str = json.dumps(args, sort_keys=True, default=str)
        return hashlib.md5(args_str.encode()).hexdigest()[:8]

    def check_duplicate_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        call_history: List[Tuple[str, str]]
    ) -> bool:
        """
        Check if this exact call was already made.

        Args:
            tool_name: Name of the tool
            args: Tool arguments
            call_history: Previous calls as (tool_name, args_hash) tuples

        Returns:
            True if this is a duplicate call
        """
        args_hash = self.hash_tool_args(args)
        call_key = (tool_name, args_hash)

        if call_key in call_history:
            logger.warning(
                f"[ExecutionGuard] Duplicate call detected: "
                f"{tool_name} with same arguments"
            )
            return True

        return False


# Module-level convenience functions

def hash_tool_args(args: Dict[str, Any]) -> str:
    """Create a hash of tool arguments."""
    args_str = json.dumps(args, sort_keys=True, default=str)
    return hashlib.md5(args_str.encode()).hexdigest()[:8]


def detect_circular_calls(
    call_history: List[Tuple[str, str]],
    window: int = 4
) -> bool:
    """Detect circular call patterns."""
    guard = ExecutionGuard()
    return guard.detect_circular_calls(call_history, window)
