"""
Human-like page reading for extraction tasks.

Implements a three-step approach:
1. Page scanning - Quick relevance check
2. Focused extraction - Read only relevant sections
3. Validation - Double-check extracted data
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
import json

from libs.gateway.llm.recipe_loader import load_recipe, RecipeNotFoundError

logger = logging.getLogger(__name__)

# Recipe cache for navigation prompts
_recipe_cache: Dict[str, Any] = {}


def _load_navigation_prompt(prompt_name: str) -> str:
    """
    Load a navigation prompt via the recipe system.

    Uses caching to avoid repeated recipe loads.

    Args:
        prompt_name: Prompt name without extension (e.g., "human_scanner")

    Returns:
        Prompt content as string, or empty string if not found
    """
    if prompt_name in _recipe_cache:
        return _recipe_cache[prompt_name]

    try:
        recipe = load_recipe(f"navigation/{prompt_name}")
        prompt_content = recipe.get_prompt()
        _recipe_cache[prompt_name] = prompt_content
        logger.debug(f"[HumanPageReader] Loaded prompt via recipe: navigation/{prompt_name}")
        return prompt_content
    except RecipeNotFoundError:
        logger.warning(f"[HumanPageReader] Recipe not found: navigation/{prompt_name}")
        return ""
    except Exception as e:
        logger.warning(f"[HumanPageReader] Failed to load prompt from recipe: {e}")
        return ""


async def scan_page_for_relevance(
    text_content: str,
    url: str,
    search_goal: str,
    llm_url: str,
    llm_model: str,
    llm_api_key: str
) -> Dict[str, Any]:
    """
    Step 1: Quick scan to determine if page is relevant.

    Like a human quickly skimming a page to see if it's worth reading.
    Uses minimal tokens - just check if page contains what we're looking for.

    Args:
        text_content: Full page text
        url: Page URL
        search_goal: What we're looking for (e.g., "vendor recommendations for Syrian hamsters")
        llm_url: LLM endpoint
        llm_model: Model name
        llm_api_key: API key

    Returns:
        {
            "is_relevant": bool,
            "relevance_score": float (0-1),
            "relevant_sections": [str],  // Brief descriptions of relevant parts
            "skip_reason": str | None    // Why page was skipped (if not relevant)
        }
    """
    # Truncate content for quick scan (first 2000 chars + last 1000 chars)
    # Like a human reading the intro and conclusion
    preview = text_content[:2000]
    if len(text_content) > 3000:
        preview += "\n\n[...]\n\n" + text_content[-1000:]

    # Load prompt template from file
    prompt_template = _load_navigation_prompt("human_scanner")
    if prompt_template:
        prompt = prompt_template.format(
            search_goal=search_goal,
            url=url,
            preview=preview
        )
    else:
        # Fallback inline prompt if file not found
        prompt = f"""You are scanning a webpage to determine if it's relevant for: "{search_goal}"

URL: {url}

PAGE PREVIEW:
{preview}

Task: Quickly determine if this page is relevant. Answer in JSON format:

{{
  "is_relevant": true/false,
  "relevance_score": 0.0-1.0,
  "relevant_sections": ["brief description of relevant section 1", "section 2"],
  "skip_reason": "why not relevant (if is_relevant=false)" or null
}}

Be efficient - we're just checking if it's worth reading the full page.
If the page is a forum post, Reddit thread, or review site discussing the topic, it's likely relevant.
If it's completely unrelated (e.g., about a different topic), mark it as not relevant."""

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                llm_url,
                json={
                    "model": llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 200
                },
                headers={"Authorization": f"Bearer {llm_api_key}"}
            ) as response:
                result = await response.json()
                content = result["choices"][0]["message"]["content"]

                # Extract JSON from response
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]

                data = json.loads(content.strip())

                logger.info(
                    f"[PageScanner] {url[:60]} - "
                    f"Relevant: {data['is_relevant']} (score: {data.get('relevance_score', 0):.2f})"
                )

                return data

    except Exception as e:
        logger.error(f"[PageScanner] Error scanning {url[:60]}: {e}")
        # Default to relevant on error (don't skip potentially good pages)
        return {
            "is_relevant": True,
            "relevance_score": 0.5,
            "relevant_sections": [],
            "skip_reason": None
        }


