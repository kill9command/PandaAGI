"""
LLM Client for v4.0 Flow

Simple wrapper around httpx for OpenAI-compatible LLM calls.

Author: v4.0 Migration - Production Integration
Date: 2025-11-16
"""

import json
import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Simple LLM client for OpenAI-compatible endpoints.

    Supports role-specific URLs (guide vs coordinator) with different models.
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
        timeout: Optional[float] = None
    ) -> str:
        """
        Call LLM with prompt.

        Args:
            prompt: System + user prompt
            role: "guide" or "coordinator" (selects URL and model)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            timeout: Override default timeout

        Returns:
            LLM response text
        """
        url = self.guide_url if role == "guide" else self.coordinator_url
        model = self.guide_model if role == "guide" else self.coordinator_model
        headers = self.guide_headers if role == "guide" else self.coordinator_headers

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        logger.info(f"[LLMClient] Calling {role} LLM: {url} (max_tokens={max_tokens})")

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
