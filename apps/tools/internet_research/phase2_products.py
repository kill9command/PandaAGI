"""
Phase 2: Product Finding

Uses Phase 1 intelligence to find products from 3 vendors.

Flow:
1. Build vendor list from Phase 1 hints + search if needed
2. Visit each vendor (max 3) using WebAgent for navigation
3. WebAgent navigates and extracts products using PERCEIVE-DECIDE-ACT-VERIFY loop
4. Extract products and compare to Phase 1 price expectations
5. Return products with recommendations

Architecture: Uses WebAgent (the canonical system for web navigation/extraction)
See: architecture/mcp-tool-patterns/internet-research-mcp/WEB_AGENT_ARCHITECTURE.md
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .state import ResearchState
from .browser import ResearchBrowser, get_domain

# WebAgent integration - the canonical system for web navigation
from apps.services.tool_server.web_agent import (
    WebAgent,
    WebAgentResult,
    Product as WebAgentProduct,
)
from apps.services.tool_server.site_knowledge_cache import SiteKnowledgeCache

logger = logging.getLogger(__name__)


@dataclass
class Product:
    """A product found during Phase 2."""
    name: str
    price: str
    price_numeric: Optional[float]
    vendor: str
    url: str
    in_stock: bool = True
    specs: dict = field(default_factory=dict)
    confidence: float = 0.8

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "price": self.price,
            "price_numeric": self.price_numeric,
            "vendor": self.vendor,
            "url": self.url,
            "in_stock": self.in_stock,
            "specs": self.specs,
            "confidence": self.confidence,
        }


@dataclass
class Phase2Result:
    """Output of Phase 2 product finding."""
    success: bool
    products: list[Product]

    # Context from Phase 1
    recommendation: str  # Which product is best and why
    price_assessment: str  # Are prices good based on Phase 1?

    # Metadata
    vendors_visited: list[str]
    vendors_failed: list[str]
    elapsed_seconds: float

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "products": [p.to_dict() for p in self.products],
            "recommendation": self.recommendation,
            "price_assessment": self.price_assessment,
            "vendors_visited": self.vendors_visited,
            "vendors_failed": self.vendors_failed,
            "elapsed_seconds": self.elapsed_seconds,
        }


# Common vendor domains for commerce searches
KNOWN_VENDORS = [
    "amazon.com",
    "bestbuy.com",
    "newegg.com",
    "walmart.com",
    "target.com",
    "bhphotovideo.com",
    "microcenter.com",
    "costco.com",
]


class Phase2ProductFinder:
    """
    Find products from vendors using Phase 1 intelligence.
    """

    def __init__(
        self,
        session_id: str,
        llm_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        target_vendors: int = 3,
        event_emitter = None,
        human_assist_allowed: bool = True,
    ):
        self.session_id = session_id
        self.llm_url = llm_url or os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        self.llm_model = llm_model or os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        self.llm_api_key = llm_api_key or os.getenv("SOLVER_API_KEY", "qwen-local")
        self.target_vendors = int(target_vendors)
        self.event_emitter = event_emitter
        self.human_assist_allowed = human_assist_allowed

        self.browser = ResearchBrowser(
            session_id=session_id,
            human_assist_allowed=human_assist_allowed,
        )

        # Site knowledge cache for WebAgent learning
        self._knowledge_cache = SiteKnowledgeCache()

    async def execute(
        self,
        goal: str,
        phase1_intelligence: dict,
        vendor_hints: list[str],
        search_terms: list[str],
        price_range: Optional[dict] = None,
    ) -> Phase2Result:
        """
        Find products from vendors.

        Args:
            goal: Original user query
            phase1_intelligence: Intelligence from Phase 1
            vendor_hints: Vendors mentioned in Phase 1
            search_terms: Search terms from Phase 1 (e.g., product names)
            price_range: Expected price range from Phase 1

        Returns:
            Phase2Result with products and recommendations
        """
        # Normalize inputs — may be strings from §2 template resolution
        if not isinstance(phase1_intelligence, dict):
            phase1_intelligence = {}
        if not isinstance(vendor_hints, list):
            vendor_hints = []
        if not isinstance(search_terms, list):
            search_terms = []
        if not isinstance(price_range, dict):
            price_range = None

        logger.info(f"[Phase2] Starting product search for: {goal}")
        logger.info(f"[Phase2] Vendor hints: {vendor_hints}")
        logger.info(f"[Phase2] Search terms: {search_terms}")
        logger.info(f"[Phase2] Price range: {price_range}")

        start_time = time.time()
        all_products: list[Product] = []
        vendors_visited: list[str] = []
        vendors_failed: list[str] = []

        try:
            # Step 1: Build vendor list
            vendors = await self._build_vendor_list(goal, vendor_hints, search_terms)
            logger.info(f"[Phase2] Will visit {len(vendors)} vendors: {vendors}")

            # Step 2: Visit each vendor and extract products
            for vendor_url in vendors[:self.target_vendors]:
                vendor_domain = get_domain(vendor_url)
                logger.info(f"[Phase2] Visiting vendor: {vendor_domain}")

                try:
                    products = await self._extract_from_vendor(
                        vendor_url=vendor_url,
                        goal=goal,
                        search_terms=search_terms,
                    )

                    if products:
                        all_products.extend(products)
                        vendors_visited.append(vendor_domain)
                        logger.info(f"[Phase2] Found {len(products)} products from {vendor_domain}")
                    else:
                        vendors_failed.append(vendor_domain)
                        logger.warning(f"[Phase2] No products from {vendor_domain}")

                except Exception as e:
                    logger.error(f"[Phase2] Error with {vendor_domain}: {e}")
                    vendors_failed.append(vendor_domain)

            # Step 3: Generate recommendations based on Phase 1 intelligence
            recommendation, price_assessment = await self._generate_recommendations(
                products=all_products,
                phase1_intelligence=phase1_intelligence,
                price_range=price_range,
                goal=goal,
            )

            elapsed = time.time() - start_time

            return Phase2Result(
                success=len(all_products) > 0,
                products=all_products,
                recommendation=recommendation,
                price_assessment=price_assessment,
                vendors_visited=vendors_visited,
                vendors_failed=vendors_failed,
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            logger.error(f"[Phase2] Error: {e}", exc_info=True)
            return Phase2Result(
                success=False,
                products=[],
                recommendation="",
                price_assessment="",
                vendors_visited=vendors_visited,
                vendors_failed=vendors_failed,
                elapsed_seconds=time.time() - start_time,
            )

        finally:
            await self.browser.close()

    async def _build_vendor_list(
        self,
        goal: str,
        vendor_hints: list[str],
        search_terms: list[str],
    ) -> list[str]:
        """
        Build list of vendor URLs to visit.

        Priority:
        1. Vendors mentioned in Phase 1
        2. Search for vendors if not enough
        """
        vendors = []

        # Add vendor hints (convert to URLs if needed)
        for hint in vendor_hints:
            hint_lower = hint.lower()
            # Check if it's a known vendor
            for known in KNOWN_VENDORS:
                if known.replace(".com", "") in hint_lower or hint_lower in known:
                    vendors.append(f"https://www.{known}")
                    break
            else:
                # Try to use it as-is if it looks like a domain
                if "." in hint:
                    if not hint.startswith("http"):
                        vendors.append(f"https://www.{hint}")
                    else:
                        vendors.append(hint)

        # If we don't have enough vendors, search for more
        if len(vendors) < self.target_vendors:
            search_query = f"{search_terms[0] if search_terms else goal} buy"
            logger.info(f"[Phase2] Searching for vendors: {search_query}")

            search_result = await self.browser.search(search_query)

            if search_result.success:
                for result in search_result.results:
                    url = result.get("url", "")
                    domain = get_domain(url)

                    # Check if it's a vendor domain
                    for known in KNOWN_VENDORS:
                        if known in domain:
                            vendor_url = f"https://www.{known}"
                            if vendor_url not in vendors:
                                vendors.append(vendor_url)
                            break

                    if len(vendors) >= self.target_vendors:
                        break

        # Dedupe and limit
        seen = set()
        unique_vendors = []
        for v in vendors:
            domain = get_domain(v)
            if domain not in seen:
                seen.add(domain)
                unique_vendors.append(v)

        return unique_vendors[:self.target_vendors]

    async def _extract_from_vendor(
        self,
        vendor_url: str,
        goal: str,
        search_terms: list[str],
    ) -> list[Product]:
        """
        Visit a vendor and extract products using WebAgent.

        WebAgent implements PERCEIVE-DECIDE-ACT-VERIFY loop for intelligent
        navigation and product extraction. This replaces the old hardcoded
        URL pattern + LLM text extraction approach.

        Args:
            vendor_url: Base URL of the vendor (e.g., https://www.amazon.com)
            goal: User's search goal
            search_terms: Search terms from Phase 1

        Returns:
            List of products found, or empty list if none/error
        """
        vendor_domain = get_domain(vendor_url)
        search_term = search_terms[0] if search_terms else goal

        # Build initial search URL as starting point for WebAgent
        # WebAgent may navigate further from here based on page understanding
        search_url = self._build_vendor_search_url(vendor_url, search_term)
        logger.info(f"[Phase2] Using WebAgent to navigate: {vendor_domain}")

        try:
            # Get the Playwright page from web_vision_mcp
            from apps.services.tool_server import web_vision_mcp

            # Ensure we have a page in the session
            nav_result = await web_vision_mcp.navigate(
                session_id=self.session_id,
                url=search_url,
                wait_for="networkidle",
            )

            if not nav_result.get("success"):
                logger.warning(f"[Phase2] Initial navigation failed: {nav_result.get('error')}")
                return []

            page = await web_vision_mcp.get_page(self.session_id)
            if not page:
                logger.warning(f"[Phase2] Could not get page object for {vendor_domain}")
                return []

            # Create WebAgent with the page
            agent = WebAgent(
                page=page,
                llm_url=self.llm_url,
                llm_model=self.llm_model,
                llm_api_key=self.llm_api_key,
                knowledge_cache=self._knowledge_cache,
                session_id=self.session_id,
            )

            # Let WebAgent navigate and extract products
            # It will use PERCEIVE-DECIDE-ACT-VERIFY loop to:
            # - Understand the page
            # - Navigate if needed (click filters, scroll, etc.)
            # - Extract products when appropriate
            web_result: WebAgentResult = await agent.navigate(
                url=search_url,
                goal=f"find products matching: {search_term}",
                original_query=goal,
                max_steps=5,
            )

            # Handle WebAgent determination signals
            logger.info(f"[Phase2] WebAgent result: determination={web_result.determination}, "
                       f"items_seen={web_result.items_seen}, products={len(web_result.products)}")

            if web_result.determination == "products_found":
                # Success - convert WebAgent products to Phase2 products
                return self._convert_webagent_products(web_result.products, vendor_domain)

            elif web_result.determination == "no_relevant_products":
                # Valid result: page examined but nothing matched
                # This is NOT a failure - just no matching products on this vendor
                logger.info(f"[Phase2] No relevant products on {vendor_domain}: {web_result.reason}")
                return []

            elif web_result.determination == "no_online_availability":
                # Products exist but in-store only - skip this vendor
                logger.info(f"[Phase2] {vendor_domain} has no online availability: {web_result.reason}")
                return []

            elif web_result.determination == "blocked":
                # CAPTCHA/login wall - intervention was attempted
                logger.warning(f"[Phase2] Blocked at {vendor_domain}: {web_result.reason}")
                return []

            elif web_result.determination == "wrong_page_type":
                # Not a product listing page
                logger.info(f"[Phase2] {vendor_domain} is not a product page: {web_result.reason}")
                return []

            else:  # "error" or unknown
                logger.warning(f"[Phase2] WebAgent error on {vendor_domain}: {web_result.reason}")
                return []

        except Exception as e:
            logger.error(f"[Phase2] WebAgent exception on {vendor_domain}: {e}", exc_info=True)
            return []

    def _convert_webagent_products(
        self,
        webagent_products: list[WebAgentProduct],
        vendor_domain: str,
    ) -> list[Product]:
        """Convert WebAgent products to Phase2 Product format."""
        products = []
        for wp in webagent_products:
            # Parse numeric price - handle both string and float from SelectorExtractor
            price_numeric = None
            price_display = ""
            if wp.price is not None:
                import re
                # SelectorExtractor may return float (transform: price) or string
                if isinstance(wp.price, (int, float)):
                    price_numeric = float(wp.price)
                    price_display = f"${wp.price:.2f}"
                else:
                    price_display = str(wp.price)
                    price_match = re.search(r'[\d,]+\.?\d*', price_display.replace(',', ''))
                    if price_match:
                        try:
                            price_numeric = float(price_match.group())
                        except ValueError:
                            pass

            products.append(Product(
                name=wp.name,
                price=price_display,
                price_numeric=price_numeric,
                vendor=vendor_domain,
                url=wp.url or "",
                in_stock=wp.in_stock if wp.in_stock is not None else True,
                specs={},  # WebAgent Product doesn't have specs field
                confidence=wp.confidence,
            ))

        return products

    def _build_vendor_search_url(self, vendor_url: str, search_term: str) -> str:
        """
        Build initial search URL for a vendor.

        NOTE: This provides a starting point for WebAgent navigation.
        WebAgent may navigate further from this URL using its
        PERCEIVE-DECIDE-ACT-VERIFY loop (e.g., clicking filters, sorting).

        The patterns here help WebAgent start on a search results page
        rather than the homepage, saving navigation steps.
        """
        from urllib.parse import quote_plus

        domain = get_domain(vendor_url)
        encoded = quote_plus(search_term)

        # Vendor-specific search URL patterns
        if "amazon" in domain:
            return f"https://www.amazon.com/s?k={encoded}"
        elif "bestbuy" in domain:
            return f"https://www.bestbuy.com/site/searchpage.jsp?st={encoded}"
        elif "newegg" in domain:
            return f"https://www.newegg.com/p/pl?d={encoded}"
        elif "walmart" in domain:
            return f"https://www.walmart.com/search?q={encoded}"
        elif "target" in domain:
            return f"https://www.target.com/s?searchTerm={encoded}"
        elif "costco" in domain:
            return f"https://www.costco.com/CatalogSearch?keyword={encoded}"
        elif "bhphoto" in domain:
            return f"https://www.bhphotovideo.com/c/search?q={encoded}"
        elif "microcenter" in domain:
            return f"https://www.microcenter.com/search/search_results.aspx?N=&Ntt={encoded}"
        else:
            # Generic - try /search?q=
            return f"{vendor_url}/search?q={encoded}"

    async def _extract_products_from_page(
        self,
        vendor_domain: str,
        page_url: str,
        page_text: str,
        goal: str,
    ) -> list[Product]:
        """
        DEPRECATED: Extract products from page text using LLM.

        This method is no longer used. WebAgent now handles product extraction
        via PageIntelligenceService with proper PERCEIVE-DECIDE-ACT-VERIFY loop.

        Kept for backwards compatibility if needed for fallback scenarios.
        See _extract_from_vendor() for the WebAgent-based approach.
        """
        prompt = f"""# Product Extractor

Extract products from this vendor page.

## Goal
{goal}

## Vendor
{vendor_domain}

## Page URL
{page_url}

## Page Content
{page_text[:12000]}

## Extract Products

Find products on this page. For each product, extract:
- name: Product name/title
- price: Price as shown (e.g., "$799.99")
- price_numeric: Numeric price (e.g., 799.99)
- in_stock: true/false
- specs: Key specifications (dict)

Output as JSON array:
[
  {{"name": "...", "price": "$799.99", "price_numeric": 799.99, "in_stock": true, "specs": {{}}}},
  ...
]

Only include actual products with prices. Limit to 10 products max.

JSON:"""

        try:
            import httpx

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.llm_url,
                    json={
                        "model": self.llm_model,
                        "messages": [
                            {"role": "system", "content": "You are a product extractor. Output valid JSON array only."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 2000,
                        "top_p": 0.8,
                        "stop": ["<|im_end|>", "<|endoftext|>"],
                        "repetition_penalty": 1.05,
                    },
                    headers={"Authorization": f"Bearer {self.llm_api_key}"},
                )
                response.raise_for_status()
                result = response.json()

            content = result["choices"][0]["message"]["content"]
            products_data = self._parse_json_response(content)

            if not isinstance(products_data, list):
                return []

            # Convert to Product objects
            products = []
            for p in products_data:
                if not p.get("name") or not p.get("price"):
                    continue

                products.append(Product(
                    name=p.get("name", ""),
                    price=p.get("price", ""),
                    price_numeric=p.get("price_numeric"),
                    vendor=vendor_domain,
                    url=page_url,
                    in_stock=p.get("in_stock", True),
                    specs=p.get("specs", {}),
                    confidence=0.8,
                ))

            return products

        except Exception as e:
            logger.warning(f"[Phase2] Product extraction failed: {e}")
            return []

    async def _generate_recommendations(
        self,
        products: list[Product],
        phase1_intelligence: dict,
        price_range: Optional[dict],
        goal: str,
    ) -> tuple[str, str]:
        """Generate recommendations based on Phase 1 intelligence."""
        if not products:
            return ("No products found to recommend.", "Unable to assess prices.")

        # Normalize phase1_intelligence — may be a string from §2 template resolution
        if not isinstance(phase1_intelligence, dict):
            phase1_intelligence = {}

        # Normalize price_range
        if not isinstance(price_range, dict):
            price_range = None

        # Build product summary
        product_summary = ""
        for i, p in enumerate(products[:10], 1):
            product_summary += f"{i}. {p.name} - {p.price} ({p.vendor})\n"

        # Build Phase 1 context
        phase1_context = ""
        if phase1_intelligence.get("recommended_models"):
            phase1_context += f"Recommended models from research: {phase1_intelligence['recommended_models']}\n"
        if phase1_intelligence.get("what_to_look_for"):
            phase1_context += f"Features to look for: {phase1_intelligence['what_to_look_for']}\n"
        if phase1_intelligence.get("user_warnings"):
            phase1_context += f"Things to avoid: {phase1_intelligence['user_warnings']}\n"

        price_context = ""
        if price_range:
            price_context = f"Expected price range from research: ${price_range.get('min', '?')} - ${price_range.get('max', '?')}"

        prompt = f"""# Product Recommender

Based on research and found products, make a recommendation.

## User Goal
{goal}

## Research Intelligence
{phase1_context}
{price_context}

## Products Found
{product_summary}

## Generate

1. **recommendation**: Which product(s) are best and why? Reference the research findings.
2. **price_assessment**: Are these prices good based on the research? Any deals?

Output as JSON:
{{"recommendation": "...", "price_assessment": "..."}}

JSON:"""

        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.llm_url,
                    json={
                        "model": self.llm_model,
                        "messages": [
                            {"role": "system", "content": "You are a product recommender. Output valid JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.5,
                        "max_tokens": 500,
                        "top_p": 0.8,
                        "stop": ["<|im_end|>", "<|endoftext|>"],
                        "repetition_penalty": 1.05,
                    },
                    headers={"Authorization": f"Bearer {self.llm_api_key}"},
                )
                response.raise_for_status()
                result = response.json()

            content = result["choices"][0]["message"]["content"]
            rec_data = self._parse_json_response(content)

            if isinstance(rec_data, dict):
                return (
                    rec_data.get("recommendation", ""),
                    rec_data.get("price_assessment", ""),
                )

        except Exception as e:
            logger.warning(f"[Phase2] Recommendation generation failed: {e}")

        return ("Unable to generate recommendation.", "Unable to assess prices.")

    def _parse_json_response(self, content: str):
        """Parse JSON from LLM response."""
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            content = "\n".join(lines)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r'(\{.*\}|\[.*\])', content, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except:
                    pass
            return None


async def execute_phase2(
    goal: str,
    phase1_intelligence: dict,
    vendor_hints: list[str],
    search_terms: list[str],
    price_range: Optional[dict] = None,
    session_id: Optional[str] = None,
    target_vendors: int = 3,
    event_emitter = None,
    human_assist_allowed: bool = True,
) -> Phase2Result:
    """
    Execute Phase 2 product finding.

    Args:
        goal: Original user query
        phase1_intelligence: Intelligence from Phase 1
        vendor_hints: Vendors mentioned in Phase 1
        search_terms: Search terms from Phase 1
        price_range: Expected price range
        session_id: Browser session ID
        target_vendors: Number of vendors to visit (default 3)
        event_emitter: Optional event emitter for progress events
        human_assist_allowed: Whether to allow human intervention for CAPTCHAs

    Returns:
        Phase2Result with products and recommendations
    """
    session_id = session_id or f"phase2_{int(time.time())}"
    finder = Phase2ProductFinder(
        session_id=session_id,
        target_vendors=target_vendors,
        event_emitter=event_emitter,
        human_assist_allowed=human_assist_allowed,
    )
    return await finder.execute(
        goal=goal,
        phase1_intelligence=phase1_intelligence,
        vendor_hints=vendor_hints,
        search_terms=search_terms,
        price_range=price_range,
    )
