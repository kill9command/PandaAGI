# CLAUDE.md - Pandora

<mandatory_behavior>
## BEFORE EVERY RESPONSE, I MUST:

1. **If investigating/debugging:** Follow `DEBUG.md` protocol EXACTLY. Report findings, STOP, wait for "fix it"
2. **If editing code:** Quote the architecture spec that justifies the change
3. **If unsure:** Ask, don't guess

I will state which rule I'm following at the start of my response.

## DEBUGGING IS GOVERNED BY DEBUG.md - NO EXCEPTIONS

When ANY bug, error, or unexpected behavior is encountered:

1. **STOP** - Do not attempt fixes
2. **READ** `DEBUG.md` - Follow the protocol step by step
3. **CATEGORIZE** - State the bug category before investigating
4. **INVESTIGATE** - Read ALL phase outputs, find the break point
5. **ANALYZE** - Determine root cause, assess impact
6. **DESIGN** - Propose fix with architecture reference
7. **WAIT** - Get approval before implementing
8. **VERIFY** - Run regression tests after fixing

**Skipping steps in DEBUG.md causes cascading failures. The protocol exists because debugging without structure creates more bugs than it fixes.**
</mandatory_behavior>

---

## Critical Rules (5 only - memorize these)

1. **INVESTIGATE != FIX** - These are separate steps. Never combine them.
2. **READ BEFORE EDIT** - Read `architecture/INDEX.md` and quote the relevant spec
3. **NO HARDCODING** - If LLM makes bad decisions, fix prompts/context, not code. Don't fill prompts with garbage either - consider them in whole with the system.
4. **VERIFY WITH EVIDENCE** - Run tests/commands, show output, never just say "Done"
5. **RE-READ AFTER CORRECTIONS** - If corrected, re-read the source file before trying again

---

## Where to Find Info

| Need | Location |
|------|----------|
| **DEBUGGING PROTOCOL** | `DEBUG.md` (MANDATORY) |
| **System-wide log** | `logs/panda/system.log` |
| **Domain events log** | `logs/panda/latest.log` |
| Architecture specs | `architecture/INDEX.md` (start here) |
| Phase prompts | `apps/prompts/**/*.md` |
| Turn debugging | `panda_system_docs/users/*/turns/turn_XXXXX/context.md` |
| Pipeline implementation | `libs/gateway/unified_flow.py` |
| Tool execution | `apps/services/orchestrator/*_mcp.py` |

---

## Quick Commands

```bash
./scripts/start.sh        # Start services (vLLM + Gateway + Orchestrator)
./scripts/stop.sh         # Stop all services
./scripts/health_check.sh # Check service status
```

**Services:** Gateway :9000, Orchestrator :8090, vLLM :8000

---

## When Debugging Turn Issues

**FOLLOW DEBUG.md PROTOCOL. This is a quick reference only.**

```bash
# Find the turn
ls -lt panda_system_docs/users/default/turns/ | head -5

# Read the context.md (has all phase sections)
cat panda_system_docs/users/default/turns/turn_XXXXX/context.md

# Check system logs
tail -100 logs/panda/system.log

# Follow live
tail -f logs/panda/system.log
```

**Report what each phase produced. Wait for approval before fixing.**

---

## Bug Report Format (from DEBUG.md)

When reporting a bug, use this structure:

```
## Bug: [Title]

### Category
[STARTUP | PIPELINE | PHASE0-7 | MEMORY | TOOL | RESEARCH]

### Turn Location
panda_system_docs/users/{user}/turns/turn_XXXXXX/

### Break Point
- Phase: [which phase failed]
- Input: [correct/incorrect]
- Output: [what was wrong]

### Root Cause
- Type: [PROMPT | CODE | CONTEXT | TOOL | INTEGRATION]
- Location: [file:function]
- Why: [explanation]

### Status
[INVESTIGATING | ANALYZED | DESIGNED | AWAITING APPROVAL | IMPLEMENTING | VERIFYING]
```

---

## Verification Checklist

After ANY fix, verify:

```bash
# 1. Original bug fixed
# Test via API or UI

# 2. Imports work
python -c "from libs.gateway.unified_flow import UnifiedFlow; from apps.services.gateway.app import app; print('OK')"

# 3. Run relevant tests
python scripts/test_intent_classification.py
```

