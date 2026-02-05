# LLM Roles Quick Reference

**Version:** 5.1
**Updated:** 2026-01-26

Quick reference for the single-model multi-role system. For detailed specs, see individual phase docs.

---

## Model Stack

| Component | Model | Server | VRAM | Notes |
|-----------|-------|--------|------|-------|
| ALL ROLES | Qwen3-Coder-30B-AWQ | vLLM (8000) | ~20GB | Single model for all text tasks |
| Vision | EasyOCR | CPU | 0 | OCR-based text extraction |
| Embedding | all-MiniLM-L6-v2 | CPU | 0 | Semantic search |

**Hardware:** RTX 3090 Server (24GB VRAM)

**Architecture:** Single-model system - one Qwen3-Coder-30B-AWQ instance handles all roles.
Role behavior is controlled entirely by temperature and system prompts.

---

## Text Roles

All roles use the same Qwen3-Coder-30B model with different temperatures:

| Role | Temperature | Purpose | Used By |
|------|-------------|---------|---------|
| REFLEX | 0.3 | Classification, binary decisions, fast gates | Phase 0, 1 |
| NERVES | 0.1 | Compression, low creativity | Background compression |
| MIND | 0.5 | Reasoning, planning, coordination | Phase 2, 3, 4, 6 |
| VOICE | 0.7 | User dialogue, natural responses | Phase 5 |

**Why temperature-based roles work:**
- Lower temp (0.1-0.3): More deterministic, good for classification
- Medium temp (0.5): Balanced reasoning
- Higher temp (0.7): More varied, natural-sounding responses

---

## vLLM Configuration

```bash
python -m vllm.entrypoints.openai.api_server \
  --model models/qwen3-coder-30b-awq4 \
  --served-model-name qwen3-coder \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192 \
  --port 8000
```

**API Endpoint:** `http://localhost:8000/v1/chat/completions`

---

## Phase → Role Mapping

| Phase | Name | Role | Temp | Recipe | Purpose |
|-------|------|------|------|--------|---------|
| 0 | Query Analyzer | REFLEX | 0.3 | `query_analyzer.yaml` | Classify intent |
| 1 | Reflection | REFLEX | 0.3 | `reflection.yaml` | PROCEED/CLARIFY gate |
| 2 | Context Gatherer | MIND | 0.5 | `context_gatherer_*.yaml` | Gather context |
| 3 | Planner | MIND | 0.5 | `planner_*.yaml` | Plan tasks |
| 4 | Coordinator | MIND | 0.5 | `coordinator_*.yaml` | Execute tools |
| 5 | Synthesis | VOICE | 0.7 | `synthesizer_*.yaml` | Generate response |
| 6 | Validation | MIND | 0.5 | `validator.yaml` | Verify accuracy |
| 7 | Save | N/A | N/A | - | Persist turn |

---

## Research Subsystem Roles

The internet.research tool (invoked from Phase 4) has its own LLM roles:

| Role | Temperature | Recipe | Purpose |
|------|-------------|--------|---------|
| Research Planner | MIND (0.5) | `research_planner.yaml` | Decides next action (search/visit/done) |
| Result Scorer | REFLEX (0.3) | `research_scorer.yaml` | Scores search results for relevance |
| Content Extractor | MIND (0.5) | `research_extractor.yaml` | Extracts findings from page text |

**Document IO Compliance:**
- Research roles can read from `context.md` and `research_state.md` via recipes
- Research Planner checks `context.md §2` for prior intelligence before starting Phase 1
- State is persisted to turn directory via `ResearchState.write_to_turn()`

See: `architecture/mcp-tool-patterns/internet-research-mcp/INTERNET_RESEARCH_ARCHITECTURE.md`

---

## Token Budgets

| Phase | Role | Total | Prompt | Input | Output |
|-------|------|-------|--------|-------|--------|
| 0 | REFLEX | 1,500 | 500 | 700 | 300 |
| 1 | REFLEX | 2,200 | 600 | 1,200 | 400 |
| 2 | MIND | 10,500 | 2,000 | 6,000 | 2,500 |
| 3 | MIND | 5,750 | 1,540 | 2,000 | 2,000 |
| 4 | MIND | 8,000-12,000 | 2,500 | 3,500 | 2,000 |
| 5 | VOICE | 10,000 | 1,300 | 5,500 | 3,000 |
| 6 | MIND | 6,000 | 1,500 | 4,000 | 500 |

**Context Window:** 8192 tokens (vLLM configured)

---

## Phase Decisions

| Phase | Decision | Action |
|-------|----------|--------|
| 1 | PROCEED | → Phase 2 |
| 1 | CLARIFY | → User |
| 3 | coordinator | → Phase 4 |
| 3 | synthesis | → Phase 5 |
| 3 | clarify | → User |
| 6 | APPROVE | → Phase 7 |
| 6 | REVISE | → Phase 5 (max 2) |
| 6 | RETRY | → Phase 3 (max 1) |
| 6 | FAIL | → User (error) |

---

## Quality Gates

| Gate | Phase | Enforcement |
|------|-------|-------------|
| Schema | All | Output must match role schema |
| Evidence | 4, 5, 6 | Claims must link to documents |
| Confidence | 2, 6 | Below threshold → escalate |
| Validation | 6 | APPROVE/REVISE/RETRY/FAIL |

---

## Error Limits

| Limit | Value |
|-------|-------|
| Max LLM calls per turn | 25 |
| Max Planner-Coordinator iterations | 5 |
| Max RETRY loops | 1 |
| Max REVISE loops | 2 |
| Combined loop max | 3 |

---

## NERVES Background Compression

NERVES is NOT part of the main 8-phase pipeline. It handles background document
compression when sections exceed token budgets:

- Triggered asynchronously when content exceeds budget
- Uses temperature 0.1 for deterministic compression
- Verifies key facts are preserved after compression

---

## Vision: EasyOCR

For vision tasks, we use EasyOCR for text extraction from images:

```python
import easyocr
reader = easyocr.Reader(['en'], gpu=False)  # CPU mode

def extract_text_from_image(image_path: str) -> list[dict]:
    results = reader.readtext(image_path)
    return [
        {"bbox": bbox, "text": text, "confidence": conf}
        for bbox, text, conf in results
    ]
```

**Use Cases:**
- Web page navigation (screenshots)
- Document text extraction
- UI element identification

**Future:** EYES vision model (Qwen-VL) for complex image understanding
(charts, diagrams, photos) once the system is stable.

---

## Detailed Documentation

| Topic | Document |
|-------|----------|
| Document IO | `DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` |
| Phase 0 | `main-system-patterns/phase0-query-analyzer.md` |
| Phase 1 | `main-system-patterns/phase1-reflection.md` |
| Phase 2 | `main-system-patterns/phase2-context-gathering.md` |
| Phase 3 | `main-system-patterns/phase3-planner.md` |
| Phase 4 | `main-system-patterns/phase4-executor.md` |
| Phase 5 | `main-system-patterns/phase5-coordinator.md` |
| Phase 6 | `main-system-patterns/phase6-synthesis.md` |
| Phase 7 | `main-system-patterns/phase7-validation.md` |
| Phase 8 | `main-system-patterns/phase8-save.md` |

---

**Last Updated:** 2026-01-26

**v5.1 Changes:** Added Research Subsystem Roles section documenting Research Planner (MIND 0.5), Result Scorer (REFLEX 0.3), and Content Extractor (MIND 0.5) with Document IO compliance notes.
