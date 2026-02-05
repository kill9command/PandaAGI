"""
Token Budget Allocator

Dynamic token budget allocation based on query characteristics.
Maximizes utilization of the 12k token limit by allocating more budget
to memory for knowledge-heavy queries and more to tools for product queries.

Usage:
    allocator = TokenBudgetAllocator()
    profile = allocator.get_profile(query_type="informational_memory")
    memory_budget = profile["forever_memory"]  # 4000 tokens
"""

import logging
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class BudgetProfile:
    """Token budget allocation for a specific query type."""

    name: str
    forever_memory: int
    prior_turns: int
    preferences: int
    tool_results: int
    other_sections: int  # §0, §2, §3 combined

    @property
    def total_input(self) -> int:
        """Total input tokens allocated."""
        return (
            self.forever_memory +
            self.prior_turns +
            self.preferences +
            self.tool_results +
            self.other_sections
        )

    def to_dict(self) -> Dict[str, int]:
        return {
            "forever_memory": self.forever_memory,
            "prior_turns": self.prior_turns,
            "preferences": self.preferences,
            "tool_results": self.tool_results,
            "other_sections": self.other_sections,
        }


class TokenBudgetAllocator:
    """
    Dynamic token budget allocation based on query characteristics.

    Maximizes the 12k token limit by shifting budget between memory
    and tool results based on what the query actually needs.

    Profiles:
    - informational_memory: Knowledge queries answered from memory (4k memory)
    - transactional: Product/commerce queries needing fresh data (4k tools)
    - follow_up: Balanced queries needing both (2.5k each)
    - code: Code-related queries (3.5k tools for code context)
    """

    TOTAL_BUDGET = 12000

    # Fixed costs that don't change
    FIXED_COSTS = {
        "system_prompt": 1500,   # Prompts from apps/prompts/
        "response_reserve": 2500,  # Space for LLM response
        "buffer": 500,           # Safety margin
    }

    # Available for input after fixed costs
    AVAILABLE_INPUT = TOTAL_BUDGET - sum(FIXED_COSTS.values())  # 7500

    # Budget profiles for different query types
    PROFILES = {
        "informational_memory": BudgetProfile(
            name="informational_memory",
            forever_memory=4000,   # Memory IS the answer
            prior_turns=500,
            preferences=200,
            tool_results=500,      # Minimal - just for citations
            other_sections=800,    # §0, §2, §3
        ),
        "transactional": BudgetProfile(
            name="transactional",
            forever_memory=1000,   # Just preferences and context
            prior_turns=300,
            preferences=300,
            tool_results=4000,     # Products, prices, URLs
            other_sections=900,
        ),
        "follow_up": BudgetProfile(
            name="follow_up",
            forever_memory=2500,   # Balanced
            prior_turns=1000,      # Prior context important
            preferences=200,
            tool_results=2000,
            other_sections=800,
        ),
        "code": BudgetProfile(
            name="code",
            forever_memory=1500,   # Code patterns, architecture
            prior_turns=500,
            preferences=100,
            tool_results=3500,     # Code context, file contents
            other_sections=900,
        ),
        "research": BudgetProfile(
            name="research",
            forever_memory=3000,   # Prior research findings
            prior_turns=500,
            preferences=200,
            tool_results=2500,     # New research results
            other_sections=800,
        ),
    }

    def __init__(self):
        self._validate_profiles()

    def _validate_profiles(self):
        """Ensure all profiles fit within available budget."""
        for name, profile in self.PROFILES.items():
            if profile.total_input > self.AVAILABLE_INPUT:
                logger.warning(
                    f"Profile '{name}' exceeds available budget: "
                    f"{profile.total_input} > {self.AVAILABLE_INPUT}"
                )

    def get_profile(self, query_type: str) -> BudgetProfile:
        """
        Get budget profile for a query type.

        Args:
            query_type: One of informational_memory, transactional,
                       follow_up, code, research

        Returns:
            BudgetProfile with token allocations
        """
        profile = self.PROFILES.get(query_type)
        if not profile:
            logger.warning(f"Unknown query type '{query_type}', using follow_up")
            profile = self.PROFILES["follow_up"]
        return profile

    def get_memory_budget(
        self,
        query_type: str,
        has_tool_results: bool = True,
        memory_result_count: int = 0
    ) -> int:
        """
        Get memory token budget for a specific query.

        If no tool results are expected, reallocates some of that budget
        to memory for richer context.

        Args:
            query_type: Query type for profile selection
            has_tool_results: Whether tool results will be included
            memory_result_count: Number of memory results found

        Returns:
            Token budget for forever memory section
        """
        profile = self.get_profile(query_type)
        base_budget = profile.forever_memory

        # If no tool results, reallocate half of tool budget to memory
        if not has_tool_results:
            bonus = profile.tool_results // 2
            base_budget += bonus
            logger.debug(
                f"No tool results - reallocating {bonus} tokens to memory "
                f"(total: {base_budget})"
            )

        # If many memory results, ensure we have enough budget
        if memory_result_count > 5:
            # At least 400 tokens per result for meaningful content
            min_budget = memory_result_count * 400
            if base_budget < min_budget and min_budget <= self.AVAILABLE_INPUT // 2:
                logger.debug(
                    f"Expanding memory budget for {memory_result_count} results: "
                    f"{base_budget} -> {min_budget}"
                )
                base_budget = min_budget

        return base_budget

    def detect_query_profile(
        self,
        intent: str,
        has_memory_hits: bool = False,
        memory_relevance: float = 0.0,
        is_follow_up: bool = False,
        mode: str = "chat"
    ) -> str:
        """
        Detect which budget profile to use based on query characteristics.

        Args:
            intent: Query intent (informational, transactional, navigation, code)
            has_memory_hits: Whether memory search found relevant results
            memory_relevance: Average relevance of memory hits (0-1)
            is_follow_up: Whether this is a follow-up to prior conversation
            mode: Operating mode (chat, code)

        Returns:
            Profile name to use
        """
        # Code mode always uses code profile
        if mode == "code":
            return "code"

        # High-relevance memory hits + informational intent = memory-focused
        if has_memory_hits and memory_relevance > 0.6:
            if intent in ["informational", "navigation"]:
                logger.info(
                    f"Detected informational_memory profile "
                    f"(intent={intent}, memory_relevance={memory_relevance:.2f})"
                )
                return "informational_memory"

        # Transactional queries need fresh tool results
        if intent == "transactional":
            return "transactional"

        # Research intent
        if intent == "research":
            return "research"

        # Follow-up queries need balanced context
        if is_follow_up:
            return "follow_up"

        # Default to follow_up for balanced allocation
        return "follow_up"


# Module-level instance
_allocator: Optional[TokenBudgetAllocator] = None


def get_allocator() -> TokenBudgetAllocator:
    """Get the global TokenBudgetAllocator instance."""
    global _allocator
    if _allocator is None:
        _allocator = TokenBudgetAllocator()
    return _allocator
