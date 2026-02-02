"""
GoalDirectedNavigator - Universal web navigation that works on ANY website.

Instead of classifying websites into types and using type-specific extractors,
this system reasons about each page and decides whether to:
1. EXTRACT - Found relevant content, extract it
2. NAVIGATE - Need to go somewhere else, click a link
3. GIVE_UP - This site doesn't have what we need

Key innovation: After extraction, VALIDATES that extracted content actually
matches the goal. If we extracted "water bottles" when looking for "hamsters",
the system recognizes the mismatch and tries a different approach.

This handles:
- Unknown website layouts
- Multi-step navigation
- Contact-based vendors (breeders, etc.)
- E-commerce sites with wrong landing pages
- Any new website style without code changes
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable, TYPE_CHECKING
from urllib.parse import urlparse, urljoin, parse_qs, unquote, unquote_plus

import aiohttp

if TYPE_CHECKING:
    from playwright.async_api import Page
    from orchestrator.product_requirements import ProductRequirements

logger = logging.getLogger(__name__)


class NavigationAction(str, Enum):
    """Actions the navigator can take."""
    EXTRACT = "extract"      # Found relevant content, extract it
    NAVIGATE = "navigate"    # Click a link to go deeper
    GIVE_UP = "give_up"      # Site doesn't have what we need
    RETRY = "retry"          # Extraction didn't match goal, try different page


class ContentType(str, Enum):
    """Types of extractable content."""
    PRODUCT_LISTING = "product_listing"      # E-commerce product grid
    PRODUCT_DETAIL = "product_detail"        # Single product page
    CONTACT_VENDOR = "contact_vendor"        # Breeder/vendor with contact info
    MARKETPLACE_LISTING = "marketplace"      # Classifieds/marketplace
    INFORMATIONAL = "informational"          # Info page, may have links to products


@dataclass
class PagePerception:
    """Structured understanding of a web page."""
    url: str
    title: str
    main_heading: str
    nav_links: List[Dict[str, str]]  # [{text, href}, ...]
    content_headings: List[str]
    price_count: int
    has_cart: bool
    has_product_grid: bool
    has_email: bool
    has_phone: bool
    has_contact_form: bool
    body_preview: str
    screenshot_path: Optional[str] = None


@dataclass
class NavigationDecision:
    """LLM's decision about what to do on current page."""
    action: NavigationAction
    reason: str
    target: Optional[str] = None           # Link text/selector to click (for NAVIGATE)
    alternative: Optional[str] = None      # Backup target if first fails
    content_type: Optional[ContentType] = None  # Type of content to extract (for EXTRACT)
    extraction_hints: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Dict) -> 'NavigationDecision':
        """Parse LLM response into NavigationDecision."""
        action_str = data.get('action', 'give_up').lower()

        # Map action string to enum
        action_map = {
            'extract': NavigationAction.EXTRACT,
            'navigate': NavigationAction.NAVIGATE,
            'click': NavigationAction.NAVIGATE,  # Allow "click" as alias
            'give_up': NavigationAction.GIVE_UP,
            'retry': NavigationAction.RETRY,
        }
        action = action_map.get(action_str, NavigationAction.GIVE_UP)

        # Parse content type if present
        content_type = None
        hints = data.get('hints', data.get('extraction_hints', {}))
        if hints.get('content_type'):
            try:
                content_type = ContentType(hints['content_type'])
            except ValueError:
                content_type = ContentType.PRODUCT_LISTING

        return cls(
            action=action,
            reason=data.get('reason', 'No reason provided'),
            target=data.get('target'),
            alternative=data.get('alternative'),
            content_type=content_type,
            extraction_hints=hints
        )


@dataclass
class ExtractionValidation:
    """Result of validating extracted content against goal."""
    matches_goal: bool
    match_score: float  # 0.0 to 1.0
    reason: str
    suggested_action: NavigationAction
    navigation_hint: Optional[str] = None  # e.g., "Try clicking 'Hamsters' category"


@dataclass
class NavigatorResult:
    """Final result from the navigator."""
    success: bool
    claims: List[Any]  # Extracted claims/products
    content_type: ContentType
    steps_taken: int
    navigation_path: List[str]  # URLs visited
    validation_notes: str


