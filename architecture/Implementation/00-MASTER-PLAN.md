# PandaAI v2 Implementation Plan

**Status:** IMPLEMENTATION ROADMAP
**Version:** 1.1
**Created:** 2026-01-05
**Updated:** 2026-01-06

---

## Executive Summary

This document provides the complete implementation roadmap for PandaAI v2, a modular LLM pipeline implementing a **simplified cognitive stack** optimized for RTX 3090 Server (24GB VRAM). The system processes queries through an **8-phase document pipeline** with a single model handling all text roles via temperature.

**Key Characteristics:**
- Document-centric IO via `context.md`
- Quality over speed philosophy
- Fail-fast development mode
- LLM-driven decisions (no hardcoded workarounds)

**Model Stack (Simplified - vLLM Tested 2026-01-06):**
- Hot Pool (~3.3GB): MIND (Qwen3-Coder-30B-AWQ) - handles ALL text roles via temperature
- Cold Pool (~5GB): EYES (Qwen3-VL-2B) - swaps with MIND for vision (~60-90s swap)
- CPU: Embeddings (all-MiniLM-L6-v2) - no VRAM impact
- NOT USED: Qwen3-0.6B (REFLEX) - MIND handles classification adequately

---

## Implementation Phases Overview

| Phase | Name | Dependencies | Priority |
|-------|------|--------------|----------|
| 1 | Infrastructure Setup | None | Critical |
| 2 | Core Libraries | Phase 1 | Critical |
| 3 | Document IO System | Phase 2 | Critical |
| 4 | vLLM Model Server | Phase 1 | Critical |
| 5 | Orchestrator Service | Phase 2, 3 | High |
| 6 | Gateway Service | Phase 3, 4, 5 | High |
| 7 | Pipeline Phases 0-2 | Phase 6 | High |
| 8 | Pipeline Phases 3-4 | Phase 7 | High |
| 9 | MCP Tools (Basic) | Phase 5 | High |
| 10 | Internet Research MCP | Phase 9 | Medium |
| 11 | Pipeline Phases 5-7 | Phase 8 | High |
| 12 | Vision Integration (EYES) | Phase 4 | Medium |
| 13 | Background Services (NERVES) | Phase 3 | Low |
| 14 | UI Layer | Phase 11 | Medium |
| 15 | Testing & Validation | All | High |

---

## Architecture Linkages

This section documents how the implementation plan traces back to the architecture documentation.

### 8-Phase Pipeline Structure

**Architecture Reference:** `architecture/README.md#8-Phase-Pipeline`, `architecture/LLM-ROLES/llm-roles-reference.md`

> From `architecture/README.md`:
> ```
> Phase 0: Query Analyzer   → MIND (REFLEX role, temp=0.3) classifies intent/type
> Phase 1: Reflection       → MIND (REFLEX role, temp=0.3) decides PROCEED | CLARIFY → §1
> Phase 2: Context Gatherer → MIND (temp=0.5) searches turns, memory, research → §2
> Phase 3: Planner          → MIND (temp=0.5) creates task plan → §3
> Phase 4: Coordinator      → MIND (temp=0.5) + EYES execute tools → §4
> Phase 5: Synthesis        → MIND (VOICE role, temp=0.7) generates response → §5
> Phase 6: Validation       → MIND (temp=0.5) checks quality → §6
> Phase 7: Save             → Procedural (no LLM) → disk
> ```

**Why 8 Phases:** The pipeline mirrors the cognitive process: understand → reflect → gather context → plan → execute → synthesize → validate → persist. Each phase has clear inputs/outputs documented in `architecture/main-system-patterns/phase*.md`.

---

### Simplified Model Stack

**Architecture Reference:** `architecture/LLM-ROLES/llm-roles-reference.md#Model-Stack`, `config/model-registry.yaml`

> From `architecture/LLM-ROLES/llm-roles-reference.md` (Final Build 2026-01-06):
> | Role | Model | Server | VRAM | Pool | Temp |
> |------|-------|--------|------|------|------|
> | MIND | Qwen3-Coder-30B-AWQ | vLLM (8000) | ~5.3GB | Hot | 0.5 |
> | EYES | Qwen3-VL-2B-Instruct | vLLM (8000) | ~5.0GB | Cold | 0.3 |
> | SERVER | Qwen3-Coder-30B | Remote | N/A | Remote | 0.3 |

**Why Single MIND Model:** Testing showed a single model handles all text roles via temperature. REFLEX=0.3 (classification), NERVES=0.1 (compression), MIND=0.5 (reasoning), VOICE=0.7 (dialogue). Qwen3-0.6B (REFLEX) was dropped after testing confirmed MIND handles classification adequately.

