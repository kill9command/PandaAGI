# Docker Integration Architecture

**Status:** SPECIFICATION
**Version:** 1.0
**Created:** 2026-01-05
**Architecture:** PandaAI v2

---

## 1. Overview

This document specifies the Docker infrastructure design for PandaAI v2. Docker Compose orchestrates stateful services (databases) while the core application (Gateway, Orchestrator, vLLM) runs directly on the host for GPU access and development flexibility.

**Philosophy:** Docker for infrastructure, host for application.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        HOST MACHINE                                  │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                  APPLICATION LAYER                           │    │
│  │                                                              │    │
│  │  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐     │    │
│  │  │ Gateway  │  │ Orchestrator │  │ vLLM (GPU access)  │     │    │
│  │  │ :9000    │  │ :8090        │  │ :8000              │     │    │
│  │  └────┬─────┘  └──────┬───────┘  └────────────────────┘     │    │
│  │       │               │                                      │    │
│  └───────┼───────────────┼──────────────────────────────────────┘    │
│          │               │                                           │
│          ▼               ▼                                           │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                  DOCKER COMPOSE                              │    │
│  │                                                              │    │
│  │  ┌─────────────────┐      ┌─────────────────────────┐       │    │
│  │  │     Qdrant      │      │      PostgreSQL         │       │    │
│  │  │  Vector Store   │      │   Relational Store      │       │    │
│  │  │    :6333        │      │       :5432             │       │    │
│  │  │                 │      │                         │       │    │
│  │  │  qdrant_data    │      │    postgres_data        │       │    │
│  │  │   (volume)      │      │      (volume)           │       │    │
│  │  └─────────────────┘      └─────────────────────────┘       │    │
│  │                                                              │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                  FILE-BASED STORAGE                          │    │
│  │                                                              │    │
│  │  panda_system_docs/                                          │    │
│  │  ├── turns/             # Turn documents (context.md)        │    │
│  │  ├── site_knowledge/    # Learned site patterns              │    │
│  │  ├── turn_index.db      # SQLite (to migrate → Postgres)     │    │
│  │  ├── research_index.db  # SQLite (to migrate → Postgres)     │    │
│  │  └── source_reliability.db                                   │    │
│  │                                                              │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Docker Compose Services

### 2.1 Current Configuration

**File:** `docker-compose.yml`

```yaml
services:
  vectordb:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 10s

  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: pandora
      POSTGRES_PASSWORD: pandora
      POSTGRES_DB: pandora
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U pandora -d pandora"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  qdrant_data:
  postgres_data:
```

### 2.2 Service Descriptions

| Service | Image | Port | Purpose | Data Persistence |
|---------|-------|------|---------|------------------|
| `vectordb` | qdrant/qdrant:latest | 6333 | Vector similarity search | `qdrant_data` volume |
| `postgres` | postgres:16 | 5432 | Relational database | `postgres_data` volume |

---

## 3. Qdrant Vector Database

### 3.1 Purpose

Qdrant provides vector similarity search for semantic retrieval operations:

| Use Case | Description | Collection |
|----------|-------------|------------|
| **Turn Embedding Search** | Find semantically similar past turns | `turns` |
| **Research Embedding Search** | Find related research documents | `research` |
| **Memory Search** | Semantic search across user memories | `memories` |

### 3.2 Integration Points

```
┌─────────────────────────────────────────────────────────────────┐
│                    QDRANT INTEGRATION                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Phase 2: Context Gatherer                                       │
│  ─────────────────────────                                       │
│  1. Embed user query using embedding model                       │
│  2. Search Qdrant for similar past turns/research                │
│  3. Retrieve top-K results                                       │
│  4. Include in §2 (gathered context)                             │
│                                                                  │
│  Phase 7: Save                                                   │
│  ─────────────                                                   │
│  1. Embed context.md summary                                     │
│  2. Upsert to Qdrant with turn metadata                          │
│  3. Enable future semantic retrieval                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 Collection Schema (Target)

```json
{
  "collection_name": "turns",
  "vectors": {
    "size": 384,
    "distance": "Cosine"
  },
  "payload_schema": {
    "turn_number": "integer",
    "session_id": "keyword",
    "topic": "text",
    "intent": "keyword",
    "timestamp": "datetime",
    "quality": "float"
  }
}
```

### 3.4 API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `http://localhost:6333` | REST API |
| `http://localhost:6333/dashboard` | Web UI (Qdrant Dashboard) |

### 3.5 Client Usage

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

client = QdrantClient(host="localhost", port=6333)

