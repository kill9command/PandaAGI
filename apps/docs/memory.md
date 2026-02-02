# Memory Model

## Types

- `scratch_note` — ephemeral, expires 24–72h.
- `memory_file` — Markdown/JSONL under `/mem/{topic}/{slug}.md`.
- `memory_index` — Qdrant collection; metadata: repo, topic, tags, sha.

## Save Policy

Save when:
- cross‑task utility,
- hard‑won derivations,
- API schemas, repo maps, design decisions.

Do **not** save:
- secrets/keys/tokens,
- huge raw files (save digest + path).

## Re-injection

Top‑k (k ≤ 6) memories + a Thinking‑compressed **memory_pack** ≤ 1500 tokens.