---

### Document-Centric IO

**Architecture Reference:** `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md#context.md-Schema`

> "context.md is the single source of truth for a turn. Each phase appends its output as a numbered section (§0-§6). The document accumulates during pipeline execution and is saved in Phase 7."

**Why context.md:** Markdown documents provide human readability for debugging, Obsidian integration for knowledge management, and clear provenance via dual-format links. Section numbers map directly to phases for traceability.

---

### Service Architecture

**Architecture Reference:** `architecture/services/orchestrator-service.md`, `architecture/README.md#Services`

> From `architecture/README.md`:
> | Service | Port | Purpose |
> |---------|------|---------|
> | Gateway | 9000 | Pipeline orchestration |
> | Orchestrator | 8090 | Tool execution |
> | vLLM | 8000 | LLM inference |

**Why Two Services:** Gateway handles the 8-phase pipeline logic. Orchestrator handles tool execution (file, git, memory, research). Separation allows independent scaling and clear responsibility boundaries.

---

### Quality Over Speed Philosophy

**Architecture Reference:** `architecture/README.md#Design-Philosophy`, `CLAUDE.md#Design-Philosophy`

> From `CLAUDE.md`:
> "Pandora prioritizes **correct, high-quality answers** over response time. Do NOT suggest: Time budgets that cut off research early, arbitrary timeouts that return partial garbage..."

**Why No Timeouts:** The system researches until it has enough quality data, not until a timer expires. Speed optimizations focus on efficiency (skip redundant work, cache better), not on cutting corners.

---

### Fail-Fast Development Mode

**Architecture Reference:** `architecture/main-system-patterns/ERROR_HANDLING.md`

> "Every error is a bug that needs to be fixed. Silent fallbacks and graceful degradation HIDE bugs... When something fails: Log full context, create intervention request, STOP processing."

**Why Fail-Fast:** Development mode halts on all errors to surface bugs early. No silent retries that mask problems. Every failure is a learning opportunity to improve the system.

---

## Phase 1: Infrastructure Setup

**Goal:** Set up foundational infrastructure (Docker services, project structure, configuration)

### 1.1 Project Structure

```
pandaaiv2/
├── apps/
│   ├── main-system-patterns/     # 8-phase pipeline implementation
│   │   └── phases/               # Phase executors
│   │       ├── base_phase.py
│   │       ├── phase0_query_analyzer.py
│   │       ├── phase1_reflection.py
│   │       ├── phase2_context_gatherer.py
│   │       ├── phase3_planner.py
│   │       ├── phase4_coordinator.py
│   │       ├── phase5_synthesis.py
│   │       ├── phase6_validation.py
│   │       └── phase7_save.py
│   │
│   ├── services/
│   │   ├── gateway/              # Port 9000 - Pipeline orchestration
│   │   │   ├── app.py            # FastAPI application
│   │   │   ├── pipeline/         # Phase orchestration
│   │   │   │   ├── runner.py
│   │   │   │   └── phase_executor.py
│   │   │   └── routes/
│   │   │       └── chat.py
│   │   │
│   │   └── orchestrator/         # Port 8090 - Tool execution
│   │       ├── app.py            # FastAPI application
│   │       ├── tools/            # MCP tool implementations
│   │       │   ├── base.py
│   │       │   ├── registry.py
│   │       │   ├── file_mcp.py
│   │       │   └── memory_mcp.py
│   │       └── routes/
│   │           └── tools.py
│   │
│   ├── recipes/                  # LLM prompts & recipes
│   │   └── prompts/phase{0-6}/
│   │
│   └── mcp-tools/                # MCP tool implementations
│       └── internet-research-mcp/
│
├── libs/                     # Shared libraries
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py         # Configuration management
│   │   ├── models.py         # Pydantic models
│   │   └── exceptions.py     # Custom exceptions
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py         # vLLM client wrapper
│   │   ├── router.py         # Model routing (all use MIND via temp)
│   │   ├── recipes.py        # Recipe loader
│   │   └── model_swap.py     # MIND ↔ EYES swap manager
│   │
│   └── document_io/
│       ├── __init__.py
│       ├── context_manager.py    # context.md operations
│       ├── research_manager.py   # research.md operations
│       ├── turn_manager.py       # Turn lifecycle
│       └── link_formatter.py     # Dual-link generation
│
├── panda-system-docs/        # Runtime data (turns, memories)
│   ├── users/{user_id}/turns/    # Turn documents (context.md, etc.)
│   ├── site_knowledge/           # Learned site schemas
│   └── transcripts/              # Session transcripts
│
├── config/
│   └── model-registry.yaml   # Model configuration (exists)
│
├── scripts/
│   ├── start.sh              # Start all services
│   ├── stop.sh               # Stop all services
│   ├── health_check.sh       # Check service health
│   └── download_models.sh    # Download model weights
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── docker-compose.yml        # Docker services (exists)
├── pyproject.toml            # Python project config
├── .env.example              # Environment template
└── requirements.txt          # Dependencies
```