class GoalDirectedNavigator:
    """
    Universal web navigator that finds goal-relevant content on ANY website.

    Instead of classifying websites into types, it reasons about each page
    and decides whether to extract or navigate further. After extraction,
    it validates that the content actually matches the goal.

    Example flow for furballcritters.com looking for "Syrian hamsters":
    1. Land on homepage (shows pet supplies in featured products)
    2. LLM sees "Hamsters" in nav → NAVIGATE to hamster category
    3. Extract products from hamster page
    4. VALIDATE: Are these hamsters? Yes → return results

    Example flow if extraction validation fails:
    1. Land on homepage
    2. LLM sees products → EXTRACT
    3. Extraction returns water bottles, food dishes
    4. VALIDATE: "water bottles" != "hamsters" → RETRY
    5. LLM looks for hamster-specific navigation → NAVIGATE
    6. Extract again from correct page
    """

    def __init__(
        self,
        llm_url: str = None,
        llm_model: str = None,
        llm_api_key: str = None,
        max_steps: int = 5,
        enable_screenshots: bool = True,
        use_unified_calibrator: bool = None
    ):
        """
        Initialize the navigator.

        Args:
            llm_url: URL for LLM API
            llm_model: Model ID to use
            llm_api_key: API key
            max_steps: Maximum navigation steps before giving up
            enable_screenshots: Whether to include screenshots in LLM reasoning
            use_unified_calibrator: Whether to use learned URL patterns (defaults to env var)
        """
        self.llm_url = llm_url or os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        self.llm_model = llm_model or os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        self.llm_api_key = llm_api_key or os.getenv("SOLVER_API_KEY", "qwen-local")
        self.max_steps = max_steps
        self.enable_screenshots = enable_screenshots

        # Unified calibrator integration
        self.use_unified_calibrator = use_unified_calibrator
        if self.use_unified_calibrator is None:
            self.use_unified_calibrator = os.getenv("USE_UNIFIED_CALIBRATOR", "false").lower() == "true"

        self._calibrator = None
        self._profile_store = None  # Backwards compat reference
        if self.use_unified_calibrator:
            try:
                # Using PageIntelligence adapter for backwards compatibility
                from orchestrator.page_intelligence.legacy_adapter import get_calibrator
                self._calibrator = get_calibrator()  # Uses PageIntelligenceService internally
                self._profile_store = self._calibrator  # Alias for backwards compat
                logger.info("[Navigator] Unified calibrator enabled - will use learned URL patterns")
            except ImportError as e:
                logger.warning(f"[Navigator] Could not import unified calibrator: {e}")
                self._calibrator = None

        # Recipe executor for LLM-integrated navigation (lazy loaded)
        self._recipe_executor = None
        self._requirements: Optional['ProductRequirements'] = None

    def _get_recipe_executor(self):
        """Lazy-load recipe executor to avoid circular imports."""
        if self._recipe_executor is None:
            try:
                from orchestrator.navigator_recipe_executor import NavigatorRecipeExecutor
                self._recipe_executor = NavigatorRecipeExecutor(
                    llm_url=self.llm_url,
                    llm_model=self.llm_model,
                    llm_api_key=self.llm_api_key
                )
                logger.info("[Navigator] Recipe executor initialized")
            except ImportError as e:
                logger.warning(f"[Navigator] Could not import recipe executor: {e}")
                return None
        return self._recipe_executor

    async def find_and_extract(
        self,
        page: 'Page',
        goal: str,
        extraction_callback: Callable,
        vendor: str = None,
        requirements: Optional['ProductRequirements'] = None
    ) -> NavigatorResult:
        """
        Navigate through website to find and extract goal-relevant content.

        This is the main entry point. It will:
        1. Perceive the current page
        2. Decide what to do (extract, navigate, or give up)
        3. If extract, validate that results match the goal
        4. If validation fails, try navigating to find better content

        Args:
            page: Playwright page object (already on starting URL)
            goal: What we're looking for (e.g., "Syrian hamsters for sale")
            extraction_callback: Async function(page, hints) -> List[claims]
            vendor: Vendor name for logging
            requirements: Optional ProductRequirements from Phase 1 for spec-based validation

        Returns:
            NavigatorResult with extracted claims and metadata
        """
        # Store requirements for use by decision methods
        self._requirements = requirements

        visited_urls = set()
        navigation_path = []
        start_time = time.time()
        vendor = vendor or urlparse(page.url).netloc

        if requirements:
            logger.info(f"[Navigator] Starting goal-directed navigation with requirements: {requirements.category}")
        logger.info(f"[Navigator] Starting goal-directed navigation for: {goal}")
        logger.info(f"[Navigator] Starting URL: {page.url}")

        for step in range(self.max_steps):
            current_url = page.url

            # Track navigation path
            if current_url not in navigation_path:
                navigation_path.append(current_url)

            # Avoid infinite loops
            url_key = current_url.split('?')[0]  # Ignore query params for dedup
            if url_key in visited_urls and step > 0:
                logger.warning(f"[Navigator] Already visited {url_key}, stopping")
                break
            visited_urls.add(url_key)

            # PERCEIVE: Understand what's on this page
            logger.info(f"[Navigator] Step {step + 1}/{self.max_steps}: Perceiving {current_url[:60]}...")
            perception = await self._perceive_page(page)

            # DECIDE: Ask LLM what to do
            decision = await self._decide_action(perception, goal, step, visited_urls)

            logger.info(
                f"[Navigator] Decision: {decision.action.value} - {decision.reason[:100]}"
            )

            # ACT based on decision
            if decision.action == NavigationAction.EXTRACT:
                # Found content to extract
                logger.info(f"[Navigator] Extracting content (type: {decision.content_type})")

                claims = await extraction_callback(
                    page=page,
                    hints=decision.extraction_hints
                )

                if not claims:
                    logger.warning("[Navigator] Extraction returned no claims")
                    # Continue navigating if we have steps left
                    if step < self.max_steps - 1:
                        # Try to find another path
                        decision = await self._decide_action(
                            perception, goal, step, visited_urls,
                            context="Extraction returned no results"
                        )
                        if decision.action == NavigationAction.NAVIGATE:
                            success = await self._navigate_to_target(page, decision.target)
                            if success:
                                continue
                    break

                # VALIDATE: Check if extracted content matches goal
                validation = await self._validate_extraction(claims, goal, perception)

                logger.info(
                    f"[Navigator] Validation: matches={validation.matches_goal}, "
                    f"score={validation.match_score:.2f}, reason={validation.reason[:80]}"
                )

                if validation.matches_goal:
                    # Success! Return the results
                    elapsed = time.time() - start_time
                    logger.info(
                        f"[Navigator] SUCCESS: Extracted {len(claims)} matching claims "
                        f"in {step + 1} steps ({elapsed:.1f}s)"
                    )

                    return NavigatorResult(
                        success=True,
                        claims=claims,
                        content_type=decision.content_type or ContentType.PRODUCT_LISTING,
                        steps_taken=step + 1,
                        navigation_path=navigation_path,
                        validation_notes=validation.reason
                    )
                else:
                    # Extracted content doesn't match goal!
                    # This is the furballcritters case - extracted water bottles instead of hamsters
                    logger.warning(
                        f"[Navigator] Extraction MISMATCH: {validation.reason}"
                    )

                    if step < self.max_steps - 1:
                        # Try to navigate to correct content
                        retry_decision = await self._decide_retry_action(
                            perception, goal, validation, visited_urls
                        )

                        if retry_decision.action == NavigationAction.NAVIGATE:
                            logger.info(
                                f"[Navigator] Retrying: navigating to {retry_decision.target}"
                            )
                            success = await self._navigate_to_target(page, retry_decision.target)
                            if success:
                                continue
                        elif retry_decision.action == NavigationAction.GIVE_UP:
                            logger.info(f"[Navigator] Giving up after mismatch: {retry_decision.reason}")
                            break
                    else:
                        # Out of steps, return partial results with warning
                        logger.warning("[Navigator] Out of steps, returning mismatched results")
                        return NavigatorResult(
                            success=False,
                            claims=claims,
                            content_type=decision.content_type or ContentType.PRODUCT_LISTING,
                            steps_taken=step + 1,
                            navigation_path=navigation_path,
                            validation_notes=f"MISMATCH: {validation.reason}"
                        )

            elif decision.action == NavigationAction.NAVIGATE:
                # Need to navigate to a different page
                logger.info(f"[Navigator] Navigating to: {decision.target}")

                # GUARDRAIL: Check if navigation would lose important filters
                current_url_context = self._analyze_url_context(current_url)
                if current_url_context["is_filtered"] and current_url_context.get("price_filter"):
                    # Check if target looks like it would lose the filter
                    risky_targets = ['filter', 'sort', 'refine', 'all ', 'clear', 'reset', 'category', 'browse']
                    target_lower = (decision.target or "").lower()

                    if any(risky in target_lower for risky in risky_targets):
                        logger.warning(
                            f"[Navigator] GUARDRAIL: Blocking navigation to '{decision.target}' - "
                            f"would likely lose price filter {current_url_context['price_filter']}. "
                            f"Forcing EXTRACT instead."
                        )
                        # Force extraction instead of risky navigation
                        claims = await extraction_callback(
                            page=page,
                            hints={
                                "content_type": "product_listing",
                                "has_prices": perception.price_count > 0,
                                "notes": "Guardrail prevented filter-losing navigation"
                            }
                        )

                        if claims:
                            # Validate and return
                            validation = await self._validate_extraction(claims, goal, perception)
                            elapsed = time.time() - start_time
                            return NavigatorResult(
                                success=validation.matches_goal,
                                claims=claims,
                                content_type=ContentType.PRODUCT_LISTING,
                                steps_taken=step + 1,
                                navigation_path=navigation_path,
                                validation_notes=f"Guardrail extraction: {validation.reason}"
                            )
                        # If no claims, let navigation proceed as fallback

                success = await self._navigate_to_target(page, decision.target)

                if not success and decision.alternative:
                    logger.info(f"[Navigator] Primary failed, trying alternative: {decision.alternative}")
                    success = await self._navigate_to_target(page, decision.alternative)

                if not success:
                    logger.warning("[Navigator] Navigation failed, trying to continue...")
                    # Let next iteration try a different approach

            elif decision.action == NavigationAction.GIVE_UP:
                # LLM determined this site doesn't have what we need
                logger.info(f"[Navigator] Giving up: {decision.reason}")
                break

        # Max steps reached or gave up
        elapsed = time.time() - start_time
        logger.warning(
            f"[Navigator] FAILED: Could not find goal-matching content "
            f"in {len(navigation_path)} pages ({elapsed:.1f}s)"
        )

        return NavigatorResult(
            success=False,
            claims=[],
            content_type=ContentType.INFORMATIONAL,
            steps_taken=len(navigation_path),
            navigation_path=navigation_path,
            validation_notes="Could not find goal-matching content"
        )

    async def _perceive_page(self, page: 'Page') -> PagePerception:
        """
        Capture structured understanding of the current page.

        This extracts key signals without using LLM (fast, cheap).
        """
        try:
            page_info = await page.evaluate('''() => {
                // Get navigation links
                const navSelectors = 'nav a, header a, [class*="menu"] a, [class*="nav"] a, [role="navigation"] a';
                const navLinks = [...document.querySelectorAll(navSelectors)]
                    .slice(0, 20)
                    .map(a => ({
                        text: (a.textContent || '').trim().substring(0, 60),
                        href: a.href || ''
                    }))
                    .filter(l => l.text && l.href && !l.href.startsWith('javascript:'));

                // Get main content headings
                const headingSelectors = 'main h1, main h2, main h3, article h1, article h2, .content h1, .content h2, #content h1, #content h2';
                const headings = [...document.querySelectorAll(headingSelectors)]
                    .slice(0, 10)
                    .map(h => (h.textContent || '').trim().substring(0, 100))
                    .filter(h => h.length > 2);

                // Count price patterns
                const bodyText = document.body.textContent || '';
                const priceMatches = bodyText.match(/\\$[\\d,]+\\.?\\d{0,2}/g) || [];

                // Get body preview (for context)
                const bodyPreview = bodyText
                    .substring(0, 2000)
                    .replace(/\\s+/g, ' ')
                    .trim();

                return {
                    title: document.title || '',
                    url: window.location.href,
                    h1: (document.querySelector('h1')?.textContent || '').trim().substring(0, 150),
                    nav_links: navLinks,
                    headings: headings,
                    price_count: priceMatches.length,
                    has_cart: !!(
                        document.querySelector('[class*="cart"]') ||
                        document.querySelector('[id*="cart"]') ||
                        document.querySelector('.add-to-cart') ||
                        document.querySelector('[data-action*="cart"]')
                    ),
                    has_product_grid: !!(
                        document.querySelector('[class*="product-grid"]') ||
                        document.querySelector('[class*="product-list"]') ||
                        document.querySelector('.products') ||
                        document.querySelector('[class*="item-grid"]')
                    ),
                    has_email: !!document.querySelector('[href^="mailto:"]'),
                    has_phone: !!document.querySelector('[href^="tel:"]'),
                    has_contact_form: !!(
                        document.querySelector('form[action*="contact"]') ||
                        document.querySelector('[class*="contact-form"]') ||
                        document.querySelector('form[id*="contact"]')
                    ),
                    body_preview: bodyPreview
                };
            }''')

            return PagePerception(
                url=page_info['url'],
                title=page_info['title'],
                main_heading=page_info['h1'],
                nav_links=page_info['nav_links'],
                content_headings=page_info['headings'],
                price_count=page_info['price_count'],
                has_cart=page_info['has_cart'],
                has_product_grid=page_info['has_product_grid'],
                has_email=page_info['has_email'],
                has_phone=page_info['has_phone'],
                has_contact_form=page_info['has_contact_form'],
                body_preview=page_info['body_preview']
            )

        except Exception as e:
            logger.error(f"[Navigator] Perception error: {e}")
            return PagePerception(
                url=page.url,
                title="",
                main_heading="",
                nav_links=[],
                content_headings=[],
                price_count=0,
                has_cart=False,
                has_product_grid=False,
                has_email=False,
                has_phone=False,
                has_contact_form=False,
                body_preview=""
            )

    def _analyze_url_context(self, url: str) -> Dict[str, Any]:
        """
        Analyze URL to extract context about filters, search terms, and page type.

        This helps the LLM understand what's already applied to the current page,
        preventing unnecessary navigation that could lose important filters.

        Uses learned patterns from UnifiedCalibrator when available,
        falls back to hard-coded patterns otherwise.

        Returns:
            {
                "url_type": "search_results" | "category" | "product" | "homepage" | "unknown",
                "is_filtered": bool,
                "search_query": str | None,
                "price_filter": {"min": float, "max": float} | None,
                "other_filters": [str],  # e.g., ["brand=nvidia", "in_stock=true"]
                "warnings": [str]  # e.g., ["Price filter applied - don't navigate away"]
            }
        """
        # Try learned patterns first (if unified calibrator is enabled)
        if self._calibrator:
            learned_context = self._get_learned_url_context(url)
            if learned_context and learned_context.get("price_filter"):
                # We have learned patterns for this site!
                logger.debug(f"[Navigator] Using learned URL patterns for {urlparse(url).netloc}")
                return learned_context

        # Fall back to hard-coded pattern matching
        parsed = urlparse(url)
        path = parsed.path.lower()
        query_string = parsed.query
        params = parse_qs(query_string)

        context = {
            "url_type": "unknown",
            "is_filtered": False,
            "search_query": None,
            "price_filter": None,
            "other_filters": [],
            "warnings": []
        }

        # Detect URL type from path patterns
        search_patterns = ['/s', '/search', '/results', '/pl', '/find', '/query']
        category_patterns = ['/category/', '/browse/', '/c/', '/dept/', '/shop/']
        product_patterns = ['/dp/', '/product/', '/item/', '/p/', '/pd/', '/ip/']

        if any(p in path for p in search_patterns) or any(k in params for k in ['q', 'k', 'query', 'keyword', 'search', 'st', 'ntt', 'd']):
            context["url_type"] = "search_results"
        elif any(p in path for p in product_patterns):
            context["url_type"] = "product"
        elif any(p in path for p in category_patterns):
            context["url_type"] = "category"
        elif path in ['/', '', '/index.html', '/home']:
            context["url_type"] = "homepage"

        # Extract search query from common parameters
        search_param_names = ['q', 'k', 'query', 'keyword', 'search', 'st', 'ntt', 'd', 'term', 'text']
        for param in search_param_names:
            if param in params:
                context["search_query"] = unquote(params[param][0])
                break

        # Generic price params only - site-specific parsing removed per LLM-first architecture
        # See: panda_system_docs/architecture/LLM-ROLES/CONTEXT_DISCIPLINE.md
        price_params = {
            'minPrice': lambda v: {'min': float(v)},
            'maxPrice': lambda v: {'max': float(v)},
            'price_min': lambda v: {'min': float(v)},
            'price_max': lambda v: {'max': float(v)},
            'lowPrice': lambda v: {'min': float(v)},
            'highPrice': lambda v: {'max': float(v)},
        }

        price_filter = {}
        for param, parser in price_params.items():
            if param in params:
                try:
                    result = parser(params[param][0])
                    if result:
                        price_filter.update(result)
                        context["is_filtered"] = True
                except (ValueError, IndexError) as e:
                    logger.debug(f"[FilterParsing] Could not parse filter param '{param}' with value '{params[param][0]}': {e}")

        if price_filter:
            context["price_filter"] = price_filter
            if 'max' in price_filter:
                context["warnings"].append(
                    f"Price filter applied: max ${price_filter['max']:.0f}. "
                    f"Navigating away may LOSE this filter!"
                )

        # Extract other filters
        filter_keywords = ['brand', 'category', 'color', 'size', 'rating', 'shipping', 'seller', 'condition', 'rh', 'fq']
        for param, values in params.items():
            param_lower = param.lower()
            if any(kw in param_lower for kw in filter_keywords):
                for v in values:
                    context["other_filters"].append(f"{param}={v[:50]}")
                    context["is_filtered"] = True

        # Add warning if heavily filtered
        if len(context["other_filters"]) > 2 or context["price_filter"]:
            context["warnings"].append(
                "This page has filters applied. If you navigate to 'Filters', 'Sort', or category links, "
                "you may lose these filters and get irrelevant results."
            )

        return context

    def _get_learned_url_context(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Get URL context using learned patterns from UnifiedCalibrator.

        Returns None if no profile exists for the domain.
        """
        if not self._calibrator:
            return None

        try:
            # UnifiedCalibrator.get_url_context() uses cached schemas directly
            context = self._calibrator.get_url_context(url)

            # Check if this came from a learned schema vs basic parsing
            if context.get("source") != "learned_schema":
                return None  # Only return if we have actual learned patterns

            # Convert to our expected format
            result = {
                "url_type": "search_results" if context.get("search_query") else "unknown",
                "is_filtered": context.get("is_filtered", False),
                "search_query": context.get("search_query"),
                "price_filter": context.get("price_filter"),
                "other_filters": [],
                "warnings": [],
                "source": "learned_patterns"
            }

            # Add warnings if filtered
            if result["price_filter"]:
                pf = result["price_filter"]
                price_str = ""
                if isinstance(pf, dict):
                    if pf.get("min"):
                        price_str += f"${pf['min']:.0f}"
                    if pf.get("max"):
                        price_str += f" - ${pf['max']:.0f}" if price_str else f"up to ${pf['max']:.0f}"
                    if not price_str and pf.get("raw"):
                        price_str = f"raw: {pf['raw']}"
                else:
                    price_str = str(pf)
                if price_str:
                    result["warnings"].append(
                        f"Price filter applied: {price_str}. Navigating away may LOSE this filter!"
                    )

            return result

        except Exception as e:
            logger.warning(f"[Navigator] Error getting learned URL context: {e}")
            return None

    async def _decide_action(
        self,
        perception: PagePerception,
        goal: str,
        step: int,
        visited_urls: set,
        context: str = None
    ) -> NavigationDecision:
        """
        Ask LLM to decide what to do on this page.

        The LLM reasons about:
        - Does this page have what we're looking for?
        - If not, where should we navigate?
        - Should we give up?

        Now includes URL context analysis to help LLM understand existing filters.
        Uses recipe executor when requirements are available for spec-aware decisions.
        """
        # If we have requirements and recipe executor, use recipe-compliant path
        if self._requirements and self._get_recipe_executor():
            try:
                page_state = {
                    "url": perception.url,
                    "title": perception.title,
                    "content_summary": f"{perception.main_heading}\n{perception.body_preview[:500]}",
                    "visible_products": [h for h in perception.content_headings if h][:10],
                    "navigation_links": [link.get("text", "") for link in perception.nav_links[:10]]
                }

                result = await self._recipe_executor.decide_action(
                    self._requirements,
                    page_state
                )

                # Convert recipe executor result to NavigationDecision
                action_map = {
                    "EXTRACT": NavigationAction.EXTRACT,
                    "NAVIGATE": NavigationAction.NAVIGATE,
                    "GIVE_UP": NavigationAction.GIVE_UP
                }
                action = action_map.get(result.action, NavigationAction.GIVE_UP)

                logger.info(f"[Navigator] Recipe-based decision: {action.value} - {result.reason}")

                return NavigationDecision(
                    action=action,
                    reason=result.reason,
                    target=result.navigate_to,
                    alternative=None,
                    extraction_hints={"content_type": "product_listing", "has_prices": True}
                )
            except Exception as e:
                logger.warning(f"[Navigator] Recipe executor failed, falling back to legacy: {e}")
                # Fall through to legacy implementation

        # Analyze URL to understand existing filters and page type
        url_context = self._analyze_url_context(perception.url)

        # Log URL context for debugging
        if url_context["is_filtered"]:
            logger.info(
                f"[Navigator] URL context: type={url_context['url_type']}, "
                f"filtered={url_context['is_filtered']}, "
                f"price_filter={url_context.get('price_filter')}"
            )

        # Format navigation links for prompt
        nav_text = "\n".join([
            f"  - '{link['text']}' → {link['href'][:80]}"
            for link in perception.nav_links[:15]
        ]) or "  (no navigation links found)"

        # Format headings
        headings_text = "\n".join([
            f"  - {h}" for h in perception.content_headings[:8]
        ]) or "  (no content headings found)"

        # Build URL context section for prompt
        url_context_text = f"- Page Type: {url_context['url_type']}"
        if url_context["search_query"]:
            url_context_text += f"\n- Search Query in URL: \"{url_context['search_query']}\""
        if url_context["price_filter"]:
            pf = url_context["price_filter"]
            price_str = ""
            if 'min' in pf:
                price_str += f"${pf['min']:.0f}"
            if 'max' in pf:
                price_str += f" - ${pf['max']:.0f}" if price_str else f"up to ${pf['max']:.0f}"
            url_context_text += f"\n- ⚠️ PRICE FILTER ALREADY APPLIED: {price_str}"
        if url_context["other_filters"]:
            url_context_text += f"\n- Other Filters: {', '.join(url_context['other_filters'][:5])}"

        # Build warnings section
        warnings_text = ""
        if url_context["warnings"]:
            warnings_text = "\n\n⚠️ CRITICAL WARNINGS:\n" + "\n".join(f"- {w}" for w in url_context["warnings"])

        # Load base prompt from file
        prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "navigation" / "decision.md"
        if prompt_path.exists():
            base_prompt = prompt_path.read_text()
        else:
            logger.warning(f"[Navigator] Prompt file not found: {prompt_path}")
            base_prompt = "You are navigating a website. Decide: extract, navigate, or give_up. Respond in JSON with action, reason, target, alternative, and hints."

        prompt = f"""{base_prompt}

## Current Task

Find: "{goal}"

## Current Page

URL: {perception.url}
Title: {perception.title}
Main Heading: {perception.main_heading}

## URL Analysis (filters already applied to this page)

{url_context_text}
{warnings_text}

## Navigation Links Available

{nav_text}

## Content Headings on Page

{headings_text}

## Page Indicators

- Price patterns found: {perception.price_count}
- Has shopping cart: {perception.has_cart}
- Has product grid/listing: {perception.has_product_grid}
- Has contact email: {perception.has_email}
- Has contact phone: {perception.has_phone}
- Has contact form: {perception.has_contact_form}

## Content Preview (first 800 chars)

{perception.body_preview[:800]}

## Navigation Status

- This is step {step + 1} of {self.max_steps}
- Already visited: {len(visited_urls)} pages
{f'- Context: {context}' if context else ''}"""

        try:
            response = await self._llm_call(prompt, max_tokens=400)

            # Parse JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
                return NavigationDecision.from_json(data)
            else:
                logger.warning(f"[Navigator] Could not parse LLM response: {response[:200]}")
                return NavigationDecision(
                    action=NavigationAction.GIVE_UP,
                    reason="Could not parse navigation decision"
                )

        except Exception as e:
            logger.error(f"[Navigator] Decision error: {e}")
            return NavigationDecision(
                action=NavigationAction.GIVE_UP,
                reason=f"Error making decision: {str(e)}"
            )

    async def _validate_extraction(
        self,
        claims: List[Any],
        goal: str,
        perception: PagePerception
    ) -> ExtractionValidation:
        """
        Validate that extracted content actually matches the goal.

        This catches cases like furballcritters where we extracted
        "water bottles" when looking for "hamsters".

        When requirements are available, uses recipe-based spec validation
        to check if products match acceptable_alternatives and deal_breakers.
        """
        if not claims:
            return ExtractionValidation(
                matches_goal=False,
                match_score=0.0,
                reason="No claims extracted",
                suggested_action=NavigationAction.NAVIGATE
            )

        # If we have requirements and recipe executor, use recipe-based validation
        if self._requirements and self._get_recipe_executor():
            try:
                # Convert claims to product dicts
                products = []
                for i, claim in enumerate(claims):
                    if hasattr(claim, 'title'):
                        products.append({
                            "title": claim.title,
                            "price": getattr(claim, 'price', None),
                            "specs": getattr(claim, 'specs', {}),
                            "url": getattr(claim, 'url', "")
                        })
                    elif isinstance(claim, dict):
                        products.append({
                            "title": claim.get('title', claim.get('name', "")),
                            "price": claim.get('price'),
                            "specs": claim.get('specs', {}),
                            "url": claim.get('url', "")
                        })

                if products:
                    result = await self._recipe_executor.validate_products(
                        self._requirements,
                        products
                    )

                    # Determine if overall validation passes
                    match_ratio = len(result.matches) / len(products) if products else 0
                    matches_goal = match_ratio >= 0.3  # At least 30% match

                    logger.info(f"[Navigator] Recipe-based validation: {len(result.matches)}/{len(products)} products match requirements")

                    return ExtractionValidation(
                        matches_goal=matches_goal,
                        match_score=match_ratio,
                        reason=f"{len(result.matches)} of {len(products)} products match requirements",
                        suggested_action=NavigationAction.NAVIGATE if not matches_goal else None
                    )
            except Exception as e:
                logger.warning(f"[Navigator] Recipe-based validation failed, falling back: {e}")
                # Fall through to legacy validation

        # Build summary of what was extracted
        claim_summaries = []
        for claim in claims[:10]:  # Check first 10
            if hasattr(claim, 'title'):
                title = claim.title
            elif isinstance(claim, dict):
                title = claim.get('title', claim.get('name', str(claim)))
            else:
                title = str(claim)
            claim_summaries.append(title[:100])

        claims_text = "\n".join([f"  - {s}" for s in claim_summaries])

        # Load base prompt from file
        prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "navigation" / "extraction_validator.md"
        if prompt_path.exists():
            base_prompt = prompt_path.read_text()
        else:
            logger.warning(f"[Navigator] Prompt file not found: {prompt_path}")
            base_prompt = "Validate if extracted items match the goal. Respond in JSON with matches_goal, match_score, reason, suggested_action, and navigation_hint."

        prompt = f"""{base_prompt}

## Current Validation Task

Goal: "{goal}"

### Extracted Items ({len(claims)} total)

{claims_text}

### Page Context

URL: {perception.url}
Title: {perception.title}"""

        try:
            response = await self._llm_call(prompt, max_tokens=300)

            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())

                action_map = {
                    'continue': NavigationAction.EXTRACT,
                    'navigate': NavigationAction.NAVIGATE,
                    'retry': NavigationAction.RETRY,
                    'give_up': NavigationAction.GIVE_UP,
                }

                return ExtractionValidation(
                    matches_goal=data.get('matches_goal', False),
                    match_score=float(data.get('match_score', 0.0)),
                    reason=data.get('reason', 'No reason provided'),
                    suggested_action=action_map.get(
                        data.get('suggested_action', 'give_up'),
                        NavigationAction.GIVE_UP
                    ),
                    navigation_hint=data.get('navigation_hint')
                )
            else:
                # Couldn't parse, assume match (conservative)
                return ExtractionValidation(
                    matches_goal=True,
                    match_score=0.5,
                    reason="Could not validate, assuming match",
                    suggested_action=NavigationAction.EXTRACT
                )

        except Exception as e:
            logger.error(f"[Navigator] Validation error: {e}")
            # On error, assume match to avoid blocking valid results
            return ExtractionValidation(
                matches_goal=True,
                match_score=0.5,
                reason=f"Validation error: {str(e)}",
                suggested_action=NavigationAction.EXTRACT
            )

    async def _decide_retry_action(
        self,
        perception: PagePerception,
        goal: str,
        validation: ExtractionValidation,
        visited_urls: set
    ) -> NavigationDecision:
        """
        Decide what to do after extraction validation failed.

        The extracted content didn't match the goal (e.g., extracted water bottles
        when looking for hamsters). Look for a better navigation path.
        """
        nav_text = "\n".join([
            f"  - '{link['text']}' → {link['href'][:60]}"
            for link in perception.nav_links[:15]
        ]) or "  (no navigation links found)"

        # Load base prompt from file
        prompt_path = Path(__file__).parent.parent / "apps" / "prompts" / "navigation" / "fallback.md"
        if prompt_path.exists():
            base_prompt = prompt_path.read_text()
        else:
            logger.warning(f"[Navigator] Prompt file not found: {prompt_path}")
            base_prompt = "Find an alternative navigation path after extraction mismatch. Respond in JSON with action, reason, target, and alternative."

        prompt = f"""{base_prompt}

