"""
Shared LLM utilities for orchestrator components.

Provides common functions for calling LLMs and parsing responses.
This consolidates duplicate _call_llm implementations from:
- browser_agent.py
- meta_reflection.py

Usage:
    from apps.services.orchestrator.shared import call_llm_json, call_llm_text

    # For JSON responses
    result = await call_llm_json(prompt, llm_url, llm_model, llm_api_key)

    # For plain text responses
    text = await call_llm_text(prompt, llm_url, llm_model, llm_api_key)
"""

import json
import logging
import os
import re
from typing import Dict, Any, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# Approximate tokens per character (conservative estimate)
CHARS_PER_TOKEN = 4

# Recipe-based prompt loading
_prompt_cache: Dict[str, str] = {}


def _load_prompt_via_recipe(recipe_name: str, category: str = "tools") -> str:
    """
    Load prompt via recipe system with inline fallback.

    Args:
        recipe_name: Name of the recipe (e.g., "content_summarizer")
        category: Recipe category (default "tools")

    Returns:
        Prompt content from recipe, or empty string if not found
    """
    cache_key = f"{category}/{recipe_name}"
    if cache_key in _prompt_cache:
        return _prompt_cache[cache_key]

    try:
        from libs.gateway.recipe_loader import load_recipe, RecipeNotFoundError
        recipe = load_recipe(f"{category}/{recipe_name}")
        content = recipe.get_prompt()
        _prompt_cache[cache_key] = content
        return content
    except Exception as e:
        logger.warning(f"[LLMUtils] Recipe {cache_key} not found: {e}")
        return ""


# Legacy alias for backward compatibility
def _load_prompt(prompt_name: str) -> str:
    """Load prompt - maps legacy names to recipe names."""
    return _load_prompt_via_recipe(prompt_name, "tools")

# Default LLM settings from environment
DEFAULT_LLM_URL = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
DEFAULT_LLM_MODEL = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
DEFAULT_LLM_API_KEY = os.getenv("SOLVER_API_KEY", "qwen-local")


async def call_llm_text(
    prompt: str,
    llm_url: str = None,
    llm_model: str = None,
    llm_api_key: str = None,
    max_tokens: int = 50,
    temperature: float = 0.2,
    timeout: float = 30.0
) -> str:
    """
    Call LLM and return plain text response.

    Useful for simple yes/no queries or short text responses.

    Args:
        prompt: Prompt for LLM
        llm_url: LLM endpoint URL (default from env)
        llm_model: Model ID (default from env)
        llm_api_key: API key (default from env)
        max_tokens: Max tokens to generate
        temperature: Temperature for sampling
        timeout: Request timeout in seconds

    Returns:
        Plain text response string

    Raises:
        httpx.HTTPStatusError: If LLM returns error status
        httpx.TimeoutException: If request times out
    """
    url = llm_url or DEFAULT_LLM_URL
    model = llm_model or DEFAULT_LLM_MODEL
    api_key = llm_api_key or DEFAULT_LLM_API_KEY

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature
            }
        )

        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()


