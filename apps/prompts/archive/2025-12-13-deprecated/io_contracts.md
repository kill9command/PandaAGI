# JSON I/O Contracts

## Solver Output
- `analysis`: free text (internal)
- `requests[]`: NL messages to Thinking
- `tool_intent`: optional high-level action for Orchestrator in ACT mode
- `needs_more_context`: boolean
- `final`: final answer string (when done)

## Thinking Output
- `plan[]`: tool calls with safe caps
- `notes`: NoteFrames {facts, open_qs, decisions, todos}
- `save_plan`: optional {title, tags[], body_md, ttl_days?}

## Tool intents & Orchestrator flow
- `tool_intent`: high-level action object that the Solver may emit in Act Mode for the Orchestrator/Gateway to execute. Intended to be a small JSON object with clear action names and payloads. Examples:
  - {"action":"save_memory","payload":{"title":"...", "tags":["..."], "body_md":"...", "importance":5, "ttl_days":null}}
  - {"action":"file.create","payload":{"file_path":"...", "content":"..."}}
  - {"action":"run_command","payload":{"cmd":"...", "cwd":"...", "requires_confirm":true}}
- Orchestrator behavior:
  - Validate `tool_intent` payloads (redaction, size checks).
  - In Chat Mode: attach `requires_confirm=true` to mutating intents and surface to user for approval (the Gateway may prompt).
  - In Act Mode: execute intents immediately if whitelisted and passed validation; otherwise require manual approval.
  - Log all mutating intents to audit JSONL.

### Commerce and spreadsheet tools
- `web.fetch_text` (read-only):
  ```
  {
    "tool": "web.fetch_text",
    "args": {
      "url": "https://www.thingiverse.com/thing:3492360"
    }
  }
  ```
  Response:
  ```
  {
    "url": "https://www.thingiverse.com/thing:3492360",
    "status": 200,
    "title": "Remix Rizzler Cinewhoop",
    "content": "Printable BOM..."
  }
  ```
  - Primary mechanism for gathering BOM data. Parse `content` into structured parts before consulting SerpAPI.
  - When `content` is empty or status ≥400, fall back to `commerce.search_offers` or prompt the user for alternate sources.
- `bom.normalize` (read-only):
  ```
  {
    "tool": "bom.normalize",
    "args": {
      "content": "Frame\n4x Motor Mounts\nESC - 30A",
      "source": "https://www.thingiverse.com/thing:3492360"
    }
  }
  ```
  Response:
  ```
  {
    "rows": [
      {"part": "Frame", "quantity": 1, "source": "https://..."},
      {"part": "Motor Mounts", "quantity": 4, "source": "https://..."},
      {"part": "ESC", "quantity": 1, "notes": "30A", "source": "https://..."}
    ],
    "count": 3
  }
  ```
  - Feeds normalized rows into subsequent spreadsheet + memory steps. Caller is responsible for enriching with pricing (via SerpAPI or manual inputs).
- `bom.build` (read/write):
  ```
  {
    "tool": "bom.build",
    "args": {
      "url": "https://www.thingiverse.com/thing:3492360",
      "repo": "/path/to/project",
      "format": "csv",
      "use_serpapi": false
    }
  }
  ```
  Response:
  ```
  {
    "status": "ok",
    "rows": [{"part": "Frame", "quantity": 1, ...}, ...],
    "spreadsheet_path": "/path/to/project/bom_20251104_123456.csv",
    "message": null,
    "source_url": "https://www.thingiverse.com/thing:3492360"
  }
  ```
  - Performs fetch → normalize → optional SerpAPI pricing → spreadsheet write in one call.
  - Status values: `ok`, `content_empty`, `pricing_missing`, `fetch_failed`. Solver should surface non-`ok` statuses instead of guessing parts.
