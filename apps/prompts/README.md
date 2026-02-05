# Panda Prompt System

**Last Updated:** 2026-01-27
**Architecture Version:** V6 Recipe-Based

---

## Overview

All prompts are loaded through the recipe system. Each prompt has a corresponding recipe YAML that defines token budgets, input/output documents, and loading configuration.

**Key Principle:** `context.md` is the source of truth. All phases read from and write to context.md sections.

**Total:** 91 prompts, 93 recipes

---

## Directory Structure

```
apps/prompts/
├── pipeline/          # Main 9-phase flow (13 prompts)
│   ├── phase0_query_analyzer.md
│   ├── phase1_context_gatherer.md
│   ├── phase1_context_gatherer_retrieval.md
│   ├── phase1_context_gatherer_synthesis.md
│   ├── phase2_reflection.md
│   ├── phase3_planner_chat.md
│   ├── phase3_planner_code.md
│   ├── phase4_coordinator_chat.md
│   ├── phase4_coordinator_code.md
│   ├── phase5_synthesizer_chat.md
│   ├── phase5_synthesizer_code.md
│   ├── phase6_validator.md
│   ├── phase7_summarizer.md
│   ├── reference_resolver.md
│   └── response_revision.md
│
├── research/          # Research sub-system (23 prompts)
│   ├── strategy_selector.md
│   ├── query_generator.md
│   ├── serp_analyzer.md
│   ├── content_extractor.md
│   ├── page_reader.md
│   ├── result_scorer.md
│   ├── synthesizer.md
│   ├── goal_checker.md
│   ├── shopping_query_generator.md
│   ├── item_lister.md
│   ├── page_summarizer.md
│   ├── ocr_serp_analyzer.md
│   ├── organic_results_extractor.md
│   ├── webpage_reader.md
│   ├── goal_generator.md
│   ├── requirements_reasoning.md
│   ├── intelligence_synthesizer.md
│   ├── search_result_evaluator.md
│   ├── query_reflection.md
│   ├── phase1_search_terms_structured.md
│   ├── query_sanitizer.md
│   ├── topic_keyword_extractor.md
│   └── topic_extractor.md
│
├── browser/           # Browser/Page Intelligence (22 prompts)
│   ├── navigation_decider.md
│   ├── relevance_checker.md
│   ├── pagination_handler.md
│   ├── element_selector.md
│   ├── extraction_validator.md
│   ├── multi_page_synth.md
│   ├── continuation.md
│   ├── page_selector_generator.md
│   ├── page_zone_identifier.md
│   ├── page_strategy_selector.md
│   ├── calibration_selector_generator.md
│   ├── calibration_schema_creator.md
│   ├── ocr_items.md
│   ├── raw_ocr.md
│   ├── vision_zone.md
│   ├── prose_intel.md
│   ├── article.md
│   ├── contact_info.md
│   ├── forum.md
│   ├── list.md
│   ├── news.md
│   └── generic.md
│
├── memory/            # Memory/Save (8 prompts)
│   ├── claim_summarizer.md
│   ├── fact_summarizer.md
│   ├── preference_extractor.md
│   ├── turn_compressor.md
│   ├── cache_decision.md
│   ├── context_builder.md
│   ├── summarizer.md
│   └── context_memory_processor.md
│
├── tools/             # Tool-specific (12 prompts)
│   ├── product_extractor.md
│   ├── viability_evaluator.md
│   ├── viability_evaluator_v2.md
│   ├── schema_builder.md
│   ├── claim_evaluator.md
│   ├── pdp_selector.md
│   ├── pdp_specs.md
│   ├── content_summarizer.md
│   ├── search_result_verifier.md
│   ├── vendor_selector.md
│   ├── product_matcher.md
│   └── search_result_filter.md
│
├── filtering/         # Filtering/Scoring (3 prompts)
│   ├── candidate_filter.md
│   ├── vendor_validator.md
│   └── source_quality_scorer.md
│
├── reflection/        # Meta-reflection (4 prompts)
│   ├── unified.md
│   ├── guide_reflection.md
│   ├── coordinator_reflection.md
│   └── context_manager_reflection.md
│
├── navigation/        # Human navigation (3 prompts)
│   ├── human_scanner.md
│   ├── human_extractor.md
│   └── human_validator.md
│
├── executor/          # Executor tactical (2 prompts)
│   ├── tactical.md
│   └── code_tactical.md
│
└── archive/           # Deprecated prompts
    └── 2026-01-26-cleanup/
```

