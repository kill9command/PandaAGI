# Guardrails

## Risks & Mitigations

- **Forever loops** → cap to 3 cycles; require unmet-info list; stop or ask user.
- **Token bloat** → per‑tool `max_tokens`; pack compression; budget shrinker.
- **Tool abuse** → `act` gate + diff preview + per-path whitelist + audit.
- **Hallucinated paths** → Orchestrator verifies existence; returns `not_found`.
- **Secret leakage** → redaction + deny memory.create when secrets detected.

## Decision Hardpoints

- If Solver returns `needs_more_context=true` without a concrete ask → terminate.
- If Orchestrator returns 0 hits twice → terminate with gap summary.
- Write operations require either **user confirm** or safe-list match.