- `commerce.search_offers` (read-only, allowed in Chat & Continue):
  ```
  {
    "tool": "commerce.search_offers",
    "args": {
      "query": "diatone roma f35 frame",
      "extra_query": "cinewhoop drone",
      "max_results": 5,
      "country": "us",
      "language": "en"
    }
  }
  ```
  Response:
  ```
  {
    "offers": [
      {
        "title": "Diatone Roma F3.5 Frame",
        "link": "https://store.example.com/roma",
        "source": "Example Store",
        "price": 89.99,
        "currency": "USD",
        "price_text": "$89.99",
        "availability": "In Stock",
        "position": 1
      }
    ],
    "best_offer": { ...lowest numeric price... },
    "summary": "1 offer(s) found for query 'diatone roma f35 frame'. Best offer 89.99 USD at Example Store."
  }
  ```
  - Uses SerpAPI shopping; requires `SERPAPI_API_KEY` in the environment.
  - Gateway ensures the tool is discoverable in both Chat and Continue modes.
  - If SerpAPI returns zero offers, the Solver must report “No offers found” and request clarification instead of inventing a list.

- `docs.write_spreadsheet` (mutating, Continue mode):
  ```
  {
    "tool": "docs.write_spreadsheet",
    "args": {
      "repo": "/path/to/project",
      "rows": [
        {"part": "Frame", "quantity": 1, "price": 89.99, "link": "..."},
        {"part": "Flight Controller", "quantity": 1, "price": 129.00, "link": "..."}
      ],
      "filename": "cinewhoop_parts.csv",
      "format": "csv"
    }
  }
  ```
  Response:
  ```
  {
    "path": "/path/to/project/cinewhoop_parts.csv",
    "format": "csv",
    "rows": 2,
    "columns": ["part","quantity","price","link"]
  }
  ```
  - `repo` must be under `REPOS_BASE`; Gateway injects it automatically when the session is tied to a repo.
  - Supported formats: `csv` (default), `ods` (requires odfpy). The tool returns the relative path and column ordering for follow-up actions.

### Memory save heuristic
- Any priced bill of materials, component sourcing guide, or reusable troubleshooting flow **must** trigger a `suggest_memory_save` proposal:
  ```
  {
    "title": "Drone parts: Remix Rizzler Cinewhoop",
    "tags": ["drone","parts_list","pricing"],
    "body_md": "## Bill of materials\n| Part | Qty | Price | Retailer | Link |\n| ... |\n\nSources: ...",
    "importance": 6,
    "ttl_days": null
  }
  ```
- If the Solver believes the result is not worth saving (e.g., incomplete data), it should include a short justification in `analysis` and still surface a warning to the user.

## Save plan vs suggest_memory_save
- `save_plan` (Thinking) and `suggest_memory_save` (Solver) semantics:
  - Both represent requests to persist memory-like artifacts; `save_plan` originates from Thinking, `suggest_memory_save` originates from Solver.
  - Schema:
    { "title": "string", "tags": ["string"], "body_md": "string", "importance": int(1-10), "ttl_days": int|null }
- Persistence flow:
  - Orchestrator applies redaction policies (remove secrets, keys).
  - For very large bodies, persist only digest+path and a short summary rather than full content.
  - After redaction and validation, Orchestrator either:
    - In Chat Mode: mark requires_confirm and persist after user approval.
    - In Act Mode: persist if whitelisted or policy allows.
  - Update `panda_system_docs/memory/index.json` and enqueue embedding generation if configured.

## Confirmations & auditing
- All mutating actions (file writes, memory saves, commands) must be recorded in an audit JSONL with timestamp, actor, action, payload (redacted), and confirmation status.
Orchestrator should emit a transcript entry for each loop containing `solver_self_history`, returned NoteFrames, proposed `tool_intents`, and the `termination_reason`.

SearchRequest / SearchResult I/O (Orchestrator integration)
- The Orchestrator exposes a testable `search_request` contract for Thinking/Solver to use when web evidence is required. A minimal SearchRequest:
  {
    "type":"search_request",
    "queries":["https://example.com/article","file:///path/to/fixture.html"],
    "fetch_mode":"http|file|playwright|search_api",
    "k_per_query":3,
    "max_pages_per_query":2,
    "follow_links":false,
    "follow_links_depth":1,
    "max_links_per_page":3,
    "deny_patterns":["login","paywall"],
    "save_raw": true,
    "persist_memory": false
  }

- The Orchestrator returns SearchResultItems (one per staged fetch) with a stable shape:
  {
    "url":"https://...",
    "title":"string",
    "snippet":"short text",
    "content_md":"full extracted text in markdown/plain-text",
    "token_est":1234,
    "score":0.0,
    "source":"web|search_api|file",
    "domain":"example.com",
    "fetched_at":"ISO8601",
    "staged_path":"panda_system_docs/scrape_staging/<uuid>/"
  }

