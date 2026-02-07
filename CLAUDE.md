# CLAUDE.md - Panda

*** The golden build cycle ***
- create concepts, create design, create implementation plans, create code, create code review stories, test
- for changing code we must go back to the begenning and ensure all changes go through each process again.

<mandatory_behavior>
## BEFORE EVERY RESPONSE, I MUST:

1. **If debugging:** Follow `DEBUG.md` protocol EXACTLY. Report findings, STOP, wait for approval.
2. **If editing code:** Quote the architecture spec that justifies the change.
3. **If unsure:** Ask, don't guess.
4. **If doing design/architecture/code work:** Follow `ActualDesignInstructions.md` as the authoritative workflow.

## DEBUGGING IS GOVERNED BY DEBUG.md - NO EXCEPTIONS

When ANY bug, error, or unexpected behavior is encountered:
1. **STOP** - Do not attempt fixes
2. **READ** `DEBUG.md` - Follow the protocol step by step
3. **REPORT** - Document findings using the bug report format
4. **WAIT** - Get approval before implementing fixes

**Skipping steps causes cascading failures.**
</mandatory_behavior>

---

## Critical Rules

1. **INVESTIGATE != FIX** - These are separate steps. Never combine them.
2. **READ BEFORE EDIT** - Quote the relevant spec from `architecture/INDEX.md`
3. **NO HARDCODING** - If LLM makes bad decisions, fix prompts/context, not code.
4. **VERIFY WITH EVIDENCE** - Run tests/commands, show output, never just say "Done"
5. **RE-READ AFTER CORRECTIONS** - If corrected, re-read the source file before trying again

---

## Documentation Map

| Need | Go To |
|------|-------|
| **Debugging** | `DEBUG.md` |
| **Architecture** | `architecture/README.md` → `architecture/INDEX.md` |
| **Phase prompts** | `apps/prompts/pipeline/*.md` |
| **Research workflows** | `apps/workflows/research/*.md` |

---

## Quick Commands

```bash
./scripts/start.sh        # Start services (vLLM + Gateway + Tool Server)
./scripts/stop.sh         # Stop all services
./scripts/health_check.sh # Check service status
```

**Services:** Gateway :9000, Tool Server :8090, vLLM :8000

**Logs:**
```bash
tail -f logs/panda/system.log   # All system activity
tail -f logs/panda/latest.log   # Domain events (turns, phases)
```

**Find latest turn:**
```bash
ls -lt panda_system_docs/users/default/turns/ | head -5
```

---

## Spec Pointer (Required Before Edits)

Before proposing or making changes:

```
Spec Doc: architecture/path/to/doc.md#Section
Quoted Section:
> [relevant quote]

Planned Files: path/to/file1, path/to/file2
Alignment: [how change matches spec]
Out of Scope: [what you will NOT touch]
```

If you cannot fill this, stop and ask for clarification.

---

## Design Philosophy

**Quality over speed.** Panda prioritizes correct answers over response time.

Do NOT suggest:
- Time budgets that cut off research early
- Arbitrary timeouts that return partial results
- "Fast path" shortcuts that sacrifice accuracy

