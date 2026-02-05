# Pandora AGI

> Context-orchestrated LLM stack implementing single-model multi-role reflection

Pandora is an experimental AI system that uses a single LLM to play multiple roles through an 8-phase document pipeline. Rather than routing to specialized models, one model (Qwen3-Coder-30B-AWQ) adopts different "roles" with distinct temperatures and prompting strategies.

## Goal

Pandora is a self-adapting agent that interfaces with digital systems on behalf of its user. It reads documents, writes files, searches the web, manages tasks, navigates browsers, and can build tools it doesn't have yet. It runs locally on consumer hardware.

The end state is an agent that can handle any task a human does at a computer—not by having every tool pre-built, but by understanding what's needed and building or adapting to get it done.

## Key Concepts

### Single-Model Multi-Role Architecture

One LLM plays all roles. Behavior is controlled by temperature and system prompts:

| Role | Temp | Purpose |
|------|------|---------|
| NERVES | 0.1 | Compression, summarization |
| REFLEX | 0.3-0.4 | Classification, gates, binary decisions |
| MIND | 0.5-0.6 | Reasoning, planning, analysis |
| VOICE | 0.7 | User-facing dialogue |

### 8-Phase Document Pipeline

Every query flows through a structured pipeline where each phase reads the accumulated `context.md` document, does its work, and writes its section for the next phase:

| Phase | Name | Role | Purpose |
|-------|------|------|---------|
| 0 | Query Analyzer | REFLEX | Resolve references, capture user purpose + data requirements |
| 1 | Reflection | REFLEX | PROCEED \| CLARIFY gate |
| 2.1 | Context Retrieval | MIND | Identify relevant sources (turns, memory, cache) |
| 2.2 | Context Synthesis | MIND | Compile gathered context into working document |
| 3 | Planner | MIND | Define goals and strategic approach |
| 4 | Executor | MIND | Produce tactical natural language commands |
| 5 | Coordinator | MIND | Translate commands to tool calls, execute tools |
| 6 | Synthesis | VOICE | Generate user-facing response |
| 7 | Validation | MIND | Verify accuracy, approve or retry |
| 8 | Save | Procedural | Persist turn, update indexes |

**Validation sub-phases:** Phase 1.5 (Query Validator) and Phase 2.5 (Context Validator) ensure coherence and completeness.

### Document-Driven State

All state flows through documents per turn:
- `context.md` — Accumulated working document. Each phase reads prior sections, appends its own.
- `plan_state.json` — Goals and execution progress.
- `toolresults.md` — Full tool outputs for synthesis and validation.

### Recipe System

Every LLM call is defined as a YAML recipe paired with a markdown prompt. Recipes specify token budgets, role assignment, and input/output documents. This enables token governance, testability, and observability.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Gateway (port 9000)                     │
│  FastAPI service handling chat, SSE streaming, job mgmt     │
├─────────────────────────────────────────────────────────────┤
│                    Unified Flow Pipeline                     │
│  Phase 0 → 1 → 2.1 → 2.2 → 3 → 4 → 5 → 6 → 7 → 8           │
│  Each phase reads/writes context.md                          │
├─────────────────────────────────────────────────────────────┤
│                   Tool Server (port 8090)                    │
│  MCP tool execution: browser, search, files, code, etc.     │
├─────────────────────────────────────────────────────────────┤
│                     vLLM (port 8000)                         │
│  Qwen3-Coder-30B-AWQ model serving                          │
└─────────────────────────────────────────────────────────────┘
```

### Model Stack

| Component | Model | Server | Notes |
|-----------|-------|--------|-------|
| All text roles | Qwen3-Coder-30B-AWQ | vLLM (:8000) | Single model, temperature-controlled |
| Vision | EasyOCR | CPU | OCR-based extraction |
| Embedding | all-MiniLM-L6-v2 | CPU | Semantic search |

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
   # Edit .env with your settings
   ```

2. **Set up environment**
   ```bash
   conda env create -f environment.yml
   conda activate pandaagi
   ```

3. **Download models**
   ```bash
   ./scripts/get_models.sh
   ```