## Current Situation

Goal: "{goal}"
Problem: {validation.reason}
{f'Hint: {validation.navigation_hint}' if validation.navigation_hint else ''}

### Current Page

URL: {perception.url}
Title: {perception.title}

### Navigation Links Available

{nav_text}

### Key Item Type to Look For

Primary keyword: "{goal.split()[0]}" """

        try:
            response = await self._llm_call(prompt, max_tokens=300)

            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
                return NavigationDecision.from_json(data)
            else:
                return NavigationDecision(
                    action=NavigationAction.GIVE_UP,
                    reason="Could not find alternative navigation"
                )

        except Exception as e:
            logger.error(f"[Navigator] Retry decision error: {e}")
            return NavigationDecision(
                action=NavigationAction.GIVE_UP,
                reason=f"Error: {str(e)}"
            )

    async def _navigate_to_target(self, page: 'Page', target: str) -> bool:
        """
        Click a navigation target to move to a new page.

        Tries multiple matching strategies:
        1. Exact text match
        2. Partial text match
        3. As CSS selector
        """
        if not target:
            return False

        original_url = page.url

        # Strategy 1: Exact text match (case-insensitive)
        try:
            # Use getByRole or getByText for better matching
            await page.get_by_role("link", name=target).first.click(timeout=3000)
            await page.wait_for_load_state('domcontentloaded', timeout=10000)
            if page.url != original_url:
                logger.info(f"[Navigator] Navigated via exact text: {target}")
                return True
        except Exception as e:
            logger.debug(f"[Navigation] Strategy 1 (exact text) failed for '{target}': {e}")

        # Strategy 2: Partial text match
        try:
            await page.click(f'a:has-text("{target}")', timeout=3000)
            await page.wait_for_load_state('domcontentloaded', timeout=10000)
            if page.url != original_url:
                logger.info(f"[Navigator] Navigated via partial text: {target}")
                return True
        except Exception as e:
            logger.debug(f"[Navigation] Strategy 2 (partial text) failed for '{target}': {e}")

        # Strategy 3: Contains text (more lenient)
        try:
            # Find link containing the target text
            links = await page.query_selector_all('a')
            for link in links:
                text = await link.text_content()
                if text and target.lower() in text.lower():
                    await link.click(timeout=3000)
                    await page.wait_for_load_state('domcontentloaded', timeout=10000)
                    if page.url != original_url:
                        logger.info(f"[Navigator] Navigated via text contains: {target}")
                        return True
                    break
        except Exception as e:
            logger.debug(f"[Navigation] Strategy 3 (text contains) failed for '{target}': {e}")

        # Strategy 4: As href contains
        try:
            # Try to find link with href containing target
            target_slug = target.lower().replace(' ', '-').replace('_', '-')
            await page.click(f'a[href*="{target_slug}"]', timeout=3000)
            await page.wait_for_load_state('domcontentloaded', timeout=10000)
            if page.url != original_url:
                logger.info(f"[Navigator] Navigated via href: {target_slug}")
                return True
        except Exception as e:
            logger.debug(f"[Navigation] Strategy 4 (href contains) failed for '{target}': {e}")

        logger.warning(f"[Navigator] Could not navigate to: {target}")
        return False

    async def _llm_call(self, prompt: str, max_tokens: int = 500) -> str:
        """Make an LLM API call."""

        payload = {
            "model": self.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3  # Low temperature for consistent decisions
        }

        headers = {
            "Content-Type": "application/json"
        }
        if self.llm_api_key:
            headers["Authorization"] = f"Bearer {self.llm_api_key}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.llm_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise Exception(f"LLM API error {resp.status}: {text[:200]}")

                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]

        except Exception as e:
            logger.error(f"[Navigator] LLM call failed: {e}")
            raise


# Convenience function
async def navigate_and_extract(
    page: 'Page',
    goal: str,
    extraction_callback: Callable,
    **kwargs
) -> NavigatorResult:
    """
    Navigate a website to find and extract goal-relevant content.

    Args:
        page: Playwright page (already on starting URL)
        goal: What to find (e.g., "Syrian hamsters for sale")
        extraction_callback: Async function(page, hints) -> List[claims]
        **kwargs: Additional args for GoalDirectedNavigator

    Returns:
        NavigatorResult with extracted claims
    """
    navigator = GoalDirectedNavigator(**kwargs)
    return await navigator.find_and_extract(page, goal, extraction_callback)
