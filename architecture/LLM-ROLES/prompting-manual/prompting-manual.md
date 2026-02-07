# Prompting Manual for Panda's Single-Model System

This document details prompt design for the Panda single-model multi-role system.

## Overview: Single-Model Architecture

Panda uses a single-model system running on RTX 3090 (24GB VRAM):

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

## Qwen3-Coder-30B Model Specifications

**Model:** Qwen3-Coder-30B-AWQ via vLLM

**Model Type:** Qwen3-Coder is a coding-specialized MoE (Mixture-of-Experts) LLM by Alibaba.
The 30B AWQ version activates ~3.3B parameters at inference time, providing strong reasoning
and code generation while fitting in 24GB VRAM.

**Key Capabilities:**
- Supports 358 programming languages
- Native 256K token context window (extendable to 1M with YaRN)
- Fill-in-the-Middle (FIM) code completion
- Agentic coding and function calling
- **No Thinking Mode**: Unlike standard Qwen3, Qwen3-Coder does NOT generate `<think></think>` blocks

---

## ChatML Prompt Format

Qwen3-Coder uses the **ChatML template** - the same format used by OpenAI and many open-source models.

### Special Tokens

| Token | Purpose |
|-------|---------|
| `<\|im_start\|>` | Start of a message turn |
| `<\|im_end\|>` | End of a message turn |
| `system` | System instruction role |
| `user` | User message role |
| `assistant` | Model response role |

### Raw ChatML Format

```
<|im_start|>system
You are a helpful AI assistant.<|im_end|>
<|im_start|>user
Your question here<|im_end|>
<|im_start|>assistant
```

### Using via OpenAI-Compatible API

```python
import openai

client = openai.OpenAI(base_url="http://localhost:8000/v1", api_key="dummy")

response = client.chat.completions.create(
    model="qwen3-coder",
    messages=[
        {"role": "system", "content": "You are a helpful AI assistant."},
        {"role": "user", "content": "Classify this query intent."}
    ],
    temperature=0.7,
    top_p=0.8,
    # top_k and repetition_penalty via extra_body if needed
)
```

### Using via Transformers

```python
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-Coder-30B")

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Write a function to sort a list."}
]

text = tokenizer.apply_chat_template(
    messages,
    tokenize=False,
    add_generation_prompt=True  # Appends <|im_start|>assistant\n
)
```

---

## Inference Settings

### Qwen Official Recommendations

Qwen recommends these settings for Qwen3-Coder-30B:

| Parameter | Value | Notes |
|-----------|-------|-------|
| `temperature` | 0.7 | Default for balanced outputs |
| `top_p` | 0.8 | Nucleus sampling threshold |
| `top_k` | 20 | Limit token candidates |
| `repetition_penalty` | 1.05 | Prevent repetitive text |
| `max_new_tokens` | 65536 | Standard; up to 32768+ for complex tasks |

**Important:** Do NOT use greedy decoding (temperature=0) as it can cause endless repetitions.

### Panda Role-Based Temperature Strategy

While Qwen recommends a single temperature (0.7), Panda uses **role-based temperatures** to
control output characteristics for different pipeline phases:

| Role | Temperature | Rationale |
|------|-------------|-----------|
| REFLEX | 0.3 | Classification, binary decisions - need deterministic outputs |
| NERVES | 0.1 | Compression, summarization - minimal creativity needed |
| MIND | 0.5 | Reasoning, planning - balanced exploration |
| VOICE | 0.7 | User dialogue - natural, varied responses (matches Qwen default) |

**Why deviate from 0.7?**
- Lower temperatures (0.1-0.3) produce more consistent, predictable outputs for classification tasks
- The VOICE role uses 0.7 to match Qwen's recommendation for natural dialogue
- This approach leverages the model's flexibility while optimizing for task-specific needs

---

## Structured Output / JSON Mode

For tasks requiring structured JSON output, use explicit system prompts:

### Basic JSON Mode
```python
messages = [
    {"role": "system", "content": "You are a JSON generator. Always return clean, valid JSON only. No commentary."},
    {"role": "user", "content": "Extract entities from: 'Apple released iPhone 15 in September 2023'"}
]
```

