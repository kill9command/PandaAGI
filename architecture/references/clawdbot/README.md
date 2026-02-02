# Clawdbot Reference Documentation

**Source:** https://clawd.bot / https://github.com/clawdbot/clawdbot
**Author:** Peter Steinberger
**GitHub Stars:** 44k+ (9k in first day)
**Documentation:** https://docs.clawd.bot

---

## What is Clawdbot?

Clawdbot is an open-source, local-first personal AI assistant that operates through messaging platforms (WhatsApp, Telegram, Discord, Slack, Signal, iMessage). It runs on your own hardware, keeping data private.

## Why Study Clawdbot?

Clawdbot solves several problems that Pandora could benefit from:

| Problem | Clawdbot Solution | Relevance to Pandora |
|---------|-------------------|---------------------|
| Multi-channel access | Gateway bridges 12+ messaging platforms | Pandora is web-only |
| Long-term memory | Workspace files + memory flush before compaction | Pandora has turn-based sessions |
| Scheduled tasks | Cron jobs, heartbeats, proactive background ops | Pandora is purely reactive |
| Extensibility | Hot-reloadable skills + hooks system | Pandora requires restarts for MCP changes |
| Context management | Auto-compaction with pre-flush memory preservation | Pandora has fixed context windows |
| Workflow automation | Lobster typed pipelines with approval gates | Pandora has no workflow engine |

---

## Documentation Index

| File | Contents |
|------|----------|
| [architecture.md](./architecture.md) | Gateway-centric design, session model, security |
| [agent-loop.md](./agent-loop.md) | Agent execution, prompting, streaming |
| [system-prompt.md](./system-prompt.md) | Prompt assembly, workspace files, bootstrap |
| [skills-and-tools.md](./skills-and-tools.md) | Skill format, tool definitions, dispatch |
| [hooks-and-extensions.md](./hooks-and-extensions.md) | Event system, extension API, lifecycle |
| [lobster-workflows.md](./lobster-workflows.md) | Typed pipelines, approval gates, automation |
| [memory-and-compaction.md](./memory-and-compaction.md) | Memory management, compaction, pruning |
| [configuration.md](./configuration.md) | Config structure, agent defaults, channels |

---

## Key Takeaways for Pandora

### 1. Gateway Architecture
Clawdbot's single WebSocket gateway (`ws://127.0.0.1:18789`) acts as the control plane for all messaging surfaces, tools, and sessions. This is similar to Pandora's Gateway (port 9000) but more modular.

**Pandora opportunity:** Abstract the Gateway to support additional input channels (Telegram bot, etc.)

### 2. Workspace-Based Memory
Clawdbot uses markdown files in a workspace directory (`~/clawd/`) for persistent memory:
- `AGENTS.md` - Operating instructions
- `SOUL.md` - Persona/personality
- `TOOLS.md` - Tool instructions
- `USER.md` - User preferences
- `memory/YYYY-MM-DD.md` - Daily notes

**Pandora opportunity:** Implement a similar file-based memory system alongside turns.

### 3. Pre-Compaction Memory Flush
Before auto-compacting, Clawdbot runs a silent turn to persist important notes to disk. This prevents memory loss during compaction.

**Pandora opportunity:** Add a memory extraction step before context truncation.

### 4. Minimal System Prompt (<1000 tokens)
Pi-mono (Clawdbot's agent runtime) uses an extremely minimal system prompt, relying on AGENTS.md files for customization. The philosophy: frontier models already understand coding agents from RL training.

**Pandora opportunity:** Audit prompt sizes; consider moving instructions to context files.

### 5. Skills with Progressive Disclosure
Skills are listed in the system prompt as compact XML. The agent reads skill files on-demand rather than including all instructions upfront. This saves tokens.

**Pandora opportunity:** Consider lazy-loading tool documentation.

### 6. Heartbeat System
Every 30 minutes, the agent runs a full turn with a fixed prompt to check `HEARTBEAT.md` for pending tasks. This enables proactive behavior.

**Pandora opportunity:** Add scheduled/proactive research capabilities.

### 7. Lobster Workflow Engine
Typed pipelines with approval gates allow deterministic multi-step workflows without LLM orchestration overhead. The LLM calls `lobster run workflow.lobster` and gets structured JSON back.

**Pandora opportunity:** Consider a similar workflow layer for complex research patterns.

---

## Architecture Comparison

| Aspect | Clawdbot | Pandora |
|--------|----------|---------|
| **Model** | Claude/GPT/local (user choice) | Qwen3-Coder-30B-AWQ (fixed) |
| **Architecture** | Gateway + Pi agent (RPC) | 8-phase document pipeline |
| **IO Model** | Tool streaming + block streaming | Document-based (context.md) |
| **Memory** | Workspace files + session JSONL | Turn documents + transcripts |
| **Tools** | read/write/edit/bash + skills | MCP tools in orchestrator |
| **Extensibility** | Hot-reload skills/hooks/extensions | Requires service restart |
| **Scheduling** | Cron + heartbeats | None (reactive only) |
| **Channels** | 12+ messaging platforms | Web UI only |

---

## Sources

- [Clawd.bot Official Site](https://clawd.bot/)
- [GitHub - clawdbot/clawdbot](https://github.com/clawdbot/clawdbot)
- [Clawdbot Documentation](https://docs.clawd.bot)
- [Pi-mono (underlying agent)](https://github.com/badlogic/pi-mono)
- [Mario Zechner's Blog on Pi Agent](https://mariozechner.at/posts/2025-11-30-pi-coding-agent/)
- [Lobster Workflow Engine](https://github.com/clawdbot/lobster)
