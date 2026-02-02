# Unified WebAgent Architecture

**Status:** SPECIFICATION
**Version:** 1.0
**Created:** 2026-01-19
**Supersedes:** UniversalAgent, SmartExtractor, AdaptiveExtractor, UnifiedWebExtractor fallback chains

---

## Overview

WebAgent is the **single, unified system** for all web navigation and extraction in Pandora. It replaces the previous architecture of 5+ overlapping systems with fallback chains.

**Core principle:** Navigate websites like a person would - perceive the page, decide what to do, act, and verify the result.

---

## Problem Statement

The previous architecture had multiple overlapping systems:

| System | Purpose | Problem |
|--------|---------|---------|
| `UniversalAgent` | Navigation + extraction | Gets stuck clicking same elements, 90s timeouts |
| `SmartExtractor` | Selector-based extraction | No navigation, only extracts loaded pages |
| `AdaptiveExtractor` | Multi-strategy extraction | DEPRECATED, complex fallbacks |
| `UnifiedWebExtractor` | Multi-strategy extraction | DEPRECATED, complex fallbacks |
| `PageIntelligenceService` | Page understanding | Good, but not integrated with navigation |

The research orchestrator chained these with multiple fallbacks:
```
UniversalAgent → timeout? → SmartExtractor → fail? → DOM fallback → OCR fallback
```

This resulted in:
- Unpredictable behavior
- Silent quality degradation
- Difficult debugging
- The system "working" by accident through fallback layers

---

## Solution: One Unified WebAgent

```
┌─────────────────────────────────────────────────────────────┐
│                        WebAgent                              │
│                                                              │
│    ┌──────────────────────────────────────────────────┐     │
│    │                 PERCEIVE                          │     │
│    │           (PageIntelligenceService)               │     │
│    │  - Screenshot + DOM + OCR capture                 │     │
│    │  - Zone identification                            │     │
│    │  - Page type classification                       │     │
│    │  - Interactive element detection                  │     │
│    └──────────────────────────────────────────────────┘     │
│                           │                                  │
│                           ▼                                  │
│    ┌──────────────────────────────────────────────────┐     │
│    │                  DECIDE                           │     │
│    │               (MIND LLM)                          │     │
│    │  - Given: page understanding, goal, history       │     │
│    │  - Output: action + target + expected_state       │     │
│    │  - Actions: click, type, scroll, extract, finish  │     │
│    └──────────────────────────────────────────────────┘     │
│                           │                                  │
│                           ▼                                  │
│    ┌──────────────────────────────────────────────────┐     │
│    │                   ACT                             │     │
│    │              (Playwright)                         │     │
│    │  - Execute the decided action                     │     │
│    │  - Wait for page response                         │     │
│    └──────────────────────────────────────────────────┘     │
│                           │                                  │
│                           ▼                                  │
│    ┌──────────────────────────────────────────────────┐     │
│    │                 VERIFY                            │     │
│    │  - Did page change as expected?                   │     │
│    │  - Stuck detection (same element twice = stuck)   │     │
│    │  - Error page detection                           │     │
│    └──────────────────────────────────────────────────┘     │
│                           │                                  │
│              ┌────────────┴────────────┐                    │
│              ▼                         ▼                    │
│         [Continue]                [Intervention]            │
│         Loop back                 Human needed              │
│         to PERCEIVE               for blockers              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. PageIntelligenceService (PERCEIVE)

**Role:** Single source of truth for page understanding.

**Location:** `apps/services/orchestrator/page_intelligence/service.py`

**Responsibilities:**
- Capture screenshot, DOM, and OCR data
- Identify content zones (navigation, products, search, filters)
- Classify page type (listing, pdp, search_results, homepage, error)
- Extract interactive elements with bounding boxes

**Output:**
```python
@dataclass
class PageUnderstanding:
    url: str
    page_type: str  # "listing" | "pdp" | "search" | "homepage" | "error" | "blocked"
    zones: List[ContentZone]
    interactive_elements: List[InteractiveElement]
    products: List[Product]  # Only populated if page_type in ["listing", "pdp"]
    text_content: str
    has_prices: bool
    confidence: float
