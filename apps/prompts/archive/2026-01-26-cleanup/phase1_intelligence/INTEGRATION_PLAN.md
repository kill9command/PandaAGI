# Requirements Reasoning Integration Plan

## Architecture Context

The `internet.research` MCP tool uses a two-phase architecture:
- **Phase 1:** Intelligence gathering from forums/guides (`gather_intelligence()`)
- **Phase 2:** Product extraction from vendors (`intelligent_vendor_search()`)

See: `panda_system_docs/architecture/mcp-tool-patterns/internet-research-mcp/internet-research-mcp.md`

## Current Flow (to be modified)

```
internet.research MCP
    ↓
ResearchRole.orchestrate()  [research_role.py]
    ↓
Phase 1: gather_intelligence()  [research_orchestrator.py]
    → Searches forums/guides
    → Returns: {specs_discovered, price_range, retailers_mentioned, ...}
         ↓
Phase 2: intelligent_vendor_search()  [research_orchestrator.py]
    → Google search for products
    → Visit vendor sites
    → Extract products (SmartExtractor)
    → Filter viable products (product_viability.py)
         ↓
         filter_viable_products()
             → Uses ProductRequirements (structured, hardcoded)
             → NO pet/toy distinction
             → PROBLEM: Toy hamster passes as valid
```

## New Flow

```
internet.research MCP
    ↓
ResearchRole.orchestrate()  [research_role.py]
    ↓
Phase 1: gather_intelligence()
    → Returns: {specs_discovered, price_range, retailers_mentioned, ...}
         ↓
NEW: _generate_requirements_reasoning()  ← INSERT HERE
    → Input: query + Phase 1 intelligence + user context
    → Prompt: requirements_reasoning.md
    → LLM reasons about what user actually needs
    → Output: {
        validity_criteria: {must_be: "live animal"},
        disqualifiers: {wrong_category: ["toy", "plush"]},
        search_optimization: {primary_query: "live Syrian hamster for sale"}
      }
         ↓
Phase 2: intelligent_vendor_search()
    → Uses optimized_query (from reasoning)
    → Visits vendors
    → Extracts products
         ↓
         filter_viable_products()
             → Input: requirements_reasoning document (not structured fields)
             → Prompt: viability_reasoning.md
             → LLM reasons: "Schylling Chonky Cheeks = toy, REJECT"
             → Output: Only valid products
```

## Code Changes Required

### 1. research_role.py - Add reasoning step in _execute_standard()

Location: After Phase 1 completes (line ~559), before Phase 2 begins (line ~576)

```python
# In ResearchRole class

async def _generate_requirements_reasoning(
    self,
    query: str,
    intelligence: Dict[str, Any],
    user_constraints: Dict[str, Any],
    session_id: str
) -> Dict[str, Any]:
    """
    Generate LLM-reasoned requirements from query and Phase 1 intelligence.

    This replaces the hardcoded ProductRequirements logic with LLM reasoning.
    """
    # Load prompt template
    prompt_path = Path("apps/prompts/phase1_intelligence/requirements_reasoning.md")
    prompt_template = prompt_path.read_text()

    # Build research summary from Phase 1 intelligence
    research_summary = self._format_intelligence_for_reasoning(intelligence)

    # Build user context
    context = self._format_user_context(user_constraints, session_id)

    # Fill template
    prompt = prompt_template.replace("{{query}}", query)
    prompt = prompt_template.replace("{{context}}", context)
    prompt = prompt_template.replace("{{research_summary}}", research_summary)

    # Call LLM
    response = await self._call_reasoning_llm(prompt)

    # Parse YAML from response
    parsed = self._parse_reasoning_yaml(response)

    return {
        "reasoning_document": response,
        "parsed": parsed,
        "optimized_query": parsed.get("search_optimization", {}).get("primary_query", query)
    }

def _format_intelligence_for_reasoning(self, intelligence: Dict) -> str:
    """Format Phase 1 intelligence for the reasoning prompt."""
    lines = []

    if intelligence.get("specs_discovered"):
        lines.append("**Specs discovered:**")
        for k, v in intelligence["specs_discovered"].items():
            lines.append(f"- {k}: {v}")

    if intelligence.get("price_range"):
        pr = intelligence["price_range"]
        lines.append(f"**Price range:** ${pr.get('min', '?')} - ${pr.get('max', '?')}")

    if intelligence.get("key_findings"):
        lines.append("**Key findings:**")
        for finding in intelligence["key_findings"][:5]:
            lines.append(f"- {finding}")

    if intelligence.get("forum_recommendations"):
        lines.append("**Community recommendations:**")
        for rec in intelligence["forum_recommendations"][:3]:
            lines.append(f"- {rec.get('content', '')[:200]}")

    return "\n".join(lines) if lines else "No research findings available."
```