### 1.2 Docker Services

**Already Defined in docker-compose.yml:**
- Qdrant (port 6333) - Vector database
- PostgreSQL (port 5432) - Relational database

**Tasks:**
1. Verify Docker Compose configuration
2. Create database initialization scripts
3. Create health check scripts
4. Document startup procedures

### 1.3 Environment Configuration

**Create `.env.example`:**
```bash
# vLLM Server
VLLM_HOST=localhost
VLLM_PORT=8000
VLLM_GPU_MEMORY_UTILIZATION=0.90

# Gateway
GATEWAY_HOST=0.0.0.0
GATEWAY_PORT=9000

# Orchestrator
ORCHESTRATOR_HOST=0.0.0.0
ORCHESTRATOR_PORT=8090

# Databases
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=pandora
POSTGRES_USER=pandora
POSTGRES_PASSWORD=pandora

QDRANT_HOST=localhost
QDRANT_PORT=6333

# Model Configuration (Simplified Stack)
MIND_MODEL=cyankiwi/Qwen3-Coder-30B-AWQ-4bit
EYES_MODEL=Qwen/Qwen3-VL-2B-Instruct

# Role Temperatures (all use MIND model)
REFLEX_TEMP=0.3
NERVES_TEMP=0.1
MIND_TEMP=0.5
VOICE_TEMP=0.7

# Development
DEV_MODE=true
TRACE_VERBOSE=1
```

### 1.4 Deliverables

| Item | File | Description |
|------|------|-------------|
| Project structure | `apps/`, `libs/`, `tests/` | Directory skeleton |
| Environment config | `.env.example` | Configuration template |
| pyproject.toml | `pyproject.toml` | Python project definition |
| requirements.txt | `requirements.txt` | Dependencies |
| DB init scripts | `scripts/init_db.sql` | PostgreSQL schema (CREATED) |

**Database Schema includes:**
- `users` - User accounts
- `turns` - Turn index with Qdrant cross-reference
- `memories` - User facts/preferences with semantic search
- `research_entries` - Research index with TTL
- `webpage_cache` - Cached page index
- `site_knowledge` - Learned domain patterns
- `products` - Extracted product data
- `interventions` - CAPTCHA/blocker tracking
- `metrics_daily` - Observability aggregates

---

## Phase 2: Core Libraries

**Goal:** Build shared libraries used across all services

### 2.1 Configuration Management (`libs/core/config.py`)

```python
# Key functionality:
# - Load .env file
# - Load model-registry.yaml
# - Provide typed access to configuration
# - Environment-aware (dev/prod)
```

### 2.2 LLM Client (`libs/llm/client.py`)

```python
# Key functionality:
# - Async HTTP client for vLLM
# - Request/response schemas
# - Token counting
# - Error handling with intervention requests
# - Streaming support (SSE)
```

### 2.3 Model Router (`libs/llm/router.py`)

```python
# Key functionality:
# - Route requests to MIND with appropriate temperature per role
# - Handle EYES cold loading (swaps with MIND, ~60-90s overhead)
# - Track VRAM usage
# - Model swap management (MIND ↔ EYES)
# - Apply role temperatures: REFLEX=0.3, NERVES=0.1, MIND=0.5, VOICE=0.7
```

### 2.4 Recipe System (`libs/llm/recipes.py`)

```python
# Key functionality:
# - Load YAML recipe files
# - Validate token budgets
# - Provide prompt templates
# - Phase-specific configurations
```

### 2.5 Pydantic Models (`libs/core/models.py`)

```python
# Key models:
# - QueryAnalysis (Phase 0 output)
# - ReflectionDecision (Phase 1 output)
# - GatheredContext (Phase 2 output)
# - TaskPlan (Phase 3 output)
# - ToolExecution (Phase 4 output)
# - SynthesisResult (Phase 5 output)
# - ValidationResult (Phase 6 output)
# - InterventionRequest (error handling)
```

### 2.6 Deliverables

| Item | File | Description |
|------|------|-------------|
| Config manager | `libs/core/config.py` | Configuration loading |
| LLM client | `libs/llm/client.py` | vLLM HTTP client |
| Model router | `libs/llm/router.py` | Model selection/loading |
| Recipe system | `libs/llm/recipes.py` | YAML recipe loader |
| Pydantic models | `libs/core/models.py` | Type definitions |
| Exceptions | `libs/core/exceptions.py` | Custom exceptions |

