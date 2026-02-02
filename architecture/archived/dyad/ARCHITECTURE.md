# Dyad Architecture

## System Overview

Dyad uses a **three-tier Electron architecture**:

```
┌─────────────────────────────────────────────────────────────┐
│                 Renderer Process (React 19)                  │
│  ├── Chat Interface (ChatInput - 33KB component)            │
│  ├── Code Editor (Monaco)                                   │
│  └── Live Preview Panel                                     │
└──────────────────────────┬──────────────────────────────────┘
                           │ IPC (secured via preload whitelist)
┌──────────────────────────▼──────────────────────────────────┐
│                  Main Process (Node.js)                      │
│  ├── 50+ IPC Handlers                                       │
│  ├── LLM Integration (Vercel AI SDK)                        │
│  ├── Git Operations                                         │
│  └── File System Operations                                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│              SQLite Database (Drizzle ORM)                   │
│  ├── Apps, Chats, Messages                                  │
│  ├── MCP Server Configs                                     │
│  └── LLM Provider Settings                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
src/
├── main/                    # Electron main process
├── pages/                   # Route pages (chat, app-details, settings, hub)
├── components/              # 78+ React components
│   ├── chat/               # Message, input, panels
│   ├── home/               # App management
│   ├── settings/           # Configuration UI
│   └── ui/                 # Radix UI primitives
├── client_logic/           # Business logic hooks
├── hooks/                  # Custom React hooks
├── atoms/                  # Jotai state atoms
├── contexts/               # React contexts
├── db/                     # Database schema (Drizzle ORM)
├── ipc/                    # IPC handlers + contracts
│   ├── handlers/           # 50+ handler files
│   ├── contracts/          # IPC message types
│   └── processors/         # Message processing logic
├── lib/                    # Utilities
├── prompts/                # System prompts (6 files, ~24KB main prompt)
├── styles/                 # Tailwind CSS
└── utils/                  # General utilities
```

---

## LLM Integration

### Request Pipeline

```
User Input
    ↓
Chat Interface
    ↓
Message + Context Packaging
  ├── User message
  ├── Codebase (full or smart-filtered)
  ├── System Prompt (24KB)
  └── Chat history
    ↓
LLM API Call (Vercel AI SDK)
    ↓
Streaming Response Parser (DyadMarkdownParser)
    ↓
XML Tag Processing
  ├── <dyad-write> → File creation/modification
  ├── <dyad-delete> → File deletion
  ├── <dyad-rename> → File renaming
  ├── <dyad-command> → UI commands
  ├── <dyad-read> → File reading
  ├── <dyad-mcp-tool-call> → MCP tool invocation
  └── <dyad-think> → Extended reasoning display
    ↓
IPC Handler Execution
    ↓
Response to User
```

### XML Tags Over Native Tool Calling

Dyad chose XML syntax instead of native function calling because:

1. **Parallel tool calls** inconsistently supported across models
2. **Code in JSON** degrades code quality (escaping, formatting issues)
3. **XML is unambiguous** for code blocks
4. **Simpler cost model** than complex agentic workflows

**Example Output:**
```xml
I'll create the component for you.

<dyad-write path="src/components/Button.tsx">
import React from 'react';

interface ButtonProps {
  label: string;
  onClick: () => void;
}

export const Button: React.FC<ButtonProps> = ({ label, onClick }) => {
  return (
    <button
      className="px-4 py-2 bg-blue-500 text-white rounded"
      onClick={onClick}
    >
      {label}
    </button>
  );
};
</dyad-write>

<dyad-command name="rebuild" />
```

---

## Operating Modes

| Mode | Description | Code Output |
|------|-------------|-------------|
| **Build** | Full code generation (default) | Yes - uses all XML tags |
| **Ask** | Conceptual explanations only | No - "MUST NOT WRITE CODE" |
| **Agent** | Information gathering phase | No - determines needs first |
| **Local-Agent** | Agentic loop with tools | Yes - native tool calling |

### Mode Selection Logic

```
User selects mode in UI
    ↓
System prompt adjusted:
  - Build: Full XML tag permissions
  - Ask: All <dyad-*> tags forbidden
  - Agent: Research-only phase
  - Local-Agent: Enable native tool loop
    ↓
LLM receives mode-appropriate instructions
```

---

## Context Management

### Default: Full Codebase

By default, Dyad sends the entire project codebase to the LLM:
- All source files concatenated
- File paths as headers
- Enables LLM to understand full context

### Smart Filtering (Optional)

Uses a smaller/faster model to pre-filter relevant files:

```
User prompt
    ↓
Small model identifies relevant files
    ↓
Only relevant files sent to main LLM
    ↓
Reduces token usage for large projects
```

---

## Tech Stack

### Frontend
- React 19 + TypeScript
- TanStack Router (navigation)
- React Query (server state)
- Jotai (client state atoms)
- Tailwind CSS
- Radix UI (accessible components)
- Monaco Editor (code editing)

### Backend
- Electron (desktop shell)
- Node.js (main process)
- SQLite + Drizzle ORM
- Vercel AI SDK (multi-provider LLM)

### LLM Providers Supported
- OpenAI
- Anthropic
- Google (Gemini)
- Vertex AI
- Azure OpenAI
- X.AI (Grok)
- AWS Bedrock
- Ollama (local)
- LM Studio (local)
- OpenRouter

---

## Security Model

### IPC Channel Whitelisting

```typescript
// Preload script validates all IPC channels
const VALID_INVOKE_CHANNELS = [
  'app:create',
  'app:delete',
  'file:write',
  'llm:chat',
  // ... exhaustive list
];

const VALID_RECEIVE_CHANNELS = [
  'chat:stream',
  'file:changed',
  // ... exhaustive list
];

// Only whitelisted channels can communicate
contextBridge.exposeInMainWorld('api', {
  invoke: (channel, ...args) => {
    if (VALID_INVOKE_CHANNELS.includes(channel)) {
      return ipcRenderer.invoke(channel, ...args);
    }
    throw new Error(`Invalid channel: ${channel}`);
  }
});
```

### MCP Tool Consent System

```
Tool Request
    ↓
Check mcpToolConsents table
    ↓
├── "always" → Execute immediately
├── "denied" → Block execution
└── "ask" → Prompt user for permission
    ↓
Execute or reject based on consent
```

---

## Database Schema (Key Tables)

```sql
-- Projects/Apps
apps: id, name, path, created_at, updated_at

-- Conversations
chats: id, app_id, title, created_at

-- Messages in conversations
messages: id, chat_id, role, content, ai_sdk_data, created_at

-- MCP Server configurations
mcp_servers: id, name, command, args, env_vars, transport

-- Tool permission tracking
mcp_tool_consents: id, server_id, tool_name, consent_level
```

---

## Key Design Patterns

### 1. Query Key Factory
```typescript
// Type-safe cache invalidation
queryKeys.apps.all              // All apps
queryKeys.apps.detail({appId})  // Specific app
queryKeys.chats.byApp({appId})  // Chats for app
```

### 2. Streaming Response Processing
```typescript
// Parse markdown + XML in real-time
for await (const chunk of stream) {
  parser.feed(chunk);
  // XML tags trigger immediate actions
  // Markdown rendered progressively
}
```

### 3. Deep Link Protocol
```
dyad:// protocol handles:
├── OAuth callbacks (Supabase, Neon)
├── Pro subscription activation
├── MCP server config import (base64 JSON)
└── Prompt data import (base64 JSON)
```