async def call_llm_json(
    prompt: str,
    llm_url: str = None,
    llm_model: str = None,
    llm_api_key: str = None,
    max_tokens: int = 500,
    temperature: float = 0.2,
    timeout: float = 30.0,
    required_keys: List[str] = None,
    repair_json: bool = True,
    use_json_mode: bool = True
) -> Dict[str, Any]:
    """
    Call LLM and parse JSON response with structured output support.

    Uses vLLM's response_format for guaranteed valid JSON when use_json_mode=True.
    Falls back to repair strategies if JSON mode is disabled or fails.

    Handles common JSON parsing issues:
    - Markdown code blocks (```json ... ```)
    - Unescaped newlines in strings
    - Truncated JSON (from max_tokens limit)

    Args:
        prompt: Prompt for LLM
        llm_url: LLM endpoint URL (default from env)
        llm_model: Model ID (default from env)
        llm_api_key: API key (default from env)
        max_tokens: Max tokens to generate
        temperature: Temperature for sampling
        timeout: Request timeout in seconds
        required_keys: Optional list of keys that must be present in response
        repair_json: Whether to attempt JSON repair on parse failure
        use_json_mode: Use vLLM's structured JSON output (default True)

    Returns:
        Parsed JSON response as dict

    Raises:
        httpx.HTTPStatusError: If LLM returns error status
        httpx.TimeoutException: If request times out
        ValueError: If response is not valid JSON or missing required keys
    """
    url = llm_url or DEFAULT_LLM_URL
    model = llm_model or DEFAULT_LLM_MODEL
    api_key = llm_api_key or DEFAULT_LLM_API_KEY

    # Build request payload
    request_body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    # Add structured JSON output if enabled (vLLM/OpenAI compatible)
    if use_json_mode:
        request_body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=request_body
        )

        response.raise_for_status()
        result = response.json()

        content = result["choices"][0]["message"]["content"]
        original_content = content

        # Remove markdown code blocks if present
        content = _extract_json_from_markdown(content)

        # DEBUG: Log what we're about to parse
        if content != original_content:
            extracted_preview = content[:150].replace('\n', ' ')
            logger.debug(f"[LLMUtils] Extracted content: {extracted_preview}...")

        # Try to parse as JSON
        parsed = _parse_json_with_repair(content, repair_json)

        if parsed is None:
            # DEBUG: Log both original and extracted content for troubleshooting
            extracted_preview = content[:100].replace('\n', ' ')
            logger.warning(f"[LLMUtils] Parse failed. Extracted: {extracted_preview}...")
            # Log what we received for debugging
            preview = original_content[:100].replace('\n', '\\n')
            logger.error(f"[LLMUtils] Failed to parse JSON. Content preview: {preview}")
            raise ValueError(f"Failed to parse JSON from LLM response: {preview}")

        # Ensure parsed is a dict (json.loads might return list, str, etc.)
        if not isinstance(parsed, dict):
            preview = original_content[:100].replace('\n', '\\n')
            logger.error(f"[LLMUtils] JSON parsed but not a dict (got {type(parsed).__name__}): {preview}")
            raise ValueError(f"Expected JSON object, got {type(parsed).__name__}: {preview}")

        # Validate required keys
        if required_keys:
            missing = [k for k in required_keys if k not in parsed]
            if missing:
                raise ValueError(f"Response missing required keys: {missing}")

        return parsed


def _extract_json_from_markdown(content: str) -> str:
    """Extract JSON from markdown code blocks and clean up whitespace."""
    content = content.strip()

    # Strip <think>...</think> tags from Qwen3's chain-of-thought output
    # Also handle unclosed <think> tags (model might get cut off by max_tokens)
    content = re.sub(r'<think>[\s\S]*?</think>', '', content)
    content = re.sub(r'<think>[\s\S]*$', '', content)  # Unclosed think at end
    content = content.strip()

    # Try ```json ... ``` first
    if "```json" in content:
        parts = content.split("```json")
        if len(parts) > 1:
            json_part = parts[1].split("```")[0]
            return json_part.strip()

    # Try generic ``` ... ```
    if "```" in content:
        parts = content.split("```")
        if len(parts) >= 2:
            return parts[1].strip()

    # Handle case where LLM returns JSON with leading whitespace/newlines
    # Find the first { or [ which marks the start of JSON
    json_start = -1
    for i, char in enumerate(content):
        if char in '{[':
            json_start = i
            break

    if json_start > 0:
        # There's content before the JSON starts - strip it
        content = content[json_start:]
    elif json_start == -1 and '"' in content:
        # No opening brace found but content looks like JSON interior
        # (e.g., LLM returned '\n  "page_type": "content"...')
        # Try wrapping in braces
        content = '{' + content.strip()
        # Find where to close it - look for the last complete key:value
        if not content.rstrip().endswith('}'):
            content = content.rstrip().rstrip(',') + '}'

    return content


