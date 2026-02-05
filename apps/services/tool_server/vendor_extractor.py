"""
LLM-based vendor and intelligence extraction for Phase 1.

Extracts vendor recommendations, spec requirements, and quality criteria
from community discussions, forums, and expert content.

Uses human-like reading approach: scan → focus → validate
"""

import json
import logging
from typing import Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)


VENDOR_EXTRACTION_PROMPT = """You are extracting vendor and product intelligence from web content.

INPUT TEXT:
{text}

PRODUCT: {product}

Extract the following information:

1. VENDOR RECOMMENDATIONS: Any mentioned vendors, stores, websites, or sources where this product can be purchased
   - Include vendor names, URLs if mentioned, vendor types (breeder/store/marketplace/classified)
   - Note if vendor is recommended or warned against
   - Count how many times vendor is mentioned

2. SPEC REQUIREMENTS: What specifications or characteristics matter for this product
   - Age requirements (for animals)
   - Technical specs (for electronics)
   - Size, material, quality indicators
   - Mark importance level (critical/important/nice-to-have)

3. QUALITY CRITERIA: What makes a good vendor or product in this category
   - Prefer breeders over stores?
   - Check for certifications?
   - Avoid certain sources?

4. PRICE INTELLIGENCE: What are normal/reasonable price ranges
   - Normal price range
   - Premium price range
   - Warning signs (too cheap/overpriced)

5. COMMUNITY WISDOM: Direct advice, tips, or warnings
   - What to look for
   - What to avoid
   - Red flags

OUTPUT FORMAT (JSON):
{{
  "vendors": [
    {{
      "name": "vendor name",
      "url": "domain.com" or null,
      "type": "breeder|pet_store|marketplace|classified|online_retailer|specialty_store",
      "mentioned_count": 1,
      "sentiment": "positive|negative|neutral",
      "quality_signals": ["recommended_by_reddit", "expert_approved", etc]
    }}
  ],
  "specs_required": {{
    "spec_name": {{
      "requirement": "description of requirement",
      "importance": 0.0-1.0,
      "reason": "why this matters"
    }}
  }},
  "quality_criteria": {{
    "criterion_description": 0.0-1.0  // weight/importance
  }},
  "price_intelligence": {{
    "normal_range": [min, max],
    "premium_range": [min, max] or null,
    "too_cheap_warning": threshold or null
  }},
  "community_wisdom": [
    "direct quote or paraphrased advice"
  ]
}}

If information is not found, use empty arrays/objects. Extract only factual information from the text.
"""


PRODUCT_EXTRACTION_PROMPT = """You are extracting product listing information from web content.

INPUT TEXT:
{text}

PRODUCT BEING SEARCHED: {product}

SOURCE URL: {url}

VENDOR: {vendor}

Extract the following for any product listings found:

1. PRODUCT DETAILS:
   - Title/name
   - Price (extract number and currency)
   - Availability (in_stock/out_of_stock/contact_seller/preorder)
   - Direct product URL if different from source URL

2. PRODUCT SPECS:
   - Extract any specifications mentioned (age, size, color, model, etc.)
   - Match format to common spec names when possible

3. SHIPPING/LOCATION:
   - Shipping info
   - Location if local pickup
   - Delivery timeframe

OUTPUT FORMAT (JSON):
{{
  "products": [
    {{
      "title": "product title",
      "price": number or null,
      "currency": "USD|EUR|GBP" or null,
      "availability": "in_stock|out_of_stock|contact_seller|preorder|unknown",
      "url": "direct product URL" or null,
      "location": "city, state" or null,
      "shipping": "shipping description" or null,
      "extracted_specs": {{
        "spec_name": "value"
      }}
    }}
  ]
}}

If no products found, return empty array. Extract only products relevant to the search.
"""


