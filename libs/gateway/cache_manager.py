"""
Cache Manager Gate

Pre-Guide gate that evaluates cache eligibility and decides cache reuse strategy.

Position in fractal reflection:
- Meta-Reflection: "Can I proceed?" (confidence gate)
- Cache Manager: "Can I reuse?" (efficiency gate) ← THIS
- Guide: "What should I create?" (strategy gate)

Token budget: ~250 tokens per call
Latency: ~200ms (accepted trade-off for intelligent decisions)
"""
import logging
import re
from typing import Dict, Any, Optional
from dataclasses import dataclass

from libs.gateway.recipe_loader import load_recipe

logger = logging.getLogger(__name__)


@dataclass
class CacheDecision:
    """Cache Manager decision"""
    decision: str  # "use_response_cache" | "use_claims" | "proceed_to_guide"
    cache_source: Optional[str]  # "response" | "claims" | None
    reasoning: str
    confidence: float  # 0.0-1.0


@dataclass
class CacheStatus:
    """Status of all cache layers"""
    has_potential: bool
    response_cache: Optional[Dict[str, Any]]
    claims_cache: Optional[Dict[str, Any]]
    tool_cache: Optional[Dict[str, Any]]


class CacheManagerGate:
    """
    Pre-Guide gate that evaluates cache eligibility.

    Design:
    - Checks all 3 cache layers (response, claims, tools)
    - Makes intelligent decision with lightweight LLM call (250 tokens)
    - Bypasses cache for multi-goal queries and low-confidence intents
    """

    def __init__(self, llm_client=None):
        """
        Initialize Cache Manager Gate.

        Args:
            llm_client: LLM client for cache evaluation (optional, will use default)
        """
        self.llm_client = llm_client

    async def evaluate_cache(
        self,
        query: str,
        intent: str,
        intent_confidence: float,
        cache_status: CacheStatus,
        session_context: dict,
        is_multi_goal: bool = False
    ) -> CacheDecision:
        """
        Lightweight LLM call to decide cache reuse.

        Token budget: ~250 tokens
        Latency: ~200ms (accepted trade-off for intelligent decisions)

        Args:
            query: User query
            intent: Detected intent (transactional/informational/etc)
            intent_confidence: Confidence in intent classification (0-1)
            cache_status: Status of all cache layers
            session_context: Session context
            is_multi_goal: Whether query has multiple distinct goals

        Returns:
            CacheDecision with strategy and reasoning
        """
        # FAST BYPASS #0: Recall/follow-up queries (context-dependent, must not cache)
        recall_patterns = [
            'why did you', 'why those', 'why that', 'explain your choice',
            'tell me more about', 'more about the', 'the first one', 'the second one',
            'the cheapest one', 'those options', 'that option', 'your recommendation',
            'why did you choose', 'why did you pick', 'how did you decide',
            'what was the', 'which one', 'you mentioned', 'you said', 'you recommended'
        ]
        query_lower = query.lower()
        if any(pattern in query_lower for pattern in recall_patterns):
            logger.info(f"[CacheManager] Bypass: Recall/follow-up query detected (context-dependent)")
            return CacheDecision(
                decision="proceed_to_guide",
                cache_source=None,
                reasoning="Recall query is context-dependent and must not be cached",
                confidence=0.99
            )

        # FAST BYPASS #1: Explicit cache bypass signals (retry/refresh)
        retry_keywords = ['retry', 'try again', 'refresh', 'redo', 'rerun', 'again', 'once more']
        if any(keyword in query_lower for keyword in retry_keywords):
            logger.info(f"[CacheManager] Bypass: Retry keyword detected in query")

            # Extract previous action context to help Guide understand what to retry
            retry_context = ""
            recent_actions = session_context.get("recent_actions", [])
            current_topic = session_context.get("current_topic", "")

            if recent_actions and isinstance(recent_actions, list) and len(recent_actions) > 0:
                # Get the most recent action that involved tools
                last_action = recent_actions[0]
                if isinstance(last_action, dict):
                    prev_tools = last_action.get("tools", [])  # Correct field name

                    # Use current_topic as the previous query context
                    if current_topic and prev_tools:
                        retry_context = f"Previous query context: '{current_topic}' (tools: {', '.join(prev_tools)})"
                        logger.info(f"[CacheManager] Retry context found: {retry_context}")
                    elif current_topic:
                        # Has topic but no tools - still useful context
                        retry_context = f"Previous query context: '{current_topic}'"
                        logger.info(f"[CacheManager] Retry context found (no tools): {retry_context}")
                    else:
                        logger.info(f"[CacheManager] No topic found for retry context")

            reasoning = "User explicitly requested fresh execution (retry/refresh)"
            if retry_context:
                reasoning += f". {retry_context}"

            return CacheDecision(
                decision="proceed_to_guide",
                cache_source=None,
                reasoning=reasoning,
                confidence=0.99
            )

        # FAST BYPASS #1: Low-confidence intent classification
        if intent_confidence < 0.3:
            logger.info(f"[CacheManager] Bypass: Low intent confidence ({intent_confidence:.2f})")
            return CacheDecision(
                decision="proceed_to_guide",
                cache_source=None,
                reasoning=f"Intent confidence too low ({intent_confidence:.2f})",
                confidence=0.95
            )

        # FAST BYPASS #2: Multi-goal queries
        if is_multi_goal:
            logger.info("[CacheManager] Bypass: Multi-goal query detected")
            return CacheDecision(
                decision="proceed_to_guide",
                cache_source=None,
                reasoning="Multi-goal query requires separate subtasks",
                confidence=0.95
            )

        # FAST BYPASS #3: No cache potential
        if not cache_status.has_potential:
            logger.info("[CacheManager] Bypass: No cache data available")
            return CacheDecision(
                decision="proceed_to_guide",
                cache_source=None,
                reasoning="No cached data available",
                confidence=0.95
            )

        # BUILD EVALUATION PROMPT (Concise, 250 tokens)
        prompt = self._build_evaluation_prompt(
            query=query,
            intent=intent,
            cache_status=cache_status,
            session_context=session_context
        )

        # CALL LLM FOR EVALUATION
        try:
            if self.llm_client:
                response = await self._call_llm(prompt)
                decision_data = self._parse_llm_response(response, query)
            else:
                # Fallback: Use heuristic if no LLM available
                decision_data = self._heuristic_decision(cache_status, query)

            return CacheDecision(**decision_data)

        except Exception as e:
            logger.error(f"[CacheManager] LLM call failed: {e}, using heuristic fallback")
            decision_data = self._heuristic_decision(cache_status, query)
            return CacheDecision(**decision_data)

    def _build_evaluation_prompt(
        self,
        query: str,
        intent: str,
        cache_status: CacheStatus,
        session_context: dict
    ) -> str:
        """
        Build concise cache evaluation prompt (250 tokens target).
        """
        # Build response cache status string
        if cache_status.response_cache and cache_status.response_cache.get("hit"):
            rc = cache_status.response_cache
            status = "FRESH" if rc.get("status") == "fresh" else "STALE"
            response_cache_status = f"""- Match: "{rc.get('cached_query', '')[:60]}..."
- Similarity: {rc.get('hybrid_score', rc.get('similarity', 0)):.2f}
- Age: {rc.get('age_hours', 0):.1f}h / TTL: {rc.get('ttl_hours', 0)}h ({status})
- Quality: {rc.get('quality_score', 0):.2f}
- Intent match: {rc.get('intent_match', True)}"""
        else:
            response_cache_status = "- No match"

        # Build claims cache status string
        if cache_status.claims_cache:
            cc = cache_status.claims_cache
            claims_cache_status = f"""- Coverage: {cc.get('coverage_score', 0):.2f} (>0.80 = high)
- Claims: {cc.get('num_claims', 0)} relevant claims"""
        else:
            claims_cache_status = "- No claims"

        # Load and format the prompt template
        try:
            recipe = load_recipe("memory/cache_decision")
            prompt_template = recipe.get_prompt()
        except Exception as e:
            logger.warning(f"Failed to load cache_decision recipe: {e}")
            prompt_template = ""
        if prompt_template:
            return prompt_template.format(
                query=query,
                intent=intent,
                domain=session_context.get('domain', 'unknown'),
                preference_count=len(session_context.get('preferences', {})),
                response_cache_status=response_cache_status,
                claims_cache_status=claims_cache_status
            )

        # Fallback: inline prompt if file not found
        return f"""You are the Cache Manager. Decide if cached data can satisfy the user's request.

## User Query
"{query}"

## Session Context
- Intent: {intent}
- Domain: {session_context.get('domain', 'unknown')}
- User preferences: {len(session_context.get('preferences', {}))} stored

## Cache Status

**Layer 1: Response Cache (User-Specific)**
{response_cache_status}

**Layer 2: Claims Registry (Shared)**
{claims_cache_status}

## Decision

Evaluate: semantic match, freshness, quality vs staleness trade-off, intent alignment

Output ONE of:
- "use_response_cache" (L1 hit, return cached response)
- "use_claims" (L2 sufficient, synthesize from claims)
- "proceed_to_guide" (insufficient, need fresh search)

JSON:
{{
  "decision": "use_response_cache|use_claims|proceed_to_guide",
  "cache_source": "response|claims|none",
  "reasoning": "<1 sentence>",
  "confidence": 0.0-1.0
}}
"""

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM for cache evaluation"""
        # This would be implemented to call the actual LLM
        # For now, return None to trigger heuristic fallback
        return None

    def _parse_llm_response(self, response: str, query: str = "") -> dict:
        """Parse LLM JSON response"""
        import json
        try:
            return json.loads(response)
        except:
            return self._heuristic_decision(None, query)

    def _heuristic_decision(self, cache_status: Optional[CacheStatus], query: str = "") -> dict:
        """
        Fallback heuristic decision if LLM unavailable.

        Rules:
        - Fresh response cache (age < TTL, quality >= 0.70) → use_response_cache
          UNLESS: action verb + failed search (bypass for fresh search)
        - High claims coverage (>= 0.80) → use_claims
        - Otherwise → proceed_to_guide
        """
        if not cache_status:
            return {
                "decision": "proceed_to_guide",
                "cache_source": None,
                "reasoning": "No cache status available",
                "confidence": 0.5
            }

        # Check response cache
        if cache_status.response_cache and cache_status.response_cache.get("hit"):
            rc = cache_status.response_cache
            is_fresh = rc.get("status") == "fresh"
            quality_ok = rc.get("quality_score", 0) >= 0.70

            if is_fresh and quality_ok:
                # RETRY DETECTION (HIGHEST PRIORITY): Explicit retry keywords
                query_lower = query.lower()
                retry_keywords = ["retry", "refresh", "search again", "try again", "new search",
                                  "fresh search", "re-search", "redo", "re-do"]
                is_explicit_retry = any(keyword in query_lower for keyword in retry_keywords)

                if is_explicit_retry:
                    logger.info(
                        f"[CacheManager-Heuristic] RETRY DETECTED - bypassing cache: "
                        f"explicit retry keyword found in query"
                    )
                    return {
                        "decision": "proceed_to_guide",
                        "cache_source": None,
                        "reasoning": "Explicit retry intent - user wants fresh data",
                        "confidence": 0.95,
                        "is_retry": True  # NEW: Expose retry detection flag
                    }

                # ADDITIONAL CHECK: Detect action verbs + failed search
                action_verbs = ["find", "search", "get", "look for", "show me", "fetch"]
                has_action_verb = any(verb in query_lower for verb in action_verbs)

                # Check if cached response is a failed search
                cached_response = rc.get("response", "")
                failed_search_indicators = [
                    "couldn't find any",
                    "no results found",
                    "no offers found",
                    "no current listings",
                    "no matches found",
                    "I couldn't find",
                    "I don't see",
                    "don't see specific",
                    "I don't have specific",
                    "0 offer(s) found"
                ]
                is_failed_search = any(indicator in cached_response.lower() for indicator in failed_search_indicators)

                # BYPASS: Action verb + failed search = user wants fresh search
                if has_action_verb and is_failed_search:
                    logger.info(
                        f"[CacheManager-Heuristic] Bypassing cache: "
                        f"action verb detected + cached response is failed search"
                    )
                    return {
                        "decision": "proceed_to_guide",
                        "cache_source": None,
                        "reasoning": "Action query with failed cached search - performing fresh search",
                        "confidence": 0.90,
                        "is_retry": False  # Implicit retry (inferred from context)
                    }

                logger.info(f"[CacheManager-Heuristic] Using response cache (fresh + quality)")
                return {
                    "decision": "use_response_cache",
                    "cache_source": "response",
                    "reasoning": f"Fresh cache hit with quality {rc.get('quality_score', 0):.2f}",
                    "confidence": 0.85
                }

        # Check claims coverage
        if cache_status.claims_cache:
            coverage = cache_status.claims_cache.get("coverage_score", 0)
            if coverage >= 0.80:
                logger.info(f"[CacheManager-Heuristic] Using claims (coverage={coverage:.2f})")
                return {
                    "decision": "use_claims",
                    "cache_source": "claims",
                    "reasoning": f"High claims coverage ({coverage:.2f})",
                    "confidence": 0.75
                }

        # Default: proceed to guide
        logger.info("[CacheManager-Heuristic] Proceeding to guide (insufficient cache)")
        return {
            "decision": "proceed_to_guide",
            "cache_source": None,
            "reasoning": "Insufficient cache data",
            "confidence": 0.70
        }


def detect_multi_goal_query(query: str, use_llm_verify: bool = False) -> bool:
    """
    Detect multi-goal queries that MUST bypass cache.

    Per systemPatterns.md: multi-goal queries must be separated.

    Two-phase approach:
    1. Fast mechanical check (string matching)
    2. LLM verification if ambiguous (reduces false positives)

    Args:
        query: User query
        use_llm_verify: Use LLM to verify mechanical check

    Returns:
        True if query has multiple distinct goals
    """
    multi_goal_indicators = [
        "and also",
        "additionally",
        "plus",
        "as well as",
        "both",
        "also",
        "; ",  # Semicolon separator
    ]

    query_lower = query.lower()

    # Check for multiple action verbs (strong multi-goal signal)
    action_verbs = ["find", "get", "search", "buy", "show", "list", "tell", "explain"]
    verb_count = sum(1 for verb in action_verbs if verb in query_lower)

    # Phase 1: Mechanical check
    has_indicators = any(indicator in query_lower for indicator in multi_goal_indicators)
    mechanical_multi_goal = verb_count > 1 or has_indicators

    if not mechanical_multi_goal:
        return False  # Definitely single-goal

    if not use_llm_verify:
        logger.info(f"[MultiGoal] Mechanical detection: {query[:50]}...")
        return True  # Trust mechanical check

    # Phase 2: LLM verification (would be implemented)
    # For now, trust mechanical check
    logger.info(f"[MultiGoal] Detected (mechanical): {query[:50]}...")
    return True


# Global singleton
CACHE_MANAGER_GATE = CacheManagerGate()
