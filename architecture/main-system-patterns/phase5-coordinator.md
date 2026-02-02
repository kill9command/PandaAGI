# Phase 5: Coordinator (Tool Expert)

**Status:** SPECIFICATION
**Version:** 3.0
**Created:** 2026-01-04
**Updated:** 2026-01-24
**Layer:** MIND role (Qwen3-Coder-30B-AWQ @ temp=0.4)

---

## 1. Overview

The Coordinator is the **Tool Expert** that translates natural language commands from the Executor into specific tool calls. It answers the question: **"Which tool best accomplishes this command?"**

Given:
- A natural language command from the Executor
- The current context (sections 0-4)

Do:
- Select the appropriate tool from the catalog
- Determine tool parameters
- Execute the tool
- Return structured results

**Key Design Principle:** The Coordinator owns the complete tool catalog. The Executor does NOT know tool signatures - it issues natural language commands like "search for laptops" and the Coordinator translates that to `internet.research(query="laptops", mode="commerce")`.

---

## 2. Position in Pipeline

```
Phase 4: Executor (Tactical) → Natural language command
    ↓
Phase 5: Coordinator (Tool Expert) → Tool selection + execution
    ↓
Results back to Executor (loop) or Phase 6: Synthesis
```

```
┌─────────────────────────────────────────────────────────────────┐
│                    COORDINATOR (TOOL EXPERT)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Input: Natural language command from Executor                   │
│  "Search for cheap laptops with good reviews"                    │
│                                                                  │
│                            ↓                                     │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ TOOL SELECTION (LLM)                                        │ │
│  │                                                             │ │
│  │ Command: "Search for cheap laptops with good reviews"       │ │
│  │                                                             │ │
│  │ → Match to: internet.research                               │ │
│  │ → Args: {query: "cheap laptops good reviews", mode: "commerce"} │
│  └────────────────────────────────────────────────────────────┘ │
│                            ↓                                     │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ TOOL EXECUTION                                              │ │
│  │                                                             │ │
│  │ Call MCP server with selected tool                          │ │
│  │ Receive results                                             │ │
│  │ Extract claims/evidence                                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            ↓                                     │
│                                                                  │
│  Output: COORDINATOR_RESULT                                      │
│  {command, tool_selected, status, result, claims}                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Input/Output Specification

### 2.1 Input: Natural Language Command

The Coordinator receives a command from the Executor:

```json
{
  "command": "Search for cheap laptops with good reviews",
  "context": {
    "goal_focus": "GOAL_1",
    "intent": "commerce",
    "original_query": "find me a cheap laptop"
  }
}
```

### 2.2 Output: COORDINATOR_RESULT

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Search for cheap laptops with good reviews",
  "tool_selected": "internet.research",
  "tool_args": {
    "query": "cheap laptops good reviews",
    "mode": "commerce",
    "original_query": "find me a cheap laptop"
  },
  "status": "success" | "error" | "blocked",
  "result": {
    "findings": [...],
    "sources_visited": 5
  },
  "claims": [
    {"claim": "HP Victus @ $649", "confidence": 0.90, "source": "walmart.com"},
    {"claim": "Lenovo LOQ @ $697", "confidence": 0.92, "source": "bestbuy.com"}
  ],
  "error": null
}
```

---

## 3. Tool Catalog

The Coordinator owns the complete tool catalog. This is the single source of truth for available tools.

### 3.1 Chat Mode Tools

| Tool | MCP Server | When to Select |
|------|------------|----------------|
| `internet.research` | internet-research-mcp | "search", "find", "look up", web queries |
| `memory.search` | memory-mcp | "recall", "what did I say", "my preferences" |
| `memory.save` | memory-mcp | "remember", "save", "store" |
| `memory.delete` | memory-mcp | "forget", "remove", "delete from memory" |
| `file.read` | filesystem-mcp | "read file", "show contents", "what's in" |
| `file.glob` | filesystem-mcp | "find files", "list files matching" |
| `file.grep` | filesystem-mcp | "search in files", "find text in" |

### 3.2 Code Mode Tools (Additional)

