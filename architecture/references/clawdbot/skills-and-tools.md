# Clawdbot Skills & Tools System

## Overview

Clawdbot extends its capabilities through **skills** - markdown files with YAML frontmatter that teach the agent how to use tools. Skills are hot-reloadable and can be contributed by plugins.

---

## Skill Format

### Basic Structure

```markdown
---
name: my-skill
description: What the skill does
---

# My Skill

Instructions for using this skill...

## Examples

...
```

### SKILL.md Location

Skills load from three locations with precedence:

1. `<workspace>/skills/` (highest)
2. `~/.clawdbot/skills/`
3. Bundled skills (lowest)

```
~/clawd/skills/my-skill/SKILL.md     # Project-specific
~/.clawdbot/skills/my-skill/SKILL.md # User-global
/usr/lib/clawdbot/skills/...          # Bundled
```

---

## YAML Frontmatter

### Required Fields

```yaml
---
name: skill-name
description: What the skill does
---
```

### Optional Fields

```yaml
---
name: gmail
description: Read and send emails via Gmail API
homepage: https://docs.clawd.bot/skills/gmail
user-invocable: true                    # Expose as /gmail command (default: true)
disable-model-invocation: false         # Hide from model prompts (default: false)
command-dispatch: tool                  # Direct tool invocation bypassing model
command-tool: gmail                     # Tool name for dispatch
command-arg-mode: raw                   # Pass args directly (default: raw)
metadata: {"clawdbot":{"requires":{"bins":["gcloud"],"env":["GMAIL_TOKEN"]}}}
---
```

---

## Metadata Gating

Skills filter at load time via `metadata.clawdbot` (must be single-line JSON):

```yaml
metadata: {"clawdbot":{"requires":{"bins":["ffmpeg"],"env":["OPENAI_API_KEY"],"config":["features.experimental"],"os":["darwin","linux"]}}}
```

### Gate Types

| Gate | Description |
|------|-------------|
| `bins` | Required executables (all must exist) |
| `anyBins` | Required executables (any one) |
| `env` | Environment variables (config can substitute) |
| `config` | Boolean paths in clawdbot.json |
| `os` | Platform filter: `darwin`, `linux`, `win32` |
| `primaryEnv` | Associates env vars with API key config |
| `install` | Installer specs for macOS UI |

### Example: Complex Gating

```yaml
metadata: {"clawdbot":{"requires":{"bins":["docker"],"env":["DOCKER_HOST"],"os":["linux","darwin"]},"primaryEnv":"DOCKER_HOST","install":{"macos":{"cask":"docker"}}}}
```

---

## Command Dispatch

### Direct Tool Invocation

For skills that directly map to tools:

```yaml
---
name: calculator
description: Perform calculations
command-dispatch: tool
command-tool: eval_math
command-arg-mode: raw
---
```

When user types `/calculator 2+2`:
1. Skill intercepts the command
2. Directly invokes `eval_math` tool
3. Bypasses LLM interpretation

### Tool Parameters

```json
{
  "command": "2+2",           // Raw user args
  "commandName": "calculator", // Slash command used
  "skillName": "calculator"    // Skill name
}
```

---

## Skill Configuration

### Per-Skill Settings

```json
{
  "skills": {
    "entries": {
      "gmail": {
        "enabled": true,
        "apiKey": "SECRET_VALUE",
        "env": {
          "GMAIL_OAUTH_CLIENT": "...",
          "GMAIL_OAUTH_SECRET": "..."
        },
        "config": {
          "maxEmails": 100
        }
      }
    }
  }
}
```

### Disabling Bundled Skills

```json
{
  "skills": {
    "entries": {
      "unwanted-skill": {
        "enabled": false
      }
    }
  }
}
```

### Extra Skill Directories

```json
{
  "skills": {
    "load": {
      "extraDirs": [
        "/path/to/custom/skills"
      ]
    }
  }
}
```

---

## Plugin Skills

Plugins can ship their own skills:

### Plugin Structure

```
my-plugin/
├── clawdbot.plugin.json
├── skills/
│   └── my-skill/
│       └── SKILL.md
└── src/
    └── index.ts
```

