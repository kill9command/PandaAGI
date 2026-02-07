# V2 Prompt Style Guide

Version: 1.0
Updated: 2026-02-02

---

## Overview

V2 prompts are concise, abstract, and table-driven. This style reduces token usage while maintaining clarity and preventing the LLM from overfitting to specific examples.

**Core Principles:**
1. Abstract over concrete
2. Tables over prose
3. 2-3 examples max
4. Role is implicit (defined in recipe YAML)
5. Anti-patterns explicit ("Do NOT" section)
6. 150 lines target

---

## Concrete vs Abstract Examples

### The Problem

Concrete examples cause the LLM to pattern-match specific values instead of learning the underlying concept:

```markdown
# BAD - Concrete examples
## Example 1: Gaming Laptop Search

**Query:** "cheapest gaming laptop with RTX 4060 under $1000"

**Analysis:**
- Intent: transactional (user wants to buy)
- Product: gaming laptop
- GPU: RTX 4060
- Budget: under $1000
- Priority: cheapest (price-focused)
```

This teaches the LLM to look for "RTX 4060" and "$1000", not the general pattern.

### The Solution

Use placeholders that teach the pattern:

```markdown
# GOOD - Abstract examples
## Example: Product Search

**Query:** `[adjective] [product] with [spec] under [budget]`

| Field | Value | Extracted From |
|-------|-------|----------------|
| intent | transactional | "[adjective]" = buying |
| priority | price | "cheapest" |
| budget | [number] | "under [X]" |
```

---

## Placeholder Reference

| Concrete | Abstract Placeholder |
|----------|---------------------|
| `RTX 4060`, `RTX 4070`, `RTX 5090` | `[GPU]`, `[spec]` |
| `Lenovo LOQ 15`, `ASUS TUF Gaming` | `[brand] [model]`, `[product]` |
| `$699`, `$799`, `$999`, `$1,299` | `[price]`, `$[N]`, `$XXX` |
| `hamsters`, `Syrian hamsters` | `[item]`, `[animal]` |
| `Best Buy`, `Newegg`, `Amazon` | `[retailer]`, `[vendor]` |
| `16GB RAM`, `512GB SSD` | `[spec]` |
| `gaming laptop` | `[product category]` |
| `auth.py`, `user_service.py` | `[file]`, `[module]` |
| `login()`, `validate()` | `[function]`, `[method]` |

---

## Structure: Tables Over Prose

### Before (Prose)

```markdown
When the user asks for the cheapest option, you should set the priority
field to "price". When they ask for the best option, set it to "quality".
If they mention a budget constraint like "under $500", extract that as
the max_budget field. Navigation intents are when users want to go to
a specific website...
```

### After (Table)

```markdown
| Keyword | Field | Value |
|---------|-------|-------|
| "cheapest" | priority | price |
| "best" | priority | quality |
| "under $[N]" | max_budget | [N] |
| "go to [site]" | intent | navigation |
```

---

## Example Count

**Rule:** Maximum 2-3 examples per concept.

### Before (8 examples)

```markdown
### Example 1: Gaming Laptop
### Example 2: Budget Laptop
### Example 3: Workstation Laptop
### Example 4: Hamster Search
### Example 5: Pet Food
### Example 6: Navigation
### Example 7: Follow-up
### Example 8: Recall
```

### After (3 examples)

```markdown
### Example 1: Product Search
### Example 2: Follow-up Query
### Example 3: Recall Query
```

Each example should demonstrate a **different pattern**, not the same pattern with different products.

---

## Role Headers

**Remove from prompts.** Role and temperature belong in recipe YAML.

### Before

```markdown
# Phase 3: Strategic Planner

**Role:** MIND (temp=0.6)
**Reads:** sections 0, 1, 2
**Writes:** section 3
```

### After

```markdown
# Phase 3: Strategic Planner

You define **strategic goals**. The Executor handles tactical execution.
```

Role configuration lives in `apps/recipes/recipes/[phase].yaml`:

```yaml
role: mind
temperature: 0.5
```

---

## Anti-Patterns Section

Every prompt should end with explicit "Do NOT" guidance:

```markdown
## Do NOT

- Invent products not in evidence
- Show raw URLs (use markdown links)
- Skip verification section after changes
- Specify tools in goals (Executor's job)
- Claim success without evidence in section 4
```

This prevents common mistakes more effectively than positive examples.

---

## Output Schema

Always include the exact JSON schema expected:

```markdown
## Output Schema

```json
{
  "_type": "STRATEGIC_PLAN",
  "route_to": "executor | synthesis | clarify",
  "goals": [
    {"id": "GOAL_1", "description": "[outcome]", "priority": "high|medium|low"}
  ],
  "reason": "[routing rationale]"
}
```
```

Use `|` for enums, `[placeholder]` for dynamic values.

---

## Line Count Targets

| Category | Target Lines |
|----------|-------------|
| Phase prompts | 150-200 |
| Tool prompts | 100-150 |
| Reflection prompts | 100-150 |
| Helper prompts | 50-100 |

---

## Checklist for V2 Compliance

- [ ] No concrete product names, brands, or prices
- [ ] Uses `[placeholder]` syntax for examples
- [ ] Tables for decision logic
- [ ] 2-3 examples maximum
- [ ] No role/temperature header (in recipe)
- [ ] Has "Do NOT" section
- [ ] Has output schema
- [ ] Under 200 lines

---

## Validation

Check for concrete examples:

```bash
grep -rn "RTX\|Lenovo\|ASUS\|hamster\|\$699\|\$799" apps/prompts --include="*.md" | grep -v archive
```

Count lines:

```bash
wc -l apps/prompts/pipeline/*.md | sort -n
```

---

## Migration Example

### Before (V1 Style - 446 lines)

```markdown
# Phase 0: Query Analyzer

**Role:** REFLEX (temp=0.4)

## Example 1: Gaming Laptop Search

**Query:** "cheapest gaming laptop with RTX 4060 under $1000"

**Analysis:**
- Intent: transactional
- Product: gaming laptop
- GPU: RTX 4060
- Budget: under $1000

## Example 2: Hamster Search
...
[8 more detailed examples]
```

### After (V2 Style - 187 lines)

```markdown
# Phase 0: Query Analyzer

Classify action needed, capture user purpose, resolve references.

## Output Schema
```json
{"action_needed": "live_search | recall_memory | ...", ...}
```

## Decision Table
| Query Pattern | action_needed |
|---------------|---------------|
| "[adjective] [product]" | live_search |
| "what's my [preference]" | recall_memory |

## Example: Commerce Query
**Query:** `[adjective] [product] with [feature]`
| Field | Value | Source |
|-------|-------|--------|
| action_needed | live_search | needs prices |

## Do NOT
- Include concrete product names in reasoning
- Set needs_current_prices for informational queries
```

---

## References

- `PROMPT_CLEANUP_PLAN.md` - Original migration checklist
- `apps/prompts/` - Updated prompts
- `apps/recipes/` - Recipe definitions
