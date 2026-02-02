# Phase 4: Coordinator

**Status:** SPECIFICATION
**Version:** 2.2
**Created:** 2026-01-04
**Updated:** 2026-01-06
**Layer:** MIND role (Qwen3-Coder-30B-AWQ @ temp=0.5)

---

## 1. Overview

The Coordinator manages the MCP tool registry and executes tool requests from the Planner. It is a **thin execution layer** - the intelligence lives in the Orchestrator (which manages the overall flow) and in the individual MCP tools themselves (which have their own internal loops and LLM roles).

**Core Question:** "Which tools are available and how do I execute them?"

```
┌─────────────────────────────────────────────────────────────────┐
│                     PHASE 4: COORDINATOR                         │
│                     Tool Registry & Executor                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐                                            │
│  │   ticket.md      │ ◄── Tool requests from Planner             │
│  │   (from Phase 3) │                                            │
│  └────────┬─────────┘                                            │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │  Tool Registry   │ ◄── Available MCP tools                    │
│  │  - Chat tools    │                                            │
│  │  - Code tools    │                                            │
│  └────────┬─────────┘                                            │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │  Execute Tools   │ ◄── Call MCP servers                       │
│  │                  │     (tools have own internal logic)        │
│  └────────┬─────────┘                                            │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │  Return Results  │ ──► context.md §4 + toolresults.md         │
│  └──────────────────┘                                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Key Principle:** Each MCP tool (like `internet.research`) has its own knowledge loop and LLM roles internally. The Coordinator doesn't manage that complexity - it just calls the tool and receives results.

---

## 2. Input/Output Specification

### 2.1 Inputs

| Input | Source | Description |
|-------|--------|-------------|
| context.md (§0-§3) | Prior phases | Query, reflection, gathered context, task plan |
| ticket.md | Phase 3 (Planner) | Structured tool requests |

### 2.2 Outputs

| Output | Destination | Description |
|--------|-------------|-------------|
| context.md §4 | Phase 5 (Synthesis) | Tool execution summary with claims |
| toolresults.md | Phase 5 (Synthesis) | Detailed results from each tool call |

---

## 3. Tool Registry

### 3.1 Chat Mode Tools

Available for conversational queries:

| Tool | MCP Server | Description |
|------|------------|-------------|
| `internet.research` | internet-research-mcp | Web search and content extraction (has internal research loop) |
| `memory.search` | memory-mcp | Search persistent memory |
| `memory.save` | memory-mcp | Save information to memory |
| `memory.retrieve` | memory-mcp | Retrieve specific memory entry |
| `file.read` | filesystem-mcp | Read file contents (read-only) |
| `file.glob` | filesystem-mcp | Find files by pattern (read-only) |
| `file.grep` | filesystem-mcp | Search file contents (read-only) |

### 3.2 Code Mode Tools

Additional tools when Planner routes to code mode:

| Tool | MCP Server | Description |
|------|------------|-------------|
| `file.write` | filesystem-mcp | Write content to file |
| `file.edit` | filesystem-mcp | Edit existing file |
| `file.create` | filesystem-mcp | Create new file |
| `file.delete` | filesystem-mcp | Delete file |
| `git.add` | git-mcp | Stage files |
| `git.commit` | git-mcp | Create commit |
| `git.push` | git-mcp | Push to remote |
| `git.pull` | git-mcp | Pull from remote |
| `bash.execute` | shell-mcp | Execute shell command |
| `test.run` | testing-mcp | Run test suite |

### 3.3 Tool Registration

Tools are registered at startup from MCP server discovery. Each MCP server exposes its available tools:

| MCP Server | Tools Exposed |
|------------|---------------|
| internet-research-mcp | internet.research |
| memory-mcp | memory.search, memory.save, memory.retrieve |
| filesystem-mcp | file.read, file.glob, file.grep, file.write, file.edit, file.create, file.delete |
| git-mcp | git.add, git.commit, git.push, git.pull |
| shell-mcp | bash.execute |
| testing-mcp | test.run |

---

## 4. Tool Execution Interface

### 4.1 Request Format (from ticket.md)

```markdown
## ticket.md

**Goal:** Find cheapest laptop with nvidia gpu
**Intent:** commerce
**Tools Required:**
- internet.research

