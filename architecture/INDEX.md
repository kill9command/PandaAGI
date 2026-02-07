# Architecture Index

Complete index of architecture documents for humans and LLMs.

**System overview:** [`architecture/README.md`](README.md)
**Debugging protocol:** [`DEBUG.md`](../DEBUG.md)
**Agent instructions:** [`CLAUDE.md`](../CLAUDE.md)

---

## Start Here

| Document | Purpose |
|----------|---------|
| `architecture/README.md` | System summary, phases, services |
| `DEBUG.md` | Mandatory debugging protocol |
| `CLAUDE.md` | Agent behavioral rules |

---

## Core Context

- `LLM-ROLES/llm-roles-reference.md` — Model stack definitions and phase role specs
- `LLM-ROLES/prompting-manual/prompting-manual.md` — Prompting guidance for the single-model system
- `LLM-ROLES/prompting-manual/V2_PROMPT_STYLE.md` — V2 prompt style guide (abstract, concise, table-driven)

---

## Phase Specifications (8-Phase Pipeline)

| Phase | Document | Purpose |
|-------|----------|---------|
| 1 | `main-system-patterns/phase1-query-analyzer.md` | User purpose extraction, query parsing, data requirements, validation |
| 1.5 | `main-system-patterns/phase1.5-query-analyzer-validator.md` | Query analysis validation helper |
| 2.1 | `main-system-patterns/phase2.1-context-gathering-retrieval.md` | Search-First Retrieval: LLM generates search terms, code does BM25 + embedding hybrid search |
| 2.2 | `main-system-patterns/phase2.2-context-gathering-synthesis.md` | Synthesis sub-phase (extract and compile context) |
| 2.5 | `main-system-patterns/phase2.5-context-gathering-validator.md` | Context gathering validation helper |
| 3 | `main-system-patterns/phase3-planner.md` | Strategic planning with goals |
| 4 | `main-system-patterns/phase4-executor.md` | Tactical decisions, natural language commands |
| 5 | `main-system-patterns/phase5-coordinator.md` | Tool Expert: translates commands to tool calls |
| 6 | `main-system-patterns/phase6-synthesis.md` | User-facing response construction |
| 7 | `main-system-patterns/phase7-validation.md` | Quality checks and retry logic |
| 8 | `main-system-patterns/phase8-save.md` | Persistence, indexing, turn archival |

**Deprecated:** `main-system-patterns/phase1-reflection.md` — Reflection gate removed; validation now lives inside Phase 1.

---

## Concepts (Cross-Cutting Patterns)

| Document | Purpose | Key Phases |
|----------|---------|------------|
| `concepts/system_loops/EXECUTION_SYSTEM.md` | 3-tier loop, workflow system, multi-task loop | P3, P4, P5 |
| `concepts/system_loops/CONTEXT_COMPRESSION.md` | NERVES compression, never blind truncation | All |
| `concepts/recipe_system/RECIPE_SYSTEM.md` | Recipe-driven LLM execution and token governance | All |
| `concepts/recipe_system/PROMPT_MANAGEMENT_SYSTEM.md` | Prompt philosophy, quality gates, auto-compression | All |
| `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | Document flow and context.md schema | All |
| `concepts/DOCUMENT-IO-SYSTEM/OBSERVABILITY_SYSTEM.md` | Metrics, decision trail, quality trends | All |
| `concepts/memory_system/MEMORY_ARCHITECTURE.md` | Memory retrieval, caching, and learning | P2, P3, P8 |
| `concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` | Confidence/quality scoring | P2, P3, P6, P7, P8 |
| `concepts/error_and_improvement_system/ERROR_HANDLING.md` | Fail-fast error handling | All |
| `concepts/error_and_improvement_system/improvement-principle-extraction.md` | Learning from revisions | P7 |
| `concepts/tools_workflows_system/TOOL_SYSTEM.md` | Tool families, creation pipeline, sandbox | P4, P5 |
| `concepts/self_building_system/SELF_BUILDING_SYSTEM.md` | Tool + workflow self-extension | P3, P4, P5 |
| `concepts/self_building_system/BACKTRACKING_POLICY.md` | Replanning rules + failure routing | P3, P7 |
| `concepts/artifacts_system/ARTIFACT_SYSTEM.md` | Output artifacts and file generation | P6, P8 |
| `concepts/code_mode/code-mode-architecture.md` | Code-mode behavior and constraints | P0, P3, P5 |
| `concepts/user_interface_systems/INJECTION_SYSTEM.md` | Mid-turn message injection | Gateway level |

---

## Workflows

Research workflows define declarative tool sequences for the Executor:

| Workflow | Purpose |
|----------|---------|
| `apps/workflows/research/intelligence_search.md` | Informational research |
| `apps/workflows/research/product_quick_find.md` | Fast product lookup |
| `apps/workflows/research/product_research.md` | Full commerce research |
| `apps/workflows/meta/create_workflow.md` | Meta-workflow for self-creation |

**See:** `concepts/system_loops/EXECUTION_SYSTEM.md` for workflow architecture.

---

## Services

| Document | Purpose |
|----------|---------|
| `main-system-patterns/services/gateway_processes.md` | Gateway service — pipeline orchestration (port 9000) |
| `main-system-patterns/services/tool-execution-service.md` | Tool Server — tool execution (port 8090) |
| `main-system-patterns/services/user-interface.md` | Web interface (SvelteKit), VSCode, CLI |
| `concepts/memory_system/MEMORY_ARCHITECTURE.md` | Memory system (referenced from Services) |
| `main-system-patterns/services/DOCKER-INTEGRATION/DOCKER_ARCHITECTURE.md` | Docker services and deployment |

---

## Research & Browser Architecture

| Document | Purpose |
|----------|---------|
| `main-system-patterns/workflows/internet-research-mcp/PRODUCT_RESEARCH_ARCHITECTURE.md` | Product research system |
| `main-system-patterns/workflows/internet-research-mcp/WEB_AGENT_ARCHITECTURE.md` | Web navigation and extraction |

---

## References

| Document | Purpose |
|----------|---------|
| `references/confidence-research/CONFIDENCE_RESEARCH.md` | Academic research on LLM calibration |
| `references/obsidian-integration/OBSIDIAN_INTEGRATION.md` | Obsidian vault integration patterns |
| `references/superpowers-coding/` | Coding skill patterns (TDD, debugging, verification) |

---

## Plans

| Document | Purpose | Status |
|----------|---------|--------|
| `plans/next-phase-panda.md` | Roadmap and next-phase goals | Active |
| `plans/N8N_INTEGRATION.md` | n8n workflow orchestration | Planned |

---

## Archived

| Document | Notes |
|----------|-------|
| `archived/pandaaiv2.md` | Historical system overview |
| `archived/FRACTAL_ARCHITECTURE.md` | Fractal design patterns (superseded) |
| `archived/INTENT_SYSTEM_MIGRATION.md` | Intent refactor (completed) |
| `archived/URL_VALIDATION_FIX_PLAN.md` | URL validation fixes |
| `archived/IMPLEMENTATION_PLAN.md` | Old implementation plan |

---

**Last Updated:** 2026-02-04
