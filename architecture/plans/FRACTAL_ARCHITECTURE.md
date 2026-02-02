# Fractal Architecture Plan

**Status:** VISION
**Created:** 2026-01-27
**Goal:** Design a self-similar, bootstrappable AI system with minimal instruction overhead

---

## 1. Core Insight

The same pattern that works at the system level should work at every level:
- System orchestrating phases
- Phase orchestrating tools
- Tool orchestrating operations
- Operation orchestrating sub-operations

**If the pattern works, repeat it. Don't invent new patterns for new scales.**

---

## 2. The Problem with Current Approaches

### 2.1 Moltbot/Clawdbot Pattern

```
while not done:
    response = llm(context)
    if response.has_tools:
        execute_tools()
    else:
        done = True
```

**Issues:**
- No validation (trusts model output)
- No structured reasoning (hopes model thinks)
- No quality gates (outputs whatever)
- Not actually local (calls cloud APIs)

### 2.2 Verbose Instruction Pattern

```
System prompt: 2000 tokens explaining all phases, all rules, all edge cases
```

**Issues:**
- Consumes context budget with instructions
- Local models (30B) struggle with long prompts
- Instructions compete with actual work context
- Repetition at every level = bloat explosion

### 2.3 Current Pandora (v1)

8 phases, document-based IO, validation gates - **the pattern works**.

But:
- Each phase has its own prompt structure
- Tools don't follow the same pattern internally
- Instructions are loaded upfront, not on demand
- Not self-similar across levels

---

## 3. The Fractal Pattern

### 3.1 Core Loop (The Atom)

Every level of the system follows the same 4-phase micro-loop:

```
UNDERSTAND → PLAN → DO → CHECK → (loop or exit)
```

Expanded:

| Phase | Purpose | Gate |
|-------|---------|------|
| UNDERSTAND | What is the task? What context do I have? | - |
| PLAN | How do I approach this? Am I confident? | PROCEED or CLARIFY |
| DO | Execute the plan (may invoke child loops) | - |
| CHECK | Did it work? Is it correct? | ACCEPT, RETRY, or ESCALATE |

### 3.2 Applied Fractally

```
SYSTEM LEVEL (orchestrating a user request):
├── UNDERSTAND: Parse query, gather context
├── PLAN: Decide approach, select tools
├── DO: Execute tools ──────────────────────────────┐
│                                                    │
│   TOOL LEVEL (e.g., research tool):               │
│   ├── UNDERSTAND: What am I researching?          │
│   ├── PLAN: Search strategy                       │
│   ├── DO: Execute searches ───────────────────┐   │
│   │                                            │   │
│   │   OPERATION LEVEL (e.g., web fetch):      │   │
│   │   ├── UNDERSTAND: What URL? What to get?  │   │
│   │   ├── PLAN: Request strategy              │   │
│   │   ├── DO: HTTP request                    │   │
│   │   └── CHECK: Valid response?              │   │
│   │                                            │   │
│   └── CHECK: Good results? Retry?         ────┘   │
│                                                    │
└── CHECK: Quality? Complete? ──────────────────────┘
```

### 3.3 The Constraint: Context Budget

Local LLM (Qwen3-30B): ~8k effective context
Cloud LLMs: 100k+ but costly

**Every instruction token costs.** Verbose patterns are unusable at local scale.

---

## 4. Progressive Document Discovery

### 4.1 The Idea

Don't load all instructions upfront. Load them **on demand** when entering a phase.

**Traditional approach:**
```
[2000 token system prompt with all instructions]
[Remaining context for actual work]
```

**Progressive approach:**
```
[50 token base prompt: "You follow the pattern at /docs/pattern.md"]
[Load current phase section on demand: ~100 tokens]
[Maximum context for actual work]
```

### 4.2 Directory Structure

```
/system/
├── pattern.md              # Core loop definition (read section by section)
├── phases/
│   ├── understand.md       # UNDERSTAND phase details
│   ├── plan.md             # PLAN phase details
│   ├── do.md               # DO phase details
│   └── check.md            # CHECK phase details
├── tools/
│   ├── research/
│   │   └── pattern.md      # Research tool's pattern (same structure)
│   ├── code/
│   │   └── pattern.md      # Code tool's pattern
│   └── web/
│       └── pattern.md      # Web tool's pattern
└── operations/
    ├── fetch.md            # Atomic operation: HTTP fetch
    ├── read.md             # Atomic operation: file read
    └── write.md            # Atomic operation: file write
```

### 4.3 Just-In-Time Loading