4. **Start services**
   ```bash
   ./scripts/start.sh
   ```

5. **Access the UI**
   ```
   http://localhost:9000
   ```

### Utility Scripts

```bash
./scripts/start.sh        # Start all services (vLLM, Tool Server, Gateway)
./scripts/stop.sh         # Stop all services
./scripts/health_check.sh # Check service health
./scripts/serve_llm.sh    # Start vLLM standalone
```

## Project Structure

```
pandaagi/
├── architecture/              # System specifications and design docs
│   ├── README.md              # Architecture overview
│   ├── INDEX.md               # Complete documentation index (90+ docs)
│   ├── main-system-patterns/  # Phase-by-phase specifications
│   ├── concepts/              # Cross-cutting patterns
│   └── LLM-ROLES/             # Model stack and role definitions
│
├── apps/
│   ├── services/
│   │   ├── gateway/           # FastAPI webapp (pipeline orchestration)
│   │   └── tool_server/       # MCP tool execution service
│   ├── phases/                # 8-phase pipeline implementations
│   ├── prompts/               # LLM prompts organized by function
│   ├── recipes/               # YAML recipe definitions
│   ├── ui/                    # SvelteKit frontend
│   ├── tools/                 # Tool implementations
│   ├── workflows/             # Declarative workflow definitions
│   └── tests/                 # Integration and unit tests
│
├── libs/
│   ├── gateway/               # Pipeline implementation (unified_flow.py)
│   ├── llm/                   # LLM client (vLLM wrapper)
│   ├── core/                  # Config, logging, models
│   ├── document_io/           # Document management
│   └── compression/           # Context compression
│
├── scripts/                   # Startup and utility scripts
├── config/                    # Configuration files
├── static/                    # Built frontend assets
├── .env.example               # Configuration template
└── environment.yml            # Conda environment specification
```

## Configuration

Key settings in `.env`:

| Setting | Purpose |
|---------|---------|
| `SOLVER_URL` | vLLM endpoint for LLM calls |
| `SOLVER_MODEL_ID` | Model identifier |
| `SOLVER_API_KEY` | API key for local vLLM |
| `BROWSER_DEFAULT_MODE` | `local_view` (CAPTCHA support) or `headless` |
| `PLAYWRIGHT_HEADLESS` | Browser visibility |
| `UNIFIED_FLOW_ENABLED` | Enable 8-phase pipeline (required) |

See `.env.example` for full configuration options.

## Documentation

| Need | Go To |
|------|-------|
| Architecture overview | `architecture/README.md` |
| Full documentation index | `architecture/INDEX.md` |
| Phase specifications | `architecture/main-system-patterns/phase*.md` |
| Concept docs | `architecture/concepts/*.md` |
| Development guide | `CLAUDE.md` |
| Debug protocol | `DEBUG.md` |

## Design Philosophy

### Quality Over Speed
Pandora prioritizes correct, high-quality answers over response time. There are no arbitrary timeouts that return partial results.

### LLM Context Discipline
When an LLM makes a bad decision, the fix is always better context—not programmatic workarounds. Pass the original query to any LLM that makes decisions. No hardcoded rules that bypass LLM judgment.

### Document-Based IO
All phase communication goes through `context.md`. Each phase reads what previous phases wrote and appends its own section. No hidden state.

### Design Before Code
Architecture docs are written first. Code implements the docs. If code doesn't match docs, fix one or the other until they agree.

### Self-Building
The system can create tools and workflows it doesn't have yet. When no workflow exists for a task, the system can build one.

## Tech Stack

- **Model:** Qwen3-Coder-30B-AWQ via vLLM
- **Backend:** FastAPI (Python 3.11+)
- **Frontend:** SvelteKit + Tailwind CSS
- **Browser Automation:** Playwright
- **Search:** SerpAPI (optional)
- **Vision:** EasyOCR (CPU-based)
- **Embeddings:** all-MiniLM-L6-v2 (CPU)

## API

The Gateway exposes an OpenAI-compatible API:

```bash
curl http://localhost:9000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "pandora",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

## Status

This is an experimental research project exploring agentic AI architectures. It's a working system but expect rough edges.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
