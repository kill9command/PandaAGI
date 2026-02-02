# Prompt System Inventory

**Last Updated:** 2026-02-02
**Status:** CURRENT (V2 Style Migration Complete for Pipeline/Executor)

---

## V2 Style Migration

Pipeline and Executor prompts have been migrated to V2 style:
- Abstract examples with `[placeholders]`
- Tables over prose
- 150-line target
- "Do NOT" anti-pattern sections

**See:** `architecture/prompting-manual/V2_PROMPT_STYLE.md`

---

## Summary

| Category | Prompts | Recipes |
|----------|---------|---------|
| Pipeline | 13 | 15 |
| Research | 23 | 23 |
| Browser | 22 | 22 |
| Memory | 8 | 8 |
| Tools | 12 | 12 |
| Filtering | 3 | 3 |
| Reflection | 4 | 4 |
| Navigation | 3 | 3 |
| Executor | 2 | 2 |
| **Total** | **91** | **93** |

**Loading Method:** ALL prompts use recipe system (`load_recipe()`)

---

## Directory Structure

```
apps/prompts/
├── pipeline/          # Main 8-phase flow (13 prompts)
├── research/          # Research sub-system (23 prompts)
├── browser/           # Browser/Page Intelligence (22 prompts)
├── memory/            # Memory/Save (8 prompts)
├── tools/             # Tool-specific (12 prompts)
├── filtering/         # Filtering/Scoring (3 prompts)
├── reflection/        # Meta-reflection (4 prompts)
├── navigation/        # Human navigation (3 prompts)
├── executor/          # Executor tactical (2 prompts)
└── archive/           # Deprecated prompts
```

---

## 1. Pipeline Prompts (13)

Main 8-phase flow with chat/code variants for phases 3, 4, 5.

| Prompt | Recipe | Purpose |
|--------|--------|---------|
| phase0_query_analyzer.md | pipeline/phase0_query_analyzer | Classify intent, extract entities |
| phase1_context_gatherer.md | pipeline/phase1_context_gatherer | Gather relevant context |
| phase1_context_gatherer_retrieval.md | pipeline/phase1_context_gatherer_retrieval | Retrieve context |
| phase1_context_gatherer_synthesis.md | pipeline/phase1_context_gatherer_synthesis | Synthesize context |
| phase2_reflection.md | pipeline/phase2_reflection | PROCEED/CLARIFY gate |
| phase3_planner_chat.md | pipeline/phase3_planner_chat | Chat mode planning |
| phase3_planner_code.md | pipeline/phase3_planner_code | Code mode planning |
| phase4_coordinator_chat.md | pipeline/phase4_coordinator_chat | Chat mode tool execution |
| phase4_coordinator_code.md | pipeline/phase4_coordinator_code | Code mode tool execution |
| phase5_synthesizer_chat.md | pipeline/phase5_synthesizer_chat | Chat response generation |
| phase5_synthesizer_code.md | pipeline/phase5_synthesizer_code | Code response generation |
| phase6_validator.md | pipeline/phase6_validator | Final validation |
| phase7_summarizer.md | pipeline/phase7_summarizer | Turn summary |
| reference_resolver.md | pipeline/reference_resolver | Resolve pronouns/references |
| response_revision.md | pipeline/response_revision | Revise on RETRY |

---

## 2. Research Prompts (23)

Research sub-system reads from context.md, writes to research.md.

| Prompt | Recipe | Purpose |
|--------|--------|---------|
| strategy_selector.md | research/strategy_selector | Choose research strategy |
| query_generator.md | research/query_generator | Generate search queries |
| serp_analyzer.md | research/serp_analyzer | Analyze search results |
| content_extractor.md | research/content_extractor | Extract from pages |
| page_reader.md | research/page_reader | Read/summarize pages |
| result_scorer.md | research/result_scorer | Score results |
| synthesizer.md | research/synthesizer | Synthesize findings |
| goal_checker.md | research/goal_checker | Check if goals met |
| shopping_query_generator.md | research/shopping_query_generator | Generate shopping queries |
| item_lister.md | research/item_lister | List items from page |
| page_summarizer.md | research/page_summarizer | Summarize page content |
| ocr_serp_analyzer.md | research/ocr_serp_analyzer | Analyze OCR'd SERP |
| organic_results_extractor.md | research/organic_results_extractor | Extract organic results |
| webpage_reader.md | research/webpage_reader | Read web pages |
| goal_generator.md | research/goal_generator | Generate research goals |
| requirements_reasoning.md | research/requirements_reasoning | Reason about requirements |
| intelligence_synthesizer.md | research/intelligence_synthesizer | Synthesize intelligence |
| search_result_evaluator.md | research/search_result_evaluator | Evaluate search results |
| query_reflection.md | research/query_reflection | Reflect on query |
| phase1_search_terms_structured.md | research/phase1_search_terms_structured | Extract search terms |
| query_sanitizer.md | research/query_sanitizer | Sanitize query |
| topic_keyword_extractor.md | research/topic_keyword_extractor | Extract topic keywords |
| topic_extractor.md | research/topic_extractor | Extract topic metadata |

---

## 3. Browser Prompts (22)

Browser/page intelligence for navigation and extraction.