async def extract_vendor_intelligence(
    text: str,
    product: str,
    llm_url: str,
    llm_model: str,
    llm_api_key: str
) -> Dict:
    """
    Use LLM to extract vendor intelligence from text content.

    Args:
        text: Page content (cleaned text)
        product: Product being searched
        llm_url: LLM API endpoint
        llm_model: Model identifier
        llm_api_key: API key

    Returns:
        Extracted intelligence dict
    """
    # Truncate text to fit in context
    max_chars = 8000
    if len(text) > max_chars:
        text = text[:max_chars] + "..."

    prompt = VENDOR_EXTRACTION_PROMPT.format(
        text=text,
        product=product
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                llm_url,
                json={
                    "model": llm_model,
                    "messages": [
                        {"role": "system", "content": "You extract structured product intelligence from text."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2000
                },
                headers={"Authorization": f"Bearer {llm_api_key}"}
            )

            if response.status_code != 200:
                logger.error(f"[VendorExtractor] LLM request failed: {response.status_code}")
                return _empty_intelligence()

            result = response.json()
            content = result["choices"][0]["message"]["content"]

            # Parse JSON from content
            # Handle markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            extracted = json.loads(content)
            logger.info(f"[VendorExtractor] Extracted {len(extracted.get('vendors', []))} vendors")

            return extracted

    except Exception as e:
        logger.error(f"[VendorExtractor] Extraction failed: {e}")
        return _empty_intelligence()


async def extract_product_listings(
    text: str,
    product: str,
    url: str,
    vendor: str,
    llm_url: str,
    llm_model: str,
    llm_api_key: str
) -> List[Dict]:
    """
    Use LLM to extract product listings from page content.

    Args:
        text: Page content (cleaned text)
        product: Product being searched
        url: Source URL
        vendor: Vendor name
        llm_url: LLM API endpoint
        llm_model: Model identifier
        llm_api_key: API key

    Returns:
        List of product dicts
    """
    # Truncate text
    max_chars = 8000
    if len(text) > max_chars:
        text = text[:max_chars] + "..."

    prompt = PRODUCT_EXTRACTION_PROMPT.format(
        text=text,
        product=product,
        url=url,
        vendor=vendor
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                llm_url,
                json={
                    "model": llm_model,
                    "messages": [
                        {"role": "system", "content": "You extract product listings from web pages."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2000
                },
                headers={"Authorization": f"Bearer {llm_api_key}"}
            )

            if response.status_code != 200:
                logger.error(f"[ProductExtractor] LLM request failed: {response.status_code}")
                return []

            result = response.json()
            content = result["choices"][0]["message"]["content"]

            # Parse JSON from content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            extracted = json.loads(content)
            products = extracted.get("products", [])

            logger.info(f"[ProductExtractor] Extracted {len(products)} products from {url[:60]}")
            return products

    except Exception as e:
        logger.error(f"[ProductExtractor] Extraction failed: {e}")
        return []


def _empty_intelligence() -> Dict:
    """Return empty intelligence structure"""
    return {
        "vendors": [],
        "specs_required": {},
        "quality_criteria": {},
        "price_intelligence": {},
        "community_wisdom": []
    }


def merge_intelligence(intelligence_list: List[Dict]) -> Dict:
    """
    Merge multiple intelligence extractions into one.

    Args:
        intelligence_list: List of intelligence dicts from different sources

    Returns:
        Merged intelligence dict
    """
    merged = {
        "vendors": [],
        "specs_required": {},
        "quality_criteria": {},
        "price_intelligence": {
            "normal_range": [999999, 0],
            "premium_range": None,
            "too_cheap_warning": None
        },
        "community_wisdom": []
    }

    vendor_map = {}  # name -> vendor dict

    for intel in intelligence_list:
        # Merge vendors (deduplicate and aggregate mentions)
        for vendor in intel.get("vendors", []):
            name = vendor["name"]
            if name in vendor_map:
                # Increment mention count
                vendor_map[name]["mentioned_count"] += vendor.get("mentioned_count", 1)
                # Merge quality signals
                existing_signals = set(vendor_map[name].get("quality_signals", []))
                new_signals = set(vendor.get("quality_signals", []))
                vendor_map[name]["quality_signals"] = list(existing_signals | new_signals)
            else:
                vendor_map[name] = vendor.copy()

        # Merge specs (keep highest importance)
        for spec_name, spec_data in intel.get("specs_required", {}).items():
            if spec_name not in merged["specs_required"]:
                merged["specs_required"][spec_name] = spec_data
            else:
                # Keep version with higher importance
                if spec_data.get("importance", 0) > merged["specs_required"][spec_name].get("importance", 0):
                    merged["specs_required"][spec_name] = spec_data

        # Merge quality criteria (average weights)
        for criterion, weight in intel.get("quality_criteria", {}).items():
            if criterion not in merged["quality_criteria"]:
                merged["quality_criteria"][criterion] = weight
            else:
                # Average the weights
                merged["quality_criteria"][criterion] = (
                    merged["quality_criteria"][criterion] + weight
                ) / 2

        # Merge price intelligence (expand ranges)
        price_intel = intel.get("price_intelligence", {})
        if "normal_range" in price_intel and price_intel["normal_range"]:
            min_price, max_price = price_intel["normal_range"]
            merged["price_intelligence"]["normal_range"][0] = min(
                merged["price_intelligence"]["normal_range"][0], min_price
            )
            merged["price_intelligence"]["normal_range"][1] = max(
                merged["price_intelligence"]["normal_range"][1], max_price
            )

        # Collect community wisdom (deduplicate)
        for wisdom in intel.get("community_wisdom", []):
            if wisdom not in merged["community_wisdom"]:
                merged["community_wisdom"].append(wisdom)

    # Convert vendor map to list and sort by mentions
    merged["vendors"] = sorted(
        vendor_map.values(),
        key=lambda v: v.get("mentioned_count", 0),
        reverse=True
    )

    # Fix price range if still default
    if merged["price_intelligence"]["normal_range"][0] == 999999:
        merged["price_intelligence"]["normal_range"] = None

    return merged


# ============================================================================
# HUMAN-LIKE READING APPROACH (NEW: 2025-11-15)
# ============================================================================

async def extract_vendor_intelligence_human_like(
    text: str,
    url: str,
    product: str,
    llm_url: str,
    llm_model: str,
    llm_api_key: str
) -> Optional[Dict]:
    """
    Extract vendor intelligence using human-like 3-step reading.

    Uses: scan (relevance) → focus (extract) → validate

    Args:
        text: Page content
        url: Page URL
        product: Product being searched
        llm_url: LLM endpoint
        llm_model: Model ID
        llm_api_key: API key

    Returns:
        Extracted intelligence or None if page not relevant
    """
    from apps.services.tool_server.human_page_reader import read_page_like_human

    # Define extraction schema
    schema = {
        "vendors": [
            {
                "name": "str",
                "url": "str or null",
                "type": "breeder|pet_store|marketplace|classified|online_retailer|specialty_store",
                "mentioned_count": "int",
                "sentiment": "positive|negative|neutral",
                "quality_signals": ["str"]
            }
        ],
        "specs_required": {
            "spec_name": {
                "requirement": "str",
                "importance": "0.0-1.0",
                "reason": "str"
            }
        },
        "quality_criteria": {
            "criterion_description": "0.0-1.0"
        },
        "price_intelligence": {
            "normal_range": "[min, max]",
            "premium_range": "[min, max] or null",
            "too_cheap_warning": "threshold or null"
        },
        "community_wisdom": ["str"]
    }

    result = await read_page_like_human(
        text_content=text,
        url=url,
        search_goal=f"vendor recommendations and product intelligence for {product}",
        extraction_schema=schema,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        min_relevance=0.4
    )

    if not result:
        return None

    # Remove _meta field before returning
    if "_meta" in result:
        del result["_meta"]

    return result


async def extract_product_listings_human_like(
    text: str,
    url: str,
    product: str,
    vendor: str,
    llm_url: str,
    llm_model: str,
    llm_api_key: str
) -> List[Dict]:
    """
    Extract product listings using human-like 3-step reading.

    Uses: scan (relevance) → focus (extract) → validate

    Args:
        text: Page content
        url: Page URL
        product: Product being searched
        vendor: Vendor name (from URL domain)
        llm_url: LLM endpoint
        llm_model: Model ID
        llm_api_key: API key

    Returns:
        List of extracted product listings
    """
    from apps.services.tool_server.human_page_reader import read_page_like_human

    # Define extraction schema
    schema = {
        "products": [
            {
                "title": "str",
                "price": "float or null",
                "currency": "str (USD, EUR, etc)",
                "availability": "in_stock|out_of_stock|preorder|unknown",
                "url": "str or null",
                "vendor": "str",
                "extracted_specs": {
                    "spec_name": "value"
                },
                "description_snippet": "str (brief excerpt)"
            }
        ]
    }

    result = await read_page_like_human(
        text_content=text,
        url=url,
        search_goal=f"product listings for {product} on {vendor}",
        extraction_schema=schema,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        min_relevance=0.3  # Lower threshold for product pages
    )

    if not result or "products" not in result:
        return []

    return result["products"]
