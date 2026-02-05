# Phase 5: Coordinator (Workflow Handler)

**Status:** SPECIFICATION
**Version:** 3.4
**Created:** 2026-01-04
**Updated:** 2026-02-05
**Layer:** REFLEX role (Qwen3-Coder-30B-AWQ @ temp=0.4)

**Related Concepts:** See §13 (Concept Alignment)

---

## 1. Overview

The Coordinator is the **Workflow Handler** that translates natural language commands from the Executor into workflow selections and executions. It answers the question: **"Which workflow best accomplishes this command?"**

Given:
- A natural language command from the Executor
- The current context (sections 0-4)

Do:
- Select the appropriate workflow from the catalog
- Determine workflow inputs
- Execute the workflow (tools are embedded in the workflow)
- Return structured results

**Key Design Principle:** The Coordinator owns the complete workflow catalog. The Executor does NOT know tool signatures - it issues natural language commands like "run research workflow for <topic>" and the Coordinator executes the workflow with embedded tools.

---

## 2. Position in Pipeline

```
Phase 4: Executor (Tactical) → Natural language command
    ↓
Phase 5: Coordinator (Workflow Handler) → Workflow selection + execution
    ↓
Results back to Executor (loop). Executor COMPLETE returns to Phase 3, which routes to Synthesis.
```

```
┌─────────────────────────────────────────────────────────────────┐
│                   COORDINATOR (WORKFLOW HANDLER)                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Input: Natural language command from Executor                   │
│  "Run research workflow for <item> under <budget>"               │
│                                                                  │
│                            ↓                                     │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ WORKFLOW SELECTION (LLM)                                    │ │
│  │                                                             │ │
│  │ Command: "Run research workflow for <item> under <budget>"  │ │
│  │                                                             │ │
│  │ → Match to: <workflow_name>                                 │ │
│  │ → Args: {query: "<item> under <budget>", mode: "<mode>"}    │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            ↓                                     │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ WORKFLOW EXECUTION                                          │ │
│  │                                                             │ │
│  │ Execute workflow (embedded tools)                           │ │
│  │ Receive results                                             │ │
│  │ Extract claims/evidence                                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            ↓                                     │
│                                                                  │
│  Output: COORDINATOR_RESULT                                      │
│  {command, workflow_selected, status, result, claims}            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Input/Output Specification

### 3.1 Input: Natural Language Command

The Coordinator receives a command from the Executor:

```json
{
  "command": "Run research workflow for <item> under <budget> with <constraint>",
  "context": {
    "goal_focus": "GOAL_1",
    "workflow_hint": "<workflow_name_or_intent>",
    "original_query": "<original_query>"
  }
  // Note: workflow_hint is optional and should not override user constraints.
}
```

### 3.2 Output: COORDINATOR_SELECTION (LLM Output)

The Coordinator LLM returns a **selection** (no execution):

```json
{
  "_type": "COORDINATOR_SELECTION",
  "command_received": "Run research workflow for <item> under <budget> with <constraint>",
  "workflow_selected": "<workflow_name>",
  "workflow_args": {
    "<arg>": "<value>",
    "original_query": "<original_query>"
  },
  "status": "selected | needs_more_info | blocked",
  "missing": ["<required_input_1>", "<required_input_2>"],
  "message": "Need <required_input_1> and <required_input_2> to continue",
  "error": "Workflow not allowed in current mode"
}
```

Only include `missing`, `message`, or `error` when status requires them.

### 3.3 Output: COORDINATOR_RESULT (System Output)

After selection, the system executes the workflow and returns:

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Run research workflow for <item> under <budget> with <constraint>",
  "workflow_selected": "<workflow_name>",
  "workflow_args": {
    "query": "<item> under <budget> with <constraint>",
    "mode": "<workflow_mode>",
    "original_query": "<original_query>"
  },
  "status": "success" | "error" | "blocked",
  "result": {
    "findings": [...],
    "sources_visited": <N>
  },
  "claims": [
    {
      "claim": "<item> @ <$price>",
      "confidence": 0.90,
      "source_name": "<source_name>",
      "source_domain": "<source_domain>",
      "url": "<url>",
      "title": "<title_or_null>",
      "source_type": "web",
      "source_ref": "<source_reference>"
    },
    {
      "claim": "<item> @ <$price>",
      "confidence": 0.92,
      "source_name": "<source_name>",
      "source_domain": "<source_domain>",
      "url": "<url>",
      "title": "<title_or_null>",
      "source_type": "web",
      "source_ref": "<source_reference>"
    }
  ],
  "tool_runs": [
    {"tool": "<tool_name>", "status": "success", "duration_ms": <N>}
  ],
  "error": null
}
```