| Prompt | Recipe | Purpose |
|--------|--------|---------|
| navigation_decider.md | browser/navigation_decider | Decide next action |
| relevance_checker.md | browser/relevance_checker | Check content relevance |
| pagination_handler.md | browser/pagination_handler | Handle pagination |
| element_selector.md | browser/element_selector | Select UI elements |
| extraction_validator.md | browser/extraction_validator | Validate extractions |
| multi_page_synth.md | browser/multi_page_synth | Synthesize multi-page |
| continuation.md | browser/continuation | Continue multi-page |
| page_selector_generator.md | browser/page_selector_generator | Generate CSS selectors |
| page_zone_identifier.md | browser/page_zone_identifier | Identify page zones |
| page_strategy_selector.md | browser/page_strategy_selector | Select extraction strategy |
| calibration_selector_generator.md | browser/calibration_selector_generator | Generate calibration selectors |
| calibration_schema_creator.md | browser/calibration_schema_creator | Create calibration schema |
| ocr_items.md | browser/ocr_items | Extract OCR items |
| raw_ocr.md | browser/raw_ocr | Raw OCR extraction |
| vision_zone.md | browser/vision_zone | Vision zone identification |
| prose_intel.md | browser/prose_intel | Prose intelligence |
| article.md | browser/article | Article extraction |
| contact_info.md | browser/contact_info | Contact info extraction |
| forum.md | browser/forum | Forum extraction |
| list.md | browser/list | List extraction |
| news.md | browser/news | News extraction |
| generic.md | browser/generic | Generic extraction |

---

## 4. Memory Prompts (8)

Memory operations for context compression and persistence.

| Prompt | Recipe | Purpose |
|--------|--------|---------|
| claim_summarizer.md | memory/claim_summarizer | Summarize claims |
| fact_summarizer.md | memory/fact_summarizer | Summarize facts |
| preference_extractor.md | memory/preference_extractor | Extract preferences |
| turn_compressor.md | memory/turn_compressor | Compress turn |
| cache_decision.md | memory/cache_decision | Decide cacheability |
| context_builder.md | memory/context_builder | Build context |
| summarizer.md | memory/summarizer | General summarization |
| context_memory_processor.md | memory/context_memory_processor | Process context memory |

---

## 5. Tools Prompts (12)

Tool-specific prompts for product extraction, viability, etc.

| Prompt | Recipe | Purpose |
|--------|--------|---------|
| product_extractor.md | tools/product_extractor | Extract product data |
| viability_evaluator.md | tools/viability_evaluator | Evaluate viability |
| viability_evaluator_v2.md | tools/viability_evaluator_v2 | V2 viability evaluation |
| schema_builder.md | tools/schema_builder | Build schemas |
| claim_evaluator.md | tools/claim_evaluator | Evaluate claims |
| pdp_selector.md | tools/pdp_selector | Select PDP elements |
| pdp_specs.md | tools/pdp_specs | Extract PDP specs |
| content_summarizer.md | tools/content_summarizer | Summarize content |
| search_result_verifier.md | tools/search_result_verifier | Verify search results |
| vendor_selector.md | tools/vendor_selector | Select vendors |
| product_matcher.md | tools/product_matcher | Match products |
| search_result_filter.md | tools/search_result_filter | Filter search results |

---

## 6. Filtering Prompts (3)

Filtering and scoring prompts.

| Prompt | Recipe | Purpose |
|--------|--------|---------|
| candidate_filter.md | filtering/candidate_filter | Filter candidates |
| vendor_validator.md | filtering/vendor_validator | Validate vendors |
| source_quality_scorer.md | filtering/source_quality_scorer | Score source quality |

---

## 7. Reflection Prompts (4)

Meta-reflection for role introspection.

| Prompt | Recipe | Purpose |
|--------|--------|---------|
| unified.md | reflection/unified | Unified reflection |
| guide_reflection.md | reflection/guide_reflection | Guide role reflection |
| coordinator_reflection.md | reflection/coordinator_reflection | Coordinator reflection |
| context_manager_reflection.md | reflection/context_manager_reflection | CM reflection |

---

## 8. Navigation Prompts (3)

Human-like navigation prompts.

| Prompt | Recipe | Purpose |
|--------|--------|---------|
| human_scanner.md | navigation/human_scanner | Human-like page scan |
| human_extractor.md | navigation/human_extractor | Human-like extraction |
| human_validator.md | navigation/human_validator | Human-like validation |

---

## 9. Executor Prompts (2)

Executor tactical prompts.

| Prompt | Recipe | Purpose |
|--------|--------|---------|
| tactical.md | executor_chat | Chat executor |
| code_tactical.md | executor_code | Code executor |

---

## Loading Pattern

All prompts are loaded via the recipe system:

```python
from libs.gateway.recipe_loader import load_recipe

# Load via category/name
recipe = load_recipe("pipeline/phase3_planner_chat")
prompt = recipe.get_prompt()

# For backward compatibility in orchestrator files
def _load_prompt_via_recipe(recipe_name: str, category: str = "tools") -> str:
    try:
        recipe = load_recipe(f"{category}/{recipe_name}")
        return recipe.get_prompt()
    except Exception:
        return ""  # fallback to inline
```

---

## Related Documentation

- `apps/prompts/README.md` - Detailed prompt system documentation
- `architecture/DOCUMENT-IO-SYSTEM/PROMPT_MANAGEMENT_SYSTEM.md` - Full specification
- `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` - Document IO pattern
