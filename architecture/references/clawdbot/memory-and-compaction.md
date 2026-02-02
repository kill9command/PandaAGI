# Clawdbot Memory & Compaction

## Overview

Clawdbot uses a multi-layer memory system:
1. **Session memory**: JSONL conversation history
2. **Workspace files**: Persistent markdown files
3. **Memory flush**: Pre-compaction preservation

---

## Session Memory

### Storage Format

Sessions persist as JSONL files:

```
~/.clawdbot/agents/<agentId>/sessions/{{SessionId}}.jsonl
```

Each line is a message entry:

```json
{"role":"user","content":"Hello","timestamp":"2026-01-26T10:00:00Z"}
{"role":"assistant","content":"Hi there!","timestamp":"2026-01-26T10:00:01Z"}
{"role":"tool_call","name":"read","params":{"path":"file.txt"},"timestamp":"..."}
{"role":"tool_result","name":"read","content":"...","timestamp":"..."}
```

### Session Lifecycle

```
New message
    |
    v
Load session JSONL
    |
    v
Build context (system prompt + history)
    |
    v
LLM request
    |
    v
Append response to JSONL
    |
    v
[Check context limit]
    |
    +-- Over limit --> Compaction
    |
    +-- Under limit --> Done
```

---

## Workspace Files

### Memory Architecture

```
~/clawd/
├── AGENTS.md       # Operating instructions
├── SOUL.md         # Persona
├── TOOLS.md        # Tool usage
├── USER.md         # User preferences
├── memory.md       # Long-term notes
└── memory/
    ├── 2026-01-24.md
    ├── 2026-01-25.md
    └── 2026-01-26.md
```

### Memory Guidance (from AGENTS.md)

> "You wake up fresh each session. These files are your continuity:
> - Daily notes: `memory/YYYY-MM-DD.md`
> - Long-term notes: `memory.md` for durable facts, preferences, open loops
>
> Memory is limited. If you want to remember something, write it to a file.
> 'Mental notes' don't survive session restarts, but files do."

### Memory Rules

| Trigger | Action |
|---------|--------|
| User says "remember this" | Update `memory/YYYY-MM-DD.md` |
| Learn a lesson | Update `AGENTS.md`, `TOOLS.md`, or skill |
| User preference | Update `USER.md` |
| Important fact | Update `memory.md` |

---

## Compaction

### What is Compaction?

Compaction summarizes older conversation history into a compact entry while preserving recent messages. This prevents context overflow.

### Trigger Conditions

Auto-compaction activates when:
- Session approaches context window limit (~95% capacity)
- User manually triggers `/compact`

### Compaction Process

```
1. Detect approaching limit
2. Run memory flush (silent turn to save important notes)
3. Summarize old messages
4. Replace old messages with summary
5. Persist compacted session
6. Retry original request
```

### Memory Flush

Before compaction, Clawdbot runs a **silent memory turn**:

> "A background turn storing durable memories to disk before compacting."

This prevents losing important information during summarization.

### Configuration

```json
{
  "agents": {
    "defaults": {
      "compaction": {
        "memoryFlush": {
          "enabled": true,
          "softThreshold": 0.7,    // Trigger at 70% capacity
          "systemPrompt": "Save important notes before compaction..."
        }
      }
    }
  }
}
```

### Manual Compaction

```bash
/compact [optional instructions]
```

Example:
```bash
/compact Focus on decisions and open questions
```

---

## Context Pruning vs Compaction

| Aspect | Pruning | Compaction |
|--------|---------|------------|
| Scope | Tool results only | Full conversation |
| Persistence | In-memory only | Saved to JSONL |
| Trigger | Per-request | At context limit |
| Reversible | Yes | No |

### Context Pruning Modes

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
| `off` | Keep all tool results |
| `adaptive` | Prune based on relevance |
| `aggressive` | Minimize tool result context |

---

## Compaction Safeguards

### Adaptive Chunking

Large conversations are chunked for summarization to avoid overwhelming the summarizer.

### Progressive Fallback

If summarization fails:
1. Try smaller chunks
2. Try simpler summarization
3. Fall back to truncation

### Overflow Recovery

> "Auto-recover from compaction context overflow by resetting the session and retrying."

If compaction still exceeds limits, the system can reset and propagate overflow details.

---

## Best Practices

### Proactive Context Management

1. **Disable unused MCP servers** before compacting to maximize available context
2. **Manual compaction at strategic times** rather than waiting for auto-compact
3. **Compact earlier** (50-70%) to preserve more nuanced details

### Why Compact Earlier?

> "Triggering earlier, preserving more working memory, and giving the model room to think before hitting crisis mode means stopping earlier actually extends productive session length."

Compacting under pressure (95% capacity) leads to aggressive summarization and lost details.

### Session Reset

For complete resets:
```bash
/new     # Start fresh session
/reset   # Reset current session
```

---

## Status & Inspection

### Check Compaction Count

```bash
/status
```

Shows:
- Current context usage
- Compaction count
- Session duration

### Inspect Context

```bash
/context list    # Summary of each component's contribution
/context detail  # Detailed breakdown with truncation info
```

---

## Comparison to Pandora

| Aspect | Clawdbot | Pandora |
|--------|----------|---------|
| Session storage | JSONL files | Turn documents |
| Memory files | Workspace markdown | N/A |
| Compaction | Auto + manual | Context window management |
| Memory flush | Pre-compaction | N/A |
| Pruning | Tool results | N/A |

### Lessons for Pandora

1. **Pre-compaction memory flush**: Extract and save important notes before truncating context
2. **Workspace memory files**: Let users maintain persistent preferences and facts
3. **Manual compaction**: Give users control over when to summarize
4. **Compaction instructions**: Allow guiding what to preserve
5. **Context inspection**: Show users where tokens are going

---

## Potential Pandora Implementation

### Memory Architecture

```
panda_system_docs/users/default/
├── memory/
│   ├── preferences.md      # User preferences
│   ├── facts.md            # Known facts
│   ├── research_history.md # Past research summaries
│   └── daily/
│       ├── 2026-01-24.md
│       └── 2026-01-25.md
├── turns/                  # Existing turn documents
└── sessions/               # Session data
```

### Memory Flush Phase

Add a Phase 7.5 before truncation:

```python
async def memory_flush(context):
    """Extract important information before context truncation."""

    prompt = """
    Review the current session and extract:
    1. User preferences mentioned
    2. Important facts learned
    3. Research conclusions
    4. Open questions

    Save to appropriate memory files.
    """

    # LLM extracts and saves to memory files
    await save_to_memory(extract_memories(context, prompt))
```

### User Memory Commands

```
/memory show        # Show current memory files
/memory add <fact>  # Add a fact
/memory forget <id> # Remove a memory
/memory search <q>  # Search memories
```