```python
def micro_loop(task, level="system", phase="understand"):
    # Load ONLY current phase instructions
    instructions = read(f"/system/phases/{phase}.md")

    # Execute with minimal context
    result = llm(
        system=BASE_PROMPT,  # ~50 tokens
        context=instructions,  # ~100 tokens for current phase
        task=task
    )

    # Transition to next phase (loads new instructions)
    if phase == "understand":
        return micro_loop(result, level, "plan")
    elif phase == "plan":
        if result.confident:
            return micro_loop(result, level, "do")
        else:
            return clarify(result)
    # ... etc
```

### 4.4 Token Budget Per Level

| Level | Base | Phase | Work Context | Total |
|-------|------|-------|--------------|-------|
| System | 50 | 100 | 3000 | 3150 |
| Tool | 50 | 100 | 2000 | 2150 |
| Operation | 50 | 100 | 1000 | 1150 |

Each level gets full instructions but progressively less work context.
**Recursion depth is naturally limited by shrinking context.**

---

## 5. Document-Based IO (Persistent State)

### 5.1 Core Principle

Every loop iteration reads from and writes to documents. State is **explicit and persistent**, not hidden in memory.

### 5.2 State Document Structure

Each loop maintains a state document:

```markdown
# State: {task_id}

## §1 UNDERSTAND
Task: {original task}
Context gathered: {relevant context}
Resolved task: {task with references resolved}

## §2 PLAN
Approach: {chosen approach}
Confidence: {high|medium|low}
Steps: {planned steps}
Rationale: {why this approach}

## §3 DO
Execution log:
- Step 1: {action} → {result}
- Step 2: {action} → {result}
Child loops: {references to child state docs}

## §4 CHECK
Validation: {pass|fail}
Issues: {any problems found}
Decision: {accept|retry|escalate}

## §5 OUTPUT
Final result: {output}
```

### 5.3 Parent-Child Document Relationship

```
/state/
├── system-{id}.md           # System level state
├── tool-research-{id}.md    # Research tool state (child of system)
├── tool-code-{id}.md        # Code tool state (child of system)
├── op-fetch-{id}.md         # Fetch operation state (child of research)
└── op-fetch-{id2}.md        # Another fetch (child of research)
```

Parent document references children:
```markdown
## §3 DO
Child loops:
- /state/tool-research-{id}.md → COMPLETE
- /state/tool-code-{id}.md → IN_PROGRESS
```

Child document references parent:
```markdown
## §0 META
Parent: /state/system-{id}.md
Level: tool
Type: research
```

### 5.4 Benefits

1. **Debuggable**: Inspect any state document to see exactly what happened
2. **Resumable**: If interrupted, resume from persisted state
3. **Auditable**: Full trace of decisions and actions
4. **Cacheable**: Identical tasks can reuse prior state documents

---

## 6. The Minimal Instruction Set

### 6.1 Base Prompt (~50 tokens)

```
You follow the pattern. Your current phase and instructions are provided.
State document: {path}
Read your phase instructions. Update the state document. Proceed or ask.
```

### 6.2 Phase Instructions (~100 tokens each)

**understand.md:**
```
# UNDERSTAND Phase

Read the task. Gather relevant context from:
- State document history
- Referenced files
- Prior conversation

Write to §1:
- Original task
- Gathered context
- Resolved task (references made explicit)

Then proceed to PLAN.
```

**plan.md:**
```
# PLAN Phase

Read §1. Decide approach.

If unclear: Output CLARIFY with question.
If clear: Write to §2:
- Approach
- Confidence (high/medium/low)
- Steps
- Rationale

If confidence < medium: CLARIFY
Else: Proceed to DO.
```

**do.md:**
```
# DO Phase

Read §2. Execute each step.

For each step:
- If simple: Execute directly
- If complex: Spawn child loop

Write to §3:
- Each action and result
- Child loop references

When complete: Proceed to CHECK.
```

**check.md:**
```
# CHECK Phase

Read §2 (plan) and §3 (execution).

Validate:
- Did execution match plan?
- Is result correct?
- Any errors?

Write to §4:
- Validation result
- Issues found
- Decision: ACCEPT / RETRY / ESCALATE

If ACCEPT: Write §5 output, exit.
If RETRY: Return to PLAN with learned context.
If ESCALATE: Return error to parent loop.
```

### 6.3 Total Instruction Overhead

```
Base prompt:           50 tokens
Phase instructions:   100 tokens
State doc read:       ~200 tokens (depends on history)
─────────────────────────────────
Total overhead:       ~350 tokens

Remaining for work:   ~2800 tokens (in 3150 budget)
```

Compare to current: ~2000 tokens of instructions, leaving ~1150 for work.

