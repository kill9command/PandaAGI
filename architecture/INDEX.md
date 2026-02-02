# Architecture Index

This index lists all current architecture documents with short summaries to
speed up navigation for both humans and LLMs.

---

## Start Here

- `architecture/README.md` - Canonical system summary, phases, services, and doc map.

---

## Core Context

- `architecture/next-phase-pandora.md` - Roadmap and next-phase goals for the project.
- `architecture/LLM-ROLES/llm-roles-reference.md` - Model stack definitions and phase role specs.
- `architecture/prompting-manual/prompting-manual-5stack.md` - Prompting guidance for the single-model system.
- `architecture/prompting-manual/V2_PROMPT_STYLE.md` - **NEW** V2 prompt style guide (abstract, concise, table-driven).

---

## Phase Specifications (9-Phase Pipeline)

- `architecture/main-system-patterns/phase0-query-analyzer.md` - Intent classification and query parsing.
- `architecture/main-system-patterns/phase1-reflection.md` - PROCEED vs CLARIFY gate and reflection logic.
- `architecture/main-system-patterns/phase2-context-gathering.md` - Retrieval of relevant memory and context.
- `architecture/main-system-patterns/phase3-planner.md` - Strategic planning with goals and approach.
- `architecture/main-system-patterns/phase4-executor.md` - **NEW** Tactical decisions, natural language commands.
- `architecture/main-system-patterns/phase5-coordinator.md` - Tool Expert: translates commands to tool calls.
- `architecture/main-system-patterns/phase6-synthesis.md` - User-facing response construction.
- `architecture/main-system-patterns/phase7-validation.md` - Quality checks and retry logic.
- `architecture/main-system-patterns/phase8-save.md` - Persistence, indexing, and turn archival.

---

## System Patterns

- `architecture/main-system-patterns/PLANNER_EXECUTOR_COORDINATOR_LOOP.md` - 3-tier loop design (Planner → Executor → Coordinator).
- `architecture/main-system-patterns/WORKFLOW_SYSTEM.md` - **NEW** Declarative workflow definitions and execution.
- `architecture/main-system-patterns/ERROR_HANDLING.md` - Failure modes and recovery strategies.
- `architecture/main-system-patterns/INJECTION_SYSTEM.md` - Controlled context injection system.
- `architecture/main-system-patterns/UNIVERSAL_CONFIDENCE_SYSTEM.md` - Confidence scoring patterns.
- `architecture/main-system-patterns/USER_FEEDBACK_SYSTEM.md` - Feedback capture and learning signals.
- `architecture/main-system-patterns/code-mode-architecture.md` - Code-mode behavior and constraints.

---

## Document IO System

- `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` - Document flow and `context.md` schema.
- `architecture/DOCUMENT-IO-SYSTEM/CONTEXT-DOCUMENT-LOG.md` - Turn document logging and conventions.
- `architecture/DOCUMENT-IO-SYSTEM/MEMORY_ARCHITECTURE.md` - Memory retrieval and caching design.
- `architecture/DOCUMENT-IO-SYSTEM/OBSERVABILITY_SYSTEM.md` - Metrics, tracing, and decision logs.
- `architecture/DOCUMENT-IO-SYSTEM/PROMPT_MANAGEMENT_SYSTEM.md` - Prompt recipes and summarization flow.

---

## Prompt System

- `architecture/PROMPT_INVENTORY.md` - Current inventory of all prompts and recipes by category.
- `architecture/PROMPT_SYSTEM_REFACTOR_PLAN.md` - Completed refactor plan (January 2026).
- `architecture/prompting-manual/V2_PROMPT_STYLE.md` - **V2 prompt style**: Abstract examples, tables over prose, 150-line target.
- `apps/prompts/README.md` - Detailed prompt system documentation (canonical reference).
- `PROMPT_CLEANUP_PLAN.md` - Migration checklist for V2 style (February 2026).

---

## Tooling and Services

- `architecture/services/orchestrator-service.md` - Tool execution service and interface.
- `architecture/services/user-interface.md` - Web interface (SvelteKit), VSCode extension, CLI.
- `architecture/services/OBSIDIAN_MEMORY.md` - **Forever memory system** for persistent knowledge across sessions.
- `architecture/mcp-tool-patterns/internet-research-mcp/INTERNET_RESEARCH_ARCHITECTURE.md` - Web research tool flow.
- `architecture/mcp-tool-patterns/internet-research-mcp/WEB_AGENT_ARCHITECTURE.md` - **Unified web navigation and extraction** (WebAgent).

---

## Infrastructure

- `architecture/services/DOCKER-INTEGRATION/DOCKER_ARCHITECTURE.md` - Docker services and deployment strategy.

---

## Integrations

- `architecture/integrations/N8N_INTEGRATION.md` - n8n workflow orchestration integration (Phase API).

---

## Archived

- `architecture/archived/pandaaiv2.md` - Historical system overview (archived).

---

Last Updated: 2026-02-02