---

## Phase 3: Document IO System

**Goal:** Implement the document-centric IO model (context.md, research.md, linking)

### 3.1 Context Manager (`libs/document_io/context_manager.py`)

```python
# Key functionality:
# - Create new context.md for turn
# - Read/write sections (§0-§6)
# - Parse existing context.md
# - Section validation
# - Token budget enforcement
```

### 3.2 Turn Manager (`libs/document_io/turn_manager.py`)

```python
# Key functionality:
# - Generate turn numbers (per-user sequential)
# - Create turn directories
# - Manage turn lifecycle
# - Index turns in PostgreSQL
# - Embed turns in Qdrant
```

### 3.3 Research Manager (`libs/document_io/research_manager.py`)

```python
# Key functionality:
# - Create research.md documents
# - Parse research.md
# - Link from context.md
# - Separate evergreen vs time-sensitive data
# - Index in research_index
```

### 3.4 Link Formatter (`libs/document_io/link_formatter.py`)

```python
# Key functionality:
# - Generate dual-format links (Markdown + Wikilink)
# - Relative path calculation
# - Block ID generation
# - Source reference formatting
```

### 3.5 Webpage Cache Manager (`libs/document_io/webpage_cache.py`)

```python
# Key functionality:
# - Create webpage_cache directories
# - Store manifest.json, page_content.md, extracted_data.json
# - Check cache before navigation
# - Cache freshness evaluation
```

### 3.6 Deliverables

| Item | File | Description |
|------|------|-------------|
| Context manager | `libs/document_io/context_manager.py` | context.md operations |
| Turn manager | `libs/document_io/turn_manager.py` | Turn lifecycle |
| Research manager | `libs/document_io/research_manager.py` | research.md operations |
| Link formatter | `libs/document_io/link_formatter.py` | Dual links |
| Webpage cache | `libs/document_io/webpage_cache.py` | Cache management |

---

## Phase 4: vLLM Model Server

**Goal:** Set up vLLM to serve the simplified cognitive stack (single MIND model)

### 4.1 Model Download Script

```bash
# scripts/download_models.sh
# Download required models from HuggingFace:
# - cyankiwi/Qwen3-Coder-30B-AWQ-4bit (MIND - handles all text roles)
# - Qwen/Qwen3-VL-2B-Instruct (EYES - vision tasks)
# - sentence-transformers/all-MiniLM-L6-v2 (Embeddings - CPU)
#
# NOT NEEDED:
# - Qwen/Qwen3-0.6B (REFLEX) - MIND handles classification
```

### 4.2 vLLM Server Configuration (Tested)

```bash
# Tested vLLM startup command:
python -m vllm.entrypoints.openai.api_server \
  --host 0.0.0.0 \
  --port 8000 \
  --model models/Qwen3-Coder-30B-AWQ \
  --served-model-name mind \
  --gpu-memory-utilization 0.80 \
  --max-model-len 4096 \
  --enforce-eager \  # Required on WSL
  --trust-remote-code

# Hot pool (always loaded):
# - MIND: Qwen3-Coder-30B-AWQ (~3.3GB) - serves ALL text roles via temperature
# Total: ~3.3GB

# Cold pool (load on demand):
# - EYES: Qwen3-VL-2B (~5GB) - swaps with MIND (~60-90s swap overhead)

# Notes:
# - Quantization auto-detected as "compressed-tensors" (not AWQ)
# - --enforce-eager required on WSL
# - Single model handles REFLEX/NERVES/MIND/VOICE roles
```

### 4.3 Model Loading Strategy

**Option A: Multi-model vLLM (if supported)**
- Single vLLM instance serving multiple models
- Automatic memory management

**Option B: Model-specific endpoints (fallback)**
- Separate endpoints per model
- Manual model loading/unloading

### 4.4 Deliverables

| Item | File | Description |
|------|------|-------------|
| Download script | `scripts/download_models.sh` | Model download |
| vLLM config | `config/vllm_config.yaml` | Server configuration |
| Startup script | `scripts/start_vllm.sh` | Launch vLLM |
| Health check | `scripts/vllm_health.sh` | Model readiness |

---

## Phase 5: Orchestrator Service

**Goal:** Build the tool execution service (port 8090)

### 5.1 FastAPI Application (`apps/orchestrator/app.py`)

```python
# Key functionality:
# - FastAPI application
# - Tool endpoint routing
# - Mode gate middleware (chat vs code)
# - Health check endpoint
# - CORS configuration
```

