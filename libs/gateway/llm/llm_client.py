"""
Panda LLM Client for Gateway Integration.

Simple wrapper around httpx for OpenAI-compatible LLM calls.

Implements Qwen3-Coder recommended inference settings:
- ChatML stop tokens (<|im_end|>)
- top_p=0.8, top_k=20, repetition_penalty=1.05
- Role-based temperature control

Architecture Note:
- This client uses "guide"/"coordinator" role terminology which predates
  the current 8-phase pipeline. The roles map to URL/model selection
  rather than pipeline phases.
- For phase-based temperature routing, see libs/llm/router.py which
  implements the PHASE_TEMPERATURE_MAP.
- This client remains compatible for legacy integration patterns.

Author: v4.0 Migration - Production Integration
Date: 2025-11-16
Updated: 2026-02-02 (added Qwen inference params and stop tokens)
"""

import json
import logging
import httpx
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# ChatML stop tokens for Qwen3-Coder
# These prevent the model from generating past the end of a turn
CHATML_STOP_TOKENS = ["<|im_end|>", "<|endoftext|>"]

# Qwen3-Coder recommended inference settings
QWEN_DEFAULTS = {
    "top_p": 0.8,
    "top_k": 20,
    "repetition_penalty": 1.05,
}


class LLMClient:
    """
    Simple LLM client for OpenAI-compatible endpoints.

    Supports role-specific URLs (guide vs coordinator) with different models.
    Implements Qwen3-Coder recommended inference settings.
    """

    def __init__(
        self,
        guide_url: str,
        coordinator_url: str,
        guide_model: str,
        coordinator_model: str,
        guide_headers: Optional[Dict[str, str]] = None,
        coordinator_headers: Optional[Dict[str, str]] = None,
        timeout: float = 90.0
    ):
        self.guide_url = guide_url
        self.coordinator_url = coordinator_url
        self.guide_model = guide_model
        self.coordinator_model = coordinator_model
        self.guide_headers = guide_headers or {}
        self.coordinator_headers = coordinator_headers or {}
        self.timeout = timeout

    async def call(
        self,
        prompt: str,
        role: str,  # "guide" or "coordinator"
        max_tokens: int = 1000,
        temperature: float = 0.7,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        repetition_penalty: Optional[float] = None,
        stop: Optional[List[str]] = None,
        timeout: Optional[float] = None
    ) -> str:
        """
        Call LLM with prompt.

        Args:
            prompt: System + user prompt
            role: "guide" or "coordinator" (selects URL and model)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (default 0.7 per Qwen recommendation)
            top_p: Nucleus sampling threshold (default 0.8 per Qwen)
            top_k: Top-k sampling (default 20 per Qwen)
            repetition_penalty: Repetition penalty (default 1.05 per Qwen)
            stop: Stop sequences (default ChatML tokens)
            timeout: Override default timeout

        Returns:
            LLM response text
        """
        url = self.guide_url if role == "guide" else self.coordinator_url
        model = self.guide_model if role == "guide" else self.coordinator_model
        headers = self.guide_headers if role == "guide" else self.coordinator_headers

        # Build payload with Qwen recommended defaults
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p if top_p is not None else QWEN_DEFAULTS["top_p"],
            "stop": stop if stop is not None else CHATML_STOP_TOKENS,
        }

        # Add optional parameters (vLLM supports these via extra_body or directly)
        # Note: top_k and repetition_penalty may need to go in extra_body for some servers
        if top_k is not None or QWEN_DEFAULTS.get("top_k"):
            payload["top_k"] = top_k if top_k is not None else QWEN_DEFAULTS["top_k"]

        if repetition_penalty is not None or QWEN_DEFAULTS.get("repetition_penalty"):
            payload["repetition_penalty"] = (
                repetition_penalty if repetition_penalty is not None
                else QWEN_DEFAULTS["repetition_penalty"]
            )

        logger.info(
            f"[LLMClient] Calling {role} LLM: {url} "
            f"(max_tokens={max_tokens}, temp={temperature}, top_p={payload.get('top_p')})"
        )

        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()

                result = response.json()
                content = result["choices"][0]["message"]["content"]

                logger.info(f"[LLMClient] {role} LLM response: {len(content)} chars")
                return content

        except httpx.TimeoutException as e:
            logger.error(f"[LLMClient] {role} LLM timeout: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"[LLMClient] {role} LLM HTTP error: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"[LLMClient] {role} LLM error: {e}")
            raise