**Progressive loading doubles usable context.**

---

## 7. Self-Building / Bootstrap

### 7.1 The Kernel

Minimum viable system:

```
LLM + read + write + bash + pattern.md
```

That's it. The system can build everything else.

### 7.2 Bootstrap Sequence

**Day 0: Kernel**
```
/system/
├── pattern.md              # The core loop definition
└── kernel/
    ├── read.md             # How to read files
    ├── write.md            # How to write files
    └── bash.md             # How to run commands
```

**Day 1: Self-Build**
```
User: "Build yourself following the pattern."

System:
1. UNDERSTAND: I need to create the phase infrastructure
2. PLAN: Create understand.md, plan.md, do.md, check.md
3. DO: Write each file following the pattern
4. CHECK: Test by running a simple task through the loop
```

**Day 2: Capability Expansion**
```
User: "Add web research capability."

System:
1. UNDERSTAND: Need a tool for web research
2. PLAN: Create /system/tools/research/pattern.md following core pattern
3. DO: Write tool definition, test with sample query
4. CHECK: Verify research tool follows the fractal pattern
```

**Day N: Continuous Growth**
```
System encounters new need → Spawns new pattern instance
Pattern instance follows same structure → Automatically integrates
No human coding required → System grows itself
```

### 7.3 The Growth Rule

When the system needs a new capability:

1. Create new directory under appropriate level (`tools/`, `operations/`)
2. Copy `pattern.md` template
3. Fill in domain-specific instructions
4. Register with parent level
5. Test with sample task

The system can do all of this itself because it follows the same pattern.

---

## 8. Communication Between Levels

### 8.1 Downward (Parent → Child)

Parent passes:
- Task description
- Relevant context subset
- Constraints (depth limit, timeout, etc.)

```python
child_result = spawn_child_loop(
    task="Search for nvidia laptop reviews",
    context=extract_relevant(parent_context),
    max_depth=current_depth + 1,
    parent_state="/state/system-{id}.md"
)
```

### 8.2 Upward (Child → Parent)

Child returns:
- Result (success output)
- OR Error (with reason)
- OR Escalation (needs parent decision)

```python
# In child's CHECK phase
if cannot_complete:
    return Escalate(
        reason="Need user clarification on budget",
        partial_result=what_we_found,
        question="What's the maximum price?"
    )
```

### 8.3 Sibling Communication

Siblings communicate through shared state in parent document.

```markdown
## §3 DO (parent)
Child loops:
- tool-research-{id}: COMPLETE, found 5 products
- tool-code-{id}: IN_PROGRESS, needs research results

Shared context:
- Research found: [product list]
- Code tool can read above
```

---

## 9. Recursion Limits

### 9.1 Depth Limiting

```python
MAX_DEPTH = 3  # System → Tool → Operation → (no deeper)

def micro_loop(task, depth=0):
    if depth >= MAX_DEPTH:
        # Don't spawn children, execute atomically
        return execute_atomic(task)

    # ... normal loop with possible child spawning
    child = micro_loop(subtask, depth=depth + 1)
```

### 9.2 Context-Based Limiting

Context shrinks at each level. When context is too small for meaningful work, execute atomically.

```python
def micro_loop(task, context_budget):
    MINIMUM_WORK_CONTEXT = 500  # tokens

    if context_budget < MINIMUM_WORK_CONTEXT:
        return execute_atomic(task)

    # Child gets reduced budget
    child_budget = context_budget - OVERHEAD - len(task)
    child = micro_loop(subtask, child_budget)
```

### 9.3 Retry Limiting

```python
MAX_RETRIES = 2

def micro_loop(task, retry_count=0):
    # ... execute loop ...

    if check_result == "RETRY":
        if retry_count >= MAX_RETRIES:
            return Escalate("Max retries exceeded")
        return micro_loop(task_with_learning, retry_count + 1)
```

---

## 10. Mapping to Current Pandora

### 10.1 Current 8 Phases → Fractal 4 Phases

| Current Pandora | Fractal Pattern |
|-----------------|-----------------|
| Phase 0: Query Analysis | UNDERSTAND (part 1) |
| Phase 2: Context Gathering | UNDERSTAND (part 2) |
| Phase 1: Reflection | PLAN (gate) |
| Phase 3: Planning | PLAN (strategy) |
| Phase 4: Coordinator | DO (orchestration) |
| Phase 4: Tool Execution | DO (child loops) |
| Phase 5: Synthesis | DO (output formatting) |
| Phase 6: Validation | CHECK |
| Phase 7: Save | CHECK (side effect) |

### 10.2 Migration Path