**Tool Parameters:**
```json
{
  "tool": "internet.research",
  "args": {
    "query": "cheapest nvidia gpu laptop",
    "mode": "commerce",
    "original_query": "whats the cheapest laptop with nvidia gpu"
  }
}
```
```

### 4.2 Execution Flow

1. Parse tool requests from ticket.md
2. Validate tool exists in registry
3. Validate mode permissions (code tools only in code mode)
4. Call MCP server with parameters
5. Receive results from tool
6. Format results into §4 and toolresults.md

### 4.3 MCP Call Structure

Each MCP call contains:

| Field | Description | Example |
|-------|-------------|---------|
| server | Target MCP server name | `internet-research-mcp` |
| tool | Tool name to invoke | `internet.research` |
| args | Tool-specific parameters | `{query, mode, original_query}` |

**Note:** The MCP tool handles all internal complexity. For example, `internet.research` has its own multi-phase research loop with multiple LLM calls - the Coordinator just waits for the final result.

---

## 5. Section 4 Output Format

### 5.1 Structure

```markdown
## 4. Tool Execution

**Tools Requested:** internet.research
**Tools Executed:** 1
**Status:** SUCCESS

### internet.research

**Parameters:**
- query: "cheapest nvidia gpu laptop"
- mode: commerce

**Result:** SUCCESS

**Claims Extracted:**

| Claim | Confidence | Source | TTL |
|-------|------------|--------|-----|
| HP Victus 15 RTX 4050 @ $649 | 0.90 | walmart.com | 6h |
| Lenovo LOQ 15 @ $697 | 0.92 | bestbuy.com | 6h |
| Acer Nitro V @ $749 | 0.88 | newegg.com | 6h |
```

### 5.2 toolresults.md Format

```markdown
# Tool Results

**Turn:** 743

## internet.research

**Status:** SUCCESS
**Duration:** 45.2s

### Findings

| Product | Price | Vendor | URL | Specs |
|---------|-------|--------|-----|-------|
| HP Victus 15 | $649 | Walmart | https://... | RTX 4050, 16GB RAM |
| Lenovo LOQ 15 | $697 | Best Buy | https://... | RTX 4050, 16GB RAM |
| Acer Nitro V | $749 | Newegg | https://... | RTX 4050, 8GB RAM |

### Raw Response
```json
{
  "findings": [...],
  "sources_visited": 12,
  "research_phases": 3
}
```
```

---

## 6. Error Handling

### 6.1 Error Types

| Error | Source | Response |
|-------|--------|----------|
| Tool not found | Registry | HALT - invalid tool request |
| MCP server unavailable | Network | HALT - create intervention |
| Tool execution failed | MCP tool | HALT - log error, create intervention |
| Mode violation | Permissions | HALT - code tool in chat mode |

### 6.2 Fail-Fast Principle

All errors HALT execution and create intervention requests. There are no fallbacks or retries at the Coordinator level.

If a tool fails, that's either:
- A bug in the tool (fix the tool)
- An external dependency failure (report to user)

**Rationale:** The Coordinator is a thin layer. Error recovery logic belongs in the Orchestrator or in the MCP tools themselves.

---

## 7. Mode Enforcement

### 7.1 Chat Mode Restrictions

In chat mode, the Coordinator:
- Only allows tools from the chat mode registry
- Rejects any file write/edit/delete requests
- Rejects git and bash operations

### 7.2 Code Mode Permissions

In code mode, the Coordinator:
- Allows all chat mode tools
- Additionally allows file write operations
- Allows git operations
- Allows bash execution

Mode is determined by Planner (Phase 3) and passed in ticket.md.

---

## 8. Related Documents

- `architecture/main-system-patterns/phase3-planner.md` - Prior phase (creates ticket.md)
- `architecture/main-system-patterns/phase5-synthesis.md` - Next phase (consumes results)
- `architecture/mcp-tool-patterns/` - Individual MCP tool specifications
- `architecture/mcp-tool-patterns/internet-research-mcp/` - Research tool with internal loop

---

## 9. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-04 | Initial specification |
| 2.0 | 2026-01-05 | Simplified scope - Coordinator is tool registry/executor only |
| 2.1 | 2026-01-05 | Added Layer header, converted YAML/Python code to tables |

---

**Last Updated:** 2026-01-05
