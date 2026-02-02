# Next Phase: Pandora Intelligence Expansion (Wiki + Science Tools)

**Status:** Proposed Architecture (FUTURE)
**Created:** 2026-01-03
**Purpose:** Define the next capability phase where Pandora becomes more intelligent by retrieving facts from a wiki knowledge base and using explicit science tools (math/physics/chem) to answer questions with evidence.

**Prerequisites:** This document describes features for AFTER the core PandaAI v2 system is stable and fully implemented. Do not begin work on these features until the 8-phase pipeline, 5-model stack, and document IO system are production-ready.

---

## 1. Core Shift

Pandora’s next phase is **system intelligence**, not just model intelligence.
The system becomes smarter by:
- retrieving known facts from a wiki
- using deterministic tools for computation
- enforcing evidence‑linked answers

This keeps LLMs as decision makers but grounds answers in **retrieval + tools**.

---

## 2. Wiki-First Answering

**Rule:** If the answer exists in the wiki, use it before web research.

### 2.1 Retrieval Flow

1. Context Gatherer queries wiki index with the user question.
2. Returned wiki docs are linked into `context.md §2`.
3. Planner decides:
   - answer from wiki
   - or request research if missing/stale.

### 2.2 Evidence Discipline

- Every fact must cite a wiki doc or tool output.
- If the wiki does not contain the answer, respond with:
  **“Not found in wiki, need research.”**

---

## 3. Science Tooling (Math, Physics, Chemistry)

Add explicit tools that the LLM must call for scientific work:

- **Calculator** (numeric, unit conversion)
- **Physics solver** (kinematics, forces, energy, etc.)
- **Chemistry solver** (stoichiometry, balancing, molarity)

**Rule:** Do not allow “mental math” for scientific answers. Require tool outputs.

Tool outputs are saved and linked in `context.md §4`.

---

## 4. Evaluation Strategy (System-Level)

### 4.1 Wiki QA Track

- Questions where answers exist in the wiki.
- Measure: exact match/F1 + evidence‑link rate.
- Include “not found” cases to enforce correct deferral.

### 4.2 Science Tool Track

- Questions requiring physics/chem/math tools.
- Measure: numerical accuracy + correct tool usage.
- Require citations to tool output.

### 4.3 Web Research Track (Optional)

- Questions not in wiki.
- Measure: citation quality + validation pass rate.

---

## 5. Quality Gates (Phase-Specific)

- **Evidence Gate:** wiki/tool citations required.
- **Tool Gate:** science tasks must show tool calls.
- **Freshness Gate:** wiki facts must pass TTL or trigger research.

---

## 6. Next Steps (Implementation Outline)

1. Add wiki index + retriever tool.
2. Add calculator/physics/chem tools.
3. Update prompt recipes to require tool usage on science intents.
4. Build a small eval set for wiki + science tracks.

---

## 7. Why This Matters

This phase makes Pandora **provably smarter**:
- answers are grounded in the wiki
- computations are verifiable
- the system can admit “unknown” and trigger research
