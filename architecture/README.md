# PandaAI Architecture

Version: 6.1
Updated: 2026-02-02
Hardware Target: RTX 3090 Server (24GB VRAM)

---

## Overview

PandaAI is a context-orchestrated LLM stack built around a **single-model multi-role system**
with an 9-phase document pipeline. One model handles all text tasks using different
temperatures for different roles. All state flows through a single `context.md` document
per turn.

**Key Features:**
- Single model architecture: Qwen3-Coder-30B-AWQ handles all roles
- Web-accessible via FastAPI + Cloudflare tunnel
- 9-phase pipeline with document-based IO
- **Workflow-centric execution**: Declarative tool sequences replace ad-hoc decisions
- **V2 prompt style**: Concise, abstract examples, table-driven
- OCR-based vision (EasyOCR), with EYES model planned for future

---

## System Summary

### Single-Model Architecture

| Component | Model | Server | VRAM | Notes |
|-----------|-------|--------|------|-------|
| ALL ROLES | Qwen3-Coder-30B-AWQ | vLLM (8000) | ~20GB | Single model, all text tasks |
| Vision | EasyOCR | CPU | 0 | OCR-based extraction |
| Embedding | all-MiniLM-L6-v2 | CPU | 0 | Semantic search |

**Text Roles (all use the same model via temperature):**

| Role | Temperature | Purpose |
|------|-------------|---------|
| REFLEX | 0.3 | Classification, binary decisions |
| NERVES | 0.1 | Compression (low creativity) |
| MIND | 0.5 | Reasoning, planning |
| VOICE | 0.7 | User dialogue (more natural) |

### vLLM Configuration

```bash
python -m vllm.entrypoints.openai.api_server \
  --model models/qwen3-coder-30b-awq4 \
  --served-model-name qwen3-coder \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192
```

### Future: EYES Vision Model

Once the system is stable, we plan to add the EYES vision model for complex
image understanding tasks that OCR cannot handle (charts, diagrams, photos).

---

## Web Access

PandaAI is accessible via web browser through Cloudflare tunnel:

```
User Browser
    │
    ▼
Cloudflare Tunnel (HTTPS)
    │
    ▼
Gateway (port 9000) ─── FastAPI webapp
    │
    ├── Orchestrator (port 8090) ─── Tool execution
    │
    └── vLLM (port 8000) ─── LLM inference
```

**Access Methods:**
- Local: `http://localhost:9000`
- Remote: Via Cloudflare tunnel URL (configured in start.sh)

---

## 9-Phase Pipeline

| Phase | Name | Role/Temp | Purpose |
|-------|------|-----------|---------|
| 0 | Query Analyzer | REFLEX/0.3 | Classify intent, resolve references |
| 1 | Reflection | REFLEX/0.3 | PROCEED or CLARIFY gate |
| 2 | Context Gatherer | MIND/0.5 | Gather relevant context |
| 3 | Planner | MIND/0.5 | Strategic: define goals and approach |
| 4 | Executor | MIND/0.5 | Tactical: natural language commands |
| 5 | Coordinator | MIND/0.4 | Tool Expert: translate commands to tool calls |
| 6 | Synthesis | VOICE/0.7 | Generate user-facing response |
| 7 | Validation | MIND/0.5 | Verify accuracy, approve or retry |
| 8 | Save | Procedural | Persist turn, update indexes |

**Note:** All phases use the same Qwen3-Coder-30B model. Role behavior is controlled
by temperature and system prompts.

---

## Services

| Service | Port | Purpose |
|---------|------|---------|
| Gateway | 9000 | FastAPI webapp, pipeline orchestration |
| vLLM | 8000 | LLM inference (Qwen3-Coder-30B-AWQ) |
| Orchestrator | 8090 | Tool execution (file, git, research, memory) |

**Optional Services (Docker):**
| Service | Port | Purpose |
|---------|------|---------|
| Qdrant | 6333 | Vector database |
| PostgreSQL | 5432 | Relational database |

