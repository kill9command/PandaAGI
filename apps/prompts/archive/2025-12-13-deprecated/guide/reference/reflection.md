# Reflection Protocol Reference

## 🧠 Reflection Protocol

### Phase 1 - PLAN (before ticket)

Include in ticket's `reflection` field:
- **Strategy**: Single-phase or multi-phase?
- **Assumptions**: What are we assuming? (intent, data sources, constraints)
- **Risks**: What could fail? (wrong results, API errors, empty data, filtering issues)
- **Success criteria**: How do we know it succeeded? (e.g., "≥3 verified listings")

### Phase 3 - REVIEW (after capsule)

Check `quality_report`:
- Quality score above threshold? (typically >30%)
- Met success criteria from Phase 1?
- If not: Gateway may auto-retry with refinement

### Loop Discipline

- Max ONE ticket per turn (exception: empty/conflict capsule or quality retry needed)
- Code operations with status:"ok" → emit ANSWER immediately (no verification ticket)
- Final answer ≤500 tokens
