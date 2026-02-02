# Ralph: Autonomous AI Agent Loop for Coding

> An automation framework that orchestrates repeated cycles of AI-assisted coding until all requirements are fulfilled.

**Source:** https://github.com/snarktank/ralph
**Based on:** Geoffrey Huntley's architectural pattern
**Saved:** 2026-01-23

---

## Overview

Ralph is an autonomous agent system that repeatedly runs AI coding tools until all project requirements are complete. Each iteration starts fresh, with memory persisted through git history, progress tracking, and a structured requirements file.

### Core Concept

The system works by:
1. Taking a PRD (Product Requirements Document) converted to JSON format
2. Running fresh AI instances in a loop
3. Having each iteration tackle one user story
4. Using quality checks (type checking, tests) as feedback loops
5. Committing completed work and updating progress
6. Continuing until all stories are marked complete

---

## Requirements

**Prerequisites:**
- Amp CLI or Claude Code (`npm install -g @anthropic-ai/claude-code`)
- `jq` command-line JSON processor
- Git-initialized project repository

---

## Installation

### Local Project Setup

Create a scripts directory, copy ralph.sh and your chosen prompt template, then make executable.

### Global Skill Installation

Place the prd and ralph skill directories in:
- `~/.config/amp/skills/` (Amp)
- `~/.claude/skills/` (Claude Code)

### Amp Configuration

Add this to `~/.config/amp/settings.json` to enable automatic context handoff:

```json
{
  "amp.experimental.autoHandoff": { "context": 90 }
}
```

---

## Workflow Process

### Phase 1 - Requirements Definition

Invoke the prd skill with a feature description. Answer clarifying questions to generate a detailed markdown PRD saved as `tasks/prd-[feature-name].md`.

### Phase 2 - Conversion

Use the ralph skill to transform the markdown PRD into `prd.json`, structuring user stories for autonomous execution with pass/fail status fields.

### Phase 3 - Execution

Launch the loop:

```bash
./scripts/ralph/ralph.sh [max_iterations]
```

With optional `--tool claude` flag for Claude Code instead of Amp.

---

## Loop Mechanics

Each iteration:

1. Creates/checks out feature branch from PRD configuration
2. Selects highest-priority incomplete story
3. Implements single story in fresh AI context
4. Executes quality checks (type validation, test suites)
5. Commits if checks pass
6. Updates story status to `passes: true`
7. Appends learnings to `progress.txt`
8. Repeats until all stories complete or max iterations reached

---

## Critical Design Principles

### Fresh Context Per Iteration

Each cycle spawns a completely new AI instance. Continuity depends solely on:
- Git commits
- `progress.txt` annotations
- `prd.json` status updates

NOT on conversation history.

### Task Granularity

Stories must fit within a single context window.

**Appropriate scope:**
- Adding database columns with migrations
- Creating UI components within existing pages
- Extending server-side logic
- Implementing filter controls

**Avoid monolithic features:**
- Complete dashboard builds
- Full authentication systems

### Documentation as Memory

AGENTS.md files serve as persistent knowledge. Ralph automatically updates them with:
- Discovered patterns
- Common pitfalls
- Architectural conventions

AI tools automatically reference these during subsequent iterations.

### Validation Feedback

The system requires functioning:
- Type-checking
- Unit tests
- Continuous integration

Broken code from one iteration cascades through subsequent cycles without proper safeguards.

### UI Verification

Frontend stories must include acceptance criteria mentioning dev-browser skill usage for manual verification of visual changes.

### Completion Signal

When all stories have `passes: true`, Ralph outputs `<promise>COMPLETE</promise>` and terminates.

---

## The Loop Script

