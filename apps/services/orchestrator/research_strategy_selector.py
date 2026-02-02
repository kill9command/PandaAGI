"""
orchestrator/research_strategy_selector.py

LLM-powered research strategy selection.
Analyzes query and session context to select optimal execution strategy.

Created: 2025-11-15
"""
import json
import httpx
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Prompt cache
_prompt_cache: Dict[str, str] = {}


def _load_prompt_via_recipe(recipe_name: str, category: str = "research") -> str:
    """Load prompt via recipe system with fallback."""
    cache_key = f"{category}/{recipe_name}"
    if cache_key in _prompt_cache:
        return _prompt_cache[cache_key]
    try:
        from libs.gateway.recipe_loader import load_recipe
        recipe = load_recipe(f"{category}/{recipe_name}")
        content = recipe.get_prompt()
        _prompt_cache[cache_key] = content
        return content
    except Exception as e:
        logger.warning(f"Recipe {cache_key} not found: {e}")
        return ""


def _load_query_prompt(prompt_name: str) -> str:
    """Load a prompt template via recipe system (backwards-compatible name)."""
    # Map old prompt name to new recipe location
    name_mapping = {
        "research_strategy_selector": "strategy_selector",
    }
    recipe_name = name_mapping.get(prompt_name, prompt_name)
    return _load_prompt_via_recipe(recipe_name, "research")


