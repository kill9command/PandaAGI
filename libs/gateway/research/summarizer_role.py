"""
Summarizer Role - Memory Write Layer

Handles two responsibilities:
1. Turn-level: Compress current turn -> turn_summary.json
2. Long-term: Write important facts to persistent memory storage

Author: Panda System Architecture
Date: 2025-11-27
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from libs.gateway.llm.recipe_loader import load_recipe, RecipeNotFoundError

logger = logging.getLogger(__name__)

# Memory storage base path
MEMORY_BASE = Path("panda_system_docs/memory")


@dataclass
class MemoryWrite:
    """A memory write instruction from the Summarizer"""
    doc_type: str  # user_preferences, user_facts, system_learnings, domain_knowledge
    section: str   # e.g., "## Shopping Preferences"
    entry: str     # e.g., "- Budget: $500 (high confidence)"
    confidence: str  # high, medium, low
    source: str    # What triggered this memory write


@dataclass
class TurnSummary:
    """Turn summary for immediate next turn"""
    short_summary: str
    key_findings: List[str]
    preferences_learned: List[str]
    topic: str
    satisfaction_estimate: float
    next_turn_hints: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "short_summary": self.short_summary,
            "key_findings": self.key_findings,
            "preferences_learned": self.preferences_learned,
            "topic": self.topic,
            "satisfaction_estimate": self.satisfaction_estimate,
            "next_turn_hints": self.next_turn_hints,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class SummarizerResult:
    """Result from running the Summarizer role"""
    turn_summary: TurnSummary
    memory_writes: List[MemoryWrite] = field(default_factory=list)
    memories_written: int = 0


def build_turn_summary_simple(
    user_query: str,
    answer: str,
    capsule: Optional[str] = None,
) -> TurnSummary:
    """
    Build turn summary without LLM (simple extraction).

    This is a fallback when LLM summarization is not available.

    Args:
        user_query: The user's question
        answer: The response given
        capsule: Optional capsule content

    Returns:
        TurnSummary
    """
    # Extract topic from query
    topic = "general"
    query_lower = user_query.lower()
    if any(w in query_lower for w in ["buy", "price", "cost", "shop", "purchase"]):
        topic = "commerce"
    elif any(w in query_lower for w in ["code", "file", "git", "function", "class"]):
        topic = "code"
    elif any(w in query_lower for w in ["research", "find", "search", "look"]):
        topic = "research"

    # Extract key findings from answer (first few sentences)
    sentences = re.split(r'[.!?]', answer)
    key_findings = [s.strip() for s in sentences[:3] if s.strip() and len(s.strip()) > 20]

    # Simple summary
    short_summary = sentences[0].strip() if sentences else "Query processed."
    if len(short_summary) > 150:
        short_summary = short_summary[:147] + "..."

    return TurnSummary(
        short_summary=short_summary,
        key_findings=key_findings,
        preferences_learned=[],
        topic=topic,
        satisfaction_estimate=0.7,  # Default estimate
        next_turn_hints=[]
    )


def detect_memory_writes(
    user_query: str,
    answer: str,
    capsule: Optional[str] = None,
) -> List[MemoryWrite]:
    """
    Detect potential memory writes from the turn.

    This uses simple heuristics. For LLM-driven detection, use run_summarizer_role().

    Args:
        user_query: The user's question
        answer: The response given
        capsule: Optional capsule content

    Returns:
        List of MemoryWrite instructions
    """
    writes = []
    query_lower = user_query.lower()

    # Detect explicit "remember" requests
    if "remember" in query_lower:
        # Extract what to remember
        match = re.search(r"remember\s+(?:that\s+)?(.+?)(?:\.|$)", user_query, re.IGNORECASE)
        if match:
            fact = match.group(1).strip()
            writes.append(MemoryWrite(
                doc_type="user_facts",
                section="## Other Facts",
                entry=f"- {fact} (explicit request)",
                confidence="high",
                source=f"User requested: '{user_query[:50]}...'"
            ))

    # Detect preference statements
    preference_patterns = [
        (r"i prefer\s+(.+?)(?:\.|,|$)", "high"),
        (r"i like\s+(.+?)(?:\.|,|$)", "medium"),
        (r"i don'?t like\s+(.+?)(?:\.|,|$)", "medium"),
        (r"my budget is\s+(.+?)(?:\.|,|$)", "high"),
        (r"i want\s+(.+?)(?:\.|,|$)", "low"),
    ]

    for pattern, confidence in preference_patterns:
        match = re.search(pattern, user_query, re.IGNORECASE)
        if match:
            preference = match.group(1).strip()
            writes.append(MemoryWrite(
                doc_type="user_preferences",
                section="## Other Preferences",
                entry=f"- {preference} ({confidence} confidence)",
                confidence=confidence,
                source=f"Detected in query: '{user_query[:50]}...'"
            ))

    # Detect location mentions
    location_patterns = [
        r"i live in\s+(.+?)(?:\.|,|$)",
        r"i'm in\s+(.+?)(?:\.|,|$)",
        r"i am in\s+(.+?)(?:\.|,|$)",
        r"near\s+(.+?)(?:\.|,|$)",
    ]

    for pattern in location_patterns:
        match = re.search(pattern, user_query, re.IGNORECASE)
        if match:
            location = match.group(1).strip()
            writes.append(MemoryWrite(
                doc_type="user_preferences",
                section="## Location Preferences",
                entry=f"- Location: {location} (from query)",
                confidence="high",
                source=f"Detected in query: '{user_query[:50]}...'"
            ))
            break  # Only capture one location

    return writes


async def run_summarizer_role(
    user_query: str,
    answer: str,
    capsule: Optional[str],
    llm_client,
    turn_dir: Path,
    use_llm: bool = True,
) -> SummarizerResult:
    """
    Run Summarizer role to create turn summary and memory writes.

    Args:
        user_query: The user's question
        answer: The response given
        capsule: Capsule content (claims from Verifier)
        llm_client: LLM client for intelligent summarization
        turn_dir: Directory to write outputs
        use_llm: Whether to use LLM for intelligent summarization

    Returns:
        SummarizerResult with turn_summary and memory_writes
    """
    logger.info("[Summarizer] Starting turn summarization")

    if use_llm and llm_client is not None:
        try:
            result = await _summarize_with_llm(
                user_query=user_query,
                answer=answer,
                capsule=capsule,
                llm_client=llm_client,
            )
        except Exception as e:
            logger.warning(f"[Summarizer] LLM summarization failed: {e}, using simple fallback")
            turn_summary = build_turn_summary_simple(user_query, answer, capsule)
            memory_writes = detect_memory_writes(user_query, answer, capsule)
            result = SummarizerResult(
                turn_summary=turn_summary,
                memory_writes=memory_writes,
            )
    else:
        turn_summary = build_turn_summary_simple(user_query, answer, capsule)
        memory_writes = detect_memory_writes(user_query, answer, capsule)
        result = SummarizerResult(
            turn_summary=turn_summary,
            memory_writes=memory_writes,
        )

    # Write turn_summary.json
    summary_path = turn_dir / "turn_summary.json"
    summary_path.write_text(result.turn_summary.to_json())
    logger.info(f"[Summarizer] Wrote turn_summary.json")

    # Execute memory writes
    if result.memory_writes:
        result.memories_written = await _execute_memory_writes(result.memory_writes)
        logger.info(f"[Summarizer] Wrote {result.memories_written} memories")

    # Write memory_writes.json for transparency
    writes_path = turn_dir / "memory_writes.json"
    writes_data = [
        {
            "doc_type": w.doc_type,
            "section": w.section,
            "entry": w.entry,
            "confidence": w.confidence,
            "source": w.source,
        }
        for w in result.memory_writes
    ]
    writes_path.write_text(json.dumps(writes_data, indent=2))

    return result


async def _summarize_with_llm(
    user_query: str,
    answer: str,
    capsule: Optional[str],
    llm_client,
) -> SummarizerResult:
    """
    Use LLM to create intelligent turn summary and detect memory writes.
    """
    # Load recipe and prompt using the recipe system
    try:
        recipe = load_recipe("memory/summarizer")
        system_prompt = recipe.get_prompt()
    except RecipeNotFoundError:
        logger.warning("[Summarizer] Recipe not found, using fallback prompt")
        system_prompt = "You are the Summarizer. Create a turn summary and detect memory writes."

    # Build user message
    user_message = f"""## User Query
