# LLM Roles Quick Reference

**Version:** 7.0
**Updated:** 2026-02-03

Quick reference for the single-model multi-role system. For detailed specs, see individual phase docs.

---

## Model Stack

| Component | Model | Purpose |
|-----------|-------|---------|
| All text roles | Qwen3-Coder-30B-AWQ | Single model for all text tasks via temperature control |
| Vision/OCR | EasyOCR | Text extraction from images (CPU) |
| Embedding | all-MiniLM-L6-v2 | Semantic search (CPU) |

**Architecture:** Single-model system — one Qwen3-Coder-30B-AWQ instance handles all roles. Role behavior is controlled entirely by **temperature** and **system prompts**.

---

## Text Roles

| Role | Temperature | Purpose |
|------|-------------|---------|
| NERVES | 0.3 | Compression, deterministic summarization |
| REFLEX | 0.4 | Classification, binary decisions, fast gates |
| MIND | 0.6 | Reasoning, planning, coordination, validation |
| VOICE | 0.7 | User dialogue, natural responses |

**Principle:** Route to the lowest temperature capable of the task. Lower temperature = more deterministic. Higher temperature = more varied and natural.

### Temperature Rationale (Qwen3-Coder-30B-A3B-Instruct)

Qwen3-Coder is a **non-thinking-only** model. Official recommended inference settings:
- temperature=0.7, top_p=0.8, top_k=20, repetition_penalty=1.05

Qwen explicitly warns: **"DO NOT use greedy decoding, as it can lead to performance degradation and endless repetitions."** This applies to all temperatures near 0. As a Mixture-of-Experts model, expert routing is nondeterministic even at temperature=0, so very low temperatures do not achieve true determinism.

Our graduated scale (0.3–0.7) balances task-appropriate creativity against the model's documented sensitivity to low temperatures. The floor of 0.3 stays above the greedy-danger zone while maintaining low variance for factual tasks.

**Sources:** [Qwen3-Coder Model Card](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct), [Qwen Quickstart](https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html), [HuggingFace Discussion: Temp 0.7 is too high](https://huggingface.co/Qwen/Qwen3-30B-A3B-GGUF/discussions/1)

---

## Phase → Role Mapping

| Phase | Name | Role | Temp |
|-------|------|------|------|
| 1 | Query Analyzer | REFLEX | 0.4 |
| 2 | Context Gatherer | MIND | 0.6 |
| 3 | Planner | MIND | 0.6 |
| 4 | Executor | MIND | 0.6 |
| 5 | Coordinator | REFLEX | 0.4 |
| 6 | Synthesis | VOICE | 0.7 |
| 7 | Validation | MIND | 0.6 |
| 8 | Save | N/A | N/A |

NERVES runs as background compression when documents exceed token budgets — it is not a pipeline phase.

---

## Phase Decisions

| Phase | Decision | Routes To |
|-------|----------|-----------|
| 1 Query Analyzer (Validation) | pass | Phase 2.1 |
| 1 Query Analyzer (Validation) | retry | Phase 1 rerun |
| 1 Query Analyzer (Validation) | clarify | User |
| 3 Planner | executor | Phase 4 (Executor–Coordinator loop) |
| 3 Planner | synthesis | Phase 6 (skip execution) |
| 3 Planner | clarify | User |
| 7 Validation | APPROVE | Phase 8 |
| 7 Validation | REVISE | Phase 6 (max 2) |
| 7 Validation | RETRY | Phase 3 (max 1) |
| 7 Validation | FAIL | User (error) |

---

## Quality Gates

| Gate | Phases | Enforcement |
|------|--------|-------------|
| Schema validation | All LLM calls | Output must match recipe's declared schema |
| Evidence grounding | P4, P5, P6 | Claims must link to source documents |
| Confidence threshold | P2, P7 | Below threshold triggers escalation |
| Validation judgment | P7 | APPROVE / REVISE / RETRY / FAIL |

---

## Research Subsystem Roles

The internet research tool (invoked from Phase 5 Coordinator) has its own internal LLM roles:

| Role | Temperature | Purpose |
|------|-------------|---------|
| Research Planner | MIND (0.6) | Decides next action (search, visit, done) |
| Result Scorer | REFLEX (0.4) | Scores search results for relevance |
| Content Extractor | MIND (0.6) | Extracts findings from page text |

These roles follow the same recipe system and token governance as pipeline roles.

---

## Related Documents

| Topic | Document |
|-------|----------|
| Recipe system | `concepts/recipe_system/RECIPE_SYSTEM.md` |
| Prompt philosophy | `concepts/recipe_system/PROMPT_MANAGEMENT_SYSTEM.md` |
| Phase 1 | `main-system-patterns/phase1-query-analyzer.md` |
| Phase 1.5 | `main-system-patterns/phase1.5-query-analyzer-validator.md` |
| Phase 2.1 | `main-system-patterns/phase2.1-context-gathering-retrieval.md` |
| Phase 2.2 | `main-system-patterns/phase2.2-context-gathering-synthesis.md` |
| Phase 2.5 | `main-system-patterns/phase2.5-context-gathering-validator.md` |
| Phase 3 | `main-system-patterns/phase3-planner.md` |
| Phase 4 | `main-system-patterns/phase4-executor.md` |
| Phase 5 | `main-system-patterns/phase5-coordinator.md` |
| Phase 6 | `main-system-patterns/phase6-synthesis.md` |
| Phase 7 | `main-system-patterns/phase7-validation.md` |
| Phase 8 | `main-system-patterns/phase8-save.md` |
| Deprecated | `main-system-patterns/phase1-reflection.md` |
| Research architecture | `main-system-patterns/workflows/internet-research-mcp/` |

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 5.1 | 2026-01-26 | Added Research Subsystem Roles section |
| 6.0 | 2026-02-03 | Fixed all phase numbers to 9-phase pipeline. Removed vLLM config, Python code, token budgets, error limits (now in ERROR_HANDLING.md). Removed NERVES/EasyOCR implementation detail. |
| 7.0 | 2026-02-03 | **Revised all role temperatures based on Qwen3-Coder research.** NERVES 0.1→0.3, REFLEX 0.3→0.4, MIND 0.5→0.6, VOICE 0.7 unchanged. Phase 5 Coordinator changed from MIND to REFLEX (deterministic tool selection). Added temperature rationale section with Qwen sources. |
| 7.1 | 2026-02-04 | Removed deprecated Phase 1.2 reference after normalization moved into Phase 1. |

---

**Last Updated:** 2026-02-04
