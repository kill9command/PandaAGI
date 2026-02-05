"""
Context Summarization - LLM-based compression for long sessions

Intelligently compresses accumulated facts, actions, and context data
when approaching token limits. Uses LLM to create natural language summaries
that preserve essential information while dramatically reducing token count.

Author: Panda Team
Created: 2025-11-10
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import httpx
import logging

from libs.gateway.llm.recipe_loader import load_recipe, RecipeNotFoundError

logger = logging.getLogger(__name__)

# Cache for loaded prompts from recipes
_prompt_cache: Dict[str, str] = {}


def _load_prompt_from_recipe(recipe_name: str) -> str:
    """
    Load prompt from recipe.

    Args:
        recipe_name: Recipe path (e.g., "memory/fact_summarizer")

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
        logger.warning(f"[ContextSummarizer] Recipe not found: {recipe_name}")
        return ""
    except Exception as e:
        logger.warning(f"[ContextSummarizer] Failed to load recipe {recipe_name}: {e}")
        return ""


@dataclass
class SummarizationConfig:
    """Configuration for context summarization"""
    max_facts_before_summarization: int = 20  # Per domain
    max_actions_before_summarization: int = 10
    target_compression_ratio: float = 0.4  # Compress to 40% of original
    staleness_threshold_hours: int = 24  # Mark facts older than this as stale
    min_confidence_to_keep: float = 0.5  # Drop low-confidence facts


@dataclass
class SummarizedFacts:
    """Result of fact summarization"""
    summary: str  # Compressed natural language summary
    key_points: List[str]  # Critical facts to preserve verbatim
    dropped_count: int  # How many facts were dropped
    compression_ratio: float  # Actual compression achieved


class ContextSummarizer:
    """LLM-based context summarization for long sessions"""

    def __init__(self, model_url: str, model_id: str, api_key: str):
        self.model_url = model_url
        self.model_id = model_id
        self.api_key = api_key
        self.config = SummarizationConfig()

        logger.info(f"[ContextSummarizer] Initialized with model {model_id}")

    async def should_summarize(self, live_ctx: 'LiveSessionContext') -> bool:
        """
        Check if context needs summarization.

        Criteria:
        - Total facts > threshold
        - Actions > threshold
        - Estimated tokens > 600 (approaching 500 token budget)

        Args:
            live_ctx: LiveSessionContext to check

        Returns:
            True if summarization needed
        """
        # Count total facts across all domains
        total_facts = sum(len(facts) for facts in live_ctx.discovered_facts.values())

        if total_facts > self.config.max_facts_before_summarization:
            logger.info(f"[ContextSummarizer] Summarization needed: {total_facts} facts > {self.config.max_facts_before_summarization}")
            return True

        # Check if actions list is too long
        if len(live_ctx.recent_actions) > self.config.max_actions_before_summarization:
            logger.info(f"[ContextSummarizer] Summarization needed: {len(live_ctx.recent_actions)} actions > {self.config.max_actions_before_summarization}")
            return True

        # Check estimated token count
        context_block = live_ctx.to_context_block(max_tokens=1000)
        estimated_tokens = len(context_block.split()) * 1.3  # Rough estimate
        if estimated_tokens > 600:  # Approaching 500 token limit
            logger.info(f"[ContextSummarizer] Summarization needed: {estimated_tokens:.0f} tokens > 600")
            return True

        return False

    async def summarize_facts(
        self,
        facts_by_domain: Dict[str, List[str]],
        session_context: str
    ) -> Dict[str, SummarizedFacts]:
        """
        Summarize facts per domain using LLM.

        Args:
            facts_by_domain: Dict of domain -> list of facts
            session_context: Brief session context for LLM

        Returns:
            Dict of domain -> SummarizedFacts
        """
        summarized = {}

        for domain, facts in facts_by_domain.items():
            if len(facts) <= 5:
                # Don't summarize small fact sets
                continue

            try:
                # Call LLM to summarize
                prompt = self._build_summarization_prompt(domain, facts, session_context)
                summary_result = await self._call_llm(prompt)

                summarized[domain] = self._parse_summary_result(summary_result, facts)
                logger.info(f"[ContextSummarizer] Summarized {domain}: {len(facts)} facts → {summarized[domain].compression_ratio:.1%} size")

            except Exception as e:
                logger.error(f"[ContextSummarizer] Failed to summarize {domain}: {e}")
                # Skip summarization for this domain on error
                continue

        return summarized

    def _build_summarization_prompt(
        self,
        domain: str,
        facts: List[str],
        session_context: str
    ) -> str:
        """Build prompt for fact summarization"""
        # Load base prompt from recipe
        base_prompt = _load_prompt_from_recipe("memory/fact_summarizer")
        if not base_prompt:
            # Fallback inline prompt if file not found
            base_prompt = """You are a context compression specialist. Summarize facts about a domain into a concise summary that preserves essential information.

Instructions:
1. Create a 2-3 sentence summary capturing the core information
2. List 3-5 key facts that must be preserved verbatim (most important/recent)
3. Identify any contradictory or outdated facts

Output format:
SUMMARY: <concise summary>
KEY_FACTS:
- <critical fact 1>
- <critical fact 2>
- <critical fact 3>
DROPPED: <any facts that are outdated/contradictory>"""

        return f"""{base_prompt}

---

Domain: {domain}
Session Context: {session_context}

Facts to Summarize ({len(facts)} total):
{chr(10).join(f'{i+1}. {fact}' for i, fact in enumerate(facts))}

Begin:"""

    async def _call_llm(self, prompt: str) -> str:
        """
        Call LLM for summarization.

        Args:
            prompt: Summarization prompt

        Returns:
            LLM response text
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.model_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 500,
                        "temperature": 0.3  # Lower temp for consistent compression
                    }
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]

        except httpx.HTTPError as e:
            logger.error(f"[ContextSummarizer] HTTP error calling LLM: {e}")
            raise
        except Exception as e:
            logger.error(f"[ContextSummarizer] Error calling LLM: {e}")
            raise

    def _parse_summary_result(
        self,
        llm_output: str,
        original_facts: List[str]
    ) -> SummarizedFacts:
        """
        Parse LLM output into structured summary.

        Args:
            llm_output: LLM response text
            original_facts: Original fact list

        Returns:
            SummarizedFacts object
        """
        lines = llm_output.strip().split('\n')

        summary = ""
        key_points = []
        dropped_count = 0

        current_section = None
        for line in lines:
            line = line.strip()
            if line.startswith("SUMMARY:"):
                current_section = "summary"
                summary = line.replace("SUMMARY:", "").strip()
            elif line.startswith("KEY_FACTS:"):
                current_section = "key_facts"
            elif line.startswith("DROPPED:"):
                current_section = "dropped"
            elif current_section == "summary" and line:
                summary += " " + line
            elif current_section == "key_facts" and line.startswith("-"):
                key_points.append(line[1:].strip())
            elif current_section == "dropped" and line:
                # Rough count of dropped items
                dropped_count += line.count(',') + 1

        # Calculate compression
        original_tokens = sum(len(f.split()) for f in original_facts) * 1.3
        compressed_tokens = len(summary.split()) * 1.3 + sum(len(k.split()) for k in key_points) * 1.3
        compression_ratio = compressed_tokens / original_tokens if original_tokens > 0 else 1.0

        return SummarizedFacts(
            summary=summary,
            key_points=key_points,
            dropped_count=dropped_count,
            compression_ratio=compression_ratio
        )

    async def summarize_actions(
        self,
        actions: List[Dict],
        session_context: str
    ) -> str:
        """
        Summarize action history into concise narrative.

        Args:
            actions: List of action dicts
            session_context: Brief session context

        Returns:
            Concise summary sentence
        """
        if len(actions) <= 5:
            return ""  # No need to summarize

        # Load base prompt from recipe (falls back to inline if recipe not found)
        base_prompt = _load_prompt_from_recipe("memory/action_summarizer")
        if not base_prompt:
            # Fallback inline prompt if file not found
            base_prompt = """Summarize this sequence of user actions into a concise 1-2 sentence narrative.

