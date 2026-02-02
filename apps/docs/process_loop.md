# Process Loop & Controller

## Budgets (defaults)

- Total prompt target (Solver): 10–12k tokens
- System+tools: ≤1.2k
- User query: ≤1.5k
- Active pack (top chunks): ≤3k
- Scratch notes (compressed): ≤1k
- History summary: ≤800

## Loop States

`START → FETCH → INJECT → SOLVE → (SAVE?) → (ACT?) → ANSWER → END`

Max **3** cycles per request. If still `needs_more_context=true`, return unmet info + ask user to clarify.

## Thinking Duties

- Rank sources (BM25 + embeddings hybrid).
- Produce **NoteFrames**: `{facts, open_qs, decisions, todos}`.
- Propose **SavePlan** when notes > 1k tokens or reusable across tasks.
- Emit a **memory_pack** ≤1500 tokens.

## Guardrails

- Token caps at every boundary (Orchestrator trims, Gateway enforces).
- Mode gates: only `act` can write; confirm or whitelist files.
- Redaction filter for secrets; never save secrets in memory.
- Audit JSONL for all mutating tool calls.
- Tool timeouts: 20s (read), 45s (write).