```

---

## WebAgent Result Contract

WebAgent returns a `WebAgentResult` with a **determination signal** that tells the orchestrator WHY the result was produced:

```python
@dataclass
class WebAgentResult:
    products: List[Product]
    determination: str  # See values below
    reason: Optional[str] = None
    page_type: Optional[str] = None
    items_seen: int = 0  # How many items were on the page
```

### Determination Values

| Value | Meaning | Orchestrator Action |
|-------|---------|---------------------|
| `products_found` | Successfully extracted matching products | Use products, record success |
| `no_relevant_products` | Page examined, nothing matches query | **Skip to next vendor** (no fallback!) |
| `no_online_availability` | Products exist but only available in-store | Skip vendor, record availability info for user |
| `wrong_page_type` | Not a product listing (homepage, blog) | Skip vendor, optionally create intervention |
| `blocked` | CAPTCHA, login wall detected | Create intervention |
| `error` | Technical failure | Record failure, create intervention |

### Early Exit for Availability

When PageIntelligence detects `availability_status: in_store_only` or `out_of_stock`, WebAgent immediately returns `no_online_availability` without further navigation. This saves time by not clicking through pages when we already know there are no online products.

**Example:** Petco.com shows "Syrian Hamster (0) In-Store Only"
- PageIntelligence detects: `availability_status: in_store_only`
- WebAgent returns immediately: `determination="no_online_availability"`
- Orchestrator skips to next vendor (saves ~90 seconds)

### Availability Detection Rules

PageIntelligence uses these rules to determine `availability_status`:

**1. Visible Price = Purchasable (Default to `available_online`)**

If a specific price is visible ($XX), the item is likely purchasable. Default to `available_online` unless there is EXPLICIT in-store-only language.

**2. Breeder/Adoption Site Terminology**

Small breeders use different language than retailers:
- "retire", "rehome", "adopt", "going-home fee" = FOR SALE (`available_online`)
- These sites require pickup but ARE online-purchasable vendors

**3. Only Mark `in_store_only` With EXPLICIT Language**

Only use `in_store_only` when you see explicit statements like:
- "Sold in stores only"
- "Not available for online purchase"
- "Check your local store for availability"

### Content-First Extraction Rule

WebAgent uses "content-first" extraction for non-e-commerce sites:

**Problem:** Breeder sites, classifieds, and small vendors show products in article/prose format, not product grids. WebAgent was navigating endlessly looking for a "product listing" page.

**Solution:** If the page mentions the TARGET PRODUCT with PRICES visible, try `extract` action FIRST, even if `page_type` is "article" or "content_prose". Only navigate further if extraction returns 0 products.

**Indicators to extract immediately:**
- Product names matching query (e.g., "Syrian hamster")
- Prices visible ($XX)
- Availability words ("available", "for sale", "ready")

If 2+ indicators present → try extraction before navigation.

### Key Insight

**"0 products extracted" is NOT the same as "extraction failed".**

When WebAgent visits Petco.com looking for "live Syrian hamster":
- WebAgent sees 50 pet supplies on the page
- WebAgent extracts 0 matching products (no live animals)
- This is `determination="no_relevant_products"`, NOT a failure

The orchestrator should **accept this as a valid result** and move to the next vendor, NOT trigger fallback extraction chains that would waste time extracting those 50 supplies just to filter them all out.

### 2. MIND LLM (DECIDE)

**Role:** Navigation decision making.

**Model:** Qwen3-Coder-30B-AWQ
**Temperature:** 0.5

**Input:**
```json
{
  "goal": "find the cheapest laptop with nvidia gpu",
  "original_query": "cheapest laptop with nvidia gpu",
  "page_understanding": { /* PageUnderstanding */ },
  "action_history": [ /* previous actions in this session */ ],
  "site_knowledge": { /* learned patterns for this domain */ }
}
```

**Output:**
```json
{
  "action": "click",
  "target_id": "c12",
  "reasoning": "Clicking 'Sort by Price: Low to High' to show cheapest first",
  "expected_state": {
    "page_type": "listing",
    "must_see": ["$", "laptop"]
  },
  "confidence": 0.85
}
```

**Actions:**
| Action | Description | Required Fields |
|--------|-------------|-----------------|
| `click` | Click an element | `target_id` |
| `type` | Type text into input | `target_id`, `input_text` |
| `scroll` | Scroll the page | - |
| `extract` | Extract products from current page | - |
| `finish` | Done navigating, return results | - |

### 3. Playwright (ACT)

**Role:** Execute browser actions.

**Responsibilities:**
- Click at element center coordinates
- Type text with human-like delays
- Scroll page
- Wait for navigation/network idle

**Implementation:**
```python
async def execute_action(self, action: AgentDecision, page_understanding: PageUnderstanding):
    if action.action == "click":
        element = page_understanding.get_element(action.target_id)
        if element:
            await self.page.mouse.click(element.center_x, element.center_y)
            await asyncio.sleep(CLICK_WAIT_TIME)
    elif action.action == "type":
        element = page_understanding.get_element(action.target_id)
        if element:
            await self.page.mouse.click(element.center_x, element.center_y)
            await self.page.keyboard.type(action.input_text, delay=75)
            await self.page.keyboard.press("Enter")
    elif action.action == "scroll":
        await self.page.evaluate("window.scrollBy(0, 500)")
    elif action.action == "extract":
        return await self._extract_products(page_understanding)
