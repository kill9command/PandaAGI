# DEBUG.md - Mandatory Debugging Protocol

**THIS PROTOCOL IS NON-NEGOTIABLE. VIOLATIONS WILL CAUSE CASCADING FAILURES.**

---

## The Golden Rule

```
INVESTIGATE → ANALYZE → DESIGN → IMPLEMENT → VERIFY
     ↑                                            |
     └────────── NEVER SKIP STEPS ────────────────┘
```

**You MUST complete each phase before moving to the next. No exceptions.**

---

## Phase 1: CATEGORIZE (Before Anything Else)

When a bug is reported or discovered, IMMEDIATELY classify it:

| Category | Symptoms | Primary Files |
|----------|----------|---------------|
| **STARTUP** | Services won't start, connection errors | `scripts/start.sh`, `logs/panda/*.log` |
| **PIPELINE** | Wrong output, no output, hangs | `libs/gateway/unified_flow.py` |
| **PHASE0** | Wrong intent, bad classification | `apps/services/gateway/`, `apps/recipes/recipes/intent_*.yaml` |
| **PHASE1** | Wrong PROCEED/CLARIFY decision | `apps/prompts/reflection/`, `libs/gateway/unified_flow.py` |
| **PHASE2** | Missing context, wrong recall | `apps/services/gateway/`, context gathering code |
| **PHASE3** | Bad plan, wrong route | `apps/prompts/pipeline/`, planner recipes |
| **PHASE4** | Tool failures, wrong execution | `apps/services/orchestrator/*_mcp.py` |
| **PHASE5** | Bad synthesis, wrong response | `apps/prompts/pipeline/`, synthesis code |
| **PHASE6** | Wrong validation decision | `apps/prompts/reflection/`, validation code |
| **PHASE7** | Failed save, index issues | `libs/gateway/`, turn save code |
| **MEMORY** | Wrong recall, failed save | `apps/services/`, memory system |
| **TOOL** | Specific MCP tool broken | `apps/services/orchestrator/*_mcp.py` |
| **RESEARCH** | Research flow issues | `apps/services/orchestrator/internet_research_mcp.py` |

**State the category before proceeding.**

---

## Agent-Based Debugging Workflow

For complex issues, use specialized agents to debug:

```
1. SPAWN DEBUG AGENT
   - Agent investigates logs, turns, code
   - Agent proposes root cause and fix direction

2. VERIFY ANALYSIS
   - Review agent's findings
   - Confirm alignment with architecture specs

3. APPROVE FIX
   - If aligned: approve implementation
   - If not aligned: guide agent to correct approach

4. AGENT IMPLEMENTS
   - Agent makes minimal fix
   - Agent runs verification

5. VERIFY FIX
   - Review changes
   - Run regression tests
```

**When to use agents:** Complex issues spanning multiple files, format mismatches, prompt/code alignment issues.

---

## Phase 2: INVESTIGATE (NO CODE CHANGES)

### Step 2.1: Reproduce the Bug

```bash
# Test via the UI or API
curl -X POST http://localhost:9000/chat -H "Content-Type: application/json" \
  -d '{"message": "the failing query"}'
```

### Step 2.2: Check System Log First

The system log shows all turns with phase timing in one place:

```bash
# View recent activity (quick overview)
tail -100 logs/panda/system.log

# Search for specific trace/turn
grep "trace_id" logs/panda/system.log

# Follow live during testing
tail -f logs/panda/system.log

# View domain events (turns, phases)
tail -f logs/panda/latest.log

# Watch both simultaneously
tail -f logs/panda/system.log logs/panda/latest.log
```

### Step 2.3: Locate the Turn Directory

```bash
# Find the turn directory
ls -lt panda_system_docs/users/default/turns/ | head -5
```

### Step 2.4: Read ALL Phase Outputs

**YOU MUST READ EVERY FILE. NO SKIPPING.**

```bash
TURN_DIR="panda_system_docs/users/default/turns/turn_XXXXXX"

# Read the context.md (main document with all phase sections)
cat "$TURN_DIR/context.md"

# Check for any debug or error logs
ls -la "$TURN_DIR/"
```

The context.md has sections for each phase:
- §1: Reflection (PROCEED/CLARIFY decision)
- §2: Context (gathered context)
- §3: Plan (task planning)
- §4: Execution (tool execution results)
- §5: Synthesis (final response)
- §6: Validation (APPROVE/REVISE/RETRY/FAIL)

### Step 2.5: Identify the Break Point

Answer these questions IN ORDER:

1. **Which phase produced the first unexpected output?**
2. **Was the INPUT to that phase correct?**
3. **Is the issue in the PROMPT or the CODE?**

**STOP. Report findings. Do not proceed to fixes.**

---

## Phase 3: ROOT CAUSE ANALYSIS

Use this decision tree:

```
                    ┌─────────────────────────┐
                    │ Is the LLM output wrong?│
                    └───────────┬─────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              ▼                                   ▼
        YES (LLM issue)                    NO (Code issue)
              │                                   │
              ▼                                   ▼
    ┌─────────────────────┐           ┌─────────────────────┐
    │ Is the prompt clear │           │ Where did code fail?│
    │ and complete?       │           └──────────┬──────────┘
    └──────────┬──────────┘                      │
               │                    ┌────────────┼────────────┐
        ┌──────┴──────┐             ▼            ▼            ▼
        ▼             ▼          Parsing      Routing      Tool Exec
   NO: Prompt    YES: Check      Issue        Issue        Issue
   Issue         Context         │            │            │
        │             │          ▼            ▼            ▼
        ▼             ▼      libs/gateway/  unified_    apps/services/
   apps/prompts/  context     unified_      flow.py     orchestrator/
   {phase}/*.md   gathering   flow.py                   *_mcp.py
```

### Root Cause Report Format

```markdown
## Root Cause

**Category:** [from Phase 1]
**Break Point:** [phase name]
**Type:** [PROMPT | CODE | CONTEXT | TOOL | INTEGRATION]
**Location:** [file:function or file:line]
**Explanation:** [1-2 sentences on WHY it fails]
```

---

## Phase 4: IMPACT ANALYSIS (Before ANY Change)

**THIS PHASE IS MANDATORY. SKIPPING IT CAUSES REGRESSION BUGS.**

### Step 4.1: Identify What You Plan to Change

| File | Function/Section | Change Type |
|------|------------------|-------------|
| `path/to/file.py` | `function_name` | [ADD\|MODIFY\|DELETE] |

### Step 4.2: Find All Callers/Importers

```bash
# For Python files
grep -r "from libs.MODULE import" --include="*.py"
grep -r "import libs.MODULE" --include="*.py"
grep -r "function_name" --include="*.py"

# For prompt files
grep -r "SECTION_NAME" apps/prompts/
```

### Step 4.3: Assess Risk

| Risk Factor | Check |
|-------------|-------|
| Changes document format? | If YES → All downstream phases affected |
| Changes function signature? | If YES → All callers must be updated |
| Changes routing logic? | If YES → All route types must be tested |
| Changes prompt structure? | If YES → LLM behavior may change unpredictably |

### Step 4.4: List Regression Tests

```markdown
## Regression Tests Required

Before merging, these queries MUST still work:
1. [Simple direct query] - Tests: direct route
2. [Research query] - Tests: tool route
3. [Memory recall query] - Tests: context gather
4. [Multi-step query] - Tests: workflow route
```

---

## Phase 5: DESIGN THE FIX

### For Prompt Changes

```markdown
## Proposed Prompt Change

**File:** apps/prompts/{phase}/{file}.md

**Current:**
```
[quote exact current text]
```

**Proposed:**
```
[show new text]
```

**Rationale:** [why this fixes the issue]

**Risk:** [what could break]
```

### For Code Changes

```markdown
## Proposed Code Change

**File:** libs/gateway/{file}.py or apps/services/orchestrator/{file}.py
**Function:** {function_name}

**Architecture Reference:**
> [Quote from architecture/*.md that governs this code]

**Current Code:**
```python
[quote exact current code]
```

**Proposed Code:**
```python
[show new code]
```

**Rationale:** [why this fixes the issue]

**Callers Affected:** [list them]
```

**STOP. Get approval before implementing.**

---

## Phase 6: IMPLEMENT

Only after Phases 1-5 are complete:

1. Make the minimal change described in Phase 5
2. Do NOT add "improvements" or "while I'm here" changes
3. Do NOT refactor surrounding code
4. Do NOT add comments to unchanged code

---

## Phase 7: VERIFY

### Step 7.1: Test the Original Bug

```bash
# Test via API
curl -X POST http://localhost:9000/chat -H "Content-Type: application/json" \
  -d '{"message": "the original failing query"}'
# Confirm it now works
```

### Step 7.2: Run Regression Tests

```bash
# Test queries identified in Phase 4
# Run any relevant test scripts
python scripts/test_intent_classification.py
python scripts/test_code_operations.py
```

### Step 7.3: Verify Imports

```bash
python -c "from libs.gateway.unified_flow import UnifiedFlow; print('OK')"
python -c "from apps.services.gateway.app import app; print('OK')"
```

### Step 7.4: Report Results

```markdown
## Verification Results

- [ ] Original bug fixed: [YES/NO]
- [ ] Regression test 1: [PASS/FAIL]
- [ ] Regression test 2: [PASS/FAIL]
- [ ] Imports clean: [YES/NO]
```

---

## Bug Report Template

Use this template for every bug:

