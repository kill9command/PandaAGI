"""
orchestrator/internet_research_mcp.py

Internet Research MCP Tool - Entry point for the internet.research tool.

This module provides the /internet.research endpoint handler that delegates
to ResearchRole for multi-phase web research:

Flow:
    /internet.research endpoint (apps/orchestrator/app.py)
        → adaptive_research() (this file)
        → research_orchestrate() (research_role.py)
        → ResearchRole.orchestrate()
            → Phase 1: gather_intelligence() - forum/community search
            → Phase 2: intelligent_vendor_search() - product extraction

See: panda_system_docs/architecture/mcp-tool-patterns/internet-research-mcp/

Created: 2025-11-21
Updated: 2025-12-26
"""

import asyncio
import hashlib
import logging
import os
import httpx
from typing import Dict, Any, Optional, List
from pathlib import Path

# Removed: research_gateway_client imports (no longer using LLM action loop)
from orchestrator.search_rate_limiter import get_search_rate_limiter

logger = logging.getLogger(__name__)

# Configuration
TOOL_SERVER_URL = os.getenv("TOOL_SERVER_URL", "http://127.0.0.1:8090")


async def human_warmup_behavior(session_id: str):
    """
    Perform human-like warmup actions to avoid bot detection.

    Mimics real human behavior before search:
    - Random initial delay (3-8 seconds)
    - Small scrolls (simulating page scan)

    Args:
        session_id: Browser session ID
    """
    import random

    # Random initial delay (humans take time to process the page)
    initial_delay = 3.0 + random.uniform(0, 5.0)  # 3-8 seconds
    logger.info(f"[HumanWarmup] Initial observation delay: {initial_delay:.1f}s")
    await asyncio.sleep(initial_delay)

    try:
        # Small scroll down (humans scan the page)
        # web.scroll uses clicks: ~100px per click, positive=down
        scroll_clicks = random.randint(2, 4)
        logger.info(f"[HumanWarmup] Scrolling down {scroll_clicks} clicks (page scan)")
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{TOOL_SERVER_URL}/web.scroll",
                json={"session_id": session_id, "clicks": scroll_clicks}
            )

        await asyncio.sleep(0.5 + random.uniform(0, 0.5))

        # Small scroll back up (humans adjust view)
        # Negative clicks = scroll up
        scroll_back_clicks = -random.randint(1, 2)
        logger.info(f"[HumanWarmup] Scrolling up {abs(scroll_back_clicks)} clicks (view adjustment)")
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{TOOL_SERVER_URL}/web.scroll",
                json={"session_id": session_id, "clicks": scroll_back_clicks}
            )

        await asyncio.sleep(0.3 + random.uniform(0, 0.4))

        logger.info("[HumanWarmup] Warmup sequence complete")

    except Exception as e:
        logger.warning(f"[HumanWarmup] Warmup actions failed (non-critical): {e}")
        # Continue anyway - warmup is best-effort


