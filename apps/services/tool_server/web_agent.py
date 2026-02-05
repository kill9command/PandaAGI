"""
orchestrator/web_agent.py

WebAgent - Unified Web Navigation and Extraction System

THE CANONICAL SYSTEM for all web navigation and extraction in Panda.
Replaces: UniversalAgent, SmartExtractor, AdaptiveExtractor, UnifiedWebExtractor.

Architecture: PERCEIVE → DECIDE → ACT → VERIFY loop
- PERCEIVE: PageIntelligenceService understands page structure
- DECIDE: MIND LLM plans actions based on goal
- ACT: Playwright executes actions
- VERIFY: StuckDetector prevents loops, validates state

Key features:
- ONE code path (no fallbacks)
- StuckDetector prevents infinite loops
- Site knowledge integration for learning
- Interventions for unrecoverable failures

See: architecture/mcp-tool-patterns/internet-research-mcp/WEB_AGENT_ARCHITECTURE.md
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple, TYPE_CHECKING
from urllib.parse import urlparse

from apps.services.tool_server.shared.llm_utils import call_llm_json
from apps.services.tool_server.site_knowledge_cache import (
    SiteKnowledgeCache,
    SiteKnowledgeEntry,
    ActionTrace
)
from apps.services.tool_server.intervention_manager import (
    InterventionManager,
    InterventionStatus,
    get_intervention_manager,
    register_intervention_manager
)
from apps.services.tool_server.page_intelligence.service import (
    PageIntelligenceService,
    get_page_intelligence_service
)
from apps.services.tool_server.page_intelligence.models import (
    PageUnderstanding,
    PageType,
    ZoneType,
    AvailabilityStatus
)

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

MAX_STEPS = 5               # Maximum navigation steps per goal
CLICK_WAIT_TIME = 2.0       # Seconds to wait after click
TYPE_DELAY_MS = 75          # Milliseconds between keystrokes
INTERVENTION_TIMEOUT = 120  # Seconds to wait for human intervention
MAX_PRODUCTS = 10           # Maximum products to extract per vendor
STUCK_THRESHOLD = 2         # Same element clicked this many times = stuck
CONSECUTIVE_FAILURE_LIMIT = 3  # Failures before requesting intervention

# Prompt templates directory
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts" / "web_agent"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Product:
    """Product extracted from a page."""
    name: str
    price: str = ""
    url: str = ""
    description: str = ""
    vendor: str = ""
    in_stock: Optional[bool] = None
    confidence: float = 0.8

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "price": self.price,
            "url": self.url,
            "description": self.description,
            "vendor": self.vendor,
            "in_stock": self.in_stock,
            "confidence": self.confidence
        }


@dataclass
class WebAgentResult:
    """
    Result from WebAgent navigation with determination signal.

    The determination field tells the orchestrator WHY we got these results:
    - "products_found": Successfully extracted matching products
    - "no_relevant_products": Page examined, nothing matches query (valid result, not failure)
    - "no_online_availability": Products exist but only available in-store (early exit)
    - "wrong_page_type": Not a product listing page (homepage, blog, etc.)
    - "blocked": CAPTCHA, login wall, or other blocker detected
    - "error": Technical failure during navigation

    This allows the orchestrator to distinguish between "extraction failed"
    and "extraction succeeded but found nothing relevant".
    """
    products: List[Product]
    determination: str  # "products_found" | "no_relevant_products" | "no_online_availability" | "wrong_page_type" | "blocked" | "error"
    reason: Optional[str] = None
    page_type: Optional[str] = None
    items_seen: int = 0  # How many items were on the page (even if not matching)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "products": [p.to_dict() for p in self.products],
            "determination": self.determination,
            "reason": self.reason,
            "page_type": self.page_type,
            "items_seen": self.items_seen
        }


@dataclass
class InteractiveElement:
    """An interactive element on the page."""
    element_id: str
    element_type: str  # "link", "button", "input", "select"
    text: str
    bounds: Dict[str, float]
    href: str = ""

    @property
    def center(self) -> Tuple[float, float]:
        """Get center coordinates for clicking."""
        x = self.bounds.get("left", 0) + self.bounds.get("width", 0) / 2
        y = self.bounds.get("top", 0) + self.bounds.get("height", 0) / 2
        return (x, y)


@dataclass
class ExpectedState:
    """What should be true after an action succeeds."""
    page_type: str = ""
    must_see: List[str] = field(default_factory=list)
    must_not_see: List[str] = field(default_factory=list)


@dataclass
class AgentDecision:
    """LLM's decision about what action to take."""
    action: str  # "click", "type", "scroll", "extract", "finish"
    reasoning: str
    target_id: str = ""
    target_text: str = ""  # Text of element (for learning)
    input_text: str = ""   # Text to type
    expected_state: Optional[ExpectedState] = None
    confidence: float = 0.8


