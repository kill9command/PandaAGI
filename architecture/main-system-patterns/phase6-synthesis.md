# Phase 6: Synthesis

**Status:** SPECIFICATION
**Version:** 3.3
**Created:** 2026-01-04
**Updated:** 2026-02-04
**Layer:** VOICE role (Qwen3-Coder-30B-AWQ @ temp=0.7) - User Dialogue

**Related Concepts:** See §13 (Concept Alignment)

---

## Overview

The Synthesis phase transforms accumulated context into a user-facing response. This is the **only model the user "hears"** - it serves as the voice of Pandora, converting structured data into natural, engaging dialogue.

**Key Question:** "How do I present this to the user?"

```
┌──────────────────────────────────────────────────────────────┐
│                    PHASE 6: SYNTHESIS                         │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ INPUT: context.md (§0-§4) + toolresults.md              │ │
│  │        OR context.md (§0-§3) if no tools                │ │
│  └─────────────────────────────────────────────────────────┘ │
│                            ↓                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ PROCESS: Format response based on user purpose            │ │
│  │          - Use ONLY data from context.md                │ │
│  │          - Convert URLs to clickable links              │ │
│  │          - Include source citations                     │ │
│  └─────────────────────────────────────────────────────────┘ │
│                            ↓                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ OUTPUT: context.md §6 (preview) + response.md (full)    │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

**Why VOICE Role (MIND @ temp=0.7)?**
- Uses Qwen3-Coder-30B-AWQ model with higher temperature for natural output
- Same model as other phases, but temperature 0.7 for more conversational tone
- Follows formatting instructions precisely

---

## INPUTS

### 1. context.md (§0-§4 or §0-§3)

Synthesis reads only the sections it needs:
- **§0** User Query (`user_purpose`, `data_requirements`)
- **§1** Query Analysis Validation status (pass/fail context)
- **§2** Gathered Context (cached/memory evidence)
- **§3** Strategic Plan (rendered view of STRATEGIC_PLAN JSON, if present)
- **§4** Execution Progress (claims from workflow runs)

### 2. toolresults.md (if tools were executed)

**Location:** `turns/turn_{N}/toolresults.md`

**Purpose:** Contains complete, untruncated workflow execution results (including embedded tool runs) that may be summarized or truncated in §4 due to token limits.

**Rule:** toolresults.md is not embedded into context.md. The Orchestrator summarizes workflow results into §4 (Execution Progress) and stores full outputs in toolresults.md.

Synthesis loads toolresults.md to access:
- Full product details, prices, and URLs from research
- Complete file contents from file.read operations
- Detailed test results from test.run operations

**Why Synthesis needs both context.md AND toolresults.md:**
- §4 contains LLM-summarized claims (may lose detail due to token limits)
- toolresults.md contains exact prices, URLs, and product specs from workflow runs
- Synthesis uses toolresults.md for authoritative source URLs and pricing data

**Note:** toolresults.md is also used by Validation (Phase 7) for price cross-checking.

---

## TWO SYNTHESIS PATHS

| Path | Condition | Primary Data Source |
|------|-----------|---------------------|
| **With Tools** | Executor/Coordinator completed successfully | §4 claims (fresh data) |
| **Without Tools** | Planner routed directly to Synthesis | §2 gathered context (cached/memory) |

**Note:** If Coordinator fails (BLOCKED), the turn HALTs with an intervention request. Synthesis only runs on successful completion.

### Path 1: With Tools (Fresh Data)

When Executor/Coordinator executed tools successfully, §4 contains fresh claims. These take **precedence over §2** (cached context).

**Data Priority:**
1. §4 claims (authoritative - just gathered)
2. §2 gathered context (supplementary)
3. toolresults.md (full details)

### Path 2: Without Tools (Cached/Memory)

When Planner determined tools were unnecessary (recall queries, preference confirmations), Synthesis uses §2 gathered context directly.

**Example:** "What's my favorite <item>?"
- §2 contains: `**preference:** <preference_value>`
- No tool execution needed
- Synthesis responds directly from memory

---

## RESPONSE PATTERNS BY PURPOSE

Response formatting adapts based on `user_purpose` and `data_requirements` from §0 (plus Planner outputs):

| Signal | Response Pattern | Example Structure |
|--------|------------------|-------------------|
| Time-sensitive research + `needs_current_prices` | Structured list with prices, links, specs | Headers, bullet points, product cards |
| Informational question (no live data) | Prose explanation with citations | Paragraphs with inline sources |
| Memory recall signal | Direct answer from memory | Single sentence, confirmation |
| Greeting/acknowledgement | Conversational response, no elaboration | Natural dialogue, greeting, follow-up |
| Code signal + `mode=code` | Operation summary, file changes, test results | Code blocks, file lists, status |
| Navigation signal | List exact titles/items from source | Preserved original wording |

### live_search (Commerce) Template

```markdown
Great news! I found <N> options:

## Best Value
**<item_name> - <$price>** at <source_name>
- <key_detail>
- [View on <source_name>](<url>)