async def extract_focused_content(
    text_content: str,
    url: str,
    search_goal: str,
    relevant_sections: List[str],
    extraction_schema: Dict[str, Any],
    llm_url: str,
    llm_model: str,
    llm_api_key: str
) -> Dict[str, Any]:
    """
    Step 2: Focused extraction from relevant sections.

    Like a human reading specific paragraphs that looked interesting.
    Uses section hints from Step 1 to guide where to focus.

    Args:
        text_content: Full page text
        url: Page URL
        search_goal: What we're extracting
        relevant_sections: Section descriptions from Step 1
        extraction_schema: JSON schema describing what to extract
        llm_url: LLM endpoint
        llm_model: Model name
        llm_api_key: API key

    Returns:
        Extracted data matching the schema
    """
    # Chunk the content into readable sections (simulate human reading flow)
    # Take first 3000 chars, middle 2000, and last 2000
    chunks = []

    if len(text_content) <= 7000:
        chunks = [text_content]
    else:
        chunks = [
            text_content[:3000],
            text_content[len(text_content)//2 - 1000:len(text_content)//2 + 1000],
            text_content[-2000:]
        ]

    combined_text = "\n\n[...]\n\n".join(chunks)

    # Build context-aware prompt
    section_context = ""
    if relevant_sections:
        section_context = "\nFocus on these relevant sections:\n" + "\n".join(f"- {s}" for s in relevant_sections)

    extraction_schema_str = json.dumps(extraction_schema, indent=2)

    # Load prompt template from file
    prompt_template = _load_navigation_prompt("human_extractor")
    if prompt_template:
        prompt = prompt_template.format(
            search_goal=search_goal,
            url=url,
            section_context=section_context,
            combined_text=combined_text,
            extraction_schema=extraction_schema_str
        )
    else:
        # Fallback inline prompt if file not found
        prompt = f"""You are reading a webpage to extract: {search_goal}

URL: {url}
{section_context}

PAGE CONTENT:
{combined_text}

Extract information according to this schema:
{extraction_schema_str}

Return ONLY valid JSON matching the schema. If information is not found, use empty values ([], {{}}, null)."""

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                llm_url,
                json={
                    "model": llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 1000
                },
                headers={"Authorization": f"Bearer {llm_api_key}"}
            ) as response:
                result = await response.json()
                content = result["choices"][0]["message"]["content"]

                # Extract JSON from response
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]

                extracted_data = json.loads(content.strip())

                logger.info(f"[FocusedExtraction] Extracted from {url[:60]}")

                return extracted_data

    except Exception as e:
        logger.error(f"[FocusedExtraction] Error extracting from {url[:60]}: {e}")
        return {}