Then modify `_execute_standard()`:

```python
async def _execute_standard(self, ...):
    # ... Phase 1 code (lines 522-559) ...
    # At this point: intelligence is either fresh (from Phase 1) or cached

    # ════════════════════════════════════════════════════════════
    # NEW: Generate requirements reasoning (INSERT AFTER LINE 575)
    # Only needed if we're going to run Phase 2 (product search)
    # ════════════════════════════════════════════════════════════
    requirements_reasoning = None
    optimized_query = query  # Default to original query

    # Only generate reasoning if Phase 2 will run (we need to filter products)
    if strategy["execute_phase2"] and query_type in ["commerce_search", "comparison"]:
        logger.info("[ResearchRole:STANDARD] Generating requirements reasoning")
        requirements_reasoning = await self._generate_requirements_reasoning(
            query=query,
            intelligence=intelligence,  # May be fresh, cached, or empty {}
            user_constraints=user_constraints,
            session_id=session_id
        )
        optimized_query = requirements_reasoning.get("optimized_query", query)
        logger.info(f"[ResearchRole:STANDARD] Optimized query: {optimized_query}")
    # ════════════════════════════════════════════════════════════

    # Phase 2: Search products/info (if needed)
    phase2_result = None
    if strategy["execute_phase2"]:
        if is_commerce_query:
            phase2_result = await research_orchestrator.intelligent_vendor_search(
                query=optimized_query,  # USE OPTIMIZED QUERY
                intelligence=intelligence or {},
                requirements_reasoning=requirements_reasoning,  # PASS REASONING (may be None for non-commerce)
                max_vendors=min_vendors,
                ...
            )
        else:
            # Non-commerce query - use standard Phase 2 without reasoning
            phase2_result = await research_orchestrator.search_products(
                query=query,  # Original query (no optimization needed)
                ...
            )
```

**Key Logic:**
- Requirements reasoning ONLY runs if Phase 2 will execute AND it's a commerce query
- For `phase1_only` (informational): Skip reasoning entirely
- For `phase2_only` (cached): Use cached intelligence for reasoning
- For non-commerce Phase 2: Skip reasoning (no product filtering needed)

### 2. research_orchestrator.py - Pass reasoning to viability filter

Location: `intelligent_vendor_search()` function

```python
async def intelligent_vendor_search(
    query: str,
    intelligence: Dict[str, Any],
    requirements_reasoning: Dict[str, Any] = None,  # NEW PARAMETER
    max_vendors: int = 3,
    ...
) -> Dict[str, Any]:
    """
    Intelligent multi-vendor product search.

    Args:
        requirements_reasoning: LLM-generated reasoning about validity criteria
                               and disqualifiers (from research_role.py)
    """
    # ... existing search and extraction code ...

    # When filtering products, pass the reasoning
    if requirements_reasoning:
        viable_result = await filter_viable_products_with_reasoning(
            products=extracted_products,
            requirements_reasoning=requirements_reasoning["reasoning_document"],
            query=query
        )
    else:
        # Fallback to old behavior
        viable_result = await filter_viable_products(
            products=extracted_products,
            requirements=requirements,  # Old ProductRequirements
            query=query
        )
```

### 3. product_viability.py - New reasoning-based filter

Add new function alongside existing `filter_viable_products()`:

```python
async def filter_viable_products_with_reasoning(
    products: List[Dict[str, Any]],
    requirements_reasoning: str,  # Full YAML reasoning document
    query: str,
    max_products: int = 4
) -> Dict[str, Any]:
    """
    Filter products using LLM reasoning chain.

    This is the new approach that uses the reasoning document
    instead of structured ProductRequirements fields.
    """
    if not products:
        return {"viable_products": [], "rejected": [], "stats": {...}}

    # Load viability reasoning prompt
    prompt_path = Path("apps/prompts/phase2_results/viability_reasoning.md")
    prompt_template = prompt_path.read_text()

    # Format products for evaluation
    products_text = _format_products_for_evaluation(products)

    # Build full prompt
    prompt = f"""{prompt_template}

---

## Requirements Reasoning (from Phase 1)

{requirements_reasoning}

---

## Products to Evaluate

{products_text}

---

Now evaluate each product against the requirements reasoning above.
"""

    # Call LLM
    response = await _call_viability_llm(prompt)

    # Parse evaluations
    evaluations = _parse_viability_response(response)

    # Separate by decision
    viable = []
    rejected = []
    uncertain = []

    for eval_item in evaluations:
        product_idx = eval_item.get("product_index", 0) - 1
        if 0 <= product_idx < len(products):
            product = products[product_idx].copy()
            product["viability_reasoning"] = eval_item.get("reasoning", {})
            product["viability_score"] = eval_item.get("score", 0.5)

            decision = eval_item.get("decision", "UNCERTAIN")
            if decision == "ACCEPT":
                viable.append(product)
            elif decision == "REJECT":
                product["rejection_reason"] = eval_item.get("rejection_reason", "")
                rejected.append(product)
            else:
                uncertain.append(product)

    return {
        "viable_products": viable[:max_products],
        "rejected": rejected,
        "uncertain": uncertain,
        "reasoning_chain": response,
        "stats": {
            "total_input": len(products),
            "viable_count": len(viable),
            "rejected_count": len(rejected),
            "uncertain_count": len(uncertain)
        }
    }
```

## Files to Modify

| File | Change |
|------|--------|
| `orchestrator/research_role.py` | Add `_generate_requirements_reasoning()` method |
| `orchestrator/research_role.py` | Modify `_execute_standard()` to call reasoning and pass optimized query |
| `orchestrator/research_orchestrator.py` | Add `requirements_reasoning` parameter to `intelligent_vendor_search()` |
| `orchestrator/product_viability.py` | Add `filter_viable_products_with_reasoning()` function |

## Backwards Compatibility

- Keep existing `filter_viable_products()` function
- Keep existing `ProductRequirements` class
- New reasoning path is used only when `requirements_reasoning` is provided
- Old path still works for callers that don't pass reasoning

## Skip Scenario Handling

### Scenario 1: Skip Phase 1 (cached intelligence exists)
- ✅ Use cached intelligence for requirements reasoning
- Flow continues normally

### Scenario 2: Skip Phase 2 (informational query)
- ✅ Skip requirements reasoning entirely (no products to filter)
- Return Phase 1 intelligence only

### Scenario 3: Skip Phase 1 + No Cached Intelligence
- ⚠️ Fallback: Run requirements reasoning with query-only context
- LLM must reason from query alone (no research findings)
- Add this to `_generate_requirements_reasoning()`:

```python
async def _generate_requirements_reasoning(self, query, intelligence, ...):
    # Format research summary
    if intelligence and any(intelligence.values()):
        research_summary = self._format_intelligence_for_reasoning(intelligence)
    else:
        # FALLBACK: No intelligence available
        research_summary = """No research findings available.

Reason based on the query alone. Use your knowledge to determine:
- What type of product the user likely wants
- Common disqualifiers for this product category
- Reasonable price expectations
- Appropriate search terms"""

    # ... rest of function
```

### Scenario 4: Never Run Phase 1 or Phase 2
- This shouldn't happen (strategy always picks at least one)
- If it does, return empty results gracefully

## Testing

After implementation, test with:
```bash
# Test 1: Pet query - should reject toys
python scripts/test_research_role_e2e.py --query "Find me a Syrian hamster for sale"
# Expected: Rejects "Schylling Chonky Cheeks Hamster" as toy

# Test 2: Electronics query - should reject accessories
python scripts/test_research_role_e2e.py --query "Budget gaming laptop nvidia"
# Expected: Rejects laptop bags, stands, skins

# Test 3: Accessory query - should reject main product
python scripts/test_research_role_e2e.py --query "Syrian hamster starter kit"
# Expected: Returns cages/supplies, rejects live hamsters
```
