# 06-1 - Browser System: Phase 1 Multi-Source Research

**Created:** 2026-01-07
**Status:** Proposed (Partially Superseded)
**Priority:** HIGH

> **Note (2026-01-19):** The Phase 2 navigation and extraction sections of this document have been superseded by the unified **WebAgent** architecture.
>
> See: `architecture/mcp-tool-patterns/internet-research-mcp/WEB_AGENT_ARCHITECTURE.md`
>
> **Key changes:**
> - Solutions 1-12 (fallbacks, recovery strategies) are replaced by ONE unified system
> - No more fallback chains - failures create interventions
> - StuckDetector prevents navigation loops
>
> The **Phase 1 Multi-Source Research** sections of this document remain current.

---

## Overview

Phase 1 must handle general informational research, not just forum discovery. This document extends the Phase 1 intelligence step to generate high-quality queries, find diverse sources, and produce an evidence ledger that supports strong synthesis when Phase 2 is not required.

This is a companion to `architecture/Implementation/06-BROWSER-SYSTEM.md` and aligns with `architecture/mcp-tool-patterns/internet-research-mcp/INTERNET_RESEARCH_ARCHITECTURE.md`.

---

## Goals

- Make Phase 1 useful for informational queries and mixed queries.
- Generate queries that target multiple evidence types without hardcoded domain rules.
- Use SourceQualityScorer to rank and select sources.
- Produce an evidence ledger with citations and confidence.
- Support Phase 2 by extracting vendors, specs, and constraints when relevant.

---

## Non-Goals

- No hardcoded allowlists or blocklists of domains.
- No site-specific navigation rules.
- No time-based cutoffs that return partial results.

---

## Phase Selection (High-Level)

Phase selection is handled by the strategy selector:

- Informational intent -> Phase 1 only.
- Commerce intent + cached intelligence -> Phase 2 only.
- Commerce intent + no cache -> Phase 1 + Phase 2.

Phase 1 must remain strong enough that informational queries can be answered without Phase 2.

---

## Process Refinement (Phase 1 -> Requirements -> Phase 2)

- Phase 1 output includes vendor candidates with evidence, spec hints, price bands, and terminology, each with source URL and confidence.
- Requirements Reasoning remains a distinct LLM step that turns Phase 1 + `original_query` into validity criteria, disqualifiers, and optimized search terms.
- Phase 2 vendor selection comes from the union of Phase 1 recommendations and fresh search results, then LLM-ranked for relevance and coverage.
- PDP verification is mandatory for price, specs, and availability before synthesis.
- Completion is quality-based: enough PDP-verified matches across multiple vendors or a clear gap that requires clarification.
- ResearchLogger captures decision rationale and evidence so prompts can be tuned without hardcoded rules.

---

## Phase 1 Query Planning

### Inputs

- `original_query` (unsanitized)
- `goal` (user intent and task objective)
- `cached_intelligence_available`
- Session context (if available)

### Outputs (Query Plan)

The LLM creates a small query plan with labeled purposes and coverage targets.

```json
{
  "coverage_targets": [
    "definition_or_basics",
    "authoritative_guidance",
    "expert_analysis",
    "practical_experience",
    "recent_updates"
  ],
  "queries": [
    {
      "query": "topic official guidance best practices",
      "source_type": "official",
      "purpose": "Authoritative guidance",
      "coverage_target": "authoritative_guidance"
    },
    {
      "query": "topic expert review analysis",
      "source_type": "expert_review",
      "purpose": "Independent analysis",
      "coverage_target": "expert_analysis"
    },
    {
      "query": "topic forum discussion 2026",
      "source_type": "forum",
      "purpose": "Real-world experiences",
      "coverage_target": "practical_experience"
    }
  ],
  "refinement_rules": [
    "If any coverage target has no high-quality source, generate a follow-up query."
  ]
}
```

Notes:
- Coverage targets are LLM-defined based on the query.
- Keep queries short and general. Avoid domain constraints.
- Always include the original query in the prompt to preserve user priorities.

---

## Source Types and Scoring

Use SourceQualityScorer to classify and score each source. The LLM should aim for coverage across multiple source types where relevant.

Source types include:
- official
- expert_review
- forum
- vendor
- news
- video
- social
- unknown

No hardcoded domain rules. Low-quality sources are down-ranked, not excluded.

---

## Phase 1 Execution Flow

1. Build query plan (LLM).
2. Execute searches via BrowserSystem.
3. Score sources with SourceQualityScorer.
4. Select top sources per coverage target.
5. Extract claims and evidence.
6. Check coverage and confidence.
7. If coverage missing or confidence low, refine queries and repeat.

---

## Evidence Ledger

Phase 1 must produce a structured evidence ledger for synthesis.

