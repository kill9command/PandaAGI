"""
orchestrator/product_extractor.py

DEPRECATED (2026-01-02): This module contains hardcoded domain-specific CSS selectors
which violate the LLM-first architecture. See CLAUDE.md.

Use instead:
- orchestrator/page_intelligence/service.py (PageIntelligenceService)
- orchestrator/smart_extractor.py (SmartExtractor)

These learn selectors dynamically from page content instead of hardcoding per-domain.

The domain-specific selectors below (amazon.com, bestbuy.com, newegg.com, dell.com, etc.)
should NOT be maintained - they break when retailers update their HTML and require
code changes for new retailers.

LLM-powered product extraction from web pages.

Extracts structured product data (price, seller, availability) from HTML
content and returns ProductClaim objects for the claim registry.
"""
from __future__ import annotations

import warnings
warnings.warn(
    "product_extractor.py is deprecated. Use page_intelligence.service.PageIntelligenceService "
    "or smart_extractor.SmartExtractor instead. See CLAUDE.md for architecture principles.",
    DeprecationWarning,
    stacklevel=2
)

import json
import logging
import os
import re
from typing import List, Optional, Dict, Any
from datetime import datetime

from bs4 import BeautifulSoup
import httpx

from apps.services.tool_server.product_claim_schema import ProductClaim
from apps.services.tool_server.shared.llm_utils import load_prompt_via_recipe as _load_prompt_via_recipe

logger = logging.getLogger(__name__)


def _load_prompt(prompt_name: str) -> str:
    """Load prompt - maps legacy names to recipe names."""
    return _load_prompt_via_recipe(prompt_name, "tools")


def _extract_product_links(html: str, base_url: str) -> Dict[str, str]:
    """
    Extract product links from HTML before text cleaning.

    Args:
        html: Raw HTML content
        base_url: Base URL for resolving relative links

    Returns:
        Dict mapping product text/title to full URL
    """
    product_urls = {}
    try:
        from urllib.parse import urljoin
        soup = BeautifulSoup(html, 'html.parser')

        # Use retailer-specific selectors for better accuracy
        from urllib.parse import urlparse
        domain = urlparse(base_url).netloc

        if "amazon.com" in domain:
            product_selectors = [
                'h2.s-size-mini a.s-link',  # Amazon search result title
                'h2 a.a-link-normal',
                'a[href*="/dp/"]',
                'a[href*="/gp/product/"]',
            ]
        elif "bestbuy.com" in domain:
            product_selectors = [
                'h4.sku-title a',  # Best Buy product title link
                'a.sku-header',
                'a[href*="/site/"][href*=".p"]',  # Product page URLs
            ]
        elif "newegg.com" in domain:
            product_selectors = [
                'a.item-title',  # Newegg product title
                'a[href*="/Item/"]',
                'a[href*="/p/"]',
            ]
        elif "dell.com" in domain:
            product_selectors = [
                'a[href*="/en-us/shop/"][href*="/spd/"]',  # Dell product detail pages
                'a.ps-product-title',  # Product title links
                'a[data-testid="product-title"]',
                'h3.ps-title a',
                'a[href*="/pd/"]',  # Product detail shorthand
            ]
        elif "lenovo.com" in domain:
            product_selectors = [
                'a[href*="/p/laptops/"][href*="?orgRef"]',  # Lenovo product links with tracking
                'a.product_title',
                'a[data-product-id]',
                'a[href*="/p/"][href*="laptops"]',
                'h3.product-title a',
            ]
        elif "hp.com" in domain:
            product_selectors = [
                'a[href*="/shop/"][href*="/pdp/"]',  # HP product detail pages
                'a.product-title-link',
                'a[data-product-id]',
            ]
        else:
            # Generic fallback
            product_selectors = [
                'a[data-product-id]',
                'a.product-link',
                'a.product-title',
                'a[href*="/product/"]',
                'a[href*="/item/"]',
                'h2 > a[href*="/p/"]',
                'h3 > a[href*="/p/"]',
            ]

        for selector in product_selectors:
            for link in soup.select(selector):
                href = link.get('href')
                if not href or href.startswith('#') or href.startswith('javascript:'):
                    continue

                # Get link text (product name)
                link_text = link.get_text(strip=True)
                if not link_text or len(link_text) < 5:  # Skip very short text
                    continue

                # Resolve relative URLs
                full_url = urljoin(base_url, href)

                # Skip non-product URLs
                if any(x in full_url.lower() for x in ['/search', '/category', '/categories', '/brands', '/help', '/account']):
                    continue

                product_urls[link_text] = full_url

        logger.info(f"Extracted {len(product_urls)} potential product URLs")

    except Exception as e:
        logger.warning(f"Failed to extract product links: {e}")

    return product_urls


