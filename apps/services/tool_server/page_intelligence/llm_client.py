"""
orchestrator/page_intelligence/llm_client.py

Shared LLM Client for Page Intelligence System

Features:
- Reuses aiohttp session across requests (connection pooling)
- Centralized JSON parsing with proper error handling
- Token counting and budget enforcement
- Consistent error handling across all phases
"""

import asyncio
import json
import logging
import os
import re
import threading
from typing import Dict, Any, Optional, List

import aiohttp

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Shared LLM client with session reuse and proper error handling.

    All three phases (Zone Identifier, Selector Generator, Strategy Selector)
    use this client for LLM calls.
    """

    def __init__(
        self,
        llm_url: str = None,
        llm_model: str = None,
        timeout_seconds: int = 60
    ):
        """
        Initialize LLM client.

        Args:
            llm_url: URL for LLM API
            llm_model: Model name
            timeout_seconds: Request timeout
        """
        self.llm_url = llm_url or os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        self.llm_model = llm_model or os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        self.api_key = os.getenv("LLM_API_KEY", "qwen-local")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)

        # Session management
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=self.timeout,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                )
            return self._session

    async def close(self):
        """Close the aiohttp session."""
        async with self._session_lock:
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None

    async def call(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        use_json_mode: bool = True
    ) -> Dict[str, Any]:
        """
        Call LLM and parse JSON response.

        Args:
            prompt: User message prompt
            temperature: LLM temperature
            max_tokens: Maximum output tokens
            use_json_mode: Use vLLM's structured JSON output (default True)

        Returns:
            Parsed JSON response or error dict
        """
        session = await self._get_session()

        request_data = {
            "model": self.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        # Add structured JSON output if enabled (vLLM/OpenAI compatible)
        if use_json_mode:
            request_data["response_format"] = {"type": "json_object"}

        try:
            async with session.post(self.llm_url, json=request_data) as response:
                if response.status == 200:
                    data = await response.json()
                    content = data["choices"][0]["message"]["content"]
                    return self.parse_json_response(content)
                else:
                    body = await response.text()
                    logger.error(f"[LLMClient] API error {response.status}: {body[:200]}")
                    return {
                        "error": f"LLM API error: {response.status}",
                        "status_code": response.status,
                        "body_preview": body[:200]
                    }

        except asyncio.TimeoutError:
            logger.error(f"[LLMClient] Request timeout after {self.timeout.total}s")
            return {"error": "LLM request timeout"}
        except aiohttp.ClientConnectionError as e:
            logger.error(f"[LLMClient] Connection error: {e}")
            return {"error": f"Connection error: {e}"}
        except aiohttp.ClientError as e:
            logger.error(f"[LLMClient] Client error: {e}")
            return {"error": f"Client error: {e}"}
        except json.JSONDecodeError as e:
            logger.error(f"[LLMClient] Failed to parse API response JSON: {e}")
            return {"error": f"API response parse error: {e}"}
        except KeyError as e:
            logger.error(f"[LLMClient] Unexpected API response structure: {e}")
            return {"error": f"Unexpected response structure: {e}"}

    def parse_json_response(self, content: str) -> Dict[str, Any]:
        """
        Extract and parse JSON from LLM response.

        Handles:
        - JSON in code blocks (```json ... ```)
        - Raw JSON
        - JSON embedded in text

        Args:
            content: Raw LLM response content

        Returns:
            Parsed JSON dict or error dict
        """
        # Method 1: Try to find JSON in code block
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError as e:
                logger.debug(f"[LLMClient] Code block JSON parse failed: {e}")

        # Method 2: Try parsing whole content as JSON
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as e:
            logger.debug(f"[LLMClient] Full content JSON parse failed: {e}")

        # Method 3: Extract JSON object/array from text
        # Find the first { or [ and last } or ]
        obj_start = content.find('{')
        arr_start = content.find('[')

        if obj_start >= 0 and (arr_start < 0 or obj_start < arr_start):
            # Try to extract JSON object
            obj_end = content.rfind('}')
            if obj_end > obj_start:
                try:
                    return json.loads(content[obj_start:obj_end + 1])
                except json.JSONDecodeError as e:
                    logger.debug(f"[LLMClient] Object extraction failed: {e}")
        elif arr_start >= 0:
            # Try to extract JSON array
            arr_end = content.rfind(']')
            if arr_end > arr_start:
                try:
                    result = json.loads(content[arr_start:arr_end + 1])
                    # Wrap array in object for consistency
                    return {"items": result} if isinstance(result, list) else result
                except json.JSONDecodeError as e:
                    logger.debug(f"[LLMClient] Array extraction failed: {e}")

        # Method 4: Try to repair truncated JSON
        repaired = self._repair_truncated_json(content)
        if repaired:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError as e:
                logger.debug(f"[LLMClient] Repaired JSON parse failed: {e}")

        # All methods failed
        logger.warning(f"[LLMClient] Could not parse JSON from response: {content[:200]}...")
        return {
            "error": "Could not parse JSON from LLM response",
            "raw_preview": content[:500]
        }

    def _repair_truncated_json(self, content: str) -> Optional[str]:
        """
        Attempt to repair truncated JSON by adding missing closing brackets.

        This handles the common case where LLM output was cut off mid-generation.
        """
        # Find JSON start
        obj_start = content.find('{')
        if obj_start < 0:
            return None

        json_str = content[obj_start:]

        # Count open brackets that need closing
        open_braces = 0
        open_brackets = 0
        in_string = False
        escape_next = False

        for char in json_str:
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                continue
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == '{':
                open_braces += 1
            elif char == '}':
                open_braces -= 1
            elif char == '[':
                open_brackets += 1
            elif char == ']':
                open_brackets -= 1

        # If already balanced, no repair needed
        if open_braces == 0 and open_brackets == 0:
            return None

        # Need to repair - truncate at a reasonable point
        # Find the last complete item by looking for patterns like },\n or ],\n
        last_complete = max(
            json_str.rfind('},'),
            json_str.rfind('}]'),
            json_str.rfind('],'),
            json_str.rfind(']\n'),
            json_str.rfind('}\n'),
        )

        if last_complete > 0:
            # Truncate to last complete structure, then close
            truncated = json_str[:last_complete + 1]

            # Recount after truncation
            open_braces = 0
            open_brackets = 0
            in_string = False
            escape_next = False

            for char in truncated:
                if escape_next:
                    escape_next = False
                    continue
                if char == '\\':
                    escape_next = True
                    continue
                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if char == '{':
                    open_braces += 1
                elif char == '}':
                    open_braces -= 1
                elif char == '[':
                    open_brackets += 1
                elif char == ']':
                    open_brackets -= 1

            # Add closing brackets
            repaired = truncated + (']' * open_brackets) + ('}' * open_braces)
            logger.info(f"[LLMClient] Repaired truncated JSON: added {open_brackets} ] and {open_braces} }}")
            return repaired

        return None

    def estimate_tokens(self, text: str) -> int:
        """
        Rough token estimate (4 chars ≈ 1 token for English).

        This is a rough estimate. For precise counting, use tiktoken.
        """
        return len(text) // 4

    def truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """Truncate text to approximately max_tokens."""
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... [truncated]"


# Global instance with thread-safe initialization
_client: Optional[LLMClient] = None
_client_lock = threading.Lock()


def get_llm_client(
    llm_url: str = None,
    llm_model: str = None
) -> LLMClient:
    """Get or create global LLM client instance (thread-safe)."""
    global _client
    if _client is None:
        with _client_lock:
            # Double-check pattern
            if _client is None:
                _client = LLMClient(llm_url=llm_url, llm_model=llm_model)
    return _client


async def close_llm_client():
    """Close the global LLM client."""
    global _client
    with _client_lock:
        if _client:
            await _client.close()
            _client = None