```bash
#!/bin/bash
# Ralph Wiggum - Long-running AI agent loop
# Usage: ./ralph.sh [--tool amp|claude] [max_iterations]

set -e

# Parse arguments
TOOL="amp"  # Default to amp for backwards compatibility
MAX_ITERATIONS=10

while [[ $# -gt 0 ]]; do
  case $1 in
    --tool)
      TOOL="$2"
      shift 2
      ;;
    --tool=*)
      TOOL="${1#*=}"
      shift
      ;;
    *)
      # Assume it's max_iterations if it's a number
      if [[ "$1" =~ ^[0-9]+$ ]]; then
        MAX_ITERATIONS="$1"
      fi
      shift
      ;;
  esac
done

# Validate tool choice
if [[ "$TOOL" != "amp" && "$TOOL" != "claude" ]]; then
  echo "Error: Invalid tool '$TOOL'. Must be 'amp' or 'claude'."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRD_FILE="$SCRIPT_DIR/prd.json"
PROGRESS_FILE="$SCRIPT_DIR/progress.txt"
ARCHIVE_DIR="$SCRIPT_DIR/archive"
LAST_BRANCH_FILE="$SCRIPT_DIR/.last-branch"

# Archive previous run if branch changed
if [ -f "$PRD_FILE" ] && [ -f "$LAST_BRANCH_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  LAST_BRANCH=$(cat "$LAST_BRANCH_FILE" 2>/dev/null || echo "")

  if [ -n "$CURRENT_BRANCH" ] && [ -n "$LAST_BRANCH" ] && [ "$CURRENT_BRANCH" != "$LAST_BRANCH" ]; then
    # Archive the previous run
    DATE=$(date +%Y-%m-%d)
    FOLDER_NAME=$(echo "$LAST_BRANCH" | sed 's|^ralph/||')
    ARCHIVE_FOLDER="$ARCHIVE_DIR/$DATE-$FOLDER_NAME"

    echo "Archiving previous run: $LAST_BRANCH"
    mkdir -p "$ARCHIVE_FOLDER"
    [ -f "$PRD_FILE" ] && cp "$PRD_FILE" "$ARCHIVE_FOLDER/"
    [ -f "$PROGRESS_FILE" ] && cp "$PROGRESS_FILE" "$ARCHIVE_FOLDER/"
    echo "   Archived to: $ARCHIVE_FOLDER"

    # Reset progress file for new run
    echo "# Ralph Progress Log" > "$PROGRESS_FILE"
    echo "Started: $(date)" >> "$PROGRESS_FILE"
    echo "---" >> "$PROGRESS_FILE"
  fi
fi

# Track current branch
if [ -f "$PRD_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  if [ -n "$CURRENT_BRANCH" ]; then
    echo "$CURRENT_BRANCH" > "$LAST_BRANCH_FILE"
  fi
fi

# Initialize progress file if it doesn't exist
if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# Ralph Progress Log" > "$PROGRESS_FILE"
  echo "Started: $(date)" >> "$PROGRESS_FILE"
  echo "---" >> "$PROGRESS_FILE"
fi

echo "Starting Ralph - Tool: $TOOL - Max iterations: $MAX_ITERATIONS"

for i in $(seq 1 $MAX_ITERATIONS); do
  echo ""
  echo "==============================================================="
  echo "  Ralph Iteration $i of $MAX_ITERATIONS ($TOOL)"
  echo "==============================================================="

  # Run the selected tool with the ralph prompt
  if [[ "$TOOL" == "amp" ]]; then
    OUTPUT=$(cat "$SCRIPT_DIR/prompt.md" | amp --dangerously-allow-all 2>&1 | tee /dev/stderr) || true
  else
    # Claude Code: use --dangerously-skip-permissions for autonomous operation
    OUTPUT=$(claude --dangerously-skip-permissions --print < "$SCRIPT_DIR/CLAUDE.md" 2>&1 | tee /dev/stderr) || true
  fi

  # Check for completion signal
  if echo "$OUTPUT" | grep -q "<promise>COMPLETE</promise>"; then
    echo ""
    echo "Ralph completed all tasks!"
    echo "Completed at iteration $i of $MAX_ITERATIONS"
    exit 0
  fi

  echo "Iteration $i complete. Continuing..."
  sleep 2
done

echo ""
echo "Ralph reached max iterations ($MAX_ITERATIONS) without completing all tasks."
echo "Check $PROGRESS_FILE for status."
exit 1
```

---

## PRD JSON Format

Example `prd.json`:

