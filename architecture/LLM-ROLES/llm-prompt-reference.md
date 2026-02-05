# LLM Prompt Reference

**Status:** SPECIFICATION
**Version:** 1.0
**Updated:** 2026-01-05

Index of all LLM prompts needed for the system. Each entry describes what the prompt must accomplish.

---

## Main Pipeline Prompts

### Phase 0: Query Analyzer

| Prompt | Model | Purpose |
|--------|-------|---------|
| `query_analyzer` | REFLEX | Classify query type (general_question, specific_content, followup, new_topic). Resolve references ("that laptop" → specific product from prior turns). Output structured QueryAnalysis JSON. |

### Phase 1: Reflection

| Prompt | Model | Purpose |
|--------|-------|---------|
| `reflection` | REFLEX | Decide PROCEED or CLARIFY based on syntactic clarity. Determine if query is parseable and actionable before gathering context. Output decision with reasoning. |

### Phase 2: Context Gatherer

| Prompt | Model | Purpose |
|--------|-------|---------|
| `context_retrieval` | MIND | Given query + turn summaries + memory headers + cache headers, identify which sources are relevant. Output RetrievalPlan with relevant_turns, memory_keys, research_cache_match. |
| `context_synthesis` | MIND | Given query + loaded documents, extract and compile relevant context into structured §2 format. Include session preferences, prior turn summaries, cached research intel. |

### Phase 3: Planner

| Prompt | Model | Purpose |
|--------|-------|---------|
| `planner` | MIND | Determine routing: executor (needs tools), synthesis (can answer from context), or clarify (query ambiguous). Create STRATEGIC_PLAN with goals, approach, success criteria. On RETRY, read §7 failure feedback and create new plan avoiding prior failures. |

### Phase 4: Executor

| Prompt | Model | Purpose |
|--------|-------|---------|
| `executor` | MIND | Given strategic plan from §3 and accumulated results in §4, determine next tactical step. Output EXECUTOR_DECISION with action (COMMAND/ANALYZE/COMPLETE/BLOCKED). Issue natural language commands to Coordinator. |

### Phase 5: Coordinator

| Prompt | Model | Purpose |
|--------|-------|---------|
| `coordinator` | MIND | Translate natural language command from Executor into specific tool call. Validate against tool registry, execute MCP tool call, format results with claims into §4 and toolresults.md. |

### Phase 6: Synthesis

| Prompt | Model | Purpose |
|--------|-------|---------|
| `synthesis` | VOICE | Generate user-facing response from §0-§4 context. Ground all claims in evidence from §4. Use appropriate hedging based on confidence scores. Format with markdown. On REVISE, incorporate revision_hints from §7. |

### Phase 7: Validation

| Prompt | Model | Purpose |
|--------|-------|---------|
| `validation` | MIND | Validate response against 4 checks: claims_supported, no_hallucinations, query_addressed, coherent_format. Assign confidence score. Output decision (APPROVE/REVISE/RETRY/FAIL) with issues and hints. |

---

## Smart Summarization Prompts (NERVES Background)

| Prompt | Model | Purpose |
|--------|-------|---------|
| `key_fact_extraction` | REFLEX | Extract 5-10 key facts from content before compression. Used to verify compression preserves important information. |
| `content_compression` | NERVES | Compress content to fit token budget while preserving key information. Used when §4 or memory sections exceed limits. |
| `fact_verification` | REFLEX | Given compressed text and list of key facts, verify each fact is still derivable. Output verification score. |

---

## Internet Research MCP Prompts

### Classification & Routing

| Prompt | Model | Purpose |
|--------|-------|---------|
| `page_classifier` | REFLEX | Classify page type: listing, pdp, navigation, blocked, no_content. Fast classification from DOM/OCR text. ~300 tokens. |
| `search_engine_router` | REFLEX | Basic intent detection for search engine selection. |

### Strategy & Planning

| Prompt | Model | Purpose |
|--------|-------|---------|
| `strategy_selector` | MIND | Analyze query and cached intelligence to select research strategy: phase1_only (informational), phase2_only (commerce + cache), phase1_and_phase2 (commerce, no cache). ~2,500 tokens. |
| `requirements_reasoning` | MIND | Analyze user query to determine: core_product, implicit_requirements, user_intent, validity_criteria, disqualifiers, search_optimization. Creates context for Phase 2 filtering. ~3,500 tokens. |

### Source Evaluation

| Prompt | Model | Purpose |
|--------|-------|---------|
| `source_quality_scorer` | MIND | Score URL quality (0.0-1.0) based on source type (forum, expert_review, official, vendor), reliability history, and query context. ~1,500 tokens. |

### Navigation & Decision