@dataclass
class PagePerception:
    """Combined perception of current page state."""
    url: str
    page_type: str
    has_products: bool
    has_prices: bool
    interactive_elements: List[InteractiveElement]
    page_understanding: PageUnderstanding
    text_preview: str = ""  # First ~500 chars for LLM context

    def format_for_decision(self) -> str:
        """Format perception for LLM decision making."""
        lines = [
            f"URL: {self.url}",
            f"Page Type: {self.page_type}",
            f"Has Products: {self.has_products}",
            f"Has Prices: {self.has_prices}",
        ]

        # Add availability info if there are restrictions
        if self.page_understanding and self.page_understanding.has_availability_restriction():
            availability_summary = self.page_understanding.get_availability_summary()
            lines.append(f"AVAILABILITY: {availability_summary}")

        lines.append("")
        lines.append("Interactive Elements:")

        for elem in self.interactive_elements[:20]:  # Limit for token budget
            lines.append(f"  [{elem.element_id}] {elem.element_type}: \"{elem.text[:50]}\"")

        if self.text_preview:
            lines.append("")
            lines.append("Page Preview:")
            lines.append(self.text_preview[:500])

        return "\n".join(lines)


# =============================================================================
# STUCK DETECTOR
# =============================================================================

class StuckDetector:
    """
    Detects when the agent is stuck in a loop.

    Key insight: If we click the same element twice, we're stuck.
    """

    def __init__(self):
        self.clicked_elements: Set[Tuple[str, str]] = set()  # (url_path, element_id)
        self.action_history: List[AgentDecision] = []
        self.consecutive_failures = 0
        self.last_url: str = ""

    def would_be_stuck(self, url: str, action: AgentDecision) -> bool:
        """Check if this action would repeat a previous click."""
        if action.action != "click":
            return False

        url_path = self._normalize_url(url)
        key = (url_path, action.target_id)
        return key in self.clicked_elements

    def record_action(self, url: str, action: AgentDecision, success: bool):
        """Record an action for future stuck detection."""
        if action.action == "click":
            url_path = self._normalize_url(url)
            self.clicked_elements.add((url_path, action.target_id))

        self.action_history.append(action)
        self.last_url = url

        if not success:
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 0

    def should_intervene(self) -> bool:
        """Check if human intervention is needed."""
        return self.consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT

    def reset(self):
        """Reset detector for new navigation session."""
        self.clicked_elements.clear()
        self.action_history.clear()
        self.consecutive_failures = 0
        self.last_url = ""

    def _normalize_url(self, url: str) -> str:
        """Normalize URL to path for comparison."""
        parsed = urlparse(url)
        return f"{parsed.netloc}{parsed.path}"


# =============================================================================
# WEB AGENT
# =============================================================================

