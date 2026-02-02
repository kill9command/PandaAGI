"""
Token Governance: Budget Reservation and Strategy Management

Implements Pre-Phase token governance for v4 flow:
- Detect research strategy from ticket
- Reserve budget upfront before building doc packs
- Auto-downgrade strategy if budget insufficient
- Track decisions in manifest for audit trail
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Strategy budget requirements
STRATEGY_BUDGETS = {
    "QUICK": {
        "phase1_tokens": 0,      # No Phase 1 (cache-only or skip)
        "phase2_tokens": 1500,   # Product claims from vendors
        "doc_pack_tokens": 500,  # Summary for Guide
        "total_reserved": 2000
    },
    "STANDARD": {
        "phase1_tokens": 0,      # Reuse cached intelligence
        "phase2_tokens": 3000,   # Full vendor search
        "doc_pack_tokens": 1000, # Summary + key findings
        "total_reserved": 4000
    },
    "DEEP": {
        "phase1_tokens": 4000,   # SerpApi + selective Playwright
        "phase2_tokens": 3000,   # Vendor search + claims
        "doc_pack_tokens": 1000, # Summary
        "total_reserved": 8000   # Budget reservation for deep research
    }
}


def detect_strategy(ticket: Dict[str, Any]) -> str:
    """
    Detect research strategy from ticket.

    Args:
        ticket: Task ticket from Guide

    Returns:
        Strategy name: "QUICK", "STANDARD", or "DEEP"

    Logic:
        - QUICK: User says "quick", "fast", "price check"
        - DEEP: Tool is "research.deep" OR user says "deep research"
        - STANDARD: Default for internet.research
    """

    # Check tool name (explicit deep research tool)
    tools = ticket.get("tools", [])
    if "research.deep" in tools:
        logger.info("[TokenGov] Detected DEEP strategy: research.deep tool")
        return "DEEP"

    # Check user query keywords
    user_query = ticket.get("user_query", "").lower()

    # Quick indicators
    quick_keywords = ["quick", "fast", "price check", "how much", "cost"]
    if any(kw in user_query for kw in quick_keywords):
        logger.info(f"[TokenGov] Detected QUICK strategy: keyword match")
        return "QUICK"

    # Deep indicators
    deep_keywords = [
        "deep research", "comprehensive", "detailed analysis",
        "thorough", "exhaustive", "learn everything", "in-depth"
    ]
    if any(kw in user_query for kw in deep_keywords):
        logger.info(f"[TokenGov] Detected DEEP strategy: keyword match")
        return "DEEP"

    # Explicit strategy hint from ticket
    if "strategy_hint" in ticket:
        strategy = ticket["strategy_hint"].upper()
        if strategy in ["QUICK", "STANDARD", "DEEP"]:
            logger.info(f"[TokenGov] Using explicit strategy hint: {strategy}")
            return strategy

    # Default to STANDARD
    logger.info("[TokenGov] Defaulting to STANDARD strategy")
    return "STANDARD"


def reserve_research_budget(
    ticket: Dict[str, Any],
    available_budget: int,
    force_strategy: Optional[str] = None
) -> Dict[str, Any]:
    """
    Reserve token budget for research BEFORE building doc packs.

    Args:
        ticket: Task ticket from Guide
        available_budget: Tokens available after Guide/Coordinator/CM prompts
        force_strategy: Override strategy detection (for testing)

    Returns:
        {
            "strategy": "QUICK" | "STANDARD" | "DEEP",
            "reserved": int,  # Tokens reserved for doc pack
            "remaining": int,  # Available for Guide/Coord/CM
            "approved": bool,
            "fallback": str | None,  # Downgrade reason if applicable
            "budget_details": dict  # Phase breakdown
        }

    Quality Agent Requirement: Reserve budget upfront to prevent overflow,
    auto-downgrade if insufficient.
    """

    # Detect strategy
    if force_strategy:
        strategy = force_strategy.upper()
        logger.info(f"[TokenGov] Strategy FORCED: {strategy}")
    else:
        strategy = detect_strategy(ticket)

    budget_req = STRATEGY_BUDGETS[strategy]
    total_reserved = budget_req["total_reserved"]

    logger.info(
        f"[TokenGov] Strategy: {strategy}, "
        f"Requires: {total_reserved} tokens, "
        f"Available: {available_budget} tokens"
    )

    # Check if we can afford it
    if total_reserved > available_budget:
        logger.warning(
            f"[TokenGov] Insufficient budget for {strategy} "
            f"(needs {total_reserved}, have {available_budget})"
        )

        # Auto-downgrade DEEP → STANDARD
        if strategy == "DEEP" and available_budget >= STRATEGY_BUDGETS["STANDARD"]["total_reserved"]:
            logger.warning(f"[TokenGov] Downgrading DEEP → STANDARD")
            downgraded_budget = STRATEGY_BUDGETS["STANDARD"]
            return {
                "strategy": "STANDARD",
                "reserved": downgraded_budget["total_reserved"],
                "remaining": available_budget - downgraded_budget["total_reserved"],
                "approved": True,
                "fallback": "downgrade_from_deep",
                "original_strategy": "DEEP",
                "budget_details": downgraded_budget
            }

        # Auto-downgrade STANDARD → QUICK
        elif strategy in ["DEEP", "STANDARD"] and available_budget >= STRATEGY_BUDGETS["QUICK"]["total_reserved"]:
            logger.warning(f"[TokenGov] Downgrading {strategy} → QUICK")
            downgraded_budget = STRATEGY_BUDGETS["QUICK"]
            return {
                "strategy": "QUICK",
                "reserved": downgraded_budget["total_reserved"],
                "remaining": available_budget - downgraded_budget["total_reserved"],
                "approved": True,
                "fallback": f"downgrade_from_{strategy.lower()}",
                "original_strategy": strategy,
                "budget_details": downgraded_budget
            }

        # Not enough budget for ANY research
        else:
            logger.error(
                f"[TokenGov] Cannot afford ANY research strategy "
                f"(minimum 2000 tokens, have {available_budget})"
            )
            return {
                "strategy": None,
                "reserved": 0,
                "remaining": available_budget,
                "approved": False,
                "fallback": "insufficient_budget",
                "original_strategy": strategy,
                "budget_details": {}
            }

    # Budget approved - no downgrade needed
    logger.info(f"[TokenGov] Budget approved for {strategy} strategy")
    return {
        "strategy": strategy,
        "reserved": total_reserved,
        "remaining": available_budget - total_reserved,
        "approved": True,
        "fallback": None,
        "original_strategy": strategy,
        "budget_details": budget_req
    }


def validate_budget_usage(
    reservation: Dict[str, Any],
    actual_usage: Dict[str, int]
) -> Dict[str, Any]:
    """
    Validate that actual token usage matches reservation.

    Args:
        reservation: Budget reservation from reserve_research_budget()
        actual_usage: Actual token usage by phase

    Returns:
        {
            "within_budget": bool,
            "reserved": int,
            "used": int,
            "overflow": int,
            "efficiency": str  # Percentage of reserved budget used
        }
    """

    reserved = reservation["reserved"]
    used = sum(actual_usage.values())
    overflow = max(0, used - reserved)
    within_budget = used <= reserved

    efficiency = (used / reserved * 100) if reserved > 0 else 0.0

    if not within_budget:
        logger.error(
            f"[TokenGov] Budget overflow! "
            f"Reserved: {reserved}, Used: {used}, Overflow: {overflow}"
        )
    else:
        logger.info(
            f"[TokenGov] Budget OK: {used}/{reserved} tokens ({efficiency:.1f}% efficiency)"
        )

    return {
        "within_budget": within_budget,
        "reserved": reserved,
        "used": used,
        "overflow": overflow,
        "efficiency": f"{efficiency:.1f}%",
        "breakdown": actual_usage
    }


def get_strategy_config(strategy: str) -> Dict[str, Any]:
    """Get configuration for a strategy."""
    return STRATEGY_BUDGETS.get(strategy.upper(), STRATEGY_BUDGETS["STANDARD"])