def _clean_html_to_text(html: str, base_url: str, max_tokens: int = 6000, product_urls: Optional[Dict[str, str]] = None) -> str:
    """
    Clean HTML and extract text content, preserving product URLs.

    Focuses on extracting product-rich content by prioritizing product containers
    and removing navigation/header/footer noise.

    Args:
        html: Raw HTML content
        base_url: Source URL for retailer-specific parsing
        max_tokens: Approximate token limit (1 token ≈ 4 chars) - increased default to 6000
        product_urls: Optional dict of product text -> URL mapping to preserve

    Returns:
        Cleaned text content with product URLs preserved, truncated to max_tokens
    """
    try:
        soup = BeautifulSoup(html, 'html.parser')

        # Remove script, style, and navigation elements
        for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe']):
            element.decompose()

        # Try to extract product-specific containers first (better signal-to-noise)
        # Use retailer-specific selectors for better accuracy
        from urllib.parse import urlparse
        domain = urlparse(base_url).netloc

        if "amazon.com" in domain:
            # Amazon-specific: Use data-asin attribute (actual products)
            product_containers = soup.select('div[data-component-type="s-search-result"], div[data-asin]')
        elif "bestbuy.com" in domain:
            # Best Buy-specific: Use sku-item class
            product_containers = soup.select('li.sku-item, div.sku-item')
        elif "newegg.com" in domain:
            # Newegg-specific: Use item-container class
            product_containers = soup.select('div.item-container, div.item-cell')
        elif "dell.com" in domain:
            # Dell-specific: Product stack items
            product_containers = soup.select('div.ps-stack-item, article.product-card, div[data-testid="product-card"]')
        elif "lenovo.com" in domain:
            # Lenovo-specific: Product tiles
            product_containers = soup.select('div.product-tile, div.product-card, article[data-product-id]')
        elif "hp.com" in domain:
            # HP-specific: Product cards
            product_containers = soup.select('div.product-card, div[data-product-id], article.product-item')
        else:
            # Generic fallback - expanded selectors
            product_containers = soup.select(
                '[data-product], [data-product-id], '
                '[class*="product-item"], [class*="product-card"], '
                '[class*="product-tile"], [class*="ProductCard"], '
                'article.product, div.product-listing'
            )

        if product_containers and len(product_containers) > 2:
            # Extract text from product containers only
            logger.info(f"Found {len(product_containers)} product containers, extracting from those")
            text_parts = []
            for container in product_containers[:20]:  # Limit to first 20 products to avoid timeout
                container_text = container.get_text(separator=' ', strip=True)
                if container_text:
                    text_parts.append(container_text)
            text = '\n\n'.join(text_parts)
        else:
            # Fallback to full page text
            text = soup.get_text(separator='\n', strip=True)

        # Clean up whitespace
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)

        # Append product URLs section if available
        if product_urls:
            url_section = "\n\n=== PRODUCT URLS ===\n"
            for product_text, url in list(product_urls.items())[:25]:  # Increased from 20 to 25
                # Truncate very long product names to save tokens
                display_name = product_text[:80] + "..." if len(product_text) > 80 else product_text
                url_section += f"{display_name}: {url}\n"
            text += url_section

        # Truncate to approximate token limit (1 token ≈ 4 chars)
        max_chars = max_tokens * 4
        if len(text) > max_chars:
            # Try to truncate at a sentence boundary
            truncate_at = text.rfind('.', 0, max_chars)
            if truncate_at > max_chars * 0.8:  # Only use if close to limit
                text = text[:truncate_at + 1] + "\n[... truncated ...]"
            else:
                text = text[:max_chars] + "\n[... truncated ...]"

        return text

    except Exception as e:
        logger.warning(f"HTML cleaning failed: {e}")
        # Fallback: simple regex stripping
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_tokens * 4]


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON object from text that may contain markdown code blocks."""
    # Try to find JSON in code blocks first
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _build_extraction_prompt(text_content: str, query: str, url: str) -> str:
    """
    Build LLM prompt for product extraction.

    Args:
        text_content: Cleaned text from web page
        query: Original search query
        url: Source URL

    Returns:
        Prompt string for LLM
    """
    # Load base prompt from file
    base_prompt = _load_prompt("product_extractor")
    if not base_prompt:
        # Fallback inline prompt if file not found
        base_prompt = """You are a product data extraction assistant. Extract structured product listings from web page content.