```yaml
evidence_ledger:
  - claim: "X is recommended for Y because Z"
    source_type: "official"
    url: "https://example.com/..."
    quote: "..."
    confidence: 0.87
  - claim: "Users report A and B issues"
    source_type: "forum"
    url: "https://example.com/..."
    quote: "..."
    confidence: 0.71
```

---

## Phase 1 Output Contract

```json
{
  "intelligence": {
    "key_findings": ["..."],
    "specs_discovered": {"...": "..."},
    "spec_hints": ["..."],
    "price_range": {"min": 0, "max": 0},
    "price_bands": [{"min": 0, "max": 0, "currency": "USD"}],
    "terminology": ["..."],
    "vendors_mentioned": ["..."],
    "vendor_candidates": [
      {
        "vendor": "...",
        "evidence": "...",
        "source_url": "...",
        "confidence": 0.82
      }
    ],
    "coverage": {
      "targets": ["..."],
      "missing": ["..."]
    }
  },
  "sources": [
    {
      "url": "...",
      "title": "...",
      "source_type": "expert_review",
      "quality_score": 0.82,
      "confidence": 0.86
    }
  ],
  "evidence_ledger": [
    {
      "claim": "...",
      "url": "...",
      "source_type": "official",
      "confidence": 0.9
    }
  ]
}
```

---

## Requirements Reasoning (Between Phase 1 and Phase 2)

Requirements Reasoning is a separate LLM step that transforms Phase 1 intelligence and the `original_query` into product validity criteria, disqualifiers, and optimized search terms.

Inputs:
- `original_query`
- Phase 1 intelligence
- Evidence ledger

Outputs:
- `validity_criteria` (must-have constraints)
- `disqualifiers` (exclusions)
- `search_optimization` (query terms for Phase 2)

---

## Phase 2 Vendor Selection and Verification

- Build the vendor candidate pool from Phase 1 vendor candidates plus fresh search results.
- Let the LLM rank vendors for relevance and coverage using the evidence ledger.
- Always verify product price/specs/availability on PDPs before returning results.
- Finish when enough PDP-verified matches exist across multiple vendors, or request clarification when gaps remain.

---

## Quality Tightening (Search and Results)

This section addresses poor vendor matching, weak source quality, and empty extractions.

### Query and Source Quality

- Expand Phase 1 queries to cover multiple evidence types (official, expert review, community, vendor listings).
- Include a vendor-focused query variant for commerce intent (e.g., "for sale", "buy", "retailer").
- Use SourceQualityScorer to down-rank thin or off-topic sources instead of excluding by domain.
- If coverage targets remain unmet, generate follow-up queries rather than stopping early.

### Vendor and URL Validation

- Validate that a vendor candidate resolves to a vendor site and a relevant product listing context.
- Treat mismatches (editorial pages, review articles, aggregates) as non-vendor evidence.
- Prefer direct vendor listings when Phase 2 requires extraction.

### Page-Type Verification and Recovery

- If a page is classified as "listing" but extraction returns 0 products, treat it as a failure signal.
- Replan to find site search, category pages, or alternate listings before abandoning the vendor.
- Do not accept listing classifications without extraction success.

### Quality Completion Gate

- End Phase 2 only when there are enough PDP-verified products across multiple vendors.
- If the gate is not met, either expand vendor discovery or request clarification.

---

## Decision Support (LLM Guidance)

- Pass `original_query` unchanged into every decision step (strategy, requirements, vendor selection, extraction, ranking).
- Include a compact evidence ledger (top findings + URLs + quotes) in prompts to ground decisions.
- Require structured outputs with reasoning, confidence, and explicit missing-info signals.
- Keep must-have and disqualifier constraints explicit and enforce per-product compliance checks.
- Cache Phase 1 intelligence for 24 hours but always do fresh Phase 2 extraction for commerce queries.
- If decisions are off, improve prompts and context rather than adding hardcoded rules.

---

## Integration Notes

- Query planning and coverage evaluation are LLM steps (MIND role).
- BrowserSystem executes queries and page extraction.
- Phase 1 remains responsible for intelligence even when Phase 2 is not executed.
- Phase 2 must receive Phase 1 insights (vendors, specs, constraints) plus the original query.

---

## Quality Gates (LLM-Driven)

Phase 1 can finish when:
- Each coverage target has at least one high-quality source, or
- The LLM reports that the remaining gap cannot be satisfied by available sources.

Never use a time-based cutoff to end research.

---

## Logging

Log the following with ResearchLogger:
- Query plan with coverage targets.
- Search queries executed.
- Source types selected and quality scores.
- Coverage gaps and refinements.
- Decision rationale (why sources or vendors were selected).
- Evidence ledger summaries used in selection and ranking.

---

## Phase 2 Navigation and Extraction Fixes

This section addresses issues discovered in production where Phase 2 fails to extract products from vendor sites despite Phase 1 gathering excellent intelligence.