def _parse_json_with_repair(content: str, repair: bool = True) -> Optional[Dict[str, Any]]:
    """
    Parse JSON with repair strategies for common issues.

    NOTE: With use_json_mode=True in call_llm_json(), repair should rarely be needed.
    If repair is frequently triggered, check if JSON mode is working properly.
    """
    # Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        if not repair:
            return None

        logger.debug(f"[LLMUtils] JSON parse failed, trying repair: {e}")

    # Strategy 1: Escape unescaped newlines in strings
    try:
        def escape_newlines_in_strings(match):
            return match.group(0).replace('\n', '\\n').replace('\r', '')

        fixed = re.sub(r'"[^"]*"', escape_newlines_in_strings, content, flags=re.DOTALL)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Handle truncated JSON (common with max_tokens limit)
    # Find the last complete object/value and try to close the structure
    try:
        # Find last complete object marker (},) or (},\n) or just (})
        last_complete = -1
        for match in re.finditer(r'\}\s*,', content):
            last_complete = match.end()

        if last_complete > 0:
            truncated = content[:last_complete - 1]  # Remove trailing comma
            # Count open brackets to determine what closers we need
            open_braces = truncated.count('{') - truncated.count('}')
            open_brackets = truncated.count('[') - truncated.count(']')

            # Build closer based on what's still open
            closer = '}' * open_braces + ']' * open_brackets
            if closer:
                try:
                    repaired = truncated + closer
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass

            # Fallback: try common closers
            for closer in [']}', '}]}', '}}]', '}', ']}}}']:
                try:
                    repaired = truncated + closer
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass

    # Strategy 3: Try to find JSON array pattern
    try:
        match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', content)
        if match:
            return json.loads(match.group())
    except json.JSONDecodeError:
        pass

    # Strategy 4: Try to find JSON object pattern
    try:
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            return json.loads(match.group())
    except json.JSONDecodeError:
        pass

    return None


# ==============================================================================
# Document Summarization for Token Budget Management
# ==============================================================================