---

## 4. Workflow Catalog (Dynamic)

The Coordinator owns the complete workflow catalog. This is the single source of truth for available workflows. Each workflow embeds the tools it needs.

### 4.1 Catalog Injection

The workflow catalog is injected into the Coordinator prompt at runtime. The Coordinator **must** select from this list and may not invent workflows.

### 4.2 Workflow Definition Contract (Abstract)

Each workflow defines:
- **Triggers** (pattern or intent)
- **Inputs** (required/optional)
- **Steps** (embedded tools)
- **Outputs** (fields returned)
- **Success criteria** (validation)

---

## 5. Command Translation Templates

### 5.1 Abstract Translation Patterns

| Command Pattern | Workflow Selection Pattern |
|----------------|----------------------------|
| "Run <category> workflow for <goal>" | Select a workflow whose triggers match `<category>` and `<goal>` |
| "Run <workflow_name> for <goal>" | Use `<workflow_name>` if present in catalog |
| "Run <workflow> with <constraints>" | Map `<constraints>` into `workflow_args` |

---

## 6. Workflow Selection Process

### 6.1 Selection Algorithm

1. **Parse command intent** - What is the user trying to accomplish?
2. **Match to workflow category** - Use catalog triggers.
3. **Select specific workflow** - Choose the best match.
4. **Extract parameters** - Populate `workflow_args`.
5. **Validate mode** - Is this workflow allowed in current mode (chat/code)?

### 6.2 Mode Enforcement

The catalog specifies what workflows are allowed by mode. If a workflow is not permitted in the current mode, return `blocked`.

If the Executor issues a command that requires a code-mode workflow while in chat mode:

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Run edit workflow for <file>",
  "status": "blocked",
  "error": "file_write_edit workflow requires code mode - currently in chat mode"
}
```

---

## 7. Result Format

### 7.1 Success Result

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Run research workflow for <item> under <budget> with <constraint>",
  "workflow_selected": "<workflow_name>",
  "workflow_args": {
    "query": "<item> under <budget> with <constraint>",
    "mode": "<workflow_mode>"
  },
  "status": "success",
  "result": {
    "findings": [
      {"item": "<item_name>", "price": "<price>", "url": "<url>"},
      {"item": "<item_name>", "price": "<price>", "url": "<url>"}
    ],
    "sources_visited": <N>,
    "duration_ms": <N>
  },
  "claims": [
    {
      "claim": "<item> @ <price>",
      "confidence": 0.90,
      "source_name": "<source_name>",
      "source_domain": "<source_domain>",
      "url": "<url>",
      "title": "<title_or_null>",
      "source_type": "web",
      "source_ref": "<source_reference>",
      "ttl": "<ttl>"
    },
    {
      "claim": "<item> @ <price>",
      "confidence": 0.92,
      "source_name": "<source_name>",
      "source_domain": "<source_domain>",
      "url": "<url>",
      "title": "<title_or_null>",
      "source_type": "web",
      "source_ref": "<source_reference>",
      "ttl": "<ttl>"
    }
  ],
  "tool_runs": [
    {"tool": "<tool_name>", "status": "success", "duration_ms": <N>}
  ]
}
```

### 7.2 Error Result

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Run file read workflow for <restricted_path>",
  "workflow_selected": "file_read",
  "workflow_args": {
    "file_path": "<restricted_path>"
  },
  "status": "error",
  "error": "Permission denied: cannot read protected file",
  "result": null,
  "claims": []
}
```

### 7.3 Blocked Result

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Run delete workflow for <path>",
  "status": "blocked",
  "error": "Destructive operation requires explicit user approval",
  "requires_approval": true
}
```