### Problem Analysis

Observed failure pattern:
1. Phase 1 visits article sites (hothardware, propelrc) and extracts accurate price/product data
2. Phase 2 visits vendor homepages (amazon, bestbuy, walmart)
3. MIND correctly decides to search
4. Search URL returns error page ("We're sorry, something went wrong")
5. Error page has content > 300 chars, so navigation is marked "successful"
6. LLM extraction returns 0 products
7. System moves to next vendor, repeats failure

Root causes:
- Search URL patterns don't work for all vendors
- Error page detection is missing
- Recovery only triggers on "listing" pages, not navigation failures
- Article sites get included as vendors
- Phase 1 product URLs not extracted and passed to Phase 2

---

### Solution 1: Extract Product URLs in Phase 1

**Problem:** Phase 1 visits articles that link directly to vendor product pages, but only extracts text evidence, not URLs.

**Solution:** During Phase 1 evidence extraction, also extract product URLs from articles.

**Role:** MIND (temp=0.5) - This is reasoning/extraction, part of Phase 1 intelligence gathering.

**Extended Evidence Ledger Schema:**
```json
{
  "evidence_ledger": [
    {
      "claim": "HP Omen with RTX 5060 is $1,129.99 at Best Buy",
      "source_type": "expert_review",
      "url": "https://hothardware.com/article",
      "quote": "...",
      "confidence": 0.87,
      "product_urls": [
        {
          "vendor": "bestbuy",
          "url": "https://www.bestbuy.com/site/hp-omen-xxx/123456",
          "context": "linked in article"
        }
      ]
    }
  ]
}
```

**Updated extraction prompt (add to existing):**
```
ORIGINAL QUERY: {original_query}

... existing extraction instructions ...

ADDITIONAL: Extract any direct product URLs linked in the content.
For each product mentioned with a price, look for:
- Direct links to vendor product pages (bestbuy.com/site/..., amazon.com/dp/...)
- Affiliate links that resolve to vendor pages
- "Buy now" or "Check price" links

Return product_urls array with: vendor name, full URL, context of mention.
```

**Data flow (Document IO alignment):**
1. Phase 1 extracts evidence with product_urls into evidence_ledger
2. Evidence ledger stored in Phase 1 output (flows to §4 via toolresults.md)
3. Phase 2 reads product_urls from Phase 1 output
4. Phase 2 visits these URLs directly as high-priority verification targets

**Why this works:** Articles already link to vendor pages. Extracting these URLs gives Phase 2 direct access instead of hoping homepage navigation works.

---

### Solution 2: Error Page Detection

**Problem:** Search navigation returns error pages but marks them as "success" because content > 300 chars.

**Solution:** Add LLM-based error page detection after navigation.

**Role:** REFLEX (temp=0.3) - This is a classification task.

```python
async def _detect_error_page(self, page_data: dict, vendor: str, original_query: str) -> dict:
    """Detect if page is an error/blocked page.

    Uses REFLEX role (temp=0.3) for fast binary classification.
    Must receive original_query per architecture context discipline.

    Returns:
        {"is_error": bool, "error_type": str, "reasoning": str}
    """
```

**Prompt structure (LLM-detected, not hardcoded):**
```
ORIGINAL QUERY: {original_query}
VENDOR: {vendor}
PAGE TITLE: {title}
PAGE CONTENT (first 500 chars): {content[:500]}

Is this an error page, blocked page, or valid product page?

Error indicators to look for:
- Error messages ("sorry", "not found", "oops", "went wrong")
- CAPTCHA or bot detection
- Login/access walls
- No product-related content

Return: {"is_error": true/false, "error_type": "error|blocked|captcha|valid", "reasoning": "..."}
```

**Implementation:**
1. After navigation "succeeds" (content > 300 chars), call REFLEX for error detection
2. If `is_error == true`, trigger recovery instead of extraction
3. Log error type to ResearchLogger for debugging

---

### Solution 3: Expanded Recovery Triggers

**Problem:** Recovery only triggers when `page_type == "listing" and not products`. But failures occur at multiple stages:
- Homepage → search → error page
- Navigation → wrong page type
- Listing → 0 products

**Solution:** Trigger recovery for any extraction failure, not just listing+0.

```python
# Current (too narrow):
if page_type == "listing" and not products:
    attempt_recovery()

# Proposed (comprehensive):
should_recover = (
    (page_type == "listing" and not products) or  # Original case
    (navigation_failed) or                         # Search/click failed
    (is_error_page) or                            # Error page detected
    (page_type in ["homepage", "navigation"] and  # Couldn't reach products
     navigation_attempts >= 2)
)
if should_recover:
    attempt_recovery()
```