async def summarize_sources_for_budget(
    sources: List[Dict[str, Any]],
    query: str,
    target_tokens: int = 4000,
    llm_url: str = None,
    llm_model: str = None,
    llm_api_key: str = None
) -> List[Dict[str, Any]]:
    """
    Summarize Phase 1 sources to fit within a token budget using LLM.

    This function intelligently compresses source content while PRESERVING:
    - Source structure (URL, type, status)
    - Key findings and recommendations
    - Vendor names, prices, specific products
    - Expert opinions and user experiences

    The LLM is instructed to maintain document structure while summarizing
    verbose content. This ensures downstream roles (Intelligence Synthesizer)
    receive properly structured input.

    Args:
        sources: List of source dicts from gather_intelligence()
        query: Original user query (for context)
        target_tokens: Target token budget for all sources combined
        llm_url: LLM endpoint URL (default from env)
        llm_model: Model ID (default from env)
        llm_api_key: API key (default from env)

    Returns:
        List of source dicts with summarized content, fitting within budget
    """
    if not sources:
        return []

    # Calculate current token estimate
    current_tokens = _estimate_sources_tokens(sources)

    if current_tokens <= target_tokens:
        logger.info(f"[DocSummarizer] Sources already within budget ({current_tokens} <= {target_tokens} tokens)")
        return sources

    logger.info(
        f"[DocSummarizer] Sources exceed budget ({current_tokens} > {target_tokens} tokens), "
        f"summarizing {len(sources)} sources"
    )

    # Calculate per-source budget (with overhead for structure)
    structure_overhead = 100  # tokens per source for URL, type, headers
    content_budget_per_source = max(200, (target_tokens - (structure_overhead * len(sources))) // len(sources))

    summarized_sources = []
    for i, source in enumerate(sources):
        try:
            summarized = await _summarize_single_source(
                source=source,
                query=query,
                target_content_tokens=content_budget_per_source,
                llm_url=llm_url,
                llm_model=llm_model,
                llm_api_key=llm_api_key
            )
            summarized_sources.append(summarized)
        except Exception as e:
            logger.warning(f"[DocSummarizer] Failed to summarize source {i+1}: {e}")
            # Fall back to truncation
            summarized_sources.append(_truncate_source(source, content_budget_per_source))

    final_tokens = _estimate_sources_tokens(summarized_sources)
    logger.info(
        f"[DocSummarizer] Summarization complete: {current_tokens} -> {final_tokens} tokens "
        f"(target: {target_tokens})"
    )

    return summarized_sources


async def _summarize_single_source(
    source: Dict[str, Any],
    query: str,
    target_content_tokens: int,
    llm_url: str = None,
    llm_model: str = None,
    llm_api_key: str = None
) -> Dict[str, Any]:
    """
    Summarize a single source while preserving its structure.

    The LLM is instructed to maintain the document structure expected by
    downstream roles while compressing verbose content.
    """
    # Extract content from source (handle multiple formats)
    content = (
        source.get("text_content_full") or
        source.get("text_content") or
        source.get("content") or
        ""
    )

    # If content is already short enough, return as-is
    target_chars = target_content_tokens * CHARS_PER_TOKEN
    if len(content) <= target_chars:
        return source

    url = source.get("url", "Unknown URL")
    page_type = source.get("page_type") or source.get("content_type") or "unknown"

    # Limit input to prevent context overflow
    content_truncated = content[:8000]

    # Load prompt template and format
    prompt_template = _load_prompt("content_summarizer")
    if prompt_template:
        prompt = prompt_template.format(
            query=query,
            url=url,
            page_type=page_type,
            content=content_truncated,
            target_content_tokens=target_content_tokens,
            target_chars=target_chars
        )
    else:
        # Fallback to inline prompt if file not found
        prompt = f"""Summarize this research source content while STRICTLY preserving structure.

RESEARCH QUERY: {query}

SOURCE URL: {url}
SOURCE TYPE: {page_type}

ORIGINAL CONTENT:
{content_truncated}

===== CRITICAL SUMMARIZATION RULES =====

1. **PRESERVE STRUCTURE** - Your output MUST maintain these sections:
   - Main summary paragraph (2-3 sentences)
   - Key Points (bullet list)
   - Any specific products/vendors mentioned
   - Any prices mentioned

2. **PRESERVE SPECIFICS** - NEVER generalize these:
   - Vendor/retailer names (Best Buy, Amazon, Newegg, etc.)
   - Product names and model numbers
   - Prices and price ranges
   - Specifications (GPU, RAM, storage, etc.)
   - Expert recommendations

3. **COMPRESS VERBOSITY** - Remove:
   - Repetitive information
   - Off-topic tangents
   - Excessive context/background
   - Navigation/UI text artifacts

4. **TARGET LENGTH**: ~{target_content_tokens} tokens (~{target_chars} characters)

===== OUTPUT FORMAT =====

Provide a structured summary with:

**Summary:** [2-3 sentence overview]

**Key Points:**
- [Specific finding with numbers/names]
- [Another specific finding]

**Vendors Mentioned:** [List any retailers/vendors]

**Products/Prices:** [List any specific products with prices]

**Expert Recommendations:** [Any specific recommendations]

BEGIN SUMMARY:"""

    try:
        summary = await call_llm_text(
            prompt=prompt,
            llm_url=llm_url,
            llm_model=llm_model,
            llm_api_key=llm_api_key,
            max_tokens=target_content_tokens + 50,  # Small buffer
            temperature=0.3,
            timeout=30.0
        )

        # Return source with summarized content
        summarized_source = source.copy()
        summarized_source["text_content"] = summary
        summarized_source["text_content_full"] = None  # Clear full content
        summarized_source["_summarized"] = True
        summarized_source["_original_length"] = len(content)

        return summarized_source

    except Exception as e:
        logger.warning(f"[DocSummarizer] LLM summarization failed: {e}")
        raise


def _truncate_source(source: Dict[str, Any], target_tokens: int) -> Dict[str, Any]:
    """
    Fallback: Simple truncation if LLM summarization fails.
    """
    content = (
        source.get("text_content_full") or
        source.get("text_content") or
        source.get("content") or
        ""
    )

    target_chars = target_tokens * CHARS_PER_TOKEN
    if len(content) > target_chars:
        content = content[:target_chars] + "\n\n[... content truncated to fit budget ...]"

    truncated_source = source.copy()
    truncated_source["text_content"] = content
    truncated_source["text_content_full"] = None
    truncated_source["_truncated"] = True

    return truncated_source


def _estimate_sources_tokens(sources: List[Dict[str, Any]]) -> int:
    """
    Estimate total tokens for a list of sources.
    """
    total_chars = 0
    for source in sources:
        # URL and metadata
        total_chars += len(source.get("url", "")) + 100  # overhead for headers

        # Content
        content = (
            source.get("text_content_full") or
            source.get("text_content") or
            source.get("content") or
            ""
        )
        total_chars += len(content)

        # Key points
        key_points = source.get("key_points", [])
        if isinstance(key_points, list):
            total_chars += sum(len(str(p)) for p in key_points)

    return total_chars // CHARS_PER_TOKEN


def estimate_document_tokens(content: str) -> int:
    """
    Estimate tokens for a document string.
    """
    return len(content) // CHARS_PER_TOKEN