### 7.4 Needs‑More‑Info Result

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Run research workflow for <item> under <budget>",
  "status": "needs_more_info",
  "missing": ["<required_input_1>", "<required_input_2>"],
  "message": "Need <required_input_1> and <required_input_2> to continue"
}
```

### 7.5 Missing Source Metadata (Blocked)

If a workflow result lacks required source metadata (`url` or `source_ref`), the Coordinator must return a blocked result so the Executor can retry with a more precise command:

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Run research workflow for <item> under <budget>",
  "status": "blocked",
  "error": "Missing source metadata in workflow results",
  "requires_retry": true
}
```

---

## 8. Section 4 Contribution

The Coordinator's results are formatted and appended to section 4 by the Orchestrator:

```markdown
### Executor Iteration 3
**Action:** COMMAND
**Command:** "Run research workflow for <item> under <budget> with <constraint>"
**Coordinator:** <workflow_name> → "<query>"
**Result:** SUCCESS - <N> results found
**Claims:**
| Claim | Confidence | Source | TTL |
|-------|------------|--------|-----|
| <item> @ <price> | 0.90 | <source_domain> | <ttl> |
| <item> @ <price> | 0.92 | <source_domain> | <ttl> |
| <item> @ <price> | 0.88 | <source_domain> | <ttl> |
```

---

## 9. Token Budget

**Total Budget:** ~2,500 tokens per invocation

| Component | Tokens | Purpose |
|-----------|--------|---------|
| Workflow catalog | 800 | Workflow definitions and embedded tool signatures |
| Command + context | 500 | Input from Executor |
| Selection reasoning | 200 | Tool choice |
| Output | 1,000 | Result JSON |

**Note:** The Coordinator is invoked once per command, not once per turn. Token usage scales with number of Executor commands.

---

## 10. Error Handling

### 10.1 Workflow Errors

| Error Type | Coordinator Response |
|------------|---------------------|
| Workflow not found | status: "error", error: "Unknown workflow" |
| Invalid parameters | status: "error", error: "Missing required parameter: X" |
| Execution timeout | status: "error", error: "Workflow execution timed out" |
| Network failure | status: "error", error: "Network error: ..." |

### 10.2 Recovery

The Coordinator does NOT retry. It returns errors to the Executor, which decides whether to:
- Issue a different command
- Report BLOCKED
- Try alternative approach

---

## 11. Ambiguous Command Handling

When a command is ambiguous, the Coordinator asks for clarification:

**Command:** "Get the thing"

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Get the thing",
  "status": "needs_clarification",
  "clarification_options": [
    {"interpretation": "Read a file", "would_select": "file_read"},
    {"interpretation": "Search the web", "would_select": "research_web"},
    {"interpretation": "Retrieve from memory", "would_select": "memory_query"}
  ]
}
```

The Executor can then issue a more specific command.

---

## 12. Key Principles

1. **Single Responsibility:** Translate commands to workflows, nothing else
2. **Complete Catalog Ownership:** Only the Coordinator knows workflow definitions and embedded tools
3. **No Planning:** Don't decide what to do, just how to do it
4. **Transparent Translation:** Always report what workflow was selected and why
5. **Mode Enforcement:** Respect chat vs code mode restrictions
6. **Clean Results:** Return structured data with extracted claims
7. **Self‑Extension Execution:** CREATE_TOOL / CREATE_WORKFLOW actions are executed via workflows, sandbox, and tool registration (see SELF_BUILDING_SYSTEM)
8. **Constraint Enforcement:** Block workflow executions that violate constraints and report the violation to the Executor
9. **Plan State Updates:** Record constraint violations/satisfaction in plan state
10. **Workflow Registration:** Validate and register new workflow specs before activation

---

## 13. Concept Alignment

This section maps Phase 5's responsibilities to the cross-cutting concept documents.

| Concept | Document | Phase 5 Relevance |
|---------|----------|--------------------|
| **Tool System** | `concepts/tools_workflows_system/TOOL_SYSTEM.md` | The Coordinator OWNS the workflow catalog — this is its primary responsibility. It knows workflow definitions, embedded tool families, signatures, parameters, and MCP servers. Adding new tools typically requires updating workflow definitions. |
| **Execution System** | `concepts/system_loops/EXECUTION_SYSTEM.md` | Phase 5 is the **mechanical tier** of the 3-tier architecture. It operates in a loop with the Executor (Phase 4). The Coordinator translates commands to workflows — it does not plan or decide what to do. |
| **Code Mode** | `concepts/code_mode/code-mode-architecture.md` | Mode enforcement is a core Coordinator responsibility. Chat mode restricts to read-only, research, and memory workflows. Code mode adds write/edit, git, test, and shell workflows. Mode violations return structured error responses. |
| **Self-Building System** | `concepts/self_building_system/SELF_BUILDING_SYSTEM.md` | Executes CREATE_TOOL and CREATE_WORKFLOW actions from the Executor. Validates specs, runs in sandbox, and registers new tools/workflows. The Coordinator is where self-built tools enter the workflow catalog. |
| **Document IO** | `concepts/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md` | Workflow results are formatted and appended to §4 (Execution Progress) by the Orchestrator. Each result includes the command received, workflow selected, status, findings, and extracted claims. |
| **Recipe System** | `concepts/recipe_system/RECIPE_SYSTEM.md` | Executed as a REFLEX recipe, ~2,500 tokens per invocation. The workflow catalog is a significant portion of the prompt. Invoked once per command, not once per turn — token usage scales with Executor iterations. |
| **Confidence System** | `concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md` | Claims extracted from workflow results include confidence scores and TTL. These feed into Validation (Phase 7) quality checks and the Executor's ANALYZE decisions. |
| **Error Handling** | `concepts/error_and_improvement_system/ERROR_HANDLING.md` | The Coordinator does NOT retry on workflow errors. It returns structured error responses (workflow not found, invalid parameters, timeout, permission denied) to the Executor, which decides recovery strategy. |
| **LLM Roles** | `LLM-ROLES/llm-roles-reference.md` | Uses the REFLEX role (temp=0.4) for deterministic workflow selection. Workflow matching is a classification task — it maps natural language commands to workflow definitions, requiring consistency over creativity. |
| **Prompt Management** | `concepts/recipe_system/PROMPT_MANAGEMENT_SYSTEM.md` | The workflow catalog is embedded in the Coordinator's prompt. This is the only phase whose prompt scales with the number of registered workflows. The natural language command interface means Executor prompts stay small. |

---

## 14. Related Documents

- `architecture/main-system-patterns/phase4-executor.md` — Prior phase (issues commands)
- `architecture/main-system-patterns/phase6-synthesis.md` — After execution complete
- `architecture/concepts/system_loops/EXECUTION_SYSTEM.md` — Full loop specification
- `architecture/main-system-patterns/workflows/internet-research-mcp/` — Research workflow architecture
- `architecture/main-system-patterns/services/tool-execution-service.md` — Workflow/tool execution service

---

## 15. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 2.0 | 2026-01-05 | Simplified scope - Coordinator is tool registry/executor only |
| 2.1 | 2026-01-05 | Added Layer header, converted YAML/Python code to tables |
| 3.0 | 2026-01-24 | **Major revision:** Changed to Tool Expert role. Now receives natural language commands from Executor instead of structured tickets. Added command translation examples. Updated to Phase 5 (new Executor is Phase 4). |
| 3.1 | 2026-02-03 | Added §13 Concept Alignment. Fixed temperature (0.5 → 0.4 per LLM Roles reference). Fixed duplicate §2 numbering. Abstracted `plan_state.json` and `workflow.register` references. Fixed Related Documents paths. Removed stale Concept Implementation Touchpoints and Benchmark Gaps sections. |
| 3.2 | 2026-02-04 | Shifted from tool selection to workflow handling. Updated catalogs, templates, results, and mode enforcement to be workflow-centric. |
| 3.3 | 2026-02-04 | Added required source metadata fields in claims and explicit missing-source handling. |

---

**Last Updated:** 2026-02-04