**Recovery strategy order:**
1. Try direct product URLs from Phase 1 evidence (Solution 1)
2. Try Google site-specific search: `site:bestbuy.com laptop nvidia gpu`
3. Try common search URL patterns
4. Try category page patterns
5. Mark vendor as failed, move to next

---

### Solution 4: LLM-Based Vendor Validation

**Problem:** Article sites (geeky-gadgets, propelrc) score 0.5 and get included as vendors.

**Solution:** Add LLM validation step before adding to vendor pool.

**Role:** REFLEX (temp=0.3) - This is a classification task.

```python
async def _validate_vendor_candidate(self, candidate: dict, original_query: str) -> dict:
    """Validate if a candidate is actually a vendor.

    Uses REFLEX role (temp=0.3) for fast classification.
    Must receive original_query per architecture context discipline.

    Returns:
        {"is_vendor": bool, "vendor_type": str, "confidence": float, "reasoning": str}
    """
```

**Prompt:**
```
ORIGINAL QUERY: {original_query}

Given this URL and context, determine if this is an actual vendor/retailer that sells products directly.

URL: {url}
Title: {title}
Evidence: {evidence}

Types:
- direct_vendor: Sells products directly (amazon, bestbuy, newegg)
- marketplace: Platform for sellers (ebay, etsy)
- manufacturer: Makes and sells own products (apple, dell)
- article_site: Reviews/news, doesn't sell (propelrc, hothardware)
- aggregator: Price comparison, links elsewhere (google shopping)

Return: {"is_vendor": true/false, "vendor_type": "...", "confidence": 0.0-1.0, "reasoning": "..."}
```

**Implementation:**
1. Before adding to vendor pool, call REFLEX for vendor validation
2. Only include candidates where `is_vendor == true`
3. Article sites become evidence sources, not vendor targets
4. Log classification to ResearchLogger for prompt tuning

---

### Solution 5: Google Site-Specific Search Fallback

**Problem:** Vendor search URLs don't work reliably (different patterns, anti-bot).

**Solution:** Use Google site-specific search as reliable fallback.

```python
# When direct vendor search fails:
google_query = f"site:{vendor}.com {product_query}"
results = await browser.search(google_query, max_results=5)

# Results are actual vendor product pages, not homepage
for result in results:
    if vendor in result["url"]:
        # Visit this URL directly - it's already a product page
        page_data = await extract(result["url"])
```

**Why this works:**
- Google indexes vendor product pages
- `site:bestbuy.com laptop nvidia rtx` returns Best Buy product listing pages
- Avoids homepage navigation entirely
- Works regardless of vendor's internal search implementation

**Implementation:**
1. Add to recovery strategy as step 2 (after Phase 1 URLs)
2. Use browser.search with site: prefix
3. Filter results to only vendor domain
4. Visit top 3 results directly

---

### Solution 6: Phase 1 Evidence Trust for High-Confidence Claims

**Problem:** Phase 1 finds accurate prices from authoritative sources, but validation rejects them because Phase 2 can't verify on vendor sites.

**Solution:** Modify evidence presentation to distinguish verification status, enabling Validation (Phase 6) to make informed decisions.

**Role alignment:**
- Phase 4 (Coordinator): Tracks verification status per finding
- Phase 5 (Synthesis/VOICE): Presents findings with appropriate caveats
- Phase 6 (Validation/MIND): Decides APPROVE with caveats vs RETRY

**Current flow (problematic):**
```
Phase 1: "HP Omen is $1,129.99 at Best Buy" (from hothardware.com)
Phase 2: Visits bestbuy.com → fails → 0 products
Phase 5: Uses Phase 1 data without qualification
Phase 6: Rejects because "claims not supported by vendor verification"
Result: No answer despite having correct information
```

**Proposed flow (validation-integrated):**
```
Phase 1: "HP Omen is $1,129.99 at Best Buy" (from hothardware.com, confidence 0.87)
Phase 2: Visits bestbuy.com → fails → 0 products
Phase 2: Returns findings with verification_status: "phase1_only"
Phase 5: Uses Phase 1 data WITH caveat: "According to [source], price is X"
Phase 6: Evaluates: high-confidence Phase 1 + transparent sourcing → APPROVE
Result: Useful answer with appropriate transparency
```

**toolresults.md schema extension:**
```json
{
  "findings": [
    {
      "product": "HP Omen RTX 5060",
      "price": "$1,129.99",
      "vendor": "bestbuy",
      "verification_status": "phase1_only",
      "phase1_source": "hothardware.com",
      "phase1_confidence": 0.87,
      "phase2_attempted": true,
      "phase2_result": "navigation_failed"
    }
  ]
}
```

**Synthesis prompt update (VOICE role):**
```
When presenting findings with verification_status: "phase1_only":
- Include source attribution: "According to [source]..."
- Add verification caveat: "Price may vary; verify on vendor site"
- Do NOT present as definitively verified

When presenting findings with verification_status: "pdp_verified":
- Present confidently with vendor attribution
```

