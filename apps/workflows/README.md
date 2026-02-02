# Pandora Workflow System

Workflows are self-documenting markdown files that define predictable tool sequences.
Instead of the Coordinator making ad-hoc tool decisions, workflows define what tools
to call and in what order.

## Directory Structure

```
apps/workflows/
├── README.md               # This file
├── research/               # Research workflows
│   ├── intelligence_search.md   # Phase 1 informational research
│   └── product_search.md        # Phase 1 + Phase 2 commerce research
├── meta/                   # Meta-workflows
│   └── create_workflow.md       # Self-creating workflow system
└── _bootstrap/             # Bootstrap tools (cannot be self-created)
    ├── file_io.md              # File read/write primitive
    └── code_execution.md       # Code execution primitive
```

## Workflow Format

Workflows are markdown files with YAML frontmatter:

```yaml
---
name: workflow_name
version: "1.0"
category: research | memory | file | meta
description: >
  What this workflow does.

triggers:
  - intent: commerce            # Match by Phase 0 intent
  - "find me {product}"         # Match by pattern
  - "buy {product}"             # Multiple triggers allowed

inputs:
  goal:
    type: string
    required: true
    from: original_query        # Source: original_query, section_N
    description: "User's query"

outputs:
  products:
    type: array
    description: "Products found"

steps:
  - name: step_name
    tool: internal://module.function
    args:
      param: "{{goal}}"         # Template interpolation
    outputs: [products]

success_criteria:
  - "products is not empty"

fallback:
  workflow: alternative_workflow
  message: "Fallback message if this fails"
---

## Human-Readable Documentation

Rest of the file is documentation for humans.
```

## How Workflows Are Matched

1. **Intent Match**: Phase 0 determines intent (commerce, informational)
   - Workflows with `intent: commerce` trigger match commerce queries
   - High confidence (0.9)

2. **Pattern Match**: Natural language patterns
   - `"find me {product}"` extracts `product` parameter
   - Confidence 0.85

3. **Keyword Match**: Fallback keyword detection
   - "buy", "price", "cheapest" → product_search
   - "research", "what", "how" → intelligence_search
   - Lower confidence (0.6)

## Tool URIs

Workflows reference tools by URI:

- `internal://internet_research.execute_research` - Phase 1 research
- `internal://internet_research.execute_full_research` - Full commerce research
- `internal://memory.save` - Save to memory
- `internal://llm.call` - Direct LLM call
- `bootstrap://file_io.write` - Bootstrap file write

## Template Interpolation

Args support `{{variable}}` interpolation:

```yaml
args:
  goal: "{{goal}}"                              # Simple variable
  intent: "{{context.intent | default: 'informational'}}"  # With default
  task: "{{task | default: ''}}"               # Empty string default
```

## Success Criteria

Expressions evaluated against outputs:

```yaml
success_criteria:
  - "products is not empty"           # Array has items
  - "products.length >= 1"            # Comparison
  - "confidence > 0.8"                # Numeric comparison
  - "A OR B"                          # Disjunction
  - "A AND B"                         # Conjunction
  - "intelligence.key_facts exists"   # Nested path
```

## Fallback Behavior

When success criteria fail:

```yaml
fallback:
  workflow: intelligence_search    # Try this workflow instead
  message: "Fallback message"      # Or return this message
```

If `workflow` is null, just returns the message with any partial outputs.

## Creating New Workflows

1. Create a new `.md` file in the appropriate category directory
2. Add YAML frontmatter with required fields
3. Define inputs, outputs, steps, and success criteria
4. Add human-readable documentation
5. Workflows are loaded automatically on startup

## Self-Creating Workflows

The `meta/create_workflow.md` workflow can create new workflows, but cannot
create workflows that depend on bootstrap tools (`file_io`, `code_execution`).

## Integration

Workflows integrate at the Executor level (Phase 4):

1. Executor receives command from Planner
2. WorkflowMatcher tries to match command to workflow
3. If match (confidence > 0.7): WorkflowExecutor runs workflow
4. If no match: Falls through to Coordinator for ad-hoc tool selection

This preserves backward compatibility - existing tool calls still work.