```
{user_query}
```

## Answer Given
```
{answer[:3000]}
```

## Capsule (Claims)
```
{capsule[:2000] if capsule else "No capsule available"}
```

## Instructions

Create two outputs:

1. **turn_summary.json**: Compressed context for next turn
2. **memory_writes**: List of facts to persist to long-term memory

Output as JSON:
```json
{{
  "_type": "SUMMARIZER_OUTPUT",
  "turn_summary": {{
    "short_summary": "1-2 sentence turn description",
    "key_findings": ["fact1", "fact2", "fact3"],
    "preferences_learned": ["pref1", "pref2"],
    "topic": "commerce|research|code|general",
    "satisfaction_estimate": 0.0-1.0,
    "next_turn_hints": ["hint1", "hint2"]
  }},
  "memory_writes": [
    {{
      "doc_type": "user_preferences|user_facts|system_learnings|domain_knowledge",
      "section": "## Section Name",
      "entry": "- Entry content (confidence)",
      "confidence": "high|medium|low",
      "source": "Why this memory"
    }}
  ]
}}
```

Only include memory_writes if there's something worth remembering long-term.
"""

    # Call LLM
    try:
        solver_url = os.getenv("SOLVER_URL", "http://localhost:8000/v1/chat/completions")
        solver_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                solver_url,
                headers={
                    "Authorization": f"Bearer {solver_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": os.getenv("SOLVER_MODEL_ID", "qwen3-coder"),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1500,
                    "top_p": 0.8,
                    "stop": ["<|im_end|>", "<|endoftext|>"],
                    "repetition_penalty": 1.05
                }
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]

            # Parse JSON from response
            data = _extract_json_from_text(content)
            if not data:
                raise ValueError("No JSON in LLM response")

            # Extract turn_summary
            ts_data = data.get("turn_summary", {})
            turn_summary = TurnSummary(
                short_summary=ts_data.get("short_summary", "Turn completed."),
                key_findings=ts_data.get("key_findings", []),
                preferences_learned=ts_data.get("preferences_learned", []),
                topic=ts_data.get("topic", "general"),
                satisfaction_estimate=ts_data.get("satisfaction_estimate", 0.7),
                next_turn_hints=ts_data.get("next_turn_hints", []),
            )

            # Extract memory_writes
            memory_writes = []
            for mw in data.get("memory_writes", []):
                memory_writes.append(MemoryWrite(
                    doc_type=mw.get("doc_type", "user_facts"),
                    section=mw.get("section", "## Other"),
                    entry=mw.get("entry", ""),
                    confidence=mw.get("confidence", "medium"),
                    source=mw.get("source", "LLM detection"),
                ))

            return SummarizerResult(
                turn_summary=turn_summary,
                memory_writes=memory_writes,
            )

    except Exception as e:
        logger.error(f"[Summarizer] LLM call failed: {e}")
        raise


async def _execute_memory_writes(writes: List[MemoryWrite]) -> int:
    """
    Execute memory write instructions.

    Returns number of successful writes.
    """
    from libs.gateway.context.context_builder_role import append_to_memory_document

    success_count = 0
    for write in writes:
        if not write.entry:
            continue

        try:
            result = append_to_memory_document(
                doc_type=write.doc_type,
                section=write.section,
                entry=write.entry,
            )
            if result:
                success_count += 1
                logger.info(f"[MemoryWrite] Added to {write.doc_type}: {write.entry[:50]}...")
        except Exception as e:
            logger.warning(f"[MemoryWrite] Failed to write {write.doc_type}: {e}")

    return success_count


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON object from text that may contain markdown code blocks."""
    # Try to find JSON in code blocks first
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None
