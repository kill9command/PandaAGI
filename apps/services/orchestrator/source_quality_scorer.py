"""
orchestrator/source_quality_scorer.py

LLM-first source quality scoring with reliability blending.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from apps.services.orchestrator.shared_state.source_reliability import (
    RELIABILITY_CONFIG,
    get_tracker,
)

logger = logging.getLogger(__name__)

# Prompt cache for recipe-loaded prompts
_prompt_cache: Dict[str, str] = {}


def _load_prompt_via_recipe(recipe_name: str, category: str = "filtering") -> str:
    """Load prompt via recipe system with inline fallback."""
    cache_key = f"{category}/{recipe_name}"
    if cache_key in _prompt_cache:
        return _prompt_cache[cache_key]
    try:
        from libs.gateway.recipe_loader import load_recipe
        recipe = load_recipe(f"{category}/{recipe_name}")
        content = recipe.get_prompt()
        _prompt_cache[cache_key] = content
        logger.info(f"[SourceQualityScorer] Loaded prompt from recipe {cache_key}")
        return content
    except Exception as e:
        logger.warning(f"Recipe {cache_key} not found: {e}")
        return ""


def _load_source_quality_scorer_prompt() -> str:
    """Load the source quality scorer prompt via recipe system."""
    prompt = _load_prompt_via_recipe("source_quality_scorer", "filtering")
    if not prompt:
        logger.warning("[SourceQualityScorer] Prompt not found via recipe, using fallback")
        prompt = "Score search results for source quality. Return JSON with results array containing index, source_type, llm_quality_score, confidence, and reasoning."
    return prompt

DEFAULT_OVERRIDE_PATH = "panda_system_docs/source_policy_overrides.json"

SOURCE_TYPES = [
    "official",
    "expert_review",
    "forum",
    "vendor",
    "news",
    "video",
    "social",
    "unknown",
]


def _repair_json(text: str) -> str:
    """Attempt to repair common LLM JSON errors."""
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    text = re.sub(r"\}(\s*)\{", r"},\1{", text)
    text = re.sub(r"\"(\s*)\{", r"\",\1{", text)
    text = re.sub(r"\}(\s*)\"", r"},\1\"", text)
    text = re.sub(r"\](\s*)\"", r"],\1\"", text)
    text = re.sub(r"(\d)(\s*)\"(\w+)\":", r"\1,\2\"\3\":", text)
    text = re.sub(r"(true|false|null)(\s*)\"(\w+)\":", r"\1,\2\"\3\":", text)
    return text


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split("/")[0]
        domain = domain.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


@dataclass
class SourceQualityResult:
    index: int
    source_type: str
    llm_quality_score: float
    confidence: float
    reasoning: str


class SourceQualityScorer:
    """LLM-first scoring with reliability blend and policy overrides."""

    def __init__(self, override_path: Optional[str] = None):
        self.override_path = override_path or DEFAULT_OVERRIDE_PATH
        self._override_cache: Optional[Dict[str, List[str]]] = None

    def _load_overrides(self) -> Dict[str, List[str]]:
        if self._override_cache is not None:
            return self._override_cache

        overrides = {"block": [], "allow": []}
        try:
            if os.path.exists(self.override_path):
                with open(self.override_path, "r") as f:
                    data = json.load(f)
                overrides["block"] = data.get("block", []) or []
                overrides["allow"] = data.get("allow", []) or []
        except Exception as e:
            logger.warning(f"[SourceQuality] Failed to load overrides: {e}")

        self._override_cache = overrides
        return overrides

    def _override_action(self, domain: str) -> Optional[str]:
        overrides = self._load_overrides()
        domain = domain.lower()
        for blocked in overrides.get("block", []):
            if domain == _extract_domain(blocked):
                return "block"
        for allowed in overrides.get("allow", []):
            if domain == _extract_domain(allowed):
                return "allow"
        return None

    async def score_candidates(
        self,
        candidates: List[Dict[str, Any]],
        query: str,
        goal: str,
        key_requirements: Optional[List[str]] = None,
        model_url: Optional[str] = None,
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        model_url = model_url or os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        model_id = model_id or os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        api_key = api_key or os.getenv("SOLVER_API_KEY", "qwen-local")

        requirements_text = ""
        if key_requirements:
            requirements_text = f"\nKey requirements: {', '.join(key_requirements[:6])}"

        candidate_lines = []
        for i, c in enumerate(candidates, 1):
            candidate_lines.append(
                f"{i}. URL: {c.get('url', 'N/A')}\n"
                f"   Title: {c.get('title', 'N/A')}\n"
                f"   Snippet: {c.get('snippet', 'N/A')[:160]}"
            )

        # Load base prompt from file
        base_prompt = _load_source_quality_scorer_prompt()

        prompt = f"""{base_prompt}