### 5.2 Basic MCP Tools

| Tool | Endpoint | Implementation |
|------|----------|----------------|
| file.read | `/file/read` | Read file contents |
| file.glob | `/file/glob` | Find files by pattern |
| file.grep | `/file/grep` | Search file contents |
| git.status | `/git/status` | Repository status |
| git.diff | `/git/diff` | View changes |
| git.log | `/git/log` | Commit history |
| memory.create | `/memory/create` | Store user fact |
| memory.query | `/memory/query` | Search memories |

### 5.3 Shared Utilities

```python
# apps/orchestrator/shared/llm_utils.py
# - LLM client wrapper for tool-internal LLM calls
# - Token budget management

# apps/orchestrator/shared/browser_factory.py
# - Playwright browser instance management
# - Session persistence
# - Human behavior simulation
```

### 5.4 Deliverables

| Item | File | Description |
|------|------|-------------|
| Orchestrator app | `apps/orchestrator/app.py` | FastAPI server |
| File tools | `apps/orchestrator/tools/file_mcp.py` | File operations |
| Git tools | `apps/orchestrator/tools/git_mcp.py` | Git operations |
| Memory tools | `apps/orchestrator/tools/memory_mcp.py` | Memory operations |
| LLM utils | `apps/orchestrator/shared/llm_utils.py` | LLM helpers |

---

## Phase 6: Gateway Service

**Goal:** Build the pipeline orchestration service (port 9000)

### 6.1 FastAPI Application (`apps/gateway/app.py`)

```python
# Key functionality:
# - FastAPI application with WebSocket support
# - Chat endpoint (main entry)
# - Injection endpoint (mid-research messages)
# - Health check
# - CORS and authentication
```

### 6.2 Pipeline Orchestrator (`apps/gateway/pipeline/orchestrator.py`)

```python
# Key functionality:
# - Execute 8-phase pipeline
# - Phase transitions
# - RETRY/REVISE loop handling
# - Iteration counting
# - Error handling (fail-fast)
```

### 6.3 Phase Runner (`apps/gateway/pipeline/phase_runner.py`)

```python
# Key functionality:
# - Load phase recipe
# - Build phase prompt
# - Call appropriate model via router
# - Parse phase output
# - Update context.md
```

### 6.4 Deliverables

| Item | File | Description |
|------|------|-------------|
| Gateway app | `apps/gateway/app.py` | FastAPI server |
| Pipeline orchestrator | `apps/gateway/pipeline/orchestrator.py` | Phase management |
| Phase runner | `apps/gateway/pipeline/phase_runner.py` | Phase execution |
| Chat routes | `apps/gateway/routes/chat.py` | API endpoints |

---

## Phase 7: Pipeline Phases 0-2

**Goal:** Implement the first three phases (Query Analyzer, Reflection, Context Gatherer)

### 7.1 Phase 0: Query Analyzer

**Model:** MIND (with REFLEX role, temp=0.3)
**Recipe:** `query_analyzer.yaml`

```python
# Input: Raw user query, recent turn summaries
# Output: query_analysis.json with:
#   - resolved_query
#   - query_type
#   - content_reference (if any)
#   - was_resolved
```

### 7.2 Phase 1: Reflection

**Model:** MIND (with REFLEX role, temp=0.3)
**Recipe:** `reflection.yaml`

```python
# Input: §0 (user query)
# Output: §1 with:
#   - Decision: PROCEED | CLARIFY
#   - Confidence
#   - Reasoning
```

### 7.3 Phase 2: Context Gatherer

**Model:** MIND (Qwen3-Coder-30B-Instruct)
**Recipe:** `context_gatherer_retrieval.yaml`, `context_gatherer_synthesis.yaml`

```python
# Two-phase process:
# 1. RETRIEVAL: Identify relevant turns, research, memory
# 2. SYNTHESIS: Follow links, extract details, compile §2

# Input: §0, §1, turn_index, research_index, memory
# Output: §2 with gathered context
```

### 7.4 Deliverables

| Item | File | Description |
|------|------|-------------|
| Phase 0 | `apps/phases/phase0_query_analyzer.py` | Query analysis |
| Phase 1 | `apps/phases/phase1_reflection.py` | PROCEED/CLARIFY gate |
| Phase 2 | `apps/phases/phase2_context_gatherer.py` | Context gathering |
| Phase 0 recipe | `apps/recipes/query_analyzer.yaml` | Configuration |
| Phase 1 recipe | `apps/recipes/reflection.yaml` | Configuration |
| Phase 2 recipes | `apps/recipes/context_gatherer_*.yaml` | Configuration |
| Phase 0 prompts | `apps/prompts/phase0/*.txt` | Prompt templates |
| Phase 1 prompts | `apps/prompts/phase1/*.txt` | Prompt templates |
| Phase 2 prompts | `apps/prompts/phase2/*.txt` | Prompt templates |

