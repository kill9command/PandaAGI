# Pandora AGI

> Context-orchestrated LLM stack implementing single-model multi-role reflection

Pandora is an experimental AI system that uses a single LLM to play multiple roles through an 8-phase document pipeline. Rather than using separate models for different tasks, one model (Qwen3-Coder-30B-AWQ) adopts different "roles" with distinct temperatures and prompting strategies.

## Key Concepts

### Single-Model Multi-Role Architecture
Instead of routing to specialized models, Pandora uses role-based temperature control:

| Role | Temp | Purpose |
|------|------|---------|
| REFLEX | 0.3 | Classification, gates, quick decisions |
| NERVES | 0.1 | Compression, summarization |
| MIND | 0.5 | Reasoning, planning, analysis |
| VOICE | 0.7 | User-facing dialogue |

### 8-Phase Document Pipeline
Every query flows through a structured pipeline where each phase writes to a shared `context.md` document:

```
Phase 0: Query Analyzer    → Classify intent, resolve references
Phase 1: Reflection        → PROCEED | CLARIFY gate
Phase 2: Context Gatherer  → Search memory, retrieve relevant context
Phase 3: Planner           → Task decomposition and planning
Phase 4: Coordinator       → Tool execution (includes research)
Phase 5: Synthesis         → Generate final response
Phase 6: Validation        → APPROVE | REVISE | RETRY | FAIL
Phase 7: Save              → Persist turn, update indexes
```

### Research as a Tool
Research isn't a separate system—it's a tool that runs inside Phase 4 (Coordinator). The same reflection and validation patterns apply to research operations.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Gateway (port 9000)                     │
│  FastAPI service handling chat, SSE streaming, job mgmt     │
├─────────────────────────────────────────────────────────────┤
│                    Unified Flow Pipeline                     │
│  Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7                        │
│  Each phase reads/writes context.md                          │
├─────────────────────────────────────────────────────────────┤
│                  Orchestrator (port 8090)                    │
│  MCP tool execution: browser, search, file ops              │
├─────────────────────────────────────────────────────────────┤
│                     vLLM (port 8000)                         │
│  Qwen3-Coder-30B-AWQ model serving                          │
└─────────────────────────────────────────────────────────────┘
```

## Hardware Requirements

- **GPU:** RTX 3090 or equivalent (24GB VRAM minimum)
- **RAM:** 32GB recommended
- **Storage:** 100GB for models

## Quick Start

1. **Clone and configure**
   ```bash
   git clone https://github.com/yourusername/pandaagi.git
   cd pandaagi
   cp .env.example .env
   # Edit .env with your API keys (SerpAPI for search)
   ```

2. **Download models**
   ```bash
   ./scripts/get_models.sh
   ```

3. **Start services**
   ```bash
   ./scripts/start.sh
   ```

4. **Access the UI**
   ```
   http://localhost:9000
   ```

## Project Structure

```
pandaagi/
├── architecture/          # System specifications and design docs
│   ├── README.md          # Start here for architecture overview
│   ├── INDEX.md           # Complete documentation index
│   └── main-system-patterns/  # Phase-by-phase specifications
├── apps/
│   ├── services/
│   │   ├── gateway/       # FastAPI webapp
│   │   └── orchestrator/  # Tool execution service
│   ├── prompts/           # LLM prompts organized by function
│   ├── phases/            # Phase implementations
│   └── ui/                # SvelteKit frontend
├── libs/
│   ├── gateway/           # Pipeline implementation
│   ├── llm/               # LLM client
│   └── core/              # Config, logging, models
├── scripts/               # Start/stop/test scripts
└── tests/                 # Test suite
```

## Documentation

- **[Architecture Overview](architecture/README.md)** — System design and philosophy
- **[Documentation Index](architecture/INDEX.md)** — Navigate 90+ architecture docs
- **[Development Guide](CLAUDE.md)** — Contributing and debugging
- **[Debug Protocol](DEBUG.md)** — Systematic debugging methodology

## Design Philosophy

### Quality Over Speed
Pandora prioritizes correct, high-quality answers over response time. There are no arbitrary timeouts that return partial results.

### LLM Context Discipline
When an LLM makes a bad decision, the fix is always better context—not programmatic workarounds. No hardcoded rules that bypass LLM judgment.

### Document-Driven State
All state flows through `context.md`. Each phase reads what previous phases wrote and appends its own section. This creates an auditable trail of reasoning.

## Tech Stack

- **Model:** Qwen3-Coder-30B-AWQ via vLLM
- **Backend:** FastAPI (Python 3.11+)
- **Frontend:** SvelteKit
- **Browser Automation:** Playwright
- **Search:** SerpAPI
- **Vision:** EasyOCR (CPU-based)

## Status

This is an experimental research project exploring agentic AI architectures. It's a working system but expect rough edges.

## License

[License to be determined]