### Schema-Constrained JSON (Hermes-style)
```python
schema = {
    "type": "object",
    "properties": {
        "action_needed": {"type": "string", "enum": ["live_search", "recall_memory", "answer_from_context", "navigate_to_site", "execute_code", "unclear"]},
        "confidence": {"type": "number"}
    },
    "required": ["action_needed", "confidence"]
}

messages = [
    {"role": "system", "content": f"""You are a helpful assistant that answers in JSON.
Here's the json schema you must adhere to:
<schema>
{json.dumps(schema)}
</schema>"""},
    {"role": "user", "content": "Classify: 'buy cheap flights to Paris'"}
]
```

---

## Fill-in-the-Middle (FIM) Code Completion

Qwen3-Coder supports FIM for inserting code between existing code segments.

### FIM Special Tokens

| Token | Purpose |
|-------|---------|
| `<\|fim_prefix\|>` | Code before the insertion point |
| `<\|fim_suffix\|>` | Code after the insertion point |
| `<\|fim_middle\|>` | Marker for where model should generate |

### FIM Example

```python
fim_prompt = """<|fim_prefix|>def calculate_total(items):
    total = 0
    for item in items:
<|fim_suffix|>
    return total

# Test
print(calculate_total([1, 2, 3]))
<|fim_middle|>"""

# Model generates: "        total += item"
```

### FIM Settings

```python
eos_token_ids = [151659, 151661, 151662, 151663, 151664, 151643, 151645]
max_new_tokens = 512  # FIM completions are typically short
```

---

## Tool Calling / Function Calling

Qwen3-Coder supports function calling with a custom tool parser format.

### Tool Definition Format

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
                },
                "required": ["location"]
            }
        }
    }
]
```

### Important Notes

- Qwen3-Coder uses updated special tokens for tool calling (different from Qwen2.5)
- Always use the tokenizer bundled with the model for correct token IDs
- The model outputs tool calls in a structured format that requires parsing

---

## System Prompt Best Practices

### Be Explicit About Output Format

```python
# Good - explicit format
{"role": "system", "content": "You are a code assistant. Return ONLY code, no explanations."}

# Good - explicit JSON
{"role": "system", "content": "Return a JSON object with keys: intent, confidence, reasoning"}
```

### Use Role-Appropriate Personas

```python
# REFLEX role - classifier
{"role": "system", "content": "You are an intent classifier. Classify queries into exactly one category."}

# MIND role - planner
{"role": "system", "content": "You are a strategic planner. Break down tasks into actionable steps."}

# VOICE role - dialogue
{"role": "system", "content": "You are a helpful assistant. Respond naturally and conversationally."}
```

### Avoid These Anti-Patterns

1. **Empty system prompts** - Always provide context
2. **Greedy decoding** - Don't set temperature=0 (causes repetition)
3. **Vague instructions** - Be specific about expected output format
4. **Overly long system prompts** - Keep concise; detail belongs in user message

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
  --max-model-len 65536 \
  --port 8000
```

**Note:** The model supports 256K context natively. We configure vLLM with 65536 tokens
as a practical limit for RTX 3090 memory constraints.

**Environment Variables (.env):**
```bash
SOLVER_URL=http://127.0.0.1:8000/v1/chat/completions
SOLVER_MODEL_ID=qwen3-coder
```

---

## Phase → Role → Temperature Mapping

| Phase | Name | Role | Temp | Purpose |
|-------|------|------|------|---------|
| 0 | Query Analyzer | REFLEX | 0.3 | Classify action, capture user purpose |
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

### Official Documentation
- [Qwen3-Coder GitHub](https://github.com/QwenLM/Qwen3-Coder) - Official repository
- [Qwen3-Coder-30B-A3B-Instruct](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct) - HuggingFace model card
- [vLLM OpenAI-compatible API](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html)
- [EasyOCR](https://github.com/JaidedAI/EasyOCR)

### Prompting Guides
- [ChatML Template Guide](https://huggingface.co/docs/transformers/en/chat_templating) - HuggingFace chat templates
- [Qwen3 Prompt Engineering](https://qwen3lm.com/qwen3-prompt-engineering-structured-output/) - Structured output guide
- [Nous Research Hermes](https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-8B) - ChatML and JSON mode patterns

### Research
- [Prompt Engineering Taxonomy (2025)](https://link.springer.com/article/10.1007/s11704-025-50058-z) - Academic survey
- [IBM Prompt Engineering Guide](https://www.ibm.com/think/prompt-engineering) - Industry best practices

---

**Last Updated:** 2026-02-02
