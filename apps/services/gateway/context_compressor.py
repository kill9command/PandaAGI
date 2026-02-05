"""
Context compression utilities for managing LLM context windows.

Provides LLM-based turn summarization, token estimation, and sliding windows
for long multi-step tasks.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Dict, Any
import tiktoken

from libs.gateway.llm.recipe_loader import load_recipe, RecipeNotFoundError

logger = logging.getLogger(__name__)

# Cache for loaded prompts from recipes
_prompt_cache: Dict[str, str] = {}


def _load_prompt_from_recipe(recipe_name: str) -> str:
    """
    Load prompt from recipe.

    Args:
        recipe_name: Recipe path (e.g., "memory/turn_compressor")

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
        logger.warning(f"[ContextCompressor] Recipe not found: {recipe_name}")
        return ""
    except Exception as e:
        logger.warning(f"[ContextCompressor] Failed to load recipe {recipe_name}: {e}")
        return ""

# Initialize tokenizer (cl100k_base used by GPT-3.5/4 and similar models)
try:
    tokenizer = tiktoken.get_encoding("cl100k_base")
except Exception:
    tokenizer = None
    logger.warning("tiktoken not available, falling back to character estimation")


def estimate_tokens(text: str | list[str]) -> int:
    """Accurately estimate token count using tiktoken if available."""
    if isinstance(text, list):
        text = "\n".join(text)

    if tokenizer:
        return len(tokenizer.encode(text))
    else:
        # Fallback: rough approximation (4 chars per token)
        return len(text) // 4


def compress_turn_with_llm(
    turn_text: str,
    solver_url: str,
    solver_headers: dict,
    max_tokens: int = 100,
    timeout: float = 10.0
) -> str:
    """Use LLM to compress a turn into bullet points.

    Args:
        turn_text: The full turn text to compress
        solver_url: URL for the solver/thinking model
        solver_headers: Headers for auth
        max_tokens: Maximum tokens in compressed output
        timeout: Request timeout

    Returns:
        Compressed summary as bullet points
    """
    import httpx

    # Load base prompt from recipe
    base_prompt = _load_prompt_from_recipe("memory/turn_compressor")
    if not base_prompt:
        # Fallback inline prompt if file not found
        base_prompt = """Summarize this conversation turn into 2-3 concise bullet points.

Format as:
- Key action or question
- Main result or finding
- Important context (if any)"""

    prompt = f"""{base_prompt}

---

Max tokens: {max_tokens}

Turn to summarize:
{turn_text[:2000]}"""

    payload = {
        "model": "qwen3-coder",  # Will be overridden by server
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,  # Lower temp for factual summarization
        "stop": ["\n\n", "---"]
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(solver_url, headers=solver_headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if "choices" in data and len(data["choices"]) > 0:
                summary = data["choices"][0]["message"]["content"].strip()
                # Ensure it's actually bullet points
                if not summary.startswith("-") and not summary.startswith("•"):
                    summary = "- " + summary.replace("\n", "\n- ")
                return summary
            else:
                logger.warning("LLM compression failed, no choices in response")
                return _fallback_compress(turn_text, max_tokens)

    except Exception as e:
        logger.warning(f"LLM compression error: {e}, using fallback")
        return _fallback_compress(turn_text, max_tokens)


def _fallback_compress(text: str, max_tokens: int) -> str:
    """Fallback compression when LLM is unavailable."""
    # Extract key sentences (first and last, plus any with important keywords)
    sentences = re.split(r'[.!?]+', text)
    important = []

    keywords = ['error', 'success', 'result', 'found', 'created', 'updated', 'failed']
    for sent in sentences:
        if any(kw in sent.lower() for kw in keywords):
            important.append(sent.strip())

    # Take first, last, and up to 2 important sentences
    summary_parts = []
    if sentences:
        summary_parts.append(sentences[0].strip())
    summary_parts.extend(important[:2])
    if len(sentences) > 1:
        summary_parts.append(sentences[-1].strip())

    summary = " ".join(summary_parts)

    # Truncate to token limit
    if estimate_tokens(summary) > max_tokens:
        # Rough character limit
        char_limit = max_tokens * 4
        summary = summary[:char_limit] + "..."

    return "- " + summary


def sliding_window_compress(
    messages: List[Dict[str, Any]],
    window_size: int = 10,
    keep_recent: int = 3,
    compress_fn: Optional[callable] = None
) -> List[Dict[str, Any]]:
    """Apply sliding window compression for long task histories.

    Args:
        messages: List of message dicts with 'role' and 'content'
        window_size: Number of messages to keep uncompressed
        keep_recent: Always keep this many most recent messages
        compress_fn: Optional function to compress old messages

    Returns:
        Compressed message list with summary of old messages
    """
    if len(messages) <= window_size:
        return messages

    # Always keep system message if present
    system_msg = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]

    if len(other_msgs) <= window_size:
        return messages

    # Split into old and recent
    old_msgs = other_msgs[:-keep_recent]
    recent_msgs = other_msgs[-keep_recent:]

    # Compress old messages
    if compress_fn:
        compressed_text = compress_fn(old_msgs)
    else:
        # Default: just count
        compressed_text = f"[Previous {len(old_msgs)} messages compressed - included {sum(1 for m in old_msgs if m.get('role') == 'user')} user queries and responses]"

    compressed_msg = {
        "role": "system",
        "content": f"## Conversation Summary (Older Messages)\n{compressed_text}"
    }

    return system_msg + [compressed_msg] + recent_msgs


def adaptive_context_budgeting(
    components: Dict[str, str | list[str]],
    total_budget: int,
    min_allocations: Optional[Dict[str, int]] = None
) -> Dict[str, str | list[str]]:
    """Adaptively allocate tokens across context components.

    Args:
        components: Dict of component_name -> text/list
        total_budget: Total token budget
        min_allocations: Minimum tokens to allocate per component

    Returns:
        Trimmed components fitting within budget
    """
    min_allocations = min_allocations or {}

    # Estimate current sizes
    component_sizes = {
        name: estimate_tokens(content)
        for name, content in components.items()
    }

    total_current = sum(component_sizes.values())

    if total_current <= total_budget:
        return components  # No trimming needed

    # Apply minimum allocations first
    remaining_budget = total_budget
    for name, min_alloc in min_allocations.items():
        remaining_budget -= min_alloc

    # Distribute remaining budget proportionally
    result = {}
    for name, content in components.items():
        min_alloc = min_allocations.get(name, 0)
        current_size = component_sizes[name]

        if current_size <= min_alloc:
            result[name] = content
            continue

        # Calculate proportional allocation
        proportion = current_size / total_current
        target_size = min_alloc + int(remaining_budget * proportion)

        if current_size <= target_size:
            result[name] = content
        else:
            # Trim to target
            result[name] = _trim_to_tokens(content, target_size)

    return result


def _trim_to_tokens(text: str | list[str], max_tokens: int) -> str | list[str]:
    """Trim text to fit within token budget."""
    is_list = isinstance(text, list)
    if is_list:
        text_str = "\n".join(text)
    else:
        text_str = text

    current_tokens = estimate_tokens(text_str)
    if current_tokens <= max_tokens:
        return text

    # Binary search for the right length
    char_ratio = len(text_str) / max(current_tokens, 1)
    target_chars = int(max_tokens * char_ratio * 0.9)  # 90% to be safe

    trimmed = text_str[:target_chars] + "..."

    if is_list:
        # Re-split into list, keeping whole items
        lines = trimmed.split("\n")
        return lines
    return trimmed