class WebAgent:
    """
    Unified web navigation and extraction agent.

    PERCEIVE → DECIDE → ACT → VERIFY loop.
    """

    def __init__(
        self,
        page: 'Page',
        llm_url: str = None,
        llm_model: str = None,
        llm_api_key: str = None,
        knowledge_cache: Optional[SiteKnowledgeCache] = None,
        session_id: str = None
    ):
        self.page = page
        self.llm_url = llm_url
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self.knowledge_cache = knowledge_cache or SiteKnowledgeCache()
        self.session_id = session_id or f"web_agent_{int(time.time())}"

        # Components
        self.page_intelligence = get_page_intelligence_service(llm_url, llm_model)
        self.stuck_detector = StuckDetector()

        # Get or create intervention manager for this session
        self.intervention_manager = get_intervention_manager(self.session_id)
        if not self.intervention_manager:
            self.intervention_manager = InterventionManager()
            register_intervention_manager(self.session_id, self.intervention_manager)

        # State
        self.partial_results: List[Product] = []

    async def navigate(
        self,
        url: str,
        goal: str,
        original_query: str = None,
        max_steps: int = None,
        turn_dir: Optional[Path] = None
    ) -> WebAgentResult:
        """
        Navigate to extract products matching the goal.

        Args:
            url: Starting URL
            goal: What we're trying to achieve (e.g., "find laptops under $500")
            original_query: User's original query (for context)
            max_steps: Override default max steps
            turn_dir: Directory to save debug artifacts

        Returns:
            WebAgentResult with products and determination signal
        """
        max_steps = max_steps or MAX_STEPS
        original_query = original_query or goal
        domain = self._get_domain(url)

        logger.info(f"[WebAgent] Starting navigation: {goal} on {domain}")

        # Reset stuck detector for new session
        self.stuck_detector.reset()

        # Track last perception for determination
        last_perception: Optional[PagePerception] = None

        # Navigate to starting URL
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1.0)
        except Exception as e:
            logger.error(f"[WebAgent] Failed to navigate to {url}: {e}")
            return WebAgentResult(
                products=[],
                determination="error",
                reason=f"Failed to load page: {e}",
                page_type=None,
                items_seen=0
            )

        # PERCEIVE → DECIDE → ACT → VERIFY loop
        for step in range(max_steps):
            logger.info(f"[WebAgent] Step {step + 1}/{max_steps}")

            # 1. PERCEIVE - Understand current page
            perception = await self._perceive(turn_dir)
            if not perception:
                logger.warning("[WebAgent] Perception failed")
                continue

            last_perception = perception  # Track for determination
            logger.info(f"[WebAgent] Page: {perception.page_type}, has_products={perception.has_products}")

            # Early exit: Check for in-store-only or out-of-stock availability
            # This saves time by not navigating when we already know there are no online products
            if perception.page_understanding and perception.page_understanding.availability_status in (
                AvailabilityStatus.IN_STORE_ONLY,
                AvailabilityStatus.OUT_OF_STOCK
            ):
                availability_summary = perception.page_understanding.get_availability_summary()
                logger.info(f"[WebAgent] Early exit - no online availability: {availability_summary}")
                return WebAgentResult(
                    products=[],
                    determination="no_online_availability",
                    reason=availability_summary,
                    page_type=perception.page_type,
                    items_seen=0
                )

            # FORCE EXTRACT: If we detect products with prices, extract immediately.
            # This prevents the common failure mode where agent navigates away from
            # products that are already visible on the page.
            #
            # Check for prices in two places:
            # 1. has_prices - regex check on page text content
            # 2. page_notices - ZoneIdentifier may find prices like "$35" in notices
            has_price_signal = perception.has_prices or self._page_notices_contain_prices(
                perception.page_understanding
            )

            if perception.has_products and has_price_signal:
                logger.info(f"[WebAgent] FORCE EXTRACT: {perception.page_type} has products with price signals - extracting immediately")
                products, items_seen = await self._extract_products_with_count(perception, original_query)
                if products:
                    logger.info(f"[WebAgent] Force extract found {len(products)} products")
                    return WebAgentResult(
                        products=products,
                        determination="products_found",
                        reason=f"Found {len(products)} matching products on {perception.page_type}",
                        page_type=perception.page_type,
                        items_seen=items_seen
                    )
                elif items_seen > 0:
                    # Products on page but none matched query - still valid
                    logger.info(f"[WebAgent] Force extract: {items_seen} items on page, none matched query")
                    return WebAgentResult(
                        products=[],
                        determination="no_relevant_products",
                        reason=f"Page has {items_seen} items but none match '{original_query}'",
                        page_type=perception.page_type,
                        items_seen=items_seen
                    )
                else:
                    # Extraction returned nothing - fall through to LLM decision
                    logger.info(f"[WebAgent] Force extract returned 0 items, falling back to LLM decision")

            # 2. DECIDE - Plan action
            decision = await self._decide(
                perception=perception,
                goal=goal,
                original_query=original_query,
                step=step,
                max_steps=max_steps
            )

            logger.info(f"[WebAgent] Decision: {decision.action} - {decision.reasoning[:80]}")

            # Check for stuck condition BEFORE acting
            if self.stuck_detector.would_be_stuck(self.page.url, decision):
                logger.warning(f"[WebAgent] Would repeat action on {decision.target_id}, trying alternate")
                decision = await self._get_alternate_decision(
                    perception, goal, original_query, decision
                )

            # 3. ACT - Execute decision
            if decision.action == "extract":
                products, items_seen = await self._extract_products_with_count(perception, original_query)
                if products:
                    logger.info(f"[WebAgent] Extracted {len(products)} products")
                    self._record_success(domain, decision)
                    return WebAgentResult(
                        products=products,
                        determination="products_found",
                        reason=f"Found {len(products)} matching products",
                        page_type=perception.page_type,
                        items_seen=items_seen
                    )
                else:
                    # No products found - but this might be valid (e.g., page has pet supplies, not live animals)
                    logger.info(f"[WebAgent] Extraction returned 0 matching products (saw {items_seen} items on page)")
                    if items_seen > 0:
                        # Page HAS products, just none matching query - this is valid determination
                        return WebAgentResult(
                            products=[],
                            determination="no_relevant_products",
                            reason=f"Page has {items_seen} items but none match '{original_query}'",
                            page_type=perception.page_type,
                            items_seen=items_seen
                        )
                    else:
                        # Page truly has no products - maybe wrong page type
                        self.stuck_detector.consecutive_failures += 1

            elif decision.action == "click":
                success = await self._execute_click(perception, decision)
                self.stuck_detector.record_action(self.page.url, decision, success)

                if success:
                    await asyncio.sleep(CLICK_WAIT_TIME)
                    self._record_action(domain, decision, success)
                else:
                    logger.warning(f"[WebAgent] Click failed for {decision.target_id}")

            elif decision.action == "type":
                success = await self._execute_type(perception, decision)
                self.stuck_detector.record_action(self.page.url, decision, success)

                if success:
                    await asyncio.sleep(CLICK_WAIT_TIME)
                    self._record_action(domain, decision, success)
                else:
                    logger.warning(f"[WebAgent] Type failed for {decision.target_id}")

            elif decision.action == "scroll":
                await self.page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(1.0)

            elif decision.action == "finish":
                logger.info("[WebAgent] Finish action - returning results")
                return self._build_final_result(last_perception, original_query)

            # 4. VERIFY - Check if we need intervention
            if self.stuck_detector.should_intervene():
                logger.warning("[WebAgent] Stuck - requesting intervention")
                resolved = await self._request_intervention(perception, goal)
                if resolved:
                    self.stuck_detector.consecutive_failures = 0
                else:
                    logger.error("[WebAgent] Intervention not resolved")
                    return WebAgentResult(
                        products=self.partial_results,
                        determination="blocked",
                        reason="Navigation stuck, intervention not resolved",
                        page_type=perception.page_type if perception else None,
                        items_seen=0
                    )

        logger.info(f"[WebAgent] Completed {max_steps} steps, returning results")
        return self._build_final_result(last_perception, original_query)

    def _build_final_result(
        self,
        last_perception: Optional[PagePerception],
        original_query: str
    ) -> WebAgentResult:
        """Build final result with appropriate determination."""
        if self.partial_results:
            return WebAgentResult(
                products=self.partial_results,
                determination="products_found",
                reason=f"Found {len(self.partial_results)} products",
                page_type=last_perception.page_type if last_perception else None,
                items_seen=len(self.partial_results)
            )

        # No products - determine why
        if not last_perception:
            return WebAgentResult(
                products=[],
                determination="error",
                reason="Could not perceive any pages",
                page_type=None,
                items_seen=0
            )

        # Check page type
        page_type = last_perception.page_type.lower() if last_perception.page_type else ""
        if page_type in ["blocked", "captcha", "login"]:
            return WebAgentResult(
                products=[],
                determination="blocked",
                reason=f"Page requires authentication or CAPTCHA",
                page_type=page_type,
                items_seen=0
            )

        if page_type in ["homepage", "error", "unknown"]:
            return WebAgentResult(
                products=[],
                determination="wrong_page_type",
                reason=f"Page type is '{page_type}', not a product listing",
                page_type=page_type,
                items_seen=0
            )

        # Page is a listing/search but no products matched
        if last_perception.has_products:
            return WebAgentResult(
                products=[],
                determination="no_relevant_products",
                reason=f"Page has products but none match '{original_query}'",
                page_type=page_type,
                items_seen=0  # We don't know exact count here
            )

        # Default: couldn't find anything
        return WebAgentResult(
            products=[],
            determination="no_relevant_products",
            reason="No matching products found after navigation",
            page_type=page_type,
            items_seen=0
        )

    # =========================================================================
    # PERCEIVE
    # =========================================================================

    async def _perceive(self, turn_dir: Optional[Path] = None) -> Optional[PagePerception]:
        """
        Perceive current page state using PageIntelligenceService.

        Returns combined understanding including:
        - Page type and zones
        - Interactive elements
        - Product presence
        """
        try:
            url = self.page.url
            domain = self._get_domain(url)

            # Get page understanding from PageIntelligenceService
            understanding = await self.page_intelligence.understand_page(
                self.page,
                url,
                extraction_goal="products"
            )

            # Extract interactive elements from page
            interactive_elements = await self._extract_interactive_elements()

            # Check for prices in page content
            text_content = await self._get_page_text()
            has_prices = bool(re.search(r'\$\d+(?:[,\.]\d+)?', text_content))

            # Determine page type string
            page_type = understanding.page_type.value if hasattr(understanding.page_type, 'value') else str(understanding.page_type)

            return PagePerception(
                url=url,
                page_type=page_type,
                has_products=understanding.has_products,
                has_prices=has_prices,
                interactive_elements=interactive_elements,
                page_understanding=understanding,
                text_preview=text_content[:500]
            )

        except Exception as e:
            logger.error(f"[WebAgent] Perception failed: {e}")
            return None

    async def _extract_interactive_elements(self) -> List[InteractiveElement]:
        """Extract clickable/interactive elements from page."""
        try:
            elements_data = await self.page.evaluate("""() => {
                const elements = [];
                let counter = 0;

                // Find all interactive elements
                const selectors = [
                    'a[href]',
                    'button',
                    'input[type="text"]',
                    'input[type="search"]',
                    '[role="button"]',
                    '[onclick]',
                    'select'
                ];

                for (const selector of selectors) {
                    document.querySelectorAll(selector).forEach(el => {
                        const rect = el.getBoundingClientRect();
                        // Skip invisible or off-screen elements
                        if (rect.width < 10 || rect.height < 10) return;
                        if (rect.top > window.innerHeight * 2) return;

                        const id = `e${counter++}`;
                        let type = 'link';
                        if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') type = 'button';
                        if (el.tagName === 'INPUT') type = 'input';
                        if (el.tagName === 'SELECT') type = 'select';

                        elements.push({
                            element_id: id,
                            element_type: type,
                            text: (el.textContent || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().substring(0, 100),
                            href: el.href || '',
                            bounds: {
                                top: rect.top,
                                left: rect.left,
                                width: rect.width,
                                height: rect.height
                            }
                        });
                    });
                }

                return elements.slice(0, 50);  // Limit for performance
            }""")

            return [
                InteractiveElement(
                    element_id=e['element_id'],
                    element_type=e['element_type'],
                    text=e['text'],
                    href=e.get('href', ''),
                    bounds=e['bounds']
                )
                for e in elements_data
            ]

        except Exception as e:
            logger.warning(f"[WebAgent] Failed to extract interactive elements: {e}")
            return []

    async def _get_page_text(self) -> str:
        """Get visible text content from page."""
        try:
            return await self.page.evaluate("""() => {
                return document.body.innerText.substring(0, 4000);
            }""")
        except Exception:
            return ""

    # =========================================================================
    # DECIDE
    # =========================================================================

    async def _decide(
        self,
        perception: PagePerception,
        goal: str,
        original_query: str,
        step: int,
        max_steps: int
    ) -> AgentDecision:
        """
        Use MIND LLM to decide next action.
        """
        domain = self._get_domain(perception.url)

        # Get site knowledge
        site_entry = self.knowledge_cache.get_entry(domain)
        site_knowledge = self._format_site_knowledge(site_entry) if site_entry else "No prior knowledge for this site."

        # Build prompt
        prompt = self._build_decision_prompt(
            perception=perception,
            goal=goal,
            original_query=original_query,
            site_knowledge=site_knowledge,
            step=step,
            max_steps=max_steps
        )

        try:
            result = await call_llm_json(
                prompt=prompt,
                llm_url=self.llm_url,
                llm_model=self.llm_model,
                llm_api_key=self.llm_api_key,
                max_tokens=500,
                temperature=0.5,  # MIND role
                timeout=20.0
            )

            action = result.get("action", "finish")
            target_id = result.get("target_id", "")
            target_text = result.get("target_text", "")
            input_text = result.get("input_text", "")
            reasoning = result.get("reasoning", "")
            confidence = float(result.get("confidence", 0.5))

            # Parse expected_state
            expected_state = None
            if "expected_state" in result:
                es = result["expected_state"]
                expected_state = ExpectedState(
                    page_type=es.get("page_type", ""),
                    must_see=es.get("must_see", [])
                )

            return AgentDecision(
                action=action,
                reasoning=reasoning,
                target_id=target_id,
                target_text=target_text,
                input_text=input_text,
                expected_state=expected_state,
                confidence=confidence
            )

        except Exception as e:
            logger.error(f"[WebAgent] Decision failed: {e}")
            # Default to finish on error
            return AgentDecision(
                action="finish",
                reasoning=f"Decision error: {e}",
                confidence=0.0
            )

    def _build_decision_prompt(
        self,
        perception: PagePerception,
        goal: str,
        original_query: str,
        site_knowledge: str,
        step: int,
        max_steps: int
    ) -> str:
        """Build prompt for navigation decision."""
        return f"""You are a web navigation agent. Your goal is to navigate a website to find products.

GOAL: {goal}
ORIGINAL QUERY: {original_query}
STEP: {step + 1}/{max_steps}

CURRENT PAGE:
{perception.format_for_decision()}

SITE KNOWLEDGE:
{site_knowledge}

ACTIONS AVAILABLE:
- click: Click an element by ID (e.g., "e5")
- type: Type text into an input element
- scroll: Scroll down to see more content
- extract: Extract products from the current page (use when you see products with prices)
- finish: Give up and return any partial results

DECISION RULES:
1. If AVAILABILITY shows "In-store only" or "Out of stock", use "finish" - no online products available
2. **CONTENT-FIRST**: If the page mentions the TARGET PRODUCT with PRICES visible, use "extract" FIRST
   - Breeder sites, classifieds, and small vendors show products in article/prose format (not grids)
   - Look for: product names + prices ($XX) + availability words ("available", "for sale")
   - If you see 2+ of these, try "extract" even if page_type is "article" or "content_prose"
   - Only navigate further if extraction returns 0 products
3. If the page has a product grid with visible prices, use "extract"
4. If you see a search box and haven't searched yet, type the product query
5. If you see relevant category links or filters, click them
6. If you've already clicked an element, don't click it again
7. If stuck after multiple attempts, use "finish"

Respond with JSON:
{{
  "action": "click|type|scroll|extract|finish",
  "target_id": "e5",
  "target_text": "text of element clicked",
  "input_text": "search query (for type action)",
  "reasoning": "Brief explanation of why this action",
  "expected_state": {{
    "page_type": "listing|product_detail|search_results",
    "must_see": ["price", "product name"]
  }},
  "confidence": 0.8
}}"""

    async def _get_alternate_decision(
        self,
        perception: PagePerception,
        goal: str,
        original_query: str,
        blocked_decision: AgentDecision
    ) -> AgentDecision:
        """Get alternate decision when stuck."""
        prompt = f"""You are a web navigation agent. Your previous action would repeat a click you already tried.

GOAL: {goal}
BLOCKED ACTION: Click element [{blocked_decision.target_id}] "{blocked_decision.target_text}"

You must choose a DIFFERENT action. Options:
1. Click a DIFFERENT element
2. Try scrolling to reveal more options
3. Extract products if any are visible
4. Finish and return partial results

CURRENT PAGE:
{perception.format_for_decision()}

Respond with JSON:
{{
  "action": "click|scroll|extract|finish",
  "target_id": "different_element_id",
  "reasoning": "Why this alternate action",
  "confidence": 0.6
}}"""

        try:
            result = await call_llm_json(
                prompt=prompt,
                llm_url=self.llm_url,
                llm_model=self.llm_model,
                llm_api_key=self.llm_api_key,
                max_tokens=300,
                temperature=0.5,
                timeout=15.0
            )

            return AgentDecision(
                action=result.get("action", "finish"),
                reasoning=result.get("reasoning", "Alternate action"),
                target_id=result.get("target_id", ""),
                target_text=result.get("target_text", ""),
                confidence=float(result.get("confidence", 0.5))
            )

        except Exception as e:
            logger.warning(f"[WebAgent] Alternate decision failed: {e}")
            return AgentDecision(
                action="finish",
                reasoning="Failed to get alternate decision",
                confidence=0.0
            )

    # =========================================================================
    # ACT
    # =========================================================================

    async def _execute_click(
        self,
        perception: PagePerception,
        decision: AgentDecision
    ) -> bool:
        """Execute click action."""
        # Find element by ID
        element = None
        for e in perception.interactive_elements:
            if e.element_id == decision.target_id:
                element = e
                break

        if not element:
            logger.warning(f"[WebAgent] Element {decision.target_id} not found")
            return False

        try:
            center_x, center_y = element.center
            await self.page.mouse.click(center_x, center_y)
            logger.info(f"[WebAgent] Clicked {decision.target_id} at ({center_x:.0f}, {center_y:.0f})")
            return True
        except Exception as e:
            logger.warning(f"[WebAgent] Click failed: {e}")
            return False

    async def _execute_type(
        self,
        perception: PagePerception,
        decision: AgentDecision
    ) -> bool:
        """Execute type action with search button fallback."""
        # Find input element
        element = None
        for e in perception.interactive_elements:
            if e.element_id == decision.target_id:
                element = e
                break

        if not element:
            # Try to find any search input
            for e in perception.interactive_elements:
                if e.element_type == "input" and ("search" in e.text.lower() or not e.text):
                    element = e
                    break

        if not element:
            logger.warning(f"[WebAgent] No input element found for typing")
            return False

        try:
            # Remember URL before typing to detect navigation
            url_before = self.page.url

            center_x, center_y = element.center
            await self.page.mouse.click(center_x, center_y)
            await asyncio.sleep(0.3)

            # Clear existing text and type new
            await self.page.keyboard.press("Control+a")
            await self.page.keyboard.type(decision.input_text, delay=TYPE_DELAY_MS)
            await self.page.keyboard.press("Enter")

            logger.info(f"[WebAgent] Typed '{decision.input_text}' into {decision.target_id}")

            # Wait for potential navigation
            await asyncio.sleep(2.0)

            # Check if page navigated
            if self.page.url == url_before:
                # Enter didn't work - try clicking a search button
                logger.info("[WebAgent] Enter didn't navigate, looking for search button")
                search_button = await self._find_search_button(perception)
                if search_button:
                    btn_x, btn_y = search_button.center
                    await self.page.mouse.click(btn_x, btn_y)
                    logger.info(f"[WebAgent] Clicked search button {search_button.element_id}")
                    await asyncio.sleep(2.0)

            return True
        except Exception as e:
            logger.warning(f"[WebAgent] Type failed: {e}")
            return False

    async def _find_search_button(
        self,
        perception: PagePerception
    ) -> Optional[InteractiveElement]:
        """Find a search/submit button near search input."""
        search_keywords = ["search", "go", "find", "submit", "🔍", "magnif"]

        for e in perception.interactive_elements:
            if e.element_type in ("button", "link"):
                text_lower = e.text.lower()
                if any(kw in text_lower for kw in search_keywords):
                    return e

        # Also try finding by aria-label via page evaluation
        try:
            btn_data = await self.page.evaluate("""() => {
                const btn = document.querySelector(
                    'button[type="submit"], ' +
                    'button[aria-label*="search" i], ' +
                    'button[aria-label*="Search" i], ' +
                    '[role="button"][aria-label*="search" i], ' +
                    '.search-button, .search-submit, .search-btn'
                );
                if (btn) {
                    const rect = btn.getBoundingClientRect();
                    return {
                        element_id: 'search_btn',
                        element_type: 'button',
                        text: btn.textContent?.trim() || 'Search',
                        bounds: {top: rect.top, left: rect.left, width: rect.width, height: rect.height}
                    };
                }
                return null;
            }""")

            if btn_data:
                return InteractiveElement(
                    element_id=btn_data['element_id'],
                    element_type=btn_data['element_type'],
                    text=btn_data['text'],
                    bounds=btn_data['bounds']
                )
        except Exception as e:
            logger.debug(f"[WebAgent] Search button lookup failed: {e}")

        return None

    async def _extract_products_with_count(
        self,
        perception: PagePerception,
        original_query: str
    ) -> Tuple[List[Product], int]:
        """
        Extract products from current page using simplified HTML-to-text pipeline.

        Uses the simplified extraction path:
        HTML → ContentSanitizer → Clean Text → ProseExtractor (LLM)

        This bypasses selector generation, which often fails due to
        hallucinated selectors that don't exist in the DOM.

        Returns:
            Tuple of (matching products, total items seen on page)
        """
        try:
            # PRIMARY: Use simplified extraction (HTML → clean text → LLM)
            # This bypasses selector generation which often fails
            items = await self.page_intelligence.extract_from_page_simplified(
                self.page,
                extraction_goal="products",
                query_context=original_query,
                max_tokens=4000
            )

            if not items:
                # FALLBACK: Try PageUnderstanding-based extraction
                # This may still fail on selector generation but try it anyway
                logger.info("[WebAgent] Simplified extraction returned 0, trying understanding-based extraction")
                items = await self.page_intelligence.extract(
                    self.page,
                    perception.page_understanding
                )

            # Total items seen on page (before filtering)
            items_seen = len(items) if items else 0

            # Convert to Product objects
            products = []
            for item in items[:MAX_PRODUCTS]:
                product = Product(
                    name=item.get("name", item.get("title", "Unknown")),
                    price=item.get("price", ""),
                    url=item.get("url", self.page.url),
                    description=item.get("description", ""),
                    vendor=self._get_domain(self.page.url),
                    in_stock=item.get("in_stock"),
                    confidence=float(item.get("confidence", 0.7))
                )
                products.append(product)

            # Add to partial results
            self.partial_results.extend(products)

            return products, items_seen

        except Exception as e:
            logger.error(f"[WebAgent] Extraction failed: {e}")
            return [], 0

    async def _extract_products(
        self,
        perception: PagePerception,
        original_query: str
    ) -> List[Product]:
        """Extract products from current page (legacy compatibility)."""
        products, _ = await self._extract_products_with_count(perception, original_query)
        return products

    # =========================================================================
    # VERIFY / INTERVENTION
    # =========================================================================

    async def _request_intervention(
        self,
        perception: PagePerception,
        goal: str
    ) -> bool:
        """Request human intervention when stuck."""
        try:
            intervention = await self.intervention_manager.request_intervention(
                blocker_type="navigation_stuck",
                url=perception.url,
                blocker_details={
                    "goal": goal,
                    "page_type": perception.page_type,
                    "consecutive_failures": self.stuck_detector.consecutive_failures,
                    "action_count": len(self.stuck_detector.action_history)
                }
            )

            logger.info(f"[WebAgent] Waiting for intervention: {intervention.intervention_id}")
            resolved = await intervention.wait_for_resolution(timeout=INTERVENTION_TIMEOUT)
            return resolved

        except Exception as e:
            logger.error(f"[WebAgent] Intervention request failed: {e}")
            return False

    # =========================================================================
    # SITE KNOWLEDGE
    # =========================================================================

    def _format_site_knowledge(self, entry: SiteKnowledgeEntry) -> str:
        """Format site knowledge for LLM prompt."""
        lines = [f"Domain: {entry.domain}"]

        if entry.successful_actions:
            lines.append("Successful actions:")
            for action in entry.successful_actions[:5]:
                lines.append(f"  - {action.get('action')}: \"{action.get('target_text', '')}\" for goal \"{action.get('goal', '')}\"")

        if entry.failed_actions:
            lines.append("Failed actions to avoid:")
            for action in entry.failed_actions[:3]:
                lines.append(f"  - {action.get('action')}: \"{action.get('target_text', '')}\" ({action.get('failure_reason', '')})")

        return "\n".join(lines)

    def _record_action(self, domain: str, decision: AgentDecision, success: bool):
        """Record action outcome for site knowledge learning."""
        trace = ActionTrace(
            goal="navigation",
            action=decision.action,
            target_text=decision.target_text,
            target_type="element",
            input_text=decision.input_text,
            outcome="success" if success else "failure",
            failure_reason="" if success else "action_failed"
        )

        entry = self.knowledge_cache.get_entry(domain)
        if not entry:
            entry = SiteKnowledgeEntry(domain=domain)

        entry.add_action_trace(trace)
        self.knowledge_cache.save_entry(entry)

    def _record_success(self, domain: str, decision: AgentDecision):
        """Record successful extraction for learning."""
        trace = ActionTrace(
            goal="extract_products",
            action="extract",
            target_text="",
            outcome="success",
            reached_page_type="listing"
        )

        entry = self.knowledge_cache.get_entry(domain)
        if not entry:
            entry = SiteKnowledgeEntry(domain=domain)

        entry.add_action_trace(trace)
        entry.success_count += 1
        self.knowledge_cache.save_entry(entry)

    # =========================================================================
    # UTILITIES
    # =========================================================================

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")
            return domain
        except Exception:
            return url

    def _page_notices_contain_prices(self, understanding: PageUnderstanding) -> bool:
        """
        Check if page notices contain price information.

        The ZoneIdentifier may detect prices in page notices (e.g., "We retire
        hamsters for $35") even when the main page text regex doesn't find them.
        This is a fallback price detection for the FORCE EXTRACT logic.
        """
        if not understanding or not understanding.page_notices:
            return False

        price_pattern = re.compile(r'\$\d+(?:[,\.]\d+)?')

        for notice in understanding.page_notices:
            if notice.message and price_pattern.search(notice.message):
                logger.debug(f"[WebAgent] Found price in page notice: {notice.message[:50]}")
                return True

        return False


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def get_web_agent(
    page: 'Page',
    llm_url: str = None,
    llm_model: str = None,
    llm_api_key: str = None,
    session_id: str = None
) -> WebAgent:
    """Create a WebAgent instance."""
    return WebAgent(
        page=page,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        session_id=session_id
    )
