# Prompt & Compression System

**Version:** 5.0
**Updated:** 2026-02-03

---

## 1. Core Idea

Panda is a **prompt-managed system**. The LLM is responsible for all complex decisions — routing, planning, tool selection, extraction, validation. Code supplies structured evidence, executes actions, and verifies outcomes.

- **LLM decides:** routing, planning, selection, navigation, extraction intent, validation judgment
- **Code provides:** evidence packs, tool execution, logging, verification, persistence

Prompts are first-class assets. Code is a deterministic substrate.

---

## 2. Prompt Packs

Each LLM call receives a **prompt pack** — a structured bundle of everything the model needs:

| Component | Source |
|-----------|--------|
| Role prompt | Markdown files loaded by the recipe's `prompt_fragments` |
| IO schema | Output format and validation rules from the recipe |
| context.md sections | Specified sections from the working document |
| Linked documents | Research, tool results, prior turns as needed |
| Original user query | Always included — the LLM reads user priorities directly |
| Target role | REFLEX, NERVES, MIND, or VOICE — determines temperature |

**Rule:** The LLM always sees the original user query for priority interpretation. Sanitized search queries go to search engines. The LLM reads "cheapest" directly from §0.

---

## 3. LLM-Owned Decisions

These decisions must be handled by prompts, not code:

| Decision | Role | Why Not Code |
|----------|------|-------------|
| Reflection gate (PROCEED/CLARIFY) | REFLEX | Ambiguity is contextual |
| Strategic planning and goal decomposition | MIND | Requires understanding user intent |
| Tool selection and iteration control | MIND | Depends on accumulated results |
| Research strategy (sources, phases) | MIND | Requires domain judgment |
| Extraction validation (accept/reject) | MIND | Quality is subjective |
| Response synthesis | VOICE | Natural language generation |
| Quality validation | MIND | Holistic judgment across goals |
| Compression (what to preserve) | NERVES | Content importance is contextual |

**Principle:** Route to the lowest temperature capable of the task. REFLEX (0.3) for gates and classification. MIND (0.5) for reasoning. VOICE (0.7) for user-facing text. NERVES (0.1) for compression.

---

## 4. Quality Gates

Every recipe can define quality gates that its output must pass:

| Gate | Purpose |
|------|---------|
| **Schema validation** | Output must match the declared JSON Schema |
| **Confidence threshold** | LLM's stated confidence must exceed minimum |
| **Evidence requirement** | Claims must cite source documents |
| **Timeout** | Maximum execution time |

On validation failure: retry up to the recipe's `max_retries`, then create intervention and HALT. No silent fallbacks.

---

## 5. Smart Summarization

The document-based IO pattern causes context.md and supporting documents to grow through phases. Any document sent to an LLM could exceed the per-call token budget.

**The Smart Summarization layer automatically compresses documents to fit within budget.** No manual intervention needed.

### How It Works

Before every LLM call:
1. **Count tokens** — Measure the prompt pack against the recipe's budget
2. **If within budget** — Proceed normally (fast path, no overhead)
3. **If over budget** — NERVES (temperature 0.1) compresses the overflowing content, preserving critical information while reducing size

### Content-Type Strategies

Different content requires different compression approaches:

| Content Type | Strategy | Always Preserve |
|--------------|----------|-----------------|
| context.md | Section-aware | §0 (user query), most recent section |
| research.md | Evidence-focused | URLs, prices, key claims with sources |
| Page documents | Zone-focused | Structured extraction zones, product data |
| Tool results | Output-focused | Error messages, key data points |
| Prior turns | Summary | User intent, system response outcome |

### Trigger Hierarchy

Compression triggers at three levels, from targeted to aggressive:

| Level | Trigger | Action | Impact |
|-------|---------|--------|--------|
| **Section overflow** | One section exceeds its budget | Compress that section only | Minimal — targeted |
| **Document overflow** | Total context.md exceeds budget | Compress largest sections first | Moderate — may lose detail |
| **Call overflow** | Full prompt pack exceeds per-call limit | Aggressive compression, drop low-relevance content | Severe — last resort |

**Principle:** Always compress at the earliest possible level. Section overflow prevention avoids document overflow. Document overflow prevention avoids call overflow.

### Section 4 Enforcement

§4 (Tool Execution) grows during the Coordinator loop as tools execute. The system enforces the budget during writing, not just at compression time:

- Check §4 size before adding each tool result
- If approaching limit, compress existing content first
- Always keep the newest result in full (most relevant)
- Older results are summarized progressively

### What NERVES Preserves

When compressing, NERVES follows priority rules:
- **Never compress:** User query (§0), error messages, URLs
- **Compress last:** Prices, claims with sources, most recent section
- **Compress first:** Verbose descriptions, older conversation history, marketing language

---

## 6. Design Principles

1. **LLM-First Decisions** — All complex decision logic lives in prompts. Code never replaces LLM judgment with hand-tuned rules.
2. **Context Discipline** — Prompts always receive the original user query and relevant evidence. Don't pre-classify user priorities.
3. **Recipe-Driven** — Every LLM call goes through a recipe that defines token budgets and output schema. No ad-hoc invocations.
4. **Right-Sized Roles** — Each decision point is assigned to the lowest-temperature role that can reliably handle it.
5. **Transparent Compression** — Documents are automatically compressed when they exceed budget. No manual checks needed.
6. **Observable** — Every recipe execution is logged with recipe name, role, tokens, latency, and success status.

---

## 7. Related Documents

- Recipe system: `architecture/concepts/recipe_system/RECIPE_SYSTEM.md`
- Document IO: `architecture/concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md`
- Error handling: `architecture/concepts/error_and_improvement_system/ERROR_HANDLING.md`
- Observability: `architecture/concepts/DOCUMENT-IO-SYSTEM/OBSERVABILITY_SYSTEM.md`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-01 | Initial specification |
| 4.1 | 2026-01-27 | Consolidated prompt management, recipes, and compression |
| 5.0 | 2026-02-03 | Distilled to pure concept. Extracted recipe schema to RECIPE_SYSTEM.md. Removed all Python code, YAML examples, JSON logging, file paths, environment variables, and implementation checklist. Kept prompt philosophy, quality gates, and compression concepts. |

---

**Last Updated:** 2026-02-03