**Validation prompt update (MIND role):**
```
For findings with verification_status: "phase1_only":
- APPROVE if: phase1_confidence >= 0.8 AND source is authoritative AND caveat included
- REVISE if: caveat missing or source not attributed
- RETRY only if: no usable findings at all

Do NOT reject solely because Phase 2 verification failed if Phase 1 has high-confidence evidence from authoritative sources.
```

**Implementation:**
1. Phase 2 returns verification_status per finding
2. Synthesis uses status to apply appropriate caveats
3. Validation evaluates considering verification status
4. Maintains existing APPROVE/REVISE/RETRY loop

**Architecture alignment:**
- Integrates with existing Phase 6 validation loop
- Uses VOICE for synthesis, MIND for validation (correct roles)
- Provides transparency via source attribution
- No hardcoded rules - LLM decides based on confidence and sourcing

---

### Implementation Priority

| Priority | Solution | Impact | Effort |
|----------|----------|--------|--------|
| P0 | Solution 2: Error Page Detection | Fixes false "success" | Low |
| P0 | Solution 3: Expanded Recovery | Catches more failures | Low |
| P1 | Solution 5: Google Site Search | Reliable fallback | Medium |
| P1 | Solution 4: Vendor Validation | Cleaner vendor pool | Medium |
| P2 | Solution 1: Extract Product URLs | Direct PDP access | Medium |
| P2 | Solution 6: Phase 1 Trust | Graceful degradation | Low |

---

### Success Metrics

After implementing these solutions:
- Phase 2 should extract products from >50% of vendor visits (vs 0% currently)
- Error pages should be detected and trigger recovery
- Article sites should not appear in vendor pool
- System should return useful answers even when vendor navigation fails

---

### Non-Goals

These solutions maintain architecture principles:
- No hardcoded vendor-specific URL patterns
- No domain blocklists/allowlists
- All decisions remain LLM-driven
- No time-based cutoffs

---

## LLM Product Extraction Fixes (Solutions 7-12)

This section addresses the core extraction failure: **LLM returns empty arrays despite valid pages with prices.**

### Problem Analysis

From logs:
```
[21:37:46] Extraction content for amazon (4000 chars)
    has_dollar_sign: true
    has_price_patterns: true
[21:37:47] LLM extraction response for amazon
    response_preview: "[]"
```

The page has prices but extraction fails. Root causes:

1. **Content Truncation Issue**: First 4000 chars are header/navigation text
   ```
   "Skip to Main content About this item About this item Buying options..."
   ```
   Product listings with prices are below the 4000 char cutoff.

2. **Category vs Listing Pages**: Navigation lands on category pages (product types) not listing pages (products with prices)
   ```
   razer: /pc → shows "Laptops, Mice, Keyboards" categories, no prices
   acer: /laptops → shows "Gaming, OLED, Chromebooks" categories, no prices
   ```

3. **Single-Step Navigation**: Current approach does one click and stops
   - Homepage → Category page (no prices)
   - Should be: Homepage → Category → Product listing (has prices)

4. **DOM Text Extraction Order**: `innerText` returns text in DOM order
   - Header, navigation, sidebars come first
   - Product grid with prices is further down

5. **Missing Structured Data**: Many sites have JSON-LD product data in `<script>` tags
   - Current extraction ignores this
   - JSON-LD is more reliable than parsing visible text

---

### Solution 7: Smart Content Windowing

**Problem:** First 4000 chars are navigation text, not product listings.

**Solution:** Find the content section with prices and extract from there.

**Role:** N/A (procedural, no LLM)

```python
def _extract_price_relevant_content(
    self,
    full_text: str,
    max_chars: int = 6000,
) -> str:
    """Find and extract content window containing prices.

    From architecture doc (06-1-BROWSER-SYSTEM.md):
        > First 4000 chars are header/navigation text.
        > Product listings with prices are below the cutoff.
        > Find the content section with prices and extract from there.

    Strategy:
    1. Find first occurrence of price pattern ($XX.XX)
    2. Start extraction 500 chars before first price
    3. This captures product context around prices

    Args:
        full_text: Full page text content
        max_chars: Maximum characters to return

    Returns:
        Content window likely containing product listings
    """
    import re

    # Find price patterns
    price_pattern = r'\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?'
    matches = list(re.finditer(price_pattern, full_text))

    if not matches:
        # No prices found, return from start
        return full_text[:max_chars]

    # Start 500 chars before first price
    first_price_pos = matches[0].start()
    start_pos = max(0, first_price_pos - 500)

    # Extract window around prices
    content_window = full_text[start_pos:start_pos + max_chars]

    return content_window
```

