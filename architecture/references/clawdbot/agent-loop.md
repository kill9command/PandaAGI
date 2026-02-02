# Clawdbot Agent Loop & Execution

## Overview

Clawdbot uses the Pi agent runtime from [pi-mono](https://github.com/badlogic/pi-mono). The agent loop is deliberately simple: process messages, execute tools, repeat until done.

---

## Core Loop

```
User Message
    |
    v
[Build System Prompt]
    |
    v
[Load Session Context]
    |
    v
[LLM Request] <-----------------------+
    |                                  |
    v                                  |
[Response with Tool Calls?]           |
    |                                  |
    +-- Yes --> [Execute Tools] -------+
    |
    +-- No --> [Return Response]
              |
              v
          [Persist to JSONL]
```

### Key Characteristics

- **No max iterations**: Loop continues until the model stops calling tools
- **Message queuing**: Can inject messages between turns via callbacks
- **Abort support**: Can stop mid-execution
- **Event streaming**: Emits events for UI reactivity

---

## Agent Session Lifecycle

```typescript
// Simplified from pi-mono
AgentSession.prompt(userMessage) {
  1. SessionManager.buildSessionContext()  // Load JSONL history
  2. Build system prompt (skills, SYSTEM.md, AGENTS.md)
  3. ExtensionRunner.emit("before_agent_start")
  4.
  5. while (true) {
       response = await llm.stream(messages)

       if (response.hasToolCalls) {
         for (toolCall of response.toolCalls) {
           ExtensionRunner.emit("tool_call")  // Extensions can block
           result = await tool.execute(toolCall)
           ExtensionRunner.emit("tool_result")  // Extensions can modify
           SessionManager.appendEntry(result)
         }
         continue  // Another turn
       }

       break  // No tool calls = done
     }

  6. SessionManager.appendEntry(response)
  7. ExtensionRunner.emit("agent_end")
}
```

---

## Tool Execution

### Core Tools

Pi uses a minimal 4-tool stack:

| Tool | Purpose |
|------|---------|
| `read` | Read file contents |
| `write` | Write/create files |
| `edit` | Modify existing files |
| `bash` | Execute shell commands |

### Tool Definition (TypeBox Schema)

```typescript
import { Type } from "@sinclair/typebox";

const tool = {
  name: "read",
  description: "Read file contents",
  parameters: Type.Object({
    path: Type.String({ description: "File path" }),
    startLine: Type.Optional(Type.Number()),
    endLine: Type.Optional(Type.Number()),
  }),
  async execute(toolCallId, params, onUpdate, ctx, signal) {
    const content = await fs.readFile(params.path, "utf-8");
    return {
      content: [{ type: "text", text: content }],
      details: { path: params.path, size: content.length },
    };
  },
};
```

### Split Tool Results

Tools return separate content for:
1. **LLM context**: What the model sees
2. **UI rendering**: What the user sees

```typescript
return {
  // For LLM
  content: [{ type: "text", text: "File written successfully" }],
  // For UI
  details: {
    path: "/path/to/file",
    diff: "... rendered diff ...",
  },
};
```

### Tool Streaming

Partial JSON parsing during tool call streaming enables real-time UI:

```typescript
tool.execute(..., onUpdate, ...) {
  // Stream progress
  onUpdate({ progress: 0.5, status: "Processing..." });

  // Return final result
  return { content: [...] };
}
```

---

## Thinking Modes

The agent supports configurable reasoning depth:

| Level | Description |
|-------|-------------|
| `off` | No extended thinking |
| `minimal` | Brief reasoning |
| `low` | Light thinking |
| `medium` | Moderate reasoning |
| `high` | Deep thinking (default) |
| `xhigh` | Maximum reasoning |

```json
{
  "agents": {
    "defaults": {
      "thinkingDefault": "high"
    }
  }
}
```

### Thinking Trace Handling

When switching between providers, thinking traces convert:

```
Anthropic thinking blocks -> <thinking>...</thinking> tags
```

---

## Message Queuing

### Steering (Interrupt)

Inject a message that interrupts current execution:

```json
{"type": "steer", "content": "Stop that and do this instead"}
```

Delivered after current tool execution completes.

### Follow-up (Queue)

Inject a message for after the agent completes:

```json
{"type": "follow_up", "content": "Also check this file"}
```

### Queue Modes

```json
{
  "agents": {
    "defaults": {
      "steeringMode": "all",        // or "one-at-a-time"
      "followUpMode": "all"
    }
  }
}
```

---

## Heartbeat System

A background process runs agent turns on a schedule.

### Configuration

```json
{
  "agents": {
    "defaults": {
      "heartbeat": {
        "enabled": true,
        "intervalMinutes": 30
      }
    }
  }
}
```

### Heartbeat Prompt

> "Read HEARTBEAT.md if it exists (workspace context). Follow it strictly. Do not infer or repeat old tasks from prior chats. If nothing needs attention, reply HEARTBEAT_OK."

### Usage

Create `~/clawd/HEARTBEAT.md`:

```markdown
## Scheduled Tasks

- [ ] Check email every 2 hours
- [ ] Monitor stock price at market open
- [ ] Run daily backup at midnight
```

**Note:** Heartbeats run full agent turns and consume tokens.

---

## Context Management

### Context Pruning

Remove old tool results before LLM requests:

```json
{
  "agents": {
    "defaults": {
      "contextPruning": "adaptive"  // off | adaptive | aggressive
    }
  }
}
```

| Mode | Behavior |
|------|----------|
| `off` | Keep all history |
| `adaptive` | Prune based on relevance |
| `aggressive` | Maximize available context |

### History Limits

```json
{
  "channels": {
    "telegram": {
      "historyLimit": 50,      // Last N messages for groups
      "dmHistoryLimit": 100    // Last N for DMs
    }
  }
}
```

---

## Model Management

### Model Selection

```json
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "anthropic/claude-opus-4-5",
        "fallbacks": [
          "anthropic/claude-sonnet-4",
          "openai/gpt-4o"
        ]
      }
    }
  }
}
```

### Runtime Switching

```bash
# Via command
/model anthropic/claude-sonnet-4

# Via API
{"type": "set_model", "model": "anthropic/claude-sonnet-4"}
```

### Supported Providers

- Anthropic (Claude)
- OpenAI (GPT-4, GPT-4o)
- Google (Gemini)
- Mistral
- xAI (Grok)
- Groq
- GitHub Copilot
- AWS Bedrock
- Google Vertex
- Local models (Ollama, vLLM, etc.)

---

## Comparison to Pandora

| Aspect | Clawdbot/Pi | Pandora |
|--------|-------------|---------|
| Loop type | Run until no tool calls | 8-phase pipeline |
| State | JSONL session file | context.md document |
| Tools | 4 core + skills | MCP tools |
| Thinking | Configurable levels | Role temperatures |
| Scheduling | Heartbeats + cron | None |
| Streaming | Tool + block streaming | SSE events |

### Lessons for Pandora

1. **Simpler loop**: Consider if 8 phases are always needed
2. **Heartbeats**: Add scheduled background research
3. **Message queuing**: Allow interrupts and follow-ups
4. **Thinking levels**: Map to temperature/sampling params
