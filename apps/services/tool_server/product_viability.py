"""
orchestrator/product_viability.py

Product viability filter for intelligent multi-vendor search.
Filters extracted products against Phase 1 requirements using LLM.

Created: 2025-11-27
Updated: 2025-11-27 - Added URL spec parsing, improved prompts, keyword fallback
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
import httpx

from apps.services.tool_server.shared.llm_utils import load_prompt_via_recipe as _load_prompt_via_recipe

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).parent / "prompts"


def _load_prompt(prompt_name: str) -> str:
    """Load prompt - maps legacy names to recipe names."""
    return _load_prompt_via_recipe(prompt_name, "tools")


def parse_specs_from_url(url: str) -> Dict[str, str]:
    """
    Extract structured specs from product URL path.

    Many retailer URLs encode full product specs in the path, e.g.:
    /ASUS-TUF-Gaming-A16-Gaming-Laptop-16-WUXGA-144Hz-AMD-Processor-NVIDIA-GeForce-RTX-4050-16GB-DDR5-512GB-PCIe-SSD

    Args:
        url: Product URL

    Returns:
        Dict of extracted specs, e.g. {"gpu": "RTX 4050", "ram": "16GB DDR5", "storage": "512GB SSD"}
    """
    if not url:
        return {}

    try:
        path = urlparse(url).path.lower()
        # Also check query string for some retailers
        full_text = path.replace('-', ' ').replace('_', ' ').replace('/', ' ')
        specs = {}

        # GPU patterns - RTX/GTX with model number
        gpu_patterns = [
            r'(rtx|gtx)\s*(\d{4})\s*(ti|super)?',  # RTX 4050, GTX 1660 Ti
            r'geforce\s*(rtx|gtx)\s*(\d{4})\s*(ti|super)?',  # GeForce RTX 4050
            r'nvidia\s*geforce\s*(rtx|gtx)\s*(\d{4})',  # NVIDIA GeForce RTX 4050
            r'(rtx|gtx)\s*(\d{3,4})',  # RTX 4050 or GTX 970
        ]
        for pattern in gpu_patterns:
            gpu_match = re.search(pattern, full_text)
            if gpu_match:
                groups = gpu_match.groups()
                gpu_type = groups[0].upper() if groups[0] else ""
                gpu_num = groups[1] if len(groups) > 1 else ""
                gpu_suffix = groups[2].upper() if len(groups) > 2 and groups[2] else ""
                specs['gpu'] = f"{gpu_type} {gpu_num} {gpu_suffix}".strip()
                break

        # RAM patterns - look for GB with DDR indicator
        ram_patterns = [
            r'(\d+)\s*gb\s*(ddr\d+)',  # 16GB DDR5
            r'(\d+)\s*gb\s*ram',  # 16GB RAM
            r'(\d+)gb\s*(ddr\d)?',  # 16GB or 16GB DDR5
        ]
        for pattern in ram_patterns:
            ram_match = re.search(pattern, full_text)
            if ram_match:
                groups = ram_match.groups()
                ram_size = groups[0]
                ram_type = groups[1].upper() if len(groups) > 1 and groups[1] else ""
                specs['ram'] = f"{ram_size}GB {ram_type}".strip()
                break

        # Storage patterns
        storage_patterns = [
            r'(\d+)\s*(gb|tb)\s*(ssd|nvme|pcie|hdd)',  # 512GB SSD
            r'(\d+)\s*(gb|tb)\s*(?:pcie\s*)?(ssd|nvme)',  # 512GB PCIe SSD
        ]
        for pattern in storage_patterns:
            storage_match = re.search(pattern, full_text)
            if storage_match:
                groups = storage_match.groups()
                size = groups[0]
                unit = groups[1].upper()
                storage_type = groups[2].upper() if len(groups) > 2 else "SSD"
                specs['storage'] = f"{size}{unit} {storage_type}"
                break

        # CPU patterns
        cpu_patterns = [
            r'(intel\s*core\s*i\d)',  # Intel Core i7
            r'(amd\s*ryzen\s*\d)',  # AMD Ryzen 7
            r'(core\s*i\d\s*\d+)',  # Core i7 12700
            r'(ryzen\s*\d\s*\d+)',  # Ryzen 7 7840
        ]
        for pattern in cpu_patterns:
            cpu_match = re.search(pattern, full_text)
            if cpu_match:
                specs['cpu'] = cpu_match.group(1).title()
                break

        # Display patterns
        display_patterns = [
            r'(\d+(?:\.\d+)?)\s*(?:inch|")',  # 16 inch or 15.6"
            r'(\d{3,4})\s*hz',  # 144Hz
            r'(wuxga|fhd|qhd|4k|uhd)',  # Resolution names
        ]
        for pattern in display_patterns:
            display_match = re.search(pattern, full_text)
            if display_match:
                if 'hz' in pattern:
                    specs['refresh_rate'] = f"{display_match.group(1)}Hz"
                elif 'inch' in pattern or '"' in pattern:
                    specs['screen_size'] = f"{display_match.group(1)} inch"
                else:
                    specs['resolution'] = display_match.group(1).upper()

        if specs:
            logger.debug(f"[URLSpecs] Parsed from URL: {specs}")

        return specs

    except Exception as e:
        logger.warning(f"[URLSpecs] Failed to parse URL specs: {e}")
        return {}


def check_keyword_viability(
    product: Dict[str, Any],
    requirements: Dict[str, Any],
    query: str
) -> Optional[bool]:
    """
    Keyword-based viability check as fallback when LLM is uncertain.

    This is a GENERAL PURPOSE fallback that checks if a product's
    name, URL, and description match the user's query terms.

    Returns:
        True if product appears viable based on keywords
        False if product clearly doesn't match query
        None if uncertain (defer to LLM)
    """
    name = (product.get('name', '') or '').lower()
    url = (product.get('url', '') or '').lower()
    desc = (product.get('description', '') or '').lower()
    text = f"{name} {url} {desc}"

    # Parse specs from URL for better matching
    url_specs = parse_specs_from_url(product.get('url', ''))
    specs_text = ' '.join(str(v).lower() for v in url_specs.values())
    text = f"{text} {specs_text}"

    # Extract meaningful terms from query (skip common words)
    stop_words = {'find', 'search', 'buy', 'get', 'want', 'need', 'looking', 'for',
                  'the', 'a', 'an', 'with', 'and', 'or', 'under', 'over', 'about'}
    query_lower = query.lower()
    query_terms = [t for t in query_lower.split() if len(t) > 2 and t not in stop_words]

    if not query_terms:
        return None  # Can't determine without query terms

    # Check if product matches query terms
    matches = sum(1 for term in query_terms if term in text)
    match_ratio = matches / len(query_terms) if query_terms else 0

    # Also check key requirements if available
    key_reqs = requirements.get('key_requirements', [])
    if key_reqs:
        req_matches = sum(1 for req in key_reqs
                        if any(word.lower() in text for word in str(req).split() if len(word) > 3))
        req_ratio = req_matches / len(key_reqs)
    else:
        req_ratio = match_ratio  # Use query match if no requirements

    # High match ratio = likely viable
    if match_ratio >= 0.6 or req_ratio >= 0.5:
        logger.info(f"[KeywordViability] Product matches query terms ({match_ratio:.0%}): {name[:50]}")
        return True

    # Very low match = likely not viable
    if match_ratio < 0.2 and req_ratio < 0.2:
        logger.info(f"[KeywordViability] Product doesn't match query ({match_ratio:.0%}): {name[:50]}")
        return False

    # Uncertain - defer to LLM
    return None


async def filter_viable_products(
    products: List[Dict[str, Any]],
    requirements: Dict[str, Any],
    query: str,
    max_products: int = 4
) -> Dict[str, Any]:
    """
    Filter products to only viable candidates based on requirements.

    Uses LLM to evaluate each product against the requirements from Phase 1
    intelligence gathering.

    Args:
        products: List of extracted products with name, price, specs, etc.
        requirements: Requirements from Phase 1 intelligence
            Example: {"gpu": "RTX 4060+", "ram": "16GB+", "budget": "<$2000"}
        query: User's original query
        max_products: Maximum products to return per vendor

    Returns:
        {
            "viable_products": [
                {
                    "name": "...",
                    "price": "...",
                    "viability_score": 0.85,
                    "meets_requirements": {"gpu": true, "ram": true, "budget": true},
                    "strengths": ["..."],
                    "weaknesses": ["..."],
                    ...original product fields...
                }
            ],
            "rejected": [
                {"name": "...", "reason": "No dedicated GPU"}
            ],
            "stats": {
                "total_input": 10,
                "viable_count": 4,
                "rejected_count": 6
            }
        }
    """
    if not products:
        return {
            "viable_products": [],
            "rejected": [],
            "stats": {"total_input": 0, "viable_count": 0, "rejected_count": 0}
        }

    # Get model config from env
    model_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    model_id = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
    api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    # Build products text for prompt with enhanced spec extraction
    products_text = []
    enriched_products = []  # Keep track of products with parsed URL specs

    for i, p in enumerate(products[:10], 1):  # Limit to 10 products
        # Get description, truncate if too long
        desc = p.get('description', 'N/A') or 'N/A'
        if len(desc) > 200:
            desc = desc[:200] + "..."

        # Build specs from product data
        specs = p.get('specs', {}) or {}

        # ENHANCEMENT: Parse additional specs from URL
        url = p.get('url', '')
        url_specs = parse_specs_from_url(url) if url else {}

        # Merge URL specs into product specs (URL specs fill in gaps)
        merged_specs = {**url_specs, **specs}  # Product specs override URL specs

        # Store enriched product for fallback
        enriched_p = p.copy()
        enriched_p['_parsed_url_specs'] = url_specs
        enriched_p['_merged_specs'] = merged_specs
        enriched_products.append(enriched_p)

        # Build specs text
        specs_text = ""
        if merged_specs:
            specs_text = f"\n   Specs: {', '.join(f'{k}: {v}' for k, v in merged_specs.items() if v)}"

        # Extract URL path hint (INCREASED from 100 to 200 chars)
        url_hint = ""
        if url:
            path = urlparse(url).path
            # URLs often contain full product specs
            if any(kw in path.lower() for kw in ['rtx', 'gtx', 'geforce', 'radeon', 'laptop', 'gaming', 'nvidia', 'amd']):
                url_hint = f"\n   URL path: {path[:200]}"

        products_text.append(
            f"{i}. Name: {p.get('name', 'Unknown')}\n"
            f"   Price: {p.get('price', 'N/A')}\n"
            f"   Description: {desc}\n"
            f"   Vendor: {p.get('vendor', 'N/A')}"
            f"{specs_text}"
            f"{url_hint}"
        )

    # Use enriched products for result building
    products = enriched_products

    # Build requirements text - now returns (hard, nice_to_have) tuple
    hard_requirements_text, nice_to_haves_text = _format_requirements(requirements, query)

    # Load prompt from recipe file
    prompt_path = _PROMPT_DIR / "viability_evaluator.md"
    if prompt_path.exists():
        base_prompt = prompt_path.read_text()
    else:
        logger.warning(f"Prompt file not found: {prompt_path}")
        base_prompt = "You are evaluating products for viability. Respond with JSON containing evaluations array."

    # Build full prompt with dynamic data
    prompt = f"""{base_prompt}