---

## Recipe Structure

Each prompt has a corresponding recipe in `apps/recipes/recipes/{category}/`:

```yaml
name: phase3_planner_chat
category: pipeline
phase: 3

prompt_fragments:
  - "apps/prompts/pipeline/phase3_planner_chat.md"

input_docs:
  - path: "context.md"
    sections: ["§0", "§1", "§2"]
    path_type: "turn"

output_doc:
  path: "context.md"
  section: "§3"

token_budget:
  total: 6000
  prompt: 2000
  input_docs: 2500
  output: 1500
```

---

## Document IO Pattern

### Main Pipeline

| Phase | Reads | Writes |
|-------|-------|--------|
| 0 Query Analyzer | User query | §0 |
| 1 Context Gatherer | §0 | §1 |
| 2 Reflection | §0, §1 | §2 |
| 3 Planner | §0, §1, §2 | §3 |
| 4 Coordinator | §0-§3 | §4 |
| 5 Synthesizer | §0-§4 | §5 |
| 6 Validator | §0-§5 | §6 |
| 7 Summarizer | §0-§6 | Turn index |

### Research Sub-system

Research reads from `context.md` (query, goals) and writes to `research.md`. Relevant findings are appended to `context.md §4` with a link to the full `research.md`.

---

## Chat vs Code Mode

Phases 0, 1, 2, 6, 7 are shared between modes.

Phases 3, 4, 5 have mode-specific variants:

| Phase | Chat Mode | Code Mode |
|-------|-----------|-----------|
| 3 Planner | Routes: executor/synthesis/clarify | + brainstorm route |
| 4 Coordinator | Tools: internet.research, memory.* | Tools: file.*, git.*, code.* |
| 5 Synthesizer | Conversational response | Code blocks, diffs |

---

## Loading Prompts

All prompts are loaded via the recipe system:

```python
from libs.gateway.recipe_loader import load_recipe

recipe = load_recipe("pipeline/phase3_planner_chat")
prompt = recipe.get_prompt()
```

For Python files that previously used `_load_prompt()`, use this pattern:

```python
from typing import Dict

_prompt_cache: Dict[str, str] = {}

def _load_prompt_via_recipe(recipe_name: str, category: str = "tools") -> str:
    """Load prompt via recipe system with inline fallback."""
    cache_key = f"{category}/{recipe_name}"
    if cache_key in _prompt_cache:
        return _prompt_cache[cache_key]
    try:
        from libs.gateway.recipe_loader import load_recipe
        recipe = load_recipe(f"{category}/{recipe_name}")
        content = recipe.get_prompt()
        _prompt_cache[cache_key] = content
        return content
    except Exception as e:
        logger.warning(f"Recipe {cache_key} not found: {e}")
        return ""
```

**DO NOT** use direct file loading. The recipe system ensures:
- Token budgets are enforced
- Input/output contracts are defined
- Prompts are cacheable

---

## Adding New Prompts

1. Create prompt file: `apps/prompts/{category}/{name}.md`
2. Create recipe: `apps/recipes/recipes/{category}/{name}.yaml`
3. Define token budget in recipe
4. Specify input_docs and output_doc
5. Test with: `python scripts/test_recipe_loading.py`

---

## Token Budgets

Total system budget: 12,000 tokens

| Category | Typical Budget |
|----------|----------------|
| Query Analyzer | 1,500 |
| Context Gatherer | 4,000 |
| Reflection | 1,500 |
| Planner | 6,000 |
| Coordinator | 8,000 |
| Synthesizer | 10,000 |
| Validator | 9,500 |
| Summarizer | 3,000 |
