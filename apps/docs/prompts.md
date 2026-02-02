# Prompts — Roles and Usage

Files
- `project_build_instructions/prompts/solver_system.md` — Guide (Planner/Speaker)
- `project_build_instructions/prompts/thinking_system.md` — Coordinator (Worker/Operator)
- `project_build_instructions/prompts/context_manager.md` — Context Manager (Reviewer/Reducer)
- `project_build_instructions/prompts/io_contracts.md` — legacy summaries of earlier schemas (will be updated to reference task tickets/bundles/capsules)

When used
- Gateway prepends `solver_system.md` to Guide requests.
- Gateway prepends `thinking_system.md` to Coordinator requests.
- Gateway (or a dedicated reducer call) prepends `context_manager.md` when converting Raw Bundles to Distilled Capsules.
- Guide is tool-agnostic: it delegates in natural language. Coordinator owns the tool catalog (`purchasing.lookup`, `doc.search`, `bom.build`, etc.). Context Manager enforces evidence discipline and emits claims/caveats.

Editing
- In P2, the Web UI “Prompts” panel lets you list, view, and update these files via Gateway endpoints (`/prompts`).
- Saved to disk; takes effect on the next request.

Formatting
- Where a model must emit JSON, allow fenced code blocks and the Gateway will extract JSON. Each role now has a strict schema:
  - Guide → Task Ticket or final answer (see `solver_system.md`).
  - Coordinator → Raw Bundle (`thinking_system.md`).
  - Context Manager → Distilled Capsule (`context_manager.md`).
  ```json
  { "ticket_id": "pending", "status": "ok", "claims": [...], ... }
  ```