| Tool | MCP Server | When to Select |
|------|------------|----------------|
| `file.write` | filesystem-mcp | "create file", "write to" |
| `file.edit` | filesystem-mcp | "edit", "modify", "change", "update file" |
| `file.delete` | filesystem-mcp | "delete file", "remove file" |
| `repo.scope_discover` | code-mcp | "find related files", "discover structure" |
| `file.read_outline` | code-mcp | "show structure", "outline of" |
| `git.status` | git-mcp | "git status", "what changed" |
| `git.diff` | git-mcp | "show diff", "what's different" |
| `git.commit_safe` | git-mcp | "commit", "save changes to git" |
| `git.push` | git-mcp | "push", "upload changes" |
| `bash.execute` | shell-mcp | "run command", "execute" |
| `test.run` | testing-mcp | "run tests", "verify", "check tests" |
| `code.verify_suite` | code-mcp | "run test suite", "verify all tests" |

### 3.3 Tool Signatures

Each tool has a defined signature. The Coordinator knows these:

```yaml
internet.research:
  args:
    query: string (required) - search query
    mode: string (optional) - "commerce", "informational", "navigation"
    original_query: string (optional) - user's original query for context

memory.save:
  args:
    type: string - "preference", "fact", "instruction"
    content: string - what to remember

file.read:
  args:
    file_path: string - path to file
    offset: int (optional) - line to start from
    limit: int (optional) - max lines to read

file.edit:
  args:
    file_path: string - path to file
    old_string: string - text to find
    new_string: string - text to replace with
    replace_all: bool (optional) - replace all occurrences
```

---

## 4. Command Translation Examples

### 4.1 Research Commands

| Natural Language Command | Tool Selection |
|--------------------------|----------------|
| "Search for cheap laptops" | `internet.research(query="cheap laptops", mode="commerce")` |
| "Find information about hamster care" | `internet.research(query="hamster care guide", mode="informational")` |
| "Go to Best Buy and check laptop prices" | `internet.research(query="Best Buy laptop prices", mode="navigation")` |
| "Look up the latest RTX 4090 reviews" | `internet.research(query="RTX 4090 reviews 2024", mode="informational")` |

### 4.2 Memory Commands

| Natural Language Command | Tool Selection |
|--------------------------|----------------|
| "Remember that I prefer RTX GPUs" | `memory.save(type="preference", content="prefers RTX GPUs")` |
| "What's my favorite hamster breed?" | `memory.search(query="favorite hamster")` |
| "Forget that I like AMD" | `memory.delete(query="AMD preference")` |
| "Save that my budget is $1000" | `memory.save(type="fact", content="budget is $1000")` |

### 4.3 File Commands

| Natural Language Command | Tool Selection |
|--------------------------|----------------|
| "Read the auth.py file" | `file.read(file_path="src/auth.py")` |
| "Find Python files in the src folder" | `file.glob(pattern="src/**/*.py")` |
| "Search for TODO comments in the code" | `file.grep(pattern="TODO", glob="**/*.py")` |
| "Show the structure of the main module" | `file.read_outline(file_path="src/main.py")` |

### 4.4 Code Operations

| Natural Language Command | Tool Selection |
|--------------------------|----------------|
| "Add a new function to auth.py" | `file.edit(file_path="src/auth.py", ...)` |
| "Run the test suite" | `test.run(target="tests/")` or `code.verify_suite(target="tests/")` |
| "Commit the changes with message 'Fix login bug'" | `git.commit_safe(message="Fix login bug")` |
| "Show what files have changed" | `git.status()` |

---

## 5. Tool Selection Process

### 5.1 Selection Algorithm

1. **Parse command intent** - What is the user trying to accomplish?
2. **Match to tool category** - Research? Memory? File? Git?
3. **Select specific tool** - Which tool in that category?
4. **Extract parameters** - What values from the command?
5. **Validate mode** - Is this tool allowed in current mode (chat/code)?

### 5.2 Mode Enforcement

| Mode | Allowed Tools |
|------|---------------|
| Chat | internet.research, memory.*, file.read, file.glob, file.grep |
| Code | All chat tools + file.write, file.edit, file.delete, git.*, bash.*, test.*, code.* |

If the Executor issues a command that requires a code-mode tool while in chat mode:

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Edit the auth.py file",
  "status": "blocked",
  "error": "file.edit requires code mode - currently in chat mode"
}
```

---

## 6. Result Format

### 6.1 Success Result

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Search for cheap laptops with RTX GPU",
  "tool_selected": "internet.research",
  "tool_args": {
    "query": "cheap laptops RTX GPU",
    "mode": "commerce"
  },
  "status": "success",
  "result": {
    "findings": [
      {"product": "HP Victus 15", "price": "$649", "url": "https://..."},
      {"product": "Lenovo LOQ 15", "price": "$697", "url": "https://..."}
    ],
    "sources_visited": 8,
    "duration_ms": 12500
  },
  "claims": [
    {"claim": "HP Victus 15 @ $649", "confidence": 0.90, "source": "walmart.com", "ttl": "6h"},
    {"claim": "Lenovo LOQ 15 @ $697", "confidence": 0.92, "source": "bestbuy.com", "ttl": "6h"}
  ]
}
```

