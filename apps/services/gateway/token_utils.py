"""
Token counting utilities with safety margins.

Uses tiktoken for model-accurate token counting with configurable safety margin
to prevent budget overflow due to counting inaccuracies.

Quality Agent Requirement: Use model-specific encoding with 5% safety margin.
"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Try to import tiktoken (model-accurate token counting)
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning("[TokenUtils] tiktoken not available, using character-based estimation")


def count_tokens_safe(
    text: str,
    model_id: str = "gpt-3.5-turbo",  # Default, should match SOLVER_MODEL_ID
    safety_margin: float = 0.05  # 5% safety margin
) -> int:
    """
    Count tokens with 5% safety margin using tiktoken.

    Args:
        text: Text to count
        model_id: Model identifier for encoding selection
        safety_margin: Safety factor (0.05 = 5% extra)

    Returns:
        Token count with safety margin applied (rounded up)

    Quality Agent Requirement: Use model-specific encoding with safety margin
    to prevent budget overflow due to counting inaccuracies.
    """

    if not text:
        return 0

    if TIKTOKEN_AVAILABLE:
        try:
            # Get model-specific encoding
            # Map common model names to tiktoken encodings
            encoding_map = {
                "gpt-3.5-turbo": "cl100k_base",
                "gpt-4": "cl100k_base",
                "qwen": "cl100k_base",  # Approximate with GPT-4 encoding
                "qwen3-coder": "cl100k_base",
                "qwen-coder": "cl100k_base",
            }

            # Get encoding name
            encoding_name = encoding_map.get(model_id, "cl100k_base")

            # For unknown models, try tiktoken's model lookup first
            if model_id not in encoding_map:
                try:
                    encoding = tiktoken.encoding_for_model(model_id)
                except Exception:
                    # Fallback to cl100k_base
                    encoding = tiktoken.get_encoding(encoding_name)
            else:
                encoding = tiktoken.get_encoding(encoding_name)

            token_count = len(encoding.encode(text))

            # Apply safety margin
            safe_count = int(token_count * (1 + safety_margin))

            logger.debug(f"[TokenUtils] Counted {token_count} tokens, with margin: {safe_count}")
            return safe_count

        except Exception as e:
            logger.error(f"[TokenUtils] tiktoken failed: {e}, falling back to estimation")
            # Fall through to estimation

    # Fallback: Character-based estimation
    # Rough estimate: 1 token ≈ 4 characters for English text
    char_count = len(text)
    estimated_tokens = char_count // 4

    # Apply larger safety margin for estimation (10% instead of 5%)
    safe_count = int(estimated_tokens * 1.10)

    logger.debug(f"[TokenUtils] Using estimation: {char_count} chars → {safe_count} tokens (with 10% margin)")
    return safe_count


def validate_token_budget(
    components: Dict[str, str],  # {"section_name": "content"}
    max_tokens: int,
    model_id: str = "gpt-3.5-turbo",
    safety_margin: float = 0.05
) -> Dict[str, Any]:
    """
    Validate that combined components fit within budget.

    Args:
        components: Dictionary of section names to content
        max_tokens: Maximum allowed tokens
        model_id: Model identifier for accurate counting
        safety_margin: Safety margin to apply

    Returns:
        {
            "valid": bool,
            "total_tokens": int,
            "max_tokens": int,
            "overflow": int (if invalid),
            "breakdown": {"section": token_count},
            "utilization": str (percentage)
        }
    """

    breakdown = {}
    total = 0

    for name, content in components.items():
        if content is None:
            content = ""
        tokens = count_tokens_safe(content, model_id=model_id, safety_margin=safety_margin)
        breakdown[name] = tokens
        total += tokens

    valid = total <= max_tokens
    overflow = max(0, total - max_tokens)

    return {
        "valid": valid,
        "total_tokens": total,
        "max_tokens": max_tokens,
        "overflow": overflow,
        "breakdown": breakdown,
        "utilization": f"{total / max_tokens * 100:.1f}%"
    }


def truncate_to_budget(
    text: str,
    max_tokens: int,
    model_id: str = "gpt-3.5-turbo",
    safety_margin: float = 0.05,
    suffix: str = "\n\n[... truncated due to token budget ...]"
) -> str:
    """
    Truncate text to fit within token budget.

    Args:
        text: Text to truncate
        max_tokens: Maximum allowed tokens
        model_id: Model identifier
        safety_margin: Safety margin to apply
        suffix: Suffix to append to truncated text

    Returns:
        Truncated text that fits within budget
    """

    current_tokens = count_tokens_safe(text, model_id=model_id, safety_margin=safety_margin)

    if current_tokens <= max_tokens:
        return text

    # Binary search for truncation point
    suffix_tokens = count_tokens_safe(suffix, model_id=model_id, safety_margin=safety_margin)
    target_tokens = max_tokens - suffix_tokens

    left, right = 0, len(text)
    best_pos = 0

    while left < right:
        mid = (left + right) // 2
        chunk = text[:mid]
        chunk_tokens = count_tokens_safe(chunk, model_id=model_id, safety_margin=safety_margin)

        if chunk_tokens <= target_tokens:
            best_pos = mid
            left = mid + 1
        else:
            right = mid

    truncated = text[:best_pos] + suffix

    final_tokens = count_tokens_safe(truncated, model_id=model_id, safety_margin=safety_margin)
    logger.info(f"[TokenUtils] Truncated {current_tokens} tokens → {final_tokens} tokens")

    return truncated


# Convenience function for backward compatibility with existing code
def count_tokens(text: str, model_id: str = "gpt-3.5-turbo") -> int:
    """
    Count tokens without safety margin (for backward compatibility).

    Prefer count_tokens_safe() for new code.
    """
    if not text:
        return 0

    if TIKTOKEN_AVAILABLE:
        try:
            encoding_map = {
                "gpt-3.5-turbo": "cl100k_base",
                "gpt-4": "cl100k_base",
                "qwen": "cl100k_base",
                "qwen3-coder": "cl100k_base",
                "qwen-coder": "cl100k_base",
            }

            encoding_name = encoding_map.get(model_id, "cl100k_base")
            encoding = tiktoken.get_encoding(encoding_name)
            return len(encoding.encode(text))

        except Exception as e:
            logger.error(f"[TokenUtils] tiktoken failed: {e}")

    # Fallback
    return len(text) // 4