## Other Options
**<item_name> - <$price>** at <source_name>
- [View on <source_name>](<url>)

Would you like more details on any of these?
```

### live_search (Informational) Template

```markdown
<Topic> is <brief definition>. <Follow-up sentence with key context>.

**Key characteristics:**
- <Attribute 1>: <value>
- <Attribute 2>: <value>
- <Attribute 3>: <value>

Source: [<Source Name>](<url>)
```

### recall_memory Template

```markdown
Yes! Your favorite <item> is <preference_value>.
```

### execute_code Template

```markdown
I've made the requested changes to `<file>`:

## Changes Made
- Added `<change_1>`
- Updated `<change_2>`
- Added `<change_3>`

## Files Modified
- `<file_1>` - <summary>
- `<file_2>` - <summary>

All tests passing
```

---

## SPECIAL CASE: List Queries (navigate_to_site)

When query asks for "topics", "threads", "titles", "popular posts", the response must preserve exact titles:

| Do | Don't |
|----|-------|
| List exact titles as extracted | Summarize into categories |
| Preserve author names if present | Group by topic type |
| Keep original wording | Paraphrase titles |

---

## FORMATTING RULES

### URL Handling

**Rule:** ALWAYS convert URLs in claims to clickable markdown links.

**Claim in §4:**
```
<item> at <source_domain> for <$price> - <url>
```

**Output Format:**
```markdown
**<item> - <$price>**
- [View on <source_name>](<url>)
```

### Response Structure Elements

| Element | Requirement | Example |
|---------|-------------|---------|
| Opening | Engaging, natural | "Great news! I found..." |
| Structure | Use ## headers | `## Best Options` |
| Links | Clickable markdown | `[View on <source_name>](<url>)` |
| Details | Specific numbers | "$35.50", "8 weeks old" |
| Action | Tell user what to do | "Contact breeder at..." |

### Source Citation Format

Citations must be included when presenting factual claims:

**Inline Citation:**
```markdown
The average <item> costs between <$min>–<$max> ([<Source>](<url>)).
```

**Section Citation:**
```markdown
## Sources
- [<Source Name>](<url>)
- [<Source Name>](<url>)
```

---

## OUTPUTS

### 1. response.md (Primary Output)

**Location:** `turns/turn_{N}/response.md`

The full response delivered to the user.

### 2. context.md §6 (Appended)

A preview of the response with validation checklist:

```markdown
## 6. Synthesis

**Response Preview:**
Great news! I found <N> options:

## Best Value
**<item_name> - <$price>** at <source_name>
...

**Validation Checklist:**
- [x] Claims match evidence
- [x] User purpose satisfied
- [x] No hallucinations from prior context
- [x] Appropriate format
```

---

## TOKEN BUDGET

**Total Budget:** ~10,000 tokens

| Component | Tokens | Purpose |
|-----------|--------|---------|
| Prompt fragments | 1,318 | Base constraints, synthesis instructions |
| Input documents | 5,500 | context.md + toolresults.md |
| Output response | 2,900 | User-facing response |
| Buffer | 282 | Safety margin |
| **Total** | **10,000** | Per-synthesis budget |

---

## PROCESS FLOW

| Step | Action | Details |
|------|--------|---------|
| 1. Load Configuration | Load mode-specific settings | Chat vs Code mode determines output token limits |
| 2. Construct Prompt | Build synthesis prompt | Base constraints + mode/user_purpose + context.md + toolresults.md |
| 3. Call VOICE Role | Invoke Qwen3-Coder-30B-AWQ | Temperature: 0.7, Max tokens: 1000 (chat) or 3100 (code) |
| 4. Write Outputs | Save results | Write response.md, append §6 to context.md |

### Error Handling (Fail-Fast)

If the LLM call fails, the phase HALTs and creates an intervention request:

| Error | Action |
|-------|--------|
| LLM timeout | HALT - create intervention |
| Empty response | HALT - create intervention |
| Model unavailable | HALT - create intervention |

---

## KEY CONSTRAINTS

### 1. Capsule-Only Constraint

**Response must ONLY use data from context.md (no hallucinations)**

- Every factual claim must have evidence in §4 or §2
- Never invent prices, URLs, product names, or specifications
- If data is missing, acknowledge the gap rather than fabricate

### 1.1 Source Metadata Requirement

When presenting factual claims that should include sources, Synthesis MUST use `url` or `source_ref` from workflow results (toolresults.md or §4 claims). If a claim lacks source metadata, Synthesis must omit the claim or explicitly note the missing source.

### 2. URL Preservation

Claims contain URLs; synthesis MUST format as clickable links.

### 3. Purpose-Aware Formatting

Response structure adapts to `user_purpose` and `data_requirements` from §0 — time‑sensitive research gets product cards, informational searches get prose, and code tasks get file change summaries.

### 4. §4 vs §2 Priority

Fresh tool data (§4) takes precedence over cached context (§2). If §4 has newer prices, use §4 prices even if §2 has different data.

### 5. Validation Checklist

