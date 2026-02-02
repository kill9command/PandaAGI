# Prompt, Recipe & Summarization System

**Status:** SPECIFICATION
**Version:** 4.1
**Created:** 2026-01-01
**Updated:** 2026-01-27
**Purpose:** Define the prompt-management control plane, recipe-driven LLM execution, and automatic context compression.

---

## Table of Contents

**Part 1: Prompt Management**
1. [Core Idea](#1-core-idea)
2. [Definition](#2-definition)
3. [5-Model Cognitive Stack](#3-5-model-cognitive-stack)
4. [Design Principles](#4-design-principles)
5. [Core Components](#5-core-components)
6. [Prompt Packs](#6-prompt-packs-standard-input)
7. [Major Decision Points](#7-major-decision-points-llm-owned)

**Part 2: Recipe System**
8. [What is a Recipe](#8-what-is-a-recipe)
9. [Recipe File Structure](#9-recipe-file-structure)
10. [Recipe Schema](#10-recipe-schema)
11. [Token Budget System](#11-token-budget-system)
12. [Input Specification](#12-input-specification)
13. [Output Specification](#13-output-specification)
14. [Quality Gates](#14-quality-gates)
15. [Recipe Execution Flow](#15-recipe-execution-flow)
16. [Recipe Examples](#16-recipe-examples)
17. [Mode-Specific Recipes](#17-mode-specific-recipes)
18. [Recipe Loading & Validation](#18-recipe-loading--validation)

**Part 3: Smart Summarization**
19. [Summarization Overview](#19-summarization-overview)
20. [NERVES Model Assignment](#20-nerves-model-assignment)
21. [Core Components](#21-summarization-core-components)
22. [Content Types & Strategies](#22-content-types--strategies)
23. [Compression Recipes](#23-compression-recipes)
24. [Compression Algorithm](#24-compression-algorithm)
25. [Budget Trigger Hierarchy](#25-budget-trigger-hierarchy)
26. [Section 4 Enforcement](#26-section-4-enforcement)

**Part 4: Governance**
27. [Observability](#27-observability)
28. [Prompt Governance](#28-prompt-governance)
29. [Implementation Checklist](#29-implementation-checklist)

---

# Part 1: Prompt Management

## 1. Core Idea

Pandora is a **prompt-managed system**. The LLM is responsible for complex decisions, while code supplies structured evidence, executes actions, and verifies outcomes.

- **LLM decides**: routing, planning, selection, navigation, extraction intent, validation judgment.
- **Code provides**: evidence packs, tool execution, logging, verification, persistence.

> Document-Based IO and Recipe-Driven prompts are the system's control plane.

---

## 2. Definition

**Prompt Management System** = a control layer that:
1. Registers all prompts and their metadata.
2. Assembles prompt packs from documents and context.
3. Routes decisions to the correct prompt version.
4. Enforces IO contracts and token budgets via recipes.
5. Scores and tracks prompt quality over time.

**Outcome:** Prompts become first-class assets, and code becomes a deterministic substrate.

---

## 3. 5-Model Cognitive Stack

The system distributes prompt execution across a specialized 5-model stack:

| Layer | Model | Size | Role | Characteristics |
|-------|-------|------|------|-----------------|
| **Layer 0 (REFLEX)** | Qwen3-0.6B | ~0.2GB | Fast gates, classification | Sub-100ms, always hot |
| **Layer 1 (NERVES)** | Youtu-LLM-2B-Base | ~0.5GB | **Compression**, routing | Context summarization |
| **Layer 2 (MIND)** | Qwen3-Coder-30B-Instruct | ~1.0GB | Planning, reasoning | Keystone model |
| **Layer 4 (VOICE)** | Llama-3.1-8B-Instruct | ~4.0GB | User dialogue, synthesis | Natural language |
| **Layer 6 (EYES)** | Qwen3-VL-8B-Instruct | ~4.0GB | Vision tasks | Cold load on demand |

**Model Selection Principle:** Route to the smallest model capable of the task.

---

## 4. Design Principles

1. **LLM-First Decisions**
   All complex decision logic lives in prompts. Code never replaces LLM judgment with hand-tuned rules.

2. **Context Discipline**
   Prompts always receive the original user query and relevant evidence docs. Do not pre-classify user priorities.

3. **Document-Based IO**
   Context packs reference `context.md` and linked documents.

4. **Recipe-Driven Governance**
   Every prompt is loaded via a recipe that defines token budgets and output schema.

5. **Observable and Testable**
   Prompt version, inputs, outputs, and quality scores are logged for regression detection.

6. **Right-Sized Models**
   Each decision point is assigned to the smallest model that can reliably handle it.

7. **Transparent Compression**
   Documents are automatically compressed when they exceed budget - no manual intervention needed.

---

## 5. Core Components

### 5.1 Prompt Registry
- Catalog of all prompts with metadata: name, role, purpose, IO schema, token budget, risk level
- Version and change history
- Assigned model layer
- Source: `apps/prompts/` and `apps/recipes/*.yaml`

### 5.2 Prompt Pack Compiler
- Assembles the final prompt from: role prompt, shared policy, context docs, tool outputs
- Enforces token budgets and section limits
- Adapts context size to target model's capacity

### 5.3 Prompt Router
- Chooses which prompt to run based on phase and intent
- Routes to appropriate model layer based on task complexity
- Avoids hardcoded routing logic beyond mode gates

### 5.4 Prompt Evaluator
- Scores outputs by: schema compliance, confidence alignment, downstream success rate
- Logs per-prompt metrics for regression tracking
- Tracks model-specific performance metrics

### 5.5 Prompt Learning Loop
- Captures failures, interventions, and corrections
- Prompts are updated instead of adding heuristics in code

---

## 6. Prompt Packs (Standard Input)

Each LLM decision receives a **Prompt Pack**:

```
Prompt Pack
├── Role Prompt (apps/prompts/.../*.md)
├── Policy + IO Schema (shared)
├── context.md (current turn)
├── Linked docs (research.md, webpage_cache/*.json)
├── Tool results (raw bundles)
├── Original user query
└── Target Model Layer (REFLEX | NERVES | MIND | VOICE | EYES)
```

**Rule:** The LLM always sees the original user query for priority interpretation.

---

## 7. Major Decision Points (LLM-Owned)

These must be handled by prompts, not code:

| Decision Point | Model Layer | Rationale |
|----------------|-------------|-----------|
| **Reflection Gate** | REFLEX | Binary PROCEED/CLARIFY; fast classification |
| **Planner** | MIND | Goal decomposition, step ordering |
| **Coordinator** | MIND | Tool selection and iteration |
| **Research Strategy** | MIND | Phase/source/vendor selection |
| **Web Navigation** | MIND + EYES | Page understanding, action selection |
| **Extraction Validation** | MIND | Accept/reject/retry judgment |
| **Synthesis** | VOICE | User-facing response generation |
| **Validation** | MIND | Final quality gate |
| **Compression** | NERVES | Context summarization when over budget |

---

# Part 2: Recipe System

## 8. What is a Recipe

A **recipe** is a YAML configuration file that defines how to invoke an LLM for a specific task. Every LLM call in PandaAI v2 is executed via a recipe - there are no ad-hoc LLM invocations.

```
Recipe defines:
├── Which model to use (model_layer)
├── Token budgets (prompt, input, output)
├── System prompt (instructions)
├── Input documents (what the LLM sees)
├── Output schema (expected response format)
└── Quality gates (validation rules)
```

**Why Recipes?**
1. **Predictable Resource Usage** - Token budgets prevent runaway costs
2. **Model Assignment** - Each task routes to the right-sized model
3. **Testable** - Recipes can be unit tested for schema compliance
4. **Observable** - All invocations are logged with recipe metadata
5. **Versionable** - Recipe changes are tracked separately from code
6. **Separation of Concerns** - Prompt engineering is decoupled from application logic

---

## 9. Recipe File Structure

```
apps/
├── recipes/recipes/
│   ├── pipeline/              # Main 8-phase flow (15 recipes)
│   │   ├── phase0_query_analyzer.yaml
│   │   ├── phase1_context_gatherer.yaml
│   │   ├── phase2_reflection.yaml
│   │   ├── phase3_planner_chat.yaml
│   │   ├── phase3_planner_code.yaml
│   │   ├── phase4_coordinator_chat.yaml
│   │   ├── phase4_coordinator_code.yaml
│   │   ├── phase5_synthesizer_chat.yaml
│   │   ├── phase5_synthesizer_code.yaml
│   │   ├── phase6_validator.yaml
│   │   └── phase7_summarizer.yaml
│   ├── research/              # Research sub-system (23 recipes)
│   ├── browser/               # Browser/Page Intelligence (22 recipes)
│   ├── memory/                # Memory/Save (8 recipes)
│   ├── tools/                 # Tool-specific (12 recipes)
│   ├── filtering/             # Filtering/Scoring (3 recipes)
│   ├── reflection/            # Meta-reflection (4 recipes)
│   ├── navigation/            # Human navigation (3 recipes)
│   └── archive/               # Deprecated recipes
│
└── prompts/
    ├── pipeline/              # Main 8-phase flow (13 prompts)
    ├── research/              # Research sub-system (23 prompts)
    ├── browser/               # Browser/Page Intelligence (22 prompts)
    ├── memory/                # Memory/Save (8 prompts)
    ├── tools/                 # Tool-specific (12 prompts)
    ├── filtering/             # Filtering/Scoring (3 prompts)
    ├── reflection/            # Meta-reflection (4 prompts)
    ├── navigation/            # Human navigation (3 prompts)
    ├── executor/              # Executor tactical (2 prompts)
    └── archive/               # Deprecated prompts
```

**Convention:**
- Recipe files: `apps/recipes/recipes/{category}/{name}.yaml`
- Prompt files: `apps/prompts/{category}/{name}.md`
- Loading: `load_recipe("{category}/{name}")` e.g., `load_recipe("pipeline/phase3_planner_chat")`

---

## 10. Recipe Schema

### 10.1 Complete Schema

```yaml
# Required fields
name: planner_chat                    # Unique recipe identifier
description: Strategic planning for chat mode
model_layer: MIND                     # REFLEX | NERVES | MIND | VOICE | EYES

# Token budget (required)
token_budget:
  total: 5750                         # Maximum total tokens
  prompt: 1540                        # System prompt tokens
  input: 2000                         # Input document tokens
  output: 2000                        # Expected output tokens
  response_reserve: 200               # Buffer for response overhead

# Prompt configuration (required - choose one)
system_prompt: |
  You are the Planner...

# OR reference external prompt files
prompt_files:
  - prompts/planner/common.md
  - prompts/planner/strategic.md

# Input specification (required)
input_docs:
  - context.md
  - query_analysis.json

input_sections:                       # Which context.md sections
  - "§0"
  - "§1"
  - "§2"

# Output specification (required)
output_format: json                   # json | markdown | yaml | text
output_schema:                        # JSON Schema for validation
  type: object
  required:
    - next_step
    - tasks
  properties:
    next_step:
      type: string
      enum: [coordinator, synthesis, clarify]
    tasks:
      type: array

# Quality gates (optional)
quality_gates:
  schema_validation: true
  confidence_threshold: 0.7
  evidence_required: false
  max_retries: 2

# Compression settings (optional)
compression:
  enabled: true
  model_layer: NERVES                 # Always NERVES for compression
  preserve:
    - "section_0"                     # Never compress user query
    - "tool_errors"                   # Never compress errors

# Mode configuration (optional)
mode: chat                            # chat | code | null (both)
tools_available:
  - internet.research
  - memory.query
```

### 10.2 Minimal Recipe

```yaml
name: reflection
description: PROCEED or CLARIFY gate
model_layer: REFLEX

token_budget:
  total: 2200
  prompt: 600
  input: 1200
  output: 400

prompt_files:
  - prompts/reflection.md

input_sections:
  - "§0"
  - "§1"

output_format: json
output_schema:
  type: object
  required: [decision, confidence]
  properties:
    decision:
      type: string
      enum: [PROCEED, CLARIFY]
    confidence:
      type: number
```

---

## 11. Token Budget System

### 11.1 Budget Components

```yaml
token_budget:
  total: 5750       # Hard limit for entire call
  prompt: 1540      # System prompt allocation
  input: 2000       # Input documents allocation
  output: 2000      # Expected response size
  response_reserve: 200  # Safety buffer
```

**Constraint:** `prompt + input + output + response_reserve <= total`

### 11.2 Per-Phase Budgets

| Phase | Model | Total | Prompt | Input | Output |
|-------|-------|-------|--------|-------|--------|
| 0 Query Analyzer | REFLEX | 1,500 | 500 | 700 | 300 |
| 1 Reflection | REFLEX | 2,200 | 600 | 1,200 | 400 |
| 2 Context Gatherer | MIND | 10,500 | 2,000 | 6,000 | 2,500 |
| 3 Planner | MIND | 5,750 | 1,540 | 2,000 | 2,000 |
| 4 Coordinator | MIND | 8,000-12,000 | 2,500 | 3,500 | 2,000 |
| 5 Synthesis | VOICE | 10,000 | 1,300 | 5,500 | 3,000 |
| 6 Validation | MIND | 6,000 | 1,500 | 4,000 | 500 |
| Compression | NERVES | 1,000 | 300 | 500 | 200 |

**Per-Turn Estimate:** ~70K tokens typical

### 11.3 Section Budgets (context.md)

| Section | Budget | Content |
|---------|--------|---------|
| §0 | 500 | User query - never truncated |
| §1 | 300 | Reflection decision |
| §2 | 2,000 | Gathered context |
| §3 | 800 | Task plan |
| §4 | 2,500 | Tool results |
| §5 | 2,000 | Synthesis |
| §6 | 500 | Validation |

**All sections can be compressed** when they exceed budget (except §0).

---

## 12. Input Specification

### 12.1 Input Documents

```yaml
input_docs:
  - context.md                # Primary turn context
  - query_analysis.json       # Structured analysis from Phase 0
  - ticket.md                 # Task plan from Planner
  - toolresults.md            # Tool execution results
  - research.md               # Research findings
```

### 12.2 Section Selection

```yaml
input_sections:
  - "§0"    # User Query (always include)
  - "§1"    # Reflection
  - "§2"    # Context
  - "§3"    # Plan
```

The recipe executor extracts only specified sections from context.md.

### 12.3 Variable Injection

```yaml
variables:
  mode: "{{mode}}"
  session_id: "{{session_id}}"
  tools_available: "{{tools}}"
```

---

## 13. Output Specification

### 13.1 Output Format

```yaml
output_format: json    # json | markdown | yaml | text
```

### 13.2 Output Schema (JSON Schema)

```yaml
output_schema:
  type: object
  required:
    - decision
    - confidence
    - reasoning
  properties:
    decision:
      type: string
      enum: [PROCEED, CLARIFY]
    confidence:
      type: number
      minimum: 0
      maximum: 1
    reasoning:
      type: string
      maxLength: 500
```

### 13.3 Schema Validation

```python
async def execute_with_validation(recipe, inputs):
    result = await llm.invoke(recipe, inputs)

    if recipe.output_format == "json":
        parsed = json.loads(result)
        if recipe.output_schema:
            validate(parsed, recipe.output_schema)

    return result
```

On validation failure:
1. Retry up to `quality_gates.max_retries` times
2. If still failing, create intervention request and HALT

---

## 14. Quality Gates

```yaml
quality_gates:
  schema_validation: true      # Validate output against schema
  confidence_threshold: 0.7    # Minimum confidence score
  evidence_required: true      # Must cite source documents
  max_retries: 2               # Retry on failure
  timeout_ms: 30000            # Maximum execution time
```

| Gate | Phases | Description |
|------|--------|-------------|
| `schema_validation` | All | Output must match JSON Schema |
| `confidence_threshold` | 2, 6 | Below threshold → escalate |
| `evidence_required` | 4, 5, 6 | Claims must link to sources |
| `timeout_ms` | All | Maximum wait time |

---

## 15. Recipe Execution Flow

```
+-----------------------------------------------------------------------------+
|                         RECIPE EXECUTION FLOW                                |
+-----------------------------------------------------------------------------+

  1. LOAD RECIPE
     +-- Load YAML from apps/recipes/{name}.yaml
     +-- Validate recipe schema
     +-- Load prompt files if specified

  2. PREPARE INPUTS
     +-- Load input_docs (context.md, etc.)
     +-- Extract input_sections from context.md
     +-- Inject variables (mode, session_id, etc.)
     +-- Count tokens (fast, via tiktoken)

  3. CHECK BUDGET & COMPRESS IF NEEDED
     +-- Calculate: prompt_tokens + input_tokens
     +-- If over budget → SmartSummarizer compresses (NERVES)
     +-- Reserve space for output

  4. BUILD PROMPT PACK
     +-- System prompt (from recipe or prompt_files)
     +-- Input documents (compressed if needed)
     +-- Variables and context

  5. INVOKE MODEL
     +-- Route to model_layer (REFLEX/NERVES/MIND/VOICE/EYES)
     +-- Execute with timeout
     +-- Capture raw response

  6. VALIDATE OUTPUT
     +-- Parse according to output_format
     +-- Validate against output_schema
     +-- Check quality_gates (confidence, evidence)
     +-- On failure: retry or escalate

  7. LOG & RETURN
     +-- Log: recipe name, model, tokens, latency, success
     +-- Return validated result

+-----------------------------------------------------------------------------+
```

---

## 16. Recipe Examples

### 16.1 Phase 0: Query Analyzer

```yaml
name: query_analyzer
description: Classify user intent and extract entities
model_layer: REFLEX

token_budget:
  total: 1500
  prompt: 500
  input: 700
  output: 300

prompt_files:
  - prompts/query_analyzer/analyze.md

input_docs:
  - raw_query
  - turn_summaries

output_format: json
output_schema:
  type: object
  required: [query_type, intent, entities, resolved_query]
  properties:
    query_type:
      type: string
      enum: [informational, transactional, navigation, commerce_search, comparison]
    intent:
      type: string
    entities:
      type: array
    resolved_query:
      type: string
```

### 16.2 Phase 3: Planner

```yaml
name: planner_chat
description: Strategic planning for chat mode
model_layer: MIND
mode: chat

token_budget:
  total: 5750
  prompt: 1540
  input: 2000
  output: 2000

prompt_files:
  - prompts/planner/common.md
  - prompts/planner/strategic.md

input_sections:
  - "§0"
  - "§1"
  - "§2"

output_format: json
output_schema:
  type: object
  required: [next_step, confidence]
  properties:
    next_step:
      type: string
      enum: [coordinator, synthesis, clarify]
    tasks:
      type: array
    confidence:
      type: number

quality_gates:
  schema_validation: true
  max_retries: 2

tools_available:
  - internet.research
  - memory.query
  - memory.create
  - doc.search
```

### 16.3 Phase 5: Synthesis

```yaml
name: synthesizer_chat
description: Generate user-facing response
model_layer: VOICE
mode: chat

token_budget:
  total: 10000
  prompt: 1318
  input: 5500
  output: 3000

prompt_files:
  - prompts/synthesis/common.md
  - prompts/synthesis/synthesize.md

input_sections:
  - "§0"
  - "§1"
  - "§2"
  - "§3"
  - "§4"

input_docs:
  - toolresults.md

output_format: markdown

quality_gates:
  evidence_required: true
```

---

## 17. Mode-Specific Recipes

Some phases have different recipes for chat vs code mode:

| Phase | Chat Recipe | Code Recipe | Difference |
|-------|-------------|-------------|------------|
| 3 Planner | `planner_chat.yaml` | `planner_code.yaml` | Tools available, safety checks |
| 4 Coordinator | `coordinator_chat.yaml` | `coordinator_code.yaml` | Write tool access |
| 5 Synthesis | `synthesizer_chat.yaml` | `synthesizer_code.yaml` | Code formatting |

```python
def get_recipe(phase: str, mode: str) -> Recipe:
    if mode == "code":
        return load_recipe(f"{phase}_code.yaml")
    return load_recipe(f"{phase}_chat.yaml")
```

---

## 18. Recipe Loading & Validation

### 18.1 Fail-Fast Policy

**If a recipe file is missing, the system HALTS.** No fallback - missing recipes are configuration bugs.

```python
def load_recipe(name: str) -> Recipe:
    path = f"apps/recipes/{name}"

    if not path.exists():
        logger.error(f"Recipe not found: {name}")
        create_intervention_request(
            type="config_error",
            message=f"Missing recipe: {name}"
        )
        raise RecipeNotFoundError(name)

    return parse_yaml(path)
```

### 18.2 Recipe Validation

On load, recipes are validated:

```python
REQUIRED_FIELDS = ["name", "description", "model_layer", "token_budget"]

def validate_recipe(recipe: dict) -> None:
    for field in REQUIRED_FIELDS:
        if field not in recipe:
            raise RecipeValidationError(f"Missing required field: {field}")

    budget = recipe["token_budget"]
    total = budget.get("total", 0)
    parts = budget.get("prompt", 0) + budget.get("input", 0) + budget.get("output", 0)

    if parts > total:
        raise RecipeValidationError(f"Budget parts ({parts}) exceed total ({total})")
```

---

# Part 3: Smart Summarization

## 19. Summarization Overview

Pandora's document-based IO pattern causes context.md and supporting documents to grow through phases. Any document sent to an LLM could exceed the per-call context budget, causing truncated context or failed calls.

**The Smart Summarization Layer automatically compresses documents to fit within budget.**

**Design Goals:**
1. **Transparent** - No manual checks needed; system handles it automatically
2. **Preserving** - Critical information survives compression
3. **Universal** - Works for any document type (context.md, research.md, tool results)
4. **Efficient** - Minimal overhead when documents are already within budget
5. **Integrated** - Fits naturally into recipe-based LLM invocation pattern

**Constraint:** Per-call budget is limited (~12k tokens), but total tokens across all calls is unlimited.

---

## 20. NERVES Model Assignment

**All summarization/compression operations use the NERVES layer:**

| Component | Model | VRAM | Pool Status |
|-----------|-------|------|-------------|
| SummarizationEngine | Youtu-LLM-2B-Base (NERVES) | ~0.5 GB | **Always Hot** |

**Why NERVES for Summarization:**
- **Always in hot pool** - No cold load penalty, instant availability
- **Small and fast** - ~0.5 GB allows frequent compression calls without VRAM pressure
- **Designed for compression** - Layer 1 purpose is "routing, compression, lightweight reasoning"
- **Parallel-safe** - Can run compression while other phases use MIND/VOICE

**Token Budget per Compression Call:** ~1,000 tokens

---

## 21. Summarization Core Components

### 21.1 Token Counter

Fast, synchronous token counting using tiktoken (no LLM call needed):

```python
class TokenCounter:
    """Fast token counting for budget checks."""

    def __init__(self, model: str = "cl100k_base"):
        self.encoder = tiktoken.get_encoding(model)

    def count(self, text: str) -> int:
        """Count tokens in text. O(n) complexity."""
        return len(self.encoder.encode(text))

    def count_document(self, doc: Document) -> TokenBreakdown:
        """Count tokens per section for targeted compression."""
        return TokenBreakdown(
            total=self.count(doc.full_text),
            by_section={
                section.name: self.count(section.content)
                for section in doc.sections
            }
        )
```

### 21.2 Budget Checker

Determines if compression is needed and which sections to compress:

```python
class BudgetChecker:
    """Determines compression needs based on recipe budgets."""

    def check(self, documents: List[Document], recipe: Recipe) -> CompressionPlan:
        budget = recipe.token_budget  # e.g., 12000
        system_prompt_tokens = self.counter.count(recipe.system_prompt)
        available = budget - system_prompt_tokens - RESPONSE_RESERVE

        total_doc_tokens = sum(
            self.counter.count_document(d).total
            for d in documents
        )

        if total_doc_tokens <= available:
            return CompressionPlan(needed=False)

        return self._create_compression_plan(documents, available, total_doc_tokens)
```

### 21.3 Summarization Engine

Performs actual compression using NERVES:

```python
class SummarizationEngine:
    """
    Compresses documents while preserving critical information.
    Uses NERVES layer (Youtu-LLM-2B-Base) for all compression calls.
    """

    MODEL_LAYER = "NERVES"  # Always hot, ~0.5GB

    async def compress(
        self,
        content: str,
        content_type: ContentType,
        target_tokens: int,
        preserve_hints: List[str] = None
    ) -> str:
        recipe = self._get_compression_recipe(content_type)

        result = await self.llm.invoke(
            recipe=recipe,
            model_layer=self.MODEL_LAYER,
            variables={
                "content": content,
                "target_tokens": target_tokens,
                "preserve": preserve_hints or []
            }
        )

        return result.compressed_text
```

### 21.4 SmartSummarizer (Integration Layer)

Wraps every LLM call transparently:

```python
class SmartSummarizer:
    """Transparent summarization layer for LLM calls."""

    async def invoke_with_budget(
        self,
        recipe: Recipe,
        documents: Dict[str, str],
        variables: Dict[str, Any] = None
    ) -> LLMResponse:
        """
        Invoke LLM with automatic budget management.
        This is the ONLY way to call the LLM in the system.
        """
        # Step 1: Check if compression needed
        plan = self.checker.check(documents, recipe)

        if not plan.needed:
            # Fast path: no compression needed
            return await self._invoke_direct(recipe, documents, variables)

        # Step 2: Compress as needed (uses NERVES layer)
        compressed_docs = await self._apply_compression(documents, plan)

        # Step 3: Invoke with compressed docs
        return await self._invoke_direct(recipe, compressed_docs, variables)
```

---

## 22. Content Types & Strategies

Different content types require different compression strategies:

| Content Type | Strategy | Preserve |
|--------------|----------|----------|
| `context.md` | Section-aware | Section 0 (query), recent sections |
| `research.md` | Evidence-focused | URLs, prices, key claims |
| `page_doc` | Zone-focused | Content zone items, prices, product names |
| `tool_result` | Output-focused | Error messages, key data |
| `prior_turn` | Summary | User intent, system response |

### Content Type Detection

```python
class ContentType(Enum):
    CONTEXT_DOC = "context.md"
    RESEARCH_DOC = "research.md"
    PAGE_DOC = "page_doc"
    TOOL_RESULT = "tool_result"
    PRIOR_TURN = "prior_turn"
    GENERIC = "generic"

def detect_content_type(name: str, content: str) -> ContentType:
    if name == "context.md" or "## 0. User Query" in content:
        return ContentType.CONTEXT_DOC
    if name == "research.md" or "## Research Findings" in content:
        return ContentType.RESEARCH_DOC
    if "page_doc" in name or "ocr_items" in content:
        return ContentType.PAGE_DOC
    if name.startswith("tool:") or "tool_result" in name:
        return ContentType.TOOL_RESULT
    if "turn_" in name or "Previous Turn" in content:
        return ContentType.PRIOR_TURN
    return ContentType.GENERIC
```

### PAGE_DOC Compression Strategy

Page Intelligence captures can be large (full OCR + DOM zones). Special handling:

**Compression Rules:**
1. **Preserve structured data** - Zones with extracted fields kept intact
2. **Compress narrative** - raw_text summarized, not truncated
3. **Priority order:** pricing > product_info > reviews > navigation > other
4. **Confidence-based retention:**
   - Zones with confidence >= 0.8: keep full
   - Zones with confidence 0.5-0.79: keep key fields only
   - Zones with confidence < 0.5: drop or flag as uncertain

**Budget Allocation:**
- Structured zones: up to 70% of PAGE_DOC budget
- Supporting text: up to 20%
- Metadata (URL, timestamps): 10%

---

## 23. Compression Recipes

Each content type has a dedicated compression recipe.

### Recipe: compress_context.yaml

```yaml
name: compress_context
description: Compress context.md while preserving structure
model_layer: NERVES
token_budget:
  total: 1000
  prompt: 300
  input: 500
  output: 200

system_prompt: |
  You are a context compressor. Reduce the size of a context document
  while preserving critical information.

  RULES:
  1. ALWAYS preserve Section 0 (User Query) exactly as-is
  2. ALWAYS preserve the most recent section (highest number)
  3. Summarize middle sections, keeping key facts
  4. Preserve: URLs, prices, names, dates, error messages
  5. Remove: verbose explanations, redundant information

  Output the compressed document in the same markdown format.

input_docs:
  - context_to_compress

output_format: markdown
```

### Recipe: compress_research.yaml

```yaml
name: compress_research
description: Compress research findings preserving evidence
model_layer: NERVES
token_budget:
  total: 1000
  prompt: 300
  input: 500
  output: 200

system_prompt: |
  You are a research compressor. Compress research findings while
  preserving evidence integrity.

  RULES:
  1. ALWAYS preserve: URLs, prices, product names, store names
  2. ALWAYS preserve: error messages, availability status
  3. Summarize descriptions, remove marketing language
  4. Keep claims with their sources
  5. Prioritize: actionable data over background info

  Output compressed research in markdown format.

input_docs:
  - research_to_compress

output_format: markdown
```

### Recipe: compress_page_doc.yaml

```yaml
name: compress_page_doc
description: Compress PAGE_DOC preserving structured data
model_layer: NERVES
token_budget:
  total: 1000
  prompt: 300
  input: 500
  output: 200

system_prompt: |
  You are a page document compressor. Compress web page data while
  preserving extraction results.

  RULES:
  1. ALWAYS preserve: product names, prices, URLs
  2. ALWAYS preserve: zones with confidence >= 0.8
  3. Summarize zones with confidence 0.5-0.79
  4. Drop zones with confidence < 0.5
  5. Priority: pricing > product_info > reviews > navigation

  Output compressed page data in JSON format.

input_docs:
  - page_doc_to_compress

output_format: json
```

---

## 24. Compression Algorithm

### Phase 1: Budget Assessment

```python
def assess_budget(documents: Dict[str, str], recipe: Recipe) -> Assessment:
    budget = recipe.token_budget
    system_tokens = count_tokens(recipe.system_prompt)
    response_reserve = 2000

    available = budget - system_tokens - response_reserve
    total = sum(count_tokens(doc) for doc in documents.values())

    if total <= available:
        return Assessment(needed=False)

    return Assessment(
        needed=True,
        total_tokens=total,
        budget=available,
        overflow=total - available,
        compression_ratio=available / total
    )
```

### Phase 2: Prioritization

Not all content is equally important:

```python
PRIORITY_ORDER = [
    # Highest priority - never compress
    ("section_0", Priority.CRITICAL),   # User query
    ("error", Priority.CRITICAL),       # Error messages
    ("url", Priority.HIGH),             # URLs (evidence)
    ("price", Priority.HIGH),           # Prices (key data)

    # Medium priority - compress if needed
    ("section_N", Priority.MEDIUM),     # Most recent section
    ("claim", Priority.MEDIUM),         # Claims with sources

    # Lower priority - compress first
    ("description", Priority.LOW),      # Verbose descriptions
    ("history", Priority.LOW),          # Older conversation
]
```

### Phase 3: Iterative Compression

Compress lowest-priority content first until within budget:

```python
async def compress_to_budget(
    documents: Dict[str, str],
    target_tokens: int,
    engine: SummarizationEngine  # Uses NERVES layer
) -> Dict[str, str]:
    current = documents.copy()

    while count_total(current) > target_tokens:
        target = find_compression_target(current)

        if target is None:
            logger.warning(f"Cannot compress further. Over budget.")
            break

        # Compress via NERVES - fast, always hot
        compressed = await engine.compress(
            content=target.content,
            content_type=target.type,
            target_tokens=target.suggested_size
        )

        current[target.name] = compressed

    return current
```

---

## 25. Budget Trigger Hierarchy

Compression triggers at three levels, from most specific to most aggressive:

```
+-----------------------------------------------------------------------------+
|                    COMPRESSION TRIGGER HIERARCHY                             |
+-----------------------------------------------------------------------------+

  Level 1: SECTION OVERFLOW (soft limit)
  ----------------------------------------
  If section N > section_max_tokens[N]:
    → Compress section N only using section-specific recipe
    → Example: Section 4 > 2500 tokens → summarize tool results

  Level 2: DOCUMENT OVERFLOW (medium limit)
  -----------------------------------------
  If total context.md > 8600 tokens:
    → Apply SmartSummarizer to largest sections first
    → Target: reduce to 7500 tokens (leave headroom)

  Level 3: CALL OVERFLOW (hard limit)
  ------------------------------------
  If context.md + prompt + system > 11000 tokens:
    → Aggressive compression, drop low-relevance content
    → Must fit in 12000 token per-call budget

  Priority: Level 1 prevents Level 2, Level 2 prevents Level 3
  Always compress at the earliest possible level.

+-----------------------------------------------------------------------------+
```

**Why Early Compression Matters:**

| Trigger Level | Action | Impact |
|---------------|--------|--------|
| Section overflow | Compress one section | Minimal - targeted |
| Document overflow | Compress multiple sections | Moderate - may lose detail |
| Call overflow | Emergency truncation | Severe - may drop critical context |

---

## 26. Section 4 Enforcement

Section 4 grows during the Coordinator loop as tools execute. Enforce budget DURING writing, not just at compression time:

```python
async def append_tool_result_to_section4(context_doc, result):
    """Add tool result to Section 4 with budget enforcement."""

    current_tokens = count_tokens(context_doc.get_section(4))
    result_tokens = count_tokens(format_tool_result(result))

    if current_tokens + result_tokens > SECTION_4_BUDGET:  # 2500 tokens
        # Summarize existing Section 4 before adding new result
        # Uses NERVES layer - fast, no cold load penalty
        existing = context_doc.get_section(4)
        compressed = await compress_section4(existing, target_tokens=1500)
        context_doc.replace_section(4, compressed)

    # Now add the new result
    context_doc.append_to_section(4, format_tool_result(result))
```

**Key rules:**
- Check Section 4 size BEFORE adding each tool result
- If approaching limit, compress EXISTING content first
- Always keep newest result in full (most relevant)
- Older results get summarized progressively

---

# Part 4: Governance

## 27. Observability

Every recipe execution is logged:

```json
{
  "timestamp": "2026-01-05T14:30:00Z",
  "recipe": "planner_chat",
  "model_layer": "MIND",
  "session_id": "abc123",
  "turn_id": "turn_000042",

  "tokens": {
    "prompt": 1520,
    "input": 1850,
    "output": 1200,
    "total": 4570
  },

  "latency_ms": 850,
  "success": true,
  "schema_valid": true,
  "confidence": 0.85,

  "retries": 0,
  "compression_applied": false,
  "compression_savings": 0
}
```

### Compression Logging

```python
logger.info(
    "smart_summarization",
    event="compressed",
    original_tokens=15000,
    compressed_tokens=9500,
    compression_ratio=0.63,
    content_type="context.md",
    recipe="coordinator_chat",
    model_layer="NERVES"
)
```

### Compression Metrics

```python
METRICS = {
    "compression_invocations": Counter,    # How often compression runs
    "tokens_saved": Histogram,             # Tokens saved per compression
    "compression_latency_ms": Histogram,   # Time spent compressing
    "overflow_warnings": Counter,          # Times we couldn't fit budget
}
```

---

## 28. Prompt Governance

**Versioning**
- Prompts are versioned by file history
- Each change is tracked in logs and evaluation metrics
- Model assignment changes are tracked separately

**Testing**
- Prompts have unit tests for schema compliance
- Integration tests validate full flows
- Model-specific performance benchmarks
- Compression tests verify critical content is preserved

**Rollbacks**
- Prompt regressions can be rolled back without code changes
- Model assignment can be adjusted independently of prompt content

---

## 29. Implementation Checklist

**Recipe System:**
- [ ] Create `apps/recipes/` directory
- [ ] Create `apps/prompts/` directory structure
- [ ] Implement `RecipeLoader` with validation
- [ ] Implement `RecipeExecutor` with budget checking
- [ ] Add schema validation (jsonschema)
- [ ] Add execution logging
- [ ] Create recipe registry index (`apps/recipes/registry.yaml`)
- [ ] Migrate all inline prompts to recipe files
- [ ] Implement model routing layer

**Smart Summarization:**
- [ ] Implement `TokenCounter` using tiktoken
- [ ] Implement `BudgetChecker`
- [ ] Implement `SummarizationEngine` with NERVES layer
- [ ] Create compression recipes (`compress_*.yaml`)
- [ ] Implement content type detection
- [ ] Integrate SmartSummarizer into RecipeExecutor
- [ ] Add Section 4 enforcement during Coordinator loop
- [ ] Add compression metrics and logging

---

## Related Documentation

- `DOCUMENT_IO_ARCHITECTURE.md` - Document flow and context.md specification
- `MEMORY_ARCHITECTURE.md` - Memory retrieval and storage
- `OBSERVABILITY_SYSTEM.md` - Full metrics and debugging system
- `../LLM-ROLES/llm-roles-reference.md` - Model stack and phase assignments
- Phase docs (`phase0-*.md` through `phase6-*.md`) - Per-phase specifications

---

## Configuration

```bash
# Token budgets
DEFAULT_CONTEXT_BUDGET=12000      # Default per-call budget
RESPONSE_TOKEN_RESERVE=2000       # Reserved for response
COMPRESSION_THRESHOLD=0.9         # Compress if >90% of budget

# Compression behavior
COMPRESSION_ENABLED=true          # Toggle system on/off
COMPRESSION_CACHE_TTL=300         # Cache compressed versions (seconds)
MIN_COMPRESSION_SAVINGS=500       # Don't compress if savings < 500 tokens

# Model layer for compression
COMPRESSION_MODEL_LAYER=NERVES    # Always use NERVES (Youtu-LLM-2B-Base)
```

---

**Last Updated:** 2026-01-05