### clawdbot.plugin.json

```json
{
  "name": "my-plugin",
  "skills": ["skills"]
}
```

### Gating Plugin Skills

```yaml
metadata: {"clawdbot":{"requires":{"config":["plugins.my-plugin.enabled"]}}}
```

---

## Token Cost

Skills consume prompt tokens:

```
Base overhead (≥1 skill): 195 characters
Per skill: 97 chars + len(name) + len(description) + len(location)
```

**Estimate:** ~24 tokens per skill (OpenAI tokenization)

### Example Calculation

```
50 skills × 24 tokens = 1,200 tokens
+ 195 base = 1,200 tokens total

(About 3% of a 32k context window)
```

---

## Skill Lifecycle

### Load Time

1. Scan skill directories
2. Parse YAML frontmatter
3. Apply metadata gates (bins, env, os, config)
4. Inject eligible skills' environment variables
5. Build system prompt with skill list

### Session Start

> "Changes to skills or config take effect on the next new session."

Eligibility is snapshotted at session start. Modifying skills mid-session has no effect until `/new` or session reset.

### Environment Injection

```typescript
// Before agent run
for (skill of eligibleSkills) {
  for ([key, value] of skill.env) {
    if (!process.env[key]) {
      process.env[key] = value;
    }
  }
}

// After agent run
// Restore original environment
```

---

## Built-in Tools

### Core Tools (Pi Agent)

| Tool | Description |
|------|-------------|
| `read` | Read file contents |
| `write` | Write/create files |
| `edit` | Modify existing files |
| `bash` | Execute shell commands |

### Clawdbot Extensions

| Tool | Description |
|------|-------------|
| `browser` | CDP-controlled Chrome/Chromium |
| `canvas` | Agent-driven visual workspace |
| `cron` | Schedule recurring tasks |
| `webhook` | HTTP event triggers |
| `sessions_*` | Multi-agent coordination |
| `node.*` | Camera, screen, location, notifications |
| `lobster` | Workflow automation |

---

## Custom Tool Registration

### Via Extensions

```typescript
import { Type } from "@sinclair/typebox";

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "greet",
    label: "Greet",
    description: "Greet someone by name",
    parameters: Type.Object({
      name: Type.String({ description: "Name to greet" }),
    }),
    async execute(toolCallId, params, onUpdate, ctx, signal) {
      return {
        content: [{ type: "text", text: `Hello, ${params.name}!` }],
        details: {},
      };
    },
  });
}
```

### Tool Definition Schema

```typescript
interface ToolDefinition {
  name: string;           // Unique identifier
  label: string;          // Display name
  description: string;    // For model context
  parameters: TSchema;    // TypeBox schema
  execute: (
    toolCallId: string,
    params: object,
    onUpdate: (update: object) => void,
    ctx: ExtensionContext,
    signal: AbortSignal
  ) => Promise<ToolResult>;
}

interface ToolResult {
  content: ContentBlock[];  // For LLM
  details?: object;         // For UI
}
```

---

## ClawdHub Registry

Public skills registry: https://clawdhub.com

### Installation

```bash
clawdbot skills install <skill-name>
clawdbot skills update <skill-name>
clawdbot skills remove <skill-name>
```

### Publishing

```bash
clawdbot skills publish ./my-skill
```

---

## Comparison to Pandora

| Aspect | Clawdbot Skills | Pandora MCP Tools |
|--------|-----------------|-------------------|
| Format | Markdown + YAML | Python classes |
| Location | Filesystem dirs | orchestrator/*.py |
| Hot reload | Yes | No (restart needed) |
| Gating | Bins, env, OS, config | None |
| Registry | ClawdHub | N/A |
| Token cost | ~24 per skill | Varies |

### Lessons for Pandora

1. **Hot reloading**: Watch for tool file changes
2. **Gating**: Skip tools based on availability
3. **Progressive disclosure**: Load tool docs on demand
4. **Token budgeting**: Calculate tool overhead upfront
5. **Plugin skills**: Allow users to add custom tools easily