## Current Task

USER QUERY: {query}

HARD REQUIREMENTS (product MUST meet these to be viable):
{hard_requirements_text}

NICE TO HAVE (improve score but do NOT reject if missing):
{nice_to_haves_text}

PRODUCTS TO EVALUATE ({len(products)} total, showing up to 10):
{chr(10).join(products_text)}

Evaluate each product against the requirements and determine viability."""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                model_url,
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": 1200
                },
                headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            result = response.json()

        # Parse LLM response with robust JSON extraction
        llm_content = result["choices"][0]["message"]["content"].strip()
        if "```json" in llm_content:
            llm_content = llm_content.split("```json")[1].split("```")[0].strip()
        elif "```" in llm_content:
            llm_content = llm_content.split("```")[1].split("```")[0].strip()

        # Try to extract JSON object even if there's extra text
        json_start = llm_content.find('{')
        json_end = llm_content.rfind('}')
        if json_start >= 0 and json_end > json_start:
            llm_content = llm_content[json_start:json_end + 1]

        # Try to repair common JSON errors from LLMs
        try:
            evaluation = json.loads(llm_content)
        except json.JSONDecodeError as e:
            logger.warning(f"[Viability] JSON parse error: {e}, attempting repair...")

            # Common LLM JSON errors:
            # 1. Unterminated strings - truncate at last complete object
            # 2. Trailing commas
            # 3. Single quotes instead of double quotes

            repaired = llm_content

            # Fix trailing commas before ] or }
            repaired = re.sub(r',\s*([}\]])', r'\1', repaired)

            # If still failing, try to find last complete evaluation
            try:
                evaluation = json.loads(repaired)
            except json.JSONDecodeError:
                # Last resort: extract individual evaluations
                logger.warning("[Viability] Repair failed, extracting partial evaluations...")
                eval_pattern = r'\{\s*"index"\s*:\s*\d+[^}]+\}'
                matches = re.findall(eval_pattern, repaired)
                if matches:
                    partial_evals = []
                    for m in matches:
                        try:
                            partial_evals.append(json.loads(m))
                        except:
                            pass
                    if partial_evals:
                        evaluation = {"evaluations": partial_evals, "summary": "Partial evaluation (JSON repair)"}
                        logger.info(f"[Viability] Recovered {len(partial_evals)} evaluations from malformed response")
                    else:
                        raise
                else:
                    raise
        evaluations = evaluation.get("evaluations", [])
        summary = evaluation.get("summary", "")

        logger.info(f"[Viability] {summary}")

        # Build result
        viable_products = []
        rejected = []

        for eval_item in evaluations:
            idx = eval_item.get("index", 0)
            if 1 <= idx <= len(products):
                original = products[idx - 1].copy()

                if eval_item.get("viable", False):
                    # Add viability metadata to product
                    original["viability_score"] = eval_item.get("viability_score", 0.7)
                    original["meets_requirements"] = eval_item.get("meets_requirements", {})
                    original["strengths"] = eval_item.get("strengths", [])
                    original["weaknesses"] = eval_item.get("weaknesses", [])
                    original["viability_summary"] = eval_item.get("summary", "")
                    viable_products.append(original)

                    logger.info(
                        f"[Viability] VIABLE: {original.get('name', 'Unknown')[:40]} "
                        f"(score: {original['viability_score']:.2f})"
                    )
                else:
                    rejection_reason = eval_item.get("rejection_reason", "")

                    # FALLBACK: If LLM gave unclear rejection, use keyword check
                    if not rejection_reason or rejection_reason in ("N/A", "Does not meet requirements"):
                        keyword_viable = check_keyword_viability(original, requirements, query)
                        if keyword_viable is True:
                            # Override LLM rejection - keyword check says it's viable
                            logger.info(
                                f"[Viability] OVERRIDE: Keyword check says viable despite LLM rejection: "
                                f"{original.get('name', 'Unknown')[:40]}"
                            )
                            original["viability_score"] = 0.55  # Conservative score
                            original["meets_requirements"] = {}
                            original["strengths"] = ["Matches query terms"]
                            original["weaknesses"] = ["Viability uncertain - keyword match only"]
                            original["viability_summary"] = "Viable based on keyword matching"
                            viable_products.append(original)
                            continue

                    rejected.append({
                        "name": original.get("name", "Unknown"),
                        "price": original.get("price", "N/A"),
                        "reason": rejection_reason or "Does not meet requirements"
                    })

                    logger.info(
                        f"[Viability] REJECTED: {original.get('name', 'Unknown')[:40]} - "
                        f"{rejection_reason or 'N/A'}"
                    )

        # Sort by viability score and limit
        viable_products.sort(key=lambda x: x.get("viability_score", 0), reverse=True)
        viable_products = viable_products[:max_products]

        # Record rejections to global tracker for future query refinement
        if rejected:
            try:
                from apps.services.tool_server.rejection_tracker import get_rejection_tracker
                tracker = get_rejection_tracker()

                # Extract vendor from products (all products in batch are from same vendor)
                vendor = products[0].get("vendor", "unknown") if products else "unknown"

                tracker.record_rejections(
                    vendor=vendor,
                    query=query,
                    rejections=rejected,
                    total_products=len(products)
                )
            except Exception as e:
                logger.warning(f"[Viability] Failed to record rejections: {e}")

        return {
            "viable_products": viable_products,
            "rejected": rejected,
            "stats": {
                "total_input": len(products),
                "viable_count": len(viable_products),
                "rejected_count": len(rejected)
            }
        }

    except json.JSONDecodeError as e:
        logger.error(f"[Viability] Failed to parse LLM response: {e}")
        # Fallback: Return products with keyword and price filtering
        return _heuristic_viability_filter(products, requirements, max_products, query)

    except Exception as e:
        logger.error(f"[Viability] LLM viability check failed: {e}")
        # Fallback: Return products with keyword and price filtering
        return _heuristic_viability_filter(products, requirements, max_products, query)


# ==================== LLM REASONING-BASED VIABILITY FILTER ====================
#
# This is the NEW approach that uses an LLM-generated reasoning document
# to evaluate products, instead of structured ProductRequirements fields.
#
# The reasoning document contains:
# - validity_criteria: what the product MUST be (e.g., "a living animal")
# - disqualifiers: what would make a product WRONG (e.g., "toy", "plush")
# - specifications: user-stated and recommended specs
#
# This allows flexible reasoning about ANY product category, not just electronics.
# ==================================================================================

async def filter_viable_products_with_reasoning(
    products: List[Dict[str, Any]],
    requirements_reasoning: str,
    query: str,
    max_products: int = 4
) -> Dict[str, Any]:
    """
    Filter products using LLM reasoning chain.

    This is the new approach that uses a reasoning document from Phase 1
    instead of structured ProductRequirements fields. The LLM reasons about
    each product's fundamental viability against the reasoning document.

    Args:
        products: List of extracted products with name, price, specs, etc.
        requirements_reasoning: Full YAML reasoning document from Phase 1.
            Contains: validity_criteria, disqualifiers, specifications, etc.
        query: User's original query
        max_products: Maximum products to return

    Returns:
        {
            "viable_products": [...],  # Products that pass reasoning check
            "rejected": [...],         # Products rejected with reasons
            "uncertain": [...],        # Products needing more info
            "reasoning_chain": str,    # Full LLM reasoning output
            "stats": {...}
        }
    """
    if not products:
        return {
            "viable_products": [],
            "rejected": [],
            "uncertain": [],
            "reasoning_chain": "",
            "stats": {"total_input": 0, "viable_count": 0, "rejected_count": 0, "uncertain_count": 0}
        }

    # Get model config from env
    model_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
    model_id = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
    api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    # Load viability reasoning prompt via recipe system
    prompt_template = _load_prompt_via_recipe("viability_evaluator_v2", "tools")
    if not prompt_template:
        logger.warning("[Viability:Reasoning] Prompt not found via recipe, using inline fallback")
        prompt_template = _get_inline_viability_prompt()

    # Format products for evaluation
    products_text = _format_products_for_reasoning_eval(products[:10])

    # Build full prompt
    prompt = f"""{prompt_template}