async def adaptive_research(
    query: str,
    research_goal: str = None,
    session_id: str = None,
    human_assist_allowed: bool = True,
    event_emitter: Optional[Any] = None,
    mode: str = "standard",
    remaining_token_budget: int = 8000,
    query_type: str = "commerce_search",  # DEPRECATED: Ignored, use research_context.intent
    force_refresh: bool = False,
    force_strategy: Optional[str] = None,  # DEPRECATED: Ignored
    research_context: Optional[Dict[str, Any]] = None,  # Context from Planner (contains intent)
    turn_number: int = 0,  # For research document indexing
    deep_read: bool = False,  # Multi-page reading mode for forums/articles
    max_pages: int = 5  # Max pages to read in deep_read mode
) -> Dict[str, Any]:
    """
    Research Role delegation with proven Google search.

    Research phases (following Pandora architecture):
    - Phase 1: Intelligence gathering (Google SERP + forum discovery)
    - Phase 2: Product extraction (visit and extract from URLs)

    Delegates to Research Role which uses research_orchestrator.gather_intelligence()
    with autonomous Google search, CAPTCHA handling, and LLM SERP extraction.

    IMPORTANT: Intent-based routing is the single source of truth.
    - Intent values: navigation, site_search, commerce, informational
    - Only "commerce" intent triggers Phase 2 (multi-vendor search)
    - Other intents use Phase 1 only (direct navigation/info gathering)
    See: panda_system_docs/architecture/LLM-ROLES/CONTEXT_DISCIPLINE.md

    Args:
        query: Search query (e.g., "Syrian hamsters for sale")
        research_goal: Optional detailed goal
        session_id: Browser session ID (auto-generated from query if not provided)
        human_assist_allowed: Allow CAPTCHA intervention
        event_emitter: Progress events
        mode: "standard" (1-pass) or "deep" (multi-pass with satisfaction criteria)
        remaining_token_budget: Token budget for research role
        query_type: DEPRECATED - Ignored. Use research_context["intent"] instead.
        force_refresh: Force fresh research, bypass cache
        force_strategy: DEPRECATED - Ignored
        research_context: Context from Planner with:
            - intent: Intent (navigation, site_search, commerce, informational) - REQUIRED
            - intent_metadata: Additional intent info (target_url, site_name, etc.)
            - entities: List of specific product/item names from context
            - subtasks: Pre-planned search queries with rationale
            - research_type: Type of research (technical_specs, comparison, pricing, etc.)
            - phase_hint: Whether to skip Phase 1 (e.g., "skip_phase1")
            - information_needed: List of specific info to find

    Returns:
        {
            "query": str,
            "strategy_used": str,
            "strategy_reason": str,
            "results": {
                "findings": [...],
                "synthesis": {...}
            },
            "stats": {...},
            "intelligence_cached": bool
        }
    """

    # Generate per-query session ID to avoid fingerprint tracking across searches
    if not session_id or session_id == "default":
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        session_id = f"web_vision_{query_hash}"
        logger.info(f"[InternetResearch] Generated session ID: {session_id}")

    # Default research goal
    if not research_goal:
        research_goal = f"Find and evaluate sources for: {query}"

    # Log research context if provided
    if research_context:
        intent = research_context.get('intent', 'unknown')
        intent_metadata = research_context.get('intent_metadata', {})
        logger.info(
            f"[InternetResearch] Research context provided: "
            f"intent={intent}, "
            f"intent_metadata={intent_metadata}, "
            f"entities={len(research_context.get('entities', []))}, "
            f"subtasks={len(research_context.get('subtasks', []))}, "
            f"research_type={research_context.get('research_type', 'general')}, "
            f"phase_hint={research_context.get('phase_hint', 'none')}"
        )

    # Add deep_read params to research_context
    if research_context is None:
        research_context = {}
    if deep_read:
        research_context["deep_read"] = deep_read
        research_context["max_pages"] = max_pages
        logger.info(f"[InternetResearch] Deep read mode enabled: max_pages={max_pages}")

    logger.info(
        f"[InternetResearch] Delegating to Research Role: '{query[:60]}...', "
        f"mode={mode.upper()}, budget={remaining_token_budget}, force_refresh={force_refresh}"
    )

    # Emit start event
    if event_emitter:
        await event_emitter.emit("research_started", {
            "query": query,
            "mode": mode,
            "query_type": query_type,
            "session_id": session_id,
            "strategy": "research_role_google_search"
        })

    try:
        # Delegate to Research Role (proper Pandora architecture)
        from orchestrator.research_role import research_orchestrate

        research_result = await research_orchestrate(
            query=query,
            research_goal=research_goal,
            mode=mode,
            session_id=session_id,
            query_type=query_type,
            user_constraints=None,
            event_emitter=event_emitter,
            remaining_token_budget=remaining_token_budget,
            force_refresh=force_refresh,
            research_context=research_context,  # Pass entities/subtasks/research_type
            turn_number=turn_number  # NEW: For research document indexing
        )

        # Extract results for Gateway compatibility
        # Navigation strategy returns findings directly, normal flow returns in results.findings
        phase2_results = research_result.get("results", {})

        # Handle both direct findings (navigation) and nested findings (normal research)
        if "findings" in research_result:
            # Navigation/site_search strategy returns findings directly
            raw_findings = research_result.get("findings", [])
            logger.info(f"[InternetResearch] Using direct findings (strategy={research_result.get('strategy', 'unknown')})")
        else:
            # Phase2 returns "findings" not "products"
            raw_findings = phase2_results.get("findings", [])

        # Check if this is Phase 1 only (technical specs, no products)
        is_phase1_only = phase2_results.get("phase1_only", False)

        # Extract products from each finding
        # Handle multiple formats:
        # 1. New format (search_products_with_comparison): findings are already product dicts
        # 2. Old format (search_products): findings have extracted_info.products structure
        # 3. Phase 1 only: findings have "statement" field (intelligence/facts, not products)
        all_products = []
        all_statements = []  # For Phase 1-only findings

        for finding in raw_findings:
            # Check if finding is already in final format (new Phase 2)
            if isinstance(finding, dict) and "name" in finding and "price" in finding:
                # New format: finding is already a product dict
                all_products.append(finding)
            elif isinstance(finding, dict) and "statement" in finding:
                # Phase 1 format: intelligence/fact finding with statement
                statement_finding = {
                    "statement": finding.get("statement", ""),
                    "type": finding.get("type", "fact"),
                    "confidence": finding.get("confidence", 0.8),
                    "source": finding.get("source", "phase1_intelligence")
                }
                # Include extracted links from page (for forum threads, articles, etc.)
                if finding.get("extracted_links"):
                    statement_finding["extracted_links"] = finding.get("extracted_links")
                all_statements.append(statement_finding)
            else:
                # Old format: extract from extracted_info.products
                extracted_info = finding.get("extracted_info", {})
                page_products = extracted_info.get("products", None)

                if isinstance(page_products, list):
                    for product in page_products:
                        if isinstance(product, dict):
                            all_products.append({
                                "name": product.get("name", "Unknown"),
                                "price": product.get("price", "N/A"),
                                "vendor": product.get("vendor") or finding.get("url", "").split('/')[2] if finding.get("url") else "Unknown vendor",
                                "url": product.get("url") or finding.get("url", ""),
                                "description": product.get("description", ""),
                                "confidence": product.get("confidence", 0.8)
                            })

        # Build findings list for Gateway compatibility
        # Use products for commerce queries, statements for technical specs

        # ===== QUALITY FILTERING =====
        # Filter out zero-confidence and garbage extractions
        if all_products:
            original_count = len(all_products)

            # Filter patterns that indicate bad extraction (headers, taglines, etc.)
            garbage_patterns = [
                "delivering to",
                "ethically breeding",
                "free shipping",
                "sign in",
                "log in",
                "subscribe",
                "newsletter",
            ]

            quality_products = []
            for p in all_products:
                confidence = p.get("confidence", 0.8)
                name = str(p.get("name", "")).lower()

                # Skip zero/very low confidence items
                if confidence < 0.15:
                    logger.debug(f"[InternetResearch] Skipping low-confidence product: {p.get('name', 'unknown')[:50]} (conf={confidence})")
                    continue

                # Skip items that look like page headers/taglines
                is_garbage = any(pattern in name for pattern in garbage_patterns)
                if is_garbage:
                    logger.debug(f"[InternetResearch] Skipping garbage extraction: {p.get('name', 'unknown')[:50]}")
                    continue

                quality_products.append(p)

            if quality_products:
                filtered_count = original_count - len(quality_products)
                if filtered_count > 0:
                    logger.info(f"[InternetResearch] Quality filter removed {filtered_count} garbage extractions")
                all_products = quality_products

        # ===== INTENT-AWARE FILTERING =====
        # For "cheapest" queries, filter out items without actual prices
        query_lower = query.lower()
        if all_products and ("cheapest" in query_lower or "lowest price" in query_lower or "best deal" in query_lower):
            original_count = len(all_products)
            # Filter out "Contact for pricing" and similar non-priced items
            priced_products = [
                p for p in all_products
                if p.get("price") and
                p.get("price") != "N/A" and
                "contact" not in str(p.get("price", "")).lower() and
                "call" not in str(p.get("price", "")).lower()
            ]

            if priced_products:
                all_products = priced_products
                filtered_count = original_count - len(priced_products)
                if filtered_count > 0:
                    logger.info(f"[InternetResearch] Filtered {filtered_count} 'contact for pricing' items for cheapest query")
            else:
                # All items were contact-based
                logger.warning(
                    f"[InternetResearch] All {original_count} products require contact for pricing - "
                    f"keeping them but user should be informed"
                )

        if all_products:
            findings = all_products
        elif all_statements:
            # Phase 1-only: return statements as findings
            findings = all_statements
            logger.info(f"[InternetResearch] Phase 1 only: {len(all_statements)} intelligence findings")
        else:
            findings = []

        stats = research_result.get("stats", {})
        # Handle different stats formats (navigation uses sources_visited, normal uses total_sources)
        sources_visited = stats.get("sources_visited", stats.get("total_sources", len(raw_findings)))
        # Count sources that have products or statements
        sources_extracted = stats.get("sources_extracted", len([f for f in raw_findings if (
            f.get("extracted_info", {}).get("products") or
            ("name" in f and "price" in f) or
            "statement" in f  # Navigation/informational findings have statement
        )]))

        logger.info(
            f"[InternetResearch] Research Role complete: "
            f"{research_result.get('passes', 1)} pass(es), "
            f"{sources_visited} sources visited, "
            f"{sources_extracted} sources extracted, "
            f"{len(findings)} findings"
        )

        # Emit completion event
        if event_emitter:
            await event_emitter.emit("research_completed", {
                "passes": research_result.get("passes", 1),
                "sources_count": sources_visited,
                "findings_count": len(findings),
                "strategy": research_result.get("strategy_used", "standard")
            })

        # Return Gateway-compatible format
        strategy_used = research_result.get("strategy", research_result.get("strategy_used", "research_role"))
        strategy_reason = research_result.get("strategy_reason", f"Research Role with Google search ({mode} mode)")
        return {
            "query": query,
            "research_goal": research_goal,
            "mode": mode,
            "strategy": strategy_used,  # Add strategy field for unified_flow claims extraction
            "strategy_used": strategy_used,
            "strategy_reason": strategy_reason,
            "passes": research_result.get("passes", 1),
            "findings": findings,  # Top-level for Gateway compatibility
            "rejected": phase2_results.get("rejected", []),  # Rejected products for context awareness
            "results": {
                "findings": findings,
                "raw_findings": raw_findings,  # Include raw findings for debugging
                "synthesis": {
                    "total_sources": sources_visited,
                    "extracted_sources": sources_extracted,
                    "findings_count": len(findings)
                }
            },
            # Phase 1 data for document generation (new document-based IO)
            "phase1_sources": research_result.get("phase1_sources", []),
            "intelligence": research_result.get("intelligence", {}),
            "stats": {
                "sources_visited": sources_visited,
                "sources_extracted": sources_extracted,
                "findings_extracted": len(findings),
                "mode": mode,
                "strategy": research_result.get("strategy_used", "research_role"),
                "passes_executed": research_result.get("passes", 1),
                "intelligence_used": research_result.get("intelligence_cached", False)
            },
            "intelligence_cached": research_result.get("intelligence_cached", False)
        }

    except Exception as e:
        # Ensure error message is never empty (e.g., httpx.ReadTimeout has empty str())
        error_msg = str(e) or type(e).__name__
        logger.error(f"[InternetResearch] Research Role error: {error_msg}", exc_info=True)

        # Emit error event
        if event_emitter:
            await event_emitter.emit("research_failed", {
                "error": error_msg,
                "query": query
            })

        return {
            "error": "research_failed",
            "message": f"Research Role error: {error_msg}",
            "query": query,
            "strategy_used": "research_role",
            "mode": mode,
            "results": {
                "findings": [],
                "synthesis": {}
            },
            "stats": {
                "sources_visited": 0,
                "sources_extracted": 0,
                "findings_extracted": 0
            },
            "details": error_msg
        }



