# Prompting Manual for Pandora's Single-Model System

This document details prompt design for the Pandora single-model multi-role system.

## Overview: Single-Model Architecture

Pandora uses a single-model system running on RTX 3090 (24GB VRAM):

| Model | Server | Roles | When Used |
|-------|--------|-------|-----------|
| Qwen3-Coder-30B-AWQ | vLLM (8000) | REFLEX, NERVES, MIND, VOICE | All text tasks |
| EasyOCR | CPU | N/A | Vision/OCR tasks |

**Key Points:**
- All text roles use the same Qwen3-Coder-30B model with different temperatures
- Role behavior is controlled entirely by temperature and system prompts
- No model swapping required - single model handles everything
- Vision tasks use EasyOCR (CPU-based OCR), not a vision LLM

---

## Qwen3-Coder-30B (All Text Roles)

**Model:** Qwen3-Coder-30B-AWQ via vLLM

**Model Type:** Qwen3-Coder is a coding-specialized LLM by Alibaba. The 30B AWQ version
provides strong reasoning and code generation capabilities while fitting in 24GB VRAM.

**Prompt Format:** Use Qwen's chat template with role-based messages via vLLM's OpenAI-compatible API:

```python
import openai

client = openai.OpenAI(base_url="http://localhost:8000/v1", api_key="dummy")

response = client.chat.completions.create(
    model="qwen3-coder",
    messages=[
        {"role": "system", "content": "You are a helpful AI assistant."},
        {"role": "user", "content": "Classify this query intent."}
    ],
    temperature=0.3  # Adjust per role
)
```

**Temperature by Role:**

| Role | Temperature | Use Case |
|------|-------------|----------|
| REFLEX | 0.3 | Classification, binary decisions, fast gates |
| NERVES | 0.1 | Compression, summarization (low creativity) |
| MIND | 0.5 | Reasoning, planning, coordination |
| VOICE | 0.7 | User-facing dialogue (more natural) |

**Notes:**
- All roles use the same model - behavior is controlled by temperature and system prompt
- vLLM serves model as "qwen3-coder" via `--served-model-name qwen3-coder`
- Context window: 8192 tokens (configured in vLLM)

---

## Vision: EasyOCR

For vision tasks, we use EasyOCR for text extraction from images rather than a
vision LLM. This runs on CPU and doesn't require model swapping.

```python
import easyocr

reader = easyocr.Reader(['en'], gpu=False)  # CPU mode

def extract_text_from_image(image_path: str) -> list[dict]:
    results = reader.readtext(image_path)
    return [
        {"bbox": bbox, "text": text, "confidence": conf}
        for bbox, text, conf in results
    ]

# Example usage
texts = extract_text_from_image("screenshot.png")
for item in texts:
    print(f"Found text: {item['text']} (confidence: {item['confidence']:.2f})")
```

**Use Cases:**
- Web page navigation (reading buttons, links, text)
- Document text extraction
- UI element identification
- Screenshot analysis

**Limitations:**
- OCR only extracts text, no visual understanding
- Cannot interpret charts, diagrams, or non-text content
- Works best with clear, high-contrast text

**Future: EYES Vision Model**

Once the system is stable, we plan to add the EYES vision model (Qwen-VL) for
complex image understanding tasks that OCR cannot handle:
- Chart and diagram interpretation
- Photo analysis and description
- Visual reasoning tasks

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

**Environment Variables (.env):**
```bash
SOLVER_URL=http://127.0.0.1:8000/v1/chat/completions
SOLVER_MODEL_ID=qwen3-coder
```

---

## Phase → Role → Temperature Mapping

| Phase | Name | Role | Temp | Purpose |
|-------|------|------|------|---------|
| 0 | Query Analyzer | REFLEX | 0.3 | Classify intent |
| 1 | Reflection | REFLEX | 0.3 | PROCEED/CLARIFY gate |
| 2 | Context Gatherer | MIND | 0.5 | Gather context |
| 3 | Planner | MIND | 0.5 | Plan tasks |
| 4 | Coordinator | MIND | 0.5 | Execute tools |
| 5 | Synthesis | VOICE | 0.7 | Generate response |
| 6 | Validation | MIND | 0.5 | Verify accuracy |
| 7 | Save | N/A | N/A | Persist turn |

**NERVES** is used for background compression, not a pipeline phase.

---

## References

- Qwen/Qwen3-Coder - Hugging Face: https://huggingface.co/Qwen/Qwen3-Coder
- vLLM OpenAI-compatible API: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html
- EasyOCR: https://github.com/JaidedAI/EasyOCR

---

**Last Updated:** 2026-01-09
