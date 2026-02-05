"""
LLM-Assisted Context Extraction

Uses LLM to extract implicit preferences, topics, and entities from user messages.
Supplements regex patterns with semantic understanding for 95%+ capture rate.

Author: Pandora Team
Created: 2025-11-10
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import httpx
import json
import re
import logging

from libs.gateway.llm.recipe_loader import load_recipe, RecipeNotFoundError

logger = logging.getLogger(__name__)

# Cache for loaded prompts from recipes
_prompt_cache: Dict[str, str] = {}


def _load_prompt_from_recipe(recipe_name: str) -> str:
    """
    Load prompt from recipe.

    Args:
        recipe_name: Recipe path (e.g., "memory/preference_extractor")

    Returns:
        Prompt content from recipe, or empty string if not found
    """
    if recipe_name in _prompt_cache:
        return _prompt_cache[recipe_name]

    try:
        recipe = load_recipe(recipe_name)
        content = recipe.get_prompt()
        _prompt_cache[recipe_name] = content
        return content
    except RecipeNotFoundError:
        logger.warning(f"[LLMExtractor] Recipe not found: {recipe_name}")
        return ""
    except Exception as e:
        logger.warning(f"[LLMExtractor] Failed to load recipe {recipe_name}: {e}")
        return ""


@dataclass
class ExtractionResult:
    """Result from LLM extraction"""
    preferences: Dict[str, str]
    topic: Optional[str]
    entities: List[str]  # Extracted entities (products, locations, etc.)
    confidence: float  # 0-1 confidence score
    reasoning: str  # Why these extractions were made


class LLMExtractor:
    """LLM-based context extraction (supplements regex)"""

    def __init__(self, model_url: str, model_id: str, api_key: str):
        self.model_url = model_url
        self.model_id = model_id
        self.api_key = api_key
        self.cache = {}  # Simple cache for identical queries

        logger.info(f"[LLMExtractor] Initialized with model {model_id}")

    async def extract_from_message(
        self,
        user_msg: str,
        conversation_context: Optional[str] = None,
        fallback_to_regex: bool = True
    ) -> ExtractionResult:
        """
        Extract preferences, topic, and entities using LLM.

        Args:
            user_msg: User message to extract from
            conversation_context: Optional conversation context
            fallback_to_regex: If True, fall back to regex on LLM failure

        Returns:
            ExtractionResult with extracted data
        """
        # Check cache
        cache_key = f"{user_msg}:{conversation_context}"
        if cache_key in self.cache:
            logger.debug(f"[LLMExtractor] Cache hit for message")
            return self.cache[cache_key]

        # Build extraction prompt
        prompt = self._build_extraction_prompt(user_msg, conversation_context)

        # Call LLM
        try:
            llm_response = await self._call_llm(prompt)
            result = self._parse_extraction_result(llm_response)

            # Cache result
            self.cache[cache_key] = result

            logger.info(f"[LLMExtractor] Extracted {len(result.preferences)} preferences (confidence: {result.confidence:.2f})")
            return result

        except Exception as e:
            logger.error(f"[LLMExtractor] Extraction failed: {e}")
            # Fallback to regex if enabled
            if fallback_to_regex:
                from apps.services.gateway.context_extractors import (
                    extract_preferences,
                    extract_topic
                )
                return ExtractionResult(
                    preferences=extract_preferences(user_msg),
                    topic=extract_topic(user_msg),
                    entities=[],
                    confidence=0.6,  # Lower confidence for regex
                    reasoning="LLM extraction failed, used regex fallback"
                )
            raise

    def _build_extraction_prompt(
        self,
        user_msg: str,
        conversation_context: Optional[str]
    ) -> str:
        """Build prompt for extraction"""
        # Load base prompt from recipe
        base_prompt = _load_prompt_from_recipe("memory/preference_extractor")
        if not base_prompt:
            # Fallback inline prompt if file not found
            base_prompt = """You are a context extraction specialist. Extract structured information from user messages.

Extract: Preferences, Topic, Entities, Confidence (0.0-1.0), Reasoning.

Output ONLY valid JSON:
{"preferences": {}, "topic": "...", "entities": [], "confidence": 0.0-1.0, "reasoning": "..."}"""

        context_section = ""
        if conversation_context:
            context_section = f"""
Previous Context:
{conversation_context}
"""

        return f"""{base_prompt}

---
{context_section}
User Message: "{user_msg}"

Now extract from the user message above. Output ONLY the JSON, no other text."""

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM for extraction"""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self.model_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 300,
                    "temperature": 0.2  # Low temp for consistent extraction
                }
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]

    def _parse_extraction_result(self, llm_output: str) -> ExtractionResult:
        """Parse LLM JSON output into ExtractionResult"""
        # Try to extract JSON from response
        json_match = re.search(r'\{.*\}', llm_output, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON found in LLM output: {llm_output}")

        json_str = json_match.group(0)
        data = json.loads(json_str)

        return ExtractionResult(
            preferences=data.get("preferences", {}),
            topic=data.get("topic"),
            entities=data.get("entities", []),
            confidence=float(data.get("confidence", 0.5)),
            reasoning=data.get("reasoning", "No reasoning provided")
        )

    def clear_cache(self):
        """Clear extraction cache"""
        self.cache.clear()
        logger.info("[LLMExtractor] Cache cleared")


# Global LLM extractor (initialized by Gateway)
_llm_extractor: Optional[LLMExtractor] = None


def set_llm_extractor(extractor: LLMExtractor):
    """Set the global LLM extractor"""
    global _llm_extractor
    _llm_extractor = extractor


def get_llm_extractor() -> Optional[LLMExtractor]:
    """Get the global LLM extractor"""
    return _llm_extractor
