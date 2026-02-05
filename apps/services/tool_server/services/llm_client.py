"""
LLM Client for PandaAI Orchestrator

Communicates with vLLM server via OpenAI-compatible API.
Handles role-based temperature mapping and streaming.

Architecture Reference:
    architecture/LLM-ROLES/llm-roles-reference.md

Text Roles (all use MIND model via temperature):
    - REFLEX (temp=0.3): Classification, binary decisions
    - NERVES (temp=0.1): Compression, low creativity
    - MIND (temp=0.5): Reasoning, planning
    - VOICE (temp=0.7): User dialogue, more natural

vLLM Server:
    - Default endpoint: http://localhost:8000/v1
    - Model: MIND (Qwen3-4B-Instruct-2507-AWQ)
    - OpenAI-compatible chat completions API
"""

import json
import logging
from enum import Enum
from typing import AsyncIterator, Optional

import httpx
from pydantic import BaseModel

from libs.core.config import get_settings
from libs.core.exceptions import LLMError


logger = logging.getLogger(__name__)


class LLMRole(str, Enum):
    """LLM roles with associated temperatures.

    All text roles use the same MIND model on vLLM.
    Role behavior is controlled by temperature and system prompts.
    """
    REFLEX = "reflex"  # temp=0.3 - Classification, binary decisions
    NERVES = "nerves"  # temp=0.1 - Compression, low creativity
    MIND = "mind"      # temp=0.5 - Reasoning, planning
    VOICE = "voice"    # temp=0.7 - User dialogue, synthesis


# Role to temperature mapping
ROLE_TEMPERATURES = {
    LLMRole.REFLEX: 0.3,
    LLMRole.NERVES: 0.1,
    LLMRole.MIND: 0.5,
    LLMRole.VOICE: 0.7,
}


class LLMResponse(BaseModel):
    """Response from LLM."""
    content: str
    role: str
    model: str
    usage: dict[str, int]
    finish_reason: str


class LLMClient:
    """
    Async HTTP client for vLLM server.

    Provides methods for generating completions with role-based
    temperature settings. Supports both blocking and streaming modes.

    Usage:
        client = LLMClient()

        # Blocking call
        response = await client.generate(
            prompt="What is the capital of France?",
            role=LLMRole.MIND,
        )

        # Streaming call
        async for chunk in client.generate_stream(
            prompt="Write a story...",
            role=LLMRole.VOICE,
        ):
            print(chunk, end="")
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 60.0,
    ):
        """
        Initialize LLM client.

        Args:
            base_url: vLLM server base URL (default: from settings)
            model_name: Model to use (default: from settings)
            timeout: Request timeout in seconds
        """
        self.settings = get_settings()
        self.base_url = base_url or self.settings.vllm.get_base_url("mind")
        self.model_name = model_name or self.settings.models.mind
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def get_temperature(self, role: LLMRole) -> float:
        """Get temperature for a role."""
        return ROLE_TEMPERATURES.get(role, 0.5)

    async def generate(
        self,
        prompt: str,
        role: LLMRole = LLMRole.MIND,
        temperature: Optional[float] = None,
        max_tokens: int = 2000,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Generate completion from vLLM.

        Args:
            prompt: User prompt text
            role: LLM role (determines temperature if not overridden)
            temperature: Override default temperature for role
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt

        Returns:
            Generated text content

        Raises:
            LLMError: On API errors or connection failures
        """
        client = await self._get_client()

        # Use role temperature if not overridden
        temp = temperature if temperature is not None else self.get_temperature(role)

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tokens,
            "top_p": 0.8,
            "stop": ["<|im_end|>", "<|endoftext|>"],
            "repetition_penalty": 1.05,
        }

        try:
            logger.debug(f"LLM request: role={role.value}, temp={temp}, max_tokens={max_tokens}")

            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]

            logger.debug(f"LLM response: {len(content)} chars, finish_reason={data['choices'][0]['finish_reason']}")

            return content

        except httpx.HTTPStatusError as e:
            error_msg = f"vLLM HTTP error {e.response.status_code}: {e.response.text}"
            logger.error(error_msg)
            raise LLMError(error_msg, context={"role": role.value, "status_code": e.response.status_code})

        except httpx.RequestError as e:
            error_msg = f"vLLM connection error: {e}"
            logger.error(error_msg)
            raise LLMError(error_msg, context={"role": role.value, "base_url": self.base_url})

        except (KeyError, IndexError) as e:
            error_msg = f"Invalid vLLM response format: {e}"
            logger.error(error_msg)
            raise LLMError(error_msg, context={"role": role.value})

    async def generate_stream(
        self,
        prompt: str,
        role: LLMRole = LLMRole.MIND,
        temperature: Optional[float] = None,
        max_tokens: int = 2000,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream completion from vLLM.

        Args:
            prompt: User prompt text
            role: LLM role (determines temperature if not overridden)
            temperature: Override default temperature for role
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt

        Yields:
            Text chunks as they arrive

        Raises:
            LLMError: On API errors or connection failures
        """
        client = await self._get_client()

        # Use role temperature if not overridden
        temp = temperature if temperature is not None else self.get_temperature(role)

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tokens,
            "stream": True,
            "top_p": 0.8,
            "stop": ["<|im_end|>", "<|endoftext|>"],
            "repetition_penalty": 1.05,
        }

        try:
            logger.debug(f"LLM stream request: role={role.value}, temp={temp}, max_tokens={max_tokens}")

            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break

                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue

        except httpx.HTTPStatusError as e:
            error_msg = f"vLLM stream HTTP error {e.response.status_code}"
            logger.error(error_msg)
            raise LLMError(error_msg, context={"role": role.value, "status_code": e.response.status_code})

        except httpx.RequestError as e:
            error_msg = f"vLLM stream connection error: {e}"
            logger.error(error_msg)
            raise LLMError(error_msg, context={"role": role.value, "base_url": self.base_url})

    async def generate_with_messages(
        self,
        messages: list[dict[str, str]],
        role: LLMRole = LLMRole.MIND,
        temperature: Optional[float] = None,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        """
        Generate completion with full message list.

        Args:
            messages: List of message dicts with 'role' and 'content'
            role: LLM role (determines temperature if not overridden)
            temperature: Override default temperature for role
            max_tokens: Maximum tokens to generate

        Returns:
            LLMResponse with full response details

        Raises:
            LLMError: On API errors or connection failures
        """
        client = await self._get_client()

        # Use role temperature if not overridden
        temp = temperature if temperature is not None else self.get_temperature(role)

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tokens,
            "top_p": 0.8,
            "stop": ["<|im_end|>", "<|endoftext|>"],
            "repetition_penalty": 1.05,
        }

        try:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            return LLMResponse(
                content=data["choices"][0]["message"]["content"],
                role=role.value,
                model=data.get("model", self.model_name),
                usage=data.get("usage", {}),
                finish_reason=data["choices"][0].get("finish_reason", "unknown"),
            )

        except httpx.HTTPStatusError as e:
            raise LLMError(f"vLLM HTTP error {e.response.status_code}")
        except httpx.RequestError as e:
            raise LLMError(f"vLLM connection error: {e}")

    async def health_check(self) -> bool:
        """Check if vLLM server is healthy."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False


# Singleton instance
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
