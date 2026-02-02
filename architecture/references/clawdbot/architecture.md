# Clawdbot System Architecture

## Overview

Clawdbot follows a **Gateway-centric architecture** where a single long-lived daemon serves as the control plane for all messaging surfaces, tool executions, and client connections.

```
Messaging channels (WhatsApp/Telegram/Discord/iMessage/Signal/Slack)
        |
        v
    Gateway (ws://127.0.0.1:18789)
        |
        +-- Pi agent (RPC mode)
        +-- CLI (clawdbot ...)
        +-- WebChat UI
        +-- macOS/iOS/Android nodes
        +-- Canvas HTTP server (port 18793)
```

---

## Gateway Control Plane

The Gateway is the heart of the system:

| Responsibility | Description |
|---------------|-------------|
| Session management | Per-sender, per-channel, or shared sessions |
| Channel routing | Route messages from 12+ platforms to agents |
| Tool execution | Invoke tools with streaming support |
| Device pairing | Connect macOS/iOS/Android nodes |
| Webhooks & cron | Background automation triggers |
| Event streaming | WebSocket events for all client types |

### Network Configuration

```bash
# Default: localhost only
clawdbot gateway --port 18789

# Tailnet access (private network)
clawdbot gateway --bind tailnet --token <TOKEN>

# SSH tunnel for remote access
clawdbot gateway --ssh-tunnel user@host
```

### Wire Protocol

- **Transport:** WebSocket text frames
- **Format:** JSON payloads, one per line
- **Pattern:** Request-response with server-push events

```json
// Request
{"type": "prompt", "id": "abc123", "content": "Hello", "sessionKey": "main"}

// Response
{"type": "response", "command": "prompt", "success": true, "data": {...}}

// Server-push event
{"type": "event", "event": "tool_execution_start", "data": {...}}
```

---

## Multi-Channel Support

### Native Integrations (12+)

| Platform | Library | Notes |
|----------|---------|-------|
| WhatsApp | Baileys | Web session ownership |
| Telegram | grammY | Bot API |
| Discord | discord.js | Bot token |
| Slack | Bolt | App manifest |
| Signal | signal-cli | Linked device |
| iMessage | AppleScript | macOS only |
| Google Chat | Google APIs | Workspace app |
| Microsoft Teams | Bot Framework | Azure registration |
| Matrix | matrix-js-sdk | Homeserver |
| WebChat | Built-in | Browser interface |

### Extension Channels
BlueBubbles, Zalo, Zalo Personal

### DM Policies

```json
{
  "channels": {
    "telegram": {
      "dmPolicy": "pairing"  // or "open"
    }
  }
}
```

- **pairing** (default): Unknown senders get a pairing code; must be approved
- **open**: Process all messages (requires explicit allowlisting)

---

## Session Model

Sessions isolate conversation context and execution scope.

### Session Types

| Type | Scope | Tool Access |
|------|-------|-------------|
| **main** | Direct personal chats | Full access |
| **group** | Per-group/channel | Configurable sandbox |
| **thread** | Per-thread in groups | Inherits group settings |

### Session Lifecycle

```
session.scope: "per-sender" | "per-channel-peer" | "per-peer"
session.reset.mode: "daily" | "idle"
session.reset.atHour: 0-23
```

### Activation Modes

- **mention** (default for groups): Respond only when @mentioned
- **always**: Respond to all messages

```bash
# Toggle in chat
/activation always
/activation mention
```

### Session Storage

Sessions persist as JSONL files:
```
~/.clawdbot/agents/<agentId>/sessions/{{SessionId}}.jsonl
```

---

## Agent Runtime (Pi Agent)

Clawdbot uses the Pi agent from [pi-mono](https://github.com/badlogic/pi-mono) in RPC mode.

### Features

| Feature | Description |
|---------|-------------|
| Tool streaming | Real-time execution feedback |
| Block streaming | Incremental response chunks |
| Model selection | Support for multiple providers |
| Session awareness | Context management per session |
| Extended thinking | Configurable reasoning depth |

### RPC Communication

```json
// Send prompt
{"type": "prompt", "content": "Hello", "sessionKey": "main"}

// Queue interruption
{"type": "steer", "content": "Stop and do this instead"}

// Queue follow-up
{"type": "follow_up", "content": "Also check this"}

// Abort
{"type": "abort"}
```

### Event Stream

The agent emits events during execution:
- `agent_start` / `agent_end`
- `turn_start` / `turn_end`
- `message_start` / `message_update` / `message_end`
- `tool_execution_start` / `tool_execution_update` / `tool_execution_end`
- `auto_compaction_start` / `auto_compaction_end`

---

## Security Model

### Default Posture

> "Inbound DMs are treated as untrusted input."

### Layers of Protection

1. **Pairing Policy**: Unknown senders must be explicitly approved
2. **Session Sandboxing**: Non-main sessions can run in Docker
3. **Tool Allowlists**: Elevated commands require explicit permission
4. **TCC Integration**: macOS tools respect system permissions

### Sandbox Configuration

```json
{
  "agents": {
    "defaults": {
      "sandbox": {
        "mode": "non-main",  // off | non-main | all
        "scope": "session",   // session | agent | shared
        "docker": {
          "image": "clawdbot/sandbox:latest"
        }
      }
    }
  }
}
```

### Sandbox Allowlist (non-main sessions)

```
Allowed: bash, process, read, write, edit, sessions_*
Denied: browser, canvas, nodes, cron, discord, gateway
```

### Elevated Access

```json
{
  "tools": {
    "elevated": {
      "allowFrom": {
        "telegram": ["+1234567890"]
      }
    }
  }
}
```

---

## Device Nodes

macOS/iOS/Android devices can pair as remote execution nodes.

### Node Capabilities

| Capability | Description |
|-----------|-------------|
| Camera | Snap photos/videos |
| Screen | Recording/screenshots |
| Location | GPS coordinates |
| Notifications | Push alerts |
| Canvas | Visual workspace |

### Pairing Protocol

```bash
# On gateway host
clawdbot node pair

# On device
# Enter pairing code in app
```

### Execution Model

- Device-local actions execute on the node
- File/bash operations run on the gateway host
- `node.invoke` RPC for remote tool calls

---

## Deployment Patterns

### 1. Local-Only

Gateway + CLI on single machine. All tools execute locally.

```bash
clawdbot onboard --install-daemon
clawdbot gateway --port 18789
```

### 2. Remote Gateway + Local Nodes

- Gateway on Linux server (Docker/Nix/npm)
- macOS/iOS/Android devices pair as nodes
- Access via Tailscale Serve/Funnel

```bash
# On server
clawdbot gateway --bind tailnet

# On macOS
clawdbot node connect <gateway-url>
```

### 3. SSH Tunneling

Alternative to Tailscale for remote access.

```bash
clawdbot gateway --ssh-tunnel user@host:port
```

---

## Comparison to Pandora

| Aspect | Clawdbot | Pandora |
|--------|----------|---------|
| Control plane | WebSocket Gateway | FastAPI Gateway |
| Protocol | JSON-RPC over WS | REST + SSE |
| Session storage | JSONL files | Turn documents |
| Sandboxing | Docker per-session | None (server-side) |
| Multi-channel | 12+ platforms | Web only |
| Device nodes | macOS/iOS/Android | N/A |

### Lessons for Pandora

1. **Abstract the input layer**: Pandora could support Telegram/Discord with a thin adapter
2. **Session isolation**: Consider Docker sandboxing for research tools
3. **Event streaming**: Pandora's SSE could be expanded to a full event protocol
