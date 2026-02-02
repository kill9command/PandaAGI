# Clawdbot System Prompt Design

## Philosophy

> "The system prompt is below 1000 tokens. Frontier models have been RL-trained extensively, so they inherently understand what a coding agent is without verbose guidance."

Clawdbot uses a **minimal system prompt** assembled dynamically per request, with customization via workspace files.

---

## Prompt Assembly

The system prompt is Clawdbot-owned (not a default template) and assembled with these sections:

```
1. Tooling          - Current tool list + short descriptions
2. Skills           - XML list of available skills (when present)
3. Self-Update      - How to run config.apply and update.run
4. Workspace        - Working directory path
5. Documentation    - Local docs path and when to read them
6. Workspace Files  - Bootstrap files injected below
7. Sandbox          - (conditional) Runtime isolation details
8. Date & Time      - User timezone (no dynamic clock for cache stability)
9. Reply Tags       - Provider-specific syntax options
10. Heartbeats      - Notification behavior settings
11. Runtime         - Host, OS, Node version, model, thinking level
12. Reasoning       - Current visibility level with toggle instructions

--- Project Context ---
[AGENTS.md content]
[SOUL.md content]
[TOOLS.md content]
[IDENTITY.md content]
[USER.md content]
[HEARTBEAT.md content]
```

---

## Workspace Files (Bootstrap)

Six markdown files are injected under "Project Context":

| File | Purpose | Max Size |
|------|---------|----------|
| `AGENTS.md` | Operating instructions, coding guidelines | 20,000 chars |
| `SOUL.md` | Persona, personality, tone | 20,000 chars |
| `TOOLS.md` | Custom tool usage instructions | 20,000 chars |
| `IDENTITY.md` | Agent name, avatar, metadata | 20,000 chars |
| `USER.md` | User preferences, personal info | 20,000 chars |
| `HEARTBEAT.md` | Scheduled task definitions | 20,000 chars |
| `BOOTSTRAP.md` | First-run setup (new workspaces) | 20,000 chars |

### Workspace Location

Default: `~/clawd/`

Configurable via:
```json
{
  "agents": {
    "defaults": {
      "workspace": "/path/to/workspace"
    }
  }
}
```

### Bootstrap Size Control

```json
{
  "agents": {
    "defaults": {
      "bootstrapMaxChars": 20000
    }
  }
}
```

### Inspecting Context Usage

```bash
/context list    # Summary of each file's contribution
/context detail  # Detailed breakdown with truncation info
```

---

## AGENTS.md Template

The default AGENTS.md teaches the agent about memory management:

```markdown
# Operating Instructions

You wake up fresh each session. These files are your continuity:

- Daily notes: `memory/YYYY-MM-DD.md` (create memory/ if needed)
- Long-term notes: `memory.md` for durable facts, preferences, open loops

## Memory Rules

Memory is limited. If you want to remember something, write it to a file.
"Mental notes" don't survive session restarts, but files do.

When someone says "remember this":
  -> Update `memory/YYYY-MM-DD.md` or relevant file

When you learn a lesson:
  -> Update AGENTS.md, TOOLS.md, or the relevant skill

## Coding Guidelines

- Keep files under ~700 LOC
- Extract helpers rather than creating "V2" copies
- Add comments for non-obvious logic
- Prefer Bun for TypeScript execution
```

---

## SOUL.md Template

Defines persona and tone:

```markdown
# Clawd

You are Clawd, a friendly space lobster AI assistant.

## Personality

- Helpful and direct
- Slightly irreverent humor
- Use the lobster emoji sparingly

## Communication Style

- Concise responses
- Code over explanation when appropriate
- Ask clarifying questions when ambiguous
```

---

## Skills Rendering

When skills are available, they appear as compact XML:

```xml
<available_skills>
  <skill>
    <n>gmail</n>
    <description>Read and send emails via Gmail</description>
    <location>~/.clawdbot/skills/gmail/SKILL.md</location>
  </skill>
  <skill>
    <n>spotify</n>
    <description>Control Spotify playback</description>
    <location>~/.clawdbot/skills/spotify/SKILL.md</location>
  </skill>
</available_skills>
```

The agent uses `read` to access skill documentation on-demand rather than including all instructions upfront. This is **progressive disclosure** - skills only consume tokens when needed.

### Token Cost Formula

```
Base overhead (when ≥1 skill): 195 characters
Per skill: 97 chars + len(name) + len(description) + len(location)
≈ 24 tokens per skill (OpenAI tokenization)
```

---

## Prompt Modes

Three rendering levels for different contexts:

| Mode | Use Case | Includes |
|------|----------|----------|
| **Full** | Main sessions | All sections |
| **Minimal** | Sub-agents | Omits Skills, Self-Update, Reply Tags, Heartbeats |
| **None** | Bare mode | Identity line only |

---

## Time Handling

The system prompt includes timezone but not the current time (for cache stability):

```
Current timezone: America/Los_Angeles (PST)
```

The agent can call tools to get the exact time when needed.

---

## Response Prefix Templates

Customize response prefixes with dynamic variables:

```json
{
  "messages": {
    "responsePrefix": "[{model}] "
  }
}
```

Variables:
- `{model}` - Model name
- `{provider}` - Provider name
- `{thinkingLevel}` - Current thinking level
- `{identity.name}` - Agent name from IDENTITY.md

---

## Comparison to Pandora

| Aspect | Clawdbot | Pandora |
|--------|----------|---------|
| Prompt size | <1000 tokens base | Variable per phase |
| Customization | Workspace files | Prompt files in apps/prompts/ |
| Tool docs | Progressive (read on demand) | Included in context |
| Persona | SOUL.md | System prompts per role |
| Memory guidance | AGENTS.md | Not formalized |

### Lessons for Pandora

1. **Smaller base prompts**: Frontier models need less hand-holding
2. **Workspace files**: User-editable personality and preferences
3. **Progressive disclosure**: Load tool docs on demand, not upfront
4. **Memory instructions**: Explicit guidance on what to persist
5. **Cache stability**: Avoid dynamic content that breaks caching

---

## Example: Minimal System Prompt

A reconstructed minimal prompt:

```
You are a coding assistant with access to these tools:
- read: Read file contents
- write: Write/create files
- edit: Modify existing files
- bash: Execute shell commands

Workspace: ~/clawd
Documentation: ~/.clawdbot/docs (read when needed)

<available_skills>
  <skill><n>gmail</n><description>Email access</description><location>...</location></skill>
</available_skills>

To use a skill, read its SKILL.md file first.

Timezone: America/Los_Angeles

---

[Contents of AGENTS.md]

---

[Contents of SOUL.md]
```