If improving performance:
1. Make it smarter (skip unnecessary work)
2. Make it cache better (don't repeat work)
3. Make it detect completion better (based on quality, not time)

---

## LLM Context Discipline

**When an LLM makes a bad decision, fix context/prompts, not code.**

Pass the **original query** to any LLM that makes decisions. The LLM reads user priorities ("cheapest", "best") directly.

```
WRONG: LLM picked wrong vendors -> Add hardcoded vendor list
RIGHT: LLM picked wrong vendors -> Is it seeing the original query?
       If NOT -> Add original_query parameter
       If YES -> Improve prompt instructions
```

**NEVER HARDCODE** decisions that LLMs should make:
- Blocklists/allowlists of domains, vendors, patterns
- Site-specific URL templates
- Conditional logic based on domain names

### Hardcoding Removal Guidelines

When reviewing hardcoded values, classify them into three categories:

**1. Subjective relevance decisions (MUST remove)**
Values where the "right answer" depends on the user's query or context. These are LLM decisions encoded as Python lists/dicts.
```
EXAMPLE: Blocklisting all forum URLs — a forum post ABOUT buying hamsters
IS relevant to "where to buy hamster". The LLM knows this, the regex doesn't.
EXAMPLE: Fixed "good/bad" keyword lists with static weights — "syrian hamster"
is only relevant if the user is searching for hamsters, not for laptops.
```

**2. Objective facts used as filters (SHOULD remove, lower priority)**
Values that are factually correct today but brittle to future changes. An LLM would arrive at the same answer but would also adapt when facts change.
```
EXAMPLE: "Chromebooks never have NVIDIA GPUs" — true today, but hardcoding it
means a code change if that ever changes. The LLM knows this fact already.
EXAMPLE: GPU model lists (RTX 4050, 4060, 4070...) — correct but needs manual
updates when new models ship. The LLM already knows product model names.
```

**3. Advisory scoring heuristics (SHOULD remove, lowest priority)**
Values that influence priority/ordering but don't gate decisions. Damage from stale values is low since items are still processed, just in suboptimal order.
```
EXAMPLE: "$900-$3000 is typical dGPU laptop range" — adjusts verification order
but doesn't reject products. If the market shifts, ordering is slightly wrong
but nothing breaks.
```

**The replacement pattern is the same for all three:**
- Pass the data + original query to the LLM
- Let the LLM evaluate relevance/facts/priority in context
- Use prompts (recipes) to guide the LLM's evaluation criteria
- If the LLM is too slow for per-item evaluation, batch candidates into a single LLM call

---

## LLM Output Interpretation (NO REGEX BY DEFAULT)

**If an LLM produced the output, an LLM should interpret it.**

Claude and ChatGPT both default to regex-based extraction when parsing LLM output. This is a training artifact from 2023-2024 when models were unreliable. **It is the wrong default for this system.**

```
WRONG: re.search(r'DECISION:\s*(EXECUTE|COMPLETE)', response)
RIGHT: Send the output to the next phase's LLM role for interpretation
```

### Why Regex Fails in LLM Pipelines

1. **Masks bad output** — Regex silently extracts garbage instead of surfacing that the prompt needs fixing
2. **Parallel bug surface** — When something breaks, you can't tell if the model is wrong or the regex is wrong
3. **Couples code to syntax** — Every output format change requires new parsing code
4. **Blocks self-extension** — Regex can't generalize; the system can't build tools that parse novel formats
5. **Makes debugging harder** — The regex layer hides what the LLM actually produced

### When Regex IS Appropriate

- Truly mechanical extraction (URLs from text, timestamps, file paths)
- Performance-critical inner loops where an LLM call is genuinely too expensive
- Extracting from non-LLM sources (system logs, structured data files)

**If you're about to write a regex to parse LLM output, STOP and ask:** Can the next phase's LLM role interpret this instead? The answer is almost always yes.

---

## Prompt Debugging Hierarchy

When an LLM phase produces bad output, follow this order:

### 1. REMOVE instructions (most common fix)

The model is doing too many things at once. The prompt has accumulated competing objectives and the model's attention is diluted.

```
WRONG: "Also make sure to check X, and verify Y, and don't forget Z..."
RIGHT: Strip to the one thing this role needs to decide
```

**If a prompt is longer than ~500 tokens of instructions, it's probably doing too much.** Split into multiple roles instead.

### 2. FIX the prompt (second most common)

The remaining instructions are unclear or missing critical context. Rewrite for clarity, don't add volume.

### 3. FIX the context (third)

The model isn't seeing the information it needs to decide correctly. Check: Is the original query visible? Is the relevant prior phase output included?

### 4. SPLIT into a new role (if 1-3 don't work)

The task is genuinely too complex for one LLM call. Create a new phase/role with its own temperature, its own focused prompt, and a clear single-purpose contract.

This is how multi-role architecture was born: not by design committee, but by discovering that **a focused 30B model outperforms a distracted 30B model every time.**

### NEVER

- Add regex fallbacks to "handle" bad output
- Add retry loops that just call the same bad prompt again
- Add hardcoded defaults for when parsing fails
- Increase temperature hoping for a "better" answer

These all mask the real problem and make the system harder to debug over time.

---

## Project Overview

**Panda** is a context-orchestrated LLM stack implementing a **single-model multi-role reflection system**. One LLM (Qwen3-Coder-30B-AWQ) plays multiple roles through a 9-phase document pipeline.

**Hardware:** RTX 3090 (24GB VRAM)
**Model:** Qwen3-Coder-30B-AWQ via vLLM

**Pipeline:** Phase 0-8 (Query Analyzer → Reflection → Context → Planner → Executor → Coordinator → Synthesis → Validation → Save)

**Role Temperatures:**
| Role | Temp | Purpose |
|------|------|---------|
| NERVES | 0.3 | Compression |
| REFLEX | 0.4 | Classification, gates |
| MIND | 0.6 | Reasoning, planning |
| VOICE | 0.7 | User dialogue |

**See `architecture/README.md` for full details.**

---

## Verification Checklist

After ANY fix:

```bash
# 1. Test via API or UI

# 2. Verify imports
python -c "from libs.gateway.unified_flow import UnifiedFlow; from apps.services.gateway.app import app; print('OK')"

# 3. Run relevant tests
python scripts/test_intent_classification.py
```

---

**Last Updated:** 2026-02-05