Provide ONLY a concise summary sentence, no additional commentary."""

        prompt = f"""{base_prompt}

---

Session Context: {session_context}

Actions ({len(actions)} total):
{chr(10).join(f"{i+1}. {act.get('summary', str(act))}" for i, act in enumerate(actions))}

Summary:"""

        try:
            summary = await self._call_llm(prompt)
            # Clean up response
            summary = summary.strip().replace("Summary:", "").strip()
            logger.info(f"[ContextSummarizer] Summarized {len(actions)} actions")
            return summary
        except Exception as e:
            logger.error(f"[ContextSummarizer] Failed to summarize actions: {e}")
            return ""

    async def prune_stale_facts(
        self,
        live_ctx: 'LiveSessionContext'
    ) -> Dict[str, List[str]]:
        """
        Remove stale/low-confidence facts.

        Currently just returns all facts (staleness tracking not yet implemented).
        Future enhancement: Use fact timestamps and confidence scores.

        Args:
            live_ctx: LiveSessionContext

        Returns:
            Pruned facts dict
        """
        import time

        current_time = time.time()
        pruned_facts = {}

        for domain, facts in live_ctx.discovered_facts.items():
            fresh_facts = []

            for fact in facts:
                # In production, facts would have metadata (timestamp, confidence)
                # For now, we'll keep all facts but this is where pruning logic goes
                fresh_facts.append(fact)

            if fresh_facts:
                pruned_facts[domain] = fresh_facts

        return pruned_facts

    def get_stats(self) -> Dict[str, Any]:
        """Get summarizer statistics"""
        return {
            "config": {
                "max_facts_threshold": self.config.max_facts_before_summarization,
                "max_actions_threshold": self.config.max_actions_before_summarization,
                "target_compression": f"{self.config.target_compression_ratio:.0%}"
            },
            "model": {
                "url": self.model_url,
                "model_id": self.model_id
            }
        }