# ============================================================================
# REMOVED: _gateway_delegated_research() - Old LLM action loop (336 lines)
#
# This function implemented a fragile LLM-driven browser automation loop that:
# - Asked LLM for next action on each cycle
# - Frequently failed due to JSON parsing errors  
# - Had no fallback strategy
# - Resulted in 0 findings
#
# REPLACED BY: Research Role delegation to proven Google search
# See: adaptive_research() above → research_role.orchestrate() →
#      research_orchestrator.gather_intelligence() → _web_vision_search_google()
#
# Benefits of new approach:
# - Deterministic Google search with SERP extraction
# - CAPTCHA detection and human intervention
# - Pagination support
# - No reliance on LLM returning valid JSON
# - Follows Pandora's single-model multi-role reflection architecture
# ============================================================================

# ============================================================================
# Browser Session Management
# ============================================================================

async def ensure_browser_session(session_id: str):
    """
    Ensure browser session exists and is ready.

    Creates persistent Playwright browser context if needed.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{TOOL_SERVER_URL}/web.get_screen_state",
                json={"session_id": session_id, "max_elements": 5, "max_text_len": 10}
            )
            resp.raise_for_status()
            state = resp.json()

        if state.get("success"):
            logger.info(f"[BrowserSession] Session '{session_id}' ready")
        else:
            logger.info(f"[BrowserSession] Session '{session_id}' initialized")

    except Exception as e:
        logger.warning(f"[BrowserSession] Could not verify session: {e}")


async def close_browser_session(session_id: str):
    """
    Close browser session and cleanup resources.
    """
    try:
        # Browser sessions auto-close on idle timeout (15 minutes)
        # No explicit close needed for Playwright sessions
        logger.info(f"[BrowserSession] Session '{session_id}' will auto-close on timeout")

    except Exception as e:
        logger.warning(f"[BrowserSession] Close error: {e}")


async def get_browser_state(session_id: str) -> Dict[str, Any]:
    """
    Get current browser state (URL, elements, text preview).

    Args:
        session_id: Browser session ID

    Returns:
        {
            "success": bool,
            "current_url": str,
            "page_title": str,
            "visible_elements": [...],
            "page_text_preview": str
        }
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{TOOL_SERVER_URL}/web.get_screen_state",
                json={"session_id": session_id, "max_elements": 20, "max_text_len": 50}
            )
            resp.raise_for_status()
            state = resp.json()

        if state.get("success"):
            # Extract page_info (web.get_screen_state returns nested structure)
            page_info = state.get("page_info", {})
            screen_state = state.get("screen_state", "")

            # Parse screen_state text to extract visible elements
            # Format is: "1. [DOM] 'text' @(x,y) role=button 95%"
            elements = []
            for line in screen_state.split("\n")[5:]:  # Skip header lines
                if line.strip() and ". [" in line:
                    # Parse line to extract element info
                    try:
                        # Extract text between quotes
                        start = line.find("'")
                        end = line.find("'", start + 1)
                        if start >= 0 and end > start:
                            text = line[start+1:end]
                            tag = "element"
                            if "role=" in line:
                                role_start = line.find("role=") + 5
                                role_end = line.find(" ", role_start)
                                if role_end < 0:
                                    role_end = line.find("%", role_start)
                                tag = line[role_start:role_end] if role_end > role_start else "element"
                            elements.append({"tag": tag, "text": text})
                    except Exception:
                        continue

            return {
                "success": True,
                "current_url": page_info.get("url", ""),
                "page_title": page_info.get("title", ""),
                "visible_elements": elements,
                "page_text_preview": screen_state
            }
        else:
            return {
                "success": False,
                "message": state.get("message", "Unknown error")
            }

    except Exception as e:
        logger.error(f"[BrowserState] Error: {e}")
        return {
            "success": False,
            "message": f"Error: {str(e)}"
        }