**Phase 1: Restructure prompts to match UNDERSTAND/PLAN/DO/CHECK**
- Keep current code, change mental model
- Verify same behavior with new framing

**Phase 2: Implement progressive loading**
- Split monolithic prompts into phase files
- Load on demand instead of upfront
- Measure context savings

**Phase 3: Apply pattern to tools**
- Refactor MCP tools to follow micro_loop internally
- Each tool maintains its own state document
- Tools become fractal instances

**Phase 4: Implement state documents**
- Replace in-memory state with persistent docs
- Add parent/child relationships
- Enable resumption and debugging

**Phase 5: Self-building capabilities**
- Create tool templates
- System can instantiate new tools following pattern
- Test with "build a new capability" requests

---

## 11. Example: Full Trace

User query: "Find the cheapest nvidia laptop"

```
/state/system-abc123.md
─────────────────────────────────────────────────

## §0 META
Level: system
Created: 2026-01-27T10:00:00Z

## §1 UNDERSTAND
Task: Find the cheapest nvidia laptop
Context: No prior conversation
Resolved: Find the cheapest laptop with nvidia GPU, user wants to buy

## §2 PLAN
Approach: Web research for current prices
Confidence: high
Steps:
1. Search for nvidia laptop reviews and prices
2. Extract product information
3. Rank by price
4. Return cheapest options with URLs
Rationale: Commerce query needs live data

## §3 DO
Step 1: Spawned research tool
- Child: /state/tool-research-abc123-1.md → COMPLETE

Step 2-4: Research tool returned results

## §4 CHECK
Validation: PASS
- Found 5 products with prices
- URLs verified working
- Prices are current (< 1 hour old)
Decision: ACCEPT

## §5 OUTPUT
Cheapest nvidia laptops found:
1. MSI Thin 15 - $649 - [url]
2. ASUS TUF Gaming - $699 - [url]
...

─────────────────────────────────────────────────
/state/tool-research-abc123-1.md
─────────────────────────────────────────────────

## §0 META
Level: tool
Type: research
Parent: /state/system-abc123.md

## §1 UNDERSTAND
Task: Search for nvidia laptop reviews and prices
Context: User wants cheapest option
Resolved: Find current nvidia laptop prices from retailers

## §2 PLAN
Approach: Multi-source search
Confidence: high
Steps:
1. Search Google for "nvidia laptop prices 2026"
2. Search retailer sites (Amazon, Newegg, BestBuy)
3. Extract product data from results
Rationale: Multiple sources for price verification

## §3 DO
Step 1: Spawned web fetch
- Child: /state/op-fetch-abc123-1.md → COMPLETE (Google results)

Step 2: Spawned web fetches
- Child: /state/op-fetch-abc123-2.md → COMPLETE (Amazon)
- Child: /state/op-fetch-abc123-3.md → COMPLETE (Newegg)
- Child: /state/op-fetch-abc123-4.md → FAILED (BestBuy blocked)

Step 3: Extracted 8 products from successful fetches

## §4 CHECK
Validation: PASS
- 3/4 fetches succeeded (acceptable)
- Found 8 products with prices
- Data is consistent across sources
Decision: ACCEPT

## §5 OUTPUT
[Product list with prices and URLs]
```

---

## 12. Open Questions

1. **State document format**: Markdown sections or structured JSON?
2. **Child loop spawning**: Synchronous or async with callbacks?
3. **Context inheritance**: How much parent context passes to children?
4. **Pattern evolution**: How does the system improve its own pattern.md?
5. **Error boundaries**: Where do errors get caught vs. propagated?
6. **Caching**: Can identical UNDERSTAND results skip to cached PLAN?

---

## 13. Success Criteria

1. **Same pattern at every level**: System, tool, operation all follow UNDERSTAND→PLAN→DO→CHECK
2. **Minimal instruction overhead**: < 400 tokens total vs current ~2000
3. **Progressive loading works**: Context savings measurable
4. **Self-building demonstrated**: System creates new tool from pattern
5. **State documents debuggable**: Can trace any decision from docs
6. **Recursion bounded**: No infinite loops, graceful depth limiting

---

## 14. Next Steps

1. **Validate pattern mapping**: Confirm current Pandora phases map cleanly to UNDERSTAND/PLAN/DO/CHECK
2. **Prototype progressive loading**: Test context savings with split prompts
3. **Design state document schema**: Finalize format and relationships
4. **Implement micro_loop primitive**: Core function that all levels use
5. **Test self-building**: Can system create a simple tool from pattern?

---

**This is a vision document. Implementation requires iterative prototyping and validation.**