---

## Phase 8: Pipeline Phases 3-4

**Goal:** Implement Planner and Coordinator with the Planner-Coordinator loop

### 8.1 Phase 3: Planner

**Model:** MIND (Qwen3-Coder-30B-Instruct)
**Recipe:** `planner_chat.yaml`, `planner_code.yaml`

```python
# Input: §0-§2
# Output: §3 + ticket.md with:
#   - Decision: EXECUTE | COMPLETE
#   - Goals (if multi-goal)
#   - Tool requests
#   - Routing decision
```

### 8.2 Phase 4: Coordinator

**Model:** MIND (Qwen3-Coder-30B-Instruct)
**Recipe:** `coordinator_chat.yaml`, `coordinator_code.yaml`

```python
# Input: §0-§3, ticket.md
# Output: §4 (accumulates), toolresults.md

# Key: Thin execution layer - reads ticket.md, calls tools, returns
# Loop management is in Gateway orchestrator, not Coordinator
```

### 8.3 Planner-Coordinator Loop

```python
# Managed by Gateway orchestrator:
# 1. Run Planner
# 2. If EXECUTE: Run Coordinator, append §4, loop back to Planner
# 3. If COMPLETE: Exit loop, proceed to Phase 5
# 4. Max 5 iterations
```

### 8.4 Deliverables

| Item | File | Description |
|------|------|-------------|
| Phase 3 | `apps/phases/phase3_planner.py` | Planning |
| Phase 4 | `apps/phases/phase4_coordinator.py` | Tool execution |
| Loop logic | `apps/gateway/pipeline/planner_loop.py` | Loop management |
| Phase 3 recipes | `apps/recipes/planner_*.yaml` | Configuration |
| Phase 4 recipes | `apps/recipes/coordinator_*.yaml` | Configuration |

---

## Phase 9: MCP Tools (Basic)

**Goal:** Implement essential tools for Coordinator

**Note:** "MCP" is used loosely here. Tools are custom REST endpoints on the Orchestrator service (port 8090), not the official Model Context Protocol. This keeps the implementation simple and avoids external dependencies.

### 9.1 File Operations (`apps/orchestrator/tools/file_mcp.py`)

- `file.read` - Read file contents
- `file.write` - Write file (code mode only)
- `file.edit` - Edit file with diff (code mode only)
- `file.glob` - Find files by pattern
- `file.grep` - Search file contents

### 9.2 Git Operations (`apps/orchestrator/tools/git_mcp.py`)

- `git.status` - Repository status
- `git.diff` - View changes
- `git.log` - Commit history
- `git.add` - Stage changes (code mode only)
- `git.commit` - Create commit (code mode only)

### 9.3 Memory Operations (`apps/orchestrator/tools/memory_mcp.py`)

- `memory.create` - Store user fact/preference
- `memory.query` - Search user memories
- `memory.delete` - Remove memory
- Uses PostgreSQL for structured storage
- Uses Qdrant for semantic search

### 9.4 Deliverables

| Item | File | Description |
|------|------|-------------|
| File tools | `apps/orchestrator/tools/file_mcp.py` | File operations |
| Git tools | `apps/orchestrator/tools/git_mcp.py` | Git operations |
| Memory tools | `apps/orchestrator/tools/memory_mcp.py` | Memory operations |

---

## Phase 10: Internet Research MCP

**Goal:** Implement comprehensive web research tool

### 10.1 Research Orchestration (`apps/orchestrator/tools/internet_research_mcp.py`)

```python
# Entry point for internet.research tool
# Orchestrates Phase 1 (Intelligence) and Phase 2 (Extraction)
```

### 10.2 Strategy Selection

```python
# Select strategy based on query:
# - phase1_only (informational)
# - phase2_only (commerce + cached data within TTL)
# - phase1_and_phase2 (commerce, cache expired or missing)
#
# Cache TTL: Configurable per data type (default: 24h for product data)
```

### 10.3 Phase 1: Intelligence Gathering

- Generate search queries (MIND)
- Execute Google/DuckDuckGo search
- Classify results (REFLEX)
- Score source quality (MIND)
- Deep browse relevant pages

### 10.4 Phase 2: Product Extraction

- Select retailers (MIND)
- Build search URLs (MIND)
- Capture pages (PageDocument)
- Extract products (MIND)
- Filter viable products (MIND)
- Verify on PDP (mandatory)

