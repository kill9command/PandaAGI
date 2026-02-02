"""vLLM HTTP client for PandaAI v2."""

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx
from pydantic import BaseModel

from libs.core.config import get_settings
from libs.core.exceptions import LLMError, InterventionRequired


class LLMRequest(BaseModel):
    """LLM request payload."""

    model: str
    messages: list[dict[str, str]]
    temperature: float = 0.7
    max_tokens: int = 2000
    stream: bool = False


class LLMResponse(BaseModel):
    """LLM response."""

    content: str
    model: str
    usage: dict[str, Any]  # Can contain nested objects in newer vLLM
    finish_reason: str


@dataclass
class TokenUsage:
    """Token usage tracking."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMClient:
    """Async HTTP client for vLLM server."""

    def __init__(self):
        self.settings = get_settings()
        self._clients: dict[str, httpx.AsyncClient] = {}

    async def _get_client(self, model_layer: str) -> httpx.AsyncClient:
        """Get or create HTTP client for specific model layer."""
        if model_layer not in self._clients:
            base_url = self.settings.vllm.get_base_url(model_layer)
            api_key = self.settings.vllm.api_key
            self._clients[model_layer] = httpx.AsyncClient(
                base_url=base_url,
                timeout=httpx.Timeout(60.0, connect=10.0),
                headers={"Authorization": f"Bearer {api_key}"},
            )
        return self._clients[model_layer]

    async def close(self):
        """Close all HTTP clients."""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def complete(
        self,
        model_layer: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        """
        Send completion request to vLLM.

        Args:
            model_layer: Model layer name (reflex, nerves, mind, voice, eyes)
            messages: Chat messages
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            LLMResponse with generated content

        Raises:
            LLMError: On API errors
            InterventionRequired: On critical failures (fail-fast mode)
        """
        client = await self._get_client(model_layer)

        # Get model ID from settings for the request
        model_id = getattr(self.settings.models, model_layer, model_layer)

        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            return LLMResponse(
                content=data["choices"][0]["message"]["content"],
                model=data["model"],
                usage=data["usage"],
                finish_reason=data["choices"][0]["finish_reason"],
            )

        except httpx.HTTPStatusError as e:
            if self.settings.fail_fast:
                raise InterventionRequired(
                    component="LLMClient",
                    error=f"HTTP {e.response.status_code}: {e.response.text}",
                    context={"model_layer": model_layer, "endpoint": "/chat/completions"},
                )
            raise LLMError(f"HTTP error: {e}") from e

        except httpx.RequestError as e:
            base_url = self.settings.vllm.get_base_url(model_layer)
            if self.settings.fail_fast:
                raise InterventionRequired(
                    component="LLMClient",
                    error=f"Request failed: {e}",
                    context={"model_layer": model_layer, "base_url": base_url},
                )
            raise LLMError(f"Request error: {e}") from e

    async def stream(
        self,
        model_layer: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> AsyncIterator[str]:
        """
        Stream completion from vLLM.

        Args:
            model_layer: Model layer name (reflex, nerves, mind, voice, eyes)

        Yields:
            Text chunks as they arrive
        """
        client = await self._get_client(model_layer)
        model_id = getattr(self.settings.models, model_layer, model_layer)

        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        # Parse SSE data
                        import json
                        chunk = json.loads(data)
                        if chunk["choices"][0].get("delta", {}).get("content"):
                            yield chunk["choices"][0]["delta"]["content"]

        except httpx.HTTPStatusError as e:
            if self.settings.fail_fast:
                raise InterventionRequired(
                    component="LLMClient",
                    error=f"Stream HTTP {e.response.status_code}",
                    context={"model_layer": model_layer},
                )
            raise LLMError(f"Stream error: {e}") from e

    async def health_check(self, model_layer: str = "mind") -> bool:
        """Check if vLLM server is healthy for a specific model layer."""
        try:
            # Health endpoint is at root, not under /v1
            base_url = self.settings.vllm.get_base_url(model_layer).replace("/v1", "")
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(f"{base_url}/health")
                return response.status_code == 200
        except Exception:
            return False

    async def health_check_all(self) -> dict[str, bool]:
        """Check health of all vLLM instances."""
        results = {}
        for layer in ["reflex", "nerves", "mind", "voice"]:
            results[layer] = await self.health_check(layer)
        return results


# Singleton instance
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
