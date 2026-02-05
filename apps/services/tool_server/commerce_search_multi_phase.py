"""
Multi-phase product search orchestrator.

Phase 1: Intelligence gathering (vendors, specs, quality criteria)
Phase 2: Product matching and pricing

Implements intelligence-driven search with Context Manager integration.
"""

import asyncio
import logging
import os
import time
from typing import Dict, List, Optional
from datetime import datetime

from apps.services.tool_server.product_search_config import (
    SearchConfig,
    get_phase1_queries,
    get_phase2_queries,
    get_phase2_generic_queries,
    get_default_vendors,
    infer_category
)
from apps.services.tool_server.vendor_extractor import (
    extract_vendor_intelligence,
    extract_product_listings,
    merge_intelligence
)
from apps.services.tool_server.context_manager_memory import (
    process_phase1_intelligence,
    process_phase2_products,
    build_synthesis_package,
    cache_phase1_intelligence,
    get_cached_phase1_intelligence
)
from apps.services.tool_server import human_search_engine
from apps.services.tool_server import playwright_stealth_mcp

logger = logging.getLogger(__name__)


class MultiPhaseProductSearch:
    """Orchestrates multi-phase product search"""

    def __init__(
        self,
        config: Optional[SearchConfig] = None,
        intervention_manager: Optional[Any] = None
    ):
        self.config = config or SearchConfig()
        self.llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        self.llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        self.llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")
        self.intervention_manager = intervention_manager

    async def deep_search(
        self,
        query: str,
        session_id: str = "default",
        category: Optional[str] = None,
        config: Optional[SearchConfig] = None,
        intervention_manager: Optional[Any] = None
    ) -> Dict:
        """
        Execute full deep search: Phase 1 + Phase 2.

        Args:
            query: Product search query
            session_id: Session ID for browser context reuse
            category: Product category (auto-inferred if None)
            config: Per-request config (overrides instance config)

        Returns:
            Complete search results with both phases
        """
        start_time = time.time()

        # Use per-request config or fall back to instance config
        search_config = config or self.config

        # Use per-request intervention_manager or fall back to instance
        intervention_mgr = intervention_manager or self.intervention_manager

        logger.info(f"[MultiPhase] Starting DEEP search for: {query}")

        # Infer category if not provided
        if not category:
            category = infer_category(query)
            logger.info(f"[MultiPhase] Inferred category: {category}")

        # Phase 1: Intelligence Gathering
        logger.info(f"[MultiPhase] ===== PHASE 1: Intelligence Gathering =====")
        phase1_start = time.time()
        phase1_result = await self._execute_phase1(
            product=query,
            category=category,
            session_id=session_id,
            config=search_config,
            intervention_manager=intervention_mgr
        )
        phase1_time = time.time() - phase1_start
        logger.info(f"[MultiPhase] Phase 1 complete in {phase1_time:.1f}s")

        # Check if Phase 1 succeeded
        if not phase1_result.get("ready_for_phase2"):
            logger.warning("[MultiPhase] Phase 1 failed, cannot proceed to Phase 2")
            return {
                "mode": "deep",
                "status": "phase1_failed",
                "phase1": phase1_result,
                "error": "Insufficient intelligence gathered"
            }

        # Create Phase 1 capsule with claims
        logger.info("[MultiPhase] Creating Phase 1 capsule with Context Manager")
        phase1_capsule = process_phase1_intelligence(
            product=query,
            intelligence=phase1_result["intelligence"],
            evidence_urls=phase1_result["evidence_urls"]
        )
        logger.info(f"[MultiPhase] Phase 1 capsule created: {phase1_capsule['capsule_id']}")

        # Cache Phase 1 intelligence for quick search reuse
        cache_phase1_intelligence(
            session_id=session_id,
            product=query,
            phase1_capsule=phase1_capsule,
            ttl_days=search_config.intelligence_cache_ttl_days
        )
        logger.info(f"[MultiPhase] Phase 1 intelligence cached for session {session_id}")

        # Phase 2: Product Search with Phase 1 context
        logger.info(f"[MultiPhase] ===== PHASE 2: Product Search =====")
        phase2_start = time.time()
        phase2_result = await self._execute_phase2(
            product=query,
            phase1_intelligence=phase1_result["intelligence"],
            session_id=session_id,
            config=search_config,
            intervention_manager=intervention_mgr
        )
        phase2_time = time.time() - phase2_start
        logger.info(f"[MultiPhase] Phase 2 complete in {phase2_time:.1f}s")

        # Create Phase 2 capsule with product claims linked to Phase 1
        logger.info("[MultiPhase] Creating Phase 2 capsule with Context Manager")
        phase2_capsule = process_phase2_products(
            product=query,
            products=phase2_result["products"],
            phase1_capsule=phase1_capsule,
            evidence_urls=phase2_result["evidence_urls"]
        )
        logger.info(f"[MultiPhase] Phase 2 capsule created: {phase2_capsule['capsule_id']}")

        # Build synthesis package for Guide
        logger.info("[MultiPhase] Building synthesis package for Guide")
        synthesis = build_synthesis_package(
            phase1_capsule=phase1_capsule,
            phase2_capsule=phase2_capsule
        )
        logger.info(f"[MultiPhase] Synthesis package ready with {len(synthesis['phase2']['products'])} products")

        total_time = time.time() - start_time

        return {
            "mode": "deep",
            "status": "success",
            "product": query,
            "category": category,
            "phase1_capsule_id": phase1_capsule["capsule_id"],
            "phase2_capsule_id": phase2_capsule["capsule_id"],
            "synthesis": synthesis,
            "stats": {
                "total_time_sec": round(total_time, 1),
                "phase1_time_sec": round(phase1_time, 1),
                "phase2_time_sec": round(phase2_time, 1),
                "vendors_discovered": len(phase1_result["intelligence"]["vendors"]),
                "products_found": len(phase2_result["products"]),
                "claims_created": len(phase1_capsule["claims"]) + len(phase2_capsule["claims"])
            }
        }

    async def quick_search(
        self,
        query: str,
        session_id: str = "default",
        category: Optional[str] = None,
        cached_intelligence: Optional[Dict] = None
    ) -> Dict:
        """
        Execute quick search: Phase 2 only (skip Phase 1).

        Args:
            query: Product search query
            session_id: Session ID
            category: Product category
            cached_intelligence: Cached Phase 1 intelligence (if available)

        Returns:
            Quick search results
        """
        start_time = time.time()

        logger.info(f"[MultiPhase] Starting QUICK search for: {query}")

        # Infer category
        if not category:
            category = infer_category(query)

        # Try to get cached Phase 1 intelligence
        if not cached_intelligence:
            logger.info(f"[MultiPhase] Checking cache for session {session_id}")
            cached_capsule = get_cached_phase1_intelligence(
                session_id=session_id,
                product=query
            )
            if cached_capsule:
                cached_intelligence = cached_capsule["intelligence"]
                logger.info(f"[MultiPhase] Found cached intelligence from {cached_capsule['timestamp']}")

        # Use cached intelligence or defaults
        if cached_intelligence:
            logger.info("[MultiPhase] Using cached intelligence from previous search")
            intelligence = cached_intelligence
            vendor_source = "cached"
        else:
            logger.info(f"[MultiPhase] No cache, using category defaults: {category}")
            default_vendors = get_default_vendors(category)
            intelligence = {
                "vendors": default_vendors,
                "specs_required": {},
                "quality_criteria": {},
                "price_intelligence": {}
            }
            vendor_source = "defaults"

        # Phase 2 only
        phase2_result = await self._execute_phase2(
            product=query,
            phase1_intelligence=intelligence,
            session_id=session_id,
            config=self.config,  # Use instance config for quick search
            intervention_manager=None,  # Quick search doesn't support intervention yet
            is_quick_mode=True
        )

        total_time = time.time() - start_time

        return {
            "mode": "quick",
            "status": "success",
            "product": query,
            "category": category,
            "vendor_source": vendor_source,
            "phase2": phase2_result,
            "note": "Quick search - run deep search for vendor recommendations",
            "stats": {
                "total_time_sec": round(total_time, 1),
                "products_found": len(phase2_result["products"]),
                "cache_hit": cached_intelligence is not None
            }
        }

    async def _execute_phase1(
        self,
        product: str,
        category: str,
        session_id: str,
        config: SearchConfig,
        intervention_manager: Optional[Any] = None
    ) -> Dict:
        """Execute Phase 1: Intelligence Gathering"""

        # Generate search queries
        queries = get_phase1_queries(product, category)
        logger.info(f"[Phase1] Generated {len(queries)} search queries")

        # Search and fetch URLs
        all_urls = []
        for query in queries[:config.num_query_variations_phase1]:
            try:
                results = await human_search_engine.search(query, k=config.max_urls_per_query_phase1, session_id=session_id)
                urls = [r["url"] for r in results]
                all_urls.extend(urls)
                logger.info(f"[Phase1] Query '{query[:40]}...' found {len(urls)} URLs")
            except Exception as e:
                logger.error(f"[Phase1] Search failed for '{query}': {e}")

        # Deduplicate URLs
        all_urls = list(dict.fromkeys(all_urls))
        logger.info(f"[Phase1] Total unique URLs to fetch: {len(all_urls)}")

        # Fetch and extract intelligence (parallel with limit)
        intelligence_extractions = []
        semaphore = asyncio.Semaphore(config.parallel_fetch_limit)

        async def fetch_and_extract(url: str):
            async with semaphore:
                try:
                    # Fetch page
                    from apps.services.tool_server.crawler_session_manager import get_crawler_session_manager
                    session_mgr = get_crawler_session_manager()
                    from urllib.parse import urlparse
                    domain = urlparse(url).netloc

                    context = await session_mgr.get_or_create_session(
                        domain=domain,
                        session_id=session_id
                    )

                    # Use intervention-aware fetch
                    fetch_result = await self._fetch_with_intervention(
                        url=url,
                        context=context,
                        timeout=config.fetch_timeout_sec,
                        intervention_manager=intervention_manager
                    )

                    if not fetch_result.get("success") or fetch_result.get("blocked"):
                        logger.warning(f"[Phase1] Failed to fetch {url[:60]}: {fetch_result.get('error')}")
                        return None

                    text_content = fetch_result.get("text_content", "")
                    if not text_content or len(text_content) < 100:
                        return None

                    # Extract intelligence using human-like reading
                    from apps.services.tool_server.vendor_extractor import extract_vendor_intelligence_human_like

                    intel = await extract_vendor_intelligence_human_like(
                        text=text_content,
                        url=url,
                        product=product,
                        llm_url=self.llm_url,
                        llm_model=self.llm_model,
                        llm_api_key=self.llm_api_key
                    )

                    return intel

                except Exception as e:
                    logger.error(f"[Phase1] Error processing {url[:60]}: {e}")
                    return None

        # Execute fetches sequentially (one at a time to avoid triggering blockers)
        results = []
        for url in all_urls[:20]:  # Limit to 20 URLs
            try:
                result = await fetch_and_extract(url)
                results.append(result)
            except Exception as e:
                logger.error(f"[Phase1] Exception fetching {url[:60]}: {e}")
                results.append(None)

        # Filter out None and exceptions
        intelligence_extractions = [
            r for r in results
            if r is not None
        ]

        logger.info(f"[Phase1] Successfully extracted from {len(intelligence_extractions)} pages")

        # Merge all intelligence
        if intelligence_extractions:
            merged_intelligence = merge_intelligence(intelligence_extractions)
        else:
            merged_intelligence = {
                "vendors": [],
                "specs_required": {},
                "quality_criteria": {},
                "price_intelligence": {},
                "community_wisdom": []
            }

        # Build Phase 1 result
        ready = len(merged_intelligence["vendors"]) >= 3  # Need at least 3 vendors

        return {
            "intelligence": merged_intelligence,
            "ready_for_phase2": ready,
            "vendor_count": len(merged_intelligence["vendors"]),
            "top_vendors": [v["name"] for v in merged_intelligence["vendors"][:10]],
            "evidence_urls": all_urls[:20],
            "timestamp": datetime.now().isoformat()
        }

    async def _execute_phase2(
        self,
        product: str,
        phase1_intelligence: Dict,
        session_id: str,
        config: SearchConfig,
        intervention_manager: Optional[Any] = None,
        is_quick_mode: bool = False
    ) -> Dict:
        """Execute Phase 2: Product Search and Matching"""

        vendors = phase1_intelligence.get("vendors", [])
        specs_required = phase1_intelligence.get("specs_required", {})

        # Generate search queries
        all_queries = []

        if vendors and not is_quick_mode:
            # Vendor-specific queries (use top vendors)
            for vendor in vendors[:10]:
                vendor_queries = get_phase2_queries(
                    product=product,
                    vendor_name=vendor["name"],
                    vendor_url=vendor.get("url", "")
                )
                all_queries.extend(vendor_queries)
        else:
            # Generic queries
            all_queries = get_phase2_generic_queries(product)

        logger.info(f"[Phase2] Generated {len(all_queries)} product search queries")

        # Search and fetch product pages
        all_urls = []
        for query in all_queries[:15]:  # Limit queries
            try:
                results = await human_search_engine.search(query, k=config.max_urls_per_vendor_phase2, session_id=session_id)
                urls = [r["url"] for r in results]
                all_urls.extend(urls)
            except Exception as e:
                logger.error(f"[Phase2] Search failed for '{query}': {e}")

        all_urls = list(dict.fromkeys(all_urls))
        logger.info(f"[Phase2] Total unique product URLs to fetch: {len(all_urls)}")

        # Fetch and extract products
        all_products = []
        semaphore = asyncio.Semaphore(config.parallel_fetch_limit)

        async def fetch_and_extract_products(url: str):
            async with semaphore:
                try:
                    # Fetch page
                    from apps.services.tool_server.crawler_session_manager import get_crawler_session_manager
                    session_mgr = get_crawler_session_manager()
                    from urllib.parse import urlparse
                    domain = urlparse(url).netloc

                    context = await session_mgr.get_or_create_session(
                        domain=domain,
                        session_id=session_id
                    )

                    # Use intervention-aware fetch
                    fetch_result = await self._fetch_with_intervention(
                        url=url,
                        context=context,
                        timeout=config.fetch_timeout_sec,
                        intervention_manager=intervention_manager
                    )

                    if not fetch_result.get("success") or fetch_result.get("blocked"):
                        return []

                    text_content = fetch_result.get("text_content", "")
                    if not text_content:
                        return []

                    # Determine vendor from URL
                    vendor_name = domain.split(".")[0] if domain else "unknown"

                    # Extract products using human-like reading
                    from apps.services.tool_server.vendor_extractor import extract_product_listings_human_like

                    products = await extract_product_listings_human_like(
                        text=text_content,
                        url=url,
                        product=product,
                        vendor=vendor_name,
                        llm_url=self.llm_url,
                        llm_model=self.llm_model,
                        llm_api_key=self.llm_api_key
                    )

                    # Add source URL to each product
                    for p in products:
                        if not p.get("url"):
                            p["url"] = url
                        p["source_url"] = url

                    return products

                except Exception as e:
                    logger.error(f"[Phase2] Error processing {url[:60]}: {e}")
                    return []

        # Execute fetches sequentially (one at a time to avoid triggering blockers)
        for url in all_urls[:30]:  # Limit to 30 URLs
            try:
                result = await fetch_and_extract_products(url)
                if isinstance(result, list):
                    all_products.extend(result)
            except Exception as e:
                logger.error(f"[Phase2] Exception fetching {url[:60]}: {e}")

        logger.info(f"[Phase2] Extracted {len(all_products)} total products")

        # Match products against specs (if Phase 1 intelligence available)
        if specs_required:
            for product_item in all_products:
                product_item["spec_matches"] = self._match_specs(
                    product_item.get("extracted_specs", {}),
                    specs_required
                )
                product_item["quality_score"] = self._calculate_quality_score(
                    product_item,
                    phase1_intelligence
                )
        else:
            # No spec matching in quick mode without cache
            for product_item in all_products:
                product_item["spec_matches"] = {}
                product_item["quality_score"] = 0.5  # Neutral score

        # Rank products
        ranked_products = sorted(
            all_products,
            key=lambda p: p.get("quality_score", 0),
            reverse=True
        )

        return {
            "products": ranked_products[:config.max_products_phase2],
            "total_found": len(all_products),
            "evidence_urls": all_urls[:30],
            "timestamp": datetime.now().isoformat()
        }

    def _match_specs(self, product_specs: Dict, required_specs: Dict) -> Dict:
        """Match product specs against requirements"""
        matches = {}

        for spec_name, spec_req in required_specs.items():
            required_value = spec_req.get("requirement", "")
            actual_value = product_specs.get(spec_name, "unknown")

            # Simple matching logic (can be enhanced)
            if actual_value == "unknown" or not actual_value:
                match = False
                score = 0.0
            else:
                match = True  # Simplified - actual matching would be more complex
                score = 1.0

            matches[spec_name] = {
                "required": required_value,
                "actual": actual_value,
                "match": match,
                "score": score
            }

        return matches

    async def _fetch_with_intervention(
        self,
        url: str,
        context: Any,
        timeout: int,
        intervention_manager: Optional[Any] = None,
        max_retries: int = 2
    ) -> Dict:
        """
        Fetch URL with human-assist intervention support.

        Args:
            url: URL to fetch
            context: Browser context
            timeout: Fetch timeout
            max_retries: Max intervention retry attempts

        Returns:
            Fetch result dict
        """
        for attempt in range(max_retries):
            # Attempt fetch
            fetch_result = await playwright_stealth_mcp.fetch(
                url=url,
                strategy="auto",
                use_stealth=True,
                timeout=timeout,
                wait_until="load",
                context=context
            )

            # Check if blocked
            intervention_mgr = intervention_manager or self.intervention_manager
            if fetch_result.get("blocked") and intervention_mgr:
                blocker_type = fetch_result.get("block_type", "unknown")
                screenshot = fetch_result.get("screenshot_path")

                logger.warning(
                    f"[MultiPhase] Blocked by {blocker_type} at {url[:60]}, "
                    f"requesting intervention (attempt {attempt + 1}/{max_retries})"
                )

                # Request intervention
                intervention = await intervention_mgr.request_intervention(
                    blocker_type=blocker_type,
                    url=url,
                    screenshot_path=screenshot,
                    blocker_details={"fetch_result": fetch_result}
                )

                # Wait for resolution (90 second timeout)
                resolved = await intervention.wait_for_resolution(timeout=180)

                if resolved:
                    logger.info(f"[MultiPhase] Intervention resolved, retrying {url[:60]}")
                    # Retry fetch with same context (session should be solved)
                    continue
                else:
                    logger.warning(
                        f"[MultiPhase] Intervention timeout/cancelled for {url[:60]}, "
                        f"skipping URL"
                    )
                    return fetch_result  # Return blocked result

            # Success or non-blocked failure
            return fetch_result

        # Max retries reached
        logger.error(f"[MultiPhase] Max retries reached for {url[:60]}")
        return fetch_result

    def _calculate_quality_score(self, product: Dict, intelligence: Dict) -> float:
        """Calculate product quality score using Phase 1 intelligence"""

        # Base score
        score = 0.5

        # Spec compliance (40%)
        spec_matches = product.get("spec_matches", {})
        if spec_matches:
            match_scores = [m.get("score", 0) for m in spec_matches.values()]
            if match_scores:
                score += 0.4 * (sum(match_scores) / len(match_scores))

        # Vendor quality (30%)
        vendor_name = product.get("vendor", "").lower()
        vendors = intelligence.get("vendors", [])
        for v in vendors:
            if v["name"].lower() in vendor_name or vendor_name in v["name"].lower():
                # Found vendor in Phase 1
                if v.get("sentiment") == "positive":
                    score += 0.3
                elif v.get("sentiment") == "negative":
                    score -= 0.2
                break

        # Price reasonableness (20%)
        price = product.get("price")
        price_intel = intelligence.get("price_intelligence", {})
        normal_range = price_intel.get("normal_range")
        if price and normal_range:
            min_price, max_price = normal_range
            if min_price <= price <= max_price:
                score += 0.2
            elif price < min_price:
                score += 0.1  # Cheap but maybe low quality
            else:
                score -= 0.1  # Overpriced

        # Availability (10%)
        if product.get("availability") == "in_stock":
            score += 0.1

        return min(1.0, max(0.0, score))