```json
{
  "project": "MyApp",
  "branchName": "ralph/task-priority",
  "description": "Task Priority System - Add priority levels to tasks",
  "userStories": [
    {
      "id": "US-001",
      "title": "Add priority field to database",
      "description": "As a developer, I need to store task priority so it persists across sessions.",
      "acceptanceCriteria": [
        "Add priority column to tasks table: 'high' | 'medium' | 'low' (default 'medium')",
        "Generate and run migration successfully",
        "Typecheck passes"
      ],
      "priority": 1,
      "passes": false,
      "notes": ""
    },
    {
      "id": "US-002",
      "title": "Display priority indicator on task cards",
      "description": "As a user, I want to see task priority at a glance.",
      "acceptanceCriteria": [
        "Each task card shows colored priority badge (red=high, yellow=medium, gray=low)",
        "Priority visible without hovering or clicking",
        "Typecheck passes",
        "Verify in browser using dev-browser skill"
      ],
      "priority": 2,
      "passes": false,
      "notes": ""
    },
    {
      "id": "US-003",
      "title": "Add priority selector to task edit",
      "description": "As a user, I want to change a task's priority when editing it.",
      "acceptanceCriteria": [
        "Priority dropdown in task edit modal",
        "Shows current priority as selected",
        "Saves immediately on selection change",
        "Typecheck passes",
        "Verify in browser using dev-browser skill"
      ],
      "priority": 3,
      "passes": false,
      "notes": ""
    },
    {
      "id": "US-004",
      "title": "Filter tasks by priority",
      "description": "As a user, I want to filter the task list to see only high-priority items.",
      "acceptanceCriteria": [
        "Filter dropdown with options: All | High | Medium | Low",
        "Filter persists in URL params",
        "Empty state message when no tasks match filter",
        "Typecheck passes",
        "Verify in browser using dev-browser skill"
      ],
      "priority": 4,
      "passes": false,
      "notes": ""
    }
  ]
}
```

---

## Agent Prompt (Core Process)

The agent follows a structured cycle:

1. Read project requirements from `prd.json` and progress from `progress.txt`
2. Verify correct git branch alignment
3. Select the highest-priority incomplete user story
4. Implement the story with quality checks (typecheck, lint, test)
5. Commit with standardized messaging format: `feat: [Story ID] - [Story Title]`
6. Update documentation and mark story as complete
7. Append progress entry with:
   - Date and story ID
   - Implementation details
   - Changed files
   - Learnings section documenting discovered patterns, gotchas, and useful context

### Progress Tracking

Append timestamped entries recording implementation details, changed files, and learnings—never replace existing entries.

### Pattern Consolidation

Maintain a "Codebase Patterns" section at the top of `progress.txt` documenting reusable conventions discovered during implementation.

### AGENTS.md Updates

Document non-obvious patterns in module-specific AGENTS.md files:
- API conventions
- Dependencies
- Testing requirements
- Gotchas

Focus on reusable knowledge, not story-specific details.

---

## Key Project Files

| File | Purpose |
|------|---------|
| `ralph.sh` | Bash orchestration loop |
| `prompt.md` | Amp-specific system instructions |
| `CLAUDE.md` | Claude Code system instructions |
| `prd.json` | Task status tracker |
| `prd.json.example` | Reference format |
| `progress.txt` | Cumulative iteration notes |
| `skills/prd/` | PRD generation automation |
| `skills/ralph/` | Format conversion automation |
| `flowchart/` | Interactive visualization (React-based) |

---

## Debugging Commands

```bash
# View story completion status
cat prd.json | jq '.userStories[] | {id, title, passes}'

# Review accumulated knowledge
cat progress.txt

# Examine iteration commits
git log --oneline -10
```

---

## Customization

After copying prompt templates to your project, enhance them with:
- Project-specific quality-check commands
- Codebase naming conventions and patterns
- Stack-specific gotchas and workarounds

---

## Archiving

Ralph automatically archives completed runs under `archive/YYYY-MM-DD-feature-name/` when starting a new feature with a different branch name.

---

## Key Insights for Pandora

This pattern is relevant for Pandora because it demonstrates:

1. **Stateless iteration with state in documents** - Each AI instance is fresh, but state persists in structured files (like our `context.md` pattern)

2. **Progressive task completion** - Work through prioritized stories one at a time, marking progress

3. **Quality gates as feedback** - Use typecheck/tests to validate before committing (similar to our validation phase)

4. **Documentation as memory** - AGENTS.md files accumulate knowledge across iterations (similar to our obsidian_memory)

5. **Structured PRD format** - JSON with user stories, acceptance criteria, and pass/fail status

---

## License

MIT