```

### 4. StuckDetector (VERIFY)

**Role:** Prevent infinite loops and detect failures.

**Key insight:** If we click the same element twice, we're stuck.

```python
class StuckDetector:
    def __init__(self):
        self.clicked_elements: Set[Tuple[str, str]] = set()  # (url, element_id)
        self.action_history: List[AgentDecision] = []
        self.consecutive_failures = 0

    def would_be_stuck(self, url: str, action: AgentDecision) -> bool:
        """Check if this action would repeat a previous click."""
        if action.action != "click":
            return False
        key = (url, action.target_id)
        return key in self.clicked_elements

    def record_action(self, url: str, action: AgentDecision, success: bool):
        """Record an action for future stuck detection."""
        if action.action == "click":
            self.clicked_elements.add((url, action.target_id))
        self.action_history.append(action)

        if not success:
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 0

    def should_intervene(self) -> bool:
        """Check if human intervention is needed."""
        return self.consecutive_failures >= 3
```

---

## Navigation Flow

### Goal-Oriented Navigation

WebAgent navigates based on the user's goal, not hardcoded rules:

```
User Query: "cheapest laptop with nvidia gpu"
Goal: "find the cheapest laptop with nvidia gpu and extract its details"

Step 1: Visit bestbuy.com
  PERCEIVE: Homepage with search box (c3), categories
  DECIDE: Type "laptop nvidia gpu" into search box
  ACT: Click c3, type query, press Enter
  VERIFY: Page changed to search results ✓

Step 2: Search results page
  PERCEIVE: Listing page with 24 products, sort dropdown (c12)
  DECIDE: Click "Sort by Price: Low to High" to show cheapest first
  ACT: Click c12
  VERIFY: Products reordered by price ✓

Step 3: Sorted listing
  PERCEIVE: Listing page, first product is cheapest
  DECIDE: Extract products from this page
  ACT: Extract top 5 products with prices
  VERIFY: 5 products extracted ✓

Done: Return products
```

### Error Recovery

When navigation fails, WebAgent uses recovery strategies:

```
1. Expected state not met?
   → Try alternate action (different element with similar purpose)

2. Error page detected?
   → Try Google site-specific search: site:bestbuy.com laptop nvidia gpu

3. Stuck (same element clicked twice)?
   → Backtrack to previous page, try different path

4. All recovery failed?
   → Create intervention for human
```

---

## Integration with Research

WebAgent is called from the research orchestrator for Phase 2 vendor extraction:

```python
async def visit_vendor(self, url: str, query: str, requirements: dict) -> List[Product]:
    """Visit a vendor and extract products."""
    agent = WebAgent(
        page=self.page,
        llm_url=self.llm_url,
        llm_model=self.llm_model
    )

    products = await agent.navigate(
        url=url,
        goal=f"find products matching: {requirements.get('core_product', query)}",
        original_query=query,
        max_steps=5
    )

    return products
