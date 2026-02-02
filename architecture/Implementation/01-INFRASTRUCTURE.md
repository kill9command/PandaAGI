# Phase 1: Infrastructure Setup

**Dependencies:** None
**Priority:** Critical
**Estimated Effort:** 1-2 days

---

## Architecture Linkages

This section documents how each implementation decision traces back to the architecture documentation.

### Conda/Python Environment

**Architecture Reference:** `architecture/README.md#Overview`, `config/model-registry.yaml#hardware`

> From `config/model-registry.yaml` (updated 2026-01-06):
> ```yaml
> hardware:
>   gpu: "RTX 3090 Server"
>   vram_total_gb: 8
>   vram_hot_pool_gb: 3.3  # Single MIND model
>   vram_cold_reserve_gb: 5.0  # EYES when swapped in
> ```

**Why Python 3.11 + CUDA 12.1:** The architecture targets RTX 3090 Server (24GB VRAM). Python 3.11 provides async/performance improvements needed for the multi-phase pipeline. CUDA 12.1 provides optimal driver compatibility for Ampere architecture GPUs. vLLM is the chosen inference engine for OpenAI-compatible API and efficient GPU memory management.

---

### Directory Structure

**Architecture Reference:** `architecture/services/orchestrator-service.md#Architecture`, `architecture/README.md#Directory-Structure`

> From `architecture/services/orchestrator-service.md`:
> ```
> apps/orchestrator/app.py          # FastAPI application
>     ├── orchestrator/*.py         # Tool implementations (*_mcp.py)
>     └── orchestrator/shared/      # Shared utilities
> ```

**Why This Structure:** Clean separation between Gateway (pipeline orchestration, port 9000), Orchestrator (tool execution, port 8090), and shared libraries. Phase-specific prompts in `apps/prompts/phase{0-6}/` align with the 8-phase pipeline. Recipe YAML files support the mode-aware recipe loading system.

---

### Docker Services (PostgreSQL, Qdrant)

**Architecture Reference:** `architecture/services/DOCKER-INTEGRATION/DOCKER_ARCHITECTURE.md`

> "Docker Compose orchestrates stateful services (databases) while the core application (Gateway, Orchestrator, vLLM) runs directly on the host for GPU access and development flexibility."
>
> **Philosophy:** Docker for infrastructure, host for application.

**Why Docker for DBs Only:** vLLM requires direct GPU access for inference. Docker GPU passthrough adds complexity and latency. Running vLLM on host provides direct CUDA access, simpler debugging, and better performance. Databases (Qdrant, PostgreSQL) are stateful services that benefit from containerization.

**PostgreSQL Tables:**
- `pandora.turns` - Turn metadata index (architecture: turn history retrieval)
- `pandora.research` - Research cache index (architecture: research reuse)
- `pandora.sources` - Source reliability tracking (architecture: source trust scores)
- `pandora.user_memory` - User preferences and facts (architecture: memory system)

**Qdrant Collections:**
- `turns` (384 dim) - Semantic search for similar past turns
- `research` (384 dim) - Related research document retrieval
- `memories` (384 dim) - User memory semantic search

---

### Environment Configuration

**Architecture Reference:** `architecture/README.md#Services`, `config/model-registry.yaml#vllm`

> From `architecture/README.md`:
> | Service | Port | Purpose |
> |---------|------|---------|
> | Gateway | 9000 | Pipeline orchestration and routing |
> | vLLM | 8000 | LLM inference |
> | Orchestrator | 8090 | Tool execution |

**Why These Ports:** Canonical service ports from architecture. vLLM settings (`gpu_memory_utilization: 0.80`, `max_model_len: 4096`) from model-registry.yaml (vLLM tested 2026-01-06). Research settings (`MIN_SUCCESSFUL_VENDORS=3`) from orchestrator-service.md.

---

### Model Downloads

**Architecture Reference:** `architecture/LLM-ROLES/llm-roles-reference.md#Model-Stack`, `config/model-registry.yaml#models`

> **Simplified Stack (vLLM tested 2026-01-06):**
> | Role | Model | VRAM | Pool | Notes |
> |------|-------|------|------|-------|
> | MIND | Qwen3-Coder-30B-AWQ | ~3.3 GB | Hot | All text roles via temperature |
> | EYES | Qwen3-VL-2B (BF16) | ~5.0 GB | Cold | Vision tasks only |
> | SERVER | Qwen3-Coder-30B | Remote | Remote | Heavy coding |
> | Embedding | all-MiniLM-L6-v2 | 0 | CPU | Semantic search |
>
> **NOT USED:** Qwen3-0.6B (REFLEX) - MIND handles classification adequately.

