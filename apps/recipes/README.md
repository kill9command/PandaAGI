# Recipe System

**Version:** v4.0-document-driven
**Purpose:** Define role I/O contracts via YAML recipes

## Overview

Recipes define exactly what each role can read and write, with hard token budgets enforced by the Doc Pack Builder.

## Recipe Schema

```yaml
name: str                    # Unique recipe identifier
role: str                    # guide | coordinator | context_manager | system
phase: str (optional)        # strategic | synthesis (for guide)
mode: str (optional)         # chat | code (if mode-specific)

prompt_fragments: List[str]  # Ordered list of prompt files to load
  # Format: prompts/{role}/{fragment}.md
  # Token count validated against budget

input_docs: List[str]        # Required and optional input documents
  # Format: {doc_name}.{ext}
  # Supports: (optional), (max N tokens) annotations
  # Example: "unified_context.md (max 500 tokens)"

output_docs: List[str]       # Documents this role will create
  # All outputs must be listed, no hidden artifacts

token_budget:                # Hard limits enforced by doc pack builder
  total: int                 # Maximum tokens for this recipe
  prompt: int                # Fixed cost of prompt fragments
  input_docs: int            # Budget for input documents
  output: int                # Expected output size
  buffer: int                # Safety margin

trimming_strategy:           # How to trim if budget exceeded
  method: str                # truncate_end | drop_oldest | summarize
  field: str (optional)      # Field to apply strategy to
  target: int (optional)     # Target token count

output_schema: str (optional)  # Reference to schema in io_contracts.md
  # TICKET, PLAN, CAPSULE, etc.
```

## Available Recipes

### Guide Recipes
- `guide_strategic_chat.yaml` - Chat mode delegation
- `guide_strategic_code.yaml` - Code mode planning
- `guide_synthesis_chat.yaml` - Chat mode responses
- `guide_synthesis_code.yaml` - Code mode responses

### Coordinator Recipes
- `coordinator_chat.yaml` - Research, commerce, memory ops
- `coordinator_code.yaml` - Chat tools + file ops, git, bash

### Context Manager Recipe
- `context_manager.yaml` - Evidence evaluation (unified for both modes)

### System Recipes
- `context_gathering.yaml` - Unified context assembly
- `meta_reflection.yaml` - Gate decision
- `cache_evaluation.yaml` - Cache layer checks
- `archivist.yaml` - Turn finalization

## Recipe Selection

```python
from gateway.recipe_loader import load_recipe

# Select by role, mode, phase
recipe = load_recipe("guide_strategic_chat")
recipe = load_recipe("coordinator_code")
recipe = load_recipe("context_manager")  # No mode suffix (unified)
```

## Token Budget Enforcement

The Doc Pack Builder enforces hard limits:
1. Load prompt fragments (fixed cost)
2. Allocate budgets across input docs
3. Load and trim docs to fit budget
4. Apply emergency trimming if needed
5. Reserve output budget

**Guarantee:** Never exceeds `token_budget.total`

## Creating New Recipes

1. Copy template from existing recipe
2. Update `prompt_fragments` (reference existing prompts)
3. Define `input_docs` (from turn directory)
4. Set `token_budget` (measure with `scripts/measure_actual_prompts.py`)
5. Choose `trimming_strategy`
6. Test with Doc Pack Builder

## Validation

Run recipe validator:
```bash
python scripts/validate_recipes.py
```

Checks:
- All prompt fragments exist
- Token budgets sum correctly
- Input docs have valid annotations
- Output schemas reference valid contracts
