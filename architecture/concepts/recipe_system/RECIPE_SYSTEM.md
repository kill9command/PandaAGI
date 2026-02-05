# Recipe System

**Version:** 2.0
**Updated:** 2026-02-03

**Related:**
- All phases — every LLM call is executed via a recipe
- [`PROMPT_MANAGEMENT_SYSTEM.md`](./PROMPT_MANAGEMENT_SYSTEM.md) — Prompt philosophy, quality gates, and auto-compression

---

## 1. Overview

A **recipe** is a YAML configuration file that defines how to invoke an LLM for a specific task. Every LLM call in Pandora is executed via a recipe — there are no ad-hoc LLM invocations.

Each recipe has a paired prompt markdown file. Recipes and prompts are organized by category and share the same naming convention.

**Why recipes?**
- **Token governance** — Budgets prevent runaway costs
- **Role assignment** — Each task routes to the right temperature
- **Testability** — Recipes can be validated for schema compliance
- **Observability** — All invocations are logged with recipe metadata
- **Separation** — Prompt engineering is decoupled from application logic

---

## 2. Recipe Schema

### 2.1 Core Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique recipe identifier |
| `category` | string | Yes | Category grouping |
| `role` | string | Yes | LLM role: REFLEX, NERVES, MIND, VOICE |
| `temperature` | float | No | Overrides role default if set |
| `mode` | string | No | `chat`, `code`, or omit for both |
| `phase` | integer | No | Pipeline phase number (for pipeline recipes) |

### 2.2 Prompt Configuration

| Field | Type | Description |
|-------|------|-------------|
| `prompt_fragments` | array of strings | Paths to prompt markdown files, loaded in order |

### 2.3 Input Documents

| Field | Type | Description |
|-------|------|-------------|
| `input_docs` | array of objects | Documents the LLM sees |

Each input doc:

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Document path (e.g., `context.md`) |
| `sections` | array | Which context.md sections to include |
| `path_type` | string | `turn` (turn directory) or `input` (injected) |
| `optional` | boolean | Whether missing doc is an error |
| `max_tokens` | integer | Token limit for this input |
| `description` | string | Human-readable purpose |

### 2.4 Output Documents

| Field | Type | Description |
|-------|------|-------------|
| `output_doc` | object | Single output (path, section, description) |
| `output_docs` | array | Multiple outputs (for executor/tool recipes) |
| `output_schema` | string | Named schema for validation |

### 2.5 Token Budget

| Field | Type | Description |
|-------|------|-------------|
| `total` | integer | Hard limit for entire call |
| `prompt` | integer | System prompt allocation |
| `input_docs` | integer | Input documents allocation |
| `output` | integer | Expected response size |
| `buffer` | integer | Safety margin |

**Constraint:** `prompt + input_docs + output + buffer <= total`

### 2.6 LLM Parameters

| Field | Type | Description |
|-------|------|-------------|
| `temperature` | float | Sampling temperature |
| `max_tokens` | integer | Max response tokens (hard limit sent to the inference server) |

### 2.7 Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `executor_loop` | object | Loop config (`enabled`, `max_iterations`) for executor recipes |
| `trimming_strategy` | object | How to trim input when over budget (`method`, `target`) |
| `compression` | object | NERVES compression settings |

---

## 3. Recipe Categories

Recipes are organized by the subsystem they serve:

| Category | Purpose |
|----------|---------|
| `pipeline` | Main 9-phase flow — one or more recipes per phase |
| `browser` | Page intelligence, zone identification, element selection, extraction |
| `research` | Research planning, source selection, result scoring, synthesis |
| `memory` | Preference extraction, cache decisions, memory operations |
| `tools` | Tool-specific execution recipes |
| `filtering` | Result filtering and scoring |
| `reflection` | Meta-reflection and improvement extraction |
| `navigation` | Site navigation decisions |
| `executor` | Executor tactical layer (chat and code variants) |

---

## 4. Pipeline Phase Assignments

Each pipeline phase has one or more assigned recipes with an appropriate role:

| Phase | Role | Notes |
|-------|------|-------|
| 0 Query Analyzer | REFLEX | Single recipe, low budget |
| 1 Reflection | REFLEX | Gate decision only |
| 2 Context Gatherer | MIND | May have variants for different gathering strategies |
| 3 Planner | MIND | Mode-specific (chat/code) |
| 4 Executor | MIND | Mode-specific (chat/code) |
| 5 Coordinator | MIND | Mode-specific (chat/code), largest budget for tool orchestration |
| 6 Synthesis | VOICE | Mode-specific (chat/code) |
| 7 Validation | MIND | Single recipe |
| Compression | NERVES | Invoked when documents exceed budget |

Roles determine base temperature. Budgets are defined per-recipe in the YAML files.

---

## 5. Named Output Schemas

Recipes that produce structured output declare a named `output_schema`. The recipe executor validates the LLM's response against this schema:

| Schema Name | Phase | Key Fields |
|-------------|-------|------------|
| `QUERY_ANALYSIS` | 1 | `resolved_query`, `user_purpose`, `data_requirements`, `mode` |
| `REFLECTION_DECISION` | 1 | `decision` (PROCEED/CLARIFY), `confidence` |
| `STRATEGIC_PLAN` | 3 | `route_to`, `goals`, `approach`, `success_criteria` |
| `EXECUTOR_DECISION` | 4 | Decision: COMMAND, ANALYZE, COMPLETE, or BLOCKED |
| `TOOL_CALLS` | 5 | Tool name and arguments |

On validation failure: retry up to `max_retries`, then create intervention and HALT.

---

## 6. Recipe + Prompt Separation

Recipes define **what** (budgets, schema, inputs). Prompts define **how** (instructions to the LLM).

```
Recipe (YAML)                    Prompt (Markdown)
├── role: MIND                   ├── System instructions
├── token_budget: ...            ├── Output format examples
├── input_docs: ...              ├── Decision criteria
├── output_schema: ...           └── Domain-specific guidance
└── prompt_fragments: [path] ──────►
```

**Rule:** To change LLM behavior, edit the prompt. To change resource allocation, edit the recipe. Never mix concerns.

---

## 7. Mode-Specific Recipes

Four phases have separate recipes for chat and code modes:

| Phase | Difference |
|-------|------------|
| 3 Planner | Different tools available, code-specific goals |
| 4 Executor | Different command vocabulary |
| 5 Coordinator | Different tool families |
| 6 Synthesis | Response format differs |

Mode is determined by Phase 0 and propagated through the pipeline. Phases 0, 1, 2, 7, and compression use the same recipe regardless of mode.

---

## 8. Related Documents

- [`PROMPT_MANAGEMENT_SYSTEM.md`](./PROMPT_MANAGEMENT_SYSTEM.md) — Prompt philosophy, quality gates, and auto-compression
- `architecture/concepts/system_loops/EXECUTION_SYSTEM.md` — How recipes fit in the execution loop
- `architecture/concepts/error_and_improvement_system/ERROR_HANDLING.md` — What happens when schema validation fails
- `architecture/LLM-ROLES/llm-roles-reference.md` — Role definitions (REFLEX, NERVES, MIND, VOICE)

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-03 | Initial specification. Distilled from actual recipe files and PROMPT_MANAGEMENT_SYSTEM.md |
| 2.0 | 2026-02-03 | Removed specific recipe filenames, token counts, category counts, file paths, and function signatures. Pure concept doc. |

---

**Last Updated:** 2026-02-03
