"""
Claude LLM Client for Gateway Integration.

Drop-in replacement for LLMClient that targets Claude's API.
Same call() interface so UnifiedFlow works unchanged.

The "guide"/"coordinator" role distinction is ignored — both
map to the same Claude model/endpoint. Temperature and max_tokens
pass through; Qwen-specific params (top_k, repetition_penalty,
ChatML stop tokens) are stripped.
"""

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Lazy import — anthropic SDK only needed when this client is actually used
_anthropic = None


def _get_anthropic():
    """Lazy-load anthropic SDK."""
    global _anthropic
    if _anthropic is None:
        try:
            import anthropic
            _anthropic = anthropic
        except ImportError:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            )
    return _anthropic


class ClaudeLLMClient:
    """
    LLM client targeting Anthropic Claude API.

    Same call() interface as gateway LLMClient so it can be swapped
    into UnifiedFlow without changes to the pipeline.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5-20250929",
        timeout: float = 120.0,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        # Client created lazily on first call
        self._client = None

    def _ensure_client(self):
        """Create async client on first use."""
        if self._client is None:
            anthropic = _get_anthropic()
            self._client = anthropic.AsyncAnthropic(
                api_key=self.api_key,
                timeout=self.timeout,
            )

    async def call(
        self,
        prompt: str,
        role: str,  # "guide" or "coordinator" — ignored, both use same model
        max_tokens: int = 1000,
        temperature: float = 0.7,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        repetition_penalty: Optional[float] = None,
        stop: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Call Claude with prompt. Matches LLMClient.call() exactly.

        Qwen-specific params (top_k, repetition_penalty, ChatML stops)
        are silently ignored. Temperature and max_tokens pass through.

        Args:
            prompt: System + user prompt (sent as system message)
            role: Ignored — both guide/coordinator use same Claude model
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Passed through to Claude (optional)
            top_k: Ignored (Qwen-specific)
            repetition_penalty: Ignored (Qwen-specific)
            stop: Ignored (ChatML tokens not relevant for Claude)
            timeout: Override default timeout (unused — set at client level)

        Returns:
            LLM response text (string)
        """
        self._ensure_client()

        # Claude uses system param separately from messages
        # The pipeline sends everything as a system prompt
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": prompt,
            "messages": [{"role": "user", "content": "Please respond to the system instructions above."}],
        }

        if top_p is not None:
            kwargs["top_p"] = top_p

        logger.info(
            f"[ClaudeLLMClient] Calling Claude ({self.model}) for role={role} "
            f"(max_tokens={max_tokens}, temp={temperature})"
        )

        try:
            response = await self._client.messages.create(**kwargs)
            content = response.content[0].text

            logger.info(
                f"[ClaudeLLMClient] Claude response: {len(content)} chars "
                f"(input_tokens={response.usage.input_tokens}, "
                f"output_tokens={response.usage.output_tokens})"
            )
            return content

        except Exception as e:
            logger.error(f"[ClaudeLLMClient] Claude API error: {e}")
            raise