# Create collection
client.create_collection(
    collection_name="turns",
    vectors_config=VectorParams(size=384, distance=Distance.COSINE)
)

# Search similar turns
results = client.search(
    collection_name="turns",
    query_vector=query_embedding,
    limit=5,
    query_filter={"session_id": session_id}
)
```

---

## 4. PostgreSQL Database

### 4.1 Purpose

PostgreSQL provides relational storage for structured data:

| Table | Purpose |
|-------|---------|
| `pandora.turns` | Turn metadata index |
| `pandora.research` | Research cache index |
| `pandora.sources` | Source trust scores |
| `pandora.observability` | Metrics and trends |

### 4.2 Why PostgreSQL

| Capability | Benefit |
|------------|---------|
| **Concurrency** | Multiple writers supported |
| **Scaling** | Horizontal scaling possible |
| **Full-Text Search** | Advanced tsquery support |
| **JSON Support** | JSONB with indexing |
| **Transactions** | Full ACID with savepoints |
| **Production Ready** | Battle-tested, production grade |

### 4.3 Schema

```sql
-- Turn Index
CREATE TABLE turns (
    turn_number SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    topic TEXT,
    intent TEXT,
    keywords JSONB,
    quality FLOAT,
    turn_dir TEXT NOT NULL,
    embedding_id UUID  -- References Qdrant vector
);

CREATE INDEX idx_turns_session ON turns(session_id, timestamp DESC);
CREATE INDEX idx_turns_topic ON turns USING gin(to_tsvector('english', topic));

-- Research Index
CREATE TABLE research (
    id SERIAL PRIMARY KEY,
    turn_number INTEGER REFERENCES turns(turn_number),
    primary_topic TEXT NOT NULL,
    quality_overall FLOAT,
    confidence_current FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    scope TEXT,
    content_types JSONB,
    doc_path TEXT
);

CREATE INDEX idx_research_topic ON research(primary_topic);
CREATE INDEX idx_research_quality ON research(quality_overall DESC);

-- Source Reliability
CREATE TABLE sources (
    domain TEXT PRIMARY KEY,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    last_success TIMESTAMPTZ,
    last_failure TIMESTAMPTZ,
    reliability_score FLOAT DEFAULT 0.5,
    notes JSONB
);
```

### 4.4 Connection Configuration

```python
# Environment variables
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=pandora
POSTGRES_USER=pandora
POSTGRES_PASSWORD=pandora  # Change in production!

# Connection string
DATABASE_URL=postgresql://pandora:pandora@localhost:5432/pandora
```

### 4.5 Schema Deployment

On first startup, run schema initialization:

```bash
# Apply schema
docker compose exec postgres psql -U pandora -d pandora -f /schema/init.sql

# Or use application migration tool (when implemented)
python -m pandora.db.migrate
```

---

## 5. Docker Operations

### 5.1 Starting Services

```bash
# Start all Docker services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f vectordb
docker compose logs -f postgres
```

### 5.2 Stopping Services

```bash
# Stop services (keeps data)
docker compose stop

# Stop and remove containers (keeps volumes)
docker compose down

# Stop and remove everything including volumes (DATA LOSS!)
docker compose down -v
```

### 5.3 Health Checks

```bash
# Check container health status (uses built-in healthchecks)
docker compose ps

# Manual Qdrant health
curl http://localhost:6333/health

# Manual PostgreSQL health
docker compose exec postgres pg_isready -U pandora -d pandora

# Quick validation script
./scripts/docker_health.sh
```

### 5.4 Data Backup

```bash
# Backup Qdrant data
docker run --rm -v pandaaiv2_qdrant_data:/data -v $(pwd)/backups:/backup \
    alpine tar czf /backup/qdrant_$(date +%Y%m%d).tar.gz /data

# Backup PostgreSQL
docker compose exec postgres pg_dump -U pandora pandora > backups/postgres_$(date +%Y%m%d).sql
```

---

## 6. Why Not Containerize Everything?

### 6.1 GPU Access

vLLM requires direct GPU access for inference:

```
vLLM (Host) ──── CUDA ──── RTX 3090 (24GB VRAM)
                              │
                              ├── REFLEX  (~0.2GB)
                              ├── NERVES  (~0.5GB)
                              ├── MIND    (~1.0GB)
                              ├── VOICE   (~4.0GB)
                              └── EYES    (~4.0GB, cold)