---

## Current Task

**Goal:** {goal}
**Original query:** {query}{requirements_text}

**Candidates:**
{chr(10).join(candidate_lines)}

Score each candidate."""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    model_url,
                    json={
                        "model": model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 1200,
                    },
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                response.raise_for_status()
                result = response.json()

            llm_content = result["choices"][0]["message"]["content"].strip()
            if "```json" in llm_content:
                llm_content = llm_content.split("```json")[1].split("```")[0].strip()
            elif "```" in llm_content:
                llm_content = llm_content.split("```")[1].split("```")[0].strip()

            try:
                parsed = json.loads(llm_content)
            except json.JSONDecodeError:
                parsed = json.loads(_repair_json(llm_content))

            results = parsed.get("results", [])
            # Log LLM reasoning for debugging
            for r in results:
                logger.info(f"[SourceQuality] LLM scored idx={r.get('index')} score={r.get('llm_quality_score')} reason={r.get('reasoning', '')[:100]}")
        except Exception as e:
            logger.warning(f"[SourceQuality] LLM scoring failed: {e}")
            results = []

        result_by_index: Dict[int, SourceQualityResult] = {}
        for entry in results:
            try:
                idx = int(entry.get("index", 0))
            except (TypeError, ValueError):
                continue
            source_type = entry.get("source_type", "unknown")
            if source_type not in SOURCE_TYPES:
                source_type = "unknown"
            result_by_index[idx] = SourceQualityResult(
                index=idx,
                source_type=source_type,
                llm_quality_score=float(entry.get("llm_quality_score", 0.5)),
                confidence=float(entry.get("confidence", 0.5)),
                reasoning=str(entry.get("reasoning", "")),
            )

        tracker = get_tracker()
        scored: List[Dict[str, Any]] = []

        for i, candidate in enumerate(candidates, 1):
            url = candidate.get("url", "")
            domain = _extract_domain(url)
            override_action = self._override_action(domain) if domain else None
            llm_result = result_by_index.get(i, SourceQualityResult(
                index=i,
                source_type="unknown",
                llm_quality_score=0.5,
                confidence=0.4,
                reasoning="Default score (LLM unavailable).",
            ))

            stats = tracker.get_domain_stats(domain) if domain else None
            reliability_score = tracker.get_reliability(domain) if domain else RELIABILITY_CONFIG["default_reliability"]
            total_samples = stats.total_extractions if stats else 0

            if total_samples < RELIABILITY_CONFIG["min_samples"]:
                quality_score = llm_result.llm_quality_score
            else:
                quality_score = 0.6 * llm_result.llm_quality_score + 0.4 * reliability_score

            if override_action == "block":
                quality_score = 0.0
            elif override_action == "allow":
                quality_score = max(0.9, quality_score)

            enriched = candidate.copy()
            enriched.update({
                "source_type": llm_result.source_type,
                "quality_score": round(float(quality_score), 4),
                "quality_confidence": round(float(llm_result.confidence), 4),
                "quality_reasoning": llm_result.reasoning,
                "llm_quality_score": round(float(llm_result.llm_quality_score), 4),
                "reliability_score": round(float(reliability_score), 4),
                "override_action": override_action,
            })
            scored.append(enriched)

        return scored


_scorer_instance: Optional[SourceQualityScorer] = None


def get_source_quality_scorer() -> SourceQualityScorer:
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = SourceQualityScorer()
    return _scorer_instance