---

## Document-Based IO

- `context.md` is the single accumulated document for each turn
- Each phase reads previous sections and writes its own section
- `toolresults.md` stores full tool outputs for Synthesis and Validation

---

## Workflow System

The Phase 4 Executor uses a workflow-centric execution model where **workflows define
predictable tool sequences** instead of ad-hoc tool selection.

```
┌─────────────────────────────────────────────────────────────┐
│  Phase 4 Executor                                            │
│                                                              │
│  Command ──▶ WorkflowMatcher ──▶ WorkflowExecutor           │
│                    │                    │                    │
│                    │ no match           │ match              │
│                    ▼                    ▼                    │
│              Coordinator          Execute workflow          │
│              (fallback)           steps in sequence         │
└─────────────────────────────────────────────────────────────┘
```

**Built-in Workflows:**
- `intelligence_search` - Phase 1 informational research
- `product_search` - Phase 1 + Phase 2 commerce research
- `create_workflow` - Meta-workflow for self-extension

**See:** `architecture/main-system-patterns/WORKFLOW_SYSTEM.md`

---

## Read Order

Start with `architecture/INDEX.md` for a complete map of all architecture docs.

### Core References

- `architecture/LLM-ROLES/llm-roles-reference.md` - Model and role specs
- `architecture/main-system-patterns/phase*.md` - Phase documentation
- `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` - context.md schema
- `architecture/mcp-tool-patterns/internet-research-mcp/` - Research tool

### Services

- `architecture/services/orchestrator-service.md` - Tool execution service

---

## Directory Structure

### Architecture Documentation

```
architecture/
├── README.md                     # This file
├── INDEX.md                      # Complete doc index
├── LLM-ROLES/                    # Model roles and decision schemas
├── main-system-patterns/         # Phase docs and system patterns
├── DOCUMENT-IO-SYSTEM/           # Document IO specifications
├── mcp-tool-patterns/            # Tool architecture patterns
├── services/                     # Service documentation
└── Implementation/               # Implementation guides
```

### Code Structure

```
apps/
├── phases/                       # Phase 0-8 executors
├── services/
│   ├── gateway/                  # FastAPI webapp (port 9000)
│   └── orchestrator/             # Tool execution (port 8090)
├── prompts/                      # LLM prompts (V2 style)
├── recipes/                      # YAML recipes
└── workflows/                    # Declarative workflow definitions
    ├── research/                 # Research workflows
    └── meta/                     # Meta-workflows

libs/
├── core/                         # Config, models, exceptions
├── llm/                          # LLM client and routing
├── gateway/                      # Pipeline implementation
├── document_io/                  # Context and turn management
└── compression/                  # Smart summarization

panda_system_docs/                # Runtime data
├── users/default/
│   ├── turns/                    # Turn documents
│   ├── transcripts/              # Session transcripts
│   └── sessions/                 # Session data
└── shared_state/                 # Shared state (caches, etc.)
```

---

## Quick Start

```bash
# Start all services
./scripts/start.sh

# Stop all services
./scripts/stop.sh

# Check service health
./scripts/health_check.sh
```

**Environment Variables (in .env):**
```bash
SOLVER_URL=http://127.0.0.1:8000/v1/chat/completions
SOLVER_MODEL_ID=qwen3-coder
TUNNEL_ENABLE=1  # Enable Cloudflare tunnel for remote access
```

---

## Design Principles

1. **Single model simplicity** - One powerful model handles all roles
2. **Document-based IO** - All state flows through context.md
3. **Web-first** - Accessible via browser, not just CLI
4. **Context discipline** - Pass original queries to decision-making LLMs
5. **Recipe-driven** - Budgets and schemas defined in YAML recipes
6. **Workflow-centric** - Declarative tool sequences, not ad-hoc decisions
7. **Abstract prompts** - V2 style with placeholders, not concrete examples

---

Last Updated: 2026-02-02