---

## User Query
{query}

---

## Requirements Reasoning (from Phase 1)

{requirements_reasoning}

---

## Products to Evaluate

{products_text}

---

Now evaluate each product against the requirements reasoning above.
Output your evaluations in YAML format as shown in the prompt template.
"""

    logger.info(f"[Viability:Reasoning] Evaluating {len(products)} products with LLM reasoning")

    # LLM call with retry logic
    import asyncio

    max_retries = 2
    last_error = None
    result = None

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    model_url,
                    json={
                        "model": model_id,
                        "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.6,
                        "max_tokens": 2000
                    },
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                response.raise_for_status()
                result = response.json()
                break  # Success, exit retry loop

        except httpx.TimeoutException as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2  # 2s, 4s backoff
                logger.warning(f"[Viability:Reasoning] Timeout, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"[Viability:Reasoning] Failed after {max_retries} attempts: {e}")
                # Fall through to fallback handling below

        except Exception as e:
            last_error = e
            logger.error(f"[Viability:Reasoning] LLM call failed: {e}")
            break  # Don't retry on non-timeout errors

    # If no result after retries, fall back
    if result is None:
        logger.info("[Viability:Reasoning] Falling back to heuristic filter after LLM failure")
        # Extract any useful info from requirements_reasoning for fallback
        fallback_reqs = _extract_fallback_requirements(requirements_reasoning)
        return _heuristic_viability_filter(products, fallback_reqs, max_products, query)

    try:
        # Parse LLM response
        llm_content = result["choices"][0]["message"]["content"].strip()
        reasoning_chain = llm_content  # Store full response for debugging

        # Parse YAML evaluations from response
        evaluations = _parse_viability_reasoning_response(llm_content)

        # Categorize by decision
        viable_products = []
        rejected = []
        uncertain = []

        for eval_item in evaluations:
            product_idx = eval_item.get("product_index", 0) - 1
            if 0 <= product_idx < len(products):
                product = products[product_idx].copy()

                # Add reasoning metadata
                product["viability_reasoning"] = eval_item.get("reasoning", {})
                product["viability_score"] = eval_item.get("score", 0.5)

                decision = eval_item.get("decision", "UNCERTAIN").upper()
                score = product["viability_score"]

                if decision == "ACCEPT":
                    viable_products.append(product)
                    logger.info(
                        f"[Viability:Reasoning] ACCEPT: {product.get('name', 'Unknown')[:40]} "
                        f"(score: {score:.2f})"
                    )
                elif decision == "REJECT":
                    product["rejection_reason"] = eval_item.get("rejection_reason", "Failed reasoning check")
                    rejected.append(product)
                    logger.info(
                        f"[Viability:Reasoning] REJECT: {product.get('name', 'Unknown')[:40]} - "
                        f"{product['rejection_reason']}"
                    )
                else:
                    # UNCERTAIN products: include if score >= 0.40 (borderline viable)
                    # These are products where the LLM wasn't confident but might still be relevant
                    if score >= 0.40:
                        viable_products.append(product)
                        logger.info(
                            f"[Viability:Reasoning] UNCERTAIN->VIABLE: {product.get('name', 'Unknown')[:40]} "
                            f"(score: {score:.2f} >= 0.40 threshold)"
                        )
                    else:
                        uncertain.append(product)
                        logger.info(
                            f"[Viability:Reasoning] UNCERTAIN: {product.get('name', 'Unknown')[:40]} "
                            f"(score: {score:.2f})"
                        )

        # Sort viable by score and limit
        viable_products.sort(key=lambda x: x.get("viability_score", 0), reverse=True)
        viable_products = viable_products[:max_products]

        return {
            "viable_products": viable_products,
            "rejected": rejected,
            "uncertain": uncertain,
            "reasoning_chain": reasoning_chain,
            "stats": {
                "total_input": len(products),
                "viable_count": len(viable_products),
                "rejected_count": len(rejected),
                "uncertain_count": len(uncertain)
            }
        }

    except Exception as e:
        logger.error(f"[Viability:Reasoning] Response parsing failed: {e}")
        # Fallback to structured filter if parsing fails
        logger.info("[Viability:Reasoning] Falling back to heuristic filter")
        fallback_reqs = _extract_fallback_requirements(requirements_reasoning)
        return _heuristic_viability_filter(products, fallback_reqs, max_products, query)


def _extract_fallback_requirements(requirements_reasoning: str) -> Dict[str, Any]:
    """
    Extract structured requirements from requirements_reasoning text for fallback.

    When the viability reasoning LLM fails, we can still use information from
    the requirements reasoning document to inform the heuristic filter.

    Args:
        requirements_reasoning: YAML text from requirements reasoning step

    Returns:
        Dict with extracted requirements for heuristic filter
    """
    if not requirements_reasoning:
        return {}

    import yaml

    fallback_reqs = {}

    try:
        # Try to parse the YAML
        # Find YAML block if wrapped in ```yaml
        text = requirements_reasoning
        if "```yaml" in text:
            import re
            yaml_match = re.search(r'```yaml\s*(.*?)```', text, re.DOTALL)
            if yaml_match:
                text = yaml_match.group(1)

        parsed = yaml.safe_load(text)
        if not isinstance(parsed, dict):
            return {}

        # Extract useful fields for heuristic filter
        validity = parsed.get("validity_criteria", {})
        if validity.get("must_be"):
            fallback_reqs["core_requirement"] = validity["must_be"]

        if validity.get("must_have"):
            fallback_reqs["hard_requirements"] = validity["must_have"]

        disqualifiers = parsed.get("disqualifiers", {})
        if disqualifiers.get("wrong_category"):
            fallback_reqs["wrong_categories"] = disqualifiers["wrong_category"]

        if disqualifiers.get("red_flags"):
            fallback_reqs["red_flags"] = disqualifiers["red_flags"]

        specs = parsed.get("specifications", {})
        if specs.get("user_stated"):
            fallback_reqs["user_explicit_requirements"] = specs["user_stated"]

        query_understanding = parsed.get("query_understanding", {})
        if query_understanding.get("user_intent"):
            fallback_reqs["intent"] = query_understanding["user_intent"]

        logger.info(f"[Viability:Fallback] Extracted {len(fallback_reqs)} fields from requirements reasoning")

    except Exception as e:
        logger.warning(f"[Viability:Fallback] Could not parse requirements reasoning: {e}")

    return fallback_reqs


def _format_products_for_reasoning_eval(products: List[Dict[str, Any]]) -> str:
    """Format products for the reasoning-based viability evaluation."""
    lines = []
    for i, p in enumerate(products, 1):
        name = p.get("name", "Unknown")
        price = p.get("price", "N/A")
        vendor = p.get("vendor", "N/A")
        desc = p.get("description", "") or ""
        if len(desc) > 300:
            desc = desc[:300] + "..."

        # Build specs summary
        specs = p.get("specs", {}) or {}
        specs_text = ", ".join(f"{k}: {v}" for k, v in specs.items() if v) if specs else "N/A"

        # Extract URL info
        url = p.get("url", "")
        url_info = ""
        if url:
            from urllib.parse import urlparse
            path = urlparse(url).path
            if path and len(path) > 5:
                url_info = f"\n   URL path: {path[:150]}"

        lines.append(f"""