async def analyze_and_select_strategy(
    query: str,
    session_id: str,
    cached_intelligence_available: bool = False,
    user_preferences: Optional[Dict] = None,
    knowledge_context: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Use LLM to decide which research phases to execute.

    This decides WHICH PHASES to run:
    - "phase1_only": Just gather intelligence (informational/research queries)
    - "phase2_only": Just search products (use cached intel)
    - "phase1_and_phase2": Run both phases (commerce without cached intel)

    Pass count (single vs multi-pass) is controlled by the `mode` parameter
    in research_role.orchestrate(), NOT by this function.

    Args:
        query: User's search query
        session_id: Session ID
        cached_intelligence_available: Whether Phase 1 intelligence is cached
        user_preferences: Optional user preferences (speed vs quality, etc.)
        knowledge_context: Optional knowledge context with topic match info

    Returns:
        {
            "phases": "phase1_only|phase2_only|phase1_and_phase2",
            "confidence": 0.0-1.0,
            "reason": "explanation",
            "config": {
                "skip_phase1": bool,
                "execute_phase2": bool,
                "max_sources_phase1": int,
                "max_sources_phase2": int
            }
        }
    """
    # Extract knowledge context info for LLM prompt
    has_topic_knowledge = False
    topic_name = ""
    knowledge_completeness = 0.0

    if knowledge_context:
        has_topic_knowledge = knowledge_context.get("phase1_skip_recommended", False)
        topic_name = knowledge_context.get("best_match_topic_name", "")
        knowledge_completeness = knowledge_context.get("knowledge_completeness", 0.0)

    # Build user preference context
    pref_text = "Normal quality and speed"
    if user_preferences:
        if user_preferences.get("prefer_speed"):
            pref_text = "Prefer fast results over comprehensive research"
        elif user_preferences.get("prefer_quality"):
            pref_text = "Prefer comprehensive research over speed"

    # Build knowledge context for prompt
    knowledge_text = "None"
    if knowledge_context:
        knowledge_text = f"""
- Topic match: {topic_name or 'None'} (completeness: {knowledge_completeness:.0%})
- Has retailers: {bool(knowledge_context.get('retailers', []))}
- Has specs: {bool(knowledge_context.get('key_specs', []))}
- Phase 1 skip recommended: {has_topic_knowledge}"""

    # Get intent from Phase 0 (authoritative source)
    phase0_intent = user_preferences.get('intent', 'unknown') if user_preferences else 'unknown'

    # CRITICAL: Honor Phase 0 intent - do not re-classify
    # This is a deterministic decision based on architecture rules
    if phase0_intent in ("commerce", "transactional", "site_search", "navigation"):
        # Commerce-type intent: need products
        if cached_intelligence_available or has_topic_knowledge:
            logger.info(f"[StrategySelector] Intent={phase0_intent}, cached=True → PHASE2_ONLY (deterministic)")
            return {
                "phases": "phase2_only",
                "confidence": 0.95,
                "reason": f"Phase 0 intent is {phase0_intent} with cached intelligence - skip to product finding",
                "config": {
                    "skip_phase1": True,
                    "execute_phase2": True,
                    "max_sources_phase1": 0,
                    "max_sources_phase2": 12
                }
            }
        else:
            logger.info(f"[StrategySelector] Intent={phase0_intent}, cached=False → PHASE1_AND_PHASE2 (deterministic)")
            return {
                "phases": "phase1_and_phase2",
                "confidence": 0.95,
                "reason": f"Phase 0 intent is {phase0_intent} without cached intelligence - need both phases",
                "config": {
                    "skip_phase1": False,
                    "execute_phase2": True,
                    "max_sources_phase1": 8,
                    "max_sources_phase2": 12
                }
            }
    elif phase0_intent == "informational":
        logger.info(f"[StrategySelector] Intent={phase0_intent} → PHASE1_ONLY (deterministic)")
        return {
            "phases": "phase1_only",
            "confidence": 0.95,
            "reason": f"Phase 0 intent is {phase0_intent} - research only, no product finding",
            "config": {
                "skip_phase1": False,
                "execute_phase2": False,
                "max_sources_phase1": 10,
                "max_sources_phase2": 0
            }
        }

    # Only use LLM if Phase 0 intent is unknown (fallback path)
    logger.info(f"[StrategySelector] Intent={phase0_intent} (unknown) - using LLM to decide")

    # Load prompt from recipe file
    base_prompt = _load_query_prompt("research_strategy_selector")
    if not base_prompt:
        base_prompt = """You are a research phase selector. Decide which research phases to execute.

## Available Phase Options

### 1. PHASE1_ONLY (Research only, 30-60 seconds)
When to use:
- Informational queries ("what is", "how does", "tell me about", "learn about")
- User wants to understand a topic, not buy something
- Research/educational intent

### 2. PHASE2_ONLY (Product search, 30-60 seconds)
When to use:
- Cached intelligence EXISTS for this topic
- Follow-up commerce query in same conversation

### 3. PHASE1_AND_PHASE2 (Full search, 60-120 seconds)
When to use:
- Commerce/transactional queries WITHOUT cached intelligence
- First "buy"/"find"/"where to get" query on new topic

## Decision Rules
1. Informational intent → PHASE1_ONLY
2. Commerce intent + cached_intelligence_available=True → PHASE2_ONLY
3. Commerce intent + cached_intelligence_available=False → PHASE1_AND_PHASE2

Output JSON ONLY (no other text)."""

    # Build full prompt with dynamic data
    prompt = f"""{base_prompt}

## Current Request

QUERY: "{query}"

SESSION CONTEXT:
- Cached intelligence available: {cached_intelligence_available}
- Session ID: {session_id}
- User preference: {pref_text}

TOPIC KNOWLEDGE:{knowledge_text}"""

    try:
        # Get LLM config
        llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

        logger.info(f"[StrategySelector] Analyzing query: '{query[:50]}...'")

        # Call LLM
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                llm_url,
                json={
                    "model": llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 400,
                    "temperature": 0.1  # Low temperature for consistent decisions
                },
                headers={"Authorization": f"Bearer {llm_api_key}"}
            )

        response.raise_for_status()
        result_text = response.json()["choices"][0]["message"]["content"]

        # Extract JSON from response
        result_text = result_text.strip()

        # Remove markdown code blocks if present
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]

        # Parse JSON
        decision = json.loads(result_text.strip())

        # Validate decision structure (phases: phase1_only, phase2_only, or phase1_and_phase2)
        phases = decision.get("phases", "").lower()
        if phases not in ["phase1_only", "phase2_only", "phase1_and_phase2"]:
            raise ValueError(f"Invalid phases: {phases}")

        if "config" not in decision:
            decision["config"] = {}

        # Set defaults for missing config fields based on phases
        config = decision["config"]

        if phases == "phase1_only":
            config.setdefault("skip_phase1", False)
            config.setdefault("execute_phase2", False)
            config.setdefault("max_sources_phase1", 10)
            config.setdefault("max_sources_phase2", 0)
        elif phases == "phase2_only":
            config.setdefault("skip_phase1", True)
            config.setdefault("execute_phase2", True)
            config.setdefault("max_sources_phase1", 0)
            config.setdefault("max_sources_phase2", 10)
        else:  # phase1_and_phase2
            config.setdefault("skip_phase1", False)
            config.setdefault("execute_phase2", True)
            config.setdefault("max_sources_phase1", 10)
            config.setdefault("max_sources_phase2", 12)

        logger.info(
            f"[PhaseSelector] Selected: {phases.upper()} "
            f"(confidence: {decision.get('confidence', 0.9):.2f}) - {decision.get('reason', 'No reason')}"
        )

        return decision

    except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error(f"[StrategySelector] Error selecting strategy: {e}")
        logger.warning("[StrategySelector] Falling back to default strategy selection")

        # Fallback logic if LLM fails - pass intent for deterministic handling
        intent = user_preferences.get('intent', 'unknown') if user_preferences else 'unknown'
        return _fallback_strategy_selection(query, cached_intelligence_available, knowledge_context, intent)


def _fallback_strategy_selection(
    query: str,
    cached_intelligence_available: bool,
    knowledge_context: Optional[Dict] = None,
    intent: str = "unknown"
) -> Dict[str, Any]:
    """
    Rule-based fallback if LLM phase selection fails.

    PRIORITY: Honor Phase 0 intent if provided, then fall back to keyword matching.

    Logic:
    1. If intent from Phase 0 is known, use it (authoritative)
    2. Otherwise, use keyword matching (legacy fallback)
    """
    # Check for topic knowledge from knowledge_retriever
    has_topic_knowledge = False
    if knowledge_context:
        has_topic_knowledge = knowledge_context.get("phase1_skip_recommended", False)

    # PRIORITY 1: Honor Phase 0 intent if known
    if intent in ("commerce", "transactional", "site_search", "navigation"):
        if cached_intelligence_available or has_topic_knowledge:
            phases = "phase2_only"
            reason = f"Phase 0 intent={intent} with cache - product finding only (fallback)"
        else:
            phases = "phase1_and_phase2"
            reason = f"Phase 0 intent={intent} without cache - need both phases (fallback)"
    elif intent == "informational":
        phases = "phase1_only"
        reason = f"Phase 0 intent={intent} - research only (fallback)"
    else:
        # PRIORITY 2: Keyword matching only if Phase 0 intent is unknown
        query_lower = query.lower()
        informational_keywords = ["what is", "how does", "tell me about", "learn about", "explain", "research"]
        commerce_keywords = ["buy", "purchase", "for sale", "cheapest", "price", "cost", "where to get", "find me"]

        is_informational = any(kw in query_lower for kw in informational_keywords)
        is_commerce = any(kw in query_lower for kw in commerce_keywords)

        if is_informational and not is_commerce:
            phases = "phase1_only"
            reason = "Informational keywords detected (fallback rule)"
        elif is_commerce or has_topic_knowledge:
            if cached_intelligence_available or has_topic_knowledge:
                phases = "phase2_only"
                reason = "Commerce keywords + cache available (fallback rule)"
            else:
                phases = "phase1_and_phase2"
                reason = "Commerce keywords, no cache (fallback rule)"
        else:
            # Default to full research for unknown queries
            phases = "phase1_and_phase2"
            reason = "Unknown intent - using full research (fallback rule)"

    # Build config based on phases
    if phases == "phase1_only":
        config = {
            "skip_phase1": False,
            "execute_phase2": False,
            "max_sources_phase1": 10,
            "max_sources_phase2": 0
        }
    elif phases == "phase2_only":
        config = {
            "skip_phase1": True,
            "execute_phase2": True,
            "max_sources_phase1": 0,
            "max_sources_phase2": 12
        }
    else:  # phase1_and_phase2
        config = {
            "skip_phase1": False,
            "execute_phase2": True,
            "max_sources_phase1": 8,
            "max_sources_phase2": 12
        }

    logger.info(f"[PhaseSelector] Fallback: {phases.upper()} - {reason}")

    return {
        "phases": phases,
        "confidence": 0.7,  # Lower confidence for fallback
        "reason": reason,
        "config": config
    }