Extract: title, price, currency, url, seller_name, in_stock, description, confidence.
Optional: seller_type, item_type, breed_or_variant, age, price_note.

Output ONLY valid JSON: {"products": [...]}"""

    return f"""{base_prompt}

---

User's search query: "{query}"
Page URL: {url}

Web page content:
---
{text_content}
---

Now extract products:"""


def _validate_product_url(
    llm_url: Optional[str],
    product_title: str,
    product_urls: Dict[str, str],
    fallback_url: str
) -> str:
    """
    Validate LLM-provided URL against extracted URLs to prevent hallucination.

    Args:
        llm_url: URL provided by LLM (may be hallucinated)
        product_title: Product title for fuzzy matching
        product_urls: Dict of product text -> URL extracted from HTML
        fallback_url: Page URL to use if no valid URL found

    Returns:
        Validated URL (either from product_urls or fallback_url)
    """
    # If no LLM URL provided, use fallback
    if not llm_url:
        return fallback_url

    # Check if LLM URL exactly matches one of the extracted URLs
    extracted_url_set = set(product_urls.values())
    if llm_url in extracted_url_set:
        logger.debug(f"URL validated (exact match): {llm_url}")
        return llm_url

    # Check if LLM URL is the same as fallback (page URL) - that's fine
    if llm_url == fallback_url:
        return llm_url

    # Try to match product title to extracted URLs (fuzzy match)
    title_lower = product_title.lower().strip()
    for link_text, extracted_url in product_urls.items():
        link_text_lower = link_text.lower().strip()
        # Check for significant overlap
        if title_lower in link_text_lower or link_text_lower in title_lower:
            logger.info(f"URL matched via title: '{product_title}' -> {extracted_url}")
            return extracted_url

    # URL appears to be hallucinated - log warning and use fallback
    logger.warning(
        f"Rejecting potentially hallucinated URL: {llm_url} "
        f"(not found in {len(product_urls)} extracted URLs). "
        f"Using fallback: {fallback_url}"
    )
    return fallback_url


async def extract_products_from_html(
    html: str,
    url: str,
    query: str,
    llm_url: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_api_key: Optional[str] = None
) -> List[ProductClaim]:
    """
    Use LLM to extract product listings from HTML.

    Args:
        html: Raw HTML content
        url: Source page URL
        query: Original search query
        llm_url: LLM endpoint (defaults to SOLVER_URL env var)
        llm_model: Model ID (defaults to SOLVER_MODEL_ID env var)
        llm_api_key: API key (defaults to SOLVER_API_KEY env var)

    Returns:
        List of ProductClaim objects with confidence scores
    """
    # Default to env vars
    llm_url = llm_url or os.getenv("SOLVER_URL", "http://localhost:8000/v1/chat/completions")
    llm_model = llm_model or os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
    llm_api_key = llm_api_key or os.getenv("SOLVER_API_KEY", "qwen-local")

    logger.info(f"Extracting products from {url}")

    # Step 1: Extract product URLs from HTML (before stripping tags)
    product_urls = _extract_product_links(html, url)

    # Step 2: Clean HTML to text, preserving extracted URLs
    text_content = _clean_html_to_text(html, base_url=url, max_tokens=6000, product_urls=product_urls)

    if not text_content.strip():
        logger.warning(f"No text content extracted from {url}")
        return []

    # Debug: Log text preview for diagnosis
    logger.info(f"Text content preview ({len(text_content)} chars): {text_content[:500]}...")

    # Step 3: Build extraction prompt
    prompt = _build_extraction_prompt(text_content, query, url)

    # Step 3: Call LLM
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:  # Increased from 30s to 60s for large pages
            response = await client.post(
                llm_url,
                headers={
                    "Authorization": f"Bearer {llm_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,  # Low temp for structured extraction
                    "max_tokens": 3000  # Increased from 2000 to accommodate more products
                }
            )
            response.raise_for_status()

            content = response.json()["choices"][0]["message"]["content"]
            logger.info(f"LLM extraction response: {content[:200]}...")

            # Parse JSON from response
            extraction_data = _extract_json_from_text(content)
            if not extraction_data or "products" not in extraction_data:
                logger.warning(f"No products in LLM response")
                return []

            # Step 4: Convert to ProductClaim objects
            products = []
            for product_dict in extraction_data["products"]:
                try:
                    # Validate URL against extracted product_urls to prevent hallucination
                    llm_url = product_dict.get("url")
                    validated_url = _validate_product_url(
                        llm_url=llm_url,
                        product_title=product_dict.get("title", ""),
                        product_urls=product_urls,
                        fallback_url=url
                    )

                    product = ProductClaim(
                        title=product_dict.get("title", "Unknown Product"),
                        price=product_dict.get("price"),
                        currency=product_dict.get("currency", "USD"),
                        url=validated_url,
                        seller_name=product_dict.get("seller_name", "Unknown"),
                        seller_type=product_dict.get("seller_type", "unknown"),
                        in_stock=product_dict.get("in_stock", True),
                        description=product_dict.get("description", ""),
                        item_type=product_dict.get("item_type", "unknown"),
                        breed_or_variant=product_dict.get("breed_or_variant"),
                        age=product_dict.get("age"),
                        price_note=product_dict.get("price_note"),
                        source_url=url,
                        extracted_at=datetime.utcnow().isoformat() + "Z",
                        confidence=product_dict.get("confidence", 0.7),
                        ttl_hours=24,
                        claim_type="product_listing"
                    )
                    products.append(product)
                    logger.info(
                        f"Extracted: {product.title} - ${product.price} "
                        f"(confidence: {product.confidence:.2f})"
                    )

                except Exception as e:
                    logger.warning(f"Failed to create ProductClaim: {e}")
                    continue

            logger.info(f"Successfully extracted {len(products)} products from {url}")
            return products

    except Exception as e:
        logger.error(f"Product extraction failed for {url}: {e}")
        return []


def filter_products_by_relevance(
    products: List[ProductClaim],
    query: str,
    min_confidence: float = 0.5
) -> List[ProductClaim]:
    """
    Filter products by relevance to query and confidence threshold.

    Args:
        products: List of extracted products
        query: Original search query
        min_confidence: Minimum confidence threshold (0.0-1.0)

    Returns:
        Filtered list of products
    """
    filtered = []
    query_lower = query.lower()

    for product in products:
        # Filter by confidence
        if product.confidence < min_confidence:
            logger.info(
                f"Skipping low-confidence product: {product.title} "
                f"(confidence: {product.confidence:.2f})"
            )
            continue

        # Check relevance (basic keyword matching)
        product_text = (
            f"{product.title} {product.description} "
            f"{product.breed_or_variant or ''} {product.item_type}"
        ).lower()

        # Extract key terms from query
        query_terms = [term for term in query_lower.split()
                      if len(term) > 3 and term not in ["find", "search", "buy", "sale"]]

        # Check if at least one key term matches
        if query_terms:
            has_match = any(term in product_text for term in query_terms)
            if not has_match:
                logger.info(
                    f"Skipping irrelevant product: {product.title} "
                    f"(no match for query terms: {query_terms})"
                )
                continue

        filtered.append(product)

    logger.info(f"Filtered {len(products)} products → {len(filtered)} relevant products")
    return filtered