**Implementation:**
1. In `_extract_products_from_page`, replace:
   ```python
   page_content = page_data.get("text_content", "")[:4000]
   ```
   With:
   ```python
   full_text = page_data.get("text_content", "")
   page_content = self._extract_price_relevant_content(full_text, max_chars=6000)
   ```

2. If no prices found in text_content, check OCR items for prices

---

### Solution 8: Multi-Step Navigation with Price Detection

**Problem:** Single navigation step lands on category pages without prices.

**Solution:** Continue navigating until prices are visible or max depth reached.

**Role:** MIND (temp=0.5) for navigation decisions

```python
async def _navigate_to_products_deep(
    self,
    page_extractor,
    page_data: dict,
    vendor: str,
    query: str,
    requirements: dict,
    max_depth: int = 3,
) -> dict:
    """Navigate through category hierarchy until product listings found.

    From architecture doc (06-1-BROWSER-SYSTEM.md):
        > Navigation lands on category pages (product types) not listing pages.
        > Continue navigating until prices are visible or max depth reached.

    Strategy:
    1. Check if current page has prices
    2. If not, ask MIND to select next navigation action
    3. Repeat until prices found or max_depth reached

    Returns:
        {"success": bool, "page_data": dict, "depth": int, "has_prices": bool}
    """
    current_page = page_data
    depth = 0

    while depth < max_depth:
        # Check if current page has prices
        text_content = current_page.get("text_content", "")
        has_prices = bool(re.search(r'\$\d+(?:\.\d{2})?', text_content))

        if has_prices:
            return {
                "success": True,
                "page_data": current_page,
                "depth": depth,
                "has_prices": True,
            }

        depth += 1

        # Ask MIND for next navigation action
        nav_result = await self._navigate_to_products(
            page_extractor, current_page, vendor, query, requirements
        )

        if not nav_result.get("success"):
            break

        current_page = nav_result.get("page_data", current_page)

        # Check for error page
        error_check = await self._detect_error_page(current_page, vendor, query)
        if error_check.get("is_error"):
            break

    return {
        "success": False,
        "page_data": current_page,
        "depth": depth,
        "has_prices": False,
        "reason": "Max depth reached without finding prices",
    }
```

**Implementation:**
1. Replace single `_navigate_to_products` call with `_navigate_to_products_deep`
2. Track navigation depth in logs
3. Stop when prices found or max_depth (3) reached

---

### Solution 9: JSON-LD Structured Data Extraction

**Problem:** Text parsing is unreliable. Sites have structured product data in JSON-LD.

**Solution:** Extract JSON-LD first, fall back to text extraction.

**Role:** N/A (procedural extraction)

```python
def _extract_jsonld_products(
    self,
    html_content: str,
    vendor: str,
) -> list[dict]:
    """Extract products from JSON-LD structured data.

    From architecture doc (06-1-BROWSER-SYSTEM.md):
        > Many sites have JSON-LD product data in <script> tags.
        > JSON-LD is more reliable than parsing visible text.

    Looks for:
    - <script type="application/ld+json">
    - @type: Product, Offer, ItemList

    Args:
        html_content: Full HTML content
        vendor: Vendor name for logging

    Returns:
        List of product dicts with name, price, url, availability
    """
    import json
    import re

    products = []

    # Find all JSON-LD script tags
    jsonld_pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    matches = re.findall(jsonld_pattern, html_content, re.DOTALL | re.IGNORECASE)

    for match in matches:
        try:
            data = json.loads(match)

            # Handle single product
            if isinstance(data, dict):
                if data.get("@type") == "Product":
                    product = self._parse_jsonld_product(data)
                    if product:
                        products.append(product)

                # Handle product list
                elif data.get("@type") == "ItemList":
                    for item in data.get("itemListElement", []):
                        if item.get("@type") == "Product" or item.get("item", {}).get("@type") == "Product":
                            product = self._parse_jsonld_product(item.get("item", item))
                            if product:
                                products.append(product)

            # Handle array of items
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Product":
                        product = self._parse_jsonld_product(item)
                        if product:
                            products.append(product)

        except json.JSONDecodeError:
            continue

    return products

def _parse_jsonld_product(self, data: dict) -> Optional[dict]:
    """Parse a JSON-LD Product object."""
    name = data.get("name", "")
    if not name:
        return None

    # Extract price from offers
    offers = data.get("offers", {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}

    price = offers.get("price") or offers.get("lowPrice")
    currency = offers.get("priceCurrency", "USD")
    availability = offers.get("availability", "")

    # Normalize availability
    in_stock = None
    if "InStock" in availability:
        in_stock = True
    elif "OutOfStock" in availability:
        in_stock = False

    return {
        "name": name,
        "price": f"${price}" if price else None,
        "url": data.get("url", ""),
        "in_stock": in_stock,
        "image": data.get("image", ""),
        "source": "jsonld",
    }
```