---

## Architecture Documentation

**Start here:** `architecture/README.md` -> links to `architecture/INDEX.md`

```
architecture/
├── README.md                      # System overview - START HERE
├── INDEX.md                       # Complete doc index
├── LLM-ROLES/
│   └── llm-roles-reference.md     # Model stack, roles, temperatures
├── main-system-patterns/
│   ├── phase0-query-analyzer.md   # Intent classification
│   ├── phase1-reflection.md       # PROCEED/CLARIFY gate
│   ├── phase2-context-gathering.md
│   ├── phase3-planner.md
│   ├── phase4-coordinator.md      # Tool execution
│   ├── phase5-synthesis.md        # Response generation
│   ├── phase6-validation.md
│   └── phase7-save.md
├── DOCUMENT-IO-SYSTEM/            # context.md pattern
├── mcp-tool-patterns/             # Tool implementations
├── services/                      # Service specs
└── prompting-manual/              # Prompt design guide
```

---

## Spec Pointer (Required Before Edits)

Before proposing or making changes, respond with this filled template:

```
Spec Doc: architecture/path/to/doc.md#Section
Quoted Section:
> ...

Planned Files: path/to/file1, path/to/file2
Alignment: One sentence on how the change matches the quoted spec
Out of Scope: What you will NOT touch
```

If you cannot fill this, stop and ask for clarification.

---

## LLM Context Discipline

**When an LLM makes a bad decision, the fix is ALWAYS better context, not programmatic workarounds.**

### The Principle

Pass the **original query** to any LLM that makes decisions. The LLM reads user priorities ("cheapest", "best", "fastest") directly from the query text.

**Important distinction:**
- **Intent** (`transactional`, `navigation`) = System routing (which flow, cache TTL)
- **User Priority** ("cheapest", "best") = LLM interprets from original query

Don't pre-classify user priorities. "Transactional" doesn't mean "price-focused" - it just means user wants to buy. The LLM reads "cheapest" directly.

### Debugging LLM Decision Errors

```
WRONG approach:
  LLM picked wrong vendors -> Add hardcoded vendor priority list
  LLM missed "cheapest" -> Pre-classify as "price_intent" and pass that

RIGHT approach:
  LLM picked wrong vendors -> Is it seeing the ORIGINAL query with "cheapest"?

  If NOT -> Add original_query parameter, include in prompt
  If YES -> Improve prompt instructions to use that context
```

**NEVER HARDCODE DECISIONS THAT LLMs SHOULD MAKE:**
- Blocklists/allowlists of domains, vendors, patterns
- Site-specific URL templates (e.g., "if amazon, add &sort=price")
- Conditional logic based on domain names
- Any "if X then Y" rules that encode knowledge the LLM should learn

**If the LLM is making bad decisions, the fix is ALWAYS better context/prompts, NOT hardcoded workarounds.** Teach the system, don't code around it.

---

## Design Philosophy: Quality Over Speed

**THIS IS NOT A TYPICAL CHATBOT.**

Pandora prioritizes **correct, high-quality answers** over response time. Do NOT suggest:
- Time budgets that cut off research early
- Arbitrary timeouts that return partial garbage
- "Fast path" shortcuts that sacrifice accuracy
- Any optimization that trades quality for speed