**Why This Stack:** Single MIND model handles ALL text roles (REFLEX, NERVES, MIND, VOICE) via temperature settings. Hot pool (~3.3GB) = MIND only. EYES is cold pool and swaps with MIND when vision tasks are needed. Embeddings run on CPU with no VRAM impact.

---

### vLLM Configuration (Tested)

**Architecture Reference:** `architecture/LLM-ROLES/llm-roles-reference.md#EYES-Model-Swap-Strategy`

> **Swap Strategy: MIND <-> EYES**
> | Step | Action | VRAM State |
> |------|--------|------------|
> | 1 | Vision task detected | MIND loaded (~3.3GB) |
> | 2 | Unload MIND (3.3GB) | Empty (~0GB) |
> | 3 | Load EYES (5.0GB) | EYES only (~5GB) |
> | 4 | Execute vision | EYES active |
> | 5 | Unload EYES | Empty (~0GB) |
> | 6 | Load MIND | MIND restored (~3.3GB) |
>
> **Why MIND Swaps:** Single MIND model handles ALL text roles. No separate REFLEX model to swap. Total swap overhead: ~8-14 seconds per vision task.

**vLLM Startup Command (Tested):**
```bash
python -m vllm.entrypoints.openai.api_server \
  --host 0.0.0.0 \
  --port 8000 \
  --model models/Qwen3-Coder-30B-AWQ \
  --served-model-name mind \
  --gpu-memory-utilization 0.80 \
  --max-model-len 4096 \
  --enforce-eager \  # Required on WSL
  --trust-remote-code
```

**Notes:**
- Quantization is auto-detected as `compressed-tensors` (not AWQ format)
- `--enforce-eager` required on WSL
- Single model serves all text roles via temperature
- EYES started on-demand by `model_swap.py`
- SERVER accessed via remote API

---

## Overview

This phase establishes the foundational infrastructure for PandaAI v2:
- Conda environment setup
- Project directory structure
- Python project configuration
- Docker services verification
- Database initialization
- Environment configuration
- Model downloads
- Startup/shutdown scripts

---

## 1. Conda Environment Setup

### 1.1 Create Conda Environment

```bash
# Create new conda environment with Python 3.11
conda create -n pandaai python=3.11 -y

# Activate the environment
conda activate pandaai

# Verify Python version
python --version  # Should show Python 3.11.x
```

### 1.2 Install CUDA Dependencies (for vLLM)

```bash
# Install CUDA toolkit via conda (matches your NVIDIA driver)
conda install -c conda-forge cudatoolkit=12.1 -y

# Verify CUDA is accessible
python -c "import torch; print(torch.cuda.is_available())"  # Should print True
```

### 1.3 Install Core Dependencies

```bash
# Upgrade pip
pip install --upgrade pip

# Install PyTorch with CUDA support
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Install vLLM (requires CUDA)
pip install vllm

# Install project dependencies (after creating requirements.txt)
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 1.4 Verify Installation

```bash
# Check vLLM installation
python -c "import vllm; print(vllm.__version__)"

# Check VRAM availability
python -c "import torch; print(f'VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB')"

# Should show ~8GB for RTX 3090 Server
```

---

## 2. Directory Structure

Create the following directory skeleton:

```bash
# From project root
mkdir -p apps/gateway/pipeline
mkdir -p apps/gateway/routes
mkdir -p apps/orchestrator/tools
mkdir -p apps/orchestrator/shared
mkdir -p apps/orchestrator/research
mkdir -p apps/orchestrator/page_intelligence
mkdir -p apps/orchestrator/search
mkdir -p apps/orchestrator/vision
mkdir -p apps/phases
mkdir -p apps/prompts/phase{0,1,2,3,4,5,6}
mkdir -p apps/recipes
mkdir -p libs/core
mkdir -p libs/llm
mkdir -p libs/document_io
mkdir -p libs/compression
mkdir -p tests/unit
mkdir -p tests/integration
mkdir -p tests/e2e
mkdir -p tests/fixtures
```

Create `__init__.py` files:

```bash
touch apps/__init__.py
touch apps/gateway/__init__.py
touch apps/gateway/pipeline/__init__.py
touch apps/gateway/routes/__init__.py
touch apps/orchestrator/__init__.py
touch apps/orchestrator/tools/__init__.py
touch apps/orchestrator/shared/__init__.py
touch apps/phases/__init__.py
touch libs/__init__.py
touch libs/core/__init__.py
touch libs/llm/__init__.py
touch libs/document_io/__init__.py
```

---

## 3. Python Project Configuration

### 3.1 pyproject.toml

```toml
[project]
name = "pandaaiv2"
version = "0.1.0"
description = "PandaAI v2 - 5-Model Cognitive Stack LLM Pipeline"
readme = "README.md"
requires-python = ">=3.11"
license = {text = "MIT"}
authors = [
    {name = "Your Name", email = "your@email.com"}
]