### 10.5 Page Intelligence System

```python
# PageCapturer - Screenshot + OCR + DOM
# DocumentStructurer - EYES creates PageDocument
# OCRDOMMapper - Cross-reference
# SiteKnowledgeCache - Learned patterns
```

### 10.6 Deliverables

| Item | File | Description |
|------|------|-------------|
| Research MCP | `apps/orchestrator/tools/internet_research_mcp.py` | Main handler |
| Research role | `apps/orchestrator/research/research_role.py` | Orchestration |
| Strategy selector | `apps/orchestrator/research/strategy_selector.py` | Strategy selection |
| Page capturer | `apps/orchestrator/page_intelligence/capturer.py` | Page capture |
| Document structurer | `apps/orchestrator/page_intelligence/structurer.py` | EYES structuring |
| Site knowledge | `apps/orchestrator/site_knowledge_cache.py` | Pattern learning |
| Search engine | `apps/orchestrator/search/human_search.py` | Stealth search |
| Stealth behavior | `apps/orchestrator/search/stealth.py` | Human simulation |

---

## Phase 11: Pipeline Phases 5-7

**Goal:** Complete the pipeline with Synthesis, Validation, and Save

### 11.1 Phase 5: Synthesis

**Model:** MIND (with VOICE role, temp=0.7)
**Recipe:** `synthesizer_chat.yaml`, `synthesizer_code.yaml`

```python
# Input: §0-§4, toolresults.md
# Output: §5 (preview), response.md (full response)
# Key: User-facing response with citations
```

### 11.2 Phase 6: Validation

**Model:** MIND (Qwen3-Coder-30B-Instruct)
**Recipe:** `validator.yaml`

```python
# Input: §0-§5, response.md
# Output: §6 with:
#   - Decision: APPROVE | REVISE | RETRY | FAIL
#   - Per-goal validation (if multi-goal)
#   - Issues found
#   - Revision hints (if REVISE)
```

### 11.3 Phase 7: Save

**Model:** None (procedural)

```python
# Tasks:
# - Save context.md to disk
# - Generate turn metadata
# - Index in PostgreSQL
# - Embed in Qdrant
# - Update research_index (if research occurred)
# - Archive if needed
```

### 11.4 Deliverables

| Item | File | Description |
|------|------|-------------|
| Phase 5 | `apps/phases/phase5_synthesis.py` | Response generation |
| Phase 6 | `apps/phases/phase6_validation.py` | Quality validation |
| Phase 7 | `apps/phases/phase7_save.py` | Persistence |
| Phase 5 recipes | `apps/recipes/synthesizer_*.yaml` | Configuration |
| Phase 6 recipe | `apps/recipes/validator.yaml` | Configuration |

---

## Phase 12: Vision Integration (EYES)

**Goal:** Implement EYES model loading and vision tasks

### 12.1 Model Swap Manager

```python
# Handle MIND ↔ EYES swap:
# 1. Detect vision task needed
# 2. Unload MIND (~3.3GB freed)
# 3. Load EYES: Qwen3-VL-2B (~5GB)
# 4. Execute vision task
# 5. Unload EYES, reload MIND
# Note: All text processing pauses during vision tasks
# Total swap overhead: ~60-90 seconds per swap cycle
```

### 12.2 Vision Tasks

**Model:** EYES (Qwen3-VL-2B-Instruct)

- PageDocument structuring
- Screenshot analysis
- CAPTCHA detection
- Visual verification (when MIND confidence < 0.7)
- OCR verification for complex layouts

### 12.3 CAPTCHA Intervention

```python
# Flow:
# 1. EYES detects CAPTCHA
# 2. Create InterventionRequest
# 3. Queue for human (noVNC)
# 4. Wait for resolution (max 90s)
# 5. Resume research
```

### 12.4 Deliverables

| Item | File | Description |
|------|------|-------------|
| Model swap manager | `libs/llm/model_swap.py` | MIND/EYES swap |
| Screenshot analyzer | `apps/orchestrator/vision/analyzer.py` | Vision extraction |
| CAPTCHA intervention | `apps/orchestrator/vision/captcha.py` | CAPTCHA handling |

---

## Phase 13: Background Services (NERVES)

**Goal:** Implement background document compression services

**Model:** MIND (with NERVES role, temp=0.1)

### 13.1 Smart Summarization

```python
# Triggered when §4 exceeds token budget
# Uses MIND model with NERVES role (temp=0.1) for compression
# Preserves key facts (verified with REFLEX role)
```

### 13.2 Compression Verification