```

Docker GPU passthrough adds complexity and latency. Running vLLM on host provides:
- Direct CUDA access
- Simpler debugging
- Better performance
- Easier model management

### 6.2 Development Workflow

Host-based application services enable:
- Hot reload during development
- Direct file system access
- Easier debugging with IDE
- No container rebuild cycle

### 6.3 What SHOULD Be Containerized

| Service | Containerize? | Reason |
|---------|---------------|--------|
| Qdrant | Yes | Stateful, isolated, easy upgrade |
| PostgreSQL | Yes | Stateful, isolated, easy backup |
| Redis (future) | Yes | Stateful, isolated |
| Gateway | No | Development, hot reload |
| Orchestrator | No | Development, file access |
| vLLM | No | GPU access required |

---

## 7. Production Considerations

### 7.1 Security

**Current (Development):**
```yaml
environment:
  POSTGRES_USER: pandora
  POSTGRES_PASSWORD: pandora  # INSECURE - change in production!
  POSTGRES_DB: pandora
```

**Production:**
```yaml
environment:
  POSTGRES_PASSWORD_FILE: /run/secrets/db_password
secrets:
  db_password:
    external: true
```

### 7.2 Resource Limits

```yaml
services:
  postgres:
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '1.0'
        reservations:
          memory: 512M

  vectordb:
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: '2.0'
```

### 7.3 Networking

**Development:** All services on default bridge network, exposed ports.

**Production:**
```yaml
networks:
  backend:
    driver: bridge
    internal: true  # No external access

services:
  postgres:
    networks:
      - backend
    # No ports exposed externally
```

### 7.4 Logging

```yaml
services:
  postgres:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

---

## 8. Future Docker Services

### 8.1 Planned Additions

| Service | Purpose | Priority |
|---------|---------|----------|
| Redis | Session cache, rate limiting | High |
| MinIO | Object storage for screenshots | Medium |
| Grafana | Metrics visualization | Medium |
| Prometheus | Metrics collection | Medium |

### 8.2 Redis Integration (Planned)

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
```

**Use Cases:**
- Session state caching
- Rate limiting counters
- Pub/sub for real-time updates
- Research cache (fast layer)

---

## 9. Troubleshooting

### 9.1 Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Port 6333 in use | Another Qdrant instance | `docker compose down` other projects |
| Port 5432 in use | Local PostgreSQL | Stop local postgres or change port |
| Volume permission denied | Docker user mismatch | `sudo chown -R 1000:1000 volumes/` |
| Container keeps restarting | Misconfiguration | Check `docker compose logs` |

### 9.2 Reset Everything

```bash
# Nuclear option - removes ALL data
docker compose down -v
docker compose up -d

# Recreate specific service
docker compose up -d --force-recreate postgres
```

### 9.3 Inspect Volumes

```bash
# List volumes
docker volume ls | grep pandaaiv2

# Inspect volume
docker volume inspect pandaaiv2_qdrant_data

# Browse volume contents
docker run --rm -v pandaaiv2_qdrant_data:/data alpine ls -la /data
```

---

## 10. Integration with Application

### 10.1 Startup Order

```bash
#!/bin/bash
# scripts/start.sh

# 1. Start Docker services first
docker compose up -d

# 2. Wait for services to be ready
./scripts/wait_for_services.sh

# 3. Start application services
python -m vllm.entrypoints.openai.api_server &  # vLLM
python apps/orchestrator/app.py &                # Orchestrator
python apps/gateway/app.py &                     # Gateway
```

### 10.2 Service Dependencies

```
┌────────────────────────────────────────────────────────────────┐
│                    SERVICE STARTUP ORDER                        │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Docker Compose Services (infrastructure)                    │
│     ├── Qdrant (vector store)                                   │
│     └── PostgreSQL (relational store)                           │
│                                                                 │
│  2. vLLM (model inference)                                      │
│     └── Waits for GPU availability                              │
│                                                                 │
│  3. Orchestrator (tool execution)                               │
│     └── Waits for vLLM health check                             │
│                                                                 │
│  4. Gateway (pipeline orchestration)                            │
│     ├── Waits for Orchestrator health check                     │
│     ├── Waits for Qdrant health check                           │
│     └── Waits for PostgreSQL health check                       │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## 11. Related Documentation

- [Memory Architecture](../DOCUMENT-IO-SYSTEM/MEMORY_ARCHITECTURE.md) - How databases are used
- [Phase 7: Save](../main-system-patterns/phase7-save.md) - Turn persistence
- [Observability System](../DOCUMENT-IO-SYSTEM/OBSERVABILITY_SYSTEM.md) - Metrics storage

---

**Last Updated:** 2026-01-05