Memory JSON schema & md→json conversion (scripts/memory_schema.py)
- Minimal memory JSON record schema:
  {
    "id":"uuid4",
    "title":"short title",
    "created_at":"ISO8601",
    "tags":["tag1","tag2"],
    "summary":"<=200 chars",
    "facts":["fact1","fact2"],
    "body_md":"full markdown text",
    "source":"agent|imported|manual",
    "token_est":345,
    "ttl_days":null
  }
- A helper script `scripts/memory_schema.py` should:
  - Convert a markdown file (or staged scrape content) into the minimal JSON record (generate id, estimate tokens, extract a short summary).
  - Optionally update `panda_system_docs/memory/index.json` mapping tags → ids + metadata.
  - This script is a stand-alone utility callable by Orchestrator or CI to bootstrap memory JSON from MD files.

Orchestrator memory_manager hooks (orchestrator/memory_manager.py)
- Responsibilities:
  - Accept `suggest_memory_save` or `save_plan` payloads from Solver/Thinking.
  - Apply redaction filters (drop secrets, API keys).
  - Persist JSON memory records under `panda_system_docs/memory/json/<id>.json`.
  - Update `panda_system_docs/memory/index.json`.
  - Enqueue optional embedding creation (if embedding pipeline enabled).
  - Respect Chat vs Act Mode persistence policies (requires_confirm, whitelist).
- Audit:
  - Record all persistence attempts to audit JSONL with timestamp, source_role, action, redacted_payload, and confirm_status.

Gateway recap + memory lifecycle
- Short-term memories are stored via `/memory.create` with a default 2-day TTL and cached in-process (`RECENT_SHORT_TERM`) so recap questions can replay the latest turn.
- Long-term memories live under `panda_system_docs/memory/long_term/json/` and are created either explicitly or when short-term notes expire and auto-promote.
- When the user asks a recap question (e.g., “what were we just talking about?”), the Gateway injects a `Recent conversation summary` system message before calling the solver and expects the response to restate those facts first.
- The solver prompt also instructs the model to restate injected context; if the model ignores it, the Gateway falls back to a deterministic recap so the user still sees the correct summary.
- Operators can inspect both scopes without reading JSON manually:
  - `python scripts/memory_admin.py list --scope short_term --limit 10` shows the latest cached turns (TTL, summary, metadata).
  - Add `--json` for machine-readable output or `--include-body` to preview bodies (useful when deciding whether to promote or prune).
  - Use `--scope long_term` to review promoted items; check `metadata.promoted_from` to trace provenance.
- Per-user memories:
  - Profiles live in `profiles.json`; each profile defines prompts, allowed tools, and memory identifiers (`memory_user`, optional `shared_user`).
  - Gateway passes the selected `user_id` to `/memory.create` and `/memory.query` so the orchestrator stores data under `MEMORY_ROOT/users/<id>`; shared profiles (e.g., `family`) receive a mirrored copy when defined.
  - The memory admin CLI accepts `--user <id>` to target a specific profile’s store (default: `default`).
- Recap troubleshooting playbook:
  1. Run the CLI (short_term scope) to confirm the previous turn was saved and that the topic matches the recap question.
  2. Review `transcripts/verbose/<date>/<trace_id>.json` — `injected_context` should contain `Recent conversation summary`.
  3. If the solver answer omitted the summary, expect the deterministic fallback; otherwise, use the CLI to prune or adjust TTLs as needed.
- Follow-up phrasing such as “tell me more about this/that” also triggers the cached summary injection even when the user doesn’t explicitly say “what were we just talking about,” keeping pronoun-heavy questions grounded in the last saved topic. The Gateway maintains a rolling conversation buffer and rewrites pronoun-heavy follow-ups with the latest topic before calling the solver (the rewrite is logged in the trace for audit), and this applies to both Chat and Continue modes.

I/O contract reminders
- Thinking and Solver should use the SearchRequest contract when requesting web evidence.
- Orchestrator will stage results under `panda_system_docs/scrape_staging/<uuid>/` and return SearchResultItems pointing to staged_path.
- Persistence from staged to permanent memory must be explicit (suggest_memory_save or save_plan) or user-confirmed in Chat Mode.