async def execute_multi_query_search(
    search_plan: Dict,
    session_id: str,
    token_budget: int,
    solver_url: str = "http://127.0.0.1:8000",
    solver_model_id: str = "qwen3-coder",
    solver_api_key: str = "qwen-local",
    min_quality_threshold: float = 0.7
) -> Dict:
    """
    Execute search queries sequentially with result evaluation.

    Returns early if satisfaction criteria met.

    Args:
        search_plan: Strategy from query planner with queries list
        session_id: Session identifier for search context
        token_budget: Remaining token budget for searches
        solver_url: LLM solver URL for evaluations
        solver_model_id: Model ID to use
        solver_api_key: API key for authentication
        min_quality_threshold: Minimum quality score to be satisfied

    Returns:
        Dict containing:
            - searches_executed: List of search results with evaluations
            - final_quality: Average quality score
            - satisfied: Whether any search met satisfaction criteria
            - best_results: Results from highest-scoring search
    """
    from apps.services.tool_server.search_result_evaluator import evaluate_search_results

    logger.info(f"[MultiQuery] Executing multi-query search with {len(search_plan['queries'])} queries")

    all_results = []
    cumulative_quality = 0.0
    best_search = None
    best_quality = 0.0
    tokens_used = 0

    for i, query_spec in enumerate(search_plan['queries'], 1):
        if tokens_used >= token_budget:
            logger.warning(f"[MultiQuery] Token budget exhausted after {i-1} queries")
            break

        logger.info(f"[MultiQuery] Query {i}/{len(search_plan['queries'])}: '{query_spec['text']}'")
        logger.info(f"[MultiQuery] Rationale: {query_spec.get('rationale', 'N/A')}")

        # Execute search using human_search_engine
        try:
            search_results = await human_search_engine.perform_google_search(
                query=query_spec['text'],
                session_id=session_id,
                num_results=10
            )

            # Rough token estimate (search results are typically 1-2k tokens)
            tokens_used += 2000

        except Exception as e:
            logger.error(f"[MultiQuery] Search failed for query {i}: {e}", exc_info=True)
            search_results = {"organic_results": []}

        # Evaluate results
        try:
            evaluation = await evaluate_search_results(
                results=search_results,
                required_fields=search_plan.get('required_fields', []),
                goal=search_plan.get('stop_criteria'),
                use_llm=False,  # Use heuristic evaluation to save tokens
                min_quality_threshold=min_quality_threshold,
                solver_url=solver_url,
                solver_model_id=solver_model_id,
                solver_api_key=solver_api_key
            )

            cumulative_quality += evaluation['quality_score']

            # Track best search
            if evaluation['quality_score'] > best_quality:
                best_quality = evaluation['quality_score']
                best_search = {
                    'query': query_spec['text'],
                    'results': search_results,
                    'evaluation': evaluation
                }

        except Exception as e:
            logger.error(f"[MultiQuery] Evaluation failed for query {i}: {e}", exc_info=True)
            evaluation = {
                'satisfied': False,
                'quality_score': 0.0,
                'recommendation': 'continue',
                'gaps': f'Evaluation error: {str(e)}'
            }

        all_results.append({
            'query': query_spec['text'],
            'results': search_results,
            'evaluation': evaluation,
            'priority': query_spec.get('priority', i)
        })

        logger.info(
            f"[MultiQuery] Query {i} quality: {evaluation['quality_score']:.2f}, "
            f"Satisfied: {evaluation.get('satisfied', False)}"
        )

        # Check stop criteria
        if evaluation.get('satisfied', False):
            logger.info(f"[MultiQuery] Satisfied after {i} queries (quality: {evaluation['quality_score']:.2f})")
            break

        if evaluation.get('recommendation') == 'stop':
            logger.info(f"[MultiQuery] Evaluator recommends stopping after {i} queries")
            break

    avg_quality = cumulative_quality / len(all_results) if all_results else 0.0
    any_satisfied = any(r['evaluation'].get('satisfied', False) for r in all_results)

    logger.info(
        f"[MultiQuery] Completed {len(all_results)} searches, "
        f"Avg quality: {avg_quality:.2f}, "
        f"Satisfied: {any_satisfied}, "
        f"Best quality: {best_quality:.2f}"
    )

    return {
        'searches_executed': all_results,
        'final_quality': avg_quality,
        'satisfied': any_satisfied,
        'best_results': best_search,
        'tokens_used': tokens_used
    }


# Global instance
_search_orchestrator: Optional[MultiPhaseProductSearch] = None


def get_search_orchestrator() -> MultiPhaseProductSearch:
    """Get or create global search orchestrator"""
    global _search_orchestrator
    if _search_orchestrator is None:
        _search_orchestrator = MultiPhaseProductSearch()
    return _search_orchestrator