**Implementation:**
1. In `_extract_from_vendor`, try JSON-LD extraction first
2. If JSON-LD returns products, use those
3. Fall back to LLM text extraction if JSON-LD empty

---

### Solution 10: Search-First Navigation Strategy

**Problem:** Homepage → Click navigation often fails or lands on category pages.

**Solution:** Go directly to search URL, skip homepage entirely.

**Role:** N/A (procedural)

```python
async def _navigate_via_search(
    self,
    page_extractor,
    vendor: str,
    query: str,
    requirements: dict,
) -> dict:
    """Navigate directly to search results, skipping homepage.

    From architecture doc (06-1-BROWSER-SYSTEM.md):
        > Homepage → Click navigation often fails.
        > Go directly to search URL, skip homepage entirely.

    Strategy:
    1. Build search URL with vendor domain
    2. Navigate directly to search results
    3. More likely to land on listing page with prices

    Returns:
        {"success": bool, "page_data": dict, "method": str}
    """
    from urllib.parse import quote_plus

    search_query = requirements.get("core_product", query)
    base_url = f"https://www.{vendor}.com"

    # Common search URL patterns (tried in order)
    search_patterns = [
        f"{base_url}/s?k={quote_plus(search_query)}",  # Amazon
        f"{base_url}/search?q={quote_plus(search_query)}",  # Generic
        f"{base_url}/search?query={quote_plus(search_query)}",  # Alt generic
        f"{base_url}/site/searchpage.jsp?st={quote_plus(search_query)}",  # Best Buy
        f"{base_url}/search/{quote_plus(search_query)}",  # Path-based
    ]

    for search_url in search_patterns:
        try:
            page_data = await page_extractor.extract_structured_data(search_url)

            if not page_data:
                continue

            # Check if this is an error page
            error_check = await self._detect_error_page(page_data, vendor, query)
            if error_check.get("is_error"):
                continue

            # Check if page has prices (good sign it's a listing)
            text_content = page_data.get("text_content", "")
            has_prices = bool(re.search(r'\$\d+(?:\.\d{2})?', text_content))

            if has_prices or len(text_content) > 1000:
                return {
                    "success": True,
                    "page_data": page_data,
                    "method": "search_url",
                    "url": search_url,
                }

        except Exception:
            continue

    return {"success": False, "reason": "All search URL patterns failed"}
```

**Implementation:**
1. Before homepage navigation, try `_navigate_via_search`
2. If search works, skip homepage navigation entirely
3. Only fall back to homepage if search fails

---

### Solution 11: OCR-Augmented Extraction

**Problem:** DOM text extraction misses dynamically loaded content.

**Solution:** Use OCR items to augment/verify DOM extraction.

**Role:** N/A (procedural)

```python
def _augment_with_ocr(
    self,
    page_data: dict,
    vendor: str,
) -> str:
    """Augment DOM text with OCR results for better coverage.

    From architecture doc (06-1-BROWSER-SYSTEM.md):
        > DOM text extraction misses dynamically loaded content.
        > OCR captures text rendered by JavaScript.

    Strategy:
    1. Get OCR items with prices
    2. Find product-like text near prices
    3. Combine with DOM text for richer extraction

    Returns:
        Augmented text content
    """
    dom_text = page_data.get("text_content", "")
    ocr_items = page_data.get("ocr_items", [])

    if not ocr_items:
        return dom_text

    # Find OCR items with prices
    price_items = []
    for item in ocr_items:
        text = item.get("text", "")
        if re.search(r'\$\d+', text):
            price_items.append(item)

    if not price_items:
        return dom_text

    # Build OCR context around prices
    ocr_context_parts = []
    for price_item in price_items:
        y_pos = price_item.get("y", 0)

        # Find nearby OCR items (within 100px vertically)
        nearby = [
            item.get("text", "")
            for item in ocr_items
            if abs(item.get("y", 0) - y_pos) < 100
        ]

        ocr_context_parts.append(" ".join(nearby))

    ocr_context = "\n---\n".join(ocr_context_parts)

    # Combine DOM and OCR
    return f"{dom_text}\n\n=== OCR DETECTED PRODUCTS ===\n{ocr_context}"
```

**Implementation:**
1. Before extraction, call `_augment_with_ocr`
2. Pass augmented text to LLM
3. OCR context helps when DOM text is missing prices

---

### Solution 12: Improved Extraction Prompt

**Problem:** Current prompt is generic and doesn't handle e-commerce page structures.

**Solution:** Rewrite prompt with specific e-commerce patterns.

**Role:** MIND (temp=0.5)

