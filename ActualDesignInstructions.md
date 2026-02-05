# Actual Design Instructions

Version: 1.0  
Updated: 2026-02-03

This document defines **how we actually build systems** so they work end‑to‑end and don’t collapse into hallucinated, ungrounded output. It prioritizes **design‑first correctness** over test theater.

---

## Project Design Workflow (Authoritative Steps)

This is the required order for building all systems.

1. **CLAUDE.md** — establish the core patterns and rules of engagement.
2. **DEBUG.md** — establish the debugging patterns and failure response rules.
3. **Design Document** — capture the full project scope and descriptions.
4. **architecture/INDEX.md** — track all architecture docs and ensure discoverability.
5. **(Reserved)** — intentionally left open for future process needs.
6. **Architecture Docs** — write the full phase and system architecture documentation.
7. **Code Implementation** — implement all code files strictly aligned with the architecture docs.
8. **Review Stories** — the LLM explains exactly how each code file conforms to the architecture.  
   If anything doesn’t align, fix the design, fix the code, and fix the story until they match.

**Testing comes last** and is treated as validation only.  
If the system is correctly designed and implemented, tests should pass.

---

## What “Correct” Means

A system is correct when:

- A real query yields a grounded response.
- Each claim can be traced to evidence.
- Phase outputs match architecture docs exactly.
- The system can fail gracefully and say “unknown.”

Tests are optional. **Proof‑carrying outputs are required.**


## If We Break These Rules

Stop. Fix the architecture or the code. Do not add new features.

---

## Why This Works

- Eliminates hallucinated output.
- Creates a system that can be audited line‑by‑line.
- Keeps the pipeline coherent as features grow.
- Prevents wasted effort on features that do not integrate.

