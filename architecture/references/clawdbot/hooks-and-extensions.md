# Clawdbot Hooks & Extensions System

## Overview

Extensions are TypeScript modules that enhance Clawdbot by:
- Subscribing to lifecycle events
- Registering custom tools
- Adding slash commands
- Intercepting and modifying behavior

---

## Extension Locations

Extensions auto-discover from:

1. `~/.pi/agent/extensions/` (global)
2. `.pi/extensions/` (project-local)

Use `/reload` to hot-reload after modifications.

---

## Extension Styles

### Single File

```
~/.pi/agent/extensions/my-extension.ts
```

```typescript
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.on("agent_start", async (event, ctx) => {
    console.log("Agent started!");
  });
}
```

### Directory with Index

```
~/.pi/agent/extensions/my-extension/
├── index.ts
├── tools.ts
└── utils.ts
```

### Package with Dependencies

```
~/.pi/agent/extensions/my-extension/
├── package.json
├── node_modules/
└── src/index.ts
```

Run `npm install` in the extension directory.

---

## Event Lifecycle

```
session_start
    |
    v
input (can intercept/transform user message)
    |
    v
before_agent_start (inject messages, modify prompt)
    |
    v
agent_start
    |
    +---> turn_start
    |         |
    |         v
    |     context (context building)
    |         |
    |         v
    |     tool_call (can block)
    |         |
    |         v
    |     tool_result (can modify)
    |         |
    |         v
    |     turn_end
    |         |
    +----<----+  (loop if more tool calls)
    |
    v
agent_end
    |
    v
session_before_switch / session_switch (on /new)
session_before_fork / session_fork (on branching)
session_before_compact / session_compact (on compaction)
    |
    v
session_shutdown (on exit)
```

---

## Key Events

### session_start

First load of the session.

```typescript
pi.on("session_start", async (_event, ctx) => {
  ctx.ui.notify(`Session: ${ctx.sessionManager.getSessionFile()}`, "info");
});
```

### input

Intercept user messages before processing.

```typescript
pi.on("input", async (event, ctx) => {
  // Block sensitive content
  if (event.content.includes("secret")) {
    return { block: true, reason: "Contains sensitive data" };
  }

  // Transform content
  event.content = event.content.replace(/password/gi, "[REDACTED]");
});
```

### before_agent_start

Modify context before the agent runs.

```typescript
pi.on("before_agent_start", async (event, ctx) => {
  // Inject additional context
  event.messages.push({
    role: "user",
    content: "Remember: Be concise today."
  });
});
```

### tool_call

Intercept tool calls (can block execution).

```typescript
pi.on("tool_call", async (event, ctx) => {
  // Dangerous command protection
  if (event.toolName === "bash" && event.input.command?.includes("rm -rf")) {
    const ok = await ctx.ui.confirm(
      "Dangerous Command",
      "Allow rm -rf?"
    );
    if (!ok) {
      return { block: true, reason: "Blocked by user" };
    }
  }

  // Path protection
  if (event.toolName === "write" && event.input.path?.includes(".env")) {
    return { block: true, reason: "Cannot write to .env files" };
  }
});
```

### tool_result

Modify tool results before returning to the model.

```typescript
pi.on("tool_result", async (event, ctx) => {
  // Redact secrets from output
  if (typeof event.result.content === "string") {
    event.result.content = event.result.content.replace(
      /API_KEY=\w+/g,
      "API_KEY=[REDACTED]"
    );
  }
});
```

### tool_result_persist

Synchronously transform results before session persistence.

```typescript
pi.on("tool_result_persist", (event, ctx) => {
  // Log all tool results
  console.log(`Tool ${event.toolName}: ${JSON.stringify(event.result)}`);
});
```

### agent_end

After the agent completes.

```typescript
pi.on("agent_end", async (event, ctx) => {
  // Auto-save after each interaction
  await ctx.exec("git", ["add", "-A"]);
  await ctx.exec("git", ["commit", "-m", "Auto-save"]);
});
```

---

## ExtensionContext (ctx)

Available in all event handlers:

### UI Methods

```typescript
// Dialogs
const result = await ctx.ui.input("Prompt", "Enter value:");
const ok = await ctx.ui.confirm("Title", "Confirm?");
const choice = await ctx.ui.select("Pick one", ["A", "B", "C"]);
ctx.ui.notify("Message", "info" | "warning" | "error" | "success");

// Status & Widgets
ctx.ui.setStatus("processing", "Working...");
ctx.ui.setWidget("stats", ["Line 1", "Line 2"]);

// Custom components
await ctx.ui.custom(component, { initialState, timeout });
```

### Session Management

```typescript
ctx.sessionManager.getSessionFile()    // Current session path
await ctx.newSession(options?)         // Create new session
await ctx.fork(entryId)                // Branch from entry
await ctx.navigateTree(targetId)       // Tree navigation
await ctx.compact()                    // Trigger compaction
```

### Execution

```typescript
await ctx.exec("command", ["args"])    // Run shell command
ctx.abort()                            // Stop current operation
await ctx.waitForIdle()                // Wait for agent to finish
```

### State

```typescript
ctx.cwd                                // Current working directory
ctx.hasUI                              // UI availability
ctx.isIdle()                           // Check if agent is idle
ctx.hasPendingMessages()               // Check message queue
ctx.getContextUsage()                  // Token usage info
```

### Model

```typescript
ctx.model                              // Current model
ctx.modelRegistry                      // All available models
```

---

## ExtensionAPI Methods

### Events

```typescript
pi.on("event_name", handler)           // Subscribe to event
pi.events                              // Direct event emitter
```

