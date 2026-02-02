# APIs

## Gateway (external)

`POST /v1/chat/completions` — OpenAI-compatible shim routing to Solver/Thinking/Orchestrator.

### UI + Helper Endpoints
- `GET /` — serves `static/index.html`
- `GET /static/*` — serves assets from `./static`
- `GET /teach/tools` — tool list for Teach UI
- `GET /broker/providers` — available retrieval providers (stub)
- `POST /broker/request_context` — returns packed context (stub)
- `POST /broker/summarize_map` — map summaries (stub)
- `POST /broker/summarize_reduce` — reduced summary (stub)
- `POST /ui/log` — append UI turn logs to `ui.log`
- `POST /continue/relay` — optional relay to Continue webhook (`CONTINUE_WEBHOOK`)
- `GET /ui/repos` — lists repos under `REPOS_BASE` for repo picker

## Gateway ↔ Orchestrator (internal)

- `POST /orchestrator/doc.search`
- `POST /orchestrator/code.search`
- `POST /orchestrator/fs.read`
- `POST /orchestrator/memory.create`
- `POST /orchestrator/memory.query`
- `POST /orchestrator/file.create`   (act only)
- `POST /orchestrator/git.commit`    (act only)

All requests/returns are JSON. Orchestrator enforces `max_tokens` and returns `digest + path/span` for each chunk.
