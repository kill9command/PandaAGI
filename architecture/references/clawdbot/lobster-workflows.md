# Lobster Workflow Engine

## Overview

**Lobster** is a Clawdbot-native workflow shell: a typed, local-first "macro engine" that turns skills/tools into composable pipelines and safe automations.

**Repository:** https://github.com/clawdbot/lobster

---

## Why Lobster?

Complex workflows require many back-and-forth tool calls. Each call:
- Consumes tokens
- Introduces latency
- Risks LLM misinterpretation

Lobster solves this by:
1. **Deterministic execution**: Multi-step sequences run without LLM orchestration
2. **Typed data flow**: JSON objects/arrays, not text pipes
3. **Approval gates**: Human-in-the-loop for sensitive operations
4. **Resumability**: Pause and resume workflows

---

## Basic Pipeline

### Command Line Syntax

```bash
inbox list --json | inbox categorize --json | inbox apply --json
```

Commands emit JSON for inter-step communication.

### Clawdbot Integration

The agent invokes Lobster via tool call:

```json
{
  "tool": "lobster",
  "params": {
    "action": "run",
    "pipeline": "inbox list --json | inbox categorize --json"
  }
}
```

---

## Workflow Files (.lobster)

### Basic Structure

```yaml
name: inbox-triage
description: Categorize and process inbox items

args:
  tag:
    type: string
    default: "family"

steps:
  - id: collect
    command: inbox list --json

  - id: categorize
    command: inbox categorize --json
    stdin: $collect.stdout

  - id: approve
    command: inbox apply --approve
    stdin: $categorize.stdout
    approval: required
```

### Step Fields

| Field | Description |
|-------|-------------|
| `id` | Unique step identifier |
| `command` | Shell command to execute |
| `stdin` | Input from prior step (`$step.stdout` or `$step.json`) |
| `approval` | `required` to pause for human approval |
| `condition` | Expression to gate execution |
| `env` | Environment variables for this step |
| `timeout` | Step-specific timeout |

---

## Data References

### Reference Syntax

| Reference | Description |
|-----------|-------------|
| `$step.stdout` | Raw stdout from step |
| `$step.stderr` | Raw stderr from step |
| `$step.json` | Parsed JSON from stdout |
| `$step.exitCode` | Exit code |
| `$args.param` | Workflow argument |

### Example: Chained Steps

```yaml
steps:
  - id: fetch
    command: curl -s https://api.example.com/data

  - id: process
    command: jq '.items[] | select(.active)'
    stdin: $fetch.stdout

  - id: save
    command: tee processed.json
    stdin: $process.stdout
```

---

## Approval Gates

### Configuration

```yaml
steps:
  - id: dangerous-step
    command: rm -rf /tmp/cache/*
    approval: required
```

### Execution Flow

1. Workflow reaches approval step
2. Returns `needs_approval` status:

```json
{
  "status": "needs_approval",
  "requiresApproval": {
    "stepId": "dangerous-step",
    "prompt": "Delete cache files?",
    "resumeToken": "abc123..."
  }
}
```

3. User/agent approves or denies
4. Resume with token:

```json
{
  "action": "resume",
  "token": "abc123...",
  "approve": true
}
```

---

## Tool Parameters

### Run Action

```json
{
  "action": "run",
  "pipeline": "command | command",  // or file path
  "timeoutMs": 20000,               // default: 20000
  "maxStdoutBytes": 512000,         // default: 512000
  "argsJson": {"tag": "family"},    // workflow arguments
  "cwd": "/path/to/dir"             // working directory
}
```

### Resume Action

```json
{
  "action": "resume",
  "token": "<resumeToken>",
  "approve": true  // or false to deny
}
```

---

## Conditional Execution

### Basic Conditions

```yaml
steps:
  - id: check
    command: test -f config.json && echo "exists"

  - id: create
    command: echo '{}' > config.json
    condition: $check.exitCode != 0
```

### Approval-Based Conditions

```yaml
steps:
  - id: confirm
    command: echo "Proceeding..."
    approval: required

  - id: execute
    command: dangerous-operation
    condition: $confirm.approved == true
```

---

## LLM Integration

### llm-task Plugin

For workflows that need LLM judgment within deterministic pipelines:

```yaml
steps:
  - id: categorize
    command: llm-task
    params:
      prompt: "Categorize this email"
      input: $fetch.json
      schema:
        type: object
        properties:
          category: { type: string, enum: [work, personal, spam] }
          priority: { type: integer, minimum: 1, maximum: 5 }
```

The LLM call is structured and validated, not free-form.

---

## Real-World Example

### Second Brain Workflow

A "second brain" CLI + Lobster pipelines managing Markdown vaults:

```yaml
name: weekly-review
description: Weekly review of all notes

steps:
  - id: stats
    command: brain stats --json

  - id: inbox
    command: brain inbox list --json

  - id: stale
    command: brain scan stale --json

  - id: categorize
    command: llm-task
    params:
      prompt: "Categorize these inbox items"
      input: $inbox.json
    approval: required

  - id: apply
    command: brain inbox apply
    stdin: $categorize.json
    condition: $categorize.approved == true

  - id: consolidate
    command: brain memory consolidate
    stdin: $stale.json
    approval: required
```

### Key Pattern

- CLI emits JSON for deterministic operations
- Lobster chains commands into workflows
- Approval gates for human checkpoints
- LLM handles judgment when available
- Falls back to deterministic rules when not

---

## Safety Constraints

### Enforced Limits

| Constraint | Default |
|------------|---------|
| `timeoutMs` | 20000 |
| `maxStdoutBytes` | 512000 |
| Sandbox checks | Per-session |
| Allowlists | Per-command |

### Sandbox Behavior

> "The tool runs locally only, doesn't manage secrets, and disables when sandboxed."

In sandboxed sessions, Lobster is unavailable.

---

## Comparison to Pandora

| Aspect | Lobster | Pandora |
|--------|---------|---------|
| Workflow type | Typed pipelines | 8-phase pipeline |
| Data flow | JSON objects | context.md sections |
| Approval gates | Built-in | N/A |
| Resumability | Token-based | N/A |
| LLM integration | Optional plugin | Every phase |
| Scheduling | Via cron | N/A |

### Lessons for Pandora

1. **Deterministic workflows**: Not everything needs LLM orchestration
2. **Approval gates**: Human checkpoints for sensitive research
3. **Resumability**: Pause/resume long-running research
4. **JSON data flow**: Typed data between steps
5. **Token savings**: Complex multi-step tasks without per-step LLM calls

---

## Potential Pandora Implementation

### Research Workflow Example

```yaml
name: product-comparison
description: Compare products across vendors

args:
  query:
    type: string
    required: true
  budget:
    type: number
    default: 1000

steps:
  - id: plan
    command: panda research plan --query "$args.query" --json

  - id: approve-plan
    approval: required
    prompt: "Approve research plan?"

  - id: search
    command: panda research search
    stdin: $plan.json
    condition: $approve-plan.approved

  - id: extract
    command: panda research extract
    stdin: $search.json

  - id: compare
    command: panda research compare --budget $args.budget
    stdin: $extract.json

  - id: approve-report
    approval: required
    prompt: "Approve final report?"

  - id: save
    command: panda research save
    stdin: $compare.json
    condition: $approve-report.approved
```

This would:
1. Use LLM for planning (deterministic query generation)
2. Get user approval before searching
3. Run search/extract deterministically
4. Use LLM for comparison
5. Get final approval before saving
