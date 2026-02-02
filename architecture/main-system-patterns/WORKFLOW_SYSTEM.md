# Workflow System

Version: 1.0
Updated: 2026-02-02

---

## Overview

The Workflow System provides declarative, predictable tool sequences that replace ad-hoc tool decisions. Instead of the Planner deciding which tools to use on each turn, it selects a **workflow by name**, and the workflow defines the exact tool sequence.

**Key Benefits:**
- Predictable execution paths
- Testable tool sequences
- Self-documenting behavior
- Reduced hallucination in tool selection

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      Phase 4: Executor                        │
│                                                               │
│  ┌─────────────────┐    ┌──────────────────┐                 │
│  │ WorkflowMatcher │───▶│ WorkflowExecutor │                 │
│  └─────────────────┘    └──────────────────┘                 │
│          │                       │                            │
│          ▼                       ▼                            │
│  ┌─────────────────┐    ┌──────────────────┐                 │
│  │WorkflowRegistry │    │  Registered Tools │                 │
│  │ (loads .md)     │    │  (internet.research│                │
│  └─────────────────┘    │   memory.*, etc)  │                 │
│                          └──────────────────┘                 │
│                                                               │
│  If no workflow match ──▶ Fall through to Coordinator        │
└──────────────────────────────────────────────────────────────┘
```

---

## Components

### WorkflowRegistry (`libs/gateway/workflow_registry.py`)

Loads workflow definitions from `apps/workflows/` directory.

```python
from libs.gateway.workflow_registry import WorkflowRegistry

registry = WorkflowRegistry()
registry.load_all()  # Loads from apps/workflows/**/*.md

workflow = registry.get("intelligence_search")
workflows = registry.get_by_intent("live_search")
```

**Features:**
- Parses YAML frontmatter from markdown files
- Indexes by intent and trigger patterns
- Tracks bootstrap vs user-created workflows

### WorkflowMatcher (`libs/gateway/workflow_matcher.py`)

Matches commands to workflows using multiple strategies.

```python
from libs.gateway.workflow_matcher import WorkflowMatcher

matcher = WorkflowMatcher(registry)
match = matcher.match(command, context_doc)

if match and match.confidence > 0.7:
    # Execute the workflow
```

**Matching Strategies (in order):**
1. Intent-based (from Phase 0 `action_needed`)
2. Trigger pattern matching
3. Semantic similarity (LLM-based)
4. Keyword fallback

### WorkflowExecutor (`libs/gateway/workflow_executor.py`)

Executes workflow steps with template interpolation.

```python
from libs.gateway.workflow_executor import WorkflowExecutor

executor = WorkflowExecutor(registry)
executor.register_tool("internet.research", research_func)

result = await executor.execute(
    workflow=workflow,
    inputs={"goal": "find cheap laptops"},
    context_doc=context_doc,
    turn_dir=turn_dir
)
```

---

## Workflow Definition Format

Workflows are markdown files with YAML frontmatter in `apps/workflows/`:

```markdown
---
name: intelligence_search
version: "1.0"
category: research
description: >
  Execute Phase 1 informational research for general queries.

triggers:
  - intent: informational
  - intent: live_search
  - "research {topic}"
  - "find information about {topic}"

inputs:
  goal:
    type: string
    required: true
    from: original_query
    description: "The research goal"

outputs:
  intelligence:
    type: object
    description: "Research findings"

steps:
  - name: execute_research
    tool: internal://internet_research.execute_research
    args:
      goal: "{{goal}}"
      intent: "informational"
    outputs: [intelligence, findings]

success_criteria:
  - "findings is not empty"

fallback:
  workflow: null
  message: "Could not gather information."
---

## Intelligence Search Workflow

Documentation for the workflow goes here.
```

---

## Trigger Types

| Type | Format | Example |
|------|--------|---------|
| Intent | `intent: [value]` | `intent: commerce` |
| Pattern | `"[pattern with {vars}]"` | `"find {product} for sale"` |
| Literal | `"[exact match]"` | `"search products"` |

**Intent values from Phase 0:**
- `live_search` - Needs web research
- `commerce` / `transactional` - Product search
- `informational` - General research
- `navigate_to_site` - Visit specific site
- `recall_memory` - Check stored data
- `answer_from_context` - Can answer from context

---

## Built-in Workflows

### intelligence_search (`apps/workflows/research/intelligence_search.md`)

Wraps Phase 1 informational research.

**Triggers:** `informational`, `live_search`, pattern matches
**Tool:** `internet.research` with `mode=informational`

### product_search (`apps/workflows/research/product_search.md`)

Wraps Phase 1 + Phase 2 commerce research.

**Triggers:** `commerce`, `transactional`, pattern matches
**Tool:** `internet.research` with `mode=commerce`
**Fallback:** `intelligence_search` if no products found

### create_workflow (`apps/workflows/meta/create_workflow.md`)

Meta-workflow for self-creating new workflows.

**Limitation:** Cannot create workflows requiring bootstrap tools.

---

## Integration with Pipeline

In `libs/gateway/unified_flow.py`, the Executor loop tries workflows first:

```python
async def _phase4_executor_loop(self, context_doc, turn_dir, mode):
    while True:
        decision = await self._call_executor(context_doc, turn_dir, mode)

        if decision.action == "COMMAND":
            # Try workflow first
            result = await self._try_workflow_execution(
                command, context_doc, turn_dir
            )

            if result is None:
                # No workflow match, fall through to Coordinator
                result = await self._coordinator_execute_command(...)

        elif decision.action == "COMPLETE":
            break
```

---

## Bootstrap Tools

These tools cannot be self-created by the workflow system:

| Tool | Reason |
|------|--------|
| `bootstrap://file_io.read` | Required to read workflow files |
| `bootstrap://file_io.write` | Required to write workflow files |
| `bootstrap://code_execution.run` | Requires system-level access |

Workflows requiring these tools must be manually created.

---

## Forgiving Parser

The workflow system uses a forgiving parser (`libs/gateway/forgiving_parser.py`) that never fails on parse errors:

```python
from libs.gateway.forgiving_parser import ForgivingParser

parser = ForgivingParser()
result = parser.parse(llm_output, expected_schema)

# Always returns something usable
print(result.parsed_data)  # Parsed or default values
print(result.strategy_used)  # "json", "repair", "semantic", "default"
```

**Parse Strategies (in order):**
1. Direct JSON parse
2. JSON repair (fix quotes, trailing commas)
3. Semantic extraction (regex patterns)
4. Sensible defaults

---

## Directory Structure

```
apps/workflows/
├── README.md
├── research/
│   ├── intelligence_search.md
│   └── product_search.md
└── meta/
    └── create_workflow.md

libs/gateway/
├── workflow_registry.py
├── workflow_matcher.py
├── workflow_executor.py
└── forgiving_parser.py
```

---

## Adding a New Workflow

1. Create markdown file in `apps/workflows/[category]/[name].md`
2. Define YAML frontmatter with triggers, inputs, outputs, steps
3. Registry auto-loads on startup
4. Test with: `python -c "from libs.gateway.workflow_registry import WorkflowRegistry; r = WorkflowRegistry(); r.load_all(); print(r.get('[name]'))"`

---

## References

- `libs/gateway/workflow_registry.py` - Registry implementation
- `libs/gateway/workflow_matcher.py` - Matching implementation
- `libs/gateway/workflow_executor.py` - Execution implementation
- `apps/workflows/` - Workflow definitions