§6 includes self-validation markers that Phase 7 (Validation) will verify:
- Claims match evidence
- Intent satisfied
- No hallucinations from prior context
- Appropriate format

### 6. Authoritative Spelling/Terminology

Use spelling and terminology from authoritative sources (§4), not the user's potentially misspelled query.

---

## KEY ARCHITECTURAL POINTS

1. **Single Voice** - VOICE role (MIND @ temp=0.7) is the ONLY interface users interact with directly
2. **Document-Driven** - All data comes from context.md; no external lookups during synthesis
3. **Purpose-Adaptive** - Response format matches user purpose and action type automatically
4. **Link Preservation** - URLs from research become clickable markdown links
5. **Honest Reporting** - Partial/blocked results are acknowledged, not hidden
6. **Validation-Ready** - §6 includes checklist for Phase 7 verification

---

## 13. Concept Alignment

This section maps Phase 6's responsibilities to the cross-cutting concept documents.

| Concept | Document | Phase 6 Relevance |
|---------|----------|--------------------|
| **LLM Roles** | `LLM-ROLES/llm-roles-reference.md` | Uses the VOICE role (temp=0.7) — the highest temperature in the pipeline. This is the **only phase users interact with directly**. Higher temperature produces natural, conversational output. |
| **Confidence System** | `concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` | Uses claim confidence scores to determine language: high confidence (≥ 0.85) = state as fact, lower confidence = hedge with qualifiers ("appears to be", "approximately"). |
| **Document IO** | `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | Reads §0–§4 plus toolresults.md. Writes §6 (response preview + validation checklist) to context.md and the full response to response.md. |
| **Artifact System** | `concepts/artifacts_system/ARTIFACT_SYSTEM.md` | Can generate output artifacts (documents, files) as part of the response. Artifacts are referenced in the response with filenames and summaries. |
| **Recipe System** | `concepts/recipe_system/RECIPE_SYSTEM.md` | Executed as a VOICE recipe with ~10,000 token budget. Mode-specific output limits: chat (1,000 tokens) vs code (3,100 tokens). |
| **Execution System** | `concepts/system_loops/EXECUTION_SYSTEM.md` | Synthesis is reached either directly from Planner (fast path, §8 of Execution System) or after the Executor-Coordinator loop completes. On REVISE from Validation, the loop returns to Synthesis (max 2 attempts). |
| **Context Compression** | `concepts/system_loops/CONTEXT_COMPRESSION.md` | Synthesis relies on NERVES having compressed §4 if it exceeded budget. It also loads toolresults.md for full uncompressed details that may have been summarized in §4. |
| **Code Mode** | `concepts/code_mode/code-mode-architecture.md` | Mode affects output token limits and response format. Code mode responses include file change summaries, code blocks, and test results. Chat mode responses are conversational. |
| **Error Handling** | `concepts/error_and_improvement_system/ERROR_HANDLING.md` | Fail-fast on LLM errors (timeout, empty response, model unavailable). All failures HALT with intervention — no partial responses. |
| **Prompt Management** | `concepts/recipe_system/PROMPT_MANAGEMENT_SYSTEM.md` | The synthesis prompt carries the original query from §0 (context discipline) and formatting instructions based on `user_purpose` + `data_requirements`. |

---

## RELATED DOCUMENTATION

- `architecture/LLM-ROLES/llm-roles-reference.md` — Model assignments and role definitions
- `architecture/main-system-patterns/phase4-executor.md` — Phase 4 (tactical decisions)
- `architecture/main-system-patterns/phase5-coordinator.md` — Phase 5 (provides §4 and toolresults.md)
- `architecture/main-system-patterns/phase7-validation.md` — Phase 7 (validates response.md)
- `architecture/concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` — Quality thresholds for hedging language
- `architecture/concepts/artifacts_system/ARTIFACT_SYSTEM.md` — Artifact creation, manifest, storage

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | 2026-01-05 | Updated phase ordering (§1=Query Analysis Validation, §2=Context) |
| 2.1 | 2026-01-05 | Removed hardcoded claim filtering, aligned with fail-fast |
| 2.2 | 2026-01-05 | Removed prompt/recipe file references, converted process flow to table |
| 2.3 | 2026-01-24 | Added constraint #6 (Authoritative Spelling/Terminology) |
| 3.0 | 2026-01-24 | **Renumbered from Phase 5 to Phase 6** due to new Executor phase. Updated section numbers (§5→§6). Updated related document references. |
| 3.1 | 2026-02-03 | Added §13 Concept Alignment. Updated response patterns from old intent values to `user_purpose` terminology. Fixed stale references throughout. Fixed Related Documents paths. Removed stale Concept Implementation Touchpoints and Benchmark Gaps sections. |
| 3.2 | 2026-02-04 | Removed `action_needed` dependency; response patterns now derive from `user_purpose` + `data_requirements`. |
| 3.3 | 2026-02-04 | Abstracted examples into templates. Updated inputs to Phase 1.5 validation language. Clarified workflow-oriented toolresults usage. Added source metadata requirements. |

---

**Last Updated:** 2026-02-04
