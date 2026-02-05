"""
orchestrator/reflection_engine.py

Shared reflexion utilities for LLM-driven self-correction and query refinement.

Implements the Reflexion Loop pattern: when operations fail, ask the LLM to
analyze what went wrong and generate a better approach.
"""

import httpx
import logging
from typing import Dict

from apps.services.tool_server.shared.llm_utils import load_prompt_via_recipe as _load_prompt_via_recipe

logger = logging.getLogger(__name__)


def _load_prompt(prompt_name: str) -> str:
    """Load prompt - maps legacy names to recipe names."""
    return _load_prompt_via_recipe(prompt_name, "research")


def llm_refine_query(
    original_query: str,
    search_context: str,
    previous_results_summary: str,
    attempt_number: int,
    *,
    llm_url: str = "http://localhost:8000/v1/chat/completions",
    llm_model: str = "qwen3-coder",
    llm_api_key: str = "qwen-local"
) -> str:
    """
    Generic LLM-driven query refinement for any search operation.

    Use this when a search fails to find results or returns low-quality results.
    The LLM analyzes the failure and suggests a better query.

    Args:
        original_query: The query that failed
        search_context: What we're trying to find (e.g., "product pricing for BOM item", "research papers", "memory")
        previous_results_summary: Summary of what we got (e.g., "No results", "3 results but wrong category")
        attempt_number: Which attempt this is (1, 2, 3...)
        llm_url: LLM endpoint URL
        llm_model: Model identifier
        llm_api_key: API key for authentication

    Returns:
        Refined query string

    Examples:
        # Product search
        refined = llm_refine_query(
            "Arduino Nano",
            "product pricing for BOM item",
            "No results found",
            2
        )
        # Returns: "Arduino Nano V3 microcontroller board buy online"

        # Research query
        refined = llm_refine_query(
            "hamster breeders",
            "finding pet breeders",
            "Found 5 results but all are educational resources",
            2
        )
        # Returns: "USDA licensed Syrian hamster breeder directory"
    """
    # Load prompt template and format
    prompt_template = _load_prompt("query_reflection")
    if prompt_template:
        prompt = prompt_template.format(
            original_query=original_query,
            search_context=search_context,
            attempt_number=attempt_number,
            previous_results_summary=previous_results_summary
        )
    else:
        # Fallback to inline prompt if file not found
        prompt = f"""This search query failed to find good results:

ORIGINAL QUERY: "{original_query}"
SEARCH CONTEXT: {search_context}
ATTEMPT NUMBER: {attempt_number}

WHAT WE GOT:
{previous_results_summary}

PROBLEM:
The search didn't find what we need. Analyze why and suggest ONE improved query.

Think about:
- Is the query too broad or too specific?
- Should we add brand names, model numbers, or specifications?
- Should we try synonyms or alternative phrasings?
- Should we add context keywords (e.g., "buy", "for sale", "official")?
- Should we remove ambiguous terms?

Output ONLY the refined query text. No quotes, no explanation."""

    try:
        response = httpx.post(
            llm_url,
            json={
                "model": llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 80,
                "top_p": 0.8,
                "stop": ["<|im_end|>", "<|endoftext|>"],
                "repetition_penalty": 1.05
            },
            headers={"Authorization": f"Bearer {llm_api_key}"},
            timeout=30.0
        )
        response.raise_for_status()

        refined_query = response.json()["choices"][0]["message"]["content"].strip()
        # Strip any quotes the LLM might have added
        refined_query = refined_query.strip('"').strip("'").strip()

        logger.info(f"LLM refined query: '{original_query}' -> '{refined_query}'")
        return refined_query

    except Exception as e:
        logger.error(f"LLM query refinement failed: {e}")
        # Fallback: simple heuristic if LLM fails
        if attempt_number == 2:
            return f"{original_query} buy online"
        elif attempt_number == 3:
            return f"{original_query} official store"
        else:
            return original_query


async def llm_refine_query_async(
    original_query: str,
    search_context: str,
    previous_results_summary: str,
    attempt_number: int,
    *,
    llm_url: str = "http://localhost:8000/v1/chat/completions",
    llm_model: str = "qwen3-coder",
    llm_api_key: str = "qwen-local"
) -> str:
    """
    Async version of llm_refine_query for use in async contexts.

    See llm_refine_query() for documentation.
    """
    # Load prompt template and format
    prompt_template = _load_prompt("query_reflection")
    if prompt_template:
        prompt = prompt_template.format(
            original_query=original_query,
            search_context=search_context,
            attempt_number=attempt_number,
            previous_results_summary=previous_results_summary
        )
    else:
        # Fallback to inline prompt if file not found
        prompt = f"""This search query failed to find good results:

ORIGINAL QUERY: "{original_query}"
SEARCH CONTEXT: {search_context}
ATTEMPT NUMBER: {attempt_number}

WHAT WE GOT:
{previous_results_summary}

PROBLEM:
The search didn't find what we need. Analyze why and suggest ONE improved query.

Think about:
- Is the query too broad or too specific?
- Should we add brand names, model numbers, or specifications?
- Should we try synonyms or alternative phrasings?
- Should we add context keywords (e.g., "buy", "for sale", "official")?
- Should we remove ambiguous terms?

Output ONLY the refined query text. No quotes, no explanation."""

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                llm_url,
                json={
                    "model": llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 80,
                    "top_p": 0.8,
                    "stop": ["<|im_end|>", "<|endoftext|>"],
                    "repetition_penalty": 1.05
                },
                headers={"Authorization": f"Bearer {llm_api_key}"},
                timeout=30.0
            )
            response.raise_for_status()

            refined_query = response.json()["choices"][0]["message"]["content"].strip()
            # Strip any quotes the LLM might have added
            refined_query = refined_query.strip('"').strip("'").strip()

            logger.info(f"LLM refined query: '{original_query}' -> '{refined_query}'")
            return refined_query

    except Exception as e:
        logger.error(f"LLM query refinement failed: {e}")
        # Fallback: simple heuristic if LLM fails
        if attempt_number == 2:
            return f"{original_query} buy online"
        elif attempt_number == 3:
            return f"{original_query} official store"
        else:
            return original_query