dependencies = [
    # Web Framework
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "websockets>=12.0",
    "httpx>=0.26.0",
    "sse-starlette>=1.8.0",

    # Database
    "asyncpg>=0.29.0",
    "sqlalchemy>=2.0.25",
    "qdrant-client>=1.7.0",

    # LLM
    "openai>=1.10.0",  # vLLM uses OpenAI-compatible API
    "tiktoken>=0.5.2",

    # Browser Automation
    "playwright>=1.41.0",

    # OCR
    "easyocr>=1.7.1",

    # Utilities
    "pydantic>=2.5.3",
    "pydantic-settings>=2.1.0",
    "pyyaml>=6.0.1",
    "python-dotenv>=1.0.0",
    "rich>=13.7.0",
    "tenacity>=8.2.3",

    # Testing
    "pytest>=7.4.4",
    "pytest-asyncio>=0.23.3",
    "pytest-cov>=4.1.0",
]

[project.optional-dependencies]
dev = [
    "ruff>=0.1.13",
    "mypy>=1.8.0",
    "pre-commit>=3.6.0",
]

[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["apps*", "libs*"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]
ignore = ["E501"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_ignores = true
```

### 3.2 requirements.txt (alternative)

```txt
# Web Framework
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
websockets>=12.0
httpx>=0.26.0
sse-starlette>=1.8.0

# Database
asyncpg>=0.29.0
sqlalchemy>=2.0.25
qdrant-client>=1.7.0

# LLM
openai>=1.10.0
tiktoken>=0.5.2

# Browser Automation
playwright>=1.41.0

# OCR
easyocr>=1.7.1
pillow>=10.2.0

# Utilities
pydantic>=2.5.3
pydantic-settings>=2.1.0
pyyaml>=6.0.1
python-dotenv>=1.0.0
rich>=13.7.0
tenacity>=8.2.3

# Testing
pytest>=7.4.4
pytest-asyncio>=0.23.3
pytest-cov>=4.1.0
```

---

## 4. Environment Configuration

### 4.1 Create `.env.example`

```bash
# =============================================================================
# PandaAI v2 Environment Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# vLLM Model Server (vLLM tested 2026-01-06)
# -----------------------------------------------------------------------------
VLLM_HOST=localhost
VLLM_PORT=8000
VLLM_GPU_MEMORY_UTILIZATION=0.80  # Tested stable
VLLM_MAX_MODEL_LEN=4096  # Tested (can increase to 8192)
VLLM_ENFORCE_EAGER=true  # Required on WSL

# -----------------------------------------------------------------------------
# Gateway Service (Pipeline Orchestration)
# -----------------------------------------------------------------------------
GATEWAY_HOST=0.0.0.0
GATEWAY_PORT=9000
GATEWAY_WORKERS=1

# -----------------------------------------------------------------------------
# Orchestrator Service (Tool Execution)
# -----------------------------------------------------------------------------
ORCHESTRATOR_HOST=0.0.0.0
ORCHESTRATOR_PORT=8090
ORCHESTRATOR_WORKERS=1

# -----------------------------------------------------------------------------
# PostgreSQL Database
# -----------------------------------------------------------------------------
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=pandora
POSTGRES_USER=pandora
POSTGRES_PASSWORD=pandora

# Connection URL (constructed in code from above values)
# DATABASE_URL is built programmatically - do not set here

# -----------------------------------------------------------------------------
# Qdrant Vector Database
# -----------------------------------------------------------------------------
QDRANT_HOST=localhost
QDRANT_PORT=6333

# -----------------------------------------------------------------------------
# Model Configuration (Simplified - vLLM tested 2026-01-06)
# -----------------------------------------------------------------------------
# Hot Pool Model (single model handles all text roles)
MIND_MODEL=cyankiwi/Qwen3-Coder-30B-AWQ-4bit
# REFLEX, NERVES, VOICE roles use MIND with different temperatures
# REFLEX_MODEL not used - MIND handles classification adequately

# Cold Pool Models (load on demand, swaps with MIND)
EYES_MODEL=Qwen/Qwen3-VL-2B-Instruct

# Remote Models (accessed via API)
SERVER_ENDPOINT=http://localhost:8001
SERVER_MODEL=Qwen/Qwen3-Coder-30B

# Model Load Timeouts
EYES_LOAD_TIMEOUT_SECONDS=30
EYES_UNLOAD_AFTER_SECONDS=60

# -----------------------------------------------------------------------------
# Browser Configuration (Research)
# -----------------------------------------------------------------------------
BROWSER_HEADLESS=true
PLAYWRIGHT_TIMEOUT_MS=30000
VIEWPORT_WIDTH=1920
VIEWPORT_HEIGHT=1080

# -----------------------------------------------------------------------------
# Research Configuration
# -----------------------------------------------------------------------------
MIN_SUCCESSFUL_VENDORS=3
RESEARCH_MAX_PASSES=3
RESEARCH_SATISFACTION_THRESHOLD=0.8
MIN_REQUEST_INTERVAL_MS=2000

# -----------------------------------------------------------------------------
# Development Settings
# -----------------------------------------------------------------------------
DEV_MODE=true
TRACE_VERBOSE=1
LOG_LEVEL=INFO

# Fail-fast mode (exit on errors instead of fallbacks)
FAIL_FAST=true
```

### 4.2 Create `.env` from template

```bash
cp .env.example .env
# Edit .env with your specific values
```

---

## 5. Docker Services Verification

### 5.1 Verify docker-compose.yml

The existing `docker-compose.yml` defines:
- `vectordb` (Qdrant) on port 6333
- `postgres` (PostgreSQL) on port 5432

Both have:
- Health checks configured
- Data persistence via volumes

### 5.2 Database Initialization Script

Create `scripts/init_db.sql`:

```sql
-- =============================================================================
-- PandaAI v2 PostgreSQL Schema
-- =============================================================================

BEGIN;

-- Create schema
CREATE SCHEMA IF NOT EXISTS pandora;
SET search_path TO pandora, public;

-- -----------------------------------------------------------------------------
-- Turn Index
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS turns (
    turn_number SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    topic TEXT,
    intent TEXT,
    keywords JSONB DEFAULT '[]'::jsonb,
    quality FLOAT,
    turn_dir TEXT NOT NULL,
    embedding_id UUID,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_turns_session
    ON turns(session_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_turns_topic
    ON turns USING gin(to_tsvector('english', topic));
CREATE INDEX IF NOT EXISTS idx_turns_keywords
    ON turns USING gin(keywords);

-- -----------------------------------------------------------------------------
-- Research Index
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research (
    id SERIAL PRIMARY KEY,
    turn_number INTEGER REFERENCES turns(turn_number),
    primary_topic TEXT NOT NULL,
    quality_overall FLOAT,
    confidence_current FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    scope TEXT DEFAULT 'user',
    content_types JSONB DEFAULT '[]'::jsonb,
    doc_path TEXT NOT NULL,

    -- Metadata
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_topic
    ON research(primary_topic);
CREATE INDEX IF NOT EXISTS idx_research_quality
    ON research(quality_overall DESC);
CREATE INDEX IF NOT EXISTS idx_research_expiry
    ON research(expires_at);

-- -----------------------------------------------------------------------------
-- Source Reliability
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    domain TEXT PRIMARY KEY,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    last_success TIMESTAMPTZ,
    last_failure TIMESTAMPTZ,
    reliability_score FLOAT DEFAULT 0.5,
    notes JSONB DEFAULT '{}'::jsonb,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- User Memory
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_memory (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    memory_type TEXT NOT NULL,  -- 'preference', 'fact', 'context'
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    source_turn INTEGER,
    confidence FLOAT DEFAULT 1.0,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(session_id, memory_type, key)
);

CREATE INDEX IF NOT EXISTS idx_memory_session
    ON user_memory(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_type
    ON user_memory(memory_type);

-- -----------------------------------------------------------------------------
-- Observability Metrics
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metrics (
    id SERIAL PRIMARY KEY,
    turn_number INTEGER REFERENCES turns(turn_number),
    phase INTEGER NOT NULL,
    model TEXT NOT NULL,
    tokens_prompt INTEGER,
    tokens_completion INTEGER,
    tokens_total INTEGER,
    latency_ms INTEGER,
    success BOOLEAN DEFAULT true,
    error_type TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_metrics_turn
    ON metrics(turn_number);
CREATE INDEX IF NOT EXISTS idx_metrics_phase
    ON metrics(phase);
CREATE INDEX IF NOT EXISTS idx_metrics_model
    ON metrics(model);

-- -----------------------------------------------------------------------------
-- Functions
-- -----------------------------------------------------------------------------

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to tables with updated_at
CREATE TRIGGER update_turns_updated_at
    BEFORE UPDATE ON turns
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_research_updated_at
    BEFORE UPDATE ON research
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_sources_updated_at
    BEFORE UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_memory_updated_at
    BEFORE UPDATE ON user_memory
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- -----------------------------------------------------------------------------
-- Initial Data
-- -----------------------------------------------------------------------------

-- No initial data required

COMMIT;
```

### 5.3 Apply Schema Script

Create `scripts/init_postgres.sh`:

```bash
#!/bin/bash
set -e

echo "Waiting for PostgreSQL to be ready..."
until docker compose exec -T postgres pg_isready -U pandora -d pandora; do
    sleep 1
done

echo "Applying database schema..."
docker compose exec -T postgres psql -U pandora -d pandora < scripts/init_db.sql

echo "Database initialized successfully!"
```

---

## 6. Model Downloads

### 6.1 Download Script (Updated for Simplified Stack)

Create `scripts/download_models.sh`:

```bash
#!/bin/bash
# =============================================================================
# PandaAI v2 Model Download Script (Simplified Stack - vLLM tested 2026-01-06)
# =============================================================================

set -e

# Load environment variables
source .env 2>/dev/null || true

echo "=== Downloading PandaAI v2 Models (Simplified Stack) ==="
echo ""

# Create models directory
MODELS_DIR="${MODELS_DIR:-./models}"
mkdir -p "$MODELS_DIR"

# -----------------------------------------------------------------------------
# HOT POOL MODEL (Single model handles all text roles)
# -----------------------------------------------------------------------------

echo "[1/3] Downloading MIND model (compressed-tensors quantized)..."
echo "      Model: cyankiwi/Qwen3-Coder-30B-AWQ-4bit"
echo "      Note: Handles ALL text roles (REFLEX, NERVES, MIND, VOICE) via temperature"
huggingface-cli download cyankiwi/Qwen3-Coder-30B-AWQ-4bit --local-dir "${MODELS_DIR}/Qwen3-Coder-30B-AWQ"

# NOTE: Qwen3-0.6B (REFLEX) is NOT used - MIND handles classification adequately

# -----------------------------------------------------------------------------
# COLD POOL MODELS (Loaded on demand, swaps with MIND)
# -----------------------------------------------------------------------------

echo "[2/3] Downloading EYES model..."
echo "      Model: Qwen/Qwen3-VL-2B-Instruct"
echo "      Note: BF16 for quality, swaps with MIND for vision tasks"
huggingface-cli download Qwen/Qwen3-VL-2B-Instruct --local-dir "${MODELS_DIR}/Qwen3-VL-2B-Instruct"

# -----------------------------------------------------------------------------
# EMBEDDING MODEL (CPU)
# -----------------------------------------------------------------------------

echo "[3/3] Downloading embedding model..."
echo "      Model: sentence-transformers/all-MiniLM-L6-v2"
echo "      Note: Runs on CPU, no VRAM impact"
huggingface-cli download sentence-transformers/all-MiniLM-L6-v2 --local-dir "${MODELS_DIR}/all-MiniLM-L6-v2"

echo ""
echo "=== Download Complete ==="
echo ""
echo "Models downloaded to: ${MODELS_DIR}"
echo ""
echo "Hot Pool (~3.3GB VRAM):"
echo "  - MIND:   ${MODELS_DIR}/Qwen3-Coder-30B-AWQ"
echo "            (handles REFLEX/NERVES/MIND/VOICE roles via temperature)"
echo ""
echo "Cold Pool (~5GB VRAM when loaded):"
echo "  - EYES:   ${MODELS_DIR}/Qwen3-VL-2B-Instruct"
echo "            (swaps with MIND for vision tasks)"
echo ""
echo "CPU (no VRAM):"
echo "  - Embedding: ${MODELS_DIR}/all-MiniLM-L6-v2"
echo ""
echo "Remote (SERVER on separate machine):"
echo "  - SERVER: Qwen3-Coder-30B (configure SERVER_ENDPOINT in .env)"
echo ""
echo "NOT USED:"
echo "  - Qwen3-0.6B (REFLEX) - MIND handles classification adequately"
```

### 6.2 Model Verification

```bash
#!/bin/bash
# scripts/verify_models.sh

MODELS_DIR="${MODELS_DIR:-./models}"

echo "=== Verifying Model Downloads (Simplified Stack) ==="

# Hot pool model (single model for all text roles)
if [ -d "${MODELS_DIR}/Qwen3-Coder-30B-AWQ" ]; then
    echo "✓ Qwen3-Coder-30B-AWQ: Found (hot pool - ALL text roles)"
else
    echo "✗ Qwen3-Coder-30B-AWQ: NOT FOUND"
fi

# Cold pool models
if [ -d "${MODELS_DIR}/Qwen3-VL-2B-Instruct" ]; then
    echo "✓ Qwen3-VL-2B-Instruct: Found (cold pool - vision)"
else
    echo "✗ Qwen3-VL-2B-Instruct: NOT FOUND"
fi

# Embedding model (CPU)
if [ -d "${MODELS_DIR}/all-MiniLM-L6-v2" ]; then
    echo "✓ all-MiniLM-L6-v2: Found (CPU - embeddings)"
else
    echo "✗ all-MiniLM-L6-v2: NOT FOUND"
fi

# Note about REFLEX
echo ""
echo "Note: Qwen3-0.6B (REFLEX) is NOT USED - MIND handles classification."
```

### 6.3 Model Summary (Simplified Stack - vLLM Tested)

| Role | Model | Path | VRAM | Pool |
|------|-------|------|------|------|
| MIND | Qwen3-Coder-30B-AWQ | models/Qwen3-Coder-30B-AWQ | ~3.3GB | Hot |
| (REFLEX) | via MIND | temp=0.3 | - | - |
| (NERVES) | via MIND | temp=0.1 | - | - |
| (VOICE) | via MIND | temp=0.7 | - | - |
| EYES | Qwen3-VL-2B | models/Qwen3-VL-2B-Instruct | ~5.0GB | Cold |
| SERVER | Qwen3-Coder-30B | (remote) | - | Remote |
| Embedding | all-MiniLM-L6-v2 | models/all-MiniLM-L6-v2 | 0 | CPU |

**Note:** Single MIND model handles ALL text roles via temperature. Qwen3-0.6B (REFLEX) is NOT used - testing showed MIND handles classification adequately.

---

## 7. Startup/Shutdown Scripts

### 7.1 Health Check Script

Create `scripts/health_check.sh`:

```bash
#!/bin/bash

echo "=== PandaAI v2 Health Check ==="
echo ""

# Check Docker services
echo "Docker Services:"
echo "----------------"

# Qdrant
if curl -s http://localhost:6333/health > /dev/null 2>&1; then
    echo "✓ Qdrant (6333): healthy"
else
    echo "✗ Qdrant (6333): not responding"
fi

# PostgreSQL
if docker compose exec -T postgres pg_isready -U pandora -d pandora > /dev/null 2>&1; then
    echo "✓ PostgreSQL (5432): healthy"
else
    echo "✗ PostgreSQL (5432): not responding"
fi

echo ""
echo "Application Services:"
echo "---------------------"

# vLLM
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ vLLM (8000): healthy"
else
    echo "✗ vLLM (8000): not responding"
fi

# Orchestrator
if curl -s http://localhost:8090/health > /dev/null 2>&1; then
    echo "✓ Orchestrator (8090): healthy"
else
    echo "✗ Orchestrator (8090): not responding"
fi

# Gateway
if curl -s http://localhost:9000/health > /dev/null 2>&1; then
    echo "✓ Gateway (9000): healthy"
else
    echo "✗ Gateway (9000): not responding"
fi

echo ""
echo "=== Health Check Complete ==="
```

### 7.2 Start Script

Update `scripts/start.sh`:

```bash
#!/bin/bash
set -e

echo "=== Starting PandaAI v2 ==="

# Load environment
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Validate required environment variables
: "${VLLM_HOST:=localhost}"
: "${VLLM_PORT:=8000}"
: "${GATEWAY_HOST:=0.0.0.0}"
: "${GATEWAY_PORT:=9000}"
: "${ORCHESTRATOR_HOST:=0.0.0.0}"
: "${ORCHESTRATOR_PORT:=8090}"
: "${MODELS_DIR:=./models}"

# Create logs and pids directories
mkdir -p logs
mkdir -p .pids

# 1. Start Docker services
echo ""
echo "[1/6] Starting Docker services..."
docker compose up -d

# 2. Wait for Docker services
echo "[2/6] Waiting for Docker services..."
sleep 3

# Check Qdrant
until curl -s http://localhost:6333/health > /dev/null 2>&1; do
    echo "  Waiting for Qdrant..."
    sleep 2
done
echo "  ✓ Qdrant ready"

# Check PostgreSQL
until docker compose exec -T postgres pg_isready -U pandora -d pandora > /dev/null 2>&1; do
    echo "  Waiting for PostgreSQL..."
    sleep 2
done
echo "  ✓ PostgreSQL ready"

# 3. Initialize database (if needed)
# Uncomment on first run:
# ./scripts/init_postgres.sh

# -----------------------------------------------------------------------------
# 4. Start vLLM Server (Simplified - Single MIND Model)
# -----------------------------------------------------------------------------
echo ""
echo "[3/6] Starting vLLM server with MIND model (handles all text roles)..."

# Single vLLM instance with MIND model
# Handles ALL text roles (REFLEX, NERVES, MIND, VOICE) via temperature
echo "  Starting vLLM on port 8000..."
python -m vllm.entrypoints.openai.api_server \
    --host 0.0.0.0 \
    --port 8000 \
    --model "${MODELS_DIR}/Qwen3-Coder-30B-AWQ" \
    --served-model-name "mind" \
    --gpu-memory-utilization 0.80 \
    --max-model-len 4096 \
    --enforce-eager \
    --trust-remote-code \
    > logs/vllm.log 2>&1 &
echo $! > .pids/vllm.pid

# NOTE: Quantization is auto-detected as "compressed-tensors" (not AWQ)
# NOTE: --enforce-eager required on WSL
# NOTE: REFLEX (Qwen3-0.6B) is NOT used - MIND handles classification

# NOTE: EYES (Qwen3-VL-2B) is cold pool - started on demand by model_swap.py
# When EYES is needed, MIND is unloaded and EYES loaded (swap ~8-14s)

# NOTE: SERVER (Qwen3-Coder-30B) is accessed via remote API at SERVER_ENDPOINT

echo "  Waiting for vLLM to initialize..."
sleep 15

# Verify vLLM
if curl -s "http://localhost:8000/health" > /dev/null 2>&1; then
    echo "  ✓ vLLM on port 8000 ready"
else
    echo "  ✗ vLLM on port 8000 not responding (check logs/vllm.log)"
fi

# 5. Start Orchestrator
echo ""
echo "[4/6] Starting Orchestrator..."
python -m uvicorn apps.orchestrator.app:app \
    --host "${ORCHESTRATOR_HOST}" \
    --port "${ORCHESTRATOR_PORT}" \
    > logs/orchestrator.log 2>&1 &
echo $! > .pids/orchestrator.pid

until curl -s "http://localhost:${ORCHESTRATOR_PORT}/health" > /dev/null 2>&1; do
    sleep 1
done
echo "  ✓ Orchestrator ready"

# 6. Start Gateway
echo ""
echo "[5/6] Starting Gateway..."
python -m uvicorn apps.gateway.app:app \
    --host "${GATEWAY_HOST}" \
    --port "${GATEWAY_PORT}" \
    > logs/gateway.log 2>&1 &
echo $! > .pids/gateway.pid

until curl -s "http://localhost:${GATEWAY_PORT}/health" > /dev/null 2>&1; do
    sleep 1
done
echo "  ✓ Gateway ready"

echo ""
echo "[6/6] All services started!"
echo ""
echo "=== PandaAI v2 Started ==="
echo ""
echo "Services:"
echo "  Gateway:      http://localhost:${GATEWAY_PORT}"
echo "  Orchestrator: http://localhost:${ORCHESTRATOR_PORT}"
echo "  vLLM:         http://localhost:8000 (MIND - handles ALL text roles via temperature)"
echo "  vLLM EYES:    (cold pool - started on demand, swaps with MIND)"
echo "  SERVER:       ${SERVER_ENDPOINT:-http://localhost:8001} (remote Qwen3-Coder-30B)"
echo "  Qdrant:       http://localhost:6333"
echo "  PostgreSQL:   localhost:5432"
echo ""
echo "Logs: logs/"
echo "PIDs: .pids/"
```

### 7.3 Stop Script

Update `scripts/stop.sh`:

```bash
#!/bin/bash

echo "=== Stopping PandaAI v2 ==="

# Stop application services using PID files
echo "Stopping application services..."

if [ -d .pids ]; then
    for pidfile in .pids/*.pid; do
        if [ -f "$pidfile" ]; then
            pid=$(cat "$pidfile")
            name=$(basename "$pidfile" .pid)
            if kill -0 "$pid" 2>/dev/null; then
                echo "  Stopping ${name} (PID: ${pid})..."
                kill "$pid" 2>/dev/null || true
            fi
            rm -f "$pidfile"
        fi
    done
fi

# Fallback: Kill by process name
echo "Cleaning up any remaining processes..."
pkill -f "uvicorn apps.gateway" 2>/dev/null || true
pkill -f "uvicorn apps.orchestrator" 2>/dev/null || true
pkill -f "vllm.entrypoints" 2>/dev/null || true

# Stop Docker services
echo "Stopping Docker services..."
docker compose stop

echo ""
echo "=== PandaAI v2 Stopped ==="
```

---

## 8. Qdrant Collection Setup

Create `scripts/init_qdrant.py`:

```python
"""Initialize Qdrant collections for PandaAI v2."""

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

def init_collections():
    """Create Qdrant collections if they don't exist."""
    client = QdrantClient(host="localhost", port=6333)

    # Collection configurations
    collections = [
        {
            "name": "turns",
            "size": 384,  # Embedding dimension
            "distance": Distance.COSINE,
        },
        {
            "name": "research",
            "size": 384,
            "distance": Distance.COSINE,
        },
        {
            "name": "memories",
            "size": 384,
            "distance": Distance.COSINE,
        },
    ]

    for config in collections:
        try:
            client.get_collection(config["name"])
            print(f"Collection '{config['name']}' already exists")
        except Exception:
            client.create_collection(
                collection_name=config["name"],
                vectors_config=VectorParams(
                    size=config["size"],
                    distance=config["distance"],
                ),
            )
            print(f"Created collection '{config['name']}'")

    print("Qdrant initialization complete!")

if __name__ == "__main__":
    init_collections()
```

---

## 9. Verification Checklist

Before proceeding to Phase 2, verify:

- [ ] Conda environment created and activated (`conda activate pandaai`)
- [ ] Python 3.11 installed (`python --version`)
- [ ] PyTorch with CUDA working (`python -c "import torch; print(torch.cuda.is_available())"`)
- [ ] vLLM installed (`python -c "import vllm"`)
- [ ] Directory structure created
- [ ] `pyproject.toml` or `requirements.txt` created
- [ ] Project dependencies installed (`pip install -r requirements.txt`)
- [ ] `.env` file configured from `.env.example`
- [ ] Docker services start successfully (`docker compose up -d`)
- [ ] Qdrant health check passes
- [ ] PostgreSQL health check passes
- [ ] Database schema applied
- [ ] Qdrant collections created
- [ ] All models downloaded to `models/` directory
- [ ] All scripts have execute permission (`chmod +x scripts/*.sh`)
- [ ] Playwright browsers installed (`playwright install chromium`)

---

## Deliverables Checklist

| Item | Status |
|------|--------|
| Directory structure | |
| `pyproject.toml` | |
| `requirements.txt` | |
| `.env.example` | |
| `.env` | |
| `scripts/init_db.sql` | |
| `scripts/init_postgres.sh` | |
| `scripts/init_qdrant.py` | |
| `scripts/health_check.sh` | |
| `scripts/start.sh` | |
| `scripts/stop.sh` | |

---

**Next Phase:** [02-CORE-LIBRARIES.md](./02-CORE-LIBRARIES.md)