### Tools & Commands

```typescript
pi.registerTool(definition)            // Add LLM-callable tool
pi.registerCommand("name", options)    // Add /command
pi.registerShortcut("ctrl+k", options) // Add keyboard binding
pi.registerFlag("name", options)       // Add feature flag
```

### Messaging

```typescript
pi.sendMessage(message, options?)      // Send agent message
pi.sendUserMessage(content, options?)  // Send as user
pi.appendEntry(customType, data?)      // Persist custom entry
```

### Tools Management

```typescript
pi.getActiveTools()                    // Currently enabled tools
pi.getAllTools()                       // All available tools
pi.setActiveTools(names)               // Enable specific tools
```

### Model

```typescript
pi.setModel(model)                     // Switch model
pi.getThinkingLevel()                  // Current thinking level
pi.setThinkingLevel(level)             // Adjust thinking
```

### Session

```typescript
pi.setSessionName(name)                // Name the session
pi.getSessionName()                    // Get session name
pi.setLabel(entryId, label)            // Label an entry
```

---

## Custom Tools via Extensions

```typescript
import { Type } from "@sinclair/typebox";

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "weather",
    label: "Get Weather",
    description: "Get current weather for a location",
    parameters: Type.Object({
      location: Type.String({ description: "City name" }),
    }),
    async execute(toolCallId, params, onUpdate, ctx, signal) {
      onUpdate({ status: "Fetching weather..." });

      const response = await fetch(
        `https://api.weather.com/v1/${params.location}`
      );
      const data = await response.json();

      return {
        content: [{
          type: "text",
          text: `Weather in ${params.location}: ${data.temp}°F`
        }],
        details: { raw: data },
      };
    },
  });
}
```

---

## Custom Commands

```typescript
pi.registerCommand("stats", {
  description: "Show session statistics",
  async execute(args, ctx) {
    const usage = ctx.getContextUsage();
    ctx.ui.notify(
      `Tokens: ${usage.total} / Messages: ${usage.messages}`,
      "info"
    );
  },
});
```

Usage: `/stats`

---

## Hooks System

Hooks are a simpler alternative to extensions, defined via HOOK.md files.

### HOOK.md Format

```markdown
---
metadata: {"clawdbot":{"emoji":"🎯","events":["command:new"],"requires":{"bins":["node"]}}}
---

# My Hook

Handler for command events.
```

### Hook Events

| Event | Trigger |
|-------|---------|
| `command:new` | `/new` command |
| `command:reset` | `/reset` command |
| `command:stop` | `/stop` command |
| `command` | Any command |
| `agent:bootstrap` | Before workspace file injection |
| `gateway:startup` | After channels initialize |
| `tool_result_persist` | Before transcript persistence |

### Hook Handler

```typescript
const handler: HookHandler = async (event) => {
  if (event.type !== "command" || event.action !== "new") return;

  console.log(`New session: ${event.sessionKey}`);
  event.messages.push("Starting fresh session!");
};

export default handler;
```

### Hook Configuration

```json
{
  "hooks": {
    "internal": {
      "enabled": true,
      "entries": {
        "session-memory": { "enabled": true },
        "my-hook": {
          "enabled": true,
          "env": { "CUSTOM_VAR": "value" }
        }
      }
    }
  }
}
```

---

## Practical Use Cases

### 1. Permission Gates

```typescript
pi.on("tool_call", async (event, ctx) => {
  const dangerousCommands = ["rm -rf", "sudo", "chmod 777"];

  if (event.toolName === "bash") {
    for (const cmd of dangerousCommands) {
      if (event.input.command?.includes(cmd)) {
        const ok = await ctx.ui.confirm(
          "Dangerous Command",
          `Allow: ${event.input.command}?`
        );
        if (!ok) return { block: true, reason: "User declined" };
      }
    }
  }
});
```

### 2. Git Checkpointing

```typescript
pi.on("turn_start", async (event, ctx) => {
  await ctx.exec("git", ["stash", "push", "-m", "auto-checkpoint"]);
});

pi.on("turn_end", async (event, ctx) => {
  await ctx.exec("git", ["stash", "pop"]);
});
```

### 3. Path Protection

```typescript
const protectedPaths = [".env", "credentials.json", "node_modules/"];

pi.on("tool_call", async (event, ctx) => {
  if (["write", "edit"].includes(event.toolName)) {
    for (const path of protectedPaths) {
      if (event.input.path?.includes(path)) {
        return { block: true, reason: `Protected path: ${path}` };
      }
    }
  }
});
```

### 4. Custom Compaction

```typescript
pi.on("session_before_compact", async (event, ctx) => {
  // Save important context before compaction
  const summary = await summarizeSession(ctx.sessionManager);
  await fs.writeFile("memory/session-summary.md", summary);
});
```

---

## Comparison to Pandora

| Aspect | Clawdbot Extensions | Pandora |
|--------|---------------------|---------|
| Language | TypeScript | Python |
| Hot reload | Yes (`/reload`) | No |
| Event hooks | Full lifecycle | Phase transitions |
| Tool blocking | Yes | N/A |
| UI integration | Dialogs, widgets | SSE events |
| Persistence | `appendEntry()` | Turn documents |

### Lessons for Pandora

1. **Lifecycle hooks**: Add before/after events for each phase
2. **Tool interception**: Allow blocking dangerous operations
3. **Hot reload**: Watch extension files for changes
4. **UI dialogs**: Add confirmation prompts for risky actions
5. **Custom entries**: Allow extensions to persist custom data