| Prompt | Model | Purpose |
|--------|-------|---------|
| `navigation_decision` | MIND | Given PageDocument + goal + site_knowledge, decide next action (click, type, scroll, wait, back, extract, request_help, finish). Output LLMDecision with target_candidate_id, expected_state, reasoning. |
| `expected_state_generator` | MIND | Generate expected_state for navigation action: what page_type should result, what must_see elements should appear. |
| `state_verification` | MIND | Compare expected_state to actual PageDocument after action. Determine if action succeeded or needs replanning. |

### Extraction & Learning

| Prompt | Model | Purpose |
|--------|-------|---------|
| `schema_learner` | MIND | Analyze DOM structure to learn extraction selectors for a domain. Output selector patterns for product_container, name, price, url. ~1,500 tokens. |
| `product_extractor` | MIND | Extract structured product data from PageDocument using learned schema or generic extraction. ~2,000 tokens. |
| `viability_filter` | MIND | Filter products against validity_criteria from requirements_reasoning. Semantic matching - is this actually the product user wants? ~2,000 tokens. |
| `product_ranker` | MIND | Rank viable products by relevance to original query. Consider user priorities ("cheapest", "best", etc.) from original_query. ~3,000 tokens. |

### Vision (EYES)

| Prompt | Model | Purpose |
|--------|-------|---------|
| `page_structurer` | EYES | Convert RawPageCapture (screenshot + OCR + DOM) into structured PageDocument with semantic sections. Decide what sections exist on page, their purpose, which items belong in each. |
| `screenshot_analyzer` | EYES | Analyze screenshot for specific extraction task (prices, specs, availability). Used when DOM extraction fails or for JS-rendered content. ~2,000 tokens. |
| `captcha_detector` | EYES | Detect and classify CAPTCHA type from screenshot: CAPTCHA_RECAPTCHA, CAPTCHA_HCAPTCHA, CAPTCHA_CLOUDFLARE, LOGIN_REQUIRED, etc. |
| `visual_verifier` | EYES | Visual verification when MIND confidence < 0.7. Confirm page state matches expected state. |
| `ocr_verifier` | EYES | OCR verification for complex layouts where standard OCR may fail. |

---

## Prompt Organization

Prompts should be organized in `app/recipes/prompts/` with the following structure:

```
app/recipes/prompts/
├── pipeline/
│   ├── phase0_query_analyzer.yaml
│   ├── phase1_reflection.yaml
│   ├── phase2_context_retrieval.yaml
│   ├── phase2_context_synthesis.yaml
│   ├── phase3_planner.yaml
│   ├── phase4_executor.yaml
│   ├── phase5_coordinator.yaml
│   ├── phase6_synthesis.yaml
│   └── phase7_validation.yaml
├── smart_summarization/
│   ├── key_fact_extraction.yaml
│   ├── content_compression.yaml
│   └── fact_verification.yaml
└── research/
    ├── classification/
    │   ├── page_classifier.yaml
    │   └── search_engine_router.yaml
    ├── strategy/
    │   ├── strategy_selector.yaml
    │   └── requirements_reasoning.yaml
    ├── evaluation/
    │   └── source_quality_scorer.yaml
    ├── navigation/
    │   ├── navigation_decision.yaml
    │   ├── expected_state_generator.yaml
    │   └── state_verification.yaml
    ├── extraction/
    │   ├── schema_learner.yaml
    │   ├── product_extractor.yaml
    │   ├── viability_filter.yaml
    │   └── product_ranker.yaml
    └── vision/
        ├── page_structurer.yaml
        ├── screenshot_analyzer.yaml
        ├── captcha_detector.yaml
        ├── visual_verifier.yaml
        └── ocr_verifier.yaml
```

---

## Token Budget Summary

| Category | Model | Total Tokens | Count |
|----------|-------|--------------|-------|
| Pipeline | REFLEX | ~4,000 | 2 prompts |
| Pipeline | MIND | ~30,000 | 5 prompts |
| Pipeline | VOICE | ~10,000 | 1 prompt |
| Smart Summarization | REFLEX | ~2,000 | 2 prompts |
| Smart Summarization | NERVES | ~3,000 | 1 prompt |
| Research | REFLEX | ~600 | 2 prompts |
| Research | MIND | ~20,000 | 10 prompts |
| Research | EYES | ~10,000 | 5 prompts |

---

## Related Documents

- `architecture/LLM-ROLES/llm-roles-reference.md` - Model stack and phase assignments
- `architecture/main-system-patterns/phase*.md` - Individual phase specifications
- `architecture/mcp-tool-patterns/internet-research-mcp/INTERNET_RESEARCH_ARCHITECTURE.md` - Research tool internals

---

**Last Updated:** 2026-01-05