```

**No fallbacks.** If WebAgent fails to extract products, it creates an intervention. The research orchestrator does not try alternative extraction methods.

---

## Site Knowledge

WebAgent learns what works for each domain:

```json
{
  "domain": "bestbuy.com",
  "last_updated": "2026-01-19T10:00:00Z",
  "successful_actions": [
    {
      "goal": "search for products",
      "action": "type",
      "target_text": "Search",
      "target_type": "input",
      "frequency": 5,
      "success_rate": 1.0
    },
    {
      "goal": "sort by price",
      "action": "click",
      "target_text": "Price: Low to High",
      "frequency": 3,
      "success_rate": 0.8
    }
  ],
  "failed_actions": [
    {
      "goal": "search for products",
      "action": "click",
      "target_text": "Deals",
      "reason": "Led to deals page, not search results"
    }
  ]
}
```

**Location:** `panda_system_docs/site_knowledge/{domain}.json`

---

## Configuration

```python
# apps/services/orchestrator/web_agent.py

MAX_STEPS = 5               # Maximum navigation steps per vendor
CLICK_WAIT_TIME = 2.0       # Seconds to wait after click
INTERVENTION_TIMEOUT = 120  # Seconds to wait for human intervention
PDP_VERIFICATION = True     # Require PDP visit for price verification
MAX_PRODUCTS = 10           # Maximum products to extract per vendor
```

---

## Intervention System

When WebAgent cannot proceed, it creates an intervention:

```python
@dataclass
class WebAgentIntervention:
    intervention_type: str  # "stuck" | "blocked" | "extraction_failed"
    url: str
    screenshot_path: str
    action_history: List[AgentDecision]
    last_page_understanding: PageUnderstanding
    suggested_action: str
```

**Intervention types:**

| Type | Trigger | Human Action |
|------|---------|--------------|
| `stuck` | Same element clicked 3+ times | Navigate manually |
| `blocked` | CAPTCHA, login wall detected | Solve blocker |
| `extraction_failed` | Page has products but extraction returned 0 | Verify page structure |

---

## Files

### New Files

| File | Purpose |
|------|---------|
| `apps/services/orchestrator/web_agent.py` | Unified WebAgent implementation |
| `architecture/mcp-tool-patterns/internet-research-mcp/WEB_AGENT_ARCHITECTURE.md` | This spec |

### Modified Files

| File | Change |
|------|--------|
| `apps/services/orchestrator/research_orchestrator.py` | Use WebAgent, remove fallback chains |
| `architecture/mcp-tool-patterns/internet-research-mcp/INTERNET_RESEARCH_ARCHITECTURE.md` | Reference WebAgent |

### Deprecated Files

| File | Status |
|------|--------|
| `apps/services/orchestrator/universal_agent.py` | Keep for reference, mark deprecated |
| `apps/services/orchestrator/adaptive_extractor.py` | Already deprecated |
| `apps/services/orchestrator/unified_web_extractor.py` | Already deprecated |

---

## Migration Path

### Phase 1: Create WebAgent
1. Implement `web_agent.py` with PERCEIVE-DECIDE-ACT-VERIFY loop
2. Integrate PageIntelligenceService for perception
3. Add StuckDetector
4. Add site knowledge integration

### Phase 2: Update Research Orchestrator
1. Replace vendor visit logic with WebAgent calls
2. Remove all fallback chains
3. Add intervention creation for failures

### Phase 3: Verify and Cleanup
1. Run hamster and laptop golden queries
2. Verify no fallback code paths remain
3. Deprecate old files

---

## Success Criteria

After implementation:

- [x] ONE code path for all vendor extraction (no fallbacks)
- [x] Stuck detection prevents infinite loops
- [x] Site knowledge improves over time
- [x] Failures create interventions (not silent degradation)
- [x] WebAgentResult determination distinguishes "no products found" from "extraction failed"
- [ ] Hamster query returns live animals from breeders
- [ ] Laptop query returns laptops with prices

---

## Non-Goals

- **No hardcoded selectors** - LLM decides what to click
- **No domain-specific rules** - Site knowledge is learned, not coded
- **No time-based cutoffs** - Quality gates, not time limits
- **No silent fallbacks** - Fail loudly, create interventions

---

## Related Documents

- [INTERNET_RESEARCH_ARCHITECTURE.md](./INTERNET_RESEARCH_ARCHITECTURE.md) - Overall research architecture
- [06-1-BROWSER-SYSTEM.md](../../Implementation/06-1-BROWSER-SYSTEM.md) - Phase 1 multi-source research
- [phase4-coordinator.md](../../main-system-patterns/phase4-coordinator.md) - Tool execution phase

---

**Last Updated:** 2026-01-19