async def validate_extraction(
    extracted_data: Dict[str, Any],
    url: str,
    search_goal: str,
    llm_url: str,
    llm_model: str,
    llm_api_key: str
) -> Dict[str, Any]:
    """
    Step 3: Validate extracted data.

    Like a human double-checking what they read to make sure it makes sense.
    Quick validation pass to catch obvious errors or hallucinations.

    Args:
        extracted_data: Data from Step 2
        url: Page URL
        search_goal: What we were extracting
        llm_url: LLM endpoint
        llm_model: Model name
        llm_api_key: API key

    Returns:
        {
            "is_valid": bool,
            "confidence": float (0-1),
            "issues": [str],  // List of problems found
            "cleaned_data": Dict  // Corrected version of extracted_data
        }
    """
    if not extracted_data:
        return {
            "is_valid": False,
            "confidence": 0.0,
            "issues": ["No data extracted"],
            "cleaned_data": {}
        }

    extracted_data_str = json.dumps(extracted_data, indent=2)

    # Load prompt template from file
    prompt_template = _load_navigation_prompt("human_validator")
    if prompt_template:
        prompt = prompt_template.format(
            search_goal=search_goal,
            url=url,
            extracted_data=extracted_data_str
        )
    else:
        # Fallback inline prompt if file not found
        prompt = f"""You are validating extracted data for quality and correctness.

Goal: {search_goal}
URL: {url}

EXTRACTED DATA:
{extracted_data_str}

Task: Validate this data. Check for:
1. Completeness - Is required information present?
2. Consistency - Do values make sense together?
3. Hallucinations - Any made-up or unlikely data?
4. Format errors - Correct data types?

Return JSON:
{{
  "is_valid": true/false,
  "confidence": 0.0-1.0,
  "issues": ["issue 1", "issue 2"] or [],
  "cleaned_data": {{cleaned version of extracted_data}}
}}

If data looks good, return is_valid=true with cleaned_data=original data."""

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                llm_url,
                json={
                    "model": llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 500
                },
                headers={"Authorization": f"Bearer {llm_api_key}"}
            ) as response:
                result = await response.json()
                content = result["choices"][0]["message"]["content"]

                # Extract JSON from response
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]

                validation = json.loads(content.strip())

                status = "VALID" if validation["is_valid"] else "INVALID"
                logger.info(
                    f"[Validation] {url[:60]} - {status} "
                    f"(confidence: {validation.get('confidence', 0):.2f})"
                )

                return validation

    except Exception as e:
        logger.error(f"[Validation] Error validating {url[:60]}: {e}")
        # Default to accepting data on validation error
        return {
            "is_valid": True,
            "confidence": 0.5,
            "issues": [f"Validation error: {str(e)}"],
            "cleaned_data": extracted_data
        }


async def read_page_like_human(
    text_content: str,
    url: str,
    search_goal: str,
    extraction_schema: Dict[str, Any],
    llm_url: str,
    llm_model: str,
    llm_api_key: str,
    min_relevance: float = 0.4
) -> Optional[Dict[str, Any]]:
    """
    Full three-step human-like page reading process.

    Args:
        text_content: Full page text
        url: Page URL
        search_goal: What we're looking for
        extraction_schema: What to extract (JSON schema)
        llm_url: LLM endpoint
        llm_model: Model name
        llm_api_key: API key
        min_relevance: Minimum relevance score to proceed (0-1)

    Returns:
        Extracted and validated data, or None if page not relevant
    """
    logger.info(f"[HumanReader] Starting 3-step read of {url[:60]}")

    # Step 1: Quick scan
    scan_result = await scan_page_for_relevance(
        text_content=text_content,
        url=url,
        search_goal=search_goal,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key
    )

    if not scan_result["is_relevant"] or scan_result["relevance_score"] < min_relevance:
        logger.info(
            f"[HumanReader] Skipping {url[:60]} - "
            f"Reason: {scan_result.get('skip_reason', 'low relevance')}"
        )
        return None

    # Step 2: Focused extraction
    extracted_data = await extract_focused_content(
        text_content=text_content,
        url=url,
        search_goal=search_goal,
        relevant_sections=scan_result.get("relevant_sections", []),
        extraction_schema=extraction_schema,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key
    )

    if not extracted_data:
        logger.warning(f"[HumanReader] No data extracted from {url[:60]}")
        return None

    # Step 3: Validation
    validation = await validate_extraction(
        extracted_data=extracted_data,
        url=url,
        search_goal=search_goal,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key
    )

    if not validation["is_valid"] or validation["confidence"] < 0.5:
        logger.warning(
            f"[HumanReader] Validation failed for {url[:60]} - "
            f"Issues: {validation.get('issues', [])}"
        )
        # Still return data but mark it as low confidence
        return {
            **validation["cleaned_data"],
            "_meta": {
                "validation_passed": False,
                "confidence": validation["confidence"],
                "issues": validation["issues"]
            }
        }

    # Success!
    logger.info(f"[HumanReader] Successfully read {url[:60]}")
    return {
        **validation["cleaned_data"],
        "_meta": {
            "validation_passed": True,
            "confidence": validation["confidence"],
            "relevance_score": scan_result["relevance_score"]
        }
    }
