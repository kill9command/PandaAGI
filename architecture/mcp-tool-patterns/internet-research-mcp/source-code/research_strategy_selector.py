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

# Prompt templates directory
QUERY_PROMPTS_DIR = Path(__file__).parent.parent / "apps" / "prompts" / "query"


def _load_query_prompt(prompt_name: str) -> str:
    """Load a prompt template from the query prompts directory."""
    prompt_path = QUERY_PROMPTS_DIR / f"{prompt_name}.md"
    if prompt_path.exists():
        return prompt_path.read_text()
    else:
        logger.warning(f"[StrategySelector] Query prompt file not found: {prompt_path}")
        return ""


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
1. Informational intent ("what is", "how does", "learn about") -> PHASE1_ONLY
2. Commerce intent + cached_intelligence_available=True -> PHASE2_ONLY
3. Commerce intent + cached_intelligence_available=False -> PHASE1_AND_PHASE2

Output JSON ONLY (no other text)."""

    # Build full prompt with dynamic data
    prompt = f"""{base_prompt}

## Current Request

QUERY: "{query}"

SESSION CONTEXT:
- Cached intelligence available: {cached_intelligence_available}
- Session ID: {session_id}
- User preference: {pref_text}
- Query type hint: {user_preferences.get('query_type', 'unknown') if user_preferences else 'unknown'}

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

        # Fallback logic if LLM fails
        return _fallback_strategy_selection(query, cached_intelligence_available, knowledge_context)


def _fallback_strategy_selection(
    query: str,
    cached_intelligence_available: bool,
    knowledge_context: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Rule-based fallback if LLM phase selection fails.

    Logic:
    - Informational keywords → phase1_only
    - Commerce + topic knowledge → phase2_only
    - Commerce + cached intel → phase2_only
    - Commerce + no cached intel → phase1_and_phase2
    """
    query_lower = query.lower()

    # Check for informational intent
    informational_keywords = ["what is", "how does", "tell me about", "learn about", "explain", "research"]
    is_informational = any(kw in query_lower for kw in informational_keywords)

    # Check for topic knowledge from knowledge_retriever
    has_topic_knowledge = False
    if knowledge_context:
        has_topic_knowledge = knowledge_context.get("phase1_skip_recommended", False)

    if is_informational:
        phases = "phase1_only"
        reason = "Informational query - research only (fallback rule)"
        config = {
            "skip_phase1": False,
            "execute_phase2": False,
            "max_sources_phase1": 10,
            "max_sources_phase2": 0
        }
    elif has_topic_knowledge:
        # Knowledge retriever recommends skipping Phase 1
        phases = "phase2_only"
        reason = "Knowledge retriever recommends skip Phase 1 (fallback rule)"
        config = {
            "skip_phase1": True,
            "execute_phase2": True,
            "max_sources_phase1": 0,
            "max_sources_phase2": 12
        }
    elif cached_intelligence_available:
        phases = "phase2_only"
        reason = "Cached intelligence available - skip Phase 1 (fallback rule)"
        config = {
            "skip_phase1": True,
            "execute_phase2": True,
            "max_sources_phase1": 0,
            "max_sources_phase2": 10
        }
    else:
        phases = "phase1_and_phase2"
        reason = "No cached intelligence - need both phases (fallback rule)"
        config = {
            "skip_phase1": False,
            "execute_phase2": True,
            "max_sources_phase1": 10,
            "max_sources_phase2": 12
        }

    logger.info(f"[PhaseSelector] Fallback: {phases.upper()} - {reason}")

    return {
        "phases": phases,
        "confidence": 0.7,  # Lower confidence for fallback
        "reason": reason,
        "config": config
    }
