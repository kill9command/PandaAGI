# CLAUDE.md - Pandora

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
./scripts/start.sh        # Start services (vLLM + Gateway + Orchestrator)
./scripts/stop.sh         # Stop all services
./scripts/health_check.sh # Check service status
```

**Services:** Gateway :9000, Orchestrator :8090, vLLM :8000

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

**Quality over speed.** Pandora prioritizes correct answers over response time.

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

---

## Project Overview

**Pandora** is a context-orchestrated LLM stack implementing a **single-model multi-role reflection system**. One LLM (Qwen3-Coder-30B-AWQ) plays multiple roles through an 8-phase document pipeline.

**Hardware:** RTX 3090 (24GB VRAM)
**Model:** Qwen3-Coder-30B-AWQ via vLLM

**Pipeline:** Phase 0-7 (Query Analyzer → Reflection → Context → Planner → Coordinator → Synthesis → Validation → Save)

**Role Temperatures:**
| Role | Temp | Purpose |
|------|------|---------|
| REFLEX | 0.3 | Classification, gates |
| NERVES | 0.1 | Compression |
| MIND | 0.5 | Reasoning, planning |
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

**Last Updated:** 2026-02-02