```markdown
# Bug: [Short Title]

## Symptoms
- What happened:
- Expected behavior:
- Query that triggered it:

## Category
[STARTUP | PIPELINE | PHASE0-7 | MEMORY | TOOL | RESEARCH]

## Turn Location
`panda_system_docs/users/{user}/turns/turn_XXXXXX/`

## Investigation Findings

### Phase Outputs
- PHASE0 (Query Analyzer): [correct/incorrect - brief description]
- PHASE1 (Reflection): [correct/incorrect - brief description]
- PHASE2 (Context Gatherer): [correct/incorrect - brief description]
- PHASE3 (Planner): [correct/incorrect - brief description]
- PHASE4 (Coordinator): [correct/incorrect - brief description]
- PHASE5 (Synthesis): [correct/incorrect - brief description]
- PHASE6 (Validation): [correct/incorrect - brief description]
- PHASE7 (Save): [correct/incorrect - brief description]

### Break Point
Phase: [name]
Input was: [correct/incorrect]
Output was: [describe what was wrong]

## Root Cause
**Type:** [PROMPT | CODE | CONTEXT | TOOL | INTEGRATION]
**Location:** [file:function]
**Explanation:** [why it fails]

## Impact Analysis
**Files to change:** [list]
**Callers affected:** [list]
**Risk level:** [HIGH | MEDIUM | LOW]
**Regression tests:** [list queries]

## Proposed Fix
[describe or show code/prompt change]

## Verification
- [ ] Original bug fixed
- [ ] Regression tests pass

## Status
[INVESTIGATING | ANALYZED | DESIGNED | IMPLEMENTED | VERIFIED | CLOSED]
```

---

## Quick Debug Commands

```bash
# Check service status
./scripts/health_check.sh

# View system log (all services)
tail -100 logs/panda/system.log

# Follow system log live
tail -f logs/panda/system.log

# View domain events (turns, phases)
tail -f logs/panda/latest.log

# Find latest turn
ls -t panda_system_docs/users/default/turns/ | head -1

# Read latest context.md
LATEST=$(ls -t panda_system_docs/users/default/turns/ | head -1)
cat "panda_system_docs/users/default/turns/$LATEST/context.md"

# Run quick import test
python -c "from libs.gateway.unified_flow import UnifiedFlow; from apps.services.gateway.app import app; print('All imports OK')"

# Restart services
./scripts/stop.sh && sleep 2 && ./scripts/start.sh
```

---

## What NOT To Do

1. **DO NOT** make changes while investigating
2. **DO NOT** fix multiple bugs in one change
3. **DO NOT** skip reading phase outputs
4. **DO NOT** assume you know the root cause
5. **DO NOT** add "improvements" while fixing bugs
6. **DO NOT** change code without quoting the architecture spec
7. **DO NOT** skip verification
8. **DO NOT** skip regression tests

---

## Documentation & Prompt Design Principles

When editing documentation, architecture specs, or LLM prompts:

### Use Abstract Patterns, Not Real Examples

**DO NOT** use specific real-world examples like:
- Product names: "MacBook Pro", "HP Pavilion", "Dell XPS"
- Websites: "reef2reef.com", "amazon.com"
- Topics: "Syrian hamsters", "Bitcoin price"
- Brands: "HP", "Apple", "Samsung"

**DO** use abstract placeholder patterns:
- `[product]`, `[product type]`, `[brand]`
- `[website]`, `[domain]`, `[url]`
- `[topic]`, `[preference]`, `[entity]`
- `[price]`, `[budget]`, `[amount]`

### Why This Matters

1. **Prompt pollution** - Real examples in prompts bias the LLM toward those specific cases
2. **Pattern learning** - Abstract patterns teach the LLM to generalize, not memorize
3. **Maintenance** - Real examples become outdated (prices change, products discontinued)
4. **Testing** - Hard to know if LLM is following the pattern or just recognizing the example

### Example

**Wrong:**
```markdown
NEED: Find the current price of Bitcoin
NEED: Fetch trending topics from reef2reef.com
NEED: Find laptops under $1000, preferably HP
```

**Correct:**
```markdown
NEED: Find the current [time-sensitive data type]
NEED: Fetch [content type] from [website]
NEED: Find [product type] under [budget], preferably [brand]
```

### Files That Follow This Pattern

- `architecture/main-system-patterns/*.md` - Phase documentation
- `apps/prompts/**/*.md` - LLM prompt templates
- `apps/recipes/recipes/*.yaml` - Recipe definitions

### Files That May Have Real Data (Expected)

- `panda_system_docs/users/*/turns/*` - Actual user conversation data
- `transcripts/*` - Actual conversation transcripts

---

## Escalation

If after following this protocol you cannot identify the root cause:

1. Document everything you've tried
2. List the files you've read
3. State your hypotheses and why each was ruled out
4. Ask for help with specific questions
