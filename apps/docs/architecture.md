# Architecture

## Roles

- **Gateway (FastAPI)** — single ingress; serves Web UI; routes user → Solver; enforces mode/timeouts/budgets; injects memories.
- **Solver LLM — Qwen3‑30B‑Coder** — heavy reasoning; writes answers; issues *natural-language* tool requests (no direct JSON calls).
- **Thinking LLM — Qwen3‑4B‑Thinking** — context manager & planner: turns Solver asks into concrete tool plans, compresses notes, proposes memory saves.
- **Orchestrator (FastAPI)** — deterministic executor of MCP tools (doc.search, code.search, fs.read, memory.create/query, file.create, git.commit).
- **Stores**
  - *Scratch* (ephemeral notes): SQLite table (or Redis) with TTL.
  - *Long-term memory*: `/mem/` files + embeddings in Qdrant.
  - *Repos*: fs + git, and RAG corpora.

## Modes

- `chat`: read-only, RAG permitted; no repo writes.
- `plan`: read + save memories; no repo writes.
- `act`: read + gated writes/commits with audit & confirmations.

## Dataflow (Simplified)

```text
User → Gateway → Solver
  Solver → (NL ask) → Thinking → (tool plans) → Gateway → Orchestrator → results
  Gateway budgets & injects → Solver → synthesis
  (optional) memory.create → Orchestrator → memory_pack → Gateway injects → Solver
  (act mode) file.create/git.commit → Orchestrator → audit → Gateway
Answer → User
```

See `docs/process_loop.md` and `docs/guardrails.md`.

## Web UI

- Static assets under `./static` are served by Gateway at `/` and `/static/*`.
- The UI posts to `/v1/chat/completions` (Gateway shim). It also uses helper endpoints:
  - `/teach/tools`, `/broker/*` (stubs), `/ui/log`, `/continue/relay`, `/ui/repos`.
- Continue mode can relay instructions via `CONTINUE_WEBHOOK` if configured.

## Access

- Set `GATEWAY_HOST=0.0.0.0` in `.env` and restart. Open `http://<LAN_IP>:9000` from phone or laptop.
- For internet exposure, place Caddy/Nginx in front with TLS and optional auth.