```python
# 1. MIND (REFLEX role, temp=0.3) extracts key facts from original
# 2. MIND (NERVES role, temp=0.1) compresses content
# 3. MIND (REFLEX role, temp=0.3) verifies facts preserved (>= 80%)
# 4. Accept or retry with higher budget
```

### 13.3 Memory Compression

```python
# Compress memory sections when exceeding budget
# Same verification pattern as context compression
```

### 13.4 Deliverables

| Item | File | Description |
|------|------|-------------|
| Smart summarizer | `libs/compression/summarizer.py` | Compression logic |
| Compression verifier | `libs/compression/verifier.py` | Fact verification |

---

## Phase 14: UI Layer

**Goal:** Build user interface for interaction

**Decision:** CLI first, then VSCode extension (per `architecture/services/user-interface.md`)

### 14.1 Phase 14a: CLI Tool (First)

**Technology:** Python (Typer + Rich)

```
apps/cli/
├── main.py              # Typer CLI entry point
├── commands/
│   ├── chat.py          # Main query command
│   ├── turns.py         # Turn management
│   ├── status.py        # System status
│   └── memory.py        # Memory operations
├── display/
│   ├── progress.py      # Rich progress display
│   ├── response.py      # Response formatting
│   └── tables.py        # Product tables
└── api/
    └── client.py        # Gateway HTTP/WebSocket client
```

### 14.2 Phase 14b: VSCode Extension (Second)

**Technology:** TypeScript + Webview

- Chat panel with streaming responses
- Sidebar status panel
- Research progress visualization
- Intervention alerts
- Product cards for commerce results

### 14.3 Key Features

- Chat input/output
- Streaming responses (WebSocket)
- Research progress visualization
- CAPTCHA intervention UI (local browser, not noVNC)
- Turn history browser

### 14.4 Deliverables

| Item | File | Description |
|------|------|-------------|
| CLI tool | `apps/cli/` | Terminal interface |
| VSCode extension | `panda-vscode/` | IDE integration |
| Gateway client | `apps/cli/api/client.py` | HTTP/WebSocket client |

---

## Phase 15: Testing & Validation

**Goal:** Ensure system correctness and reliability

### 15.1 Unit Tests

```python
# Test individual components:
# - LLM client
# - Document IO
# - Each phase
# - Each tool
```

### 15.2 Integration Tests

```python
# Test component interactions:
# - Gateway → Orchestrator
# - Phase transitions
# - Planner-Coordinator loop
# - Research pipeline
```

### 15.3 End-to-End Tests

```python
# Test complete flows:
# - Simple query (no tools)
# - Commerce query (full research)
# - Multi-goal query
# - RETRY/REVISE scenarios
```

### 15.4 Deliverables

| Item | File | Description |
|------|------|-------------|
| Unit tests | `tests/unit/` | Component tests |
| Integration tests | `tests/integration/` | Integration tests |
| E2E tests | `tests/e2e/` | Full flow tests |
| Test fixtures | `tests/fixtures/` | Test data |

---

## Implementation Order Summary

```
Week 1-2: Foundation
├── Phase 1: Infrastructure Setup
├── Phase 2: Core Libraries
└── Phase 3: Document IO System

Week 3-4: Services
├── Phase 4: vLLM Model Server
├── Phase 5: Orchestrator Service
└── Phase 6: Gateway Service

Week 5-6: Pipeline
├── Phase 7: Phases 0-2
├── Phase 8: Phases 3-4
└── Phase 9: Basic MCP Tools

Week 7-8: Research & Completion
├── Phase 10: Internet Research MCP
├── Phase 11: Phases 5-7
└── Phase 12: Vision Integration

Week 9-10: Polish
├── Phase 13: Background Services
├── Phase 14: UI Layer
└── Phase 15: Testing
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Model availability | Verify HuggingFace IDs early, have fallbacks |
| VRAM constraints | Test hot pool fit, optimize quantization if needed |
| vLLM multi-model | Have fallback to separate endpoints |
| Browser detection | Robust stealth implementation, human intervention |
| API rate limits | Rate limiting, search engine rotation |

---

## Success Criteria

| Criterion | Measurement |
|-----------|-------------|
| Pipeline completes | Query → Response in < 60s for simple queries |
| Research quality | Relevant products found for commerce queries |
| Validation accuracy | < 5% hallucination rate |
| System stability | No crashes in 100 consecutive queries |
| VRAM usage | Stays within 8GB limit |

---

## Next Steps

1. Review and approve this implementation plan
2. Create detailed implementation guides for each phase
3. Set up project skeleton (Phase 1)
4. Begin implementation in order

---

**Last Updated:** 2026-01-06 (Added Architecture Linkages section)
