"""
Internet Research Tool - LLM-Driven Research Loop

Phase 1: Intelligence Gathering
- LLM (Research Planner) decides what to search and visit
- Document-based state (research_state.md)
- Simple tools: search(), visit(), done()

Phase 2: Product Finding
- Uses Phase 1 intelligence to find products from 3 vendors
- Extracts products and compares to Phase 1 expectations
- Returns products with recommendations
"""

from .research_loop import execute_research, Phase1Intelligence
from .phase2_products import execute_phase2, Phase2Result, Product

__all__ = [
    "execute_research",
    "execute_phase2",
    "execute_full_research",
    "Phase1Intelligence",
    "Phase2Result",
    "Product",
]


async def execute_full_research(
    goal: str,
    intent: str = "commerce",
    context: str = "",
    task: str = "",
    session_id: str = None,
    target_vendors: int = 3,
    max_visits: int = 8,
    config: dict = None,
    event_emitter = None,
    human_assist_allowed: bool = True,
    turn_dir_path: str = None,
    **kwargs,  # Accept extra args from workflow (prior_turn_context, topic, etc.)
) -> dict:
    """
    Execute full research: Phase 1 (intelligence) + Phase 2 (products).

    For commerce queries, this:
    1. Runs Phase 1 to gather intelligence (forums, reviews)
    2. Runs Phase 2 to find products from vendors using Phase 1 insights

    Args:
        goal: The user's original query (preserves priority signals like "cheapest")
        intent: "informational" or "commerce" (default commerce for full research)
        context: Session context from Planner (what we were discussing)
        task: Specific task from Planner (what to research)
        session_id: Browser session ID
        target_vendors: Number of vendors to visit in Phase 2 (default 3)
        config: Optional config overrides
        event_emitter: Optional event emitter for progress events
        human_assist_allowed: Whether to allow human intervention for CAPTCHAs
        turn_dir_path: Turn directory path for Document IO compliance

    Returns:
        Combined result with intelligence and products
    """
    import time
    import logging

    logger = logging.getLogger(__name__)
    session_id = session_id or f"research_{int(time.time())}"

    logger.info(f"[FullResearch] Starting research")
    logger.info(f"[FullResearch] Goal: {goal}")
    if context:
        logger.info(f"[FullResearch] Context: {context[:100]}...")
    if task:
        logger.info(f"[FullResearch] Task: {task}")
    logger.info(f"[FullResearch] Intent: {intent}, Target vendors: {target_vendors}")

    # Phase 1: Intelligence Gathering
    logger.info("[FullResearch] === PHASE 1: Intelligence Gathering ===")

    # Merge max_visits into config
    phase1_config = config.copy() if config else {}
    if max_visits:
        phase1_config["max_visits"] = max_visits

    # Extract target_url from kwargs if provided (for follow-up query routing)
    target_url = kwargs.get("target_url")

    phase1_result = await execute_research(
        goal=goal,
        intent=intent,
        context=context,
        task=task,
        session_id=f"{session_id}_p1",
        config=phase1_config,
        event_emitter=event_emitter,
        human_assist_allowed=human_assist_allowed,
        turn_dir_path=turn_dir_path,
        target_url=target_url,
    )

    logger.info(f"[FullResearch] Phase 1 complete: {phase1_result.pages_visited} pages visited")
    logger.info(f"[FullResearch] Phase 1 intelligence: {list(phase1_result.intelligence.keys())}")

    # For informational queries, stop here
    # Flatten phase1 results to top level for workflow success criteria
    if intent == "informational":
        phase1_dict = phase1_result.to_dict()
        # DEBUG: Log sources in phase1_dict
        logger.info(f"[FullResearch] DEBUG: phase1_dict sources={phase1_dict.get('sources', [])}")
        return {
            "success": phase1_result.success,
            "goal": goal,
            "intent": intent,
            # Flatten for workflow success criteria (expects findings, sources at top level)
            "findings": phase1_dict.get("findings", []),
            "sources": phase1_dict.get("sources", []),
            "intelligence": phase1_dict.get("intelligence", {}),
            "vendor_hints": phase1_dict.get("vendor_hints", []),
            "search_terms": phase1_dict.get("search_terms", []),
            "price_range": phase1_dict.get("price_range"),
            "research_state_md": phase1_dict.get("research_state_md", ""),
            # Also keep phase1 for backwards compatibility
            "phase1": phase1_dict,
            "phase2": None,
            "products": [],
            "recommendation": "",
            "price_assessment": "",
        }

    # Phase 2: Product Finding
    logger.info("[FullResearch] === PHASE 2: Product Finding ===")
    logger.info(f"[FullResearch] Vendor hints: {phase1_result.vendor_hints}")
    logger.info(f"[FullResearch] Search terms: {phase1_result.search_terms}")

    phase2_result = await execute_phase2(
        goal=goal,
        phase1_intelligence=phase1_result.intelligence,
        vendor_hints=phase1_result.vendor_hints,
        search_terms=phase1_result.search_terms,
        price_range=phase1_result.price_range,
        session_id=f"{session_id}_p2",
        target_vendors=target_vendors,
        event_emitter=event_emitter,
        human_assist_allowed=human_assist_allowed,
    )

    logger.info(f"[FullResearch] Phase 2 complete: {len(phase2_result.products)} products found")
    logger.info(f"[FullResearch] Vendors visited: {phase2_result.vendors_visited}")

    # Combined result
    return {
        "success": phase1_result.success and phase2_result.success,
        "goal": goal,
        "intent": intent,
        "phase1": phase1_result.to_dict(),
        "phase2": phase2_result.to_dict(),
        "products": [p.to_dict() for p in phase2_result.products],
        "recommendation": phase2_result.recommendation,
        "price_assessment": phase2_result.price_assessment,
        "research_state": phase1_result.research_state_md,
        "total_elapsed_seconds": phase1_result.elapsed_seconds + phase2_result.elapsed_seconds,
    }