If you want to improve performance:
1. Make it smarter (skip unnecessary work)
2. Make it cache better (don't repeat work)
3. Make it detect completion better (know when enough is enough based on QUALITY, not time)

**DO NOT** just slap a timeout on something and call it optimization.

---

## Project Overview

**Pandora** is a context-orchestrated LLM stack implementing a **single-model multi-role reflection system**. One LLM (Qwen3-Coder-30B-AWQ) plays multiple roles through an 8-phase document pipeline. Research runs as a tool inside Phase 4.

**Hardware:** RTX 3090 Server (24GB VRAM)
**Model:** Qwen3-Coder-30B-AWQ via vLLM (port 8000)
**Vision:** EasyOCR (CPU-based OCR)

**8-Phase Pipeline:**
```
Phase 0: Query Analyzer -> Classify intent, resolve references
Phase 1: Reflection -> context.md S1 (PROCEED | CLARIFY)
Phase 2: Context Gatherer -> context.md S2 (searches turns, memory)
Phase 3: Planner -> context.md S3 (task planning)
Phase 4: Coordinator -> context.md S4 (MCP tool execution, includes research)
Phase 5: Synthesis -> context.md S5 (final response generation)
Phase 6: Validation -> context.md S6 (APPROVE | REVISE | RETRY | FAIL)
Phase 7: Save -> (procedural save, index turn, no LLM)
```

**Role Temperatures (all use same model):**
| Role | Temp | Purpose |
|------|------|---------|
| REFLEX | 0.3 | Classification, gates |
| NERVES | 0.1 | Compression |
| MIND | 0.5 | Reasoning, planning |
| VOICE | 0.7 | User dialogue |

---

## Key Files

| Purpose | Location |
|---------|----------|
| Architecture docs | `architecture/` (start with README.md) |
| Flow implementation | `libs/gateway/unified_flow.py` |
| Tool implementations | `apps/services/orchestrator/*_mcp.py` |
| LLM prompts | `apps/prompts/` |
| Recipes | `apps/recipes/recipes/*.yaml` |
| Runtime config | `.env` |
| Logging config | `libs/core/logging_config.py` |
| System logs | `logs/panda/system.log` |

---

## Directory Structure

```
pandaai/
├── architecture/              # System specifications (READ FIRST)
├── apps/
│   ├── services/
│   │   ├── gateway/          # FastAPI webapp (port 9000)
│   │   └── orchestrator/     # Tool execution (port 8090)
│   ├── prompts/              # LLM prompts by function
│   └── recipes/              # YAML recipes
├── libs/
│   ├── gateway/              # Pipeline implementation (unified_flow.py)
│   ├── core/                 # Config, models
│   └── llm/                  # LLM client
├── scripts/                  # Start/stop/test scripts
├── panda_system_docs/        # Runtime data
│   └── users/default/
│       ├── turns/            # Turn documents
│       └── sessions/         # Session data
└── logs/                     # Service logs
```

---

## Gateway Service Structure

```
apps/services/gateway/
├── app.py                    # Slim app factory (~160 lines)
├── config.py                 # All env vars, constants, settings
├── dependencies.py           # Singleton getters (lazy initialization)
├── lifespan.py               # Startup/shutdown handlers
│
├── services/                 # Business logic modules
│   ├── thinking.py           # ThinkingEvent, SSE queues, confidence
│   ├── jobs.py               # Async job management
│   └── orchestrator_client.py # Circuit breaker calls to Orchestrator
│
├── utils/                    # Utility functions
│   ├── text.py               # Subject extraction, keyword matching
│   ├── json_helpers.py       # JSON parsing from LLM responses
│   └── trace.py              # Trace envelope building, logging
│
├── routers/                  # Internal API endpoints
│   ├── health.py             # /healthz, /health, /health/detailed
│   ├── thinking.py           # /v1/thinking/{id}, /v1/response/{id}
│   ├── jobs.py               # /jobs/start, /jobs/{id}, /jobs/{id}/cancel
│   ├── transcripts.py        # /transcripts, /transcripts/{id}
│   └── interventions.py      # /interventions/*, /api/captchas/*
│
└── routes/                   # External API endpoints (proxy to Orchestrator)
    ├── chat.py               # /chat, /inject, /intervention/resolve
    ├── turns.py              # /turns (proxy)
    ├── memory.py             # /memory (proxy)
    ├── cache.py              # /cache (proxy)
    ├── status.py             # /status, /metrics (proxy)
    └── diff.py               # /diff/last (proxy)
```

---

## Logging System

**Log Files:**
| File | Purpose |
|------|---------|
| `logs/panda/system.log` | All Python logging from all services (rotating, 10MB max, 5 backups) |
| `logs/panda/latest.log` | Domain events from PandaLogger (turns, phases, LLM calls) |

**Quick debugging commands:**
```bash
tail -f logs/panda/system.log        # Watch all system activity
tail -f logs/panda/latest.log        # Watch domain events
grep -i error logs/panda/system.log | tail -20  # Search for errors
grep "trace_id" logs/panda/system.log            # Follow a specific trace
```

**Using logging in code:**
```python
from libs.core.logging_config import setup_logging, get_logger

setup_logging(service_name="my_service")
logger = get_logger(__name__)
logger.info("Processing request")
```

---

**Last Updated:** 2026-02-02