**Product {i}:**
- Name: {name}
- Price: {price}
- Vendor: {vendor}
- Description: {desc}
- Specs: {specs_text}{url_info}
""")

    return "\n".join(lines)


def _parse_viability_reasoning_response(response: str) -> List[Dict[str, Any]]:
    """
    Parse YAML evaluations from the viability reasoning LLM response.

    Handles various formats including:
    - Multiple YAML blocks with ```yaml markers
    - Inline YAML after "```yaml" markers
    - Plain YAML without markers
    """
    import yaml

    evaluations = []

    # Try to find YAML blocks
    yaml_pattern = r'```yaml\s*(.*?)```'
    yaml_blocks = re.findall(yaml_pattern, response, re.DOTALL)

    if yaml_blocks:
        for block in yaml_blocks:
            try:
                # Use safe_load_all to handle multiple YAML documents (separated by ---)
                for parsed in yaml.safe_load_all(block):
                    if isinstance(parsed, dict):
                        evaluations.append(parsed)
                    elif isinstance(parsed, list):
                        evaluations.extend(parsed)
            except yaml.YAMLError as e:
                logger.warning(f"[Viability:Reasoning] YAML parse error: {e}")
                continue
    else:
        # Try to parse entire response as YAML
        try:
            # Find product_index patterns to extract evaluations
            eval_pattern = r'product_index:\s*(\d+).*?decision:\s*"?(\w+)"?.*?score:\s*([\d.]+)'
            matches = re.findall(eval_pattern, response, re.DOTALL | re.IGNORECASE)

            for match in matches:
                product_idx, decision, score = match
                # Try to extract reasoning and rejection_reason
                eval_block = {
                    "product_index": int(product_idx),
                    "decision": decision.upper(),
                    "score": float(score),
                    "reasoning": {},
                    "rejection_reason": ""
                }

                # Look for rejection_reason if REJECT
                if decision.upper() == "REJECT":
                    reason_match = re.search(
                        rf'product_index:\s*{product_idx}.*?rejection_reason:\s*"([^"]*)"',
                        response, re.DOTALL | re.IGNORECASE
                    )
                    if reason_match:
                        eval_block["rejection_reason"] = reason_match.group(1)

                evaluations.append(eval_block)

        except Exception as e:
            logger.warning(f"[Viability:Reasoning] Failed to parse response: {e}")

    return evaluations


def _get_inline_viability_prompt() -> str:
    """Load viability reasoning prompt from file, with inline fallback."""
    # Try to load from file first
    prompt = _load_prompt("viability_evaluator_v2")
    if prompt:
        return prompt

    # Fallback inline prompt if file not found
    return """# Product Viability Reasoning