async def execute_browser_action(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute browser action via orchestrator MCP.

    Args:
        tool: Tool name (web.navigate, web.click, web.type_text, web.capture_content, noop)
        args: Tool arguments (must include session_id)

    Returns:
        Tool result dict
    """
    try:
        # Handle noop action (used when completing research due to errors)
        if tool == "noop":
            logger.info("[BrowserAction] Executing noop (no operation)")
            return {
                "success": True,
                "message": "No operation performed (research complete)"
            }

        # Map tool names to endpoints
        endpoint = f"{TOOL_SERVER_URL}/{tool}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(endpoint, json=args)
            resp.raise_for_status()
            result = resp.json()

        return result

    except Exception as e:
        logger.error(f"[BrowserAction] Error executing {tool}: {e}")
        return {
            "success": False,
            "message": f"Execution failed: {str(e)}"
        }


async def trigger_captcha_intervention(
    session_id: str,
    url: str,
    screenshot_path: Optional[str] = None
):
    """
    Trigger CAPTCHA intervention for human assistance.

    Args:
        session_id: Browser session ID
        url: URL with CAPTCHA
        screenshot_path: Optional screenshot path
    """
    try:
        from orchestrator.captcha_intervention import queue_intervention

        intervention_id = await queue_intervention(
            session_id=session_id,
            url=url,
            intervention_type="captcha",
            screenshot_path=screenshot_path
        )

        logger.info(f"[CAPTCHA] Intervention queued: {intervention_id}")

    except Exception as e:
        logger.error(f"[CAPTCHA] Failed to queue intervention: {e}")