### 6.2 Error Result

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Read the secret config file",
  "tool_selected": "file.read",
  "tool_args": {
    "file_path": "/etc/secrets/config"
  },
  "status": "error",
  "error": "Permission denied: cannot read protected file",
  "result": null,
  "claims": []
}
```

### 6.3 Blocked Result

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Delete all test files",
  "status": "blocked",
  "error": "Destructive operation requires explicit user approval",
  "requires_approval": true
}
```

---

## 7. Section 4 Contribution

The Coordinator's results are formatted and appended to section 4 by the Orchestrator:

```markdown
### Executor Iteration 3
**Action:** COMMAND
**Command:** "Search for cheap laptops with RTX GPU"
**Coordinator:** internet.research → "cheap laptops RTX GPU"
**Result:** SUCCESS - 5 products found
**Claims:**
| Claim | Confidence | Source | TTL |
|-------|------------|--------|-----|
| HP Victus 15 @ $649 | 0.90 | walmart.com | 6h |
| Lenovo LOQ 15 @ $697 | 0.92 | bestbuy.com | 6h |
| Acer Nitro V @ $749 | 0.88 | newegg.com | 6h |
```

---

## 8. Token Budget

**Total Budget:** ~2,500 tokens per invocation

| Component | Tokens | Purpose |
|-----------|--------|---------|
| Tool catalog | 800 | All tool signatures |
| Command + context | 500 | Input from Executor |
| Selection reasoning | 200 | Tool choice |
| Output | 1,000 | Result JSON |

**Note:** The Coordinator is invoked once per command, not once per turn. Token usage scales with number of Executor commands.

---

## 9. Error Handling

### 9.1 Tool Errors

| Error Type | Coordinator Response |
|------------|---------------------|
| Tool not found | status: "error", error: "Unknown tool" |
| Invalid parameters | status: "error", error: "Missing required parameter: X" |
| Execution timeout | status: "error", error: "Tool execution timed out" |
| Network failure | status: "error", error: "Network error: ..." |

### 9.2 Recovery

The Coordinator does NOT retry. It returns errors to the Executor, which decides whether to:
- Issue a different command
- Report BLOCKED
- Try alternative approach

---

## 10. Ambiguous Command Handling

When a command is ambiguous, the Coordinator asks for clarification:

**Command:** "Get the thing"

```json
{
  "_type": "COORDINATOR_RESULT",
  "command_received": "Get the thing",
  "status": "needs_clarification",
  "clarification_options": [
    {"interpretation": "Read a file", "would_select": "file.read"},
    {"interpretation": "Search the web", "would_select": "internet.research"},
    {"interpretation": "Retrieve from memory", "would_select": "memory.search"}
  ]
}
```

The Executor can then issue a more specific command.

---

## 11. Key Principles

1. **Single Responsibility:** Translate commands to tools, nothing else
2. **Complete Catalog Ownership:** Only the Coordinator knows tool signatures
3. **No Planning:** Don't decide what to do, just how to do it
4. **Transparent Translation:** Always report what tool was selected and why
5. **Mode Enforcement:** Respect chat vs code mode restrictions
6. **Clean Results:** Return structured data with extracted claims

---

## 12. Related Documents

- `architecture/main-system-patterns/phase4-executor.md` - Prior phase (issues commands)
- `architecture/main-system-patterns/phase6-synthesis.md` - After execution complete
- `architecture/main-system-patterns/PLANNER_EXECUTOR_COORDINATOR_LOOP.md` - Full loop specification
- `architecture/mcp-tool-patterns/` - Individual tool specifications
- `architecture/mcp-tool-patterns/internet-research-mcp/` - Research tool details
- `architecture/services/orchestrator-service.md` - Tool execution service

---

## 13. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 2.0 | 2026-01-05 | Simplified scope - Coordinator is tool registry/executor only |
| 2.1 | 2026-01-05 | Added Layer header, converted YAML/Python code to tables |
| 3.0 | 2026-01-24 | **Major revision:** Changed to Tool Expert role. Now receives natural language commands from Executor instead of structured tickets. Added command translation examples. Updated to Phase 5 (new Executor is Phase 4). |

---

**Last Updated:** 2026-01-24