You are evaluating whether extracted products match what the user is actually looking for.

IMPORTANT: Do NOT reject products because you don't recognize a model number or spec.
Your job is to check product TYPE and user requirements - NOT to validate if specs exist.
Retailers have current databases; your training data may be outdated.

For each product, reason through:
1. Is this fundamentally the right type of product?
2. Would the user be satisfied receiving this?
3. Does it meet the stated requirements?

Output a YAML list. Each item is one product:
```yaml
- product_index: 1
  product_name: "[name]"
  reasoning:
    fundamental_check: "[Is this the right TYPE of product?]"
    user_satisfaction: "[Would user be happy with this?]"
    requirements_check: "[Does it meet requirements?]"
  decision: "ACCEPT" | "REJECT" | "UNCERTAIN"
  score: 0.0-1.0
  rejection_reason: "[Only if rejected]"
```

REJECT only if:
- Product is wrong TYPE (e.g., toy when they want real item)
- Product fundamentally fails must_be criterion
- User would clearly be disappointed

ACCEPT if:
- Matches must_be criterion (right product type)
- Has must_have characteristics
- No disqualifiers present
"""


def _format_requirements(requirements: Dict[str, Any], query: str = "") -> tuple:
    """
    Format requirements into hard requirements vs nice-to-haves.

    Separates user-explicit requirements (must have) from forum recommendations
    (nice to have). This prevents rejecting valid products that meet user needs
    but don't match forum-recommended specific models.

    Args:
        requirements: Intelligence dict from Phase 1
        query: Original user query for context

    Returns:
        Tuple of (hard_requirements_text, nice_to_haves_text)
    """
    if not requirements:
        return ("No specific requirements provided", "None")

    hard_lines = []
    nice_lines = []
    query_lower = query.lower() if query else ""

    # 0. FUNDAMENTAL: Extract what user is searching for from query
    # This is the PRIMARY hard requirement - product must BE this thing
    if query:
        # Extract the subject from query by removing common action words
        subject = query_lower
        for remove_word in ["find", "buy", "get", "search", "looking for", "for sale",
                            "online", "near me", "cheap", "best", "good", "where to",
                            "can you", "please", "i want", "i need", "show me"]:
            subject = subject.replace(remove_word, "")
        subject = " ".join(subject.split()).strip()  # Clean whitespace

        if subject and len(subject) > 2:
            hard_lines.append(f"- Product must be: {subject} (from user query - reject if product is something else entirely)")

    # 1. User explicit requirements → HARD (must have)
    user_explicit = requirements.get("user_explicit_requirements", [])
    if user_explicit:
        for req in user_explicit[:5]:
            hard_lines.append(f"- {req} (user specified)")

    # 2. Hard requirements → HARD (must have)
    hard_reqs = requirements.get("hard_requirements", [])
    if hard_reqs:
        for req in hard_reqs[:5]:
            if req not in user_explicit:  # Avoid duplicates
                hard_lines.append(f"- {req}")

    # 3. Key requirements - check if they match user's words
    # If requirement uses words from user query → HARD, otherwise → NICE
    key_reqs = requirements.get("key_requirements", [])
    for req in key_reqs[:5]:
        req_lower = req.lower()
        # Check if any significant word from the requirement is in the query
        req_words = [w for w in req_lower.split() if len(w) > 3]
        matches_query = any(word in query_lower for word in req_words)

        if matches_query:
            if req not in user_explicit and req not in hard_reqs:
                hard_lines.append(f"- {req}")
        else:
            nice_lines.append(f"- {req} (recommended)")

    # 4. Forum recommendations → NICE TO HAVE
    forum_recs = requirements.get("forum_recommendations", [])
    if forum_recs:
        for rec in forum_recs[:5]:
            if rec not in nice_lines:
                nice_lines.append(f"- {rec} (from forums)")

    # 5. Nice to haves → NICE TO HAVE
    nice_to_haves = requirements.get("nice_to_haves", [])
    if nice_to_haves:
        for item in nice_to_haves[:5]:
            nice_lines.append(f"- {item}")

    # 6. Price range - if user mentioned budget/price/under → HARD
    if "price_range" in requirements:
        pr = requirements["price_range"]
        budget_in_query = any(word in query_lower for word in ["budget", "under", "cheap", "affordable", "$"])
        if isinstance(pr, dict):
            budget_text = f"Budget: ${pr.get('min', 0)} - ${pr.get('max', 'unlimited')}"
        else:
            budget_text = f"Budget: {pr}"

        if budget_in_query:
            hard_lines.append(f"- {budget_text}")
        else:
            nice_lines.append(f"- {budget_text} (recommended range)")

    # 7. Recommended brands → NICE TO HAVE (unless user mentioned)
    if "recommended_brands" in requirements:
        brands = requirements["recommended_brands"][:5]
        brands_text = f"Preferred brands: {', '.join(brands)}"
        # Check if user mentioned any brand
        brand_in_query = any(brand.lower() in query_lower for brand in brands)
        if brand_in_query:
            hard_lines.append(f"- {brands_text}")
        else:
            nice_lines.append(f"- {brands_text}")

    hard_text = "\n".join(hard_lines) if hard_lines else "None specified - accept any matching product"
    nice_text = "\n".join(nice_lines) if nice_lines else "None"

    return (hard_text, nice_text)


def _heuristic_viability_filter(
    products: List[Dict[str, Any]],
    requirements: Dict[str, Any],
    max_products: int = 4,
    query: str = ""
) -> Dict[str, Any]:
    """
    Fallback heuristic viability filter when LLM fails.
    Uses price checking and keyword matching against query terms.
    """
    logger.info("[Viability] Using heuristic fallback filter")

    # Extract budget from requirements
    max_budget = None
    if "price_range" in requirements:
        pr = requirements["price_range"]
        if isinstance(pr, dict):
            max_budget = pr.get("max")
        elif isinstance(pr, (int, float)):
            max_budget = pr

    viable_products = []
    rejected = []

    for product in products:
        # Parse price
        price_str = str(product.get("price", "$0"))
        try:
            price = float(price_str.replace("$", "").replace(",", ""))
        except ValueError:
            price = 0

        # Basic viability check
        is_viable = True
        rejection_reason = None

        # Check budget
        if max_budget and price > max_budget:
            is_viable = False
            rejection_reason = f"Over budget (${price:.0f} > ${max_budget})"

        # Check for valid price
        if price <= 0:
            is_viable = False
            rejection_reason = "Invalid or missing price"

        # Use keyword viability check if query provided
        if is_viable and query:
            keyword_result = check_keyword_viability(product, requirements, query)
            if keyword_result is False:
                is_viable = False
                rejection_reason = "Does not match query terms"

        if is_viable:
            product_copy = product.copy()
            # Use keyword check to determine score
            if query:
                keyword_result = check_keyword_viability(product, requirements, query)
                product_copy["viability_score"] = 0.65 if keyword_result is True else 0.5
            else:
                product_copy["viability_score"] = 0.5  # Default score for heuristic
            product_copy["meets_requirements"] = {}
            product_copy["strengths"] = ["Passed heuristic filter"]
            product_copy["weaknesses"] = ["Viability not fully evaluated (LLM fallback)"]
            viable_products.append(product_copy)
        else:
            rejected.append({
                "name": product.get("name", "Unknown"),
                "price": product.get("price", "N/A"),
                "reason": rejection_reason or "Did not pass heuristic filter"
            })

    # Sort by viability score then price
    def sort_key(product):
        """Sort by viability score (desc) then price (asc)."""
        score = product.get("viability_score", 0)
        try:
            price_str = str(product.get("price", "$99999")).replace("$", "").replace(",", "")
            price = float(price_str) if price_str else 99999.0
        except (ValueError, TypeError):
            price = 99999.0
        return (-score, price)  # Negative score for descending

    viable_products.sort(key=sort_key)
    viable_products = viable_products[:max_products]

    return {
        "viable_products": viable_products,
        "rejected": rejected,
        "stats": {
            "total_input": len(products),
            "viable_count": len(viable_products),
            "rejected_count": len(rejected)
        }
    }


# Quick test
if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)

    async def test():
        test_products = [
            {"name": "Dell G15 Gaming", "price": "$1,199", "description": "RTX 4060, 16GB RAM, 512GB SSD"},
            {"name": "Dell Inspiron 15", "price": "$599", "description": "Intel UHD Graphics, 8GB RAM"},
            {"name": "ASUS TUF Gaming", "price": "$1,099", "description": "RTX 4060, 16GB RAM, 1TB SSD"},
            {"name": "Alienware m18", "price": "$2,999", "description": "RTX 4090, 64GB RAM, 2TB SSD"},
        ]

        test_requirements = {
            "key_requirements": ["RTX 4060 or better", "16GB RAM minimum", "Under $2000"],
            "price_range": {"min": 800, "max": 2000},
            "specs_discovered": {"gpu": "RTX 4060", "ram": "16GB"}
        }

        result = await filter_viable_products(
            products=test_products,
            requirements=test_requirements,
            query="laptop with NVIDIA GPU for AI",
            max_products=4
        )

        print(f"\n\nRESULTS: {result['stats']}")
        print("\nVIABLE:")
        for p in result["viable_products"]:
            print(f"  - {p['name']} ({p['price']}) - Score: {p.get('viability_score', 0):.2f}")

        print("\nREJECTED:")
        for r in result["rejected"]:
            print(f"  - {r['name']} ({r['price']}) - {r['reason']}")

    asyncio.run(test())