```python
# Updated extraction prompt
prompt = f"""You are extracting product listings from an e-commerce page.

VENDOR: {vendor}
USER QUERY: {original_query}
LOOKING FOR: {core_product}
USER PRIORITY: {user_priority}

PAGE CONTENT:
{page_content}

=== EXTRACTION RULES ===

1. FIND PRODUCTS: Look for items that match "{core_product}". Each product typically has:
   - A product name/title
   - A price (e.g., $599.99, $1,299.00)
   - Optional: availability, specs, ratings

2. PRICE PATTERNS: Recognize these price formats:
   - "$1,299.99" or "$599.00"
   - "Price: $XXX" or "Now $XXX"
   - "From $XXX" or "Starting at $XXX"
   - "Sale: $XXX (was $XXX)"

3. PRODUCT NAME PATTERNS: Look for:
   - Brand + Model: "HP Omen 16", "ASUS ROG Strix G16"
   - Descriptive names: "15.6 inch Gaming Laptop with RTX 4060"
   - Near price mentions (product names usually appear near prices)

4. IGNORE:
   - Navigation links, category names
   - "Add to cart", "Learn more" buttons
   - Generic text not related to products

5. OUTPUT: Return a JSON array of products found:
[
  {{
    "name": "Exact product name from page",
    "price": "$XXX.XX",
    "url": "product URL if visible, null otherwise",
    "in_stock": true/false/null,
    "confidence": 0.0-1.0
  }}
]

If NO products with prices are found, return: []

CRITICAL: Only include items with VISIBLE PRICES. Do not guess prices.
Extract up to 5 products, prioritizing by {user_priority}.

Return ONLY the JSON array:"""
```

**Key changes:**
1. Specific price pattern guidance
2. Product name pattern examples
3. Clear instructions on what to ignore
4. Emphasis on visible prices only
5. Priority-based ordering

---

### Implementation Priority (Solutions 7-12)

| Priority | Solution | Impact | Effort |
|----------|----------|--------|--------|
| P0 | Solution 7: Smart Content Windowing | Fixes content truncation | Low |
| P0 | Solution 12: Improved Extraction Prompt | Better LLM parsing | Low |
| P1 | Solution 9: JSON-LD Extraction | Most reliable data source | Medium |
| P1 | Solution 10: Search-First Strategy | Skips broken homepage nav | Medium |
| P2 | Solution 8: Multi-Step Navigation | Reaches listing pages | Medium |
| P2 | Solution 11: OCR Augmentation | Captures dynamic content | Medium |

---

### Expected Improvements

After implementing Solutions 7-12:

| Issue | Before | After |
|-------|--------|-------|
| Content truncation | First 4000 chars (nav) | Window around prices |
| Category vs listing | Stuck on category | Multi-step to listing |
| Structured data | Ignored JSON-LD | JSON-LD first |
| Navigation failures | Homepage → fail | Search URL first |
| Dynamic content | DOM only | DOM + OCR |
| LLM parsing | Generic prompt | E-commerce specific |

---

### Architecture Alignment Summary

All solutions align with the core system architecture:

| Solution | Role | Temp | Phase | Context Discipline |
|----------|------|------|-------|-------------------|
| 1. Extract Product URLs | MIND | 0.5 | Phase 1 (intelligence) | original_query in prompt |
| 2. Error Page Detection | REFLEX | 0.3 | Phase 4 (coordinator) | original_query in prompt |
| 3. Expanded Recovery | N/A | N/A | Phase 4 (control flow) | N/A |
| 4. Vendor Validation | REFLEX | 0.3 | Phase 4 (coordinator) | original_query in prompt |
| 5. Google Site Search | N/A | N/A | Phase 4 (tool call) | N/A |
| 6. Evidence Trust | VOICE/MIND | 0.7/0.5 | Phase 5-6 | Integrates with validation loop |

**Key Architecture Principles Followed:**

1. **Role Assignment (llm-roles-reference.md):**
   - Classification tasks → REFLEX (temp=0.3)
   - Reasoning/extraction → MIND (temp=0.5)
   - User-facing output → VOICE (temp=0.7)

2. **Context Discipline (CLAUDE.md):**
   - `original_query` passed to all LLM decision calls
   - No pre-classification of user intent that loses priority signals

3. **Document IO (DOCUMENT_IO_ARCHITECTURE.md):**
   - Data flows through context.md sections and toolresults.md
   - Evidence ledger format extended, not replaced
   - Append-only during pipeline execution

4. **Quality Gates (llm-roles-reference.md):**
   - Solution 6 integrates with existing APPROVE/REVISE/RETRY loop
   - No bypassing of Phase 6 validation

5. **No Hardcoded Rules (CLAUDE.md):**
   - No domain blocklists/allowlists
   - No site-specific URL templates
   - All decisions LLM-driven with prompts, not code

6. **Logging (ResearchLogger):**
   - All decisions logged for prompt tuning
   - Error types, vendor classifications, recovery attempts tracked
